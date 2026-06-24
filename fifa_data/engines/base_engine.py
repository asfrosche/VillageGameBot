from __future__ import annotations


class MatchEngine:
    def simulate_match(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
    ) -> tuple[int, int]:
        raise NotImplementedError

    def notify_match(self, team1: str, team2: str, goals1: int, goals2: int, is_real: bool) -> None:
        pass
