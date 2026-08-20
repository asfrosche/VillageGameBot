from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from cogs.data_utils import load_guild_data
from cogs.library_cog import LibraryDatabase, TEAMS
from utils.bot_db import (
    get_role_package,
    get_role_packages,
    save_role_package,
)
from utils.embeds import error_embed, info_embed, success_embed, warning_embed


TEAM_NAMES = dict(TEAMS)
TEAM_IDS = {name.lower(): number for number, name in TEAM_NAMES.items()}

MAX_FIELD_NAME = 256
MAX_FIELD_CHARS = 1024
MAX_FIELDS_PER_EMBED = 25
MAX_EMBED_CHARS = 6000


@dataclass
class DraftRole:
    channel_id: int
    role_name: str | None
    team: int | None
    player_name: str | None
    player_id: int | None
    sponsors: list[tuple[str, int]] = field(default_factory=list)
    library_sponsor: tuple[str, int] | None = None
    descriptions: list[str | None] = field(default_factory=list)
    package: dict = field(default_factory=dict)
    card_message_id: int | None = None
    issues: list[str] = field(default_factory=list)


@dataclass
class RoleDraft:
    guild_id: int
    game_number: int | None = None
    game_name: str | None = None
    roles: list[DraftRole] = field(default_factory=list)
    approved: bool = False
    published: bool = False


class PackageConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, on_confirm):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.on_confirm = on_confirm
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This confirmation is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await self.on_confirm(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Cancelled.", embed=None, view=self)
        self.stop()


class SponsorSelectView(discord.ui.View):
    def __init__(self, owner_id: int, options: list[tuple[str, int]], on_select):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.on_select = on_select
        self.select = discord.ui.Select(
            placeholder="Choose the Library Sponsor...",
            options=[discord.SelectOption(label=name[:100], value=str(uid)) for name, uid in options[:25]],
        )
        self.select.callback = self._select_callback
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return False
        return True

    async def _select_callback(self, interaction: discord.Interaction):
        selected_id = int(self.select.values[0])
        await self.on_select(interaction, selected_id)
        self.stop()


class RoleHelpView(discord.ui.View):
    def __init__(self, user_id: int, pages: list[discord.Embed], is_admin: bool = False):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.pages = pages
        self.is_admin = is_admin
        self.index = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id or interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("This help menu is not for you.", ephemeral=True)
        return False

    def _update_buttons(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.pages) - 1 or not self.is_admin

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_admin:
            return
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass


class CopyNarrateView(discord.ui.View):
    def __init__(self, user_id: int, channels: list[discord.TextChannel]):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.channels = channels

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("This button is not for you.", ephemeral=True)
        return False

    @discord.ui.button(label="Copy Narrate Command", style=discord.ButtonStyle.secondary)
    async def copy_narrate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.channels:
            await interaction.response.send_message("No channels to message.", ephemeral=True)
            return
        mentions = " ".join(channel.mention for channel in self.channels)
        await interaction.response.send_message(
            f"\n```\n.narrate {mentions} <your message>\n```",
            ephemeral=True,
        )


class RolePackageCog(commands.Cog):
    """Role package registration, publishing, and library import workflow."""

    def __init__(self, bot):
        self.bot = bot
        self.library_db = LibraryDatabase()
        self.drafts: dict[int, RoleDraft] = {}

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _guild_data(self, guild: discord.Guild) -> dict | None:
        return load_guild_data(guild.id)

    def _is_role_chat(self, channel: discord.abc.GuildChannel, guild_data: dict) -> bool:
        for category_name in (
            guild_data.get("rc_category_name"),
            guild_data.get("dead_rc_category_name"),
        ):
            if not category_name:
                continue
            category = discord.utils.get(channel.guild.categories, name=category_name)
            if category and channel in category.channels:
                return True
        return False

    def _is_moderator(self, member: discord.Member, guild_data: dict) -> bool:
        if member.guild_permissions.administrator:
            return True
        role = discord.utils.get(member.guild.roles, name=guild_data.get("overseer_role_name"))
        return bool(role and role in member.roles)

    async def _require_admin(self, ctx: commands.Context) -> bool:
        """Allow only Administrators of the guild where roles are registered."""
        if ctx.author.guild_permissions.administrator:
            return True
        await ctx.send("❌ Only Administrators can use this command.")
        return False

    def _can_view_role_chat(
        self,
        member: discord.Member,
        channel: discord.TextChannel,
        guild_data: dict,
    ) -> bool:
        """Allow any member who can access the Role Chat to read its role."""
        if member.guild_permissions.administrator:
            return True
        if member.bot:
            return False
        return channel.permissions_for(member).read_messages

    async def _require_role_chat(self, ctx: commands.Context) -> bool:
        guild_data = self._guild_data(ctx.guild)
        if not guild_data or not self._is_role_chat(ctx.channel, guild_data):
            await ctx.send("❌ This command must be used in a configured Role Chat.")
            return False
        return True

    @staticmethod
    def _split_text(text: str, limit: int = MAX_FIELD_CHARS) -> list[str]:
        """Split text into field-sized chunks, always breaking at line boundaries."""
        chunks = []
        while len(text) > limit:
            window = text[:limit]
            cut = window.rfind("\n")
            if cut <= 0:
                cut = window.rfind(" ")
                if cut <= 0:
                    cut = limit
            chunks.append(text[:cut].rstrip())
            text = text[cut:].lstrip("\n ")
        if text:
            chunks.append(text)
        return chunks or [""]

    def _package_embeds(
        self,
        messages: list[discord.Message],
        channel: discord.TextChannel,
        exclude_message_id: int | None = None,
    ) -> list[discord.Embed]:
        """Build the role package as paginated embeds, each within Discord limits."""
        title = channel.name
        if messages and messages[0].embeds and messages[0].embeds[0].title:
            title = messages[0].embeds[0].title

        jump_url = None
        for message in messages:
            if exclude_message_id and message.id == exclude_message_id:
                continue
            jump_url = getattr(message, "jump_url", None)
            break
        link = f"\n\n[jump]({jump_url})" if jump_url else ""

        fields: list[tuple[str, str]] = []
        split_limit = MAX_FIELD_CHARS - len(link)
        for message in messages:
            if exclude_message_id and message.id == exclude_message_id:
                continue
            sections = self._message_sections(message)
            if not sections:
                sections = [("", "*[No readable content]*")]
            for name, value in sections:
                label = (name or "\u200b")[:MAX_FIELD_NAME]
                for chunk in self._split_text(value, split_limit):
                    fields.append((label, chunk or "*[No content]*"))

        embeds: list[discord.Embed] = []
        current = info_embed(title=title)
        current_chars = len(title)
        field_count = 0

        def start_new() -> None:
            nonlocal current, current_chars, field_count
            current = info_embed(title=title)
            current_chars = len(title)
            field_count = 0

        for index, (name, value) in enumerate(fields):
            if index == len(fields) - 1 and link:
                value = value + link
            cost = len(name) + len(value)
            if field_count >= MAX_FIELDS_PER_EMBED or current_chars + cost > MAX_EMBED_CHARS:
                embeds.append(current)
                start_new()
            current.add_field(name=name or "_", value=value, inline=False)
            field_count += 1
            current_chars += cost

        if current.fields:
            embeds.append(current)
        if not embeds:
            current = info_embed(title=title)
            current.description = "*[No readable content]*"
            embeds.append(current)
        return embeds

    @staticmethod
    def _message_sections(message: discord.Message) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        for embed in message.embeds:
            if embed.title or embed.description:
                sections.append((embed.title or "Role Information", embed.description or ""))
            for field in embed.fields:
                sections.append((field.name or "Details", field.value or ""))
        if message.content:
            sections.insert(0, ("", message.content))
        return sections

    async def _fetch_package_messages(self, channel: discord.TextChannel, package: dict):
        found = []
        missing = []
        for message_id in package.get("package_ids", []):
            try:
                found.append(await channel.fetch_message(int(message_id)))
            except discord.NotFound:
                missing.append(int(message_id))
            except discord.HTTPException:
                missing.append(int(message_id))
        return found, missing

    def _compile_descriptions(self, messages: list[discord.Message]) -> list[str | None]:
        descriptions: list[str] = []
        for message in messages:
            parts = []
            for name, value in self._message_sections(message):
                parts.append(f"{name}\n{value}" if name else value)
            text = "\n\n".join(part for part in parts if part).strip()
            if text:
                descriptions.append(text)
        return (descriptions + [None] * 4)[:4]

    def _role_name(self, channel: discord.TextChannel, messages: list[discord.Message]) -> str:
        if messages:
            for embed in messages[0].embeds:
                if embed.title:
                    return embed.title.strip()
            if messages[0].content:
                first_line = messages[0].content.splitlines()[0].strip()
                if first_line:
                    return first_line[:100]
        return channel.name

    def _team_from_dashboard(self, guild_id: int, channel_id: int) -> int | None:
        try:
            from utils.bot_db import get_role_dashboard
            dashboard = get_role_dashboard(guild_id, channel_id)
        except Exception:
            dashboard = None
        if not dashboard:
            return None
        value = str(dashboard.get("team", "")).strip().lower()
        if value.isdigit() and int(value) in TEAM_NAMES:
            return int(value)
        return TEAM_IDS.get(value)

    def _resolve_player(self, channel: discord.TextChannel, guild_data: dict):
        alive_role = discord.utils.get(channel.guild.roles, name=guild_data.get("alive_role_name"))
        alive = [member for member in channel.members if not member.bot and alive_role and alive_role in member.roles]
        if len(alive) == 1:
            return alive[0]
        candidates = [
            member for member in channel.members
            if not member.bot and not member.guild_permissions.administrator
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _resolve_sponsors(self, channel: discord.TextChannel, guild_data: dict):
        sponsor_role = discord.utils.get(channel.guild.roles, name=guild_data.get("sponsor_role_name"))
        if not sponsor_role:
            return []
        return [(member.display_name, member.id) for member in channel.members if sponsor_role in member.roles]

    async def _notify_registration(self, ctx: commands.Context):
        guild_data = self._guild_data(ctx.guild) or {}
        if self._is_moderator(ctx.author, guild_data):
            return
        role = discord.utils.get(ctx.guild.roles, name=guild_data.get("role_package_admin_role_name", "Overseer"))
        if role:
            await ctx.send(f"⚠️ {role.mention} Role Package registered by {ctx.author.mention}. Please verify the registration.")

    @staticmethod
    def _library_game_info(channel: discord.TextChannel):
        if not channel.category or channel.category.name not in ("📖 Library A", "📖 Library B"):
            return None
        try:
            number, name = channel.name.split("│", 1)
            return int(number.strip()), name.strip()
        except (ValueError, AttributeError):
            return None

    async def _legacy_firstpin(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        channel = channel or ctx.channel
        spectator_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("spectator_role_name"))
        if channel != ctx.channel and not ctx.author.guild_permissions.administrator:
            if not spectator_role or spectator_role not in ctx.author.roles:
                await ctx.send("You do not have permission to use this command.")
                return
        pins = await channel.pins()
        if not pins:
            await ctx.send("No pinned messages were found in that channel.")
            return
        first_pin = pins[-1]
        embed = discord.Embed(
            title="First Pinned Message",
            description=first_pin.content or "*[No content]*",
            color=0xff3fb9,
            timestamp=datetime.now(),
        )
        embed.add_field(name=" ", value=f"[Jump to the message!]({first_pin.jump_url})", inline=False)
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Stage 1
    # ------------------------------------------------------------------

    @commands.group(name="role", invoke_without_command=True)
    async def role(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Show the registered role package, or use the legacy first-pin view."""
        if ctx.invoked_children:
            return
        if channel is not None and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Only administrators can specify another channel.")
            return
        target = channel or ctx.channel
        guild_data = self._guild_data(ctx.guild)
        if not guild_data or not self._is_role_chat(target, guild_data):
            await self._legacy_firstpin(ctx, target)
            return
        if not self._can_view_role_chat(ctx.author, target, guild_data):
            await ctx.send("❌ You can only view your own Role Chat role.")
            return
        package = get_role_package(target.id)
        if not package or not package.get("package_ids"):
            await self._legacy_firstpin(ctx, target)
            return
        messages, missing = await self._fetch_package_messages(target, package)
        if missing:
            await ctx.send(
                f"⚠️ Role Package `{target.name}` contains missing messages. "
                "Please re-register this package."
            )
        if messages:
            embeds = self._package_embeds(messages, target, exclude_message_id=package.get("card_id"))
            for start in range(0, len(embeds), 10):
                await ctx.send(embeds=embeds[start:start + 10])
        else:
            await ctx.send("❌ No registered Role Package messages could be retrieved.")

    @role.command(name="register")
    async def role_register(self, ctx: commands.Context, count: int):
        if not await self._require_role_chat(ctx):
            return
        if count < 1 or count > 4:
            await ctx.send("❌ Role Packages may contain between one and four messages.")
            return
        pins = list(reversed(await ctx.channel.pins()))
        if count > len(pins):
            await ctx.send(f"❌ Only {len(pins)} pinned message(s) were found.")
            return
        selected = pins[:count]
        existing = get_role_package(ctx.channel.id)
        description = (
            f"**Channel:** {ctx.channel.name}\n"
            f"**Messages:** {len(selected)}\n\n"
            + "\n".join(f"✓ {message.embeds[0].title if message.embeds and message.embeds[0].title else message.content[:80] or 'Untitled'}" for message in selected)
        )
        if existing:
            description = f"⚠️ This channel already has a package with {len(existing.get('package_ids', []))} messages.\n\n" + description + "\n\nReplace existing package?"

        async def save(_interaction):
            old_card = existing.get("card_id") if existing else None
            save_role_package(ctx.channel.id, ctx.guild.id, [message.id for message in selected], old_card, ctx.author.id)
            await ctx.send(embed=success_embed(title="Role Package Registered", description=f"Registered {count} message(s) for {ctx.channel.mention}."))
            await self._notify_registration(ctx)

        view = PackageConfirmView(ctx.author.id, save)
        await ctx.send(embed=info_embed(title="Role Package Registration", description=description), view=view)

    @role.command(name="registercard")
    async def role_registercard(self, ctx: commands.Context, message_id: int | None = None):
        if not await self._require_role_chat(ctx):
            return
        package = get_role_package(ctx.channel.id)
        if not package or not package.get("package_ids"):
            await ctx.send("❌ Register a Role Package first with `.role register <n>`." )
            return
        target_id = message_id or (ctx.message.reference.message_id if ctx.message.reference else None)
        if not target_id:
            await ctx.send("❌ Reply to the role card message or provide its message ID.")
            return
        try:
            await ctx.channel.fetch_message(target_id)
        except (discord.NotFound, discord.HTTPException):
            await ctx.send("❌ That message could not be found in this channel.")
            return
        save_role_package(ctx.channel.id, ctx.guild.id, package["package_ids"], target_id, ctx.author.id)
        await ctx.send(embed=success_embed(title="Role Card Registered", description=f"Message `{target_id}` is now the Role Card."))
        await self._notify_registration(ctx)

    @role.command(name="card")
    async def role_card(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Show the registered Role Card (embeds and images included)."""
        target = channel or ctx.channel
        guild_data = self._guild_data(ctx.guild)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        if channel is not None:
            if not self._is_moderator(ctx.author, guild_data):
                await ctx.send("❌ Only overseers can specify a channel.")
                return
            await ctx.send(
                f"⚠️ Are you sure you want to reveal the Role Card for {target.mention}?\n"
                "Reply **yes** to confirm, anything else to cancel."
            )
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            try:
                response = await self.bot.wait_for("message", timeout=30, check=check)
            except asyncio.TimeoutError:
                await ctx.send("Timed out. Action cancelled.")
                return
            if response.content.lower() != "yes":
                await ctx.send("Action cancelled.")
                return
        else:
            if not self._is_role_chat(ctx.channel, guild_data):
                await ctx.send("❌ This command can only be used in a Role Channel.")
                return
        package = get_role_package(target.id)
        card_id = package.get("card_id") if package else None
        if not card_id:
            await ctx.send("❌ No Role Card registered for this channel. Use `.role registercard <message_id>` first.")
            return
        try:
            card = await target.fetch_message(int(card_id))
        except (discord.NotFound, discord.HTTPException):
            await ctx.send("❌ The registered Role Card message could not be found.")
            return
        await ctx.send(
            content=card.content or None,
            embeds=card.embeds if card.embeds else [],
            files=[await attachment.to_file() for attachment in card.attachments],
        )

    @app_commands.command(name="reveal")
    @app_commands.describe(channel="The Role Channel to reveal")
    async def reveal(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Reveal the Role Card for a Role Channel. Overseer/admin only."""
        guild_data = self._guild_data(interaction.guild)
        if not guild_data:
            await interaction.response.send_message("Guild data not loaded.", ephemeral=True)
            return
        os_role = discord.utils.get(interaction.guild.roles, name=guild_data["overseer_role_name"])
        if os_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only overseers or admins can use this command.", ephemeral=True)
            return
        package = get_role_package(channel.id)
        if not package:
            await interaction.response.send_message("❌ No Role Package registered for this channel. Use `.role register <n>` first.", ephemeral=True)
            return
        card_id = package.get("card_id")
        if not card_id:
            await interaction.response.send_message("❌ No Role Card registered. Use `.role registercard <message_id>` first.", ephemeral=True)
            return
        try:
            card = await channel.fetch_message(int(card_id))
        except (discord.NotFound, discord.HTTPException):
            await interaction.response.send_message("❌ The registered Role Card message could not be found.", ephemeral=True)
            return
        await interaction.response.send_message(
            content=card.content or None,
            embeds=card.embeds if card.embeds else [],
            files=[await attachment.to_file() for attachment in card.attachments],
            ephemeral=True,
        )

    @role.command(name="list")
    async def role_list(self, ctx: commands.Context):
        """List Role Chats with and without registered packages (admin only)."""
        if not await self._require_admin(ctx):
            return
        guild_data = self._guild_data(ctx.guild)
        if not guild_data:
            await ctx.send("❌ Guild data is not loaded.")
            return
        packages = {package["channel_id"]: package for package in get_role_packages(ctx.guild.id)}
        channels: list[discord.TextChannel] = []
        for category_name in (
            guild_data.get("rc_category_name"),
            guild_data.get("dead_rc_category_name"),
        ):
            category = discord.utils.get(ctx.guild.categories, name=category_name)
            if category:
                channels.extend(category.text_channels)
        with_card = [channel for channel in channels if packages.get(channel.id, {}).get("card_id")]
        no_card = [
            channel for channel in channels
            if channel.id in packages and not packages[channel.id].get("card_id")
        ]
        unregistered = [channel for channel in channels if channel.id not in packages]
        needs_action = no_card + unregistered
        mentions = lambda items: " ".join(channel.mention for channel in items) or "*None*"
        await ctx.send(
            embed=info_embed(
                title="Role Chat Registration Status",
                description=(
                    f"**✅ Card Registered ({len(with_card)})**\n{mentions(with_card)}\n\n"
                    f"**⚠️ Registered, No Card ({len(no_card)})**\n{mentions(no_card)}\n\n"
                    f"**❌ Not Registered ({len(unregistered)})**\n{mentions(unregistered)}"
                ),
            ),
            view=CopyNarrateView(ctx.author.id, needs_action),
        )

    @role.command(name="help")
    async def role_help(self, ctx: commands.Context):
        """Explain the Role Package workflow (starts at Stage 1)."""
        pages = [
            info_embed(
                title="🧩 Stage 1 · Registration (in your Role Chat)",
                description=(
                    "**Step 1 — Pin your role**\n"
                    "Make sure the **first `<n>` pinned messages** are **ONLY** the messages describing the role "
                    "you own (up to 4). No other pinned messages should be above them — the bot registers the "
                    "top `<n>` pins.\n\n"
                    "**Step 2 — Register the package**\n"
                    "Use:\n"
                    "`.role register <n>`\n"
                    "Example: `.role register 2`\n"
                    "*(Replace `<n>` with how many messages you pinned, 1-4.)*\n\n"
                    "**Step 3 — Register the Role Card (optional)**\n"
                    "Reply to the card image with `.role registercard`, or run `.role registercard <message_id>`.\n\n"
                    "**Step 4 — View it**\n"
                    "`.role` — show your package (role card excluded)\n"
                    "`.role card` — show your Role Card image\n\n"
                    "*Anyone who can see the Role Chat can view; registering notifies the Overseer.*"
                ),
            ),
            info_embed(
                title="🧩 Stage 2 · Publishing (admin/Overseer)",
                description=(
                    "**Step 1 — Build the draft**\n"
                    "Run `.publishroles [game_number] [game_name]`.\n"
                    "If you leave the arguments empty, you will be prompted for them.\n\n"
                    "**Step 2 — Resolve every issue**\n"
                    "`.resolveplayers` — list Role Chats missing a player, then fix with:\n"
                    "`.resolveplayer #channel @player`\n"
                    "`.resolveteam #channel <team>` — 1=Village, 2=Evil, 3=Random Killer, 4=Neutral, 5=Bonus\n"
                    "`.resolvesponsor #channel @sponsor` — pick the Library sponsor\n\n"
                    "**Step 3 — Review**\n"
                    "`.reviewroles` — check player/team/sponsor/package/card for every role\n"
                    "`.reviewteams` — see the full team list\n\n"
                    "**Step 4 — Publish**\n"
                    "`.approvepublish` — validates everything, then archives the roles to the logging server."
                ),
            ),
            info_embed(
                title="🧩 Stage 3 · Import (admin/Overseer)",
                description=(
                    "**Step 1 — Finish publishing**\n"
                    "Make sure `.approvepublish` completed (draft approved and published) before continuing.\n\n"
                    "**Step 2 — Go to the right Library channel**\n"
                    "The channel name must match the draft, e.g. `12│ Custom Ranked Game`.\n"
                    "`.libimport` refuses to run elsewhere or if the name does not match.\n\n"
                    "**Step 3 — Import**\n"
                    "`.libimport` — writes the roles into the Library.\n"
                    "The import is atomic: any error rolls the whole transaction back."
                ),
            ),
        ]
        for index, embed in enumerate(pages, start=1):
            embed.set_footer(text=f"Page {index} of {len(pages)} · Use the buttons to navigate")
        view = RoleHelpView(ctx.author.id, pages, is_admin=ctx.author.guild_permissions.administrator)
        msg = await ctx.send(embed=pages[0], view=view)
        view.message = msg

    # ------------------------------------------------------------------
    # Stage 2
    # ------------------------------------------------------------------

    @commands.command(name="publishroles")
    async def publishroles(self, ctx: commands.Context, game_number: int | None = None, *, game_name: str | None = None):
        if not await self._require_admin(ctx):
            return
        packages = get_role_packages(ctx.guild.id)
        if not packages:
            await ctx.send("❌ No Role Packages are registered in this server.")
            return
        draft = RoleDraft(ctx.guild.id, game_number=game_number, game_name=game_name)
        for package in packages:
            channel = ctx.guild.get_channel(package["channel_id"])
            issues = []
            if not channel:
                continue
            messages, missing = await self._fetch_package_messages(channel, package)
            if missing:
                issues.append("Registered message deleted")
            if not package.get("card_id"):
                issues.append("Role Card missing")
            player = self._resolve_player(channel, guild_data)
            if not player:
                issues.append("Player unresolved")
            team = self._team_from_dashboard(ctx.guild.id, channel.id)
            if team is None:
                issues.append("Team unresolved")
            sponsors = self._resolve_sponsors(channel, guild_data)
            if len(sponsors) > 1:
                issues.append("Library sponsor unresolved")
            descriptions = self._compile_descriptions(messages)
            role = DraftRole(
                channel_id=channel.id,
                role_name=self._role_name(channel, messages) if messages else channel.name,
                team=team,
                player_name=player.display_name if player else None,
                player_id=player.id if player else None,
                sponsors=sponsors,
                library_sponsor=sponsors[0] if len(sponsors) == 1 else None,
                descriptions=descriptions,
                package=package,
                card_message_id=package.get("card_id"),
                issues=issues,
            )
            draft.roles.append(role)
        if draft.game_number is None or not draft.game_name:
            try:
                await ctx.send("Enter the Game Number for this archive:")
                number_message = await self.bot.wait_for(
                    "message",
                    timeout=120,
                    check=lambda message: message.author.id == ctx.author.id and message.channel.id == ctx.channel.id,
                )
                draft.game_number = int(number_message.content.strip())
                await ctx.send("Enter the Game Name for this archive:")
                name_message = await self.bot.wait_for(
                    "message",
                    timeout=120,
                    check=lambda message: message.author.id == ctx.author.id and message.channel.id == ctx.channel.id,
                )
                draft.game_name = name_message.content.strip()
            except (asyncio.TimeoutError, ValueError):
                await ctx.send("❌ Publishing draft cancelled or invalid game information was provided.")
                return
        self.drafts[ctx.guild.id] = draft
        unresolved = sum(bool(role.issues) for role in draft.roles)
        await ctx.send(embed=info_embed(title="Role Publishing Draft Built", description=f"Roles: {len(draft.roles)}\nBlocking issues: {unresolved}\n\nUse `.reviewroles` and `.reviewteams` to review."))
        for role in draft.roles:
            if len(role.sponsors) <= 1:
                continue

            async def choose_sponsor(interaction, selected_id, channel_id=role.channel_id):
                current = self.drafts.get(interaction.guild.id)
                if not current:
                    await interaction.response.send_message("Draft no longer exists.", ephemeral=True)
                    return
                selected = next((item for item in current.roles if item.channel_id == channel_id), None)
                if not selected:
                    await interaction.response.send_message("Role is no longer in the draft.", ephemeral=True)
                    return
                selected.library_sponsor = next(item for item in selected.sponsors if item[1] == selected_id)
                selected.issues = [issue for issue in selected.issues if issue != "Library sponsor unresolved"]
                await interaction.response.edit_message(content=f"✅ Library Sponsor selected: {selected.library_sponsor[0]}", view=None)

            channel = ctx.guild.get_channel(role.channel_id)
            await ctx.send(
                f"**{role.role_name}** in {channel.mention if channel else role.channel_id} has multiple sponsors. Choose the Library Sponsor:",
                view=SponsorSelectView(ctx.author.id, role.sponsors, choose_sponsor),
            )

    @commands.command(name="resolveplayers")
    async def resolveplayers(self, ctx: commands.Context):
        if not await self._require_admin(ctx):
            return
        draft = self.drafts.get(ctx.guild.id)
        if not draft:
            await ctx.send("❌ No publishing draft exists. Run `.publishroles` first.")
            return
        unresolved = [role for role in draft.roles if "Player unresolved" in role.issues]
        if not unresolved:
            await ctx.send("✅ All players are resolved.")
            return
        lines = ["**Unresolved Role Chats**"]
        for role in unresolved:
            channel = ctx.guild.get_channel(role.channel_id)
            lines.append(f"{channel.mention if channel else role.channel_id} — {role.role_name}\nUse `.resolveplayer #{channel.name if channel else 'channel'} @player`" )
        await ctx.send("\n".join(lines))

    @commands.command(name="resolveplayer")
    async def resolveplayer(self, ctx: commands.Context, channel: discord.TextChannel, player: discord.Member):
        if not await self._require_admin(ctx):
            return
        draft = self.drafts.get(ctx.guild.id)
        if not draft:
            await ctx.send("❌ No publishing draft exists. Run `.publishroles` first.")
            return
        for role in draft.roles:
            if role.channel_id == channel.id:
                role.player_name = player.display_name
                role.player_id = player.id
                role.issues = [issue for issue in role.issues if issue != "Player unresolved"]
                await ctx.send(f"✅ Player for {channel.mention} resolved to {player.mention}.")
                return
        await ctx.send("❌ That channel is not in the current publishing draft.")

    @commands.command(name="resolveteam")
    async def resolveteam(self, ctx: commands.Context, channel: discord.TextChannel, team: int):
        if not await self._require_admin(ctx):
            return
        draft = self.drafts.get(ctx.guild.id)
        if not draft or team not in TEAM_NAMES:
            await ctx.send("❌ Invalid draft or team. Teams are 1=Village, 2=Evil, 3=Random Killer, 4=Neutral, 5=Bonus.")
            return
        for role in draft.roles:
            if role.channel_id == channel.id:
                role.team = team
                role.issues = [issue for issue in role.issues if issue != "Team unresolved"]
                await ctx.send(f"✅ Team for {channel.mention} set to {TEAM_NAMES[team]}.")
                return
        await ctx.send("❌ That channel is not in the current draft.")

    @commands.command(name="resolvesponsor")
    async def resolvesponsor(self, ctx: commands.Context, channel: discord.TextChannel, sponsor: discord.Member):
        """Choose the one sponsor that will be written to the Library."""
        if not await self._require_admin(ctx):
            return
        draft = self.drafts.get(ctx.guild.id)
        if not draft:
            await ctx.send("❌ No publishing draft exists. Run `.publishroles` first.")
            return
        for role in draft.roles:
            if role.channel_id == channel.id:
                if sponsor.id not in {uid for _, uid in role.sponsors}:
                    await ctx.send("❌ That member is not a sponsor in this Role Chat.")
                    return
                role.library_sponsor = (sponsor.display_name, sponsor.id)
                role.issues = [issue for issue in role.issues if issue != "Library sponsor unresolved"]
                await ctx.send(f"✅ Library sponsor for {channel.mention} set to {sponsor.mention}.")
                return
        await ctx.send("❌ That channel is not in the current publishing draft.")

    @commands.command(name="reviewroles")
    async def reviewroles(self, ctx: commands.Context):
        if not await self._require_admin(ctx):
            return
        draft = self.drafts.get(ctx.guild.id)
        if not draft:
            await ctx.send("❌ No publishing draft exists. Run `.publishroles` first.")
            return
        lines = []
        for role in draft.roles:
            package_ok = bool(role.package.get("package_ids"))
            card_ok = bool(role.card_message_id)
            sponsors = ", ".join(name for name, _ in role.sponsors) or "None"
            library_sponsor = role.library_sponsor[0] if role.library_sponsor else "Needs selection" if len(role.sponsors) > 1 else "None"
            issues = ", ".join(role.issues) or "None"
            lines.append(
                f"**{role.role_name}**\n"
                f"Player: {role.player_name or '❌ Unknown'}\n"
                f"Team: {TEAM_NAMES.get(role.team, '❌ Unknown')}\n"
                f"Sponsors: {sponsors}\nLibrary Sponsor: {library_sponsor}\n"
                f"Package: {'✅' if package_ok else '❌'} | Card: {'✅' if card_ok else '❌'}\n"
                f"Issues: {issues}"
            )
        for start in range(0, len(lines), 5):
            await ctx.send(embed=info_embed(title=f"Role Review ({start + 1}-{min(start + 5, len(lines))}/{len(lines)})", description="\n\n".join(lines[start:start + 5])))

    @commands.command(name="reviewteams")
    async def reviewteams(self, ctx: commands.Context):
        if not await self._require_admin(ctx):
            return
        draft = self.drafts.get(ctx.guild.id)
        if not draft:
            await ctx.send("❌ No publishing draft exists. Run `.publishroles` first.")
            return
        sections = []
        for team_number, team_name in TEAM_NAMES.items():
            roles = [role for role in draft.roles if role.team == team_number]
            if roles:
                sections.append(f"# {team_name} Team\n" + "\n".join(f"{role.role_name} → {role.player_name or 'Unknown'}" for role in roles))
        await ctx.send(embed=info_embed(title="Team Review", description="\n\n────────────────\n\n".join(sections) + "\n\n⚠️ Verify that no player swapped roles with a sponsor."))

    @commands.command(name="approvepublish")
    async def approvepublish(self, ctx: commands.Context):
        guild_data = self._guild_data(ctx.guild)
        draft = self.drafts.get(ctx.guild.id)
        if not await self._require_admin(ctx):
            return
        if not draft or not guild_data:
            await ctx.send("❌ No draft exists or guild data is not loaded.")
            return
        issues = [f"{role.role_name}: {', '.join(role.issues)}" for role in draft.roles if role.issues or not role.player_id or role.team is None]
        if issues:
            await ctx.send(embed=error_embed(title="Publishing Blocked", description="\n".join(issues)))
            return
        draft.approved = True
        await self._publish_logging_archive(ctx, draft, guild_data)
        await ctx.send(embed=success_embed(title="Publishing Complete", description=f"Game {draft.game_number or 'pending'} archive published."))

    async def _publish_logging_archive(self, ctx: commands.Context, draft: RoleDraft, guild_data: dict):
        guild_id = guild_data.get("role_package_logging_guild_id")
        channel_name = guild_data.get("role_package_logging_channel_name")
        if not guild_id or not channel_name:
            raise RuntimeError("Logging server is not configured.")
        guild = self.bot.get_guild(int(guild_id))
        channel = discord.utils.find(lambda item: item.name == channel_name, guild.text_channels) if guild else None
        if not channel:
            raise RuntimeError("Logging server channel could not be found.")
        for team_number, team_name in TEAM_NAMES.items():
            team_roles = [role for role in draft.roles if role.team == team_number]
            if not team_roles:
                continue
            header = await channel.send(f"# {team_name} Team")
            try:
                await header.pin()
            except discord.HTTPException:
                pass
            for role in team_roles:
                text = "\n\n".join(value for value in role.descriptions if value)
                details = f"{text}\n\nPlayed by {role.player_name}"
                if role.sponsors:
                    details += "\nSponsored by " + ", ".join(name for name, _ in role.sponsors)
                await channel.send(details[:2000])
                if role.card_message_id:
                    source = ctx.guild.get_channel(role.channel_id)
                    if source:
                        try:
                            card = await source.fetch_message(role.card_message_id)
                            await channel.send(embeds=card.embeds, files=[await attachment.to_file() for attachment in card.attachments])
                        except (discord.NotFound, discord.HTTPException):
                            pass
                await asyncio.sleep(0.5)
        draft.published = True

    # ------------------------------------------------------------------
    # Stage 3
    # ------------------------------------------------------------------

    @commands.command(name="libimport")
    async def libimport(self, ctx: commands.Context):
        guild_data = self._guild_data(ctx.guild)
        draft = self.drafts.get(ctx.guild.id)
        if not await self._require_admin(ctx):
            return
        if not draft or not draft.approved or not draft.published:
            await ctx.send("❌ No approved published draft exists. Complete `.approvepublish` first.")
            return
        if not guild_data:
            await ctx.send("❌ Guild data is not loaded.")
            return
        game_info = self._library_game_info(ctx.channel)
        if not game_info:
            await ctx.send("❌ This command must be used in a Library game channel.")
            return
        if draft.game_number != game_info[0] or draft.game_name != game_info[1]:
            await ctx.send(
                f"❌ Library channel does not match the approved draft.\n"
                f"Expected: {draft.game_number}│ {draft.game_name}\n"
                f"Current: {game_info[0]}│ {game_info[1]}"
            )
            return
        roles = []
        for role in draft.roles:
            roles.append({
                "role_name": role.role_name,
                "team": role.team,
                "player_name": role.player_name,
                "player_id": role.player_id,
                "sponsor_name": role.library_sponsor[0] if role.library_sponsor else None,
                "sponsor_id": role.library_sponsor[1] if role.library_sponsor else None,
                "description1": role.descriptions[0] if len(role.descriptions) > 0 else None,
                "description2": role.descriptions[1] if len(role.descriptions) > 1 else None,
                "description3": role.descriptions[2] if len(role.descriptions) > 2 else None,
                "description4": role.descriptions[3] if len(role.descriptions) > 3 else None,
            })
        try:
            imported = self.library_db.import_roles_atomic(draft.game_number, draft.game_name, roles)
        except Exception as exc:
            await ctx.send(embed=error_embed(title="Library Import Failed", description=f"The transaction was rolled back.\n\n`{exc}`"))
            return
        await ctx.send(embed=success_embed(title="Library Import Complete", description=f"Imported {imported} role(s) into {draft.game_number}│ {draft.game_name}."))


async def setup(bot):
    await bot.add_cog(RolePackageCog(bot))
