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
    get_matches_for_team, load_data,
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
        resolved = self.fantasy.resolve_players(team["players"])
        total = sum(r["net_points"] for r in resolved)

        member = ctx.guild.get_member(user.id)
        name = member.display_name if member else f"<@{user.id}>"
        embed = discord.Embed(
            title=f"Team {name}",
            color=0xff3fb9,
        )
        lines = []
        for pos in POSITIONS:
            pos_players = [r for r in resolved if r["position"] == pos]
            if pos_players:
                for r in pos_players:
                    pts_str = f"{r['net_points']}pts" if r['match'] else "N/A"
                    lines.append(f"{POSITION_EMOJIS[pos]} **{r['name']}** — {pts_str}")
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

        results = []
        for uid_str, team in draft["teams"].items():
            uid = int(uid_str)
            member = ctx.guild.get_member(uid)
            manager = member.display_name if member else f"<@{uid}>"
            resolved = self.fantasy.resolve_players(team["players"])
            total = sum(r["net_points"] for r in resolved)
            details = [(r["name"], r["net_points"], r["position"]) for r in resolved]
            results.append((total, manager, details))

        results.sort(key=lambda x: x[0], reverse=True)

        embed = discord.Embed(title="🏆 Draft Fantasy Points", color=0xff3fb9)
        for rank, (total, manager, details) in enumerate(results, 1):
            lines = [f"{n}: {p}pts ({pos})" for n, p, pos in details]
            val = "\n".join(lines) if lines else "No players drafted"
            val += f"\n**Total: {total} pts**"
            embed.add_field(name=f"#{rank} {manager}", value=val[:1024], inline=False)

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

        embed = discord.Embed(title=f"⚽ {pname}", color=0xff3fb9)
        embed.add_field(name="Position", value=pos, inline=True)
        embed.add_field(name="Team", value=squad_name, inline=True)
        embed.add_field(name="Total Points", value=net, inline=True)
        embed.add_field(name="Last Round", value=last, inline=True)
        embed.add_field(name="Games Played", value=gp, inline=True)
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
        """Show latest match results with fantasy top scorers.
        Optional: group letter (A-L) or team name to filter."""
        await ctx.send("⏳ Fetching latest match data...")
        try:
            await fetch_and_cache_data()
        except Exception:
            await ctx.send("⚠️ Could not fetch live data, using cached...")

        match_reports, upcoming_reports = get_match_analytics(limit_matches=12)

        if filter_term:
            group_filter = filter_term.upper().replace("GROUP ", "")
            team_filter = filter_term.lower()
            match_reports = [
                m for m in match_reports
                if m["group"].replace("Group ", "") == group_filter
                or team_filter in m["home"].lower() or team_filter in m["away"].lower()
            ]
            upcoming_reports = [
                m for m in upcoming_reports
                if m["group"].replace("Group ", "") == group_filter
                or team_filter in m["home"].lower() or team_filter in m["away"].lower()
            ]

        if not match_reports and not upcoming_reports:
            return await ctx.send("No matches found for that filter.")

        embed = discord.Embed(
            title="⚽ World Cup 2026 — Match Report",
            color=0xff3fb9,
        )

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
            embed.add_field(
                name=f"📊 Latest Results ({len(match_reports)} matches)",
                value="\n".join(lines)[:1024],
                inline=False,
            )

        if upcoming_reports:
            lines = []
            for ur in upcoming_reports:
                lines.append(f"`{ur['group']:8s}` {ur['home']} vs {ur['away']}")
            embed.add_field(
                name=f"🔜 Upcoming ({len(upcoming_reports)} matches)",
                value="\n".join(lines),
                inline=False,
            )

        await ctx.send(embed=embed)

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
        """Detailed explanation of simulation models (V1-V4)."""
        embed1 = discord.Embed(title="Simulation Commands Overview", color=0xff3fb9)
        embed1.add_field(name="Tournament Simulation", value=(
            "`.simulate` / `.fsim` / `.sim` — **full World Cup 2026 sim**\n"
            "Picks: version → mode → flags\n\n"
            "**Syntax:** `.simulate [version] [mode] [debug]`\n"
            "**Short:** `.fsim [version] [mode] [debug]`\n"
            "**Examples:**\n"
            "`.fsim` — V1 fast (default)\n"
            "`.fsim v4` — V4 tactical, fast\n"
            "`.fsim v4 animated` — V4 goal-by-goal\n"
            "`.fsim v4 debug` — V4 with tactical breakdown"
        ), inline=False)
        embed1.add_field(name="Head-to-Head Analysis", value=(
            "`.fsim detailed` — **Monte Carlo between 2 teams**\n"
            "Picks: version → team A → team B → options\n\n"
            "**Syntax:** `.fsim detailed <version> <Team A> <Team B> [knockout] [N]`\n"
            "**Examples:**\n"
            "`.fsim detailed v4 France Spain`\n"
            "`.fsim detailed v4 France Spain knockout`\n"
            "`.fsim detailed v4 France Spain 10000`\n"
            "`.fsim detailed v4 France Spain knockout 10000`"
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
        embed2.set_footer(text="48 teams | 20+ attributes | 8 formations | 5 contexts")
        await ctx.send(embed=embed2)

    @commands.command(aliases=["sim", "fsim"])
    async def simulate(self, ctx, *, args: str = None):
        """Run tournament simulation: `.simulate [v1|v2|v3|v4] [fast|animated|detailed] [debug]` or `.fsim ...`."""
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
        VALID_VERSIONS = {"v1", "v2", "v3", "v4"}
        VERSION_LABELS = {
            "v1": "Historical ELO/PELE",
            "v2": "FC26 Player Intelligence",
            "v3": "Dynamic Team State",
            "v4": "Tactical Intelligence",
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
                "",
                "Examples:",
                "`.fsim detailed v4 France Spain`",
                "`.fsim detailed v4 France Spain knockout`",
                "`.fsim detailed v4 France Spain 1000`",
                "`.fsim detailed v4 France Spain knockout 10000`",
            ]
            return await ctx.send("\n".join(lines))

        version = tokens[0].lower()
        if version not in VALID_VERSIONS:
            avail = "\n".join(f"`{v}` — {VERSION_LABELS[v]}" for v in ["v1", "v2", "v3", "v4"])
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
            result = await loop.run_in_executor(
                None, self._run_monte_carlo,
                version, team_a, team_b, knockout, simulations,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return await ctx.send(f"❌ Simulation error: {e}")

        w1, w2, draws, total = result["wins_a"], result["wins_b"], result["draws"], result["total"]
        p1 = w1 / total * 100 if total else 0
        p2 = w2 / total * 100 if total else 0
        pd = draws / total * 100 if total else 0
        avg_xg_a = result["avg_xg_a"]
        avg_xg_b = result["avg_xg_b"]

        embed = discord.Embed(
            title=f"🔬 {version.upper()} Detailed Match Analysis",
            color=0xff3fb9,
        )
        embed.add_field(
            name=f"{flag_a} {team_a} vs {flag_b} {team_b}",
            value=f"`{knockout and 'Knockout' or 'Group Stage'}` | {simulations:,} simulations",
            inline=False,
        )

        bar_len = 12
        w1_bar = "█" * max(1, round(p1 / 100 * bar_len)) if p1 > 0 else ""
        w2_bar = "█" * max(1, round(p2 / 100 * bar_len)) if p2 > 0 else ""
        d_bar = "█" * max(1, round(pd / 100 * bar_len)) if pd > 0 else ""

        embed.add_field(
            name="📊 Match Outcome",
            value=(
                f"**{flag_a} {team_a}**  {p1:.1f}%\n`{w1_bar:<{bar_len}}` {w1:,}\n"
                f"**Draw**          {pd:.1f}%\n`{d_bar:<{bar_len}}` {draws:,}\n"
                f"**{flag_b} {team_b}**  {p2:.1f}%\n`{w2_bar:<{bar_len}}` {w2:,}"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚽ Expected Goals (avg)",
            value=f"{flag_a} {team_a}: **{avg_xg_a:.3f}**\n{flag_b} {team_b}: **{avg_xg_b:.3f}**",
            inline=True,
        )
        embed.add_field(
            name="🏆 Most Common Scorelines",
            value="\n".join(
                f"{flag_a} {s[0]}-{s[1]} {flag_b}  — {c:,}× ({c/total*100:.1f}%)"
                for s, c in result["top_scores"][:5]
            ) or "N/A",
            inline=True,
        )

        if version == "v4":
            plan_a = result.get("plan_a", "balanced")
            plan_b = result.get("plan_b", "balanced")
            embed.add_field(
                name="🧠 Game Plans",
                value=f"{flag_a} {team_a}: **{plan_a}**\n{flag_b} {team_b}: **{plan_b}**",
                inline=False,
            )

        embed.set_footer(text=f"Model: {version.upper()} | {VERSION_LABELS[version]}")
        await status.edit(content=None, embed=embed)

    def _run_monte_carlo(
        self, version: str, team_a: str, team_b: str,
        knockout: bool, simulations: int,
    ) -> dict:
        from fifa_data.engines.v1_elo_engine import V1EloMatchEngine
        from fifa_data.engines.v2_player_engine import V2PlayerMatchEngine
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        from fifa_data.engines.v4_tactical_engine import V4TacticalEngine

        fifa_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fifa_data")

        if version == "v1":
            from fifa_data.services.simulation_service import TEAM_METRICS
            engine = V1EloMatchEngine(TEAM_METRICS)
        elif version == "v2":
            engine = V2PlayerMatchEngine(data_dir=fifa_dir)
        elif version == "v3":
            engine = V3DynamicEngine(data_dir=fifa_dir)
        else:
            engine = V4TacticalEngine(data_dir=fifa_dir)

        wins_a = 0
        wins_b = 0
        draws = 0
        total_xg_a = 0.0
        total_xg_b = 0.0
        score_counter: dict[tuple[int, int], int] = collections.Counter()
        last_plan_a = "balanced"
        last_plan_b = "balanced"

        for _ in range(simulations):
            if version == "v4" and knockout:
                g1, g2 = engine.simulate_match(team_a, team_b, can_draw=False, context="knockout")
            elif version == "v4":
                g1, g2 = engine.simulate_match(team_a, team_b, can_draw=True, context="group")
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

            # Capture last game plans from V4
            if version == "v4":
                report = getattr(engine, "last_tactical_report", None)
                if report:
                    last_plan_a = report.game_plan_a
                    last_plan_b = report.game_plan_b

        avg_xg_a = total_xg_a / simulations
        avg_xg_b = total_xg_b / simulations
        top_scores = score_counter.most_common(10)

        result = {
            "wins_a": wins_a,
            "wins_b": wins_b,
            "draws": draws,
            "total": simulations,
            "avg_xg_a": avg_xg_a,
            "avg_xg_b": avg_xg_b,
            "top_scores": top_scores,
        }
        if version == "v4":
            result["plan_a"] = last_plan_a
            result["plan_b"] = last_plan_b
        return result

    def _parse_simulation_args(self, args: str | None) -> tuple[str | None, str, bool]:
        tokens = args.split() if args and args.strip() else []
        model = "v1"
        presentation = "fast"
        debug = False

        if not tokens:
            return model, presentation, debug

        first = tokens[0].lower()
        if first in {"v1", "v2", "v3", "v4"}:
            model = first
            tokens = tokens[1:]
        elif first in {"animated", "fast", "debug"}:
            pass
        else:
            return None, "Usage: `.simulate [v1|v2|v3|v4] [fast|animated] [debug]`", False

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


async def setup(bot):
    await bot.add_cog(DraftCog(bot))
