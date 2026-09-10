from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils import botc


class JinxCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="jinx", description="Look up jinxes for a BOTC role")
    @app_commands.describe(name="Role name")
    async def jinx(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        role = botc.get_role(name)
        if not role:
            await interaction.followup.send(
                f"Could not find a role matching `{name}`.",
                ephemeral=True,
            )
            return

        jinxes = botc.get_jinxes_for_role(role["name"])
        embed = botc.build_jinx_embed(role, jinxes)
        await interaction.followup.send(embed=embed)

    @commands.command(name="jinx", aliases=["botcjinx"])
    async def jinx_prefix(self, ctx: commands.Context, *, name: str):
        role = botc.get_role(name)
        if not role:
            await ctx.send(f"Could not find a role matching `{name}`.")
            return

        jinxes = botc.get_jinxes_for_role(role["name"])
        embed = botc.build_jinx_embed(role, jinxes)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(JinxCog(bot))
