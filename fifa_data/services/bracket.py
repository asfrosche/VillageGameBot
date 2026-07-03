"""
BracketCog — renders the WC26 circular knockout bracket as a PNG using Pillow.
No Playwright / Chromium / system libraries needed.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import traceback
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None

SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))
FIFA_DIR = os.path.dirname(SERVICES_DIR)
MATCHES_PATH = os.path.join(FIFA_DIR, "data", "matches.json")
INDEX_HTML = os.path.join(FIFA_DIR, "data", "index.html")

# ---------------------------------------------------------------------------
# Skeleton data (nums 73–104)
# ---------------------------------------------------------------------------

R32_SKELETON: dict[int, dict[str, str | None]] = {
    73:  {"team1": "South Africa",      "team2": "Canada",          "ground": "Los Angeles (Inglewood)",      "date": "2026-06-28", "time": "12:00 UTC-7"},
    74:  {"team1": "Germany",           "team2": "Paraguay",        "ground": "Boston (Foxborough)",          "date": "2026-06-29", "time": "16:30 UTC-4"},
    75:  {"team1": "Netherlands",       "team2": "Morocco",         "ground": "Monterrey (Guadalupe)",        "date": "2026-06-29", "time": "19:00 UTC-6"},
    76:  {"team1": "Brazil",            "team2": "Japan",           "ground": "Houston",                      "date": "2026-06-29", "time": "12:00 UTC-5"},
    77:  {"team1": "France",            "team2": "Sweden",          "ground": "New York/New Jersey (East Rutherford)", "date": "2026-06-30", "time": "17:00 UTC-4"},
    78:  {"team1": "Ivory Coast",       "team2": "Norway",          "ground": "Dallas (Arlington)",           "date": "2026-06-30", "time": "12:00 UTC-5"},
    79:  {"team1": "Mexico",            "team2": "Ecuador",         "ground": "Mexico City",                  "date": "2026-06-30", "time": "19:00 UTC-6"},
    80:  {"team1": "England",           "team2": "DR Congo",        "ground": "Atlanta",                      "date": "2026-07-01", "time": "12:00 UTC-4"},
    81:  {"team1": "USA",               "team2": "Bosnia & Herzegovina", "ground": "San Francisco Bay Area (Santa Clara)", "date": "2026-07-01", "time": "17:00 UTC-7"},
    82:  {"team1": "Belgium",           "team2": "Senegal",         "ground": "Seattle",                      "date": "2026-07-01", "time": "13:00 UTC-7"},
    83:  {"team1": "Portugal",          "team2": "Croatia",         "ground": "Toronto",                      "date": "2026-07-02", "time": "19:00 UTC-4"},
    84:  {"team1": "Spain",             "team2": "Austria",         "ground": "Los Angeles (Inglewood)",      "date": "2026-07-02", "time": "12:00 UTC-7"},
    85:  {"team1": "Switzerland",       "team2": "Algeria",         "ground": "Vancouver",                    "date": "2026-07-02", "time": "20:00 UTC-7"},
    86:  {"team1": "Argentina",         "team2": "Cape Verde",      "ground": "Miami (Miami Gardens)",        "date": "2026-07-03", "time": "18:00 UTC-4"},
    87:  {"team1": "Colombia",          "team2": "Ghana",           "ground": "Kansas City",                  "date": "2026-07-03", "time": "20:30 UTC-5"},
    88:  {"team1": "Australia",         "team2": "Egypt",           "ground": "Dallas (Arlington)",           "date": "2026-07-03", "time": "13:00 UTC-5"},
}

INNER_SKELETON: dict[int, dict[str, str | None]] = {
    89:  {"ground": "Philadelphia",                        "date": "2026-07-04", "time": "17:00 UTC-4"},
    90:  {"ground": "Houston",                             "date": "2026-07-04", "time": "12:00 UTC-5"},
    91:  {"ground": "New York/New Jersey (East Rutherford)", "date": "2026-07-05", "time": "16:00 UTC-4"},
    92:  {"ground": "Mexico City",                          "date": "2026-07-05", "time": "18:00 UTC-6"},
    93:  {"ground": "Dallas (Arlington)",                   "date": "2026-07-06", "time": "14:00 UTC-5"},
    94:  {"ground": "Seattle",                              "date": "2026-07-06", "time": "17:00 UTC-7"},
    95:  {"ground": "Atlanta",                              "date": "2026-07-07", "time": "12:00 UTC-4"},
    96:  {"ground": "Vancouver",                            "date": "2026-07-07", "time": "13:00 UTC-7"},
    97:  {"ground": "Boston (Foxborough)",                  "date": "2026-07-09", "time": "16:00 UTC-4"},
    98:  {"ground": "Los Angeles (Inglewood)",              "date": "2026-07-10", "time": "12:00 UTC-7"},
    99:  {"ground": "Miami (Miami Gardens)",                "date": "2026-07-11", "time": "17:00 UTC-4"},
    100: {"ground": "Kansas City",                          "date": "2026-07-11", "time": "20:00 UTC-5"},
    101: {"ground": "Dallas (Arlington)",                   "date": "2026-07-14", "time": "14:00 UTC-5"},
    102: {"ground": "Atlanta",                              "date": "2026-07-15", "time": "15:00 UTC-4"},
    104: {"ground": "New York/New Jersey (East Rutherford)", "date": "2026-07-19", "time": "15:00 UTC-4"},
}

NAME_NORMALIZE: dict[str, str] = {
    "Côte d'Ivoire": "Ivory Coast",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Cabo Verde": "Cape Verde",
    "Czechia": "Czech Republic",
    "Türkiye": "Turkey",
    "Korea Republic": "South Korea",
    "United States": "USA",
}

# ---------------------------------------------------------------------------
# Geometry (mirrors the HTML page)
# ---------------------------------------------------------------------------

CX, CY = 0.0, 0.0
RADIUS = {0: 0.91, 1: 0.76, 2: 0.57, 3: 0.39, 4: 0.22, 5: 0.0}
STEP = 360.0 / 32

CHILDREN: dict[int, list[int]] = {
    89: [74, 77], 90: [73, 75], 91: [76, 78], 92: [79, 80],
    93: [83, 84], 94: [81, 82], 95: [86, 88], 96: [85, 87],
    97: [89, 90], 98: [93, 94], 99: [91, 92], 100: [95, 96],
    101: [97, 98], 102: [99, 100],
    104: [101, 102],
}
PARENT: dict[int, int] = {}
for p, kids in CHILDREN.items():
    for c in kids:
        PARENT[c] = p

R32_NUMS = list(range(73, 89))
R32SET = set(R32_NUMS)
NODE_NUMS = R32_NUMS + [89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 104]
ROOT = 104


def _dfs_flags(num: int) -> list[dict]:
    if num in R32SET:
        return [{"num": num, "slot": 0}, {"num": num, "slot": 1}]
    a, b = CHILDREN[num]
    return _dfs_flags(a) + _dfs_flags(b)


FLAG_ORDER = _dfs_flags(ROOT)
_angle_memo: dict[int, float] = {}


def _flag_angle(i: int) -> float:
    return -(i + 0.5) * STEP if i < 16 else (i - 16 + 0.5) * STEP


def _angle_of(num: int) -> float:
    if num in _angle_memo:
        return _angle_memo[num]
    if num in R32SET:
        idxs = [i for i, f in enumerate(FLAG_ORDER) if f["num"] == num]
        a = (_flag_angle(idxs[0]) + _flag_angle(idxs[1])) / 2
    else:
        c1, c2 = CHILDREN[num]
        a = (_angle_of(c1) + _angle_of(c2)) / 2
    _angle_memo[num] = a
    return a


def _pt(radius: float, ang_deg: float) -> tuple[float, float]:
    r = math.radians(ang_deg)
    return (radius * math.sin(r), -radius * math.cos(r))


def _winner_idx(score: dict | None) -> int | None:
    if not score:
        return None
    s = score.get("p") or score.get("et") or score.get("ft")
    if not s or len(s) < 2 or s[0] == s[1]:
        return None
    return 0 if s[0] > s[1] else 1


def _score_label(score: dict | None) -> str:
    if not score:
        return ""
    if score.get("p"):
        base = score.get("et") or score.get("ft") or score["p"]
        return f"{base[0]}-{base[1]}"
    if score.get("et"):
        return f"{score['et'][0]}-{score['et'][1]}"
    if score.get("ft"):
        return f"{score['ft'][0]}-{score['ft'][1]}"
    return ""


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_local_matches() -> list[dict[str, Any]]:
    if not os.path.isfile(MATCHES_PATH):
        logger.warning("matches.json not found at %s", MATCHES_PATH)
        return []
    with open(MATCHES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("completed", []) + data.get("upcoming", [])


def _norm(name: str) -> str:
    return NAME_NORMALIZE.get(name, name)


def _make_score(hs: int, as_: int, winner_id: str | None, home_id: str | None, away_id: str | None) -> dict:
    score: dict = {"ft": [hs, as_]}
    if hs != as_:
        return score
    if winner_id and home_id and away_id:
        if winner_id == home_id:
            score["p"] = [hs + 1, as_]
        elif winner_id == away_id:
            score["p"] = [hs, as_ + 1]
    return score


def _build_local_index(local: list[dict]) -> dict[frozenset[str], dict]:
    idx: dict[frozenset[str], dict] = {}
    for m in local:
        stage = m.get("stage", "")
        if not any(p in stage for p in ("Round of 32", "Round of 16", "Quarter", "Semi", "Final")):
            continue
        home = m.get("home", {}).get("name", "")
        away = m.get("away", {}).get("name", "")
        if not home or not away or home == "?" or away == "?":
            continue
        key = frozenset([_norm(home), _norm(away)])
        idx[key] = m
    return idx


def build_bracket_data(local: list[dict]) -> list[dict]:
    idx = _build_local_index(local)
    result: list[dict] = []

    for num, skel in R32_SKELETON.items():
        entry = dict(skel)
        entry["num"] = num
        entry["round"] = "Round of 32"
        t1, t2 = _norm(skel["team1"] or ""), _norm(skel["team2"] or "")
        key = frozenset([t1, t2])
        lm = idx.get(key)
        if lm is not None:
            home = lm.get("home", {}) or {}
            away = lm.get("away", {}) or {}
            hs = home.get("score")
            as_ = away.get("score")
            if hs is not None and as_ is not None:
                entry["score"] = _make_score(hs, as_, lm.get("winner"), home.get("id"), away.get("id"))
        result.append(entry)

    for num, skel in INNER_SKELETON.items():
        entry = dict(skel)
        entry["num"] = num
        entry["round"] = "Round of 16" if num <= 96 else "Quarter-final" if num <= 100 else "Semi-final" if num <= 102 else "Final"
        result.append(entry)

    result.sort(key=lambda x: x["num"])
    return result


# ---------------------------------------------------------------------------
# Build model (resolve winners through the bracket tree)
# ---------------------------------------------------------------------------

def _build_model(ko_matches: list[dict]) -> dict[int, dict]:
    feed: dict[int, dict] = {m["num"]: m for m in ko_matches}
    node: dict[int, dict] = {}
    _w: dict[int, str | None] = {}

    def participants(num: int):
        if num in R32SET:
            m = feed.get(num, {})
            return [m.get("team1"), m.get("team2")]
        c1, c2 = CHILDREN[num]
        return [_wof(c1), _wof(c2)]

    def _wof(num: int) -> str | None:
        if num in _w:
            return _w[num]
        p = participants(num)
        sc = feed.get(num, {}).get("score")
        idx = _winner_idx(sc)
        w = p[idx] if (idx is not None and p[idx]) else None
        _w[num] = w
        return w

    for num in NODE_NUMS:
        p = participants(num)
        m = feed.get(num, {})
        sc = m.get("score")
        rnd = m.get("round", "")
        if not rnd:
            if num in R32SET:
                rnd = "Round of 32"
            elif num <= 96:
                rnd = "Round of 16"
            elif num <= 100:
                rnd = "Quarter-final"
            elif num <= 102:
                rnd = "Semi-final"
            else:
                rnd = "Final"
        node[num] = {"participants": p, "winner": _wof(num), "score": sc, "label": _score_label(sc), "round": rnd}
    return node


# ---------------------------------------------------------------------------
# Pillow renderer
# ---------------------------------------------------------------------------

BG = (242, 237, 225)
INK = (28, 27, 24)
LINE = (42, 40, 35)
MUTED = (154, 148, 138)
GOLD = (200, 162, 74)
RED = (209, 73, 58)
BLUE = (84, 113, 168)
GREEN = (61, 139, 87)
WHITE = (255, 255, 255)

ROUND_COLORS = {
    "Round of 32": GOLD, "Round of 16": MUTED, "Quarter-final": BLUE,
    "Semi-final": GREEN, "Final": RED,
}

SHORT = {
    "South Africa": "RSA", "Canada": "CAN", "Germany": "GER", "Paraguay": "PAR",
    "Netherlands": "NED", "Morocco": "MAR", "Brazil": "BRA", "Japan": "JPN",
    "France": "FRA", "Sweden": "SWE", "Ivory Coast": "CIV", "Norway": "NOR",
    "Mexico": "MEX", "Ecuador": "ECU", "England": "ENG", "DR Congo": "COD",
    "USA": "USA", "Bosnia & Herzegovina": "BIH", "Belgium": "BEL", "Senegal": "SEN",
    "Portugal": "POR", "Croatia": "CRO", "Spain": "ESP", "Austria": "AUT",
    "Switzerland": "SUI", "Algeria": "ALG", "Argentina": "ARG", "Cape Verde": "CPV",
    "Colombia": "COL", "Ghana": "GHA", "Australia": "AUS", "Egypt": "EGY",
}

# Team name → flagcdn ISO 3166-1 alpha-2 code (from the HTML page)
ISO = {
    "South Africa": "za", "Canada": "ca", "Germany": "de", "Paraguay": "py",
    "Netherlands": "nl", "Morocco": "ma", "Brazil": "br", "Japan": "jp",
    "France": "fr", "Sweden": "se", "Ivory Coast": "ci", "Norway": "no",
    "Mexico": "mx", "Ecuador": "ec", "England": "gb-eng", "DR Congo": "cd",
    "USA": "us", "Bosnia & Herzegovina": "ba", "Belgium": "be", "Senegal": "sn",
    "Portugal": "pt", "Croatia": "hr", "Spain": "es", "Austria": "at",
    "Switzerland": "ch", "Algeria": "dz", "Argentina": "ar", "Cape Verde": "cv",
    "Colombia": "co", "Ghana": "gh", "Australia": "au", "Egypt": "eg",
}


def _load_fonts():
    bold_path = score_path = None
    for c in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ]:
        if os.path.isfile(c):
            bold_path = c
            break
    for c in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]:
        if os.path.isfile(c):
            score_path = c
            break
    f_bold = ImageFont.truetype(bold_path, 20) if bold_path else ImageFont.load_default()
    f_score = ImageFont.truetype(bold_path, 34) if bold_path else ImageFont.load_default()
    f_title = ImageFont.truetype(bold_path, 40) if bold_path else ImageFont.load_default()
    f_champ = ImageFont.truetype(bold_path, 48) if bold_path else ImageFont.load_default()
    return f_bold, f_score, f_title, f_champ


def _bezier(t, a, b, ctrl):
    return (
        (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * ctrl[0] + t ** 2 * b[0],
        (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * ctrl[1] + t ** 2 * b[1],
    )


# ── Flag image cache ──

# Shared flag-circle sizing — used for EVERY round (R32, R16, QF, SF, Final).
# All circular team markers have the same visible diameter.
FLAG_RADIUS = 56
FLAG_DIAMETER = FLAG_RADIUS * 2
FLAG_BORDER_WIDTH = 4

_flag_cache: dict[str, Image.Image | None] = {}


def _get_flag(team: str) -> Image.Image | None:
    if team in _flag_cache:
        return _flag_cache[team]
    iso = ISO.get(team)
    if not iso:
        _flag_cache[team] = None
        return None
    try:
        import requests
        url = f"https://flagcdn.com/w160/{iso}.png"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            flag = Image.open(io.BytesIO(resp.content))
            flag = flag.resize((FLAG_DIAMETER, FLAG_DIAMETER), Image.LANCZOS)
            flag = flag.convert("RGBA")
            _flag_cache[team] = flag
            return flag
    except Exception:
        pass
    _flag_cache[team] = None
    return None


def draw_flag_circle(
    image: Image.Image,
    draw: ImageDraw.Draw,
    center: tuple[float, float],
    team: str,
    *,
    border_color: tuple[int, int, int] | None = None,
    fallback_fill: tuple[int, int, int] | None = None,
    is_winner: bool = False,
    eliminated: bool = False,
    font: ImageFont.ImageFont | None = None,
) -> None:
    cx, cy = int(center[0]), int(center[1])
    border = border_color or (GOLD if is_winner else WHITE)
    r = FLAG_RADIUS
    diam = FLAG_DIAMETER

    flag = _get_flag(team)
    if flag:
        mask = Image.new("L", (diam, diam), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, diam, diam], fill=255)
        image.paste(flag, (cx - diam // 2, cy - diam // 2), mask)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=None, outline=border, width=FLAG_BORDER_WIDTH)
    else:
        fill = fallback_fill or MUTED
        if eliminated:
            fill = tuple(v // 2 + 128 for v in fill)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=fill, outline=border, width=FLAG_BORDER_WIDTH)
        if font:
            txt = SHORT.get(team, team[:3].upper())
            bb = font.getbbox(txt)
            tw = (bb[2] - bb[0]) / 2 if bb else 0
            draw.text((cx - tw, cy - 12), txt, fill=INK, font=font)


def render_png(ko_matches: list[dict]) -> bytes:
    if Image is None:
        raise RuntimeError("Pillow not installed")

    model = _build_model(ko_matches)

    SZ = 2400
    CX, CY = SZ // 2, SZ // 2
    SC = SZ / 2

    img = Image.new("RGB", (SZ, SZ), BG)
    draw = ImageDraw.Draw(img)

    f_bold, f_score, f_title, f_champ = _load_fonts()

    def p2px(x, y):
        return (CX + x * SC, CY + y * SC)

    # Precompute positions
    pos = {}
    for num in NODE_NUMS:
        lvl = 1 if num in R32SET else (2 if num <= 96 else 3 if num <= 100 else 4 if num <= 102 else 5)
        pos[num] = p2px(*_pt(RADIUS[lvl], _angle_of(num)))

    # Outer flag data
    flag_data = []
    for i, f in enumerate(FLAG_ORDER):
        nd = model[f["num"]]
        team = nd["participants"][f["slot"]]
        if not team:
            continue
        flag_data.append({
            "pos": p2px(*_pt(RADIUS[0], _flag_angle(i))),
            "team": team,
            "win": nd["winner"],
            "nd": nd,
            "num": f["num"],
        })

    # ── Connectors ──
    for num in NODE_NUMS:
        if num == ROOT:
            continue
        lvl = 1 if num in R32SET else (2 if num <= 96 else 3 if num <= 100 else 4 if num <= 102 else 5)
        rc, rp = RADIUS[lvl - 1], RADIUS[lvl]
        if num in R32SET:
            idxs = [i for i, ff in enumerate(FLAG_ORDER) if ff["num"] == num]
            a1c, a2c = _flag_angle(idxs[0]), _flag_angle(idxs[1])
        else:
            c1, c2 = CHILDREN[num]
            a1c, a2c = _angle_of(c1), _angle_of(c2)
        ap = _angle_of(num)
        A1, A2 = p2px(*_pt(rp, a1c)), p2px(*_pt(rp, a2c))
        C1, C2 = p2px(*_pt(rc, a1c)), p2px(*_pt(rc, a2c))
        P = p2px(*_pt(rp, ap))

        draw.line([C1, A1], fill=LINE, width=4)
        draw.line([C2, A2], fill=LINE, width=4)

        ctrl = (2 * P[0] - 0.5 * (A1[0] + A2[0]), 2 * P[1] - 0.5 * (A1[1] + A2[1]))
        prev = A1
        for j in range(1, 41):
            ptc = _bezier(j / 40, A1, A2, ctrl)
            draw.line([prev, ptc], fill=LINE, width=4)
            prev = ptc

    # Center lines
    sf1 = p2px(*_pt(RADIUS[4], _angle_of(101)))
    sf2 = p2px(*_pt(RADIUS[4], _angle_of(102)))
    draw.line([(CX, CY), sf1], fill=LINE, width=4)
    draw.line([(CX, CY), sf2], fill=LINE, width=4)

    def _draw_label(d, cx, cy, text, font, fill=INK):
        bb = font.getbbox(text)
        tw = (bb[2] - bb[0]) / 2 if bb else 0
        d.text((cx - tw, cy - 12), text, fill=fill, font=font)

    # ── Inner-ring nodes ──
    for num in NODE_NUMS:
        if num == ROOT:
            continue
        nd = model[num]
        px, py = pos[num]
        if nd["winner"]:
            draw_flag_circle(img, draw, (px, py), nd["winner"],
                             is_winner=True, font=f_bold)
        else:
            draw.ellipse([px - 10, py - 10, px + 10, py + 10], fill=LINE)

    # ── Outer flags (with flagcdn images) ──
    for fd in flag_data:
        fx, fy = fd["pos"]
        team = fd["team"]
        win = fd["win"]
        nd = fd["nd"]

        draw_flag_circle(
            img, draw, (fx, fy), team,
            border_color=GOLD if (win == team) else WHITE,
            fallback_fill=ROUND_COLORS.get(nd.get("round", "Round of 32"), MUTED),
            is_winner=(win == team),
            eliminated=(win is not None and win != team),
            font=f_bold,
        )

        # Score label (drawn at the match-node level)
        score_text = _score_label(nd.get("score"))
        if score_text:
            sn = fd["num"]
            ang = _angle_of(sn)
            slvl = 1 if sn in R32SET else (2 if sn <= 96 else 3 if sn <= 100 else 4 if sn <= 102 else 5)
            sp = p2px(*_pt(RADIUS[slvl] + 0.04, ang))
            bb = f_score.getbbox(score_text)
            sw = (bb[2] - bb[0]) / 2 if bb else 0
            draw.text((sp[0] - sw, sp[1] - 11), score_text, fill=INK, font=f_score)

    # ── Center: champion or trophy ──
    final_nd = model[ROOT]
    if final_nd["winner"]:
        team = final_nd["winner"]
        txt = SHORT.get(team, team[:3].upper())
        r = 80
        draw.ellipse([CX - r, CY - r, CX + r, CY + r], fill=GOLD, outline=WHITE, width=6)
        _draw_label(draw, CX, CY - 10, txt, f_champ)
        _draw_label(draw, CX, CY + 40, "CHAMPIONS", f_bold, GOLD)
    else:
        r = 55
        draw.ellipse([CX - r, CY - r, CX + r, CY + r], fill=None, outline=LINE, width=4)
        _draw_label(draw, CX, CY, "🏆", f_title)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def _concise_pw_error(msg: str) -> str:
    """Short user-facing error — no install instructions, just the fact."""
    import re
    if "error while loading shared libraries" in msg:
        m = re.search(r"lib\S+\.so", msg)
        lib = m.group(0) if m else "unknown library"
        return f"System library missing: {lib}"
    if "Executable doesn't exist" in msg or "Executable not found" in msg:
        return "Chromium executable not found"
    if "Target page, context or browser has been closed" in msg:
        return "Chromium crashed on launch (missing system library)"
    return msg[:300]

# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class BracketCog(commands.Cog):
    _pw_ready: bool = False
    _pw_error: str = ""
    _pw_info: dict = {}

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._pw_check()

    # ------------------------------------------------------------------
    # Playwright readiness check (runs at cog load)
    # ------------------------------------------------------------------

    def _pw_check(self) -> None:
        """Synchronous check at cog load: verify playwright package is importable."""
        try:
            import playwright
            # __version__ is not available on all playwright versions;
            # use importlib metadata as a reliable fallback.
            try:
                from importlib.metadata import version as _pvw
                ver = _pvw("playwright")
            except Exception:
                ver = getattr(playwright, "__version__", "unknown")
            self._pw_info["pw_version"] = ver
            logger.info("[Playwright] Import OK  (version %s)", ver)
        except ImportError:
            self._pw_error = "playwright package not installed"
            logger.warning("[Playwright] Import FAILED — package missing")

    @staticmethod
    def _extract_deb(deb_path: str, dest_dir: str) -> bool:
        """Extract a .deb file into dest_dir using dpkg-deb (if available) or ar+tar."""
        import subprocess
        # Prefer dpkg-deb (handles all compression formats: gz, xz, zst)
        try:
            r = subprocess.run(
                ["dpkg-deb", "-x", deb_path, dest_dir],
                capture_output=True, timeout=30,
            )
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            pass
        # Fallback: parse ar manually
        import tarfile
        with open(deb_path, "rb") as fh:
            deb_data = fh.read()
        pos = 8
        while pos < len(deb_data) - 60:
            raw_name = deb_data[pos:pos+16].rstrip(b' /')
            size_str = deb_data[pos+48:pos+58].rstrip(b' ').decode("ascii", errors="replace")
            if not size_str.isdigit():
                break
            size = int(size_str)
            pos += 60
            chunk = deb_data[pos:pos + size]
            pos += (size + 1) & ~1
            if raw_name in (b"data.tar.gz", b"data.tar.xz"):
                mode = "r:gz" if raw_name == b"data.tar.gz" else "r:xz"
                try:
                    with tarfile.open(fileobj=io.BytesIO(chunk), mode=mode) as tf:
                        tf.extractall(path=dest_dir)
                    return True
                except Exception:
                    return False
            if raw_name == b"data.tar.zst":
                # Try zstandard if installed, or zstd CLI
                try:
                    import zstandard
                    dctx = zstandard.ZstdDecompressor()
                    with dctx.stream_reader(io.BytesIO(chunk)) as reader:
                        with tarfile.open(fileobj=reader, mode="r|") as tf:
                            tf.extractall(path=dest_dir)
                    return True
                except ImportError:
                    pass
                try:
                    r2 = subprocess.run(
                        ["zstd", "-d", "-c"],
                        input=chunk, capture_output=True, timeout=30,
                    )
                    if r2.returncode == 0:
                        with tarfile.open(fileobj=io.BytesIO(r2.stdout), mode="r:") as tf:
                            tf.extractall(path=dest_dir)
                        return True
                except FileNotFoundError:
                    pass
                return False
        return False

    @staticmethod
    def _deb_url(pkg: str) -> str | None:
        """Fetch the latest amd64 .deb URL for a package from the Ubuntu archive."""
        import re as _re
        # Pool subdirectory for each package
        subdirs: dict[str, str] = {
            "libnspr4": "n/nspr",
            "libnss3": "n/nss",
            "libatk1.0-0": "a/atk1.0",
            "libatk-bridge2.0-0": "a/at-spi2-atk",
            "libcups2": "c/cups",
            "libxcomposite1": "libx/libxcomposite",
            "libxdamage1": "libx/libxdamage",
            "libatspi2.0-0": "a/at-spi2-core",
        }
        sub = subdirs.get(pkg)
        if not sub:
            return None
        pool_url = f"http://archive.ubuntu.com/ubuntu/pool/main/{sub}/"
        try:
            import requests as _req
            resp = _req.get(pool_url, timeout=15)
            if resp.status_code != 200:
                return None
            # Find amd64 .deb files matching the package name
            pattern = _re.compile(
                _re.escape(pkg) + r"_([\w.~-]+)_amd64\.deb"
            )
            candidates = pattern.findall(resp.text)
            if not candidates:
                return None

            def _vkey(v: str) -> tuple:
                return tuple(
                    int(p) for p in _re.sub(r"[^\d.]", ".", v).split(".") if p.isdigit()
                )
            latest_ver = max(candidates, key=_vkey)
            return f"{pool_url}{pkg}_{latest_ver}_amd64.deb"
        except Exception:
            return None

    @staticmethod
    def _bundle_libs(sonames: list[str]) -> bool:
        """Download missing .so files into ~/.local/share/pw-libs (no root, no apt needed)."""
        import subprocess
        if not sonames:
            return False

        soname_to_pkg: dict[str, str] = {
            "libnspr4.so": "libnspr4",
            "libnss3.so": "libnss3",
            "libnssutil3.so": "libnss3",
            "libsmime3.so": "libnss3",
            "libatk-1.0.so.0": "libatk1.0-0",
            "libatk-bridge-2.0.so.0": "libatk-bridge2.0-0",
            "libcups.so.2": "libcups2",
            "libXcomposite.so.1": "libxcomposite1",
            "libXdamage.so.1": "libxdamage1",
            "libatspi.so.0": "libatspi2.0-0",
        }
        pkgs: set[str] = set()
        for line in sonames:
            name = line.split()[0]
            if name in soname_to_pkg:
                pkgs.add(soname_to_pkg[name])
        if not pkgs:
            return False

        lib_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "pw-libs")
        os.makedirs(lib_dir, exist_ok=True)
        logger.info("[Playwright] Bundling missing libs into %s", lib_dir)

        # Strategy 1: apt-get download (works on many Debian containers)
        apt_worked = False
        try:
            r = subprocess.run(
                ["apt-get", "download"] + sorted(pkgs),
                cwd=lib_dir, capture_output=True, timeout=120,
            )
            apt_worked = r.returncode == 0
        except FileNotFoundError:
            pass
        if apt_worked:
            logger.info("[Playwright] apt-get download succeeded")
        else:
            logger.info("[Playwright] apt-get not available, trying direct HTTP download ...")
            import requests as req_mod
            for pkg in sorted(pkgs):
                url = BracketCog._deb_url(pkg)
                if not url:
                    continue
                clean_url = url.split('"')[0]
                try:
                    resp = req_mod.get(clean_url, timeout=60)
                    if resp.status_code == 200:
                        deb_file = os.path.join(lib_dir, f"{pkg}.deb")
                        with open(deb_file, "wb") as fh:
                            fh.write(resp.content)
                        logger.info("[Playwright] Downloaded %s (%d bytes)", clean_url, len(resp.content))
                    else:
                        logger.warning("[Playwright] HTTP %d for %s", resp.status_code, clean_url)
                except Exception as exc:
                    logger.warning("[Playwright] Failed to download %s: %s", clean_url, exc)

        # Extract all .deb files found in lib_dir
        for fname in os.listdir(lib_dir):
            if not fname.endswith(".deb"):
                continue
            deb_path = os.path.join(lib_dir, fname)
            if BracketCog._extract_deb(deb_path, lib_dir):
                logger.info("[Playwright] Extracted %s", fname)
            else:
                logger.warning("[Playwright] Failed to extract %s", fname)
            try:
                os.remove(deb_path)
            except Exception:
                pass

        # Set LD_LIBRARY_PATH to include all dirs with .so files
        so_dirs: set[str] = set()
        for root, _dirs, files in os.walk(lib_dir):
            for f in files:
                if f.endswith(".so") or ".so." in f:
                    so_dirs.add(root)
        if so_dirs:
            existing = os.environ.get("LD_LIBRARY_PATH", "")
            new_path = ":".join(sorted(so_dirs))
            os.environ["LD_LIBRARY_PATH"] = f"{new_path}:{existing}" if existing else new_path
            logger.info("[Playwright] LD_LIBRARY_PATH += %s", new_path)
            return True
        return False

    async def _diagnose_launch(self) -> dict:
        """Run comprehensive diagnostics on the Chromium environment, auto-fix if needed."""
        import platform, subprocess
        diag: dict = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pw_version": self._pw_info.get("pw_version", "unknown"),
            "binary_path": None,
            "binary_exists": None,
            "binary_executable": None,
            "ldd_not_found": [],
            "ldd_all_ok": None,
            "libs_bundled": False,
        }
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        try:
            exe = pw.chromium.executable_path
            diag["binary_path"] = exe
            diag["binary_exists"] = os.path.exists(exe)
            if diag["binary_exists"]:
                diag["binary_executable"] = os.access(exe, os.X_OK)
                try:
                    ldd = subprocess.run(
                        ["ldd", exe], capture_output=True, text=True, timeout=10,
                    )
                    for line in ldd.stdout.splitlines():
                        if "not found" in line:
                            diag["ldd_not_found"].append(line.strip())
                    diag["ldd_all_ok"] = len(diag["ldd_not_found"]) == 0
                except FileNotFoundError:
                    pass
        finally:
            await pw.stop()

        logger.info("[Playwright] === Diagnostic report ===")
        logger.info("[Playwright] Python: %s", diag["python"])
        logger.info("[Playwright] Platform: %s", diag["platform"])
        logger.info("[Playwright] Playwright version: %s", diag["pw_version"])
        logger.info("[Playwright] Chromium executable: %s", diag["binary_path"])
        logger.info("[Playwright]   Exists: %s", diag["binary_exists"])
        logger.info("[Playwright]   Executable: %s", diag["binary_executable"])
        if diag["ldd_not_found"]:
            logger.error("[Playwright]   Missing system libraries: %d", len(diag["ldd_not_found"]))
            for lib in diag["ldd_not_found"]:
                logger.error("[Playwright]     %s", lib)
            # Auto-fix: download & extract into ~/.local/share/pw-libs
            diag["libs_bundled"] = self._bundle_libs(diag["ldd_not_found"])
            if diag["libs_bundled"]:
                logger.info("[Playwright] Libs bundled, re-running ldd...")
                pw2 = await async_playwright().start()
                try:
                    exe2 = pw2.chromium.executable_path
                    ldd2 = subprocess.run(
                        ["ldd", exe2], capture_output=True, text=True, timeout=10,
                    )
                    diag["ldd_not_found"] = [
                        l for l in ldd2.stdout.splitlines() if "not found" in l
                    ]
                    diag["ldd_all_ok"] = len(diag["ldd_not_found"]) == 0
                    logger.info("[Playwright]   After bundle — missing: %d",
                                len(diag["ldd_not_found"]))
                    for lib in diag["ldd_not_found"]:
                        logger.error("[Playwright]     %s", lib)
                finally:
                    await pw2.stop()
        else:
            logger.info("[Playwright]   ldd: all libraries resolved" if diag["ldd_all_ok"] else "[Playwright]   ldd: not checked (non-Linux)")

        # Log the chromium install directory structure
        for root in (
            os.path.expanduser("~/.cache/ms-playwright"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
            os.path.join(os.environ.get("HOME", ""), "Library", "Caches", "ms-playwright"),
        ):
            if os.path.isdir(root):
                entries = os.listdir(root)
                logger.info("[Playwright] Install dir %s contains: %s", root, entries)
                break

        return diag

    async def ensure_playwright_ready(self) -> bool:
        """Async check: run diagnostics + attempt launch. Caches result."""
        if self._pw_ready:
            return True
        if self._pw_error:
            return False

        import time as time_module
        diag = await self._diagnose_launch()
        self._pw_info.update(diag)

        t0 = time_module.monotonic()
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                await browser.close()
            elapsed = time_module.monotonic() - t0
            logger.info("[Playwright] Launch successful  (%.2fs)", elapsed)
            self._pw_ready = True
            self._pw_error = ""
            return True
        except Exception as exc:
            elapsed = time_module.monotonic() - t0
            logger.error("[Playwright] Launch FAILED after %.2fs", elapsed)
            logger.error("[Playwright] Exception type: %s", type(exc).__name__)
            logger.error("[Playwright] Exception message: %s", exc)
            import traceback as tb_mod
            tb = "".join(tb_mod.TracebackException.from_exception(exc).format())
            logger.error("[Playwright] Full traceback:\n%s", tb)

            import re
            msg = str(exc)
            if "error while loading shared libraries" in msg:
                m = re.search(r"lib\S+\.so", msg)
                lib = m.group(0) if m else "unknown"
                logger.error("[Playwright] Root cause: missing system library `%s`", lib)
                logger.error("[Playwright] Resolve: install the missing library or rebuild the container image with it included")
            elif diag.get("ldd_not_found"):
                logger.error("[Playwright] Root cause: %d unresolved system libraries", len(diag["ldd_not_found"]))
            self._pw_error = _concise_pw_error(msg)
            return False

    # ------------------------------------------------------------------
    # .bracket  — Pillow renderer (no external dependencies)
    # ------------------------------------------------------------------

    @commands.command(name="bracket")
    async def bracket(self, ctx: commands.Context) -> None:
        if Image is None:
            await ctx.send("Pillow is required but not installed.")
            return

        async with ctx.typing():
            step = "initialising"
            try:
                step = "load_local_matches"
                local = load_local_matches()
                if not local:
                    await ctx.send("No match data found.")
                    return

                step = "build_bracket_data"
                ko = build_bracket_data(local)

                step = "render_png"
                png = render_png(ko)
                logger.info("[bracket] rendered %d bytes", len(png))

                step = "discord_upload"
                with io.BytesIO(png) as fp:
                    fp.seek(0)
                    await ctx.send(file=discord.File(fp, filename="bracket.png"))
                logger.info("[bracket] done")

            except Exception:
                logger.exception("[bracket] crashed at '%s'", step)
                tb = traceback.format_exc()
                if len(tb) > 3500:
                    tb = tb[:3500] + "\n... (truncated)"
                await ctx.send(
                    f"**Bracket command failed.**\n"
                    f"Step: `{step}`\n"
                    f"```\n{tb}\n```"
                )

    # ------------------------------------------------------------------
    # .brackets  — Playwright renderer (needs chromium installed)
    # ------------------------------------------------------------------

    @commands.command(name="brackets")
    async def brackets(self, ctx: commands.Context) -> None:
        """Render the bracket via Playwright + local index.html (needs chromium installed)."""
        if not await self.ensure_playwright_ready():
            missing_count = len(self._pw_info.get("ldd_not_found", []))
            detail = ""
            if missing_count:
                detail = f" ({missing_count} missing system libraries — container lacks them)"
            elif self._pw_error:
                detail = f" — {self._pw_error}"
            await ctx.send(
                f"**Playwright is unavailable{detail}.** "
                f"The `.bracket` command works without Playwright."
            )
            return

        async with ctx.typing():
            playwright_obj = None
            browser = None
            step = "initialising"
            try:
                step = "load_local_matches"
                local = load_local_matches()
                if not local:
                    await ctx.send("No match data found.")
                    return

                step = "build_bracket_data"
                ko_matches = build_bracket_data(local)

                step = "playwright_start"
                from playwright.async_api import async_playwright
                playwright_obj = await async_playwright().start()

                step = "chromium_launch"
                browser = await playwright_obj.chromium.launch(headless=True)

                step = "browser_context"
                context = await browser.new_context(
                    viewport={"width": 1200, "height": 1200},
                )
                page = await context.new_page()

                step = "page_navigate"
                html_path = INDEX_HTML.replace("\\", "/")
                if not html_path.startswith("/"):
                    html_path = "/" + html_path
                file_url = "file://" + html_path
                await page.goto(file_url, wait_until="load", timeout=15000)
                await page.wait_for_timeout(1000)

                step = "page_evaluate"
                await page.evaluate(
                    """(data) => {
                        if (typeof render !== 'function' || typeof buildModel !== 'function' || typeof normalize !== 'function') {
                            throw new Error("Page render functions not found");
                        }
                        render(buildModel(normalize(data)));
                    }""",
                    ko_matches,
                )

                step = "settle"
                await page.wait_for_timeout(2500)

                step = "screenshot"
                stage_el = page.locator("#stage")
                if await stage_el.count() == 0:
                    raise RuntimeError("#stage element not found")
                png = await stage_el.screenshot(type="png", omit_background=True)
                logger.info("[brackets] captured %d bytes", len(png))

                step = "discord_upload"
                with io.BytesIO(png) as fp:
                    fp.seek(0)
                    await ctx.send(file=discord.File(fp, filename="bracket.png"))
                logger.info("[brackets] done")

            except Exception:
                logger.exception("[brackets] crashed at '%s'", step)
                await ctx.send(f"**Brackets command failed** at step `{step}`. Check the bot logs.")
            finally:
                if browser is not None:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                if playwright_obj is not None:
                    try:
                        await playwright_obj.stop()
                    except Exception:
                        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BracketCog(bot))
