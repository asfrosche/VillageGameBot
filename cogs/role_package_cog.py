from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from cogs.data_utils import load_guild_data, save_guild_data
from cogs.library_cog import LibraryDatabase, TEAMS, LIBRARIAN_IDS
from cogs.library_it_cog import ItalianLibraryDatabase
from utils.bot_db import (
    get_role_package,
    get_role_packages,
    save_role_package,
)
from utils.embeds import error_embed, info_embed, success_embed, warning_embed


TEAM_NAMES = dict(TEAMS)
TEAM_IDS = {name.lower(): number for number, name in TEAM_NAMES.items()}

CHANNEL_INCOMPLETE_SUFFIX = " xx"

MAX_FIELD_NAME = 256
MAX_FIELD_CHARS = 1024
MAX_FIELDS_PER_EMBED = 25
MAX_EMBED_CHARS = 6000
MAX_EMBED_DESC = 4096


def _escape_md(value: str | None) -> str | None:
    """Escape Discord markdown (_, *, ~, `, |, \\) so raw names render as plain text."""
    return discord.utils.escape_markdown(value) if value else value


def _clean_visual_name(value: str | None) -> str | None:
    """Visual-only filter: keep letters and spaces, drop numbers/special characters."""
    if not value:
        return value
    cleaned = " ".join("".join(c if c.isalpha() or c.isspace() else " " for c in value).split())
    return cleaned or value


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
        self.library_db_it = ItalianLibraryDatabase()
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

    async def _require_overseer(self, ctx: commands.Context) -> bool:
        guild_data = self._guild_data(ctx.guild)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return False
        category_name = guild_data.get("overseer_category_name", "OVERSEER")
        category = discord.utils.get(ctx.guild.categories, name=category_name)
        if not category or ctx.channel.category != category:
            if ctx.author.guild_permissions.administrator:
                confirm_msg = await ctx.send(
                    f"⚠️ Admin bypass: This command should be used in a channel within the **{category_name}** category.\n"
                    "Reply **yes** to proceed anyway, anything else to cancel."
                )
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel
                try:
                    response = await self.bot.wait_for("message", timeout=30, check=check)
                except asyncio.TimeoutError:
                    await ctx.send("Timed out. Action cancelled.")
                    return False
                if response.content.lower() != "yes":
                    await ctx.send("Action cancelled.")
                    return False
                try:
                    await confirm_msg.delete()
                    await response.delete()
                except discord.HTTPException:
                    pass
                return True
            await ctx.send(f"❌ This command must be used in a channel within the **{category_name}** category.")
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
            else:
                descriptions.append(None)
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

    def _team_from_slots(self, guild_data: dict, player_id: int, channel_id: int = None) -> int | None:
        if channel_id is not None:
            channel_slots = guild_data.get("channel_slots", {})
            stored_slot = self._get_channel_slot(channel_slots, channel_id)
            if stored_slot is not None:
                return stored_slot
        return guild_data.get("player_slots", {}).get(str(player_id))

    def _resolve_player(self, channel: discord.TextChannel, guild_data: dict):
        alive_role = discord.utils.get(channel.guild.roles, name=guild_data.get("alive_role_name"))
        alive = [member for member in channel.members if not member.bot and alive_role and alive_role in member.roles]
        if len(alive) == 1:
            return alive[0]
        candidates = [
            member for member in channel.members
            if not member.bot and not member.guild_permissions.administrator
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

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
        if ctx.command is not self.role:
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
    async def role_register(self, ctx: commands.Context, count: int, *, role_name: str):
        if not await self._require_role_chat(ctx):
            return
        if count < 1 or count > 4:
            await ctx.send("❌ Role Packages may contain between one and four messages.")
            return
        if not role_name or not role_name.strip():
            await ctx.send("❌ Role name is required. Usage: `.role register <1-4> <role name>`")
            return
        pins = list(reversed(await ctx.channel.pins()))
        if count > len(pins):
            await ctx.send(f"❌ Only {len(pins)} pinned message(s) were found.")
            return
        selected = pins[:count]
        existing = get_role_package(ctx.channel.id)
        name_display = f"**Role Name:** {role_name}\n" if role_name else ""
        description = (
            f"**Channel:** {ctx.channel.name}\n"
            + name_display
            + f"**Messages:** {len(selected)}\n\n"
            + "\n".join(f"✓ {message.embeds[0].title if message.embeds and message.embeds[0].title else message.content[:80] or 'Untitled'}" for message in selected)
        )
        if existing:
            description = f"⚠️ This channel already has a package with {len(existing.get('package_ids', []))} messages.\n\n" + description + "\n\nReplace existing package?"

        async def save(_interaction):
            try:
                old_card = existing.get("card_id") if existing else None
                save_role_package(ctx.channel.id, ctx.guild.id, [message.id for message in selected], old_card, ctx.author.id, role_name)
            except Exception as exc:
                await ctx.send(embed=error_embed(title="Registration Failed", description=f"Failed to save role package: {exc}"))
                return
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
            await ctx.send("❌ Register a Role Package first with `.role register <n> <role name>`.")
            return
        target_id = message_id or (ctx.message.reference.message_id if ctx.message.reference else None)
        if not target_id:
            await ctx.send("❌ Reply to the role card message or provide its message ID.")
            return
        try:
            card_message = await ctx.channel.fetch_message(target_id)
        except (discord.NotFound, discord.HTTPException):
            await ctx.send("❌ That message could not be found in this channel.")
            return
        if card_message.content and card_message.attachments:
            await ctx.send("❌ Please download the image, send it **alone** in a separate message, then run `.role registercard` again with that new message.")
            return
        save_role_package(ctx.channel.id, ctx.guild.id, package["package_ids"], target_id, ctx.author.id, package.get("role_name"))
        await ctx.send(embed=success_embed(title="Role Card Registered", description=f"Message `{target_id}` is now the Role Card."))
        await self._notify_registration(ctx)

    def _resolve_name(self, guild, input_str: str):
        """Resolve a player/sponsor string: mention, user ID, or display name. Returns (display_name, user_id_or_None)."""
        if not input_str:
            return None, None
        input_str = input_str.strip()
        m = re.match(r"<@!?(\d+)>$", input_str)
        if m:
            uid = int(m.group(1))
            member = guild.get_member(uid)
            if member:
                return member.name, str(uid)
            return input_str, str(uid)
        if input_str.isdigit():
            uid = int(input_str)
            member = guild.get_member(uid)
            return (member.name if member else f"User ID {uid}", str(uid))
        for member in guild.members:
            if member.name.lower() == input_str.lower():
                return member.name, str(member.id)
        return input_str, None

    def _normalize_player_info(self, member_or_info, guild=None):
        """Normalize player/sponsor input: Member, dict, or string name → {name, id, member}."""
        if member_or_info is None:
            return {"name": "—", "id": None, "member": None}
        if isinstance(member_or_info, dict):
            return member_or_info
        if isinstance(member_or_info, discord.Member):
            return {"name": member_or_info.name, "id": str(member_or_info.id), "member": member_or_info}
        return {"name": str(member_or_info), "id": None, "member": None}

    def _get_channel_slot(self, channel_slots, channel_id):
        """Get slot from channel_slots, handling both old int format and new dict format."""
        stored = channel_slots.get(str(channel_id))
        if stored is None:
            return None
        if isinstance(stored, int):
            return stored
        if isinstance(stored, dict):
            return stored.get("slot")
        return None

    def _get_channel_slot_info(self, channel_slots, channel_id):
        """Get full info dict from channel_slots, handling both old int format and new dict format."""
        stored = channel_slots.get(str(channel_id))
        if stored is None:
            return None
        if isinstance(stored, dict):
            return stored
        return None

    @role.command(name="regteam")
    async def role_regteam(self, ctx: commands.Context, slot: int, player: str = None, sponsor: str = None, *, channel: discord.TextChannel = None):
        """Set the team slot for a role channel.
        Usage:
          .role regteam [1-5]             — in your own RC (auto-detect player + sponsor)
          .role regteam [1-5] @player     — specify player if no sponsor 
          .role regteam [1-5] @player @sponsor — specify both directly (only 1 sponsor)
        Player and sponsor can be mentions, user IDs, display names, or (for logged players no longer on the server) plain text names.
        """
        cog_ref = self
        slot_names = {1: "Village", 2: "Evil", 3: "Rk", 4: "Neutral", 5: "Bonus/Extra"}

        if slot is not None and (slot < 1 or slot > 5):
            await ctx.send("❌ Slot must be 1-5.\n1=Village · 2=Evil · 3=Rk · 4=Neutral · 5=Bonus")
            return

        guild_data = self._guild_data(ctx.guild)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        is_admin = ctx.author.guild_permissions.administrator

        if channel is None:
            channel = ctx.channel
            is_self = True
        else:
            is_self = False

        package = get_role_package(channel.id)
        if not package or not package.get("package_ids"):
            await ctx.send(f"❌ No Role Package registered for {channel.mention}.\nRun `.role register <n> <role name>` first.")
            return

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alt_role_name", "")) if guild_data.get("alt_role_name") else None

        player_members = [m for m in channel.members if alive_role in m.roles] if alive_role else []
        sponsor_members = [
            m for m in channel.members
            if (sponsor_role in m.roles or (alt_role and alt_role in m.roles)) and alive_role not in m.roles
        ] if sponsor_role else []

        resolved_player_name, resolved_player_id = self._resolve_name(ctx.guild, player)
        resolved_sponsor_name, resolved_sponsor_id = self._resolve_name(ctx.guild, sponsor)

        player_is_ctx_author = (
            (resolved_player_id is not None and str(ctx.author.id) == resolved_player_id)
            or (player is not None and (player.strip() == f"<@{ctx.author.id}>" or player.strip() == f"<@!{ctx.author.id}>"))
        )

        sponsor_is_ctx_author = (
            (resolved_sponsor_id is not None and str(ctx.author.id) == resolved_sponsor_id)
            or (sponsor is not None and (sponsor.strip() == f"<@{ctx.author.id}>" or sponsor.strip() == f"<@!{ctx.author.id}>"))
        )

        if player and sponsor:
            if not is_admin and not player_is_ctx_author and not sponsor_is_ctx_author:
                await ctx.send("❌ Only administrators can specify a player or sponsor other than themselves.")
                return
            resolved = {
                "name": resolved_player_name or player or "—",
                "id": resolved_player_id,
                "member": ctx.guild.get_member(int(resolved_player_id)) if resolved_player_id else None,
            }
            resolved_sp = {
                "name": resolved_sponsor_name or sponsor or "None",
                "id": resolved_sponsor_id,
                "member": ctx.guild.get_member(int(resolved_sponsor_id)) if resolved_sponsor_id else None,
            }
            await self._do_regteam_confirm(ctx, channel, slot, resolved, resolved_sp)
            return

        if player:
            if not is_admin and not player_is_ctx_author:
                await ctx.send("❌ Only administrators can specify a player other than themselves.")
                return
            if sponsor:
                sp_info = {
                    "name": resolved_sponsor_name or sponsor or "None",
                    "id": resolved_sponsor_id,
                    "member": ctx.guild.get_member(int(resolved_sponsor_id)) if resolved_sponsor_id else None,
                }
                selected_sponsor = sp_info
            else:
                selected_sponsor = None
            await self._do_regteam_confirm(ctx, channel, slot, player, selected_sponsor)
            return

        if not player_members:
            all_members = [m for m in channel.members if not m.bot]
            if not all_members:
                await ctx.send(f"❌ No members found in {channel.mention}.")
                return

            picker_msg = await ctx.send(
                f"⚠️ No Alive players found in {channel.mention}.\n"
                f"Select the **player** for Slot {slot} ({slot_names[slot]}):"
            )

            class PlayerPickView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=60)
                    self.select = discord.ui.Select(
                        placeholder="Choose the player...",
                        options=[
                            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
                            for m in all_members[:25]
                        ],
                    )
                    self.select.callback = self._on_select
                    self.add_item(self.select)

                async def _on_select(self, interaction: discord.Interaction):
                    if interaction.user.id != ctx.author.id:
                        await interaction.response.send_message("Not for you.", ephemeral=True)
                        return
                    player_id = int(self.select.values[0])
                    await interaction.message.delete()
                    await picker_msg.delete()
                    selected_member = ctx.guild.get_member(player_id)
                    if is_self:
                        await cog_ref._do_regteam_self_picked(ctx, channel, slot, selected_member, sponsor_members, is_admin)
                    else:
                        await cog_ref._do_regteam_confirm(ctx, channel, slot, selected_member, None)

                async def interaction_check(self, interaction: discord.Interaction) -> bool:
                    if interaction.user.id != ctx.author.id:
                        await interaction.response.send_message("Not for you.", ephemeral=True)
                        return False
                    return True

            await ctx.send(view=PlayerPickView())
            return

        if len(sponsor_members) > 25:
            await ctx.send(f"❌ Too many sponsors in {channel.mention} (max 25).")
            return

        if is_self:
            if not is_admin and ctx.author not in player_members and ctx.author not in sponsor_members:
                await ctx.send(f"❌ You must have the **Alive** or **Sponsor** role in {channel.mention} to register your team.")
                return
            selected_player = ctx.author if ctx.author in player_members else None
            if selected_player is None and player_members:
                if len(player_members) == 1:
                    selected_player = player_members[0]
                else:
                    picker_msg = await ctx.send(
                        f"⚠️ Multiple Alive players found in {channel.mention}.\n"
                        f"Select the **player** for Slot {slot} ({slot_names[slot]}):"
                    )
                    all_members = player_members

                    class PlayerPickView(discord.ui.View):
                        def __init__(self):
                            super().__init__(timeout=60)
                            self.select = discord.ui.Select(
                                placeholder="Choose the player...",
                                options=[
                                    discord.SelectOption(label=m.display_name[:100], value=str(m.id))
                                    for m in all_members[:25]
                                ],
                            )
                            self.select.callback = self._on_select
                            self.add_item(self.select)

                        async def _on_select(self, interaction: discord.Interaction):
                            if interaction.user.id != ctx.author.id:
                                await interaction.response.send_message("Not for you.", ephemeral=True)
                                return
                            player_id = int(self.select.values[0])
                            await interaction.message.delete()
                            await picker_msg.delete()
                            selected_member = ctx.guild.get_member(player_id)
                            if len(sponsor_members) > 1:
                                sponsor_picker_msg = await ctx.send(
                                    f"⚠️ **{channel.name}** has multiple sponsors. Which sponsor do you want to log for stats? (Slot {slot} — {slot_names[slot]}):\n"
                                    + "\n".join(f"• {m.display_name}" for m in sponsor_members)
                                )

                                class SponsorPickView(discord.ui.View):
                                    def __init__(self, on_selected):
                                        super().__init__(timeout=60)
                                        self.on_selected = on_selected
                                        self.select = discord.ui.Select(
                                            placeholder="Choose a sponsor...",
                                            options=[
                                                discord.SelectOption(label=m.display_name[:100], value=str(m.id))
                                                for m in sponsor_members[:25]
                                            ],
                                        )
                                        self.select.callback = self._on_select
                                        self.add_item(self.select)

                                    async def _on_select(self, interaction: discord.Interaction):
                                        if interaction.user.id != ctx.author.id:
                                            await interaction.response.send_message("Not for you.", ephemeral=True)
                                            return
                                        sponsor_id = int(self.select.values[0])
                                        await interaction.message.delete()
                                        await sponsor_picker_msg.delete()
                                        await self.on_selected(sponsor_id)
                                        self.stop()

                                async def on_selected(sponsor_id):
                                    sponsor = ctx.guild.get_member(sponsor_id)
                                    await cog_ref._do_regteam_confirm(ctx, channel, slot, selected_member, sponsor)

                                await ctx.send(view=SponsorPickView(on_selected))
                            else:
                                selected_sponsor = sponsor_members[0] if sponsor_members else None
                                await cog_ref._do_regteam_confirm(ctx, channel, slot, selected_member, selected_sponsor)

                        async def interaction_check(self, interaction: discord.Interaction) -> bool:
                            if interaction.user.id != ctx.author.id:
                                await interaction.response.send_message("Not for you.", ephemeral=True)
                                return False
                            return True

                    await ctx.send(view=PlayerPickView())
                    return
            elif selected_player is None and not player_members and ctx.author in sponsor_members:
                selected_player = ctx.author
            if len(sponsor_members) > 1:
                prompt_msg = await ctx.send(
                    f"⚠️ **{channel.name}** has multiple sponsors. Which sponsor do you want to log for stats? (Slot {slot} — {slot_names[slot]}):\n"
                    + "\n".join(f"• {m.display_name}" for m in sponsor_members)
                )

                class SponsorPickView(discord.ui.View):
                    def __init__(self, on_selected):
                        super().__init__(timeout=60)
                        self.on_selected = on_selected
                        self.select = discord.ui.Select(
                            placeholder="Choose a sponsor...",
                            options=[
                                discord.SelectOption(label=m.display_name[:100], value=str(m.id))
                                for m in sponsor_members[:25]
                            ],
                        )
                        self.select.callback = self._on_select
                        self.add_item(self.select)

                    async def _on_select(self, interaction: discord.Interaction):
                        if interaction.user.id != ctx.author.id:
                            await interaction.response.send_message("Not for you.", ephemeral=True)
                            return
                        sponsor_id = int(self.select.values[0])
                        await interaction.message.delete()
                        await self.on_selected(sponsor_id)
                        self.stop()

                async def on_selected(sponsor_id):
                    sponsor = ctx.guild.get_member(sponsor_id)
                    await cog_ref._do_regteam_confirm(ctx, channel, slot, selected_player, sponsor)

                await ctx.send(view=SponsorPickView(on_selected))
                return
            selected_sponsor = sponsor_members[0] if len(sponsor_members) == 1 else None
            await self._do_regteam_confirm(ctx, channel, slot, selected_player, selected_sponsor)
        else:
            if not is_admin:
                await ctx.send("Only administrators can set team for another channel.")
                return
            if len(sponsor_members) > 1:
                prompt_msg = await ctx.send(
                    f"⚠️ **{channel.name}** has multiple sponsors. Which sponsor do you want to log for stats? (Slot {slot} — {slot_names[slot]}):\n"
                    + "\n".join(f"• {m.display_name}" for m in sponsor_members)
                )

                class SponsorPickView(discord.ui.View):
                    def __init__(self, on_selected):
                        super().__init__(timeout=60)
                        self.on_selected = on_selected
                        self.select = discord.ui.Select(
                            placeholder="Choose the Library Sponsor...",
                            options=[
                                discord.SelectOption(label=m.display_name[:100], value=str(m.id))
                                for m in sponsor_members[:25]
                            ],
                        )
                        self.select.callback = self._on_select
                        self.add_item(self.select)

                    async def _on_select(self, interaction: discord.Interaction):
                        if interaction.user.id != ctx.author.id:
                            await interaction.response.send_message("Not for you.", ephemeral=True)
                            return
                        sponsor_id = int(self.select.values[0])
                        await interaction.message.delete()
                        await self.on_selected(sponsor_id)
                        self.stop()

                async def on_selected(sponsor_id):
                    sponsor = ctx.guild.get_member(sponsor_id)
                    await self._do_regteam_confirm(ctx, channel, slot, None, sponsor)

                await ctx.send(view=SponsorPickView(on_selected))
                return
            elif len(sponsor_members) == 1:
                await self._do_regteam_confirm(ctx, channel, slot, None, sponsor_members[0])
            else:
                await self._do_regteam_confirm(ctx, channel, slot, None, None)

    async def _do_regteam_self_picked(self, ctx, channel, slot, selected_member, sponsor_members, is_admin=False):
        """Handle when a player was picked from the dropdown (no alive role case)."""
        slot_names = {1: "Village", 2: "Evil", 3: "Rk", 4: "Neutral", 5: "Bonus/Extra"}
        if len(sponsor_members) > 1:
            picker_msg = await ctx.send(
                f"⚠️ Multiple sponsors found in {channel.mention}. Which sponsor for Slot {slot} ({slot_names[slot]})?\n"
                + "\n".join(f"• {m.display_name}" for m in sponsor_members)
            )

            class SponsorPickView(discord.ui.View):
                def __init__(self, on_selected):
                    super().__init__(timeout=60)
                    self.on_selected = on_selected
                    self.select = discord.ui.Select(
                        placeholder="Choose a sponsor...",
                        options=[
                            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
                            for m in sponsor_members[:25]
                        ],
                    )
                    self.select.callback = self._on_select
                    self.add_item(self.select)

                async def _on_select(self, interaction: discord.Interaction):
                    if interaction.user.id != ctx.author.id:
                        await interaction.response.send_message("Not for you.", ephemeral=True)
                        return
                    sponsor_id = int(self.select.values[0])
                    await interaction.message.delete()
                    await picker_msg.delete()
                    sponsor = ctx.guild.get_member(sponsor_id)
                    await self.on_selected(sponsor)
                    self.stop()

            async def on_selected(sponsor):
                await self._do_regteam_confirm(ctx, channel, slot, selected_member, sponsor)

            await ctx.send(view=SponsorPickView(on_selected))
        elif len(sponsor_members) == 1:
            await self._do_regteam_confirm(ctx, channel, slot, selected_member, sponsor_members[0])
        else:
            await self._do_regteam_confirm(ctx, channel, slot, selected_member, None)

    async def _do_regteam_confirm(self, ctx, channel, slot, player_member, sponsor_member):
        guild_data = self._guild_data(ctx.guild)
        slot_names = {1: "Village", 2: "Evil", 3: "Rk", 4: "Neutral", 5: "Bonus/Extra"}

        p = self._normalize_player_info(player_member)
        s = self._normalize_player_info(sponsor_member)
        player_name = p["name"]
        sponsor_name = s["name"]

        confirm_msg = await ctx.send(
            f"⚠️ Set **{channel.mention}** → **Slot {slot} ({slot_names[slot]})**\n"
            f"Player: **{player_name}**\n"
            f"Sponsor: **{sponsor_name}**\n\n"
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

        try:
            await confirm_msg.delete()
            await response.delete()
        except discord.HTTPException:
            pass

        guild_data.setdefault("channel_slots", {})[str(channel.id)] = {
            "slot": slot,
            "player_name": player_name,
            "player_id": p["id"],
            "sponsor_name": sponsor_name,
            "sponsor_id": s["id"],
        }
        if p["id"]:
            guild_data.setdefault("player_slots", {})[p["id"]] = slot
        save_guild_data(ctx.guild.id, guild_data)

        await ctx.send(embed=success_embed(
            title="Team Slot Assigned",
            description=f"**{channel.name}** → Slot {slot} ({slot_names[slot]})\n"
            f"Player: **{player_name}**\n"
            f"Sponsor: **{sponsor_name}**"
        ))

    @commands.command(name="reviewteams")
    async def reviewteams(self, ctx: commands.Context):
        if not await self._require_admin(ctx):
            return
        if not await self._require_overseer(ctx):
            return
        guild_data = self._guild_data(ctx.guild)
        packages = get_role_packages(ctx.guild.id)
        if not packages:
            await ctx.send("No Role Packages registered.")
            return
        channel_slots = guild_data.get("channel_slots", {})
        slot_names = {1: "Village", 2: "Evil", 3: "Rk", 4: "Neutral", 5: "Bonus/Extra"}

        by_team: dict[int, list] = {1: [], 2: [], 3: [], 4: [], 5: []}
        unassigned = []

        for package in packages:
            channel = ctx.guild.get_channel(package["channel_id"])
            ch_name = channel.mention if channel else f"ID {package['channel_id']}"

            stored_info = self._get_channel_slot_info(channel_slots, channel.id)
            stored_slot = self._get_channel_slot(channel_slots, channel.id)

            player_name = _clean_visual_name(_escape_md(stored_info.get("player_name", "Unknown"))) if stored_info else "Unknown"
            sponsor_name = _clean_visual_name(_escape_md(stored_info.get("sponsor_name", "—"))) if stored_info else "—"
            team_slot = stored_slot

            entry = f"🔹 **{ch_name}** — {player_name} + {sponsor_name}"
            if team_slot:
                by_team[team_slot].append(entry)
            else:
                unassigned.append(entry)

        MAX_EMBED = MAX_EMBED_DESC
        pages: list[str] = []
        current_page = ""
        current_chars = 0

        def start_new_page():
            nonlocal current_page, current_chars
            if current_page:
                pages.append(current_page)
            current_page = ""
            current_chars = 0

        def add_section(title: str, entries: list[str]):
            nonlocal current_page, current_chars
            section_header = f"**{title}**\n"
            section_lines = "\n".join(entries)
            section_full = section_header + section_lines
            section_chars = len(section_full)

            if section_chars > MAX_EMBED:
                if current_page:
                    start_new_page()
                chunk_header = section_header
                chunk_lines = []
                chunk_chars = len(chunk_header)
                for line in entries:
                    line_chars = len(line) + 1
                    if chunk_chars + line_chars > MAX_EMBED:
                        pages.append(chunk_header + "\n".join(chunk_lines))
                        chunk_lines = [line]
                        chunk_chars = len(chunk_header) + line_chars
                    else:
                        chunk_lines.append(line)
                        chunk_chars += line_chars
                if chunk_lines:
                    pages.append(chunk_header + "\n".join(chunk_lines))
                return

            if current_chars + section_chars + 2 > MAX_EMBED:
                start_new_page()
            current_page += ("\n\n" if current_page else "") + section_full
            current_chars += section_chars + (2 if current_page != section_full else 0)

        for slot_num in range(1, 6):
            entries = by_team[slot_num]
            if entries:
                add_section(f"{slot_names[slot_num]} Team ({len(entries)})", entries)

        if unassigned:
            add_section(f"Unassigned ({len(unassigned)})", unassigned)

        if current_page:
            pages.append(current_page)

        if not pages:
            await ctx.send("No role packages to review.")
            return

        for i, page_text in enumerate(pages):
            await ctx.send(embed=info_embed(
                title="Team Review" + (f" ({i + 1}/{len(pages)})" if len(pages) > 1 else ""),
                description=page_text
            ))

    @commands.command(name="ps", aliases=["playerspons"])
    async def ps(self, ctx: commands.Context):
        """Show a randomized list of players & their sponsors (team tags hidden so pairings can't be inferred).

        Only includes entries where at least one of the player or their sponsor currently holds the Alive role.
        Uses the same data as `.reviewteams` but strips all team/slot info and shuffles the order."""
        guild_data = self._guild_data(ctx.guild)
        packages = get_role_packages(ctx.guild.id)
        if not packages:
            await ctx.send("No Role Packages registered.")
            return

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))

        def _member_by_id(member_id):
            if not member_id:
                return None
            try:
                return ctx.guild.get_member(int(member_id))
            except (TypeError, ValueError):
                return None

        def _verified_alive(member):
            if alive_role is None:
                return True
            return member is not None and alive_role in member.roles

        channel_slots = guild_data.get("channel_slots", {})

        entries = []
        for package in packages:
            channel = ctx.guild.get_channel(package["channel_id"])
            if channel is None:
                continue
            ch_name = channel.mention

            stored_info = self._get_channel_slot_info(channel_slots, channel.id)
            if not stored_info:
                continue

            player_name = _clean_visual_name(_escape_md(stored_info.get("player_name", "Unknown")))
            sponsor_name = _clean_visual_name(_escape_md(stored_info.get("sponsor_name", "—")))

            if not _verified_alive(_member_by_id(stored_info.get("player_id"))) and not _verified_alive(_member_by_id(stored_info.get("sponsor_id"))):
                continue

            entries.append(f"🔹 **{ch_name}** — {player_name} + {sponsor_name}")

        if not entries:
            await ctx.send("No player/sponsor packages to review.")
            return

        random.shuffle(entries)

        pages: list[str] = []
        current_page = ""
        current_chars = 0
        for line in entries:
            line_chars = len(line) + 1
            if current_chars + line_chars > MAX_EMBED_DESC:
                pages.append(current_page)
                current_page = line
                current_chars = line_chars
            else:
                current_page += ("\n" if current_page else "") + line
                current_chars += line_chars
        if current_page:
            pages.append(current_page)

        for i, page_text in enumerate(pages):
            await ctx.send(embed=info_embed(
                title="Players & Sponsors" + (f" ({i + 1}/{len(pages)})" if len(pages) > 1 else ""),
                description=page_text
            ))

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
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
            confirm_msg = await ctx.send(
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
            try:
                await confirm_msg.delete()
                await response.delete()
            except discord.HTTPException:
                pass
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
            await interaction.response.send_message("❌ No Role Package registered for this channel. Use `.role register <n> <role name>` first.", ephemeral=True)
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

    async def _role_check_display(self, ctx, target_channel, guild_data, package, channel_slots):
        """Build and send the role check display for a channel."""
        slot_info = self._get_channel_slot_info(channel_slots, target_channel.id)

        pin_count = len(package.get("package_ids", [])) if package else 0
        role_name = package.get("role_name") if package else None
        card_id = package.get("card_id") if package else None

        missing: list[str] = []
        fix_commands: list[str] = []

        if pin_count < 1:
            missing.append("Pinned messages (0/4)")
        if not role_name:
            missing.append("Role name")
            fix_commands.append("`.role register <1-4> <role name>` — register pins & set role name")
        if not card_id:
            missing.append("Card")
            fix_commands.append("`.role registercard <message_id>` — register the card")
        if not slot_info or not slot_info.get("slot"):
            missing.append("Team")
            fix_commands.append("`.role regteam <1-5> [@player] [@sponsor]` — assign team slot")
        elif not slot_info or not slot_info.get("player_name"):
            missing.append("Player")
            fix_commands.append("`.role regteam <1-5> @player` — set player name")
        elif not slot_info or not slot_info.get("sponsor_name"):
            missing.append("Sponsor")
            fix_commands.append("`.role regteam <1-5> @player @sponsor` — set sponsor name")

        is_complete = len(missing) == 0

        slot_names = {1: "Village", 2: "Evil", 3: "Rk", 4: "Neutral", 5: "Bonus/Extra"}
        team_display = "—"
        if slot_info and slot_info.get("slot"):
            slot = slot_info["slot"]
            team_display = f"{slot_names.get(slot, 'Unknown')} (Slot {slot})"

        player_display = slot_info.get("player_name", "—") if slot_info else "—"
        sponsor_display = slot_info.get("sponsor_name", "—") if slot_info else "—"
        card_status = "✅ Registered" if card_id else "❌ Missing"

        status_emoji = "✅" if is_complete else "❌"
        status_text = "COMPLETE" if is_complete else "INCOMPLETE"

        description_lines = [
            f"**👤 Role:** {role_name or '—'}",
            f"**🏷️ Team:** {team_display}",
            f"**👤 Player:** {player_display}",
            f"**🎁 Sponsor:** {sponsor_display}",
            f"**📌 Pins:** {pin_count}/4 {'✅' if pin_count >= 1 else '❌'}",
            f"**🎴 Card:** {card_status}",
        ]

        embed = discord.Embed(
            title=f"Role Package Check: {target_channel.name}",
            description="\n".join(description_lines),
            color=0x2ecc71 if is_complete else 0xe74c3c,
        )
        embed.add_field(
            name=f"Status: {status_emoji} {status_text}",
            value=f"Missing: {', '.join(missing)}" if missing else "All items present",
            inline=False,
        )
        if fix_commands:
            embed.add_field(
                name="💡 Fix with:",
                value="\n".join(fix_commands),
                inline=False,
            )

        await ctx.send(embed=embed)

        if card_id and ctx.author.guild_permissions.administrator:
            try:
                card = await target_channel.fetch_message(int(card_id))
                await ctx.send(
                    content=card.content or None,
                    embeds=card.embeds if card.embeds else [],
                    files=[await attachment.to_file() for attachment in card.attachments],
                )
            except (discord.NotFound, discord.HTTPException):
                await ctx.send("⚠️ Card message could not be retrieved.")

    @role.command(name="check")
    async def role_check(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Check the completeness of a role package. Use without arguments in your RC, or specify a channel (admin only)."""
        guild_data = self._guild_data(ctx.guild)
        if not guild_data:
            await ctx.send("❌ Guild data is not loaded.")
            return

        target = channel or ctx.channel

        if channel is None:
            if not ctx.author.guild_permissions.administrator:
                if not self._is_role_chat(ctx.channel, guild_data):
                    await ctx.send("❌ This command must be used in a Role Chat channel.")
                    return
                await self._role_check_display(ctx, target, guild_data, get_role_package(target.id), guild_data.get("channel_slots", {}))
                return
            if not await self._require_overseer(ctx):
                return
            confirm_msg = await ctx.send(
                f"⚠️ Are you sure you want to check **{target.name}**?\n"
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
            try:
                await confirm_msg.delete()
                await response.delete()
            except discord.HTTPException:
                pass
            await self._role_check_display(ctx, target, guild_data, get_role_package(target.id), guild_data.get("channel_slots", {}))
        else:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ Only administrators can check another channel.")
                return
            if not await self._require_overseer(ctx):
                return
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
            confirm_msg = await ctx.send(
                f"⚠️ Are you sure you want to check the Role Package for {target.mention}?\n"
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
            try:
                await confirm_msg.delete()
                await response.delete()
            except discord.HTTPException:
                pass
            await self._role_check_display(ctx, target, guild_data, get_role_package(target.id), guild_data.get("channel_slots", {}))

    @role.command(name="help")
    async def role_help(self, ctx: commands.Context):
        """Explain the Role Package workflow (starts at Stage 1)."""
        pages = [
            info_embed(
                title="🧩 Stage 1 · Registration (in your Role Chat)",
                description=(
                    "**Step 1 — Pin your role messages**\n"
                    "Make sure the **first `<n>` pinned messages** are only the messages describing your role (up to 4). The bot reads the top `<n>` pins.\n\n"
                    "**Step 2 — Register your role**\n"
                    "In your **Role Chat**, run:\n"
                    "`.role register <n> <role name>`\n"
                    "Example: `.role register 2 The Clown Killer`\n\n"
                    "**Step 3 — Add your Role Card**\n"
                    "Reply to the card image with `.role registercard`, or use `.role registercard <message_id>`.\n\n"
                    "**Step 4 — Choose your team slot**\n"
                    "In your **Role Chat**, run:\n"
                    "`.role regteam [1-5]`\n"
                    "The bot auto-detects player + sponsor when possible.\n\n"
                    "**Team Slots:** `1` Village · `2` Evil · `3` Rk · `4` Neutral · `5` Bonus\n\n"
                    "**Need to specify manually?**\n"
                    "`.role regteam [1-5] @player` — specify player only if no sponsor\n"
                    "`.role regteam [1-5] @player @sponsor` — specify both\n\n"
                    "**Check:** `.role` · `.role card` · `.role check`\n"
                ),
            ),
            info_embed(
                title="🧩 Stage 2 · Publishing (admin only)",
                description=(
                    "**Step 0 — Set logging server** *(one-time setup)*\n"
                    "`.setlogserver <channel_id>` — set where role archives are posted\n"
                    "Right-click the channel → Copy Channel ID. The bot must be in the target server.\n"
                    "Run this once per game server.\n\n"
                    "**Step 1 — Review first**\n"
                    "`.reviewteams` — see all RCs and which are missing teams\n"
                    "`.reviewroles` — check what needs fixing; incomplete RCs get `-x` suffix, complete ones get it removed\n\n"
                    "**Step 2 — Build the draft**\n"
                    "`.publishroles [game_number] [game_name]`\n"
                    "Only succeeds if all packages are clean (card, player, team set, no duplicate sponsors).\n"
                    "Fix issues and re-run until it succeeds.\n\n"
                    "**Step 3 — Publish**\n"
                    "`.approvepublish` — archives the roles to the logging server."
                ),
            ),
            info_embed(
                title="🧩 Stage 3 · Import (admin only)",
                description=(
                    "**Step 1 — Import into the stats library**\n"
                    "The draft from Stage 2 already contains your game number/name — no channel setup or republish needed.\n"
                    "Run in **any** channel:\n"
                    "`.libimport` — English (Hearthside) library\n"
                    "`.libitimport` — Italian (The Village) library\n\n"
                    "⚠️ **Do not restart the bot** between `.approvepublish` and `.libimport`!\n"
                    "The draft (including game number/name from `.publishroles`) is stored in memory and will be lost."
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

        await ctx.send("⏳ Processing role packages...")
        guild_data = self._guild_data(ctx.guild)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        channel_slots = guild_data.get("channel_slots", {})
        all_players: dict[int, list[tuple[str, int]]] = {}  # player_id -> [(channel_name, channel_id), ...]
        for package in packages:
            channel = ctx.guild.get_channel(package["channel_id"])
            if not channel:
                continue
            stored_info = self._get_channel_slot_info(channel_slots, channel.id)
            if stored_info and stored_info.get("player_id"):
                pid = int(stored_info["player_id"])
                all_players.setdefault(pid, []).append((channel.name, channel.id))

        duplicate_issues = []
        for player_id, channels in all_players.items():
            if len(channels) > 1:
                ch_names = ", ".join(f"#{ch[0]}" for ch in channels)
                member = ctx.guild.get_member(player_id)
                name = member.display_name if member else f"ID {player_id}"
                duplicate_issues.append(f"Duplicate player **{name}** in: {ch_names}")

        draft = RoleDraft(ctx.guild.id, game_number=game_number, game_name=game_name)
        all_issues: list[str] = []

        for package in packages:
            channel = ctx.guild.get_channel(package["channel_id"])
            issues = []
            if not channel:
                continue
            messages, missing = await self._fetch_package_messages(channel, package)
            if missing:
                issues.append(f"{channel.name}: Registered message deleted ({len(missing)} message(s) not found)")
                draft.roles.append(DraftRole(
                    channel_id=channel.id,
                    role_name=package.get("role_name") or channel.name,
                    team=None,
                    player_name=None,
                    player_id=None,
                    descriptions=[None]*4,
                    package=package,
                    issues=issues,
                ))
                all_issues.extend(issues)
                continue
            if not package.get("card_id"):
                issues.append(f"{channel.name}: Role Card missing")
            stored_info = self._get_channel_slot_info(channel_slots, channel.id)
            if stored_info and stored_info.get("player_name") and stored_info.get("player_name") not in ("Unknown", "❌ Unknown"):
                player_name = stored_info.get("player_name")
                player_id = stored_info.get("player_id")
                member = channel.guild.get_member(int(player_id)) if player_id else None
                if member:
                    player_name = member.name
            else:
                player = self._resolve_player(channel, guild_data)
                is_stored = isinstance(player, dict)
                player_name = player.get("player_name") if is_stored else (player.name if player else None)
                player_id = player.get("player_id") if is_stored else (player.id if player else None)
            if not player_name:
                issues.append(f"{channel.name}: Player unresolved")
                team = None
            else:
                team = self._team_from_slots(guild_data, int(player_id) if player_id else 0, channel.id)
                if team is None:
                    issues.append(f"{channel.name}: Team not set (use `.role regteam` first)")
            stored_sponsor_info = self._get_channel_slot_info(channel_slots, channel.id)
            sponsors = [(stored_sponsor_info["sponsor_name"], stored_sponsor_info["sponsor_id"])] if stored_sponsor_info and stored_sponsor_info.get("sponsor_name") else []
            library_sponsor = sponsors[0] if sponsors else None
            descriptions = self._compile_descriptions(messages)
            role = DraftRole(
                channel_id=channel.id,
                role_name=package.get("role_name") or (self._role_name(channel, messages) if messages else channel.name),
                team=team,
                player_name=player_name,
                player_id=int(player_id) if player_id else None,
                sponsors=sponsors,
                library_sponsor=library_sponsor,
                descriptions=descriptions,
                package=package,
                card_message_id=package.get("card_id"),
                issues=issues,
            )
            draft.roles.append(role)
            all_issues.extend(issues)

        if duplicate_issues:
            for di in duplicate_issues:
                await ctx.send(f"❌ {di}")

        if all_issues:
            slot_names = {1: "Village", 2: "Evil", 3: "Rk", 4: "Neutral", 5: "Bonus/Extra"}
            issue_by_channel = {}
            for issue in all_issues:
                parts = issue.split(":", 1)
                ch_name = parts[0] if len(parts) > 1 else issue
                if ch_name not in issue_by_channel:
                    issue_by_channel[ch_name] = []
                issue_by_channel[ch_name].append(issue)
            lines = []
            for ch, ch_issues in issue_by_channel.items():
                lines.append(f"**{ch}**: {', '.join(ch_issues)}")
            await ctx.send(
                f"❌ Publishing blocked — **{len(all_issues)}** issue(s) across **{len(issue_by_channel)}** channel(s):\n\n" + "\n".join(f"  • {l}" for l in lines)
            )
            return

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
        await ctx.send(embed=success_embed(
            title="Draft Ready",
            description=f"**{len(draft.roles)}** role(s) — all clean.\n"
            f"Game: **{draft.game_number}│ {draft.game_name}**\n\n"
            "Use `.reviewroles` and `.reviewteams` to verify, then `.approvepublish`."
        ))

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
            lines.append(f"{channel.mention if channel else role.channel_id} — {role.role_name}\nUse `.resolveplayer #{channel.name if channel else 'channel'} @player`")
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
        if not await self._require_overseer(ctx):
            return
        guild_data = self._guild_data(ctx.guild)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        all_packages = {p["channel_id"]: p for p in get_role_packages(ctx.guild.id)}
        channel_slots = guild_data.get("channel_slots", {})
        slot_names = {1: "Village", 2: "Evil", 3: "Rk", 4: "Neutral", 5: "Bonus/Extra"}

        all_channels: list[discord.TextChannel] = []
        for category_name in (guild_data.get("rc_category_name"), guild_data.get("dead_rc_category_name")):
            category = discord.utils.get(ctx.guild.categories, name=category_name)
            if category:
                all_channels.extend(category.text_channels)

        if not all_channels:
            await ctx.send("No Role Chat channels found.")
            return

        entries = []
        for channel in all_channels:
            package = all_packages.get(channel.id)
            ch_name = channel.mention
            package_ok = bool(package.get("package_ids")) if package else False
            card_ok = bool(package.get("card_id")) if package else False
            role_name = package.get("role_name") if package else None

            stored_info = self._get_channel_slot_info(channel_slots, channel.id)
            stored_slot = self._get_channel_slot(channel_slots, channel.id)

            player_name = _escape_md(stored_info.get("player_name", "❌ Unknown")) if stored_info else "❌ Unknown"
            sponsor_name_display = _escape_md(stored_info.get("sponsor_name", "—")) if stored_info else "—"

            team_slot = stored_slot
            team_name = slot_names.get(team_slot, "❌ Not set") if team_slot else "❌ Not set"
            issues = []
            if not package_ok:
                issues.append("No package")
            if not role_name:
                issues.append("No role name")
            if not card_ok:
                issues.append("No card")
            if not team_slot:
                issues.append("No team")
            issues_str = ", ".join(issues) or "None"
            line = (
                f"**{ch_name}**\n"
                f"Role: {_escape_md(role_name) or '❌ Not set'}\n"
                f"Player: {player_name}\n"
                f"Team: {team_name}\n"
                f"Sponsor: {sponsor_name_display}\n"
                f"Package: {'✅' if package_ok else '❌'} | Card: {'✅' if card_ok else '❌'}\n"
                f"Issues: {issues_str}"
            )
            entries.append((len(issues), line))
        entries.sort(key=lambda x: x[0], reverse=True)
        lines = [e[1] for e in entries]
        for start in range(0, len(lines), 5):
            await ctx.send(embed=info_embed(title=f"Role Review ({start + 1}-{min(start + 5, len(lines))}/{len(lines)})", description="\n\n".join(lines[start:start + 5])))

        suffix = CHANNEL_INCOMPLETE_SUFFIX

        for channel in all_channels:
            package = all_packages.get(channel.id)
            package_ok = bool(package.get("package_ids")) if package else False
            card_ok = bool(package.get("card_id")) if package else False
            role_name = package.get("role_name") if package else None
            stored_info = self._get_channel_slot_info(channel_slots, channel.id)
            stored_slot = self._get_channel_slot(channel_slots, channel.id)
            is_complete = package_ok and card_ok and role_name and stored_slot

            current_name = channel.name
            normalized = current_name.replace("-", " ").rstrip()

            stripped = re.sub(r'(\s*[xX])+$', '', normalized).rstrip()
            has_suffix = stripped != normalized.rstrip()
            base_name = stripped.replace(" ", "-")

            if is_complete:
                if has_suffix:
                    try:
                        await channel.edit(name=base_name)
                    except discord.HTTPException:
                        pass
            else:
                if not has_suffix:
                    try:
                        await channel.edit(name=base_name + "-x")
                    except discord.HTTPException:
                        pass

            await asyncio.sleep(0.5)

    @commands.command(name="approvepublish")
    async def approvepublish(self, ctx: commands.Context):
        if not await self._require_admin(ctx):
            return
        guild_data = self._guild_data(ctx.guild)
        draft = self.drafts.get(ctx.guild.id)
        if not draft or not guild_data:
            await ctx.send("❌ No draft exists or guild data is not loaded.")
            return

        await ctx.send("⏳ Publishing to logging server...")
        slot_names = {1: "Village", 2: "Evil", 3: "Rk", 4: "Neutral", 5: "Bonus/Extra"}
        issues = []
        for role in draft.roles:
            reason = None
            if role.issues:
                reason = ", ".join(role.issues)
            elif not role.player_name:
                reason = "No player assigned"
            elif role.team is None:
                reason = "No team slot assigned"
            if reason:
                channel = ctx.guild.get_channel(role.channel_id)
                ch_name = f"#{channel.name}" if channel else f"ID {role.channel_id}"
                team_label = slot_names.get(role.team, "Not set") if role.team is not None else "❌ Not set"
                player_info = f"{role.player_name} ({role.player_id})" if role.player_name and role.player_id else (role.player_name or "❌ No player")
                sponsor_info = role.library_sponsor[0] if role.library_sponsor else "—"
                pkg_ids = bool(role.package.get("package_ids")) if role.package else False
                card_id = bool(role.card_message_id) if role.card_message_id else False
                issues.append(
                    f"**Channel:** {ch_name}\n"
                    f"**Role:** {role.role_name or 'Unknown'}\n"
                    f"**Player:** {player_info}\n"
                    f"**Team:** {team_label}\n"
                    f"**Sponsor:** {sponsor_info}\n"
                    f"**Package:** {'✅' if pkg_ids else '❌'} | **Card:** {'✅' if card_id else '❌'}\n"
                    f"**❌ Issue:** {reason}"
                )
        if issues:
            await ctx.send(embed=error_embed(title=f"Publishing Blocked — {len(issues)} issue(s)", description="\n\n".join(issues)))
            return
        draft.approved = True
        await self._publish_logging_archive(ctx, draft, guild_data)
        await ctx.send(embed=success_embed(title="Publishing Complete", description=f"Game {draft.game_number or 'pending'} archive published."))

    @commands.command(name="setlogserver")
    async def setlogserver(self, ctx: commands.Context, channel_id_arg: str):
        """Set the logging server and channel for role package archives. Usage: .setlogserver <channel_id>"""
        if not await self._require_admin(ctx):
            return
        guild_data = self._guild_data(ctx.guild)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        try:
            channel_id = int(channel_id_arg.strip())
        except ValueError:
            await ctx.send("❌ Invalid channel ID. Provide a numeric channel ID.")
            return
        try:
            channel = await self.bot.fetch_channel(channel_id)
        except discord.NotFound:
            await ctx.send(f"❌ Channel with ID `{channel_id}` not found. Make sure the bot has access to that channel.")
            return
        except discord.HTTPException:
            await ctx.send(f"❌ Failed to fetch channel. Try again.")
            return
        if not isinstance(channel, discord.TextChannel):
            await ctx.send("❌ That is not a text channel.")
            return
        guild_data["role_package_logging_guild_id"] = str(channel.guild.id)
        guild_data["role_package_logging_channel_id"] = channel.id
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(embed=success_embed(
            title="Logging Server Set",
            description=f"Role archives will be published to **{channel.guild.name}** → **#{channel.name}**"
        ))

    async def _publish_logging_archive(self, ctx: commands.Context, draft: RoleDraft, guild_data: dict):
        guild_id = guild_data.get("role_package_logging_guild_id")
        channel_id = guild_data.get("role_package_logging_channel_id")
        if not guild_id or not channel_id:
            raise RuntimeError("Logging server is not configured.")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            raise RuntimeError("Logging server guild could not be found. Make sure the bot is in that server.")
        channel = discord.utils.get(guild.text_channels, id=int(channel_id))
        if not channel:
            raise RuntimeError(f"Logging server channel with ID **{channel_id}** could not be found.")
        for team_number, team_name in TEAM_NAMES.items():
            team_roles = [role for role in draft.roles if role.team == team_number]
            if not team_roles:
                continue
            header = await channel.send(f"# {team_name} Team")
            try:
                await header.pin()
                await asyncio.sleep(0.5)
                async for recent in channel.history(limit=3, after=header.created_at):
                    if recent.type == discord.MessageType.pins_add:
                        await recent.delete()
            except discord.HTTPException:
                pass
            for role in team_roles:
                text = "\n\n".join(value for value in role.descriptions if value)
                meta = f"Played by {role.player_name}"
                if role.sponsors:
                    meta += "\nSponsored by " + ", ".join(name for name, _ in role.sponsors)
                if text:
                    for i in range(0, len(text), 1950):
                        await channel.send(text[i:i+1950])
                await channel.send(meta)
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

    @staticmethod
    def _draft_to_role_records(draft: RoleDraft) -> list[dict]:
        """Convert a RoleDraft into library import records (used by libimport/libitimport)."""
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
        return roles

    @commands.command(name="libimport")
    async def libimport(self, ctx: commands.Context):
        if ctx.author.id not in LIBRARIAN_IDS:
            await ctx.send("❌ Only Librarians can use this command.")
            return
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

        confirm_msg = await ctx.send(
            "⚠️ **Confirm Import to English Library (Hearthside)**\n\n"
            f"This will import **{len(draft.roles)}** role(s) into **{draft.game_number}│ {draft.game_name}**\n"
            "in the **English (Hearthside) stats library**.\n\n"
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

        try:
            await confirm_msg.delete()
            await response.delete()
        except discord.HTTPException:
            pass

        roles = self._draft_to_role_records(draft)
        try:
            imported = self.library_db.import_roles_atomic(draft.game_number, draft.game_name, roles)
        except Exception as exc:
            await ctx.send(embed=error_embed(title="Library Import Failed", description=f"The transaction was rolled back.\n\n`{exc}`"))
            return
        await ctx.send(embed=success_embed(title="Library Import Complete", description=f"Imported {imported} role(s) into {draft.game_number}│ {draft.game_name}."))

    @commands.command(name="libitimport")
    async def libitimport(self, ctx: commands.Context):
        if ctx.author.id not in LIBRARIAN_IDS:
            await ctx.send("❌ Only Librarians can use this command.")
            return
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

        confirm_msg = await ctx.send(
            "⚠️ **Confirm Import to Italian Library (The Village)**\n\n"
            f"This will import **{len(draft.roles)}** role(s) into **{draft.game_number}│ {draft.game_name}**\n"
            "in the **Italian (The Village) stats library**.\n\n"
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

        try:
            await confirm_msg.delete()
            await response.delete()
        except discord.HTTPException:
            pass

        roles = self._draft_to_role_records(draft)
        try:
            imported = self.library_db_it.import_roles_atomic(draft.game_number, draft.game_name, roles)
        except Exception as exc:
            await ctx.send(embed=error_embed(title="Italian Library Import Failed", description=f"The transaction was rolled back.\n\n`{exc}`"))
            return
        await ctx.send(embed=success_embed(title="Italian Library Import Complete", description=f"Imported {imported} role(s) into {draft.game_number}│ {draft.game_name}."))


async def setup(bot):
    await bot.add_cog(RolePackageCog(bot))
