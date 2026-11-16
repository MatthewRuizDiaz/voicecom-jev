"""Check (and optionally request) the three macOS permissions voicecom needs.

macOS grants these to the *app the command runs from* (Terminal, iTerm, Claude...), not to Python,
so we also work out which app that is by walking up the process tree.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass

import ApplicationServices as AX
import AVFoundation as AV
import Quartz

SETTINGS = "System Settings > Privacy & Security > {}"
PANES = {  # deep links into the right System Settings list
    "Microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "Input Monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "Accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
}


@dataclass
class Permission:
    name: str
    status: str  # "granted", "denied", "not granted", "not asked yet", "restricted"
    needed_for: str

    @property
    def ok(self) -> bool:
        return self.status == "granted"


def host_app() -> str:
    """The outermost .app bundle among this process's ancestors, i.e. who macOS asks about."""
    pid, found = os.getpid(), None
    while pid > 1:
        out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True).stdout
        m = re.match(r"\s*(\d+)\s+(.*)", out)
        if not m:
            break
        ppid, path = int(m.group(1)), m.group(2)
        bundle = re.search(r"/([^/]+)\.app(/|$)", path)  # first .app in the path is the outer bundle
        if bundle:
            found = bundle.group(1)
        pid = ppid
    return found or "your terminal app"


def _microphone(prompt: bool) -> str:
    kind = AV.AVMediaTypeAudio
    status = AV.AVCaptureDevice.authorizationStatusForMediaType_(kind)
    if status == 0 and prompt:  # not determined: show the system prompt and wait for the answer
        done = threading.Event()
        AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(kind, lambda granted: done.set())
        done.wait(60)
        status = AV.AVCaptureDevice.authorizationStatusForMediaType_(kind)
    return {0: "not asked yet", 1: "restricted", 2: "denied", 3: "granted"}.get(status, "unknown")


def _input_monitoring(prompt: bool) -> str:
    if Quartz.CGPreflightListenEventAccess():
        return "granted"
    if prompt:
        Quartz.CGRequestListenEventAccess()  # adds the app to the list and shows the prompt once
    return "not granted"


def _accessibility(prompt: bool) -> str:
    trusted = AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: bool(prompt)})
    return "granted" if trusted else "not granted"


def check(prompt: bool = True) -> list[Permission]:
    return [
        Permission("Microphone", _microphone(prompt), "recording while the push-to-talk key is held"),
        Permission("Input Monitoring", _input_monitoring(prompt), "noticing the push-to-talk key in any app"),
        Permission("Accessibility", _accessibility(prompt), "clicking, typing, scrolling and moving windows"),
    ]


def report(prompt: bool = True, open_settings: bool = True) -> bool:
    app = host_app()
    perms = check(prompt)
    print(f"Permissions for {app} (macOS grants them to the app you run voicecom from):\n")
    for p in perms:
        mark = "\033[32m✓\033[0m" if p.ok else "\033[31m✗\033[0m"
        print(f"  {mark} {p.name:17} {p.status:14} needed for {p.needed_for}")
    missing = [p for p in perms if not p.ok]
    if not missing:
        print("\nAll set. Run: .venv/bin/python -m voicecom")
        return True
    print(f"\nTo fix: turn on {app} in each list below (use + to add it if it isn't there), "
          f"then quit and reopen {app} and run this check again.")
    for p in missing:
        print(f"  - {SETTINGS.format(p.name)}")
    if open_settings:
        subprocess.run(["open", PANES[missing[0].name]], check=False)
        print(f"\nOpened the {missing[0].name} settings for you.")
    return False
