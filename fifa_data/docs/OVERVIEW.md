# World Cup 2026 Simulator — Overview

Three simulation models share the same 48-team, 72-group-match + 31-knockout tournament structure (`TournamentOrchestrator`). Each model plugs in via a common `BaseEngine` interface and differs only in **how match scores are generated**.

---

## The Three Models

```
                ┌──────────────────────────────────────────┐
                │          TournamentOrchestrator           │
                │                                           │
                │  Groups → Knockout → Champion (same for   │
                │  all models, only the scoring differs)    │
                └──────────────┬───────────────────────────┘
                               │ uses BaseEngine
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
        ┌────────────┐ ┌────────────┐ ┌────────────┐
        │  V1        │ │  V2        │ │  V3        │
        │  EloEngine │ │ PlrMatch   │ │ Dynamic    │
        │            │ │ Engine     │ │ State      │
        │  Team      │ │            │ │ Engine     │
        │  ratings   │ │ Individual │ │            │
        │  (Elo +    │ │ player     │ │ V2 ratings │
        │  PELE)     │ │ attributes │ │ + 6 dynamic│
        │            │ │ + fantasy  │ │ modifiers  │
        │            │ │ points     │ │ + non-lin  │
        │            │ │            │ │ curve +    │
        │            │ │            │ │ nat str    │
        └────────────┘ └────────────┘ └────────────┘
```

### V1 — Elo/PELE Team Ratings

**What it uses:** Two historical team strength metrics from `worldcupsimulator.py`:
- **ELO** — betting-odds-derived rating
- **PELE** — prediction-market-derived rating

**How scoring works:**
```
avg_rating = (ELO + PELE) / 2
delta = avg_rating(team_a) - avg_rating(team_b)
upset = clamp(0.4, 1.6, 1.0 + delta / 800)
lambda_a = 1.1 * upset
lambda_b = 1.1 * (2.0 - upset)
goals = Poisson(lambda)
```

**Key trait:** Purely team-level. No player names, no positions, no attributes. Fastest engine.

**File:** `engines/v1_elo_engine.py`

---

### V2 — Player Attribute Match Engine

**What it uses:** Individual player ratings from fantasy data + FC26, assigned to 11 positions per squad.

**How scoring works:**
```
For each team:
  - Load 23-player roster, assign formation, pick Starting XI
  - Rate each player by role (GK/DEF/MID/FWD)
  - Average ratings into positional groups

For each match:
  - attack_rating  = avg of FWD ratings
  - midfield_rating = avg of MID ratings
  - defense_rating  = avg of DEF + GK ratings
  - For each team: attack_strength = attack_rating / opposing_defense
  - Lambda_scaling based on attack_strength ratio
  - Goals via Poisson
```

**Key trait:** Player-aware. Who starts matters. Formation affects which players play. FC26 ratings injected for realism.

**File:** `engines/v2_player_engine.py`

---

### V3 — Dynamic Team State Engine (Calibrated V3.1)

**What it uses:** Everything from V2, plus:
- **Star-weighted positional averages** — CB weighted 0.35×, ST 0.40×, FB 0.15×, etc.
- **6 dynamic state modifiers** — chemistry, experience, form, momentum, continuity, leadership
- **National strength modifier** — from V1's ELO/PELE (±3% max)
- **Non-linear strength curve** — `attack_ratio^3`
- **All configurable** in `data/calibration_config.json`

**How scoring works:**
```
defensive_index = 0.70 × star_defense + 0.30 × star_goalkeeper
attack_ratio    = star_attack / defensive_index
curve_value     = attack_ratio^3                # non-linear amplification
midfield_mod    = 1.0 + 0.25 × Δmid/100
v3_mult         = clamp(1.0 + sum(6 mods), 0.90, 1.10)
lambda          = base_goals × curve_value × midfield_mod × v3_mult × (1 + nat_a - nat_d)
goals           = Poisson(lambda)
```

**Key trait:** "How good is this team right now?" — same squad can perform differently match-to-match based on form, momentum, chemistry, etc.

**File:** `engines/v3_dynamic_engine.py`

---

## One-Liner Comparison

| | V1 | V2 | V3 |
|---|---|---|---|
| **Input** | Team names | Player names + ratings | Player names + ratings + state |
| **Awareness** | Team-level only | Player-level | Player-level + team state |
| **X-Factor** | Elo/PELE averages | Who starts the match | Chemistry, form, momentum, leadership |
| **Speed** | Fastest (~3s) | Medium (~15s) | Medium (~15s) |
| **Realism** | Historical odds | Player quality | Player quality + situational factors |
| **Determinism** | Same teams = same outcome | Same XI ≈ same outcome | Same XI can differ (momentum/form) |

---

## Data Pipeline

```
worldcupsimulator.py (V1 data)
  │
  ├─ TEAM_METRICS → Elo/PELE for V1 engine
  │                  → national_strength_modifiers.json for V3
  │
  └─ RAW_ROSTERS → players.json → v2_data_loader
                     │
                     ├─ squads.json (48 teams, 23 players each, formations)
                     │
                     └─ fc26 fetcher / fantasy API
                          │
                          ├─ fc26_ratings.json (962 players with OVR + attributes)
                          │
                           └─ club_links.json (for chemistry service)
                               player_experience.json (caps/WCs/captains)
```

---

## Running

| Command | What it does |
|---|---|
| `.simulate` | V1 default (fast) |
| `.simulate v1` | V1 Elo/PELE |
| `.simulate v2` | V2 player attributes |
| `.simulate v3` | V3 dynamic team state |
| `.simulate v3 debug` | V3 with per-match breakdown |

Programmatic:
```python
from fifa_data.services.simulation_service import run_simulation
result = run_simulation(model="v3", debug=True)
print(result["champion"])
```

---

## Calibration (V3)

V3.1 was calibrated over 9 pairings × 2,000 matches each. Results are realistic:

| Matchup | Favorite Win % | Draw % | Total Goals |
|---|---|---|---|
| Elite vs Good (France–Switzerland) | 58–61% | 20–25% | 2.4–3.0 |
| Good vs Weak (Spain–Mexico) | 67–69% | 20% | 2.5–2.9 |
| Elite vs Weak (Germany–Curaçao) | 69% | 20% | 2.5 |
| Balanced (Portugal–Netherlands) | 40–50% | 23–26% | 2.6 |

See `SIMULATION_CALIBRATION.md` for full table.

---

## Key Files

| File | Purpose |
|---|---|
| `engines/v1_elo_engine.py` | V1 — Elo/PELE team ratings |
| `engines/v2_player_engine.py` | V2 — Player attribute match engine |
| `engines/v3_dynamic_engine.py` | V3 — Dynamic team state engine |
| `services/simulation_service.py` | Entry point: `run_simulation(model)` |
| `services/orchestrator.py` | Tournament structure (groups, knockout, bracket) |
| `services/v2_data_loader.py` | Squad/player loading, FC26 injection |
| `services/chemistry_service.py` | V3 chemistry evaluation |
| `services/experience_service.py` | V3 experience evaluation |
| `services/form_service.py` | V3 form evaluation |
| `services/momentum_service.py` | V3 momentum tracking |
| `services/continuity_service.py` | V3 lineup continuity |
| `services/leadership_service.py` | V3 leadership evaluation |
| `models/team_strength.py` | `weighted_average()`, `POSITION_WEIGHTS`, `RoleRating` |
| `data/calibration_config.json` | All tunable V3.1 parameters |
| `data/national_strength_modifiers.json` | Per-team national strength (±3%) |
| `worldcupsimulator.py` | V1 root data + team metrics |
