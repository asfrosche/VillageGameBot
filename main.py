import asyncio
import discord
import os
import datetime
import random
import json
import sqlite3
from discord.ext import commands
from datetime import datetime
from cogs.data_utils import load_guild_data, save_guild_data, base_variables, invites_db_path, init_invites_db, load_invites, save_invites, init_deadlist_db, add_player, remove_player, get_team_players, deadlist_db_path
from cogs.actions_logging_cog import ActionsLogging
from cogs.setup_cog import Setup
from cogs.send_role import SendRole
from cogs.moving_cog import Moving
from cogs.home_cog import Home
from cogs.handling_cog import Handling
from cogs.infos_cog import Infos
from cogs.lists_cog import Lists
from cogs.presets_cog import Presets
from cogs.voting_cog import Voting
from cogs.nominations_cog import Nominations
from cogs.utility_cog import Utility
from cogs.other_cog import Other
from cogs.tracker_cog import MessageTracker
from cogs.privatecommands_cog import Privatecommands
from cogs.location_manager import LocationManager
from cogs.game_manager import GameManager
from cogs.help import HelpCommand
from cogs.aux_battle import AuxBattle
from cogs.soldati_cog import SoldatiGame
from cogs.bday import Birthday  
from cogs.meetupmatrix import Meetup

TOKEN = os.getenv('TOKEN')

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='.', help_command=None, intents=intents)

init_invites_db()
init_deadlist_db()

@bot.event
async def on_ready():
    await asyncio.sleep(8)  # give Discord API time to stabilize

    for guild in bot.guilds:
        guild_data = load_guild_data(guild.id)
        if guild_data is None:
            guild_data = base_variables
            save_guild_data(guild.id, guild_data)
    for guild in bot.guilds:
        try: 
            current_invites = await guild.invites()
            invites = {invite.code: invite.uses for invite in current_invites}
            save_invites(guild.id, invites)
        except Exception as e:
            print(f"Error fetching invites for {guild.name}: {e}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name='With Bidet'))
    print('Server in cui si trova il bot:')
    for guild in bot.guilds:
        print(f'- {guild.name}')
    try:
        await bot.load_extension(f"cogs.senet_cog")
    except Exception as e:
        print(f"Errore caricamento Senet cog: {e}")
    try:
        await bot.load_extension(f"cogs.library_cog")
    except Exception as e:
        print(f"Errore caricamento Lybrary cog: {e}")
    try:
        await bot.load_extension('cogs.meeting_cog')
    except Exception as e:
        print(f"Errore caricamento Meetings cog: {e}")
    


@bot.event
async def on_guild_join(guild):
    guild_data_file = f"db/{guild.id}.json"
    bidet = bot.get_user(450772749829537793)
    await bidet.send(f'Bot joined a new server: {guild.name}')
    welcome_channel = guild.system_channel
    if welcome_channel:
        embedw = discord.Embed(title="Hello there👋! And thanks for adding Village Game!", color=0xff3fb9)
        embedw.add_field(name="My default prefix is:", value="`.`\nIt can be changed by an admin by using the `.prefix` command👾", inline=False)
        embedw.add_field(name="Commands:", value="Get started with `.help` command, it will send you all commands of the bot!🤖\nThen use the `.help {category}` command to go further into commands🏳️", inline=False)
        embedw.set_thumbnail(url="https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExdHRscTV0cG1oejNtaXRhcjRwY3g5OXlmc281NmJhejJlMTBydDNwdCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/yoJC2mx6HwjayMefeg/giphy.gif")
        await welcome_channel.send(embed=embedw)
    if not os.path.exists(guild_data_file):
        with open(guild_data_file, "w") as f:
            json.dump(base_variables, f, indent=4)
    try: 
        current_invites = await guild.invites()
        invites = {invite.code: invite.uses for invite in current_invites}
        save_invites(guild.id, invites)
    except Exception as e:
        print(f"Error fetching invites for {guild.name} on join: {e}")


@bot.event
async def on_guild_remove(guild):
    bidet = bot.get_user(450772749829537793)
    await bidet.send(f'Bot left a server: {guild.name}')

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

    target_channels_file = 'db/target_channels.json'
    if os.path.exists(target_channels_file):
        with open(target_channels_file, 'r+') as f:
            try:
                target_channels = json.load(f)
                if guild_id_str in target_channels:
                    del target_channels[guild_id_str]
                    f.seek(0)
                    json.dump(target_channels, f, indent=4)
                    f.truncate()
            except json.JSONDecodeError:
                pass

    guild_data_file = f"db/{guild.id}.json"
    if os.path.exists(guild_data_file):
        os.remove(guild_data_file)
    await bidet.send(f'{guild.name} data deleted')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Missing required argument. Please check the command usage.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Bad argument. Please check the command usage.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.reply("You don't have permission to use this command.")
    elif isinstance(error, discord.errors.HTTPException):
        if error.status == 429:
            retry_after = error.retry_after
            await ctx.reply(f"Rate limit exceeded. Retry in {retry_after:.2f} seconds.")
            await asyncio.sleep(retry_after)
            return
    else:
        await ctx.reply("An error occurred. Please try again later.")
    print(f'Error: {error}')

@bot.event
async def on_message(message):
    if message.author == bot.user or message.author.id == 408785106942164992:
        return
    if not message.guild:
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
        category = discord.utils.get(message.guild.categories, name=guild_data["rc_category_name"])
        if not category:
            return
        if message.channel not in category.channels:
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
            edit_del_channel = discord.utils.get(message.guild.channels, name=edit_del_channel_name)
            if edit_del_channel:
                if len(message.content) < 1024:
                    embed=discord.Embed(title="Message Deleted", description=f"**User:** {message.author.mention} `{message.author.name}`\n**Channel:** {message.channel.mention} `[#{message.channel.name}]`", color=0xFF0000, timestamp=datetime.now())
                    embed.add_field(name="**Message:**" ,value=message.content, inline=False)
                    embed.set_footer(text="Village Game")
                    await edit_del_channel.send(embed=embed)
                else:
                    log_filename = "del_log.txt"
                    timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                    with open(log_filename, "w") as log_file:
                        log_file.write(f"{timestamp} - {message.author.name}: {message.content}")
                    await edit_del_channel.send(f"{message.author.display_name} `{message.author.name}` message was deleted in {message.channel.mention}:")
                    await edit_del_channel.send(file=discord.File(log_filename))
                    os.remove(log_filename)

@bot.event
async def on_message_edit(message_before, message_after):
    if message_before.author == bot.user or message_before.author.id == 292953664492929025 or message_before.content == message_after.content:
        return
    if message_before.content and message_after.content:
        guild_data = load_guild_data(message_before.guild.id)
        if guild_data:
            edit_del_channel_name = guild_data.get("edit_del_logs")
            edit_del_channel = discord.utils.get(message_before.guild.channels, name=edit_del_channel_name)
            if edit_del_channel:
                if len(message_before.content) < 1024 and len(message_after.content) < 1024:
                    embed = discord.Embed(title="Message Edited", description=f"**User:** {message_before.author.mention} `{message_before.author.name}`\n**Channel:** {message_before.channel.mention} `[#{message_before.channel.name}]`", color=0xFFFF00, timestamp=datetime.now())
                    embed.add_field(name="**Message Before:**", value=message_before.content, inline=False)
                    embed.add_field(name="**Message After:**", value=message_after.content, inline=False)
                    embed.set_footer(text="Village Game")
                    await edit_del_channel.send(embed=embed)
                else:
                    log_filename = "edit_log.txt"
                    with open(log_filename, "w") as log_file:
                        log_file.write(f"{message_before.author.name} Edited a Message\n\nMessage Before:\n{message_before.content}\n\nMessage After:\n{message_after.content}")
                    await edit_del_channel.send(f"{message_before.author.display_name} `{message_before.author.name}` edited a message in {message_before.channel.mention}:")
                    await edit_del_channel.send(file=discord.File(log_filename))
                    os.remove(log_filename)

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
            await leave_logs_channel.send(f"## User Left ➖\n**Name:** {member.mention} `{member.name}`")

@bot.event
async def on_command(ctx):
    if ctx.guild:
        print(f'In "{ctx.guild.name}" by "{ctx.author}": {ctx.command}')
    if isinstance(ctx.channel, discord.DMChannel):
        print(f'By {ctx.author}: {ctx.command}')

async def send_first_embed(message, guild_data):
    embed = discord.Embed(title="What message do you want to send?", description="Answer to this message with the message you want to send, remember to not go against rules like exceed maximum allowed words (there is a log channel)", color=0xff3fb9)
    embed.set_footer(text="Village Game")
    bot_message = await message.channel.send(embed=embed)
    try:
        def check(m):
            return (
                m.channel == message.channel
                and m.reference and m.reference.message_id == bot_message.id
            )
        user_response = await bot.wait_for("message", check=check, timeout=300)
        await send_second_embed(message, guild_data, user_response.channel, user_response.content, user_response.author)
    except asyncio.TimeoutError:
        embedto = discord.Embed(title="Whisper canceled", description="You didn't send a message within the given time", color=discord.Color.red(), timestamp=datetime.now())
        embedto.set_footer(text="Village Game")
        await message.channel.send(embed=embedto)
        return

async def send_second_embed(message, guild_data, channel, user_response1, author):
    embed = discord.Embed(title="Who do you want to send it to?", description="Send the user MENTION answering to this message", color=0xff3fb9)
    embed.set_footer(text="Village Game")
    bot_message = await channel.send(embed=embed)
    alive_role = discord.utils.get(message.guild.roles, name=guild_data["alive_role_name"])
    while True:
        try:
            def check(m):
                return (
                    m.channel == message.channel
                    and m.reference and m.reference.message_id == bot_message.id
                    )
            user_response2 = await bot.wait_for("message", check=check, timeout=300)
            try:
                mentioned_user_id = int(user_response2.content.strip("<@!>"))
            except ValueError:
                embed_invalid = discord.Embed(title="Invalid Mention", description="Please mention a valid user.", color=discord.Color.red())
                embed_invalid.set_footer(text="Village Game")
                await channel.send(embed=embed_invalid)
                continue
            mentioned_user = message.guild.get_member(mentioned_user_id)
            if mentioned_user and alive_role in mentioned_user.roles:
                await whisper(message, guild_data, mentioned_user_id, user_response1, author)
                await message.channel.send('Whisper sent.')
                break
            else:
                embed_invalid = discord.Embed(title="Invalid User Mentioned", description=f"The mentioned user does not have '{alive_role.name}' role. Please mention someone with '{alive_role.name}' role.", color=discord.Color.red())
                embed_invalid.set_footer(text="Village Game")
                await channel.send(embed=embed_invalid)
        except asyncio.TimeoutError:
            embedto = discord.Embed(title="Whisper canceled", description="You didn't send the user within the given time", color=discord.Color.red(), timestamp=datetime.now())
            embedto.set_footer(text="Village Game")
            await channel.send(embed=embedto)
            return

async def whisper(message, guild_data, mentioned_user_id, user_response1, author):
    user = bot.get_user(mentioned_user_id)
    rc_category = discord.utils.get(message.guild.categories, name=guild_data["rc_category_name"])
    whisper_logs_channel = discord.utils.get(message.guild.channels, name=guild_data["whisper_logs_channel_name"])
    for channel in rc_category.channels:
        if user in channel.members:
            embed = discord.Embed(color=0xff3fb9, timestamp=datetime.now())
            if guild_data["showwhispersender"]:
                embed.add_field(name=f"{author.mention} `[{author.display_name}]` sent you a whisper:", value=f'{user_response1}', inline=False)
            else:
                embed.add_field(name="Someone sent you a whisper:", value=f'{user_response1}', inline=False)
            embed.set_footer(text="Village Game")
            await channel.send(f"{user.mention}")
            await channel.send(embed=embed)
            # Log the whisper
            embedlog = discord.Embed(color=0xff3fb9, timestamp=datetime.now())
            embedlog.add_field(name=f"{author.mention} sent a whisper to {user.mention}:", value=f'{user_response1}\n\n{channel.mention}', inline=False)
            embedlog.set_footer(text="Village Game")
            await whisper_logs_channel.send(embed=embedlog)

#fireworks_gifs = ['https://tenor.com/view/fireworks-gif-13143174', 'https://tenor.com/view/fireworks-explosions-lights-gif-17712639', 'https://tenor.com/view/fireworks-firework-night-aesthetic-anime-gif-19222229', 'https://tenor.com/view/firework-2020-2021-2019-fireworks-gif-19768402', 'https://tenor.com/view/firework-gif-21770535', 'https://tenor.com/view/pyroworks-fireworks-mania-firework-happy-new-year-new-year-gif-4556811341928768447', 'https://tenor.com/view/firework-anime-gif-24295480', 'https://tenor.com/view/firework-feuerwerk-s1nnr3-s1nn3rv3-pyroworks-gif-20635964', 'https://tenor.com/view/sono-bisque-doll-wa-koi-wo-suru-fireworks-anime-my-dress-up-darling-festival-gif-25800144']
fireworks_gifs = ['https://tenor.com/view/lanterns-flying-lantern-chinese-lantern-gif-9054613', 'https://tenor.com/view/lanterns-lights-peace-gif-15906930', 'https://tenor.com/view/lantern-lights-ceremony-lanterns-magic-giant-gif-14420747', 'https://tenor.com/view/lanterns-ceremony-lights-memorial-cp-vy0i2xp-uc-gif-14420759', 'https://tenor.com/view/maga-communist-chinese-lanterns-gif-26663664', 'https://tenor.com/view/tangled-tangled-movie-lanterns-tangled-lanterns-i-see-the-light-gif-12379369862241479266']

async def fireworks(message, guild_data):
    alive_role = discord.utils.get(message.guild.roles, name=guild_data["alive_role_name"])
    sponsor_role = discord.utils.get(message.guild.roles, name=guild_data["sponsor_role_name"])
    announcements_channel = discord.utils.get(message.guild.channels, name=guild_data["announcements_channel_name"])
    houses_category = discord.utils.get(message.guild.categories, name=guild_data["houses_category_name"])
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
    await bot.add_cog(HelpCommand(bot))
    await bot.add_cog(AuxBattle(bot))
    await bot.add_cog(SoldatiGame(bot))
    await bot.add_cog(Birthday(bot))
    await bot.add_cog(Meetup(bot))
asyncio.run(startcog())

bot.run(TOKEN)