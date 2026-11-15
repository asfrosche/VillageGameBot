"""Tests for .whorc: like .who, one embed per RoleChat the player can send in, listing the people there."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import home_cog

GUILD_DATA = {"rc_category_name": "ROLES", "overseer_role_name": "Overseer"}


def member(mid, bot=False, admin=False):
    m = MagicMock()
    m.id = mid
    m.bot = bot
    m.display_name = f"p{mid}"
    m.roles = []
    m.guild_permissions.administrator = admin
    return m


def rc(name, cid, members, can_send):
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = cid
    ch.name = name
    ch.mention = f"#{name}"
    ch.members = members
    ch.permissions_for.side_effect = lambda m: MagicMock(send_messages=m.id in can_send)
    return ch


def make_ctx(author, channels, admin=False):
    rc_cat = MagicMock()
    rc_cat.name = "ROLES"
    rc_cat.text_channels = channels
    guild = MagicMock()
    guild.categories = [rc_cat]
    guild.roles = []
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = author
    ctx.author.guild_permissions.administrator = admin
    ctx.send = AsyncMock()
    return ctx


def run(ctx, member_arg=None):
    cog = object.__new__(home_cog.Home)
    with patch.object(home_cog, "load_guild_data", return_value=GUILD_DATA):
        asyncio.run(home_cog.Home.whorc.callback(cog, ctx, member=member_arg))


class TestWhorc:
    def test_one_embed_per_rolechat_the_player_can_send_in(self):
        p10, p11, p12 = member(10), member(11), member(12)
        a = rc("rc-a", 1, [p10, p11], can_send={10, 11})
        b = rc("rc-b", 2, [p12], can_send={12})
        ctx = make_ctx(p10, [a, b])
        run(ctx)
        embeds = [c.kwargs["embed"] for c in ctx.send.await_args_list]
        assert [e.title for e in embeds] == ["rc-a"]
        assert "`[p10]`" in embeds[0].description and "`[p11]`" in embeds[0].description

    def test_admins_and_bots_are_not_listed(self):
        p10 = member(10)
        staff = member(20, admin=True)
        bot = member(21, bot=True)
        a = rc("rc-a", 1, [p10, staff, bot], can_send={10, 20, 21})
        ctx = make_ctx(p10, [a])
        run(ctx)
        desc = ctx.send.await_args.kwargs["embed"].description
        assert "p10" in desc and "p20" not in desc and "p21" not in desc

    def test_long_lists_are_split_so_no_embed_is_too_big(self):
        p10 = member(10)
        crowd = [member(100 + i) for i in range(1000)]
        a = rc("rc-a", 1, [p10] + crowd, can_send={10} | {m.id for m in crowd})
        ctx = make_ctx(p10, [a])
        run(ctx)
        embeds = [c.kwargs["embed"] for c in ctx.send.await_args_list]
        assert len(embeds) > 1
        assert all(len(e.description) <= 4096 for e in embeds)

    def test_player_with_no_rolechat_is_told_so(self):
        p10 = member(10)
        ctx = make_ctx(p10, [rc("rc-a", 1, [p10], can_send=set())])
        run(ctx)
        assert "any RoleChat" in ctx.send.await_args.args[0]

    def test_a_player_cannot_check_someone_else(self):
        p10, p11 = member(10), member(11)
        ctx = make_ctx(p10, [rc("rc-a", 1, [p11], can_send={11})])
        run(ctx, member_arg=p11)
        assert "Only staff" in ctx.send.await_args.args[0]

    def test_admin_can_check_another_player(self):
        p10, p11 = member(10), member(11)
        ctx = make_ctx(p10, [rc("rc-a", 1, [p11], can_send={11})], admin=True)
        run(ctx, member_arg=p11)
        assert ctx.send.await_args.kwargs["embed"].title == "rc-a"
