"""Tests for the server-wide selling toggle: the shop button, the .sellshop command, and both sell paths."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from cogs import economy_cog


def admin_user(admin=True):
    user = MagicMock()
    user.guild_permissions.administrator = admin
    return user


class TestSettingHelpers:
    def test_selling_is_on_when_the_setting_is_missing(self):
        with patch.object(economy_cog, "load_guild_data", return_value={}):
            assert economy_cog.selling_enabled(1) is True

    def test_selling_reads_the_stored_off_value(self):
        with patch.object(economy_cog, "load_guild_data", return_value={"shop_selling_enabled": False}):
            assert economy_cog.selling_enabled(1) is False

    def test_set_selling_saves_the_flag(self):
        saved = {}
        with patch.object(economy_cog, "load_guild_data", return_value={"other": 1}), \
                patch.object(economy_cog, "save_guild_data", side_effect=lambda gid, data: saved.update(data)):
            economy_cog.set_selling_enabled(1, False)
        assert saved["shop_selling_enabled"] is False
        assert saved["other"] == 1  # other settings are kept


class TestSellCommandRefused:
    def test_sell_command_is_refused_while_off(self):
        cog = object.__new__(economy_cog.Economy)
        ctx = MagicMock()
        ctx.guild.id = 1
        ctx.send = AsyncMock()
        with patch.object(economy_cog, "selling_enabled", return_value=False), \
                patch.object(economy_cog, "get_shop_item_by_id") as lookup:
            asyncio.run(economy_cog.Economy.sell_item.callback(cog, ctx, item_name="broom"))
        lookup.assert_not_called()
        assert ctx.send.await_args.args[0] == economy_cog.SELL_DISABLED_MESSAGE


class TestInventorySellRefused:
    def test_inventory_sell_button_is_refused_while_off_and_takes_nothing(self):
        async def build():
            return economy_cog.InventoryView([], MagicMock(), 5, cog=None)
        view = asyncio.run(build())
        view.selected_item_id = 2
        interaction = MagicMock()
        interaction.guild_id = 1
        interaction.response.send_message = AsyncMock()
        with patch.object(economy_cog, "selling_enabled", return_value=False), \
                patch.object(economy_cog, "add_inventory_item_channel") as take, \
                patch.object(economy_cog, "update_economy_channel_balance") as pay:
            asyncio.run(view._do_sell(interaction))
        take.assert_not_called()
        pay.assert_not_called()
        assert interaction.response.send_message.await_args.args[0] == economy_cog.SELL_DISABLED_MESSAGE


class TestShopToggleButton:
    def _shop(self):
        async def build():
            return economy_cog.ShopView(["page"], [[]], admin_user(True), 1, 5)
        return asyncio.run(build())

    def _interaction(self, user):
        inter = MagicMock()
        inter.user = user
        inter.guild = MagicMock()
        inter.channel.mention = "#shop"
        inter.response.send_message = AsyncMock()
        inter.response.edit_message = AsyncMock()
        return inter

    def test_admin_click_turns_selling_off_and_says_so(self):
        view = self._shop()
        saved = {}
        inter = self._interaction(view.invoker)
        with patch.object(economy_cog, "load_guild_data", return_value={"shop_selling_enabled": True}), \
                patch.object(economy_cog, "save_guild_data", side_effect=lambda gid, d: saved.update(d)), \
                patch.object(economy_cog, "_log_economy", AsyncMock()):
            asyncio.run(economy_cog.ShopView.btn_toggle_sell(view, inter, MagicMock()))
        assert saved["shop_selling_enabled"] is False
        inter.response.edit_message.assert_awaited_once()

    def test_admin_click_turns_selling_back_on(self):
        view = self._shop()
        saved = {}
        inter = self._interaction(view.invoker)
        with patch.object(economy_cog, "load_guild_data", return_value={"shop_selling_enabled": False}), \
                patch.object(economy_cog, "save_guild_data", side_effect=lambda gid, d: saved.update(d)), \
                patch.object(economy_cog, "_log_economy", AsyncMock()):
            asyncio.run(economy_cog.ShopView.btn_toggle_sell(view, inter, MagicMock()))
        assert saved["shop_selling_enabled"] is True

    def test_non_admin_click_changes_nothing(self):
        view = self._shop()
        player = admin_user(False)
        view.invoker = player
        inter = self._interaction(player)
        with patch.object(economy_cog, "save_guild_data") as save:
            asyncio.run(economy_cog.ShopView.btn_toggle_sell(view, inter, MagicMock()))
        save.assert_not_called()
        assert "Admin only" in inter.response.send_message.await_args.args[0]

    def test_button_label_shows_the_current_state(self):
        view = self._shop()
        with patch.object(economy_cog, "load_guild_data", return_value={"shop_selling_enabled": False}):
            view._rebuild()
        assert view.btn_toggle_sell.label == "Selling: OFF"


class TestSellshopCommand:
    def _ctx(self, admin):
        ctx = MagicMock()
        ctx.guild.id = 1
        ctx.author = admin_user(admin)
        ctx.send = AsyncMock()
        return ctx

    def test_admin_can_turn_selling_off(self):
        saved = {}
        ctx = self._ctx(True)
        cog = object.__new__(economy_cog.Economy)
        with patch.object(economy_cog, "load_guild_data", return_value={}), \
                patch.object(economy_cog, "save_guild_data", side_effect=lambda gid, d: saved.update(d)):
            asyncio.run(economy_cog.Economy.sellshop.callback(cog, ctx, state="off"))
        assert saved["shop_selling_enabled"] is False

    def test_non_admin_cannot_change_it(self):
        cog = object.__new__(economy_cog.Economy)
        ctx = self._ctx(False)
        with patch.object(economy_cog, "save_guild_data") as save:
            asyncio.run(economy_cog.Economy.sellshop.callback(cog, ctx, state="off"))
        save.assert_not_called()

    def test_no_argument_reports_the_state(self):
        cog = object.__new__(economy_cog.Economy)
        ctx = self._ctx(True)
        with patch.object(economy_cog, "load_guild_data", return_value={"shop_selling_enabled": False}):
            asyncio.run(economy_cog.Economy.sellshop.callback(cog, ctx, state=None))
        assert "off" in ctx.send.await_args.args[0]

    def test_bad_argument_is_rejected(self):
        cog = object.__new__(economy_cog.Economy)
        ctx = self._ctx(True)
        with patch.object(economy_cog, "save_guild_data") as save:
            asyncio.run(economy_cog.Economy.sellshop.callback(cog, ctx, state="maybe"))
        save.assert_not_called()
