import re
import discord
import asyncio
from datetime import datetime

from discord.ext import commands
from discord.ui import Button, View

from cogs.data_utils import load_guild_data, save_guild_data
from utils.embeds import info_embed, success_embed, error_embed


class Infos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def info(self, ctx, type: str = None, channel: discord.TextChannel = None, *, info_or_number: str = None):
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if type and re.match(r'<#(\d+)>', type):
                    channel_id = int(re.match(r'<#(\d+)>', type).group(1))
                    channel = ctx.guild.get_channel(channel_id)
                    if channel:
                        await self.info_show(ctx, channel, guild_data)
                    else:
                        await ctx.send(f'{type} is not a valid channel.')
                elif type.lower() == 'add':
                    if channel is None:
                        channel = ctx.channel
                    await self.info_add(ctx, channel, info_or_number, guild_data)
                elif type.lower() == 'remove':
                    if channel is None:
                        channel = ctx.channel
                    await self.info_remove(ctx, channel, info_or_number, guild_data)
                elif type.lower() == 'edit':
                    if channel is None:
                        channel = ctx.channel
                    await self.info_edit(ctx, channel, info_or_number, guild_data)
                elif type.lower() == 'reset':
                    await self.info_reset(ctx, guild_data)
                else:
                    await ctx.send(f'{type} is not a valid argument for info command.')
            else:
                await ctx.send('Guild data not loaded.')
        else:
            await ctx.send("You don't have enough perms to use this command")

    async def info_show(self, ctx, channel, guild_data):
        channel_id = str(channel.id)
        if "infos" in guild_data and channel_id in guild_data["infos"]:
            infos = guild_data["infos"][channel_id]
            info_list = []
            for idx, info in enumerate(infos, 1):
                info_list.append(f"{idx}. {info}")
            info_list_str = "\n".join(info_list)
            embed = info_embed(
                title=f"{channel.name} infos",
                description=info_list_str,
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"No info found for {channel.name}.")

    async def info_add(self, ctx, channel, info, guild_data):
        channel_id = str(channel.id)
        if "infos" not in guild_data:
            guild_data["infos"] = {}
        if channel_id not in guild_data["infos"]:
            guild_data["infos"][channel_id] = []
        guild_data["infos"][channel_id].append(info)
        save_guild_data(ctx.guild.id, guild_data)
        await ctx.send(f"Info added to {channel.name}.")

    async def info_remove(self, ctx, channel, number, guild_data):
        channel_id = str(channel.id)
        if "infos" in guild_data and channel_id in guild_data["infos"]:
            try:
                idx = int(number) - 1
                if 0 <= idx < len(guild_data["infos"][channel_id]):
                    del guild_data["infos"][channel_id][idx]
                    save_guild_data(ctx.guild.id, guild_data)
                    await ctx.send(f"Info {number} removed from {channel.name}.")
                else:
                    await ctx.send("Invalid info number.")
            except ValueError:
                await ctx.send("Invalid info number.")
        else:
            await ctx.send(f"No info found for {channel.name}.")

    async def info_edit(self, ctx, channel, number_and_info, guild_data):
        """
        Edit an existing info entry.
        Usage: .info edit #channel <number> <new text>
        """
        channel_id = str(channel.id)
        if "infos" not in guild_data or channel_id not in guild_data["infos"]:
            await ctx.send(f"No info found for {channel.name}.")
            return

        if not number_and_info:
            await ctx.send("Usage: `.info edit [#channel] <number> <new text>`")
            return

        parts = number_and_info.split(None, 1)
        if len(parts) < 2:
            await ctx.send("Usage: `.info edit [#channel] <number> <new text>`\nYou must provide both a number and the new text.")
            return

        try:
            idx = int(parts[0]) - 1
            new_info = parts[1]
        except ValueError:
            await ctx.send("Invalid info number. Please provide a valid integer.")
            return

        infos = guild_data["infos"][channel_id]
        if 0 <= idx < len(infos):
            old_info = infos[idx]
            infos[idx] = new_info
            save_guild_data(ctx.guild.id, guild_data)
            embed = success_embed(
                title="Info Updated",
                description=(
                    f"**Channel:** {channel.mention}\n"
                    f"**Entry #{idx + 1}**\n"
                    f"**Old:** {old_info}\n"
                    f"**New:** {new_info}"
                ),
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Invalid info number. {channel.name} has {len(infos)} entr{'y' if len(infos) == 1 else 'ies'}.")

    async def info_reset(self, ctx, guild_data):
        embedq = info_embed(
            title="Confirm you want to reset all infos",
            description="Click a button to confirm or cancel.",
        )
        confirm_view = View(timeout=60)

        async def confirm_callback(interaction):
            if interaction.user == ctx.author:
                guild_data["infos"] = {}
                save_guild_data(ctx.guild.id, guild_data)
                embedy = success_embed(
                    title="Confirmed",
                    description="All infos have been reset.",
                )
                await interaction.response.edit_message(embed=embedy, view=None)
            else:
                await interaction.response.send_message("You can't confirm this action.", ephemeral=True)

        async def cancel_callback(interaction):
            if interaction.user == ctx.author:
                embedn = error_embed(
                    title="Canceled",
                    description="Reset canceled.",
                )
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


async def setup(bot):
    await bot.add_cog(Infos(bot))