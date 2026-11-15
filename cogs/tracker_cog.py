import discord
from discord.ext import commands
from datetime import datetime, timezone
from discord import Embed

from cogs.data_utils import load_guild_data, save_guild_data


ROLE_INFO = [
    {"name": "Alive", "emoji": "🟢"},
    {"name": "Sponsor", "emoji": "💰"},
    {"name": "Dead", "emoji": "💀"},
    {"name": "Overseer", "emoji": "👑"},
    {"name": "Spectator", "emoji": "👁️"},
]


def _total_messages(counts) -> int:
    """Sum every stored message count, ignoring malformed values."""
    total = 0
    for value in (counts or {}).values():
        try:
            total += int(value)
        except (TypeError, ValueError):
            continue
    return total


def _split_message(text, size=1900):
    """Split long output so it never exceeds Discord's 2000-character limit."""
    chunks = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:size])
            line = line[size:]
        if len(current) + len(line) > size:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks or [""]


class LapConfirmView(discord.ui.View):
    """Ask before snapshotting the current server stats and resetting them."""

    def __init__(self, cog, author_id, label):
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.label = label

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran the command can confirm this lap.",
                ephemeral=True,
            )
            return False
        return True

    def _disable(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Save lap & reset", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        self._disable()
        await interaction.message.edit(view=self)
        data = load_guild_data(interaction.guild.id) or {}
        await self.cog._save_lap(interaction, data, self.label)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self._disable()
        await interaction.response.edit_message(
            content=f"❌ Lap **{self.label}** was not saved. The counter is unchanged.",
            view=None,
        )
        self.stop()


class MessageTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_tracked_channel(self, guild: discord.Guild):
        """Resolve the channel to track for this guild (day discussion channel by name from guild data)."""
        data = load_guild_data(guild.id)
        if not data or not data.get("message_tracking_enabled"):
            return None
        name = data.get("daydiscussion_channel_name")
        if not name:
            return None
        return discord.utils.get(guild.text_channels, name=name)

    def _is_rc_channel(self, channel: discord.TextChannel, guild_data: dict) -> bool:
        """Check if a channel is in an RC category."""
        if not channel.category:
            return False
        rc_categories = [
            guild_data.get("rc_category_name"),
            guild_data.get("alt_category_name"),
            guild_data.get("dead_rc_category_name"),
        ]
        return channel.category.name in rc_categories

    @commands.command()
    async def statss(self, ctx):
        """Show message counts for the day discussion channel (when tracking is enabled) grouped by role priority."""
        data = load_guild_data(ctx.guild.id) or {}
        counts = data.get("tracked_message_counts") or {}
        if not counts:
            await ctx.send("No stats available for this server. Enable tracking with `.setmessagetracking true` (day discussion channel must be set in setup).")
            return

        # 1. Define the role priority order with corresponding emojis
        # Check roles in this exact order: first matching role determines the user's section.
        role_info = [
            {"name": "Alive", "emoji": "🟢"},
            {"name": "Sponsor", "emoji": "💰"},
            {"name": "Dead", "emoji": "💀"},
            {"name": "Overseer", "emoji": "👑"},
            {"name": "Spectator", "emoji": "👁️"}
        ]
        role_priority = [info["name"] for info in role_info]
        
        # 2. Grouping behavior: Initialize dictionary to map each category to lists of members and their counts
        grouped_stats = {role: [] for role in role_priority}
        
        # 3. Process each tracked user
        for user_id_str, count in counts.items():
            try:
                user_id = int(user_id_str)
            except ValueError:
                continue
            
            # Fetch Discord Member object (try cache first, fallback to API)
            member = ctx.guild.get_member(user_id)
            if not member:
                try:
                    member = await ctx.guild.fetch_member(user_id)
                except (discord.NotFound, discord.HTTPException):
                    # Ignore users that no longer exist or cannot be fetched
                    continue

            # Inspect roles and assign to the first matching category using priority order
            assigned_role = None
            member_role_names = {role.name for role in member.roles}
            for role_name in role_priority:
                if role_name in member_role_names:
                    assigned_role = role_name
                    break  # Stop checking after first match to ensure each user appears ONLY ONCE
            
            # If the user has none of the tracked roles, ignore them
            if assigned_role:
                grouped_stats[assigned_role].append((member.display_name, int(count)))

        # 4. Sorting inside each category and formatting output sections
        list_str = []
        for info in role_info:
            role_name = info["name"]
            emoji = info["emoji"]
            users_list = grouped_stats[role_name]
            if not users_list:
                continue
            
            # Sort users inside each category by: highest message count first
            users_list.sort(key=lambda x: x[1], reverse=True)
            
            # Calculate section totals (subtle clean stats)
            total_members = len(users_list)
            total_msgs = sum(count for _, count in users_list)
            
            member_suffix = "member" if total_members == 1 else "members"
            msg_suffix = "msg" if total_msgs == 1 else "msgs"
            
            # Add category section header using Discord native small header markdown (###) for size and weight distinction
            list_str.append(f"### {emoji} {role_name} ({total_members} {member_suffix} • {total_msgs} {msg_suffix})")
            
            # Add each user under that section formatted cleanly: Name — Count
            for name, count in users_list:
                list_str.append(f"{name} — {count}")
                
            # Add empty line as readable spacing between sections
            list_str.append("")

        # Remove the trailing empty line if it exists
        if list_str and list_str[-1] == "":
            list_str.pop()

        if not list_str:
            await ctx.send("No tracked users currently have any of the required roles.")
            return

        embed = discord.Embed(title="📊 Message Stats", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        
        description_text = "\n".join(list_str)
        if len(description_text) > 2000:
            chunks = _split_message(description_text)
            await ctx.send("Message Stats:\n" + chunks[0])
            for chunk in chunks[1:]:
                await ctx.send(chunk)
        else:
            embed.description = description_text
            await ctx.send(embed=embed)

    async def _grouped_stats_lines(self, guild, counts):
        """Group message counts by role priority and format them for an embed."""
        role_priority = [info["name"] for info in ROLE_INFO]
        grouped_stats = {role: [] for role in role_priority}

        for user_id_str, count in counts.items():
            try:
                user_id = int(user_id_str)
            except ValueError:
                continue
            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except (discord.NotFound, discord.HTTPException):
                    continue
            assigned_role = None
            member_role_names = {role.name for role in member.roles}
            for role_name in role_priority:
                if role_name in member_role_names:
                    assigned_role = role_name
                    break
            if assigned_role:
                grouped_stats[assigned_role].append((member.display_name, int(count)))

        list_str = []
        for info in ROLE_INFO:
            role_name = info["name"]
            emoji = info["emoji"]
            users_list = grouped_stats[role_name]
            if not users_list:
                continue
            users_list.sort(key=lambda x: x[1], reverse=True)
            total_members = len(users_list)
            total_msgs = sum(count for _, count in users_list)
            member_suffix = "member" if total_members == 1 else "members"
            msg_suffix = "msg" if total_msgs == 1 else "msgs"
            list_str.append(f"### {emoji} {role_name} ({total_members} {member_suffix} • {total_msgs} {msg_suffix})")
            for name, count in users_list:
                list_str.append(f"{name} — {count}")
            list_str.append("")

        if list_str and list_str[-1] == "":
            list_str.pop()
        return list_str

    async def _send_stats(self, ctx, counts, title, footer):
        """Render one set of message counts, grouped by role, as an embed."""
        list_str = await self._grouped_stats_lines(ctx.guild, counts)
        total = _total_messages(counts)
        if list_str:
            list_str.append("")
            list_str.append(f"**Total messages:** {total}")
        description_text = "\n".join(list_str)
        if not description_text:
            await ctx.send(f"{title}\nNo tracked members with a known role. Total messages: **{total}**.")
            return
        if len(description_text) > 2000:
            chunks = _split_message(description_text)
            await ctx.send(f"{title}\n{chunks[0]}")
            for chunk in chunks[1:]:
                await ctx.send(chunk)
            return
        embed = discord.Embed(title=title, color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text=footer)
        embed.description = description_text
        await ctx.send(embed=embed)

    @commands.command()
    async def serverstats(self, ctx, *, view: str = None):
        """Show server-wide message counts (all channels except RCs) grouped by role priority. Admin only.

        `.serverstats` shows the current (not yet saved) lap.
        `.serverstats lap [label]` saves the current counts as a lap and resets them.
        `.serverstats laps` lists every saved lap plus the all-time total.
        `.serverstats total` shows every saved lap plus the current one combined.
        """
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Only server admins can use this command.")
            return
        data = load_guild_data(ctx.guild.id) or {}
        laps = data.get("server_message_laps") or []
        current = data.get("server_message_counts") or {}
        raw_view = (view or "").strip()
        key = raw_view.lower() or "current"

        if key == "lap" or key.startswith("lap "):
            label = raw_view[3:].strip()
            if not label:
                await ctx.send(
                    "❌ Please give the lap a label, e.g. `.serverstats lap day1`."
                )
                return
            if not current:
                await ctx.send("Nothing to lap yet — no server-wide messages have been recorded.")
                return
            view = LapConfirmView(self, ctx.author.id, label)
            await ctx.send(
                f"⚠️ You will save the current msgs in a lap (**{label}**) and reset the count. Are you sure?",
                view=view,
            )
            return

        if key in ("laps", "list"):
            await self._send_laps_list(ctx, data)
            return

        if key in ("current", "now", "session", "this"):
            if not current:
                await ctx.send("No server-wide stats available. Enable tracking with `.setservers tracking true`.")
                return
            await self._send_stats(
                ctx, current,
                "📊 Server-Wide Message Stats",
                f"Village Game — current lap • {_total_messages(current)} msgs",
            )
            return

        if key in ("total", "all", "cumulative", "overall"):
            totals = {}
            for record in laps:
                for user_id, count in (record.get("counts") or {}).items():
                    try:
                        totals[user_id] = totals.get(user_id, 0) + int(count)
                    except (TypeError, ValueError):
                        continue
            for user_id, count in current.items():
                try:
                    totals[user_id] = totals.get(user_id, 0) + int(count)
                except (TypeError, ValueError):
                    continue
            if not totals:
                await ctx.send("No server-wide stats available. Enable tracking with `.setservers tracking true`.")
                return
            lap_count = len(laps)
            lap_word = "lap" if lap_count == 1 else "laps"
            await self._send_stats(
                ctx, totals,
                "📊 Server-Wide Message Stats — Total",
                f"Village Game — {lap_count} {lap_word} + current • {_total_messages(totals)} msgs",
            )
            return

        await ctx.send(
            f"Unknown option `{raw_view}`. Use `.serverstats`, "
            "`.serverstats lap [label]`, `.serverstats laps`, or `.serverstats total`."
        )

    async def _send(self, target, **kwargs):
        """Reply to either a command context or a button interaction."""
        if isinstance(target, discord.Interaction):
            await target.response.send_message(**kwargs)
        else:
            await target.send(**kwargs)

    async def _save_lap(self, ctx, data, label=None):
        """Save the current server-wide counts as a lap and reset the counter."""
        counts = data.get("server_message_counts") or {}
        if not counts:
            await self._send(ctx, content="Nothing to lap yet — no server-wide messages have been recorded.")
            return
        now = datetime.now(timezone.utc)
        laps = data.get("server_message_laps") or []
        number = int(data.get("server_message_lap_counter") or 0) + 1
        record = {
            "lap": number,
            "label": label.strip() if label and label.strip() else None,
            "saved_at": now.isoformat(),
            "saved_ts": int(now.timestamp()),
            "counts": dict(counts),
        }
        laps.append(record)
        data["server_message_laps"] = laps
        data["server_message_lap_counter"] = number
        data["server_message_counts"] = {}
        save_guild_data(ctx.guild.id, data)

        total = _total_messages(counts)
        embed = discord.Embed(
            title=f"📊 Lap {number} saved",
            description=(
                f"**{total}** message(s) from **{len(counts)}** member(s) were saved.\n"
                "The current counter has been reset to zero."
            ),
            color=0xff3fb9,
            timestamp=datetime.now(),
        )
        if record["label"]:
            embed.add_field(name="Label", value=record["label"], inline=True)
        embed.set_footer(text="Village Game")
        await self._send(ctx, embed=embed)

    async def _send_laps_list(self, ctx, data):
        """Send the list of every saved lap plus the current session."""
        laps = data.get("server_message_laps") or []
        current = data.get("server_message_counts") or {}
        if not laps and not current:
            await ctx.send("No server-wide stats available. Enable tracking with `.setservers tracking true`.")
            return

        lines = []
        grand_total = 0
        for record in laps:
            counts = record.get("counts") or {}
            total = _total_messages(counts)
            grand_total += total
            name = f"Lap {record.get('lap')}"
            if record.get("label"):
                name += f" — {record['label']}"
            saved_ts = record.get("saved_ts")
            when = f" • <t:{int(saved_ts)}:d>" if saved_ts else ""
            lines.append(f"**{name}** — {total} msgs • {len(counts)} members{when}")
        if current:
            total = _total_messages(current)
            grand_total += total
            lines.append(f"**Current (not lapped)** — {total} msgs • {len(current)} members")
        lines.append("")
        lines.append(f"**All messages (laps + current):** {grand_total}")

        description_text = "\n".join(lines)
        if len(description_text) > 2000:
            chunks = _split_message(description_text)
            await ctx.send("Server stats laps:\n" + chunks[0])
            for chunk in chunks[1:]:
                await ctx.send(chunk)
            return
        embed = discord.Embed(
            title="📊 Server Stats Laps",
            description=description_text,
            color=0xff3fb9,
            timestamp=datetime.now(),
        )
        embed.set_footer(text="Village Game — .serverstats lap <n|label> to view one")
        await ctx.send(embed=embed)

    @commands.command(name="setmessagetracking")
    @commands.has_permissions(administrator=True)
    async def setmessagetracking(self, ctx, value: bool):
        """Enable or disable message tracking for this server. Tracks the day discussion channel (see setup)."""
        data = load_guild_data(ctx.guild.id) or {}
        data["message_tracking_enabled"] = bool(value)
        save_guild_data(ctx.guild.id, data)
        await ctx.send(f"Message tracking **{'enabled' if value else 'disabled'}** for this server (day discussion channel).")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def start_tracking(self, ctx):
        """Start message tracking (same as setmessagetracking true)."""
        await self.setmessagetracking(ctx, True)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def stop_tracking(self, ctx):
        """Pause message tracking (same as setmessagetracking false)."""
        await self.setmessagetracking(ctx, False)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reset_tracking(self, ctx):
        """Reset message counts for this server."""
        data = load_guild_data(ctx.guild.id) or {}
        data["tracked_message_counts"] = {}
        save_guild_data(ctx.guild.id, data)
        await ctx.send("Message tracking stats have been reset for this server.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def resetservstats(self, ctx, everything: bool = False):
        """Reset the current server-wide message counts. Admin only.

        Saved laps are kept unless you pass `true`: `.resetservstats true`
        also deletes every saved lap and restarts lap numbering.
        """
        data = load_guild_data(ctx.guild.id) or {}
        data["server_message_counts"] = {}
        if everything:
            data["server_message_laps"] = []
            data["server_message_lap_counter"] = 0
        save_guild_data(ctx.guild.id, data)
        if everything:
            await ctx.send("Server-wide message stats and **all saved laps** have been reset.")
        else:
            await ctx.send("Current server-wide message stats have been reset. Saved laps were kept.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        data = load_guild_data(message.guild.id) or {}

        # Day discussion channel tracking
        channel = self._get_tracked_channel(message.guild)
        if channel and message.channel.id == channel.id:
            counts = data.get("tracked_message_counts") or {}
            uid_str = str(message.author.id)
            counts[uid_str] = counts.get(uid_str, 0) + 1
            data["tracked_message_counts"] = counts

        # Server-wide tracking (all channels except RCs) — always on
        if not self._is_rc_channel(message.channel, data):
            s_counts = data.get("server_message_counts") or {}
            uid_str = str(message.author.id)
            s_counts[uid_str] = s_counts.get(uid_str, 0) + 1
            data["server_message_counts"] = s_counts

        save_guild_data(message.guild.id, data)