"""Tests for the Discord-compatibility fixes: thread members, length limits, transient errors,
category limits, edit-limit fallbacks and user-facing failure messages."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from utils import discord_safe as ds


# ── helpers ────────────────────────────────────────────────────────────────

def make_http_error(status=400, code=0, text="error"):
    error = discord.HTTPException(MagicMock(status=status, reason="reason"), text)
    error.code = code
    return error


# ── split_text / chunk_fields / add_text_fields ────────────────────────────

class TestSplitText:
    def test_short_text_is_unchanged(self):
        assert ds.split_text("hello", 10) == ["hello"]

    def test_splits_on_line_breaks_and_keeps_every_line(self):
        text = "\n".join(f"line {i:03d}" for i in range(100))
        chunks = ds.split_text(text, 200)
        assert all(len(chunk) <= 200 for chunk in chunks)
        assert "\n".join(chunks).split("\n") == text.split("\n")

    def test_hard_splits_a_single_line_longer_than_limit(self):
        chunks = ds.split_text("x" * 2500, 1000)
        assert [len(c) for c in chunks] == [1000, 1000, 500]
        assert "".join(chunks) == "x" * 2500

    def test_rejects_non_positive_limit(self):
        with pytest.raises(ValueError):
            ds.split_text("abc", 0)


class TestChunkFields:
    def test_each_value_fits_the_field_limit(self):
        items = ["a" * 300, "b" * 2000, "short"]
        values = ds.chunk_fields(items)
        assert values
        assert all(len(v) <= ds.EMBED_FIELD_VALUE_LIMIT for v in values)

    def test_empty_input_gives_no_values(self):
        assert ds.chunk_fields([]) == []


class TestAddTextFields:
    def test_long_text_becomes_several_fields_within_limits(self):
        embed = discord.Embed()
        ds.add_text_fields(embed, "Message:", "word " * 800)  # ~4000 chars
        assert len(embed.fields) > 1
        assert all(len(f.value) <= ds.EMBED_FIELD_VALUE_LIMIT for f in embed.fields)
        assert embed.fields[1].name.endswith("(part 2)")

    def test_short_text_is_a_single_field(self):
        embed = discord.Embed()
        ds.add_text_fields(embed, "Name:", "value")
        assert len(embed.fields) == 1
        assert embed.fields[0].name == "Name:"
        assert embed.fields[0].value == "value"


# ── retries ────────────────────────────────────────────────────────────────

class TestWithRetries:
    def test_retries_rate_limits_then_succeeds(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise make_http_error(429)
            return "ok"

        result = asyncio.run(ds.with_retries(flaky, attempts=3, base_delay=0))
        assert result == "ok"
        assert calls["n"] == 3

    def test_retries_server_errors(self):
        async def down():
            raise make_http_error(503)

        with pytest.raises(discord.HTTPException):
            asyncio.run(ds.with_retries(down, attempts=2, base_delay=0))

    def test_does_not_retry_permanent_errors(self):
        calls = {"n": 0}

        async def forbidden():
            calls["n"] += 1
            raise make_http_error(403)

        with pytest.raises(discord.HTTPException):
            asyncio.run(ds.with_retries(forbidden, attempts=3, base_delay=0))
        assert calls["n"] == 1


# ── user-facing messages ───────────────────────────────────────────────────

class TestUserFacingMessage:
    def test_forbidden_gets_permission_message(self):
        forbidden = discord.Forbidden(MagicMock(status=403, reason="x"), "Missing Permissions")
        assert "permission" in ds.user_facing_message(forbidden).lower()

    def test_wrapped_forbidden_is_unwrapped(self):
        forbidden = discord.Forbidden(MagicMock(status=403, reason="x"), "Missing Permissions")
        wrapped = commands.CommandInvokeError(forbidden)
        assert "permission" in ds.user_facing_message(wrapped).lower()

    def test_category_full_message(self):
        assert "full" in ds.user_facing_message(make_http_error(400, code=ds.CATEGORY_FULL_CODE)).lower()

    def test_edit_limit_message(self):
        assert "edited" in ds.user_facing_message(make_http_error(400, code=ds.EDIT_LIMIT_CODE)).lower()

    def test_rate_limit_and_outage_messages(self):
        assert "rate limited" in ds.user_facing_message(make_http_error(429)).lower()
        assert "temporary" in ds.user_facing_message(make_http_error(503)).lower()

    def test_unknown_errors_return_none(self):
        assert ds.user_facing_message(ValueError("boom")) is None

    def test_wrapped_unknown_error_returns_none(self):
        assert ds.user_facing_message(commands.CommandInvokeError(ValueError("boom"))) is None


# ── embed guard ────────────────────────────────────────────────────────────

class TestEmbedGuard:
    def test_oversized_value_is_truncated_not_raised(self):
        ds.install_embed_guard()
        embed = discord.Embed()
        embed.add_field(name="Big", value="z" * 5000, inline=False)
        assert len(embed.fields[0].value) == ds.EMBED_FIELD_VALUE_LIMIT

    def test_empty_value_gets_placeholder(self):
        ds.install_embed_guard()
        embed = discord.Embed()
        embed.add_field(name="Empty", value="", inline=False)
        assert embed.fields[0].value == "​"

    def test_install_is_idempotent(self):
        ds.install_embed_guard()
        first = discord.Embed.add_field
        ds.install_embed_guard()
        assert discord.Embed.add_field is first


# ── handling cog: category moves and role pings ────────────────────────────

class TestMoveChannelOrWarn:
    def _channel(self, current_category=None):
        channel = MagicMock()
        channel.category = current_category
        channel.mention = "#house"
        channel.edit = AsyncMock()
        return channel

    def test_full_category_returns_warning_without_moving(self):
        from cogs.handling_cog import move_channel_or_warn
        category = MagicMock()
        category.name = "INACCESSIBLE"
        category.channels = [MagicMock() for _ in range(50)]
        channel = self._channel()
        warning = asyncio.run(move_channel_or_warn(channel, category))
        assert "full" in warning
        channel.edit.assert_not_awaited()

    def test_moves_when_there_is_room(self):
        from cogs.handling_cog import move_channel_or_warn
        category = MagicMock()
        category.channels = [MagicMock() for _ in range(3)]
        channel = self._channel()
        assert asyncio.run(move_channel_or_warn(channel, category)) is None
        channel.edit.assert_awaited_once_with(category=category)

    def test_discord_reports_full_even_when_cache_says_room(self):
        from cogs.handling_cog import move_channel_or_warn
        category = MagicMock()
        category.name = "OLD PCS"
        category.channels = []
        channel = self._channel()
        channel.edit = AsyncMock(side_effect=make_http_error(400, code=ds.CATEGORY_FULL_CODE))
        assert "full" in asyncio.run(move_channel_or_warn(channel, category))

    def test_already_in_category_is_a_no_op(self):
        from cogs.handling_cog import move_channel_or_warn
        category = MagicMock()
        channel = self._channel(current_category=category)
        assert asyncio.run(move_channel_or_warn(channel, category)) is None
        channel.edit.assert_not_awaited()


class TestRolePings:
    def test_skips_missing_roles(self):
        from cogs.handling_cog import role_pings
        alive = MagicMock(mention="@Alive")
        assert role_pings(alive, None) == "@Alive"

    def test_all_missing_gives_empty_string(self):
        from cogs.handling_cog import role_pings
        assert role_pings(None, None) == ""


# ── estate and vote board: edit-limit fallbacks ────────────────────────────

class TestEstateMapPublish:
    def test_edit_limit_posts_fresh_message_and_saves_id(self, monkeypatch):
        from cogs import estate_cog
        saved = {}
        monkeypatch.setattr(estate_cog, "save_guild_data", lambda gid, data: saved.update(data))
        cog = object.__new__(estate_cog.Estate)

        old = MagicMock()
        old.edit = AsyncMock(side_effect=make_http_error(400, code=ds.EDIT_LIMIT_CODE))
        old.delete = AsyncMock()
        new = MagicMock(id=777)
        channel = MagicMock()
        channel.guild.id = 1
        channel.send = AsyncMock(return_value=new)
        guild_data = {"estate_directory": {"message_id": 5}}

        result = asyncio.run(cog._publish_map(channel, old, guild_data, [("map.png", b"png")]))
        assert result is new
        old.delete.assert_awaited_once()
        assert guild_data["estate_directory"]["message_id"] == 777

    def test_successful_edit_keeps_message(self):
        from cogs import estate_cog
        cog = object.__new__(estate_cog.Estate)
        msg = MagicMock()
        msg.edit = AsyncMock()
        result = asyncio.run(cog._publish_map(MagicMock(), msg, {"estate_directory": {}}, [("m.png", b"x")]))
        assert result is msg
        msg.edit.assert_awaited_once()

    def test_other_edit_errors_are_raised(self):
        from cogs import estate_cog
        cog = object.__new__(estate_cog.Estate)
        msg = MagicMock()
        msg.edit = AsyncMock(side_effect=make_http_error(403, code=50013))
        with pytest.raises(discord.HTTPException):
            asyncio.run(cog._publish_map(MagicMock(), msg, {"estate_directory": {}}, [("m.png", b"x")]))


class TestVoteBoardRefresh:
    def test_edit_limit_reposts_board_message(self):
        from cogs import voting_cog
        cog = object.__new__(voting_cog.Voting)
        existing = MagicMock()
        existing.edit = AsyncMock(side_effect=make_http_error(400, code=ds.EDIT_LIMIT_CODE))
        existing.delete = AsyncMock()
        board = MagicMock()
        board.send = AsyncMock()
        asyncio.run(cog._refresh_board_message(board, existing, "# LYNCH VOTES 1:\n"))
        existing.delete.assert_awaited_once()
        board.send.assert_awaited_once_with("# LYNCH VOTES 1:\n")

    def test_successful_edit_does_not_repost(self):
        from cogs import voting_cog
        cog = object.__new__(voting_cog.Voting)
        existing = MagicMock()
        existing.edit = AsyncMock()
        board = MagicMock()
        board.send = AsyncMock()
        asyncio.run(cog._refresh_board_message(board, existing, "body"))
        existing.edit.assert_awaited_once()
        board.send.assert_not_awaited()


# ── PC category families (main + numbered overflow) ────────────────────────

def fake_category(name, channels=0):
    category = MagicMock()
    category.name = name
    category.channels = [MagicMock() for _ in range(channels)]
    return category


class TestCategoryFamily:
    def test_main_and_numbered_overflow_are_found_in_order(self):
        cats = [fake_category("PRIVATE CHANNELS 2"), fake_category("OTHER"),
                fake_category("PRIVATE CHANNELS"), fake_category("PRIVATE CHANNELS 10")]
        names = [c.name for c in ds.category_family(cats, "PRIVATE CHANNELS")]
        assert names == ["PRIVATE CHANNELS", "PRIVATE CHANNELS 2", "PRIVATE CHANNELS 10"]

    def test_match_is_case_insensitive(self):
        cats = [fake_category("private channels 3")]
        assert [c.name for c in ds.category_family(cats, "PRIVATE CHANNELS")] == ["private channels 3"]

    def test_base_name_is_not_matched_as_a_substring(self):
        cats = [fake_category("DEAD RC"), fake_category("RC 1")]
        assert [c.name for c in ds.category_family(cats, "RC")] == ["RC 1"]

    def test_unrelated_names_containing_the_base_are_ignored(self):
        cats = [fake_category("OLD PRIVATE CHANNELS"), fake_category("PRIVATE CHANNELS (archive)")]
        assert ds.category_family(cats, "PRIVATE CHANNELS") == []

    def test_empty_base_matches_nothing(self):
        assert ds.category_family([fake_category("X")], "") == []
        assert ds.category_family([fake_category("X")], None) == []


class TestNextFamilyName:
    def test_first_overflow_is_two(self):
        cats = [fake_category("PRIVATE CHANNELS")]
        assert ds.next_family_name(cats, "PRIVATE CHANNELS") == "PRIVATE CHANNELS 2"

    def test_uses_highest_number_not_count_after_a_deletion(self):
        # PRIVATE CHANNELS 1 was deleted; 2 and 3 exist. Count-based naming would reuse "3".
        cats = [fake_category("PRIVATE CHANNELS"), fake_category("PRIVATE CHANNELS 2"),
                fake_category("PRIVATE CHANNELS 3")]
        assert ds.next_family_name(cats, "PRIVATE CHANNELS") == "PRIVATE CHANNELS 4"

    def test_no_existing_categories_starts_at_two(self):
        assert ds.next_family_name([], "OLD PCS") == "OLD PCS 2"


class TestFamilyChannels:
    def test_collects_channels_from_every_category(self):
        a = fake_category("A", channels=2)
        b = fake_category("B", channels=3)
        assert len(ds.family_channels([a, b])) == 5

    def test_empty_list_gives_no_channels(self):
        assert ds.family_channels([]) == []


class TestOverflowCategoryCreation:
    def _guild(self, categories):
        guild = MagicMock()
        guild.categories = categories
        guild.default_role = MagicMock()
        new = MagicMock()
        new.set_permissions = AsyncMock()
        guild.create_category = AsyncMock(return_value=new)
        guild.roles = []
        return guild

    def test_returns_main_when_it_has_room(self):
        from cogs.handling_cog import get_pc_category
        main = fake_category("PRIVATE CHANNELS", channels=3)
        guild = self._guild([main])
        assert asyncio.run(get_pc_category(guild, {"privc_category_name": "PRIVATE CHANNELS"}, "private")) is main
        guild.create_category.assert_not_awaited()

    def test_creates_next_numbered_category_when_all_full(self):
        from cogs.handling_cog import get_pc_category
        main = fake_category("PRIVATE CHANNELS", channels=50)
        overflow = fake_category("PRIVATE CHANNELS 2", channels=50)
        guild = self._guild([main, overflow])
        guild.create_category.return_value.name = "PRIVATE CHANNELS 3"
        result = asyncio.run(get_pc_category(guild, {"privc_category_name": "PRIVATE CHANNELS"}, "private"))
        guild.create_category.assert_awaited_once_with("PRIVATE CHANNELS 3")
        assert result is guild.create_category.return_value

    def test_returns_full_category_when_creation_fails(self):
        from cogs.handling_cog import get_pc_category
        main = fake_category("PRIVATE CHANNELS", channels=50)
        guild = self._guild([main])
        guild.create_category = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=400, reason="x"), "no"))
        assert asyncio.run(get_pc_category(guild, {"privc_category_name": "PRIVATE CHANNELS"}, "private")) is main

    def test_no_base_category_returns_none(self):
        from cogs.handling_cog import get_pc_category
        guild = self._guild([fake_category("SOMETHING ELSE")])
        assert asyncio.run(get_pc_category(guild, {"privc_category_name": "PRIVATE CHANNELS"}, "private")) is None


class TestSideChannelRemoval:
    def test_removes_member_from_every_family_channel_where_they_can_send(self):
        from cogs import utility_cog
        cog = object.__new__(utility_cog.Utility)
        member = MagicMock()
        member.mention = "@player"

        def channel(can_send):
            ch = MagicMock()
            ch.permissions_for.return_value = MagicMock(send_messages=can_send)
            ch.set_permissions = AsyncMock()
            ch.send = AsyncMock()
            return ch

        yes_main, no_main = channel(True), channel(False)
        yes_overflow = channel(True)
        cats = [fake_category("PRIVATE CHANNELS"), fake_category("PRIVATE CHANNELS 2")]
        cats[0].channels = [yes_main, no_main]
        cats[1].channels = [yes_overflow]

        asyncio.run(cog._remove_member_from_side_channels(member, cats))
        yes_main.set_permissions.assert_awaited_once()
        yes_overflow.set_permissions.assert_awaited_once()
        no_main.set_permissions.assert_not_awaited()
        yes_main.send.assert_awaited_once()

    def test_announce_false_clears_access_silently(self):
        from cogs import utility_cog
        cog = object.__new__(utility_cog.Utility)
        member = MagicMock()
        ch = MagicMock()
        ch.permissions_for.return_value = MagicMock(send_messages=True)
        ch.set_permissions = AsyncMock()
        ch.send = AsyncMock()
        category = fake_category("OLD PCS")
        category.channels = [ch]
        asyncio.run(cog._remove_member_from_side_channels(member, [category], announce=False))
        ch.set_permissions.assert_awaited_once()
        ch.send.assert_not_awaited()
