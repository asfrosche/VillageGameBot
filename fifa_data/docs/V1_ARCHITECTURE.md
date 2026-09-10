# V1 Architecture: ELO-Based Match Engine

## Overview

V1 is the foundational match simulation engine. It uses pre-computed **ELO and PELE ratings** to determine match outcomes via Poisson distribution. No squad data, no player attributes — just team-level power ratings.

**V1 asks:** "Which team is stronger on paper?"

```
Team ELO/PELE Ratings → Upset Factor → Poisson λ → Goals
```

---

## System Flow

```
┌──────────────────────────────┐
│  TEAM_METRICS dict            │
│  {team: {ELO, PELE}}         │
│  + tournament_form modifier    │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  _rating(team)                │
│  = (ELO + PELE) / 2          │
│    + tournament_form[team]    │
└──────────┬───────────────────┘
           │ raw_delta = r1 - r2
           ▼
┌──────────────────────────────┐
│  upset_factor                 │
│  = clamp(                    │
│    1.0 + delta / 800,        │
│    0.4, 1.6)                 │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  Poisson lambdas              │
│  λ1 = base_goals × upf       │
│  λ2 = base_goals ×           │
│    max(0.20, 1.5 - 0.5×upf)  │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  g1 = Poisson(λ1)            │
│  g2 = Poisson(λ2)            │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  Knockout resolution          │
│  (extra time + penalties)     │
└──────────────────────────────┘
```

---

## Core Algorithm

### 1. Team Rating

```python
rating = (ELO + PELE) / 2.0 + tournament_form
```

- **ELO** and **PELE** are pre-computed from historical match results (1500 baseline)
- **tournament_form** is an additive bonus from the `TournamentFormService` based on recent results

### 2. Upset Factor

Balances the Poisson lambdas based on rating difference:

```python
upset_factor = max(0.4, min(1.6, 1.0 + (r1 - r2) / 800.0))
```

| Rating Delta | Upset Factor | Effect |
|:---:|:---:|:---|
| +800 | 1.60 | Massive favorite gets 1.6x goals |
| +400 | 1.50 | Strong favorite advantage |
| 0 | 1.00 | Even match |
| -400 | 0.50 | Underdog struggles |
| -800 | 0.40 | Massive underdog |

### 3. Poisson Lambdas

```python
lambda1 = base_goals * upset_factor
lambda2 = max(minimum_lambda, base_goals * max(0.20, 1.5 - 0.5 * upset_factor))
```

The underdog lambda has a floor of `base_goals × 0.20` (never truly zero) and uses a complementary formula that ensures the total expected goals stays reasonable.

### 4. Goal Generation

```python
g1 = poisson(max(minimum_lambda, lambda1))
g2 = poisson(max(minimum_lambda, lambda2))
```

`minimum_lambda = 0.05` prevents degenerate zero-lambda cases.

---

## Knockout Resolution

When `can_draw=False` (knockout matches):

### Extra Time
```python
g1_et = poisson(lambda1 * extra_time_lambda_scale)  # 0.30x scaling
g2_et = poisson(lambda2 * extra_time_lambda_scale)
if g1_et != g2_et:
    g1 += g1_et; g2 += g2_et
```

### Penalties (if still tied)
```python
prob = tiebreaker_base_probability + (raw_delta * tiebreaker_delta_scale)
if random.random() < prob:
    g1 += 1  # Favorite wins
else:
    g2 += 1  # Upset
```

- `tiebreaker_base_probability = 0.50`
- `tiebreaker_delta_scale = 0.0005`
- Small delta-scale means upsets happen ~50% of the time even with rating gaps

---

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_goals` | 1.10 | Baseline expected goals per match |
| `upset_factor_min` | 0.40 | Minimum upset factor (max underdog suppression) |
| `upset_factor_max` | 1.60 | Maximum upset factor (max favorite boost) |
| `upset_factor_slope` | 800.0 | Rating delta divisor for upset calculation |
| `minimum_lambda` | 0.05 | Floor for Poisson lambda |
| `extra_time_lambda_scale` | 0.30 | ET lambda = regular × 0.30 |
| `tiebreaker_base_probability` | 0.50 | Base penalty shootout win probability |
| `tiebreaker_delta_scale` | 0.0005 | Rating delta influence on penalty probability |

All parameters are configurable via constructor kwargs.

---

## Data Sources

| Data | Source | Purpose |
|------|--------|---------|
| `TEAM_METRICS` | `worldcupsimulator.py` (loaded via `_load_worldcup_data()`) | ELO + PELE per team |
| `tournament_form` | `TournamentFormService` (computed at runtime) | Recent form bonus per team |

### TEAM_METRICS Structure
```python
TEAM_METRICS = {
    "Brazil":  {"ELO": 2100, "PELE": 1950},
    "Germany": {"ELO": 2050, "PELE": 1900},
    ...
}
```

---

## ELO/PELE Update Pipeline

After real matches are played, `update_elo_from_matches()` (in `_match_config.py`) reads `matches.json` and updates `TEAM_METRICS` in-place. This means:

1. Real match results adjust ELO/PELE ratings
2. Simulated matches use updated ratings
3. The orchestrator calls `update_elo_from_matches()` before each simulation run

---

## Files Reference

| File | Purpose |
|------|---------|
| `engines/v1_elo_engine.py` | V1 engine class (84 lines) |
| `engines/base_engine.py` | Abstract `MatchEngine` base class |
| `services/simulation_service.py` | `run_simulation(model="v1")` entry point |
| `services/_match_config.py` | `update_elo_from_matches()`, `MATCHES_TEAM_MAP` |
| `worldcupsimulator.py` | Static `TEAM_METRICS` and `GROUPS` data |

---

## Limitations

- **No squad data**: Ignores player attributes, formations, roles
- **No in-tournament dynamics**: No momentum, form, chemistry tracking
- **Stateless**: Each match is independent (except tournament_form carry-over)
- **Penalty outcomes**: ~50/50 regardless of team quality (small delta_scale)
- **No tactical awareness**: All matchups treated equally

V1 is best for quick, simple simulations where team-level power is the primary signal.

---

## Usage

```python
from fifa_data import run_simulation

# Run full tournament with V1
result = run_simulation(model="v1")
print(result["champion"])

# Single match
from fifa_data import sim_match
g1, g2 = sim_match("Brazil", "Germany", can_draw=False)
```
