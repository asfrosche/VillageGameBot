import random
from utils.discord_safe import add_text_fields, category_family, next_family_name
import discord
import datetime
from datetime import datetime, timedelta, timezone
from discord.ext import commands
from cogs.data_utils import load_guild_data, save_guild_data

PUBLIC_CHANNEL_EMOJI = " \U0001f513"

# Discord allows at most 50 channels per category; moving into a full one fails with code 50035.
DISCORD_CATEGORY_LIMIT = 50
CATEGORY_FULL_CODE = 50035


async def move_channel_or_warn(channel, category):
    """Move *channel* into *category*. Returns a warning string if the category has no room, else None."""
    if category is None or channel.category is category:
        return None
    if len(category.channels) >= DISCORD_CATEGORY_LIMIT:
        return f"⚠️ **{category.name}** is full ({DISCORD_CATEGORY_LIMIT} channels), so {channel.mention} was not moved."
    try:
        await channel.edit(category=category)
    except discord.HTTPException as e:
        if getattr(e, "code", None) == CATEGORY_FULL_CODE:
            return f"⚠️ **{category.name}** is full, so {channel.mention} was not moved."
        raise
    return None


async def get_pc_category(guild, guild_data, pc_type="private"):
    """Return a PC category with room: the main one, an existing overflow, or a new overflow.

    Returns the last full category if creating an overflow fails, so callers can report it.
    """
    pc_type = (pc_type or "").lower()
    if pc_type in ["public", "publ"]:
        base_name = guild_data.get("publc_category_name") or "PUBLIC CHANNELS"
    else:
        base_name = guild_data.get("privc_category_name") or "PRIVATE CHANNELS"
    family = category_family(guild.categories, base_name)
    for cat in family:
        if len(cat.channels) < DISCORD_CATEGORY_LIMIT:
            return cat
    if not family:
        return None
    try:
        new_cat = await guild.create_category(next_family_name(guild.categories, base_name))
        await new_cat.set_permissions(guild.default_role, read_messages=False, mention_everyone=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False)
        return new_cat
    except Exception:
        return family[-1]


def role_pings(*roles):
    """Mention string for roles that exist; roles missing from the server are skipped."""
    return " ".join(role.mention for role in roles if role is not None)


async def announce_homeless(guild, house, member_id):
    """Post that a former resident no longer lives in *house*. Skipped if they have left the server."""
    try:
        member_obj = await guild.fetch_member(int(member_id))
    except discord.NotFound:
        return
    message = await house.send(f"{member_obj.mention} doesn't live here anymore")
    await message.pin()


async def get_old_pcs_category(guild, guild_data):
    """Return an OLD PCS category with room, creating an overflow category if every one is full."""
    base_name = guild_data.get("old_pcs_category_name") or "OLD PCS"
    family = category_family(guild.categories, base_name)
    for cat in family:
        if len(cat.channels) < DISCORD_CATEGORY_LIMIT:
            return cat
    if not family:
        return None
    try:
        new_cat = await guild.create_category(next_family_name(guild.categories, base_name))
        spec = discord.utils.get(guild.roles, name=guild_data.get("spectator_role_name", "Spectator"))
        if spec:
            await new_cat.set_permissions(spec, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False)
        await new_cat.set_permissions(guild.default_role, read_messages=False)
        return new_cat
    except Exception:
        return family[-1]


def _ensure_public_emoji(name: str) -> str:
    emoji = PUBLIC_CHANNEL_EMOJI.strip()
    stripped = name.rstrip()
    if stripped.endswith(emoji):
        return stripped
    return stripped + PUBLIC_CHANNEL_EMOJI


def _remove_public_emoji(name: str) -> str:
    emoji = PUBLIC_CHANNEL_EMOJI.strip()
    stripped = name.rstrip()
    if stripped.endswith(emoji):
        return stripped[: -len(emoji)].rstrip()
    return stripped


class Handling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_owners = {}

    @commands.command()
    async def decay(self, ctx, house: discord.TextChannel = None):
        """Move a house to the inaccessible category and remove its members."""
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
                    await announce_homeless(ctx.guild, house, m_id)
            if inaccessible_houses_category:
                warning = await move_channel_or_warn(house, inaccessible_houses_category)
                if warning:
                    await ctx.send(warning)
            if map_channel:    
                await map_channel.send(f"{house.name} is inaccessible")
            if ctx.channel is not house:
                await ctx.send('Done')
            if house.name in guild_data["houselist"]:
                guild_data["houselist"].remove(house.name)
            save_guild_data(ctx.guild.id, guild_data)
            estate_cog = self.bot.get_cog('Estate')
            if estate_cog:
                await estate_cog.update_estate_map(ctx.guild)
        else:
            await ctx.send("You don't have enough perms to use this command")

    explosion_gifs = ['https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUycm56ODBpaGI1dnV3aWZ5MGZ1cTBkMjByOTZ5NzBhYnUxbTcyMWRtNSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l1Etg54Au9BpEpp16/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUyZzljejNib3l2ODlzcTY5ZG9vMXB0N3pqMXZhNjg3ZzZtcmxoajltbyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/xT3i1esgYABOKDHQ3u/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUycGlhd3c5bHZ6cTY2OXduZG5ibGUxZnNrNzh1aXpxc3V5ZWd4aTJ6cCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3oKHWuYEenjTKqib9m/giphy.gif ', 'https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUydWlqbHNubGw4enY5bGRmOTc0djFubGhweHJ1bW81dzZ4bWlsMXM0ciZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/5bGYUuT3VEVLa/giphy.gif ', 'https://i.gifer.com/3Tt5.gif', 'https://media0.giphy.com/media/XUFPGrX5Zis6Y/giphy.gif', 'https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExMW9zNGR1N20wcHdleG5kcGZ5NDFmbDZ4dXFleHhnOHF3NGJ1amFneCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/7OYLjpt8E2W7S/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUyeXI1MnhvNGt0am84aDd0ajMxMnhkdnFzMHkxaThmY3VnN3Zmd3ppcyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/146BUR1IHbM6zu/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyc2NhdGc2MHN3MnBvcXE0dGdtc2Y0MmtpcWRvd3B0Zm12NnRxajloeCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/aDyTZoEowCf84/giphy.gif']

    @commands.command()
    async def destroy(self, ctx, house: discord.TextChannel = None):
        """Destroy a house and announce with an explosion GIF."""
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
                    await announce_homeless(ctx.guild, house, m_id)
            if inaccessible_houses_category:
                warning = await move_channel_or_warn(house, inaccessible_houses_category)
                if warning:
                    await ctx.send(warning)
            if announcements_channel:
                embed = discord.Embed(title=f"{house.name} gets destroyed", color=0xff3fb9, timestamp=datetime.now())
                embed.set_image(url=random_explosion_gif)
                embed.set_footer(text="Village Game")
                await announcements_channel.send(role_pings(alive_role, sponsor_role) or None, embed=embed)
            if map_channel:
                    await map_channel.send(f"{house.name} is inaccessible")
            if ctx.channel is not house:
                await ctx.send('Done')
            if house.name in guild_data["houselist"]:
                guild_data["houselist"].remove(house.name)
            save_guild_data(ctx.guild.id, guild_data)
            estate_cog = self.bot.get_cog('Estate')
            if estate_cog:
                await estate_cog.update_estate_map(ctx.guild)
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def fdestroy(self, ctx, house: discord.TextChannel = None):
        """Force-destroy a house instantly without member cleanup."""
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
            await announcements_channel.send(role_pings(alive_role, sponsor_role) or None, embed=embed)
        if map_channel:
            await map_channel.send(f"{house.name} is inaccessible")
        if house.name in guild_data["houselist"]:
            guild_data["houselist"].remove(house.name)
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.message.add_reaction("👍")
        estate_cog = self.bot.get_cog('Estate')
        if estate_cog:
            await estate_cog.update_estate_map(ctx.guild)

    rebuild_gifs = ['https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUycmU4YXZwMzNwcjFzZGMwdzVreG44a3poOGJqOTF4cTJ3cGk3N2Z1dCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/Rm1p7xp3Odl2o/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyc3R1NmZzZjZvN29zem4ydXR3aHVoNDBtbWtzdXBwd2NxNDNiOXUxaiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/xT8qB5POKfq8lGclkQ/giphy.gif', 'https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUybGQwZG1mdnFmbjN4ZGhlazhlbmZqMzg0MjRxZWppN3ZldHBpaGRseiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/OmfuBa7G55geGgC2Kn/giphy.gif', 'https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyN3c5aTNiNTA1OHZ3Y3piOGVjNTU3NjJ4a2diczRxdXpzcXkyaWs0ZyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/c5eqVJN7oNLTq/giphy.gif', 'https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUyOWR4bnY5NzRkZmtra3pvcjFhOTNrNjVzbmgzaDdtNDBvd3BvNTR2NCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/Mah9dFWo1WZX0WM62Q/giphy.gif', 'https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUyNGIzdzh6OXc4bTh0aXEyN3lncWM2ZmNmenc3Z2s3cm1jZ3VqN2MxdCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ZTans30ONaaIM/giphy.gif', 'https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyMTlqYmlvMnRwdmlwNGYyNGowMjA1MHZ4NjZrM2JjeGRlbzl6aDhkciZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3oEduHHt9xZMlUY9m8/giphy.gif']

    @commands.command()
    async def rebuild(self, ctx, house: discord.TextChannel = None):
        """Restore a destroyed or decayed house to the houses category."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if not guild_data:
                return await ctx.send("Guild data not loaded")
            random_rebuild_gif = random.choice(self.rebuild_gifs)
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name", ""))
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name", ""))
            houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name", ""))
            map_channel = discord.utils.get(ctx.guild.channels, name=guild_data.get("map_channel_name", ""))
            announcements_channel = discord.utils.get(ctx.guild.channels, name=guild_data.get("announcements_channel_name", ""))
            if house is None:
                house = ctx.channel
            if house.category is not houses_category:
                await house.edit(category=houses_category)
            if announcements_channel:
                embed = discord.Embed(title=f"{house.name} gets rebuilt", color=0xff3fb9, timestamp=datetime.now())
                embed.set_image(url=random_rebuild_gif)
                embed.set_footer(text="Village Game")
                await announcements_channel.send(role_pings(alive_role, sponsor_role) or None, embed=embed)
            if map_channel:
                await map_channel.send(f"{house.name} is accessible")
            if ctx.channel is not house:
                await ctx.send('Done')
            house_prefix = guild_data.get("house_prefix", "")
            house_name = house.name
            def _house_num(name):
                if house_prefix and name.startswith(house_prefix) and name[len(house_prefix):].isdigit():
                    return int(name[len(house_prefix):])
                return None
            house_number = _house_num(house_name)
            if house_number is not None:
                houselist = guild_data.get("houselist") or []
                houselist = [h for h in houselist if _house_num(h) != house_number]
                houselist.append(house_name)
                houselist.sort(key=lambda x: _house_num(x) or 0)
                guild_data["houselist"] = houselist
            save_guild_data(ctx.guild.id, guild_data)
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def newpc(self, ctx, pc_type: str, name: str, *rolechats: discord.TextChannel):
        """Create a new public or private PC with optional RC members."""
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
            publc_category = await get_pc_category(ctx.guild, guild_data, "public")
            if not publc_category:
                await ctx.send("Public category not found.")
                return
            if len(publc_category.channels) >= DISCORD_CATEGORY_LIMIT:
                await ctx.send(f"❌ **{publc_category.name}** is full ({DISCORD_CATEGORY_LIMIT} channels). Make room or add another public category.")
                return
            new_channel = await publc_category.create_text_channel(name=name)
        elif pc_type.lower() in ["private", "priv"]:
            privc_category = await get_pc_category(ctx.guild, guild_data, "private")
            if not privc_category:
                await ctx.send("Private category not found.")
                return
            if len(privc_category.channels) >= DISCORD_CATEGORY_LIMIT:
                await ctx.send(f"❌ **{privc_category.name}** is full ({DISCORD_CATEGORY_LIMIT} channels). Make room or add another private category.")
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
        """Close a PC by moving it to Old PCs and removing members."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if not guild_data:
                return await ctx.send("Guild data not loaded")
            old_pcs_category = await get_old_pcs_category(ctx.guild, guild_data)
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
            if spect_role:
                await chat.set_permissions(spect_role, read_messages=True, send_messages=False)
            save_guild_data(ctx.guild.id, guild_data)
            if old_pcs_category:
                if chat.category is not old_pcs_category:
                    try:
                        await chat.edit(category=old_pcs_category)
                    except discord.HTTPException as e:
                        if getattr(e, "code", None) == CATEGORY_FULL_CODE:
                            await ctx.send(f"⚠️ **{old_pcs_category.name}** is full, so {chat.mention} was closed but not moved.")
                        else:
                            pass
                    except Exception:
                        pass
            else:
                await ctx.send(f"⚠️ No OLD PCS category has room ({DISCORD_CATEGORY_LIMIT} channels each), so {chat.mention} was closed but not moved.")
            await ctx.send('Done')
            estate_cog = self.bot.get_cog('Estate')
            if estate_cog:
                await estate_cog.update_estate_map(ctx.guild)
        else:
            await ctx.send("You don't have enough perms to use this command")

    public_gifs = ['https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUyamhsdTh4dWFwdW02eHFldzN1aTUyNW9sdmpham12MGY3NWduMWRjayZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/5ZRBBjFsEjN9n8rQ65/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUydGo1ZnRjcDlpYXY0MHAzaG9xOTY4OWY4Zjl0bG1zZzB2N205eDBpZyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/yxwXI1zzm8dbgX9XVt/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUycW4waGFibnhvNjNpbXVxdWxmb3F3bXlxcjdqOWtqbm92NWpkcXl3dSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ieUnhMAQptDkfKc2LV/giphy.gif', 'https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUyZmF6aGZ6bGw4Nmo2YTJlZzVnbWZsZ3Q5eHN2aW94OWh4cXJnbWozdyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o6Mb9sgoEBjQomNDW/giphy.gif', 'https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUycjFmcXFnZXcycmFrOTJxdG9jMmlkbnhxcmR6ZHRuYnZqOWxlN3Z3YyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l2SpT5QO27LWaFHB6/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyamV4dnpndWlkcTF4aGtnbDN4ODEzb2tsaW1kMWRkNjZkdTBxNmxkMyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/TQmOxn9y3BoFG/giphy.gif', 'https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyaG5sZ3l5cG1iYmRlaW82eTB5dDd5dnB1NXFoNGJjam1jbzM0dzhhayZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/FDITqxKuHCIp1T5Kjf/giphy.gif']

    @commands.command()
    async def public(self, ctx, channel: discord.TextChannel = None):
        """Grant read-only access to a channel for all player roles."""
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
                public_name = _ensure_public_emoji(channel.name)
                if public_name != channel.name:
                    try:
                        await channel.edit(name=public_name)
                    except discord.HTTPException:
                        pass
                if announcements_channel:
                    embed=discord.Embed(title=f"{channel.name} is now public", color=0xff3fb9, timestamp=datetime.now())
                    embed.set_image(url=random_public_gif)
                    embed.set_footer(text="Village Game")
                    await announcements_channel.send(role_pings(alive_role, sponsor_role) or None, embed=embed) 
                await ctx.send('Done')
            else:
                await ctx.send('Guild data not loaded')
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def private(self, ctx, channel: discord.TextChannel = None):
        """Restrict a channel to default role only."""
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
                private_name = _remove_public_emoji(channel.name)
                if private_name != channel.name:
                    try:
                        await channel.edit(name=private_name)
                    except discord.HTTPException:
                        pass
                await ctx.send('Done')
            else:
                await ctx.send('Guild data not loaded')
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def setowner(self, ctx, channel1: discord.TextChannel, channel2: discord.TextChannel = None):
        """Set channel owners from members in another channel."""
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
        """Remove all non-owner members from a channel."""
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

    @commands.command()
    async def mergepc(self, ctx, pc1: discord.TextChannel, pc2: discord.TextChannel, name: str = None):
        """Merge members from two private channels into a new private channel."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send('Guild data not loaded')
            return

        privc_category = discord.utils.get(ctx.guild.categories, name=guild_data["privc_category_name"])
        if not privc_category:
            await ctx.send("Private Channels category not found.")
            return

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        log_channel = discord.utils.get(ctx.guild.channels, name=guild_data.get("log_channel_name"))

        eligible_roles = [alive_role, sponsor_role, alt_role, dead_role]
        seen_members = {}
        for source_pc in (pc1, pc2):
            for member in source_pc.members:
                if any(r in member.roles for r in eligible_roles if r):
                    seen_members[member.id] = member

        if not seen_members:
            await ctx.send("No eligible members found in either channel.")
            return

        if name is None:
            name = f"merged-{pc1.name}-{pc2.name}"

        new_channel = await privc_category.create_text_channel(name=name)

        for member in seen_members.values():
            await new_channel.set_permissions(member, read_messages=True, send_messages=True)
            await new_channel.send(f'{member.mention} Joins')
            if log_channel:
                embed = discord.Embed(title='Member added', description=f'{member.mention} `[{member.display_name}, {member.name}]`', color=0xff3fb9, timestamp=datetime.now())
                embed.add_field(name='Added To:', value=f"{new_channel.mention} `[{new_channel.name}]`", inline=False)
                embed.set_footer(text="Village Game")
                await log_channel.send(embed=embed)

        await ctx.send(f"Created {new_channel.mention} with **{len(seen_members)}** members from {pc1.mention} and {pc2.mention}.")

    @commands.command()
    async def decayinactive(self, ctx):
        """Show houses inactive >24h and prompt to decay them."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if not houses_category:
            return await ctx.send("Houses category not found.")
        now = discord.utils.utcnow()
        cutoff = now - timedelta(hours=24)
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        inactive = []
        skipped = []
        for channel in houses_category.text_channels:
            if any(alive_role in m.roles for m in channel.members):
                skipped.append(channel)
                continue
            last = None
            async for message in channel.history(limit=1, oldest_first=False):
                last = message.created_at
                break
            if last is None:
                inactive.append((channel, None))
            elif last < cutoff:
                inactive.append((channel, last))
        if not inactive:
            return await ctx.send("All house channels have had messages within the last 24 hours.")
        lines = []
        for ch, ts in sorted(inactive, key=lambda x: x[1] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
            if ts is None:
                lines.append(f"{ch.mention} → no messages ever")
            else:
                diff = now - ts
                total_secs = int(diff.total_seconds())
                h, rem = divmod(total_secs, 3600)
                m = rem // 60
                lines.append(f"{ch.mention} → {h:02d}:{m:02d} hours")
        if skipped:
            lines.append("")
            lines.append("⏭️ Skipped (players inside):")
            for ch in skipped:
                lines.append(f"  {ch.mention}")
        embed = discord.Embed(
            title="🏠 Inactive Houses (24h+)",
            description="\n".join(lines),
            color=0xff3fb9,
            timestamp=datetime.now()
        )
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)
        await ctx.send(f"Decay these {len(inactive)} houses? Reply with **yes** to confirm, anything else to cancel.")
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        try:
            response = await self.bot.wait_for("message", timeout=30, check=check)
        except asyncio.TimeoutError:
            return await ctx.send("Action cancelled (timeout).")
        if response.content.lower() != "yes":
            return await ctx.send("Action cancelled.")
        inaccessible_category = discord.utils.get(ctx.guild.categories, name=guild_data["inaccessible_houses_category_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
        map_channel = discord.utils.get(ctx.guild.channels, name=guild_data["map_channel_name"])
        announcements_channel = discord.utils.get(ctx.guild.channels, name=guild_data["announcements_channel_name"])
        decayed_names = []
        for house, _ in inactive:
            for member in house.members:
                perms = house.permissions_for(member)
                if perms.send_messages:
                    if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                        await house.send(f"{member.mention} leaves")
                        await house.set_permissions(member, overwrite=None)
                    elif sponsor_role in member.roles:
                        await house.set_permissions(member, overwrite=None)
            homeless = [m_id for m_id, c_id in guild_data["member_homes"].items() if c_id == str(house.id)]
            for m_id in homeless:
                del guild_data["member_homes"][m_id]
                try:
                    member_obj = await ctx.guild.fetch_member(int(m_id))
                    msg = await house.send(f"{member_obj.mention} doesn't live here anymore")
                    await msg.pin()
                except discord.NotFound:
                    pass
            if inaccessible_category:
                warning = await move_channel_or_warn(house, inaccessible_category)
                if warning:
                    await ctx.send(warning)
            if map_channel:
                await map_channel.send(f"{house.name} is inaccessible")
            if house.name in guild_data["houselist"]:
                guild_data["houselist"].remove(house.name)
            decayed_names.append(house.name)
        save_guild_data(ctx.guild.id, guild_data)
        if announcements_channel:
            embed = discord.Embed(
                title="🏚️ Houses Decayed",
                description="The following houses decayed after 24h+ of inactivity:\n" + "\n".join(f"• {name}" for name in decayed_names),
                color=0xff3fb9,
                timestamp=datetime.now()
            )
            embed.set_footer(text="Village Game")
            await announcements_channel.send(embed=embed)
        estate_cog = self.bot.get_cog('Estate')
        if estate_cog:
            await estate_cog.update_estate_map(ctx.guild)
        await ctx.send(f"Decayed {len(inactive)} houses.")