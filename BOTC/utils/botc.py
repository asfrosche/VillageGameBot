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

    title = f"{team_emoji(team)} {name}"
    description = f"*{ability}*"

    color = TEAM_COLOR.get(team, discord.Color.default())

    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_thumbnail(url=_token_image_url(role_id))
    embed.add_field(name="Team", value=team.capitalize(), inline=True)
    embed.add_field(name="Edition", value=edition, inline=True)

    if setup:
        embed.add_field(name="Setup", value="Has setup changes", inline=True)

    if reminders:
        all_reminders = reminders + reminders_global
        rem_text = ", ".join(f"`{r}`" for r in all_reminders)
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

# ── Script image generation ──

import io
import urllib.request
from PIL import Image, ImageDraw, ImageFont  # type: ignore[import]

ICON_CACHE = os.path.join(BASE_DIR, "data", ".icon_cache")
SCRIPT_CACHE = os.path.join(BASE_DIR, "data", ".script_cache")

_TEAM_LABELS = {
    "townsfolk": "Townsfolk",
    "outsider": "Outsider",
    "minion": "Minion",
    "demon": "Demon",
    "traveler": "Traveler",
    "fabled": "Fabled",
}
_TEAM_HEADER_COLORS = {
    "townsfolk": (0x00, 0x49, 0xFF),
    "outsider": (0x00, 0xBB, 0xFF),
    "minion": (0xFF, 0x88, 0x00),
    "demon": (0xFF, 0x00, 0x00),
    "traveler": (0xFF, 0x00, 0xFF),
    "fabled": (0x00, 0xCC, 0x00),
}
_TEAM_ORDER = ["townsfolk", "outsider", "minion", "demon", "traveler", "fabled"]
_ICON_SIZE = 70
_ICON_GAP = 10
_SEC_PAD = 24
_HEADER_H = 46
_ROW_H = _ICON_SIZE + 28
_PER_ROW = 7
_FONT_CACHE: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = f"font_{size}"
    if key not in _FONT_CACHE:
        try:
            _FONT_CACHE[key] = ImageFont.truetype("arial.ttf", size)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def _ensure_cache_dirs() -> None:
    os.makedirs(ICON_CACHE, exist_ok=True)
    os.makedirs(SCRIPT_CACHE, exist_ok=True)


def _load_icon(role_id: str) -> Image.Image:
    cache = os.path.join(ICON_CACHE, f"{role_id}.png")
    if os.path.isfile(cache):
        return Image.open(cache).convert("RGBA")
    url = _token_image_url(role_id)
    try:
        data = urllib.request.urlopen(url, timeout=10).read()
        with open(cache, "wb") as f:
            f.write(data)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        fallback = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (60, 60, 60, 255))
        return fallback


def generate_script_image(edition_key: str) -> bytes:
    _ensure_cache_dirs()
    edition_name = EDITION_NAMES.get(edition_key, edition_key.upper())
    roles = [r for r in ALL_ROLES if r.get("edition") == edition_key]

    grouped: dict[str, list[dict]] = {t: [] for t in _TEAM_ORDER}
    for r in roles:
        t = r["team"]
        if t in grouped:
            grouped[t].append(r)

    w = _PER_ROW * (_ICON_SIZE + _ICON_GAP) - _ICON_GAP + _SEC_PAD * 2
    y_pos = 0
    sections: list[tuple[str, list[dict], int]] = []
    y_pos += 90  # title

    for team in _TEAM_ORDER:
        members = grouped.get(team, [])
        if not members:
            continue
        rows = (len(members) + _PER_ROW - 1) // _PER_ROW
        sec_h = _HEADER_H + 8 + rows * _ROW_H + _SEC_PAD
        sections.append((team, members, y_pos))
        y_pos += sec_h

    h = y_pos
    img = Image.new("RGBA", (w, h), (30, 30, 35, 255))
    draw = ImageDraw.Draw(img)

    tf = _get_font(28)
    draw.text((w // 2, 32), edition_name, fill=(255, 255, 255), font=tf, anchor="mm")

    for team, members, y_start in sections:
        color = _TEAM_HEADER_COLORS.get(team, (100, 100, 100))
        draw.rounded_rectangle(
            [(_SEC_PAD, y_start), (w - _SEC_PAD, y_start + _HEADER_H)],
            radius=6, fill=color,
        )
        hf = _get_font(18)
        draw.text(
            (_SEC_PAD + 14, y_start + _HEADER_H // 2),
            _TEAM_LABELS.get(team, team),
            fill=(255, 255, 255), font=hf, anchor="lm",
        )

        y = y_start + _HEADER_H + 8
        x = _SEC_PAD
        nf = _get_font(12)
        for i, role in enumerate(members):
            if i and i % _PER_ROW == 0:
                x = _SEC_PAD
                y += _ROW_H
            icon = _load_icon(role["id"]).resize((_ICON_SIZE, _ICON_SIZE))
            img.paste(icon, (x, y), icon)
            name = role["name"]
            if draw.textlength(name, font=nf) > _ICON_SIZE + _ICON_GAP - 4:
                name = name[:10] + ".."
            draw.text(
                (x + _ICON_SIZE // 2, y + _ICON_SIZE + 4),
                name, fill=(200, 200, 200), font=nf, anchor="mt",
            )
            x += _ICON_SIZE + _ICON_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
