from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    SHOT = "shot"
    BIG_CHANCE = "big_chance"
    GOAL = "goal"
    ASSIST = "assist"
    CORNER = "corner"
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"
    SUBSTITUTION = "substitution"
    FOUL = "foul"
    PENALTY = "penalty"
    PENALTY_MISSED = "penalty_missed"
    INJURY = "injury"
    SAVE = "save"
    WOODWORK = "woodwork"
    TACTICAL_CHANGE = "tactical_change"
    POSSESSION_PHASE = "possession_phase"


@dataclass
class MatchEvent:
    minute: float
    team: str
    event_type: EventType
    player_name: str | None = None
    secondary_player: str | None = None
    xg: float | None = None
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "minute": self.minute,
            "team": self.team,
            "event_type": self.event_type.value,
            "player_name": self.player_name,
            "secondary_player": self.secondary_player,
            "xg": self.xg,
            "detail": self.detail,
            "data": self.data,
        }
