import discord
import datetime
from discord.ext import commands
from datetime import datetime
from cogs.data_utils import load_guild_data
import aiosqlite
import re

def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())

class Nominations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_listener(self.on_ready, "on_ready")
        self.conn: aiosqlite.Connection | None = None

    async def on_ready(self):
        await self.init_db()

    async def init_db(self):
        self.conn = await aiosqlite.connect('db/nominations.db')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS votes (
                channel_id INTEGER,
                voter_id INTEGER,
                vote TEXT,
                voting_closed BOOLEAN DEFAULT 0,
                PRIMARY KEY (channel_id, voter_id)
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                user_id INTEGER,
                guild_id INTEGER,
                balance INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        # New: single source of truth for whether a nomination channel is closed
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS vote_status (
                channel_id INTEGER PRIMARY KEY,
                closed BOOLEAN DEFAULT 0
            )
        ''')
        await self.conn.commit()

    async def cog_unload(self):
        if self.conn:
            await self.conn.close()

    async def update_tokens(self, user_id: int, guild_id: int, amount: int):
        await self.conn.execute(
            'INSERT OR IGNORE INTO tokens (user_id, guild_id, balance) VALUES (?, ?, 0)',
            (user_id, guild_id)
        )
        await self.conn.execute(
            'UPDATE tokens SET balance = balance + ? WHERE user_id = ? AND guild_id = ?',
            (amount, user_id, guild_id)
        )
        await self.conn.commit()

    async def get_tokens(self, user_id: int, guild_id: int):
        async with self.conn.execute(
            'SELECT balance FROM tokens WHERE user_id = ? AND guild_id = ?',
            (user_id, guild_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def _ensure_guild_config(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return None, None
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        if not alive_role:
            await ctx.send("Alive role not found. Check your config.")
            return None, None
        return guild_data, alive_role

    def _find_single_alive_in_channel(self, channel: discord.TextChannel, alive_role: discord.Role):
        alive = [m for m in channel.members if alive_role in m.roles and not m.bot]
        # Return (member_or_none, count) so we can error if ambiguous
        return (alive[0] if len(alive) == 1 else None, len(alive))

    async def _is_closed(self, channel_id: int) -> bool:
        async with self.conn.execute('SELECT closed FROM vote_status WHERE channel_id = ?', (channel_id,)) as c:
            row = await c.fetchone()
            return bool(row[0]) if row else False

    @commands.command()
    async def addtokens(self, ctx, target: str, quantity: int = 2):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have permission to use this command.")
        guild_data, alive_role = await self._ensure_guild_config(ctx)
        if not guild_data:
            return

        members: list[discord.Member] = []
        mention_text = ""

        if target == "everyone":
            members = [m for m in alive_role.members if not m.bot]
            mention_text = "everyone"
        else:
            # Try to resolve a single member (ID or mention)
            target_id = _digits(target)
            member = ctx.guild.get_member(int(target_id)) if target_id else None
            if not member:
                return await ctx.send("Member not found.")
            members = [member]
            mention_text = member.mention

        for m in members:
            await self.update_tokens(m.id, ctx.guild.id, quantity)

        if not members:
            return await ctx.send("No eligible members to add tokens to.")
        await ctx.send(f"Added {quantity} token(s) to {mention_text}.")

    @commands.command()
    async def removetokens(self, ctx, target: str, quantity: int = 2):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have permission to use this command.")
        guild_data, alive_role = await self._ensure_guild_config(ctx)
        if not guild_data:
            return

        # Resolve targets
        if target == "everyone":
            targets = [m for m in alive_role.members if not m.bot]
        else:
            target_id = _digits(target)
            member = ctx.guild.get_member(int(target_id)) if target_id else None
            if not member:
                return await ctx.send("Member not found.")
            targets = [member]

        if not targets:
            return await ctx.send("No eligible members to remove tokens from.")

        successes = []
        failures = []
        for m in targets:
            current_balance = await self.get_tokens(m.id, ctx.guild.id)
            if current_balance >= quantity:
                await self.update_tokens(m.id, ctx.guild.id, -quantity)
                successes.append(m.mention)
            else:
                failures.append(m.mention)

        # Send clear, accurate feedback
        if len(targets) == 1:
            if successes:
                return await ctx.send(f"Removed {quantity} token(s) from {successes[0]}.")
            else:
                return await ctx.send(f"{failures[0]} does not have enough tokens to remove.")
        else:
            parts = []
            if successes:
                parts.append(f"Removed {quantity} token(s) from: {', '.join(successes)}.")
            if failures:
                parts.append(f"Not enough tokens for: {', '.join(failures)}.")
            return await ctx.send("\n".join(parts))

    @commands.command()
    async def tokens(self, ctx, channel: discord.TextChannel = None):
        guild_data, alive_role = await self._ensure_guild_config(ctx)
        if not guild_data:
            return

        if channel is None:
            channel = ctx.channel

        balance_lines = []

        if ctx.author.guild_permissions.administrator:
            for m in channel.members:
                if alive_role in m.roles and not m.bot:
                    bal = await self.get_tokens(m.id, ctx.guild.id)
                    balance_lines.append(f"{m.mention}: {bal} token(s)")
            if not balance_lines:
                return await ctx.send("No eligible members found in that channel.")
            return await ctx.send("\n".join(balance_lines))

        # Non-admins: only in their own RoleChat, only their RC channel
        rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
        if not rc_category:
            return await ctx.send("RoleChat category not found. Ask an admin to configure it.")
        if ctx.channel not in rc_category.channels:
            return await ctx.send("You can only check your tokens balance in your RoleChat.")

        if channel is not ctx.channel:
            return await ctx.send("You can only check your tokens balance.")

        # Show balances for alive members in the RC (usually just one)
        for m in channel.members:
            if alive_role in m.roles and not m.bot:
                bal = await self.get_tokens(m.id, ctx.guild.id)
                balance_lines.append(f"{m.mention}: {bal} token(s)")

        if not balance_lines:
            return await ctx.send("No eligible members in this RoleChat.")
        return await ctx.send("\n".join(balance_lines))

    @commands.command()
    async def intervene(self, ctx, nomination_channel: discord.TextChannel):
        guild_data, alive_role = await self._ensure_guild_config(ctx)
        if not guild_data:
            return

        # Determine who is spending
        if ctx.author.guild_permissions.administrator:
            # Prefer author if they are alive; otherwise try to find the sole alive member in the channel
            if alive_role in ctx.author.roles:
                messager = ctx.author
            else:
                messager, count = self._find_single_alive_in_channel(ctx.channel, alive_role)
                if not messager:
                    return await ctx.send("No unique alive player found in this channel.")
        else:
            # Must be run in the player's RC, by that alive player
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            if not rc_category or ctx.channel not in rc_category.channels:
                return await ctx.send("You can only use this command in your RoleChat.")
            if alive_role not in ctx.author.roles:
                return await ctx.send("Only alive players can use this command.")
            messager = ctx.author

        current_balance = await self.get_tokens(messager.id, ctx.guild.id)
        if current_balance < 1:
            return await ctx.send("Not enough tokens to intervene.")

        await self.update_tokens(messager.id, ctx.guild.id, -1)
        await nomination_channel.set_permissions(messager, send_messages=True)
        await nomination_channel.send(f"{messager.mention} paid one token to intervene in this nomination.")

    @commands.command()
    async def accuse(self, ctx, accused: discord.Member, channel_accuser: discord.TextChannel = None):
        guild_data, alive_role = await self._ensure_guild_config(ctx)
        if not guild_data:
            return

        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        hidden_role = discord.utils.get(ctx.guild.roles, id=1264205063338066050)

        # Figure out who the accuser is
        accuser = None

        if ctx.author.guild_permissions.administrator:
            # If no channel provided, use current
            channel_accuser = channel_accuser or ctx.channel
            accuser, count = self._find_single_alive_in_channel(channel_accuser, alive_role)
            if not accuser:
                return await ctx.send("No unique alive player found in the accuser RoleChannel.")
        else:
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            if not rc_category or ctx.channel not in rc_category.channels:
                return await ctx.send("You can only accuse in your RoleChannel.")
            # If channel not provided, it must be their own RC
            channel_accuser = channel_accuser or ctx.channel
            if channel_accuser != ctx.channel:
                return await ctx.send("You can only accuse in your own RoleChannel.")
            if alive_role not in ctx.author.roles:
                return await ctx.send("Only alive players can accuse.")
            accuser = ctx.author

        if accuser == accused:
            return await ctx.send("You can't nominate yourself.")

        current_balance = await self.get_tokens(accuser.id, ctx.guild.id)
        if current_balance < 1:
            return await ctx.send("Not enough tokens to accuse.")

        category = discord.utils.get(ctx.guild.categories, name=guild_data["nominations_category_name"])
        if not category:
            return await ctx.send("Nominations aren't set up in this server.")

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
            accused: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            accuser: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if alt_role:
            overwrites[alt_role] = discord.PermissionOverwrite(read_messages=False)
        if hidden_role:
            overwrites[hidden_role] = discord.PermissionOverwrite(read_messages=False)

        channel = await ctx.guild.create_text_channel(f'👉│{accused.name}', overwrites=overwrites, category=category)
        await ctx.send(f'Nomination channel created: {channel.mention}')
        await channel.send(
            f"{discord.utils.get(ctx.guild.roles, name=guild_data['alive_role_name']).mention} {sponsor_role.mention if sponsor_role else ''}\n"
            f"{accuser.mention} nominated {accused.mention}\n"
            f"You can vote in your RoleChannels with the command\n"
            f".voten {channel.mention} yes/no\n"
            f"Yes means you're voting guilty\n"
            f"No means you're voting not guilty"
        )

        # Initialize vote status for this channel as open
        await self.conn.execute('INSERT OR REPLACE INTO vote_status (channel_id, closed) VALUES (?, 0)', (channel.id,))
        await self.conn.commit()

        await self.update_tokens(accuser.id, ctx.guild.id, -1)

    @commands.command()
    async def voten(self, ctx, nomination_channel: discord.TextChannel, vote: str):
        vote = vote.lower()
        if vote not in ("yes", "no"):
            return await ctx.send("Invalid vote. Use 'yes' or 'no'.")

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")

        rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
        if not rc_category or ctx.channel not in rc_category.channels:
            return await ctx.send("You can only vote in your RoleChannel.")

        # Enforce closed status
        if await self._is_closed(nomination_channel.id):
            return await ctx.send(f"Voting is closed for {nomination_channel.mention}.")

        # Upsert the vote
        async with self.conn.execute(
            'SELECT 1 FROM votes WHERE channel_id = ? AND voter_id = ?',
            (nomination_channel.id, ctx.author.id)
        ) as cursor:
            exists = await cursor.fetchone()

        if exists:
            await self.conn.execute(
                'UPDATE votes SET vote = ? WHERE channel_id = ? AND voter_id = ?',
                (vote, nomination_channel.id, ctx.author.id)
            )
            await self.conn.commit()
            return await ctx.send(f"Your vote has been updated to '{vote}' in {nomination_channel.mention}.")
        else:
            await self.conn.execute(
                'INSERT INTO votes (channel_id, voter_id, vote) VALUES (?, ?, ?)',
                (nomination_channel.id, ctx.author.id, vote)
            )
            await self.conn.commit()
            return await ctx.send(f"Your vote ({vote}) has been registered in {nomination_channel.mention}.")

    @commands.command()
    async def showvotesn(self, ctx, channel: discord.TextChannel = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have permission to use this command.")

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")

        category = discord.utils.get(ctx.guild.categories, name=guild_data["nominations_category_name"])
        if not category:
            return await ctx.send("Nominations aren't set up in this server.")

        if not channel:
            channel = ctx.channel

        async with self.conn.execute('SELECT vote, voter_id FROM votes WHERE channel_id = ?', (channel.id,)) as cursor:
            votes = await cursor.fetchall()

        if not votes:
            return await ctx.send(f'No votes recorded for {channel.mention}')

        yes_ids = [voter_id for vote, voter_id in votes if vote == 'yes']
        no_ids  = [voter_id for vote, voter_id in votes if vote == 'no']

        yes_text = "\n".join([f"<@{uid}>" for uid in yes_ids]) or "—"
        no_text  = "\n".join([f"<@{uid}>" for uid in no_ids]) or "—"

        embed = discord.Embed(title=f"{channel.mention} votes", color=0xff3fb9, timestamp=datetime.now())
        embed.add_field(name=f"Players who voted guilty (yes): {len(yes_ids)}", value=yes_text, inline=False)
        embed.add_field(name=f"Players who voted not guilty (no): {len(no_ids)}", value=no_text, inline=False)
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)

    @commands.command()
    async def stopvotes(self, ctx, channel: discord.TextChannel = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have permission to use this command.")

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")

        category = discord.utils.get(ctx.guild.categories, name=guild_data["nominations_category_name"])
        if not category:
            return await ctx.send("Nominations aren't set up in this server.")

        if not channel:
            channel = ctx.channel

        # Mark closed at the channel level
        await self.conn.execute('INSERT OR REPLACE INTO vote_status (channel_id, closed) VALUES (?, 1)', (channel.id,))
        await self.conn.commit()
        await ctx.send(f'Votes have been stopped for {channel.mention}')

    @commands.command()
    async def resumevotes(self, ctx, channel: discord.TextChannel = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have permission to use this command.")

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")

        category = discord.utils.get(ctx.guild.categories, name=guild_data["nominations_category_name"])
        if not category:
            return await ctx.send("Nominations aren't set up in this server.")

        if not channel:
            channel = ctx.channel

        await self.conn.execute('INSERT OR REPLACE INTO vote_status (channel_id, closed) VALUES (?, 0)', (channel.id,))
        await self.conn.commit()
        await ctx.send(f'Votes have been resumed for {channel.mention}')

    @commands.command()
    async def clearvotes(self, ctx, guild_id: int = None):
        if not (ctx.author.guild_permissions.administrator or ctx.author.id == 450772749829537793):
            return await ctx.send("You don't have permission to use this command.")

        guild = ctx.guild if guild_id is None else self.bot.get_guild(guild_id)
        if not guild:
            return await ctx.send("Guild not found.")

        guild_data = load_guild_data(guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")

        category = discord.utils.get(guild.categories, name=guild_data["nominations_category_name"])
        if not category:
            return await ctx.send("Nominations category not found in this server.")

        for channel in category.channels:
            await self.conn.execute('DELETE FROM votes WHERE channel_id = ?', (channel.id,))
            await self.conn.execute('DELETE FROM vote_status WHERE channel_id = ?', (channel.id,))
        await self.conn.commit()
        await ctx.send(f"All votes have been deleted for the nomination channels in {guild.name}.")