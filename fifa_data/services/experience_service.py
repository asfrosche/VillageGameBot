from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from ..models.dynamic_state import ComponentScore
from ..models.player import Player
from ..models.squad import Squad

HERE = Path(__file__).resolve().parents[1]


def _normalize(name: str) -> str:
    n = unicodedata.normalize("NFKD", name)
    n = n.encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


class ExperienceService:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        base = Path(data_dir) if data_dir else HERE
        exp_path = base / "data" / "player_experience.json"
        self.experience_data: dict[str, dict] = {}
        self.exp_norm: dict[str, dict] = {}
        if exp_path.exists():
            with exp_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            for name, data in raw.items():
                self.exp_norm[_normalize(name)] = data

    def evaluate(
        self,
        team: str,
        squad: Squad,
        is_knockout: bool = False,
        is_extra_time: bool = False,
        is_penalties: bool = False,
    ) -> ComponentScore:
        xi = squad.current_starting_xi
        if not xi:
            return ComponentScore("experience", 0.0, "Empty starting XI", 1.0)

        total_caps = 0
        total_wc = 0
        captain_count = 0
        player_count = 0
        sources: list[str] = []

        for player in xi:
            exp = self.exp_norm.get(_normalize(player.name), {})
            caps = exp.get("international_caps", 0)
            wc = exp.get("world_cups", 0)
            is_cap = exp.get("is_captain", False)

            total_caps += caps
            total_wc += wc
            if is_cap:
                captain_count += 1
            player_count += 1

        if player_count == 0:
            return ComponentScore("experience", 0.0, "No players in XI", 1.0)

        avg_caps = total_caps / player_count
        avg_wc = total_wc / player_count

        bonus = 0.0

        if avg_caps >= 80:
            bonus += 0.02
            sources.append(f"Avg {avg_caps:.0f} caps: +2%")
        elif avg_caps >= 50:
            bonus += 0.01
            sources.append(f"Avg {avg_caps:.0f} caps: +1%")
        elif avg_caps >= 30:
            bonus += 0.005
            sources.append(f"Avg {avg_caps:.0f} caps: +0.5%")
        else:
            bonus -= 0.01
            sources.append(f"Avg {avg_caps:.0f} caps (inexperienced): -1%")

        if avg_wc >= 2.0:
            bonus += 0.01
            sources.append(f"Avg {avg_wc:.1f} WCs: +1%")
        elif avg_wc >= 1.0:
            bonus += 0.005
            sources.append(f"Avg {avg_wc:.1f} WCs: +0.5%")

        if captain_count >= 3:
            bonus += 0.005
            sources.append(f"{captain_count} leaders: +0.5%")

        if is_knockout:
            bonus += 0.005
            sources.append("Knockout experience: +0.5%")
        if is_extra_time:
            bonus += 0.005
            sources.append("Extra time experience: +0.5%")
        if is_penalties:
            bonus += 0.005
            sources.append("Penalty experience: +0.5%")

        bonus = max(-0.02, min(0.03, bonus))
        bonus = round(bonus, 4)

        return ComponentScore(
            "experience",
            bonus,
            "; ".join(sources),
            min(0.5 + player_count * 0.04, 0.9),
        )
