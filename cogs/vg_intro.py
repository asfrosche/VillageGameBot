import discord
from discord.ext import commands


MECHANIC_PAGES = {
    1: {
        "title": "What is Hearthside?",
        "image": None,
        "content": """
  🎲  VILLAGE GAMES

  A social deduction server
  running 30-40 player games.

  Inspired by Mafia & Werewolf
  but pushed far beyond.

  • Houses & Visits
  • Lynches & Voting
  • Economy & Shop
  • Unique Custom Roles
  • 50+ iterations

  Every game is unique.
  No two games are the same.

  Also hosts:
  Mafia | Puzzles | Side Events
""",
    },
    2: {
        "title": "Game Structure",
        "image": None,
        "content": """
  ⏳  GAME STRUCTURE

  • ~10 days per game
  • 30-40 players
  • Day/Night cycles (24h each)

  Day — Discuss, accuse, lynch
  Night — Abilities, visits, kills

  Game ends when all players
  have 0% or 100% win chance.
""",
    },
    3: {
        "title": "Teams",
        "image": None,
        "content": """
  🏘️  VILLAGE (majority)
  Wins when they are the
  only team alive.

  ⚔️  EVIL (minority)
  Wins on parity with or
  being the only team alive.

  ❓  OTHER (may not exist)
  Alternative win conditions
  known only to themselves.

  Names may change per theme.
  Concepts stay the same.
""",
    },
    4: {
        "title": "Solo Breakdown",
        "image": None,
        "content": """
  🤷  NEUTRAL
  Keep head down.
  Reach wincon quietly.

  💀  KILLER (RK)
  Last player standing.
  Your win = everyone dies.

  ⚖️  SOLO TEAM
  Balance the game.
  Strike at the end.

  You are your own faction.
""",
    },
    5: {
        "title": "Day Phase",
        "image": None,
        "content": """
  ☀️  Discuss / Accuse / Vote

  24 hours to talk,
  push suspects,
  and lynch someone.

  📣  Megaphone
  1 message per 6 hours
  so key posts aren't lost.

Voting closes 30 min
before day ends.

Day abilities exist
but most activate at Night.
""",
    },
    6: {
        "title": "Night Phase",
        "image": None,
        "content": """
  🌙  Abilities | Visits | Kills

  24 hours where most
  role actions happen.

  🏠  House channel
  Where you live. Night
  actions target you here.

  📜  Role channel
  Your role card + description.
  Ping Overseers with
  questions here.

Most abilities are
Night-only unless
specified otherwise.
""",
    },
    7: {
        "title": "Houses & Visits",
        "image": None,
        "content": """
  🏠  Every player owns a house.

  Visit others:
    [knock] or [barge]
        |
    TARGET HOUSE

  Max 3 owners per house.
  Owner must approve entry.

  ⚠️  Homeless at night = death
  at end of night, unless your
  house was destroyed without
  warning near end of night
  (you may seek a new one).

  Special locations cannot
  override other special
  locations.

  1 visit/night by default.
  Roles may grant more.
  Returning home is free.
""",
    },
    8: {
        "title": "Visit Types & Priority",
        "image": None,
        "content": """
  [REGULAR] 🚪 Knock -> owner
  opens -> you enter.
  Default for all roles.

  [FORCED]  💥 Barge in without
  knocking (role must
  allow this).

  [STEALTH] 👤 Move without
  narration. Hidden
  arrival.

  [PRIORITY]
  Visits are lowest priority
  in presets. Owner's door
  open/close presets win.

End of night: back to
your own house (free).
""",
    },
    9: {
        "title": "Regions & Locations",
        "image": None,
        "content": """
  🗺️  REGIONS
  Split players into groups.
  Affect abilities, info,
  travel, and interactions.

  📍  SPECIAL LOCATIONS
  Role-tied places, lore
  areas, mechanical zones.

Read the game-specific
mechanics channel before
each game for details.
""",
    },
    10: {
        "title": "Ability Categories",
        "image": None,
        "content": """
  🗡️  LETHAL
    Attacks, bleeds, kills
  🚫  BLOCK
    Visitblock, roleblock, category block
  🎭  MANIPULATION
    Visit control, fake narrations, role control
  💊  CURING
    Cures, revives, immunities
  🛡️  PROTECTION
    Shields, death delays
  📡  INFO & COMMS
    Checks, public/private chats, tracking
  🌐  MOBILITY
    Teleports, pulls
  ✨  SUPPORT
    Buffs, visit grant, refills
  ❓  OTHER
    Anything else

A role can have multiple
ability types.
""",
    },
    11: {
        "title": "How Abilities Work",
        "image": None,
        "content": """
  🤝  PHYSICAL
    Must visit target in person.
  📡  REMOTE
    Use by player name.
  🏠  REMOTE-HOUSE
    Need player name + house number.
  🏘️  HOUSE
    Targets a house itself (remote
    or physical).

Your role card specifies
which type clearly.
""",
    },
    12: {
        "title": "Fakeclaiming",
        "image": None,
        "content": """
  🎭  If you are Evil or Solo,
  you MUST make a fake claim.

  A good fakeclaim:
  • Stays consistent
  • Sounds useful
  • Blends into village plans
  • Mixes in real abilities
  • Gets you trusted

  Credibility = currency.

  Don't sacrifice yourself
  unless it helps the team.
""",
    },
    13: {
        "title": "Evil Strategy",
        "image": None,
        "content": """
  ☠️  Gain trust first.
  • Look useful
  • Push with logic
  • Vote with village
  • Be in plans

  🎯  Coordination
  Sync kills on strong
  villagers (medics,
  protectors, info roles,
  utilities).

  Keep weak players
  alive as scapegoats.

  💬  Framing
  Accuse with reason.
  No logic = you become
  the suspect.

  Sometimes let a teammate
  die for your credibility.
""",
    },
    14: {
        "title": "Rules & Tips",
        "image": None,
        "content": """
  🚫  FORBIDDEN
  • Screenshots of private channels
  • Copy-pasted role text
  • Sharing role channel contents

  ✅  You MAY describe your
  role in your own words.

  ❓  ASK OVERSEERS
  • Mechanics questions
  • Role clarification
  • Anything unclear

  ⚡  ALWAYS
  • Read game mechanics channel
  • Trust carefully
  • Speak carefully
  • Visit carefully
""",
    },
    15: {
        "title": "Economy",
        "image": None,
        "content": """
  💰  ECONOMY

  🏪  SHOP
  Buy items with effects.

  Commands:
  • `$bal`     — Check balance
  • `$give`    — Give money to a player
    (must be in the same house
     physically)

Items from the shop have
various effects.

Money transfers require
you to be physically in
the same house.
""",
    },
    16: {
        "title": "Glossary: Roles & Channels",
        "image": None,
        "content": """
  📖  GLOSSARY

  ROLES
  OS — Overseer. Moderators.
  spec — Spectator. Watching.
  rk — Random Killer. Goal is
       last man standing.
  el — Evil Leader. Evil with
       huge impact.
  tk — Town Killer. Villager
       with killing potential.
  med — Medium. Revive ability.
  vills — Villagers.

  CHANNELS
  ec — Evil Chat. For evils.
       Not in every game.
  pc — Private Chat. Only
       players inside can read.
  rc — Rolechannel. For actions
       and OS communication.
""",
    },
    17: {
        "title": "Glossary: Phases & Abilities",
        "image": None,
        "content": """
  📖  GLOSSARY

  PHASES
  eod — end of day
  eon — end of night
  oag — once a game
  n1/d1/v1/h1 — Night/Day/
       Vote/House 1

  ABILITIES
  abi — Ability (active/passive)
  vb — Visit Block. Can't visit.
  rb — Role Block. Can't use
       Active abilities.
  prots — Protections. Blocks
       following attack.
  rev — Revive. Bring back
       dead players.
  gs — Green Seer. Checks
       a player's category.

  OTHER
  rc — Rolecard. Your role info.
       Also Rolechannel (actions).
  cred — Credibility.
  nar — Narration (kill msgs).
  mechs — Mechanics.
  wincon — Win condition.
  corr — Corrupted.
  poe — Process of elimination.
  recog — Recognition. 
       Evil team (usually) finding each other
  dory — Player loses all active abilities and usually passives too.
       Only visits and vote left.
""",
    },
}


MECHANIC_PAGES_IT = {
    1: {
        "title": "Cos'è The Village?",
        "image": None,
        "content": """
  🎲  VILLAGE GAMES

  Un server di deduzione sociale
  con partite da 30-40 giocatori.

  Ispirato a Mafia & Lupo Mannaro
  ma portato ben oltre.

  • Case & Visite
  • Linciaggi & Votazioni
  • Economia & Negozio
  • Ruoli Personalizzati Unici
  • 50+ iterazioni

  Ogni partita è unica.
  Non esistono due partite uguali.

  Ospita anche:
  Mafia | Puzzle | Eventi Collaterali
""",
    },
    2: {
        "title": "Struttura di Gioco",
        "image": None,
        "content": """
  ⏳  STRUTTURA DI GIOCO

  • ~10 giorni per partita
  • 30-40 giocatori
  • Cicli Giorno/Notte (24h ciascuno)

  Giorno — Discuti, accusa, lincia
  Notte — Abilità, visite, uccisioni

  La partita finisce quando tutti
  i giocatori hanno 0% o 100%
  di probabilità di vincita.
""",
    },
    3: {
        "title": "Team",
        "image": None,
        "content": """
  🏘️  VILLAGGIO (maggioranza)
  Vince quando è l'unico
  team sopravvissuto.

  ⚔️  MALVAGIO (minoranza)
  Vince alla parità o
  come unico team rimasto.

  ❓  ALTRO (potrebbe non esistere)
  Condizioni di vittoria
  alternative note solo a loro.

  I nomi possono cambiare per tema.
  I concetti restano uguali.
""",
    },
    4: {
        "title": "Categoria Solitaria",
        "image": None,
        "content": """
  🤷  NEUTRAL
  Tieni un profilo basso.
  Raggiungi la wincon in silenzio.

  💀  KILLER (RK)
  Ultimo giocatore in piedi.
  Vinci = tutti muoiono.

  ⚖️  TEAM SOLITARIO
  Bilancia la partita.
  Colpisci alla fine.

  Sei la tua stessa fazione.
""",
    },
    5: {
        "title": "Fase Giorno",
        "image": None,
        "content": """
  ☀️  Discuti / Accusa / Vota

  24 ore per parlare,
  spingere sospetti
  e linciare qualcuno.

  📣  Megafono
  1 messaggio ogni 6 ore
  per non perdere post chiave.

  Votazioni chiudono 30 min
  prima della fine del giorno.

  Le abilità diurne esistono
  ma la maggior parte si attiva di Notte.
""",
    },
    6: {
        "title": "Fase Notte",
        "image": None,
        "content": """
  🌙  Abilità | Visite | Uccisioni

  24 ore in cui avvengono
  la maggior parte delle azioni.

  🏠  Canale casa
  Dove abiti. Le azioni
  notturne ti bersagliano qui.

  📜  Canale ruolo
  La tua carta ruolo + descrizione.
  Pinga gli Overseer per
  domande qui.

  La maggior parte delle abilità
  sono solo notturne salvo
  diversa indicazione.
""",
    },
    7: {
        "title": "Case & Visite",
        "image": None,
        "content": """
  🏠  Ogni giocatore possiede una casa.

  Visita altri:
    [bussa] o [irrompi]
        |
    CASA BERSAGLIO

  Max 3 proprietari per casa.
  Il proprietario deve approvare.

  ⚠️  Senzatetto di notte = morte
  a fine notte, a meno che la tua
  casa non sia stata distrutta
  senza preavviso verso fine notte
  (puoi cercarne una nuova).

  Luoghi speciali non possono
  sovrascrivere altri luoghi
  speciali.

  1 visita/notte di default.
  I ruoli possono concederne altre.
  Tornare a casa è gratuito.
""",
    },
    8: {
        "title": "Tipi Visita & Priorità",
        "image": None,
        "content": """
  [REGOLARE] 🚪 Bussa -> il proprietario
  apre -> entri.
  Default per tutti i ruoli.

  [FORZATO]  💥 Irrompi senza
  bussare (il ruolo deve
  permetterlo).

  [FURTIVO]  👤 Muoviti senza
  narrazione. Arrivo
  nascosto.

  [PRIORITÀ]
  Le visite sono priorità più
  bassa nei preset. Apri/chiudi
  porta del proprietario vince.
  Fine notte: torni a casa
  tua (gratuito).
""",
    },
    9: {
        "title": "Regioni & Luoghi",
        "image": None,
        "content": """
  🗺️  REGIONI
  Dividono i giocatori in gruppi.
  Influenzano abilità, info,
  viaggi e interazioni.

  📍  LUOGHI SPECIALI
  Posti legati al ruolo, aree
  narrativamente importanti,
  zone meccaniche.

  Leggi il canale meccaniche
  specifico della partita
  prima di ogni gioco.
""",
    },
    10: {
        "title": "Categorie Abilità",
        "image": None,
        "content": """
  🗡️  LETALE
    Attacchi, sanguinamenti, uccisioni
  🚫  BLOCCO
    Blocco visite, blocco ruolo, blocco categoria
  🎭  MANIPOLAZIONE
    Controllo visite, finte narrazioni, controllo ruoli
  💊  CURA
    Cure, revival, immunità
  🛡️  PROTEZIONE
    Scudi, ritardi morte
  📡  INFO & COMUNICAZIONE
    Controlli, chat pubbliche/private, tracciamento
  🌐  MOBILITÀ
    Teletrasporti, attrazioni
  ✨  SUPPORTO
    Potenziamenti, concessione visite, ricariche
  ❓  ALTRO
    Qualunque altra cosa

  Un ruolo può avere più
  tipi di abilità.
""",
    },
    11: {
        "title": "Come Funzionano le Abilità",
        "image": None,
        "content": """
  🤝  FISICA
    Deve visitare il bersaglio di persona.
  📡  REMOTA
    Usata per nome giocatore.
  🏠  REMOTA-CASA
    Serve nome giocatore + numero casa.
  🏘️  CASA
    Bersaglia una casa stessa (remota
    o fisica).

  La tua carta ruolo specifica
  chiaramente il tipo.
""",
    },
    12: {
        "title": "Falso Claim",
        "image": None,
        "content": """
  🎭  Se sei Malvagio o Solitario,
  DEVI fare un falso claim.

  Un buon falso claim:
  • È coerente
  • Sembra utile
  • Si mescola ai piani del villaggio
  • Include abilità reali
  • Ti fa guadagnare fiducia

  Credibilità = valuta.

  Non sacrificarti
  a meno che non aiuti il team.
""",
    },
    13: {
        "title": "Strategia Malvagia",
        "image": None,
        "content": """
  ☠️  Guadagna fiducia prima.
  • Sembra utile
  • Spingi con logica
  • Vota col villaggio
  • Fai parte dei piani

  🎯  Coordinazione
  Uccidi giocatori forti
  (medici, protettori, ruoli info,
  utilità).

  Tieni in vita i deboli
  come capri espiatori.

  💬  Incolpazione
  Accusa con ragione.
  Senza logica = diventi sospetto.

  A volte lascia morire un
  compagno per la tua credibilità.
""",
    },
    14: {
        "title": "Regole & Consigli",
        "image": None,
        "content": """
  🚫  VIETATO
  • Screenshot di canali privati
  • Testo ruolo copiato-incollato
  • Condividere contenuti del canale ruolo

  ✅  PUOI descrivere il tuo
  ruolo con parole tue.

  ❓  CHIEDI AGLI OVERSEER
  • Domande sulle meccaniche
  • Chiarimenti sul ruolo
  • Qualunque dubbio

  ⚡  SEMPRE
  • Leggi il canale meccaniche
  • Fidati con cautela
  • Parla con cautela
  • Visita con cautela
""",
    },
    15: {
        "title": "Economia",
        "image": None,
        "content": """
  💰  ECONOMIA

  🏪  NEGOZIO
  Compra oggetti con effetti.

  Comandi:
  • `$bal`     — Controlla saldo
  • `$give`    — Dà soldi a un giocatore
    (devi essere fisicamente
     nella stessa casa)

  Gli oggetti del negozio hanno
  vari effetti.

  I trasferimenti richiedono
  che tu sia fisicamente
  nella stessa casa.
""",
    },
    16: {
        "title": "Glossario: Ruoli & Canali",
        "image": None,
        "content": """
  📖  GLOSSARIO

  RUOLI
  OS — Overseer. Moderatori.
  spec — Spettatore. Osserva.
  rk — Killer Casuale. Obiettivo:
       ultimo sopravvissuto.
  el — Leader Malvagio. Malvagio
       con grande impatto.
  tk — Killer del Villaggio. Abitante
       con potenziale letale.
  med — Medium. Abilità di revival.
  vills — Abitanti del villaggio.

  CANALI
  ec — Chat Malvagia. Per i malvagi.
       Non in ogni partita.
  pc — Chat Privata. Solo i giocatori
       dentro possono leggere.
  rc — Canale Ruolo. Per azioni
       e comunicazione con OS.
""",
    },
    17: {
        "title": "Glossario: Fasi & Abilità",
        "image": None,
        "content": """
  📖  GLOSSARIO

  FASI
  eod — fine del giorno
  eon — fine della notte
  oag — una volta a partita
  n1/d1/v1/h1 — Notte/Giorno/
       Voto/Casa 1

  ABILITÀ
  abi — Abilità (attiva/passiva)
  vb — Blocco Visite. Non può visitare.
  rb — Blocco Ruolo. Non può usare
        abilità attive.
  prots — Protezioni. Blocca
        l'attacco successivo.
  rev — Revival. Riporta in vita
        giocatori morti.
  gs — Veggente Verde. Controlla
        la categoria di un giocatore.

  ALTRO
  rc — Carta Ruolo. Info sul tuo ruolo.
        Anche Canale Ruolo (azioni).
  cred — Credibilità.
  nar — Narrazione (messaggi di morte).
  mechs — Meccaniche.
  wincon — Condizione di vittoria.
  corr — Corrotto.
  poe — Processo di eliminazione.
  recog — Riconoscimento.
        Team Malvagio (di solito) che si trova
  dory — Giocatore perde tutte le abilità attive e di solito anche le passive.
        Solo visite e voto rimasti.
""",
    },
}


EMBED_COLOR = 0xFF3FB9


def get_index_embed():
    lines = []
    for num, data in MECHANIC_PAGES.items():
        icon = data["title"].split(" ")[0] if data["title"].startswith("<") else ""
        lines.append(f"`{num:>2}` {data['title']}")
    embed = discord.Embed(
        title="Mechanics Index",
        description="\n".join(lines),
        color=EMBED_COLOR,
    )
    embed.set_footer(text="Select a topic below or use the dropdown")
    return embed


def get_page_embed(page_num):
    data = MECHANIC_PAGES[page_num]
    embed = discord.Embed(
        title=data["title"],
        description=data["content"],
        color=EMBED_COLOR,
    )
    embed.set_footer(
        text=f"Page {page_num}/{len(MECHANIC_PAGES)}"
    )
    if data["image"]:
        embed.set_image(url=data["image"])
    return embed


class MechanicsView(discord.ui.View):
    def __init__(self, author_id, pages=MECHANIC_PAGES, embed_color=EMBED_COLOR,
                 index_title="Mechanics Index", index_footer="Select a topic below or use the dropdown",
                 select_placeholder="Choose a topic...",
                 not_your_msg="Not your menu.",
                 current_page=1):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.pages = pages
        self.embed_color = embed_color
        self.index_title = index_title
        self.index_footer = index_footer
        self.select_placeholder = select_placeholder
        self.not_your_msg = not_your_msg
        self.current_page = current_page
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current_page == 1
        self.next_btn.disabled = self.current_page == len(self.pages)

    def _get_page_embed(self, page_num):
        data = self.pages[page_num]
        embed = discord.Embed(
            title=data["title"],
            description=data["content"],
            color=self.embed_color,
        )
        embed.set_footer(text=f"Page {page_num}/{len(self.pages)}")
        if data["image"]:
            embed.set_image(url=data["image"])
        return embed

    def _get_index_embed(self):
        lines = []
        for num, data in self.pages.items():
            lines.append(f"`{num:>2}` {data['title']}")
        embed = discord.Embed(
            title=self.index_title,
            description="\n".join(lines),
            color=self.embed_color,
        )
        embed.set_footer(text=self.index_footer)
        return embed

    async def _show_page(self, interaction):
        self._update_buttons()
        embed = self._get_page_embed(self.current_page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="\u25c0", style=discord.ButtonStyle.primary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(self.not_your_msg, ephemeral=True)
        if self.current_page > 1:
            self.current_page -= 1
        await self._show_page(interaction)

    @discord.ui.button(label="\U0001f4cb List", style=discord.ButtonStyle.secondary, row=0)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(self.not_your_msg, ephemeral=True)
        view = MechanicsIndexView(self.author_id, self)
        embed = self._get_index_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="\u25b6", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(self.not_your_msg, ephemeral=True)
        if self.current_page < len(self.pages):
            self.current_page += 1
        await self._show_page(interaction)


class MechanicsIndexView(discord.ui.View):
    def __init__(self, author_id, parent_view):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.parent_view = parent_view

        options = [
            discord.SelectOption(
                label=f"{num}. {data['title'][:80]}",
                value=str(num),
            )
            for num, data in parent_view.pages.items()
        ]

        select = discord.ui.Select(
            placeholder=parent_view.select_placeholder,
            options=options,
            row=0,
        )
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(self.parent_view.not_your_msg, ephemeral=True)
        page = int(self.children[0].values[0])
        self.parent_view.current_page = page
        self.parent_view._update_buttons()
        embed = self.parent_view._get_page_embed(page)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class VgIntro(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="vgintro", aliases=["vgi"])
    async def vgintro(self, ctx, page: str = None):
        """Show the Village Games introduction (English)."""
        if page is not None and page.lower() == "list":
            view = MechanicsIndexView(ctx.author.id, MechanicsView(ctx.author.id))
            embed = get_index_embed()
            await ctx.send(embed=embed, view=view)
            return

        if page is not None:
            try:
                num = int(page)
                if num not in MECHANIC_PAGES:
                    return await ctx.send("That mechanics page does not exist.")
                current = num
            except ValueError:
                return await ctx.send("Invalid page. Use `.mechanics list`")
        else:
            current = 1

        view = MechanicsView(ctx.author.id, current_page=current)
        embed = get_page_embed(current)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="vgintro_it", aliases=["vgii"])
    async def vgintro_it(self, ctx, page: str = None):
        """Show the Village Games introduction (Italian)."""
        if page is not None and page.lower() == "list":
            it_view = MechanicsView(ctx.author.id, pages=MECHANIC_PAGES_IT,
                                    index_title="Indice Meccaniche",
                                    index_footer="Seleziona un argomento o usa il menu",
                                    not_your_msg="Non è il tuo menu.",
                                    select_placeholder="Scegli un argomento...")
            it_index = MechanicsIndexView(ctx.author.id, it_view)
            embed = it_view._get_index_embed()
            await ctx.send(embed=embed, view=it_index)
            return

        if page is not None:
            try:
                num = int(page)
                if num not in MECHANIC_PAGES_IT:
                    return await ctx.send("Quella pagina non esiste.")
                current = num
            except ValueError:
                return await ctx.send("Pagina non valida. Usa `.vgii list`")
        else:
            current = 1

        view = MechanicsView(ctx.author.id, pages=MECHANIC_PAGES_IT, current_page=current,
                             not_your_msg="Non è il tuo menu.")
        embed = view._get_page_embed(current)
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(VgIntro(bot))
