import discord
from discord.ext import commands
from datetime import datetime, timezone
from discord import Embed, ui
from cogs.data_utils import load_guild_data
from utils.bot_db import insert_action_log


class ActionButtons(ui.View):
    def __init__(
        self,
        user_embed: discord.Message,
        log_embed: discord.Message,
        user_embed_obj: Embed,
        log_embed_obj: Embed,
        meta: dict,
        timeout=86400,
    ):
        super().__init__(timeout=timeout)
        self.user_embed = user_embed
        self.log_embed = log_embed
        self.user_embed_obj = user_embed_obj
        self.log_embed_obj = log_embed_obj
        self.meta = meta

    async def update_embed(self, interaction: discord.Interaction, status_text: str, color: int, store_done: bool):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        footer_text = f"{status_text} at {timestamp} by {interaction.user.display_name}"

        self.user_embed_obj.set_footer(text=footer_text)
        self.user_embed_obj.color = discord.Color(color)

        self.log_embed_obj.set_footer(text=footer_text)
        self.log_embed_obj.color = discord.Color(color)
        self.log_embed_obj.remove_author()

        await interaction.response.edit_message(embed=self.log_embed_obj, view=None)
        await self.user_embed.edit(embed=self.user_embed_obj, view=None)
        await self.log_embed.edit(embed=self.log_embed_obj, view=None)

        # Persist only confirmed "Done" actions
        if store_done:
            try:
                insert_action_log(
                    guild_id=self.meta["guild_id"],
                    channel_id=self.meta["channel_id"],
                    player_id=self.meta.get("player_id"),
                    message=self.meta.get("message", "")[:1000],
                    created_at=self.meta.get("created_at", datetime.now(timezone.utc)),
                    marked_at=datetime.now(timezone.utc),
                    marked_by_id=interaction.user.id,
                )
            except Exception:
                # Logging failure should not break UX
                pass

        self.stop()

    @ui.button(label="Done", style=discord.ButtonStyle.success, emoji="✅")
    async def done_button(self, interaction: discord.Interaction, button: ui.Button):
        guild_data = load_guild_data(interaction.guild.id)
        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(interaction.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(interaction.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(interaction.guild.roles, name=guild_data["dead_role_name"])
        if not (
            interaction.user.guild_permissions.administrator
            or alive_role in interaction.user.roles
            or sponsor_role in interaction.user.roles
            or alt_role in interaction.user.roles
            or dead_role in interaction.user.roles
        ):
            await interaction.response.send_message("You don't have permission to use this button.", ephemeral=True)
            return
        await self.update_embed(interaction, "✅ Done", 0x00FF00, True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        guild_data = load_guild_data(interaction.guild.id)
        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(interaction.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(interaction.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(interaction.guild.roles, name=guild_data["dead_role_name"])
        if not (
            interaction.user.guild_permissions.administrator
            or alive_role in interaction.user.roles
            or sponsor_role in interaction.user.roles
            or alt_role in interaction.user.roles
            or dead_role in interaction.user.roles
        ):
            await interaction.response.send_message("You don't have permission to use this button.", ephemeral=True)
            return
        await self.update_embed(interaction, "❌ Cancelled", 0xFF0000, False)


class CancelOnlyView(ui.View):
    def __init__(self, user_embed: discord.Message, log_embed: discord.Message, user_embed_obj: Embed, log_embed_obj: Embed, timeout=86400):
        super().__init__(timeout=timeout)
        self.user_embed = user_embed
        self.log_embed = log_embed
        self.user_embed_obj = user_embed_obj
        self.log_embed_obj = log_embed_obj

    async def update_embed(self, interaction: discord.Interaction, status_text: str, color: int):
        timestamp = datetime.now(timezone.utc).strftime("%d-%m %H:%M:%S")
        footer_text = f"{status_text} at {timestamp} by {interaction.user.display_name}"

        self.user_embed_obj.set_footer(text=footer_text)
        self.user_embed_obj.color = discord.Color(color)

        self.log_embed_obj.set_footer(text=footer_text)
        self.log_embed_obj.color = discord.Color(color)
        self.log_embed_obj.remove_author()

        await interaction.response.edit_message(embed=self.user_embed_obj, view=None)
        await self.user_embed.edit(embed=self.user_embed_obj, view=None)
        await self.log_embed.edit(embed=self.log_embed_obj, view=None)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        guild_data = load_guild_data(interaction.guild.id)
        alive_role = discord.utils.get(interaction.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(interaction.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(interaction.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(interaction.guild.roles, name=guild_data["dead_role_name"])
        if not (
            interaction.user.guild_permissions.administrator
            or alive_role in interaction.user.roles
            or sponsor_role in interaction.user.roles
            or alt_role in interaction.user.roles
            or dead_role in interaction.user.roles
        ):
            await interaction.response.send_message("You don't have permission to use this button.", ephemeral=True)
            return
        await self.update_embed(interaction, "❌ Cancelled", 0xff0000)

class ActionsLogging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

        timestamp = message.created_at.strftime("%d-%m %H:%M:%S")
        jump_url = message.jump_url
        pinned_messages = await message.channel.pins()
        pinned_url = pinned_messages[-1].jump_url if pinned_messages else None

        content = (message.content[:500] + "...") if len(message.content) > 500 else message.content or "*No text*"
        jump_link = f"[Jump to Message]({jump_url})"
        pinned_link = f" | [Jump to Role]({pinned_url})" if pinned_url else ""

        embed_log = Embed(color=0xff3fb9)
        embed_log.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed_log.description = (
            f"**Message:**\n{content}\n\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Time:** {timestamp}\n"
            f"{jump_link}{pinned_link}"
        )
        embed_log.set_footer(text="⏳ Pending...")

        embed_user = Embed(color=0xff3fb9)
        embed_user.description = (
            f"**Message:**\n{content}\n\n"
            f"**Log Channel:** {log_channel.mention}\n"
            f"**Time:** {timestamp}\n"
            f"{jump_link}{pinned_link}"
        )
        embed_user.set_footer(text="⏳ Pending...")

        tag_message = await log_channel.send(f"{os_role.mention}")
        await tag_message.delete()

        log_message = await log_channel.send(embed=embed_log)
        user_message = await message.channel.send(embed=embed_user)

        meta = {
            "guild_id": guild.id,
            "channel_id": message.channel.id,
            "player_id": message.author.id,
            "message": content,
            "created_at": message.created_at.replace(tzinfo=timezone.utc),
        }

        log_view = ActionButtons(
            user_embed=user_message,
            log_embed=log_message,
            user_embed_obj=embed_user.copy(),
            log_embed_obj=embed_log.copy(),
            meta=meta,
        )
        user_view = CancelOnlyView(
            user_embed=user_message,
            log_embed=log_message,
            user_embed_obj=embed_user,
            log_embed_obj=embed_log
        )

        await log_message.edit(view=log_view)
        await user_message.edit(view=user_view)