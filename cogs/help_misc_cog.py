import re
import random
import discord
import asyncio
import datetime
from datetime import datetime
from discord.ext import commands
from discord import AllowedMentions
from discord.ui import Select, View
from cogs.data_utils import load_guild_data


class Other(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def who(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            if channel:
                perms = channel.permissions_for(ctx.author)
                if not ctx.author.guild_permissions.administrator and not perms.read_messages:
                    await ctx.send("You don't have enough perms to use this command")
                    return
            else:
                channel = ctx.channel
            members = channel.members
            embed = discord.Embed(title=f"{channel.name} Members:", color=0xff3fb9, timestamp=datetime.now())
            embed.set_footer(text="Village Game")
            alive_list = []
            dead_list = []
            alt_list = []
            for member in members:
                permissions = channel.permissions_for(member)
                if permissions.send_messages:
                    if alive_role in member.roles:
                        alive_list.append(f"{member.mention} `[{member.display_name}]`")
                    if dead_role in member.roles:
                        dead_list.append(f"{member.mention} `[{member.display_name}]`")
                    if alt_role in member.roles:
                        alt_list.append(f"{member.mention} `[{member.display_name}]`")
            if alive_list:
                embed.add_field(name=f'{alive_role.name}:', value="\n".join(alive_list), inline=False)
            if alt_list:
                embed.add_field(name=f'{alt_role.name}:', value="\n".join(alt_list), inline=False)
            if dead_list:
                embed.add_field(name=f'{dead_role.name}:', value="\n".join(dead_list), inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send('Guild data not loaded.')

    @commands.command()
    async def where(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        spectator_role = discord.utils.get(ctx.guild.roles, name=guild_data["spectator_role_name"])
        if ctx.author.guild_permissions.administrator or spectator_role in ctx.author.roles:
            if channel is None:
                channel = ctx.channel
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            category_houses = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
            category_pcs = discord.utils.get(ctx.guild.categories, name=guild_data["privc_category_name"])
            category_publc = discord.utils.get(ctx.guild.categories, name=guild_data["publc_category_name"])
            members = channel.members
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    embed = discord.Embed(title=f"{member.mention} Location:", color=0xff3fb9, timestamp=datetime.now())
                    embed.set_footer(text="Village Game")
                    houses_list = []
                    if category_houses:
                        for house in category_houses.channels:
                            permissions = house.permissions_for(member)
                            if permissions.send_messages:
                                houses_list.append(house.mention)
                    pcs_list = []
                    if category_pcs:
                        for pc in category_pcs.channels:
                            permissions = pc.permissions_for(member)
                            if permissions.send_messages:
                                pcs_list.append(pc.mention)
                    publc_list = []
                    if category_publc:
                        for pubc in category_publc.channels:
                            permissions = pubc.permissions_for(member)
                            if permissions.send_messages:
                                publc_list.append(pubc.mention)
                    if houses_list:
                        embed.add_field(name="🏠 Houses:", value="\n".join(houses_list), inline=False)
                    if pcs_list:
                        embed.add_field(name="👤 Private Chats:", value="\n".join(pcs_list), inline=False)
                    if publc_list:
                        embed.add_field(name="🏟️ Public Channels:", value="\n".join(publc_list), inline=False)
                    await ctx.send(embed=embed)
                    break
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def loc(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        spectator_role = discord.utils.get(ctx.guild.roles, name=guild_data["spectator_role_name"])
        if not ctx.author.guild_permissions.administrator and not spectator_role in ctx.author.roles:
            await ctx.send("You don't have enough perms to use this command.")
            return
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if not houses_category:
            await ctx.send("Houses category not found.")
            return
        embed = discord.Embed(title="Everyone Location:", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        content_nempty = ""
        content_empty = ""
        for channel in houses_category.channels:
            players = []
            for member in channel.members:
                if alive_role in member.roles or alt_role in member.roles or dead_role in member.roles:
                    permissions = channel.permissions_for(member)
                    if permissions.send_messages:
                        players.append(member.display_name)
            if players:
                content_nempty += f"{channel.name}\n"
                content_nempty += "\n".join(players) + "\n\n"
            else:
                content_empty += f"{channel.name}\n"
        embed.add_field(name="Non Empty Houses:", value=content_nempty, inline=False)
        embed.add_field(name="Empty Houses:", value=content_empty, inline=False)
        await ctx.send(embed=embed)

    @commands.command(aliases=["t"])
    async def timer(self, ctx, tempo: str, tag: str = None, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        pattern = re.compile(r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$")
        match = pattern.match(tempo)
        if not match or not any(match.groups()):
            await ctx.send("Invalid format. Example: 1h2m10s")
            return
        time_dict = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
        total_seconds = time_dict['hours'] * 3600 + time_dict['minutes'] * 60 + time_dict['seconds']
        if total_seconds <= 0:
            await ctx.send("Time value must be greater than 0")
            return
        time_parts = []
        if time_dict['hours']:
            time_parts.append(f"{time_dict['hours']}h")
        if time_dict['minutes']:
            time_parts.append(f"{time_dict['minutes']}m")
        if time_dict['seconds']:
            time_parts.append(f"{time_dict['seconds']}s")
        display_time = " ".join(time_parts)
        await ctx.send(f"⏳ Timer set for {display_time}!")
        await asyncio.sleep(total_seconds)
        message = f"⏰ Time's up!"
        if tag == "tag":
            message += f" {ctx.author.mention}"
        await channel.send(message)

    @commands.command()
    async def roll(self, ctx, role: discord.Role, num_users: int = 1, tag: str = None):
        guild_data = load_guild_data(ctx.guild.id)
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        if role == alt_role and not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to roll for alts.")
            return
        if role.id == ctx.guild.id and not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to roll for everyone.")
            return
        if num_users <= 0:
            await ctx.send('Insert a valid number')
            return
        members_in_role = [member for member in ctx.guild.members if role in member.roles]
        if len(members_in_role) < num_users:
            await ctx.send(f"Not enough members with {role.mention} role", allowed_mentions=discord.AllowedMentions.none())
            return
        random_users = random.sample(members_in_role, num_users)
        user_names = [user.display_name for user in random_users]
        user_tags = [user.mention for user in random_users]
        if tag is None:
            await ctx.send(f'Roll results:\n' + '\n'.join(user_names))
        elif tag.lower() == 'tag':
            if ctx.author.guild_permissions.administrator:
                await ctx.send(f'Roll results:\n' + '\n'.join(user_tags))
            else:
                await ctx.send("You don't have enough perms to use this command")
        else:
            await ctx.send(f'{tag} is not a valid argument')

    @roll.error
    async def roll_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            await ctx.send("I think you want to use `.dice` instead.\nUsage: `.dice <number>` to roll 1-N, or `.dice <option1> <option2> ...` to pick randomly.")
        else:
            raise error

    @commands.command()
    async def narrate(self, ctx, *, message: str):
        if ctx.author.guild_permissions.administrator:
            cleaned_message = re.sub(r'<#\d+>', '', message)
            text_channels = ctx.message.channel_mentions
            if not text_channels:
                guild_data = load_guild_data(ctx.guild.id)
                rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                alt_category = discord.utils.get(ctx.guild.categories, name=guild_data["alt_category_name"])
                if rc_category:
                    for channel in rc_category.text_channels:
                        await channel.send(cleaned_message)
                if alt_category:
                    for c in alt_category.text_channels:
                        await c.send(cleaned_message)
            else:
                for channel in text_channels:
                    await channel.send(cleaned_message)
            await ctx.send('Done')
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def deletechannel(self, ctx):
        if ctx.author.guild_permissions.administrator:
            await ctx.channel.delete()
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def deletecategory(self, ctx):
        if ctx.author.guild_permissions.administrator:
            if ctx.channel.category:
                category = ctx.channel.category
                for channel in category.channels:
                    await channel.delete()
                await category.delete()
            else:
                await ctx.send("This channel doesn't have a category")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def timestamp(self, ctx, date_str: str, time_str: str):
        try:
            datetime_obj = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S")
            timestamp_str = datetime_obj.strftime("<t:%s>" % int(datetime_obj.timestamp()))
            await ctx.send(f"Discord Timestamp: {timestamp_str}")
        except ValueError:
            await ctx.send("Invalid date or time format. Please use 'DD-MM-YYYY' for date and 'HH:MM:SS' for time.")

    @commands.command()
    async def time(self, ctx):
        if ctx.message.reference:
            replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            timestamp = replied_message.created_at
            discord_timestamp = f"<t:{int(timestamp.timestamp())}:T>"
            await ctx.send(f"The message was sent at: {discord_timestamp}")
        else:
            await ctx.send("You need to reply to a message to use this command.")

    @commands.command()
    async def gettag(self, ctx, *, arg=None):
        msg = None
        if ctx.message.reference:
            msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        elif arg:
            m = re.search(r'/channels/\d+/(\d+)/(\d+)', arg)
            if m:
                channel_id, message_id = map(int, m.groups())
                chan = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                msg = await chan.fetch_message(message_id)
            else:
                try:
                    msg = await ctx.channel.fetch_message(int(arg))
                except Exception:
                    await ctx.reply("Invalid message ID or link.", mention_author=False)
                    return
        else:
            await ctx.reply("Please reply to a message or provide its ID/link.", mention_author=False)
            return
        mentions = msg.mentions
        if not mentions:
            return await ctx.reply("No user mentions found in that message.", mention_author=False)
        mention_list = ' '.join(user.mention for user in mentions)
        await ctx.send(mention_list, allowed_mentions=AllowedMentions(users=False, roles=False))
        
    @commands.command(name="firstpin", aliases=["role"])
    async def firstpin(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        spectator_role = discord.utils.get(ctx.guild.roles, name=guild_data["spectator_role_name"])
        if not ctx.author.guild_permissions.administrator and channel:
            if not spectator_role in ctx.author.roles:
                await ctx.send("You do not have permission to use this command.")
                return
        if channel is None:
            channel = ctx.channel
        pins = await channel.pins()
        if not pins:
            await ctx.send("No pinned messages were found in that channel.")
            return
        first_pin = pins[-1]
        embed = discord.Embed(title="First Pinned Message", description=first_pin.content or "*[No content]*", color=0xff3fb9, timestamp=datetime.now())
        embed.add_field(name=" ", value=f"[Jump to the message!]({first_pin.jump_url})", inline=False)
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)
            
    @commands.command()
    async def ping(self, ctx):
        await ctx.send('Pong')

    @commands.command()
    async def ding(self, ctx):
        await ctx.send("Dong! ||MF||")

    @commands.command()
    async def dice(self, ctx, *args):
        if not args:
            await ctx.send("Usage: `.dice <number>` to roll 1-N, or `.dice <option1> <option2> ...` to pick randomly.")
            return
        if len(args) == 1:
            try:
                n = int(args[0])
            except ValueError:
                await ctx.send(f"`{args[0]}` is not a valid number. Usage: `.dice <number>` or `.dice <opt1> <opt2> ...`")
                return
            if n < 1:
                await ctx.send(f"Number must be 1 or higher. Usage: `.dice <number>`")
                return
            result = random.randint(1, n)
            await ctx.send(f"🎲 You rolled a **{result}** (1–{n})!")
        else:
            choice = random.choice(args)
            await ctx.send(f"🎲 I picked: **{choice}**")


    @commands.command()
    async def goat(self, ctx):
        if ctx.author.id == 388776401668538368 or ctx.author.id == 450772749829537793:
            message = await ctx.send('# 🚨 ATTENTION EVERYONE 🚨\nPlease pause your regularly scheduled mediocrity.\nWe’re here to honor the one they tried to contain—but never could.\n\n💥🔥 THE UNDISPUTED LEGEND 🔥💥\n🎖️ MVP of MVPs\n🏆 Winner of Winners\n📜 So decorated, the awards had to be printed in landscape mode\n🥇 Made Heartside rewrite its policy to fit all his wins\n👑 The reason "balance" nerfs exist\n\n# GALAMT — THE ABSOLUTE GOAT\n\nToo powerful to play as a contestant—now only allowed as a sponsor. Because Some OS dont Like him \nWhy? Because every time he plays, the game breaks.\nOverseers are forced to nerf him constantly, or the meta collapses.\n\nHe won 2 times as the evil team with just a 1% chance of victory.\nStatistically impossible.\nGalamt just called it "a Tuesday."\n\n🕯️ Founder of ECG – Evil Cult Graveyard\nIt started as a meme cult during a social deduction match…\nAnd somehow, it’s still active.\nHe didn’t plan to make history—history followed him.\n\nThat look?\n✔️ “I didn’t ask for this power.”\n✔️ “I logged in for fun and broke the leaderboard.”\n✔️ “This isn’t a bug. It’s legacy.”\n\n**#Galamt**\n**#ECG**\n**#TooPowerful**\n**#SponsorOnly**\n**#LionOfTheMeta**')
            await message.delete(delay=60)

    @commands.command()
    async def help2(self, ctx, category: str = None):
        """Show additional command categories."""
        if category is not None:
            category = category.lower()
            extra_categories = {
                "meetupmatrix": self.help_meetupmatrix,
                "economy": self.help_economy,
                "location": self.help_location,
                "dashboard": self.help_dashboard,
                "gamemanager": self.help_gamemanager,
                "library": self.help_library,
                "games": self.help_games,
                "birthdays": self.help_birthdays,
                "calendar": self.help_calendar,
            }
            if category in extra_categories:
                self._in_help2 = True
                await extra_categories[category](ctx)
                return
        self._in_help2 = True
        embed = discord.Embed(title="📂 Extended Command Categories", color=0xff3fb9)
        embed.add_field(name="📊 - Meetings & Meetup Matrix", value="21 Commands\n`.help2 meetupmatrix`", inline=True)
        embed.add_field(name="💰 - Economy", value="18 Commands\n`.help2 economy`", inline=True)
        embed.add_field(name="📍 - Location", value="17 Commands\n`.help2 location`", inline=True)
        embed.add_field(name="🎮 - Dashboard & Info", value="17 Commands\n`.help2 dashboard`", inline=True)
        embed.add_field(name="🎲 - Game Manager", value="4 Commands\n`.help2 gamemanager`", inline=True)
        embed.add_field(name="📚 - Library & Stats", value="19 Commands\n`.help2 library`", inline=True)
        embed.add_field(name="⚔️ - Games (Aux, Senet)", value="18 Commands\n`.help2 games`", inline=True)
        embed.add_field(name="🎂 - Birthdays", value="6 Commands\n`.help2 birthdays`", inline=True)
        embed.add_field(name="📅 - Calendar & Intro", value="4 Commands\n`.help2 calendar`", inline=True)
        embed.set_footer(text="Village Game • Use `.help2 {category}` for details")
        await self.send_help_page(ctx, embed, self.help2)

    @commands.command()
    async def help(self, ctx, category: str = None):
        self._in_help2 = False
        if category is None:
            await self.help_homepage(ctx)
        else:
            category = category.lower()
            categories = {
                "setup": self.help_setup,
                "moving": self.help_moving,
                "home": self.help_home,
                "handling": self.help_handling,
                "infos": self.help_infos,
                "presets": self.help_presets,
                "voting": self.help_voting,
                "nominations": self.help_nominations,
                "lists": self.help_lists,
                "sendrole": self.help_sendrole,
                "utility": self.help_utility,
                "other": self.help_other,
                "meetupmatrix": self.help_meetupmatrix,
                "economy": self.help_economy,
                "location": self.help_location,
                "dashboard": self.help_dashboard,
                "gamemanager": self.help_gamemanager,
                "library": self.help_library,
                "games": self.help_games,
                "birthdays": self.help_birthdays,
                "calendar": self.help_calendar,
            }
            if category in categories:
                await categories[category](ctx)
            else:
                await ctx.send(f"{category} is not a valid category")

    async def send_help_page(self, ctx, embed, callback, options=None):
        if options is None:
            in_help2 = getattr(self, '_in_help2', False)
            if in_help2:
                options = [
                    discord.SelectOption(label="📊 - Meetings & Meetup Matrix", value="meetupmatrix", description="Get all 'Meetings & Meetup Matrix' commands"),
                    discord.SelectOption(label="💰 - Economy", value="economy", description="Get all 'Economy' commands"),
                    discord.SelectOption(label="📍 - Location", value="location", description="Get all 'Location' commands"),
                    discord.SelectOption(label="🎮 - Dashboard & Info", value="dashboard", description="Get all 'Dashboard & OS Info' commands"),
                    discord.SelectOption(label="🎲 - Game Manager", value="gamemanager", description="Get all 'Game Manager' commands"),
                    discord.SelectOption(label="📚 - Library & Stats", value="library", description="Get all 'Library & Stats' commands"),
                    discord.SelectOption(label="⚔️ - Games (Aux, Senet)", value="games", description="Get all 'Games' commands"),
                    discord.SelectOption(label="🎂 - Birthdays", value="birthdays", description="Get all 'Birthday' commands"),
                    discord.SelectOption(label="📅 - Calendar & Intro", value="calendar", description="Get all 'Calendar & Intro' commands"),
                ]
                route_fn = lambda cat: self.help2(ctx, category=cat)
            else:
                options = [
                    discord.SelectOption(label="🏗️ - Setup", value="setup", description="Get all 'Setup' commands"),
                    discord.SelectOption(label="👟 - Moving", value="moving", description="Get all 'Moving' commands"),
                    discord.SelectOption(label="🏡 - Home", value="home", description="Get all 'Home' commands"),
                    discord.SelectOption(label="🔓 - Houses and PCs handling", value="handling", description="Get all 'Handling' commands"),
                    discord.SelectOption(label="📜 - Infos", value="infos", description="Get all 'Infos' commands"),
                    discord.SelectOption(label="🎟️ - Presets", value="presets", description="Get all 'Presets' commands"),
                    discord.SelectOption(label="🗳️ - Voting", value="voting", description="Get all 'Voting' commands"),
                    discord.SelectOption(label="👉 - Nominations", value="nominations", description="Get all 'Nominations' commands"),
                    discord.SelectOption(label="📄 - Lists", value="lists", description="Get all 'Lists' commands"),
                    discord.SelectOption(label="↪ - Send Role", value="sendrole", description="Get all 'Send Role' commands"),
                    discord.SelectOption(label="⚙️ - Utility", value="utility", description="Get all 'Utility' commands"),
                    discord.SelectOption(label="👽 - Other", value="other", description="Get all 'Other' commands"),
                ]
                route_fn = lambda cat: self.help(ctx, category=cat)
        else:
            route_fn = lambda cat: self.help2(ctx, category=cat)
        select = Select(
            placeholder="Choose an option",
            options=options,
        )
        view = View()
        view.add_item(select)
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message(embed=embed, view=view)
            message = await ctx.original_response()
        else:
            message = await ctx.send(embed=embed, view=view)
        async def callback(interaction):
            if interaction.message.id == message.id:
                await message.delete()
                category = interaction.data["values"][0]
                await route_fn(category)
        select.callback = callback

    async def help_homepage(self, ctx):
        embedh = discord.Embed(title="Village Game - Commands list", color=0xff3fb9)
        embedh.add_field(name="🏗️ - Setup", value="19 Commands\n`.help setup`", inline=True)
        embedh.add_field(name="👟 - Moving", value="9 Commands\n`.help moving`", inline=True)
        embedh.add_field(name="🏡 - Home", value="12 Commands\n`.help home`", inline=True)
        embedh.add_field(name="🔓 - Houses and PCs handling", value="14 Commands\n`.help handling`", inline=True)
        embedh.add_field(name="📜 - Infos", value="4 Commands\n`.help infos`", inline=True)
        embedh.add_field(name="🎟️ - Presets", value="3 Commands\n`.help presets`", inline=True)
        embedh.add_field(name="🗳️ - Voting", value="7 Commands\n`.help voting`", inline=True)
        embedh.add_field(name="👉 - Nominations", value="10 Commands\n`.help nominations`", inline=True)
        embedh.add_field(name="📄 - Lists", value="8 Commands\n`.help lists`", inline=True)
        embedh.add_field(name="↪ - Send Role", value="2 Commands\n`.help sendrole`", inline=True)
        embedh.add_field(name="⚙️ - Utility", value="20 Commands\n`.help utility`", inline=True)
        embedh.add_field(name="👽 - Other", value="17 Commands\n`.help other`", inline=True)
        embedh.set_footer(text="Village Game • You can also use `.help {category}` to select the category")
        await self.send_help_page(ctx, embedh, self.help_homepage)

    async def help_setup(self, ctx):
        embeds = discord.Embed(title="🏗️ - Setup commands", description="19 Commands", color=0xff3fb9)
        embeds.add_field(name=" ", value="**setup {Number Of Players}** • Setup Roles, Channels and Categories\n**roleset {Role To Set} {@Role}** • Set Roles in order to make the bot work\n**channelset {Channel To Set} {#Channel}** • Set Channels in order to make the bot work\n**categoryset {Category To Set} {Category Name}** • Set Categories in order to make the bot work\n**houseprefix {Prefix}** • Set Houses Prefix in order to make the bot work\n**knockduration {Time In Seconds}** • Set the duration of the knock", inline=False)
        embeds.add_field(name="🏗️ - Setup commands (Continue1)", value="**showwhispersender True/False** • Show/Hide whisper sender\n**ajifempty True/False** • AutoJoin on knock if the House is empty\n**ajknockexpire True/False** • AutoJoin when knock expires\n**maxpinh {Number}** • Max Players inside a house (high number for no limits)\n**refuseresponse 1/2/3** • Response when knock gets refused, 1=Reveal all players inside the house, 2=Reveal number of players inside the house, 3=No info\n**settings** • See current settings\n**resetdb** • Reset all Setup settings", inline=False)
        embeds.add_field(name="🏗️ - Setup commands (Continue2)", value="**deadcount True/False** • Deads count inside the house for AutoJoin and MaxPlayers conditions\n**altcount True/False** • Alts count inside the house for AutoJoin and MaxPlayers conditions\n**showdeadsonrefuse True/False** • Show deads between players/the number of players inside the house on knock refuse\n**showaltsonrefuse True/False** • Show alts between players/the number of players on knock refuse\n**candeadsinteract True/False** • Can deads open/refuse a knock\n**canaltsinteract True/False** • Can alts open/refuse a knock.")
        embeds.add_field(name="🏗️ - Setup commands (Continue3)", value="If you want the bot to auto manage Fireworks, Whispers and Moving in, set the following replies when items get used on UnbelievaBot with the command !edititem reply (item) (reply)\nFireworks reply = fireworks\nWhisper reply = whisper\nMove in reply = move in", inline=False)
        embeds.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embeds, self.help_setup)

    async def help_moving(self, ctx):
        embedm = discord.Embed(title="👟 - Moving commands", description='All commands can be executed in Stealth by adding "stealth" after the command. There wont be Joining and Leaving narrations. Additionally add, pcadd, move, renmove commands can be executed so that they give Read Only permisions by adding "read" after the command', color=0xff3fb9)
        embedm.add_field(name=" ", value="**move {House Number}** • Use it in RoleChats, move the player in the specified house removing them from any other house they're currently in\n**renmove {#HouseName}** • 'move' command but for renamed houses\n**knock {House Number}** • Use it in RoleChats, it will knock inside the specified house and gives 3 options to users inside the house:\n- If they type 'open' replying to the knock message, the knocking player will join the house leaving any other house they're currently in\n- If they type 'refuse' replying to the knock message, the knocking player will receive the name of all players and alts inside the house\n- If noone opens the door before the knock expires, it will be cancelled and a message notifying OverSeers will be sent inside the knocking player's RoleChat\n**renknock {#HouseName}** • 'knock' command for renamed houses", inline=False)
        embedm.add_field(name="👟 - Moving commands (Continue)", value="**add {House Number}** • Use it in RoleChats, add the player to the house you specify\n**remove {House Number}** • Use it in RoleChats, remove the player from the house you specify\n**pcadd {#PCName}** • 'add' command but for renamed houses or private channels\n**pcremove {#PCName}** • 'remove' command but for renamed houses or private channels\n**addhere #RoleChat** • Add the player of the specified Rolechat inside the channel you send the command to", inline=False)
        embedm.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedm, self.help_moving)

    async def help_home(self, ctx):
        embedh = discord.Embed(title="🏡 - Home commands", description="12 commands", color=0xff3fb9)
        embedh.add_field(name=" ", value="**home** • Bring the player home\n**home initialize** • Assign a random RoleChat and House to all players(only alive)\n**home setup** • Once all Sponsors are in RoleChat with their player (Alive) and all players have a home, use this command to put all Sponsors in the same House where their player is and set that house as their home\n**home set {@Player} {#HomeName}** • Set a player home\n**home mset** • Automatically set every player current location as their home\n**home list** • Get a list of players homes\n**home delete {@Player}** • Make a Player homeless\n**home return** • Bring all Players home\n**rolechat initialize** • Same as home initialize but doesn't assign houses, only RoleChats\n**rolechat check** • Get a list of all current rolechats and their player\n**owner** • Get a house owners' list", inline=False)
        embedh.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedh, self.help_home)

    async def help_handling(self, ctx):
        embedhan = discord.Embed(title="🔓 - Houses and PCs handling", description="14 commands", color=0xff3fb9)
        embedhan.add_field(name="Houses", value="**destroy {#HouseName}** • Move the House in inaccessible houses category, remove everyone from the house, send narration in announcements with explosion gif and narration in map channel\n**decay {#HouseName}** • Move the House in inaccessible houses category and send narration in map\n**rebuild {#HouseName}** • Rebuild the House sending narration in announcements and map\n**setowner {#PC} {#RC}** • Can also send it in RC. Set a Player the onwer of a PC (read next command)\n**end {#PC}** • Make everybody leave the channel except the setted owner", inline=False)
        embedhan.add_field(name="PCs & Maps", value="**newpc {Public/Private} {Name} {#RoleChannel}** • Generate a Chat in Public/Private Channels category. Players of the specified RoleChats will be added in there\n**close {#PCName}** • Move the Chat in Old PCS category, remove everyone from the chat\n**public {#Channel}** • Make the Channel public\n**private {#Channel}** • Make the Channel private\n**channels** • Generate a visual map of all Public and Private Channels\n**publicmap** • Generate a visual map of only Public Channels\n**privatemap** • Generate a visual map of only Private Channels\n**estatehelp** • Displays help for all Estate and Neighborhood map functions\n**estate {init} {#channel}** • Initialize the dynamic estate map in a channel, or force an update", inline=False)
        embedhan.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedhan, self.help_handling)

    async def help_infos(self, ctx):
        embedinf = discord.Embed(title="📜 - Infos", description="4 commands", color=0xff3fb9)
        embedinf.add_field(name=" ", value="**info {#Channel}** • Show the Channel infos\n**info add {#Channel} {info}** • Add an info to a Channel\n**info remove {#Channel} {info number}** • Remove an info from a Channel\n**info reset** • Reset all infos", inline=False)
        embedinf.set_footer(text="Village Game • All listed commands need the prefix . to work")
        await self.send_help_page(ctx, embedinf, self.help_infos)

    async def help_presets(self, ctx):
        embedpres = discord.Embed(title="🎟️ - Presets", description="3 commands", color=0xff3fb9)
        embedpres.add_field(name=" ", value="**preset** • For players and their Sponsors, it gives a menu with buttons to add, remove or edit a preset\n**ospreset** • For Administrators (OS), it gives a menu with buttons to edit the presets order so during the start of the phase you can read the presets in chronological order, remove a preset or reset all presets\n**prioritylist** • Shows the priority list for day/night phases", inline=False)
        embedpres.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedpres, self.help_presets)

    async def help_voting(self, ctx):
        embedv = discord.Embed(title="🗳️ - Voting commands", description="8 commands", color=0xff3fb9)
        embedv.add_field(name=" ", value="**vote {@Player}** • Vote or change your vote\n**abstain** • Abstain from the votation\n**manipulate {@Player to manipulate} {@Player to vote}** • Manipulate a Player into voting another Player\n**removevote {@Player}** • Remove a Player vote\n**votelist** • Show all the votes\n**resetvotes** • Reset all votes\n**votehistory/vh [mode]** • Reply to a start message to scan votes. `mode`: `grouped` (group by target) / `range` (prompts for end message)", inline=False)
        embedv.add_field(name="🗳️ - Voting commands (Continue)", value="**voteinrc true/false** • Set voting in RoleChats on true or false\nEnabling this option, players will be able to vote only in their RoleChats. Don't delete voting channels, players need them to specify what type of vote they are casting by putting the channel mention (ex. #lynch-session-1) at the end of the vote command (#lynch-session-1 is on default if no channel is specified). Same thing applies for every other command. If you don't want vote count to be displayed, delete the voe count channel. You will be able to check votes with .votelist and if you also don't want players to be able to use .votelist command, contact Bidet, he will enable the command only of OS.")
        embedv.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedv, self.help_voting)

    async def help_nominations(self, ctx):
        embedn = discord.Embed(title="👉 - Nominations commands", description="10 commands", color=0xff3fb9)
        embedn.add_field(name="How to setup:", value="Create a new category (for Nominations) and name it as you wish.\nUse the command\n.categoryset Nominations {name of the category you created}\nThat's all! Your server is ready to use nominations!")
        embedn.add_field(name="List of commands:", value="**accuse {@AccusedMention} {#AccuserRC}** • Can be used in RoleChats, Players can use it too. It will remove 2 tokens from the tokens bal and create a TextChannel for the nomination\n**intervene {#NominationChannel}** • Pay one token to send a message inside a #NominationChannel\n**voten {#NominationChannel} yes/no** • Vote guilty (yes) or not guilty (no) for an ongoing Nomination\n**tokens** • Get your tokens bal\n**addtokens {everyone/@Player} {Quantity}** • Add tokens to someone balance\n**removetokens {everyone/@Player} {Quantity}** • Remove tokens from someone balance\n**showvotesn {#NominationChannel}** • Get the list of votes for the specified Nomination\n**stopvotes {#NominationChannel}** • Stop a nomination. Accuser and Accused will also not be able to talk anymore inside the NominationChannel\n**resumevotes {NominationChannel}** • Resume a nomination\n**clearvotes** • Clear all nomination votes", inline=False)
        embedn.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedn, self.help_nominations)

    async def help_lists(self, ctx):
        embedu = discord.Embed(title="📄 - Lists", description="8 commands", color=0xff3fb9)
        embedu.add_field(name=" ", value="**playerlist** • Get a list of Alive members\n**houselist** • Get a list of visitable houses\n**setuphouselist** • Setup the houselist with the current existing houses\n**houselistadd {#House}** • Add #House to the houselist\n**houselistremove {#House}** • Remove #House from the houselist\n**deadlist** • Get a list of dead Players and their roles\n**deadlist add {Player} {Team} {Role Name}** • Add Player to the deadlist with the specified team and role\n**deadlist remove {Player}** • Remove Player from the deadlist", inline=False)
        embedu.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedu, self.help_lists)

    async def help_sendrole(self, ctx):
        embedsendrole = discord.Embed(title="↪ - Send Role", description="3 commands", color=0xff3fb9)
        embedsendrole.add_field(name=" ", value="**settarget <target_channel_id>** • Set the channel where you want the role to be sent to by sending its ID (not its mention).\n**sendrole/sr <Player/s>** • Reply to a message, the bot will send it inside the setted channel with the previous command. If <Player/s> is specified, the bot will send the text 'Played by <Player/s>' at the end of the role message.", inline=False)
        embedsendrole.add_field(name="🎲 - Team Roll", value="**teamroll <n1> \"msg1\" <n2> \"msg2\" ...** • Admin only. Randomly assigns one of the quoted messages to each of `n` role channels (total must match existing channels in the RC category; missing channels are auto-created up to 50). Example: `.teamroll 3 \"Evil team\" 3 \"Village team\"`", inline=False)
        embedsendrole.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedsendrole, self.help_sendrole)

    async def help_utility(self, ctx):
        embedu = discord.Embed(title="⚙️ - Utility", description="20 commands", color=0xff3fb9)
        embedu.add_field(name=" ", value="**day** • Unlock all Day Channels\n**night** • Lock all Day Channels\n**broom** • Delete replied-to messages (except pinned), log to log channel and RCs\n**log** • Log message range. Use count/source/send-to options\n**whisper {#Receiver RC Mention} {Message}** • Send a whisper\n**dead** • Player leaves current channels, RC moves to Dead category\n**deadrole** • Mark player dead, remove house access, pin corpse in chosen house, prompt for deadlist details\n**addrole {@Role} {@User1/everyone} {@User2}...** • Give all mentioned members the specified Role\n**switch** • Switch between Player and Sponsor roles\n**deadc** • Move a RoleChat to dead category and remove house access (admin only)\n**removerole {role} {member}** • Remove a role from a member (admin only)\n**skipnight {min_votes}** • Start a vote to skip the night phase (OS/admin only)", inline=False)
        embedu.add_field(name="⚙️ - Utility commands (Continue)", value="**addcategoryperms {@Role} {CategoryName} {Permission}** • Add the specified perms to all channels in the specified category for the specified role.\n**addchannelperms {@Role} {#TextChannel} {Permission}** • Add the specified perms to the specified channel for the specified role.\n**R =** Read Messages\n**S =** Read and Send Messages\n**endgame** • Use it when the game ends. The bot will unlock all channls except OS channels for everyone to read and send messages inside them\n**statss** • Show message counts for the day discussion channel grouped by role priority\n**setmessagetracking {true/false}** • Enable or disable message tracking (admin only)\n**start_tracking** • Start message tracking (admin only)\n**stop_tracking** • Stop/pause message tracking (admin only)\n**reset_tracking** • Reset message counts for this server (admin only)")
        embedu.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedu, self.help_utility)

    async def help_other(self, ctx):
        embedo = discord.Embed(title="👽 - Other", description="17 commands", color=0xff3fb9)
        embedo.add_field(name=" ", value="**help** • Get a list of all aviable commands\n**ghelp** • Show general Gentleman Help overview\n**who {#Channel}** • Get a list of players inside the channel\n**where #RoleChat** • Get a list of where the player is\n**map** • Get the map pic (It has to be the first pinned message in map channel)\n**role/firstpinned** • Make your role the first pinned message in your RC to have easy access to it through this command\n**roll {@Role} {Number}** • Get a list of random players with the specified Role\n**narrate {#Channels} {Message}** • Send the narration in specified Channels, if None specified it will be sent in all RoleChats. Watch out, the narration will be sent into any Channel mention inside the command\n**deletechannel** • Delete the text channel\n**deletecategory** • Delete the category\n**timestamp {YYYY-MM-DD HH:MM:SS}** • Generate a timestamp\n**time** • Reply to a message, get the exact time it was sent\n**ping** • Check if the bot is online", inline=False)
        embedo.add_field(name="👽 - Other commands (Continue)", value=            "**dice {N}** • Roll 1–N\n**dice {option1} {option2} ...** • Pick one randomly\n**loc** • Get a list of all houses and current players inside of them\n**gettag {Message Link}** • Can also be used replying to a message, it sends the list of mentioned users inside the specified message\n**timer {time} <tag> {#channel}** • Set a timer in hhmmss format (1h2m10s). Type 'tag' if you want it to mention you when the time is up.\n**dropitem** • Drop an interactive item with count and expiration. Use: `.dropitem #house #logs \"Name\" \"Desc\" <count> <showpickups t/f> [duration]`", inline=False)
        embedo.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedo, self.help_other)

    async def help_meetupmatrix(self, ctx):
        embedm = discord.Embed(title="📊 - Meetings & Meetup Matrix", description="21 commands", color=0xff3fb9)
        embedm.add_field(name="📊 - Meetup Matrix", value="**setupmeetupmatrix** • Admin only. Toggle automated meetup tracking for this server. Requires confirmation.\n**setphase {day/night}** • Admin only. Manually trigger a phase change and bootstrap meetups.\n**forcemeet {@Player1} {@Player2}** • Admin only. Force a meetup recording between two players.\n**allmeets {@Player}** • Show all players the specified member has met during the current phase. Grouped by role.\n**meetupmatrix** • Show the full meetup matrix for the current phase, listing everyone who has met.", inline=False)
        embedm.add_field(name="🤝 - Meeting Commands (1/2)", value="**meeting** • Request a meeting with other players (max 5)\n**endmeeting** • End your active meeting\n**meetingenable** • Enable or disable the meeting system (admin only)\n**setmeetingchannel {#channel}** • Set channel for `.meeting` requests (admin only)\n**setmeetingtargetguild {guild_id}** • Set server where meeting channels are created (admin only)\n**setmeetingcategory {category}** • Set category for new meeting channels (admin only)\n**meetingconfig** • Show current meeting configuration (admin only)\n**blockmeeting {@user}** • Block a user from using meeting commands (admin only)", inline=False)
        embedm.add_field(name="🤝 - Meeting Commands (2/2)", value="**unblockmeeting {@user}** • Unblock a user from using meeting commands (admin only)\n**removecooldown {@user}** • Remove meeting cooldown from a user (admin only)\n**checkcooldown {@user}** • Check meeting cooldown for yourself or another user\n**forcemeeting {@user1} {@user2} ...** • Create a forced meeting without voting (admin only)\n**listblocked** • Show the list of blocked users (admin only)\n**listcooldowns** • Show all users currently on meeting cooldown (admin only)\n**cancelmeeting** • Cancel a pending meeting (admin only)\n**meetingstats** • Show meeting statistics (admin only)", inline=False)
        embedm.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedm, self.help_meetupmatrix)

    async def help_economy(self, ctx):
        embede = discord.Embed(title="💰 - Economy commands", description="18 commands", color=0xff3fb9)
        embede.add_field(name="Player Commands", value=(
            "**`.bal` / `.balance`** • Show your rolechat's balance\n"
            "**`.shop`** • View the server shop with interactive buy/edit buttons\n"
            "**`.buy <item> [qty]`** • Buy an item from the shop (adds to rolechat inventory)\n"
            "**`.sell-item` / `.sell` <item>** • Sell an item from your user inventory for 50% refund\n"
            "**`.inv` / `.inventory` [#channel]** • View rolechat inventory\n"
            "**`.give @user <amount>`** • Give coins from your rolechat to another player's rolechat (use in Houses)\n"
            "**`.give-money @user <amount>`** • Transfer coins from your personal wallet to another user\n"
            "**`.use <item>`** • Use an item from your user inventory (Fireworks, Whisper, Broom, Will)\n"
        ), inline=False)
        embede.add_field(name="Admin Commands", value=(
            "**`.additem <price> <name>`** • Add a new item to the shop\n"
            "**`.edititem <field> <name> <value>`** • Edit an item's price/name/description\n"
            "**`.delitem <name>`** • Remove an item from the shop\n"
            "**`.addmoney #channel <amount>`** • Add coins to a rolechat's balance\n"
            "**`.removemoney #channel <amount>`** • Remove coins from a rolechat's balance\n"
            "**`.add-money-role @role <amount>`** • Add coins to all members with a role (wallet)\n"
            "**`.additemrole @role <item> <qty>, <item2> <qty2>`** • Give items to all members with a role\n"
            "**`.reseteconomy [amount]`** • Reset all alive players' money to a set amount (default 0)\n"
            "**`.clearinventory`** • Clear all alive players' inventories\n"
            "**`.collect`** • Add the collect amount to every rolechat\n"
            "**`.setcollect <value>`** • Set the amount added by `.collect` (max 10,000)\n"
            "**`.leaderboard` / `.lb` / `.top` [top]** • Show richest rolechats by balance\n"
        ), inline=False)
        embede.add_field(name="Shop Items", value=(
            "🎆 **Fireworks** — Reveal your position in announcements\n"
            "👟 **Shoes** — Extra visit grant\n"
            "✉ **Whisper** — Send an anonymous private message\n"
            "🧹 **Broom** — Clear recent messages in a channel\n"
            "📜 **Will** — Notify Overseers to pin your last will\n"
        ), inline=False)
        embede.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embede, self.help_economy)

    async def help_location(self, ctx):
        embed = discord.Embed(title="📍 Location commands", description="17 commands", color=0xff3fb9)
        embed.add_field(name="User Commands", value="**`.mysetloc <location>`** • Set your own location\n**`.myremoveloc`** • Remove your own location\n**`.localtime` / `.lt` [@user]** • View a user's local time\n**`.near [@user]** • Find the 5 closest members to you or another user\n**`.locations`** • Browse all locations by continent\n**`.locstats`** • Show location statistics\n**`.lochelp` / `.hloc`** • Show all location commands", inline=False)
        embed.add_field(name="Admin Commands", value="**`.setloc @user <location>`** • Set a user's location\n**`.remloc <@user/username>`** • Remove a user's location\n**`.setcontinent @user <continent>`** • Manually assign a continent\n**`.listunknown`** • List entries with Unknown continent\n**`.refreshtz`** • Refresh timezones for all saved users\n**`.forceremloc` / `.forceremoveloc <name/id>`** • Force remove a location entry\n**`.test_geocoder`** • Test geocoder connectivity", inline=False)
        embed.add_field(name="Maps", value="**`.mapp`** • View the world map of registered users\n**`.mapheat`** • View the heatmap of registered users\n**`.locsnotset`** • Show members who haven't set their location", inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_location)

    async def help_dashboard(self, ctx):
        embed = discord.Embed(title="🎮 Dashboard & OS Info commands", description="17 commands", color=0xff3fb9)
        embed.add_field(name="Dashboard", value="**`.dashboard`** • Open the role dashboard\n**`.dashboardtoggle`** • Enable/disable the dashboard\n**`.setrole @role`** • Set the role for the dashboard\n**`.addpassiveability <name> <desc>`** • Add a passive ability\n**`.removepassiveability <name>`** • Remove a passive ability\n**`.addactiveability <name> <desc> <uses>`** • Add an active ability\n**`.removeactiveability <name>`** • Remove an active ability\n**`.vb`** • View your vote balance\n**`.checkvb [@user]`** • Check vote balance for yourself or another\n**`.setvisits @user <amount>`** • Set a user's visit count\n**`.addvisits @user <amount>`** • Add visits to a user\n**`.removevisits @user <amount>`** • Remove visits from a user\n**`.actionlog [@user]`** • View action log for a user", inline=False)
        embed.add_field(name="OS Info", value="**`.setboard`** • Set up the OS info board\n**`.setinfophase <phase>`** • Set the current phase info\n**`.addcard`** • Add an info card\n**`.refreshcards`** • Refresh all info cards", inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_dashboard)

    async def help_gamemanager(self, ctx):
        embed = discord.Embed(title="🎲 Game Manager commands", description="4 commands", color=0xff3fb9)
        embed.add_field(name="Commands", value="**`.startgame` / `.sg` <slots> @host [-role <name>] <name>** • Start a new game lobby\n**`.addplayer` / `.ap` <slot> @player [name]** • Add a player to an empty slot\n**`.removeplayer` / `.rp` <slot> [name]** • Remove a player from a slot\n**`.closegame` / `.cg` [name]** • Close and archive the current game", inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_gamemanager)

    async def help_library(self, ctx):
        embed = discord.Embed(title="📚 Library & Stats commands", description="19 commands", color=0xff3fb9)
        embed.add_field(name="Stats", value="**`.stats` / `.stats @player`** • View player statistics\n**`.winrate`** • Show winrate stats by team\n**`.relations`** [@user] • Show allies and nemeses", inline=False)
        embed.add_field(name="Library", value="**`.lib`** • Browse the game library\n**`.lib add`** • Add a new game to the library\n**`.lib summary`** • Show a summary of all games\n**`.lib edit <game#> <field> <value>`** • Edit a game's field\n**`.lib delete <game#>`** • Delete a game\n**`.lib deletegame <game#>`** • Delete a game\n**`.lib setwin <game#> <team>`** • Manually set the winning team\n**`.lib search <term>`** • Search games by name or player\n**`.lib idsearch <id>`** • Search game by ID\n**`.lib migrateaccount`** • Move stats to a new account\n**`.lib mergeaccount`** • Merge two accounts' stats\n**`.lib syncname`** • Sync display name for stats\n**`.lib bulksyncnames`** • Bulk sync all display names\n**`.lib help`** • Show library help\n**`.libit help`** • Show Italian library help\n**`.missingids`** • List games with missing player IDs", inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_library)

    async def help_games(self, ctx):
        embed = discord.Embed(title="⚔️ Games (Aux Battle & Senet)", description="18 commands", color=0xff3fb9)
        embed.add_field(name="🎯 Aux Battle", value="**`.auxbattle` / `.aux`** • Main aux battle command\n**`.help_aux`** • Show detailed aux battle help\n**`.auxbattle signup`** • Sign up for the battle\n**`.auxbattle opensignup`** • Open signups (admin)\n**`.auxbattle closesignup`** • Close signups (admin)\n**`.auxbattle bracket`** • View the bracket\n**`.auxbattle reset`** • Reset the tournament (admin)\n**`.auxbattle start`** • Start the tournament (admin)\n**`.auxbattle submit`** • Submit your battle entry", inline=False)
        embed.add_field(name="🎲 Senet", value="**`.senet help`** • Show Senet help\n**`.senet challenge` / `.senet sfida @user`** • Challenge someone\n**`.senet accept` / `.senet accetta @user`** • Accept a challenge\n**`.senet roll` / `.senet lancia`** • Roll the dice\n**`.senet move` / `.senet muovi <piece>`** • Move a piece\n**`.senet skip` / `.senet passo`** • Skip your turn\n**`.senet status` / `.senet board`** • View the board\n**`.senet forfeit` / `.senet abbandona`** • Forfeit the game\n**`.senet rules` / `.senet regole`** • Show the rules", inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_games)

    async def help_birthdays(self, ctx):
        embed = discord.Embed(title="🎂 Birthday commands", description="6 commands", color=0xff3fb9)
        embed.add_field(name="Commands", value="**`.birthday <DD-MM>`** • Set your birthday\n**`.bdaystatus`** • Check your birthday status\n**`.testbday`** • Test birthday announcement (admin)\n**`.nextbirthdays`** • Show upcoming birthdays\n**`.birthdays`** • List all registered birthdays\n**`.helpbday`** • Show birthday help", inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_birthdays)

    async def help_calendar(self, ctx):
        embed = discord.Embed(title="📅 Calendar & Intro commands", description="4 commands", color=0xff3fb9)
        embed.add_field(name="Commands", value="**`.calendar`** • Show the English Village Games calendar/schedule\n**`.calendario`** • Show the Italian Village Games calendar/schedule\n**`.vgintro` / `.vgi`** • Show the Village Games introduction\n**`.vgintro_it` / `.vgii`** • Show the Village Games introduction (Italian)", inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_calendar)