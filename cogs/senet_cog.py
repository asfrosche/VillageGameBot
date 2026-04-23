import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import io
import random
import asyncio
from typing import Optional, Dict, List, Tuple
import json
import os
from datetime import datetime
import requests

def get_stick_animation_frames() -> list:
    """Generate frames for throw animation"""
    frames = [
        "🎲 Rolling... ⚫⚫⚫⚫",
        "🎲 Rolling... ⚪⚫⚫⚫",
        "🎲 Rolling... ⚫⚪⚫⚫",
        "🎲 Rolling... ⚫⚫⚪⚫",
        "🎲 Rolling... ⚫⚫⚫⚪",
        "🎲 Rolling... ⚪⚪⚫⚫",
        "🎲 Rolling... ⚫⚪⚪⚫",
        "🎲 Rolling... ⚪⚫⚪⚫",
    ]
    return frames

class SenetGame:
    """Class to manage a single Senet game"""
    
    def __init__(self, player1: discord.User, player2: discord.User):
        self.player1 = player1
        self.player2 = player2
        self.current_player = player1
        
        # Board: 30 squares (3x10)
        # 0 = empty, 1 = player 1 piece, 2 = player 2 piece
        self.board = [0] * 30
        
        # Alternating starting positions
        for i in range(5):
            self.board[i * 2] = 1  # Player 1
            self.board[i * 2 + 1] = 2  # Player 2
        
        self.last_roll = 0
        self.game_over = False
        self.winner = None
        
        # Pieces that have exited the board
        self.player1_escaped = 0
        self.player2_escaped = 0
        
        # Special squares
        self.special_squares = {
            14: "House of Rebirth",     # House 15
            25: "House of Beauty",      # House 26 (safe)
            26: "House of Waters",      # House 27 (returns to 15)
            27: "House of Three Truths", # House 28 (exact roll of 3)
            28: "House of Ra-Atum",     # House 29 (exact roll of 2)
            29: "House of Horus"        # House 30 (exact roll of 1)
        }
    
    def roll_sticks(self) -> int:
        """Roll the 4 sticks to determine movement"""
        sticks = [random.choice([0, 1]) for _ in range(4)]
        white_count = sum(sticks)
        
        # Stick rules
        if white_count == 0:
            return 5  # All black = 5
        else:
            return white_count
    
    def get_valid_moves(self, player: discord.User, roll: int) -> List[int]:
        """Get all valid moves for the current player"""
        player_num = 1 if player == self.player1 else 2
        valid_moves = []
        
        for pos in range(30):
            if self.board[pos] == player_num:
                new_pos = pos + roll
                
                # Check valid movement
                if new_pos < 30:
                    # Cannot land on own piece
                    if self.board[new_pos] != player_num:
                        # House 26 is protected
                        if new_pos == 25 and self.board[new_pos] != 0:
                            continue
                        valid_moves.append(pos)
                elif new_pos >= 30:
                    # Can only exit from last 5 houses with exact roll
                    if pos >= 25:
                        if new_pos == 30 or (pos == 29 and roll == 1) or \
                           (pos == 28 and roll == 2) or (pos == 27 and roll == 3):
                            valid_moves.append(pos)
        
        return valid_moves
    
    def move_piece(self, from_pos: int, player: discord.User) -> str:
        """Move a piece and return the result"""
        player_num = 1 if player == self.player1 else 2
        roll = self.last_roll
        new_pos = from_pos + roll
        
        message = ""
        
        if new_pos >= 30:
            # Piece exits the board
            self.board[from_pos] = 0
            if player_num == 1:
                self.player1_escaped += 1
            else:
                self.player2_escaped += 1
            message = f"🏆 Piece exited the board!"
            
            # Check for victory
            if self.player1_escaped == 5:
                self.game_over = True
                self.winner = self.player1
            elif self.player2_escaped == 5:
                self.game_over = True
                self.winner = self.player2
        else:
            # Normal movement
            opponent = 2 if player_num == 1 else 1
            
            # Capture opponent piece
            if self.board[new_pos] == opponent:
                # Swap positions (except house 26)
                if new_pos != 25:
                    self.board[from_pos] = opponent
                    message = f"⚔️ Opponent piece captured!"
            else:
                self.board[from_pos] = 0
            
            self.board[new_pos] = player_num
            
            # Special square effects
            if new_pos == 26 and self.board[15]==0:
                self.board[new_pos] = 0
                self.board[14] = player_num
                message += f"\n💧 House of Waters! You return to the House of Rebirth!"
            elif self.board[15]!=0:
                i = 0
                while self.board[i] != 0:
                    i += 1
        
        return message
    
    def switch_turn(self):
        """Switch turn"""
        self.current_player = self.player2 if self.current_player == self.player1 else self.player1

class SenetRenderer:
    """Class for rendering the Senet board"""
    
    def __init__(self, cache_dir: str = "senet_cache"):
        self.scale_factor = 2
        self.cell_size = 80 * self.scale_factor
        self.board_width = 10 * self.cell_size
        self.board_height = 3 * self.cell_size
        self.margin = 60 * self.scale_factor
        
        # Egyptian theme colors
        self.colors = {
            'background': (255, 255, 255),      # White
            'board': (222, 184, 135),        # Sand
            'border': (139, 90, 43),         # Brown
            'special': (255, 215, 0),         # Gold
            'player1': (30, 144, 255),       # Blue
            'player2': (220, 20, 60),        # Red
            'text': (64, 48, 32),             # Dark brown
            'shadow': (0, 0, 0, 128)         # Shadow
        }
        
        self.init_assets()
        self.base_board_cache = None
        self.piece_cache = {}
    
    def init_assets(self):
        """Initialize or download necessary assets"""
        import os
        from pathlib import Path
        
        try:
            # Standard fonts - use system fonts or default
            try:
                # Try to load common system fonts
                # Windows
                if os.name == 'nt':
                    self.font_large = ImageFont.truetype("arial.ttf", 24 * self.scale_factor)
                    self.font_medium = ImageFont.truetype("arial.ttf", 18 * self.scale_factor)
                    self.font_small = ImageFont.truetype("arial.ttf", 14 * self.scale_factor)
                else:
                    # Linux/Mac - try common fonts
                    font_paths = [
                        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        "/System/Library/Fonts/Helvetica.ttc",
                    ]
                    font_found = False
                    for font_path in font_paths:
                        if os.path.exists(font_path):
                            self.font_large = ImageFont.truetype(font_path, 24 * self.scale_factor)
                            self.font_medium = ImageFont.truetype(font_path, 18 * self.scale_factor)
                            self.font_small = ImageFont.truetype(font_path, 14 * self.scale_factor)
                            font_found = True
                            break
                    
                    if not font_found:
                        raise Exception("No system font found")
                        
            except Exception as e:
                print(f"System fonts not found, using default: {e}")
                # Use PIL default font
                self.font_large = ImageFont.load_default()
                self.font_medium = ImageFont.load_default()
                self.font_small = ImageFont.load_default()
            
            # Egyptian font (optional)
            try:
                cog_dir = Path(__file__).parent
                main_dir = cog_dir.parent
                font_path = main_dir / "NotoSansEgyptianHieroglyphs-Regular.ttf"
                
                if font_path.exists():
                    self.font_hieroglyph = ImageFont.truetype(str(font_path), 36 * self.scale_factor)
                else:
                    print(f"Egyptian font not found (optional): {font_path}")
                    self.font_hieroglyph = None
                    
            except Exception as e:
                print(f"Egyptian font not available (optional): {e}")
                self.font_hieroglyph = None

            # Papyrus font for numbers (optional)
            try:
                cog_dir = Path(__file__).parent
                main_dir = cog_dir.parent
                papyrus_path = main_dir / "papyrus.ttf"
                
                if papyrus_path.exists():
                    self.font_papyrus = ImageFont.truetype(str(papyrus_path), 20 * self.scale_factor)
                else:
                    print(f"Papyrus font not found, using default for numbers")
                    self.font_papyrus = self.font_small
                    
            except Exception as e:
                print(f"Papyrus font not available: {e}")
                self.font_papyrus = self.font_small
                
        except Exception as e:
            print(f"Font initialization error, using defaults: {e}")
            self.font_large = ImageFont.load_default()
            self.font_medium = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
            self.font_hieroglyph = None

        # Initialize hieroglyphs even if font is not available
        self.hieroglyphs = {
            14: "𓊖",  # House 15 - Rebirth
            25: "𓄤",  # House 26 - Beauty  
            26: "𓈗",  # House 27 - Waters
            27: "𓊽",  # House 28 - Three Truths
            28: "𓇳",  # House 29 - Ra-Atum
            29: "𓅃"   # House 30 - Horus
        }
    
    def create_base_board(self) -> Image.Image:
        """Create the base board (cacheable)"""
        if self.base_board_cache:
            return self.base_board_cache.copy()
        
        # Image with margins
        img_width = self.board_width + 2 * self.margin
        img_height = self.board_height + 2 * self.margin
        img = Image.new('RGB', (img_width, img_height), self.colors['background'])
        draw = ImageDraw.Draw(img)
        
        # Main board
        draw.rectangle([
            self.margin,
            self.margin,
            self.margin + self.board_width,
            self.margin + self.board_height
        ], fill=self.colors['board'], outline=self.colors['border'], width=3 * self.scale_factor)
        
        # Draw the grid
        for row in range(3):
            for col in range(10):
                x = self.margin + col * self.cell_size
                y = self.margin + row * self.cell_size
                
                # Cell borders
                draw.rectangle([x, y, x + self.cell_size, y + self.cell_size],
                             outline=self.colors['border'], width=2 * self.scale_factor)
                
                # Square numbering (snake pattern)
                if row == 0:  # First row: 1-10
                    square_num = col
                elif row == 1:  # Second row: 11-20 (reversed)
                    square_num = 19 - col
                else:  # Third row: 21-30
                    square_num = 20 + col
                
                # Special squares with hieroglyphs
                if square_num in self.hieroglyphs:
                    # Gold background for special squares
                    draw.rectangle([x+2, y+2, x+self.cell_size-2, y+self.cell_size-2],
                                 fill=self.colors['special'])
                    
                    # Thick border like other squares
                    draw.rectangle([x, y, x + self.cell_size, y + self.cell_size],
                                 outline=self.colors['border'], width=2 * self.scale_factor)
                    
                    # Hieroglyph
                    if self.font_hieroglyph:
                        text = self.hieroglyphs[square_num]
                        bbox = draw.textbbox((0, 0), text, font=self.font_hieroglyph)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        draw.text((x + (self.cell_size - text_width) // 2,
                                y + (self.cell_size - text_height) // 2 - 5),
                                text, fill=self.colors['text'], font=self.font_hieroglyph)
                
                # Square number with Papyrus font
                num_text = str(square_num + 1)
                draw.text((x + 10, y + 10), num_text, 
                         fill=self.colors['text'], font=self.font_papyrus)
        
        # Decorative outer border
        border_offset = 5 * self.scale_factor
        border_width = 4 * self.scale_factor
        draw.rectangle([
            self.margin - border_offset,
            self.margin - border_offset,
            self.margin + self.board_width + border_offset,
            self.margin + self.board_height + border_offset
        ], outline=self.colors['border'], width=border_width)

        # Resize with high quality (antialiasing)
        final_width = img_width // self.scale_factor
        final_height = img_height // self.scale_factor
        img = img.resize((final_width, final_height), Image.Resampling.LANCZOS)
        
        # Apply slight sharpening to improve clarity
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.2)
        
        self.base_board_cache = img
        return img.copy()
    
    def draw_piece(self, draw: ImageDraw, x: int, y: int, player: int, img: Image.Image):
        """Draw a piece using the cached image"""
        piece_img = self.get_piece_image(player)
        
        # Calculate position to center the piece in the cell (correct scale)
        piece_size = 60
        cell_size_final = self.cell_size // self.scale_factor
        piece_x = x // self.scale_factor + (cell_size_final - piece_size) // 2
        piece_y = y // self.scale_factor + (cell_size_final - piece_size) // 2
        
        # Paste the piece image on the board
        img.paste(piece_img, (piece_x, piece_y), piece_img)
    
    def get_piece_image(self, player: int) -> Image.Image:
        """Get piece image from cache or create it"""
        if player not in self.piece_cache:
            # Create piece image with transparency
            size_hd = 120 * self.scale_factor
            piece_img = Image.new('RGBA', (size_hd, size_hd), (0, 0, 0, 0))
            draw = ImageDraw.Draw(piece_img, 'RGBA')
            
            color = self.colors['player1'] if player == 1 else self.colors['player2']
            radius = 50 * self.scale_factor
            center = size_hd // 2
            
            # Piece shadow (larger and more visible)
            shadow_offset = 6
            shadow_radius = radius + 4 * self.scale_factor
            draw.ellipse([
                center - shadow_radius + shadow_offset * self.scale_factor,
                center - shadow_radius + shadow_offset * self.scale_factor,
                center + shadow_radius + shadow_offset * self.scale_factor,
                center + shadow_radius + shadow_offset * self.scale_factor
            ], fill=(0, 0, 0, 100))
            
            # Main piece
            draw.ellipse([
                center - radius,
                center - radius,
                center + radius,
                center + radius
            ], fill=color, outline=self.colors['border'], width=2 * self.scale_factor)
            
            # Symbol on piece (larger and centered)
            symbol = "♔" if player == 1 else "♕"
            try:
                # Use larger font for symbols
                symbol_font = ImageFont.truetype("arial.ttf" if os.name == 'nt' else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 56 * self.scale_factor)
                bbox = draw.textbbox((0, 0), symbol, font=symbol_font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                # Correct vertical offset for better centering
                draw.text((center - text_width // 2, center - text_height // 2 - 4 * self.scale_factor),
                         symbol, fill='white', font=symbol_font, stroke_width=2 * self.scale_factor, stroke_fill=self.colors['border'])
            except:
                # Fallback with larger default font
                try:
                    bbox = draw.textbbox((0, 0), symbol, font=self.font_large)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    draw.text((center - text_width // 2, center - text_height // 2 - 4 * self.scale_factor),
                             symbol, fill='white', font=self.font_large)
                except:
                    pass
            
            # Apply antialiasing with superior quality
            piece_img = piece_img.resize((60, 60), Image.Resampling.LANCZOS)
            # Sharpen to improve symbol clarity
            enhancer = ImageEnhance.Sharpness(piece_img)
            piece_img = enhancer.enhance(1.5)
            self.piece_cache[player] = piece_img
        
        return self.piece_cache[player].copy()

    def render_board(self, game: SenetGame) -> io.BytesIO:
        """Render the current state of the board"""
        # Start from the cached base board
        img = self.create_base_board()
        
        # Draw the pieces
        for row in range(3):
            for col in range(10):
                if row == 0:
                    square_num = col
                elif row == 1:
                    square_num = 19 - col
                else:
                    square_num = 20 + col
                
                if game.board[square_num] != 0:
                    x = self.margin + col * self.cell_size
                    y = self.margin + row * self.cell_size
                    # MODIFIED: pass img as parameter
                    self.draw_piece(None, x, y, game.board[square_num], img)
        
        draw = ImageDraw.Draw(img)
        
        # Convert to bytes
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG', optimize=True)
        img_byte_arr.seek(0)
        
        return img_byte_arr

class SenetCog(commands.Cog):
    """Cog for playing Senet on Discord"""
    
    def __init__(self, bot):
        self.bot = bot
        self.games: Dict[int, SenetGame] = {}
        self.renderer = SenetRenderer()
        self.invites: Dict[int, Tuple[discord.User, discord.User]] = {}
    
    @commands.group(name='senet', help='Commands for the Senet game')
    async def senet(self, ctx):
        """Senet command group"""
        if ctx.invoked_subcommand is None:
            await ctx.send('Use `.senet help` to see all commands!')
    
    @senet.command(name='help')
    async def senet_help(self, ctx):
        """Show help for the Senet game"""
        embed = discord.Embed(
            title="🏺 **SENET - The Ancient Egyptian Game** 🏺",
            description="Play the ancient game of the Pharaohs!",
            color=0xff3fb9
        )
        
        embed.add_field(
            name="📜 Main Commands",
            value=(
                "`.senet challenge @user` - Challenge a player\n"
                "`.senet accept` - Accept a challenge\n"
                "`.senet roll` - Roll the sticks\n"
                "`.senet move <number>` - Move piece from square\n"
                "`.senet status` - Show current board\n"
                "`.senet forfeit` - Forfeit the game\n"
                "`.senet rules` - Show complete rules"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🎯 Objective",
            value="Get all your 5 pieces off the board!",
            inline=False
        )
        
        embed.add_field(
            name="🎲 Sticks",
            value=(
                "• 1 white = move 1\n"
                "• 2 white = move 2\n"
                "• 3 white = move 3\n"
                "• 4 white = move 4\n"
                "• 0 white = move 5 + roll again!"
            ),
            inline=True
        )
        
        embed.add_field(
            name="✨ Special Squares",
            value=(
                "• **15**: House of Rebirth\n"
                "• **26**: House of Beauty (safe)\n"
                "• **27**: House of Waters (returns to 15)\n"
                "• **28-30**: Exact roll needed to exit"
            ),
            inline=True
        )
        
        await ctx.send(embed=embed)

    @senet.command(name='skip', aliases=['passo', 'switch'])
    async def skip(self, ctx):
        if ctx.channel.id not in self.games:
            await ctx.send("❌ There is no game in progress!")
            return
        game = self.games[ctx.channel.id]
        if ctx.author != game.player1 and ctx.author != game.player2:
            await ctx.send("❌ You are not participating in this game!")
            return
        embed = discord.Embed(
            title="🐸 turn skipped",
            description=f"{ctx.author.mention} has skipped his turn.",
            color=ffff00
            )
        game.last_roll = 0
        game.switch_turn()
        await ctx.send(embed=embed)

    @senet.command(name='challenge', aliases=['sfida'])
    async def challenge(self, ctx, opponent: discord.Member):
        """Challenge another player"""
        if opponent == ctx.author:
            await ctx.send("❌ You cannot challenge yourself!")
            return
        
        if opponent.bot:
            await ctx.send("❌ You cannot challenge a bot!")
            return
        
        if ctx.channel.id in self.games:
            await ctx.send("❌ There is already a game in progress in this channel!")
            return
        
        self.invites[ctx.channel.id] = (ctx.author, opponent)
        
        embed = discord.Embed(
            title="⚔️ Senet Challenge!",
            description=f"{opponent.mention}, {ctx.author.mention} has challenged you to Senet!\n"
                       f"Type `.senet accept` to accept the challenge!",
            color=0xff3fb9
        )
        embed.set_footer(text="Challenge expires in 60 seconds")
        
        await ctx.send(embed=embed)
        
        # Challenge timeout
        await asyncio.sleep(60)
        if ctx.channel.id in self.invites:
            del self.invites[ctx.channel.id]
            await ctx.send("⏰ The challenge has expired!")
    
    @senet.command(name='accept', aliases=['accetta'])
    async def accept(self, ctx):
        """Accept a challenge"""
        if ctx.channel.id not in self.invites:
            await ctx.send("❌ There are no active challenges in this channel!")
            return
        
        challenger, challenged = self.invites[ctx.channel.id]
        
        if ctx.author != challenged:
            await ctx.send("❌ This challenge is not for you!")
            return
        
        # Start the game
        game = SenetGame(challenger, challenged)
        self.games[ctx.channel.id] = game
        del self.invites[ctx.channel.id]
        
        embed = discord.Embed(
            title="🎮 Game Started!",
            description=f"**{challenger.mention}** (🔵) VS **{challenged.mention}** (🔴)",
            color=0xff3fb9
        )
        embed.add_field(name="First turn", value=f"{challenger.mention}, use `.senet roll` to start!")
        
        # Generate and send the initial board
        board_image = self.renderer.render_board(game)
        file = discord.File(board_image, filename="senet_board.png")
        embed.set_image(url="attachment://senet_board.png")
        
        await ctx.send(embed=embed, file=file)
    
    @senet.command(name='roll', aliases=['lancia'])
    async def roll(self, ctx):
        """Roll the sticks"""
        if ctx.channel.id not in self.games:
            await ctx.send("❌ There is no game in progress! Use `.senet challenge @user`")
            return
        
        game = self.games[ctx.channel.id]
        
        if ctx.author != game.current_player:
            await ctx.send(f"❌ It's not your turn! It's {game.current_player.mention}'s turn")
            return
        
        if game.last_roll != 0:
            await ctx.send("❌ You already rolled! Use `.senet move <number>` to move a piece")
            return
        
        # NEW: Roll animation
        animation_frames = get_stick_animation_frames()
        animation_msg = await ctx.send(animation_frames[0])
        
        # Show animation
        for frame in animation_frames[1:]:
            await asyncio.sleep(0.3)  # Pause between frames
            await animation_msg.edit(content=frame)
        
        await asyncio.sleep(0.5)  # Pause before result
        
        # Roll the sticks
        roll = game.roll_sticks()
        game.last_roll = roll
        
        # Emoji for final sticks
        sticks_visual = ""
        if roll == 5:
            sticks_visual = "⚫⚫⚫⚫"
            extra = " (all black = 5) 🎉 Roll again after moving!"
        elif roll == 4:
            sticks_visual = "⚪⚪⚪⚪"
            extra = " 🎉 Roll again after moving!"
        elif roll == 3:
            sticks_visual = "⚪⚪⚪⚫"
            extra = ""
        elif roll == 2:
            sticks_visual = "⚪⚪⚫⚫"
            extra = ""
        else:
            sticks_visual = "⚪⚫⚫⚫"
            extra = " 🎉 Roll again after moving!"
        
        # Delete animation message and show result
        await animation_msg.delete()
        
        # Find valid moves
        valid_moves = game.get_valid_moves(ctx.author, roll)
        
        embed = discord.Embed(
            title=f"🎲 Stick Roll",
            description=f"{sticks_visual}\n**Result: {roll}**{extra}",
            color=0xff3fb9
        )
        
        if valid_moves:
            moves_str = ", ".join([str(m+1) for m in valid_moves])
            embed.add_field(
                name="Available moves",
                value=f"You can move from squares: **{moves_str}**\n"
                    f"Use `.senet move <number>` to move",
                inline=False
            )
        else:
            embed.add_field(
                name="❌ No valid moves!",
                value="You cannot move any piece. Turn passes to opponent.",
                inline=False
            )
            game.last_roll = 0
            game.switch_turn()
        
        await ctx.send(embed=embed)
    
    @senet.command(name='move', aliases=['muovi'])
    async def move(self, ctx, position: int):
        """Move a piece from the specified position"""
        if ctx.channel.id not in self.games:
            await ctx.send("❌ There is no game in progress!")
            return
        
        game = self.games[ctx.channel.id]
        
        if ctx.author != game.current_player:
            await ctx.send(f"❌ It's not your turn! It's {game.current_player.mention}'s turn")
            return
        
        if game.last_roll == 0:
            await ctx.send("❌ You must roll the sticks first! Use `.senet roll`")
            return
        
        # Convert to 0-based index
        position -= 1
        
        if position < 0 or position >= 30:
            await ctx.send("❌ Invalid position! Squares range from 1 to 30")
            return
        
        valid_moves = game.get_valid_moves(ctx.author, game.last_roll)
        
        if position not in valid_moves:
            moves_str = ", ".join([str(m+1) for m in valid_moves])
            await ctx.send(f"❌ Invalid move! You can only move from squares: {moves_str}")
            return
        
        # Execute the move
        result = game.move_piece(position, ctx.author)
        
        # Prepare result embed
        embed = discord.Embed(
            title="🎮 Move Executed!",
            description=f"{ctx.author.mention} moved from square **{position+1}**",
            color=0xff3fb9
        )
        
        if result:
            embed.add_field(name="Result", value=result, inline=False)
        
        # Check for victory
        if game.game_over:
            embed.add_field(
                name="🏆 VICTORY! 🏆",
                value=f"**{game.winner.mention} won the game!**\n"
                      f"All pieces have exited the board!",
                inline=False
            )
            del self.games[ctx.channel.id]
        else:
            # Handle next turn
            bonus_roll = game.last_roll in [1, 4, 5]
            
            if bonus_roll:
                embed.add_field(
                    name="🎉 Bonus Roll!",
                    value=f"{ctx.author.mention}, you can roll again!",
                    inline=False
                )
            else:
                game.switch_turn()
                embed.add_field(
                    name="Next turn",
                    value=f"{game.current_player.mention}, use `.senet roll`",
                    inline=False
                )
            
            game.last_roll = 0
        
        # Generate and send the updated board
        board_image = self.renderer.render_board(game)
        file = discord.File(board_image, filename="senet_board.png")
        embed.set_image(url="attachment://senet_board.png")
        
        await ctx.send(embed=embed, file=file)
    
    @senet.command(name='status', aliases=['stato', 'board'])
    async def status(self, ctx):
        """Show the current state of the board"""
        if ctx.channel.id not in self.games:
            await ctx.send("❌ There is no game in progress!")
            return
        
        game = self.games[ctx.channel.id]
        
        embed = discord.Embed(
            title="📊 Game Status",
            color=0xff3fb9
        )
        
        embed.add_field(
            name="Players",
            value=f"🔵 {game.player1.mention}: {game.player1_escaped}/5 pieces exited\n"
                  f"🔴 {game.player2.mention}: {game.player2_escaped}/5 pieces exited",
            inline=False
        )
        
        embed.add_field(
            name="Current turn",
            value=game.current_player.mention,
            inline=True
        )
        
        if game.last_roll > 0:
            embed.add_field(
                name="Last roll",
                value=game.last_roll,
                inline=True
            )
        
        # Generate and send the board
        board_image = self.renderer.render_board(game)
        file = discord.File(board_image, filename="senet_board.png")
        embed.set_image(url="attachment://senet_board.png")
        
        await ctx.send(embed=embed, file=file)
    
    @senet.command(name='forfeit', aliases=['abbandona', 'quit'])
    async def forfeit(self, ctx):
        """Forfeit the current game"""
        if ctx.channel.id not in self.games:
            await ctx.send("❌ There is no game in progress!")
            return
        
        game = self.games[ctx.channel.id]
        
        if ctx.author != game.player1 and ctx.author != game.player2:
            await ctx.send("❌ You are not participating in this game!")
            return
        
        winner = game.player2 if ctx.author == game.player1 else game.player1
        
        embed = discord.Embed(
            title="🏳️ Game Ended",
            description=f"{ctx.author.mention} has forfeited the game.\n"
                       f"**{winner.mention} wins by forfeit!**",
            color=0xff3fb9
        )
        
        del self.games[ctx.channel.id]
        await ctx.send(embed=embed)
    
    @senet.command(name='rules', aliases=['regole'])
    async def rules(self, ctx):
        """Show complete Senet rules"""
        embed = discord.Embed(
            title="📜 Complete Senet Rules",
            description="Senet is one of the oldest board games in the world, played in Ancient Egypt.",
            color=0xff3fb9
        )
        
        embed.add_field(
            name="🎯 Objective",
            value="Be the first to move all 5 pieces off the board.",
            inline=False
        )
        
        embed.add_field(
            name="🎲 Movement",
            value=(
                "• Roll 4 sticks to determine movement\n"
                "• Pieces move forward following a snake path\n"
                "• You cannot land on your own pieces\n"
                "• You can capture opponent pieces (swap positions)\n"
                "• With 1, 4, or 5 you get a bonus roll!"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🏛️ Special Squares",
            value=(
                "**House 15 - Rebirth**: Return point from House 27\n"
                "**House 26 - Beauty**: Protected, cannot be captured\n"
                "**House 27 - Waters**: Landing here returns you to House 15\n"
                "**Houses 28-30**: Exact rolls (3, 2, 1) needed to exit"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🏁 Exiting the Board",
            value=(
                "• Pieces can only exit from the last 5 squares\n"
                "• Exact roll or higher is needed\n"
                "• From houses 28-30 EXACT roll is required"
            ),
            inline=False
        )
        
        embed.set_footer(text="Good luck, may the gods favor you! 🏺")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(SenetCog(bot))