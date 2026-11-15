"""Command-level tests for the PC overflow behaviour: .newpc with a full category, .close when no
OLD PCS category has room, and channel stats counting overflow categories."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import channel_cog, handling_cog
from utils import discord_safe as ds


def category(name, channels=0):
    cat = MagicMock()
    cat.name = name
    cat.channels = [MagicMock() for _ in range(channels)]
    cat.text_channels = []
    cat.create_text_channel = AsyncMock()
    return cat


def admin_ctx(guild):
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author.guild_permissions.administrator = True
    ctx.send = AsyncMock()
    return ctx


GUILD_DATA = {
    "privc_category_name": "PRIVATE CHANNELS",
    "publc_category_name": "PUBLIC CHANNELS",
    "old_pcs_category_name": "OLD PCS",
    "alive_role_name": "Alive",
    "sponsor_role_name": "Sponsor",
    "alt_role_name": "Alt",
    "dead_role_name": "Dead",
    "spectator_role_name": "Spectator",
    "log_channel_name": "logs",
    "rc_category_name": "ROLES",
}


class TestNewpcFullCategory:
    def test_full_private_category_is_refused_without_creating_a_channel(self):
        full = category("PRIVATE CHANNELS", channels=50)
        guild = MagicMock()
        guild.categories = [full]
        guild.roles = []
        ctx = admin_ctx(guild)
        cog = object.__new__(handling_cog.Handling)

        async def fake_get_pc(guild_, guild_data, kind):
            return full

        with patch.object(handling_cog, "load_guild_data", return_value=GUILD_DATA), \
                patch.object(handling_cog, "get_pc_category", fake_get_pc):
            asyncio.run(handling_cog.Handling.newpc.callback(cog, ctx, "private", "secret"))

        full.create_text_channel.assert_not_awaited()
        sent = ctx.send.await_args.args[0]
        assert "is full" in sent

    def test_room_available_creates_the_channel(self):
        room = category("PRIVATE CHANNELS", channels=3)
        created = MagicMock()
        created.mention = "#secret"
        created.set_permissions = AsyncMock()
        created.send = AsyncMock()
        room.create_text_channel = AsyncMock(return_value=created)
        guild = MagicMock()
        guild.categories = [room]
        guild.roles = []
        ctx = admin_ctx(guild)
        cog = object.__new__(handling_cog.Handling)

        async def fake_get_pc(guild_, guild_data, kind):
            return room

        with patch.object(handling_cog, "load_guild_data", return_value=GUILD_DATA), \
                patch.object(handling_cog, "get_pc_category", fake_get_pc):
            asyncio.run(handling_cog.Handling.newpc.callback(cog, ctx, "private", "secret"))

        room.create_text_channel.assert_awaited_once_with(name="secret")


class TestCloseWithoutOldPcsRoom:
    def test_no_old_pcs_room_says_so_instead_of_silently_saying_done(self):
        guild = MagicMock()
        guild.roles = []
        guild.default_role = MagicMock()
        chat = MagicMock()
        chat.members = []
        chat.send = AsyncMock()
        chat.set_permissions = AsyncMock()
        chat.mention = "#closing"
        ctx = admin_ctx(guild)
        ctx.channel = chat
        cog = object.__new__(handling_cog.Handling)
        cog.bot = MagicMock()
        cog.bot.get_cog.return_value = None

        async def no_room(guild_, guild_data):
            return None

        with patch.object(handling_cog, "load_guild_data", return_value=GUILD_DATA), \
                patch.object(handling_cog, "save_guild_data"), \
                patch.object(handling_cog, "get_old_pcs_category", no_room):
            asyncio.run(handling_cog.Handling.close.callback(cog, ctx, None))

        messages = [c.args[0] for c in ctx.send.await_args_list if c.args]
        assert any("No OLD PCS category has room" in m for m in messages)


class TestChannelStatsCountOverflow:
    def test_overflow_categories_contribute_their_channels(self):
        main = category("PRIVATE CHANNELS")
        overflow = category("PRIVATE CHANNELS 2")
        a = MagicMock()
        a.name = "room-a"
        b = MagicMock()
        b.name = "room-b"
        main.text_channels = [a]
        overflow.text_channels = [b]
        unrelated = category("PRIVATE CHANNELS (archive)")
        unrelated.text_channels = [MagicMock(name="ignored")]
        guild = MagicMock()
        guild.categories = [main, overflow, unrelated]
        guild.members = []
        guild.default_role = MagicMock()
        for ch in (a, b):
            ch.permissions_for.return_value = MagicMock(send_messages=False)
            ch.overwrites_for.return_value = MagicMock(send_messages=None)

        cog = object.__new__(channel_cog.ChannelMap)
        rows = asyncio.run(cog._gather_channels(guild, "PRIVATE CHANNELS"))
        names = [row["name"] for row in rows]
        assert names == ["room-a", "room-b"]
