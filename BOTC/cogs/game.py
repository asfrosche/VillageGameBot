from __future__ import annotations

import asyncio
import math
import time

import discord
from discord.ext import commands
from cogs.data_utils import load_guild_data

NOMINATION_TIMEOUT = 120


class VoteView(discord.ui.View):
    def __init__(self, cog: BOTCGame, guild_id: int, nominator_id: int, nominee_id: int, timeout_secs: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.nominator_id = nominator_id
        self.nominee_id = nominee_id
        self.votes: dict[int, bool] = {}  # user_id -> True=guilty, False=notguilty
        self._closed = False
        self._expires_at = time.time() + timeout_secs
        self._alive_count = 0
        self._required = 0

    def _refresh_alive_info(self, guild: discord.Guild):
        guild_data = load_guild_data(self.guild_id)
        if not guild_data:
            return
        role_name = guild_data.get("alive_role_name")
        if not role_name:
            return
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            return
        self._alive_count = sum(1 for m in role.members if not m.bot)
        self._required = math.ceil(self._alive_count / 2)

    def _build_embed(self) -> discord.Embed:
        nominee = self.cog.bot.get_user(self.nominee_id)
        nominator = self.cog.bot.get_user(self.nominator_id)
        n_name = nominee.display_name if nominee else f"<@{self.nominee_id}>"
        nom_name = nominator.display_name if nominator else f"<@{self.nominator_id}>"

        guilty = [uid for uid, v in self.votes.items() if v]
        notguilty = [uid for uid, v in self.votes.items() if not v]
        total = len(guilty) + len(notguilty)

        embed = discord.Embed(
            title=f"🗳️ {nom_name} nominated {n_name}",
            color=discord.Color.teal(),
        )
        embed.add_field(
            name=f"🟥 Guilty ({len(guilty)})",
            value="\n".join(f"<@{uid}>" for uid in guilty) or "—",
            inline=True,
        )
        embed.add_field(
            name=f"🟩 Not Guilty ({len(notguilty)})",
            value="\n".join(f"<@{uid}>" for uid in notguilty) or "—",
            inline=True,
        )

        status = "Closed" if self._closed else f"Expires <t:{int(self._expires_at)}:R>"
        embed.set_footer(text=f"Alive: {self._alive_count}  |  Need {self._required} guilty  |  {status}")
        return embed

    async def _refresh(self):
        msg = self.cog._messages.get(self.guild_id)
        if msg:
            await msg.edit(embed=self._build_embed(), view=self)

    async def _has_alive_role(self, user: discord.Member) -> bool:
        guild_data = load_guild_data(self.guild_id)
        if not guild_data:
            return False
        alive_role_name = guild_data.get("alive_role_name")
        if not alive_role_name:
            return False
        role = discord.utils.get(user.guild.roles, name=alive_role_name)
        return role is not None and role in user.roles

    async def _close(self):
        self._closed = True
        for child in self.children:
            child.disabled = True
        await self._refresh()
        if self.guild_id in self.cog._tasks:
            self.cog._tasks[self.guild_id].cancel()

    async def _vote(self, interaction: discord.Interaction, guilty: bool):
        if self._closed:
            return await interaction.response.send_message("Voting is closed.", ephemeral=True)
        if not await self._has_alive_role(interaction.user):
            return await interaction.response.send_message("Only alive players can vote.", ephemeral=True)
        self._refresh_alive_info(interaction.guild)
        self.votes[interaction.user.id] = guilty
        await self._refresh()
        label = "Guilty" if guilty else "Not Guilty"
        await interaction.response.send_message(f"You voted **{label}**.", ephemeral=True)

    @discord.ui.button(label="🟥 Guilty", style=discord.ButtonStyle.danger)
    async def guilty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, True)

    @discord.ui.button(label="🟩 Not Guilty", style=discord.ButtonStyle.success)
    async def notguilty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, False)


class BOTCGame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._messages: dict[int, discord.Message] = {}   # guild_id -> nomination message
        self._views: dict[int, VoteView] = {}             # guild_id -> vote view
        self._tasks: dict[int, asyncio.Task] = {}         # guild_id -> expiry task
        self._timeouts: dict[int, int] = {}               # guild_id -> custom timeout

    def cog_unload(self):
        for t in self._tasks.values():
            t.cancel()

    async def _expire(self, guild_id: int, view: VoteView):
        remaining = view._expires_at - time.time()
        if remaining > 0:
            await asyncio.sleep(remaining)
        await view._close()
        channel = self._messages[guild_id].channel if guild_id in self._messages else None
        if channel:
            await channel.send(f"⏰ Nomination expired. Final tally above.")
        self._messages.pop(guild_id, None)
        self._views.pop(guild_id, None)
        self._tasks.pop(guild_id, None)

    @commands.command(name="bnominate")
    @commands.has_permissions(administrator=True)
    async def bnominate(self, ctx: commands.Context, *, target: discord.Member):
        """Nominate a player. Voting buttons appear immediately. Expires after a set time."""
        if ctx.author == target:
            return await ctx.send("You cannot nominate yourself.")
        if ctx.guild.id in self._messages:
            return await ctx.send("A nomination is already in progress. Wait for it to finish.")

        timeout = self._timeouts.get(ctx.guild.id, NOMINATION_TIMEOUT)
        view = VoteView(self, ctx.guild.id, ctx.author.id, target.id, timeout)
        view._refresh_alive_info(ctx.guild)
        msg = await ctx.send(embed=view._build_embed(), view=view)
        self._messages[ctx.guild.id] = msg
        self._views[ctx.guild.id] = view
        self._tasks[ctx.guild.id] = asyncio.create_task(self._expire(ctx.guild.id, view))

    @commands.command(name="bnomtimeout")
    @commands.has_permissions(administrator=True)
    async def bnomtimeout(self, ctx: commands.Context, seconds: int):
        """[Admin] Set the nomination expiry timeout in seconds for this server."""
        if seconds < 10:
            return await ctx.send("Minimum timeout is 10 seconds.")
        self._timeouts[ctx.guild.id] = seconds
        await ctx.send(f"⏱️ Nomination timeout set to {seconds} seconds.")

    @commands.command(name="bnoms")
    async def bnoms(self, ctx: commands.Context):
        """Show current nomination status, vote counts, and required votes."""
        view = self._views.get(ctx.guild.id)
        if not view or view._closed:
            await ctx.send("No active nomination.")
            return

        view._refresh_alive_info(ctx.guild)
        guilty = sum(1 for v in view.votes.values() if v)
        notguilty = sum(1 for v in view.votes.values() if not v)
        total_voted = guilty + notguilty

        nominee = self.bot.get_user(view.nominee_id)
        nominator = self.bot.get_user(view.nominator_id)
        n_name = nominee.display_name if nominee else f"<@{view.nominee_id}>"
        nom_name = nominator.display_name if nominator else f"<@{view.nominator_id}>"

        embed = discord.Embed(
            title=f"🗳️ Nomination Status",
            color=discord.Color.teal(),
        )
        embed.add_field(name="Nominator", value=nom_name, inline=True)
        embed.add_field(name="Nominee", value=n_name, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
        embed.add_field(
            name=f"🟥 Guilty ({guilty})",
            value="\n".join(f"<@{uid}>" for uid in view.votes if view.votes[uid]) or "—",
            inline=True,
        )
        embed.add_field(
            name=f"🟩 Not Guilty ({notguilty})",
            value="\n".join(f"<@{uid}>" for uid in view.votes if not view.votes[uid]) or "—",
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(
            name="Voter Turnout",
            value=f"{total_voted} / {view._alive_count} alive",
            inline=True,
        )
        embed.add_field(
            name="Required Guilty",
            value=f"{view._required}",
            inline=True,
        )
        embed.add_field(
            name="Status",
            value=f"Expires <t:{int(view._expires_at)}:R>",
            inline=True,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(BOTCGame(bot))
