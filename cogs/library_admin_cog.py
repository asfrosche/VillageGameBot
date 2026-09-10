import os
import discord
from discord.ext import commands
from typing import List, Tuple
import re
import asyncio
import math

from .library_cog import (
    LIBRARIAN_IDS,
    EMBED_COLOR,
    EMBED_FOOTER_TEXT,
    EMBED_FOOTER_ICON,
    TEAMS,
    LibraryDatabase,
)


# =============================================================================
# ADMIN VIEWS — used exclusively by .libadmin
# =============================================================================


def _admin_paginate_fields(embed: discord.Embed, name: str, lines: list, max_chars: int = 1024):
    chunk, current_len, field_num = [], 0, 0
    for line in lines:
        if current_len + len(line) > max_chars:
            embed.add_field(
                name=name if field_num == 0 else f"{name} (cont.)",
                value="".join(chunk) or "*—*",
                inline=False,
            )
            chunk, current_len, field_num = [], 0, field_num + 1
        chunk.append(line)
        current_len += len(line)
    embed.add_field(
        name=name if field_num == 0 else f"{name} (cont.)",
        value="".join(chunk) or "*—*",
        inline=False,
    )


class AdminGameSelectView(discord.ui.View):
    def __init__(self, games: List[Tuple[int, str]], db, bot, page: int = 0):
        super().__init__(timeout=300)
        self.games = games
        self.db = db
        self.bot = bot
        self.page = page
        self.max_page = max(0, math.ceil(len(games) / 10) - 1)

        if self.max_page > 0:
            self.prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.primary, disabled=True)
            self.prev_btn.callback = self._prev_page
            self.add_item(self.prev_btn)

            self.next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary)
            self.next_btn.callback = self._next_page
            self.add_item(self.next_btn)

    def get_embed(self) -> discord.Embed:
        start = self.page * 10
        end = min(start + 10, len(self.games))
        page_games = self.games[start:end]

        embed = discord.Embed(
            title="📚 [ADMIN] Game Library — Select a Game",
            description="Use the button below to enter the game number you want to edit.",
            color=EMBED_COLOR,
        )

        games_text = ""
        for game_num, game_name in page_games:
            winners = self.db.get_winning_teams(game_num)
            winner_str = f" | 🏆 {', '.join(winners)}" if winners else ""
            games_text += f"**{game_num}** | {game_name.replace('-', ' ').title()}{winner_str}\n"

        embed.add_field(name="Available Games", value=games_text or "*No games*", inline=False)

        footer_extra = f" | Page {self.page + 1}/{self.max_page + 1}" if self.max_page > 0 else ""
        embed.set_footer(text=f"{EMBED_FOOTER_TEXT}{footer_extra}", icon_url=EMBED_FOOTER_ICON)
        return embed

    async def _prev_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self._refresh(interaction)

    async def _next_page(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction):
        if self.max_page > 0:
            self.prev_btn.disabled = self.page == 0
            self.next_btn.disabled = self.page == self.max_page
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢 Enter Game Number", style=discord.ButtonStyle.success, row=1)
    async def open_game_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AdminGameNumberModal(self.games, self.db, self.bot)
        )


class AdminGameNumberModal(discord.ui.Modal, title="Enter Game Number"):
    def __init__(self, games, db, bot):
        super().__init__()
        self.games = games
        self.db = db
        self.bot = bot

    game_number = discord.ui.TextInput(
        label="Game Number",
        placeholder="e.g. 42",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            game_num = int(self.game_number.value)
        except ValueError:
            await interaction.response.send_message("❌ Enter a valid number!", ephemeral=True)
            return

        game_data = next((g for g in self.games if g[0] == game_num), None)
        if not game_data:
            await interaction.response.send_message("❌ Game not found!", ephemeral=True)
            return

        view = AdminTeamSelectView(game_num, game_data[1], self.db, self.bot)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class AdminTeamSelectView(discord.ui.View):
    def __init__(self, game_number: int, game_name: str, db, bot, selected_team: int = 1):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.db = db
        self.bot = bot
        self.selected_team = selected_team

    def get_embed(self) -> discord.Embed:
        roles_basic = self.db.get_roles_by_team(self.game_number, self.selected_team)

        embed = discord.Embed(
            title=f"🔧 [ADMIN] {self.game_number} — {self.game_name.replace('-', ' ').title()}",
            description=f"**Team: {TEAMS[self.selected_team]}**\n\nSelect a team or enter a Role ID.",
            color=EMBED_COLOR,
        )

        if roles_basic:
            lines = []
            for role_id, role_name, player_name, count_flag in roles_basic:
                role_details = self.db.get_role_details(self.game_number, role_id)
                if role_details and role_details.get("count", 1):
                    is_mvp = bool(role_details.get("mvp"))
                    if role_details["win"]:
                        win_emoji = "🏆⭐" if is_mvp else "🏆"
                    else:
                        win_emoji = "❌⭐" if is_mvp else "❌"
                    emoji_part = f" {win_emoji}"
                else:
                    emoji_part = " ⛔"
                player_str = f" — {player_name}{emoji_part}" if player_name else emoji_part
                lines.append(f"**{role_id}** — {role_name}{player_str}\n")

            _admin_paginate_fields(embed, f"Roles ({len(roles_basic)})", lines)
        else:
            embed.add_field(name="Roles", value="*No roles found for this team.*", inline=False)

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        return embed

    @discord.ui.select(
        placeholder="Select a team...",
        options=[
            discord.SelectOption(label="Village",       value="1", emoji="🏘️"),
            discord.SelectOption(label="Evil",          value="2", emoji="😈"),
            discord.SelectOption(label="Random Killer", value="3", emoji="🔪"),
            discord.SelectOption(label="Neutral",       value="4", emoji="⚖️"),
            discord.SelectOption(label="Bonus/Extra",   value="5", emoji="⭐"),
        ],
        row=0,
    )
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_team = int(select.values[0])
        new_view = AdminTeamSelectView(
            self.game_number, self.game_name, self.db, self.bot, self.selected_team
        )
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)

    @discord.ui.button(label="🔢 Enter Role ID", style=discord.ButtonStyle.primary, row=2)
    async def enter_role_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AdminRoleIDModal(self.game_number, self.game_name, self.db, self.bot)
        )

    @discord.ui.button(label="↩️ Back to Games", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        games = self.db.get_all_games()
        view = AdminGameSelectView(games, self.db, self.bot)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class AdminRoleIDModal(discord.ui.Modal, title="Enter Role ID"):
    def __init__(self, game_number, game_name, db, bot):
        super().__init__()
        self.game_number = game_number
        self.game_name = game_name
        self.db = db
        self.bot = bot

    role_id = discord.ui.TextInput(
        label="Role ID",
        placeholder="e.g. 7",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
        except ValueError:
            await interaction.response.send_message("❌ Enter a valid number!", ephemeral=True)
            return

        role_data = self.db.get_role_details(self.game_number, role_id)
        if not role_data:
            await interaction.response.send_message("❌ Role not found!", ephemeral=True)
            return

        roles = self.db.get_roles_by_team(self.game_number, role_data["team"])
        try:
            index = next(i for i, r in enumerate(roles) if r[0] == role_id)
        except StopIteration:
            await interaction.response.send_message("❌ Role not found in the list.", ephemeral=True)
            return

        view = AdminRoleDescriptionView(
            self.game_number, self.game_name, roles, index, self.db, self.bot
        )
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class AdminRoleDescriptionView(discord.ui.View):
    _EDIT_OPTIONS = [
        discord.SelectOption(label="role_name",       value="role_name",       description="Role name",                       emoji="📛"),
        discord.SelectOption(label="team",            value="team",            description="Team (1=Village … 5=Bonus)",      emoji="🎯"),
        discord.SelectOption(label="player",          value="player",          description="Player via @mention or name",     emoji="👤"),
        discord.SelectOption(label="player_id",       value="player_id",       description="Discord ID of the player (number)",emoji="🪪"),
        discord.SelectOption(label="sponsor",         value="sponsor",         description="Sponsor via @mention or name",    emoji="💼"),
        discord.SelectOption(label="sponsor_id",      value="sponsor_id",      description="Discord ID of the sponsor (number)",emoji="🪪"),
        discord.SelectOption(label="win",             value="win",             description="Win — 1=yes  0=no",              emoji="🏆"),
        discord.SelectOption(label="count",           value="count",           description="Count in stats — 1=yes  0=no",   emoji="📊"),
        discord.SelectOption(label="mvp",             value="mvp",             description="MVP — 1=yes  0=no",              emoji="⭐"),
        discord.SelectOption(label="description1",    value="description1",    description="First description (or 'none')",   emoji="📜"),
        discord.SelectOption(label="description2",    value="description2",    description="Second description (or 'none')",  emoji="📜"),
        discord.SelectOption(label="description3",    value="description3",    description="Third description (or 'none')",   emoji="📜"),
        discord.SelectOption(label="description4",    value="description4",    description="Fourth description (or 'none')",  emoji="📜"),
    ]

    def __init__(self, game_number: int, game_name: str, roles: list, current_index: int, db, bot):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.roles = roles
        self.current_index = current_index
        self.db = db
        self.bot = bot
        self.current_desc = 1
        self._update_available_descs()

    def _update_available_descs(self):
        role_data = self.get_role_data()
        self.available_descs = [
            i for i in range(1, 5)
            if role_data.get(f"description{i}") and str(role_data[f"description{i}"]).strip()
        ]
        if not self.available_descs:
            self.available_descs = [1]
        if self.current_desc not in self.available_descs:
            self.current_desc = self.available_descs[0]

    def get_role_data(self) -> dict:
        role_id = self.roles[self.current_index][0]
        return self.db.get_role_details(self.game_number, role_id)

    def get_embed(self) -> discord.Embed:
        role = self.get_role_data()

        description_text = role.get(f"description{self.current_desc}") or "*No description available.*"
        if not str(description_text).strip():
            description_text = "*No description available.*"

        embed = discord.Embed(
            title=f"🔧 {role['role_name']}",
            description=description_text,
            color=EMBED_COLOR,
        )

        def _fmt(val):
            return f"`{val}`" if val is not None else "`—`"

        db_info = (
            f"**role_id** → {_fmt(role.get('role_id'))}\n"
            f"**role_name** → `{role.get('role_name', '—')}`\n"
            f"**team** → `{role.get('team')}` — {TEAMS.get(role.get('team'), '?')}\n"
            f"**player_name** → `{role.get('player_name') or '—'}`\n"
            f"**player_id** → {_fmt(role.get('player_id'))}\n"
            f"**sponsor_name** → `{role.get('sponsor_name') or '—'}`\n"
            f"**sponsor_id** → {_fmt(role.get('sponsor_id'))}\n"
            f"**win** → {'✅ `1`' if role.get('win') else '❌ `0`'}\n"
            f"**mvp** → {'⭐ `1`' if role.get('mvp') else '— `0`'}\n"
            f"**count** → {'✅ `1`' if role.get('count', 1) else '❌ `0`'}"
        )
        embed.add_field(name="🗃️ Database Fields", value=db_info, inline=False)

        game_str = f"{self.game_number} — {self.game_name.replace('-', ' ').title()}"
        embed.add_field(
            name="ℹ️ Context",
            value=(
                f"**Game:** {game_str}\n"
                f"**Role:** {self.current_index + 1}/{len(self.roles)} "
                f"(team {TEAMS.get(role.get('team'), '?')})"
            ),
            inline=False,
        )

        max_desc = max(self.available_descs)
        embed.set_footer(
            text=f"{EMBED_FOOTER_TEXT} | Description {self.current_desc}/{max_desc}",
            icon_url=EMBED_FOOTER_ICON,
        )
        return embed

    @discord.ui.button(label="◀ Desc", style=discord.ButtonStyle.primary, row=0)
    async def prev_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        idx = self.available_descs.index(self.current_desc)
        if idx > 0:
            self.current_desc = self.available_descs[idx - 1]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Desc ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        idx = self.available_descs.index(self.current_desc)
        if idx < len(self.available_descs) - 1:
            self.current_desc = self.available_descs[idx + 1]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="◀◀ Role", style=discord.ButtonStyle.secondary, row=1)
    async def prev_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0:
            self.current_index -= 1
            self._update_available_descs()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Role ▶▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.roles) - 1:
            self.current_index += 1
            self._update_available_descs()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="↩️ Back to Roles", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_role = self.get_role_data()
        view = AdminTeamSelectView(
            self.game_number, self.game_name, self.db, self.bot,
            selected_team=current_role["team"],
        )
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.select(
        placeholder="✏️ Edit a database field...",
        options=_EDIT_OPTIONS,
        row=3,
    )
    async def edit_field_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id not in LIBRARIAN_IDS:
            await interaction.response.send_message(
                "❌ You don't have permission to edit fields!", ephemeral=True
            )
            return

        field = select.values[0]
        role_id = self.roles[self.current_index][0]

        team_opts = " · ".join(f"**{k}**={v}" for k, v in TEAMS.items())
        prompts = {
            "role_name":    "Write the **new name** for the role.",
            "team":         f"Write the **team number**:\n{team_opts}",
            "player":       (
                "Mention the player **`@user`** → saves name + Discord ID\n"
                "Write just the **name** → saves only the name (player_id unchanged)\n"
                "Write **`none`** → removes player_name and player_id"
            ),
            "player_id":    "Write the numeric **Discord ID** of the player (or `none` to remove).",
            "sponsor":      (
                "Mention the sponsor **`@user`** → saves name + Discord ID\n"
                "Write just the **name** → saves only the name (sponsor_id unchanged)\n"
                "Write **`none`** → removes sponsor_name and sponsor_id"
            ),
            "sponsor_id":   "Write the numeric **Discord ID** of the sponsor (or `none` to remove).",
            "win":          "Write **`1`** (win) or **`0`** (loss).",
            "count":        "Write **`1`** (count in stats) or **`0`** (exclude).",
            "mvp":          "Write **`1`** (MVP) or **`0`** (not MVP).",
            "description1": "Write text for **description1**, or `none` to remove.",
            "description2": "Write text for **description2**, or `none` to remove.",
            "description3": "Write text for **description3**, or `none` to remove.",
            "description4": "Write text for **description4**, or `none` to remove.",
        }
        prompt_text = prompts.get(field, f"Write the new value for **{field}**.")

        await interaction.response.defer()
        prompt_msg = await interaction.channel.send(
            f"<@{interaction.user.id}> ✏️ **Field:** `{field}`\n{prompt_text}\n"
            f"_(You have 60 seconds. Write your message below.)_"
        )

        def _check(m: discord.Message):
            return (
                m.author.id == interaction.user.id
                and m.channel.id == interaction.channel.id
            )

        try:
            user_msg = await self.bot.wait_for("message", check=_check, timeout=60)
        except asyncio.TimeoutError:
            try:
                await prompt_msg.delete()
            except Exception:
                pass
            await interaction.followup.send(
                "⌛ Time expired. No changes were made.", ephemeral=True
            )
            return

        value_str = user_msg.content.strip()
        feedback = ""

        try:
            if field == "player":
                mention_match = re.search(r"<@!?(\d+)>", value_str)
                if mention_match:
                    mid = int(mention_match.group(1))
                    member = await interaction.guild.fetch_member(mid)
                    self.db.update_field(self.game_number, role_id, "player_name", member.display_name)
                    self.db.update_field(self.game_number, role_id, "player_id", member.id)
                    feedback = f"✅ Player → **{member.display_name}** (ID: `{member.id}`)"
                elif value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, "player_name", None)
                    self.db.update_field(self.game_number, role_id, "player_id", None)
                    feedback = "✅ Player removed (player_name and player_id = NULL)."
                else:
                    self.db.update_field(self.game_number, role_id, "player_name", value_str)
                    feedback = f"✅ player_name → **{value_str}** _(player_id unchanged)_"

            elif field == "sponsor":
                mention_match = re.search(r"<@!?(\d+)>", value_str)
                if mention_match:
                    mid = int(mention_match.group(1))
                    member = await interaction.guild.fetch_member(mid)
                    self.db.update_field(self.game_number, role_id, "sponsor_name", member.display_name)
                    self.db.update_field(self.game_number, role_id, "sponsor_id", member.id)
                    feedback = f"✅ Sponsor → **{member.display_name}** (ID: `{member.id}`)"
                elif value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, "sponsor_name", None)
                    self.db.update_field(self.game_number, role_id, "sponsor_id", None)
                    feedback = "✅ Sponsor removed (sponsor_name and sponsor_id = NULL)."
                else:
                    self.db.update_field(self.game_number, role_id, "sponsor_name", value_str)
                    feedback = f"✅ sponsor_name → **{value_str}** _(sponsor_id unchanged)_"

            elif field == "player_id":
                if value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, "player_id", None)
                    feedback = "✅ player_id removed (NULL)."
                else:
                    val = int(value_str)
                    self.db.update_field(self.game_number, role_id, "player_id", val)
                    feedback = f"✅ player_id → `{val}`"

            elif field == "sponsor_id":
                if value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, "sponsor_id", None)
                    feedback = "✅ sponsor_id removed (NULL)."
                else:
                    val = int(value_str)
                    self.db.update_field(self.game_number, role_id, "sponsor_id", val)
                    feedback = f"✅ sponsor_id → `{val}`"

            elif field == "team":
                team_val = int(value_str)
                if team_val not in TEAMS:
                    raise ValueError(f"Invalid team `{team_val}`. Use: {team_opts}")
                self.db.update_field(self.game_number, role_id, "team", team_val)
                self.roles = self.db.get_roles_by_team(self.game_number, team_val)
                self.current_index = 0
                feedback = f"✅ team → `{team_val}` — **{TEAMS[team_val]}**"

            elif field in ("win", "count", "mvp"):
                val = int(value_str)
                if val not in (0, 1):
                    raise ValueError("Use `1` (yes) or `0` (no).")
                self.db.update_field(self.game_number, role_id, field, val)
                icons = {"win": "🏆", "count": "📊", "mvp": "⭐"}
                feedback = f"{icons[field]} **{field}** → `{'1 (yes)' if val else '0 (no)'}`"

            elif field.startswith("description"):
                if value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, field, None)
                    feedback = f"✅ **{field}** removed (NULL)."
                else:
                    self.db.update_field(self.game_number, role_id, field, value_str)
                    preview = value_str[:80] + ("…" if len(value_str) > 80 else "")
                    feedback = f"✅ **{field}** updated: `{preview}`"

            else:
                self.db.update_field(self.game_number, role_id, field, value_str)
                feedback = f"✅ **{field}** → `{value_str[:100]}`"

        except Exception as exc:
            for m in (prompt_msg, user_msg):
                try:
                    await m.delete()
                except Exception:
                    pass
            await interaction.followup.send(f"❌ Error: `{exc}`", ephemeral=True)
            return

        for m in (prompt_msg, user_msg):
            try:
                await m.delete()
            except Exception:
                pass

        self._update_available_descs()
        new_view = AdminRoleDescriptionView(
            self.game_number, self.game_name, self.roles,
            self.current_index, self.db, self.bot,
        )
        await interaction.message.edit(embed=new_view.get_embed(), view=new_view)
        await interaction.followup.send(feedback, ephemeral=True)


# ============================================================================
# ADMIN COG
# ============================================================================

class GameLibraryAdmin(commands.Cog):
    """Cog for the English library admin interface."""

    def __init__(self, bot):
        self.bot = bot
        self.db = LibraryDatabase()

    def is_librarian(self, user_id: int) -> bool:
        return user_id in LIBRARIAN_IDS

    @commands.group(name="libadmin", invoke_without_command=True)
    async def libadmin(self, ctx):
        """[ADMIN] Browse and edit the English library (librarian only)."""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission to use this command!")
            return
        games = self.db.get_all_games()
        if not games:
            await ctx.send("❌ The library is empty!")
            return
        view = AdminGameSelectView(games, self.db, self.bot)
        await ctx.send(embed=view.get_embed(), view=view)


async def setup(bot):
    await bot.add_cog(GameLibraryAdmin(bot))
