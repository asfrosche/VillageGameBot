# Village Game Bot 🏡

Welcome to the **Village Game Bot** repository! This is a production-grade, highly-modular Discord bot designed to host, automate, and manage large-scale **Discord Mafia & Social Deduction** games (30–40 players). It is built on `discord.py` and ships with several complete sub-systems: a community-simulation (World Cup) engine, a full **Blood on the Clocktower** toolkit, an economy, a live analytics pipeline, and a web dashboard.

Rather than relying on manual moderation, this bot turns a Discord server into a living "map." Players physically navigate channels (rooms), interact with items, knock on doors, whisper, and take part in a rigid Day/Night phase structure, while Game Masters (Overseers) get complete, centralized control.

---

## ✨ Features at a glance

- 🗺️ **Living map** — channels are physical rooms; players move, knock, sneak and get moved around.
- 🗳️ **Voting & lynching** — classic social-deduction votes plus a token-based accusation/trial system.
- 🪙 **Economy & items** — shop, wallet/RC balances, inventories, trading and interactive item drops.
- 🛎️ **Role packages** — register pinned-message role packages, role cards, and publish archives.
- 🕵️ **Surveillance** — follow/track/stalk relationships for hosts and over-informing roles.
- 📊 **Analytics** — every command execution is recorded, exposed via `.failures`/`.analytics` and a FastAPI dashboard.
- 🕰️ **Scheduling** — EN/IT game calendars, meeting-room scheduler, meetup matrix, birthday reminders.
- 📌 **Sticky messages** — silent, cooldown-based re-pinned messages per channel.

---

## 🧩 Architecture

The bot is constructed using a robust, cog-based architecture (`discord.ext.commands.Cog`). Every cog handles an isolated aspect of the game. All cogs live under `cogs/`, are registered in `main.py` (`startcog()`), and some heavy ones (`library_cog`, `library_it_cog`, `meeting_cog`, `os_info_cog`) are loaded dynamically via `bot.load_extension` on `on_ready`.

Persistence is **SQLite-first** through `utils/bot_db.py` (guild settings, invites, deadlist, players, and dedicated per-feature DBs), with legacy JSON data auto-migrated on first run. A background **analytics pipeline** (`utils/analytics/`) writes every command execution to `data/analytics.db`.

---

## 📦 Cog reference

### A. Core game loop

| Cog file | Class | What it does |
|---|---|---|
| `setup_cog.py` | `Setup` | Foundation. Maps categories/roles/channels (Alive, Sponsor, Dead, Alt, log channels…) to the datastore. `.setup`, `.roleset`, `.channelset`, `.categoryset`, `.settings`. |
| `moving_cog.py` | `Moving` | The player navigation engine. `.move`, `.knock`, `.renmove`, `.pendingknock`, `.movehouse`, plus force-move host tools. Stealth mode suppresses join/leave messages. |
| `home_cog.py` | `Home` | Spawn & reset logic. `.home`, `.home return`, `.owner`, `.rolechat initialize`, `.home set/mset/list/delete`. |
| `handling_cog.py` | `Handling` | Dynamic world building. `.destroy`, `.rebuild`, `.decay`, `.newpc`, `.mergepc`, `.close`, `.setowner`, `.end`, `.public`/`.private`. |
| `voting_cog.py` | `Voting` | Core lynching. `.vote`, `.abstain`, `.manipulate`, `.removevote`, `.remvote`, `.skipnight`, `.patibolo`, `.votelist`, `.resetvotes`. |
| `nominations_cog.py` | `Nominations` | Token economy + trials. `.addtokens`, `.accuse`, `.intervene`, `.voten`, `.stopvotes`, `.clearvotes`. |
| `utility_cog.py` | `Utility` | Game Master toolbox. `.day`/`.night` phase shifts, `.broom`/`.fbroom` sweeping, `.log` transcripts, `.deadrole`/`.dead`, kill logs, role management, `.endgame`. |
| `status_cog.py` | `Status` | Per-channel **Status Manager** (protection, roleblock, visitblock, immunity, stealth, untargetable + custom statuses). Integrated movement warnings. `/status`, `.statuslist`. |

### B. Economy, items & abilities

| Cog file | Class | What it does |
|---|---|---|
| `economy_cog.py` | `Economy` | RC balances/wallets, shop, `.buy`/`.sell`, inventories, `.trade`, `.collect`, `.leaderboard`. |
| `item_drop_cog.py` | `ItemDrop` | Interactive, SQLite-backed item drops on persistent buttons with atomic claim guarantees and an expiration loop. |
| `dashboard_cog.py` | `Dashboard` | Player-facing role sheet/abilities UI (`.dashboard`), active/passive abilities, visit blocking (`.vb`), action log, house locks. |
| `presets_cog.py` | `Presets` | Ability preset management with categories (`.preset`, `.ospreset`). |

### C. Surveillance, intel & logging

| Cog file | Class | What it does |
|---|---|---|
| `surveillance_cog.py` | `Surveillance` | Follow/track/stalk relationships; hooks into movement for automated updates. |
| `os_info_cog.py` | `Overseer` | The **Overseer Intelligence Board** (own `db/overseer.db`): per-player effect cards, `.setboard`, `.addcard`, `.refreshcards`. |
| `actions_logging_cog.py` | `ActionsLogging` | Central action log channel; intercepts role/bot mentions and tracks player actions with approval buttons. |
| `tracker_cog.py` | `MessageTracker` | Message-count metrics (`.statss`, `.serverstats`, `.start_tracking`). |

### D. Communication & navigation helpers

| Cog file | Class | What it does |
|---|---|---|
| `help_misc_cog.py` | `Other` | The hub: dynamic dropdown-based `.help`, `.sh` search, `.who`, `.where`, `.map`, `.narrate`, `.timer`, `.roll`, `.revive`, `.loc`, `.timestamp`. |
| `meetupmatrix.py` | `Meetup` | Passive **who-met-whom** adjacency matrix (`.meetupmatrix`, `.allmeets`). |
| `meeting_cog.py` | `MeetingCog` | Meeting-room scheduler — requests, cooldowns, blocked users, archives (`.meeting`, `.endmeeting`, `.meetingconfig`). Integrates with `Meetup`. |
| `channel_cog.py` | `ChannelMap` | Visual PC/public maps (`.channels`, `.publicmap`, `.privatemap`). |
| `location_manager.py` | `LocationManager` | Timezone/location features (`.mysetloc`, `.localtime`, `.near`, `.mapp`, `.mapheat`) via `timezonefinder`/`geopy`. |

### E. Game library & stat archives

| Cog file | Class | What it does |
|---|---|---|
| `library_cog.py` | `GameLibrary` | English game/role codex (`lib`/`libit` group): add/search/edit games, `stats`, `winrate`, `relations`, `missingids`. |
| `library_it_cog.py` | `GameLibraryIT` | Italian library (`libit` group) sharing the EN database & views. |
| `library_admin_cog.py` | `GameLibraryAdmin` | Interactive admin browser for the library (`libadmin`). |
| `role_package_cog.py` | `RolePackageCog` | Registers pinned-message role packages, role cards/teams, and the full publishing pipeline (`.publishroles`, `.reviewroles`, `.approvepublish`, `.libimport`). `/reveal` slash command. |
| `send_role.py` | `SendRole` | Forwards replied messages to a configured target channel (`.settarget`, `.sendrole`/`.sr`), plus `.teamroll`. |

### F. Scheduling, misc & developer tools

| Cog file | Class | What it does |
|---|---|---|
| `game_manager.py` | `GameManager` | Legacy lobby/sign-up system with persistent buttons (`.startgame`, `.addplayer`, `.closegame`). |
| `game_manager_en.py` / `game_manager_it.py` | `GameManagerEn` / `GameManagerIt` | **Heartside Calendar** (EN `.calendar`) and **Calendario** (IT `.calendario`) game-scheduling wizards, each with its own SQLite DB. |
| `vg_intro.py` | `VgIntro` | Paginated intro to the Village Games (EN/IT) — `.vgintro`/`.vgintro_it`, `/vgi`. |
| `bday.py` | `Birthday` | Birthday registry + background announcement loop (`.birthdays`, `.birthday add`). |
| `infos_cog.py` | `Infos` | Free-text notes attached to channels (`.info`). |
| `lists_cog.py` | `Lists` | `.playerlist`, `.sponsorlist`, `.houselist`, `.deadlist`, `.rollhouses`. |
| `estate_cog.py` | `Estate` | Estate mapping & room-coordinate management for larger properties. |
| `sticky_cog.py` | `StickyCog` | **Sticky messages** — silent, cooldown-based re-pinning (`.sticky set/remove/cooldown/list`). |
| `aux_battle.py` | `AuxBattle` | Auxiliary battle/tournament engine. |
| `privatecommands_cog.py` | `Privatecommands` | Developer-only diagnostics (guild list, invites, `.fake`) + lighthearted triggers. |
| `analytics_cog.py` | `AnalyticsCog` | Discord-facing analytics: `.analytics`, `.failures`, `.analyticsexport`, `.analyticsreset`. |

---

## 🎯 Specialized sub-systems

### Blood on the Clocktower (`BOTC/`)
A complete BOTC implementation as its own cog namespace: role, jinx, fabled, night-order, scripts and help cogs plus a game engine. Uses `botc*`-aliased prefix commands and `/role`, `/help` etc. slash commands to avoid collisions.

### FIFA World Cup simulator (`fifa_data/`)
Community-draft + match simulation engine:
- `DraftCog` (`.draftstart`, `.myteam`, `.draftpoints`, `.scoutingboard`, `.topplayers`)
- `BracketCog` (`.bracket` renders the bracket as PNG)
- Multi-generation match simulators (`.simulate` with V1–V5 tactical models), live standings, trends and heatmaps.
- Data is ingested from online providers (`fifa_data/data/`) with a `provider_cache` for responsiveness.

### Analytics & web dashboard (`utils/analytics/`, `analytics_dashboard/`)
Two faces of the same SQLite `AnalyticsDB`:
1. **In-bot**: every `before_invoke`/`after_invoke`/error is captured by `utils/analytics/instrumentation.py` and queried via `AnalyticsCog`.
2. **Web**: a FastAPI single-page dashboard (`analytics_dashboard/`) reads the same DB through REST endpoints and is opened via `main.py`'s `start_dashboard()` (optional; disabled by default).

---

## 🧹 Legacy / dormant modules

Some files exist in the repo but are **not loaded** by the running bot. They are kept for reference or are leftovers:

| File | Status |
|---|---|
| `cogs/other_cog.py` | 100% commented-out legacy copy of `help_misc_cog`. Not loaded. |
| `cogs/auto_visit_cog.py` | Feature-complete auto-visit scheduling cog (`AutoVisit`). **Not loaded** in `main.py`. |
| `cogs/track_stalk_utils.py` | Removed. Was a stale duplicate of `after_movement_update`, which now lives in `cogs/surveillance_cog.py` (all 12 call sites import it from there). A guard test keeps it from returning. |
| `cogs/dashboard_cog.py` | **Not loaded** in `main.py` (disabled). ~9 help entries still advertise its commands. |
| `.senet` / `.soldiers` | Advertised in the help index but the cog modules are not present in this release. |

---

## 🛠️ Technology stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| Framework | `discord.py` 2.x (2.5+) |
| Storage | SQLite3 (via `utils/bot_db.py` + per-feature DBs), no external DB server required |
| Async | `asyncio`, `tasks.loop`, persistent `discord.ui` views/buttons |
| Analytics | Custom SQLite analytics service; optional **PostHog** provider; FastAPI + uvicorn dashboard |
| Geo/location | `timezonefinder`, `geopy`, `pycountry_convert`, `pytz` |
| Data/plotting | `numpy`, `pandas`, `matplotlib`, `folium`, `playwright` (charts/maps) |
| Config | `python-dotenv` + env vars |

---

## 🚀 Deployment & installation

The bot runs in any modern async Python environment (local host, VPS, Pterodactyl, Docker).

```bash
# 1. Clone & enter the repository
git clone <repo-url>
cd Village_Game_sept

# 2. (Recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment (see table below)
#    Copy the needed keys into a `.env` file next to config.py

# 5. Run
python main.py
```

1. Add the bot to your server with **Administrator** permission.
2. The host runs `.setup <num_houses>` to bind roles, channels and categories.
3. Use `.help` and `.help {category}` to explore, or `.sh <keyword>` to search commands.

### Environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` (or legacy `TOKEN`) | The bot token. **Required.** |
| `COMMAND_PREFIX` | Command prefix (default `.`). |
| `DATA_DIRECTORY` | Runtime data folder (default `./data`). |
| `ANALYTICS_DASHBOARD_PASSWORD` | Password protecting the web dashboard. |
| `ANALYTICS_DB_PATH` | Override analytics DB location. |
| `POSTHOG_API_KEY` | Optional PostHog analytics key. |

> ⚠️ Never commit `analytics_secrets.py` or your `.env` — both are git-ignored.

---

## 📁 Project layout

```
.
├── main.py                 # Bootstrap: cogs, events, analytics, commands
├── config.py               # Env-based configuration
├── requirements.txt
├── cogs/                   # All game cogs (see reference above)
├── BOTC/                   # Blood on the Clocktower implementation
├── fifa_data/              # World Cup draft/simulation engine
├── utils/
│   ├── bot_db.py           # SQLite storage layer
│   ├── embeds.py           # Embed factories
│   └── analytics/          # Analytics service, providers, instrumentation
├── analytics_dashboard/    # FastAPI web dashboard
├── data/                   # Runtime data (git-ignored)
├── db/                     # SQLite databases (git-ignored)
├── testing/                # Auto-generated test suite
└── assets/                 # Static images
```

---

## 🧪 Tests

Auto-generated command-metadata tests live in `cogs/tests/` and `testing/tests/` and run with `pytest` (`pip install pytest`, then `pytest` from the repo root).

---

## 📌 Contributing

This is a solo/closed project, but PRs are welcome. Keep new features as isolated cogs, register them in `main.py`, add a `setup(bot)` function, and document commands in `help_misc_cog.py`'s `COMMAND_INDEX` and category pages if they should appear in `.help`.