import discord
import asyncio
import aiohttp
import datetime
import difflib
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from discord.ext import commands
from discord.ui import Button, View, Select
from cogs.data_utils import load_guild_data, save_guild_data, base_variables, set_lynch_channel
from cogs.help_misc_cog import COMMON_TIMEZONES

def _utc_offset_str(tz_name: str) -> str:
    try:
        offset = datetime.now(ZoneInfo(tz_name)).utcoffset()
        total_seconds = int(offset.total_seconds())
        hours, remainder = divmod(abs(total_seconds), 3600)
        minutes = remainder // 60
        sign = "+" if total_seconds >= 0 else "-"
        if minutes:
            return f" (UTC{sign}{hours}:{minutes:02d})"
        return f" (UTC{sign}{hours})"
    except Exception:
        return ""

def _refresh_voting_schedule(bot):
    """Tell the voting cog's lynch-end loop that a time changed, so it re-reads it now."""
    voting = bot.get_cog("Voting")
    if voting is not None:
        voting.refresh_lynch_schedule()


def _parse_time_value(val: str):
    """Parse a stored time value like '14:30' or '14:30|America/New_York'.
    Returns (hour, minute, tz_name_or_None)."""
    tz_name = None
    if "|" in val:
        time_part, tz_name = val.split("|", 1)
    else:
        time_part = val
    h, m = (int(x) for x in time_part.split(":"))
    return h, m, tz_name


_CUSTOM_EMOJI_RE = re.compile(r"<(a?):([0-9a-zA-Z_]+):(\d+)>")

def _parse_custom_emoji(emoji: str):
    """Parse a custom emoji string like `<:pepe:123456789>` or `<a:pepe:123456789>`.

    Returns (name, emoji_id, animated) or None if it isn't a custom emoji."""
    match = _CUSTOM_EMOJI_RE.fullmatch(emoji.strip())
    if not match:
        return None
    animated = bool(match.group(1))
    name = match.group(2)
    emoji_id = int(match.group(3))
    return name, emoji_id, animated


_CHANNEL_MENTION_RE = re.compile(r"<#(\d+)>")


def _normalize_channel_name(name: str) -> str:
    """Lowercase a channel name and collapse separators/emoji so lookups are forgiving."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _resolve_channel(guild, value):
    """Resolve *value* to a guild text channel as robustly as possible.

    Accepts, in order of confidence: a channel mention (``<#id>``), a raw ID, a
    ``#name``, an exact name, a name that only differs by emoji/punctuation/case,
    a unique substring, or a unique fuzzy match. Returns ``(channel, candidates)``
    where *candidates* holds the closest near-misses when *value* was ambiguous
    (or couldn't be resolved at all).
    """
    value = (value or "").strip()
    if not value:
        return None, []

    mention = _CHANNEL_MENTION_RE.fullmatch(value)
    if mention:
        return guild.get_channel(int(mention.group(1))), []

    query = value[1:] if value.startswith("#") else value
    if query.isdigit():
        channel = guild.get_channel(int(query))
        if channel is not None:
            return channel, []

    channels = list(guild.text_channels)
    target = query.lower()
    norm_target = _normalize_channel_name(query)

    # Exact name (case-insensitive) wins outright - channel names are unique.
    for channel in channels:
        if channel.name.lower() == target:
            return channel, []

    # Group channels by normalised name so emoji/punctuation can be ignored.
    norm = {}
    for channel in channels:
        norm.setdefault(_normalize_channel_name(channel.name), []).append(channel)

    if norm_target:
        if len(norm.get(norm_target, [])) == 1:
            return norm[norm_target][0], []

        contains = [c for c in channels if target in c.name.lower()]
        if len(contains) == 1:
            return contains[0], []
        norm_contains = [c for c in channels if norm_target in _normalize_channel_name(c.name)]
        if len(norm_contains) == 1:
            return norm_contains[0], []

        close = difflib.get_close_matches(norm_target, list(norm.keys()), n=3, cutoff=0.6)
        if len(close) == 1 and len(norm[close[0]]) == 1:
            return norm[close[0]][0], []

    # No unique hit - offer the nearest candidates (fuzzy first, then substring).
    suggestions = []
    seen_ids = set()

    def add(candidates):
        for channel in candidates:
            if channel.id not in seen_ids:
                seen_ids.add(channel.id)
                suggestions.append(channel)

    if norm_target:
        for close_key in difflib.get_close_matches(norm_target, list(norm.keys()), n=5, cutoff=0.5):
            add(norm[close_key])
    add([c for c in channels if target and target in c.name.lower()])
    return None, suggestions[:10]


SETUP_GUIDE_PAGES = [
    {
        "title": "🛠️ Setup Guide 1/2 — Server & Roles",
        "steps": [
            ("1. Create houses and RoleChats",
             "`.setup 12 10`\nCreates 12 houses and 10 RCs (admin, asks you to confirm). First number = houses, second = RCs."),
            ("2. Map your roles (skip if `.setup` made them)",
             "`.roleset alive @Alive`\n`.roleset sponsor @Sponsor`\nKeys: overseer, alive, sponsor, spectator, dead, alt."),
            ("3. Give out the roles",
             "Give **Alive** to every player and **Sponsor** to every sponsor in Discord's member list."),
            ("4. Assign RCs and houses to players",
             "Every Alive player gets one RoleChat. Pick a house method:\n"
             "`.home initialize` **structured**: each player gets their own house (extra players share once houses run out).\n"
             "`.home initstagger` **staggered**: players are dealt randomly across the houses."),
        ],
    },
    {
        "title": "🛠️ Setup Guide 2/2 — Sponsors & Settings",
        "steps": [
            ("5. Add sponsors to RoleChats",
             "`.addspons @Sam #rc-3`\nAdds a sponsor straight into a RoleChat."),
            ("6. Set sponsor homes",
             "`.home setup`\nMoves every sponsor into their player's house.\nOne sponsor only: `.home set @Sam #house-3`"),
            ("7. Knock timeout",
             "`.knockduration 600`\nHow long a knock waits for an answer, in seconds."),
            ("8. Auto-join when a house is empty",
             "`.ajifempty true`\nPlayers join an empty house automatically."),
            ("9. Auto-join when a knock expires",
             "`.ajknockexpire true`\nIf nobody answers a knock, the knocker joins automatically."),
        ],
    },
]


class SetupGuideView(View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.index = 0
        self.message = None

    def _embed(self) -> discord.Embed:
        page = SETUP_GUIDE_PAGES[self.index]
        embed = discord.Embed(title=page["title"], color=0xff3fb9)
        for name, value in page["steps"]:
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text="Check your current settings anytime with .settings")
        return embed

    def _sync_buttons(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index == len(SETUP_GUIDE_PAGES) - 1

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        self.index = max(0, self.index - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        self.index = min(len(SETUP_GUIDE_PAGES) - 1, self.index + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="setupguide", aliases=["setuphelp"])
    async def setupguide(self, ctx):
        """Show a two-page guide to setting up a game, with example commands."""
        view = SetupGuideView(ctx.author.id)
        view._sync_buttons()
        view.message = await ctx.send(embed=view._embed(), view=view)

    # Auto setup
    @commands.command()
    async def setup(self, ctx, num_houses: int, num_rcs: int):
        """Set up roles, channels and categories for the server (admin only)."""
        if ctx.author.guild_permissions.administrator:
            confirm_view = View(timeout=30)
            confirmed = {"value": False}
            async def confirm_cb(interaction):
                if interaction.user == ctx.author:
                    confirmed["value"] = True
                    await interaction.response.edit_message(content="Setting up server...", embed=None, view=None)
            async def cancel_cb(interaction):
                if interaction.user == ctx.author:
                    await interaction.response.edit_message(content="Setup cancelled.", embed=None, view=None)
            confirm_button = Button(label="✔ Yes", style=discord.ButtonStyle.green)
            confirm_button.callback = confirm_cb
            cancel_button = Button(label="❌ No", style=discord.ButtonStyle.red)
            cancel_button.callback = cancel_cb
            confirm_view.add_item(confirm_button)
            confirm_view.add_item(cancel_button)
            embed = discord.Embed(title="⚠️ Confirm Server Setup", description=f"Are you sure you want to create the FULL server setup? This will create 6 roles, 14 categories, {num_houses} houses and {num_rcs} RoleChats.", color=0xff3fb9)
            msg = await ctx.send(embed=embed, view=confirm_view)
            await confirm_view.wait()
            if not confirmed["value"]:
                try:
                    await msg.edit(content="Setup cancelled.", embed=None, view=None)
                except:
                    pass
                return
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
                await daychat_category.set_permissions(ctx.guild.default_role, read_messages=True, send_messages=False, manage_messages=False, mention_everyone=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False)
                await daychat_category.set_permissions(alive_role, read_messages=True)
                await daychat_category.set_permissions(sponsor_role, read_messages=True)
                await daychat_category.set_permissions(dead_role, read_messages=True, add_reactions=False)
                await daychat_category.set_permissions(spectator_role, read_messages=True, add_reactions=False)
                await daychat_category.set_permissions(alt_role, read_messages=False)
                await publc_category.set_permissions(ctx.guild.default_role, read_messages=True, send_messages=False, mention_everyone=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False, add_reactions=False)
                await publc_category.set_permissions(alive_role, read_messages=True)
                await publc_category.set_permissions(sponsor_role, read_messages=True)
                await publc_category.set_permissions(dead_role, read_messages=True)
                await publc_category.set_permissions(spectator_role, read_messages=True)
                await publc_category.set_permissions(alt_role, read_messages=False)
                await privc_category.set_permissions(ctx.guild.default_role, read_messages=False, mention_everyone=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False)
                await privc_category.set_permissions(spectator_role, read_messages=True, send_messages=False, add_reactions=False)
                await houses_category.set_permissions(ctx.guild.default_role, read_messages=False, mention_everyone=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, use_application_commands=False, use_embedded_activities=False)
                await houses_category.set_permissions(spectator_role, read_messages=True, send_messages=False, add_reactions=False)
                await roles_category.set_permissions(ctx.guild.default_role, read_messages=False, manage_messages=True, mention_everyone=False, use_application_commands=False, use_embedded_activities=False)
                await roles_category.set_permissions(spectator_role, view_channel=True, send_messages=False, manage_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, add_reactions=False)
                await alt_category.set_permissions(ctx.guild.default_role, read_messages=False, mention_everyone=False, use_application_commands=False, use_embedded_activities=False)
                await alt_category.set_permissions(spectator_role, read_messages=True, send_messages=False, create_public_threads=False, create_private_threads=False, send_messages_in_threads=False, add_reactions=False)
                await dead_rc_category.set_permissions(ctx.guild.default_role, read_messages=False, mention_everyone=False, use_application_commands=False, use_embedded_activities=False)
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
                set_lynch_channel(guild_data, "lynch_channel_name1", await daychat_category.create_text_channel(name=lynch_channel_name1))
                set_lynch_channel(guild_data, "lynch_channel_name2", await daychat_category.create_text_channel(name=lynch_channel_name2))
                set_lynch_channel(guild_data, "leader_channel_name", await daychat_category.create_text_channel(name=leader_channel_name))
                # Leader election 2 is optional: it is not created by .setup. Assign
                # an existing channel with `.channelset leaderelection2` to enable it.
                await daychat_category.create_text_channel(name=vote_count_name)
                await publc_category.create_text_channel(name='duplicate-this')
                await privc_category.create_text_channel(name='duplicate-this')
                for i in range(1, num_houses + 1):
                    await houses_category.create_text_channel(name=f"{house_prefix}{i}")
                for i in range(1, num_rcs + 1):
                    await roles_category.create_text_channel(str(i))
                guild_data["houselist"] = []
                for i in range(1, num_houses + 1):
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
    async def roleset(self, ctx, role: str = None, *, new_role: str = None):
        """Assign a role configuration key to a role."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if not new_role:
            await ctx.send('Please provide a valid role (mention it like @RoleName or type the name)')
            return

        # Resolve role from mention, ID, or name
        resolved = None
        if new_role.startswith('<@&') and new_role.endswith('>'):
            rid = int(new_role[3:-1])
            resolved = ctx.guild.get_role(rid)
        elif new_role.isdigit():
            resolved = ctx.guild.get_role(int(new_role))
        if resolved is None:
            resolved = discord.utils.get(ctx.guild.roles, name=new_role)
        if resolved is None:
            await ctx.send(f'Could not find role "{new_role}". Mention it like @RoleName.')
            return

        valid_keys = ['overseer', 'alive', 'sponsor', 'spectator', 'dead', 'alt']
        key = role.lower() if role else ''
        if key not in valid_keys:
            await ctx.send(f'Invalid role name, choose between:\n- ' + '\n- '.join(k.capitalize() for k in valid_keys))
            return

        guild_data[f'{key}_role_name'] = resolved.name
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(f"{role.capitalize()} role set to {resolved.name}")

    # Setup channels
    @commands.command()
    async def channelset(self, ctx, channel: str = None, *, new_channel: str = None):
        """Assign a channel configuration key to a channel.

        The channel can be a mention (#channel), an ID, or a name - emoji,
        punctuation and case are ignored, and a unique partial/close name also
        works (e.g. "vote count" matches "📊│vote-count"). If nothing is given,
        the current channel is used.
        """
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                valid_channels = ['daydiscussion', 'megaphone', 'lynchsession1', 'lynchsession2', 'lynchsession3', 'lynchsession4', 'lynchsession5', 'lynchsession6', 'leaderelection', 'leaderelection2', 'votecount', 'logchannel', 'actionslogchannel', 'announcements', 'map', 'whisperlogs', 'editdellogs', 'joinleavelogs', 'narrationlog']
                key = channel.lower() if channel else ''
                if key in valid_channels:
                    if new_channel:
                        resolved, candidates = _resolve_channel(ctx.guild, new_channel)
                        if resolved is None:
                            if candidates:
                                options = "\n".join(f"• {c.mention} (`{c.name}`)" for c in candidates)
                                await ctx.send(f'"{new_channel}" matches more than one channel. Did you mean:\n{options}\n\nTip: mention the channel or use its ID.')
                            else:
                                await ctx.send(f'Could not find a channel matching "{new_channel}". Mention it like #channel, send its ID, or type its name.')
                            return
                        new_channel = resolved
                    else:
                        new_channel = ctx.channel
                    new_channel_name = new_channel.name
                    if key == 'daydiscussion':
                        guild_data['daydiscussion_channel_name'] = new_channel_name
                    elif key == 'megaphone':
                        guild_data['megaphone_channel_name'] = new_channel_name
                    elif key == 'lynchsession1':
                        set_lynch_channel(guild_data, 'lynch_channel_name1', new_channel)
                    elif key == 'lynchsession2':
                        set_lynch_channel(guild_data, 'lynch_channel_name2', new_channel)
                    elif key == 'lynchsession3':
                        set_lynch_channel(guild_data, 'lynch_channel_name3', new_channel)
                    elif key == 'lynchsession4':
                        set_lynch_channel(guild_data, 'lynch_channel_name4', new_channel)
                    elif key == 'lynchsession5':
                        set_lynch_channel(guild_data, 'lynch_channel_name5', new_channel)
                    elif key == 'lynchsession6':
                        set_lynch_channel(guild_data, 'lynch_channel_name6', new_channel)
                    elif key == 'leaderelection':
                        set_lynch_channel(guild_data, 'leader_channel_name', new_channel)
                    elif key == 'leaderelection2':
                        set_lynch_channel(guild_data, 'leader_channel_name2', new_channel)
                    elif key == 'votecount':
                        guild_data['vote_count_name'] = new_channel_name
                    elif key == 'logchannel':
                        guild_data['log_channel_name'] = new_channel_name
                    elif key == 'actionslogchannel':
                        guild_data['actions_log_channel_name'] = new_channel_name
                    elif key == 'announcements':
                        guild_data['announcements_channel_name'] = new_channel_name
                    elif key == 'map':
                        guild_data['map_channel_name'] = new_channel_name
                    elif key == 'whisperlogs':
                        guild_data['whisper_logs_channel_name'] = new_channel_name
                    elif key == 'editdellogs':
                        guild_data['edit_del_logs'] = new_channel_name
                    elif key == 'joinleavelogs':
                        guild_data['join_and_leave_logs'] = new_channel_name
                    elif key == 'narrationlog':
                        guild_data['narration_log_channel_name'] = new_channel_name
                    save_guild_data(ctx.guild.id, guild_data)
                    await ctx.send(f"{key.capitalize()} channel set to {new_channel_name}")
                else:
                    await ctx.send('Invalid type of channel. Try using the following arguments:\n- Announcements\n- Map\n- DayDiscussion\n- Megaphone\n- LynchSession1\n- LynchSession2\n- LynchSession3\n- LynchSession4\n- LynchSession5\n- LynchSession6\n- LeaderElection\n- LeaderElection2\n- VoteCount\n- LogChannel\n- ActionsLogChannel\n- WhisperLogs\n- EditDelLogs\n- JoinLeaveLogs\n- NarrationLog')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    # Add text to the current channel name, or rename the channel
    @commands.group(invoke_without_command=True)
    async def addch(self, ctx, *, text: str = None):
        """Append text to the current channel name (admin only). Example: .addch Po makes 'apple' become 'apple -po'. Use .addch rename <name> to fully rename the channel."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        if not text:
            await ctx.send("❌ Provide the text to append. Example: `.addch Po`")
            return
        suffix = text.strip()
        if not suffix:
            await ctx.send("❌ Provide the text to append. Example: `.addch Po`")
            return
        if suffix.startswith("-"):
            new_name = f"{ctx.channel.name} {suffix}"
        else:
            new_name = f"{ctx.channel.name} -{suffix}"
        if len(new_name) > 100:
            await ctx.send("❌ The new channel name would exceed Discord's 100 character limit.")
            return
        try:
            await ctx.channel.edit(name=new_name)
            await ctx.send(f"✅ Channel renamed to `{new_name}`")
        except discord.Forbidden:
            await ctx.send("I don't have permission to rename this channel.")
        except discord.HTTPException as e:
            await ctx.send(f"❌ Could not rename the channel: {e}")

    @addch.command(name="rename")
    async def addch_rename(self, ctx, *, args: str = None):
        """Rename a channel (admin only). Defaults to current channel.
        Example: .addch rename apple pie
                 .addch rename apple pie #this
        """
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return

        # Parse manually so multi-word names work; an optional trailing #channel picks the target.
        channel = None
        new_text = (args or "").strip()
        mention = re.search(r"<#(\d+)>\s*$", new_text)
        if mention:
            channel = ctx.guild.get_channel(int(mention.group(1)))
            new_text = new_text[:mention.start()].strip()
            if channel is None:
                await ctx.send("❌ I couldn't find that channel.")
                return
        target = channel or ctx.channel

        if not new_text or new_text.startswith("<#"):
            await ctx.send("❌ Provide the new channel name. Example: `.addch rename apple-pie #channel`")
            return

        new_name = re.sub(r"[^a-z0-9_-]", "-", new_text.strip().lower())
        new_name = re.sub(r"-{2,}", "-", new_name).strip("-")
        if not new_name:
            await ctx.send("❌ That text produced an empty/invalid channel name. Example: `.addch rename apple-pie`")
            return
        if len(new_name) > 100:
            new_name = new_name[:100].strip("-")
        try:
            await target.edit(name=new_name)
            await ctx.send(f"✅ Channel {target.mention} renamed to `{new_name}`")
        except discord.Forbidden:
            await ctx.send("I don't have permission to rename this channel.")
        except discord.HTTPException as e:
            await ctx.send(f"❌ Could not rename the channel: {e}")

    # Setup categories
    @commands.command()
    async def categoryset(self, ctx, category: str, *, new_category_name: str = None):
        """Assign a category configuration key to a category."""
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
        """Set the prefix used for house channel names."""
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
        """Set the timeout duration for knocks in seconds."""
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
        """Toggle whether the whisper sender is shown or hidden."""
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
        """Toggle auto-join when a house is empty."""
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
        """Toggle auto-join when a knock expires."""
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
        """Set the maximum number of players allowed per house."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        guild_data["maxmembersinhome"] = value
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(f"Max Player in Home set to {guild_data['maxmembersinhome']}.")

    @commands.command()
    async def refuseresponse(self, ctx, value: int):
        """Set the knock refuse behavior (1=see occupants, 2=anonymous, 3=hidden)."""
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
        """Toggle whether dead players count for auto-join and max players."""
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
        """Toggle whether alt players count for auto-join and max players."""
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
        """Toggle showing dead players on knock refuse."""
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
        """Toggle showing alt players on knock refuse."""
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
        """Toggle whether dead players can open or refuse knocks."""
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
        """Toggle whether alt players can open or refuse knocks."""
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
    async def autopincorpse(self, ctx, value: bool):
        """Toggle whether corpse messages are automatically created and pinned."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            guild_data['auto_pin_corpse'] = value
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"Auto Pin Corpses has been set to {value}.")
        else:
            await ctx.send("Guild data not loaded.")

    @commands.command()
    async def settime(self, ctx, event: str = None):
        """Set a daily recurring game time via dropdowns. Events: dayend, lynchend, presetend."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        if not event:
            await ctx.send("❌ Usage: `.settime <event>`\nAvailable events: `dayend`, `lynchend`, `presetend`")
            return
        event_map = {
            "dayend": ("day_end_time", "Day End"),
            "lynchend": ("lynch_end_time", "Lynch End"),
            "presetend": ("presets_end_time", "Presets End"),
        }
        match = event_map.get(event.lower())
        if not match:
            await ctx.send("❌ Unknown event. Use: `dayend`, `lynchend`, or `presetend`.")
            return
        key, label = match

        hour_options = [discord.SelectOption(label=f"{h:02d}", value=str(h)) for h in range(24)]
        minute_options = [discord.SelectOption(label=f"{m:02d}", value=str(m)) for m in range(0, 60, 5)]
        tz_options = [
            discord.SelectOption(label=f"{name} {_utc_offset_str(tz)}", value=tz, emoji=emoji)
            for name, tz, emoji in COMMON_TIMEZONES
        ]

        state = {"hour": None, "minute": None, "tz": None}

        hour_select = Select(placeholder="Hour (24h)...", options=hour_options, min_values=1, max_values=1, row=0)
        minute_select = Select(placeholder="Minute...", options=minute_options, min_values=1, max_values=1, row=1)
        tz_select = Select(placeholder="Timezone...", options=tz_options, min_values=1, max_values=1, row=2)

        async def _save_and_confirm(interaction):
            h = state["hour"]
            m = state["minute"]
            tz_name = state["tz"]
            guild_data = load_guild_data(ctx.guild.id)
            if not guild_data:
                await interaction.response.edit_message(content="Guild data not loaded.", view=None)
                return
            guild_data[key] = f"{h:02d}:{m:02d}|{tz_name}"
            save_guild_data(ctx.guild.id, guild_data)
            _refresh_voting_schedule(ctx.bot)
            tz_obj = ZoneInfo(tz_name)
            now_local = datetime.now(tz_obj)
            target = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now_local:
                target += timedelta(days=1)
            unix_ts = int(target.timestamp())
            embed = discord.Embed(title=f"✅ {label} Updated", color=discord.Color.green())
            embed.add_field(name="Time", value=f"`{h:02d}:{m:02d}` — <t:{unix_ts}:t> (<t:{unix_ts}:R>)", inline=False)
            embed.set_footer(text="Village Game")
            await interaction.response.edit_message(embed=embed, view=None)

        async def _maybe_save(interaction):
            if state["hour"] is not None and state["minute"] is not None and state["tz"] is not None:
                await _save_and_confirm(interaction)
            else:
                await interaction.response.defer()

        async def on_hour(interaction):
            state["hour"] = int(hour_select.values[0])
            hour_select.placeholder = f"Hour: {hour_select.values[0]}"
            await _maybe_save(interaction)

        async def on_minute(interaction):
            state["minute"] = int(minute_select.values[0])
            minute_select.placeholder = f"Minute: {minute_select.values[0]}"
            await _maybe_save(interaction)

        async def on_tz(interaction):
            state["tz"] = tz_select.values[0]
            tz_label = next((n for n, v, _ in COMMON_TIMEZONES if v == state["tz"]), state["tz"])
            tz_select.placeholder = f"Timezone: {tz_label}"
            await _maybe_save(interaction)

        hour_select.callback = on_hour
        minute_select.callback = on_minute
        tz_select.callback = on_tz

        view = View(timeout=120)
        view.add_item(hour_select)
        view.add_item(minute_select)
        view.add_item(tz_select)

        async def _only_admin_author(interaction):
            if interaction.user.id == ctx.author.id and interaction.user.guild_permissions.administrator:
                return True
            await interaction.response.send_message("Only the admin who opened this menu can change it.", ephemeral=True)
            return False

        view.interaction_check = _only_admin_author

        embed = discord.Embed(
            title=f"Set {label} Time",
            description="Pick the hour, minute, and timezone for this daily event.",
            color=0xff3fb9,
        )
        embed.set_footer(text="Village Game • All three must be selected to save")
        await ctx.send(embed=embed, view=view)

    @commands.command()
    async def times(self, ctx):
        """Show all configured daily game times and when they next occur."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        events = [
            ("day_end_time", "Day End", "dayend"),
            ("lynch_end_time", "Lynch End", "lynchend"),
            ("presets_end_time", "Presets End", "presetend"),
        ]
        embed = discord.Embed(title="Daily Game Times", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        any_set = False
        for key, label, cmd in events:
            val = guild_data.get(key)
            if not val:
                embed.add_field(name=label, value=f"Not set — use `.settime {cmd}`", inline=False)
                continue
            any_set = True
            h, m, tz_name = _parse_time_value(val)
            tz_obj = ZoneInfo(tz_name) if tz_name else timezone.utc
            now_local = datetime.now(tz_obj)
            target = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now_local:
                target += timedelta(days=1)
            unix_ts = int(target.timestamp())
            display = f"<t:{unix_ts}:t> (<t:{unix_ts}:R>)"
            embed.add_field(
                name=label,
                value=display,
                inline=False,
            )
        if not any_set:
            embed.description = "No daily times configured yet."

        is_admin = ctx.author.guild_permissions.administrator
        if is_admin:
            view = TimesButtonView(ctx.author.id, guild_data, ctx.channel)
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(embed=embed)

    @commands.command()
    async def settings(self, ctx):
        """View all current server configuration settings."""
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
        embed.add_field(name="Auto Pin Corpses", value=str(guild_data.get("auto_pin_corpse", True)), inline=False)

        def _fmt_time_val(val):
            if not val:
                return "Not set"
            h, m, tz_name = _parse_time_value(val)
            base = f"{h:02d}:{m:02d}"
            if tz_name:
                tz_label = next((n for n, v, _ in COMMON_TIMEZONES if v == tz_name), tz_name)
                return f"{base} ({tz_label}{_utc_offset_str(tz_name)})"
            return f"{base} (UTC)"

        embed.add_field(name="Day End Time", value=_fmt_time_val(guild_data.get("day_end_time")), inline=False)
        embed.add_field(name="Lynch End Time", value=_fmt_time_val(guild_data.get("lynch_end_time")), inline=False)
        embed.add_field(name="Presets End Time", value=_fmt_time_val(guild_data.get("presets_end_time")), inline=False)
        embed.add_field(name="Dashboard enabled", value=str(guild_data.get("dashboard_enabled", False)), inline=False)

        await ctx.send(embed=embed)

    # Reset
    @commands.command()
    async def resetdb(self, ctx):
        """Reset all server setup configuration back to defaults."""
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

    @commands.command(name="stealemoji")
    async def stealemoji(self, ctx, emoji: str):
        """Copy a custom emoji (animated or static) from another server into this one (admin only). Usage: .stealemoji <:pepe:123456789> or <a:pepe:123456789>"""
        if not ctx.author.guild_permissions.administrator and not ctx.author.guild_permissions.manage_emojis:
            await ctx.send("You don't have enough perms to use this command")
            return

        parsed = _parse_custom_emoji(emoji)
        if parsed is None:
            await ctx.send("❌ That isn't a custom emoji. Provide one from another server, e.g. `<:pepe:123456789>` or `<a:animated:123456789>`.")
            return
        name, emoji_id, animated = parsed

        if any(existing.name == name for existing in ctx.guild.emojis):
            await ctx.send(f"❌ An emoji named `{name}` already exists in this server. Delete it first or choose a different one.")
            return

        if len(name) > 32 or not re.fullmatch(r"[0-9a-zA-Z_]+", name):
            await ctx.send("❌ The emoji name is invalid (max 32 characters, letters/digits/underscores only).")
            return

        extension = "gif" if animated else "png"
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await ctx.send(f"❌ Couldn't fetch the emoji image (HTTP {resp.status}). The emoji URL may be invalid.")
                        return
                    image_data = await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await ctx.send("❌ Couldn't download the emoji image. Try again in a few seconds.")
            return

        if len(image_data) > 256 * 1024:
            await ctx.send("❌ The emoji image is larger than Discord's 256KB upload limit.")
            return

        try:
            created = await ctx.guild.create_custom_emoji(
                name=name,
                image=image_data,
                reason=f"{name} added by {ctx.author} via .stealemoji",
            )
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to create emojis (the bot needs **Manage Emojis & Stickers**).")
            return
        except discord.HTTPException as e:
            await ctx.send(f"❌ Discord rejected the emoji: {e}")
            return

        animated_note = " (animated)" if created.animated else ""
        await ctx.send(f"✅ Added {created} `{created.name}`{animated_note} to this server.")


class TimesButtonView(View):
    def __init__(self, author_id: int, guild_data: dict, channel):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild_data = guild_data
        self.channel = channel

        day_val = guild_data.get("day_end_time")
        self.day_set = day_val is not None
        if self.day_set:
            self.day_h, self.day_m, self.day_tz = _parse_time_value(day_val)
        else:
            self.day_h, self.day_m, self.day_tz = None, None, None

        offsets = [0, 15, 30, 45, 60]
        for offset in offsets:
            lynch_btn = Button(
                label=f"-{offset}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"lynch_{offset}",
                row=0,
            )
            lynch_btn.callback = self._make_lynch_callback(offset)
            self.add_item(lynch_btn)

            preset_btn = Button(
                label=f"-{offset}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"preset_{offset}",
                row=1,
            )
            preset_btn.callback = self._make_preset_callback(offset)
            self.add_item(preset_btn)

    def _make_lynch_callback(self, offset: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("Not for you.", ephemeral=True)
                return
            if not self.day_set:
                await interaction.response.send_message(
                    "❌ Set **Day End** first with `.settime dayend`.",
                    ephemeral=True
                )
                return
            await self._save_offset("lynch_end_time", "Lynch End", offset, interaction)
        return callback

    def _make_preset_callback(self, offset: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("Not for you.", ephemeral=True)
                return
            if not self.day_set:
                await interaction.response.send_message(
                    "❌ Set **Day End** first with `.settime dayend`.",
                    ephemeral=True
                )
                return
            await self._save_offset("presets_end_time", "Presets End", offset, interaction)
        return callback

    async def _save_offset(self, key: str, label: str, offset: int, interaction: discord.Interaction):
        h = self.day_h
        m = self.day_m - offset
        tz_name = self.day_tz
        if m < 0:
            h -= 1
            m += 60
        if h < 0:
            h += 24
        self.guild_data[key] = f"{h:02d}:{m:02d}|{tz_name}"
        save_guild_data(interaction.guild.id, self.guild_data)
        _refresh_voting_schedule(interaction.client)

        tz_obj = ZoneInfo(tz_name) if tz_name else timezone.utc
        now_local = datetime.now(tz_obj)
        target = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now_local:
            target += timedelta(days=1)
        unix_ts = int(target.timestamp())

        await interaction.response.send_message(
            f"✅ **{label}** set to <t:{unix_ts}:t> (-{offset} min from Day End)",
            ephemeral=True
        )