"""Tests for .owned: in a Role Chat, show the house(s) owned by the players in that channel."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import home_cog

GUILD_DATA = {
    "rc_category_name": "ROLES",
    "alt_category_name": "ALTs",
    "dead_rc_category_name": "DEAD RC",
    "houses_category_name": "HOUSES",
}


def player(mid, bot=False):
    m = MagicMock()
    m.id = mid
    m.bot = bot
    m.display_name = f"p{mid}"
    m.mention = f"@p{mid}"
    return m


def house(hid, name):
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = hid
    ch.name = name
    ch.mention = f"#{name}"
    return ch


def ctx_in(channel_category, members, houses):
    houses_cat = MagicMock()
    houses_cat.name = "HOUSES"
    houses_cat.channels = houses
    rc = MagicMock()
    rc.name = "ROLES"
    guild = MagicMock()
    guild.categories = [rc, houses_cat]
    guild.roles = []
    ctx = MagicMock()
    ctx.guild = guild
    ctx.channel = MagicMock()
    ctx.channel.category = channel_category(rc)
    ctx.channel.members = members
    ctx.send = AsyncMock()
    return ctx


class TestOwned:
    def test_shows_the_house_owned_by_the_player_in_the_role_chat(self):
        h = house(555, "🏡│house-18")
        p = player(10)
        ctx = ctx_in(lambda rc: rc, [p], [h])
        cog = object.__new__(home_cog.Home)
        with patch.object(home_cog, "load_guild_data", return_value=dict(GUILD_DATA, member_homes={"10": 555})):
            asyncio.run(home_cog.Home.owned.callback(cog, ctx))
        embed = ctx.send.await_args.kwargs["embed"]
        assert "#🏡│house-18" in embed.description
        assert "@p10" in embed.description

    def test_players_with_no_houses_are_reported(self):
        ctx = ctx_in(lambda rc: rc, [player(10)], [house(555, "🏡│house-18")])
        cog = object.__new__(home_cog.Home)
        with patch.object(home_cog, "load_guild_data", return_value=dict(GUILD_DATA, member_homes={"11": 555})):
            asyncio.run(home_cog.Home.owned.callback(cog, ctx))
        assert "don't own any houses" in ctx.send.await_args.args[0]

    def test_refused_outside_a_role_chat(self):
        ctx = ctx_in(lambda rc: MagicMock(name="houses"), [player(10)], [house(555, "🏡│house-18")])
        cog = object.__new__(home_cog.Home)
        with patch.object(home_cog, "load_guild_data", return_value=dict(GUILD_DATA, member_homes={"10": 555})):
            asyncio.run(home_cog.Home.owned.callback(cog, ctx))
        assert "Role Chat channel" in ctx.send.await_args.args[0]
