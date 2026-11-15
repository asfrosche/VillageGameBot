"""Small single-purpose commands grouped into one module.

Each class is a separate Cog so command names, aliases and behaviour are unchanged:
RcHome (.rchome), Scout (.scout), Infos (.info), SendRole (.settarget, .sendrole),
OSQuestions (.askos), RPSCog (.rps), ReactCog (.react).
"""
import re
from typing import Optional

import discord
from discord import Embed
from discord.ext import commands
from discord.ui import Button, View

from cogs.data_utils import load_guild_data, save_guild_data
from cogs.actions_logging_cog import AskosActionButtons, CancelOnlyView
from utils.bot_db import get_target_channel, set_target_channel
from utils.embeds import info_embed, success_embed, error_embed


# ---- from rchome_cog.py ----
class RcHome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="rchome", aliases=["rch", "rolechome", "whichhouse"])
    async def rchome(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))

        target = channel or ctx.channel
        if channel is not None and channel != ctx.channel:
            # Looking up another RoleChat's membership is staff-only, like .whorc @player.
            overseer = discord.utils.get(ctx.guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
            is_staff = ctx.author.guild_permissions.administrator or (overseer is not None and overseer in ctx.author.roles)
            if not is_staff:
                await ctx.send("Only staff can check another RoleChat. Use this command inside the RoleChat instead.", ephemeral=True)
                return
        if target.category not in (rc_cat, dead_rc, alt_cat):
            await ctx.send("Use this in a RoleChat or specify a RoleChat.", ephemeral=True)
            return

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name"))
        member_homes = guild_data.get("member_homes", {}) or {}

        players = []
        for m in target.members:
            if m.bot:
                continue
            if alive_role and alive_role in m.roles:
                players.append(m)
            elif alive_role is None:
                players.append(m)

        if not players:
            await ctx.send("No players found in that RoleChat.", ephemeral=True)
            return

        results = []
        for p in players:
            hid = member_homes.get(str(p.id))
            if not hid:
                results.append(f"{p.display_name}: No home set")
                continue
            house = ctx.guild.get_channel(int(hid))
            if house and houses_category and house.category == houses_category:
                results.append(f"{p.display_name}: {house.mention} ({house.name})")
            elif house:
                results.append(f"{p.display_name}: {house.mention} ({house.name})")
            else:
                results.append(f"{p.display_name}: Unknown house ({hid})")

        embed = discord.Embed(title=f"Home for {target.name}", description="\n".join(results), color=0xff3fb9)
        await ctx.send(embed=embed)


# ---- from scout_cog.py ----
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


# ---- from infos_cog.py ----
class Infos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def info(self, ctx, type: str = None, channel: discord.TextChannel = None, *, info_or_number: str = None):
        """Show, add, remove, edit, or reset channel infos (admin only)."""
        type = (type or "").strip()
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if type and re.match(r'<#(\d+)>', type):
                    channel_id = int(re.match(r'<#(\d+)>', type).group(1))
                    channel = ctx.guild.get_channel(channel_id)
                    if channel:
                        await self.info_show(ctx, channel, guild_data)
                    else:
                        await ctx.send(f'{type} is not a valid channel.')
                elif type.lower() == 'add':
                    if channel is None:
                        channel = ctx.channel
                    await self.info_add(ctx, channel, info_or_number, guild_data)
                elif type.lower() == 'remove':
                    if channel is None:
                        channel = ctx.channel
                    await self.info_remove(ctx, channel, info_or_number, guild_data)
                elif type.lower() == 'edit':
                    if channel is None:
                        channel = ctx.channel
                    await self.info_edit(ctx, channel, info_or_number, guild_data)
                elif type.lower() == 'reset':
                    await self.info_reset(ctx, guild_data)
                else:
                    await ctx.send(f'{type} is not a valid argument for info command.')
            else:
                await ctx.send('Guild data not loaded.')
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def info_show(self, ctx, channel, guild_data):
        channel_id = str(channel.id)
        if "infos" in guild_data and channel_id in guild_data["infos"]:
            infos = guild_data["infos"][channel_id]
            info_list = []
            for idx, info in enumerate(infos, 1):
                info_list.append(f"{idx}. {info}")
            info_list_str = "\n".join(info_list)
            embed = info_embed(
                title=f"{channel.name} infos",
                description=info_list_str,
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"No info found for {channel.name}.")

    async def info_add(self, ctx, channel, info, guild_data):
        channel_id = str(channel.id)
        if "infos" not in guild_data:
            guild_data["infos"] = {}
        if channel_id not in guild_data["infos"]:
            guild_data["infos"][channel_id] = []
        guild_data["infos"][channel_id].append(info)
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(f"Info added to {channel.name}.")

    async def info_remove(self, ctx, channel, number, guild_data):
        channel_id = str(channel.id)
        if "infos" in guild_data and channel_id in guild_data["infos"]:
            try:
                idx = int(number) - 1
                if 0 <= idx < len(guild_data["infos"][channel_id]):
                    del guild_data["infos"][channel_id][idx]
                    save_guild_data(ctx.guild.id, guild_data)
                    await ctx.send(f"Info {number} removed from {channel.name}.")
                else:
                    await ctx.send("Invalid info number.")
            except (TypeError, ValueError):
                await ctx.send("Invalid info number.")
        else:
            await ctx.send(f"No info found for {channel.name}.")

    async def info_edit(self, ctx, channel, number_and_info, guild_data):
        """
        Edit an existing info entry.
        Usage: .info edit #channel <number> <new text>
        """
        channel_id = str(channel.id)
        if "infos" not in guild_data or channel_id not in guild_data["infos"]:
            await ctx.send(f"No info found for {channel.name}.")
            return

        if not number_and_info:
            await ctx.send("Usage: `.info edit [#channel] <number> <new text>`")
            return

        parts = number_and_info.split(None, 1)
        if len(parts) < 2:
            await ctx.send("Usage: `.info edit [#channel] <number> <new text>`\nYou must provide both a number and the new text.")
            return

        try:
            idx = int(parts[0]) - 1
            new_info = parts[1]
        except ValueError:
            await ctx.send("Invalid info number. Please provide a valid integer.")
            return

        infos = guild_data["infos"][channel_id]
        if 0 <= idx < len(infos):
            old_info = infos[idx]
            infos[idx] = new_info
            save_guild_data(ctx.guild.id, guild_data)
            embed = success_embed(
                title="Info Updated",
                description=(
                    f"**Channel:** {channel.mention}\n"
                    f"**Entry #{idx + 1}**\n"
                    f"**Old:** {old_info}\n"
                    f"**New:** {new_info}"
                ),
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Invalid info number. {channel.name} has {len(infos)} entr{'y' if len(infos) == 1 else 'ies'}.")

    async def info_reset(self, ctx, guild_data):
        embedq = info_embed(
            title="Confirm you want to reset all infos",
            description="Click a button to confirm or cancel.",
        )
        confirm_view = View(timeout=60)

        async def confirm_callback(interaction):
            if interaction.user == ctx.author:
                guild_data["infos"] = {}
                save_guild_data(ctx.guild.id, guild_data)
                embedy = success_embed(
                    title="Confirmed",
                    description="All infos have been reset.",
                )
                await interaction.response.edit_message(embed=embedy, view=None)
            else:
                await interaction.response.send_message("You can't confirm this action.", ephemeral=True)

        async def cancel_callback(interaction):
            if interaction.user == ctx.author:
                embedn = error_embed(
                    title="Canceled",
                    description="Reset canceled.",
                )
                await interaction.response.edit_message(embed=embedn, view=None)
            else:
                await interaction.response.send_message("You can't cancel this action.", ephemeral=True)

        confirm_button = Button(label="✔Yes", style=discord.ButtonStyle.green)
        confirm_button.callback = confirm_callback
        cancel_button = Button(label="❌No", style=discord.ButtonStyle.red)
        cancel_button.callback = cancel_callback
        confirm_view.add_item(confirm_button)
        confirm_view.add_item(cancel_button)
        await ctx.send(embed=embedq, view=confirm_view)


# ---- from send_role.py ----
class SendRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def settarget(self, ctx, channel_id: int):
        """Set the target channel ID for sending roles (admin only)."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command.")
            return
        set_target_channel(ctx.guild.id, channel_id)
        await ctx.send(f"Target channel set to {channel_id}")

    @commands.command(aliases=["sr"])
    async def sendrole(self, ctx, *, player: str = None):
        """Reply to a message to send its content to the target channel (admin only)."""
        if not ctx.message.reference or not isinstance(ctx.message.reference.resolved, discord.Message):
            await ctx.send("You must reply to the message you want to send.")
            return
        replied_message = ctx.message.reference.resolved
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You need admin permissions in this server to use this command.")
            return
        try:
            target_channel_id = get_target_channel(ctx.guild.id)
            if not target_channel_id:
                await ctx.send("No target channel set. Use `.settarget #channel` first.")
                return
            target_channel = self.bot.get_channel(target_channel_id)
            if not target_channel:
                await ctx.send("Couldn't find the target channel.")
                return
            target_guild = target_channel.guild
            target_member = target_guild.get_member(ctx.author.id)
            librarian_role_id = 1329517813626310679
            has_admin = target_member.guild_permissions.administrator
            has_librarian_role = any(role.id == librarian_role_id for role in target_member.roles)
            if not (has_admin or has_librarian_role):
                await ctx.send("You need to be an admin or have the 'Librarian' role in the **target server** to use this command.")
                return
            message_to_send = replied_message.content
            if player:
                message_to_send += f"\n\nPlayed by **{player}**"
            if replied_message.attachments:
                files = [await a.to_file() for a in replied_message.attachments]
                await target_channel.send(content=message_to_send, files=files)
            else:
                await target_channel.send(message_to_send)
            await ctx.send(f"Role sent to {target_channel.mention}")
        except Exception as e:
            await ctx.send(f"Error: {e}")


# ---- from os_questions_cog.py ----
class OSQuestions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_or_create_log_channel(self, guild: discord.Guild, guild_data: dict):
        channel_name = guild_data.get("os_questions_log_channel_name") or "log-actions"
        log_channel = discord.utils.get(guild.text_channels, name=channel_name)
        if log_channel:
            return log_channel

        os_role = discord.utils.get(guild.roles, name=guild_data.get("overseer_role_name"))
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
        }

        if os_role:
            overwrites[os_role] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                read_message_history=True,
            )

        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
            )

        try:
            log_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                reason=".askos - auto created log-actions channel",
            )
            return log_channel
        except (discord.Forbidden, discord.HTTPException):
            return None

    @commands.command(name="askos", aliases=["osq", "askoverseer"])
    async def askos(self, ctx, *, question: str):
        if ctx.author.bot or ctx.guild is None:
            return

        guild = ctx.guild
        guild_data = load_guild_data(guild.id)
        if not guild_data:
            return

        def get_role(name):
            return discord.utils.get(guild.roles, name=name)

        def get_category(name):
            return discord.utils.get(guild.categories, name=name)

        alive_role = get_role(guild_data["alive_role_name"])
        sponsor_role = get_role(guild_data["sponsor_role_name"])
        alt_role = get_role(guild_data["alt_role_name"])
        dead_role = get_role(guild_data["dead_role_name"])
        os_role = get_role(guild_data["overseer_role_name"])
        rc_category = get_category(guild_data["rc_category_name"])
        dead_rc_category = get_category(guild_data["dead_rc_category_name"])
        alt_category = get_category(guild_data["alt_category_name"])

        allowed_roles = {alive_role, sponsor_role, alt_role, dead_role}
        allowed_categories = {rc_category, dead_rc_category, alt_category}

        if ctx.channel.category not in allowed_categories:
            await ctx.send("You can only use `.askos` in an RC, Dead RC, or Alt.", ephemeral=True)
            return

        if not any(role in ctx.author.roles for role in allowed_roles):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)
            return

        if not question or not question.strip():
            await ctx.send("You need to write a question to ask the overseers.", ephemeral=True)
            return

        log_channel = await self._get_or_create_log_channel(guild, guild_data)
        if not log_channel:
            await ctx.send("Could not find or create the `log-actions` channel. Contact an admin.", ephemeral=True)
            return

        jump_url = ctx.message.jump_url

        content = question.strip() or "*No text*"
        jump_link = f"[Jump to Message]({jump_url})"

        embed_log = Embed(color=0xff3fb9)
        embed_log.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed_log.description = (
            f"**Message:**\n{content}\n\n"
            f"**Channel:** {ctx.channel.mention}\n"
            f"**Time:** <t:{int(ctx.message.created_at.timestamp())}:R>\n"
            f"{jump_link}"
        )
        embed_log.set_footer(text="⏳ Pending")

        embed_user = Embed(color=0xff3fb9)
        embed_user.description = (
            f"**Question:**\n{content}\n\n"
            f"**Log Channel:** {log_channel.mention}\n"
            f"**Time:** <t:{int(ctx.message.created_at.timestamp())}:R>\n"
            f"{jump_link}"
        )
        embed_user.set_footer(text="⏳ Pending")

        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        if os_role:
            tag_message = await log_channel.send(f"{os_role.mention}")
            await tag_message.delete()

        log_message = await log_channel.send(embed=embed_log)

        user_message = await ctx.send(embed=embed_user)

        log_view = AskosActionButtons(
            user_embed=user_message,
            log_embed=log_message,
            user_embed_obj=embed_log.copy(),
            log_embed_obj=embed_log.copy(),
        )
        user_view = CancelOnlyView(
            user_embed=user_message,
            log_embed=log_message,
            user_embed_obj=embed_user,
            log_embed_obj=embed_log,
        )

        await log_message.edit(view=log_view)
        await user_message.edit(view=user_view)


# ---- from rps_cog.py ----
class RPSView(discord.ui.View):
    def __init__(self, author_id: int, opponent_id: int, author_choice: Optional[str] = None, opponent_choice: Optional[str] = None):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.opponent_id = opponent_id
        self.author_choice = author_choice
        self.opponent_choice = opponent_choice
        self.message = None
        self._update_buttons()
    
    def _update_buttons(self):
        self.clear_items()
        
        if self.author_choice is None and self.opponent_choice is None:
            rock1 = discord.ui.Button(label="Rock", style=discord.ButtonStyle.secondary, emoji="🪨")
            rock1.callback = self.make_callback("rock", self.author_id)
            paper1 = discord.ui.Button(label="Paper", style=discord.ButtonStyle.secondary, emoji="📄")
            paper1.callback = self.make_callback("paper", self.author_id)
            scissors1 = discord.ui.Button(label="Scissors", style=discord.ButtonStyle.secondary, emoji="✂️")
            scissors1.callback = self.make_callback("scissors", self.author_id)
            self.add_item(rock1)
            self.add_item(paper1)
            self.add_item(scissors1)
            
            rock2 = discord.ui.Button(label="Rock", style=discord.ButtonStyle.secondary, emoji="🪨")
            rock2.callback = self.make_callback("rock", self.opponent_id)
            paper2 = discord.ui.Button(label="Paper", style=discord.ButtonStyle.secondary, emoji="📄")
            paper2.callback = self.make_callback("paper", self.opponent_id)
            scissors2 = discord.ui.Button(label="Scissors", style=discord.ButtonStyle.secondary, emoji="✂️")
            scissors2.callback = self.make_callback("scissors", self.opponent_id)
            self.add_item(rock2)
            self.add_item(paper2)
            self.add_item(scissors2)
        elif self.author_choice is None and self.opponent_choice is not None:
            rock1 = discord.ui.Button(label="Rock", style=discord.ButtonStyle.primary, emoji="🪨")
            rock1.callback = self.make_callback("rock", self.author_id)
            paper1 = discord.ui.Button(label="Paper", style=discord.ButtonStyle.primary, emoji="📄")
            paper1.callback = self.make_callback("paper", self.author_id)
            scissors1 = discord.ui.Button(label="Scissors", style=discord.ButtonStyle.primary, emoji="✂️")
            scissors1.callback = self.make_callback("scissors", self.author_id)
            self.add_item(rock1)
            self.add_item(paper1)
            self.add_item(scissors1)
        elif self.opponent_choice is None and self.author_choice is not None:
            rock2 = discord.ui.Button(label="Rock", style=discord.ButtonStyle.primary, emoji="🪨")
            rock2.callback = self.make_callback("rock", self.opponent_id)
            paper2 = discord.ui.Button(label="Paper", style=discord.ButtonStyle.primary, emoji="📄")
            paper2.callback = self.make_callback("paper", self.opponent_id)
            scissors2 = discord.ui.Button(label="Scissors", style=discord.ButtonStyle.primary, emoji="✂️")
            scissors2.callback = self.make_callback("scissors", self.opponent_id)
            self.add_item(rock2)
            self.add_item(paper2)
            self.add_item(scissors2)
    
    def make_callback(self, choice, player_id):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != player_id:
                await interaction.response.send_message("This isn't your move!", ephemeral=True)
                return
            if player_id == self.author_id and self.author_choice is not None:
                await interaction.response.send_message("You already made your choice!", ephemeral=True)
                return
            if player_id == self.opponent_id and self.opponent_choice is not None:
                await interaction.response.send_message("You already made your choice!", ephemeral=True)
                return
            
            if player_id == self.author_id:
                self.author_choice = choice
            else:
                self.opponent_choice = choice
            
            self._update_buttons()
            
            if self.author_choice and self.opponent_choice:
                result_embed = self.get_result_embed()
                await interaction.response.edit_message(embed=result_embed, view=self)
                self.stop()
            else:
                embed = self.get_status_embed()
                await interaction.response.edit_message(embed=embed, view=self)
        return callback
    
    def get_status_embed(self):
        embed = discord.Embed(title="Rock Paper Scissors", color=0x9b59b6)
        author = self.message.guild.get_member(self.author_id) if self.message and self.message.guild else None
        opponent = self.message.guild.get_member(self.opponent_id) if self.message and self.message.guild else None
        a_name = author.display_name if author else f"Player 1"
        o_name = opponent.display_name if opponent else f"Player 2"
        
        if self.author_choice and not self.opponent_choice:
            embed.description = f"**{a_name}** has chosen!\n\n**{o_name}**, it's your turn - pick Rock, Paper, or Scissors below."
        elif self.opponent_choice and not self.author_choice:
            embed.description = f"**{o_name}** has chosen!\n\n**{a_name}**, it's your turn - pick Rock, Paper, or Scissors below."
        else:
            embed.description = f"**{a_name}** vs **{o_name}**\n\nBoth players pick below. Choices are hidden until both pick!"
        embed.set_footer(text="Choices are hidden until both players have picked")
        return embed
    
    def get_result_embed(self):
        author = self.message.guild.get_member(self.author_id) if self.message and self.message.guild else None
        opponent = self.message.guild.get_member(self.opponent_id) if self.message and self.message.guild else None
        a_name = author.display_name if author else f"Player 1"
        o_name = opponent.display_name if opponent else f"Player 2"
        
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        a_choice = self.author_choice
        o_choice = self.opponent_choice
        
        embed = discord.Embed(title="Rock Paper Scissors - Results", color=0x2ecc71)
        embed.add_field(name=f"{a_name}", value=f"{emojis[a_choice]} {a_choice.title()}", inline=True)
        embed.add_field(name="vs", value="⚔️", inline=True)
        embed.add_field(name=f"{o_name}", value=f"{emojis[o_choice]} {o_choice.title()}", inline=True)
        
        if a_choice == o_choice:
            embed.description = "**It's a tie!**"
            embed.color = 0xf1c40f
        elif (a_choice == "rock" and o_choice == "scissors") or \
             (a_choice == "paper" and o_choice == "rock") or \
             (a_choice == "scissors" and o_choice == "paper"):
            embed.description = f"**{a_name} wins!**"
            embed.color = 0x2ecc71
        else:
            embed.description = f"**{o_name} wins!**"
            embed.color = 0xe74c3c
        
        return embed

class RPSCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="rps")
    async def rps(self, ctx, opponent: discord.Member = None):
        if opponent is None:
            await ctx.send("You need to challenge someone! Usage: `.rps @user`", ephemeral=True)
            return
        if opponent.bot:
            await ctx.send("You can't challenge a bot!", ephemeral=True)
            return
        if opponent.id == ctx.author.id:
            await ctx.send("You can't challenge yourself!", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Rock Paper Scissors",
            description=f"**{ctx.author.display_name}** vs **{opponent.display_name}**\n\nBoth players pick below. Choices are hidden until both pick!",
            color=0x9b59b6
        )
        embed.set_footer(text="Choices are hidden until both players have picked")
        
        view = RPSView(ctx.author.id, opponent.id)
        message = await ctx.send(embed=embed, view=view)
        view.message = message


# ---- from react_cog.py ----
# Discord allows at most 20 distinct reactions on a single message.
MAX_REACTIONS = 20

KEYCAP_EMOJIS = {
    0: "0️⃣",
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
}

# 🇦 … 🇿, in A-Z order.
REGIONAL_INDICATORS = {chr(ord("a") + i): chr(0x1F1E6 + i) for i in range(26)}

# Discord only lets a message hold one reaction per emoji, so a repeated letter
# can't be added twice. These are the visual stand-ins used for the 2nd, 3rd…
# occurrence of a letter (e.g. `hello` → 🇭 🇪 🇱 1️⃣ 🇴, `see` → 🇸 🇪 3️⃣).
LETTER_ALTERNATES = {
    "a": ("4️⃣", "🅰️"),
    "b": ("8️⃣", "🅱️"),
    "c": ("©️",),
    "d": ("🌓",),
    "e": ("3️⃣",),
    "f": ("🚩",),
    "g": ("6️⃣", "9️⃣"),
    "h": ("♓️",),
    "i": ("❗", "ℹ️"),
    "j": ("🪝",),
    "k": ("🔑",),
    "l": ("1️⃣",),
    "m": ("Ⓜ️",),
    "n": ("♑",),
    "o": ("0️⃣", "🅾️"),
    "p": ("🅿️",),
    "q": ("🔍",),
    "r": ("®️",),
    "s": ("5️⃣", "💲"),
    "t": ("7️⃣", "➕"),
    "u": ("⛎",),
    "v": ("✌️",),
    "w": ("〰️",),
    "x": ("✖️", "❌"),
    "y": ("🌱",),
    "z": ("2️⃣", "💤"),
}

RANGE_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
TOKEN_SPLIT_RE = re.compile(r"[,\s]+")
CUSTOM_EMOJI_RE = re.compile(r"^<a?:\w+:\d+>$")


def spell_word(word: str):
    """Spell ``word`` with letter emojis, substituting repeated letters.

    Returns ``(emojis, dropped)``. ``dropped`` counts repeated characters that
    ran out of stand-ins (normally only for words with 3+ of the same letter).
    Literal digits mixed into the word become keycaps; punctuation is ignored.
    """
    emojis = []
    emitted_digits = set()
    # Literal digits win over letter stand-ins, so reserve them up front.
    used = {
        KEYCAP_EMOJIS[int(ch)] for ch in word if ch in "0123456789"
    }
    dropped = 0

    for ch in word:
        key = ch.lower()

        if key in REGIONAL_INDICATORS:
            candidates = (REGIONAL_INDICATORS[key],) + LETTER_ALTERNATES.get(key, ())
            for emoji in candidates:
                if emoji not in used:
                    used.add(emoji)
                    emojis.append(emoji)
                    break
            else:
                dropped += 1
            continue

        if ch in "0123456789":
            emoji = KEYCAP_EMOJIS[int(ch)]
            if emoji in emitted_digits:
                dropped += 1
                continue
            emitted_digits.add(emoji)
            emojis.append(emoji)

    return emojis, dropped


def parse_react_args(raw: str):
    """Turn `.react` arguments into ``(emojis, unknown)``.

    ``emojis`` is ordered and de-duplicated. ``unknown`` holds numbers that
    have no keycap (e.g. ``20``) and words that cannot be spelled out.
    """
    emojis = []
    unknown = []

    def add(emoji: str) -> None:
        if emoji not in emojis:
            emojis.append(emoji)

    # Allow "1 - 10" as well as "1-10".
    raw = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", raw or "")

    for token in TOKEN_SPLIT_RE.split(raw.strip()):
        if not token:
            continue

        range_match = RANGE_RE.match(token)
        if range_match:
            start, end = sorted(int(n) for n in range_match.groups())
            for number in range(start, end + 1):
                if number in KEYCAP_EMOJIS:
                    add(KEYCAP_EMOJIS[number])
                else:
                    unknown.append(str(number))
            continue

        if token.isdigit():
            number = int(token)
            if number in KEYCAP_EMOJIS:
                add(KEYCAP_EMOJIS[number])
            else:
                unknown.append(token)
            continue

        if CUSTOM_EMOJI_RE.match(token):
            add(token)
            continue

        if any(ch.isalpha() for ch in token):
            # Word mode: spell it out. Repeated letters get a lookalike
            # stand-in because Discord can't add the same reaction twice.
            spelled, _dropped = spell_word(token)
            if spelled:
                for emoji in spelled:
                    add(emoji)
            else:
                unknown.append(token)
            continue

        # Anything else is assumed to be a literal unicode emoji. Plain ASCII
        # punctuation (a stray "-", "!", etc.) can't be an emoji.
        if token.isascii():
            unknown.append(token)
        else:
            add(token)

    return emojis, unknown


class ReactCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="react")
    async def react(self, ctx, *, args: str = None):
        """Add reactions to the message you reply to (admin/overseer only)."""
        if ctx.guild is None:
            return

        guild_data = load_guild_data(ctx.guild.id) or {}
        overseer_role = discord.utils.get(
            ctx.guild.roles, name=guild_data.get("overseer_role_name")
        )
        is_overseer = overseer_role is not None and overseer_role in ctx.author.roles
        if not (ctx.author.guild_permissions.administrator or is_overseer):
            await ctx.send("You don't have enough perms to use this command")
            return

        if not ctx.message.reference or not ctx.message.reference.message_id:
            await ctx.send(
                "❌ Reply to the message you want me to react to.\n"
                "Examples: `.react 1,2,3` · `.react 1-10` · `.react ✅` · `.react word`"
            )
            return

        if not args or not args.strip():
            await ctx.send(
                "❌ Tell me what to react with.\n"
                "Examples: `.react 1,2,3` · `.react 1-10` · `.react ✅` · `.react word`"
            )
            return

        emojis, unknown = parse_react_args(args)
        if not emojis:
            await ctx.send(f"❌ I couldn't understand any of that: `{args}`")
            return

        target = ctx.message.reference.resolved
        if not isinstance(target, discord.Message):
            try:
                target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await ctx.send("❌ I can't access the message you replied to.")
                return

        # Respect Discord's 20-reactions-per-message limit.
        existing = {str(reaction.emoji) for reaction in target.reactions}
        to_add = [emoji for emoji in emojis if emoji not in existing]
        room = MAX_REACTIONS - len(existing)
        if room <= 0 or not to_add:
            if room <= 0:
                await ctx.send(
                    f"❌ That message already has {MAX_REACTIONS} different reactions "
                    "(Discord's limit)."
                )
            else:
                await ctx.send("❌ All of those reactions are already on that message.")
            return

        truncated = len(to_add) > room
        to_add = to_add[:room]

        failed = []
        for emoji in to_add:
            try:
                await target.add_reaction(emoji)
            except (discord.Forbidden, discord.HTTPException):
                failed.append(emoji)

        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        problems = unknown + failed
        if problems:
            shown = ", ".join(f"`{item}`" for item in problems[:10])
            extra = f" (+{len(problems) - 10} more)" if len(problems) > 10 else ""
            await ctx.send(f"⚠️ Couldn't react with: {shown}{extra}")
        if truncated:
            await ctx.send(
                f"⚠️ Only added {room} reaction(s) — a message can hold at most "
                f"{MAX_REACTIONS} different reactions."
            )


async def setup(bot):
    await bot.add_cog(RcHome(bot))
    await bot.add_cog(Scout(bot))
    await bot.add_cog(Infos(bot))
    await bot.add_cog(SendRole(bot))
    await bot.add_cog(OSQuestions(bot))
    await bot.add_cog(RPSCog(bot))
    await bot.add_cog(ReactCog(bot))
