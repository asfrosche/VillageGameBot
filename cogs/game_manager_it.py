from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────────────────────────────────────

DB_PATH = "db/calendario_it.db"
VIEW_TIMEOUT = 86400          # 10 minuti
GLOBAL_ADMINS: list[int] = [450772749829537793]

BRAND_COLOUR = discord.Colour(0xFF3FB9)

# Importa load_guild_data dal tuo cog di configurazione.
# Modifica il percorso in base alla struttura del tuo progetto.
try:
    from cogs.data_utils import load_guild_data
except ImportError:
    def load_guild_data(guild_id: int):  # type: ignore[misc]
        return None

# ──────────────────────────────────────────────────────────────────────────────
# LAYER DATABASE
# ──────────────────────────────────────────────────────────────────────────────

# Schema aggiornato: guild_id aggiunto, CHECK su status rimosso (gestito dall'app)
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

# Nomi dei mesi in italiano
MESI_IT = {
    1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile",
    5: "Maggio", 6: "Giugno", 7: "Luglio", 8: "Agosto",
    9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre",
}


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
    # Crea le tabelle se non esistono (installazioni nuove)
    with get_db() as conn:
        conn.executescript(DDL)

    # Migrazione colonne semplici per DB preesistenti
    with get_db() as conn:
        for col, default in [("status", "'pending'"), ("discord_invite", "''")]:
            try:
                conn.execute(f"ALTER TABLE Games ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
            except sqlite3.OperationalError:
                pass  # colonna già presente

    # Migrazione: aggiungi guild_id e rimuovi il vecchio CHECK constraint su status
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


# ── helper ────────────────────────────────────────────────────────────────────

def _parse_ids(raw: str) -> list[int]:
    """Analizza una stringa di ID separati da virgola/spazio e restituisce una lista di interi."""
    return [int(x) for x in re.findall(r"\d{6,}", raw)]


def _is_host(game: sqlite3.Row, user_id: int) -> bool:
    if game["host_id"] == user_id:
        return True
    return user_id in _parse_ids(game["cohost_ids"] or "")


def _can_manage(game: sqlite3.Row, user_id: int) -> bool:
    return user_id in GLOBAL_ADMINS or _is_host(game, user_id)


def _range_label_from_value(value: str) -> str:
    """Converte il valore ordinabile "2026-07-H1" → "Luglio 2026 - Prima Metà"."""
    m = re.match(r"^(\d{4})-(\d{2})-H([12])$", value)
    if m:
        year, month, half = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= month <= 12:
            mese = MESI_IT[month]
            meta = "Prima Metà" if half == "1" else "Seconda Metà"
            return f"{mese} {year} - {meta}"
    return value  # fallback: restituisce così com'è


def _display_to_value(text: str) -> str:
    """Converte l'etichetta display o un valore grezzo nel formato valore ordinabile."""
    text = text.strip()
    if re.match(r"^\d{4}-\d{2}-H[12]$", text):
        return text
    m = re.match(r"^(\w+)\s+(\d{4})\s*[-–]\s*(Prima|Seconda)\s+Met[àa]$", text, re.IGNORECASE)
    if m:
        nome_mese = m.group(1).capitalize()
        year = int(m.group(2))
        meta = "H1" if m.group(3).lower() == "prima" else "H2"
        for num, nome in MESI_IT.items():
            if nome.lower() == nome_mese.lower():
                return f"{year}-{num:02d}-{meta}"
    return text


def _status_emoji(status: str) -> str:
    return {
        "ongoing":  "🟢",
        "ended":    "🔴",
        "pending":  "⏳",
        "inviting": "🚪",
        "canceled": "❌",
    }.get(status or "pending", "⏳")


def _status_label_it(status: str) -> str:
    return {
        "ongoing":  "In Corso",
        "ended":    "Terminata",
        "pending":  "In Attesa",
        "inviting": "I Giocatori Stanno Entrando",
        "canceled": "Cancellata",
    }.get(status or "pending", "In Attesa")


def _safe_get(row: sqlite3.Row, key: str, default="") -> str:
    """Legge una colonna in modo sicuro anche su DB non ancora migrati."""
    try:
        return row[key] or default
    except (IndexError, KeyError):
        return default


# ──────────────────────────────────────────────────────────────────────────────
# EMBED
# ──────────────────────────────────────────────────────────────────────────────

def calendario_embed(games: list[sqlite3.Row]) -> discord.Embed:
    embed = discord.Embed(title="📅  Calendario di The Village", colour=BRAND_COLOUR)
    if not games:
        embed.description = "*Nessuna partita in programma. Usa **Aggiungi Partita** per crearne una!*"
        return embed

    sorted_games = sorted(games, key=lambda g: g["range_label"])
    blocks: list[str] = []
    for g in sorted_games:
        nome   = g["name"] or f"Partita #{g['id']}"
        status = _safe_get(g, "status", "pending")
        emoji  = _status_emoji(status)
        range_display = _range_label_from_value(g["range_label"])
        blocks.append(f"**{nome}**\n{emoji} — {range_display}")

    embed.description = "\n\n".join(blocks)
    return embed


def dettaglio_partita_embed(game: sqlite3.Row, bot: commands.Bot) -> discord.Embed:
    nome     = game["name"] or f"Partita #{game['id']}"
    status   = _safe_get(game, "status", "pending")
    emoji    = _status_emoji(status)
    label_st = _status_label_it(status)
    embed    = discord.Embed(title=f"🎮  {nome}", colour=BRAND_COLOUR)

    embed.add_field(name="Periodo", value=_range_label_from_value(game["range_label"]), inline=True)
    embed.add_field(name="Stato",   value=f"{emoji} {label_st}", inline=True)

    invite = _safe_get(game, "discord_invite")
    embed.add_field(name="Invito Discord", value=invite or "—", inline=False)

    host_mention = f"<@{game['host_id']}>"
    cohost_ids   = _parse_ids(game["cohost_ids"] or "")
    cohost_str   = ", ".join(f"<@{c}>" for c in cohost_ids) if cohost_ids else "—"
    embed.add_field(name="Host",    value=host_mention, inline=False)
    embed.add_field(name="Co-Host", value=cohost_str,   inline=False)

    embed.add_field(name="Descrizione", value=game["description"] or "—", inline=False)
    return embed


def lista_giocatori_embed(game: sqlite3.Row, players: list[sqlite3.Row]) -> discord.Embed:
    nome  = game["name"] or f"Partita #{game['id']}"
    embed = discord.Embed(title=f"📋  Lista Giocatori — {nome}", colour=BRAND_COLOUR)
    max_p = game["max_players"]
    player_map = {(r["role"], r["slot"]): r["user_id"] for r in players}

    lines: list[str] = []
    for slot in range(1, max_p + 1):
        p_uid = player_map.get(("player",  slot))
        s_uid = player_map.get(("sponsor", slot))
        p_str = f"<@{p_uid}>" if p_uid else "Giocatore: *Vuoto*"
        s_str = f"<@{s_uid}>" if s_uid else "Sponsor: *Vuoto*"
        lines.append(f"**{slot}.** {p_str}")
        lines.append(f"\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u2514 {s_str}")

    embed.description = "\n".join(lines) if lines else "*Nessun giocatore iscritto.*"
    return embed


# ──────────────────────────────────────────────────────────────────────────────
# WIZARD AGGIUNTA PARTITA
#
# Flusso (tutto efimero):
#   Step 1 – selezione anno
#   Step 2 – selezione mese
#   Step 3 – selezione prima/seconda metà
#   Step 4 – CoHostAndServerModalIt  (ID co-host + Server ID)  + pulsante Continua
#   Step 5 – AggiuntaDettagliPartitaModal (nome, descrizione, max_giocatori, discord_invite)
# ──────────────────────────────────────────────────────────────────────────────

class CoHostAndServerModalIt(discord.ui.Modal, title="Co-Host e Server"):
    """Primo modal del wizard: raccoglie gli ID dei co-host e il Server ID del gioco."""

    cohost_input = discord.ui.TextInput(
        label="ID Co-Host (opzionale)",
        placeholder="@utente1 @utente2   oppure   123456789, 987654321",
        required=False,
        max_length=300,
    )
    guild_id_input = discord.ui.TextInput(
        label="Server ID del gioco",
        placeholder="ID numerico del server Discord dove si svolge il gioco",
        required=False,
        max_length=30,
    )

    def __init__(self, wizard: "WizardAggiungiPartitaView"):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        self.wizard.cohost_raw  = self.cohost_input.value.strip()
        self.wizard.guild_id_raw = self.guild_id_input.value.strip()

        parsed        = _parse_ids(self.wizard.cohost_raw)
        cohost_display = ", ".join(f"<@{c}>" for c in parsed) if parsed else "Nessuno"

        self.wizard._costruisci_step_cohost()
        mese       = MESI_IT[self.wizard.month]
        meta_label = "Prima Metà" if self.wizard.half == "H1" else "Seconda Metà"
        await interaction.response.edit_message(
            content=(
                f"**📅 Nuova Partita**\n"
                f"**Data:** {mese} {self.wizard.year} — {meta_label}\n"
                f"**Co-Host:** {cohost_display}\n\n"
                "Clicca **Continua** per inserire i dettagli della partita."
            ),
            view=self.wizard,
        )


class AggiuntaDettagliPartitaModal(discord.ui.Modal, title="Dettagli Nuova Partita"):
    nome_input = discord.ui.TextInput(
        label="Nome della Partita",
        placeholder="es. The Village 5",
        max_length=100,
    )
    descrizione = discord.ui.TextInput(
        label="Descrizione",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )
    max_giocatori = discord.ui.TextInput(
        label="Numero Massimo di Giocatori",
        placeholder="25",
        max_length=3,
    )
    discord_invite = discord.ui.TextInput(
        label="Invito Discord (opzionale)",
        placeholder="https://discord.gg/...",
        required=False,
        max_length=100,
    )

    def __init__(self, cog: "GameManagerIt", wizard: "WizardAggiungiPartitaView"):
        super().__init__()
        self.cog    = cog
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_p = int(self.max_giocatori.value.strip())
            if max_p < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Il numero massimo di giocatori deve essere un intero positivo.", ephemeral=True
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
                    self.nome_input.value.strip(),
                    self.descrizione.value.strip(),
                    max_p,
                    self.discord_invite.value.strip(),
                    now_str,
                ),
            )

        await interaction.response.edit_message(
            content="✅ Partita aggiunta con successo al Calendario di The Village!", view=None
        )
        if self.wizard.calendar_message:
            new_view = CalendarioView(self.cog, self.wizard.invoker_id)
            await self.wizard.calendar_message.edit(embed=new_view.build_embed(), view=new_view)


class WizardAggiungiPartitaView(discord.ui.View):
    """Wizard efimero multi-step per la creazione di una nuova partita."""

    def __init__(
        self,
        cog: "GameManagerIt",
        invoker_id: int,
        calendar_message: discord.Message,
    ):
        super().__init__(timeout=300)
        self.cog              = cog
        self.invoker_id       = invoker_id
        self.calendar_message = calendar_message
        self.year:        Optional[int] = None
        self.month:       Optional[int] = None
        self.half:        Optional[str] = None
        self.cohost_raw:  str = ""
        self.guild_id_raw: str = ""
        self._costruisci_anno()

    async def _controlla_invoker(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "❌ Questo wizard è stato aperto da qualcun altro.", ephemeral=True
            )
            return False
        return True

    def _costruisci_anno(self):
        self.clear_items()
        now   = datetime.now(timezone.utc)
        years = [now.year, now.year + 1, now.year + 2]
        sel   = discord.ui.Select(
            placeholder="📅 Step 1 — Seleziona l'anno…",
            options=[discord.SelectOption(label=str(y), value=str(y)) for y in years],
        )

        async def cb(interaction: discord.Interaction):
            if not await self._controlla_invoker(interaction):
                return
            self.year = int(sel.values[0])
            self._costruisci_mese()
            await interaction.response.edit_message(
                content=f"**📅 Nuova Partita — Step 2/3**\n**Anno:** {self.year}\nSeleziona un mese:",
                view=self,
            )

        sel.callback = cb
        self.add_item(sel)

    def _costruisci_mese(self):
        self.clear_items()
        now = datetime.now(timezone.utc)
        if self.year == now.year:
            mesi_validi = range(now.month, 13)
        elif self.year == now.year + 2:
            mesi_validi = range(1, now.month + 1)
        else:
            mesi_validi = range(1, 13)
        sel = discord.ui.Select(
            placeholder="📅 Step 2 — Seleziona il mese…",
            options=[
                discord.SelectOption(label=MESI_IT[m], value=str(m))
                for m in mesi_validi
            ],
        )

        async def cb(interaction: discord.Interaction):
            if not await self._controlla_invoker(interaction):
                return
            self.month = int(sel.values[0])
            self._costruisci_meta()
            mese = MESI_IT[self.month]
            await interaction.response.edit_message(
                content=(
                    f"**📅 Nuova Partita — Step 3/3**\n"
                    f"**Anno:** {self.year} — **Mese:** {mese}\n"
                    "Prima o seconda metà del mese?"
                ),
                view=self,
            )

        sel.callback = cb
        self.add_item(sel)

    def _costruisci_meta(self):
        self.clear_items()
        now         = datetime.now(timezone.utc)
        solo_seconda = (self.year == now.year and self.month == now.month and now.day > 15)
        opzioni     = []
        if not solo_seconda:
            opzioni.append(discord.SelectOption(label="Prima Metà  (1–15)",    value="H1", emoji="1️⃣"))
        opzioni.append(discord.SelectOption(label="Seconda Metà (16–fine)", value="H2", emoji="2️⃣"))
        sel = discord.ui.Select(
            placeholder="📅 Step 3 — Seleziona il periodo…",
            options=opzioni,
        )

        async def cb(interaction: discord.Interaction):
            if not await self._controlla_invoker(interaction):
                return
            self.half = sel.values[0]
            self._costruisci_step_cohost()
            mese       = MESI_IT[self.month]
            meta_label = "Prima Metà" if self.half == "H1" else "Seconda Metà"
            await interaction.response.edit_message(
                content=(
                    f"**📅 Nuova Partita**\n"
                    f"**Data:** {mese} {self.year} — {meta_label}\n\n"
                    "Vuoi aggiungere co-host e/o il Server ID? *(opzionale)*"
                ),
                view=self,
            )

        sel.callback = cb
        self.add_item(sel)

    def _costruisci_step_cohost(self):
        self.clear_items()

        btn_cohost = discord.ui.Button(
            label="👥 Co-Host & Server ID",
            style=discord.ButtonStyle.secondary,
        )
        async def cohost_cb(interaction: discord.Interaction):
            if not await self._controlla_invoker(interaction):
                return
            await interaction.response.send_modal(CoHostAndServerModalIt(self))
        btn_cohost.callback = cohost_cb
        self.add_item(btn_cohost)

        btn_continua = discord.ui.Button(
            label="Continua ▶️",
            style=discord.ButtonStyle.primary,
        )
        async def continua_cb(interaction: discord.Interaction):
            if not await self._controlla_invoker(interaction):
                return
            await interaction.response.send_modal(AggiuntaDettagliPartitaModal(self.cog, self))
        btn_continua.callback = continua_cb
        self.add_item(btn_continua)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ──────────────────────────────────────────────────────────────────────────────
# MODAL – MODIFICA SINGOLO CAMPO
# ──────────────────────────────────────────────────────────────────────────────

_CAMPI_IT = {
    "name":           "Nome Partita",
    "range":          "Periodo",
    "cohost_ids":     "ID Co-Host",
    "guild_id":       "Server ID",
    "description":    "Descrizione",
    "discord_invite": "Invito Discord",
    "max_players":    "Max Giocatori",
}
# Campi validi per UPDATE diretto (whitelist anti-injection)
_CAMPI_DB_DIRETTI = {"name", "cohost_ids", "guild_id", "description", "discord_invite"}


class ModificaCampoModal(discord.ui.Modal):
    """Modal a campo singolo per modificare un campo specifico della partita."""

    def __init__(self, cog: "GameManagerIt", game: sqlite3.Row, campo: str):
        super().__init__(title=f"Modifica: {_CAMPI_IT.get(campo, campo)}")
        self.cog   = cog
        self.game  = game
        self.campo = campo

        placeholder_map = {
            "name":           "es. The Village 5",
            "range":          "es. Luglio 2026 - Prima Metà",
            "cohost_ids":     "123456789, 987654321",
            "guild_id":       "ID numerico del server Discord",
            "description":    "",
            "discord_invite": "https://discord.gg/...",
            "max_players":    "25",
        }
        valore_attuale = {
            "name":           game["name"] or "",
            "range":          _range_label_from_value(game["range_label"]),
            "cohost_ids":     game["cohost_ids"] or "",
            "guild_id":       _safe_get(game, "guild_id"),
            "description":    game["description"] or "",
            "discord_invite": _safe_get(game, "discord_invite"),
            "max_players":    str(game["max_players"]),
        }

        self.valore_input = discord.ui.TextInput(
            label=_CAMPI_IT.get(campo, campo),
            placeholder=placeholder_map.get(campo, ""),
            default=valore_attuale.get(campo, ""),
            style=discord.TextStyle.paragraph if campo == "description" else discord.TextStyle.short,
            required=campo not in ("description", "cohost_ids", "discord_invite", "guild_id"),
            max_length=500 if campo == "description" else 300,
        )
        self.add_item(self.valore_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not _can_manage(self.game, interaction.user.id):
            await interaction.response.send_message(
                "❌ Non hai i permessi per modificare questa partita.", ephemeral=True
            )
            return

        val = self.valore_input.value.strip()

        if self.campo == "range":
            db_val = _display_to_value(val)
            with get_db() as conn:
                conn.execute("UPDATE Games SET range_label=? WHERE id=?", (db_val, self.game["id"]))

        elif self.campo == "max_players":
            try:
                max_p = int(val)
                if max_p < 1:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    "❌ Il numero massimo di giocatori deve essere un intero positivo.", ephemeral=True
                )
                return
            with get_db() as conn:
                conn.execute("UPDATE Games SET max_players=? WHERE id=?", (max_p, self.game["id"]))

        elif self.campo in _CAMPI_DB_DIRETTI:
            with get_db() as conn:
                conn.execute(f"UPDATE Games SET {self.campo}=? WHERE id=?", (val, self.game["id"]))  # noqa: S608

        else:
            await interaction.response.send_message("❌ Campo non riconosciuto.", ephemeral=True)
            return

        await interaction.response.defer()
        with get_db() as conn:
            aggiornata = conn.execute("SELECT * FROM Games WHERE id=?", (self.game["id"],)).fetchone()
        await self.cog.mostra_dettaglio_partita(interaction, aggiornata)


# ──────────────────────────────────────────────────────────────────────────────
# VIEW – STATO 1 : CALENDARIO
# ──────────────────────────────────────────────────────────────────────────────

class CalendarioView(discord.ui.View):
    PAGINA_SIZE = 6

    def __init__(self, cog: "GameManagerIt", invoker_id: int, pagina: int = 0):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog             = cog
        self.invoker_id      = invoker_id
        self.pagina          = pagina
        self._pagina_partite: list[sqlite3.Row] = []
        self._costruisci()

    def _carica_partite(self) -> list[sqlite3.Row]:
        with get_db() as conn:
            return conn.execute("SELECT * FROM Games ORDER BY range_label, id").fetchall()

    def build_embed(self) -> discord.Embed:
        return calendario_embed(self._pagina_partite)

    def _costruisci(self):
        self.clear_items()
        sorted_partite = sorted(self._carica_partite(), key=lambda g: g["range_label"])
        totale     = len(sorted_partite)
        num_pagine = max(1, (totale + self.PAGINA_SIZE - 1) // self.PAGINA_SIZE)
        self.pagina = max(0, min(self.pagina, num_pagine - 1))
        inizio      = self.pagina * self.PAGINA_SIZE
        self._pagina_partite = sorted_partite[inizio:inizio + self.PAGINA_SIZE]

        if num_pagine > 1:
            btn_prec = discord.ui.Button(
                label="◀️ Precedente", style=discord.ButtonStyle.secondary,
                disabled=(self.pagina == 0), row=0,
            )
            async def prec_callback(interaction: discord.Interaction):
                nuova_view = CalendarioView(self.cog, self.invoker_id, self.pagina - 1)
                await interaction.response.defer()
                await interaction.edit_original_response(embed=nuova_view.build_embed(), view=nuova_view)
            btn_prec.callback = prec_callback
            self.add_item(btn_prec)

            self.add_item(discord.ui.Button(
                label=f"{self.pagina + 1} / {num_pagine}",
                style=discord.ButtonStyle.secondary, disabled=True, row=0,
            ))

            btn_succ = discord.ui.Button(
                label="Successiva ▶️", style=discord.ButtonStyle.secondary,
                disabled=(self.pagina >= num_pagine - 1), row=0,
            )
            async def succ_callback(interaction: discord.Interaction):
                nuova_view = CalendarioView(self.cog, self.invoker_id, self.pagina + 1)
                await interaction.response.defer()
                await interaction.edit_original_response(embed=nuova_view.build_embed(), view=nuova_view)
            btn_succ.callback = succ_callback
            self.add_item(btn_succ)

        self.add_item(self._btn_aggiungi_partita())

        if not self._pagina_partite:
            return

        opzioni = []
        for g in self._pagina_partite:
            nome          = g["name"] or f"Partita #{g['id']}"
            range_display = _range_label_from_value(g["range_label"])
            etichetta     = f"{nome}  •  {range_display}"
            opzioni.append(discord.SelectOption(label=etichetta[:100], value=str(g["id"])))

        menu = discord.ui.Select(
            placeholder="Seleziona una partita per i dettagli…",
            options=opzioni, custom_id="cal_partita_select", row=2,
        )

        async def menu_callback(interaction: discord.Interaction):
            game_id = int(menu.values[0])
            with get_db() as conn:
                game = conn.execute("SELECT * FROM Games WHERE id=?", (game_id,)).fetchone()
            if not game:
                await interaction.response.send_message("❌ Partita non trovata.", ephemeral=True)
                return
            await interaction.response.defer()
            await self.cog.mostra_dettaglio_partita(interaction, game)

        menu.callback = menu_callback
        self.add_item(menu)

    def _btn_aggiungi_partita(self):
        btn = discord.ui.Button(
            label="➕ Aggiungi Partita", style=discord.ButtonStyle.primary,
            custom_id="cal_aggiungi_partita", row=3,
        )

        async def callback(interaction: discord.Interaction):
            wizard = WizardAggiungiPartitaView(self.cog, interaction.user.id, interaction.message)
            await interaction.response.send_message(
                "**📅 Nuova Partita — Step 1/3**\nSeleziona l'anno:",
                view=wizard, ephemeral=True,
            )

        btn.callback = callback
        return btn

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ──────────────────────────────────────────────────────────────────────────────
# VIEW – STATO 2 : DETTAGLIO PARTITA
# ──────────────────────────────────────────────────────────────────────────────

class DettaglioPartitaView(discord.ui.View):
    def __init__(self, cog: "GameManagerIt", game: sqlite3.Row, invoker_id: int):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog        = cog
        self.game       = game
        self.invoker_id = invoker_id
        self._costruisci()

    def _costruisci(self):
        self.clear_items()
        is_manager = _can_manage(self.game, self.invoker_id)

        # ── riga 0/1: Lista Giocatori + Indietro (sempre visibili) + Elimina (solo host/admin) ──
        row_nav = 1 if is_manager else 0
        btn_lista = discord.ui.Button(
            label="📋 Lista Giocatori", style=discord.ButtonStyle.secondary, row=row_nav,
        )
        async def lista_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.cog.mostra_lista_giocatori(interaction, self.game)
        btn_lista.callback = lista_callback
        self.add_item(btn_lista)

        btn_indietro = discord.ui.Button(
            label="⬅️ Indietro", style=discord.ButtonStyle.secondary, row=row_nav,
        )
        async def indietro_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.cog.mostra_calendario(interaction)
        btn_indietro.callback = indietro_callback
        self.add_item(btn_indietro)

        if is_manager:
            btn_elimina = discord.ui.Button(
                emoji="🗑️", style=discord.ButtonStyle.danger, row=1,
            )
            async def elimina_callback(interaction: discord.Interaction):
                if not _can_manage(self.game, interaction.user.id):
                    await interaction.response.send_message(
                        "❌ Non hai i permessi per eliminare questa partita.", ephemeral=True
                    )
                    return
                with get_db() as conn:
                    conn.execute("DELETE FROM Games WHERE id=?", (self.game["id"],))
                await interaction.response.defer()
                await self.cog.mostra_calendario(interaction)
            btn_elimina.callback = elimina_callback
            self.add_item(btn_elimina)

        if not is_manager:
            return

        # ── riga 2: Cambia Stato ───────────────────────────────────────────────
        status_attuale = _safe_get(self.game, "status", "pending")
        menu_stato = discord.ui.Select(
            placeholder="🔄 Cambia Stato della Partita…",
            options=[
                discord.SelectOption(label="⏳ In Attesa",                  value="pending",  default=(status_attuale == "pending")),
                discord.SelectOption(label="🟢 In Corso",                   value="ongoing",  default=(status_attuale == "ongoing")),
                discord.SelectOption(label="🔴 Terminata",                  value="ended",    default=(status_attuale == "ended")),
                discord.SelectOption(label="🚪 I Giocatori Stanno Entrando", value="inviting", default=(status_attuale == "inviting")),
                discord.SelectOption(label="❌ Cancellata",                  value="canceled", default=(status_attuale == "canceled")),
            ],
            custom_id="det_stato_select",
            row=2,
        )

        async def stato_callback(interaction: discord.Interaction):
            if not _can_manage(self.game, interaction.user.id):
                await interaction.response.send_message(
                    "❌ Non hai i permessi per cambiare lo stato di questa partita.", ephemeral=True
                )
                return
            nuovo_stato = menu_stato.values[0]
            with get_db() as conn:
                conn.execute("UPDATE Games SET status=? WHERE id=?", (nuovo_stato, self.game["id"]))

            # Quando lo status diventa "inviting", invia il link di invito in DM
            if nuovo_stato == "inviting":
                with get_db() as conn:
                    giocatori = conn.execute(
                        "SELECT user_id FROM Players WHERE game_id=?", (self.game["id"],)
                    ).fetchall()
                invite_link = _safe_get(self.game, "discord_invite")
                if invite_link and giocatori:
                    await interaction.response.defer()
                    inviati, errori = 0, 0
                    for p in giocatori:
                        try:
                            utente = await interaction.client.fetch_user(p["user_id"])
                            await utente.send(
                                f"🚪 **Sei stato invitato a entrare nel server di gioco!**\n"
                                f"Usa questo link per unirti: {invite_link}"
                            )
                            inviati += 1
                        except Exception:
                            errori += 1
                    with get_db() as conn:
                        aggiornata = conn.execute("SELECT * FROM Games WHERE id=?", (self.game["id"],)).fetchone()
                    await self.cog.mostra_dettaglio_partita(interaction, aggiornata)
                    # Notifica efimera all'host
                    await interaction.followup.send(
                        f"✅ Inviti inviati: **{inviati}**. DM non recapitabili: **{errori}**.",
                        ephemeral=True,
                    )
                    return
            
            await interaction.response.defer()
            with get_db() as conn:
                aggiornata = conn.execute("SELECT * FROM Games WHERE id=?", (self.game["id"],)).fetchone()
            await self.cog.mostra_dettaglio_partita(interaction, aggiornata)

        menu_stato.callback = stato_callback
        self.add_item(menu_stato)

        # ── riga 3: Modifica Campo (solo host/admin) ───────────────────────────
        opzioni_modifica = [
            discord.SelectOption(label="✏️ Nome Partita",    value="name",           emoji="📝"),
            discord.SelectOption(label="📅 Periodo",          value="range",          emoji="🗓️"),
            discord.SelectOption(label="👥 Co-Host",          value="cohost_ids",     emoji="👤"),
            discord.SelectOption(label="🖥️ Server ID",        value="guild_id",       emoji="🔑"),
            discord.SelectOption(label="📖 Descrizione",      value="description",    emoji="📄"),
            discord.SelectOption(label="🔗 Invito Discord",   value="discord_invite", emoji="📨"),
            discord.SelectOption(label="👤 Max Giocatori",    value="max_players",    emoji="🔢"),
        ]
        menu_modifica = discord.ui.Select(
            placeholder="✏️ Modifica un campo…",
            options=opzioni_modifica,
            custom_id="det_modifica_select",
            row=3,
        )

        async def modifica_callback(interaction: discord.Interaction):
            if not _can_manage(self.game, interaction.user.id):
                await interaction.response.send_message(
                    "❌ Non hai i permessi per modificare questa partita.", ephemeral=True
                )
                return
            campo = menu_modifica.values[0]
            await interaction.response.send_modal(ModificaCampoModal(self.cog, self.game, campo))

        menu_modifica.callback = modifica_callback
        self.add_item(menu_modifica)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ──────────────────────────────────────────────────────────────────────────────
# VIEW – STATO 3 : LISTA GIOCATORI
# ──────────────────────────────────────────────────────────────────────────────

class ListaGiocatoriView(discord.ui.View):
    """
    Tre sotto-stati:
      A) Iniziale     → solo menu Ruolo
      B) Ruolo scelto → menu Ruolo + menu Slot
      C) (dopo iscrizione) reset ad A
    """

    def __init__(
        self,
        cog: "GameManagerIt",
        game: sqlite3.Row,
        invoker_id: int,
        ruolo_scelto: Optional[str] = None,
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog          = cog
        self.game         = game
        self.invoker_id   = invoker_id
        self.ruolo_scelto = ruolo_scelto
        self._costruisci()

    def _carica_giocatori(self) -> list[sqlite3.Row]:
        with get_db() as conn:
            return conn.execute(
                "SELECT * FROM Players WHERE game_id=? ORDER BY role, slot",
                (self.game["id"],),
            ).fetchall()

    def _slot_liberi(self, ruolo: str, giocatori: list[sqlite3.Row]) -> list[int]:
        occupati = {r["slot"] for r in giocatori if r["role"] == ruolo}
        return [s for s in range(1, self.game["max_players"] + 1) if s not in occupati]

    def _costruisci(self):
        self.clear_items()
        giocatori = self._carica_giocatori()

        # ── Menu Ruolo ───────────────────────────────────────────────────────
        menu_ruolo = discord.ui.Select(
            placeholder="1️⃣ Scegli il tuo ruolo…",
            options=[
                discord.SelectOption(label="Giocatore", value="player",  emoji="🎮"),
                discord.SelectOption(label="Sponsor",   value="sponsor", emoji="💰"),
            ],
            custom_id="pl_ruolo_select",
        )
        if self.ruolo_scelto:
            for opt in menu_ruolo.options:
                opt.default = (opt.value == self.ruolo_scelto)

        async def ruolo_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.cog.mostra_lista_giocatori(
                interaction, self.game, ruolo_scelto=menu_ruolo.values[0]
            )

        menu_ruolo.callback = ruolo_callback
        self.add_item(menu_ruolo)

        # ── Menu Slot (visibile solo dopo aver scelto il ruolo) ───────────────
        if self.ruolo_scelto:
            liberi       = self._slot_liberi(self.ruolo_scelto, giocatori)
            nome_ruolo_it = "Giocatore" if self.ruolo_scelto == "player" else "Sponsor"
            if liberi:
                menu_slot = discord.ui.Select(
                    placeholder=f"2️⃣ Scegli il tuo slot ({nome_ruolo_it})…",
                    options=[discord.SelectOption(label=f"Slot {s}", value=str(s)) for s in liberi[:25]],
                    custom_id="pl_slot_select",
                )

                async def slot_callback(interaction: discord.Interaction):
                    slot  = int(menu_slot.values[0])
                    uid   = interaction.user.id
                    ruolo = self.ruolo_scelto

                    with get_db() as conn:
                        qualsiasi_esistente = conn.execute(
                            "SELECT role FROM Players WHERE game_id=? AND user_id=?",
                            (self.game["id"], uid),
                        ).fetchone()

                    if qualsiasi_esistente:
                        ruolo_esistente = qualsiasi_esistente["role"]
                        nome_r_es = "Giocatore" if ruolo_esistente == "player" else "Sponsor"
                        nome_r_nu = "Giocatore" if ruolo == "player" else "Sponsor"
                        if ruolo_esistente == ruolo:
                            msg = f"❌ Sei già iscritto come **{nome_r_es}** in questa partita."
                        else:
                            msg = (
                                f"❌ Sei già in questa partita come **{nome_r_es}**. "
                                f"Non puoi iscriverti anche come **{nome_r_nu}**."
                            )
                        await interaction.response.send_message(msg, ephemeral=True)
                        return

                    try:
                        with get_db() as conn:
                            conn.execute(
                                "INSERT INTO Players (game_id, user_id, role, slot) VALUES (?,?,?,?)",
                                (self.game["id"], uid, ruolo, slot),
                            )
                    except sqlite3.IntegrityError:
                        await interaction.response.send_message(
                            "❌ Questo slot è stato appena occupato. Scegline un altro.", ephemeral=True
                        )
                        return

                    await interaction.response.defer()
                    await self.cog.mostra_lista_giocatori(interaction, self.game)

                menu_slot.callback = slot_callback
                self.add_item(menu_slot)
            else:
                self.add_item(discord.ui.Select(
                    placeholder=f"Nessuno slot {nome_ruolo_it} disponibile!",
                    options=[discord.SelectOption(label="—", value="nessuno")],
                    disabled=True,
                    custom_id="pl_slot_disabilitato",
                ))

        # ── Gestisci Giocatori (solo host/admin) ─────────────────────────────
        if _can_manage(self.game, self.invoker_id) and giocatori:
            opzioni_gestione = [
                discord.SelectOption(
                    label=f"[{'Giocatore' if p['role'] == 'player' else 'Sponsor'} #{p['slot']}] ID:{p['user_id']}",
                    value=str(p["id"]),
                    emoji="❌",
                )
                for p in giocatori[:25]
            ]
            menu_gestisci = discord.ui.Select(
                placeholder="🛠️ Gestisci Giocatori — seleziona per rimuovere…",
                options=opzioni_gestione,
                custom_id="pl_gestisci_select",
            )

            async def gestisci_callback(interaction: discord.Interaction):
                if not _can_manage(self.game, interaction.user.id):
                    await interaction.response.send_message(
                        "❌ Non hai i permessi per gestire i giocatori di questa partita.", ephemeral=True
                    )
                    return
                with get_db() as conn:
                    conn.execute("DELETE FROM Players WHERE id=?", (int(menu_gestisci.values[0]),))
                await interaction.response.defer()
                await self.cog.mostra_lista_giocatori(interaction, self.game)

            menu_gestisci.callback = gestisci_callback
            self.add_item(menu_gestisci)

        # ── Assegna Ruoli (solo host/admin) ───────────────────────────────────
        if _can_manage(self.game, self.invoker_id):
            btn_ruoli = discord.ui.Button(
                label="🎭 Assegna Ruoli nel Server",
                style=discord.ButtonStyle.primary,
                row=3,
            )

            async def assegna_ruoli_callback(interaction: discord.Interaction):
                if not _can_manage(self.game, interaction.user.id):
                    await interaction.response.send_message(
                        "❌ Non hai i permessi.", ephemeral=True
                    )
                    return

                raw_gid = _safe_get(self.game, "guild_id")
                if not raw_gid:
                    await interaction.response.send_message(
                        "❌ Server ID non configurato per questa partita. "
                        "Modificalo dal menu **✏️ Modifica un campo**.", ephemeral=True
                    )
                    return

                try:
                    target_guild_id = int(raw_gid)
                except ValueError:
                    await interaction.response.send_message(
                        "❌ Server ID non valido (deve essere numerico).", ephemeral=True
                    )
                    return

                target_guild = interaction.client.get_guild(target_guild_id)
                if not target_guild:
                    await interaction.response.send_message(
                        "❌ Server non trovato. Verifica che il bot sia in quel server "
                        "e che il Server ID sia corretto.", ephemeral=True
                    )
                    return

                guild_data = load_guild_data(target_guild.id)
                if not guild_data:
                    await interaction.response.send_message(
                        "❌ Dati di configurazione del server non trovati.", ephemeral=True
                    )
                    return

                alive_role   = discord.utils.get(target_guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(target_guild.roles, name=guild_data["sponsor_role_name"])

                with get_db() as conn:
                    players_db = conn.execute(
                        "SELECT * FROM Players WHERE game_id=?", (self.game["id"],)
                    ).fetchall()

                await interaction.response.defer(ephemeral=True)

                assegnati, non_trovati, errori = 0, 0, 0
                for p in players_db:
                    member = target_guild.get_member(p["user_id"])
                    if not member:
                        non_trovati += 1
                        continue
                    role_to_add = alive_role if p["role"] == "player" else sponsor_role
                    if not role_to_add:
                        errori += 1
                        continue
                    try:
                        await member.add_roles(role_to_add, reason="Assegnazione ruoli partita")
                        assegnati += 1
                    except discord.Forbidden:
                        errori += 1
                    except Exception:
                        errori += 1

                righe = [f"✅ Ruoli assegnati con successo: **{assegnati}**"]
                if non_trovati:
                    righe.append(f"⚠️ Non presenti nel server: **{non_trovati}**")
                if errori:
                    righe.append(f"❌ Errori (ruolo mancante / permessi): **{errori}**")
                await interaction.followup.send("\n".join(righe), ephemeral=True)

            btn_ruoli.callback = assegna_ruoli_callback
            self.add_item(btn_ruoli)

        # ── Abbandona (visibile solo se l'invoker è in questa partita) ────────
        with get_db() as conn:
            propria_entry = conn.execute(
                "SELECT id, role FROM Players WHERE game_id=? AND user_id=?",
                (self.game["id"], self.invoker_id),
            ).fetchone()

        if propria_entry:
            nome_ruolo_label = "Giocatore" if propria_entry["role"] == "player" else "Sponsor"
            btn_abbandona = discord.ui.Button(
                label=f"🚪 Abbandona ({nome_ruolo_label})",
                style=discord.ButtonStyle.danger,
                row=4,
            )
            async def abbandona_callback(interaction: discord.Interaction):
                with get_db() as conn:
                    entry = conn.execute(
                        "SELECT id FROM Players WHERE game_id=? AND user_id=?",
                        (self.game["id"], interaction.user.id),
                    ).fetchone()
                if not entry:
                    await interaction.response.send_message(
                        "❌ Non sei iscritto a questa partita.", ephemeral=True
                    )
                    return
                with get_db() as conn:
                    conn.execute("DELETE FROM Players WHERE id=?", (entry["id"],))
                await interaction.response.defer()
                await self.cog.mostra_lista_giocatori(interaction, self.game)
            btn_abbandona.callback = abbandona_callback
            self.add_item(btn_abbandona)

        # ── Indietro ──────────────────────────────────────────────────────────
        btn_indietro = discord.ui.Button(label="⬅️ Indietro", style=discord.ButtonStyle.secondary, row=4)
        async def indietro_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.cog.mostra_dettaglio_partita(interaction, self.game)
        btn_indietro.callback = indietro_callback
        self.add_item(btn_indietro)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ──────────────────────────────────────────────────────────────────────────────
# COG
# ──────────────────────────────────────────────────────────────────────────────

class GameManagerIt(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

    async def mostra_calendario(self, interaction: discord.Interaction, pagina: int = 0):
        view  = CalendarioView(self, interaction.user.id, pagina)
        embed = view.build_embed()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    async def mostra_dettaglio_partita(
        self, interaction: discord.Interaction, game: sqlite3.Row
    ):
        embed = dettaglio_partita_embed(game, self.bot)
        view  = DettaglioPartitaView(self, game, interaction.user.id)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    async def mostra_lista_giocatori(
        self,
        interaction: discord.Interaction,
        game: sqlite3.Row,
        ruolo_scelto: Optional[str] = None,
    ):
        with get_db() as conn:
            giocatori = conn.execute(
                "SELECT * FROM Players WHERE game_id=? ORDER BY role, slot",
                (game["id"],),
            ).fetchall()
        embed = lista_giocatori_embed(game, giocatori)
        view  = ListaGiocatoriView(self, game, interaction.user.id, ruolo_scelto=ruolo_scelto)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    @commands.command(name="calendario")
    async def calendario_cmd(self, ctx: commands.Context):
        """Apre il Calendario di The Village."""
        view  = CalendarioView(self, ctx.author.id)
        embed = view.build_embed()
        await ctx.send(embed=embed, view=view)


# ──────────────────────────────────────────────────────────────────────────────
# SETUP
# ──────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(GameManagerIt(bot))