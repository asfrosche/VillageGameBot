from __future__ import annotations

import math
from typing import Any

from ..models.market_comparison import ModelVsMarketComparison
from ..models.player_influence import TeamDependency
from ..services.simulation_report import MonteCarloResult, V4ReportData


def compute_confidence(
    mc: MonteCarloResult,
    v4_data: V4ReportData | None = None,
    dependency: TeamDependency | None = None,
    market_comparison: ModelVsMarketComparison | None = None,
    simulations: int = 100,
) -> dict[str, Any]:
    factors: list[tuple[str, float, float]] = []

    # 1. Simulation variance (lower variance = higher confidence)
    fav_win = max(mc.wins_a, mc.wins_b)
    underdog_win = min(mc.wins_a, mc.wins_b)
    total_decided = mc.wins_a + mc.wins_b
    if total_decided > 0:
        fav_ratio = fav_win / total_decided
        variance_score = 1.0 - abs(fav_ratio - 0.5) * 2
        variance_confidence = 1.0 - variance_score * 0.4
    else:
        variance_confidence = 0.5
    factors.append(("Simulation Variance", round(variance_confidence * 100, 1), 0.25))

    # 2. Score variance (big spread in common scores = less confidence)
    if mc.top_scores:
        top_score_share = mc.top_scores[0][1] / mc.total if mc.total > 0 else 0
        score_var = 1.0 - min(1.0, (1.0 - top_score_share) * 2)
        score_confidence = 0.5 + score_var * 0.5
    else:
        score_confidence = 0.5
    factors.append(("Score Consistency", round(score_confidence * 100, 1), 0.15))

    # 3. Tactical edge clarity
    if v4_data:
        xg_gap = abs(v4_data.final_xg_a - v4_data.final_xg_b)
        tactical_edge = min(1.0, xg_gap / 2.0)
        tactical_confidence = 0.5 + tactical_edge * 0.4
    else:
        tactical_confidence = 0.5
    factors.append(("Tactical Edge", round(tactical_confidence * 100, 1), 0.20))

    # 4. Player dependency (high dependency = lower confidence if star underperforms)
    if dependency:
        dep_score = dependency.attack_output_share / 100.0
        dep_confidence = 1.0 - min(1.0, max(0, (dep_score - 0.35) / 0.4))
    else:
        dep_confidence = 0.7
    factors.append(("Player Dependency", round(dep_confidence * 100, 1), 0.10))

    # 5. Market agreement (more agreement = higher confidence)
    if market_comparison and market_comparison.entries:
        fav_entry = max(market_comparison.entries, key=lambda e: e.model_prob)
        market_agreement = 1.0 - min(1.0, abs(fav_entry.edge) * 3)
        market_confidence = 0.4 + market_agreement * 0.5
    else:
        market_confidence = 0.6
    factors.append(("Market Agreement", round(market_confidence * 100, 1), 0.10))

    # 6. Simulation count (more sims = higher confidence)
    sim_factor = min(1.0, math.log10(max(simulations, 10)) / 4.0)
    sim_confidence = 0.3 + sim_factor * 0.6
    factors.append(("Sample Size", round(sim_confidence * 100, 1), 0.10))

    weighted_sum = sum(score * weight for _, score, weight in factors)
    total_weight = sum(weight for _, _, weight in factors)
    overall = round(weighted_sum / total_weight, 1)
    overall = max(0.0, min(100.0, overall))

    upset_prob = _compute_upset_probability(mc, v4_data)

    return {
        "score": overall,
        "level": _confidence_label(overall),
        "factors": [{"name": name, "score": score, "weight": weight} for name, score, weight in factors],
        "upset_probability": upset_prob,
        "volatility": _compute_volatility(mc),
    }


def _confidence_label(score: float) -> str:
    if score >= 85:
        return "Very High"
    if score >= 70:
        return "High"
    if score >= 50:
        return "Moderate"
    if score >= 30:
        return "Low"
    return "Very Low"


def _compute_upset_probability(
    mc: MonteCarloResult,
    v4_data: V4ReportData | None = None,
) -> float:
    if mc.total == 0:
        return 0.0

    if v4_data:
        xg_favored = v4_data.final_xg_a if v4_data.final_xg_a >= v4_data.final_xg_b else v4_data.final_xg_b
        xg_underdog = v4_data.final_xg_b if v4_data.final_xg_a >= v4_data.final_xg_b else v4_data.final_xg_a
        if xg_underdog > 0 and xg_favored > 0:
            upset_raw = mc.draws / mc.total * (xg_underdog / xg_favored)
            upset_results = min(mc.wins_a, mc.wins_b)
            upset_from_results = upset_results / mc.total if mc.total > 0 else 0
            return round(max(upset_raw, upset_from_results) * 100, 1)

    return round(min(mc.wins_a, mc.wins_b) / mc.total * 100, 1) if mc.total > 0 else 0.0


def _compute_volatility(mc: MonteCarloResult) -> float:
    if mc.total == 0 or not mc.top_scores:
        return 50.0

    unique_scores = len(mc.top_scores)
    fav_score_share = mc.top_scores[0][1] / mc.total if mc.total > 0 else 0
    volatility = (1.0 - fav_score_share) * 50 + (unique_scores / 10.0) * 30
    return round(min(100.0, volatility), 1)
