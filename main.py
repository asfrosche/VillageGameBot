import asyncio
import io
import json
import os
import random
import sqlite3

import discord
from discord.ext import commands
from datetime import datetime

from cogs.actions_logging_cog import ActionsLogging
from cogs.aux_battle import AuxBattle
from cogs.bday import Birthday
from cogs.data_utils import (
    base_variables,
    deadlist_db_path,
    delete_guild_data,
    init_deadlist_db,
    init_invites_db,
    invites_db_path,
    load_guild_data,
    load_invites,
    save_guild_data,
    save_invites,
)
from utils.bot_db import delete_target_channel
from cogs.game_manager import GameManager
from cogs.game_manager_en import GameManagerEn
from cogs.game_manager_it import GameManagerIt
from cogs.economy_cog import Economy
from cogs.dashboard_cog import Dashboard
from cogs.handling_cog import Handling
from cogs.home_cog import Home
from cogs.infos_cog import Infos
from cogs.lists_cog import Lists
from cogs.location_manager import LocationManager
from cogs.meetupmatrix import Meetup
from cogs.moving_cog import Moving
from cogs.nominations_cog import Nominations
from cogs.other_cog import Other
from cogs.presets_cog import Presets
from cogs.privatecommands_cog import Privatecommands
from cogs.send_role import SendRole
from cogs.setup_cog import Setup
from cogs.tracker_cog import MessageTracker
from cogs.utility_cog import Utility
from cogs.vg_intro import VgIntro
from cogs.voting_cog import Voting
from config import PREFIX, TOKEN
from utils.embeds import error_embed, info_embed, plain_embed
from cogs.estate_cog import Estate
from cogs.item_drop_cog import ItemDrop
from cogs.channel_cog import ChannelMap



intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, help_command=None, intents=intents)

init_invites_db()
init_deadlist_db()

@bot.event
async def on_ready():
    for guild in bot.guilds:
        guild_data = load_guild_data(guild.id)
        if guild_data is None:
            guild_data = base_variables
            save_guild_data(guild.id, guild_data)
    for guild in bot.guilds:
        current_invites = await guild.invites()
        invites = {invite.code: invite.uses for invite in current_invites}
        save_invites(guild.id, invites)
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.playing,
            name="With Bidet",
        )
    )
    print("Server in cui si trova il bot:")
    for guild in bot.guilds:
        print(f'- {guild.name}')
    # Load dynamic/optional cogs that are not added via startcog()
    try:
        await bot.load_extension("cogs.library_cog")
    except Exception as e:
        print(f"Errore caricamento Lybrary cog: {e}")
    try:
        await bot.load_extension("cogs.library_it_cog")
    except Exception as e:
        print(f"Errore caricamento Ita Lybrary cog: {e}")
    try:
        await bot.load_extension("cogs.meeting_cog")
    except Exception as e:
        print(f"Errore caricamento Meetings cog: {e}")
    try:
        await bot.load_extension('cogs.os_info_cog')
    except Exception as e:
        print(f"Errore caricamento Overseer cog: {e}")
    


@bot.event
async def on_guild_join(guild):
    bidet = bot.get_user(450772749829537793)
    if bidet:
        await bidet.send(f"Bot joined a new server: {guild.name}")
    welcome_channel = guild.system_channel
    if welcome_channel:
        embedw = plain_embed(
            title="Hello there👋! And thanks for adding Village Game!",
        )
        embedw.add_field(
            name="My default prefix is:",
            value=f"`{bot.command_prefix}`\nIt can be changed by an admin by using the `.prefix` command👾",
            inline=False,
        )
        embedw.add_field(
            name="Commands:",
            value=(
                "Get started with `.help` command, it will send you all commands of the bot!🤖\n"
                "Then use the `.help {category}` command to go further into commands🏳️"
            ),
            inline=False,
        )
        embedw.set_thumbnail(
            url=(
                "https://media1.giphy.com/media/"
                "v1.Y2lkPTc5MGI3NjExdHRscTV0cG1oejNtaXRhcjRwY3g5OXlmc281NmJhejJlMTBydDNwdC"
                "ZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/yoJC2mx6HwjayMefeg/giphy.gif"
            )
        )
        await welcome_channel.send(embed=embedw)
    # Ensure default guild settings exist
    if load_guild_data(guild.id) is None:
        save_guild_data(guild.id, base_variables)
    current_invites = await guild.invites()
    invites = {invite.code: invite.uses for invite in current_invites}
    save_invites(guild.id, invites)

@bot.event
async def on_guild_remove(guild):
    bidet = bot.get_user(450772749829537793)
    if bidet:
        await bidet.send(f"Bot left a server: {guild.name}")

    guild_id = guild.id
    guild_id_str = str(guild.id)

    conn_invites = sqlite3.connect(invites_db_path)
    c_invites = conn_invites.cursor()
    c_invites.execute('DELETE FROM invites WHERE guild_id = ?', (guild_id,))
    conn_invites.commit()
    conn_invites.close()

    conn_deadlist = sqlite3.connect(deadlist_db_path)
    c_deadlist = conn_deadlist.cursor()
    c_deadlist.execute('DELETE FROM deadlist WHERE server = ?', (guild_id,))
    conn_deadlist.commit()
    conn_deadlist.close()

    presets_cog = bot.get_cog('Presets')
    if presets_cog:
        await presets_cog._remove_all_for_guild(guild_id_str)

    nominations_cog = bot.get_cog('Nominations')
    if nominations_cog:
        channel_ids_in_guild = [c.id for c in guild.channels]
        if channel_ids_in_guild:
            await nominations_cog.conn.execute(f"DELETE FROM votes WHERE channel_id IN ({','.join('?' for _ in channel_ids_in_guild)})", tuple(channel_ids_in_guild))

        await nominations_cog.conn.execute("DELETE FROM tokens WHERE guild_id = ?", (guild_id,))
        await nominations_cog.conn.commit()

    # Clean up persisted settings
    try:
        delete_target_channel(guild_id)
    except Exception:
        pass
    try:
        delete_guild_data(guild_id)
    except Exception:
        pass
    if bidet:
        await bidet.send(f"{guild.name} data deleted")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        embed = error_embed(
            description="Missing required argument. Please check the command usage.",
        )
        await ctx.reply(embed=embed, mention_author=False)
    elif isinstance(error, commands.BadArgument):
        embed = error_embed(
            description="Bad argument. Please check the command usage.",
        )
        await ctx.reply(embed=embed, mention_author=False)
    elif isinstance(error, commands.CheckFailure):
        embed = error_embed(
            description="You don't have permission to use this command.",
        )
        await ctx.reply(embed=embed, mention_author=False)
    elif isinstance(error, discord.errors.HTTPException) and getattr(error, "status", None) == 429:
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            embed = error_embed(
                title="Rate Limited",
                description=f"Rate limit exceeded. Retry in {retry_after:.2f} seconds.",
            )
            await ctx.reply(embed=embed, mention_author=False)
            await asyncio.sleep(retry_after)
    else:
        embed = error_embed(
            description="An unexpected error occurred. Please try again later.",
        )
        await ctx.reply(embed=embed, mention_author=False)

    print(f"Error: {error}")

@bot.event
async def on_message(message):
    if message.author == bot.user or message.author.id == 408785106942164992:
        return
    if not message.guild:
        if message.content.startswith(bot.command_prefix):
            await bot.invoke(await bot.get_context(message))
        return
    guild_data = load_guild_data(message.guild.id)
    if not guild_data:
        return
    content = message.content.lower()
    if content in ("pin", "unpin") and message.reference and message.reference.message_id:
        try:
            replied_message = await message.channel.fetch_message(message.reference.message_id)
            if content == "pin":
                if not replied_message.pinned:
                    await replied_message.pin()
                else:
                    await message.channel.send("Message is already pinned")
            else:
                if replied_message.pinned:
                    await replied_message.unpin()
                    await message.channel.send("Unpinned")
                else:
                    await message.channel.send("Message isn't pinned")
        except discord.NotFound:
            print("Message not found")
        except discord.Forbidden:
            print("Not enough perms")
        except discord.HTTPException:
            print("Network error")   
    if message.author.id == 292953664492929025:
        rc_category   = discord.utils.get(message.guild.categories, name=guild_data.get("rc_category_name"))
        dead_category = discord.utils.get(message.guild.categories, name=guild_data.get("dead_category_name"))
        alt_category  = discord.utils.get(message.guild.categories, name=guild_data.get("alt_category_name"))
        allowed_categories = [c for c in [rc_category, dead_category, alt_category] if c]
        if not allowed_categories:
            return
        if not any(message.channel in cat.channels for cat in allowed_categories):
            return
        original_content = message.content
        if guild_data["whisper_response"] in original_content:
            await message.delete()
            await send_first_embed(message, guild_data)
        elif guild_data["fireworks_response"] in original_content:
            await message.delete()
            await fireworks(message, guild_data)
        elif guild_data["move_in_response"] in original_content:
            await message.delete()
            home = bot.get_cog('Home')
            await home.home_set(message, None, None)
    if message.content.startswith(bot.command_prefix):
        await bot.invoke(await bot.get_context(message))

@bot.event
async def on_message_delete(message):
    if message.author == bot.user or message.author.id == 292953664492929025:
        return
    if message.content:
        guild_data = load_guild_data(message.guild.id)
        if guild_data:
            edit_del_channel_name = guild_data.get("edit_del_logs")
            edit_del_channel = discord.utils.get(
                message.guild.channels,
                name=edit_del_channel_name,
            )
            if edit_del_channel:
                header = (
                    f"**User:** {message.author.mention} `{message.author.name}`\n"
                    f"**Channel:** {message.channel.mention} `[#{message.channel.name}]`"
                )
                if len(message.content) <= 4000:
                    embed = error_embed(
                        title="Message Deleted",
                        description=f"{header}\n\n**Message:**\n{message.content}",
                    )
                    await edit_del_channel.send(embed=embed)
                else:
                    ts = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                    log_content = f"{ts} - {message.author.name}:\n{message.content}"
                    log_file = io.BytesIO(log_content.encode("utf-8"))
                    await edit_del_channel.send(
                        f"**Message Deleted** — {message.author.mention} `{message.author.name}` in {message.channel.mention}:",
                        file=discord.File(log_file, filename="deleted_message.txt"),
                    )

@bot.event
async def on_message_edit(message_before, message_after):
    if message_before.author == bot.user or message_before.author.id == 292953664492929025 or message_before.content == message_after.content:
        return
    if message_before.content and message_after.content:
        guild_data = load_guild_data(message_before.guild.id)
        if guild_data:
            edit_del_channel_name = guild_data.get("edit_del_logs")
            edit_del_channel = discord.utils.get(
                message_before.guild.channels,
                name=edit_del_channel_name,
            )
            if edit_del_channel:
                before_len = len(message_before.content)
                after_len = len(message_after.content)
                header = (
                    f"**User:** {message_before.author.mention} `{message_before.author.name}`\n"
                    f"**Channel:** {message_before.channel.mention} `[#{message_before.channel.name}]`"
                )
                if before_len <= 1900 and after_len <= 1900:
                    embed = plain_embed(
                        title="Message Edited",
                        color=0xFFFF00,
                    )
                    embed.description = (
                        f"{header}\n\n"
                        f"**Message Before:**\n{message_before.content}\n\n"
                        f"**Message After:**\n{message_after.content}"
                    )
                    await edit_del_channel.send(embed=embed)
                else:
                    log_content = (
                        f"{message_before.author.name} edited a message\n\n"
                        f"--- BEFORE ---\n{message_before.content}\n\n"
                        f"--- AFTER ---\n{message_after.content}"
                    )
                    log_file = io.BytesIO(log_content.encode("utf-8"))
                    await edit_del_channel.send(
                        f"**Message Edited** — {message_before.author.mention} `{message_before.author.name}` in {message_before.channel.mention}:",
                        file=discord.File(log_file, filename="edited_message.txt"),
                    )

@bot.event
async def on_member_join(member):
    guild_data = load_guild_data(member.guild.id)
    if not guild_data:
        return
    guild_id = member.guild.id
    new_invites = await member.guild.invites()
    old_invites = load_invites(guild_id) or {}
    inviter = None
    for invite in new_invites:
        if invite.code in old_invites and invite.uses > old_invites[invite.code]:
            inviter = invite.inviter
            break
    join_logs_channel_name = guild_data.get("join_and_leave_logs")
    join_logs_channel = discord.utils.get(member.guild.channels, name=join_logs_channel_name)
    if join_logs_channel:
        if inviter:
            await join_logs_channel.send(
                f"## User Joined ➕\n"
                f"**Name:** {member.mention} `{member.name}`\n"
                f"**Invited by:** {inviter.mention} `{inviter.name}`"
            )
        else:
            await join_logs_channel.send(
                f"## User Joined ➕\n"
                f"**Name:** {member.mention} `{member.name}`"
            )
    updated_invites = {invite.code: invite.uses for invite in new_invites}
    save_invites(guild_id, updated_invites)

@bot.event
async def on_invite_create(invite):
    guild_id = invite.guild.id
    current_invites = load_invites(guild_id) or {}
    current_invites[invite.code] = invite.uses
    save_invites(guild_id, current_invites)

@bot.event
async def on_invite_delete(invite):
    guild_id = invite.guild.id
    current_invites = load_invites(guild_id) or {}
    if invite.code in current_invites:
        del current_invites[invite.code]
        save_invites(guild_id, current_invites)

@bot.event
async def on_member_remove(member):
    if member.id == 1165666436379836506:
        return
    guild_data = load_guild_data(member.guild.id)
    if guild_data:
        leave_logs_channel_name = guild_data.get("join_and_leave_logs")
        leave_logs_channel = discord.utils.get(member.guild.channels, name=leave_logs_channel_name)
        if leave_logs_channel:
            await leave_logs_channel.send(
                f"## User Left ➖\n**Name:** {member.mention} `{member.name}`"
            )

@bot.event
async def on_command(ctx):
    if ctx.guild:
        print(f'In "{ctx.guild.name}" by "{ctx.author}": {ctx.command}')
    if isinstance(ctx.channel, discord.DMChannel):
        print(f'By {ctx.author}: {ctx.command}')

class WhisperTargetSelectView(discord.ui.View):
    def __init__(self, origin_message: discord.Message, guild_data: dict, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.origin_message = origin_message
        self.guild_data = guild_data

        guild = origin_message.guild
        alive_role = discord.utils.get(guild.roles, name=guild_data.get("alive_role_name"))

        options: list[discord.SelectOption] = []
        if alive_role:
            for member in guild.members:
                if alive_role in member.roles:
                    label = member.display_name[:95]
                    options.append(discord.SelectOption(label=label, value=str(member.id)))
                    if len(options) >= 25:
                        break

        select = discord.ui.Select(
            placeholder="Select the whisper recipient...",
            min_values=1,
            max_values=1,
            options=options,
        )

        async def on_select(interaction: discord.Interaction):
            # ── Role/permission check ─────────────────────────────────────────
            guild = interaction.guild
            gd = self.guild_data
            alive_role_obj   = discord.utils.get(guild.roles, name=gd.get("alive_role_name"))
            sponsor_role_obj = discord.utils.get(guild.roles, name=gd.get("sponsor_role_name"))
            dead_role_obj    = discord.utils.get(guild.roles, name=gd.get("dead_role_name"))
            alt_role_obj     = discord.utils.get(guild.roles, name=gd.get("alt_role_name"))
            user_roles = set(interaction.user.roles)
            is_allowed = (
                interaction.user.guild_permissions.administrator
                or alive_role_obj   in user_roles
                or sponsor_role_obj in user_roles
                or dead_role_obj    in user_roles
                or alt_role_obj     in user_roles
            )
            if not is_allowed:
                return await interaction.response.send_message(
                    "You don't have permission to send whispers.",
                    ephemeral=True,
                )

            target_id = int(select.values[0])
            target_member = guild.get_member(target_id) if guild else None
            if not target_member:
                return await interaction.response.send_message(
                    "Selected user is no longer available.",
                    ephemeral=True,
                )

            # ── Lock the menu immediately so no second selection is possible ──
            select.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

            # Ask for the whisper message
            prompt_embed = info_embed(
                title="What message do you want to send?",
                description=(
                    f"Reply to this message with the whisper you want to send to {target_member.mention}.\n"
                    "Remember not to exceed the maximum allowed words (there is a log channel)."
                ),
            )
            # send_message returns None — fetch the real message object right after
            await interaction.response.send_message(embed=prompt_embed)
            prompt_msg = await interaction.original_response()

            try:
                def check(m: discord.Message):
                    return (
                        m.channel == self.origin_message.channel
                        and m.reference is not None
                        and m.reference.message_id == prompt_msg.id
                        and m.author == interaction.user
                    )

                user_response = await bot.wait_for("message", check=check, timeout=300)
                await whisper(
                    self.origin_message,
                    self.guild_data,
                    target_id,
                    user_response.content,
                    user_response.author,
                )
                await self.origin_message.channel.send("Whisper sent.")
            except asyncio.TimeoutError:
                embedto = error_embed(
                    title="Whisper canceled",
                    description="You didn't send a message within the given time.",
                )
                await self.origin_message.channel.send(embed=embedto)

            # Fully remove the view once done
            try:
                if interaction.message:
                    await interaction.message.edit(view=None)
            except Exception:
                pass

            self.stop()

        select.callback = on_select
        self.add_item(select)


async def send_first_embed(message, guild_data):
    """
    Entry point for automated whispers via the overseer bot message.
    Step 1: show a dropdown of alive players.
    Step 2: after a player is selected, ask for the message content by reply.
    """
    embed = info_embed(
        title="Who do you want to send a whisper to?",
        description="Use the dropdown below to select an **alive** player.",
    )
    view = WhisperTargetSelectView(message, guild_data)
    await message.channel.send(embed=embed, view=view)

async def whisper(message, guild_data, mentioned_user_id, user_response1, author):
    user = bot.get_user(mentioned_user_id)
    rc_category = discord.utils.get(message.guild.categories, name=guild_data["rc_category_name"])
    whisper_logs_channel = discord.utils.get(message.guild.channels, name=guild_data["whisper_logs_channel_name"])
    for channel in rc_category.channels:
        if user in channel.members:
            embed = info_embed()
            if guild_data["showwhispersender"]:
                embed.add_field(name=f"{author.mention} `[{author.display_name}]` sent you a whisper:", value=f'{user_response1}', inline=False)
            else:
                embed.add_field(name="Someone sent you a whisper:", value=f'{user_response1}', inline=False)
            await channel.send(f"{user.mention}")
            await channel.send(embed=embed)
            # Log the whisper
            embedlog = info_embed()
            embedlog.add_field(name=f"{author.mention} sent a whisper to {user.mention}:", value=f'{user_response1}\n\n{channel.mention}', inline=False)
            await whisper_logs_channel.send(embed=embedlog)

#fireworks_gifs = ['https://tenor.com/view/fireworks-gif-13143174', 'https://tenor.com/view/fireworks-explosions-lights-gif-17712639', 'https://tenor.com/view/fireworks-firework-night-aesthetic-anime-gif-19222229', 'https://tenor.com/view/firework-2020-2021-2019-fireworks-gif-19768402', 'https://tenor.com/view/firework-gif-21770535', 'https://tenor.com/view/pyroworks-fireworks-mania-firework-happy-new-year-new-year-gif-4556811341928768447', 'https://tenor.com/view/firework-anime-gif-24295480', 'https://tenor.com/view/firework-feuerwerk-s1nnr3-s1nn3rv3-pyroworks-gif-20635964', 'https://tenor.com/view/sono-bisque-doll-wa-koi-wo-suru-fireworks-anime-my-dress-up-darling-festival-gif-25800144']
fireworks_gifs = ['https://tenor.com/view/lanterns-flying-lantern-chinese-lantern-gif-9054613', 'https://tenor.com/view/lanterns-lights-peace-gif-15906930', 'https://tenor.com/view/lantern-lights-ceremony-lanterns-magic-giant-gif-14420747', 'https://tenor.com/view/lanterns-ceremony-lights-memorial-cp-vy0i2xp-uc-gif-14420759', 'https://tenor.com/view/maga-communist-chinese-lanterns-gif-26663664', 'https://tenor.com/view/tangled-tangled-movie-lanterns-tangled-lanterns-i-see-the-light-gif-12379369862241479266']

async def fireworks(message, guild_data):
    alive_role = discord.utils.get(message.guild.roles, name=guild_data["alive_role_name"])
    sponsor_role = discord.utils.get(message.guild.roles, name=guild_data["sponsor_role_name"])
    announcements_channel = discord.utils.get(
        message.guild.channels,
        name=guild_data["announcements_channel_name"],
    )
    houses_category = discord.utils.get(
        message.guild.categories,
        name=guild_data["houses_category_name"],
    )
    random_fireworks_gif = random.choice(fireworks_gifs)
    members = message.channel.members
    for member in members:
        if alive_role in member.roles:
            for channel in houses_category.channels:
                permissions = channel.permissions_for(member)
                if permissions.send_messages:
                    await announcements_channel.send(f"{alive_role.mention}{sponsor_role.mention}\n{member.mention} is in {channel.name}")
                    await announcements_channel.send(f"{random_fireworks_gif}")
                    await message.channel.send('Done')
                    break

async def startcog():
    await bot.add_cog(ActionsLogging(bot))
    await bot.add_cog(Setup(bot))
    await bot.add_cog(SendRole(bot))
    await bot.add_cog(Moving(bot))
    await bot.add_cog(Home(bot))
    await bot.add_cog(Handling(bot))
    await bot.add_cog(Infos(bot))
    await bot.add_cog(Lists(bot))
    await bot.add_cog(Presets(bot))
    await bot.add_cog(Voting(bot))
    await bot.add_cog(Nominations(bot))
    await bot.add_cog(Utility(bot))
    await bot.add_cog(Other(bot))
    await bot.add_cog(Privatecommands(bot))
    await bot.add_cog(MessageTracker(bot))
    await bot.add_cog(LocationManager(bot))
    await bot.add_cog(GameManager(bot))
    await bot.add_cog(GameManagerEn(bot))
    await bot.add_cog(GameManagerIt(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Dashboard(bot))
    await bot.add_cog(AuxBattle(bot))
    await bot.add_cog(Birthday(bot))
    await bot.add_cog(Meetup(bot))
    await bot.add_cog(Estate(bot))
    await bot.add_cog(ItemDrop(bot))
    await bot.add_cog(ChannelMap(bot))
    await bot.add_cog(VgIntro(bot))


asyncio.run(startcog())

bot.run(TOKEN)