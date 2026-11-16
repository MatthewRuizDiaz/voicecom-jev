"""All TypeSafe Jev calls live here. Jev answers typed questions; it never generates text."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from typesafe_sdk import Choice, Noul, NoulCriteria, TypeSafeClient

from .platforms import Element
from .registry import REGISTRY

MAX_OPTIONS = 255  # Jev's Choice limit
NO_APP = "no_app_named"
NO_ELEMENT = "none_of_these"


@dataclass
class Decision:
    command: str
    p: float  # probability of the chosen command (what the gate thresholds on)
    confidence: float  # Jev's spread-based confidence, logged for reference
    destructive: float  # Noul: probability the request is destructive
    meaningful: float  # Noul: probability this is real speech, not filler or noise
    app: str | None
    app_p: float
    latency: float


def _api_key() -> str | None:
    key = os.environ.get("TYPESAFE_API_KEY")
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not key and env_file.exists():  # a gitignored .env in the project root
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip().removeprefix("export ").strip() == "TYPESAFE_API_KEY":
                key = value.strip().strip("'\"") or None
    if not key and platform.system() == "Darwin":
        # Keys set with `launchctl setenv` reach GUI apps but not always terminals.
        key = subprocess.run(["launchctl", "getenv", "TYPESAFE_API_KEY"],
                             capture_output=True, text=True).stdout.strip() or None
    return key


class Jev:
    def __init__(self, model: str = "jev-latest"):
        key = _api_key()
        if not key or key == "your-typesafe-api-key":
            raise SystemExit("TYPESAFE_API_KEY is not set (or is still the .env placeholder). Get a key at https://console.typesafe.ai/keys "
                             "and put it in .env or run: export TYPESAFE_API_KEY=...")
        self.client = TypeSafeClient(api_key=key, model=model, timeout=15)

    # ------------------------------------------------------------ call 1: what command?
    def decide(self, transcript: str, frontmost_app: str, apps: list[str]) -> Decision:
        commands = {c.name: c.description for c in REGISTRY.values()}
        app_options = {a: None for a in apps[: MAX_OPTIONS - 1]}
        app_options[NO_APP] = "The request doesn't name any of these applications"
        state = {"spoken_request": transcript, "frontmost_app": frontmost_app}

        t = time.perf_counter()
        r = self.client.system_one(
            state=state,
            questions={
                "command": Choice(
                    instructions="Which command does the spoken request ask the computer to do? "
                                 "If it is not an instruction to the computer, choose dictate.",
                    criteria=commands,
                ),
                "destructive": Noul(
                    instructions="Carrying out this spoken request would close, quit, delete, send, "
                                 "or discard something, so work could be lost or it would be hard to undo.",
                    criteria=NoulCriteria(
                        true="Closes or quits something, deletes, sends, submits, or overwrites",
                        false="Opens, moves, scrolls, searches, changes volume, or types",
                    ),
                ),
                "meaningful": Noul(
                    instructions="This is a real request or sentence the speaker means, not just filler "
                                 "sounds, hesitation, or noise.",
                    criteria=NoulCriteria(
                        true="A command, a question, or a sentence with real words, even a one-word command",
                        false="Only filler like uh, um, hmm, er, a cough, or a stray word fragment",
                    ),
                ),
                # Speculative: only read when the chosen command takes an app.
                "app": Choice(
                    instructions="Which application does the spoken request name, if any?",
                    criteria=app_options,
                ),
            },
        )
        latency = time.perf_counter() - t
        cmd, dest, app = r.answers["command"], r.answers["destructive"], r.answers["app"]
        # The best real app, even when "no app named" wins: "open my email" puts most weight on
        # no_app_named but still leans toward Mail, and the command code decides what to do with that.
        real = {k: float(v) for k, v in app.probabilities.items() if k != NO_APP}
        best_app = max(real, key=real.get) if real else None
        return Decision(
            command=cmd.choice,
            p=float(cmd.probabilities[cmd.choice]),
            confidence=float(cmd.confidence),
            destructive=float(dest.noul),
            meaningful=float(r.answers["meaningful"].noul),
            app=best_app,
            app_p=real.get(best_app, 0.0),
            latency=latency,
        )

    # ------------------------------------------------------------ call 2: which element?
    def pick_element(self, transcript: str, elements: list[Element], app: str) -> tuple[Element | None, float]:
        elements = _shortlist(transcript, elements, MAX_OPTIONS - 1)
        options: dict[str, str] = {}
        by_key: dict[str, Element] = {}
        for el in elements:
            key = el.label
            n = 2
            while key in options:
                key = f"{el.label} ({n})"
                n += 1
            options[key] = f"{el.role}: {el.label}"
            by_key[key] = el
        options[NO_ELEMENT] = "None of these elements is what the user wants to click"

        r = self.client.system_one(
            state={"spoken_request": transcript, "app": app},
            questions={"element": Choice(
                instructions="Which on-screen element does the user want to click?",
                criteria=options,
            )},
        )
        a = r.answers["element"]
        p = float(a.probabilities[a.choice])
        return (None if a.choice == NO_ELEMENT else by_key[a.choice]), p

    # ------------------------------------------------------------ confirmations
    def is_yes(self, reply: str, question: str) -> float:
        r = self.client.system_one(
            state={"assistant_asked": question, "user_replied": reply},
            questions={"yes": Noul(
                instructions="The user's reply agrees to go ahead.",
                criteria=NoulCriteria(true="yes, do it, go ahead, confirm, sure",
                                      false="no, stop, cancel, wait, or unrelated"),
            )},
        )
        return float(r.answers["yes"].noul)


def _shortlist(transcript: str, elements: list[Element], limit: int) -> list[Element]:
    """If the window has more elements than Jev's option cap, keep the ones sharing words with the request."""
    if len(elements) <= limit:
        return elements
    words = set(re.findall(r"\w+", transcript.lower()))
    scored = sorted(elements, key=lambda e: -len(words & set(re.findall(r"\w+", e.label.lower()))))
    return scored[:limit]
