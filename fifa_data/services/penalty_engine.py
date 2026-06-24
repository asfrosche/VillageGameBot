from __future__ import annotations

import random

from ..models.player import Player
from ..models.squad import Squad


class PenaltyEngine:
    def simulate_penalty_shootout(
        self,
        squad_a: Squad,
        squad_b: Squad,
        team_a: str,
        team_b: str,
        a_go_first: bool = True,
    ) -> tuple[list[str], list[str], str]:
        takers_a = self._select_penalty_takers(squad_a)
        takers_b = self._select_penalty_takers(squad_b)
        scores_a: list[str] = []
        scores_b: list[str] = []
        max_rounds = 5
        sudden_death = False

        a_takes_first = a_go_first

        for round_num in range(10):
            if round_num >= max_rounds and not sudden_death:
                if scores_a.count("✓") != scores_b.count("✓"):
                    break
                sudden_death = True

            if round_num < len(takers_a) and (sudden_death or round_num < max_rounds):
                taker_a = takers_a[round_num % len(takers_a)]
                scored_a = self._attempt_penalty(taker_a, squad_a)
                scores_a.append("✓" if scored_a else "✗")
            else:
                scores_a.append("✗")

            if round_num < len(takers_b) and (sudden_death or round_num < max_rounds):
                taker_b = takers_b[round_num % len(takers_b)]
                scored_b = self._attempt_penalty(taker_b, squad_b)
                scores_b.append("✓" if scored_b else "✗")
            else:
                scores_b.append("✗")

            if sudden_death and scores_a[-1] != scores_b[-1]:
                break

        a_total = scores_a.count("✓")
        b_total = scores_b.count("✓")
        winner = team_a if a_total > b_total else team_b
        return scores_a, scores_b, winner

    def _select_penalty_takers(self, squad: Squad) -> list[Player]:
        takers = sorted(
            squad.current_starting_xi,
            key=lambda p: (
                p.attributes.get("penalties", 50.0)
                + p.attributes.get("finishing", 50.0)
                + p.attributes.get("composure", 50.0)
            ),
            reverse=True,
        )
        return takers[:5] if len(takers) >= 5 else takers + takers[:5 - len(takers)]

    def _attempt_penalty(self, taker: Player, squad: Squad) -> bool:
        finishing = taker.attributes.get("finishing", 50.0)
        composure = taker.attributes.get("composure", 50.0)
        leadership = taker.attributes.get("leadership", 50.0)
        experience = taker.attributes.get("experience", 50.0)
        penalties = taker.attributes.get("penalties", 50.0)

        gk = self._get_goalkeeper(squad)
        gk_reflexes = gk.attributes.get("reflexes", 50.0) if gk else 50.0
        gk_positioning = gk.attributes.get("positioning", 50.0) if gk else 50.0
        gk_penalties = gk.attributes.get("penalty_save", 50.0) if gk else 50.0

        taker_score = (
            finishing * 0.25
            + composure * 0.25
            + leadership * 0.10
            + experience * 0.10
            + penalties * 0.30
        )
        gk_score = (
            gk_reflexes * 0.30
            + gk_positioning * 0.25
            + gk_penalties * 0.45
        )

        success_prob = (taker_score / max(gk_score, 1.0)) * 0.35
        success_prob = max(0.30, min(0.92, success_prob))
        return random.random() < success_prob

    def _get_goalkeeper(self, squad: Squad) -> Player | None:
        for player in squad.current_starting_xi:
            if "GK" in player.normalized_positions() or "GOALKEEPER" in player.normalized_positions():
                return player
        return None
