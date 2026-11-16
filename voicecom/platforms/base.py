"""The automation interface. One implementation per OS; commands only talk to this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Element:
    """A labeled, clickable element in the foreground window."""

    label: str
    role: str
    handle: Any = field(default=None, repr=False)  # OS-specific reference used by click()


class Automation(ABC):
    # --- read-only (safe in --dry-run) ---
    @abstractmethod
    def frontmost_app(self) -> str: ...

    @abstractmethod
    def installed_apps(self) -> list[str]: ...

    @abstractmethod
    def clickable_elements(self) -> list[Element]: ...

    @abstractmethod
    def get_volume(self) -> int: ...

    # --- actions ---
    @abstractmethod
    def open_app(self, name: str) -> None: ...

    @abstractmethod
    def quit_app(self, name: str) -> None: ...

    @abstractmethod
    def click(self, element: Element) -> None: ...

    @abstractmethod
    def scroll(self, notches: int) -> None:
        """Positive scrolls down, negative scrolls up."""

    @abstractmethod
    def press(self, keys: list[str]) -> None:
        """Press a chord, e.g. ["cmd", "shift", "t"]. Names follow parse.KEY_ALIASES."""

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def snap_window(self, where: str) -> None:
        """where: "left", "right" or "max"."""

    @abstractmethod
    def set_volume(self, percent: int) -> None: ...

    @abstractmethod
    def toggle_mute(self) -> None: ...

    @abstractmethod
    def open_url(self, url: str) -> None: ...

    @abstractmethod
    def new_tab(self) -> None: ...

    @abstractmethod
    def close_tab(self) -> None: ...

    # --- feedback ---
    def say(self, text: str) -> None:  # optional spoken feedback
        pass


READ_ONLY = {"frontmost_app", "installed_apps", "clickable_elements", "get_volume", "say"}


class DryRun:
    """Wraps an Automation: read-only calls pass through, actions are printed instead."""

    def __init__(self, inner: Automation):
        self._inner = inner

    def __getattr__(self, name: str):
        attr = getattr(self._inner, name)
        if name in READ_ONLY or not callable(attr):
            return attr

        def fake(*args, **kwargs):
            shown = ", ".join([repr(a.label if isinstance(a, Element) else a) for a in args]
                              + [f"{k}={v!r}" for k, v in kwargs.items()])
            print(f"    [dry-run] would call {name}({shown})")

        return fake
