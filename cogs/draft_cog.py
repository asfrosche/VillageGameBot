import collections
import difflib
import discord
import json
import logging
import os
import re
import asyncio
import aiohttp
import sys
from datetime import datetime
from discord.ext import commands

logger = logging.getLogger(__name__)

# Add fifa_data parent to path so we can import fifa_data.services.*
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
for p in [
    os.path.join(BASE_DIR, "fifa_data"),          # local: .../may/fifa_data
    os.path.join(BASE_DIR, "..", "fifa_data"),     # local alternative
    "/home/container/fifa_data",                   # server path
]:
    if os.path.isdir(p):
        sys.path.insert(0, p)
        break

from fifa_data.services.simulation_service import run_simulation, TEAM_METRICS, GROUPS
from fifa_data.services.fantasy_service import FantasyService, FIFA_POSITION_MAP
from fifa_data.services.match_analytics import (
    fetch_and_cache_data, get_match_analytics, get_form_players, get_differentials,
    get_matches_for_team, get_squad_remaining, get_squad_games_played,
    get_group_standings, load_data, expand_name_variants,
)

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fifa_data", "data", "draft_data.json")
FIFA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fifa_data")

POSITIONS = ["GK", "DEF", "MID", "FWD"]
POSITION_LIMITS = {"GK": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
POSITION_EMOJIS = {"GK": "🧤", "DEF": "🛡️", "MID": "⚡", "FWD": "⚽"}

COUNTRY_LIST = [
    # Oceania
    ("Australia", "\U0001f1e6\U0001f1fa", "AUS"),
    # Asia
    ("Iran", "\U0001f1ee\U0001f1f7", "IRN"),
    ("Iraq", "\U0001f1ee\U0001f1f6", "IRQ"),
    ("Japan", "\U0001f1ef\U0001f1f5", "JPN"),
    ("Jordan", "\U0001f1ef\U0001f1f4", "JOR"),
    ("Qatar", "\U0001f1f6\U0001f1e6", "QAT"),
    ("Saudi Arabia", "\U0001f1f8\U0001f1e6", "KSA"),
    ("South Korea", "\U0001f1f0\U0001f1f7", "KOR"),
    ("Uzbekistan", "\U0001f1fa\U0001f1ff", "UZB"),
    # Africa
    ("Algeria", "\U0001f1e9\U0001f1ff", "ALG"),
    ("Cabo Verde", "\U0001f1e8\U0001f1fb", "CPV"),
    ("Congo DR", "\U0001f1e8\U0001f1e9", "COD"),
    ("Côte d'Ivoire", "\U0001f1e8\U0001f1ee", "CIV"),
    ("Egypt", "\U0001f1ea\U0001f1ec", "EGY"),
    ("Ghana", "\U0001f1ec\U0001f1ed", "GHA"),
    ("Morocco", "\U0001f1f2\U0001f1e6", "MAR"),
    ("Senegal", "\U0001f1f8\U0001f1f3", "SEN"),
    ("South Africa", "\U0001f1ff\U0001f1e6", "RSA"),
    ("Tunisia", "\U0001f1f9\U0001f1f3", "TUN"),
    # North America
    ("Canada", "\U0001f1e8\U0001f1e6", "CAN"),
    ("Curaçao", "\U0001f1e8\U0001f1fc", "CUW"),
    ("Haiti", "\U0001f1ed\U0001f1f9", "HAI"),
    ("Mexico", "\U0001f1f2\U0001f1fd", "MEX"),
    ("Panama", "\U0001f1f5\U0001f1e6", "PAN"),
    ("United States", "\U0001f1fa\U0001f1f8", "USA"),
    # South America
    ("Argentina", "\U0001f1e6\U0001f1f7", "ARG"),
    ("Brazil", "\U0001f1e7\U0001f1f7", "BRA"),
    ("Colombia", "\U0001f1e8\U0001f1f4", "COL"),
    ("Ecuador", "\U0001f1ea\U0001f1e8", "ECU"),
    ("Paraguay", "\U0001f1f5\U0001f1fe", "PAR"),
    ("Peru", "\U0001f1f5\U0001f1ea", "PER"),
    ("Uruguay", "\U0001f1fa\U0001f1fe", "URU"),
    ("Venezuela", "\U0001f1fb\U0001f1ea", "VEN"),
    # Europe
    ("Austria", "\U0001f1e6\U0001f1f9", "AUT"),
    ("Belgium", "\U0001f1e7\U0001f1ea", "BEL"),
    ("Croatia", "\U0001f1ed\U0001f1f7", "CRO"),
    ("Czech Republic", "\U0001f1e8\U0001f1ff", "CZE"),
    ("Denmark", "\U0001f1e9\U0001f1f0", "DEN"),
    ("England", "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f", "ENG"),
    ("France", "\U0001f1eb\U0001f1f7", "FRA"),
    ("Germany", "\U0001f1e9\U0001f1ea", "GER"),
    ("Italy", "\U0001f1ee\U0001f1f9", "ITA"),
    ("Netherlands", "\U0001f1f3\U0001f1f1", "NED"),
    ("Norway", "\U0001f1f3\U0001f1f4", "NOR"),
    ("Poland", "\U0001f1f5\U0001f1f1", "POL"),
    ("Portugal", "\U0001f1f5\U0001f1f9", "POR"),
    ("Serbia", "\U0001f1f7\U0001f1f8", "SRB"),
    ("Spain", "\U0001f1ea\U0001f1f8", "ESP"),
    ("Sweden", "\U0001f1f8\U0001f1ea", "SWE"),
    ("Switzerland", "\U0001f1e8\U0001f1ed", "SUI"),
    ("Turkey", "\U0001f1f9\U0001f1f7", "TUR"),
    ("Ukraine", "\U0001f1fa\U0001f1e6", "UKR"),
    ("Wales", "\U0001f3f4\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f", "WAL"),
]

CONTINENTS = [
    ("Oceania", "\U0001f30f", ["Australia"]),
    ("Asia", "\U0001f30f", [
        "Iran", "Iraq", "Japan", "Jordan", "Qatar",
        "Saudi Arabia", "South Korea", "Uzbekistan",
    ]),
    ("Africa", "\U0001f30d", [
        "Algeria", "Cabo Verde", "Congo DR", "Côte d'Ivoire",
        "Egypt", "Ghana", "Morocco", "Senegal", "South Africa", "Tunisia",
    ]),
    ("North America", "\U0001f30e", [
        "Canada", "Curaçao", "Haiti", "Mexico", "Panama", "United States",
    ]),
    ("South America", "\U0001f30e", [
        "Argentina", "Brazil", "Colombia", "Ecuador",
        "Paraguay", "Peru", "Uruguay", "Venezuela",
    ]),
    ("Europe", "\U0001f30d", [
        "Austria", "Belgium", "Croatia", "Czech Republic", "Denmark",
        "England", "France", "Germany", "Italy", "Netherlands",
        "Norway", "Poland", "Portugal", "Serbia", "Spain",
        "Sweden", "Switzerland", "Turkey", "Ukraine", "Wales",
    ]),
]

COUNTRY_CONTINENT = {}
for c_name, _, countries in CONTINENTS:
    for name in countries:
        COUNTRY_CONTINENT[name] = c_name

def empty_team():
    return {"players": [], "country_counts": {}}

COUNTRY_TO_SIM = {
    "South Korea": "Korea Republic",
    "Czech Republic": "Czechia",
    "Turkey": "Türkiye",
    "Iran": "IR Iran",
    "Cabo Verde": "Cape Verde",
}
SIM_TO_COUNTRY = {v: k for k, v in COUNTRY_TO_SIM.items()}


def country_to_sim(name):
    return COUNTRY_TO_SIM.get(name, name)


def sim_to_country(name):
    return SIM_TO_COUNTRY.get(name, name)


# ── Squad flag emojis ──────────────────────────────────────────
# Build from COUNTRY_LIST + known name variants; add 3 missing teams.
SQUAD_FLAGS = {}
for _name, _flag, _ in COUNTRY_LIST:
    SQUAD_FLAGS[_name] = _flag
    for _v in expand_name_variants(_name):
        SQUAD_FLAGS[_v] = _flag
# Three teams not in COUNTRY_LIST
SQUAD_FLAGS.setdefault("New Zealand", "\U0001f1f3\U0001f1ff")
SQUAD_FLAGS.setdefault("Bosnia and Herzegovina", "\U0001f1e7\U0001f1e6")
SQUAD_FLAGS.setdefault("Scotland", "\U0001f3f4\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f")


def _flag(name):
    return SQUAD_FLAGS.get(name, "")


def get_roster_counts(players):
    counts = {p: 0 for p in POSITIONS}
    for p in players:
        counts[p["position"]] += 1
    return counts


def get_country_counts(players):
    counts = {}
    for p in players:
        counts[p["country"]] = counts.get(p["country"], 0) + 1
    return counts


def get_remaining_slots(players):
    counts = get_roster_counts(players)
    remaining = {}
    for pos in POSITIONS:
        lo, hi = POSITION_LIMITS[pos]
        current = counts[pos]
        remaining[pos] = {"current": current, "min": lo, "max": hi, "remaining": hi - current}
    return remaining


def can_add_position(players, position):
    counts = get_roster_counts(players)
    lo, hi = POSITION_LIMITS[position]
    if counts[position] >= hi:
        return False
    new_counts = counts.copy()
    new_counts[position] += 1
    remaining_slots = 11 - len(players) - 1
    min_needed = sum(max(0, POSITION_LIMITS[p][0] - new_counts[p]) for p in POSITIONS)
    if remaining_slots < min_needed:
        return False
    for p in POSITIONS:
        if new_counts[p] + remaining_slots < POSITION_LIMITS[p][0]:
            return False
        if new_counts[p] > POSITION_LIMITS[p][1]:
            return False
    return True


def can_add_country(players, country):
    counts = get_country_counts(players)
    return counts.get(country, 0) < 2


def is_player_drafted(draft, name):
    name_lower = name.strip().lower()
    for pick in draft["pick_history"]:
        if pick["name"].strip().lower() == name_lower:
            return True
    return False


def make_roster_str(players):
    lines = []
    for pos in POSITIONS:
        pos_players = [p["name"] for p in players if p["position"] == pos]
        if pos_players:
            lines.append(f"{POSITION_EMOJIS[pos]} {pos}: {', '.join(pos_players)}")
        else:
            lines.append(f"{POSITION_EMOJIS[pos]} {pos}: --")
    return "\n".join(lines)


def make_country_counts_str(players):
    cc = get_country_counts(players)
    if not cc:
        return "None"
    return ", ".join(f"{c}: {n}/2" for c, n in sorted(cc.items()))


def make_remaining_str(players):
    slots = get_remaining_slots(players)
    return " | ".join(f"{pos} {slots[pos]['current']}/{slots[pos]['max']}" for pos in POSITIONS)


def generate_snake_order(managers):
    if not managers:
        return []
    order = []
    for rnd in range(11):
        if rnd % 2 == 0:
            order.extend(managers)
        else:
            order.extend(reversed(managers))
    return order[: len(managers) * 11]


def get_country_options(current_players, continent=None):
    options = []
    for name, flag, code in COUNTRY_LIST:
        if continent and COUNTRY_CONTINENT.get(name) != continent:
            continue
        if not can_add_country(current_players, name):
            continue
        options.append(discord.SelectOption(label=f"{flag} {code}", value=name, emoji=flag))
    return options



# ── World Cup Interactive Panel ──────────────────────────

def _standings_table(standings):
    lines = [f"`{'#':2s} {'Team':20s} {'Pld':3s} {'W':3s} {'D':3s} {'L':3s} {'GF':3s} {'GA':3s} {'GD':4s} {'Pts':3s}`"]
    for i, t in enumerate(standings, 1):
        lines.append(
            f"`{i:2d} {t['name']:20s} {t['pld']:3d} {t['w']:3d} {t['d']:3d} "
            f"{t['l']:3d} {t['gf']:3d} {t['ga']:3d} {t['gd']:+3d} {t['pts']:3d}`"
        )
    return "\n".join(lines)


def _tiebreaker_text(standings, completed):
    from collections import defaultdict
    pts_groups = defaultdict(list)
    for t in standings:
        pts_groups[t['pts']].append(t)

    lines = []
    for pts, teams in pts_groups.items():
        if len(teams) < 2:
            continue
        team_names = [t['name'] for t in teams]
        h2h = {t: {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0} for t in team_names}
        for m in completed:
            home, away = m['home']['name'], m['away']['name']
            if home in team_names and away in team_names:
                hs, aas = m['home']['score'], m['away']['score']
                h2h[home]['gf'] += hs; h2h[home]['ga'] += aas
                h2h[away]['gf'] += aas; h2h[away]['ga'] += hs
                if hs > aas:
                    h2h[home]['pts'] += 3
                elif hs == aas:
                    h2h[home]['pts'] += 1; h2h[away]['pts'] += 1
                else:
                    h2h[away]['pts'] += 3
        for t in team_names:
            h2h[t]['gd'] = h2h[t]['gf'] - h2h[t]['ga']

        sorted_h2h = sorted(team_names, key=lambda t: (-h2h[t]['pts'], -h2h[t]['gd'], -h2h[t]['gf']))
        lines.append(f"\n**Tied on {pts}pts — Head-to-Head:**")
        for t in sorted_h2h:
            lines.append(f"  {t}: {h2h[t]['pts']}pts, GD {h2h[t]['gd']:+d}, GF {h2h[t]['gf']}")

    return "\n".join(lines)


def _build_group_embed(letter):
    standings, completed, upcoming = get_group_standings(letter)
    if not standings:
        return None

    embed = discord.Embed(
        title=f"🌍 World Cup 2026 — Group {letter}",
        color=0xff3fb9,
    )
    embed.add_field(name="📊 Standings", value=_standings_table(standings), inline=False)

    tb = _tiebreaker_text(standings, completed)
    if tb:
        embed.add_field(name="⚖️ Tiebreakers", value=tb, inline=False)

    if completed:
        match_lines = []
        for m in sorted(completed, key=lambda x: x.get("date", "")):
            match_lines.append(
                f"**{m['home']['name']}** {m['home']['score']} — {m['away']['score']} **{m['away']['name']}**"
            )
        embed.add_field(name=f"✅ Results ({len(completed)})", value="\n".join(match_lines), inline=False)

    if upcoming:
        match_lines = []
        for m in upcoming:
            match_lines.append(f"**{m['home']['name']}** vs **{m['away']['name']}**")
        embed.add_field(name=f"🔜 Upcoming ({len(upcoming)})", value="\n".join(match_lines), inline=False)

    return embed


class GroupSelect(discord.ui.Select):
    def __init__(self, disabled=False):
        options = [
            discord.SelectOption(label=f"Group {l}", value=l, description=f"View standings for Group {l}")
            for l in "ABCDEFGHIJKL"
        ]
        super().__init__(placeholder="Select a group for standings + tiebreakers...", options=options, disabled=disabled)

    async def callback(self, interaction):
        await interaction.response.defer()
        letter = self.values[0]
        status = await interaction.followup.send("⏳ Fetching data...", ephemeral=True)
        try:
            await fetch_and_cache_data()
        except Exception:
            pass
        embed = _build_group_embed(letter)
        if embed is None:
            return await status.edit(content=f"No data for Group {letter}.")
        await status.delete()
        view = StandingsView(letter)
        await interaction.edit_original_response(embed=embed, view=view)


class StandingsView(discord.ui.View):
    def __init__(self, letter):
        super().__init__(timeout=300)
        self.letter = letter

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction, button):
        await interaction.response.defer()
        try:
            await fetch_and_cache_data()
        except Exception:
            pass
        embed = _build_group_embed(self.letter)
        if embed:
            await interaction.edit_original_response(embed=embed, view=self)


class GroupSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(GroupSelect())


class PlayerNameModal(discord.ui.Modal, title="Enter Player Name"):
    name_input = discord.ui.TextInput(
        label="Player Name",
        placeholder="Enter the player's full name",
        required=True,
        max_length=100,
    )

    def __init__(self, cog, guild_id, owner_id, position, country, country_flag):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.position = position
        self.country = country
        self.country_flag = country_flag

    async def on_submit(self, interaction: discord.Interaction):
        player_name = self.name_input.value.strip()
        if not player_name:
            return await interaction.response.send_message("Player name cannot be empty.", ephemeral=True)

        draft = self.cog._get_draft(self.guild_id)
        if draft is None:
            return await interaction.response.send_message("Draft no longer active.", ephemeral=True)

        if draft.get("paused") or draft.get("ended"):
            return await interaction.response.send_message("Draft is paused or ended.", ephemeral=True)

        if self.owner_id != get_current_owner(draft):
            return await interaction.response.send_message("Not your turn anymore.", ephemeral=True)

        team = draft["teams"].get(str(self.owner_id), empty_team())

        if not can_add_position(team["players"], self.position):
            return await interaction.response.send_message(f"Position {self.position} is no longer available.", ephemeral=True)
        if not can_add_country(team["players"], self.country):
            return await interaction.response.send_message(f"Country limit (2) reached for {self.country}.", ephemeral=True)
        if is_player_drafted(draft, player_name):
            return await interaction.response.send_message(f"'{player_name}' is already drafted.", ephemeral=True)

        pick = await self.cog._execute_pick(self.guild_id, self.owner_id, self.position, self.country, player_name)
        if pick is None:
            return await interaction.response.send_message("Something went wrong.", ephemeral=True)

        guild = self.cog.bot.get_guild(int(self.guild_id))
        guild_ch = guild.get_channel(draft.get("channel_id")) if guild else None
        if guild_ch is None and guild:
            guild_ch = guild.get_channel_or_thread(draft.get("channel_id"))

        if guild_ch:
            turn_msg_id = draft.get("turn_message_id")
            if turn_msg_id:
                try:
                    turn_msg = await guild_ch.fetch_message(turn_msg_id)
                    await turn_msg.edit(content=None, embed=discord.Embed(
                        title=f"✅ Pick #{pick['pick_number']} Complete",
                        description=f"{interaction.user.mention} picked **{player_name}**",
                        color=0x00ff00
                    ), view=None)
                except Exception:
                    pass

        announce_embed = discord.Embed(
            title=f"✅ Pick #{pick['pick_number']}",
            description=f"{interaction.user.mention} selects",
            color=0x00ff00,
        )
        announce_embed.add_field(name="Player", value=f"**{player_name}**", inline=True)
        announce_embed.add_field(name="Country", value=f"{self.country_flag} {self.country}", inline=True)
        announce_embed.add_field(name="Position", value=f"{POSITION_EMOJIS[self.position]} {self.position}", inline=True)

        try:
            await interaction.response.send_message(embed=announce_embed)
        except discord.InteractionResponded:
            await interaction.followup.send(embed=announce_embed)

        try:
            await self.cog._advance_after_pick(self.guild_id, guild_ch, guild)
        except Exception as e:
            logger.exception("on_submit: _advance_after_pick failed — %s", e)


class CountrySelect(discord.ui.Select):
    def __init__(self, cog, guild_id, owner_id, position, continent=None):
        draft = cog._get_draft(guild_id)
        team = draft["teams"].get(str(owner_id), {"players": [], "country_counts": {}})
        options = get_country_options(team["players"], continent=continent)
        if not options:
            options = [discord.SelectOption(label="No countries available", value="__none__", default=True)]
        super().__init__(placeholder="Select country...", options=options, row=0)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.position = position

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Not your turn.", ephemeral=True)
        country = self.values[0]
        if country == "__none__":
            return
        flag = ""
        for name, f, _ in COUNTRY_LIST:
            if name == country:
                flag = f
                break
        modal = PlayerNameModal(self.cog, self.guild_id, self.owner_id, self.position, country, flag)
        await interaction.response.send_modal(modal)


class ContinentSelect(discord.ui.Select):
    def __init__(self, cog, guild_id, owner_id, position):
        draft = cog._get_draft(guild_id)
        team = draft["teams"].get(str(owner_id), {"players": [], "country_counts": {}})
        available = []
        for c_name, emoji, countries in CONTINENTS:
            for name in countries:
                if can_add_country(team["players"], name):
                    available.append((c_name, emoji))
                    break
        options = [
            discord.SelectOption(label=f"{emoji} {c_name}", value=c_name, emoji=emoji)
            for c_name, emoji in available
        ]
        if not options:
            options = [discord.SelectOption(label="No continents available", value="__none__")]
        super().__init__(placeholder="Select continent...", options=options, row=0)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.position = position

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Not your turn.", ephemeral=True)
        continent = self.values[0]
        if continent == "__none__":
            return
        country_select = CountrySelect(self.cog, self.guild_id, self.owner_id, self.position, continent=continent)
        view = CountrySelectView(self.cog, self.guild_id, self.owner_id, self.position, continent_select=country_select)
        embed = discord.Embed(
            title=f"Select Country ({continent})",
            color=0xff3fb9,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class CountrySelectView(discord.ui.View):
    def __init__(self, cog, guild_id, owner_id, position, continent_select=None):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.position = position
        if continent_select:
            self.add_item(continent_select)
            back = discord.ui.Button(label="◀ Back to continents", style=discord.ButtonStyle.secondary, row=1)
            back.callback = self._back_callback
            self.add_item(back)
        else:
            self.add_item(ContinentSelect(cog, guild_id, owner_id, position))

    async def _back_callback(self, interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Not your turn.", ephemeral=True)
        view = CountrySelectView(self.cog, self.guild_id, self.owner_id, self.position)
        embed = discord.Embed(title="Select Continent", color=0xff3fb9)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        draft = self.cog._get_draft(self.guild_id)
        if draft and not draft.get("ended"):
            self.cog._start_timer(self.guild_id)
            ch = self.cog.bot.get_channel(draft.get("channel_id"))
            if ch is None:
                ch = self.cog.bot.get_channel_or_thread(draft.get("channel_id"))
            if ch:
                try:
                    msg = await ch.fetch_message(draft.get("turn_message_id"))
                    await msg.edit(view=None)
                except Exception:
                    pass

    async def on_error(self, interaction, error, item):
        logger.warning("CountrySelectView error: %s", error)


class PositionButtons(discord.ui.View):
    def __init__(self, cog, guild_id, owner_id):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id

        draft = cog._get_draft(guild_id)
        team = draft["teams"].get(str(owner_id), {"players": [], "country_counts": {}})
        players = team["players"]

        for pos in POSITIONS:
            can = can_add_position(players, pos)
            label = f"{POSITION_EMOJIS[pos]} {pos}"
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, disabled=not can, row=0)
            btn.callback = self._make_callback(pos)
            self.add_item(btn)

        prepicks = draft.get("prepicks", {}).get(str(owner_id), [])
        has_valid = False
        for pp in prepicks:
            if can_add_position(players, pp["position"]) and can_add_country(players, pp["country"]) and not is_player_drafted(draft, pp["player_name"]):
                has_valid = True
                break
        if has_valid:
            btn = discord.ui.Button(label="⏩ Prepick", style=discord.ButtonStyle.success, row=1)
            btn.callback = self._prepick_callback
            self.add_item(btn)

    async def _prepick_callback(self, interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Not your turn.", ephemeral=True)
        draft = self.cog._get_draft(self.guild_id)
        if draft.get("paused") or draft.get("ended"):
            return await interaction.response.send_message("Draft is paused or ended.", ephemeral=True)
        if self.owner_id != get_current_owner(draft):
            return await interaction.response.send_message("Not your turn anymore.", ephemeral=True)

        prepicks = draft.get("prepicks", {}).get(str(self.owner_id), [])
        team = draft["teams"].get(str(self.owner_id), empty_team())

        for pp in prepicks:
            if not can_add_position(team["players"], pp["position"]):
                continue
            if not can_add_country(team["players"], pp["country"]):
                continue
            if is_player_drafted(draft, pp["player_name"]):
                continue

            pick = await self.cog._execute_pick(self.guild_id, self.owner_id, pp["position"], pp["country"], pp["player_name"])
            if pick:
                await interaction.response.send_message(f"✅ Prepick used: **{pp['player_name']}** ({POSITION_EMOJIS[pp['position']]} {pp['position']})", ephemeral=True)
                channel = interaction.channel
                guild = interaction.guild
                await self.cog._advance_after_pick(self.guild_id, channel, guild)
                return

        await interaction.response.send_message("No valid prepicks available.", ephemeral=True)

    def _make_callback(self, position):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message("Not your turn.", ephemeral=True)
            draft = self.cog._get_draft(self.guild_id)
            if draft.get("paused") or draft.get("ended"):
                return await interaction.response.send_message("Draft is paused or ended.", ephemeral=True)
            if self.owner_id != get_current_owner(draft):
                return await interaction.response.send_message("Not your turn anymore.", ephemeral=True)

            self.cog._cancel_timer(self.guild_id)

            team = draft["teams"].get(str(self.owner_id), empty_team())
            if not can_add_position(team["players"], position):
                return await interaction.response.send_message(f"Position {position} is no longer available.", ephemeral=True)

            view = CountrySelectView(self.cog, self.guild_id, self.owner_id, position)
            embed = discord.Embed(
                title=f"Select Country for {POSITION_EMOJIS[position]} {position}",
                color=0xff3fb9,
            )
            await interaction.response.edit_message(embed=embed, view=view)
        return callback

    async def on_error(self, interaction, error, item):
        logger.warning("PositionButtons error: %s", error)


class PrepickManageView(discord.ui.View):
    def __init__(self, cog, guild_id, owner_id):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id

        draft = cog._get_draft(guild_id)
        prepicks = draft.get("prepicks", {}).get(str(owner_id), [])

        embed_desc = []
        for i, pp in enumerate(prepicks, 1):
            embed_desc.append(f"**Prepicks #{i}:** {POSITION_EMOJIS[pp['position']]} {pp['position']} | {pp['country']} | {pp['player_name']}")

        if not embed_desc:
            embed_desc.append("No prepicks set.")

        self.embed = discord.Embed(
            title="📋 Your Prepicks",
            description="\n".join(embed_desc),
            color=0xff3fb9,
        )
        self.embed.set_footer(text="Prepicks are used when your turn timer expires (max 2).")

        if len(prepicks) < 2:
            btn = discord.ui.Button(label="Add Prepick", style=discord.ButtonStyle.success, emoji="➕", row=0)
            btn.callback = self._add_callback
            self.add_item(btn)

        for i in range(len(prepicks)):
            btn = discord.ui.Button(label=f"Clear Prepick #{i+1}", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
            btn.callback = self._make_clear_callback(i)
            self.add_item(btn)

    async def _add_callback(self, interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Not your prepicks.", ephemeral=True)
        view = PrepickPositionView(self.cog, self.guild_id, self.owner_id)
        embed = discord.Embed(title="Select position for prepick", color=0xff3fb9)
        await interaction.response.edit_message(embed=embed, view=view)

    def _make_clear_callback(self, index):
        async def callback(interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message("Not your prepicks.", ephemeral=True)
            draft = self.cog._get_draft(self.guild_id)
            user_prepicks = draft.setdefault("prepicks", {}).setdefault(str(self.owner_id), [])
            if index < len(user_prepicks):
                user_prepicks.pop(index)
            self.cog._save()
            await interaction.response.edit_message(
                content="Prepick cleared.", embed=None, view=None
            )
        return callback

    async def on_error(self, interaction, error, item):
        logger.warning("PrepickManageView error: %s", error)


class PrepickCountrySelect(discord.ui.Select):
    def __init__(self, cog, guild_id, owner_id, position, continent=None):
        draft = cog._get_draft(guild_id)
        team = draft["teams"].get(str(owner_id), {"players": [], "country_counts": {}})
        options = get_country_options(team["players"], continent=continent)
        if not options:
            options = [discord.SelectOption(label="No countries available", value="__none__")]
        super().__init__(placeholder="Select country...", options=options, row=0)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.position = position

    async def callback(self, interaction):
        if interaction.user.id != self.owner_id:
            return
        country = self.values[0]
        if country == "__none__":
            return
        flag = ""
        for name, f, _ in COUNTRY_LIST:
            if name == country:
                flag = f
                break
        modal = PrepickNameModal(self.cog, self.guild_id, self.owner_id, self.position, country, flag)
        await interaction.response.send_modal(modal)


class PrepickContinentSelect(discord.ui.Select):
    def __init__(self, cog, guild_id, owner_id, position):
        draft = cog._get_draft(guild_id)
        team = draft["teams"].get(str(owner_id), {"players": [], "country_counts": {}})
        available = []
        for c_name, emoji, countries in CONTINENTS:
            for name in countries:
                if can_add_country(team["players"], name):
                    available.append((c_name, emoji))
                    break
        options = [
            discord.SelectOption(label=f"{emoji} {c_name}", value=c_name, emoji=emoji)
            for c_name, emoji in available
        ]
        if not options:
            options = [discord.SelectOption(label="No continents available", value="__none__")]
        super().__init__(placeholder="Select continent...", options=options, row=0)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.position = position

    async def callback(self, interaction):
        if interaction.user.id != self.owner_id:
            return
        continent = self.values[0]
        if continent == "__none__":
            return
        view = discord.ui.View()
        view.add_item(PrepickCountrySelect(self.cog, self.guild_id, self.owner_id, self.position, continent=continent))
        back = discord.ui.Button(label="◀ Back to continents", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._make_back_callback()
        view.add_item(back)
        embed = discord.Embed(
            title=f"Select Country for Prepick ({continent})",
            color=0xff3fb9,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    def _make_back_callback(self):
        async def cb(interaction):
            if interaction.user.id != self.owner_id:
                return
            view = discord.ui.View()
            view.add_item(PrepickContinentSelect(self.cog, self.guild_id, self.owner_id, self.position))
            embed = discord.Embed(
                title=f"Select Continent for Prepick ({POSITION_EMOJIS[self.position]} {self.position})",
                color=0xff3fb9,
            )
            await interaction.response.edit_message(embed=embed, view=view)
        return cb


class PrepickPositionView(discord.ui.View):
    def __init__(self, cog, guild_id, owner_id):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id

        draft = cog._get_draft(guild_id)
        team = draft["teams"].get(str(owner_id), {"players": [], "country_counts": {}})

        for pos in POSITIONS:
            can = can_add_position(team["players"], pos)
            btn = discord.ui.Button(
                label=f"{POSITION_EMOJIS[pos]} {pos}",
                style=discord.ButtonStyle.primary,
                disabled=not can,
                row=0,
            )
            btn.callback = self._make_callback(pos)
            self.add_item(btn)

    def _make_callback(self, position):
        async def callback(interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message("Not yours.", ephemeral=True)
            view = discord.ui.View()
            view.add_item(PrepickContinentSelect(self.cog, self.guild_id, self.owner_id, position))
            embed = discord.Embed(
                title=f"Select Continent for Prepick ({POSITION_EMOJIS[position]} {position})",
                color=0xff3fb9,
            )
            await interaction.response.edit_message(embed=embed, view=view)
        return callback


class PrepickNameModal(discord.ui.Modal, title="Prepick Player Name"):
    name_input = discord.ui.TextInput(
        label="Player Name",
        placeholder="Enter the player's full name",
        required=True,
        max_length=100,
    )

    def __init__(self, cog, guild_id, owner_id, position, country, flag):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.position = position
        self.country = country
        self.flag = flag

    async def on_submit(self, interaction):
        player_name = self.name_input.value.strip()
        if not player_name:
            return await interaction.response.send_message("Name cannot be empty.", ephemeral=True)

        draft = self.cog._get_draft(self.guild_id)
        prepicks = draft.setdefault("prepicks", {}).setdefault(str(self.owner_id), [])

        if len(prepicks) >= 2:
            return await interaction.response.send_message("Max 2 prepicks.", ephemeral=True)

        team = draft["teams"].get(str(self.owner_id), empty_team())
        if not can_add_position(team["players"], self.position):
            return await interaction.response.send_message(f"Position {self.position} is no longer available.", ephemeral=True)

        prepicks.append({
            "position": self.position,
            "country": self.country,
            "player_name": player_name,
        })
        self.cog._save()

        embed = discord.Embed(
            title="✅ Prepick Saved",
            description=f"{POSITION_EMOJIS[self.position]} {self.position} | {self.flag} {self.country} | **{player_name}**",
            color=0x00ff00,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def get_current_owner(draft):
    if draft["current_index"] < len(draft["snake_order"]):
        return draft["snake_order"][draft["current_index"]]
    return None


def get_next_owners(draft, count=2):
    owners = []
    idx = draft["current_index"] + 1
    while len(owners) < count and idx < len(draft["snake_order"]):
        owners.append(draft["snake_order"][idx])
        idx += 1
    return owners


class ForcePickNameModal(discord.ui.Modal, title="Force Pick — Player Name"):
    name_input = discord.ui.TextInput(
        label="Player Name",
        placeholder="Enter the player's full name",
        required=True,
        max_length=100,
    )

    def __init__(self, cog, ctx, draft, owner_id, team, valid):
        super().__init__()
        self.cog = cog
        self.ctx = ctx
        self.draft = draft
        self.owner_id = owner_id
        self.team = team
        self.valid = valid

    async def on_submit(self, interaction):
        player_name = self.name_input.value.strip()
        if not player_name:
            return await interaction.response.send_message("Name cannot be empty.", ephemeral=True)
        if is_player_drafted(self.draft, player_name):
            return await interaction.response.send_message(f"'{player_name}' is already drafted.", ephemeral=True)

        await interaction.response.defer()
        await self.cog._show_forcepick_view(self.ctx, self.draft, self.owner_id, self.team, self.valid, player_name)


class DraftCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data = {}
        self.timers = {}
        self._fantasy_cache = None
        self._fantasy_cache_time = 0
        self.fantasy = FantasyService()
        self._api_lock = asyncio.Lock()
        self._load()

    def _load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Corrupt draft data file: %s — resetting", e)
                backup = DATA_FILE + ".bak"
                try:
                    if os.path.exists(DATA_FILE):
                        os.replace(DATA_FILE, backup)
                        logger.info("Backed up corrupt file to %s", backup)
                except OSError:
                    pass
                self.data = {}
        else:
            self.data = {}
        for draft in self.data.values():
            if draft.get("started") and not draft.get("ended"):
                draft["paused"] = True
                draft["turn_message_id"] = None

    def _save(self):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, DATA_FILE)

    def _get_draft(self, guild_id):
        return self.data.get(str(guild_id))

    async def _cleanup_turn_message(self, guild_id):
        draft = self._get_draft(guild_id)
        if draft is None:
            return
        msg_id = draft.get("turn_message_id")
        if msg_id:
            ch = self.bot.get_channel(draft.get("channel_id"))
            if ch is None:
                ch = self.bot.get_channel_or_thread(draft.get("channel_id"))
            if ch:
                try:
                    msg = await ch.fetch_message(msg_id)
                    await msg.edit(view=None)
                except (discord.NotFound, discord.Forbidden):
                    pass
                except Exception as e:
                    logger.warning("cleanup_turn_message: %s", e)
            draft["turn_message_id"] = None
            self._save()

    def _cancel_timer(self, guild_id):
        task = self.timers.pop(str(guild_id), None)
        if task and not task.done():
            task.cancel()

    async def _timer_task(self, guild_id):
        try:
            await asyncio.sleep(600)
        except asyncio.CancelledError:
            return

        draft = self._get_draft(guild_id)
        if draft is None or draft.get("paused") or draft.get("ended"):
            return

        owner_id = get_current_owner(draft)
        if owner_id is None:
            return

        channel = self.bot.get_channel(draft.get("channel_id"))
        if channel is None:
            channel = self.bot.get_channel_or_thread(draft.get("channel_id"))
        if channel is None:
            return

        draft = self._get_draft(guild_id)
        if draft is None or draft.get("paused") or draft.get("ended"):
            return
        if get_current_owner(draft) != owner_id:
            return

        try:
            await channel.send(f"⏰ <@{owner_id}> you've been on the clock for 10 minutes. Please make your pick!")
        except (discord.Forbidden, discord.NotFound):
            pass

    def _start_timer(self, guild_id):
        self._cancel_timer(guild_id)
        self.timers[str(guild_id)] = asyncio.create_task(self._timer_task(guild_id))

    async def _execute_pick(self, guild_id, owner_id, position, country, player_name):
        draft = self._get_draft(guild_id)
        if draft is None:
            return None

        team = draft["teams"].setdefault(str(owner_id), empty_team())

        pick_number = len(draft["pick_history"]) + 1
        pick = {
            "name": player_name,
            "country": country,
            "position": position,
            "owner": owner_id,
            "pick_number": pick_number,
        }

        team["players"].append(pick)
        team["country_counts"] = get_country_counts(team["players"])
        draft["pick_history"].append(pick.copy())
        draft["current_index"] += 1
        self._save()

        return pick

    async def _advance_after_pick(self, guild_id, channel=None, guild=None):
        draft = self._get_draft(guild_id)
        if draft is None:
            return

        if guild is None or channel is None:
            guild = self.bot.get_guild(int(guild_id))
            if guild:
                channel = guild.get_channel(draft.get("channel_id"))
                if channel is None:
                    channel = guild.get_channel_or_thread(draft.get("channel_id"))
        if guild is None or channel is None:
            logger.warning("_advance_after_pick: guild=%s channel=%s — pausing", guild, channel)
            draft["paused"] = True
            self._save()
            return

        total_managers = len(draft["managers"])
        if len(draft["pick_history"]) >= total_managers * 11:
            await self._end_draft(guild_id, channel, guild)
            return

        try:
            await self._update_status(guild_id, channel, guild)
            await self._send_turn(guild_id, channel, guild)
        except (discord.Forbidden, discord.NotFound) as e:
            logger.warning("_advance_after_pick: Forbidden/NotFound — %s", e)
            draft["paused"] = True
            self._save()
        except Exception as e:
            logger.exception("_advance_after_pick: unexpected error — %s", e)
            draft["paused"] = True
            self._save()

    async def _send_turn(self, guild_id, channel, guild):
        draft = self._get_draft(guild_id)
        if draft is None or draft.get("ended") or draft.get("paused"):
            return

        owner_id = get_current_owner(draft)
        if owner_id is None:
            return

        member = guild.get_member(owner_id)
        mention = member.mention if member else f"<@{owner_id}>"

        next_owners = get_next_owners(draft)
        next_str = ", ".join(
            f"<@{uid}>" if guild.get_member(uid) else f"<@{uid}>"
            for uid in next_owners
        )

        team = draft["teams"].get(str(owner_id), {"players": [], "country_counts": {}})

        embed = discord.Embed(
            title=f"🟢 Pick #{len(draft['pick_history']) + 1} — Your Turn",
            description=f"{mention}",
            color=0xff3fb9,
        )
        embed.add_field(name="Roster", value=make_roster_str(team["players"]), inline=False)
        embed.add_field(name="Country Counts", value=make_country_counts_str(team["players"]), inline=True)
        embed.add_field(name="Remaining", value=make_remaining_str(team["players"]), inline=True)
        if next_str:
            embed.add_field(name="Next", value=next_str, inline=False)

        # DM the player with interactive pick buttons if they're not in the server
        if member is None:
            try:
                user = await self.bot.fetch_user(owner_id)
                dm_embed = discord.Embed(
                    title=f"🟢 Pick #{len(draft['pick_history']) + 1} — Your Turn",
                    description=f"It's your turn in the **{guild.name}** draft!\nSelect a position below to start your pick.",
                    color=0xff3fb9,
                )
                dm_embed.add_field(name="Roster", value=make_roster_str(team["players"]), inline=False)
                dm_embed.add_field(name="Country Counts", value=make_country_counts_str(team["players"]), inline=True)
                dm_embed.add_field(name="Remaining", value=make_remaining_str(team["players"]), inline=True)
                dm_view = PositionButtons(self, guild_id, owner_id)
                await user.send(embed=dm_embed, view=dm_view)
            except Exception:
                pass

        view = PositionButtons(self, guild_id, owner_id)

        try:
            msg = await channel.send(content=mention, embed=embed, view=view)
        except (discord.Forbidden, discord.NotFound) as e:
            logger.warning("_send_turn: can't send turn — %s", e)
            return
        except Exception as e:
            logger.exception("_send_turn: unexpected error — %s", e)
            return
        draft["turn_message_id"] = msg.id
        self._save()

        self._start_timer(guild_id)

    async def _update_status(self, guild_id, channel, guild):
        draft = self._get_draft(guild_id)
        if draft is None:
            return

        total = len(draft["managers"]) * 11
        done = len(draft["pick_history"])

        owner_id = get_current_owner(draft)
        next_owners = get_next_owners(draft)
        next_str = ", ".join(
            f"<@{uid}>" if guild.get_member(uid) else f"<@{uid}>"
            for uid in next_owners
        )

        recent = draft["pick_history"][-5:]
        recent_lines = []
        for p in recent:
            m = guild.get_member(p["owner"])
            owner_name = m.display_name if m else f"<@{p['owner']}>"
            recent_lines.append(f"`#{p['pick_number']}` **{p['name']}** → {owner_name}")

        title = "🏆 World Cup Draft"
        if draft.get("paused"):
            title += " ⏸️ PAUSED"
        embed = discord.Embed(
            title=title,
            color=0xff3fb9,
        )
        if owner_id is not None:
            embed.add_field(name="Current Pick", value=f"<@{owner_id}>", inline=True)
        else:
            embed.add_field(name="Current Pick", value="Draft Complete!", inline=True)
        if next_str:
            embed.add_field(name="Next", value=next_str, inline=True)
        embed.add_field(name="Drafted", value=f"{done} / {total}", inline=True)
        if recent_lines:
            embed.add_field(name="Recent Picks", value="\n".join(recent_lines), inline=False)

        msg_id = draft.get("status_message_id")
        ch_id = draft.get("status_channel_id")
        target_ch = None
        if ch_id:
            target_ch = self.bot.get_channel(ch_id)
            if target_ch is None:
                target_ch = self.bot.get_channel_or_thread(ch_id)
        if target_ch is None:
            target_ch = channel

        if msg_id and target_ch:
            try:
                old = await target_ch.fetch_message(msg_id)
                await old.edit(embed=embed)
                return
            except Exception:
                pass

        if target_ch:
            try:
                msg = await target_ch.send(embed=embed)
            except (discord.Forbidden, discord.NotFound) as e:
                logger.warning("_update_status: can't send status — %s", e)
                return
            except Exception as e:
                logger.exception("_update_status: unexpected error — %s", e)
                return
            draft["status_message_id"] = msg.id
            draft["status_channel_id"] = target_ch.id
            self._save()

    async def _end_draft(self, guild_id, channel, guild):
        draft = self._get_draft(guild_id)
        if draft is None:
            return
        draft["ended"] = True
        self._cancel_timer(guild_id)
        await self._cleanup_turn_message(guild_id)
        self._save()

        embed = discord.Embed(
            title="🏆 Draft Complete!",
            description="All teams have been drafted.",
            color=0x00ff00,
        )
        await channel.send(embed=embed)
        await self._update_status(guild_id, channel, guild)

        board = self._draftboard_embed(draft, guild)
        await channel.send(embed=board)

    def _draftboard_embed(self, draft, guild):
        embed = discord.Embed(
            title="🏆 World Cup Draft Board",
            color=0xff3fb9,
        )
        for uid_str, team in draft["teams"].items():
            uid = int(uid_str)
            member = guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            roster = make_roster_str(team["players"])
            cc = make_country_counts_str(team["players"])
            val = f"{roster}\n\nCountries: {cc}"
            embed.add_field(name=name, value=val, inline=False)
        return embed

    def _team_embed(self, team, owner_id, guild):
        member = guild.get_member(owner_id)
        name = member.display_name if member else f"<@{owner_id}>"
        embed = discord.Embed(
            title=f"Team {name}",
            color=0xff3fb9,
        )
        embed.add_field(name="Roster", value=make_roster_str(team["players"]), inline=False)
        embed.add_field(name="Country Counts", value=make_country_counts_str(team["players"]), inline=True)
        embed.add_field(name="Remaining", value=make_remaining_str(team["players"]), inline=True)
        return embed

    # ── Commands ──────────────────────────────────────────────

    @commands.command()
    async def draftstart(self, ctx, *users: discord.User):
        """Start a new World Cup Snake Draft."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")

        if not users:
            return await ctx.send("Mention at least one manager: `.draftstart @user1 @user2 ...`")

        seen = set()
        mentioned = []
        for u in users:
            if u.id not in seen:
                seen.add(u.id)
                mentioned.append(u)
        if len(mentioned) < 1:
            return await ctx.send("Need at least 1 manager.")
        if len(mentioned) > 25:
            return await ctx.send("Max 25 managers allowed.")

        gid = str(ctx.guild.id)
        if gid in self.data and self.data[gid].get("started") and not self.data[gid].get("ended"):
            return await ctx.send("A draft is already active in this server. Use `.enddraft` first.")

        manager_ids = [u.id for u in mentioned]
        snake = generate_snake_order(manager_ids)

        draft = {
            "channel_id": ctx.channel.id,
            "managers": manager_ids,
            "snake_order": snake,
            "current_index": 0,
            "teams": {},
            "pick_history": [],
            "prepicks": {},
            "status_message_id": None,
            "status_channel_id": None,
            "turn_message_id": None,
            "paused": False,
            "started": True,
            "ended": False,
        }

        for uid in manager_ids:
            draft["teams"][str(uid)] = empty_team()

        self.data[gid] = draft
        self._save()

        order_str = "\n".join(
            f"`#{i+1}` {ctx.guild.get_member(uid).mention if ctx.guild.get_member(uid) else f'<@{uid}>'}"
            for i, uid in enumerate(manager_ids)
        )
        snake_preview = "\n".join(
            f"Round {r+1}: {' → '.join(ctx.guild.get_member(s).mention if ctx.guild.get_member(s) else f'<@{s}>' for s in snake[r*len(manager_ids):(r+1)*len(manager_ids)])}"
            for r in range(min(3, 11))
        )

        embed = discord.Embed(
            title="🏆 World Cup Snake Draft Started!",
            color=0xff3fb9,
        )
        embed.add_field(name="Draft Order", value=order_str, inline=False)
        embed.add_field(name="Snake Preview (first 3 rounds)", value=snake_preview, inline=False)
        embed.set_footer(text="Each manager drafts 11 players. Good luck!")
        await ctx.send(embed=embed)

        await self._update_status(guild_id=gid, channel=ctx.channel, guild=ctx.guild)
        await self._send_turn(gid, ctx.channel, ctx.guild)

    @commands.command()
    async def prepick(self, ctx):
        """Manage your prepicks (max 2)."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started") or draft.get("ended"):
            return await ctx.send("No active draft.")

        if str(ctx.author.id) not in draft["teams"]:
            return await ctx.send("You're not in this draft.")

        view = PrepickManageView(self, ctx.guild.id, ctx.author.id)
        await ctx.send(embed=view.embed, view=view)

    @commands.command()
    async def draftboard(self, ctx):
        """Show all teams in the draft."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")

        embed = self._draftboard_embed(draft, ctx.guild)
        await ctx.send(embed=embed)

    @commands.command()
    async def myteam(self, ctx):
        """Show your drafted team."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")

        team = draft["teams"].get(str(ctx.author.id))
        if team is None:
            return await ctx.send("You're not in this draft.")

        embed = self._team_embed(team, ctx.author.id, ctx.guild)
        await ctx.send(embed=embed)

    @commands.command()
    async def team(self, ctx, *, user: discord.User = None):
        """Show a user's team with fantasy points. Defaults to yourself."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")

        if user is None:
            user = ctx.author
        team = draft["teams"].get(str(user.id))
        if team is None:
            return await ctx.send("That user is not in this draft.")

        await self.fantasy.fetch_data()
        try:
            await fetch_and_cache_data()
        except Exception:
            pass
        resolved = self.fantasy.resolve_players(team["players"])
        total = sum(r["net_points"] for r in resolved)

        squad_games, max_games = get_squad_games_played()
        squad_remaining = get_squad_remaining()

        def _behind(sn):
            """True if this squad hasn't played the current round yet."""
            if not sn:
                return False
            gp = squad_games.get(sn, 0)
            if gp < max_games:
                return True
            if max_games >= 3 and sn in squad_remaining:
                return True
            return False

        remaining = sum(1 for r in resolved if _behind(r["squad_name"]))
        member = ctx.guild.get_member(user.id)
        name = member.display_name if member else f"<@{user.id}>"
        title = f"Team {name}"
        if remaining:
            title += f" — ({remaining} not played ⏳)"

        embed = discord.Embed(title=title, color=0xff3fb9)
        lines = []
        for pos in POSITIONS:
            pos_players = [r for r in resolved if r["position"] == pos]
            if pos_players:
                for r in pos_players:
                    pts_str = f"{r['net_points']}pts" if r['match'] else "N/A"
                    icon = "⏳ " if _behind(r["squad_name"]) else ""
                    sf = f" {_flag(r['squad_name'])} {r['squad_name']}" if r["squad_name"] else ""
                    lines.append(f"{POSITION_EMOJIS[pos]} {icon}**{r['name']}** — {pts_str}{sf}")
            else:
                lines.append(f"{POSITION_EMOJIS[pos]} {pos}: --")
        embed.description = "\n".join(lines)
        embed.add_field(name="Total Points", value=f"**{total}**", inline=True)
        embed.add_field(name="Picks", value=f"{len(resolved)}/11", inline=True)
        cc_str = ", ".join(f"{c}: {n}/2" for c, n in sorted(team["country_counts"].items()))
        embed.add_field(name="Countries", value=cc_str, inline=False)
        await ctx.send(embed=embed)

    @commands.command()
    async def undo(self, ctx):
        """Undo the most recent pick (commissioner only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")

        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started") or draft.get("ended"):
            return await ctx.send("No active draft.")

        if not draft["pick_history"]:
            return await ctx.send("No picks to undo.")

        last = draft["pick_history"].pop()
        owner_str = str(last["owner"])
        team = draft["teams"].get(owner_str)
        if team:
            idx = None
            for i, p in enumerate(team["players"]):
                if p["name"] == last["name"] and p["pick_number"] == last["pick_number"]:
                    idx = i
                    break
            if idx is not None:
                team["players"].pop(idx)
            team["country_counts"] = get_country_counts(team["players"])

        draft["current_index"] = max(0, draft["current_index"] - 1)
        draft["paused"] = False
        self._cancel_timer(ctx.guild.id)
        await self._cleanup_turn_message(ctx.guild.id)
        self._save()

        await ctx.send(f"✅ Undid pick #{last['pick_number']}: **{last['name']}** ({last['position']}, {last['country']})")

        await self._update_status(ctx.guild.id, ctx.channel, ctx.guild)
        await self._send_turn(ctx.guild.id, ctx.channel, ctx.guild)

    @commands.command()
    async def forcepick(self, ctx, *, player_name: str = None):
        """Force a pick for the current user (commissioner only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")

        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started") or draft.get("ended") or draft.get("paused"):
            return await ctx.send("No active draft or draft is paused.")

        owner_id = get_current_owner(draft)
        if owner_id is None:
            return await ctx.send("No current turn.")

        self._cancel_timer(ctx.guild.id)

        team = draft["teams"].get(str(owner_id), {"players": [], "country_counts": {}})
        valid = [p for p in POSITIONS if can_add_position(team["players"], p)]
        if not valid:
            return await ctx.send("No valid positions available for this user.")

        # Try auto-prepick first
        prepicks = draft.get("prepicks", {}).get(str(owner_id), [])
        for pp in prepicks:
            if not can_add_position(team["players"], pp["position"]):
                continue
            if not can_add_country(team["players"], pp["country"]):
                continue
            if is_player_drafted(draft, pp["player_name"]):
                continue

            pick = await self._execute_pick(ctx.guild.id, owner_id, pp["position"], pp["country"], pp["player_name"])
            if pick:
                flag = ""
                for n, f, _ in COUNTRY_LIST:
                    if n == pp["country"]:
                        flag = f
                        break
                announce = discord.Embed(
                    title=f"👑 Force Pick (Auto-Prepick) #{pick['pick_number']}",
                    description=f"Commissioner forced pick via prepick for <@{owner_id}>",
                    color=0xff0000,
                )
                announce.add_field(name="Player", value=f"**{pp['player_name']}**", inline=True)
                announce.add_field(name="Country", value=f"{flag} {pp['country']}", inline=True)
                announce.add_field(name="Position", value=f"{POSITION_EMOJIS[pp['position']]} {pp['position']}", inline=True)
                await ctx.send(embed=announce)
                await self._advance_after_pick(ctx.guild.id, ctx.channel, ctx.guild)
                return

        # No valid prepick — need manual input
        if not player_name:
            class ModalTrigger(discord.ui.View):
                def __init__(self2):
                    super().__init__(timeout=120)
                    btn = discord.ui.Button(label="✏️ Enter Player Name", style=discord.ButtonStyle.primary)
                    btn.callback = self2._trigger
                    self2.add_item(btn)
                async def _trigger(self2, interaction2):
                    if interaction2.user.id != ctx.author.id:
                        return await interaction2.response.send_message("Not yours.", ephemeral=True)
                    await interaction2.response.send_modal(ForcePickNameModal(self, ctx, draft, owner_id, team, valid))
                    await self2.message.delete(delay=2)
                async def on_timeout(self2):
                    try:
                        await self2.message.edit(content="Force pick timed out.", view=None)
                    except Exception:
                        pass
            trigger_msg = await ctx.send("✏️ No player name provided. Click the button to enter one:", view=ModalTrigger())
            trigger_msg.view.message = trigger_msg
            return

        player_name = player_name.strip()
        if not player_name:
            return await ctx.send("Player name cannot be empty.")
        if is_player_drafted(draft, player_name):
            return await ctx.send(f"'{player_name}' is already drafted.")

        await self._show_forcepick_view(ctx, draft, owner_id, team, valid, player_name)

    async def _show_forcepick_view(self, ctx, draft, owner_id, team, valid, player_name):
        available_continents = {}
        for c_name, emoji, countries in CONTINENTS:
            filtered = [(name, flag) for name, flag, _ in COUNTRY_LIST if name in countries and can_add_country(team["players"], name)]
            if filtered:
                available_continents[c_name] = (emoji, filtered)
        if not available_continents:
            return await ctx.send("No countries available (all maxed out).")

        msg = await ctx.send(
            f"Force-picking **{player_name}** for <@{owner_id}>.\nSelect position, continent, and country:",
        )

        class ForcePickView(discord.ui.View):
            def __init__(self2, cog, msg):
                super().__init__(timeout=120)
                self2.cog = cog
                self2.position = None
                self2.country = None
                self2.message = msg

                pos_select = discord.ui.Select(
                    placeholder="Select position...",
                    options=[
                        discord.SelectOption(label=pos, value=pos, emoji=POSITION_EMOJIS[pos])
                        for pos in valid
                    ],
                    row=0,
                )
                pos_select.callback = self2._pos_callback
                self2.add_item(pos_select)

                cont_select = discord.ui.Select(
                    placeholder="Select continent...",
                    options=[
                        discord.SelectOption(label=f"{emoji} {c_name}", value=c_name, emoji=emoji)
                        for c_name, (emoji, _) in available_continents.items()
                    ],
                    row=1,
                )
                cont_select.callback = self2._cont_callback
                self2.add_item(cont_select)

                self2._country_select = discord.ui.Select(
                    placeholder="Select country...",
                    options=[discord.SelectOption(label="Pick a continent first", value="__placeholder__")],
                    row=2,
                    disabled=True,
                )
                self2._country_select.callback = self2._country_callback
                self2.add_item(self2._country_select)

                confirm = discord.ui.Button(label="Force Pick", style=discord.ButtonStyle.danger, row=3)
                confirm.callback = self2._confirm_callback
                self2.add_item(confirm)

            async def on_timeout(self2):
                try:
                    await self2.message.edit(content="Force pick timed out.", view=None)
                except Exception:
                    pass

            async def _pos_callback(self2, interaction):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Not yours.", ephemeral=True)
                self2.position = interaction.data["values"][0]
                await interaction.response.defer()

            async def _cont_callback(self2, interaction):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Not yours.", ephemeral=True)
                continent = interaction.data["values"][0]
                _, countries = available_continents[continent]
                self2._country_select.options = [
                    discord.SelectOption(label=f"{f} {n}", value=n, emoji=f) for n, f in countries
                ]
                self2._country_select.disabled = False
                await interaction.response.edit_message(view=self2)

            async def _country_callback(self2, interaction):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Not yours.", ephemeral=True)
                self2.country = interaction.data["values"][0]
                await interaction.response.defer()

            async def _confirm_callback(self2, interaction):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Not yours.", ephemeral=True)
                if not self2.position or not self2.country:
                    return await interaction.response.send_message("Select both position and country first.", ephemeral=True)
                d = self2.cog._get_draft(ctx.guild.id)
                if d.get("paused") or d.get("ended"):
                    return await interaction.response.send_message("Draft is paused or ended.", ephemeral=True)
                if get_current_owner(d) != owner_id:
                    return await interaction.response.send_message("That user is no longer on the clock.", ephemeral=True)
                current_team = d["teams"].get(str(owner_id), empty_team())
                if not can_add_position(current_team["players"], self2.position):
                    return await interaction.response.send_message(f"Position {self2.position} is no longer available.", ephemeral=True)
                if not can_add_country(current_team["players"], self2.country):
                    return await interaction.response.send_message(f"Country limit reached for {self2.country}.", ephemeral=True)
                if is_player_drafted(d, player_name):
                    return await interaction.response.send_message(f"'{player_name}' already drafted since you started.", ephemeral=True)

                await interaction.response.defer()
                pick = await self2.cog._execute_pick(ctx.guild.id, owner_id, self2.position, self2.country, player_name)
                if pick is None:
                    return
                flag = ""
                for n, f, _ in COUNTRY_LIST:
                    if n == self2.country:
                        flag = f
                        break
                announce = discord.Embed(
                    title=f"👑 Force Pick #{pick['pick_number']}",
                    description=f"Commissioner forced pick for <@{owner_id}>",
                    color=0xff0000,
                )
                announce.add_field(name="Player", value=f"**{player_name}**", inline=True)
                announce.add_field(name="Country", value=f"{flag} {self2.country}", inline=True)
                announce.add_field(name="Position", value=f"{POSITION_EMOJIS[self2.position]} {self2.position}", inline=True)
                await ctx.send(embed=announce)

                await self2.cog._advance_after_pick(ctx.guild.id, ctx.channel, ctx.guild)
                try:
                    await msg.delete()
                except Exception:
                    pass

        view = ForcePickView(self, msg)
        await msg.edit(view=view)

    # ── Fantasy Points ─────────────────────────────────────────

    FANTASY_PLAYERS_URL = "https://play.fifa.com/json/fantasy/players.json"
    FANTASY_SQUADS_URL = "https://play.fifa.com/json/fantasy/squads.json"
    FANTASY_CACHE_TTL = 120

    @staticmethod
    def _norm(s):
        return re.sub(r"[^\w\s]", "", s.strip().lower())

    async def _fetch_fantasy_data(self):
        loop = asyncio.get_event_loop()
        now = loop.time()
        if self._fantasy_cache and now - self._fantasy_cache_time < self.FANTASY_CACHE_TTL:
            return self._fantasy_cache

        async with aiohttp.ClientSession() as session:
            async with session.get(self.FANTASY_PLAYERS_URL) as r:
                players = await r.json()
            async with session.get(self.FANTASY_SQUADS_URL) as r:
                squads_raw = await r.json()

        squads = {s["id"]: s for s in squads_raw}
        self._fantasy_cache = (players, squads)
        self._fantasy_cache_time = now
        return players, squads

    def _match_player(self, players, name):
        q = self._norm(name)
        for p in players:
            pname = self._norm(p.get("knownName") or f"{p['firstName']} {p['lastName']}")
            if pname == q:
                return p
        for p in players:
            pname = self._norm(p.get("knownName") or f"{p['firstName']} {p['lastName']}")
            if q in pname or pname in q:
                return p
        return None

    @commands.command()
    async def draftpoints(self, ctx):
        """Show fantasy points leaderboard for all draft teams."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")

        await ctx.send("⏳ Fetching fantasy points...")

        await self.fantasy.fetch_data()
        try:
            await fetch_and_cache_data()
        except Exception:
            pass
        squad_games, max_games = get_squad_games_played()
        squad_remaining = get_squad_remaining()

        def _behind(sn):
            if not sn:
                return False
            gp = squad_games.get(sn, 0)
            if gp < max_games:
                return True
            if max_games >= 3 and sn in squad_remaining:
                return True
            return False

        results = []
        for uid_str, team in draft["teams"].items():
            uid = int(uid_str)
            member = ctx.guild.get_member(uid)
            manager = member.display_name if member else f"<@{uid}>"
            resolved = self.fantasy.resolve_players(team["players"])
            total = sum(r["net_points"] for r in resolved)
            not_played = sum(1 for r in resolved if _behind(r["squad_name"]))
            details = [
                (r["name"], r["net_points"], r["position"], r["squad_name"])
                for r in resolved
            ]
            results.append((total, manager, details, not_played))

        results.sort(key=lambda x: x[0], reverse=True)

        embed = discord.Embed(title="🏆 Draft Fantasy Points", color=0xff3fb9)
        for rank, (total, manager, details, not_played) in enumerate(results, 1):
            lines = []
            for n, p, pos, squad_name in details:
                icon = "⏳ " if _behind(squad_name) else ""
                sf = f" {_flag(squad_name)} {squad_name}" if squad_name else ""
                pts_str = f"{p}pts"
                lines.append(f"{icon}{n}: {pts_str} ({pos}){sf}")
            val = "\n".join(lines) if lines else "No players drafted"
            val += f"\n**Total: {total} pts**"
            suffix = f" — ({not_played} not played ⏳)" if not_played else ""
            embed.add_field(name=f"#{rank} {manager}{suffix}", value=val[:1024], inline=False)

        await ctx.send(embed=embed)

    @commands.command()
    async def playerpoints(self, ctx, *, name: str):
        """Look up a player's fantasy points."""
        if not name:
            return await ctx.send("Usage: `.playerpoints <player name>`")

        players, squads = await self._fetch_fantasy_data()
        match = self._match_player(players, name)
        if not match:
            return await ctx.send(f"Player '{name}' not found in FIFA fantasy data.")

        pname = match.get("knownName") or f"{match['firstName']} {match['lastName']}"
        squad = squads.get(match["squadId"], {})
        squad_name = squad.get("name", "Unknown")
        pos = match["position"]
        pts = match["stats"]["totalPoints"]
        last = match["stats"]["lastRoundPoints"]

        embed = discord.Embed(title=f"⚽ {pname}", color=0xff3fb9)
        embed.add_field(name="Position", value=pos, inline=True)
        embed.add_field(name="Team", value=squad_name, inline=True)
        embed.add_field(name="Total Points", value=pts, inline=True)
        embed.add_field(name="Last Round", value=last, inline=True)
        await ctx.send(embed=embed)

    @commands.command()
    async def standings(self, ctx):
        """Show fantasy points standings for all teams."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")

        await ctx.send("⏳ Fetching fantasy points...")
        await self.fantasy.fetch_data()
        standings = self.fantasy.get_standings(draft, ctx.guild)

        embed = discord.Embed(title="🏆 Draft Standings", color=0xff3fb9)
        for rank, s in enumerate(standings, 1):
            total = s["net_points"]
            avg = round(total / max(s["pick_count"], 1), 1)
            best = max(s["players"], key=lambda x: x["net_points"])
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
            val = (
                f"**Total:** {total} pts\n"
                f"**Avg:** {avg} | **Best:** {best['name']} ({best['net_points']})"
            )
            embed.add_field(name=f"{medal} {s['name']}", value=val, inline=False)

        await ctx.send(embed=embed)

    @commands.command(aliases=["pp"])
    async def player(self, ctx, *, name: str):
        """Look up a player's fantasy points."""
        if not name:
            return await ctx.send("Usage: `.player <player name>`")

        await self.fantasy.fetch_data()
        match = self.fantasy.match_player(name)
        if not match:
            return await ctx.send(f"Player '{name}' not found in FIFA fantasy data.")

        pname = match.get("knownName") or f"{match['firstName']} {match['lastName']}"
        squad = self.fantasy.get_player_squad(match.get("squadId"))
        squad_name = squad.get("name", "Unknown") if squad else "Unknown"
        pos_code = str(match.get("position", ""))
        pos = FIFA_POSITION_MAP.get(pos_code, pos_code)
        total, last, round_pts = self.fantasy.get_player_points(match)
        gp = self.fantasy.get_games_played(match)
        scout, _ = self.fantasy.get_scouting_bonus(match)
        net = total - scout

        # Find which draft user owns this player
        name_lower = pname.lower()
        owner_info = None
        draft = self._get_draft(ctx.guild.id)
        if draft:
            for uid_str, team in draft["teams"].items():
                for p in team["players"]:
                    if p["name"].lower() == name_lower:
                        uid = int(uid_str)
                        member = ctx.guild.get_member(uid)
                        owner_info = member.display_name if member else f"<@{uid}>"
                        break
                if owner_info:
                    break

        embed = discord.Embed(title=f"⚽ {pname}", color=0xff3fb9)
        sf = f" {_flag(squad_name)} {squad_name}" if squad_name else squad_name
        embed.add_field(name="Position", value=pos, inline=True)
        embed.add_field(name="Team", value=sf, inline=True)
        embed.add_field(name="Total Points", value=net, inline=True)
        embed.add_field(name="Last Round", value=last, inline=True)
        embed.add_field(name="Games Played", value=gp, inline=True)
        if owner_info:
            embed.add_field(name="Drafted by", value=owner_info, inline=True)

        all_rounds = round_pts.copy() if round_pts else {}
        rounds_sel = match.get("roundsSelected", {})
        if rounds_sel:
            for rnd in rounds_sel:
                if rnd not in all_rounds:
                    all_rounds[rnd] = None

        if all_rounds:
            sorted_rounds = sorted(all_rounds.items(), key=lambda x: int(x[0]))
            round_lines = []
            for r, pts in sorted_rounds:
                if pts is not None:
                    round_lines.append(f"**M{r}:** {pts} pts")
                else:
                    round_lines.append(f"**M{r}:** ⏳ not played yet")
            embed.add_field(
                name="📅 Round Breakdown",
                value="\n".join(round_lines),
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command()
    async def topplayers(self, ctx, limit: int = 10):
        """Show top N drafted players by fantasy points."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")

        if limit < 1 or limit > 25:
            limit = 10

        await ctx.send("⏳ Fetching fantasy points...")
        await self.fantasy.fetch_data()
        top = self.fantasy.get_top_drafted_players(draft, limit)

        embed = discord.Embed(
            title=f"🏆 Top {limit} Drafted Players",
            color=0xff3fb9,
        )
        lines = []
        for rank, r in enumerate(top, 1):
            pts_str = f"{r['net_points']}pts" if r['match'] else "N/A"
            lines.append(f"`#{rank}` **{r['name']}** — {pts_str} ({r['position']})")
        embed.description = "\n".join(lines) if lines else "No players found."
        await ctx.send(embed=embed)

    @commands.command()
    async def teamvalue(self, ctx, *, user: discord.User = None):
        """Show a team's point breakdown per player."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")

        if user is None:
            user = ctx.author
        team = draft["teams"].get(str(user.id))
        if team is None:
            return await ctx.send("That user is not in this draft.")

        await ctx.send("⏳ Fetching fantasy points...")
        await self.fantasy.fetch_data()
        resolved = self.fantasy.resolve_players(team["players"])
        total = sum(r["net_points"] for r in resolved)

        member = ctx.guild.get_member(user.id)
        name = member.display_name if member else f"<@{user.id}>"
        embed = discord.Embed(
            title=f"📊 {name} — Point Breakdown",
            color=0xff3fb9,
        )
        sorted_players = sorted(resolved, key=lambda x: x["net_points"], reverse=True)
        lines = []
        for r in sorted_players:
            pts_str = f"{r['net_points']}pts" if r['match'] else "N/A"
            gp = f"({r['games_played']}g)" if r['match'] else ""
            lines.append(f"**{r['name']}** — {pts_str} {gp}")
        embed.description = "\n".join(lines)
        embed.add_field(name="Total", value=f"**{total} pts**", inline=True)
        embed.add_field(name="Avg", value=f"**{round(total / max(len(resolved), 1), 1)}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command()
    async def scoutingboard(self, ctx):
        """Leaderboard showing scouting bonus breakdown for all teams."""
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")

        await ctx.send("⏳ Fetching fantasy data...")
        await self.fantasy.fetch_data()

        embed = discord.Embed(
            title="🔍 Scouting Bonus Leaderboard",
            color=0xff3fb9,
        )
        team_data = []
        for uid_str, team in draft["teams"].items():
            uid = int(uid_str)
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            total_bonus = 0
            player_lines = []
            for pp in team["players"]:
                match = self.fantasy.match_player(pp["name"], fifa_id=pp.get("fifa_id"))
                bonus, breakdown = self.fantasy.get_scouting_bonus(match)
                total_bonus += bonus
                if breakdown:
                    rounds_str = "; ".join(
                        f"R{rnd}: +2 ({det['pts']}pts @ {det['ownership']}%)"
                        for rnd, det in sorted(breakdown.items())
                    )
                    player_lines.append(f"**{pp['name']}** — {rounds_str}")
            team_data.append((total_bonus, name, player_lines))

        team_data.sort(key=lambda x: x[0], reverse=True)
        for rank, (total_bonus, name, player_lines) in enumerate(team_data, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
            val = "\n".join(player_lines) if player_lines else "No scouting bonuses"
            val += f"\n**Total Bonus: +{total_bonus}**"
            embed.add_field(name=f"{medal} {name}", value=val, inline=False)

        await ctx.send(embed=embed)



    @commands.command()
    async def pause(self, ctx):
        """Pause the draft (commissioner only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started") or draft.get("ended"):
            return await ctx.send("No active draft.")
        draft["paused"] = True
        self._cancel_timer(ctx.guild.id)
        await self._cleanup_turn_message(ctx.guild.id)
        self._save()
        await ctx.send("⏸️ Draft paused.")

    @commands.command()
    async def resume(self, ctx):
        """Resume the draft (commissioner only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started") or draft.get("ended"):
            return await ctx.send("No active draft.")
        if not draft.get("paused"):
            return await ctx.send("Draft is not paused.")
        draft["paused"] = False
        self._save()
        await ctx.send("▶️ Draft resumed.")
        await self._update_status(ctx.guild.id, ctx.channel, ctx.guild)
        await self._send_turn(ctx.guild.id, ctx.channel, ctx.guild)

    @commands.command()
    async def enddraft(self, ctx):
        """End the draft (commissioner only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")
        draft = self._get_draft(ctx.guild.id)
        if draft is None or not draft.get("started"):
            return await ctx.send("No active draft.")
        await self._end_draft(ctx.guild.id, ctx.channel, ctx.guild)
        await ctx.send("Draft ended.")


    # ── Match Analytics ──────────────────────────────────────────

    @commands.command(aliases=["matchinfo"])
    async def matches(self, ctx, *, filter_term: str = None):
        """Show match results, group standings with tiebreakers, and upcoming fixtures. Interactive."""
        if filter_term:
            group_filter = filter_term.upper().replace("GROUP ", "")
            team_filter = filter_term.lower()
            if group_filter in "ABCDEFGHIJKL":
                await ctx.send("⏳ Fetching data...")
                try:
                    await fetch_and_cache_data()
                except Exception:
                    pass
                embed = _build_group_embed(group_filter)
                if embed is None:
                    return await ctx.send(f"No data for Group {group_filter}.")
                view = StandingsView(group_filter)
                return await ctx.send(embed=embed, view=view)

            await ctx.send("⏳ Fetching latest match data...")
            try:
                await fetch_and_cache_data()
            except Exception:
                await ctx.send("⚠️ Could not fetch live data, using cached...")

            match_reports, upcoming_reports = get_match_analytics(limit_matches=12)
            match_reports = [
                m for m in match_reports
                if team_filter in m["home"].lower() or team_filter in m["away"].lower()
            ]
            upcoming_reports = [
                m for m in upcoming_reports
                if team_filter in m["home"].lower() or team_filter in m["away"].lower()
            ]
            if not match_reports and not upcoming_reports:
                return await ctx.send("No matches found for that filter.")
            embed = discord.Embed(title="⚽ World Cup 2026 — Match Report", color=0xff3fb9)
            if match_reports:
                lines = []
                for mr in match_reports:
                    scoreline = f"**{mr['home']}** {mr['home_score']} — {mr['away_score']} **{mr['away']}**"
                    lines.append(f"`{mr['group']:8s}` {scoreline}")
                    h_top = mr["home_scorers"][:2]
                    a_top = mr["away_scorers"][:2]
                    if h_top:
                        h_str = ", ".join(f"{n} ({p}pts)" for p, n, _, _, _, _ in h_top)
                        lines.append(f"         ⬆ {h_str}")
                    if a_top:
                        a_str = ", ".join(f"{n} ({p}pts)" for p, n, _, _, _, _ in a_top)
                        lines.append(f"         ⬇ {a_str}")
                    lines.append("")
                embed.add_field(name=f"📊 Results ({len(match_reports)} matches)", value="\n".join(lines)[:1024], inline=False)
            if upcoming_reports:
                lines = [f"`{ur['group']:8s}` {ur['home']} vs {ur['away']}" for ur in upcoming_reports]
                embed.add_field(name=f"🔜 Upcoming ({len(upcoming_reports)} matches)", value="\n".join(lines), inline=False)
            return await ctx.send(embed=embed)

        embed = discord.Embed(
            title="🌍 World Cup 2026",
            description="Select a group below to view standings, match results, and tiebreakers.",
            color=0xff3fb9,
        )
        await ctx.send(embed=embed, view=GroupSelectView())

    @commands.command(aliases=["form"])
    async def trending(self, ctx, position: str = None):
        """Show players with best form rating.
        Optional: GK / DEF / MID / FWD to filter by position."""
        pos = position.upper() if position else None
        if pos and pos not in ("GK", "DEF", "MID", "FWD"):
            return await ctx.send("Invalid position. Use: GK, DEF, MID, or FWD")

        await ctx.send("⏳ Analyzing player form...")
        players = get_form_players(position=pos, limit=15)

        if not players:
            return await ctx.send("No players found.")

        embed = discord.Embed(
            title=f"🔥 Trending Players{' (' + pos + ')' if pos else ''}",
            description="Highest form rating (last 3 rounds weighted)",
            color=0xff3fb9,
        )
        lines = []
        for rank, p in enumerate(players, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"`#{rank}`")
            lines.append(
                f"{medal} **{p['name']}** — {p['position']} | "
                f"Form: {p['form']} | Avg: {p['avg']} | "
                f"${p['price']}M | {p['squad']}"
            )
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.command(aliases=["diff"])
    async def differentials(self, ctx, limit: int = 10):
        """Show best differential picks (high points, low ownership)."""
        if limit < 1 or limit > 25:
            limit = 10

        await ctx.send("⏳ Finding differential picks...")
        players = get_differentials(limit=limit)

        if not players:
            return await ctx.send("No players found.")

        embed = discord.Embed(
            title="🎯 Differential Picks",
            description=f"Top {limit} players with high points & low ownership",
            color=0xff3fb9,
        )
        lines = []
        for rank, p in enumerate(players, 1):
            lines.append(
                f"`#{rank}` **{p['name']}** — {p['position']} | "
                f"{p['total']}pts | ${p['price']}M | "
                f"Owned: {p['owned']}% | {p['squad']}"
            )
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.command()
    async def refreshpoints(self, ctx):
        """Fetch fresh fantasy points from FIFA servers (admin only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")

        status = await ctx.send("🔄 Fetching latest fantasy data from FIFA servers...")

        try:
            await self.fantasy.fetch_data(force=True)
            total = len(self.fantasy._players)
            with_points = len([p for p in self.fantasy._players if p.get("stats", {}).get("totalPoints", 0) > 0])
            # Save fresh data to local files
            with open(os.path.join(FIFA_DIR, "players.json"), "w", encoding="utf-8") as f:
                json.dump(self.fantasy._players, f, ensure_ascii=False)
            with open(os.path.join(FIFA_DIR, "squads.json"), "w", encoding="utf-8") as f:
                json.dump(list(self.fantasy._squads.values()), f, ensure_ascii=False)
            await status.edit(content=f"✅ Updated! {total} players loaded, {with_points} with points.")
        except Exception as e:
            await status.edit(content=f"❌ Failed to fetch: {e}")

    # ── Live Simulation ─────────────────────────────────────────

    @commands.command(aliases=["simhelp"])
    async def simulate_help(self, ctx):
        """Detailed explanation of simulation models (V1-V5)."""
        embed1 = discord.Embed(title="Simulation Commands Overview", color=0xff3fb9)
        embed1.add_field(name="Tournament Simulation", value=(
            "`.simulate` / `.fsim` / `.sim` — **full World Cup 2026 sim**\n"
            "Picks: version → mode → flags\n\n"
            "**Syntax:** `.simulate [version] [mode] [debug]`\n"
            "**Short:** `.fsim [version] [mode] [debug]`\n"
            "**Examples:**\n"
            "`.fsim` — V1 fast (default)\n"
            "`.fsim v4` — V4 tactical, fast\n"
            "`.fsim v5` — V5 match state, fast\n"
            "`.fsim v4 animated` — V4 goal-by-goal\n"
            "`.fsim v4 debug` — V4 with tactical breakdown"
        ), inline=False)
        embed1.add_field(name="Head-to-Head Analysis", value=(
            "`.fsim detailed` — **Monte Carlo between 2 teams**\n"
            "Picks: version → team A → team B → options\n\n"
            "**Syntax:** `.fsim detailed <version> <Team A> <Team B> [knockout] [N]`\n"
            "**Examples:**\n"
            "`.fsim detailed v4 France Spain`\n"
            "`.fsim detailed v5 France Spain`\n"
            "`.fsim detailed v4 France Spain knockout`\n"
            "`.fsim detailed v4 France Spain 10000`\n"
            "`.fsim detailed v5 France Spain knockout 10000`"
        ), inline=False)
        await ctx.send(embed=embed1)

        embed2 = discord.Embed(title="Simulation Versions", color=0xff3fb9)
        embed2.add_field(name="V1 — ELO Rating Engine", value=(
            "`.simulate v1`\n"
            "Classic ELO + PELE. Teams rated by historical strength. "
            "Goal diff weighted (1x / 1.5x / 2x). "
            "Fastest option — best when only team quality matters."
        ), inline=False)
        embed2.add_field(name="V2 — Player Attribute Engine", value=(
            "`.simulate v2`\n"
            "Every player rated individually from FC26 + fantasy data. "
            "7 role formulas (GK, CB, FB, CM, DM, WINGER, ST). "
            "Formation-aware. Star players can carry weaker teams."
        ), inline=False)
        embed2.add_field(name="V3 — Dynamic State Engine", value=(
            "`.simulate v3`\n"
            "Builds on V2 + 6 dynamic modifiers: Chemistry, Experience, Form, "
            "Momentum, Continuity, Leadership. National strength modifiers. "
            "Most realistic single-match sim."
        ), inline=False)
        embed2.add_field(name="V4 — Tactical Intelligence Engine", value=(
            "`.simulate v4` / `.fsim detailed v4`\n"
            "Tactical layer on top of V3. "
            "20+ attributes per team, 62 manager profiles, 5 defensive styles, "
            "5 game plans, 8 formation profiles. "
            "Match context affects xG: Group (baseline), Knockout (-0.01), "
            "Must-win (+0.02), Need draw (-0.015), GD chase (+0.025 xG, -0.015 def)."
        ), inline=False)
        embed2.add_field(name="V5 — Match State Simulation (NEW)", value=(
            "**`.simulate v5` / `.fsim detailed v5`**\n"
            "Full 90+ minute phase-based simulation on top of V4 tactical layer. "
            "Every match unfolds through 6 regular phases + 2 extra time phases. "
            "Features: player fatigue system, yellow/red cards, substitutions, "
            "in-match momentum, scoreline intelligence, manager reactions, "
            "penalty shootouts, and dynamic event generation (attacks → shots → "
            "big chances → goals). Most immersive and realistic option."
        ), inline=False)
        embed2.set_footer(text="48 teams | 20+ attributes | 8 formations | 5 contexts | V5 adds fatigue, cards, subs")
        await ctx.send(embed=embed2)

    @commands.command(aliases=["sim", "fsim"])
    async def simulate(self, ctx, *, args: str = None):
        """Run tournament simulation: `.simulate [v1|v2|v3|v4|v5] [fast|animated|detailed] [debug]` or `.fsim ...`."""
        if args and args.strip().lower() in ("help", "?"):
            return await self.simulate_help(ctx)
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")

        tokens = args.split() if args and args.strip() else []
        if tokens and tokens[0].lower() == "detailed":
            return await self._simulate_detailed(ctx, tokens[1:])

        model, presentation, debug = self._parse_simulation_args(args)
        if model is None:
            return await ctx.send(presentation)

        status_msg = await ctx.send(f"🌍 **World Cup 2026 — {model.upper()} Simulation**\n⏳ Fetching latest FIFA data...")

        fifa_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fifa_data")

        try:
            async with aiohttp.ClientSession() as session:
                params = {"idCompetition": "17", "idSeason": "285023", "count": 200}
                async with session.get(
                    "https://api.fifa.com/api/v3/calendar/matches",
                    params=params, timeout=15,
                ) as r:
                    match_data = await r.json()
                async with session.get(
                    "https://play.fifa.com/json/fantasy/players.json",
                    timeout=15,
                ) as r:
                    players = await r.json()
                async with session.get(
                    "https://play.fifa.com/json/fantasy/squads.json",
                    timeout=15,
                ) as r:
                    squads_raw = await r.json()

            results = match_data.get("Results", [])
            completed = []
            upcoming = []
            for m in results:
                status = m.get("MatchStatus")
                home_data = m.get("Home") or {}
                away_data = m.get("Away") or {}
                home = (home_data.get("TeamName") or [{}])[0].get("Description", "?")
                away = (away_data.get("TeamName") or [{}])[0].get("Description", "?")
                hs = m.get("HomeTeamScore")
                aas = m.get("AwayTeamScore")
                entry = {
                    "id": m.get("IdMatch"),
                    "date": m.get("Date", "?"),
                    "stage": (m.get("StageName") or [{}])[0].get("Description") if m.get("StageName") else None,
                    "group": (m.get("GroupName") or [{}])[0].get("Description") if m.get("GroupName") else None,
                    "home": {"name": home, "score": hs, "id": home_data.get("IdTeam")},
                    "away": {"name": away, "score": aas, "id": away_data.get("IdTeam")},
                    "winner": m.get("Winner"),
                    "status": status,
                }
                if status == 0:
                    completed.append(entry)
                else:
                    upcoming.append(entry)

            matches_out = {
                "last_updated": datetime.utcnow().isoformat(),
                "completed_count": len(completed),
                "upcoming_count": len(upcoming),
                "competition": "FIFA World Cup 2026",
                "completed": completed,
                "upcoming": upcoming,
            }
            with open(os.path.join(fifa_dir, "matches.json"), "w", encoding="utf-8") as f:
                json.dump(matches_out, f, indent=2, ensure_ascii=False)
            with open(os.path.join(fifa_dir, "players.json"), "w", encoding="utf-8") as f:
                json.dump(players, f, indent=2, ensure_ascii=False)
            with open(os.path.join(fifa_dir, "squads.json"), "w", encoding="utf-8") as f:
                json.dump(squads_raw, f, indent=2, ensure_ascii=False)

            self.fantasy._players = None
            self.fantasy._cache_time = 0

            await status_msg.edit(content=f"🌍 **World Cup 2026 — {model.upper()} Simulation**\n✅ Data fetched. Simulating...")
        except Exception as e:
            await status_msg.edit(content=f"🌍 **World Cup 2026 — {model.upper()} Simulation**\n⚠️ Using cached data ({e})")

        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, run_simulation, model, debug)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return await ctx.send(f"❌ Simulation error: {e}")

        if presentation == "animated":
            await self._simulate_animated(ctx, status_msg, data, model=model)
        else:
            await self._simulate_fast(ctx, status_msg, data, model=model, debug=debug)

    async def _simulate_detailed(self, ctx, tokens: list[str]) -> None:
        VALID_VERSIONS = {"v1", "v2", "v3", "v4", "v5"}
        VERSION_LABELS = {
            "v1": "Historical ELO/PELE",
            "v2": "FC26 Player Intelligence",
            "v3": "Dynamic Team State",
            "v4": "Tactical Intelligence",
            "v5": "Match State Simulation",
        }
        MATCHES_TEAM_MAP = {
            "USA": "United States",
            "Cabo Verde": "Cape Verde",
            "Bosnia and Herzegovina": "Bosnia-Herzegovina",
            "South Korea": "Korea Republic",
            "Czech Republic": "Czechia",
            "Turkey": "Türkiye",
            "Iran": "IR Iran",
        }

        all_teams = set()
        for group_teams in GROUPS.values():
            all_teams.update(group_teams)

        flag_map = {}
        for name, emoji, _ in COUNTRY_LIST:
            mapped = MATCHES_TEAM_MAP.get(name, name)
            flag_map[name] = emoji
            flag_map[mapped] = emoji

        def normalize_team(name: str) -> str:
            return name.strip().lower().replace("-", " ")

        def resolve_team(raw: str) -> tuple[str | None, str | None]:
            raw_mapped = MATCHES_TEAM_MAP.get(raw.strip(), raw.strip())
            q = normalize_team(raw_mapped)
            for t in all_teams:
                if normalize_team(t) == q:
                    return t, None
            matches = difflib.get_close_matches(q, [normalize_team(t) for t in all_teams], n=1, cutoff=0.6)
            if matches:
                for t in all_teams:
                    if normalize_team(t) == matches[0]:
                        return t, None
            suggestions = difflib.get_close_matches(q, [normalize_team(t) for t in all_teams], n=3, cutoff=0.4)
            resolved = []
            for s in suggestions:
                for t in all_teams:
                    if normalize_team(t) == s:
                        resolved.append(t)
            return None, resolved

        if not tokens or len(tokens) < 3:
            lines = [
                "❌ **Invalid .fsim detailed syntax.**",
                "",
                "Usage:",
                "`.fsim detailed <version> <Team A> <Team B> [knockout] [simulations]`",
                "",
                "Versions:",
                "`v1` — Historical strength (ELO + PELE)",
                "`v2` — Player intelligence (FC26 ratings, XI, formations)",
                "`v3` — Team state (chemistry, form, experience, momentum, leadership)",
                "`v4` — Tactical intelligence (styles, formations, managers, matchups)",
                "`v5` — Match state simulation (fatigue, cards, subs, momentum, penalties)",
                "",
                "Examples:",
                "`.fsim detailed v4 France Spain`",
                "`.fsim detailed v4 France Spain knockout`",
                "`.fsim detailed v5 France Spain 1000`",
                "`.fsim detailed v5 France Spain knockout 10000`",
            ]
            return await ctx.send("\n".join(lines))

        version = tokens[0].lower()
        if version not in VALID_VERSIONS:
            avail = "\n".join(f"`{v}` — {VERSION_LABELS[v]}" for v in ["v1", "v2", "v3", "v4", "v5"])
            return await ctx.send(
                f"❌ Unknown version: `{version}`\n\nAvailable:\n{avail}"
            )

        team_a_raw, team_b_raw = tokens[1], tokens[2]
        team_a, suggestion_a = resolve_team(team_a_raw)
        team_b, suggestion_b = resolve_team(team_b_raw)

        if not team_a:
            msg = f"❌ Unknown team: `{team_a_raw}`\n"
            if suggestion_a:
                msg += "\nDid you mean:\n" + "\n".join(
                    f"{flag_map.get(t, '🏳️')} {t}" for t in suggestion_a[:3]
                )
            return await ctx.send(msg)

        if not team_b:
            msg = f"❌ Unknown team: `{team_b_raw}`\n"
            if suggestion_b:
                msg += "\nDid you mean:\n" + "\n".join(
                    f"{flag_map.get(t, '🏳️')} {t}" for t in suggestion_b[:3]
                )
            return await ctx.send(msg)

        remaining = tokens[3:]
        knockout = False
        simulations = 100

        for tok in remaining:
            lowered = tok.lower()
            if lowered == "knockout":
                knockout = True
            elif lowered.isdigit() and int(lowered) > 0:
                simulations = int(lowered)
            else:
                return await ctx.send(
                    f"❌ Unknown option: `{tok}`\n\n"
                    "Usage: `.fsim detailed <version> <Team A> <Team B> [knockout] [simulations]`"
                )

        flag_a = flag_map.get(team_a, "🏳️")
        flag_b = flag_map.get(team_b, "🏳️")

        status = await ctx.send(
            f"🔬 **{version.upper()} Detailed Analysis**\n"
            f"{flag_a} **{team_a}** vs {flag_b} **{team_b}**\n"
            f"{'🏟️ Knockout mode' if knockout else '📊 Group stage'}"
            f" | {simulations:,} simulations\n⏳ Working..."
        )

        loop = asyncio.get_event_loop()
        try:
            report = await loop.run_in_executor(
                None, self._run_monte_carlo,
                version, team_a, team_b, knockout, simulations,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return await ctx.send(f"❌ Simulation error: {e}")

        report.flag_a = flag_a
        report.flag_b = flag_b

        pages = self._build_report_pages(report)
        view = _ReportView(pages, ctx.author.id)
        await status.edit(content=None, embed=pages[0], view=view)
        view.message = status

    def _build_report_pages(self, report: "SimulationReport") -> list[discord.Embed]:
        raw: list[discord.Embed] = []
        raw.append(self._page_prediction(report))
        raw.append(self._page_model_edge(report))
        if report.v2:
            raw.append(self._page_squad_quality(report))
            raw.append(self._page_player_battles(report))
        if report.v3:
            raw.append(self._page_dynamic_state(report))
        if report.v4:
            raw.append(self._page_tactical_identity(report))
            raw.append(self._page_tactical_battles(report))
        if report.version == "v5":
            raw.append(self._page_match_flow(report))
        if report.has_v51_data:
            if report.v51 and report.v51.player_influence:
                raw.append(self._page_player_influence(report))
            if report.v51 and report.v51.tactical_exploitation:
                raw.append(self._page_tactical_vulnerabilities(report))
            if report.v51 and report.v51.match_archetypes:
                raw.append(self._page_match_archetype(report))
            if report.v51 and report.v51.market_comparison:
                raw.append(self._page_market_comparison(report))
            if report.v51 and report.v51.model_confidence:
                raw.append(self._page_model_confidence(report))
        raw.append(self._page_simulation_insights(report))

        total = len(raw)
        for i, embed in enumerate(raw):
            embed.title = f"{i+1}/{total} {embed.title}"
        return raw

    def _page_header(self, report: "SimulationReport", title: str) -> discord.Embed:
        embed = discord.Embed(title=title, color=0xff3fb9)
        embed.set_author(name=f"{report.flag_a} {report.team_a} vs {report.flag_b} {report.team_b}")
        return embed

    def _page_prediction(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Match Prediction")
        mc = report.mc
        embed.add_field(
            name=f"{report.flag_a} {report.team_a} vs {report.flag_b} {report.team_b}",
            value=f"`{'Knockout' if report.knockout else 'Group Stage'}` | {report.simulations:,} simulations",
            inline=False,
        )
        bar_len = 12
        w1_bar = "█" * max(1, round(mc.win_prob_a / 100 * bar_len)) if mc.win_prob_a > 0 else ""
        w2_bar = "█" * max(1, round(mc.win_prob_b / 100 * bar_len)) if mc.win_prob_b > 0 else ""
        d_bar = "█" * max(1, round(mc.draw_prob / 100 * bar_len)) if mc.draw_prob > 0 else ""
        embed.add_field(
            name="📊 Match Outcome",
            value=(
                f"**{report.flag_a} {report.team_a}**  {mc.win_prob_a:.1f}%\n`{w1_bar:<{bar_len}}` {mc.wins_a:,}\n"
                f"**Draw**          {mc.draw_prob:.1f}%\n`{d_bar:<{bar_len}}` {mc.draws:,}\n"
                f"**{report.flag_b} {report.team_b}**  {mc.win_prob_b:.1f}%\n`{w2_bar:<{bar_len}}` {mc.wins_b:,}"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚽ Expected Goals (avg)",
            value=f"{report.flag_a} {report.team_a}: **{mc.avg_xg_a:.3f}**\n{report.flag_b} {report.team_b}: **{mc.avg_xg_b:.3f}**",
            inline=True,
        )
        embed.add_field(
            name="🏆 Most Common Scorelines",
            value="\n".join(
                f"{report.flag_a} {s[0]}-{s[1]} {report.flag_b}  — {c:,}× ({c/mc.total*100:.1f}%)"
                for s, c in mc.top_scores[:5]
            ) or "N/A",
            inline=True,
        )
        embed.set_footer(text=f"Model: {report.version.upper()} | {report.version_label}")
        return embed

    def _page_model_edge(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Model Edge")

        if report.v1:
            v1 = report.v1
            embed.add_field(name="📈 ELO Rating", value=f"{report.flag_a} {report.team_a}: **{v1.elo_a:.0f}**\n{report.flag_b} {report.team_b}: **{v1.elo_b:.0f}**\nDiff: `{v1.elo_diff:+.0f}`", inline=True)
            embed.add_field(name="📊 PELE Rating", value=f"{report.flag_a} {report.team_a}: **{v1.pele_a:.0f}**\n{report.flag_b} {report.team_b}: **{v1.pele_b:.0f}**\nDiff: `{v1.pele_diff:+.0f}`", inline=True)
            embed.add_field(name="🎯 Combined Rating", value=f"{report.flag_a} {report.team_a}: **{v1.combined_a:.0f}**\n{report.flag_b} {report.team_b}: **{v1.combined_b:.0f}**\nDiff: `{v1.combined_diff:+.0f}`", inline=True)
            embed.add_field(name="⚡ Upset Factor", value=f"`{v1.upset_factor:.2f}` (1.0 = even, <1 = {report.team_b} favored, >1 = {report.team_a} favored)", inline=False)
            embed.set_footer(text=f"Model: {report.version.upper()} | Base goals: 1.1/match")
            return embed

        if report.v4:
            v4 = report.v4
            adj_line_a = f"Base: {v4.base_xg_a:.3f} → Final: **{v4.final_xg_a:.3f}** ({v4.xg_shift_a:+.3f})"
            adj_line_b = f"Base: {v4.base_xg_b:.3f} → Final: **{v4.final_xg_b:.3f}** ({v4.xg_shift_b:+.3f})"
            plans_line = f"{report.flag_a} **{v4.game_plan_a}** vs {report.flag_b} **{v4.game_plan_b}**"
            embed.add_field(name="🧮 xG Adjustment", value=adj_line_a + "\n" + adj_line_b, inline=False)
            embed.add_field(name="🧠 Game Plans", value=plans_line, inline=False)
            embed.add_field(name="📉 Total Adjustment", value=f"{report.flag_a}: `{v4.total_adjustment_a:+.4f}` xG\n{report.flag_b}: `{v4.total_adjustment_b:+.4f}` xG", inline=False)

        if report.v2:
            v2 = report.v2
            a_line = f"{report.flag_a} {report.team_a}: A={v2.attack_a:.1f} M={v2.midfield_a:.1f} D={v2.defense_a:.1f} GK={v2.goalkeeper_a:.1f}"
            b_line = f"{report.flag_b} {report.team_b}: A={v2.attack_b:.1f} M={v2.midfield_b:.1f} D={v2.defense_b:.1f} GK={v2.goalkeeper_b:.1f}"
            embed.add_field(name="⭐ Squad Ratings", value=a_line + "\n" + b_line, inline=False)

        if report.v3:
            v3 = report.v3
            dyn_a = v3.combined_mult_a
            dyn_b = v3.combined_mult_b
            embed.add_field(name="🔄 Dynamic Multiplier", value=f"{report.flag_a} {report.team_a}: **{dyn_a:.4f}×** ({v3.net_dynamic_a:+.2%})\n{report.flag_b} {report.team_b}: **{dyn_b:.4f}×** ({v3.net_dynamic_b:+.2%})", inline=False)
            if report.v1 is None and not report.v4:
                lines_a = []
                lines_b = []
                for c in v3.components:
                    lines_a.append(f"{c.name}: {c.value_a:+.2%}")
                    lines_b.append(f"{c.name}: {c.value_b:+.2%}")
                embed.add_field(name=f"{report.flag_a} {report.team_a} Components", value="\n".join(lines_a) or "None", inline=True)
                embed.add_field(name=f"{report.flag_b} {report.team_b} Components", value="\n".join(lines_b) or "None", inline=True)

        if not embed.fields:
            embed.description = f"{report.flag_a} {report.team_a} vs {report.flag_b} {report.team_b} — No additional model edge data available"

        embed.set_footer(text=f"Model: {report.version.upper()} | {report.version_label}")
        return embed

    def _page_squad_quality(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Squad Quality")
        if not report.v2:
            embed.description = "Squad data not available for this version"
            return embed
        v2 = report.v2

        def fmt_xi(ratings, names, formation):
            by_pos = {"GK": [], "DEF": [], "MID": [], "AT": []}
            for rr in ratings:
                if rr.role == "GK":
                    by_pos["GK"].append(f"{rr.player_name} ({rr.rating:.1f})")
                elif rr.role in ("CB", "FB"):
                    by_pos["DEF"].append(f"{rr.player_name} ({rr.rating:.1f})")
                elif rr.role in ("CM", "DM"):
                    by_pos["MID"].append(f"{rr.player_name} ({rr.rating:.1f})")
                else:
                    by_pos["AT"].append(f"{rr.player_name} ({rr.rating:.1f})")
            lines = [f"Formation: {formation}"]
            for label, key in [("GK", "GK"), ("Defense", "DEF"), ("Midfield", "MID"), ("Attack", "AT")]:
                if by_pos[key]:
                    lines.append(f"\n{label}:")
                    lines.extend(f"  {p}" for p in by_pos[key])
            return "\n".join(lines)

        sorted_a = sorted(v2.role_ratings_a, key=lambda r: r.rating, reverse=True)
        sorted_b = sorted(v2.role_ratings_b, key=lambda r: r.rating, reverse=True)
        best_a = "\n".join(f"{r.player_name} ({r.role}): {r.rating:.1f}" for r in sorted_a[:3])
        worst_a = "\n".join(f"{r.player_name} ({r.role}): {r.rating:.1f}" for r in sorted_a[-3:])
        best_b = "\n".join(f"{r.player_name} ({r.role}): {r.rating:.1f}" for r in sorted_b[:3])
        worst_b = "\n".join(f"{r.player_name} ({r.role}): {r.rating:.1f}" for r in sorted_b[-3:])

        embed.add_field(name=f"{report.flag_a} {report.team_a} — Starting XI", value=fmt_xi(v2.role_ratings_a, v2.xi_names_a, v2.formation_a), inline=True)
        embed.add_field(name=f"{report.flag_b} {report.team_b} — Starting XI", value=fmt_xi(v2.role_ratings_b, v2.xi_names_b, v2.formation_b), inline=True)
        embed.add_field(name=f"⭐ Best {report.team_a}", value=best_a or "N/A", inline=True)
        embed.add_field(name=f"⚠️ Weakest {report.team_a}", value=worst_a or "N/A", inline=True)
        embed.add_field(name=f"⭐ Best {report.team_b}", value=best_b or "N/A", inline=True)
        embed.add_field(name=f"⚠️ Weakest {report.team_b}", value=worst_b or "N/A", inline=True)
        return embed

    def _page_player_battles(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Player Battles")
        if not report.v2:
            embed.description = "Squad data not available for this version"
            return embed
        v2 = report.v2

        def best_at(ratings, roles):
            candidates = [r for r in ratings if r.role in roles]
            return max(candidates, key=lambda r: r.rating) if candidates else None

        duels = [
            ("🥅 Goalkeepers", ["GK"], ["GK"]),
            ("🛡️ ST vs CBs", ["ST"], ["CB"]),
            ("🏃 Wingers vs FBs", ["WINGER"], ["FB"]),
            ("⚔️ Midfield Battle", ["CM", "DM"], ["CM", "DM"]),
        ]
        for title, roles_a, roles_b in duels:
            pa = best_at(v2.role_ratings_a, set(roles_a))
            pb = best_at(v2.role_ratings_b, set(roles_b))
            line_a = f"{pa.player_name} ({pa.rating:.1f})" if pa else "N/A"
            line_b = f"{pb.player_name} ({pb.rating:.1f})" if pb else "N/A"
            diff = (pa.rating if pa else 70) - (pb.rating if pb else 70)
            edge = f"{report.flag_a} +{diff:.1f}" if diff > 0 else (f"{report.flag_b} +{-diff:.1f}" if diff < 0 else "Even")
            embed.add_field(name=title, value=f"{report.flag_a}: {line_a}\n{report.flag_b}: {line_b}\nEdge: {edge}", inline=True)

        embed.set_footer(text=f"Model: {report.version.upper()} | Ratings based on position formulas")
        return embed

    def _page_dynamic_state(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Dynamic State")
        if not report.v3:
            embed.description = "Dynamic state not available for this version"
            return embed
        v3 = report.v3

        for c in v3.components:
            emoji_map = {
                "chemistry": "🧪", "experience": "🎓", "form": "🔥",
                "momentum": "📈", "continuity": "🔗", "leadership": "👑",
            }
            emoji = emoji_map.get(c.name, "•")
            a_val = f"{c.value_a:+.2%}" if c.value_a != 0 else "0%"
            b_val = f"{c.value_b:+.2%}" if c.value_b != 0 else "0%"
            diff = (c.value_a - c.value_b)
            edge = f"({report.flag_a} edge: {diff:+.2%})" if abs(diff) > 0.001 else "(even)"
            embed.add_field(
                name=f"{emoji} {c.name.title()}",
                value=f"{report.flag_a}: `{a_val}` {c.source_a[:50]}\n{report.flag_b}: `{b_val}` {c.source_b[:50]}\n{edge}",
                inline=False,
            )

        embed.add_field(
            name="📊 Combined Effect",
            value=f"{report.flag_a} {report.team_a}: **{v3.combined_mult_a:.4f}×** ({v3.net_dynamic_a:+.2%})\n"
                   f"{report.flag_b} {report.team_b}: **{v3.combined_mult_b:.4f}×** ({v3.net_dynamic_b:+.2%})\n"
                   f"Nat'l modifiers: {report.flag_a} `{v3.nationality_modifier_a:+.3f}` vs {report.flag_b} `{v3.nationality_modifier_b:+.3f}`",
            inline=False,
        )
        embed.set_footer(text=f"Model: {report.version.upper()} | Range: 0.90×–1.10×")
        return embed

    def _page_tactical_identity(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Tactical Identity")
        if not report.v4:
            embed.description = "Tactical data only available for V4"
            return embed
        v4 = report.v4
        v2 = report.v2

        embed.add_field(
            name=f"{report.flag_a} {report.team_a}",
            value=f"**Formation:** {v2.formation_a if v2 else 'N/A'}\n"
                   f"**Manager:** {v4.manager_a}\n"
                   f"**Game Plan:** {v4.game_plan_a}\n"
                   f"**Role:** {'Favorite' if v4.final_xg_a >= v4.final_xg_b else 'Underdog'}",
            inline=True,
        )
        embed.add_field(
            name=f"{report.flag_b} {report.team_b}",
            value=f"**Formation:** {v2.formation_b if v2 else 'N/A'}\n"
                   f"**Manager:** {v4.manager_b}\n"
                   f"**Game Plan:** {v4.game_plan_b}\n"
                   f"**Role:** {'Favorite' if v4.final_xg_b >= v4.final_xg_a else 'Underdog'}",
            inline=True,
        )
        embed.set_footer(text="Game plan chosen based on relative strength, context, and tactics")
        return embed

    def _page_tactical_battles(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Tactical Battles")
        if not report.v4:
            embed.description = "Tactical data only available for V4"
            return embed
        v4 = report.v4

        if v4.advantages_a:
            embed.add_field(
                name=f"{report.flag_a} {report.team_a} Advantages",
                value="\n".join(f"• {a}" for a in v4.advantages_a[:5]) or "None",
                inline=True,
            )
        if v4.advantages_b:
            embed.add_field(
                name=f"{report.flag_b} {report.team_b} Advantages",
                value="\n".join(f"• {a}" for a in v4.advantages_b[:5]) or "None",
                inline=True,
            )

        if v4.adjustments_a:
            adj_lines_a = [f"{a.category}: {a.description[:50]} ({a.value:+.4f})" for a in v4.adjustments_a[:5]]
            embed.add_field(name=f"{report.flag_a} Key Adjustments", value="\n".join(adj_lines_a) or "None", inline=False)
        if v4.adjustments_b:
            adj_lines_b = [f"{a.category}: {a.description[:50]} ({a.value:+.4f})" for a in v4.adjustments_b[:5]]
            embed.add_field(name=f"{report.flag_b} Key Adjustments", value="\n".join(adj_lines_b) or "None", inline=False)

        embed.add_field(
            name="📊 Net xG Effect",
            value=f"{report.flag_a}: `{v4.total_adjustment_a:+.4f}` → **{v4.final_xg_a:.3f}**\n"
                   f"{report.flag_b}: `{v4.total_adjustment_b:+.4f}` → **{v4.final_xg_b:.3f}**",
            inline=False,
        )
        embed.set_footer(text="Adjustments capped at ±10% of base xG per team")
        return embed

    def _page_match_flow(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Match Flow (Sample)")
        if report.version != "v5":
            embed.description = "Match flow data only available for V5"
            return embed
        embed.description = "One sample match from the Monte Carlo simulation."
        embed.add_field(name="⚙️ Features", value=(
            "• **8-phase simulation** (6 regular + 2 extra time)\n"
            "• Player fatigue system per 15-min phase\n"
            "• Yellow/red cards with attribute-driven probability\n"
            "• Substitution AI based on energy, cards, and rating\n"
            "• In-match momentum (goals, cards, chances trigger shifts)\n"
            "• Scoreline intelligence (trailing teams attack more)\n"
            "• Manager reactions (game plan changes)\n"
            "• Penalty shootout support"
        ), inline=False)
        embed.add_field(name="📊 Event Pipeline", value=(
            "Possession → Attacks → Dangerous Attacks → Shots → "
            "Shots on Target → Big Chances → Goals"
        ), inline=False)
        embed.set_footer(text=f"Model: {report.version.upper()} | Each match unfolds minute-by-minute")
        return embed

    def _page_player_influence(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Player Influence (V5.1)")
        v51 = report.v51
        if not v51 or not v51.player_influence:
            embed.description = "Player influence data not available."
            return embed
        pi = v51.player_influence

        top_a = pi.get("top_attackers_a", [])
        top_b = pi.get("top_attackers_b", [])
        if top_a and top_b:
            val_a = "\n".join(f"{p['name']} ({p['role']}): {p['influence']}" for p in top_a[:3])
            val_b = "\n".join(f"{p['name']} ({p['role']}): {p['influence']}" for p in top_b[:3])
            embed.add_field(name=f"⚔️ Top Attackers: {report.flag_a} {report.team_a}",
                            value=f"```{val_a}```", inline=True)
            embed.add_field(name=f"⚔️ Top Attackers: {report.flag_b} {report.team_b}",
                            value=f"```{val_b}```", inline=True)

        dep_a = pi.get("dependency_a")
        dep_b = pi.get("dependency_b")
        if dep_a and dep_b:
            embed.add_field(name="🎯 Dependency",
                            value=f"{report.flag_a}: **{dep_a['dependency_level']}** ({dep_a['attack_output_share']}% top 3)\n"
                                  f"{report.flag_b}: **{dep_b['dependency_level']}** ({dep_b['attack_output_share']}% top 3)",
                            inline=False)

        matchups = pi.get("matchups", [])
        if matchups:
            lines = []
            for m in matchups[:4]:
                arrow = "→" if m["advantage_team"] == m["player_a"].split(" ")[0] else "←"
                lines.append(f"**{m['category']}**: {m['player_a']} {arrow} {m['player_b']} ({m['advantage_team']})")
            embed.add_field(name="🔗 Key Matchups", value="\n".join(lines), inline=False)

        gk_a = pi.get("gk_a")
        gk_b = pi.get("gk_b")
        if gk_a and gk_b:
            embed.add_field(name="🧤 Goalkeepers",
                            value=f"{report.flag_a}: {gk_a['player_name']} ({gk_a['overall_influence']}/10)\n"
                                  f"{report.flag_b}: {gk_b['player_name']} ({gk_b['overall_influence']}/10)",
                            inline=False)

        embed.set_footer(text="V5.1 Explainability: Player-level attribution")
        return embed

    def _page_tactical_vulnerabilities(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Tactical Exploitation (V5.1)")
        v51 = report.v51
        if not v51 or not v51.tactical_exploitation:
            embed.description = "Tactical vulnerability data not available."
            return embed
        te = v51.tactical_exploitation

        opportunities = te.get("opportunities", [])
        if not opportunities:
            embed.description = "No significant exploitation opportunities found."
            return embed

        lines = []
        for opp in opportunities[:5]:
            lines.append(f"**{opp['attacker']}** → **{opp['defender']}**: {opp['description']} "
                         f"(+{opp['xg_impact']:.3f} xG)")
        embed.description = "\n".join(lines)

        embed.set_footer(text="V5.1 Explainability: Strength vs Weakness exploitation analysis")
        return embed

    def _page_match_archetype(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Match Archetype (V5.1)")
        v51 = report.v51
        if not v51 or not v51.match_archetypes:
            embed.description = "Match archetype data not available."
            return embed
        arch = v51.match_archetypes

        archetypes = arch.get("archetypes", [])
        if not archetypes:
            embed.description = "No archetype classification available."
            return embed

        lines = []
        for a in archetypes:
            bar = "█" * max(1, round(a["prob"] / 10))
            lines.append(f"**{a['name']}**: {a['prob']:.1f}%\n`{bar}`\n_{a.get('desc', '')}_")
        embed.description = "\n".join(lines)

        wc_a = v51.win_conditions_a or {}
        wc_b = v51.win_conditions_b or {}
        conds_a = wc_a.get("conditions", [])
        conds_b = wc_b.get("conditions", [])
        if conds_a:
            embed.add_field(name=f"🏆 {report.team_a} Win Conditions",
                            value="\n".join(f"**{c['method']}**: {c['prob']:.1f}% — {c.get('desc', '')}"
                                            for c in conds_a[:3]),
                            inline=True)
        if conds_b:
            embed.add_field(name=f"🏆 {report.team_b} Win Conditions",
                            value="\n".join(f"**{c['method']}**: {c['prob']:.1f}% — {c.get('desc', '')}"
                                            for c in conds_b[:3]),
                            inline=True)

        embed.set_footer(text="V5.1 Explainability: Archetype classification & win conditions")
        return embed

    def _page_market_comparison(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Market Comparison (V5.1)")
        v51 = report.v51
        if not v51 or not v51.market_comparison:
            embed.description = "Market comparison data not available."
            return embed
        mc_dict = v51.market_comparison

        entries = mc_dict.get("entries", [])
        if entries:
            lines = []
            for e in entries:
                emoji = "🟢" if e["edge"] > 0.03 else "🟡" if e["edge"] > 0 else "🔴"
                lines.append(f"{emoji} **{e['team']}**: Model {e['model_prob']:.1f}% vs Market {e['market_prob']:.1f}% "
                             f"(Edge: {e['edge']:+.1%}) [{e.get('value_level', '')}]")
            embed.description = "\n".join(lines)

        market = mc_dict.get("market")
        if market and market.get("home_prob") is not None:
            embed.add_field(name="📊 Normalized Market",
                            value=f"Home: {market['home_prob']:.1f}% | Draw: {market['draw_prob']:.1f}% | Away: {market['away_prob']:.1f}%",
                            inline=False)

        consensus = mc_dict.get("consensus")
        if consensus:
            embed.add_field(name="🤝 Market Consensus",
                            value=f"Home: **{consensus['home_consensus']}** ({consensus['home_range'][0]:.1f}–{consensus['home_range'][1]:.1f}%)\n"
                                  f"Draw: **{consensus['draw_consensus']}** ({consensus['draw_range'][0]:.1f}–{consensus['draw_range'][1]:.1f}%)\n"
                                  f"Away: **{consensus['away_consensus']}** ({consensus['away_range'][0]:.1f}–{consensus['away_range'][1]:.1f}%)\n"
                                  f"Sources: {consensus['market_count']}",
                            inline=False)

        embed.set_footer(text="V5.1 Explainability: Model vs Market odds comparison")
        return embed

    def _page_model_confidence(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Model Confidence (V5.1)")
        v51 = report.v51
        if not v51 or not v51.model_confidence:
            embed.description = "Model confidence data not available."
            return embed
        conf = v51.model_confidence

        score = conf.get("score", 0)
        level = conf.get("level", "Unknown")
        colors = {"Very High": 0x00ff00, "High": 0x88ff00, "Moderate": 0xffaa00,
                  "Low": 0xff6600, "Very Low": 0xff0000}
        embed.color = colors.get(level, 0xff3fb9)
        bar_len = 14
        filled = round(score / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        embed.description = f"**{level}** (Score: {score:.1f}/100)\n`{bar}`"

        factors = conf.get("factors", [])
        if factors:
            lines = []
            for f in factors:
                f_bar = "█" * max(1, round(f["score"] / 100 * 10))
                lines.append(f"**{f['name']}**: {f['score']:.0f}/100 `{f_bar:<10}` (weight: {f['weight']:.0%})")
            embed.add_field(name="📈 Confidence Factors", value="\n".join(lines), inline=False)

        upset = conf.get("upset_probability", 0)
        volatility = conf.get("volatility", 0)
        embed.add_field(name="⚡ Risk Metrics",
                        value=f"Upset Probability: **{upset:.1f}%**\nVolatility: **{volatility:.1f}/100**",
                        inline=False)

        embed.set_footer(text="V5.1 Explainability: Multi-factor prediction confidence")
        return embed

    def _page_simulation_insights(self, report: "SimulationReport") -> discord.Embed:
        embed = self._page_header(report, "Simulation Insights")
        mc = report.mc

        embed.add_field(name="📉 Goal Extremes", value=f"{report.flag_a}: {mc.min_goals_a}–{mc.max_goals_a} goals\n{report.flag_b}: {mc.min_goals_b}–{mc.max_goals_b} goals", inline=True)

        upset_prob = 0.0
        if mc.wins_a > 0 and mc.avg_xg_b > mc.avg_xg_a:
            upset_prob = mc.wins_a / mc.total * 100
        elif mc.wins_b > 0 and mc.avg_xg_a > mc.avg_xg_b:
            upset_prob = mc.wins_b / mc.total * 100
        embed.add_field(name="⚡ Upset Probability", value=f"**{upset_prob:.1f}%**" if upset_prob > 0 else "No upset detected", inline=True)

        eta_val = max(mc.avg_xg_a, mc.avg_xg_b) / max(min(mc.avg_xg_a, mc.avg_xg_b), 0.001)
        favored = report.flag_a if mc.avg_xg_a >= mc.avg_xg_b else report.flag_b
        embed.add_field(name="📊 xG Ratio", value=f"**{eta_val:.2f}×** ({favored} favored)", inline=True)

        embed.add_field(name="🔬 Methodology", value=f"**{report.version_label}**\n{report.simulations:,} Monte Carlo simulations\n{'🏟️ Knockout tiebreaker rules' if report.knockout else '📊 Group stage rules'}", inline=False)

        embed.set_footer(text=f"Data confidence increases with simulation count (recommend 1,000+)")
        return embed



    def _run_monte_carlo(
        self, version: str, team_a: str, team_b: str,
        knockout: bool, simulations: int,
    ) -> "SimulationReport":
        from fifa_data.engines.v1_elo_engine import V1EloMatchEngine
        from fifa_data.engines.v2_player_engine import V2PlayerMatchEngine
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
        from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
        from fifa_data.services.simulation_report import (
            SimulationReport, MonteCarloResult, V1ReportData, V2ReportData,
            V3ReportData, V4ReportData, V3ComponentData, RoleRatingData,
            TacticalAdjustmentData, V51ReportData,
        )

        fifa_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fifa_data")
        report = SimulationReport(version=version, team_a=team_a, team_b=team_b, knockout=knockout, simulations=simulations)

        # === Pre-match analysis: capture engine state before any simulations ===
        if version == "v1":
            from fifa_data.services.simulation_service import TEAM_METRICS
            engine = V1EloMatchEngine(TEAM_METRICS)
            r_a = engine.get_team_ratings(team_a)
            r_b = engine.get_team_ratings(team_b)
            raw_delta = r_a["combined"] - r_b["combined"]
            upset = max(0.4, min(1.6, 1.0 + (raw_delta / 800.0)))
            report.v1 = V1ReportData(
                elo_a=r_a["elo"], elo_b=r_b["elo"],
                pele_a=r_a["pele"], pele_b=r_b["pele"],
                combined_a=r_a["combined"], combined_b=r_b["combined"],
                upset_factor=upset,
            )

        elif version == "v2":
            engine = V2PlayerMatchEngine(data_dir=fifa_dir)
            sa = engine.get_team_strength(team_a)
            sb = engine.get_team_strength(team_b)
            report.v2 = V2ReportData(
                role_ratings_a=[RoleRatingData(r.player_name, r.role, r.rating) for r in sa.role_ratings],
                role_ratings_b=[RoleRatingData(r.player_name, r.role, r.rating) for r in sb.role_ratings],
                attack_a=sa.attack_rating, midfield_a=sa.midfield_rating,
                defense_a=sa.defense_rating, goalkeeper_a=sa.goalkeeper_rating,
                attack_b=sb.attack_rating, midfield_b=sb.midfield_rating,
                defense_b=sb.defense_rating, goalkeeper_b=sb.goalkeeper_rating,
                formation_a=sa.formation, formation_b=sb.formation,
                xi_names_a=[p.name for p in engine.squads[team_a].current_starting_xi],
                xi_names_b=[p.name for p in engine.squads[team_b].current_starting_xi],
            )

        elif version == "v3":
            engine = V3DynamicEngine(data_dir=fifa_dir)
            sa = engine.get_team_strength(team_a, is_knockout=knockout)
            sb = engine.get_team_strength(team_b, is_knockout=knockout)
            da = engine.get_dynamic_state(team_a, is_knockout=knockout)
            db = engine.get_dynamic_state(team_b, is_knockout=knockout)
            report.v2 = V2ReportData(
                role_ratings_a=[RoleRatingData(r.player_name, r.role, r.rating) for r in sa.role_ratings],
                role_ratings_b=[RoleRatingData(r.player_name, r.role, r.rating) for r in sb.role_ratings],
                attack_a=sa.attack_rating, midfield_a=sa.midfield_rating,
                defense_a=sa.defense_rating, goalkeeper_a=sa.goalkeeper_rating,
                attack_b=sb.attack_rating, midfield_b=sb.midfield_rating,
                defense_b=sb.defense_rating, goalkeeper_b=sb.goalkeeper_rating,
                formation_a=sa.formation, formation_b=sb.formation,
                xi_names_a=[p.name for p in engine.squads[team_a].current_starting_xi],
                xi_names_b=[p.name for p in engine.squads[team_b].current_starting_xi],
            )
            components = []
            for cn in ["chemistry", "experience", "form", "momentum", "continuity", "leadership"]:
                ca = next(c for c in da.components() if c.component == cn)
                cb = next(c for c in db.components() if c.component == cn)
                components.append(V3ComponentData(cn, ca.value, cb.value, ca.source, cb.source, ca.confidence, cb.confidence))
            form_a = [{"name": p.name, "form": (p.stats.get("form", 0) if isinstance(p.stats, dict) else 0)} for p in engine.squads[team_a].current_starting_xi]
            form_b = [{"name": p.name, "form": (p.stats.get("form", 0) if isinstance(p.stats, dict) else 0)} for p in engine.squads[team_b].current_starting_xi]
            report.v3 = V3ReportData(
                components=components,
                combined_mult_a=da.combined_multiplier(),
                combined_mult_b=db.combined_multiplier(),
                form_details_a=form_a, form_details_b=form_b,
                experience_details_a=engine.experience_service.get_player_details(engine.squads[team_a].current_starting_xi),
                experience_details_b=engine.experience_service.get_player_details(engine.squads[team_b].current_starting_xi),
                leadership_a=engine.leadership_service.get_leadership_details(engine.squads[team_a].current_starting_xi),
                leadership_b=engine.leadership_service.get_leadership_details(engine.squads[team_b].current_starting_xi),
                chemistry_a=engine.chemistry_service.get_club_groupings(team_a, engine.squads[team_a].current_starting_xi, engine.squads[team_a].formation),
                chemistry_b=engine.chemistry_service.get_club_groupings(team_b, engine.squads[team_b].current_starting_xi, engine.squads[team_b].formation),
                nationality_modifier_a=engine.national_modifiers.get(team_a, 0.0),
                nationality_modifier_b=engine.national_modifiers.get(team_b, 0.0),
            )

        elif version == "v4":
            engine = V4TacticalEngine(data_dir=fifa_dir)
            v3 = engine._v3
            sa = v3.get_team_strength(team_a, is_knockout=knockout)
            sb = v3.get_team_strength(team_b, is_knockout=knockout)
            da = v3.get_dynamic_state(team_a, is_knockout=knockout)
            db = v3.get_dynamic_state(team_b, is_knockout=knockout)
            report.v2 = V2ReportData(
                role_ratings_a=[RoleRatingData(r.player_name, r.role, r.rating) for r in sa.role_ratings],
                role_ratings_b=[RoleRatingData(r.player_name, r.role, r.rating) for r in sb.role_ratings],
                attack_a=sa.attack_rating, midfield_a=sa.midfield_rating,
                defense_a=sa.defense_rating, goalkeeper_a=sa.goalkeeper_rating,
                attack_b=sb.attack_rating, midfield_b=sb.midfield_rating,
                defense_b=sb.defense_rating, goalkeeper_b=sb.goalkeeper_rating,
                formation_a=sa.formation, formation_b=sb.formation,
                xi_names_a=[p.name for p in engine.squads[team_a].current_starting_xi],
                xi_names_b=[p.name for p in engine.squads[team_b].current_starting_xi],
            )
            components = []
            for cn in ["chemistry", "experience", "form", "momentum", "continuity", "leadership"]:
                ca = next(c for c in da.components() if c.component == cn)
                cb = next(c for c in db.components() if c.component == cn)
                components.append(V3ComponentData(cn, ca.value, cb.value, ca.source, cb.source, ca.confidence, cb.confidence))
            form_a = [{"name": p.name, "form": (p.stats.get("form", 0) if isinstance(p.stats, dict) else 0)} for p in engine.squads[team_a].current_starting_xi]
            form_b = [{"name": p.name, "form": (p.stats.get("form", 0) if isinstance(p.stats, dict) else 0)} for p in engine.squads[team_b].current_starting_xi]
            report.v3 = V3ReportData(
                components=components,
                combined_mult_a=da.combined_multiplier(),
                combined_mult_b=db.combined_multiplier(),
                form_details_a=form_a, form_details_b=form_b,
                experience_details_a=v3.experience_service.get_player_details(engine.squads[team_a].current_starting_xi),
                experience_details_b=v3.experience_service.get_player_details(engine.squads[team_b].current_starting_xi),
                leadership_a=v3.leadership_service.get_leadership_details(engine.squads[team_a].current_starting_xi),
                leadership_b=v3.leadership_service.get_leadership_details(engine.squads[team_b].current_starting_xi),
                chemistry_a=v3.chemistry_service.get_club_groupings(team_a, engine.squads[team_a].current_starting_xi, engine.squads[team_a].formation),
                chemistry_b=v3.chemistry_service.get_club_groupings(team_b, engine.squads[team_b].current_starting_xi, engine.squads[team_b].formation),
                nationality_modifier_a=v3.national_modifiers.get(team_a, 0.0),
                nationality_modifier_b=v3.national_modifiers.get(team_b, 0.0),
            )
            context = "knockout" if knockout else "group"
            from fifa_data.services.tactical_analysis import compute_tactical_matchup
            from fifa_data.services.manager_service import get_manager
            base_l1, base_l2 = v3.expected_goals(sa, sb)
            tactical = compute_tactical_matchup(
                team_a, team_b, base_l1, base_l2,
                engine.squads[team_a], engine.squads[team_b], context=context,
            )
            mgr_a = get_manager(team_a)
            mgr_b = get_manager(team_b)
            report.v4 = V4ReportData(
                base_xg_a=tactical.base_xg_a, base_xg_b=tactical.base_xg_b,
                final_xg_a=tactical.final_xg_a, final_xg_b=tactical.final_xg_b,
                game_plan_a=tactical.game_plan_a, game_plan_b=tactical.game_plan_b,
                advantages_a=list(tactical.advantages_a), advantages_b=list(tactical.advantages_b),
                adjustments_a=[TacticalAdjustmentData(a.category, a.description, a.value, a.confidence) for a in tactical.adjustments_a],
                adjustments_b=[TacticalAdjustmentData(a.category, a.description, a.value, a.confidence) for a in tactical.adjustments_b],
                manager_a=mgr_a.name if mgr_a else "Unknown",
                manager_b=mgr_b.name if mgr_b else "Unknown",
            )

        else:  # v5
            engine = V5MatchStateEngine(data_dir=fifa_dir)
            v4 = engine._v4
            v3 = v4._v3
            sa = v3.get_team_strength(team_a, is_knockout=knockout)
            sb = v3.get_team_strength(team_b, is_knockout=knockout)
            da = v3.get_dynamic_state(team_a, is_knockout=knockout)
            db = v3.get_dynamic_state(team_b, is_knockout=knockout)
            report.v2 = V2ReportData(
                role_ratings_a=[RoleRatingData(r.player_name, r.role, r.rating) for r in sa.role_ratings],
                role_ratings_b=[RoleRatingData(r.player_name, r.role, r.rating) for r in sb.role_ratings],
                attack_a=sa.attack_rating, midfield_a=sa.midfield_rating,
                defense_a=sa.defense_rating, goalkeeper_a=sa.goalkeeper_rating,
                attack_b=sb.attack_rating, midfield_b=sb.midfield_rating,
                defense_b=sb.defense_rating, goalkeeper_b=sb.goalkeeper_rating,
                formation_a=sa.formation, formation_b=sb.formation,
                xi_names_a=[p.name for p in engine.squads[team_a].current_starting_xi],
                xi_names_b=[p.name for p in engine.squads[team_b].current_starting_xi],
            )
            components = []
            for cn in ["chemistry", "experience", "form", "momentum", "continuity", "leadership"]:
                ca = next(c for c in da.components() if c.component == cn)
                cb = next(c for c in db.components() if c.component == cn)
                components.append(V3ComponentData(cn, ca.value, cb.value, ca.source, cb.source, ca.confidence, cb.confidence))
            form_a = [{"name": p.name, "form": (p.stats.get("form", 0) if isinstance(p.stats, dict) else 0)} for p in engine.squads[team_a].current_starting_xi]
            form_b = [{"name": p.name, "form": (p.stats.get("form", 0) if isinstance(p.stats, dict) else 0)} for p in engine.squads[team_b].current_starting_xi]
            report.v3 = V3ReportData(
                components=components,
                combined_mult_a=da.combined_multiplier(),
                combined_mult_b=db.combined_multiplier(),
                form_details_a=form_a, form_details_b=form_b,
                experience_details_a=v3.experience_service.get_player_details(engine.squads[team_a].current_starting_xi),
                experience_details_b=v3.experience_service.get_player_details(engine.squads[team_b].current_starting_xi),
                leadership_a=v3.leadership_service.get_leadership_details(engine.squads[team_a].current_starting_xi),
                leadership_b=v3.leadership_service.get_leadership_details(engine.squads[team_b].current_starting_xi),
                chemistry_a=v3.chemistry_service.get_club_groupings(team_a, engine.squads[team_a].current_starting_xi, engine.squads[team_a].formation),
                chemistry_b=v3.chemistry_service.get_club_groupings(team_b, engine.squads[team_b].current_starting_xi, engine.squads[team_b].formation),
                nationality_modifier_a=v3.national_modifiers.get(team_a, 0.0),
                nationality_modifier_b=v3.national_modifiers.get(team_b, 0.0),
            )
            context = "knockout" if knockout else "group"
            from fifa_data.services.tactical_analysis import compute_tactical_matchup
            from fifa_data.services.manager_service import get_manager
            base_l1, base_l2 = v3.expected_goals(sa, sb)
            tactical = compute_tactical_matchup(
                team_a, team_b, base_l1, base_l2,
                engine.squads[team_a], engine.squads[team_b], context=context,
            )
            mgr_a = get_manager(team_a)
            mgr_b = get_manager(team_b)
            report.v4 = V4ReportData(
                base_xg_a=tactical.base_xg_a, base_xg_b=tactical.base_xg_b,
                final_xg_a=tactical.final_xg_a, final_xg_b=tactical.final_xg_b,
                game_plan_a=tactical.game_plan_a, game_plan_b=tactical.game_plan_b,
                advantages_a=list(tactical.advantages_a), advantages_b=list(tactical.advantages_b),
                adjustments_a=[TacticalAdjustmentData(a.category, a.description, a.value, a.confidence) for a in tactical.adjustments_a],
                adjustments_b=[TacticalAdjustmentData(a.category, a.description, a.value, a.confidence) for a in tactical.adjustments_b],
                manager_a=mgr_a.name if mgr_a else "Unknown",
                manager_b=mgr_b.name if mgr_b else "Unknown",
            )

            # === V5.1 Explainability: pre-match analysis (static: squads, tactics) ===
            from fifa_data.services.tactical_analysis import (
                compute_player_influence, compute_exploitation,
                classify_match_archetypes, analyze_win_conditions,
            )
            from fifa_data.services.market_odds_service import compute_model_vs_market

            profile_a = {
                "possession": tactical.base_possession_a if hasattr(tactical, "base_possession_a") else 50,
                "pressing": tactical.pressing_a if hasattr(tactical, "pressing_a") else 50,
                "directness": tactical.directness_a if hasattr(tactical, "directness_a") else 50,
                "defensive_line": tactical.defensive_line_a if hasattr(tactical, "defensive_line_a") else 50,
                "aerial_strength": 55, "set_piece_attack": 50, "set_piece_defense": 50,
                "big_chance_creation": 55, "defensive_compactness": 55,
                "build_up": 55, "defensive_width": 50,
            }
            profile_b = {k: v for k, v in profile_a.items()}

            try:
                pi_report = compute_player_influence(
                    team_a, team_b,
                    engine.squads[team_a], engine.squads[team_b],
                    tactical.final_xg_a, tactical.final_xg_b,
                )
            except Exception:
                pi_report = None

            try:
                exploitation = compute_exploitation(
                    team_a, team_b,
                    engine.squads[team_a], engine.squads[team_b],
                    profile_a, profile_b, tactical_report=tactical,
                )
            except Exception:
                exploitation = None

            try:
                archetypes = classify_match_archetypes(
                    team_a, team_b, profile_a, profile_b, tactical_report=tactical,
                )
            except Exception:
                archetypes = None

            try:
                wc_a = analyze_win_conditions(team_a, profile_a, engine.squads[team_a])
            except Exception:
                wc_a = None

            try:
                wc_b = analyze_win_conditions(team_b, profile_b, engine.squads[team_b])
            except Exception:
                wc_b = None

            try:
                market_comp = compute_model_vs_market(
                    team_a, team_b,
                    tactical.final_xg_a / max(tactical.final_xg_a + tactical.final_xg_b, 0.01) * 100,
                    25.0,
                    tactical.final_xg_b / max(tactical.final_xg_a + tactical.final_xg_b, 0.01) * 100,
                )
            except Exception:
                market_comp = None

            v51_dict: dict[str, Any] = {}

            if pi_report:
                import dataclasses
                v51_dict["player_influence"] = {
                    "team_a": pi_report.team_a,
                    "team_b": pi_report.team_b,
                    "top_attackers_a": [
                        {"name": p.player_name, "role": p.role, "influence": p.overall_influence}
                        for p in pi_report.top_attackers(pi_report.team_a, 5)
                    ],
                    "top_attackers_b": [
                        {"name": p.player_name, "role": p.role, "influence": p.overall_influence}
                        for p in pi_report.top_attackers(pi_report.team_b, 5)
                    ],
                    "top_defenders_a": [
                        {"name": p.player_name, "role": p.role, "influence": p.overall_influence}
                        for p in pi_report.top_defenders(pi_report.team_a, 5)
                    ],
                    "top_defenders_b": [
                        {"name": p.player_name, "role": p.role, "influence": p.overall_influence}
                        for p in pi_report.top_defenders(pi_report.team_b, 5)
                    ],
                    "gk_a": dataclasses.asdict(pi_report.goalkeeper_a) if pi_report.goalkeeper_a else None,
                    "gk_b": dataclasses.asdict(pi_report.goalkeeper_b) if pi_report.goalkeeper_b else None,
                    "dependency_a": dataclasses.asdict(pi_report.dependency_a) if pi_report.dependency_a else None,
                    "dependency_b": dataclasses.asdict(pi_report.dependency_b) if pi_report.dependency_b else None,
                    "matchups": [
                        {"player_a": m.player_a, "player_b": m.player_b, "category": m.category,
                         "advantage_team": m.advantage_team, "net_xg_impact": m.net_xg_impact}
                        for m in pi_report.top_matchups(6)
                    ],
                }

            if exploitation:
                v51_dict["tactical_exploitation"] = {
                    "opportunities": [
                        {"attacker": o.attacker, "defender": o.defender, "category": o.category,
                         "description": o.description, "xg_impact": o.xg_impact}
                        for o in exploitation.top_exploits(6)
                    ],
                }

            if archetypes:
                v51_dict["match_archetypes"] = {
                    "archetypes": [
                        {"name": a.archetype, "prob": a.probability, "desc": a.description}
                        for a in archetypes.archetypes
                    ],
                }

            if wc_a:
                v51_dict["win_conditions_a"] = {
                    "conditions": [
                        {"method": c.method, "prob": c.probability, "desc": c.description}
                        for c in wc_a.conditions
                    ],
                }

            if wc_b:
                v51_dict["win_conditions_b"] = {
                    "conditions": [
                        {"method": c.method, "prob": c.probability, "desc": c.description}
                        for c in wc_b.conditions
                    ],
                }

            if market_comp:
                v51_dict["market_comparison"] = {
                    "team_a": market_comp.team_a,
                    "team_b": market_comp.team_b,
                    "entries": [
                        {"team": e.team, "model_prob": e.model_prob, "market_prob": e.market_prob,
                         "edge": e.edge, "value_level": e.value_level.value}
                        for e in market_comp.entries
                    ],
                    "market": {
                        "home_prob": market_comp.market.home_prob if market_comp.market else None,
                        "draw_prob": market_comp.market.draw_prob if market_comp.market else None,
                        "away_prob": market_comp.market.away_prob if market_comp.market else None,
                    } if market_comp.market else None,
                    "consensus": {
                        "market_count": market_comp.consensus.market_count,
                        "home_range": list(market_comp.consensus.home_range),
                        "draw_range": list(market_comp.consensus.draw_range),
                        "away_range": list(market_comp.consensus.away_range),
                        "home_consensus": market_comp.consensus.home_consensus.value,
                        "draw_consensus": market_comp.consensus.draw_consensus.value,
                        "away_consensus": market_comp.consensus.away_consensus.value,
                    } if market_comp.consensus else None,
                }

            report.v51 = V51ReportData(**v51_dict)

        # === Monte Carlo simulation loop ===
        wins_a = 0
        wins_b = 0
        draws = 0
        total_xg_a = 0.0
        total_xg_b = 0.0
        score_counter: dict[tuple[int, int], int] = collections.Counter()

        for _ in range(simulations):
            if version in ("v4", "v5"):
                ctx_str = "knockout" if knockout else "group"
                g1, g2 = engine.simulate_match(team_a, team_b, can_draw=not knockout, context=ctx_str)
            else:
                g1, g2 = engine.simulate_match(team_a, team_b, can_draw=not knockout)

            if g1 > g2:
                wins_a += 1
            elif g2 > g1:
                wins_b += 1
            else:
                draws += 1

            total_xg_a += g1
            total_xg_b += g2
            score_counter[(g1, g2)] += 1

        avg_xg_a = total_xg_a / simulations
        avg_xg_b = total_xg_b / simulations
        top_scores = score_counter.most_common(10)
        min_a = min(g for g, _ in score_counter.keys()) if score_counter else 0
        max_a = max(g for g, _ in score_counter.keys()) if score_counter else 0
        min_b = min(g for _, g in score_counter.keys()) if score_counter else 0
        max_b = max(g for _, g in score_counter.keys()) if score_counter else 0

        report.mc = MonteCarloResult(
            wins_a=wins_a, wins_b=wins_b, draws=draws, total=simulations,
            avg_xg_a=avg_xg_a, avg_xg_b=avg_xg_b,
            top_scores=top_scores,
            min_goals_a=min_a, max_goals_a=max_a,
            min_goals_b=min_b, max_goals_b=max_b,
        )

        # === V5.1 Model Confidence (after MC results available) ===
        if version == "v5" and report.v51:
            from fifa_data.services.model_confidence_service import compute_confidence
            dep_a = None
            if report.v51.player_influence and report.v51.player_influence.get("dependency_a"):
                from fifa_data.models.player_influence import TeamDependency
                d = report.v51.player_influence["dependency_a"]
                dep_a = TeamDependency(
                    team=d["team"], top_n_attackers=d["top_n_attackers"],
                    attack_output_share=d["attack_output_share"],
                    top_attackers_names=d["top_attackers_names"],
                    dependency_level=d["dependency_level"],
                    top_n_defenders=d["top_n_defenders"],
                    defense_output_share=d["defense_output_share"],
                    top_defenders_names=d["top_defenders_names"],
                )
            mc_result = report.mc
            confidence = compute_confidence(
                mc_result, v4_data=report.v4,
                dependency=dep_a,
                market_comparison=None,
                simulations=simulations,
            )
            report.v51.model_confidence = confidence

        return report

    def _parse_simulation_args(self, args: str | None) -> tuple[str | None, str, bool]:
        tokens = args.split() if args and args.strip() else []
        model = "v1"
        presentation = "fast"
        debug = False

        if not tokens:
            return model, presentation, debug

        first = tokens[0].lower()
        if first in {"v1", "v2", "v3", "v4", "v5"}:
            model = first
            tokens = tokens[1:]
        elif first in {"animated", "fast", "debug"}:
            pass
        else:
            return None, "Usage: `.simulate [v1|v2|v3|v4|v5] [fast|animated] [debug]`", False

        for token in tokens:
            lowered = token.lower()
            if lowered == "animated":
                presentation = "animated"
            elif lowered == "fast":
                presentation = "fast"
            elif lowered == "debug":
                debug = True
            else:
                return None, "Usage: `.simulate [v1|v2|v3|v4] [fast|animated] [debug]`", False

        return model, presentation, debug

    @staticmethod
    def _build_goal_events(h_goals, a_goals):
        all_events = []
        for g in h_goals:
            all_events.append((g, "H"))
        for g in a_goals:
            all_events.append((g, "A"))
        all_events.sort()
        return all_events

    async def _simulate_animated(self, ctx, status_msg, data, model: str = "v1"):
        await status_msg.edit(content=f"🌍 **World Cup 2026 — {model.upper()} Live Simulation**\n🔄 Group Stage underway...")

        # ── GROUP STAGE ──
        for gid in sorted(data["groups"].keys()):
            gp = data["groups"][gid]
            group_msg = await ctx.send(f"┅┅ **Group {gid}** ┅┅")

            for midx, m in enumerate(gp["matches"]):
                h, a = m["home"], m["away"]
                hg, ag = m["home_goals"], m["away_goals"]
                is_real = m["is_real"]

                tag = "📺 LIVE" if not is_real else "📺 REAL"
                match_msg = await ctx.send(f"⚽ **{h}** vs **{a}** — {tag}")

                if is_real:
                    await asyncio.sleep(0.8)
                    await match_msg.edit(content=f"✅ **{h}** {hg}-{ag} **{a}** — REAL RESULT")
                else:
                    await asyncio.sleep(1.2)

                    all_events = self._build_goal_events(m["home_goal_minutes"], m["away_goal_minutes"])

                    cur_h = 0
                    cur_a = 0
                    prev_min = 0

                    for minute, side in all_events:
                        if minute - prev_min > 5:
                            scoreline = f"**{h}** {cur_h}-{cur_a} **{a}**"
                            await match_msg.edit(content=f"⚽ {scoreline} ({minute-2 if minute > 2 else 1}') — {tag}")
                            await asyncio.sleep(0.4)
                        if side == "H":
                            cur_h += 1
                        else:
                            cur_a += 1
                        await match_msg.edit(content=f"⚽ **{h}** {cur_h}-{cur_a} **{a}** 🔊 GOAL! ({minute}') — {tag}")
                        await asyncio.sleep(0.6)
                        prev_min = minute

                    await match_msg.edit(content=f"✅ **{h}** {hg}-{ag} **{a}** — FT")
                    await asyncio.sleep(0.5)

            # Group table
            table = gp["table"]
            tbl_lines = [f"┅┅ **Group {gid}** ┅┅", "` #  Team                 PTS  GD  GF`"]
            for rank, t, pts, gd, gf in table:
                medal = {1: "🥇", 2: "🥈", 3: "🥉", 4: "  "}.get(rank, "  ")
                tbl_lines.append(f"`{medal}{rank}.  {t:<20s} {pts:>2d}  {gd:+>2d}  {gf}`")
            await group_msg.edit(content="\n".join(tbl_lines))
            await asyncio.sleep(0.8)

        # ── BEST 3RD PLACED ──
        tp_lines = ["┅┅ **Best 3rd-Placed Teams** (top 8 advance) ┅┅"]
        for rank, tp in enumerate(data["third_placed"], 1):
            gid, t, pts, gd, gf = tp
            mark = "✅" if rank <= 8 else "❌"
            tp_lines.append(f"{mark} Grp {gid} **{t}** — {pts}pts, {gd:+}GD, {gf}GF")
        await ctx.send("\n".join(tp_lines))
        await asyncio.sleep(0.5)

        # ── KNOCKOUT ──
        ko_names = ["🔵 **Round of 32**", "🟢 **Round of 16**", "🟡 **Quarter-Finals**", "🟠 **Semi-Finals**", "🔴 **Final**"]
        for rnd_idx, (rd_name, rd_matches) in enumerate(zip(ko_names, data["knockout"])):
            await ctx.send(f"── {rd_name} ──")
            await asyncio.sleep(0.5)
            for m in rd_matches:
                if m is None:
                    continue
                h, a = m["home"], m["away"]
                hg, ag = m["home_goals"], m["away_goals"]
                winner = m["winner"]

                match_msg = await ctx.send(f"⚽ **{h}** vs **{a}**")
                await asyncio.sleep(1.0)

                all_events = self._build_goal_events(m["home_goal_minutes"], m["away_goal_minutes"])

                cur_h = 0
                cur_a = 0
                prev_min = 0
                for minute, side in all_events:
                    if minute - prev_min > 5:
                        scoreline = f"**{h}** {cur_h}-{cur_a} **{a}**"
                        await match_msg.edit(content=f"⚽ {scoreline} ({minute-3 if minute > 3 else 1}')")
                        await asyncio.sleep(0.3)
                    if side == "H":
                        cur_h += 1
                    else:
                        cur_a += 1
                    await match_msg.edit(content=f"⚽ **{h}** {cur_h}-{cur_a} **{a}** 🔊 GOAL! ({minute}')")
                    await asyncio.sleep(0.5)
                    prev_min = minute

                emoji = "🏆" if rnd_idx == 4 else "✅"
                await match_msg.edit(content=f"{emoji} **{h}** {hg}-{ag} **{a}** → **{winner}**")
                await asyncio.sleep(0.5)

        # ── THIRD PLACE ──
        tp3 = data.get("third_place")
        if tp3:
            await ctx.send(f"── 🥉 **Third Place Play-Off** ──")
            h, a = tp3["home"], tp3["away"]
            hg, ag = tp3["home_goals"], tp3["away_goals"]
            winner = tp3["winner"]
            tp_msg = await ctx.send(f"⚽ **{h}** vs **{a}**")
            await asyncio.sleep(1.0)
            all_events = self._build_goal_events(tp3["home_goal_minutes"], tp3["away_goal_minutes"])
            cur_h, cur_a = 0, 0
            for minute, side in all_events:
                if side == "H":
                    cur_h += 1
                else:
                    cur_a += 1
                await tp_msg.edit(content=f"⚽ **{h}** {cur_h}-{cur_a} **{a}** 🔊 GOAL! ({minute}')")
                await asyncio.sleep(0.5)
            await tp_msg.edit(content=f"🥉 **{h}** {hg}-{ag} **{a}** → **{winner}** wins 3rd place!")
            await asyncio.sleep(0.5)

        # ── CHAMPION ──
        champ = data.get("champion", "TBD")
        await status_msg.edit(content=f"🌍 **World Cup 2026 — {model.upper()} SIMULATION COMPLETE**")
        await ctx.send(f"🏆🏆🏆 **{champ.upper()}** ARE WORLD CUP 2026 CHAMPIONS! 🏆🏆🏆")

    async def _simulate_fast(self, ctx, status_msg, data, model: str = "v1", debug: bool = False):
        """Fast simulation - show results without animations."""
        await status_msg.edit(content=f"🌍 **World Cup 2026 — {model.upper()} Simulation Complete**")

        # Group Stage - tables only
        for gid in sorted(data["groups"].keys()):
            gp = data["groups"][gid]
            table = gp["table"]
            lines = [f"**Group {gid}**", "` #  Team                PTS  GD  GF`"]
            for rank, t, pts, gd, gf in table:
                medal = {1: "🥇", 2: "🥈", 3: "🥉", 4: "  "}.get(rank, "  ")
                lines.append(f"`{medal}{rank}.  {t:<18s} {pts:>2d}  {gd:+>2d}  {gf}`")
            await ctx.send("\n".join(lines))

        # Third place
        tp_lines = ["**Best 3rd-Placed Teams** (top 8 advance)"]
        for rank, tp in enumerate(data["third_placed"], 1):
            gid, t, pts, gd, gf = tp
            mark = "✅" if rank <= 8 else "❌"
            tp_lines.append(f"{mark} Grp {gid} **{t}** — {pts}pts, {gd:+}GD, {gf}GF")
        await ctx.send("\n".join(tp_lines[:13]))

        # Knockout results
        ko_names = ["Round of 32", "Round of 16", "Quarter-Finals", "Semi-Finals", "Final"]
        for rnd_idx, (rd_name, rd_matches) in enumerate(zip(ko_names, data["knockout"])):
            if rnd_idx == 4:
                await ctx.send(f"🔴 **{rd_name}**")
            else:
                await ctx.send(f"**{rd_name}**")
            for m in rd_matches:
                if m:
                    await ctx.send(f"⚽ **{m['home']}** {m['home_goals']}-{m['away_goals']} **{m['away']}** → **{m['winner']}**")

        # Third place
        tp3 = data.get("third_place")
        if tp3:
            await ctx.send("🥉 **Third Place Play-Off**")
            await ctx.send(f"⚽ **{tp3['home']}** {tp3['home_goals']}-{tp3['away_goals']} **{tp3['away']}** → **{tp3['winner']}** wins!")

        champ = data.get("champion", "TBD")
        if debug:
            debug_items = data.get("debug", [])
            if debug_items:
                await ctx.send(f"🔎 **{model.upper()} Debug Preview** — first {min(3, len(debug_items))} simulated matches")
                for item in debug_items[:3]:
                    safe = item.replace("```", "` ` `")
                    await ctx.send(f"```{safe[:1800]}```")
        await ctx.send(f"🏆🏆🏆 **{champ.upper()}** ARE WORLD CUP 2026 CHAMPIONS! 🏆🏆🏆")
        await ctx.send(f"📊 Model: {model.upper()} | Matches: {data['stats']['real_count']} real + {data['stats']['total_group_matches'] - data['stats']['real_count']} simulated group + {data['stats']['knockout_matches'] + data['stats']['third_place']} KO = {data['stats']['total_group_matches'] + data['stats']['knockout_matches'] + data['stats']['third_place']} total")


class _ReportView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], author_id: int) -> None:
        super().__init__(timeout=120)
        self.pages = pages
        self.author_id = author_id
        self.current = 0
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command author can navigate.", ephemeral=True)
            return False
        return True

    def _update_buttons(self) -> None:
        self._prev.disabled = self.current == 0
        self._next.disabled = self.current == len(self.pages) - 1

    async def _show_page(self, interaction: discord.Interaction) -> None:
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def _prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.current > 0:
            self.current -= 1
            await self._show_page(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def _next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.current < len(self.pages) - 1:
            self.current += 1
            await self._show_page(interaction)

    @discord.ui.button(label="✕", style=discord.ButtonStyle.danger)
    async def _close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.message.delete()
        self.stop()

    async def on_timeout(self) -> None:
        if self.message:
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
        self.stop()


async def setup(bot):
    await bot.add_cog(DraftCog(bot))
