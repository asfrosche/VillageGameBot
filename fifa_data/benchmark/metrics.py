"""V5 Benchmark - Comparison Metrics.

Computes match-level and tournament-level comparison metrics
between V5 predictions and real match data.
"""
from __future__ import annotations

import math
from collections import defaultdict


def compute_match_metrics(
    sim_results: list[dict],
    real_matches: list[dict],
) -> list[dict]:
    """Compute comparison metrics for each match.

    Returns list of dicts with all comparison data.
    """
    real_lookup = {}
    for m in real_matches:
        key = (m["home_name"], m["away_name"])
        real_lookup[key] = m

    metrics = []
    for sim in sim_results:
        if "error" in sim:
            metrics.append({
                "home": sim["home"],
                "away": sim["away"],
                "stage": sim["stage"],
                "group": sim.get("group", ""),
                "date": sim.get("date", ""),
                "error": sim["error"],
            })
            continue

        home = sim["home"]
        away = sim["away"]

        pred_home_goals = sim["predicted_home_goals"]
        pred_away_goals = sim["predicted_away_goals"]
        actual_home_goals = sim["actual_home_goals"]
        actual_away_goals = sim["actual_away_goals"]

        pred_winner = sim["predicted_winner"]
        actual_winner = sim["actual_winner"]
        winner_correct = pred_winner == actual_winner

        scoreline_error = abs(pred_home_goals - actual_home_goals) + abs(pred_away_goals - actual_away_goals)

        pred_total_goals = pred_home_goals + pred_away_goals
        actual_total_goals = actual_home_goals + actual_away_goals
        total_goals_error = abs(pred_total_goals - actual_total_goals)

        pred_xg_home = sim.get("predicted_xg_home", 0)
        pred_xg_away = sim.get("predicted_xg_away", 0)
        xg_home_error = abs(pred_xg_home - actual_home_goals)
        xg_away_error = abs(pred_xg_away - actual_away_goals)
        total_xg_error = (xg_home_error + xg_away_error) / 2

        pred_poss_home = sim.get("predicted_possession_home", 50)
        pred_poss_away = sim.get("predicted_possession_away", 50)

        pred_shots_home = sim.get("predicted_shots_home", 0)
        pred_shots_away = sim.get("predicted_shots_away", 0)

        pred_sot_home = sim.get("predicted_sot_home", 0)
        pred_sot_away = sim.get("predicted_sot_away", 0)

        pred_ppda_home = sim.get("predicted_ppda_home", 15)
        pred_ppda_away = sim.get("predicted_ppda_away", 15)

        pred_da_home = sim.get("predicted_da_home", 0)
        pred_da_away = sim.get("predicted_da_away", 0)

        pred_corners_home = sim.get("predicted_corners_home", 0)
        pred_corners_away = sim.get("predicted_corners_away", 0)

        pred_yellows_home = sim.get("predicted_yellows_home", 0)
        pred_yellows_away = sim.get("predicted_yellows_away", 0)
        pred_reds_home = sim.get("predicted_reds_home", 0)
        pred_reds_away = sim.get("predicted_reds_away", 0)

        from fifa_data.benchmark.data_loader import get_stage_category
        stage_category = get_stage_category(sim["stage"], sim.get("group", ""))

        metrics.append({
            "home": home,
            "away": away,
            "stage": sim["stage"],
            "stage_category": stage_category,
            "group": sim.get("group", ""),
            "date": sim.get("date", ""),
            "predicted_home_goals": pred_home_goals,
            "predicted_away_goals": pred_away_goals,
            "predicted_winner": pred_winner,
            "actual_home_goals": actual_home_goals,
            "actual_away_goals": actual_away_goals,
            "actual_winner": actual_winner,
            "winner_correct": winner_correct,
            "scoreline_error": scoreline_error,
            "total_goals_error": total_goals_error,
            "predicted_total_goals": pred_total_goals,
            "actual_total_goals": actual_total_goals,
            "predicted_xg_home": pred_xg_home,
            "predicted_xg_away": pred_xg_away,
            "xg_home_error": round(xg_home_error, 3),
            "xg_away_error": round(xg_away_error, 3),
            "total_xg_error": round(total_xg_error, 3),
            "predicted_possession_home": pred_poss_home,
            "predicted_possession_away": pred_poss_away,
            "predicted_shots_home": pred_shots_home,
            "predicted_shots_away": pred_shots_away,
            "predicted_sot_home": pred_sot_home,
            "predicted_sot_away": pred_sot_away,
            "predicted_ppda_home": pred_ppda_home,
            "predicted_ppda_away": pred_ppda_away,
            "predicted_da_home": pred_da_home,
            "predicted_da_away": pred_da_away,
            "predicted_corners_home": pred_corners_home,
            "predicted_corners_away": pred_corners_away,
            "predicted_yellows_home": pred_yellows_home,
            "predicted_yellows_away": pred_yellows_away,
            "predicted_reds_home": pred_reds_home,
            "predicted_reds_away": pred_reds_away,
            "game_plan_home": sim.get("game_plan_home", ""),
            "game_plan_away": sim.get("game_plan_away", ""),
            "tactical_summary": sim.get("tactical_summary", ""),
            "top_performers": sim.get("top_performers", []),
            "most_likely_score": sim.get("most_likely_score", ""),
            "xg_per_shot_home": sim.get("xg_per_shot_home", 0),
            "xg_per_shot_away": sim.get("xg_per_shot_away", 0),
            "home_energy_avg": sim.get("home_energy_avg", 100),
            "away_energy_avg": sim.get("away_energy_avg", 100),
            "is_extra_time": sim.get("is_extra_time", False),
            "is_penalty_shootout": sim.get("is_penalty_shootout", False),
            "total_events": sim.get("total_events", 0),
            "real_xg_home": sim.get("real_xg_home"),
            "real_xg_away": sim.get("real_xg_away"),
            "real_shots_home": sim.get("real_shots_home"),
            "real_shots_away": sim.get("real_shots_away"),
            "real_sot_home": sim.get("real_sot_home"),
            "real_sot_away": sim.get("real_sot_away"),
            "real_possession_home": sim.get("real_possession_home"),
            "real_possession_away": sim.get("real_possession_away"),
            "real_corners_home": sim.get("real_corners_home"),
            "real_corners_away": sim.get("real_corners_away"),
            "real_yellows_home": sim.get("real_yellows_home"),
            "real_yellows_away": sim.get("real_yellows_away"),
            "real_reds_home": sim.get("real_reds_home"),
            "real_reds_away": sim.get("real_reds_away"),
            "real_ppda_home": sim.get("real_ppda_home"),
            "real_ppda_away": sim.get("real_ppda_away"),
        })

    return metrics


def compute_tournament_summary(match_metrics: list[dict]) -> dict:
    """Compute overall tournament summary statistics."""
    valid = [m for m in match_metrics if "error" not in m]
    if not valid:
        return {"total_matches": 0}

    total = len(valid)
    correct_winners = sum(1 for m in valid if m["winner_correct"])

    avg_scoreline_error = sum(m["scoreline_error"] for m in valid) / total
    avg_total_goals_error = sum(m["total_goals_error"] for m in valid) / total
    avg_xg_home_error = sum(m["xg_home_error"] for m in valid) / total
    avg_xg_away_error = sum(m["xg_away_error"] for m in valid) / total
    avg_total_xg_error = sum(m["total_xg_error"] for m in valid) / total

    avg_pred_total_goals = sum(m["predicted_total_goals"] for m in valid) / total
    avg_actual_total_goals = sum(m["actual_total_goals"] for m in valid) / total

    avg_pred_shots_home = sum(m["predicted_shots_home"] for m in valid) / total
    avg_pred_shots_away = sum(m["predicted_shots_away"] for m in valid) / total

    avg_pred_sot_home = sum(m["predicted_sot_home"] for m in valid) / total
    avg_pred_sot_away = sum(m["predicted_sot_away"] for m in valid) / total

    avg_pred_ppda_home = sum(m["predicted_ppda_home"] for m in valid) / total
    avg_pred_ppda_away = sum(m["predicted_ppda_away"] for m in valid) / total

    avg_pred_poss_home = sum(m["predicted_possession_home"] for m in valid) / total

    avg_energy_home = sum(m["home_energy_avg"] for m in valid) / total
    avg_energy_away = sum(m["away_energy_avg"] for m in valid) / total

    by_stage = defaultdict(lambda: {"total": 0, "correct": 0})
    for m in valid:
        cat = m["stage_category"]
        by_stage[cat]["total"] += 1
        if m["winner_correct"]:
            by_stage[cat]["correct"] += 1

    stage_accuracy = {}
    for cat, data in by_stage.items():
        stage_accuracy[cat] = {
            "total": data["total"],
            "correct": data["correct"],
            "accuracy": round(data["correct"] / data["total"], 3) if data["total"] > 0 else 0,
        }

    pred_goals_distribution = defaultdict(int)
    actual_goals_distribution = defaultdict(int)
    for m in valid:
        pred_key = f"{m['predicted_home_goals']}-{m['predicted_away_goals']}"
        actual_key = f"{m['actual_home_goals']}-{m['actual_away_goals']}"
        pred_goals_distribution[pred_key] += 1
        actual_goals_distribution[actual_key] += 1

    return {
        "total_matches": total,
        "correct_winners": correct_winners,
        "winner_accuracy": round(correct_winners / total, 3),
        "avg_scoreline_error": round(avg_scoreline_error, 3),
        "avg_total_goals_error": round(avg_total_goals_error, 3),
        "avg_xg_home_error": round(avg_xg_home_error, 3),
        "avg_xg_away_error": round(avg_xg_away_error, 3),
        "avg_total_xg_error": round(avg_total_xg_error, 3),
        "avg_predicted_total_goals": round(avg_pred_total_goals, 2),
        "avg_actual_total_goals": round(avg_actual_total_goals, 2),
        "goals_bias": round(avg_pred_total_goals - avg_actual_total_goals, 2),
        "avg_predicted_shots_home": round(avg_pred_shots_home, 1),
        "avg_predicted_shots_away": round(avg_pred_shots_away, 1),
        "avg_predicted_sot_home": round(avg_pred_sot_home, 1),
        "avg_predicted_sot_away": round(avg_pred_sot_away, 1),
        "avg_predicted_ppda_home": round(avg_pred_ppda_home, 1),
        "avg_predicted_ppda_away": round(avg_pred_ppda_away, 1),
        "avg_predicted_possession_home": round(avg_pred_poss_home, 1),
        "avg_energy_home": round(avg_energy_home, 1),
        "avg_energy_away": round(avg_energy_away, 1),
        "by_stage": stage_accuracy,
        "pred_goals_distribution": dict(pred_goals_distribution),
        "actual_goals_distribution": dict(actual_goals_distribution),
    }
