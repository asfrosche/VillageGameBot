from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from ..models.match_event import EventType, MatchEvent
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
from ..models.team_strength import TeamStrength
from ..models.tactical_state import ManagerProfile
from ..services.card_service import CardService
from ..services.event_engine import EventEngine
from ..services.game_script_service import GameScriptService
from ..services.manager_service import get_manager, manager_game_plan_modifier
from ..services.match_momentum_service import MatchMomentumService
from ..services.match_state_service import MatchStateService
from ..services.penalty_engine import PenaltyEngine
from ..services.substitution_manager import FatigueService, SubstitutionService
from ..services.tactical_analysis import compute_tactical_matchup
from ..services.v2_data_loader import load_v2_squads
from .base_engine import MatchEngine
from .v4_tactical_engine import V4TacticalEngine


class V5MatchStateEngine(MatchEngine):
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
        self._v4 = V4TacticalEngine(data_dir=resolved, squads=self.squads, team_metrics=team_metrics, tournament_form=tournament_form)

        self.minimum_lambda = self._v4.minimum_lambda
        self.max_xg = 4.0
        self.extra_time_lambda_scale = self._v4.extra_time_lambda_scale
        self.tiebreaker_base_probability = self._v4.tiebreaker_base_probability
        self.tiebreaker_delta_scale = self._v4.tiebreaker_delta_scale

        self.fatigue_service = FatigueService()
        self.card_service = CardService()
        self.momentum_service = MatchMomentumService()
        self.penalty_engine = PenaltyEngine()
        self.match_state_service = MatchStateService()
        self.substitution_service = SubstitutionService(self.fatigue_service)
        self.event_engine = EventEngine(self.card_service, self.momentum_service)
        self.game_script_service = GameScriptService()

        self._match_number = 0
        self.last_match_debug = ""
        self.last_match_state: MatchState | None = None
        self.last_match_events: list[MatchEvent] = []

    def simulate_match(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
        context: str | None = None,
    ) -> tuple[int, int]:
        result, _, _ = self._simulate_full(team1, team2, can_draw, context)
        return result

    def simulate_match_debug(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
        context: str | None = None,
    ) -> tuple[tuple[int, int], str]:
        result, state, _ = self._simulate_full(team1, team2, can_draw, context)
        return result, self._format_v5_debug(team1, team2, state)

    def simulate_match_detailed(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
        context: str | None = None,
    ) -> tuple[tuple[int, int], MatchState, list[MatchEvent]]:
        return self._simulate_full(team1, team2, can_draw, context)

    def _simulate_full(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
        context: str | None = None,
    ) -> tuple[tuple[int, int], MatchState, list[MatchEvent]]:
        self._match_number += 1
        is_knockout = not can_draw
        if context is None:
            context = "knockout" if is_knockout else "group"

        if team1 not in self.squads:
            raise KeyError(f"Unknown team: {team1}")
        if team2 not in self.squads:
            raise KeyError(f"Unknown team: {team2}")
        squad1 = self.squads[team1]
        squad2 = self.squads[team2]

        squad1.current_starting_xi = list(squad1.preferred_starting_xi)
        squad2.current_starting_xi = list(squad2.preferred_starting_xi)

        state = self.match_state_service.initialize_match_state(team1, team2, squad1, squad2)
        self.last_match_state = state

        strength1 = self._v4._v3.get_team_strength(team1, is_knockout)
        strength2 = self._v4._v3.get_team_strength(team2, is_knockout)

        base_lambda1, base_lambda2 = self._v4._v3.expected_goals(strength1, strength2)

        tactical_report = compute_tactical_matchup(
            team1, team2,
            base_lambda1, base_lambda2,
            squad1, squad2,
            context=context,
        )
        self._v4.last_tactical_report = tactical_report

        lambda1 = max(self.minimum_lambda, min(tactical_report.final_xg_a, self.max_xg))
        lambda2 = max(self.minimum_lambda, min(tactical_report.final_xg_b, self.max_xg))

        manager1 = get_manager(team1)
        manager2 = get_manager(team2)

        state.game_plan_a = tactical_report.game_plan_a
        state.game_plan_b = tactical_report.game_plan_b

        for phase in PHASE_ORDER:
            self._run_phase(state, team1, team2, squad1, squad2, phase,
                            lambda1, lambda2, manager1, manager2)

        g1 = state.scoreline.goals_a
        g2 = state.scoreline.goals_b

        extra_time_used = False
        penalties_used = False
        penalty_shootout_a: list[str] = []
        penalty_shootout_b: list[str] = []

        if not can_draw and g1 == g2:
            state.is_extra_time = True
            for phase in EXTRA_TIME_PHASES:
                et_lambda1 = lambda1 * self.extra_time_lambda_scale * 0.7
                et_lambda2 = lambda2 * self.extra_time_lambda_scale * 0.7
                self._run_phase(state, team1, team2, squad1, squad2, phase,
                                et_lambda1, et_lambda2, manager1, manager2,
                                is_extra_time=True)

            g1 = state.scoreline.goals_a
            g2 = state.scoreline.goals_b

            if g1 == g2:
                state.is_penalty_shootout = True
                penalty_shootout_a, penalty_shootout_b, winner = self.penalty_engine.simulate_penalty_shootout(
                    squad1, squad2, team1, team2,
                )
                penalties_used = True
                if winner == team1:
                    g1 += 1
                else:
                    g2 += 1
                extra_time_used = True
            else:
                extra_time_used = True

        score = (int(g1), int(g2))

        squad1 = self.squads[team1]
        squad2 = self.squads[team2]
        self._v4._v3.continuity_service.record_lineup(team1, [p.name for p in squad1.current_starting_xi])
        self._v4._v3.continuity_service.record_lineup(team2, [p.name for p in squad2.current_starting_xi])
        self._v4._v3.momentum_service.record_result(team1, int(g1), int(g2), is_real=False)
        self._v4._v3.momentum_service.record_result(team2, int(g2), int(g1), is_real=False)

        self.last_match_state = state
        self.last_match_events = state.events
        self.last_match_debug = self._format_v5_debug(team1, team2, state)
        self._v4.last_match_debug = self.last_match_debug

        return score, state, state.events

    def _run_phase(
        self,
        state: MatchState,
        team1: str,
        team2: str,
        squad1: Squad,
        squad2: Squad,
        phase: MatchPhase,
        lambda1: float,
        lambda2: float,
        manager1: ManagerProfile,
        manager2: ManagerProfile,
        is_extra_time: bool = False,
    ) -> None:
        state.current_phase = phase
        state.record_phase()
        state.minute = self._phase_midpoint(phase)

        press_intensity_a = self.fatigue_service.get_pressing_intensity(state.game_plan_a)
        press_intensity_b = self.fatigue_service.get_pressing_intensity(state.game_plan_b)
        match_intensity = self.fatigue_service.get_match_intensity(state.momentum_a)
        fatigue_mult = 1.3 if is_extra_time else 1.0

        self.fatigue_service.apply_phase_fatigue(
            squad1.current_starting_xi, state.team_a_players,
            is_extra_time=is_extra_time,
            match_intensity=match_intensity * fatigue_mult,
            pressing_intensity=press_intensity_a,
        )
        self.fatigue_service.apply_phase_fatigue(
            squad2.current_starting_xi, state.team_b_players,
            is_extra_time=is_extra_time,
            match_intensity=match_intensity * fatigue_mult,
            pressing_intensity=press_intensity_b,
        )

        self.momentum_service.decay_momentum()
        state.momentum_a = self.momentum_service.team_a_momentum
        state.momentum_b = self.momentum_service.team_b_momentum

        scoreline_state_a = state.scoreline.description_for_team(team1, team1, team2)
        scoreline_state_b = state.scoreline.description_for_team(team2, team1, team2)

        if is_extra_time:
            phase_lambda_a = lambda1
            phase_lambda_b = lambda2
        else:
            phase_lambda_a = self._compute_phase_xg(
                lambda1, state, team1, squad1,
                scoreline_state_a, state.momentum_a,
            )
            phase_lambda_b = self._compute_phase_xg(
                lambda2, state, team2, squad2,
                scoreline_state_b, state.momentum_b,
            )

        phase_events = self.event_engine.generate_phase_events(
            state, squad1, squad2,
            phase_lambda_a, phase_lambda_b,
            phase_lambda_a, phase_lambda_b,
            phase, is_extra_time,
        )
        state.events.extend(phase_events)

        state.momentum_a = self.momentum_service.team_a_momentum
        state.momentum_b = self.momentum_service.team_b_momentum

        phase_minute = int(self._phase_midpoint(phase))
        subs1 = self.substitution_service.evaluate_substitutions(
            team1, squad1, state.team_a_players,
            scoreline_state_a, phase_minute, manager1,
            state.game_plan_a, state.red_card_count_a, is_extra_time,
        )
        subs2 = self.substitution_service.evaluate_substitutions(
            team2, squad2, state.team_b_players,
            scoreline_state_b, phase_minute, manager2,
            state.game_plan_b, state.red_card_count_b, is_extra_time,
        )
        for sub in subs1 + subs2:
            state.substitutions.append(sub)
            off_name = sub.player_off
            on_name = sub.player_on
            state.events.append(MatchEvent(
                minute=sub.minute,
                team=sub.team,
                event_type=EventType.SUBSTITUTION,
                player_name=on_name,
                data={"player_off": off_name, "player_on": on_name, "reason": sub.reason},
            ))

        if not is_extra_time:
            new_plan_a = self.match_state_service.evaluate_manager_reaction(
                manager1, scoreline_state_a, phase_minute, state.game_plan_a,
            )
            if new_plan_a and new_plan_a != state.game_plan_a:
                old_plan = state.game_plan_a
                state.game_plan_a = new_plan_a
                state.game_plan_history_a.append((phase_minute, new_plan_a))
                state.events.append(MatchEvent(
                    minute=phase_minute,
                    team=team1,
                    event_type=EventType.TACTICAL_CHANGE,
                    detail=f"{old_plan} -> {new_plan_a}",
                ))

            new_plan_b = self.match_state_service.evaluate_manager_reaction(
                manager2, scoreline_state_b, phase_minute, state.game_plan_b,
            )
            if new_plan_b and new_plan_b != state.game_plan_b:
                old_plan = state.game_plan_b
                state.game_plan_b = new_plan_b
                state.game_plan_history_b.append((phase_minute, new_plan_b))
                state.events.append(MatchEvent(
                    minute=phase_minute,
                    team=team2,
                    event_type=EventType.TACTICAL_CHANGE,
                    detail=f"{old_plan} -> {new_plan_b}",
                ))

    def _compute_phase_xg(
        self,
        base_lambda: float,
        state: MatchState,
        team: str,
        squad: Squad,
        scoreline_state: str,
        momentum: float,
    ) -> float:
        phase_xg = base_lambda * (15.0 / 90.0)

        energy_avg = state.get_team_energy_avg(team)
        energy_mod = 0.75 + (energy_avg / 100.0) * 0.25

        momentum_mod = self.momentum_service.get_momentum_multiplier(momentum)

        score_mod = self._scoreline_xg_modifier(scoreline_state, state, team, int(state.minute))

        red_mod = 1.0
        if team == state.team_a and state.red_card_count_a > 0:
            red_mod = 1.0 - 0.25 * state.red_card_count_a
        elif team == state.team_b and state.red_card_count_b > 0:
            red_mod = 1.0 - 0.25 * state.red_card_count_b

        return max(0.01, phase_xg * energy_mod * momentum_mod * score_mod * red_mod)

    def _scoreline_xg_modifier(
        self,
        scoreline_state: str,
        state: MatchState,
        team: str,
        minute: int,
    ) -> float:
        if scoreline_state == "winning":
            attack_mod = 0.95
            defense_mod = 1.05

            if minute >= 75:
                attack_mod *= 0.92
                defense_mod *= 1.05

            return (attack_mod + defense_mod) / 2.0

        if scoreline_state == "trailing":
            attack_mod = 1.10
            defense_mod = 0.95
            risk_mod = 1.15

            if state.scoreline.trailing_by_two_plus(team, state.team_a, state.team_b):
                attack_mod = 1.15
                defense_mod = 0.92
                risk_mod = 1.25

            if minute >= 75:
                attack_mod *= 1.08
                risk_mod *= 1.10

            return (attack_mod * 0.5 + risk_mod * 0.3 + defense_mod * 0.2)

        return 1.0

    def get_team_strength(self, team: str) -> TeamStrength:
        return self._v4.get_team_strength(team)

    def expected_goals(
        self,
        team1: str,
        team2: str,
        context: str = "group",
    ) -> tuple[float, float]:
        return self._v4.expected_goals(team1, team2, context)

    def notify_match(self, team1: str, team2: str, goals1: int, goals2: int, is_real: bool) -> None:
        self._v4.notify_match(team1, team2, goals1, goals2, is_real)

    def _phase_midpoint(self, phase: MatchPhase) -> float:
        mapping = {
            MatchPhase.EARLY_FIRST_HALF: 7.5,
            MatchPhase.MID_FIRST_HALF: 22.5,
            MatchPhase.LATE_FIRST_HALF: 37.5,
            MatchPhase.EARLY_SECOND_HALF: 52.5,
            MatchPhase.MID_SECOND_HALF: 67.5,
            MatchPhase.LATE_SECOND_HALF: 82.5,
            MatchPhase.EXTRA_TIME_FIRST: 97.5,
            MatchPhase.EXTRA_TIME_SECOND: 112.5,
        }
        return mapping.get(phase, 45.0)

    def _format_v5_debug(self, team1: str, team2: str, state: MatchState) -> str:
        v4_report = self._v4.last_tactical_report
        lines = [
            f"{'='*60}",
            f"V5 MATCH STATE SIMULATION",
            f"{'='*60}",
            f"{team1} vs {team2}",
            f"Final Score: {state.scoreline.goals_a} - {state.scoreline.goals_b}",
            "",
            f"{'='*60}",
            f"MATCH FLOW",
            f"{'='*60}",
        ]

        for phase in PHASE_ORDER:
            key = phase.value
            s_a = state.phase_stats_a.get(key)
            s_b = state.phase_stats_b.get(key)
            if s_a and s_b:
                lines.append(
                    f"Phase {key}: {team1} attacks={s_a.attacks} shots={s_a.shots} "
                    f"xG={s_a.xg:.2f} | {team2} attacks={s_b.attacks} shots={s_b.shots} "
                    f"xG={s_b.xg:.2f}"
                )

        if state.is_extra_time:
            lines.append(f"\nExtra Time played. Penalties: {state.is_penalty_shootout}")

        lines.append(f"\n{'='*60}")
        lines.append(f"EVENT TIMELINE")
        lines.append(f"{'='*60}")
        timeline = self.game_script_service.format_timeline(state)
        lines.extend(f"  {l}" for l in timeline)

        lines.append(f"\n{'='*60}")
        lines.append(f"TOP PERFORMERS")
        lines.append(f"{'='*60}")
        performers = self.game_script_service.get_top_performers(state)
        for p in performers:
            lines.append(
                f"  {p['name']} ({p['team']}): rating={p['rating']} goals={p['goals']} "
                f"assists={p['assists']} shots={p['shots']} energy={p['energy']}%"
            )

        lines.append(f"\n{'='*60}")
        lines.append(f"MATCH STORY")
        lines.append(f"{'='*60}")
        story = self.game_script_service.generate_match_story(state)
        lines.extend(f"  {l}" for l in story)

        if v4_report:
            from ..services.tactical_analysis import format_tactical_report
            lines.append(f"\n{format_tactical_report(v4_report)}")

        lines.append(f"\n{'='*60}")
        lines.append(f"V5 SUB-SYSTEM STATE")
        lines.append(f"{'='*60}")
        lines.append(f"Momentum: {team1}={state.momentum_a:.1f}, {team2}={state.momentum_b:.1f}")
        lines.append(f"Game Plans: {team1}={state.game_plan_a}, {team2}={state.game_plan_b}")
        lines.append(f"Red Cards: {team1}={state.red_card_count_a}, {team2}={state.red_card_count_b}")
        lines.append(f"Substitutions: {len(state.substitutions)}")
        lines.append(f"Total Events: {len(state.events)}")

        energy_a = state.get_team_energy_avg(team1)
        energy_b = state.get_team_energy_avg(team2)
        lines.append(f"Avg Energy: {team1}={energy_a:.1f}%, {team2}={energy_b:.1f}%")

        return "\n".join(lines)
