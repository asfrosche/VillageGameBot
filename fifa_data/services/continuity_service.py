from __future__ import annotations

from ..models.dynamic_state import ComponentScore


class ContinuityService:
    def __init__(self) -> None:
        self.lineup_history: dict[str, list[list[str]]] = {}

    def record_lineup(self, team: str, player_names: list[str]) -> None:
        if team not in self.lineup_history:
            self.lineup_history[team] = []
        self.lineup_history[team].append(list(player_names))

    def evaluate(self, team: str) -> ComponentScore:
        history = self.lineup_history.get(team, [])
        if len(history) < 2:
            return ComponentScore("continuity", 0.0, "First match of tournament", 0.7)

        current = set(history[-1])
        previous = set(history[-2])
        unchanged = len(current & previous)
        total = len(current | previous)
        changes = total - unchanged

        if total == 0:
            return ComponentScore("continuity", 0.0, "No lineup data", 0.5)

        stability = unchanged / len(current) if len(current) > 0 else 0
        bonus = 0.0
        sources: list[str] = []

        if changes == 0:
            bonus = 0.025
            sources.append("Identical XI: +2.5%")
        elif changes == 1:
            bonus = 0.015
            sources.append(f"1 change ({stability:.0%} stable): +1.5%")
        elif changes == 2:
            bonus = 0.005
            sources.append(f"2 changes ({stability:.0%} stable): +0.5%")
        elif changes >= 4:
            bonus = -0.01
            sources.append(f"{changes} changes: -1%")
        elif changes >= 3:
            bonus = -0.005
            sources.append(f"{changes} changes: -0.5%")

        bonus = max(-0.01, min(0.03, bonus))
        bonus = round(bonus, 4)

        return ComponentScore(
            "continuity",
            bonus,
            "; ".join(sources),
            min(0.5 + len(history) * 0.1, 0.9),
        )
