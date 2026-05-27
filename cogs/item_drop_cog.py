import discord
from discord.ext import commands, tasks
import sqlite3
import re
import random
from datetime import datetime, timedelta, timezone
import os

# We assume cogs.data_utils is available based on existing codebase
from cogs.data_utils import load_guild_data

DB_PATH = 'db/item_drops.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS drops (
        message_id INTEGER PRIMARY KEY,
        channel_id INTEGER,
        log_channel_id INTEGER,
        name TEXT,
        description TEXT,
        count INTEGER,
        showpickups BOOLEAN,
        showremaining BOOLEAN,
        expire_at TIMESTAMP,
        emoji TEXT,
        depleted BOOLEAN,
        guild_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS claims (
        message_id INTEGER,
        user_id INTEGER,
        timestamp TIMESTAMP,
        PRIMARY KEY (message_id, user_id)
    )''')
    conn.commit()
    conn.close()

def parse_duration(duration_str):
    match = re.match(r"(\d+)([mhd])", duration_str.lower())
    if match:
        val = int(match.group(1))
        unit = match.group(2)
        if unit == 'm':
            return timedelta(minutes=val)
        elif unit == 'h':
            return timedelta(hours=val)
        elif unit == 'd':
            return timedelta(days=val)
    return None

def get_drop(message_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM drops WHERE message_id = ?", (message_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_claims(message_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM claims WHERE message_id = ? ORDER BY timestamp ASC", (message_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_drops():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM drops WHERE depleted = 0")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def claim_item(message_id, user_id, max_count):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM claims WHERE message_id = ?", (message_id,))
    current_count = c.fetchone()[0]
    if current_count >= max_count:
        conn.close()
        return False, "depleted"
    
    try:
        ts = datetime.now(timezone.utc).isoformat()
        c.execute("INSERT INTO claims (message_id, user_id, timestamp) VALUES (?, ?, ?)", 
                  (message_id, user_id, ts))
        conn.commit()
        
        # Check if depleted now
        if current_count + 1 >= max_count:
            c.execute("UPDATE drops SET depleted = 1 WHERE message_id = ?", (message_id,))
            conn.commit()
            conn.close()
            return True, "success_depleted"
            
        conn.close()
        return True, "success"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "already_claimed"

def generate_drop_embed(drop_data, claims_data=None):
    emoji = drop_data['emoji'] if drop_data['emoji'] else "📦"
    
    embed = discord.Embed(
        title=f"{emoji} {drop_data['name']}", 
        description=f"*{drop_data['description']}*", 
        color=0x2b2d31  # Dark theme color for premium look
    )
    
    status = "🟢 **Active**"
    if drop_data['depleted']:
        status = "🔴 **Depleted**"
    elif drop_data['expire_at']:
        expire_dt = datetime.fromisoformat(drop_data['expire_at'])
        if datetime.now(timezone.utc) > expire_dt:
            status = "⏱️ **Expired**"
            
    embed.add_field(name="Status", value=status, inline=True)
        
    if drop_data['expire_at']:
        expire_dt = datetime.fromisoformat(drop_data['expire_at'])
        embed.add_field(name="Expires", value=f"<t:{int(expire_dt.timestamp())}:R>", inline=True)
        
    if drop_data['showpickups'] and claims_data:
        claims_str = "\n".join([f"🔹 <@{c['user_id']}> - <t:{int(datetime.fromisoformat(c['timestamp']).timestamp())}:t>" for c in claims_data])
        if len(claims_str) > 1024:
            claims_str = claims_str[:1020] + "..."
        embed.add_field(name="Claimed By", value=claims_str, inline=False)
        
    embed.set_footer(text="Village Game • Interactive Drop System")
    return embed

class ItemDropView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        
        self.pickup_button = discord.ui.Button(
            label="Pick Up", 
            style=discord.ButtonStyle.success,
            custom_id=f"item_drop_pickup:{message_id}",
            emoji="✋"
        )
        self.pickup_button.callback = self.pickup_callback
        self.add_item(self.pickup_button)
        
    async def pickup_callback(self, interaction: discord.Interaction):
        # Interaction validation
        guild_data = load_guild_data(interaction.guild_id)
        if guild_data:
            alive_role_name = guild_data.get("alive_role_name", "Alive")
            alive_role = discord.utils.get(interaction.guild.roles, name=alive_role_name)
            if alive_role and alive_role not in interaction.user.roles:
                return await interaction.response.send_message("You must be Alive to pick up this item.", ephemeral=True)
                
        drop_data = get_drop(self.message_id)
        if not drop_data:
            return await interaction.response.send_message("This drop is no longer active or tracked.", ephemeral=True)
            
        if drop_data['expire_at']:
            expire_dt = datetime.fromisoformat(drop_data['expire_at'])
            if datetime.now(timezone.utc) > expire_dt:
                await self.update_message(interaction.client, interaction.guild)
                return await interaction.response.send_message("This item has expired.", ephemeral=True)
            
        if drop_data['depleted']:
            return await interaction.response.send_message("This item has been depleted.", ephemeral=True)
            
        # Attempt claim
        success, reason = claim_item(self.message_id, interaction.user.id, drop_data['count'])
        if not success:
            if reason == "depleted":
                await self.update_message(interaction.client, interaction.guild)
                return await interaction.response.send_message("You were too late! The item is depleted.", ephemeral=True)
            elif reason == "already_claimed":
                return await interaction.response.send_message("You have already claimed this item.", ephemeral=True)
                
        # Successful claim
        await interaction.response.send_message(f"You successfully picked up: **{drop_data['name']}**!", ephemeral=True)
        
        # Logging
        log_channel = interaction.guild.get_channel(drop_data['log_channel_id'])
        if log_channel:
            log_embed = discord.Embed(title="📦 Item Picked Up", color=discord.Color.green())
            log_embed.add_field(name="Item", value=drop_data['name'], inline=True)
            log_embed.add_field(name="User", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
            log_embed.set_footer(text=f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            await log_channel.send(embed=log_embed)
            
        # Update original message embed
        await self.update_message(interaction.client, interaction.guild)

    async def update_message(self, client, guild):
        drop_data = get_drop(self.message_id)
        if not drop_data:
            return
            
        channel = guild.get_channel(drop_data['channel_id'])
        if not channel:
            return
            
        try:
            message = await channel.fetch_message(self.message_id)
        except discord.NotFound:
            return
            
        claims_data = get_claims(self.message_id)
        embed = generate_drop_embed(drop_data, claims_data)
        
        is_expired = False
        if drop_data['expire_at']:
            expire_dt = datetime.fromisoformat(drop_data['expire_at'])
            if datetime.now(timezone.utc) > expire_dt:
                is_expired = True
                
        if drop_data['depleted'] or is_expired:
            self.pickup_button.disabled = True
            self.pickup_button.style = discord.ButtonStyle.secondary
            await message.edit(embed=embed, view=self)
        else:
            await message.edit(embed=embed, view=self)

class ItemDrop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_db()

    @commands.Cog.listener()
    async def on_ready(self):
        active_drops = get_active_drops()
        for drop in active_drops:
            self.bot.add_view(ItemDropView(drop['message_id']))
            
        if not self.check_expirations.is_running():
            self.check_expirations.start()

    def cog_unload(self):
        if self.check_expirations.is_running():
            self.check_expirations.cancel()

    @tasks.loop(minutes=1)
    async def check_expirations(self):
        active_drops = get_active_drops()
        for drop in active_drops:
            if drop['expire_at']:
                expire_dt = datetime.fromisoformat(drop['expire_at'])
                if datetime.now(timezone.utc) > expire_dt:
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute("UPDATE drops SET depleted = 1 WHERE message_id = ?", (drop['message_id'],))
                    conn.commit()
                    conn.close()
                    
                    guild = self.bot.get_guild(drop['guild_id'])
                    if guild:
                        channel = guild.get_channel(drop['channel_id'])
                        if channel:
                            try:
                                message = await channel.fetch_message(drop['message_id'])
                                claims_data = get_claims(drop['message_id'])
                                drop['depleted'] = 1  # update local dict for embed generation
                                embed = generate_drop_embed(drop, claims_data)
                                view = ItemDropView(drop['message_id'])
                                view.pickup_button.disabled = True
                                view.pickup_button.style = discord.ButtonStyle.secondary
                                await message.edit(embed=embed, view=view)
                            except discord.NotFound:
                                pass

    @check_expirations.before_loop
    async def before_check_expirations(self):
        await self.bot.wait_until_ready()

    @commands.command(name='dropitem')
    async def dropitem(self, ctx, channel: discord.TextChannel, log_channel: discord.TextChannel, name: str, description: str, count: int, showpickups: bool, duration_str: str = None):
        guild_data = load_guild_data(ctx.guild.id)
        overseer_role_name = guild_data.get("overseer_role_name", "Overseer") if guild_data else "Overseer"
        overseer_role = discord.utils.get(ctx.guild.roles, name=overseer_role_name)
        
        if not ctx.author.guild_permissions.administrator and (overseer_role not in ctx.author.roles):
            return await ctx.send("You do not have permission to use this command.")

        expire_at_iso = None
        if duration_str:
            delta = parse_duration(duration_str)
            if delta:
                expire_dt = datetime.now(timezone.utc) + delta
                expire_at_iso = expire_dt.isoformat()
            else:
                return await ctx.send("Invalid duration format. Use e.g. `30m`, `12h`, `2d`.")
                
        random_emojis = ['📦', '💎', '📜', '🩸', '🗝️', '🗡️', '🏺', '🧪', '🧿', '🔮']
        emoji = random.choice(random_emojis)
                
        # Initial Drop Data for embed
        drop_data = {
            'name': name,
            'description': description,
            'count': count,
            'showpickups': showpickups,
            'showremaining': False,
            'expire_at': expire_at_iso,
            'emoji': emoji,
            'depleted': 0
        }
        
        embed = generate_drop_embed(drop_data, [])
        
        # Send message to target channel to get message ID
        msg = await channel.send(embed=embed)
        
        # Save to DB
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''INSERT INTO drops (
            message_id, channel_id, log_channel_id, name, description, 
            count, showpickups, showremaining, expire_at, emoji, depleted, guild_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            msg.id, channel.id, log_channel.id, name, description,
            count, showpickups, False, expire_at_iso, emoji, 0, ctx.guild.id
        ))
        conn.commit()
        conn.close()
        
        # Attach view now that we have message_id
        view = ItemDropView(msg.id)
        await msg.edit(view=view)
        
        # Add view to persistent views
        self.bot.add_view(view)
        
        await ctx.send(f"Successfully dropped **{name}** in {channel.mention} with emoji {emoji}.")
