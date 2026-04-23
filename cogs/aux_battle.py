import discord
from discord.ext import commands
import random
import asyncio
import json
import os

class AuxBattle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.participants = []
        self.is_signup_open = False
        self.current_tournament = None
        self.matches = {}
        self.image_urls = [
            # Add some default image URLs or load from a file
            "https://example.com/image1.jpg",
            "https://example.com/image2.jpg",
            # etc.
        ]
        self.voting_timer = 3600*24  # Default 24 hours (in seconds)
        self.submission_timer = 3600*12  # Default 24 hours (in seconds)
        
        # Load data if exists
        self.data_file = "aux_battle_data.json"
        self.load_data()

    def load_data(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.participants = data.get('participants', [])
                    self.matches = data.get('matches', {})
                    self.current_tournament = data.get('current_tournament', None)
                    self.is_signup_open = data.get('is_signup_open', False)
            except Exception as e:
                print(f"Error loading aux battle data: {e}")
    
    def save_data(self):
        data = {
            'participants': self.participants,
            'matches': self.matches,
            'current_tournament': self.current_tournament,
            'is_signup_open': self.is_signup_open
        }
        with open(self.data_file, 'w') as f:
            json.dump(data, f)
    
    @commands.group(name="auxbattle", aliases=["aux"], invoke_without_command=True)
    async def auxbattle(self, ctx):
        """Main command for Aux Battle. Use subcommands for specific actions."""
        await ctx.send("Welcome to Aux Battle! Use `!auxbattle signup` to join the tournament.")
    
    @auxbattle.command(name="signup")
    async def signup(self, ctx):
        """Sign up for the aux battle tournament"""
        if not self.is_signup_open:
            await ctx.send("Signups are currently closed!")
            return
            
        user_id = ctx.author.id
        if user_id in self.participants:
            await ctx.send("You're already signed up for the tournament!")
            return
            
        self.participants.append(user_id)
        self.save_data()
        await ctx.send(f"{ctx.author.mention} has signed up for the Aux Battle tournament!")
    
    @auxbattle.command(name="opensignup")
    @commands.has_permissions(administrator=True)
    async def open_signup(self, ctx):
        """Open signups for a new tournament"""
        self.is_signup_open = True
        self.participants = []
        self.save_data()
        await ctx.send("Aux Battle tournament signups are now open! Use `!auxbattle signup` to join.")
    
    @auxbattle.command(name="closesignup")
    @commands.has_permissions(administrator=True)
    async def close_signup(self, ctx):
        """Close signups and prepare for tournament"""
        if not self.is_signup_open:
            await ctx.send("Signups are already closed!")
            return
            
        self.is_signup_open = False
        self.save_data()
        await ctx.send(f"Signups are now closed! {len(self.participants)} players have registered.")
     
    @auxbattle.command(name="bracket")
    async def show_bracket(self, ctx):
        """Display the current tournament bracket"""
        if not self.current_tournament:
            await ctx.send("No active tournament!")
            return
            
        embed = discord.Embed(title="Aux Battle Tournament Bracket", color=discord.Color.gold())
        
        for round_idx, round_matches in enumerate(self.current_tournament['rounds']):
            round_text = ""
            for match_idx, match_id in enumerate(round_matches):
                match = self.matches[match_id]
                
                # Get player names
                try:
                    player1 = await self.bot.fetch_user(match['player1'])
                    player1_name = player1.name
                except:
                    player1_name = "TBD"
                    
                try:
                    if match['player2']:
                        player2 = await self.bot.fetch_user(match['player2'])
                        player2_name = player2.name
                    else:
                        player2_name = "BYE"
                except:
                    player2_name = "TBD"
                
                # Show winner if match is completed
                if match['status'] == 'completed':
                    winner_name = player1_name if match['winner'] == match['player1'] else player2_name
                    round_text += f"Match {match_idx+1}: {player1_name} vs {player2_name} - Winner: {winner_name}\n"
                else:
                    round_text += f"Match {match_idx+1}: {player1_name} vs {player2_name}\n"
            
            embed.add_field(name=f"Round {round_idx+1}", value=round_text or "No matches", inline=False)
        
        await ctx.send(embed=embed)
    
    @auxbattle.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def reset_tournament(self, ctx):
        """Reset the current tournament"""
        self.current_tournament = None
        self.matches = {}
        self.participants = []
        self.is_signup_open = False
        self.save_data()
        await ctx.send("Tournament has been reset!")

    

    @auxbattle.command(name="start")
    @commands.has_permissions(administrator=True)
    async def start_tournament(self, ctx):
        """Start the tournament and create the bracket"""
        if len(self.participants) < 2:
            await ctx.send("Need at least 2 participants to start a tournament!")
            return
            
        # Shuffle participants for random matchups
        random.shuffle(self.participants)
        
        # Create tournament bracket with support for simultaneous matches
        self.current_tournament = {
            'rounds': [],
            'current_round': 0,
            'active_matches': []  # Replace current_match with a list of active matches
        }
        
        # Create first round matches
        matches = []
        for i in range(0, len(self.participants), 2):
            if i + 1 < len(self.participants):
                match_id = f"r0m{i//2}"
                self.matches[match_id] = {
                    'player1': self.participants[i],
                    'player2': self.participants[i+1],
                    'image': random.choice(self.image_urls),
                    'song1': None,
                    'song2': None,
                    'votes1': 0,
                    'votes2': 0,
                    'winner': None,
                    'status': 'pending'
                }
                matches.append(match_id)
            else:
                # If odd number of participants, give one a bye
                next_round_match_id = f"r1m{i//4}"
                if next_round_match_id not in self.matches:
                    self.matches[next_round_match_id] = {
                        'player1': self.participants[i],
                        'player2': None,
                        'image': None,
                        'song1': None,
                        'song2': None,
                        'votes1': 0,
                        'votes2': 0,
                        'winner': self.participants[i],
                        'status': 'pending'
                    }
        
        self.current_tournament['rounds'].append(matches)
        # Set all matches in the first round as active
        self.current_tournament['active_matches'] = list(range(len(matches)))
        self.save_data()
        
        await ctx.send("Tournament has been created! Use `!auxbattle bracket` to see the matchups.")
        await self.start_all_matches(ctx)

    async def start_match(self, ctx, match_id):
        """Start a specific match"""
        match = self.matches[match_id]
        
        # Get player usernames
        player1 = await self.bot.fetch_user(match['player1'])
        if match['player2']:
            player2 = await self.bot.fetch_user(match['player2'])
        else:
            # Handle bye match
            match['status'] = 'completed'
            self.save_data()
            await self.check_round_completion(ctx)
            return
        
        embed = discord.Embed(title=f"Aux Battle - Match {match_id}", 
                            color=discord.Color.green())
        embed.set_image(url=match['image'])
        embed.add_field(name="Players", value=f"{player1.mention} vs {player2.mention}", inline=False)
        embed.add_field(name="Instructions", 
                    value=f"Submit a song that matches this image using `!auxbattle submit [song_link]`\nYou have {self.submission_timer//60} minutes to submit!", 
                    inline=False)
        
        await ctx.send(embed=embed)
        await ctx.send(f"{player1.mention} and {player2.mention}, please submit your songs for match {match_id}!")

    async def start_all_matches(self, ctx):
        """Start all active matches in the current round simultaneously"""
        if not self.current_tournament:
            await ctx.send("No active tournament!")
            return
            
        current_round = self.current_tournament['current_round']
        
        for match_idx in self.current_tournament['active_matches']:
            if match_idx < len(self.current_tournament['rounds'][current_round]):
                match_id = self.current_tournament['rounds'][current_round][match_idx]
                await self.start_match(ctx, match_id)
        
        # Start submission timer
        await ctx.send(f"Submission phase has begun! All players have {self.submission_timer//60} minutes to submit their songs.")
        
        # Schedule the end of submission phase
        self.bot.loop.create_task(self.end_submission_phase(ctx))

    async def end_submission_phase(self, ctx):
        """End the submission phase after the timer expires"""
        await asyncio.sleep(self.submission_timer)
        
        if not self.current_tournament:
            return
        
        await ctx.send("Submission time has ended! Starting voting phase for all matches.")
        await self.start_all_voting(ctx)

    async def start_voting(self, ctx, match_id):
        """Start voting for a specific match"""
        match = self.matches[match_id]
        
        # Get player usernames
        player1 = await self.bot.fetch_user(match['player1'])
        player2 = await self.bot.fetch_user(match['player2'])
        
        # Create voting embed
        embed = discord.Embed(title=f"Aux Battle - Match {match_id} - VOTE!", 
                            color=discord.Color.blue())
        embed.set_image(url=match['image'])
        embed.add_field(name="Players", value=f"{player1.mention} vs {player2.mention}", inline=False)
        embed.add_field(name="Song 1", value=match['song1'], inline=True)
        embed.add_field(name="Song 2", value=match['song2'], inline=True)
        embed.add_field(name="Instructions", 
                    value="React with 1️⃣ to vote for Song 1\nReact with 2️⃣ to vote for Song 2", 
                    inline=False)
        
        # Send voting message
        vote_msg = await ctx.send(embed=embed)
        
        # Add reaction options
        await vote_msg.add_reaction("1️⃣")
        await vote_msg.add_reaction("2️⃣")
        
        # Store message ID for vote counting
        match['vote_message'] = vote_msg.id
        match['vote_channel'] = ctx.channel.id
        self.save_data()
        
        # Schedule end of voting
        self.bot.loop.create_task(self.end_voting(ctx, match_id))

    async def end_voting(self, ctx, match_id):
        """End voting for a match and determine the winner"""
        await asyncio.sleep(self.voting_timer)
        
        match = self.matches[match_id]
        
        # Skip if match is already completed
        if match['status'] == 'completed':
            return
        
        # Get the vote message
        try:
            channel = self.bot.get_channel(match['vote_channel'])
            vote_msg = await channel.fetch_message(match['vote_message'])
            
            # Count votes
            for reaction in vote_msg.reactions:
                if reaction.emoji == "1️⃣":
                    # Subtract 1 to account for the bot's reaction
                    match['votes1'] = max(0, reaction.count - 1)
                elif reaction.emoji == "2️⃣":
                    match['votes2'] = max(0, reaction.count - 1)
            
            # Determine winner
            player1 = await self.bot.fetch_user(match['player1'])
            player2 = await self.bot.fetch_user(match['player2'])
            
            if match['votes1'] > match['votes2']:
                match['winner'] = match['player1']
                await ctx.send(f"Match {match_id} results: {player1.mention} wins with {match['votes1']} votes vs {match['votes2']} votes!")
            elif match['votes2'] > match['votes1']:
                match['winner'] = match['player2']
                await ctx.send(f"Match {match_id} results: {player2.mention} wins with {match['votes2']} votes vs {match['votes1']} votes!")
            else:
                # In case of a tie, choose randomly
                match['winner'] = random.choice([match['player1'], match['player2']])
                winner = player1 if match['winner'] == match['player1'] else player2
                await ctx.send(f"Match {match_id} resulted in a tie! {winner.mention} wins by random selection!")
            
            match['status'] = 'completed'
            self.save_data()
            
            # Check if round is complete
            await self.check_round_completion(ctx)
        
        except Exception as e:
            await ctx.send(f"Error counting votes for match {match_id}: {e}")

    async def start_all_voting(self, ctx):
        """Start voting for all matches in the current round"""
        if not self.current_tournament:
            return
            
        current_round = self.current_tournament['current_round']
        
        for match_idx in self.current_tournament['active_matches']:
            if match_idx < len(self.current_tournament['rounds'][current_round]):
                match_id = self.current_tournament['rounds'][current_round][match_idx]
                match = self.matches[match_id]
                
                # Skip matches that are already in voting or completed
                if match['status'] in ['voting', 'completed']:
                    continue
                    
                # For matches where one or both players didn't submit, handle accordingly
                if not match['song1'] and match['player2'] is not None:
                    # Player 1 didn't submit, player 2 wins by default
                    match['winner'] = match['player2']
                    match['status'] = 'completed'
                    player2 = await self.bot.fetch_user(match['player2'])
                    await ctx.send(f"Match {match_id}: {player2.mention} wins by default (opponent didn't submit)")
                elif not match['song2'] and match['player1'] is not None:
                    # Player 2 didn't submit, player 1 wins by default
                    match['winner'] = match['player1']
                    match['status'] = 'completed'
                    player1 = await self.bot.fetch_user(match['player1'])
                    await ctx.send(f"Match {match_id}: {player1.mention} wins by default (opponent didn't submit)")
                elif match['song1'] and match['song2']:
                    # Both submitted, start voting
                    match['status'] = 'voting'
                    await self.start_voting(ctx, match_id)
        
        self.save_data()
        
        # Check if any matches need voting
        has_voting_matches = False
        for match_idx in self.current_tournament['active_matches']:
            if match_idx < len(self.current_tournament['rounds'][current_round]):
                match_id = self.current_tournament['rounds'][current_round][match_idx]
                if self.matches[match_id]['status'] == 'voting':
                    has_voting_matches = True
                    break
        
        # If no matches need voting, check if round is complete
        if not has_voting_matches:
            await self.check_round_completion(ctx)

    async def check_all_submissions(self, ctx):
        """Check if all players in the current round have submitted their songs"""
        if not self.current_tournament:
            return
            
        current_round = self.current_tournament['current_round']
        all_submitted = True
        
        for match_idx in self.current_tournament['active_matches']:
            if match_idx < len(self.current_tournament['rounds'][current_round]):
                match_id = self.current_tournament['rounds'][current_round][match_idx]
                match = self.matches[match_id]
                
                # Skip matches with byes
                if match['player2'] is None:
                    continue
                    
                # Check if both players submitted
                if not match['song1'] or not match['song2']:
                    all_submitted = False
                    break
        
        # If all players have submitted, start voting for all matches
        if all_submitted:
            await ctx.send("All players have submitted their songs! Starting voting phase.")
            await self.start_all_voting(ctx)

    async def check_round_completion(self, ctx):
        """Check if the current round is complete and advance to the next round if needed"""
        if not self.current_tournament:
            return
        
        current_round = self.current_tournament['current_round']
        all_completed = True
        
        # Check if all matches in the current round are completed
        for match_idx in self.current_tournament['active_matches']:
            if match_idx < len(self.current_tournament['rounds'][current_round]):
                match_id = self.current_tournament['rounds'][current_round][match_idx]
                if self.matches[match_id]['status'] != 'completed':
                    all_completed = False
                    break
        
        if all_completed:
            # Check if this was the final round
            if current_round == len(self.current_tournament['rounds']) - 1 and len(self.current_tournament['rounds'][current_round]) == 1:
                # Tournament is complete
                final_match_id = self.current_tournament['rounds'][current_round][0]
                final_match = self.matches[final_match_id]
                winner = await self.bot.fetch_user(final_match['winner'])
                
                await ctx.send(f"🏆 **TOURNAMENT COMPLETE!** 🏆\n\nCongratulations to {winner.mention} for winning the Aux Battle Tournament!")
                return
            
            # Create next round matches
            await self.create_next_round(ctx)

    async def create_next_round(self, ctx):
        """Create matches for the next round based on winners of the current round"""
        current_round = self.current_tournament['current_round']
        next_round = current_round + 1
        
        # Get winners from current round
        winners = []
        for match_id in self.current_tournament['rounds'][current_round]:
            match = self.matches[match_id]
            winners.append(match['winner'])
        
        # Create matches for next round
        next_round_matches = []
        for i in range(0, len(winners), 2):
            if i + 1 < len(winners):
                match_id = f"r{next_round}m{i//2}"
                self.matches[match_id] = {
                    'player1': winners[i],
                    'player2': winners[i+1],
                    'image': random.choice(self.image_urls),
                    'song1': None,
                    'song2': None,
                    'votes1': 0,
                    'votes2': 0,
                    'winner': None,
                    'status': 'pending'
                }
                next_round_matches.append(match_id)
            else:
                # If odd number of winners, give one a bye to the next round
                if next_round + 1 < len(self.current_tournament['rounds']):
                    next_next_round_match_id = f"r{next_round+1}m{i//4}"
                    if next_next_round_match_id not in self.matches:
                        self.matches[next_next_round_match_id] = {
                            'player1': winners[i],
                            'player2': None,
                            'image': None,
                            'song1': None,
                            'song2': None,
                            'votes1': 0,
                            'votes2': 0,
                            'winner': winners[i],
                            'status': 'pending'
                        }
                else:
                    # If this is the final round, just add the winner
                    match_id = f"r{next_round}m0"
                    self.matches[match_id] = {
                        'player1': winners[i],
                        'player2': None,
                        'image': None,
                        'song1': None,
                        'song2': None,
                        'votes1': 0,
                        'votes2': 0,
                        'winner': winners[i],
                        'status': 'completed'
                    }
                    next_round_matches.append(match_id)
        
        # Add the new round to the tournament
        if next_round >= len(self.current_tournament['rounds']):
            self.current_tournament['rounds'].append(next_round_matches)
        else:
            self.current_tournament['rounds'][next_round] = next_round_matches
        
        # Update tournament state
        self.current_tournament['current_round'] = next_round
        self.current_tournament['active_matches'] = list(range(len(next_round_matches)))
        self.save_data()
        
        await ctx.send(f"Round {current_round + 1} complete! Starting Round {next_round + 1}...")
        await self.start_all_matches(ctx)

    @auxbattle.command(name="submit")
    async def submit_song(self, ctx, song_link: str):
        """Submit a song for your current match"""
        if not self.current_tournament:
            await ctx.send("No active tournament!")
            return
            
        # Find user's current match
        user_id = ctx.author.id
        current_round = self.current_tournament['current_round']
        
        match_id = None
        for match_idx in self.current_tournament['active_matches']:
            if match_idx < len(self.current_tournament['rounds'][current_round]):
                current_match_id = self.current_tournament['rounds'][current_round][match_idx]
                match = self.matches[current_match_id]
                if user_id == match['player1'] or user_id == match['player2']:
                    match_id = current_match_id
                    break
        
        if not match_id:
            await ctx.send("You're not in any active match!")
            return
            
        # Validate song link (basic check)
        if not ('youtube.com' in song_link or 'youtu.be' in song_link or 
                'spotify.com' in song_link or 'soundcloud.com' in song_link):
            await ctx.send("Please submit a valid music link (YouTube, Spotify, SoundCloud).")
            return
            
        # Store the song
        match = self.matches[match_id]
        if user_id == match['player1']:
            match['song1'] = song_link
            await ctx.send(f"{ctx.author.mention} has submitted their song!")
        else:
            match['song2'] = song_link
            await ctx.send(f"{ctx.author.mention} has submitted their song!")
        
        self.save_data()
        
        # Check if all songs in the round have been submitted
        await self.check_all_submissions(ctx)