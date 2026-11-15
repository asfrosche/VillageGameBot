import re
import time
import asyncio
import discord
import datetime
from datetime import datetime, timedelta
from discord.ext import commands
from utils.discord_safe import EDIT_LIMIT_CODE, with_retries
from cogs.data_utils import (
    LYNCH_SESSION_COUNT,
    LYNCH_SESSION_VOTE_KEYS,
    get_lynch_channel,
    load_guild_data,
    resolve_lynch_channels,
    save_guild_data,
)

# Duration of a public execution vote ("letale fisica" -> lynch vote), in minutes
EXECUTION_VOTE_MINUTES = 15
# Solo in memoria: si perde a ogni riavvio, non tocca mai guild_data.
active_executions = {}

class ExecutionView(discord.ui.View):
    """Sì/No buttons for a public execution vote.

    Several execution votes can run at the same time, one per target, tracked
    separately in the in-memory active_executions dict (never guild_data, never
    written to disk - a restart loses any vote in progress by design). Only
    members with the guild's 'alive' role can vote, and votes can be changed.
    Nothing about the tally is ever shown live: when the vote ends, its record
    is dropped and the full breakdown is posted once to the private
    overseer-discussion channel.
    """

    def __init__(self, bot, guild_id: int, target_id: int):
        super().__init__(timeout=EXECUTION_VOTE_MINUTES * 60)
        self.bot = bot
        self.guild_id = guild_id
        self.target_id = target_id
        self.message: discord.Message | None = None

    async def _handle_vote(self, interaction: discord.Interaction, value: bool):
        guild_data = load_guild_data(self.guild_id)
        executions = active_executions.get(self.guild_id, {})
        execution = executions.get(str(self.target_id))
        if not execution or time.time() >= execution.get("end_timestamp", 0):
            await interaction.response.send_message("Questa votazione non è più attiva.", ephemeral=True)
            return
        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data["alive_role_name"])
        if alive_role is None or alive_role not in interaction.user.roles:
            await interaction.response.send_message("Non puoi votare in questa votazione.", ephemeral=True)
            return
        voter_id = str(interaction.user.id)
        previous = execution["votes"].get(voter_id)
        execution["votes"][voter_id] = value
        if previous is None:
            msg = "Voto registrato."
        elif previous != value:
            msg = "Voto aggiornato."
        else:
            msg = "Hai già votato così."
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Sì", style=discord.ButtonStyle.success)
    async def vote_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def vote_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, False)

    async def on_timeout(self):
        executions = active_executions.get(self.guild_id, {})
        execution = executions.get(str(self.target_id))
        if not execution:
            return

        guild = self.bot.get_guild(self.guild_id)
        target = guild.get_member(self.target_id) if guild else None
        target_text = target.mention if target else "Il giocatore"

        alive_members = []
        yes_names, no_names, non_voters = [], [], []
        threshold, executed = 0, False
        try:
            guild_data = load_guild_data(self.guild_id) if guild else None
            alive_role = (
                discord.utils.get(guild.roles, name=guild_data.get("alive_role_name"))
                if guild_data
                else None
            )
            alive_members = alive_role.members if alive_role else []
            alive_ids = {m.id for m in alive_members}

            for uid, v in execution["votes"].items():
                if int(uid) not in alive_ids:
                    continue
                member = guild.get_member(int(uid)) if guild else None
                name = member.display_name if member else f"ID {uid}"
                (yes_names if v else no_names).append(name)
            non_voters = [m.display_name for m in alive_members if str(m.id) not in execution["votes"]]

            threshold = len(alive_members) // 2 + 1
            executed = len(alive_members) > 0 and len(yes_names) >= threshold
        except Exception:
            # Never let a bug here leave the vote stuck "active" forever -
            # log it (visible in the bot's console/logs) and fall through
            # with the safe defaults above so cleanup below still runs.
            import traceback
            print(f"[execution] on_timeout failed for target {self.target_id} in guild {self.guild_id}:")
            traceback.print_exc()

        # Drop the record and disable the buttons unconditionally - even if
        # the tally above failed, the vote must not stay open.
        del executions[str(self.target_id)]
        for child in self.children:
            child.disabled = True

        if self.message:
            result_embed = discord.Embed(
                title="⚖️ Esecuzione conclusa",
                description=("A breve vi diremo i risultati"),
                color=0xff3fb9,
            )
            result_embed.set_footer(text="Village Game")
            try:
                await self.message.edit(embed=result_embed, view=self)
            except discord.HTTPException:
                pass

        # Full breakdown (counts + who voted what) goes only here, once, to the
        # private admin channel - never anywhere public, never kept in storage.
        overseer_channel_name = "overseer-discussion"
        overseer_channel = discord.utils.get(guild.channels, name=overseer_channel_name) if guild else None
        if overseer_channel:
            detail_embed = discord.Embed(
                title=f"Risultato voto: {target.display_name if target else 'sconosciuto'}",
                color=0xff3fb9,
                timestamp=datetime.now(),
            )
            detail_embed.add_field(name="Esito", value="Sì ha vinto" if executed else "No ha vinto", inline=False)
            detail_embed.add_field(name="Quorum necessario", value=f"{threshold} / {len(alive_members)}", inline=False)
            detail_embed.add_field(name=f"Voti Sì ({len(yes_names)})", value="\n".join(yes_names) or "—", inline=True)
            detail_embed.add_field(name=f"Voti No ({len(no_names)})", value="\n".join(no_names) or "—", inline=True)
            detail_embed.add_field(name=f"Non votanti ({len(non_voters)})", value="\n".join(non_voters) or "—", inline=False)
            detail_embed.set_footer(text="Village Game")
            try:
                await overseer_channel.send(embed=detail_embed)
            except discord.HTTPException:
                pass


class Voting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def vote(self, ctx, user: discord.Member, channel: discord.TextChannel = None):
        """Cast or change your vote for a player."""
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            overseer_role = discord.utils.get(ctx.guild.roles, name=guild_data["overseer_role_name"])
            if alive_role not in ctx.author.roles and dead_role not in ctx.author.roles and overseer_role not in ctx.author.roles:
                await ctx.send("You can't vote")
                return
            if channel is None:
                sessions = resolve_lynch_channels(ctx.guild, guild_data)
                leader = get_lynch_channel(ctx.guild, guild_data, "leader_channel_name")
                leader2 = get_lynch_channel(ctx.guild, guild_data, "leader_channel_name2")
                if ctx.channel is not None and ctx.channel in (*sessions, leader, leader2):
                    channel = ctx.channel
                else:
                    channel = sessions[0]
            if guild_data["voteinrc"] is False:
                channel = ctx.channel
            lynch_channels = resolve_lynch_channels(ctx.guild, guild_data)
            rc_categories = [
                cat
                for cat in (
                    discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"]),
                    discord.utils.get(ctx.guild.categories, name=guild_data["alt_category_name"]),
                )
                if cat
            ]
            is_rc_channel = bool(
                ctx.channel and any(ctx.channel in cat.channels for cat in rc_categories)
            )
            if guild_data["voteinrc"] is True:
                if is_rc_channel is False:
                    await ctx.send("You can only vote in your RoleChat.")
                    return
            for lidx, lynch_channel in enumerate(lynch_channels):
                if lynch_channel and channel.id == lynch_channel.id:
                    lynch_votes = guild_data[f"lynch_votes{lidx + 1}"]
                    voter_id = str(ctx.author.id)
                    if voter_id in lynch_votes:
                        old_vote_id = lynch_votes.get(voter_id)
                        if old_vote_id:
                            old_vote = await self.bot.fetch_user(old_vote_id)
                            lynch_votes[voter_id] = user.id
                            await ctx.send(f'{ctx.author.display_name} changes their vote from {old_vote.display_name} to {user.display_name}')
                    else:
                        lynch_votes[voter_id] = user.id
                        await ctx.send(f'{ctx.author.display_name} votes {user.display_name}')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            for leader_name_key, leader_votes_key in (("leader_channel_name", "leader_votes"), ("leader_channel_name2", "leader_votes2")):
                leader_channel = get_lynch_channel(ctx.guild, guild_data, leader_name_key)
                if leader_channel and channel.id == leader_channel.id:
                    leader_votes = guild_data[leader_votes_key]
                    voter_id = str(ctx.author.id)
                    if voter_id in leader_votes:
                        old_vote_id = leader_votes.get(voter_id)
                        if old_vote_id:
                            old_vote = await self.bot.fetch_user(old_vote_id)
                            leader_votes[voter_id] = user.id
                            await ctx.send(f'{ctx.author.display_name} changes their vote from {old_vote.display_name} to {user.display_name}')
                    else:
                        leader_votes[voter_id] = user.id
                        await ctx.send(f'{ctx.author.display_name} votes {user.display_name}')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            await ctx.send("You can't vote in this channel")
        else:
            await ctx.send("Guild data not loaded.")

    # Command to abstain
    @commands.command()
    async def abstain(self, ctx, channel: discord.TextChannel = None):
        """Abstain from voting."""
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            overseer_role = discord.utils.get(ctx.guild.roles, name=guild_data["overseer_role_name"])
            if alive_role not in ctx.author.roles and dead_role not in ctx.author.roles and overseer_role not in ctx.author.roles:
                await ctx.send("You can't abstain")
                return
            if channel is None:
                sessions = resolve_lynch_channels(ctx.guild, guild_data)
                leader = get_lynch_channel(ctx.guild, guild_data, "leader_channel_name")
                leader2 = get_lynch_channel(ctx.guild, guild_data, "leader_channel_name2")
                if ctx.channel is not None and ctx.channel in (*sessions, leader, leader2):
                    channel = ctx.channel
                else:
                    channel = sessions[0]
            if guild_data["voteinrc"] is False:
                channel = ctx.channel
            lynch_channels = resolve_lynch_channels(ctx.guild, guild_data)
            rc_categories = [
                cat
                for cat in (
                    discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"]),
                    discord.utils.get(ctx.guild.categories, name=guild_data["alt_category_name"]),
                )
                if cat
            ]
            is_rc_channel = bool(
                ctx.channel and any(ctx.channel in cat.channels for cat in rc_categories)
            )
            if guild_data["voteinrc"] is True:
                if is_rc_channel is False:
                    await ctx.send("You can only vote in your RoleChat.")
                    return
            for lidx, lynch_channel in enumerate(lynch_channels):
                if lynch_channel and channel.id == lynch_channel.id:
                    lynch_votes = guild_data[f"lynch_votes{lidx + 1}"]
                    voter_id = str(ctx.author.id)
                    if voter_id not in lynch_votes:
                        await ctx.send(f"{ctx.author.display_name}, you didn't vote yet")
                    else:
                        del lynch_votes[voter_id]
                        await ctx.send(f'{ctx.author.display_name} abstains')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            for leader_name_key, leader_votes_key in (("leader_channel_name", "leader_votes"), ("leader_channel_name2", "leader_votes2")):
                leader_channel = get_lynch_channel(ctx.guild, guild_data, leader_name_key)
                if leader_channel and channel.id == leader_channel.id:
                    leader_votes = guild_data[leader_votes_key]
                    voter_id = str(ctx.author.id)
                    if voter_id not in leader_votes:
                        await ctx.send(f"{ctx.author.display_name}, you didn't vote yet")
                    else:
                        del leader_votes[voter_id]
                        await ctx.send(f'{ctx.author.display_name} abstains')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            await ctx.send("You can't abstain in this channel")
        else:
            await ctx.send("Guild data not loaded.")

    # Command to manipulate a vote
    @commands.command()
    async def manipulate(self, ctx, old_user: discord.Member, new_user: discord.Member, channel: discord.TextChannel = None):
        """Force another player's vote (requires manipulate power)."""
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data and ctx.author.guild_permissions.administrator:
            if channel is None:
                channel = get_lynch_channel(ctx.guild, guild_data, "lynch_channel_name1")
            if guild_data["voteinrc"] is False:
                channel = ctx.channel
            lynch_channels = resolve_lynch_channels(ctx.guild, guild_data)
            for lidx, lynch_channel in enumerate(lynch_channels):
                if lynch_channel and ctx.channel.id == lynch_channel.id:
                    lynch_votes = guild_data[f"lynch_votes{lidx + 1}"]
                    if str(old_user.id) in lynch_votes:
                        old_vote_id = lynch_votes.get(str(old_user.id))
                        if old_vote_id:
                            old_vote = await self.bot.fetch_user(old_vote_id)
                            lynch_votes[str(old_user.id)] = new_user.id
                            await ctx.send(f'Vote for {old_user.display_name} has been changed from {old_vote.display_name} to {new_user.display_name} by {ctx.author.display_name}')
                    else:
                        lynch_votes[str(old_user.id)] = new_user.id
                        await ctx.send(f'{old_user.display_name} votes {new_user.display_name}')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            for leader_name_key, leader_votes_key in (("leader_channel_name", "leader_votes"), ("leader_channel_name2", "leader_votes2")):
                leader_channel = get_lynch_channel(ctx.guild, guild_data, leader_name_key)
                if leader_channel and ctx.channel.id == leader_channel.id:
                    leader_votes = guild_data[leader_votes_key]
                    if str(old_user.id) in leader_votes:
                        old_vote_id = leader_votes.get(str(old_user.id))
                        if old_vote_id:
                            old_vote = await self.bot.fetch_user(old_vote_id)
                            leader_votes[str(old_user.id)] = new_user.id
                            await ctx.send(f'Vote for {old_user.display_name} has been changed from {old_vote.display_name} to {new_user.display_name} by {ctx.author.display_name}')
                    else:
                        leader_votes[str(old_user.id)] = new_user.id
                        await ctx.send(f'{old_user.display_name} votes {new_user.display_name}')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            await ctx.send("You can't manipulate in this channel")
        else:
            await ctx.send("Guild data not loaded or you don't have enough permissions.")

    # Command to remove a vote
    @commands.command()
    async def removevote(self, ctx, user: discord.Member, channel: discord.TextChannel = None):
        """Remove a player's vote (admin only)."""
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data and ctx.author.guild_permissions.administrator:
            if channel is None:
                channel = get_lynch_channel(ctx.guild, guild_data, "lynch_channel_name1")
            if guild_data["voteinrc"] is False:
                channel = ctx.channel
            lynch_channels = resolve_lynch_channels(ctx.guild, guild_data)
            for lidx, lynch_channel in enumerate(lynch_channels):
                if lynch_channel and ctx.channel.id == lynch_channel.id:
                    lynch_votes = guild_data[f"lynch_votes{lidx + 1}"]
                    if str(user.id) not in lynch_votes:
                        await ctx.send(f"{user.display_name} didn't vote yet")
                    else:
                        del lynch_votes[str(user.id)]
                        await ctx.send(f'{user.display_name} vote has been removed by {ctx.author.display_name}')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            for leader_name_key, leader_votes_key in (("leader_channel_name", "leader_votes"), ("leader_channel_name2", "leader_votes2")):
                leader_channel = get_lynch_channel(ctx.guild, guild_data, leader_name_key)
                if leader_channel and ctx.channel.id == leader_channel.id:
                    leader_votes = guild_data[leader_votes_key]
                    if str(user.id) not in leader_votes:
                        await ctx.send(f"{user.display_name} didn't vote yet")
                    else:
                        del leader_votes[str(user.id)]
                        await ctx.send(f'{user.display_name} vote has been removed by {ctx.author.display_name}')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            await ctx.send("You can't manipulate in this channel")
        else:
            await ctx.send("Guild data not loaded or you don't have enough permissions.")

    class RemVoteConfirmView(discord.ui.View):
        def __init__(self, ctx, user, vote_data):
            super().__init__(timeout=60)
            self.ctx = ctx
            self.user = user
            self.vote_data = vote_data

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("This isn't for you.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.green)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            guild_data = load_guild_data(self.ctx.guild.id)
            if not guild_data:
                await interaction.response.edit_message(content="Guild data not loaded.", embed=None, view=None)
                self.stop()
                return

            player_id = str(self.user.id)
            removed_by = self.vote_data["removed_by"]
            removed_on = self.vote_data["removed_on"]
            total_removed = len(removed_by) + len(removed_on)

            vote_sessions = [
                (key, guild_data.get(key, {})) for key in LYNCH_SESSION_VOTE_KEYS
            ]
            vote_sessions += [
                ("leader_votes", guild_data.get("leader_votes", {})),
                ("leader_votes2", guild_data.get("leader_votes2", {})),
            ]

            for session_name, vote_dict in vote_sessions:
                vote_dict_new = {k: v for k, v in vote_dict.items()}
                for vid in list(vote_dict_new.keys()):
                    if vid == player_id:
                        del vote_dict[vid]
                for vid, tid in list(vote_dict_new.items()):
                    if tid == self.user.id:
                        if vid in vote_dict:
                            del vote_dict[vid]

            save_guild_data(self.ctx.guild.id, guild_data)

            lynch_channels = resolve_lynch_channels(self.ctx.guild, guild_data)
            leader_channel = get_lynch_channel(self.ctx.guild, guild_data, "leader_channel_name")
            leader_channel2 = get_lynch_channel(self.ctx.guild, guild_data, "leader_channel_name2")

            narration_text = f"All votes involving **{self.user.display_name}** have been removed ({total_removed} vote(s))."

            for channel in [*lynch_channels, leader_channel, leader_channel2]:
                if channel:
                    try:
                        embed = discord.Embed(
                            title="🗳️ Votes Removed",
                            description=narration_text,
                            color=0xDC143C,
                        )
                        if removed_by:
                            embed.add_field(name="Votes By", value="\n".join(removed_by[:10]) + ("..." if len(removed_by) > 10 else ""), inline=False)
                        if removed_on:
                            embed.add_field(name="Votes On", value="\n".join(removed_on[:10]) + ("..." if len(removed_on) > 10 else ""), inline=False)
                        await channel.send(embed=embed)
                    except Exception:
                        pass

            voting_cog = self.ctx.bot.get_cog('Voting')
            if voting_cog:
                await voting_cog.aggiorna_risultati(self.ctx, lynch_channels[0])

            await interaction.response.edit_message(content=f"✅ Confirmed. Removed {total_removed} vote(s) for **{self.user.display_name}**.", embed=None, view=None)
            self.stop()

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(content="❌ Vote removal cancelled.", embed=None, view=None)
            self.stop()

        async def on_timeout(self):
            try:
                await self.message.edit(content="⏰ Vote removal timed out.", embed=None, view=None)
            except Exception:
                pass

    @commands.command(name="remvote")
    async def remvote(self, ctx, user: discord.Member):
        """Remove all votes by and on a player across all lynch sessions. Usage: .remvote @player"""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have permission to use this command.")
            return

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        player_id = str(user.id)
        removed_by = []
        removed_on = []

        vote_sessions = [(key, guild_data.get(key, {})) for key in LYNCH_SESSION_VOTE_KEYS]
        vote_sessions += [
            ("leader_votes", guild_data.get("leader_votes", {})),
            ("leader_votes2", guild_data.get("leader_votes2", {})),
        ]

        for session_name, vote_dict in vote_sessions:
            to_remove_by = [vid for vid in vote_dict if vid == player_id]
            for vid in to_remove_by:
                target_id = vote_dict[vid]
                target = ctx.guild.get_member(target_id)
                target_name = target.display_name if target else f"ID {target_id}"
                removed_by.append(f"• **{user.display_name}** → **{target_name}** ({session_name})")

            to_remove_on = [vid for vid, tid in vote_dict.items() if tid == user.id]
            for vid in to_remove_on:
                voter = ctx.guild.get_member(int(vid))
                voter_name = voter.display_name if voter else f"ID {vid}"
                removed_on.append(f"• **{voter_name}** → **{user.display_name}** ({session_name})")

        total_removed = len(removed_by) + len(removed_on)

        if total_removed == 0:
            await ctx.send(f"No votes found for {user.display_name}.")
            return

        embed = discord.Embed(
            title=f"🗳️ Vote Removal — {user.display_name}",
            description=f"Found **{total_removed}** vote(s) involving this player. Click **Confirm** to remove all votes.",
            color=0xDC143C,
        )
        if removed_by:
            embed.add_field(name="Votes By This Player", value="\n".join(removed_by[:15]) + ("..." if len(removed_by) > 15 else ""), inline=False)
        if removed_on:
            embed.add_field(name="Votes On This Player", value="\n".join(removed_on[:15]) + ("..." if len(removed_on) > 15 else ""), inline=False)

        vote_data = {"removed_by": removed_by, "removed_on": removed_on}
        view = self.RemVoteConfirmView(ctx, user, vote_data)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @commands.command()
    async def voteinrc(self, ctx, value: bool):
        """Toggle whether voting is allowed in RoleChat channels."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild_data['voteinrc'] = value
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.send(f"Votes in RoleChats have been set to `{value}` for this server.")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    # Command to see votes
    @commands.command(aliases=['v'])
    async def votelist(self, ctx, type: str = None):
        """Show all current votes."""
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            if guild_data["voteinrc"] is True:
                if not ctx.author.guild_permissions.administrator:
                    await ctx.send("You can't use this command while voting is allowed only in RoleChats.")
                    return
            votes_sessions = {
                f"LYNCH SESSION {i}": guild_data.get(f"lynch_votes{i}", {})
                for i in range(1, LYNCH_SESSION_COUNT + 1)
            }
            votes_sessions["LEADER ELECTION"] = guild_data["leader_votes"]
            votes_sessions["LEADER ELECTION 2"] = guild_data.get("leader_votes2", {})
            # Map each .votelist argument to its board title. Looking up by
            # title (not list index) keeps the right session even when others
            # have no votes and are skipped below.
            session_labels = {
                f"lynch{i}": f"LYNCH SESSION {i}"
                for i in range(1, LYNCH_SESSION_COUNT + 1)
            }
            session_labels["leader"] = "LEADER ELECTION"
            session_labels["leader2"] = "LEADER ELECTION 2"
            valid_types = list(session_labels)
            embeds = []
            embeds_by_label = {}
            for session, votes in votes_sessions.items():
                if not votes:
                    continue
                session_votes = {}
                for voter_id, voted_id in votes.items():
                    voted_user = ctx.guild.get_member(voted_id)
                    voter_user = ctx.guild.get_member(int(voter_id))
                    if voted_user and voter_user:
                        if voted_user.display_name not in session_votes:
                            session_votes[voted_user.display_name] = []
                        session_votes[voted_user.display_name].append(voter_user.display_name)
                description = ""
                for voted, voters in session_votes.items():
                    vote_count = len(voters)
                    vote_text = "vote" if vote_count == 1 else "votes"
                    description += f"**{voted} ({vote_count} {vote_text}):**\n" + "\n".join(voters) + "\n\n"
                embed = discord.Embed(title=session, description=description, color=0xff3fb9, timestamp=datetime.now())
                embeds.append(embed)
                embeds_by_label[session] = embed
            if not embeds:
                await ctx.send("No votes in any session.")
            elif type is None:
                for embed in embeds:
                    await ctx.send(embed=embed)
            elif type.lower() in valid_types:
                label = session_labels[type.lower()]
                if label in embeds_by_label:
                    await ctx.send(embed=embeds_by_label[label])
                else:
                    await ctx.send(f"{type} has no votes yet.")
            else:
                await ctx.send(f"{type} is not a valid argument")
        else:
            await ctx.send("Guild data not loaded")

    # Command to reset votes
    @commands.command()
    async def resetvotes(self, ctx):
        """Clear all votes."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                for key in LYNCH_SESSION_VOTE_KEYS:
                    guild_data[key] = {}
                guild_data["leader_votes"] = {}
                guild_data["leader_votes2"] = {}
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.send('Votes have been reset')
                await self.aggiorna_risultati(ctx)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    @commands.command(name="updatevotes", aliases=["uv"])
    async def updatevotes(self, ctx, channel: discord.TextChannel = None):
        """Guide to refresh the votecount for a session via .vh (admin only).

        The stored vote tallies live in memory for temporary sessions, so after a
        restart the readable count comes from the votes still in chat history.
        Run .vh here to rebuild/show them.
        """
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if channel is None:
            channel = ctx.channel

        lynch_channels = [
            *resolve_lynch_channels(ctx.guild, guild_data),
            get_lynch_channel(ctx.guild, guild_data, "leader_channel_name"),
            get_lynch_channel(ctx.guild, guild_data, "leader_channel_name2"),
        ]
        is_fixed = any(c and c.id == channel.id for c in lynch_channels)

        embed = discord.Embed(
            title=f"🗳 Refresh votecount — {channel.name}",
            description=(
                "Use **`.vh`** (alias for `.votehistory`) **in this channel** to rebuild or read the votecount "
                "from the chat history.\n\n"
                "• Reply to the **Day Start** message, then `.vh` — counts every vote from that point.\n"
                "• `.vh range` — same, then pick an **end** message/link to scan a window.\n"
                "• `.vh grouped` — results grouped by target (last vote per voter wins).\n\n"
                "`.vh` also tracks `.remvote`, `.removevote` and `.manipulate`, so the count "
                "matches the live vote-count board even after admin edits."
            ),
            color=0xff3fb9,
        )
        if not is_fixed:
            embed.add_field(
                name="Note",
                value="This doesn't look like a registered voting channel, but `.vh` still works here to scan this channel's history.",
                inline=False,
            )
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)

    @commands.command(aliases=["vh"])
    async def votehistory(self, ctx, mode: str = None):
        """Scan and display vote history. Modes: grouped (by target), range (with end). Reply to a Day Start message.

        Tracks .vote/.abstain plus admin edits: .remvote, .removevote and
        .manipulate, so the recount matches the live vote-count board.
        """
        if not ctx.message.reference:
            await ctx.send("Reply to a Day Start message to scan vote history from that point.")
            return

        try:
            start_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        except discord.NotFound:
            await ctx.send("The referenced message could not be found.")
            return
        except discord.Forbidden:
            await ctx.send("I don't have permission to read messages.")
            return
        except discord.HTTPException:
            await ctx.send("An error occurred while fetching the message.")
            return

        is_range = mode and mode.lower() == "range"
        is_grouped = mode and mode.lower() == "grouped"
        end_message = None

        if is_range:
            prompt = await ctx.send("Reply directly to the **end message**, or send its message ID/link.")
            try:
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel
                reply = await self.bot.wait_for("message", check=check, timeout=60)
                end_id = self._extract_end_message_id(reply)
                if not end_id:
                    await ctx.send("Could not resolve the end message. Reply to it directly or send its message ID/link.")
                    return
                end_message = await ctx.channel.fetch_message(end_id)
            except asyncio.TimeoutError:
                await ctx.send("Timed out waiting for the end message.")
                return

        prefix = self.bot.command_prefix
        if callable(prefix):
            prefix = "."
        elif not isinstance(prefix, str):
            prefix = prefix[0]

        # {uid: {"actions": [], "first_vote_ts": None}}
        user_actions = {}
        # Track when each voter first cast any action (for chronological sorting)
        voter_first_ts = {}
        # How many vote entries were dropped by .remvote/.removevote
        removed_total = [0]

        def active_target(voter_id):
            """Target of a voter's latest action, or None if they hold no vote."""
            entry = user_actions.get(voter_id)
            if not entry:
                return None
            actions = entry["actions"]
            if actions and actions[-1]["type"] == "vote":
                return actions[-1]["target_id"]
            return None

        def mark_removed(voter_id, ts):
            """Void a voter's standing vote, but only if they actually hold one."""
            entry = user_actions.get(voter_id)
            if not entry:
                return
            actions = entry["actions"]
            if actions and actions[-1]["type"] == "vote":
                actions.append({"type": "removed", "ts": ts})
                removed_total[0] += 1

        def clear_votes_for(target_id, ts, exclude=None):
            """Void every standing vote cast for *target_id*."""
            for voter_id in list(user_actions.keys()):
                if voter_id == exclude:
                    continue
                if active_target(voter_id) == target_id:
                    mark_removed(voter_id, ts)

        start_ts = int(start_message.created_at.timestamp())
        range_label = f" (Start: <t:{start_ts}:T>)"

        async with ctx.typing():
            kwargs = {"after": start_message, "oldest_first": True}
            if end_message:
                kwargs["before"] = end_message
                range_label += f" — End: <t:{int(end_message.created_at.timestamp())}:T>"
            async for message in ctx.channel.history(**kwargs):
                content = message.content.strip()
                uid = message.author.id
                lower = content.lower()
                msg_ts = message.created_at.timestamp()

                # A confirmed .remvote leaves a "Votes Removed" embed in every
                # session channel, so the removal is picked up even when the
                # command itself was run elsewhere (e.g. overseer-discussion).
                if message.author.bot:
                    for embed in message.embeds:
                        if embed.title and "votes removed" in embed.title.lower():
                            removed = self._resolve_removed_player(embed, ctx.guild)
                            if removed:
                                mark_removed(removed.id, msg_ts)
                                clear_votes_for(removed.id, msg_ts, exclude=removed.id)
                    continue

                if lower.startswith(prefix + "abstain"):
                    if uid not in user_actions:
                        user_actions[uid] = {"actions": []}
                    user_actions[uid]["actions"].append({"type": "abstain", "ts": msg_ts})
                elif lower.startswith(prefix + "removevote"):
                    target = self._resolve_target_from_message(
                        message, content[len(prefix) + len("removevote"):], ctx.guild
                    )
                    if target:
                        mark_removed(target.id, msg_ts)
                elif lower.startswith(prefix + "remvote"):
                    target = self._resolve_target_from_message(
                        message, content[len(prefix) + len("remvote"):], ctx.guild
                    )
                    if target:
                        mark_removed(target.id, msg_ts)
                        clear_votes_for(target.id, msg_ts, exclude=target.id)
                elif lower.startswith(prefix + "manipulate"):
                    if len(message.mentions) >= 2:
                        old_user, new_user = message.mentions[0], message.mentions[1]
                        if old_user.id not in user_actions:
                            user_actions[old_user.id] = {"actions": []}
                            voter_first_ts[old_user.id] = msg_ts
                        user_actions[old_user.id]["actions"].append(
                            {"type": "vote", "target_id": new_user.id, "ts": msg_ts}
                        )
                elif lower.startswith(prefix + "vote "):
                    target = self._resolve_target_from_message(
                        message, content[len(prefix) + len("vote"):], ctx.guild
                    )
                    if target:
                        if uid not in user_actions:
                            user_actions[uid] = {"actions": []}
                            voter_first_ts[uid] = msg_ts
                        user_actions[uid]["actions"].append({"type": "vote", "target_id": target.id, "ts": msg_ts})

        if not user_actions:
            await ctx.send(f"No votes found in the scanned range.{range_label}")
            return

        # ── Vote Count: current votes (last non-abstain action) ──
        # {target_id: [(voter_id, first_vote_ts), ...]}
        current_votes = {}
        for uid, data in user_actions.items():
            actions = data["actions"]
            last = actions[-1]
            if last["type"] == "vote":
                first_ts = voter_first_ts.get(uid, 0)
                current_votes.setdefault(last["target_id"], []).append((uid, first_ts))

        # Sort targets by vote count desc, then by first vote time asc
        sorted_targets = sorted(current_votes.items(), key=lambda x: (-len(x[1]), x[1][0][1] if x[1] else 0))

        count_lines = []
        for target_id, voter_data_list in sorted_targets:
            target = ctx.guild.get_member(target_id)
            if not target:
                continue
            # Sort voters chronologically (oldest first) by their first vote timestamp
            sorted_voters = sorted(voter_data_list, key=lambda x: x[1])
            names = []
            for vid, _ in sorted_voters:
                m = ctx.guild.get_member(vid)
                names.append(m.display_name if m else "Unknown")
            count_lines.append(f"**{target.display_name}** ({len(voter_data_list)}): {', '.join(names)}")

        count_text = "\n".join(count_lines) if count_lines else "No active votes."

        # ── Vote History ──
        mode_label = " [Grouped]" if is_grouped else (" [Range]" if is_range else "")

        if is_grouped or is_range:
            # Grouped: Target → list of voters (in chronological order)
            # {target_id: [(voter_name, vote_ts), ...]}
            target_history = {}
            for uid, data in user_actions.items():
                voter = ctx.guild.get_member(uid)
                vname = voter.display_name if voter else "Unknown"
                for a in data["actions"]:
                    if a["type"] == "vote":
                        target_history.setdefault(a["target_id"], []).append((vname, a["ts"]))
            # Sort targets by when they received their first vote
            sorted_targets_h = sorted(
                target_history.items(),
                key=lambda x: min(v[1] for v in x[1]) if x[1] else 0
            )
            history_lines = []
            for tid, voter_ts_list in sorted_targets_h:
                target = ctx.guild.get_member(tid)
                if not target:
                    continue
                # Sort voters chronologically by their vote timestamp for THIS target
                sorted_voters_h = sorted(voter_ts_list, key=lambda x: x[1])
                vnames = [v[0] for v in sorted_voters_h]
                history_lines.append(f"**{target.display_name}** ({len(vnames)}): {' \u2192 '.join(vnames)}")
        else:
            # Non-grouped: per-voter chains
            # Sort voters by their first action timestamp
            sorted_users = sorted(user_actions.items(), key=lambda x: voter_first_ts.get(x[0], 0))
            history_lines = []
            for uid, data in sorted_users:
                voter = ctx.guild.get_member(uid)
                vname = voter.display_name if voter else "Unknown"
                parts = []
                for a in data["actions"]:
                    if a["type"] == "vote":
                        t = ctx.guild.get_member(a["target_id"])
                        parts.append(t.display_name if t else "Unknown")
                    elif a["type"] == "abstain":
                        parts.append("Ø")
                    elif a["type"] == "removed":
                        parts.append("✕")
                history_lines.append(f"**{vname}**: {' \u2192 '.join(parts)}")

        history_text = "\n".join(history_lines) if history_lines else "No vote history."

        if removed_total[0]:
            range_label += f" — ✕ {removed_total[0]} removed by .remvote/.removevote"

        for embed in self._build_vh_embeds(f"Vote Count{mode_label}", count_text, range_label):
            await ctx.send(embed=embed)
        for embed in self._build_vh_embeds(f"Vote History{mode_label}", history_text, range_label):
            await ctx.send(embed=embed)

    @staticmethod
    def _resolve_target_from_message(message: discord.Message, name_text: str, guild: discord.Guild):
        """Resolve a member from a message's first mention, else by name/display_name."""
        if message.mentions:
            return message.mentions[0]
        if name_text:
            lower = name_text.strip().lower()
            return discord.utils.find(
                lambda m: m.name.lower() == lower or m.display_name.lower() == lower,
                guild.members
            )
        return None

    @staticmethod
    def _resolve_removed_player(embed: discord.Embed, guild: discord.Guild):
        """Pull the removed player out of a 'Votes Removed' embed description.

        The description reads 'All votes involving **Name** have been removed
        (N vote(s)).' - the first bolded name is the player whose votes were
        stripped (both their own vote and every vote cast for them).
        """
        match = re.search(r"\*\*(.+?)\*\*", embed.description or "")
        if not match:
            return None
        name = match.group(1).strip().lower()
        return discord.utils.find(
            lambda m: m.name.lower() == name or m.display_name.lower() == name,
            guild.members
        )

    def _extract_end_message_id(self, message: discord.Message) -> int | None:
        if message.reference and message.reference.message_id:
            return message.reference.message_id
        content = message.content.strip()
        match = re.search(r"\d{17,20}", content)
        if match:
            return int(match.group(0))
        url_match = re.search(r"discord(?:app)?\.com/channels/\d+/\d+/(\d{17,20})", content)
        if url_match:
            return int(url_match.group(1))
        return None

    def _build_vh_embeds(self, title: str, text: str, suffix: str = "") -> list:
        MAX = 4096
        if not text:
            e = discord.Embed(title=title + suffix, description="No data.", color=0xff3fb9)
            e.set_footer(text="Village Game")
            return [e]
        if len(text) <= MAX:
            e = discord.Embed(title=title + suffix, description=text, color=0xff3fb9, timestamp=datetime.now())
            e.set_footer(text="Village Game")
            return [e]
        chunks, buf = [], ""
        for line in text.split("\n"):
            candidate = buf + ("\n" + line if buf else line)
            if len(candidate) > MAX:
                chunks.append(buf)
                buf = line
            else:
                buf = candidate
        if buf:
            chunks.append(buf)
        embeds = []
        for i, chunk in enumerate(chunks):
            label = f"{title} ({i+1}/{len(chunks)}){suffix}" if len(chunks) > 1 else f"{title}{suffix}"
            e = discord.Embed(title=label, description=chunk, color=0xff3fb9, timestamp=datetime.now())
            e.set_footer(text="Village Game")
            embeds.append(e)
        return embeds

    async def _refresh_board_message(self, board_channel, existing, body):
        """Edit a vote board message; if Discord refuses (old message edit limit), repost it."""
        try:
            await with_retries(lambda: existing.edit(content=body))
        except discord.HTTPException as error:
            if getattr(error, "code", None) != EDIT_LIMIT_CODE:
                raise
            try:
                await existing.delete()
            except discord.HTTPException:
                pass
            await with_retries(lambda: board_channel.send(body))

    async def aggiorna_risultati(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        vote_count_channel = discord.utils.get(ctx.guild.channels, name=guild_data["vote_count_name"])
        if not vote_count_channel:
            await ctx.send("Vote count channel not found")
            return

        fixed = [
            (
                f"# LYNCH VOTES {i}:",
                True,
                get_lynch_channel(ctx.guild, guild_data, f"lynch_channel_name{i}"),
                guild_data.get(f"lynch_votes{i}", {}),
            )
            for i in range(1, LYNCH_SESSION_COUNT + 1)
        ]
        fixed += [
            ("# LEADER VOTES:", False, get_lynch_channel(ctx.guild, guild_data, "leader_channel_name"), guild_data.get("leader_votes", {})),
            ("# LEADER VOTES 2:", False, get_lynch_channel(ctx.guild, guild_data, "leader_channel_name2"), guild_data.get("leader_votes2", {})),
        ]
        sessions = list(fixed)

        # history() is newest-first, so keep the first match per prefix and skip
        # prefixes already found, otherwise a stale duplicate would win.
        board = {}
        async for message in vote_count_channel.history(limit=50):
            if message.author != ctx.guild.me:
                continue
            for prefix, _, _, _ in sessions:
                if prefix in board:
                    continue
                if message.content.startswith(prefix):
                    board[prefix] = message
                    break
            if len(board) == len(sessions):
                break

        for prefix, trailing_newline, session_channel, votes in sessions:
            if session_channel is None:
                continue
            # A vote cast in a session channel only refreshes that session's
            # board; the other sessions are left exactly as they are.
            if channel is not None and channel.id != session_channel.id:
                continue
            voted = {ctx.guild.get_member(uid) for uid in votes.values() if ctx.guild.get_member(uid)}
            results = '\n'.join(
                f'{user.mention} has **{list(votes.values()).count(user.id)}** votes'
                for user in voted
            )
            body = f'{prefix}\n{results}{"\n" if trailing_newline else ""}'
            existing = board.get(prefix)
            if existing:
                if channel is None:
                    # Full refresh: move the board back to the bottom so the
                    # sessions stay in order.
                    await existing.delete()
                    await with_retries(lambda: vote_count_channel.send(body))
                else:
                    await self._refresh_board_message(vote_count_channel, existing, body)
            else:
                await with_retries(lambda: vote_count_channel.send(body))

    # ---- Execution vote ("letali fisiche" mechanic) ----

    async def _notify(self, channel: discord.abc.Messageable, text: str, delay: int = 8):
        """Send a short-lived notice so replies don't clutter the channel."""
        try:
            msg = await channel.send(text)
            await asyncio.sleep(delay)
            await msg.delete()
        except discord.HTTPException:
            pass

    @commands.command(name="execution", aliases=["patibolo"])
    async def execution(self, ctx, target: discord.Member):
        """Start a public execution vote for a player on the gallows (admin only).

        Multiple execution votes can run at the same time, one per target -
        they're tracked separately and never interfere with each other.
        """
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        if not ctx.author.guild_permissions.administrator:
            return

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return

        announcement_channel_name = guild_data.get("announcements_channel_name")
        announcement_channel = discord.utils.get(ctx.guild.channels, name=announcement_channel_name)
        if not announcement_channel:
            await self._notify(ctx.channel, f"Canale annunci `{announcement_channel_name}` non trovato.")
            return

        overseer_channel_name = "overseer-discussion"
        if not discord.utils.get(ctx.guild.channels, name=overseer_channel_name):
            await self._notify(ctx.channel, f"Canale privato `{overseer_channel_name}` non trovato.")
            return

        executions = active_executions.setdefault(ctx.guild.id, {})
        if str(target.id) in executions:
            await self._notify(ctx.channel, f"C'è già una votazione di esecuzione attiva per {target.display_name}.")
            return

        end_timestamp = time.time() + EXECUTION_VOTE_MINUTES * 60
        embed = discord.Embed(
            title="⚖️ Esecuzione",
            description=f"{target.mention} è sul patibolo.\nVotate entro <t:{int(end_timestamp)}:R>.",
            color=0xff3fb9,
        )
        embed.set_footer(text="Village Game")

        view = ExecutionView(self.bot, ctx.guild.id, target.id)
        message = await announcement_channel.send(embed=embed, view=view)
        view.message = message

        executions[str(target.id)] = {
            "target_id": target.id,
            "channel_id": announcement_channel.id,
            "message_id": message.id,
            "votes": {},
            "end_timestamp": end_timestamp,
        }