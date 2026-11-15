import discord
from discord.ext import commands
from datetime import datetime, timezone
from discord import Embed
from cogs.data_utils import load_guild_data
from cogs.actions_logging_cog import ActionButtons, AskosActionButtons, CancelOnlyView


class OSQuestions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_or_create_log_channel(self, guild: discord.Guild, guild_data: dict):
        channel_name = guild_data.get("os_questions_log_channel_name") or "os-questions"
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
                reason=".askos - auto created os-questions channel",
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
            await ctx.send("Could not find or create the `os-questions` channel. Contact an admin.", ephemeral=True)
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


async def setup(bot):
    await bot.add_cog(OSQuestions(bot))
