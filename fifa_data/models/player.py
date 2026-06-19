from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Availability:
    available: bool = True
    injured: bool = False
    suspended: bool = False
    expected_return_match: int | None = None

    def is_available(self, match_number: int | None = None) -> bool:
        if not self.available or self.injured or self.suspended:
            return False
        if match_number is not None and self.expected_return_match is not None:
            return match_number >= self.expected_return_match
        return True


@dataclass(frozen=True)
class Player:
    name: str
    country: str
    positions: tuple[str, ...]
    attributes: dict[str, float] = field(default_factory=dict)
    availability: Availability = field(default_factory=Availability)
    fantasy_id: int | None = None
    squad_id: int | None = None
    roster_rating: float | None = None
    roster_tier: str | None = None
    price: float = 0.0
    status: str | None = None
    stats: dict[str, object] = field(default_factory=dict)

    def is_available(self, match_number: int | None = None) -> bool:
        return self.availability.is_available(match_number)

    def normalized_positions(self) -> tuple[str, ...]:
        return tuple(position.upper() for position in self.positions)
