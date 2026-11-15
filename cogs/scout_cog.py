import discord
from discord.ext import commands
from cogs.data_utils import load_guild_data
from cogs.moving_cog import _find_house


class Scout(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="scout")
    async def scout(self, ctx, channel: discord.TextChannel = None):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command.", ephemeral=True)
            return

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.", ephemeral=True)
            return

        if channel is None:
            if ctx.channel.category and ctx.channel.category.name in [
                guild_data.get("rc_category_name"),
                guild_data.get("dead_rc_category_name"),
                guild_data.get("alt_category_name"),
            ]:
                channel = ctx.channel
            else:
                await ctx.send("You need to specify a rolechat: `.scout #rolechat`", ephemeral=True)
                return

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))

        if channel.category not in (rc_cat, dead_rc, alt_cat):
            await ctx.send(f"{channel.mention} is not a Role Chat.", ephemeral=True)
            return

        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))
        if not houses_category:
            await ctx.send("Houses category not found.", ephemeral=True)
            return

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alt_role_name"))
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("dead_role_name"))

        results = []
        seen = set()

        for member in channel.members:
            if member.bot or member.id in seen:
                continue
            seen.add(member.id)

            if not any(r and r in member.roles for r in [alive_role, sponsor_role, alt_role, dead_role]):
                continue

            house = None
            for ch in houses_category.channels:
                if not isinstance(ch, discord.TextChannel):
                    continue
                try:
                    if ch.permissions_for(member).send_messages:
                        house = ch
                        break
                except Exception:
                    continue

            if house:
                results.append(f"{member.display_name} → {house.mention}")
            else:
                results.append(f"{member.display_name} → No house")

        if not results:
            await ctx.send(f"No players found in {channel.mention}.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Scout - {channel.name}",
            description="\n".join(results),
            color=0x9b59b6,
        )
        embed.set_footer(text="Only houses (no private/public channels)")
        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Scout(bot))
