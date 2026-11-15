"""Tests for .give with items: a player gives items to another player in the same house, straight away."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from cogs import economy_cog

ITEM = {"id": 7, "name": "🚪 Shoes", "price": 250}


def cat(name, channels=()):
    c = MagicMock()
    c.name = name
    c.text_channels = list(channels)
    return c


def rc_channel(member_ids, can_send=None):
    ch = MagicMock()
    ch.id = 100 + len(member_ids)
    can = set(member_ids) if can_send is None else set(can_send)
    ch.permissions_for.side_effect = lambda m: MagicMock(
        send_messages=m.id in can, read_messages=m.id in can)
    return ch


def player(mid):
    m = MagicMock()
    m.id = mid
    m.bot = False
    m.mention = f"@p{mid}"
    m.display_name = f"p{mid}"
    return m


def setup(sender_rc_members=(10,), target_rc_members=(20,), house_members=(10, 20), house_in=True):
    author = player(10)
    target = player(20)
    sender_rc = rc_channel(sender_rc_members)
    target_rc = rc_channel(target_rc_members)
    rc = cat("ROLES", [sender_rc, target_rc])
    house = MagicMock()
    house.permissions_for.side_effect = lambda m: MagicMock(
        send_messages=m.id in house_members, read_messages=m.id in house_members)
    ctx = MagicMock()
    ctx.guild.id = 1
    ctx.guild.categories = [rc]
    ctx.author = author
    ctx.channel = house
    ctx.channel.mention = "#house"
    ctx.send = AsyncMock()
    return ctx, target, sender_rc, target_rc


GUILD_DATA = {"rc_category_name": "ROLES", "alt_category_name": "ALTs", "dead_rc_category_name": "DEAD RC"}


def run_gift(ctx, target, text, inventory, *, in_house=True, credit_result=2):
    cog = object.__new__(economy_cog.Economy)
    cog._resolve_shop_item = AsyncMock(return_value=ITEM)
    with patch.object(economy_cog, "load_guild_data", return_value=GUILD_DATA), \
            patch.object(economy_cog, "_is_houses_category", return_value=in_house), \
            patch.object(economy_cog, "get_inventory_channel", return_value=inventory), \
            patch.object(economy_cog, "add_inventory_item_channel", side_effect=[-2, credit_result] if credit_result == 2 else [-2, credit_result, 2]) as adjust, \
            patch.object(economy_cog, "_log_economy", AsyncMock()):
        asyncio.run(economy_cog.Economy.give.callback(cog, ctx, target, amount=text))
    return adjust


class TestGift:
    def test_gift_moves_the_quantity_from_sender_to_recipient(self):
        ctx, target, sender_rc, target_rc = setup()
        adjust = run_gift(ctx, target, "shoes 2", [{"item_id": 7, "quantity": 5}])
        calls = [(c.args[1], c.args[3]) for c in adjust.call_args_list]
        assert calls == [(sender_rc.id, -2), (target_rc.id, 2)]
        assert "gave" in ctx.send.await_args.args[0]

    def test_outside_a_house_is_refused(self):
        ctx, target, *_ = setup()
        adjust = run_gift(ctx, target, "shoes", [{"item_id": 7, "quantity": 5}], in_house=False)
        adjust.assert_not_called()
        assert "house channel" in ctx.send.await_args.args[0]

    def test_giving_to_yourself_is_refused(self):
        ctx, target, *_ = setup()
        adjust = run_gift(ctx, ctx.author, "shoes", [{"item_id": 7, "quantity": 5}])
        adjust.assert_not_called()
        assert "yourself" in ctx.send.await_args.args[0]

    def test_recipient_not_in_the_house_is_refused(self):
        ctx, target, *_ = setup(house_members=(10,))
        adjust = run_gift(ctx, target, "shoes", [{"item_id": 7, "quantity": 5}])
        adjust.assert_not_called()
        assert "isn't in this house" in ctx.send.await_args.args[0]

    def test_not_enough_items_moves_nothing(self):
        ctx, target, *_ = setup()
        adjust = run_gift(ctx, target, "shoes 3", [{"item_id": 7, "quantity": 1}])
        adjust.assert_not_called()
        assert "only have **1" in ctx.send.await_args.args[0]

    def test_same_rolechat_is_refused(self):
        ctx, target, *_ = setup(sender_rc_members=(10, 20), target_rc_members=(10, 20))
        adjust = run_gift(ctx, target, "shoes", [{"item_id": 7, "quantity": 5}])
        adjust.assert_not_called()

    def test_failed_credit_refunds_the_sender(self):
        ctx, target, sender_rc, target_rc = setup()
        adjust = run_gift(ctx, target, "shoes 2", [{"item_id": 7, "quantity": 5}], credit_result=0)
        calls = [(c.args[1], c.args[3]) for c in adjust.call_args_list]
        assert calls == [(sender_rc.id, -2), (target_rc.id, 2), (sender_rc.id, 2)]
        assert "no longer available" in ctx.send.await_args.args[0]


class TestMoveHelper:
    def test_credit_failure_returns_false_and_refunds(self):
        with patch.object(economy_cog, "get_inventory_channel", return_value=[{"item_id": 7, "quantity": 5}]), \
                patch.object(economy_cog, "add_inventory_item_channel", side_effect=[-2, 0, 2]) as adjust:
            ok, message = economy_cog.move_items_between_rcs(1, 100, 200, ITEM, 2)
        assert ok is False
        assert adjust.call_count == 3

    def test_success_returns_true(self):
        with patch.object(economy_cog, "get_inventory_channel", return_value=[{"item_id": 7, "quantity": 5}]), \
                patch.object(economy_cog, "add_inventory_item_channel", side_effect=[-2, 2]):
            ok, _ = economy_cog.move_items_between_rcs(1, 100, 200, ITEM, 2)
        assert ok is True


class TestGiveAll:
    def test_all_gives_every_item_held(self):
        ctx, target, sender_rc, target_rc = setup()
        adjust = run_gift(ctx, target, "shoes all", [{"item_id": 7, "quantity": 5}], credit_result=5)
        calls = [(c.args[1], c.args[3]) for c in adjust.call_args_list]
        assert calls == [(sender_rc.id, -5), (target_rc.id, 5)]

    def test_all_with_none_held_is_refused(self):
        ctx, target, *_ = setup()
        adjust = run_gift(ctx, target, "shoes all", [])
        adjust.assert_not_called()
        assert "don't have any" in ctx.send.await_args.args[0]


class TestGiveCoinsUnchanged:
    def test_a_number_goes_to_the_coin_path_not_the_item_path(self):
        cog = object.__new__(economy_cog.Economy)
        ctx = MagicMock()
        ctx.guild.id = 1
        ctx.send = AsyncMock()
        target = player(20)
        with patch.object(economy_cog, "load_guild_data", return_value=GUILD_DATA),                 patch.object(economy_cog, "_is_houses_category", return_value=False),                 patch.object(cog, "_give_items", AsyncMock()) as items:
            asyncio.run(economy_cog.Economy.give.callback(cog, ctx, target, amount="50"))
        items.assert_not_awaited()
        assert "Houses category" in ctx.send.await_args.args[0]

    def test_all_alone_is_still_coins(self):
        cog = object.__new__(economy_cog.Economy)
        ctx = MagicMock()
        ctx.guild.id = 1
        ctx.send = AsyncMock()
        target = player(20)
        with patch.object(economy_cog, "load_guild_data", return_value=GUILD_DATA),                 patch.object(economy_cog, "_is_houses_category", return_value=False),                 patch.object(cog, "_give_items", AsyncMock()) as items:
            asyncio.run(economy_cog.Economy.give.callback(cog, ctx, target, amount="all"))
        items.assert_not_awaited()
