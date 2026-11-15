"""Redaction for analytics text that may later be pasted outside the bot.

Removes Discord IDs and mentions. Free text is otherwise kept, so reports stay
useful for diagnosis.
"""
from __future__ import annotations

import re

_LONG_ID_RE = re.compile(r"\b\d{15,20}\b")
_MENTION_RE = re.compile(r"<[@#&!]{1,2}\d+>")


def redact_text(text: str | None, limit: int | None = None) -> str:
    """Return ``text`` with mentions and long numeric IDs replaced, optionally truncated."""
    if not isinstance(text, str) or not text:
        return ""
    out = _MENTION_RE.sub("<mention>", text)
    out = _LONG_ID_RE.sub("<id>", out)
    if limit is not None:
        out = out[:limit]
    return out
