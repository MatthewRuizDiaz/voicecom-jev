"""Several commands in one sentence: code proposes where to split, Jev decides (ADR 0005).

"open Safari and search for tacos" is cut at every likely boundary ("and", "then", commas, sentence
ends) into Pieces. Every run of consecutive Pieces is a Span, and each Span gets its own command
Choice in the same Jev request as the whole sentence, so splitting costs no extra round trip.
A split is used only when every Span in it is a confident, non-dictate Command; otherwise the
sentence is one Command, which keeps "type salt and pepper" whole.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

MAX_STEPS = 5  # nobody says six commands in one breath
MAX_PIECES = 6  # 6 pieces -> 20 spans besides the whole sentence, still one Jev request

# Boundaries Whisper produces between spoken commands: "and", "then", "and then", "after that",
# commas and semicolons, and sentence ends ("Open Safari. Search for tacos.").
_BOUNDARY = re.compile(
    r"[\s,;.!?]*\b(?:and then|after that|then|and)\b[\s,;.!?]*"
    r"|\s*[,;]\s*"
    r"|(?<=[.!?])\s+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Span:
    first: int  # index of its first Piece
    last: int  # index of its last Piece (inclusive)
    text: str


def pieces(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of the Pieces between boundaries, at most MAX_PIECES."""
    out, last = [], 0
    for m in _BOUNDARY.finditer(text):
        if m.start() > last and text[last:m.start()].strip(" .,;!?"):
            out.append((last, m.start()))
        last = max(last, m.end())
    if text[last:].strip(" .,;!?"):
        out.append((last, len(text)))
    if len(out) > MAX_PIECES:  # fold the overflow into the last piece
        out = out[:MAX_PIECES - 1] + [(out[MAX_PIECES - 1][0], out[-1][1])]
    return out


def spans(text: str) -> list[Span]:
    """Every run of consecutive Pieces except the whole sentence. Empty if there's nothing to split."""
    ps = pieces(text)
    if len(ps) < 2:
        return []
    return [Span(i, j, text[ps[i][0]:ps[j][1]].strip(" ,;"))
            for i in range(len(ps)) for j in range(i, len(ps)) if (i, j) != (0, len(ps) - 1)]


def best_split(found: list[Span], decisions: list, act: float, dictate: str = "dictate") -> list[tuple[Span, object]] | None:
    """The split into the most Steps (2..MAX_STEPS) whose every Span is a confident non-dictate Command.

    Ties go to the higher product of probabilities. None means: treat the sentence as one Command.
    """
    if not found:
        return None
    n = max(s.last for s in found) + 1
    ok = {(s.first, s.last): (s, d) for s, d in zip(found, decisions) if d.command != dictate and d.p >= act}
    # best[(k, steps)] = (log-probability, chosen spans) covering pieces[:k] in that many steps
    best: dict[tuple[int, int], tuple[float, list]] = {(0, 0): (0.0, [])}
    for end in range(1, n + 1):
        for start in range(end):
            if (start, end - 1) not in ok:
                continue
            span, d = ok[(start, end - 1)]
            for steps in range(MAX_STEPS):
                if (start, steps) not in best:
                    continue
                logp, chosen = best[(start, steps)]
                cand = (logp + math.log(max(d.p, 1e-9)), chosen + [(span, d)])
                key = (end, steps + 1)
                if key not in best or cand[0] > best[key][0]:
                    best[key] = cand
    for steps in range(MAX_STEPS, 1, -1):
        if (n, steps) in best:
            return best[(n, steps)][1]
    return None
