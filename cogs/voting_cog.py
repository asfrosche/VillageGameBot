import re
import time
import asyncio
import discord
import datetime
from datetime import datetime, timedelta
from discord.ext import commands
from cogs.data_utils import load_guild_data, save_guild_data

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
                if ctx.channel == discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name1"]):
                    channel = ctx.channel
                elif ctx.channel == discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name2"]):
                    channel = ctx.channel
                elif ctx.channel == discord.utils.get(ctx.guild.channels, name=guild_data["leader_channel_name"]):
                    channel = ctx.channel
                else:
                    channel = discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name1"])
            if guild_data["voteinrc"] is False:
                channel = ctx.channel
            lynch_channel_names = [guild_data["lynch_channel_name1"], guild_data["lynch_channel_name2"]]
            lynch_channels = [discord.utils.get(ctx.guild.channels, name=name) for name in lynch_channel_names]
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            is_rc_channel = False
            if rc_category and ctx.channel:
                if ctx.channel in rc_category.channels:
                    is_rc_channel = True
                else:
                    is_rc_channel = False
            else:
                is_rc_channel = False
            if guild_data["voteinrc"] is True:
                if is_rc_channel is False:
                    await ctx.send("You can only vote in your RoleChat.")
                    return
            for lynch_channel in lynch_channels:
                if lynch_channel and channel.id == lynch_channel.id:
                    lynch_votes = guild_data["lynch_votes1"] if lynch_channel.name == guild_data["lynch_channel_name1"] else guild_data["lynch_votes2"]
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
            leader_channel = discord.utils.get(ctx.guild.channels, name=guild_data["leader_channel_name"])
            if leader_channel and channel.id == leader_channel.id:
                leader_votes = guild_data["leader_votes"]
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
                if ctx.channel == discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name1"]):
                    channel = ctx.channel
                elif ctx.channel == discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name2"]):
                    channel = ctx.channel
                elif ctx.channel == discord.utils.get(ctx.guild.channels, name=guild_data["leader_channel_name"]):
                    channel = ctx.channel
                else:
                    channel = discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name1"])
            if guild_data["voteinrc"] is False:
                channel = ctx.channel
            lynch_channel_names = [guild_data["lynch_channel_name1"], guild_data["lynch_channel_name2"]]
            lynch_channels = [discord.utils.get(ctx.guild.channels, name=name) for name in lynch_channel_names]
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            is_rc_channel = False
            if rc_category and ctx.channel:
                if ctx.channel in rc_category.channels:
                    is_rc_channel = True
                else:
                    is_rc_channel = False
            else:
                is_rc_channel = False
            if guild_data["voteinrc"] is True:
                if is_rc_channel is False:
                    await ctx.send("You can only vote in your RoleChat.")
                    return
            for lynch_channel in lynch_channels:
                if lynch_channel and channel.id == lynch_channel.id:
                    lynch_votes = guild_data["lynch_votes1"] if lynch_channel.name == guild_data["lynch_channel_name1"] else guild_data["lynch_votes2"]
                    voter_id = str(ctx.author.id)
                    if voter_id not in lynch_votes:
                        await ctx.send(f"{ctx.author.display_name}, you didn't vote yet")
                    else:
                        del lynch_votes[voter_id]
                        await ctx.send(f'{ctx.author.display_name} abstains')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            leader_channel = discord.utils.get(ctx.guild.channels, name=guild_data["leader_channel_name"])
            if leader_channel and channel.id == leader_channel.id:
                leader_votes = guild_data["leader_votes"]
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
                channel = discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name1"])
            if guild_data["voteinrc"] is False:
                channel = ctx.channel
            lynch_channel_names = [guild_data["lynch_channel_name1"], guild_data["lynch_channel_name2"]]
            lynch_channels = [discord.utils.get(ctx.guild.channels, name=name) for name in lynch_channel_names]
            for lynch_channel in lynch_channels:
                if lynch_channel and ctx.channel.id == lynch_channel.id:
                    lynch_votes = guild_data["lynch_votes1"] if lynch_channel.name == guild_data["lynch_channel_name1"] else guild_data["lynch_votes2"]
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
            leader_channel = discord.utils.get(ctx.guild.channels, name=guild_data["leader_channel_name"])
            if leader_channel and ctx.channel.id == leader_channel.id:
                leader_votes = guild_data["leader_votes"]
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
                channel = discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name1"])
            if guild_data["voteinrc"] is False:
                channel = ctx.channel
            lynch_channel_names = [guild_data["lynch_channel_name1"], guild_data["lynch_channel_name2"]]
            lynch_channels = [discord.utils.get(ctx.guild.channels, name=name) for name in lynch_channel_names]
            for lynch_channel in lynch_channels:
                if lynch_channel and ctx.channel.id == lynch_channel.id:
                    lynch_votes = guild_data["lynch_votes1"] if lynch_channel.name == guild_data["lynch_channel_name1"] else guild_data["lynch_votes2"]
                    if str(user.id) not in lynch_votes:
                        await ctx.send(f"{user.display_name} didn't vote yet")
                    else:
                        del lynch_votes[str(user.id)]
                        await ctx.send(f'{user.display_name} vote has been removed by {ctx.author.display_name}')
                    save_guild_data(ctx.guild.id, guild_data)
                    await self.aggiorna_risultati(ctx, channel)
                    return
            leader_channel = discord.utils.get(ctx.guild.channels, name=guild_data["leader_channel_name"])
            if leader_channel and ctx.channel.id == leader_channel.id:
                leader_votes = guild_data["leader_votes"]
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
            votes_sessions = {"LYNCH SESSION 1": guild_data["lynch_votes1"], "LYNCH SESSION 2": guild_data["lynch_votes2"], "LEADER ELECTION": guild_data["leader_votes"]}
            embeds = []
            valid_types = ['lynch1', 'lynch2', 'leader']
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
            if not embeds:
                await ctx.send("No votes in any session.")
            elif type is None:
                for embed in embeds:
                    await ctx.send(embed=embed)
            elif type.lower() in valid_types:
                index = valid_types.index(type.lower())
                if index < len(embeds):
                    await ctx.send(embed=embeds[index])
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
                guild_data["lynch_votes1"] = {}
                guild_data["lynch_votes2"] = {}
                guild_data["leader_votes"] = {}
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.send('Votes have been reset')
                await self.aggiorna_risultati(ctx)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    @commands.command(aliases=["vh"])
    async def votehistory(self, ctx, mode: str = None):
        """Scan and display vote history with optional mode (grouped/range)."""
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
        user_actions = {}

        start_ts = int(start_message.created_at.timestamp())
        range_label = f" (Start: <t:{start_ts}:T>)"

        async with ctx.typing():
            kwargs = {"after": start_message, "oldest_first": True}
            if end_message:
                kwargs["before"] = end_message
                range_label += f" — End: <t:{int(end_message.created_at.timestamp())}:T>"
            async for message in ctx.channel.history(**kwargs):
                if message.author.bot:
                    continue
                content = message.content.strip()
                uid = message.author.id
                lower = content.lower()

                if lower.startswith(prefix + "abstain"):
                    user_actions.setdefault(uid, []).append({"type": "abstain"})
                elif lower.startswith(prefix + "vote "):
                    if message.mentions:
                        target = message.mentions[0]
                        user_actions.setdefault(uid, []).append({"type": "vote", "target_id": target.id})
                    else:
                        name = content[len(prefix) + 5:].strip()
                        if name:
                            member = discord.utils.find(lambda m: m.name == name or m.display_name == name, ctx.guild.members)
                            if member:
                                user_actions.setdefault(uid, []).append({"type": "vote", "target_id": member.id})

        if not user_actions:
            await ctx.send(f"No votes found in the scanned range.{range_label}")
            return

        current_votes = {}
        for uid, actions in user_actions.items():
            last = actions[-1]
            if last["type"] == "vote":
                current_votes.setdefault(last["target_id"], []).append(uid)

        sorted_targets = sorted(current_votes.items(), key=lambda x: len(x[1]), reverse=True)

        count_lines = []
        for target_id, voter_ids in sorted_targets:
            target = ctx.guild.get_member(target_id)
            if not target:
                continue
            names = []
            for vid in voter_ids:
                m = ctx.guild.get_member(vid)
                names.append(m.display_name if m else "Unknown")
            count_lines.append(f"**{target.display_name}** ({len(voter_ids)}): {', '.join(names)}")

        count_text = "\n".join(count_lines) if count_lines else "No active votes."

        if is_grouped or is_range:
            target_history = {}
            for uid, actions in user_actions.items():
                voter = ctx.guild.get_member(uid)
                vname = voter.display_name if voter else "Unknown"
                for a in actions:
                    if a["type"] == "vote":
                        target_history.setdefault(a["target_id"], []).append(vname)
            history_lines = []
            for tid, vnames in target_history.items():
                target = ctx.guild.get_member(tid)
                if not target:
                    continue
                history_lines.append(f"**{target.display_name}**:\n" + " \u2192 ".join(vnames))
        else:
            history_lines = []
            for uid, actions in user_actions.items():
                voter = ctx.guild.get_member(uid)
                vname = voter.display_name if voter else "Unknown"
                parts = []
                for a in actions:
                    if a["type"] == "vote":
                        t = ctx.guild.get_member(a["target_id"])
                        parts.append(t.display_name if t else "Unknown")
                    else:
                        parts.append("Ø")
                history_lines.append(f"**{vname}**:\n" + " \u2192 ".join(parts))

        history_text = "\n\n".join(history_lines) if history_lines else "No vote history."

        for embed in self._build_vh_embeds("Vote Count", count_text, range_label):
            await ctx.send(embed=embed)
        for embed in self._build_vh_embeds("Vote History", history_text, range_label):
            await ctx.send(embed=embed)

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

    async def aggiorna_risultati(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            vote_count_channel = discord.utils.get(ctx.guild.channels, name=guild_data["vote_count_name"])
            if vote_count_channel:
                lynch_message1 = None
                lynch_message2 = None
                leader_message = None
                lynch_channel1 = discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name1"])
                lynch_channel2 = discord.utils.get(ctx.guild.channels, name=guild_data["lynch_channel_name2"])
                leader_channel = discord.utils.get(ctx.guild.channels, name=guild_data["leader_channel_name"])
                async for message in vote_count_channel.history(limit=10):
                    if message.author != ctx.guild.me:
                        continue
                    if message.content.startswith('# LYNCH VOTES 1:'):
                        lynch_message1 = message
                    elif message.content.startswith('# LYNCH VOTES 2:'):
                        lynch_message2 = message
                    elif message.content.startswith('# LEADER VOTES:'):
                        leader_message = message
                lynch_votes1 = {ctx.guild.get_member(user_id) for user_id in guild_data.get("lynch_votes1", {}).values() if ctx.guild.get_member(user_id)}
                lynch_votes2 = {ctx.guild.get_member(user_id) for user_id in guild_data.get("lynch_votes2", {}).values() if ctx.guild.get_member(user_id)}
                leader_votes = {ctx.guild.get_member(user_id) for user_id in guild_data.get("leader_votes", {}).values() if ctx.guild.get_member(user_id)}
                vote_count_lynch1 = {user: list(guild_data["lynch_votes1"].values()).count(user.id) for user in lynch_votes1}
                vote_count_lynch2 = {user: list(guild_data["lynch_votes2"].values()).count(user.id) for user in lynch_votes2}
                vote_count_leader = {user: list(guild_data["leader_votes"].values()).count(user.id) for user in leader_votes}
                results_lynch1 = '\n'.join(f'{user.mention} has **{count}** votes' for user, count in vote_count_lynch1.items())
                results_lynch2 = '\n'.join(f'{user.mention} has **{count}** votes' for user, count in vote_count_lynch2.items())
                results_leader = '\n'.join(f'{user.mention} has **{count}** votes' for user, count in vote_count_leader.items())
                if lynch_channel1:
                    if lynch_message1:
                        if channel:
                            if channel == lynch_channel1:
                                await lynch_message1.edit(content=f'# LYNCH VOTES 1:\n{results_lynch1}\n')
                        else:
                            await lynch_message1.delete()
                            await vote_count_channel.send(f'# LYNCH VOTES 1:\n{results_lynch1}\n')
                    else:
                        lynch_message1 = await vote_count_channel.send(f'# LYNCH VOTES 1:\n{results_lynch1}\n')
                if lynch_channel2:
                    if lynch_message2:
                        if channel:
                            if channel == lynch_channel2:
                                await lynch_message2.edit(content=f'# LYNCH VOTES 2:\n{results_lynch2}\n')
                        else:
                            await lynch_message2.delete()
                            await vote_count_channel.send(f'# LYNCH VOTES 2:\n{results_lynch2}\n')
                    else:
                        lynch_message2 = await vote_count_channel.send(f'# LYNCH VOTES 2:\n{results_lynch2}\n')
                if leader_channel:
                    if leader_message:
                        if channel:
                            if channel == leader_channel:
                                await leader_message.edit(content=f'# LEADER VOTES:\n{results_leader}')
                        else:
                            await leader_message.delete()
                            await vote_count_channel.send(f'# LEADER VOTES:\n{results_leader}')
                    else:
                        leader_message = await vote_count_channel.send(f'# LEADER VOTES:\n{results_leader}')
            else:
                await ctx.send("Vote count channel not found")
        else:
            await ctx.send("Guild data not loaded")

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