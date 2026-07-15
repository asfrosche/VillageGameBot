"""V5 Benchmark - Report Generator.

Generates Markdown reports for individual matches and the tournament summary.
"""
from __future__ import annotations

from pathlib import Path


def generate_match_reports(
    match_metrics: list[dict],
    sim_results: list[dict],
    real_matches: list[dict],
    output_dir: Path,
) -> None:
    """Generate individual match report files."""
    reports_dir = output_dir / "match_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    for i, m in enumerate(match_metrics):
        if "error" in m:
            continue

        home = m["home"]
        away = m["away"]
        safe_home = home.replace(" ", "_").replace("/", "_")
        safe_away = away.replace(" ", "_").replace("/", "_")
        filename = f"{i+1:03d}_{safe_home}_vs_{safe_away}.md"

        lines = []
        lines.append(f"# {home} vs {away}")
        lines.append("")
        lines.append(f"**Stage:** {m['stage']}  ")
        lines.append(f"**Date:** {m.get('date', 'N/A')}")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## V5 Prediction")
        lines.append("")

        pred_winner = m["predicted_winner"]
        pred_xg_diff = m["predicted_xg_home"] - m["predicted_xg_away"]
        if pred_xg_diff > 0:
            fav_prob = _xg_diff_to_win_prob(pred_xg_diff)
        elif pred_xg_diff < 0:
            fav_prob = 1 - _xg_diff_to_win_prob(pred_xg_diff)
        else:
            fav_prob = 0.5

        lines.append(f"**Predicted Winner:** {pred_winner}  ")
        lines.append(f"**Confidence:** {fav_prob:.1%}")
        lines.append("")
        lines.append(f"| Metric | {home} | {away} |")
        lines.append(f"|--------|------|------|")
        lines.append(f"| xG | {m['predicted_xg_home']:.2f} | {m['predicted_xg_away']:.2f} |")
        lines.append(f"| Possession % | {m['predicted_possession_home']:.1f} | {m['predicted_possession_away']:.1f} |")
        lines.append(f"| Shots | {m['predicted_shots_home']} | {m['predicted_shots_away']} |")
        lines.append(f"| Shots on Target | {m['predicted_sot_home']} | {m['predicted_sot_away']} |")
        lines.append(f"| Dangerous Attacks | {m['predicted_da_home']} | {m['predicted_da_away']} |")
        lines.append(f"| Corners | {m['predicted_corners_home']} | {m['predicted_corners_away']} |")
        lines.append(f"| Yellow Cards | {m['predicted_yellows_home']} | {m['predicted_yellows_away']} |")
        lines.append(f"| Red Cards | {m['predicted_reds_home']} | {m['predicted_reds_away']} |")
        lines.append(f"| PPDA | {m['predicted_ppda_home']:.1f} | {m['predicted_ppda_away']:.1f} |")
        lines.append(f"| Game Plan | {m['game_plan_home']} | {m['game_plan_away']} |")
        lines.append(f"| Avg Energy | {m['home_energy_avg']:.1f}% | {m['away_energy_avg']:.1f}% |")
        lines.append(f"| Most Likely Score | {m['most_likely_score']} | |")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Actual Match")
        lines.append("")

        actual_winner = m["actual_winner"]
        lines.append(f"**Actual Winner:** {actual_winner}  ")
        lines.append(f"**Score:** {m['actual_home_goals']} - {m['actual_away_goals']}")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Comparison")
        lines.append("")

        winner_icon = "Correct" if m["winner_correct"] else "Incorrect"
        winner_mark = "✅" if m["winner_correct"] else "❌"
        lines.append(f"| Metric | Status |")
        lines.append(f"|--------|--------|")
        lines.append(f"| Winner | {winner_mark} {winner_icon} |")
        lines.append(f"| Scoreline Error | {m['scoreline_error']} |")
        lines.append(f"| XG Home Error | {m['xg_home_error']:.3f} |")
        lines.append(f"| XG Away Error | {m['xg_away_error']:.3f} |")
        lines.append(f"| Total Goals Error | {m['total_goals_error']} |")
        lines.append("")

        if m.get("top_performers"):
            lines.append("---")
            lines.append("")
            lines.append("## Top Performers (Predicted)")
            lines.append("")
            for p in m["top_performers"]:
                lines.append(f"- **{p['name']}** ({p['team']}): Rating {p['rating']:.1f}, "
                           f"Goals {p['goals']}, Assists {p['assists']}, Shots {p['shots']}")
            lines.append("")

        with open(reports_dir / filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


def generate_tournament_report(
    tournament_summary: dict,
    calibration: dict,
    error_analysis: dict,
    match_metrics: list[dict],
    sim_results: list[dict],
    real_matches: list[dict],
    output_dir: Path,
) -> None:
    """Generate the main tournament benchmark report."""
    lines = []
    lines.append("# V5 Benchmark Report")
    lines.append("")
    lines.append("## FIFA World Cup 2026 - Simulator Evaluation")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 1. Overview")
    lines.append("")
    total = tournament_summary.get("total_matches", 0)
    correct = tournament_summary.get("correct_winners", 0)
    accuracy = tournament_summary.get("winner_accuracy", 0)
    lines.append(f"- **Total Matches Evaluated:** {total}")
    lines.append(f"- **Correct Winner Predictions:** {correct}")
    lines.append(f"- **Winner Prediction Accuracy:** {accuracy:.1%}")
    lines.append("")

    lines.append("## 2. Key Metrics")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Winner Accuracy | {accuracy:.1%} |")
    lines.append(f"| Avg XG Error | {tournament_summary.get('avg_total_xg_error', 0):.3f} |")
    lines.append(f"| Avg Scoreline Error | {tournament_summary.get('avg_scoreline_error', 0):.3f} |")
    lines.append(f"| Avg Predicted Goals/Match | {tournament_summary.get('avg_predicted_total_goals', 0):.2f} |")
    lines.append(f"| Avg Actual Goals/Match | {tournament_summary.get('avg_actual_total_goals', 0):.2f} |")
    lines.append(f"| Goals Bias | {tournament_summary.get('goals_bias', 0):+.2f} |")
    lines.append(f"| Brier Score | {calibration.get('brier_score', 0):.4f} |")
    lines.append(f"| Log Loss | {calibration.get('log_loss', 0):.4f} |")
    lines.append(f"| Reliability | {calibration.get('reliability', 0):.4f} |")
    lines.append(f"| Avg Confidence | {calibration.get('avg_confidence', 0):.3f} |")
    lines.append("")

    lines.append("## 3. Accuracy by Stage")
    lines.append("")
    by_stage = tournament_summary.get("by_stage", {})
    lines.append("| Stage | Correct | Total | Accuracy |")
    lines.append("|-------|---------|-------|----------|")
    for cat in ["Group Stage", "Round of 32", "Round of 16", "Quarterfinals", "Semifinals", "Third Place", "Final"]:
        if cat in by_stage:
            s = by_stage[cat]
            lines.append(f"| {cat} | {s['correct']} | {s['total']} | {s['accuracy']:.1%} |")
    lines.append("")

    lines.append("## 4. Calibration")
    lines.append("")
    lines.append(f"- **Brier Score:** {calibration.get('brier_score', 0):.4f} (lower is better, 0 = perfect)")
    lines.append(f"- **Log Loss:** {calibration.get('log_loss', 0):.4f} (lower is better)")
    lines.append(f"- **Reliability:** {calibration.get('reliability', 0):.4f} (lower is better, 0 = perfect)")
    lines.append(f"- **Average Confidence:** {calibration.get('avg_confidence', 0):.3f}")
    lines.append("")

    curve = calibration.get("calibration_curve", [])
    if curve:
        lines.append("### Calibration Curve Data")
        lines.append("")
        lines.append("| Bin | Predicted | Actual | Count | Gap |")
        lines.append("|-----|-----------|--------|-------|-----|")
        for p in curve:
            lines.append(f"| {p['bin_start']:.1f}-{p['bin_end']:.1f} | {p['avg_predicted']:.3f} | {p['avg_actual']:.3f} | {p['count']} | {p['gap']:.3f} |")
        lines.append("")

    lines.append("## 5. Error Analysis")
    lines.append("")
    findings = error_analysis.get("findings", [])
    for finding in findings:
        severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢", "info": "ℹ️"}.get(finding["severity"], "")
        lines.append(f"### {severity_icon} {finding['category']}")
        lines.append("")
        lines.append(f"{finding['finding']}")
        lines.append("")

        if finding["category"] == "XG Error by Stage":
            by_stage = finding.get("by_stage", {})
            lines.append("| Stage | Avg XG Error | Matches |")
            lines.append("|-------|-------------|---------|")
            for cat, data in by_stage.items():
                lines.append(f"| {cat} | {data['avg_xg_error']:.3f} | {data['count']} |")
            lines.append("")

        if finding["category"] == "Upset Prediction":
            examples = finding.get("examples", [])
            if examples:
                lines.append("**Examples:**")
                for ex in examples:
                    lines.append(f"- {ex['home']} vs {ex['away']}: Predicted {ex['predicted_winner']}, "
                               f"Actual {ex['actual_winner']} (XG diff: {ex['xg_diff']})")
                lines.append("")

        if finding["category"] == "Scoreline Distribution":
            lines.append("**Most Predicted Scorelines:**")
            for score, count in finding.get("top_predicted", []):
                lines.append(f"- {score}: {count} times")
            lines.append("")
            lines.append("**Most Actual Scorelines:**")
            for score, count in finding.get("top_actual", []):
                lines.append(f"- {score}: {count} times")
            lines.append("")

    lines.append("## 6. Best and Worst Predictions")
    lines.append("")

    valid = [m for m in match_metrics if "error" not in m]

    best_by_xg = sorted(valid, key=lambda m: m["total_xg_error"])[:5]
    lines.append("### Best XG Predictions")
    lines.append("")
    lines.append("| Match | Pred XG | Actual Score | XG Error |")
    lines.append("|-------|---------|--------------|----------|")
    for m in best_by_xg:
        lines.append(f"| {m['home']} vs {m['away']} | {m['predicted_xg_home']:.2f}-{m['predicted_xg_away']:.2f} | "
                    f"{m['actual_home_goals']}-{m['actual_away_goals']} | {m['total_xg_error']:.3f} |")
    lines.append("")

    worst_by_xg = sorted(valid, key=lambda m: -m["total_xg_error"])[:5]
    lines.append("### Worst XG Predictions")
    lines.append("")
    lines.append("| Match | Pred XG | Actual Score | XG Error |")
    lines.append("|-------|---------|--------------|----------|")
    for m in worst_by_xg:
        lines.append(f"| {m['home']} vs {m['away']} | {m['predicted_xg_home']:.2f}-{m['predicted_xg_away']:.2f} | "
                    f"{m['actual_home_goals']}-{m['actual_away_goals']} | {m['total_xg_error']:.3f} |")
    lines.append("")

    best_scoreline = sorted(valid, key=lambda m: m["scoreline_error"])[:5]
    lines.append("### Best Scoreline Predictions")
    lines.append("")
    lines.append("| Match | Predicted | Actual | Error |")
    lines.append("|-------|-----------|--------|-------|")
    for m in best_scoreline:
        lines.append(f"| {m['home']} vs {m['away']} | {m['predicted_home_goals']}-{m['predicted_away_goals']} | "
                    f"{m['actual_home_goals']}-{m['actual_away_goals']} | {m['scoreline_error']} |")
    lines.append("")

    lines.append("## 7. V6 Improvement Areas")
    lines.append("")
    lines.append("Based on this benchmark, the following areas would most benefit from improvement in V6:")
    lines.append("")

    if tournament_summary.get("goals_bias", 0) > 0.2:
        lines.append("- **Goal Prediction Calibration:** V5 overestimates goals. Adjust xG lambda calculations.")
    elif tournament_summary.get("goals_bias", 0) < -0.2:
        lines.append("- **Goal Prediction Calibration:** V5 underestimates goals. Adjust xG lambda calculations.")

    if calibration.get("brier_score", 0) > 0.3:
        lines.append("- **Probability Calibration:** Brier score indicates poorly calibrated probabilities. Improve win probability model.")

    if calibration.get("reliability", 0) > 0.1:
        lines.append("- **Reliability:** Model is not well calibrated. Consider adjusting the xG-to-win-probability mapping.")

    for finding in findings:
        if finding["severity"] == "high":
            lines.append(f"- **{finding['category']}:** {finding['finding']}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*This report was generated automatically by the V5 Benchmark Framework.*")
    lines.append("*It serves as the official baseline for comparing future simulator versions.*")

    with open(output_dir / "tournament_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _xg_diff_to_win_prob(xg_diff: float) -> float:
    """Convert xG difference to win probability using logistic function."""
    import math
    k = 2.5
    return 1.0 / (1.0 + math.exp(-k * xg_diff))
