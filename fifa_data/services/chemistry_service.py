from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from ..models.dynamic_state import ComponentScore
from ..models.player import Player
from ..models.team_strength import assign_roles

HERE = Path(__file__).resolve().parents[1]


def _normalize(name: str) -> str:
    n = unicodedata.normalize("NFKD", name)
    n = n.encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


class ChemistryService:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        base = Path(data_dir) if data_dir else HERE
        club_path = base / "data" / "club_links.json"
        rel_path = base / "data" / "player_relationships.json"
        self.club_links: dict[str, str] = {}
        self.club_links_norm: dict[str, str] = {}
        self.relationships: dict[str, list[str]] = {}
        if club_path.exists():
            with club_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            for name, club in raw.items():
                key = _normalize(name)
                self.club_links[key] = club
                self.club_links_norm[key] = name
        if rel_path.exists():
            with rel_path.open("r", encoding="utf-8") as f:
                self.relationships = json.load(f)

    def evaluate_for_xi(
        self,
        team: str,
        starting_xi: list[Player],
        formation: str,
    ) -> ComponentScore:
        if not starting_xi:
            return ComponentScore("chemistry", 0.0, "Empty squad", 1.0)

        role_assignments = assign_roles(starting_xi, formation)
        sources: list[str] = []
        bonus = 0.0

        club_groups: dict[str, list[tuple[str, str]]] = {}
        for player, role in role_assignments:
            club = self.club_links.get(_normalize(player.name), "")
            if club:
                club_groups.setdefault(club, []).append((player.name, role))

        pair_bonus = 0.0
        for club, members in club_groups.items():
            if len(members) >= 2:
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        role1 = members[i][1]
                        role2 = members[j][1]
                        pair_bonus += self._pair_bonus(role1, role2)
                sources.append(f"{len(members)} from {club}")

        bonus += min(pair_bonus, 0.04)
        if pair_bonus > 0:
            sources.append(f"Club pairings: +{pair_bonus:.2%}")

        known_partnerships = self.relationships.get(team, [])
        if known_partnerships:
            partnership_hits = 0
            xi_names = {player.name for player in starting_xi}
            for pair in known_partnerships:
                names = [n.strip() for n in pair.split(",")]
                if len(names) == 2 and names[0] in xi_names and names[1] in xi_names:
                    partnership_hits += 1
            if partnership_hits > 0:
                pair_val = min(partnership_hits * 0.005, 0.01)
                bonus += pair_val
                sources.append(f"{partnership_hits} known partnerships: +{pair_val:.2%}")

        bonus = min(bonus, 0.05)
        bonus = round(bonus, 4)

        if not sources:
            return ComponentScore("chemistry", 0.0, "No club links found", 0.7)

        return ComponentScore(
            "chemistry",
            bonus,
            "; ".join(sources),
            min(0.5 + len(sources) * 0.15, 0.95),
        )

    def get_club_groupings(
        self,
        team: str,
        starting_xi: list[Player],
        formation: str,
    ) -> dict[str, object]:
        role_assignments = assign_roles(starting_xi, formation)
        club_groups: dict[str, list[tuple[str, str]]] = {}
        for player, role in role_assignments:
            club = self.club_links.get(_normalize(player.name), "")
            if club:
                club_groups.setdefault(club, []).append((player.name, role))
        xi_names = {p.name for p in starting_xi}
        relationships = self.relationships.get(team, [])
        partnerships = [
            p for p in relationships
            if len(p.split(",")) == 2
            and p.split(",")[0].strip() in xi_names
            and p.split(",")[1].strip() in xi_names
        ]
        return {
            "club_groups": club_groups,
            "partnerships": partnerships,
        }

    @staticmethod
    def _pair_bonus(role1: str, role2: str) -> float:
        cb_pair = {"CB", "FB"}
        fb_wing = {"FB", "WINGER"}
        midfield_pair = {"CM", "DM"}
        attack_pair = {"ST", "WINGER"}

        if {role1, role2} == cb_pair:
            return 0.015
        if role1 in fb_wing and role2 in fb_wing:
            return 0.010
        if role1 in midfield_pair and role2 in midfield_pair:
            return 0.010
        if role1 in attack_pair and role2 in attack_pair:
            return 0.008
        if role1 == "GK" and role2 == "CB":
            return 0.005
        return 0.005
