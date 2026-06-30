from __future__ import annotations

import json
import os
import re

import discord
from discord import app_commands
from discord.ext import commands

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
REFS_FILE = os.path.join(DATA_DIR, "references.json")

LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild>\d+)/(?P<channel>\d+)/(?P<message>\d+)"
)


def _load_refs() -> dict:
    if not os.path.exists(REFS_FILE):
        return {}
    with open(REFS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_refs(refs: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REFS_FILE, "w", encoding="utf-8") as f:
        json.dump(refs, f, indent=2, ensure_ascii=False)


async def _resolve_target(ctx: commands.Context, target: str | None) -> tuple[int, int] | None:
    if target:
        m = LINK_RE.search(target)
        if m:
            return int(m.group("channel")), int(m.group("message"))
        parts = target.strip().split("-")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
        return None

    if ctx.message.reference and ctx.message.reference.message_id:
        ref = ctx.message.reference
        channel_id = ref.channel_id or ctx.channel.id
        return channel_id, ref.message_id

    return None


async def _show_ref(ctx: commands.Context, ref_type: str):
    refs = _load_refs()
    guild_refs = refs.get(str(ctx.guild.id), {})
    entry = guild_refs.get(ref_type)
    if not entry:
        await ctx.send(f"No {ref_type} reference has been set. Use `.setref {ref_type} <link>`")
        return

    channel = ctx.guild.get_channel(entry["channel_id"])
    if not channel:
        await ctx.send(f"The channel for the {ref_type} reference no longer exists.")
        return

    try:
        msg = await channel.fetch_message(entry["message_id"])
    except (discord.NotFound, discord.Forbidden):
        await ctx.send(f"The {ref_type} reference message was deleted or inaccessible.")
        return

    embed = discord.Embed(
        title=f"📌 {ref_type.capitalize()} Reference",
        color=discord.Color.teal(),
    )
    if msg.content:
        embed.description = msg.content[:4096]
    embed.set_author(name=msg.author.display_name, icon_url=msg.author.display_avatar.url)

    files = []
    if msg.attachments:
        att = msg.attachments[0]
        embed.set_image(url=att.url)

    embed.add_field(name="Go to message", value=msg.jump_url, inline=False)

    await ctx.send(embed=embed, files=files if files else None)


def _build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🐦 Blood on the Clocktower Commands",
        color=discord.Color.teal(),
    )

    embed.add_field(
        name="`.rr <name>` / </role>",
        value="Look up a role by name or alias.\n"
              "Usage: `.rr washerwoman`\n"
              "Shows ability, team, edition, reminder tokens. Interactive buttons for jinxes, night order, aliases, and wiki.",
        inline=False,
    )
    embed.add_field(
        name="`.jinx <name>` / </jinx>",
        value="Show all jinxes for a role.\n"
              "Usage: `.jinx alchemist`",
        inline=False,
    )
    embed.add_field(
        name="`.fabled <name>` / </fabled>",
        value="Look up a fabled character.\n"
              "Usage: `.fabled djinn`",
        inline=False,
    )
    embed.add_field(
        name="`.scripts [tb|bmr|snv]` / </scripts>",
        value="View a script as full-script image with role icons by team.\n"
              "Usage: `.scripts` (interactive buttons) or `.scripts tb` (skip buttons)",
        inline=False,
    )
    embed.add_field(
        name="`.nightorder [tb|bmr|snv]` / </nightorder>",
        value="Display first-night and other-night order.\n"
              "Usage: `.nightorder` (interactive buttons), `.nightorder bmr` (skip buttons), or `.nightorder bmr short` (role names only)",
        inline=False,
    )
    embed.add_field(
        name="`.setref <script|grim> [link]`",
        value="Store a reference message for this server.\n"
              "Usage: `.setref script` (reply to a message) or `.setref grim <message_link>`",
        inline=False,
    )
    embed.add_field(
        name="`.ref <script|grim>`",
        value="Show the saved reference message with its image.\n"
              "Usage: `.ref script`",
        inline=False,
    )
    embed.add_field(
        name="── Voting ──",
        value="Players with the **Alive** Discord role vote via buttons on the nomination embed.\n"
              "Sponsors can vote. Dead players can vote once if they still have a dead vote.",
        inline=False,
    )
    embed.add_field(
        name="`.bnominate @player`",
        value="[Admin] Start a nomination with voting buttons.\n"
              "Usage: `.bnominate @player`\n"
              "Creates a seating chart with Guilty/Not Guilty buttons, visual clock, accusation/defense fields. Expires after timeout.",
        inline=False,
    )
    embed.add_field(
        name="`.baccuse <text>`",
        value="[Admin] Set the accusation for the current nomination.\n"
              "Usage: `.baccuse I saw them with the murder weapon`\n"
              "Max 1024 characters.",
        inline=False,
    )
    embed.add_field(
        name="`.bdefend <text>`",
        value="[Admin] Set the defense for the current nomination.\n"
              "Usage: `.bdefend I was elsewhere at the time`\n"
              "Max 1024 characters.",
        inline=False,
    )
    embed.add_field(
        name="`.bnomtimeout <minutes>`",
        value="[Admin] Set the nomination expiry timeout.\n"
              "Usage: `.bnomtimeout 2`\n"
              "No default timeout — nomination runs until manually closed or timed out via this command. Minimum 1 minute.",
        inline=False,
    )
    embed.add_field(
        name="`.bclose`",
        value="[Admin] Close the current nomination early.\n"
              "Usage: `.bclose`\n"
              "Also available as a 🔒 Close Voting button on the nomination embed for Storytellers.",
        inline=False,
    )
    embed.add_field(
        name="`.bnoms`",
        value="Show current nomination status without creating a new message.\n"
              "Usage: `.bnoms`\n"
              "Displays seating chart, votes, clock position, and required guilty count.",
        inline=False,
    )
    embed.add_field(
        name="── Seating ──",
        value="Set and view the BOTC seating order. All nomination mechanics reference this order.",
        inline=False,
    )
    embed.add_field(
        name="`.bsetseating @p1 @p2 ...`",
        value="[Admin] Set the permanent seating order.\n"
              "Usage: `.bsetseating @alice @bob @charlie @dave`\n"
              "Auto-creates private neighbor threads in `🌞daytime-chat` for each alive-adjacent pair. Only pings the two players (Storytellers added silently). Min 3 players.",
        inline=False,
    )
    embed.add_field(
        name="`.bseating`",
        value="Show the current seating order.\n"
              "Usage: `.bseating`\n"
              "Displays player names with dead ☠️ and → sponsor: indicators.",
        inline=False,
    )
    embed.add_field(
        name="── Player State ──",
        value="Track dead/alive status, sponsors, and view the deadlist.",
        inline=False,
    )
    embed.add_field(
        name="`.bkill @player`",
        value="[Admin] Mark a player as dead with double confirmation.\n"
              "Usage: `.bkill @alice`\n"
              "Shows new neighbor pairs before confirming, then recreates threads skipping the dead player.",
        inline=False,
    )
    embed.add_field(
        name="`.brevive @player`",
        value="[Admin] Revive a dead player.\n"
              "Usage: `.brevive @alice`\n"
              "Restores their dead vote capability.",
        inline=False,
    )
    embed.add_field(
        name="`.bsponsor @player @sponsor`",
        value="[Admin] Assign a sponsor to a player.\n"
              "Usage: `.bsponsor @alice @bob`\n"
              "Bob is now Alice's sponsor. Sponsors can vote normally.",
        inline=False,
    )
    embed.add_field(
        name="`.bunsponsor @player`",
        value="[Admin] Remove the sponsor from a player.\n"
              "Usage: `.bunsponsor @alice`",
        inline=False,
    )
    embed.add_field(
        name="`.bdead`",
        value="Show the list of dead players and their dead vote status.\n"
              "Usage: `.bdead`\n"
              "Shows who is dead and whether they still have a dead vote remaining.",
        inline=False,
    )

    embed.set_footer(text="Use .botchelp or /help to see this message again.")
    return embed


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show available BOTC commands")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=_build_help_embed())

    @commands.command(name="botchelp")
    async def botchelp(self, ctx: commands.Context):
        await ctx.send(embed=_build_help_embed())

    @commands.group(name="setref", invoke_without_command=True)
    async def setref(self, ctx: commands.Context, ref_type: str, *, target: str | None = None):
        if ref_type not in ("script", "grim"):
            await ctx.send("Usage: `.setref <script|grim> [message_link]` (or reply to a message)")
            return
        resolved = await _resolve_target(ctx, target)
        if not resolved:
            await ctx.send("Could not find the target message. Provide a message link or reply to one.")
            return

        channel_id, message_id = resolved
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            await ctx.send("That channel doesn't exist in this server.")
            return
        try:
            msg = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden):
            await ctx.send("Could not fetch that message. Check the link.")
            return

        refs = _load_refs()
        gid = str(ctx.guild.id)
        refs.setdefault(gid, {})[ref_type] = {"channel_id": channel_id, "message_id": message_id}
        _save_refs(refs)

        await ctx.send(f"✅ {ref_type.capitalize()} reference set to [this message]({msg.jump_url}).")

    @commands.command(name="ref")
    async def ref(self, ctx: commands.Context, ref_type: str):
        if ref_type not in ("script", "grim"):
            await ctx.send("Usage: `.ref <script|grim>`")
            return
        await _show_ref(ctx, ref_type)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
