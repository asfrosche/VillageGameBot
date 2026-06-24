from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from ..models.dynamic_state import ComponentScore
from ..models.player import Player
from ..models.squad import Squad
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
            sources.append(f"Club pairings: +{min(pair_bonus, 0.04):.2%}")

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
        changes = len(current) - unchanged

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

    def get_player_details(self, xi: list[Player]) -> list[dict[str, object]]:
        result = []
        for player in xi:
            exp = self.exp_norm.get(_normalize(player.name), {})
            result.append({
                "name": player.name,
                "caps": exp.get("international_caps", 0),
                "world_cups": exp.get("world_cups", 0),
                "is_captain": exp.get("is_captain", False),
            })
        return result

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
