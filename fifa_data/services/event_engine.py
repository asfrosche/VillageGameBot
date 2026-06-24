from __future__ import annotations

import math
import random

from ..models.match_event import EventType, MatchEvent
from ..models.match_state import MatchPhase, MatchState, PhaseStats
from ..models.player import Player
from ..models.player_match_state import PlayerMatchState
from ..models.squad import Squad
from ..services.card_service import CardService
from ..services.match_momentum_service import MatchMomentumService


class EventEngine:
    def __init__(
        self,
        card_service: CardService,
        momentum_service: MatchMomentumService,
    ) -> None:
        self.card_service = card_service
        self.momentum_service = momentum_service

    def generate_phase_events(
        self,
        match_state: MatchState,
        squad_a: Squad,
        squad_b: Squad,
        lambda_a: float,
        lambda_b: float,
        v4_xg_a: float,
        v4_xg_b: float,
        phase: MatchPhase,
        is_extra_time: bool = False,
    ) -> list[MatchEvent]:
        events: list[MatchEvent] = []
        minutes_in_phase = 15
        phase_min_start = self._phase_start_minute(phase)

        xg_a = v4_xg_a
        xg_b = v4_xg_b

        if is_extra_time:
            xg_a *= 0.7
            xg_b *= 0.7

        total_attack_events_a = self._estimate_attacks(xg_a, match_state.team_a_players, match_state.momentum_a)
        total_attack_events_b = self._estimate_attacks(xg_b, match_state.team_b_players, match_state.momentum_b)

        goal_stalemate_mod = self._goal_stalemate_mod(squad_a, squad_b)
        events.extend(self._distribute_attacks(
            match_state, squad_a, total_attack_events_a, match_state.team_a,
            squad_b, phase_min_start, minutes_in_phase, goal_stalemate_mod,
        ))
        events.extend(self._distribute_attacks(
            match_state, squad_b, total_attack_events_b, match_state.team_b,
            squad_a, phase_min_start, minutes_in_phase, goal_stalemate_mod,
        ))

        self._record_phase_stats(
            match_state, match_state.team_a, total_attack_events_a, xg_a,
        )
        self._record_phase_stats(
            match_state, match_state.team_b, total_attack_events_b, xg_b,
        )

        match_state.total_possession_a += total_attack_events_a
        match_state.total_possession_b += total_attack_events_b

        return events

    def _estimate_attacks(
        self,
        phase_xg: float,
        player_states: dict[str, PlayerMatchState],
        momentum: float,
    ) -> int:
        if phase_xg <= 0:
            return max(2, int(abs(momentum) / 15))
        base_attacks = max(5, int(phase_xg * 35))
        momentum_mod = 1.0 + (momentum / 100.0) * 0.15
        energy_avg = sum(
            ps.energy for ps in player_states.values()
            if not ps.was_substituted and not ps.red_card
        ) / max(len([ps for ps in player_states.values() if not ps.was_substituted and not ps.red_card]), 1)
        energy_mod = 0.85 + (energy_avg / 100.0) * 0.15
        return max(2, int(base_attacks * momentum_mod * energy_mod))

    def _distribute_attacks(
        self,
        match_state: MatchState,
        squad: Squad,
        total_attacks: int,
        team: str,
        opposing_squad: Squad,
        phase_start: int,
        minutes: int,
        goal_stalemate_mod: float = 1.0,
    ) -> list[MatchEvent]:
        events: list[MatchEvent] = []
        if total_attacks <= 0:
            return events

        shot_ratio = 0.35 + random.random() * 0.15
        shot_count = max(1, int(total_attacks * shot_ratio))
        sot_ratio = 0.45 + random.random() * 0.15
        sot_count = max(1, int(shot_count * sot_ratio))
        bc_roll = random.random()
        big_chance_count = 2 if bc_roll < 0.08 else (1 if bc_roll < 0.45 else 0)

        shot_indices = set(random.sample(range(total_attacks), min(shot_count, total_attacks)))
        sot_indices = set(random.sample(list(shot_indices), min(sot_count, len(shot_indices))))
        bc_indices = set()
        if big_chance_count > 0 and len(shot_indices) > 0:
            bc_indices = set(random.sample(list(shot_indices), min(big_chance_count, len(shot_indices))))

        gk_mod = self._get_opponent_gk_mod(opposing_squad)

        for i in range(total_attacks):
            minute = phase_start + int((i / max(total_attacks, 1)) * minutes)

            is_shot = i in shot_indices
            is_sot = i in sot_indices
            is_big_chance = i in bc_indices

            if is_shot:
                taker = self._select_event_player(squad, "ST")
                if taker is None:
                    taker = self._select_event_player(squad, "CM")

                if is_big_chance:
                    bc_xg = round(random.uniform(0.15, 0.40), 3)
                    events.append(MatchEvent(
                        minute=minute,
                        team=team,
                        event_type=EventType.BIG_CHANCE,
                        player_name=taker.name if taker else None,
                        xg=bc_xg,
                    ))
                    shot_xg = bc_xg
                    finishing = taker.attributes.get("finishing", 50.0) if taker else 50.0
                    composure = taker.attributes.get("composure", 50.0) if taker else 50.0
                    goal_prob = 0.16 + (finishing - 50.0) / 200.0 + (composure - 50.0) / 350.0
                    goal_prob = min(0.40, max(0.08, goal_prob)) * gk_mod * goal_stalemate_mod
                else:
                    shot_xg = round(random.uniform(0.02, 0.15), 3)
                    finishing = taker.attributes.get("finishing", 50.0) if taker else 50.0
                    composure = taker.attributes.get("composure", 50.0) if taker else 50.0
                    goal_prob = 0.07 + (finishing - 50.0) / 300.0 + (composure - 50.0) / 450.0
                    goal_prob = min(0.22, max(0.03, goal_prob)) * gk_mod * goal_stalemate_mod

                events.append(MatchEvent(
                    minute=minute,
                    team=team,
                    event_type=EventType.SHOT,
                    player_name=taker.name if taker else None,
                    xg=shot_xg,
                    detail="on_target" if is_sot else "off_target",
                ))

                if is_sot:
                    if random.random() < goal_prob:
                        scorer = taker or self._select_event_player(squad, "ST")
                        assist = self._select_event_player(squad, "CM") if random.random() < (0.70 if is_big_chance else 0.60) else None
                        events.append(self._create_goal_event(
                            match_state, team, minute + random.randint(0, 2 if is_big_chance else 1),
                            scorer, assist, shot_xg,
                        ))

                player_state = match_state.get_player_state(team, taker.name) if taker else None
                if player_state:
                    player_state.shots += 1
                    if is_sot:
                        player_state.shots_on_target += 1

            if random.random() < 0.06:
                corner_taker = self._select_event_player(squad, "WINGER")
                events.append(MatchEvent(
                    minute=minute,
                    team=team,
                    event_type=EventType.CORNER,
                    player_name=corner_taker.name if corner_taker else None,
                ))

        up_to = len(events)
        eligible = squad.current_starting_xi[:]
        checked_this_phase = set()
        for event in events[:up_to]:
            if event.team != team:
                continue
            minute = event.minute
            player = None
            if event.player_name:
                for p in eligible:
                    if p.name == event.player_name:
                        player = p
                        break
            if player is None:
                non_red = [p for p in eligible
                           if not match_state.get_player_state(team, p.name).red_card]
                if non_red:
                    player = random.choice(non_red)
                else:
                    continue
            state = match_state.get_player_state(team, player.name)
            if state is None or state.was_substituted or state.red_card:
                continue
            # Check involved player
            self._check_player_card(match_state, team, player, state, minute, events)
            # Check 1 additional random player per event (for off-ball fouls)
            if random.random() < 0.6:
                extra_candidates = [p for p in eligible if p.name != player.name
                                    and p.name not in checked_this_phase
                                    and not match_state.get_player_state(team, p.name).red_card]
                if extra_candidates:
                    p = random.choice(extra_candidates)
                    ps = match_state.get_player_state(team, p.name)
                    if ps and not ps.was_substituted:
                        self._check_player_card(match_state, team, p, ps, minute, events)
                        checked_this_phase.add(p.name)

        return events

    def _create_goal_event(
        self,
        match_state: MatchState,
        team: str,
        minute: int,
        scorer: Player | None,
        assist: Player | None,
        xg: float,
    ) -> MatchEvent:
        event = MatchEvent(
            minute=minute,
            team=team,
            event_type=EventType.GOAL,
            player_name=scorer.name if scorer else None,
            secondary_player=assist.name if assist else None,
            xg=xg,
        )

        player_state = match_state.get_player_state(team, scorer.name) if scorer else None
        if player_state:
            player_state.goals += 1
        if assist:
            assist_state = match_state.get_player_state(team, assist.name)
            if assist_state:
                assist_state.assists += 1

        self._update_scoreline(match_state, team)
        self.momentum_service.apply_event(event, match_state.team_a, match_state.team_b)
        return event

    def _check_player_card(
        self,
        match_state: MatchState,
        team: str,
        player: Player,
        player_state: PlayerMatchState,
        minute: int,
        events: list[MatchEvent],
    ) -> None:
        foul, yellow, red = self.card_service.check_foul_and_card(
            player, player_state, 1.0,
        )
        if foul:
            player_state.fouls += 1
            events.append(MatchEvent(
                minute=minute,
                team=team,
                event_type=EventType.FOUL,
                player_name=player.name,
            ))
            if yellow:
                events.append(MatchEvent(
                    minute=minute,
                    team=team,
                    event_type=EventType.YELLOW_CARD,
                    player_name=player.name,
                ))
                self.momentum_service.apply_event(
                    MatchEvent(minute, team, EventType.YELLOW_CARD, player_name=player.name),
                    match_state.team_a, match_state.team_b,
                )
            if red:
                events.append(MatchEvent(
                    minute=minute,
                    team=team,
                    event_type=EventType.RED_CARD,
                    player_name=player.name,
                ))
                if team == match_state.team_a:
                    match_state.red_card_count_a += 1
                else:
                    match_state.red_card_count_b += 1
                self.momentum_service.apply_event(
                    MatchEvent(minute, team, EventType.RED_CARD, player_name=player.name),
                    match_state.team_a, match_state.team_b,
                )

    def _goal_stalemate_mod(self, squad_a: Squad, squad_b: Squad) -> float:
        def_a = sum(p.attributes.get("defending", 50.0) for p in squad_a.current_starting_xi) / max(len(squad_a.current_starting_xi), 1)
        def_b = sum(p.attributes.get("defending", 50.0) for p in squad_b.current_starting_xi) / max(len(squad_b.current_starting_xi), 1)
        if def_a < 58.0 or def_b < 58.0:
            return 1.0
        avg_def = (def_a + def_b) / 2.0
        above = (avg_def - 58.0) / 30.0
        reduction = min(0.40, 0.75 * above)
        return max(0.60, 1.0 - reduction)

    def _get_opponent_gk_mod(self, opposing_squad: Squad) -> float:
        from ..models.team_strength import role_for_player
        gk = None
        for p in opposing_squad.current_starting_xi:
            if role_for_player(p) == "GK":
                gk = p
                break
        if gk is None:
            return 1.0
        reflexes = gk.attributes.get("reflexes", 50.0)
        diving = gk.attributes.get("diving", 50.0)
        positioning = gk.attributes.get("positioning", 50.0)
        handling = gk.attributes.get("handling", 50.0)
        gk_rating = (reflexes * 0.30 + diving * 0.25 + positioning * 0.20 + handling * 0.15) / 0.90
        mod = 1.0 - (gk_rating - 50.0) / 200.0
        return max(0.60, min(1.0, mod))

    def _select_event_player(self, squad: Squad, preferred_role: str) -> Player | None:
        from ..models.team_strength import role_for_player
        candidates = [
            p for p in squad.current_starting_xi
            if role_for_player(p) == preferred_role
        ]
        if candidates:
            return random.choice(candidates)
        if preferred_role == "ST":
            candidates = [p for p in squad.current_starting_xi if role_for_player(p) in {"WINGER", "CM"}]
        elif preferred_role == "CM":
            candidates = [p for p in squad.current_starting_xi if role_for_player(p) in {"DM", "WINGER"}]
        else:
            candidates = list(squad.current_starting_xi)
        return random.choice(candidates) if candidates else None

    def _update_scoreline(self, match_state: MatchState, scoring_team: str) -> None:
        if scoring_team == match_state.team_a:
            match_state.scoreline.goals_a += 1
        else:
            match_state.scoreline.goals_b += 1

    def _record_phase_stats(
        self,
        match_state: MatchState,
        team: str,
        attacks: int,
        xg: float,
    ) -> None:
        stats = match_state.get_current_phase_stats(team)
        stats.attacks += attacks
        stats.xg += xg
        dangerous = max(1, int(attacks * 0.30))
        stats.dangerous_attacks += dangerous
        shots = max(1, int(attacks * 0.40))
        stats.shots += shots
        stats.shots_on_target += int(shots * 0.45)

    @staticmethod
    def _phase_start_minute(phase: MatchPhase) -> int:
        mapping = {
            MatchPhase.EARLY_FIRST_HALF: 0,
            MatchPhase.MID_FIRST_HALF: 15,
            MatchPhase.LATE_FIRST_HALF: 30,
            MatchPhase.EARLY_SECOND_HALF: 45,
            MatchPhase.MID_SECOND_HALF: 60,
            MatchPhase.LATE_SECOND_HALF: 75,
            MatchPhase.EXTRA_TIME_FIRST: 90,
            MatchPhase.EXTRA_TIME_SECOND: 105,
        }
        return mapping.get(phase, 0)
