import discord
from discord.ext import commands
from datetime import datetime, timezone
from discord import Embed

from cogs.data_utils import load_guild_data, save_guild_data


class MessageTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_tracked_channel(self, guild: discord.Guild):
        """Resolve the channel to track for this guild (day discussion channel by name from guild data)."""
        data = load_guild_data(guild.id)
        if not data or not data.get("message_tracking_enabled"):
            return None
        name = data.get("daydiscussion_channel_name")
        if not name:
            return None
        return discord.utils.get(guild.text_channels, name=name)

    @commands.command()
    async def statss(self, ctx):
        """Show message counts for the day discussion channel (when tracking is enabled) grouped by role priority."""
        data = load_guild_data(ctx.guild.id) or {}
        counts = data.get("tracked_message_counts") or {}
        if not counts:
            await ctx.send("No stats available for this server. Enable tracking with `.setmessagetracking true` (day discussion channel must be set in setup).")
            return

        # 1. Define the role priority order with corresponding emojis
        # Check roles in this exact order: first matching role determines the user's section.
        role_info = [
            {"name": "Alive", "emoji": "🟢"},
            {"name": "Sponsor", "emoji": "💰"},
            {"name": "Dead", "emoji": "💀"},
            {"name": "Overseer", "emoji": "👑"},
            {"name": "Spectator", "emoji": "👁️"}
        ]
        role_priority = [info["name"] for info in role_info]
        
        # 2. Grouping behavior: Initialize dictionary to map each category to lists of members and their counts
        grouped_stats = {role: [] for role in role_priority}
        
        # 3. Process each tracked user
        for user_id_str, count in counts.items():
            try:
                user_id = int(user_id_str)
            except ValueError:
                continue
            
            # Fetch Discord Member object (try cache first, fallback to API)
            member = ctx.guild.get_member(user_id)
            if not member:
                try:
                    member = await ctx.guild.fetch_member(user_id)
                except (discord.NotFound, discord.HTTPException):
                    # Ignore users that no longer exist or cannot be fetched
                    continue

            # Inspect roles and assign to the first matching category using priority order
            assigned_role = None
            member_role_names = {role.name for role in member.roles}
            for role_name in role_priority:
                if role_name in member_role_names:
                    assigned_role = role_name
                    break  # Stop checking after first match to ensure each user appears ONLY ONCE
            
            # If the user has none of the tracked roles, ignore them
            if assigned_role:
                grouped_stats[assigned_role].append((member.display_name, int(count)))

        # 4. Sorting inside each category and formatting output sections
        list_str = []
        for info in role_info:
            role_name = info["name"]
            emoji = info["emoji"]
            users_list = grouped_stats[role_name]
            if not users_list:
                continue
            
            # Sort users inside each category by: highest message count first
            users_list.sort(key=lambda x: x[1], reverse=True)
            
            # Calculate section totals (subtle clean stats)
            total_members = len(users_list)
            total_msgs = sum(count for _, count in users_list)
            
            member_suffix = "member" if total_members == 1 else "members"
            msg_suffix = "msg" if total_msgs == 1 else "msgs"
            
            # Add category section header using Discord native small header markdown (###) for size and weight distinction
            list_str.append(f"### {emoji} {role_name} ({total_members} {member_suffix} • {total_msgs} {msg_suffix})")
            
            # Add each user under that section formatted cleanly: Name — Count
            for name, count in users_list:
                list_str.append(f"{name} — {count}")
                
            # Add empty line as readable spacing between sections
            list_str.append("")

        # Remove the trailing empty line if it exists
        if list_str and list_str[-1] == "":
            list_str.pop()

        if not list_str:
            await ctx.send("No tracked users currently have any of the required roles.")
            return

        embed = discord.Embed(title="📊 Message Stats", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        
        description_text = "\n".join(list_str)
        if len(description_text) > 2000:
            await ctx.send("Message Stats:\n" + description_text)
        else:
            embed.description = description_text
            await ctx.send(embed=embed)

    @commands.command(name="setmessagetracking")
    @commands.has_permissions(administrator=True)
    async def setmessagetracking(self, ctx, value: bool):
        """Enable or disable message tracking for this server. Tracks the day discussion channel (see setup)."""
        data = load_guild_data(ctx.guild.id) or {}
        data["message_tracking_enabled"] = bool(value)
        save_guild_data(ctx.guild.id, data)
        await ctx.send(f"Message tracking **{'enabled' if value else 'disabled'}** for this server (day discussion channel).")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def start_tracking(self, ctx):
        """Start message tracking (same as setmessagetracking true)."""
        await self.setmessagetracking(ctx, True)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def stop_tracking(self, ctx):
        """Pause message tracking (same as setmessagetracking false)."""
        await self.setmessagetracking(ctx, False)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reset_tracking(self, ctx):
        """Reset message counts for this server."""
        data = load_guild_data(ctx.guild.id) or {}
        data["tracked_message_counts"] = {}
        save_guild_data(ctx.guild.id, data)
        await ctx.send("Message tracking stats have been reset for this server.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        channel = self._get_tracked_channel(message.guild)
        if not channel or message.channel.id != channel.id:
            return
        data = load_guild_data(message.guild.id) or {}
        counts = data.get("tracked_message_counts") or {}
        uid_str = str(message.author.id)
        counts[uid_str] = counts.get(uid_str, 0) + 1
        data["tracked_message_counts"] = counts
        save_guild_data(message.guild.id, data)