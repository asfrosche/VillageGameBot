# V6 Architecture: Evaluation & Diagnostics Engine

## Overview

V6 is **not a simulation engine** — it is a non-invasive evaluation and diagnostics layer that sits on top of V5. It runs V5 simulations against real match data, then computes calibration metrics, upset classification, statistical tests, and visualizations. V6 does not modify any V5 parameters or game logic.

```
Real Match Data → V5 Simulations → Poisson H/D/A → Market Comparison → Statistical Tests → Report
```

---

## Inheritance Chain

```
MatchEngine (abstract base)
├── V1EloMatchEngine        — team ELO/PELE only
├── V2PlayerMatchEngine     — player attributes, roles, formations
├── V3DynamicEngine         — 6 dynamic states + ELO + national modifiers
├── V4TacticalEngine        — wraps V3; tactical adjustments (13 factors)
├── V5MatchStateEngine      — wraps V4; phase-by-phase with fatigue, cards, subs
└── V6EvaluationEngine      — wraps V5; evaluation pipeline, no match simulation
```

V6 inherits from `MatchEngine` but delegates `simulate_match()` to V5 internally. Its primary entry point is `run_evaluation()`, not `simulate_match()`.

---

## V6 Architecture Diagram

```
run_evaluation()
│
├─ Step 1: Load Real Match Data
│     └─ benchmark.data_loader.load_real_matches()
│     └─ benchmark.data_loader.load_groups()
│     └─ benchmark.data_loader.load_team_metrics()
│
├─ Step 2: Run V5 Simulations
│     └─ benchmark.simulation_runner.simulate_all_matches()
│     └─ Returns predicted xG, possession, PPDA per match
│
├─ Step 3: Compute V5 H/D/A from xG (Poisson Model)
│     └─ poisson_hda(xg_home, xg_away) → {home_win, draw, away_win}
│     └─ Independent Poisson distributions, max 9 goals
│     └─ Adds v5_home_prob, v5_draw_prob, v5_away_prob per match
│     └─ Determines v5_favorite and v5_favorite_prob
│
├─ Step 4: Compute Market Odds
│     └─ load_market_odds() → real sportsbook or synthetic ELO-based
│     └─ ELO-based: _elo_win_prob() + _elo_draw_prob()
│     └─ Returns normalized H/D/A probabilities per match
│
├─ Step 5: Classify Upsets
│     └─ classify_all_matches() → upset_category per match
│     └─ Categories: Correct, True Upset, Model Failure, Close Call, V5 Contrarian
│     └─ Favorite strength: Toss-up, Slight, Moderate, Heavy, Major
│
├─ Step 6: Compute Calibration Metrics
│     └─ benchmark.calibration.compute_calibration_metrics()
│     └─ Brier Score, Log Loss, Reliability, Calibration Curve
│
├─ Step 7: Statistical Tests
│     ├─ one_sample_t_test() — goals bias, xG errors
│     ├─ bootstrap_mean_ci() — confidence intervals
│     ├─ chi_square_calibration_test() — probability calibration
│     ├─ detect_systematic_biases() — home advantage, draw prediction, etc.
│     └─ Home advantage & draw analysis
│
└─ Step 8: Generate Visualizations & Report
      ├─ generate_all_graphs() → 10 PNG files
      └─ generate_v6_report() → 9-section Markdown report
```

---

## Poisson H/D/A Model

V6 converts V5's predicted xG into win/draw/away probabilities using independent Poisson distributions:

```python
def poisson_hda(xg_home, xg_away, max_goals=9):
    """P(H) = sum over i>j of P(H=i) * P(A=j)
       P(D) = sum over i==j of P(H=i) * P(A=j)
       P(A) = sum over i<j of P(H=i) * P(A=j)
    """
    for hi in range(max_goals + 1):
        ph = poisson_pmf(hi, xg_home)
        for ai in range(max_goals + 1):
            pa = poisson_pmf(ai, xg_away)
            joint = ph * pa
            if hi > ai: home_win += joint
            elif hi == ai: draw += joint
            else: away_win += joint
    # Normalize to sum to 1.0
    return {"home_win": home_win, "draw": draw, "away_win": away_win}
```

This gives proper three-way probabilities instead of relying on a single scoreline prediction.

---

## Upset Classification

Each match is classified by **favorite strength** (market probability) and **prediction outcome**:

### Favorite Strength Categories

| Category | Market Favorite Prob | Description |
|----------|---------------------|-------------|
| Toss-up | < 55% | Evenly matched |
| Slight favorite | 55-65% | Marginal edge |
| Moderate favorite | 65-75% | Clear but not dominant |
| Heavy favorite | 75-85% | Strong expected winner |
| Major favorite | > 85% | Near-certain winner |

### Upset Labels

| Label | Condition |
|-------|-----------|
| **Correct** | V5 predicted the right result |
| **True Upset** | Market favorite also lost (both saw underdog < 45%) |
| **Model Failure** | V5 and market agreed on favorite, but it lost |
| **Close Call** | Both V5 and market saw toss-up; error expected |
| **V5 Contrarian** | V5 picked a different winner than market, and V5 was wrong |

---

## Statistical Tests

| Test | What It Measures |
|------|-----------------|
| **One-sample t-test** | Does goals bias significantly differ from 0? Are xG errors systematic? |
| **Two-sample t-test** | Do two groups (e.g., home-favored vs away-favored) differ? |
| **Chi-square calibration** | Are predicted probabilities well-calibrated against actual outcomes? |
| **Bootstrap mean CI** | Confidence interval for mean goals bias |
| **Bias detection** | Systematic patterns: goals underestimation, home advantage miscalibration, low favorite accuracy, xG bias by strength category |

Bias detection only flags patterns where >5% of matches show the same bias, with statistical significance when possible.

---

## Visualizations

V6 generates 10 PNG graphs in `output/graphs/`:

| Graph | Description |
|-------|-------------|
| `xg_scatter.png` | Predicted xG vs actual goals (home/away panels) |
| `possession_distribution.png` | Histogram of predicted home possession % |
| `calibration_curve.png` | Predicted probability vs actual frequency |
| `error_distribution.png` | XG error and scoreline error histograms |
| `winner_probability_distribution.png` | Distribution of favorite win probabilities |
| `ppda_scatter.png` | Home vs away PPDA scatter |
| `market_comparison.png` | V5 vs market favorite probabilities (colored by outcome) |
| `goals_bias.png` | Predicted vs actual average goals bar chart |
| `stage_accuracy.png` | Winner accuracy by tournament stage |
| `upset_breakdown.png` | Bar chart of upset category distribution |

---

## Report Sections

The generated `v6_report.md` contains 9 sections:

1. **Executive Summary** — Key metrics, actual result distribution, key findings
2. **V5 vs Reality** — Prediction accuracy, scoreline distribution, sample matches
3. **V5 vs Market** — Agreement rate, biggest disagreements
4. **Upset Analysis** — Classification definitions, favorite strength breakdown, notable failures
5. **Home Advantage & Draw Analysis** — Actual vs predicted rates, t-tests
6. **Calibration** — Brier score, log loss, reliability, calibration curve table
7. **Stage Breakdown** — Accuracy by tournament stage
8. **Strengths** — Statistically supported positive findings
9. **Weaknesses & Recommendations** — Evidence-based improvement suggestions

---

## Output Files

| File | Format | Content |
|------|--------|---------|
| `v6_report.md` | Markdown | Full 9-section evaluation report |
| `v6_summary.json` | JSON | Machine-readable metrics, calibration, biases |
| `v6_matches.csv` | CSV | Per-match data with all metrics |
| `graphs/*.png` | PNG | 10 visualization graphs |

---

## Key Functions

| Function | File | Purpose |
|----------|------|---------|
| `run_v6()` | `v6_evaluation_engine.py` | Convenience entry point |
| `V6EvaluationEngine.run_evaluation()` | `v6_evaluation_engine.py` | Full 8-step pipeline |
| `poisson_hda()` | `v6_evaluation_engine.py` | xG → H/D/A probabilities |
| `compute_v5_hda()` | `v6_evaluation_engine.py` | Add Poisson H/D/A to match metrics |
| `classify_all_matches()` | `v6_evaluation_engine.py` | Upset classification |
| `detect_systematic_biases()` | `v6_evaluation_engine.py` | Bias detection |
| `generate_all_graphs()` | `v6_evaluation_engine.py` | Visualization generation |
| `generate_v6_report()` | `v6_evaluation_engine.py` | Markdown report generation |

---

## Files Reference

| File | Purpose |
|------|---------|
| `engines/v6_evaluation_engine.py` | V6 engine — all evaluation logic in one file |
| `engines/base_engine.py` | `MatchEngine` abstract base |
| `engines/v5_match_state_engine.py` | V5 engine (delegated to by V6) |
| `benchmark/data_loader.py` | Real match data loading |
| `benchmark/simulation_runner.py` | V5 simulation runner |
| `benchmark/metrics.py` | Match metrics and tournament summary |
| `benchmark/calibration.py` | Calibration metrics computation |

---

## Usage

```python
from fifa_data import run_simulation

# Run V6 evaluation (generates report + graphs)
result = run_simulation(model="v6")

# Direct evaluation
from fifa_data.engines.v6_evaluation_engine import run_v6
summary = run_v6()

# With custom odds file
from pathlib import Path
summary = run_v6(odds_file=Path("odds.json"), output_dir=Path("output/"))

# Direct engine usage
from fifa_data.engines.v6_evaluation_engine import V6EvaluationEngine
engine = V6EvaluationEngine(team_metrics=TEAM_METRICS)
result = engine.run_evaluation()
```

---

## Discord Bot Integration

```discord
.evaluate          — Run V6 evaluation pipeline
.eval              — Alias for .evaluate
.v6eval            — Alias for .evaluate
.simulate v6       — Run V5 simulation (V6 delegates to V5)
.montecarlo v6 100 — Monte Carlo with V6 engine
```

---

## Design Philosophy

V6 is **diagnostic, not generative**. It does not create new simulations — it analyzes existing V5 output against real-world data to answer:

- **How accurate are V5's predictions?** (calibration, Brier score)
- **Where does V5 fail?** (upset classification, bias detection)
- **How does V5 compare to market odds?** (ELO-based synthetic odds)
- **What should be improved?** (evidence-based recommendations)

This separation keeps V5's game logic clean while providing rigorous statistical evaluation of its outputs.
