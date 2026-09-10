from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ValueLevel(Enum):
    STRONG = "Strong Value"
    MODERATE = "Moderate Value"
    NO_VALUE = "No Value"
    NEGATIVE = "Negative Value"


class ConsensusLevel(Enum):
    STRONG = "Strong"
    MODERATE = "Moderate"
    WEAK = "Weak"


@dataclass
class MarketOdds:
    source: str
    home_decimal: float
    draw_decimal: float
    away_decimal: float
    home_implied: float
    draw_implied: float
    away_implied: float

    @property
    def total_implied(self) -> float:
        return self.home_implied + self.draw_implied + self.away_implied


@dataclass
class NormalizedMarket:
    home_prob: float
    draw_prob: float
    away_prob: float
    sources_used: int = 0
    source_names: list[str] = field(default_factory=list)


@dataclass
class ModelVsMarketEntry:
    team: str
    model_prob: float
    market_prob: float
    edge: float

    @property
    def value_level(self) -> ValueLevel:
        if self.edge >= 0.05:
            return ValueLevel.STRONG
        if self.edge >= 0.03:
            return ValueLevel.MODERATE
        if self.edge >= -0.01:
            return ValueLevel.NO_VALUE
        return ValueLevel.NEGATIVE


@dataclass
class ModelVsMarketComparison:
    team_a: str
    team_b: str
    entries: list[ModelVsMarketEntry] = field(default_factory=list)
    market: NormalizedMarket | None = None
    consensus: ConsensusData | None = None

    @property
    def largest_disagreement(self) -> ModelVsMarketEntry | None:
        return max(self.entries, key=lambda e: abs(e.edge)) if self.entries else None


@dataclass
class ValueDetection:
    team: str
    edge: float
    level: ValueLevel
    description: str = ""


@dataclass
class ConsensusData:
    market_count: int
    home_range: tuple[float, float]
    draw_range: tuple[float, float]
    away_range: tuple[float, float]
    home_consensus: ConsensusLevel
    draw_consensus: ConsensusLevel
    away_consensus: ConsensusLevel
    source_details: list[dict[str, Any]] = field(default_factory=list)
