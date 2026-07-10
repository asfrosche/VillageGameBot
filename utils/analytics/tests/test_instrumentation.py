"""Tests for analytics instrumentation hooks."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands

from utils.analytics.instrumentation import register_analytics_hooks


def _await(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestRegisterAnalyticsHooks:
    """Verify that register_analytics_hooks properly installs instrumentation hooks."""

    @staticmethod
    def _make_mock_bot():
        bot = MagicMock()
        bot.before_invoke = MagicMock()
        bot.after_invoke = MagicMock()
        return bot

    @staticmethod
    def _make_mock_ctx(**kwargs):
        ctx = MagicMock()
        ctx.command.qualified_name = kwargs.get("command_name", "test_cmd")
        ctx.cog.qualified_name = kwargs.get("cog_name", "TestCog")
        ctx.author.id = kwargs.get("user_id", 12345)
        ctx.guild.id = kwargs.get("guild_id", 67890)
        return ctx

    @staticmethod
    def _make_mock_service(**kwargs):
        svc = MagicMock()
        svc.enabled = kwargs.get("enabled", True)
        svc.record_execution = AsyncMock()
        svc.record_failure = AsyncMock()
        svc.config.bot_version = ""
        svc.config.git_commit = ""
        return svc

    def test_skips_when_service_is_none(self):
        bot = self._make_mock_bot()
        register_analytics_hooks(bot, None)
        bot.before_invoke.assert_not_called()
        bot.after_invoke.assert_not_called()
        bot.event.assert_not_called()

    def test_skips_when_service_disabled(self):
        bot = self._make_mock_bot()
        service = self._make_mock_service(enabled=False)
        register_analytics_hooks(bot, service)
        bot.before_invoke.assert_not_called()
        bot.after_invoke.assert_not_called()
        bot.event.assert_not_called()

    def test_registers_before_invoke_and_after_invoke(self):
        bot = self._make_mock_bot()
        service = self._make_mock_service()
        register_analytics_hooks(bot, service)
        bot.before_invoke.assert_called_once()
        bot.after_invoke.assert_called_once()

    def test_before_invoke_sets_start_time_on_ctx(self):
        bot = self._make_mock_bot()
        service = self._make_mock_service()
        register_analytics_hooks(bot, service)

        fn = bot.before_invoke.call_args[0][0]
        ctx = self._make_mock_ctx()
        _await(fn(ctx))
        assert hasattr(ctx, "_analytics_start")
        assert isinstance(ctx._analytics_start, float)

    def test_after_invoke_records_successful_execution(self):
        bot = self._make_mock_bot()
        service = self._make_mock_service()
        register_analytics_hooks(bot, service)

        before = bot.before_invoke.call_args[0][0]
        after = bot.after_invoke.call_args[0][0]

        ctx = self._make_mock_ctx()
        _await(before(ctx))
        time.sleep(0.05)
        _await(after(ctx))

        service.record_execution.assert_called_once()
        event = service.record_execution.call_args[0][0]
        assert event.command_name == "test_cmd"
        assert event.cog_name == "TestCog"
        assert event.success is True
        assert event.duration_ms > 0
        assert event.user_id == "12345"
        assert event.guild_id == "67890"

    def test_after_invoke_skips_when_no_start_time(self):
        bot = self._make_mock_bot()
        service = self._make_mock_service()
        register_analytics_hooks(bot, service)

        after = bot.after_invoke.call_args[0][0]
        ctx = self._make_mock_ctx()
        ctx._analytics_start = None  # MagicMock auto-creates attrs; explicitly set None
        _await(after(ctx))

        service.record_execution.assert_not_called()

    def test_after_invoke_records_unknown_command_when_no_command(self):
        bot = self._make_mock_bot()
        service = self._make_mock_service()
        register_analytics_hooks(bot, service)

        after = bot.after_invoke.call_args[0][0]
        ctx = self._make_mock_ctx()
        ctx.command = None
        _await(after(ctx))

        service.record_execution.assert_called_once()
        event = service.record_execution.call_args[0][0]
        assert event.command_name == "unknown"


class TestOnCommandError:
    """Verify the on_command_error listener filters and records errors correctly."""

    @staticmethod
    def _make_handlers():
        bot = MagicMock()
        bot.before_invoke = MagicMock()
        bot.after_invoke = MagicMock()
        service = MagicMock()
        service.enabled = True
        service.record_execution = AsyncMock()
        service.record_failure = AsyncMock()
        service.config.bot_version = ""
        service.config.git_commit = ""
        register_analytics_hooks(bot, service)
        before = bot.before_invoke.call_args[0][0]
        after = bot.after_invoke.call_args[0][0]
        on_error = bot.event.call_args[0][0]
        return before, on_error, service

    def test_filters_out_bad_argument(self):
        _, on_error, service = self._make_handlers()
        ctx = MagicMock()
        ctx.command.qualified_name = "test"
        ctx.cog = None
        error = commands.BadArgument("invalid input")
        _await(on_error(ctx, error))
        service.record_failure.assert_not_called()

    def test_filters_out_missing_required_argument(self):
        _, on_error, service = self._make_handlers()
        ctx = MagicMock()
        ctx.command.qualified_name = "test"
        ctx.cog = None
        error = commands.MissingRequiredArgument(MagicMock())
        _await(on_error(ctx, error))
        service.record_failure.assert_not_called()

    def test_filters_out_too_many_arguments(self):
        _, on_error, service = self._make_handlers()
        ctx = MagicMock()
        ctx.command.qualified_name = "test"
        ctx.cog = None
        error = commands.TooManyArguments("too many")
        _await(on_error(ctx, error))
        service.record_failure.assert_not_called()

    def test_records_command_on_cooldown(self):
        """CommandOnCooldown is NOT a UserInputError, so it is recorded."""
        _, on_error, service = self._make_handlers()
        ctx = MagicMock()
        ctx.command.qualified_name = "test"
        ctx.cog = None
        error = commands.CommandOnCooldown(MagicMock(), 10, commands.BucketType.default)
        _await(on_error(ctx, error))
        service.record_failure.assert_called_once()

    def test_records_non_user_input_errors(self):
        before, on_error, service = self._make_handlers()
        ctx = MagicMock()
        ctx.command.qualified_name = "fail_cmd"
        ctx.cog.qualified_name = "FailCog"
        ctx.author.id = 111
        ctx.guild.id = 222
        _await(before(ctx))
        time.sleep(0.05)
        error = RuntimeError("something went wrong")
        _await(on_error(ctx, error))

        service.record_failure.assert_called_once()
        event = service.record_failure.call_args[0][0]
        assert event.command_name == "fail_cmd"
        assert event.cog_name == "FailCog"
        assert event.success is False
        assert event.error_type == "RuntimeError"
        assert "something went wrong" in event.error_traceback
        assert event.user_id == "111"
        assert event.guild_id == "222"
        assert event.duration_ms > 0

    def test_records_error_with_zero_duration_when_no_start(self):
        _, on_error, service = self._make_handlers()
        ctx = MagicMock()
        ctx.command.qualified_name = "test"
        ctx.cog = None
        ctx._analytics_start = None  # override MagicMock auto-creation
        error = ValueError("no start time")
        _await(on_error(ctx, error))

        service.record_failure.assert_called_once()
        event = service.record_failure.call_args[0][0]
        assert event.success is False
        assert event.error_type == "ValueError"
        assert event.duration_ms == 0

    def test_records_command_invoke_error(self):
        """CommandInvokeError is NOT a UserInputError, so it is recorded."""
        _, on_error, service = self._make_handlers()
        ctx = MagicMock()
        ctx.command.qualified_name = "test"
        ctx.cog = None
        inner = ValueError("wrapped")
        error = commands.CommandInvokeError(inner)
        _await(on_error(ctx, error))
        service.record_failure.assert_called_once()

    def test_handles_ctx_with_no_command(self):
        _, on_error, service = self._make_handlers()
        ctx = MagicMock()
        ctx.command = None
        ctx.cog = None
        error = RuntimeError("no command")
        _await(on_error(ctx, error))

        service.record_failure.assert_called_once()
        event = service.record_failure.call_args[0][0]
        assert event.command_name == "unknown"
        assert event.cog_name is None
        assert event.success is False
