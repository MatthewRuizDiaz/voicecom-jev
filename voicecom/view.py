"""What the engine shows besides the log line: a Card per Utterance. The overlay draws it; tests ignore it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class StepView:
    label: str  # what it will do / did ("open Safari"), or the words Jev couldn't use
    p: float  # Jev's probability for this Step's Command
    dim: bool = False  # the part that wasn't understood


@dataclass
class Card:
    transcript: str
    steps: list[StepView] = field(default_factory=list)
    outcome: str = ""  # ran | confirm | ignored | failed | cancelled
    detail: str = ""  # why, e.g. "unsure" or the error
    total_s: float = 0.0


class View:
    """No-op view: the terminal log is enough (tests, --no-overlay, non-macOS)."""

    def listening(self, level: Callable[[], float]) -> None: ...
    def thinking(self, transcript: str | None = None) -> None: ...
    def result(self, card: Card) -> None: ...
    def hide(self) -> None: ...
