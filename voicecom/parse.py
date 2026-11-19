"""Plain-code extraction for what Jev doesn't extract: numbers, key names, free text."""

from __future__ import annotations

import re

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split())
         if w != "_"}


def clean(transcript: str) -> str:
    """Whisper adds capitals and trailing punctuation; strip them for matching."""
    return re.sub(r"\s+", " ", transcript.strip().strip(".!?,").strip())


def number(text: str) -> int | None:
    """First number in text, as digits ("50", "50%") or words ("twenty five", "a hundred")."""
    m = re.search(r"\d+", text)
    if m:
        return int(m.group())
    words = re.findall(r"[a-z]+", text.lower())
    total, found = 0, False
    for w in words:
        if w == "hundred":
            total = (total or 1) * 100
            found = True
        elif w in _TENS:
            total += _TENS[w]
            found = True
        elif w in _UNITS:
            total += _UNITS[w]
            found = True
        elif found and w not in ("and", "percent"):
            break
    if "half" in words and not found:
        return 50
    return total if found else None


def after(text: str, *leads: str, keep_end: bool = False) -> str:
    """Text after the first matching lead phrase, e.g. after("Type hello there", "type") -> "hello there".

    Whisper often writes a pause after the command word as punctuation ("Type. Hello guys."), so any
    punctuation between the lead and the rest is skipped. keep_end keeps the speaker's own sentence
    punctuation at the end (for text that gets typed out).
    """
    t = re.sub(r"\s+", " ", text.strip()) if keep_end else clean(text)
    for lead in sorted(leads, key=len, reverse=True):
        words = r"[\s.,:;!?-]+".join(map(re.escape, lead.split()))  # "web search" also matches "Web. Search"
        m = re.match(rf"^(?:please[\s,]+)?(?:can you\s+)?{words}\b[\s.,:;!?-]*(.*)$", t, re.IGNORECASE)
        if m:
            rest = m.group(1).strip()
            return rest
    return t


KEY_ALIASES = {
    "command": "cmd", "cmd": "cmd", "control": "ctrl", "ctrl": "ctrl", "option": "alt", "alt": "alt",
    "shift": "shift", "enter": "enter", "return": "enter", "escape": "escape", "esc": "escape",
    "tab": "tab", "space": "space", "spacebar": "space", "backspace": "backspace", "delete": "backspace",
    "forward delete": "delete", "up": "up", "down": "down", "left": "left", "right": "right",
    "page up": "pageup", "page down": "pagedown", "home": "home", "end": "end",
    "comma": ",", "period": ".", "dot": ".", "slash": "/", "minus": "-", "dash": "-", "equals": "=",
    "plus": "=", "semicolon": ";", "backtick": "`",
}
_NUMBER_WORDS = {w: str(i) for w, i in _UNITS.items() if i < 10}


def keys(text: str) -> list[str] | None:
    """"press command shift T" -> ["cmd", "shift", "t"]. None if nothing recognisable."""
    body = after(text, "press", "hit", "push", "tap", "type the key", "key")
    body = re.sub(r"[-+]", " ", body.lower())
    body = re.sub(r"[^\w\s,./;=`]", "", body)
    tokens = body.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        two = " ".join(tokens[i:i + 2])
        if two in KEY_ALIASES:
            out.append(KEY_ALIASES[two])
            i += 2
            continue
        tok = tokens[i]
        if tok in KEY_ALIASES:
            out.append(KEY_ALIASES[tok])
        elif re.fullmatch(r"f([1-9]|1[0-2])", tok):
            out.append(tok)
        elif tok in _NUMBER_WORDS:
            out.append(_NUMBER_WORDS[tok])
        elif len(tok) == 1:
            out.append(tok)
        elif tok in ("the", "key", "keys", "and", "then", "button"):
            pass
        elif len(tok) <= 3 and tok.isalpha() and not out:
            # Whisper sometimes writes a lone letter as a word ("tee"); keep the first char.
            out.append(tok[0])
        i += 1
    return out or None


def scroll_amount(text: str) -> int:
    """Wheel notches to scroll: an explicit number, 'a lot'/'a little', or a default."""
    t = text.lower()
    n = number(t)
    if n:
        return max(1, min(n, 50))
    if any(w in t for w in ("a lot", "way", "page", "far", "bottom", "top")):
        return 15
    if any(w in t for w in ("little", "bit", "slightly")):
        return 2
    return 5


def screen_vocabulary(labels: list[str], max_chars: int = 600) -> str:
    """On-screen labels as a hint for Whisper, so "Expedia" beats a sound-alike (issue #24).

    Unique, short labels in screen order, cut at a label boundary to stay well inside Whisper's
    224-token prompt (it keeps the end, where these go).
    """
    seen, out, used = set(), [], 0
    for label in labels:
        label = " ".join(label.split())
        if not label or len(label) > 40 or label.lower() in seen:
            continue
        if used + len(label) + 2 > max_chars:
            break
        seen.add(label.lower())
        out.append(label)
        used += len(label) + 2
    return ", ".join(out)
