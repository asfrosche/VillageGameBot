import asyncio
import random
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord.ui import Modal, Select, View, Button

from cogs.data_utils import (
    load_guild_data,
    save_guild_data,
)
from utils.economy_db import (
    add_inventory_item_channel,
    add_shop_item,
    buy_shop_item,
    clear_channel_inventory,
    get_economy_channel_balance,
    get_inventory_channel,
    get_removed_default_items,
    get_shop_item_by_id,
    get_shop_item_by_name,
    get_shop_items,
    get_top_economy_channels,
    remove_shop_item_by_name,
    search_inventory_items,
    search_shop_items,
    set_economy_channel_balance,
    transfer_channel_balance,
    update_economy_channel_balance,
    update_shop_item_by_name,
)
from utils.embeds import info_embed, success_embed, plain_embed
from cogs.handling_cog import get_pc_category, role_pings
from utils.private_pc import create_private_pc, sponsor_members


DEFAULT_SHOP_ITEMS = [
    {"name": "🎆 Fireworks", "description": "Reveal your current position in Announcements", "price": 100},
    {"name": "👟 Shoes", "description": "Gives you an additional visit", "price": 250},
    {"name": "✉ Whisper", "description": "Send a private message to someone", "price": 200},
    {"name": "🧹 Broom", "description": "Clears messages in a house channel", "price": 300},
    {"name": "📜 Will", "description": "Notify Overseers to pin your last will", "price": 150},
    {"name": "🔭 Peep Hole", "description": "See who knocks on this house for 24h", "price": 150},
    {"name": "🔒 Private PC", "description": "Open a private channel with an alive player and all sponsors", "price": 1500},
]

# Maximum value accepted by .setcollect to prevent accidental huge payouts.
MAX_COLLECT_AMOUNT = 10_000


def _split_trailing_qty(text: str) -> tuple[str, int]:
    """Split "item [qty]" text into (query, quantity). The last numeric token is the quantity."""
    parts = text.strip().split()
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].isdigit():
            qty = int(parts[i])
            if qty > 0:
                return " ".join(parts[:i]).strip(), qty
    return text.strip(), 1


def _stock_text(item: dict) -> str:
    """Short stock indicator: '' for unlimited (0), otherwise 'N left'."""
    stock = item.get("stock", 0) or 0
    return "" if stock <= 0 else f" · **{stock} left**"

# Matches an emoji at the start of an item name: custom Discord emoji
# (<:name:id> / <a:name:id>) or a unicode emoji glyph.
_ITEM_EMOJI_RE = re.compile(
    r"<a?:\w+:\d+>|[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\uFE0F\u200D]"
)


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
    return channel.category is not None and channel.category in (rc_cat, alt_cat, dead_rc)


def _player_rolechat_channels(guild, guild_data) -> list:
    """Text channels in the player rolechat categories (RoleChats and ALTs).

    Players who overflow into ALT rolechats are included, so whispers and house items reach them.
    """
    cats = [
        discord.utils.get(guild.categories, name=guild_data.get("rc_category_name")),
        discord.utils.get(guild.categories, name=guild_data.get("alt_category_name")),
    ]
    return [ch for cat in cats if cat is not None for ch in cat.text_channels]


def _players_rolechat(ctx, guild_data):
    """The rolechat the author can read and send in (used for house items), or an error string."""
    for channel in _player_rolechat_channels(ctx.guild, guild_data):
        if ctx.author in channel.members and channel.permissions_for(ctx.author).send_messages:
            return channel
    return "Could not find your rolechat to check inventory."


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
    return channel.category is not None and channel.category == houses


def _find_player_rolechat(
    guild: discord.Guild,
    member: discord.Member,
    guild_data: dict | None = None,
) -> discord.TextChannel | None:
    """Return the first rolechat the member can send in, or None."""
    if guild_data is None:
        guild_data = load_guild_data(guild.id)
    if not guild_data:
        return None
    rc_cat = discord.utils.get(guild.categories, name=guild_data.get("rc_category_name"))
    alt_cat = discord.utils.get(guild.categories, name=guild_data.get("alt_category_name"))
    dead_rc = discord.utils.get(guild.categories, name=guild_data.get("dead_rc_category_name"))
    for cat in (rc_cat, alt_cat, dead_rc):
        if not cat:
            continue
        for c in cat.text_channels:
            if c.permissions_for(member).send_messages:
                return c
    return None


async def _log_economy(
    guild: discord.Guild,
    guild_data: dict,
    *,
    action: str,
    actor: discord.Member,
    details: str,
) -> None:
    """Post a one-line audit embed to the economy log channel.

    The channel is identified by the ``economy_log_channel_name`` key in
    guild_data (falls back to ``logs-economy``). If the channel doesn't exist
    yet it is created under the OVERSEER category so logging works without a
    manual setup step.
    """
    log_channel_name = guild_data.get("economy_log_channel_name") or "logs-economy"
    if not log_channel_name:
        return
    log_ch = discord.utils.get(guild.text_channels, name=log_channel_name)
    if log_ch is None:
        overseer_cat = discord.utils.get(guild.categories, name=guild_data.get("overseer_category_name", "OVERSEER"))
        try:
            log_ch = await guild.create_text_channel(name=log_channel_name, category=overseer_cat)
        except discord.HTTPException:
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


def move_items_between_rcs(guild_id: int, sender_rc_id: int, target_rc_id: int, item: dict, quantity: int) -> tuple[bool, str]:
    """Move items from one rolechat inventory to another. Returns (ok, message).

    The sender is debited first. If the recipient's credit fails (the item was removed from the
    shop meanwhile), the sender is refunded, so no items are created or lost.
    """
    held = next((i for i in get_inventory_channel(guild_id, sender_rc_id) if i["item_id"] == item["id"]), None)
    have = held["quantity"] if held else 0
    if have < quantity:
        return False, f"You only have **{have}× {item['name']}** here."
    add_inventory_item_channel(guild_id, sender_rc_id, item["id"], -quantity)
    new_qty = add_inventory_item_channel(guild_id, target_rc_id, item["id"], quantity)
    if new_qty < quantity:
        add_inventory_item_channel(guild_id, sender_rc_id, item["id"], quantity)
        return False, f"**{item['name']}** is no longer available. Nothing was moved."
    return True, ""


SELLING_KEY = "shop_selling_enabled"


def selling_enabled(guild_id: int) -> bool:
    """Selling is on unless an admin has turned it off (the default is on)."""
    return bool((load_guild_data(guild_id) or {}).get(SELLING_KEY, True))


def set_selling_enabled(guild_id: int, enabled: bool) -> None:
    guild_data = load_guild_data(guild_id) or {}
    guild_data[SELLING_KEY] = bool(enabled)
    save_guild_data(guild_id, guild_data)


SELL_DISABLED_MESSAGE = "Selling is turned off on this server."


PRIVATE_PC_PAGE_SIZE = 25


def private_pc_targets(guild, guild_data, author):
    """Alive players the buyer can open a private PC with, or an error message string."""
    alive_role = discord.utils.get(guild.roles, name=guild_data.get("alive_role_name"))
    if not alive_role:
        return "Alive role not configured."
    members = [m for m in guild.members if alive_role in m.roles and not m.bot and m.id != author.id]
    if not members:
        return "No other alive players to open a private channel with."
    members.sort(key=lambda m: m.display_name.lower())
    return members


async def open_private_pc_with(guild, guild_data, initiator, target):
    """Create the private PC between *initiator* and *target* plus sponsors. Returns (ok, message)."""
    alive_role = discord.utils.get(guild.roles, name=guild_data.get("alive_role_name"))
    if alive_role is None or alive_role not in target.roles:
        return False, f"{target.display_name} is no longer an alive player."
    category = await get_pc_category(guild, guild_data, "private")
    if category is None:
        return False, "No private channel category exists. Check your setup."
    sponsor_role = discord.utils.get(guild.roles, name=guild_data.get("sponsor_role_name"))
    try:
        channel = await create_private_pc(guild, category, initiator, target, sponsor_role)
    except discord.HTTPException as error:
        return False, f"Could not open the private channel: {error}"
    return True, f"🔒 Private channel opened: {channel.mention}"


def private_pc_menu(invoker, targets, on_pick, result, done):
    """Player dropdowns, paginated like the whisper menu. Choosing a player runs on_pick."""
    view = View(timeout=300)
    total_pages = (len(targets) + PRIVATE_PC_PAGE_SIZE - 1) // PRIVATE_PC_PAGE_SIZE
    for start in range(0, len(targets), PRIVATE_PC_PAGE_SIZE):
        chunk = targets[start:start + PRIVATE_PC_PAGE_SIZE]
        page = start // PRIVATE_PC_PAGE_SIZE + 1
        select = discord.ui.Select(
            placeholder=f"Choose a player... ({page}/{total_pages})",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=m.display_name[:95], value=str(m.id)) for m in chunk],
        )

        async def on_select(interaction, sel=select):
            if interaction.user != invoker:
                return await interaction.response.send_message("Not your menu.", ephemeral=True)
            target = next((m for m in targets if str(m.id) == sel.values[0]), None)
            for child in view.children:
                child.disabled = True
            if target is None:
                ok, text = False, "That player is no longer available."
            else:
                ok, text = await on_pick(target)
            result["ok"] = ok
            try:
                await interaction.response.edit_message(content=text, embed=None, view=None)
            except discord.HTTPException:
                await interaction.followup.send(text, ephemeral=True)
            done.set()

        select.callback = on_select
        view.add_item(select)
    return view


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
        elif "private pc" in name_lower:
            ok = await self._do_private_pc(interaction)
        elif "broom" in name_lower or "peep" in name_lower:
            keyword = "broom" if "broom" in name_lower else "peep"
            await interaction.response.send_message(
                f"Use **{owned['name']}** from a House channel with `.use {keyword}`.", ephemeral=True
            )
            return
        elif "shoe" in name_lower:
            ok = await self._do_extra_visit(interaction)
        elif "will" in name_lower:
            ok = await self._do_will(interaction)
        else:
            ok = True
            await interaction.response.send_message(f"Used **{owned['name']}**.", ephemeral=True)

        if ok:
            add_inventory_item_channel(interaction.guild_id, self.channel_id, owned["item_id"], -1)
            await _log_economy(
                interaction.guild,
                load_guild_data(interaction.guild_id) or {},
                action="Item Used",
                actor=interaction.user,
                details=f"Used **{owned['name']}** in {interaction.channel.mention} (×1).",
            )

    async def _do_sell(self, interaction: discord.Interaction) -> None:
        if not selling_enabled(interaction.guild_id):
            return await interaction.response.send_message(SELL_DISABLED_MESSAGE, ephemeral=True)
        owned = self._get_owned(interaction, self.selected_item_id)
        if not owned:
            await interaction.response.send_message("Item no longer available. Refresh with `.inv`.", ephemeral=True)
            return

        item = get_shop_item_by_id(interaction.guild_id, owned["item_id"])
        if not item:
            await interaction.response.send_message("Could not determine shop price for that item.", ephemeral=True)
            return

        refund = item["price"] // 2
        add_inventory_item_channel(interaction.guild_id, self.channel_id, owned["item_id"], -1)
        update_economy_channel_balance(interaction.guild_id, self.channel_id, refund)
        await _log_economy(
            interaction.guild,
            load_guild_data(interaction.guild_id) or {},
            action="Item Sold",
            actor=interaction.user,
            details=f"Sold **{owned['name']}** for **{refund:,}** coins (50% refund) in {interaction.channel.mention}.",
        )
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
            f"{role_pings(alive_role, sponsor_role)}\n{user.mention} is in {house.name}"
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

            async def on_select(wi: discord.Interaction, sel=select):
                nonlocal delivered
                try:
                    if wi.user != interaction.user:
                        return await wi.response.send_message("Not your menu.", ephemeral=True)

                    target_id = int(sel.values[0])
                    target = wi.guild.get_member(target_id)
                    if not target:
                        await wi.response.send_message("User not found.", ephemeral=True)
                        done.set()
                        return

                    for child in view.children:
                        child.disabled = True
                    await wi.response.edit_message(view=view)

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

                    rolechats = _player_rolechat_channels(interaction.guild, guild_data)
                    if not rolechats:
                        await interaction.channel.send("RoleChats category not configured.")
                        return
                    log_ch = discord.utils.get(interaction.guild.channels, name=guild_data.get("whisper_logs_channel_name"))
                    for ch in rolechats:
                        if target in ch.members:
                            embed = info_embed()
                            content = reply.content[:1021] + "..." if len(reply.content) > 1024 else reply.content
                            if guild_data.get("showwhispersender"):
                                embed.add_field(name=f"{interaction.user.mention} sent you a whisper:", value=content, inline=False)
                            else:
                                embed.add_field(name="Someone sent you a whisper:", value=content, inline=False)
                            await ch.send(f"{target.mention}", embed=embed)
                            if log_ch:
                                log_embed = info_embed()
                                log_content = reply.content[:1021] + "..." if len(reply.content) > 1024 else reply.content
                                log_embed.add_field(name=f"{interaction.user.mention} → {target.mention}:", value=log_content, inline=False)
                                await log_ch.send(embed=log_embed)
                            delivered = True
                            break
                    if not delivered:
                        await interaction.channel.send(f"✉ Whisper not sent: {target.display_name} isn't in a RoleChat right now.")
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
        try:
            await asyncio.wait_for(done.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass
        return delivered

    async def _do_private_pc(self, interaction: discord.Interaction) -> bool:
        guild_data = load_guild_data(interaction.guild_id)
        targets = private_pc_targets(interaction.guild, guild_data, interaction.user)
        if isinstance(targets, str):
            await interaction.response.send_message(targets, ephemeral=True)
            return False
        await interaction.response.defer()

        result, done = {"ok": False}, asyncio.Event()

        async def on_pick(target):
            return await open_private_pc_with(interaction.guild, guild_data, interaction.user, target)

        view = private_pc_menu(interaction.user, targets, on_pick, result, done)
        await interaction.followup.send(
            embed=plain_embed(title="🔒 Private PC", description="Choose the player to open a private channel with. Every sponsor is added automatically."),
            view=view,
            ephemeral=True,
        )
        try:
            await asyncio.wait_for(done.wait(), timeout=300)
        except asyncio.TimeoutError:
            return False
        return result["ok"]

    async def _do_broom(self, interaction: discord.Interaction) -> bool:
        guild_data = load_guild_data(interaction.guild_id)
        houses_cat = discord.utils.get(interaction.guild.categories, name=guild_data.get("houses_category_name"))
        if interaction.channel.category != houses_cat:
            await interaction.response.send_message("🧹 Broom can only be used in a House channel.", ephemeral=True)
            return False
        try:
            await interaction.response.defer(ephemeral=True)
            prompt = await interaction.channel.send(
                embed=plain_embed(
                    title="🧹 Broom",
                    description=(
                        "**How to use:**\n"
                        "1. Find the message you want to start brooming **from**\n"
                        "2. **Right-click → Reply** to that message (not this one)\n"
                        "3. Type anything and send\n\n"
                        "I'll delete everything after that message (skipping pinned)."
                    ),
                ),
            )

            def reply_check(m):
                return (m.author == interaction.user
                        and m.channel == interaction.channel
                        and m.reference
                        and m.reference.message_id != prompt.id)

            try:
                reply = await interaction.client.wait_for("message", check=reply_check, timeout=120)
            except asyncio.TimeoutError:
                await interaction.channel.send("Broom cancelled (timeout).")
                return False

            anchor = reply.reference.resolved
            if not isinstance(anchor, discord.Message):
                try:
                    anchor = await interaction.channel.fetch_message(reply.reference.message_id)
                except (discord.NotFound, discord.HTTPException):
                    await interaction.channel.send("Could not resolve the target message.")
                    return False

            # The replied-to message is part of the sweep, unless it is pinned.
            to_delete = [] if anchor.pinned else [anchor]
            async for msg in interaction.channel.history(after=anchor, limit=None, oldest_first=True):
                if not msg.pinned:
                    to_delete.append(msg)

            if not to_delete:
                await interaction.channel.send("No unpinned messages to delete.")
                return False

            utility = interaction.client.get_cog("Utility")
            if not utility:
                await interaction.channel.send("Utility cog is not loaded. Cannot broom.")
                return False
            await utility.broom_delete(interaction, to_delete, individual_limit=None)
            return True
        except discord.Forbidden:
            await interaction.followup.send("I need Manage Messages permission to use the broom here.", ephemeral=True)
            return False

    async def _announce_extra_visit(self, channel, display_name: str) -> bool:
        """Announce the extra visit in the rolechat where it was used, pinned.

        Extra visits only make sense inside a rolechat, so the announcement is
        limited to the channel the item was used in — and only if that channel
        lives in a configured rolechat category. The previous scan posted to the
        first rolechat the user was a member of, which could be the wrong one.
        """
        if not isinstance(channel, discord.TextChannel):
            return False
        guild = getattr(channel, "guild", None)
        if guild is None:
            return False
        guild_data = load_guild_data(guild.id)
        rolechat_cats = {
            guild_data.get("rc_category_name"),
            guild_data.get("alt_category_name"),
            guild_data.get("dead_rc_category_name"),
        }
        if getattr(channel, "category", None) is None or channel.category.name not in rolechat_cats:
            return False
        try:
            msg = await channel.send(f"🚪 **{display_name}** used an extra visit!")
        except discord.HTTPException:
            return False
        try:
            await msg.pin()
        except (discord.Forbidden, discord.HTTPException):
            pass
        return True

    async def _do_extra_visit(self, interaction: discord.Interaction) -> bool:
        sent = await self._announce_extra_visit(interaction.channel, interaction.user.display_name)
        await interaction.response.send_message(
            "🚪 Extra visit used!" if sent else "Extra visits can only be used in a rolechat.",
            ephemeral=True,
        )
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

    async def _do_peephole(self, interaction: discord.Interaction) -> bool:
        guild_data = load_guild_data(interaction.guild_id)
        if not _is_houses_category(interaction, guild_data=guild_data):
            await interaction.response.send_message("🔭 Peep Hole can only be used in a House channel.", ephemeral=True)
            return False

        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("sponsor_role_name"))
        if not (alive_role in interaction.user.roles or sponsor_role in interaction.user.roles):
            await interaction.response.send_message("You need the Alive or Sponsor role to use the Peep Hole.", ephemeral=True)
            return False

        peep_holes = guild_data.get("peep_holes") or {}
        peep_holes[str(interaction.channel.id)] = datetime.now(timezone.utc).timestamp() + 86400
        guild_data["peep_holes"] = peep_holes
        save_guild_data(interaction.guild_id, guild_data)

        await interaction.response.send_message(f"🔭 Peep Hole activated in {interaction.channel.mention} for 24 hours.", ephemeral=True)
        return True


# ─────────────────────────────────────────────
# Shop components
# ─────────────────────────────────────────────

class ShopItemSelect(Select):
    """Dropdown listing items on the current page."""

    def __init__(self, items: list[dict], page_offset: int):
        options = []
        for i, item in enumerate(items, start=page_offset + 1):
            desc = f"{item['price']:,} coins"
            if (item.get("stock") or 0) > 0:
                desc += f" · {item['stock']} left"
            options.append(
                discord.SelectOption(
                    label=f"{i}. {item['name']}",
                    description=desc,
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
        update_shop_item_by_name(self.guild_id, self.item["name"], price=price, item_id=self.item["id"])
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
        state = "on" if selling_enabled(self.guild_id) else "off"
        embed.set_footer(
            text=f"Page {self.page_index + 1}/{len(self.pages)} • Select item, then Buy • Selling: {state}"
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
            self.btn_toggle_sell.label = "Selling: ON" if selling_enabled(self.guild_id) else "Selling: OFF"
            self.btn_toggle_sell.style = discord.ButtonStyle.success if selling_enabled(self.guild_id) else discord.ButtonStyle.danger
            self.add_item(self.btn_toggle_sell)
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

        ok, new_qty, reason = buy_shop_item(self.guild_id, self.channel_id, item["id"], item["price"], 1)
        if not ok:
            if reason == "stock":
                return await interaction.response.send_message(
                    "Not enough of that item in stock.", ephemeral=True
                )
            return await interaction.response.send_message(
                "Purchase failed. That item may have just been removed from the shop.", ephemeral=True
            )

        await interaction.response.send_message(
            f"Bought **{item['name']}** for **{item['price']:,}**. ×{new_qty}", ephemeral=True
        )
        await _log_economy(
            interaction.guild,
            load_guild_data(self.guild_id) or {},
            action="Purchase",
            actor=interaction.user,
            details=f"Bought **{item['name']}** for **{item['price']:,}** coins in {interaction.channel.mention}. ×{new_qty}",
        )

    @discord.ui.button(label="Selling: ON", emoji="💰", style=discord.ButtonStyle.success, row=3)
    async def btn_toggle_sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.invoker:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Admin only.", ephemeral=True)
        now_enabled = not selling_enabled(self.guild_id)
        set_selling_enabled(self.guild_id, now_enabled)
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)
        await _log_economy(
            interaction.guild,
            load_guild_data(self.guild_id) or {},
            action="Selling Toggled",
            actor=interaction.user,
            details=f"Selling is now **{'on' if now_enabled else 'off'}** (shop in {interaction.channel.mention}).",
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


class ConfirmView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.confirmed = False
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✔ Yes", style=discord.ButtonStyle.green)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(content=None, embed=None, view=None)

    @discord.ui.button(label="❌ No", style=discord.ButtonStyle.red)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", embed=None, view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="Confirmation timed out.", embed=None, view=None)
        except Exception:
            pass


class Economy(commands.Cog):
    """Rolechat-based economy: balance and inventory per rolechat."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _ensure_default_items(self, guild: discord.Guild) -> None:
        items = get_shop_items(guild.id)
        existing_names = {i["name"] for i in items}
        removed = get_removed_default_items(guild.id)
        for item in DEFAULT_SHOP_ITEMS:
            if item["name"] in existing_names or item["name"] in removed:
                continue
            add_shop_item(
                guild.id,
                name=item["name"],
                description=item["description"],
                price=item["price"],
                is_default=True,
            )

    async def _resolve_shop_item(self, ctx: commands.Context, query: str) -> dict | None:
        """Fuzzy-match a shop item by name (resolves ambiguity by asking the user)."""
        return await self._resolve_item(
            ctx,
            search_shop_items(ctx.guild.id, query),
            f"No shop item matches `{query}`.",
        )

    async def _resolve_inventory_item(self, ctx: commands.Context, channel_id: int, query: str) -> dict | None:
        """Fuzzy-match an item this inventory actually owns (resolves ambiguity by asking the user)."""
        return await self._resolve_item(
            ctx,
            search_inventory_items(ctx.guild.id, channel_id, query),
            f"You don't have any item matching `{query}` here.",
        )

    async def _resolve_item(self, ctx: commands.Context, candidates: list[dict], not_found: str) -> dict | None:
        """Shared resolution: an unambiguous winner is used directly, otherwise the user picks.

        Sends its own error/prompt messages and returns the chosen item dict,
        or None when nothing matched / was cancelled.
        """
        if not candidates:
            await ctx.send(not_found)
            return None
        pick = candidates[0]
        if len(candidates) > 1:
            top, second = candidates[0], candidates[1]
            # An exact match wins unless another item is also exact; near-misses need a clear gap.
            exact_win = top["score"] == 1.0 and second["score"] < 1.0
            unambiguous = exact_win or (top["score"] - second["score"]) >= 0.1
            if not unambiguous:
                pick = await self._ask_item_choice(ctx, candidates)
                if pick is None:
                    return None
        return pick

    async def _ask_item_choice(self, ctx: commands.Context, candidates: list[dict]) -> dict | None:
        """Send a numbered list of candidates and wait (30s) for the user's pick."""
        lines = []
        for i, it in enumerate(candidates, 1):
            line = f"**{i}.** {it['name']}"
            if it.get("price") is not None:
                line += f" — **{it['price']:,}** coins"
            stock_line = _stock_text(it)
            if stock_line:
                line += stock_line
            if it.get("quantity") and it["quantity"] > 0:
                line += f" · you own **{it['quantity']}**"
            if it.get("description"):
                line += f"\n> {it['description']}"
            lines.append(line)
        await ctx.send(
            "Multiple items matched. Reply with the **number** of the one you meant "
            "(or re-run with a clearer name):\n" + "\n".join(lines)
        )

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await ctx.bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("Timed out — cancelled.")
            return None

        content = msg.content.strip()
        if not content.isdigit():
            await ctx.send(f"`{content}` isn't a number — cancelled. Re-run with a clearer name.")
            return None
        idx = int(content)
        if not 1 <= idx <= len(candidates):
            await ctx.send(f"Number must be between **1** and **{len(candidates)}** — cancelled.")
            return None
        return candidates[idx - 1]

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
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Collect",
            actor=ctx.author,
            details=f"Added **{amount:,}** to **{count}** rolechat(s).",
        )

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

    @commands.command(name="sellshop")
    async def sellshop(self, ctx: commands.Context, state: str = None):
        """Admin: turn selling on or off for the whole server. Usage: .sellshop on|off"""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")
        if state is None:
            return await ctx.send(f"Selling is **{'on' if selling_enabled(ctx.guild.id) else 'off'}**. Use `.sellshop on` or `.sellshop off`.")
        value = state.strip().lower()
        if value not in ("on", "off"):
            return await ctx.send("Use `.sellshop on` or `.sellshop off`.")
        set_selling_enabled(ctx.guild.id, value == "on")
        await ctx.send(f"Selling is now **{value}**.")

    @commands.command(name="shop")
    async def shop(self, ctx: commands.Context):
        """View the server shop."""
        await self._ensure_default_items(ctx.guild)
        items = get_shop_items(ctx.guild.id)
        if not items:
            return await ctx.send("The shop is empty. Admins can add items with `.additem <name> <price> [description] [stock]`.")

        per_page = 10
        pages = []
        items_by_page = []
        for i in range(0, len(items), per_page):
            chunk = items[i: i + per_page]
            items_by_page.append(chunk)
            lines = []
            for idx, it in enumerate(chunk, start=i + 1):
                line = f"**{idx}.** **{it['name']}** — **{it['price']:,}**"
                stock_line = _stock_text(it)
                if stock_line:
                    line += stock_line
                if it.get("description"):
                    line += f"\n> {it['description']}"
                lines.append(line)
            pages.append("\n\n".join(lines))

        view = ShopView(pages, items_by_page, ctx.author, ctx.guild.id, ctx.channel.id)
        await ctx.send(embed=view._build_embed(), view=view)

    @commands.command(name="buy")
    async def buy(self, ctx: commands.Context, *, text: str):
        """Buy an item by name (fuzzy match). Only in rolechats. Usage: .buy <item> [qty]"""
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, guild_data=guild_data):
            return await ctx.send("Buy items only in a RoleChat channel.")
        query, quantity = _split_trailing_qty(text)
        if quantity <= 0:
            return await ctx.send("Quantity must be at least 1. Usage: `.buy <item> [quantity]`.")
        if not query:
            return await ctx.send("Usage: `.buy <item> [quantity]`.")

        item = await self._resolve_shop_item(ctx, query)
        if item is None:
            return

        if (item.get("stock") or 0) > 0 and quantity > item["stock"]:
            return await ctx.send(f"Only **{item['stock']}× {item['name']}** left in stock — you asked for **{quantity}**.")

        cost = item["price"] * quantity
        bal = get_economy_channel_balance(ctx.guild.id, ctx.channel.id)
        if cost > bal:
            return await ctx.send(f"You don't have enough coins. You need **{cost:,}**, have **{bal:,}**.")

        ok, new_qty, reason = buy_shop_item(ctx.guild.id, ctx.channel.id, item["id"], item["price"], quantity)
        if not ok:
            if reason == "stock":
                cur = next((i for i in get_shop_items(ctx.guild.id) if i["id"] == item["id"]), None)
                left = cur["stock"] if cur and cur["stock"] is not None else 0
                return await ctx.send(f"Not enough **{item['name']}** in stock — only **{left}** left.")
            if reason == "balance":
                return await ctx.send(f"You don't have enough coins. You need **{cost:,}**, have **{bal:,}**.")
            return await ctx.send("Item not found. Use a part of the name (e.g. `.buy fumo`).")

        embed = success_embed(
            title="✅ Purchase successful",
            description=(
                f"You bought **{quantity}× {item['name']}** for **{cost:,}** coins.\n"
                f"You now have **{new_qty}×** in this rolechat."
            ),
        )
        await ctx.send(embed=embed)
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Purchase",
            actor=ctx.author,
            details=f"Bought **{quantity}× {item['name']}** for **{cost:,}** coins in {ctx.channel.mention}. ×{new_qty}",
        )

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
    async def give(self, ctx: commands.Context, member: discord.Member, *, amount: str):
        """Give coins or items to a player in a house.

        `.give @user <amount>` or `.give @user all` gives coins.
        `.give @user <item> [qty]` or `.give @user <item> all` gives items from your inventory.
        """
        token = amount.strip().lower()
        if not (token == "all" or token.replace(",", "").isdigit()):
            return await self._give_items(ctx, member, amount)
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

    class GiveItemConfirmView(discord.ui.View):
        def __init__(self, ctx, recipient, item, quantity, sender_rc, target_rc):
            super().__init__(timeout=60)
            self.ctx = ctx
            self.recipient = recipient
            self.item = item
            self.quantity = quantity
            self.sender_rc = sender_rc
            self.target_rc = target_rc

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.ctx.author.id and interaction.user.id != self.recipient.id:
                await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.green)
        async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id == self.recipient.id:
                held = next(
                    (i for i in get_inventory_channel(self.ctx.guild.id, self.sender_rc.id) if i["item_id"] == self.item["id"]),
                    None,
                )
                if not held or held["quantity"] < self.quantity:
                    await interaction.response.edit_message(
                        content="❌ The sender no longer has enough of this item. Transfer cancelled.",
                        embed=None, view=None,
                    )
                    return self.stop()
                # No await between the check and the debit, so nothing else can spend the items in between.
                add_inventory_item_channel(self.ctx.guild.id, self.sender_rc.id, self.item["id"], -self.quantity)
                new_qty = add_inventory_item_channel(self.ctx.guild.id, self.target_rc.id, self.item["id"], self.quantity)
                if new_qty < self.quantity:
                    # The item was removed from the shop meanwhile; give the items back.
                    add_inventory_item_channel(self.ctx.guild.id, self.sender_rc.id, self.item["id"], self.quantity)
                    await interaction.response.edit_message(
                        content="❌ That item is no longer available. Transfer cancelled.",
                        embed=None, view=None,
                    )
                    return self.stop()
                await _log_economy(
                    self.ctx.guild,
                    load_guild_data(self.ctx.guild.id) or {},
                    action="Item Trade",
                    actor=self.ctx.author,
                    details=f"Gave **{self.quantity}× {self.item['name']}** to {self.recipient.mention} — #{self.sender_rc.name} → #{self.target_rc.name}.",
                )
                await interaction.response.edit_message(
                    content=f"✅ {self.recipient.mention} accepted! **{self.quantity}× {self.item['name']}** transferred.\n"
                            f"They now have **{new_qty}× {self.item['name']}** in #{self.target_rc.name}.",
                    embed=None, view=None,
                )
            else:
                return await interaction.response.send_message("Only the recipient can accept.", ephemeral=True)
            self.stop()

        @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red)
        async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id == self.ctx.author.id or interaction.user.id == self.recipient.id:
                await interaction.response.edit_message(
                    content="❌ Item transfer declined.",
                    embed=None, view=None,
                )
            else:
                await interaction.response.send_message("This isn't for you.", ephemeral=True)
            self.stop()

        async def on_timeout(self):
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(content="⏰ Transfer request timed out.", embed=None, view=None)
            except Exception:
                pass

    async def _give_items(self, ctx: commands.Context, member: discord.Member, text: str):
        """Give items to a player in this house, straight away."""
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_houses_category(ctx, guild_data=guild_data):
            return await ctx.send("Use `.give` in a house channel, with the player you are giving to in the same house.")
        if member.bot:
            return await ctx.send("You can't give items to a bot.")
        if member == ctx.author:
            return await ctx.send("You can't give items to yourself.")

        ch = ctx.channel
        if not (ch.permissions_for(ctx.author).read_messages and ch.permissions_for(ctx.author).send_messages):
            return await ctx.send("You need read and send permission in this house.")
        if not (ch.permissions_for(member).read_messages and ch.permissions_for(member).send_messages):
            return await ctx.send(f"{member.display_name} isn't in this house.")

        rc_cats = [discord.utils.get(ctx.guild.categories, name=guild_data.get(k)) for k in (
            "rc_category_name", "alt_category_name", "dead_rc_category_name")]

        def _find_rc(who: discord.Member):
            for cat in rc_cats:
                if not cat:
                    continue
                for c in cat.text_channels:
                    if c.permissions_for(who).send_messages:
                        return c
            return None

        sender_rc = _find_rc(ctx.author)
        target_rc = _find_rc(member)
        if not sender_rc:
            return await ctx.send("Could not find your rolechat.")
        if not target_rc:
            return await ctx.send(f"Could not find a rolechat for {member.display_name}.")
        if sender_rc == target_rc:
            return await ctx.send("You can't give items to someone in the same rolechat.")

        words = text.strip().split()
        give_all = len(words) > 1 and words[-1].lower() == "all"
        if give_all:
            query, quantity = " ".join(words[:-1]), None
        else:
            query, quantity = _split_trailing_qty(text)
            if quantity <= 0:
                return await ctx.send("Quantity must be greater than 0.")
        if not query:
            return await ctx.send("Usage: `.give @player <item> [quantity]` or `.give @player <item> all`.")

        item = await self._resolve_shop_item(ctx, query)
        if item is None:
            return

        if give_all:
            held = next((i for i in get_inventory_channel(ctx.guild.id, sender_rc.id) if i["item_id"] == item["id"]), None)
            quantity = held["quantity"] if held else 0
            if quantity <= 0:
                return await ctx.send(f"You don't have any **{item['name']}** here.")
        ok, message = move_items_between_rcs(ctx.guild.id, sender_rc.id, target_rc.id, item, quantity)
        if not ok:
            return await ctx.send(message)
        await ctx.send(f"🎁 {ctx.author.mention} gave **{quantity}× {item['name']}** to {member.mention}.")
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Item Gift",
            actor=ctx.author,
            details=f"{ctx.author.mention} gave **{quantity}× {item['name']}** to {member.mention} in {ctx.channel.mention}.",
        )

    @commands.command(name="trade")
    async def giveitem_player(self, ctx: commands.Context, member: discord.Member, *, text: str):
        """Give an item to another player. Usage: .trade @player <item> [qty]"""
        guild_data = load_guild_data(ctx.guild.id)

        if not _is_houses_category(ctx, guild_data=guild_data):
            return await ctx.send("Use `.trade` in a channel inside the Houses category.")
        if member.bot:
            return await ctx.send("You can't give items to a bot.")
        if member == ctx.author:
            return await ctx.send("You can't give items to yourself.")

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
            return await ctx.send("You can't give items to someone in the same rolechat.")

        query, quantity = _split_trailing_qty(text)
        if quantity <= 0:
            return await ctx.send("Quantity must be greater than 0.")
        if not query:
            return await ctx.send("Usage: `.trade @player <item> [quantity]`.")

        item = await self._resolve_shop_item(ctx, query)
        if item is None:
            return

        sender_inv = get_inventory_channel(ctx.guild.id, sender_rc.id)
        sender_item = next((i for i in sender_inv if i["item_id"] == item["id"]), None)
        if not sender_item or sender_item["quantity"] < quantity:
            owned = sender_item["quantity"] if sender_item else 0
            return await ctx.send(f"You only have **{owned}× {item['name']}** in #{sender_rc.name}.")

        view = self.GiveItemConfirmView(ctx, member, item, quantity, sender_rc, target_rc)
        msg = await ctx.send(
            f"{member.mention}, {ctx.author.mention} wants to give you **{quantity}× {item['name']}**.\n"
            f"Click ✅ Accept to receive or ❌ Decline to refuse.",
            view=view,
        )
        view.message = msg

    # ------------------------------------------------------------------ #
    # Admin commands
    # ------------------------------------------------------------------ #

    @commands.command(name="additem")
    @commands.has_permissions(administrator=True)
    async def additem(self, ctx: commands.Context, *, text: str):
        """Add a shop item. Usage: .additem <name> <price> [description] [stock].
        The name must start with an emoji. Avoid numbers in the name — the first
        number is read as the price. If a number is needed, wrap the name in
        quotes, e.g. .additem 🪵 "Axe 3" 500 Powerful axe. Trailing number = stock."""
        parts = text.strip().split()
        if not parts:
            return await ctx.send("Usage: `.additem <name> <price> [description] [stock]` — item name must start with an emoji.")

        price_pos = -1
        for i, part in enumerate(parts):
            try:
                int(part)
            except ValueError:
                continue
            price_pos = i
            break

        if price_pos <= 0:
            return await ctx.send(
                "Couldn't find a price. Usage: `.additem <name> <price> [description] [stock]` "
                "— e.g. `.additem 🪵 Log 1000000 Ominous looking log 50`. "
                "If your name contains a number, wrap it in quotes, e.g. `.additem 🪵 \"Axe 3\" 500 Powerful axe`."
            )

        price = int(parts[price_pos])
        if price <= 0:
            return await ctx.send("Price must be greater than 0. Usage: `.additem <name> <price> [description] [stock]`.")

        stock = 0
        remainder = parts[price_pos + 1:]
        if remainder and remainder[-1].isdigit():
            remainder, stock = remainder[:-1], int(remainder[-1])

        name = " ".join(t.strip("'\"") for t in parts[:price_pos]).strip()
        if not name:
            return await ctx.send("Item name cannot be empty.")
        if not _ITEM_EMOJI_RE.match(name):
            return await ctx.send(
                f"Item name must start with an emoji. Usage: `.additem <name> <price> [description] [stock]` — "
                f"e.g. `.additem 🪵 Log 1000000 Ominous looking log`."
            )

        description = " ".join(remainder).strip()
        add_shop_item(ctx.guild.id, name=name, description=description, price=price, is_default=False, stock=stock)
        stock_note = f"\nStock: **{stock}**" if stock > 0 else "\nStock: **unlimited**"
        embed = success_embed(title="🛒 Item added", description=f"**{name}** for **{price:,}** coins.{stock_note}")
        await ctx.send(embed=embed)

    @commands.command(name="updatestock")
    @commands.has_permissions(administrator=True)
    async def updatestock(self, ctx: commands.Context, *, text: str):
        """Set how many units of an item are in stock. 0 = unlimited. Usage: .updatestock <item> <stock>"""
        stock = None
        parts = text.strip().split()
        if parts and parts[-1].lstrip("-").isdigit():
            stock = int(parts[-1])
            query = " ".join(parts[:-1])
        else:
            query = text.strip()
        if stock is None:
            return await ctx.send("Usage: `.updatestock <item> <stock>` — e.g. `.updatestock Log 100` (0 = unlimited).")
        if stock < 0:
            return await ctx.send("Stock must be >= 0 (0 = unlimited).")

        item = await self._resolve_shop_item(ctx, query)
        if item is None:
            return

        ok = update_shop_item_by_name(ctx.guild.id, item["name"], stock=stock, item_id=item["id"])
        if not ok:
            return await ctx.send("Could not update that item's stock.")
        if stock == 0:
            await ctx.send(f"**{item['name']}** is now **unlimited** (no stock limit).")
        else:
            await ctx.send(f"**{item['name']}** stock → **{stock}**.")

    @commands.command(name="edititem")
    @commands.has_permissions(administrator=True)
    async def edititem(self, ctx: commands.Context, field: str, item_name: str, *, new_value: str):
        """Edit an item: .edititem price/name/description/stock <item_name> <new_value>"""
        field = field.lower()
        if field not in ("price", "name", "description", "stock"):
            return await ctx.send("Field must be price, name, description, or stock.")
        if field in ("price", "stock"):
            try:
                val = int(new_value.strip())
            except ValueError:
                return await ctx.send("Value must be a number.")
            if val < 0:
                return await ctx.send("Value must be >= 0 (stock 0 = unlimited).")

        item = await self._resolve_shop_item(ctx, item_name)
        if item is None:
            return

        if field == "price":
            ok = update_shop_item_by_name(ctx.guild.id, item["name"], price=val, item_id=item["id"])
            label = f"price → **{val:,}**"
        elif field == "stock":
            ok = update_shop_item_by_name(ctx.guild.id, item["name"], stock=val, item_id=item["id"])
            label = f"stock → **{val}** (0 = unlimited)" if val == 0 else f"stock → **{val}**"
        elif field == "name":
            new_name = new_value.strip()
            if not new_name:
                return await ctx.send("Item name cannot be empty.")
            if not _ITEM_EMOJI_RE.match(new_name):
                return await ctx.send("New item name must start with an emoji.")
            if update_shop_item_by_name(ctx.guild.id, item["name"], name=new_name, item_id=item["id"]):
                return await ctx.send(f"Updated **{item['name']}** — new name: **{new_name}**.")
            return await ctx.send("An item with that name already exists.")
        else:
            ok = update_shop_item_by_name(ctx.guild.id, item["name"], description=new_value.strip(), item_id=item["id"])
            label = f"description updated for **{item['name']}**"

        if not ok:
            return await ctx.send("Item not found. Use a part of the name.")
        await ctx.send(f"Updated **{item['name']}** — {label}.")

    @commands.command(name="delitem")
    @commands.has_permissions(administrator=True)
    async def delitem(self, ctx: commands.Context, *, item_name: str):
        """Remove an item from the shop by name."""
        item = await self._resolve_shop_item(ctx, item_name)
        if item is None:
            return

        class DelItemView(discord.ui.View):
            def __init__(self, cog_instance, context, item_data):
                super().__init__(timeout=60)
                self.cog = cog_instance
                self.ctx = context
                self.item = item_data
                self.value = None

            @discord.ui.button(label="Delete Everywhere", style=discord.ButtonStyle.danger)
            async def delete_everywhere(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.ctx.author.id:
                    await interaction.response.send_message("This is not for you.", ephemeral=True)
                    return
                ok = remove_shop_item_by_name(self.ctx.guild.id, self.item["name"], delete_from_inventory=True, item_id=self.item["id"])
                if not ok:
                    await interaction.response.edit_message(content="Item not found. Use a part of the name.", view=None)
                    return
                await interaction.response.edit_message(content=f"Item removed from the shop and all inventories: **{self.item['name']}**.", view=None)
                self.stop()

            @discord.ui.button(label="Delete from Shop Only", style=discord.ButtonStyle.secondary)
            async def delete_shop_only(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.ctx.author.id:
                    await interaction.response.send_message("This is not for you.", ephemeral=True)
                    return
                ok = remove_shop_item_by_name(self.ctx.guild.id, self.item["name"], delete_from_inventory=False, item_id=self.item["id"])
                if not ok:
                    await interaction.response.edit_message(content="Item not found. Use a part of the name.", view=None)
                    return
                await interaction.response.edit_message(content=f"Item removed from the shop only (kept in existing player inventories): **{self.item['name']}**.", view=None)
                self.stop()

        view = DelItemView(self, ctx, item)
        await ctx.send(f"How should **{item['name']}** be deleted?", view=view)

    @commands.command(name="reseteconomy", aliases=["re"])
    @commands.has_permissions(administrator=True)
    async def reset_economy(self, ctx: commands.Context, amount: int = 0):
        """Reset all alive players' rolechat balances to a fixed amount (default 0).
        
        Usage: `.reseteconomy [amount]`
        Examples:
          `.reseteconomy`      — sets all to 0
          `.reseteconomy 500`  — sets all to 500
        """
        if amount < 0:
            return await ctx.send("Amount must be >= 0. Usage: `.reseteconomy [amount]` — defaults to 0.")
        if amount > 10_000:
            return await ctx.send("Amount cannot exceed **10,000**. Usage: `.reseteconomy [amount]` — defaults to 0.")

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")

        alive_role_name = guild_data.get("alive_role_name")
        if not alive_role_name:
            return await ctx.send("Alive role not configured. Run `.setup` first.")

        alive_role = discord.utils.get(ctx.guild.roles, name=alive_role_name)
        if not alive_role:
            return await ctx.send("Alive role not found.")

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        cats = [c for c in (rc_cat, alt_cat, dead_rc) if c]

        def _find_rc(member: discord.Member) -> discord.TextChannel | None:
            for cat in cats:
                for c in cat.text_channels:
                    if c.permissions_for(member).send_messages:
                        return c
            return None

        view = ConfirmView(ctx)
        embed = discord.Embed(description=f"⚠️ Are you sure you want to reset ALL alive rolechat balances to **{amount:,}** coins?", color=0xff0000)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()
        if not view.confirmed:
            return

        count = 0
        for member in alive_role.members:
            if member.bot:
                continue
            rc = _find_rc(member)
            if rc:
                set_economy_channel_balance(ctx.guild.id, rc.id, amount)
                count += 1

        if count == 0:
            return await ctx.send("No alive players with rolechats found. Usage: `.reseteconomy [amount]` — defaults to 0.")

        await ctx.send(f"Reset **{count}** rolechat(s) to **{amount:,}** coins.")

        await _log_economy(
            ctx.guild,
            guild_data,
            action="Reset Economy",
            actor=ctx.author,
            details=f"Reset **{count}** rolechat(s) to **{amount:,}** coins.",
        )

    @commands.command(name="clearinventory", aliases=["ci"])
    @commands.has_permissions(administrator=True)
    async def clear_inventory(self, ctx: commands.Context):
        """Remove all items from all alive players' rolechat inventories.
        
        Usage: `.clearinventory`
        """
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")

        alive_role_name = guild_data.get("alive_role_name")
        if not alive_role_name:
            return await ctx.send("Alive role not configured. Run `.setup` first.")

        alive_role = discord.utils.get(ctx.guild.roles, name=alive_role_name)
        if not alive_role:
            return await ctx.send("Alive role not found.")

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        cats = [c for c in (rc_cat, alt_cat, dead_rc) if c]

        def _find_rc(member: discord.Member) -> discord.TextChannel | None:
            for cat in cats:
                for c in cat.text_channels:
                    if c.permissions_for(member).send_messages:
                        return c
            return None

        view = ConfirmView(ctx)
        embed = discord.Embed(description="⚠️ Are you sure you want to remove ALL items from ALL alive rolechat inventories?", color=0xff0000)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()
        if not view.confirmed:
            return

        total_deleted = 0
        channels_cleared = 0
        seen_channels = set()
        for member in alive_role.members:
            if member.bot:
                continue
            rc = _find_rc(member)
            if rc and rc.id not in seen_channels:
                seen_channels.add(rc.id)
                deleted = clear_channel_inventory(ctx.guild.id, rc.id)
                if deleted > 0:
                    total_deleted += deleted
                    channels_cleared += 1

        if total_deleted == 0:
            return await ctx.send("No inventory to clear. Usage: `.clearinventory` — removes all items from all alive rolechats.")

        await ctx.send(f"Cleared **{total_deleted}** item(s) from **{channels_cleared}** rolechat(s).")

        await _log_economy(
            ctx.guild,
            guild_data,
            action="Clear Inventory",
            actor=ctx.author,
            details=f"Cleared **{total_deleted}** item(s) from **{channels_cleared}** rolechat(s).",
        )

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
    # Rolechat-to-rolechat transfers
    # ------------------------------------------------------------------ #

    @commands.command(name="give-money", aliases=["give_money"])
    async def give_money(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Transfer coins from your rolechat to another player's rolechat."""
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0. Usage: `.give-money @user <amount>`.")
        if member.bot:
            return await ctx.send("You can't give coins to a bot.")
        if member == ctx.author:
            return await ctx.send("You can't give coins to yourself.")

        guild_data = load_guild_data(ctx.guild.id)
        sender_rc = _find_player_rolechat(ctx.guild, ctx.author, guild_data)
        recipient_rc = _find_player_rolechat(ctx.guild, member, guild_data)
        if sender_rc is None:
            return await ctx.send("Couldn't find your rolechat.")
        if recipient_rc is None:
            return await ctx.send(f"Couldn't find a rolechat for {member.mention}.")
        if sender_rc.id == recipient_rc.id:
            return await ctx.send("You can't give coins to someone in the same rolechat.")

        if not transfer_channel_balance(ctx.guild.id, sender_rc.id, recipient_rc.id, amount):
            bal = get_economy_channel_balance(ctx.guild.id, sender_rc.id)
            return await ctx.send(f"Insufficient coins. Rolechat balance: **{bal:,}**.")

        await _log_economy(
            ctx.guild,
            guild_data,
            action="Give Money",
            actor=ctx.author,
            details=(
                f"Gave **{amount:,}** to {member.mention} ({member.id}). "
                f"{sender_rc.mention} → {recipient_rc.mention}."
            ),
        )
        await ctx.send(f"You gave **{amount:,}** coins from {sender_rc.mention} to {member.mention} ({recipient_rc.mention}).")

    @commands.command(name="sell-item", aliases=["sell_item", "sell"])
    async def sell_item(self, ctx: commands.Context, *, item_name: str):
        """Sell an item from your rolechat's inventory back to the shop (50% refund)."""
        if not selling_enabled(ctx.guild.id):
            return await ctx.send(SELL_DISABLED_MESSAGE)
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_rolechat_category(ctx, guild_data=guild_data):
            return await ctx.send("Sell items only in a RoleChat channel. Usage: `.sell <item_name>`.")

        owned = await self._resolve_inventory_item(ctx, ctx.channel.id, item_name)
        if owned is None:
            return

        shop_item = get_shop_item_by_id(ctx.guild.id, owned["item_id"])
        if not shop_item:
            return await ctx.send("That item is no longer in the shop, so it can't be sold back.")

        refund = shop_item["price"] // 2
        add_inventory_item_channel(ctx.guild.id, ctx.channel.id, owned["item_id"], -1)
        update_economy_channel_balance(ctx.guild.id, ctx.channel.id, refund)

        await _log_economy(
            ctx.guild,
            guild_data,
            action="Item Sold",
            actor=ctx.author,
            details=f"Sold **{owned['name']}** for **{refund:,}** coins (50% of shop price) in {ctx.channel.mention}.",
        )
        await ctx.send(
            f"Sold **{owned['name']}** for **{refund:,}** coins (50% of shop price)."
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

        count = 0
        for member in role.members:
            if member.bot:
                continue
            rc = _find_player_rolechat(ctx.guild, member, guild_data)
            if rc:
                update_economy_channel_balance(ctx.guild.id, rc.id, amount)
                count += 1

        await ctx.send(f"Added **{amount:,}** to **{count}** rolechats of members with {role.mention}.")
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Add Money Role",
            actor=ctx.author,
            details=f"Added **{amount:,}** to **{count}** rolechat(s) of members with {role.mention}.",
        )

    @commands.command(name="remove-money-role", aliases=["remove_money_role", "rmmrole"])
    @commands.has_permissions(administrator=True)
    async def remove_money_role(self, ctx: commands.Context, role: discord.Role, amount: int):
        """Remove money from rolechats of all members with a specific role."""
        if amount <= 0:
            return await ctx.send("Amount must be greater than 0. Usage: `.rmmrole @role <amount>`.")
        if amount > 10_000:
            return await ctx.send("Amount cannot exceed **10,000** per user.")

        guild_data = load_guild_data(ctx.guild.id)

        # Count members per rolechat so a shared rolechat is only charged once
        # per member, and never below zero.
        member_counts: dict[int, int] = {}
        rolechats: dict[int, discord.TextChannel] = {}
        for member in role.members:
            if member.bot:
                continue
            rc = _find_player_rolechat(ctx.guild, member, guild_data)
            if rc:
                member_counts[rc.id] = member_counts.get(rc.id, 0) + 1
                rolechats[rc.id] = rc

        total_removed = 0
        for rc_id, member_count in member_counts.items():
            bal = get_economy_channel_balance(ctx.guild.id, rc_id)
            to_remove = min(amount * member_count, bal)
            if to_remove <= 0:
                continue
            total_removed += to_remove
            update_economy_channel_balance(ctx.guild.id, rc_id, -to_remove)

        await ctx.send(
            f"Removed **{total_removed:,}** from **{len(rolechats)}** rolechats of members with {role.mention}."
        )
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Remove Money Role",
            actor=ctx.author,
            details=f"Removed **{total_removed:,}** from **{len(rolechats)}** rolechat(s) of members with {role.mention}.",
        )

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    async def leaderboard(self, ctx: commands.Context):
        """Show all rolechats ranked by balance (admin only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
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
            set_economy_channel_balance(ctx.guild.id, cid, 0)

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
        """Use an item from your inventory: most items in a RoleChat, Broom and Peep Hole in a House."""
        guild_data = load_guild_data(ctx.guild.id)
        in_rolechat = _is_rolechat_category(ctx, guild_data=guild_data)
        in_house = _is_houses_category(ctx, guild_data=guild_data)
        if not (in_rolechat or in_house):
            return await ctx.send("Use items in a RoleChat or House channel. Usage: `.use <item_name>`.")

        if in_rolechat:
            inv_channel_id = ctx.channel.id
        else:
            # Items are stored per rolechat, so a house lookup uses the author's rolechat.
            found = _players_rolechat(ctx, guild_data)
            if isinstance(found, str):
                return await ctx.send(found)
            inv_channel_id = found.id

        owned = await self._resolve_inventory_item(ctx, inv_channel_id, item_name)
        if owned is None:
            return

        # Routing uses the item that was matched, not the text typed, so partial names behave the same.
        name_lower = owned["name"].lower()
        is_broom = "broom" in name_lower
        is_peep = "peep" in name_lower
        if is_broom or is_peep:
            label, keyword = ("🧹 Broom", "broom") if is_broom else ("🔭 Peep Hole", "peep")
            if not in_house:
                return await ctx.send(f"{label} can only be used in a House channel. Use `.use {keyword}` there.")
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))
            if not (alive_role in ctx.author.roles or sponsor_role in ctx.author.roles):
                return await ctx.send(f"You need the Alive or Sponsor role to use the {'Peep Hole' if is_peep else 'broom'}.")
        elif not in_rolechat:
            return await ctx.send(f"**{owned['name']}** can only be used in a RoleChat channel.")

        ok = False

        if "firework" in name_lower:
            ok = await self._trigger_fireworks(ctx)
        elif "whisper" in name_lower:
            ok = await self._trigger_whisper(ctx)
        elif "private pc" in name_lower:
            ok = await self._trigger_private_pc(ctx)
        elif "broom" in name_lower:
            ok = await self._trigger_broom(ctx)
        elif "shoe" in name_lower:
            ok = await self._trigger_extra_visit(ctx)
        elif "will" in name_lower:
            ok = await self._trigger_will(ctx)
        elif "peep" in name_lower:
            ok = await self._trigger_peephole(ctx)
        else:
            await ctx.send(f"Used **{owned['name']}**.")
            ok = True

        if ok:
            add_inventory_item_channel(ctx.guild.id, inv_channel_id, owned["item_id"], -1)
            await _log_economy(
                ctx.guild,
                guild_data,
                action="Item Used",
                actor=ctx.author,
                details=f"Used **{owned['name']}** in {ctx.channel.mention} (×1).",
            )

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
            f"{role_pings(alive_role, sponsor_role)}\n{user.mention} is in {house.name}"
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

                    rolechats = _player_rolechat_channels(ctx.guild, guild_data)
                    if not rolechats:
                        await ctx.send("RoleChats category not configured.")
                        return
                    log_ch = discord.utils.get(ctx.guild.channels, name=guild_data.get("whisper_logs_channel_name"))
                    for ch in rolechats:
                        if target in ch.members:
                            embed = info_embed()
                            content = reply.content[:1021] + "..." if len(reply.content) > 1024 else reply.content
                            if guild_data.get("showwhispersender"):
                                embed.add_field(name=f"{ctx.author.mention} sent you a whisper:", value=content, inline=False)
                            else:
                                embed.add_field(name="Someone sent you a whisper:", value=content, inline=False)
                            await ch.send(f"{target.mention}", embed=embed)
                            if log_ch:
                                log_embed = info_embed()
                                log_content = reply.content[:1021] + "..." if len(reply.content) > 1024 else reply.content
                                log_embed.add_field(name=f"{ctx.author.mention} → {target.mention}:", value=log_content, inline=False)
                                await log_ch.send(embed=log_embed)
                            delivered = True
                            break
                    if not delivered:
                        await ctx.send(f"✉ Whisper not sent: {target.display_name} isn't in a RoleChat right now.")
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

    async def _trigger_private_pc(self, ctx: commands.Context) -> bool:
        """Open a private PC with a chosen alive player, plus all sponsors."""
        guild_data = load_guild_data(ctx.guild.id)
        targets = private_pc_targets(ctx.guild, guild_data, ctx.author)
        if isinstance(targets, str):
            await ctx.send(targets)
            return False

        result, done = {"ok": False}, asyncio.Event()

        async def on_pick(target):
            return await open_private_pc_with(ctx.guild, guild_data, ctx.author, target)

        view = private_pc_menu(ctx.author, targets, on_pick, result, done)
        await ctx.send(
            embed=plain_embed(title="🔒 Private PC", description="Choose the player to open a private channel with. Every sponsor is added automatically."),
            view=view,
        )
        try:
            await asyncio.wait_for(done.wait(), timeout=300)
        except asyncio.TimeoutError:
            await ctx.send("Private PC cancelled (timeout).")
            return False
        return result["ok"]

    async def _trigger_broom(self, ctx: commands.Context) -> bool:
        """Clears messages after a user-specified anchor message. Delegates to Utility.broom_delete."""
        try:
            prompt = await ctx.send(
                embed=plain_embed(
                    title="🧹 Broom",
                    description=(
                        "**How to use:**\n"
                        "1. Find the message you want to start brooming **from**\n"
                        "2. **Right-click → Reply** to that message (not this one)\n"
                        "3. Type anything and send\n\n"
                        "I'll delete everything after that message (skipping pinned)."
                    ),
                ),
            )

            def reply_check(m):
                return (m.author == ctx.author
                        and m.channel == ctx.channel
                        and m.reference
                        and m.reference.message_id != prompt.id)

            reply = await ctx.bot.wait_for("message", check=reply_check, timeout=120)
            anchor = reply.reference.resolved
            if not isinstance(anchor, discord.Message):
                try:
                    anchor = await ctx.channel.fetch_message(reply.reference.message_id)
                except (discord.NotFound, discord.HTTPException):
                    await ctx.send("Could not resolve the target message.")
                    return False

            # The replied-to message is part of the sweep, unless it is pinned.
            to_delete = [] if anchor.pinned else [anchor]
            async for msg in ctx.channel.history(after=anchor, limit=None, oldest_first=True):
                if not msg.pinned:
                    to_delete.append(msg)

            if not to_delete:
                await ctx.send("No unpinned messages to delete.")
                return False

            utility = ctx.bot.get_cog("Utility")
            if not utility:
                await ctx.send("Utility cog is not loaded. Cannot broom.")
                return False
            await utility.broom_delete(ctx, to_delete, individual_limit=None)
            return True
        except asyncio.TimeoutError:
            await ctx.send("Broom cancelled (timeout).")
            return False
        except discord.Forbidden:
            await ctx.send("I need Manage Messages permission to use the broom here.")
            return False

    async def _trigger_extra_visit(self, ctx: commands.Context) -> bool:
        """Grants an extra visit and announces in the rolechat where it was used."""
        sent = await self._announce_extra_visit(ctx.channel, ctx.author.display_name)
        if sent:
            await ctx.send("🚪 Extra visit used!")
        else:
            await ctx.send("Extra visits can only be used in a rolechat.")
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

    async def _trigger_peephole(self, ctx: commands.Context) -> bool:
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_houses_category(ctx, guild_data=guild_data):
            await ctx.send("🔭 Peep Hole can only be used in a House channel.")
            return False

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))
        if not (alive_role in ctx.author.roles or sponsor_role in ctx.author.roles):
            await ctx.send("You need the Alive or Sponsor role to use the Peep Hole.")
            return False

        peep_holes = guild_data.get("peep_holes") or {}
        peep_holes[str(ctx.channel.id)] = datetime.now(timezone.utc).timestamp() + 86400
        guild_data["peep_holes"] = peep_holes
        save_guild_data(ctx.guild.id, guild_data)

        await ctx.send(f"🔭 Peep Hole activated in {ctx.channel.mention} for 24 hours.")
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
            if qty <= 0:
                await ctx.send(f"Quantity for `{pair}` must be greater than 0.")
                continue
            item = await self._resolve_shop_item(ctx, name_part)
            if item is None:
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
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Add Items Role",
            actor=ctx.author,
            details=f"Added {summary} to **{count}** rolechat(s) of members with {role.mention}.",
        )

    @commands.command(name="removeitem", aliases=["rmitem"])
    @commands.has_permissions(administrator=True)
    async def removeitem(self, ctx: commands.Context, channel: discord.TextChannel, *, text: str):
        """Remove items from a rolechat's inventory. Usage: .removeitem #rolechannel <item> [qty]"""
        guild_data = load_guild_data(ctx.guild.id)
        query, quantity = _split_trailing_qty(text)
        if quantity <= 0:
            return await ctx.send("Quantity must be positive.")
        if not query:
            return await ctx.send("Usage: `.removeitem #rolechannel <item> [qty]`.")

        item = await self._resolve_shop_item(ctx, query)
        if item is None:
            return

        old_qty = add_inventory_item_channel(ctx.guild.id, channel.id, item["id"], 0)
        if old_qty == 0:
            return await ctx.send(f"{channel.mention} has no **{item['name']}** to remove.")

        new_qty = add_inventory_item_channel(ctx.guild.id, channel.id, item["id"], -quantity)
        removed = old_qty - new_qty
        await ctx.send(f"Removed **{removed}× {item['name']}** from {channel.mention}.")
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Remove Item",
            actor=ctx.author,
            details=f"Removed **{removed}× {item['name']}** from {channel.mention}.",
        )

    @commands.command(name="giveitem")
    @commands.has_permissions(administrator=True)
    async def giveitem(self, ctx: commands.Context, member: discord.Member, *, text: str):
        """Give items to a player. Usage: .giveitem @player <item> [qty]"""
        guild_data = load_guild_data(ctx.guild.id)

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

        target_rc = _find_rc(member)
        if not target_rc:
            return await ctx.send(f"Could not find a rolechat for {member.mention}.")

        query, quantity = _split_trailing_qty(text)
        if quantity <= 0:
            return await ctx.send("Quantity must be greater than 0.")
        if not query:
            return await ctx.send("Usage: `.giveitem @player <item> [qty]`.")

        item = await self._resolve_shop_item(ctx, query)
        if item is None:
            return

        new_qty = add_inventory_item_channel(ctx.guild.id, target_rc.id, item["id"], quantity)
        await ctx.send(f"Gave **{quantity}× {item['name']}** to {member.mention} in #{target_rc.name}. They now have **{new_qty}**.")
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Give Item",
            actor=ctx.author,
            details=f"Gave **{quantity}× {item['name']}** to {member.mention} in #{target_rc.name}. They now have **{new_qty}**.",
        )

    @commands.command(name="removeitemplayer", aliases=["rip"])
    @commands.has_permissions(administrator=True)
    async def removeitemplayer(self, ctx: commands.Context, member: discord.Member, *, text: str):
        """Remove items from a player's inventory. Usage: .removeitemplayer @player <item> [qty]"""
        guild_data = load_guild_data(ctx.guild.id)

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

        target_rc = _find_rc(member)
        if not target_rc:
            return await ctx.send(f"Could not find a rolechat for {member.mention}.")

        query, quantity = _split_trailing_qty(text)
        if quantity <= 0:
            return await ctx.send("Quantity must be greater than 0.")
        if not query:
            return await ctx.send("Usage: `.removeitemplayer @player <item> [qty]`.")

        item = await self._resolve_shop_item(ctx, query)
        if item is None:
            return

        old_qty = add_inventory_item_channel(ctx.guild.id, target_rc.id, item["id"], 0)
        if old_qty == 0:
            return await ctx.send(f"{member.mention} has no **{item['name']}** in #{target_rc.name}.")

        new_qty = add_inventory_item_channel(ctx.guild.id, target_rc.id, item["id"], -quantity)
        removed = old_qty - new_qty
        await ctx.send(f"Removed **{removed}× {item['name']}** from {member.mention} in #{target_rc.name}.")
        await _log_economy(
            ctx.guild,
            guild_data,
            action="Remove Item Player",
            actor=ctx.author,
            details=f"Removed **{removed}× {item['name']}** from {member.mention} in #{target_rc.name}.",
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
