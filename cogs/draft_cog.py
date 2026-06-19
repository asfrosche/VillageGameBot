import discord
import json
import os
import re
import asyncio
import aiohttp
import sys
from datetime import datetime
from discord.ext import commands

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

from fifa_data.services.simulation_service import run_simulation
from fifa_data.services.fantasy_service import FantasyService, norm as fs_norm, FIFA_POSITION_MAP
from fifa_data.services.match_analytics import (
    get_match_analytics, get_form_players, get_differentials,
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

        team = draft["teams"].get(str(self.owner_id), {"players": [], "country_counts": {}})

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
            import traceback
            print(f"[DRAFT] on_submit: _advance_after_pick failed — {e}")
            traceback.print_exc()


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
        print(f"CountrySelectView error: {error}")


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
        team = draft["teams"].get(str(self.owner_id), {"players": [], "country_counts": {}})

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

            team = draft["teams"].get(str(self.owner_id), {"players": [], "country_counts": {}})
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
        print(f"PositionButtons error: {error}")


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
        print(f"PrepickManageView error: {error}")


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

        team = draft["teams"].get(str(self.owner_id), {"players": [], "country_counts": {}})
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
        self._load()

    def _load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.data = {}
        else:
            self.data = {}
        for draft in self.data.values():
            if draft.get("started") and not draft.get("ended"):
                draft["paused"] = True
                draft["turn_message_id"] = None

    def _save(self):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

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
                except Exception:
                    pass
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

        team = draft["teams"].setdefault(str(owner_id), {"players": [], "country_counts": {}})

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
        draft["pick_history"].append(pick)
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
            print(f"[DRAFT] _advance_after_pick: guild={guild} channel={channel} — pausing")
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
            print(f"[DRAFT] _advance_after_pick: Forbidden/NotFound — {e}")
            draft["paused"] = True
            self._save()
        except Exception as e:
            import traceback
            print(f"[DRAFT] _advance_after_pick: unexpected error — {e}")
            traceback.print_exc()
            draft["paused"] = True
            self._save()

    async def _send_turn(self, guild_id, channel, guild):
        draft = self._get_draft(guild_id)
        if draft is None or draft.get("ended"):
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
            print(f"[DRAFT] _send_turn: can't send turn — {e}")
            return
        except Exception as e:
            print(f"[DRAFT] _send_turn: unexpected error — {e}")
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
                print(f"[DRAFT] _update_status: can't send status — {e}")
                return
            except Exception as e:
                print(f"[DRAFT] _update_status: unexpected error — {e}")
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
            draft["teams"][str(uid)] = {"players": [], "country_counts": {}}

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

        await self.fantasy.fetch_data(force=True)
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
            def __init__(self2):
                super().__init__(timeout=120)
                self2.position = None
                self2.country = None
                self2.message = None

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
                if not can_add_position(team["players"], self2.position):
                    return await interaction.response.send_message(f"Position {self2.position} is no longer available.", ephemeral=True)
                if not can_add_country(team["players"], self2.country):
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

        view = ForcePickView()
        view.cog = self
        view.message = msg
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

        await self.fantasy.fetch_data(force=True)

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
        await self.fantasy.fetch_data(force=True)
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

        await self.fantasy.fetch_data(force=True)
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
        await self.fantasy.fetch_data(force=True)
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
        await self.fantasy.fetch_data(force=True)
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
        await self.fantasy.fetch_data(force=True)

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
        await ctx.send("⏳ Loading match data...")

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
        """Detailed explanation of .sim models (V1-V4)."""
        lines = [
            "**World Cup Simulation Models**",
            "",
            "**`.sim v1` — ELO Rating Engine**",
            "• Based on classic ELO + PELE rating system",
            "• Teams rated by historical performance and match results",
            "• Real WC 2026 results update ELO in real time",
            "• Goal difference weighted (1 GD = 1x, 2 GD = 1.5x, 3+ GD = 2x)",
            "• Expected goals derived from rating ratios with non-linear curve",
            "• Best for: quick simulations where only team quality matters",
            "",
            "**`.sim v2` — Player Attribute Engine**",
            "• Every player rated individually from FC26 data",
            "• 11 positional roles rated separately (GK, CB, FB, CM, DM, WINGER, ST)",
            "• Formation-aware: 4-3-3 vs 4-4-2 vs 3-5-2 etc. each evaluated",
            "• Attack/Defense/Goalkeeper strength computed from role-weighted averages",
            "• More granular than V1 — a star player can carry a weaker squad",
            "• Requires up-to-date players.json and squads.json",
            "",
            "**`.sim v3` — Dynamic State Engine**",
            "• Builds on V2 player ratings",
            "• Adds 6 dynamic modifiers that change match-to-match:",
            "  - Chemistry: how well the starting XI fits together",
            "  - Experience: big-match temperament (boosted in KO stages)",
            "  - Form: recent performance trend",
            "  - Momentum: winning/losing streak effects",
            "  - Continuity: how often same XI plays together",
            "  - Leadership: captain and veteran influence",
            "• National strength modifiers add patriotic home-field context",
            "• Each modifier applies ±10% multiplier to base strength",
            "• Most realistic simulation of a single match",
            "",
            "**`.sim v4` — Tactical Intelligence Engine**",
            "• Advanced tactical layer **on top of V3** (does not replace it)",
            "• Every team has a tactical profile with 20+ attributes (0-100):",
            "  - Possession quality: progressive passes, final-third entries,",
            "    big chance creation, shot quality (FBref/Opta-based)",
            "  - Defensive style: low block, mid block, high press,",
            "    man marking, or zonal (each interacts differently)",
            "  - Tactical flexibility: ability to adapt mid-match",
            "  - Set-piece threat, aerial strength, pressing intensity",
            "• Real manager profiles: risk tolerance, pressing preference,",
            "  defensive discipline, tactical flexibility",
            "  (Scaloni, Deschamps, Nagelsmann, Bielsa, Southgate, etc.)",
            "• Match context matters:",
            "  - Group stage: standard approach",
            "  - Knockout: slightly more cautious (-0.01 xG)",
            "  - Must-win: attacking urgency (+0.02 xG)",
            "  - Need draw: deep defensive focus (-0.015 xG)",
            "  - GD chase: high-risk attacking (+0.025 xG, -0.015 defensive)",
            "• 7 tactical matchup categories evaluated per match:",
            "  1. High line vs pace exploitation",
            "  2. Pressing vs weak build-up",
            "  3. Possession vs low block creativity",
            "  4. Set-piece mismatches",
            "  5. Aerial dominance",
            "  6. Formation advantages (width, midfield control)",
            "  7. Player-tactic compatibility",
            "• All adjustments capped at ±10% of base xG",
            "• Elite teams remain favorites; upsets still happen via Poisson",
            "• Add `debug` flag for full tactical breakdown per match",
            "",
            "**Usage:**",
            "`.sim v4` — Fast V4 simulation (default)",
            "`.sim v4 animated` — Watch matches play out in real time",
            "`.sim v4 debug` — Show tactical reports for first 3 matches",
            "`.fsim v4` — Alias for `.simulate v4`",
            "",
            "**Statistics:** 48 World Cup teams | 20+ tactical attributes each",
            "| 48 manager profiles | 8 formation profiles | 5 match contexts",
            "| 5 defensive styles | 5 game plans",
        ]
        await ctx.send("\n".join(lines))

    @commands.command(aliases=["fsim"])
    async def simulate(self, ctx, *, args: str = None):
        """Run tournament simulation: `.simulate [v1|v2|v3|v4] [fast|animated] [debug]` or `.fsim ...`."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.")
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

            from datetime import datetime
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
            return None, "Usage: `.sim [v1|v2|v3|v4] [fast|animated] [debug]`", False

        for token in tokens:
            lowered = token.lower()
            if lowered == "animated":
                presentation = "animated"
            elif lowered == "fast":
                presentation = "fast"
            elif lowered == "debug":
                debug = True
            else:
                return None, "Usage: `.sim [v1|v2|v3|v4] [fast|animated] [debug]`", False

        return model, presentation, debug

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

                    h_goals = m["home_goal_minutes"]
                    a_goals = m["away_goal_minutes"]
                    all_events = []
                    for g in h_goals:
                        all_events.append((g, "H"))
                    for g in a_goals:
                        all_events.append((g, "A"))
                    all_events.sort()

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

                h_goals = m["home_goal_minutes"]
                a_goals = m["away_goal_minutes"]
                all_events = []
                for g in h_goals:
                    all_events.append((g, "H"))
                for g in a_goals:
                    all_events.append((g, "A"))
                all_events.sort()

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
            h_goals = tp3["home_goal_minutes"]
            a_goals = tp3["away_goal_minutes"]
            all_events = []
            for g in h_goals:
                all_events.append((g, "H"))
            for g in a_goals:
                all_events.append((g, "A"))
            all_events.sort()
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
        await ctx.send("\n".join(tp_lines[:9]))

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
