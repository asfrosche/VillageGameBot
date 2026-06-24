from __future__ import annotations

import random

from numpy.random import poisson

from .base_engine import MatchEngine


class V1EloMatchEngine(MatchEngine):
    def __init__(
        self,
        team_metrics: dict[str, dict[str, float]],
        base_goals: float = 1.1,
        upset_factor_min: float = 0.4,
        upset_factor_max: float = 1.6,
        upset_factor_slope: float = 800.0,
        minimum_lambda: float = 0.05,
        extra_time_lambda_scale: float = 0.3,
        tiebreaker_base_probability: float = 0.50,
        tiebreaker_delta_scale: float = 0.0005,
    ) -> None:
        self.team_metrics = team_metrics
        self.base_goals = base_goals
        self.upset_factor_min = upset_factor_min
        self.upset_factor_max = upset_factor_max
        self.upset_factor_slope = upset_factor_slope
        self.minimum_lambda = minimum_lambda
        self.extra_time_lambda_scale = extra_time_lambda_scale
        self.tiebreaker_base_probability = tiebreaker_base_probability
        self.tiebreaker_delta_scale = tiebreaker_delta_scale

    def _rating(self, team: str) -> float:
        if team not in self.team_metrics:
            raise KeyError(f"Unknown team: {team}")
        metrics = self.team_metrics[team]
        return (float(metrics.get("ELO", 1500)) + float(metrics.get("PELE", 1500))) / 2.0

    def get_team_ratings(self, team: str) -> dict[str, float]:
        if team not in self.team_metrics:
            raise KeyError(f"Unknown team: {team}")
        metrics = self.team_metrics[team]
        elo = float(metrics.get("ELO", 1500))
        pele = float(metrics.get("PELE", 1500))
        return {"elo": elo, "pele": pele, "combined": (elo + pele) / 2.0}

    def simulate_match(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
    ) -> tuple[int, int]:
        r1 = self._rating(team1)
        r2 = self._rating(team2)
        raw_delta = r1 - r2

        upset_factor = max(
            self.upset_factor_min,
            min(
                self.upset_factor_max,
                1.0 + (raw_delta / self.upset_factor_slope),
            ),
        )
        lam1 = self.base_goals * upset_factor
        lam2 = max(self.minimum_lambda, self.base_goals * max(0.20, 1.5 - 0.5 * upset_factor))
        g1 = poisson(max(self.minimum_lambda, lam1))
        g2 = poisson(max(self.minimum_lambda, lam2))
        if not can_draw and g1 == g2:
            g1_et = poisson(lam1 * self.extra_time_lambda_scale)
            g2_et = poisson(lam2 * self.extra_time_lambda_scale)
            if g1_et != g2_et:
                g1 += g1_et
                g2 += g2_et
            else:
                if random.random() < (
                    self.tiebreaker_base_probability + (raw_delta * self.tiebreaker_delta_scale)
                ):
                    g1 += 1
                else:
                    g2 += 1
        return int(g1), int(g2)
