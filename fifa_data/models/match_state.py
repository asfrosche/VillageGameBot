from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .match_event import MatchEvent
from .player_match_state import PlayerMatchState
from .substitution_event import SubstitutionEvent


class MatchPhase(Enum):
    EARLY_FIRST_HALF = "0-15"
    MID_FIRST_HALF = "15-30"
    LATE_FIRST_HALF = "30-45"
    EARLY_SECOND_HALF = "45-60"
    MID_SECOND_HALF = "60-75"
    LATE_SECOND_HALF = "75-90"
    EXTRA_TIME_FIRST = "90-105"
    EXTRA_TIME_SECOND = "105-120"


PHASE_ORDER = [
    MatchPhase.EARLY_FIRST_HALF,
    MatchPhase.MID_FIRST_HALF,
    MatchPhase.LATE_FIRST_HALF,
    MatchPhase.EARLY_SECOND_HALF,
    MatchPhase.MID_SECOND_HALF,
    MatchPhase.LATE_SECOND_HALF,
]

EXTRA_TIME_PHASES = [
    MatchPhase.EXTRA_TIME_FIRST,
    MatchPhase.EXTRA_TIME_SECOND,
]


@dataclass
class PhaseStats:
    possession: float = 50.0
    attacks: int = 0
    dangerous_attacks: int = 0
    shots: int = 0
    shots_on_target: int = 0
    big_chances: int = 0
    xg: float = 0.0
    goals: int = 0
    corners: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0


@dataclass
class ScorelineState:
    goals_a: int = 0
    goals_b: int = 0

    @property
    def is_draw(self) -> bool:
        return self.goals_a == self.goals_b

    @property
    def goal_difference(self) -> int:
        return self.goals_a - self.goals_b

    def description_for_team(self, team: str, team_a_label: str, team_b_label: str) -> str:
        if team == team_a_label:
            if self.goals_a > self.goals_b:
                return "winning_2+" if self.goals_a - self.goals_b >= 2 else "winning"
            if self.goals_a < self.goals_b:
                return "trailing_2+" if self.goals_b - self.goals_a >= 2 else "trailing"
            return "drawing"
        if self.goals_b > self.goals_a:
            return "winning_2+" if self.goals_b - self.goals_a >= 2 else "winning"
        if self.goals_b < self.goals_a:
            return "trailing_2+" if self.goals_a - self.goals_b >= 2 else "trailing"
        return "drawing"

    def trailing_by_two_plus(self, team: str, team_a_label: str, team_b_label: str) -> bool:
        if team == team_a_label:
            return self.goals_b - self.goals_a >= 2
        return self.goals_a - self.goals_b >= 2


@dataclass
class MatchState:
    team_a: str
    team_b: str
    team_a_players: dict[str, PlayerMatchState] = field(default_factory=dict)
    team_b_players: dict[str, PlayerMatchState] = field(default_factory=dict)
    scoreline: ScorelineState = field(default_factory=ScorelineState)
    momentum_a: float = 0.0
    momentum_b: float = 0.0
    current_phase: MatchPhase = MatchPhase.EARLY_FIRST_HALF
    minute: float = 0.0
    game_plan_a: str = "balanced"
    game_plan_b: str = "balanced"
    game_plan_history_a: list[tuple[int, str]] = field(default_factory=list)
    game_plan_history_b: list[tuple[int, str]] = field(default_factory=list)
    events: list[MatchEvent] = field(default_factory=list)
    substitutions: list[SubstitutionEvent] = field(default_factory=list)
    phase_stats_a: dict[str, PhaseStats] = field(default_factory=dict)
    phase_stats_b: dict[str, PhaseStats] = field(default_factory=dict)
    is_extra_time: bool = False
    is_penalty_shootout: bool = False
    red_card_count_a: int = 0
    red_card_count_b: int = 0
    total_possession_a: float = 0.0
    total_possession_b: float = 0.0
    phase_count: int = 0

    def get_player_state(self, team: str, player_name: str) -> PlayerMatchState | None:
        pool = self.team_a_players if team == self.team_a else self.team_b_players
        return pool.get(player_name)

    def get_team_energy_avg(self, team: str) -> float:
        pool = self.team_a_players if team == self.team_a else self.team_b_players
        if not pool:
            return 100.0
        energies = [p.energy for p in pool.values() if not p.was_substituted]
        return sum(energies) / len(energies) if energies else 100.0

    def record_phase(self) -> None:
        key = self.current_phase.value
        if key not in self.phase_stats_a:
            self.phase_stats_a[key] = PhaseStats()
            self.phase_stats_b[key] = PhaseStats()
        self.phase_count += 1

    def get_current_phase_stats(self, team: str) -> PhaseStats:
        key = self.current_phase.value
        if team == self.team_a:
            if key not in self.phase_stats_a:
                self.phase_stats_a[key] = PhaseStats()
            return self.phase_stats_a[key]
        if key not in self.phase_stats_b:
            self.phase_stats_b[key] = PhaseStats()
        return self.phase_stats_b[key]

    @property
    def phases(self) -> list[str]:
        """Return list of phase keys that have been recorded."""
        return list(self.phase_stats_a.keys())

    def is_knockout(self) -> bool:
        return False

    def set_knockout(self) -> None:
        pass
