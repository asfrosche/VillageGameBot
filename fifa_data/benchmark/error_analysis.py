"""V5 Benchmark - Error Analysis.

Identifies systematic weaknesses in V5 predictions.
"""
from __future__ import annotations

from collections import defaultdict


def analyze_systematic_errors(
    match_metrics: list[dict],
    real_matches: list[dict],
) -> dict:
    """Analyze systematic weaknesses in V5 predictions.

    Returns dict with error categories and specific findings.
    """
    valid = [m for m in match_metrics if "error" not in m]
    if not valid:
        return {"findings": [], "summary": "No valid matches to analyze."}

    findings = []

    total_goals_pred = sum(m["predicted_total_goals"] for m in valid)
    total_goals_actual = sum(m["actual_total_goals"] for m in valid)
    avg_pred = total_goals_pred / len(valid)
    avg_actual = total_goals_actual / len(valid)
    goals_bias = avg_pred - avg_actual

    if abs(goals_bias) > 0.2:
        direction = "overestimates" if goals_bias > 0 else "underestimates"
        findings.append({
            "category": "Goal Prediction",
            "finding": f"V5 {direction} total goals by {abs(goals_bias):.2f} per match",
            "avg_predicted": round(avg_pred, 2),
            "avg_actual": round(avg_actual, 2),
            "bias": round(goals_bias, 2),
            "severity": "high" if abs(goals_bias) > 0.5 else "medium",
        })

    pred_high_scoring = sum(1 for m in valid if m["predicted_total_goals"] >= 3)
    actual_high_scoring = sum(1 for m in valid if m["actual_total_goals"] >= 3)
    high_scoring_ratio_pred = pred_high_scoring / len(valid)
    high_scoring_ratio_actual = actual_high_scoring / len(valid)

    if abs(high_scoring_ratio_pred - high_scoring_ratio_actual) > 0.1:
        findings.append({
            "category": "High-Scoring Matches",
            "finding": f"V5 predicts {high_scoring_ratio_pred:.1%} high-scoring matches vs {high_scoring_ratio_actual:.1%} actual",
            "predicted_ratio": round(high_scoring_ratio_pred, 3),
            "actual_ratio": round(high_scoring_ratio_actual, 3),
            "severity": "medium",
        })

    home_wins_pred = sum(1 for m in valid if m["predicted_winner"] == m["home"])
    home_wins_actual = sum(1 for m in valid if m["actual_winner"] == m["home"])
    home_ratio_pred = home_wins_pred / len(valid)
    home_ratio_actual = home_wins_actual / len(valid)

    if abs(home_ratio_pred - home_ratio_actual) > 0.05:
        direction = "overestimates" if home_ratio_pred > home_ratio_actual else "underestimates"
        findings.append({
            "category": "Home Advantage",
            "finding": f"V5 {direction} home wins: {home_ratio_pred:.1%} predicted vs {home_ratio_actual:.1%} actual",
            "predicted_ratio": round(home_ratio_pred, 3),
            "actual_ratio": round(home_ratio_actual, 3),
            "severity": "medium",
        })

    draw_pred = sum(1 for m in valid if m["predicted_winner"] == "Draw")
    draw_actual = sum(1 for m in valid if m["actual_winner"] == "Draw")
    draw_ratio_pred = draw_pred / len(valid)
    draw_ratio_actual = draw_actual / len(valid)

    if abs(draw_ratio_pred - draw_ratio_actual) > 0.05:
        findings.append({
            "category": "Draw Prediction",
            "finding": f"V5 predicts {draw_ratio_pred:.1%} draws vs {draw_ratio_actual:.1%} actual",
            "predicted_ratio": round(draw_ratio_pred, 3),
            "actual_ratio": round(draw_ratio_actual, 3),
            "severity": "medium",
        })

    favorites_correct = 0
    favorites_total = 0
    underdogs_correct = 0
    underdogs_total = 0
    for m in valid:
        pred_xg_diff = m["predicted_xg_home"] - m["predicted_xg_away"]
        if abs(pred_xg_diff) > 0.3:
            if pred_xg_diff > 0:
                favorites_total += 1
                if m["winner_correct"] and m["actual_winner"] == m["home"]:
                    favorites_correct += 1
            else:
                favorites_total += 1
                if m["winner_correct"] and m["actual_winner"] == m["away"]:
                    favorites_correct += 1

    if favorites_total > 0:
        fav_accuracy = favorites_correct / favorites_total
        findings.append({
            "category": "Favorite Accuracy",
            "finding": f"V5 correctly predicts {fav_accuracy:.1%} of clear favorites ({favorites_correct}/{favorites_total})",
            "accuracy": round(fav_accuracy, 3),
            "total_favorites": favorites_total,
            "severity": "low" if fav_accuracy > 0.6 else "medium",
        })

    upset_matches = []
    for m in valid:
        pred_fav = m["home"] if m["predicted_xg_home"] > m["predicted_xg_away"] else m["away"]
        if m["actual_winner"] != "Draw" and m["actual_winner"] != pred_fav:
            upset_matches.append({
                "home": m["home"],
                "away": m["away"],
                "predicted_winner": m["predicted_winner"],
                "actual_winner": m["actual_winner"],
                "xg_diff": round(m["predicted_xg_home"] - m["predicted_xg_away"], 2),
                "stage": m["stage_category"],
            })

    if upset_matches:
        findings.append({
            "category": "Upset Prediction",
            "finding": f"V5 missed {len(upset_matches)} upsets",
            "count": len(upset_matches),
            "examples": upset_matches[:5],
            "severity": "high" if len(upset_matches) > len(valid) * 0.2 else "medium",
        })

    xg_errors_by_stage = defaultdict(list)
    for m in valid:
        cat = m["stage_category"]
        xg_errors_by_stage[cat].append(m["total_xg_error"])

    stage_xg_analysis = {}
    for cat, errors in xg_errors_by_stage.items():
        avg_error = sum(errors) / len(errors)
        stage_xg_analysis[cat] = {
            "avg_xg_error": round(avg_error, 3),
            "count": len(errors),
        }

    findings.append({
        "category": "XG Error by Stage",
        "finding": "XG prediction accuracy varies by tournament stage",
        "by_stage": stage_xg_analysis,
        "severity": "info",
    })

    xg_bias_by_side = {
        "home": sum(m["predicted_xg_home"] - m["actual_home_goals"] for m in valid) / len(valid),
        "away": sum(m["predicted_xg_away"] - m["actual_away_goals"] for m in valid) / len(valid),
    }

    for side, bias in xg_bias_by_side.items():
        if abs(bias) > 0.15:
            direction = "overestimates" if bias > 0 else "underestimates"
            findings.append({
                "category": f"XG Bias ({side})",
                "finding": f"V5 {direction} {side} team xG by {abs(bias):.3f} on average",
                "bias": round(bias, 3),
                "severity": "medium",
            })

    most_common_pred = defaultdict(int)
    most_common_actual = defaultdict(int)
    for m in valid:
        most_common_pred[m["most_likely_score"]] += 1
        actual_score = f"{m['actual_home_goals']}-{m['actual_away_goals']}"
        most_common_actual[actual_score] += 1

    top_pred_scores = sorted(most_common_pred.items(), key=lambda x: -x[1])[:5]
    top_actual_scores = sorted(most_common_actual.items(), key=lambda x: -x[1])[:5]

    findings.append({
        "category": "Scoreline Distribution",
        "finding": "Most predicted vs most actual scorelines",
        "top_predicted": top_pred_scores,
        "top_actual": top_actual_scores,
        "severity": "info",
    })

    return {
        "findings": findings,
        "total_matches": len(valid),
        "summary": f"Analyzed {len(valid)} matches. Found {len(findings)} systematic patterns.",
    }
