# V1 World Cup Simulator Architecture Analysis

## 1. Overall Flow

The simulator has two active V1 paths:

1. **Structured/API path**: `fifa_data/services/simulation_service.py`
2. **CLI/headless path**: `fifa_data/headless_sim.py`
3. **Interactive notebook/UI path**: `fifa_data/worldcupsimulator.py`

The core tournament data lives in `worldcupsimulator.py`. The service and headless scripts load the data portion of that file by reading it as text, cutting off before `RAW_ROSTERS`, and executing the data block. This gives them access to `GROUPS`, `TEAM_METRICS`, `FIFA_CODES`, `ISO_CODES`, and helper constants without importing the full notebook UI code.

### API/service flow

`simulation_service.py` is the cleanest entry point for the app.

1. `_load_worldcup_data()` loads `worldcupsimulator.py` text.
2. It executes only the pre-`RAW_ROSTERS` data block.
3. `update_elo_from_matches()` reads `matches.json` and mutates `TEAM_METRICS` using completed results.
4. `run_simulation()` builds real group results from `matches.json`, simulates remaining group matches, ranks teams, chooses the top eight third-place teams, resolves the 32-team bracket, simulates knockout matches, and returns a structured dictionary.

Main return shape from `run_simulation()`:

```python
{
    "groups": groups_data,
    "third_placed": all_third,
    "best_thirds": best_thirds,
    "knockout": KO_MATCHES,
    "third_place": third_place,
    "champion": champion,
    "stats": stats,
}
```

### Headless flow

`headless_sim.py` performs the same broad process as the service path but prints a formatted bracket and champion to stdout. It is not a reusable API; it is an execution script.

### Interactive notebook/UI flow

`worldcupsimulator.py` contains a richer, stateful simulation engine designed for `ipywidgets`.

1. Tournament data and roster data are defined at module load.
2. `trigger_global_update_pipeline()` reads manual/simulated group scores from widget registries, computes standings, wildcard third-place advancement, and bracket placements.
3. `trigger_global_simulation_pipeline()` simulates group matches and knockout matches, writes scores back into widgets, and refreshes the bracket.
4. `run_master_calculation_pipeline()` is the central UI reconciliation function. It recomputes standings, third-place slots, bracket nodes, champion badge, and status board.
5. `run_constrained_monte_carlo_pipeline()` runs repeated tournament loops and aggregates probabilities by finish stage.

## 2. Project Structure

Relevant file tree:

```text
fifa_data/
  worldcupsimulator.py        # Primary V1 data + interactive notebook simulation engine
  headless_sim.py             # CLI/headless copy of V1 tournament simulation
  matches.json                # Completed/upcoming match data from FIFA API
  players.json                # FIFA fantasy player data
  squads.json                 # FIFA fantasy squad/country metadata
  fetch_matches.py            # Fetches matches + fantasy data from FIFA APIs
  enrich_draft.py             # Matches draft picks to FIFA player records
  services/
    simulation_service.py     # Reusable API/service wrapper for V1 simulation
    match_analytics.py        # Player/form analytics backed by players.json + matches.json
    fantasy_service.py        # Fantasy data loading, matching, and scoring helpers
```

### `worldcupsimulator.py`

This is the source of truth for V1 data and the richer interactive engine.

Important contents:

- `GROUPS`: group allocations.
- `FIFA_CODES` / `ISO_CODES`: display code and flag mappings.
- `TEAM_METRICS`: Elo and PELE ratings.
- `MATCHES_TEAM_MAP`: match-name normalization.
- `update_elo_from_matches()`: mutates team ratings from completed matches.
- `RAW_ROSTERS`: manually curated player rosters used by the interactive match engine.
- `simulate_match()`: richer player-aware V1 match engine.
- `run_master_calculation_pipeline()`: UI standings/bracket reconciliation.
- `trigger_global_simulation_pipeline()`: one-tournament simulation through the UI.
- `run_constrained_monte_carlo_pipeline()`: Monte Carlo aggregation through the UI.

### `headless_sim.py`

A lightweight executable simulator. It:

- Loads `worldcupsimulator.py` data by `exec`.
- Updates Elo/PELE from `matches.json`.
- Simulates group tables.
- Resolves third-place slots.
- Simulates knockout rounds.
- Prints the final bracket and champion.

### `simulation_service.py`

The app-facing V1 service. It mirrors the headless flow but returns structured JSON-friendly data instead of printing. It is the best file to preserve as the stable integration point for other code.

### `match_analytics.py`

Uses `players.json`, `squads.json`, and `matches.json` to produce player and match analytics. It is not part of the tournament simulation engine but is useful for V2 player feature extraction.

### `fantasy_service.py`

Loads/matches FIFA fantasy player data. It is useful for V2 because it already normalizes player names, maps squads, and extracts form/points.

### `fetch_matches.py`

Fetches match and fantasy data from FIFA APIs and writes:

- `matches.json`
- `players.json`
- `squads.json`

## 3. Match Engine

There are two match engines in V1.

### Simplified service/headless engine

The simplified engine exists in:

- `fifa_data/services/simulation_service.py:71`
- `fifa_data/headless_sim.py:51`

Function:

```python
def sim_match(t1, t2, can_draw=True):
    r1 = (TEAM_METRICS[t1]["ELO"] + TEAM_METRICS[t1]["PELE"]) / 2
    r2 = (TEAM_METRICS[t2]["ELO"] + TEAM_METRICS[t2]["PELE"]) / 2
    raw_delta = r1 - r2
    upset_factor = max(0.4, min(1.6, 1.0 + (raw_delta / 800.0)))
    lam1 = 1.1 * upset_factor
    lam2 = 1.1 * (2.0 - upset_factor)
    g1 = poisson(max(0.05, lam1))
    g2 = poisson(max(0.05, lam2))
    if not can_draw and g1 == g2:
        g1_et = poisson(lam1 * 0.3)
        g2_et = poisson(lam2 * 0.3)
        if g1_et != g2_et:
            g1 += g1_et
            g2 += g2_et
        else:
            if random.random() < (0.50 + (raw_delta * 0.0005)):
                g1 += 1
            else:
                g2 += 1
    return int(g1), int(g2)
```

Inputs:

- `t1`: home/team 1 name.
- `t2`: away/team 2 name.
- `can_draw`: whether a draw is allowed.

Output:

- `(g1, g2)`: final integer score.

Expected goals:

```python
r1 = (ELO_t1 + PELE_t1) / 2
r2 = (ELO_t2 + PELE_t2) / 2
raw_delta = r1 - r2
upset_factor = clamp(1.0 + raw_delta / 800, 0.4, 1.6)

lam1 = 1.1 * upset_factor
lam2 = 1.1 * (2.0 - upset_factor)
```

Score generation:

```python
g1 = poisson(max(0.05, lam1))
g2 = poisson(max(0.05, lam2))
```

Knockout tie handling:

- If `can_draw=False` and regulation is tied, extra time goals are sampled from `lam * 0.3`.
- If extra time is also tied, the stronger side by `raw_delta` gets a small probability boost:
  `random.random() < 0.50 + raw_delta * 0.0005`.

### Rich interactive notebook engine

The richer engine is:

- `fifa_data/worldcupsimulator.py:847`

Function signature:

```python
def simulate_match(t1, t2, can_draw=True, is_group=False, group_id=None):
```

Inputs:

- `t1`, `t2`: team names.
- `can_draw`: whether regulation draw is allowed.
- `is_group`: whether this is a group-stage match.
- `group_id`: group identifier for logs.

Output:

```python
(points_for_t1, points_for_t2), actual_winner, g1, g2, extra_str, incidents
```

Important behavior:

- It can return cached `LIVE_RESULTS` for group matches.
- It builds starting XIs from `REAL_SQUADS`.
- It simulates red cards, injuries, tactical substitutions, and form swings.
- It computes lineups' offensive/defensive integrals.
- It uses Elo/PELE plus host advantage plus lineup ratios to calculate lambdas.
- It updates form factors after the match.

Core expected-goal calculation:

```python
base1 = TEAM_METRICS.get(t1, {"ELO": 1500, "PELE": 1500})
r1 = (base1["ELO"] + base1["PELE"]) / 2 + HOST_ADVANTAGE.get(t1, 0)
base2 = TEAM_METRICS.get(t2, {"ELO": 1500, "PELE": 1500})
r2 = (base2["ELO"] + base2["PELE"]) / 2 + HOST_ADVANTAGE.get(t2, 0)

raw_delta = r1 - r2
upset_factor = max(0.4, min(1.6, 1.0 + (raw_delta / 800.0)))

lineup_offence_modifier_t1 = (off1 / def2) * form_off_factor.get(t1, 1.0)
lineup_offence_modifier_t2 = (off2 / def1) * form_off_factor.get(t2, 1.0)

lam1 = 1.1 * upset_factor * lineup_offence_modifier_t1
lam2 = 1.1 * (2.0 - upset_factor) * lineup_offence_modifier_t2
```

Poisson score generation:

```python
g1 = poisson(max(0.05, lam1))
g2 = poisson(max(0.05, lam2))
```

## 4. Team Strength Model

### Where ratings are stored

Team ratings are stored in `TEAM_METRICS` in `worldcupsimulator.py:68`.

Example shape:

```python
TEAM_METRICS = {
    "Spain": {"ELO": 2200, "PELE": 2070},
    "Argentina": {"ELO": 2101, "PELE": 2064},
    ...
}
```

The service loads these ratings dynamically from `worldcupsimulator.py` in `simulation_service.py:17`.

### Rating formula

The simplified V1 engine uses an even Elo/PELE blend:

```python
rating = (ELO + PELE) / 2
```

The interactive engine also adds host advantage:

```python
rating = (ELO + PELE) / 2 + HOST_ADVANTAGE.get(team, 0)
```

Current host advantage is defined at `worldcupsimulator.py:660`:

```python
HOST_ADVANTAGE = {"United States": 20, "Mexico": 20, "Canada": 20}
```

### Elo update from completed matches

`update_elo_from_matches()` exists in:

- `worldcupsimulator.py:125`
- `simulation_service.py:34`
- `headless_sim.py:16`

Formula:

```python
r1 = (ELO_home + PELE_home) / 2
r2 = (ELO_away + PELE_away) / 2
we1 = 1 / (1 + 10 ** ((r2 - r1) / 400))

w1 = 1.0 if home wins else 0.0 if away wins else 0.5

g_mult = 1.0 if goal_diff <= 1 else 1.5 if goal_diff == 2 else 2.0
delta = (w1 - we1) * g_mult

ELO_home += 20 * delta
ELO_away -= 20 * delta
PELE_home += 20 * delta
PELE_away -= 20 * delta
```

Important constants:

- `k_elo = 20`
- `k_pele = 20`
- Expected score denominator: `400`
- Goal multiplier:
  - `1.0` for 0-1 goal difference
  - `1.5` for exactly 2-goal difference
  - `2.0` for 3+ goal difference

### Other factors in the rich interactive engine

The interactive engine adds player-level and match-event modifiers:

- Starting XI selection from `RAW_ROSTERS`.
- Positional ratings:
  - GK
  - DF
  - MF
  - AT
- Red cards: 3.5% chance per team.
- Injuries: 4.5% chance per team.
- Tactical substitutions: 3 to `5 - subs_used`.
- Random form modifiers:
  - 15% chance per match if fewer than 8 active form modifiers.
  - Positive or negative Gaussian modifier around `5.5`.
  - Clamped to `[-10, 10]`.
- Form factors:
  - `form_off_factor`
  - `form_def_factor`
  - Clamped to `[0.6, 1.4]`.

## 5. Core Data Models

V1 is mostly dictionary-based; there are no formal dataclasses.

### Team

Represented by team name string plus rating dictionary.

```python
"Spain": {"ELO": 2200, "PELE": 2070}
```

In the interactive engine, a team also has:

- `FIFA_CODES[team]`
- `ISO_CODES[team]`
- `REAL_SQUADS[team]`
- optional `HOST_ADVANTAGE[team]`

### Match

Completed match JSON shape in `matches.json`:

```json
{
  "id": "400021443",
  "date": "2026-06-11T19:00:00Z",
  "stage": "First Stage",
  "group": "Group A",
  "home": {
    "name": "Mexico",
    "score": 2,
    "id": "43911"
  },
  "away": {
    "name": "South Africa",
    "score": 0,
    "id": "43883"
  },
  "winner": "43911",
  "status": 0
}
```

Simulated group match shape in `simulation_service.py`:

```python
{
    "home": t1,
    "away": t2,
    "home_goals": g1,
    "away_goals": g2,
    "home_goal_minutes": hg,
    "away_goal_minutes": ag,
    "is_real": False,
}
```

Simulated knockout match shape in `simulation_service.py`:

```python
{
    "home": t1,
    "away": t2,
    "home_goals": g1,
    "away_goals": g2,
    "home_goal_minutes": hg,
    "away_goal_minutes": ag,
    "winner": winner,
    "is_real": False,
}
```

Interactive match result shape from `simulate_match()`:

```python
points, winner, g1, g2, extra_str, incidents
```

### Group standings

Dictionary keyed by team name:

```python
{
    "pts": points,
    "gd": goal_difference,
    "gf": goals_for,
    "ga": goals_against,  # service only
    "name": team_name,    # interactive only
    "group": group_id     # interactive only
}
```

Sorting rule:

```python
sorted(table.items(), key=lambda x: (pts, gd, gf), reverse=True)
```

### Tournament state

Service/headless state is local and reconstructed per run:

- `group_winners`
- `group_runners`
- `all_third` / `third_placed`
- `best_thirds`
- `KO_MATCHES` / `round_match_data`
- `champion`

Interactive notebook state is global/widget-backed:

- `LIVE_RESULTS`
- `active_form_modifiers`
- `player_status_injured`
- `team_suspensions`
- `form_off_factor`
- `form_def_factor`
- `group_match_logs`
- `match_events_archive`
- `match_snapshots`
- `MANUAL_SCORES`
- `MANUAL_BRACKET`
- `WILDCARD_OVERRIDES`
- `group_cards_registry`
- `knockout_nodes_registry`

### Knockout bracket

Bracket codes use rank/group notation:

- `1A`: Group A winner.
- `2A`: Group A runner-up.
- `3ABCDF`: one of the third-place slots.

Bracket matrix is defined in `worldcupsimulator.py:1023` and duplicated in `simulation_service.py:177`.

```python
BRACKET = [
    ("1E", "3ABCDF"), ("1I", "3CDFGH"), ("2A", "2B"), ("1F", "2C"),
    ("2K", "2L"), ("1H", "2J"), ("1D", "3BEFIJ"), ("1G", "3AEHIJ"),
    ("1C", "2F"), ("2E", "2I"), ("1A", "3CEFHI"), ("1L", "3EHIJK"),
    ("1J", "2H"), ("2D", "2G"), ("1B", "3EFGLI"), ("1K", "3DEIJL"),
]
```

## 6. Simulation Loop

### Single tournament simulation

The service path runs one tournament in `simulation_service.py:101`.

High-level loop:

1. Load ratings.
2. Update ratings from completed matches.
3. Load `matches.json`.
4. Build `real_results` for completed group matches.
5. For each group:
   - Simulate or use real group matches.
   - Update standings.
   - Record winner, runner-up, third-place team.
6. Sort third-place teams by points, GD, GF.
7. Take top eight third-place teams.
8. Resolve R32, R16, QF, SF, Final.
9. Simulate third-place match.
10. Return structured result.

The headless path does the same in `headless_sim.py` and prints the bracket.

### Monte Carlo simulation

Monte Carlo exists only in the interactive notebook engine, not in `simulation_service.py`.

Entry point:

- `fifa_data/worldcupsimulator.py:1815`

Function:

```python
def run_constrained_monte_carlo_pipeline(b):
```

Simulation count comes from:

```python
sim_count_dropdown = widgets.Dropdown(
    options=[("1,000 Runs (Fast)", 1000), ("5,000 Runs", 5000), ("10,000 Runs (Deep)", 10000)],
    value=1000,
    description="Scale:"
)
```

Aggregation shape:

```python
results = {t: {
    "1st": 0, "2nd": 0, "3rd": 0, "4th": 0,
    "QF": 0, "R16": 0, "R32": 0, "Group": 0,
    "gp1": 0, "gp2": 0, "gp3_q": 0, "gp3_e": 0, "gp4": 0
} for t in TEAM_METRICS.keys()}
```

Each run:

1. `reset_tournament_state()`.
2. Simulates every group.
3. Computes group finish positions.
4. Computes third-place advancement.
5. Simulates knockout rounds.
6. Tracks eliminator/executioner by opponent and stage.
7. Increments finish counters.

Final aggregation:

```python
df1["→ Final"] = df1["1st"] + df1["2nd"]
df1["→ SF"] = df1["→ Final"] + df1["3rd"] + df1["4th"]
df1["→ QF"] = df1["→ SF"] + df1["QF"]
df1["→ R16"] = df1["→ QF"] + df1["R16"]
df1["→ R32"] = df1["→ R16"] + df1["R32"]
```

Then counts are divided by `sims` and multiplied by `100` to produce percentages.

## 7. Configuration & Constants

Important configurable values and where they are defined:

| Constant | Value | Location | Purpose |
|---|---:|---|---|
| Elo/PELE blend | `0.5 / 0.5` | `worldcupsimulator.py:138`, `simulation_service.py:72` | Team strength rating |
| Base expected goals | `1.1` | `worldcupsimulator.py:928`, `simulation_service.py:76` | Lambda scale |
| Upset factor clamp | `0.4` to `1.6` | `worldcupsimulator.py:923`, `simulation_service.py:75` | Limits favorite/underdog lambda shift |
| Upset factor slope | `raw_delta / 800` | same | Converts rating delta to lambda multiplier |
| Minimum lambda | `0.05` | `worldcupsimulator.py:931`, `simulation_service.py:78` | Prevents zero-goal Poisson rate |
| Extra-time lambda scale | `0.3` | `worldcupsimulator.py:938`, `simulation_service.py:81` | Knockout extra-time scoring |
| Knockout tiebreaker boost | `0.50 + raw_delta * 0.0005` | `worldcupsimulator.py:944`, `simulation_service.py:87` | Favors stronger team if extra time remains tied |
| Elo K | `20` | `worldcupsimulator.py:129`, `simulation_service.py:40` | Elo update step size |
| PELE K | `20` | `worldcupsimulator.py:130`, `simulation_service.py:41` | PELE update step size |
| Expected score denominator | `400` | `worldcupsimulator.py:140`, `simulation_service.py:50` | Elo expected score formula |
| Goal multiplier | `1.0 / 1.5 / 2.0` | `worldcupsimulator.py:147`, `simulation_service.py:58` | Elo update margin multiplier |
| Host advantage | `+20` | `worldcupsimulator.py:660` | Applied only in interactive engine |
| Red card probability | `0.035` | `worldcupsimulator.py:764` | Per team per match |
| Injury probability | `0.045` | `worldcupsimulator.py:784` | Per team per match |
| Form trigger probability | `0.15` | `worldcupsimulator.py:903` | Random player form swing |
| Max active form modifiers | `8` | `worldcupsimulator.py:903` | Limits form swing accumulation |
| Form modifier distribution | `gauss(5.5, 2)` | `worldcupsimulator.py:910` | Positive/negative form swing |
| Form modifier clamp | `[-10, 10]` | `worldcupsimulator.py:909` | Caps form swing magnitude |
| Form factor clamp | `[0.6, 1.4]` | `worldcupsimulator.py:974` | Limits cumulative form drift |
| Form update weight | `0.04` | `worldcupsimulator.py:974` | Match performance effect on form |
| MC simulation options | `1000 / 5000 / 10000` | `worldcupsimulator.py:1037` | Monte Carlo scale |
| Default MC runs | `1000` | `worldcupsimulator.py:1037` | Default Monte Carlo count |
| Random seed | None set | all files | Runs are nondeterministic |

Other important toggles/maps:

- `MATCHES_TEAM_MAP`: normalizes match names like `USA` to `United States`.
- `MANUAL_SCORES`: overrides group scores in the interactive engine.
- `MANUAL_BRACKET`: overrides knockout scores in the interactive engine.
- `WILDCARD_OVERRIDES`: forces third-place teams to advance or be eliminated.
- `LIVE_RESULTS`: caches group results for the interactive engine.

## 8. V2 Integration Recommendation

The cleanest approach is to keep V1 intact and introduce V2 behind a shared simulation interface.

### Preserve V1

Do not initially rewrite `worldcupsimulator.py` in place. It currently mixes:

- data
- match math
- roster data
- ipywidgets UI
- Monte Carlo aggregation
- manual overrides

That coupling makes direct mutation risky.

Instead, keep existing V1 behavior stable and add V2 as a separate engine.

### Recommended new structure

```text
fifa_data/
  services/
    simulation_service.py        # keep as API facade
  models/
    simulation_models.py         # dataclasses for Team, Match, Standing, BracketNode, TournamentResult
  sim/
    interfaces.py                # TournamentEngine / MatchEngine protocols
    v1/
      data_loader.py             # loads GROUPS/TEAM_METRICS safely
      elo_engine.py              # existing V1 Elo/PELE Poisson engine
    v2/
      player_feature_loader.py   # loads players.json/squads.json into team/player features
      player_strength.py         # converts player stats into team strength
      player_match_engine.py     # V2 match simulation
  calibration/
    evaluate_engine.py           # compares predictions against matches.json
```

If avoiding a larger refactor, a minimal first step is:

```text
fifa_data/
  v1_engine.py
  v2_engine.py
  simulation_interfaces.py
```

Then have `simulation_service.py` select the engine:

```python
engine = V1Engine()
result = engine.run_once()
```

or:

```python
engine = V2PlayerEngine()
result = engine.run_once()
```

### V2 integration steps

1. **Add dataclasses**
   - `Team`
   - `Match`
   - `Standing`
   - `TournamentResult`
   - `KnockoutMatch`
   - `SimulationRunResult`

2. **Extract tournament orchestration**
   - Group loop
   - Third-place ranking
   - Bracket resolution
   - Knockout progression
   - Result aggregation

   This should be shared by V1 and V2.

3. **Keep V1 as an engine implementation**
   - `V1EloMatchEngine.simulate_match()` should call the current Poisson Elo/PELE logic.
   - It should return the same score tuple expected by the orchestrator.

4. **Add V2 player feature loader**
   - Use `players.json` and `squads.json`.
   - Reuse `fantasy_service.py` for player matching and form/points helpers.
   - Map FIFA squad IDs to V1 country/team names using `squads.json` and existing name maps.

5. **Add V2 team strength model**
   - Candidate features:
     - player total points
     - form
     - last round points
     - position
     - price
     - percent selected
     - fixture difficulty
     - availability/status
   - Convert player-level features into team-level attack, midfield, defense, goalkeeper, and bench-depth ratings.

6. **Add V2 match engine**
   - Implement the same interface as V1.
   - Return `(home_goals, away_goals)` or a richer match result.
   - Avoid depending on ipywidgets or notebook globals.

7. **Add calibration**
   - Use `matches.json` completed matches.
   - Compare:
     - exact score distribution
     - win/draw/loss accuracy
     - goal expectation error
     - champion probabilities if enough completed knockout data exists

8. **Expose through `simulation_service.py`**
   - Keep `run_simulation()` as a V1-compatible wrapper.
   - Add a new endpoint/function such as:
     - `run_simulation(model="v1")`
     - `run_simulation(model="v2")`
     - or `run_v2_simulation()`

### Refactoring needed before V2

The most important refactor is separating orchestration from match math.

Current coupling:

- `worldcupsimulator.py` owns both tournament orchestration and match simulation.
- `simulation_service.py` duplicates orchestration.
- `headless_sim.py` duplicates orchestration.
- Monte Carlo is embedded in notebook UI code.

Recommended refactor:

1. Create shared tournament orchestration.
2. Create shared bracket resolver.
3. Create shared standings calculator.
4. Create shared Monte Carlo aggregator.
5. Keep V1 and V2 as swappable match engines.

This allows V2 to be introduced without changing V1 outputs, UI behavior, or existing service contracts.
