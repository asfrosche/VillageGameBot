from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

DB_PATH = "db/calendar_en.db"
VIEW_TIMEOUT = 86400          # 10 minutes
GLOBAL_ADMINS: list[int] = []

BRAND_COLOUR = discord.Colour(0xFF3FB9)

# Import load_guild_data from your configuration cog.
# Adjust the import path to match your project structure.
try:
    from cogs.data_utils import load_guild_data
except ImportError:
    def load_guild_data(guild_id: int):  # type: ignore[misc]
        return None

# ── database ───────────────────────────────────────────────────────────────────

# Updated schema: guild_id added, CHECK on status removed (enforced by app)
DDL = """
CREATE TABLE IF NOT EXISTS Games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id         INTEGER NOT NULL,
    cohost_ids      TEXT    NOT NULL DEFAULT '',
    guild_id        TEXT    NOT NULL DEFAULT '',
    range_label     TEXT    NOT NULL,
    name            TEXT    NOT NULL DEFAULT '',
    description     TEXT    NOT NULL DEFAULT '',
    max_players     INTEGER NOT NULL DEFAULT 10,
    status          TEXT    NOT NULL DEFAULT 'pending',
    discord_invite  TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS Players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL REFERENCES Games(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL,
    role        TEXT    NOT NULL CHECK(role IN ('player','sponsor')),
    slot        INTEGER NOT NULL,
    UNIQUE(game_id, role, slot)
);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    # Create tables if they don't exist (fresh installs)
    with get_db() as conn:
        conn.executescript(DDL)

    # Migration: simple columns for pre-existing databases
    with get_db() as conn:
        for col, default in [("status", "'pending'"), ("discord_invite", "''")]:
            try:
                conn.execute(f"ALTER TABLE Games ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
            except sqlite3.OperationalError:
                pass  # column already exists

    # Migration: add guild_id and drop the old status CHECK constraint
    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in raw.execute("PRAGMA table_info(Games)").fetchall()}
        if "guild_id" not in cols:
            raw.executescript("""
                CREATE TABLE Games_new (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    host_id         INTEGER NOT NULL,
                    cohost_ids      TEXT    NOT NULL DEFAULT '',
                    guild_id        TEXT    NOT NULL DEFAULT '',
                    range_label     TEXT    NOT NULL,
                    name            TEXT    NOT NULL DEFAULT '',
                    description     TEXT    NOT NULL DEFAULT '',
                    max_players     INTEGER NOT NULL DEFAULT 10,
                    status          TEXT    NOT NULL DEFAULT 'pending',
                    discord_invite  TEXT    NOT NULL DEFAULT '',
                    created_at      TEXT    NOT NULL
                );
                INSERT INTO Games_new
                    (id, host_id, cohost_ids, range_label, name, description,
                     max_players, status, discord_invite, created_at)
                SELECT id, host_id, cohost_ids, range_label, name, description,
                       max_players, status, discord_invite, created_at
                FROM Games;
                DROP TABLE Games;
                ALTER TABLE Games_new RENAME TO Games;
            """)
    finally:
        raw.close()


# ── helpers ────────────────────────────────────────────────────────────────────

def _parse_ids(raw: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d{6,}", raw)]


def _is_host(game: sqlite3.Row, user_id: int) -> bool:
    if game["host_id"] == user_id:
        return True
    return user_id in _parse_ids(game["cohost_ids"] or "")


def _can_manage(game: sqlite3.Row, user_id: int) -> bool:
    return user_id in GLOBAL_ADMINS or _is_host(game, user_id)


def _range_label_from_value(value: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-H([12])$", value)
    if m:
        year, month, half = int(m.group(1)), int(m.group(2)), m.group(3)
        try:
            month_name = datetime(year, month, 1).strftime("%B %Y")
            half_str = "First Half" if half == "1" else "Second Half"
            return f"{month_name} - {half_str}"
        except ValueError:
            pass
    return value


def _display_to_value(text: str) -> str:
    text = text.strip()
    if re.match(r"^\d{4}-\d{2}-H[12]$", text):
        return text
    m = re.match(r"^(\w+)\s+(\d{4})\s*[-–]\s*(First|Second)\s+Half$", text, re.IGNORECASE)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %Y")
            half = "H1" if m.group(3).lower() == "first" else "H2"
            return f"{dt.year}-{dt.month:02d}-{half}"
        except ValueError:
            pass
    return text


def _status_emoji(status: str) -> str:
    return {
        "ongoing":  "🟢",
        "ended":    "🔴",
        "pending":  "⏳",
        "inviting": "🚪",
        "canceled": "❌",
    }.get(status or "pending", "⏳")


def _status_label(status: str) -> str:
    return {
        "ongoing":  "Ongoing",
        "ended":    "Ended",
        "pending":  "Pending",
        "inviting": "Players Joining...",
        "canceled": "Canceled",
    }.get(status or "pending", "Pending")


def _safe_get(row: sqlite3.Row, key: str, default: str = "") -> str:
    """Safely read a column even on not-yet-migrated databases."""
    try:
        return row[key] or default
    except (IndexError, KeyError):
        return default


# ── embeds ─────────────────────────────────────────────────────────────────────

def calendar_embed(games: list[sqlite3.Row]) -> discord.Embed:
    embed = discord.Embed(title="📅  Heartside Calendar", colour=BRAND_COLOUR)
    if not games:
        embed.description = "*No games scheduled yet. Use **Add Game** to create one!*"
        return embed

    sorted_games = sorted(games, key=lambda g: g["range_label"])
    blocks: list[str] = []
    for g in sorted_games:
        name   = g["name"] or f"Game #{g['id']}"
        status = _safe_get(g, "status", "pending")
        emoji  = _status_emoji(status)
        range_display = _range_label_from_value(g["range_label"])
        blocks.append(f"**{name}**\n{emoji} — {range_display}")

    embed.description = "\n\n".join(blocks)
    return embed


def game_detail_embed(game: sqlite3.Row, bot: commands.Bot) -> discord.Embed:
    name     = game["name"] or f"Game #{game['id']}"
    status   = _safe_get(game, "status", "pending")
    emoji    = _status_emoji(status)
    label_st = _status_label(status)
    embed    = discord.Embed(title=f"🎮  {name}", colour=BRAND_COLOUR)

    embed.add_field(name="Date Range", value=_range_label_from_value(game["range_label"]), inline=True)
    embed.add_field(name="Status",     value=f"{emoji} {label_st}", inline=True)

    invite = _safe_get(game, "discord_invite")
    embed.add_field(name="Discord Invite", value=invite or "—", inline=False)

    host_mention = f"<@{game['host_id']}>"
    cohost_ids   = _parse_ids(game["cohost_ids"] or "")
    cohost_str   = ", ".join(f"<@{c}>" for c in cohost_ids) if cohost_ids else "—"
    embed.add_field(name="Host",     value=host_mention, inline=False)
    embed.add_field(name="Co-Hosts", value=cohost_str,   inline=False)

    embed.add_field(name="Description", value=game["description"] or "—", inline=False)
    return embed


def playerlist_embed(game: sqlite3.Row, players: list[sqlite3.Row]) -> discord.Embed:
    name  = game["name"] or f"Game #{game['id']}"
    embed = discord.Embed(title=f"📋  Playerlist — {name}", colour=BRAND_COLOUR)
    max_p = game["max_players"]
    player_map = {(r["role"], r["slot"]): r["user_id"] for r in players}

    lines: list[str] = []
    for slot in range(1, max_p + 1):
        p_uid = player_map.get(("player",  slot))
        s_uid = player_map.get(("sponsor", slot))
        p_str = f"<@{p_uid}>" if p_uid else "Player: *Empty*"
        s_str = f"<@{s_uid}>" if s_uid else "Sponsor: *Empty*"
        lines.append(f"**{slot}.** {p_str}")
        lines.append(f"\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u2514 {s_str}")

    embed.description = "\n".join(lines) if lines else "*No players yet.*"
    return embed


# ── add-game wizard ────────────────────────────────────────────────────────────
#
# Flow (all ephemeral):
#   Step 1 – year select
#   Step 2 – month select
#   Step 3 – first/second half select
#   Step 4 – CoHostAndServerModal  (co-host IDs + Server ID)  + Continue button
#   Step 5 – AddGameDetailsModal   (name, description, max_players, discord_invite)
#
# After the modal is submitted the public calendar message is refreshed.

class CoHostAndServerModal(discord.ui.Modal, title="Co-Hosts & Server"):
    """First wizard modal: collects co-host IDs and the game Server ID."""

    cohost_input = discord.ui.TextInput(
        label="Co-Host IDs (optional)",
        placeholder="@user1 @user2   or   123456789, 987654321",
        required=False,
        max_length=300,
    )
    guild_id_input = discord.ui.TextInput(
        label="Game Server ID",
        placeholder="Numeric ID of the Discord server where the game takes place",
        required=False,
        max_length=30,
    )

    def __init__(self, wizard: "AddGameWizardView"):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        self.wizard.cohost_raw   = self.cohost_input.value.strip()
        self.wizard.guild_id_raw = self.guild_id_input.value.strip()

        parsed        = _parse_ids(self.wizard.cohost_raw)
        cohost_display = ", ".join(f"<@{c}>" for c in parsed) if parsed else "None"

        self.wizard._build_cohost_step()
        month_name = datetime(2000, self.wizard.month, 1).strftime("%B")
        half_label = "First Half" if self.wizard.half == "H1" else "Second Half"
        await interaction.response.edit_message(
            content=(
                f"**📅 New Game Setup**\n"
                f"**Date:** {month_name} {self.wizard.year} — {half_label}\n"
                f"**Co-Hosts:** {cohost_display}\n\n"
                "Click **Continue** to fill in the game details."
            ),
            view=self.wizard,
        )


class AddGameDetailsModal(discord.ui.Modal, title="New Game Details"):
    name_input = discord.ui.TextInput(
        label="Game Name",
        placeholder="e.g. The Reminiscence 7",
        max_length=100,
    )
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )
    max_players = discord.ui.TextInput(
        label="Max Players",
        placeholder="30",
        max_length=3,
    )
    discord_invite = discord.ui.TextInput(
        label="Discord Invite (optional)",
        placeholder="https://discord.gg/...",
        required=False,
        max_length=100,
    )

    def __init__(self, cog: "GameManagerEn", wizard: "AddGameWizardView"):
        super().__init__()
        self.cog    = cog
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_p = int(self.max_players.value.strip())
            if max_p < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Max Players must be a positive integer.", ephemeral=True
            )
            return

        range_value = f"{self.wizard.year}-{self.wizard.month:02d}-{self.wizard.half}"
        now_str     = datetime.now(timezone.utc).isoformat()

        with get_db() as conn:
            conn.execute(
                "INSERT INTO Games "
                "(host_id, cohost_ids, guild_id, range_label, name, description, "
                " max_players, discord_invite, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    interaction.user.id,
                    self.wizard.cohost_raw,
                    self.wizard.guild_id_raw,
                    range_value,
                    self.name_input.value.strip(),
                    self.description.value.strip(),
                    max_p,
                    self.discord_invite.value.strip(),
                    now_str,
                ),
            )

        await interaction.response.edit_message(
            content="✅ Game successfully added to the Heartside Calendar!", view=None
        )
        if self.wizard.calendar_message:
            new_view = CalendarView(self.cog, self.wizard.invoker_id)
            await self.wizard.calendar_message.edit(embed=new_view.build_embed(), view=new_view)


class AddGameWizardView(discord.ui.View):
    """Multi-step ephemeral wizard for creating a new game."""

    def __init__(
        self,
        cog: "GameManagerEn",
        invoker_id: int,
        calendar_message: discord.Message,
    ):
        super().__init__(timeout=300)
        self.cog              = cog
        self.invoker_id       = invoker_id
        self.calendar_message = calendar_message
        self.year:         Optional[int] = None
        self.month:        Optional[int] = None
        self.half:         Optional[str] = None
        self.cohost_raw:   str = ""
        self.guild_id_raw: str = ""
        self._build_year_select()

    async def _check_invoker(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "❌ This wizard was opened by someone else.", ephemeral=True
            )
            return False
        return True

    def _build_year_select(self):
        self.clear_items()
        now   = datetime.now(timezone.utc)
        years = [now.year, now.year + 1, now.year + 2]
        sel   = discord.ui.Select(
            placeholder="📅 Step 1 — Select a year…",
            options=[discord.SelectOption(label=str(y), value=str(y)) for y in years],
        )

        async def cb(interaction: discord.Interaction):
            if not await self._check_invoker(interaction):
                return
            self.year = int(sel.values[0])
            self._build_month_select()
            await interaction.response.edit_message(
                content=f"**📅 New Game Setup — Step 2/3**\n**Year:** {self.year}\nSelect a month:",
                view=self,
            )

        sel.callback = cb
        self.add_item(sel)

    def _build_month_select(self):
        self.clear_items()
        now = datetime.now(timezone.utc)
        if self.year == now.year:
            valid_months = range(now.month, 13)
        elif self.year == now.year + 2:
            valid_months = range(1, now.month + 1)
        else:
            valid_months = range(1, 13)
        sel = discord.ui.Select(
            placeholder="📅 Step 2 — Select a month…",
            options=[
                discord.SelectOption(
                    label=datetime(2000, m, 1).strftime("%B"), value=str(m)
                )
                for m in valid_months
            ],
        )

        async def cb(interaction: discord.Interaction):
            if not await self._check_invoker(interaction):
                return
            self.month = int(sel.values[0])
            self._build_half_select()
            month_name = datetime(2000, self.month, 1).strftime("%B")
            await interaction.response.edit_message(
                content=(
                    f"**📅 New Game Setup — Step 3/3**\n"
                    f"**Year:** {self.year} — **Month:** {month_name}\n"
                    "First or second half of the month?"
                ),
                view=self,
            )

        sel.callback = cb
        self.add_item(sel)

    def _build_half_select(self):
        self.clear_items()
        now        = datetime.now(timezone.utc)
        only_second = (self.year == now.year and self.month == now.month and now.day > 15)
        options    = []
        if not only_second:
            options.append(discord.SelectOption(label="First Half  (1–15)",   value="H1", emoji="1️⃣"))
        options.append(discord.SelectOption(label="Second Half (16–end)", value="H2", emoji="2️⃣"))
        sel = discord.ui.Select(
            placeholder="📅 Step 3 — Select a period…",
            options=options,
        )

        async def cb(interaction: discord.Interaction):
            if not await self._check_invoker(interaction):
                return
            self.half = sel.values[0]
            self._build_cohost_step()
            month_name = datetime(2000, self.month, 1).strftime("%B")
            half_label = "First Half" if self.half == "H1" else "Second Half"
            await interaction.response.edit_message(
                content=(
                    f"**📅 New Game Setup**\n"
                    f"**Date:** {month_name} {self.year} — {half_label}\n\n"
                    "Do you want to add co-hosts and/or the Server ID? *(optional)*"
                ),
                view=self,
            )

        sel.callback = cb
        self.add_item(sel)

    def _build_cohost_step(self):
        self.clear_items()

        cohost_btn = discord.ui.Button(
            label="👥 Co-Hosts & Server ID",
            style=discord.ButtonStyle.secondary,
        )

        async def cohost_cb(interaction: discord.Interaction):
            if not await self._check_invoker(interaction):
                return
            await interaction.response.send_modal(CoHostAndServerModal(self))

        cohost_btn.callback = cohost_cb
        self.add_item(cohost_btn)

        continue_btn = discord.ui.Button(
            label="▶️ Continue",
            style=discord.ButtonStyle.primary,
        )

        async def continue_cb(interaction: discord.Interaction):
            if not await self._check_invoker(interaction):
                return
            await interaction.response.send_modal(AddGameDetailsModal(self.cog, self))

        continue_btn.callback = continue_cb
        self.add_item(continue_btn)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── edit field modal ───────────────────────────────────────────────────────────

_FIELDS_EN = {
    "name":           "Game Name",
    "range":          "Date Range",
    "cohost_ids":     "Co-Host IDs",
    "guild_id":       "Server ID",
    "description":    "Description",
    "discord_invite": "Discord Invite",
    "max_players":    "Max Players",
}
_DIRECT_DB_FIELDS = {"name", "cohost_ids", "guild_id", "description", "discord_invite"}


class EditFieldModal(discord.ui.Modal):
    """Single-field modal for editing one specific game field."""

    def __init__(self, cog: "GameManagerEn", game: sqlite3.Row, field: str):
        super().__init__(title=f"Edit: {_FIELDS_EN.get(field, field)}")
        self.cog   = cog
        self.game  = game
        self.field = field

        placeholder_map = {
            "name":           "e.g. The Reminiscence 7",
            "range":          "e.g. July 2026 - First Half",
            "cohost_ids":     "123456789, 987654321",
            "guild_id":       "Numeric Discord server ID",
            "description":    "",
            "discord_invite": "https://discord.gg/...",
            "max_players":    "30",
        }
        current_value = {
            "name":           game["name"] or "",
            "range":          _range_label_from_value(game["range_label"]),
            "cohost_ids":     game["cohost_ids"] or "",
            "guild_id":       _safe_get(game, "guild_id"),
            "description":    game["description"] or "",
            "discord_invite": _safe_get(game, "discord_invite"),
            "max_players":    str(game["max_players"]),
        }

        self.value_input = discord.ui.TextInput(
            label=_FIELDS_EN.get(field, field),
            placeholder=placeholder_map.get(field, ""),
            default=current_value.get(field, ""),
            style=discord.TextStyle.paragraph if field == "description" else discord.TextStyle.short,
            required=field not in ("description", "cohost_ids", "discord_invite", "guild_id"),
            max_length=500 if field == "description" else 300,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not _can_manage(self.game, interaction.user.id):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        val = self.value_input.value.strip()

        if self.field == "range":
            db_val = _display_to_value(val)
            with get_db() as conn:
                conn.execute("UPDATE Games SET range_label=? WHERE id=?", (db_val, self.game["id"]))

        elif self.field == "max_players":
            try:
                max_p = int(val)
                if max_p < 1:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    "❌ Max Players must be a positive integer.", ephemeral=True
                )
                return
            with get_db() as conn:
                conn.execute("UPDATE Games SET max_players=? WHERE id=?", (max_p, self.game["id"]))

        elif self.field in _DIRECT_DB_FIELDS:
            with get_db() as conn:
                conn.execute(f"UPDATE Games SET {self.field}=? WHERE id=?", (val, self.game["id"]))  # noqa: S608

        else:
            await interaction.response.send_message("❌ Unknown field.", ephemeral=True)
            return

        await interaction.response.defer()
        with get_db() as conn:
            updated = conn.execute("SELECT * FROM Games WHERE id=?", (self.game["id"],)).fetchone()
        await self.cog.show_game_detail(interaction, updated)


# ── VIEW – calendar ────────────────────────────────────────────────────────────

class CalendarView(discord.ui.View):
    PAGE_SIZE = 6

    def __init__(self, cog: "GameManagerEn", invoker_id: int, page: int = 0):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog           = cog
        self.invoker_id    = invoker_id
        self.page          = page
        self._page_games: list[sqlite3.Row] = []
        self._build_select()

    def _load_games(self) -> list[sqlite3.Row]:
        with get_db() as conn:
            return conn.execute("SELECT * FROM Games ORDER BY range_label, id").fetchall()

    def build_embed(self) -> discord.Embed:
        return calendar_embed(self._page_games)

    def _build_select(self):
        self.clear_items()
        sorted_games = sorted(self._load_games(), key=lambda g: g["range_label"])
        total     = len(sorted_games)
        num_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = max(0, min(self.page, num_pages - 1))
        start     = self.page * self.PAGE_SIZE
        self._page_games = sorted_games[start:start + self.PAGE_SIZE]

        if num_pages > 1:
            btn_prev = discord.ui.Button(
                label="◀️ Previous", style=discord.ButtonStyle.secondary,
                disabled=(self.page == 0), row=0,
            )
            async def prev_callback(interaction: discord.Interaction):
                new_view = CalendarView(self.cog, self.invoker_id, self.page - 1)
                await interaction.response.defer()
                await interaction.edit_original_response(embed=new_view.build_embed(), view=new_view)
            btn_prev.callback = prev_callback
            self.add_item(btn_prev)

            self.add_item(discord.ui.Button(
                label=f"{self.page + 1} / {num_pages}",
                style=discord.ButtonStyle.secondary, disabled=True, row=0,
            ))

            btn_next = discord.ui.Button(
                label="Next ▶️", style=discord.ButtonStyle.secondary,
                disabled=(self.page >= num_pages - 1), row=0,
            )
            async def next_callback(interaction: discord.Interaction):
                new_view = CalendarView(self.cog, self.invoker_id, self.page + 1)
                await interaction.response.defer()
                await interaction.edit_original_response(embed=new_view.build_embed(), view=new_view)
            btn_next.callback = next_callback
            self.add_item(btn_next)

        self.add_item(self._add_game_button())

        if not self._page_games:
            return

        options = []
        for g in self._page_games:
            name          = g["name"] or f"Game #{g['id']}"
            range_display = _range_label_from_value(g["range_label"])
            label         = f"{name}  •  {range_display}"
            options.append(discord.SelectOption(label=label[:100], value=str(g["id"])))

        select = discord.ui.Select(
            placeholder="Select a game to view details…",
            options=options, custom_id="cal_game_select", row=2,
        )

        async def select_callback(interaction: discord.Interaction):
            game_id = int(select.values[0])
            with get_db() as conn:
                game = conn.execute("SELECT * FROM Games WHERE id=?", (game_id,)).fetchone()
            if not game:
                await interaction.response.send_message("❌ Game not found.", ephemeral=True)
                return
            await interaction.response.defer()
            await self.cog.show_game_detail(interaction, game)

        select.callback = select_callback
        self.add_item(select)

    def _add_game_button(self):
        btn = discord.ui.Button(
            label="➕ Add Game", style=discord.ButtonStyle.primary,
            custom_id="cal_add_game", row=3,
        )

        async def callback(interaction: discord.Interaction):
            wizard = AddGameWizardView(self.cog, interaction.user.id, interaction.message)
            await interaction.response.send_message(
                "**📅 New Game Setup — Step 1/3**\nSelect a year:",
                view=wizard, ephemeral=True,
            )

        btn.callback = callback
        return btn

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── VIEW – game detail ─────────────────────────────────────────────────────────

class GameDetailView(discord.ui.View):
    def __init__(self, cog: "GameManagerEn", game: sqlite3.Row, invoker_id: int):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog        = cog
        self.game       = game
        self.invoker_id = invoker_id
        self._build()

    def _build(self):
        self.clear_items()
        is_manager = _can_manage(self.game, self.invoker_id)

        # ── row 0/1: Playerlist + Back (always) + Delete (host/admin only) ────
        row_nav = 1 if is_manager else 0
        pl_btn = discord.ui.Button(
            label="📋 Playerlist", style=discord.ButtonStyle.secondary, row=row_nav,
        )
        async def pl_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.cog.show_playerlist(interaction, self.game)
        pl_btn.callback = pl_callback
        self.add_item(pl_btn)

        back_btn = discord.ui.Button(
            label="⬅️ Back", style=discord.ButtonStyle.secondary, row=row_nav,
        )
        async def back_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.cog.show_calendar(interaction)
        back_btn.callback = back_callback
        self.add_item(back_btn)

        if is_manager:
            del_btn = discord.ui.Button(
                emoji="🗑️", style=discord.ButtonStyle.danger, row=1,
            )
            async def del_callback(interaction: discord.Interaction):
                if not _can_manage(self.game, interaction.user.id):
                    await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
                    return
                with get_db() as conn:
                    conn.execute("DELETE FROM Games WHERE id=?", (self.game["id"],))
                await interaction.response.defer()
                await self.cog.show_calendar(interaction)
            del_btn.callback = del_callback
            self.add_item(del_btn)

        if not is_manager:
            return

        # ── row 2: Change Status ───────────────────────────────────────────────
        current_status = _safe_get(self.game, "status", "pending")
        status_select = discord.ui.Select(
            placeholder="🔄 Change Game Status…",
            options=[
                discord.SelectOption(label="⏳ Pending",             value="pending",  default=(current_status == "pending")),
                discord.SelectOption(label="🟢 Ongoing",             value="ongoing",  default=(current_status == "ongoing")),
                discord.SelectOption(label="🔴 Ended",               value="ended",    default=(current_status == "ended")),
                discord.SelectOption(label="🚪 Players Joining...",  value="inviting", default=(current_status == "inviting")),
                discord.SelectOption(label="❌ Canceled",            value="canceled", default=(current_status == "canceled")),
            ],
            custom_id="det_status_select",
            row=2,
        )

        async def status_callback(interaction: discord.Interaction):
            if not _can_manage(self.game, interaction.user.id):
                await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
                return
            new_status = status_select.values[0]
            with get_db() as conn:
                conn.execute("UPDATE Games SET status=? WHERE id=?", (new_status, self.game["id"]))

            # When status becomes "inviting", DM the invite link to all players/sponsors
            if new_status == "inviting":
                with get_db() as conn:
                    members_db = conn.execute(
                        "SELECT user_id FROM Players WHERE game_id=?", (self.game["id"],)
                    ).fetchall()
                invite_link = _safe_get(self.game, "discord_invite")
                if invite_link and members_db:
                    await interaction.response.defer()
                    sent, failed = 0, 0
                    for p in members_db:
                        try:
                            user = await interaction.client.fetch_user(p["user_id"])
                            await user.send(
                                f"🚪 **You've been invited to join the game server!**\n"
                                f"Use this link to join: {invite_link}"
                            )
                            sent += 1
                        except Exception:
                            failed += 1
                    with get_db() as conn:
                        updated = conn.execute("SELECT * FROM Games WHERE id=?", (self.game["id"],)).fetchone()
                    await self.cog.show_game_detail(interaction, updated)
                    await interaction.followup.send(
                        f"✅ Invites sent: **{sent}**. DMs not deliverable: **{failed}**.",
                        ephemeral=True,
                    )
                    return

            await interaction.response.defer()
            with get_db() as conn:
                updated = conn.execute("SELECT * FROM Games WHERE id=?", (self.game["id"],)).fetchone()
            await self.cog.show_game_detail(interaction, updated)

        status_select.callback = status_callback
        self.add_item(status_select)

        # ── row 3: Edit Field (host/admin only) ────────────────────────────────
        edit_options = [
            discord.SelectOption(label="✏️ Game Name",      value="name",           emoji="📝"),
            discord.SelectOption(label="📅 Date Range",     value="range",          emoji="🗓️"),
            discord.SelectOption(label="👥 Co-Hosts",        value="cohost_ids",     emoji="👤"),
            discord.SelectOption(label="🖥️ Server ID",       value="guild_id",       emoji="🔑"),
            discord.SelectOption(label="📖 Description",     value="description",    emoji="📄"),
            discord.SelectOption(label="🔗 Discord Invite",  value="discord_invite", emoji="📨"),
            discord.SelectOption(label="🔢 Max Players",     value="max_players",    emoji="👤"),
        ]
        edit_select = discord.ui.Select(
            placeholder="✏️ Edit a field…",
            options=edit_options,
            custom_id="det_edit_select",
            row=3,
        )

        async def edit_callback(interaction: discord.Interaction):
            if not _can_manage(self.game, interaction.user.id):
                await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
                return
            field = edit_select.values[0]
            await interaction.response.send_modal(EditFieldModal(self.cog, self.game, field))

        edit_select.callback = edit_callback
        self.add_item(edit_select)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── VIEW – playerlist ──────────────────────────────────────────────────────────

class PlayerlistView(discord.ui.View):
    """
    Sub-states:
      A) Initial    → Role select only
      B) Role chosen → Role select + Slot select
      C) (after join) reset to A
    """

    def __init__(
        self,
        cog: "GameManagerEn",
        game: sqlite3.Row,
        invoker_id: int,
        chosen_role: Optional[str] = None,
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog         = cog
        self.game        = game
        self.invoker_id  = invoker_id
        self.chosen_role = chosen_role
        self._build()

    def _load_players(self) -> list[sqlite3.Row]:
        with get_db() as conn:
            return conn.execute(
                "SELECT * FROM Players WHERE game_id=? ORDER BY role, slot",
                (self.game["id"],),
            ).fetchall()

    def _free_slots(self, role: str, players: list[sqlite3.Row]) -> list[int]:
        taken = {r["slot"] for r in players if r["role"] == role}
        return [s for s in range(1, self.game["max_players"] + 1) if s not in taken]

    def _build(self):
        self.clear_items()
        players = self._load_players()

        # ── role select ───────────────────────────────────────────────────────
        role_select = discord.ui.Select(
            placeholder="1️⃣ Choose your role…",
            options=[
                discord.SelectOption(label="Player",  value="player",  emoji="🎮"),
                discord.SelectOption(label="Sponsor", value="sponsor", emoji="💰"),
            ],
            custom_id="pl_role_select",
        )
        if self.chosen_role:
            for opt in role_select.options:
                opt.default = (opt.value == self.chosen_role)

        async def role_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.cog.show_playerlist(interaction, self.game, chosen_role=role_select.values[0])

        role_select.callback = role_callback
        self.add_item(role_select)

        # ── slot select (only after role is chosen) ───────────────────────────
        if self.chosen_role:
            free = self._free_slots(self.chosen_role, players)
            if free:
                slot_select = discord.ui.Select(
                    placeholder=f"2️⃣ Choose your slot ({self.chosen_role})…",
                    options=[discord.SelectOption(label=f"Slot {s}", value=str(s)) for s in free[:25]],
                    custom_id="pl_slot_select",
                )

                async def slot_callback(interaction: discord.Interaction):
                    slot = int(slot_select.values[0])
                    uid  = interaction.user.id
                    role = self.chosen_role

                    with get_db() as conn:
                        any_existing = conn.execute(
                            "SELECT role FROM Players WHERE game_id=? AND user_id=?",
                            (self.game["id"], uid),
                        ).fetchone()

                    if any_existing:
                        existing_role = any_existing["role"]
                        if existing_role == role:
                            msg = f"❌ You are already registered as a **{role}** in this game."
                        else:
                            msg = (
                                f"❌ You are already in this game as a **{existing_role}**. "
                                f"You cannot also sign up as a **{role}**."
                            )
                        await interaction.response.send_message(msg, ephemeral=True)
                        return

                    try:
                        with get_db() as conn:
                            conn.execute(
                                "INSERT INTO Players (game_id, user_id, role, slot) VALUES (?,?,?,?)",
                                (self.game["id"], uid, role, slot),
                            )
                    except sqlite3.IntegrityError:
                        await interaction.response.send_message(
                            "❌ That slot was just taken. Please choose another.", ephemeral=True
                        )
                        return

                    await interaction.response.defer()
                    await self.cog.show_playerlist(interaction, self.game)

                slot_select.callback = slot_callback
                self.add_item(slot_select)
            else:
                self.add_item(discord.ui.Select(
                    placeholder=f"No free {self.chosen_role} slots!",
                    options=[discord.SelectOption(label="—", value="none")],
                    disabled=True,
                    custom_id="pl_slot_disabled",
                ))

        # ── manage players (host / admin only) ────────────────────────────────
        if _can_manage(self.game, self.invoker_id) and players:
            manage_select = discord.ui.Select(
                placeholder="🛠️ Manage Players — select to remove…",
                options=[
                    discord.SelectOption(
                        label=f"[{p['role'].capitalize()} #{p['slot']}] ID:{p['user_id']}",
                        value=str(p["id"]),
                        emoji="❌",
                    )
                    for p in players[:25]
                ],
                custom_id="pl_manage_select",
            )

            async def manage_callback(interaction: discord.Interaction):
                if not _can_manage(self.game, interaction.user.id):
                    await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
                    return
                with get_db() as conn:
                    conn.execute("DELETE FROM Players WHERE id=?", (int(manage_select.values[0]),))
                await interaction.response.defer()
                await self.cog.show_playerlist(interaction, self.game)

            manage_select.callback = manage_callback
            self.add_item(manage_select)

        # ── assign roles button (host / admin only) ───────────────────────────
        if _can_manage(self.game, self.invoker_id):
            assign_btn = discord.ui.Button(
                label="🎭 Assign Server Roles",
                style=discord.ButtonStyle.primary,
                row=3,
            )

            async def assign_roles_callback(interaction: discord.Interaction):
                if not _can_manage(self.game, interaction.user.id):
                    await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
                    return

                raw_gid = _safe_get(self.game, "guild_id")
                if not raw_gid:
                    await interaction.response.send_message(
                        "❌ Server ID not configured for this game. "
                        "Set it via the **✏️ Edit a field** menu.", ephemeral=True
                    )
                    return

                try:
                    target_guild_id = int(raw_gid)
                except ValueError:
                    await interaction.response.send_message(
                        "❌ Invalid Server ID (must be numeric).", ephemeral=True
                    )
                    return

                target_guild = interaction.client.get_guild(target_guild_id)
                if not target_guild:
                    await interaction.response.send_message(
                        "❌ Server not found. Make sure the bot is in that server "
                        "and the Server ID is correct.", ephemeral=True
                    )
                    return

                guild_data = load_guild_data(target_guild.id)
                if not guild_data:
                    await interaction.response.send_message(
                        "❌ Server configuration data not found.", ephemeral=True
                    )
                    return

                alive_role   = discord.utils.get(target_guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(target_guild.roles, name=guild_data["sponsor_role_name"])

                with get_db() as conn:
                    players_db = conn.execute(
                        "SELECT * FROM Players WHERE game_id=?", (self.game["id"],)
                    ).fetchall()

                await interaction.response.defer(ephemeral=True)

                assigned, not_found, errors = 0, 0, 0
                for p in players_db:
                    member = target_guild.get_member(p["user_id"])
                    if not member:
                        not_found += 1
                        continue
                    role_to_add = alive_role if p["role"] == "player" else sponsor_role
                    if not role_to_add:
                        errors += 1
                        continue
                    try:
                        await member.add_roles(role_to_add, reason="Game role assignment")
                        assigned += 1
                    except (discord.Forbidden, Exception):
                        errors += 1

                lines = [f"✅ Roles successfully assigned: **{assigned}**"]
                if not_found:
                    lines.append(f"⚠️ Not in the server: **{not_found}**")
                if errors:
                    lines.append(f"❌ Errors (missing role / permissions): **{errors}**")
                await interaction.followup.send("\n".join(lines), ephemeral=True)

            assign_btn.callback = assign_roles_callback
            self.add_item(assign_btn)

        # ── leave (only shown if invoker is in this game) ─────────────────────
        with get_db() as conn:
            own_entry = conn.execute(
                "SELECT id, role FROM Players WHERE game_id=? AND user_id=?",
                (self.game["id"], self.invoker_id),
            ).fetchone()

        if own_entry:
            role_label = own_entry["role"].capitalize()
            leave_btn = discord.ui.Button(
                label=f"🚪 Leave ({role_label})",
                style=discord.ButtonStyle.danger,
                row=4,
            )
            async def leave_callback(interaction: discord.Interaction):
                with get_db() as conn:
                    entry = conn.execute(
                        "SELECT id FROM Players WHERE game_id=? AND user_id=?",
                        (self.game["id"], interaction.user.id),
                    ).fetchone()
                if not entry:
                    await interaction.response.send_message("❌ You are not in this game.", ephemeral=True)
                    return
                with get_db() as conn:
                    conn.execute("DELETE FROM Players WHERE id=?", (entry["id"],))
                await interaction.response.defer()
                await self.cog.show_playerlist(interaction, self.game)
            leave_btn.callback = leave_callback
            self.add_item(leave_btn)

        # ── back ──────────────────────────────────────────────────────────────
        back_btn = discord.ui.Button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=4)
        async def back_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.cog.show_game_detail(interaction, self.game)
        back_btn.callback = back_callback
        self.add_item(back_btn)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── COG ────────────────────────────────────────────────────────────────────────

class GameManagerEn(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

    async def show_calendar(self, interaction: discord.Interaction, page: int = 0):
        view  = CalendarView(self, interaction.user.id, page)
        embed = view.build_embed()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    async def show_game_detail(self, interaction: discord.Interaction, game: sqlite3.Row):
        embed = game_detail_embed(game, self.bot)
        view  = GameDetailView(self, game, interaction.user.id)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    async def show_playerlist(
        self,
        interaction: discord.Interaction,
        game: sqlite3.Row,
        chosen_role: Optional[str] = None,
    ):
        with get_db() as conn:
            players = conn.execute(
                "SELECT * FROM Players WHERE game_id=? ORDER BY role, slot",
                (game["id"],),
            ).fetchall()
        embed = playerlist_embed(game, players)
        view  = PlayerlistView(self, game, interaction.user.id, chosen_role=chosen_role)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    @commands.command(name="calendar")
    async def calendar_cmd(self, ctx: commands.Context):
        """Open the Heartside Calendar."""
        view  = CalendarView(self, ctx.author.id)
        embed = view.build_embed()
        await ctx.send(embed=embed, view=view)


# ── setup ──────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(GameManagerEn(bot))