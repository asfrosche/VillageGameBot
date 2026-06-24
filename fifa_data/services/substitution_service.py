from __future__ import annotations

import random

from ..models.player import Player
from ..models.player_match_state import PlayerMatchState
from ..models.squad import Squad
from ..models.substitution_event import SubstitutionEvent
from ..models.tactical_state import ManagerProfile
from ..services.fatigue_service import FatigueService


class SubstitutionService:
    def __init__(self, fatigue_service: FatigueService) -> None:
        self.fatigue_service = fatigue_service

    def evaluate_substitutions(
        self,
        team: str,
        squad: Squad,
        player_states: dict[str, PlayerMatchState],
        scoreline_state: str,
        minute: int,
        manager: ManagerProfile | None = None,
        game_plan: str = "balanced",
        red_cards: int = 0,
        is_extra_time: bool = False,
    ) -> list[SubstitutionEvent]:
        substitutions: list[SubstitutionEvent] = []
        if minute < 50 or minute > 88:
            return substitutions

        candidates_off: list[tuple[Player, str, float]] = []

        for player in squad.current_starting_xi:
            state = player_states.get(player.name)
            if state is None or state.was_substituted or state.red_card:
                continue

            sub_urgency = 0.0
            reason = "tactical"
            min_sub_minute = 55

            if state.energy < 30:
                sub_urgency += 0.7
                reason = "fatigue"
                min_sub_minute = 55
            elif state.energy < 45:
                sub_urgency += 0.3
                reason = "fatigue"
                min_sub_minute = 60

            if state.yellow_cards >= 1 and "CB" in squad.formation or "DM" in squad.formation:
                is_defender = any(
                    pos in player.normalized_positions()
                    for pos in ("CB", "FB", "DM")
                )
                if is_defender:
                    sub_urgency += 0.35
                    reason = "card"
                    min_sub_minute = 55

            if state.match_rating < 6.0:
                sub_urgency += 0.2
                if reason == "tactical":
                    reason = "tactical"

            if state.is_injured:
                sub_urgency += 0.9
                reason = "injury"
                min_sub_minute = 1

            if minute >= min_sub_minute and sub_urgency > 0:
                candidates_off.append((player, reason, sub_urgency))

        if not candidates_off:
            return substitutions

        attack_urgency = self._scoreline_attack_urgency(scoreline_state, minute, manager)
        def_urgency = self._scoreline_defense_urgency(scoreline_state, minute, manager)

        num_subs = 0
        max_subs = 5
        existing_subs = len([s for s in squad.bench_players if s not in squad.current_starting_xi])
        _available_subs = 5 - (existing_subs if existing_subs <= 5 else 0)

        candidates_off.sort(key=lambda x: x[2], reverse=True)

        for player_off, reason, urgency in candidates_off:
            if num_subs >= max_subs:
                break

            role = self._determine_role(player_off)
            bench_player = self._find_best_replacement(squad, role, player_states, attack_urgency, def_urgency)
            if bench_player is None:
                continue

            if reason == "tactical" and urgency < 0.5 and random.random() > 0.4:
                continue

            sub = SubstitutionEvent(
                minute=minute,
                team=team,
                player_off=player_off.name,
                player_on=bench_player.name,
                reason=reason,
            )
            substitutions.append(sub)

            player_states[player_off.name].was_substituted = True
            player_states[bench_player.name] = PlayerMatchState(
                player_name=bench_player.name,
                country=team,
                position=role,
                is_substitute=True,
                energy=100.0,
                morale=50.0,
                match_rating=6.0,
                minutes_played=0,
            )

            squad.current_starting_xi = [
                bench_player if p == player_off else p
                for p in squad.current_starting_xi
            ]
            num_subs += 1

        return substitutions

    def _scoreline_attack_urgency(self, scoreline: str, minute: int, manager: ManagerProfile | None = None) -> float:
        if scoreline == "trailing" and minute >= 60:
            base = 0.4 + (minute - 60) / 100.0
            if manager and manager.risk_tolerance > 65:
                base += 0.2
            return base
        if "2+" in scoreline and minute >= 55:
            base = 0.5 + (minute - 55) / 100.0
            if manager and manager.risk_tolerance > 65:
                base += 0.25
            return base
        return 0.0

    def _scoreline_defense_urgency(self, scoreline: str, minute: int, manager: ManagerProfile | None = None) -> float:
        if scoreline == "winning" and minute >= 70:
            base = 0.3 + (minute - 70) / 100.0
            if manager and manager.defensive_discipline > 65:
                base += 0.15
            return base
        return 0.0

    def _determine_role(self, player: Player) -> str:
        from ..models.team_strength import role_for_player, role_rating as compute_role_rating
        return role_for_player(player)

    def _find_best_replacement(
        self,
        squad: Squad,
        role: str,
        player_states: dict[str, PlayerMatchState],
        attack_urgency: float,
        def_urgency: float,
    ) -> Player | None:
        on_pitch_names = {p.name for p in squad.current_starting_xi}
        candidates = [
            p for p in squad.players
            if p.name not in on_pitch_names and p.is_available()
        ]
        if not candidates:
            return None

        def score(player: Player) -> float:
            from ..models.team_strength import role_for_player, role_rating as compute_role_rating
            base = compute_role_rating(player, role)
            freshness = self.fatigue_service.freshness_bonus(0)
            player_role = role_for_player(player)
            attack_roles = {"ST", "WINGER"}
            def_roles = {"CB", "FB", "DM"}
            if player_role in attack_roles:
                base += attack_urgency * 10
            if player_role in def_roles:
                base += def_urgency * 10
            return base * freshness

        return max(candidates, key=score)

    def calculate_bench_strength(self, squad: Squad) -> dict[str, float]:
        on_pitch_names = {p.name for p in squad.current_starting_xi}
        bench = [p for p in squad.players if p.name not in on_pitch_names]

        attack_rating = 0.0
        midfield_rating = 0.0
        defense_rating = 0.0
        count_a = count_m = count_d = 0

        for player in bench:
            from ..models.team_strength import role_for_player
            role = role_for_player(player)
            if role in {"ST", "WINGER"}:
                attack_rating += player.attributes.get("finishing", 50.0)
                count_a += 1
            elif role in {"CM", "DM"}:
                midfield_rating += player.attributes.get("passing", 50.0)
                count_m += 1
            elif role in {"CB", "FB"}:
                defense_rating += player.attributes.get("defending", 50.0)
                count_d += 1

        return {
            "bench_attack": round(attack_rating / max(count_a, 1), 2),
            "bench_midfield": round(midfield_rating / max(count_m, 1), 2),
            "bench_defense": round(defense_rating / max(count_d, 1), 2),
            "bench_size": len(bench),
        }
