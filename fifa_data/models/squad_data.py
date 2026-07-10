from __future__ import annotations

from dataclasses import dataclass, field

from .player import Player


@dataclass
class SquadData:
    team: str
    formation: str
    starting_xi: list[Player]
    bench: list[Player] = field(default_factory=list)
    squad: list[Player] = field(default_factory=list)
    provider: str = "unknown"
    source_fixture_id: str | None = None
