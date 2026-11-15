import random
from utils.discord_safe import add_text_fields, split_text
import discord
import datetime
from datetime import datetime
from discord.ext import commands
from discord.ui import Button, View
from cogs.data_utils import load_guild_data, save_guild_data
from cogs.surveillance_cog import after_movement_update
from cogs.status_cog import (
    check_move_warning,
    check_visitblock_warning,
    check_locked_house_warning,
    StatusWarningConfirmView,
    check_channel_warning,
)
from utils.embeds import warning_embed

class Home(commands.Cog):
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

    @staticmethod
    async def _rc_channel_for(role_channel_category, alt_category, name: str):
        """Find or create the RC channel *name*, overflowing into ALTS when ROLES is full.

        Discord caps each category at 50 channels, so with more than 50 alive
        players the extra RoleChats are created in the ALTS category instead.
        """
        rc_channel = discord.utils.get(role_channel_category.channels, name=name)
        if rc_channel:
            return rc_channel
        target = role_channel_category
        if len(target.channels) >= 50 and alt_category:
            target = alt_category
            rc_channel = discord.utils.get(target.channels, name=name)
            if rc_channel:
                return rc_channel
        try:
            return await target.create_text_channel(name)
        except discord.HTTPException:
            if not alt_category or target is alt_category:
                raise
            alt_channel = discord.utils.get(alt_category.channels, name=name)
            return alt_channel or await alt_category.create_text_channel(name)

    @commands.command()
    async def home(self, ctx, type: str = None, user: discord.Member = None, new_channel: discord.TextChannel = None):
        """Bring a player home or manage home assignments (admin)."""
        if ctx.author.guild_permissions.administrator:
            if type is None:
                await self.home_single(ctx)
            elif type.lower() == 'stealth':
                await self.home_single(ctx, is_stealth=True)
            elif type.lower() == 'initialize':
                if user is None:
                    if new_channel is None:
                        await self.home_initialize(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for home initialize command')
                else:
                    await ctx.send(f'{user} is not a valid argument for home initialize command')
            elif type.lower() == 'setup':
                if user is None:
                    if new_channel is None:
                        await self.home_setup(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for home setup command')
                else:
                    await ctx.send(f'{user} is not a valid argument for home setup command')
            elif type.lower() == 'set':
                await self.home_set(ctx, user, new_channel)
            elif type.lower() == 'mset':
                if user is None:
                    if new_channel is None:
                        await self.home_mass_set(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for mass home set command')
                else:
                    await ctx.send(f'{user} is not a valid argument for mass home set command')
            elif type.lower() == 'delete':
                await self.home_delete(ctx, user)
            elif type.lower() == 'return':
                if user is None:
                    if new_channel is None:
                        await self.return_home(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for home return command')
                else:
                    await ctx.send(f'{user} is not a valid argument for home return command')
            elif type.lower() == 'list':
                if user is None:
                    if new_channel is None:
                        await self.list_home(ctx)
                    else:
                        await ctx.send(f'{new_channel} is not a valid argument for home list command')
                else:
                    await ctx.send(f'{user} is not a valid argument for home list command')
            else:
                await ctx.send(f'{type} is not a valid argument')
        elif type is None or type.lower() == 'stealth':
            # Players' `.home` / `.home stealth` go to the actions log for an Overseer to Confirm or Deny.
            await self._request_home(ctx, is_stealth=type is not None)
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def _request_home(self, ctx, is_stealth: bool = False):
        """Players' `.home`: check the request and send it to the actions log for approval."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        player_cats = [discord.utils.get(ctx.guild.categories, name=guild_data.get(k)) for k in (
            "rc_category_name", "alt_category_name", "dead_rc_category_name")]
        if ctx.channel.category is None or ctx.channel.category not in [c for c in player_cats if c]:
            return await ctx.send("Use `.home` in your RoleChat to request a visit home.")
        player_roles = [discord.utils.get(ctx.guild.roles, name=guild_data.get(k)) for k in (
            "alive_role_name", "sponsor_role_name", "alt_role_name", "dead_role_name")]
        if not any(role and role in ctx.author.roles for role in player_roles):
            return await ctx.send("Only players can request visits.")
        houses = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))
        if houses is None:
            return await ctx.send("Houses category not found.")
        home_id = (guild_data.get("member_homes") or {}).get(str(ctx.author.id))
        home = discord.utils.get(houses.channels, id=int(home_id)) if home_id else None
        if home is None:
            return await ctx.send("You don't have a home set. Ask an Overseer to assign one.")
        actions = self.bot.get_cog("ActionsLogging")
        if actions is None:
            return await ctx.send("Actions logging is not loaded.")
        await actions.create_visit_request(ctx, "home", home, "", is_stealth=is_stealth)

    async def home_single(self, ctx, is_stealth=False):
        if ctx.author.guild_permissions.administrator:
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
                # ── Stealth warning (bypassable) ──
                if not is_stealth:
                    _st_text, _st_hit = check_channel_warning(guild_data, ctx.channel.id, check_move_warning)
                    if _st_hit:
                        _st_embed = warning_embed(title="⚠ Stealth Active", description=_st_text)
                        _st_view = StatusWarningConfirmView(ctx.author.id)
                        await self._send_warning(ctx, _st_embed, _st_view)
                        await _st_view.wait()
                        if not _st_view.confirmed:
                            return
                # ── End status warning ──
                # ── Locked house check ──
                locked_homes = []
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                if not category:
                    await ctx.send("Houses category not found")
                    return
                members = ctx.channel.members
                for member in members:
                    home_id = guild_data["member_homes"].get(str(member.id))
                    if home_id:
                        home_channel = discord.utils.get(category.channels, id=int(home_id))
                        if home_channel:
                            _lh_text, _lh_hit = check_channel_warning(guild_data, home_channel.id, check_locked_house_warning)
                            if _lh_hit:
                                locked_homes.append(home_channel.name)
                if locked_homes:
                    unique_locked = ", ".join(f"`{h}`" for h in dict.fromkeys(locked_homes))
                    _lh_embed = warning_embed(title="⚠ Locked House", description=f"The following homes are locked: {unique_locked}")
                    _lh_view = StatusWarningConfirmView(ctx.author.id)
                    await self._send_warning(ctx, _lh_embed, _lh_view)
                    await _lh_view.wait()
                    if not _lh_view.confirmed:
                        return
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
                if not category:
                    await ctx.send("Houses category not found")
                    return
                no_home = []
                errors = []
                for member in members:
                    if alive_role in member.roles or alt_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                try:
                                    await channel.set_permissions(member, overwrite=None)
                                    if not is_stealth:
                                        await channel.send(f'{member.mention} Leaves')
                                except (discord.Forbidden, discord.HTTPException):
                                    errors.append(f"Couldn't clear {member.display_name} from {channel.name}")
                        home_id = guild_data["member_homes"].get(str(member.id))
                        if home_id:
                            home_channel = discord.utils.get(category.channels, id=int(home_id))
                            if home_channel:
                                try:
                                    await home_channel.set_permissions(member, read_messages=True, send_messages=True)
                                    if not is_stealth:
                                        await home_channel.send(f'{member.mention} Joins')
                                except (discord.Forbidden, discord.HTTPException):
                                    errors.append(f"Couldn't restore {member.display_name} to {home_channel.name}")
                        else:
                            no_home.append(member.mention)
                        await after_movement_update(ctx, member)
                    elif sponsor_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                try:
                                    await channel.set_permissions(member, overwrite=None)
                                except (discord.Forbidden, discord.HTTPException):
                                    errors.append(f"Couldn't clear {member.display_name} from {channel.name}")
                        home_id = guild_data["member_homes"].get(str(member.id))
                        if home_id:
                            home_channel = discord.utils.get(category.channels, id=int(home_id))
                            if home_channel:
                                try:
                                    await home_channel.set_permissions(member, read_messages=True, send_messages=True)
                                except (discord.Forbidden, discord.HTTPException):
                                    errors.append(f"Couldn't restore {member.display_name} to {home_channel.name}")
                        else:
                            no_home.append(member.mention)
                        await after_movement_update(ctx, member)
                await ctx.send('Done')
                if errors:
                    await ctx.send("⚠️ Some permission updates failed (bot may be missing Manage Channels on that category):")
                    for err in errors[:10]:
                        await ctx.send(f"  • {err}")
                if no_home:
                    await ctx.send(
                        f"⚠ No home set for: {', '.join(no_home)}\n"
                        f"Use `.home set @player #house` to assign a home."
                    )
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def home_initialize(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild = ctx.guild
                role_channel_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                alt_category = discord.utils.get(ctx.guild.categories, name=guild_data["alt_category_name"])
                house_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                if not role_channel_category:
                    await ctx.send("RoleChats category not found")
                    return
                if not house_category:
                    await ctx.send("Houses category not found")
                    return
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                members = [member for member in guild.members if alive_role in member.roles]
                numbers = list(range(1, len(members) + 1))
                random.shuffle(numbers)
                status = await ctx.send(f"🧹 Initializing **{len(members)}** homes + RoleChats…")
                errors = []
                for i, member in enumerate(members):
                    role_chat_channel_name = str(numbers[i])
                    house_channel_name = f'{guild_data["house_prefix"]}{numbers[i]}'
                    try:
                        role_chat_channel = await self._rc_channel_for(role_channel_category, alt_category, role_chat_channel_name)
                        house_channel = discord.utils.get(house_category.channels, name=house_channel_name)
                        if not house_channel:
                            house_channel = await house_category.create_text_channel(house_channel_name)
                        await role_chat_channel.set_permissions(member, read_messages=True, send_messages=True)
                        await house_channel.set_permissions(member, read_messages=True, send_messages=True)
                        await self.home_set(ctx, member, house_channel)
                    except (discord.Forbidden, discord.HTTPException) as exc:
                        errors.append(f"{member.display_name} (`{role_chat_channel_name}`): {exc}")
                if errors:
                    await status.edit(
                        content=f"⚠️ Initialization finished with **{len(errors)}** error(s) — the HOUSES category may be full (50 channel limit)."
                    )
                    for err in errors[:10]:
                        await ctx.send(f"  • {err}")
                else:
                    await status.edit(content="Initialization completed")
                # Blank divider channel at the bottom of ALTS, below any overflow RCs
                if alt_category and not discord.utils.get(alt_category.channels, name="--------------"):
                    try:
                        await alt_category.create_text_channel("--------------")
                    except discord.HTTPException:
                        pass  # cosmetic only — never fail initialization over it
                estate_cog = self.bot.get_cog('Estate')
                if estate_cog:
                    await estate_cog.update_estate_map(ctx.guild)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def home_setup(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild = ctx.guild
                role_channel_category = discord.utils.get(guild.categories, name=guild_data["rc_category_name"])
                house_category = discord.utils.get(guild.categories, name=guild_data["houses_category_name"])
                alive_role = discord.utils.get(guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(guild.roles, name=guild_data["sponsor_role_name"])
                if not role_channel_category:
                    await ctx.send("RoleChats category not found")
                    return
                if not house_category:
                    await ctx.send("Houses category not found")
                    return
                for role_channel in role_channel_category.text_channels:
                    alive_member = None
                    sponsor_member = None
                    for member in role_channel.members:
                        if alive_role in member.roles:
                            alive_member = member
                        if sponsor_role in member.roles:
                            sponsor_member = member
                    if alive_member:
                        for house_channel in house_category.text_channels:
                            permissions = house_channel.permissions_for(alive_member)
                            if permissions.read_messages and permissions.send_messages:
                                if sponsor_member:
                                    await house_channel.set_permissions(sponsor_member, read_messages=True, send_messages=True)
                                    await self.home_set(ctx, sponsor_member, house_channel)
                                break
                await ctx.send("Initialization completed")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    async def home_set(self, ctx, user: discord.Member = None, new_channel: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                if user is None:
                    if not category:
                        await ctx.send("Houses category not found")
                        return
                    members = ctx.channel.members
                    for member in members:
                        if alive_role in member.roles or alt_role in member.roles:
                            assigned_channel = None
                            for channel in category.channels:
                                if channel.permissions_for(member).send_messages:
                                    assigned_channel = channel
                                    break
                            if assigned_channel:
                                old_channel_id = guild_data["member_homes"].get(str(member.id))
                                if old_channel_id and old_channel_id != assigned_channel.id:
                                    old_channel = ctx.guild.get_channel(old_channel_id)
                                    if old_channel:
                                        old_msg = await old_channel.send(f"{member.mention} doesn't live here anymore")
                                        await old_msg.pin()
                                guild_data["member_homes"][str(member.id)] = assigned_channel.id
                                new_msg = await assigned_channel.send(f"{member.mention} now lives here")
                                await new_msg.pin()
                        elif sponsor_role in member.roles:
                            assigned_channel = None
                            for channel in category.channels:
                                if channel.permissions_for(member).send_messages:
                                    assigned_channel = channel
                                    break
                            if assigned_channel:
                                guild_data["member_homes"][str(member.id)] = assigned_channel.id
                    await ctx.channel.send("Done")
                else:
                    if new_channel is None:
                        if not category:
                            await ctx.send("Houses category not found")
                            return
                        assigned_channel = None
                        for channel in category.channels:
                            if channel.permissions_for(user).send_messages:
                                assigned_channel = channel
                                break
                        if assigned_channel:
                            old_channel_id = guild_data["member_homes"].get(str(user.id))
                            if old_channel_id and old_channel_id != assigned_channel.id:
                                old_channel = ctx.guild.get_channel(old_channel_id)
                                if old_channel:
                                    old_msg = await old_channel.send(f"{user.mention} doesn't live here anymore")
                                    await old_msg.pin()
                            guild_data["member_homes"][str(user.id)] = assigned_channel.id
                            if alive_role in user.roles or alt_role in user.roles:
                                new_msg = await assigned_channel.send(f"{user.mention} now lives here")
                                await new_msg.pin()
                            await ctx.channel.send("Done")
                    else:
                        old_channel_id = guild_data["member_homes"].get(str(user.id))
                        if old_channel_id and old_channel_id != new_channel.id:
                            old_channel = ctx.guild.get_channel(old_channel_id)
                            if old_channel:
                                old_msg = await old_channel.send(f"{user.mention} doesn't live here anymore")
                                await old_msg.pin()
                        guild_data["member_homes"][str(user.id)] = new_channel.id
                        if alive_role in user.roles or alt_role in user.roles:
                            new_msg = await new_channel.send(f"{user.mention} now lives here")
                            await new_msg.pin()
                        await ctx.channel.send("Done")
                save_guild_data(ctx.guild.id, guild_data)
                estate_cog = self.bot.get_cog('Estate')
                if estate_cog:
                    await estate_cog.update_estate_map(ctx.guild)
            else:
                await ctx.channel.send("Guild data not loaded.")
        else:
            await ctx.channel.send("You don't have enough perms to use this command")

    async def home_mass_set(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                if not category:
                    await ctx.channel.send("Houses category not found.")
                    return
                for member in ctx.guild.members:
                    if alive_role in member.roles or alt_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                guild_data["member_homes"][str(member.id)] = channel.id
                                new_msg = await channel.send(f'{member.mention} now lives here')
                                await new_msg.pin()
                    elif sponsor_role in member.roles:
                        for channel in category.channels:
                            permissions = channel.permissions_for(member)
                            if permissions.send_messages:
                                guild_data["member_homes"][str(member.id)] = channel.id
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.send('Done')
                estate_cog = self.bot.get_cog('Estate')
                if estate_cog:
                    await estate_cog.update_estate_map(ctx.guild)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def home_delete(self, ctx, user: discord.Member = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
                sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
                alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
                if user is None:
                    members = ctx.channel.members
                    for member in members:
                        if alive_role in member.roles or alt_role in member.roles:
                            if str(member.id) in guild_data["member_homes"]:
                                old_house_id = guild_data["member_homes"].get(str(member .id))
                                old_house = ctx.guild.get_channel(old_house_id)
                                del guild_data["member_homes"][str(member.id)]
                                await ctx.send(f'{member.mention} is now homeless')
                                homeless_message = await old_house.send(f"{member.mention} doesn't live here anymore")
                                await homeless_message.pin()
                            else:
                                await ctx.send(f"{member.mention} doesn't have a home yet")
                        elif sponsor_role in member.roles:
                            if str(member.id) in guild_data["member_homes"]:
                                del guild_data["member_homes"][str(member.id)]
                else:
                    if str(user.id) in guild_data["member_homes"]:
                        del guild_data["member_homes"][str(user.id)]
                        await ctx.send(f'{user.mention} is now homeless')
                save_guild_data(ctx.guild.id, guild_data)
                estate_cog = self.bot.get_cog('Estate')
                if estate_cog:
                    await estate_cog.update_estate_map(ctx.guild)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def return_home(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                embedq = discord.Embed(title="Confirm you want to bring everyone home", description="Click a button to confirm or cancel.", color=0xff3fb9, timestamp=datetime.now())
                embedq.set_footer(text="Village Game")
                confirm_view = View(timeout=60)
                async def confirm_callback(interaction):
                    if interaction.user == ctx.author:
                        await interaction.message.delete()
# ── Locked house check ──
                        category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name", ""))
                        locked_homes = []
                        if category:
                            for member_id, channel_id in guild_data["member_homes"].items():
                                channel = ctx.guild.get_channel(int(channel_id))
                                if channel:
                                    _lh_text, _lh_hit = check_channel_warning(guild_data, channel.id, check_locked_house_warning)
                                    if _lh_hit:
                                        locked_homes.append(channel.name)
                        if locked_homes:
                            unique_locked = ", ".join(f"`{h}`" for h in dict.fromkeys(locked_homes))
                            _lh_embed = warning_embed(title="⚠ Locked House", description=f"The following homes are locked: {unique_locked}")
                            _lh_view = StatusWarningConfirmView(ctx.author.id)
                            await self._send_warning(ctx, _lh_embed, _lh_view)
                            await _lh_view.wait()
                            if not _lh_view.confirmed:
                                embedn = discord.Embed(title="Canceled", description="Home return command was canceled", color=discord.Color.red(), timestamp=datetime.now())
                                embedn.set_footer(text="Village Game")
                                await ctx.send(embed=embedn)
                                return
                        loading = await ctx.send("Bringing everyone home...")
                        await self.bring_everyone_home(ctx, guild_data)
                        await loading.delete()
                        embedy = discord.Embed(title="Confirm", description="Everyone has been brought home", color=discord.Color.green(), timestamp=datetime.now())
                        embedy.set_footer(text="Village Game")
                        await ctx.send(embed=embedy)
                    else:
                        await interaction.response.send_message("You can't confirm this action.", ephemeral=True)
                async def cancel_callback(interaction):
                    if interaction.user == ctx.author:
                        await interaction.message.delete()
                        embedn = discord.Embed(title="Canceled", description="Home return command was canceled", color=discord.Color.red(), timestamp=datetime.now())
                        embedn.set_footer(text="Village Game")
                        await ctx.send(embed=embedn) 
                    else:
                        await interaction.response.send_message("You can't cancel this action.", ephemeral=True)
                confirm_button = Button(label="✔Yes", style=discord.ButtonStyle.green)
                confirm_button.callback = confirm_callback
                cancel_button = Button(label="❌No", style=discord.ButtonStyle.red)
                cancel_button.callback = cancel_callback
                confirm_view.add_item(confirm_button)
                confirm_view.add_item(cancel_button)
                await ctx.send(embed=embedq, view=confirm_view)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def bring_everyone_home(self, ctx, guild_data):
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if not category:
            await ctx.send("Houses category not found")
            return
        for member in ctx.guild.members:
            if alive_role in member.roles or alt_role in member.roles:
                for channel in category.channels:
                    permissions = channel.permissions_for(member)
                    if permissions.send_messages:
                        await channel.set_permissions(member, overwrite=None)
                        await channel.send(f'{member.mention} Leaves')
            elif sponsor_role in member.roles:
                for channel in category.channels:
                    permissions = channel.permissions_for(member)
                    if permissions.send_messages:
                        await channel.set_permissions(member, overwrite=None)
        for member_id, channel_id in guild_data["member_homes"].items():
            member = ctx.guild.get_member(int(member_id))
            channel = ctx.guild.get_channel(int(channel_id))
            if member and channel:
                await channel.set_permissions(member, read_messages=True, send_messages=True)
                if alive_role in member.roles or alt_role in member.roles:
                    await channel.send(f'{member.mention} Joins')
                await after_movement_update(ctx, None)

    async def list_home(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                home_list = []
                for member_id, channel_id in guild_data["member_homes"].items():
                    member = ctx.guild.get_member(int(member_id))
                    channel = ctx.guild.get_channel(int(channel_id))
                    if member and channel:
                        home_list.append(f"{member.display_name}: {channel.name}")
                home_list_str = "\n".join(home_list)
                embed = discord.Embed(title="Home List", description=home_list_str, color=0xff3fb9, timestamp=datetime.now())
                await ctx.send(embed=embed)
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def rolechat(self, ctx, type: str = None):
        """Manage RoleChat assignments (admin).

        Usage: `.rolechat initialize` — rebuild one RC per alive player.
               `.rolechat list` (aliases `.rolechat check`, `.rolechat lynch`) — list
               RCs with their players and sponsors.
        """
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        action = (type or "").lower()
        if action == 'initialize':
            await self.rc_initialize(ctx)
        elif action in ('check', 'list', 'lynch'):
            await self.rc_list(ctx)
        else:
            await ctx.send(
                "This is not a valid command. Use `.rolechat initialize` or `.rolechat list`."
            )

    async def rc_initialize(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        guild = ctx.guild
        role_channel_category = discord.utils.get(guild.categories, name=guild_data["rc_category_name"])
        alt_category = discord.utils.get(guild.categories, name=guild_data["alt_category_name"])
        if not role_channel_category:
            await ctx.send("RoleChats category not found.")
            return

        alive_role = discord.utils.get(guild.roles, name=guild_data["alive_role_name"])
        if not alive_role:
            await ctx.send("Alive role not found.")
            return
        members = [member for member in guild.members if alive_role in member.roles]

        status = await ctx.send(
            f"🧹 Rebuilding **{len(members)}** RoleChats — one alive player each "
            f"(overflow into ALTS beyond 50)…"
        )
        errors = []

        # Clean slate: drop every member overwrite from the RC channels (ROLES +
        # any ALTS overflow) so players from a previous game don't linger.
        reset_channels = list(role_channel_category.text_channels)
        if alt_category:
            reset_channels += list(alt_category.text_channels)
        for channel in reset_channels:
            for target, overwrite in list(channel.overwrites.items()):
                # Only clear per-member grants; leave role-level overwrites alone.
                if isinstance(target, discord.Member):
                    try:
                        await channel.set_permissions(target, overwrite=None)
                    except (discord.Forbidden, discord.HTTPException) as exc:
                        errors.append(f"reset #{channel.name}: {exc}")

        numbers = list(range(1, len(members) + 1))
        random.shuffle(numbers)
        for i, member in enumerate(members):
            try:
                role_chat_channel = await self._rc_channel_for(
                    role_channel_category, alt_category, str(numbers[i])
                )
                await role_chat_channel.set_permissions(member, read_messages=True, send_messages=True)
            except (discord.Forbidden, discord.HTTPException) as exc:
                errors.append(f"{member.display_name}: {exc}")

        if errors:
            await status.edit(
                content=f"⚠️ Initialization finished with **{len(errors)}** error(s) — check that the ROLES and ALTS categories aren't both full."
            )
            for err in errors[:10]:
                await ctx.send(f"  • {err}")
        else:
            await status.edit(content="Initialization completed")

        # Blank divider channel at the bottom of ALTS, below any overflow RCs
        if alt_category and not discord.utils.get(alt_category.channels, name="--------------"):
            try:
                await alt_category.create_text_channel("--------------")
            except discord.HTTPException:
                pass  # cosmetic only — never fail initialization over it

    async def rc_list(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command.")
            return
        guild = ctx.guild
        guild_data = load_guild_data(guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        role_channel_category = discord.utils.get(guild.categories, name=guild_data["rc_category_name"])
        alt_category = discord.utils.get(guild.categories, name=guild_data["alt_category_name"])
        alive_role = discord.utils.get(guild.roles, name=guild_data["alive_role_name"])
        sponsor_name = guild_data.get("sponsor_role_name")
        sponsor_role = discord.utils.get(guild.roles, name=sponsor_name) if sponsor_name else None

        # Include ALTS overflow RCs, not just the ROLES category.
        channels = list(role_channel_category.text_channels) if role_channel_category else []
        if alt_category:
            channels += list(alt_category.text_channels)

        rc_lines = []
        empty_count = 0
        for channel in sorted(channels, key=lambda c: c.name):
            entries = []
            for member in sorted(channel.members, key=lambda m: m.display_name.lower()):
                if alive_role and alive_role in member.roles:
                    entries.append(f"{member.mention} `[{member.display_name}]`")
                elif sponsor_role and sponsor_role in member.roles:
                    entries.append(f"{member.mention} `[{member.display_name}]` 💰")
            if entries:
                rc_lines.append(f"{channel.mention}: {', '.join(entries)}")
            else:
                empty_count += 1

        description = "\n".join(rc_lines) if rc_lines else "No players or sponsors found in any RC."
        if empty_count:
            description += f"\n\n*({empty_count} empty RC(s) not shown)*"
        embed = discord.Embed(
            title="RCs List",
            description=description[:4000],
            color=0xff3fb9,
            timestamp=datetime.now(),
        )
        await ctx.send(embed=embed)

    @commands.command()
    async def owner(self, ctx, house: discord.TextChannel = None):
        """List all house owners."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if house:
            perms = house.permissions_for(ctx.author)
            if not ctx.author.guild_permissions.administrator and not perms.read_messages:
                await ctx.send("You don't have enough perms to use this command.")
                return
        if house is None:
            house = ctx.channel
        house_id = house.id
        owners = []
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        for member_id, channel_id in guild_data["member_homes"].items():
            if channel_id == house_id:
                member = ctx.guild.get_member(int(member_id))
                if member and alive_role in member.roles:
                    owners.append(f"{member.mention} `[{member.display_name}]`")
        embed = discord.Embed(title=f"{house.name} Owners:", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        if owners:
            add_text_fields(embed, 'Players:', "\n".join(owners))
        else:
            embed.add_field(name='Players:', value="No owners found in this house.", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="owned", aliases=["myhouses"])
    async def owned(self, ctx):
        """Use in a Role Chat: show the house(s) owned by the player(s) in this channel."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        rc_cats = [discord.utils.get(ctx.guild.categories, name=guild_data.get(k)) for k in (
            "rc_category_name", "alt_category_name", "dead_rc_category_name")]
        if ctx.channel.category is None or ctx.channel.category not in [c for c in rc_cats if c]:
            return await ctx.send("Use `.owned` in a Role Chat channel.")
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name"))
        if houses_category is None:
            return await ctx.send("Houses category not found.")
        homes = guild_data.get("member_homes") or {}
        lines = []
        for member in ctx.channel.members:
            if member.bot:
                continue
            owned_ids = {str(channel_id) for member_id, channel_id in homes.items() if str(member_id) == str(member.id)}
            houses = [c for c in houses_category.channels
                      if isinstance(c, discord.TextChannel) and str(c.id) in owned_ids]
            if houses:
                lines.append(f"{member.mention} `[{member.display_name}]`: " + ", ".join(h.mention for h in houses))
        if not lines:
            return await ctx.send("The player(s) in this Role Chat don't own any houses.")
        embed = discord.Embed(title="Houses owned here", description="\n".join(lines), color=0xff3fb9)
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)

    @commands.command(name="whorc")
    async def whorc(self, ctx, member: discord.Member = None):
        """Show the RoleChats you can send in, and who is in each (like .who). Staff can check another player with .whorc @player."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        target = member or ctx.author
        if target != ctx.author:
            overseer = discord.utils.get(ctx.guild.roles, name=guild_data.get("overseer_role_name", "Overseer"))
            is_staff = ctx.author.guild_permissions.administrator or (overseer is not None and overseer in ctx.author.roles)
            if not is_staff:
                return await ctx.send("Only staff can check another player's RoleChats.")
        rc_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        if rc_category is None:
            return await ctx.send("RoleChats category not found.")

        sent = 0
        for channel in rc_category.text_channels:
            if not channel.permissions_for(target).send_messages:
                continue
            # The people in this RoleChat, like .who: not bots, not admins/staff.
            players = [m for m in channel.members
                       if not m.bot and not m.guild_permissions.administrator
                       and channel.permissions_for(m).send_messages]
            body = chr(10).join(f"`[{m.display_name}]`" for m in players) or "Nobody else is here."
            for chunk in split_text(body, 4000):
                embed = discord.Embed(title=channel.name, description=chunk, color=0xff3fb9)
                embed.set_footer(text=f"Village Game • {channel.mention}")
                await ctx.send(embed=embed)
            sent += 1

        if not sent:
            who = "You can't" if target == ctx.author else f"{target.display_name} can't"
            await ctx.send(f"{who} send messages in any RoleChat.")

    @commands.command()
    async def leaveonlyhomes(self, ctx):
        """Remove all players in this RC from all houses (not PCs). Use in an RC."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
        alt_category = discord.utils.get(ctx.guild.categories, name=guild_data["alt_category_name"])
        if ctx.channel.category not in tuple(c for c in (rc_category, alt_category) if c):
            await ctx.send("This command can only be used in a RoleChat.")
            return
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if not houses_category:
            await ctx.send("Houses category not found.")
            return
        members = ctx.channel.members
        count = 0
        for member in members:
            if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                for channel in houses_category.channels:
                    permissions = channel.permissions_for(member)
                    if permissions.send_messages:
                        await channel.set_permissions(member, overwrite=None)
                        await channel.send(f'{member.mention} Leaves')
                count += 1
        if count:
            await ctx.send(f'Done — removed {count} player(s) from all houses.')
        else:
            await ctx.send('No players found in this RC.')