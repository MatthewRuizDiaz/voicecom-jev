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
from AppKit import (NSApplication, NSBackingStoreBuffered, NSColor, NSFont, NSLineBreakByTruncatingTail,
                    NSMakeRect, NSPanel, NSProgressIndicator, NSScreen,
                    NSStackView, NSTextField, NSView, NSVisualEffectView)
from PyObjCTools import AppHelper
from Quartz import CABasicAnimation

from .view import Card, View

WIDTH = 340
MARGIN = 12  # from the screen's top-right corner, under the menu bar
SHOW_S = 4.2  # how long a result stays: long enough to check a Chain at a glance
PILL_W = 120  # the listening state is just a dot and a meter, out of the way
METER_W = 72
CONFIRM_S = 30.0

# AppKit constants (spelled out so older pyobjc builds without the newer names still work)
BORDERLESS, NONACTIVATING = 0, 1 << 7
STATUS_LEVEL = 25
ALL_SPACES, STATIONARY, IGNORES_CYCLE, FULLSCREEN_AUX = 1 << 0, 1 << 4, 1 << 6, 1 << 8
VERTICAL, HORIZONTAL = 1, 0
ALIGN_LEADING, ALIGN_CENTER_Y = 1, 10
SPINNER = 1
HUD_MATERIAL, BEHIND_WINDOW, ACTIVE = 13, 0, 1

OUTCOME_TEXT = {"ran": "Ran", "confirm": "Needs OK", "ignored": "Ignored", "failed": "Failed",
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
        f.setPreferredMaxLayoutWidth_(WIDTH - 32)
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


def _bar(p: float, color):
    """A thin probability bar: a track with a filled part."""
    track = _fixed(NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 70, 5)), 70, 5)
    track.setWantsLayer_(True)
    track.layer().setCornerRadius_(2.5)
    track.layer().setBackgroundColor_(NSColor.tertiaryLabelColor().CGColor())
    fill = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, max(3.0, 70 * p), 5))
    fill.setWantsLayer_(True)
    fill.layer().setCornerRadius_(2.5)
    fill.layer().setBackgroundColor_(color.CGColor())
    track.addSubview_(fill)
    return track


def _row(*views, spacing: float = 8):
    row = NSStackView.stackViewWithViews_(list(views))
    row.setOrientation_(HORIZONTAL)
    row.setAlignment_(ALIGN_CENTER_Y)
    row.setSpacing_(spacing)
    return row


class Overlay(View):
    def __init__(self, act: float = 0.80):
        self.act = act  # the run threshold, for the key under the bars
        self._gen = 0  # bumps on every new state, so stale fade timers do nothing
        self._level_fn: Callable[[], float] | None = None
        AppHelper.callAfter(self._build)

    # ---------- called from any thread ----------
    def listening(self, level: Callable[[], float]) -> None:
        AppHelper.callAfter(self._show_listening, level)

    def thinking(self, transcript: str | None = None) -> None:
        AppHelper.callAfter(self._show_thinking, transcript)

    def result(self, card: Card) -> None:
        AppHelper.callAfter(self._show_result, card)

    def hide(self) -> None:
        AppHelper.callAfter(self._fade, self._gen)

    # ---------- main thread ----------
    def _build(self) -> None:
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, 60), BORDERLESS | NONACTIVATING, NSBackingStoreBuffered, False)
        panel.setLevel_(STATUS_LEVEL)
        panel.setCollectionBehavior_(ALL_SPACES | STATIONARY | IGNORES_CYCLE | FULLSCREEN_AUX)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)  # buttons arrive with #19
        panel.setHidesOnDeactivate_(False)
        panel.setReleasedWhenClosed_(False)

        self.stack = NSStackView.alloc().init()
        self.stack.setOrientation_(VERTICAL)
        self.stack.setAlignment_(ALIGN_LEADING)
        self.stack.setSpacing_(7)
        self.stack.setEdgeInsets_((12, 16, 12, 16))
        self.stack.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._width = self.stack.widthAnchor().constraintEqualToConstant_(WIDTH)
        self._width.setActive_(True)

        glass_cls = objc.lookUpClass("NSGlassEffectView") if _has("NSGlassEffectView") else None
        if glass_cls is not None:  # Liquid Glass, macOS 26+
            glass = glass_cls.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 60))
            glass.setCornerRadius_(18)
            glass.setContentView_(self.stack)
        else:  # frosted blur on older macOS
            glass = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 60))
            glass.setMaterial_(HUD_MATERIAL)
            glass.setBlendingMode_(BEHIND_WINDOW)
            glass.setState_(ACTIVE)
            glass.setWantsLayer_(True)
            glass.layer().setCornerRadius_(18)
            glass.layer().setMasksToBounds_(True)
            glass.addSubview_(self.stack)
        self.glass, self.panel = glass, panel
        panel.setContentView_(glass)

    def _set(self, views: list, width: float = WIDTH) -> None:
        """Swap the panel's contents, size it to fit, pin it top-right, and show it without focus."""
        self._gen += 1
        self._width.setConstant_(width)
        for v in list(self.stack.arrangedSubviews()):
            self.stack.removeArrangedSubview_(v)
            v.removeFromSuperview()
        for v in views:
            self.stack.addArrangedSubview_(v)
        self.stack.layoutSubtreeIfNeeded()
        h = self.stack.fittingSize().height
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + screen.size.width - width - MARGIN
        y = screen.origin.y + screen.size.height - h - MARGIN
        self.panel.setFrame_display_(NSMakeRect(x, y, width, h), True)
        self.glass.setFrame_(NSMakeRect(0, 0, width, h))
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()

    def _show_listening(self, level: Callable[[], float]) -> None:
        """A small pill: a softly pulsing red dot and a calm level meter. No text."""
        dot = _fixed(NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 8, 8)), 8, 8)
        dot.setWantsLayer_(True)
        dot.layer().setCornerRadius_(4)
        dot.layer().setBackgroundColor_(NSColor.systemRedColor().CGColor())
        pulse = CABasicAnimation.animationWithKeyPath_("opacity")
        pulse.setFromValue_(1.0)
        pulse.setToValue_(0.35)
        pulse.setDuration_(0.8)
        pulse.setAutoreverses_(True)
        pulse.setRepeatCount_(1e9)
        dot.layer().addAnimation_forKey_(pulse, "pulse")

        track = _fixed(NSView.alloc().initWithFrame_(NSMakeRect(0, 0, METER_W, 4)), METER_W, 4)
        track.setWantsLayer_(True)
        track.layer().setCornerRadius_(2)
        track.layer().setBackgroundColor_(NSColor.tertiaryLabelColor().CGColor())
        fill = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 4, 4))
        fill.setWantsLayer_(True)
        fill.layer().setCornerRadius_(2)
        fill.layer().setBackgroundColor_(NSColor.labelColor().colorWithAlphaComponent_(0.7).CGColor())
        track.addSubview_(fill)

        self._set([_row(dot, track, spacing=10)], width=PILL_W)
        gen, shown = self._gen, [0.0]

        def tick():
            if gen != self._gen:
                return
            rms = level() or 0.0
            # Loudness in decibels, -55 dB (room) to -20 dB (speech) -> 0..1, then eased: rises fast,
            # falls slowly, so the meter follows the voice instead of every syllable.
            target = min(1.0, max(0.0, (20 * math.log10(rms + 1e-9) + 55) / 35))
            shown[0] += (target - shown[0]) * (0.3 if target > shown[0] else 0.08)
            fill.setFrame_(NSMakeRect(0, 0, max(4.0, METER_W * shown[0]), 4))
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

    def _show_result(self, card: Card) -> None:
        color = _color(card.outcome)
        status = OUTCOME_TEXT.get(card.outcome, card.outcome)
        if card.outcome in ("ignored", "failed") and card.detail:
            status += f" · {card.detail}"
        views = [_label(status, 12, 0.5, color), _label(f"“{card.transcript}”", 13, wrap=True)]
        for s in card.steps:
            name = _fixed(_label(s.label, 12, 0.0, NSColor.secondaryLabelColor() if s.dim else None), WIDTH - 32 - 70 - 36 - 16)
            row = _row(name, _bar(s.p, color), _label(f"{s.p:.0%}", 11, 0.0, NSColor.secondaryLabelColor(), mono=True))
            if s.dim:
                row.setAlphaValue_(0.45)
            views.append(row)
        if card.steps:  # a key, so the bars make sense to someone who's never heard of Jev
            key = f"How sure Jev is of each step. Runs at {self.act:.0%}+, asks below that."
            views.append(_label(key, 10, 0.0, NSColor.tertiaryLabelColor(), wrap=True))
        if card.total_s:
            views.append(_label(f"{card.total_s:.2f}s total", 10, 0.0, NSColor.tertiaryLabelColor(), mono=True))
        self._set(views)
        gen = self._gen
        AppHelper.callLater(CONFIRM_S if card.outcome == "confirm" else SHOW_S, self._fade, gen)

    def _fade(self, gen: int) -> None:
        if gen != self._gen:
            return
        self.panel.animator().setAlphaValue_(0.0)
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
    threading.Thread(target=worker, daemon=True).start()
    AppHelper.runEventLoop(installInterrupt=False)
