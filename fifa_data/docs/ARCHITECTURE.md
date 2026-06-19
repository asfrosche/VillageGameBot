# Architecture: World Cup 2026 Simulation

## Directory Structure

```
fifa_data/
+-- __init__.py                          # Top-level exports: run_simulation, sim_match, etc.
+-- worldcupsimulator.py                 # ~2163 lines: RAW_ROSTERS, GROUPS, TEAM_METRICS, legacy engine

+-- models/
|   +-- __init__.py                      # Exports: Player, Squad, TeamStrength, Availability, role_rating
|   +-- player.py                        # Player dataclass (frozen) + Availability
|   +-- squad.py                         # Squad dataclass + substitution logic
|   +-- team_strength.py                 # Formation parsing, role assignment, formula weights
|   +-- dynamic_state.py                 # DynamicState + ComponentScore dataclasses (V3)

+-- engines/
|   +-- __init__.py                      # Exports: MatchEngine, V1EloMatchEngine, V2PlayerMatchEngine
|   +-- base_engine.py                   # Abstract MatchEngine ABC
|   +-- v1_elo_engine.py                 # V1: team-level Elo/PELE Poisson engine
|   +-- v2_player_engine.py              # V2: player-level attribute/role engine
|   +-- v3_dynamic_engine.py             # V3: dynamic state (chemistry/form/momentum/etc.)

+-- services/
|   +-- __init__.py                      # (empty)
|   +-- orchestrator.py                  # TournamentOrchestrator (group stage + knockout bracket)
|   +-- v2_data_loader.py                # RAW_ROSTERS -> Player -> Squad pipeline + FC26 injection
|   +-- simulation_service.py            # Facade: loads data, creates engine, runs orchestrator
|   +-- match_analytics.py               # Fantasy analytics (top scorers, form, differentials)
|   +-- fantasy_service.py               # FantasyService: play.fifa.com integration, draft matching
|   +-- fc26_fetcher.py                  # EA FC26 ratings scraper (index builder, matcher, fetcher)
|   +-- chemistry_service.py             # V3: club pairing chemistry evaluation
|   +-- experience_service.py            # V3: caps/World Cup experience evaluation
|   +-- form_service.py                  # V3: fantasy form/points evaluation
|   +-- momentum_service.py              # V3: win streak/goal difference evaluation
|   +-- continuity_service.py            # V3: lineup stability evaluation
|   +-- leadership_service.py            # V3: captain/veteran leadership evaluation

+-- scripts/
|   +-- add_ratings.py                   # Add ELO-based ratings to matches
|   +-- analyze_team_strength.py         # Diagnostic: rank all 48 teams by V2/V3 ratings
|   +-- discover_fc26_api.py             # EA website API discovery
|   +-- enrich_draft.py                  # Enrich draft data with FC26 ratings
|   +-- fc_ratings_pipeline.py           # FC26 ratings pipeline orchestration
|   +-- fetch_matches.py                 # Fetch real match results from FIFA API
|   +-- headless_sim.py                  # Standalone CLI tournament runner
|   +-- populate_fc26_ratings.py         # Batch: gather names -> match -> fetch -> export
|   +-- re_match_unrated.py              # Re-match unrated lineup players
|   +-- re_match_unrated_v2.py           # V2: fuzzy matching + fallback fetch
|   +-- re_match_v3.py                   # V3: precise token_sort_ratio re-matching

+-- data/
|   +-- calibration_config.json          # V3.1 calibration parameters
|   +-- club_links.json                  # 929 player->club mappings from FC26
|   +-- countries.json                   # Country metadata
|   +-- draft_data.json                  # Fantasy draft teams
|   +-- fc26_lineup_analysis.json        # Detailed analysis of missing players
|   +-- fc26_lineup_missing.json         # Lineup players still unrated
|   +-- fc26_missing_players.json        # WC players absent from FC26
|   +-- fc26_new_matches.json            # FC26 match data
|   +-- fc26_player_index.json           # EA index of ~18,000 players
|   +-- fc26_ratings.json                # ~984 FC26 player ratings
|   +-- fc26_ratings_cache.json          # Raw EA cache by player ID
|   +-- lineups_with_ratings.txt         # Lineups with FC26 ratings
|   +-- matches.json                     # Completed + upcoming matches with lineups
|   +-- matches_lineups.json             # Match lineup data
|   +-- national_strength_modifiers.json # Per-team national strength modifiers
|   +-- player_experience.json           # 1245 players with caps/WCs/captain status
|   +-- player_relationships.json        # Configurable partnerships
|   +-- players.json                     # FIFA fantasy players (44k lines)
|   +-- round1_lineups.txt               # All 24 Round 1 lineups with FC26 ratings
|   +-- squads.json                      # Team/squad definitions (48 teams)
|   +-- squads.json                      # Team/squad definitions

+-- docs/
|   +-- ARCHITECTURE.md                  # This file
|   +-- FC26_RATINGS_INTEGRATION.md      # FC26 ratings integration docs
|   +-- HOW_TO_UPDATE.md                 # Update guide
|   +-- PLAYER_POINTS_PLAN.md            # Player points plan
|   +-- SIMULATION_CALIBRATION.md        # V3.1 calibration results
|   +-- V3_ARCHITECTURE.md               # V3 dynamic engine architecture
```

---

## Data Flow

```
worldcupsimulator.py (RAW_ROSTERS)
         |
         v
v2_data_loader.py:_load_raw_rosters()       players.json + squads.json
         |                                          |
         +--- _build_players() ---------------------+
                   |                         (fuzzy match RAW_ROSTERS -> fantasy data)
                   v
              Player objects
                   |
         _apply_fc26_ratings()  <---  fc26_ratings.json
                   |                (overwrites attributes & roster_rating)
                   v
              Squad objects  --->  V2PlayerMatchEngine
                                        |
                              TeamStrength builder
                              (role assignment + formula weights)
                                        |
                              simulate_match(team1, team2)
                                        |
                              TournamentOrchestrator.run()
                                        |
                              Result: { groups, knockout, champion }
```

---

## Player Model

```python
@dataclass(frozen=True)
class Player:
    name: str                           # Full name
    country: str                        # National team
    positions: tuple[str, ...]          # ("GK",), ("DEF", "MID"), etc.
    attributes: dict[str, float]        # Simulation attributes (pace, finishing, etc.)
    availability: Availability          # Available, injured, suspended
    fantasy_id: int | None              # FK -> players.json
    squad_id: int | None                # FK -> squads.json
    roster_rating: float | None         # From RAW_ROSTERS tier rating
    roster_tier: str | None             # SUPERSTAR | STAR | STARTER | WISSEL | BASIS | RESERVE
    price: float                        # Fantasy price
    status: str | None                  # "playing", "transferred", etc.
    stats: dict[str, object]            # Fantasy stats (totalPoints, form, etc.)
```

Players without FC26 data get `attributes={}` — no synthetic fallback.

---

## Squad Model

```python
@dataclass
class Squad:
    country: str
    players: list[Player]               # Full squad
    formation: str                      # "4-3-3", "4-2-3-1", etc.
    preferred_starting_xi: list[Player] # From real matches or selection logic
    current_starting_xi: list[Player]   # Mutable: simulation can modify

    # Substitution: finds best replacement by role -> position -> any,
    # sorted by role_rating * roster_rating * price descending
```

---

## Match Engine Hierarchy

```
MatchEngine (ABC)
  |-- simulate_match(team1, team2, can_draw) -> (goals1, goals2)
  |
  +-- V1EloMatchEngine
  |     Uses TEAM_METRICS["ELO"] + TEAM_METRICS["PELE"]
  |     Base goals = 1.1 * upset_factor(rating_delta)
  |     Goals ~ Poisson(lambda)
  |     Draw: extra time (Poisson * 0.3), then penalty shootout
  |
  +-- V2PlayerMatchEngine
        Loads Squad objects via v2_data_loader
        Builds TeamStrength (attack, midfield, defense, goalkeeper)
        Formula:
          def_index = 0.70 * defense + 0.30 * goalkeeper
          attack_ratio = attack / max(def_index, 1.0)
          midfield_mod = 1.0 + 0.25 * (midfield_diff / 100)
          lambda = base_goals * attack_ratio * midfield_mod
        Same Poisson + draw resolution as V1
```

---

## Role System (team_strength.py)

Formation string -> position counts. Players assigned to 7 roles:

| Role | Key Weights |
|------|------------|
| ST | finishing(0.35), positioning(0.20), shot_power(0.15), pace(0.15), composure(0.15) |
| WINGER | pace(0.30), dribbling(0.25), crossing(0.20), finishing(0.15), vision(0.10) |
| CM | passing(0.30), vision(0.20), dribbling(0.20), stamina(0.15), defending(0.15) |
| DM | defending(0.30), interceptions(0.25), passing(0.20), physical(0.15), stamina(0.10) |
| FB | pace(0.25), defending(0.20), crossing(0.20), stamina(0.15), passing(0.10), dribbling(0.10) |
| CB | defensive_awareness(0.30), tackling(0.25), strength(0.15), pace(0.15), reactions(0.15) |
| GK | reflexes(0.30), diving(0.25), positioning(0.20), handling(0.15), kicking(0.10) |

Missing attributes default to 70.0.

---

## Tournament Flow

```
TournamentOrchestrator.run()
  1. Load real results from matches.json (completed -> lineup -> score)
  2. For each group (A-L, 12 groups x 4 teams):
       Play 6 round-robin matches (real results used, rest simulated)
       Sort by: points > GD > GF
  3. Top 2 per group + 8 best third-placed advance to Round of 32
  4. Single-elimination knockout:
       R32 -> R16 -> QF -> SF -> Final + 3rd-place playoff
  5. Returns {
       groups: { GroupA: [...standings...], ... },
       knockout: { round_of_32: [...], round_of_16: [...], ... },
       champion: "TeamName",
       match_debugs: [...]
     }
```

## Simulation Service

```python
run_simulation(model="v1" | "v2", debug=False)
  - "v1": V1EloMatchEngine (team ratings only, no lineups)
  - "v2": V2PlayerMatchEngine (loads FC26 ratings, lineups, role system)
```

---

## EA FC26 Ratings Pipeline

```
1. discover_fc26_api.py  ->  Identify EA website structure
2. fc26_fetcher.py       ->  Fc26Fetcher class:
     - build_player_index()    ->  fc26_player_index.json (~18k players)
     - fuzzy_match(name)      ->  token_sort_ratio >= 85
     - fetch_player_ratings() ->  __NEXT_DATA__ from player detail page
     - Map EA stats -> sim attributes (34 mapped keys)
3. populate_fc26_ratings.py  ->  Gather 1273 WC names -> match -> fetch -> export
4. re_match_*.py             ->  Iterative re-matching for unrated players
```

### Name Matching Strategy
- `normalize_name()`: NFKD -> ascii -> lowercase -> alphanumeric + spaces
- Primary: exact match after normalization
- Secondary: `rapidfuzz.token_sort_ratio >= 85`
- Korean names handled via token_sort (Son Heung-min <-> Heung Min Son)
- Known aliases stored directly in `fc26_ratings.json` (Andy Robertson -> Andrew Robertson)

### Coverage (Current)
- **fc26_ratings.json**: 984 entries (969 real + 15 aliases)
- **Lineup coverage**: 397/520 slots (76.3%)
- **Unrated**: 123 unique players (mostly non-FC26 leagues)

---

## Key JSON Schemas

### matches.json
```json
{
  "last_updated": "...",
  "completed_count": 24,
  "upcoming_count": 35,
  "completed": [{
    "id": "match_id",
    "group": "Group A",
    "home": { "name": "Mexico", "score": 2, "formation": "4-3-3", "lineup": ["Player1", ...] },
    "away": { ... }
  }]
}
```

### fc26_ratings.json
```json
{
  "Mohamed Salah": {
    "overall": 91,
    "attributes": {
      "pace": 89.0, "finishing": 92.0, "passing": 86.0, ...
    },
    "position": "RM",
    "team": "Liverpool",
    "nationality": "Egypt"
  }
}
```

### fc26_player_index.json
```json
{
  "mohamed salah": {
    "id": 209331,
    "fullName": "Mohamed Salah",
    "overallRating": 91,
    "pace": 89, "shooting": 88, "passing": 86, "dribbling": 90, "defending": 45, "physical": 76
  }
}
```

---

## Entry Points

| Command | What It Does |
|---------|-------------|
| `python headless_sim.py` | Run CLI tournament simulation |
| `from . import run_simulation` | Python API: `run_simulation(model="v2")` |
| `python populate_fc26_ratings.py` | Refresh FC26 ratings from EA website |
| `python fc26_fetcher.py` | Build/update player index |
| `python re_match_v3.py` | Re-match unrated lineup players |
