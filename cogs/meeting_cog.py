import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import List, Optional, Union
import os
from datetime import datetime, timedelta
from cogs.data_utils import load_guild_data, save_guild_data
from utils.bot_db import (
    add_blocked_user,
    clear_meeting_cooldown,
    get_blocked_users,
    get_meeting_cooldown_until,
    list_meeting_cooldowns,
    migrate_legacy_json,
    remove_blocked_user,
    set_meeting_cooldown,
)

class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Base path (root folder)
        self.base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Database folder path
        self.db_path = os.path.join(self.base_path, 'db')
        
        # Create db folder if it doesn't exist
        os.makedirs(self.db_path, exist_ok=True)
        
        # Ensure legacy JSON settings are migrated into SQLite (one-time)
        migrate_legacy_json()
        # Per-guild state: guild_id -> ...
        self.pending_meetings = {}  # {guild_id: {message_id: meeting_data}}
        self.user_pending_meetings = {}  # {guild_id: {user_id: message_id}}
        self.active_meetings = {}  # {channel_id: {message_id, start_time, participants}} (channel_id is global)
        
        self.ARCHIVE_BASE_NAME = "ARCHIVE"  # Base name for archive categories
        self.MAX_CHANNELS_PER_ARCHIVE = 50
        
        # Cooldown duration in minutes
        self.MEETING_COOLDOWN_MINUTES = 60

    def _meeting_config(self, guild_id: int):
        """Get meeting config for a guild from guild_data. Returns dict with meeting_enabled, meeting_channel_id, target_guild_id, meeting_category_id (any can be None)."""
        data = load_guild_data(guild_id) or {}
        return {
            "meeting_enabled": bool(data.get("meeting_enabled", False)),
            "meeting_channel_id": data.get("meeting_channel_id"),
            "target_guild_id": data.get("target_guild_id"),
            "meeting_category_id": data.get("meeting_category_id"),
        }

    def _pending_for_guild(self, guild_id: int):
        if guild_id not in self.pending_meetings:
            self.pending_meetings[guild_id] = {}
        return self.pending_meetings[guild_id]

    def _user_pending_for_guild(self, guild_id: int):
        if guild_id not in self.user_pending_meetings:
            self.user_pending_meetings[guild_id] = {}
        return self.user_pending_meetings[guild_id]
    
    def is_user_blocked(self, guild_id: int, user_id: int) -> bool:
        """Check if a user is blocked"""
        return user_id in set(get_blocked_users(guild_id))
    
    def add_meeting_cooldown(self, guild_id: int, user_id: int):
        """Add a user to meeting cooldown"""
        cooldown_until = datetime.utcnow() + timedelta(minutes=self.MEETING_COOLDOWN_MINUTES)
        set_meeting_cooldown(guild_id, user_id, cooldown_until)
    
    def get_user_cooldown(self, guild_id: int, user_id: int) -> Optional[datetime]:
        """Get user's cooldown end time, returns None if no cooldown"""
        cooldown_until = get_meeting_cooldown_until(guild_id, user_id)
        if not cooldown_until:
            return None
        
        # Check if cooldown has expired
        if datetime.utcnow() >= cooldown_until:
            # Remove expired cooldown
            clear_meeting_cooldown(guild_id, user_id)
            return None
        
        return cooldown_until
    
    def get_cooldown_time_remaining(self, guild_id: int, user_id: int) -> Optional[str]:
        """Get formatted time remaining on cooldown"""
        cooldown_until = self.get_user_cooldown(guild_id, user_id)
        if not cooldown_until:
            return None
        
        time_remaining = cooldown_until - datetime.utcnow()
        minutes = int(time_remaining.total_seconds() / 60)
        seconds = int(time_remaining.total_seconds() % 60)
        
        if minutes > 0:
            return f"{minutes} minutes and {seconds} seconds"
        else:
            return f"{seconds} seconds"

    async def notify_meetup_system(self, guild: discord.Guild, channel: discord.TextChannel, members: List[discord.Member]):
        """
        Notify the Meetup cog that these members have entered this house.
        """
        meetup_cog = self.bot.get_cog("Meetup")

        if not meetup_cog:
            print("[MEETING] Meetup cog not loaded.")
            return

        print(f"[MEETING] Notifying Meetup for channel {channel.name}")

        for member in members:
            try:
                await meetup_cog.record_house_entry(
                    guild=guild,
                    house_channel=channel,
                    entering_member=member
                )
            except Exception as e:
                print(f"[MEETING] Error notifying meetup: {e}")

    
    async def find_or_create_archive_category(self, guild: discord.Guild) -> discord.CategoryChannel:
        """Find an archive category with space or create a new one"""
        
        # Find all archive categories (Archive 1, Archive 2, etc.)
        archive_categories = []
        for category in guild.categories:
            if category.name.startswith(self.ARCHIVE_BASE_NAME):
                archive_categories.append(category)
        
        # Sort by number in name
        def get_archive_number(cat):
            try:
                # Extract number from "Archive X" or just "Archive" (treat as 1)
                parts = cat.name.split()
                if len(parts) == 1:
                    return 1
                return int(parts[1])
            except:
                return 1
        
        archive_categories.sort(key=get_archive_number)
        
        # Check existing categories for space
        for category in archive_categories:
            if len(category.channels) < self.MAX_CHANNELS_PER_ARCHIVE:
                return category
        
        # All categories are full, create a new one
        next_number = len(archive_categories) + 1
        new_category_name = f"{self.ARCHIVE_BASE_NAME} {next_number}"
        
        try:
            new_category = await guild.create_category(new_category_name)
            print(f"Created new archive category: {new_category_name}")
            return new_category
        except Exception as e:
            print(f"Error creating archive category: {e}")
            # Fallback to last category if creation fails
            if archive_categories:
                return archive_categories[-1]
            raise
    
    @commands.command(name='meeting')
    async def meeting(self, ctx, *members: discord.Member):
        """Request a meeting with other players (max 5)"""
        
        # Check if user is blocked
        if self.is_user_blocked(ctx.guild.id, ctx.author.id):
            await ctx.send("❌ You have been blocked from using this command.", delete_after=10)
            await ctx.message.delete()
            return
        
        # Check if user is on cooldown
        cooldown_time = self.get_cooldown_time_remaining(ctx.guild.id, ctx.author.id)
        if cooldown_time:
            await ctx.send(f"❌ You are on cooldown. You can request a meeting again in {cooldown_time}.", delete_after=15)
            await ctx.message.delete()
            return
        
        cfg = self._meeting_config(ctx.guild.id)
        if not cfg["meeting_enabled"] or not cfg["meeting_channel_id"]:
            await ctx.send("❌ Meeting system is not enabled or not configured for this server.", delete_after=10)
            return
        if ctx.channel.id != cfg["meeting_channel_id"]:
            await ctx.send("❌ This command can only be used in the meeting channel.", delete_after=10)
            return
        
        # Load guild data
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("❌ Guild configuration not found.", delete_after=10)
            return
        
        # Verify alive role
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        if not alive_role or alive_role not in ctx.author.roles:
            await ctx.send("❌ You don't have the required role to use this command.", delete_after=10)
            return
        
        # Verify number of members (1-5)
        if len(members) < 1 or len(members) > 5:
            await ctx.send("❌ You must mention between 1 and 5 players.", delete_after=10)
            return
        
        # Verify members have alive role and check cooldowns
        for member in members:
            if alive_role not in member.roles:
                await ctx.send(f"❌ {member.mention} doesn't have the alive role.", delete_after=10)
                return
            
            # Check if member is on cooldown
            member_cooldown = self.get_cooldown_time_remaining(ctx.guild.id, member.id)
            if member_cooldown:
                await ctx.send(f"❌ {member.mention} is on meeting cooldown for {member_cooldown}.", delete_after=15)
                return
        
        user_pending = self._user_pending_for_guild(ctx.guild.id)
        if ctx.author.id in user_pending:
            old_message_id = user_pending[ctx.author.id]
            await self.cancel_meeting(ctx.guild.id, old_message_id, f"Cancelled by {ctx.author.mention} to create a new meeting request")
        
        # Delete command message
        await ctx.message.delete()
        
        # Create embed
        members_list = "\n".join([f"• {member.mention}" for member in members])
        embed = discord.Embed(
            title="📋 Meeting Request",
            description=f"**{ctx.author.mention}** has requested a meeting with:",
            color=0xff3fb9,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Participants", value=members_list, inline=False)
        embed.add_field(
            name="Status",
            value="⏳ Waiting for confirmation from all participants...",
            inline=False
        )
        embed.set_footer(text="React with 👍 to accept or 👎 to decline")
        
        # Send embed
        message = await ctx.send(embed=embed)
        
        # Add reactions
        await message.add_reaction("👍")
        await message.add_reaction("👎")
        
        all_participants = [ctx.author] + list(members)
        self._pending_for_guild(ctx.guild.id)[message.id] = {
            'organizer': ctx.author,
            'participants': all_participants,
            'members': list(members),
            'votes': {},
            'guild_id': ctx.guild.id,
            'channel_id': ctx.channel.id
        }
        self._user_pending_for_guild(ctx.guild.id)[ctx.author.id] = message.id
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle reactions to meeting embeds"""
        if payload.user_id == self.bot.user.id:
            return

        meeting_data = None
        origin_guild_id = None
        for gid, pending in self.pending_meetings.items():
            if payload.message_id in pending:
                meeting_data = pending[payload.message_id]
                origin_guild_id = gid
                break
        if not meeting_data or origin_guild_id is None:
            return

        user = self.bot.get_user(payload.user_id)
        if user not in meeting_data['participants']:
            return

        if str(payload.emoji) == "👍":
            meeting_data['votes'][payload.user_id] = True
        elif str(payload.emoji) == "👎":
            await self.cancel_meeting(origin_guild_id, payload.message_id, f"{user.mention} declined the meeting")
            return
        else:
            return

        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        total_participants = len(meeting_data['participants'])
        votes_count = len(meeting_data['votes'])
        embed = message.embeds[0]
        embed.set_field_at(
            1,
            name="Status",
            value=f"✅ {votes_count}/{total_participants} participants have accepted",
            inline=False
        )
        await message.edit(embed=embed)
        if votes_count == total_participants:
            await self.create_meeting_channel(origin_guild_id, payload.message_id, channel)
    
    async def create_meeting_channel(self, origin_guild_id: int, message_id: int, origin_channel):
        """Create the meeting channel in the target server (config from origin guild)."""
        pending = self._pending_for_guild(origin_guild_id)
        if message_id not in pending:
            return
        meeting_data = pending[message_id]
        cfg = self._meeting_config(origin_guild_id)
        target_guild_id = cfg.get("target_guild_id")
        meeting_category_id = cfg.get("meeting_category_id")
        if not target_guild_id or not meeting_category_id:
            await origin_channel.send("❌ Meeting target server or category not configured.")
            return

        try:
            message = await origin_channel.fetch_message(message_id)
            embed = message.embeds[0]
            embed.color = discord.Color.green()
            embed.set_field_at(
                1,
                name="Status",
                value="✅ Meeting approved! Creating channel...",
                inline=False
            )
            await message.edit(embed=embed)

            target_guild = self.bot.get_guild(int(target_guild_id))
            if not target_guild:
                await origin_channel.send("❌ Error: target server not found.")
                return
            category = target_guild.get_channel(int(meeting_category_id))
            if not category:
                await origin_channel.send("❌ Error: meeting category not found.")
                return
            
            # Create channel name from ALL participants (organizer + members)
            all_names = [p.display_name.lower().replace(" ", "-") for p in meeting_data['participants']]
            channel_name = "-".join(all_names)[:100]  # Limit length
            
            # Collect people to add (participants only, no sponsors yet)
            people_to_add = set(meeting_data['participants'])
            
            # Check existing meetings and close if necessary
            for participant in meeting_data['participants']:
                target_member = target_guild.get_member(participant.id)
                if target_member:
                    for channel in category.text_channels:
                        try:
                            perms = channel.permissions_for(target_member)
                            if perms.send_messages:
                                # Close old meeting (with reason)
                                await self.close_meeting_channel(channel, closed_by=participant)
                                break
                        except:
                            continue
            
            # Get origin guild data
            origin_guild = self.bot.get_guild(meeting_data['guild_id'])
            guild_data = load_guild_data(origin_guild.id)
            
            # Find RC channels of participants and add sponsors
            rc_category = discord.utils.get(origin_guild.categories, name=guild_data["rc_category_name"])
            sponsor_role = discord.utils.get(origin_guild.roles, name=guild_data["sponsor_role_name"])
            
            if rc_category and sponsor_role:
                for rc_channel in rc_category.text_channels:
                    # Check if any participant has access to this RC channel
                    has_participant = False
                    for participant in meeting_data['participants']:
                        perms = rc_channel.permissions_for(participant)
                        if perms.read_messages:
                            has_participant = True
                            break
                    
                    # If a participant is in this RC channel, add all sponsors from it
                    if has_participant:
                        for member in rc_channel.members:
                            if sponsor_role in member.roles:
                                people_to_add.add(member)
            
            # Create meeting channel with specific permissions
            # Everyone cannot read messages
            overwrites = {
                target_guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                )
            }
            
            # Add permissions only for collected people (participants + sponsors)
            for person in people_to_add:
                try:
                    # Verify person is in target server
                    target_member = target_guild.get_member(person.id)
                    if target_member:
                        overwrites[target_member] = discord.PermissionOverwrite(
                            read_messages=True,
                            send_messages=True
                        )
                except:
                    continue
            
            # Create channel
            new_channel = await target_guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )
            
            # ADD COOLDOWNS TO ALL PARTICIPANTS
            for participant in meeting_data['participants']:
                self.add_meeting_cooldown(origin_guild.id, participant.id)
            
            # Welcome message - only mention participants, not sponsors
            participants_mentions = " ".join([p.mention for p in meeting_data['participants'] if target_guild.get_member(p.id)])
            welcome_embed = discord.Embed(
                title="🎯 Active Meeting",
                description=f"Welcome to the meeting organized by **{meeting_data['organizer'].display_name}**",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            welcome_embed.add_field(
                name="Participants",
                value=participants_mentions,
                inline=False
            )
            welcome_embed.add_field(
                name="How to close",
                value="Use the `.endmeeting` command when you're done.",
                inline=False
            )
            welcome_embed.add_field(
                name="⏱️ Cooldown",
                value=f"All participants are on cooldown for {self.MEETING_COOLDOWN_MINUTES} minutes.",
                inline=False
            )
            welcome_embed.set_footer(text=f"Meeting ID: {new_channel.id}")
            
            await new_channel.send(embed=welcome_embed)
            # 🔥 Notify Meetup system
            participants_in_target = [
                target_guild.get_member(p.id)
                for p in meeting_data['participants']
                if target_guild.get_member(p.id)
            ]

            await self.notify_meetup_system(target_guild, new_channel, participants_in_target)


            
            start_time = datetime.utcnow()
            self.active_meetings[new_channel.id] = {
                'message_id': message.id,
                'start_time': start_time,
                'participants': meeting_data['participants'],
                'origin_channel_id': meeting_data['channel_id'],
                'origin_guild_id': origin_guild_id,
            }
            
            # Update original embed with start time
            start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S UTC")
            embed.set_field_at(
                1,
                name="Status",
                value=f"✅ Meeting active in {new_channel.mention}\n⏰ Started: {start_time_str}\n⏱️ Participants on {self.MEETING_COOLDOWN_MINUTES}min cooldown",
                inline=False
            )
            await message.edit(embed=embed)
            
            organizer_id = meeting_data['organizer'].id
            user_pending = self._user_pending_for_guild(origin_guild_id)
            if organizer_id in user_pending:
                del user_pending[organizer_id]
            del pending[message_id]
            
        except Exception as e:
            await origin_channel.send(f"❌ Error creating meeting: {str(e)}")
            print(f"Error create_meeting_channel: {e}")
    
    async def close_meeting_channel(self, channel: discord.TextChannel, closed_by: discord.Member = None):
        """Close a meeting channel"""
        
        try:
            # Get meeting data before closing
            meeting_data = self.active_meetings.get(channel.id)
            
            # Get all members who currently have send_messages permission
            members_with_access = []
            for member, overwrite in channel.overwrites.items():
                if isinstance(member, discord.Member):
                    if overwrite.send_messages:
                        members_with_access.append(member)
            
            # Create new overwrites
            # Everyone keeps same permissions (read_messages=False)
            overwrites = {
                channel.guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                )
            }
            
            # For all members who had send access, set read_messages=True, send_messages=False
            for member in members_with_access:
                overwrites[member] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False
                )
            
            # Apply new overwrites
            await channel.edit(overwrites=overwrites)
            
            # Move to appropriate archive category (find or create)
            archive_category = await self.find_or_create_archive_category(channel.guild)
            if archive_category:
                await channel.edit(category=archive_category)
            
            # Closing message
            close_embed = discord.Embed(
                title="🔒 Meeting Closed",
                description="This meeting has been closed and archived.",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            await channel.send(embed=close_embed)
            
            # Update original embed if meeting data exists
            if meeting_data:
                try:
                    origin_channel = self.bot.get_channel(meeting_data['origin_channel_id'])
                    if origin_channel:
                        original_message = await origin_channel.fetch_message(meeting_data['message_id'])
                        
                        # Calculate duration and format times
                        end_time = datetime.utcnow()
                        duration = end_time - meeting_data['start_time']
                        hours, remainder = divmod(int(duration.total_seconds()), 3600)
                        minutes, seconds = divmod(remainder, 60)
                        
                        if hours > 0:
                            duration_str = f"{hours}h {minutes}m"
                        else:
                            duration_str = f"{minutes}m {seconds}s"
                        
                        start_time_str = meeting_data['start_time'].strftime("%d-%m %H:%M:%S UTC")
                        end_time_str = end_time.strftime("%d-%m %H:%M:%S UTC")
                        
                        # Update embed
                        embed = original_message.embeds[0]
                        embed.color = discord.Color.greyple()
                        
                        # Build status message
                        status_msg = f"🔒 Meeting ended"
                        if closed_by:
                            status_msg += f" by {closed_by.mention}"
                        status_msg += f"\n⏰ Started: {start_time_str}\n⏱️ Duration: {duration_str}\n🏁 Ended: {end_time_str}"
                        
                        embed.set_field_at(
                            1,
                            name="Status",
                            value=status_msg,
                            inline=False
                        )
                        await original_message.edit(embed=embed)
                except Exception as e:
                    print(f"Error updating original embed: {e}")
                
                # Remove from active meetings
                del self.active_meetings[channel.id]
            
        except Exception as e:
            print(f"Error close_meeting_channel: {e}")
    
    async def cancel_meeting(self, guild_id: int, message_id: int, reason: str):
        """Cancel a pending meeting."""
        pending = self._pending_for_guild(guild_id)
        if message_id not in pending:
            return
        meeting_data = pending[message_id]
        try:
            channel = self.bot.get_channel(meeting_data['channel_id'])
            message = await channel.fetch_message(message_id)
            embed = message.embeds[0]
            embed.color = discord.Color.red()
            embed.set_field_at(
                1,
                name="Status",
                value=f"❌ Meeting cancelled: {reason}",
                inline=False
            )
            await message.edit(embed=embed)
            organizer_id = meeting_data['organizer'].id
            user_pending = self._user_pending_for_guild(guild_id)
            if organizer_id in user_pending:
                del user_pending[organizer_id]
            del pending[message_id]
        except Exception as e:
            print(f"Error cancel_meeting: {e}")
    
    @commands.command(name='endmeeting')
    async def endmeeting(self, ctx):
        """End your active meeting"""
        if self.is_user_blocked(ctx.guild.id, ctx.author.id):
            await ctx.send("❌ You have been blocked from using this command.", delete_after=10)
            return
        try:
            target_guild = ctx.guild
            cfg = None
            for guild in self.bot.guilds:
                c = self._meeting_config(guild.id)
                if c.get("target_guild_id") and int(c["target_guild_id"]) == ctx.guild.id and c.get("meeting_category_id"):
                    cfg = c
                    break
            if not cfg:
                await ctx.send("❌ Meeting system is not configured for this server.")
                return
            category = target_guild.get_channel(int(cfg["meeting_category_id"]))
            if not category:
                await ctx.send("❌ Meeting category not found.")
                return
            
            # Search for user's channel
            user_channel = None
            target_member = target_guild.get_member(ctx.author.id)
            
            if not target_member:
                await ctx.send("❌ You are not present in the meeting server.")
                return
            
            for channel in category.text_channels:
                try:
                    perms = channel.permissions_for(target_member)
                    if perms.send_messages:
                        user_channel = channel
                        break
                except:
                    continue
            
            if not user_channel:
                await ctx.send("❌ You don't have any active meetings.")
                return
            
            # Close channel with user info
            await self.close_meeting_channel(user_channel, closed_by=ctx.author)
            
        except Exception as e:
            await ctx.send(f"❌ Error closing meeting: {str(e)}")
            print(f"Error endmeeting: {e}")
    
    # ---------- Setup commands (admin) ----------
    @commands.command(name='meetingenable')
    @commands.has_permissions(administrator=True)
    async def meetingenable(self, ctx, value: bool):
        """Enable or disable the meeting system for this server. Requires meeting channel, target guild and category to be set first."""
        data = load_guild_data(ctx.guild.id) or {}
        if value and (not data.get("meeting_channel_id") or not data.get("target_guild_id") or not data.get("meeting_category_id")):
            await ctx.send("❌ Set meeting channel, target guild and meeting category first (`.setmeetingchannel`, `.setmeetingtargetguild`, `.setmeetingcategory`).")
            return
        data["meeting_enabled"] = bool(value)
        save_guild_data(ctx.guild.id, data)
        await ctx.send(f"Meeting system **{'enabled' if value else 'disabled'}** for this server.")

    @commands.command(name='setmeetingchannel')
    @commands.has_permissions(administrator=True)
    async def setmeetingchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where users run `.meeting` to request meetings. Should be a channel only alive players can use."""
        data = load_guild_data(ctx.guild.id) or {}
        data["meeting_channel_id"] = channel.id
        save_guild_data(ctx.guild.id, data)
        await ctx.send(f"Meeting request channel set to {channel.mention}. Use `.meetingenable true` when ready.")

    @commands.command(name='setmeetingtargetguild')
    @commands.has_permissions(administrator=True)
    async def setmeetingtargetguild(self, ctx, guild_id: int = None):
        """Set the server where meeting private channels are created. Use the server's ID (right-click server → Copy ID). If omitted, uses this server."""
        gid = guild_id or ctx.guild.id
        guild = self.bot.get_guild(gid)
        if not guild:
            await ctx.send("❌ Bot is not in that server. Use the server ID where meeting channels should be created (same server or another the bot is in).")
            return
        data = load_guild_data(ctx.guild.id) or {}
        data["target_guild_id"] = gid
        save_guild_data(ctx.guild.id, data)
        await ctx.send(f"Target guild set to **{guild.name}** (ID: {gid}). Use `.setmeetingcategory` to set the category there.")

    @commands.command(name='setmeetingcategory')
    @commands.has_permissions(administrator=True)
    async def setmeetingcategory(self, ctx, category_or_id: Union[discord.CategoryChannel, int]):
        """Set the category (in the target server) where new meeting channels are created. Use a category mention, or the category ID from the target server."""
        data = load_guild_data(ctx.guild.id) or {}
        target_gid = data.get("target_guild_id") or ctx.guild.id
        target_guild = self.bot.get_guild(int(target_gid))
        if not target_guild:
            await ctx.send("❌ Target server not found. Set target guild first.")
            return
        if isinstance(category_or_id, int):
            category = target_guild.get_channel(category_or_id)
        else:
            category = category_or_id
        if not category or not isinstance(category, discord.CategoryChannel):
            await ctx.send("❌ Category not found or not in the target server.")
            return
        if category.guild.id != target_gid:
            await ctx.send(f"❌ That category is not in the target server (**{target_guild.name}**). Use a category from that server (or its ID).")
            return
        data["meeting_category_id"] = category.id
        save_guild_data(ctx.guild.id, data)
        await ctx.send(f"Meeting category set to **{category.name}**. Use `.meetingenable true` when all is set.")

    @commands.command(name='meetingconfig')
    @commands.has_permissions(administrator=True)
    async def meetingconfig(self, ctx):
        """Show current meeting configuration for this server."""
        cfg = self._meeting_config(ctx.guild.id)
        channel = self.bot.get_channel(cfg["meeting_channel_id"]) if cfg.get("meeting_channel_id") else None
        target_guild = self.bot.get_guild(int(cfg["target_guild_id"])) if cfg.get("target_guild_id") else None
        category = target_guild.get_channel(cfg["meeting_category_id"]) if target_guild and cfg.get("meeting_category_id") else None
        embed = discord.Embed(title="Meeting configuration", color=0xff3fb9, timestamp=datetime.utcnow())
        embed.add_field(name="Enabled", value="Yes" if cfg["meeting_enabled"] else "No", inline=True)
        embed.add_field(name="Meeting channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Target server", value=target_guild.name if target_guild else "Not set", inline=True)
        embed.add_field(name="Meeting category", value=category.name if category else "Not set", inline=True)
        await ctx.send(embed=embed)

    # ---------- Admin moderation ----------
    @commands.command(name='blockmeeting')
    @commands.has_permissions(administrator=True)
    async def blockmeeting(self, ctx, member: discord.Member):
        """Block a user from using meeting commands"""

        blocked = set(get_blocked_users(ctx.guild.id))
        if member.id in blocked:
            await ctx.send(f"⚠️ {member.mention} is already blocked.")
            return

        add_blocked_user(ctx.guild.id, member.id)
        
        embed = discord.Embed(
            title="🚫 User Blocked",
            description=f"{member.mention} has been blocked from using meeting commands.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Admin: {ctx.author}")
        await ctx.send(embed=embed)
    
    @commands.command(name='unblockmeeting')
    @commands.has_permissions(administrator=True)
    async def unblockmeeting(self, ctx, member: discord.Member):
        """Unblock a user from using meeting commands"""

        blocked = set(get_blocked_users(ctx.guild.id))
        if member.id not in blocked:
            await ctx.send(f"⚠️ {member.mention} is not blocked.")
            return

        remove_blocked_user(ctx.guild.id, member.id)
        
        embed = discord.Embed(
            title="✅ User Unblocked",
            description=f"{member.mention} can now use meeting commands.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Admin: {ctx.author}")
        await ctx.send(embed=embed)
    
    @commands.command(name='removecooldown')
    @commands.has_permissions(administrator=True)
    async def removecooldown(self, ctx, member: discord.Member):
        """Remove meeting cooldown from a user (admin only)"""

        if get_meeting_cooldown_until(ctx.guild.id, member.id):
            clear_meeting_cooldown(ctx.guild.id, member.id)
            
            embed = discord.Embed(
                title="✅ Cooldown Removed",
                description=f"Meeting cooldown removed for {member.mention}.",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Admin: {ctx.author}")
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"⚠️ {member.mention} doesn't have an active cooldown.")
    
    @commands.command(name='checkcooldown')
    async def checkcooldown(self, ctx, member: discord.Member = None):
        """Check meeting cooldown for yourself or another user"""
        
        target = member if member else ctx.author
        
        cooldown_time = self.get_cooldown_time_remaining(ctx.guild.id, target.id)
        
        if cooldown_time:
            embed = discord.Embed(
                title="⏱️ Meeting Cooldown",
                description=f"{target.mention} is on cooldown for **{cooldown_time}**.",
                color=0xff3fb9,
                timestamp=datetime.utcnow()
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="✅ No Cooldown",
                description=f"{target.mention} can request meetings.",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            await ctx.send(embed=embed)
    
    @commands.command(name='forcemeeting')
    @commands.has_permissions(administrator=True)
    async def forcemeeting(self, ctx, *members: discord.Member):
        """Create a forced meeting without voting (admin only) - does not apply cooldowns"""
        if len(members) < 1 or len(members) > 5:
            await ctx.send("❌ You must mention between 1 and 5 players.")
            return
        cfg = self._meeting_config(ctx.guild.id)
        if not cfg["meeting_enabled"] or not cfg.get("target_guild_id") or not cfg.get("meeting_category_id"):
            await ctx.send("❌ Meeting system is not configured. Use `.setmeetingchannel`, `.setmeetingtargetguild`, `.setmeetingcategory`, then `.meetingenable true`.")
            return
        try:
            await ctx.message.delete()
            target_guild = self.bot.get_guild(int(cfg["target_guild_id"]))
            if not target_guild:
                await ctx.send("❌ Target server not found.")
                return
            category = target_guild.get_channel(int(cfg["meeting_category_id"]))
            if not category:
                await ctx.send("❌ Meeting category not found.")
                return
            
            # Channel name from all members
            member_names = "-".join([m.display_name.lower().replace(" ", "-") for m in members])
            channel_name = f"{member_names}"[:100]
            
            # Prepare permissions
            people_to_add = set(members)
            
            # Check existing meetings and close if necessary
            for participant in members:
                target_member = target_guild.get_member(participant.id)
                if target_member:
                    for channel in category.text_channels:
                        try:
                            perms = channel.permissions_for(target_member)
                            if perms.send_messages:
                                await self.close_meeting_channel(channel, closed_by=participant)
                                break
                        except:
                            continue
            
            # Add sponsors from RC channels
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                
                if rc_category and sponsor_role:
                    for rc_channel in rc_category.text_channels:
                        has_participant = False
                        for member in members:
                            perms = rc_channel.permissions_for(member)
                            if perms.read_messages:
                                has_participant = True
                                break
                        
                        if has_participant:
                            for rc_member in rc_channel.members:
                                if sponsor_role in rc_member.roles:
                                    people_to_add.add(rc_member)
            
            # Create overwrites - everyone cannot read
            overwrites = {
                target_guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                )
            }
            
            for person in people_to_add:
                try:
                    target_member = target_guild.get_member(person.id)
                    if target_member:
                        overwrites[target_member] = discord.PermissionOverwrite(
                            read_messages=True,
                            send_messages=True
                        )
                except:
                    continue
            
            # Create channel
            new_channel = await target_guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )
            
            # Welcome message - only mention actual participants
            participants_mentions = " ".join([p.mention for p in members if target_guild.get_member(p.id)])
            welcome_embed = discord.Embed(
                title="⚡ Administrative Meeting",
                description=f"Meeting forced by administrator **{ctx.author.display_name}**",
                color=0xff3fb9,
                timestamp=datetime.utcnow()
            )
            welcome_embed.add_field(
                name="Participants",
                value=participants_mentions,
                inline=False
            )
            welcome_embed.add_field(
                name="Note",
                value="This is an admin-created meeting. No cooldowns applied.",
                inline=False
            )
            welcome_embed.set_footer(text=f"Meeting ID: {new_channel.id}")
            
            await new_channel.send(embed=welcome_embed)

            # 🔥 Notify Meetup system
            participants_in_target = [
                target_guild.get_member(p.id)
                for p in members
                if target_guild.get_member(p.id)
            ]

            await self.notify_meetup_system(target_guild, new_channel, participants_in_target)

            # Store active meeting data
            start_time = datetime.utcnow()
            self.active_meetings[new_channel.id] = {
                'message_id': None,
                'origin_guild_id': ctx.guild.id,
                'start_time': start_time,
                'participants': list(members),
                'origin_channel_id': ctx.channel.id
            }
            
            # Send confirmation to admin
            await ctx.send(f"✅ Forced meeting created: {new_channel.mention}", delete_after=10)
            
        except Exception as e:
            await ctx.send(f"❌ Error creating meeting: {str(e)}")
            print(f"Error forcemeeting: {e}")
    
    @commands.command(name='listblocked')
    @commands.has_permissions(administrator=True)
    async def listblocked(self, ctx):
        """Show the list of blocked users"""

        blocked_user_ids = get_blocked_users(ctx.guild.id)
        if not blocked_user_ids:
            await ctx.send("✅ No blocked users.")
            return
        
        blocked_mentions = []
        for user_id in blocked_user_ids:
            member = ctx.guild.get_member(user_id)
            if member:
                blocked_mentions.append(f"• {member.mention} (`{member.id}`)")
            else:
                blocked_mentions.append(f"• Unknown user (`{user_id}`)")
        
        embed = discord.Embed(
            title="🚫 Blocked Users",
            description="\n".join(blocked_mentions),
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Total: {len(blocked_user_ids)}")
        await ctx.send(embed=embed)
    
    @commands.command(name='listcooldowns')
    @commands.has_permissions(administrator=True)
    async def listcooldowns(self, ctx):
        """Show all users currently on meeting cooldown"""

        rows = list_meeting_cooldowns(ctx.guild.id)
        if not rows:
            await ctx.send("✅ No users on cooldown.")
            return
        
        cooldown_list = []
        current_time = datetime.utcnow()

        for user_id, cooldown_until in rows:
            if current_time >= cooldown_until:
                # best-effort cleanup of expired entries
                clear_meeting_cooldown(ctx.guild.id, user_id)
                continue

            member = ctx.guild.get_member(user_id)
            
            time_remaining = cooldown_until - current_time
            minutes = int(time_remaining.total_seconds() / 60)
            seconds = int(time_remaining.total_seconds() % 60)
            
            if minutes > 0:
                time_str = f"{minutes}m {seconds}s"
            else:
                time_str = f"{seconds}s"
            
            if member:
                cooldown_list.append(f"• {member.mention} - {time_str} remaining")
            else:
                cooldown_list.append(f"• Unknown user (`{user_id}`) - {time_str} remaining")
        
        if not cooldown_list:
            await ctx.send("✅ No users on cooldown.")
            return
        
        embed = discord.Embed(
            title="⏱️ Users on Meeting Cooldown",
            description="\n".join(cooldown_list),
            color=0xff3fb9,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Total: {len(cooldown_list)}")
        await ctx.send(embed=embed)
    
    @commands.command(name='cancelmeeting')
    @commands.has_permissions(administrator=True)
    async def cancelmeeting_admin(self, ctx, message_id: int):
        """Cancel a pending meeting (admin only)"""
        for gid, pending in self.pending_meetings.items():
            if message_id in pending:
                await self.cancel_meeting(gid, message_id, f"Cancelled by administrator {ctx.author.mention}")
                await ctx.send("✅ Meeting cancelled.")
                return
        await ctx.send("❌ Meeting not found or already completed.")
    
    @commands.command(name='meetingstats')
    @commands.has_permissions(administrator=True)
    async def meetingstats(self, ctx):
        """Show meeting statistics (for this server's meeting config)."""
        cfg = self._meeting_config(ctx.guild.id)
        if not cfg.get("target_guild_id") or not cfg.get("meeting_category_id"):
            await ctx.send("❌ Meeting system not configured. Set target guild and category first.")
            return
        try:
            target_guild = self.bot.get_guild(int(cfg["target_guild_id"]))
            if not target_guild:
                await ctx.send("❌ Target server not found.")
                return
            category = target_guild.get_channel(int(cfg["meeting_category_id"]))
            total_archived = 0
            archive_categories = []
            for cat in target_guild.categories:
                if cat.name.startswith(self.ARCHIVE_BASE_NAME):
                    archive_categories.append((cat.name, len(cat.channels)))
                    total_archived += len(cat.channels)
            active_meetings = len(category.text_channels) if category else 0
            pending_meetings = sum(len(p) for p in self.pending_meetings.values())
            
            # Count cooldowns
            current_time = datetime.utcnow()
            active_cooldowns = 0
            for user_id, cooldown_until in list_meeting_cooldowns(ctx.guild.id):
                if current_time < cooldown_until:
                    active_cooldowns += 1
                else:
                    clear_meeting_cooldown(ctx.guild.id, user_id)
            
            embed = discord.Embed(
                title="📊 Meeting Statistics",
                color=0xff3fb9,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Active Meetings", value=f"🟢 {active_meetings}", inline=True)
            embed.add_field(name="Archived Meetings", value=f"📦 {total_archived}", inline=True)
            embed.add_field(name="Pending Approval", value=f"⏳ {pending_meetings}", inline=True)
            embed.add_field(name="Active Cooldowns", value=f"⏱️ {active_cooldowns}", inline=True)
            
            # Show archive category breakdown
            if archive_categories:
                archive_info = "\n".join([f"• {name}: {count} channels" for name, count in sorted(archive_categories)])
                embed.add_field(name="Archive Categories", value=archive_info, inline=False)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

async def setup(bot):
    await bot.add_cog(MeetingCog(bot))