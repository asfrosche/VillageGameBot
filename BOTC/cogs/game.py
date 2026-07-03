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

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(DATA_DIR, "game_state.json")


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class PlayerState:
    user_id: int
    dead: bool = False
    has_dead_vote: bool = False
    sponsor_id: int | None = None


ACCUSE_MAX_LEN = 1021


@dataclass
class Nomination:
    id: int
    nominator_id: int
    nominee_id: int
    accusation: str = "No accusation."
    defense: str = "No defense."
    votes: dict[int, bool] = field(default_factory=dict)
    finalized: set[int] = field(default_factory=set)
    current_clock_index: int = 0
    closed: bool = False
    expires_at: float = 0.0
    accusation_pending: bool = False
    defense_pending: bool = False


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
            pd.pop("is_sponsor", None)
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
                "sponsor_id": ps.sponsor_id,
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
    if not player.dead:
        return True
    return player.has_dead_vote


def _username(user_id: int) -> str:
    return f"<@{user_id}>"


# ── Vote View ────────────────────────────────────────────────────────────────

class ViewAccuseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="View Accusation", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        view: VoteView = self.view
        await interaction.response.send_message(view.nom.accusation, ephemeral=True)


class ViewDefendButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="View Defense", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        view: VoteView = self.view
        await interaction.response.send_message(view.nom.defense, ephemeral=True)


class VoteView(discord.ui.View):
    def __init__(self, cog: BOTCGame, guild_id: int, nom: Nomination, timeout_secs: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.nom = nom
        self._alive_count = 0
        self._required = 0

        if len(nom.accusation) > ACCUSE_MAX_LEN:
            self.add_item(ViewAccuseButton())
        if len(nom.defense) > ACCUSE_MAX_LEN:
            self.add_item(ViewDefendButton())

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
        if uid in self.nom.finalized:
            if vote is True:
                return "✅"
            if vote is False:
                return "❌"
        if vote is True:
            return "◐"
        if vote is False:
            return "◑"
        if ps and ps.dead:
            return "☠️🗳️" if ps.has_dead_vote else "☠️"
        if ps and ps.sponsor_id is not None:
            return "⭐"
        return "—"

    def _build_seating_chart(self, gs: GameState) -> str:
        if not gs.seating_order:
            return "No seating order set."
        clock_order = get_clock_order(gs.seating_order, self.nom.nominee_id)
        idx = self.nom.current_clock_index
        ordered = clock_order[idx:] + clock_order[:idx]
        current_target = clock_order[idx] if clock_order else None
        lines = []
        for uid in ordered:
            marker = "🕦 " if uid == current_target else "   "
            icon = self._vote_icon(uid)
            lines.append(f"{marker}{_username(uid)} {icon}")
        return "\n".join(lines)

    def _format_text(self, text: str) -> str:
        if len(text) > ACCUSE_MAX_LEN:
            return text[:ACCUSE_MAX_LEN] + "..."
        return text

    def _build_embed(self) -> discord.Embed:
        gs = self.cog._get_state(self.guild_id)
        nominee = self.cog.bot.get_user(self.nom.nominee_id)
        nominator = self.cog.bot.get_user(self.nom.nominator_id)
        n_name = nominee.display_name if nominee else _username(self.nom.nominee_id)
        nom_name = nominator.display_name if nominator else _username(self.nom.nominator_id)

        embed = discord.Embed(
            title=f"#{self.nom.id} 🗳️ {nom_name} nominated {n_name}",
            color=discord.Color.teal(),
        )

        acc = self._format_text(self.nom.accusation)
        def_ = self._format_text(self.nom.defense)
        if self.nom.accusation_pending:
            acc = "✏️ Awaiting accusation from nominator..."
        if self.nom.defense_pending:
            def_ = "✏️ Awaiting defense from nominee..."

        embed.add_field(name="Accusation", value=acc, inline=False)
        embed.add_field(name="Defense", value=def_, inline=False)

        embed.add_field(
            name="Seating",
            value=self._build_seating_chart(gs),
            inline=False,
        )

        finalized_guilty = sum(1 for uid in self.nom.finalized if self.nom.votes.get(uid))
        finalized_notguilty = sum(1 for uid in self.nom.finalized if self.nom.votes.get(uid) is False)
        pending = len(self.nom.votes) - len(self.nom.finalized)
        clock_order = get_clock_order(gs.seating_order, self.nom.nominee_id) if gs.seating_order else []
        clock_name = _username(clock_order[self.nom.current_clock_index]) if clock_order else "—"
        status = "Closed" if self.nom.closed else f"Clock: {clock_name}"
        embed.set_footer(
            text=f"🟥 {finalized_guilty}  🟩 {finalized_notguilty}  |  Pending: {pending}  |  Need: {self._required}  |  {status}"
        )
        return embed

    async def _refresh_ui(self):
        key = (self.guild_id, self.nom.id)
        msg = self.cog._messages.get(key)
        if msg:
            new_view = VoteView(self.cog, self.guild_id, self.nom, 0)
            new_view._alive_count = self._alive_count
            new_view._required = self._required
            if self.nom.closed:
                for child in new_view.children:
                    child.disabled = True
            await msg.edit(embed=new_view._build_embed(), view=new_view)
            self.cog._views[key] = new_view

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
        await self._refresh_ui()
        key = (self.guild_id, self.nom.id)
        if key in self.cog._tasks:
            self.cog._tasks[key].cancel()

    async def _vote(self, interaction: discord.Interaction, guilty: bool):
        if self.nom.closed:
            return await interaction.response.send_message("Voting is closed.", ephemeral=True)
        if not await self._has_alive_role(interaction.user):
            return await interaction.response.send_message("Only alive players can vote.", ephemeral=True)
        ps = self.cog._get_state(self.guild_id).players.get(interaction.user.id)
        if not can_vote(ps):
            if ps and ps.dead:
                return await interaction.response.send_message("You are dead and have no dead vote left.", ephemeral=True)
            return await interaction.response.send_message("You cannot vote.", ephemeral=True)
        self._refresh_alive_info(interaction.guild)
        self.nom.votes[interaction.user.id] = guilty
        if ps and ps.dead and ps.has_dead_vote:
            ps.has_dead_vote = False
            self.cog._save()

        gs = self.cog._get_state(self.guild_id)
        clock_order = get_clock_order(gs.seating_order, self.nom.nominee_id)
        if clock_order:
            for _ in range(len(clock_order)):
                self.nom.current_clock_index = (self.nom.current_clock_index + 1) % len(clock_order)
                target = clock_order[self.nom.current_clock_index]
                tps = gs.players.get(target)
                if target in self.nom.votes and target not in self.nom.finalized:
                    self.nom.finalized.add(target)
                    continue
                if target != self.nom.nominee_id and can_vote(tps):
                    break

        await self._refresh_ui()
        label = "Guilty" if guilty else "Not Guilty"
        await interaction.response.send_message(f"You voted **{label}**. Click the other button to change your vote.", ephemeral=True)

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
            tps = gs.players.get(target)
            if target in self.nom.votes and target not in self.nom.finalized:
                self.nom.finalized.add(target)
                continue
            if target != self.nom.nominee_id and can_vote(tps):
                break
        await self._refresh_ui()
        await interaction.response.defer()

    async def _back_clock(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Only the Storyteller can move the clock.", ephemeral=True)
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
        await self._refresh_ui()
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

    @discord.ui.button(label="🔒 Close Voting", style=discord.ButtonStyle.danger, row=1)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Only the Storyteller can close voting.", ephemeral=True)
        await self._close()
        await interaction.response.send_message("🔒 Voting closed.", ephemeral=True)


# ── Cog ──────────────────────────────────────────────────────────────────────

class BOTCGame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GameState] = _load_state()
        self._messages: dict[tuple[int, int], discord.Message] = {}
        self._views: dict[tuple[int, int], VoteView] = {}
        self._tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._timeouts: dict[int, int] = {}
        self._nom_ids: dict[int, int] = {}

    def cog_unload(self):
        for t in self._tasks.values():
            t.cancel()

    def _get_state(self, guild_id: int) -> GameState:
        if guild_id not in self._states:
            self._states[guild_id] = GameState()
        return self._states[guild_id]

    def _save(self):
        _save_state(self._states)

    def _next_nom_id(self, guild_id: int) -> int:
        self._nom_ids.setdefault(guild_id, 0)
        self._nom_ids[guild_id] += 1
        return self._nom_ids[guild_id]

    async def _expire(self, guild_id: int, nom_id: int, view: VoteView):
        remaining = view.nom.expires_at - time.time()
        if remaining > 0:
            await asyncio.sleep(remaining)
        await view._close()
        key = (guild_id, nom_id)
        msg = self._messages.get(key)
        if msg:
            await msg.channel.send(f"⏰ Nomination #{nom_id} expired. Final tally above.")
        self._messages.pop(key, None)
        self._views.pop(key, None)
        self._tasks.pop(key, None)

    # ── Neighbor Threads ────────────────────────────────────────────────────

    def _get_alive_members(self, guild: discord.Guild, gs: GameState) -> list[discord.Member]:
        out = []
        for uid in gs.seating_order:
            ps = gs.players.get(uid)
            if not ps or not ps.dead:
                m = guild.get_member(uid)
                if m:
                    out.append(m)
        return out

    def _neighbor_pair_names(self, guild: discord.Guild, gs: GameState) -> list[str]:
        alive = self._get_alive_members(guild, gs)
        return [
            f"{alive[i].display_name}-{alive[(i + 1) % len(alive)].display_name}"
            for i in range(len(alive))
        ]

    async def _create_neighbor_threads(self, ctx: commands.Context, gs: GameState):
        alive = self._get_alive_members(ctx.guild, gs)
        if len(alive) < 2:
            return
        channel = discord.utils.get(ctx.guild.text_channels, name="🌞daytime-chat")
        if not channel:
            await ctx.send("No channel named `🌞daytime-chat` found. Reply `yes` to create threads in this channel instead.")
            try:
                r = await self.bot.wait_for("message", timeout=30,
                    check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
            except asyncio.TimeoutError:
                return await ctx.send("Cancelled (timeout).")
            if r.content.lower() != "yes":
                return await ctx.send("Cancelled.")
            channel = ctx.channel
        storyteller_role = discord.utils.get(ctx.guild.roles, name="Storyteller")
        storytellers = storyteller_role.members if storyteller_role else [ctx.author]
        created = 0
        for i in range(len(alive)):
            p1 = alive[i]
            p2 = alive[(i + 1) % len(alive)]
            try:
                thread = await channel.create_thread(
                    name=f"neighbor-{p1.display_name}-{p2.display_name}"[:100],
                    type=discord.ChannelType.private_thread,
                )
                await asyncio.sleep(0.6)
                await thread.add_user(p1)
                await asyncio.sleep(0.6)
                await thread.add_user(p2)
                await asyncio.sleep(0.6)
                for st in storytellers:
                    await thread.add_user(st)
                    await asyncio.sleep(0.6)
                st_names = ", ".join(st.display_name for st in storytellers)
                await thread.send(
                    f"{p1.mention} {p2.mention} — you are neighbors! "
                    f"Storyteller{'s' if len(storytellers) != 1 else ''}: {st_names}",
                    allowed_mentions=discord.AllowedMentions(users=[p1, p2]),
                )
                created += 1
                await asyncio.sleep(1)
            except Exception as e:
                await ctx.send(f"⚠️ Could not create thread for {p1.display_name} & {p2.display_name}: {e}")
        if created:
            await ctx.send(f"✅ Created {created} neighbor threads in {channel.mention}.")

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
        await self._create_neighbor_threads(ctx, gs)

    @commands.command(name="bseating")
    async def bseating(self, ctx: commands.Context):
        """Show the current seating order."""
        gs = self._get_state(ctx.guild.id)
        if not gs.seating_order:
            return await ctx.send("No seating order set. Use `.bsetseating @p1 @p2 ...`")
        lines = []
        for i, uid in enumerate(gs.seating_order):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"<unknown {uid}>"
            ps = gs.players.get(uid)
            tags = []
            if ps and ps.dead:
                tags.append("☠️")
            if ps and ps.sponsor_id is not None:
                sponsor_member = ctx.guild.get_member(ps.sponsor_id)
                sponsor_name = sponsor_member.display_name if sponsor_member else f"<unknown {ps.sponsor_id}>"
                tags.append(f"→ sponsor: {sponsor_name}")
            tag_str = " ".join(tags)
            tag_str = f" {tag_str}" if tag_str else ""
            lines.append(f"{i+1}. {name}{tag_str}")
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

        await ctx.send(f"☠️ Kill {target.display_name}? Reply `yes` to confirm.")
        try:
            r = await self.bot.wait_for("message", timeout=30,
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
        except asyncio.TimeoutError:
            return await ctx.send("Cancelled (timeout).")
        if r.content.lower() != "yes":
            return await ctx.send("Cancelled.")

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
    async def bsponsor(self, ctx: commands.Context, player: discord.Member, sponsor: discord.Member):
        """Assign a sponsor to a player. Usage: .bsponsor @player @sponsor"""
        gs = self._get_state(ctx.guild.id)
        ps = gs.players.get(player.id)
        if not ps:
            return await ctx.send("Player not found in seating order.")
        ps.sponsor_id = sponsor.id
        self._save()
        await ctx.send(f"⭐ {sponsor.display_name} is now the sponsor for {player.display_name}.")

    @commands.command(name="bunsponsor")
    @commands.has_permissions(administrator=True)
    async def bunsponsor(self, ctx: commands.Context, *, target: discord.Member):
        """Remove the sponsor from a player."""
        gs = self._get_state(ctx.guild.id)
        ps = gs.players.get(target.id)
        if not ps:
            return await ctx.send("Player not found in seating order.")
        ps.sponsor_id = None
        self._save()
        await ctx.send(f"✅ Sponsor removed from {target.display_name}.")

    # ── Dead List ────────────────────────────────────────────────────────────

    @commands.command(name="bdead")
    async def bdead(self, ctx: commands.Context):
        """Show the list of dead players."""
        gs = self._get_state(ctx.guild.id)
        dead = [(uid, gs.players[uid]) for uid in gs.seating_order if uid in gs.players and gs.players[uid].dead]
        if not dead:
            return await ctx.send("☠️ No dead players.")
        lines = []
        for uid, ps in dead:
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"<unknown {uid}>"
            lines.append(f"☠️ {name} {'🗳️(dead vote)' if ps.has_dead_vote else ''}")
        await ctx.send("\n".join(lines))

    # ── Nomination ───────────────────────────────────────────────────────────

    def _get_nomination(self, guild_id: int, nom_id: int) -> VoteView | None:
        return self._views.get((guild_id, nom_id))

    def _list_nominations(self, guild_id: int) -> list[tuple[int, Nomination]]:
        out = []
        for (gid, nid), view in self._views.items():
            if gid == guild_id:
                out.append((nid, view.nom))
        return sorted(out, key=lambda x: x[0])

    @commands.command(name="bnominate")
    @commands.has_permissions(administrator=True)
    async def bnominate(self, ctx: commands.Context, nominator: discord.Member, *, target: discord.Member):
        """Nominate a player. Usage: .bnominate @nominator @nominee"""
        if nominator == target:
            return await ctx.send("The nominator and nominee cannot be the same.")
        gs = self._get_state(ctx.guild.id)
        if target.id not in gs.seating_order:
            return await ctx.send("Target is not in the seating order.")
        if nominator.id not in gs.seating_order:
            return await ctx.send("Nominator is not in the seating order.")

        nom_id = self._next_nom_id(ctx.guild.id)
        timeout = self._timeouts.get(ctx.guild.id, 0)
        nom = Nomination(
            id=nom_id,
            nominator_id=nominator.id,
            nominee_id=target.id,
            expires_at=time.time() + timeout if timeout else 0,
        )
        view = VoteView(self, ctx.guild.id, nom, timeout)
        view._refresh_alive_info(ctx.guild)
        msg = await ctx.send(embed=view._build_embed(), view=view)
        key = (ctx.guild.id, nom_id)
        self._messages[key] = msg
        self._views[key] = view
        if timeout:
            self._tasks[key] = asyncio.create_task(self._expire(ctx.guild.id, nom_id, view))
        await ctx.send(f"✅ Nomination #{nom_id} created. Use `.baccuse {nom_id}` to set the accusation.")

    @commands.command(name="baccuse")
    @commands.has_permissions(administrator=True)
    async def baccuse(self, ctx: commands.Context, nom_id: int, *, text: str = ""):
        """Set accusation for a nomination. Omit text to enter pending mode. Usage: .baccuse <nom_id> [text]"""
        view = self._get_nomination(ctx.guild.id, nom_id)
        if not view or view.nom.closed:
            return await ctx.send(f"No active nomination #{nom_id}.")
        if text:
            view.nom.accusation = text
            view.nom.accusation_pending = False
            await view._refresh_ui()
            await ctx.send(f"✅ Accusation set for #{nom_id}.")
            return
        if view.nom.accusation_pending:
            return await ctx.send(f"Nomination #{nom_id} is already awaiting accusation.")
        for (gid, nid), v in self._views.items():
            if gid == ctx.guild.id and nid != nom_id:
                v.nom.accusation_pending = False
        view.nom.accusation_pending = True
        await view._refresh_ui()
        await ctx.send(f"✏️ Awaiting accusation for #{nom_id} from the nominator or a Storyteller.")

    @commands.command(name="bdefend")
    @commands.has_permissions(administrator=True)
    async def bdefend(self, ctx: commands.Context, nom_id: int, *, text: str = ""):
        """Set defense for a nomination. Omit text to enter pending mode. Usage: .bdefend <nom_id> [text]"""
        view = self._get_nomination(ctx.guild.id, nom_id)
        if not view or view.nom.closed:
            return await ctx.send(f"No active nomination #{nom_id}.")
        if text:
            view.nom.defense = text
            view.nom.defense_pending = False
            await view._refresh_ui()
            await ctx.send(f"✅ Defense set for #{nom_id}.")
            return
        if view.nom.defense_pending:
            return await ctx.send(f"Nomination #{nom_id} is already awaiting defense.")
        for (gid, nid), v in self._views.items():
            if gid == ctx.guild.id and nid != nom_id:
                v.nom.defense_pending = False
        view.nom.defense_pending = True
        await view._refresh_ui()
        await ctx.send(f"✏️ Awaiting defense for #{nom_id} from the nominee or a Storyteller.")

    @commands.command(name="beditaccuse")
    @commands.has_permissions(administrator=True)
    async def beditaccuse(self, ctx: commands.Context, nom_id: int, *, text: str = ""):
        """Replace accusation. Provide text directly or omit to re-enter pending mode. Usage: .beditaccuse <nom_id> [text]"""
        view = self._get_nomination(ctx.guild.id, nom_id)
        if not view or view.nom.closed:
            return await ctx.send(f"No active nomination #{nom_id}.")
        if text:
            view.nom.accusation = text
            view.nom.accusation_pending = False
            await view._refresh_ui()
            await ctx.send(f"✅ Accusation replaced for #{nom_id}.")
            return
        for (gid, nid), v in self._views.items():
            if gid == ctx.guild.id and nid != nom_id:
                v.nom.accusation_pending = False
        view.nom.accusation_pending = True
        view.nom.accusation = "No accusation."
        await view._refresh_ui()
        await ctx.send(f"✏️ Awaiting replacement accusation for #{nom_id} from the nominator or a Storyteller.")

    @commands.command(name="beditdefend")
    @commands.has_permissions(administrator=True)
    async def beditdefend(self, ctx: commands.Context, nom_id: int, *, text: str = ""):
        """Replace defense. Provide text directly or omit to re-enter pending mode. Usage: .beditdefend <nom_id> [text]"""
        view = self._get_nomination(ctx.guild.id, nom_id)
        if not view or view.nom.closed:
            return await ctx.send(f"No active nomination #{nom_id}.")
        if text:
            view.nom.defense = text
            view.nom.defense_pending = False
            await view._refresh_ui()
            await ctx.send(f"✅ Defense replaced for #{nom_id}.")
            return
        for (gid, nid), v in self._views.items():
            if gid == ctx.guild.id and nid != nom_id:
                v.nom.defense_pending = False
        view.nom.defense_pending = True
        view.nom.defense = "No defense."
        await view._refresh_ui()
        await ctx.send(f"✏️ Awaiting replacement defense for #{nom_id} from the nominee or a Storyteller.")

    @commands.command(name="bnomtimeout")
    @commands.has_permissions(administrator=True)
    async def bnomtimeout(self, ctx: commands.Context, minutes: int):
        """Set the nomination expiry timeout for this server."""
        if minutes < 1:
            return await ctx.send("Minimum timeout is 1 minute.")
        self._timeouts[ctx.guild.id] = minutes * 60
        await ctx.send(f"⏱️ Nomination timeout set to {minutes} minute(s).")

    @commands.command(name="bclose")
    @commands.has_permissions(administrator=True)
    async def bclose(self, ctx: commands.Context, nom_id: int):
        """Close a nomination early. Usage: .bclose <nom_id>"""
        view = self._get_nomination(ctx.guild.id, nom_id)
        if not view or view.nom.closed:
            await ctx.send(f"No active nomination #{nom_id} to close.")
            return
        await view._close()
        await ctx.send(f"🔒 Nomination #{nom_id} closed.")

    @commands.command(name="bnoms")
    async def bnoms(self, ctx: commands.Context, nom_id: int | None = None):
        """Show nomination status. Usage: .bnoms [nom_id] (lists all if no id given)"""
        if nom_id is not None:
            view = self._get_nomination(ctx.guild.id, nom_id)
            if not view or view.nom.closed:
                await ctx.send(f"No active nomination #{nom_id}.")
                return
            view._refresh_alive_info(ctx.guild)
            await ctx.send(embed=view._build_embed())
            return

        noms = self._list_nominations(ctx.guild.id)
        active = [(nid, nom) for nid, nom in noms if not nom.closed]
        if not active:
            await ctx.send("No active nominations.")
            return
        lines = []
        for nid, nom in active:
            acc = "✏️" if nom.accusation_pending else "✅" if nom.accusation != "No accusation." else "—"
            deff = "✏️" if nom.defense_pending else "✅" if nom.defense != "No defense." else "—"
            nom_user = self.bot.get_user(nom.nominator_id)
            nom_name = nom_user.display_name if nom_user else str(nom.nominator_id)
            nee_user = self.bot.get_user(nom.nominee_id)
            nee_name = nee_user.display_name if nee_user else str(nom.nominee_id)
            votes = len(nom.votes)
            lines.append(f"`#{nid}` {nom_name} → {nee_name}  |  🗳️{votes}  |  Acc:{acc}  Def:{deff}")
        await ctx.send("\n".join(lines))

    @commands.command(name="bvote")
    @commands.has_permissions(administrator=True)
    async def bvote(self, ctx: commands.Context, nom_id: int, player: discord.Member, guilty: str):
        """Set or change a player's vote. Usage: .bvote <nom_id> @player guilty/notguilty"""
        view = self._get_nomination(ctx.guild.id, nom_id)
        if not view or view.nom.closed:
            await ctx.send(f"No active nomination #{nom_id}.")
            return
        if guilty.lower() not in ("guilty", "notguilty"):
            await ctx.send("Vote must be `guilty` or `notguilty`.")
            return
        val = guilty.lower() == "guilty"
        view.nom.votes[player.id] = val
        if player.id in view.nom.finalized:
            pass  # keep finalized status
        view._refresh_alive_info(ctx.guild)
        await view._refresh_ui()
        await ctx.send(f"✅ Vote set for {player.display_name}: **{guilty.capitalize()}**")

    def _is_command(self, message: discord.Message) -> bool:
        prefix = self.bot.command_prefix
        if callable(prefix):
            return False  # can't check callable prefixes without context
        return message.content.startswith(prefix)

    # ── Message Listener ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is None:
            return

        for (gid, nid), view in list(self._views.items()):
            if gid != message.guild.id:
                continue
            nom = view.nom
            if nom.closed:
                continue
            msg = self._messages.get((gid, nid))
            if not msg or message.channel.id != msg.channel.id:
                continue

            if nom.accusation_pending:
                if self._is_command(message):
                    continue
                if message.author.id == nom.nominator_id or message.author.guild_permissions.administrator:
                    nom.accusation = message.content
                    nom.accusation_pending = False
                    await view._refresh_ui()
                    try:
                        await message.add_reaction("✅")
                    except Exception:
                        pass
                    return

            if nom.defense_pending:
                if self._is_command(message):
                    continue
                if message.author.id == nom.nominee_id or message.author.guild_permissions.administrator:
                    nom.defense = message.content
                    nom.defense_pending = False
                    await view._refresh_ui()
                    try:
                        await message.add_reaction("✅")
                    except Exception:
                        pass
                    return


async def setup(bot: commands.Bot):
    await bot.add_cog(BOTCGame(bot))
