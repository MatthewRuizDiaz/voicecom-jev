"""The command registry. Add a command with @command(...) in commands.py; Jev sees its description."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .jev import Jev
    from .platforms import Automation


@dataclass
class Ctx:
    """Everything a command needs to turn a transcript into an action."""

    transcript: str
    auto: Automation
    jev: Jev
    app: str | None = None  # app name Jev picked in the same request, if any
    app_p: float = 0.0
    apps: list[str] = field(default_factory=list)  # installed app names
    elements: list | None = None  # foreground-window elements, prefetched while Jev runs


@dataclass
class Plan:
    """What a command will do, before it does it (so we can confirm or dry-run)."""

    summary: str
    do: Callable[[], None]
    p: float | None = None  # extra probability from a second Jev call (e.g. which element)
    confirm: bool = False  # the command itself wants a yes first (e.g. it guessed the app)
    extra: dict = field(default_factory=dict)


@dataclass
class Command:
    name: str
    description: str
    plan: Callable[[Ctx], Plan | None]
    uses_app: bool = False
    takes_rest: bool = False  # its text runs to the end of the sentence, so a Chain can't split after it


REGISTRY: dict[str, Command] = {}


def command(name: str, description: str, uses_app: bool = False, takes_rest: bool = False):
    def register(fn: Callable[[Ctx], Plan | None]):
        REGISTRY[name] = Command(name, description, fn, uses_app, takes_rest)
        return fn

    return register
