"""Tests for .housewho: the house is where the player can send messages right now, and its residents are
the members who can send messages there."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import help_misc_cog

GUILD_DATA = {
    "rc_category_name": "ROLES",
    "alt_category_name": "ALTs",
    "dead_rc_category_name": "DEAD RC",
    "houses_category_name": "HOUSES",
    "alive_role_name": "Alive",
    "sponsor_role_name": "Sponsor",
    "alt_role_name": "Alt",
    "dead_role_name": "Dead",
}


def player(mid, bot=False):
    m = MagicMock()
    m.id = mid
    m.bot = bot
    m.display_name = f"p{mid}"
    return m


def house(hid, name, can_send=()):
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = hid
    ch.name = name
    ch.permissions_for.side_effect = lambda m: MagicMock(
        send_messages=m.id in can_send, view_channel=True, read_messages=True)
    return ch


class TestHouseLookup:
    def test_the_house_you_can_send_in_is_yours(self):
        h1 = house(555, "🏡│house-18", can_send={10})
        h2 = house(556, "🏡│tower", can_send={11})
        houses = MagicMock()
        houses.channels = [h1, h2]
        assert help_misc_cog.Other._housewho_house_of(houses, player(10)) is h1

    def test_seeing_a_house_is_not_enough(self):
        visible_only = house(555, "🏡│house-18", can_send=())
        houses = MagicMock()
        houses.channels = [visible_only]
        assert help_misc_cog.Other._housewho_house_of(houses, player(10)) is None

    def test_no_send_permission_anywhere_means_no_house(self):
        houses = MagicMock()
        houses.channels = [house(555, "🏡│house-18", can_send={99})]
        assert help_misc_cog.Other._housewho_house_of(houses, player(10)) is None


class TestResidents:
    def test_residents_are_the_members_who_can_send_in_the_house(self):
        h = house(555, "🏡│house-18", can_send={10, 11})
        members = [player(10), player(11), player(12), player(13, bot=True)]
        ctx = MagicMock()
        ctx.guild.members = members
        ids = [m.id for m in help_misc_cog.Other._housewho_residents(ctx, h)]
        assert ids == [10, 11]


class TestHouseWhoCommand:
    def _ctx(self, rc_members, houses_channels):
        rc = MagicMock()
        rc.name = "ROLES"
        houses = MagicMock()
        houses.name = "HOUSES"
        houses.channels = houses_channels
        guild = MagicMock()
        guild.categories = [rc, houses]
        guild.roles = []
        ctx = MagicMock()
        ctx.guild = guild
        ctx.channel = MagicMock()
        ctx.channel.category = rc
        ctx.channel.members = rc_members
        ctx.author = rc_members[0]
        ctx.send = AsyncMock()
        return ctx

    def test_in_a_rolechat_shows_the_house_the_player_can_send_in(self):
        p10 = player(10)
        h = house(555, "🏡│house-18", can_send={10})
        ctx = self._ctx([p10], [h])
        cog = object.__new__(help_misc_cog.Other)
        show = AsyncMock()
        cog._housewho_show_house = show
        with patch.object(help_misc_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(help_misc_cog.Other.housewho.callback(cog, ctx, target=None))
        show.assert_awaited_once()
        assert show.await_args.args[1] is h

    def test_player_who_can_send_in_no_house_is_told_so(self):
        ctx = self._ctx([player(10)], [house(555, "🏡│house-18", can_send=())])
        cog = object.__new__(help_misc_cog.Other)
        cog._housewho_show_house = AsyncMock()
        with patch.object(help_misc_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(help_misc_cog.Other.housewho.callback(cog, ctx, target=None))
        cog._housewho_show_house.assert_not_awaited()
        assert "any house" in ctx.send.await_args.args[0]
