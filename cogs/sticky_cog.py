import re
import time

import discord
from discord.ext import commands

from cogs.data_utils import load_guild_data, save_guild_data
from utils.embeds import error_embed, info_embed, success_embed

DEFAULT_STICKY_COOLDOWN = 60
MIN_STICKY_COOLDOWN = 10
MAX_STICKY_CONTENT = 2048


class StickyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cooldown_lock = {}

    @staticmethod
    def _is_admin(ctx):
        return ctx.author.guild_permissions.administrator

    def _get_stickies(self, guild_data):
        stickies = guild_data.get("stickies")
        if stickies is None:
            guild_data["stickies"] = {}
        return guild_data["stickies"]

    @classmethod
    def _parse_channel_and_text(cls, ctx, text):
        match = re.match(r"<#(\d+)>\s+([\s\S]+)", text)
        if match:
            channel = ctx.guild.get_channel(int(match.group(1)))
            if isinstance(channel, discord.TextChannel):
                return channel, match.group(2)
            return None, None
        return ctx.channel, text

    async def _send_sticky(self, channel, sticky):
        message = await channel.send(
            sticky["content"],
            silent=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        sticky["message_id"] = message.id
        sticky["last_refresh"] = time.time()
        return message

    async def _delete_old_sticky(self, channel, sticky):
        old_id = sticky.get("message_id")
        if not old_id:
            return
        try:
            old = await channel.fetch_message(old_id)
            await old.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    @commands.group(name="sticky")
    async def sticky(self, ctx):
        if ctx.invoked_subcommand is None:
            await self._status_channel(ctx, None)

    @sticky.command(name="set")
    async def sticky_set(self, ctx, *, text):
        """Set a sticky message. Usage: .sticky set [#channel] <text>"""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        channel, content = self._parse_channel_and_text(ctx, text)
        if channel is None:
            await ctx.send(embed=error_embed(description="Invalid channel."))
            return
        content = content.strip()
        if not content:
            await ctx.send(embed=error_embed(description="You must provide some text for the sticky message."))
            return
        if len(content) > MAX_STICKY_CONTENT:
            await ctx.send(
                embed=error_embed(
                    description=f"Sticky message is too long. Maximum is {MAX_STICKY_CONTENT} characters.",
                )
            )
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        stickies = self._get_stickies(guild_data)
        old_sticky = stickies.get(str(channel.id))
        sticky = {
            "channel_id": channel.id,
            "content": content,
            "message_id": None,
            "last_refresh": None,
            "cooldown": DEFAULT_STICKY_COOLDOWN,
        }
        if old_sticky:
            sticky["cooldown"] = old_sticky.get("cooldown", DEFAULT_STICKY_COOLDOWN)
        await self._delete_old_sticky(channel, old_sticky)
        try:
            await self._send_sticky(channel, sticky)
        except discord.HTTPException:
            await ctx.send(embed=error_embed(description="Failed to send the sticky message."))
            return
        stickies[str(channel.id)] = sticky
        save_guild_data(ctx.guild.id, guild_data)
        embed = success_embed(
            title="Sticky set",
            description=f"Sticky message set in {channel.mention}.\nRefresh cooldown: {sticky['cooldown']}s",
        )
        await ctx.send(embed=embed)

    @sticky.command(name="remove", aliases=["rm", "delete", "del"])
    async def sticky_remove(self, ctx, *, channel_text: str = None):
        """Remove the sticky message from a channel. Usage: .sticky remove [#channel]"""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        stickies = self._get_stickies(guild_data)
        channel = ctx.channel
        if channel_text:
            match = re.match(r"<#(\d+)>", channel_text)
            if match:
                target = ctx.guild.get_channel(int(match.group(1)))
                if target is not None:
                    channel = target
        sticky = stickies.pop(str(channel.id), None)
        if sticky is None:
            await ctx.send(embed=error_embed(description=f"No sticky message set in {channel.mention}."))
            return
        await self._delete_old_sticky(channel, sticky)
        save_guild_data(ctx.guild.id, guild_data)
        embed = success_embed(
            title="Sticky removed",
            description=f"Sticky message removed from {channel.mention}.",
        )
        await ctx.send(embed=embed)

    @sticky.command(name="cooldown")
    async def sticky_cooldown(self, ctx, *args):
        """Set the refresh cooldown. Usage: .sticky cooldown [#channel] <seconds>"""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        stickies = self._get_stickies(guild_data)
        channel = ctx.channel
        parts = list(args)
        match = re.match(r"<#(\d+)>", parts[0]) if parts else None
        if match:
            target = ctx.guild.get_channel(int(match.group(1)))
            if target is not None:
                channel = target
            parts = parts[1:]
        if not parts:
            await ctx.send(
                embed=error_embed(description="Usage: `.sticky cooldown [#channel] <seconds>`"),
            )
            return
        try:
            cooldown = int(parts[0])
        except ValueError:
            await ctx.send(embed=error_embed(description="Cooldown must be a number in seconds."))
            return
        if cooldown < MIN_STICKY_COOLDOWN:
            await ctx.send(
                embed=error_embed(description=f"Cooldown must be at least {MIN_STICKY_COOLDOWN} seconds."),
            )
            return
        sticky = stickies.get(str(channel.id))
        if sticky is None:
            await ctx.send(embed=error_embed(description=f"No sticky message set in {channel.mention}."))
            return
        sticky["cooldown"] = cooldown
        save_guild_data(ctx.guild.id, guild_data)
        embed = success_embed(
            title="Sticky cooldown updated",
            description=f"Cooldown for {channel.mention}: {cooldown}s",
        )
        await ctx.send(embed=embed)

    @sticky.command(name="list")
    async def sticky_list(self, ctx):
        """List all sticky messages in this server."""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        stickies = self._get_stickies(guild_data)
        if not stickies:
            await ctx.send(embed=info_embed(description="No sticky messages set in this server."))
            return
        lines = []
        for channel_id, sticky in stickies.items():
            channel = ctx.guild.get_channel(int(channel_id))
            name = channel.mention if channel else f"#{channel_id}"
            content = sticky.get("content", "")
            preview = content if len(content) <= 80 else content[:77] + "..."
            lines.append(f"{name}: {preview}")
        embed = info_embed(
            title="Sticky messages",
            description="\n".join(lines),
        )
        await ctx.send(embed=embed)

    async def _status_channel(self, ctx, channel_text):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        stickies = self._get_stickies(guild_data)
        channel = ctx.channel
        if channel_text:
            match = re.match(r"<#(\d+)>", channel_text)
            if match:
                target = ctx.guild.get_channel(int(match.group(1)))
                if target is not None:
                    channel = target
        sticky = stickies.get(str(channel.id))
        if sticky is None:
            await ctx.send(embed=info_embed(description=f"No sticky message set in {channel.mention}."))
            return
        content = sticky.get("content", "")
        embed = info_embed(
            title=f"Sticky in {channel.name}",
            description=f"{content}\n\nCooldown: {sticky.get('cooldown', DEFAULT_STICKY_COOLDOWN)}s",
        )
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if message.content.startswith(self.bot.command_prefix):
            return
        guild_data = load_guild_data(message.guild.id)
        if not guild_data:
            return
        stickies = self._get_stickies(guild_data)
        sticky = stickies.get(str(message.channel.id))
        if sticky is None:
            return
        cooldown = sticky.get("cooldown", DEFAULT_STICKY_COOLDOWN)
        last = sticky.get("last_refresh") or 0
        if time.time() - last < cooldown:
            return
        lock_key = (message.guild.id, message.channel.id)
        now = time.time()
        last_lock = self._cooldown_lock.get(lock_key) or 0
        if now - last_lock < cooldown:
            return
        self._cooldown_lock[lock_key] = now
        await self._delete_old_sticky(message.channel, sticky)
        try:
            await self._send_sticky(message.channel, sticky)
        except discord.HTTPException:
            return
        save_guild_data(message.guild.id, guild_data)


async def setup(bot):
    await bot.add_cog(StickyCog(bot))