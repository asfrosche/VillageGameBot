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
        value="Look up a role by name or alias. Shows ability, team, edition, reminder tokens. Use the buttons below the embed for jinxes, night order, aliases, and the wiki page.",
        inline=False,
    )
    embed.add_field(
        name="`.jinx <name>` / </jinx>",
        value="Show all jinxes for a given role.",
        inline=False,
    )
    embed.add_field(
        name="`.fabled <name>` / </fabled>",
        value="Look up a fabled character.",
        inline=False,
    )
    embed.add_field(
        name="`.scripts [tb|bmr|snv]` / </scripts>",
        value="View TB, BMR, or SNV as a full-script image with role icons organized by team. Include an edition to skip the interactive buttons.",
        inline=False,
    )
    embed.add_field(
        name="`.nightorder [tb|bmr|snv]` / </nightorder>",
        value="Display first-night and other-night order for the selected edition. Include an edition to skip the interactive buttons.",
        inline=False,
    )
    embed.add_field(
        name="`.setref <script|grim> [link]`",
        value="Store a message as the custom script or grim reference for this server (reply or paste a link).",
        inline=False,
    )
    embed.add_field(
        name="`.ref <script|grim>`",
        value="Show the saved reference message with its image.",
        inline=False,
    )
    embed.add_field(
        name="── Voting ──",
        value="Players with the **Alive** role vote via buttons on the nomination message.",
        inline=False,
    )
    embed.add_field(
        name="`.bnominate @player`",
        value="[Admin] Nominate a player. Seating chart embed with Guilty/Not Guilty buttons, visual clock, accusation/defense. Expires after a set time.",
        inline=False,
    )
    embed.add_field(
        name="`.baccuse <text>`",
        value="[Admin] Set the accusation for the current nomination.",
        inline=False,
    )
    embed.add_field(
        name="`.bdefend <text>`",
        value="[Admin] Set the defense for the current nomination.",
        inline=False,
    )
    embed.add_field(
        name="`.bnomtimeout <seconds>`",
        value="[Admin] Set the nomination expiry timeout (default 120s, min 10s).",
        inline=False,
    )
    embed.add_field(
        name="`.bnoms`",
        value="Show current nomination status, seating chart with votes, clock position, and required guilty votes.",
        inline=False,
    )
    embed.add_field(
        name="── Seating ──",
        value="Set and view the BOTC seating order. All mechanics reference this order.",
        inline=False,
    )
    embed.add_field(
        name="`.bsetseating @p1 @p2 ...`",
        value="[Admin] Set the permanent seating order for this server.",
        inline=False,
    )
    embed.add_field(
        name="`.bseating`",
        value="Show the current seating order with dead ☠️ and sponsor ⭐ indicators.",
        inline=False,
    )
    embed.add_field(
        name="── Player State ──",
        value="Track dead players and sponsors (substitutes who never vote).",
        inline=False,
    )
    embed.add_field(
        name="`.bkill @player`",
        value="[Admin] Mark a player as dead. They lose their dead vote.",
        inline=False,
    )
    embed.add_field(
        name="`.brevive @player`",
        value="[Admin] Revive a dead player and restore their dead vote.",
        inline=False,
    )
    embed.add_field(
        name="`.bsponsor @player`",
        value="[Admin] Mark a player as a sponsor (substitute, cannot vote).",
        inline=False,
    )
    embed.add_field(
        name="`.bunsponsor @player`",
        value="[Admin] Remove sponsor status from a player.",
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
