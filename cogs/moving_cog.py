import re
import uuid
import types
from utils.discord_safe import add_text_fields
import discord
import asyncio
from datetime import datetime, timedelta, timezone
from discord.ext import commands
from discord.ui import View, Button
from utils.house_lookup import NO_MATCH, closest_house, house_match
from cogs.data_utils import load_guild_data, save_guild_data
from cogs.handling_cog import PUBLIC_CHANNEL_EMOJI
from cogs.surveillance_cog import after_movement_update
from utils.bot_db import get_role_dashboard
from utils.embeds import info_embed, warning_embed, error_embed
from cogs.status_cog import (
    check_move_warning,
    check_knock_warning,
    check_visitblock_warning,
    check_locked_house_warning,
    StatusWarningConfirmView,
    check_channel_warning,
)


def _strip_house_emoji(channel_name: str) -> str:
    """Strip the public channel emoji from a house name for lookups."""
    emoji = PUBLIC_CHANNEL_EMOJI.strip()
    if channel_name.endswith(emoji):
        name = channel_name[:-len(emoji)]
        return name.rstrip("-")
    return channel_name


def _find_house(category, channel_name: str):
    """Find a house channel, accounting for the public emoji."""
    ch = discord.utils.get(category.channels, name=channel_name)
    if not ch:
        emoji = PUBLIC_CHANNEL_EMOJI.strip()
        if emoji:
            ch = discord.utils.get(category.channels, name=f"{channel_name}-{emoji}")
    return ch


# ─────────────────────────────────────────────────────────────
# Portal View (.pportal interactive button)
# ─────────────────────────────────────────────────────────────


class PortalView(View):
    """Portal button placed inside a house: residents click to travel to the paired house.

    Ephemeral by design (timeout + auto-disable), matching the "buttons only"
    behaviour: the link lives on this message and is not stored in guild data.
    """

    def __init__(
        self,
        cog: "Moving",
        source: discord.TextChannel,
        dest: discord.TextChannel,
        max_uses: int | None = None,
    ):
        super().__init__(timeout=86400)
        self.cog = cog
        self.source = source
        self.dest = dest
        # Per-alive-player click limit for this portal button. ``None`` means
        # unlimited. Counters live in memory, keyed by alive-member id.
        self.max_uses = max_uses
        self.uses: dict[int, int] = {}
        self.message = None

    def _uses_left(self, member_id: int) -> int | None:
        """Remaining clicks for *member_id*, or ``None`` when unlimited."""
        if self.max_uses is None:
            return None
        return self.max_uses - self.uses.get(member_id, 0)

    @discord.ui.button(label="Portal", emoji="🌀", style=discord.ButtonStyle.primary)
    async def portal_btn(self, interaction: discord.Interaction, button: Button):
        guild_data = load_guild_data(self.source.guild.id)
        if not guild_data:
            return await interaction.response.send_message("Guild data not loaded.", ephemeral=True)

        can_use = interaction.user.guild_permissions.administrator
        if not can_use:
            os_role = discord.utils.get(interaction.guild.roles, name=guild_data.get("overseer_role_name", ""))
            can_use = bool(os_role and os_role in interaction.user.roles)
        if not can_use:
            perms = self.source.permissions_for(interaction.user)
            if not (perms.read_messages and perms.send_messages):
                return await interaction.response.send_message("You are not in this house.", ephemeral=True)

        # The usage limit applies to alive players only; admins/overseers and
        # members without the alive role (dead/alt/sponsor) are never counted.
        alive_role = discord.utils.get(
            interaction.guild.roles, name=guild_data.get("alive_role_name", "")
        )
        is_alive = bool(alive_role and alive_role in interaction.user.roles)
        if is_alive and self.max_uses is not None:
            left = self._uses_left(interaction.user.id)
            if left is not None and left <= 0:
                return await interaction.response.send_message(
                    f"🌀 You've already used this portal **{self.max_uses}** "
                    f"time{'s' if self.max_uses != 1 else ''}.",
                    ephemeral=True,
                )

        await interaction.response.defer(ephemeral=True)
        moved = await self.cog._portal_move(self.source, self.dest, guild_data)

        if is_alive and self.max_uses is not None and moved:
            self.uses[interaction.user.id] = self.uses.get(interaction.user.id, 0) + 1
        if not moved:
            return await interaction.followup.send(
                f"🌀 The house is empty — nobody to portal through to {self.dest.mention}.",
                ephemeral=True,
            )

        self.stop()
        if interaction.message:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except discord.HTTPException:
                pass

        names = ", ".join(f"**{n}**" for n in moved)
        remaining_note = ""
        if is_alive and self.max_uses is not None:
            left = self._uses_left(interaction.user.id)
            if left is not None:
                remaining_note = f"\nYou have **{left}** portal use{'s' if left != 1 else ''} left."
        await interaction.followup.send(
            f"🌀 Portaled **{len(moved)}** to {self.dest.mention}: {names}{remaining_note}",
            ephemeral=True,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.Forbidden):
                pass


class HouseSuggestView(discord.ui.View):
    """Yes/No for a suggested house. Only the person who asked can answer."""

    def __init__(self, invoker):
        super().__init__(timeout=60)
        self.invoker = invoker
        self.result = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message("This question isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        self.stop()
        await interaction.response.edit_message(content="Sending the request…", view=None)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)


class Moving(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_warning(self, ctx, embed, view):
        os_disc = discord.utils.get(ctx.guild.text_channels, name="overseer-discussion")
        if os_disc:
            msg = await os_disc.send(embed=embed, view=view)
            await ctx.send("⚠ Check **overseer-discussion** for status details.")
        else:
            msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        return msg

    async def _channel_has_active_knock(self, guild_data, channel):
        """Return True if *channel* still has an active (unanswered) knock message."""
        if not guild_data or not isinstance(channel, discord.TextChannel):
            return False
        try:
            async for message in channel.history(limit=50):
                if message.author != self.bot.user:
                    continue
                embed_titles = [embed.title for embed in message.embeds]
                is_knock_message = (
                    "knock knock" in (message.content or "")
                    and (message.pinned or "🚪 Someone is knocking..." in embed_titles)
                )
                if is_knock_message:
                    return True
        except (discord.Forbidden, discord.HTTPException):
            return False
        return False

    async def _warn_pending_knock(self, ctx):
        """Warn that the current house has an unanswered knock. Default = cancel."""
        embed = warning_embed(
            title="🚪 Pending Knock",
            description=(
                "There is a knock on **this house** that has **not been answered**.\n"
                "Proceeding may interrupt it — this is **not recommended**.\n\n"
                "Continue anyway?"
            ),
        )
        view = StatusWarningConfirmView(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()
        return view.confirmed

    # ──────────────────────────────────────────────────────────────────────────
    # Add commands
    # ──────────────────────────────────────────────────────────────────────────

    @commands.command()
    async def add(self, ctx, channel_str: str, *args):
        """Add a player to a house while keeping their current location."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = _find_house(category, channel_name)
                channel = ctx.channel
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    await self.process_add(ctx, new_channel, channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command(aliases=['renadd'])
    async def pcadd(self, ctx, new_channel: discord.TextChannel, *args):
        """Add a player to a PC or renamed house."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                channel = ctx.channel
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    await self.process_add(ctx, new_channel, channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command()
    async def addhere(self, ctx, *rolechats: discord.TextChannel):
        """Add the player from each mentioned RC to this channel."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        for rolechat in rolechats:
            if rolechat is not None:
                channel = rolechat
                new_channel = ctx.channel
                await self.process_add(ctx, new_channel, channel, is_stealth=False, read_only=False)
            else:
                await ctx.send(f"{rolechat.name} not found.")

    @commands.command(name="addspons", aliases=["addsponsor"])
    async def addspons(self, ctx, sponsor: discord.Member, rolechat: discord.TextChannel = None, *args):
        """Add a sponsor to a rolechat (RC) directly.

        Usage: `.addspons @Sponsor #rc`           — add with a Joins message
               `.addspons @Sponsor #rc stealth`   — add silently
               `.addspons @Sponsor #rc read`      — read-only (cannot send)
        Omit the channel to use the current one (must be an RC).
        """
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        channel = rolechat or ctx.channel
        rc_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        alt_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        dead_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        valid_categories = tuple(c for c in (rc_category, alt_category, dead_category) if c)
        if valid_categories and channel.category not in valid_categories:
            await ctx.send(f"{channel.mention} is not a Rolechat channel.")
            return

        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))

        give_role = False
        if sponsor_role and sponsor_role not in sponsor.roles:
            class AddsponsConfirmView(View):
                def __init__(self):
                    super().__init__(timeout=60)
                    self.value = None
                    self.message = None

                @discord.ui.button(label="Add sponsor role + access", style=discord.ButtonStyle.success, emoji="✅")
                async def add_both(self, interaction: discord.Interaction, button: Button):
                    if interaction.user != ctx.author:
                        return await interaction.response.send_message("Only the command user can choose.", ephemeral=True)
                    self.value = "both"
                    self.stop()
                    await interaction.response.defer()

                @discord.ui.button(label="Channel access only", style=discord.ButtonStyle.primary, emoji="🔑")
                async def add_channel(self, interaction: discord.Interaction, button: Button):
                    if interaction.user != ctx.author:
                        return await interaction.response.send_message("Only the command user can choose.", ephemeral=True)
                    self.value = "channel"
                    self.stop()
                    await interaction.response.defer()

                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
                async def cancel(self, interaction: discord.Interaction, button: Button):
                    if interaction.user != ctx.author:
                        return await interaction.response.send_message("Only the command user can choose.", ephemeral=True)
                    self.value = "cancel"
                    self.stop()
                    await interaction.response.defer()

                async def on_timeout(self):
                    for child in self.children:
                        child.disabled = True
                    if self.message:
                        try:
                            await self.message.edit(view=self)
                        except Exception:
                            pass

            view = AddsponsConfirmView()
            prompt = await ctx.send(
                f"{sponsor.mention} does not have the **{sponsor_role.name}** role.\n"
                f"Choose an option:",
                view=view,
            )
            view.message = prompt
            await view.wait()
            if view.value == "cancel" or view.value is None:
                for child in view.children:
                    child.disabled = True
                try:
                    await prompt.edit(content="Action cancelled.", view=view)
                except Exception:
                    pass
                return
            if view.value == "both":
                give_role = True
            # channel only -> no role
            for child in view.children:
                child.disabled = True
            try:
                await prompt.edit(content="Processing...", view=view)
            except Exception:
                pass
        elif not sponsor_role:
            prompt = await ctx.send(
                f"The sponsor role isn't configured in guild data, but it may still exist.\n"
                f"Do you still want to add {sponsor.mention} to {channel.mention} anyway?\n"
                f"Reply **yes** to confirm, anything else to cancel."
            )
            def check_role(m):
                return m.author == ctx.author and m.channel == ctx.channel
            try:
                response = await self.bot.wait_for("message", timeout=60, check=check_role)
            except asyncio.TimeoutError:
                await prompt.edit(content="Timed out. Action cancelled.")
                return
            if response.content.lower() != "yes":
                await prompt.edit(content="Action cancelled.")
                return
            try:
                await prompt.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

        if give_role and sponsor_role:
            try:
                await sponsor.add_roles(sponsor_role, reason=f".addspons by {ctx.author}")
            except (discord.Forbidden, discord.HTTPException) as exc:
                await ctx.send(f"Could not add the sponsor role: {exc}")
                return

        stealth = 'stealth' in args
        read_only = 'read' in args

        try:
            await channel.set_permissions(
                sponsor, read_messages=True, send_messages=not read_only
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await ctx.send(f"Could not update permissions: {exc}")
            return

        if not stealth:
            await channel.send(f'{sponsor.mention} Joins')

        log_channel = discord.utils.get(ctx.guild.channels, name=guild_data.get("log_channel_name"))
        if log_channel:
            embed = discord.Embed(
                title='Sponsor added',
                description=f'{sponsor.mention} `[{sponsor.display_name}, {sponsor.name}]`',
                color=0xff3fb9,
                timestamp=datetime.now(),
            )
            embed.add_field(
                name='Added To:',
                value=f"{channel.mention} `[{channel.name}]`",
                inline=False,
            )
            embed.set_footer(text="Village Game")
            await log_channel.send(embed=embed)

        mode = " (read-only)" if read_only else ""
        if give_role and sponsor_role:
            await ctx.send(f'✅ Gave **{sponsor_role.name}** to {sponsor.mention} and added them to {channel.mention}{mode}.')
        elif sponsor_role and sponsor_role in sponsor.roles:
            await ctx.send(f'✅ {sponsor.mention} added to {channel.mention}{mode}.')
        else:
            await ctx.send(f'✅ {sponsor.mention} added to {channel.mention}{mode} (no sponsor role).')

    async def process_add(self, ctx, new_channel: discord.TextChannel, channel: discord.TextChannel, is_stealth=False, read_only=False):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            members = channel.members
            if new_channel.category == rc_category:
                await ctx.send("**Do you confirm you want to add the player inside a Rolechat?**\nReply with yes/no.")
                def check(m):
                    return m.author == ctx.author and m.content.lower() in ["yes", "no"]
                try:
                    response = await self.bot.wait_for("message", timeout=60, check=check)
                    if response.content.lower() == "yes":
                        pass  # proceed
                    else:
                        await ctx.send("Action cancelled.")
                        return
                except asyncio.TimeoutError:
                    await ctx.send("Time expired. Action cancelled.")
                    return
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
                    if not is_stealth:
                        await new_channel.send(f'{member.mention} Joins')
                    embed = discord.Embed(
                        title='Member added',
                        description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`',
                        color=0xff3fb9,
                        timestamp=datetime.now(),
                    )
                    embed.add_field(name='Added To:', value=f"{new_channel.mention} `[{new_channel.name}]`", inline=False)
                    embed.set_footer(text="Village Game")
                    if log_channel:
                        await log_channel.send(embed=embed)
                    await after_movement_update(ctx, member)
                elif sponsor_role in member.roles:
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
            await ctx.send('Done')
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def remove(self, ctx, channel_str: str, stealth: str = None):
        """Remove a player from the current house."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = _find_house(category, channel_name)
                if new_channel is not None:
                    if stealth is None:
                        await self.process_remove(ctx, new_channel)
                    elif stealth.lower() == 'stealth':
                        await self.process_remove(ctx, new_channel, is_stealth=True)
                    else:
                        await ctx.send(f'{stealth} is not a valid argument')
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command(aliases=['renremove'])
    async def pcremove(self, ctx, new_channel: discord.TextChannel, stealth: str = None):
        """Remove a player from a PC or renamed house."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if new_channel is not None:
                    if stealth is None:
                        await self.process_remove(ctx, new_channel)
                    elif stealth.lower() == 'stealth':
                        await self.process_remove(ctx, new_channel, is_stealth=True)
                    else:
                        await ctx.send(f'{stealth} is not a valid argument')
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def process_remove(self, ctx, new_channel: discord.TextChannel, is_stealth=False):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
            channel = ctx.channel
            members = channel.members
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    ow = new_channel.overwrites_for(member)
                    if ow != discord.PermissionOverwrite():
                        await new_channel.set_permissions(member, overwrite=None)
                        if not is_stealth:
                            await new_channel.send(f'{member.mention} Leaves')
                        embed = discord.Embed(
                            title='Member removed',
                            description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`',
                            color=0xff3fb9,
                            timestamp=datetime.now(),
                        )
                        embed.add_field(name='Removed From:', value=f"{new_channel.mention} `[{new_channel.name}]`", inline=False)
                        embed.set_footer(text="Village Game")
                        if log_channel:
                            await log_channel.send(embed=embed)
                elif sponsor_role in member.roles:
                    ow = new_channel.overwrites_for(member)
                    if ow != discord.PermissionOverwrite():
                        await new_channel.set_permissions(member, overwrite=None)
            # Delegate follower removal to Surveillance cog
            surv_cog = ctx.bot.get_cog("Surveillance")
            if surv_cog:
                await surv_cog._remove_followers_from_house(
                    ctx.guild, guild_data, members, new_channel, is_stealth=is_stealth
                )
            await after_movement_update(ctx, None)
            await ctx.send('Done')
        else:
            await ctx.send("Guild data not loaded.")

    # ──────────────────────────────────────────────────────────────────────────
    # Moving commands
    # ──────────────────────────────────────────────────────────────────────────

    def _is_staff(self, ctx) -> bool:
        """Admins and Overseers act directly; their commands are not sent to the actions log."""
        if ctx.author.guild_permissions.administrator:
            return True
        guild_data = load_guild_data(ctx.guild.id) or {}
        overseer = discord.utils.get(ctx.guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
        return overseer is not None and overseer in ctx.author.roles

    async def _confirm_suggestion(self, ctx, query: str, suggestion) -> bool:
        """Ask the requester to confirm a close match before it is used."""
        view = HouseSuggestView(ctx.author)
        await ctx.send(f"No house matches **{query}**. Did you mean **{suggestion.name}**?", view=view)
        await view.wait()
        return bool(view.result)

    async def _house_from_arg(self, ctx, target: str):
        """Staff: a channel mention, a house number or a house name. Returns None after replying if nothing fits."""
        mention = re.fullmatch(r"<#(\d+)>", target.strip())
        if mention:
            channel = ctx.guild.get_channel(int(mention.group(1)))
            if channel is None:
                await ctx.send("Channel not found.")
                return None
            houses = discord.utils.get(ctx.guild.categories, name=(load_guild_data(ctx.guild.id) or {}).get("houses_category_name"))
            if houses is None or channel.category != houses:
                await ctx.send("That channel isn't in the Houses category, so it can't be a visit target.")
                return None
            return channel
        guild_data = load_guild_data(ctx.guild.id) or {}
        houses = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))
        if houses is None:
            await ctx.send("Houses category not found.")
            return None
        house, error = house_match(houses.channels, target)
        if house is None:
            suggestion = closest_house(houses.channels, target) if error.startswith(NO_MATCH) else None
            await ctx.send(error + (f" Did you mean **{suggestion.name}**?" if suggestion else ""))
        return house

    async def _request_visit(self, ctx, action: str, query: str, stealth: bool = False):
        """Players' `.move` / `.knock`: check the request and send it to the actions log for approval."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        player_cats = [discord.utils.get(ctx.guild.categories, name=guild_data.get(k)) for k in (
            "rc_category_name", "alt_category_name", "dead_rc_category_name")]
        if ctx.channel.category is None or ctx.channel.category not in [c for c in player_cats if c]:
            return await ctx.send(f"Use `.{action}` in your RoleChat to request a visit.")
        player_roles = [discord.utils.get(ctx.guild.roles, name=guild_data.get(k)) for k in (
            "alive_role_name", "sponsor_role_name", "alt_role_name", "dead_role_name")]
        if not any(role and role in ctx.author.roles for role in player_roles):
            return await ctx.send("Only players can request visits.")
        houses = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if houses is None:
            return await ctx.send("Houses category not found.")
        house, error = house_match(houses.channels, query)
        if house is None:
            suggestion = closest_house(houses.channels, query) if error.startswith(NO_MATCH) else None
            if suggestion is None:
                return await ctx.send(error)
            if not await self._confirm_suggestion(ctx, query, suggestion):
                return
            house = suggestion
        actions = self.bot.get_cog("ActionsLogging")
        if actions is None:
            return await ctx.send("Actions logging is not loaded.")
        await actions.create_visit_request(ctx, action, house, query, is_stealth=stealth)

    @commands.command()
    async def move(self, ctx, channel_str: str, *args):
        """Move a player to a house, leaving their current location."""
        if not self._is_staff(ctx):
            return await self._request_visit(ctx, "move", channel_str, stealth='stealth' in args)
        if self._is_staff(ctx):
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                new_channel, _ = house_match(category.channels, channel_str)
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    # ── Locked house warning ──
                    _lh_text, _lh_hit = check_channel_warning(guild_data, new_channel.id, check_locked_house_warning)
                    if _lh_hit:
                        _lh_embed = warning_embed(title="⚠ Locked House", description=_lh_text)
                        _lh_view = StatusWarningConfirmView(ctx.author.id)
                        await self._send_warning(ctx, _lh_embed, _lh_view)
                        await _lh_view.wait()
                        if not _lh_view.confirmed:
                            return
                    # ── Visitblock warning ──
                    _vb_text, _vb_hit = check_channel_warning(guild_data, ctx.channel.id, check_visitblock_warning)
                    if _vb_hit:
                        _vb_embed = warning_embed(title="⚠ Visit Block Active", description=_vb_text)
                        _vb_view = StatusWarningConfirmView(ctx.author.id)
                        await self._send_warning(ctx, _vb_embed, _vb_view)
                        await _vb_view.wait()
                        if not _vb_view.confirmed:
                            return
                    # ── Stealth warning (bypassable) ──
                    if not stealth:
                        _st_text, _st_hit = check_channel_warning(guild_data, ctx.channel.id, check_move_warning)
                        if _st_hit:
                            _st_embed = warning_embed(title="⚠ Stealth Active", description=_st_text)
                            _st_view = StatusWarningConfirmView(ctx.author.id)
                            await self._send_warning(ctx, _st_embed, _st_view)
                            await _st_view.wait()
                            if not _st_view.confirmed:
                                return
                    # ── End status warning ──
                    await self.process_move(ctx, new_channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command()
    async def renmove(self, ctx, target: str, *args):
        """Move a player to a renamed house by name."""
        if not self._is_staff(ctx):
            return await self._request_visit(ctx, "renmove", target)
        new_channel = await self._house_from_arg(ctx, target)
        if new_channel is None:
            return
        if self._is_staff(ctx):
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    # ── Locked house warning ──
                    _lh_text, _lh_hit = check_channel_warning(guild_data, new_channel.id, check_locked_house_warning)
                    if _lh_hit:
                        _lh_embed = warning_embed(title="⚠ Locked House", description=_lh_text)
                        _lh_view = StatusWarningConfirmView(ctx.author.id)
                        await self._send_warning(ctx, _lh_embed, _lh_view)
                        await _lh_view.wait()
                        if not _lh_view.confirmed:
                            return
                    # ── Visitblock warning ──
                    _vb_text, _vb_hit = check_channel_warning(guild_data, ctx.channel.id, check_visitblock_warning)
                    if _vb_hit:
                        _vb_embed = warning_embed(title="⚠ Visit Block Active", description=_vb_text)
                        _vb_view = StatusWarningConfirmView(ctx.author.id)
                        await self._send_warning(ctx, _vb_embed, _vb_view)
                        await _vb_view.wait()
                        if not _vb_view.confirmed:
                            return
                    # ── Stealth warning (bypassable) ──
                    if not stealth:
                        _st_text, _st_hit = check_channel_warning(guild_data, ctx.channel.id, check_move_warning)
                        if _st_hit:
                            _st_embed = warning_embed(title="⚠ Stealth Active", description=_st_text)
                            _st_view = StatusWarningConfirmView(ctx.author.id)
                            await self._send_warning(ctx, _st_embed, _st_view)
                            await _st_view.wait()
                            if not _st_view.confirmed:
                                return
                    # ── End status warning ──
                    await self.process_move(ctx, new_channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    async def process_move(self, ctx, new_channel: discord.TextChannel, is_stealth=False, read_only=False):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
            category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
            rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
            channel = ctx.channel
            members = channel.members
            if await self._channel_has_active_knock(guild_data, channel):
                if not await self._warn_pending_knock(ctx):
                    return
            if new_channel.category == rc_category:
                await ctx.send("**Do you confirm you want to move the player inside a Rolechat?**\nReply with yes/no.")
                def check(m):
                    return m.author == ctx.author and m.content.lower() in ["yes", "no"]
                try:
                    response = await self.bot.wait_for("message", timeout=60, check=check)
                    if response.content.lower() != "yes":
                        await ctx.send("Action cancelled.")
                        return
                except asyncio.TimeoutError:
                    await ctx.send("Time expired. Action cancelled.")
                    return
            old_house_list = []
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    for ch in category.channels:
                        permissions = ch.permissions_for(member)
                        if permissions.send_messages:
                            try:
                                await ch.set_permissions(member, overwrite=None)
                            except (discord.Forbidden, discord.HTTPException):
                                await ctx.send(f"⚠️ Couldn't remove {member.mention} from {ch.name} (permissions).")
                            old_house_list.append(f"{ch.mention} `[{ch.name}]`")
                            if not is_stealth:
                                await ch.send(f'{member.mention} Leaves')
                    try:
                        await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
                    except (discord.Forbidden, discord.HTTPException):
                        await ctx.send(f"⚠️ Couldn't add {member.mention} to {new_channel.mention} (permissions).")
                    if not is_stealth:
                        await new_channel.send(f'{member.mention} Joins')
                    embed = discord.Embed(
                        title='Member moved',
                        description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`',
                        color=0xff3fb9,
                        timestamp=datetime.now(),
                    )
                    if old_house_list:
                        add_text_fields(embed, 'Removed From:', "\n".join(old_house_list))
                    embed.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                    embed.set_footer(text="Village Game")
                    if log_channel:
                        await log_channel.send(embed=embed)
                    await after_movement_update(ctx, member)
                elif sponsor_role in member.roles:
                    for ch in category.channels:
                        permissions = ch.permissions_for(member)
                        if permissions.send_messages:
                            try:
                                await ch.set_permissions(member, overwrite=None)
                            except (discord.Forbidden, discord.HTTPException):
                                await ctx.send(f"⚠️ Couldn't remove {member.mention} from {ch.name} (permissions).")
                    try:
                        await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
                    except (discord.Forbidden, discord.HTTPException):
                        await ctx.send(f"⚠️ Couldn't add {member.mention} to {new_channel.mention} (permissions).")
            await ctx.send(f'Done {new_channel.mention}')
        else:
            await ctx.send("Guild data not loaded.")

    # ──────────────────────────────────────────────────────────────────────────
    # Knocking commands
    # ──────────────────────────────────────────────────────────────────────────

    @commands.command(aliases=["k"])
    async def knock(self, ctx, channel_str: str):
        """Knock on a house door to request entry."""
        if not self._is_staff(ctx):
            return await self._request_visit(ctx, "knock", channel_str)
        if self._is_staff(ctx):
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                # ── Visitblock warning ──
                _vb_text, _vb_hit = check_channel_warning(guild_data, ctx.channel.id, check_visitblock_warning)
                if _vb_hit:
                    _vb_embed = warning_embed(title="⚠ Visit Block Active", description=_vb_text)
                    _vb_view = StatusWarningConfirmView(ctx.author.id)
                    await self._send_warning(ctx, _vb_embed, _vb_view)
                    await _vb_view.wait()
                    if not _vb_view.confirmed:
                        return
                # ── Stealth warning ──
                _st_text, _st_hit = check_channel_warning(guild_data, ctx.channel.id, check_knock_warning)
                if _st_hit:
                    _st_embed = warning_embed(title="⚠ Stealth Active", description=_st_text)
                    _st_view = StatusWarningConfirmView(ctx.author.id)
                    await self._send_warning(ctx, _st_embed, _st_view)
                    await _st_view.wait()
                    if not _st_view.confirmed:
                        return
                # ── End status warning ──
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                new_channel, _ = house_match(category.channels, channel_str)
                if new_channel is not None:
                    # ── Locked house warning ──
                    _lh_text, _lh_hit = check_channel_warning(guild_data, new_channel.id, check_locked_house_warning)
                    if _lh_hit:
                        _lh_embed = warning_embed(title="⚠ Locked House", description=_lh_text)
                        _lh_view = StatusWarningConfirmView(ctx.author.id)
                        await self._send_warning(ctx, _lh_embed, _lh_view)
                        await _lh_view.wait()
                        if not _lh_view.confirmed:
                            return
                    await self.process_knock(ctx, new_channel, guild_data)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command(aliases=["rk"])
    async def renknock(self, ctx, target: str):
        """Knock on a renamed house by name."""
        if not self._is_staff(ctx):
            return await self._request_visit(ctx, "renknock", target)
        new_channel = await self._house_from_arg(ctx, target)
        if new_channel is None:
            return
        if self._is_staff(ctx):
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                # ── Locked house warning ──
                if new_channel is not None:
                    _lh_text, _lh_hit = check_channel_warning(guild_data, new_channel.id, check_locked_house_warning)
                    if _lh_hit:
                        _lh_embed = warning_embed(title="⚠ Locked House", description=_lh_text)
                        _lh_view = StatusWarningConfirmView(ctx.author.id)
                        await self._send_warning(ctx, _lh_embed, _lh_view)
                        await _lh_view.wait()
                        if not _lh_view.confirmed:
                            return
                # ── Visitblock warning ──
                _vb_text, _vb_hit = check_channel_warning(guild_data, ctx.channel.id, check_visitblock_warning)
                if _vb_hit:
                    _vb_embed = warning_embed(title="⚠ Visit Block Active", description=_vb_text)
                    _vb_view = StatusWarningConfirmView(ctx.author.id)
                    await self._send_warning(ctx, _vb_embed, _vb_view)
                    await _vb_view.wait()
                    if not _vb_view.confirmed:
                        return
                # ── Stealth warning ──
                _st_text, _st_hit = check_channel_warning(guild_data, ctx.channel.id, check_knock_warning)
                if _st_hit:
                    _st_embed = warning_embed(title="⚠ Stealth Active", description=_st_text)
                    _st_view = StatusWarningConfirmView(ctx.author.id)
                    await self._send_warning(ctx, _st_embed, _st_view)
                    await _st_view.wait()
                    if not _st_view.confirmed:
                        return
                # ── End status warning ──
                if new_channel is not None:
                    await self.process_knock(ctx, new_channel, guild_data)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    OWNER_IDS = (450772749829537793, 691180618402234399)  # Bidet, Asfro

    @commands.command(aliases=["pendingknocks", "showknocks", "knocks"])
    async def pendingknock(self, ctx, *args):
        """Check if any knocks are pending and show the oldest pending knock age."""
        if ctx.guild is None:
            await ctx.send("This command is not available in DMs.")
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        scan_all = "restart" in [a.lower() for a in args]
        if scan_all and ctx.author.id not in self.OWNER_IDS:
            await ctx.send("Only the bot owners can scan all servers.")
            return

        searching_msg = await ctx.send("Searching for pending knocks...")

        if scan_all:
            pending, scanned = await self._get_pending_knocks(ctx, all_guilds=True)
        else:
            pending, scanned = await self._get_pending_knocks(ctx, all_guilds=False)

        if not pending:
            await searching_msg.edit(content=f"Pending knock: False\nScanned: {scanned} server{'s' if scanned != 1 else ''}")
            return

        lines = [
            "Pending knock: True",
            f"Scanned: {scanned} server{'s' if scanned != 1 else ''}",
            f"Count: {len(pending)}",
        ]
        for created_at, channel, message in pending[:10]:
            age = datetime.now(timezone.utc) - created_at
            lines.append(
                f"{channel.guild.name} | {channel.mention} | "
                f"Age: {self._format_duration(age)} | {message.jump_url}"
            )
        if len(pending) > 10:
            lines.append(f"...and {len(pending) - 10} more")

        await searching_msg.edit(content="\n".join(lines))

    async def _get_pending_knocks(self, ctx, all_guilds=False):
        if all_guilds:
            is_owner = await self.bot.is_owner(ctx.author)
            eligible_guilds = []
            for guild in self.bot.guilds:
                member = guild.get_member(ctx.author.id)
                if is_owner or (member and member.guild_permissions.administrator):
                    eligible_guilds.append(guild)
        else:
            eligible_guilds = [ctx.guild]

        pending = []
        for guild in eligible_guilds:
            guild_data = load_guild_data(guild.id)
            if not guild_data:
                continue

            category = discord.utils.get(guild.categories, name=guild_data["houses_category_name"])
            if not category:
                continue

            for channel in category.channels:
                if not isinstance(channel, discord.TextChannel):
                    continue
                try:
                    async for message in channel.history(limit=50):
                        embed_titles = [embed.title for embed in message.embeds]
                        is_knock_message = (
                            message.author == self.bot.user
                            and "knock knock" in (message.content or "")
                            and (message.pinned or "🚪 Someone is knocking..." in embed_titles)
                        )
                        if is_knock_message:
                            pending.append((message.created_at, channel, message))
                            break
                except discord.Forbidden:
                    continue

        pending.sort(key=lambda item: item[0])
        return pending, len(eligible_guilds)

    def _format_duration(self, delta: timedelta) -> str:
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            total_seconds = 0
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    @staticmethod
    async def _safe_toggle_pin(message, value):
        try:
            if value:
                await message.pin()
            else:
                await message.unpin()
        except (discord.HTTPException, discord.Forbidden):
            pass

    async def process_knock(self, ctx, new_channel: discord.TextChannel, guild_data):
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        log_channel = discord.utils.get(ctx.guild.channels, name=guild_data["log_channel_name"])
        overseer_role = discord.utils.get(ctx.guild.roles, name=guild_data["overseer_role_name"])
        category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        channel = ctx.channel
        members = channel.members
        old_house_list = []
        alive_members_with_permission = []
        dead_members_with_permissions = []
        alt_members_with_permissions = []

        if await self._channel_has_active_knock(guild_data, channel):
            if not await self._warn_pending_knock(ctx):
                return

        for member in new_channel.members:
            if alive_role in member.roles:
                permissions = new_channel.permissions_for(member)
                if permissions.send_messages:
                    alive_members_with_permission.append(member)
            if dead_role in member.roles:
                permissions = new_channel.permissions_for(member)
                if permissions.send_messages:
                    dead_members_with_permissions.append(member)
            if alt_role in member.roles:
                permissions = new_channel.permissions_for(member)
                if permissions.send_messages:
                    alt_members_with_permissions.append(member)

        check = True
        if alive_members_with_permission:
            check = False
        else:
            if guild_data["dead_count"] and dead_members_with_permissions:
                check = False
            elif guild_data["alt_count"] and alt_members_with_permissions:
                check = False

        if check:
            if guild_data["autojoinifempty"]:
                moved_any = False
                for member in members:
                    if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                        moved_any = True
                        for ch in category.channels:
                            permissions = ch.permissions_for(member)
                            if permissions.send_messages:
                                await ch.set_permissions(member, overwrite=None)
                                old_house_list.append(f"{ch.mention} `[{ch.name}]`")
                                await ch.send(f'{member.mention} Leaves')
                        await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                        await new_channel.send(f'{member.mention} Joins')
                        embed = discord.Embed(
                            title='Member moved',
                            description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`',
                            color=0xff3fb9,
                            timestamp=datetime.now(),
                        )
                        if old_house_list:
                            add_text_fields(embed, 'Removed From:', "\n".join(old_house_list))
                        embed.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                        embed.set_footer(text="Village Game")
                        if log_channel:
                            await log_channel.send(embed=embed)
                        await after_movement_update(ctx, member)
                    elif sponsor_role in member.roles:
                        for ch in category.channels:
                            permissions = ch.permissions_for(member)
                            if permissions.send_messages:
                                await ch.set_permissions(member, overwrite=None)
                        await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                if moved_any:
                    await ctx.send("The house is empty. Auto Joining...")
                return
            else:
                await ctx.send("The house is empty")
                return

        total_members = len(alive_members_with_permission)
        if guild_data["dead_count"]:
            total_members += len(dead_members_with_permissions)
        if guild_data["alt_count"]:
            total_members += len(alt_members_with_permissions)

        if total_members >= guild_data["maxmembersinhome"]:
            await ctx.send("The house is full")
            return

        await ctx.send("Knocking...")

        embed = discord.Embed(
            title="🚪 Someone is knocking...",
            description="Use buttons below to open/refuse the knock.",
            color=0xff3fb9,
        )

        view = discord.ui.View(timeout=guild_data["timeout_duration"])
        # Flag to track whether a handler completed (vs. timeout)
        view.handled = False

        async def handle_open(interaction: discord.Interaction):
            is_admin = interaction.user.guild_permissions.administrator
            if not is_admin:
                perms = new_channel.permissions_for(interaction.user)
                if not (perms.read_messages and perms.send_messages):
                    await interaction.response.send_message("You are not in this house.", ephemeral=True)
                    return
                author_roles = set(interaction.user.roles)
                is_alive = alive_role in author_roles
                is_sponsor = sponsor_role in author_roles
                is_dead = dead_role in author_roles and guild_data["can_dead_open"]
                is_alt = alt_role in author_roles and guild_data["can_alt_open"]
                if not (is_alive or is_sponsor or is_dead or is_alt):
                    await interaction.response.send_message("You can't interact with the door.", ephemeral=True)
                    return

            # Mark as handled and stop the view so view.wait() returns immediately
            view.handled = True
            view.stop()

            await interaction.response.defer()
            entered_members = []
            open_old_house_list = []
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    for ch in category.channels:
                        permissions = ch.permissions_for(member)
                        if permissions.send_messages:
                            await ch.set_permissions(member, overwrite=None)
                            open_old_house_list.append(f"{ch.mention} `[{ch.name}]`")
                            await ch.send(f"{member.mention} Leaves")
                    await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                    await new_channel.send(f"{member.mention} Joins")
                    entered_members.append(member)
                    embed_move = info_embed(
                        title="Member moved",
                        description=f"{channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`",
                    )
                    if open_old_house_list:
                        add_text_fields(embed_move, "Removed From:", "\n".join(open_old_house_list))
                    embed_move.add_field(
                        name="Added To:",
                        value=f"{new_channel.mention} `[{new_channel.name}]`",
                        inline=False,
                    )
                    if log_channel:
                        await log_channel.send(embed=embed_move)
                    await after_movement_update(ctx, member)
                elif sponsor_role in member.roles:
                    for ch in category.channels:
                        permissions = ch.permissions_for(member)
                        if permissions.send_messages:
                            await ch.set_permissions(member, overwrite=None)
                    await new_channel.set_permissions(member, read_messages=True, send_messages=True)

            now_ts = int(datetime.now().timestamp())
            joined_lines = "\n".join(
                f"**Member joined:** {m.mention} `[{m.display_name}, {m.name}]`"
                for m in entered_members
            ) or "**Member joined:** None"
            embed_final = discord.Embed(
                description=(
                    f"{joined_lines}\n"
                    f"**Opened by:** {interaction.user.mention} `[{interaction.user.display_name}, {interaction.user.name}]`\n"
                    f"**Time:** <t:{now_ts}:T>"
                ),
                color=0x2ecc71,
            )
            await interaction.edit_original_response(
                content=f"{alive_role.mention} {sponsor_role.mention} knock knock",
                embed=embed_final,
                view=None,
            )
            await self._safe_toggle_pin(knock_message, False)

        async def handle_refuse(interaction: discord.Interaction):
            is_admin = interaction.user.guild_permissions.administrator
            if not is_admin:
                perms = new_channel.permissions_for(interaction.user)
                if not (perms.read_messages and perms.send_messages):
                    await interaction.response.send_message("You are not in this house.", ephemeral=True)
                    return
                author_roles = set(interaction.user.roles)
                is_alive = alive_role in author_roles
                is_sponsor = sponsor_role in author_roles
                is_dead = dead_role in author_roles and guild_data["can_dead_open"]
                is_alt = alt_role in author_roles and guild_data["can_alt_open"]
                if not (is_alive or is_sponsor or is_dead or is_alt):
                    await interaction.response.send_message("You can't interact with the door.", ephemeral=True)
                    return

            view.handled = True
            view.stop()

            await interaction.response.defer()
            alive_users = []
            for member in new_channel.members:
                if alive_role in member.roles:
                    alive_users.append(f"{member.mention} `{member.name}`")
                if guild_data["show_dead_on_refuse"] and dead_role in member.roles:
                    alive_users.append(f"{member.mention} `{member.name}`")
                if guild_data["show_alt_on_refuse"] and alt_role in member.roles:
                    alive_users.append(f"{member.mention} `{member.name}`")

            if guild_data["refuseresponse"] == 1:
                players_list = "\n".join(alive_users)
                embedr = info_embed(
                    title="Knock Refused",
                    description=f"Players inside the house:\n{players_list}",
                )
                await ctx.send(f"{alive_role.mention} {sponsor_role.mention}", embed=embedr)
            elif guild_data["refuseresponse"] == 2:
                await ctx.send(
                    f"Your knock in {new_channel.name} got refused.\n"
                    f"There are currently {len(alive_users)} players inside the house."
                )
            elif guild_data["refuseresponse"] == 3:
                await ctx.send(f"Your knock in {new_channel.name} got refused.")

            now_ts = int(datetime.now().timestamp())
            embed_final = discord.Embed(
                description=(
                    f"**Refused by:** {interaction.user.mention} `[{interaction.user.display_name}, {interaction.user.name}]`\n"
                    f"**Time:** <t:{now_ts}:T>"
                ),
                color=0xe74c3c,
            )
            await interaction.edit_original_response(
                content=f"{alive_role.mention} {sponsor_role.mention} knock knock",
                embed=embed_final,
                view=None,
            )
            await self._safe_toggle_pin(knock_message, False)

        async def handle_cancel(interaction: discord.Interaction):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "You don't have permission to cancel the knock.",
                    ephemeral=True,
                )
                return

            view.handled = True
            view.stop()

            await interaction.response.defer()
            await ctx.send("The knock has been cancelled.")
            now_ts = int(datetime.now().timestamp())
            embed_final = discord.Embed(
                description=(
                    f"**Cancelled by:** {interaction.user.mention} `[{interaction.user.display_name}, {interaction.user.name}]`\n"
                    f"**Time:** <t:{now_ts}:T>"
                ),
                color=0xe74c3c,
            )
            await interaction.edit_original_response(
                content=f"{alive_role.mention} {sponsor_role.mention} knock knock",
                embed=embed_final,
                view=None,
            )
            await self._safe_toggle_pin(knock_message, False)

        btn_open = discord.ui.Button(label="Open", style=discord.ButtonStyle.success, emoji="✅", row=0)
        btn_refuse = discord.ui.Button(label="Refuse", style=discord.ButtonStyle.danger, emoji="❌", row=0)
        btn_cancel = discord.ui.Button(label=None, style=discord.ButtonStyle.secondary, emoji="🛑", row=0)

        btn_open.callback = handle_open
        btn_refuse.callback = handle_refuse
        btn_cancel.callback = handle_cancel

        view.add_item(btn_open)
        view.add_item(btn_refuse)
        view.add_item(btn_cancel)

        knock_message = await new_channel.send(
            content=f"{alive_role.mention} {sponsor_role.mention} knock knock",
            embed=embed,
            view=view,
        )
        await self._safe_toggle_pin(knock_message, True)
        try:
            async for messages in new_channel.history(limit=3):
                if messages.type == discord.MessageType.pins_add and messages.author == self.bot.user:
                    await messages.delete()
                    break
        except (discord.HTTPException, discord.Forbidden):
            pass

        # ── Peep Hole reveal ─────────────────────────────────────────────────
        peep_holes = guild_data.get("peep_holes") or {}
        expiry = peep_holes.get(str(new_channel.id))
        if expiry and datetime.now().timestamp() < expiry:
            knocker_names = []
            for m in members:
                if alive_role in m.roles or sponsor_role in m.roles:
                    if channel.permissions_for(m).send_messages:
                        knocker_names.append(m.mention)
            if knocker_names:
                verb = "is" if len(knocker_names) == 1 else "are"
                await new_channel.send(f"🔭 **Peep Hole** reveals: {' & '.join(knocker_names)} {verb} knocking!")

        # Wait for a button press or timeout
        await view.wait()

        # ── Handle timeout ─────────────────────────────────────────────────────
        # view.handled is True only if one of the handlers completed successfully.
        # If it's still False here, the view timed out without any interaction.
        if not view.handled:
            try:
                now_ts = int(datetime.now().timestamp())
                timeout_duration_hours = guild_data["timeout_duration"] // 3600

                if guild_data["autojoinknockexpired"]:
                    # Auto-join all members from the knocking channel into the target house
                    auto_join_old_house_list = []
                    for member in members:
                        if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                            for ch in category.channels:
                                permissions = ch.permissions_for(member)
                                if permissions.send_messages:
                                    await ch.set_permissions(member, overwrite=None)
                                    if alive_role in member.roles or alt_role in member.roles:
                                        auto_join_old_house_list.append(f"{ch.mention} `[{ch.name}]`")
                                        await ch.send(f'{member.mention} Leaves')
                            await new_channel.set_permissions(member, read_messages=True, send_messages=True)
                            if alive_role in member.roles or alt_role in member.roles:
                                await new_channel.send(f'{member.mention} Joins')
                                timeout_embed = discord.Embed(
                                    description=(
                                        f"⏰ **Knock expired — Auto Joined**\n"
                                        f"**Time:** <t:{now_ts}:T>"
                                    ),
                                    color=0x95a5a6,
                                )
                                await knock_message.edit(
                                    content=f"{alive_role.mention} {sponsor_role.mention} knock knock",
                                    embed=timeout_embed,
                                    view=None,
                                )
                                embed_move = discord.Embed(
                                    title='Member moved',
                                    description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`',
                                    color=0xff3fb9,
                                    timestamp=datetime.now(),
                                )
                                if auto_join_old_house_list:
                                    add_text_fields(embed_move, 'Removed From:', "\n".join(auto_join_old_house_list))
                                embed_move.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                                embed_move.set_footer(text="Village Game")
                                if log_channel:
                                    await log_channel.send(embed=embed_move)
                                await after_movement_update(ctx, member)
                                await ctx.send(f"{timeout_duration_hours} hours went by from the knock in {new_channel.mention}. Auto Joining...")
                else:
                    # Notify overseer/roles that the knock expired, no auto-join
                    await ctx.send(
                        f"{overseer_role.mention} {alive_role.mention} {sponsor_role.mention}\n"
                        f"{timeout_duration_hours} hours went by from the knock in {new_channel.mention}"
                    )
                    timeout_embed = discord.Embed(
                        description=(
                            f"⏰ **Knock expired** — no response received.\n"
                            f"**Time:** <t:{now_ts}:T>"
                        ),
                        color=0x95a5a6,
                    )
                    await knock_message.edit(
                        content=f"{alive_role.mention} {sponsor_role.mention} knock knock",
                        embed=timeout_embed,
                        view=None,
                    )

                await knock_message.unpin()
            except discord.NotFound:
                pass  # message was deleted externally, nothing to do
            except Exception as e:
                print(f"[Moving] Error handling knock timeout: {e}")

    @commands.command(name="movehouse")
    async def movehouse(self, ctx, src_channel: discord.TextChannel, dest_channel: discord.TextChannel):
        """Bulk-move all residents from one house to another. Admin only."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        houselist = guild_data.get("houselist") or []
        if not isinstance(houselist, list):
            houselist = []
        if src_channel.name not in houselist or dest_channel.name not in houselist:
            await ctx.send("Both channels must be registered houses.")
            return
        if src_channel.id == dest_channel.id:
            await ctx.send("Source and destination cannot be the same house.")
            return
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        members_in_src = [
            m for m in src_channel.members
            if src_channel.permissions_for(m).send_messages
            and (alive_role in m.roles or alt_role in m.roles or sponsor_role in m.roles)
        ]
        if not members_in_src:
            await ctx.send("No residents to move.")
            return
        names = ", ".join(m.mention for m in members_in_src)
        confirm_msg = await ctx.send(
            f"Move all residents from {src_channel.mention} → {dest_channel.mention}?\n"
            f"This affects: {names}\n"
            f"Reply **yes** to confirm, anything else to cancel."
        )
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        try:
            response = await self.bot.wait_for("message", timeout=60, check=check)
        except asyncio.TimeoutError:
            await confirm_msg.edit(content="Timed out. Action cancelled.")
            return
        if response.content.lower() != "yes":
            await confirm_msg.edit(content="Action cancelled.")
            return
        moved = []
        for member in members_in_src:
            await src_channel.set_permissions(member, overwrite=None)
            await dest_channel.set_permissions(member, read_messages=True, send_messages=True)
            current = guild_data.setdefault("current_houses", {})
            house_list = current.setdefault(str(member.id), [])
            if src_channel.id in house_list:
                house_list.remove(src_channel.id)
            if dest_channel.id not in house_list:
                house_list.append(dest_channel.id)
            current[str(member.id)] = house_list
            if str(member.id) in guild_data["member_homes"]:
                if guild_data["member_homes"][str(member.id)] == str(src_channel.id):
                    guild_data["member_homes"][str(member.id)] = str(dest_channel.id)
            moved.append(member.display_name)
        save_guild_data(ctx.guild.id, guild_data)
        color = guild_data.get("narration_color", 0xdc143c) if guild_data else 0xdc143c
        narration = discord.Embed(
            description=(
                "The call echoes through the old dwelling.\n"
                "Every soul stirs and follows.\n"
                "A great migration begins."
            ),
            color=color
        )
        await src_channel.send(embed=narration)
        moved_str = ", ".join(f"**{n}**" for n in moved)
        await ctx.send(
            f"🏠 Moved to {dest_channel.mention} — {len(moved)} resident{'s' if len(moved) != 1 else ''} relocated.\n"
            f"Moved: {moved_str}"
        )

    # ── Portal command ────────────────────────────────────────

    def _is_admin_or_overseer(self, ctx: commands.Context) -> bool:
        if ctx.author.guild_permissions.administrator:
            return True
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            os_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("overseer_role_name", ""))
            if os_role and os_role in ctx.author.roles:
                return True
        return False

    async def _portal_move(self, source_channel: discord.TextChannel, dest_channel: discord.TextChannel, guild_data: dict) -> list[str]:
        """Move every resident of *source_channel* into *dest_channel*.

        Mirrors the standard house move (permission overwrites, Joins/Leaves,
        Member-moved log, Follow/Track/Stalk sync, current_houses/member_homes).
        Returns the list of moved display names.
        """
        guild = source_channel.guild
        alive_role = discord.utils.get(guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(guild.roles, name=guild_data["sponsor_role_name"])
        dead_role = discord.utils.get(guild.roles, name=guild_data["dead_role_name"])
        alt_role = discord.utils.get(guild.roles, name=guild_data["alt_role_name"])
        log_channel = discord.utils.get(guild.channels, name=guild_data["log_channel_name"])
        category = discord.utils.get(guild.categories, name=guild_data["houses_category_name"])

        members = [m for m in source_channel.members if not m.bot]
        moved: list[str] = []

        for member in members:
            is_resident = alive_role in member.roles or dead_role in member.roles or alt_role in member.roles
            is_sponsor = sponsor_role in member.roles
            if not (is_resident or is_sponsor):
                continue

            old_house_list = []
            for ch in category.channels:
                if not ch.permissions_for(member).send_messages:
                    continue
                try:
                    await ch.set_permissions(member, overwrite=None)
                except (discord.Forbidden, discord.HTTPException):
                    continue
                old_house_list.append(f"{ch.mention} `[{ch.name}]`")
                await ch.send(f"{member.mention} Leaves")

            try:
                await dest_channel.set_permissions(member, read_messages=True, send_messages=True)
            except (discord.Forbidden, discord.HTTPException):
                continue
            await dest_channel.send(f"{member.mention} Joins")
            moved.append(member.display_name)

            if is_sponsor:
                continue

            embed = discord.Embed(
                title='Member moved',
                description=f'{source_channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`',
                color=0xff3fb9,
                timestamp=datetime.now(),
            )
            if old_house_list:
                add_text_fields(embed, 'Removed From:', "\n".join(old_house_list))
            embed.add_field(name='Added To:', value=f'{dest_channel.mention} `[{dest_channel.name}]`', inline=False)
            embed.set_footer(text="Village Game")
            if log_channel:
                try:
                    await log_channel.send(embed=embed)
                except discord.HTTPException:
                    pass
            proxy = types.SimpleNamespace(guild=guild, bot=self.bot)
            await after_movement_update(proxy, member)

        if moved:
            current = guild_data.setdefault("current_houses", {})
            member_homes = guild_data.get("member_homes") or {}
            for member in members:
                if not (alive_role in member.roles or dead_role in member.roles or alt_role in member.roles or sponsor_role in member.roles):
                    continue
                key = str(member.id)
                house_list = current.setdefault(key, [])
                if source_channel.id in house_list:
                    house_list.remove(source_channel.id)
                if dest_channel.id not in house_list:
                    house_list.append(dest_channel.id)
                current[key] = house_list
                if key in member_homes and member_homes[key] == str(source_channel.id):
                    member_homes[key] = str(dest_channel.id)
            guild_data["current_houses"] = current
            guild_data["member_homes"] = member_homes
            save_guild_data(guild.id, guild_data)

        return moved

    @commands.command(name="pportal", aliases=["portal"])
    async def pportal(
        self,
        ctx: commands.Context,
        house_a: discord.TextChannel,
        house_b: discord.TextChannel,
        uses: int = None,
    ):
        """Place a bidirectional portal between two houses.

        Each house gets a 🌀 button; any resident inside can click it to move the
        house's residents to the paired house. The buttons are ephemeral (not
        restored after a restart).

        Alive players may click a portal only *N* times (per portal); omit *N*
        for unlimited clicks. Usage: .pportal #house-a #house-b [N]
        """
        if not self._is_admin_or_overseer(ctx):
            await ctx.send("You don't have enough permissions to use this command.")
            return
        if uses is not None and uses < 1:
            await ctx.send("The portal use limit must be **1** or more (omit it for unlimited).")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))
        if house_a.category != houses_category or house_b.category != houses_category:
            await ctx.send("Both channels must be houses inside the Houses category.")
            return
        if house_a.id == house_b.id:
            await ctx.send("The two houses must be different.")
            return

        limit_note = (
            f"Alive players can use each portal **{uses}** "
            f"time{'s' if uses != 1 else ''}."
            if uses is not None
            else "Alive players can use the portal **unlimited** times."
        )
        prompt = await ctx.send(
            f"🌀 {ctx.author.mention}, place a portal between {house_a.mention} ↔ {house_b.mention}?\n"
            f"{limit_note}\n"
            f"Reply **yes** to confirm, anything else to cancel."
        )

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            response = await self.bot.wait_for("message", timeout=60, check=check)
        except asyncio.TimeoutError:
            await prompt.edit(content="Timed out. Portal cancelled.")
            return
        if response.content.lower() != "yes":
            await prompt.edit(content="Portal cancelled.")
            return

        view_a = PortalView(self, house_a, house_b, max_uses=uses)
        view_b = PortalView(self, house_b, house_a, max_uses=uses)
        msg_a = await house_a.send(
            content=f"🌀 A **portal** to {house_b.mention} hums quietly. Click to travel.",
            view=view_a,
        )
        msg_b = await house_b.send(
            content=f"🌀 A **portal** to {house_a.mention} hums quietly. Click to travel.",
            view=view_b,
        )
        view_a.message = msg_a
        view_b.message = msg_b
        await prompt.edit(content=f"🌀 Portal placed between {house_a.mention} ↔ {house_b.mention}.")


async def setup(bot):
    await bot.add_cog(Moving(bot))