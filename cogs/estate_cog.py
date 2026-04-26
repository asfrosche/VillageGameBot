import discord
from discord.ext import commands
import os
import re
import io
import math
from PIL import Image, ImageDraw, ImageFont
from cogs.data_utils import load_guild_data, save_guild_data

class Estate(commands.Cog):
    SHOW_AVATARS = True
    OWNER_INDICATOR_MODE = "crown"

    def __init__(self, bot):
        self.bot = bot

    def get_text_bbox(self, draw, text, font, x, y):
        try:
            bbox = draw.textbbox((x, y), text, font=font)
        except AttributeError:
            tw, th = draw.textsize(text, font=font)
            bbox = (x, y, x + tw, y + th)
        return bbox

    def check_collision(self, bbox, bboxes):
        x1, y1, x2, y2 = bbox
        for (bx1, by1, bx2, by2) in bboxes:
            if not (x2 < bx1 or x1 > bx2 or y2 < by1 or y1 > by2):
                return True
        return False

    def extract_number(self, name):
        match = re.search(r'\d+', name)
        return int(match.group()) if match else None

    @commands.command()
    async def estate(self, ctx, type: str = None, channel: discord.TextChannel = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
            
        if type and type.lower() == 'init':
            if not channel:
                return await ctx.send("Please specify a channel to initialize the estate map.")
            
            guild_data = load_guild_data(ctx.guild.id)
            if not guild_data:
                return await ctx.send("Guild data not loaded.")
                
            houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name", "Houses"))
            if not houses_category:
                return await ctx.send("Houses category not found.")
                
            msg = await channel.send("Generating estate map...")
            
            guild_data["estate_directory"] = {
                "channel_id": channel.id,
                "message_id": msg.id,
                "houses_category_id": houses_category.id
            }
            save_guild_data(ctx.guild.id, guild_data)
            
            await self.update_estate_map(ctx.guild)
        else:
            await ctx.send("Usage: `.estate init #channel`")

    async def update_estate_map(self, guild):
        guild_data = load_guild_data(guild.id)
        if not guild_data or "estate_directory" not in guild_data:
            return
            
        estate_dir = guild_data["estate_directory"]
        channel_id = estate_dir.get("channel_id")
        message_id = estate_dir.get("message_id")
        category_id = estate_dir.get("houses_category_id")
        
        channel = guild.get_channel(channel_id)
        if not channel:
            return
            
        category = guild.get_channel(category_id)
        if not category:
            return
            
        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            # Rebuild behavior: recreate message
            msg = await channel.send("Rebuilding estate map...")
            estate_dir["message_id"] = msg.id
            save_guild_data(guild.id, guild_data)
            
        # Analyze houses
        existing_channels = category.text_channels
        houses = {}
        max_num = 0
        for ch in existing_channels:
            num = self.extract_number(ch.name)
            if num is not None:
                houses[num] = {"channel": ch, "name": ch.name, "status": "empty", "occupants": []}
                max_num = max(max_num, num)
                
        # Include destroyed houses up to max_num
        for i in range(1, max_num + 1):
            if i not in houses:
                houses[i] = {"name": f"House {i}", "status": "destroyed", "occupants": []}
                
        # Check occupants
        alive_role = discord.utils.get(guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(guild.roles, name=guild_data.get("sponsor_role_name"))
        alt_role = discord.utils.get(guild.roles, name=guild_data.get("alt_role_name"))
        
        member_homes = guild_data.get("member_homes", {})
        for member_id, ch_id in member_homes.items():
            member = guild.get_member(int(member_id))
            if member:
                is_alive = alive_role in member.roles if alive_role else False
                is_sponsor = sponsor_role in member.roles if sponsor_role else False
                is_alt = alt_role in member.roles if alt_role else False
                
                if is_alive or is_sponsor or is_alt:
                    # Find which house this channel is
                    for num, h_data in houses.items():
                        if h_data.get("channel") and h_data["channel"].id == int(ch_id):
                            avatar_bytes = None
                            if getattr(self, 'SHOW_AVATARS', True):
                                try:
                                    avatar_bytes = await member.display_avatar.replace(size=64).read()
                                except Exception:
                                    pass
                            
                            # Differentiate between owners, players, and alts
                            if is_sponsor:
                                role_type = "owner"
                            elif is_alive:
                                role_type = "player"
                            else:
                                role_type = "alt"
                            
                            h_data["occupants"].append({
                                "name": member.display_name,
                                "avatar": avatar_bytes,
                                "role_type": role_type
                            })
                            h_data["status"] = "occupied"
                            break
                        
        # Now draw the image
        image = self.draw_estate_map(houses)
        
        # Save to bytes
        with io.BytesIO() as image_binary:
            image.save(image_binary, 'PNG')
            image_binary.seek(0)
            file = discord.File(fp=image_binary, filename='estate_map.png')
            await msg.edit(content="", attachments=[file])

    def draw_estate_map(self, houses):
        house_nums = sorted(houses.keys())
        count = len(house_nums)
        if count == 0:
            return Image.new('RGB', (800, 600), color=(44, 47, 51))
            
        house_size = 70
        padding_x = 220
        padding_y = 200
        
        cols = math.ceil(math.sqrt(count * 1.5))
        if cols < 3: cols = 3
        rows = math.ceil(count / cols)
        
        row_heights = [0] * rows
        
        for i, num in enumerate(house_nums):
            r = i // cols
            occupants_count = len(houses[num].get("occupants", []))
            needed_height = house_size + 40 + (occupants_count * 45) + 60
            needed_height = max(needed_height, padding_y)
            if needed_height > row_heights[r]:
                row_heights[r] = needed_height
                
        width = cols * (house_size + padding_x) + padding_x
        total_height = 200 + padding_y # Title area
        current_y = 200 + padding_y
        
        positions = {}
        for r in range(rows):
            for c in range(cols):
                idx = r * cols + c
                if idx < count:
                    num = house_nums[idx]
                    stagger_y = (c % 2) * 50
                    x = padding_x + c * (house_size + padding_x) + house_size / 2
                    y = current_y + house_size / 2 + stagger_y
                    positions[num] = (x, y)
            current_y += row_heights[r]
            
        height = current_y + padding_y
            
        img = Image.new('RGBA', (int(width), int(height)), color=(44, 47, 51, 255))
        
        # Load Background Wallpaper
        try:
            bg_path = os.path.join(os.path.dirname(__file__), "..", "assets", "contour_wall.jpg")
            if os.path.exists(bg_path):
                bg = Image.open(bg_path).convert("RGBA")
                bg_w, bg_h = bg.size
                canvas_ratio = width / height
                bg_ratio = bg_w / bg_h
                if canvas_ratio > bg_ratio:
                    new_h = int(bg_w / canvas_ratio)
                    bg = bg.crop((0, (bg_h - new_h) // 2, bg_w, (bg_h + new_h) // 2))
                else:
                    new_w = int(bg_h * canvas_ratio)
                    bg = bg.crop(((bg_w - new_w) // 2, 0, (bg_w + new_w) // 2, bg_h))
                bg = bg.resize((int(width), int(height)), Image.LANCZOS)
                img.paste(bg, (0, 0))
        except Exception:
            pass
            
        draw = ImageDraw.Draw(img, 'RGBA')
        
        font_choices = ["arialbd.ttf", "arial.ttf", "tahoma.ttf", "segoeui.ttf"]
        for f in font_choices:
            try:
                title_font = ImageFont.truetype(f, 50)
                subtitle_font = ImageFont.truetype(f, 26)
                label_font = ImageFont.truetype(f, 26)
                names_font = ImageFont.truetype(f, 32)
                small_font = ImageFont.truetype(f, 20)
                break
            except IOError:
                continue
        else:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            label_font = ImageFont.load_default()
            names_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
            
        # Draw Title and Subtitle Metadata
        num_houses = len(houses)
        num_occupied = sum(1 for h in houses.values() if h["status"] == "occupied")
        num_ruined = sum(1 for h in houses.values() if h["status"] == "destroyed")
        
        title = "Estate Map"
        subtitle = f"{num_houses} Houses | {num_occupied} Occupied | {num_ruined} Ruined"
        
        try:
            tw = draw.textbbox((0, 0), title, font=title_font)[2] - draw.textbbox((0, 0), title, font=title_font)[0]
            sw = draw.textbbox((0, 0), subtitle, font=subtitle_font)[2] - draw.textbbox((0, 0), subtitle, font=subtitle_font)[0]
        except AttributeError:
            tw = draw.textsize(title, font=title_font)[0]
            sw = draw.textsize(subtitle, font=subtitle_font)[0]
            
        # Draw Title with subtle shadow for contrast against wallpaper
        draw.text(((width - tw) / 2 + 2, 42), title, font=title_font, fill=(0, 0, 0))
        draw.text(((width - tw) / 2, 40), title, font=title_font, fill=(255, 215, 0))
        
        draw.text(((width - sw) / 2 + 1, 101), subtitle, font=subtitle_font, fill=(0, 0, 0))
        draw.text(((width - sw) / 2, 100), subtitle, font=subtitle_font, fill=(220, 220, 220))
        
        # Draw Subtle Neighborhood Roads (Semi-transparent black)
        for r in range(rows):
            row_positions = []
            for c in range(cols):
                idx = r * cols + c
                if idx < count:
                    row_positions.append(positions[house_nums[idx]])
            if len(row_positions) > 1:
                draw.line(row_positions, fill=(0, 0, 0, 150), width=15)
        
        bboxes = []
        for num in house_nums:
            x, y = positions[num]
            h_data = houses[num]
            self.draw_house(draw, img, x, y, house_size, h_data, num, label_font, names_font, small_font, bboxes)
            
        return img.convert('RGB')

    def draw_house(self, draw, img, cx, cy, size, data, num, label_font, names_font, small_font, bboxes):
        status = data["status"]
        half = size / 2
        
        # Subtle Territory Halo (Semi-transparent black)
        halo_radius = size * 1.3
        draw.ellipse([cx - halo_radius, cy - half - halo_radius*0.8, cx + halo_radius, cy + half + halo_radius*0.3], fill=(0, 0, 0, 150))
        
        roof_top = (cx, cy - half + 10)
        roof_left = (cx - half, cy - half + 35)
        roof_right = (cx + half, cy - half + 35)
        base_tl = (cx - half + 10, cy - half + 35)
        base_tr = (cx + half - 10, cy - half + 35)
        base_bl = (cx - half + 10, cy + half - 15)
        base_br = (cx + half - 10, cy + half - 15)
        
        bboxes.append((cx - half, cy - half, cx + half, cy + half))
        
        if status == "destroyed":
            draw.polygon([base_bl, (cx - 15, cy), (cx, cy + 10), (cx + 20, cy - 5), base_br], fill=(70, 70, 70))
            draw.line([(cx - 15, cy), (cx + 5, cy + 5), (cx - 5, cy + 15)], fill=(40, 40, 40), width=3)
            
            ruin_text = "RUINS"
            try:
                tw = draw.textbbox((0, 0), ruin_text, font=small_font)[2] - draw.textbbox((0, 0), ruin_text, font=small_font)[0]
            except AttributeError:
                tw = draw.textsize(ruin_text, font=small_font)[0]
            draw.text((cx - tw/2, cy), ruin_text, fill=(200, 50, 50), font=small_font)
        else:
            color = (139, 69, 19) if status == "occupied" else (80, 80, 80)
            roof_color = (178, 34, 34) if status == "occupied" else (60, 60, 60)
            
            draw.rectangle([base_tl, base_br], fill=color)
            draw.polygon([roof_top, roof_left, roof_right], fill=roof_color)
            
            door_w = 15
            door_h = 20
            draw.rectangle([(cx - door_w/2, base_br[1] - door_h), (cx + door_w/2, base_br[1])], fill=(60, 30, 0) if status == "occupied" else (40, 40, 40))
            
            # Lit / Muted Windows
            win_color = (255, 215, 0) if status == "occupied" else (40, 40, 40)
            draw.rectangle([cx - 25, cy + 5, cx - 15, cy + 15], fill=win_color)
            draw.rectangle([cx + 15, cy + 5, cx + 25, cy + 15], fill=win_color)
            
        occupants = data.get("occupants", [])
        
        # Compact Labeling
        label = f"🏠{num}"
        try:
            tw = draw.textbbox((0, 0), label, font=label_font)[2] - draw.textbbox((0, 0), label, font=label_font)[0]
        except AttributeError:
            tw = draw.textsize(label, font=label_font)[0]
            
        label_x = cx - tw/2
        label_y = cy - half - 30
        l_bbox = self.get_text_bbox(draw, label, label_font, label_x, label_y)
        draw.rectangle([l_bbox[0]-4, l_bbox[1]-4, l_bbox[2]+4, l_bbox[3]+4], fill=(30, 30, 30))
        draw.text((label_x, label_y), label, font=label_font, fill=(255, 255, 255))
        bboxes.append(l_bbox)
        
        # Occupancy Badge
        if occupants:
            badge = f"● {len(occupants)}"
            try:
                bw = draw.textbbox((0, 0), badge, font=small_font)[2] - draw.textbbox((0, 0), badge, font=small_font)[0]
            except AttributeError:
                bw = draw.textsize(badge, font=small_font)[0]
                
            badge_x = l_bbox[2] + 10
            badge_y = label_y + 2
            b_bbox = self.get_text_bbox(draw, badge, small_font, badge_x, badge_y)
            draw.rectangle([b_bbox[0]-4, b_bbox[1]-2, b_bbox[2]+4, b_bbox[3]+2], fill=(200, 50, 50), outline=(255, 255, 255))
            draw.text((badge_x, badge_y), badge, font=small_font, fill=(255, 255, 255))
            bboxes.append(b_bbox)
            
        if status == "occupied":
            y_off = cy + half + 5
            owners = [o for o in occupants if o.get("role_type") == "owner"]
            others = [o for o in occupants if o.get("role_type") != "owner"]
            is_crowded = len(occupants) >= 5
            
            def render_text_line(text, color, font, y_pos, has_avatar=False, avatar_bytes=None, is_bold_crown=False):
                try:
                    _tw = draw.textbbox((0, 0), text, font=font)[2] - draw.textbbox((0, 0), text, font=font)[0]
                    _th = draw.textbbox((0, 0), text, font=font)[3] - draw.textbbox((0, 0), text, font=font)[1]
                except AttributeError:
                    _tw, _th = draw.textsize(text, font=font)
                    
                avatar_size = 24
                total_w = _tw + (avatar_size + 5 if has_avatar else 0)
                tx = cx - total_w/2 + (avatar_size + 5 if has_avatar else 0)
                
                while True:
                    t_bbox = self.get_text_bbox(draw, text, font, tx, y_pos)
                    if has_avatar:
                        t_bbox = (t_bbox[0] - avatar_size - 5, t_bbox[1], t_bbox[2], max(t_bbox[3], y_pos + avatar_size))
                    if self.check_collision(t_bbox, bboxes):
                        y_pos += 5
                    else:
                        bboxes.append(t_bbox)
                        break
                        
                if has_avatar and avatar_bytes:
                    try:
                        av_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                        av_img = av_img.resize((avatar_size, avatar_size))
                        mask = Image.new("L", (avatar_size, avatar_size), 0)
                        m_draw = ImageDraw.Draw(mask)
                        m_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
                        av_img.putalpha(mask)
                        img.paste(av_img, (int(tx - avatar_size - 5), int(y_pos + _th/2 - avatar_size/2)), av_img)
                    except Exception:
                        pass
                        
                stroke_width = 3 if is_bold_crown else 2
                for sx in [-stroke_width, stroke_width]:
                    for sy in [-stroke_width, stroke_width]:
                        draw.text((tx+sx, y_pos+sy), text, font=font, fill=(0,0,0))
                draw.text((tx, y_pos), text, font=font, fill=color)
                return y_pos + _th + 10

            def role_priority(occ):
                r = occ.get("role_type", "player")
                if r == "owner": return 0
                if r == "player": return 1
                return 2
                
            sorted_occupants = sorted(occupants, key=role_priority)
            
            for occ in sorted_occupants:
                name = occ["name"]
                if len(name) > 15: name = name[:12] + "..."
                role_type = occ.get("role_type", "player")
                is_owner = role_type == "owner"
                
                if is_owner and self.OWNER_INDICATOR_MODE == "crown":
                    disp = f"♛ {name}"
                    c = (255, 215, 0)
                else:
                    disp = name
                    c = (152, 251, 152) if role_type == "player" else (180, 180, 180)
                    
                has_av = getattr(self, 'SHOW_AVATARS', True) and occ.get("avatar") is not None
                y_off = render_text_line(disp, c, names_font, y_off, has_avatar=has_av, avatar_bytes=occ.get("avatar"), is_bold_crown=is_owner)
                    
        elif status == "empty":
            text = "(Empty)"
            try:
                tw = draw.textbbox((0, 0), text, font=small_font)[2] - draw.textbbox((0, 0), text, font=small_font)[0]
            except AttributeError:
                tw = draw.textsize(text, font=small_font)[0]
            y_off = cy + half + 5
            while True:
                t_bbox = self.get_text_bbox(draw, text, small_font, cx - tw/2, y_off)
                if self.check_collision(t_bbox, bboxes):
                    y_off += 5
                else:
                    bboxes.append(t_bbox)
                    break
            draw.text((cx - tw/2, y_off), text, font=small_font, fill=(169, 169, 169))

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        guild_data = load_guild_data(channel.guild.id)
        if not guild_data or "estate_directory" not in guild_data:
            return
        if channel.category and channel.category.id == guild_data["estate_directory"].get("houses_category_id"):
            await self.update_estate_map(channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild_data = load_guild_data(channel.guild.id)
        if not guild_data or "estate_directory" not in guild_data:
            return
        if channel.category_id == guild_data["estate_directory"].get("houses_category_id"):
            await self.update_estate_map(channel.guild)

async def setup(bot):
    await bot.add_cog(Estate(bot))
