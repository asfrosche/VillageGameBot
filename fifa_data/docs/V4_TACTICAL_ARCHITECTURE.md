# V4 Architecture: Tactical Intelligence Engine (Deep Technical Architecture)

## Architecture Overview: V1 → V2 → V3 → V4

The FIFA simulation engine is a layered architecture where each version builds upon the previous one. All versions share the same core: FC26 player data → Poisson distribution → match scores.

```
FC26 Players
    ↓
V1: ELO Rating (static team power)
    ↓
V2: Player Strength (position-weighted attributes)
    ↓
V3: Dynamic State (chemistry, form, momentum, etc.)
    ↓
V4: Tactical Intelligence (matchup-specific adjustments)
    ↓
Poisson Simulation (goals from expected goals)
```

Each layer adds sophistication while preserving lower-layer outputs as inputs.

---

## V1: ELO-Based Engine (`engines/v1_elo_engine.py`)

The foundation. Uses pre-computed ELO/Pele ratings to determine match outcomes.

### Core Algorithm

1. **Team Rating:** Average of ELO and PELE ratings (1500 baseline)
   ```python
   rating = (ELO + PELE) / 2.0
   ```

2. **Upset Factor:** Balances the Poisson lambdas based on rating delta
   ```python
   upset_factor = max(0.4, min(1.6, 1.0 + (r1 - r2) / 800.0))
   lambda1 = base_goals * upset_factor
   lambda2 = base_goals * (2.0 - upset_factor)
   ```

3. **Poisson Draw:** Goal counts drawn from Poisson distributions
4. **Extra Time/Penalties:** For knockout matches (can_draw=False)

**V1 is stateless** - no tournament context carries forward.

---

## V2: Player Attribute Engine (`engines/v2_player_engine.py`)

Replaces ELO with actual FC26 player attributes weighted by position.

### Player Role Rating Formulas (`models/team_strength.py`)

Each position has attribute weights summing to 1.0:

| Role | Attributes |
|------|------------|
| ST | finishing (35%), positioning (20%), shot_power (15%), pace (15%), composure (15%) |
| WINGER | pace (30%), dribbling (25%), crossing (20%), finishing (15%), vision (10%) |
| CM | passing (30%), vision (20%), dribbling (20%), stamina (15%), defending (15%) |
| DM | defending (30%), interceptions (25%), passing (20%), physical (15%), stamina (10%) |
| FB | pace (25%), defending (20%), crossing (20%), stamina (15%), passing (10%), dribbling (10%) |
| CB | defensive_awareness (30%), tackling (25%), strength (15%), pace (15%), reactions (15%) |
| GK | reflexes (30%), diving (25%), positioning (20%), handling (15%), kicking (10%) |

### Team Strength Calculation

1. **Role Assignment:** Players mapped to roles via `normalized_positions()` and formation slots
2. **Average Ratings:** Simple mean of role ratings
   - Attack = avg(ST, WINGER)
   - Midfield = avg(CM, DM)
   - Defense = avg(CB, FB)
   - Goalkeeper = avg(GK)

3. **Expected Goals:** Non-linear attack ratio with midfield modifier
   ```python
   defensive_index = 0.70 * defender_rating + 0.30 * goalkeeper_rating
   attack_ratio = attacker_rating / max(defensive_index, 1.0)
   curve_value = attack_ratio ** 3.0  # exponent configurable
   midfield_modifier = 1.0 + 0.25 * (attacking_mid - defending_mid) / 100.0
   lambda = 1.1 * curve_value * midfield_modifier
   ```

**V2 is stateless** - no in-tournament dynamics.

---

## V3: Dynamic State Engine (`engines/v3_dynamic_engine.py`)

Adds six dynamic state components that evolve during tournament simulation.

### V3 Dynamic State Components (`models/dynamic_state.py`)

Each component produces a percentage modifier (-2% to +3%) combined into a multiplier (0.90x to 1.10x):

| Component | Service | Range | Source |
|-----------|---------|-------|--------|
| Chemistry | `chemistry_service.py` | -2% to +5% | Club links, partnerships |
| Experience | `experience_service.py` | -2% to +3% | International caps, WC appearances |
| Form | `form_service.py` | -5% to +4% | Fantasy points, form ratings |
| Momentum | `momentum_service.py` | -3% to +2.5% | Recent results, GD, clean sheets |
| Continuity | `continuity_service.py` | -1% to +2.5% | Lineup stability |
| Leadership | `leadership_service.py` | 0% to +2% | Captains, WC veterans |

### Chemistry Calculation (`services/chemistry_service.py`)

- **Club Pairings:** Players from same club in same XI get bonus
  - CB-CB: +1.5%
  - FB-FB: +1.0%
  - CM-DM: +1.0%
  - ST-WINGER: +0.8%
  - GK-CB: +0.5%
  - Other pairs: +0.5%

- **Partnerships:** Known player pairs from historical data (+0.5% per pair)

### Experience Calculation (`services/experience_service.py`)

| Avg Caps | Bonus |
|----------|-------|
| ≥80 | +2% |
| 50-79 | +1% |
| 30-49 | +0.5% |
| <30 | -1% |

+0.5% for WC veterans in knockout/extra time/penalties stages.

### Form Calculation (`services/form_service.py`)

| Avg Form | Bonus |
|----------|-------|
| ≥4.0 | +4% |
| 2.0-3.9 | +2% |
| 0.5-1.9 | +0.5% |
| -1.0 to -0.5 | -1% |
| ≤-1.0 | -3% |

### Momentum Calculation (`services/momentum_service.py`)

Rolling 5-match window:
- Win rate ≥80%: +2.5%
- Win rate 60-79%: +1.5%
- Win rate 40-59%: +0.5%
- Losses ≥2: -2%
- GD ≥8: +0.5%
- Clean sheets ≥2: +0.5%

### Continuity Calculation (`services/continuity_service.py`)

- 0 changes from previous match: +2.5%
- 1 change: +1.5%
- 2 changes: +0.5%
- 3+ changes: -0.5% to -1%

### Leadership Calculation (`services/leadership_service.py`)

- 2+ captains: +1%
- 3+ WC veterans: +0.5%
- +0.3% for knockout, +0.2% for extra time, +0.5% for penalties

### V3 Team Strength Formula

```python
star_attack = weighted_average(role_ratings, {"ST", "WINGER"}, star_weights)
star_midfield = weighted_average(role_ratings, {"CM", "DM"}, star_weights)
star_defense = weighted_average(role_ratings, {"CB", "FB"}, star_weights)
star_goalkeeper = weighted_average(role_ratings, {"GK"}, star_weights)

dyn = DynamicState(chemistry, experience, form, momentum, continuity, leadership)
v3_mult = dyn.combined_multiplier()  # clamped 0.90-1.10

attack_rating = round(star_attack * (1.0 + nat_mod) * v3_mult, 4)
```

### National Modifiers (`data/national_strength_modifiers.json`)

Regional bias adjustments (e.g., South American teams at +0.03 in knockouts).

---

## V4: Tactical Intelligence Layer (`engines/v4_tactical_engine.py`)

Wraps V3, adding matchup-specific tactical adjustments.

### Layer Integration

```
V3 Dynamic Engine
    ↓
Base xG (1.60 vs 1.20)
    ↓
Tactical Matchup Service
    ↓
Adjustment: +0.06 xG
    ↓
Final xG (1.66 vs 1.26)
    ↓
Poisson (goals from xG)
```

### V4 Flow

1. **Get V3 Strength & Base xG** via `V3DynamicEngine.get_team_strength()` and `expected_goals()`
2. **Compute Tactical Matchup** via `compute_tactical_matchup()`:
   - Load tactical profiles for both teams
   - Calculate relative strength ratios
   - Determine game plans via `choose_game_plan()`
   - Apply 11 matchup effect functions
   - Clamp total adjustments to ±10% of base xG
3. **Return Final xG** for Poisson simulation

---

## V4 Tactical Matchup Engine (`services/tactical_matchup_service.py`)

### 11 Matchup Categories

#### Original 7 Matchups

**1. High Line vs Pace** (`_high_line_vs_pace`)
- Opponent with high defensive line (≥65) exploited by fast attackers
- Uses attacker pace and dribbling averages
- Boost = 0.12 * max(0, (avg_pace + avg_drib)/2 - 50) / 50

**2. Pressing vs Build-up** (`_pressing_vs_buildup`)
- High pressing (≥65) vs weak build-up (<60)
- Quality factor from opponent composure + passing
- Boost = 0.10 * press_gap * quality_factor

**3. Possession vs Low Block** (`_possession_vs_low_block`)
- High possession (≥70) vs compact defense (≥70)
- Creativity factor from vision, dribbling, crossing, long_shots
- Boost = 0.08 * creativity_factor

**4. Set Pieces** (`_set_pieces`)
- Attack vs defense rating mismatch
- Quality factor from heading, strength, crossing
- Boost = 0.10 * gap * quality_factor

**5. Aerial Battles** (`_aerial_battles`)
- Aerial strength gap > 10 points
- Quality from jumping, heading, strength
- Boost = 0.04 * (gap/50) * quality_factor

**6. Formation Matchup** (`_formation_matchup`)
- Width advantage (>10% difference)
- Central control advantage (>10% difference)
- Space behind fullbacks exploitation

**7. Player-Tactic Compatibility** (`_player_tactic_compatibility`)
- High pressing teams exploit low stamina/composure opponents
- Penalty applied against vulnerable teams

#### NEW: 8. Possession Quality (`_possession_quality`)

Separates possession **volume** from **quality** using 4 metrics:

```
possession_quality = pp * 0.25 + f3 * 0.25 + bcc * 0.30 + sq * 0.20
```

Where:
- `pp` = progressive_passes (FBref/StatsBomb)
- `f3` = final_third_entries (Opta)
- `bcc` = big_chance_creation (StatsBomb/Opta)
- `sq` = shot_quality (average xG per shot)

Boost applied when gap > 8% and attackers have vision/passing quality.

#### NEW: 9. Defensive Style Interaction (`_defensive_style_interaction`)

5 defensive styles in a 5×7 matrix matchup table:

| Style | vs high_press | vs direct | vs possession | vs high_line |
|-------|--------------|-----------|---------------|--------------|
| low_block | +0.02 | +0.02 | -0.02 | +0.03 |
| mid_block | +0.01 | +0.01 | 0.00 | +0.02 |
| high_press | +0.01 | -0.02 | +0.02 | +0.02 |
| man_marking | 0.00 | -0.01 | -0.01 | +0.01 |
| zonal | -0.01 | 0.00 | +0.01 | +0.01 |

The style key is derived from opponent's predominant attribute:
- pressing > 70 → "high_press"
- directness > 65 → "direct"
- possession > 70 → "possession"
- defensive_line > 65 → "high_line"
- else → "mid_block"

#### NEW: 10. Tactical Flexibility (`_tactical_flexibility_effects`)

- Flexibility gap > 15% → ±0.02 boost for flexible team
- Rigid team (<40) vs flexible (>60) → -0.015 penalty

#### NEW: 11. Match Context Effects (`_match_context_effects`)

| Context | Adjustment |
|---------|------------|
| knockout | Both teams -0.01 xG (cautious) |
| must_win | Attacking/high_press teams +0.02 xG |
| need_draw | Low block teams -0.015 xG |
| gd_chase | Attacking teams +0.025/-0.015 (risk/reward) |

---

## Game Plan Selection (`services/tactical_matchup_service.py:31-65`)

### Algorithm

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

### Game Plan Effects

| Plan | xG Effect | Description |
|------|-----------|-------------|
| attacking | +0.03 | More risk, more chances; -0.02 defensive vulnerability |
| counter | +0.02 | Transition threat; -0.02 possession reduction |
| low_block | -0.03/-0.02 | Fewer goals conceded; reduced attacking threat |
| high_press | +0.03 | Ball recoveries; -0.02 defensive risk |

---

## Manager Influence (`services/manager_service.py`)

### Profile Attributes (0-100 range)

| Attribute | Effect |
|-----------|--------|
| risk_tolerance | Pushes toward attacking/high_press plans |
| tactical_flexibility | Enables plan adaptation mid-match |
| pressing_preference | Favors high_press game plan |
| defensive_discipline | Adds defensive solidity |

### Game Plan Modulation (`manager_game_plan_modifier`)

- High-flex (>70) pushes "balanced" toward attacking
- Low-flex (<40) keeps conservative plans
- High-risk (>70) pushes attacking; Low-risk (<40) pulls back
- High-pressing-preference (<55) reverts high_press to balanced

### Context Adjustments (`apply_manager_context_adjustment`)

| Context | Risk > 70 | Risk < 45 | Discipline > 70 |
|---------|-----------|-----------|-----------------|
| knockout | +0.015 | -0.015 | -0.01 |
| must_win | +0.03 scaled | - | - |
| gd_chase | +0.02 | +0.01 | - |

---

## Data Flow Summary

```
FC26 Player Attributes (pace, shooting, etc.)
    ↓
┌─────────────────────────────────────────────────────────┐
│ V2 Player Strength Calculation (build_team_strength)     │
│   - Role assignment via formation slots                  │
│   - Weighted attribute formulas                          │
│   - Attack/Midfield/Defense/GK ratings                   │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│ V3 Dynamic State (6 components)                         │
│   - Chemistry (club links)                               │
│   - Experience (caps, WC appearances)                    │
│   - Form (fantasy points)                                │
│   - Momentum (rolling 5-match results)                   │
│   - Continuity (lineup stability)                        │
│   - Leadership (captains, veterans)                     │
│   Combined multiplier (0.90x - 1.10x)                    │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│ V4 Tactical Intelligence                                │
│   - Tactical profiles (22 attributes)                    │
│   - Formation characteristics (7 dimensions)               │
│   - Manager profiles (4 attributes)                      │
│   - 11 matchup categories                                │
│   - Game plan selection                                    │
│   - Match context awareness                                │
│   Adjustments clamped to ±10% of base xG                   │
└─────────────────────────────────────────────────────────┘
    ↓
    Poisson(λ = final_xG) → Goals
```

---

## Configuration Parameters (`services/tactical_matchup_service.py`)

| Parameter | Default | Location |
|-----------|---------|----------|
| `MAX_XG_ADJUSTMENT_PCT` | 0.10 | Line 68 |
| High-line pace boost | 0.12 | Line 218 |
| Pressing vs buildup | 0.10 | Line 247 |
| Possession creativity | 0.08 | Line 281 |
| Possession quality | 0.06 | Line 493 |
| Set-piece gap factor | 0.10 | Line 316 |
| Aerial gap factor | 0.04 | Line 350 |
| Flexibility edge | 0.02 | Line 623 |
| Rigidity penalty | 0.015 | Line 633 |
| Knockout suppression | -0.01 | Line 657 |
| Must-win urgency | +0.02 | Line 663 |
| GD chase risk | +0.025/-0.015 | Line 677 |

---

## Key Design Decisions

1. **Additive adjustments:** V4 modifies xG additively (not multiplicatively) to maintain linear interpretability and prevent compounding with V3.

2. **±10% cap:** Ensures tactical differences cannot overturn major quality gaps. A 2.0 xG favorite remains favorite even with tactical disadvantages.

3. **Player-mediated effects:** Team-level tactical profiles provide direction, but FC26 attributes determine actual effect magnitude (pace determines high-line exploit, vision/passing determines possession quality boost).

4. **Composable layers:** V4 wraps V3 without modifying it. V3 can run independently. V2 can run independently. V1 is standalone.

5. **Explainable adjustments:** Every tactical modifier has category, value, and description for debugging.

6. **Context-aware game plans:** Game plan selection integrates relative strength (V3), opponent style (tactical profiles), and match context.

---

## Execution Flow

### Match Simulation (`V4TacticalEngine.simulate_match_debug`)

```python
# 1. Increment match counter
self._match_number += 1

# 2. Determine context
context = "knockout" if not can_draw else "group"

# 3. Get V3 strength (includes dynamic state)
strength1 = self._v3.get_team_strength(team1, is_knockout)
strength2 = self._v3.get_team_strength(team2, is_knockout)

# 4. Get V3 base xG
base_lambda1, base_lambda2 = self._v3.expected_goals(strength1, strength2)

# 5. Apply V4 tactical adjustments
report = compute_tactical_matchup(team1, team2, base_lambda1, base_lambda2, squad1, squad2, context)

# 6. Poisson simulation with final xG
g1 = poisson(max(self.minimum_lambda, report.final_xg_a))
g2 = poisson(max(self.minimum_lambda, report.final_xg_b))

# 7. Extra time / penalties if knockout tie
# ... (same as V3)

# 8. Update V3 services (momentum, continuity)
self._v3.momentum_service.record_result(team1, g1, g2, False)
self._v3.continuity_service.record_lineup(team1, player_names)

# 9. Format debug output
return score, v4_debug_output
```

---

## Files Reference

| Layer | File | Purpose |
|-------|------|---------|
| V1 | `engines/v1_elo_engine.py` | ELO-based simulation |
| V2 | `engines/v2_player_engine.py` | Player attribute simulation |
| V2 | `models/team_strength.py` | Role formulas, strength calculation |
| V3 | `engines/v3_dynamic_engine.py` | Dynamic state engine |
| V3 | `models/dynamic_state.py` | ComponentScore, DynamicState dataclasses |
| V3 | `services/chemistry_service.py` | Team chemistry calculation |
| V3 | `services/experience_service.py` | Experience calculation |
| V3 | `services/form_service.py` | Form calculation |
| V3 | `services/momentum_service.py` | Momentum tracking |
| V3 | `services/continuity_service.py` | Continuity calculation |
| V3 | `services/leadership_service.py` | Leadership calculation |
| V4 | `engines/v4_tactical_engine.py` | Tactical engine (wraps V3) |
| V4 | `models/tactical_state.py` | TacticalAdjustment, TacticalReport, FormationProfile, ManagerProfile |
| V4 | `services/tactical_matchup_service.py` | 11 matchup categories, game plan selection |
| V4 | `services/formation_service.py` | Formation profiles and matchup evaluation |
| V4 | `services/manager_service.py` | Manager profile loading and modulation |
| V4 | `data/tactical_profiles.json` | 22 tactical attributes per team |
| V4 | `data/manager_profiles.json` | 4 manager attributes per team |