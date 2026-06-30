from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import botc

WIKI_BASE = "https://wiki.bloodontheclocktower.com"


class RoleView(discord.ui.View):
    def __init__(self, role: dict, author_id: int):
        super().__init__(timeout=120)
        self.role = role
        self.author_id = author_id
        self.message: discord.Message | None = None
        wiki_url = f"{WIKI_BASE}/{role['name'].replace(' ', '_')}"
        self.add_item(discord.ui.Button(label="Wiki", style=discord.ButtonStyle.link, url=wiki_url))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    async def _respond(self, interaction: discord.Interaction, embed: discord.Embed, view: discord.ui.View | None = None):
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Jinxes", style=discord.ButtonStyle.secondary)
    async def jinxes(self, interaction: discord.Interaction, button: discord.ui.Button):
        jinxes = botc.get_jinxes_for_role(self.role["name"])
        embed = botc.build_jinx_embed(self.role, jinxes)
        await self._respond(interaction, embed, self)

    @discord.ui.button(label="Night Order", style=discord.ButtonStyle.secondary)
    async def night_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = botc.build_role_embed(self.role)
        first_night = _get_night_roles("firstNight", self.role)
        other_night = _get_night_roles("otherNight", self.role)

        if first_night:
            embed.add_field(
                name="First Night",
                value=f"This role acts at position **{self.role.get('firstNight', 0)}**",
                inline=False,
            )
        if other_night:
            embed.add_field(
                name="Other Night",
                value=f"This role acts at position **{self.role.get('otherNight', 0)}**",
                inline=False,
            )
        await self._respond(interaction, embed, self)

    @discord.ui.button(label="Aliases", style=discord.ButtonStyle.secondary)
    async def aliases(self, interaction: discord.Interaction, button: discord.ui.Button):
        aliases = botc.get_aliases(self.role["id"])
        if not aliases:
            await interaction.response.send_message("This role has no aliases.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"{botc.team_emoji(self.role['team'])} {self.role['name']} — Aliases",
            color=botc.TEAM_COLOR.get(self.role["team"], discord.Color.default()),
        )
        embed.add_field(name="Aliases", value=", ".join(f"`{a}`" for a in aliases), inline=False)
        await self._respond(interaction, embed, self)

    @discord.ui.button(label="Back to Role", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = botc.build_role_embed(self.role)
        await self._respond(interaction, embed, self)


def _get_night_roles(key: str, role: dict) -> list[dict]:
    val = role.get(key, 0)
    if val and isinstance(val, int) and val > 0:
        return [role]
    return []


class RoleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="role", description="Look up a BOTC role")
    @app_commands.describe(name="Role name or alias")
    async def role(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        role = botc.get_role(name)
        if not role:
            await interaction.followup.send(
                f"Could not find a role matching `{name}`. Try a different name or check `/aliases`.",
                ephemeral=True,
            )
            return

        embed = botc.build_role_embed(role)
        view = RoleView(role, interaction.user.id)
        await interaction.followup.send(embed=embed, view=view)

    @commands.command(name="rr", aliases=["botcrole"])
    async def rr(self, ctx: commands.Context, *, name: str):
        role = botc.get_role(name)
        if not role:
            await ctx.send(f"Could not find a role matching `{name}`.")
            return

        embed = botc.build_role_embed(role)
        view = RoleView(role, ctx.author.id)
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleCog(bot))
