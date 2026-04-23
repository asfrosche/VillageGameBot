import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import List, Optional
import json
import os
from datetime import datetime, timedelta
from cogs.data_utils import load_guild_data

class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Base path (root folder)
        self.base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Database folder path
        self.db_path = os.path.join(self.base_path, 'db')
        
        # Create db folder if it doesn't exist
        os.makedirs(self.db_path, exist_ok=True)
        
        self.blocked_users = self.load_blocked_users()
        self.meeting_cooldowns = self.load_meeting_cooldowns()
        self.pending_meetings = {}  # {message_id: meeting_data}
        self.user_pending_meetings = {}  # {user_id: message_id} to track user's pending meetings
        self.active_meetings = {}  # {channel_id: {message_id, start_time, participants}}
        
        # Fixed IDs
        self.MEETING_CHANNEL_ID = 1451263087913992353
        self.TARGET_GUILD_ID = 1451261733678223486
        self.MEETING_CATEGORY_ID = 1451262840173363240
        self.ARCHIVE_BASE_NAME = "ARCHIVE"  # Base name for archive categories
        self.MAX_CHANNELS_PER_ARCHIVE = 50
        
        # Cooldown duration in minutes
        self.MEETING_COOLDOWN_MINUTES = 60
    
    def load_blocked_users(self):
        """Load the list of blocked users"""
        try:
            file_path = os.path.join(self.db_path, 'blocked_users.json')
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading blocked_users: {e}")
        return {}
    
    def save_blocked_users(self):
        """Save the list of blocked users"""
        try:
            file_path = os.path.join(self.db_path, 'blocked_users.json')
            with open(file_path, 'w') as f:
                json.dump(self.blocked_users, f, indent=4)
        except Exception as e:
            print(f"Error saving blocked_users: {e}")
    
    def load_meeting_cooldowns(self):
        """Load meeting cooldowns"""
        try:
            file_path = os.path.join(self.db_path, 'meeting_cooldowns.json')
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    # Convert string timestamps back to datetime objects
                    cooldowns = {}
                    for guild_id, users in data.items():
                        cooldowns[guild_id] = {}
                        for user_id, timestamp_str in users.items():
                            cooldowns[guild_id][user_id] = datetime.fromisoformat(timestamp_str)
                    return cooldowns
        except Exception as e:
            print(f"Error loading meeting_cooldowns: {e}")
        return {}
    
    def save_meeting_cooldowns(self):
        """Save meeting cooldowns"""
        try:
            file_path = os.path.join(self.db_path, 'meeting_cooldowns.json')
            # Convert datetime objects to ISO format strings
            data = {}
            for guild_id, users in self.meeting_cooldowns.items():
                data[guild_id] = {}
                for user_id, timestamp in users.items():
                    data[guild_id][user_id] = timestamp.isoformat()
            
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving meeting_cooldowns: {e}")
    
    def is_user_blocked(self, guild_id: int, user_id: int) -> bool:
        """Check if a user is blocked"""
        guild_key = str(guild_id)
        return guild_key in self.blocked_users and user_id in self.blocked_users[guild_key]
    
    def add_meeting_cooldown(self, guild_id: int, user_id: int):
        """Add a user to meeting cooldown"""
        guild_key = str(guild_id)
        if guild_key not in self.meeting_cooldowns:
            self.meeting_cooldowns[guild_key] = {}
        
        cooldown_until = datetime.utcnow() + timedelta(minutes=self.MEETING_COOLDOWN_MINUTES)
        self.meeting_cooldowns[guild_key][str(user_id)] = cooldown_until
        self.save_meeting_cooldowns()
    
    def get_user_cooldown(self, guild_id: int, user_id: int) -> Optional[datetime]:
        """Get user's cooldown end time, returns None if no cooldown"""
        guild_key = str(guild_id)
        user_key = str(user_id)
        
        if guild_key not in self.meeting_cooldowns:
            return None
        
        if user_key not in self.meeting_cooldowns[guild_key]:
            return None
        
        cooldown_until = self.meeting_cooldowns[guild_key][user_key]
        
        # Check if cooldown has expired
        if datetime.utcnow() >= cooldown_until:
            # Remove expired cooldown
            del self.meeting_cooldowns[guild_key][user_key]
            self.save_meeting_cooldowns()
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
        
        # Verify it's in the correct channel
        if ctx.channel.id != self.MEETING_CHANNEL_ID:
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
        
        # Check if user has a pending meeting and cancel it
        if ctx.author.id in self.user_pending_meetings:
            old_message_id = self.user_pending_meetings[ctx.author.id]
            await self.cancel_meeting(old_message_id, f"Cancelled by {ctx.author.mention} to create a new meeting request")
        
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
        
        # Save pending meeting data
        all_participants = [ctx.author] + list(members)
        self.pending_meetings[message.id] = {
            'organizer': ctx.author,
            'participants': all_participants,
            'members': list(members),
            'votes': {},
            'guild_id': ctx.guild.id,
            'channel_id': ctx.channel.id
        }
        
        # Track user's pending meeting
        self.user_pending_meetings[ctx.author.id] = message.id
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle reactions to meeting embeds"""
        
        # Ignore bot reactions
        if payload.user_id == self.bot.user.id:
            return
        
        # Check if it's a pending meeting
        if payload.message_id not in self.pending_meetings:
            return
        
        meeting_data = self.pending_meetings[payload.message_id]
        
        # Check if user is a participant
        user = self.bot.get_user(payload.user_id)
        if user not in meeting_data['participants']:
            return
        
        # Check emoji
        if str(payload.emoji) == "👍":
            meeting_data['votes'][payload.user_id] = True
        elif str(payload.emoji) == "👎":
            # Meeting declined
            await self.cancel_meeting(payload.message_id, f"{user.mention} declined the meeting")
            return
        else:
            return
        
        # Update embed
        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        
        # Count votes
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
        
        # If everyone voted yes, create the meeting
        if votes_count == total_participants:
            await self.create_meeting_channel(payload.message_id, channel)
    
    async def create_meeting_channel(self, message_id: int, origin_channel):
        """Create the meeting channel in the other server"""
        
        meeting_data = self.pending_meetings[message_id]
        
        try:
            # Get original message
            message = await origin_channel.fetch_message(message_id)
            
            # Update embed
            embed = message.embeds[0]
            embed.color = discord.Color.green()
            embed.set_field_at(
                1,
                name="Status",
                value="✅ Meeting approved! Creating channel...",
                inline=False
            )
            await message.edit(embed=embed)
            
            # Get target server
            target_guild = self.bot.get_guild(self.TARGET_GUILD_ID)
            if not target_guild:
                await origin_channel.send("❌ Error: target server not found.")
                return
            
            # Get category
            category = target_guild.get_channel(self.MEETING_CATEGORY_ID)
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


            
            # Store active meeting data
            start_time = datetime.utcnow()
            self.active_meetings[new_channel.id] = {
                'message_id': message.id,
                'start_time': start_time,
                'participants': meeting_data['participants'],
                'origin_channel_id': meeting_data['channel_id']
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
            
            # Remove from pending meetings and user tracking
            organizer_id = meeting_data['organizer'].id
            if organizer_id in self.user_pending_meetings:
                del self.user_pending_meetings[organizer_id]
            del self.pending_meetings[message_id]
            
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
    
    async def cancel_meeting(self, message_id: int, reason: str):
        """Cancel a pending meeting"""
        
        if message_id not in self.pending_meetings:
            return
        
        meeting_data = self.pending_meetings[message_id]
        
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
            
            # Remove from user tracking
            organizer_id = meeting_data['organizer'].id
            if organizer_id in self.user_pending_meetings:
                del self.user_pending_meetings[organizer_id]
            
            del self.pending_meetings[message_id]
            
        except Exception as e:
            print(f"Error cancel_meeting: {e}")
    
    @commands.command(name='endmeeting')
    async def endmeeting(self, ctx):
        """End your active meeting"""
        
        # Check if user is blocked
        if self.is_user_blocked(ctx.guild.id, ctx.author.id):
            await ctx.send("❌ You have been blocked from using this command.", delete_after=10)
            return
        
        try:
            # Get target server
            target_guild = self.bot.get_guild(self.TARGET_GUILD_ID)
            if not target_guild:
                await ctx.send("❌ Target server not found.")
                return
            
            # Get meeting category
            category = target_guild.get_channel(self.MEETING_CATEGORY_ID)
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
    
    # ADMIN COMMANDS
    
    @commands.command(name='blockmeeting')
    @commands.has_permissions(administrator=True)
    async def blockmeeting(self, ctx, member: discord.Member):
        """Block a user from using meeting commands"""
        
        guild_key = str(ctx.guild.id)
        if guild_key not in self.blocked_users:
            self.blocked_users[guild_key] = []
        
        if member.id in self.blocked_users[guild_key]:
            await ctx.send(f"⚠️ {member.mention} is already blocked.")
            return
        
        self.blocked_users[guild_key].append(member.id)
        self.save_blocked_users()
        
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
        
        guild_key = str(ctx.guild.id)
        if guild_key not in self.blocked_users or member.id not in self.blocked_users[guild_key]:
            await ctx.send(f"⚠️ {member.mention} is not blocked.")
            return
        
        self.blocked_users[guild_key].remove(member.id)
        self.save_blocked_users()
        
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
        
        guild_key = str(ctx.guild.id)
        user_key = str(member.id)
        
        if guild_key in self.meeting_cooldowns and user_key in self.meeting_cooldowns[guild_key]:
            del self.meeting_cooldowns[guild_key][user_key]
            self.save_meeting_cooldowns()
            
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
        
        try:
            # Delete command message
            await ctx.message.delete()
            
            # Create meeting directly
            target_guild = self.bot.get_guild(self.TARGET_GUILD_ID)
            if not target_guild:
                await ctx.send("❌ Target server not found.")
                return
            
            category = target_guild.get_channel(self.MEETING_CATEGORY_ID)
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
                'message_id': None,  # No original message for forced meetings
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
        
        guild_key = str(ctx.guild.id)
        if guild_key not in self.blocked_users or not self.blocked_users[guild_key]:
            await ctx.send("✅ No blocked users.")
            return
        
        blocked_mentions = []
        for user_id in self.blocked_users[guild_key]:
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
        embed.set_footer(text=f"Total: {len(self.blocked_users[guild_key])}")
        await ctx.send(embed=embed)
    
    @commands.command(name='listcooldowns')
    @commands.has_permissions(administrator=True)
    async def listcooldowns(self, ctx):
        """Show all users currently on meeting cooldown"""
        
        guild_key = str(ctx.guild.id)
        if guild_key not in self.meeting_cooldowns or not self.meeting_cooldowns[guild_key]:
            await ctx.send("✅ No users on cooldown.")
            return
        
        cooldown_list = []
        current_time = datetime.utcnow()
        
        for user_id_str, cooldown_until in list(self.meeting_cooldowns[guild_key].items()):
            # Check if cooldown has expired
            if current_time >= cooldown_until:
                continue
            
            user_id = int(user_id_str)
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
        
        if message_id not in self.pending_meetings:
            await ctx.send("❌ Meeting not found or already completed.")
            return
        
        await self.cancel_meeting(message_id, f"Cancelled by administrator {ctx.author.mention}")
        await ctx.send("✅ Meeting cancelled.")
    
    @commands.command(name='meetingstats')
    @commands.has_permissions(administrator=True)
    async def meetingstats(self, ctx):
        """Show meeting statistics"""
        
        try:
            target_guild = self.bot.get_guild(self.TARGET_GUILD_ID)
            if not target_guild:
                await ctx.send("❌ Target server not found.")
                return
            
            category = target_guild.get_channel(self.MEETING_CATEGORY_ID)
            
            # Count all archive categories
            total_archived = 0
            archive_categories = []
            for cat in target_guild.categories:
                if cat.name.startswith(self.ARCHIVE_BASE_NAME):
                    archive_categories.append((cat.name, len(cat.channels)))
                    total_archived += len(cat.channels)
            
            active_meetings = len(category.text_channels) if category else 0
            pending_meetings = len(self.pending_meetings)
            
            # Count cooldowns
            guild_key = str(ctx.guild.id)
            active_cooldowns = 0
            if guild_key in self.meeting_cooldowns:
                current_time = datetime.utcnow()
                for cooldown_until in self.meeting_cooldowns[guild_key].values():
                    if current_time < cooldown_until:
                        active_cooldowns += 1
            
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