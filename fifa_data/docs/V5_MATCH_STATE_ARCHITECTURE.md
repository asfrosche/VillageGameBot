# V5 Architecture: Match State Engine

## Overview

V5 is the most advanced match simulation engine. It moves beyond static expected-goals by simulating matches **phase-by-phase** with continuous live state tracking — fatigue, momentum, cards, substitutions, and manager reactions all update every 15 minutes. The goal is emergent, realistic match narratives.

```
V4 Tactical Engine → Base xG → Phase-by-Phase Simulation → Live Events → Final Score
```

---

## Inheritance Chain

```
MatchEngine (abstract base)
├── V1EloMatchEngine        — team ELO/PELE only
├── V2PlayerMatchEngine     — player attributes, roles, formations
├── V3DynamicEngine         — 6 dynamic states + ELO + national modifiers
├── V4TacticalEngine        — wraps V3; tactical adjustments (13 factors)
└── V5MatchStateEngine      — wraps V4; phase-by-phase with fatigue, cards, subs
```

Each engine is standalone — V4 holds a `V3DynamicEngine`; V5 holds a `V4TacticalEngine` (accesses `self._v4._v3` for underlying V3 services).

---

## V5 Architecture Diagram

```
simulate_match(team1, team2, can_draw)
│
├─ 1. Initialize MatchState
│     └─ Creates PlayerMatchState per player (100% energy)
│
├─ 2. Compute Base Strengths
│     └─ _v4._v3.get_team_strength() → TeamStrength
│     └─ _v4._v3.expected_goals() → base_lambda_a, base_lambda_b
│
├─ 3. Compute Tactical Matchup
│     └─ compute_tactical_matchup() → TacticalReport
│     └─ final_xg_a, final_xg_b (clamped to max_xg = 4.0)
│
├─ 4. Loop: 6 Regular Phases
│     │
│     ├─ Apply Fatigue
│     │   └─ Per-player energy loss based on stamina, age, work rate,
│     │      physical, pace, match intensity, pressing intensity
│     │   └─ Extra time: 1.3× fatigue multiplier
│     │
│     ├─ Decay Momentum
│     │   └─ MomentumService.decay_momentum()
│     │
│     ├─ Compute Phase xG
│     │   └─ phase_xg = base_lambda × (15/90)
│     │   └─ energy_mod = 0.75 + (energy_avg / 100) × 0.25
│     │   └─ momentum_mod = get_momentum_multiplier(momentum)
│     │   └─ score_mod = scoreline_xg_modifier()
│     │   └─ red_mod = 1.0 - 0.25 × red_cards
│     │   └─ Return max(0.01, phase_xg × all_modifiers)
│     │
│     ├─ Generate Events
│     │   └─ EventEngine: shots, goals, cards, fouls
│     │   └─ Momentum updates from events
│     │
│     ├─ Evaluate Substitutions
│     │   └─ Fatigue <30% → urgent
│     │   └─ Yellow-carded defenders → high priority
│     │   └─ Match rating <6.0 → subbed
│     │   └─ Finds best replacement by role + scoreline urgency
│     │
│     └─ Evaluate Manager Reactions
│         └─ May change game plan based on scoreline + minute + profile
│
├─ 5. Extra Time (if knockout & tied)
│     └─ 2 phases (ET_FIRST, ET_SECOND)
│     └─ 0.7× lambda scaling, 1.3× fatigue multiplier
│
├─ 6. Penalty Shootout (if still tied)
│     └─ PenaltyEngine: top 5 takers by penalties+finishing+composure
│     └─ Per-shot: taker vs goalkeeper attributes
│     └─ Sudden death after 5 rounds
│
└─ 7. Record + Debug
      └─ Update V3 continuity & momentum
      └─ Generate match story, timeline, top performers
```

---

## Match Phases

```python
PHASE_ORDER = [
    EARLY_FIRST_HALF,    # 0-15 min  (midpoint: 7.5)
    MID_FIRST_HALF,      # 15-30 min (midpoint: 22.5)
    LATE_FIRST_HALF,     # 30-45 min (midpoint: 37.5)
    EARLY_SECOND_HALF,   # 45-60 min (midpoint: 52.5)
    MID_SECOND_HALF,     # 60-75 min (midpoint: 67.5)
    LATE_SECOND_HALF,    # 75-90 min (midpoint: 82.5)
]

EXTRA_TIME_PHASES = [
    EXTRA_TIME_FIRST,    # 90-105 min (midpoint: 97.5)
    EXTRA_TIME_SECOND,   # 105-120 min (midpoint: 112.5)
]
```

---

## Phase xG Calculation

Each 15-minute phase, base xG is modulated by 4 factors:

```python
phase_xg = base_lambda × (15.0 / 90.0)  # Scale to 15-minute window

# 1. Energy modifier
energy_avg = mean(all starting XI energy)
energy_mod = 0.75 + (energy_avg / 100.0) × 0.25
# Range: 0.75 (0% energy) to 1.00 (100% energy)

# 2. Momentum modifier
momentum_mod = get_momentum_multiplier(momentum_value)
# Maps momentum to 0.85–1.15x range

# 3. Scoreline modifier
score_mod = scoreline_xg_modifier(scoreline_state, minute)
# See table below

# 4. Red card modifier
red_mod = 1.0 - 0.25 × red_card_count

return max(0.01, phase_xg × energy_mod × momentum_mod × score_mod × red_mod)
```

### Scoreline Modifier

| Scoreline | Minute | Attack Mod | Defense Mod | Risk Mod | Combined |
|-----------|--------|------------|-------------|----------|----------|
| winning | <75 | 0.95 | 1.05 | — | ~1.00 |
| winning | ≥75 | 0.87 | 1.10 | — | ~0.99 |
| trailing | <75 | 1.10 | 0.95 | 1.15 | ~1.08 |
| trailing (2+) | <75 | 1.15 | 0.92 | 1.25 | ~1.13 |
| trailing | ≥75 | 1.19 | 0.95 | 1.27 | ~1.15 |
| trailing (2+) | ≥75 | 1.24 | 0.92 | 1.38 | ~1.20 |
| level | any | 1.00 | 1.00 | — | 1.00 |

When trailing by 2+ goals, teams attack more aggressively (risk mod increases). After 75 minutes, urgency amplifies.

---

## Key V5 Services

| Service | File | What It Does |
|---------|------|-------------|
| **FatigueService** | `substitution_manager.py` | Computes energy loss per phase per player. Factors: stamina, age, work rate, physical, pace, match intensity, pressing intensity, extra time. |
| **CardService** | `card_service.py` | Per-event probability of foul, yellow, red. Inputs: aggression, composure, defending, energy level, current cards. |
| **MatchMomentumService** | `match_momentum_service.py` | Real-time momentum tracker. Events trigger: goal +25, concede -20, big chance +5, red card -30. Decays per phase. Provides multiplier (0.85-1.15x). |
| **EventEngine** | `event_engine.py` | Generates phase events from xG. Estimates attack count, distributes over minutes, determines shots/goals. Goal probability integrates finishing + composure vs GK. |
| **PenaltyEngine** | `penalty_engine.py` | Full 5-round + sudden death. Selects takers by penalties+finishing+composure. Each attempt: taker vs GK attributes. |
| **SubstitutionService** | `substitution_manager.py` | Evaluates subs each phase. Fatigue <30% urgent. Yellow-carded defenders high priority. Rating <6.0 subbed. Manager profile influences. |
| **GameScriptService** | `game_script_service.py` | Post-match: match story narrative, event timeline, top performers by weighted score. |
| **MatchStateService** | `match_state_service.py` | Initializes MatchState, advances phases, evaluates manager reactions, computes possession. |

---

## MatchState Dataclass

```python
MatchState
├── team_a, team_b: str
├── scoreline: ScorelineState (goals, description)
├── player_states: dict[str, PlayerMatchState]  ← per-player energy, cards, rating
├── momentum_a, momentum_b: float
├── current_phase: MatchPhase
├── minute: int
├── game_plan_a, game_plan_b: str
├── game_plan_history_a, game_plan_history_b: list[(minute, plan)]
├── events: list[MatchEvent]
├── substitutions: list[SubstitutionEvent]
├── phase_stats_a, phase_stats_b: dict[str, PhaseStats]
├── red_card_count_a, red_card_count_b: int
├── is_extra_time, is_penalty_shootout: bool
├── team_a_players, team_b_players: dict[str, PlayerMatchState]
└── possession: dict[str, float]
```

---

## PlayerMatchState (Per-Player Live State)

```python
PlayerMatchState
├── energy: float (100 → 0)
├── morale: float (affects performance 0.88-1.08x)
├── match_rating: float (1-10 scale)
├── cards: int (0, 1=yellow, 2=red)
├── minutes_played: int
├── goals, assists, fouls, shots, tackles, interceptions: int
├── pressing_intensity: float
├── apply_energy_effects() → degrades attributes at energy thresholds
└── morale_multiplier() → returns 0.88-1.08x
```

---

## Phase Execution Detail

For each phase in `PHASE_ORDER`:

1. **Apply Fatigue**
   - `fatigue_service.apply_phase_fatigue()` updates each player's energy
   - Extra time uses 1.3× fatigue multiplier
   - Pressing intensity from game plan

2. **Decay Momentum**
   - `momentum_service.decay_momentum()` reduces momentum toward 0

3. **Compute Phase xG**
   - Base xG scaled to 15-minute window
   - Modified by energy, momentum, scoreline, red cards

4. **Generate Events**
   - `event_engine.generate_phase_events()` creates match events
   - Estimates attack count from xG, distributes over minutes
   - Determines shots, big chances, goals per attack
   - Goal probability: finishing + composure vs GK reflexes + positioning
   - Triggers cards via `card_service`

5. **Evaluate Substitutions**
   - `substitution_service.evaluate_substitutions()` checks:
     - Energy < 30% → urgent sub
     - Yellow-carded defenders → high priority
     - Match rating < 6.0 → tactical sub
   - Finds best replacement by role compatibility + scoreline urgency
   - Manager profile influences sub timing

6. **Manager Reactions**
   - `match_state_service.evaluate_manager_reaction()` may change game plan
   - Based on scoreline, minute, manager risk tolerance
   - Game plan change recorded in history + events

---

## Extra Time

When knockout match is tied after 90 minutes:

```python
state.is_extra_time = True

for phase in EXTRA_TIME_PHASES:
    et_lambda1 = lambda1 × 0.30 × 0.7  # Reduced scoring
    et_lambda2 = lambda2 × 0.30 × 0.7

    # Same phase execution with 1.3× fatigue multiplier
    _run_phase(state, ..., is_extra_time=True)

    g1 = state.scoreline.goals_a
    g2 = state.scoreline.goals_b
```

- Lambda scaled by 0.30 (ET scale) × 0.7 (additional dampening)
- Fatigue multiplier 1.3× (players tire faster)
- Same event generation, substitution, and momentum systems

---

## Penalty Shootout

If still tied after extra time:

```python
state.is_penalty_shootout = True

penalty_shootout_a, penalty_shootout_b, winner = \
    penalty_engine.simulate_penalty_shootout(squad1, squad2, team1, team2)
```

### PenaltyEngine Flow

1. **Select top 5 takers**: sorted by `penalties + finishing + composure`
2. **Per-shot**: taker attributes vs goalkeeper `penalty_save + reflexes + positioning`
3. **5 rounds**: alternating penalties
4. **Sudden death**: if tied after 5 rounds, continues until one team leads after both have kicked

---

## Event Types

```python
class EventType(Enum):
    GOAL = "goal"
    SHOT = "shot"
    BIG_CHANCE = "big_chance"
    FOUL = "foul"
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"
    SUBSTITUTION = "substitution"
    TACTICAL_CHANGE = "tactical_change"
    CORNER = "corner"
    FREE_KICK = "free_kick"
    OFFSIDE = "offside"
    SAVE = "save"
```

Each event records: minute, team, player, type, xg (for shots), detail.

---

## Debug Output

V5 produces comprehensive debug output:

```
============================================================
V5 MATCH STATE SIMULATION
============================================================
Brazil vs Germany
Final Score: 2 - 1

============================================================
MATCH FLOW
============================================================
Phase 1: Brazil attacks=4 shots=3 xG=0.42 | Germany attacks=3 shots=2 xG=0.31
Phase 2: Brazil attacks=5 shots=4 xG=0.55 | Germany attacks=4 shots=3 xG=0.38
...

============================================================
EVENT TIMELINE
============================================================
  12' ⚽ GOAL — Brazil — Vinicius Jr. (xG: 0.72)
  23' 🟨 YELLOW — Germany — Rudiger (foul)
  34' ⚽ GOAL — Germany — Musiala (xG: 0.45)
  67' 🔄 SUB — Brazil — OFF: Paqueta, ON: Bruno Guimaraes
  78' ⚽ GOAL — Brazil — Raphinha (xG: 0.38)
  82' 🔄 SUB — Germany — OFF: Musiala, ON: Wirtz
  88' 🟥 RED — Germany — Rudiger (second yellow)

============================================================
TOP PERFORMERS
============================================================
  Vinicius Jr. (Brazil): rating=8.2 goals=1 assists=0 shots=4 energy=72%
  Raphinha (Brazil): rating=7.8 goals=1 assists=1 shots=3 energy=68%
  Musiala (Germany): rating=7.5 goals=1 assists=0 shots=2 energy=65%

============================================================
MATCH STORY
============================================================
  Brazil took an early lead through Vinicius Jr...
  Germany equalized before halftime...
  Raphinha restored the lead in the second half...
  Rudiger's red card sealed Germany's fate...

============================================================
V5 SUB-SYSTEM STATE
============================================================
Momentum: Brazil=15.2, Germany=-8.5
Game Plans: Brazil=balanced, Germany=attacking
Red Cards: Brazil=0, Germany=1
Substitutions: 3
Total Events: 24
Avg Energy: Brazil=68.5%, Germany=61.2%
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `engines/v5_match_state_engine.py` | V5 engine (471 lines) |
| `engines/v4_tactical_engine.py` | Underlying V4 engine |
| `models/match_state.py` | `MatchState`, `MatchPhase`, `ScorelineState`, `PHASE_ORDER`, `EXTRA_TIME_PHASES` |
| `models/match_event.py` | `MatchEvent`, `EventType` |
| `models/player_match_state.py` | `PlayerMatchState` (energy, cards, rating) |
| `services/substitution_manager.py` | `FatigueService`, `SubstitutionService` |
| `services/card_service.py` | `CardService` |
| `services/match_momentum_service.py` | `MatchMomentumService` |
| `services/event_engine.py` | `EventEngine` |
| `services/penalty_engine.py` | `PenaltyEngine` |
| `services/game_script_service.py` | `GameScriptService` (narrative, timeline, top performers) |
| `services/match_state_service.py` | `MatchStateService` (init, manager reactions) |
| `services/manager_service.py` | `get_manager()`, `manager_game_plan_modifier()` |
| `services/tactical_analysis.py` | `compute_tactical_matchup()` |

---

## Usage

```python
from fifa_data import run_simulation

# Run full tournament with V5
result = run_simulation(model="v5")
print(result["champion"])

# Direct engine usage
from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
engine = V5MatchStateEngine(data_dir="fifa_data", team_metrics=TEAM_METRICS)

# Basic match
score = engine.simulate_match("Brazil", "Germany", can_draw=False)
print(score)  # (2, 1)

# Detailed match with events
score, state, events = engine.simulate_match_detailed(
    "Brazil", "Germany", can_draw=False, context="knockout"
)
print(f"Goals: {score}")
print(f"Events: {len(events)}")
for event in events:
    print(f"  {event.minute}' {event.event_type.value} — {event.player_name}")

# Debug output
score, debug = engine.simulate_match_debug("Brazil", "Germany", can_draw=False)
print(debug)
```

---

## Monte Carlo

```python
from fifa_data import run_monte_carlo

# Run 100 V5 simulations
results = run_monte_carlo(model="v5", n=100)

print("Champion probabilities:")
for team, count in results["champion"][:5]:
    print(f"  {team}: {count}%")

print(f"\nCompleted {results['total']} sims in {results['elapsed']}s")
print(f"Speed: {results['sims_per_sec']} sims/sec")
```

---

## Design Philosophy

V5 is the most **deterministic** at the team-strength level (ELO modifier is strongest here) but also has the most sources of **in-match variance**:

| Engine | Base Determinacy | Extra Variance Sources |
|--------|-----------------|----------------------|
| V1 | ELO/PELE difference only | Upset factor, Poisson noise |
| V2 | Player rating difference | + midfield modifier |
| V3 | Dynamic states × star ratings × ELO | + 6 dynamic services |
| V4 | V3 + tactical matchup | + 13 tactical factors |
| V5 | V4 + phase mechanics | + fatigue, live momentum, cards, subs, scoreline pressure, ET, penalties |

V5 produces the **richest emergent narratives** while keeping overall outcomes aligned with real-world team quality.
