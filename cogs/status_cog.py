import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
from datetime import datetime, timezone

from cogs.data_utils import load_guild_data, save_guild_data
from utils.embeds import info_embed, warning_embed


# ── Constants ────────────────────────────────────────────────────────────────

BUILTIN_STATUSES = {
    "protection":        ("🛡", "Protection"),
    "roleblock":         ("⛔", "Roleblock"),
    "visitblock":        ("👣", "Visit Block"),
    "immunity":          ("✨", "Immunity"),
    "untargetable":      ("🎯", "Untargetable"),
    "stealth":           ("🌑", "Stealth"),
}


# ── Storage helpers (importable by other cogs) ──────────────────────────────

def _channel_entry(guild_data, channel_id):
    cs = guild_data.setdefault("channel_statuses", {})
    return cs.setdefault(str(channel_id), {})


def get_channel_statuses(guild_data, channel_id):
    return dict(_channel_entry(guild_data, channel_id))


def has_status(guild_data, channel_id, key):
    return key in _channel_entry(guild_data, channel_id)


def set_status(guild_data, channel_id, key, moderator_id):
    _channel_entry(guild_data, channel_id)[key] = {
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
        "moderator": moderator_id,
    }


def remove_status(guild_data, channel_id, key):
    _channel_entry(guild_data, channel_id).pop(key, None)


def clear_all_statuses(guild_data, channel_id):
    cs = guild_data.setdefault("channel_statuses", {})
    cs.pop(str(channel_id), None)


def add_custom_status(guild_data, channel_id, text, moderator_id):
    entry = _channel_entry(guild_data, channel_id)
    entry.setdefault("custom", []).append({
        "text": text,
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
        "moderator": moderator_id,
    })


def remove_custom_status(guild_data, channel_id, index):
    entry = _channel_entry(guild_data, channel_id)
    custom = entry.get("custom", [])
    if 0 <= index < len(custom):
        custom.pop(index)
    if not custom:
        entry.pop("custom", None)


def build_status_description(guild_data, channel_id):
    entry = guild_data.get("channel_statuses", {}).get(str(channel_id), {})
    lines = []
    for key, (emoji, label) in BUILTIN_STATUSES.items():
        if key in entry:
            ts = entry[key]["timestamp"]
            lines.append(f"{emoji} {label}\nAdded <t:{ts}:t>")
    for c in entry.get("custom", []):
        ts = c["timestamp"]
        lines.append(f"📝 {c['text']}\nAdded <t:{ts}:t>")
    return "\n\n".join(lines) if lines else "No active statuses."


def check_dead_warning(guild_data, channel_id):
    entry = _channel_entry(guild_data, channel_id)
    if "protection" in entry:
        ts = entry["protection"]["timestamp"]
        return f"🛡 Protection\nAdded <t:{ts}:t>"
    return None


def check_move_warning(guild_data, channel_id):
    entry = _channel_entry(guild_data, channel_id)
    if "stealth" in entry:
        ts = entry["stealth"]["timestamp"]
        return f"🌑 Stealth\nAdded <t:{ts}:t>"
    return None


def check_knock_warning(guild_data, channel_id):
    return check_move_warning(guild_data, channel_id)


def check_visitblock(guild_data, channel_id):
    return has_status(guild_data, channel_id, "visitblock")


def check_visitblock_warning(guild_data, channel_id):
    entry = _channel_entry(guild_data, channel_id)
    if "visitblock" in entry:
        ts = entry["visitblock"]["timestamp"]
        return f"👣 Visit Block\nAdded <t:{ts}:t>"
    return None


# ── Logging helper ────────────────────────────────────────────────────────────

async def _log_status_change(guild, channel_id, action, status_label, moderator):
    guild_data = load_guild_data(guild.id)
    if not guild_data:
        return
    log_ch = discord.utils.get(guild.text_channels, name=guild_data.get("actions_log_channel_name"))
    if not log_ch:
        return
    channel = guild.get_channel(channel_id)
    ch_mention = channel.mention if channel else f"<#{channel_id}>"
    embed = discord.Embed(
        title=f"Status {action}",
        description=(
            f"**Channel:** {ch_mention}\n"
            f"**Status:** {status_label}\n"
            f"**By:** {moderator.mention}"
        ),
        color=0xff3fb9,
        timestamp=datetime.now(timezone.utc),
    )
    try:
        await log_ch.send(embed=embed)
    except Exception:
        pass


# ── UI Components ────────────────────────────────────────────────────────────

class CustomStatusModal(Modal, title="Custom Status"):
    text = TextInput(
        label="Status",
        style=discord.TextStyle.short,
        placeholder="e.g. Cannot be poisoned tonight",
        max_length=200,
    )

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        guild_data = load_guild_data(interaction.guild_id)
        if not guild_data:
            return await interaction.response.send_message("Guild data not loaded.", ephemeral=True)
        add_custom_status(guild_data, self.view.channel_id, self.text.value, interaction.user.id)
        save_guild_data(interaction.guild_id, guild_data)
        await _log_status_change(interaction.guild, self.view.channel_id, "Added", f"Custom: {self.text.value}", interaction.user)
        embed = _build_status_embed(self.view.channel_name, self.view.channel_id, guild_data)
        await interaction.response.edit_message(embed=embed, view=self.view)


class ClearConfirmView(View):
    def __init__(self, manager_view):
        super().__init__(timeout=60)
        self.mv = manager_view

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger, emoji="✔")
    async def confirm(self, interaction, button):
        if interaction.user.id != self.mv.invoker_id:
            return await interaction.response.send_message("Not for you.", ephemeral=True)
        guild_data = load_guild_data(interaction.guild_id)
        if not guild_data:
            return await interaction.response.send_message("Guild data not loaded.", ephemeral=True)
        clear_all_statuses(guild_data, self.mv.channel_id)
        save_guild_data(interaction.guild_id, guild_data)
        await _log_status_change(interaction.guild, self.mv.channel_id, "Cleared", "All statuses", interaction.user)
        embed = _build_status_embed(self.mv.channel_name, self.mv.channel_id, guild_data)
        await interaction.response.edit_message(embed=embed, view=self.mv)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction, button):
        if interaction.user.id != self.mv.invoker_id:
            return await interaction.response.send_message("Not for you.", ephemeral=True)
        await interaction.response.edit_message(view=self.mv)


class StatusWarningConfirmView(View):
    def __init__(self, invoker_id):
        super().__init__(timeout=60)
        self.invoker_id = invoker_id
        self.confirmed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("Not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.danger, emoji="⚠")
    async def continue_btn(self, interaction, button):
        self.confirmed = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_btn(self, interaction, button):
        self.confirmed = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Action cancelled.", embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="Timed out.", embed=None, view=self)
        except Exception:
            pass


def check_channel_warning(guild_data, channel_id, warning_fn):
    """Return (description, True) or (None, False)."""
    text = warning_fn(guild_data, channel_id)
    if text:
        return text, True
    return None, False


class StatusManagerView(View):
    def __init__(self, channel_id, channel_name, invoker_id):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.channel_name = channel_name
        self.invoker_id = invoker_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This isn't yours.", ephemeral=True)
            return False
        return True

    def _toggle_buttons(self, guild_data):
        entry = _channel_entry(guild_data, self.channel_id)
        keys = list(BUILTIN_STATUSES.keys())
        for i, child in enumerate(self.children):
            if i < len(keys):
                child.style = (
                    discord.ButtonStyle.success if keys[i] in entry
                    else discord.ButtonStyle.secondary
                )

    @discord.ui.button(label="Protection", style=discord.ButtonStyle.secondary, emoji="🛡", row=0)
    async def btn_protection(self, interaction, button):
        await self._toggle(interaction, "protection")

    @discord.ui.button(label="Roleblock", style=discord.ButtonStyle.secondary, emoji="⛔", row=0)
    async def btn_roleblock(self, interaction, button):
        await self._toggle(interaction, "roleblock")

    @discord.ui.button(label="Visit Block", style=discord.ButtonStyle.secondary, emoji="👣", row=0)
    async def btn_visitblock(self, interaction, button):
        await self._toggle(interaction, "visitblock")

    @discord.ui.button(label="Immunity", style=discord.ButtonStyle.secondary, emoji="✨", row=0)
    async def btn_immunity(self, interaction, button):
        await self._toggle(interaction, "immunity")

    @discord.ui.button(label="Untargetable", style=discord.ButtonStyle.secondary, emoji="🎯", row=1)
    async def btn_untargetable(self, interaction, button):
        await self._toggle(interaction, "untargetable")

    @discord.ui.button(label="Stealth", style=discord.ButtonStyle.secondary, emoji="🌑", row=1)
    async def btn_stealth(self, interaction, button):
        await self._toggle(interaction, "stealth")

    @discord.ui.button(label="Custom Status", style=discord.ButtonStyle.primary, emoji="📝", row=1)
    async def btn_custom(self, interaction, button):
        await interaction.response.send_modal(CustomStatusModal(self))

    @discord.ui.button(label="Clear All", style=discord.ButtonStyle.danger, emoji="🗑", row=1)
    async def btn_clear(self, interaction, button):
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not for you.", ephemeral=True)
        embed = warning_embed(
            title="Clear All Statuses?",
            description="This will remove every status for this channel.",
        )
        await interaction.response.edit_message(embed=embed, view=ClearConfirmView(self))

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, emoji="✅", row=1)
    async def btn_done(self, interaction, button):
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not for you.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def _toggle(self, interaction, key):
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not for you.", ephemeral=True)
        guild_data = load_guild_data(interaction.guild_id)
        if not guild_data:
            return await interaction.response.send_message("Guild data not loaded.", ephemeral=True)
        emoji, label = BUILTIN_STATUSES[key]
        if has_status(guild_data, self.channel_id, key):
            remove_status(guild_data, self.channel_id, key)
            action = "Removed"
        else:
            set_status(guild_data, self.channel_id, key, interaction.user.id)
            action = "Added"
        save_guild_data(interaction.guild_id, guild_data)
        await _log_status_change(interaction.guild, self.channel_id, action, f"{emoji} {label}", interaction.user)
        self._toggle_buttons(guild_data)
        embed = _build_status_embed(self.channel_name, self.channel_id, guild_data)
        await interaction.response.edit_message(embed=embed, view=self)


class StatusListClearView(View):
    def __init__(self, entries, invoker_id, guild):
        super().__init__(timeout=300)
        self._entries = entries
        self.invoker_id = invoker_id
        prev_ch = None
        ch_count = 0
        for idx in range(len(entries)):
            ch_id, status_key, _, _, _ = entries[idx]
            if ch_id != prev_ch:
                ch_count = 1
                prev_ch = ch_id
            else:
                ch_count += 1
            channel = guild.get_channel(ch_id)
            ch_name = channel.name[:7] if channel else str(ch_id)[-7:]
            btn = Button(
                label=f"{ch_name}#{ch_count}",
                style=discord.ButtonStyle.danger,
                emoji="🗑",
                custom_id=f"slclear_{idx}",
                row=idx if idx < 5 else (idx % 5),
            )
            btn.callback = self._make_callback(idx)
            self.add_item(btn)
            if idx >= 24:
                break

    def _make_callback(self, idx):
        async def callback(interaction):
            if interaction.user.id != self.invoker_id:
                return await interaction.response.send_message("Not for you.", ephemeral=True)
            ch_id, status_key, _, _, custom_idx = self._entries[idx]
            guild_data = load_guild_data(interaction.guild_id)
            if not guild_data:
                return await interaction.response.send_message("Guild data not loaded.", ephemeral=True)
            if status_key == "custom":
                remove_custom_status(guild_data, ch_id, custom_idx)
                label = "Custom status"
            else:
                remove_status(guild_data, ch_id, status_key)
                emoji, lbl = BUILTIN_STATUSES[status_key]
                label = f"{emoji} {lbl}"
            save_guild_data(interaction.guild_id, guild_data)
            await _log_status_change(interaction.guild, ch_id, "Removed", label, interaction.user)
            await _edit_statuslist(interaction, guild_data, self.invoker_id)
        return callback


# ── Statuslist helpers ───────────────────────────────────────────────────────

async def _edit_statuslist(interaction, guild_data, invoker_id):
    content = _build_statuslist_content(guild_data, interaction.guild)
    if not content:
        await interaction.response.edit_message(content="No active statuses.", embed=None, view=None)
        return
    view = _build_statuslist_view(guild_data, invoker_id, interaction.guild)
    await interaction.response.edit_message(content=content, embed=None, view=view)


def _build_statuslist_content(guild_data, guild):
    cs = guild_data.get("channel_statuses", {})
    if not cs:
        return None
    blocks = []
    for ch_id_str, statuses in cs.items():
        has_any = any(key in statuses for key in BUILTIN_STATUSES)
        if not has_any and not statuses.get("custom"):
            continue
        channel = guild.get_channel(int(ch_id_str))
        ch_mention = channel.mention if channel else f"#{ch_id_str}"
        block_lines = []
        for key, (emoji, label) in BUILTIN_STATUSES.items():
            if key in statuses:
                ts = statuses[key]["timestamp"]
                block_lines.append(f"{emoji} {label}\nAdded <t:{ts}:t>")
        for c in statuses.get("custom", []):
            ts = c["timestamp"]
            block_lines.append(f"📝 {c['text']}\nAdded <t:{ts}:t>")
        blocks.append((ch_id_str, ch_mention, "\n".join(block_lines)))
    if not blocks:
        return None
    return "\n\n────────────────────\n\n".join(
        f"{mention}\n{lines}" for _, mention, lines in blocks
    )


def _build_statuslist_view(guild_data, invoker_id, guild):
    cs = guild_data.get("channel_statuses", {})
    entries = []
    for ch_id_str, statuses in cs.items():
        ch_id = int(ch_id_str)
        for key in BUILTIN_STATUSES:
            if key in statuses:
                entries.append((ch_id, key, statuses[key]["timestamp"], statuses[key]["moderator"], None))
        for ci, c in enumerate(statuses.get("custom", [])):
            entries.append((ch_id, "custom", c["timestamp"], c["moderator"], ci))
    if not entries:
        return None
    return StatusListClearView(entries, invoker_id, guild)


# ── Embed builder ────────────────────────────────────────────────────────────

def _build_status_embed(channel_name, channel_id, guild_data):
    desc = build_status_description(guild_data, channel_id)
    return info_embed(title=f"Status Manager — #{channel_name}", description=desc)


# ── Cog ──────────────────────────────────────────────────────────────────────

class Status(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="statuslist")
    @commands.has_permissions(administrator=True)
    async def statuslist(self, ctx):
        """Show all Role Channels that currently have active statuses."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        content = _build_statuslist_content(guild_data, ctx.guild)
        if not content:
            return await ctx.send("No active statuses.")
        view = _build_statuslist_view(guild_data, ctx.author.id, ctx.guild)
        if view is None:
            await ctx.send(content)
        else:
            await ctx.send(content, view=view)

    @commands.hybrid_command(name="status")
    @commands.has_permissions(administrator=True)
    async def status(self, ctx, *, subcommand: str = None):
        """Open the Status Manager for this channel, or use .status clear to clear all."""
        if subcommand and subcommand.lower() == "clear":
            guild_data = load_guild_data(ctx.guild.id)
            if not guild_data:
                return await ctx.send("Guild data not loaded.")
            clear_all_statuses(guild_data, ctx.channel.id)
            save_guild_data(ctx.guild.id, guild_data)
            await _log_status_change(ctx.guild, ctx.channel.id, "Cleared", "All statuses", ctx.author)
            return await ctx.send(f"All statuses cleared for {ctx.channel.mention}.")
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.", ephemeral=True)
        embed = _build_status_embed(ctx.channel.name, ctx.channel.id, guild_data)
        view = StatusManagerView(ctx.channel.id, ctx.channel.name, ctx.author.id)
        await ctx.send(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Status(bot))
