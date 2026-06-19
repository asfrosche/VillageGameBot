from __future__ import annotations

from dataclasses import dataclass, field

from .player import Player
from .team_strength import role_for_player, role_rating


@dataclass
class Squad:
    country: str
    players: list[Player]
    formation: str
    preferred_starting_xi: list[Player]
    current_starting_xi: list[Player] = field(init=False)

    def __post_init__(self) -> None:
        self.current_starting_xi = list(self.preferred_starting_xi)

    @property
    def bench_players(self) -> list[Player]:
        starter_names = {player.name for player in self.current_starting_xi}
        return [player for player in self.players if player.name not in starter_names]

    def replace_player(self, player_to_replace: Player) -> Player | None:
        if player_to_replace not in self.current_starting_xi:
            return None

        role = role_for_player(player_to_replace, self.formation)
        current_names = {player.name for player in self.current_starting_xi}
        candidates = [
            player
            for player in self.players
            if player.name not in current_names
            and player.is_available()
            and role_for_player(player, self.formation) == role
        ]
        if not candidates:
            candidates = [
                player
                for player in self.players
                if player.name not in current_names
                and player.is_available()
                and _shares_broad_position(player, player_to_replace)
            ]
        if not candidates:
            candidates = [
                player
                for player in self.players
                if player.name not in current_names and player.is_available()
            ]

        candidates.sort(
            key=lambda player: (
                role_rating(player, role),
                player.roster_rating or 0,
                player.price,
            ),
            reverse=True,
        )
        replacement = candidates[0]
        self.current_starting_xi = [
            replacement if player == player_to_replace else player
            for player in self.current_starting_xi
        ]
        return replacement


def _shares_broad_position(left: Player, right: Player) -> bool:
    left_role = role_for_player(left)
    right_role = role_for_player(right)
    if left_role == right_role:
        return True
    attack_roles = {"ST", "WINGER"}
    midfield_roles = {"CM", "DM"}
    defense_roles = {"CB", "FB"}
    return (
        left_role in attack_roles and right_role in attack_roles
        or left_role in midfield_roles and right_role in midfield_roles
        or left_role in defense_roles and right_role in defense_roles
    )
