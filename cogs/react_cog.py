"""`.react` — add reactions to the message you reply to.

Supported arguments (mix and match, separated by spaces and/or commas):
  * numbers 0-10      → keycap emojis (1️⃣ … 9️⃣, 🔟, 0️⃣)
  * ranges            → `1-10`
  * pasted custom     → `<:pepe:123456789>` / `<a:spin:987654321>`
  * literal emojis    → ✅ 🔥 👀
  * words             → spelled out with letter (regional indicator) emojis

A letter can only be reacted with once per message, so repeated letters use a
visually similar stand-in instead (e.g. `hello` → 🇭 🇪 🇱 1️⃣ 🇴).

Admin/overseer only. The `.react` command message is deleted afterwards.
"""

import re

import discord
from discord.ext import commands

from cogs.data_utils import load_guild_data

# Discord allows at most 20 distinct reactions on a single message.
MAX_REACTIONS = 20

KEYCAP_EMOJIS = {
    0: "0️⃣",
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
}

# 🇦 … 🇿, in A-Z order.
REGIONAL_INDICATORS = {chr(ord("a") + i): chr(0x1F1E6 + i) for i in range(26)}

# Discord only lets a message hold one reaction per emoji, so a repeated letter
# can't be added twice. These are the visual stand-ins used for the 2nd, 3rd…
# occurrence of a letter (e.g. `hello` → 🇭 🇪 🇱 1️⃣ 🇴, `see` → 🇸 🇪 3️⃣).
LETTER_ALTERNATES = {
    "a": ("4️⃣", "🅰️"),
    "b": ("8️⃣", "🅱️"),
    "c": ("©️",),
    "d": ("🌓",),
    "e": ("3️⃣",),
    "f": ("🚩",),
    "g": ("6️⃣", "9️⃣"),
    "h": ("♓️",),
    "i": ("❗", "ℹ️"),
    "j": ("🪝",),
    "k": ("🔑",),
    "l": ("1️⃣",),
    "m": ("Ⓜ️",),
    "n": ("♑",),
    "o": ("0️⃣", "🅾️"),
    "p": ("🅿️",),
    "q": ("🔍",),
    "r": ("®️",),
    "s": ("5️⃣", "💲"),
    "t": ("7️⃣", "➕"),
    "u": ("⛎",),
    "v": ("✌️",),
    "w": ("〰️",),
    "x": ("✖️", "❌"),
    "y": ("🌱",),
    "z": ("2️⃣", "💤"),
}

RANGE_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
TOKEN_SPLIT_RE = re.compile(r"[,\s]+")
CUSTOM_EMOJI_RE = re.compile(r"^<a?:\w+:\d+>$")


def spell_word(word: str):
    """Spell ``word`` with letter emojis, substituting repeated letters.

    Returns ``(emojis, dropped)``. ``dropped`` counts repeated characters that
    ran out of stand-ins (normally only for words with 3+ of the same letter).
    Literal digits mixed into the word become keycaps; punctuation is ignored.
    """
    emojis = []
    emitted_digits = set()
    # Literal digits win over letter stand-ins, so reserve them up front.
    used = {
        KEYCAP_EMOJIS[int(ch)] for ch in word if ch in "0123456789"
    }
    dropped = 0

    for ch in word:
        key = ch.lower()

        if key in REGIONAL_INDICATORS:
            candidates = (REGIONAL_INDICATORS[key],) + LETTER_ALTERNATES.get(key, ())
            for emoji in candidates:
                if emoji not in used:
                    used.add(emoji)
                    emojis.append(emoji)
                    break
            else:
                dropped += 1
            continue

        if ch in "0123456789":
            emoji = KEYCAP_EMOJIS[int(ch)]
            if emoji in emitted_digits:
                dropped += 1
                continue
            emitted_digits.add(emoji)
            emojis.append(emoji)

    return emojis, dropped


def parse_react_args(raw: str):
    """Turn `.react` arguments into ``(emojis, unknown)``.

    ``emojis`` is ordered and de-duplicated. ``unknown`` holds numbers that
    have no keycap (e.g. ``20``) and words that cannot be spelled out.
    """
    emojis = []
    unknown = []

    def add(emoji: str) -> None:
        if emoji not in emojis:
            emojis.append(emoji)

    # Allow "1 - 10" as well as "1-10".
    raw = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", raw or "")

    for token in TOKEN_SPLIT_RE.split(raw.strip()):
        if not token:
            continue

        range_match = RANGE_RE.match(token)
        if range_match:
            start, end = sorted(int(n) for n in range_match.groups())
            for number in range(start, end + 1):
                if number in KEYCAP_EMOJIS:
                    add(KEYCAP_EMOJIS[number])
                else:
                    unknown.append(str(number))
            continue

        if token.isdigit():
            number = int(token)
            if number in KEYCAP_EMOJIS:
                add(KEYCAP_EMOJIS[number])
            else:
                unknown.append(token)
            continue

        if CUSTOM_EMOJI_RE.match(token):
            add(token)
            continue

        if any(ch.isalpha() for ch in token):
            # Word mode: spell it out. Repeated letters get a lookalike
            # stand-in because Discord can't add the same reaction twice.
            spelled, _dropped = spell_word(token)
            if spelled:
                for emoji in spelled:
                    add(emoji)
            else:
                unknown.append(token)
            continue

        # Anything else is assumed to be a literal unicode emoji. Plain ASCII
        # punctuation (a stray "-", "!", etc.) can't be an emoji.
        if token.isascii():
            unknown.append(token)
        else:
            add(token)

    return emojis, unknown


class ReactCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="react")
    async def react(self, ctx, *, args: str = None):
        """Add reactions to the message you reply to (admin/overseer only)."""
        if ctx.guild is None:
            return

        guild_data = load_guild_data(ctx.guild.id) or {}
        overseer_role = discord.utils.get(
            ctx.guild.roles, name=guild_data.get("overseer_role_name")
        )
        is_overseer = overseer_role is not None and overseer_role in ctx.author.roles
        if not (ctx.author.guild_permissions.administrator or is_overseer):
            await ctx.send("You don't have enough perms to use this command")
            return

        if not ctx.message.reference or not ctx.message.reference.message_id:
            await ctx.send(
                "❌ Reply to the message you want me to react to.\n"
                "Examples: `.react 1,2,3` · `.react 1-10` · `.react ✅` · `.react word`"
            )
            return

        if not args or not args.strip():
            await ctx.send(
                "❌ Tell me what to react with.\n"
                "Examples: `.react 1,2,3` · `.react 1-10` · `.react ✅` · `.react word`"
            )
            return

        emojis, unknown = parse_react_args(args)
        if not emojis:
            await ctx.send(f"❌ I couldn't understand any of that: `{args}`")
            return

        target = ctx.message.reference.resolved
        if not isinstance(target, discord.Message):
            try:
                target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await ctx.send("❌ I can't access the message you replied to.")
                return

        # Respect Discord's 20-reactions-per-message limit.
        existing = {str(reaction.emoji) for reaction in target.reactions}
        to_add = [emoji for emoji in emojis if emoji not in existing]
        room = MAX_REACTIONS - len(existing)
        if room <= 0 or not to_add:
            if room <= 0:
                await ctx.send(
                    f"❌ That message already has {MAX_REACTIONS} different reactions "
                    "(Discord's limit)."
                )
            else:
                await ctx.send("❌ All of those reactions are already on that message.")
            return

        truncated = len(to_add) > room
        to_add = to_add[:room]

        failed = []
        for emoji in to_add:
            try:
                await target.add_reaction(emoji)
            except (discord.Forbidden, discord.HTTPException):
                failed.append(emoji)

        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        problems = unknown + failed
        if problems:
            shown = ", ".join(f"`{item}`" for item in problems[:10])
            extra = f" (+{len(problems) - 10} more)" if len(problems) > 10 else ""
            await ctx.send(f"⚠️ Couldn't react with: {shown}{extra}")
        if truncated:
            await ctx.send(
                f"⚠️ Only added {room} reaction(s) — a message can hold at most "
                f"{MAX_REACTIONS} different reactions."
            )


async def setup(bot):
    await bot.add_cog(ReactCog(bot))
