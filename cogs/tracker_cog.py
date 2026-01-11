import discord
from discord.ext import commands
from datetime import datetime, timezone
from discord import Embed

class MessageTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tracked_channel_id = 1446470487676031088
        self.message_counts = {}
        self.tracking_active = True

    @commands.command()
    async def statss(self, ctx):
        if not self.message_counts:
            await ctx.send("No stats available.")
            return
        sorted_message_counts = sorted(self.message_counts.items(), key=lambda x: x[1], reverse=True)
        list_str = []
        for user_id, count in sorted_message_counts:
            user = self.bot.get_user(user_id)
            user_name = f"{user.display_name}" if user else f"User ID {user_id}"
            list_str.append(f"**{user_name}:** {count}")
        embed = discord.Embed(title="📊 Message Stats", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        if len("\n".join(list_str)) > 2000:
            await ctx.send("Message Stats:\n" + "\n".join(list_str))
        else:
            embed.description = "\n".join(list_str)
            await ctx.send(embed=embed)

    @commands.command()
    async def start_tracking(self, ctx):
        if ctx.author.guild_permissions.administrator:
            self.tracking_active = True
            await ctx.send("Message tracking started.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    @commands.command()
    async def stop_tracking(self, ctx):
        if ctx.author.guild_permissions.administrator:
            self.tracking_active = False
            await ctx.send("Message tracking has been paused.")
        else:
            await ctx.send("You don't have enough permissions to use this command")

    @commands.command()
    async def reset_tracking(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command")
            return
        self.message_counts = {}
        await ctx.send("Message tracking stats have been reset.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if (
            message.channel.id == self.tracked_channel_id
            and not message.author.bot
            and self.tracking_active
        ):
            user_id = message.author.id
            if user_id in self.message_counts:
                self.message_counts[user_id] += 1
            else:
                self.message_counts[user_id] = 1