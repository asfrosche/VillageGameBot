"""Tests for the Blind Auction cog (escrow model)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs import auction_cog
from cogs.auction_cog import Auction, AuctionCog


class _Role:
    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, _Role) and other.name == self.name

    def __hash__(self):
        return hash(self.name)


class _Member:
    def __init__(self, uid: int, name: str, roles: list, guild):
        self.id = uid
        self.display_name = name
        self.roles = roles
        self.guild = guild

    @property
    def guild_permissions(self):
        perms = MagicMock()
        perms.administrator = False
        return perms


class _Channel:
    def __init__(self, cid: int, name: str = "ch"):
        self.id = cid
        self.name = name
        self.mention = f"#{name}"
        self.send = AsyncMock()


class _Guild:
    def __init__(self, gid: int, *, with_alive_role: bool = True):
        self.id = gid
        self.roles = [_Role("Alive")] if with_alive_role else []
        self.members: dict[int, _Member] = {}
        self.channels: dict[int, _Channel] = {}

    def get_member(self, uid):
        return self.members.get(uid)

    def get_channel(self, cid):
        return self.channels.get(cid)


def _make_auction(guild_id: int = 1, mode: str = "sealed", *, min_bid: int = 50, **kw) -> Auction:
    auction = Auction(guild_id)
    auction.item = kw.get("item", "Mystery Box")
    auction.item_type = kw.get("item_type", "named")
    auction.shop_item_id = kw.get("shop_item_id")
    auction.mode = mode
    auction.min_bid = min_bid
    auction.ends_at = datetime.now(timezone.utc) + timedelta(hours=1)
    auction.board_channel_id = 10
    auction.board_message_id = 100
    if kw.get("bids"):
        auction.bids = kw["bids"]
    if kw.get("reserved"):
        auction.reserved = kw["reserved"]
    auction.aliases = {b["player_id"]: b["alias"] for b in auction.bids}
    return auction


async def _run_place_bid(cog, auction, member, amount):
    with patch.object(cog, "_refresh_board", new=AsyncMock()), \
         patch("cogs.auction_cog.save_live_auction"):
        return await cog._place_bid(member, auction, amount)


class TestAuctionCommands:
    """Validate all commands exist and have required metadata."""

    def _cog(self) -> AuctionCog:
        return AuctionCog(MagicMock())

    def _assert_exists(self, name: str):
        assert hasattr(AuctionCog, name)

    def _assert_help(self, name: str):
        method = getattr(AuctionCog, name)
        doc = getattr(method, "help", None) or getattr(method, "__doc__", None)
        assert doc is not None and len(doc.strip()) > 0



    def test_auc_subcommands(self):
        cmd = getattr(AuctionCog, "auc")
        subs = {c.name for c in cmd.commands}
        assert {"status", "start", "bid", "extend", "close", "cancel", "alias"} <= subs








    def test_aucset_subcommands(self):
        cmd = getattr(AuctionCog, "aucset")
        subs = {c.name for c in cmd.commands}
        assert {"show", "channel", "minbid", "increment", "duration"} <= subs
        assert "pot" not in subs

    def test_auction_to_and_from_payload(self):
        auction = _make_auction(bids=[{"player_id": 5, "channel_id": 7, "amount": 100, "ts": 1.0, "alias": "Anon #1"}])
        auction.reserved = {5: 100}
        restored = Auction.from_payload(auction.guild_id, auction.to_payload())
        assert restored.item == auction.item
        assert restored.mode == "sealed"
        assert restored.min_bid == 50
        assert len(restored.bids) == 1
        assert restored.bids[0]["amount"] == 100
        assert restored.aliases == {5: "Anon #1"}
        assert restored.reserved == {5: 100}
        assert restored.ends_at.tzinfo is not None


class TestBoardRendering:
    def _cog(self) -> AuctionCog:
        return AuctionCog(MagicMock())

    def test_sealed_board_hides_amounts(self):
        cfg = self._cog()
        auction = _make_auction(
            mode="sealed",
            bids=[
                {"player_id": 1, "channel_id": 7, "amount": 100, "ts": 1.0, "alias": "Anon #1"},
                {"player_id": 2, "channel_id": 8, "amount": 150, "ts": 2.0, "alias": "Anon #2"},
            ],
        )
        auction.aliases = {1: "Anon #1", 2: "Anon #2"}
        guild = _Guild(1)
        embed = cfg.build_board_embed(auction, guild, 0)
        text = embed.description + "\n" + "\n".join(f.value for f in embed.fields)
        assert "placed a bid" in text
        assert "100" not in text and "150" not in text
        assert "hidden until reveal" in text

    def test_visible_board_shows_amounts(self):
        cfg = self._cog()
        auction = _make_auction(
            mode="visible",
            bids=[
                {"player_id": 1, "channel_id": 7, "amount": 100, "ts": 1.0, "alias": "Anon #1"},
            ],
        )
        auction.aliases = {1: "Anon #1"}
        guild = _Guild(1)
        embed = cfg.build_board_embed(auction, guild, 0)
        text = embed.description + "\n" + "\n".join(f.value for f in embed.fields)
        assert "100" in text
        assert "Current highest" in text


class TestPlaceBid:
    def _cog(self) -> AuctionCog:
        return AuctionCog(MagicMock())

    def _env(self, *, balance: int = 1000, alive: bool = True, open_auction: bool = True):
        guild = _Guild(1)
        alive_role = _Role("Alive")
        guild.roles = [alive_role]
        guild.channels[7] = _Channel(7, "rc-a")
        guild.channels[8] = _Channel(8, "rc-b")
        a = _Member(42, "Alice", [alive_role] if alive else [], guild)
        b = _Member(43, "Bob", [alive_role], guild)
        guild.members[42] = a
        guild.members[43] = b
        auction = _make_auction()
        if not open_auction:
            auction.status = "closed"
        update = MagicMock()
        patches = [
            patch("cogs.auction_cog.load_guild_data", return_value={"alive_role_name": "Alive"}),
            patch("cogs.auction_cog._find_player_rolechat", side_effect=lambda g, m, gd: guild.channels[7] if m is a else guild.channels[8]),
            patch("cogs.auction_cog.get_economy_channel_balance", return_value=balance),
            patch("cogs.auction_cog.update_economy_channel_balance", new=update),
            patch("cogs.auction_cog.save_live_auction"),
            patch.object(AuctionCog, "_refresh_board", new=AsyncMock()),
        ]
        return guild, a, b, auction, patches, update

    @pytest.mark.asyncio
    async def test_leader_change_escrow_move(self):
        """A bids 100 -> hold 100 from A; B bids 150 -> hold 150 from B, refund A 100;
        A bids 200 -> hold 200 from A, refund B 150."""
        cfg = self._cog()
        guild, a, b, auction, patches, update = self._env()
        for p in patches:
            p.start()
        try:
            await cfg._place_bid(a, auction, 100)
            await cfg._place_bid(b, auction, 150)
            await cfg._place_bid(a, auction, 200)
        finally:
            for p in patches:
                p.stop()
        calls = [(c.args[0], c.args[1], c.args[2]) for c in update.call_args_list]
        assert calls == [
            (1, 7, -100),   # A 100 held
            (1, 8, -150),   # B 150 held
            (1, 7, 100),    # A refunded
            (1, 7, -200),   # A 200 held
            (1, 8, 150),    # B refunded
        ]
        assert auction.reserved == {42: 200}
        assert auction.current_high() == 200

    @pytest.mark.asyncio
    async def test_bid_accepted_and_alias_assigned(self):
        cfg = self._cog()
        guild, a, b, auction, patches, update = self._env()
        for p in patches:
            p.start()
        try:
            ok, err, bid = await cfg._place_bid(a, auction, 100)
        finally:
            for p in patches:
                p.stop()
        assert ok is True and err is None
        assert bid["amount"] == 100
        assert bid["alias"] == "Anon #1"
        assert auction.reserved == {42: 100}
        update.assert_called_once_with(1, 7, -100)

    @pytest.mark.asyncio
    async def test_bid_must_exceed_current_high(self):
        cfg = self._cog()
        guild, a, b, auction, patches, update = self._env()
        auction.bids = [{"player_id": 42, "channel_id": 7, "amount": 100, "ts": 1.0, "alias": "Anon #1"}]
        auction.aliases = {42: "Anon #1"}
        auction.reserved = {42: 100}
        for p in patches:
            p.start()
        try:
            ok, err, bid = await cfg._place_bid(a, auction, 100)
            assert ok is False and "exceed" in err
            update.assert_not_called()
            # self-raise: only the difference is held
            ok2, _, _ = await cfg._place_bid(a, auction, 150)
        finally:
            for p in patches:
                p.stop()
        assert ok2 is True
        assert auction.reserved == {42: 150}
        delta_calls = [c.args[2] for c in update.call_args_list]
        assert delta_calls == [-50]

    @pytest.mark.asyncio
    async def test_bid_below_minimum_rejected(self):
        cfg = self._cog()
        guild, a, b, auction, patches, update = self._env()
        auction.min_bid = 500
        for p in patches:
            p.start()
        try:
            ok, err, _ = await cfg._place_bid(a, auction, 100)
        finally:
            for p in patches:
                p.stop()
        assert ok is False and "Minimum bid" in err
        update.assert_not_called()

    @pytest.mark.asyncio
    async def test_bid_insufficient_balance_rejected(self):
        cfg = self._cog()
        guild, a, b, auction, patches, update = self._env(balance=50)
        for p in patches:
            p.start()
        try:
            ok, err, _ = await cfg._place_bid(a, auction, 200)
        finally:
            for p in patches:
                p.stop()
        assert ok is False and "Insufficient" in err
        update.assert_not_called()

    @pytest.mark.asyncio
    async def test_bid_requires_alive(self):
        cfg = self._cog()
        guild, a, b, auction, patches, update = self._env(alive=False)
        for p in patches:
            p.start()
        try:
            ok, err, _ = await cfg._place_bid(a, auction, 100)
        finally:
            for p in patches:
                p.stop()
        assert ok is False and "Alive" in err
        update.assert_not_called()

    @pytest.mark.asyncio
    async def test_bid_when_closed_rejected(self):
        cfg = self._cog()
        guild, a, b, auction, patches, update = self._env(open_auction=False)
        for p in patches:
            p.start()
        try:
            ok, err, _ = await cfg._place_bid(a, auction, 100)
        finally:
            for p in patches:
                p.stop()
        assert ok is False and "not open" in err
        update.assert_not_called()


def _bid(pid, cid, amt, ts, alias):
    return {"player_id": pid, "channel_id": cid, "amount": amt, "ts": ts, "alias": alias}


class TestResolveAndCancel:
    def _setup(self, *, item_type: str = "named", shop_item_id=None, leader_id=3, leader_amount=150):
        cfg = AuctionCog(MagicMock())
        guild = _Guild(1)
        guild.channels[10] = _Channel(10, "board")
        bids = [
            _bid(2, 8, 100, 1.0, "Anon #1"),
            _bid(3, 8, leader_amount, 2.0, "Anon #2"),
        ]
        auction = _make_auction(item_type=item_type, shop_item_id=shop_item_id, bids=bids)
        auction.reserved = {leader_id: leader_amount}
        auction.aliases = {b["player_id"]: b["alias"] for b in bids}
        guild.members[2] = _Member(2, "Bob", [], guild)
        guild.members[3] = _Member(3, "Carol", [], guild)
        return cfg, guild, auction

    @pytest.mark.asyncio
    async def test_named_winner_keeps_escrow_no_extra_charge(self):
        cfg, guild, auction = self._setup(item_type="named", leader_id=3, leader_amount=150)
        with patch("cogs.auction_cog.delete_live_auction"), \
             patch("cogs.auction_cog.load_guild_data", return_value={"overseer_role_name": "Overseer"}), \
             patch("cogs.auction_cog.update_economy_channel_balance") as update, \
             patch.object(cfg, "_refresh_board", new=AsyncMock()):
            await cfg._resolve_auction(auction, guild)
        update.assert_not_called()  # winner's bid was already escrowed
        assert auction.status == "closed"
        embed = guild.channels[10].send.await_args_list[0].kwargs["embed"]
        assert "Carol" in embed.description
        assert "200" not in embed.description  # ^ no winner was wrongly deducted again

    @pytest.mark.asyncio
    async def test_shop_winner_auto_grants_item(self):
        cfg, guild, auction = self._setup(item_type="shop", shop_item_id=77, leader_id=3, leader_amount=150)
        with patch("cogs.auction_cog.delete_live_auction"), \
             patch("cogs.auction_cog.buy_shop_item", return_value=(True, 1, None)) as buy, \
             patch("cogs.auction_cog.update_economy_channel_balance") as update, \
             patch.object(cfg, "_refresh_board", new=AsyncMock()):
            await cfg._resolve_auction(auction, guild)
        buy.assert_called_once_with(1, 8, 77, price=150)
        update.assert_not_called()
        embed = guild.channels[10].send.await_args_list[0].kwargs["embed"]
        assert "Carol" in embed.description

    @pytest.mark.asyncio
    async def test_no_bids_charges_nothing(self):
        cfg, guild, auction = self._setup(item_type="named")
        auction.bids = []
        auction.aliases = {}
        auction.reserved = {}
        with patch("cogs.auction_cog.delete_live_auction"), \
             patch("cogs.auction_cog.update_economy_channel_balance") as update, \
             patch.object(cfg, "_refresh_board", new=AsyncMock()):
            await cfg._resolve_auction(auction, guild)
        update.assert_not_called()
        embed = guild.channels[10].send.await_args_list[0].kwargs["embed"]
        assert "No Valid Bids" in embed.title

    @pytest.mark.asyncio
    async def test_cancel_refunds_all_escrow(self):
        cfg = AuctionCog(MagicMock())
        guild = _Guild(1)
        overseer_role = _Role("Overseer")
        guild.roles = [_Role("Alive"), overseer_role]
        guild.channels[10] = _Channel(10, "board")
        bids = [
            _bid(2, 8, 100, 1.0, "Anon #1"),
            _bid(3, 8, 150, 2.0, "Anon #2"),
        ]
        auction = _make_auction(bids=bids)
        auction.reserved = {3: 150}
        auction.aliases = {2: "Anon #1", 3: "Anon #2"}
        cfg.auctions[1] = auction
        ctx = MagicMock()
        ctx.guild = guild
        ctx.author = _Member(1, "Overseer", [overseer_role], guild)
        ctx.send = AsyncMock()
        with patch("cogs.auction_cog.load_guild_data", return_value={"overseer_role_name": "Overseer"}), \
             patch("cogs.auction_cog.update_economy_channel_balance") as update, \
             patch("cogs.auction_cog.delete_live_auction"), \
             patch.object(cfg, "_refresh_board", new=AsyncMock()):
            await cfg.auc_cancel.callback(cfg, ctx)
        update.assert_called_once_with(1, 8, 150)
        assert auction.status == "cancelled"
        assert auction.reserved == {}