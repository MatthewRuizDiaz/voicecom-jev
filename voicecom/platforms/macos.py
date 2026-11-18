"""macOS automation: Accessibility (AX) API for windows and elements, Quartz events for input."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from urllib.parse import quote_plus

import ApplicationServices as AX
import Quartz
from AppKit import NSURL, NSApplication, NSDate, NSRunLoop, NSScreen, NSWorkspace

NS_ACCESSORY = 1  # NSApplicationActivationPolicyAccessory: no Dock icon, may still show panels

from .base import Automation, Element

# US-layout virtual key codes.
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
    "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21,
    "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31,
    "u": 32, "[": 33, "i": 34, "p": 35, "enter": 36, "l": 37, "j": 38, "'": 39, "k": 40,
    ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "tab": 48, "space": 49,
    "`": 50, "backspace": 51, "escape": 53, "f5": 96, "f6": 97, "f7": 98, "f3": 99, "f8": 100,
    "f9": 101, "f11": 103, "f10": 109, "f12": 111, "home": 115, "pageup": 116, "delete": 117,
    "f4": 118, "end": 119, "f2": 120, "pagedown": 121, "f1": 122, "left": 123, "right": 124,
    "down": 125, "up": 126,
}
MODIFIERS = {
    "cmd": Quartz.kCGEventFlagMaskCommand,
    "shift": Quartz.kCGEventFlagMaskShift,
    "alt": Quartz.kCGEventFlagMaskAlternate,
    "ctrl": Quartz.kCGEventFlagMaskControl,
}

CLICKABLE_ROLES = {
    "AXButton", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXCheckBox", "AXRadioButton",
    "AXPopUpButton", "AXMenuButton", "AXDisclosureTriangle", "AXTab", "AXComboBox",
    "AXTextField", "AXSearchField", "AXCell", "AXRow",
}
CHROMIUM_HINTS = ("chrome", "chromium", "brave", "edge", "arc", "electron", "slack", "discord",
                  "code", "cursor", "notion", "spotify", "vivaldi", "opera")

BROWSERS = ("safari", "chrome", "chromium", "brave", "arc", "firefox", "edge", "opera", "vivaldi",
            "orion", "zen", "dia", "duckduckgo")

# Typing into one of these (or into nothing) goes nowhere useful: lists jump to the typed letter.
NOT_TYPABLE_ROLES = {"AXList", "AXOutline", "AXTable", "AXBrowser", "AXApplication", "AXWindow"}

# macOS's system web search provider (System Settings / Safari "Search engine") -> query URL.
SEARCH_URLS = {
    "com.google": "https://www.google.com/search?q={}",
    "com.duckduckgo": "https://duckduckgo.com/?q={}",
    "com.bing": "https://www.bing.com/search?q={}",
    "com.yahoo": "https://search.yahoo.com/search?p={}",
    "org.ecosia": "https://www.ecosia.org/search?q={}",
    "com.ecosia": "https://www.ecosia.org/search?q={}",
}

APP_DIRS = ["/Applications", "/Applications/Utilities", "/System/Applications",
            "/System/Applications/Utilities", str(Path.home() / "Applications")]


def _attr(el, name):
    err, value = AX.AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def _osascript(script: str) -> str:
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return out.stdout.strip()


class MacAutomation(Automation):
    def __init__(self, warn: bool = True):
        # Using AppKit makes the Python process a Dock app that bounces forever; voicecom is a background tool.
        NSApplication.sharedApplication().setActivationPolicy_(NS_ACCESSORY)
        if warn and not AX.AXIsProcessTrusted():
            print("! Accessibility permission is missing: clicking, typing and window snapping won't work.\n"
                  "  Run: .venv/bin/python -m voicecom --check")

    # ---------- read-only ----------
    def _front(self):
        # NSWorkspace only learns about app switches when the run loop runs, and this process never
        # runs one; without this pump the answer stays stuck on whatever was in front at startup.
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.01))
        return NSWorkspace.sharedWorkspace().frontmostApplication()

    def frontmost_app(self) -> str:
        app = self._front()
        return str(app.localizedName()) if app else ""

    def installed_apps(self) -> list[str]:
        running = [str(a.localizedName()) for a in NSWorkspace.sharedWorkspace().runningApplications()
                   if a.activationPolicy() == 0 and a.localizedName()]
        found = []
        for d in APP_DIRS:
            if os.path.isdir(d):
                found += [f[:-4] for f in os.listdir(d) if f.endswith(".app")]
        # Running apps first, so they survive the 255-option cap.
        return list(dict.fromkeys(running + sorted(found, key=str.lower)))

    def _focused_window(self):
        app = self._front()
        if app is None:
            return None, None
        app_el = AX.AXUIElementCreateApplication(app.processIdentifier())
        AX.AXUIElementSetMessagingTimeout(app_el, 0.5)
        name = str(app.localizedName() or "").lower()
        if any(h in name for h in CHROMIUM_HINTS):
            # Chromium/Electron only build their web accessibility tree when asked.
            AX.AXUIElementSetAttributeValue(app_el, "AXManualAccessibility", True)
        if "safari" in name:
            AX.AXUIElementSetAttributeValue(app_el, "AXEnhancedUserInterface", True)
        return app_el, _attr(app_el, "AXFocusedWindow")

    def clickable_elements(self, max_nodes: int = 4000, budget_s: float = 2.0) -> list[Element]:
        _, window = self._focused_window()
        if window is None:
            return []
        out: list[Element] = []
        seen: set[tuple[str, str]] = set()
        stack = [(window, 0)]
        start, visited = time.time(), 0
        while stack and visited < max_nodes and time.time() - start < budget_s:
            el, depth = stack.pop()
            visited += 1
            role = _attr(el, "AXRole") or ""
            if role in CLICKABLE_ROLES:
                label = self._label(el)
                if label and (role, label) not in seen:
                    seen.add((role, label))
                    out.append(Element(label=label, role=role.removeprefix("AX"), handle=el))
            if depth < 60:
                children = _attr(el, "AXChildren") or []
                stack.extend((c, depth + 1) for c in reversed(list(children)))
        return out

    def _label(self, el) -> str:
        for name in ("AXTitle", "AXDescription", "AXValue", "AXPlaceholderValue", "AXHelp"):
            v = _attr(el, name)
            if isinstance(v, str) and v.strip():
                return " ".join(v.split())[:80]
        # Links and cells often carry their text in a child.
        for child in list(_attr(el, "AXChildren") or [])[:4]:
            for name in ("AXValue", "AXTitle", "AXDescription"):
                v = _attr(child, name)
                if isinstance(v, str) and v.strip():
                    return " ".join(v.split())[:80]
        return ""

    def get_volume(self) -> int:
        try:
            return int(_osascript("output volume of (get volume settings)"))
        except ValueError:
            return 50

    # ---------- actions ----------
    def open_app(self, name: str) -> None:
        if subprocess.run(["open", "-a", name], capture_output=True).returncode != 0:
            raise RuntimeError(f"no app called {name!r} is installed")

    def quit_app(self, name: str) -> None:
        _osascript(f'tell application "{name}" to quit')

    def click(self, element: Element) -> None:
        if AX.AXUIElementPerformAction(element.handle, "AXPress") == 0:
            return
        # Fallback: a real mouse click at the element's center.
        pos, size = _attr(element.handle, "AXPosition"), _attr(element.handle, "AXSize")
        if pos is None or size is None:
            raise RuntimeError(f"can't press {element.label!r}")
        _, p = AX.AXValueGetValue(pos, AX.kAXValueCGPointType, None)
        _, s = AX.AXValueGetValue(size, AX.kAXValueCGSizeType, None)
        point = Quartz.CGPointMake(p.x + s.width / 2, p.y + s.height / 2)
        for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
            ev = Quartz.CGEventCreateMouseEvent(None, kind, point, Quartz.kCGMouseButtonLeft)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    def scroll(self, notches: int) -> None:
        # Wheel events are positive for "up"; post one 3-line notch at a time so it feels smooth.
        step = -1 if notches > 0 else 1
        for _ in range(abs(notches)):
            ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, step * 3)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            time.sleep(0.015)

    def press(self, keys: list[str]) -> None:
        mods = [k for k in keys if k in MODIFIERS]
        main = [k for k in keys if k not in MODIFIERS]
        if not main or main[-1] not in KEYCODES:
            raise ValueError(f"unknown key in {keys}")
        flags = 0
        for m in mods:
            flags |= MODIFIERS[m]
        code = KEYCODES[main[-1]]
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
            Quartz.CGEventSetFlags(ev, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            time.sleep(0.01)

    def type_text(self, text: str) -> None:
        err, focused = AX.AXUIElementCopyAttributeValue(AX.AXUIElementCreateSystemWide(), "AXFocusedUIElement", None)
        role = _attr(focused, "AXRole") if focused is not None else None
        if focused is None or role in NOT_TYPABLE_ROLES:
            raise RuntimeError(f"nothing to type into in {self.frontmost_app()}: click into a text field first")
        for i in range(0, len(text), 20):  # the API takes at most 20 UTF-16 units per event
            chunk = text[i:i + 20]
            for down in (True, False):
                ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
                Quartz.CGEventKeyboardSetUnicodeString(ev, len(chunk), chunk)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            time.sleep(0.005)

    def snap_window(self, where: str) -> None:
        _, window = self._focused_window()
        if window is None:
            raise RuntimeError("no focused window (is Accessibility permission granted?)")
        screen = NSScreen.mainScreen()
        full, vis = screen.frame(), screen.visibleFrame()
        # AppKit's origin is bottom-left; AX's is top-left.
        top = full.size.height - (vis.origin.y + vis.size.height)
        x, w, h = vis.origin.x, vis.size.width, vis.size.height
        if where == "left":
            w = w / 2
        elif where == "right":
            x, w = x + w / 2, w / 2
        pos = AX.AXValueCreate(AX.kAXValueCGPointType, Quartz.CGPointMake(x, top))
        size = AX.AXValueCreate(AX.kAXValueCGSizeType, Quartz.CGSizeMake(w, h))
        AX.AXUIElementSetAttributeValue(window, "AXPosition", pos)
        AX.AXUIElementSetAttributeValue(window, "AXSize", size)

    def set_volume(self, percent: int) -> None:
        _osascript(f"set volume output volume {max(0, min(100, int(percent)))}")

    def toggle_mute(self) -> None:
        _osascript("set volume output muted not (output muted of (get volume settings))")

    def search_url(self, query: str) -> str:
        out = subprocess.run(["defaults", "read", "-g", "NSPreferredWebServices"], capture_output=True, text=True).stdout
        for provider, template in SEARCH_URLS.items():
            if f'"{provider}"' in out or f"= {provider};" in out:
                return template.format(quote_plus(query))
        return super().search_url(query)

    def open_url(self, url: str) -> None:
        subprocess.run(["open", url], check=False)

    def _menu_item(self, app_name: str, title: str):
        """Find a menu bar item by title (e.g. "New Tab") in a running app, or None."""
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if str(app.localizedName() or "") != app_name:
                continue
            bar = _attr(AX.AXUIElementCreateApplication(app.processIdentifier()), "AXMenuBar")
            for top in list(_attr(bar, "AXChildren") or []) if bar is not None else []:
                for menu in list(_attr(top, "AXChildren") or []):
                    for item in list(_attr(menu, "AXChildren") or []):
                        if _attr(item, "AXTitle") == title:
                            return item
        return None

    def default_browser(self) -> str:
        url = NSWorkspace.sharedWorkspace().URLForApplicationToOpenURL_(NSURL.URLWithString_("https://example.com"))
        return Path(str(url.path())).stem if url else "Safari"

    def new_tab_target(self) -> str:
        front = self.frontmost_app()
        if any(b in front.lower() for b in BROWSERS) or self._menu_item(front, "New Tab") is not None:
            return front
        return self.default_browser()

    def new_tab(self, app: str) -> None:
        if app != self.frontmost_app():
            subprocess.run(["open", "-a", app], check=False)
            deadline = time.time() + 3
            while self.frontmost_app() != app and time.time() < deadline:
                time.sleep(0.02)
            time.sleep(0.1)  # let the window take keyboard focus
        item = self._menu_item(app, "New Tab")
        if item is None or AX.AXUIElementPerformAction(item, "AXPress") != 0:
            self.press(["cmd", "t"])

    def close_tab(self) -> None:
        self.press(["cmd", "w"])

    def say(self, text: str) -> None:
        subprocess.Popen(["say", "-r", "220", text])
