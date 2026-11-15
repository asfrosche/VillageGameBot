"""Tests for the trade accept rules, the exact-id sell price, the .role 30-second timer,
the .guilds split, and long-field chunking in .who."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import economy_cog, help_misc_cog, privatecommands_cog, role_package_cog


# ── trade: accept / decline ───────────────────────────────────────────────

def trade_view(item_id=7):
    """Build a GiveItemConfirmView with a sender, recipient and the item."""
    async def build():
        ctx = MagicMock()
        ctx.guild.id = 1
        ctx.author = MagicMock(id=10)
        recipient = MagicMock(id=20, mention="@recipient")
        sender_rc = MagicMock(id=100, name="sender-rc")
        target_rc = MagicMock(id=200, name="target-rc")
        item = {"id": item_id, "name": "🚪 Shoes", "price": 250}
        view = economy_cog.Economy.GiveItemConfirmView(ctx, recipient, item, 2, sender_rc, target_rc)
        return view, recipient, ctx
    return asyncio.run(build())


def interaction_for(user):
    interaction = MagicMock()
    interaction.user = user
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def accept(view, interaction):
    return asyncio.run(economy_cog.Economy.GiveItemConfirmView.accept_btn(view, interaction, MagicMock()))


class TestTradeAccept:
    def test_recipient_accepts_with_enough_items_moves_exactly_the_quantity(self):
        view, recipient, ctx = trade_view()
        inv = [{"item_id": 7, "quantity": 5}]
        with patch.object(economy_cog, "get_inventory_channel", return_value=inv), \
                patch.object(economy_cog, "add_inventory_item_channel", side_effect=[-2, 2]) as adjust, \
                patch.object(economy_cog, "_log_economy", AsyncMock()), \
                patch.object(economy_cog, "load_guild_data", return_value={}):
            accept(view, interaction_for(recipient))

        calls = [c.args for c in adjust.call_args_list]
        # sender debited first, then recipient credited
        assert calls[0][1] == 100 and calls[0][3] == -2
        assert calls[1][1] == 200 and calls[1][3] == 2
        assert view.is_finished()

    def test_sender_short_on_items_cancels_without_creating_any(self):
        view, recipient, ctx = trade_view()
        inv = [{"item_id": 7, "quantity": 1}]  # 1 left, 2 promised
        with patch.object(economy_cog, "get_inventory_channel", return_value=inv), \
                patch.object(economy_cog, "add_inventory_item_channel") as adjust, \
                patch.object(economy_cog, "load_guild_data", return_value={}):
            interaction = interaction_for(recipient)
            accept(view, interaction)

        adjust.assert_not_called()
        assert "no longer has enough" in interaction.response.edit_message.await_args.kwargs["content"]
        assert view.is_finished()

    def test_recipient_side_failure_gives_the_items_back_to_the_sender(self):
        view, recipient, ctx = trade_view()
        inv = [{"item_id": 7, "quantity": 5}]
        # debit sender -> -2 ok; credit recipient returns 0 (item gone); refund sender -> +2
        with patch.object(economy_cog, "get_inventory_channel", return_value=inv), \
                patch.object(economy_cog, "add_inventory_item_channel", side_effect=[-2, 0, 2]) as adjust, \
                patch.object(economy_cog, "load_guild_data", return_value={}):
            interaction = interaction_for(recipient)
            accept(view, interaction)

        calls = [(c.args[1], c.args[3]) for c in adjust.call_args_list]
        assert calls == [(100, -2), (200, 2), (100, 2)]
        assert "no longer available" in interaction.response.edit_message.await_args.kwargs["content"]

    def test_someone_else_clicking_accept_does_not_end_the_trade(self):
        view, recipient, ctx = trade_view()
        bystander = MagicMock(id=999)
        interaction = interaction_for(bystander)
        with patch.object(economy_cog, "add_inventory_item_channel") as adjust:
            accept(view, interaction)
        adjust.assert_not_called()
        assert not view.is_finished()
        interaction.response.send_message.assert_awaited_once()

    def test_decline_by_sender_is_allowed_and_ends_the_trade(self):
        view, recipient, ctx = trade_view()
        sender = MagicMock(id=10)
        interaction = interaction_for(sender)
        asyncio.run(economy_cog.Economy.GiveItemConfirmView.decline_btn(view, interaction, MagicMock()))
        interaction.response.edit_message.assert_awaited_once()
        assert "declined" in interaction.response.edit_message.await_args.kwargs["content"]


# ── sell: the price comes from the exact item ─────────────────────────────

class TestSellUsesExactItem:
    def test_refund_is_half_of_the_item_the_row_points_to(self):
        async def build():
            return economy_cog.InventoryView([], MagicMock(), 5, cog=None)
        view = asyncio.run(build())
        view.selected_item_id = 2
        interaction = MagicMock()
        interaction.guild_id = 1
        interaction.guild = MagicMock()
        interaction.channel.mention = "#rc"
        interaction.user = MagicMock()
        interaction.response.send_message = AsyncMock()
        owned = {"item_id": 2, "name": "🪵 Log", "quantity": 1}
        big = {"id": 2, "name": "🪵 Log", "price": 500}

        with patch.object(economy_cog, "get_inventory_channel", return_value=[owned]), \
                patch.object(economy_cog, "get_shop_item_by_id", return_value=big) as by_id, \
                patch.object(economy_cog, "get_shop_item_by_name", side_effect=AssertionError("name lookup used")), \
                patch.object(economy_cog, "add_inventory_item_channel"), \
                patch.object(economy_cog, "update_economy_channel_balance") as credit, \
                patch.object(economy_cog, "_log_economy", AsyncMock()), \
                patch.object(economy_cog, "load_guild_data", return_value={}):
            asyncio.run(view._do_sell(interaction))

        by_id.assert_called_once_with(1, 2)
        credit.assert_called_once_with(1, 5, 250)


# ── .role: output is removed after 60 seconds ─────────────────────────────

class TestRoleReplyTimer:
    def test_timer_constant_is_sixty_seconds(self):
        assert role_package_cog.ROLE_REPLY_DELETE_AFTER == 60

    def test_no_pins_reply_is_sent_with_the_timer(self):
        channel = MagicMock()
        channel.pins = AsyncMock(return_value=[])
        ctx = MagicMock()
        ctx.guild.id = 1
        ctx.guild.roles = []
        ctx.author.guild_permissions.administrator = False
        ctx.send = AsyncMock()
        cog = object.__new__(role_package_cog.RolePackageCog)
        with patch.object(role_package_cog, "load_guild_data", return_value={"spectator_role_name": "Spectator"}):
            asyncio.run(cog._legacy_firstpin(ctx, channel))
        assert ctx.send.await_args.kwargs.get("delete_after") == 60

    def test_pinned_reply_is_sent_with_the_timer(self):
        pin = MagicMock()
        pin.content = "the first pin"
        pin.jump_url = "https://discord.test/x"
        channel = MagicMock()
        channel.pins = AsyncMock(return_value=[pin])
        ctx = MagicMock()
        ctx.guild.id = 1
        ctx.guild.roles = []
        ctx.author.guild_permissions.administrator = False
        ctx.send = AsyncMock()
        cog = object.__new__(role_package_cog.RolePackageCog)
        with patch.object(role_package_cog, "load_guild_data", return_value={"spectator_role_name": "Spectator"}):
            asyncio.run(cog._legacy_firstpin(ctx, channel))
        assert ctx.send.await_args.kwargs.get("delete_after") == 60


# ── .guilds: owner list split under the 2000-character limit ──────────────

class TestGuildListSplit:
    def test_long_list_is_sent_in_chunks_under_the_limit_with_every_guild(self):
        guilds = []
        for i in range(300):
            g = MagicMock()
            g.name = f"server-{i:03d}-" + "x" * 20
            g.id = 1000 + i
            guilds.append(g)
        bot = MagicMock()
        bot.guilds = guilds
        cog = object.__new__(privatecommands_cog.Privatecommands)
        cog.bot = bot
        ctx = MagicMock()
        ctx.author.id = 450772749829537793
        ctx.send = AsyncMock()

        asyncio.run(privatecommands_cog.Privatecommands.guilds.callback(cog, ctx))

        sent = [c.args[0] for c in ctx.send.await_args_list]
        assert len(sent) > 1
        assert all(len(chunk) <= 2000 for chunk in sent)
        joined = "".join(sent)
        assert all(g.name in joined for g in guilds)

    def test_non_owner_gets_no_reply(self):
        cog = object.__new__(privatecommands_cog.Privatecommands)
        cog.bot = MagicMock(guilds=[])
        ctx = MagicMock(send=AsyncMock())
        ctx.author.id = 1
        asyncio.run(privatecommands_cog.Privatecommands.guilds.callback(cog, ctx))
        ctx.send.assert_not_awaited()


# ── .who / embed pages: a single very long name must not overflow a field ──

class TestEmbedPageChunking:
    def test_long_single_line_is_split_across_fields(self):
        chunks = help_misc_cog._chunk_lines(["a" * 2500])
        assert len(chunks) == 3
        assert all(len(c) <= 1024 for c in chunks)
        assert "".join(chunks) == "a" * 2500

    def test_many_short_lines_group_without_losing_any(self):
        lines = [f"member {i}" for i in range(400)]
        chunks = help_misc_cog._chunk_lines(lines)
        assert all(len(c) <= 1024 for c in chunks)
        assert "\n".join(chunks).split("\n") == lines

    def test_embed_pages_never_produce_an_oversized_field(self):
        groups = [("Alive:", ["x" * 900, "y" * 900, "z" * 30])]
        pages = help_misc_cog._embed_pages("title", "footer", groups, 0)
        for page in pages:
            for field in page.fields:
                assert len(field.value) <= 1024
