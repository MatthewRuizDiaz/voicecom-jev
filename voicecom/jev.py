"""All TypeSafe Jev calls live here. Jev answers typed questions; it never generates text."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from typesafe_sdk import Choice, Noul, NoulCriteria, TypeSafeClient

from .platforms import Element
from .registry import REGISTRY

MAX_OPTIONS = 255  # Jev's Choice limit
NO_APP = "no_app_named"
NO_ELEMENT = "none_of_these"
NAMES_APP = re.compile(r"\b(open|launch|start|switch|go to|bring up|show|quit|close|exit|kill)\b", re.I)


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
    spans: list[Decision] = field(default_factory=list)  # one per candidate Span, same order


def _api_key() -> str | None:
    key = os.environ.get("TYPESAFE_API_KEY")
    # A gitignored .env in the project root, or in the folder you run from (for a pipx install).
    for env_file in (Path(__file__).resolve().parent.parent / ".env", Path.cwd() / ".env"):
        if key or not env_file.exists():
            continue
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
            raise SystemExit("TYPESAFE_API_KEY is not set (or is still the .env placeholder). "
                             "Get a key at https://console.typesafe.ai/keys "
                             "and put it in .env or run: export TYPESAFE_API_KEY=...")
        self.client = TypeSafeClient(api_key=key, model=model, timeout=15)

    # ------------------------------------------------------------ call 1: what command?
    def decide(self, transcript: str, frontmost_app: str, apps: list[str],
               spans: list[str] = ()) -> Decision:
        """One request: the command for the whole sentence plus, when it might hold several
        commands, the command for each candidate Span (see chain.py)."""
        commands = {c.name: c.description for c in REGISTRY.values()}
        app_options = {a: None for a in apps[: MAX_OPTIONS - 1]}
        app_options[NO_APP] = "The request doesn't name any of these applications"
        state = {"spoken_request": transcript, "frontmost_app": frontmost_app}

        questions = {
            "command": Choice(
                instructions="Which command does the spoken request ask the computer to do? "
                             "If it is not an instruction to the computer, choose dictate.",
                criteria=commands,
            ),
            "destructive": _destructive("this spoken request"),
            "meaningful": Noul(
                instructions="This is a real request or sentence the speaker means, not just filler "
                             "sounds, hesitation, or noise.",
                criteria=NoulCriteria(
                    true="A command, a question, or a sentence with real words, even a one-word command",
                    false="Only filler like uh, um, hmm, er, a cough, or a stray word fragment",
                ),
            ),
            # Speculative: only read when the chosen command takes an app.
            "app": Choice(instructions="Which application does the spoken request name, if any?",
                          criteria=app_options),
        }
        for k, text in enumerate(spans):
            state[f"phrase_{k}"] = text
            questions[f"command_{k}"] = Choice(
                instructions=f"Taken on its own, which command does phrase_{k} (\"{text}\") ask the computer "
                             "to do? If it is not a complete instruction to the computer by itself, choose dictate.",
                criteria=commands,
            )
            questions[f"destructive_{k}"] = _destructive(f"phrase_{k} (\"{text}\")")
            if NAMES_APP.search(text):
                questions[f"app_{k}"] = Choice(
                    instructions=f"Which application does phrase_{k} (\"{text}\") name, if any?",
                    criteria=app_options)

        t = time.perf_counter()
        r = self.client.system_one(state=state, questions=questions)
        latency = time.perf_counter() - t
        meaningful = float(r.answers["meaningful"].noul)

        def read(suffix: str) -> Decision:
            cmd, dest = r.answers["command" + suffix], r.answers["destructive" + suffix]
            app, app_p = _best_app(r.answers.get("app" + suffix))
            return Decision(command=cmd.choice, p=float(cmd.probabilities[cmd.choice]),
                            confidence=float(cmd.confidence), destructive=float(dest.noul),
                            meaningful=meaningful, app=app, app_p=app_p, latency=latency)

        d = read("")
        d.spans = [read(f"_{k}") for k in range(len(spans))]
        return d

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


def _destructive(subject: str) -> Noul:
    return Noul(
        instructions=f"Carrying out {subject} would close, quit, delete, send, or discard something, "
                     "so work could be lost or it would be hard to undo.",
        criteria=NoulCriteria(
            true="Closes or quits something, deletes, sends, submits, or overwrites",
            false="Opens, moves, scrolls, searches, changes volume, or types",
        ),
    )


def _best_app(answer) -> tuple[str | None, float]:
    """The best real app, even when "no app named" wins: "open my email" puts most weight on
    no_app_named but still leans toward Mail, and the command code decides what to do with that."""
    if answer is None:
        return None, 0.0
    real = {k: float(v) for k, v in answer.probabilities.items() if k != NO_APP}
    best = max(real, key=real.get) if real else None
    return best, real.get(best, 0.0)


def _shortlist(transcript: str, elements: list[Element], limit: int) -> list[Element]:
    """If the window has more elements than Jev's option cap, keep the ones sharing words with the request."""
    if len(elements) <= limit:
        return elements
    words = set(re.findall(r"\w+", transcript.lower()))
    scored = sorted(elements, key=lambda e: -len(words & set(re.findall(r"\w+", e.label.lower()))))
    return scored[:limit]
