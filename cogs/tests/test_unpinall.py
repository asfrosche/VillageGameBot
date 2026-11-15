"""Tests for .unpinall: confirmation, permission check, pin order cleanup, and partial failures."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import pins_cog


def pin(mid, fail=False):
    m = MagicMock()
    m.id = mid
    m.unpin = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500, reason="x"), "fail") if fail else None)
    return m


def ctx_for(pins, manage=True):
    channel = MagicMock()
    channel.id = 42
    channel.mention = "#general"
    channel.pins = AsyncMock(return_value=pins)
    ctx = MagicMock()
    ctx.guild.id = 1
    ctx.channel = channel
    ctx.author.guild_permissions.manage_messages = manage
    prompt = MagicMock()
    prompt.edit = AsyncMock()
    ctx.send = AsyncMock(return_value=prompt)
    return ctx, channel, prompt


def run(ctx, result):
    cog = object.__new__(pins_cog.PinsCog)

    async def fake_wait(self):
        self.result = result

    with patch.object(pins_cog.UnpinAllView, "wait", fake_wait), \
            patch.object(pins_cog, "load_guild_data", return_value={"pins_manager": {"42": [1, 2]}}), \
            patch.object(pins_cog, "save_guild_data") as save:
        asyncio.run(pins_cog.PinsCog.unpinall.callback(cog, ctx, channel=None))
    return save


class TestUnpinAll:
    def test_without_manage_messages_nothing_is_read_or_removed(self):
        pins = [pin(1), pin(2)]
        ctx, channel, prompt = ctx_for(pins, manage=False)
        run(ctx, True)
        channel.pins.assert_not_awaited()
        assert all(not p.unpin.await_count for p in pins)

    def test_no_pins_says_so(self):
        ctx, channel, prompt = ctx_for([])
        run(ctx, True)
        assert "no pinned messages" in ctx.send.await_args.args[0]

    def test_confirm_unpins_every_message_and_clears_the_saved_order(self):
        pins = [pin(1), pin(2), pin(3)]
        ctx, channel, prompt = ctx_for(pins)
        save = run(ctx, True)
        assert all(p.unpin.await_count == 1 for p in pins)
        saved = save.call_args.args[1]
        assert "42" not in saved["pins_manager"]
        assert "Unpinned **3** message(s)" in ctx.send.await_args.args[0]

    def test_cancel_removes_nothing(self):
        pins = [pin(1), pin(2)]
        ctx, channel, prompt = ctx_for(pins)
        save = run(ctx, False)
        assert all(p.unpin.await_count == 0 for p in pins)
        save.assert_not_called()

    def test_timeout_removes_nothing_and_says_so(self):
        pins = [pin(1)]
        ctx, channel, prompt = ctx_for(pins)
        run(ctx, None)
        assert pins[0].unpin.await_count == 0
        prompt.edit.assert_awaited_once()
        assert "Timed out" in prompt.edit.await_args.kwargs["content"]

    def test_failures_are_counted_and_reported(self):
        pins = [pin(1), pin(2, fail=True), pin(3)]
        ctx, channel, prompt = ctx_for(pins)
        run(ctx, True)
        report = ctx.send.await_args.args[0]
        assert "Unpinned **2** message(s)" in report
        assert "1 could not be unpinned" in report


class TestConfirmationView:
    def test_only_the_person_who_asked_can_answer(self):
        async def make():
            return pins_cog.UnpinAllView(MagicMock(id=1), 3)
        view = asyncio.run(make())
        intruder = MagicMock()
        intruder.id = 2
        interaction = MagicMock()
        interaction.user = intruder
        interaction.response.send_message = AsyncMock()
        allowed = asyncio.run(view.interaction_check(interaction))
        assert allowed is False
        interaction.response.send_message.assert_awaited_once()
