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
            else:
                houses[ch.name] = {"channel": ch, "name": ch.name, "status": "empty", "occupants": [], "is_special": True}
                
        # Include destroyed houses up to max_num
        for i in range(1, max_num + 1):
            if i not in houses:
                houses[i] = {"name": f"House {i}", "status": "destroyed", "occupants": []}
                
        # Check occupants and owners
        alive_role = discord.utils.get(guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(guild.roles, name=guild_data.get("sponsor_role_name"))
        alt_role = discord.utils.get(guild.roles, name=guild_data.get("alt_role_name"))
        
        member_homes = guild_data.get("member_homes", {})
        
        # Initialize storage
        for h_data in houses.values():
            h_data["owners"] = []
            h_data["residents"] = []

        # 1. Gather Owners from member_homes
        for member_id, ch_id in member_homes.items():
            member = guild.get_member(int(member_id))
            if member and sponsor_role in member.roles:
                for num, h_data in houses.items():
                    if h_data.get("channel") and h_data["channel"].id == int(ch_id):
                        avatar_bytes = None
                        if getattr(self, 'SHOW_AVATARS', True):
                            try:
                                avatar_bytes = await member.display_avatar.replace(size=64).read()
                            except Exception: pass
                        
                        h_data["owners"].append({
                            "id": member.id,
                            "name": member.display_name,
                            "avatar": avatar_bytes,
                            "role_type": "owner"
                        })
                        h_data["status"] = "occupied"
                        break

        # 2. Gather Residents from channel members (authoritative)
        for num, h_data in houses.items():
            ch = h_data.get("channel")
            if not ch or h_data["status"] == "destroyed":
                continue
                
            for member in ch.members:
                if member.bot: continue
                
                is_alive = alive_role in member.roles if alive_role else False
                is_sponsor = sponsor_role in member.roles if sponsor_role else False
                is_alt = alt_role in member.roles if alt_role else False
                
                if is_alive or is_sponsor or is_alt:
                    avatar_bytes = None
                    if getattr(self, 'SHOW_AVATARS', True):
                        try:
                            avatar_bytes = await member.display_avatar.replace(size=64).read()
                        except Exception: pass
                    
                    role_type = "player" if is_alive else ("owner" if is_sponsor else "alt")
                    
                    h_data["residents"].append({
                        "id": member.id,
                        "name": member.display_name,
                        "avatar": avatar_bytes,
                        "role_type": role_type
                    })
                    h_data["status"] = "occupied"

                        
        # Now draw the image
        image = self.draw_estate_map(houses)
        
        # Save to bytes
        with io.BytesIO() as image_binary:
            image.save(image_binary, 'PNG')
            image_binary.seek(0)
            file = discord.File(fp=image_binary, filename='estate_map.png')
            await msg.edit(content="", attachments=[file])

    def draw_estate_map(self, houses):
        house_nums = sorted([k for k in houses.keys() if isinstance(k, int)])
        special_names = sorted([k for k in houses.keys() if isinstance(k, str)])
        all_keys = house_nums + special_names
        
        count = len(all_keys)
        if count == 0:
            return Image.new('RGB', (800, 600), color=(44, 47, 51))
            
        house_size = 70
        padding_x = 220
        padding_y = 200
        
        cols = math.ceil(math.sqrt(count * 1.5))
        if cols < 3: cols = 3
        rows = math.ceil(count / cols)
        
        row_heights = [0] * rows
        
        for i, num in enumerate(all_keys):
            r = i // cols
            owners_count = len(houses[num].get("owners", []))
            residents_count = len(houses[num].get("residents", []))
            # Space for owners + divider + residents
            divider_height = 20 if (owners_count > 0 and residents_count > 0) else 0
            total_lines = owners_count + residents_count
            needed_height = house_size + 40 + (total_lines * 45) + divider_height + 80
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
                    num = all_keys[idx]
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
                    row_positions.append(positions[all_keys[idx]])
            if len(row_positions) > 1:
                draw.line(row_positions, fill=(0, 0, 0, 150), width=15)
        
        bboxes = []
        for num in all_keys:
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
        
        is_special = isinstance(num, str)
        
        if is_special:
            if status == "destroyed":
                draw.polygon([base_bl, (cx - 15, cy), (cx, cy + 10), (cx + 20, cy - 5), base_br], fill=(70, 70, 70, 255))
                draw.line([(cx - 15, cy), (cx + 5, cy + 5), (cx - 5, cy + 15)], fill=(40, 40, 40, 255), width=3)
                ruin_text = "RUINS"
                try:
                    tw = draw.textbbox((0, 0), ruin_text, font=small_font)[2] - draw.textbbox((0, 0), ruin_text, font=small_font)[0]
                except AttributeError:
                    tw = draw.textsize(ruin_text, font=small_font)[0]
                draw.text((cx - tw/2, cy), ruin_text, fill=(200, 50, 50), font=small_font)
            else:
                color = (72, 61, 139, 255) if status == "occupied" else (55, 50, 80, 255)
                roof_color = (218, 165, 32, 255) if status == "occupied" else (110, 85, 15, 255)
                
                draw.rectangle([cx - half, cy - half + 30, cx + half, cy + half - 15], fill=color)
                draw.polygon([(cx, cy - half - 5), (cx - half - 10, cy - half + 30), (cx + half + 10, cy - half + 30)], fill=roof_color)
                
                door_w = 20
                door_h = 25
                draw.rectangle([(cx - door_w/2, cy + half - 15 - door_h), (cx + door_w/2, cy + half - 15)], fill=(40, 20, 5, 255) if status == "occupied" else (20, 20, 20, 255))
                
                win_color = (255, 215, 0, 255) if status == "occupied" else (40, 40, 40, 255)
                draw.rectangle([cx - 25, cy - 5, cx - 15, cy + 15], fill=win_color)
                draw.rectangle([cx + 15, cy - 5, cx + 25, cy + 15], fill=win_color)
        else:
            if status == "destroyed":
                draw.polygon([base_bl, (cx - 15, cy), (cx, cy + 10), (cx + 20, cy - 5), base_br], fill=(70, 70, 70, 255))
                draw.line([(cx - 15, cy), (cx + 5, cy + 5), (cx - 5, cy + 15)], fill=(40, 40, 40, 255), width=3)
                
                ruin_text = "RUINS"
                try:
                    tw = draw.textbbox((0, 0), ruin_text, font=small_font)[2] - draw.textbbox((0, 0), ruin_text, font=small_font)[0]
                except AttributeError:
                    tw = draw.textsize(ruin_text, font=small_font)[0]
                draw.text((cx - tw/2, cy), ruin_text, fill=(200, 50, 50), font=small_font)
            else:
                color = (139, 69, 19, 255) if status == "occupied" else (80, 80, 80, 255)
                roof_color = (178, 34, 34, 255) if status == "occupied" else (60, 60, 60, 255)
                
                draw.rectangle([base_tl, base_br], fill=color)
                draw.polygon([roof_top, roof_left, roof_right], fill=roof_color)
                
                door_w = 15
                door_h = 20
                draw.rectangle([(cx - door_w/2, base_br[1] - door_h), (cx + door_w/2, base_br[1])], fill=(60, 30, 0, 255) if status == "occupied" else (40, 40, 40, 255))
                
                win_color = (255, 215, 0, 255) if status == "occupied" else (40, 40, 40, 255)
                draw.rectangle([cx - 25, cy + 5, cx - 15, cy + 15], fill=win_color)
                draw.rectangle([cx + 15, cy + 5, cx + 25, cy + 15], fill=win_color)
            
        owners = data.get("owners", [])
        residents = data.get("residents", [])
        
        # Compact Labeling
        if is_special:
            clean_name = data["name"].replace("-", " ").title()
            label = f"🏛️ {clean_name}"
        else:
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
        
        # Occupancy Badge (Residents count)
        if residents:
            badge = f"● {len(residents)}"
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
            # 1. Prepare all lines for the unified block
            lines = []
            
            # Add Owners
            for occ in owners:
                name = occ["name"]
                if len(name) > 15: name = name[:12] + "..."
                disp = f"♛ {name}" if self.OWNER_INDICATOR_MODE == "crown" else name
                lines.append({
                    "text": disp,
                    "color": (255, 215, 0),
                    "font": names_font,
                    "avatar": occ.get("avatar"),
                    "is_owner": True
                })
            
            # Add Divider if both exist
            if owners and residents:
                lines.append({"type": "divider"})
            
            # Add Residents
            owner_ids = {o["id"] for o in owners}
            def res_priority(res):
                # Owners first in resident list
                if res["id"] in owner_ids: return 0
                if res["role_type"] == "player": return 1
                return 2
                
            sorted_residents = sorted(residents, key=res_priority)
            for occ in sorted_residents:
                name = occ["name"]
                if len(name) > 15: name = name[:12] + "..."
                c = (152, 251, 152) if occ.get("role_type") == "player" else (180, 180, 180)
                lines.append({
                    "text": name,
                    "color": c,
                    "font": names_font,
                    "avatar": occ.get("avatar"),
                    "is_owner": False
                })
                
            # 2. Calculate Total Height and Max Width of the block
            total_h = 0
            max_w = 0
            line_details = []
            avatar_size = 24
            
            for line in lines:
                if line.get("type") == "divider":
                    line_h = 20
                    total_h += line_h
                    line_details.append({"h": line_h})
                else:
                    try:
                        bbox = draw.textbbox((0, 0), line["text"], font=line["font"])
                        tw = bbox[2] - bbox[0]
                        th = bbox[3] - bbox[1]
                    except AttributeError:
                        tw, th = draw.textsize(line["text"], font=line["font"])
                        
                    full_w = tw + (avatar_size + 5 if line.get("avatar") else 0)
                    max_w = max(max_w, full_w)
                    line_h = th + 10
                    total_h += line_h
                    line_details.append({"h": line_h, "w": full_w, "tw": tw, "th": th})
            
            # 3. Find non-colliding y_off for the UNIFIED BLOCK
            y_off = cy + half + 10
            while True:
                # Padding around the block for better readability
                block_bbox = (cx - max_w/2 - 10, y_off, cx + max_w/2 + 10, y_off + total_h)
                if self.check_collision(block_bbox, bboxes):
                    y_off += 5
                else:
                    bboxes.append(block_bbox)
                    break
            
            # 4. Render the block
            current_y = y_off
            for i, line in enumerate(lines):
                detail = line_details[i]
                if line.get("type") == "divider":
                    # Faint separator line
                    line_y = current_y + 10
                    draw.line([(cx - max_w/2, line_y), (cx + max_w/2, line_y)], fill=(255, 255, 255, 60), width=2)
                    current_y += detail["h"]
                else:
                    tx = cx - detail["w"]/2 + (avatar_size + 5 if line.get("avatar") else 0)
                    
                    # Avatar
                    if line.get("avatar") and getattr(self, 'SHOW_AVATARS', True):
                        try:
                            av_img = Image.open(io.BytesIO(line["avatar"])).convert("RGBA")
                            av_img = av_img.resize((avatar_size, avatar_size))
                            mask = Image.new("L", (avatar_size, avatar_size), 0)
                            m_draw = ImageDraw.Draw(mask)
                            m_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
                            av_img.putalpha(mask)
                            img.paste(av_img, (int(tx - avatar_size - 5), int(current_y + detail["th"]/2 - avatar_size/2)), av_img)
                        except Exception: pass
                        
                    # Text with shadow/stroke
                    stroke_w = 3 if line.get("is_owner") else 2
                    for sx in [-stroke_w, stroke_w]:
                        for sy in [-stroke_w, stroke_w]:
                            draw.text((tx+sx, current_y+sy), line["text"], font=line["font"], fill=(0,0,0))
                    draw.text((tx, current_y), line["text"], font=line["font"], fill=line["color"])
                    current_y += detail["h"]

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
