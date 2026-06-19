# V4 Architecture: Tactical Intelligence Engine (Improved)

## V4 Overview

V4 adds a **Tactical Intelligence** layer on top of V3's dynamic team state system.

**V3 asks:** "How good is this team right now?"
**V4 asks:** "How do these two teams actually approach this specific match under this specific situation?"

V4 does not replace V1-V3. It is an additional layer that modifies V3 xG based on tactical matchups, manager profiles, possession quality, defensive styles, tactical flexibility, and match context.

```
FC26 Players
    ↓
V2 Player Strength
    ↓
V3 Dynamic State (chemistry, form, momentum, continuity, experience, leadership)
    ↓
V4 Tactical Intelligence Layer  <-- 6 new module categories
    ↓
Adjusted Expected Goals
    ↓
Poisson Simulation
```

Tactical effects are constrained to ±10% of base xG to ensure elite quality differences remain the primary factor.

---

## Data Sources

### Tactical Profiles (`data/tactical_profiles.json`)

Each of the 48 World Cup teams has a tactical profile with **22 attributes** rated 0-100.

#### Original 15 Attributes

| Attribute | Description | Source Tier |
|-----------|-------------|-------------|
| possession | Ability and preference to control the ball | Analysis of match statistics |
| build_up | Ability to progress from defense | Analysis of passing patterns |
| directness | Preference for quick vertical attacks | Match observation |
| pressing | Intensity of pressing | Match observation |
| counter_press | Ability to win ball after losing possession | Match analysis |
| counter_attack | Threat during transitions | Match analysis |
| defensive_line | How high the team defends | Match observation |
| defensive_compactness | Ability to close central spaces | Match analysis |
| width | Use of wide areas | Formation/tactical analysis |
| central_play | Ability through midfield combinations | Match analysis |
| transition_speed | Speed of attacking transitions | Match observation |
| set_piece_attack | Corners and free-kick threat | Set piece analysis |
| set_piece_defense | Ability to defend dead balls | Set piece analysis |
| aerial_strength | Heading and physical presence | Physical metrics |
| press_resistance | Ability to escape pressure | Build-up analysis |

#### New Possession Quality Attributes (FBref / StatsBomb / Opta-based)

| Attribute | Description | Source Tier |
|-----------|-------------|-------------|
| progressive_passes | Passes that move ball 10+ yards toward opponent's goal | FBref, StatsBomb |
| final_third_entries | Number of times ball enters attacking third | Opta event data |
| big_chance_creation | Opta-defined 'big chances' created per match | StatsBomb, Opta |
| shot_quality | Average xG per shot (chance creation efficiency) | StatsBomb, Opta |

#### New Defensive Style Attributes

| Attribute | Description | Source Tier |
|-----------|-------------|-------------|
| defensive_style | One of: low_block, mid_block, high_press, man_marking, zonal | FIFA tech reports |
| man_marking_tendency | Preference for man-oriented marking | Match analysis |
| zonal_discipline | Ability to maintain zonal shape | Match analysis |

#### New Tactical Attributes

| Attribute | Description | Source Tier |
|-----------|-------------|-------------|
| tactical_flexibility | Ability to adapt formation/style mid-match | Manager analysis |

### Manager Profiles (`data/manager_profiles.json`)

Every team has a manager with 4 profile attributes:

| Attribute | Range | Description | Source |
|-----------|-------|-------------|--------|
| risk_tolerance | 0-100 | Willingness to take tactical risks | FIFA reports, interviews |
| tactical_flexibility | 0-100 | Ability to adapt game plan mid-match | The Coaches' Voice |
| pressing_preference | 0-100 | Natural inclination toward pressing | Tactical analysis |
| defensive_discipline | 0-100 | Organisation quality of defensive setup | Match observation |

**Notable managers:**
- **Marcelo Bielsa (Uruguay):** risk=88, pressing=92, flex=75 — extreme risk/pressing
- **Julian Nagelsmann (Germany):** risk=78, flex=88, pressing=85 — modern high-flexibility
- **Gareth Southgate (England):** risk=50, discipline=82, flex=65 — cautious, disciplined
- **Walid Regragui (Morocco):** discipline=82, flex=74 — defensive organisation specialist

### Data Quality

| Tier | Sources | Confidence |
|------|---------|------------|
| 1 (Preferred) | FIFA tactical reports, FBref, StatsBomb | High (0.8-1.0) |
| 2 | The Coaches' Voice, major sports publications | Medium (0.6-0.8) |
| 3 | Expert commentary and video breakdowns | Low (0.4-0.6) |

---

## Formation Intelligence (`services/formation_service.py`)

Formations are not only shapes. Each formation has characteristics:

| Formation | Width | Central Control | Defensive Stability | Pressing | Space Behind FBs |
|-----------|:-----:|:---------------:|:-------------------:|:--------:|:----------------:|
| 4-3-3 | 0.80 | 0.55 | 0.50 | 0.80 | 0.60 |
| 4-2-3-1 | 0.65 | 0.75 | 0.70 | 0.60 | 0.40 |
| 4-4-2 | 0.70 | 0.50 | 0.65 | 0.55 | 0.35 |
| 3-4-3 | 0.85 | 0.50 | 0.40 | 0.65 | 0.70 |
| 3-5-2 | 0.70 | 0.75 | 0.55 | 0.60 | 0.60 |
| 5-3-2 | 0.50 | 0.60 | 0.85 | 0.35 | 0.25 |
| 5-4-1 | 0.45 | 0.55 | 0.90 | 0.30 | 0.20 |
| 4-1-4-1 | 0.65 | 0.65 | 0.75 | 0.55 | 0.35 |

Formation matchup advantages are computed by comparing these profiles across width, midfield control, and space-behind-fullbacks dimensions.

---

## Tactical Matchup Engine (`services/tactical_matchup_service.py`)

### Matchup Categories (11 total)

#### Original 7

##### 1. High Line vs Pace
If Team A defends high and Team B has fast attackers, Team B's transition xG increases.
```
pace_factor = max(0, (avg_attacker_pace + avg_attacker_dribbling) / 2 - 50) / 50.0
boost = 0.12 * pace_factor
```
**FC26 attributes:** pace, dribbling

##### 2. Pressing vs Build-up
If Team A presses aggressively and Team B has weak build-up.
```
press_gap = (pressing_a - build_up_b) / 100.0
quality_factor = max(0, 1.0 - (composure_b + passing_b) / 200.0)
boost = 0.10 * press_gap * quality_factor
```
**FC26 attributes:** passing, composure

##### 3. Possession vs Low Block
If Team A dominates possession and Team B is compact, evaluate creativity.
```
creativity = (vision + dribbling + crossing + long_shots) / 4.0
creativity_factor = max(0, (creativity - 50) / 50.0)
boost = 0.08 * creativity_factor
```
**FC26 attributes:** vision, dribbling, crossing, long_shots

##### 4. Set Pieces
Comparative set-piece threat based on attack vs defense ratings.
```
sp_quality = (heading_accuracy + strength + crossing) / 3.0
gap = (sp_attack - sp_defense) / 100.0
boost = 0.10 * gap * max(0, (sp_quality - 50) / 50.0)
```
**FC26 attributes:** crossing, heading_accuracy, strength

##### 5. Aerial Battles
Aerial advantage based on team rating gap and player attributes.
```
aerial_quality = (jumping + heading_accuracy + strength) / 3.0
gap = aerial_a - aerial_b
boost = 0.04 * (gap / 50.0) * max(0, (aerial_quality - 50) / 50.0)
```
**FC26 attributes:** jumping, strength, heading_accuracy

##### 6. Formation Matchup
Width advantages, midfield numerical superiority, space behind fullbacks.

##### 7. Player-Tactic Compatibility
Individual player attributes moderate tactical effects. Mbappe-level pace exploits a high line more than a slow team.

#### NEW: 8. Possession Quality

Separates possession **volume** from **quality**. Uses FBref/StatsBomb-derived metrics:

```
a_quality = (progressive_passes * 0.25 + final_third_entries * 0.25 + big_chance_creation * 0.30 + shot_quality * 0.20)
gap = (a_quality - b_quality) / 100.0
if abs(gap) > 0.08:
    boost = 0.06 * gap * quality_factor
```

A team with 70% sideways possession (low progressive passes) gets less benefit than a team with 55% but high progressive pass rate. This models the difference between:
- **Spain 2010**: 70% possession, high quality → deserved xG boost
- **Possession-without-penetration**: high volume, low quality → minimal boost

#### NEW: 9. Defensive Style Interaction

Each team has one of 5 defensive styles. These interact in a 5×7 matrix:

| Style | vs high_press | vs mid_block | vs high_line | vs possession | vs direct | vs man_marking | vs zonal |
|-------|:-----------:|:----------:|:----------:|:----------:|:--------:|:------------:|:------:|
| low_block | +0.02 | +0.01 | +0.03 | -0.02 | +0.02 | +0.01 | +0.01 |
| mid_block | +0.01 | 0.00 | +0.02 | 0.00 | +0.01 | +0.01 | 0.00 |
| high_press | +0.01 | +0.01 | +0.02 | +0.02 | -0.02 | +0.01 | +0.01 |
| man_marking | 0.00 | 0.00 | +0.01 | -0.01 | -0.01 | 0.00 | -0.01 |
| zonal | -0.01 | 0.00 | +0.01 | +0.01 | 0.00 | +0.01 | 0.00 |

**Example interactions:**
- Low block vs high line (+0.03): Low block sits deep, exploits space behind pushing fullbacks
- High press vs direct (-0.02): Direct balls over the press bypass the intensity
- Low block vs possession (-0.02): Patient possession can break down deep blocks
- Man marking vs possession (-0.01): Position-swapping attackers can lose markers

#### NEW: 10. Tactical Flexibility

Teams with high tactical flexibility (70+) can partially counter opponent advantages:
```
flex_gap = (flex_a - flex_b) / 100.0
boost = 0.02 * flex_gap  (if abs(flex_gap) > 0.15)
```

Rigid teams (flex < 40) against flexible opponents suffer an additional penalty:
```
penalty = -0.015 * (flex_b - flex_a) / 60.0
```

**Examples:**
- Spain (flex 88) vs rigid minnow (flex 35): Spain gets +0.01 xG, minnow gets -0.013 xG
- Germany (flex 85) vs Switzerland (flex 68): Small flexibility edge for Germany

#### NEW: 11. Match Context Effects

Different match situations produce different tactical behaviors:

| Context | Effect |
|---------|--------|
| **group** (default) | Standard approach, no adjustment |
| **knockout** | Both teams -0.01 xG (higher stakes, less risk) |
| **must_win** | Attacking/high press teams get +0.02 xG urgency |
| **need_draw** | Low block teams get -0.015 xG (defensive focus) |
| **gd_chase** | Attacking teams get +0.025 xG, -0.015 defensive cost |

Game plan selection also adapts to context:
- **knockout**: More conservative thresholds (strength > 1.10 → balanced, not attacking)
- **must_win**: More aggressive thresholds (strength > 0.95 → attacking)
- **need_draw**: Defensive thresholds (strength < 0.90 → low block)

---

## Manager Influence (`services/manager_service.py`)

Manager profiles modulate game plan selection and produce context-specific adjustments:

### Game Plan Modulation
```
manager_game_plan_modifier(team, base_plan, relative_strength)
```
- High-risk managers (Bielsa: 88) push "balanced" toward "attacking"
- Low-risk managers (Southgate: 50) may pull "attacking" toward "balanced" when strength is marginal
- High pressing-preference managers favor high_press plans

### Context Adjustments
```
apply_manager_context_adjustment(team, context, plan)
```

| Manager Trait | Context | Effect |
|---------------|---------|--------|
| High risk (>70) | knockout | +0.015 xG (bold approach) |
| Low risk (<45) | knockout | -0.015 xG (cautious) |
| High discipline (>70) | knockout | -0.01 xG (defensive solidity) |
| High risk (>55) | gd_chase | +0.02 xG |
| Low risk (<=55) | gd_chase | +0.01 xG |

---

## Game Plans

Before every match, V4 chooses a strategy based on relative strength, opponent style, match context, and manager profile:

| Plan | Conditions | Effects |
|------|-----------|---------|
| Attacking | strength > 1.15x opponent | +0.03 xG, -0.02 defensive |
| Balanced | Default | No adjustment |
| Counter | strength < 0.85x opponent | +0.02 xG transitions, -0.02 possession |
| Low Block | strength < 0.85x + opponent counters | -0.03 conceded, -0.02 attack |
| High Press | strength > 1.15x | +0.03 recoveries, -0.02 defensive risk |

Context and manager profiles can override these defaults (see sections above).

---

## xG Adjustment

V4 modifies V3 xG with additive adjustments, clamped to ±10% of base xG (minimum ±0.05).

**Example: France vs Morocco (knockout context)**

| Team | Base xG | Tactical Adjustments | Final xG |
|------|:-------:|:--------------------:|:--------:|
| France | 1.60 | +0.03 (game_plan) +0.015 (manager) -0.01 (context) | 1.635 |
| Morocco | 1.20 | +0.02 (game_plan) +0.01 (defensive style) -0.01 (context) | 1.220 |

Clamping formula:
```
max_adj = max(base_xg * 0.10, 0.05)
clamped_adj = max(-max_adj, min(max_adj, total_adj))
final_xg = max(0.01, base_xg + clamped_adj)
```

If raw adjustments exceed the cap, a `clamp` adjustment is added with explanation.

---

## FC26 Attribute Mappings

| Tactical Context | FC26 Attributes Used |
|------------------|---------------------|
| Pace exploitation | pace, dribbling |
| Press vulnerability | stamina, composure, passing |
| Possession creativity | vision, dribbling, crossing, long_shots |
| Possession quality | vision, passing |
| Set-piece threat | crossing, heading_accuracy, strength |
| Aerial battles | jumping, heading_accuracy, strength |

---

## Configuration

All tactical parameters are tunable in `services/tactical_matchup_service.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_XG_ADJUSTMENT_PCT` | 0.10 (10%) | Maximum tactical adjustment as fraction of base xG |
| High-line pace factor | 0.12 | Base boost for pace exploitation |
| Pressing boost | 0.10 | Base boost for pressing vs weak buildup |
| Possession creativity | 0.08 | Base boost for creative possession teams |
| Possession quality factor | 0.06 | Base boost for possession quality advantage |
| Set-piece gap factor | 0.10 | Base boost for set-piece mismatches |
| Aerial gap factor | 0.04 | Base boost for aerial dominance |
| Flexibility factor | 0.02 | Base boost per 0.15 flex gap |
| Rigidity penalty | 0.015 | Penalty for rigid vs flexible |
| Attacking game plan | +0.03/-0.02 | Risk/reward for attacking plans |
| Counter game plan | +0.02/-0.02 | Transition vs possession trade-off |
| Low block | -0.03/-0.02 | Defensive solidity vs attacking cost |
| Knockout context | -0.01 | Slight xG suppression in knockouts |
| Must-win context | +0.02 | Urgency boost when must win |
| GD chase context | +0.025/-0.015 | High-risk attacking in GD situations |

---

## Key Design Decisions

1. **Additive, not multiplicative**: Tactical effects modify xG as additive adjustments, not multipliers. This prevents compounding between V3 and V4.

2. **±10% cap**: Tactical effects cannot overturn major quality differences. Elite teams remain favorites.

3. **Player-mediated**: Team-level tactical profiles provide the base, but FC26 player attributes moderate the actual effect size.

4. **Explainable**: Every tactical modifier has a category, description, and exact value. Debug mode shows the full chain.

5. **Game plan selection**: Based on relative V3 strength, match context, AND manager profile — multi-factor decision.

6. **Possession quality ≠ volume**: Possession quality metrics (progressive passes, final-third entries, big chances) separate meaningful possession from sterile ball circulation.

7. **Defensive styles**: 5 distinct defensive approaches with a matchup matrix — low block isn't just "defend deep," it interacts differently with pressing, direct play, and possession than mid block does.

8. **Match context matters**: A must-win group match produces different tactical behavior than a knockout tie or a GD chase.

---

## Validation

### Benchmark Tests (38 tests)
- All 20 original V4 tests pass
- 18 new tests covering:
  - Manager profile loading and validation (9 tests)
  - Updated profile structure (6 tests)
  - Possession quality adjustments (2 tests)
  - Defensive style interactions (3 tests)
  - Tactical flexibility (3 tests)
  - Match context effects (5 tests)
  - V4 improved engine integration (5 tests)
  - Boundary conditions (3 tests)
  - Model dataclasses (2 tests)

### Verified Properties
- Elite teams remain favorites in all matchups
- Tactical adjustments capped at ±10% of base xG
- All 5 defensive styles appear in profiles
- All 5 match contexts produce correct behavior
- Knockout context slightly suppresses xG
- Must-win and GD chase contexts increase attacking intent
- Manager profiles load for all 48 teams with valid ranges

### Expected Results
- Elite teams remain favorites in all matchups
- Tactical mismatches provide 0.02-0.15 xG swing
- Upsets remain possible through Poisson variance
- V4 improved adds realism through context-dependent tactical decisions

---

## Debug Mode

```bash
.fsim v4 --debug
```

Output includes V3 debug section followed by V4 tactical report with all 11 matchup categories:

```
=== V3 DEBUG ===
France vs Morocco
...

=== V4 TACTICAL INTELLIGENCE ===
Tactical Matchup Report: France vs Morocco
Match Context: knockout

Game Plans: France (attacking) vs Morocco (counter)

Base xG (from V3):
  France: 1.50
  Morocco: 1.20

Tactical Advantages (France):
  + Midfield numerical advantage
  + Possession quality advantage (+0.02 xG)
  + Defensive style advantage (high_press vs low_block)
  + Tactical flexibility advantage (+0.01 xG)

Tactical Advantages (Morocco):
  + High defensive line exploited by pace (+0.10 xG)
  + Counter game plan: transition threat (+0.02 xG)

V4 Tactical Adjustments:
  France:
    game_plan: +0.0300 xG  [Attacking game plan]
    possession_quality: +0.0200 xG  [Superior possession quality]
    defensive_style: +0.0100 xG  [high_press vs possession: disrupts build-up]
    flexibility: +0.0100 xG  [Tactical flexibility edge (78 vs 68)]
    match_context: -0.0100 xG  [Knockout stage: higher stakes, less risk]
    Total: +0.0600 xG
  Morocco:
    high_line_exploit: +0.1000 xG  [High line exploited by pace]
    game_plan: +0.0200 xG  [Counter game plan: faster transitions]
    defensive_style: +0.0100 xG  [low_block vs high_press: absorbs press]
    match_context: -0.0100 xG  [Knockout stage: higher stakes, less risk]
    Total: +0.1200 xG

Final xG (V3 + V4 tactical):
  France: 1.5600
  Morocco: 1.3000

Final Score: 2-1
```

Every tactical modifier is explainable with category, value, and description.

---

## Files

### New Files

| File | Purpose |
|------|---------|
| `models/tactical_state.py` | TacticalAdjustment, TacticalReport, FormationProfile, ManagerProfile, MatchContext dataclasses |
| `data/tactical_profiles.json` | 48 team tactical profiles (22 attributes each) |
| `data/manager_profiles.json` | 48 manager profiles (4 attributes each) |
| `services/formation_service.py` | Formation characteristics and matchup evaluation |
| `services/tactical_matchup_service.py` | Core matchup engine (11 categories) |
| `services/manager_service.py` | Manager profile loading and game plan modulation |
| `engines/v4_tactical_engine.py` | V4 engine wrapping V3 with tactical layer |
| `tests/test_v4_tactical_engine.py` | 20 original V4 tactical benchmark tests |
| `tests/test_v4_improved.py` | 38 improved V4 tests |
| `V4_TACTICAL_ARCHITECTURE.md` | This file |
| `scripts/generate_tactical_profiles.py` | Script to generate/update tactical profiles |
| `scripts/generate_v4_improved_data.py` | Script to generate improved V4 data files |

### Modified Files

| File | Change |
|------|--------|
| `engines/__init__.py` | Export V4TacticalEngine |
| `models/__init__.py` | Export tactical state models |
| `__init__.py` | Export V4TacticalEngine |
| `services/simulation_service.py` | Handle model="v4" |
| `engines/v4_tactical_engine.py` | Accept match context parameter |

---

## Usage

```python
from fifa_data import run_simulation

# Run V4 simulation (improved)
result = run_simulation(model="v4", debug=True)
print(result["champion"])

# View tactical debug output
for debug in result.get("debug", []):
    print(debug)

# Direct engine access with context
from fifa_data.engines import V4TacticalEngine
engine = V4TacticalEngine(data_dir="fifa_data")

# Knockout context with tactical depth
xg1, xg2 = engine.expected_goals("France", "Morocco", context="knockout")
score, debug = engine.simulate_match_debug("England", "Germany", can_draw=False, context="knockout")
```

### Discord Commands
```bash
.sim v1          # ELO-based simulation
.sim v2          # Player attribute simulation
.sim v3          # Dynamic state simulation
.sim v4          # Tactical intelligence simulation (improved)
.sim v4 debug    # Show tactical breakdowns
.sim v4 animated # Watch matches in real time
.sim help        # Show model comparison
```

---

## Future Extensions

- **Dynamic tactical profiles**: Update profiles based on in-tournament performance
- **In-match adjustments**: Tactic changes at halftime based on score
- **Set-piece routines**: Specific set-piece patterns from match data
- **Fatigue effects**: Tactical execution degrading with player fatigue
- **ML-informed profiles**: Machine learning from Opta/StatsBomb event data
- **Head-to-head historical context**: Previous meeting results influence game plan
