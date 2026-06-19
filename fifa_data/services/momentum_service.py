from __future__ import annotations

from ..models.dynamic_state import ComponentScore


class MomentumService:
    def __init__(self) -> None:
        self.team_history: dict[str, list[dict]] = {}

    def record_result(self, team: str, goals_for: int, goals_against: int, is_real: bool) -> None:
        if team not in self.team_history:
            self.team_history[team] = []
        self.team_history[team].append({
            "gf": goals_for,
            "ga": goals_against,
            "is_real": is_real,
        })

    def evaluate(self, team: str) -> ComponentScore:
        history = self.team_history.get(team, [])
        if not history:
            return ComponentScore("momentum", 0.0, "No tournament history yet", 0.5)

        recent = history[-5:]
        wins = sum(1 for m in recent if m["gf"] > m["ga"])
        draws = sum(1 for m in recent if m["gf"] == m["ga"])
        losses = sum(1 for m in recent if m["gf"] < m["ga"])
        total_gd = sum(m["gf"] - m["ga"] for m in recent)
        clean_sheets = sum(1 for m in recent if m["ga"] == 0)
        matches = len(recent)

        bonus = 0.0
        sources: list[str] = []

        win_pct = wins / matches if matches > 0 else 0
        if win_pct >= 0.8:
            bonus += 0.025
            sources.append(f"{wins}/{matches} wins: +2.5%")
        elif win_pct >= 0.6:
            bonus += 0.015
            sources.append(f"{wins}/{matches} wins: +1.5%")
        elif win_pct >= 0.4:
            bonus += 0.005
            sources.append(f"{wins}/{matches} wins: +0.5%")
        elif losses >= 2:
            bonus -= 0.02
            sources.append(f"{losses}/{matches} losses: -2%")
        elif losses >= matches / 2:
            bonus -= 0.01
            sources.append(f"{losses}/{matches} losses: -1%")

        if total_gd >= 8:
            bonus += 0.005
            sources.append(f"GD +{total_gd}: +0.5%")
        elif total_gd <= -4:
            bonus -= 0.01
            sources.append(f"GD {total_gd}: -1%")

        if clean_sheets >= 2:
            bonus += 0.005
            sources.append(f"{clean_sheets} clean sheets: +0.5%")

        bonus = max(-0.03, min(0.03, bonus))
        bonus = round(bonus, 4)

        if not sources:
            return ComponentScore("momentum", 0.0, "Neutral momentum", 0.6)

        return ComponentScore(
            "momentum",
            bonus,
            "; ".join(sources),
            min(0.5 + matches * 0.08, 0.9),
        )
