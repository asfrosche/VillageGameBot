import discord
from cogs.data_utils import save_guild_data  # kept: tests patch this name
from discord.ext import commands
from datetime import datetime, timezone
from discord import Embed, ui
import re
from cogs.data_utils import load_guild_data
from cogs.moving_cog import _find_house
from cogs.status_cog import check_visitblock_warning, check_channel_warning


class ActionButtons(ui.View):
    def __init__(
        self,
        user_embed: discord.Message,
        log_embed: discord.Message,
        user_embed_obj: Embed,
        log_embed_obj: Embed,
        timeout=86400,
    ):
        super().__init__(timeout=timeout)
        self.user_embed = user_embed
        self.log_embed = log_embed
        self.user_embed_obj = user_embed_obj
        self.log_embed_obj = log_embed_obj

    async def update_embed(self, interaction: discord.Interaction, status_text: str, color: int, track: bool = False):
        ts = int(datetime.now(timezone.utc).timestamp())
        timestamp = f"<t:{ts}:R> • <t:{ts}:T>"
        footer_text = f"{status_text} • {timestamp} by {interaction.user.display_name}"

        self.user_embed_obj.set_footer(text=footer_text)
        self.user_embed_obj.color = discord.Color(color)

        self.log_embed_obj.set_footer(text=footer_text)
        self.log_embed_obj.color = discord.Color(color)
        self.log_embed_obj.remove_author()

        # A deferred interaction can't use response.edit_message; edit the message directly instead.
        if interaction.response.is_done():
            await interaction.message.edit(embed=self.log_embed_obj, view=None)
        else:
            await interaction.response.edit_message(embed=self.log_embed_obj, view=None)
        await self.user_embed.edit(embed=self.user_embed_obj, view=None)
        await self.log_embed.edit(embed=self.log_embed_obj, view=None)

        if track and interaction.guild:
            try:
                guild_data = load_guild_data(interaction.guild.id)
                if guild_data is not None:
                    completed = guild_data.get("completed_actions", {})
                    user_id = str(interaction.user.id)
                    completed[user_id] = completed.get(user_id, 0) + 1
                    guild_data["completed_actions"] = completed
                    from cogs.data_utils import save_guild_data
                    save_guild_data(interaction.guild.id, guild_data)
            except Exception:
                pass

        self.stop()

    async def _check_permission(self, interaction: discord.Interaction):
        guild_data = load_guild_data(interaction.guild.id)
        if not guild_data:
            await interaction.response.send_message("You don't have permission to use this button.", ephemeral=True)
            return False
        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(interaction.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(interaction.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(interaction.guild.roles, name=guild_data["dead_role_name"])
        if (
            interaction.user.guild_permissions.administrator
            or (alive_role and alive_role in interaction.user.roles)
            or (sponsor_role and sponsor_role in interaction.user.roles)
            or (alt_role and alt_role in interaction.user.roles)
            or (dead_role and dead_role in interaction.user.roles)
        ):
            return True
        await interaction.response.send_message("You don't have permission to use this button.", ephemeral=True)
        return False

    @ui.button(label="Done", style=discord.ButtonStyle.success, emoji="✅")
    async def done_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_permission(interaction):
            return
        await self.update_embed(interaction, "✅ Done", 0x00FF00, track=True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_permission(interaction):
            return
        await self.update_embed(interaction, "❌ Cancelled", 0xFF0000)


class AskosActionButtons(ActionButtons):
    @ui.button(label="Yes", style=discord.ButtonStyle.success, emoji="✅")
    async def yes_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_permission(interaction):
            return
        await self.update_embed(interaction, "✅ Yes", 0x00FF00, track=True)

    @ui.button(label="No", style=discord.ButtonStyle.danger, emoji="❌")
    async def no_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_permission(interaction):
            return
        await self.update_embed(interaction, "❌ No", 0xFF0000)


class CancelOnlyView(ui.View):
    def __init__(self, user_embed: discord.Message, log_embed: discord.Message, user_embed_obj: Embed, log_embed_obj: Embed, timeout=86400):
        super().__init__(timeout=timeout)
        self.user_embed = user_embed
        self.log_embed = log_embed
        self.user_embed_obj = user_embed_obj
        self.log_embed_obj = log_embed_obj

    async def update_embed(self, interaction: discord.Interaction, status_text: str, color: int, track: bool = False):
        ts = int(datetime.now(timezone.utc).timestamp())
        timestamp = f"<t:{ts}:R> • <t:{ts}:T>"
        footer_text = f"{status_text} • {timestamp} by {interaction.user.display_name}"

        self.user_embed_obj.set_footer(text=footer_text)
        self.user_embed_obj.color = discord.Color(color)

        self.log_embed_obj.set_footer(text=footer_text)
        self.log_embed_obj.color = discord.Color(color)
        self.log_embed_obj.remove_author()

        try:
            # A deferred interaction can't use response.edit_message; edit the message directly instead.
            if interaction.response.is_done():
                await interaction.message.edit(embed=self.log_embed_obj, view=None)
            else:
                await interaction.response.edit_message(embed=self.log_embed_obj, view=None)
        except (discord.errors.NotFound, discord.errors.InteractionResponded):
            try:
                await interaction.message.edit(embed=self.log_embed_obj, view=None)
            except Exception:
                pass
        await self.user_embed.edit(embed=self.user_embed_obj, view=None)
        await self.log_embed.edit(embed=self.log_embed_obj, view=None)

        if track and interaction.guild:
            try:
                guild_data = load_guild_data(interaction.guild.id)
                if guild_data is not None:
                    completed = guild_data.get("completed_askos", {})
                    user_id = str(interaction.user.id)
                    completed[user_id] = completed.get(user_id, 0) + 1
                    guild_data["completed_askos"] = completed
                    from cogs.data_utils import save_guild_data
                    save_guild_data(interaction.guild.id, guild_data)
            except Exception:
                pass

        self.stop()

    async def _check_os_permission(self, interaction: discord.Interaction):
        guild_data = load_guild_data(interaction.guild.id)
        if not guild_data:
            await interaction.response.send_message("Only overseers can use this button.", ephemeral=True)
            return False
        os_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("overseer_role_name"))
        if os_role and os_role in interaction.user.roles:
            return True
        await interaction.response.send_message("Only overseers can use this button.", ephemeral=True)
        return False

    async def _check_user_permission(self, interaction: discord.Interaction):
        guild_data = load_guild_data(interaction.guild.id)
        if not guild_data:
            await interaction.response.send_message("You don't have permission to use this button.", ephemeral=True)
            return False
        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(interaction.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(interaction.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(interaction.guild.roles, name=guild_data["dead_role_name"])
        if (
            interaction.user.guild_permissions.administrator
            or (alive_role and alive_role in interaction.user.roles)
            or (sponsor_role and sponsor_role in interaction.user.roles)
            or (alt_role and alt_role in interaction.user.roles)
            or (dead_role and dead_role in interaction.user.roles)
        ):
            return True
        await interaction.response.send_message("You don't have permission to use this button.", ephemeral=True)
        return False

    @ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_os_permission(interaction):
            return
        await self.update_embed(interaction, "✅ Confirmed", 0x00FF00, track=True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_user_permission(interaction):
            return
        await self.update_embed(interaction, "❌ Cancelled", 0xff0000)

    @ui.button(label="Yes", style=discord.ButtonStyle.success, emoji="✅")
    async def yes_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_os_permission(interaction):
            return
        await self.update_embed(interaction, "✅ Yes", 0x00FF00, track=True)

    @ui.button(label="No", style=discord.ButtonStyle.danger, emoji="❌")
    async def no_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_os_permission(interaction):
            return
        await self.update_embed(interaction, "❌ No", 0xFF0000)

class VisitActionView(ActionButtons):
    def __init__(self, *args, target_house=None, house_number=None, action_type=None, requester=None, approver_only=False, is_stealth=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_house = target_house
        self.house_number = house_number
        self.action_type = action_type
        self.requester = requester
        self.approver_only = approver_only
        self.is_stealth = is_stealth
        self.executed = False
        self._busy = False  # set while a visit is being carried out, so a second click cannot run it again

    async def _execute_visit(self, interaction: discord.Interaction):
        guild = interaction.guild
        guild_data = load_guild_data(guild.id)
        if not guild_data:
            await interaction.followup.send("Guild data not loaded.", ephemeral=True)
            return False

        moving_cog = interaction.client.get_cog("Moving")
        if not moving_cog:
            await interaction.followup.send("Moving cog not loaded.", ephemeral=True)
            return False

        class Ctx:
            def __init__(self, bot, author, guild, channel, message):
                self.bot = bot
                self.author = author
                self.guild = guild
                self.channel = channel
                self.message = message
                self.prefix = "."

            async def send(self, content=None, **kwargs):
                try:
                    return await interaction.followup.send(content=content, **kwargs)
                except Exception:
                    return await interaction.channel.send(content=content, **kwargs)

            async def reply(self, content=None, **kwargs):
                return await self.send(content=content, **kwargs)

        # The visit is carried out for the player who asked for it, not for whoever clicked.
        actor = self.requester or interaction.user
        ctx_mock = Ctx(interaction.client, actor, guild, self.user_embed.channel, interaction.message)

        try:
            if self.action_type == "move":
                await moving_cog.process_move(ctx_mock, self.target_house, is_stealth=self.is_stealth, read_only=False)
                return True
            elif self.action_type == "home":
                await moving_cog.process_move(ctx_mock, self.target_house, is_stealth=self.is_stealth, read_only=False)
                return True
            elif self.action_type == "knock":
                await moving_cog.process_knock(ctx_mock, self.target_house, guild_data)
                return True
            elif self.action_type == "renmove":
                await moving_cog.process_move(ctx_mock, self.target_house, is_stealth=False, read_only=False)
                return True
            elif self.action_type == "renknock":
                await moving_cog.process_knock(ctx_mock, self.target_house, guild_data)
                return True
            elif self.action_type == "pcadd":
                await moving_cog.pcadd(ctx_mock, self.target_house)
                return True
            else:
                return False
        except Exception as e:
            await interaction.followup.send(f"Error executing visit: {e}", ephemeral=True)
            return False

    async def _check_approver(self, interaction: discord.Interaction) -> bool:
        """Requests made with a command are decided by Overseers or admins only."""
        if not self.approver_only:
            return True
        guild_data = load_guild_data(interaction.guild.id) or {}
        os_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
        if interaction.user.guild_permissions.administrator or (os_role and os_role in interaction.user.roles):
            return True
        await interaction.response.send_message("Only Overseers can approve or deny this request.", ephemeral=True)
        return False

    @ui.button(label="Confirm Visit", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_visit(self, interaction: discord.Interaction, button: ui.Button):
        if self.executed or self._busy:
            return await interaction.response.send_message("This visit has already been carried out or is in progress.", ephemeral=True)
        if not await self._check_approver(interaction):
            return
        if not self.approver_only and not await self._check_permission(interaction):
            return
        guild_data = load_guild_data(interaction.guild.id)
        if guild_data:
            vb_text, vb_hit = check_channel_warning(guild_data, self.user_embed.channel.id, check_visitblock_warning)
            if vb_hit:
                await interaction.response.send_message(f"⚠️ Visit blocked: {vb_text}", ephemeral=True)
                return

        self._busy = True
        await interaction.response.defer()
        # Grey out the buttons straight away so the click can't be repeated.
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        try:
            success = await self._execute_visit(interaction)
        except Exception:
            self._busy = False
            await self._restore_buttons(interaction)
            raise
        self._busy = False
        if success:
            self.executed = True
            await self.update_embed(interaction, "✅ Visit Completed", 0x00FF00, track=True)
        else:
            await self._restore_buttons(interaction)
            await interaction.followup.send("Failed to execute visit.", ephemeral=True)

    async def _restore_buttons(self, interaction: discord.Interaction):
        """A visit that failed can be tried again, so the buttons come back."""
        for child in self.children:
            child.disabled = False
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

    @ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_visit(self, interaction: discord.Interaction, button: ui.Button):
        if self.executed or self._busy:
            return await interaction.response.send_message("This visit has already been carried out or is in progress.", ephemeral=True)
        if not await self._check_approver(interaction):
            return
        if not self.approver_only and not await self._check_permission(interaction):
            return
        await self.update_embed(interaction, "❌ Denied", 0xFF0000)


class ActionsLogging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _detect_visit_action(self, message: discord.Message, guild_data: dict):
        content = message.content.lower()
        bot_member = message.guild.me
        if bot_member not in message.mentions and not any(r in message.role_mentions for r in bot_member.roles if bot_member.roles):
            return None

        move_match = re.search(r'\.move\s+(\d+)', content)
        knock_match = re.search(r'\.knock\s+(\d+)', content)
        renmove_match = re.search(r'\.renmove\s+([^\s]+)', content)
        renknock_match = re.search(r'\.renknock\s+([^\s]+)', content)
        pcadd_match = re.search(r'\.pcadd\s+([^\s]+)', content)
        if not move_match and not knock_match and not renmove_match and not renknock_match and not pcadd_match:
            return None

        houses_category = discord.utils.get(message.guild.categories, name=guild_data.get("houses_category_name"))
        if not houses_category:
            return None

        target_house = None
        action_type = "move"
        house_num = None

        if move_match or knock_match:
            num = move_match.group(1) if move_match else knock_match.group(1)
            house_num = num
            target_house = _find_house(houses_category, str(num)) or _find_house(houses_category, f"house-{num}") or discord.utils.get(houses_category.channels, name=str(num))
            if not target_house:
                for ch in houses_category.channels:
                    if str(num) in ch.name:
                        target_house = ch
                        break
            action_type = "move" if move_match else "knock"
        else:
            if renmove_match:
                name = renmove_match.group(1)
                action_type = "renmove"
            elif renknock_match:
                name = renknock_match.group(1)
                action_type = "renknock"
            else:
                name = pcadd_match.group(1)
                action_type = "pcadd"
            name_clean = name.replace("<#", "").replace(">", "").strip()
            if name_clean.isdigit():
                target_house = message.guild.get_channel(int(name_clean))
            else:
                target_house = discord.utils.get(houses_category.channels, name=name_clean)
                if not target_house:
                    target_house = discord.utils.get(houses_category.channels, name=name)
                if not target_house:
                    for ch in houses_category.channels:
                        ch_low = ch.name.lower()
                        nc_low = name_clean.lower()
                        nc_low2 = name.lower().replace("<#", "").replace(">", "").strip()
                        if nc_low in ch_low or ch_low in nc_low or nc_low2 in ch_low or ch_low in nc_low2:
                            target_house = ch
                            break
                if not target_house:
                    for ch in houses_category.channels:
                        if any(token in ch.name for token in name_clean.split('-') if len(token) > 2):
                            target_house = ch
                            break

        if not target_house:
            return None

        return {"house": target_house, "num": house_num, "type": action_type}

    async def create_visit_request(self, ctx, action_type: str, house, query: str, is_stealth: bool = False) -> bool:
        """Post a `.move` / `.knock` / `.home` request from a player. Overseers answer with Confirm or Deny."""
        guild = ctx.guild
        guild_data = load_guild_data(guild.id) or {}
        log_channel = discord.utils.get(guild.text_channels, name=guild_data.get("actions_log_channel_name"))
        if not log_channel:
            await ctx.send("The actions log channel is not set up, so this request could not be sent.")
            return False
        os_role = discord.utils.get(guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
        verb = {"move": "Move", "renmove": "Move", "home": "Home"}.get(action_type, "Knock")
        if is_stealth:
            verb += " (stealth)"
        command = " ".join(part for part in (f".{action_type}", query, "stealth" if is_stealth else "") if part)

        embed_log = Embed(color=0xff3fb9)
        embed_log.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed_log.description = (
            f"**Visit Request:** `{command}`\n"
            f"**Target:** {house.mention} ({house.name})\n"
            f"**Action:** {verb}\n"
            f"**Channel:** {ctx.channel.mention}\n"
            f"**Time:** <t:{int(ctx.message.created_at.timestamp())}:R>\n"
            f"[Jump to Message]({ctx.message.jump_url})"
        )
        embed_log.set_footer(text="⏳ Pending: Overseers, Confirm or Deny")

        embed_user = Embed(color=0xff3fb9)
        embed_user.description = (
            f"**Visit Request:** `{command}`\n"
            f"**Target:** {house.mention} ({house.name})\n"
            f"**Action:** {verb}\n"
            f"**Status:** waiting for an Overseer"
        )
        embed_user.set_footer(text="⏳ Pending")

        log_message = await log_channel.send(content=os_role.mention if os_role else None, embed=embed_log)
        user_message = await ctx.channel.send(embed=embed_user)
        log_view = VisitActionView(
            user_embed=user_message,
            log_embed=log_message,
            user_embed_obj=embed_user.copy(),
            log_embed_obj=embed_log.copy(),
            target_house=house,
            house_number=query if query.isdigit() else None,
            action_type=action_type,
            requester=ctx.author,
            approver_only=True,
            is_stealth=is_stealth,
        )
        user_view = CancelOnlyView(
            user_embed=user_message,
            log_embed=log_message,
            user_embed_obj=embed_user,
            log_embed_obj=embed_log,
        )
        await log_message.edit(view=log_view)
        await user_message.edit(view=user_view)
        return True

    @commands.command(name="actionstats", aliases=["actionlog", "donestats"])
    async def actionstats(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.", ephemeral=True)
            return
        completed = guild_data.get("completed_actions", {}) or {}
        askos = guild_data.get("completed_askos", {}) or {}

        merged = {}
        for uid, c in completed.items():
            merged[uid] = merged.get(uid, 0) + int(c)
        for uid, c in askos.items():
            merged[uid] = merged.get(uid, 0) + int(c)

        if not merged:
            await ctx.send("No completed actions tracked yet.", ephemeral=True)
            return

        sorted_items = sorted(merged.items(), key=lambda x: x[1], reverse=True)
        embed = Embed(title="✅ Completed Actions", color=0x00FF00)
        lines = []
        for idx, (uid, total) in enumerate(sorted_items[:15], start=1):
            member = ctx.guild.get_member(int(uid))
            name = member.display_name if member else f"Unknown ({uid})"
            a = int(completed.get(uid, 0))
            o = int(askos.get(uid, 0))
            lines.append(f"`#{idx}` {name} — **{total}** (Actions: {a} | AskOS: {o})")
        embed.description = "\n".join(lines)
        embed.set_footer(text="Sorted by total completions")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        guild = message.guild
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

        if message.channel.category not in allowed_categories:
            return
        if not any(role in message.author.roles for role in allowed_roles):
            return

        bot_member = guild.me
        bot_roles = bot_member.roles

        if message.reference:
            if not message.reference.message_id:
                return
            try:
                replied_msg = await message.channel.fetch_message(message.reference.message_id)
                if replied_msg.author.bot:
                    return
            except (discord.NotFound, discord.Forbidden):
                return

        if bot_member not in message.mentions and not any(role in message.role_mentions for role in bot_roles):
            return

        log_channel = discord.utils.get(guild.text_channels, name=guild_data["actions_log_channel_name"])
        if not log_channel:
            return

        jump_url = message.jump_url
        pinned_messages = await message.channel.pins()
        pinned_url = pinned_messages[-1].jump_url if pinned_messages else None

        content = (message.content[:500] + "...") if len(message.content) > 500 else message.content or "*No text*"
        jump_link = f"[Jump to Message]({jump_url})"
        pinned_link = f" | [Jump to Role]({pinned_url})" if pinned_url else ""

        visit_info = await self._detect_visit_action(message, guild_data)

        embed_log = Embed(color=0xff3fb9)
        embed_log.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        if visit_info:
            embed_log.description = (
                f"**Visit Request:**\n{message.content}\n\n"
                f"**Target:** {visit_info['house'].mention} ({visit_info['house'].name})\n"
                f"**Action:** {visit_info['type'].title()}\n"
                f"**Channel:** {message.channel.mention}\n"
                f"**Time:** <t:{int(message.created_at.timestamp())}:R>\n"
                f"{jump_link}{pinned_link}\n\n"
                f"⚠️ Visitblocked check will run on confirm."
            )
        else:
            embed_log.description = (
                f"**Message:**\n{content}\n\n"
                f"**Channel:** {message.channel.mention}\n"
                f"**Time:** <t:{int(message.created_at.timestamp())}:R>\n"
                f"{jump_link}{pinned_link}"
            )
        embed_log.set_footer(text="⏳ Pending")

        embed_user = Embed(color=0xff3fb9)
        if visit_info:
            embed_user.description = (
                f"**Visit Request:**\n{message.content}\n\n"
                f"**Target:** {visit_info['house'].mention} ({visit_info['house'].name})\n"
                f"**Action:** {visit_info['type'].title()}\n"
                f"**Log Channel:** {log_channel.mention}\n"
                f"**Time:** <t:{int(message.created_at.timestamp())}:R>\n"
                f"{jump_link}{pinned_link}"
            )
        else:
            embed_user.description = (
                f"**Message:**\n{content}\n\n"
                f"**Log Channel:** {log_channel.mention}\n"
                f"**Time:** <t:{int(message.created_at.timestamp())}:R>\n"
                f"{jump_link}{pinned_link}"
            )
        embed_user.set_footer(text="⏳ Pending")

        tag_message = await log_channel.send(f"{os_role.mention}")
        await tag_message.delete()

        log_message = await log_channel.send(embed=embed_log)

        user_message = await message.channel.send(embed=embed_user)

        if visit_info:
            log_view = VisitActionView(
                user_embed=user_message,
                log_embed=log_message,
                user_embed_obj=embed_user.copy(),
                log_embed_obj=embed_log.copy(),
                requester=message.author,
                target_house=visit_info['house'],
                house_number=visit_info['num'],
                action_type=visit_info['type'],
            )
            user_view = CancelOnlyView(
                user_embed=user_message,
                log_embed=log_message,
                user_embed_obj=embed_user,
                log_embed_obj=embed_log,
            )
        else:
            log_view = ActionButtons(
                user_embed=user_message,
                log_embed=log_message,
                user_embed_obj=embed_user.copy(),
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