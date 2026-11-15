"""Match a player's `.move` / `.knock` argument to a house channel.

Players can type a house number (`23`) or a name (`tower`). House channels are named like
`🏡│house-23`, so the part after the last `│` is compared, case-insensitively.
"""
from __future__ import annotations

import difflib

NO_MATCH = "No house matches"


def _short(name: str) -> str:
    """The part of a channel name after the emoji prefix, lowercased."""
    return name.split("│")[-1].strip().lower()


def house_match(channels, query: str):
    """Return (channel, error). Exactly one of them is set.

    A number matches `house-<n>`. A name matches a house whose short name equals it, or else
    contains it when that is unambiguous. Several matches return an error listing them.
    """
    q = (query or "").strip().lstrip("#").lower()
    if not q:
        return None, "Give a house number or name, e.g. `.knock 23` or `.knock tower`."

    if q.isdigit():
        wanted = {q, f"house-{q}"}
        exact = [ch for ch in channels if _short(ch.name) in wanted]
    else:
        exact = [ch for ch in channels if _short(ch.name) == q]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, _ambiguous(exact)

    if q.isdigit():
        return None, f"No house numbered **{q}**."

    partial = [ch for ch in channels if q in _short(ch.name)]
    if len(partial) == 1:
        return partial[0], None
    if not partial:
        return None, f"{NO_MATCH} **{query}**."
    return None, _ambiguous(partial)


def _ambiguous(channels) -> str:
    names = ", ".join(f"`{_short(ch.name)}`" for ch in channels[:10])
    return f"More than one house matches: {names}. Use the house number."


def closest_house(channels, query: str, cutoff: float = 0.6):
    """The house whose short name is most similar to *query*, or None if nothing is close enough.

    Used to suggest a house after a typo, and never for plain numbers (18 must not become 81).
    """
    q = (query or "").strip().lstrip("#").lower()
    if not q or q.isdigit():
        return None
    best, best_score = None, 0.0
    for ch in channels:
        score = difflib.SequenceMatcher(None, q, _short(ch.name)).ratio()
        if score > best_score:
            best, best_score = ch, score
    return best if best_score >= cutoff else None
