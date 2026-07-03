# Townsquare Features Not in BOTC Discord Bot

> Based on [nicholas-eden/townsquare](https://github.com/nicholas-eden/townsquare) (fork of bra1n/townsquare) — a web-based Blood on the Clocktower virtual grimoire & town square.

---

## 🧭 Core Views & UI Paradigm

| Feature | Description |
|---------|-------------|
| **Storyteller Grimoire View** | Full visual grimoire with all roles, reminders, night order markers visible to the ST |
| **Public Town Square View** | Player-facing view that hides all secret info (roles, bluffs, reminders) — toggleable with `[G]` |
| **Visual Player Circle** | Radial/circular layout of player tokens arranged around the center |
| **Drag-and-Drop Seat Swapping** | ST can drag players to swap positions visually |
| **Player Zoom Controls** | Adjust token size 70%–130% via `[+]/[-]` |
| **Custom Backgrounds** | ST can set image/video background; script `_meta` can specify one |
| **Night Visual Effect** | Blue gradient overlay with drifting clouds during night phase |
| **Animated UI** | Smooth CSS transitions throughout (can be disabled) |
| **Sound Effects** | Countdown bell, role-notification sounds (can be muted) |
| **Full Mobile Web Support** | Touch-optimized controls and responsive layout |

---

## 🎭 Role Management & Grimoire

| Feature | Description |
|---------|-------------|
| **Visual Role Assignment** | Click-to-assign roles via a searchable modal with team/edition filters |
| **Role Distribution to Players** | ST sends each player only their own role (WebSocket, server-side split) |
| **Demon Bluffs Panel** | 3 bluff slots visible only to ST, assignable fake roles for the Demon |
| **Role Mock Assignments** | Preview assigned tokens without sending to players |
| **Alignment Toggle** | Cycle player alignment (regular → good → evil); token glow updates accordingly |
| **Ability Tooltips on Tokens** | Hover token in grimoire to see ability text |
| **Character Reference Sheet** | Modal `[R]` listing all script characters with ability text, team colors, flavor |
| **Full Night Sheet Modal** | `[N]` key — ordered list of all roles with wake-up positions |
| **All Experimental Characters** | Includes Carousel set (~60+ experimental roles) plus all Loric characters |
| **Pre-built Example Custom Scripts** | Built-in popular community scripts (Boozling, Catfishing, etc.) and Teensyville scripts |
| **Game State JSON Export/Import** | Full save/restore of entire game state as JSON |
| **Reminder Tokens on Tokens** | Visual reminder tokens displayed as small circular icons below each player token |
| **Global Reminders** | Reminder tokens always available regardless of assignment (e.g., Philosopher, Drunk) |
| **Reminder Search** | Search bar to filter available reminders |
| **Setup-Affected Role Warnings** | Leaf icon on roles affecting setup (Drunk, Baron) |

---

## 🌐 Live Session (WebSocket Multiplayer)

| Feature | Description |
|---------|-------------|
| **Host a Session** | ST enters a channel name; generates a shareable URL for players |
| **Join a Session** | Players enter channel name or paste URL to join |
| **Seat Claiming** | Players claim their own seat on the circle |
| **Cryptographic Player IDs** | SHA-256 hashed from 32-byte random secrets prevents impersonation |
| **Reconnection Support** | Seat reserved for 30+s on disconnect; player can reclaim |
| **Full Gamestate Sync** | Names, roles, life/death, votes, nomination, night phase, NPCs, edition synced in real-time |
| **Hand Sync** | Raised hands visible to ST across session |
| **Pronoun Sync** | Player pronouns synced across session |
| **Latency/Ping Display** | Connection latency calculated via heartbeat pings |
| **Rate Limiting** | 5 messages/second enforced server-side |
| **Prometheus Metrics** | Server monitoring: concurrent players/channels, messages in/out |
| **SSL Support** | Production uses Let's Encrypt certs |
| **Domain Whitelist** | Server restricts origin to known domains |

---

## 🗳️ Voting System

| Feature | Description |
|---------|-------------|
| **Visual Nomination Overlay** | Central demon-head overlay showing nominator/nominee with animated clock arrows |
| **Real-Time Vote Tally** | Live count with majority calculation (`ceil(alive/2)` for execution, `ceil(total/2)` for exile) |
| **Adjustable Voting Speed** | ST can set 0.5s–4s per vote round |
| **Countdown Timer** | 3-2-1-GO audible countdown with bell sounds |
| **Auto-Vote Progression** | Votes lock automatically per player as timer elapses |
| **Manual ST Vote Override** | ST can click locked votes to change them (for Flowergirl, etc.) |
| **Ghost Votes** | Dead players show ghost vote icon; ST can toggle voteless |
| **Two Votes Per Player** | Optional per-player two-vote toggle (for Banshee, etc.) |
| **Secret Vote Mode** | Players see question marks instead of actual votes (for Organ Grinder) |
| **Mark for Execution** | ST sets a skull icon for "on the block" |
| **Vote History Modal** | `[V]` key — all past nominations with timestamps, nominator, nominee, type, majority, vote breakdown |
| **Vote History Clear** | ST can clear history |

---

## 🌙 Night Management

| Feature | Description |
|---------|-------------|
| **Night/Day Phase Toggle** | `[S]` key switches phases |
| **Night Number Tracking** | Current night number tracked and displayed |
| **Night Phase Locking** | Kill/revive disabled during night to prevent accidents |
| **Night Order Badges on Tokens** | Each player token shows night position badge (first/other night); dead badges grayed out |
| **Night Reminder Text on Hover** | Hover night badge to see official ability reminder text |
| **Dusk/Dawn in Night Order** | Included for Vizier/Leviathan positioning |
| **JSON-Driven Night Order** | Custom scripts can specify `firstNight`/`otherNight` per character |

---

## 🧌 NPC / Fabled / Loric Management

| Feature | Description |
|---------|-------------|
| **Visual NPC Management** | Modal to add any Fabled/Loric character to the game |
| **Auto-Add NPCs** | Djinn auto-added when script has active jinxes; Bootlegger auto-added for homebrew/bootlegger rules |
| **NPC Panel** | Collapsible panel at top-left showing active NPCs |
| **NPC Night Order** | NPCs appear in night order with own wake-up positions and reminder texts |

---

## 📜 Custom Script / Homebrew Support

| Feature | Description |
|---------|-------------|
| **Script Upload** | Upload custom JSON script file from the official Script Tool |
| **Clipboard Script Import** | Paste script JSON directly from clipboard |
| **Script `_meta` Properties** | Supports `name`, `author`, `logo`, `background`, `hideTitle`, `bootlegger` |
| **Full Custom Character Definitions** | Define custom roles with `id`, `name`, `team`, `ability`, `image`, `edition`, night positions, reminders, jinxes |
| **Custom Image Opt-In** | Players must explicitly enable custom images (security warning) |
| **Official JSON Schema Compliance** | Follows TPI's official [script schema](https://github.com/ThePandemoniumInstitute/botc-release) |

---

## ⚙️ UI Customization

| Feature | Description |
|---------|-------------|
| **Unofficial Art Toggle** | Switch between official and unofficial character art |
| **Custom Images Toggle** | Opt-in for custom character images from scripts |
| **Disable Animations** | Performance toggle |
| **Mute Sounds** | Toggle sound effects |
| **Allow Self-Naming** | Toggle whether players can rename themselves |
| **Keyboard Shortcuts** | 15+ shortcuts for all major actions (`,` `]` `[` `A` `C` `E` `G` `H` `J` `N` `R` `S` `V` `Escape`) |
| **Empty Seat Management** | ST can empty a claimed seat; disconnected player seats show red chair icon |
| **Player Color-Coding** | Tokens glow with team colors based on alignment |

---

## 🧠 What the BOTC Bot Already Has (For Context)

These features exist in your bot but NOT in townsquare:

- **Discord-native integration** — commands, embeds, roles, permissions, threads
- **Text-based gameplay** — asynchronous, long-form voting with accusation/defense text
- **Seating order with clock** — linear clockwise progression through voters
- **Sponsor system** — players can assign sponsors to vote on their behalf
- **Neighbor threads** — auto-created private Discord threads for adjacent alive pairs
- **Dead vote tracking** — tracks whether dead players have used their one ghost vote
- **Nomination timeout** — configurable expiry for nominations
- **Script image generation** — Pillow-generated full-script PNG with role icons
- **Fuzzy role search** — SequenceMatcher-based fuzzy matching for role names
- **Per-guild persistence** — SQLite-backed guild-specific game state
- **Alias system** — short-name to full-name role mapping

---

## 🗺️ Summary of Feature Categories

| Category | In Townsquare | In BOTC Bot | Gap |
|----------|:---:|:---:|:---:|
| Visual Grimoire/Town Square | ✅ | ❌ | Web UI vs Discord text |
| Role Lookups/Reference | ✅ | ✅ | Comparable |
| Jinx Lookups | ✅ (inline) | ✅ (dedicated) | Comparable |
| Night Order Display | ✅ (modal+badges) | ✅ (embed) | Comparable |
| Fabled Lookups | ✅ (NPC panel) | ✅ (command) | Comparable |
| Script Display | ✅ (upload) | ✅ (image gen) | Comparable |
| Live Multiplayer Session | ✅ | ❌ | Full real-time sync |
| Visual Role Assignment | ✅ | ⚠️ (text only) | Grimoire UI |
| Role Distribution to Players | ✅ | ❌ | Direct role DM |
| Nomination & Voting | ✅ (visual+auto) | ✅ (text+clock) | Different paradigms |
| Execution Flow | ✅ (mark+votes) | ⚠️ (no auto-process) | Bot needs completion |
| Night/Phase Management | ✅ (full) | ❌ | Bot has no phase system |
| Reminder Tokens | ✅ (visual UI) | ❌ | Bot: text-only planned |
| Status Effects (poison/drunk) | ✅ (alignment toggle) | ❌ | Bot: planned |
| Day/Night Cycle | ✅ | ❌ | Bot: planned |
| Private Player Channels | ❌ | ❌ (planned) | Both need it |
| Night Action Resolution | ❌ | ❌ | Both need it |
| Dawn Processing | ❌ | ❌ | Both need it |
| Win Condition Checking | ❌ | ❌ | Both need it |
| Graveyard/Dead Chat | ❌ | ❌ | Both need it |
| Traveler System | ✅ (roles) | ❌ (planned) | Bot: planned |
| Game Logging/Audit | ❌ | ❌ (planned) | Both need it |
| Custom Character Support | ✅ (JSON upload) | ❌ | Bot can't load custom scripts |
| Homebrew Support | ✅ (full) | ❌ | Only base editions |
| Keyboard Shortcuts | ✅ (15+) | ❌ | N/A (Discord) |
| Mobile Web Support | ✅ | ✅ (Discord app) | Different platforms |
