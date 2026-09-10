from __future__ import annotations

import io
import os
import urllib.request

from PIL import Image, ImageDraw, ImageFont  # type: ignore[import]

from utils.botc import ALL_ROLES, EDITION_NAMES, _token_image_url

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
        return Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (60, 60, 60, 255))


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
    y_pos += 90

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
