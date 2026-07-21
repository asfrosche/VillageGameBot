from __future__ import annotations

import asyncio
import logging
import time
import traceback as tb_module
from datetime import datetime

from discord.ext import commands

from .models import CommandEvent

logger = logging.getLogger("analytics.instrumentation")


def register_analytics_hooks(bot: commands.Bot, service) -> None:
    if service is None or not service.enabled:
        logger.info("Analytics disabled — hooks not registered")
        return

    @bot.before_invoke
    async def _analytics_before_invoke(ctx):
        ctx._analytics_start = time.monotonic()

    @bot.after_invoke
    async def _analytics_after_invoke(ctx):
        start = getattr(ctx, "_analytics_start", None)
        if start is None:
            return
        duration = time.monotonic() - start
        event = CommandEvent(
            command_name=ctx.command.qualified_name if ctx.command else "unknown",
            cog_name=ctx.cog.qualified_name if ctx.cog else None,
            timestamp=datetime.utcnow(),
            duration_ms=round(duration * 1000, 2),
            success=True,
            user_id=str(ctx.author.id) if ctx.author else None,
            guild_id=str(ctx.guild.id) if ctx.guild else None,
            bot_version=service.config.bot_version,
            git_commit=service.config.git_commit,
        )
        asyncio.create_task(service.record_execution(event))

    # Save the original bot-level on_command_error before replacing.
    # discord.py only keeps one @bot.event per event name — the second
    # registration silently replaces the first.  We chain them here so
    # analytics recording AND user-facing error messages both run.
    _original_on_error = getattr(bot, "on_command_error", None)

    @bot.event
    async def on_command_error(ctx, error):
        if not isinstance(error, (commands.UserInputError, commands.CheckFailure, commands.CommandNotFound)):
            start = getattr(ctx, "_analytics_start", None)
            duration = time.monotonic() - start if start else 0
            tb = "".join(
                tb_module.format_exception(type(error), error, error.__traceback__)
            )
            event = CommandEvent(
                command_name=ctx.command.qualified_name if ctx.command else "unknown",
                cog_name=ctx.cog.qualified_name if ctx.cog else None,
                timestamp=datetime.utcnow(),
                duration_ms=round(duration * 1000, 2),
                success=False,
                error_type=type(error).__name__,
                error_traceback=tb,
                user_id=str(ctx.author.id) if ctx.author else None,
                guild_id=str(ctx.guild.id) if ctx.guild else None,
                bot_version=service.config.bot_version,
                git_commit=service.config.git_commit,
            )
            asyncio.create_task(service.record_failure(event))

        # Chain to original handler so user-facing error messages still fire.
        if _original_on_error is not None:
            await _original_on_error(ctx, error)

    logger.info("Analytics instrumentation hooks registered")
