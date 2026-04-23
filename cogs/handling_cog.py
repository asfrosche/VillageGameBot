import random
import discord
import datetime
from datetime import datetime
from discord.ext import commands
from cogs.data_utils import load_guild_data, save_guild_data

class Handling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_owners = {}

    @commands.command()
    async def decay(self, ctx, house: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            inaccessible_houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["inaccessible_houses_category_name"])
            map_channel = discord.utils.get(ctx.guild.channels, name=guild_data["map_channel_name"])
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            if house is None:
                house = ctx.channel
            members = house.members
            for member in members:
                permissions = house.permissions_for(member)
                if permissions.send_messages:
                    if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                        await house.send(f"{member.mention} leaves")
                        await house.set_permissions(member, overwrite=None)
                    elif sponsor_role in member.roles:
                        await house.set_permissions(member, overwrite=None)
            members_to_delete = [m_id for m_id, c_id in guild_data["member_homes"].items() if c_id == str(house.id)]
            if members_to_delete:
                for m_id in members_to_delete:
                    del guild_data["member_homes"][m_id]
                    member_obj = await ctx.guild.fetch_member(int(m_id))
                    message = await house.send(f"{member_obj.mention} doesn't live here anymore")
                    await message.pin()
            if inaccessible_houses_category:
                if house.category is not inaccessible_houses_category:
                    await house.edit(category=inaccessible_houses_category)
            if map_channel:    
                await map_channel.send(f"{house.name} is inaccessible")
            if ctx.channel is not house:
                await ctx.send('Done')
            if house.name in guild_data["houselist"]:
                guild_data["houselist"].remove(house.name)
            save_guild_data(ctx.guild.id, guild_data)
        else:
            await ctx.send("You don't have enough perms to use this command")

    explosion_gifs = ['https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUycm56ODBpaGI1dnV3aWZ5MGZ1cTBkMjByOTZ5NzBhYnUxbTcyMWRtNSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l1Etg54Au9BpEpp16/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUyZzljejNib3l2ODlzcTY5ZG9vMXB0N3pqMXZhNjg3ZzZtcmxoajltbyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/xT3i1esgYABOKDHQ3u/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUycGlhd3c5bHZ6cTY2OXduZG5ibGUxZnNrNzh1aXpxc3V5ZWd4aTJ6cCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3oKHWuYEenjTKqib9m/giphy.gif ', 'https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUydWlqbHNubGw4enY5bGRmOTc0djFubGhweHJ1bW81dzZ4bWlsMXM0ciZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/5bGYUuT3VEVLa/giphy.gif ', 'https://i.gifer.com/3Tt5.gif', 'https://media0.giphy.com/media/XUFPGrX5Zis6Y/giphy.gif', 'https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExMW9zNGR1N20wcHdleG5kcGZ5NDFmbDZ4dXFleHhnOHF3NGJ1amFneCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/7OYLjpt8E2W7S/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUyeXI1MnhvNGt0am84aDd0ajMxMnhkdnFzMHkxaThmY3VnN3Zmd3ppcyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/146BUR1IHbM6zu/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyc2NhdGc2MHN3MnBvcXE0dGdtc2Y0MmtpcWRvd3B0Zm12NnRxajloeCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/aDyTZoEowCf84/giphy.gif']

    @commands.command()
    async def destroy(self, ctx, house: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if not guild_data:
                return await ctx.send("Guild data not loaded")
            random_explosion_gif = random.choice(self.explosion_gifs)
            inaccessible_houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["inaccessible_houses_category_name"])
            map_channel = discord.utils.get(ctx.guild.channels, name=guild_data["map_channel_name"])
            announcements_channel = discord.utils.get(ctx.guild.channels, name=guild_data["announcements_channel_name"])
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            if house is None:
                house = ctx.channel
            members = house.members
            for member in members:
                permissions = house.permissions_for(member)
                if permissions.send_messages:
                    if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                        await house.send(f"{member.mention} leaves")
                        await house.set_permissions(member, overwrite=None)
                    elif sponsor_role in member.roles:
                        await house.set_permissions(member, overwrite=None)
            members_to_delete = [m_id for m_id, c_id in guild_data["member_homes"].items() if c_id == str(house.id)]
            if members_to_delete:
                for m_id in members_to_delete:
                    del guild_data["member_homes"][m_id]
                    member_obj = await ctx.guild.fetch_member(int(m_id))
                    message = await house.send(f"{member_obj.mention} doesn't live here anymore")
                    await message.pin()
            if inaccessible_houses_category:
                if house.category is not inaccessible_houses_category:
                    await house.edit(category=inaccessible_houses_category)
            if announcements_channel:
                embed = discord.Embed(title=f"{house.name} gets destroyed", color=0xff3fb9, timestamp=datetime.now())
                embed.set_image(url=random_explosion_gif)
                embed.set_footer(text="Village Game")
                await announcements_channel.send(f"{alive_role.mention} {sponsor_role.mention}", embed=embed)
            if map_channel:
                    await map_channel.send(f"{house.name} is inaccessible")
            if ctx.channel is not house:
                await ctx.send('Done')
            if house.name in guild_data["houselist"]:
                guild_data["houselist"].remove(house.name)
            save_guild_data(ctx.guild.id, guild_data)
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def fdestroy(self, ctx, house: discord.TextChannel = None):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded")
        if house is None:
            house = ctx.channel
        random_explosion_gif = random.choice(self.explosion_gifs)
        announcements_channel = discord.utils.get(ctx.guild.channels, name=guild_data["announcements_channel_name"])
        map_channel = discord.utils.get(ctx.guild.channels, name=guild_data["map_channel_name"])
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        if announcements_channel:
            embed = discord.Embed(title=f"{house.name} gets destroyed", color=0xff3fb9, timestamp=datetime.now())
            embed.set_image(url=random_explosion_gif)
            embed.set_footer(text="Village Game")
            await announcements_channel.send(f"{alive_role.mention} {sponsor_role.mention}", embed=embed)
        if map_channel:
            await map_channel.send(f"{house.name} is inaccessible")
        if house.name in guild_data["houselist"]:
            guild_data["houselist"].remove(house.name)
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.message.add_reaction("👍")

    rebuild_gifs = ['https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUycmU4YXZwMzNwcjFzZGMwdzVreG44a3poOGJqOTF4cTJ3cGk3N2Z1dCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/Rm1p7xp3Odl2o/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyc3R1NmZzZjZvN29zem4ydXR3aHVoNDBtbWtzdXBwd2NxNDNiOXUxaiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/xT8qB5POKfq8lGclkQ/giphy.gif', 'https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUybGQwZG1mdnFmbjN4ZGhlazhlbmZqMzg0MjRxZWppN3ZldHBpaGRseiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/OmfuBa7G55geGgC2Kn/giphy.gif', 'https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyN3c5aTNiNTA1OHZ3Y3piOGVjNTU3NjJ4a2diczRxdXpzcXkyaWs0ZyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/c5eqVJN7oNLTq/giphy.gif', 'https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUyOWR4bnY5NzRkZmtra3pvcjFhOTNrNjVzbmgzaDdtNDBvd3BvNTR2NCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/Mah9dFWo1WZX0WM62Q/giphy.gif', 'https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUyNGIzdzh6OXc4bTh0aXEyN3lncWM2ZmNmenc3Z2s3cm1jZ3VqN2MxdCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ZTans30ONaaIM/giphy.gif', 'https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyMTlqYmlvMnRwdmlwNGYyNGowMjA1MHZ4NjZrM2JjeGRlbzl6aDhkciZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3oEduHHt9xZMlUY9m8/giphy.gif']

    @commands.command()
    async def rebuild(self, ctx, house: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if not guild_data:
                return await ctx.send("Guild data not loaded")
            random_rebuild_gif = random.choice(self.rebuild_gifs)
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
            map_channel = discord.utils.get(ctx.guild.channels, name=guild_data["map_channel_name"])
            announcements_channel = discord.utils.get(ctx.guild.channels, name=guild_data["announcements_channel_name"])
            if house is None:
                house = ctx.channel
            if house.category is not houses_category:
                await house.edit(category=houses_category)
            if announcements_channel:
                embed = discord.Embed(title=f"{house.name} gets rebuilt", color=0xff3fb9, timestamp=datetime.now())
                embed.set_image(url=random_rebuild_gif)
                embed.set_footer(text="Village Game")
                await announcements_channel.send(f"{alive_role.mention} {sponsor_role.mention}", embed=embed)
            if map_channel:
                await map_channel.send(f"{house.name} is accessible")
            if ctx.channel is not house:
                await ctx.send('Done')
            house_prefix = guild_data["house_prefix"]
            house_name = house.name
            house_number = int(house_name.replace(house_prefix, ""))
            guild_data["houselist"] = [h for h in guild_data["houselist"] if int(h.replace(house_prefix, "")) != house_number]
            guild_data["houselist"].append(house_name)
            guild_data["houselist"].sort(key=lambda x: int(x.replace(house_prefix, "")))  
            save_guild_data(ctx.guild.id, guild_data)
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def newpc(self, ctx, pc_type: str, name: str, *rolechats: discord.TextChannel):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        if not pc_type or not name:
            await ctx.send("Required inputs missing, please check command usage.")
            return
        new_channel = None
        if pc_type.lower() in ["public", "publ"]:
            publc_category = discord.utils.get(ctx.guild.categories, name=guild_data["publc_category_name"])
            if not publc_category:
                await ctx.send("Public category not found.")
                return
            new_channel = await publc_category.create_text_channel(name=name)
        elif pc_type.lower() in ["private", "priv"]:
            privc_category = discord.utils.get(ctx.guild.categories, name=guild_data["privc_category_name"])
            if not privc_category:
                await ctx.send("Private category not found.")
                return
            new_channel = await privc_category.create_text_channel(name=name)
        else:
            await ctx.send("Invalid pc_type. Please choose 'public' or 'private'")
            return
        if rolechats:
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
            for rolechat in rolechats:
                members = rolechat.members
                for member in members:
                    if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                        await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                        await new_channel.send(f'{member.mention} Joins')
                        embed = discord.Embed(title='Member added', description=f'{member.mention} `[{member.display_name}, {member.name}]`', color=0xff3fb9, timestamp=datetime.now())
                        embed.add_field(name='Added To:', value=f"{new_channel.mention} `[{new_channel.name}]`", inline=False)
                        embed.set_footer(text="Village Game")
                        if log_channel:
                            await log_channel.send(embed=embed)
                    elif sponsor_role in member.roles:
                        await new_channel.set_permissions(member, read_messages=True, send_messages=True)
        await ctx.send(f"Channel {new_channel.mention} created successfully.")

    @commands.command()
    async def close(self, ctx, chat: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            old_pcs_category = discord.utils.get(ctx.guild.categories, name=guild_data["old_pcs_category_name"])
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            spect_role = discord.utils.get(ctx.guild.roles, name=guild_data["spectator_role_name"])
            roles = [alive_role, sponsor_role, alt_role, dead_role]
            if chat is None:
                chat = ctx.channel
            members = chat.members
            for member in members:
                permissions = chat.permissions_for(member)
                if permissions.send_messages:
                    if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                        await chat.send(f"{member.mention} leaves")
                        await chat.set_permissions(member, overwrite=None)
                    elif sponsor_role in member.roles:
                        await chat.set_permissions(member, overwrite=None)
            await chat.send('Closes')
            for role in roles:
                permissions = chat.permissions_for(role)
                if permissions.read_messages:
                    await chat.set_permissions(role, overwrite=None)
            await chat.set_permissions(ctx.guild.default_role, read_messages=False)
            await chat.set_permissions(spect_role, read_messages=True, send_messages=False)
            await chat.edit(category=old_pcs_category)
            await ctx.send('Done')
        else:
            await ctx.send("You don't have enough perms to use this command")

    public_gifs = ['https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUyamhsdTh4dWFwdW02eHFldzN1aTUyNW9sdmpham12MGY3NWduMWRjayZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/5ZRBBjFsEjN9n8rQ65/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUydGo1ZnRjcDlpYXY0MHAzaG9xOTY4OWY4Zjl0bG1zZzB2N205eDBpZyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/yxwXI1zzm8dbgX9XVt/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUycW4waGFibnhvNjNpbXVxdWxmb3F3bXlxcjdqOWtqbm92NWpkcXl3dSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ieUnhMAQptDkfKc2LV/giphy.gif', 'https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUyZmF6aGZ6bGw4Nmo2YTJlZzVnbWZsZ3Q5eHN2aW94OWh4cXJnbWozdyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o6Mb9sgoEBjQomNDW/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUycjFmcXFnZXcycmFrOTJxdG9jMmlkbnhxcmR6ZHRuYnZqOWxlN3Z3YyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l2SpT5QO27LWaFHB6/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyamV4dnpndWlkcTF4aGtnbDN4ODEzb2tsaW1kMWRkNjZkdTBxNmxkMyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/TQmOxn9y3BoFG/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyaG5sZ3l5cG1iYmRlaW82eTB5dDd5dnB1NXFoNGJjam1jbzM0dzhhayZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/FDITqxKuHCIp1T5Kjf/giphy.gif']

    @commands.command()
    async def public(self, ctx, channel: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if channel is None:
                    channel = ctx.channel
                overwrite = discord.PermissionOverwrite(read_messages=True, send_messages=False, add_reactions=False)
                announcements_channel = discord.utils.get(ctx.guild.channels, name=guild_data["announcements_channel_name"])
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
                random_public_gif = random.choice(self.public_gifs)
                if alive_role:
                    await channel.set_permissions(alive_role, overwrite=overwrite)
                if sponsor_role:
                    await channel.set_permissions(sponsor_role, overwrite=overwrite)
                if dead_role:
                    await channel.set_permissions(dead_role, overwrite=overwrite)
                if announcements_channel:
                    embed=discord.Embed(title=f"{channel.name} is now public", color=0xff3fb9, timestamp=datetime.now())
                    embed.set_image(url=random_public_gif)
                    embed.set_footer(text="Village Game")
                    await announcements_channel.send(f"{alive_role.mention} {sponsor_role.mention}", embed=embed) 
                await ctx.send('Done')
            else:
                await ctx.send('Guild data not loaded')
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def private(self, ctx, channel: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if channel is None:
                    channel = ctx.channel
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
                overwrite = discord.PermissionOverwrite(read_messages=False)
                await channel.set_permissions(alive_role, overwrite=None)
                await channel.set_permissions(sponsor_role, overwrite=None)
                await channel.set_permissions(dead_role, overwrite=None)
                await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
                await ctx.send('Done')
            else:
                await ctx.send('Guild data not loaded')
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def setowner(self, ctx, channel1: discord.TextChannel, channel2: discord.TextChannel = None):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send('Guild data not loaded')
            return
        if channel2 is None:
            channel2 = ctx.channel
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        owners = []
        for member in channel2.members:
            if alive_role in member.roles or sponsor_role in member.roles or alt_role in member.roles:
                owners.append(member.id)
        self.channel_owners[channel1.id] = owners
        if owners:
            owner_mentions = ", ".join([f"<@{owner}>" for owner in owners])
            await ctx.send(f"Saved owners for {channel1.mention}: {owner_mentions}")
        else:
            await ctx.send(f"No eligible owners found in {channel2.mention}")

    @commands.command()
    async def end(self, ctx, channel: discord.TextChannel = None):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send('Guild data not loaded')
            return
        if channel is None:
            channel = ctx.channel
        if channel.id not in self.channel_owners:
            return await ctx.send(f"No owners set for {channel.mention}. Use `.setowner` first.")
        owners = self.channel_owners[channel.id]
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        overwrites = channel.overwrites
        removed_anyone = False
        for target, perms in overwrites.items():
            if isinstance(target, discord.Member):
                if target.id in owners:
                    continue
                if alive_role in target.roles or sponsor_role in target.roles or alt_role in target.roles:
                    await channel.set_permissions(target, overwrite=None)
                    removed_anyone = True
                    if not sponsor_role in target.roles:
                        await ctx.send(f"{target.mention} leaves")
        if not removed_anyone:
            await ctx.send("No non-owner permissions found.")