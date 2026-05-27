import uuid
import discord
import asyncio
from datetime import datetime
from discord.ext import commands
from cogs.data_utils import load_guild_data
from utils.bot_db import get_role_dashboard
from utils.embeds import info_embed, warning_embed, error_embed


class Moving(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ──────────────────────────────────────────────────────────────────────────
    # Add commands
    # ──────────────────────────────────────────────────────────────────────────

    @commands.command()
    async def add(self, ctx, channel_str: str, *args):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = discord.utils.get(category.channels, name=channel_name)
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
                elif sponsor_role in member.roles:
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
            await ctx.send('Done')
        else:
            await ctx.send("Guild data not loaded.")

    # ──────────────────────────────────────────────────────────────────────────
    # Remove commands
    # ──────────────────────────────────────────────────────────────────────────

    @commands.command()
    async def remove(self, ctx, channel_str: str, stealth: str = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = discord.utils.get(category.channels, name=channel_name)
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
            await ctx.send('Done')
        else:
            await ctx.send("Guild data not loaded.")

    # ──────────────────────────────────────────────────────────────────────────
    # Moving commands
    # ──────────────────────────────────────────────────────────────────────────

    @commands.command()
    async def move(self, ctx, channel_str: str, *args):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = discord.utils.get(category.channels, name=channel_name)
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
                    await self.process_move(ctx, new_channel, is_stealth=stealth, read_only=read_only)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command()
    async def renmove(self, ctx, new_channel: discord.TextChannel, *args):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if new_channel is not None:
                    stealth = 'stealth' in args
                    read_only = 'read' in args
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
                            await ch.set_permissions(member, overwrite=None)
                            old_house_list.append(f"{ch.mention} `[{ch.name}]`")
                            if not is_stealth:
                                await ch.send(f'{member.mention} Leaves')
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
                    if not is_stealth:
                        await new_channel.send(f'{member.mention} Joins')
                    embed = discord.Embed(
                        title='Member moved',
                        description=f'{ctx.channel.mention}\n{member.mention} `[{member.display_name}, {member.name}]`',
                        color=0xff3fb9,
                        timestamp=datetime.now(),
                    )
                    if old_house_list:
                        embed.add_field(name='Removed From:', value="\n".join(old_house_list), inline=False)
                    embed.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                    embed.set_footer(text="Village Game")
                    if log_channel:
                        await log_channel.send(embed=embed)
                elif sponsor_role in member.roles:
                    for ch in category.channels:
                        permissions = ch.permissions_for(member)
                        if permissions.send_messages:
                            await ch.set_permissions(member, overwrite=None)
                    await new_channel.set_permissions(member, read_messages=True, send_messages=not read_only)
            await ctx.send('Done')
        else:
            await ctx.send("Guild data not loaded.")

    # ──────────────────────────────────────────────────────────────────────────
    # Knocking commands
    # ──────────────────────────────────────────────────────────────────────────

    @commands.command()
    async def knock(self, ctx, channel_str: str):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
                channel_name = f'{guild_data["house_prefix"]}{channel_str}'
                new_channel = discord.utils.get(category.channels, name=channel_name)
                if new_channel is not None:
                    await self.process_knock(ctx, new_channel, guild_data)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def renknock(self, ctx, new_channel: discord.TextChannel):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if new_channel is not None:
                    await self.process_knock(ctx, new_channel, guild_data)
                else:
                    await ctx.send("Channel not found")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

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
                for member in members:
                    if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
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
                            embed.add_field(name='Removed From:', value="\n".join(old_house_list), inline=False)
                        embed.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                        embed.set_footer(text="Village Game")
                        if log_channel:
                            await log_channel.send(embed=embed)
                        await ctx.send("The house is empty. Auto Joining...")
                    elif sponsor_role in member.roles:
                        for ch in category.channels:
                            permissions = ch.permissions_for(member)
                            if permissions.send_messages:
                                await ch.set_permissions(member, overwrite=None)
                        await new_channel.set_permissions(member, read_messages=True, send_messages=True)
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
                        embed_move.add_field(
                            name="Removed From:",
                            value="\n".join(open_old_house_list),
                            inline=False,
                        )
                    embed_move.add_field(
                        name="Added To:",
                        value=f"{new_channel.mention} `[{new_channel.name}]`",
                        inline=False,
                    )
                    if log_channel:
                        await log_channel.send(embed=embed_move)
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
            await knock_message.unpin()

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
            await knock_message.unpin()

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
            await knock_message.unpin()

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
        await knock_message.pin()
        async for messages in new_channel.history(limit=3):
            if messages.type == discord.MessageType.pins_add and messages.author == self.bot.user:
                await messages.delete()
                break

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
                                    embed_move.add_field(name='Removed From:', value="\n".join(auto_join_old_house_list), inline=False)
                                embed_move.add_field(name='Added To:', value=f'{new_channel.mention} `[{new_channel.name}]`', inline=False)
                                embed_move.set_footer(text="Village Game")
                                if log_channel:
                                    await log_channel.send(embed=embed_move)
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


async def setup(bot):
    await bot.add_cog(Moving(bot))