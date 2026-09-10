import discord
from cogs.data_utils import load_guild_data


async def after_movement_update(ctx, target_member=None):
    """Call this after every movement operation to keep Follow/Track/Stalk in sync."""
    guild_data = load_guild_data(ctx.guild.id)
    if not guild_data:
        return

    cog = ctx.bot.get_cog("Surveillance")
    if cog:
        await cog.after_movement_update(ctx.guild, guild_data)
