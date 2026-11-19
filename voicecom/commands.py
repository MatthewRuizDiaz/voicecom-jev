"""The command set. Each entry: a name, a description Jev chooses by, and a planner in plain code."""

from __future__ import annotations

import re

from . import parse
from .registry import Ctx, Plan, command

DICTATE = "dictate"


def _app_name(ctx: Ctx, *leads: str) -> tuple[str | None, bool]:
    """Resolve which app the user named. Returns (name, guessed); guessed means confirm first.

    1. Jev picked an installed app confidently -> use it.
    2. The spoken name is an installed app ("open safari") -> use it.
    3. Jev leans toward an app ("open my email" -> Mail at about 0.2) -> Confirm "open Mail?"
       instead of opening an app literally named "my email".
    4. Otherwise the spoken words; opening fails clearly if no such app is installed.
    """
    if ctx.app and ctx.app_p >= 0.7:
        return ctx.app, False
    spoken = parse.after(ctx.transcript, *leads)
    spoken = re.sub(r"^(the\s+)?(app\s+)?", "", spoken, flags=re.I)
    spoken = re.sub(r"\s+(app|application)$", "", spoken, flags=re.I)
    installed = {a.lower(): a for a in ctx.apps}
    if spoken and spoken.lower() in installed:
        return installed[spoken.lower()], False
    if ctx.app and ctx.app_p >= 0.15:
        return ctx.app, True
    return spoken or None, False


# ---------------------------------------------------------------- apps
@command("open_app", "Open, launch, start, or switch to an application. E.g. 'open Chrome', "
         "'switch to Slack', 'go to Spotify'.", uses_app=True)
def open_app(ctx: Ctx):
    name, guessed = _app_name(ctx, "open up", "open", "launch", "start", "switch to", "go to", "bring up", "show")
    if name:
        return Plan(f"open {name}", lambda: ctx.auto.open_app(name), confirm=guessed, extra={"front": name})


@command("quit_app", "Quit or close a whole application. E.g. 'quit Spotify', 'close Slack completely'.",
         uses_app=True)
def quit_app(ctx: Ctx):
    name, guessed = _app_name(ctx, "quit", "close", "exit", "kill")
    name = name or ctx.auto.frontmost_app()
    return Plan(f"quit {name}", lambda: ctx.auto.quit_app(name), confirm=guessed)


# ---------------------------------------------------------------- pointer / keyboard
@command("click", "Click, press, or select a button, link, tab, or menu item on screen by its label. "
         "E.g. 'click Submit', 'press the Sign in button', 'select Settings'.")
def click(ctx: Ctx):
    # Clicks search the active app's focused window, not whatever is under the pointer, so every
    # outcome names that app: a miss in the wrong app is then obvious (issue #15).
    app = ctx.auto.frontmost_app()
    target = parse.after(ctx.transcript, "click on", "click", "press", "tap", "select", "hit", "choose", "push")
    target = re.sub(r"^the\s+|\s+(button|link|tab)$", "", target, flags=re.I) or "that"
    elements = ctx.elements if ctx.elements is not None else ctx.auto.clickable_elements()
    if not elements:  # p=0 sends both misses to the gate's Ignore
        return Plan(f"no labeled buttons in {app}'s window", lambda: None, p=0.0)
    el, p = ctx.jev.pick_element(ctx.transcript, elements, app)
    if el is None:
        return Plan(f'no "{target}" in {app}\'s window', lambda: None, p=0.0, extra={"none_of_these": p})
    return Plan(f"click {el.role} '{el.label}' in {app}", lambda: ctx.auto.click(el), p=p,
                extra={"elements": len(elements)})


@command("scroll_down", "Scroll down the page or window. E.g. 'scroll down', 'scroll down a lot', 'page down'.")
def scroll_down(ctx: Ctx):
    n = parse.scroll_amount(ctx.transcript)
    return Plan(f"scroll down {n}", lambda: ctx.auto.scroll(n))


@command("scroll_up", "Scroll up the page or window. E.g. 'scroll up', 'go back up a bit'.")
def scroll_up(ctx: Ctx):
    n = parse.scroll_amount(ctx.transcript)
    return Plan(f"scroll up {n}", lambda: ctx.auto.scroll(-n))


@command("press_keys", "Press a key or keyboard shortcut. E.g. 'press enter', 'hit escape', "
         "'press command shift T', 'press tab'.")
def press_keys(ctx: Ctx):
    keys = parse.keys(ctx.transcript)
    if keys:
        return Plan(f"press {'+'.join(keys)}", lambda: ctx.auto.press(keys))


@command("type_text", "Type out specific text the user dictates after the word 'type' or 'write'. "
         "E.g. 'type hello world', 'write see you tomorrow'.")
def type_text(ctx: Ctx):
    text = parse.after(ctx.transcript, "type out", "type", "write", "enter the text", keep_end=True)
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1]  # Whisper ends every Transcript with a period; keep ? and ! the speaker meant
    if text:
        return Plan(f"type {text!r}", lambda: ctx.auto.type_text(text))


# ---------------------------------------------------------------- windows
@command("snap_left", "Move or snap the current window to the left half of the screen.")
def snap_left(ctx: Ctx):
    return Plan("snap window left", lambda: ctx.auto.snap_window("left"))


@command("snap_right", "Move or snap the current window to the right half of the screen.")
def snap_right(ctx: Ctx):
    return Plan("snap window right", lambda: ctx.auto.snap_window("right"))


@command("maximize_window", "Maximize the current window or make it fill the screen.")
def maximize_window(ctx: Ctx):
    return Plan("maximize window", lambda: ctx.auto.snap_window("max"))


# ---------------------------------------------------------------- volume
@command("volume_up", "Make the sound louder / turn the volume up.")
def volume_up(ctx: Ctx):
    step = parse.number(ctx.transcript) or 10
    v = min(100, ctx.auto.get_volume() + step)
    return Plan(f"volume -> {v}", lambda: ctx.auto.set_volume(v))


@command("volume_down", "Make the sound quieter / turn the volume down.")
def volume_down(ctx: Ctx):
    step = parse.number(ctx.transcript) or 10
    v = max(0, ctx.auto.get_volume() - step)
    return Plan(f"volume -> {v}", lambda: ctx.auto.set_volume(v))


@command("set_volume", "Set the volume to a specific level. E.g. 'set volume to 30', 'volume fifty percent'.")
def set_volume(ctx: Ctx):
    v = parse.number(ctx.transcript)
    if v is not None:
        return Plan(f"volume -> {v}", lambda: ctx.auto.set_volume(v))


@command("mute", "Mute or unmute the sound.")
def mute(ctx: Ctx):
    return Plan("toggle mute", ctx.auto.toggle_mute)


# ---------------------------------------------------------------- browser
@command("new_tab", "Open a new browser or editor tab.")
def new_tab(ctx: Ctx):
    app = ctx.auto.new_tab_target()  # the front app if it has tabs, otherwise the default browser
    return Plan(f"new tab in {app}", lambda: ctx.auto.new_tab(app), extra={"front": app})


@command("close_tab", "Close the current tab.")
def close_tab(ctx: Ctx):
    return Plan("close tab", ctx.auto.close_tab)


@command("web_search", "Search the web for something. E.g. 'search for pizza near me', "
         "'google how tall is Everest', 'look up the weather'.")
def web_search(ctx: Ctx):
    q = parse.after(ctx.transcript, "do a web search for", "web search for", "web search", "search the web for",
                    "search for", "search", "google",
                    "look up", "find me", "find")
    if q:
        url = ctx.auto.search_url(q)  # the user's own search engine
        return Plan(f"search {q!r}", lambda: ctx.auto.open_url(url), extra={"settle": 1.0})  # page load


# ---------------------------------------------------------------- notes
NOTE_LEADS = ("open the notes app and type", "open the notes app and write", "open notes and type",
              "open notes and write", "go to notes and type", "open a new note and type", "open a new note and write",
              "make a new note saying",
              "make a note saying", "create a new note saying", "create a note saying", "new note saying",
              "make a new note", "create a new note", "open a new note", "start a new note", "make a note",
              "create a note", "write a note", "take a note", "jot down", "new note", "note that", "note")


@command("new_note", "Create a new note in the Notes app containing what the user says, including any "
         "request to open Notes and type or write something. E.g. 'new note call the dentist', "
         "'make a note saying buy milk', 'open Notes and type meeting at 3'.",
         takes_rest=True)
def new_note(ctx: Ctx):
    text = parse.after(ctx.transcript, *NOTE_LEADS, keep_end=True)
    text = re.sub(r"^(saying|that says|that|with|and type|and write|to say)\b[\s:,]*", "", text, flags=re.I)
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1]
    if text.lower() == parse.clean(ctx.transcript).lower():  # nothing matched: don't put the command in the note
        text = ""
    return Plan(f"new note {text!r}" if text else "new empty note", lambda: ctx.auto.new_note(text),
                extra={"front": "Notes"})


# ---------------------------------------------------------------- fallback
@command(DICTATE, "Not a command for the computer: ordinary speech or a sentence to be typed out "
         "as dictation.")
def dictate(ctx: Ctx):
    text = ctx.transcript.strip()
    if text:
        return Plan(f"dictate {text!r}", lambda: ctx.auto.type_text(text))
