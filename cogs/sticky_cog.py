import asyncio
import re
import time

import discord
from discord.ext import commands

from cogs.data_utils import load_guild_data, save_guild_data
from utils.embeds import error_embed, info_embed, success_embed

DEFAULT_STICKY_COOLDOWN = 60
MIN_STICKY_COOLDOWN = 10
MAX_STICKY_CONTENT = 2048

DISBOARD_BOT_ID = 302050872383242240
DEFAULT_BUMP_HOURS = 4
MIN_BUMP_HOURS = 1
MAX_BUMP_HOURS = 24


class StickyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cooldown_lock = {}
        self._bump_timers = {}  # (guild_id, channel_id) -> task that sends that bump's reminder

    async def cog_unload(self):
        for task in self._bump_timers.values():
            task.cancel()
        self._bump_timers.clear()

    @commands.Cog.listener()
    async def on_ready(self):
        # Re-arm reminders for bumps still waiting after a restart (runs once per pending bump).
        for guild in self.bot.guilds:
            guild_data = load_guild_data(guild.id)
            config = guild_data.get("bump_reminder") if guild_data else None
            if not config:
                continue
            for channel_key, entry in config.get("bumps", {}).items():
                if entry and not entry.get("reminded") and entry.get("last_bump_time"):
                    self._schedule_bump(guild.id, int(channel_key), entry["last_bump_time"])

    def _get_bump_config(self, guild_data):
        config = guild_data.get("bump_reminder")
        if config is None:
            config = {
                "channel_ids": [],
                "hours": DEFAULT_BUMP_HOURS,
                "bumps": {},
            }
            guild_data["bump_reminder"] = config
        if "channel_id" in config:
            old = config.pop("channel_id")
            if old:
                config.setdefault("channel_ids", []).append(old)
        config.setdefault("channel_ids", [])
        config.setdefault("hours", DEFAULT_BUMP_HOURS)
        config.setdefault("bumps", {})
        return config

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
        if not sticky:
            return
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

    @sticky.command(name="bumpchannel", aliases=["bump"])
    async def sticky_bump_channel(self, ctx, *, channel_text: str = None):
        """Add a channel to watch for Disboard /bump and send reminders. Usage: .sticky bumpchannel [#ch]"""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        config = self._get_bump_config(guild_data)
        channel = ctx.channel
        if channel_text:
            match = re.match(r"<#(\d+)>", channel_text)
            if match:
                target = ctx.guild.get_channel(int(match.group(1)))
                if target is not None:
                    channel = target
        channel_ids = config["channel_ids"]
        if channel.id not in channel_ids:
            channel_ids.append(channel.id)
            save_guild_data(ctx.guild.id, guild_data)
            embed = success_embed(
                title="Bump reminder channel added",
                description=(
                    f"Now watching {channel.mention} for Disboard `/bump`.\n"
                    f"Reminder after {config['hours']}h."
                ),
            )
        else:
            embed = error_embed(
                description=f"{channel.mention} is already being watched for bumps."
            )
        await ctx.send(embed=embed)

    @sticky.command(name="bumpremove")
    async def sticky_bump_remove(self, ctx, *, channel_text: str = None):
        """Remove a channel from bump reminders. Usage: .sticky bumpremove [#ch]"""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        config = self._get_bump_config(guild_data)
        channel = ctx.channel
        if channel_text:
            match = re.match(r"<#(\d+)>", channel_text)
            if match:
                target = ctx.guild.get_channel(int(match.group(1)))
                if target is not None:
                    channel = target
        channel_ids = config["channel_ids"]
        if channel.id in channel_ids:
            channel_ids.remove(channel.id)
            config["bumps"].pop(str(channel.id), None)
            save_guild_data(ctx.guild.id, guild_data)
            embed = success_embed(
                title="Bump reminder channel removed",
                description=f"Stopped watching {channel.mention} for bumps.",
            )
        else:
            embed = error_embed(
                description=f"{channel.mention} was not being watched for bumps."
            )
        await ctx.send(embed=embed)

    @sticky.command(name="bumplist", aliases=["bumpchannels"])
    async def sticky_bump_list(self, ctx):
        """List all channels watching for Disboard /bump. Usage: .sticky bumplist"""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        config = self._get_bump_config(guild_data)
        channel_ids = config["channel_ids"]
        if not channel_ids:
            await ctx.send(embed=info_embed(description="No bump reminder channels set."))
            return
        bumps = config["bumps"]
        lines = []
        for channel_id in channel_ids:
            channel = ctx.guild.get_channel(channel_id)
            name = channel.mention if channel else f"#{channel_id}"
            entry = bumps.get(str(channel_id))
            last = entry.get("last_bump_time") if entry else None
            if last:
                lines.append(f"{name} — last bump <t:{int(last)}:R>")
            else:
                lines.append(f"{name} — no bump recorded yet")
        embed = info_embed(
            title="Bump reminder channels",
            description=(
                "\n".join(lines)
                + f"\n\nReminder delay: {config['hours']}h"
            ),
        )
        await ctx.send(embed=embed)

    @sticky.command(name="bumphours")
    async def sticky_bump_hours(self, ctx, hours: int):
        """Set bump reminder delay in hours. Usage: .sticky bumphours <hours>"""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        if not MIN_BUMP_HOURS <= hours <= MAX_BUMP_HOURS:
            await ctx.send(
                embed=error_embed(description=f"Hours must be between {MIN_BUMP_HOURS} and {MAX_BUMP_HOURS}."),
            )
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        config = self._get_bump_config(guild_data)
        config["hours"] = hours
        save_guild_data(ctx.guild.id, guild_data)
        self._reschedule_guild_bumps(ctx.guild.id, config)
        embed = success_embed(
            title="Bump reminder delay updated",
            description=f"Reminder will be sent {hours}h after each bump.",
        )
        await ctx.send(embed=embed)

    @sticky.command(name="bumpoff")
    async def sticky_bump_off(self, ctx):
        """Disable bump reminders. Usage: .sticky bumpoff"""
        if not self._is_admin(ctx):
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        config = self._get_bump_config(guild_data)
        config["channel_ids"] = []
        config["bumps"] = {}
        save_guild_data(ctx.guild.id, guild_data)
        embed = success_embed(
            title="Bump reminders disabled",
            description="No more bump reminders will be sent.",
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
        if not message.guild:
            return
        if message.author.id == DISBOARD_BOT_ID:
            self._record_bump(message)
            return
        if message.author.bot:
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

    def _record_bump(self, message):
        guild_data = load_guild_data(message.guild.id)
        if not guild_data:
            return
        config = self._get_bump_config(guild_data)
        if message.channel.id not in config["channel_ids"]:
            return
        description = (message.embeds[0].description or "") if message.embeds else ""
        content = message.content or ""
        if "Bump done" not in description and "Bump done" not in content:
            return
        now = time.time()
        config["bumps"][str(message.channel.id)] = {
            "last_bump_time": now,
            "reminded": False,
        }
        save_guild_data(message.guild.id, guild_data)
        self._schedule_bump(message.guild.id, message.channel.id, now)

    # ------------------------------------------------------------------
    # Bump reminders: one timer per bump, sleeping until its reminder is due.
    # No periodic polling. A timer re-checks its bump when it wakes, so
    # removed/off/already-reminded bumps stop quietly, and a changed delay
    # just makes it sleep the rest of the way.
    # ------------------------------------------------------------------

    def _schedule_bump(self, guild_id, channel_id, last_bump):
        key = (guild_id, channel_id)
        old = self._bump_timers.pop(key, None)
        if old is not None and not old.done():
            old.cancel()
        self._bump_timers[key] = asyncio.create_task(self._bump_timer(guild_id, channel_id, last_bump))

    def _reschedule_guild_bumps(self, guild_id, config):
        for channel_key, entry in config.get("bumps", {}).items():
            if entry and not entry.get("reminded") and entry.get("last_bump_time"):
                self._schedule_bump(guild_id, int(channel_key), entry["last_bump_time"])

    async def _bump_timer(self, guild_id, channel_id, last_bump):
        key = (guild_id, channel_id)
        try:
            while True:
                guild_data = load_guild_data(guild_id)
                config = guild_data.get("bump_reminder") if guild_data else None
                entry = config.get("bumps", {}).get(str(channel_id)) if config else None
                if (
                    not entry
                    or entry.get("reminded")
                    or entry.get("last_bump_time") != last_bump
                    or channel_id not in config.get("channel_ids", [])
                ):
                    return
                hours = config.get("hours", DEFAULT_BUMP_HOURS)
                remaining = last_bump + hours * 3600 - time.time()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    continue
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    return
                try:
                    await channel.send(
                        f"🔔 Time to bump! Run `/bump` to keep the server on DISBOARD "
                        f"(last bump: <t:{int(last_bump)}:R>)."
                    )
                except discord.HTTPException:
                    return
                entry["reminded"] = True
                save_guild_data(guild_id, guild_data)
                return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[sticky-bump] reminder failed for channel {channel_id}: {e}")
        finally:
            if self._bump_timers.get(key) is asyncio.current_task():
                del self._bump_timers[key]


async def setup(bot):
    await bot.add_cog(StickyCog(bot))