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
    def __init__(self, author_id, current_page=1):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.current_page = current_page
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current_page == 1
        self.next_btn.disabled = self.current_page == len(MECHANIC_PAGES)

    async def _show_page(self, interaction):
        self._update_buttons()
        embed = get_page_embed(self.current_page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="\u25c0", style=discord.ButtonStyle.primary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if self.current_page > 1:
            self.current_page -= 1
        await self._show_page(interaction)

    @discord.ui.button(label="\U0001f4cb List", style=discord.ButtonStyle.secondary, row=0)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        view = MechanicsIndexView(self.author_id, self)
        embed = get_index_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="\u25b6", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        if self.current_page < len(MECHANIC_PAGES):
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
            for num, data in MECHANIC_PAGES.items()
        ]

        select = discord.ui.Select(
            placeholder="Choose a topic...",
            options=options,
            row=0,
        )
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Not your menu.", ephemeral=True)
        page = int(self.children[0].values[0])
        self.parent_view.current_page = page
        self.parent_view._update_buttons()
        embed = get_page_embed(page)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class VgIntro(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="vgintro", aliases=["vgi"])
    async def vgintro(self, ctx, page: str = None):
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


async def setup(bot):
    await bot.add_cog(VgIntro(bot))
