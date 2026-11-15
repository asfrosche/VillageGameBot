"""Private PC shop item: naming and channel creation.

A private PC is opened between the buyer and one alive player. Every sponsor is added too,
like a `.newpc private` channel. The default channel name is the two Discord usernames,
each reversed, joined with a dash. For example, `coconut` opening with `falcon` gives
`tunococ-noclaf`.
"""
from __future__ import annotations

import re

import discord


def _reversible_username(username: str | None) -> str:
    """Lowercase, keep only characters Discord allows in channel names, then reverse."""
    cleaned = re.sub(r"[^a-z0-9_-]", "", (username or "").lower())
    return cleaned[::-1] or "player"


def private_pc_name(first_username: str, second_username: str) -> str:
    """Channel name for two players: reversed usernames joined with a dash, initiator first."""
    return f"{_reversible_username(first_username)}-{_reversible_username(second_username)}"


def unique_channel_name(existing_names, base: str) -> str:
    """Return *base*, or *base-2*, *base-3*, ... if that name is already taken."""
    taken = {name.lower() for name in existing_names}
    if base.lower() not in taken:
        return base
    number = 2
    while f"{base}-{number}".lower() in taken:
        number += 1
    return f"{base}-{number}"


def sponsor_members(guild: discord.Guild, sponsor_role: discord.Role | None) -> list:
    """Every non-bot member with the sponsor role."""
    if sponsor_role is None:
        return []
    return [member for member in guild.members if sponsor_role in member.roles and not member.bot]


async def create_private_pc(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    initiator: discord.Member,
    target: discord.Member,
    sponsor_role: discord.Role | None,
) -> discord.TextChannel:
    """Create the private PC in *category* with the two players and all sponsors able to read and send."""
    name = unique_channel_name(
        [channel.name for channel in guild.text_channels],
        private_pc_name(initiator.name, target.name),
    )
    channel = await category.create_text_channel(name=name)
    await channel.set_permissions(guild.default_role, read_messages=False)

    participants = {member.id: member for member in [initiator, target, *sponsor_members(guild, sponsor_role)]}
    for member in participants.values():
        await channel.set_permissions(member, read_messages=True, send_messages=True)

    await channel.send(
        f"🔒 {initiator.mention} and {target.mention} opened a private channel. "
        "Sponsors have been added."
    )
    return channel
