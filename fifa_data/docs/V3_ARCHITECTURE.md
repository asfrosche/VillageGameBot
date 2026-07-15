# V3 Architecture: Dynamic Team State Engine

## V3 Overview

V3 adds a **Dynamic Team State** layer on top of V2's player-attribute system.

**V2 asks:** "How good are these players?"
**V3 asks:** "How good is this team right now?"

V3 applies six real-time modifiers as **separate multiplicative factors** on the xG formula (not baked into ratings), plus a **national strength modifier** and an **ELO/PELE modifier** derived from real match results, plus a **non-linear strength curve** for realistic separation.

```
Players → Role Ratings → Star-Weighted Averages → V3 Dynamic State → xG Formula → Poisson
```

Key differences from V2:
- **Star-weighted averages** replace simple positional averages (configurable weights per position)
- **`attack_ratio^curve_factor` non-linear curve** (default exponent 3.0) amplifies rating gaps
- **Modifiers are multiplicative** on the final xG lambda, not baked into ratings
- **National strength modifier** (±3% max) from `data/national_strength_modifiers.json`
- **ELO/PELE modifier** from real match results (dampened ratio)
- **xG delta calibration** from historical match results
- **Penalty resolution** influenced by leadership, experience, national modifiers
- Combined dynamic multiplier clamped to [0.80, 1.20]

---

## System Flow

```
┌─────────────────────────────────┐
│  V2 Player Data                  │
│  Squad + Formation               │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  build_team_strength()           │
│  → base TeamStrength             │
│    (role_ratings, breakdown)     │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│  V3DynamicEngine.get_team_strength()         │
│                                              │
│  1. Star-weighted averages:                  │
│     star_attack  = weighted_avg(ST, WINGER)  │
│     star_mid     = weighted_avg(CM, DM)      │
│     star_defense = weighted_avg(CB, FB)      │
│     star_gk      = GK rating                 │
│                                              │
│  2. Dynamic modifiers (6 components):        │
│     chemistry    ±0–5%                       │
│     experience   –2–+3%                      │
│     form         –5–+5%                      │
│     momentum     ±3%                         │
│     continuity   –1–+3%                      │
│     leadership   +0–2%                       │
│     dyn_mult = clamp(1.0 + sum, 0.80, 1.20) │
│                                              │
│  3. National modifier: ±3% from JSON         │
│                                              │
│  4. ELO modifier:                            │
│     elo_avg = (ELO + PELE) / 2              │
│     elo_mod = 1.0 + 0.003 × (elo_avg - 1500)│
│     elo_mod ×= form_mult (tournament form)   │
│     clamped [0.50, 3.0]                      │
│                                              │
│  5. Combined multiplier:                     │
│     combined = (1+nat) × dyn × elo           │
│                                              │
│  6. Apply to star ratings:                   │
│     attack = star_a × combined               │
│     midfield = star_m × combined             │
│     defense = star_d × combined              │
│     gk = star_g × combined                   │
└──────────┬──────────────────────────────────┘
           │ TeamStrength (adjusted)
           ▼
┌─────────────────────────────────────────────┐
│  xG Formula                                  │
│                                              │
│  defensive_index =                           │
│    0.70 × star_def + 0.30 × star_gk         │
│  attack_ratio = star_att / def_idx           │
│  curve_value = attack_ratio ^ curve_factor   │
│  midfield_mod = 1 + 0.25 × Δmid/100        │
│  lambda_raw = base × curve × mid_mod        │
│  lambda_raw *= v3_mult                       │
│  lambda_raw *= (1 + nat_a - nat_d)          │
│  lambda_raw *= elo_ratio (dampened)          │
│  lambda = max(0.05, lambda_raw + xg_delta)  │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│  Poisson(g1, g2) → Final Score              │
│  Knockout: ET + penalties (leadership/exp)   │
└─────────────────────────────────────────────┘
```

---

## How `.simulate v3` Works

1. `run_simulation(model="v3")` → `V3DynamicEngine(data_dir=HERE, team_metrics=TEAM_METRICS)`
2. Auto-loads V2 squads via `load_v2_squads()`
3. Loads `calibration_config.json` for all parameters
4. Loads `national_strength_modifiers.json` for per-team national modifiers
5. Initializes 6 dynamic services: Chemistry, Experience, Form, Momentum, Continuity, Leadership
6. Computes **xG deltas** from historical match results (calibration)
7. For each match:
   - Build base `TeamStrength` via `build_team_strength()`
   - Compute all 6 dynamic modifiers
   - Apply combined multiplier to star-weighted ratings
   - Feed into calibrated xG formula with non-linear curve
8. Post-match: update momentum/continuity tracking via `notify_match()`
9. Knockout/penalty resolution uses leadership & experience modifiers

---

## Components

### Dynamic State Model (`models/dynamic_state.py`)

```python
@dataclass(frozen=True)
class ComponentScore:
    component: str       # Name of the component
    value: float         # Modifier value
    source: str          # Human-readable explanation
    confidence: float    # 0.0 to 1.0 (default 1.0)

@dataclass(frozen=True)
class DynamicState:
    team: str
    chemistry: ComponentScore
    experience: ComponentScore
    form: ComponentScore
    momentum: ComponentScore
    continuity: ComponentScore
    leadership: ComponentScore

    def combined_multiplier(self) -> float:
        total = sum(6 components values)
        return max(0.80, min(1.20, 1.0 + total))
```

### Chemistry (`services/v3_modifiers.py` → `ChemistryService`)

**Input:** Starting XI + role assignments + `data/club_links.json`

**Logic:**
- Groups players by club team (from FC26 data)
- Awards pair bonuses for club teammates playing complementary roles:
  - CB+CB pair: +1.5%
  - FB+WINGER, CM+DM, ST+WINGER: +0.8% to +1.0%
  - GK+CB: +0.5%
- National team partnerships add +0.5% per known pair
- Total chemistry capped at +5%

**Data source:** `fc26_ratings.json` → club team, extracted to `data/club_links.json`

**Range:** 0% to +5%

### Experience (`services/v3_modifiers.py` → `ExperienceService`)

**Input:** Starting XI + `data/player_experience.json`

**Logic:**
- Averages international caps across XI
- Awards bonus for high average caps (>50: +1-2%, >30: +0.5%)
- Penalty for inexperienced squads (<30 avg caps: -1%)
- Bonus for World Cup veterans (>1 avg WC: +0.5-1%)
- Bonus for multiple captains in XI: +0.5%
- Extra bonuses in knockout/ET/penalties: +0.5% each

**Data source:** Derived from roster tiers and FC26 overall ratings

**Range:** -2% to +3%

### Form (`services/v3_modifiers.py` → `FormService`)

**Input:** Starting XI players' fantasy stats (`stats.form`, `stats.totalPoints`) + xG deltas

**Logic:**
- Averages fantasy form across XI
- High form (>2.0): +2%, >4.0: +4%
- Poor form (<-0.5): -1% to -3%
- High total points (>80 avg): +1%, low (<20): -1%
- **xG delta calibration**: adjusts based on historical over/under-performance

**Data source:** Fantasy API data (from `players.json`) + `matches.json` for xG deltas

**Range:** -5% to +5%

### Momentum (`services/v3_modifiers.py` → `MomentumService`)

**Input:** Tournament match history (tracked by engine during simulation)

**Logic:**
- Win percentage in recent 5 matches
- >80% wins: +2.5%, >60%: +1.5%
- Multiple losses: -1% to -2%
- Goal difference bonus: +0.5% for GD > +8, -1% for GD < -4
- Clean sheet bonus: +0.5% per 2+ clean sheets

**Data source:** Orchestrator calls `notify_match()` after each result

**Range:** ±3%

### Continuity (`services/v3_modifiers.py` → `ContinuityService`)

**Input:** Lineup history (tracked during simulation)

**Logic:**
- Compares current XI to previous XI
- Identical XI: +2.5%
- 1 change: +1.5%
- 2 changes: +0.5%
- 3+ changes: -0.5% to -1%

**Data source:** Engine tracks `record_lineup()` per team per match

**Range:** -1% to +3%

### Leadership (`services/v3_modifiers.py` → `LeadershipService`)

**Input:** Starting XI + `data/player_experience.json`

**Logic:**
- Counts captains (SUPERSTAR tier or OVR >= 85) in XI
- 2+ captains: +1%, 1 captain: +0.5%
- 5+ veterans (80+ caps): +0.5%
- 4+ WC veterans (2+ WCs): +0.5%
- Knockout/ET/penalty composure bonuses

**Data source:** Same as experience data

**Range:** 0% to +2%

---

## xG Formula (V3)

### Star-Weighted Averages

```python
star_attack  = weighted_average(role_ratings, {"ST", "WINGER"}, star_weights)
star_midfield = weighted_average(role_ratings, {"CM", "DM"}, star_weights)
star_defense  = weighted_average(role_ratings, {"CB", "FB"}, star_weights)
star_gk       = role_ratings["GK"]
```

Star weights are configurable in `calibration_config.json` (e.g., ST 0.40, WINGER 0.15).

### Multiplier Chain

```python
# Dynamic state
dyn = _compute_dynamic_state(team, is_knockout)
dyn_mult = max(0.80, min(1.20, dyn.combined_multiplier()))

# National modifier
nat_mod = national_modifiers.get(team, 0.0)

# ELO modifier from real match results
elo_avg = (ELO + PELE) / 2
elo_mod = 1.0 + 0.003 * (elo_avg - 1500)  # clamped [0.50, 3.0]
elo_mod *= form_mult  # tournament form
elo_mod = clamp(elo_mod, 0.50, 3.0)

# Combined
combined_mult = (1.0 + nat_mod) * dyn_mult * elo_mod

# Apply to star ratings
attack_rating  = star_attack × combined_mult
midfield_rating = star_midfield × combined_mult
defense_rating = star_defense × combined_mult
goalkeeper_rating = star_gk × combined_mult
```

### xG Calculation

```python
defensive_index = 0.70 × star_def + 0.30 × star_gk
attack_ratio = star_att / max(defensive_index, 1.0)
curve_value = attack_ratio ** curve_factor  # default 3.0
midfield_mod = 1.0 + 0.25 × (star_m_a - star_m_d) / 100.0

lambda_raw = base_goals × curve_value × midfield_mod
lambda_raw *= v3_mult
lambda_raw *= (1.0 + nat_mod_a - nat_mod_d)

# ELO dampening (applies ratio difference, not absolute)
if elo_mod_a != elo_mod_d and elo_dampening > 0:
    elo_ratio = elo_mod_a / elo_mod_d
    lambda_raw *= (1.0 + (elo_ratio - 1.0) × elo_dampening)  # default 0.60

# xG delta calibration from historical matches
lambda_raw += xg_delta.get(team, 0.0)

lambda = max(0.05, lambda_raw)
```

---

## xG Delta Calibration

V3 computes per-team xG deltas from historical match results:

1. For each completed match in `matches.json`:
   - Compute expected xG using V3 formula (without deltas)
   - Compare to actual goals scored
   - Delta = actual - expected (clamped ±2.0)
2. Average deltas per team → `xg_delta[team]`
3. Applied as additive correction to final lambda

This calibrates the model to real-world over/under-performance.

---

## Knockout Resolution

### Extra Time
```python
g1_et = poisson(lambda1 × 0.30)  # extra_time_lambda_scale
g2_et = poisson(lambda2 × 0.30)
```

### Penalties (if still tied)
```python
leader_prob = tiebreaker_base_probability + (raw_diff × tiebreaker_delta_scale × 10)

# Leadership modifier
leader_prob += (dyn1.leadership.value - dyn2.leadership.value) × 0.5

# Experience modifier
leader_prob += (dyn1.experience.value - dyn2.experience.value) × 0.3

# National modifier
leader_prob += (nat1 - nat2) × 2.0

leader_prob = max(0.05, min(0.95, leader_prob))
```

This makes penalty outcomes influenced by team quality, not just coin-flip.

---

## Configuration Values

All tunable in `data/calibration_config.json`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_goals` | 1.10 | Baseline goals per match |
| `strength_curve.curve_factor` | 3.0 | Non-linearity exponent |
| `strength_curve.max_multiplier` | 3.0 | Max curve value clamp |
| `strength_curve.min_multiplier` | 0.20 | Min curve value clamp |
| `v3_dynamic_multiplier.min` | 0.80 | Min combined dynamic multiplier |
| `v3_dynamic_multiplier.max` | 1.20 | Max combined dynamic multiplier |
| `attack_weight_defense` | 0.70 | Defense weight in defensive index |
| `attack_weight_goalkeeper` | 0.30 | GK weight in defensive index |
| `midfield_control_weight` | 0.25 | Midfield modifier scaling |
| `minimum_lambda` | 0.05 | Floor for Poisson lambda |
| `extra_time_lambda_scale` | 0.30 | ET lambda scaling |
| `tiebreaker_base_probability` | 0.50 | Base penalty win probability |
| `tiebreaker_delta_scale` | 0.0005 | Rating influence on penalties |
| `elo_dampening` | 0.60 | ELO ratio dampening factor |
| `star_player_weights` | Configurable | Per-position weights for star averages |
| National mod range | ±3% | From `data/national_strength_modifiers.json` |

---

## Data Sources

| File | Source | Contents |
|------|--------|----------|
| `data/club_links.json` | FC26 ratings | Player → Club mapping |
| `data/player_experience.json` | Derived from roster tiers + FC26 OVR | caps, WC appearances, captain status |
| `data/national_strength_modifiers.json` | V1 ELO/PELE averages | Per-team modifier (–0.023 to +0.029) |
| `data/calibration_config.json` | Tuned via calibration | All formula parameters |
| `data/matches.json` | Real match results | Used for xG delta calibration |

---

## Files Reference

| File | Purpose |
|------|---------|
| `engines/v3_dynamic_engine.py` | V3 engine (460 lines) |
| `engines/base_engine.py` | Abstract `MatchEngine` base class |
| `models/dynamic_state.py` | `DynamicState`, `ComponentScore` dataclasses (36 lines) |
| `models/team_strength.py` | `TeamStrength`, role formulas, `weighted_average()` |
| `services/v3_modifiers.py` | All 6 dynamic services (ChemistryService, ExperienceService, etc.) |
| `services/v2_data_loader.py` | `load_v2_squads()` |
| `services/simulation_service.py` | `run_simulation(model="v3")` entry point |
| `__init__.py` | Exports `V3DynamicEngine` |

---

## Integration Points

### Modified Files

- `engines/base_engine.py` — Added `notify_match()` no-op method
- `services/simulation_service.py` — Handle `model="v3"`, pass `team_metrics`
- `services/orchestrator.py` — Call `notify_match()` after each match result

### How V3 Composes

```
V3DynamicEngine
├── squads (from load_v2_squads)
├── team_metrics (ELO/PELE dict)
├── national_modifiers (from JSON)
├── calibration_config (from JSON)
├── chemistry_service
├── experience_service
├── form_service
├── momentum_service
├── continuity_service
└── leadership_service
```

---

## Debug Output Example

```
Brazil vs Germany

Starting XI:
Team 1: Brazil  Formation: 4-3-3
  GK: Alisson
  Defense: Danilo, Marquinhos, Silva, Sandro
  Midfield: Casemiro, Bruno, Paqueta
  Attack: Raphinha, Vinicius, Rodrygo

Base Ratings (simple average):
  Brazil: A=82.5 M=78.3 D=75.1 GK=80.0
  Germany: A=79.0 M=76.5 D=74.2 GK=78.5

Star-Weighted Ratings (star player influence):
  Brazil: A=83.2  NatMod=+0.029  V3Mult=1.0700x
  Germany: A=78.8  NatMod=+0.015  V3Mult=0.9800x

V3 Dynamic State Modifiers (Brazil):
  chemistry:    +1.50%  [2 from Liverpool; 2 from Man City; Club pairings]
  experience:   +1.00%  [Avg 62 caps +1%; Avg 1.5 WCs +0.5%]
  form:         -0.50%  [Avg form 1.2: +0.5%; Low pts: -1%]
  momentum:     +1.50%  [2/3 wins]
  continuity:   +2.50%  [Identical XI]
  leadership:   +1.00%  [2 captains; 4 veterans]
  Combined: 1.0700x

Adjusted Ratings (star-weighted * nat_mod * v3_mult):
  Brazil: A=89.0 M=84.4 D=80.8 GK=86.0
  Germany: A=78.2 M=76.0 D=73.7 GK=77.9

Expected Goals (ratio + non-linear curve):
  Brazil: 1.50
  Germany: 1.10

Score: 2-1
```

---

## Testing V3

```python
from fifa_data import run_simulation

# Run V3 with debug output
result = run_simulation(model="v3", debug=True)
print(result["champion"])

# Direct engine usage
from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
engine = V3DynamicEngine(data_dir="fifa_data", team_metrics=TEAM_METRICS)
score, debug = engine.simulate_match_debug("Brazil", "Germany", can_draw=False)
print(debug)
```

---

## Future Extensions

V3 is designed to be modular so future systems can plug in:

- **Tactical engine** (V4): `services/tactical_analysis.py` for formation matchups, pressing style
- **Match state** (V5): Phase-by-phase simulation with fatigue, cards, substitutions
- **ML prediction**: Replace any `*Service` with a model-based predictor implementing the same `evaluate()` interface
- **Injury/fatigue**: Add a `fitness_service.py` tracking minutes played and recovery
- **Home advantage**: Add a `crowd_service.py` for neutral/away/home venue effects
