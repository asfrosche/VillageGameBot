import asyncio
import random
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord.ui import Modal, Select, View

from cogs.data_utils import (
    load_guild_data,
    save_guild_data,
)
from utils.bot_db import (
    add_inventory_item,
    add_inventory_item_channel,
    add_shop_item,
    get_economy_account,
    get_economy_channel_balance,
    get_inventory,
    get_inventory_channel,
    get_shop_item_by_name,
    get_shop_items,
    get_top_economy_users,
    remove_shop_item_by_name,
    update_economy_balance,
    update_economy_channel_balance,
    update_shop_item_by_name,
)
from utils.embeds import info_embed, success_embed, error_embed, plain_embed


DEFAULT_SHOP_ITEMS = [
    {"name": "🎆 Fireworks", "description": "Reveal your current position in Announcements", "price": 100},
    {"name": "👟 Shoes", "description": "Gives you an additional visit", "price": 250},
    {"name": "✉ Whisper", "description": "Send a private message to someone", "price": 200},
    {"name": "🧹 Broom", "description": "Clears messages in a house channel", "price": 300},
    {"name": "📜 Will", "description": "Notify Overseers to pin your last will", "price": 150},
    {"name": "🚪 Extra Visit", "description": "Grants an extra visit to your rolechat", "price": 200},
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
# Shop components
# ─────────────────────────────────────────────

class ShopItemSelect(Select):
    """Dropdown listing items on the current page."""

    def __init__(self, items: list[dict], page_offset: int):
        options = []
        for i, item in enumerate(items, start=page_offset + 1):
            options.append(
                discord.SelectOption(
                    label=f"{i}. {item['name']}",
                    description=f"{item['price']:,} coins",
                    value=str(item["id"]),
                )
            )
        super().__init__(placeholder="Pick an item...", options=options, min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user != self.view.invoker:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        self.view.selected_item_id = int(self.values[0])
        await interaction.response.defer()


class EditPriceModal(Modal):
    """Modal to edit an item's price."""

    def __init__(self, guild_id: int, item: dict):
        super().__init__(title=f"Edit Price — {item['name']}")
        self.guild_id = guild_id
        self.item = item
        self.price_input = discord.ui.TextInput(
            label="New price",
            placeholder=str(item["price"]),
            min_length=1,
            max_length=10,
        )
        self.add_item(self.price_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            price = int(self.price_input.value)
        except ValueError:
            return await interaction.response.send_message("Must be a number.", ephemeral=True)
        if price < 0:
            return await interaction.response.send_message("Price must be >= 0.", ephemeral=True)
        update_shop_item_by_name(self.guild_id, self.item["name"], price=price)
        await interaction.response.send_message(
            f"**{self.item['name']}** price → **{price:,}**.", ephemeral=True
        )


class ShopView(View):
    """Paginated shop with item selector, buy, and edit-price buttons."""

    def __init__(self, pages: list[str], items_by_page: list[list[dict]], invoker: discord.Member, guild_id: int, channel_id: int):
        super().__init__(timeout=120)
        self.pages = pages
        self.items_by_page = items_by_page
        self.invoker = invoker
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.page_index = 0
        self.selected_item_id: int | None = None
        self._rebuild()

    def _build_embed(self) -> discord.Embed:
        embed = plain_embed(title="🛒 Shop", description=self.pages[self.page_index])
        embed.set_footer(
            text=f"Page {self.page_index + 1}/{len(self.pages)} • Select item, then Buy"
        )
        return embed

    def _rebuild(self) -> None:
        self.clear_items()

        self.add_item(self.btn_prev)
        self.add_item(self.btn_next)

        items = self.items_by_page[self.page_index]
        if items:
            self.add_item(ShopItemSelect(items, self.page_index * 10))

        self.add_item(self.btn_buy)
        if self.invoker.guild_permissions.administrator:
            self.add_item(self.btn_edit_price)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if self.page_index > 0:
            self.page_index -= 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if self.page_index < len(self.pages) - 1:
            self.page_index += 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Buy", emoji="🛒", style=discord.ButtonStyle.success, row=2)
    async def btn_buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if self.selected_item_id is None:
            return await interaction.response.send_message("Pick an item from the dropdown first.", ephemeral=True)

        items = get_shop_items(self.guild_id)
        item = next((i for i in items if i["id"] == self.selected_item_id), None)
        if not item:
            return await interaction.response.send_message("That item is gone.", ephemeral=True)

        bal = get_economy_channel_balance(self.guild_id, self.channel_id)
        if item["price"] > bal:
            return await interaction.response.send_message(
                f"Need **{item['price']:,}**, have **{bal:,}**.", ephemeral=True
            )

        update_economy_channel_balance(self.guild_id, self.channel_id, -item["price"])
        new_qty = add_inventory_item_channel(self.guild_id, self.channel_id, item["id"], 1)
        await interaction.response.send_message(
            f"Bought **{item['name']}** for **{item['price']:,}**. ×{new_qty}", ephemeral=True
        )

    @discord.ui.button(label="Edit Price", emoji="✏️", style=discord.ButtonStyle.secondary, row=2)
    async def btn_edit_price(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Admin only.", ephemeral=True)
        if self.selected_item_id is None:
            return await interaction.response.send_message("Pick an item from the dropdown first.", ephemeral=True)

        items = get_shop_items(self.guild_id)
        item = next((i for i in items if i["id"] == self.selected_item_id), None)
        if not item:
            return await interaction.response.send_message("Item not found.", ephemeral=True)

        await interaction.response.send_modal(EditPriceModal(self.guild_id, item))


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
        items_by_page = []
        for i in range(0, len(items), per_page):
            chunk = items[i: i + per_page]
            items_by_page.append(chunk)
            lines = []
            for idx, it in enumerate(chunk, start=i + 1):
                line = f"**{idx}.** **{it['name']}** — **{it['price']:,}**"
                if it.get("description"):
                    line += f"\n> {it['description']}"
                lines.append(line)
            pages.append("\n\n".join(lines))

        view = ShopView(pages, items_by_page, ctx.author, ctx.guild.id, ctx.channel.id)
        await ctx.send(embed=view._build_embed(), view=view)

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


    # ------------------------------------------------------------------ #
    # User-based economy (ebeblieve-style)
    # ------------------------------------------------------------------ #

    @commands.command(name="give-money", aliases=["give_money"])
    async def give_money(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Transfer coins from your wallet to another user."""
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0.")
        if member.bot:
            return await ctx.send("You can't give coins to a bot.")
        if member == ctx.author:
            return await ctx.send("You can't give coins to yourself.")

        wallet, _ = get_economy_account(ctx.guild.id, ctx.author.id)
        if amount > wallet:
            return await ctx.send(
                f"You don't have enough coins. Your wallet: **{wallet:,}**."
            )

        update_economy_balance(ctx.guild.id, ctx.author.id, delta_wallet=-amount)
        update_economy_balance(ctx.guild.id, member.id, delta_wallet=amount)

        await ctx.send(f"You gave **{amount:,}** coins to {member.mention}.")

    @commands.command(name="sell-item", aliases=["sell_item", "sell"])
    async def sell_item(self, ctx: commands.Context, *, item_name: str):
        """Sell an item from your inventory back to the shop (50% refund)."""
        item = get_shop_item_by_name(ctx.guild.id, item_name)
        if not item:
            return await ctx.send("Item not found.")

        inv = get_inventory(ctx.guild.id, ctx.author.id)
        owned = next((i for i in inv if i["item_id"] == item["id"]), None)
        if not owned or owned["quantity"] < 1:
            return await ctx.send("You don't own that item.")

        refund = item["price"] // 2
        add_inventory_item(ctx.guild.id, ctx.author.id, item["id"], -1)
        update_economy_balance(ctx.guild.id, ctx.author.id, delta_wallet=refund)

        await ctx.send(
            f"Sold **{item['name']}** for **{refund:,}** coins (50% of shop price)."
        )

    @commands.command(name="add-money-role", aliases=["add_money_role", "addmrole"])
    @commands.has_permissions(administrator=True)
    async def add_money_role(self, ctx: commands.Context, role: discord.Role, amount: int):
        """Add money to all members with a specific role."""
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0.")
        if amount > 10_000:
            return await ctx.send("Amount cannot exceed **10,000** per user.")

        count = 0
        for member in role.members:
            if not member.bot:
                update_economy_balance(ctx.guild.id, member.id, delta_wallet=amount)
                count += 1

        await ctx.send(f"Added **{amount:,}** coins to **{count}** members with {role.mention}.")

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    async def leaderboard(self, ctx: commands.Context, top: int = 10):
        """Show the richest users by total (wallet + bank)."""
        top = max(1, min(top, 50))
        entries = get_top_economy_users(ctx.guild.id, top)
        if not entries:
            return await ctx.send("No economy data yet.")

        lines = []
        for rank, entry in enumerate(entries, start=1):
            user = ctx.guild.get_member(entry["user_id"])
            name = user.mention if user else f"`{entry['user_id']}`"
            lines.append(
                f"**#{rank}.** {name} — **{entry['total']:,}** "
                f"(wallet: {entry['wallet']:,}, bank: {entry['bank']:,})"
            )

        embed = plain_embed(
            title=f"🏆 Leaderboard — Top {len(entries)}",
            description="\n".join(lines),
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Item usage & admin distribution
    # ------------------------------------------------------------------ #

    @commands.command(name="use")
    async def use_item(self, ctx: commands.Context, *, item_name: str):
        """Use an item from your user inventory."""
        item = get_shop_item_by_name(ctx.guild.id, item_name)
        if not item:
            return await ctx.send("Item not found.")

        inv = get_inventory(ctx.guild.id, ctx.author.id)
        owned = next((i for i in inv if i["item_id"] == item["id"]), None)
        if not owned or owned["quantity"] < 1:
            return await ctx.send("You don't have that item. Buy it first with `.buy` or get it from an Overseer.")

        add_inventory_item(ctx.guild.id, ctx.author.id, item["id"], -1)
        name_lower = item["name"].lower()

        if "firework" in name_lower:
            await self._trigger_fireworks(ctx)
        elif "whisper" in name_lower:
            await self._trigger_whisper(ctx)
        elif "broom" in name_lower:
            await self._trigger_broom(ctx)
        elif "extra visit" in name_lower or "shoe" in name_lower:
            await self._trigger_extra_visit(ctx)
        elif "will" in name_lower:
            await self._trigger_will(ctx)
        else:
            await ctx.send(f"Used **{item['name']}**.")

    async def _trigger_fireworks(self, ctx: commands.Context) -> None:
        """Reveal the caller's position in announcements."""
        guild_data = load_guild_data(ctx.guild.id)
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))
        ann_ch = discord.utils.get(ctx.guild.channels, name=guild_data.get("announcements_channel_name"))
        houses_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))
        if not ann_ch or not houses_cat:
            return await ctx.send("Announcements channel or Houses category not set up.")

        gifs = [
            "https://tenor.com/view/lanterns-flying-lantern-chinese-lantern-gif-9054613",
            "https://tenor.com/view/lanterns-lights-peace-gif-15906930",
            "https://tenor.com/view/tangled-tangled-movie-lanterns-tangled-lanterns-i-see-the-light-gif-12379369862241479266",
        ]
        gif = random.choice(gifs)
        for member in ctx.channel.members:
            if alive_role in member.roles or sponsor_role in member.roles:
                for ch in houses_cat.text_channels:
                    if ch.permissions_for(member).send_messages:
                        await ann_ch.send(
                            f"{alive_role.mention}{sponsor_role.mention}\n{member.mention} is in {ch.name}"
                        )
                        await ann_ch.send(gif)
                        await ctx.send("🎆 Fireworks launched!")
                        return
        await ctx.send("No eligible member found in this channel.")

    async def _trigger_whisper(self, ctx: commands.Context) -> None:
        """Start the whisper target selection UI."""
        guild_data = load_guild_data(ctx.guild.id)
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        if not alive_role:
            return await ctx.send("Alive role not configured.")

        options = []
        for member in ctx.guild.members:
            if alive_role in member.roles:
                options.append(discord.SelectOption(label=member.display_name[:95], value=str(member.id)))
                if len(options) >= 25:
                    break

        if not options:
            return await ctx.send("No alive players to whisper to.")

        select = discord.ui.Select(placeholder="Select recipient...", options=options, min_values=1, max_values=1)

        async def on_select(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                return await interaction.response.send_message("Not your menu.", ephemeral=True)
            select.disabled = True
            await interaction.message.edit(view=view)
            target_id = int(select.values[0])
            target = ctx.guild.get_member(target_id)
            if not target:
                return await interaction.response.send_message("User not found.", ephemeral=True)

            prompt = await interaction.response.send_message(
                embed=plain_embed(title="✉ Whisper", description=f"Reply to this message with your whisper to {target.mention}."),
            )
            prompt_msg = await interaction.original_response()

            try:
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel and m.reference and m.reference.message_id == prompt_msg.id
                reply = await ctx.bot.wait_for("message", check=check, timeout=300)
            except asyncio.TimeoutError:
                await ctx.send("Whisper cancelled (timeout).")
                return

            rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
            log_ch = discord.utils.get(ctx.guild.channels, name=guild_data.get("whisper_logs_channel_name"))
            for ch in rc_cat.text_channels:
                if target in ch.members:
                    embed = info_embed()
                    if guild_data.get("showwhispersender"):
                        embed.add_field(name=f"{ctx.author.mention} sent you a whisper:", value=reply.content, inline=False)
                    else:
                        embed.add_field(name="Someone sent you a whisper:", value=reply.content, inline=False)
                    await ch.send(f"{target.mention}", embed=embed)
                    if log_ch:
                        log_embed = info_embed()
                        log_embed.add_field(name=f"{ctx.author.mention} → {target.mention}:", value=reply.content, inline=False)
                        await log_ch.send(embed=log_embed)
                    break
            await ctx.send("✉ Whisper sent.")

        select.callback = on_select
        view = View(timeout=300)
        view.add_item(select)
        embed = info_embed(title="Who do you want to whisper?", description="Select an alive player.")
        await ctx.send(embed=embed, view=view)

    async def _trigger_broom(self, ctx: commands.Context) -> None:
        """Clears messages in the current channel (last 5 messages)."""
        try:
            deleted = await ctx.channel.purge(limit=5, bulk=True)
            await ctx.send(f"🧹 Broom swept away **{len(deleted)}** messages.", delete_after=5)
        except discord.Forbidden:
            await ctx.send("I need Manage Messages permission to use the broom here.")

    async def _trigger_extra_visit(self, ctx: commands.Context) -> None:
        """Grants an extra visit and announces in the rolechat."""
        guild_data = load_guild_data(ctx.guild.id)
        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        sent = False
        for cat in (rc_cat, alt_cat, dead_rc):
            if not cat:
                continue
            for ch in cat.text_channels:
                if ctx.author in ch.members and ch.permissions_for(ctx.author).send_messages:
                    await ch.send(f"🚪 **{ctx.author.display_name}** used an extra visit!")
                    sent = True
                    break
            if sent:
                break
        if not sent:
            await ctx.send("Could not find a rolechat to announce the visit.")
        else:
            await ctx.send("🚪 Extra visit used!")

    async def _trigger_will(self, ctx: commands.Context) -> None:
        """Notify Overseers to pin the user's last will."""
        guild_data = load_guild_data(ctx.guild.id)
        overseer_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
        if not overseer_role:
            return await ctx.send("Overseer role not found.")
        await ctx.send(
            f"{overseer_role.mention} **{ctx.author.display_name}** has used a Will. "
            f"Please check their will message and pin it.\n"
            f"Will message (reply below):"
        )
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            reply = await ctx.bot.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError:
            return await ctx.send("Will cancelled (timeout).")
        await ctx.send(f"{overseer_role.mention} {reply.jump_url} — please pin this will.")

    @commands.command(name="additemrole")
    @commands.has_permissions(administrator=True)
    async def additemrole(self, ctx: commands.Context, role: discord.Role, *, items_str: str):
        """Add items to all members with a role. Format: .additemrole @Alive broom 3, fireworks 1"""
        pairs = [p.strip() for p in items_str.split(",")]
        items_to_add = []
        for pair in pairs:
            parts = pair.rsplit(None, 1)
            if len(parts) != 2:
                await ctx.send(f"Invalid pair: `{pair}` — use `<item> <qty>`")
                continue
            name_part, qty_str = parts
            try:
                qty = int(qty_str)
            except ValueError:
                await ctx.send(f"Invalid quantity for `{pair}`.")
                continue
            item = get_shop_item_by_name(ctx.guild.id, name_part)
            if not item:
                await ctx.send(f"Item `{name_part}` not found, skipping.")
                continue
            items_to_add.append((item["id"], item["name"], qty))

        if not items_to_add:
            return await ctx.send("No valid items specified.")

        count = 0
        for member in role.members:
            if member.bot:
                continue
            for item_id, _, qty in items_to_add:
                add_inventory_item(ctx.guild.id, member.id, item_id, qty)
            count += 1

        summary = ", ".join(f"{qty}× {name}" for _, name, qty in items_to_add)
        await ctx.send(f"Added {summary} to **{count}** members with {role.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
