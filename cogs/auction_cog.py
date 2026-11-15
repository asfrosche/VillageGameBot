from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import ui
from discord.ext import commands, tasks

from cogs.data_utils import load_guild_data, save_guild_data
from cogs.economy_cog import _find_player_rolechat
from utils.auction_db import (
    delete_live_auction,
    get_all_live_auctions,
    init_auction_db,
    save_live_auction,
)
from utils.economy_db import (
    buy_shop_item,
    get_economy_channel_balance,
    get_shop_item_by_name,
    update_economy_channel_balance,
)
from utils.embeds import error_embed, info_embed, success_embed, warning_embed


MAX_BID = 1_000_000_000
LOG_LINES_PER_PAGE = 12

DURATION_RE = re.compile(r"(\d+)([mhd])", re.IGNORECASE)


def parse_duration(text: str) -> timedelta | None:
    """Parse `30m`, `2h`, `1d` into a timedelta."""
    match = DURATION_RE.fullmatch(text.strip().lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(days=value)


def _resolve_user_input_to_text(value: str | None) -> str:
    parts = re.split(r"[\s,]+", (value or "").strip())
    return " ".join(parts)


class Auction:
    """State for the single live blind auction of a guild."""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.item: str = ""
        self.item_type: str = "named"  # "named" | "shop"
        self.shop_item_id: int | None = None
        self.mode: str = "sealed"  # "sealed" | "visible"
        self.opened_by_id: int | None = None
        self.ends_at: datetime = datetime.now(timezone.utc)
        self.min_bid: int = 50
        self.board_message_id: int | None = None
        self.board_channel_id: int | None = None
        self.status: str = "open"  # "open" | "closed" | "cancelled"
        self.bids: list[dict] = []
        self.aliases: dict[int, str] = {}
        # Escrow: funds held per player while they are the highest bidder.
        self.reserved: dict[int, int] = {}

    def current_high(self) -> int:
        return max((b["amount"] for b in self.bids), default=0)

    def alias_for(self, player_id: int) -> str:
        alias = self.aliases.get(player_id)
        if alias is None:
            alias = f"Anon #{len(self.aliases) + 1}"
            self.aliases[player_id] = alias
        return alias

    def log_lines(self) -> list[str]:
        lines = []
        for bid in sorted(self.bids, key=lambda b: b["ts"]):
            if self.mode == "visible":
                lines.append(f"🔹 {bid['alias']} bid **{bid['amount']:,}**")
            else:
                lines.append(f"✅ {bid['alias']} placed a bid")
        return lines

    def log_pages(self) -> list[str]:
        lines = self.log_lines()
        if not lines:
            return []
        pages = []
        for i in range(0, len(lines), LOG_LINES_PER_PAGE):
            pages.append("\n".join(lines[i : i + LOG_LINES_PER_PAGE]))
        return pages

    def to_payload(self) -> dict:
        return {
            "item": self.item,
            "item_type": self.item_type,
            "shop_item_id": self.shop_item_id,
            "mode": self.mode,
            "opened_by_id": self.opened_by_id,
            "ends_at": self.ends_at.isoformat(),
            "min_bid": self.min_bid,
            "board_message_id": self.board_message_id,
            "board_channel_id": self.board_channel_id,
            "status": self.status,
            "bids": self.bids,
            "aliases": {str(k): v for k, v in self.aliases.items()},
            "reserved": {str(k): v for k, v in self.reserved.items()},
        }

    @classmethod
    def from_payload(cls, guild_id: int, payload: dict) -> "Auction":
        auction = cls(guild_id)
        auction.item = payload.get("item", "")
        auction.item_type = payload.get("item_type", "named")
        auction.shop_item_id = payload.get("shop_item_id")
        auction.mode = payload.get("mode", "sealed")
        auction.opened_by_id = payload.get("opened_by_id")
        ends_at = payload.get("ends_at")
        if ends_at:
            auction.ends_at = datetime.fromisoformat(ends_at)
        auction.min_bid = int(payload.get("min_bid", 50))
        auction.board_message_id = payload.get("board_message_id")
        auction.board_channel_id = payload.get("board_channel_id")
        auction.status = payload.get("status", "open")
        auction.bids = list(payload.get("bids", []))
        auction.aliases = {
            int(k): v for k, v in (payload.get("aliases") or {}).items()
        }
        auction.reserved = {
            int(k): int(v) for k, v in (payload.get("reserved") or {}).items()
        }
        return auction


class BidModal(ui.Modal):
    def __init__(self, cog: "AuctionCog", auction: Auction):
        super().__init__(title=f"🔨 Bid on {auction.item}")
        self.cog = cog
        self.auction = auction
        self.amount = ui.TextInput(
            label="Your bid amount",
            placeholder="Must exceed the current highest bid",
            style=discord.TextStyle.short,
            min_length=1,
            max_length=12,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.amount.value.strip().replace(",", "").replace("_", "")
        try:
            amount = int(raw)
        except ValueError:
            amount = -1
        await interaction.response.defer(ephemeral=True)
        ok, err, bid = await self.cog._place_bid(interaction.user, self.auction, amount)
        if ok:
            await interaction.followup.send(
                f"✅ Bid placed: **{amount:,}** ({bid['alias']}, this is visible to you only).",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)


class AuctionBoardView(ui.View):
    """The persistent auction board: pagination + a Bid button."""

    def __init__(self, cog: "AuctionCog", auction: Auction):
        super().__init__(timeout=None)
        self.cog = cog
        self.auction = auction
        self.page_index = 0

        self.bid_button = ui.Button(
            label="Bid",
            style=discord.ButtonStyle.success,
            custom_id=f"auction_bid:{auction.guild_id}",
        )
        self.prev_button = ui.Button(
            label="◀",
            style=discord.ButtonStyle.secondary,
            custom_id=f"auction_prev:{auction.guild_id}",
        )
        self.next_button = ui.Button(
            label="▶",
            style=discord.ButtonStyle.secondary,
            custom_id=f"auction_next:{auction.guild_id}",
        )
        self.bid_button.callback = self.bid_callback
        self.prev_button.callback = self.prev_callback
        self.next_button.callback = self.next_callback

        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.add_item(self.bid_button)

    def prepare_buttons(self) -> None:
        is_open = self.auction.status == "open"
        pages = self.auction.log_pages()
        self.bid_button.disabled = not is_open
        self.prev_button.disabled = self.page_index <= 0 or not pages
        self.next_button.disabled = self.page_index >= len(pages) - 1 or not pages

    async def _edit(self, interaction: discord.Interaction) -> None:
        self.prepare_buttons()
        embed = self.cog.build_board_embed(self.auction, interaction.guild, self.page_index)
        await interaction.response.edit_message(embed=embed, view=self)

    async def prev_callback(self, interaction: discord.Interaction) -> None:
        if self.auction.status != "open":
            return
        if self.page_index > 0:
            self.page_index -= 1
        await self._edit(interaction)

    async def next_callback(self, interaction: discord.Interaction) -> None:
        if self.auction.status != "open":
            return
        pages = self.auction.log_pages()
        if self.page_index < len(pages) - 1:
            self.page_index += 1
        await self._edit(interaction)

    async def bid_callback(self, interaction: discord.Interaction) -> None:
        auction = self.auction
        if auction.status != "open":
            await interaction.response.send_message("This auction is not open.", ephemeral=True)
            return
        guild_data = load_guild_data(interaction.guild_id)
        if not self.cog._is_alive(interaction.user, guild_data):
            await interaction.response.send_message("Only Alive players can bid.", ephemeral=True)
            return
        await interaction.response.send_modal(BidModal(self.cog, auction))


class AuctionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auctions: dict[int, Auction] = {}
        self.board_views: dict[int, AuctionBoardView] = {}
        init_auction_db()

    def cog_unload(self) -> None:
        if self.check_expirations.is_running():
            self.check_expirations.cancel()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_alive(self, member: discord.Member, guild_data: dict | None) -> bool:
        role = discord.utils.get(member.guild.roles, name=(guild_data or {}).get("alive_role_name"))
        if role is None:
            return True
        return role in member.roles

    def _is_overseer_or_admin(self, member: discord.Member, guild_data: dict | None) -> bool:
        if member.guild_permissions.administrator:
            return True
        role = discord.utils.get(member.guild.roles, name=(guild_data or {}).get("overseer_role_name"))
        return bool(role and role in member.roles)

    def _persist(self, auction: Auction) -> None:
        save_live_auction(auction.guild_id, int(auction.ends_at.timestamp()), auction.to_payload())

    # ------------------------------------------------------------------
    # Board rendering
    # ------------------------------------------------------------------

    def build_board_embed(self, auction: Auction, guild: discord.Guild, page_index: int = 0) -> discord.Embed:
        mode_icon = "🔒" if auction.mode == "sealed" else "👀"
        mode_label = "Sealed bids" if auction.mode == "sealed" else "Visible bids"
        ends_ts = int(auction.ends_at.timestamp())

        header = [
            f"**Item:** {auction.item}",
            f"**Mode:** {mode_icon} {mode_label}",
            f"**Minimum bid:** {auction.min_bid:,}",
            f"**Bids placed:** {len(auction.bids)}",
            f"**Ends:** <t:{ends_ts}:R> (<t:{ends_ts}:T>)",
        ]
        if auction.status == "open":
            if auction.mode == "visible":
                header.append(f"**Current highest:** {auction.current_high():,}")
            else:
                header.append("**Current highest:** hidden until reveal")
                header.append("Bids must exceed the highest bid placed so far.")
        elif auction.status == "closed":
            header.append("**Status:** 🔨 Closed")
        else:
            header.append("**Status:** ❌ Cancelled")

        title = "🔨 Blind Auction"
        if auction.status != "open":
            title = f"{title} — [{auction.status.upper()}]"
        embed = info_embed(title=title, description="\n".join(header), timestamp=False)

        pages = auction.log_pages()
        if pages:
            page_index = max(0, min(page_index, len(pages) - 1))
            embed.add_field(
                name=f"📜 Bid Log (page {page_index + 1}/{len(pages)})",
                value=pages[page_index],
                inline=False,
            )
        else:
            embed.add_field(name="📜 Bid Log", value="No bids yet. Click **Bid** to place one.", inline=False)
        return embed

    async def _refresh_board(self, auction: Auction) -> None:
        guild = self.bot.get_guild(auction.guild_id)
        if not guild:
            return
        view = self.board_views.get(auction.guild_id)
        if view is None:
            view = AuctionBoardView(self, auction)
            self.board_views[auction.guild_id] = view
            self.bot.add_view(view)
        view.prepare_buttons()

        board_channel = guild.get_channel(auction.board_channel_id) if auction.board_channel_id else None
        if board_channel and auction.board_message_id:
            try:
                message = await board_channel.fetch_message(auction.board_message_id)
            except discord.NotFound:
                message = None
            if message is not None:
                try:
                    await message.edit(embed=self.build_board_embed(auction, guild, view.page_index), view=view)
                except discord.HTTPException:
                    pass
                return
        if board_channel:
            try:
                message = await board_channel.send(embed=self.build_board_embed(auction, guild, view.page_index), view=view)
            except discord.HTTPException:
                return
            auction.board_message_id = message.id
            auction.board_channel_id = board_channel.id
            self._persist(auction)

    # ------------------------------------------------------------------
    # Bidding
    # ------------------------------------------------------------------

    async def _place_bid(
        self,
        member: discord.Member,
        auction: Auction,
        amount: int,
    ) -> tuple[bool, str | None, dict | None]:
        if auction.status != "open":
            return False, "This auction is not open.", None
        if amount <= 0:
            return False, "Amount must be a positive number.", None
        if amount > MAX_BID:
            return False, f"Amount is too large (max {MAX_BID:,}).", None
        if amount < auction.min_bid:
            return False, f"Minimum bid is **{auction.min_bid:,}**.", None
        if amount <= auction.current_high():
            return False, "Your bid must **exceed** the current highest bid (ties are not allowed).", None

        guild_data = load_guild_data(member.guild.id)
        if not self._is_alive(member, guild_data):
            return False, "Only Alive players can bid.", None
        rc = _find_player_rolechat(member.guild, member, guild_data)
        if rc is None:
            return False, "Could not find your RoleChat channel to draw funds from.", None

        # Escrow: on the fly the leader's bid amount is taken out of their RoleChat
        # and held. A new higher bid refunds the previous leader in full and then
        # deducts the new bid, so bid money can never be spent elsewhere.
        held = auction.reserved.get(member.id, 0)
        needs = amount - held
        if needs > 0:
            balance = get_economy_channel_balance(member.guild.id, rc.id)
            if balance < needs:
                return False, f"Insufficient balance. Your RoleChat has **{balance:,}** available; this bid needs **{needs:,}** more.", None

        previous_leader = None
        if auction.reserved:
            previous_leader = max(auction.reserved, key=lambda pid: (auction.reserved.get(pid, 0), pid))
            if auction.reserved.get(previous_leader, 0) <= 0:
                previous_leader = None

        if needs > 0:
            update_economy_channel_balance(member.guild.id, rc.id, -needs)

        if previous_leader is not None and previous_leader != member.id:
            refunded = auction.reserved.pop(previous_leader, 0)
            leader_bids = [b for b in auction.bids if b["player_id"] == previous_leader]
            if refunded > 0 and leader_bids:
                leader_channel = max(leader_bids, key=lambda b: b["ts"])["channel_id"]
                update_economy_channel_balance(member.guild.id, leader_channel, refunded)
        auction.reserved[member.id] = amount

        bid = {
            "player_id": member.id,
            "channel_id": rc.id,
            "amount": amount,
            "ts": datetime.now(timezone.utc).timestamp(),
            "alias": auction.alias_for(member.id),
        }
        auction.bids.append(bid)
        self._persist(auction)
        await self._refresh_board(auction)
        return True, None, bid

    @commands.group(name="auc", aliases=["auction"], invoke_without_command=True)
    async def auc(self, ctx: commands.Context):
        """Blind auction system. Use .auc status / start / bid / extend / close / cancel / alias."""
        await self.auc_status(ctx)

    @auc.command(name="status")
    async def auc_status(self, ctx: commands.Context):
        """Show the current auction board."""
        auction = self.auctions.get(ctx.guild.id)
        if auction is None:
            await ctx.send(embed=info_embed(title="🔨 Blind Auction", description="No auction is currently running.", timestamp=False))
            return
        await ctx.send(embed=self.build_board_embed(auction, ctx.guild, 0))

    @auc.command(name="bid")
    async def auc_bid(self, ctx: commands.Context, amount: int):
        """Place a sealed bid on the current auction. Usage: .auc bid <amount>"""
        auction = self.auctions.get(ctx.guild.id)
        if auction is None:
            await ctx.send("There is no auction running right now.")
            return
        ok, err, bid = await self._place_bid(ctx.author, auction, amount)
        if not ok:
            await ctx.send(f"❌ {err}")
            return
        try:
            await ctx.author.send(
                f"✅ Bid placed on **{auction.item}**: **{amount:,}** ({bid['alias']})."
            )
            await ctx.send(f"✅ Bid placed ({bid['alias']}). Confirmation sent to your DMs.")
        except discord.Forbidden:
            await ctx.send(f"✅ Bid placed ({bid['alias']}) — your amount was not DM'd (DMs closed).")

    @auc.command(name="start")
    async def auc_start(self, ctx: commands.Context, *, args: str):
        """Open a blind auction (alive players). Usage: .auc start <item> <duration> [sealed|visible]"""
        guild_data = load_guild_data(ctx.guild.id)
        if not self._is_alive(ctx.author, guild_data) and not self._is_overseer_or_admin(ctx.author, guild_data):
            await ctx.send("Only Alive players can open an auction.")
            return
        existing = self.auctions.get(ctx.guild.id)
        if existing is not None and existing.status == "open":
            await ctx.send("An auction is already open in this server.")
            return
        if existing is not None and existing.status != "open":
            self.auctions.pop(ctx.guild.id, None)
            self.board_views.pop(ctx.guild.id, None)

        parts = args.strip().split()
        if len(parts) < 2:
            await ctx.send("Usage: `.auc start <item> <duration> [sealed|visible]` — e.g. `.auc start 🎆 Fireworks 2h sealed`")
            return

        mode = "sealed"
        if parts[-1].lower() in ("sealed", "visible"):
            mode = parts.pop().lower()
        duration_str = parts.pop()
        item = " ".join(parts)

        delta = parse_duration(duration_str)
        if delta is None:
            default_seconds = (guild_data or {}).get("auction_default_duration") or 3600
            delta = timedelta(seconds=int(default_seconds))

        min_bid = int((guild_data or {}).get("auction_min_bid") or 50)
        auction_channel_id = (guild_data or {}).get("auction_channel_id")
        board_channel = ctx.guild.get_channel(int(auction_channel_id)) if auction_channel_id else None
        if board_channel is None:
            await ctx.send("No auction board channel is configured. Use `.aucset channel <#channel>` first.")
            return
        auction = Auction(ctx.guild.id)
        auction.item = item
        auction.mode = mode
        auction.opened_by_id = ctx.author.id
        auction.ends_at = datetime.now(timezone.utc) + delta
        auction.min_bid = min_bid
        auction.board_channel_id = board_channel.id

        shop_item = get_shop_item_by_name(ctx.guild.id, item)
        if shop_item is not None:
            auction.item_type = "shop"
            auction.shop_item_id = int(shop_item["id"])

        self.auctions[ctx.guild.id] = auction
        self._persist(auction)
        await self._refresh_board(auction)

        shop_note = f" (matches shop item **{shop_item['name']}** — winner auto-receives it)" if shop_item else " (named item — an Overseer hands it over)"
        await ctx.send(
            embed=success_embed(
                title="🔨 Auction Opened",
                description=f"**{auction.item}** · ends <t:{int(auction.ends_at.timestamp())}:R>\n"
                f"Mode: **{auction.mode}**.{shop_note}",
            )
        )

    @auc.command(name="extend")
    async def auc_extend(self, ctx: commands.Context, *, duration: str):
        """Overseer: add time to the current auction. Usage: .auc extend 30m"""
        guild_data = load_guild_data(ctx.guild.id)
        if not self._is_overseer_or_admin(ctx.author, guild_data):
            await ctx.send("Overseer permission required.")
            return
        auction = self.auctions.get(ctx.guild.id)
        if auction is None or auction.status != "open":
            await ctx.send("There is no open auction.")
            return
        delta = parse_duration(duration)
        if delta is None:
            await ctx.send("Invalid duration. Use e.g. `30m`, `2h`.")
            return
        old = auction.ends_at
        auction.ends_at = auction.ends_at + delta
        self._persist(auction)
        await self._refresh_board(auction)
        await ctx.send(
            embed=info_embed(
                title="⏱ Auction Extended",
                description=f"End was <t:{int(old.timestamp())}:R>, now ends <t:{int(auction.ends_at.timestamp())}:R>.",
            )
        )

    @auc.command(name="close")
    async def auc_close(self, ctx: commands.Context):
        """Overseer: end the auction early (same resolution as the timer)."""
        guild_data = load_guild_data(ctx.guild.id)
        if not self._is_overseer_or_admin(ctx.author, guild_data):
            await ctx.send("Overseer permission required.")
            return
        auction = self.auctions.get(ctx.guild.id)
        if auction is None or auction.status != "open":
            await ctx.send("There is no open auction to close.")
            return
        await self._resolve_auction(auction, ctx.guild)
        self.auctions.pop(ctx.guild.id, None)
        self.board_views.pop(ctx.guild.id, None)
        await ctx.send("Auction closed.")

    @auc.command(name="cancel")
    async def auc_cancel(self, ctx: commands.Context):
        """Overseer: void the current auction (no winner, no charges)."""
        guild_data = load_guild_data(ctx.guild.id)
        if not self._is_overseer_or_admin(ctx.author, guild_data):
            await ctx.send("Overseer permission required.")
            return
        auction = self.auctions.get(ctx.guild.id)
        if auction is None or auction.status != "open":
            await ctx.send("There is no open auction to cancel.")
            return
        for pid, held in list(auction.reserved.items()):
            if held > 0:
                bids = [b for b in auction.bids if b["player_id"] == pid]
                if bids:
                    chan = max(bids, key=lambda b: b["ts"])["channel_id"]
                    update_economy_channel_balance(ctx.guild.id, chan, held)
        auction.reserved.clear()
        auction.status = "cancelled"
        delete_live_auction(auction.guild_id)
        await self._refresh_board(auction)
        self.auctions.pop(ctx.guild.id, None)
        self.board_views.pop(ctx.guild.id, None)
        await ctx.send(embed=info_embed(title="❌ Auction Cancelled", description=f"**{auction.item}** was cancelled. All escrowed bids were refunded.", timestamp=False))

    @auc.command(name="alias")
    async def auc_alias(self, ctx: commands.Context, *, member: discord.Member):
        """Overseer: reveal a player's Anon alias in the current auction."""
        guild_data = load_guild_data(ctx.guild.id)
        if not self._is_overseer_or_admin(ctx.author, guild_data):
            await ctx.send("Overseer permission required.")
            return
        auction = self.auctions.get(ctx.guild.id)
        if auction is None:
            await ctx.send("There is no auction running.")
            return
        alias = auction.aliases.get(member.id)
        bids = [b for b in auction.bids if b["player_id"] == member.id]
        if alias is None:
            await ctx.send(f"**{member.display_name}** has not placed a bid.")
            return
        await ctx.send(
            embed=info_embed(
                title="🔎 Alias Lookup",
                description=f"**{member.display_name}** → **{alias}**\n"
                f"Highest bid: **{max((b['amount'] for b in bids), default=0):,}**\n"
                f"Total bids: **{len(bids)}**",
                timestamp=False,
            )
        )

    # ------------------------------------------------------------------
    # Resolution & config
    # ------------------------------------------------------------------

    async def _resolve_auction(self, auction: Auction, guild: discord.Guild) -> None:
        if auction.status != "open":
            return
        auction.status = "closed"
        delete_live_auction(auction.guild_id)

        # The leader already had their winning amount deducted at bid time (escrow).
        winner = None
        if auction.reserved:
            leader_id = max(auction.reserved, key=lambda pid: (auction.reserved.get(pid, 0), pid))
            if auction.reserved.get(leader_id, 0) > 0:
                winner = max(
                    (b for b in auction.bids if b["player_id"] == leader_id and b["amount"] == auction.reserved[leader_id]),
                    key=lambda b: b["ts"],
                    default=None,
                )

        # Refund any leftover reservations (should be none, but be safe).
        for pid, held in list(auction.reserved.items()):
            if winner is not None and pid == winner["player_id"]:
                continue
            if held > 0:
                bids = [b for b in auction.bids if b["player_id"] == pid]
                if bids:
                    chan = max(bids, key=lambda b: b["ts"])["channel_id"]
                    update_economy_channel_balance(guild.id, chan, held)
        auction.reserved.clear()

        board_channel = guild.get_channel(auction.board_channel_id) if auction.board_channel_id else None
        if winner is None:
            await self._refresh_board(auction)
            if board_channel:
                await board_channel.send(
                    embed=warning_embed(
                        title="🔨 Auction Closed — No Valid Bids",
                        description=f"**{auction.item}** closed with no qualifying bids. Nothing was charged.",
                    )
                )
            self.auctions.pop(auction.guild_id, None)
            self.board_views.pop(auction.guild_id, None)
            return

        paid_note = ""
        if auction.item_type == "shop" and auction.shop_item_id:
            ok, _qty, reason = buy_shop_item(guild.id, winner["channel_id"], auction.shop_item_id, price=winner["amount"])
            if not ok:
                paid_note = f"\n⚠️ Item grant failed ({reason}). The Overseer should resolve this manually."
        else:
            paid_note = "\n🏦 The winning bid was already escrowed from the winner's RoleChat."

        auction.winner = winner
        await self._refresh_board(auction)

        overlay = ""
        if auction.item_type == "shop" and auction.shop_item_id:
            overlay = "\n✉️ The shop item was granted automatically to the winner's inventory."
        else:
            overseer_role = discord.utils.get(guild.roles, name=load_guild_data(guild.id).get("overseer_role_name"))
            if overseer_role:
                overlay = f"\n{overseer_role.mention} — please hand over **{auction.item}** to the winner."

        winner_member = guild.get_member(winner["player_id"])
        winner_display = winner_member.display_name if winner_member else f"<@{winner['player_id']}>"
        if board_channel:
            await board_channel.send(
                embed=success_embed(
                    title="🔨 Auction Closed — Winner",
                    description=f"**{auction.item}**\n"
                    f"🏆 **Winner:** {winner_display}\n"
                    f"💸 **Winning bid:** {winner['amount']:,}\n"
                    f"{winner['alias']} (revealed){paid_note}{overlay}",
                )
            )
        self.auctions.pop(auction.guild_id, None)
        self.board_views.pop(auction.guild_id, None)

    @commands.group(name="aucset", aliases=["auctionconfig"], invoke_without_command=True)
    async def aucset(self, ctx: commands.Context):
        """Configure the blind auction system. Admin only. Use .aucset show for current settings."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("Administrator permission required.")
            return
        await self.aucset_show(ctx)

    async def _require_admin(self, ctx: commands.Context) -> bool:
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("Administrator permission required.")
            return False
        return True

    @aucset.command(name="show")
    async def aucset_show(self, ctx: commands.Context):
        """Show current auction settings."""
        if not await self._require_admin(ctx):
            return
        guild_data = load_guild_data(ctx.guild.id) or {}
        board = ctx.guild.get_channel(int(guild_data["auction_channel_id"])) if guild_data.get("auction_channel_id") else None
        desc = (
            f"**Board channel:** {board.mention if board else 'not set'}\n"
            f"**Minimum bid:** {guild_data.get('auction_min_bid') or 50:,}\n"
            f"**Min increment:** {guild_data.get('auction_min_increment') or 25:,}\n"
            f"**Default duration (s):** {guild_data.get('auction_default_duration') or 3600}"
        )
        await ctx.send(embed=info_embed(title="🔨 Auction Settings", description=desc, timestamp=False))

    @aucset.command(name="channel")
    async def aucset_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the auction board channel. Usage: .aucset channel #auction-house"""
        if not await self._require_admin(ctx):
            return
        guild_data = load_guild_data(ctx.guild.id) or {}
        guild_data["auction_channel_id"] = channel.id
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(embed=success_embed(title="✅ Board channel set", description=f"Auction board will live in {channel.mention}."))

    @aucset.command(name="minbid")
    async def aucset_minbid(self, ctx: commands.Context, value: int):
        """Set the minimum allowed bid."""
        if not await self._require_admin(ctx):
            return
        if value <= 0:
            await ctx.send("Minimum bid must be positive.")
            return
        guild_data = load_guild_data(ctx.guild.id) or {}
        guild_data["auction_min_bid"] = value
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(embed=success_embed(title="✅ Minimum bid set", description=f"Minimum bid is now **{value:,}**."))

    @aucset.command(name="increment")
    async def aucset_increment(self, ctx: commands.Context, value: int):
        """Set the minimum increment above the current highest bid."""
        if not await self._require_admin(ctx):
            return
        if value <= 0:
            await ctx.send("Increment must be positive.")
            return
        guild_data = load_guild_data(ctx.guild.id) or {}
        guild_data["auction_min_increment"] = value
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(embed=success_embed(title="✅ Increment set", description=f"Minimum increment is now **{value:,}**."))

    @aucset.command(name="duration")
    async def aucset_duration(self, ctx: commands.Context, duration: str):
        """Set the default auction duration when none is given. Usage: .aucset duration 1h"""
        if not await self._require_admin(ctx):
            return
        delta = parse_duration(duration)
        if delta is None:
            await ctx.send("Invalid duration. Use e.g. `30m`, `2h`.")
            return
        guild_data = load_guild_data(ctx.guild.id) or {}
        guild_data["auction_default_duration"] = int(delta.total_seconds())
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(embed=success_embed(title="✅ Default duration set", description=f"Default auction duration is now **{duration}**."))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        for row in get_all_live_auctions():
            guild_id = row["guild_id"]
            if guild_id in self.auctions:
                continue
            auction = Auction.from_payload(guild_id, row["payload"])
            if auction.status != "open":
                delete_live_auction(guild_id)
                continue
            self.auctions[guild_id] = auction
            view = AuctionBoardView(self, auction)
            self.board_views[guild_id] = view
            self.bot.add_view(view)
            try:
                await self._refresh_board(auction)
            except Exception:
                pass
            if auction.ends_at <= datetime.now(timezone.utc):
                guild = self.bot.get_guild(guild_id)
                if guild:
                    await self._resolve_auction(auction, guild)

        if not self.check_expirations.is_running():
            self.check_expirations.start()

    @tasks.loop(seconds=15)
    async def check_expirations(self):
        now = datetime.now(timezone.utc)
        for guild_id, auction in list(self.auctions.items()):
            if auction.status != "open":
                continue
            if auction.ends_at <= now:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    try:
                        await self._resolve_auction(auction, guild)
                    except Exception:
                        pass

    @check_expirations.before_loop
    async def before_check_expirations(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(AuctionCog(bot))