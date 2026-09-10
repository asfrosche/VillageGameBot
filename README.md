# Village Game Bot 🏡

Welcome to the **Village Game Bot** repository! This is a production-grade, highly-modular Discord bot designed from the ground up to host, automate, and manage large-scale **Discord Mafia & Social Deduction** games. 

Rather than relying on manual moderation, this bot transforms a Discord server into a living "map." Players physically navigate channels (rooms), interact with items, lock/unlock doors, whisper, and participate in a rigid phase structure, while the Game Masters (Overseers) have complete, centralized control.

---

## 🧩 Complete System Architecture & Modules (Cogs)

The bot is constructed using a robust, cog-based architecture (`discord.ext.commands.Cog`). Each cog handles a completely isolated aspect of the game mechanics, ensuring a scalable and maintainable codebase.

Here is the complete, comprehensive list of all cogs driving the Village Game Bot:

### 1. `setup_cog.py` (The Foundation)
Responsible for initializing the game framework.
* **Role & Channel Binding:** Links server categories, specific roles (Alive, Dead, Alt, Spectator), and log channels to the bot's internal database.
* **Game Rules Engine:** Configures rules like whether dead players count towards room limits, whether whispers are anonymous, and auto-join knock mechanics.
* **Configuration:** Exposes commands like `.setup`, `.roleset`, `.categoryset`, and `.settings`.

### 2. `moving_cog.py` (Navigation Engine)
The heart of the player experience. Transforms channels into a physical map.
* **Locomotion:** Players use `.move <house>` to transfer between rooms. The bot dynamically strips read/write permissions from the old room and grants them to the new room.
* **Knocking System:** If a room is closed, players can `.knock`. Those inside are prompted to type `open` or `refuse`. Refusals can optionally leak who is inside based on game settings.
* **Stealth Mode:** Appending `stealth` to commands allows movement without triggering automated "Player joined/left" announcements.

### 3. `home_cog.py` (Spawn & Reset Logic)
Manages the "base" states of the players.
* **Random Initialization:** Automatically assigns players to randomized houses and private RoleChats at the start of a game.
* **Phase Resets:** With a single command (`.home return`), Overseers can snap every player out of their current locations and instantly teleport them back to their assigned homes.

### 4. `handling_cog.py` (Dynamic World Building)
Manages the physical destruction and creation of the map in real-time.
* **Map Events:** Use `.destroy` to simulate an explosion or map collapse—it removes everyone, moves the channel to an inaccessible category, and broadcasts a global event. Use `.rebuild` to bring it back.
* **Private Chats:** Overseers can dynamically spin up temporary rooms using `.newpc` and assign an owner using `.setowner`. The owner can later `.end` the chat to kick everyone out.

### 5. `voting_cog.py` (Core Social Deduction)
Handles the primary mechanics of Mafia (voting and lynching).
* **Vote Tracking:** A robust system allowing players to `.vote`, `.abstain`, or `.removevote`.
* **Abilities:** Supports ability-driven interactions like `.manipulate` (forcing a player's vote elsewhere secretly).
* **Tallying:** Generates comprehensive vote tallies (`.votelist`) and allows resetting after the execution.

### 6. `nominations_cog.py` (Economy & Trials)
An advanced variant of voting tied to an economy system.
* **Token Economy:** Players are granted tokens (`.addtokens`, `.tokens`).
* **Trial System:** Players spend tokens to `.accuse` someone. This spins up a dedicated text channel for the trial.
* **Interventions:** Other players can spend tokens to `.intervene` and inject messages into the trial channel. Overseers can halt trials with `.stopvotes`.

### 7. `item_drop_cog.py` (Interactive Drops)
A fully persistent, SQLite-backed interactive game system.
* **Interactive Spawning:** Overseers use `.dropitem` to spawn a rich UI embed inside a room representing an item (e.g., "Wooden Key").
* **Atomic Concurrency:** Uses `discord.ui.View` persistent buttons and atomic database transactions to ensure race conditions (two people clicking at the exact same millisecond) never result in duplicate item claims.
* **Expiration Engine:** Runs a continuous `tasks.loop` to monitor drops, disabling buttons automatically when the expiration time hits.

### 8. `utility_cog.py` (Game Master Tools)
A suite of commands designed to keep the game flowing.
* **Phase Shifts:** `.day` and `.night` instantly bulk-modify permissions across the server, locking or unlocking the map.
* **Sweeping & Logging:** `.broom` bulk-deletes messages while preserving pins. `.log` takes a full transcript of a channel and outputs it cleanly to the Overseer channel.
* **Death Handling:** `.deadrole` executes a player—revoking access, appending them to the graveyard, moving their chat, and pinning a customized "corpse" message in the room they died in.

### 9. `meetupmatrix.py` (The Meetup Matrix)
A highly requested feature for social deduction hosts.
* **Passive Tracking:** Silently records every time two players exist in the same room simultaneously during a specific phase.
* **Generation:** Spits out a visual "Meetup Matrix" showing exactly who interacted with whom, drastically cutting down manual host labor.

### 10. `lists_cog.py` & `infos_cog.py` (Information Displays)
* **Lists:** Maintains the `.houselist` (which rooms are currently open), the `.playerlist` (who is currently alive), and the `.deadlist` (graveyard with roles).
* **Infos:** Allows hosts to append text descriptions to channels (e.g., "The kitchen smells like gas") via `.info`.

### 11. `other_cog.py` (The Hub)
Contains global commands that don't fit into specific mechanics.
* **Locators:** `.where` finds a specific player's exact channel. `.who` lists everyone in the current channel. `.loc` dumps a global view of all populated rooms.
* **Fun & Timing:** Contains `.ping`, global `.narrate`, random `.roll`, and asynchronous countdown `.timer` commands.
* **Help System:** Houses the dynamic, dropdown-based UI for `.help`.

---

## 🔍 Additional Sub-Systems & Specialty Cogs

These modules handle specific subset features, minigames, or behind-the-scenes logging.

### 12. `actions_logging_cog.py` (Bot Mentions Interceptor)
* **Approval Logging:** Intercepts bot/role mentions inside private player channels, sending them to a central GM log.
* **Interactive Controls:** Embeds `Done` and `Cancel` buttons allowing Game Masters to track and mark player actions as complete in real-time.

### 13. `library_cog.py` (Game Codex & Searching)
* **Role/Rule Directory:** Hosts a massive embedded archive of game roles, definitions, rules, and alignment lists.
* **Safe Formatting:** Utilizes character limits split safely across multiple fields to prevent Discord API characters overflow errors.

### 14. `meeting_cog.py` (Meeting Room Scheduler)
* **Scheduled Collisions:** Allows hosts to lock and unlock designated meeting locations, controlling when group discussions can occur.

### 15. `overseer_cog.py` (GM Override Panels)
* **Admin Controls:** Gives Game Masters special tools to directly override player permissions, edit stats, manually force move updates, and oversee the entire game flow.

### 16. `estate_cog.py` (Estate Mapping & Coordinates)
* **Large Property Attributes:** Manages player ownership of estates, coordinates, dynamic mapping, and room permissions for larger properties outside the standard home layout.

### 17. `send_role.py` (Confident Role Dispatcher)
* **Target Channels:** Allows hosts to set a private destination channel using `.settarget` and dispatch encrypted or plain-text role files dynamically with `.sendrole` or `.sr`.

### 18. `tracker_cog.py` (Activity Metrics)
* **Stat Tracker:** Keeps metrics on message counts across specified channels. Enables commands like `.statss`, `.start_tracking`, and `.stop_tracking`.

### 19. `privatecommands_cog.py` (Developer & Fun Triggers)
* **Guild Diagnostics:** Gives the developer (Bidet) commands to list guilds, generate invitations, leave servers, and simulate user webhooks (`.fake`).
* **Interaction Commands:** Includes playful triggers like `.amore` and `.fart`.

### 20. `aux_battle.py` (Combat & Battle Engine)
* **Conflict Resolution:** Helper algorithms and commands to roll, resolve, and output battlefield states or user fights during physical conflicts in the game.

### 21. `senet_cog.py` & `soldati_cog.py` (Interactive Minigames)
* **Senet Game:** Features a fully playable implementation of the ancient board game Senet directly in Discord using interactive views.
* **Soldati Game:** Handles the special "Soldati" minigame or combat scenario to decide outcomes dynamically.

### 22. `bday.py` (Birthday Reminders)
* **Birthday tracker:** Simple utilities to register and announce player birthdays.

### 23. `location_manager.py` & `game_manager.py` (Core Coordinators)
* Background manager systems tracking channel transitions and player mappings in memory.

---

## 🛠️ Technology Stack

* **Language:** Python 3.12+
* **Framework:** `discord.py` 2.x
* **Databases:** 
  * `item_drops.db` (SQLite3) for persistent, transactional item drops.
  * Local JSON datastores for guild configurations and volatile phase data.
* **Async Engine:** Heavy utilization of `asyncio` for simultaneous background expiration checking and dynamic UI updating without blocking the command execution stream.

---

## 🚀 Deployment & Installation

The bot is designed to run in modern asynchronous environments (e.g., local host, Pterodactyl Panel, Docker).

1. Clone the repository to your host.
2. Install the necessary packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your `.env` or configuration file with the bot token.
4. Run the main initialization script:
   ```bash
   python main.py
   ```
5. Once the bot is in your server, assign it the **Administrator** permission.
6. The host must run `.setup` to map the server categories to the bot's datastore.
