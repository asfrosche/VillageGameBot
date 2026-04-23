import discord
import asyncio
import datetime
from datetime import datetime
from discord.ext import commands
from discord.ui import Button, View
from cogs.data_utils import load_guild_data, save_guild_data, base_variables

class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Auto setup
    @commands.command()
    async def setup(self, ctx, num_channels: int):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                overseer_role_name = guild_data.get("overseer_role_name")
                alive_role_name = guild_data.get("alive_role_name")
                sponsor_role_name = guild_data.get("sponsor_role_name")
                spectator_role_name = guild_data.get("spectator_role_name")
                dead_role_name = guild_data.get("dead_role_name")
                alt_role_name = guild_data.get("alt_role_name")
                log_channel_name = guild_data.get("log_channel_name")
                actions_log_channel_name = guild_data.get("actions_log_channel_name")
                join_and_leave_logs_name = guild_data.get("join_and_leave_logs")
                editdel_channel_name = guild_data.get("edit_del_logs")
                whisper_logs_channel_name = guild_data.get("whisper_logs_channel_name")
                announcements_channel_name = guild_data.get("announcements_channel_name")
                map_channel_name = guild_data.get("map_channel_name")
                daydiscussion_channel_name = guild_data.get("daydiscussion_channel_name")
                megaphone_channel_name = guild_data.get("megaphone_channel_name")
                lynch_channel_name1 = guild_data.get("lynch_channel_name1")
                lynch_channel_name2 = guild_data.get("lynch_channel_name2")
                leader_channel_name = guild_data.get("leader_channel_name")
                vote_count_name = guild_data.get("vote_count_name")
                house_prefix = guild_data.get("house_prefix")
                overseer_category_name = guild_data.get("overseer_category_name")
                atg_category_name = guild_data.get("atg_category_name")
                chats_category_name = guild_data.get("chats_category_name")
                os_relations_category_name = guild_data.get("os_relations_category_name")
                daychat_category_name = guild_data.get("daychat_category_name")
                publc_category_name = guild_data.get("publc_category_name")
                privc_category_name = guild_data.get("privc_category_name")
                houses_category_name = guild_data.get("houses_category_name")
                rc_category_name = guild_data.get("rc_category_name")
                alt_category_name = guild_data.get("alt_category_name")
                dead_rc_category_name = guild_data.get("dead_rc_category_name")
                inaccessible_houses_category_name = guild_data.get("inaccessible_houses_category_name")
                old_pcs_category_name = guild_data.get("old_pcs_category_name")
                await ctx.guild.create_role(name=overseer_role_name, permissions=discord.Permissions(administrator=True), color=discord.Color.from_rgb(0, 0, 255), mentionable=True)
                await ctx.guild.create_role(name=alt_role_name, color=discord.Color.from_rgb(0, 0, 1))
                await ctx.guild.create_role(name=alive_role_name, color=discord.Color.from_rgb(0, 218, 233))
                await ctx.guild.create_role(name=sponsor_role_name, color=discord.Color.from_rgb(0, 235, 41))
                await ctx.guild.create_role(name=spectator_role_name, color=discord.Color.from_rgb(255, 158, 0))
                await ctx.guild.create_role(name=dead_role_name, color=discord.Color.from_rgb(240, 0, 4))
                overseer_role = discord.utils.get(ctx.guild.roles, name=overseer_role_name)
                await ctx.author.add_roles(overseer_role)
                alive_role = discord.utils.get(ctx.guild.roles, name=alive_role_name)
                sponsor_role = discord.utils.get(ctx.guild.roles, name=sponsor_role_name)
                spectator_role = discord.utils.get(ctx.guild.roles, name=spectator_role_name)
                dead_role = discord.utils.get(ctx.guild.roles, name=dead_role_name)
                alt_role = discord.utils.get(ctx.guild.roles, name=alt_role_name)
                overseer_category = await ctx.guild.create_category(name=overseer_category_name)
                atg_category = await ctx.guild.create_category(name=atg_category_name)
                chats_category = await ctx.guild.create_category(name=chats_category_name)
                os_relations_category = await ctx.guild.create_category(name=os_relations_category_name)
                daychat_category = await ctx.guild.create_category(name=daychat_category_name)
                publc_category = await ctx.guild.create_category(name=publc_category_name)
                privc_category = await ctx.guild.create_category(name=privc_category_name)
                houses_category = await ctx.guild.create_category(name=houses_category_name)
                roles_category = await ctx.guild.create_category(name=rc_category_name)
                alt_category = await ctx.guild.create_category(name=alt_category_name)
                dead_rc_category = await ctx.guild.create_category(name=dead_rc_category_name)
                inaccessible_houses_category = await ctx.guild.create_category(name=inaccessible_houses_category_name)
                old_pcs_category = await ctx.guild.create_category(name=old_pcs_category_name)
                os_disc_channel = await ctx.guild.create_text_channel(name="overseer-discussion")
                await overseer_category.set_permissions(ctx.guild.default_role, read_messages=False)
                await atg_category.set_permissions(ctx.guild.default_role, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False)
                await atg_category.set_permissions(alt_role, read_messages=False)
                await chats_category.set_permissions(ctx.guild.default_role, read_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False)
                await chats_category.set_permissions(spectator_role, read_messages=True, send_messages=False)
                await os_relations_category.set_permissions(ctx.guild.default_role, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False)
                await os_relations_category.set_permissions(alt_role, read_messages=False)
                await daychat_category.set_permissions(ctx.guild.default_role, read_messages=True, send_messages=False, manage_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False)
                await daychat_category.set_permissions(alive_role, read_messages=True)
                await daychat_category.set_permissions(sponsor_role, read_messages=True)
                await daychat_category.set_permissions(dead_role, read_messages=True, add_reactions=False)
                await daychat_category.set_permissions(spectator_role, read_messages=True, add_reactions=False)
                await daychat_category.set_permissions(alt_role, read_messages=False)
                await publc_category.set_permissions(ctx.guild.default_role, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False, add_reactions=False)
                await publc_category.set_permissions(alive_role, read_messages=True)
                await publc_category.set_permissions(sponsor_role, read_messages=True)
                await publc_category.set_permissions(dead_role, read_messages=True)
                await publc_category.set_permissions(spectator_role, read_messages=True)
                await publc_category.set_permissions(alt_role, read_messages=False)
                await privc_category.set_permissions(ctx.guild.default_role, read_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False)
                await privc_category.set_permissions(spectator_role, read_messages=True, send_messages=False, add_reactions=False)
                await houses_category.set_permissions(ctx.guild.default_role, read_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False)
                await houses_category.set_permissions(spectator_role, read_messages=True, send_messages=False, add_reactions=False)
                await roles_category.set_permissions(ctx.guild.default_role, read_messages=False, manage_messages=True, mention_everyone=True, use_application_commands=False, use_embedded_activities=False)
                await roles_category.set_permissions(spectator_role, view_channel=True, send_messages=False, manage_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, add_reactions=False)
                await alt_category.set_permissions(ctx.guild.default_role, read_messages=False, mention_everyone=True, use_application_commands=False, use_embedded_activities=False)
                await alt_category.set_permissions(spectator_role, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, add_reactions=False)
                await dead_rc_category.set_permissions(ctx.guild.default_role, read_messages=False, use_application_commands=False, use_embedded_activities=False)
                await dead_rc_category.set_permissions(spectator_role, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, add_reactions=False)
                await inaccessible_houses_category.set_permissions(ctx.guild.default_role, read_messages=False, use_application_commands=False, use_embedded_activities=False)
                await inaccessible_houses_category.set_permissions(spectator_role, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False)
                await old_pcs_category.set_permissions(ctx.guild.default_role, read_messages=False, use_application_commands=False, use_embedded_activities=False)
                await old_pcs_category.set_permissions(spectator_role, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False)
                await os_disc_channel.set_permissions(ctx.guild.default_role, read_messages=False)
                await overseer_category.create_text_channel(name="notes")
                await overseer_category.create_text_channel(name=log_channel_name)
                await overseer_category.create_text_channel(name=actions_log_channel_name)
                await overseer_category.create_text_channel(name=whisper_logs_channel_name)
                await overseer_category.create_text_channel(name=editdel_channel_name)
                await overseer_category.create_text_channel(name='logs-economy')
                await overseer_category.create_text_channel(name=join_and_leave_logs_name)
                await overseer_category.create_text_channel(name='commands')
                highlights_channel = await overseer_category.create_text_channel(name='🌟│highlights')
                commentary_channel = await overseer_category.create_text_channel(name='✍️│commentary')
                await highlights_channel.set_permissions(spectator_role, read_messages=True, send_messages=False)
                await commentary_channel.set_permissions(spectator_role, read_messages=True, send_messages=False)
                rules_channel = await atg_category.create_text_channel(name='📜│rules')
                await rules_channel.send(f"1. You cannot copy-paste, screenshot, or share in a similar way that isn't your own words, anything related to private channels. You cannot pretend to be doing this either.\n2. Using code words or encrypted messages to plan during the day with only certain players is prohibited.\n3. You cannot share any kind of information with other players outside of the server. (No cheating or teaming)\n4. Avoid spamming, flooding the chat (talking too much throughout the day) or sending many images. If you talk about topics, or repeatedly send GIFs or images, not related to the game in day-discussion, you will be warned.\n5. You can only edit or delete messages that were just recently sent to correct a mistake. You cannot instantly delete or edit recent messages either, with the purpose of simulating this way a private chat with currently online players.\n6. If you misbehave: be toxic, racist, rude to other players, or stir up drama, the host and the bot will mute you. If you continuously misbehave, you could get banned. Persistent and rude comments won't be tolerated. Sending these messages to delete them right after won't work either.\n7. Homophobia, racism, sexism or any form of discrimination will face a zero-tolerance policy and will be met with a one strike rule. Extreme toxicity or harassments will also be met with the same policy.\n8. If you make anyone feel uncomfortable you will be warned. If you continue, you'll be timed out, then kicked if necessary.")
                await rules_channel.send(f"9. If you believe an {overseer_role.mention} being biased towards a player, or if you have any complaint, let **Aoren** (SV owner of Hearthside) know. If you believe anyone is breaking a rule, feel free to ping {overseer_role.mention} as well, or reach out to us in DM.\n10. Metagaming is heavily discouraged. It is your responsibility to keep it out of the game to ensure fairness for you and other players, and we recommend to not make use of it outside of your role channel.\n11. Using curses, threats, reporting, flaming or ethical suicide as a defense or excuse is unacceptable and is beyond the purpose of this game.\n12. Any sorts of outside tools such as DM, bots, plugins, etc. that can give you information you shouldn't have, are strictly prohibited. Failure to follow these rules will lead to restriction or removal from the game..\n13. There a lot of unspoken rules that might not be listed here, at your own discretion.... use your common sense. If you know something is not allowed that is not listed as a rule, don't do it.\n14. Stay respectful.")
                await atg_category.create_text_channel(name='❓│mechanics')
                await atg_category.create_text_channel(name='💵│economy')
                await atg_category.create_text_channel(name='🃏│role-template')
                await atg_category.create_text_channel(name='📄│playerlist')
                offtopic_channel = await chats_category.create_text_channel(name='off-topic')
                await offtopic_channel.set_permissions(ctx.guild.default_role, read_messages=True, send_messages=True, use_application_commands=False, use_embedded_activities=False)
                await offtopic_channel.set_permissions(spectator_role, read_messages=True, send_messages=True)
                await offtopic_channel.set_permissions(alive_role, read_messages=True, send_messages=True)
                await offtopic_channel.set_permissions(sponsor_role, read_messages=True, send_messages=True)
                await offtopic_channel.set_permissions(dead_role, read_messages=True, send_messages=True)
                await offtopic_channel.set_permissions(alt_role, read_messages=False)
                spectator_channel = await chats_category.create_text_channel(name='📺│spectator-lounge')
                graveyard_channel = await chats_category.create_text_channel(name='💀│graveyard')
                feedback_channel = await chats_category.create_text_channel(name='feedback')
                await spectator_channel.set_permissions(spectator_role, read_messages=True, send_messages=True)
                await graveyard_channel.set_permissions(dead_role, read_messages=True, send_messages=True)
                await feedback_channel.set_permissions(spectator_role, read_messages=True, send_messages=True)
                await os_relations_category.create_text_channel(name=announcements_channel_name)
                await os_relations_category.create_text_channel(name='💀│death-reports')
                await os_relations_category.create_text_channel(name='🔴│overseer-status')
                await os_relations_category.create_text_channel(name=map_channel_name)
                await daychat_category.create_text_channel(name=daydiscussion_channel_name)
                await daychat_category.create_text_channel(name=megaphone_channel_name)
                await daychat_category.create_text_channel(name=lynch_channel_name1)
                await daychat_category.create_text_channel(name=lynch_channel_name2)
                await daychat_category.create_text_channel(name=leader_channel_name)
                await daychat_category.create_text_channel(name=vote_count_name)
                await publc_category.create_text_channel(name='duplicate-this')
                await privc_category.create_text_channel(name='duplicate-this')
                for i in range(1, num_channels + 1):
                    await houses_category.create_text_channel(name=f"{house_prefix}{i}")
                for i in range(1, num_channels + 1):
                    await roles_category.create_text_channel(str(i))
                guild_data["houselist"] = []
                for i in range(1, num_channels+1):
                    house_name = f'{house_prefix}{i}'
                    guild_data["houselist"].append(house_name)
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.send('Setup completed')
            else:
                await ctx.send("Guild data not loaded")
        else:
            await ctx.send("You don't have enough perms to use this command")

    # Setup roles
    @commands.command()
    async def roleset(self, ctx, role: str = None, new_role: discord.Role = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if new_role:
                    new_role_name = new_role.name
                    if role.lower() == 'overseer':
                        guild_data['overseer_role_name'] = new_role_name
                    elif role.lower() == 'alive':
                        guild_data['alive_role_name'] = new_role_name
                    elif role.lower() == 'sponsor':
                        guild_data['sponsor_role_name'] = new_role_name
                    elif role.lower() == 'spectator':
                        guild_data['spectator_role_name'] = new_role_name
                    elif role.lower() == 'dead':
                        guild_data['dead_role_name'] = new_role_name
                    elif role.lower() == 'alt':
                        guild_data['alt_role_name'] = new_role_name
                    else:
                        await ctx.send(f'Invalid role name, choose between following:\n- Overseer\n- Alive\n- Sponsor\n- Spectator\n- Dead\n- Alt')
                        return
                    save_guild_data(ctx.guild.id, guild_data)
                    await ctx.send(f"{role.capitalize()} role set to {new_role_name}")
                else:
                    await ctx.send('Please provide a valid Role')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    # Setup channels
    @commands.command()
    async def channelset(self, ctx, channel: str, new_channel: discord.TextChannel = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                valid_channels = ['daydiscussion', 'megaphone', 'lynchsession1', 'lynchsession2', 'leaderelection', 'votecount', 'logchannel', 'actionslogchannel', 'announcements', 'map', 'whisperlogs', 'editdellogs', 'joinleavelogs']
                if new_channel is None:
                    new_channel = ctx.channel
                new_channel_name = new_channel.name
                if channel.lower() in valid_channels:
                    if channel.lower() == 'daydiscussion':
                        guild_data['daydiscussion_channel_name'] = new_channel_name
                    elif channel.lower() == 'megaphone':
                        guild_data['megaphone_channel_name'] = new_channel_name
                    elif channel.lower() == 'lynchsession1':
                        guild_data['lynch_channel_name1'] = new_channel_name
                    elif channel.lower() == 'lynchsession2':
                        guild_data['lynch_channel_name2'] = new_channel_name
                    elif channel.lower() == 'leaderelection':
                        guild_data['leader_channel_name'] = new_channel_name
                    elif channel.lower() == 'votecount':
                        guild_data['vote_count_name'] = new_channel_name
                    elif channel.lower() == 'logchannel':
                        guild_data['log_channel_name'] = new_channel_name
                    elif channel.lower() == 'actionslogchannel':
                        guild_data['actions_log_channel_name'] = new_channel_name
                    elif channel.lower() == 'announcements':
                        guild_data['announcements_channel_name'] = new_channel_name
                    elif channel.lower() == 'map':
                        guild_data['map_channel_name'] = new_channel_name
                    elif channel.lower() == 'whisperlogs':
                        guild_data['whisper_logs_channel_name'] = new_channel_name
                    elif channel.lower() == 'editdellogs':
                        guild_data['edit_del_logs'] = new_channel_name
                    elif channel.lower() == 'joinleavelogs':
                        guild_data['join_and_leave_logs'] = new_channel_name
                    save_guild_data(ctx.guild.id, guild_data)
                    await ctx.send(f"{channel.capitalize()} channel set to {new_channel_name}")
                else:
                    await ctx.send('Invalid type of channel. Try using the following arguments:\n- Announcements\n- Map\n- DayDiscussion\n- Megaphone\n- LynchSession1\n- LynchSession2\n- LeaderElection\n- VoteCount\n- LogChannel\n- ActionsLogChannel\n- WhisperLogs\n- EditDelLogs\n- JoinLeaveLogs')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    # Setup categories
    @commands.command()
    async def categoryset(self, ctx, category: str, *, new_category_name: str = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                valid_categories = ['publicchats', 'overseer', 'aboutthegame', 'chats', 'overseerrelations', 'daychat', 'privatechats', 'houses', 'rolechats', 'deads', 'alts', 'inaccessiblehouses', 'oldpcs', 'nominations']
                if new_category_name is None:
                    new_category = ctx.channel.category
                    new_category_name = new_category.name
                if category.lower() in valid_categories:
                    if category.lower() == 'publicchats':
                        guild_data['publc_category_name'] = new_category_name
                    elif category.lower() == 'overseer':
                        guild_data['overseer_category_name'] = new_category_name
                    elif category.lower() == 'aboutthegame':
                        guild_data['atg_category_name'] = new_category_name
                    elif category.lower() == 'chats':
                        guild_data['chats_category_name'] = new_category_name
                    elif category.lower() == 'overseerrelations':
                        guild_data['os_relations_category_name'] = new_category_name
                    elif category.lower() == 'daychat':
                        guild_data['daychat_category_name'] = new_category_name
                    elif category.lower() == 'privatechats':
                        guild_data['privc_category_name'] = new_category_name
                    elif category.lower() == 'houses':
                        guild_data['houses_category_name'] = new_category_name
                    elif category.lower() == 'rolechats':
                        guild_data['rc_category_name'] = new_category_name
                    elif category.lower() == 'deads':
                        guild_data['dead_rc_category_name'] = new_category_name
                    elif category.lower() == 'alts':
                        guild_data['alt_category_name'] = new_category_name
                    elif category.lower() == 'inaccessiblehouses':
                        guild_data['inaccessible_houses_category_name'] = new_category_name
                    elif category.lower() == 'oldpcs':
                        guild_data['old_pcs_category_name'] = new_category_name
                    elif category.lower() == 'nominations':
                        guild_data['nominations_category_name'] = new_category_name
                    save_guild_data(ctx.guild.id, guild_data)
                    await ctx.send(f'{category.capitalize()} category has been set to {new_category_name}')
                else:
                    await ctx.send('Invalid category name:\n- Overseer\n- AboutTheGame\n- Chats\n- OverseerRelations\n- DayChat\n- Nominations\n- PublicChats\n- PrivateChats\n- Houses\n- RoleChats\n- Deads\n- Alts\n- InaccessibleHouses\n- OldPCs')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    # Change house prefix
    @commands.command()
    async def houseprefix(self, ctx, *, prefix: str):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild_data['house_prefix'] = prefix
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.send(f"House prefix changed to `{prefix}`")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    # Set knock duration
    @commands.command()
    async def knockduration(self, ctx, new_timeout: int):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild_data["timeout_duration"] = new_timeout
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.send(f"Knock duration set to {new_timeout} seconds")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def showwhispersender(self, ctx, value: str):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if value.lower() in ["true", "false"]:
            guild_data["showwhispersender"] = value.lower() == "true"
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Show Whisper Sender set to {guild_data['showwhispersender']}.")
        else:
            await ctx.send("Please specify 'true' or 'false'.")

    @commands.command()
    async def ajifempty(self, ctx, value: str):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if value.lower() in ["true", "false"]:
            guild_data["autojoinifempty"] = value.lower() == "true"
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Auto Join if Empty set to {guild_data['autojoinifempty']}.")
        else:
            await ctx.send("Please specify 'true' or 'false'.")

    @commands.command()
    async def ajknockexpire(self, ctx, value: str):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if value.lower() in ["true", "false"]:
            guild_data["autojoinknockexpired"] = value.lower() == "true"
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Auto Join on Knock Expire set to {guild_data['autojoinknockexpired']}.")
        else:
            await ctx.send("Please specify 'true' or 'false'.")

    @commands.command()
    async def maxpinh(self, ctx, value: int):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        guild_data["maxmembersinhome"] = value
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(f"Max Player in Home set to {guild_data['maxmembersinhome']}.")

    @commands.command()
    async def refuseresponse(self, ctx, value: int):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        if value not in [1, 2, 3]:
            await ctx.send("refuseresponse must be 1, 2, or 3.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        guild_data["refuseresponse"] = value
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(f"Refuse response set to {guild_data['refuseresponse']}.")

    @commands.command()
    async def deadcount(self, ctx, value: bool):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            guild_data['dead_count'] = value
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Dead Count has been set to {value}.")
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def altcount(self, ctx, value: bool):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            guild_data['alt_count'] = value
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Alt Count has been set to {value}.")
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def showdeadsonrefuse(self, ctx, value: bool):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            guild_data['show_dead_on_refuse'] = value
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Show Deads on refuse setted to {value}.")
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def showaltsonrefuse(self, ctx, value: bool):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            guild_data['show_alt_on_refuse'] = value
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Show Alts on refuse setted to {value}.")
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def candeadsinteract(self, ctx, value: bool):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            guild_data['can_dead_open'] = value
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Deads can interact with the door setted on {value}.")
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def canaltsinteract(self, ctx, value: bool):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            guild_data['can_alt_open'] = value
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Alts can interact with doors setted on {value}.")
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def settings(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        
        embed = discord.Embed(color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        
        embed.add_field(name="Timeout Duration", value=str(guild_data.get("timeout_duration")), inline=False)
        embed.add_field(name="Show Whisper Sender", value=str(guild_data.get("showwhispersender")), inline=False)
        embed.add_field(name="Auto Join if empty", value=str(guild_data.get("autojoinifempty")), inline=False)
        embed.add_field(name="Auto Join on knock expire", value=str(guild_data.get("autojoinknockexpired")), inline=False)
        embed.add_field(name="Max Players in Home", value=str(guild_data.get("maxmembersinhome")), inline=False)
        embed.add_field(name="Refuse Response", value=str(guild_data.get("refuseresponse")), inline=False)
        embed.add_field(name="Vote in RC", value=str(guild_data.get("voteinrc")), inline=False)
        embed.add_field(name="Dead count in House", value=str(guild_data.get("dead_count")), inline=False)
        embed.add_field(name="Alt count in House", value=str(guild_data.get("alt_count")), inline=False)
        embed.add_field(name="Show Deads on knock refuse", value=str(guild_data.get("show_dead_on_refuse")), inline=False)
        embed.add_field(name="Show Alts on knock refuse", value=str(guild_data.get("show_alt_on_refuse")), inline=False)
        embed.add_field(name="Can Deads interact with the door", value=str(guild_data.get("can_dead_open")), inline=False)
        embed.add_field(name="Can Alts interact with the door", value=str(guild_data.get("can_alt_open")), inline=False)

        await ctx.send(embed=embed)

    # Reset
    @commands.command()
    async def resetdb(self, ctx):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                embedq = discord.Embed(title="Confirm you want to reset all personalization", description="Click a button to confirm or cancel.", color=0xff3fb9, timestamp=datetime.now())
                embedq.set_footer(text="Village Game")
                confirm_view = View(timeout=30)
                async def confirm_callback(interaction):
                    if interaction.user == ctx.author:
                        save_guild_data(ctx.guild.id, base_variables)
                        embedy = discord.Embed(title="Done", description="Personalization has been reset", color=discord.Color.green(), timestamp=datetime.now())
                        embedy.set_footer(text="Village Game")
                        await interaction.response.edit_message(embed=embedy, view=None)
                    else:
                        await interaction.response.send_message("You can't confirm this action.", ephemeral=True)
                async def cancel_callback(interaction):
                    if interaction.user == ctx.author:
                        embedn = discord.Embed(title="Reset canceled", description="Your personalization settings remain unchanged", color=discord.Color.red(), timestamp=datetime.now())
                        embedn.set_footer(text="Village Game")
                        await interaction.response.edit_message(embed=embedn, view=None)
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
            await ctx.send("You don't have enough permissions to use this command")