from __future__ import annotations

import random
from pathlib import Path

from numpy.random import poisson

from ..models.squad import Squad
from ..models.tactical_state import TacticalReport
from ..models.team_strength import TeamStrength
from ..services.tactical_analysis import (
    compute_tactical_matchup,
    format_tactical_report,
)
from ..services.v2_data_loader import load_v2_squads
from .base_engine import MatchEngine
from .v3_dynamic_engine import V3DynamicEngine


class V4TacticalEngine(MatchEngine):
    def __init__(
        self,
        data_dir: str | Path | None = None,
        squads: dict[str, Squad] | None = None,
        team_metrics: dict[str, dict[str, float]] | None = None,
        tournament_form: dict[str, float] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else None
        resolved = self.data_dir or Path(__file__).resolve().parents[1]
        self.squads = squads if squads is not None else load_v2_squads(resolved)
        self._v3 = V3DynamicEngine(data_dir=resolved, squads=self.squads, team_metrics=team_metrics, tournament_form=tournament_form)

        self.minimum_lambda = self._v3.minimum_lambda
        self.extra_time_lambda_scale = self._v3.extra_time_lambda_scale
        self.tiebreaker_base_probability = self._v3.tiebreaker_base_probability
        self.tiebreaker_delta_scale = self._v3.tiebreaker_delta_scale

        self._match_number = 0
        self.last_match_debug = ""
        self.last_tactical_report: TacticalReport | None = None

    def simulate_match(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
        context: str | None = None,
    ) -> tuple[int, int]:
        score, _ = self.simulate_match_debug(team1, team2, can_draw, context)
        return score

    def simulate_match_debug(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
        context: str | None = None,
    ) -> tuple[tuple[int, int], str]:
        self._match_number += 1
        is_knockout = not can_draw

        # Determine match context
        if context is None:
            context = "knockout" if is_knockout else "group"

        # Get V3 strength and base expected goals
        strength1 = self._v3.get_team_strength(team1, is_knockout)
        strength2 = self._v3.get_team_strength(team2, is_knockout)
        base_lambda1, base_lambda2 = self._v3.expected_goals(strength1, strength2)

        # Apply V4 tactical adjustments
        squad1 = self.squads.get(team1)
        squad2 = self.squads.get(team2)
        report = compute_tactical_matchup(
            team1, team2,
            base_lambda1, base_lambda2,
            squad1, squad2,
            context=context,
        )
        self.last_tactical_report = report

        lambda1 = report.final_xg_a
        lambda2 = report.final_xg_b

        # Poisson simulation with V4-adjusted xG
        g1 = poisson(max(self.minimum_lambda, lambda1))
        g2 = poisson(max(self.minimum_lambda, lambda2))

        extra_time_used = False
        penalties_used = False
        if not can_draw and g1 == g2:
            raw_diff = lambda1 - lambda2
            g1_et = poisson(lambda1 * self.extra_time_lambda_scale)
            g2_et = poisson(lambda2 * self.extra_time_lambda_scale)
            if g1_et != g2_et:
                g1 += g1_et
                g2 += g2_et
                extra_time_used = True
            else:
                leader_prob = self.tiebreaker_base_probability + (raw_diff * self.tiebreaker_delta_scale * 10)
                dyn1 = self._v3.get_dynamic_state(team1, is_knockout=False)
                dyn2 = self._v3.get_dynamic_state(team2, is_knockout=False)
                leader_prob += (dyn1.leadership.value - dyn2.leadership.value) * 0.5
                leader_prob += (dyn1.experience.value - dyn2.experience.value) * 0.3
                nat1 = self._v3.national_modifiers.get(team1, 0.0)
                nat2 = self._v3.national_modifiers.get(team2, 0.0)
                leader_prob += (nat1 - nat2) * 2.0
                leader_prob = max(0.05, min(0.95, leader_prob))
                if random.random() < leader_prob:
                    g1 += 1
                else:
                    g2 += 1
                penalties_used = True

        score = (int(g1), int(g2))

        # Update V3 tracking services
        self._v3.continuity_service.record_lineup(team1, [p.name for p in squad1.current_starting_xi])
        self._v3.continuity_service.record_lineup(team2, [p.name for p in squad2.current_starting_xi])
        self._v3.momentum_service.record_result(team1, int(g1), int(g2), is_real=False)
        self._v3.momentum_service.record_result(team2, int(g2), int(g1), is_real=False)

        self.last_match_debug = self._format_v4_debug(
            team1, team2, strength1, strength2,
            (base_lambda1, base_lambda2),
            report, score,
            is_knockout, extra_time_used, penalties_used,
        )
        return score, self.last_match_debug

    def get_team_strength(self, team: str) -> TeamStrength:
        return self._v3.get_team_strength(team)

    def expected_goals(
        self,
        team1: str,
        team2: str,
        context: str = "group",
    ) -> tuple[float, float]:
        strength1 = self._v3.get_team_strength(team1)
        strength2 = self._v3.get_team_strength(team2)
        base_lambda1, base_lambda2 = self._v3.expected_goals(strength1, strength2)
        squad1 = self.squads.get(team1)
        squad2 = self.squads.get(team2)
        report = compute_tactical_matchup(
            team1, team2,
            base_lambda1, base_lambda2,
            squad1, squad2,
            context=context,
        )
        return report.final_xg_a, report.final_xg_b

    def notify_match(self, team1: str, team2: str, goals1: int, goals2: int, is_real: bool) -> None:
        self._v3.notify_match(team1, team2, goals1, goals2, is_real)

    def _format_v4_debug(
        self,
        team1: str,
        team2: str,
        strength1: TeamStrength,
        strength2: TeamStrength,
        base_xg: tuple[float, float],
        report: TacticalReport,
        score: tuple[int, int],
        is_knockout: bool = False,
        extra_time_used: bool = False,
        penalties_used: bool = False,
    ) -> str:
        v3_debug = self._v3.format_match_debug(
            team1, team2, strength1, strength2,
            self._v3.get_dynamic_state(team1, is_knockout, extra_time_used, penalties_used),
            self._v3.get_dynamic_state(team2, is_knockout, extra_time_used, penalties_used),
            base_xg, score,
        )
        lines = [
            v3_debug,
            "",
            "=" * 50,
            "V4 TACTICAL INTELLIGENCE",
            "=" * 50,
            "",
        ]
        lines.append(format_tactical_report(report))
        lines.append("")
        lines.append(f"Final Score: {score[0]}-{score[1]}")
        return "\n".join(lines)
