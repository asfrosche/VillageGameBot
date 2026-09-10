# BOTC Module — Gaps for a 24h Text-Based Game

What exists vs. what's needed to run a full text-based Blood on the Clocktower
game with 24-hour day/night phases on Discord.

---

## ✅ What Already Exists

| Area | Commands / Features |
|---|---|
| **Role Lookups** | `.rr` / `/role`, `.jinx` / `/jinx`, `.fabled` / `/fabled` |
| **Scripts** | `.scripts` / `/scripts` — full-script PNG images |
| **Night Order** | `.nightorder` / `/nightorder` — first/other night order |
| **References** | `.setref`, `.ref` — per-guild script/grim message links |
| **Seating Order** | `.bsetseating`, `.bseating` — circular order persisted to `game_state.json` |
| **Player State** | `.bkill`, `.brevive`, `.bdead`, `.bsponsor`, `.bunsponsor` |
| **Nomination & Voting** | `.bnominate`, `.baccuse`, `.bdefend`, `.bnoms`, `.bnomtimeout` — seating chart embed, Guilty/Not Guilty buttons, visual clock, Storyteller clock controls |
| **Neighbor Threads** | Auto-created private threads per adjacent alive pair in `🌞daytime-chat` |
| **Help** | `.botchelp` / `/help` — full command reference |

---

## ❌ What's Missing

### 1. Phase System

The biggest gap. No day/night cycle exists.

- **Day phase timer** — configurable duration (e.g. 24h), auto-advance
- **Night phase timer** — configurable duration (e.g. 24h), auto-advance
- **Phase commands** — `.day`, `.night`, `.phase status`, `.phase set <time>`
- **Phase announcements** — automated ping when day/night starts
- **Pause/resume** — pause the phase timer for holidays or delays

### 2. Game Lifecycle

No start/stop game management.

- `.game create` — initialize a new game with seating order
- `.game end` — close the game, archive channels
- `.game status` — show current game state (phase, day number, alive count)
- Day counter (Day 1, Night 1, Day 2, Night 2…)

### 3. Role Assignment

No way to assign roles to players.

- `.assign @player <role>` — Storyteller assigns a role (DMs the player or posts in their private channel)
- `.myrole` — player views their own role (only during day/night when allowed)
- `.grimoire` — Storyteller-only overview of all roles, players, alive/dead statuses, reminder tokens

### 4. Private Player Channels

No per-player private channels.

- One private text channel per player (nameable by seat number or player name)
- Only the player + Storytellers can see it
- Used for role DMs, night action prompts, and private notes

### 5. Night Action System

No night action submission or resolution.

- **Action prompt** — when night starts, DM each player whose role acts that night
- **Action submission** — buttons or commands to choose targets (`.night kill @player`, `.night investigate @player`, etc.)
- **Night order resolution** — automated dawn processing in correct turn order
- **Storyteller queue** — list of pending night actions the ST must resolve manually (e.g. Po, Vigor, Politician)
- **Action validation** — prevent selecting dead players, invalid targets, or acting out of turn

### 6. Dawn Processing

No automated dawn.

- Resolve all night actions in order
- Apply deaths, info results, status changes
- Post dawn summary (who died, what info was learned)
- Announce "It is now Day X"

### 7. Execution Flow

After nomination voting ends, no execution processing.

- **Majority check** — did guilty votes exceed half of alive players?
- **Execution announcement** — if majority, player is executed
- **Last words** — executed player gets one final message
- **Role reveal** — optionally reveal the executed player's role
- **Death processing** — mark dead, move to graveyard channel

### 8. Status Effects

No tracking of BOTC status effects.

- **Poisoned** — player's ability does not work
- **Drunk** — player gets false info
- **Mad** — player must act a certain way
- **Protected** — player cannot die tonight
- **Good/Evil detection** — register/seem as different alignment

Commands: `.poison @player`, `.drunk @player`, `.protect @player`, `.status @player`

### 9. Reminder Token Tracking

No per-player reminder token management.

- `.reminder add @player <token>` — place a reminder token on a player
- `.reminder remove @player <token>` — remove it
- `.reminder list` — show all placed tokens

### 10. Graveyard & Dead Player Features

No dedicated dead player channel.

- **Graveyard channel** — private channel for all dead players to chat
- **Ghost votes** — track which dead players still have a ghost vote
- **Dead player info** — what dead players can see (depends on role)
- **Vote on execution** — dead players cast ghost votes during nominations

### 11. Win Condition Checking

No automated win detection.

- **Demon win** — only 2 players alive + no way to kill demon
- **Townsfolk win** — demon is dead
- **Run-off votes / ties** — what happens when nomination vote is tied
- **Game over screen** — final embed with all players, roles, teams, and winner

### 12. Traveler System

No traveler support.

- `.traveler add @player` — add a traveler with a role
- `.traveler remove @player` — remove a traveler
- Traveler-specific voting rules

### 13. Fabled Characters

Fabled lookup exists (`.fabled`), but no in-game activation.

- `.fabled enable <name>` — add a fabled to the current game
- `.fabled disable <name>` — remove it
- Fabled-specific rules and reminders

### 14. Voting Enhancements

Current nomination system is functional but lacks:

- **Multiple nominations per day** — allow cycling through multiple nominees
- **Nomination limits** — each player can only nominate once per day
- **Self-nomination** — currently blocked, may want to allow
- **Vote record** — log of who voted guilty/not guilty per nomination
- **Vote flipping** — allow changing vote before the nomination closes

### 15. Logging & Audit

No game log.

- **Action log** — timestamped record of all night actions, votes, deaths
- `.log day 2` — show all events for a specific day
- `.log player @player` — show all events involving a player

---

## Priority Order (Recommended)

1. **Phase system** — day/night cycle is the backbone
2. **Role assignment + private channels** — players need to know their role
3. **Night action system** — the core game mechanic
4. **Dawn processing** — resolve night -> day transition
5. **Execution flow** — complete the day cycle
6. **Win condition checking** — game needs to end
7. **Status effects** — many roles depend on these
8. **Graveyard** — dead player experience
9. **Travelers & Fabled** — optional expansions
10. **Logging** — quality of life for Storytellers

---

## Current File Architecture

```
may/BOTC/
├── cogs/
│   ├── role.py       # Role lookups + interactive view
│   ├── jinx.py       # Jinx lookups
│   ├── fabled.py     # Fabled lookups
│   ├── scripts.py    # Script image generation
│   ├── nightorder.py # Night order display
│   ├── help.py       # Help + references
│   └── game.py       # Seating, player state, nomination/voting
├── utils/
│   └── botc.py       # Core library: lookups, embeds, image gen
├── data/
│   ├── roles.json    # All role definitions
│   ├── jinxes.json   # Jinx pairs
│   ├── fabled.json   # Fabled definitions
│   └── aliases.json  # Alias mappings
├── README.md
└── GAPS.md           # This file
```
