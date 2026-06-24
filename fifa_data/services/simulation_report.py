from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MonteCarloResult:
    wins_a: int = 0
    wins_b: int = 0
    draws: int = 0
    total: int = 0
    avg_xg_a: float = 0.0
    avg_xg_b: float = 0.0
    top_scores: list[tuple[tuple[int, int], int]] = field(default_factory=list)
    min_goals_a: int = 0
    max_goals_a: int = 0
    min_goals_b: int = 0
    max_goals_b: int = 0

    @property
    def win_prob_a(self) -> float:
        return self.wins_a / self.total * 100 if self.total else 0.0

    @property
    def win_prob_b(self) -> float:
        return self.wins_b / self.total * 100 if self.total else 0.0

    @property
    def draw_prob(self) -> float:
        return self.draws / self.total * 100 if self.total else 0.0


@dataclass
class V1ReportData:
    elo_a: float = 1500.0
    elo_b: float = 1500.0
    pele_a: float = 1500.0
    pele_b: float = 1500.0
    combined_a: float = 1500.0
    combined_b: float = 1500.0
    upset_factor: float = 1.0

    @property
    def elo_diff(self) -> float:
        return self.elo_a - self.elo_b

    @property
    def pele_diff(self) -> float:
        return self.pele_a - self.pele_b

    @property
    def combined_diff(self) -> float:
        return self.combined_a - self.combined_b


@dataclass
class RoleRatingData:
    player_name: str
    role: str
    rating: float


@dataclass
class V2ReportData:
    role_ratings_a: list[RoleRatingData] = field(default_factory=list)
    role_ratings_b: list[RoleRatingData] = field(default_factory=list)
    attack_a: float = 0.0
    midfield_a: float = 0.0
    defense_a: float = 0.0
    goalkeeper_a: float = 0.0
    attack_b: float = 0.0
    midfield_b: float = 0.0
    defense_b: float = 0.0
    goalkeeper_b: float = 0.0
    formation_a: str = "4-3-3"
    formation_b: str = "4-3-3"
    xi_names_a: list[str] = field(default_factory=list)
    xi_names_b: list[str] = field(default_factory=list)

    @property
    def best_player_a(self) -> RoleRatingData | None:
        return max(self.role_ratings_a, key=lambda r: r.rating) if self.role_ratings_a else None

    @property
    def best_player_b(self) -> RoleRatingData | None:
        return max(self.role_ratings_b, key=lambda r: r.rating) if self.role_ratings_b else None


@dataclass
class V3ComponentData:
    name: str
    value_a: float = 0.0
    value_b: float = 0.0
    source_a: str = ""
    source_b: str = ""
    confidence_a: float = 1.0
    confidence_b: float = 1.0


@dataclass
class V3ReportData:
    components: list[V3ComponentData] = field(default_factory=list)
    combined_mult_a: float = 1.0
    combined_mult_b: float = 1.0
    form_details_a: list[dict[str, Any]] = field(default_factory=list)
    form_details_b: list[dict[str, Any]] = field(default_factory=list)
    experience_details_a: list[dict[str, Any]] = field(default_factory=list)
    experience_details_b: list[dict[str, Any]] = field(default_factory=list)
    leadership_a: dict[str, Any] = field(default_factory=dict)
    leadership_b: dict[str, Any] = field(default_factory=dict)
    chemistry_a: dict[str, Any] = field(default_factory=dict)
    chemistry_b: dict[str, Any] = field(default_factory=dict)
    nationality_modifier_a: float = 0.0
    nationality_modifier_b: float = 0.0

    @property
    def net_dynamic_a(self) -> float:
        return self.combined_mult_a - 1.0

    @property
    def net_dynamic_b(self) -> float:
        return self.combined_mult_b - 1.0


@dataclass
class TacticalAdjustmentData:
    category: str
    description: str
    value: float
    confidence: float = 1.0


@dataclass
class V4ReportData:
    base_xg_a: float = 0.0
    base_xg_b: float = 0.0
    final_xg_a: float = 0.0
    final_xg_b: float = 0.0
    game_plan_a: str = "balanced"
    game_plan_b: str = "balanced"
    advantages_a: list[str] = field(default_factory=list)
    advantages_b: list[str] = field(default_factory=list)
    adjustments_a: list[TacticalAdjustmentData] = field(default_factory=list)
    adjustments_b: list[TacticalAdjustmentData] = field(default_factory=list)
    manager_a: str = "Unknown"
    manager_b: str = "Unknown"

    @property
    def total_adjustment_a(self) -> float:
        return sum(a.value for a in self.adjustments_a)

    @property
    def total_adjustment_b(self) -> float:
        return sum(a.value for a in self.adjustments_b)

    @property
    def xg_shift_a(self) -> float:
        return self.final_xg_a - self.base_xg_a

    @property
    def xg_shift_b(self) -> float:
        return self.final_xg_b - self.base_xg_b


@dataclass
class V51ReportData:
    player_influence: dict[str, Any] = field(default_factory=dict)
    tactical_exploitation: dict[str, Any] = field(default_factory=dict)
    match_archetypes: dict[str, Any] = field(default_factory=dict)
    win_conditions_a: dict[str, Any] = field(default_factory=dict)
    win_conditions_b: dict[str, Any] = field(default_factory=dict)
    market_comparison: dict[str, Any] = field(default_factory=dict)
    model_confidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationReport:
    version: str
    team_a: str
    team_b: str
    knockout: bool
    simulations: int
    flag_a: str = ""
    flag_b: str = ""

    mc: MonteCarloResult = field(default_factory=MonteCarloResult)
    v1: V1ReportData | None = None
    v2: V2ReportData | None = None
    v3: V3ReportData | None = None
    v4: V4ReportData | None = None
    v51: V51ReportData | None = None

    @property
    def has_v51_data(self) -> bool:
        return self.v51 is not None

    @property
    def version_label(self) -> str:
        return {
            "v1": "Historical ELO/PELE",
            "v2": "FC26 Player Intelligence",
            "v3": "Dynamic Team State",
            "v4": "Tactical Intelligence",
            "v5": "Match State Simulation",
        }.get(self.version, self.version.upper())

    @property
    def has_v3_data(self) -> bool:
        return self.version in ("v3", "v4", "v5")

    @property
    def has_v4_data(self) -> bool:
        return self.version in ("v4", "v5")
