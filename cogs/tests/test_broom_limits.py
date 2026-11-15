"""Tests for broom_delete: the shop broom must delete everything, .broom keeps its cap,
and messages near the 14-day bulk-delete limit go one by one."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import utility_cog


def message(age_days):
    msg = MagicMock()
    msg.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    msg.content = "hi"
    msg.author = "someone"
    msg.delete = AsyncMock()
    return msg


def target():
    channel = MagicMock()
    channel.delete_messages = AsyncMock()
    channel.send = AsyncMock()
    channel.mention = "#house"
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.channel = channel
    ctx.author = MagicMock()
    ctx.author.__str__ = lambda self: "author"
    return ctx


def run_broom(messages, **kwargs):
    ctx = target()
    cog = object.__new__(utility_cog.Utility)
    with patch.object(utility_cog, "load_guild_data", return_value={}), \
            patch.object(utility_cog.asyncio, "sleep", AsyncMock()):
        asyncio.run(cog.broom_delete(ctx, messages, **kwargs))
    return ctx


class TestIndividualLimit:
    def test_default_cap_deletes_fifty_old_messages_and_reports_the_rest(self):
        old = [message(30) for _ in range(60)]
        ctx = run_broom(old)
        deleted = sum(1 for m in old if m.delete.await_count)
        assert deleted == 50
        report = ctx.channel.send.await_args.args[0]
        assert "Skipped **10**" in report

    def test_no_limit_deletes_every_old_message(self):
        old = [message(30) for _ in range(60)]
        ctx = run_broom(old, individual_limit=None)
        assert all(m.delete.await_count == 1 for m in old)
        report = ctx.channel.send.await_args.args[0]
        assert "Skipped" not in report
        assert "swept away **60**" in report

    def test_explicit_limit_is_respected(self):
        old = [message(30) for _ in range(10)]
        run_broom(old, individual_limit=3)
        assert sum(m.delete.await_count for m in old) == 3


class TestBulkBoundary:
    def test_recent_messages_are_bulk_deleted(self):
        recent = [message(2) for _ in range(3)]
        ctx = run_broom(recent, individual_limit=None)
        ctx.channel.delete_messages.assert_awaited_once()
        assert len(ctx.channel.delete_messages.await_args.args[0]) == 3
        assert all(m.delete.await_count == 0 for m in recent)

    def test_messages_between_thirteen_and_fourteen_days_are_not_bulk_deleted(self):
        edge = message(13.5)
        ctx = run_broom([edge], individual_limit=None)
        ctx.channel.delete_messages.assert_not_awaited()
        assert edge.delete.await_count == 1

    def test_mixed_batch_splits_by_age(self):
        recent = message(1)
        edge = message(13.5)
        ancient = message(40)
        ctx = run_broom([recent, edge, ancient], individual_limit=None)
        bulk = ctx.channel.delete_messages.await_args.args[0]
        assert bulk == [recent]
        assert edge.delete.await_count == 1
        assert ancient.delete.await_count == 1


class TestFailuresAreReported:
    def test_refused_deletes_are_counted_and_reported(self):
        refused = discord.HTTPException(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")
        ok = message(30)
        bad = message(30)
        bad.delete = AsyncMock(side_effect=refused)
        ctx = run_broom([ok, bad], individual_limit=None)
        report = ctx.channel.send.await_args.args[0]
        assert "swept away **1** messages" in report
        assert "Could not delete **1** message(s)" in report
        assert "Missing Permissions" in report
        assert ctx.channel.send.await_args.kwargs.get("delete_after") is None

    def test_failed_bulk_batch_falls_back_and_reports_only_real_failures(self):
        refused = discord.HTTPException(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")
        recent = [message(1), message(1)]
        recent[1].delete = AsyncMock(side_effect=refused)
        ctx = target()
        ctx.channel.delete_messages = AsyncMock(side_effect=refused)
        cog = object.__new__(utility_cog.Utility)
        with patch.object(utility_cog, "load_guild_data", return_value={}), \
                patch.object(utility_cog.asyncio, "sleep", AsyncMock()):
            result = asyncio.run(cog.broom_delete(ctx, recent, individual_limit=None))
        assert result == {"deleted": 1, "failed": 1, "skipped": 0}

    def test_already_deleted_messages_are_not_reported_as_failures(self):
        gone = discord.NotFound(MagicMock(status=404, reason="Not Found"), "Unknown Message")
        gone_msg = message(30)
        gone_msg.delete = AsyncMock(side_effect=gone)
        ctx = run_broom([gone_msg], individual_limit=None)
        report = ctx.channel.send.await_args.args[0]
        assert "Could not delete" not in report
        assert ctx.channel.send.await_args.kwargs.get("delete_after") == 5

    def test_clean_run_auto_hides_the_report(self):
        ctx = run_broom([message(30)], individual_limit=None)
        assert ctx.channel.send.await_args.kwargs.get("delete_after") == 5


class TestReplyTargetIsIncluded:
    def _run_shop_broom(self, pinned_anchor):
        from cogs import economy_cog

        anchor = MagicMock(spec=discord.Message)
        anchor.pinned = pinned_anchor
        later = message(1)
        later.pinned = False

        class Hist:
            def __init__(self, items):
                self.items = list(items)

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.items:
                    raise StopAsyncIteration
                return self.items.pop(0)

        reply = MagicMock()
        reply.reference.resolved = anchor
        reply.reference.message_id = 1
        ctx = MagicMock()
        ctx.author = MagicMock()
        ctx.channel.history = MagicMock(side_effect=lambda **kw: Hist([later]))
        ctx.send = AsyncMock(return_value=MagicMock(id=99))
        ctx.bot.wait_for = AsyncMock(return_value=reply)
        utility = MagicMock()
        utility.broom_delete = AsyncMock(return_value={"deleted": 0, "failed": 0, "skipped": 0})
        ctx.bot.get_cog.return_value = utility

        cog = object.__new__(economy_cog.Economy)
        ok = asyncio.run(cog._trigger_broom(ctx))
        swept = utility.broom_delete.await_args.args[1] if utility.broom_delete.await_args else None
        return ok, anchor, later, swept

    def test_replied_to_message_is_swept_with_the_rest(self):
        ok, anchor, later, swept = self._run_shop_broom(pinned_anchor=False)
        assert ok is True
        assert swept[0] is anchor
        assert later in swept

    def test_pinned_replied_to_message_is_kept(self):
        ok, anchor, later, swept = self._run_shop_broom(pinned_anchor=True)
        assert anchor not in swept
        assert later in swept
