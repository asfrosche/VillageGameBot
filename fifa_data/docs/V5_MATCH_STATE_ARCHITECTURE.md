# V5 Match State Engine — Architectural Deep Dive

## Overview

V5 is the most advanced match simulation engine in the pipeline. It moves beyond static expected-goals and tactical-layer adjustments by simulating matches **phase-by-phase** with continuous live state tracking — fatigue, momentum, cards, substitutions, and manager reactions all update every 15 minutes of simulated match time. The goal is emergent, realistic match narratives instead of a single Poisson draw.

---

## Inheritance Chain

```
MatchEngine (abstract base)
├── V1EloMatchEngine        — team ELO/PELE only, no squad data
├── V2PlayerMatchEngine     — player attribute ratings, roles, formations
├── V3DynamicEngine         — 6 dynamic states (chemistry, form, momentum, etc.)
│                              + star-weighted ratings + national modifiers + ELO
├── V4TacticalEngine        — wraps V3; game plans, manager profiles,
│                              tactical adjustments (12 factors), formation matchups
└── V5MatchStateEngine      — wraps V4; phase-by-phase simulation with fatigue,
                               live momentum, cards, subs, events, penalties
```

Each engine is standalone — V4 internally holds a `V3DynamicEngine` instance; V5 internally holds a `V4TacticalEngine` instance (and accesses `self._v4._v3` for the underlying V3 services). No engine extends another; they compose.

---

## V1 → V4: What Each Layer Contributes

### V1 — Team-Level ELO/PELE (`v1_elo_engine.py`)

- **Input**: `TEAM_METRICS` dict with `{team: {"ELO": float, "PELE": float}}`
- **Mechanic**: `_rating()` averages ELO + PELE; `upset_factor` based on rating difference scales the Poisson lambda
- **Limitation**: No squad data, no player attributes, no formations
- **xG formula**: `base_goals * upset_factor` for favorite, `base_goals * max(0.20, 1.5 - 0.5 * upset_factor)` for underdog
- **Extra time**: Poisson with scaled lambda; penalties by ELO differential

### V2 — Player Attributes & Roles (`v2_player_engine.py`)

- **Input**: Squad data with player attribute ratings, formation strings
- **Mechanic**: `assign_roles()` maps players to 7 canonical roles (GK, CB, FB, DM, CM, ST, WINGER); `build_team_strength()` computes line ratings via weighted position formulas
- **Key addition**: `TeamStrength` dataclass with `attack_rating`, `midfield_rating`, `defense_rating`, `goalkeeper_rating`
- **xG formula**: `attack_ratio = attack / (w_def * defense + w_gk * gk)` → `curve_value = ratio^2.5 [0.30, 3.0]` → `base_goals * curve_value * midfield_modifier`
- **Midfield control**: `1.0 + 0.25 * (star_m_a - star_m_d) / 100`

### V3 — Dynamic State & Star Weighting (`v3_dynamic_engine.py`)

- **Input**: Same as V2 + 6 dynamic service modifiers + national modifiers JSON + ELO/PELE
- **Star weighting**: Key positions contribute more to line ratings (e.g., ST weight 0.40 vs WINGER 0.15 in attack line)
- **Six dynamic states** (each produces a small percentage modifier, combined clamped to [0.90, 1.10]):

| Service | Source | Modifier Basis |
|---------|--------|----------------|
| ChemistryService | `club_links.json` | Same-club player count & known partnerships |
| ExperienceService | `player_experience.json` | Caps, WC experience, captains, knockout/ET/penalty exp |
| FormService | Player fantasy stats | Form and totalPoints from FIFA data |
| MomentumService | In-tournament results | Recent win rate, GD, clean sheets |
| ContinuityService | Lineup tracking | Consistency of starting XI across matches |
| LeadershipService | `player_experience.json` | Captains, veterans, WC veterans |

- **ELO/PELE modifier**: `1.0 + 0.003 * (avg - 1500)` clamped to [0.50, 3.0] (affects all 4 line ratings)
- **National modifier**: Country-specific buffs from JSON config
- **Combined**: `(1.0 + nat_mod) * dyn_mult * elo_mod` applied to all star ratings
- **Configurable curve**: `curve_factor` (default 3.0) instead of hardcoded 2.5
- **Penalties influenced by**: Leadership, experience, national modifiers

### V4 — Tactical Layer (`v4_tactical_engine.py`)

- **Input**: V3 strengths + squad data + manager profiles + context (group/knockout)
- **Wrapping**: `get_team_strength()` delegates to `self._v3.get_team_strength()` (ELO modifier already baked in)
- **`compute_tactical_matchup()`** produces a `TacticalReport` with `final_xg_a/b`:
  1. **Game plan selection**: `attacking`, `balanced`, `counter`, `low_block`, `high_press` chosen per team based on relative strength, context, and manager profile
  2. **Tactical adjustments** (up to ±10% of base xG): high line vs pace, pressing vs weak buildup, possession vs low block creativity, set-piece mismatches, aerial dominance, formation matchup, game plan effects, player tactic compatibility, possession quality, defensive style interactions, tactical flexibility, match context effects, defensive stalemate
- **Match context awareness**: `group`, `knockout`, `must_win`, `need_draw`, `gd_chase` modify game plans and adjustment weights
- **Manager profiles**: `risk_tolerance`, `tactical_flexibility`, `pressing_preference`, `defensive_discipline` affect game plan selection and sub behavior

---

## V5 — Phase-by-Phase Simulation

### Architecture Diagram

```
simulate_match(team1, team2, can_draw)
│
├─ 1. Initialize MatchState (MatchStateService)
│     └─ Creates PlayerMatchState per player (100% energy)
│
├─ 2. Compute Base Strengths (V3Delegate)
│     └─ get_team_strength() → TeamStrength (includes ELO modifier)
│     └─ expected_goals() → base_lambda_a, base_lambda_b
│
├─ 3. Compute Tactical Matchup (V4Delegate)
│     └─ compute_tactical_matchup() → TacticalReport (final_xg_a, final_xg_b)
│
├─ 4. Loop: 6 Regular Phases + 2 ET Phases
│     │
│     ├─ Apply Fatigue (FatigueService)
│     │   └─ Per-player energy loss based on stamina, age, work rate,
│     │      physical, pace, match intensity, pressing, extra time
│     │   └─ Substitutes get freshness_bonus()
│     │
│     ├─ Decay Momentum (MatchMomentumService)
│     │   └─ 8-point decay per phase
│     │
│     ├─ Compute Phase xG (_compute_phase_xg)
│     │   └─ phase_xg = base_lambda * (15/90)
│     │   └─ energy_mod = 0.85 + (energy_avg / 100) * 0.15
│     │   └─ momentum_mod = get_momentum_multiplier(momentum)
│     │   └─ score_mod = scoreline_xg_modifier()
│     │   └─ red_mod = 1.0 - 0.25 * red_cards
│     │   └─ Return max(0.01, phase_xg * all_modifiers)
│     │
│     ├─ Generate Events (EventEngine)
│     │   └─ Estimate attack count from xG, momentum, energy
│     │   └─ Distribute attacks across minutes in the phase
│     │   └─ Determine shots, big chances, goals per attack
│     │   └─ Goal probability uses finishing, composure, GK quality
│     │   └─ Trigger cards via CardService
│     │
│     ├─ Evaluate Subs (SubstitutionService)
│     │   └─ Check fatigue (<30% urgent), yellow cards (defenders),
│     │      match rating (<6.0), injury
│     │   └─ Find best replacement by role + scoreline urgency
│     │
│     └─ Evaluate Manager Reactions (MatchStateService)
│         └─ May change game plan based on scoreline + minute + profile
│
├─ 5. Extra Time (if knockout & tied)
│     └─ 2 phases with 0.7x lambda scaling, 1.3x fatigue multiplier
│
├─ 6. Penalty Shootout (PenaltyEngine)
│     └─ Select top 5 takers (penalties + finishing + composure)
│     └─ Per-shot: taker vs goalkeeper attributes
│     └─ Sudden death after 5 rounds
│
└─ 7. Record + Debug
      └─ Update V3 continuity & momentum services
      └─ Generate match story, timeline, top performers
```

### Key V5 Services

| Service | File | What It Does |
|---------|------|-------------|
| **FatigueService** | `substitution_manager.py` | Computes energy loss per phase per player. Factors: stamina, age, work rate, physical, pace, match intensity, pressing intensity, extra time. Substitutes get `freshness_bonus()`. |
| **CardService** | `card_service.py` | Per-event probability of foul, yellow, red. Inputs: aggression, composure, defending, energy level, current cards. |
| **MatchMomentumService** | `match_momentum_service.py` | Real-time momentum tracker. Events trigger: goal +25, concede -20, big chance +5, red card -30, etc. Decays 8/phase. Provides momentum_multiplier() (maps momentum to 0.85-1.15x), pressing_modifier(), shot_quality_modifier(). |
| **EventEngine** | `event_engine.py` | Generates phase events. Estimates attack count from xG, momentum, energy. Distributes over minutes. Determines shots/big chances/goals. Goal probability integrates finishing + composure vs GK reflexes + positioning. Triggers cards. |
| **PenaltyEngine** | `penalty_engine.py` | Full 5-round + sudden death. Selects takers by penalties+finishing+composure. Each attempt: taker attributes vs GK penalty_save+reflexes+positioning. |
| **SubstitutionService** | `substitution_manager.py` | Evaluates subs each phase. Fatigue <30% → urgent. Yellow-carded defenders → high priority. Match rating <6.0 → subbed. Finds best replacement by role compatibility + scoreline urgency. Manager profile influences. |
| **GameScriptService** | `game_script_service.py` | Post-match: match story narrative, event timeline (most exciting moments), top performer identification by weighted score. |
| **MatchStateService** | `match_state_service.py` | Initializes `MatchState` dataclass, advances phases, evaluates manager reactions (game plan changes based on scoreline/minute/manager profile), computes possession. |

### `MatchState` Dataclass (Core V5 Data Structure)

```
MatchState
├── team_a, team_b: str
├── scoreline: ScorelineState (goals, description)
├── player_states: dict[int, PlayerMatchState]  ← per-player energy, morale, cards
├── momentum: dict[str, int]                    ← per-team live momentum value
├── current_phase: MatchPhase
├── minute: int
├── game_plans: dict[str, str]
├── events: list[MatchEvent]
├── substitutions: list[SubstitutionEvent]
├── phase_stats: dict[MatchPhase, PhaseStats]
├── red_card_count: dict[str, int]
├── is_extra_time, is_penalties: bool
└── possession: dict[str, float]
```

### `PlayerMatchState` (Per-Player Live State)

```
PlayerMatchState
├── energy: float (100 → 0)
├── morale: float (affects performance 0.88-1.08x)
├── match_rating: float (1-10 scale)
├── cards: int
├── minutes_played: int
├── goals, assists, fouls, shots, tackles, interceptions
├── pressing_intensity: float
├── apply_energy_effects() degrades attributes at energy thresholds
└── morale_multiplier() returns 0.88-1.08x
```

### Phase-by-Phase xG Modulation

Each 15-minute phase, base xG (`base_lambda * 15/90`) is modified by:

| Modifier | Range | Source |
|----------|-------|--------|
| Energy | 0.85–1.00 | Team average energy level |
| Momentum | 0.85–1.15 | Live momentum value mapped through multiplier |
| Scoreline (winning) | 0.77–0.99 | Attack less, defend more (amplified after 75') |
| Scoreline (trailing) | 1.08–1.30 | Attack more, take risks (amplified after 75') |
| Red cards | 0.25 per card | Each red card reduces xG by 25% |

### Event Engine Flow

```
generate_phase_events(phase_xg, momentum, energy, ...)
│
├─ expected_attacks = phase_xg * k (estimated attacks from xG)
├─ actual_attacks ~ Poisson(expected_attacks)
├─ For each attack:
│   ├─ is_big_chance? → probability from momentum modifier
│   ├─ is_shot? → yes for most attacks
│   ├─ goal_probability → finishing + composure vs GK quality + stalemate
│   ├─ If goal: momentum bonus +25, concede -20
│   ├─ Triggers: CardService.check_foul() → check_yellow() → check_red()
│   └─ Record: EventType, player, minute, xg, detail
│
└─ Return phase_diff (goals scored, momentum changes, card events)
```

---

## ELO/PELE Integration (All Engines V3-V5)

All three advanced engines share the same ELO modifier path:

1. `update_elo_from_matches()` reads `matches.json` and updates `TEAM_METRICS` dict in-place
2. `TEAM_METRICS` is passed to the engine constructor as `team_metrics`
3. `V3DynamicEngine.get_team_strength()` computes:
   ```
   elo_avg = (TEAM_METRICS[team]["ELO"] + TEAM_METRICS[team]["PELE"]) / 2
   elo_mod = 1.0 + 0.003 * (elo_avg - 1500)        # clamped [0.50, 3.0]
   combined_mult = (1.0 + nat_mod) * dyn_mult * elo_mod
   attack_rating = star_a * combined_mult            # same for midfield, defense, GK
   ```
4. V4 and V5 delegate `get_team_strength()` to V3 — same modifier

This means the ELO/PELE modifier is **identical across V3, V4, V5**. The difference in outcomes comes from V4's tactical adjustments (±10% xG) and V5's phase-based mechanics (fatigue, momentum, cards, subs, scoreline pressure).

---

## Summary: Determinacy vs Variance

| Engine | Base Determinacy | Extra Variance Sources |
|--------|-----------------|----------------------|
| V1 | ELO/PELE difference only | Upset factor curve, Poisson noise |
| V2 | Player rating difference | Same + midfield modifier |
| V3 | Dynamic states × star ratings × ELO | 6 dynamic services, Poisson noise |
| V4 | V3 + tactical matchup | Game plan × 12 tactical factors |
| V5 | V4 + phase mechanics | Fatigue, live momentum, cards, subs, events scoreline pressure, ET, penalties |

V5 is the most deterministic at the team-strength level (ELO modifier is strongest here) but also has the most sources of in-match variance, producing the richest emergent narratives while keeping overall outcomes aligned with real-world team quality.
