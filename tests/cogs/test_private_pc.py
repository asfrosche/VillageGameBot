"""Tests for the Private PC shop item: channel naming, creation, target list and the menu."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import discord
import pytest

from cogs import economy_cog
from utils import private_pc as ppc


def build_menu(*args):
    """discord.ui.View needs a running event loop, so build the menu inside one."""
    async def inner():
        return economy_cog.private_pc_menu(*args)
    return asyncio.run(inner())


def role(name):
    r = MagicMock()
    r.name = name
    return r


def member(name, roles=(), bot=False, member_id=1, display=None):
    m = MagicMock(spec=discord.Member)
    m.name = name
    m.display_name = display or name
    m.mention = f"@{name}"
    m.id = member_id
    m.bot = bot
    m.roles = list(roles)
    return m


# ── naming ─────────────────────────────────────────────────────────────────

class TestPrivatePcName:
    def test_example_from_request(self):
        # coconut opens a PC with falcon -> tunococ-noclaf
        assert ppc.private_pc_name("coconut", "falcon") == "tunococ-noclaf"

    def test_initiator_comes_first(self):
        assert ppc.private_pc_name("falcon", "coconut") == "noclaf-tunococ"

    def test_strips_characters_discord_rejects(self):
        # "Cool.Name!" -> "coolname" -> "emanloc"; "Ok Person" -> "okperson" -> "nosrepko"
        assert ppc.private_pc_name("Cool.Name!", "Ok Person") == "emanlooc-nosrepko"

    def test_keeps_underscores_and_dashes(self):
        assert ppc.private_pc_name("a_b-c", "x") == "c-b_a-x"

    def test_empty_username_falls_back_to_player(self):
        assert ppc.private_pc_name("", "falcon") == "player-noclaf"


class TestUniqueChannelName:
    def test_returns_base_when_free(self):
        assert ppc.unique_channel_name(["general"], "tunococ-noclaf") == "tunococ-noclaf"

    def test_adds_suffix_when_taken(self):
        assert ppc.unique_channel_name(["tunococ-noclaf"], "tunococ-noclaf") == "tunococ-noclaf-2"

    def test_skips_taken_suffixes_and_ignores_case(self):
        taken = ["Tunococ-Noclaf", "tunococ-noclaf-2"]
        assert ppc.unique_channel_name(taken, "tunococ-noclaf") == "tunococ-noclaf-3"


# ── creation ───────────────────────────────────────────────────────────────

class TestCreatePrivatePc:
    def _guild(self, members, sponsor_role):
        guild = MagicMock()
        guild.members = members
        guild.default_role = MagicMock()
        guild.text_channels = []
        return guild

    def _category(self):
        channel = MagicMock()
        channel.set_permissions = AsyncMock()
        channel.send = AsyncMock()
        category = MagicMock()
        category.create_text_channel = AsyncMock(return_value=channel)
        return category, channel

    def test_adds_both_players_and_every_sponsor(self):
        sponsor_role = MagicMock()
        initiator = member("coconut", member_id=1)
        target = member("falcon", member_id=2)
        sponsor_a = member("sp1", roles=[sponsor_role], member_id=3)
        sponsor_b = member("sp2", roles=[sponsor_role], member_id=4)
        bot_sponsor = member("bot", roles=[sponsor_role], bot=True, member_id=5)
        guild = self._guild([initiator, target, sponsor_a, sponsor_b, bot_sponsor], sponsor_role)
        category, channel = self._category()

        result = asyncio.run(ppc.create_private_pc(guild, category, initiator, target, sponsor_role))

        assert result is channel
        category.create_text_channel.assert_awaited_once_with(name="tunococ-noclaf")
        granted = {call.args[0] for call in channel.set_permissions.await_args_list if call.args}
        assert {initiator, target, sponsor_a, sponsor_b} <= granted
        assert bot_sponsor not in granted

    def test_default_role_cannot_read(self):
        guild = self._guild([], None)
        category, channel = self._category()
        initiator, target = member("coconut", member_id=1), member("falcon", member_id=2)
        asyncio.run(ppc.create_private_pc(guild, category, initiator, target, None))
        first_call = channel.set_permissions.await_args_list[0]
        assert first_call.args[0] is guild.default_role
        assert first_call.kwargs == {"read_messages": False}

    def test_no_sponsor_role_still_creates_with_two_players(self):
        guild = self._guild([], None)
        category, channel = self._category()
        initiator, target = member("coconut", member_id=1), member("falcon", member_id=2)
        asyncio.run(ppc.create_private_pc(guild, category, initiator, target, None))
        granted = {call.args[0] for call in channel.set_permissions.await_args_list if call.args}
        assert initiator in granted and target in granted

    def test_name_collision_gets_suffix(self):
        guild = self._guild([], None)
        existing = MagicMock()
        existing.name = "tunococ-noclaf"
        guild.text_channels = [existing]
        category, channel = self._category()
        initiator, target = member("coconut", member_id=1), member("falcon", member_id=2)
        asyncio.run(ppc.create_private_pc(guild, category, initiator, target, None))
        category.create_text_channel.assert_awaited_once_with(name="tunococ-noclaf-2")


class TestSponsorMembers:
    def test_skips_bots_and_non_sponsors(self):
        sponsor_role = MagicMock()
        guild = MagicMock()
        guild.members = [
            member("sp", roles=[sponsor_role], member_id=1),
            member("bot", roles=[sponsor_role], bot=True, member_id=2),
            member("player", member_id=3),
        ]
        assert [m.name for m in ppc.sponsor_members(guild, sponsor_role)] == ["sp"]

    def test_no_role_gives_nobody(self):
        assert ppc.sponsor_members(MagicMock(), None) == []


# ── economy cog helpers ────────────────────────────────────────────────────

class TestTargetsAndOpening:
    def _guild(self, members, alive_role):
        guild = MagicMock()
        guild.members = members
        guild.roles = [alive_role]
        return guild

    def test_targets_are_other_alive_players_sorted(self):
        alive = role("Alive")
        author = member("coconut", roles=[alive], member_id=1)
        zed = member("zed", roles=[alive], member_id=2, display="Zed")
        adam = member("adam", roles=[alive], member_id=3, display="adam")
        dead = member("ghost", member_id=4)
        bot = member("bot", roles=[alive], bot=True, member_id=5)
        guild = self._guild([author, zed, adam, dead, bot], alive)
        targets = economy_cog.private_pc_targets(guild, {"alive_role_name": "Alive"}, author)
        assert [m.name for m in targets] == ["adam", "zed"]

    def test_missing_alive_role_reports_error(self):
        guild = MagicMock()
        guild.roles = []
        result = economy_cog.private_pc_targets(guild, {"alive_role_name": "Alive"}, member("x"))
        assert isinstance(result, str) and "Alive" in result

    def test_no_other_players_reports_error(self):
        alive = role("Alive")
        author = member("coconut", roles=[alive], member_id=1)
        guild = self._guild([author], alive)
        result = economy_cog.private_pc_targets(guild, {"alive_role_name": "Alive"}, author)
        assert isinstance(result, str)

    def test_open_refuses_target_who_is_not_alive(self, monkeypatch):
        alive = role("Alive")
        target = member("falcon", member_id=2)  # no alive role
        guild = self._guild([target], alive)
        ok, text = asyncio.run(economy_cog.open_private_pc_with(
            guild, {"alive_role_name": "Alive"}, member("coconut", member_id=1), target))
        assert ok is False and "no longer" in text

    def test_open_reports_missing_category(self, monkeypatch):

        async def no_category(guild, guild_data, kind):
            return None

        monkeypatch.setattr(economy_cog, "get_pc_category", no_category)
        alive = role("Alive")
        target = member("falcon", roles=[alive], member_id=2)
        guild = self._guild([target], alive)
        ok, text = asyncio.run(economy_cog.open_private_pc_with(
            guild, {"alive_role_name": "Alive"}, member("coconut", member_id=1), target))
        assert ok is False and "category" in text.lower()

    def test_open_success_reports_channel(self, monkeypatch):
        alive = role("Alive")
        channel = MagicMock()
        channel.mention = "#tunococ-noclaf"

        async def category_with_room(guild, guild_data, kind):
            return MagicMock()

        async def fake_create(guild, category, initiator, target, sponsor_role):
            return channel

        monkeypatch.setattr(economy_cog, "get_pc_category", category_with_room)
        monkeypatch.setattr(economy_cog, "create_private_pc", fake_create)
        target = member("falcon", roles=[alive], member_id=2)
        guild = self._guild([target], alive)
        ok, text = asyncio.run(economy_cog.open_private_pc_with(
            guild, {"alive_role_name": "Alive"}, member("coconut", member_id=1), target))
        assert ok is True and "#tunococ-noclaf" in text

    def test_creation_failure_is_reported_not_raised(self, monkeypatch):
        alive = role("Alive")

        async def category_with_room(guild, guild_data, kind):
            return MagicMock()

        async def failing_create(*args, **kwargs):
            raise discord.HTTPException(MagicMock(status=400, reason="x"), "full")

        monkeypatch.setattr(economy_cog, "get_pc_category", category_with_room)
        monkeypatch.setattr(economy_cog, "create_private_pc", failing_create)
        target = member("falcon", roles=[alive], member_id=2)
        guild = self._guild([target], alive)
        ok, text = asyncio.run(economy_cog.open_private_pc_with(
            guild, {"alive_role_name": "Alive"}, member("coconut", member_id=1), target))
        assert ok is False and "Could not" in text


class TestPrivatePcMenu:
    def test_pages_of_25_with_a_select_per_page(self):
        invoker = member("coconut", member_id=1)
        targets = [member(f"p{i}", member_id=100 + i) for i in range(30)]
        view = build_menu(invoker, targets, AsyncMock(), {"ok": False}, asyncio.Event())
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert [len(s.options) for s in selects] == [25, 5]
        assert selects[0].placeholder.endswith("(1/2)")

    def test_choosing_a_player_runs_on_pick_and_records_result(self):
        invoker = member("coconut", member_id=1)
        target = member("falcon", member_id=2)
        on_pick = AsyncMock(return_value=(True, "done"))
        result, done = {"ok": False}, asyncio.Event()
        view = build_menu(invoker, [target], on_pick, result, done)
        select = view.children[0]
        callback = select.callback

        interaction = MagicMock()
        interaction.user = invoker
        interaction.response.edit_message = AsyncMock()
        with patch.object(discord.ui.Select, "values", new_callable=PropertyMock, return_value=["2"]):
            asyncio.run(callback(interaction))

        on_pick.assert_awaited_once_with(target)
        assert result["ok"] is True
        assert done.is_set()
        interaction.response.edit_message.assert_awaited_once()

    def test_other_users_cannot_use_the_menu(self):
        invoker = member("coconut", member_id=1)
        intruder = member("other", member_id=9)
        on_pick = AsyncMock()
        result, done = {"ok": False}, asyncio.Event()
        view = build_menu(invoker, [member("falcon", member_id=2)], on_pick, result, done)
        select = view.children[0]
        interaction = MagicMock()
        interaction.user = intruder
        interaction.response.send_message = AsyncMock()
        with patch.object(discord.ui.Select, "values", new_callable=PropertyMock, return_value=["2"]):
            asyncio.run(select.callback(interaction))
        on_pick.assert_not_awaited()
        assert not done.is_set()


class TestShopItem:
    def test_private_pc_is_in_the_default_shop_at_1500(self):
        items = [i for i in economy_cog.DEFAULT_SHOP_ITEMS if "private pc" in i["name"].lower()]
        assert len(items) == 1
        assert items[0]["price"] == 1500
