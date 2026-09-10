"""V6 - Adaptive Simulation Engine.

Wraps V5 with live per-team xG corrections based on real match results.
V6 is a temporary adaptive layer for live tournament use — it learns from
real results and applies small corrections to improve predictions going forward.

V6 is NOT a permanent replacement for V5. It captures team-specific
over/underperformance that V5 cannot know ahead of time. Once the tournament
is done, insights from V6 should be folded back into V5's parameters.

Also contains evaluation/diagnostics utilities (reports, calibration,
upset classification, visualizations) accessible via `.evaluate` command.
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from .base_engine import MatchEngine

HERE = Path(__file__).resolve().parent
FIFA_DATA = HERE.parent

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


# ═════════════════════════════════════════════════════════════════════════════
# Poisson H/D/A from xG
# ═════════════════════════════════════════════════════════════════════════════

def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def poisson_hda(xg_home: float, xg_away: float, max_goals: int = 9) -> dict[str, float]:
    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    for hi in range(max_goals + 1):
        ph = _poisson_pmf(hi, xg_home)
        for ai in range(max_goals + 1):
            pa = _poisson_pmf(ai, xg_away)
            joint = ph * pa
            if hi > ai:
                home_win += joint
            elif hi == ai:
                draw += joint
            else:
                away_win += joint
    total = home_win + draw + away_win
    if total > 0:
        home_win /= total
        draw /= total
        away_win /= total
    return {
        "home_win": round(home_win, 4),
        "draw": round(draw, 4),
        "away_win": round(away_win, 4),
    }


def compute_v5_hda(match_metrics: list[dict]) -> list[dict]:
    for m in match_metrics:
        if "error" in m:
            m["v5_home_prob"] = 0.33
            m["v5_draw_prob"] = 0.33
            m["v5_away_prob"] = 0.33
            m["v5_favorite"] = "Draw"
            m["v5_favorite_prob"] = 0.33
            continue
        xg_h = m.get("predicted_xg_home", 1.0)
        xg_a = m.get("predicted_xg_away", 1.0)
        probs = poisson_hda(xg_h, xg_a)
        m["v5_home_prob"] = probs["home_win"]
        m["v5_draw_prob"] = probs["draw"]
        m["v5_away_prob"] = probs["away_win"]
        if probs["home_win"] >= probs["away_win"] and probs["home_win"] >= probs["draw"]:
            m["v5_favorite"] = m["home"]
            m["v5_favorite_prob"] = probs["home_win"]
        elif probs["away_win"] >= probs["home_win"] and probs["away_win"] >= probs["draw"]:
            m["v5_favorite"] = m["away"]
            m["v5_favorite_prob"] = probs["away_win"]
        else:
            m["v5_favorite"] = "Draw"
            m["v5_favorite_prob"] = probs["draw"]
    return match_metrics


# ═════════════════════════════════════════════════════════════════════════════
# ELO-based market odds
# ═════════════════════════════════════════════════════════════════════════════

def _elo_win_prob(elo_a: float, elo_b: float, home_advantage: float = 50.0) -> float:
    diff = elo_a + home_advantage - elo_b
    return 1.0 / (1.0 + math.pow(10, -diff / 400.0))


def _elo_draw_prob(elo_a: float, elo_b: float, home_advantage: float = 50.0) -> float:
    diff = abs(elo_a + home_advantage - elo_b)
    return 0.15 + 0.13 * math.exp(-diff / 200.0)


def compute_synthetic_odds(
    home: str,
    away: str,
    team_metrics: dict[str, dict[str, float]] | None = None,
    home_advantage: float = 50.0,
) -> dict[str, float]:
    from fifa_data.services.simulation_service import TEAM_METRICS
    metrics = team_metrics or TEAM_METRICS
    home_data = metrics.get(home, {})
    away_data = metrics.get(away, {})
    elo_home = home_data.get("ELO", 1500)
    elo_away = away_data.get("ELO", 1500)
    home_win = _elo_win_prob(elo_home, elo_away, home_advantage)
    draw = _elo_draw_prob(elo_home, elo_away, home_advantage)
    away_win = _elo_win_prob(elo_away, elo_home, 0.0)
    total = home_win + draw + away_win
    home_win /= total
    draw /= total
    away_win /= total
    if home_win > away_win:
        favorite = home
        favorite_prob = home_win
    elif away_win > home_win:
        favorite = away
        favorite_prob = away_win
    else:
        favorite = "Draw"
        favorite_prob = draw
    return {
        "home_win": round(home_win, 4),
        "draw": round(draw, 4),
        "away_win": round(away_win, 4),
        "favorite": favorite,
        "favorite_prob": round(favorite_prob, 4),
    }


def load_market_odds_from_file(path: Path) -> dict[str, dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    results = {}
    for match in data.get("matches", []):
        home = match["home"]
        away = match["away"]
        key = f"{home} vs {away}"
        hw = 1.0 / match["home_win"] if match.get("home_win") else 0.33
        dr = 1.0 / match["draw"] if match.get("draw") else 0.33
        aw = 1.0 / match["away_win"] if match.get("away_win") else 0.33
        total = hw + dr + aw
        hw /= total
        dr /= total
        aw /= total
        if hw > aw:
            fav = home
            fav_p = hw
        elif aw > hw:
            fav = away
            fav_p = aw
        else:
            fav = "Draw"
            fav_p = dr
        results[key] = {
            "home_win": round(hw, 4),
            "draw": round(dr, 4),
            "away_win": round(aw, 4),
            "favorite": fav,
            "favorite_prob": round(fav_p, 4),
            "source": match.get("source", "unknown"),
        }
    return results


def load_market_odds(
    matches: list[dict],
    odds_file: Path | None = None,
    team_metrics: dict[str, dict[str, float]] | None = None,
) -> dict[str, dict[str, Any]]:
    real_odds = {}
    if odds_file and odds_file.exists():
        try:
            real_odds = load_market_odds_from_file(odds_file)
        except (json.JSONDecodeError, KeyError):
            pass
    market = {}
    for m in matches:
        home = m["home_name"]
        away = m["away_name"]
        key = f"{home} vs {away}"
        if key in real_odds:
            market[key] = real_odds[key]
        else:
            market[key] = compute_synthetic_odds(home, away, team_metrics)
    return market


# ═════════════════════════════════════════════════════════════════════════════
# Upset Classification
# ═════════════════════════════════════════════════════════════════════════════

def classify_favorite_strength(favorite_prob: float) -> str:
    if favorite_prob >= 0.85:
        return "Major favorite"
    if favorite_prob >= 0.75:
        return "Heavy favorite"
    if favorite_prob >= 0.65:
        return "Moderate favorite"
    if favorite_prob >= 0.55:
        return "Slight favorite"
    return "Toss-up"


def classify_upset(
    v5_winner: str,
    actual_winner: str,
    market_favorite: str,
    market_favorite_prob: float,
    v5_favorite_prob: float,
) -> dict[str, Any]:
    strength = classify_favorite_strength(market_favorite_prob)
    correct = (v5_winner == actual_winner)
    v5_agrees = (v5_favorite_prob >= 0.50)
    if correct:
        return {
            "upset_category": "Correct",
            "upset_label": "V5 predicted correctly",
            "favorite_strength": strength,
            "v5_agrees_with_market": v5_agrees,
        }
    market_also_wrong = (market_favorite != actual_winner) and (market_favorite != "Draw")
    both_toss_up = (
        classify_favorite_strength(v5_favorite_prob) == "Toss-up"
        and strength == "Toss-up"
    )
    if both_toss_up:
        return {
            "upset_category": "Close Call",
            "upset_label": "Both V5 and market saw toss-up; error expected",
            "favorite_strength": strength,
            "v5_agrees_with_market": v5_agrees,
        }
    if market_also_wrong:
        return {
            "upset_category": "True Upset",
            "upset_label": f"Market favorite ({market_favorite}) also lost",
            "favorite_strength": strength,
            "v5_agrees_with_market": v5_agrees,
        }
    if v5_agrees and not market_also_wrong:
        return {
            "upset_category": "Model Failure",
            "upset_label": f"V5 and market both favored {v5_winner} but it lost",
            "favorite_strength": strength,
            "v5_agrees_with_market": v5_agrees,
        }
    return {
        "upset_category": "V5 Contrarian",
        "upset_label": f"V5 picked {v5_winner} against market favorite",
        "favorite_strength": strength,
        "v5_agrees_with_market": v5_agrees,
    }


def classify_all_matches(
    match_metrics: list[dict],
    market: dict[str, dict[str, Any]],
) -> list[dict]:
    for m in match_metrics:
        if "error" in m:
            m["upset_category"] = "Error"
            m["upset_label"] = "Simulation failed"
            m["favorite_strength"] = "Unknown"
            m["v5_agrees_with_market"] = False
            continue
        home = m["home"]
        away = m["away"]
        key = f"{home} vs {away}"
        mkt = market.get(key, {})
        market_fav = mkt.get("favorite", "Draw")
        market_fav_prob = mkt.get("favorite_prob", 0.50)
        result = classify_upset(
            v5_winner=m.get("v5_favorite", m.get("predicted_winner", "Draw")),
            actual_winner=m.get("actual_winner", "Draw"),
            market_favorite=market_fav,
            market_favorite_prob=market_fav_prob,
            v5_favorite_prob=m.get("v5_favorite_prob", 0.5),
        )
        m.update(result)
        m["market_favorite"] = market_fav
        m["market_favorite_prob"] = market_fav_prob
    return match_metrics


def summarize_upsets(match_metrics: list[dict]) -> dict[str, Any]:
    categories = {}
    for m in match_metrics:
        cat = m.get("upset_category", "Unknown")
        categories[cat] = categories.get(cat, 0) + 1
    total = len(match_metrics)
    by_strength = {}
    for m in match_metrics:
        s = m.get("favorite_strength", "Unknown")
        if s not in by_strength:
            by_strength[s] = {"total": 0, "correct": 0, "upsets": 0}
        by_strength[s]["total"] += 1
        if m.get("upset_category") == "Correct":
            by_strength[s]["correct"] += 1
        elif m.get("upset_category") in ("True Upset", "Model Failure", "Close Call", "V5 Contrarian"):
            by_strength[s]["upsets"] += 1
    return {
        "category_counts": categories,
        "total_matches": total,
        "by_favorite_strength": by_strength,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Statistical Tests
# ═════════════════════════════════════════════════════════════════════════════

def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / (len(values) - 1))


def _se(values: list[float]) -> float:
    s = _std(values)
    n = len(values)
    return s / math.sqrt(n) if n > 1 else 0.0


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _chi2_cdf(x: float, k: int) -> float:
    if x <= 0:
        return 0.0
    if k <= 0:
        return 0.0
    a = k / 2.0
    return _regularized_gamma_p(a, x / 2.0)


def _regularized_gamma_p(a: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x < a + 1:
        total = 1.0 / a
        term = 1.0 / a
        for n in range(1, 300):
            term *= x / (a + n)
            total += term
            if abs(term) < 1e-15:
                break
        return total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    else:
        return 1.0 - _regularized_gamma_q(a, x)


def _regularized_gamma_q(a: float, x: float) -> float:
    if x <= 0:
        return 1.0
    f = 1e-30
    C = f
    D = 0.0
    for i in range(1, 300):
        if i % 2 == 1:
            an = a + (i - 1) / 2.0
        else:
            an = i / 2.0
        D = an + x * D
        if abs(D) < 1e-30:
            D = 1e-30
        D = 1.0 / D
        C = an + x / C
        if abs(C) < 1e-30:
            C = 1e-30
        delta = C * D
        f *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return f * math.exp(-x + a * math.log(x) - math.lgamma(a))


def one_sample_t_test(values: list[float], hypothesized_mean: float = 0.0) -> dict[str, Any]:
    n = len(values)
    if n < 3:
        return {"t_stat": 0.0, "p_approx": 1.0, "significant": False, "n": n}
    m = _mean(values)
    se = _se(values)
    if se == 0:
        return {"t_stat": 0.0, "p_approx": 1.0, "significant": False, "n": n}
    t_stat = (m - hypothesized_mean) / se
    z = abs(t_stat)
    p_approx = 2.0 * (1.0 - _normal_cdf(z))
    return {
        "t_stat": round(t_stat, 4),
        "p_approx": round(p_approx, 4),
        "significant": p_approx < 0.05,
        "n": n,
        "mean": round(m, 4),
        "std": round(_std(values), 4),
    }


def two_sample_t_test(
    values_a: list[float], values_b: list[float], label_a: str = "A", label_b: str = "B"
) -> dict[str, Any]:
    n_a, n_b = len(values_a), len(values_b)
    if n_a < 3 or n_b < 3:
        return {"t_stat": 0.0, "p_approx": 1.0, "significant": False, "n_a": n_a, "n_b": n_b}
    m_a, m_b = _mean(values_a), _mean(values_b)
    v_a, v_b = _std(values_a) ** 2, _std(values_b) ** 2
    se_a, se_b = v_a / n_a, v_b / n_b
    se = math.sqrt(se_a + se_b)
    if se == 0:
        return {"t_stat": 0.0, "p_approx": 1.0, "significant": False, "n_a": n_a, "n_b": n_b}
    t_stat = (m_a - m_b) / se
    z = abs(t_stat)
    p_approx = 2.0 * (1.0 - _normal_cdf(z))
    return {
        "t_stat": round(t_stat, 4),
        "p_approx": round(p_approx, 4),
        "significant": p_approx < 0.05,
        "mean_a": round(m_a, 4),
        "mean_b": round(m_b, 4),
        "label_a": label_a,
        "label_b": label_b,
        "n_a": n_a,
        "n_b": n_b,
    }


def chi_square_calibration_test(
    predicted_probs: list[float], outcomes: list[int], n_bins: int = 5
) -> dict[str, Any]:
    if len(predicted_probs) != len(outcomes):
        return {"chi2": 0.0, "p_approx": 1.0, "significant": False}
    n = len(predicted_probs)
    if n < 10:
        return {"chi2": 0.0, "p_approx": 1.0, "significant": False, "n": n}
    bin_edges = [i / n_bins for i in range(n_bins + 1)]
    bins = [{} for _ in range(n_bins)]
    for prob, outcome in zip(predicted_probs, outcomes):
        for i in range(n_bins):
            if bin_edges[i] <= prob < bin_edges[i + 1] or (i == n_bins - 1 and prob == 1.0):
                if "predicted" not in bins[i]:
                    bins[i]["predicted"] = []
                    bins[i]["actual"] = []
                bins[i]["predicted"].append(prob)
                bins[i]["actual"].append(outcome)
                break
    chi2 = 0.0
    total_used = 0
    for b in bins:
        if "predicted" not in b or len(b["predicted"]) < 3:
            continue
        obs_predicted = sum(b["predicted"])
        obs_actual = sum(b["actual"])
        expected = obs_actual
        if expected > 0:
            chi2 += (obs_predicted - expected) ** 2 / expected
        if expected < len(b["actual"]):
            chi2 += ((len(b["actual"]) - obs_actual) - (len(b["predicted"]) - obs_predicted)) ** 2 / max(
                len(b["actual"]) - expected, 0.01
            )
        total_used += len(b["predicted"])
    df = max(total_used - n_bins, 1)
    p_approx = 1.0 - _chi2_cdf(chi2, df)
    return {
        "chi2": round(chi2, 4),
        "df": df,
        "p_approx": round(p_approx, 4),
        "significant": p_approx < 0.05,
        "n": total_used,
    }


def bootstrap_mean_ci(
    values: list[float], n_bootstrap: int = 1000, ci: float = 0.95, seed: int = 42
) -> dict[str, Any]:
    if len(values) < 3:
        return {"mean": _mean(values), "ci_low": _mean(values), "ci_high": _mean(values)}
    rng = random.Random(seed)
    means = []
    for _ in range(n_bootstrap):
        sample = [values[rng.randint(0, len(values) - 1)] for _ in range(len(values))]
        means.append(_mean(sample))
    means.sort()
    alpha = (1.0 - ci) / 2.0
    lo_idx = int(alpha * n_bootstrap)
    hi_idx = int((1.0 - alpha) * n_bootstrap) - 1
    return {
        "mean": round(_mean(values), 4),
        "ci_low": round(means[lo_idx], 4),
        "ci_high": round(means[hi_idx], 4),
        "ci_level": ci,
        "n_bootstrap": n_bootstrap,
    }


def detect_systematic_biases(match_metrics: list[dict], threshold_pct: float = 0.05) -> list[dict[str, Any]]:
    valid = [m for m in match_metrics if "error" not in m]
    n = len(valid)
    if n == 0:
        return []
    min_count = max(1, int(n * threshold_pct))
    biases = []

    under = [m for m in valid if m.get("predicted_total_goals", 0) < m.get("actual_total_goals", 0)]
    over = [m for m in valid if m.get("predicted_total_goals", 0) > m.get("actual_total_goals", 0)]
    if len(under) > min_count:
        t = one_sample_t_test(
            [m["predicted_total_goals"] - m["actual_total_goals"] for m in valid]
        )
        biases.append({
            "bias_name": "Goals Underestimation",
            "description": f"V5 predicted fewer goals than actual in {len(under)}/{n} matches",
            "affected_matches": len(under),
            "affected_pct": round(len(under) / n * 100, 1),
            "direction": "under",
            "evidence": t,
        })
    elif len(over) > min_count:
        biases.append({
            "bias_name": "Goals Overestimation",
            "description": f"V5 predicted more goals than actual in {len(over)}/{n} matches",
            "affected_matches": len(over),
            "affected_pct": round(len(over) / n * 100, 1),
            "direction": "over",
            "evidence": {},
        })

    home_favored = [m for m in valid if m.get("predicted_xg_home", 0) > m.get("predicted_xg_away", 0)]
    home_actual_wins = [m for m in valid if m.get("actual_winner") == m.get("home")]
    if len(home_favored) > min_count:
        fav_pct = len(home_favored) / n * 100
        actual_home_pct = len(home_actual_wins) / n * 100 if home_actual_wins else 0
        if abs(fav_pct - actual_home_pct) > 10:
            biases.append({
                "bias_name": "Home Advantage Calibration",
                "description": (
                    f"V5 favors home in {fav_pct:.0f}% of matches "
                    f"vs {actual_home_pct:.0f}% actual home win rate"
                ),
                "affected_matches": len(home_favored),
                "affected_pct": round(fav_pct, 1),
                "direction": "home" if fav_pct > actual_home_pct else "away",
                "evidence": {},
            })

    fav_correct = [m for m in valid if m.get("v5_winner_correct")]
    if len(fav_correct) > min_count:
        accuracy = len(fav_correct) / n
        if accuracy < 0.48:
            biases.append({
                "bias_name": "Low Favorite Accuracy",
                "description": f"V5 picks the correct winner only {accuracy:.1%} of the time",
                "affected_matches": len(fav_correct),
                "affected_pct": round(accuracy * 100, 1),
                "direction": "random",
                "evidence": {"accuracy": accuracy},
            })

    for strength in ["Toss-up", "Slight favorite", "Moderate favorite", "Heavy favorite", "Major favorite"]:
        subset = [m for m in valid if m.get("favorite_strength") == strength]
        if len(subset) >= 5:
            errors = [m.get("predicted_xg_home", 0) - m.get("actual_home_goals", 0) for m in subset]
            t = one_sample_t_test(errors)
            if t["significant"]:
                biases.append({
                    "bias_name": f"xG Bias ({strength})",
                    "description": f"V5 xG home predictions significantly off for {strength} matches",
                    "affected_matches": len(subset),
                    "affected_pct": round(len(subset) / n * 100, 1),
                    "direction": "over" if t["mean"] > 0 else "under",
                    "evidence": t,
                })

    return biases


# ═════════════════════════════════════════════════════════════════════════════
# Visualizations
# ═════════════════════════════════════════════════════════════════════════════

def generate_all_graphs(
    match_metrics: list[dict],
    calibration: dict,
    tournament_summary: dict,
    output_dir: Path,
) -> list[str]:
    if not HAS_MPL:
        return []
    graphs_dir = output_dir / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    valid = [m for m in match_metrics if "error" not in m]
    if not valid:
        return []

    for fn in [
        _plot_xg_scatter,
        _plot_possession_distribution,
        _plot_error_distribution,
        _plot_winner_probability_distribution,
        _plot_ppda_scatter,
        _plot_market_comparison,
    ]:
        try:
            path = fn(valid, graphs_dir)
            if path:
                generated.append(path)
        except Exception:
            pass
    try:
        path = _plot_calibration_curve(calibration, graphs_dir)
        if path:
            generated.append(path)
    except Exception:
        pass
    for fn in [_plot_goals_bias, _plot_stage_accuracy]:
        try:
            path = fn(tournament_summary, graphs_dir)
            if path:
                generated.append(path)
        except Exception:
            pass
    try:
        path = _plot_upset_breakdown(valid, graphs_dir)
        if path:
            generated.append(path)
    except Exception:
        pass
    return generated


def _plot_xg_scatter(valid: list[dict], out: Path) -> str | None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    pred_h = [m["predicted_xg_home"] for m in valid]
    act_h = [m["actual_home_goals"] for m in valid]
    pred_a = [m["predicted_xg_away"] for m in valid]
    act_a = [m["actual_away_goals"] for m in valid]
    for ax, actual, pred, color, edge, title in [
        (axes[0], act_h, pred_h, "#2196F3", "#1565C0", "Home Team"),
        (axes[1], act_a, pred_a, "#FF9800", "#E65100", "Away Team"),
    ]:
        ax.scatter(actual, pred, alpha=0.5, s=30, c=color, edgecolors=edge, linewidth=0.5)
        mx = max(max(actual), max(pred), 1) + 0.5
        ax.plot([0, mx], [0, mx], "r--", alpha=0.7, label="Perfect")
        ax.set_xlabel("Actual Goals", fontsize=11)
        ax.set_ylabel("Predicted xG", fontsize=11)
        ax.set_title(f"{title}: Predicted xG vs Actual Goals", fontsize=12, fontweight="bold")
        ax.legend()
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    p = str(out / "xg_scatter.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_possession_distribution(valid: list[dict], out: Path) -> str | None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist([m["predicted_possession_home"] for m in valid], bins=20,
            color="#4CAF50", alpha=0.7, edgecolor="#2E7D32", linewidth=0.8)
    ax.axvline(x=50, color="red", linestyle="--", alpha=0.7, label="50% line")
    ax.set_xlabel("Predicted Home Possession %", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("Distribution of Predicted Home Possession", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    p = str(out / "possession_distribution.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_calibration_curve(calibration: dict, out: Path) -> str | None:
    curve = calibration.get("calibration_curve", [])
    if not curve:
        return None
    fig, ax = plt.subplots(figsize=(8, 8))
    pred_vals = [c["avg_predicted"] for c in curve]
    actual_vals = [c["avg_actual"] for c in curve]
    counts = [c["count"] for c in curve]
    ax.plot([0, 1], [0, 1], "r--", alpha=0.7, label="Perfect calibration")
    ax.scatter(pred_vals, actual_vals, s=[c * 5 for c in counts],
               alpha=0.7, c="#9C27B0", edgecolors="#6A1B9A", linewidth=0.5)
    for i, (p, a) in enumerate(zip(pred_vals, actual_vals)):
        ax.annotate(f"n={counts[i]}", (p, a), textcoords="offset points",
                    xytext=(5, 5), fontsize=8, alpha=0.7)
    ax.set_xlabel("Predicted Probability", fontsize=11)
    ax.set_ylabel("Actual Frequency", fontsize=11)
    ax.set_title("Calibration Curve", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    plt.tight_layout()
    p = str(out / "calibration_curve.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_error_distribution(valid: list[dict], out: Path) -> str | None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    xg_err = [m["total_xg_error"] for m in valid]
    ax = axes[0]
    ax.hist(xg_err, bins=20, color="#F44336", alpha=0.7, edgecolor="#C62828", linewidth=0.8)
    mean_err = sum(xg_err) / len(xg_err)
    ax.axvline(x=mean_err, color="blue", linestyle="--", alpha=0.7, label=f"Mean: {mean_err:.3f}")
    ax.set_xlabel("XG Error (|pred - actual|)", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("XG Prediction Error Distribution", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)
    sc_err = [m["scoreline_error"] for m in valid]
    ax = axes[1]
    ax.hist(sc_err, bins=range(0, max(sc_err) + 2),
            color="#2196F3", alpha=0.7, edgecolor="#1565C0", linewidth=0.8)
    mean_sc = sum(sc_err) / len(sc_err)
    ax.axvline(x=mean_sc, color="red", linestyle="--", alpha=0.7, label=f"Mean: {mean_sc:.2f}")
    ax.set_xlabel("Scoreline Error (|pred - actual| per team)", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("Scoreline Prediction Error Distribution", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    p = str(out / "error_distribution.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_winner_probability_distribution(valid: list[dict], out: Path) -> str | None:
    fig, ax = plt.subplots(figsize=(10, 5))
    fav_probs = [m.get("v5_favorite_prob", 0.5) for m in valid]
    ax.hist(fav_probs, bins=20, color="#FF9800", alpha=0.7, edgecolor="#E65100", linewidth=0.8)
    ax.axvline(x=0.5, color="red", linestyle="--", alpha=0.7, label="50% (toss-up)")
    ax.set_xlabel("Favorite Win Probability", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("Distribution of Predicted Favorite Win Probability", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    p = str(out / "winner_probability_distribution.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_ppda_scatter(valid: list[dict], out: Path) -> str | None:
    fig, ax = plt.subplots(figsize=(10, 6))
    ppda_h = [m["predicted_ppda_home"] for m in valid]
    ppda_a = [m["predicted_ppda_away"] for m in valid]
    ax.scatter(ppda_h, ppda_a, alpha=0.5, s=30, c="#00BCD4", edgecolors="#006064", linewidth=0.5)
    ax.set_xlabel("Home PPDA (predicted)", fontsize=11)
    ax.set_ylabel("Away PPDA (predicted)", fontsize=11)
    ax.set_title("Predicted PPDA: Home vs Away", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    avg_h = sum(ppda_h) / len(ppda_h)
    avg_a = sum(ppda_a) / len(ppda_a)
    ax.axhline(y=avg_a, color="red", linestyle="--", alpha=0.5, label=f"Avg away: {avg_a:.1f}")
    ax.axvline(x=avg_h, color="blue", linestyle="--", alpha=0.5, label=f"Avg home: {avg_h:.1f}")
    ax.legend()
    plt.tight_layout()
    p = str(out / "ppda_scatter.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_goals_bias(tournament_summary: dict, out: Path) -> str | None:
    fig, ax = plt.subplots(figsize=(8, 5))
    avg_pred = tournament_summary.get("avg_predicted_total_goals", 0)
    avg_actual = tournament_summary.get("avg_actual_total_goals", 0)
    bias = tournament_summary.get("goals_bias", 0)
    bars = ax.bar(["Predicted", "Actual"], [avg_pred, avg_actual],
                  color=["#2196F3", "#4CAF50"], edgecolor=["#1565C0", "#2E7D32"],
                  linewidth=1.2, width=0.5)
    for bar, val in zip(bars, [avg_pred, avg_actual]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                f"{val:.2f}", ha="center", va="bottom", fontweight="bold", fontsize=11)
    ax.set_ylabel("Average Goals Per Match", fontsize=11)
    ax.set_title(f"Goals Bias: {bias:+.2f} ({'over' if bias > 0 else 'under'}estimated)",
                 fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    p = str(out / "goals_bias.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_stage_accuracy(tournament_summary: dict, out: Path) -> str | None:
    by_stage = tournament_summary.get("by_stage", {})
    if not by_stage:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    stage_order = {"Group Stage": 0, "Round of 32": 1, "Round of 16": 2,
                   "Quarterfinals": 3, "Semifinals": 4, "Third Place": 5, "Final": 6}
    stages = sorted(by_stage.keys(), key=lambda x: stage_order.get(x, 7))
    accuracies = [by_stage[s]["accuracy"] for s in stages]
    counts = [by_stage[s]["total"] for s in stages]
    colors = ["#4CAF50" if a > 0.5 else "#FF9800" if a > 0.3 else "#F44336" for a in accuracies]
    bars = ax.bar(stages, accuracies, color=colors, edgecolor="#333", linewidth=0.8)
    for bar, acc, cnt in zip(bars, accuracies, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{acc:.1%}\n(n={cnt})", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Winner Prediction Accuracy", fontsize=11)
    ax.set_title("Winner Prediction Accuracy by Tournament Stage", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 1.1)
    ax.axhline(y=0.5, color="red", linestyle="--", alpha=0.5, label="50% baseline")
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    p = str(out / "stage_accuracy.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_market_comparison(valid: list[dict], out: Path) -> str | None:
    fig, ax = plt.subplots(figsize=(10, 8))
    v5_probs = []
    mkt_probs = []
    colors = []
    labels = []
    for m in valid:
        v5_p = m.get("v5_favorite_prob", 0.5)
        mkt_p = m.get("market_favorite_prob", 0.5)
        v5_probs.append(v5_p)
        mkt_probs.append(mkt_p)
        correct = m.get("winner_correct", False)
        cat = m.get("upset_category", "Correct")
        if correct:
            colors.append("#4CAF50")
        elif cat == "True Upset":
            colors.append("#F44336")
        elif cat == "Model Failure":
            colors.append("#FF9800")
        else:
            colors.append("#9C27B0")
        labels.append(cat)
    if not v5_probs:
        return None
    color_map = {
        "Correct": "#4CAF50",
        "True Upset": "#F44336",
        "Model Failure": "#FF9800",
        "Close Call": "#9C27B0",
        "V5 Contrarian": "#2196F3",
    }
    for cat, color in color_map.items():
        idxs = [i for i, l in enumerate(labels) if l == cat]
        if idxs:
            ax.scatter([mkt_probs[i] for i in idxs], [v5_probs[i] for i in idxs],
                       c=color, label=cat, alpha=0.7, s=50, edgecolors="#333", linewidth=0.5)
    ax.plot([0, 1], [0, 1], "k--", alpha=0.4, label="Perfect agreement")
    ax.set_xlabel("Market Favorite Probability (ELO-based)", fontsize=11)
    ax.set_ylabel("V5 Favorite Probability (xG-derived)", fontsize=11)
    ax.set_title("V5 vs Market: Favorite Strength Comparison", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0.45, 1.02)
    ax.set_ylim(0.45, 1.02)
    plt.tight_layout()
    p = str(out / "market_comparison.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _plot_upset_breakdown(valid: list[dict], out: Path) -> str | None:
    cats = Counter(m.get("upset_category", "Unknown") for m in valid)
    order = ["Correct", "True Upset", "Model Failure", "Close Call", "V5 Contrarian", "Minor Surprise", "Unknown"]
    color_map = {
        "Correct": "#4CAF50",
        "True Upset": "#F44336",
        "Model Failure": "#FF9800",
        "Close Call": "#9C27B0",
        "V5 Contrarian": "#2196F3",
        "Minor Surprise": "#607D8B",
        "Unknown": "#999999",
    }
    labels = [c for c in order if c in cats]
    values = [cats[c] for c in labels]
    colors = [color_map.get(c, "#999999") for c in labels]
    if not labels:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(labels, values, color=colors, edgecolor="#333", linewidth=0.8)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                str(val), ha="center", va="bottom", fontweight="bold", fontsize=11)
    ax.set_ylabel("Number of Matches", fontsize=11)
    ax.set_title("V5 Prediction Outcome Classification", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")
    plt.xticks(rotation=15, ha="right")
    plt.tight_layout()
    p = str(out / "upset_breakdown.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


# ═════════════════════════════════════════════════════════════════════════════
# Report Generator
# ═════════════════════════════════════════════════════════════════════════════

def generate_v6_report(
    match_metrics: list[dict],
    tournament_summary: dict,
    calibration: dict,
    market: dict[str, dict],
    upset_summary: dict,
    statistical_tests: dict[str, Any],
    biases: list[dict],
    analysis: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> str:
    lines: list[str] = []
    w = lines.append

    valid = [m for m in match_metrics if "error" not in m]
    n = len(valid)
    analysis = analysis or {}
    ha = analysis.get("home_advantage", {})
    da = analysis.get("draw_analysis", {})

    w("# V6 Evaluation & Diagnostics Report")
    w("")
    w(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    w(f"**Matches Evaluated:** {n}")
    w(f"**Method:** V5 xG -> Poisson H/D/A probabilities")
    w("")
    w("---")
    w("")

    w("## 1. Executive Summary")
    w("")
    acc = calibration.get("avg_confidence", 0)
    brier = calibration.get("brier_score", 0)
    log_loss = calibration.get("log_loss", 0)
    reliability = calibration.get("reliability", 0)
    bias = tournament_summary.get("goals_bias", 0)
    v5_correct = sum(1 for m in valid if m.get("v5_winner_correct"))
    v5_acc = v5_correct / n if n else 0
    actual_hw = ha.get("actual_home_win_pct", 0)
    actual_aw = ha.get("actual_away_win_pct", 0)
    actual_d = ha.get("actual_draw_pct", 0)

    w("### Key Metrics")
    w("")
    w("| Metric | Value | Interpretation |")
    w("|--------|-------|----------------|")
    w(f"| **V5 Winner Accuracy (Poisson)** | **{v5_acc:.1%}** "
      f"| {'Above' if v5_acc > 0.50 else 'Below'} 50% baseline |")
    w(f"| Brier Score | {brier:.4f} | Lower is better (0 = perfect) |")
    w(f"| Log Loss | {log_loss:.4f} | Lower is better |")
    w(f"| Reliability | {reliability:.4f} | Lower is better (0 = perfect) |")
    w(f"| Goals Bias | {bias:+.2f} | V5 {'under' if bias < 0 else 'over'}estimates goals |")
    w(f"| Avg XG Error | {tournament_summary.get('avg_total_xg_error', 0):.3f} | |")
    w(f"| Avg Scoreline Error | {tournament_summary.get('avg_scoreline_error', 0):.2f} | |")
    w("")

    w("### Actual Result Distribution")
    w("")
    w("| Outcome | Percentage | Count |")
    w("|---------|-----------|-------|")
    w(f"| Home Win | {actual_hw:.1f}% | {ha.get('actual_home_win_count', 0)} |")
    w(f"| Draw | {actual_d:.1f}% | {da.get('actual_draws', 0)} |")
    w(f"| Away Win | {actual_aw:.1f}% | {ha.get('actual_away_win_count', 0)} |")
    w("")

    w("### Key Findings")
    w("")
    if abs(bias) > 0.3:
        w(f"1. **Goal Prediction:** V5 {'under' if bias < 0 else 'over'}estimates "
          f"goals by {abs(bias):.2f} per match.")
    if reliability > 0.15:
        w(f"2. **Calibration:** Model is poorly calibrated (reliability={reliability:.3f}). "
          "Predicted probabilities don't match actual frequencies.")
    if v5_acc < 0.52:
        w(f"3. **Winner Accuracy:** {v5_acc:.1%} is {'at' if v5_acc >= 0.50 else 'below'} "
          "the 50% random baseline.")
    draw_acc = da.get("draw_accuracy", 0)
    if draw_acc < 30:
        w(f"4. **Draw Prediction:** V5 correctly identifies only {draw_acc:.0f}% "
          f"of actual draws ({da.get('draw_predictions_correct', 0)}/{da.get('actual_draws', 0)}).")
    mkt_agree = analysis.get("market_v5_agreement", 0)
    if n > 0:
        w(f"5. **Market Agreement:** V5 agrees with ELO market in {mkt_agree}/{n} "
          f"matches ({mkt_agree/n:.1%}).")
    w("")

    w("## 2. V5 vs Reality")
    w("")
    w("### Prediction Accuracy Summary")
    w("")
    w("| Metric | V5 Predicted | Actual | Difference |")
    w("|--------|-------------|--------|------------|")
    w(f"| Avg Goals/Match | {tournament_summary.get('avg_predicted_total_goals', 0):.2f} "
      f"| {tournament_summary.get('avg_actual_total_goals', 0):.2f} "
      f"| {bias:+.2f} |")
    w(f"| Avg Home xG | {tournament_summary.get('avg_xg_home_error', 0):.3f} (error) | - | - |")
    w(f"| Avg Away xG | {tournament_summary.get('avg_xg_away_error', 0):.3f} (error) | - | - |")
    w(f"| Home Possession | {tournament_summary.get('avg_predicted_possession_home', 50):.1f}% "
      f"| ~50% (neutral) | - |")
    w(f"| Home PPDA | {tournament_summary.get('avg_predicted_ppda_home', 0):.1f} | - | - |")
    w(f"| Away PPDA | {tournament_summary.get('avg_predicted_ppda_away', 0):.1f} | - | - |")
    w("")

    w("### Scoreline Distribution")
    w("")
    pred_dist = tournament_summary.get("pred_goals_distribution", {})
    act_dist = tournament_summary.get("actual_goals_distribution", {})
    w("**Most Predicted Scorelines:**")
    for sc, cnt in sorted(pred_dist.items(), key=lambda x: -x[1])[:5]:
        w(f"- {sc}: {cnt} times")
    w("")
    w("**Most Actual Scorelines:**")
    for sc, cnt in sorted(act_dist.items(), key=lambda x: -x[1])[:5]:
        w(f"- {sc}: {cnt} times")
    w("")

    w("### Sample Matches (V5 Poisson H/D/A vs Actual)")
    w("")
    w("| Match | V5 H/D/A | Predicted Fav | Actual | Correct |")
    w("|-------|----------|---------------|--------|---------|")
    for m in valid[:15]:
        h = m["home"]
        a = m["away"]
        v5h = m.get("v5_home_prob", 0)
        v5d = m.get("v5_draw_prob", 0)
        v5a = m.get("v5_away_prob", 0)
        vfav = m.get("v5_favorite", "?")
        actual = m.get("actual_winner", "Draw")
        ok = "Yes" if m.get("v5_winner_correct") else "No"
        w(f"| {h} vs {a} | {v5h:.0%}/{v5d:.0%}/{v5a:.0%} | {vfav} | {actual} | {ok} |")
    w("")

    w("## 3. V5 vs Market")
    w("")
    w("Market probabilities are synthetic (ELO-based). No real sportsbook odds provided.")
    w("")
    w(f"- **V5 agrees with market favorite:** {mkt_agree}/{n} ({mkt_agree/n:.1%})")
    avg_diff = analysis.get("market_v5_avg_diff", 0)
    w(f"- **Mean |V5 - Market| probability difference:** {avg_diff:.3f}")
    w("")
    w("### Where V5 and Market Disagree Most")
    w("")
    disagreements = sorted(valid,
                           key=lambda m: abs(m.get("v5_favorite_prob", 0.5) - m.get("market_favorite_prob", 0.5)),
                           reverse=True)
    w("| Match | V5 Fav | V5 Prob | Market Fav | Market Prob | Delta | Actual |")
    w("|-------|--------|---------|-----------|------------|-------|--------|")
    for m in disagreements[:10]:
        delta = abs(m.get("v5_favorite_prob", 0.5) - m.get("market_favorite_prob", 0.5))
        w(f"| {m['home']} vs {m['away']} "
          f"| {m.get('v5_favorite', '?')} | {m.get('v5_favorite_prob', 0):.3f} "
          f"| {m.get('market_favorite', '?')} | {m.get('market_favorite_prob', 0):.3f} "
          f"| {delta:.3f} | {m.get('actual_winner', '?')} |")
    w("")

    w("## 4. Upset Analysis")
    w("")
    w("### Classification Definitions")
    w("")
    w("| Category | Definition |")
    w("|----------|-----------|")
    w("| **Correct** | V5 predicted the right result |")
    w("| **True Upset** | Market favorite also lost; both models expected the winner to lose |")
    w("| **Model Failure** | V5 and market agreed on favorite, but it lost |")
    w("| **Close Call** | Both V5 and market saw toss-up; error is expected |")
    w("| **V5 Contrarian** | V5 picked a different winner than market, and V5 was wrong |")
    w("")
    w("### Favorite Strength Breakdown")
    w("")
    cat_counts = upset_summary.get("category_counts", {})
    by_str = upset_summary.get("by_favorite_strength", {})
    w("| Strength | Total | Correct | Upsets | Accuracy |")
    w("|----------|-------|---------|--------|----------|")
    for s in ["Toss-up", "Slight favorite", "Moderate favorite", "Heavy favorite", "Major favorite"]:
        d = by_str.get(s, {})
        t = d.get("total", 0)
        c = d.get("correct", 0)
        u = d.get("upsets", 0)
        acc_s = f"{c/t:.1%}" if t > 0 else "N/A"
        w(f"| {s} | {t} | {c} | {u} | {acc_s} |")
    w("")
    w("### Results Summary")
    w("")
    for cat in ["Correct", "True Upset", "Model Failure", "Close Call", "V5 Contrarian"]:
        cnt = cat_counts.get(cat, 0)
        w(f"- **{cat}:** {cnt} ({cnt/n:.1%})" if n else f"- **{cat}:** {cnt}")
    w("")
    w("### Notable Model Failures")
    w("")
    failures = [m for m in valid if m.get("upset_category") == "Model Failure"]
    if failures:
        w("| Match | V5 Pick | Market Pick | Actual | Strength |")
        w("|-------|---------|------------|--------|----------|")
        for m in failures[:15]:
            w(f"| {m['home']} vs {m['away']} | {m.get('v5_favorite', '?')} "
              f"| {m.get('market_favorite', '?')} | {m.get('actual_winner', '?')} "
              f"| {m.get('favorite_strength', '?')} |")
    else:
        w("No Model Failures detected.")
    w("")

    w("## 5. Home Advantage & Draw Analysis")
    w("")
    w("### Home Advantage")
    w("")
    w(f"- **Actual home win rate:** {actual_hw:.1f}%")
    w(f"- **Actual away win rate:** {actual_aw:.1f}%")
    w(f"- **Actual draw rate:** {actual_d:.1f}%")
    w(f"- **V5 avg home advantage (home_prob - away_prob):** "
      f"{ha.get('v5_avg_home_advantage', 0):+.3f}")
    w(f"- **V5 favors home in:** {ha.get('v5_favors_home_count', 0)}/{n} matches")
    w(f"- **V5 favors away in:** {ha.get('v5_favors_away_count', 0)}/{n} matches")
    home_ttest = statistical_tests.get("home_advantage_ttest", {})
    if home_ttest:
        sig = "SIGNIFICANT" if home_ttest.get("significant") else "not significant"
        w(f"- **Home advantage calibration t-test:** t={home_ttest.get('t_stat', 0):.3f}, "
          f"p={home_ttest.get('p_approx', 1):.4f} ({sig})")
    w("")
    w("### Draw Prediction")
    w("")
    w(f"- **Actual draws:** {da.get('actual_draws', 0)} ({da.get('actual_draw_pct', 0):.1f}%)")
    w(f"- **V5 avg draw probability:** {da.get('avg_v5_draw_prob', 0):.3f}")
    w(f"- **V5 draws predicted as favorite:** {da.get('v5_predicted_draw_favorite', 0)}")
    w(f"- **Draw predictions correct:** {da.get('draw_predictions_correct', 0)}/"
      f"{da.get('actual_draws', 0)} ({da.get('draw_accuracy', 0):.0f}%)")
    draw_ttest = statistical_tests.get("draw_calibration_ttest", {})
    if draw_ttest:
        sig = "SIGNIFICANT" if draw_ttest.get("significant") else "not significant"
        w(f"- **Draw calibration t-test:** t={draw_ttest.get('t_stat', 0):.3f}, "
          f"p={draw_ttest.get('p_approx', 1):.4f} ({sig})")
        mean_err = draw_ttest.get("mean", 0)
        if abs(mean_err) > 0.05:
            direction = "overestimates" if mean_err > 0 else "underestimates"
            w(f"  - V5 {direction} draw probability by {abs(mean_err):.3f} on average")
    w("")

    w("## 6. Calibration")
    w("")
    w(f"- **Brier Score:** {brier:.4f}")
    w(f"- **Log Loss:** {log_loss:.4f}")
    w(f"- **Reliability:** {reliability:.4f}")
    w(f"- **Avg Confidence:** {calibration.get('avg_confidence', 0):.3f}")
    w("")
    chi2 = statistical_tests.get("calibration_chi2", {})
    if chi2:
        sig = "SIGNIFICANT - miscalibrated" if chi2.get("significant") else "not significant"
        w(f"- **Chi-Square Test:** chi2={chi2.get('chi2', 0):.2f}, "
          f"p={chi2.get('p_approx', 1):.4f} ({sig})")
    w("")
    w("### Calibration Curve")
    w("")
    curve = calibration.get("calibration_curve", [])
    if curve:
        w("| Bin | Predicted | Actual | Count | Gap | Status |")
        w("|-----|-----------|--------|-------|-----|--------|")
        for c in curve:
            gap = abs(c["avg_predicted"] - c["avg_actual"])
            status = "OK" if gap < 0.10 else "Overconfident" if c["avg_predicted"] > c["avg_actual"] else "Underconfident"
            w(f"| {c['bin_start']:.1f}-{c['bin_end']:.1f} | {c['avg_predicted']:.3f} "
              f"| {c['avg_actual']:.3f} | {c['count']} | {gap:.3f} | {status} |")
    w("")

    w("## 7. Stage Breakdown")
    w("")
    by_stage = tournament_summary.get("by_stage", {})
    if by_stage:
        w("| Stage | Matches | Correct | Accuracy |")
        w("|-------|---------|---------|----------|")
        for stage, data in sorted(by_stage.items()):
            w(f"| {stage} | {data['total']} | {data.get('correct', 0)} "
              f"| {data['accuracy']:.1%} |")
    w("")

    w("## 8. Strengths of V5")
    w("")
    strengths = []
    if v5_acc >= 0.50:
        strengths.append(f"Winner accuracy ({v5_acc:.1%}) meets or exceeds 50% baseline")
    if abs(bias) < 0.3:
        strengths.append(f"Goals prediction well-calibrated (bias: {bias:+.2f})")
    avg_xg_err = tournament_summary.get("avg_total_xg_error", 1.0)
    if avg_xg_err < 1.0:
        strengths.append(f"Average xG error is moderate ({avg_xg_err:.3f})")
    if avg_diff < 0.15:
        strengths.append(f"V5 probabilities align with ELO market (avg diff: {avg_diff:.3f})")
    for s_name, s_data in by_stage.items():
        if s_data["accuracy"] > 0.55 and s_data["total"] >= 4:
            strengths.append(f"Strong accuracy in {s_name} ({s_data['accuracy']:.1%}, n={s_data['total']})")
    major_str = upset_summary.get("by_favorite_strength", {}).get("Major favorite", {})
    if major_str.get("total", 0) > 0:
        major_acc = major_str.get("correct", 0) / major_str["total"]
        if major_acc > 0.80:
            strengths.append(f"High accuracy for Major Favorites ({major_acc:.1%}, n={major_str['total']})")
    if not strengths:
        strengths.append("V5 produces reasonable xG estimates that correlate with match outcomes")
    for s in strengths:
        w(f"- {s}")
    w("")

    w("## 9. Weaknesses of V5 (Statistically Supported)")
    w("")
    weaknesses = []
    for b in biases:
        ev = b.get("evidence", {})
        sig = ev.get("significant", False)
        pct = b.get("affected_pct", 0)
        if sig or pct > 30:
            weaknesses.append(
                f"**{b['bias_name']}:** {b['description']} "
                f"(affects {pct:.0f}% of matches"
                + (f", p={ev['p_approx']:.4f}" if sig else "") + ")"
            )
    if reliability > 0.15:
        weaknesses.append(
            f"**Poor Calibration:** Reliability={reliability:.3f}. "
            "V5's predicted probabilities don't match actual outcomes."
        )
    if v5_acc < 0.52:
        weaknesses.append(
            f"**Low Winner Accuracy:** {v5_acc:.1%} is "
            f"{'at' if v5_acc >= 0.50 else 'below'} the 50% random baseline."
        )
    if da.get("draw_accuracy", 0) < 25:
        weaknesses.append(
            f"**Draw Prediction:** V5 correctly identifies only {da.get('draw_accuracy', 0):.0f}% "
            f"of actual draws ({da.get('draw_predictions_correct', 0)}/{da.get('actual_draws', 0)}). "
            f"Average V5 draw probability: {da.get('avg_v5_draw_prob', 0):.3f} "
            f"vs actual {da.get('actual_draw_pct', 0):.1f}%."
        )
    if ha.get("v5_favors_home_count", 0) / n > 0.60 and actual_hw < 50:
        weaknesses.append(
            f"**Home Advantage Overestimated:** V5 favors home in "
            f"{ha.get('v5_favors_home_count', 0)/n:.0%} of matches "
            f"but actual home win rate is only {actual_hw:.0f}%."
        )
    if weaknesses:
        for wk in weaknesses:
            w(f"- {wk}")
    else:
        w("No statistically significant weaknesses identified with current data.")
    w("")

    w("## 10. Recommendations")
    w("")
    w("*Evidence-based suggestions. Only recommend changes with strong evidence.*")
    w("")
    recs = []
    if abs(bias) > 0.3:
        direction = "increase" if bias < 0 else "decrease"
        recs.append(
            f"**Goal Calibration:** V5 {'under' if bias < 0 else 'over'}estimates goals "
            f"by {abs(bias):.2f}/match. {direction.title()} xG lambda calculations. "
            "**CONFIDENCE: Strong** (systematic, statistically significant)."
        )
    if reliability > 0.15:
        recs.append(
            "**Probability Calibration:** Apply Platt scaling or isotonic regression "
            "to V5's win probabilities. "
            "**CONFIDENCE: Strong** (reliability metric well above 0)."
        )
    if da.get("draw_accuracy", 0) < 25:
        recs.append(
            f"**Draw Modeling:** V5 misses {100 - da.get('draw_accuracy', 0):.0f}% of draws. "
            "Consider adding a draw probability term to the xG-to-outcome model "
            "(e.g., Dixon-Coles with rho parameter for low-scoring draws). "
            f"**CONFIDENCE: Strong** (only {da.get('draw_accuracy', 0):.0f}% draw accuracy)."
        )
    model_failures = cat_counts.get("Model Failure", 0)
    if model_failures > n * 0.12:
        recs.append(
            f"**Favorite Selection:** {model_failures} Model Failures ({model_failures/n:.1%}) "
            "indicate V5 agrees with ELO but the favorite still loses frequently. "
            "Consider adding momentum/injury/context factors. "
            "**CONFIDENCE: Moderate** (depends on sample size)."
        )
    if not recs:
        recs.append(
            "**No changes recommended.** Current biases are within normal range. "
            "Re-evaluate after more matches are played."
        )
    for i, rec in enumerate(recs, 1):
        w(f"{i}. {rec}")
    w("")
    w("---")
    w("")
    w("*This report was generated by the V6 Evaluation & Diagnostics Layer.*")
    w("*It is for analysis only and does not modify V5 simulator parameters.*")
    w(f"*V5 predictions use Poisson model to derive H/D/A from xG.*")

    report_text = "\n".join(lines)
    if output_dir:
        report_path = output_dir / "v6_report.md"
        report_path.write_text(report_text, encoding="utf-8")
    return report_text


# ═════════════════════════════════════════════════════════════════════════════
# CSV Export
# ═════════════════════════════════════════════════════════════════════════════

CSV_COLUMNS = [
    "home", "away", "stage", "group",
    "v5_home_prob", "v5_draw_prob", "v5_away_prob",
    "v5_favorite", "v5_favorite_prob",
    "predicted_xg_home", "predicted_xg_away",
    "predicted_ppda_home", "predicted_ppda_away",
    "predicted_possession_home", "predicted_possession_away",
    "predicted_winner", "most_likely_score",
    "actual_home_goals", "actual_away_goals",
    "actual_winner",
    "market_home_prob", "market_draw_prob", "market_away_prob",
    "market_favorite", "market_favorite_prob",
    "v5_agrees_with_market",
    "upset_category", "upset_label", "favorite_strength",
    "winner_correct", "scoreline_error",
    "xg_home_error", "xg_away_error", "total_xg_error",
    "total_goals_error",
]


def _save_csv(match_metrics: list[dict], path: Path) -> None:
    valid = [m for m in match_metrics if "error" not in m]
    if not valid:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for m in valid:
            row = {}
            for k in CSV_COLUMNS:
                row[k] = m.get(k, "")
            writer.writerow(row)


# ═════════════════════════════════════════════════════════════════════════════
# V6 Adaptive Engine (main entry point)
# ═════════════════════════════════════════════════════════════════════════════

class V6AdaptiveEngine(MatchEngine):
    """V6: Wraps V5 with live per-team xG corrections from real match results.

    V6 is a temporary adaptive layer. It uses V5 as its core simulation
    and applies small per-team xG corrections based on how teams actually
    perform versus V5's predictions.

    Corrections are per-team attacking deltas only, capped at ±0.3 xG,
    requiring minimum 3 matches per team. V6 never modifies V5's global
    parameters (home advantage, draw rates, tactical weights, etc.).
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        team_metrics: dict | None = None,
        tournament_form: dict[str, float] | None = None,
    ):
        from .v5_match_state_engine import V5MatchStateEngine

        self.data_dir = Path(data_dir) if data_dir else FIFA_DATA
        resolved = self.data_dir
        self.team_metrics = team_metrics or {}
        self.tournament_form = tournament_form or {}

        self._v5 = V5MatchStateEngine(
            data_dir=resolved,
            team_metrics=self.team_metrics,
            tournament_form=self.tournament_form,
        )

        self._corrections: dict[str, float] = {}
        self._goals_scored: dict[str, list[float]] = {}
        self._xg_when_attacking: dict[str, list[float]] = {}
        self._pending_predictions: dict[str, float] = {}
        self._real_matches_observed: int = 0

        self._min_matches = 3
        self._max_correction = 0.3
        self._blend_ceiling = 10.0

        self._orig_eg = self._v5._v4._v3.expected_goals
        self._apply_xg_patch()

    def _apply_xg_patch(self) -> None:
        v3 = self._v5._v4._v3
        engine = self
        orig = self._orig_eg

        def _corrected_xg(strength1, strength2):
            base1, base2 = orig(strength1, strength2)
            c1 = engine._corrections.get(strength1.team, 0.0)
            c2 = engine._corrections.get(strength2.team, 0.0)
            return (
                max(engine._v5.minimum_lambda, base1 + c1),
                max(engine._v5.minimum_lambda, base2 + c2),
            )

        v3.expected_goals = _corrected_xg

    def simulate_match(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
    ) -> tuple[int, int]:
        s1 = self._v5._v4._v3.get_team_strength(team1)
        s2 = self._v5._v4._v3.get_team_strength(team2)
        base1, base2 = self._orig_eg(s1, s2)
        self._pending_predictions = {team1: base1, team2: base2}
        return self._v5.simulate_match(team1, team2, can_draw)

    def simulate_match_debug(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
    ) -> tuple[tuple[int, int], str]:
        s1 = self._v5._v4._v3.get_team_strength(team1)
        s2 = self._v5._v4._v3.get_team_strength(team2)
        base1, base2 = self._orig_eg(s1, s2)
        self._pending_predictions = {team1: base1, team2: base2}
        return self._v5.simulate_match_debug(team1, team2, can_draw)

    def simulate_match_detailed(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
        context: str | None = None,
    ):
        s1 = self._v5._v4._v3.get_team_strength(team1)
        s2 = self._v5._v4._v3.get_team_strength(team2)
        base1, base2 = self._orig_eg(s1, s2)
        self._pending_predictions = {team1: base1, team2: base2}
        return self._v5.simulate_match_detailed(team1, team2, can_draw, context)

    def notify_match(
        self,
        team1: str,
        team2: str,
        goals1: int,
        goals2: int,
        is_real: bool,
    ) -> None:
        self._v5.notify_match(team1, team2, goals1, goals2, is_real)
        if not is_real:
            return

        base1 = self._pending_predictions.get(team1, 1.2)
        base2 = self._pending_predictions.get(team2, 1.2)
        self._pending_predictions = {}

        self._observe(team1, goals1, base1)
        self._observe(team2, goals2, base2)
        self._recompute_corrections()
        self._real_matches_observed += 1

    def expected_goals(
        self,
        team1: str,
        team2: str,
        context: str = "group",
    ) -> tuple[float, float]:
        return self._v5.expected_goals(team1, team2, context)

    @property
    def last_match_debug(self) -> str:
        return self._v5.last_match_debug

    @property
    def last_match_state(self):
        return self._v5.last_match_state

    @property
    def last_match_events(self):
        return self._v5.last_match_events

    def _observe(self, team: str, goals_scored: float, predicted_xg: float) -> None:
        self._goals_scored.setdefault(team, []).append(goals_scored)
        self._xg_when_attacking.setdefault(team, []).append(predicted_xg)

    def _recompute_corrections(self) -> None:
        for team in list(self._goals_scored.keys()):
            scores = self._goals_scored[team]
            xgs = self._xg_when_attacking[team]
            n = len(scores)
            if n < self._min_matches:
                self._corrections[team] = 0.0
                continue
            avg_error = (sum(scores) / n) - (sum(xgs) / n)
            blend = min(1.0, n / self._blend_ceiling)
            raw = avg_error * blend
            self._corrections[team] = max(
                -self._max_correction,
                min(self._max_correction, raw),
            )

    def get_corrections(self) -> dict[str, float]:
        return dict(self._corrections)

    def run_evaluation(
        self,
        odds_file: Path | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        if output_dir is None:
            output_dir = HERE.parent / "v6_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        print("=" * 70)
        print("  V6 EVALUATION & DIAGNOSTICS LAYER")
        print("  Non-invasive analysis on top of V5 simulator")
        print("=" * 70)
        print()

        t0 = time.time()

        print("[1/8] Loading real match data...")
        from fifa_data.benchmark.data_loader import (
            load_real_matches, load_groups, load_team_metrics, get_stage_category,
        )
        matches = load_real_matches()
        groups = load_groups()
        team_metrics = load_team_metrics()
        print(f"  Loaded {len(matches)} real matches")
        stages: dict[str, int] = {}
        for m in matches:
            s = m.get("stage", "Unknown")
            stages[s] = stages.get(s, 0) + 1
        for s, c in sorted(stages.items()):
            print(f"    {s}: {c} matches")
        print()

        print("[2/8] Running V5 simulations for all matches...")
        from fifa_data.benchmark.simulation_runner import simulate_all_matches
        sim_results = simulate_all_matches(matches, groups, team_metrics)
        valid_sims = [r for r in sim_results if "error" not in r]
        print(f"  Simulated {len(valid_sims)}/{len(matches)} matches successfully")
        print()

        print("[3/8] Computing V5 win/draw probabilities from xG (Poisson model)...")
        from fifa_data.benchmark.metrics import compute_match_metrics, compute_tournament_summary

        match_metrics = compute_match_metrics(sim_results, matches)
        match_metrics = compute_v5_hda(match_metrics)

        for m in match_metrics:
            if "error" in m:
                continue
            m["stage_category"] = get_stage_category(m.get("stage", ""), m.get("group", ""))
            m["predicted_total_goals"] = m.get("predicted_xg_home", 0) + m.get("predicted_xg_away", 0)
            m["actual_total_goals"] = m.get("actual_home_goals", 0) + m.get("actual_away_goals", 0)
            m["total_goals_error"] = m["predicted_total_goals"] - m["actual_total_goals"]
            m["goals_overestimated"] = m["total_goals_error"] > 0.25
            m["goals_underestimated"] = m["total_goals_error"] < -0.25
            v5_fav = m.get("v5_favorite", "Draw")
            actual = m.get("actual_winner", "Draw")
            m["v5_winner_correct"] = (v5_fav == actual)
            m["v5_agrees_with_market"] = (v5_fav == m.get("market_favorite", "Draw"))

        tournament_summary = compute_tournament_summary(match_metrics)

        v5_correct = sum(1 for m in match_metrics if m.get("v5_winner_correct") and "error" not in m)
        total_valid = sum(1 for m in match_metrics if "error" not in m)
        print(f"  V5 Poisson-based winner accuracy: {v5_correct}/{total_valid} ({v5_correct/total_valid:.1%})")
        print()

        print("[4/8] Computing market probabilities...")
        market = load_market_odds(matches, odds_file, team_metrics)
        print(f"  Loaded odds for {len(market)} matches")
        if odds_file and odds_file.exists():
            print(f"  Source: {odds_file}")
        else:
            print("  Source: Synthetic (ELO-based)")
        print()

        print("[5/8] Classifying upsets...")
        match_metrics = classify_all_matches(match_metrics, market)
        upset_summary = summarize_upsets(match_metrics)
        cats = upset_summary.get("category_counts", {})
        print(f"  Categories: {cats}")
        print()

        print("[6/8] Computing calibration metrics...")
        from fifa_data.benchmark.calibration import compute_calibration_metrics

        valid = [m for m in match_metrics if "error" not in m]
        calibration = compute_calibration_metrics(match_metrics)
        print(f"  Brier Score: {calibration.get('brier_score', 0):.4f}")
        print(f"  Log Loss: {calibration.get('log_loss', 0):.4f}")
        print(f"  Reliability: {calibration.get('reliability', 0):.4f}")
        print()

        print("[7/8] Running statistical tests...")

        goals_diffs = [m["predicted_total_goals"] - m["actual_total_goals"] for m in valid]
        goals_ttest = one_sample_t_test(goals_diffs, hypothesized_mean=0.0)
        goals_bootstrap = bootstrap_mean_ci(goals_diffs)

        home_favored = [m for m in valid if m.get("v5_home_prob", 0.5) > m.get("v5_away_prob", 0.5)]
        away_favored = [m for m in valid if m.get("v5_away_prob", 0.5) > m.get("v5_home_prob", 0.5)]
        actual_home_wins = [m for m in valid if m.get("actual_winner") == m.get("home")]
        actual_away_wins = [m for m in valid if m.get("actual_winner") == m.get("away")]
        actual_draws_list = [m for m in valid if m.get("actual_winner") == "Draw"]

        home_win_pct = len(actual_home_wins) / len(valid) * 100 if valid else 0
        away_win_pct = len(actual_away_wins) / len(valid) * 100 if valid else 0
        draw_pct = len(actual_draws_list) / len(valid) * 100 if valid else 0

        v5_home_advantage = [m.get("v5_home_prob", 0.33) - m.get("v5_away_prob", 0.33) for m in valid]
        v5_avg_home_adv = sum(v5_home_advantage) / len(v5_home_advantage) if v5_home_advantage else 0

        home_adv_analysis = {
            "actual_home_win_pct": round(home_win_pct, 1),
            "actual_away_win_pct": round(away_win_pct, 1),
            "actual_draw_pct": round(draw_pct, 1),
            "actual_home_win_count": len(actual_home_wins),
            "actual_away_win_count": len(actual_away_wins),
            "v5_favors_home_count": len(home_favored),
            "v5_favors_away_count": len(away_favored),
            "v5_avg_home_advantage": round(v5_avg_home_adv, 4),
            "v5_home_correct": sum(1 for m in home_favored if m.get("v5_winner_correct")),
            "v5_away_correct": sum(1 for m in away_favored if m.get("v5_winner_correct")),
        }

        home_adv_diffs = []
        for m in valid:
            pred_home_adv = m.get("v5_home_prob", 0.33) - m.get("v5_away_prob", 0.33)
            actual_home_adv = 1.0 if m.get("actual_winner") == m.get("home") else (
                -1.0 if m.get("actual_winner") == m.get("away") else 0.0
            )
            home_adv_diffs.append(pred_home_adv - actual_home_adv * 0.15)
        home_adv_ttest = one_sample_t_test(home_adv_diffs, hypothesized_mean=0.0)

        v5_draw_probs = [m.get("v5_draw_prob", 0.25) for m in valid]
        avg_v5_draw_prob = sum(v5_draw_probs) / len(v5_draw_probs) if v5_draw_probs else 0
        draw_correct = sum(1 for m in valid if m.get("actual_winner") == "Draw" and m.get("v5_favorite") == "Draw")

        draw_analysis = {
            "actual_draws": len(actual_draws_list),
            "actual_draw_pct": round(draw_pct, 1),
            "v5_predicted_draw_favorite": sum(1 for m in valid if m.get("v5_favorite") == "Draw"),
            "avg_v5_draw_prob": round(avg_v5_draw_prob, 4),
            "draw_predictions_correct": draw_correct,
            "draw_accuracy": round(draw_correct / len(actual_draws_list) * 100, 1) if actual_draws_list else 0,
        }

        draw_calib_errors = []
        for m in valid:
            dp = m.get("v5_draw_prob", 0.25)
            is_draw = 1.0 if m.get("actual_winner") == "Draw" else 0.0
            draw_calib_errors.append(dp - is_draw)
        draw_calib_ttest = one_sample_t_test(draw_calib_errors, hypothesized_mean=0.0)

        v5_probs = [m.get("v5_favorite_prob", 0.5) for m in valid]
        outcomes = [1 if m.get("v5_winner_correct") else 0 for m in valid]
        chi2_test = chi_square_calibration_test(v5_probs, outcomes)

        xg_h_errs = [m.get("xg_home_error", 0) for m in valid]
        xg_h_test = one_sample_t_test(xg_h_errs, hypothesized_mean=0.0)
        xg_a_errs = [m.get("xg_away_error", 0) for m in valid]
        xg_a_test = one_sample_t_test(xg_a_errs, hypothesized_mean=0.0)

        mkt_v5_diffs = []
        for m in valid:
            v5_p = m.get("v5_favorite_prob", 0.5)
            mkt_p = m.get("market_favorite_prob", 0.5)
            mkt_v5_diffs.append(abs(v5_p - mkt_p))
        mkt_v5_avg_diff = sum(mkt_v5_diffs) / len(mkt_v5_diffs) if mkt_v5_diffs else 0

        mkt_agreement = sum(1 for m in valid if m.get("v5_agrees_with_market"))

        biases = detect_systematic_biases(match_metrics)

        stat_tests = {
            "goals_ttest": goals_ttest,
            "goals_bootstrap_ci": goals_bootstrap,
            "xg_home_error_test": xg_h_test,
            "xg_away_error_test": xg_a_test,
            "home_advantage_ttest": home_adv_ttest,
            "draw_calibration_ttest": draw_calib_ttest,
            "calibration_chi2": chi2_test,
        }

        print(f"  Goals bias: {goals_ttest['mean']:+.3f} (CI: [{goals_bootstrap['ci_low']:.3f}, "
              f"{goals_bootstrap['ci_high']:.3f}]) p={goals_ttest['p_approx']:.4f}")
        print(f"  Home advantage: actual {home_win_pct:.0f}% H wins, V5 avg home adv: {v5_avg_home_adv:+.3f}")
        print(f"  Draw accuracy: {draw_analysis['draw_accuracy']:.0f}% "
              f"(avg V5 draw prob: {avg_v5_draw_prob:.3f})")
        print(f"  V5 vs Market avg |diff|: {mkt_v5_avg_diff:.3f}, agreement: {mkt_agreement}/{len(valid)}")
        print(f"  Chi-square: chi2={chi2_test.get('chi2', 0):.2f}, p={chi2_test.get('p_approx', 1):.4f} "
              f"({'SIGNIFICANT' if chi2_test.get('significant') else 'not significant'})")
        print(f"  Detected {len(biases)} systematic bias(es)")
        for b in biases:
            print(f"    - {b['bias_name']}: {b['description']}")
        print()

        print("[8/8] Generating visualizations and report...")
        graphs = generate_all_graphs(match_metrics, calibration, tournament_summary, output_dir)
        print(f"  Generated {len(graphs)} graphs")

        analysis = {
            "home_advantage": home_adv_analysis,
            "draw_analysis": draw_analysis,
            "market_v5_avg_diff": round(mkt_v5_avg_diff, 4),
            "market_v5_agreement": mkt_agreement,
        }

        report = generate_v6_report(
            match_metrics, tournament_summary, calibration, market,
            upset_summary, stat_tests, biases, analysis, output_dir,
        )
        print(f"  Report: {output_dir / 'v6_report.md'}")

        comparisons = []
        for m in match_metrics:
            if "error" in m:
                continue
            ph = m.get("predicted_home_goals", 0)
            pa = m.get("predicted_away_goals", 0)
            ah = m.get("actual_home_goals", 0)
            aa = m.get("actual_away_goals", 0)
            v5h = m.get("v5_home_prob", 0)
            v5d = m.get("v5_draw_prob", 0)
            v5a = m.get("v5_away_prob", 0)

            def _fmt_real(key_h: str, key_a: str, fmt: str = "d") -> str | None:
                rv_h = m.get(key_h)
                rv_a = m.get(key_a)
                if rv_h is None or rv_a is None:
                    return None
                if fmt == ".2f":
                    return f"{float(rv_h):.2f} | {float(rv_a):.2f}"
                if fmt == ".1f":
                    return f"{float(rv_h):.1f} | {float(rv_a):.1f}"
                if fmt == ".0f":
                    return f"{float(rv_h):.0f} | {float(rv_a):.0f}"
                return f"{int(rv_h)} | {int(rv_a)}"

            comparisons.append({
                "home": m["home"],
                "away": m["away"],
                "stage": m.get("stage_category", m.get("stage", "")),
                "pred_score": f"{ph}-{pa}",
                "actual_score": f"{ah}-{aa}",
                "pred_winner": m.get("v5_favorite", "Draw"),
                "actual_winner": m.get("actual_winner", "Draw"),
                "winner_correct": m.get("v5_winner_correct", False),
                "pred_probs": f"{v5h:.0%}|{v5d:.0%}|{v5a:.0%}",
                "pred_xg": f"{m.get('predicted_xg_home', 0):.2f} | {m.get('predicted_xg_away', 0):.2f}",
                "real_xg": _fmt_real("real_xg_home", "real_xg_away", ".2f"),
                "pred_shots": f"{m.get('predicted_shots_home', 0)} | {m.get('predicted_shots_away', 0)}",
                "real_shots": _fmt_real("real_shots_home", "real_shots_away"),
                "pred_sot": f"{m.get('predicted_sot_home', 0)} | {m.get('predicted_sot_away', 0)}",
                "real_sot": _fmt_real("real_sot_home", "real_sot_away"),
                "pred_poss": f"{m.get('predicted_possession_home', 0):.0f} | {m.get('predicted_possession_away', 0):.0f}",
                "real_poss": _fmt_real("real_possession_home", "real_possession_away", ".0f"),
                "pred_ppda": f"{m.get('predicted_ppda_home', 0):.1f} | {m.get('predicted_ppda_away', 0):.1f}",
                "real_ppda": _fmt_real("real_ppda_home", "real_ppda_away", ".1f"),
                "pred_corners": f"{m.get('predicted_corners_home', 0)} | {m.get('predicted_corners_away', 0)}",
                "real_corners": _fmt_real("real_corners_home", "real_corners_away"),
                "pred_yellows": f"{m.get('predicted_yellows_home', 0)} | {m.get('predicted_yellows_away', 0)}",
                "real_yellows": _fmt_real("real_yellows_home", "real_yellows_away"),
                "pred_reds": f"{m.get('predicted_reds_home', 0)} | {m.get('predicted_reds_away', 0)}",
                "real_reds": _fmt_real("real_reds_home", "real_reds_away"),
                "upset_category": m.get("upset_category", ""),
            })

        summary = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_matches": len(match_metrics),
            "simulated_ok": len(valid_sims),
            "v5_poisson_winner_accuracy": round(v5_correct / total_valid, 4) if total_valid else 0,
            "tournament_summary": tournament_summary,
            "calibration": calibration,
            "upset_summary": upset_summary,
            "home_advantage": home_adv_analysis,
            "draw_analysis": draw_analysis,
            "statistical_tests": {k: v for k, v in stat_tests.items()
                                  if isinstance(v, dict) and "p_approx" in v},
            "biases": biases,
            "analysis": analysis,
            "match_comparisons": comparisons,
        }
        summary_path = output_dir / "v6_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        print(f"  Summary JSON: {summary_path}")

        csv_path = output_dir / "v6_matches.csv"
        _save_csv(match_metrics, csv_path)
        print(f"  Matches CSV: {csv_path}")

        elapsed = time.time() - t0
        print()
        print("=" * 70)
        print("  V6 EVALUATION COMPLETE")
        print("=" * 70)
        print(f"  Time: {elapsed:.1f}s")
        print(f"  Output: {output_dir}")
        print(f"  Files:")
        print(f"    - v6_report.md (comprehensive report)")
        print(f"    - v6_summary.json (machine-readable)")
        print(f"    - v6_matches.csv (per-match data)")
        print(f"    - graphs/ ({len(graphs)} PNG files)")
        print()

        return summary


def run_v6(odds_file: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    from fifa_data.services.simulation_service import TEAM_METRICS
    engine = V6AdaptiveEngine(team_metrics=TEAM_METRICS)
    return engine.run_evaluation(odds_file=odds_file, output_dir=output_dir)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="V6 Adaptive Engine")
    parser.add_argument("--odds", type=str, default=None,
                        help="Path to sportsbook odds JSON file")
    parser.add_argument("--output", type=str, default=None,
                        help="Output directory")
    args = parser.parse_args()
    odds = Path(args.odds) if args.odds else None
    out = Path(args.output) if args.output else None
    run_v6(odds_file=odds, output_dir=out)
