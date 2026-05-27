"""
Overseer Intelligence Board — overseer_cog.py
A host-only tracking system for social deduction games.
"""
import os, sqlite3, discord, asyncio
from datetime import datetime
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput

# ── Constants ────────────────────────────────────────────────────
DB_PATH  = "db/overseer.db"
COLOR    = 0x7c3aed
FOOTER   = "Overseer Intelligence Board"

STATUS_DEFS = {
    "Control": {
        "⛔ Roleblocked":     None,
        "🤫 SilentRoleblock": None,
        "🚷 Visitblocked":    None,
        "🗳️ Voteblocked":     None,
        "🔒 CategoryBlocked": ["Info","Lethal","Manipulation","Transport","Custom"],
        "🧿 CategoryImmunity":["Info","Lethal","Manipulation","Transport","Custom"],
        "⚡ ForcedAction":    None,
        "🎯 RedirectedTo":    ["__player__","Random Redirect","Custom"],
    },
    "Defense": {
        "🛡️ Protected":     ["Physical","Remote","All Attacks","Statuses","Custom"],
        "🔰 StatusImmune":  None,
        "💎 Invulnerable":  None,
        "👻 Untargetable":  None,
        "❌ Unprotectable": None,
    },
    "Recovery":    {"💊 Cured": None, "☠️ Uncurable": None},
    "Modifiers":   {"⬆️ Buffed": None, "⬇️ Debuffed": None, "🔁 ExtraUses": None, "➕ ExtraVote": None, "👣 ExtraVisit": None},
    "Damage":      {"🩸 Bleeding": ["1 Phase","2 Phases","Until Healed","Escalating"]},
    "Scars":       {"🥀 Doried": ["__ability__"]},
    "Surveillance":{"👣 Tracked": ["Visits","Movements","All Actions"], "🔭 Following": ["__player__"], "👁️ Followed": ["__player__"]},
    "Special":     {"✨ Special": None},
}

DURATIONS  = ["This Phase","Next Phase","1 Cycle","2 Cycles","Permanent","Custom"]
INFO_TYPES = ["Role Info","Action Info","Lie/Truth","OS Advice","Evil Chat Check","Team Check","Special Note"]

# ── Phase utilities ───────────────────────────────────────────────
def phase_rank(ptype: str, pnum: int) -> int:
    return (pnum - 1) * 2 + (2 if ptype == "night" else 1)

def rank_to_label(rank: int) -> str:
    pnum = (rank + 1) // 2
    return f"{'Night' if rank % 2 == 0 else 'Day'} {pnum}"

def calc_expires(duration: str, cur_rank: int):
    """Returns (expires_rank, expires_label) or (None, 'Permanent')."""
    mapping = {"This Phase": 0, "Next Phase": 1, "1 Cycle": 2, "2 Cycles": 4}
    if duration in mapping:
        r = cur_rank + mapping[duration]
        return r, rank_to_label(r)
    return None, "Permanent"

# ── Database ─────────────────────────────────────────────────────
class OverseerDB:
    def __init__(self):
        os.makedirs("db", exist_ok=True)
        with self._c() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS config(
                    guild_id INTEGER PRIMARY KEY,
                    board_channel_id INTEGER,
                    phase_type TEXT DEFAULT 'day',
                    phase_number INTEGER DEFAULT 1,
                    phase_msg_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS player_cards(
                    guild_id INTEGER, player_id INTEGER,
                    message_id INTEGER, expanded INTEGER DEFAULT 1,
                    PRIMARY KEY(guild_id, player_id)
                );
                CREATE TABLE IF NOT EXISTS effects(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER, player_id INTEGER,
                    status_name TEXT, subtype TEXT, note TEXT,
                    applied_phase TEXT, expires_rank INTEGER,
                    expires_phase TEXT, source_host_id INTEGER,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS intel(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER, player_id INTEGER,
                    info_type TEXT, note TEXT,
                    phase TEXT, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER, player_id INTEGER,
                    event TEXT, phase TEXT, created_at TEXT
                );
            """)

    def _c(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # Config
    def get_cfg(self, gid):
        with self._c() as db:
            return db.execute("SELECT * FROM config WHERE guild_id=?", (gid,)).fetchone()

    def set_board(self, gid, ch_id):
        with self._c() as db:
            db.execute("INSERT OR IGNORE INTO config(guild_id) VALUES(?)", (gid,))
            db.execute("UPDATE config SET board_channel_id=? WHERE guild_id=?", (ch_id, gid))
            db.commit()

    def set_phase(self, gid, ptype, pnum):
        with self._c() as db:
            db.execute("INSERT OR IGNORE INTO config(guild_id) VALUES(?)", (gid,))
            db.execute("UPDATE config SET phase_type=?,phase_number=? WHERE guild_id=?", (ptype, pnum, gid))
            db.commit()

    def set_phase_msg(self, gid, msg_id):
        with self._c() as db:
            db.execute("UPDATE config SET phase_msg_id=? WHERE guild_id=?", (msg_id, gid))
            db.commit()

    # Player cards
    def get_cards(self, gid):
        with self._c() as db:
            return db.execute("SELECT * FROM player_cards WHERE guild_id=?", (gid,)).fetchall()

    def get_card(self, gid, pid):
        with self._c() as db:
            return db.execute("SELECT * FROM player_cards WHERE guild_id=? AND player_id=?", (gid, pid)).fetchone()

    def get_card_by_msg(self, gid, msg_id):
        with self._c() as db:
            return db.execute("SELECT * FROM player_cards WHERE guild_id=? AND message_id=?", (gid, msg_id)).fetchone()

    def upsert_card(self, gid, pid, msg_id):
        with self._c() as db:
            db.execute("INSERT OR REPLACE INTO player_cards(guild_id,player_id,message_id,expanded) VALUES(?,?,?,1)",
                       (gid, pid, msg_id))
            db.commit()

    def toggle_expand(self, gid, pid):
        with self._c() as db:
            db.execute("UPDATE player_cards SET expanded=1-expanded WHERE guild_id=? AND player_id=?", (gid, pid))
            db.commit()

    # Effects
    def add_effect(self, gid, pid, name, subtype, note, applied, exp_rank, exp_phase, host_id):
        with self._c() as db:
            db.execute("""INSERT INTO effects(guild_id,player_id,status_name,subtype,note,applied_phase,
                expires_rank,expires_phase,source_host_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (gid, pid, name, subtype, note, applied, exp_rank, exp_phase, host_id,
                 datetime.utcnow().isoformat()))
            db.commit()

    def get_effects(self, gid, pid):
        with self._c() as db:
            return db.execute("SELECT * FROM effects WHERE guild_id=? AND player_id=? ORDER BY id",
                              (gid, pid)).fetchall()

    def expire_effects(self, gid, cur_rank):
        with self._c() as db:
            rows = db.execute("""SELECT * FROM effects WHERE guild_id=? AND expires_rank IS NOT NULL
                AND expires_rank < ?""", (gid, cur_rank)).fetchall()
            if rows:
                db.execute("DELETE FROM effects WHERE guild_id=? AND expires_rank IS NOT NULL AND expires_rank<?",
                           (gid, cur_rank))
                db.commit()
            return rows

    # Intel
    def add_intel(self, gid, pid, itype, note, phase):
        with self._c() as db:
            db.execute("INSERT INTO intel(guild_id,player_id,info_type,note,phase,created_at) VALUES(?,?,?,?,?,?)",
                       (gid, pid, itype, note, phase, datetime.utcnow().isoformat()))
            db.commit()

    def get_intel(self, gid, pid):
        with self._c() as db:
            return db.execute("SELECT * FROM intel WHERE guild_id=? AND player_id=? ORDER BY id",
                              (gid, pid)).fetchall()

    # History
    def add_history(self, gid, pid, event, phase):
        with self._c() as db:
            db.execute("INSERT INTO history(guild_id,player_id,event,phase,created_at) VALUES(?,?,?,?,?)",
                       (gid, pid, event, phase, datetime.utcnow().isoformat()))
            db.commit()

    def get_history(self, gid, pid):
        with self._c() as db:
            return db.execute("SELECT * FROM history WHERE guild_id=? AND player_id=? ORDER BY id",
                              (gid, pid)).fetchall()

odb = OverseerDB()

# ── Card renderer ────────────────────────────────────────────────
def render_card(guild: discord.Guild, pid: int) -> discord.Embed:
    gid = guild.id
    member  = guild.get_member(pid)
    name    = member.display_name if member else f"Player {pid}"
    avatar  = member.display_avatar.url if member else None
    effects = odb.get_effects(gid, pid)
    intel   = odb.get_intel(gid, pid)
    cfg     = odb.get_cfg(gid)
    phase   = f"{cfg['phase_type'].capitalize()} {cfg['phase_number']}" if cfg else "?"
    card    = odb.get_card(gid, pid)
    expanded = card["expanded"] if card else 1

    embed = discord.Embed(color=COLOR, timestamp=datetime.utcnow())
    embed.set_footer(text=FOOTER)
    if avatar:
        embed.set_thumbnail(url=avatar)

    if not expanded:
        embed.title = f"▶  {name}"
        embed.description = (f"**{len(effects)}** Active Effects  •  **{len(intel)}** Intel Records\n"
                             f"Last Updated: {phase}")
        return embed

    embed.title = f"🔽  {name}"

    # Active effects
    if effects:
        lines = []
        for e in effects:
            l = f"**{e['status_name']}**"
            if e["subtype"]:  l += f"\n  ↳ *{e['subtype']}*"
            l += f"\n  📅 {e['applied_phase']}"
            l += f"  •  ⏳ Expires: {e['expires_phase']}" if e["expires_phase"] else "  •  ♾️ Permanent"
            if e["note"]:     l += f"\n  📝 {e['note']}"
            lines.append(l)
        val = "\n\n".join(lines)
        for chunk in [val[i:i+1024] for i in range(0, len(val), 1024)]:
            embed.add_field(name="⚡ ACTIVE EFFECTS", value=chunk, inline=False)
    else:
        embed.add_field(name="⚡ ACTIVE EFFECTS", value="*None*", inline=False)

    # Intel log grouped by phase
    if intel:
        by_phase = {}
        for rec in intel:
            by_phase.setdefault(rec["phase"], []).append(rec)
        lines = []
        for p, recs in by_phase.items():
            lines.append(f"**{p}**")
            for r in recs:
                lines.append(f"*{r['info_type']}:* {r['note']}")
        val = "\n".join(lines)
        for chunk in [val[i:i+1024] for i in range(0, len(val), 1024)]:
            embed.add_field(name="📋 INTEL LOG", value=chunk, inline=False)
    else:
        embed.add_field(name="📋 INTEL LOG", value="*None*", inline=False)

    return embed


# ── Session storage (keyed by (guild_id, user_id)) ───────────────
_sess: dict = {}
def _sk(i: discord.Interaction): return (i.guild_id, i.user.id)


# ── Modals ────────────────────────────────────────────────────────
class NoteModal(Modal, title="Add a Note (optional)"):
    note = TextInput(label="Note", style=discord.TextStyle.paragraph,
                     placeholder="Enter note…", max_length=500, required=False)
    def __init__(self, cog, sk):
        super().__init__(timeout=120)
        self.cog = cog; self.sk = sk
    async def on_submit(self, i: discord.Interaction):
        _sess[self.sk]["note"] = self.note.value.strip() or None
        await self.cog._save_effect(i, self.sk)


class AbilityModal(Modal, title="Which ability was Doried?"):
    ability = TextInput(label="Ability Name", placeholder="e.g. Investigate…", max_length=100)
    def __init__(self, cog, sk):
        super().__init__(timeout=120)
        self.cog = cog; self.sk = sk
    async def on_submit(self, i: discord.Interaction):
        _sess[self.sk]["subtype"] = self.ability.value.strip()
        await self.cog._step_duration(i, self.sk)


class CustomDurationModal(Modal, title="Custom Expiry Phase"):
    val = TextInput(label="Expires on phase (e.g. Night 5)", placeholder="Night 5 / Day 3…", max_length=50)
    def __init__(self, cog, sk):
        super().__init__(timeout=120)
        self.cog = cog; self.sk = sk
    async def on_submit(self, i: discord.Interaction):
        _sess[self.sk]["expires_rank"]  = None
        _sess[self.sk]["expires_phase"] = self.val.value.strip()
        await self.cog._step_note(i, self.sk)


class IntelNoteModal(Modal, title="Intel Note"):
    note = TextInput(label="Note", style=discord.TextStyle.paragraph, max_length=800, required=True)
    def __init__(self, cog, pid, itype, phase):
        super().__init__(timeout=120)
        self.cog = cog; self.pid = pid; self.itype = itype; self.phase = phase
    async def on_submit(self, i: discord.Interaction):
        odb.add_intel(i.guild_id, self.pid, self.itype, self.note.value.strip(), self.phase)
        odb.add_history(i.guild_id, self.pid, f"Intel: {self.itype}", self.phase)
        await i.response.send_message(f"✅ Intel logged — *{self.itype}*.", ephemeral=True)
        await self.cog._refresh_card(i.guild, self.pid)


# ── Persistent Player Card View ───────────────────────────────────
def _get_cog(bot): return bot.get_cog("Overseer")

class PlayerCardView(View):
    """Registered on startup — custom_ids survive restarts.
    Player is identified by looking up message_id in the DB."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add Effect", style=discord.ButtonStyle.primary,
                       emoji="⚡", custom_id="oib:add_effect")
    async def add_effect(self, i: discord.Interaction, _: Button):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("Admins only.", ephemeral=True)
        card = odb.get_card_by_msg(i.guild_id, i.message.id)
        if not card:
            return await i.response.send_message("Card not found in DB.", ephemeral=True)
        await _get_cog(i.client)._start_effect_flow(i, card["player_id"])

    @discord.ui.button(label="Add Info", style=discord.ButtonStyle.success,
                       emoji="📝", custom_id="oib:add_info")
    async def add_info(self, i: discord.Interaction, _: Button):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("Admins only.", ephemeral=True)
        card = odb.get_card_by_msg(i.guild_id, i.message.id)
        if not card:
            return await i.response.send_message("Card not found in DB.", ephemeral=True)
        await _get_cog(i.client)._start_info_flow(i, card["player_id"])

    @discord.ui.button(label="History", style=discord.ButtonStyle.secondary,
                       emoji="🕰️", custom_id="oib:history")
    async def history(self, i: discord.Interaction, _: Button):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("Admins only.", ephemeral=True)
        card = odb.get_card_by_msg(i.guild_id, i.message.id)
        if not card:
            return await i.response.send_message("Card not found in DB.", ephemeral=True)
        rows = odb.get_history(i.guild_id, card["player_id"])
        if not rows:
            return await i.response.send_message("No history yet.", ephemeral=True)
        lines = [f"**{r['phase']}** — {r['event']}" for r in rows]
        desc  = "\n".join(lines)[-4000:]
        embed = discord.Embed(title="🕰️ History", description=desc, color=COLOR)
        embed.set_footer(text=FOOTER)
        await i.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Toggle", style=discord.ButtonStyle.secondary,
                       emoji="🔼", custom_id="oib:toggle")
    async def toggle(self, i: discord.Interaction, _: Button):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("Admins only.", ephemeral=True)
        card = odb.get_card_by_msg(i.guild_id, i.message.id)
        if not card:
            return await i.response.send_message("Card not found in DB.", ephemeral=True)
        odb.toggle_expand(i.guild_id, card["player_id"])
        await i.response.edit_message(embed=render_card(i.guild, card["player_id"]))


# ── Cog ──────────────────────────────────────────────────────────
class Overseer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(PlayerCardView())   # re-register persistent view on startup

    def _phase_label(self, gid: int) -> str:
        cfg = odb.get_cfg(gid)
        if not cfg: return "Day 1"
        return f"{cfg['phase_type'].capitalize()} {cfg['phase_number']}"

    async def _refresh_card(self, guild: discord.Guild, pid: int):
        card = odb.get_card(guild.id, pid)
        if not card or not card["message_id"]: return
        cfg = odb.get_cfg(guild.id)
        if not cfg or not cfg["board_channel_id"]: return
        ch = guild.get_channel(cfg["board_channel_id"])
        if not ch: return
        try:
            msg = await ch.fetch_message(card["message_id"])
            await msg.edit(embed=render_card(guild, pid))
        except (discord.NotFound, discord.HTTPException):
            pass

    # ── Commands ──────────────────────────────────────────────────

    @commands.command()
    async def setboard(self, ctx, channel: discord.TextChannel = None):
        """Set the private overseer board channel. Usage: .setboard #channel"""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("Admins only.")
        ch = channel or ctx.channel
        odb.set_board(ctx.guild.id, ch.id)
        await ctx.reply(f"✅ Overseer board set to {ch.mention}.")

    @commands.command(name="setinfophase")
    async def setinfophase(self, ctx, ptype: str = None, pnum: int = None):
        """Advance the Overseer info phase. Usage: .setinfophase night 4"""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("Admins only.")
        if ptype not in ("day", "night") or pnum is None:
            return await ctx.reply("Usage: `.setinfophase day 5` or `.setinfophase night 4`")

        gid   = ctx.guild.id
        label = f"{ptype.capitalize()} {pnum}"
        odb.set_phase(gid, ptype, pnum)
        cur_rank = phase_rank(ptype, pnum)

        # Expire effects and archive to history
        expired  = odb.expire_effects(gid, cur_rank)
        by_player: dict = {}
        for e in expired:
            by_player.setdefault(e["player_id"], []).append(e)
        for pid, effs in by_player.items():
            for e in effs:
                odb.add_history(gid, pid, f"{e['status_name']} expired", label)
            await self._refresh_card(ctx.guild, pid)

        # Update / post phase indicator message
        phase_embed = discord.Embed(
            title=f"📍  CURRENT PHASE:  {label}",
            color=0xfbbf24, timestamp=datetime.utcnow())
        phase_embed.set_footer(text=FOOTER)

        cfg = odb.get_cfg(gid)
        ch  = ctx.guild.get_channel(cfg["board_channel_id"]) if cfg and cfg["board_channel_id"] else None
        if ch:
            if cfg and cfg["phase_msg_id"]:
                try:
                    m = await ch.fetch_message(cfg["phase_msg_id"])
                    await m.edit(embed=phase_embed)
                except (discord.NotFound, discord.HTTPException):
                    m = await ch.send(embed=phase_embed)
                    odb.set_phase_msg(gid, m.id)
            else:
                m = await ch.send(embed=phase_embed)
                odb.set_phase_msg(gid, m.id)

        exp_note = f"  ({len(expired)} effect(s) expired)" if expired else ""
        await ctx.reply(f"✅ Phase set to **{label}**{exp_note}.")

    @commands.command()
    async def addcard(self, ctx, member: discord.Member):
        """Create a player card for a member. Usage: .addcard @player"""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("Admins only.")
        cfg = odb.get_cfg(ctx.guild.id)
        if not cfg or not cfg["board_channel_id"]:
            return await ctx.reply("Set the board channel first: `.setboard #channel`")
        ch = ctx.guild.get_channel(cfg["board_channel_id"])
        if not ch:
            return await ctx.reply("Board channel not found.")
        if odb.get_card(ctx.guild.id, member.id):
            return await ctx.reply(f"Card already exists for {member.display_name}.")
        msg = await ch.send(embed=render_card(ctx.guild, member.id), view=PlayerCardView())
        odb.upsert_card(ctx.guild.id, member.id, msg.id)
        await ctx.reply(f"✅ Player card created for **{member.display_name}**.", delete_after=5)

    @commands.command()
    async def refreshcards(self, ctx):
        """Refresh all player card embeds from the DB. Usage: .refreshcards"""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.reply("Admins only.")
        cards = odb.get_cards(ctx.guild.id)
        for card in cards:
            await self._refresh_card(ctx.guild, card["player_id"])
        await ctx.reply(f"✅ Refreshed {len(cards)} card(s).")

    # ── Add Effect — multi-step ephemeral flow ────────────────────

    async def _start_effect_flow(self, i: discord.Interaction, pid: int):
        sk = _sk(i)
        _sess[sk] = {"pid": pid}
        cats = list(STATUS_DEFS.keys())
        sel  = Select(placeholder="1/5  Select Category…",
                      options=[discord.SelectOption(label=c, value=c) for c in cats])
        async def on_cat(interaction: discord.Interaction):
            _sess[sk]["category"] = sel.values[0]
            await self._step_status(interaction, sk)
        sel.callback = on_cat
        v = View(timeout=120); v.add_item(sel)
        await i.response.send_message("**Step 1 / 5 — Select Category**", view=v, ephemeral=True)

    async def _step_status(self, i: discord.Interaction, sk):
        cat      = _sess[sk]["category"]
        statuses = list(STATUS_DEFS[cat].keys())
        sel = Select(placeholder="2/5  Select Status…",
                     options=[discord.SelectOption(label=s, value=s) for s in statuses[:25]])
        async def on_status(interaction: discord.Interaction):
            chosen   = sel.values[0]
            subtypes = STATUS_DEFS[cat][chosen]
            _sess[sk]["status"] = chosen
            if subtypes is None:
                _sess[sk]["subtype"] = None
                await self._step_duration(interaction, sk)
            elif "__player__" in subtypes:
                await self._step_player_target(interaction, sk)
            elif "__ability__" in subtypes:
                await interaction.response.send_modal(AbilityModal(self, sk))
            else:
                await self._step_subtype(interaction, sk, subtypes)
        sel.callback = on_status
        v = View(timeout=120); v.add_item(sel)
        await i.response.edit_message(
            content=f"**Step 2 / 5 — Select Status**  *(Category: {cat})*", view=v)

    async def _step_subtype(self, i: discord.Interaction, sk, subtypes: list):
        sel = Select(placeholder="3/5  Select Subtype…",
                     options=[discord.SelectOption(label=s, value=s) for s in subtypes[:25]])
        async def on_sub(interaction: discord.Interaction):
            _sess[sk]["subtype"] = sel.values[0]
            await self._step_duration(interaction, sk)
        sel.callback = on_sub
        v = View(timeout=120); v.add_item(sel)
        await i.response.edit_message(content="**Step 3 / 5 — Select Subtype**", view=v)

    async def _step_player_target(self, i: discord.Interaction, sk):
        cards   = odb.get_cards(i.guild_id)
        pid_self = _sess[sk]["pid"]
        members = [i.guild.get_member(c["player_id"]) for c in cards if c["player_id"] != pid_self]
        members = [m for m in members if m]
        opts = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in members[:23]]
        opts += [discord.SelectOption(label="Random Redirect", value="__random__"),
                 discord.SelectOption(label="Custom",          value="__custom__")]
        sel = Select(placeholder="3/5  Select Target Player…", options=opts)
        async def on_target(interaction: discord.Interaction):
            v = sel.values[0]
            if v == "__random__":   _sess[sk]["subtype"] = "Random Redirect"
            elif v == "__custom__": _sess[sk]["subtype"] = "Custom"
            else:
                m = interaction.guild.get_member(int(v))
                _sess[sk]["subtype"] = m.display_name if m else v
            await self._step_duration(interaction, sk)
        sel.callback = on_target
        v = View(timeout=120); v.add_item(sel)
        await i.response.edit_message(content="**Step 3 / 5 — Select Target Player**", view=v)

    async def _step_duration(self, i: discord.Interaction, sk):
        sel = Select(placeholder="4/5  Select Duration…",
                     options=[discord.SelectOption(label=d, value=d) for d in DURATIONS])
        async def on_dur(interaction: discord.Interaction):
            dur = sel.values[0]
            if dur == "Custom":
                await interaction.response.send_modal(CustomDurationModal(self, sk))
                return
            cfg      = odb.get_cfg(interaction.guild_id)
            cur_rank = phase_rank(cfg["phase_type"], cfg["phase_number"]) if cfg else 1
            er, ep   = calc_expires(dur, cur_rank)
            _sess[sk]["expires_rank"]  = er
            _sess[sk]["expires_phase"] = ep if ep != "Permanent" else None
            await self._step_note(interaction, sk)
        sel.callback = on_dur
        v = View(timeout=120); v.add_item(sel)
        await i.response.edit_message(content="**Step 4 / 5 — Select Duration**", view=v)

    async def _step_note(self, i: discord.Interaction, sk):
        skip  = Button(label="Skip Note",  style=discord.ButtonStyle.secondary, emoji="⏭️")
        write = Button(label="Write Note", style=discord.ButtonStyle.primary,   emoji="✏️")
        async def on_skip(interaction: discord.Interaction):
            _sess[sk]["note"] = None
            await self._save_effect(interaction, sk)
        async def on_write(interaction: discord.Interaction):
            await interaction.response.send_modal(NoteModal(self, sk))
        skip.callback  = on_skip
        write.callback = on_write
        v = View(timeout=120); v.add_item(skip); v.add_item(write)
        await i.response.edit_message(content="**Step 5 / 5 — Optional Note**", view=v)

    async def _save_effect(self, i: discord.Interaction, sk):
        s     = _sess.pop(sk, {})
        gid   = i.guild_id
        pid   = s["pid"]
        phase = self._phase_label(gid)
        odb.add_effect(gid, pid, s["status"], s.get("subtype"), s.get("note"),
                       phase, s.get("expires_rank"), s.get("expires_phase"), i.user.id)
        odb.add_history(gid, pid, f"{s['status']} added", phase)
        await i.response.edit_message(
            content=f"✅ **{s['status']}** saved to card.", view=None)
        await self._refresh_card(i.guild, pid)

    # ── Add Info flow ─────────────────────────────────────────────

    async def _start_info_flow(self, i: discord.Interaction, pid: int):
        sel = Select(placeholder="Select Info Type…",
                     options=[discord.SelectOption(label=t, value=t) for t in INFO_TYPES])
        async def on_type(interaction: discord.Interaction):
            itype = sel.values[0]
            phase = self._phase_label(interaction.guild_id)
            await interaction.response.send_modal(IntelNoteModal(self, pid, itype, phase))
        sel.callback = on_type
        v = View(timeout=120); v.add_item(sel)
        await i.response.send_message("**Add Info — Select Type**", view=v, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Overseer(bot))
