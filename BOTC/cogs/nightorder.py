from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import botc

EDITION_ROLES: dict[str, list[dict]] = {}
for r in botc.ALL_ROLES:
    ed = r.get("edition", "")
    if ed:
        EDITION_ROLES.setdefault(ed, []).append(r)

NIGHT_ORDER_EDITIONS = {
    "tb": "Trouble Brewing",
    "bmr": "Bad Moon Rising",
    "snv": "Sects & Violets",
}

EDITION_KEYS = list(NIGHT_ORDER_EDITIONS.keys())


class NightOrderView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="TB", style=discord.ButtonStyle.primary)
    async def tb(self, interaction: discord.Interaction, button: discord.ui.Button):
        embeds = _build_night_embeds("tb")
        await interaction.response.edit_message(embeds=embeds)

    @discord.ui.button(label="BMR", style=discord.ButtonStyle.primary)
    async def bmr(self, interaction: discord.Interaction, button: discord.ui.Button):
        embeds = _build_night_embeds("bmr")
        await interaction.response.edit_message(embeds=embeds)

    @discord.ui.button(label="SNV", style=discord.ButtonStyle.primary)
    async def snv(self, interaction: discord.Interaction, button: discord.ui.Button):
        embeds = _build_night_embeds("snv")
        await interaction.response.edit_message(embeds=embeds)


def _get_night_roles(edition_key: str, night_key: str) -> list[dict]:
    roles = EDITION_ROLES.get(edition_key, [])
    result = []
    for r in roles:
        order = r.get(night_key, 0)
        if order and isinstance(order, int) and order > 0:
            if r["team"] != "fabled" and r["team"] != "traveler":
                result.append((order, r))
    result.sort(key=lambda x: x[0])
    return [r for _, r in result]


def _build_night_embeds(edition_key: str) -> list[discord.Embed]:
    edition_name = NIGHT_ORDER_EDITIONS.get(edition_key, edition_key.upper())

    first = _get_night_roles(edition_key, "firstNight")
    other = _get_night_roles(edition_key, "otherNight")

    embeds = []

    if first:
        e = discord.Embed(
            title=f"🌙 {edition_name} — First Night",
            color=discord.Color.dark_blue(),
        )
        for i, r in enumerate(first, 1):
            emoji = botc.team_emoji(r["team"])
            e.add_field(
                name=f"{i}. {emoji} {r['name']}",
                value=r.get("firstNightReminder", r["ability"]),
                inline=False,
            )
        embeds.append(e)

    if other:
        e = discord.Embed(
            title=f"🌙 {edition_name} — Other Nights",
            color=discord.Color.dark_blue(),
        )
        for i, r in enumerate(other, 1):
            emoji = botc.team_emoji(r["team"])
            e.add_field(
                name=f"{i}. {emoji} {r['name']}",
                value=r.get("otherNightReminder", r["ability"]),
                inline=False,
            )
        embeds.append(e)

    if not embeds:
        embeds.append(
            discord.Embed(
                title=f"🌙 {edition_name}",
                description="No night order data available.",
                color=discord.Color.dark_blue(),
            )
        )

    return embeds


class NightOrderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="nightorder", description="Display night order for an edition")
    @app_commands.describe(edition="Edition: tb, bmr, or snv (default: tb with buttons)")
    async def nightorder(self, interaction: discord.Interaction, edition: str | None = None):
        if edition:
            edition = edition.lower()
            if edition not in EDITION_KEYS:
                await interaction.response.send_message(f"Invalid edition `{edition}`. Use: tb, bmr, or snv.", ephemeral=True)
                return
            embeds = _build_night_embeds(edition)
            await interaction.response.send_message(embeds=embeds)
            return

        embeds = _build_night_embeds("tb")
        view = NightOrderView(interaction.user.id)
        await interaction.response.send_message(embeds=embeds, view=view)

    @commands.command(name="nightorder", aliases=["botcnight"])
    async def nightorder_prefix(self, ctx: commands.Context, edition: str | None = None):
        if edition:
            edition = edition.lower()
            if edition not in EDITION_KEYS:
                await ctx.send(f"Invalid edition `{edition}`. Use: tb, bmr, or snv.")
                return
            embeds = _build_night_embeds(edition)
            await ctx.send(embeds=embeds)
            return

        embeds = _build_night_embeds("tb")
        view = NightOrderView(ctx.author.id)
        await ctx.send(embeds=embeds, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(NightOrderCog(bot))
