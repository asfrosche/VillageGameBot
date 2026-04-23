import discord
import datetime
from datetime import datetime
from discord.ext import commands
from cogs.data_utils import load_guild_data, save_guild_data, add_player, remove_player, get_team_players

class Lists(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=["p"])
    async def playerlist(self, ctx, format: str = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        alive_role_name = guild_data.get("alive_role_name")
        if not alive_role_name:
            await ctx.send("Alive role name not found in configuration.")
            return
        alive_role = discord.utils.get(ctx.guild.roles, name=alive_role_name)
        if not alive_role:
            await ctx.send("Alive role not found in this server.")
            return
        alive_members = [m for m in ctx.guild.members if alive_role in m.roles and not m.bot]
        alive_members = sorted(alive_members, key=lambda m: m.display_name.lower())
        if format in ["mention", "tag"]:
            playerlist = "\n".join(m.mention for m in alive_members) or "*None*"
        else:
            playerlist = "\n".join(m.display_name for m in alive_members) or "*None*"
        embed = discord.Embed(title="Alive Player List", description=playerlist, color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text=f"Village Game • {len(alive_members)} alive players in total")
        await ctx.send(embed=embed)

    @commands.command()
    async def sponsorlist(self, ctx, format: str = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))
        if not sponsor_role:
            await ctx.send("Sponsor role not found in this server.")
            return
        sponsor_members = [m for m in ctx.guild.members if sponsor_role in m.roles and not m.bot]
        sponsor_members = sorted(sponsor_members, key=lambda m: m.display_name.lower())
        if format in ["mention", "tag"]:
            sponsor_playerlist = "\n".join(m.mention for m in sponsor_members) or "*None*"
        else:
            sponsor_playerlist = "\n".join(m.display_name for m in sponsor_members) or "*None*"
        embed = discord.Embed(title="Sponsors List", description=sponsor_playerlist, color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text=f"Village Game • {len(sponsor_members)} sponsors in total")
        await ctx.send(embed=embed)

    @commands.command()
    async def setuphouselist(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild_data["houselist"] = []
                houses_category_name = guild_data.get("houses_category_name")
                houses_category = discord.utils.get(ctx.guild.categories, name=houses_category_name)
                if houses_category is not None:
                    for channel in houses_category.channels:
                        guild_data["houselist"].append(channel.name)
                    save_guild_data(ctx.guild.id, guild_data)
                    await ctx.send("House list setup successfully.")
                else:
                    await ctx.send(f'Category "{houses_category_name}" not found.')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command()
    async def houselistadd(self, ctx, house: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if house is None:
                    house = ctx.channel
                if house:
                    house_prefix = guild_data["house_prefix"]
                    house_name = house.name
                    house_number = int(house_name.replace(house_prefix, ""))
                    guild_data["houselist"] = [h for h in guild_data["houselist"] if int(h.replace(house_prefix, "")) != house_number]
                    guild_data["houselist"].append(house_name)
                    guild_data["houselist"].sort(key=lambda x: int(x.replace(house_prefix, "")))
                else:
                    await ctx.channel.send("Channel not found")
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.channel.send(f"{house.mention} added succesfully in house list")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command()
    async def houselistremove(self, ctx, house: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if house is None:
                    house = ctx.channel
                if house.name in guild_data["houselist"]:
                    guild_data["houselist"].remove(house.name)
                else:
                    await ctx.channel.send(f"{house.menion} not found in house list")
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.channel.send(f"{house.mention} removed succesfully from house list")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command(aliases=["hl"])
    async def houselist(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        if "houselist" in guild_data:
            houses = guild_data["houselist"]
            houses_list_str = "\n".join(houses)
            embed = discord.Embed(title=f"Visitable houses:", description=houses_list_str, color=0xff3fb9, timestamp=datetime.now())
            embed.set_footer(text=f"Village Game • {len(houses)} visitable houses in total")
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"House list not found")

    @commands.command(aliases=["d"])
    async def deadlist(self, ctx, action: str = None, player: str = None, team: str = None, *, role: str = None):
        if action is None:
            embed = discord.Embed(title="Deadlist", color=0xff3fb9, timestamp=datetime.now())
            embed.set_footer(text="Village Game")
            teams = ["village", "evil", "neutral", "rk", "corrupted"]
            for t in teams:
                results = get_team_players(t, ctx.guild.id)
                if results:
                    team_list = "\n".join([f"**{row[0]}** - {row[1]}" for row in results])
                    embed.add_field(name=f"**{t.capitalize()}**", value=team_list, inline=False)
            await ctx.send(embed=embed)
        elif action == "add":
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("You don't have enough permissions to use this command.")
                return
            if player and team and role:
                team = team.lower()
                if team in ["vill", "village", "v", "good"]:
                    team = "village"
                elif team in ["evil", "e", "bad"]:
                    team = "evil"
                elif team in ["neutral", "n", "solo", "s"]:
                    team = "neutral"
                elif team in ["rk", "r", "lms"]:
                    team = "rk"
                elif team in ["corrupted", "corr", "unk", "?", "???", "c"]:
                	team = "corrupted"
                else:
                    await ctx.send("Invalid team. Use Village, Evil, Neutral, Rk or Corrupted.")
                    return
                add_player(player, team, role, ctx.guild.id)
                await ctx.send(f"{player} added to Deadlist")
            else:
                await ctx.send("You have to fill all inputs: player, team, role.")
        elif action == "remove":
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("You don't have enough permissions to use this command.")
                return
            if player:
                remove_player(player, ctx.guild.id)
                await ctx.send(f"{player} removed from Deadlist.")
            else:
                await ctx.send("No player specified.")
        elif action == 'edit':
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("You don't have enough permissions to use this command.")
                return
            if player and team and role:
                remove_player(player, ctx.guild.id)
                team = team.lower()
                if team in ["vill", "village", "v", "good"]:
                    team = "village"
                elif team in ["evil", "e", "bad"]:
                    team = "evil"
                elif team in ["neutral", "n", "solo", "s"]:
                    team = "neutral"
                elif team in ["rk", "r", "lms"]:
                    team = "rk"
                elif team in ["corrupted", "corr", "unk", "?", "???", "c"]:
                    team = "corrupted"
                else:
                    ctx.send("Invalid team. Use Village, Evil, Neutral, Rk or Corrupted.")
                    return
                add_player(player, team, role, ctx.guild.id)
                await ctx.send(f"{player} edited in deadlist.")
            else:
                await ctx.send("You have to fill all inputs: player, team, role.")

    @commands.command(name='map')
    async def map_command(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        map_channel = discord.utils.get(ctx.guild.channels, name=guild_data["map_channel_name"])
        if not map_channel:
            await ctx.send("Map channel not found")
            return
        pinned_messages = await map_channel.pins()
        if not pinned_messages:
            await ctx.send(f"There are no pinned messages in {map_channel.mention}")
            return
        first_pinned = pinned_messages[0]
        image_url = None
        if first_pinned.attachments:
            for att in first_pinned.attachments:
                if att.content_type and att.content_type.startswith('image/'):
                    image_url = att.url
                    break
                fname = att.filename.lower()
                if fname.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                    image_url = att.url
                    break
        if image_url is None and first_pinned.embeds:
            for embed in first_pinned.embeds:
                if embed.image and embed.image.url:
                    image_url = embed.image.url
                    break
                if embed.thumbnail and embed.thumbnail.url:
                    image_url = embed.thumbnail.url
                    break
        if image_url is None:
            await ctx.send(f"First pinned message in {map_channel.mention} isn't a picture")
            return
        embed = discord.Embed(title="Map", description=f"{map_channel.mention}", color=0xff3fb9, timestamp=datetime.now())
        embed.set_image(url=image_url)
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)