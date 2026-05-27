from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord.ui import View

from cogs.data_utils import load_guild_data, save_guild_data
from utils.bot_db import (
    add_inventory_item_channel,
    add_shop_item,
    get_economy_channel_balance,
    get_inventory_channel,
    get_shop_item_by_name,
    get_shop_items,
    remove_shop_item_by_name,
    update_economy_channel_balance,
    update_shop_item_by_name,
)
from utils.embeds import info_embed, success_embed, error_embed, plain_embed


DEFAULT_SHOP_ITEMS = [
    {"name": "🎆 Fireworks", "description": "Reveal your current position in Announcements", "price": 100},
    {"name": "👟 Shoes", "description": "Gives you an additional visit", "price": 250},
    {"name": "✉ Whisper", "description": "Send a 10 words private message to someone", "price": 200},
]

# Maximum value accepted by .setcollect to prevent accidental huge payouts.
MAX_COLLECT_AMOUNT = 10_000


def _is_rolechat_category(
    ctx: commands.Context,
    channel: discord.TextChannel | None = None,
    guild_data: dict | None = None,
) -> bool:
    """Return True if *channel* (default: ctx.channel) is in a rolechat category.

    Pass *guild_data* when you've already loaded it to avoid a double read.
    """
    channel = channel or ctx.channel
    if guild_data is None:
        guild_data = load_guild_data(ctx.guild.id)
    if not guild_data:
        return False
    rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
    alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
    dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
    return channel.category in (rc_cat, alt_cat, dead_rc)


def _is_houses_category(
    ctx: commands.Context,
    channel: discord.TextChannel | None = None,
    guild_data: dict | None = None,
) -> bool:
    """Return True if *channel* (default: ctx.channel) is in the houses category.

    Pass *guild_data* when you've already loaded it to avoid a double read.
    """
    channel = channel or ctx.channel
    if guild_data is None:
        guild_data = load_guild_data(ctx.guild.id)
    if not guild_data:
        return False
    houses = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))
    return channel.category == houses


async def _log_economy(
    guild: discord.Guild,
    guild_data: dict,
    *,
    action: str,
    actor: discord.Member,
    details: str,
) -> None:
    """Post a one-line audit embed to the economy log channel, if configured.

    The channel is identified by the ``economy_log_channel_name`` key in
    guild_data. If the key is missing or the channel doesn't exist, this
    is a silent no-op so nothing breaks when logging isn't set up.
    """
    log_channel_name = guild_data.get("economy_log_channel_name")
    if not log_channel_name:
        return
    log_ch = discord.utils.get(guild.text_channels, name=log_channel_name)
    if not log_ch:
        return
    embed = discord.Embed(
        color=0xFF3FB9,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=f"{actor.display_name} ({actor.id})", icon_url=actor.display_avatar.url)
    embed.title = f"💰 Economy — {action}"
    embed.description = details
    try:
        await log_ch.send(embed=embed)
    except discord.HTTPException:
        pass


# ─────────────────────────────────────────────
# Shop pagination view
# ─────────────────────────────────────────────

class ShopView(View):
    """Paginated shop embed. Only the original invoker can change pages."""

    def __init__(self, pages: list[str], invoker: discord.Member):
        super().__init__(timeout=120)
        self.pages = pages
        self.invoker = invoker
        self.page_index = 0

    def _build_embed(self) -> discord.Embed:
        embed = plain_embed(title="🛒 Shop", description=self.pages[self.page_index])
        embed.set_footer(
            text=f"Page {self.page_index + 1}/{len(self.pages)} • Use .buy <name> to purchase"
        )
        return embed

    async def _update(self, interaction: discord.Interaction) -> None:
        if interaction.user != self.invoker:
            await interaction.response.send_message("This shop menu isn't yours.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page_index > 0:
            self.page_index -= 1
        await self._update(interaction)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page_index < len(self.pages) - 1:
            self.page_index += 1
        await self._update(interaction)


# ─────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────

class Economy(commands.Cog):
    """Rolechat-based economy: balance and inventory per rolechat."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _ensure_default_items(self, guild: discord.Guild) -> None:
        items = get_shop_items(guild.id)
        existing_names = {i["name"] for i in items}
        for item in DEFAULT_SHOP_ITEMS:
            if item["name"] in existing_names:
                continue
            add_shop_item(
                guild.id,
                name=item["name"],
                description=item["description"],
                price=item["price"],
                is_default=True,
            )

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._ensure_default_items(guild)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._ensure_default_items(guild)

    # ------------------------------------------------------------------ #
    # Player commands
    # ------------------------------------------------------------------ #

    @commands.command(name="balance", aliases=["bal"])
    async def balance(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Show balance for current rolechat (or .bal #channel for admins). Only usable in rolechats category."""
        target = channel or ctx.channel
        guild_data = load_guild_data(ctx.guild.id)

        if not _is_rolechat_category(ctx, target, guild_data):
            return await ctx.send("Use this command in a channel inside the RoleChats category.")

        # Non-admins can only check their own current channel's balance.
        if channel and not ctx.author.guild_permissions.administrator:
            return await ctx.send("You can only check the balance of your current channel.")

        bal = get_economy_channel_balance(ctx.guild.id, target.id)
        embed = info_embed(
            title=f"💰 Balance — #{target.name}",
            description=f"**Balance:** {bal:,}",
        )
        await ctx.send(embed=embed)

    @commands.command(name="collect")
    @commands.has_permissions(administrator=True)
    async def collect(self, ctx: commands.Context):
        """Admin only: add the set collect amount to every rolechat's balance."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        amount = int(guild_data.get("economy_collect_amount", 250))
        if amount <= 0:
            return await ctx.send("Collect amount is 0. Use `.setcollect <value>` to set it.")
        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        count = 0
        for cat in (rc_cat, alt_cat, dead_rc):
            if not cat:
                continue
            for ch in cat.text_channels:
                update_economy_channel_balance(ctx.guild.id, ch.id, amount)
                count += 1
        embed = success_embed(
            title="💸 Collect",
            description=f"Added **{amount:,}** to **{count}** rolechat(s).",
        )
        await ctx.send(embed=embed)

    @commands.command(name="setcollect")
    @commands.has_permissions(administrator=True)
    async def setcollect(self, ctx: commands.Context, value: int):
        """Set the amount added to each rolechat when using .collect. Max: 10,000."""
        if value < 0:
            return await ctx.send("Value must be >= 0.")
        if value > MAX_COLLECT_AMOUNT:
            return await ctx.send(f"Value cannot exceed **{MAX_COLLECT_AMOUNT:,}**.")
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        guild_data["economy_collect_amount"] = value
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(f"Collect amount set to **{value:,}**.")

    @commands.command(name="shop")
    async def shop(self, ctx: commands.Context):
        """View the server shop."""
        await self._ensure_default_items(ctx.guild)
        items = get_shop_items(ctx.guild.id)
        if not items:
            return await ctx.send("The shop is empty. Admins can add items with `.additem <price> <name>`.")

        per_page = 10
        pages = []
        for i in range(0, len(items), per_page):
            chunk = items[i: i + per_page]
            lines = []
            for it in chunk:
                line = f"**{it['name']}** — **{it['price']:,}**"
                if it.get("description"):
                    line += f"\n> {it['description']}"
                lines.append(line)
            pages.append("\n\n".join(lines))

        view = ShopView(pages, ctx.author)
        await ctx.send(embed=view._build_embed(), view=view if len(pages) > 1 else None)

    @commands.command(name="buy")
    async def buy(self, ctx: commands.Context, item_name: str, quantity: int = 1):
        """Buy an item by name (partial match). Only in rolechats."""
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, guild_data=guild_data):
            return await ctx.send("Buy items only in a RoleChat channel.")
        if quantity <= 0:
            return await ctx.send("Quantity must be at least 1.")

        item = get_shop_item_by_name(ctx.guild.id, item_name)
        if not item:
            return await ctx.send("Item not found. Use a part of the name (e.g. .buy fumo).")

        cost = item["price"] * quantity
        channel_id = ctx.channel.id
        bal = get_economy_channel_balance(ctx.guild.id, channel_id)
        if cost > bal:
            return await ctx.send(f"You don't have enough coins. You need **{cost:,}**.")

        update_economy_channel_balance(ctx.guild.id, channel_id, -cost)
        new_qty = add_inventory_item_channel(ctx.guild.id, channel_id, item["id"], quantity)

        embed = success_embed(
            title="✅ Purchase successful",
            description=(
                f"You bought **{quantity}× {item['name']}** for **{cost:,}** coins.\n"
                f"You now have **{new_qty}×** in this rolechat."
            ),
        )
        await ctx.send(embed=embed)

    @commands.command(name="inventory", aliases=["inv"])
    async def inventory(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Show inventory for current rolechat (or .inv #channel for admins). Only in rolechats."""
        target = channel or ctx.channel
        guild_data = load_guild_data(ctx.guild.id)

        if not _is_rolechat_category(ctx, target, guild_data):
            return await ctx.send("Use this command in a channel inside the RoleChats category.")
        if channel and not ctx.author.guild_permissions.administrator:
            return await ctx.send("You can only view your current channel's inventory.")

        items = get_inventory_channel(ctx.guild.id, target.id)
        if not items:
            return await ctx.send(f"No items in #{target.name}.")

        lines = []
        for it in items:
            line = f"**{it['name']}** × {it['quantity']}"
            if it.get("description"):
                line += f"\n> {it['description']}"
            lines.append(line)
        embed = plain_embed(title=f"🎒 Inventory — #{target.name}", description="\n\n".join(lines))
        await ctx.send(embed=embed)

    @commands.command(name="give")
    async def give(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Give coins to a member. Use in a house channel; both you and the member must have read/send there."""
        guild_data = load_guild_data(ctx.guild.id)

        if not _is_houses_category(ctx, guild_data=guild_data):
            return await ctx.send("Use `.give` in a channel inside the Houses category.")
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0.")
        if member.bot:
            return await ctx.send("You can't give coins to a bot.")
        if member == ctx.author:
            return await ctx.send("You can't give coins to yourself.")

        ch = ctx.channel
        perms_sender = ch.permissions_for(ctx.author)
        perms_recv = ch.permissions_for(member)
        if not (perms_sender.read_messages and perms_sender.send_messages):
            return await ctx.send("You need read and send permission in this channel.")
        if not (perms_recv.read_messages and perms_recv.send_messages):
            return await ctx.send("The recipient must have read and send permission in this channel.")

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))

        def _find_rc(target_member: discord.Member) -> discord.TextChannel | None:
            for cat in (rc_cat, alt_cat, dead_rc):
                if not cat:
                    continue
                for c in cat.text_channels:
                    if c.permissions_for(target_member).send_messages:
                        return c
            return None

        sender_rc = _find_rc(ctx.author)
        target_rc = _find_rc(member)

        if not sender_rc:
            return await ctx.send("Could not find your rolechat.")
        if not target_rc:
            return await ctx.send("Could not find a rolechat for that member.")
        if sender_rc == target_rc:
            return await ctx.send("You can't give coins to someone in the same rolechat.")

        sender_bal = get_economy_channel_balance(ctx.guild.id, sender_rc.id)
        if amount > sender_bal:
            return await ctx.send(f"You don't have enough coins. Balance: **{sender_bal:,}**.")

        update_economy_channel_balance(ctx.guild.id, sender_rc.id, -amount)
        update_economy_channel_balance(ctx.guild.id, target_rc.id, amount)

        await ctx.send(f"You gave **{amount:,}** to {member.mention}.")
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Give",
            actor=ctx.author,
            details=(
                f"{ctx.author.mention} gave **{amount:,}** coins to {member.mention}\n"
                f"From #{sender_rc.name} → #{target_rc.name}"
            ),
        )

    # ------------------------------------------------------------------ #
    # Admin commands
    # ------------------------------------------------------------------ #

    @commands.command(name="additem")
    @commands.has_permissions(administrator=True)
    async def additem(self, ctx: commands.Context, price: int, *, name: str):
        """Add a shop item. Usage: .additem <price> <name>"""
        if price <= 0:
            return await ctx.send("Price must be greater than 0.")
        name = name.strip()
        if not name:
            return await ctx.send("Item name cannot be empty.")
        add_shop_item(ctx.guild.id, name=name, description="", price=price, is_default=False)
        embed = success_embed(title="🛒 Item added", description=f"**{name}** for **{price:,}** coins.")
        await ctx.send(embed=embed)

    @commands.command(name="edititem")
    @commands.has_permissions(administrator=True)
    async def edititem(self, ctx: commands.Context, field: str, item_name: str, *, new_value: str):
        """Edit an item: .edititem price/name/description <item_name> <new_value>"""
        field = field.lower()
        if field not in ("price", "name", "description"):
            return await ctx.send("Field must be price, name, or description.")
        if field == "price":
            try:
                val = int(new_value.strip())
            except ValueError:
                return await ctx.send("New price must be a number.")
            if val < 0:
                return await ctx.send("Price must be >= 0.")
            ok = update_shop_item_by_name(ctx.guild.id, item_name, price=val)
        elif field == "name":
            ok = update_shop_item_by_name(ctx.guild.id, item_name, name=new_value.strip())
        else:
            ok = update_shop_item_by_name(ctx.guild.id, item_name, description=new_value.strip())
        if not ok:
            return await ctx.send("Item not found. Use a part of the name.")
        await ctx.send(f"Updated **{field}** for that item.")

    @commands.command(name="delitem")
    @commands.has_permissions(administrator=True)
    async def delitem(self, ctx: commands.Context, *, item_name: str):
        """Remove an item from the shop by name."""
        ok = remove_shop_item_by_name(ctx.guild.id, item_name.strip())
        if not ok:
            return await ctx.send("Item not found. Use a part of the name.")
        await ctx.send("Item removed from the shop.")

    @commands.command(name="addmoney")
    @commands.has_permissions(administrator=True)
    async def addmoney(self, ctx: commands.Context, channel: discord.TextChannel, amount: int):
        """Add money to a rolechat's balance. Usage: .addmoney #channel <amount>"""
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0.")
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, channel, guild_data):
            return await ctx.send("Channel must be in the RoleChats category.")
        bal = update_economy_channel_balance(ctx.guild.id, channel.id, amount)
        await ctx.send(f"Added **{amount:,}** to {channel.mention}. New balance: **{bal:,}**.")
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Add Money",
            actor=ctx.author,
            details=f"Added **{amount:,}** to {channel.mention}. New balance: **{bal:,}**.",
        )

    @commands.command(name="removemoney")
    @commands.has_permissions(administrator=True)
    async def removemoney(self, ctx: commands.Context, channel: discord.TextChannel, amount: int):
        """Remove money from a rolechat's balance. Usage: .removemoney #channel <amount>"""
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0.")
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, channel, guild_data):
            return await ctx.send("Channel must be in the RoleChats category.")
        bal = get_economy_channel_balance(ctx.guild.id, channel.id)
        amount = min(amount, bal)
        new_bal = update_economy_channel_balance(ctx.guild.id, channel.id, -amount)
        await ctx.send(f"Removed **{amount:,}** from {channel.mention}. New balance: **{new_bal:,}**.")
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Remove Money",
            actor=ctx.author,
            details=f"Removed **{amount:,}** from {channel.mention}. New balance: **{new_bal:,}**.",
        )

    @commands.command(name="richlist")
    @commands.has_permissions(administrator=True)
    async def richlist(self, ctx: commands.Context, top: int = 10):
        """Show the top rolechats ranked by balance. Usage: .richlist [top=10]"""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")

        top = max(1, min(top, 50))

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))

        entries: list[tuple[int, discord.TextChannel]] = []
        for cat in (rc_cat, alt_cat, dead_rc):
            if not cat:
                continue
            for ch in cat.text_channels:
                bal = get_economy_channel_balance(ctx.guild.id, ch.id)
                entries.append((bal, ch))

        if not entries:
            return await ctx.send("No rolechats found.")

        entries.sort(reverse=True)
        lines = [
            f"**#{rank}.** {ch.mention} — **{bal:,}** coins"
            for rank, (bal, ch) in enumerate(entries[:top], start=1)
        ]
        embed = plain_embed(
            title=f"💰 Rich List — Top {min(top, len(entries))}",
            description="\n".join(lines),
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
