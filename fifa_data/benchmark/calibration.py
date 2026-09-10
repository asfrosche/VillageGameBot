"""V5 Benchmark - Calibration Metrics.

Computes probabilistic calibration metrics for V5 predictions.
"""
from __future__ import annotations

import math
from collections import defaultdict


def compute_calibration_metrics(match_metrics: list[dict]) -> dict:
    """Compute calibration and probabilistic metrics.

    Uses the V5 win probabilities derived from xG differences
    to assess whether the model's probabilities are well calibrated.
    """
    valid = [m for m in match_metrics if "error" not in m]
    if not valid:
        return {}

    brier_scores = []
    log_losses = []
    confidence_scores = []

    predicted_probabilities = []
    actual_outcomes = []

    for m in valid:
        pred_xg_diff = m["predicted_xg_home"] - m["predicted_xg_away"]
        pred_home_win_prob = _xg_diff_to_win_prob(pred_xg_diff)

        if m["winner_correct"]:
            if m["actual_winner"] == "Draw":
                actual_home_win = 0.0
                actual_away_win = 0.0
            elif m["actual_winner"] == m["home"]:
                actual_home_win = 1.0
                actual_away_win = 0.0
            else:
                actual_home_win = 0.0
                actual_away_win = 1.0
        else:
            if m["actual_winner"] == "Draw":
                actual_home_win = 0.0
                actual_away_win = 0.0
            elif m["actual_winner"] == m["home"]:
                actual_home_win = 1.0
                actual_away_win = 0.0
            else:
                actual_home_win = 0.0
                actual_away_win = 1.0

        pred_away_win_prob = 1.0 - pred_home_win_prob
        if m["predicted_winner"] == "Draw":
            pred_draw_prob = max(0.1, 1.0 - pred_home_win_prob - pred_away_win_prob)
        else:
            pred_draw_prob = 0.2

        brier = (pred_home_win_prob - actual_home_win) ** 2 + \
                (pred_away_win_prob - actual_away_win) ** 2
        brier_scores.append(brier)

        eps = 1e-10
        ll_home = actual_home_win * math.log(max(pred_home_win_prob, eps)) + \
                  (1 - actual_home_win) * math.log(max(1 - pred_home_win_prob, eps))
        ll_away = actual_away_win * math.log(max(pred_away_win_prob, eps)) + \
                  (1 - actual_away_win) * math.log(max(1 - pred_away_win_prob, eps))
        log_losses.append(-(ll_home + ll_away) / 2)

        confidence = max(pred_home_win_prob, pred_away_win_prob, pred_draw_prob)
        confidence_scores.append(confidence)

        predicted_probabilities.append(pred_home_win_prob)
        actual_outcomes.append(actual_home_win)

    avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else 0
    avg_log_loss = sum(log_losses) / len(log_losses) if log_losses else 0
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0

    calibration_curve = _compute_calibration_curve(predicted_probabilities, actual_outcomes)

    reliability = _compute_reliability(calibration_curve)

    return {
        "brier_score": round(avg_brier, 4),
        "log_loss": round(avg_log_loss, 4),
        "avg_confidence": round(avg_confidence, 3),
        "calibration_curve": calibration_curve,
        "reliability": round(reliability, 4),
        "total_matches": len(valid),
    }


def _xg_diff_to_win_prob(xg_diff: float) -> float:
    """Convert xG difference to home win probability using logistic function."""
    k = 2.5
    return 1.0 / (1.0 + math.exp(-k * xg_diff))


def _compute_calibration_curve(
    predicted: list[float],
    actual: list[float],
    n_bins: int = 10,
) -> list[dict]:
    """Compute calibration curve data points."""
    bins = defaultdict(lambda: {"predicted": [], "actual": []})

    for pred, act in zip(predicted, actual):
        bin_idx = min(int(pred * n_bins), n_bins - 1)
        bins[bin_idx]["predicted"].append(pred)
        bins[bin_idx]["actual"].append(act)

    curve = []
    for i in range(n_bins):
        if bins[i]["predicted"]:
            avg_pred = sum(bins[i]["predicted"]) / len(bins[i]["predicted"])
            avg_actual = sum(bins[i]["actual"]) / len(bins[i]["actual"])
            count = len(bins[i]["predicted"])
            curve.append({
                "bin_start": round(i / n_bins, 2),
                "bin_end": round((i + 1) / n_bins, 2),
                "avg_predicted": round(avg_pred, 3),
                "avg_actual": round(avg_actual, 3),
                "count": count,
                "gap": round(abs(avg_pred - avg_actual), 3),
            })

    return curve


def _compute_reliability(calibration_curve: list[dict]) -> float:
    """Compute reliability (lower is better, 0 = perfect calibration)."""
    if not calibration_curve:
        return 1.0

    total_weight = sum(point["count"] for point in calibration_curve)
    if total_weight == 0:
        return 1.0

    weighted_gap = sum(
        point["gap"] * point["count"] for point in calibration_curve
    )
    return weighted_gap / total_weight
