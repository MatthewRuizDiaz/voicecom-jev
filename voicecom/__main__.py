"""voicecom-jev: hold a key, say a command, the computer does it.

    python -m voicecom                 # hold Right Option and speak
    python -m voicecom --dry-run       # decide and log, but don't touch anything
    python -m voicecom --text "open chrome" --text "scroll down"   # skip the mic
    python -m voicecom --repl          # type commands instead of speaking
"""

from __future__ import annotations

import argparse
import platform
import queue
import sys
import time

from .engine import Engine, Thresholds
from .jev import Jev
from .platforms import DryRun, check_permissions, get_automation
from .registry import REGISTRY

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
    ap.add_argument("--quiet", action="store_true", help="no spoken confirmation prompts")
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
    if args.dry_run:
        auto = DryRun(auto)
    typed = args.text or args.repl
    engine = Engine(auto, Jev(args.model), Thresholds(act=args.act, ignore=args.ignore),
                    speak=not (args.quiet or typed), dry_run=args.dry_run)

    if args.text:
        for line in args.text:
            engine.handle(line)
            if engine.pending:  # answer confirmations from the keyboard in text mode
                engine.handle(input("  confirm? > "))
        return
    if args.repl:
        try:
            while True:
                line = input("say> ")
                engine.handle(line)
        except (EOFError, KeyboardInterrupt):
            return

    listen(engine, args)


def listen(engine: Engine, args) -> None:
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
    target = getattr(keyboard.Key, args.hotkey)
    audio_q: queue.Queue = queue.Queue()
    held = {"down": False}

    def on_press(key):
        if key == target and not held["down"]:
            held["down"] = True
            rec.start()
            print("  ● listening...", end="\r", flush=True)

    def on_release(key):
        if key == target and held["down"]:
            held["down"] = False
            audio_q.put(rec.stop())

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    print(f"Ready. Hold {HOTKEYS[args.hotkey]}, speak, release. Ctrl+C to quit.", flush=True)
    try:
        while True:
            audio = audio_q.get()
            t = time.perf_counter()
            text = stt(audio)
            stt_s = time.perf_counter() - t
            print(" " * 20, end="\r")
            if not text:
                continue
            try:
                engine.handle(text, stt_s)
            except Exception as e:  # keep listening through network hiccups
                print(f'"{text}" -> error: {e}', file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        listener.stop()


if __name__ == "__main__":
    main()
