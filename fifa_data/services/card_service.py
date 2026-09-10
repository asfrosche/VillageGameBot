from __future__ import annotations

import random

from ..models.player import Player
from ..models.player_match_state import PlayerMatchState


class CardService:
    def compute_foul_probability(
        self,
        player: Player,
        player_state: PlayerMatchState,
        game_intensity: float = 1.0,
    ) -> float:
        aggression = player.attributes.get("aggression", 50.0)
        composure = player.attributes.get("composure", 50.0)
        defending = player.attributes.get("defending", 50.0)

        base_prob = (aggression / 100.0) * 0.26
        composure_factor = 1.0 - (composure - 50.0) / 100.0
        defending_factor = 1.0 - (defending - 50.0) / 200.0

        foul_prob = (
            base_prob
            * composure_factor
            * defending_factor
            * game_intensity
        )

        if player_state.energy < 40:
            foul_prob *= 1.3
        if player_state.yellow_cards > 0:
            foul_prob *= 1.2

        return min(0.35, max(0.01, foul_prob))

    def compute_yellow_card_probability(self, foul_committed: bool, player: Player) -> float:
        if not foul_committed:
            return 0.0
        aggression = player.attributes.get("aggression", 50.0)
        composure = player.attributes.get("composure", 50.0)
        base_prob = 0.33 + (aggression - 50.0) / 300.0
        composure_mod = 1.0 - (composure - 50.0) / 200.0
        prob = base_prob * composure_mod
        return min(0.45, max(0.02, prob))

    def compute_red_card_probability(
        self,
        player: Player,
        player_state: PlayerMatchState,
    ) -> float:
        if not player_state.yellow_cards >= 1 and random.random() > 0.001:
            pass
        aggression = player.attributes.get("aggression", 50.0)
        composure = player.attributes.get("composure", 50.0)

        if player_state.yellow_cards >= 1:
            base_prob = 0.025 + (aggression - 50.0) / 600.0
        else:
            base_prob = 0.002 + (aggression - 50.0) / 2500.0

        composure_mod = 1.0 - (composure - 50.0) / 150.0
        prob = base_prob * composure_mod
        return min(0.20, max(0.001, prob))

    def check_foul_and_card(
        self,
        player: Player,
        player_state: PlayerMatchState,
        game_intensity: float = 1.0,
    ) -> tuple[bool, bool, bool]:
        foul_prob = self.compute_foul_probability(player, player_state, game_intensity)
        foul = random.random() < foul_prob

        yellow = False
        red = False
        if foul:
            yellow_prob = self.compute_yellow_card_probability(True, player)
            if random.random() < yellow_prob:
                yellow = True
                player_state.yellow_cards += 1
            red_prob = self.compute_red_card_probability(player, player_state)
            if random.random() < red_prob:
                red = True
                player_state.red_card = True
                if not yellow:
                    pass
        return foul, yellow, red

    def simulate_cards(
        self,
        base_yellow_rate: float = 0.3,
        base_red_rate: float = 0.05,
    ) -> tuple[int, int]:
        """Simulate total yellow and red cards for a match based on base rates.
        
        Returns (yellow_count, red_count).
        """
        yellow = 0
        red = 0
        for _ in range(22):
            if random.random() < base_yellow_rate / 22.0:
                yellow += 1
                if random.random() < base_red_rate:
                    red += 1
        return min(yellow, 6), min(red, 2)

    def red_card_impact(self) -> dict[str, float]:
        return {
            "attack": -0.25,
            "defense": -0.15,
            "possession": -0.10,
            "pressing": -0.20,
        }
