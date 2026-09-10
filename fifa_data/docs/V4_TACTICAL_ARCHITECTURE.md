# V4 Architecture: Tactical Intelligence Engine

## Architecture Overview: V1 → V2 → V3 → V4

The FIFA simulation engine is a layered architecture where each version builds upon the previous one.

```
FC26 Players
    ↓
V1: ELO Rating (static team power)
    ↓
V2: Player Strength (position-weighted attributes)
    ↓
V3: Dynamic State (chemistry, form, momentum, ELO modifier)
    ↓
V4: Tactical Intelligence (matchup-specific adjustments)
    ↓
Poisson Simulation (goals from expected goals)
```

Each layer adds sophistication while preserving lower-layer outputs as inputs.

---

## V4 Overview

V4 wraps V3, adding **matchup-specific tactical adjustments**. Where V3 answers "How good is this team right now?", V4 answers "How do these two teams match up against each other?"

```
V3 Dynamic Engine → Base xG → Tactical Matchup Service → Adjusted xG → Poisson
```

---

## System Flow

```
┌──────────────────────────────┐
│  V4TacticalEngine             │
│  holds self._v3 (V3Dynamic)  │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  1. Get V3 Strength           │
│     strength1 = _v3.get_      │
│       team_strength(t1)       │
│     strength2 = _v3.get_      │
│       team_strength(t2)       │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  2. Get V3 Base xG            │
│     base_lambda1, base_lambda2│
│     = _v3.expected_goals(s1,s2)│
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  3. compute_tactical_matchup()        │
│     ├── Load tactical profiles        │
│     ├── Choose game plans             │
│     ├── Apply 13 matchup categories   │
│     ├── Clamp to ±15% of base xG     │
│     └── Return TacticalReport         │
│        (final_xg_a, final_xg_b)      │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  4. Poisson(final_xg_a)      │
│     Poisson(final_xg_b)      │
│     → Score                  │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  5. Update V3 tracking:       │
│     momentum, continuity      │
│     (via _v3.notify_match)    │
└──────────────────────────────┘
```

---

## 13 Matchup Categories

All evaluated in `services/tactical_analysis.py`:

### Original Matchups

**1. High Line vs Pace** (`_high_line_vs_pace`)
- Team with high defensive line (≥65) exploited by fast attackers
- Uses opponent's attacker pace + dribbling averages
- Boost = 0.12 × max(0, (pace + drib)/2 - 50) / 50

**2. Pressing vs Build-up** (`_pressing_vs_buildup`)
- High pressing (≥65) vs weak build-up (<60)
- Quality factor from opponent composure + passing
- Boost = 0.10 × press_gap × quality_factor

**3. Possession vs Low Block** (`_possession_vs_low_block`)
- High possession (≥70) vs compact defense (≥70)
- Creativity factor from vision, dribbling, crossing, long_shots
- Boost = 0.08 × creativity_factor

**4. Set Pieces** (`_set_pieces`)
- Attack vs defense rating mismatch
- Quality factor from heading, strength, crossing
- Boost = 0.10 × gap × quality_factor

**5. Aerial Battles** (`_aerial_battles`)
- Aerial strength gap > 10 points
- Quality from jumping, heading, strength
- Boost = 0.04 × (gap/50) × quality_factor

**6. Formation Matchup** (`_formation_matchup`)
- Width advantage (>10% difference)
- Central control advantage (>10% difference)
- Space behind fullbacks exploitation
- Delegated to `formation_service.py`

**7. Player-Tactic Compatibility** (`_player_tactic_compatibility`)
- High pressing teams exploit low stamina/composure opponents
- Penalty applied against vulnerable teams

**8. Possession Quality** (`_possession_quality`)
- Separates possession **volume** from **quality** using 4 metrics:
  ```
  quality = pp × 0.25 + f3 × 0.25 + bcc × 0.30 + sq × 0.20
  ```
  Where: pp = progressive_passes, f3 = final_third_entries, bcc = big_chance_creation, sq = shot_quality
- Boost applied when gap > 8% and attackers have vision/passing quality

**9. Defensive Style Interaction** (`_defensive_style_interaction`)
- 5 defensive styles in a 7×7 matchup matrix:
  - low_block, mid_block, high_press, man_marking, zonal
  - vs high_press, direct, possession, high_line, mid_block, etc.
- Style derived from opponent's predominant attribute

**10. Tactical Flexibility** (`_tactical_flexibility_effects`)
- Flexibility gap > 15% → ±0.02 boost for flexible team
- Rigid team (<40) vs flexible (>60) → -0.015 penalty

**11. Match Context Effects** (`_match_context_effects`)

| Context | Adjustment |
|---------|------------|
| knockout | Both teams -0.01 xG (cautious) |
| must_win | Attacking/high_press teams +0.02 xG |
| need_draw | Low block teams -0.015 xG |
| gd_chase | Attacking teams +0.025/-0.015 (risk/reward) |

**12. Game Plan Effects** (`_game_plan_effects`)

| Plan | xG Effect | Description |
|------|-----------|-------------|
| attacking | +0.03/-0.02 | More risk, more chances; defensive vulnerability |
| counter | +0.02/-0.02 | Transition threat; reduced possession control |
| low_block | -0.03/-0.02 | Fewer chances conceded; reduced attacking threat |
| high_press | +0.03/-0.02 | Ball recoveries; defensive structure risk |
| balanced | (no effect) | Default game plan |

**13. Defensive Stalemate** (`_defensive_stalemate`)
- Both teams with high defensive rating (≥55) → reduced xG for both
- Reduction scales with average defense level above threshold
- Additional composure stalemate: both teams composure ≥60 → -0.05 xG

---

## Game Plan Selection (`choose_game_plan()`)

```
if context == "knockout":
    strength > 1.10 → "balanced"
    strength < 0.80 → "low_block"
    else → "balanced"

elif context == "must_win":
    strength > 0.95 → "attacking"
    strength < 0.75 → "high_press"
    else → "attacking"

elif context == "need_draw":
    strength < 0.90 → "low_block"
    else → "balanced"

elif context == "gd_chase":
    pressing > 60 → "high_press"
    else → "attacking"

else:  # group stage
    strength > 1.15 → "attacking"
    strength < 0.85:
        opponent counter_attack > 70 → "low_block"
        else → "counter"
    else → "balanced"
```

---

## Match Contexts

| Context | When Used | Effect |
|---------|-----------|--------|
| `group` | Group stage matches | Default tactical behavior |
| `knockout` | Knockout rounds | Both teams cautious (-0.01 xG), balanced game plans |
| `must_win` | Team needs win to advance | Urgent attacking (+0.02 xG) |
| `need_draw` | Team needs draw to advance | Deep defensive focus (-0.015 xG) |
| `gd_chase` | Team needs goal difference | High-risk attacking (+0.025/-0.015) |

---

## Adjustment Clamping

```python
MAX_XG_ADJUSTMENT_PCT = 0.15

max_adj_a = max(base_xg_a × 0.15, 0.05)
max_adj_b = max(base_xg_b × 0.15, 0.05)

total_adj_a = sum(all adjustments for team_a)
clamped_adj_a = max(-max_adj_a, min(max_adj_a, total_adj_a))
```

- Maximum adjustment is **±15% of base xG** (minimum 0.05)
- Ensures tactical differences cannot overturn major quality gaps
- A 2.0 xG favorite remains favorite even with tactical disadvantages

---

## TacticalReport Output

```python
@dataclass
class TacticalReport:
    team_a: str
    team_b: str
    base_xg_a: float        # From V3
    base_xg_b: float        # From V3
    adjustments_a: list     # List of TacticalAdjustment
    adjustments_b: list
    final_xg_a: float       # After tactical adjustments
    final_xg_b: float
    game_plan_a: str        # "attacking"|"balanced"|"counter"|"low_block"|"high_press"
    game_plan_b: str
    advantages_a: list[str] # Human-readable advantage descriptions
    advantages_b: list[str]
    context: str            # "group"|"knockout"|"must_win"|"need_draw"|"gd_chase"
```

---

## Data Sources

| File | Purpose |
|------|---------|
| `data/tactical_profiles.json` | 22+ tactical attributes per team (possession, pressing, defensive_line, etc.) |
| `data/manager_profiles.json` | 4 manager attributes per team (risk_tolerance, tactical_flexibility, etc.) |

---

## Knockout Resolution

Same as V3: extra time with 0.30x lambda scaling, then penalty tiebreaker influenced by leadership, experience, and national modifiers.

---

## Configuration Parameters

| Parameter | Default | Location |
|-----------|---------|----------|
| `MAX_XG_ADJUSTMENT_PCT` | 0.15 | `tactical_analysis.py` |
| High-line pace boost | 0.12 | `_high_line_vs_pace()` |
| Pressing vs buildup | 0.10 | `_pressing_vs_buildup()` |
| Possession creativity | 0.08 | `_possession_vs_low_block()` |
| Possession quality | 0.06 | `_possession_quality()` |
| Set-piece gap factor | 0.10 | `_set_pieces()` |
| Aerial gap factor | 0.04 | `_aerial_battles()` |
| Flexibility edge | 0.02 | `_tactical_flexibility_effects()` |
| Rigidity penalty | 0.015 | `_tactical_flexibility_effects()` |
| Defensive stalemate | -0.35 max | `_defensive_stalemate()` |
| Composure stalemate | -0.05 | `_defensive_stalemate()` |

---

## Files Reference

| Layer | File | Purpose |
|-------|------|---------|
| V4 | `engines/v4_tactical_engine.py` | Tactical engine wrapping V3 (186 lines) |
| V4 | `models/tactical_state.py` | `TacticalReport`, `FormationProfile`, `ManagerProfile`, `TacticalAdjustment`, `MatchContext` |
| V4 | `services/tactical_analysis.py` | 13 matchup categories, game plan selection, vulnerability analysis |
| V4 | `services/formation_service.py` | Formation profiles and matchup evaluation |
| V4 | `services/manager_service.py` | Manager profile loading and modulation |
| V4 | `data/tactical_profiles.json` | 22+ tactical attributes per team |
| V4 | `data/manager_profiles.json` | 4 manager attributes per team |
| V3 | `engines/v3_dynamic_engine.py` | Underlying V3 engine |

---

## Key Design Decisions

1. **Additive adjustments:** V4 modifies xG additively (not multiplicatively) to maintain linear interpretability and prevent compounding with V3.

2. **±15% cap:** Ensures tactical differences cannot overturn major quality gaps.

3. **Player-mediated effects:** Team-level tactical profiles provide direction, but FC26 attributes determine actual effect magnitude.

4. **Composable layers:** V4 wraps V3 without modifying it. V3 can run independently.

5. **Explainable adjustments:** Every tactical modifier has category, value, and description for debugging.

6. **Context-aware game plans:** Game plan selection integrates relative strength, opponent style, and match context.

---

## Usage

```python
from fifa_data import run_simulation

# Run full tournament with V4
result = run_simulation(model="v4")
print(result["champion"])

# Direct engine usage
from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
engine = V4TacticalEngine(data_dir="fifa_data", team_metrics=TEAM_METRICS)
score, debug = engine.simulate_match_debug("Brazil", "Germany", can_draw=False, context="knockout")
print(debug)
```
