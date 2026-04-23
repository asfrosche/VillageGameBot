import discord
from discord.ext import commands, tasks
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
import io
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set
import math

EMBED_COLOR = 0xff3fb9

class Team:
    def __init__(self, team_id: int, default_color: str, default_name: str):
        self.team_id = team_id
        self.name = default_name
        self.color = default_color
        self.soldiers = 30
        self.total_attacks = 0
        self.attacks = {}  # {target_team_id: count}
        self.defenses = set()  # {team_id}
        self.ready = False
        self.actions_confirmed = False
        self.eliminated = False
        self.members = set()
        
    def reset_round_actions(self):
        self.attacks = {}
        self.defenses = set()
        self.actions_confirmed = False

class GameState:
    def __init__(self, guild_id: int, category_id: int, players_per_team: int):
        self.guild_id = guild_id
        self.category_id = category_id
        self.players_per_team = players_per_team
        self.teams: Dict[int, Team] = {}
        self.started = False
        self.round_number = 0
        self.round_start_time = None
        self.announcement_channel_id = None
        self.board_channel_id = None
        self.team_channels = {}  # {team_id: channel_id}
        self.team_roles = {}  # {team_id: role_id}
        self.game_ended = False
        self.stopped = False
        self.setup_message_id = None
        
    def get_alive_teams(self) -> List[Team]:
        return [t for t in self.teams.values() if not t.eliminated]

class BoardActionView(discord.ui.View):
    def __init__(self, cog, guild_id: int, user_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        
        # Menu per selezionare l'azione
        self.action_select = discord.ui.Select(
            placeholder="Pick an action...",
            options=[
                discord.SelectOption(label="⚔️ Attack", value="attack", emoji="⚔️"),
                discord.SelectOption(label="🛡️ Defend", value="defend", emoji="🛡️"),
                discord.SelectOption(label="❌ Cancel Action", value="cancel", emoji="❌"),
                discord.SelectOption(label="✅ Confirm", value="confirm", emoji="✅"),
            ]
        )
        self.action_select.callback = self.action_callback
        self.add_item(self.action_select)
    
    async def action_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ You can't use this menu.", ephemeral=True)
            return
        
        game = self.cog.games.get(self.guild_id)
        if not game or not game.started:
            await interaction.response.send_message("❌ There isn't any ongoing game.", ephemeral=True)
            return
        
        team = self.cog.get_user_team(self.guild_id, interaction.user.id)
        if not team or team.eliminated:
            await interaction.response.send_message("❌ You can't do any more action.", ephemeral=True)
            return
        
        action = self.action_select.values[0]
        
        if action == "confirm":
            await self.handle_confirm(interaction, game, team)
        elif action == "cancel":
            await self.handle_cancel_menu(interaction, game, team)
        elif action == "attack":
            await self.handle_target_menu(interaction, game, team, "attack")
        elif action == "defend":
            await self.handle_target_menu(interaction, game, team, "defend")
    
    async def handle_confirm(self, interaction: discord.Interaction, game, team):
        if team.actions_confirmed:
            await interaction.response.send_message("✅ Already confirmed!", ephemeral=True)
            return
        
        team.actions_confirmed = True
        total = sum(team.attacks.values()) + len(team.defenses)
        
        alive_teams = game.get_alive_teams()
        confirmed_teams = [t for t in alive_teams if t.actions_confirmed]
        
        await interaction.response.send_message(
            f"✅ Actions confirmed! ({total}/6)\n⏳ Waiting... ({len(confirmed_teams)}/{len(alive_teams)})",
            ephemeral=True
        )
        
        annunci = interaction.guild.get_channel(game.announcement_channel_id)
        if annunci:
            await annunci.send(f"✅ **{team.name}** confirmed! ({len(confirmed_teams)}/{len(alive_teams)})")
        
        if all(t.actions_confirmed for t in alive_teams):
            await self.cog.end_round(interaction.guild, game)
    
    async def handle_cancel_menu(self, interaction: discord.Interaction, game, team):
        actions = []
        
        for target_id in team.attacks.keys():
            target_team = game.teams[target_id]
            actions.append(discord.SelectOption(
                label=f"Attack to {target_team.name}",
                value=f"attack_{target_id}",
                emoji="⚔️"
            ))
        
        for def_id in team.defenses:
            def_team = game.teams[def_id]
            actions.append(discord.SelectOption(
                label=f"Difnd from {def_team.name}",
                value=f"defend_{def_id}",
                emoji="🛡️"
            ))
        
        if not actions:
            await interaction.response.send_message("❌ You don't have any action to cancel.", ephemeral=True)
            return
        
        if team.actions_confirmed:
            await interaction.response.send_message("❌ You already confirmed your actions. You can't cancel anymore.", ephemeral=True)
            return
        
        view = CancelActionView(self.cog, self.guild_id, self.user_id, team, actions)
        await interaction.response.send_message("Pick the action to cancel:", view=view, ephemeral=True)
    
    async def handle_target_menu(self, interaction: discord.Interaction, game, team, action_type: str):
        if team.actions_confirmed:
            await interaction.response.send_message("❌ You already confirmed.", ephemeral=True)
            return
        
        total = sum(team.attacks.values()) + len(team.defenses)
        if total >= 6:
            await interaction.response.send_message("❌ Actions limit reached.", ephemeral=True)
            return
        
        alive_teams = game.get_alive_teams()
        options = []
        
        for t in alive_teams:
            if t.team_id == team.team_id:
                continue
            
            if action_type == "attack":
                if t.team_id in team.attacks:
                    continue
                emoji = "⚔️"
                label = f"Attack {t.name}"
            else:  # defend
                if t.team_id in team.defenses:
                    continue
                emoji = "🛡️"
                label = f"Defend from {t.name}"
            
            options.append(discord.SelectOption(
                label=label,
                value=str(t.team_id),
                emoji=emoji
            ))
        
        if not options:
            if action_type == "attack":
                await interaction.response.send_message("❌ There are no teams to attack.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ There are no teams you can defend from.", ephemeral=True)
            return
        
        view = TargetSelectView(self.cog, self.guild_id, self.user_id, team, action_type, options)
        
        if action_type == "attack":
            msg = "Pick the team you want to attack:"
        else:
            msg = "Pick the team you want to defend from:"
        
        await interaction.response.send_message(msg, view=view, ephemeral=True)

class TargetSelectView(discord.ui.View):
    def __init__(self, cog, guild_id: int, user_id: int, team, action_type: str, options):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.team = team
        self.action_type = action_type
        
        self.target_select = discord.ui.Select(
            placeholder="Pick a team...",
            options=options
        )
        self.target_select.callback = self.target_callback
        self.add_item(self.target_select)
    
    async def target_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ You can't use this menu.", ephemeral=True)
            return
        
        game = self.cog.games.get(self.guild_id)
        if not game:
            await interaction.response.send_message("❌ Game not found.", ephemeral=True)
            return
        
        target_id = int(self.target_select.values[0])
        target_team = game.teams[target_id]
        
        if self.action_type == "attack":
            self.team.attacks[target_id] = 1
            await interaction.response.send_message(
                f"⚔️ Attack to **{target_team.name}** registered!",
                ephemeral=True
            )
        else:  # defend
            self.team.defenses.add(target_id)
            await interaction.response.send_message(
                f"🛡️ Defense from **{target_team.name}** registered!",
                ephemeral=True
            )

class CancelActionView(discord.ui.View):
    def __init__(self, cog, guild_id: int, user_id: int, team, options):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.team = team
        
        self.cancel_select = discord.ui.Select(
            placeholder="Pick the action to cancel...",
            options=options
        )
        self.cancel_select.callback = self.cancel_callback
        self.add_item(self.cancel_select)
    
    async def cancel_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ You can't use this menu.", ephemeral=True)
            return
        
        game = self.cog.games.get(self.guild_id)
        if not game:
            await interaction.response.send_message("❌ Game not found.", ephemeral=True)
            return
        
        action_value = self.cancel_select.values[0]
        action_parts = action_value.split("_")
        action_type = action_parts[0]
        target_id = int(action_parts[1])
        
        target_team = game.teams[target_id]
        
        if action_type == "attack":
            if target_id in self.team.attacks:
                del self.team.attacks[target_id]
                await interaction.response.send_message(
                    f"✅ Attack to **{target_team.name}** cancelled!",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Action not found.", ephemeral=True)
        else:  # defend
            if target_id in self.team.defenses:
                self.team.defenses.remove(target_id)
                await interaction.response.send_message(
                    f"✅ Defense from **{target_team.name}** cancelled!",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Action not found.", ephemeral=True)

class SoldatiGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games: Dict[int, GameState] = {}
        self.check_round_timer.start()
        
    def cog_unload(self):
        self.check_round_timer.cancel()
        
    @commands.hybrid_command(name="soldiers")
    async def soldati_command(self, ctx, action: str, *, arg: Optional[str] = None):
        """Comandi per il gioco Soldati"""
        action = action.lower()
        
        if action == "initialize":
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ Only administrators can initialize the game.")
                return
            
            players_per_team = 3
            if arg:
                try:
                    players_per_team = int(arg)
                    if players_per_team < 1 or players_per_team > 10:
                        await ctx.send("❌ Number of players must be between 1 and 10.")
                        return
                except:
                    await ctx.send("❌ Invalid number of players.")
                    return
            
            await self.initialize_game(ctx, players_per_team)
            
        elif action == "stop":
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ Only administrators can stop the game.")
                return
            await self.stop_game(ctx)
            
        elif action == "help":
            await self.show_help(ctx)
            
        elif action == "color":
            await self.set_color(ctx, arg)
            
        elif action == "name":
            await self.set_name(ctx, arg)
            
        elif action == "ready":
            await self.team_ready(ctx)
            
        elif action == "board":
            await self.show_board_interactive(ctx)
            
        else:
            await ctx.send("❌ Command not found. Use `.soldiers help` to get a list of all commands.")
    
    async def stop_game(self, ctx):
        """Ferma completamente il gioco"""
        game = self.games.get(ctx.guild.id)
        if not game:
            await ctx.send("❌ There isn't any ongoing game in this server.")
            return
        
        game.stopped = True
        game.game_ended = True
        
        annunci = ctx.guild.get_channel(game.announcement_channel_id)
        if annunci:
            embed = discord.Embed(
                title="🛑 GAME STOPPED",
                description="An administrator stopped the game.\n"
                           "Channels and roles won't be automatically deleted.",
                color=discord.Color(EMBED_COLOR)
            )
            await annunci.send(embed=embed)
        
        await ctx.send("✅ Game stopped! Channels and roles won't be automatically deleted.")
    
    async def show_help(self, ctx):
        """Mostra la lista dei comandi"""
        game = self.games.get(ctx.guild.id)
        
        admin_commands = (
            "**📋 Admin Commands:**\n"
            "• `.soldiers initialize [num]` - Initialize the game\n"
            "• `.soldiers stop` - Stop the game\n"
        )
        
        if not game:
            embed = discord.Embed(
                title="❓ Soldiers Commands",
                description=f"{admin_commands}\n"
                           "💡 *No active game at the moment. Use `.soldiers initialize` to start a game!*",
                color=discord.Color(EMBED_COLOR)
            )
            await ctx.send(embed=embed)
            return
        
        if not game.started:
            setup_commands = (
                "**🎮 Setup Commands:**\n"
                "• Buttons in announcement channel to Join/Leave\n"
                "• `.soldiers color #HEXCOLOR` - Change your team color\n"
                "• `.soldiers name NAME` - Change your team name\n"
                "• `.soldiers ready` - Mark as ready to start\n"
            )
            
            embed = discord.Embed(
                title="❓ Soldiers Commands - Setup",
                description=f"{admin_commands}\n{setup_commands}",
                color=discord.Color(EMBED_COLOR)
            )
        else:
            game_commands = (
                "**⚔️ Game Commands:**\n"
                "• `.soldiers board` - Interactive Board\n"
                "  (use the menu to attack, defend, confirm actions)\n"
            )
            
            embed = discord.Embed(
                title="❓ Soldiers Commands - In Game",
                description=f"{admin_commands}\n{game_commands}\n\n"
                           "**📖 Rules:**\n"
                           "• Every action uses 1 soldier\n"
                           "• Successful Attack: kills 3 soldiers of the attacked team\n"
                           "• Every 3 attacks: +1 bonus soldier\n"
                           "• Turn: 10 minutes or all team confirmation",
                color=discord.Color(EMBED_COLOR)
            )
        
        await ctx.send(embed=embed)
    
    async def initialize_game(self, ctx, players_per_team: int):
        if ctx.guild.id in self.games:
            await ctx.send("❌ There is an ongoing game. Use `.soldiers stop` to stop it.")
            return
            
        category = await ctx.guild.create_category("🎮 Soldiers")
        
        default_colors = ["#FF6B35", "#4ECDC4", "#FFD93D", "#A855F7"]
        default_names = ["T1", "T2", "T3", "T4"]
        roles = {}
        
        for i in range(4):
            role = await ctx.guild.create_role(
                name=f"Team {i+1}",
                color=discord.Color(int(default_colors[i][1:], 16)),
                mentionable=True
            )
            roles[i] = role
        
        overwrites_readonly = {
            ctx.guild.default_role: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=False
            )
        }
        
        annunci_channel = await category.create_text_channel(
            "📢-announcements",
            overwrites=overwrites_readonly
        )
        
        board_channel = await category.create_text_channel(
            "📊-board",
            overwrites=overwrites_readonly
        )
        
        team_channels = {}
        for i in range(4):
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                ),
                roles[i]: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True
                )
            }
            
            channel = await category.create_text_channel(
                f"team-{i+1}",
                overwrites=overwrites
            )
            team_channels[i] = channel
        
        game = GameState(ctx.guild.id, category.id, players_per_team)
        game.announcement_channel_id = annunci_channel.id
        game.board_channel_id = board_channel.id
        
        for i in range(4):
            team = Team(i, default_colors[i], default_names[i])
            game.teams[i] = team
            game.team_roles[i] = roles[i].id
            game.team_channels[i] = team_channels[i].id
        
        self.games[ctx.guild.id] = game
        
        embed = self.create_setup_embed(game)
        view = JoinTeamView(self, ctx.guild.id)
        message = await annunci_channel.send(embed=embed, view=view)
        game.setup_message_id = message.id
        
        await ctx.send(f"✅ Game initialized! Go in {annunci_channel.mention}")
    
    def create_setup_embed(self, game: GameState) -> discord.Embed:
        teams_info = ""
        for i in range(4):
            team = game.teams[i]
            members_count = len(team.members)
            emoji = "✅" if team.ready else "⏳"
            teams_info += f"{emoji} **Team {i+1}**: {members_count}/{game.players_per_team} players\n"
        
        embed = discord.Embed(
            title="🎮 Soldiers Game - Join!",
            description=f"Press on buttons to Join or Leave!\n"
                       f"Max **{game.players_per_team}** players per team.\n\n"
                       f"{teams_info}\n"
                       f"**Commands:**\n"
                       f"• `.soldiers color #HEX` - Change Team Color\n"
                       f"• `.soldiers name NAME` - Change Team Name\n"
                       f"• `.soldiers ready` - Mark As Ready\n\n"
                       f"🎯 Game starts when all teams are ready!",
            color=discord.Color(EMBED_COLOR)
        )
        return embed
    
    async def update_setup_embed(self, guild: discord.Guild, game: GameState):
        if not game.setup_message_id or game.started:
            return
        
        annunci = guild.get_channel(game.announcement_channel_id)
        if not annunci:
            return
        
        try:
            message = await annunci.fetch_message(game.setup_message_id)
            embed = self.create_setup_embed(game)
            await message.edit(embed=embed)
        except:
            pass
    
    async def set_color(self, ctx, color: str):
        if not color:
            await ctx.send("❌ Use: `.soldiers color #HEXCOLOR` (ex. `.soldiers color #FF3FB9`)")
            return
            
        game = self.games.get(ctx.guild.id)
        if not game:
            await ctx.send("❌ There isn't any ongoing game.")
            return
        
        if game.started:
            await ctx.send("❌ Game already started.")
            return
            
        team = self.get_user_team(ctx.guild.id, ctx.author.id)
        if not team:
            await ctx.send("❌ You're not in a team.")
            return
        
        if not color.startswith("#") or len(color) != 7:
            await ctx.send("❌ Invalid format! Use #RRGGBB")
            return
            
        try:
            int(color[1:], 16)
            team.color = color.upper()
            await ctx.send(f"✅ Color Changed: **{color.upper()}**")
        except:
            await ctx.send("❌ Invalid format.")
    
    async def set_name(self, ctx, name: str):
        if not name:
            await ctx.send("❌ Use: `.soldiers name NAME`")
            return
            
        game = self.games.get(ctx.guild.id)
        if not game:
            await ctx.send("❌ There isn't any ongoing game.")
            return
        
        if game.started:
            await ctx.send("❌ Game already started.")
            return
            
        team = self.get_user_team(ctx.guild.id, ctx.author.id)
        if not team:
            await ctx.send("❌ You're not in a team.")
            return
        
        if len(name) > 20:
            await ctx.send("❌ 20 characters max")
            return
        
        if len(name) < 2:
            await ctx.send("❌ 2 characters min")
            return
            
        team.name = name
        await ctx.send(f"✅ Name Changed: **{name}**")
    
    async def team_ready(self, ctx):
        game = self.games.get(ctx.guild.id)
        if not game:
            await ctx.send("❌ There isn't any ongoing game.")
            return
        
        if game.started:
            await ctx.send("❌ Game already started.")
            return
            
        team = self.get_user_team(ctx.guild.id, ctx.author.id)
        if not team:
            await ctx.send("❌ You're not in a team.")
            return
        
        if len(team.members) == 0:
            await ctx.send("❌ Team is empty.")
            return
        
        if team.ready:
            await ctx.send("✅ Ready!")
            return
            
        team.ready = True
        await ctx.send(f"✅ **{team.name}** is ready!")
        await self.update_setup_embed(ctx.guild, game)
        
        teams_with_members = [t for t in game.teams.values() if len(t.members) > 0]
        if len(teams_with_members) < 2:
            await ctx.send("⏳ 2 Teams minimum!")
            return
        
        if all(t.ready for t in teams_with_members):
            await self.start_game(ctx.guild, game)
    
    async def start_game(self, guild: discord.Guild, game: GameState):
        game.started = True
        
        for team_id, team in game.teams.items():
            if len(team.members) == 0:
                team.eliminated = True
                continue
                
            role = guild.get_role(game.team_roles[team_id])
            channel = guild.get_channel(game.team_channels[team_id])
            
            if role:
                await role.edit(
                    name=team.name,
                    color=discord.Color(int(team.color[1:], 16))
                )
            if channel:
                await channel.edit(name=team.name.lower().replace(" ", "-"))
        
        annunci = guild.get_channel(game.announcement_channel_id)
        if annunci:
            alive_teams = game.get_alive_teams()
            teams_str = "\n".join([f"**{t.name}**" for t in alive_teams])
            
            embed = discord.Embed(
                title="⚔️ GAME STARTED!",
                description=f"**Teams:**\n{teams_str}\n\n"
                           "**Each team starts with 30 soldiers.**\n\n"
                           "**Commands:**\n"
                           "• `.soldiers board` - Interactive board\n"
                           "  (use menus to handle your actions)\n\n"
                           "**Rules:**\n"
                           "• Every action uses 1 soldier\n"
                           "• Successful attack: kills 3 soldiers of the attacked team\n"
                           "• Every 3 total attacks: +1 bonus soldier\n"
                           "• Turn: 10 minutes or all team confirmation\n\n"
                           "**Good Luck! ⚔️**",
                color=discord.Color(EMBED_COLOR)
            )
            await annunci.send(embed=embed)
        
        await self.start_round(guild, game)
    
    async def start_round(self, guild: discord.Guild, game: GameState):
        if game.stopped or game.game_ended:
            return
            
        game.round_number += 1
        game.round_start_time = datetime.now()
        
        for team in game.teams.values():
            team.reset_round_actions()
        
        annunci = guild.get_channel(game.announcement_channel_id)
        if annunci:
            alive_teams = game.get_alive_teams()
            teams_str = "\n".join([
                f"**{t.name}**: {t.soldiers} soldiers" 
                for t in alive_teams
            ])
            
            # Menzioni FUORI dall'embed
            mentions = " ".join([
                f"<@&{game.team_roles[t.team_id]}>" 
                for t in alive_teams
            ])
            
            embed = discord.Embed(
                title=f"🎯 Round {game.round_number}",
                description=f"**Soldiers:**\n{teams_str}\n\n"
                           f"⏰ **10 minutes** to pick!\n"
                           f"Use `.soldiers board` to handle your actions.",
                color=discord.Color(EMBED_COLOR)
            )
            await annunci.send(content=mentions, embed=embed)
    
    async def show_board_interactive(self, ctx):
        """Mostra il tabellone con menu interattivi"""
        game = self.games.get(ctx.guild.id)
        if not game:
            await ctx.send("❌ There isn't any ongoing game.")
            return
        
        if not game.started:
            await ctx.send("❌ Game didn't start yet.")
            return
        
        if game.game_ended or game.stopped:
            await ctx.send("❌ Game ended.")
            return
            
        team = self.get_user_team(ctx.guild.id, ctx.author.id)
        if not team or team.eliminated:
            # Mostra solo il tabellone senza azioni
            await self.show_board_only(ctx, game)
            return
        
        # Crea l'embed con le informazioni
        alive_teams = game.get_alive_teams()
        teams_str = "\n".join([
            f"**{t.name}**: {t.soldiers} soldiers 🪖" 
            for t in alive_teams
        ])
        
        # Azioni correnti
        actions_str = ""
        for target_id in team.attacks.keys():
            target_team = game.teams[target_id]
            actions_str += f"⚔️ Attack to **{target_team.name}**\n"
        
        for def_id in team.defenses:
            def_team = game.teams[def_id]
            actions_str += f"🛡️ Difense fron **{def_team.name}**\n"
        
        if not actions_str:
            actions_str = "*No Actions*"
        
        total = sum(team.attacks.values()) + len(team.defenses)
        status_icon = "✅" if team.actions_confirmed else "⏳"
        status_text = "Confirmed" if team.actions_confirmed else "Not confirmed"
        
        embed = discord.Embed(
            title=f"📊 Board - Round {game.round_number}",
            description=f"**Soldiers:**\n{teams_str}\n\n"
                       f"**Your Actions ({total}/6):**\n{actions_str}\n"
                       f"{status_icon} {status_text}",
            color=discord.Color(int(team.color[1:], 16))
        )
        
        view = BoardActionView(self, ctx.guild.id, ctx.author.id)
        await ctx.send(embed=embed, view=view)
    
    async def show_board_only(self, ctx, game):
        """Mostra solo il tabellone senza azioni (per squadre eliminate)"""
        alive_teams = game.get_alive_teams()
        teams_str = "\n".join([
            f"**{t.name}**: {t.soldiers} soldiers 🪖" 
            for t in alive_teams
        ])
        
        eliminated_teams = [t for t in game.teams.values() if t.eliminated and len(t.members) > 0]
        if eliminated_teams:
            teams_str += "\n\n**Eliminated:**\n"
            teams_str += "\n".join([f"~~{t.name}~~" for t in eliminated_teams])
        
        embed = discord.Embed(
            title=f"📊 Board - Round {game.round_number}",
            description=teams_str,
            color=discord.Color(EMBED_COLOR)
        )
        await ctx.send(embed=embed)
    
    @tasks.loop(seconds=30)
    async def check_round_timer(self):
        for guild_id, game in list(self.games.items()):
            if not game.started or game.game_ended or game.stopped or not game.round_start_time:
                continue
            
            elapsed = (datetime.now() - game.round_start_time).total_seconds()
            
            # Avviso a 1 minuto
            if 540 <= elapsed < 570 and not hasattr(game, 'warned'):
                guild = self.bot.get_guild(guild_id)
                if guild:
                    annunci = guild.get_channel(game.announcement_channel_id)
                    if annunci:
                        alive_teams = game.get_alive_teams()
                        unconfirmed = [t for t in alive_teams if not t.actions_confirmed]
                        if unconfirmed:
                            mentions = " ".join([
                                f"<@&{game.team_roles[t.team_id]}>" 
                                for t in unconfirmed
                            ])
                            await annunci.send(
                                f"⏰ {mentions} **1 Minute left!** ⏰"
                            )
                        game.warned = True
            
            # Fine round a 10 minuti
            if elapsed >= 600:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    await self.end_round(guild, game)
    
    async def end_round(self, guild: discord.Guild, game: GameState):
        if game.stopped or game.game_ended:
            return
            
        if hasattr(game, 'processing_round'):
            return
        game.processing_round = True
        
        # Reset warning flag
        if hasattr(game, 'warned'):
            delattr(game, 'warned')
        
        # Reset round_start_time per evitare loop
        game.round_start_time = None
        
        results = {}
        for team in game.teams.values():
            if team.eliminated:
                continue
                
            actions_cost = sum(team.attacks.values()) + len(team.defenses)
            damage_taken = 0
            
            for attacker in game.teams.values():
                if attacker.eliminated or attacker.team_id == team.team_id:
                    continue
                
                if team.team_id in attacker.attacks:
                    if attacker.team_id not in team.defenses:
                        damage_taken += 3
            
            results[team.team_id] = {
                'actions': actions_cost,
                'damage': damage_taken,
                'total': -(actions_cost + damage_taken)
            }
            
            team.soldiers -= (actions_cost + damage_taken)
            
            team.total_attacks += sum(team.attacks.values())
            bonus_soldiers = team.total_attacks // 3
            old_bonus = (team.total_attacks - sum(team.attacks.values())) // 3
            new_bonus = bonus_soldiers - old_bonus
            
            if new_bonus > 0:
                team.soldiers += new_bonus
                results[team.team_id]['bonus'] = new_bonus
            
            if team.soldiers <= 0:
                team.eliminated = True
                team.soldiers = 0
        
        img = await self.generate_board_image(game)
        
        annunci = guild.get_channel(game.announcement_channel_id)
        board_channel = guild.get_channel(game.board_channel_id)
        
        if annunci:
            result_text = ""
            for team_id, result in results.items():
                team = game.teams[team_id]
                bonus_text = f" (+{result.get('bonus', 0)})" if result.get('bonus', 0) > 0 else ""
                elim_text = " **[ELIMINATED]** 💀" if team.eliminated else ""
                result_text += (
                    f"**{team.name}**: -{result['actions']} actions, "
                    f"-{result['damage']} damages{bonus_text} "
                    f"→ **{team.soldiers}** 🪖{elim_text}\n"
                )
            
            embed = discord.Embed(
                title=f"📊 Round Results {game.round_number}",
                description=result_text,
                color=discord.Color(EMBED_COLOR)
            )
            
            file = discord.File(io.BytesIO(img), filename="board.png")
            embed.set_image(url="attachment://board.png")
            await annunci.send(embed=embed, file=file)
        
        if board_channel and img:
            file = discord.File(io.BytesIO(img), filename="board.png")
            await board_channel.send(file=file)
        
        alive_teams = game.get_alive_teams()
        if len(alive_teams) <= 1:
            await self.end_game(guild, game, alive_teams[0] if alive_teams else None)
        else:
            delattr(game, 'processing_round')
            await self.start_round(guild, game)
    
    async def end_game(self, guild: discord.Guild, game: GameState, winner: Optional[Team]):
        game.game_ended = True
        game.round_start_time = None
        
        annunci = guild.get_channel(game.announcement_channel_id)
        if annunci:
            if winner:
                embed = discord.Embed(
                    title="🏆 VICTORY!",
                    description=f"**{winner.name}** Wins with **{winner.soldiers}** soldiers!\n\n"
                               f"Congratulations! 🎉",
                    color=discord.Color(int(winner.color[1:], 16))
                )
            else:
                embed = discord.Embed(
                    title="⚔️ Game Ended",
                    description="No Winner!",
                    color=discord.Color(EMBED_COLOR)
                )
            
            await annunci.send(embed=embed)
            
            if not game.stopped:
                await annunci.send("🗑️ Category will be deleted in 2 hours...")
        
        if not game.stopped:
            await asyncio.sleep(7200)
            await self.cleanup_game(guild, game)
    
    async def cleanup_game(self, guild: discord.Guild, game: GameState):
        if game.stopped:
            return
            
        category = guild.get_channel(game.category_id)
        
        if category:
            for channel in category.channels:
                try:
                    await channel.delete()
                except:
                    pass
            
            try:
                await category.delete()
            except:
                pass
        
        for role_id in game.team_roles.values():
            role = guild.get_role(role_id)
            if role:
                try:
                    await role.delete()
                except:
                    pass
        
        if guild.id in self.games:
            del self.games[guild.id]
    
    async def generate_board_image(self, game: GameState) -> bytes:
        """Genera l'immagine del tabellone"""
        img = Image.new('RGB', (900, 900), color='#E8D4B8')
        draw = ImageDraw.Draw(img)
        
        # Posizioni squadre
        positions = [
            (100, 100),   # Team 0 - alto sinistra
            (650, 100),   # Team 1 - alto destra
            (100, 650),   # Team 2 - basso sinistra
            (650, 650),   # Team 3 - basso destra
        ]
        
        # Disegna squadre
        for i, team in game.teams.items():
            if team.eliminated and len(team.members) == 0:
                continue
                
            x, y = positions[i]
            color = team.color
            
            # Box squadra 150x150
            draw.rectangle([x, y, x+150, y+150], fill=color, outline='black', width=4)
            
            # Nome abbreviato
            abbr = team.name[:2].upper()
            draw.text((x+75, y+75), abbr, fill='black', anchor='mm', 
                     font=ImageFont.load_default().font_variant(size=48))
            
            # Shield bars allungati
            if i == 0:  # Alto sinistra
                shields = [
                    ((x+160, y+50, x+190, y+100), 1),    # destra vs 1 - ALLUNGATO
                    ((x+50, y+160, x+100, y+190), 2),    # sotto vs 2 - ALLUNGATO
                    ((x+160, y+160, x+190, y+190), 3),   # diag vs 3 - più lungo a 45°
                ]
            elif i == 1:  # Alto destra
                shields = [
                    ((x-40, y+50, x-10, y+100), 0),      # sinistra vs 0 - ALLUNGATO
                    ((x+50, y+160, x+100, y+190), 3),    # sotto vs 3 - ALLUNGATO
                    ((x-40, y+160, x-10, y+190), 2),     # diag vs 2 - più lungo a 45°
                ]
            elif i == 2:  # Basso sinistra
                shields = [
                    ((x+50, y-40, x+100, y-10), 0),      # sopra vs 0 - ALLUNGATO
                    ((x+160, y+50, x+190, y+100), 3),    # destra vs 3 - ALLUNGATO
                    ((x+160, y-40, x+190, y-10), 1),     # diag vs 1 - più lungo a 45°
                ]
            else:  # Basso destra (3)
                shields = [
                    ((x+50, y-40, x+100, y-10), 1),      # sopra vs 1 - ALLUNGATO
                    ((x-40, y+50, x-10, y+100), 2),      # sinistra vs 2 - ALLUNGATO
                    ((x-40, y-40, x-10, y-10), 0),       # diag vs 0 - più lungo a 45°
                ]
            
            for (sx1, sy1, sx2, sy2), target_id in shields:
                if target_id in team.defenses:
                    shield_color = color
                else:
                    shield_color = '#DDDDDD'
                
                draw.rectangle([sx1, sy1, sx2, sy2], fill=shield_color, outline='black', width=2)
        
        # Disegna frecce di attacco (SENZA triangolino)
        arrow_configs = [
            # 0-1 (orizzontale alto)
            {'from': 0, 'to': 1, 'start': (260, 165), 'end': (640, 165), 'offset': 10},
            # 0-2 (verticale sinistra)
            {'from': 0, 'to': 2, 'start': (165, 260), 'end': (165, 640), 'offset': 10},
            # 0-3 (diagonale)
            {'from': 0, 'to': 3, 'start': (240, 240), 'end': (660, 660), 'offset': 8},
            # 1-2 (diagonale)
            {'from': 1, 'to': 2, 'start': (660, 240), 'end': (240, 660), 'offset': 8},
            # 1-3 (verticale destra)
            {'from': 1, 'to': 3, 'start': (735, 260), 'end': (735, 640), 'offset': 10},
            # 2-3 (orizzontale basso)
            {'from': 2, 'to': 3, 'start': (260, 735), 'end': (640, 735), 'offset': 10},
        ]
        
        for config in arrow_configs:
            from_team = game.teams[config['from']]
            to_team = game.teams[config['to']]
            
            if from_team.eliminated or to_team.eliminated:
                continue
            
            attack_from_to = config['to'] in from_team.attacks
            attack_to_from = config['from'] in to_team.attacks
            
            if attack_from_to and attack_to_from:
                # Doppio attacco: disegna 2 frecce separate
                offset = config['offset']
                start = config['start']
                end = config['end']
                
                # Calcola offset perpendicolare
                if start[0] == end[0]:  # Verticale
                    start1 = (start[0] - offset, start[1])
                    end1 = (end[0] - offset, end[1])
                    start2 = (start[0] + offset, start[1])
                    end2 = (end[0] + offset, end[1])
                elif start[1] == end[1]:  # Orizzontale
                    start1 = (start[0], start[1] - offset)
                    end1 = (end[0], end[1] - offset)
                    start2 = (start[0], start[1] + offset)
                    end2 = (end[0], end[1] + offset)
                else:  # Diagonale
                    dx = end[0] - start[0]
                    dy = end[1] - start[1]
                    length = (dx**2 + dy**2)**0.5
                    perp_x = -dy / length * offset
                    perp_y = dx / length * offset
                    start1 = (start[0] + perp_x, start[1] + perp_y)
                    end1 = (end[0] + perp_x, end[1] + perp_y)
                    start2 = (start[0] - perp_x, start[1] - perp_y)
                    end2 = (end[0] - perp_x, end[1] - perp_y)
                
                # Disegna linee SENZA freccia
                draw.line([start1, end1], fill=from_team.color, width=6)
                draw.line([end2, start2], fill=to_team.color, width=6)
                
            elif attack_from_to:
                # Linea SENZA freccia
                draw.line([config['start'], config['end']], fill=from_team.color, width=8)
            elif attack_to_from:
                # Linea SENZA freccia
                draw.line([config['end'], config['start']], fill=to_team.color, width=8)
        
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf.getvalue()
    
    def get_user_team(self, guild_id: int, user_id: int) -> Optional[Team]:
        game = self.games.get(guild_id)
        if not game:
            return None
        
        for team in game.teams.values():
            if user_id in team.members:
                return team
        return None
    
    def get_team_by_role(self, game: GameState, role_id: int) -> Optional[Team]:
        for team_id, r_id in game.team_roles.items():
            if r_id == role_id:
                return game.teams[team_id]
        return None

class JoinTeamView(discord.ui.View):
    def __init__(self, cog: SoldatiGame, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        
        for i in range(4):
            button = JoinTeamButton(i, cog, guild_id)
            self.add_item(button)
        
        leave_button = LeaveTeamButton(cog, guild_id)
        self.add_item(leave_button)

class JoinTeamButton(discord.ui.Button):
    def __init__(self, team_id: int, cog: SoldatiGame, guild_id: int):
        super().__init__(
            label=f"Team {team_id + 1}",
            style=discord.ButtonStyle.primary,
            custom_id=f"join_team_{team_id}"
        )
        self.team_id = team_id
        self.cog = cog
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        game = self.cog.games.get(self.guild_id)
        if not game:
            await interaction.response.send_message(
                "❌ Game ended.", ephemeral=True
            )
            return
            
        if game.started:
            await interaction.response.send_message(
                "❌ Game already started. You can't join anymore.", ephemeral=True
            )
            return
        
        # Rimuovi da altre squadre
        for team in game.teams.values():
            if interaction.user.id in team.members:
                if team.team_id == self.team_id:
                    await interaction.response.send_message(
                        "✅ You're already a member of this team!", ephemeral=True
                    )
                    return
                
                team.members.remove(interaction.user.id)
                team.ready = False
                old_role = interaction.guild.get_role(game.team_roles[team.team_id])
                if old_role:
                    await interaction.user.remove_roles(old_role)
        
        # Controlla limite
        team = game.teams[self.team_id]
        if len(team.members) >= game.players_per_team:
            await interaction.response.send_message(
                f"❌ This team is full! ({game.players_per_team}/{game.players_per_team})", 
                ephemeral=True
            )
            return
        
        # Aggiungi alla squadra
        team.members.add(interaction.user.id)
        team.ready = False
        role = interaction.guild.get_role(game.team_roles[self.team_id])
        if role:
            await interaction.user.add_roles(role)
        
        await interaction.response.send_message(
            f"✅ You joined **Team {self.team_id + 1}**! Go in your team channel to personalize it.", 
            ephemeral=True
        )
        
        await self.cog.update_setup_embed(interaction.guild, game)

class LeaveTeamButton(discord.ui.Button):
    def __init__(self, cog: SoldatiGame, guild_id: int):
        super().__init__(
            label="Leave the team",
            style=discord.ButtonStyle.danger,
            custom_id=f"leave_team",
            emoji="🚪"
        )
        self.cog = cog
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        game = self.cog.games.get(self.guild_id)
        if not game:
            await interaction.response.send_message(
                "❌ Game ended.", ephemeral=True
            )
            return
            
        if game.started:
            await interaction.response.send_message(
                "❌ Game already started! You can't leave anymore.", ephemeral=True
            )
            return
        
        # Trova e rimuovi dalla squadra
        found = False
        for team in game.teams.values():
            if interaction.user.id in team.members:
                team.members.remove(interaction.user.id)
                team.ready = False
                role = interaction.guild.get_role(game.team_roles[team.team_id])
                if role:
                    await interaction.user.remove_roles(role)
                found = True
                await interaction.response.send_message(
                    f"✅ Left from **Team {team.team_id + 1}**!", 
                    ephemeral=True
                )
                break
        
        if not found:
            await interaction.response.send_message(
                "❌ You're not in a team yet.", 
                ephemeral=True
            )
            return
        
        await self.cog.update_setup_embed(interaction.guild, game)

async def setup(bot):
    await bot.add_cog(SoldatiGame(bot))