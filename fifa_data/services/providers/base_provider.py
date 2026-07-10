from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ...models.player import Player
from ...models.squad_data import SquadData


@dataclass
class ValidationResult:
    valid: bool = False
    reason: str = ""
    player_count: int = 0
    has_gk: bool = False
    has_formation: bool = False
    duplicates: list[str] = field(default_factory=list)
    unknown_players: list[str] = field(default_factory=list)


KNOWN_FORMATIONS = {
    "4-3-3", "4-2-3-1", "4-4-2", "4-1-4-1", "4-5-1",
    "3-4-3", "3-5-2", "3-4-2-1", "3-5-1-1",
    "5-3-2", "5-4-1", "5-2-3",
    "4-3-2-1", "4-2-2-2",
    "3-4-1-2", "3-6-1",
    "4-6-0",
}


def validate_squad_data(data: SquadData) -> ValidationResult:
    result = ValidationResult()

    if not data.starting_xi:
        result.reason = "Empty starting XI"
        return result

    result.player_count = len(data.starting_xi)
    if result.player_count != 11:
        result.reason = f"Expected 11 players, got {result.player_count}"
        return result

    names = []
    for p in data.starting_xi:
        names.append(p.name)
        pos = p.normalized_positions()
        if "GK" in pos:
            result.has_gk = True

    if not result.has_gk:
        result.reason = "No goalkeeper (GK) in starting XI"
        return result

    seen = set()
    for name in names:
        if name in seen:
            result.duplicates.append(name)
        seen.add(name)
    if result.duplicates:
        result.reason = f"Duplicate players: {', '.join(result.duplicates)}"
        return result

    if data.formation:
        f = data.formation.strip()
        if f in KNOWN_FORMATIONS:
            result.has_formation = True
        else:
            parts = f.replace("-", " ").split()
            if len(parts) >= 3 and all(p.isdigit() for p in parts):
                result.has_formation = True

    for p in data.starting_xi:
        if not p.name or not p.positions:
            result.unknown_players.append(p.name or "???")

    result.valid = True
    result.reason = "OK"
    return result


class SquadProvider(ABC):

    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def get_starting_xi(
        self, team: str, fixture_id: str | None = None,
    ) -> SquadData | None:
        ...

    def get_squad(self, team: str) -> list[Player] | None:
        return None

    def get_formation(self, team: str, fixture_id: str | None = None) -> str | None:
        data = self.get_starting_xi(team, fixture_id)
        return data.formation if data else None

    def get_bench(self, team: str, fixture_id: str | None = None) -> list[Player]:
        data = self.get_starting_xi(team, fixture_id)
        return data.bench if data else []
