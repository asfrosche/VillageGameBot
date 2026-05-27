import discord
from datetime import datetime

from config import (
    EMBED_FOOTER_TEXT,
    EMBED_PRIMARY_COLOR,
    EMBED_ERROR_COLOR,
    EMBED_WARNING_COLOR,
)


def _build_embed(
    *,
    title: str | None = None,
    description: str | None = None,
    color: int | discord.Colour | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    """Base helper used by all embed factories."""
    kwargs: dict = {}
    if timestamp:
        kwargs["timestamp"] = datetime.now()

    embed = discord.Embed(
        title=title,
        description=description,
        color=color if color is not None else EMBED_PRIMARY_COLOR,
        **kwargs,
    )
    embed.set_footer(text=EMBED_FOOTER_TEXT)
    return embed


def info_embed(
    *,
    title: str | None = None,
    description: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    """Generic information embed with the bot's primary color."""
    return _build_embed(title=title, description=description, timestamp=timestamp)


def success_embed(
    *,
    title: str = "Success",
    description: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    """Standard success embed."""
    return _build_embed(
        title=title,
        description=description,
        color=discord.Color.green(),
        timestamp=timestamp,
    )


def error_embed(
    *,
    title: str = "Error",
    description: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    """Standard error embed."""
    return _build_embed(
        title=title,
        description=description,
        color=EMBED_ERROR_COLOR,
        timestamp=timestamp,
    )


def warning_embed(
    *,
    title: str = "Warning",
    description: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    """Warning embed, typically used for confirmations or soft errors."""
    return _build_embed(
        title=title,
        description=description,
        color=EMBED_WARNING_COLOR,
        timestamp=timestamp,
    )


def plain_embed(
    *,
    title: str | None = None,
    description: str | None = None,
    color: int | discord.Colour | None = None,
) -> discord.Embed:
    """
    Embed without an automatic timestamp, useful when the original code
    didn't include one but we still want consistent styling.
    """
    return _build_embed(title=title, description=description, color=color, timestamp=False)

