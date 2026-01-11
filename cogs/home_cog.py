import random
import discord
import asyncio
import datetime
from datetime import datetime
from discord.ext import commands
from discord.ui import Button, View
from cogs.data_utils import load_guild_data, save_guild_data

class Home(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def home(self, ctx, type: str = None, user: discord.Member = None, new_channel: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            if type is None:
                await self.home_single(ctx)
            elif type.lower() == 'initialize':
                if user is None:
                    if new_channel is None:
                        await self.home_initialize(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for home initialize command')
                else:
                    await ctx.send(f'{user} is not a valid argument for home initialize command')
            elif type.lower() == 'setup':
                if user is None:
                    if new_channel is None:
                        await self.home_setup(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for home setup command')
                else:
                    await ctx.send(f'{user} is not a valid argument for home setup command')
            elif type.lower() == 'set':
                await self.home_set(ctx, user, new_channel)
            elif type.lower() == 'mset':
                if user is None:
                    if new_channel is None:
                        await self.home_mass_set(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for mass home set command')
                else:
                    await ctx.send(f'{user} is not a valid argument for mass home set command')
            elif type.lower() == 'delete':
                await self.home_delete(ctx, user)
            elif type.lower() == 'return':
                if user is None:
                    if new_channel is None:
                        await self.return_home(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for home return command')
                else:
                    await ctx.send(f'{user} is not a valid argument for home return command')
            elif type.lower() == 'list':
                if user is None:
                    if new_channel is None:
                        await self.list_home(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for home list command')
                else:
                    await ctx.send(f'{user} is not a valid argument for home list command')
            else:
                await ctx.send(f'{type} is not a valid argument')
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def home_single(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                members = ctx.channel.members
                if not category:
                    await ctx.send("Houses category not found")
                    return
                for member in members:
                    if alive_role in member.roles or alt_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                await channel.set_permissions(member, overwrite=None)
                                await channel.send(f'{member.mention} Leaves')
                        home_id = guild_data["member_homes"].get(str(member.id))
                        if home_id:
                            home_channel = discord.utils.get(category.channels, id=int(home_id))
                            if home_channel:
                                await home_channel.set_permissions(member, read_messages=True, send_messages=True)
                                await home_channel.send(f'{member.mention} Joins')
                    elif sponsor_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                await channel.set_permissions(member, overwrite=None)
                        home_id = guild_data["member_homes"].get(str(member.id))
                        if home_id:
                            home_channel = discord.utils.get(category.channels, id=int(home_id))
                            if home_channel:
                                await home_channel.set_permissions(member, read_messages=True, send_messages=True)
                await ctx.send('Done')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def home_initialize(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild = ctx.guild
                role_channel_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                house_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                members = [member for member in guild.members if alive_role in member.roles]
                numbers = list(range(1, len(members) + 1))
                random.shuffle(numbers)
                for i, member in enumerate(members):
                    role_chat_channel_name = str(numbers[i])
                    house_channel_name = f'{guild_data["house_prefix"]}{numbers[i]}'
                    role_chat_channel = discord.utils.get(role_channel_category.channels, name=role_chat_channel_name)
                    if not role_chat_channel:
                        role_chat_channel = await role_channel_category.create_text_channel(role_chat_channel_name)
                    house_channel = discord.utils.get(house_category.channels, name=house_channel_name)
                    if not house_channel:
                        house_channel = await house_category.create_text_channel(house_channel_name)
                    await role_chat_channel.set_permissions(member, read_messages=True, send_messages=True)
                    await house_channel.set_permissions(member, read_messages=True, send_messages=True)
                    await self.home_set(ctx, member, house_channel)
                await ctx.send("Initialization completed")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def home_setup(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild = ctx.guild
                role_channel_category = discord.utils.get(guild.categories, name=guild_data["rc_category_name"])
                house_category = discord.utils.get(guild.categories, name=guild_data["houses_category_name"])
                alive_role = discord.utils.get(guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(guild.roles, name=guild_data["sponsor_role_name"])
                if not role_channel_category:
                    await ctx.send("RoleChats category not found")
                    return
                if not house_category:
                    await ctx.send("Houses category not found")
                    return
                for role_channel in role_channel_category.text_channels:
                    alive_member = None
                    sponsor_member = None
                    for member in role_channel.members:
                        if alive_role in member.roles:
                            alive_member = member
                        if sponsor_role in member.roles:
                            sponsor_member = member
                    if alive_member:
                        for house_channel in house_category.text_channels:
                            permissions = house_channel.permissions_for(alive_member)
                            if permissions.read_messages and permissions.send_messages:
                                if sponsor_member:
                                    await house_channel.set_permissions(sponsor_member, read_messages=True, send_messages=True)
                                    await self.home_set(ctx, sponsor_member, house_channel)
                                break
                await ctx.send("Initialization completed")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    async def home_set(self, ctx, user: discord.Member = None, new_channel: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                if user is None:
                    if not category:
                        await ctx.send("Houses category not found")
                        return
                    members = ctx.channel.members
                    for member in members:
                        if alive_role in member.roles or alt_role in member.roles:
                            assigned_channel = None
                            for channel in category.channels:
                                if channel.permissions_for(member).send_messages:
                                    assigned_channel = channel
                                    break
                            if assigned_channel:
                                old_channel_id = guild_data["member_homes"].get(str(member.id))
                                if old_channel_id and old_channel_id != assigned_channel.id:
                                    old_channel = ctx.guild.get_channel(old_channel_id)
                                    if old_channel:
                                        old_msg = await old_channel.send(f"{member.mention} doesn't live here anymore")
                                        await old_msg.pin()
                                guild_data["member_homes"][str(member.id)] = assigned_channel.id
                                new_msg = await assigned_channel.send(f"{member.mention} now lives here")
                                await new_msg.pin()
                        elif sponsor_role in member.roles:
                            assigned_channel = None
                            for channel in category.channels:
                                if channel.permissions_for(member).send_messages:
                                    assigned_channel = channel
                                    break
                            if assigned_channel:
                                guild_data["member_homes"][str(member.id)] = assigned_channel.id
                    await ctx.channel.send("Done")
                else:
                    if new_channel is None:
                        if not category:
                            await ctx.send("Houses category not found")
                            return
                        assigned_channel = None
                        for channel in category.channels:
                            if channel.permissions_for(user).send_messages:
                                assigned_channel = channel
                                break
                        if assigned_channel:
                            old_channel_id = guild_data["member_homes"].get(str(user.id))
                            if old_channel_id and old_channel_id != assigned_channel.id:
                                old_channel = ctx.guild.get_channel(old_channel_id)
                                if old_channel:
                                    old_msg = await old_channel.send(f"{user.mention} doesn't live here anymore")
                                    await old_msg.pin()
                            guild_data["member_homes"][str(user.id)] = assigned_channel.id
                            if alive_role in user.roles or alt_role in user.roles:
                                new_msg = await assigned_channel.send(f"{user.mention} now lives here")
                                await new_msg.pin()
                            await ctx.channel.send("Done")
                    else:
                        old_channel_id = guild_data["member_homes"].get(str(user.id))
                        if old_channel_id and old_channel_id != new_channel.id:
                            old_channel = ctx.guild.get_channel(old_channel_id)
                            if old_channel:
                                old_msg = await old_channel.send(f"{user.mention} doesn't live here anymore")
                                await old_msg.pin()
                        guild_data["member_homes"][str(user.id)] = new_channel.id
                        if alive_role in user.roles or alt_role in user.roles:
                            new_msg = await new_channel.send(f"{user.mention} now lives here")
                            await new_msg.pin()
                        await ctx.channel.send("Done")
                save_guild_data(ctx.guild.id, guild_data)
            else:
                await ctx.channel.send("Guild data not loaded.")
        else:
            await ctx.channel.send("You don't have enough perms to use this command")

    async def home_mass_set(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                if not category:
                    await ctx.channel.send("Houses category not found.")
                    return
                for member in ctx.guild.members:
                    if alive_role in member.roles or alt_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                guild_data["member_homes"][str(member.id)] = channel.id
                                new_msg = await channel.send(f'{member.mention} now lives here')
                                await new_msg.pin()
                    elif sponsor_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                guild_data["member_homes"][str(member.id)] = channel.id
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.send('Done')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def home_delete(self, ctx, user: discord.Member = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
                if user is None:
                    members = ctx.channel.members
                    for member in members:
                        if alive_role in member.roles or alt_role in member.roles:
                            if str(member.id) in guild_data["member_homes"]:
                                old_house_id = guild_data["member_homes"].get(str(member .id))
                                old_house = ctx.guild.get_channel(old_house_id)
                                del guild_data["member_homes"][str(member.id)]
                                await ctx.send(f'{member.mention} is now homeless')
                                homeless_message = await old_house.send(f"{member.mention} doesn't live here anymore")
                                await homeless_message.pin()
                            else:
                                await ctx.send(f"{member.mention} doesn't have a home yet")
                        elif sponsor_role in member.roles:
                            if str(member.id) in guild_data["member_homes"]:
                                del guild_data["member_homes"][str(member.id)]
                else:
                    if str(user.id) in guild_data["member_homes"]:
                        del guild_data["member_homes"][str(user.id)]
                        await ctx.send(f'{user.mention} is now homeless')
                save_guild_data(ctx.guild.id, guild_data)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def return_home(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                embedq = discord.Embed(title="Confirm you want to bring everyone home", description="Click a button to confirm or cancel.", color=0xff3fb9, timestamp=datetime.now())
                embedq.set_footer(text="Village Game")
                confirm_view = View(timeout=60)
                async def confirm_callback(interaction):
                    if interaction.user == ctx.author:
                        await interaction.message.delete()
                        loading = await ctx.send("Bringing everyone home...")
                        await self.bring_everyone_home(ctx, guild_data)
                        await loading.delete()
                        embedy = discord.Embed(title="Confirm", description="Everyone has been brought home", color=discord.Color.green(), timestamp=datetime.now())
                        embedy.set_footer(text="Village Game")
                        await ctx.send(embed=embedy)
                    else:
                        await interaction.response.send_message("You can't confirm this action.", ephemeral=True)
                async def cancel_callback(interaction):
                    if interaction.user == ctx.author:
                        await interaction.message.delete()
                        embedn = discord.Embed(title="Canceled", description="Home return command was canceled", color=discord.Color.red(), timestamp=datetime.now())
                        embedn.set_footer(text="Village Game")
                        await ctx.send(embed=embedn) 
                    else:
                        await interaction.response.send_message("You can't cancel this action.", ephemeral=True)
                confirm_button = Button(label="✔Yes", style=discord.ButtonStyle.green)
                confirm_button.callback = confirm_callback
                cancel_button = Button(label="❌No", style=discord.ButtonStyle.red)
                cancel_button.callback = cancel_callback
                confirm_view.add_item(confirm_button)
                confirm_view.add_item(cancel_button)
                await ctx.send(embed=embedq, view=confirm_view)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def bring_everyone_home(self, ctx, guild_data):
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if not category:
            await ctx.send("Houses category not found")
            return
        for member in ctx.guild.members:
            if alive_role in member.roles or alt_role in member.roles:
                for channel in category.channels:
                    permissions = channel.permissions_for(member)
                    if permissions.send_messages:
                        await channel.set_permissions(member, overwrite=None)
                        await channel.send(f'{member.mention} Leaves')
            elif sponsor_role in member.roles:
                for channel in category.channels:
                    permissions = channel.permissions_for(member)
                    if permissions.send_messages:
                        await channel.set_permissions(member, overwrite=None)
        for member_id, channel_id in guild_data["member_homes"].items():
            member = ctx.guild.get_member(int(member_id))
            channel = ctx.guild.get_channel(int(channel_id))
            if member and channel:
                await channel.set_permissions(member, read_messages=True, send_messages=True)
                if alive_role in member.roles or alt_role in member.roles:
                    await channel.send(f'{member.mention} Joins')

    async def list_home(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                home_list = []
                for member_id, channel_id in guild_data["member_homes"].items():
                    member = ctx.guild.get_member(int(member_id))
                    channel = ctx.guild.get_channel(int(channel_id))
                    if member and channel:
                        home_list.append(f"{member.display_name}: {channel.name}")
                home_list_str = "\n".join(home_list)
                embed = discord.Embed(title="Home List", description=home_list_str, color=0xff3fb9, timestamp=datetime.now())
                await ctx.send(embed=embed)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def rolechat(self, ctx, type: str = None):
        if ctx.author.guild_permissions.administrator:
            if type.lower() == 'initialize':
                await self.rc_initialize(ctx)
            elif type.lower() == 'list':
                await self.rc_list(ctx)
            else:
                await ctx.send("This is not a valid command")
        else:
            ctx.send("You don't have enough perms to use this command")

    async def rc_initialize(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild = ctx.guild
                role_channel_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                members = [member for member in guild.members if alive_role in member.roles]
                numbers = list(range(1, len(members) + 1))
                random.shuffle(numbers)
                for i, member in enumerate(members):
                    role_chat_channel_name = str(numbers[i])
                    role_chat_channel = discord.utils.get(role_channel_category.channels, name=role_chat_channel_name)
                    if not role_chat_channel:
                        role_chat_channel = await role_channel_category.create_text_channel(role_chat_channel_name)
                    await role_chat_channel.set_permissions(member, read_messages=True, send_messages=True)
                await ctx.send("Initialization completed")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def rc_list(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild = ctx.guild
            guild_data = load_guild_data(guild.id)
            rc_list = []
            if guild_data:
                role_channel_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                if role_channel_category:
                    for channel in role_channel_category.channels:
                        channel_members = [f"{member.mention} `[{member.display_name}]`" for member in channel.members if alive_role in member.roles]
                        if channel_members:
                            rc_list.append(f"{channel.mention}: {', '.join(channel_members)}\n")
                rc_list_str = "\n".join(rc_list) if rc_list else "No members with the Alive role found."
                embed = discord.Embed(title="RCs List", description=rc_list_str, color=0xff3fb9, timestamp=datetime.now())
                await ctx.send(embed=embed)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command.")

    @commands.command()
    async def owner(self, ctx, house: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if house:
            perms = house.permissions_for(ctx.author)
            if not ctx.author.guild_permissions.administrator and not perms.read_messages:
                await ctx.send("You don't have enough perms to use this command.")
                return
        if house is None:
            house = ctx.channel
        house_id = house.id
        owners = []
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        for member_id, channel_id in guild_data["member_homes"].items():
            if channel_id == house_id:
                member = ctx.guild.get_member(int(member_id))
                if member and alive_role in member.roles:
                    owners.append(f"{member.mention} `[{member.display_name}]`")
        embed = discord.Embed(title=f"{house.name} Owners:", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        if owners:
            embed.add_field(name='Players:', value="\n".join(owners), inline=False)
        else:
            embed.add_field(name='Players:', value="No owners found in this house.", inline=False)
        await ctx.send(embed=embed)