"""The glass overlay (macOS): a small panel top-right that shows listening, thinking, and the decided Steps.

AppKit only draws from the main thread, so every public method hops there with AppHelper.callAfter and
returns at once: the speech-to-action path never waits on drawing. The panel never takes focus or
clicks, so actions still land in the app you were using.
"""

from __future__ import annotations

import os
import signal
import sys
import math
import threading
from typing import Callable

import objc
from AppKit import (NSApplication, NSBackingStoreBuffered, NSButton, NSColor, NSFont, NSImage,
                    NSLineBreakByTruncatingTail, NSMakeRect, NSPanel, NSProgressIndicator, NSScreen,
                    NSTrackingArea,
                    NSStackView, NSTextField, NSView, NSVisualEffectView)
from PyObjCTools import AppHelper

from .view import Card, View

WIDTH = 340
INNER = WIDTH - 32  # inside the 16pt side insets
MARGIN = 12  # from the screen's top-right corner, under the menu bar
SHOW_S = 4.2  # how long a result stays: long enough to check a Chain at a glance
CONFIRM_S = 30.0
BAR_W = 64

# AppKit constants (spelled out so older pyobjc builds without the newer names still work)
BORDERLESS, NONACTIVATING = 0, 1 << 7
STATUS_LEVEL = 25
ALL_SPACES, STATIONARY, IGNORES_CYCLE, FULLSCREEN_AUX = 1 << 0, 1 << 4, 1 << 6, 1 << 8
VERTICAL, HORIZONTAL = 1, 0
ALIGN_LEADING, ALIGN_CENTER_Y = 1, 10
SPINNER = 1
HUD_MATERIAL, BEHIND_WINDOW, ACTIVE = 13, 0, 1
TRACK_ENTER_EXIT, TRACK_ALWAYS, TRACK_VISIBLE_RECT = 0x01, 0x80, 0x200

OUTCOME_TEXT = {"ran": "Ran", "confirm": "Needs your OK", "ignored": "Ignored", "failed": "Failed",
                "cancelled": "Cancelled"}


def _color(outcome: str):
    return {"ran": NSColor.systemGreenColor(), "confirm": NSColor.systemOrangeColor(),
            "failed": NSColor.systemRedColor()}.get(outcome, NSColor.secondaryLabelColor())


def _label(text: str, size: float = 13, weight: float = 0.0, color=None, wrap: bool = False, mono: bool = False):
    f = NSTextField.labelWithString_(text)
    f.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight) if mono
               else NSFont.systemFontOfSize_weight_(size, weight))
    f.setTextColor_(color or NSColor.labelColor())
    if wrap:
        f.setPreferredMaxLayoutWidth_(INNER)
        f.setMaximumNumberOfLines_(3)
    else:
        f.setLineBreakMode_(NSLineBreakByTruncatingTail)
    return f


def _fixed(view, w: float | None = None, h: float | None = None):
    view.setTranslatesAutoresizingMaskIntoConstraints_(False)
    if w is not None:
        view.widthAnchor().constraintEqualToConstant_(w).setActive_(True)
    if h is not None:
        view.heightAnchor().constraintEqualToConstant_(h).setActive_(True)
    return view


def _layer_view(w: float, h: float, color, radius: float | None = None, fixed: bool = True):
    v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    if fixed:
        _fixed(v, w, h)
    v.setWantsLayer_(True)
    v.layer().setCornerRadius_(h / 2 if radius is None else radius)
    v.layer().setBackgroundColor_(color.CGColor())
    return v


def _row(*views, spacing: float = 8):
    row = NSStackView.stackViewWithViews_(list(views))
    row.setOrientation_(HORIZONTAL)
    row.setAlignment_(ALIGN_CENTER_Y)
    row.setSpacing_(spacing)
    return row


def _spacer():
    v = NSView.alloc().init()
    v.setContentHuggingPriority_forOrientation_(1, HORIZONTAL)
    return v


class _Root(NSView):
    """The panel's content: tells the Overlay when the pointer is over it, and owns the close button."""

    def initWithOwner_(self, owner):
        self = objc.super(_Root, self).initWithFrame_(NSMakeRect(0, 0, WIDTH, 60))
        if self is None:
            return None
        self.owner, self.area = owner, None
        return self

    def updateTrackingAreas(self):
        if self.area is not None:
            self.removeTrackingArea_(self.area)
        # ActiveAlways: voicecom is never the active app, and hover must still work.
        self.area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), TRACK_ENTER_EXIT | TRACK_ALWAYS | TRACK_VISIBLE_RECT, self, None)
        self.addTrackingArea_(self.area)
        objc.super(_Root, self).updateTrackingAreas()

    def mouseEntered_(self, event):
        self.owner._hover(True)

    def mouseExited_(self, event):
        self.owner._hover(False)

    def acceptsFirstMouse_(self, event):
        return True

    def dismiss_(self, sender):
        self.owner._fade(self.owner._gen)


class Overlay(View):
    def __init__(self, act: float = 0.80, ignore: float = 0.40):
        self.act, self.ignore = act, ignore  # thresholds, for the confidence words
        self._gen = 0  # bumps on every new state, so stale timers do nothing
        self._hovering = False
        self._closable = False
        AppHelper.callAfter(self._build)

    # ---------- called from any thread ----------
    def listening(self, level: Callable[[], float]) -> None:
        AppHelper.callAfter(self._show_listening, level)

    def thinking(self, transcript: str | None = None) -> None:
        AppHelper.callAfter(self._show_thinking, transcript)

    def result(self, card: Card) -> None:
        AppHelper.callAfter(self._show_result, card)

    def hide(self) -> None:
        AppHelper.callAfter(lambda: self._fade(self._gen))

    # ---------- main thread ----------
    def _build(self) -> None:
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, 60), BORDERLESS | NONACTIVATING, NSBackingStoreBuffered, False)
        panel.setLevel_(STATUS_LEVEL)
        panel.setCollectionBehavior_(ALL_SPACES | STATIONARY | IGNORES_CYCLE | FULLSCREEN_AUX)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setReleasedWhenClosed_(False)
        panel.setAcceptsMouseMovedEvents_(True)

        self.stack = NSStackView.alloc().init()
        self.stack.setOrientation_(VERTICAL)
        self.stack.setAlignment_(ALIGN_LEADING)
        self.stack.setSpacing_(7)
        self.stack.setEdgeInsets_((12, 16, 12, 16))
        _fixed(self.stack, WIDTH)

        root = _Root.alloc().initWithOwner_(self)
        root.setTranslatesAutoresizingMaskIntoConstraints_(False)
        root.addSubview_(self.stack)
        for a, b in (("topAnchor", "topAnchor"), ("bottomAnchor", "bottomAnchor"),
                     ("leadingAnchor", "leadingAnchor"), ("trailingAnchor", "trailingAnchor")):
            getattr(self.stack, a)().constraintEqualToAnchor_(getattr(root, b)()).setActive_(True)

        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_("xmark.circle.fill", "Dismiss")
        close = NSButton.buttonWithImage_target_action_(icon, root, "dismiss:")
        close.setBordered_(False)
        close.setContentTintColor_(NSColor.secondaryLabelColor())
        close.setTranslatesAutoresizingMaskIntoConstraints_(False)
        close.setHidden_(True)
        root.addSubview_(close)
        close.topAnchor().constraintEqualToAnchor_constant_(root.topAnchor(), 9).setActive_(True)
        close.trailingAnchor().constraintEqualToAnchor_constant_(root.trailingAnchor(), -10).setActive_(True)
        self.close, self.root = close, root

        glass_cls = objc.lookUpClass("NSGlassEffectView") if _has("NSGlassEffectView") else None
        if glass_cls is not None:  # Liquid Glass, macOS 26+
            glass = glass_cls.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 60))
            glass.setCornerRadius_(18)
            glass.setContentView_(root)
        else:  # frosted blur on older macOS
            glass = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 60))
            glass.setMaterial_(HUD_MATERIAL)
            glass.setBlendingMode_(BEHIND_WINDOW)
            glass.setState_(ACTIVE)
            glass.setWantsLayer_(True)
            glass.layer().setCornerRadius_(18)
            glass.layer().setMasksToBounds_(True)
            glass.addSubview_(root)
        self.glass, self.panel = glass, panel
        panel.setContentView_(glass)

    def _hover(self, inside: bool) -> None:
        self._hovering = inside  # also pauses the countdown, so you can read without racing it
        self.close.setHidden_(not (inside and self._closable))

    def _set(self, views: list, closable: bool = False) -> None:
        """Swap the panel's contents, size it to fit, pin it top-right, and show it without focus."""
        self._gen += 1
        self._closable = closable
        self.close.setHidden_(not (closable and self._hovering))
        for v in list(self.stack.arrangedSubviews()):
            self.stack.removeArrangedSubview_(v)
            v.removeFromSuperview()
        for v in views:
            self.stack.addArrangedSubview_(v)
        self.stack.layoutSubtreeIfNeeded()
        h = self.stack.fittingSize().height
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + screen.size.width - WIDTH - MARGIN
        y = screen.origin.y + screen.size.height - h - MARGIN
        self.panel.setFrame_display_(NSMakeRect(x, y, WIDTH, h), True)
        self.glass.setFrame_(NSMakeRect(0, 0, WIDTH, h))
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()

    def _show_listening(self, level: Callable[[], float]) -> None:
        """The word "Listening" in the same style as "Thinking…", with a short level meter beside it."""
        meter_w = 56
        track = _layer_view(meter_w, 4, NSColor.tertiaryLabelColor())
        fill = _layer_view(4, 4, NSColor.secondaryLabelColor(), fixed=False)
        track.addSubview_(fill)

        self._set([_row(_label("Listening", 13, 0.4, NSColor.secondaryLabelColor()), track, spacing=10)])
        gen, rms_avg, shown = self._gen, [0.0], [0.0]

        def tick():
            if gen != self._gen:
                return
            # Average the raw loudness first, then map decibels (-55 room .. -20 speech) to 0..1 and
            # ease toward it, slowly up and more slowly down: it shows a voice, not each syllable.
            rms_avg[0] += ((level() or 0.0) - rms_avg[0]) * 0.25
            target = min(1.0, max(0.0, (20 * math.log10(rms_avg[0] + 1e-9) + 55) / 35))
            shown[0] += (target - shown[0]) * (0.12 if target > shown[0] else 0.04)
            fill.setFrame_(NSMakeRect(0, 0, max(4.0, meter_w * shown[0]), 4))
            AppHelper.callLater(1 / 30, tick)

        tick()

    def _show_thinking(self, transcript: str | None) -> None:
        spin = _fixed(NSProgressIndicator.alloc().init(), 14, 14)
        spin.setStyle_(SPINNER)
        spin.setControlSize_(1)
        spin.startAnimation_(None)
        views = [_row(spin, _label("Thinking…", 13, 0.4, NSColor.secondaryLabelColor()))]
        if transcript:
            views.append(_label(f"“{transcript}”", 13, wrap=True))
        self._set(views)

    def _confidence(self, p: float) -> tuple[str, object]:
        """Jev's probability as a word and colour that say what voicecom does with it."""
        if p >= 0.95:
            return "Certain", NSColor.systemGreenColor()
        if p >= self.act:
            return "Sure", NSColor.systemGreenColor()
        if p >= self.ignore:
            return "Unsure", NSColor.systemOrangeColor()
        return "Guessing", NSColor.secondaryLabelColor()

    def _step_row(self, label: str, p: float, dim: bool):
        word, color = self._confidence(p)
        name = _fixed(_label(label, 13, 0.0, NSColor.secondaryLabelColor() if dim else None), INNER - BAR_W - 64 - 16)
        track = _layer_view(BAR_W, 6, NSColor.tertiaryLabelColor())
        track.addSubview_(_layer_view(max(6.0, BAR_W * p), 6, color, fixed=False))
        # A tick where "sure enough to just do it" starts, so the bar reads against the rule.
        track.addSubview_(_layer_view(1.5, 10, NSColor.labelColor().colorWithAlphaComponent_(0.55),
                                      radius=0, fixed=False))
        track.subviews()[-1].setFrame_(NSMakeRect(BAR_W * self.act - 0.75, -2, 1.5, 10))
        track.layer().setMasksToBounds_(False)
        row = _row(name, track, _fixed(_label(word, 12, 0.3, color), 64))
        if dim:
            row.setAlphaValue_(0.45)
        return row

    def _show_result(self, card: Card) -> None:
        color = _color(card.outcome)
        status = OUTCOME_TEXT.get(card.outcome, card.outcome)
        if card.outcome in ("ignored", "failed") and card.detail:
            status += f" · {card.detail}"
        head = [_label(status, 13, 0.6, color), _spacer()]
        if card.total_s:
            head.append(_label(f"{card.total_s:.2f}s", 11, 0.0, NSColor.secondaryLabelColor(), mono=True))
        head.append(_fixed(NSView.alloc().init(), 18, 1))  # room for the close button
        views = [_fixed(_row(*head), INNER), _label(f"“{card.transcript}”", 13, wrap=True)]
        if card.steps:
            # A column header in plain words is the key: what the bar means, read once.
            views.append(_fixed(_row(_label("Steps", 11, 0.5, NSColor.secondaryLabelColor()), _spacer(),
                                     _label("How sure Jev is", 11, 0.5, NSColor.secondaryLabelColor())), INNER))
            views += [self._step_row(s.label, s.p, s.dim) for s in card.steps]

        # Countdown: a thin bar that empties toward the left; the panel goes when it's gone.
        seconds = CONFIRM_S if card.outcome == "confirm" else SHOW_S
        timer = _layer_view(INNER, 2, NSColor.quaternaryLabelColor())
        left = _layer_view(INNER, 2, NSColor.secondaryLabelColor(), fixed=False)
        timer.addSubview_(left)
        views.append(timer)
        self._set(views, closable=True)

        gen, remaining = self._gen, [seconds]

        def tick():
            if gen != self._gen:
                return
            if not self._hovering:
                remaining[0] -= 1 / 30
            left.setFrame_(NSMakeRect(0, 0, max(0.0, INNER * remaining[0] / seconds), 2))
            if remaining[0] <= 0:
                return self._fade(gen)
            AppHelper.callLater(1 / 30, tick)

        tick()

    def _fade(self, gen: int) -> None:
        if gen != self._gen:
            return
        self._gen += 1  # stop any countdown or meter
        self._closable = False
        self.close.setHidden_(True)
        self.panel.animator().setAlphaValue_(0.0)
        gen = self._gen
        AppHelper.callLater(0.35, lambda: gen == self._gen and self.panel.orderOut_(None))


def _has(name: str) -> bool:
    try:
        objc.lookUpClass(name)
        return True
    except objc.nosuchclass_error:
        return False


def run_app(work: Callable[[], None]) -> None:
    """Run AppKit on the main thread (it must own it to draw) and `work` (listening, typed input)
    on a background thread. Ctrl+C or the end of `work` quits."""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)  # accessory: no Dock icon

    def worker():
        try:
            work()
        finally:
            sys.stdout.flush()  # stopping AppKit exits the process without flushing Python's buffers
            AppHelper.callAfter(AppHelper.stopEventLoop)

    # Python only runs signal handlers when the main thread runs Python code, and NSApp.run() sits in C,
    # so wake it every 0.2s; Ctrl+C then quits straight away.
    def on_sigint(*_):
        sys.stdout.flush()
        os._exit(130)

    def wake():
        AppHelper.callLater(0.2, wake)

    signal.signal(signal.SIGINT, on_sigint)
    wake()
    # Start work only once AppKit has finished launching: a panel shown before that makes macOS
    # activate this process, stealing focus from the app the user is working in.
    AppHelper.callAfter(lambda: threading.Thread(target=worker, daemon=True).start())
    AppHelper.runEventLoop(installInterrupt=False)
