from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MatchContext(Enum):
    GROUP = "group"
    KNOCKOUT = "knockout"
    MUST_WIN = "must_win"
    NEED_DRAW = "need_draw"
    GD_CHASE = "gd_chase"


DEFENSIVE_STYLES = ["low_block", "mid_block", "high_press", "man_marking", "zonal"]


@dataclass(frozen=True)
class TacticalAdjustment:
    category: str
    description: str
    value: float
    confidence: float = 1.0


@dataclass(frozen=True)
class TacticalReport:
    team_a: str
    team_b: str
    base_xg_a: float
    base_xg_b: float
    adjustments_a: list[TacticalAdjustment]
    adjustments_b: list[TacticalAdjustment]
    final_xg_a: float
    final_xg_b: float
    game_plan_a: str
    game_plan_b: str
    advantages_a: list[str]
    advantages_b: list[str]
    context: str = "group"

    def total_adjustment_a(self) -> float:
        return sum(adj.value for adj in self.adjustments_a)

    def total_adjustment_b(self) -> float:
        return sum(adj.value for adj in self.adjustments_b)


@dataclass(frozen=True)
class FormationProfile:
    name: str
    width: float
    central_control: float
    defensive_stability: float
    pressing_capability: float
    space_behind_fullbacks: float
    counter_risk: float
    build_up_support: float


@dataclass(frozen=True)
class ManagerProfile:
    name: str
    risk_tolerance: float
    tactical_flexibility: float
    pressing_preference: float
    defensive_discipline: float
    source: str = ""
    confidence: float = 0.5


GAME_PLANS = ["attacking", "balanced", "counter", "low_block", "high_press"]
