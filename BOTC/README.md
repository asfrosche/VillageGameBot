# Blood on the Clocktower — Discord Bot Module

A self-contained Discord bot module for **Blood on the Clocktower** (BOTC). Provides
role lookups, jinxes, fabled, scripts, night orders, per-guild references, and a
full nomination/voting system with seating order, clock, dead tracking, and sponsors.

All commands are available as both **prefix** (`.`) and **slash** (`/`) commands.

---

## Quick Start

```
.botchelp          # Show all commands
.help              # Slash version of the above
```

---

## Role Lookups

| Command | Description |
|---|---|
| `.rr <name>` / </role> | Look up a role by name or alias. Shows ability, team, edition, reminder tokens. Interactive buttons for jinxes, night order, aliases, and the wiki page. |
| `.jinx <name>` / </jinx> | Show all jinxes for a given role. |
| `.fabled <name>` / </fabled> | Look up a fabled character. |
| `.scripts [tb\|bmr\|snv]` / </scripts> | View TB, BMR, or SNV as full-script images. Include an edition to skip the interactive view. |
| `.nightorder [tb\|bmr\|snv]` / </nightorder> | Display first-night and other-night order. Include an edition to skip the interactive view. |

---

## Per-Guild References

| Command | Description |
|---|---|
| `.setref <script\|grim> [link]` | Store a message as the custom script or grim reference for this server. Reply to a message or paste a link. |
| `.ref <script\|grim>` | Show the saved reference message with its full-resolution image. |

---

## Seating Order

**Admin commands.** The seating order is the backbone of the nomination clock.

| Command | Description |
|---|---|
| `.bsetseating @p1 @p2 @p3 ...` | Set the permanent seating order (min 3 players). Persisted to `game_state.json`. |
| `.bseating` | Show the current seating order with dead (☠️) and sponsor (⭐@user) indicators. |

---

## Player State

**Admin commands.** Track who is dead and who has a sponsor.

| Command | Description |
|---|---|
| `.bkill @player` | Mark a player as dead. They lose their dead vote. |
| `.brevive @player` | Revive a dead player and restore their dead vote capability. |
| `.bsponsor @player @sponsor` | Assign a sponsor to a player. The sponsor can vote normally. |
| `.bunsponsor @player` | Remove the sponsor from a player. |
| `.bdead` | Show the list of all dead players and whether they still have a dead vote remaining. |

### Rules
- **Dead** players cannot vote unless they still have a **dead vote** (one-time use).
- **Sponsors** are normal players who can vote. The ⭐ marker appears on the **sponsored player's** row, indicating someone else is filling in for them.
- Player state does **not** modify Discord roles — it is purely tracked in `game_state.json`.

---

## Nomination & Voting

**Admin commands.** Run a full BOTC-style nomination with a seating-chart embed,
Guilty/Not Guilty buttons, and a visual clock that advances through the seating order.

| Command | Description |
|---|---|
| `.bnominate @player` | Start a nomination. Opens the voting embed with buttons. |
| `.baccuse <text>` | Set the accusation for the current nomination (max 1024 chars). |
| `.bdefend <text>` | Set the defense for the current nomination (max 1024 chars). |
| `.bnoms` | Show the current nomination status (same embed, no new message). |
| `.bnomtimeout <seconds>` | Set the nomination expiry timeout (default 120s, min 10s). |

### Voting embed
- **Seating chart** — all players in order with vote/status icons:
  - ✅ Guilty vote
  - ❌ Not Guilty vote
  - ☠️ Dead (no vote left)
  - ☠️🗳️ Dead but has dead vote remaining
  - ⭐ Has a sponsor assigned
  - 🕦 Current clock position
  - — Not yet voted
- **Guilty / Not Guilty buttons** — only users with the **Alive** Discord role can vote.
  - Dead players with a dead vote remaining: voting uses up the dead vote.
  - Sponsors: can vote like any alive player.
- **Advance Clock / Back Clock buttons** — Storyteller-only (admin permission). Skips
  the nominee and dead-without-vote players automatically.
- **Footer** shows guilty count, not guilty count, turnout (`voted/alive`), required
  guilty votes (majority of alive), and current clock position.

### Clock mechanics
- Starts at the first player clockwise from the nominee.
- Advances one speaker at a time in seating order.
- Skips the nominee and any dead player who cannot vote.
- Sponsors are included in the rotation (they can vote).
- Players can vote at any time regardless of clock position.

---

## Data Files

All stored in `may/BOTC/data/`.

| File | Purpose |
|---|---|
| `roles.json` | All role definitions: name, aliases, team, ability, edition, reminders |
| `jinxes.json` | Jinx pairs (role A is jinxed by role B in edition C) |
| `fabled.json` | Fabled character definitions |
| `aliases.json` | Additional alias mapping |
| `references.json` | Per-guild script/grim message references |
| `game_state.json` | Per-guild seating order, player states, sponsor assignments |

---

## File Structure

```
may/BOTC/
├── cogs/
│   ├── role.py       # .rr / /role — role lookups + interactive view
│   ├── jinx.py       # .jinx / /jinx — jinx lookups
│   ├── fabled.py     # .fabled / /fabled — fabled lookups
│   ├── scripts.py    # .scripts / /scripts — script images
│   ├── nightorder.py # .nightorder / /nightorder — night order displays
│   ├── help.py       # .botchelp / /help / .setref / .ref — help + references
│   └── game.py       # Nomination, voting, seating, player state, deadlist
├── data/             # JSON data files (see above)
├── utils/
│   └── botc.py       # Core library: role/jinx/fabled lookup, embed builders
└── README.md
```

---

## Data Sources

- Roles, jinxes, and fabled: [bra1n/townsquare](https://github.com/bra1n/townsquare)
- Icons: [tomozbot/botc-icons](https://github.com/tomozbot/botc-icons)
- Wiki: [wiki.bloodontheclocktower.com](https://wiki.bloodontheclocktower.com)

---

## Dependencies

- `discord.py >= 2.0`
- `Pillow` (for script image generation)
- Standard library only beyond that
