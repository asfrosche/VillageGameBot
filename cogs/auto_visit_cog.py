import discord
from discord.ext import commands
from discord.ui import View, Button

from cogs.data_utils import load_guild_data, save_guild_data
from utils.bot_db import (
    get_auto_visit_rc_allocation,
    get_auto_visit_rc_usage,
    increment_auto_visit_rc_usage,
    reset_all_auto_visit_rc_usage,
    reset_auto_visit_rc_usage,
    get_role_dashboard,
    upsert_auto_visit_rc_allocation,
    add_to_auto_visit_rc_allocation,
    delete_auto_visit_rc_allocation,
)
from utils.embeds import info_embed, success_embed


CONFIRM_TIMEOUT = 120


VISIT_LABEL = {
    "normal": "Normal Visit",
    "forced": "Forced Visit",
    "stealth": "Stealth Visit",
}


# ─────────────────────────────────────────────────────────────
# Confirm View (auto-visit execution)
# ─────────────────────────────────────────────────────────────


class AutoVisitConfirmView(View):
    def __init__(self, cog: "AutoVisit", ctx: commands.Context, visit_type: str, house_name: str):
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.cog = cog
        self.ctx = ctx
        self.visit_type = visit_type
        self.house_name = house_name
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_btn(self, interaction: discord.Interaction, button: Button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(view=None)
        await self.cog._execute_auto_visit(self.ctx, self.visit_type, self.house_name)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_btn(self, interaction: discord.Interaction, button: Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", embed=None, view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="Confirmation timed out.", embed=None, view=None)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# Add View (.autorcadd interactive UI)
# ─────────────────────────────────────────────────────────────


class AutoVisitAddView(View):
    def __init__(self, cog: "AutoVisit", guild_id: int, channel_id: int, allocation: dict | None):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.allocation = allocation or {k: 0 for k in (
            "day_normal", "day_forced", "day_stealth",
            "night_normal", "night_forced", "night_stealth",
        )}
        self.pending = {k: 0 for k in self.allocation}
        self.message = None

        self._build_phase_one()

    def _build_phase_one(self):
        self.clear_items()
        self._add_btn("Day Normal +1",  "day_normal", 1, 0)
        self._add_btn("Day Normal -1",  "day_normal", -1, 0)
        self._add_btn("Day Forced +1",  "day_forced", 1, 0)
        self._add_btn("Day Forced -1",  "day_forced", -1, 0)
        self._add_btn("Day Stealth +1", "day_stealth", 1, 0)

        self._add_btn("Day Stealth -1", "day_stealth", -1, 1)
        self._add_btn("Night Normal +1", "night_normal", 1, 1)
        self._add_btn("Night Normal -1", "night_normal", -1, 1)
        self._add_btn("Night Forced +1", "night_forced", 1, 1)
        self._add_btn("Night Forced -1", "night_forced", -1, 1)

        self._add_btn("Night Stealth +1", "night_stealth", 1, 2)
        self._add_btn("Night Stealth -1", "night_stealth", -1, 2)

        done_btn = Button(label="Done", style=discord.ButtonStyle.success, emoji="✅", row=2)
        done_btn.callback = self._on_done
        self.add_item(done_btn)

        cancel_btn = Button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌", row=2)
        cancel_btn.callback = self._on_cancel_early
        self.add_item(cancel_btn)

    def _add_btn(self, label: str, key: str, delta: int, row: int):
        style = discord.ButtonStyle.primary if delta > 0 else discord.ButtonStyle.secondary
        btn = Button(label=label, style=style, row=row)
        btn.callback = lambda i, b=key, d=delta: self._on_adjust(i, b, d)
        self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return False
        member = interaction.user
        if member.guild_permissions.administrator:
            return True
        guild_data = load_guild_data(guild.id)
        if guild_data:
            os_role = discord.utils.get(guild.roles, name=guild_data.get("overseer_role_name", ""))
            if os_role and os_role in member.roles:
                return True
        await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
        return False

    def _build_embed(self):
        lines = []
        for period, label in (("day", "Day"), ("night", "Night")):
            parts = []
            for vtype in ("Normal", "Forced", "Stealth"):
                key = f"{period}_{vtype.lower()}"
                current = self.allocation.get(key, 0)
                delta = self.pending.get(key, 0)
                parts.append(f"{vtype}: {current}")
                if delta != 0:
                    sign = f"+{delta}" if delta > 0 else str(delta)
                    new_val = max(0, current + delta)
                    parts[-1] += f" ({sign} → {new_val})"
            lines.append(f"**{label}** — " + " | ".join(parts))
        total_pending = sum(abs(v) for v in self.pending.values())
        footer = "\nUse +/- buttons to adjust, then click **Done** to apply."
        if total_pending == 0:
            footer = "\nNo changes yet. Use +/- buttons to adjust, then click **Done**."
        return info_embed(
            title="Add Auto-Visits",
            description="\n\n".join(lines) + footer,
        )

    async def _on_adjust(self, interaction: discord.Interaction, key: str, delta: int):
        self.pending[key] += delta
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_done(self, interaction: discord.Interaction):
        has_changes = any(v != 0 for v in self.pending.values())
        if not has_changes:
            await interaction.response.send_message("No changes to apply.", ephemeral=True)
            return
        self.clear_items()
        confirm = Button(label="Confirm Apply", style=discord.ButtonStyle.success, emoji="✅", row=0)
        confirm.callback = self._on_confirm
        self.add_item(confirm)
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌", row=0)
        cancel.callback = self._on_cancel
        self.add_item(cancel)
        summary_lines = []
        for key, delta in self.pending.items():
            if delta != 0:
                period, vtype = key.split("_", 1)
                sign = f"+{delta}" if delta > 0 else str(delta)
                summary_lines.append(f"{period.capitalize()} {vtype.capitalize()}: **{sign}**")
        await interaction.response.edit_message(
            embed=info_embed(
                title="Confirm Changes",
                description="Apply these changes?\n\n" + "\n".join(summary_lines),
            ),
            view=self,
        )

    async def _on_confirm(self, interaction: discord.Interaction):
        kwargs = {k: v for k, v in self.pending.items() if v != 0}
        if kwargs:
            add_to_auto_visit_rc_allocation(self.guild_id, self.channel_id, **kwargs)
        self.stop()
        await interaction.response.edit_message(
            embed=success_embed(title="Changes Applied", description="Auto-visit allocation updated."),
            view=None,
        )

    async def _on_cancel(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(
            content="Cancelled. No changes made.", embed=None, view=None,
        )

    async def _on_cancel_early(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(
            content="Cancelled. No changes made.", embed=None, view=None,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="Session timed out.", embed=None, view=None)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────


class AutoVisit(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.current_phases: dict[int, str] = {}

    @commands.Cog.listener()
    async def on_phase_change(self, phase: str):
        if phase not in ("day", "night"):
            return
        for guild in self.bot.guilds:
            self.current_phases[guild.id] = phase
            reset_all_auto_visit_rc_usage(guild.id)

    def _get_current_phase(self, guild_id: int) -> str:
        return self.current_phases.get(guild_id, "day")

    def _is_admin_or_overseer(self, ctx: commands.Context) -> bool:
        if ctx.author.guild_permissions.administrator:
            return True
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            os_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("overseer_role_name", ""))
            if os_role and os_role in ctx.author.roles:
                return True
        return False

    def _find_rc_channel(self, guild: discord.Guild, guild_data: dict, member: discord.Member):
        category_names = [
            guild_data.get("rc_category_name"),
            guild_data.get("alt_category_name"),
            guild_data.get("dead_rc_category_name"),
        ]
        for cat_name in category_names:
            if not cat_name:
                continue
            cat = discord.utils.get(guild.categories, name=cat_name)
            if not cat:
                continue
            for ch in cat.channels:
                if isinstance(ch, discord.TextChannel) and member in ch.members:
                    return ch
        return None

    def _get_player_house(self, guild: discord.Guild, guild_data: dict, member: discord.Member):
        houses_category = discord.utils.get(guild.categories, name=guild_data.get("houses_category_name"))
        if not houses_category:
            return None
        for ch in houses_category.channels:
            if isinstance(ch, discord.TextChannel):
                perms = ch.permissions_for(member)
                if perms.send_messages:
                    return ch
        return None

    def _build_remaining_text(self, allocation: dict, phase: str, usage: dict | None) -> str:
        used = usage or {"normal_used": 0, "forced_used": 0, "stealth_used": 0}
        prefix = "day_" if phase == "day" else "night_"
        limits = {
            "normal": allocation.get(f"{prefix}normal", 0),
            "forced": allocation.get(f"{prefix}forced", 0),
            "stealth": allocation.get(f"{prefix}stealth", 0),
        }
        remaining = {
            "normal": limits["normal"] - used["normal_used"],
            "forced": limits["forced"] - used["forced_used"],
            "stealth": limits["stealth"] - used["stealth_used"],
        }
        return (
            f"Normal: **{remaining['normal']}**\n"
            f"Forced: **{remaining['forced']}**\n"
            f"Stealth: **{remaining['stealth']}**"
        )

    def _get_remaining(self, allocation: dict, phase: str, usage: dict | None, visit_type: str) -> int:
        used = usage or {"normal_used": 0, "forced_used": 0, "stealth_used": 0}
        prefix = "day_" if phase == "day" else "night_"
        limit = allocation.get(f"{prefix}{visit_type}", 0)
        return limit - used[f"{visit_type}_used"]

    # ── Management commands ──────────────────────────────────

    @commands.command(name="autovisits")
    async def autovisits(self, ctx: commands.Context, setting: str):
        """Toggle the auto-visit system on or off."""
        if not self._is_admin_or_overseer(ctx):
            await ctx.send("You don't have permission to use this command.")
            return
        if setting.lower() not in ("on", "off"):
            await ctx.send("Usage: `.autovisits on` or `.autovisits off`")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        enabled = setting.lower() == "on"
        guild_data["auto_visits_enabled"] = enabled
        save_guild_data(ctx.guild.id, guild_data)
        state = "enabled" if enabled else "disabled"
        await ctx.send(f"Auto visits are now **{state}**.")

    @commands.command(name="autorcset")
    async def autorcset(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        day_normal: int,
        day_forced: int,
        day_stealth: int,
        night_normal: int,
        night_forced: int,
        night_stealth: int,
    ):
        """Set the RC channel for auto-visit notifications."""
        if not self._is_admin_or_overseer(ctx):
            await ctx.send("You don't have permission to use this command.")
            return
        for v in (day_normal, day_forced, day_stealth, night_normal, night_forced, night_stealth):
            if v < 0:
                await ctx.send("Visit counts cannot be negative.")
                return
        total = day_normal + day_forced + day_stealth + night_normal + night_forced + night_stealth
        if total == 0:
            delete_auto_visit_rc_allocation(ctx.guild.id, channel.id)
            await ctx.send(f"Auto-visit allocation removed for {channel.mention}.")
            return
        upsert_auto_visit_rc_allocation(
            ctx.guild.id, channel.id,
            day_normal=day_normal,
            day_forced=day_forced,
            day_stealth=day_stealth,
            night_normal=night_normal,
            night_forced=night_forced,
            night_stealth=night_stealth,
        )
        await ctx.send(
            f"Auto-visit allocation set for {channel.mention}:\n"
            f"Day — Normal: **{day_normal}**, Forced: **{day_forced}**, Stealth: **{day_stealth}**\n"
            f"Night — Normal: **{night_normal}**, Forced: **{night_forced}**, Stealth: **{night_stealth}**"
        )

    @commands.command(name="autorcadd")
    async def autorcadd(self, ctx: commands.Context, channel: discord.TextChannel):
        """Add a user to the auto-visit list."""
        if not self._is_admin_or_overseer(ctx):
            await ctx.send("You don't have permission to use this command.")
            return
        allocation = get_auto_visit_rc_allocation(ctx.guild.id, channel.id)
        view = AutoVisitAddView(self, ctx.guild.id, channel.id, allocation)
        embed = view._build_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

    @commands.command(name="autorcreset")
    async def autorcreset(self, ctx: commands.Context, channel: discord.TextChannel):
        """Reset all auto-visit configurations."""
        if not self._is_admin_or_overseer(ctx):
            await ctx.send("You don't have permission to use this command.")
            return
        reset_auto_visit_rc_usage(ctx.guild.id, channel.id)
        await ctx.send(f"Auto-visit usage reset for {channel.mention}. The allocation set via `.autorcset` remains unchanged.")

    # ── Player auto-visit commands ───────────────────────────

    async def _auto_visit_common(self, ctx: commands.Context, house_str: str, visit_type: str):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        if not guild_data.get("auto_visits_enabled", False):
            await ctx.send("Auto visits are currently disabled.")
            return

        rc_channel = self._find_rc_channel(ctx.guild, guild_data, ctx.author)
        if not rc_channel:
            await ctx.send("Could not find your RoleChat channel.")
            return

        allocation = get_auto_visit_rc_allocation(ctx.guild.id, rc_channel.id)
        if not allocation:
            await ctx.send("Your RC has no auto-visit allocation. An Overseer must set one with `.autorcset`.")
            return

        phase = self._get_current_phase(ctx.guild.id)
        usage = get_auto_visit_rc_usage(ctx.guild.id, rc_channel.id)
        remaining = self._get_remaining(allocation, phase, usage, visit_type)
        if remaining <= 0:
            await ctx.send(f"**{rc_channel.name}** has no **{VISIT_LABEL[visit_type]}** remaining this phase.")
            return

        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if not houses_category:
            await ctx.send("Houses category not found.")
            return
        target_channel = discord.utils.get(houses_category.channels, name=house_str)
        if not target_channel:
            await ctx.send(f"House `{house_str}` not found.")
            return

        remaining_text = self._build_remaining_text(allocation, phase, usage)

        confirm_embed = info_embed(
            title="Confirm Auto Visit",
            description=(
                f"Use **1 {VISIT_LABEL[visit_type]}** from **{rc_channel.name}**?\n\n"
                f"**Destination:** {house_str}\n\n"
                f"**RC Remaining After Move:**\n{remaining_text}"
            ),
        )
        view = AutoVisitConfirmView(self, ctx, visit_type, house_str)
        msg = await ctx.send(embed=confirm_embed, view=view)
        view.message = msg
        await view.wait()

    async def _execute_auto_visit(self, ctx: commands.Context, visit_type: str, house_name: str):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return

        rc_channel = self._find_rc_channel(ctx.guild, guild_data, ctx.author)
        if not rc_channel:
            await ctx.send("Could not find your RoleChat channel.")
            return

        dash = get_role_dashboard(ctx.guild.id, rc_channel.id)
        if dash and dash.get("visit_blocked"):
            await ctx.send("Visits are blocked for your role.")
            return

        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if not houses_category:
            await ctx.send("Houses category not found.")
            return
        target_channel = discord.utils.get(houses_category.channels, name=house_name)
        if not target_channel:
            await ctx.send(f"House `{house_name}` not found.")
            return

        delta_map = {"normal": (1, 0, 0), "forced": (0, 1, 0), "stealth": (0, 0, 1)}
        dn, df, ds = delta_map[visit_type]
        new_usage = increment_auto_visit_rc_usage(
            ctx.guild.id, rc_channel.id,
            delta_normal=dn, delta_forced=df, delta_stealth=ds,
        )

        moving_cog = self.bot.get_cog("Moving")
        if not moving_cog:
            increment_auto_visit_rc_usage(
                ctx.guild.id, rc_channel.id,
                delta_normal=-dn, delta_forced=-df, delta_stealth=-ds,
            )
            await ctx.send("Moving system not loaded; visit refunded.")
            return

        player_house = self._get_player_house(ctx.guild, guild_data, ctx.author)
        if player_house:
            ctx.channel = player_house

        try:
            if visit_type == "normal":
                await moving_cog.process_knock(ctx, target_channel, guild_data)
            else:
                is_stealth = visit_type == "stealth"
                await moving_cog.process_move(ctx, target_channel, is_stealth=is_stealth, read_only=False)
        except Exception:
            increment_auto_visit_rc_usage(
                ctx.guild.id, rc_channel.id,
                delta_normal=-dn, delta_forced=-df, delta_stealth=-ds,
            )
            await ctx.send("Error executing visit. Visit refunded.")
            return

        allocation = get_auto_visit_rc_allocation(ctx.guild.id, rc_channel.id)
        phase = self._get_current_phase(ctx.guild.id)
        remaining_text = self._build_remaining_text(allocation, phase, new_usage) if allocation else "N/A"

        result_embed = success_embed(
            title="Visit Completed",
            description=(
                f"Moved to **{house_name}**.\n\n"
                f"**{rc_channel.name} Remaining Visits:**\n{remaining_text}"
            ),
        )
        try:
            await target_channel.send(embed=result_embed)
        except Exception:
            await ctx.send(embed=result_embed)

    @commands.command(name="autoknock")
    async def autoknock(self, ctx: commands.Context, *, house: str):
        """Toggle auto-knock on or off."""
        await self._auto_visit_common(ctx, house.strip(), "normal")

    @commands.command(name="automove")
    async def automove(self, ctx: commands.Context, *, house: str):
        """Toggle auto-move on or off."""
        await self._auto_visit_common(ctx, house.strip(), "forced")

    @commands.command(name="autostealth")
    async def autostealth(self, ctx: commands.Context, *, house: str):
        """Toggle stealth mode for auto-visits (suppress join/leave messages)."""
        await self._auto_visit_common(ctx, house.strip(), "stealth")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoVisit(bot))
