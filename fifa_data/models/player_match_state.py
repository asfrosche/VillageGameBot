from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlayerMatchState:
    player_name: str
    country: str
    position: str
    energy: float = 100.0
    morale: float = 50.0
    match_rating: float = 6.0
    yellow_cards: int = 0
    red_card: bool = False
    minutes_played: int = 0
    is_substitute: bool = False
    was_substituted: bool = False
    is_injured: bool = False
    goals: int = 0
    assists: int = 0
    fouls: int = 0
    shots: int = 0
    shots_on_target: int = 0
    key_passes: int = 0
    tackles: int = 0
    interceptions: int = 0
    pressing_intensity: float = 1.0

    def apply_energy_effects(self, base_attributes: dict[str, float]) -> dict[str, float]:
        if self.energy > 80:
            mult = 1.0
        elif self.energy > 60:
            mult = 0.95
        elif self.energy > 40:
            mult = 0.88
        elif self.energy > 20:
            mult = 0.80
        else:
            mult = 0.70
        affected = {"pace", "dribbling", "passing", "defending", "reactions", "pressing"}
        modified = dict(base_attributes)
        for attr in affected:
            if attr in modified:
                modified[attr] = round(modified[attr] * mult, 2)
        return modified

    def morale_multiplier(self) -> float:
        if self.morale >= 80:
            return 1.08
        if self.morale >= 60:
            return 1.04
        if self.morale >= 40:
            return 1.00
        if self.morale >= 20:
            return 0.95
        return 0.88

    def rating_contribution(self) -> float:
        return self.match_rating
