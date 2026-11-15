"""Tests for .use routing, rolechat lookup and fireworks in the economy cog."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import economy_cog


def cat(name, channels=()):
    c = MagicMock()
    c.name = name
    c.text_channels = list(channels)
    return c


def role(name):
    r = MagicMock()
    r.name = name
    r.mention = f"@{name}"
    return r


GUILD_DATA = {
    "alive_role_name": "Alive",
    "sponsor_role_name": "Sponsor",
    "rc_category_name": "ROLES",
    "alt_category_name": "ALTs",
    "dead_rc_category_name": "DEAD ROLES",
    "houses_category_name": "HOUSES",
    "announcements_channel_name": "announcements",
}


def make_guild(categories, roles):
    guild = MagicMock()
    guild.categories = categories
    guild.roles = roles
    return guild


class TestCategoryChecks:
    def test_channel_without_category_is_not_a_rolechat_even_if_configs_missing(self):
        guild = make_guild([], [])
        ctx = MagicMock()
        ctx.guild = guild
        ctx.channel = MagicMock(category=None)
        assert economy_cog._is_rolechat_category(ctx, guild_data={}) is False

    def test_channel_without_category_is_not_a_house_even_if_configs_missing(self):
        guild = make_guild([], [])
        ctx = MagicMock()
        ctx.guild = guild
        ctx.channel = MagicMock(category=None)
        assert economy_cog._is_houses_category(ctx, guild_data={}) is False

    def test_player_rolechat_channels_include_alts(self):
        rc_ch, alt_ch = MagicMock(), MagicMock()
        guild = make_guild([cat("ROLES", [rc_ch]), cat("ALTs", [alt_ch])], [])
        assert economy_cog._player_rolechat_channels(guild, GUILD_DATA) == [rc_ch, alt_ch]

    def test_players_rolechat_finds_the_author_in_an_alt(self):
        alt_ch = MagicMock()
        alt_ch.members = []
        author = MagicMock()
        alt_ch.members = [author]
        alt_ch.permissions_for.return_value = MagicMock(send_messages=True)
        guild = make_guild([cat("ALTs", [alt_ch])], [])
        ctx = MagicMock(guild=guild, author=author)
        assert economy_cog._players_rolechat(ctx, GUILD_DATA) is alt_ch

    def test_players_rolechat_reports_when_not_found(self):
        guild = make_guild([cat("ROLES", [])], [])
        ctx = MagicMock(guild=guild, author=MagicMock())
        assert isinstance(economy_cog._players_rolechat(ctx, GUILD_DATA), str)


class FakeCtx:
    """Minimal command context for driving use_item."""

    def __init__(self, channel_category, author_roles, guild):
        self.guild = guild
        self.author = MagicMock()
        self.author.roles = author_roles
        self.channel = MagicMock()
        self.channel.category = channel_category
        self.channel.id = 555
        self.channel.mention = "#here"
        self.send = AsyncMock()


def run_use(cog, ctx, item_name, owned):
    """Run .use with a resolved item and report whether it was consumed."""
    async def fake_resolve(_ctx, _channel_id, _query):
        return owned

    async def go():
        with patch.object(economy_cog, "load_guild_data", return_value=GUILD_DATA), \
                patch.object(economy_cog, "add_inventory_item_channel") as consume, \
                patch.object(economy_cog, "_log_economy", AsyncMock()):
            cog._resolve_inventory_item = fake_resolve
            await economy_cog.Economy.use_item.callback(cog, ctx, item_name=item_name)
            return consume

    return asyncio.run(go())


def setup_guild_with_categories():
    houses = cat("HOUSES")
    rc = cat("ROLES", [])
    alive = role("Alive")
    sponsor = role("Sponsor")
    guild = make_guild([houses, rc], [alive, sponsor])
    return guild, houses, rc, alive, sponsor


class TestUseRouting:
    def test_partial_broom_name_in_a_house_runs_the_broom(self):
        guild, houses, rc, alive, sponsor = setup_guild_with_categories()
        ctx = FakeCtx(houses, [alive], guild)
        cog = object.__new__(economy_cog.Economy)
        cog._trigger_broom = AsyncMock(return_value=True)
        owned = {"item_id": 1, "name": "🧹 Broom", "quantity": 1}

        # The author's rolechat is needed for house items; make one they can read.
        rc_ch = MagicMock()
        rc_ch.members = [ctx.author]
        rc_ch.permissions_for.return_value = MagicMock(send_messages=True)
        rc.text_channels = [rc_ch]

        consume = run_use(cog, ctx, "brm", owned)
        cog._trigger_broom.assert_awaited_once()
        consume.assert_called_once()
        assert "RoleChat" not in str(ctx.send.await_args_list)

    def test_peep_hole_typed_in_a_rolechat_is_refused_and_not_consumed(self):
        guild, houses, rc, alive, sponsor = setup_guild_with_categories()
        ctx = FakeCtx(rc, [alive], guild)
        cog = object.__new__(economy_cog.Economy)
        cog._trigger_peephole = AsyncMock(return_value=True)
        owned = {"item_id": 2, "name": "🔭 Peep Hole", "quantity": 1}

        consume = run_use(cog, ctx, "peep", owned)
        cog._trigger_peephole.assert_not_awaited()
        consume.assert_not_called()
        assert "House channel" in str(ctx.send.await_args)

    def test_rolechat_item_typed_in_a_house_is_refused(self):
        guild, houses, rc, alive, sponsor = setup_guild_with_categories()
        ctx = FakeCtx(houses, [alive], guild)
        cog = object.__new__(economy_cog.Economy)
        cog._trigger_whisper = AsyncMock(return_value=True)
        owned = {"item_id": 3, "name": "✉ Whisper", "quantity": 1}

        rc_ch = MagicMock()
        rc_ch.members = [ctx.author]
        rc_ch.permissions_for.return_value = MagicMock(send_messages=True)
        rc.text_channels = [rc_ch]

        consume = run_use(cog, ctx, "whisper", owned)
        cog._trigger_whisper.assert_not_awaited()
        consume.assert_not_called()
        assert "RoleChat channel" in str(ctx.send.await_args)

    def test_private_pc_item_is_dispatched_from_a_rolechat(self):
        guild, houses, rc, alive, sponsor = setup_guild_with_categories()
        ctx = FakeCtx(rc, [alive], guild)
        cog = object.__new__(economy_cog.Economy)
        cog._trigger_private_pc = AsyncMock(return_value=True)
        owned = {"item_id": 4, "name": "🔒 Private PC", "quantity": 1}

        consume = run_use(cog, ctx, "private pc", owned)
        cog._trigger_private_pc.assert_awaited_once()
        consume.assert_called_once()

    def test_broom_without_alive_or_sponsor_role_is_refused(self):
        guild, houses, rc, alive, sponsor = setup_guild_with_categories()
        ctx = FakeCtx(houses, [], guild)
        cog = object.__new__(economy_cog.Economy)
        cog._trigger_broom = AsyncMock(return_value=True)
        owned = {"item_id": 1, "name": "🧹 Broom", "quantity": 1}
        rc_ch = MagicMock()
        rc_ch.members = [ctx.author]
        rc_ch.permissions_for.return_value = MagicMock(send_messages=True)
        rc.text_channels = [rc_ch]

        consume = run_use(cog, ctx, "broom", owned)
        cog._trigger_broom.assert_not_awaited()
        consume.assert_not_called()

    def test_use_outside_rolechat_and_house_is_refused(self):
        guild = make_guild([], [])
        ctx = FakeCtx(None, [], guild)
        cog = object.__new__(economy_cog.Economy)
        consume = run_use(cog, ctx, "broom", {"item_id": 1, "name": "🧹 Broom", "quantity": 1})
        consume.assert_not_called()
        assert "RoleChat or House" in str(ctx.send.await_args)


class TestFireworksMissingRoles:
    def test_fireworks_do_not_crash_when_alive_role_is_missing(self):
        sponsor = role("Sponsor")
        guild = make_guild([], [sponsor])
        ann = MagicMock()
        ann.send = AsyncMock()
        guild.channels = [ann]
        ann.name = "announcements"
        user = MagicMock()
        user.roles = [sponsor]
        user.mention = "@sponsor"
        ctx = MagicMock()
        ctx.guild = guild
        ctx.author = user
        ctx.send = AsyncMock()
        house = MagicMock()
        house.name = "house-1"

        cog = object.__new__(economy_cog.Economy)
        cog._resolve_fireworks_house = MagicMock(return_value=(house, ""))
        with patch.object(economy_cog, "load_guild_data", return_value=GUILD_DATA), \
                patch.object(economy_cog.discord.utils, "get", side_effect=lambda seq, **kw: (
                    ann if kw.get("name") == "announcements" else
                    sponsor if kw.get("name") == "Sponsor" else None)):
            ok = asyncio.run(cog._trigger_fireworks(ctx))

        assert ok is True
        first_post = ann.send.await_args_list[0].args[0]
        assert "@sponsor" in first_post


class TestItemResolutionRules:
    def test_equal_scores_ask_the_user_instead_of_picking_the_first(self):
        cog = object.__new__(economy_cog.Economy)
        cog._ask_item_choice = AsyncMock(return_value={"id": 2, "name": "🪓 Log", "score": 1.0})
        candidates = [
            {"id": 1, "name": "🪵 Log", "score": 1.0},
            {"id": 2, "name": "🪓 Log", "score": 1.0},
        ]
        pick = asyncio.run(cog._resolve_item(MagicMock(), candidates, "not found"))
        cog._ask_item_choice.assert_awaited_once()
        assert pick["id"] == 2

    def test_exact_name_beats_a_near_match(self):
        cog = object.__new__(economy_cog.Economy)
        cog._ask_item_choice = AsyncMock()
        candidates = [
            {"id": 1, "name": "Broom", "score": 1.0},
            {"id": 2, "name": "Brooms", "score": 0.95},
        ]
        pick = asyncio.run(cog._resolve_item(MagicMock(), candidates, "not found"))
        cog._ask_item_choice.assert_not_awaited()
        assert pick["id"] == 1

    def test_clear_winner_is_used_directly(self):
        cog = object.__new__(economy_cog.Economy)
        cog._ask_item_choice = AsyncMock()
        candidates = [
            {"id": 1, "name": "🪵 Log", "score": 1.0},
            {"id": 2, "name": "🪵 Big Log", "score": 0.5},
        ]
        pick = asyncio.run(cog._resolve_item(MagicMock(), candidates, "not found"))
        cog._ask_item_choice.assert_not_awaited()
        assert pick["id"] == 1

    def test_exact_id_lookup_ignores_similar_names(self):
        from utils import economy_db
        items = [
            {"id": 7, "name": "🪵 Log", "price": 500, "description": "", "is_default": False, "stock": 0},
            {"id": 8, "name": "🪵 Big Log", "price": 100, "description": "", "is_default": False, "stock": 0},
        ]
        with patch.object(economy_db, "get_shop_items", return_value=items), \
                patch.object(economy_db, "_ensure_ready", lambda: None):
            assert economy_db.get_shop_item_by_id(1, 7)["name"] == "🪵 Log"
            assert economy_db.get_shop_item_by_id(1, 8)["name"] == "🪵 Big Log"
            assert economy_db.get_shop_item_by_id(1, 99) is None
