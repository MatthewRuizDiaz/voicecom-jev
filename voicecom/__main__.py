"""voicecom-jev: hold a key, say a command, the computer does it.

    python -m voicecom                 # hold Right Option and speak
    python -m voicecom --dry-run       # decide and log, but don't touch anything
    python -m voicecom --text "open chrome" --text "scroll down"   # skip the mic
    python -m voicecom --repl          # type commands instead of speaking
    python -m voicecom --no-overlay    # terminal log only, no on-screen panel
"""

from __future__ import annotations

import argparse
import platform
import queue
import sys
import time

from . import parse
from .engine import Engine, Thresholds
from .jev import Jev
from .platforms import DryRun, check_permissions, get_automation
from .registry import REGISTRY
from .view import View

HOTKEYS = {"alt_r": "Right Option", "cmd_r": "Right Command", "ctrl_r": "Right Control",
           "f13": "F13", "f18": "F18", "alt": "Left Option"}


def main() -> None:
    ap = argparse.ArgumentParser(prog="voicecom", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="decide and log, but don't perform actions")
    ap.add_argument("--text", action="append", help="process this text instead of listening (repeatable)")
    ap.add_argument("--repl", action="store_true", help="type commands at a prompt instead of speaking")
    ap.add_argument("--hotkey", default="alt_r", choices=HOTKEYS, help="push-to-talk key (default: alt_r)")
    ap.add_argument("--whisper-model", default="base.en", help="faster-whisper model (tiny.en, base.en, small.en)")
    ap.add_argument("--model", default="jev-latest", help="TypeSafe model")
    ap.add_argument("--speak", action="store_true", help="also ask confirmations out loud")
    ap.add_argument("--notes-folder", metavar="NAME",
                    help="Notes folder for new notes (default: the folder you have open)")
    ap.add_argument("--no-overlay", action="store_true", help="don't show the on-screen panel (terminal log only)")
    ap.add_argument("--act", type=float, default=Thresholds.act, help="probability to run without asking")
    ap.add_argument("--ignore", type=float, default=Thresholds.ignore, help="probability below which to ignore")
    ap.add_argument("--list", action="store_true", help="list the commands and exit")
    ap.add_argument("--check", action="store_true",
                    help="check the Microphone, Input Monitoring and Accessibility permissions, "
                         "ask for any that are missing, and exit")
    ap.add_argument("--no-prompt", action="store_true", help="with --check: only report, don't ask or open Settings")
    args = ap.parse_args()

    if args.check:
        ok = check_permissions(prompt=not args.no_prompt, open_settings=not args.no_prompt)
        sys.exit(0 if ok else 1)

    if args.list:
        for c in REGISTRY.values():
            print(f"{c.name:16} {c.description}")
        return

    print(f"voicecom-jev on {platform.system()} {platform.mac_ver()[0] or platform.release()}"
          f"{' (dry run)' if args.dry_run else ''}: {len(REGISTRY)} commands")
    auto = get_automation(warn=not args.dry_run)
    auto.notes_folder = args.notes_folder
    if args.dry_run:
        auto = DryRun(auto)
    typed = args.text or args.repl
    use_overlay = platform.system() == "Darwin" and not args.no_overlay
    view = View()
    if use_overlay:
        from .overlay import Overlay
        view = Overlay(act=args.act, ignore=args.ignore)
    engine = Engine(auto, Jev(args.model), Thresholds(act=args.act, ignore=args.ignore),
                    speak=args.speak, dry_run=args.dry_run, view=view)
    lock = None if typed else _single_instance()  # noqa: F841  (held for the life of the process)

    def work() -> None:
        if args.text:
            for line in args.text:
                engine.handle(line)
                if engine.pending:  # no buttons to click in a script: answer at the keyboard
                    yes = input("  run it? [y/N] > ").strip().lower().startswith("y")
                    engine.confirm() if yes else engine.cancel()
                if use_overlay:
                    time.sleep(2.6)  # let the panel be seen before the next line (or exit)
        elif args.repl:
            try:
                while True:
                    engine.handle(input("say> "))
                    if engine.pending:
                        yes = input("  run it? [y/N] > ").strip().lower().startswith("y")
                        engine.confirm() if yes else engine.cancel()
            except EOFError:
                pass
        else:
            listen(engine, args, view)

    if use_overlay:
        from .overlay import run_app
        run_app(work)  # AppKit needs the main thread; work runs beside it
    else:
        try:
            work()
        except KeyboardInterrupt:
            pass


def _single_instance() -> object:
    """Two listeners would both act on every command ("hello" typed twice), so allow one."""
    import fcntl
    import os
    import tempfile

    lock = open(os.path.join(tempfile.gettempdir(), "voicecom.lock"), "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.seek(0)
        pid = lock.read().strip() or "?"
        sys.exit(f"voicecom is already running (pid {pid}). Stop it first with Ctrl+C in its window.")
    lock.truncate(0)
    lock.write(str(os.getpid()))
    lock.flush()
    return lock  # keep it open: the lock lasts as long as this process


def listen(engine: Engine, args, view: View) -> None:
    from pynput import keyboard

    from .stt import Recorder, Transcriber

    if platform.system() == "Darwin":
        from .platforms.macos_permissions import check

        missing = [p.name for p in check(prompt=False) if not p.ok]
        if missing:
            print(f"! Missing permissions: {', '.join(missing)}. The push-to-talk key or mic may not work.\n"
                  "  Run: .venv/bin/python -m voicecom --check", flush=True)

    print(f"Loading speech model ({args.whisper_model})...", flush=True)
    stt = Transcriber(args.whisper_model)
    rec = Recorder()
    rec.open()  # one stream for the whole session; see Recorder
    target = getattr(keyboard.Key, args.hotkey)
    audio_q: queue.Queue = queue.Queue()
    held = {"down": False, "screen": None}

    def on_press(key):
        if key == target and not held["down"]:
            held["down"] = True
            # Read the front window's labels while you speak, as hints for Whisper (issue #24).
            held["screen"] = engine.pool.submit(engine.auto.clickable_elements)
            rec.start()
            view.listening(lambda: rec.level)
            print("  ● listening...", end="\r", flush=True)

    def on_release(key):
        if key == target and held["down"]:
            held["down"] = False
            view.thinking()
            audio_q.put((rec.stop(), held["screen"]))

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    print(f"Ready. Hold {HOTKEYS[args.hotkey]}, speak, release. Ctrl+C to quit.", flush=True)
    try:
        while True:
            audio, screen = audio_q.get()
            t = time.perf_counter()
            try:
                labels = [e.label for e in screen.result(timeout=2.5)] if screen else []
            except Exception:  # no permission, or the app didn't answer: transcribe without hints
                labels = []
            text = stt(audio, parse.screen_vocabulary(labels))
            stt_s = time.perf_counter() - t
            print(" " * 20, end="\r")
            if not text:
                view.hide()
                continue
            try:
                engine.handle(text, stt_s)
            except Exception as e:  # keep listening through network hiccups
                view.hide()
                print(f'"{text}" -> error: {e}', file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        listener.stop()


if __name__ == "__main__":
    main()
