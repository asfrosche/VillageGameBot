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
            img = Image.new('RGB', (800, 600), color=(44, 47, 51))
            return img
            
        house_size = 70  # Smaller house visual anchor
        padding_x = 220  # Expanded horizontal padding to prevent collision
        padding_y = 200  # Expanded vertical padding for multiline text
        
        if count <= 6:
            center_x, center_y = 600, 500
            radius = 350
            width, height = 1200, 1000
            positions = {}
            for i, num in enumerate(house_nums):
                angle = 2 * math.pi * i / count - math.pi / 2
                x = center_x + radius * math.cos(angle)
                y = center_y + radius * math.sin(angle)
                positions[num] = (x, y)
        else:
            # Dynamic Grid Layout for dense maps with adaptive row heights
            cols = math.ceil(math.sqrt(count * 1.5))
            if cols < 3: cols = 3
            rows = math.ceil(count / cols)
            
            row_heights = [0] * rows
            
            # Pre-calculate the maximum height needed for each row
            for i, num in enumerate(house_nums):
                r = i // cols
                occupants_count = len(houses[num].get("occupants", []))
                # Base space per house: house_size + text padding
                # Each occupant takes approx 45px vertically
                needed_height = house_size + 40 + (occupants_count * 45) + 60
                needed_height = max(needed_height, padding_y) # Ensure minimum padding
                
                if needed_height > row_heights[r]:
                    row_heights[r] = needed_height
                    
            width = cols * (house_size + padding_x) + padding_x
            
            total_height = 150 + padding_y # Start below title area
            current_y = 150 + padding_y
            
            positions = {}
            for r in range(rows):
                for c in range(cols):
                    idx = r * cols + c
                    if idx < count:
                        num = house_nums[idx]
                        stagger_y = (c % 2) * 50  # Cleaner staggered street feel
                        x = padding_x + c * (house_size + padding_x) + house_size / 2
                        y = current_y + house_size / 2 + stagger_y
                        positions[num] = (x, y)
                current_y += row_heights[r]
                
            height = current_y + padding_y
                
        img = Image.new('RGB', (int(width), int(height)), color=(44, 47, 51))
        draw = ImageDraw.Draw(img)
        
        font_choices = ["arialbd.ttf", "arial.ttf", "tahoma.ttf", "segoeui.ttf"]
        for f in font_choices:
            try:
                title_font = ImageFont.truetype(f, 60)
                label_font = ImageFont.truetype(f, 26)
                names_font = ImageFont.truetype(f, 32)
                break
            except IOError:
                continue
        else:
            title_font = ImageFont.load_default()
            label_font = ImageFont.load_default()
            names_font = ImageFont.load_default()
            
        title = "Village Estate Map"
        try:
            bbox = draw.textbbox((0, 0), title, font=title_font)
            tw = bbox[2] - bbox[0]
        except AttributeError:
            tw = draw.textsize(title, font=title_font)[0]
        draw.text(((width - tw) / 2, 40), title, font=title_font, fill=(255, 215, 0))
        
        bboxes = []
        
        for num in house_nums:
            x, y = positions[num]
            h_data = houses[num]
            self.draw_house(draw, img, x, y, house_size, h_data, label_font, names_font, bboxes)
            
        return img

    def draw_house(self, draw, img, cx, cy, size, data, label_font, names_font, bboxes):
        status = data["status"]
        half = size / 2
        
        roof_top = (cx, cy - half + 10)
        roof_left = (cx - half, cy - half + 35)
        roof_right = (cx + half, cy - half + 35)
        base_tl = (cx - half + 10, cy - half + 35)
        base_tr = (cx + half - 10, cy - half + 35)
        base_bl = (cx - half + 10, cy + half - 15)
        base_br = (cx + half - 10, cy + half - 15)
        
        # Protect house area
        bboxes.append((cx - half, cy - half, cx + half, cy + half))
        
        if status == "destroyed":
            draw.polygon([base_bl, (cx - 15, cy), (cx, cy + 10), (cx + 20, cy - 5), base_br], fill=(80, 80, 80))
            draw.text((cx - 25, cy), "RUINS", fill=(200, 50, 50), font=label_font)
        else:
            color = (139, 69, 19) if status == "occupied" else (100, 100, 100)
            roof_color = (178, 34, 34) if status == "occupied" else (70, 70, 70)
            
            draw.rectangle([base_tl, base_br], fill=color)
            draw.polygon([roof_top, roof_left, roof_right], fill=roof_color)
            
            door_w = 15
            door_h = 20
            draw.rectangle([(cx - door_w/2, base_br[1] - door_h), (cx + door_w/2, base_br[1])], fill=(60, 30, 0))
            
        occupants = data.get("occupants", [])
        label = data["name"].capitalize()
        if occupants:
            label += f" [{len(occupants)}]"
            
        try:
            tw = draw.textbbox((0, 0), label, font=label_font)[2] - draw.textbbox((0, 0), label, font=label_font)[0]
        except AttributeError:
            tw = draw.textsize(label, font=label_font)[0]
            
        # Draw label with background to ensure contrast
        label_x = cx - tw/2
        label_y = cy - half - 25
        l_bbox = self.get_text_bbox(draw, label, label_font, label_x, label_y)
        draw.rectangle([l_bbox[0]-2, l_bbox[1]-2, l_bbox[2]+2, l_bbox[3]+2], fill=(30, 30, 30))
        draw.text((label_x, label_y), label, font=label_font, fill=(255, 255, 255))
        bboxes.append(l_bbox)
        
        if status == "occupied":
            y_off = cy + half + 5
            for i, occ in enumerate(occupants):
                name = occ["name"]
                if len(name) > 15:
                    name = name[:12] + "..."
                
                role_type = occ.get("role_type", "player") # Use dynamic flag, fallback to player if missing
                
                if role_type == "owner" and getattr(self, 'OWNER_INDICATOR_MODE', '') == "crown":
                    display_text = f"♛ {name}"
                    text_color = (255, 215, 0)
                elif role_type == "player":
                    display_text = name
                    text_color = (152, 251, 152) # Light Green
                else:
                    display_text = name
                    text_color = (180, 180, 180) # Subtle silver/grey
                    
                try:
                    tw = draw.textbbox((0, 0), display_text, font=names_font)[2] - draw.textbbox((0, 0), display_text, font=names_font)[0]
                    th = draw.textbbox((0, 0), display_text, font=names_font)[3] - draw.textbbox((0, 0), display_text, font=names_font)[1]
                except AttributeError:
                    tw, th = draw.textsize(display_text, font=names_font)
                    
                avatar_size = 24
                has_avatar = getattr(self, 'SHOW_AVATARS', True) and occ.get("avatar") is not None
                total_w = tw + (avatar_size + 5 if has_avatar else 0)
                
                text_x = cx - total_w/2 + (avatar_size + 5 if has_avatar else 0)
                
                # Collision avoidance
                while True:
                    t_bbox = self.get_text_bbox(draw, display_text, names_font, text_x, y_off)
                    if has_avatar:
                        t_bbox = (t_bbox[0] - avatar_size - 5, t_bbox[1], t_bbox[2], max(t_bbox[3], y_off + avatar_size))
                    if self.check_collision(t_bbox, bboxes):
                        y_off += 5
                    else:
                        bboxes.append(t_bbox)
                        break
                        
                # Draw Avatar
                if has_avatar:
                    try:
                        av_img = Image.open(io.BytesIO(occ["avatar"])).convert("RGBA")
                        av_img = av_img.resize((avatar_size, avatar_size))
                        mask = Image.new("L", (avatar_size, avatar_size), 0)
                        m_draw = ImageDraw.Draw(mask)
                        m_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
                        av_img.putalpha(mask)
                        img.paste(av_img, (int(t_bbox[0]), int(y_off + th/2 - avatar_size/2)), av_img)
                    except Exception as e:
                        pass
                
                # Text Stroke Outline for Contrast
                draw.text((text_x-2, y_off-2), display_text, font=names_font, fill=(0,0,0))
                draw.text((text_x+2, y_off-2), display_text, font=names_font, fill=(0,0,0))
                draw.text((text_x-2, y_off+2), display_text, font=names_font, fill=(0,0,0))
                draw.text((text_x+2, y_off+2), display_text, font=names_font, fill=(0,0,0))
                
                draw.text((text_x, y_off), display_text, font=names_font, fill=text_color)
                y_off += th + 10
                
        elif status == "empty":
            text = "(Empty)"
            try:
                tw = draw.textbbox((0, 0), text, font=names_font)[2] - draw.textbbox((0, 0), text, font=names_font)[0]
            except AttributeError:
                tw = draw.textsize(text, font=names_font)[0]
                
            y_off = cy + half + 5
            while True:
                t_bbox = self.get_text_bbox(draw, text, names_font, cx - tw/2, y_off)
                if self.check_collision(t_bbox, bboxes):
                    y_off += 5
                else:
                    bboxes.append(t_bbox)
                    break
                    
            draw.text((cx - tw/2, y_off), text, font=names_font, fill=(169, 169, 169))

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
