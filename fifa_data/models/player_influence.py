from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OffensiveInfluence:
    player_name: str
    role: str
    xg_contribution: float
    xa_contribution: float
    chance_creation: float
    progressive_actions: float
    dangerous_touches: float
    transition_impact: float
    press_resistance: float
    overall_influence: float
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class DefensiveInfluence:
    player_name: str
    role: str
    opp_xg_prevented: float
    defensive_stability: float
    interceptions_rating: float
    tackling_rating: float
    aerial_win_rate: float
    recovery_rating: float
    overall_influence: float
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class GoalkeeperInfluence:
    player_name: str
    goals_prevented: float
    save_expectation: float
    claim_rating: float
    distribution_rating: float
    one_on_one_rating: float
    overall_influence: float
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class TeamDependency:
    team: str
    top_n_attackers: int
    attack_output_share: float
    top_attackers_names: list[str]
    dependency_level: str
    top_n_defenders: int
    defense_output_share: float
    top_defenders_names: list[str]


@dataclass
class PlayerMatchup:
    player_a: str
    player_b: str
    category: str
    advantage_team: str
    advantage_magnitude: float
    net_xg_impact: float
    key_stats: dict[str, tuple[float, float]] = field(default_factory=dict)
    description: str = ""


@dataclass
class PlayerInfluenceReport:
    team_a: str
    team_b: str
    offensive_a: list[OffensiveInfluence]
    offensive_b: list[OffensiveInfluence]
    defensive_a: list[DefensiveInfluence]
    defensive_b: list[DefensiveInfluence]
    goalkeeper_a: GoalkeeperInfluence | None = None
    goalkeeper_b: GoalkeeperInfluence | None = None
    dependency_a: TeamDependency | None = None
    dependency_b: TeamDependency | None = None
    matchups: list[PlayerMatchup] = field(default_factory=list)

    def top_attackers(self, team: str, n: int = 3) -> list[OffensiveInfluence]:
        source = self.offensive_a if team == self.team_a else self.offensive_b
        return sorted(source, key=lambda p: p.overall_influence, reverse=True)[:n]

    def top_defenders(self, team: str, n: int = 3) -> list[DefensiveInfluence]:
        source = self.defensive_a if team == self.team_a else self.defensive_b
        return sorted(source, key=lambda p: p.overall_influence, reverse=True)[:n]

    def top_matchups(self, n: int = 5) -> list[PlayerMatchup]:
        return sorted(self.matchups, key=lambda m: abs(m.net_xg_impact), reverse=True)[:n]
