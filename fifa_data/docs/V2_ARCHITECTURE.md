# V2 Architecture: Player Attribute Engine

## Overview

V2 replaces V1's team-level ELO with actual **FC26 player attributes** weighted by position. Each player is assigned a role (GK, CB, FB, DM, CM, ST, WINGER) via the team's formation, then role ratings are computed using weighted attribute formulas. Team strength is derived from these role ratings.

**V1 asks:** "Which team is stronger on paper?" (ELO)
**V2 asks:** "How good are these players?" (attributes)

```
FC26 Player Attributes → Role Assignment → Weighted Formulas → Team Strength → xG → Poisson
```

---

## System Flow

```
┌──────────────────────────────┐
│  Squad Data (FC26)            │
│  + Formation string           │
│  (e.g., "4-3-3")             │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  assign_roles(xi, formation)  │
│  Maps each player to a role   │
│  based on position + slot     │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  build_team_strength()        │
│  For each role:               │
│    role_rating = Σ(weight_i   │
│      × attribute_i)           │
│  Then: Attack = avg(ST, WING) │
│        Mid = avg(CM, DM)      │
│        Def = avg(CB, FB)      │
│        GK = GK rating         │
└──────────┬───────────────────┘
           │ TeamStrength
           ▼
┌──────────────────────────────┐
│  expected_goals(s1, s2)       │
│  Per-team xG via non-linear   │
│  attack ratio + midfield mod  │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  Poisson(λ1), Poisson(λ2)    │
│  → Final Score               │
└──────────────────────────────┘
```

---

## Player Role Rating Formulas

Each position has attribute weights summing to 1.0, defined in `models/team_strength.py`:

| Role | Attributes (weight) |
|------|---------------------|
| **ST** | finishing (35%), positioning (20%), shot_power (15%), pace (15%), composure (15%) |
| **WINGER** | pace (30%), dribbling (25%), crossing (20%), finishing (15%), vision (10%) |
| **CM** | passing (30%), vision (20%), dribbling (20%), stamina (15%), defending (15%) |
| **DM** | defending (30%), interceptions (25%), passing (20%), physical (15%), stamina (10%) |
| **FB** | pace (25%), defending (20%), crossing (20%), stamina (15%), passing (10%), dribbling (10%) |
| **CB** | defensive_awareness (30%), tackling (25%), strength (15%), pace (15%), reactions (15%) |
| **GK** | reflexes (30%), diving (25%), positioning (20%), handling (15%), kicking (10%) |

### Role Assignment

`assign_roles(starting_xi, formation)` maps players to roles:

1. Parse formation string (e.g., "4-3-3" → 4 defenders, 3 midfielders, 3 attackers)
2. Map formation slots to roles: defenders → CB/FB, midfielders → CM/DM, attackers → ST/WINGER
3. Assign best player per role based on position compatibility

### Team Strength Calculation

```python
attack_rating  = mean(role_ratings for ST, WINGER roles)
midfield_rating = mean(role_ratings for CM, DM roles)
defense_rating  = mean(role_ratings for CB, FB roles)
goalkeeper_rating = mean(role_ratings for GK roles)
```

---

## xG Formula (V2)

### Defensive Index
```python
defensive_index = 0.70 * defense_rating + 0.30 * goalkeeper_rating
```

### Attack Ratio
```python
attack_ratio = attack_rating / max(defensive_index, 1.0)
```

### Non-Linear Curve
```python
curve_value = attack_ratio ** 2.5
curve_value = max(0.30, min(3.0, curve_value))
```

The **2.5 exponent** amplifies rating gaps — elite attacks significantly outperform weak defenses.

### Midfield Modifier
```python
midfield_modifier = 1.0 + 0.25 * (midfield_a - midfield_d) / 100.0
```

Midfield dominance adds up to ±25% to xG.

### Final Lambda
```python
lambda = base_goals × curve_value × midfield_modifier × form_mult
```

Where `form_mult = 1.0 + tournament_form / 1500.0`.

---

## Knockout Resolution

Same as V1: extra time with 0.30x lambda scaling, then penalty tiebreaker.

```python
if not can_draw and g1 == g2:
    g1_et = poisson(lambda1 * 0.30)
    g2_et = poisson(lambda2 * 0.30)
    if g1_et != g2_et:
        g1 += g1_et; g2 += g2_et
    else:
        # Penalty tiebreaker based on attack rating delta
        prob = 0.50 + (attack_delta * 0.0005)
        if random.random() < prob: g1 += 1
        else: g2 += 1
```

---

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_goals` | 1.10 | Baseline expected goals |
| `attack_weight_defense` | 0.70 | Defense weight in defensive index |
| `attack_weight_goalkeeper` | 0.30 | GK weight in defensive index |
| `midfield_control_weight` | 0.25 | Midfield modifier scaling factor |
| `minimum_lambda` | 0.05 | Floor for Poisson lambda |
| `extra_time_lambda_scale` | 0.30 | ET lambda scaling |
| `tiebreaker_base_probability` | 0.50 | Base penalty win probability |
| `tiebreaker_delta_scale` | 0.0005 | Rating influence on penalties |

All configurable via constructor kwargs.

---

## Data Sources

| File | Source | Purpose |
|------|--------|---------|
| `data/squads.json` | FC26 ratings | Starting XI + formation per team |
| `data/fc26_ratings.json` | FC26 data | Full player attribute database |
| `tournament_form` | Runtime | Recent form bonus per team |

---

## Debug Output

V2 provides detailed debug output via `simulate_match_debug()`:

```
Brazil vs Germany

Starting XI:
Team 1: Brazil  Formation: 4-3-3
  GK: Alisson
  Defense: Danilo, Marquinhos, Silva, Sandro
  Midfield: Casemiro, Bruno, Paqueta
  Attack: Raphinha, Vinicius, Rodrygo

Ratings:
Attack: 82.5
Midfield: 78.3
Defense: 75.1
Goalkeeper: 80.0

Expected Goals:
Brazil: 1.50
Germany: 1.10

Score: 2-1
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `engines/v2_player_engine.py` | V2 engine class (179 lines) |
| `engines/base_engine.py` | Abstract `MatchEngine` base class |
| `models/team_strength.py` | `TeamStrength`, role formulas, `assign_roles()`, `build_team_strength()` |
| `models/squad.py` | `Squad` dataclass |
| `models/player.py` | `Player` dataclass with attributes |
| `services/v2_data_loader.py` | `load_v2_squads()` — loads squads from JSON |
| `services/simulation_service.py` | `run_simulation(model="v2")` entry point |

---

## Limitations

- **No dynamic state**: Each match is independent (no momentum, form tracking)
- **No tactical awareness**: All matchups treated equally
- **No chemistry**: Players are evaluated individually
- **Simple averages**: Position ratings use simple means, not star-weighted

V2 is best when you want player-level accuracy without the complexity of dynamic modifiers.

---

## Usage

```python
from fifa_data import run_simulation

# Run full tournament with V2
result = run_simulation(model="v2")
print(result["champion"])

# Direct engine usage
from fifa_data.engines.v2_player_engine import V2PlayerMatchEngine
engine = V2PlayerMatchEngine(data_dir="fifa_data")
score, debug = engine.simulate_match_debug("Brazil", "Germany", can_draw=False)
print(debug)
```
