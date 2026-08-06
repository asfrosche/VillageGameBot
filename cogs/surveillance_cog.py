"""Single cog: Follow (move with them), Track (watch where they are), Stalk (read access)."""

import discord
from discord.ext import commands
from datetime import datetime, timezone
from cogs.data_utils import load_guild_data, save_guild_data


class Surveillance(commands.Cog):
    """Manage Follow, Track, and Stalk relationships."""

    def __init__(self, bot):
        self.bot = bot
        # Track state (in-memory): guild_id -> {"target_id": int, "channel_id": int, "message_id": int}
        self.active_tracks: dict[int, dict] = {}

    # ══════════════════════════════════════════════════════════════════════════
    # Shared movement hook — called from moving_cog.py after every movement
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _require_rolechat(ctx, guild_data) -> bool:
        """Return True if the current channel is in the RC category."""
        rc_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name", "ROLES"))
        return rc_category is not None and ctx.channel.category == rc_category

    async def after_movement_update(self, guild, guild_data, target_member=None):
        """Update follow movement, tracking message, and stalk permissions."""
        guild_id = guild.id
        if target_member:
            await self._move_followers(guild, guild_data, target_member)
        if guild_id in self.active_tracks:
            await self._update_track_message(guild, guild_data, self.active_tracks[guild_id])
        await self._update_stalk_permissions(guild, guild_data)

    async def _move_followers(self, guild, guild_data, target_member, is_stealth=False, category=None):
        """After a target member moves, pull all their followers to the same house."""
        follows = guild_data.get("player_follows", {})
        if not follows:
            return
        if category is None:
            category = discord.utils.get(guild.categories,
                                         name=guild_data.get("houses_category_name", "HOUSES"))
        if not category:
            return
        alive_role = discord.utils.get(guild.roles, name=guild_data.get("alive_role_name", "Alive"))
        sponsor_role = discord.utils.get(guild.roles, name=guild_data.get("sponsor_role_name", "Sponsor"))
        dead_role = discord.utils.get(guild.roles, name=guild_data.get("dead_role_name", "Dead"))
        alt_role = discord.utils.get(guild.roles, name=guild_data.get("alt_role_name", "Alt"))
        log_channel = discord.utils.get(guild.text_channels, name=guild_data.get("log_channel_name", "log-visits"))
        target_id = str(target_member.id)

        for fid, fdata in list(follows.items()):
            if fdata["target"] != target_id:
                continue
            follower = guild.get_member(int(fid))
            if follower is None:
                continue
            if not (alive_role in follower.roles or sponsor_role in follower.roles
                    or dead_role in follower.roles or alt_role in follower.roles):
                continue

            # Multi-house check
            house_count = 0
            for ch in category.channels:
                if isinstance(ch, discord.TextChannel) and ch.permissions_for(follower).send_messages:
                    house_count += 1
            if house_count > 1:
                if log_channel:
                    await log_channel.send(
                        f"⚠️ {follower.mention} is in multiple houses — "
                        f"follow will not work. Target: {target_member.mention}"
                    )
                continue

            # Find the new house (where target just moved to)
            new_house = None
            for ch in category.channels:
                if isinstance(ch, discord.TextChannel) and ch.permissions_for(target_member).send_messages:
                    new_house = ch
                    break
            if not new_house:
                continue

            # Already in the target house?
            if new_house.permissions_for(follower).send_messages:
                continue

            pair_stealth = fdata.get("stealth", False)
            effective_stealth = is_stealth or pair_stealth

            # Remove from old house
            for ch in category.channels:
                if isinstance(ch, discord.TextChannel) and ch.permissions_for(follower).send_messages:
                    await ch.set_permissions(follower, overwrite=None)
                    if not effective_stealth:
                        await ch.send(f'{follower.mention} follows {target_member.mention} — Leaves')

            # Add to new house
            await new_house.set_permissions(follower, read_messages=True, send_messages=True)
            if not effective_stealth:
                await new_house.send(f'{follower.mention} follows {target_member.mention} — Joins {new_house.mention}')

            # Log (unless stealth)
            if log_channel and not effective_stealth:
                embed = discord.Embed(
                    title='Follower moved',
                    description=f'{follower.mention} follows {target_member.mention}',
                    color=0xff3fb9,
                    timestamp=datetime.now(),
                )
                embed.add_field(name='Added To:', value=f'{new_house.mention} `[{new_house.name}]`', inline=False)
                embed.set_footer(text="Village Game")
                await log_channel.send(embed=embed)

        save_guild_data(guild.id, guild_data)

    async def _remove_followers_from_house(self, guild, guild_data, removed_members, house_channel, is_stealth=False):
        """When members are removed from a house, also remove their followers from that house."""
        follows = guild_data.get("player_follows", {})
        if not follows:
            return
        for member in removed_members:
            mid = str(member.id)
            for fid, fdata in list(follows.items()):
                if fdata["target"] == mid:
                    follower = guild.get_member(int(fid))
                    if follower and house_channel.permissions_for(follower).send_messages:
                        await house_channel.set_permissions(follower, overwrite=None)
                        if not is_stealth:
                            await house_channel.send(f'{follower.mention} follows {member.mention} — Leaves')

    # ═════════════════════════════════════════════════════════════════════════════
    # FOLLOW — Move with them
    # ═════════════════════════════════════════════════════════════════════════════

    async def _save_follows(self, guild_id, guild_data):
        save_guild_data(guild_id, guild_data)

    async def _remove_follows_for(self, guild_id, guild_data, member_id):
        follows = guild_data.get("player_follows", {})
        removed = [k for k, v in follows.items() if v["target"] == str(member_id)]
        for k in removed:
            del follows[k]
        if removed:
            guild_data["player_follows"] = follows
            save_guild_data(guild_id, guild_data)
        return removed

    @staticmethod
    def _check_follow_cycle(follows, follower_id, target_id):
        """Return True if setting follower->target would create a cycle."""
        visited = set()
        current = target_id
        while current:
            if current == follower_id:
                return True
            if current in visited:
                return True
            visited.add(current)
            entry = follows.get(current)
            current = entry["target"] if entry else None
        return False

    @commands.command()
    async def follow(self, ctx, target: discord.Member, *args):
        """Make the player in this RC follow @target. Add 'stealth' for silent follow."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        follows = guild_data.setdefault("player_follows", {})
        stealth = 'stealth' in args

        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])

        followers_to_set = []
        for member in ctx.channel.members:
            if alive_role in member.roles or sponsor_role in member.roles:
                followers_to_set.append(member)

        if not followers_to_set:
            await ctx.send("No eligible players found in this channel to follow.")
            return

        for follower in followers_to_set:
            fid = str(follower.id)
            tid = str(target.id)

            if fid == tid:
                await ctx.send(f"{follower.mention} cannot follow themselves.")
                continue

            if fid in follows and follows[fid]["target"] == tid:
                await ctx.send(f"{follower.mention} is already following {target.mention}.")
                continue

            if self._check_follow_cycle(follows, fid, tid):
                await ctx.send(
                    f"⚠️ Cannot set follow — this would create a circular chain. "
                    f"({follower.mention} → {target.mention})"
                )
                continue

            if fid in follows and follows[fid]["target"] != tid:
                old_target = ctx.guild.get_member(int(follows[fid]["target"]))
                old_name = old_target.mention if old_target else f"ID {follows[fid]['target']}"
                await ctx.send(
                    f"⚠️ {follower.mention} was following {old_name}. "
                    f"Switching to follow {target.mention}."
                )

            follows[fid] = {"target": tid, "stealth": stealth}

        guild_data["player_follows"] = follows
        await self._save_follows(ctx.guild.id, guild_data)
        await ctx.send('Done')

    @commands.command()
    async def unfollow(self, ctx, target: discord.Member):
        """Stop the player in this RC from following @target."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        follows = guild_data.get("player_follows", {})
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])

        removed_any = False
        for member in ctx.channel.members:
            if alive_role in member.roles or sponsor_role in member.roles:
                fid = str(member.id)
                if fid in follows and follows[fid]["target"] == str(target.id):
                    del follows[fid]
                    removed_any = True
                    await ctx.send(f"{member.mention} unfollowed {target.mention}.")

        if not removed_any:
            await ctx.send("No one in this channel is following that player.")

        guild_data["player_follows"] = follows
        await self._save_follows(ctx.guild.id, guild_data)

    @commands.command()
    async def followlist(self, ctx):
        """Show all active follow pairs in this server."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        follows = guild_data.get("player_follows", {})
        if not follows:
            await ctx.send("No active follow pairs.")
            return

        lines = []
        for fid, fdata in follows.items():
            follower = ctx.guild.get_member(int(fid))
            target = ctx.guild.get_member(int(fdata["target"]))
            f_name = follower.mention if follower else f"ID {fid}"
            t_name = target.mention if target else f"ID {fdata['target']}"
            stealth_tag = " (stealth)" if fdata.get("stealth") else ""
            lines.append(f"• {f_name} → {t_name}{stealth_tag}")

        embed = discord.Embed(
            title="Follow Pairs",
            description="\n".join(lines),
            color=0xff3fb9,
        )
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)

    @commands.command()
    async def unfollowall(self, ctx):
        """Clear all follow pairs in this server."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        count = len(guild_data.get("player_follows", {}))
        guild_data["player_follows"] = {}
        await self._save_follows(ctx.guild.id, guild_data)
        await ctx.send(f"Cleared {count} follow pair(s).")

    # ═════════════════════════════════════════════════════════════════════════════
    # TRACK — Watch where they are
    # ═════════════════════════════════════════════════════════════════════════════

    def _find_player_house(self, guild, guild_data, member_id):
        member = guild.get_member(member_id)
        if not member:
            return None
        houses_category = discord.utils.get(guild.categories, name=guild_data.get("houses_category_name"))
        if not houses_category:
            return None
        for ch in houses_category.channels:
            if not isinstance(ch, discord.TextChannel):
                continue
            if ch.permissions_for(member).send_messages:
                return ch
        return None

    def _get_dead_role(self, guild, guild_data):
        return discord.utils.get(guild.roles, name=guild_data.get("dead_role_name", "Dead"))

    def _get_alive_role(self, guild, guild_data):
        return discord.utils.get(guild.roles, name=guild_data.get("alive_role_name", "Alive"))

    async def _make_track_embed(self, guild, guild_data, track_entry):
        target_id = track_entry["target_id"]
        member = guild.get_member(target_id)
        if not member:
            embed = discord.Embed(
                title="Player Tracker",
                description="Tracked player not found in this server.",
                color=0xe74c3c,
                timestamp=datetime.now(),
            )
            embed.set_footer(text="Village Game")
            return embed

        house = self._find_player_house(guild, guild_data, target_id)
        dead_role = self._get_dead_role(guild, guild_data)
        alive_role = self._get_alive_role(guild, guild_data)

        if dead_role and dead_role in member.roles:
            status = "💀 Dead"
        elif alive_role and alive_role in member.roles:
            status = "🟢 Alive"
        else:
            status = "⚪ Unknown"

        location = house.mention if house else "🏚️ None"

        embed = discord.Embed(
            title="Player Tracker",
            description=f"Tracking {member.mention}",
            color=0x3498db,
            timestamp=datetime.now(),
        )
        embed.add_field(name="Location", value=location, inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.set_footer(text="Village Game")
        return embed

    async def _update_track_message(self, guild, guild_data, track_entry):
        channel = guild.get_channel(track_entry["channel_id"])
        if not channel:
            return
        try:
            msg = await channel.fetch_message(track_entry["message_id"])
        except discord.NotFound:
            self.active_tracks.pop(guild.id, None)
            return
        except discord.Forbidden:
            return

        embed = await self._make_track_embed(guild, guild_data, track_entry)
        try:
            await msg.edit(embed=embed)
        except discord.HTTPException:
            pass

    @commands.command()
    async def track(self, ctx, target: discord.Member):
        """Track a player's location with a live-updating message."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return

        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        existing = self.active_tracks.get(ctx.guild.id)
        if existing:
            old_channel = ctx.guild.get_channel(existing["channel_id"])
            if old_channel:
                try:
                    old_msg = await old_channel.fetch_message(existing["message_id"])
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        embed = await self._make_track_embed(ctx.guild, guild_data, {
            "target_id": target.id,
        })
        msg = await ctx.send(embed=embed)

        self.active_tracks[ctx.guild.id] = {
            "target_id": target.id,
            "channel_id": ctx.channel.id,
            "message_id": msg.id,
        }

        await ctx.send(f"Now tracking {target.mention}. Use `.untrack` to stop.")

    @commands.command()
    async def untrack(self, ctx):
        """Stop tracking the current player."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return

        guild_data = load_guild_data(ctx.guild.id)
        if guild_data and not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        existing = self.active_tracks.pop(ctx.guild.id, None)
        if not existing:
            await ctx.send("No active tracking in this server.")
            return

        channel = ctx.guild.get_channel(existing["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(existing["message_id"])
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await ctx.send("Tracking stopped.")

    # ═════════════════════════════════════════════════════════════════════════════
    # STALK — Gain read access to wherever they go
    # ═════════════════════════════════════════════════════════════════════════════

    async def _update_stalk_permissions(self, guild, guild_data):
        stalks = guild_data.get("player_stalks", {})
        if not stalks:
            return

        houses_category = discord.utils.get(
            guild.categories, name=guild_data.get("houses_category_name", "HOUSES")
        )
        if not houses_category:
            return

        target_to_house = {}
        for stalker_id_str, target_ids in stalks.items():
            for target_id_str in target_ids:
                target_id = int(target_id_str)
                if target_id in target_to_house:
                    continue
                target = guild.get_member(target_id)
                if not target:
                    continue
                for ch in houses_category.channels:
                    if not isinstance(ch, discord.TextChannel):
                        continue
                    if ch.permissions_for(target).send_messages:
                        target_to_house[target_id] = ch
                        break

        houses_list = list(houses_category.channels)
        for stalker_id_str, target_ids in stalks.items():
            stalker = guild.get_member(int(stalker_id_str))
            if not stalker:
                continue

            needed_house_ids = set()
            for target_id_str in target_ids:
                house = target_to_house.get(int(target_id_str))
                if house:
                    needed_house_ids.add(house.id)

            granted = []
            for ch in houses_list:
                if not isinstance(ch, discord.TextChannel):
                    continue
                ow = ch.overwrites_for(stalker)
                if ow.read_messages is True and ow.send_messages is not True:
                    granted.append(ch)

            for ch in granted:
                if ch.id not in needed_house_ids:
                    try:
                        await ch.set_permissions(stalker, overwrite=None)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            granted_ids = {ch.id for ch in granted}
            for ch in houses_list:
                if not isinstance(ch, discord.TextChannel):
                    continue
                if ch.id in needed_house_ids and ch.id not in granted_ids:
                    try:
                        await ch.set_permissions(stalker, read_messages=True)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

    async def _cleanup_all_stalks(self, guild, guild_data):
        stalks = guild_data.get("player_stalks", {})
        if not stalks:
            return
        houses_category = discord.utils.get(
            guild.categories, name=guild_data.get("houses_category_name", "HOUSES")
        )
        if not houses_category:
            return
        for stalker_id_str in list(stalks):
            stalker = guild.get_member(int(stalker_id_str))
            if not stalker:
                continue
            for ch in houses_category.channels:
                if not isinstance(ch, discord.TextChannel):
                    continue
                ow = ch.overwrites_for(stalker)
                if ow.read_messages is True and ow.send_messages is not True:
                    try:
                        await ch.set_permissions(stalker, overwrite=None)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

    def _get_stalks(self, guild_id):
        guild_data = load_guild_data(guild_id)
        if not guild_data:
            return None, None
        return guild_data, guild_data.setdefault("player_stalks", {})

    @commands.command()
    async def stalk(self, ctx, target: discord.Member):
        """Stalk a player to silently watch their house."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return

        guild_data, stalks = self._get_stalks(ctx.guild.id)
        if guild_data is None:
            await ctx.send("Guild data not loaded.")
            return
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        stalker_id = str(ctx.author.id)
        target_id = str(target.id)

        if stalker_id == target_id:
            await ctx.send("You cannot stalk yourself.")
            return

        targets = stalks.setdefault(stalker_id, [])
        if target_id in targets:
            await ctx.send(f"You are already stalking {target.mention}.")
            return

        targets.append(target_id)
        guild_data["player_stalks"] = stalks
        save_guild_data(ctx.guild.id, guild_data)

        await self._update_stalk_permissions(ctx.guild, guild_data)
        await ctx.send(f"Now stalking {target.mention}.")

    @commands.command()
    async def unstalk(self, ctx, target: discord.Member):
        """Stop stalking a specific player."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return

        guild_data, stalks = self._get_stalks(ctx.guild.id)
        if guild_data is None:
            await ctx.send("Guild data not loaded.")
            return
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        stalker_id = str(ctx.author.id)
        target_id = str(target.id)

        targets = stalks.get(stalker_id, [])
        if target_id not in targets:
            await ctx.send(f"You are not stalking {target.mention}.")
            return

        targets.remove(target_id)
        if not targets:
            del stalks[stalker_id]
        guild_data["player_stalks"] = stalks
        save_guild_data(ctx.guild.id, guild_data)

        await self._update_stalk_permissions(ctx.guild, guild_data)
        await ctx.send(f"Stopped stalking {target.mention}.")

    @commands.command()
    async def unstalkall(self, ctx):
        """Stop stalking all players."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return

        guild_data, stalks = self._get_stalks(ctx.guild.id)
        if guild_data is None:
            await ctx.send("Guild data not loaded.")
            return
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        stalker_id = str(ctx.author.id)
        if stalker_id not in stalks:
            await ctx.send("You are not stalking anyone.")
            return

        del stalks[stalker_id]
        guild_data["player_stalks"] = stalks
        save_guild_data(ctx.guild.id, guild_data)

        await self._update_stalk_permissions(ctx.guild, guild_data)
        await ctx.send("Stopped stalking all players.")

    @commands.command()
    async def stalklist(self, ctx):
        """Show all active stalk relationships in this server."""
        guild_data, stalks = self._get_stalks(ctx.guild.id)
        if guild_data is None:
            await ctx.send("Guild data not loaded.")
            return
        if not self._require_rolechat(ctx, guild_data):
            await ctx.send("This command can only be used in a RoleChat channel.")
            return

        if not stalks:
            await ctx.send("No active stalk relationships.")
            return

        lines = []
        for stalker_id_str, target_ids in stalks.items():
            stalker = ctx.guild.get_member(int(stalker_id_str))
            s_name = stalker.mention if stalker else f"ID {stalker_id_str}"
            target_mentions = []
            for tid in target_ids:
                t = ctx.guild.get_member(int(tid))
                target_mentions.append(t.mention if t else f"ID {tid}")
            lines.append(f"• {s_name} → {', '.join(target_mentions)}")

        embed = discord.Embed(
            title="Stalk Relationships",
            description="\n".join(lines),
            color=0x9b59b6,
        )
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)

    # ── Death detection ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Detect when a player receives the Dead role and remove their stalk relationships."""
        guild_data = load_guild_data(after.guild.id)
        if not guild_data:
            return

        dead_role = discord.utils.get(after.guild.roles, name=guild_data.get("dead_role_name", "Dead"))
        if not dead_role:
            return
        if dead_role in before.roles or dead_role not in after.roles:
            return

        stalks = guild_data.get("player_stalks", {})
        if not stalks:
            return

        changed = False
        target_id_str = str(after.id)
        for stalker_id_str in list(stalks):
            targets = stalks[stalker_id_str]
            if target_id_str in targets:
                targets.remove(target_id_str)
                changed = True
                if not targets:
                    del stalks[stalker_id_str]

        if changed:
            guild_data["player_stalks"] = stalks
            save_guild_data(after.guild.id, guild_data)
            await self._update_stalk_permissions(after.guild, guild_data)


async def after_movement_update(ctx, target_member=None):
    """Call this after every movement operation to keep Follow/Track/Stalk in sync."""
    guild_data = load_guild_data(ctx.guild.id)
    if not guild_data:
        return
    cog = ctx.bot.get_cog("Surveillance")
    if cog:
        await cog.after_movement_update(ctx.guild, guild_data, target_member=target_member)


async def setup(bot):
    await bot.add_cog(Surveillance(bot))
