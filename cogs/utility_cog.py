import os
import discord
import asyncio
import datetime
import tempfile
import re
from datetime import datetime
from discord.ext import commands
from discord.ui import View, Button
from cogs.data_utils import load_guild_data, save_guild_data, add_player

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _extract_channel_from_arg(self, ctx, value):
        if not value:
            return None
        match = re.fullmatch(r"<#(\d+)>", value.strip())
        if not match:
            return None
        return ctx.guild.get_channel(int(match.group(1)))

    def _normalize_team(self, team_value):
        if team_value is None:
            return None
        normalized = str(team_value).strip().lower()
        team_map = {
            "1": "village",
            "vill": "village",
            "village": "village",
            "v": "village",
            "good": "village",
            "2": "evil",
            "evil": "evil",
            "e": "evil",
            "bad": "evil",
            "3": "neutral",
            "neutral": "neutral",
            "n": "neutral",
            "4": "rk",
            "rk": "rk",
            "solo": "rk",
            "5": "corrupted",
            "corrupted": "corrupted",
            "corr": "corrupted",
        }
        return team_map.get(normalized)

    def _format_log_message(self, message):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = message.content.replace("\n", " ").strip()
        attachments = " ".join(attachment.url for attachment in message.attachments)
        if attachments:
            content = f"{content} {attachments}".strip()
        if not content:
            content = "[No text content]"
        return f"{timestamp} - {message.author}: {content}"

    async def _write_and_send_log(self, send_channel, source_channel, messages):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as temp_log:
            for message in messages:
                temp_log.write(f"{self._format_log_message(message)}\n")
            temp_log_name = temp_log.name
        try:
            await send_channel.send(
                f"Here is the log from {source_channel.mention}",
                file=discord.File(temp_log_name, filename=f"log_{source_channel.name}.txt"),
            )
        finally:
            os.remove(temp_log_name)

    async def _choose_house_for_corpse(self, ctx, member, houses):
        if not houses:
            return None
        if len(houses) == 1:
            return houses[0]
        house_lines = [f"{index}. {house.mention}" for index, house in enumerate(houses, start=1)]
        await ctx.send(
            f"{member.mention} is in multiple houses. Reply with the house number, mention, or exact name for the corpse:\n"
            + "\n".join(house_lines)
        )

        def check(message):
            return message.author == ctx.author and message.channel == ctx.channel

        try:
            reply = await self.bot.wait_for("message", timeout=60, check=check)
        except asyncio.TimeoutError:
            await ctx.send("Timed out while waiting for the corpse house selection.")
            return False

        choice = reply.content.strip()
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(houses):
                return houses[index]

        selected_channel = self._extract_channel_from_arg(ctx, choice)
        if selected_channel in houses:
            return selected_channel

        lowered_choice = choice.lower()
        for house in houses:
            if house.name.lower() == lowered_choice:
                return house

        await ctx.send("That house selection was not recognized.")
        return False

    async def _prompt_deadrole_details(self, ctx):
        await ctx.send(
            "Please reply with the player's **Role Name** and **Team Number**:\n"
            "`1` - Villager 🟢\n"
            "`2` - Evil 🔴\n"
            "`3` - Neutral 🟡\n"
            "`4` - RK 🟣\n"
            "`5` - Corrupted ⚙️\n"
            "*(Example: `Doctor 1`)*"
        )

        def check(message):
            return message.author == ctx.author and message.channel == ctx.channel

        try:
            reply = await self.bot.wait_for("message", timeout=120, check=check)
        except asyncio.TimeoutError:
            await ctx.send("Timed out while waiting for the deadlist details.")
            return None, None

        parts = reply.content.strip().rsplit(" ", 1)
        if len(parts) != 2:
            await ctx.send("Invalid format. Please use `Role Name TeamNumber`, like `Doctor 1`.")
            return None, None

        role_name, team_value = parts
        team = self._normalize_team(team_value)
        if not team or not role_name.strip():
            await ctx.send("Invalid role or team. Please use a valid team number from 1 to 5.")
            return None, None
        return team, role_name.strip()

    async def _remove_member_from_side_channels(self, member, category):
        if not category:
            return
        for channel in category.channels:
            permissions = channel.permissions_for(member)
            if permissions.send_messages:
                await channel.set_permissions(member, overwrite=None)
                await channel.send(f"{member.mention} Leaves")

    @commands.command(aliases=['purge'])
    async def broom(self, ctx, from_id: int = None, to_id: int = None):
        if not ctx.author.guild_permissions.manage_messages:
            return await ctx.send("You need Manage Messages permission to use this command.")
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        broom_channel_name = guild_data.get("edit_del_logs")
        broom_channel = discord.utils.get(ctx.guild.text_channels, name=broom_channel_name)
        if not broom_channel:
            return await ctx.send("Broom log channel not found.")
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
        messages_to_delete = []
        if from_id and to_id:
            try:
                from_msg = await ctx.channel.fetch_message(from_id)
                to_msg = await ctx.channel.fetch_message(to_id)
            except discord.NotFound:
                return await ctx.send("One or both message IDs not found.")
            start_msg, end_msg = sorted([from_msg, to_msg], key=lambda m: m.created_at)
            async for message in ctx.channel.history(after=start_msg, before=end_msg, oldest_first=True):
                if not message.pinned:
                    messages_to_delete.append(message)
            if not from_msg.pinned:
                messages_to_delete.insert(0, from_msg)
            if not to_msg.pinned:
                messages_to_delete.append(to_msg)
        elif ctx.message.reference:
            try:
                replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except discord.NotFound:
                return await ctx.send("The replied-to message could not be found.")
            async for message in ctx.channel.history(after=replied_message, limit=None):
                if not message.pinned:
                    messages_to_delete.append(message)
            if not replied_message.pinned:
                messages_to_delete.insert(0, replied_message)
        else:
            return await ctx.send("Please reply to a message or provide `from_id` and `to_id`.")
        if not messages_to_delete:
            return await ctx.send("No messages to delete in the specified range.")
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".txt", encoding='utf-8') as temp_log:
            for message in messages_to_delete:
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                content = message.content.replace('\n', ' ')[:1000]
                temp_log.write(f"{timestamp} - {message.author}: {content}\n")
            temp_log_name = temp_log.name
        for i in range(0, len(messages_to_delete), 100):
            await ctx.channel.delete_messages(messages_to_delete[i:i + 100])
        await broom_channel.send(f'Messages broomed in {ctx.channel.mention}')
        await broom_channel.send(file=discord.File(temp_log_name))
        #alive_members = [member for member in ctx.channel.members if alive_role in member.roles]
        #if rc_category:
            #for member in alive_members:
                #for rc_channel in rc_category.channels:
                    #permissions = rc_channel.permissions_for(member)
                    #if permissions.read_messages:
                        #await rc_channel.send(f"Messages broomed in {ctx.channel.name}")
                        #await rc_channel.send(file=discord.File(temp_log_name))
        os.remove(temp_log_name)

    @commands.command()
    async def log(self, ctx, arg1: str = None, arg2: str = None, arg3: str = None):
        args = [arg for arg in [arg1, arg2, arg3] if arg is not None]
        send_channel = ctx.channel
        source_channel = ctx.channel

        if ctx.message.reference:
            if len(args) > 1:
                return await ctx.send("When replying, `.log` accepts at most one channel mention for where to send the file.")
            if args:
                send_channel = self._extract_channel_from_arg(ctx, args[0])
                if send_channel is None:
                    return await ctx.send("Invalid channel mention.")
            try:
                start_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except discord.NotFound:
                return await ctx.send("The replied-to message could not be found.")

            messages_to_log = [start_message]
            async for message in ctx.channel.history(after=start_message, before=ctx.message, oldest_first=True):
                messages_to_log.append(message)

            if not messages_to_log:
                return await ctx.send("No messages found in that range.")

            await self._write_and_send_log(send_channel, ctx.channel, messages_to_log)
            if send_channel != ctx.channel:
                await ctx.send(f"Log generated and sent to {send_channel.mention}.")
            return

        if not args:
            return await ctx.send(
                "Usage:\n"
                "`.log 25`\n"
                "`.log 25 #source-channel`\n"
                "`.log 25 #source-channel #send-channel`\n"
                "`.log #source-channel 25`"
            )

        if args[0].isdigit():
            count = int(args[0])
            if count <= 0:
                return await ctx.send("Message count must be greater than 0.")
            if len(args) >= 2:
                parsed_channel = self._extract_channel_from_arg(ctx, args[1])
                if parsed_channel is None:
                    return await ctx.send("Invalid source channel mention.")
                source_channel = parsed_channel
            if len(args) == 3:
                parsed_channel = self._extract_channel_from_arg(ctx, args[2])
                if parsed_channel is None:
                    return await ctx.send("Invalid destination channel mention.")
                send_channel = parsed_channel
            if len(args) > 3:
                return await ctx.send("Too many arguments for `.log`.")
        else:
            source_channel = self._extract_channel_from_arg(ctx, args[0])
            if source_channel is None or len(args) != 2 or not args[1].isdigit():
                return await ctx.send("Invalid arguments. Example: `.log #house-5 25`.")
            count = int(args[1])
            if count <= 0:
                return await ctx.send("Message count must be greater than 0.")

        permissions = source_channel.permissions_for(ctx.author)
        if not permissions.read_messages:
            return await ctx.send("You do not have permission to read messages in that channel.")

        messages_to_log = [message async for message in source_channel.history(limit=count, oldest_first=True)]
        if not messages_to_log:
            return await ctx.send("No messages found to log.")

        await self._write_and_send_log(send_channel, source_channel, messages_to_log)
        if send_channel != ctx.channel:
            await ctx.send(f"Log generated and sent to {send_channel.mention}.")
        else:
            await ctx.send("Log generated.")

    @commands.command()
    async def day(self, ctx):
        self.bot.dispatch("phase_change", "day") # added for meetupmatrix.py
        await self._manage_channels(ctx, True)

    @commands.command()
    async def night(self, ctx):
        self.bot.dispatch("phase_change", "night") # added for meetupmatrix.py
        await self._manage_channels(ctx, False)

    async def _manage_channels(self, ctx, allow_messages):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            os_role = discord.utils.get(ctx.guild.roles, name=guild_data["overseer_role_name"])
            if os_role in ctx.author.roles or ctx.author.guild_permissions.administrator:
                guild = ctx.guild
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                nightembed = discord.Embed(title="DAY ENDS", color=0xff3fb9, timestamp=datetime.now())
                nightembed.set_image(url="https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUyc2x4MWg1ajU1dmVvbjhlcnU1cmRncHI1ZTZmeXNvb3RrZ3BnNGJ2YSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/SirUFDS5F83Go/giphy.gif")
                nightembed.set_footer(text="Village Game")
                dayembed = discord.Embed(title="DAY STARTS", color=0xff3fb9, timestamp=datetime.now())
                dayembed.set_image(url="https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExYzhpcTRsZXpuZ2RtcTl2c2hoMms4cmc4YmFsbDE1Mnl5emM1c3NrZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/VDGOdvmp1bpc3PcCry/giphy.gif")
                dayembed.set_footer(text="Village Game")
                annnightembed = discord.Embed(title="DAY ENDS", color=0xff3fb9, timestamp=datetime.now())
                annnightembed.set_image(url="https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUyc2x4MWg1ajU1dmVvbjhlcnU1cmRncHI1ZTZmeXNvb3RrZ3BnNGJ2YSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/SirUFDS5F83Go/giphy.gif")
                annnightembed.set_footer(text="Village Game")
                anndayembed = discord.Embed(title="DAY STARTS", color=0xff3fb9, timestamp=datetime.now())
                anndayembed.set_image(url="https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExYzhpcTRsZXpuZ2RtcTl2c2hoMms4cmc4YmFsbDE1Mnl5emM1c3NrZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/VDGOdvmp1bpc3PcCry/giphy.gif")
                anndayembed.set_footer(text="Village Game")
                await ctx.send(f'{"Locking" if not allow_messages else "Unlocking"} channels')
                daychat = discord.utils.get(guild.channels, name=guild_data["daydiscussion_channel_name"])
                megaphone = discord.utils.get(guild.channels, name=guild_data["megaphone_channel_name"])
                announcements_channel = discord.utils.get(guild.channels, name=guild_data["announcements_channel_name"])
                lynch_channel1 = discord.utils.get(guild.channels, name=guild_data["lynch_channel_name1"])
                lynch_channel2 = discord.utils.get(guild.channels, name=guild_data["lynch_channel_name2"])
                leader_channel = discord.utils.get(guild.channels, name=guild_data["leader_channel_name"])
                daychat_channels = [daychat, megaphone]
                voting_channels = [lynch_channel1, lynch_channel2, leader_channel]
                if announcements_channel:
                	await announcements_channel.send(f'{alive_role.mention} {sponsor_role.mention}', embed=annnightembed if not allow_messages else anndayembed)
                for channel in daychat_channels:
                    if channel:
                    	await channel.set_permissions(alive_role, view_channel=True, send_messages=allow_messages)
                    	await channel.set_permissions(sponsor_role, view_channel=True, send_messages=allow_messages)
                    	await channel.send(embed=nightembed if not allow_messages else dayembed)
                for channel in voting_channels:
                    if channel:
                        await channel.set_permissions(alive_role, view_channel=True, send_messages=allow_messages)
                        await channel.set_permissions(sponsor_role, view_channel=True, send_messages=False)
                        await channel.send(embed=nightembed if not allow_messages else dayembed)
                meetings_channel = discord.utils.get(guild.channels, name="👥│meetings")
                if meetings_channel:
                    await meetings_channel.set_permissions(alive_role, view_channel=True, send_messages=allow_messages)
                    await meetings_channel.send(embed=nightembed if not allow_messages else dayembed)
                await ctx.send('Done')
            else:
                await ctx.send("You don't have enough perms to use this command")
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def whisper(self, ctx, receiver_channel: discord.TextChannel, *, message: str):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        if not receiver_channel:
            await ctx.send("Channel not found")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        whisper_logs_channel = discord.utils.get(ctx.guild.channels, name=guild_data["whisper_logs_channel_name"])
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sender = None
        for member in ctx.channel.members:
            if alive_role in member.roles:
                sender = member
                break
        receiver = None
        for member in receiver_channel.members:
            if alive_role in member.roles:
                receiver = member
                break
        embed = discord.Embed(color=0xff3fb9, timestamp=datetime.now())
        if guild_data["showwhispersender"] and sender:
            embed.add_field(name=f"{sender.mention} `[{sender.display_name}]` sent you a whisper:", value=f'{message}', inline=False)
        else:
            embed.add_field(name="Someone sent you a whisper:", value=f'{message}', inline=False)
        embed.set_footer(text="Village Game")
        if receiver:
            await receiver_channel.send(f"{receiver.mention}")
            eout2 = receiver.mention
        else:
            eout2 = receiver_channel.mention
        await receiver_channel.send(embed=embed)
        embedlog = discord.Embed(color=0xff3fb9, timestamp=datetime.now())
        if sender:
            eout1 = sender.mention
        else:
            eout1 = ctx.channel.mention
        embedlog.add_field(name=f"{eout1} sent a whisper to {eout2}:", value=f'{message}\n\n{receiver_channel.mention}', inline=False)
        embedlog.set_footer(text="Village Game")
        await whisper_logs_channel.send(embed=embedlog)

    @commands.command()
    async def switch(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                channel = ctx.channel
                members = channel.members
                for member in members:
                    if sponsor_role in member.roles:
                        await member.remove_roles(sponsor_role)
                        await member.add_roles(alive_role)
                        await ctx.send(f'{member.mention} is now {alive_role.mention}')
                    elif alive_role in member.roles:
                        await member.remove_roles(alive_role)
                        await member.add_roles(sponsor_role)
                        await ctx.send(f'{member.mention} is now {sponsor_role.mention}')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    # Comando dead
    @commands.command()
    async def dead(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                alt_category = discord.utils.get(ctx.guild.categories, name=guild_data["alt_category_name"])
                if ctx.channel.category not in [rc_category, alt_category]:
                    await ctx.send("This command only works in RoleChannels and ALTs RoleChannels.")
                    return
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                privc_category = discord.utils.get(ctx.guild.categories, name=guild_data["privc_category_name"])
                publc_category = discord.utils.get(ctx.guild.categories, name=guild_data["publc_category_name"])
                dead_category = discord.utils.get(ctx.guild.categories, name=guild_data["dead_rc_category_name"])
                channel = ctx.channel
                members = channel.members
                old_house = None
                await ctx.channel.edit(category=dead_category)
                for member in members:
                    if alive_role in member.roles:
                        if str(member.id) in guild_data["member_homes"]:
                            old_house_id = guild_data["member_homes"].get(str(member.id))
                            old_house = ctx.guild.get_channel(old_house_id)
                            del guild_data["member_homes"][str(member.id)]
                            await ctx.send(f'{member.mention} is now homeless')
                            save_guild_data(ctx.guild.id, guild_data)
                        if houses_category:
                            for house_channel in houses_category.channels:
                                permissions = house_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await house_channel.set_permissions(member, overwrite=None)    
                                    await house_channel.send(f'{member.mention} Leaves')
                        if old_house:
                            homeless_message = await old_house.send(f"{member.mention} doesn't live here anymore")
                            await homeless_message.pin()
                        if privc_category:
                            for priv_channel in privc_category.channels:
                                permissions = priv_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await priv_channel.set_permissions(member, overwrite=None)
                                    await priv_channel.send(f'{member.mention} Leaves')
                        if publc_category:
                            for publ_channel in publc_category.channels:
                                permissions = publ_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await publ_channel.set_permissions(member, overwrite=None)
                                    await publ_channel.send(f'{member.mention} Leaves')
                    elif sponsor_role in member.roles:
                        if str(member.id) in guild_data["member_homes"]:
                            del guild_data["member_homes"][str(member.id)]
                            await ctx.send(f'{member.mention} is now homeless')
                            save_guild_data(ctx.guild.id, guild_data)
                        if houses_category:
                            for house_channel in houses_category.channels:
                                permissions = house_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await house_channel.set_permissions(member, overwrite=None)
                        if privc_category:
                            for priv_channel in privc_category.channels:
                                permissions = priv_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await priv_channel.set_permissions(member, overwrite=None)
                        if publc_category:
                            for publ_channel in publc_category.channels:
                                permissions = publ_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await publ_channel.set_permissions(member, overwrite=None)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    # Comando dead
    @commands.command()
    async def deadc(self, ctx, current_house: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                privc_category = discord.utils.get(ctx.guild.categories, name=guild_data["privc_category_name"])
                publc_category = discord.utils.get(ctx.guild.categories, name=guild_data["publc_category_name"])
                dead_category = discord.utils.get(ctx.guild.categories, name=guild_data["dead_rc_category_name"])
                channel = ctx.channel
                members = channel.members
                old_house = None
                await ctx.channel.edit(category=dead_category)
                for member in members:
                    if alive_role in member.roles:
                        if houses_category:
                            houses = []
                            for house_channel in houses_category.channels:
                                permissions = house_channel.permissions_for(member)
                                if permissions.send_messages:
                                    houses.append(house_channel)
                            if current_house:
                                for houses_channel in houses:
                                    await houses_channel.set_permissions(member, overwrite=None)
                                    if houses_channel == current_house:
                                        corpse_message = await houses_channel.send(f'{member.mention} corpse is here')
                                        await corpse_message.pin()
                                    else:
                                        await houses_channel.send(f'{member.mention} Leaves')
                            elif len(houses) > 1:
                                await ctx.send(f"{member.mention} is currently in more than one house. Specify the house of the death in the command.")
                                return
                            elif len(houses) == 1:
                                for houses_channel in houses:
                                    await houses_channel.set_permissions(member, overwrite=None)    
                                    corpse_message = await houses_channel.send(f'{member.mention} corpse is here')
                                    await corpse_message.pin()
                        if str(member.id) in guild_data["member_homes"]:
                            old_house_id = guild_data["member_homes"].get(str(member.id))
                            old_house = ctx.guild.get_channel(old_house_id)
                            del guild_data["member_homes"][str(member.id)]
                            await ctx.send(f'{member.mention} is now homeless')
                            save_guild_data(ctx.guild.id, guild_data)
                            if old_house:
                                homeless_message = await old_house.send(f"{member.mention} doesn't live here anymore")
                                await homeless_message.pin()
                        if privc_category:
                            for priv_channel in privc_category.channels:
                                permissions = priv_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await priv_channel.set_permissions(member, overwrite=None)
                                    await priv_channel.send(f'{member.mention} Leaves')
                        if publc_category:
                            for publ_channel in publc_category.channels:
                                permissions = publ_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await publ_channel.set_permissions(member, overwrite=None)
                                    await publ_channel.send(f'{member.mention} Leaves')
                    elif sponsor_role in member.roles:
                        if str(member.id) in guild_data["member_homes"]:
                            del guild_data["member_homes"][str(member.id)]
                            await ctx.send(f'{member.mention} is now homeless')
                            save_guild_data(ctx.guild.id, guild_data)
                        if houses_category:
                            for house_channel in houses_category.channels:
                                permissions = house_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await house_channel.set_permissions(member, overwrite=None)
                        if privc_category:
                            for priv_channel in privc_category.channels:
                                permissions = priv_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await priv_channel.set_permissions(member, overwrite=None)
                        if publc_category:
                            for publ_channel in publc_category.channels:
                                permissions = publ_channel.permissions_for(member)
                                if permissions.send_messages:
                                    await publ_channel.set_permissions(member, overwrite=None)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    # Comando deadrole
    @commands.command()
    async def deadrole(self, ctx, *args):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("dead_role_name"))
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))
        privc_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("privc_category_name"))
        publc_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("publc_category_name"))
        if not dead_role:
            await ctx.send("Dead role not found")
            return
        if not alive_role and not sponsor_role:
            await ctx.send("Alive nor Sponsor roles not found")
            return
        alive_member = None
        sponsor_member = None
        for member in ctx.channel.members:
            if alive_role and alive_role in member.roles and alive_member is None:
                alive_member = member
            if sponsor_role and sponsor_role in member.roles and sponsor_member is None:
                sponsor_member = member

        target_member = alive_member or sponsor_member
        if target_member is None:
            await ctx.send("No alive player or sponsor was found in this channel.")
            return

        current_houses = []
        if houses_category:
            for house_channel in houses_category.channels:
                permissions = house_channel.permissions_for(target_member)
                if permissions.send_messages:
                    current_houses.append(house_channel)

        selected_house = await self._choose_house_for_corpse(ctx, target_member, current_houses)
        if selected_house is False:
            return

        if str(target_member.id) in guild_data["member_homes"]:
            del guild_data["member_homes"][str(target_member.id)]
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"{target_member.mention} is now homeless")

        for house_channel in current_houses:
            await house_channel.set_permissions(target_member, overwrite=None)
            if house_channel == selected_house:
                corpse_message = await house_channel.send(f"{target_member.mention} corpse is here")
                await corpse_message.pin()
            else:
                await house_channel.send(f"{target_member.mention} Leaves")

        await self._remove_member_from_side_channels(target_member, privc_category)
        await self._remove_member_from_side_channels(target_member, publc_category)

        if alive_member:
            await alive_member.remove_roles(alive_role)
            await alive_member.add_roles(dead_role)
            await ctx.send(f"{alive_member.display_name} is now {dead_role.mention}.")
        if sponsor_member:
            await sponsor_member.remove_roles(sponsor_role)
            await sponsor_member.add_roles(dead_role)
            await ctx.send(f"{sponsor_member.display_name} is now {dead_role.mention}.")

        team = None
        role = None
        if args:
            parsed = " ".join(args).strip().rsplit(" ", 1)
            if len(parsed) == 2:
                role = parsed[0].strip()
                team = self._normalize_team(parsed[1])
            if not role or not team:
                await ctx.send("Invalid syntax. Use `.deadrole Role Name TeamNumber`, for example `.deadrole Doctor 1`.")
                return
        else:
            team, role = await self._prompt_deadrole_details(ctx)
            if not team or not role:
                return

        add_player(target_member.name, team, role, ctx.guild.id)
        await ctx.send(f"{target_member.display_name} successfully added to deadlist.")
        estate_cog = self.bot.get_cog('Estate')
        if estate_cog:
            await estate_cog.update_estate_map(ctx.guild)
    
    @commands.command()
    async def addrole(self, ctx, role: discord.Role, *members):
        if ctx.author.guild_permissions.administrator:
            response = f"{role.mention} role successfully added"
            if 'everyone' in members:
                members_wo_role = [member for member in ctx.guild.members if role not in member.roles]
                for member in members_wo_role:
                    await member.add_roles(role)
                await ctx.send(f"{role.mention} role successfully added to everyone")
            else:
                members_wo_role = []
                for member in members:
                    found_member = discord.utils.find(lambda m: m.name == member or m.mention == member or str(m.id) == member, ctx.guild.members)
                    if found_member and role not in found_member.roles:
                        members_wo_role.append(found_member)
                        await found_member.add_roles(role)
                if members_wo_role:
                    await ctx.send(response)
                else:
                    await ctx.send("No valid members found or they already have the role.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    @commands.command()
    async def removerole(self, ctx, role: discord.Role, member: discord.Member):
        if not ctx.author.guild_permissions.administrator:
            return
        await member.remove_roles(role)
        
    @commands.command()
    async def addchannelperms(self, ctx, role: discord.Role, channel: discord.TextChannel, type: str = "r"):
        if ctx.author.guild_permissions.administrator:
            if type.lower() == "r":
                await channel.set_permissions(role, read_messages=True, send_messages=False)
            elif type.lower() == "s":
                await channel.set_permissions(role, read_messages=True, send_messages=True)
            else:
                return await ctx.send("Invalid type. Valid types are r and s")
            await ctx.send("Done")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    @commands.command()
    async def addcategoryperms(self, ctx, role: discord.Role, category_name: str, type: str = "r"):
        if ctx.author.guild_permissions.administrator:
            category = discord.utils.get(ctx.guild.categories, name=category_name)
            if category:
                if type.lower() == "r":
                    await category.set_permissions(role, read_messages=True, send_messages=False)
                    for channel in category.channels:
                        await channel.set_permissions(role, read_messages=True, send_messages=False)
                elif type.lower() == "s":
                    await category.set_permissions(role, read_messages=True, send_messages=True)
                    for channel in category.channels:
                        await channel.set_permissions(role, read_messages=True, send_messages=True)
                elif type.lower() == "m":
                    await category.set_permissions(role, read_messages=False, manage_messages=True)
                    for channel in category.channels:
                        await channel.set_permissions(role, read_messages=False, manage_messages=True) 
                else:
                    return await ctx.send("Invalid type. Valid types are r and s")
                await ctx.send("Done")
            else:
                await ctx.send("Category not found")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    @commands.command()
    async def endgame(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command.")
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        os_cat = discord.utils.get(ctx.guild.categories, name=guild_data['overseer_category_name'])
        everyone = ctx.guild.default_role
        prompt = discord.Embed(title='⚠️ Confirm Permissions Reset', description=("This will clear all perms outside the overseer category and give everyone **View Channels** and **Send Messages** in every channel.\n\nClick ✔ Yes to proceed or ❌ No to cancel."), color=0xFF3FB9, timestamp=datetime.utcnow()).set_footer(text="Village Game")
        view = discord.ui.View(timeout=None)

        async def confirm(inter: discord.Interaction):
            if inter.user != ctx.author:
                return await inter.response.send_message("You can't confirm this.", ephemeral=True)
            await inter.response.defer()
            base_perms = everyone.permissions
            grant = discord.Permissions(view_channel=True, send_messages=True)
            await everyone.edit(permissions=base_perms | grant)
            role_edits = [r.edit(permissions=r.permissions | discord.Permissions(send_messages=True)) for r in ctx.guild.roles if r != everyone and not r.managed]
            roles_task = asyncio.gather(*role_edits, return_exceptions=True)
            sem = asyncio.Semaphore(5)
            async def safe_clear(ch: discord.abc.GuildChannel):
                async with sem:
                    try:
                        await ch.edit(overwrites={})
                    except Exception:
                        pass
                    await asyncio.sleep(0.1)
            channels = [ch for cat in ctx.guild.categories if cat != os_cat for ch in cat.channels]
            channels_task = asyncio.gather(*(safe_clear(ch) for ch in channels), return_exceptions=True)
            await asyncio.gather(roles_task, channels_task)
            done = discord.Embed(
                title='✅ Done',
                description='Permissions have been reset.',
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            ).set_footer(text="Village Game")
            await inter.edit_original_response(embed=done, view=None)

        async def cancel(inter: discord.Interaction):
            if inter.user != ctx.author:
                return await inter.response.send_message("You can't cancel this.", ephemeral=True)
            await inter.response.edit_message(
                embed=discord.Embed(title='❌ Cancelled', description='Permissions reset cancelled.', color=discord.Color.red(), timestamp=datetime.utcnow()).set_footer(text="Village Game"), view=None)
        
        btn_yes = discord.ui.Button(label='✔ Yes', style=discord.ButtonStyle.green)
        btn_yes.callback = confirm
        btn_no  = discord.ui.Button(label='❌ No',  style=discord.ButtonStyle.red)
        btn_no.callback  = cancel
        view.add_item(btn_yes)
        view.add_item(btn_no)
        await ctx.send(embed=prompt, view=view)