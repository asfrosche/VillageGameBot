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


class LeadershipService:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        base = Path(data_dir) if data_dir else HERE
        exp_path = base / "data" / "player_experience.json"
        self.exp_norm: dict[str, dict] = {}
        if exp_path.exists():
            with exp_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            for name, data in raw.items():
                self.exp_norm[_normalize(name)] = data

    def get_leadership_details(self, xi: list[Player]) -> dict[str, object]:
        captains = 0
        veteran_count = 0
        wc_veterans = 0
        captain_names = []
        for player in xi:
            exp = self.exp_norm.get(_normalize(player.name), {})
            if exp.get("is_captain"):
                captains += 1
                captain_names.append(player.name)
            if exp.get("international_caps", 0) >= 80:
                veteran_count += 1
            if exp.get("world_cups", 0) >= 2:
                wc_veterans += 1
        return {
            "captain_count": captains,
            "captain_names": captain_names,
            "veteran_count": veteran_count,
            "wc_veterans": wc_veterans,
        }

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
            return ComponentScore("leadership", 0.0, "Empty starting XI", 1.0)

        captains = 0
        veteran_count = 0
        wc_veterans = 0
        sources: list[str] = []

        for player in xi:
            exp = self.exp_norm.get(_normalize(player.name), {})
            if exp.get("is_captain"):
                captains += 1
            if exp.get("international_caps", 0) >= 80:
                veteran_count += 1
            if exp.get("world_cups", 0) >= 2:
                wc_veterans += 1

        bonus = 0.0

        if captains >= 2:
            bonus += 0.010
            sources.append(f"{captains} captains: +1%")
        elif captains >= 1:
            bonus += 0.005
            sources.append(f"{captains} captain: +0.5%")

        if veteran_count >= 5:
            bonus += 0.005
            sources.append(f"{veteran_count} veterans: +0.5%")
        elif veteran_count >= 3:
            bonus += 0.003
            sources.append(f"{veteran_count} veterans: +0.3%")

        if wc_veterans >= 4:
            bonus += 0.005
            sources.append(f"{wc_veterans} WC veterans: +0.5%")

        if is_knockout:
            bonus += 0.003
            sources.append("Knockout composure: +0.3%")
        if is_extra_time:
            bonus += 0.002
            sources.append("Extra time composure: +0.2%")
        if is_penalties:
            bonus += 0.005
            sources.append("Penalty composure: +0.5%")

        bonus = max(0.0, min(0.02, bonus))
        bonus = round(bonus, 4)

        if not sources:
            return ComponentScore("leadership", 0.0, "No notable leadership", 0.6)

        return ComponentScore(
            "leadership",
            bonus,
            "; ".join(sources),
            min(0.5 + captains * 0.1 + veteran_count * 0.05, 0.9),
        )
