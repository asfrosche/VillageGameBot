from __future__ import annotations

from dataclasses import dataclass

from ..models.player import Player


@dataclass
class SubstitutionEvent:
    minute: int
    team: str
    player_off: str
    player_on: str
    reason: str  # tactical, fatigue, injury, card
