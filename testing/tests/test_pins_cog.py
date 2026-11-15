"""Tests for the `.pins` manager ordering logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs import pins_cog


def _make_message(mid):
    msg = MagicMock()
    msg.id = mid
    msg.content = f"message {mid}"
    msg.embeds = []
    msg.attachments = []
    msg.jump_url = f"https://discord.com/channels/1/2/{mid}"
    msg.author.mention = f"<@{mid}>"
    msg.pin = AsyncMock()
    msg.unpin = AsyncMock()
    return msg


def _make_channel(pinned, after=None, fetch_fail=False):
    channel = MagicMock()
    channel.name = "test-channel"
    by_id = {m.id: m for m in pinned}
    channel.fetch_message = AsyncMock(side_effect=lambda mid: by_id[mid])
    if fetch_fail:
        channel.pins = AsyncMock(side_effect=Exception("boom"))
    else:
        results = [list(pinned)]
        if after is not None:
            results.append(list(after))
        channel.pins = AsyncMock(side_effect=results)
    return channel


def _make_interaction(channel):
    interaction = MagicMock()
    interaction.channel = channel
    interaction.response.edit_message = AsyncMock()
    return interaction


async def _apply(channel, order):
    guild_data = {"pins_manager": {"99": list(order)}}
    view = pins_cog.PinsManagerView(MagicMock(), 1, 99)
    interaction = _make_interaction(channel)
    with patch("cogs.pins_cog.load_guild_data", return_value=guild_data), \
         patch("cogs.pins_cog.save_guild_data") as save, \
         patch("cogs.pins_cog.asyncio.sleep", new=AsyncMock()):
        await view._apply_native(interaction)
    return guild_data, save, interaction


def _record_calls(messages):
    calls = []
    for msg in messages:
        mid = msg.id
        msg.unpin = AsyncMock(side_effect=lambda mid=mid: calls.append(("unpin", mid)))
        msg.pin = AsyncMock(side_effect=lambda mid=mid: calls.append(("pin", mid)))
    return calls


def _actions(calls, action):
    return [mid for kind, mid in calls if kind == action]


class TestMergeReorderSequence:
    def test_clicked_pins_go_first(self):
        assert pins_cog.merge_reorder_sequence([3, 1], [1, 2, 3]) == [3, 1, 2]

    def test_unclicked_pins_are_kept(self):
        assert pins_cog.merge_reorder_sequence([2], [1, 2, 3]) == [2, 1, 3]

    def test_empty_sequence_keeps_order(self):
        assert pins_cog.merge_reorder_sequence([], [1, 2, 3]) == [1, 2, 3]


class TestApplyNative:
    @pytest.mark.asyncio
    async def test_pins_in_reverse_so_first_saved_pin_ends_up_on_top(self):
        messages = [_make_message(1), _make_message(2), _make_message(3)]
        calls = _record_calls(messages)
        channel = _make_channel(messages, after=[messages[2], messages[0], messages[1]])

        await _apply(channel, [3, 1, 2])

        # Discord lists the newest pin first, so the desired top pin is pinned last.
        assert _actions(calls, "pin") == [2, 1, 3]

    @pytest.mark.asyncio
    async def test_all_current_pins_are_unpinned(self):
        messages = [_make_message(1), _make_message(2)]
        calls = _record_calls(messages)
        channel = _make_channel(messages, after=messages)

        await _apply(channel, [1, 2])

        assert sorted(_actions(calls, "unpin")) == [1, 2]

    @pytest.mark.asyncio
    async def test_saves_the_order_discord_actually_returned(self):
        messages = [_make_message(1), _make_message(2), _make_message(3)]
        channel = _make_channel(messages, after=[messages[2], messages[0], messages[1]])

        guild_data, save, _ = await _apply(channel, [3, 1, 2])

        assert guild_data["pins_manager"]["99"] == [3, 1, 2]
        save.assert_called_once()

    @pytest.mark.asyncio
    async def test_pins_added_outside_the_manager_are_not_lost(self):
        messages = [_make_message(1), _make_message(2), _make_message(3)]
        calls = _record_calls(messages)
        channel = _make_channel(messages, after=[messages[1], messages[0], messages[2]])

        await _apply(channel, [2])

        # Saved pin first, then the extras, so all three get repinned.
        assert sorted(_actions(calls, "pin")) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_does_nothing_when_pins_cannot_be_fetched(self):
        messages = [_make_message(1)]
        calls = _record_calls(messages)
        channel = _make_channel(messages, fetch_fail=True)

        guild_data, save, interaction = await _apply(channel, [1])

        assert _actions(calls, "unpin") == []
        assert _actions(calls, "pin") == []
        save.assert_not_called()
        assert guild_data["pins_manager"]["99"] == [1]
        embed = interaction.response.edit_message.await_args.kwargs["embed"]
        assert "Couldn't read" in embed.description

    @pytest.mark.asyncio
    async def test_no_saved_order_sends_notice(self):
        channel = _make_channel([])

        _, save, interaction = await _apply(channel, [])

        save.assert_not_called()
        embed = interaction.response.edit_message.await_args.kwargs["embed"]
        assert "No pins to apply" in embed.description

    @pytest.mark.asyncio
    async def test_reports_failed_operations(self):
        messages = [_make_message(1), _make_message(2)]
        calls = _record_calls(messages)
        messages[0].pin = AsyncMock(side_effect=Exception("nope"))
        channel = _make_channel(messages, after=messages)

        _, _, interaction = await _apply(channel, [1, 2])

        # Apply still finishes and saves the order even if one pin fails.
        assert _actions(calls, "unpin") == [1, 2]
        embed = interaction.response.edit_message.await_args.kwargs["embed"]
        assert "failed" in embed.description
