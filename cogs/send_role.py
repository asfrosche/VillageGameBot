import discord
from discord.ext import commands
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FOLDER = os.path.join(BASE_DIR, "db")
DATA_FILE = os.path.join(DB_FOLDER, "target_channels.json")

def load_target_id():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_target_id(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

class SendRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_channels = load_target_id()

    @commands.command()
    async def settarget(self, ctx, channel_id: int):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command.")
            return
        self.target_channels[str(ctx.guild.id)] = channel_id
        save_target_id(self.target_channels)
        await ctx.send(f"Target channel set to {channel_id}")

    @commands.command(aliases=["sr"])
    async def sendrole(self, ctx, *, player: str = None):
        if not ctx.message.reference or not isinstance(ctx.message.reference.resolved, discord.Message):
            await ctx.send("You must reply to the message you want to send.")
            return
        replied_message = ctx.message.reference.resolved
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You need admin permissions in this server to use this command.")
            return
        try:
            guild_id = str(ctx.guild.id)
            if guild_id not in self.target_channels:
                await ctx.send("No target channel set. Use `.settarget #channel` first.")
                return
            target_channel_id = self.target_channels[guild_id]
            target_channel = self.bot.get_channel(target_channel_id)
            if not target_channel:
                await ctx.send("Couldn't find the target channel.")
                return
            target_guild = target_channel.guild
            target_member = target_guild.get_member(ctx.author.id)
            librarian_role_id = 1329517813626310679
            has_admin = target_member.guild_permissions.administrator
            has_librarian_role = any(role.id == librarian_role_id for role in target_member.roles)
            if not (has_admin or has_librarian_role):
                await ctx.send("You need to be an admin or have the 'Librarian' role in the **target server** to use this command.")
                return
            message_to_send = replied_message.content
            if player:
                message_to_send += f"\n\nPlayed by **{player}**"
            if replied_message.attachments:
                files = [await a.to_file() for a in replied_message.attachments]
                await target_channel.send(content=message_to_send, files=files)
            else:
                await target_channel.send(message_to_send)
            await ctx.send(f"Role sent to {target_channel.mention}")
        except Exception as e:
            await ctx.send(f"Error: {e}")