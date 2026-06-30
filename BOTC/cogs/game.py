from __future__ import annotations

import asyncio
import json
import math
import os
import time
from dataclasses import dataclass, field

import discord
from discord.ext import commands
from cogs.data_utils import load_guild_data

NOMINATION_TIMEOUT = 120
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(DATA_DIR, "game_state.json")


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class PlayerState:
    user_id: int
    dead: bool = False
    has_dead_vote: bool = False
    is_sponsor: bool = False


@dataclass
class Nomination:
    nominator_id: int
    nominee_id: int
    accusation: str = "No accusation."
    defense: str = "No defense."
    votes: dict[int, bool] = field(default_factory=dict)
    current_clock_index: int = 0
    closed: bool = False
    expires_at: float = 0.0


@dataclass
class GameState:
    seating_order: list[int] = field(default_factory=list)
    players: dict[int, PlayerState] = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_state() -> dict[int, GameState]:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[int, GameState] = {}
    for gid_str, data in raw.items():
        gid = int(gid_str)
        seating = data.get("seating_order", [])
        players_raw = data.get("players", {})
        players = {}
        for uid_str, pd in players_raw.items():
            players[int(uid_str)] = PlayerState(**pd)
        out[gid] = GameState(seating_order=seating, players=players)
    return out


def _save_state(states: dict[int, GameState]):
    os.makedirs(DATA_DIR, exist_ok=True)
    raw: dict[str, dict] = {}
    for gid, gs in states.items():
        players_raw = {}
        for uid, ps in gs.players.items():
            players_raw[str(uid)] = {
                "user_id": ps.user_id,
                "dead": ps.dead,
                "has_dead_vote": ps.has_dead_vote,
                "is_sponsor": ps.is_sponsor,
            }
        raw[str(gid)] = {
            "seating_order": gs.seating_order,
            "players": players_raw,
        }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)


def get_clock_order(seating: list[int], nominee_id: int) -> list[int]:
    i = seating.index(nominee_id)
    return seating[i + 1:] + seating[:i + 1]


def can_vote(player: PlayerState | None) -> bool:
    if player is None:
        return False
    if player.is_sponsor:
        return False
    if not player.dead:
        return True
    return player.has_dead_vote


def _username(user_id: int) -> str:
    return f"<@{user_id}>"


# ── Vote View ────────────────────────────────────────────────────────────────

class VoteView(discord.ui.View):
    def __init__(self, cog: BOTCGame, guild_id: int, nom: Nomination, timeout_secs: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.nom = nom
        self._alive_count = 0
        self._required = 0

    def _refresh_alive_info(self, guild: discord.Guild):
        guild_data = load_guild_data(self.guild_id)
        if not guild_data:
            return
        role_name = guild_data.get("alive_role_name")
        if not role_name:
            return
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            return
        self._alive_count = sum(1 for m in role.members if not m.bot)
        self._required = math.ceil(self._alive_count / 2)

    def _vote_icon(self, uid: int) -> str:
        ps = self.cog._get_state(self.guild_id).players.get(uid)
        vote = self.nom.votes.get(uid)
        if vote is True:
            return "✅"
        if vote is False:
            return "❌"
        if ps and ps.is_sponsor:
            return "⭐"
        if ps and ps.dead:
            return "☠️🗳️" if ps.has_dead_vote else "☠️"
        return "—"

    def _build_seating_chart(self, gs: GameState) -> str:
        if not gs.seating_order:
            return "No seating order set."
        clock_order = get_clock_order(gs.seating_order, self.nom.nominee_id)
        current_target = clock_order[self.nom.current_clock_index] if clock_order else None
        lines = []
        for uid in gs.seating_order:
            marker = "🕦 " if uid == current_target else "   "
            icon = self._vote_icon(uid)
            lines.append(f"{marker}{_username(uid)} {icon}")
        return "\n".join(lines)

    def _build_embed(self) -> discord.Embed:
        gs = self.cog._get_state(self.guild_id)
        nominee = self.cog.bot.get_user(self.nom.nominee_id)
        nominator = self.cog.bot.get_user(self.nom.nominator_id)
        n_name = nominee.display_name if nominee else _username(self.nom.nominee_id)
        nom_name = nominator.display_name if nominator else _username(self.nom.nominator_id)

        guilty = sum(1 for v in self.nom.votes.values() if v)
        notguilty = sum(1 for v in self.nom.votes.values() if not v)
        total = guilty + notguilty

        embed = discord.Embed(
            title=f"🗳️ {nom_name} nominated {n_name}",
            color=discord.Color.teal(),
        )

        embed.add_field(name="Accusation", value=self.nom.accusation, inline=False)
        embed.add_field(name="Defense", value=self.nom.defense, inline=False)

        embed.add_field(
            name="Seating",
            value=self._build_seating_chart(gs),
            inline=False,
        )

        clock_order = get_clock_order(gs.seating_order, self.nom.nominee_id) if gs.seating_order else []
        clock_name = _username(clock_order[self.nom.current_clock_index]) if clock_order else "—"
        status = "Closed" if self.nom.closed else f"Clock: {clock_name}"
        embed.set_footer(
            text=f"🟥 {guilty}  🟩 {notguilty}  |  Turnout: {total}/{self._alive_count}  |  Need: {self._required}  |  {status}"
        )
        return embed

    async def _refresh(self):
        msg = self.cog._messages.get(self.guild_id)
        if msg:
            await msg.edit(embed=self._build_embed(), view=self)

    async def _has_alive_role(self, user: discord.Member) -> bool:
        guild_data = load_guild_data(self.guild_id)
        if not guild_data:
            return False
        role_name = guild_data.get("alive_role_name")
        if not role_name:
            return False
        role = discord.utils.get(user.guild.roles, name=role_name)
        return role is not None and role in user.roles

    async def _close(self):
        self.nom.closed = True
        for child in self.children:
            child.disabled = True
        await self._refresh()
        if self.guild_id in self.cog._tasks:
            self.cog._tasks[self.guild_id].cancel()

    async def _vote(self, interaction: discord.Interaction, guilty: bool):
        if self.nom.closed:
            return await interaction.response.send_message("Voting is closed.", ephemeral=True)
        if not await self._has_alive_role(interaction.user):
            return await interaction.response.send_message("Only alive players can vote.", ephemeral=True)
        ps = self.cog._get_state(self.guild_id).players.get(interaction.user.id)
        if not can_vote(ps):
            if ps and ps.is_sponsor:
                return await interaction.response.send_message("Sponsors cannot vote.", ephemeral=True)
            if ps and ps.dead:
                return await interaction.response.send_message("You are dead and have no dead vote left.", ephemeral=True)
            return await interaction.response.send_message("You cannot vote.", ephemeral=True)
        self._refresh_alive_info(interaction.guild)
        self.nom.votes[interaction.user.id] = guilty
        if ps and ps.dead and ps.has_dead_vote:
            ps.has_dead_vote = False
            self.cog._save()
        await self._refresh()
        label = "Guilty" if guilty else "Not Guilty"
        await interaction.response.send_message(f"You voted **{label}**.", ephemeral=True)

    async def _advance_clock(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Only the Storyteller can advance the clock.", ephemeral=True)
        gs = self.cog._get_state(self.guild_id)
        clock_order = get_clock_order(gs.seating_order, self.nom.nominee_id)
        if not clock_order:
            return await interaction.response.send_message("No seating order.", ephemeral=True)
        for _ in range(len(clock_order)):
            self.nom.current_clock_index = (self.nom.current_clock_index + 1) % len(clock_order)
            target = clock_order[self.nom.current_clock_index]
            ps = gs.players.get(target)
            if target != self.nom.nominee_id and can_vote(ps):
                break
        await self._refresh()
        await interaction.response.defer()

    async def _back_clock(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Only the Storyteller can advance the clock.", ephemeral=True)
        gs = self.cog._get_state(self.guild_id)
        clock_order = get_clock_order(gs.seating_order, self.nom.nominee_id)
        if not clock_order:
            return await interaction.response.send_message("No seating order.", ephemeral=True)
        for _ in range(len(clock_order)):
            self.nom.current_clock_index = (self.nom.current_clock_index - 1) % len(clock_order)
            target = clock_order[self.nom.current_clock_index]
            ps = gs.players.get(target)
            if target != self.nom.nominee_id and can_vote(ps):
                break
        await self._refresh()
        await interaction.response.defer()

    @discord.ui.button(label="🟥 Guilty", style=discord.ButtonStyle.danger, row=0)
    async def guilty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, True)

    @discord.ui.button(label="🟩 Not Guilty", style=discord.ButtonStyle.success, row=0)
    async def notguilty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, False)

    @discord.ui.button(label="⏩ Advance Clock", style=discord.ButtonStyle.secondary, row=1)
    async def advance_clock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._advance_clock(interaction)

    @discord.ui.button(label="⏪ Back Clock", style=discord.ButtonStyle.secondary, row=1)
    async def back_clock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._back_clock(interaction)


# ── Cog ──────────────────────────────────────────────────────────────────────

class BOTCGame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GameState] = _load_state()
        self._messages: dict[int, discord.Message] = {}
        self._views: dict[int, VoteView] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._timeouts: dict[int, int] = {}

    def cog_unload(self):
        for t in self._tasks.values():
            t.cancel()

    def _get_state(self, guild_id: int) -> GameState:
        if guild_id not in self._states:
            self._states[guild_id] = GameState()
        return self._states[guild_id]

    def _save(self):
        _save_state(self._states)

    async def _expire(self, guild_id: int, view: VoteView):
        remaining = view.nom.expires_at - time.time()
        if remaining > 0:
            await asyncio.sleep(remaining)
        await view._close()
        channel = self._messages[guild_id].channel if guild_id in self._messages else None
        if channel:
            await channel.send("⏰ Nomination expired. Final tally above.")
        self._messages.pop(guild_id, None)
        self._views.pop(guild_id, None)
        self._tasks.pop(guild_id, None)

    # ── Seating ──────────────────────────────────────────────────────────────

    @commands.command(name="bsetseating")
    @commands.has_permissions(administrator=True)
    async def bsetseating(self, ctx: commands.Context, *members: discord.Member):
        """Set the BOTC seating order for this server."""
        if len(members) < 3:
            return await ctx.send("Need at least 3 players.")
        gs = self._get_state(ctx.guild.id)
        gs.seating_order = [m.id for m in members]
        for m in members:
            if m.id not in gs.players:
                gs.players[m.id] = PlayerState(user_id=m.id)
        self._save()
        names = ", ".join(m.display_name for m in members)
        await ctx.send(f"✅ Seating order set: {names}")

    @commands.command(name="bseating")
    async def bseating(self, ctx: commands.Context):
        """Show the current seating order."""
        gs = self._get_state(ctx.guild.id)
        if not gs.seating_order:
            return await ctx.send("No seating order set. Use `.bsetseating @p1 @p2 ...`")
        lines = []
        for i, uid in enumerate(gs.seating_order):
            ps = gs.players.get(uid)
            tags = []
            if ps and ps.dead:
                tags.append("☠️")
            if ps and ps.is_sponsor:
                tags.append("⭐")
            tag_str = " ".join(tags)
            tag_str = f" {tag_str}" if tag_str else ""
            lines.append(f"{i+1}. {_username(uid)}{tag_str}")
        await ctx.send("\n".join(lines))

    # ── Player State ─────────────────────────────────────────────────────────

    @commands.command(name="bkill")
    @commands.has_permissions(administrator=True)
    async def bkill(self, ctx: commands.Context, *, target: discord.Member):
        """Mark a player as dead. They lose their dead vote."""
        gs = self._get_state(ctx.guild.id)
        ps = gs.players.get(target.id)
        if not ps:
            return await ctx.send("Player not found in seating order.")
        ps.dead = True
        ps.has_dead_vote = False
        self._save()
        await ctx.send(f"☠️ {target.display_name} is dead.")

    @commands.command(name="brevive")
    @commands.has_permissions(administrator=True)
    async def brevive(self, ctx: commands.Context, *, target: discord.Member):
        """Revive a dead player with their dead vote restored."""
        gs = self._get_state(ctx.guild.id)
        ps = gs.players.get(target.id)
        if not ps:
            return await ctx.send("Player not found in seating order.")
        ps.dead = False
        ps.has_dead_vote = True
        self._save()
        await ctx.send(f"✨ {target.display_name} is alive.")

    @commands.command(name="bsponsor")
    @commands.has_permissions(administrator=True)
    async def bsponsor(self, ctx: commands.Context, *, target: discord.Member):
        """Mark a player as a sponsor (substitute, cannot vote)."""
        gs = self._get_state(ctx.guild.id)
        ps = gs.players.get(target.id)
        if not ps:
            return await ctx.send("Player not found in seating order.")
        ps.is_sponsor = True
        self._save()
        await ctx.send(f"⭐ {target.display_name} is now a sponsor.")

    @commands.command(name="bunsponsor")
    @commands.has_permissions(administrator=True)
    async def bunsponsor(self, ctx: commands.Context, *, target: discord.Member):
        """Remove sponsor status from a player."""
        gs = self._get_state(ctx.guild.id)
        ps = gs.players.get(target.id)
        if not ps:
            return await ctx.send("Player not found in seating order.")
        ps.is_sponsor = False
        self._save()
        await ctx.send(f"✅ {target.display_name} is no longer a sponsor.")

    # ── Nomination ───────────────────────────────────────────────────────────

    @commands.command(name="bnominate")
    @commands.has_permissions(administrator=True)
    async def bnominate(self, ctx: commands.Context, *, target: discord.Member):
        """Nominate a player. Voting buttons appear immediately."""
        if ctx.author == target:
            return await ctx.send("You cannot nominate yourself.")
        if ctx.guild.id in self._messages:
            return await ctx.send("A nomination is already in progress. Wait for it to finish.")
        gs = self._get_state(ctx.guild.id)
        if target.id not in gs.seating_order:
            return await ctx.send("Target is not in the seating order.")

        timeout = self._timeouts.get(ctx.guild.id, NOMINATION_TIMEOUT)
        nom = Nomination(
            nominator_id=ctx.author.id,
            nominee_id=target.id,
            expires_at=time.time() + timeout,
        )
        view = VoteView(self, ctx.guild.id, nom, timeout)
        view._refresh_alive_info(ctx.guild)
        msg = await ctx.send(embed=view._build_embed(), view=view)
        self._messages[ctx.guild.id] = msg
        self._views[ctx.guild.id] = view
        self._tasks[ctx.guild.id] = asyncio.create_task(self._expire(ctx.guild.id, view))

    @commands.command(name="baccuse")
    @commands.has_permissions(administrator=True)
    async def baccuse(self, ctx: commands.Context, *, text: str):
        """Set the accusation for the current nomination."""
        view = self._views.get(ctx.guild.id)
        if not view or view.nom.closed:
            return await ctx.send("No active nomination.")
        view.nom.accusation = text[:1024]
        await view._refresh()
        await ctx.send("✅ Accusation updated.")

    @commands.command(name="bdefend")
    @commands.has_permissions(administrator=True)
    async def bdefend(self, ctx: commands.Context, *, text: str):
        """Set the defense for the current nomination."""
        view = self._views.get(ctx.guild.id)
        if not view or view.nom.closed:
            return await ctx.send("No active nomination.")
        view.nom.defense = text[:1024]
        await view._refresh()
        await ctx.send("✅ Defense updated.")

    @commands.command(name="bnomtimeout")
    @commands.has_permissions(administrator=True)
    async def bnomtimeout(self, ctx: commands.Context, seconds: int):
        """Set the nomination expiry timeout for this server."""
        if seconds < 10:
            return await ctx.send("Minimum timeout is 10 seconds.")
        self._timeouts[ctx.guild.id] = seconds
        await ctx.send(f"⏱️ Nomination timeout set to {seconds} seconds.")

    @commands.command(name="bnoms")
    async def bnoms(self, ctx: commands.Context):
        """Show current nomination status."""
        view = self._views.get(ctx.guild.id)
        if not view or view.nom.closed:
            await ctx.send("No active nomination.")
            return
        view._refresh_alive_info(ctx.guild)
        await ctx.send(embed=view._build_embed())


async def setup(bot: commands.Bot):
    await bot.add_cog(BOTCGame(bot))
