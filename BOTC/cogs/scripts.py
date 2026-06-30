from __future__ import annotations

import asyncio
import io

import discord
from discord import app_commands
from discord.ext import commands

from utils import botc
from utils.script_image import generate_script_image

EDITION_KEYS = ["tb", "bmr", "snv"]


class ScriptsView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="TB", style=discord.ButtonStyle.primary)
    async def tb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_script(interaction, "tb")

    @discord.ui.button(label="BMR", style=discord.ButtonStyle.primary)
    async def bmr(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_script(interaction, "bmr")

    @discord.ui.button(label="SNV", style=discord.ButtonStyle.primary)
    async def snv(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_script(interaction, "snv")


def _script_download_url(edition_key: str) -> str:
    urls = {
        "tb": "https://botcscripts.com/script/35930/1.3.0/download",
        "bmr": "https://botcscripts.com/script/35931/1.3.0/download",
        "snv": "https://botcscripts.com/script/35932/1.3.0/download",
    }
    return urls.get(edition_key, "")


async def _make_script_embed_and_file(edition_key: str) -> tuple[discord.Embed, discord.File]:
    edition_name = botc.get_edition_name(edition_key)
    png_bytes = await asyncio.to_thread(generate_script_image, edition_key)
    file = discord.File(io.BytesIO(png_bytes), filename=f"{edition_key}.png")
    download_url = _script_download_url(edition_key)
    embed = discord.Embed(title=f"📜 {edition_name}", color=discord.Color.blue())
    embed.set_image(url=f"attachment://{edition_key}.png")
    embed.add_field(name="Download", value=f"[JSON]({download_url})", inline=True)
    return embed, file


async def _send_script(interaction: discord.Interaction, edition_key: str):
    await interaction.response.defer()
    embed, file = await _make_script_embed_and_file(edition_key)
    await interaction.followup.send(embed=embed, file=file)


class ScriptsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="scripts", description="View a BOTC script as an image")
    @app_commands.describe(edition="Edition: tb, bmr, or snv (default: tb with buttons)")
    async def scripts(self, interaction: discord.Interaction, edition: str | None = None):
        await interaction.response.defer()
        edition = edition.lower() if edition else None
        if edition:
            if edition not in EDITION_KEYS:
                await interaction.followup.send(f"Invalid edition `{edition}`. Use: tb, bmr, or snv.", ephemeral=True)
                return
            embed, file = await _make_script_embed_and_file(edition)
            await interaction.followup.send(embed=embed, file=file)
            return

        embed, file = await _make_script_embed_and_file("tb")
        view = ScriptsView(interaction.user.id)
        await interaction.followup.send(embed=embed, file=file, view=view)

    @commands.command(name="scripts", aliases=["botcscripts"])
    async def scripts_prefix(self, ctx: commands.Context, edition: str | None = None):
        if edition:
            edition = edition.lower()
            if edition not in EDITION_KEYS:
                await ctx.send(f"Invalid edition `{edition}`. Use: tb, bmr, or snv.")
                return
            async with ctx.typing():
                embed, file = await _make_script_embed_and_file(edition)
                await ctx.send(embed=embed, file=file)
            return

        async with ctx.typing():
            embed, file = await _make_script_embed_and_file("tb")
            view = ScriptsView(ctx.author.id)
            await ctx.send(embed=embed, file=file, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(ScriptsCog(bot))
