import discord
from discord import app_commands
from discord.ext import commands
import random
from typing import Optional

class RPSView(discord.ui.View):
    def __init__(self, author_id: int, opponent_id: int, author_choice: Optional[str] = None, opponent_choice: Optional[str] = None):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.opponent_id = opponent_id
        self.author_choice = author_choice
        self.opponent_choice = opponent_choice
        self.message = None
        self._update_buttons()
    
    def _update_buttons(self):
        self.clear_items()
        
        if self.author_choice is None and self.opponent_choice is None:
            rock1 = discord.ui.Button(label="Rock", style=discord.ButtonStyle.secondary, emoji="🪨")
            rock1.callback = self.make_callback("rock", self.author_id)
            paper1 = discord.ui.Button(label="Paper", style=discord.ButtonStyle.secondary, emoji="📄")
            paper1.callback = self.make_callback("paper", self.author_id)
            scissors1 = discord.ui.Button(label="Scissors", style=discord.ButtonStyle.secondary, emoji="✂️")
            scissors1.callback = self.make_callback("scissors", self.author_id)
            self.add_item(rock1)
            self.add_item(paper1)
            self.add_item(scissors1)
            
            rock2 = discord.ui.Button(label="Rock", style=discord.ButtonStyle.secondary, emoji="🪨")
            rock2.callback = self.make_callback("rock", self.opponent_id)
            paper2 = discord.ui.Button(label="Paper", style=discord.ButtonStyle.secondary, emoji="📄")
            paper2.callback = self.make_callback("paper", self.opponent_id)
            scissors2 = discord.ui.Button(label="Scissors", style=discord.ButtonStyle.secondary, emoji="✂️")
            scissors2.callback = self.make_callback("scissors", self.opponent_id)
            self.add_item(rock2)
            self.add_item(paper2)
            self.add_item(scissors2)
        elif self.author_choice is None and self.opponent_choice is not None:
            rock1 = discord.ui.Button(label="Rock", style=discord.ButtonStyle.primary, emoji="🪨")
            rock1.callback = self.make_callback("rock", self.author_id)
            paper1 = discord.ui.Button(label="Paper", style=discord.ButtonStyle.primary, emoji="📄")
            paper1.callback = self.make_callback("paper", self.author_id)
            scissors1 = discord.ui.Button(label="Scissors", style=discord.ButtonStyle.primary, emoji="✂️")
            scissors1.callback = self.make_callback("scissors", self.author_id)
            self.add_item(rock1)
            self.add_item(paper1)
            self.add_item(scissors1)
        elif self.opponent_choice is None and self.author_choice is not None:
            rock2 = discord.ui.Button(label="Rock", style=discord.ButtonStyle.primary, emoji="🪨")
            rock2.callback = self.make_callback("rock", self.opponent_id)
            paper2 = discord.ui.Button(label="Paper", style=discord.ButtonStyle.primary, emoji="📄")
            paper2.callback = self.make_callback("paper", self.opponent_id)
            scissors2 = discord.ui.Button(label="Scissors", style=discord.ButtonStyle.primary, emoji="✂️")
            scissors2.callback = self.make_callback("scissors", self.opponent_id)
            self.add_item(rock2)
            self.add_item(paper2)
            self.add_item(scissors2)
    
    def make_callback(self, choice, player_id):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != player_id:
                await interaction.response.send_message("This isn't your move!", ephemeral=True)
                return
            if player_id == self.author_id and self.author_choice is not None:
                await interaction.response.send_message("You already made your choice!", ephemeral=True)
                return
            if player_id == self.opponent_id and self.opponent_choice is not None:
                await interaction.response.send_message("You already made your choice!", ephemeral=True)
                return
            
            if player_id == self.author_id:
                self.author_choice = choice
            else:
                self.opponent_choice = choice
            
            self._update_buttons()
            
            if self.author_choice and self.opponent_choice:
                result_embed = self.get_result_embed()
                await interaction.response.edit_message(embed=result_embed, view=self)
                self.stop()
            else:
                embed = self.get_status_embed()
                await interaction.response.edit_message(embed=embed, view=self)
        return callback
    
    def get_status_embed(self):
        embed = discord.Embed(title="Rock Paper Scissors", color=0x9b59b6)
        author = self.message.guild.get_member(self.author_id) if self.message and self.message.guild else None
        opponent = self.message.guild.get_member(self.opponent_id) if self.message and self.message.guild else None
        a_name = author.display_name if author else f"Player 1"
        o_name = opponent.display_name if opponent else f"Player 2"
        
        if self.author_choice and not self.opponent_choice:
            embed.description = f"**{a_name}** has chosen!\n\n**{o_name}**, it's your turn - pick Rock, Paper, or Scissors below."
        elif self.opponent_choice and not self.author_choice:
            embed.description = f"**{o_name}** has chosen!\n\n**{a_name}**, it's your turn - pick Rock, Paper, or Scissors below."
        else:
            embed.description = f"**{a_name}** vs **{o_name}**\n\nBoth players pick below. Choices are hidden until both pick!"
        embed.set_footer(text="Choices are hidden until both players have picked")
        return embed
    
    def get_result_embed(self):
        author = self.message.guild.get_member(self.author_id) if self.message and self.message.guild else None
        opponent = self.message.guild.get_member(self.opponent_id) if self.message and self.message.guild else None
        a_name = author.display_name if author else f"Player 1"
        o_name = opponent.display_name if opponent else f"Player 2"
        
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        a_choice = self.author_choice
        o_choice = self.opponent_choice
        
        embed = discord.Embed(title="Rock Paper Scissors - Results", color=0x2ecc71)
        embed.add_field(name=f"{a_name}", value=f"{emojis[a_choice]} {a_choice.title()}", inline=True)
        embed.add_field(name="vs", value="⚔️", inline=True)
        embed.add_field(name=f"{o_name}", value=f"{emojis[o_choice]} {o_choice.title()}", inline=True)
        
        if a_choice == o_choice:
            embed.description = "**It's a tie!**"
            embed.color = 0xf1c40f
        elif (a_choice == "rock" and o_choice == "scissors") or \
             (a_choice == "paper" and o_choice == "rock") or \
             (a_choice == "scissors" and o_choice == "paper"):
            embed.description = f"**{a_name} wins!**"
            embed.color = 0x2ecc71
        else:
            embed.description = f"**{o_name} wins!**"
            embed.color = 0xe74c3c
        
        return embed

class RPSCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="rps")
    async def rps(self, ctx, opponent: discord.Member = None):
        if opponent is None:
            await ctx.send("You need to challenge someone! Usage: `.rps @user`", ephemeral=True)
            return
        if opponent.bot:
            await ctx.send("You can't challenge a bot!", ephemeral=True)
            return
        if opponent.id == ctx.author.id:
            await ctx.send("You can't challenge yourself!", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Rock Paper Scissors",
            description=f"**{ctx.author.display_name}** vs **{opponent.display_name}**\n\nBoth players pick below. Choices are hidden until both pick!",
            color=0x9b59b6
        )
        embed.set_footer(text="Choices are hidden until both players have picked")
        
        view = RPSView(ctx.author.id, opponent.id)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

async def setup(bot):
    await bot.add_cog(RPSCog(bot))
