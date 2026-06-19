# V3 Architecture: Dynamic Team State Engine (V3.1 Calibrated)

## V3 Overview

V3 adds a **Dynamic Team State** layer on top of V2's player-attribute system.

**V2 asks:** "How good are these players?"
**V3 asks:** "How good is this team right now?"

V3 applies six real-time modifiers as **separate multiplicative factors** on the xG formula (not baked into ratings), plus a **national strength modifier** from V1 ELO/PELE and a **non-linear strength curve** for realistic separation.

```
Players → Role Ratings → Star-Weighted Averages → V3 Dynamic State → xG Formula → Poisson
```

Key differences from V2:
- **Star-weighted averages** replace simple positional averages (CB 0.35×, ST 0.40×, etc.)
- **`attack_ratio^3` non-linear curve** amplifies rating gaps (elite attacks crush weak defenses)
- **Modifiers are multiplicative** on the final xG lambda, not baked into ratings
- **National strength modifier** (±3% max) derived from V1 ELO/PELE
- Combined V3 + national modifier clamped to ±10% total

---

## System Flow

```
                      ┌─────────────────────┐
                      │  V2PlayerMatchEngine │
                      │  (squad loading +    │
                      │   role ratings only) │
                      └──────────┬──────────┘
                                 │ base TeamStrength.breakdown
                                 │ (star_attack, star_defense, etc.)
                                 ▼
                      ┌──────────────────────────┐
                      │  V3DynamicEngine          │
                      │                           │
                      │  Star-weighted averages:  │
                      │   CB 0.35, FB 0.15,       │
                      │   GK 0.30, ST 0.40, ...   │
                      │                           │
                      │  1. Chemistry     ±0–5%   │
                      │  2. Experience    –2–+3%  │
                      │  3. Form          –5–+5%  │
                      │  4. Momentum      ±3%     │
                      │  5. Continuity    –1–+3%  │
                      │  6. Leadership    +0–2%   │
                      │                           │
                      │  v3_mult = clamp(         │
                      │    1.0 + sum(6 mods),     │
                      │    0.90, 1.10)            │
                      │  nat_mod = per-team ±3%   │
                      └──────────┬──────────┘
                                 │ nat_mod, v3_mult applied
                                 │ to xG formula separately
                                 ▼
                      ┌──────────────────────────┐
                      │  xG Formula (V3.1)        │
                      │                           │
                      │  defensive_index =        │
                      │    0.70×star_def +        │
                      │    0.30×star_gk           │
                      │  attack_ratio =           │
                      │    star_att / def_idx     │
                      │  curve_value =            │
                      │    attack_ratio^3         │
                      │  midfield_mod =           │
                      │    1 + 0.25×Δmid/100      │
                      │  lambda =                 │
                      │    base_goals ×           │
                      │    curve_value ×          │
                      │    midfield_mod ×         │
                      │    v3_mult ×              │
                      │    (1 + nat_a - nat_d)    │
                      └──────────┬──────────┘
                                 ▼
                      ┌─────────────────────┐
                      │  Poisson(g1, g2)     │
                      │  → Final Score      │
                      └─────────────────────┘
```

---

## How `.simulate v3` Works

1. `run_simulation(model="v3")` → `V3DynamicEngine(data_dir=HERE)`
2. Auto-loads V2 squads (same `load_v2_squads` pipeline)
3. For each match:
   - Build base `TeamStrength` via V2's `build_team_strength()` → gets star-weighted positional averages in `breakdown`
   - Compute all 6 dynamic modifiers (chemistry, experience, form, momentum, continuity, leadership)
   - Load national strength modifier from `data/national_strength_modifiers.json`
   - Compute v3_mult = clamp(1.0 + sum(6 mods), 0.90, 1.10)
   - Feed star-weighted ratings + v3_mult + nat_mod into calibrated xG formula (non-linear curve)
   - **Modifiers are NOT baked into ratings** — they're separate multiplicative factors on lambda
4. Post-match: update momentum/continuity tracking
5. Knockout/penalty resolution uses leadership & experience modifiers

---

## Components

### Dynamic State Model (`models/dynamic_state.py`)

```python
@dataclass(frozen=True)
class ComponentScore:
    component: str       # Name of the component
    value: float         # Modifier value (-0.05 to +0.05)
    source: str          # Human-readable explanation
    confidence: float    # 0.0 to 1.0

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
        total = sum(6 components)
        return max(0.90, min(1.10, 1.0 + total))
```

### Chemistry (`services/chemistry_service.py`)

**Input:** Starting XI + role assignments + `data/club_links.json`

**Logic:**
- Groups players by club team (from FC26 data)
- Awards pair bonuses for club teammates playing complementary roles:
  - CB+CB pair: +1.5%
  - FB+WINGER, CM+DM, ST+WINGER: +0.8% to +1.0%
  - GK+CB: +0.5%
- Checks `data/player_relationships.json` for known national team partnerships (+0.5% per partnership)
- Total chemistry capped at +5%

**Data source:** `fc26_ratings.json` → club team, extracted to `data/club_links.json`

**Range:** 0% to +5%

### Experience (`services/experience_service.py`)

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

### Form (`services/form_service.py`)

**Input:** Starting XI players' fantasy stats (`stats.form`, `stats.totalPoints`)

**Logic:**
- Averages fantasy form across XI
- High form (>2.0): +2%, >4.0: +4%
- Poor form (<-0.5): -1% to -3%
- High total points (>80 avg): +1%, low (<20): -1%

**Data source:** Fantasy API data (from `players.json`)

**Range:** -5% to +5%

### Momentum (`services/momentum_service.py`)

**Input:** Tournament match history (tracked by engine during simulation)

**Logic:**
- Win percentage in recent 5 matches
- >80% wins: +2.5%, >60%: +1.5%
- Multiple losses: -1% to -2%
- Goal difference bonus: +0.5% for GD > +8, -1% for GD < -4
- Clean sheet bonus: +0.5% per 2+ clean sheets

**Data source:** Orchestrator calls `notify_match()` after each result

**Range:** ±3%

### Continuity (`services/continuity_service.py`)

**Input:** Lineup history (tracked during simulation)

**Logic:**
- Compares current XI to previous XI
- Identical XI: +2.5%
- 1 change: +1.5%
- 2 changes: +0.5%
- 3+ changes: -0.5% to -1%

**Data source:** Engine tracks `record_lineup()` per team per match

**Range:** -1% to +3%

### Leadership (`services/leadership_service.py`)

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

## Data Sources

| File | Source | Confidence | Contents |
|------|--------|------------|----------|
| `data/club_links.json` | FC26 ratings | High (known clubs) | Player → Club mapping for 929 players |
| `data/player_experience.json` | Derived from roster tiers + FC26 OVR | Medium | caps, WC appearances, captain status for 1,245 players |
| `data/player_relationships.json` | Manual | User-configurable | Known national team partnerships |
| `data/national_strength_modifiers.json` | V1 ELO/PELE averages | Medium | Per-team modifier per match (–0.023 to +0.029) |
| `data/calibration_config.json` | Tuned via 9×2,000-match calibration | High | base_goals, curve_factor, star_weights, position weights, V3 multiplier range |

### Derivation Methodology

**player_experience.json:**
- International caps estimated from roster tier: SUPERSTAR=120, STAR=70, STARTER=35, WISSEL=15, BASIS=10, RESERVE=2
- World Cup appearances from FC26 overall: 85+ = 3, 80-84 = 2, 75-79 = 1, <75 = 0
- Captain status: SUPERSTAR tier or OVR >= 85

**club_links.json:** Direct extraction from FC26 ratings `team` field.

### National Strength Modifiers

**`data/national_strength_modifiers.json`** stores per-team modifiers derived from V1 ELO/PELE averages. Range: –0.023 to +0.029 (±3% max). Applied as `(1.0 + nat_mod_a - nat_mod_d)` in the xG formula — models real-world football hierarchy without distorting player ratings.

---

## Configuration Values

All tunable in `data/calibration_config.json`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_goals` | 1.10 | Baseline goals per match (scaling factor) |
| `curve_factor` | 3.0 | Non-linearity exponent: `attack_ratio^3` |
| Total V3 cap | ±10% | Combined multiplier clamped to [0.90, 1.10] |
| Chemistry max | +5% | Hard cap per team |
| Experience range | -2% to +3% | Per team |
| Form range | -5% to +5% | Per team |
| Momentum range | ±3% | Per team |
| Continuity range | -1% to +3% | Per team |
| Leadership max | +2% | Hard cap per team |
| National mod range | ±3% | Per team (from `data/national_strength_modifiers.json`) |
| Defensive weighting | 0.70/0.30 | Def/Goalie split in defensive_index |
| Star weights | CB 0.35, ST 0.40, etc. | Per-position weights for star-weighted averages |

---

## Integration Points

### Modified Files

- `engines/base_engine.py` — Added `notify_match()` no-op method
- `engines/__init__.py` — Export `V3DynamicEngine`
- `models/__init__.py` — Export `DynamicState`, `ComponentScore`
- `services/simulation_service.py` — Handle `model="v3"`
- `orchestrator.py` — Call `notify_match()` after each match result
- `__init__.py` — Export `V3DynamicEngine`

### New Files

- `models/dynamic_state.py` — Dynamic state dataclasses
- `services/chemistry_service.py` — Chemistry evaluation
- `services/experience_service.py` — Experience evaluation
- `services/form_service.py` — Form evaluation
- `services/momentum_service.py` — Momentum tracking
- `services/continuity_service.py` — Lineup continuity
- `services/leadership_service.py` — Leadership evaluation
- `engines/v3_dynamic_engine.py` — V3 engine
- `data/club_links.json` — Player club mapping
- `data/player_experience.json` — Player experience data
- `data/player_relationships.json` — National team partnerships (configurable)
- `V3_ARCHITECTURE.md` — This file

---

## Debug Output Example

```
Team A vs Team B

Starting XI:
Team 1: France  Formation: 4-3-3
  GK: Player1
  Defense: Player2, Player3, Player4, Player5
  Midfield: Player6, Player7, Player8
  Attack: Player9, Player10, Player11

Star-Weighted Base Ratings (breakdown):
  France: star_attack=82.5 star_midfield=78.3 star_defense=75.1 star_goalkeeper=80.0
  England: star_attack=79.0 star_midfield=76.5 star_defense=74.2 star_goalkeeper=78.5

V3 Dynamic State Modifiers (France):
  chemistry:    +1.50%  [2 from Liverpool; 2 from Man City; Club pairings]
  experience:   +1.00%  [Avg 62 caps +1%; Avg 1.5 WCs +0.5%]
  form:         -0.50%  [Avg form 1.2: +0.5%; Low pts: -1%]
  momentum:     +1.50%  [2/3 wins]
  continuity:   +2.50%  [Identical XI]
  leadership:   +1.00%  [2 captains; 4 veterans]
  v3_mult:      1.0700  (clamped to [0.90, 1.10])

National Strength Modifiers:
  France: +0.0290   England: +0.0150
  Relative factor: (1.0 + 0.029 - 0.015) = 1.014

xG Calculation (V3.1 formula):
  defensive_index  = 0.70×75.1 + 0.30×80.0 = 76.6
  attack_ratio     = 82.5 / 76.6 = 1.077
  curve_value      = 1.077^3 = 1.248
  midfield_mod     = 1.0 + 0.25×(78.3-76.5)/100 = 1.0045
  lambda_France    = 1.10 × 1.248 × 1.0045 × 1.07 × 1.014 = 1.50
  lambda_England   = ...

Poisson → France 1.50 goals, England 1.10 goals
Score: 2-1
```

---

## Calibration

See `SIMULATION_CALIBRATION.md` for the full 9-pair × 2,000-match calibration table. Key results:

| Matchup | Favorite Win % | Draw % | Total Goals |
|---------|:-------------:|:------:|:----------:|
| Elite vs Good | 58–61% | 20–25% | 2.4–3.0 |
| Good vs Weak | 67–69% | 20% | 2.5–2.9 |
| Elite vs Weak | 69% | 20% | 2.5 |
| Balanced | 40–50% | 23–26% | 2.6 |

Realistic draw rates (~24%) and goal totals match real-world World Cup averages.

## Testing V3

```python
from fifa_data import run_simulation

# Run V3 with debug output
result = run_simulation(model="v3", debug=True)
print(result["champion"])

# View debug strings
for debug in result.get("debug", []):
    print(debug)
    print("---")
```

---

## V3.1 Changes from V3.0

| Aspect | V3.0 | V3.1 |
|--------|------|------|
| xG Formula | V2 ratio on adjusted ratings | `attack_ratio^3` non-linear curve |
| Ratings | Modifiers baked into ratings | Modifiers are separate multiplicative factors on lambda |
| Averages | Simple positional averages | Star-weighted averages (weight per position config in `calibration_config.json`) |
| National strength | Not included | ±3% modifier from V1 ELO/PELE (`data/national_strength_modifiers.json`) |
| Calibration | Not calibrated | 9 pairs × 2,000 matches; realistic win%, draw%, goal totals |
| Config | Hardcoded | All tunable in `data/calibration_config.json` |

---

## Future Extensions

V3 is designed to be modular so future systems can plug in:

- **Tactical engine**: Add a `tactics_service.py` evaluating formation matchups, pressing style, etc.
- **ML prediction**: Replace any `*Service` with a model-based predictor implementing the same `evaluate()` interface.
- **Injury/fatigue**: Add a `fitness_service.py` tracking minutes played and recovery.
- **Home advantage**: Add a `crowd_service.py` for neutral/away/home venue effects.
- **Manager influence**: Add a `tactics_service.py` for manager reputation and style.
