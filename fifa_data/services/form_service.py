from __future__ import annotations

from pathlib import Path

from ..models.dynamic_state import ComponentScore
from ..models.player import Player
from ..models.squad import Squad

HERE = Path(__file__).resolve().parents[1]


class FormService:
    def evaluate(self, team: str, squad: Squad) -> ComponentScore:
        xi = squad.current_starting_xi
        if not xi:
            return ComponentScore("form", 0.0, "Empty starting XI", 1.0)

        total_form = 0.0
        total_pts = 0.0
        player_count = 0

        for player in xi:
            stats = player.stats if isinstance(player.stats, dict) else {}
            form = float(stats.get("form", 0) or 0)
            total_pts_val = float(stats.get("totalPoints", 0) or 0)
            total_form += form
            total_pts += total_pts_val
            player_count += 1

        if player_count == 0:
            return ComponentScore("form", 0.0, "No fantasy form data", 0.3)

        avg_form = total_form / player_count
        avg_pts = total_pts / player_count

        bonus = 0.0
        sources: list[str] = []

        if avg_form >= 4.0:
            bonus += 0.04
            sources.append(f"Avg form {avg_form:.1f}: +4%")
        elif avg_form >= 2.0:
            bonus += 0.02
            sources.append(f"Avg form {avg_form:.1f}: +2%")
        elif avg_form >= 0.5:
            bonus += 0.005
            sources.append(f"Avg form {avg_form:.1f}: +0.5%")
        elif avg_form <= -1.0:
            bonus -= 0.03
            sources.append(f"Avg form {avg_form:.1f} (poor): -3%")
        elif avg_form <= -0.5:
            bonus -= 0.01
            sources.append(f"Avg form {avg_form:.1f}: -1%")

        if avg_pts >= 80:
            bonus += 0.01
            sources.append(f"Avg {avg_pts:.0f} pts: +1%")
        elif avg_pts >= 50:
            bonus += 0.005
            sources.append(f"Avg {avg_pts:.0f} pts: +0.5%")
        elif avg_pts <= 20:
            bonus -= 0.01
            sources.append(f"Avg {avg_pts:.0f} pts (low): -1%")

        bonus = max(-0.05, min(0.05, bonus))
        bonus = round(bonus, 4)

        if not sources:
            return ComponentScore("form", 0.0, "No form data available", 0.3)

        return ComponentScore(
            "form",
            bonus,
            "; ".join(sources),
            min(0.4 + player_count * 0.04, 0.85),
        )
