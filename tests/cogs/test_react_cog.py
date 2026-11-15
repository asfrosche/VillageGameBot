"""Tests for the `.react` command."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs import misc_cog


class TestParseReactArgs:
    def test_numbers_become_keycaps(self):
        emojis, unknown = misc_cog.parse_react_args("1,2,3")
        assert emojis == ["1️⃣", "2️⃣", "3️⃣"]
        assert unknown == []

    def test_numbers_up_to_ten(self):
        emojis, unknown = misc_cog.parse_react_args("1,2,3,4,5,6,7,8,9,10")
        assert emojis == [misc_cog.KEYCAP_EMOJIS[n] for n in range(1, 11)]
        assert emojis[-1] == "🔟"
        assert unknown == []

    def test_empty(self):
        assert misc_cog.parse_react_args("") == ([], [])

    def test_range(self):
        emojis, unknown = misc_cog.parse_react_args("1-5")
        assert emojis == [misc_cog.KEYCAP_EMOJIS[n] for n in range(1, 6)]
        assert unknown == []

    def test_spaced_range(self):
        emojis, _ = misc_cog.parse_react_args("1 - 3")
        assert emojis == ["1️⃣", "2️⃣", "3️⃣"]

    def test_word_spelled_in_letters(self):
        emojis, unknown = misc_cog.parse_react_args("hi")
        assert emojis == ["🇭", "🇮"]
        assert unknown == []

    def test_word_ignores_punctuation(self):
        emojis, _ = misc_cog.parse_react_args("hi!")
        assert emojis == ["🇭", "🇮"]

    def test_mixed_word_and_number(self):
        emojis, _ = misc_cog.parse_react_args("a1")
        assert emojis == ["🇦", "1️⃣"]

    def test_double_letter_uses_lookalike(self):
        emojis, unknown = misc_cog.parse_react_args("hello")
        assert emojis == ["🇭", "🇪", "🇱", "1️⃣", "🇴"]
        assert unknown == []

    def test_multiple_doubles_use_lookalikes(self):
        emojis, _ = misc_cog.parse_react_args("committee")
        assert emojis == ["🇨", "🇴", "🇲", "Ⓜ️", "🇮", "🇹", "7️⃣", "🇪", "3️⃣"]

    def test_double_vowels_use_digit_lookalikes(self):
        emojis, _ = misc_cog.parse_react_args("balloon")
        assert emojis == ["🇧", "🇦", "🇱", "1️⃣", "🇴", "0️⃣", "🇳"]

    def test_non_consecutive_repeat_also_substituted(self):
        emojis, _ = misc_cog.parse_react_args("tweet")
        assert emojis == ["🇹", "🇼", "🇪", "3️⃣", "7️⃣"]

    def test_third_repeat_uses_next_alternate(self):
        emojis, _ = misc_cog.parse_react_args("aaa")
        assert emojis == ["🇦", "4️⃣", "🅰️"]

    def test_extra_repeats_beyond_alternates_are_dropped(self):
        emojis, _ = misc_cog.parse_react_args("aaaa")
        assert emojis == ["🇦", "4️⃣", "🅰️"]

    def test_digit_lookalike_not_reused(self):
        # "e2" already uses 2️⃣ for the digit, so it can't stand in for z.
        emojis, _ = misc_cog.parse_react_args("ezz2")
        assert emojis == ["🇪", "🇿", "💤", "2️⃣"]

    def test_literal_emoji_kept(self):
        emojis, _ = misc_cog.parse_react_args("✅")
        assert emojis == ["✅"]

    def test_custom_emoji_kept(self):
        emojis, _ = misc_cog.parse_react_args("<:pepe:123456789>")
        assert emojis == ["<:pepe:123456789>"]

    def test_animated_custom_emoji_kept(self):
        emojis, _ = misc_cog.parse_react_args("<a:spin:987654321>")
        assert emojis == ["<a:spin:987654321>"]

    def test_duplicates_removed(self):
        emojis, _ = misc_cog.parse_react_args("1,1,2")
        assert emojis == ["1️⃣", "2️⃣"]

    def test_out_of_range_number_unknown(self):
        emojis, unknown = misc_cog.parse_react_args("20")
        assert emojis == []
        assert unknown == ["20"]

    def test_ascii_punctuation_unknown(self):
        emojis, unknown = misc_cog.parse_react_args("!")
        assert emojis == []
        assert unknown == ["!"]


def _make_ctx(admin=False, is_overseer=True, reply=True):
    overseer_role = MagicMock()
    overseer_role.name = "Overseer"

    author = MagicMock()
    author.guild_permissions.administrator = admin
    author.roles = [overseer_role] if is_overseer else []

    target = MagicMock()
    target.reactions = []
    target.add_reaction = AsyncMock()

    reference = MagicMock()
    reference.message_id = 555
    reference.resolved = MagicMock()  # deliberately not a discord.Message

    message = MagicMock()
    message.reference = reference if reply else None
    message.delete = AsyncMock()

    guild = MagicMock()
    guild.roles = [overseer_role]

    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=target)

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = author
    ctx.message = message
    ctx.channel = channel
    ctx.send = AsyncMock()
    return ctx, target


GUILD_DATA = {"overseer_role_name": "Overseer"}


class TestReactCommand:
    @pytest.mark.asyncio
    async def test_adds_reactions_and_deletes_command(self):
        cog = misc_cog.ReactCog(MagicMock())
        ctx, target = _make_ctx()
        with patch("cogs.misc_cog.load_guild_data", return_value=GUILD_DATA):
            await misc_cog.ReactCog.react.callback(cog, ctx, args="1,2,w")
        assert target.add_reaction.await_count == 3
        ctx.message.delete.assert_awaited_once()
        ctx.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_admin_can_use(self):
        cog = misc_cog.ReactCog(MagicMock())
        ctx, target = _make_ctx(admin=True, is_overseer=False)
        with patch("cogs.misc_cog.load_guild_data", return_value=GUILD_DATA):
            await misc_cog.ReactCog.react.callback(cog, ctx, args="1")
        assert target.add_reaction.await_count == 1

    @pytest.mark.asyncio
    async def test_non_staff_denied(self):
        cog = misc_cog.ReactCog(MagicMock())
        ctx, target = _make_ctx(admin=False, is_overseer=False)
        with patch("cogs.misc_cog.load_guild_data", return_value=GUILD_DATA):
            await misc_cog.ReactCog.react.callback(cog, ctx, args="1")
        target.add_reaction.assert_not_awaited()
        ctx.send.assert_awaited_once()
        assert "perms" in ctx.send.await_args.args[0]

    @pytest.mark.asyncio
    async def test_requires_reply(self):
        cog = misc_cog.ReactCog(MagicMock())
        ctx, _ = _make_ctx(reply=False)
        with patch("cogs.misc_cog.load_guild_data", return_value=GUILD_DATA):
            await misc_cog.ReactCog.react.callback(cog, ctx, args="1")
        ctx.send.assert_awaited_once()
        assert "Reply" in ctx.send.await_args.args[0]

    @pytest.mark.asyncio
    async def test_requires_arguments(self):
        cog = misc_cog.ReactCog(MagicMock())
        ctx, _ = _make_ctx()
        with patch("cogs.misc_cog.load_guild_data", return_value=GUILD_DATA):
            await misc_cog.ReactCog.react.callback(cog, ctx, args=None)
        ctx.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unparseable_arguments(self):
        cog = misc_cog.ReactCog(MagicMock())
        ctx, _ = _make_ctx()
        with patch("cogs.misc_cog.load_guild_data", return_value=GUILD_DATA):
            await misc_cog.ReactCog.react.callback(cog, ctx, args="20")
        ctx.send.assert_awaited_once()
        assert "couldn't understand" in ctx.send.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_caps_at_twenty_reactions(self):
        cog = misc_cog.ReactCog(MagicMock())
        ctx, target = _make_ctx()
        with patch("cogs.misc_cog.load_guild_data", return_value=GUILD_DATA):
            await misc_cog.ReactCog.react.callback(cog, ctx, args="abcdefghijklmnopqrstuvwxyz")
        assert target.add_reaction.await_count == misc_cog.MAX_REACTIONS
        texts = [
            call.args[0] for call in ctx.send.await_args_list if call.args
        ]
        assert any("at most" in text for text in texts)

    @pytest.mark.asyncio
    async def test_reports_failed_emojis(self):
        cog = misc_cog.ReactCog(MagicMock())
        ctx, target = _make_ctx()

        async def fail(_emoji):
            raise discord.HTTPException(MagicMock(), "boom")

        target.add_reaction = AsyncMock(side_effect=fail)
        with patch("cogs.misc_cog.load_guild_data", return_value=GUILD_DATA):
            await misc_cog.ReactCog.react.callback(cog, ctx, args="1")
        texts = [call.args[0] for call in ctx.send.await_args_list if call.args]
        assert any("Couldn't react" in text for text in texts)
