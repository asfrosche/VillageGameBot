import asyncio
import discord
from discord.ext import commands
import os
import io
import math
import random
import datetime
from PIL import Image, ImageDraw, ImageFont
from cogs.data_utils import load_guild_data


class ChannelMap(commands.Cog):
    _resolved_font_path = None

    def __init__(self, bot):
        self.bot = bot

    # ── Font resolution (mirrors estate_cog.py) ──────────────────────────────

    def _resolve_font(self, size, bold=False):
        if self._resolved_font_path:
            try:
                return ImageFont.truetype(self._resolved_font_path, size)
            except Exception:
                pass

        bold_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"

        font_choices = [
            os.path.join(os.path.dirname(__file__), "..", ".local", "lib",
                         "python3.12", "site-packages", "matplotlib",
                         "mpl-data", "fonts", "ttf", bold_name),
            os.path.join(os.path.dirname(__file__), "..", ".local", "lib",
                         "python3.12", "site-packages", "matplotlib",
                         "mpl-data", "fonts", "ttf", "DejaVuSans.ttf"),
            os.path.join(os.path.dirname(__file__), "..",
                         "NotoSansEgyptianHieroglyphs-Regular.ttf"),
            os.path.join(os.path.dirname(__file__), "..", "papyrus.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "arialbd.ttf",
            "arial.ttf",
            "tahoma.ttf",
            "segoeui.ttf",
        ]

        for f_path in font_choices:
            try:
                font = ImageFont.truetype(f_path, size)
                self._resolved_font_path = f_path
                return font
            except Exception:
                continue

        try:
            search_dirs = [
                os.path.join(os.path.dirname(__file__), "..", ".local"),
                os.path.dirname(__file__),
                os.path.join(os.path.dirname(__file__), ".."),
            ]
            for s_dir in search_dirs:
                if os.path.exists(s_dir):
                    for root, dirs, files in os.walk(s_dir):
                        for file in files:
                            if file.endswith(".ttf") and "DejaVuSans" in file:
                                test_path = os.path.join(root, file)
                                try:
                                    font = ImageFont.truetype(test_path, size)
                                    self._resolved_font_path = test_path
                                    return font
                                except Exception:
                                    pass
        except Exception:
            pass

        return ImageFont.load_default()

    def _get_fonts(self):
        title_font = self._resolve_font(38, bold=True)
        subtitle_font = self._resolve_font(22)
        header_font = self._resolve_font(24, bold=True)
        name_font = self._resolve_font(21)
        count_font = self._resolve_font(18, bold=True)
        small_font = self._resolve_font(16)
        tiny_font = self._resolve_font(13)
        return {
            "title": title_font,
            "subtitle": subtitle_font,
            "header": header_font,
            "name": name_font,
            "count": count_font,
            "small": small_font,
            "tiny": tiny_font,
        }

    # ── Icon helpers ─────────────────────────────────────────────────────────

    def _get_channel_icon(self, name):
        name_lower = name.lower()
        if "radio" in name_lower:
            return "📻"
        if "pc" in name_lower or "computer" in name_lower:
            return "🖥️"
        if "hub" in name_lower or "terminal" in name_lower:
            return "📡"
        if "dead" in name_lower:
            return "💀"
        if "secret" in name_lower or "hidden" in name_lower:
            return "🔒"
        if "faction" in name_lower or "clan" in name_lower or "team" in name_lower:
            return "⚔️"
        if "operation" in name_lower or "op-" in name_lower:
            return "🎯"
        if "broadcast" in name_lower or "announce" in name_lower:
            return "📢"
        if "meeting" in name_lower or "conference" in name_lower:
            return "📞"
        if "rc" in name_lower or "role" in name_lower:
            return "🎭"
        if "alt" in name_lower:
            return "👤"
        if "private" in name_lower:
            return "🔐"
        return "💬"

    # ── Channel data gathering ───────────────────────────────────────────────

    async def _gather_channels(self, guild, category_name, alive_role=None, alt_role=None):
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            return []

        # First pass: collect all qualifying members across channels
        all_members = {}
        channels_raw = []
        for ch in category.text_channels:
            if ch.name == "duplicate-this":
                continue
            member_ids = []
            for member in ch.members:
                if member.bot:
                    continue
                if not ch.permissions_for(member).send_messages:
                    continue
                has_alive = alive_role is not None and alive_role in member.roles
                has_alt = alt_role is not None and alt_role in member.roles
                if not (has_alive or has_alt):
                    continue
                member_ids.append(member.id)
                all_members[member.id] = member
            everyone_overwrites = ch.overwrites_for(guild.default_role)
            channels_raw.append({
                "name": ch.name,
                "member_ids": member_ids,
                "hidden": everyone_overwrites.read_messages is False,
                "channel": ch,
            })

        # Fetch all avatars concurrently
        avatar_map = {}
        async def _fetch_avatar(member):
            try:
                avatar_map[member.id] = await member.display_avatar.replace(size=64).read()
            except Exception:
                avatar_map[member.id] = None
        tasks = [_fetch_avatar(m) for m in all_members.values()]
        if tasks:
            await asyncio.gather(*tasks)

        # Build final channel data
        channels = []
        for ch_raw in channels_raw:
            members = []
            for mid in ch_raw["member_ids"]:
                m = all_members.get(mid)
                if m:
                    members.append({
                        "id": m.id,
                        "name": m.display_name,
                        "avatar": avatar_map.get(mid),
                    })
            channels.append({
                "name": ch_raw["name"],
                "members": members,
                "hidden": ch_raw["hidden"],
                "channel": ch_raw["channel"],
            })

        channels.sort(key=lambda c: (c["hidden"], c["name"]))
        return channels

    # ── Drawing helpers ──────────────────────────────────────────────────────

    def _text_width(self, draw, text, font):
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except AttributeError:
            return draw.textsize(text, font=font)[0]

    def _truncate_text(self, draw, text, font, max_width):
        if self._text_width(draw, text, font) <= max_width:
            return text
        while text and self._text_width(draw, text + "…", font) > max_width:
            text = text[:-1]
        return text + "…" if text else "…"

    def _draw_text_with_shadow(self, draw, x, y, text, font, fill, shadow_offset=2):
        draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), text, font=font, fill=fill)

    # ── Noise / static texture ───────────────────────────────────────────────

    def _apply_noise(self, img, intensity=8):
        px = img.load()
        w, h = img.size
        for _ in range(w * h // 80):
            x = random.randint(0, w - 1)
            y = random.randint(0, h - 1)
            v = random.randint(-intensity, intensity)
            r, g, b, a = px[x, y]
            px[x, y] = (
                max(0, min(255, r + v)),
                max(0, min(255, g + v)),
                max(0, min(255, b + v)),
                a,
            )

    # ── Background ───────────────────────────────────────────────────────────

    def _load_background(self, width, height):
        img = Image.new("RGBA", (width, height), (10, 12, 14, 255))
        try:
            potential_paths = [
                os.path.join(os.path.dirname(__file__), "..", "assets", "contour_wall.jpg"),
                os.path.join(os.path.dirname(__file__), "..", "..", "contour_wall.jpg"),
                os.path.join(os.path.dirname(__file__), "assets", "contour_wall.jpg"),
            ]
            bg = None
            for bg_path in potential_paths:
                if os.path.exists(bg_path):
                    bg = Image.open(bg_path).convert("RGBA")
                    break
            if bg:
                bg_w, bg_h = bg.size
                canvas_ratio = width / height
                bg_ratio = bg_w / bg_h
                if canvas_ratio > bg_ratio:
                    new_h = int(bg_w / canvas_ratio)
                    bg = bg.crop((0, (bg_h - new_h) // 2, bg_w, (bg_h + new_h) // 2))
                else:
                    new_w = int(bg_h * canvas_ratio)
                    bg = bg.crop(((bg_w - new_w) // 2, 0, (bg_w + new_w) // 2, bg_h))
                bg = bg.resize((width, height), Image.LANCZOS)
                img.paste(bg, (0, 0))
                dark_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 160))
                img = Image.alpha_composite(img, dark_overlay)
        except Exception:
            pass
        return img

    # ── Sci-fi border frame ──────────────────────────────────────────────────

    def _draw_sci_fi_frame(self, draw, x1, y1, x2, y2, color, corner_len=24, width=2):
        c = color
        hr = max(corner_len, 12)
        # Top-left corner
        draw.line([(x1, y1 + hr), (x1, y1), (x1 + hr, y1)], fill=c, width=width)
        # Top-right corner
        draw.line([(x2 - hr, y1), (x2, y1), (x2, y1 + hr)], fill=c, width=width)
        # Bottom-left corner
        draw.line([(x1, y2 - hr), (x1, y2), (x1 + hr, y2)], fill=c, width=width)
        # Bottom-right corner
        draw.line([(x2 - hr, y2), (x2, y2), (x2, y2 - hr)], fill=c, width=width)
        # Subtle outer border
        draw.rectangle([x1, y1, x2, y2], outline=(*c[:3], 30), width=1)

    # ── Channel box drawing ──────────────────────────────────────────────────

    def _draw_channel_box(self, draw, img, x, y, box_w, box_h, ch_data, fonts, theme, ctx_width):
        colors = theme["colors"]
        member_count = len(ch_data["members"])
        icon = self._get_channel_icon(ch_data["name"])
        name = ch_data["name"].replace("-", " ").replace("_", " ")

        box_x1 = x
        box_y1 = y
        box_x2 = x + box_w
        box_y2 = y + box_h

        glow_color = colors["glow_normal"]
        if member_count == 0:
            glow_color = colors["glow_empty"]
        elif member_count >= 4:
            glow_color = colors["glow_crowded"]

        glow_w = 3 if member_count == 0 else (4 if member_count < 4 else 5)

        draw.rounded_rectangle(
            [box_x1, box_y1, box_x2, box_y2],
            radius=8,
            fill=colors["card_bg"],
            outline=glow_color,
            width=glow_w,
        )

        # Terminal corner accents on card
        ac_len = 10
        ac_color = (*glow_color[:3], 120)
        draw.line([(box_x1 + 2, box_y1 + ac_len), (box_x1 + 2, box_y1 + 2), (box_x1 + ac_len, box_y1 + 2)], fill=ac_color, width=2)
        draw.line([(box_x2 - 2, box_y1 + ac_len), (box_x2 - 2, box_y1 + 2), (box_x2 - ac_len, box_y1 + 2)], fill=ac_color, width=2)
        draw.line([(box_x1 + 2, box_y2 - ac_len), (box_x1 + 2, box_y2 - 2), (box_x1 + ac_len, box_y2 - 2)], fill=ac_color, width=2)
        draw.line([(box_x2 - 2, box_y2 - ac_len), (box_x2 - 2, box_y2 - 2), (box_x2 - ac_len, box_y2 - 2)], fill=ac_color, width=2)

        if member_count >= 4:
            draw.rounded_rectangle(
                [box_x1 - 2, box_y1 - 2, box_x2 + 2, box_y2 + 2],
                radius=10,
                fill=None,
                outline=colors["warning"],
                width=2,
            )

        header_font = fonts["header"]
        name_font = fonts["name"]
        count_font = fonts["count"]
        small_font = fonts["small"]

        header_text = f"{icon}  {name}"
        max_header_w = box_w - 40
        header_text = self._truncate_text(draw, header_text, header_font, max_header_w)
        hdr_y = box_y1 + 10
        self._draw_text_with_shadow(
            draw, box_x1 + 16, hdr_y, header_text, header_font,
            colors["header_text"], shadow_offset=1
        )

        sep_y = hdr_y + 30
        draw.line(
            [(box_x1 + 14, sep_y), (box_x2 - 14, sep_y)],
            fill=(*colors["separator"][:3], 120),
            width=2,
        )
        draw.line(
            [(box_x1 + 14, sep_y + 3), (box_x2 - 14, sep_y + 3)],
            fill=(*colors["separator"][:3], 30),
            width=1,
        )

        name_y = sep_y + 10
        if member_count == 0:
            empty_text = "[ EMPTY ]"
            etw = self._text_width(draw, empty_text, count_font)
            ex = box_x1 + (box_w - etw) // 2
            ey = box_y1 + (box_h // 2) - 4
            draw.rounded_rectangle(
                [ex - 12, ey - 4, ex + etw + 12, ey + 22],
                radius=4, fill=(*colors["card_bg"][:3], 200),
                outline=(*colors["empty_text"][:3], 60), width=1,
            )
            self._draw_text_with_shadow(
                draw, ex, ey, empty_text, count_font,
                colors["empty_text"], shadow_offset=1
            )
        else:
            avatar_size = 26
            max_names_h = box_h - (name_y - box_y1) - 36
            visible_members = ch_data["members"]
            line_h = max(avatar_size + 4, 28)
            max_show = max(0, int(max_names_h // line_h))
            if max_show == 0:
                max_show = 1

            show_members = visible_members[:max_show]
            overflow = len(visible_members) - len(show_members)

            for i, m in enumerate(show_members):
                my = name_y + i * line_h
                tx = box_x1 + 18

                avatar_bytes = m.get("avatar")
                if avatar_bytes:
                    try:
                        av_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                        av_img = av_img.resize((avatar_size, avatar_size))
                        mask = Image.new("L", (avatar_size, avatar_size), 0)
                        m_draw = ImageDraw.Draw(mask)
                        m_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
                        av_img.putalpha(mask)
                        av_y = my + (line_h - avatar_size) // 2
                        img.paste(av_img, (int(tx), int(av_y)), av_img)
                    except Exception:
                        pass
                    tx += avatar_size + 8

                m_text = m['name']
                m_text = self._truncate_text(draw, m_text, name_font, box_w - (tx - box_x1) - 22)
                ty = my + (line_h - 16) // 2
                self._draw_text_with_shadow(
                    draw, tx, ty, m_text, name_font,
                    colors["player_text"], shadow_offset=1
                )

            if overflow > 0:
                more_y = name_y + len(show_members) * line_h
                more_text = f"+{overflow} more"
                self._draw_text_with_shadow(
                    draw, box_x1 + 18, more_y, more_text, small_font,
                    colors["dim_text"], shadow_offset=1
                )

    # ── Main map draw ────────────────────────────────────────────────────────

    def _draw_map(self, channels, title, subtitle, theme):
        fonts = self._get_fonts()

        if not channels:
            img = Image.new("RGBA", (800, 300), (10, 12, 14, 255))
            draw = ImageDraw.Draw(img, "RGBA")
            draw.text((400, 150), "No Channels Found", font=fonts["title"],
                      fill=theme["colors"]["header_text"], anchor="mm")
            return img.convert("RGB")

        # Layout calculations
        card_w = 330
        card_min_h = 110
        card_pad_x = 20
        card_pad_y = 16
        margin_x = 36
        margin_y_top = 110
        margin_y_bot = 56

        n = len(channels)

        # Dynamic columns
        if n <= 2:
            cols = 2
        elif n <= 6:
            cols = 3
        elif n <= 12:
            cols = 4
        else:
            cols = 4

        rows = math.ceil(n / cols) if n > 0 else 1

        def _calc_card_h(ch_data):
            mc = len(ch_data["members"])
            if mc == 0:
                return card_min_h
            return max(card_min_h, 110 + mc * 30)

        row_heights = []
        for r in range(rows):
            row_channels = channels[r * cols:(r + 1) * cols]
            if row_channels:
                row_heights.append(max(_calc_card_h(c) for c in row_channels))
            else:
                row_heights.append(card_min_h)

        canvas_w = cols * (card_w + card_pad_x) - card_pad_x + margin_x * 2
        canvas_h = sum(row_heights) + card_pad_y * (rows - 1) + margin_y_top + margin_y_bot

        if canvas_w < 400:
            canvas_w = 600
        if canvas_h < 300:
            canvas_h = 350

        img = self._load_background(canvas_w, canvas_h)
        self._apply_noise(img, intensity=6)

        # Vignette overlay — apply BEFORE creating draw so both stay in sync
        vignette = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        v_draw = ImageDraw.Draw(vignette)
        for r in range(canvas_h):
            factor = 1.0 - (r / canvas_h)
            edge = min(r, canvas_h - r, canvas_w // 2) / (canvas_h // 3)
            alpha = int(max(0, min(255, (1.0 - factor) * 60 * edge)))
            if alpha > 0:
                v_draw.line([(0, r), (canvas_w, r)], fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img, vignette)

        draw = ImageDraw.Draw(img, "RGBA")

        # Sci-fi border frame around entire map
        frame_color = theme["colors"]["frame"]
        self._draw_sci_fi_frame(
            draw, 8, 8, canvas_w - 8, canvas_h - 8,
            frame_color, corner_len=30, width=3
        )

        # Title
        title_text = title
        tw = self._text_width(draw, title_text, fonts["title"])
        tx = (canvas_w - tw) // 2
        self._draw_text_with_shadow(draw, tx, 28, title_text, fonts["title"],
                                    theme["colors"]["title_text"])

        # Subtitle
        if subtitle:
            sw = self._text_width(draw, subtitle, fonts["subtitle"])
            sx = (canvas_w - sw) // 2
            self._draw_text_with_shadow(draw, sx, 68, subtitle, fonts["subtitle"],
                                        theme["colors"]["subtitle_text"])

        # Grid layout — draw channel boxes
        for idx, ch_data in enumerate(channels):
            r = idx // cols
            c = idx % cols

            cx = margin_x + c * (card_w + card_pad_x)
            cy = margin_y_top + sum(row_heights[:r]) + r * card_pad_y
            ch = row_heights[r]

            self._draw_channel_box(
                draw, img, cx, cy, card_w, ch, ch_data, fonts, theme, canvas_w
            )

        # Footer HUD
        total_members = sum(len(c["members"]) for c in channels)
        hidden_count = sum(1 for c in channels if c.get("hidden"))
        now_str = datetime.datetime.utcnow().strftime("%H:%M UTC")
        footer_parts = [
            f"TOTAL CHANNELS: {n}",
            f"ACTIVE PLAYERS: {total_members}",
        ]
        if hidden_count:
            footer_parts.append(f"HIDDEN: {hidden_count}")
        footer_text = "  │  ".join(footer_parts)
        footer_right = f"LAST UPDATED: {now_str}"

        fl_font = fonts["tiny"]
        fy = canvas_h - 28
        self._draw_text_with_shadow(draw, 20, fy, footer_text, fl_font,
                                    theme["colors"]["footer_text"], shadow_offset=1)
        fr_w = self._text_width(draw, footer_right, fl_font)
        self._draw_text_with_shadow(draw, canvas_w - fr_w - 20, fy, footer_right,
                                    fl_font, theme["colors"]["footer_text"], shadow_offset=1)

        draw.line([(16, fy - 8), (canvas_w - 16, fy - 8)],
                  fill=(255, 255, 255, 15), width=1)

        self._draw_sci_fi_frame(
            draw, 14, margin_y_top - 6, canvas_w - 14, canvas_h - margin_y_bot + 14,
            theme["colors"]["frame"], corner_len=16, width=1
        )

        return img.convert("RGB")

    # ── Theme definitions ────────────────────────────────────────────────────

    @property
    def _public_theme(self):
        return {
            "name": "public",
            "colors": {
                "title_text": (80, 255, 210),
                "subtitle_text": (160, 255, 220),
                "header_text": (120, 255, 220),
                "player_text": (180, 255, 190),
                "count_text": (0, 255, 160),
                "empty_text": (100, 170, 140),
                "dim_text": (120, 180, 160),
                "footer_text": (100, 220, 180),
                "separator": (0, 220, 170),
                "card_bg": (10, 24, 20, 210),
                "frame": (0, 255, 200),
                "glow_normal": (0, 255, 200, 90),
                "glow_empty": (0, 140, 110, 40),
                "glow_crowded": (255, 200, 0, 130),
                "warning": (255, 180, 0, 110),
            },
        }

    @property
    def _private_theme(self):
        return {
            "name": "private",
            "colors": {
                "title_text": (255, 90, 110),
                "subtitle_text": (255, 150, 160),
                "header_text": (255, 120, 135),
                "player_text": (255, 170, 175),
                "count_text": (255, 70, 90),
                "empty_text": (140, 80, 80),
                "dim_text": (170, 110, 110),
                "footer_text": (220, 100, 100),
                "separator": (200, 60, 60),
                "card_bg": (22, 10, 12, 210),
                "frame": (255, 60, 80),
                "glow_normal": (255, 70, 90, 90),
                "glow_empty": (140, 40, 50, 40),
                "glow_crowded": (255, 120, 0, 130),
                "warning": (255, 110, 0, 110),
            },
        }

    # ── Commands ─────────────────────────────────────────────────────────────

    async def _build_and_send(self, ctx, map_type):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
        alive_role = discord.utils.get(ctx.guild.roles, name="Alive")
        alt_role = discord.utils.get(ctx.guild.roles, name="Alt")

        if alive_role is None and alt_role is None:
            return await ctx.send("Could not find Alive or Alt roles.")

        if map_type in ("public", "both"):
            pub_channels = await self._gather_channels(
                ctx.guild, guild_data.get("publc_category_name", "PUBLIC CHANNELS"), alive_role, alt_role
            )
            pub_count = len(pub_channels)
            pub_title = "PUBLIC CHANNEL MAP"
            pub_subtitle = f"{pub_count} Channels"
            pub_img = self._draw_map(pub_channels, pub_title, pub_subtitle, self._public_theme)
            pub_buf = io.BytesIO()
            pub_img.save(pub_buf, "PNG")
            pub_buf.seek(0)
            pub_file = discord.File(fp=pub_buf, filename="public_channels.png")
        else:
            pub_file = None

        if map_type in ("private", "both"):
            priv_channels = await self._gather_channels(
                ctx.guild, guild_data.get("privc_category_name", "PRIVATE CHANNELS"), alive_role, alt_role
            )
            priv_count = len(priv_channels)
            priv_title = "PRIVATE CHANNEL MAP"
            priv_subtitle = f"{priv_count} Channels"
            priv_img = self._draw_map(priv_channels, priv_title, priv_subtitle, self._private_theme)
            priv_buf = io.BytesIO()
            priv_img.save(priv_buf, "PNG")
            priv_buf.seek(0)
            priv_file = discord.File(fp=priv_buf, filename="private_channels.png")
        else:
            priv_file = None

        if map_type == "both":
            files = [f for f in [pub_file, priv_file] if f]
            if len(files) == 2:
                await ctx.send(files=files)
            elif len(files) == 1:
                await ctx.send(file=files[0])
            else:
                await ctx.send("No channels found in either category.")
        elif map_type == "public" and pub_file:
            await ctx.send(file=pub_file)
        elif map_type == "private" and priv_file:
            await ctx.send(file=priv_file)
        else:
            await ctx.send("No channels found in that category.")

    @commands.command(name="channels")
    async def cmd_channels(self, ctx):
        await ctx.send("⏳ Generating channel maps...")
        await self._build_and_send(ctx, "both")

    @commands.command(name="publicmap")
    async def cmd_publicmap(self, ctx):
        await ctx.send("⏳ Generating public channel map...")
        await self._build_and_send(ctx, "public")

    @commands.command(name="privatemap")
    async def cmd_privatemap(self, ctx):
        await ctx.send("⏳ Generating private channel map...")
        await self._build_and_send(ctx, "private")

    # ── Auto-update listeners ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        guild_data = load_guild_data(channel.guild.id)
        if not guild_data:
            return
        cat_names = [
            guild_data.get("publc_category_name", "PUBLIC CHANNELS"),
            guild_data.get("privc_category_name", "PRIVATE CHANNELS"),
        ]
        if channel.category and channel.category.name in cat_names:
            pass  # Maps are generated on-demand — no persistent message to edit

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild_data = load_guild_data(channel.guild.id)
        if not guild_data:
            return
        cat_names = [
            guild_data.get("publc_category_name", "PUBLIC CHANNELS"),
            guild_data.get("privc_category_name", "PRIVATE CHANNELS"),
        ]
        if channel.category and channel.category.name in cat_names:
            pass


async def setup(bot):
    await bot.add_cog(ChannelMap(bot))
# [1] ------------------------------------------------------------------------------
