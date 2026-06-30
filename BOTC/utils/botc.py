from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from typing import Any

import discord

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IMAGE_BASE = "https://raw.githubusercontent.com/tomozbot/botc-icons/refs/heads/main/PNG"
WIKI_BASE = "https://wiki.bloodontheclocktower.com"

TEAM_EMOJI = {
    "townsfolk": "🟦",
    "outsider": "🟪",
    "minion": "🟥",
    "demon": "⬛",
    "traveler": "🟨",
    "fabled": "🟩",
}

TEAM_COLOR = {
    "townsfolk": discord.Color.blue(),
    "outsider": discord.Color.purple(),
    "minion": discord.Color.red(),
    "demon": discord.Color.from_str("#1a1a1a"),
    "traveler": discord.Color.gold(),
    "fabled": discord.Color.green(),
}

EDITION_NAMES = {
    "tb": "Trouble Brewing",
    "bmr": "Bad Moon Rising",
    "snv": "Sects & Violets",
    "carousel": "Carousel",
}

def _load_json(filename: str) -> list[dict]:
    path = os.path.join(BASE_DIR, "data", filename)
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[\s\-_'”,.!?;:()\"“”]", "", text)
    return text

def _token_image_url(role_id: str) -> str:
    return f"{IMAGE_BASE}/{role_id}.png"

_ROLES_DATA: list[dict] = _load_json("roles.json")
_FABLED_DATA: list[dict] = _load_json("fabled.json")
_JINXES_DATA: list[dict] = _load_json("jinxes.json")
_ALIASES_DATA: dict[str, str] = _load_json("aliases.json")

_ROLES_BY_ID: dict[str, dict] = {r["id"]: r for r in _ROLES_DATA}
_ROLES_BY_NAME: dict[str, dict] = {r["name"].lower(): r for r in _ROLES_DATA}
_FABLED_BY_ID: dict[str, dict] = {r["id"]: r for r in _FABLED_DATA}
_FABLED_BY_NAME: dict[str, dict] = {r["name"].lower(): r for r in _FABLED_DATA}

_ROLE_NORM_MAP: dict[str, list[str]] = {}
for r in _ROLES_DATA:
    key = _normalize(r["name"])
    _ROLE_NORM_MAP.setdefault(key, []).append(r["name"])

_FABLED_NORM_MAP: dict[str, list[str]] = {}
for r in _FABLED_DATA:
    key = _normalize(r["name"])
    _FABLED_NORM_MAP.setdefault(key, []).append(r["name"])

_JINX_MAP: dict[str, list[dict]] = {}
for entry in _JINXES_DATA:
    _JINX_MAP[entry["id"]] = entry["jinx"]

_ALIAS_TARGET: dict[str, str] = {alias: target for alias, target in _ALIASES_DATA.items()}
_ALIAS_REVERSE: dict[str, list[str]] = {}
for alias, target in _ALIASES_DATA.items():
    _ALIAS_REVERSE.setdefault(target, []).append(alias)

ALL_ROLES: list[dict] = _ROLES_DATA
ALL_FABLED: list[dict] = _FABLED_DATA

def _fuzzy_find(
    query: str,
    candidates: list[dict],
    norm_map: dict[str, list[str]],
    name_map: dict[str, dict],
    id_map: dict[str, dict],
) -> dict | None:
    q = query.strip()
    if not q:
        return None

    q_lower = q.lower()
    q_norm = _normalize(q)

    if q_lower in name_map:
        return name_map[q_lower]
    if q_lower in id_map:
        return id_map[q_lower]
    if q_norm in norm_map:
        names = norm_map[q_norm]
        if len(names) == 1:
            return name_map[names[0].lower()]
        return name_map[names[0].lower()]

    alias_target = _ALIAS_TARGET.get(q_lower)
    if alias_target:
        alias_lower = alias_target.lower()
        if alias_lower in name_map:
            return name_map[alias_lower]

    best: list[tuple[float, dict]] = []
    for r in candidates:
        name_norm = _normalize(r["name"])
        if q_norm in name_norm or name_norm in q_norm:
            best.append((0.9, r))
            continue
        ratio = SequenceMatcher(None, q_norm, name_norm).ratio()
        if ratio > 0.5:
            best.append((ratio, r))

    if best:
        best.sort(key=lambda x: -x[0])
        return best[0][1]

    return None

def get_role(name: str) -> dict | None:
    return _fuzzy_find(name, _ROLES_DATA, _ROLE_NORM_MAP, _ROLES_BY_NAME, _ROLES_BY_ID)

def get_fabled(name: str) -> dict | None:
    return _fuzzy_find(name, _FABLED_DATA, _FABLED_NORM_MAP, _FABLED_BY_NAME, _FABLED_BY_ID)

def get_jinxes(role_id: str) -> list[dict]:
    return _JINX_MAP.get(role_id, [])

def get_jinxes_for_role(name: str) -> list[dict]:
    role = get_role(name)
    if not role:
        return []
    return get_jinxes(role["id"])

def get_aliases(role_id: str) -> list[str]:
    return _ALIAS_REVERSE.get(role_id, [])

def get_role_by_id(role_id: str) -> dict | None:
    return _ROLES_BY_ID.get(role_id)

def get_fabled_by_id(role_id: str) -> dict | None:
    return _FABLED_BY_ID.get(role_id)

def get_edition_name(edition: str) -> str:
    return EDITION_NAMES.get(edition, edition.capitalize() if edition else "Experimental")

def team_emoji(team: str) -> str:
    return TEAM_EMOJI.get(team, "")

def build_role_embed(role: dict) -> discord.Embed:
    name = role["name"]
    team = role["team"]
    ability = role["ability"]
    edition_key = role.get("edition", "")
    edition = get_edition_name(edition_key)
    role_id = role["id"]

    aliases = get_aliases(role_id)
    setup = role.get("setup", False)
    reminders = role.get("reminders", [])
    reminders_global = role.get("remindersGlobal", [])

    emoji = team_emoji(team)
    title = f"{emoji} {name}"

    subtitle_parts = [f"**{team.capitalize()}**", edition]
    if setup:
        subtitle_parts.append("⚙️ Setup")
    subtitle = " · ".join(subtitle_parts)

    description = f"{subtitle}\n*{ability}*"

    color = TEAM_COLOR.get(team, discord.Color.default())

    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_thumbnail(url=_token_image_url(role_id))

    if reminders:
        all_reminders = reminders + reminders_global
        rem_text = " ".join(f"`{r}`" for r in all_reminders)
        embed.add_field(name="Reminder Tokens", value=rem_text, inline=False)

    if aliases:
        embed.add_field(name="Aliases", value=", ".join(f"`{a}`" for a in aliases), inline=False)

    embed.set_footer(text=f"ID: {role_id}")

    return embed

def build_fabled_embed(fabled: dict) -> discord.Embed:
    name = fabled["name"]
    ability = fabled["ability"]
    role_id = fabled["id"]
    reminders = fabled.get("reminders", [])

    embed = discord.Embed(
        title=f"🟩 {name}",
        description=f"*{ability}*",
        color=TEAM_COLOR["fabled"],
    )
    embed.set_thumbnail(url=_token_image_url(role_id))

    if reminders:
        rem_text = ", ".join(f"`{r}`" for r in reminders)
        embed.add_field(name="Reminder Tokens", value=rem_text, inline=False)

    embed.set_footer(text=f"ID: {role_id}")

    return embed

def build_jinx_embed(role: dict, jinxes: list[dict]) -> discord.Embed:
    name = role["name"]
    team = role["team"]

    embed = discord.Embed(
        title=f"{team_emoji(team)} {name} — Jinxes",
        color=TEAM_COLOR.get(team, discord.Color.default()),
    )
    embed.set_thumbnail(url=_token_image_url(role["id"]))

    if not jinxes:
        embed.description = "No jinxes."
        return embed

    lines = []
    for j in jinxes:
        j_role = get_role_by_id(j["id"])
        j_name = j_role["name"] if j_role else j["id"]
        emoji = team_emoji(j_role["team"]) if j_role else ""
        lines.append(f"**{emoji} {j_name}** — {j['reason']}")

    embed.description = "\n\n".join(lines)
    return embed

def build_night_order_embed(roles: list[dict], title: str) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        color=discord.Color.dark_blue(),
    )

    for i, role in enumerate(roles, 1):
        team = role.get("team", "")
        emoji = team_emoji(team)
        embed.add_field(
            name=f"{i}. {emoji} {role['name']}",
            value=role.get("ability", ""),
            inline=False,
        )

    return embed
