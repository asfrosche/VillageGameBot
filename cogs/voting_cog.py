import re
import asyncio
import discord
import datetime
from datetime import datetime
from discord.ext import commands
from cogs.data_utils import load_guild_data, save_guild_data

class Voting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def vote(self, ctx, user: discord.Member, channel: discord.TextChannel = None):
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
            prompt = await ctx.send("Reply to this message with a reference to the **end message**.")
            try:
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel and m.reference and m.reference.message_id == prompt.id
                reply = await self.bot.wait_for("message", check=check, timeout=60)
                end_id = reply.reference.resolved.id if reply.reference.resolved else None
                if not end_id:
                    await ctx.send("Could not resolve the end message.")
                    return
                end_message = await ctx.channel.fetch_message(end_id)
            except asyncio.TimeoutError:
                await ctx.send("Timed out waiting for the end message reference.")
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
                        parts.append("")
                history_lines.append(f"**{vname}**:\n" + " \u2192 ".join(parts))

        history_text = "\n\n".join(history_lines) if history_lines else "No vote history."

        for embed in self._build_vh_embeds("Vote Count", count_text, range_label):
            await ctx.send(embed=embed)
        for embed in self._build_vh_embeds("Vote History", history_text, range_label):
            await ctx.send(embed=embed)

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