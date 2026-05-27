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
    async def estatehelp(self, ctx):
        """Displays help for all Estate and Neighborhood functions."""
        embed = discord.Embed(
            title="🏡 Estate & Neighborhood Help",
            description="Manage the neighborhood map and house assignments.",
            color=0x2ecc71
        )
        
        embed.add_field(
            name="📍 Map Management",
            value=(
                "`.estate init #channel` - Initialize the dynamic map in a dedicated channel.\n"
                "`.estate` - Manually force an update of the existing map."
            ),
            inline=False
        )
        
        embed.add_field(
            name="🏠 House Actions",
            value=(
                "`.home @user #house` - Assign a user as the primary owner of a house.\n"
                "`.destroy [#house]` - Marks a house as **Ruins** on the map (Admin only).\n"
                "`.decay [#house]` - Removes residents and marks as inaccessible (Admin only)."
            ),
            inline=False
        )
        
        embed.add_field(
            name="ℹ️ Automatic Features",
            value=(
                "• **Auto-Update**: The map rebuilds whenever a house channel is created or deleted.\n"
                "• **Serpentine Layout**: Houses are automatically arranged in a snake pattern.\n"
                "• **Role Colors**: Owners (Yellow ♛), Residents (Green), Alts (Gray)."
            ),
            inline=False
        )
        
        embed.set_footer(text="Village Estate System | Created by Antigravity")
        await ctx.send(embed=embed)

    @commands.command()
    async def estate(self, ctx, type: str = None, channel: discord.TextChannel = None):
        if not (ctx.author.guild_permissions.administrator or ctx.author.id == 321117543378976771):
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
        elif type and type.lower() == 'help':
            await ctx.invoke(self.estatehelp)
        elif type is None or (type and type.lower() in ('update', 'refresh')):
            guild_data = load_guild_data(ctx.guild.id)
            if not guild_data or "estate_directory" not in guild_data:
                return await ctx.send("❌ Estate map is not initialized yet. Use `.estate init #channel` to initialize.")
            
            progress_msg = await ctx.send("⏳ Updating the estate map...")
            try:
                await self.update_estate_map(ctx.guild)
                await progress_msg.edit(content="✅ Estate map updated successfully!")
            except Exception as e:
                await progress_msg.edit(content=f"❌ Failed to update estate map: {e}")
        else:
            await ctx.send("Usage: `.estate init #channel` or `.estate` to manually update, or `.estatehelp` for all commands.")

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
            # Owners are members with alive_role OR alt_role who are in member_homes.
            if member and (alive_role in member.roles or alt_role in member.roles):
                for num, h_data in houses.items():
                    if h_data.get("channel") and h_data["channel"].id == int(ch_id):
                        avatar_bytes = None
                        if getattr(self, 'SHOW_AVATARS', True):
                            try:
                                avatar_bytes = await member.display_avatar.replace(size=128).read()
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
                is_alt = alt_role in member.roles if alt_role else False
                
                if is_alive or is_alt:
                    avatar_bytes = None
                    if getattr(self, 'SHOW_AVATARS', True):
                        try:
                            avatar_bytes = await member.display_avatar.replace(size=128).read()
                        except Exception: pass
                    
                    role_type = "player" if is_alive else "alt"
                    
                    h_data["residents"].append({
                        "id": member.id,
                        "name": member.display_name,
                        "avatar": avatar_bytes,
                        "role_type": role_type
                    })
                    h_data["status"] = "occupied"

                        
        # Now split and draw the sections
        house_nums = sorted([k for k in houses.keys() if isinstance(k, int)])
        special_names = sorted([k for k in houses.keys() if isinstance(k, str)])
        all_keys = house_nums + special_names
        
        count = len(all_keys)
        
        # Split key count almost evenly for perfect visual balance
        half_count = math.ceil(count / 2)
        top_keys = all_keys[:half_count]
        bottom_keys = all_keys[half_count:]
        
        # Calculate dynamic columns/rows for top section
        top_count = len(top_keys)
        if top_count <= 4:
            top_cols = 2 if top_count >= 2 else top_count
        elif top_count <= 7:
            top_cols = 3
        elif top_count <= 10:
            top_cols = 4
        else:
            top_cols = 5
            
        # Calculate dynamic columns/rows for bottom section
        bottom_count = len(bottom_keys)
        if bottom_count <= 4:
            bottom_cols = 2 if bottom_count >= 2 else bottom_count
        elif bottom_count <= 7:
            bottom_cols = 3
        elif bottom_count <= 10:
            bottom_cols = 4
        else:
            bottom_cols = 5
            
        # Keep both wings visually aligned to the same column layout
        max_cols = max(1, max(top_cols, bottom_cols))
        top_rows = math.ceil(top_count / max_cols)
        bottom_rows = math.ceil(bottom_count / max_cols)
        
        house_size = 100
        padding_x = 200
        padding_y = 140
        
        if top_rows <= 1 or count == 0:
            # If only 1 row or no houses, render a single map
            image = self.draw_estate_section(houses, all_keys, all_keys, "Estate Map", f"{count} Houses", 0, top_rows, max_cols, house_size, padding_x, padding_y)
            with io.BytesIO() as image_binary:
                image.save(image_binary, 'PNG')
                image_binary.seek(0)
                file = discord.File(fp=image_binary, filename='estate_map.png')
                await msg.edit(content="", attachments=[file])
        else:
            top_occupied = sum(1 for k in top_keys if houses[k]["status"] == "occupied")
            top_destroyed = sum(1 for k in top_keys if houses[k]["status"] == "destroyed")
            bottom_occupied = sum(1 for k in bottom_keys if houses[k]["status"] == "occupied")
            bottom_destroyed = sum(1 for k in bottom_keys if houses[k]["status"] == "destroyed")
            
            top_subtitle = f"{len(top_keys)} Houses | {top_occupied} Occupied | {top_destroyed} Ruined"
            bottom_subtitle = f"{len(bottom_keys)} Houses | {bottom_occupied} Occupied | {bottom_destroyed} Ruined"
            
            img_top = self.draw_estate_section(houses, all_keys, top_keys, "Estate Map - North Wing", top_subtitle, 0, top_rows, max_cols, house_size, padding_x, padding_y)
            img_bottom = self.draw_estate_section(houses, all_keys, bottom_keys, "Estate Map - South Wing", bottom_subtitle, top_rows, bottom_rows, max_cols, house_size, padding_x, padding_y)
            
            # Save both sections to bytes and attach to message
            with io.BytesIO() as top_bin, io.BytesIO() as bottom_bin:
                img_top.save(top_bin, 'PNG')
                img_bottom.save(bottom_bin, 'PNG')
                top_bin.seek(0)
                bottom_bin.seek(0)
                
                file_top = discord.File(fp=top_bin, filename='estate_top.png')
                file_bottom = discord.File(fp=bottom_bin, filename='estate_bottom.png')
                
                await msg.edit(content="", attachments=[file_top, file_bottom])

    def draw_estate_section(self, houses, all_keys, keys_subset, title, subtitle, row_offset, section_rows, cols, house_size, padding_x, padding_y):
        count = len(keys_subset)
        if count == 0:
            return Image.new('RGB', (800, 600), color=(44, 47, 51))
            
        # Helper to generate all valid combinations of rows adding up to total count
        def get_partitions(n, r, max_val):
            if r == 1:
                return [[n]] if 1 <= n <= max_val else []
            res = []
            for val in range(1, max_val + 1):
                if n - val >= r - 1:
                    for sub in get_partitions(n - val, r - 1, max_val):
                        res.append([val] + sub)
            return res
            
        # Estimate the card height for each individual house
        def get_house_height(num):
            h_data = houses[num]
            if h_data["status"] != "occupied":
                return 70
            owners_count = len(h_data.get("owners", []))
            residents_count = len(h_data.get("residents", []))
            divider_height = 24 if (owners_count > 0 and residents_count > 0) else 0
            total_lines = owners_count + residents_count
            total_h = (total_lines * 60) + divider_height
            return 220 + total_h + 100
            
        # Estimate horizontal card panel width for each individual house
        def get_house_panel_width(num):
            h_data = houses[num]
            if h_data["status"] != "occupied":
                return 160
            owners_count = len(h_data.get("owners", []))
            residents_count = len(h_data.get("residents", []))
            max_w = 0
            avatar_size = 48
            for occ in h_data.get("owners", []) + h_data.get("residents", []):
                name = occ["name"]
                if len(name) > 10: name = name[:8]
                tw_line = len(name) * 22  # Fast character-width estimator
                full_w = tw_line + (avatar_size + 12 if (occ.get("avatar") and getattr(self, 'SHOW_AVATARS', True)) else 0)
                max_w = max(max_w, full_w)
                
            occupant_count = owners_count + residents_count
            if occupant_count <= 1:
                min_w = 200
            elif occupant_count == 2:
                min_w = 240
            else:
                min_w = 300
            return max(max_w + 40, min_w)
            
        # Calculate horizontal overlap penalty for a given partition scheme
        width = cols * (house_size + padding_x) + padding_x
        
        def calculate_overlap_penalty(p):
            penalty = 0
            current_idx = 0
            for local_r, r_size in enumerate(p):
                row_keys = keys_subset[current_idx : current_idx + r_size]
                n = len(row_keys)
                if n > 1:
                    xs = []
                    global_r = local_r + row_offset
                    for i in range(n):
                        if r_size == 1:
                            c_index = (cols - 1) // 2
                        else:
                            c_index = int(round(i * (cols - 1) / (r_size - 1)))
                        display_c = c_index if global_r % 2 == 0 else (cols - 1 - c_index)
                        x = padding_x + display_c * (house_size + padding_x) + house_size / 2
                        xs.append(x)
                        
                    xs_sorted = sorted(zip(xs, row_keys), key=lambda item: item[0])
                    for i in range(len(xs_sorted) - 1):
                        x_A, key_A = xs_sorted[i]
                        x_B, key_B = xs_sorted[i+1]
                        dist = x_B - x_A
                        half_w_sum = (get_house_panel_width(key_A) + get_house_panel_width(key_B)) / 2
                        if dist < half_w_sum + 30:
                            # Quadratic penalty to heavily penalize any close panels!
                            penalty += ((half_w_sum + 30) - dist) ** 2
                current_idx += r_size
            return penalty
            
        # Run dual-objective layout solver across all valid combinations
        candidates = get_partitions(count, section_rows, cols)
        best_partition = None
        best_overlap_penalty = float('inf')
        best_height_sum = float('inf')
        
        for p in candidates:
            overlap_p = calculate_overlap_penalty(p)
            
            current_idx = 0
            height_sum = 0
            for r_size in p:
                row_keys = keys_subset[current_idx : current_idx + r_size]
                if row_keys:
                    row_max = max(get_house_height(k) for k in row_keys)
                    height_sum += row_max
                current_idx += r_size
                
            # Primary objective: minimize horizontal overlap; Secondary objective: minimize vertical height
            if overlap_p < best_overlap_penalty:
                best_overlap_penalty = overlap_p
                best_height_sum = height_sum
                best_partition = p
            elif overlap_p == best_overlap_penalty:
                if height_sum < best_height_sum:
                    best_height_sum = height_sum
                    best_partition = p
                    
        if not best_partition:
            best_partition = []
            remaining = count
            for r in range(section_rows):
                take = math.ceil(remaining / (section_rows - r))
                best_partition.append(take)
                remaining -= take
                
        # Calculate dynamic row heights based on best optimal partition
        row_heights = []
        current_idx = 0
        for r_size in best_partition:
            row_keys = keys_subset[current_idx : current_idx + r_size]
            row_max = max(get_house_height(k) for k in row_keys) if row_keys else padding_y
            row_heights.append(row_max)
            current_idx += r_size
            
        width = cols * (house_size + padding_x) + padding_x
        current_y = 220 + padding_y
        
        positions = {}
        current_idx = 0
        for local_r, r_size in enumerate(best_partition):
            # Gather all houses in this row
            row_houses = keys_subset[current_idx : current_idx + r_size]
            
            for i, num in enumerate(row_houses):
                global_r = local_r + row_offset
                
                # Dynamic horizontal distribution to utilize full space on incomplete rows
                if r_size == 1:
                    c_index = (cols - 1) // 2
                elif r_size > 1:
                    c_index = int(round(i * (cols - 1) / (r_size - 1)))
                else:
                    c_index = i
                    
                # Serpentine horizontal ordering based on global row
                display_c = c_index if global_r % 2 == 0 else (cols - 1 - c_index)
                
                stagger_y = (display_c % 2) * 60  # Organic vertical serpentine stagger
                x = padding_x + display_c * (house_size + padding_x) + house_size / 2
                y = current_y + 135 + stagger_y  # Start below top of halo boundary
                positions[num] = (x, y)
                
            # Add extra vertical gap for the transition
            current_y += row_heights[local_r]
            current_idx += r_size
            
        height = current_y + padding_y
            
        img = Image.new('RGBA', (int(width), int(height)), color=(44, 47, 51, 255))
        
        # Load Background Wallpaper
        try:
            potential_paths = [
                os.path.join(os.path.dirname(__file__), "..", "assets", "contour_wall.jpg"),
                os.path.join(os.path.dirname(__file__), "..", "..", "contour_wall.jpg"),
                os.path.join(os.path.dirname(__file__), "assets", "contour_wall.jpg")
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
                bg = bg.resize((int(width), int(height)), Image.LANCZOS)
                img.paste(bg, (0, 0))
        except Exception:
            pass
            
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Smart robust dynamic font resolver to bypass Linux/Pterodactyl container font limitations
        font_choices = [
            # Standard local python packages / matplotlib fonts (highly likely on your server)
            os.path.join(os.path.dirname(__file__), "..", ".local", "lib", "python3.12", "site-packages", "matplotlib", "mpl-data", "fonts", "ttf", "DejaVuSans-Bold.ttf"),
            os.path.join(os.path.dirname(__file__), "..", ".local", "lib", "python3.12", "site-packages", "matplotlib", "mpl-data", "fonts", "ttf", "DejaVuSans.ttf"),
            
            # Local workspace files
            os.path.join(os.path.dirname(__file__), "..", "NotoSansEgyptianHieroglyphs-Regular.ttf"),
            os.path.join(os.path.dirname(__file__), "..", "papyrus.ttf"),
            
            # Standard Linux System Paths
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            
            # Windows System Fonts
            "arialbd.ttf",
            "arial.ttf",
            "tahoma.ttf",
            "segoeui.ttf"
        ]
        
        selected_font_path = None
        for f_path in font_choices:
            try:
                # Test load at size 10 to confirm font file is fully readable and valid
                ImageFont.truetype(f_path, 10)
                selected_font_path = f_path
                break
            except Exception:
                continue
                
        # If still not found, search the local directories dynamically for any standard DejaVu Sans TTF
        if not selected_font_path:
            try:
                search_dirs = [
                    os.path.join(os.path.dirname(__file__), "..", ".local"),
                    os.path.dirname(__file__),
                    os.path.join(os.path.dirname(__file__), "..")
                ]
                for s_dir in search_dirs:
                    if os.path.exists(s_dir):
                        for root, dirs, files in os.walk(s_dir):
                            for file in files:
                                if file.endswith(".ttf") and "DejaVuSans" in file:
                                    test_path = os.path.join(root, file)
                                    try:
                                        ImageFont.truetype(test_path, 10)
                                        selected_font_path = test_path
                                        break
                                    except Exception: pass
                            if selected_font_path: break
                    if selected_font_path: break
            except Exception: pass

        if selected_font_path:
            self._resolved_font_path = selected_font_path
            title_font = ImageFont.truetype(selected_font_path, 64)
            subtitle_font = ImageFont.truetype(selected_font_path, 30)
            label_font = ImageFont.truetype(selected_font_path, 38)
            names_font = ImageFont.truetype(selected_font_path, 42)
            small_font = ImageFont.truetype(selected_font_path, 32)
        else:
            # Last-resort bitmap fallback
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            label_font = ImageFont.load_default()
            names_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
            
        try:
            tw = draw.textbbox((0, 0), title, font=title_font)[2] - draw.textbbox((0, 0), title, font=title_font)[0]
            sw = draw.textbbox((0, 0), subtitle, font=subtitle_font)[2] - draw.textbbox((0, 0), subtitle, font=subtitle_font)[0]
        except AttributeError:
            tw = draw.textsize(title, font=title_font)[0]
            sw = draw.textsize(subtitle, font=subtitle_font)[0]
            
        # Draw Title with subtle shadow for contrast against wallpaper
        draw.text(((width - tw) / 2 + 2, 42), title, font=title_font, fill=(0, 0, 0))
        draw.text(((width - tw) / 2, 40), title, font=title_font, fill=(255, 215, 0))
        
        draw.text(((width - sw) / 2 + 1, 111), subtitle, font=subtitle_font, fill=(0, 0, 0))
        draw.text(((width - sw) / 2, 110), subtitle, font=subtitle_font, fill=(220, 220, 220))
        
        # Draw serpentine road connecting staggered coordinates organically
        road_points = [positions[k] for k in keys_subset]
        if len(road_points) > 1:
            draw.line(road_points, fill=(0, 0, 0, 100), width=32)
            draw.line(road_points, fill=(255, 255, 255, 20), width=4)
        
        bboxes = []
        for num in keys_subset:
            x, y = positions[num]
            h_data = houses[num]
            self.draw_house(draw, img, x, y, house_size, h_data, num, label_font, names_font, small_font, bboxes)
            
        return img.convert('RGB')

    def draw_house(self, draw, img, cx, cy, size, data, num, label_font, names_font, small_font, bboxes):
        status = data["status"]
        half = size / 2
        
        is_special = isinstance(num, str)
        owners = data.get("owners", [])
        residents = data.get("residents", [])
        
        # Atmospheric Dark Territory Halo (Semi-transparent black)
        halo_radius = size * 1.35
        draw.ellipse([cx - halo_radius, cy - halo_radius, cx + halo_radius, cy + halo_radius], fill=(0, 0, 0, 160))
        
        # 1. Compact Label (Emoji-free to prevent standard font missing-glyph box rendering)
        if is_special:
            clean_name = data["name"].replace("-", " ").title()
            label = clean_name
        else:
            label = f"House {num}"
            
        try:
            tw = draw.textbbox((0, 0), label, font=label_font)[2] - draw.textbbox((0, 0), label, font=label_font)[0]
        except AttributeError:
            tw = draw.textsize(label, font=label_font)[0]
            
        label_y = cy - half - 35
        l_bbox = (cx - tw/2 - 12, label_y - 8, cx + tw/2 + 12, label_y + 36)
        draw.rounded_rectangle(l_bbox, radius=6, fill=(18, 19, 21, 140), outline=(255, 255, 255, 15), width=1)
        draw.text((cx - tw/2, label_y), label, font=label_font, fill=(255, 255, 255))
        
        # 2. Gather occupants text lines and calculate heights
        lines = []
        if status == "occupied":
            # Add Owners
            for occ in owners:
                name = occ["name"]
                if len(name) > 10: name = name[:8]
                lines.append({
                    "text": name,
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
                if res["id"] in owner_ids: return 0
                if res["role_type"] == "player": return 1
                return 2
                
            sorted_residents = sorted(residents, key=res_priority)
            for occ in sorted_residents:
                name = occ["name"]
                if len(name) > 10: name = name[:8]
                c = (152, 251, 152) if occ.get("role_type") == "player" else (180, 180, 180)
                lines.append({
                    "text": name,
                    "color": c,
                    "font": names_font,
                    "avatar": occ.get("avatar"),
                    "is_owner": False
                })
                
        # Calculate Occupant roster dimensions
        avatar_size = 48
        total_h = 0
        max_w = 0
        line_details = []
        
        for line in lines:
            if line.get("type") == "divider":
                line_h = 24
                total_h += line_h
                line_details.append({"h": line_h})
            else:
                try:
                    bbox = draw.textbbox((0, 0), line["text"], font=line["font"])
                    tw_line = bbox[2] - bbox[0]
                    th_line = bbox[3] - bbox[1]
                except AttributeError:
                    tw_line, th_line = draw.textsize(line["text"], font=line["font"])
                    
                full_w = tw_line + (avatar_size + 12 if line.get("avatar") else 0)
                max_w = max(max_w, full_w)
                line_h = max(th_line, avatar_size) + 12
                total_h += line_h
                line_details.append({"h": line_h, "w": full_w, "tw": tw_line, "th": th_line})
                
        # 3. Draw Proportional House Node Art centered at (cx, cy)
        roof_top = (cx, cy - half)
        roof_left = (cx - half, cy - half + size * 0.45)
        roof_right = (cx + half, cy - half + size * 0.45)
        base_tl = (cx - half + 12, cy - half + size * 0.45)
        base_tr = (cx + half - 12, cy - half + size * 0.45)
        base_bl = (cx - half + 12, cy + half - 10)
        base_br = (cx + half - 12, cy + half - 10)
        
        if status == "destroyed":
            draw.polygon([base_bl, (cx - size*0.4, cy), (cx, cy + size*0.1), (cx + size*0.4, cy - size*0.1), base_br], fill=(70, 70, 70, 255))
            draw.line([(cx - size*0.4, cy), (cx + size*0.1, cy + size*0.1), (cx - size*0.1, cy + size*0.3)], fill=(40, 40, 40, 255), width=6)
            
            ruin_text = "RUINS"
            try:
                rtw = draw.textbbox((0, 0), ruin_text, font=small_font)[2] - draw.textbbox((0, 0), ruin_text, font=small_font)[0]
            except AttributeError:
                rtw = draw.textsize(ruin_text, font=small_font)[0]
            
            # Draw snug background panel specifically under the text
            panel_w = max(rtw + 40, 160)
            panel_rect = [cx - panel_w / 2, cy + half + 20, cx + panel_w / 2, cy + half + 70]
            draw.rounded_rectangle(panel_rect, radius=8, fill=(25, 12, 12, 130), outline=(220, 50, 50, 18), width=1)
            draw.text((cx - rtw/2, cy + half + 28), ruin_text, fill=(240, 71, 71), font=small_font)
        else:
            if is_special:
                color = (72, 61, 139, 255) if status == "occupied" else (55, 50, 80, 255)
                roof_color = (218, 165, 32, 255) if status == "occupied" else (110, 85, 15, 255)
            else:
                color = (139, 69, 19, 255) if status == "occupied" else (80, 80, 80, 255)
                roof_color = (178, 34, 34, 255) if status == "occupied" else (60, 60, 60, 255)
                
            draw.rectangle([base_tl, base_br], fill=color)
            draw.polygon([roof_top, roof_left, roof_right], fill=roof_color)
            
            door_w = size * 0.25
            door_h = size * 0.35
            draw.rectangle([(cx - door_w/2, base_br[1] - door_h), (cx + door_w/2, base_br[1])], fill=(60, 30, 0, 255) if status == "occupied" else (40, 40, 40, 255))
            
            win_color = (255, 215, 0, 255) if status == "occupied" else (40, 40, 40, 255)
            draw.rectangle([cx - size*0.35, cy - size*0.1, cx - size*0.2, cy + size*0.15], fill=win_color)
            draw.rectangle([cx + size*0.2, cy - size*0.1, cx + size*0.35, cy + size*0.15], fill=win_color)
            
        # 4. Draw Snug Occupant roster background shield (Readability Backing Panel)
        if status == "occupied":
            # Dynamic card width: shrink cards with fewer members to maximize breathing room and prevent overlap
            occupant_count = len(lines)
            if occupant_count <= 1:
                min_w = 200
            elif occupant_count == 2:
                min_w = 240
            else:
                min_w = 300
                
            panel_w = max(max_w + 40, min_w)
            panel_left = cx - panel_w / 2
            panel_right = cx + panel_w / 2
            panel_top = cy + half + 20
            panel_bottom = panel_top + total_h + 15
            
            # Snug, atmospheric semi-transparent dark backing shield pill specifically wrapping the roster text
            draw.rounded_rectangle([panel_left, panel_top, panel_right, panel_bottom], radius=10, fill=(15, 15, 17, 130), outline=(255, 255, 255, 12), width=1)
            
            current_y = panel_top + 8
            for i, line in enumerate(lines):
                detail = line_details[i]
                if line.get("type") == "divider":
                    line_y = current_y + 12
                    draw.line([(panel_left + 16, line_y), (panel_right - 16, line_y)], fill=(255, 255, 255, 40), width=2)
                    current_y += detail["h"]
                else:
                    tx = panel_left + 18
                    has_avatar = line.get("avatar") and getattr(self, 'SHOW_AVATARS', True)
                    
                    if has_avatar:
                        try:
                            av_img = Image.open(io.BytesIO(line["avatar"])).convert("RGBA")
                            av_img = av_img.resize((avatar_size, avatar_size))
                            mask = Image.new("L", (avatar_size, avatar_size), 0)
                            m_draw = ImageDraw.Draw(mask)
                            m_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
                            av_img.putalpha(mask)
                            
                            # Draw Gold Crown Badge overlay on Owner's Avatar bottom right corner
                            if line.get("is_owner"):
                                av_draw = ImageDraw.Draw(av_img)
                                badge_r = 10
                                badge_cx = avatar_size - badge_r
                                badge_cy = avatar_size - badge_r
                                # Gold circular background badge (semi-transparent border)
                                av_draw.ellipse([badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r], fill=(255, 215, 0, 255), outline=(0, 0, 0, 255), width=1)
                                
                                # Draw a tiny crown shape or text in the center of the badge
                                try:
                                    badge_font_path = getattr(self, '_resolved_font_path', 'DejaVuSans-Bold.ttf')
                                    badge_font = ImageFont.truetype(badge_font_path, 15)
                                    av_draw.text((badge_cx - 7, badge_cy - 11), "♛", font=badge_font, fill=(0, 0, 0, 255))
                                except Exception:
                                    # Fallback
                                    av_draw.text((badge_cx - 4, badge_cy - 8), "*", fill=(0, 0, 0, 255))
                                    
                            img.paste(av_img, (int(tx), int(current_y + detail["h"]/2 - avatar_size/2)), av_img)
                        except Exception: pass
                        tx += avatar_size + 12
                        
                    # Prefix crown to text ONLY if there is no avatar (perfect alignment fallback!)
                    drawn_text = f"♛ {line['text']}" if (line.get("is_owner") and not has_avatar) else line["text"]
                    
                    # Calculate accurate text size for the drawn prefix fallback
                    try:
                        bbox = draw.textbbox((0, 0), drawn_text, font=line["font"])
                        tw_drawn = bbox[2] - bbox[0]
                        th_drawn = bbox[3] - bbox[1]
                    except AttributeError:
                        tw_drawn, th_drawn = draw.textsize(drawn_text, font=line["font"])
                        
                    text_y = current_y + detail["h"]/2 - th_drawn/2 - 4
                    for sx in [-2, 2]:
                        for sy in [-2, 2]:
                            draw.text((tx+sx, text_y+sy), drawn_text, font=line["font"], fill=(0,0,0))
                    draw.text((tx, text_y), drawn_text, font=line["font"], fill=line["color"])
                    current_y += detail["h"]
                    
        elif status == "empty":
            text = "(Empty)"
            try:
                etw = draw.textbbox((0, 0), text, font=small_font)[2] - draw.textbbox((0, 0), text, font=small_font)[0]
            except AttributeError:
                etw = draw.textsize(text, font=small_font)[0]
                
            panel_w = max(etw + 40, 160)
            panel_rect = [cx - panel_w / 2, cy + half + 20, cx + panel_w / 2, cy + half + 70]
            draw.rounded_rectangle(panel_rect, radius=8, fill=(15, 15, 17, 110), outline=(255, 255, 255, 10), width=1)
            draw.text((cx - etw/2, cy + half + 28), text, font=small_font, fill=(160, 160, 160))


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
# test1
async def setup(bot):
    await bot.add_cog(Estate(bot))
