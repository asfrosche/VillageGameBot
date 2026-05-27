import discord
from discord.ext import commands
from collections import defaultdict
from cogs.data_utils import load_guild_data
from datetime import datetime


class Meetup(commands.Cog):
    """
    Tracks who met whom during DAY and NIGHT phases.

    A meeting occurs when:
    1) Phase starts and multiple alive players already share a house
    2) A player gains send permission in a house with other alive players
    """

    def __init__(self, bot):
        self.bot = bot

        # "day" | "night" | None
        self.current_phase = None

        # meetups[guild_id][player_id] = set(other_player_ids)
        self.day_meetups = defaultdict(lambda: defaultdict(set))
        self.night_meetups = defaultdict(lambda: defaultdict(set))

        # Session-based activation for guilds
        self.enabled_guilds = set()

    # ======================================================
    # UTILS
    # ======================================================

    def _matrix(self, guild_id: int):
        if self.current_phase == "night":
            return self.night_meetups[guild_id]
        return self.day_meetups[guild_id]

    def _clean_name(self, name: str):
        """Escapes markdown characters in names."""
        if name:
            return discord.utils.escape_markdown(name)
        return name

    def _add_safe_field(self, embed_list, title, items, separator=", ", is_mention=False):
        """
        Helper to add fields to an embed while respecting Discord's limits.
        If a field value exceeds 1024 chars, it splits into multiple fields.
        If an embed exceeds 25 fields or ~5500 chars, it creates a new embed.
        """
        if not items:
            return

        embed = embed_list[-1]
        current_value = ""
        is_first_chunk = True

        for item in items:
            # If adding this item + separator exceeds field limit (1024)
            if len(current_value) + len(item) + len(separator) > 1000:
                field_name = title if is_first_chunk else "\u200b"
                
                # Check if we need a new embed (25 fields or 6000 chars total)
                if len(embed.fields) >= 25 or len(embed) + len(current_value) + len(field_name) > 5500:
                    title_prefix = "🤝|" if "Meetups" in embed.title else "📊|"
                    new_embed = discord.Embed(
                        title=f"{title_prefix} {embed.title.split('|')[-1].strip()} [Cont.]",
                        color=0xFF3FB9,
                        timestamp=datetime.now()
                    )
                    new_embed.set_footer(text="Village Game")
                    embed_list.append(new_embed)
                    embed = new_embed
                
                embed.add_field(name=field_name, value=current_value.strip(separator), inline=False)
                current_value = item + separator
                is_first_chunk = False
            else:
                current_value += item + separator

        if current_value:
            field_name = title if is_first_chunk else "\u200b"
            if len(embed.fields) >= 25 or len(embed) + len(current_value) + len(field_name) > 5500:
                title_prefix = "🤝|" if "Meetups" in embed.title else "📊|"
                new_embed = discord.Embed(
                    title=f"{title_prefix} {embed.title.split('|')[-1].strip()} [Cont.]",
                    color=0xFF3FB9,
                    timestamp=datetime.now()
                )
                new_embed.set_footer(text="Village Game")
                embed_list.append(new_embed)
                embed = new_embed
                
            embed.add_field(name=field_name, value=current_value.strip(separator), inline=False)

    def _get_active_players_in_channel(self, channel: discord.TextChannel, guild_data):
        """
        Matches the logic in .who command to identify players.
        Identifies members with send_messages perms and either alive, alt, or dead roles.
        """
        guild = channel.guild
        alive_role = discord.utils.get(guild.roles, name=guild_data["alive_role_name"])
        alt_role = discord.utils.get(guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(guild.roles, name=guild_data["dead_role_name"])

        active_members = []
        for member in channel.members:
            if member.bot:
                continue
            
            perms = channel.permissions_for(member)
            if perms.send_messages:
                if (alive_role and alive_role in member.roles) or \
                   (alt_role and alt_role in member.roles) or \
                   (dead_role and dead_role in member.roles):
                    active_members.append(member)
        
        return active_members

    # ======================================================
    # AUTOMATION LISTENERS
    # ======================================================

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        """
        Automatically captures meetups when permissions change in house channels.
        """
        if not isinstance(after, discord.TextChannel):
            return

        if after.guild.id not in self.enabled_guilds:
            return

        if not self.current_phase:
            return

        try:
            guild_data = load_guild_data(after.guild.id)
            if not guild_data:
                return

            houses_category = discord.utils.get(after.guild.categories, name=guild_data["houses_category_name"])
            if not houses_category or after.category != houses_category:
                return

            active_members = self._get_active_players_in_channel(after, guild_data)
            
            if len(active_members) > 1:
                matrix = self._matrix(after.guild.id)
                for i in range(len(active_members)):
                    for j in range(i + 1, len(active_members)):
                        a = active_members[i]
                        b = active_members[j]
                        matrix[a.id].add(b.id)
                        matrix[b.id].add(a.id)

        except Exception:
            pass

    # ======================================================
    # PHASE HANDLING
    # ======================================================

    @commands.Cog.listener()
    async def on_phase_change(self, phase: str):
        try:
            self.current_phase = phase

            if phase == "day":
                self.day_meetups.clear()
            elif phase == "night":
                self.night_meetups.clear()
            else:
                return

            # Bootstrap for all enabled guilds
            for guild_id in list(self.enabled_guilds):
                guild = self.bot.get_guild(guild_id)
                if guild:
                    await self._bootstrap_existing_meetups(guild)

        except Exception:
            pass

    # ======================================================
    # BOOTSTRAP LOGIC
    # ======================================================

    async def _bootstrap_existing_meetups(self, guild: discord.Guild):
        guild_data = load_guild_data(guild.id)
        if not guild_data:
            return

        houses_category = discord.utils.get(
            guild.categories, name=guild_data["houses_category_name"]
        )

        if not houses_category:
            return

        matrix = self._matrix(guild.id)

        for channel in houses_category.text_channels:
            active_members = self._get_active_players_in_channel(channel, guild_data)

            if len(active_members) > 1:
                for i in range(len(active_members)):
                    for j in range(i + 1, len(active_members)):
                        a = active_members[i]
                        b = active_members[j]
                        matrix[a.id].add(b.id)
                        matrix[b.id].add(a.id)

    # ======================================================
    # CORE ENTRY API (Fallback/Legacy)
    # ======================================================

    async def record_house_entry(
        self,
        guild: discord.Guild,
        house_channel: discord.TextChannel,
        entering_member: discord.Member,
    ):
        try:
            if guild.id not in self.enabled_guilds:
                return

            if not self.current_phase:
                return

            guild_data = load_guild_data(guild.id)
            if not guild_data:
                return

            active_members = self._get_active_players_in_channel(house_channel, guild_data)
            if entering_member not in active_members:
                return

            matrix = self._matrix(guild.id)
            for other in active_members:
                if other.id == entering_member.id:
                    continue
                matrix[entering_member.id].add(other.id)
                matrix[other.id].add(entering_member.id)

        except Exception:
            pass

    # ======================================================
    # READ HELPERS
    # ======================================================

    def get_met_players(self, guild_id: int, player_id: int):
        if not self.current_phase or guild_id not in self.enabled_guilds:
            return set()
        return self._matrix(guild_id).get(player_id, set())

    # ======================================================
    # ADMIN COMMANDS
    # ======================================================

    @commands.command(name="setupmeetupmatrix")
    @commands.has_permissions(administrator=True)
    async def setup_meetup_matrix(self, ctx):
        """Toggles the Meetup Matrix tracking for this server with a confirmation."""
        is_enabled = ctx.guild.id in self.enabled_guilds
        action = "DISABLE" if is_enabled else "ENABLE"
        
        prompt = discord.Embed(
            title="⚠️ Meetup Matrix Setup",
            description=f"Are you sure you want to **{action}** the Meetup Matrix for this server?\n\n"
                        f"*Note: This setting is session-only and will reset if the bot restarts.*",
            color=0xFF3FB9
        )
        prompt.set_footer(text="Village Game")

        view = discord.ui.View(timeout=30)

        async def confirm_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                return await interaction.response.send_message("You cannot confirm this.", ephemeral=True)
            
            if ctx.guild.id in self.enabled_guilds:
                self.enabled_guilds.remove(ctx.guild.id)
                status = "DISABLED"
            else:
                self.enabled_guilds.add(ctx.guild.id)
                status = "ENABLED"
                if self.current_phase:
                    await self._bootstrap_existing_meetups(ctx.guild)
            
            done = discord.Embed(
                title="✅ Success",
                description=f"Meetup Matrix state: **{status}** for this server.",
                color=discord.Color.green()
            )
            done.set_footer(text="Village Game")
            await interaction.response.edit_message(embed=done, view=None)

        async def cancel_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                return await interaction.response.send_message("You cannot cancel this.", ephemeral=True)
            
            cancelled = discord.Embed(
                title="❌ Cancelled",
                description="Meetup Matrix setup cancelled.",
                color=discord.Color.red()
            )
            cancelled.set_footer(text="Village Game")
            await interaction.response.edit_message(embed=cancelled, view=None)

        btn_yes = discord.ui.Button(label="✔ Yes", style=discord.ButtonStyle.green)
        btn_yes.callback = confirm_callback
        btn_no = discord.ui.Button(label="❌ No", style=discord.ButtonStyle.red)
        btn_no.callback = cancel_callback
        
        view.add_item(btn_yes)
        view.add_item(btn_no)
        
        await ctx.send(embed=prompt, view=view)

    @commands.command(name="setphase")
    @commands.has_permissions(administrator=True)
    async def setphase(self, ctx, phase: str):
        if phase.lower() not in ["day", "night"]:
            await ctx.send("Use: day or night")
            return

        await self.on_phase_change(phase.lower())
        await ctx.send(f"Phase manually set to `{phase.lower()}`")

    @commands.command(name="forcemeet")
    @commands.has_permissions(administrator=True)
    async def forcemeet(self, ctx, member1: discord.Member, member2: discord.Member):
        if ctx.guild.id not in self.enabled_guilds:
            await ctx.send("Meetup Matrix is not enabled on this server.")
            return

        if not self.current_phase:
            await ctx.send("No active phase.")
            return

        matrix = self._matrix(ctx.guild.id)
        matrix[member1.id].add(member2.id)
        matrix[member2.id].add(member1.id)

        await ctx.send(f"Forced meetup recorded between {member1.mention} and {member2.mention}")

    @commands.command(name="allmeets")
    @commands.has_permissions(administrator=True)
    async def allmeets(self, ctx, member: discord.Member = None):
        if ctx.guild.id not in self.enabled_guilds:
            await ctx.send("Meetup Matrix is not enabled on this server.")
            return

        if not member:
            await ctx.send("Usage: `.allmeets @user`")
            return

        if not self.current_phase:
            await ctx.send("Phase has not started yet.")
            return

        met_ids = self.get_met_players(ctx.guild.id, member.id)

        if not met_ids:
            await ctx.send(f"**{member.display_name}** met no one during **{self.current_phase}**.")
            return

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])

        alive_list = []
        alt_list = []
        dead_list = []

        for uid in met_ids:
            m = ctx.guild.get_member(uid)
            if not m:
                continue
            
            clean_name = self._clean_name(m.display_name)
            entry = f"{m.mention} `[{clean_name}]`"
            
            if alive_role and alive_role in m.roles:
                alive_list.append(entry)
            elif alt_role and alt_role in m.roles:
                alt_list.append(entry)
            elif dead_role and dead_role in m.roles:
                dead_list.append(entry)

        embeds = []
        initial_embed = discord.Embed(
            title=f"🤝| {member.display_name} Meetups:",
            color=0xFF3FB9,
            timestamp=datetime.now()
        )
        initial_embed.set_footer(text="Village Game")
        embeds.append(initial_embed)

        if alive_list:
            self._add_safe_field(embeds, f"**{alive_role.name}:**", alive_list, separator="\n")
        if alt_list:
            self._add_safe_field(embeds, f"**{alt_role.name}:**", alt_list, separator="\n")
        if dead_list:
            self._add_safe_field(embeds, f"**{dead_role.name}:**", dead_list, separator="\n")

        for e in embeds:
            await ctx.send(embed=e)

    @commands.command(name="meetupmatrix")
    @commands.has_permissions(administrator=True)
    async def meetupmatrix(self, ctx):
        if ctx.guild.id not in self.enabled_guilds:
            await ctx.send("Meetup Matrix is not enabled on this server.")
            return

        if not self.current_phase:
            await ctx.send("Phase has not started yet.")
            return

        matrix = self._matrix(ctx.guild.id)
        if not matrix:
            await ctx.send(f"No meetups recorded during **{self.current_phase}**.")
            return

        embeds = []
        initial_embed = discord.Embed(
            title=f"📊| Meetup Matrix ({self.current_phase.upper()})",
            color=0xFF3FB9,
            timestamp=datetime.now()
        )
        initial_embed.set_footer(text="Village Game")
        embeds.append(initial_embed)

        sorted_player_ids = sorted(matrix.keys())
        for uid in sorted_player_ids:
            member = ctx.guild.get_member(uid)
            met_ids = matrix[uid]
            if not member or not met_ids:
                continue

            met_names = sorted([self._clean_name(ctx.guild.get_member(mid).display_name) 
                               for mid in met_ids if ctx.guild.get_member(mid)])
            
            if not met_names:
                continue

            title = f"👤| {self._clean_name(member.display_name)}"
            self._add_safe_field(embeds, title, met_names, separator=", ")

        for e in embeds:
            await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Meetup(bot))
