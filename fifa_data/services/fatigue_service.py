from __future__ import annotations

from ..models.player import Player
from ..models.player_match_state import PlayerMatchState


class FatigueService:
    BASE_DECAY = 2.5
    MIN_DECAY = 1.0
    MAX_DECAY = 8.0

    def compute_energy_loss(
        self,
        player: Player,
        player_state: PlayerMatchState,
        minutes_in_phase: int = 15,
        match_intensity: float = 1.0,
        pressing_intensity: float = 1.0,
        is_extra_time: bool = False,
    ) -> float:
        stamina = player.attributes.get("stamina", 70.0)
        age = player.attributes.get("age", 27.0)
        work_rate = player.attributes.get("work_rate", 50.0)
        physical = player.attributes.get("physical", 50.0)
        pace = player.attributes.get("pace", 50.0)

        stamina_factor = max(0.5, 1.0 - (95.0 - stamina) / 100.0)
        age_factor = 1.0 + max(0, age - 27.0) * 0.03
        age_factor = min(age_factor, 2.0)
        work_rate_factor = 1.0 + (work_rate - 50.0) / 100.0
        physical_factor = 1.0 - (physical - 50.0) / 200.0
        pace_factor = 1.0 + (80.0 - pace) / 200.0

        energy_loss = (
            self.BASE_DECAY
            * (1.0 / max(0.5, stamina_factor))
            * age_factor
            * work_rate_factor
            * physical_factor
            * pace_factor
            * match_intensity
            * pressing_intensity
            * (minutes_in_phase / 15.0)
        )

        if is_extra_time:
            energy_loss *= 1.5

        energy_loss = max(self.MIN_DECAY, min(self.MAX_DECAY, energy_loss))
        return round(energy_loss, 2)

    def apply_phase_fatigue(
        self,
        players: list[Player],
        player_states: dict[str, PlayerMatchState],
        minutes_in_phase: int = 15,
        match_intensity: float = 1.0,
        pressing_intensity: float = 1.0,
        is_extra_time: bool = False,
    ) -> dict[str, PlayerMatchState]:
        for player in players:
            state = player_states.get(player.name)
            if state is None or state.was_substituted or state.red_card:
                continue
            loss = self.compute_energy_loss(
                player, state, minutes_in_phase,
                match_intensity, pressing_intensity,
                is_extra_time,
            )
            state.energy = max(0.0, state.energy - loss)
            state.minutes_played += minutes_in_phase
        return player_states

    def get_pressing_intensity(self, game_plan: str) -> float:
        mapping = {
            "high_press": 1.6,
            "attacking": 1.3,
            "balanced": 1.0,
            "counter": 1.1,
            "low_block": 0.7,
            "park_the_bus": 0.5,
        }
        return mapping.get(game_plan, 1.0)

    def get_match_intensity(self, momentum: float) -> float:
        abs_momentum = abs(momentum) / 100.0
        return 1.0 + abs_momentum * 0.3

    def freshness_bonus(self, minutes_played: int) -> float:
        if minutes_played == 0:
            return 1.10
        if minutes_played <= 15:
            return 1.05
        return 1.0
