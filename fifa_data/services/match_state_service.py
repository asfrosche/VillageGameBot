from __future__ import annotations

import random

from ..models.match_state import (
    EXTRA_TIME_PHASES,
    PHASE_ORDER,
    MatchPhase,
    MatchState,
    ScorelineState,
)
from ..models.player import Player
from ..models.player_match_state import PlayerMatchState
from ..models.squad import Squad
from ..models.tactical_state import ManagerProfile


class MatchStateService:
    def initialize_match_state(
        self,
        team_a: str,
        team_b: str,
        squad_a: Squad,
        squad_b: Squad,
    ) -> MatchState:
        state = MatchState(
            team_a=team_a,
            team_b=team_b,
        )

        for player in squad_a.current_starting_xi:
            from ..models.team_strength import role_for_player
            role = role_for_player(player)
            state.team_a_players[player.name] = PlayerMatchState(
                player_name=player.name,
                country=team_a,
                position=role,
            )

        for player in squad_b.current_starting_xi:
            from ..models.team_strength import role_for_player
            role = role_for_player(player)
            state.team_b_players[player.name] = PlayerMatchState(
                player_name=player.name,
                country=team_b,
                position=role,
            )

        return state

    def advance_phase(
        self,
        state: MatchState,
        is_extra_time: bool = False,
    ) -> None:
        current = state.current_phase

        if is_extra_time:
            phases = EXTRA_TIME_PHASES
        else:
            phases = PHASE_ORDER

        try:
            idx = phases.index(current)
            if idx < len(phases) - 1:
                state.current_phase = phases[idx + 1]
            else:
                state.current_phase = phases[-1]
        except ValueError:
            state.current_phase = phases[0]

        state.record_phase()

    def determine_phase_minutes(self, phase: MatchPhase) -> int:
        if phase in (MatchPhase.EXTRA_TIME_FIRST, MatchPhase.EXTRA_TIME_SECOND):
            return 15
        return 15

    def get_scoreline_state(self, team: str, state: MatchState) -> str:
        return state.scoreline.description_for_team(team, state.team_a, state.team_b)

    def get_relative_strength(self, lambda_a: float, lambda_b: float) -> tuple[float, float]:
        total = lambda_a + lambda_b
        if total <= 0:
            return (0.5, 0.5)
        return (lambda_a / total, lambda_b / total)

    def evaluate_manager_reaction(
        self,
        manager: ManagerProfile | None,
        scoreline_state: str,
        minute: int,
        current_game_plan: str,
    ) -> str | None:
        if manager is None:
            if scoreline_state == "trailing_2+" and minute >= 50:
                if current_game_plan != "attacking":
                    return "attacking"
            if scoreline_state == "trailing" and minute >= 55:
                if current_game_plan != "attacking":
                    return "attacking"
            if scoreline_state == "winning" and minute >= 70:
                if current_game_plan != "defensive":
                    return "counter" if current_game_plan == "balanced" else "balanced"
            return None

        risk = manager.risk_tolerance
        flex = manager.tactical_flexibility

        if scoreline_state == "trailing_2+" and minute >= 50:
            return "attacking"

        if scoreline_state == "trailing":
            if minute >= 55 and current_game_plan != "attacking":
                if risk > 65 or minute >= 70:
                    return "attacking"
                if risk > 50 and minute >= 60:
                    return "attacking"

        elif scoreline_state == "winning":
            if minute >= 75 and current_game_plan != "counter":
                if manager.defensive_discipline > 65:
                    return "counter" if current_game_plan != "low_block" else "low_block"
            if minute >= 80 and current_game_plan != "low_block":
                if manager.defensive_discipline > 70:
                    return "low_block"

        elif scoreline_state == "drawing":
            if minute >= 75 and risk > 65:
                if current_game_plan == "balanced":
                    return "attacking"

        if flex < 40 and current_game_plan != "balanced":
            return None

        return None

    def calculate_possession(
        self,
        lambda_a: float,
        lambda_b: float,
        game_plan_a: str,
        game_plan_b: str,
        red_card_a: int,
        red_card_b: int,
    ) -> float:
        plan_possession_mod = {
            "high_press": 0.52,
            "attacking": 0.54,
            "balanced": 0.50,
            "counter": 0.44,
            "low_block": 0.38,
            "park_the_bus": 0.32,
        }

        base_a = plan_possession_mod.get(game_plan_a, 0.50)
        base_b = plan_possession_mod.get(game_plan_b, 0.50)

        strength_factor = lambda_a / max(lambda_a + lambda_b, 0.01)
        plan_factor = base_a / max(base_a + base_b, 0.01)
        possession_a = 0.4 * strength_factor + 0.6 * plan_factor
        possession_a *= (1.0 - red_card_a * 0.10) / (1.0 - red_card_b * 0.10) if red_card_b == 0 else (1.0 - red_card_a * 0.10)
        possession_a = max(0.20, min(0.80, possession_a))
        return possession_a
