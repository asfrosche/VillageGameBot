"""
Stats card — Pokémon Card × Arcade Game aesthetic.
  • Thick gold border with inner trim
  • Deep navy background
  • Coloured "type badge" section titles
  • HP-bar style winrate
  • All data fits (dynamic height)
"""

import os, aiohttp, tempfile
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps


# ─────────────────────────────────────── helpers ──────────────────────────────

def _rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _font(size: int, bold: bool = False):
    for p in (
        ("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        ("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
    ):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _rr(draw, box, r=8, fill=None, outline=None, w=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)


def _pill(draw, cx, cy, label, font, bg, text_col, px=14, py=5):
    """Draw a coloured pill-shaped badge and return its right edge."""
    tw = int(draw.textlength(label, font=font))
    x1, y1 = cx, cy
    x2, y2 = cx + tw + px * 2, cy + font.size + py * 2
    _rr(draw, [x1, y1, x2, y2], r=(y2 - y1) // 2, fill=_rgb(bg))
    draw.text((x1 + px, y1 + py), label, font=font, fill=_rgb(text_col))
    return x2


def _bar(draw, x, y, w, h, pct, bg, fill):
    r = h // 2
    _rr(draw, [x, y, x + w, y + h], r=r, fill=_rgb(bg))
    fw = max(int(w * min(pct, 100) / 100), 0)
    if fw >= r * 2:
        _rr(draw, [x, y, x + fw, y + h], r=r, fill=_rgb(fill))


def _hp_bar(draw, x, y, w, h, pct, bg):
    """HP-style bar: green→yellow→red depending on %."""
    fill = "#4caf50" if pct >= 50 else ("#ff9800" if pct >= 25 else "#f44336")
    _bar(draw, x, y, w, h, pct, bg, fill)


def _divider(draw, x1, x2, y, color):
    draw.line([x1, y, x2, y], fill=_rgb(color), width=1)


# ─────────────────────────────────────── main ────────────────────────────────

async def generate_stats_card(user, stats) -> str:

    # ── Palette ──────────────────────────────────────────────────────────────
    GOLD        = "#f5c518"
    GOLD_INNER  = "#c9a227"
    GOLD_DEEP   = "#7a5c00"
    CARD_BG     = "#0e1428"     # deep navy
    HEADER_BG   = "#080e1e"
    SEC_BG      = "#141b30"
    BORDER_MID  = "#1e2a44"
    WHITE       = "#f0f0f0"
    GRAY        = "#8b93a8"
    DIM         = "#4a5168"
    BAR_BG      = "#1c2540"

    # type-badge colours
    TYPE_BLUE   = "#2980b9"    # water  → roles
    TYPE_GREEN  = "#27ae60"    # grass  → allies
    TYPE_RED    = "#c0392b"    # fire   → nemeses
    TYPE_PURPLE = "#8e44ad"    # psychic→ form

    # ── Dimensions ───────────────────────────────────────────────────────────
    W       = 700
    BORDER  = 10        # gold border thickness
    M       = BORDER + 6
    PAD     = 12
    GAP     = 10
    ROW_H   = 30
    BAR_H   = 9

    allies  = stats.get("top_allies",  [])[:5]
    nemeses = stats.get("top_nemeses", [])[:5]
    roles   = [(n, stats["team_stats"].get(n, {"total": 0, "wins": 0}))
               for n in ["Village", "Evil", "Random Killer", "Neutral"]
               if stats["team_stats"].get(n, {"total": 0})["total"] > 0]

    def sec_h(n): return 32 + n * ROW_H + 8      # section box height

    left_col_h  = sec_h(len(roles))
    right_col_h = sec_h(len(allies)) + GAP + sec_h(len(nemeses))
    body_h      = max(left_col_h, right_col_h)

    HEADER_H = 100
    FORM_H   = 34
    H = M + HEADER_H + GAP + FORM_H + GAP + body_h + M + 4

    # ── Canvas ───────────────────────────────────────────────────────────────
    img  = Image.new("RGB", (W, H), _rgb("#000000"))
    draw = ImageDraw.Draw(img)

    # Gold border layers (outer → inner)
    _rr(draw, [0, 0, W - 1, H - 1],      r=20, fill=_rgb(GOLD))
    _rr(draw, [3, 3, W - 4, H - 4],      r=18, fill=_rgb(GOLD_INNER))
    _rr(draw, [BORDER - 2, BORDER - 2,
               W - BORDER + 1, H - BORDER + 1], r=14, fill=_rgb(GOLD_DEEP))
    # Card face
    _rr(draw, [BORDER, BORDER, W - BORDER, H - BORDER],
        r=12, fill=_rgb(CARD_BG))

    # ── Fonts ─────────────────────────────────────────────────────────────────
    f_name  = _font(26, bold=True)
    f_head  = _font(16, bold=True)
    f_badge = _font(13, bold=True)
    f_body  = _font(15)
    f_small = _font(13)

    # ── Data ─────────────────────────────────────────────────────────────────
    total_wins  = stats["wins_as_player"] + stats["wins_as_sponsor"]
    total_games = stats["total_participations"]
    wr          = round(total_wins / total_games * 100) if total_games else 0
    arrow       = "^" if stats["cws"] > 0 else ("v" if stats["cls"] > 0 else "~")
    cs_sign     = "+" if stats["cws"] > 0 else ("-" if stats["cls"] > 0 else "")
    cs_val      = stats["cws"] if stats["cws"] > 0 else stats["cls"]
    form_str    = "  ".join(list(stats["form"]))

    IX = M + PAD + 6
    IY = M

    # ── HEADER ───────────────────────────────────────────────────────────────
    _rr(draw, [M, IY, W - M, IY + HEADER_H], r=10, fill=_rgb(HEADER_BG))

    # Player name
    draw.text((IX, IY + 10), user.display_name[:22], font=f_name, fill=_rgb(WHITE))

    # HP label (top right of header)
    hp_label = f"HP  {total_wins}/{total_games}  ({wr}%)"
    hp_tw = int(draw.textlength(hp_label, font=f_head))
    hp_x  = W - M - hp_tw - 90   # leave room for avatar
    draw.text((hp_x, IY + 12), hp_label, font=f_head, fill=_rgb(GOLD))

    # HP bar
    _hp_bar(draw, hp_x, IY + 36, hp_tw + 4, BAR_H, wr, BAR_BG)

    # Roles + streaks
    draw.text((IX, IY + 50),
              f"{stats['games_as_player']} Player     {stats['games_as_sponsor']} Sponsor",
              font=f_body, fill=_rgb(GRAY))
    draw.text((IX, IY + 74),
              f"Longest Win Streak: {stats['ws']}     Longest Loss Streak: {stats['ls']}",
              font=f_small, fill=_rgb(DIM))

    # Thin gold divider under name
    draw.line([IX, IY + 42, hp_x - 10, IY + 42], fill=_rgb(GOLD_DEEP), width=1)

    # ── AVATAR ────────────────────────────────────────────────────────────────
    A  = 76
    ax = W - M - A - 10
    ay = IY + 8
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(user.display_avatar.url)) as resp:
                if resp.status == 200:
                    av = Image.open(BytesIO(await resp.read())).convert("RGBA")
                    av = av.resize((A, A), Image.LANCZOS)
                    mask = Image.new("L", (A, A), 0)
                    ImageDraw.Draw(mask).rounded_rectangle([0, 0, A, A], radius=14, fill=255)
                    av.putalpha(mask)
                    img.paste(av, (ax, ay), av)
                    # Gold ring
                    _rr(draw, [ax - 3, ay - 3, ax + A + 3, ay + A + 3],
                        r=17, outline=_rgb(GOLD), w=2)
    except Exception as e:
        print(f"[stats_card] avatar: {e}")

    # ── FORM ROW ─────────────────────────────────────────────────────────────
    fy = IY + HEADER_H + GAP
    _rr(draw, [M, fy, W - M, fy + FORM_H], r=8, fill=_rgb(SEC_BG))
    _pill(draw, M + 6, fy + 5, "FORM", f_badge, TYPE_PURPLE, "#ffffff")
    draw.text((M + 80, fy + 9), f"Streak  {cs_sign}{cs_val}  ({arrow})",
              font=f_body, fill=_rgb(WHITE))
    draw.text((M + 260, fy + 9), f"Recent:  {form_str}",
              font=f_body, fill=_rgb(GRAY))

    # ── BODY ─────────────────────────────────────────────────────────────────
    by   = fy + FORM_H + GAP
    mid  = W // 2 + 4
    LX1, LX2 = M, mid - GAP // 2
    RX1, RX2 = mid + GAP // 2, W - M
    LW  = LX2 - LX1 - PAD * 2
    RW  = RX2 - RX1 - PAD * 2

    # ── ROLES (left) ─────────────────────────────────────────────────────────
    rsh = sec_h(len(roles))
    _rr(draw, [LX1, by, LX2, by + rsh], r=10, fill=_rgb(SEC_BG))
    _pill(draw, LX1 + 8, by + 6, "ROLES", f_badge, TYPE_BLUE, "#ffffff")
    cy = by + 32
    for tname, td in roles:
        twr = round(td["wins"] / td["total"] * 100)
        draw.text((LX1 + PAD, cy),
                  f"{tname[:13]}  {td['wins']}/{td['total']}  ({twr}%)",
                  font=f_small, fill=_rgb(GRAY))
        _bar(draw, LX1 + PAD, cy + 17, LW, BAR_H, twr, BAR_BG, TYPE_BLUE)
        cy += ROW_H

    # ── ALLIES (right-top) ───────────────────────────────────────────────────
    ash = sec_h(len(allies)) if allies else sec_h(1)
    _rr(draw, [RX1, by, RX2, by + ash], r=10, fill=_rgb(SEC_BG))
    _pill(draw, RX1 + 8, by + 6, "ALLIES", f_badge, TYPE_GREEN, "#ffffff")
    acy = by + 32
    for _, name, wins, games, wr_a in allies:
        wr_p = round(wr_a * 100)
        nm   = name[:10].ljust(10)
        draw.text((RX1 + PAD, acy), f"{nm}  +{wr_p}%  ({wins}/{games})",
                  font=f_small, fill=_rgb(GRAY))
        _bar(draw, RX1 + PAD, acy + 17, RW, BAR_H, wr_p, BAR_BG, TYPE_GREEN)
        acy += ROW_H

    # ── NEMESES (right-bottom) ────────────────────────────────────────────────
    ny  = by + ash + GAP
    nsh = sec_h(len(nemeses)) if nemeses else sec_h(1)
    _rr(draw, [RX1, ny, RX2, ny + nsh], r=10, fill=_rgb(SEC_BG))
    _pill(draw, RX1 + 8, ny + 6, "NEMESES", f_badge, TYPE_RED, "#ffffff")
    ncy = ny + 32
    for _, name, losses, games, lr in nemeses:
        lr_p = round(lr * 100)
        nm   = name[:10].ljust(10)
        draw.text((RX1 + PAD, ncy), f"{nm}  -{lr_p}%  ({losses}/{games})",
                  font=f_small, fill=_rgb(GRAY))
        _bar(draw, RX1 + PAD, ncy + 17, RW, BAR_H, lr_p, BAR_BG, TYPE_RED)
        ncy += ROW_H

    # ── Save ─────────────────────────────────────────────────────────────────
    path = os.path.join(tempfile.gettempdir(), f"stats_{user.id}.png")
    img.save(path, "PNG")
    return path
