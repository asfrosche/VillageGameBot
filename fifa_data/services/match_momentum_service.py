from __future__ import annotations

from ..models.match_event import EventType, MatchEvent


class MatchMomentumService:
    DECAY_PER_PHASE = 8.0
    MAX_MOMENTUM = 100.0

    TRIGGER_VALUES: dict[str, float] = {
        "goal_scored": 25.0,
        "goal_conceded": -20.0,
        "big_chance_created": 5.0,
        "big_chance_conceded": -4.0,
        "yellow_card_received": -5.0,
        "yellow_card_opponent": 3.0,
        "red_card_received": -30.0,
        "red_card_opponent": 15.0,
        "missed_penalty": -15.0,
        "saved_penalty": 12.0,
        "late_equalizer": 30.0,
        "concede_after_scoring": -15.0,
        "substitution_attacking": 5.0,
        "substitution_defensive": -3.0,
        "corner_won": 2.0,
        "shot_on_target": 3.0,
        "woodwork": 8.0,
    }

    def __init__(self) -> None:
        self.team_a_momentum: float = 0.0
        self.team_b_momentum: float = 0.0
        self._last_goal_minute_a: int | None = None
        self._last_goal_minute_b: int | None = None
        self._goals_since_last_a: int = 0
        self._goals_since_last_b: int = 0

    def reset(self) -> None:
        self.team_a_momentum = 0.0
        self.team_b_momentum = 0.0
        self._last_goal_minute_a = None
        self._last_goal_minute_b = None
        self._goals_since_last_a = 0
        self._goals_since_last_b = 0

    def apply_event(self, event: MatchEvent, team_a: str, team_b: str) -> None:
        team = event.team
        is_team_a = team == team_a
        opponent_is_a = not is_team_a

        if event.event_type == EventType.GOAL:
            if is_team_a:
                self.team_a_momentum += self.TRIGGER_VALUES["goal_scored"]
                self.team_b_momentum += self.TRIGGER_VALUES["goal_conceded"]
                if self._last_goal_minute_a and int(event.minute) - self._last_goal_minute_a <= 5:
                    self.team_b_momentum += self.TRIGGER_VALUES["concede_after_scoring"]
                self._last_goal_minute_a = int(event.minute)
                self._goals_since_last_a += 1
            else:
                self.team_b_momentum += self.TRIGGER_VALUES["goal_scored"]
                self.team_a_momentum += self.TRIGGER_VALUES["goal_conceded"]
                if self._last_goal_minute_b and int(event.minute) - self._last_goal_minute_b <= 5:
                    self.team_a_momentum += self.TRIGGER_VALUES["concede_after_scoring"]
                self._last_goal_minute_b = int(event.minute)
                self._goals_since_last_b += 1

            if event.minute >= 85:
                if is_team_a:
                    self.team_a_momentum += self.TRIGGER_VALUES["late_equalizer"]
                else:
                    self.team_b_momentum += self.TRIGGER_VALUES["late_equalizer"]

        elif event.event_type == EventType.BIG_CHANCE:
            delta = self.TRIGGER_VALUES["big_chance_created"]
            opp_delta = self.TRIGGER_VALUES["big_chance_conceded"]
            if is_team_a:
                self.team_a_momentum += delta
                self.team_b_momentum += opp_delta
            else:
                self.team_b_momentum += delta
                self.team_a_momentum += opp_delta

        elif event.event_type == EventType.YELLOW_CARD:
            delta = self.TRIGGER_VALUES["yellow_card_received"]
            opp_delta = self.TRIGGER_VALUES["yellow_card_opponent"]
            if is_team_a:
                self.team_a_momentum += delta
                self.team_b_momentum += opp_delta
            else:
                self.team_b_momentum += delta
                self.team_a_momentum += opp_delta

        elif event.event_type == EventType.RED_CARD:
            delta = self.TRIGGER_VALUES["red_card_received"]
            opp_delta = self.TRIGGER_VALUES["red_card_opponent"]
            if is_team_a:
                self.team_a_momentum += delta
                self.team_b_momentum += opp_delta
            else:
                self.team_b_momentum += delta
                self.team_a_momentum += opp_delta

        elif event.event_type == EventType.PENALTY_MISSED:
            if is_team_a:
                self.team_a_momentum += self.TRIGGER_VALUES["missed_penalty"]
            else:
                self.team_b_momentum += self.TRIGGER_VALUES["missed_penalty"]

        elif event.event_type == EventType.SHOT:
            if is_team_a:
                self.team_a_momentum += self.TRIGGER_VALUES["shot_on_target"] * 0.5
            else:
                self.team_b_momentum += self.TRIGGER_VALUES["shot_on_target"] * 0.5

        self._clamp_momentum()

    def decay_momentum(self, phases_passed: int = 1) -> None:
        decay_amount = self.DECAY_PER_PHASE * phases_passed
        if self.team_a_momentum > 0:
            self.team_a_momentum = max(0, self.team_a_momentum - decay_amount)
        elif self.team_a_momentum < 0:
            self.team_a_momentum = min(0, self.team_a_momentum + decay_amount)

        if self.team_b_momentum > 0:
            self.team_b_momentum = max(0, self.team_b_momentum - decay_amount)
        elif self.team_b_momentum < 0:
            self.team_b_momentum = min(0, self.team_b_momentum + decay_amount)

    def get_momentum_multiplier(self, team_momentum: float) -> float:
        normalized = team_momentum / self.MAX_MOMENTUM
        if normalized > 0:
            return 1.0 + normalized * 0.08
        return 1.0 + normalized * 0.12

    def get_pressing_modifier(self, team_momentum: float) -> float:
        normalized = team_momentum / self.MAX_MOMENTUM
        return 1.0 + normalized * 0.15

    def get_shot_quality_modifier(self, team_momentum: float) -> float:
        normalized = team_momentum / self.MAX_MOMENTUM
        return 1.0 + normalized * 0.10

    def _clamp_momentum(self) -> None:
        self.team_a_momentum = max(-self.MAX_MOMENTUM, min(self.MAX_MOMENTUM, self.team_a_momentum))
        self.team_b_momentum = max(-self.MAX_MOMENTUM, min(self.MAX_MOMENTUM, self.team_b_momentum))

    def get_momentum(self, team: str, team_a: str) -> float:
        return self.team_a_momentum if team == team_a else self.team_b_momentum
