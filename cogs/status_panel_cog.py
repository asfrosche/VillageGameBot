"""Status Panel cog: interactive Online/AFK member status board.

Every member is shown on a single page as one toggle button. The button
displays the member's current state (🟢 Online / 🌙 AFK) and clicking it
flips that member's status. Members can only toggle their own status;
admins can add/remove members. No embed, no pagination: buttons only.

The panel persists in per-guild data and survives bot restarts.
"""

import discord
from discord.ext import commands
from discord.ui import Button, Select, UserSelect, View

from cogs.data_utils import load_guild_data, save_guild_data

PANEL_KEY = "status_panel"
ONLINE = "online"
AFK = "afk"
STATUS_LABELS = {ONLINE: "Online", AFK: "AFK"}
STATUS_EMOJIS = {ONLINE: "🟢", AFK: "🌙"}
MAX_MEMBERS = 20  # 4 rows of toggle buttons; row 4 is reserved for admin buttons


def panel_state(guild_data):
    """Return (and create, if needed) the status panel state dict."""
    panel = guild_data.setdefault(PANEL_KEY, {})
    panel.setdefault("members", {})
    return panel


def get_member_status(guild_data, user_id):
    """Return the stored status ("online"/"afk") for a member, or None."""
    return panel_state(guild_data)["members"].get(str(user_id))


def _member_name(guild, user_id, fallback=None):
    if guild:
        member = guild.get_member(int(user_id))
        if member:
            return member.nick or member.display_name
    return fallback or str(user_id)


# ── Content builder (plain text, no embed) ───────────────────────────────────

def build_panel_content(guild_data, guild=None):
    """Return the plain-text message body that accompanies the buttons."""
    members = panel_state(guild_data)["members"]
    total = len(members)
    online = sum(1 for status in members.values() if status == ONLINE)
    afk = total - online
    if total:
        return f"🟢 **Status Panel**\n`🟢 {online} online · 🌙 {afk} afk`"
    return "🟢 **Status Panel**\n`No members yet — admins can add members below.`"


def _toggle_label(name, status):
    name = name[:60]
    return f"{name} · {STATUS_EMOJIS[status]} {STATUS_LABELS[status]}"


def overseer_role_name(guild_data):
    return (guild_data or {}).get("overseer_role_name") or "Overseer"


def overseer_candidates(guild, guild_data):
    """Members holding the overseer role who are not yet on the panel (bots included)."""
    role = discord.utils.get(guild.roles, name=overseer_role_name(guild_data))
    if role is None:
        return []
    on_panel = panel_state(guild_data)["members"]
    return [m for m in role.members if str(m.id) not in on_panel]


# ── View ─────────────────────────────────────────────────────────────────────

class StatusPanelView(View):
    def __init__(self, bot, guild_id, mode=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.mode = mode  # None | "add" | "remove"
        self._rebuild()

    # ── Guards ────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_admin(interaction):
        perms = getattr(interaction.user, "guild_permissions", None)
        return perms is not None and perms.administrator

    def _is_panel_member(self, user_id):
        gd = load_guild_data(self.guild_id) or {}
        return str(user_id) in panel_state(gd)["members"]

    async def interaction_check(self, interaction):
        if self._is_admin(interaction) or self._is_panel_member(interaction.user.id):
            return True
        await interaction.response.send_message(
            "You're not on this status panel.", ephemeral=True,
        )
        return False

    # ── Rebuild ───────────────────────────────────────────────────────────────

    def _rebuild(self):
        self.clear_items()
        if self.mode == "add":
            self._build_add_mode()
            return
        if self.mode == "remove":
            self._build_remove_mode()
            return
        self._build_main_mode()

    def _build_main_mode(self):
        gd = load_guild_data(self.guild_id) or {}
        members = panel_state(gd)["members"]
        guild = self.bot.get_guild(self.guild_id) if self.bot else None
        ordered = sorted(members.keys(), key=lambda uid: (members[uid] != ONLINE, str(uid)))[:MAX_MEMBERS]
        for idx, uid in enumerate(ordered):
            name = _member_name(guild, uid, uid)
            status = members[uid]
            btn = Button(
                label=_toggle_label(name, status),
                style=discord.ButtonStyle.success if status == ONLINE else discord.ButtonStyle.secondary,
                row=idx // 5,
                custom_id=f"sp_toggle_{uid}",
            )
            btn.callback = self._make_toggle_cb(int(uid))
            self.add_item(btn)
        self._build_admin_row()

    def _build_admin_row(self):
        add_btn = Button(
            label="Add Member", emoji="➕", style=discord.ButtonStyle.primary,
            row=4, custom_id="sp_add",
        )
        add_btn.callback = self._make_add_btn_cb()
        rem_btn = Button(
            label="Remove", emoji="➖", style=discord.ButtonStyle.danger,
            row=4, custom_id="sp_remove",
        )
        rem_btn.callback = self._make_remove_btn_cb()
        for btn in (add_btn, rem_btn):
            self.add_item(btn)

    def _build_add_mode(self):
        us = UserSelect(
            placeholder="Select a member to add…",
            min_values=1, max_values=1,
            row=0, custom_id="sp_add_user",
        )
        us.callback = self._add_user_cb(us)
        self.add_item(us)
        cancel = Button(
            label="Cancel", emoji="↩️", style=discord.ButtonStyle.secondary,
            row=1, custom_id="sp_add_cancel",
        )
        cancel.callback = self._make_cancel_cb()
        self.add_item(cancel)

    def _build_remove_mode(self):
        gd = load_guild_data(self.guild_id) or {}
        members = panel_state(gd)["members"]
        guild = self.bot.get_guild(self.guild_id) if self.bot else None
        ordered = sorted(members.keys(), key=lambda uid: (members[uid] != ONLINE, str(uid)))[:MAX_MEMBERS]
        options = [
            discord.SelectOption(
                label=_member_name(guild, uid, uid)[:100],
                value=uid,
                emoji=STATUS_EMOJIS.get(members[uid], "❓"),
            )
            for uid in ordered
        ]
        sel = Select(
            placeholder="Select a member to remove…",
            options=options, min_values=1, max_values=1,
            row=0, custom_id="sp_remove_select",
        )
        sel.callback = self._remove_member_cb(sel)
        self.add_item(sel)
        cancel = Button(
            label="Cancel", emoji="↩️", style=discord.ButtonStyle.secondary,
            row=1, custom_id="sp_remove_cancel",
        )
        cancel.callback = self._make_cancel_cb()
        self.add_item(cancel)

    # ── Callback factories ────────────────────────────────────────────────────

    def _make_toggle_cb(self, member_id):
        async def callback(interaction):
            if interaction.user.id != member_id:
                return await interaction.response.send_message(
                    "You can only change your own status.", ephemeral=True,
                )
            gd = load_guild_data(self.guild_id) or {}
            panel = panel_state(gd)
            uid = str(member_id)
            if uid not in panel["members"]:
                return await interaction.response.send_message(
                    "You're no longer on this panel.", ephemeral=True,
                )
            panel["members"][uid] = AFK if panel["members"][uid] == ONLINE else ONLINE
            save_guild_data(self.guild_id, gd)
            await self._edit_panel(interaction)
        return callback

    def _make_add_btn_cb(self):
        async def callback(interaction):
            if not self._is_admin(interaction):
                return await interaction.response.send_message("Admins only.", ephemeral=True)
            await self._edit_panel(interaction, mode="add")
        return callback

    def _make_remove_btn_cb(self):
        async def callback(interaction):
            if not self._is_admin(interaction):
                return await interaction.response.send_message("Admins only.", ephemeral=True)
            await self._edit_panel(interaction, mode="remove")
        return callback

    def _make_cancel_cb(self):
        async def callback(interaction):
            if not self._is_admin(interaction):
                return await interaction.response.send_message("Admins only.", ephemeral=True)
            await self._edit_panel(interaction, mode=None)
        return callback

    def _add_user_cb(self, select):
        async def callback(interaction):
            if not self._is_admin(interaction):
                return await interaction.response.send_message("Admins only.", ephemeral=True)
            values = interaction.data.get("values", [])
            if not values:
                return await interaction.response.defer()
            uid = str(values[0])
            gd = load_guild_data(self.guild_id) or {}
            panel = panel_state(gd)
            if uid in panel["members"]:
                return await interaction.response.send_message(
                    "That member is already on the panel.", ephemeral=True,
                )
            if len(panel["members"]) >= MAX_MEMBERS:
                return await interaction.response.send_message(
                    f"The panel is full ({MAX_MEMBERS} members).", ephemeral=True,
                )
            panel["members"][uid] = ONLINE
            save_guild_data(self.guild_id, gd)
            guild = self.bot.get_guild(self.guild_id) if self.bot else None
            name = _member_name(guild, uid, uid)
            await self._edit_panel(interaction, mode=None)
            try:
                await interaction.followup.send(f"➕ Added **{name}** to the panel.", ephemeral=True)
            except Exception:
                pass
        return callback

    def _remove_member_cb(self, select):
        async def callback(interaction):
            if not self._is_admin(interaction):
                return await interaction.response.send_message("Admins only.", ephemeral=True)
            values = interaction.data.get("values", [])
            if not values:
                return await interaction.response.defer()
            gd = load_guild_data(self.guild_id) or {}
            panel = panel_state(gd)
            for value in values:
                panel["members"].pop(str(value), None)
            save_guild_data(self.guild_id, gd)
            await self._edit_panel(interaction, mode=None)
            try:
                await interaction.followup.send("➖ Removed member(s) from the panel.", ephemeral=True)
            except Exception:
                pass
        return callback

    # ── Edit panel in place ──────────────────────────────────────────────────

    async def _edit_panel(self, interaction, *, mode=None):
        if mode is not None:
            self.mode = mode
        gd = load_guild_data(self.guild_id) or {}
        view = StatusPanelView(self.bot, self.guild_id, mode=self.mode)
        content = build_panel_content(gd, interaction.guild)
        message_id = interaction.message.id if interaction.message else None

        if self.bot:
            try:
                self.bot.remove_view(self)
            except Exception:
                pass

        try:
            await interaction.response.edit_message(content=content, view=view)
        except discord.NotFound:
            return

        if self.bot and message_id:
            self.bot.add_view(view, message_id=message_id)


class ConfirmOverseersView(View):
    """Yes/Skip prompt shown before overseers are bulk-added to the panel."""

    def __init__(self, author_id):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.confirmed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who ran the command can answer this.", ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Add them", emoji="➕", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction, button):
        self.stop()
        await interaction.response.defer()


# ── Cog ───────────────────────────────────────────────────────────────────────

class StatusPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._registered = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self._registered:
            return
        self._registered = True
        self._register_persistent_views()

    def _register_persistent_views(self):
        """Re-attach views to existing panels so buttons survive restarts."""
        if self.bot is None:
            return
        for guild in self.bot.guilds:
            gd = load_guild_data(guild.id)
            if not gd:
                continue
            panel = gd.get(PANEL_KEY)
            if not panel or not panel.get("message_id"):
                continue
            try:
                view = StatusPanelView(self.bot, guild.id)
                self.bot.add_view(view, message_id=int(panel["message_id"]))
            except Exception:
                pass

    async def _offer_overseers(self, ctx, gd, panel):
        """Ask before adding every overseer-role member to the panel."""
        candidates = overseer_candidates(ctx.guild, gd)
        if not candidates:
            return
        role_name = overseer_role_name(gd)
        room = MAX_MEMBERS - len(panel["members"])
        if room <= 0:
            return await ctx.send(
                f"ℹ️ {len(candidates)} member(s) with the **{role_name}** role were not added: "
                f"the panel is full ({MAX_MEMBERS} members)."
            )
        to_add = candidates[:room]
        skipped = len(candidates) - len(to_add)
        lines = "\n".join(
            f"• {m.display_name}{' 🤖' if m.bot else ''}" for m in to_add
        )
        text = (
            f"Found **{len(candidates)}** member(s) with the **{role_name}** role who are not on the panel:\n"
            f"{lines}\nAdd them to the panel as 🟢 Online?"
        )
        if skipped:
            text += f"\n⚠️ Only {room} fit under the {MAX_MEMBERS}-member cap; {skipped} will be skipped."
        view = ConfirmOverseersView(ctx.author.id)
        prompt = await ctx.send(text, view=view)
        await view.wait()
        if not view.confirmed:
            return await prompt.edit(content="Skipped adding overseers to the panel.", view=None)
        for m in to_add:
            panel["members"][str(m.id)] = ONLINE
        save_guild_data(ctx.guild.id, gd)
        await prompt.edit(content=f"✅ Added {len(to_add)} overseer(s) to the panel.", view=None)

    @commands.command(name="statuspanel", aliases=["sp"])
    @commands.has_permissions(administrator=True)
    async def statuspanel(self, ctx):
        """Post or refresh the Online/AFK member status panel."""
        gd = load_guild_data(ctx.guild.id)
        if gd is None:
            return await ctx.send("Guild data not loaded.")

        panel = panel_state(gd)
        await self._offer_overseers(ctx, gd, panel)
        existing_msg = None
        if panel.get("channel_id") and panel.get("message_id"):
            ch = ctx.guild.get_channel(panel["channel_id"])
            if ch:
                try:
                    existing_msg = await ch.fetch_message(int(panel["message_id"]))
                except (discord.NotFound, discord.HTTPException):
                    existing_msg = None

        view = StatusPanelView(self.bot, ctx.guild.id)
        content = build_panel_content(gd, ctx.guild)

        if existing_msg is not None:
            try:
                await existing_msg.edit(content=content, view=view)
                self.bot.add_view(view, message_id=existing_msg.id)
                return await ctx.send("✅ Status panel refreshed.")
            except (discord.HTTPException, discord.Forbidden):
                pass

        msg = await ctx.send(content=content, view=view)
        panel["channel_id"] = msg.channel.id
        panel["message_id"] = msg.id
        save_guild_data(ctx.guild.id, gd)
        self.bot.add_view(view, message_id=msg.id)


async def setup(bot):
    await bot.add_cog(StatusPanel(bot))