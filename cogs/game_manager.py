import discord
from discord import SelectOption
from discord.ext import commands
from discord.ui import View, Button, Select
from discord.utils import get
import sqlite3

# In‑memory store for active games
games = {}

games_db_path = 'db/games.db'

def init_games_db():
    conn = sqlite3.connect(games_db_path, timeout=30.0)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS active_games (
                    game_id INTEGER PRIMARY KEY,
                    host_id INTEGER,
                    message_id INTEGER,
                    hostname TEXT,
                    game_name TEXT,
                    role_name TEXT,
                    max_slots INTEGER
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS game_slots (
                    game_id INTEGER,
                    slot_number INTEGER,
                    player_id TEXT,
                    sponsor_id TEXT,
                    PRIMARY KEY (game_id, slot_number),
                    FOREIGN KEY (game_id) REFERENCES active_games (game_id) ON DELETE CASCADE
                )''')
    conn.commit()
    conn.close()

class GameSign:
    def __init__(self, max_slots, host_id, message_id, hostname, game_name, role_name):
        self.max_slots = max_slots
        self.host_id = host_id
        self.message_id = message_id
        self.hostname = hostname
        self.game_name = game_name
        self.role_name = role_name
        self.slots = {str(i): {"player": None, "sponsor": None} for i in range(1, max_slots + 1)}

class GameView(View):
    def __init__(self, game_id, bot):
        super().__init__(timeout=None)
        self.game_id = game_id
        self.bot = bot
        self.add_item(PlayerJoinButton(game_id))
        self.add_item(SponsorJoinButton(game_id))
        self.add_item(LeaveButton(game_id))

    async def update_embed(self):
        game = games.get(self.game_id)
        if not game:
            return
        try:
            channel = self.bot.get_channel(self.game_id)
            message = await channel.fetch_message(game.message_id)
            # Cache users
            users_to_cache = set()
            for slot in game.slots.values():
                if slot['player']:
                    users_to_cache.add(int(slot['player']))
                if slot['sponsor']:
                    users_to_cache.add(int(slot['sponsor']))
            for uid in users_to_cache:
                try:
                    await self.bot.fetch_user(uid)
                except:
                    pass
            embed = discord.Embed(title=f"Game Lobby: {game.game_name}", color=0x00ff00)
            embed.add_field(name="Host", value=f"{game.hostname} (<@{game.host_id}>)", inline=False)
            slot_text = ""
            for num, data in game.slots.items():
                player = f"<@{data['player']}>" if data['player'] else "Empty"
                slot_info = f"Slot {num}: {player}"
                if data['sponsor']:
                    slot_info += f"\n   Sponsor: <@{data['sponsor']}>"
                if len(slot_text) + len(slot_info) > 1024:
                    embed.add_field(name="Slots", value=slot_text, inline=False)
                    slot_text = slot_info
                else:
                    slot_text += "\n" + slot_info if slot_text else slot_info
            if slot_text:
                embed.add_field(name="Slots", value=slot_text, inline=False)
            await message.edit(embed=embed)
        except Exception as e:
            print(f"Error updating embed: {e}")

class PlayerJoinButton(Button):
    def __init__(self, game_id):
        super().__init__(label="Join as Player", style=discord.ButtonStyle.green, custom_id=f"game_{game_id}_player_join")
        self.game_id = game_id

    async def callback(self, interaction: discord.Interaction):
        game = games[self.game_id]
        user_id = str(interaction.user.id)
        if any(slot["player"] == user_id or slot["sponsor"] == user_id for slot in game.slots.values()):
            await interaction.response.send_message("You're already in a slot!", ephemeral=True)
            return
        available = [SelectOption(label=f"Slot {i}", value=str(i)) for i in range(1, game.max_slots + 1) if not game.slots[str(i)]["player"]]
        if not available:
            await interaction.response.send_message("All player slots are full!", ephemeral=True)
            return
        pages = [available[i:i+20] for i in range(0, len(available), 20)]
        view = SimplePaginationView(self.game_id, pages, 0, self.view)
        await interaction.response.send_message(f"# 🎮 {interaction.user.mention}\n## Choose your player slot:", view=view, ephemeral=True)

class SimplePaginationView(View):
    def __init__(self, game_id, pages, current_page, main_view):
        super().__init__(timeout=60)
        self.game_id = game_id
        self.pages = pages
        self.current_page = current_page
        self.main_view = main_view
        self.add_item(PlayerSlotSelect(game_id, pages[current_page], main_view))
        if len(pages) > 1:
            if current_page > 0:
                prev = Button(label="Previous", style=discord.ButtonStyle.secondary, custom_id=f"prev_{game_id}_{current_page}")
                prev.callback = self.prev_button_callback
                self.add_item(prev)
            if current_page < len(pages) - 1:
                nxt = Button(label="Next", style=discord.ButtonStyle.secondary, custom_id=f"next_{game_id}_{current_page}")
                nxt.callback = self.next_button_callback
                self.add_item(nxt)
        self.add_item(Button(label=f"Page {current_page+1}/{len(pages)}", style=discord.ButtonStyle.gray, disabled=True, custom_id=f"page_indicator_{game_id}_{current_page}"))

    async def prev_button_callback(self, interaction: discord.Interaction):
        if self.current_page > 0:
            new_view = SimplePaginationView(self.game_id, self.pages, self.current_page - 1, self.main_view)
            await interaction.response.edit_message(view=new_view)

    async def next_button_callback(self, interaction: discord.Interaction):
        if self.current_page < len(self.pages) - 1:
            new_view = SimplePaginationView(self.game_id, self.pages, self.current_page + 1, self.main_view)
            await interaction.response.edit_message(view=new_view)

class PlayerSlotSelect(Select):
    def __init__(self, game_id, options, main_view):
        super().__init__(placeholder="Select a slot...", options=options)
        self.game_id = game_id
        self.main_view = main_view

    async def callback(self, interaction: discord.Interaction):
        game = games[self.game_id]
        slot_num = self.values[0]
        user_id = str(interaction.user.id)
        if any(slot["player"] == user_id or slot["sponsor"] == user_id for slot in game.slots.values()):
            await interaction.response.send_message("You're already in a slot! Leave your current slot first.", ephemeral=True)
            return
        if game.slots[slot_num]["player"]:
            await interaction.response.send_message("Slot already taken!", ephemeral=True)
        else:
            game.slots[slot_num]["player"] = user_id
            conn = sqlite3.connect(games_db_path, timeout=30.0)
            c = conn.cursor()
            c.execute('UPDATE game_slots SET player_id = ? WHERE game_id = ? AND slot_number = ?', (user_id, self.game_id, int(slot_num)))
            conn.commit()
            conn.close()
            await interaction.response.send_message(f"Joined slot {slot_num} as player!", ephemeral=True)
            await self.main_view.update_embed()
            if game.role_name:
                await assign_role(interaction.guild, interaction.user, game.role_name)

class SponsorJoinButton(Button):
    def __init__(self, game_id):
        super().__init__(label="Join as Sponsor", style=discord.ButtonStyle.blurple, custom_id=f"game_{game_id}_sponsor_join")
        self.game_id = game_id

    async def callback(self, interaction: discord.Interaction):
        game = games[self.game_id]
        user_id = str(interaction.user.id)
        if any(slot["sponsor"] == user_id for slot in game.slots.values()):
            await interaction.response.send_message("You're already sponsoring a slot!", ephemeral=True)
            return
        available = [SelectOption(label=f"Slot {i}", value=str(i)) for i in range(1, game.max_slots + 1) if game.slots[str(i)]["player"] and not game.slots[str(i)]["sponsor"]]
        if not available:
            await interaction.response.send_message("No available slots to sponsor!", ephemeral=True)
            return
        view = SponsorSlotView(self.game_id, available, self.view)
        await interaction.response.send_message("Choose a slot to sponsor:", view=view, ephemeral=True)

class SponsorSlotView(View):
    def __init__(self, game_id, options, main_view):
        super().__init__(timeout=60)
        self.main_view = main_view
        self.add_item(SponsorSlotSelect(game_id, options))

class SponsorSlotSelect(Select):
    def __init__(self, game_id, options):
        super().__init__(placeholder="Select a slot...", options=options)
        self.game_id = game_id

    async def callback(self, interaction: discord.Interaction):
        game = games[self.game_id]
        slot_num = self.values[0]
        user_id = str(interaction.user.id)
        if game.slots[slot_num]["sponsor"]:
            await interaction.response.send_message("Slot already sponsored!", ephemeral=True)
        else:
            game.slots[slot_num]["sponsor"] = user_id
            conn = sqlite3.connect(games_db_path, timeout=30.0)
            c = conn.cursor()
            c.execute('UPDATE game_slots SET sponsor_id = ? WHERE game_id = ? AND slot_number = ?', (user_id, self.game_id, int(slot_num)))
            conn.commit()
            conn.close()
            await interaction.response.send_message(f"Now sponsoring slot {slot_num}!", ephemeral=True)
            await self.view.main_view.update_embed()

class LeaveButton(Button):
    def __init__(self, game_id):
        super().__init__(label="Leave Slot", style=discord.ButtonStyle.red, custom_id=f"game_{game_id}_leave")
        self.game_id = game_id

    async def callback(self, interaction: discord.Interaction):
        game = games[self.game_id]
        user_id = str(interaction.user.id)
        removed = False
        for num, slot in game.slots.items():
            if slot["player"] == user_id or slot["sponsor"] == user_id:
                slot["player"] = None if slot["player"] == user_id else slot["player"]
                slot["sponsor"] = None if slot["sponsor"] == user_id else slot["sponsor"]
                removed = True
                conn = sqlite3.connect(games_db_path, timeout=30.0)
                c = conn.cursor()
                c.execute('UPDATE game_slots SET player_id = ?, sponsor_id = ? WHERE game_id = ? AND slot_number = ?', (slot["player"], slot["sponsor"], self.game_id, int(num)))
                conn.commit()
                conn.close()
        await interaction.response.send_message("Left your slot!" if removed else "You weren't in any slot!", ephemeral=True)
        await self.view.update_embed()
        if removed and game.role_name:
            await remove_role(interaction.guild, interaction.user, game.role_name)
            host = interaction.guild.get_member(int(game.host_id))
            if host:
                await host.send(f"{interaction.user.name} has left the game lobby.")

class GameManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        init_games_db()
        conn = sqlite3.connect(games_db_path, timeout=30.0)
        c = conn.cursor()
        c.execute('SELECT * FROM active_games')
        rows = c.fetchall()
        for row in rows:
            game_id, host_id, message_id, hostname, game_name, role_name, max_slots = row
            game = GameSign(max_slots, host_id, message_id, hostname, game_name, role_name)
            c.execute('SELECT slot_number, player_id, sponsor_id FROM game_slots WHERE game_id = ?', (game_id,))
            slots = c.fetchall()
            for slot_num, player_id, sponsor_id in slots:
                game.slots[str(slot_num)] = {"player": player_id, "sponsor": sponsor_id}
            games[game_id] = game
        conn.close()
        for gid in list(games.keys()):
            try:
                channel = self.bot.get_channel(gid)
                if channel:
                    self.bot.add_view(GameView(gid, self.bot))
                else:
                    conn = sqlite3.connect(games_db_path, timeout=30.0)
                    cur = conn.cursor()
                    cur.execute('DELETE FROM active_games WHERE game_id = ?', (gid,))
                    conn.commit()
                    conn.close()
                    del games[gid]
            except Exception as e:
                print(f"Error re-registering view {gid}: {e}")

    @commands.command(aliases=['sg'])
    async def startgame(self, ctx, max_slots: int, host: discord.Member, *, args):
        """Start a new game lobby with specified slots and host."""
        if not 2 <= max_slots <= 50:
            return await ctx.send("Slots must be between 2-50")
        args_list = args.split()
        role_name = None
        name_parts = []
        i = 0
        while i < len(args_list):
            if args_list[i] == "-role" and i + 1 < len(args_list):
                role_name = args_list[i + 1]
                i += 2
            else:
                name_parts.append(args_list[i])
                i += 1
        game_name = " ".join(name_parts)
        if not game_name:
            return await ctx.send("Please provide a game name.")
        # Duplicate name check (case‑insensitive)
        for g in games.values():
            if g.game_name.lower() == game_name.lower():
                return await ctx.send(f"A game with the name '{game_name}' already exists.")
        game_id = ctx.channel.id
        games[game_id] = GameSign(max_slots, host.id, None, host.display_name, game_name, role_name)
        view = GameView(game_id, self.bot)
        message = await ctx.send(f"Game lobby initializing for {game_name} hosted by {host.mention}...", view=view)
        games[game_id].message_id = message.id
        conn = sqlite3.connect(games_db_path, timeout=30.0)
        c = conn.cursor()
        c.execute('INSERT INTO active_games VALUES (?, ?, ?, ?, ?, ?, ?)', (game_id, host.id, message.id, host.display_name, game_name, role_name, max_slots))
        for i in range(1, max_slots + 1):
            c.execute('INSERT INTO game_slots (game_id, slot_number, player_id, sponsor_id) VALUES (?, ?, ?, ?)', (game_id, i, None, None))
        conn.commit()
        conn.close()
        await view.update_embed()

    @commands.command(aliases=['ap'])
    async def addplayer(self, ctx, slot_num: int, player: discord.Member, *, game_name: str = None):
        """Add a player to an empty slot (Admin or Host only)"""
        game_id = ctx.channel.id
        game = games.get(game_id)
        if not game:
            if not game_name:
                return await ctx.send("No active game in this channel. Please specify a game name.")
            for gid, g in games.items():
                if g.game_name.lower() == game_name.lower():
                    game = g
                    game_id = gid
                    break
            if not game:
                return await ctx.send(f"No game found with name '{game_name}'")
        is_admin = ctx.author.guild_permissions.administrator
        is_host = str(ctx.author.id) == str(game.host_id)
        if not (is_admin or is_host):
            return await ctx.send("You must be an administrator or the game host to use this command.")
        if not 1 <= slot_num <= game.max_slots:
            return await ctx.send(f"Invalid slot number. Please choose between 1 and {game.max_slots}")
        slot_key = str(slot_num)
        if game.slots[slot_key]["player"]:
            return await ctx.send(f"Slot {slot_num} is already taken by <@{game.slots[slot_key]['player']}>")
        user_id = str(player.id)
        for slot in game.slots.values():
            if slot["player"] == user_id:
                return await ctx.send(f"{player.mention} is already in another slot. Please remove them first.")
        game.slots[slot_key]["player"] = user_id
        conn = sqlite3.connect(games_db_path, timeout=30.0)
        c = conn.cursor()
        c.execute('UPDATE game_slots SET player_id = ? WHERE game_id = ? AND slot_number = ?', (user_id, game_id, slot_num))
        conn.commit()
        conn.close()
        channel = self.bot.get_channel(game_id)
        if channel:
            await GameView(game_id, self.bot).update_embed()
        await ctx.send(f"Added {player.mention} to slot {slot_num} in game '{game.game_name}'")

    @commands.command(aliases=['rp'])
    async def removeplayer(self, ctx, slot_num: int, *, game_name: str = None):
        """Remove a player from a slot (Admin or Host only)"""
        game_id = ctx.channel.id
        game = games.get(game_id)
        if not game:
            if not game_name:
                return await ctx.send("No active game in this channel. Please specify a game name.")
            for gid, g in games.items():
                if g.game_name.lower() == game_name.lower():
                    game = g
                    game_id = gid
                    break
            if not game:
                return await ctx.send(f"No game found with name '{game_name}'")
        is_admin = ctx.author.guild_permissions.administrator
        is_host = str(ctx.author.id) == str(game.host_id)
        if not (is_admin or is_host):
            return await ctx.send("You must be an administrator or the game host to use this command.")
        if not 1 <= slot_num <= game.max_slots:
            return await ctx.send(f"Invalid slot number. Please choose between 1 and {game.max_slots}")
        slot_key = str(slot_num)
        if not game.slots[slot_key]["player"]:
            return await ctx.send(f"Slot {slot_num} is already empty")
        player_id = game.slots[slot_key]["player"]
        player_mention = f"<@{player_id}>"
        game.slots[slot_key]["player"] = None
        game.slots[slot_key]["sponsor"] = None
        conn = sqlite3.connect(games_db_path, timeout=30.0)
        c = conn.cursor()
        c.execute('UPDATE game_slots SET player_id = ?, sponsor_id = ? WHERE game_id = ? AND slot_number = ?', (None, None, game_id, slot_num))
        conn.commit()
        conn.close()
        channel = self.bot.get_channel(game_id)
        if channel:
            await GameView(game_id, self.bot).update_embed()
        await ctx.send(f"Removed {player_mention} from slot {slot_num} in game '{game.game_name}'")

    @commands.command(aliases=['cg'])
    async def closegame(self, ctx, *, game_name: str = None):
        """Close a game lobby by channel or by name. Host or admins only."""
        if game_name:
            target_id = None
            target_game = None
            for gid, g in games.items():
                if g.game_name.lower() == game_name.lower():
                    target_id = gid
                    target_game = g
                    break
            if not target_game:
                return await ctx.send(f"No active game found with name '{game_name}'.")
        else:
            target_id = ctx.channel.id
            target_game = games.get(target_id)
            if not target_game:
                return await ctx.send("No active game in this channel.")
        is_admin = ctx.author.guild_permissions.administrator
        is_host = str(ctx.author.id) == str(target_game.host_id)
        if not (is_admin or is_host):
            return await ctx.send("You must be the host or an administrator to close the lobby.")
        conn = sqlite3.connect(games_db_path, timeout=30.0)
        c = conn.cursor()
        c.execute('DELETE FROM active_games WHERE game_id = ?', (target_id,))
        c.execute('DELETE FROM game_slots WHERE game_id = ?', (target_id,))
        conn.commit()
        conn.close()
        del games[target_id]
        try:
            channel = self.bot.get_channel(target_id)
            if channel:
                message = await channel.fetch_message(target_game.message_id)
                await message.delete()
        except Exception:
            pass
        await ctx.send("Game lobby closed and data removed.")

async def assign_role(guild, member, role_name):
    if not role_name:
        return
    role = get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name)
    await member.add_roles(role)

async def remove_role(guild, member, role_name):
    if not role_name:
        return
    role = get(guild.roles, name=role_name)
    if role and role in member.roles:
        await member.remove_roles(role)