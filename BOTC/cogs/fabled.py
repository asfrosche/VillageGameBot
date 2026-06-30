from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils import botc


class FabledCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="fabled", description="Look up a BOTC fabled character")
    @app_commands.describe(name="Fabled name")
    async def fabled(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        fabled = botc.get_fabled(name)
        if not fabled:
            await interaction.followup.send(
                f"Could not find a fabled matching `{name}`.",
                ephemeral=True,
            )
            return

        embed = botc.build_fabled_embed(fabled)
        await interaction.followup.send(embed=embed)

    @commands.command(name="fabled", aliases=["botcfabled"])
    async def fabled_prefix(self, ctx: commands.Context, *, name: str):
        fabled = botc.get_fabled(name)
        if not fabled:
            await ctx.send(f"Could not find a fabled matching `{name}`.")
            return

        embed = botc.build_fabled_embed(fabled)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(FabledCog(bot))
