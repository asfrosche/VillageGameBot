import uuid
import discord
import asyncio
import datetime
from datetime import datetime
from discord.ext import commands
from cogs.data_utils import load_guild_data

class Moving(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Add commands
    @commands.command()
    async def add(self, ctx, channel_str: str, *args):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = discord.utils.get(category.channels, name=channel_name)
                channel = ctx.channel
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    await self.process_add(ctx, new_channel, channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command(aliases=['renadd'])
    async def pcadd(self, ctx, new_channel: discord.TextChannel, *args):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                channel = ctx.channel
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    await self.process_add(ctx, new_channel, channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")
    
    @commands.command()
    async def addhere(self, ctx, *rolechats: discord.TextChannel):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        for rolechat in rolechats:
            if rolechat is not None:
                channel = rolechat
                new_channel = ctx.channel
                stealth = False
                read_only = False
                await self.process_add(ctx, new_channel, channel, is_stealth=stealth, read_only=read_only)
            else:
                await ctx.send(f"{rolechat.name} not found.")

    async def process_add(self, ctx, new_channel: discord.TextChannel, channel: discord.TextChannel, is_stealth=False, read_only=False):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            members = channel.members
            if new_channel.category == rc_category:
                await ctx.send("**Do you confirm you want to add the player inside a Rolechat?**\nReply with yes/no.")
                def check(m):
                    return m.author == ctx.author and m.content.lower() in ["yes", "no"]
                try:
                    response = await self.bot.wait_for("message", timeout=60, check=check)
                    if response.content.lower() == "yes":
                        done = "Yes"
                    else:
                        await ctx.send("Action cancelled.")
                        return
                except asyncio.TimeoutError:
                    await ctx.send("Time expired. Action cancelled.")
                    return
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
                    if not is_stealth:
                        await new_channel.send(f'{member.mention} Joins')
                    embed = discord.Embed(title='Member added', description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`', color=0xff3fb9, timestamp=datetime.now())
                    embed.add_field(name='Added To:', value=f"{new_channel.mention} `[{new_channel.name}]`", inline=False)
                    embed.set_footer(text="Village Game")
                    if log_channel:
                        await log_channel.send(embed=embed)
                elif sponsor_role in member.roles:
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only )
            await ctx.send('Done')
        else:
            await ctx.send("Guild data not loaded.")

    ##############################################################################################################################################

    # Remove commands
    @commands.command()
    async def remove(self, ctx, channel_str: str, stealth: str = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = discord.utils.get(category.channels, name=channel_name)
                if new_channel is not None:
                    if stealth is None:
                        await self.process_remove(ctx, new_channel)
                    elif stealth.lower() == 'stealth':
                        await self.process_remove(ctx, new_channel, is_stealth=True)
                    else:
                        await ctx.send(f'{stealth} is not a valid argument')
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command(aliases=['renremove'])
    async def pcremove(self, ctx, new_channel: discord.TextChannel, stealth: str = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if new_channel is not None:
                    if stealth is None:
                        await self.process_remove(ctx, new_channel)
                    elif stealth.lower() == 'stealth':
                        await self.process_remove(ctx, new_channel, is_stealth=True)
                    else:
                        await ctx.send(f'{stealth} is not a valid argument')
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def process_remove(self, ctx, new_channel: discord.TextChannel, is_stealth=False):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
            channel = ctx.channel
            members = channel.members
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    ow = new_channel.overwrites_for(member)
                    if ow != discord.PermissionOverwrite():
                        await new_channel.set_permissions(member, overwrite=None)
                        if not is_stealth:
                            await new_channel.send(f'{member.mention} Leaves')
                        embed = discord.Embed(title='Member removed', description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`', color=0xff3fb9, timestamp=datetime.now())
                        embed.add_field(name='Removed From:', value=f"{new_channel.mention} `[{new_channel.name}]`", inline=False)
                        embed.set_footer(text="Village Game")
                        if log_channel:
                            await log_channel.send(embed=embed)
                elif sponsor_role in member.roles:
                    ow = new_channel.overwrites_for(member)
                    if ow != discord.PermissionOverwrite():
                        await new_channel.set_permissions(member, overwrite=None)
            await ctx.send('Done')
        else:
            await ctx.send("Guild data not loaded.")

    ##############################################################################################################################################

    # Moving commands
    @commands.command()
    async def move(self, ctx, channel_str: str, *args):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = discord.utils.get(category.channels, name=channel_name)
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    await self.process_move(ctx, new_channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command()
    async def renmove(self, ctx, new_channel: discord.TextChannel, *args):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    await self.process_move(ctx, new_channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    async def process_move(self, ctx, new_channel: discord.TextChannel, is_stealth=False, read_only=False):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
            category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            channel = ctx.channel
            members = channel.members
            if new_channel.category == rc_category:
                await ctx.send("**Do you confirm you want to move the player inside a Rolechat?**\nReply with yes/no.")
                def check(m):
                    return m.author == ctx.author and m.content.lower() in ["yes", "no"]
                try:
                    response = await self.bot.wait_for("message", timeout=60, check=check)
                    if response.lower() == "yes":
                        done = "Yes"
                    else:
                        await ctx.send("Action cancelled.")
                        return
                except asyncio.TimeoutError:
                    await ctx.send("Time expired. Action cancelled.")
                    return
            old_house_list = []
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    for channel in category.channels:
                        permissions = channel.permissions_for(member)
                        if permissions.send_messages:
                            await channel.set_permissions(member, overwrite=None)
                            old_house_list.append(f"{channel.mention} `[{channel.name}]`")
                            if not is_stealth:
                                await channel.send(f'{member.mention} Leaves')
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
                    if not is_stealth:
                        await new_channel.send(f'{member.mention} Joins')
                    embed = discord.Embed(title='Member moved', description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`', color=0xff3fb9, timestamp=datetime.now())
                    if old_house_list:
                        embed.add_field(name='Removed From:', value="\n".join(old_house_list), inline=False)
                    embed.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                    embed.set_footer(text="Village Game")
                    if log_channel:
                        await log_channel.send(embed=embed)
                elif sponsor_role in member.roles:
                    for channel in category.channels:
                        permissions = channel.permissions_for(member)
                        if permissions.send_messages:
                            await channel.set_permissions(member, overwrite=None)
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
            await ctx.send('Done')
        else:
            await ctx.send("Guild data not loaded.")

    ##############################################################################################################################################

    # Knocking commands
    @commands.command()
    async def knock(self, ctx, channel_str: str):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = discord.utils.get(category.channels, name=channel_name)
                if new_channel is not None:
                    await self.process_knock(ctx, new_channel, guild_data)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def renknock(self, ctx, new_channel: discord.TextChannel):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if new_channel is not None:
                    await self.process_knock(ctx, new_channel, guild_data)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def process_knock(self, ctx, new_channel: discord.TextChannel, guild_data):
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
        overseer_role = discord.utils.get(ctx.guild.roles, name=guild_data["overseer_role_name"])
        category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        channel = ctx.channel
        members = channel.members
        old_house_list = []
        alive_members_with_permission = []
        dead_members_with_permissions = []
        alt_members_with_permissions = []
        for member in new_channel.members:
            if alive_role in member.roles:
                permissions = new_channel.permissions_for(member)
                if permissions.send_messages:
                    alive_members_with_permission.append(member)
            if dead_role in member.roles:
                permissions = new_channel.permissions_for(member)
                if permissions.send_messages:
                    dead_members_with_permissions.append(member)
            if alt_role in member.roles:
                permissions = new_channel.permissions_for(member)
                if permissions.send_messages:
                    alt_members_with_permissions.append(member)
        check = True
        if alive_members_with_permission:
            check = False
        else:
            if guild_data["dead_count"] and dead_members_with_permissions:
                check = False
            elif guild_data["alt_count"] and alt_members_with_permissions:
                check = False
        if check:
            if guild_data["autojoinifempty"]:
                for member in members:
                    if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                await channel.set_permissions(member, overwrite=None)
                                old_house_list.append(f"{channel.mention} `[{channel.name}]`")
                                await channel.send(f'{member.mention} Leaves')
                        await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                        await new_channel.send(f'{member.mention} Joins')
                        embed = discord.Embed(title='Member moved', description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`', color=0xff3fb9, timestamp=datetime.now())
                        if old_house_list:
                            embed.add_field(name='Removed From:', value="\n".join(old_house_list), inline=False)
                        embed.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                        embed.set_footer(text="Village Game")
                        if log_channel:    
                            await log_channel.send(embed=embed)
                        await ctx.send("The house is empty. Auto Joining...")
                    elif sponsor_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                await channel.set_permissions(member, overwrite=None)
                        await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                return
            else:
                await ctx.send("The house is empty")
                return
        total_members = len(alive_members_with_permission)
        if guild_data["dead_count"]:
            total_members += len(dead_members_with_permissions)
        if guild_data["alt_count"]:
            total_members += len(alt_members_with_permissions)
        if total_members >= guild_data["maxmembersinhome"]:
            await ctx.send("The house is full")
            return
        await ctx.send('Knocking...')
        bot_message = await new_channel.send(f'{alive_role.mention} {sponsor_role.mention} Knock Knock')
        await bot_message.pin()
        async for messages in new_channel.history(limit=3):
            if messages.type == discord.MessageType.pins_add and messages.author == self.bot.user:
                await messages.delete()
                break
        def check(message):
            return (
                message.channel == new_channel
                and message.content.lower() in ['open', 'refuse', 'cancel']
                and message.reference and message.reference.message_id == bot_message.id
                )
        while True:
            try:
                response = await self.bot.wait_for('message', check=check, timeout=guild_data["timeout_duration"])
                if response.content.lower() == 'open':
                    author_roles = {role for role in response.author.roles}
                    if (dead_role in author_roles and not guild_data["can_dead_open"]) or (alt_role in author_roles and not guild_data["can_alt_open"]):
                        await response.channel.send("You can't interact with the door.")
                        continue
                    for member in members:
                        if alive_role in member.roles or alt_role in member.roles:
                            for channel in category.channels:
                                permissions = channel.permissions_for(member)
                                if permissions.send_messages:
                                    await channel.set_permissions(member, overwrite=None)
                                    old_house_list.append(f"{channel.mention} `[{channel.name}]`")
                                    await channel.send(f'{member.mention} Leaves')
                            await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                            await bot_message.reply(f'{member.mention} Joins')
                            embed = discord.Embed(title='Member moved', description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`', color=0xff3fb9, timestamp=datetime.now())
                            if old_house_list:
                                embed.add_field(name='Removed From:', value="\n".join(old_house_list), inline=False)
                            embed.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                            embed.set_footer(text="Village Game")
                            await log_channel.send(embed=embed)
                        elif sponsor_role in member.roles:
                            for channel in category.channels:
                                permissions = channel.permissions_for(member)
                                if permissions.send_messages:
                                    await channel.set_permissions(member, overwrite=None)
                            await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                    await bot_message.edit(content=f"**ACCEPTED**\n~~{alive_role.mention} {sponsor_role.mention} Knock Knock~~")
                    await bot_message.unpin()
                    break
                elif response.content.lower() == 'refuse':
                    author_roles = {role for role in response.author.roles}
                    if (dead_role in author_roles and not guild_data["can_dead_open"]) or (alt_role in author_roles and not guild_data["can_alt_open"]):
                        await response.channel.send("You can't interact with the door.")
                        continue
                    alive_users = []
                    for member in new_channel.members:
                        if alive_role in member.roles:
                            alive_users.append(f'{member.mention} `{member.name}`')
                        if guild_data["show_dead_on_refuse"]:
                            if dead_role in member.roles:
                                alive_users.append(f'{member.mention} `{member.name}`')
                        if guild_data["show_alt_on_refuse"]:
                            if alt_role in member.roles:
                                alive_users.append(f'{member.mention} `{member.name}`')
                    if guild_data["refuseresponse"] == 1:
                        players_list = '\n'.join(alive_users)
                        embedr = discord.Embed(title="Knock Refused", description=f"Players inside the house:\n{players_list}", color=0xff3fb9, timestamp=datetime.now())
                        embedr.set_footer(text="Village Game")
                        await ctx.send(f'{alive_role.mention} {sponsor_role.mention}', embed=embedr)
                    elif guild_data["refuseresponse"] == 2:
                        await ctx.send(f"Your knock in {new_channel.name} got refused.\nThere are currently {len(alive_users)} players inside the house.")
                    elif guild_data["refuseresponse"] == 3:
                        await ctx.send(f"Your knock in {new_channel.name} got refused.")
                    await bot_message.unpin()
                    await bot_message.edit(content=f"**REFUSED**\n~~{alive_role.mention} {sponsor_role.mention} Knock Knock~~")
                    await bot_message.reply("Knock refused")
                    break
                elif response.content.lower() == 'cancel':
                    if response.author.guild_permissions.administrator:
                        await ctx.send("The knock has been cancelled.")
                        await bot_message.unpin()
                        await bot_message.edit(content=f"**CANCELLED**\n~~{alive_role.mention} {sponsor_role.mention} Knock Knock~~")
                        await bot_message.reply("Knock cancelled")
                        break
                    else:
                        await new_channel.send("You don't have permission to cancel the knock.")
            except asyncio.TimeoutError:
                if guild_data["autojoinknockexpired"]:
                    for member in members:
                        if alive_role in member.roles or sponsor_role in member.roles or alt_role in member.roles:
                            for channel in category.channels:
                                permissions = channel.permissions_for(member)
                                if permissions.send_messages:
                                    await channel.set_permissions(member, overwrite=None)
                                    if alive_role in member.roles or alt_role in member.roles:
                                        old_house_list.append(f"{channel.mention}`[{channel.name}]`")
                                        await channel.send(f'{member.mention} Leaves')
                            await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                            if alive_role in member.roles or alt_role in member.roles:
                                await bot_message.reply(f'{member.mention} Joins')
                                await bot_message.edit(content=f"**EXPIRED, AUTO JOINED**\n~~{alive_role.mention} {sponsor_role.mention} Knock Knock~~")
                                embed = discord.Embed(title='Member moved', description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`', color=0xff3fb9, timestamp=datetime.now())
                                if old_house_list:
                                    embed.add_field(name='Removed From:', value="\n".join(old_house_list), inline=False)
                                embed.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                                embed.set_footer(text="Village Game")
                                await log_channel.send(embed=embed)
                                timeout_duration_hours = guild_data["timeout_duration"] // 3600
                                await ctx.send(f"{timeout_duration_hours} hours went by from the knock in {new_channel.mention}. Auto Joining...")
                else:
                    timeout_duration_hours = guild_data["timeout_duration"] // 3600
                    await ctx.send(f"{overseer_role.mention} {alive_role.mention} {sponsor_role.mention}\n{timeout_duration_hours} hours went by from the knock in {new_channel.mention}")
                    await bot_message.edit(content=f"**EXPIRED**\n~~{alive_role.mention} {sponsor_role.mention} Knock Knock~~")
                await bot_message.unpin()
                break