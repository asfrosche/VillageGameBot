"""V5 Benchmark - Visualizations.

Generates PNG graphs for benchmark analysis.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def generate_all_graphs(
    match_metrics: list[dict],
    calibration: dict,
    tournament_summary: dict,
    output_dir: Path,
) -> list[str]:
    """Generate all benchmark visualization graphs.

    Returns list of generated PNG file paths.
    """
    if not HAS_MPL:
        return []

    graphs_dir = output_dir / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)

    generated = []

    valid = [m for m in match_metrics if "error" not in m]
    if not valid:
        return []

    path = _plot_xg_scatter(valid, graphs_dir)
    if path:
        generated.append(path)

    path = _plot_possession_distribution(valid, graphs_dir)
    if path:
        generated.append(path)

    path = _plot_calibration_curve(calibration, graphs_dir)
    if path:
        generated.append(path)

    path = _plot_error_distribution(valid, graphs_dir)
    if path:
        generated.append(path)

    path = _plot_winner_probability_distribution(valid, graphs_dir)
    if path:
        generated.append(path)

    path = _plot_ppda_scatter(valid, graphs_dir)
    if path:
        generated.append(path)

    path = _plot_goals_bias(tournament_summary, graphs_dir)
    if path:
        generated.append(path)

    path = _plot_stage_accuracy(tournament_summary, graphs_dir)
    if path:
        generated.append(path)

    return generated


def _plot_xg_scatter(valid: list[dict], out: Path) -> str | None:
    """Plot predicted vs actual xG scatter."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    pred_xg_home = [m["predicted_xg_home"] for m in valid]
    actual_xg_home = [m["actual_home_goals"] for m in valid]
    pred_xg_away = [m["predicted_xg_away"] for m in valid]
    actual_xg_away = [m["actual_away_goals"] for m in valid]

    ax = axes[0]
    ax.scatter(actual_xg_home, pred_xg_home, alpha=0.5, s=30, c="#2196F3", edgecolors="#1565C0", linewidth=0.5)
    max_val = max(max(actual_xg_home), max(pred_xg_home), 1) + 0.5
    ax.plot([0, max_val], [0, max_val], "r--", alpha=0.7, label="Perfect prediction")
    ax.set_xlabel("Actual Goals", fontsize=11)
    ax.set_ylabel("Predicted xG", fontsize=11)
    ax.set_title("Home Team: Predicted xG vs Actual Goals", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.scatter(actual_xg_away, pred_xg_away, alpha=0.5, s=30, c="#FF9800", edgecolors="#E65100", linewidth=0.5)
    max_val = max(max(actual_xg_away), max(pred_xg_away), 1) + 0.5
    ax.plot([0, max_val], [0, max_val], "r--", alpha=0.7, label="Perfect prediction")
    ax.set_xlabel("Actual Goals", fontsize=11)
    ax.set_ylabel("Predicted xG", fontsize=11)
    ax.set_title("Away Team: Predicted xG vs Actual Goals", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = str(out / "xg_scatter.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_possession_distribution(valid: list[dict], out: Path) -> str | None:
    """Plot predicted possession distribution."""
    fig, ax = plt.subplots(figsize=(10, 5))

    poss_home = [m["predicted_possession_home"] for m in valid]

    ax.hist(poss_home, bins=20, color="#4CAF50", alpha=0.7, edgecolor="#2E7D32", linewidth=0.8)
    ax.axvline(x=50, color="red", linestyle="--", alpha=0.7, label="50% line")
    ax.set_xlabel("Predicted Home Possession %", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("Distribution of Predicted Home Possession", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = str(out / "possession_distribution.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_calibration_curve(calibration: dict, out: Path) -> str | None:
    """Plot calibration curve."""
    curve = calibration.get("calibration_curve", [])
    if not curve:
        return None

    fig, ax = plt.subplots(figsize=(8, 8))

    pred_vals = [p["avg_predicted"] for p in curve]
    actual_vals = [p["avg_actual"] for p in curve]
    counts = [p["count"] for p in curve]

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
    path = str(out / "calibration_curve.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_error_distribution(valid: list[dict], out: Path) -> str | None:
    """Plot prediction error distribution."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    xg_errors = [m["total_xg_error"] for m in valid]
    ax = axes[0]
    ax.hist(xg_errors, bins=20, color="#F44336", alpha=0.7, edgecolor="#C62828", linewidth=0.8)
    ax.axvline(x=sum(xg_errors) / len(xg_errors), color="blue", linestyle="--",
               alpha=0.7, label=f"Mean: {sum(xg_errors)/len(xg_errors):.3f}")
    ax.set_xlabel("XG Error (|pred - actual|)", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("XG Prediction Error Distribution", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)

    scoreline_errors = [m["scoreline_error"] for m in valid]
    ax = axes[1]
    ax.hist(scoreline_errors, bins=range(0, max(scoreline_errors) + 2),
            color="#2196F3", alpha=0.7, edgecolor="#1565C0", linewidth=0.8)
    ax.axvline(x=sum(scoreline_errors) / len(scoreline_errors), color="red", linestyle="--",
               alpha=0.7, label=f"Mean: {sum(scoreline_errors)/len(scoreline_errors):.2f}")
    ax.set_xlabel("Scoreline Error (|pred - actual| per team)", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("Scoreline Prediction Error Distribution", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = str(out / "error_distribution.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_winner_probability_distribution(valid: list[dict], out: Path) -> str | None:
    """Plot distribution of predicted winner probabilities."""
    fig, ax = plt.subplots(figsize=(10, 5))

    fav_probs = []
    for m in valid:
        pred_xg_diff = m["predicted_xg_home"] - m["predicted_xg_away"]
        if pred_xg_diff > 0:
            fav_probs.append(1 / (1 + 2.5 * (-pred_xg_diff)))
        else:
            fav_probs.append(1 / (1 + 2.5 * pred_xg_diff))

    ax.hist(fav_probs, bins=20, color="#FF9800", alpha=0.7, edgecolor="#E65100", linewidth=0.8)
    ax.axvline(x=0.5, color="red", linestyle="--", alpha=0.7, label="50% (toss-up)")
    ax.set_xlabel("Favorite Win Probability", fontsize=11)
    ax.set_ylabel("Frequency", fontsize=11)
    ax.set_title("Distribution of Predicted Favorite Win Probability", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = str(out / "winner_probability_distribution.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_ppda_scatter(valid: list[dict], out: Path) -> str | None:
    """Plot predicted PPDA scatter."""
    fig, ax = plt.subplots(figsize=(10, 6))

    ppda_home = [m["predicted_ppda_home"] for m in valid]
    ppda_away = [m["predicted_ppda_away"] for m in valid]

    ax.scatter(ppda_home, ppda_away, alpha=0.5, s=30, c="#00BCD4", edgecolors="#006064", linewidth=0.5)
    ax.set_xlabel("Home PPDA (predicted)", fontsize=11)
    ax.set_ylabel("Away PPDA (predicted)", fontsize=11)
    ax.set_title("Predicted PPDA: Home vs Away", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)

    avg_home = sum(ppda_home) / len(ppda_home)
    avg_away = sum(ppda_away) / len(ppda_away)
    ax.axhline(y=avg_away, color="red", linestyle="--", alpha=0.5, label=f"Avg away: {avg_away:.1f}")
    ax.axvline(x=avg_home, color="blue", linestyle="--", alpha=0.5, label=f"Avg home: {avg_home:.1f}")
    ax.legend()

    plt.tight_layout()
    path = str(out / "ppda_scatter.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_goals_bias(summary: dict, out: Path) -> str | None:
    """Plot goals bias chart."""
    fig, ax = plt.subplots(figsize=(8, 5))

    avg_pred = summary.get("avg_predicted_total_goals", 0)
    avg_actual = summary.get("avg_actual_total_goals", 0)
    bias = summary.get("goals_bias", 0)

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
    path = str(out / "goals_bias.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_stage_accuracy(summary: dict, out: Path) -> str | None:
    """Plot accuracy by tournament stage."""
    by_stage = summary.get("by_stage", {})
    if not by_stage:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))

    stages = sorted(by_stage.keys(), key=lambda x: {
        "Group Stage": 0, "Round of 32": 1, "Round of 16": 2,
        "Quarterfinals": 3, "Semifinals": 4, "Third Place": 5, "Final": 6,
    }.get(x, 7))
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
    path = str(out / "stage_accuracy.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path
