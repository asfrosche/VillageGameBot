import discord
from discord.ext import commands
from cogs.data_utils import load_guild_data


class RcHome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="rchome", aliases=["rch", "rolechome", "whichhouse"])
    async def rchome(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))

        target = channel or ctx.channel
        if channel is not None and channel != ctx.channel:
            # Looking up another RoleChat's membership is staff-only, like .whorc @player.
            overseer = discord.utils.get(ctx.guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
            is_staff = ctx.author.guild_permissions.administrator or (overseer is not None and overseer in ctx.author.roles)
            if not is_staff:
                await ctx.send("Only staff can check another RoleChat. Use this command inside the RoleChat instead.", ephemeral=True)
                return
        if target.category not in (rc_cat, dead_rc, alt_cat):
            await ctx.send("Use this in a RoleChat or specify a RoleChat.", ephemeral=True)
            return

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        member_homes = guild_data.get("member_homes", {}) or {}

        players = []
        for m in target.members:
            if m.bot:
                continue
            if alive_role and alive_role in m.roles:
                players.append(m)
            elif alive_role is None:
                players.append(m)

        if not players:
            await ctx.send("No players found in that RoleChat.", ephemeral=True)
            return

        results = []
        for p in players:
            hid = member_homes.get(str(p.id))
            if not hid:
                results.append(f"{p.display_name}: No home set")
                continue
            house = ctx.guild.get_channel(int(hid))
            if house and houses_category and house.category == houses_category:
                results.append(f"{p.display_name}: {house.mention} ({house.name})")
            elif house:
                results.append(f"{p.display_name}: {house.mention} ({house.name})")
            else:
                results.append(f"{p.display_name}: Unknown house ({hid})")

        embed = discord.Embed(title=f"Home for {target.name}", description="\n".join(results), color=0xff3fb9)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(RcHome(bot))
