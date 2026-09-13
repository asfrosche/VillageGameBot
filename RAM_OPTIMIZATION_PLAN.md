# Village Game Discord Bot — RAM/Memory Analysis & Optimization Plan

**Date:** 2026-09-11
**Container limits:** RAM 512 MiB (current ~226 MiB) · Disk 5 GiB (current ~1.41 GiB)
**Goal:** Reduce RAM usage as much as possible **without removing functionality**.

---

## 1. Executive Summary

The bot's ~226 MiB footprint is dominated less by game state than by **heavy libraries loaded eagerly at startup** that are only used occasionally. Measured startup bloat:

| What | Est. RAM (peak, measured) | Used how often |
|---|---|---|
| discord.py core | ~31 MiB | always (keep) |
| pandas+numpy (pulled in by FIFA `exec()`) | ~62 MiB | rare (simulations) |
| yt-dlp + curl_cffi + imageio-ffmpeg | ~39 MiB | only `.dl` |
| TimezoneFinder() index | ~22 MiB | only map/timezone cmds |
| folium import | ~10–15 MiB (81 MiB when rendering) | only map cmds |
| numpy alone | ~11 MiB | FIFA engines |
| PIL | ~4–10 MiB | maps/images |

**Conclusion:** Roughly 40% of the 226 MiB is avoidable at boot via lazy loading. Phase 1 (below) targets ~226 → **<150 MiB** with no feature loss.

---

## 2. Startup Memory Inventory (measured deltas)

Baseline Python process floor ≈ 16.6 MiB (Windows measurement; Linux container proportionally lower, but ratios hold).

| Module | Δ RAM measured | Startup? | Source |
|---|---|---|---|
| discord.py + commands | ~31 MiB | Yes | `main.py:7-8` |
| pandas (+numpy) | ~62 MiB peak | **Yes — via exec()** | `fifa_data/services/simulation_service.py:27` |
| numpy alone | ~11 MiB | Yes | `fifa_data/engines/v*_engine.py` |
| yt-dlp + curl_cffi + ffmpeg | ~39 MiB | **Yes** | `cogs/download_cog.py` (module top) |
| TimezoneFinder() | ~22 MiB | **Yes** | `cogs/location_manager.py:104` |
| folium | ~10–15 MiB import; 81 MiB when Map renders | Import yes | `utils/map_generator.py` |
| PIL | ~4–10 MiB | after first image cmd | `utils/image_generator.py` |
| aiohttp | ~3–5 MiB | Yes (discord dep) | — |

---

## 3. Findings

### F1 — `Intents.all()` used in `main.py:93`
- **CURRENT MEMORY IMPACT:** Est. 20–60 MiB (member + presence + message caching across 40 guilds)
- **WHY IT USES MEMORY:** Enables `members`, `presences`, `typing`, `voice_states`, `emojis`, `message_content`; discord.py chunks full member lists + caches presence/status for every member at connect.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Medium — must verify each cog's event needs
- **RECOMMENDED FIX:** Minimal intents. Verified listeners only use guilds, messages, message_content, members, reactions (`on_raw_reaction_add`), message_delete/edit. No cog uses presences/typing/voice/moderation:
  ```python
  intents = discord.Intents.default()
  intents.message_content = True
  intents.members = True
  intents.reactions = True
  ```

### F2 — pandas loaded at boot via FIFA `exec()`
- **CURRENT MEMORY IMPACT:** ~60 MiB measured peak
- **WHY IT USES MEMORY:** `simulation_service.py:20-33` exec's `worldcupsimulator.py[0:RAW_ROSTERS]`, which contains `import pandas as pd` (worldcupsimulator.py:17). pandas is only used inside simulation functions (lines 1997, 2083), never in the exec'd data block.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Low–medium (verify no exec'd symbol uses `pd`)
- **RECOMMENDED FIX:** Strip the pandas import from the exec block (same as line 25 already strips numpy):
  ```python
  data_block = data_block.replace("import pandas as pd\n", "")
  ```

### F3 — yt-dlp imported eagerly
- **CURRENT MEMORY IMPACT:** ~39 MiB measured
- **WHY IT USES MEMORY:** `cogs/download_cog.py` imports `yt_dlp` at module top (also pulls curl_cffi + imageio_ffmpeg bindings).
- **CAN IT BE REDUCED:** Yes
- **RISK:** Low — only needed inside `.dl`
- **RECOMMENDED FIX:** Move `import yt_dlp` into `_download_blocking()` (lazy import); keep safe-import guard for the "not installed" path.

### F4 — `TimezoneFinder()` built in `LocationManager.__init__`
- **CURRENT MEMORY IMPACT:** ~22 MiB measured
- **WHY IT USES MEMORY:** `location_manager.py:104` constructs the heavy index for the whole bot lifetime even if map/timezone cmds never run.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Low
- **RECOMMENDED FIX:** Lazy-init via getter on first `timezone_at` call.

### F5 — folium module import at startup
- **CURRENT MEMORY IMPACT:** ~10–15 MiB import (81 MiB peak only when rendering)
- **WHY IT USES MEMORY:** `location_manager.py` imports `utils/map_generator` at top → folium + HeatMap.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Low
- **RECOMMENDED FIX:** Function-local import of `map_generator`/folium inside map commands.

### F6 — Guild data reload + fresh SQLite connection on EVERY message
- **CURRENT MEMORY IMPACT:** Low steady, high churn (GC pressure / RSS spikes)
- **WHY IT USES MEMORY:** `data_utils.load_guild_data()` → `bot_db.get_guild_data()` opens a **new** `sqlite3.connect` + `json.loads` per call. Called on every `on_message` (main.py:310), edit/delete/join/remove events, and many command paths. Blobs 2–16 KB × 40 guilds — small data, wasteful parsing churn.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Medium — must invalidate cache on save
- **RECOMMENDED FIX:** Single persistent WAL connection + small per-guild LRU (e.g. 80 entries) invalidated on `save_guild_data`.

### F7 — Analytics WAL never checkpointed (4.0 MB live WAL)
- **CURRENT MEMORY IMPACT:** ~2–4 MiB resident + 4 MiB disk; crash-unflush risk
- **WHY IT USES MEMORY:** `utils/analytics/db.py:30-36` thread-local connections stay open for life; WAL auto-checkpoint never triggers at low write volume.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Low
- **RECOMMENDED FIX:** Periodic `PRAGMA wal_checkpoint(TRUNCATE)` (e.g. every 10 min); cap `command_stats.user_ids` JSON arrays.

### F8 — FIFA unbounded `_flag_cache`
- **CURRENT MEMORY IMPACT:** Grows unboundedly (~0.2–0.5 MiB/image, many teams)
- **WHY IT USES MEMORY:** `fifa_data/services/bracket.py:398-426` stores every decoded PIL flag with no eviction cap.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Low
- **RECOMMENDED FIX:** `functools.lru_cache(maxsize=64)` on the loader.

### F9 — Duplicate FIFA data builds
- **CURRENT MEMORY IMPACT:** ~1–2 MiB duplicate (transient per squad-load)
- **WHY IT USES MEMORY:** `simulation_service.py:33` builds TEAM_METRICS/GROUPS at import; `v2_data_loader.load_worldcup_data()` re-exec's the same block on every squad load.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Low–medium
- **RECOMMENDED FIX:** `v2_data_loader` reuses the already-resident dicts from `simulation_service` instead of re-exec'ing.

### F10 — `_FC26_RATINGS` + `_KNOWN_LINEUPS` permanent globals
- **CURRENT MEMORY IMPACT:** ~3–5 MiB + ~1 MiB after first FIFA v2 command (never freed)
- **WHY IT USES MEMORY:** `v2_data_loader.py:21,116` keep full normalized dicts forever; also builds a second normalized-key dict transiently.
- **CAN IT BE REDUCED:** Yes (partially)
- **RISK:** Low
- **RECOMMENDED FIX:** Keep only normalized keys; add a `clear_caches()` hook.

### F11 — BOTC closed-nomination state accumulates
- **CURRENT MEMORY IMPACT:** ~2–5 KB/nomination, **grows** during long games
- **WHY IT USES MEMORY:** `BOTC/cogs/game.py:471-472` `_views`/`_messages` entries removed only on timeout (`bnomtimeout` default off) or new-game start.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Medium (game logic)
- **RECOMMENDED FIX:** Schedule 60 s post-close cleanup of `_messages`/`_views`/`_tasks`.

### F12 — `testing/data/errors.json` full-file parse + rewrite
- **CURRENT MEMORY IMPACT:** ~5–10 MiB spike per `.test` command; rewrite every 10th error
- **WHY IT USES MEMORY:** `testing/models.py` `load_errors()` parses entire file; `flush_errors()` re-serializes with `indent=2`.
- **CAN IT BE REDUCED:** Yes
- **RISK:** Low–medium
- **RECOMMENDED FIX:** Cap stored errors (1000), paginate display, drop indent / use append-only log.

### F13 — Library stats commands fetch all rows (spiky)
- **CURRENT MEMORY IMPACT:** Transient spikes (tens of MiB) on `.stats`-style commands
- **CAN IT BE REDUCED:** Yes — paginate / server-aggregate
- **RISK:** Low (admin-only)
- **RECOMMENDED FIX:** `LIMIT/OFFSET` + SQL-side aggregation.

### F14 — Nominations persistent aiosqlite connection
- **CURRENT MEMORY IMPACT:** ~200–400 KB — acceptable. **No change.**

### F15 — 44 cogs instantiated at startup
- **CURRENT MEMORY IMPACT:** Cog instances ~1–2 KB each — not the problem. Their import-time side effects (F2–F5) are.

---

## 4. Top 10 Changes — ranked by RAM saved / risk / effort

| # | Change | Est. RAM saved | Risk | Effort |
|---|---|---|---|---|
| 1 | Lazy pandas (strip from FIFA exec block) | ~50–60 MiB peak | low–med | very low |
| 2 | Minimal intents | ~20–60 MiB | medium | very low |
| 3 | Lazy yt-dlp import | ~30–39 MiB | low | low |
| 4 | Lazy TimezoneFinder | ~15–22 MiB | low | low |
| 5 | Lazy folium import | ~10–15 MiB import | low | low |
| 6 | Guild-data LRU + single SQLite conn | ~5–15 MiB steady | medium | medium |
| 7 | Analytics WAL checkpoint + cap user_ids | ~2–6 MiB | low | low |
| 8 | Bound `_flag_cache` | prevents unbounded growth | low | very low |
| 9 | BOTC nomination cleanup | prevents grow | medium | low |
| 10 | Cap/paginate errors.json | 5–10 MiB spikes | low–med | low–med |

---

## 5. Phase 1 Plan — target ~226 → <150 MiB (keep all functionality)

### Step 1 — Kill boot-time import bloat (biggest, lowest risk)
1. `fifa_data/services/simulation_service.py:25` — strip `import pandas as pd\n` from exec block → **~50 MiB**
2. `cogs/download_cog.py` — lazy `import yt_dlp` → **~39 MiB**
3. `cogs/location_manager.py:104` — lazy `TimezoneFinder` → **~22 MiB**
4. `cogs/location_manager.py` — function-local folium/map import → **~10–15 MiB**
5. `main.py:93` — minimal intents → **~20–60 MiB**

Expected combined effect: **~60–100 MiB** peak-resident drop.

### Step 2 — Stop churn/growth (medium, keep functionality)
6. Guild data: single WAL connection + LRU (invalidate on save)
7. Analytics: periodic `wal_checkpoint(TRUNCATE)`
8. `_flag_cache` → `lru_cache(maxsize=64)`
9. BOTC nomination post-close cleanup (60 s delay)
10. errors.json: cap 1000 + paginate

### Step 3 — Verify
- Start bot; watch RSS at idle 10–20 min → should settle well under 150 MiB
- One live test per command family (BOTC, FIFA, `.map`, `.dl`, economy, library search)
- Re-run `pytest`

**Recommended order:** Step 1 sync (`1 → 3 → 4 → 2 → 5`), each independently reversible, test between steps.