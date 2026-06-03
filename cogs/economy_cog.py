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
    add_inventory_item_channel,
    add_shop_item,
    get_economy_account,
    get_economy_channel_balance,
    get_inventory_channel,
    get_shop_item_by_name,
    get_shop_items,
    get_top_economy_channels,
    remove_shop_item_by_name,
    transfer_channel_balance,
    transfer_economy_balance,
    update_economy_balance,
    update_economy_channel_balance,
    update_shop_item_by_name,
)
from utils.embeds import info_embed, success_embed, plain_embed


DEFAULT_SHOP_ITEMS = [
    {"name": "🎆 Fireworks", "description": "Reveal your current position in Announcements", "price": 100},
    {"name": "👟 Shoes", "description": "Gives you an additional visit", "price": 250},
    {"name": "✉ Whisper", "description": "Send a private message to someone", "price": 200},
    {"name": "🧹 Broom", "description": "Clears messages in a house channel", "price": 300},
    {"name": "📜 Will", "description": "Notify Overseers to pin your last will", "price": 150},
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
# Inventory use components
# ─────────────────────────────────────────────

class InventoryUseSelect(Select):
    """Dropdown to select an item from the inventory."""

    def __init__(self, items: list[dict]):
        options = []
        for item in items:
            label = f"{item['name']} × {item['quantity']}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    description=(item.get("description") or "")[:100],
                    value=str(item["item_id"]),
                )
            )
        super().__init__(placeholder="Select an item...", options=options, min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user != self.view.invoker:
            return await interaction.response.send_message("Not your inventory.", ephemeral=True)
        self.view.selected_item_id = int(self.values[0])
        await interaction.response.send_message("Item selected. Use **Use** or **Sell** below.", ephemeral=True)


class InventoryView(View):
    """Dropdown + buttons to use or sell items from inventory."""

    def __init__(self, items: list[dict], invoker: discord.Member, channel_id: int, cog):
        super().__init__(timeout=120)
        self.items = items
        self.invoker = invoker
        self.channel_id = channel_id
        self.cog = cog
        self.selected_item_id: int | None = None
        self.add_item(InventoryUseSelect(items))

    def _get_owned(self, interaction: discord.Interaction, item_id: int) -> dict | None:
        current = get_inventory_channel(interaction.guild_id, self.channel_id)
        return next((i for i in current if i["item_id"] == item_id and i["quantity"] > 0), None)

    async def _do_use(self, interaction: discord.Interaction) -> None:
        owned = self._get_owned(interaction, self.selected_item_id)
        if not owned:
            await interaction.response.send_message("Item no longer available. Refresh with `.inv`.", ephemeral=True)
            return

        name_lower = owned["name"].lower()

        if "firework" in name_lower:
            ok = await self._do_fireworks(interaction)
        elif "whisper" in name_lower:
            ok = await self._do_whisper(interaction)
        elif "broom" in name_lower:
            ok = await self._do_broom(interaction)
        elif "shoe" in name_lower:
            ok = await self._do_extra_visit(interaction)
        elif "will" in name_lower:
            ok = await self._do_will(interaction)
        else:
            ok = True
            await interaction.response.send_message(f"Used **{owned['name']}**.", ephemeral=True)

        if ok:
            add_inventory_item_channel(interaction.guild_id, self.channel_id, owned["item_id"], -1)

    async def _do_sell(self, interaction: discord.Interaction) -> None:
        owned = self._get_owned(interaction, self.selected_item_id)
        if not owned:
            await interaction.response.send_message("Item no longer available. Refresh with `.inv`.", ephemeral=True)
            return

        item = get_shop_item_by_name(interaction.guild_id, owned["name"])
        if not item:
            await interaction.response.send_message("Could not determine shop price for that item.", ephemeral=True)
            return

        refund = item["price"] // 2
        add_inventory_item_channel(interaction.guild_id, self.channel_id, owned["item_id"], -1)
        update_economy_channel_balance(interaction.guild_id, self.channel_id, refund)
        await interaction.response.send_message(
            f"Sold **{owned['name']}** for **{refund:,}** coins (50% refund).", ephemeral=True
        )

    @discord.ui.button(label="✅ Use", style=discord.ButtonStyle.success, row=1)
    async def btn_use(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your inventory.", ephemeral=True)
        if self.selected_item_id is None:
            return await interaction.response.send_message("Select an item from the dropdown first.", ephemeral=True)
        await self._do_use(interaction)

    @discord.ui.button(label="💰 Sell (50%)", style=discord.ButtonStyle.secondary, row=1)
    async def btn_sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your inventory.", ephemeral=True)
        if self.selected_item_id is None:
            return await interaction.response.send_message("Select an item from the dropdown first.", ephemeral=True)
        await self._do_sell(interaction)

    async def _do_fireworks(self, interaction: discord.Interaction) -> bool:
        guild_data = load_guild_data(interaction.guild_id)
        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("sponsor_role_name"))
        ann_ch = discord.utils.get(interaction.guild.channels, name=guild_data.get("announcements_channel_name"))
        if not ann_ch:
            await interaction.response.send_message("Announcements channel not set up.", ephemeral=True)
            return False

        user = interaction.user
        if not (alive_role in user.roles or sponsor_role in user.roles):
            await interaction.response.send_message("You need the Alive or Sponsor role to use fireworks.", ephemeral=True)
            return False

        gifs = [
            "https://tenor.com/view/lanterns-flying-lantern-chinese-lantern-gif-9054613",
            "https://tenor.com/view/lanterns-lights-peace-gif-15906930",
            "https://tenor.com/view/tangled-tangled-movie-lanterns-tangled-lanterns-i-see-the-light-gif-12379369862241479266",
        ]
        gif = random.choice(gifs)
        house, err = self.cog._resolve_fireworks_house(interaction.guild, user, guild_data)
        if not house:
            await interaction.response.send_message(err, ephemeral=True)
            return False
        await ann_ch.send(
            f"{alive_role.mention}{sponsor_role.mention}\n{user.mention} is in {house.name}"
        )
        await ann_ch.send(gif)
        await interaction.response.send_message("🎆 Fireworks launched!", ephemeral=True)
        return True

    async def _do_whisper(self, interaction: discord.Interaction) -> bool:
        guild_data = load_guild_data(interaction.guild_id)
        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("alive_role_name"))
        if not alive_role:
            await interaction.response.send_message("Alive role not configured.", ephemeral=True)
            return False

        await interaction.response.defer()

        members = [m for m in interaction.guild.members if alive_role in m.roles]
        members.sort(key=lambda m: m.display_name.lower())
        if not members:
            await interaction.followup.send("No alive players to whisper to.", ephemeral=True)
            return False

        done = asyncio.Event()
        delivered = False
        view = View()

        for chunk_start in range(0, len(members), 25):
            chunk = members[chunk_start:chunk_start + 25]
            page = chunk_start // 25 + 1
            total_pages = (len(members) + 24) // 25
            options = [
                discord.SelectOption(label=m.display_name[:95], value=str(m.id))
                for m in chunk
            ]
            select = discord.ui.Select(
                placeholder=f"Select recipient... ({page}/{total_pages})",
                min_values=1,
                max_values=1,
                options=options,
            )

            async def on_select(wi: discord.Interaction, sel=select):
                nonlocal delivered
                try:
                    if wi.user != interaction.user:
                        return await wi.response.send_message("Not your menu.", ephemeral=True)

                    for child in view.children:
                        child.disabled = True
                    await wi.message.edit(view=view)

                    target_id = int(sel.values[0])
                    target = wi.guild.get_member(target_id)
                    if not target:
                        await wi.response.send_message("User not found.", ephemeral=True)
                        done.set()
                        return
                    await wi.response.defer()

                    prompt = await interaction.channel.send(
                        embed=plain_embed(title="✉ Whisper", description=f"Reply to this message with your whisper to {target.mention}."),
                    )

                    def reply_check(m):
                        return m.author == interaction.user and m.channel == interaction.channel and m.reference and m.reference.message_id == prompt.id

                    try:
                        reply = await interaction.client.wait_for("message", check=reply_check, timeout=300)
                    except asyncio.TimeoutError:
                        await interaction.channel.send("Whisper cancelled (timeout).")
                        return

                    rc_cat = discord.utils.get(interaction.guild.categories, name=guild_data.get("rc_category_name"))
                    if not rc_cat:
                        await interaction.channel.send("RoleChats category not configured.")
                        return
                    log_ch = discord.utils.get(interaction.guild.channels, name=guild_data.get("whisper_logs_channel_name"))
                    for ch in rc_cat.text_channels:
                        if target in ch.members:
                            embed = info_embed()
                            if guild_data.get("showwhispersender"):
                                embed.add_field(name=f"{interaction.user.mention} sent you a whisper:", value=reply.content, inline=False)
                            else:
                                embed.add_field(name="Someone sent you a whisper:", value=reply.content, inline=False)
                            await ch.send(f"{target.mention}", embed=embed)
                            if log_ch:
                                log_embed = info_embed()
                                log_embed.add_field(name=f"{interaction.user.mention} → {target.mention}:", value=reply.content, inline=False)
                                await log_ch.send(embed=log_embed)
                            delivered = True
                            break
                    if delivered:
                        await interaction.channel.send("✉ Whisper sent.")
                except Exception as e:
                    if not delivered:
                        await interaction.channel.send(f"An error occurred: {e}")
                finally:
                    done.set()

            select.callback = on_select
            view.add_item(select)

        await interaction.followup.send(
            embed=plain_embed(title="✉ Whisper", description="Select the recipient from the dropdowns below."),
            view=view,
            ephemeral=True,
        )
        await done.wait()
        return delivered

    async def _do_broom(self, interaction: discord.Interaction) -> bool:
        try:
            deleted = await interaction.channel.purge(limit=5, bulk=True)
            await interaction.response.send_message(f"🧹 Broom swept away **{len(deleted)}** messages.", ephemeral=True)
            return True
        except discord.Forbidden:
            await interaction.response.send_message("I need Manage Messages permission to use the broom here.", ephemeral=True)
            return False

    async def _do_extra_visit(self, interaction: discord.Interaction) -> bool:
        guild_data = load_guild_data(interaction.guild_id)
        rc_cat = discord.utils.get(interaction.guild.categories, name=guild_data.get("rc_category_name"))
        alt_cat = discord.utils.get(interaction.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(interaction.guild.categories, name=guild_data.get("dead_rc_category_name"))
        sent = False
        for cat in (rc_cat, alt_cat, dead_rc):
            if not cat:
                continue
            for ch in cat.text_channels:
                if interaction.user in ch.members and ch.permissions_for(interaction.user).send_messages:
                    await ch.send(f"🚪 **{interaction.user.display_name}** used an extra visit!")
                    sent = True
                    break
            if sent:
                break
        if not sent:
            await interaction.response.send_message("Could not find a rolechat to announce the visit.", ephemeral=True)
        else:
            await interaction.response.send_message("🚪 Extra visit used!", ephemeral=True)
        return sent

    async def _do_will(self, interaction: discord.Interaction) -> bool:
        guild_data = load_guild_data(interaction.guild_id)
        overseer_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
        if not overseer_role:
            await interaction.response.send_message("Overseer role not found.", ephemeral=True)
            return False
        await interaction.response.send_message(
            f"{overseer_role.mention} **{interaction.user.display_name}** has used a Will. "
            f"Please check their will message and pin it.\n"
            f"Will message (reply below):"
        )
        prompt_msg = await interaction.original_response()
        try:
            def check(m):
                return m.author == interaction.user and m.channel == interaction.channel and m.reference and m.reference.message_id == prompt_msg.id
            reply = await interaction.client.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError:
            await interaction.channel.send("Will cancelled (timeout).")
            return False
        await interaction.channel.send(f"{overseer_role.mention} {reply.jump_url} — please pin this will.")
        return True


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


class LeaderboardView(View):
    """Paginated leaderboard with prev/next buttons."""

    def __init__(self, pages: list[str], total: int, invoker: discord.Member):
        super().__init__(timeout=120)
        self.pages = pages
        self.total = total
        self.invoker = invoker
        self.page_index = 0
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.btn_prev.disabled = self.page_index == 0
        self.btn_next.disabled = self.page_index == len(self.pages) - 1

    def _embed(self) -> discord.Embed:
        embed = plain_embed(
            title=f"🏆 Leaderboard — {self.total} RoleChats (Roles)",
            description=self.pages[self.page_index],
        )
        embed.set_footer(text=f"Page {self.page_index + 1}/{len(self.pages)}")
        return embed

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if self.page_index > 0:
            self.page_index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if self.page_index < len(self.pages) - 1:
            self.page_index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)


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

    def _resolve_fireworks_house(self, guild, user, guild_data) -> tuple[discord.TextChannel | None, str]:
        houses_cat = discord.utils.get(guild.categories, name=guild_data.get("houses_category_name"))
        if not houses_cat:
            return None, "Houses category not set up."

        matches = [ch for ch in houses_cat.text_channels if ch.permissions_for(user).send_messages]
        if len(matches) == 1:
            return matches[0], ""

        sponsor_role = discord.utils.get(guild.roles, name=guild_data.get("sponsor_role_name"))
        alive_role = discord.utils.get(guild.roles, name=guild_data.get("alive_role_name"))
        if sponsor_role in user.roles and not matches:
            rc_cat = discord.utils.get(guild.categories, name=guild_data.get("rc_category_name"))
            if rc_cat:
                sponsor_rc = next((ch for ch in rc_cat.text_channels if ch.permissions_for(user).send_messages), None)
                if sponsor_rc:
                    for m in sponsor_rc.members:
                        if alive_role in m.roles and m != user:
                            player_matches = [ch for ch in houses_cat.text_channels if ch.permissions_for(m).send_messages]
                            if len(player_matches) == 1:
                                return player_matches[0], ""

        return None, "Cannot determine unique house location. Fireworks aborted."

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
            return await ctx.send("Quantity must be at least 1. Usage: `.buy <item_name> [quantity]`.")

        item = get_shop_item_by_name(ctx.guild.id, item_name)
        if not item:
            return await ctx.send("Item not found. Use a part of the name (e.g. `.buy fumo`).")

        cost = item["price"] * quantity
        bal = get_economy_channel_balance(ctx.guild.id, ctx.channel.id)
        if cost > bal:
            return await ctx.send(f"You don't have enough coins. You need **{cost:,}**, have **{bal:,}**.")

        update_economy_channel_balance(ctx.guild.id, ctx.channel.id, -cost)
        new_qty = add_inventory_item_channel(ctx.guild.id, ctx.channel.id, item["id"], quantity)

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
        view = InventoryView(items, ctx.author, target.id, self)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="give")
    async def give(self, ctx: commands.Context, member: discord.Member, amount: str):
        """Give coins to a member. Use `.give @user <amount>` or `.give @user all`. Must be in a house channel."""
        guild_data = load_guild_data(ctx.guild.id)

        if not _is_houses_category(ctx, guild_data=guild_data):
            return await ctx.send("Use `.give` in a channel inside the Houses category. Usage: `.give @user <amount>` or `.give @user all`.")
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

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
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

        if amount.lower() == "all":
            amount = get_economy_channel_balance(ctx.guild.id, sender_rc.id)
        else:
            try:
                amount = int(amount)
            except ValueError:
                return await ctx.send("Amount must be a number or `all`. Usage: `.give @user <amount>` or `.give @user all`.")
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0. Usage: `.give @user <amount>` or `.give @user all`.")

        if not transfer_channel_balance(ctx.guild.id, sender_rc.id, target_rc.id, amount):
            bal = get_economy_channel_balance(ctx.guild.id, sender_rc.id)
            return await ctx.send(f"Insufficient coins. Balance: **{bal:,}**.")

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
            return await ctx.send("Price must be greater than 0. Usage: `.additem <price> <name>`.")
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
            return await ctx.send("Amount must be greater than 0. Usage: `.addmoney #channel <amount>`.")
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, channel, guild_data):
            return await ctx.send("Channel must be in the RoleChats category. Usage: `.addmoney #channel <amount>`.")
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
            return await ctx.send("Amount must be greater than 0. Usage: `.removemoney #channel <amount>`.")
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, channel, guild_data):
            return await ctx.send("Channel must be in the RoleChats category. Usage: `.removemoney #channel <amount>`.")
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

    # ------------------------------------------------------------------ #
    # User-based economy (ebeblieve-style)
    # ------------------------------------------------------------------ #

    @commands.command(name="give-money", aliases=["give_money"])
    async def give_money(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Transfer coins from your wallet to another user."""
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0. Usage: `.give-money @user <amount>`.")
        if member.bot:
            return await ctx.send("You can't give coins to a bot.")
        if member == ctx.author:
            return await ctx.send("You can't give coins to yourself.")

        if not transfer_economy_balance(ctx.guild.id, ctx.author.id, member.id, amount):
            wallet, _ = get_economy_account(ctx.guild.id, ctx.author.id)
            return await ctx.send(f"Insufficient coins. Wallet: **{wallet:,}**.")

        await ctx.send(f"You gave **{amount:,}** coins to {member.mention}.")

    @commands.command(name="sell-item", aliases=["sell_item", "sell"])
    async def sell_item(self, ctx: commands.Context, *, item_name: str):
        """Sell an item from your rolechat's inventory back to the shop (50% refund)."""
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, guild_data=guild_data):
            return await ctx.send("Sell items only in a RoleChat channel. Usage: `.sell <item_name>`.")

        item = get_shop_item_by_name(ctx.guild.id, item_name)
        if not item:
            return await ctx.send("Item not found. Usage: `.sell <item_name>`.")

        inv = get_inventory_channel(ctx.guild.id, ctx.channel.id)
        owned = next((i for i in inv if i["item_id"] == item["id"] and i["quantity"] > 0), None)
        if not owned:
            return await ctx.send("You don't own that item.")

        refund = item["price"] // 2
        add_inventory_item_channel(ctx.guild.id, ctx.channel.id, item["id"], -1)
        update_economy_channel_balance(ctx.guild.id, ctx.channel.id, refund)

        await ctx.send(
            f"Sold **{item['name']}** for **{refund:,}** coins (50% of shop price)."
        )

    @commands.command(name="add-money-role", aliases=["add_money_role", "addmrole"])
    @commands.has_permissions(administrator=True)
    async def add_money_role(self, ctx: commands.Context, role: discord.Role, amount: int):
        """Add money to rolechats of all members with a specific role."""
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0. Usage: `.addmrole @role <amount>`.")
        if amount > 10_000:
            return await ctx.send("Amount cannot exceed **10,000** per user.")

        guild_data = load_guild_data(ctx.guild.id)
        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        cats = [c for c in (rc_cat, alt_cat, dead_rc) if c]

        def _find_rc(target: discord.Member) -> discord.TextChannel | None:
            for cat in cats:
                for c in cat.text_channels:
                    if c.permissions_for(target).send_messages:
                        return c
            return None

        count = 0
        for member in role.members:
            if member.bot:
                continue
            rc = _find_rc(member)
            if rc:
                update_economy_channel_balance(ctx.guild.id, rc.id, amount)
                count += 1

        await ctx.send(f"Added **{amount:,}** to **{count}** rolechats of members with {role.mention}.")

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    @commands.has_permissions(administrator=True)
    async def leaderboard(self, ctx: commands.Context):
        """Show all rolechats ranked by balance (Roles category only), paginated."""
        guild_data = load_guild_data(ctx.guild.id)
        roles_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name", "ROLES"))
        if not roles_cat:
            return await ctx.send("Roles category not found.")

        entries = get_top_economy_channels(ctx.guild.id, 1000)

        clean = []
        deleted_ids = []
        for entry in entries:
            ch = ctx.guild.get_channel(entry["channel_id"])
            if ch:
                if ch.category_id == roles_cat.id:
                    clean.append((ch, entry["balance"]))
            else:
                deleted_ids.append(entry["channel_id"])

        for cid in deleted_ids:
            update_economy_channel_balance(ctx.guild.id, cid, 0)

        if not clean:
            return await ctx.send("No active rolechats with economy data.")

        per_page = 10
        pages = []
        for i in range(0, len(clean), per_page):
            chunk = clean[i:i + per_page]
            lines = []
            for rank, (ch, bal) in enumerate(chunk, start=i + 1):
                lines.append(f"**#{rank}.** {ch.mention} — **{bal:,}**")
            pages.append("\n".join(lines))

        view = LeaderboardView(pages, len(clean), ctx.author)
        embed = view._embed()
        await ctx.send(embed=embed, view=view)

    # ------------------------------------------------------------------ #
    # Item usage & admin distribution
    # ------------------------------------------------------------------ #

    @commands.command(name="use")
    async def use_item(self, ctx: commands.Context, *, item_name: str):
        """Use an item from your rolechat's inventory."""
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, guild_data=guild_data):
            return await ctx.send("Use items only in a RoleChat channel. Usage: `.use <item_name>`.")

        item = get_shop_item_by_name(ctx.guild.id, item_name)
        if not item:
            return await ctx.send("Item not found. Usage: `.use <item_name>`.")

        inv = get_inventory_channel(ctx.guild.id, ctx.channel.id)
        owned = next((i for i in inv if i["item_id"] == item["id"] and i["quantity"] > 0), None)
        if not owned:
            return await ctx.send("You don't have that item. Buy it first with `.buy` or get it from an Overseer.")

        name_lower = item["name"].lower()
        ok = False

        if "firework" in name_lower:
            ok = await self._trigger_fireworks(ctx)
        elif "whisper" in name_lower:
            ok = await self._trigger_whisper(ctx)
        elif "broom" in name_lower:
            ok = await self._trigger_broom(ctx)
        elif "shoe" in name_lower:
            ok = await self._trigger_extra_visit(ctx)
        elif "will" in name_lower:
            ok = await self._trigger_will(ctx)
        else:
            await ctx.send(f"Used **{item['name']}**.")
            ok = True

        if ok:
            add_inventory_item_channel(ctx.guild.id, ctx.channel.id, item["id"], -1)

    async def _trigger_fireworks(self, ctx: commands.Context) -> bool:
        """Reveal the caller's position in announcements."""
        guild_data = load_guild_data(ctx.guild.id)
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))
        ann_ch = discord.utils.get(ctx.guild.channels, name=guild_data.get("announcements_channel_name"))
        if not ann_ch:
            await ctx.send("Announcements channel not set up.")
            return False

        user = ctx.author
        if not (alive_role in user.roles or sponsor_role in user.roles):
            await ctx.send("You need the Alive or Sponsor role to use fireworks.")
            return False

        gifs = [
            "https://tenor.com/view/lanterns-flying-lantern-chinese-lantern-gif-9054613",
            "https://tenor.com/view/lanterns-lights-peace-gif-15906930",
            "https://tenor.com/view/tangled-tangled-movie-lanterns-tangled-lanterns-i-see-the-light-gif-12379369862241479266",
        ]
        gif = random.choice(gifs)
        house, err = self._resolve_fireworks_house(ctx.guild, user, guild_data)
        if not house:
            await ctx.send(err)
            return False
        await ann_ch.send(
            f"{alive_role.mention}{sponsor_role.mention}\n{user.mention} is in {house.name}"
        )
        await ann_ch.send(gif)
        await ctx.send("🎆 Fireworks launched!")
        return True

    async def _trigger_whisper(self, ctx: commands.Context) -> bool:
        """Start the whisper target selection UI."""
        guild_data = load_guild_data(ctx.guild.id)
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        if not alive_role:
            await ctx.send("Alive role not configured.")
            return False

        members = [m for m in ctx.guild.members if alive_role in m.roles]
        members.sort(key=lambda m: m.display_name.lower())
        if not members:
            await ctx.send("No alive players to whisper to.")
            return False

        done = asyncio.Event()
        delivered = False
        view = View(timeout=300)

        for chunk_start in range(0, len(members), 25):
            chunk = members[chunk_start:chunk_start + 25]
            page = chunk_start // 25 + 1
            total_pages = (len(members) + 24) // 25
            options = [
                discord.SelectOption(label=m.display_name[:95], value=str(m.id))
                for m in chunk
            ]
            select = discord.ui.Select(
                placeholder=f"Select recipient... ({page}/{total_pages})",
                min_values=1,
                max_values=1,
                options=options,
            )

            async def on_select(interaction: discord.Interaction, sel=select):
                nonlocal delivered
                try:
                    if interaction.user != ctx.author:
                        return await interaction.response.send_message("Not your menu.", ephemeral=True)

                    for child in view.children:
                        child.disabled = True
                    await interaction.message.edit(view=view)

                    target_id = int(sel.values[0])
                    target = ctx.guild.get_member(target_id)
                    if not target:
                        await interaction.response.send_message("User not found.", ephemeral=True)
                        done.set()
                        return
                    await interaction.response.defer()

                    prompt = await ctx.send(
                        embed=plain_embed(title="✉ Whisper", description=f"Reply to this message with your whisper to {target.mention}."),
                    )

                    def reply_check(m):
                        return m.author == ctx.author and m.channel == ctx.channel and m.reference and m.reference.message_id == prompt.id

                    try:
                        reply = await ctx.bot.wait_for("message", check=reply_check, timeout=300)
                    except asyncio.TimeoutError:
                        await ctx.send("Whisper cancelled (timeout).")
                        return

                    rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
                    if not rc_cat:
                        await ctx.send("RoleChats category not configured.")
                        return
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
                            delivered = True
                            break
                    if delivered:
                        await ctx.send("✉ Whisper sent.")
                finally:
                    done.set()

            select.callback = on_select
            view.add_item(select)

        embed = info_embed(title="Who do you want to whisper?", description="Select a recipient from the dropdowns below.")
        await ctx.send(embed=embed, view=view)

        try:
            await asyncio.wait_for(done.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass
        return delivered

    async def _trigger_broom(self, ctx: commands.Context) -> bool:
        """Clears messages in the current channel (last 5 messages)."""
        try:
            deleted = await ctx.channel.purge(limit=5, bulk=True)
            await ctx.send(f"🧹 Broom swept away **{len(deleted)}** messages.", delete_after=5)
            return True
        except discord.Forbidden:
            await ctx.send("I need Manage Messages permission to use the broom here.")
            return False

    async def _trigger_extra_visit(self, ctx: commands.Context) -> bool:
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
        return sent

    async def _trigger_will(self, ctx: commands.Context) -> bool:
        """Notify Overseers to pin the user's last will."""
        guild_data = load_guild_data(ctx.guild.id)
        overseer_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
        if not overseer_role:
            await ctx.send("Overseer role not found.")
            return False
        msg = await ctx.send(
            f"{overseer_role.mention} **{ctx.author.display_name}** has used a Will. "
            f"Please check their will message and pin it.\n"
            f"Will message (reply below):"
        )
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel and m.reference and m.reference.message_id == msg.id
            reply = await ctx.bot.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError:
            await ctx.send("Will cancelled (timeout).")
            return False
        await ctx.send(f"{overseer_role.mention} {reply.jump_url} — please pin this will.")
        return True

    @commands.command(name="additemrole")
    @commands.has_permissions(administrator=True)
    async def additemrole(self, ctx: commands.Context, role: discord.Role, *, items_str: str):
        """Add items to rolechats of all members with a role. Format: .additemrole @Alive broom 3, fireworks 1"""
        guild_data = load_guild_data(ctx.guild.id)
        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        cats = [c for c in (rc_cat, alt_cat, dead_rc) if c]

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

        def _find_rc(target: discord.Member) -> discord.TextChannel | None:
            for cat in cats:
                for c in cat.text_channels:
                    if c.permissions_for(target).send_messages:
                        return c
            return None

        count = 0
        for member in role.members:
            if member.bot:
                continue
            rc = _find_rc(member)
            if not rc:
                continue
            for item_id, _, qty in items_to_add:
                add_inventory_item_channel(ctx.guild.id, rc.id, item_id, qty)
            count += 1

        summary = ", ".join(f"{qty}× {name}" for _, name, qty in items_to_add)
        await ctx.send(f"Added {summary} to **{count}** rolechats of members with {role.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
