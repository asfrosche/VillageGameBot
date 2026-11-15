"""Shared helpers for Discord API quirks: thread members, length limits, transient errors.

Kept free of bot state so the logic can be unit-tested directly.
"""
from __future__ import annotations

import asyncio
import re
import logging

import discord
from discord.ext import commands

# ── Discord limits ─────────────────────────────────────────────────────────
EMBED_FIELD_VALUE_LIMIT = 1024
EMBED_FIELD_NAME_LIMIT = 256
EMBED_TOTAL_LIMIT = 6000
EMBED_DESCRIPTION_LIMIT = 4096
MESSAGE_CONTENT_LIMIT = 2000
SELECT_OPTION_LIMIT = 25

# Discord error codes we handle explicitly.
CATEGORY_FULL_CODE = 50035          # "Maximum number of channels in category reached"
EDIT_LIMIT_CODE = 30046             # "Maximum number of edits to messages older than 1 hour"
BULK_DELETE_OLD_CODE = 50034        # "You can only bulk delete messages that are under 14 days old"


# ── Text splitting ─────────────────────────────────────────────────────────
def split_text(text: str, limit: int) -> list[str]:
    """Split *text* into chunks of at most *limit* characters, preferring line breaks."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        # A single line longer than the limit is hard-split.
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_fields(items: list[str], limit: int = EMBED_FIELD_VALUE_LIMIT) -> list[str]:
    """Group *items* (lines) into field values that each fit within *limit* characters."""
    values: list[str] = []
    current = ""
    for item in items:
        for piece in split_text(item, limit):
            candidate = piece if not current else f"{current}\n{piece}"
            if len(candidate) > limit:
                values.append(current)
                current = piece
            else:
                current = candidate
    if current:
        values.append(current)
    return values


# ── Retries ────────────────────────────────────────────────────────────────
def is_transient(error: discord.HTTPException) -> bool:
    """Rate limits and Discord-side 5xx errors are worth retrying."""
    status = getattr(error, "status", None)
    return status == 429 or (status is not None and 500 <= status < 600)


async def with_retries(factory, attempts: int = 3, base_delay: float = 2.0):
    """Await ``factory()``, retrying transient Discord errors with exponential backoff."""
    for attempt in range(attempts):
        try:
            return await factory()
        except discord.HTTPException as error:
            if not is_transient(error) or attempt == attempts - 1:
                raise
            await asyncio.sleep(base_delay * (2 ** attempt))


# ── User-facing messages for command failures ──────────────────────────────
def unwrap_error(error: BaseException) -> BaseException:
    """discord.py wraps command failures in CommandInvokeError; return the real cause."""
    if isinstance(error, commands.CommandInvokeError) and error.original is not None:
        return error.original
    return error


def user_facing_message(error: BaseException) -> str | None:
    """Return a friendly message for a known Discord failure, or None for the generic fallback."""
    cause = unwrap_error(error)
    if isinstance(cause, discord.Forbidden):
        return "I don't have permission to do that here. Check my role and channel permissions."
    if isinstance(cause, discord.HTTPException):
        status = getattr(cause, "status", None)
        code = getattr(cause, "code", None)
        if code == CATEGORY_FULL_CODE:
            return "That category is full (Discord allows 50 channels per category)."
        if code == BULK_DELETE_OLD_CODE:
            return "Discord only bulk-deletes messages under 14 days old."
        if code == EDIT_LIMIT_CODE:
            return "Discord limits how often old messages can be edited. Try again later."
        if status == 429:
            return "I'm being rate limited by Discord. Please try again in a moment."
        if status is not None and 500 <= status < 600:
            return "Discord had a temporary error. Please try again in a moment."
    return None


# ── Embeds ─────────────────────────────────────────────────────────────────
def add_text_fields(embed, name: str, text: str, inline: bool = False):
    """Add *text* to *embed* as one or more fields that each respect the 1024-character limit."""
    name = name or "\u200b"
    for index, chunk in enumerate(split_text(text or "\u200b", EMBED_FIELD_VALUE_LIMIT)):
        field_name = name if index == 0 else f"{name.rstrip(':')} (part {index + 1})"
        embed.add_field(name=field_name[:EMBED_FIELD_NAME_LIMIT], value=chunk, inline=inline)
    return embed


# ── Safety net for embeds ──────────────────────────────────────────────────
_log = logging.getLogger("discord_safe")


def install_embed_guard() -> None:
    """Make ``Embed.add_field`` truncate oversized names/values instead of raising.

    Individual commands should chunk their output (see ``add_text_fields``). This is a
    last line of defence so one unexpectedly long value cannot abort a whole command.
    Each truncation is logged so the source can be fixed.
    """
    if getattr(discord.Embed.add_field, "_village_guard", False):
        return
    original = discord.Embed.add_field

    def guarded(self, *args, **kwargs):
        name = kwargs.get("name", "")
        value = kwargs.get("value", "")
        if len(name) > EMBED_FIELD_NAME_LIMIT:
            _log.warning("Embed field name truncated (%d chars): %r", len(name), name[:60])
            kwargs["name"] = name[: EMBED_FIELD_NAME_LIMIT - 1] + "…"
        if not value:
            kwargs["value"] = "​"
        elif len(value) > EMBED_FIELD_VALUE_LIMIT:
            _log.warning("Embed field value truncated (%d chars) in field %r", len(value), str(name)[:60])
            kwargs["value"] = value[: EMBED_FIELD_VALUE_LIMIT - 1] + "…"
        return original(self, *args, **kwargs)

    guarded._village_guard = True
    discord.Embed.add_field = guarded


# ── Category families (main PC category plus numbered overflow categories) ─
def category_family(categories, base_name) -> list:
    """Categories named *base_name* or ``<base_name> <number>`` (case-insensitive), in number order.

    The main category counts as number 1. Overflow categories are created as ``BASE 2``,
    ``BASE 3``, ... by the bot. Matching is exact apart from the number, so ``RC`` does not
    pick up ``DEAD RC``.
    """
    if not base_name:
        return []
    pattern = re.compile(r"^" + re.escape(base_name.strip()) + r"(?:\s+(\d+))?$", re.IGNORECASE)
    matches = []
    for category in categories:
        found = pattern.match(category.name.strip())
        if found:
            number = int(found.group(1)) if found.group(1) else 1
            matches.append((number, category))
    matches.sort(key=lambda item: item[0])
    return [category for _, category in matches]


def next_family_name(categories, base_name) -> str:
    """Name for the next overflow category: one above the highest number already in use.

    Using the highest number (not the count) means a deleted category cannot cause a
    duplicate name.
    """
    family = category_family(categories, base_name)
    highest = 1
    for category in family:
        found = re.search(r"(\d+)\s*$", category.name.strip())
        if found and category.name.strip().lower() != base_name.strip().lower():
            highest = max(highest, int(found.group(1)))
    return f"{base_name.strip()} {highest + 1}"


def family_channels(categories) -> list:
    """Every channel in *categories*, in order."""
    return [channel for category in categories for channel in category.channels]
