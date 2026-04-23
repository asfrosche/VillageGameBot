# cogs/help.py
import discord
from discord.ext import commands

class HelpCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ghelp(self, ctx):
        """Show available commands"""
        embed = discord.Embed(
            title="🌍 Gentleman Help",
            description="A bot for tracking user locations and managing games",
            color=0x7289da
        )
        
        embed.add_field(
            name="Admin Commands",
            value=( 
                "`.setloc @user <location>`: Set a user's location (Admin only)\n"
                "`.remloc @user`: Remove a user's location (Admin only)\n"
            ),
            inline=False
        )
        
        embed.add_field(
            name="User Commands",
            value=( 
                "`.locations`: Show all user locations grouped by continent/country\n"
                "`.mapp`: Generate interactive map of user locations\n"
                "`.mapheat`: Generate heatmap of user locations\n"
                "`.mysetloc <location>`: Set your own location\n"
                "`.myremoveloc`: Remove your own location\n"
                "`.near [@user]`: Show the 5 closest users to you or someone else\n"
                "`.localtime [@user]`: Show someone's local time\n"
                "`.convert <time> <from> to <to>`: Convert timezones (example: `5pm EST to IST`)\n"
                "`.locstats`: Show stats by country and continent"
            ),
            inline=False
        )

        embed.add_field(
            name="Game Commands",
            value=(
                "`.startgame (or .sg) <max_players> @host [-role <role_name>] <game_name>`: Start a new game\n"
                "`.addplayer (or .ap) <slot_num> @player [game_name]`: Add a player to an empty slot (Admin/host only)\n"
                "`.removeplayer (or .rp) <slot_num> [game_name]`: Remove a player from a slot (Admin/host only)\n"
            ),
            inline=False
        )
        
        embed.add_field(
            name="Aux Battle Commands",
            value=(
                "`.auxbattle signup`: Join the aux battle tournament\n"
                "`.auxbattle submit [song_link]`: Submit a song for the current match\n"
                "`.auxbattle bracket`: View the current tournament bracket\n"
                "`.help_aux`: Show Aux Battle specific commands"
            ),
            inline=False
        )

        await ctx.send(embed=embed)
        
    
    @commands.command(name='help_aux')
    async def help_aux(self, ctx):
        """Display help information for the Aux Battle commands"""
        embed = discord.Embed(
            title="🎵 Aux Battle Help 🎵",
            description="A music tournament where players submit songs that match an image, and others vote for the best match.",
            color=discord.Color.blue()
        )
        
        # Player Commands
        player_commands = [
            "`.auxbattle signup` - Join the aux battle tournament",
            "`.auxbattle submit [song_link]` - Submit a song for the current match",
            "`.auxbattle vote [match_id] [1/2]` - Vote for your favorite song submission",
            "`.auxbattle bracket` - View the current tournament bracket"
        ]
        embed.add_field(name="Player Commands", value="\n".join(player_commands), inline=False)
        
        # Admin Commands
        admin_commands = [
            "`.auxbattle opensignup` - Open registrations for a new tournament",
            "`.auxbattle closesignup` - Close registrations",
            "`.auxbattle start` - Create and start the tournament with signed-up players",
            "`.auxbattle endvoting [match_id]` - End voting for a specific match",
            "`.auxbattle reset` - Reset the entire tournament"
        ]
        embed.add_field(name="Admin Commands", value="\n".join(admin_commands), inline=False)
        
        # How to Play
        how_to_play = [
            "1. Sign up using `.auxbattle signup`",
            "2. Wait for an admin to start the tournament",
            "3. When it's your turn, you'll be shown an image",
            "4. Submit a song that matches the vibe of the image using `.auxbattle submit [song_link]`",
            "5. Everyone votes on which song fits better",
            "6. Winners advance to the next round",
            "7. Last player standing wins!"
        ]
        embed.add_field(name="How to Play", value="\n".join(how_to_play), inline=False)
        
        await ctx.send(embed=embed)