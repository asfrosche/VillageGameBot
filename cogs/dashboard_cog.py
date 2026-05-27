import re
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands
from discord.ui import View, Button, Select

from cogs.actions_logging_cog import ActionButtons, CancelOnlyView
from cogs.data_utils import load_guild_data, save_guild_data
from utils.bot_db import (
    adjust_visits,
    get_actions_for_channel,
    get_role_abilities,
    get_role_dashboard,
    insert_action_log,
    modify_active_ability,
    modify_passive_ability,
    replace_active_abilities,
    replace_passive_abilities,
    set_visit_block,
    set_visits,
    upsert_role_dashboard,
)
from utils.embeds import info_embed, success_embed, error_embed, plain_embed


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _fmt_ts(dt) -> str:
    """Format datetime as dd-mm hh:mm:ss (UTC)."""
    if hasattr(dt, "strftime"):
        return dt.strftime("%d-%m %H:%M:%S")
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return dt.strftime("%d-%m %H:%M:%S")
        except Exception:
            return str(dt)[:16]
    return str(dt)[:19]


EMBED_COLOR_FUCSIA = 0xFF3FB9


def _get_current_house_names(guild: discord.Guild, guild_data: dict, rc_channel: discord.TextChannel) -> list[str]:
    """Return house channel names where the RC's members (alive/dead/alt) currently have send_messages."""
    houses_category = discord.utils.get(guild.categories, name=guild_data.get("houses_category_name"))
    if not houses_category:
        return []
    alive_role = discord.utils.get(guild.roles, name=guild_data.get("alive_role_name"))
    dead_role = discord.utils.get(guild.roles, name=guild_data.get("dead_role_name"))
    alt_role = discord.utils.get(guild.roles, name=guild_data.get("alt_role_name"))
    names = []
    for member in rc_channel.members:
        if (
            not (alive_role and alive_role in member.roles)
            and not (dead_role and dead_role in member.roles)
            and not (alt_role and alt_role in member.roles)
        ):
            continue
        for ch in houses_category.channels:
            if ch.permissions_for(member).send_messages and ch.name not in names:
                names.append(ch.name)
    return names


def _get_rc_channel(ctx: commands.Context, channel: Optional[discord.TextChannel]) -> discord.TextChannel:
    """Resolve the target RoleChat channel.

    Admins can target any channel. Non-admins are always restricted to their current channel.
    """
    if channel is not None and ctx.author.guild_permissions.administrator:
        return channel
    return ctx.channel


def _rc_categories(guild: discord.Guild, guild_data: dict) -> set:
    """Return the set of rolechat categories for this guild (may contain None entries — filter before use)."""
    return {
        discord.utils.get(guild.categories, name=guild_data.get("rc_category_name")),
        discord.utils.get(guild.categories, name=guild_data.get("alt_category_name")),
        discord.utils.get(guild.categories, name=guild_data.get("dead_rc_category_name")),
    }


def _is_overseer(interaction: discord.Interaction, guild_data: dict | None) -> bool:
    """Return True if the interaction user is an admin or has the overseer role."""
    if interaction.user.guild_permissions.administrator:
        return True
    if guild_data:
        os_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("overseer_role_name"))
        if os_role and os_role in interaction.user.roles:
            return True
    return False


# ─────────────────────────────────────────────
# Visit approval view
# ─────────────────────────────────────────────

class VisitApprovalView(View):
    def __init__(
        self,
        dashboard_cog: "Dashboard",
        guild_id: int,
        rc_channel_id: int,
        target_channel_id: int,
        requester_id: int,
        visit_type: str,
        house_name: str,
        rc_pending_message: Optional[discord.Message] = None,
        timeout: int = 86400,
    ):
        super().__init__(timeout=timeout)
        self.dashboard_cog = dashboard_cog
        self.guild_id = guild_id
        self.rc_channel_id = rc_channel_id
        self.target_channel_id = target_channel_id
        self.requester_id = requester_id
        self.visit_type = visit_type
        self.house_name = house_name
        self.message_id: int | None = None
        self.rc_pending_message = rc_pending_message

    async def _guard_overseer(self, interaction: discord.Interaction) -> bool:
        """Send an ephemeral error and return False if the user isn't an overseer/admin."""
        guild_data = load_guild_data(interaction.guild.id) if interaction.guild else None
        if not _is_overseer(interaction, guild_data):
            await interaction.response.send_message(
                "You don't have permission to manage visits.",
                ephemeral=True,
            )
            return False
        return True

    def _build_done_footer(self, interaction: discord.Interaction, symbol: str) -> str:
        return (
            f"{symbol} {'Done' if symbol == '✅' else 'Denied'} at "
            f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} "
            f"by {interaction.user.display_name}"
        )

    async def _update_embeds(
        self,
        interaction: discord.Interaction,
        color: int,
        footer_text: str,
    ) -> None:
        """Edit both the log embed and the RC pending embed to the resolved state."""
        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color(color)
            embed.set_footer(text=footer_text)
            embed.timestamp = None
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await interaction.response.edit_message(view=None)

        if self.rc_pending_message and self.rc_pending_message.embeds:
            emb = self.rc_pending_message.embeds[0]
            emb.color = discord.Color(color)
            emb.set_footer(text=footer_text)
            emb.timestamp = None
            try:
                await self.rc_pending_message.edit(embed=emb, view=None)
            except Exception:
                pass

    async def _perform_visit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or guild.id != self.guild_id:
            return await interaction.response.send_message(
                "This visit request is no longer valid (guild mismatch).",
                ephemeral=True,
            )

        guild_data = load_guild_data(guild.id)
        if not guild_data:
            return await interaction.response.send_message(
                "Guild data not loaded; cannot execute visit.",
                ephemeral=True,
            )

        rc_channel = guild.get_channel(self.rc_channel_id)
        target_channel = guild.get_channel(self.target_channel_id)
        if not isinstance(rc_channel, discord.TextChannel) or not isinstance(target_channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Channels for this visit no longer exist.",
                ephemeral=True,
            )

        from_house_names = _get_current_house_names(guild, guild_data, rc_channel)
        from_str = ", ".join(from_house_names) if from_house_names else "—"

        delta_normal = delta_forced = delta_stealth = 0
        if self.visit_type == "normal":
            delta_normal = -1
        elif self.visit_type == "forced":
            delta_forced = -1
        elif self.visit_type == "stealth":
            delta_stealth = -1

        dash = get_role_dashboard(guild.id, rc_channel.id)
        if dash:
            updated = adjust_visits(
                guild.id,
                rc_channel.id,
                delta_normal=delta_normal,
                delta_forced=delta_forced,
                delta_stealth=delta_stealth,
            )
            if not updated:
                return await interaction.response.send_message(
                    "Dashboard data not found for this channel; cannot execute visit.",
                    ephemeral=True,
                )

        moving_cog = self.dashboard_cog.bot.get_cog("Moving")
        if not moving_cog:
            if dash:
                adjust_visits(
                    guild.id,
                    rc_channel.id,
                    delta_normal=-delta_normal,
                    delta_forced=-delta_forced,
                    delta_stealth=-delta_stealth,
                )
            return await interaction.response.send_message(
                "Moving system not loaded; visit refunded." if dash else "Moving system not loaded.",
                ephemeral=True,
            )

        dummy_message = interaction.message
        ctx = await self.dashboard_cog.bot.get_context(dummy_message)
        ctx.channel = rc_channel
        ctx.author = interaction.user

        try:
            if self.visit_type == "normal":
                await moving_cog.process_knock(ctx, target_channel, guild_data)
            else:
                is_stealth = self.visit_type == "stealth"
                await moving_cog.process_move(ctx, target_channel, is_stealth=is_stealth, read_only=False)
        except Exception:
            if dash:
                adjust_visits(
                    guild.id,
                    rc_channel.id,
                    delta_normal=-delta_normal,
                    delta_forced=-delta_forced,
                    delta_stealth=-delta_stealth,
                )
            return await interaction.response.send_message(
                "Error executing visit. Visit refunded." if dash else "Error executing visit.",
                ephemeral=True,
            )

        try:
            insert_action_log(
                guild_id=guild.id,
                channel_id=rc_channel.id,
                player_id=self.requester_id,
                message=f"visit from {from_str} to {target_channel.name}",
                created_at=datetime.now(timezone.utc),
                marked_at=datetime.now(timezone.utc),
                marked_by_id=interaction.user.id,
            )
        except Exception:
            pass

        await self._update_embeds(
            interaction,
            color=0x00FF00,
            footer_text=self._build_done_footer(interaction, "✅"),
        )

    @discord.ui.button(label="Allow visit", style=discord.ButtonStyle.success, emoji="✅")
    async def allow_visit(self, interaction: discord.Interaction, button: Button):
        if not await self._guard_overseer(interaction):
            return
        await self._perform_visit(interaction)
        self.stop()

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_visit(self, interaction: discord.Interaction, button: Button):
        if not await self._guard_overseer(interaction):
            return
        await self._update_embeds(
            interaction,
            color=0xFF0000,
            footer_text=self._build_done_footer(interaction, "❌"),
        )
        self.stop()


# ─────────────────────────────────────────────
# Template regexes
# ─────────────────────────────────────────────

TEMPLATE_NAME_RE = re.compile(r"^Name:\s*(.+)$", re.IGNORECASE)
TEMPLATE_TEAM_RE = re.compile(r"^Team:\s*(.+)$", re.IGNORECASE)
TEMPLATE_VISITS_RE = re.compile(
    r"^Visits:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$",
    re.IGNORECASE,
)
TEMPLATE_PASSIVE_RE = re.compile(r"^Passive ability\s+\d+:\s*(.+)$", re.IGNORECASE)
TEMPLATE_ACTIVE_RE = re.compile(
    r"^Active ability\s+\d+:\s*([^,]+),\s*(.+)$",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────
# Dashboard UI view
# ─────────────────────────────────────────────

class DashboardView(View):
    def __init__(self, cog: "Dashboard", rc_channel: discord.TextChannel, invoker: discord.Member, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.rc_channel = rc_channel
        self.invoker = invoker

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.invoker:
            await interaction.response.send_message(
                "This dashboard isn't yours. Run `.dashboard` in your own RoleChat.",
                ephemeral=True,
            )
            return False
        if not interaction.user.guild_permissions.administrator:
            guild_data = load_guild_data(interaction.guild.id)
            if not guild_data:
                await interaction.response.send_message("Guild data not loaded.", ephemeral=True)
                return False
            allowed = _rc_categories(interaction.guild, guild_data)
            if self.rc_channel.category not in allowed:
                await interaction.response.send_message(
                    "You can only use dashboard buttons inside RoleChats.",
                    ephemeral=True,
                )
                return False
        return True

    @discord.ui.button(label="Action", style=discord.ButtonStyle.primary, emoji="📋")
    async def action_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await self.cog.handle_action_button(interaction, self.rc_channel)

    @discord.ui.button(label="Visit", style=discord.ButtonStyle.primary, emoji="🚪")
    async def visit_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await self.cog.handle_visit_button(interaction, self.rc_channel)

    @discord.ui.button(label="Preset", style=discord.ButtonStyle.success, emoji="🎟️")
    async def preset_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await self.cog.handle_preset_button(interaction, self.rc_channel)

    @discord.ui.button(label="Logging", style=discord.ButtonStyle.secondary, emoji="📜")
    async def logging_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await self.cog.handle_logging_button(interaction, self.rc_channel)


# ─────────────────────────────────────────────
# Dashboard cog
# ─────────────────────────────────────────────

class Dashboard(commands.Cog):
    """Per-role dashboard with visits, abilities, presets and logging."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    # Admin: settings & template
    # ------------------------------------------------------------------ #

    @commands.command(name="dashboardtoggle")
    @commands.has_permissions(administrator=True)
    async def dashboard_toggle(self, ctx: commands.Context, value: bool):
        """Enable or disable the dashboard system in this server."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        guild_data["dashboard_enabled"] = bool(value)
        save_guild_data(ctx.guild.id, guild_data)
        state = "enabled" if value else "disabled"
        embed = success_embed(
            title="Dashboard setting updated",
            description=f"Player dashboard has been **{state}** for this server.",
        )
        await ctx.send(embed=embed)

    @commands.command(name="setrole")
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """
        Configure a RoleChat using the template.

        Usage:
          1) Write the template as a message.
          2) Reply to it with `.setrole` (optionally `.setrole #rolechat`).
        """
        rc = _get_rc_channel(ctx, channel)
        if ctx.message.reference and ctx.message.reference.resolved:
            template_text = ctx.message.reference.resolved.content
        else:
            parts = ctx.message.content.split("\n", 1)
            if len(parts) < 2:
                return await ctx.send("Reply to a template message or include the template in the same message.")
            template_text = parts[1]

        lines = [line.strip() for line in template_text.splitlines() if line.strip()]
        name = None
        team = None
        visits = (0, 0, 0)
        passives: list[str] = []
        actives: list[tuple[str, str]] = []

        for line in lines:
            if (m := TEMPLATE_NAME_RE.match(line)):
                name = m.group(1).strip()
                continue
            if (m := TEMPLATE_TEAM_RE.match(line)):
                team = m.group(1).strip()
                continue
            if (m := TEMPLATE_VISITS_RE.match(line)):
                visits = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                continue
            if (m := TEMPLATE_PASSIVE_RE.match(line)):
                passives.append(m.group(1).strip())
                continue
            if (m := TEMPLATE_ACTIVE_RE.match(line)):
                category = m.group(1).strip()
                desc = m.group(2).strip()
                actives.append((category, desc))
                continue

        if not name or not team:
            return await ctx.send("Template must include at least `Name:` and `Team:`.")

        guild_id = ctx.guild.id
        channel_id = rc.id

        upsert_role_dashboard(
            guild_id,
            channel_id,
            name=name,
            team=team,
            visits_normal=visits[0],
            visits_forced=visits[1],
            visits_stealth=visits[2],
        )
        replace_passive_abilities(guild_id, channel_id, passives)
        replace_active_abilities(guild_id, channel_id, actives)

        embed = success_embed(
            title="Role configured",
            description=(
                f"Role dashboard for {rc.mention} has been updated.\n"
                f"**Name:** {name}\n"
                f"**Team:** {team}\n"
                f"**Visits:** normal={visits[0]}, forced={visits[1]}, stealth={visits[2]}"
            ),
        )
        await ctx.send(embed=embed)

    # Ability editing

    @commands.command(name="addpassiveability")
    @commands.has_permissions(administrator=True)
    async def add_passive_ability(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel],
        index: int,
        *,
        description: str,
    ):
        """Add or replace a passive ability at the given index."""
        rc = _get_rc_channel(ctx, channel)
        try:
            current = modify_passive_ability(
                ctx.guild.id,
                rc.id,
                index,
                new_description=description,
                remove=False,
            )
        except IndexError:
            passives, _ = get_role_abilities(ctx.guild.id, rc.id)
            if index != len(passives) + 1:
                return await ctx.send("Invalid index for passive ability.")
            passives.append(description)
            replace_passive_abilities(ctx.guild.id, rc.id, passives)
            current = passives

        embed = success_embed(
            title="Passive abilities updated",
            description="\n".join(f"{i+1}. {p}" for i, p in enumerate(current)) or "None",
        )
        await ctx.send(embed=embed)

    @commands.command(name="removepassiveability")
    @commands.has_permissions(administrator=True)
    async def remove_passive_ability(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel],
        index: int,
    ):
        """Remove a passive ability at the given index."""
        rc = _get_rc_channel(ctx, channel)
        try:
            current = modify_passive_ability(
                ctx.guild.id,
                rc.id,
                index,
                remove=True,
            )
        except IndexError:
            return await ctx.send("Invalid index for passive ability.")

        embed = success_embed(
            title="Passive abilities updated",
            description="\n".join(f"{i+1}. {p}" for i, p in enumerate(current)) or "None",
        )
        await ctx.send(embed=embed)

    @commands.command(name="addactiveability")
    @commands.has_permissions(administrator=True)
    async def add_active_ability(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel],
        index: int,
        *,
        payload: str,
    ):
        """
        Add or replace an active ability at the given index.

        Format: <category>, <description>
        """
        rc = _get_rc_channel(ctx, channel)
        if "," not in payload:
            return await ctx.send("Active ability format must be: `<category>, <description>`.")
        category, desc = [p.strip() for p in payload.split(",", 1)]
        try:
            current = modify_active_ability(
                ctx.guild.id,
                rc.id,
                index,
                new_category=category,
                new_description=desc,
                remove=False,
            )
        except IndexError:
            _, actives = get_role_abilities(ctx.guild.id, rc.id)
            if index != len(actives) + 1:
                return await ctx.send("Invalid index for active ability.")
            actives.append((category, desc))
            replace_active_abilities(ctx.guild.id, rc.id, actives)
            current = actives

        lines = [f"{i+1}. [{cat}] {text}" for i, (cat, text) in enumerate(current)]
        embed = success_embed(
            title="Active abilities updated",
            description="\n".join(lines) or "None",
        )
        await ctx.send(embed=embed)

    @commands.command(name="removeactiveability")
    @commands.has_permissions(administrator=True)
    async def remove_active_ability(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel],
        index: int,
    ):
        """Remove an active ability at the given index."""
        rc = _get_rc_channel(ctx, channel)
        try:
            current = modify_active_ability(
                ctx.guild.id,
                rc.id,
                index,
                remove=True,
            )
        except IndexError:
            return await ctx.send("Invalid index for active ability.")

        lines = [f"{i+1}. [{cat}] {text}" for i, (cat, text) in enumerate(current)]
        embed = success_embed(
            title="Active abilities updated",
            description="\n".join(lines) or "None",
        )
        await ctx.send(embed=embed)

    @commands.command(name="vb")
    @commands.has_permissions(administrator=True)
    async def visitblock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """
        Toggle visit blocking for a RoleChat.

        Usage: .vb #channel  (or just .vb inside the RoleChat)
        """
        rc = _get_rc_channel(ctx, channel)
        dash = get_role_dashboard(ctx.guild.id, rc.id)
        blocked = not dash["visit_blocked"] if dash else True
        set_visit_block(ctx.guild.id, rc.id, blocked)
        state = "blocked" if blocked else "unblocked"
        await ctx.send(f"Visits for {rc.mention} are now **{state}**.")

    @commands.command(name="checkvb")
    @commands.has_permissions(administrator=True)
    async def checkvb(self, ctx: commands.Context, channel: discord.TextChannel):
        """Check if visit block is active for a rolechat. Usage: .checkvb #channel"""
        dash = get_role_dashboard(ctx.guild.id, channel.id)
        if not dash:
            return await ctx.send(f"No dashboard configured for {channel.mention}.")
        blocked = dash["visit_blocked"]
        await ctx.send(f"Visit block for {channel.mention}: **{blocked}**.")

    @commands.command(name="setvisits")
    @commands.has_permissions(administrator=True)
    async def setvisits(self, ctx: commands.Context, channel: discord.TextChannel, normal: int, forced: int, stealth: int):
        """Set absolute visit counts for a rolechat. Usage: .setvisits #channel <normal> <forced> <stealth>"""
        if normal < 0 or forced < 0 or stealth < 0:
            return await ctx.send("Visit counts cannot be negative.")
        ok = set_visits(ctx.guild.id, channel.id, normal=normal, forced=forced, stealth=stealth)
        if not ok:
            return await ctx.send(f"No dashboard configured for {channel.mention}. Use .setrole first.")
        await ctx.send(f"Visits for {channel.mention}: Normal **{normal}**, Forced **{forced}**, Stealth **{stealth}**.")

    @commands.command(name="addvisits")
    @commands.has_permissions(administrator=True)
    async def addvisits(self, ctx: commands.Context, channel: discord.TextChannel, normal: int, forced: int, stealth: int):
        """Add visits to a rolechat. Usage: .addvisits #channel <normal> <forced> <stealth>"""
        if normal < 0 or forced < 0 or stealth < 0:
            return await ctx.send("Deltas cannot be negative.")
        updated = adjust_visits(ctx.guild.id, channel.id, delta_normal=normal, delta_forced=forced, delta_stealth=stealth)
        if not updated:
            return await ctx.send(f"No dashboard configured for {channel.mention}. Use .setrole first.")
        await ctx.send(
            f"Added visits for {channel.mention}. Now: Normal **{updated['visits_normal']}**, "
            f"Forced **{updated['visits_forced']}**, Stealth **{updated['visits_stealth']}**."
        )

    @commands.command(name="removevisits")
    @commands.has_permissions(administrator=True)
    async def removevisits(self, ctx: commands.Context, channel: discord.TextChannel, normal: int, forced: int, stealth: int):
        """Remove visits from a rolechat. Usage: .removevisits #channel <normal> <forced> <stealth>"""
        if normal < 0 or forced < 0 or stealth < 0:
            return await ctx.send("Amounts cannot be negative.")
        updated = adjust_visits(ctx.guild.id, channel.id, delta_normal=-normal, delta_forced=-forced, delta_stealth=-stealth)
        if not updated:
            return await ctx.send(f"No dashboard configured for {channel.mention}. Use .setrole first.")
        await ctx.send(
            f"Removed visits for {channel.mention}. Now: Normal **{updated['visits_normal']}**, "
            f"Forced **{updated['visits_forced']}**, Stealth **{updated['visits_stealth']}**."
        )

    # ------------------------------------------------------------------ #
    # Dashboard display
    # ------------------------------------------------------------------ #

    @commands.command(name="dashboard")
    async def dashboard_cmd(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Open the dashboard for the current RoleChat (or specified one)."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data or not guild_data.get("dashboard_enabled", False):
            return await ctx.send("Dashboard is not enabled on this server.")

        rc = _get_rc_channel(ctx, channel)

        if not ctx.author.guild_permissions.administrator:
            allowed = _rc_categories(ctx.guild, guild_data)
            if rc.category not in allowed or rc != ctx.channel:
                return await ctx.send(
                    "You can only use `.dashboard` inside your own RoleChat.",
                    delete_after=10,
                )

        dash = get_role_dashboard(ctx.guild.id, rc.id)
        if not dash:
            return await ctx.send("No role dashboard is configured for this channel yet.")

        embed = self._build_dashboard_embed(ctx.guild, rc)
        view = DashboardView(self, rc_channel=rc, invoker=ctx.author)
        await ctx.send(embed=embed, view=view)

    def _build_dashboard_embed(self, guild: discord.Guild, rc: discord.TextChannel) -> discord.Embed:
        """Build the dashboard embed for a rolechat (visits + abilities)."""
        dash = get_role_dashboard(guild.id, rc.id)
        if not dash:
            return info_embed(title="No dashboard", description="No role configured.")
        passives, actives = get_role_abilities(guild.id, rc.id)
        embed = info_embed(
            title=f"📋 {dash['name']}",
            description=f"**Team:** {dash['team']}",
        )
        embed.add_field(
            name="Visits",
            value=(
                f"Normal: **{dash['visits_normal']}**\n"
                f"Forced: **{dash['visits_forced']}**\n"
                f"Stealth: **{dash['visits_stealth']}**\n"
                f"Blocked: **{'Yes' if dash['visit_blocked'] else 'No'}**"
            ),
            inline=False,
        )
        if passives:
            embed.add_field(
                name="Passive Abilities",
                value="\n".join(f"{i+1}. {p}" for i, p in enumerate(passives)),
                inline=False,
            )
        if actives:
            embed.add_field(
                name="Active Abilities",
                value="\n".join(f"{i+1}. [{cat}] {text}" for i, (cat, text) in enumerate(actives)),
                inline=False,
            )
        return embed

    # ------------------------------------------------------------------ #
    # Button handlers
    # ------------------------------------------------------------------ #

    async def handle_action_button(self, interaction: discord.Interaction, rc_channel: discord.TextChannel):
        """Ask user to reply with their action, then send pending embeds to the log channel and RC."""
        guild = interaction.guild
        guild_data = load_guild_data(guild.id)
        if not guild_data or not guild_data.get("dashboard_enabled", False):
            return await interaction.response.send_message("Dashboard is not enabled on this server.", ephemeral=True)
        log_channel = discord.utils.get(guild.text_channels, name=guild_data.get("actions_log_channel_name"))
        if not log_channel:
            return await interaction.response.send_message("Actions log channel not configured.", ephemeral=True)

        prompt_embed = info_embed(
            title="Action request",
            description="Reply to this message with the action you want to execute.",
        )
        await interaction.response.send_message(embed=prompt_embed)
        prompt_message = await interaction.original_response()

        def check(m: discord.Message):
            return (
                m.channel == rc_channel
                and m.reference
                and m.reference.message_id == prompt_message.id
                and m.author == interaction.user
            )

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError:
            return await rc_channel.send("Action request timed out. Reply to the prompt message in time next time.")

        content = (reply.content[:500] + "...") if len(reply.content) > 500 else (reply.content or "*No text*")
        ts = _fmt_ts(reply.created_at)
        jump_url = reply.jump_url
        pinned = await rc_channel.pins()
        pinned_url = pinned[-1].jump_url if pinned else None
        jump_link = f"[Jump to Message]({jump_url})"
        pinned_link = f" | [Jump to Role]({pinned_url})" if pinned_url else ""

        embed_log = discord.Embed(color=EMBED_COLOR_FUCSIA)
        embed_log.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed_log.description = (
            f"**Message:**\n{content}\n\n"
            f"**Channel:** {rc_channel.mention}\n"
            f"**Time:** {ts}\n"
            f"{jump_link}{pinned_link}"
        )
        embed_log.set_footer(text="⏳ Pending...")

        embed_user = discord.Embed(color=EMBED_COLOR_FUCSIA)
        embed_user.description = (
            f"**Message:**\n{content}\n\n"
            f"**Log Channel:** {log_channel.mention}\n"
            f"**Time:** {ts}\n"
            f"{jump_link}{pinned_link}"
        )
        embed_user.set_footer(text="⏳ Pending...")

        meta = {
            "guild_id": guild.id,
            "channel_id": rc_channel.id,
            "player_id": interaction.user.id,
            "message": content,
            "created_at": reply.created_at.replace(tzinfo=timezone.utc),
        }

        log_message = await log_channel.send(embed=embed_log)
        user_message = await rc_channel.send(embed=embed_user)

        log_view = ActionButtons(
            user_embed=user_message,
            log_embed=log_message,
            user_embed_obj=embed_user.copy(),
            log_embed_obj=embed_log.copy(),
            meta=meta,
        )
        user_view = CancelOnlyView(
            user_embed=user_message,
            log_embed=log_message,
            user_embed_obj=embed_user,
            log_embed_obj=embed_log,
        )
        await log_message.edit(view=log_view)
        await user_message.edit(view=user_view)

    async def handle_visit_button(self, interaction: discord.Interaction, rc_channel: discord.TextChannel):
        guild = interaction.guild
        guild_data = load_guild_data(guild.id)
        if not guild_data or not guild_data.get("dashboard_enabled", False):
            return await interaction.response.send_message("Dashboard is not enabled on this server.", ephemeral=True)

        dash = get_role_dashboard(guild.id, rc_channel.id)
        if dash and dash["visit_blocked"]:
            return await interaction.response.send_message("Visits are currently blocked for this role.", ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            allowed = _rc_categories(guild, guild_data)
            if rc_channel.category not in allowed:
                return await interaction.response.send_message(
                    "You can only use visits from RoleChats.",
                    ephemeral=True,
                )

        visit_options = []
        if dash:
            if dash["visits_normal"] > 0:
                visit_options.append(discord.SelectOption(label="Normal visit", value="normal", description="Use a normal (knock) visit"))
            if dash["visits_forced"] > 0:
                visit_options.append(discord.SelectOption(label="Forced visit", value="forced", description="Use a forced move visit"))
            if dash["visits_stealth"] > 0:
                visit_options.append(discord.SelectOption(label="Stealth visit", value="stealth", description="Move stealthily (no narration)"))
        if not visit_options:
            visit_options = [
                discord.SelectOption(label="Normal visit", value="normal"),
                discord.SelectOption(label="Forced visit", value="forced"),
                discord.SelectOption(label="Stealth visit", value="stealth"),
            ]

        houselist = guild_data.get("houselist") or []
        if not houselist:
            return await interaction.response.send_message("No houselist configured for this guild.", ephemeral=True)

        type_select = Select(placeholder="Choose visit type", options=visit_options, min_values=1, max_values=1)
        house_options = [discord.SelectOption(label=name, value=name) for name in houselist[:25]]
        house_select = Select(placeholder="Choose house to visit", options=house_options, min_values=1, max_values=1)

        view = View(timeout=120)
        view.add_item(type_select)
        view.add_item(house_select)

        state = {"type": None, "house": None}

        async def maybe_execute(sel_inter: discord.Interaction):
            if state["type"] and state["house"]:
                from_names = _get_current_house_names(guild, guild_data, rc_channel)
                await self._execute_visit(sel_inter, rc_channel, state["type"], state["house"], from_house_names=from_names)

        async def on_type(sel_inter: discord.Interaction):
            if sel_inter.user != interaction.user:
                return await sel_inter.response.send_message("This menu isn't yours.", ephemeral=True)
            state["type"] = sel_inter.data["values"][0]
            await sel_inter.response.defer()
            await maybe_execute(sel_inter)

        async def on_house(sel_inter: discord.Interaction):
            if sel_inter.user != interaction.user:
                return await sel_inter.response.send_message("This menu isn't yours.", ephemeral=True)
            state["house"] = sel_inter.data["values"][0]
            await sel_inter.response.defer()
            await maybe_execute(sel_inter)

        type_select.callback = on_type
        house_select.callback = on_house

        await interaction.response.send_message("Select visit type and target house:", view=view, ephemeral=True)

    async def _execute_visit(
        self,
        interaction: discord.Interaction,
        rc_channel: discord.TextChannel,
        visit_type: str,
        house_name: str,
        *,
        from_house_names: list[str] | None = None,
    ):
        """After the player chooses visit type and house, create a pending visit request in the actions log channel."""
        guild = interaction.guild
        guild_data = load_guild_data(guild.id)
        if not guild_data:
            return await interaction.followup.send("Guild data not loaded.", ephemeral=True)

        houses_category = discord.utils.get(guild.categories, name=guild_data["houses_category_name"])
        target_channel = None
        if houses_category:
            for ch in houses_category.channels:
                if ch.name == house_name:
                    target_channel = ch
                    break
        if not target_channel:
            return await interaction.followup.send("House channel not found.", ephemeral=True)

        log_channel = discord.utils.get(
            guild.text_channels,
            name=guild_data.get("actions_log_channel_name"),
        )
        if not log_channel:
            return await interaction.followup.send(
                "Actions log channel not configured; cannot request visit.",
                ephemeral=True,
            )

        if from_house_names is None:
            from_house_names = _get_current_house_names(guild, guild_data, rc_channel)
        from_str = ", ".join(from_house_names) if from_house_names else "—"

        visit_label = {
            "normal": "Normal visit",
            "forced": "Forced visit",
            "stealth": "Stealth visit",
        }.get(visit_type, visit_type)

        desc_log = (
            f"{interaction.user.mention} requests a **{visit_label}**\n"
            f"**From:** {from_str}\n"
            f"**To:** {target_channel.mention} (`{house_name}`)\n\n"
            "An Overseer must press **Allow visit** to execute this move."
        )
        desc_rc = (
            f"**{visit_label}** request to **{house_name}**\n"
            f"**From:** {from_str}\n"
            f"**Log:** {log_channel.mention}\n\n"
            "⏳ Pending approval..."
        )

        embed_log = discord.Embed(
            title="🚪 Visit Request",
            description=desc_log,
            color=EMBED_COLOR_FUCSIA,
        )
        embed_log.set_footer(text="Pending approval...")

        embed_rc = discord.Embed(
            title="🚪 Visit Request",
            description=desc_rc,
            color=EMBED_COLOR_FUCSIA,
        )
        embed_rc.set_footer(text="⏳ Pending...")

        view = VisitApprovalView(
            dashboard_cog=self,
            guild_id=guild.id,
            rc_channel_id=rc_channel.id,
            target_channel_id=target_channel.id,
            requester_id=interaction.user.id,
            visit_type=visit_type,
            house_name=house_name,
            rc_pending_message=None,
        )

        log_message = await log_channel.send(embed=embed_log, view=view)
        rc_pending_message = await rc_channel.send(embed=embed_rc)
        view.rc_pending_message = rc_pending_message
        view.message_id = log_message.id

        await interaction.followup.send(
            f"Your visit request has been sent to the Overseers in {log_channel.mention}.",
            ephemeral=True,
        )

    async def handle_preset_button(self, interaction: discord.Interaction, rc_channel: discord.TextChannel):
        presets_cog = self.bot.get_cog("Presets")
        if not presets_cog:
            return await interaction.response.send_message("Presets system not loaded.", ephemeral=True)
        try:
            await presets_cog.open_presets_for_interaction(interaction, rc_channel)
        except AttributeError:
            await interaction.response.send_message(
                "Presets view not integrated yet. Use `.preset` in this channel.",
                ephemeral=True,
            )

    async def handle_logging_button(self, interaction: discord.Interaction, rc_channel: discord.TextChannel):
        logs = get_actions_for_channel(interaction.guild.id, rc_channel.id, limit=200, offset=0)
        if not logs:
            return await interaction.response.send_message("No logged actions for this channel yet.", ephemeral=True)

        def _shorten_visit_msg(text: str) -> str:
            if not text or "visit" not in text.lower():
                return text[:200] + ("..." if len(text) > 200 else "")
            m = re.search(
                r"(?:from|From:?)\s*(?:#?\S+\s*`?\[?([^\]`#]+)\]?`?|.+?)\s*(?:to|To:?)\s*(?:#?\S+\s*`?\[?([^\]`#]+)\]?`?|.+?)(?:\s|$)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                return f"visit from {m.group(1).strip()} to {m.group(2).strip()}"
            if "Removed From:" in text and "Added To:" in text:
                parts = text.split("Added To:")
                from_part = parts[0].replace("Removed From:", "").strip()
                to_part = parts[1].strip() if len(parts) > 1 else ""
                from_name = re.sub(r"`?\[?([^\]#`]+)\]?`?", r"\1", from_part).strip()[:50]
                to_name = re.sub(r"`?\[?([^\]#`]+)\]?`?", r"\1", to_part).strip()[:50]
                return f"visit from {from_name} to {to_name}"
            return text[:200] + ("..." if len(text) > 200 else "")

        per_page = 10
        pages: list[str] = []
        for i in range(0, len(logs), per_page):
            chunk = logs[i: i + per_page]
            lines: list[str] = []
            for entry in chunk:
                created_ts = _fmt_ts(entry["created_at"])
                marked_ts = _fmt_ts(entry["marked_at"])
                text = _shorten_visit_msg(entry["message"])
                lines.append(
                    f"• **Asked:** `{created_ts}`\n"
                    f"  **Done:**  `{marked_ts}`\n"
                    f"  {text}"
                )
            pages.append("\n\n".join(lines))

        page_index = 0

        def build_log_embed() -> discord.Embed:
            emb = discord.Embed(
                title="📜 Logged Actions",
                description=pages[page_index],
                color=EMBED_COLOR_FUCSIA,
            )
            emb.set_footer(text=f"Page {page_index + 1}/{len(pages)}")
            return emb

        log_embed = build_log_embed()

        view = View(timeout=120)
        btn_prev = Button(emoji="⬅️", style=discord.ButtonStyle.secondary)
        btn_next = Button(emoji="➡️", style=discord.ButtonStyle.secondary)
        btn_back = Button(label="Back to Dashboard", style=discord.ButtonStyle.secondary)

        async def refresh(inter: discord.Interaction):
            if inter.user != interaction.user:
                return await inter.response.send_message("This menu isn't yours.", ephemeral=True)
            await inter.response.edit_message(embed=build_log_embed(), view=view)

        async def on_prev(inter: discord.Interaction):
            nonlocal page_index
            if page_index > 0:
                page_index -= 1
            await refresh(inter)

        async def on_next(inter: discord.Interaction):
            nonlocal page_index
            if page_index < len(pages) - 1:
                page_index += 1
            await refresh(inter)

        async def on_back(inter: discord.Interaction):
            if inter.user != interaction.user:
                return await inter.response.send_message("This menu isn't yours.", ephemeral=True)
            dash_embed = self._build_dashboard_embed(inter.guild, rc_channel)
            back_view = DashboardView(self, rc_channel=rc_channel, invoker=interaction.user)
            await inter.response.edit_message(embed=dash_embed, view=back_view)

        btn_prev.callback = on_prev
        btn_next.callback = on_next
        btn_back.callback = on_back

        if len(pages) > 1:
            view.add_item(btn_prev)
            view.add_item(btn_next)
        view.add_item(btn_back)

        await interaction.response.edit_message(embed=log_embed, view=view)

    # ------------------------------------------------------------------ #
    # Admin: action log command
    # ------------------------------------------------------------------ #

    @commands.command(name="actionlog")
    @commands.has_permissions(administrator=True)
    async def actionlog(self, ctx: commands.Context, channel: discord.TextChannel, limit: int = 20):
        """Show recent logged actions for a rolechat without opening the dashboard.

        Usage: .actionlog #channel [limit=20]
        """
        limit = max(1, min(limit, 100))
        logs = get_actions_for_channel(ctx.guild.id, channel.id, limit=limit, offset=0)
        if not logs:
            return await ctx.send(f"No logged actions for {channel.mention}.")

        per_page = 10
        pages: list[str] = []
        for i in range(0, len(logs), per_page):
            chunk = logs[i: i + per_page]
            lines: list[str] = []
            for entry in chunk:
                created_ts = _fmt_ts(entry["created_at"])
                marked_ts = _fmt_ts(entry["marked_at"])
                msg = (entry["message"] or "")[:200]
                lines.append(
                    f"• **Asked:** `{created_ts}`  **Done:** `{marked_ts}`\n  {msg}"
                )
            pages.append("\n\n".join(lines))

        page_index = 0

        def build_embed() -> discord.Embed:
            emb = discord.Embed(
                title=f"📜 Action Log — #{channel.name}",
                description=pages[page_index],
                color=EMBED_COLOR_FUCSIA,
            )
            emb.set_footer(text=f"Page {page_index + 1}/{len(pages)} • showing last {limit} entries")
            return emb

        view = View(timeout=120)
        btn_prev = Button(emoji="⬅️", style=discord.ButtonStyle.secondary)
        btn_next = Button(emoji="➡️", style=discord.ButtonStyle.secondary)

        async def on_prev(inter: discord.Interaction):
            nonlocal page_index
            if inter.user != ctx.author:
                return await inter.response.send_message("This menu isn't yours.", ephemeral=True)
            if page_index > 0:
                page_index -= 1
            await inter.response.edit_message(embed=build_embed(), view=view)

        async def on_next(inter: discord.Interaction):
            nonlocal page_index
            if inter.user != ctx.author:
                return await inter.response.send_message("This menu isn't yours.", ephemeral=True)
            if page_index < len(pages) - 1:
                page_index += 1
            await inter.response.edit_message(embed=build_embed(), view=view)

        btn_prev.callback = on_prev
        btn_next.callback = on_next

        if len(pages) > 1:
            view.add_item(btn_prev)
            view.add_item(btn_next)

        await ctx.send(embed=build_embed(), view=view if len(pages) > 1 else None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dashboard(bot))
