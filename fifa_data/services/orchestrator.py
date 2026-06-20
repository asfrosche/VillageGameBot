from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Callable

from ..engines.base_engine import MatchEngine


class TournamentOrchestrator:
    def __init__(
        self,
        groups: dict[str, list[str]],
        match_engine: MatchEngine,
        matches_file: str | os.PathLike[str] | None = None,
        team_name_map: dict[str, str] | None = None,
        generate_goal_minutes: Callable[[int, int], tuple[list[int], list[int]]] | None = None,
    ) -> None:
        self.groups = groups
        self.match_engine = match_engine
        self.matches_file = Path(matches_file) if matches_file else None
        self.team_name_map = team_name_map or {}
        self.generate_goal_minutes = generate_goal_minutes or self._generate_goals
        self.last_match_debugs: list[str] = []
        self._debug: bool = False

    def run(self, debug: bool = False) -> dict[str, object]:
        self.last_match_debugs = []
        self._debug = debug
        matches_data = self._load_matches()
        real_results = self._real_group_results(matches_data)

        groups_data = {}
        group_winners = {}
        group_runners = {}
        all_third = []

        for gid in sorted(self.groups.keys()):
            teams = self.groups[gid]
            table = {team: {"pts": 0, "gd": 0, "gf": 0, "ga": 0} for team in teams}
            match_list = [
                (teams[0], teams[1]),
                (teams[2], teams[3]),
                (teams[0], teams[2]),
                (teams[3], teams[1]),
                (teams[1], teams[2]),
                (teams[3], teams[0]),
            ]
            matches = []
            for team1, team2 in match_list:
                real = self._get_real_result(real_results, gid, team1, team2)
                if real:
                    goals1, goals2 = real
                    is_real = True
                else:
                    goals1, goals2 = self.match_engine.simulate_match(team1, team2, can_draw=True)
                    is_real = False
                    self._capture_debug(debug)
                self.match_engine.notify_match(team1, team2, goals1, goals2, is_real)
                home_minutes, away_minutes = self.generate_goal_minutes(goals1, goals2)
                matches.append(
                    {
                        "home": team1,
                        "away": team2,
                        "home_goals": goals1,
                        "away_goals": goals2,
                        "home_goal_minutes": home_minutes,
                        "away_goal_minutes": away_minutes,
                        "is_real": is_real,
                    }
                )
                table[team1]["pts"] += 3 if goals1 > goals2 else (1 if goals1 == goals2 else 0)
                table[team2]["pts"] += 3 if goals2 > goals1 else (1 if goals1 == goals2 else 0)
                table[team1]["gd"] += goals1 - goals2
                table[team2]["gd"] += goals2 - goals1
                table[team1]["gf"] += goals1
                table[team2]["gf"] += goals2

            sorted_teams = sorted(
                table.items(),
                key=lambda item: (item[1]["pts"], item[1]["gd"], item[1]["gf"]),
                reverse=True,
            )
            table_display = [
                (rank, team, data["pts"], data["gd"], data["gf"])
                for rank, (team, data) in enumerate(sorted_teams, 1)
            ]
            group_winners[gid] = sorted_teams[0][0]
            group_runners[gid] = sorted_teams[1][0]
            all_third.append(
                (
                    gid,
                    sorted_teams[2][0],
                    sorted_teams[2][1]["pts"],
                    sorted_teams[2][1]["gd"],
                    sorted_teams[2][1]["gf"],
                )
            )
            groups_data[gid] = {
                "matches": matches,
                "table": table_display,
            }

        all_third.sort(key=lambda item: (item[2], item[3], item[4]), reverse=True)
        best_thirds = all_third[:8]
        knockout = self._resolve_knockout(group_winners, group_runners, best_thirds)

        third_place = self._third_place_match(knockout)
        champion = None
        if len(knockout) >= 5 and knockout[4] and knockout[4][0]:
            champion = knockout[4][0]["winner"]

        stats = {
            "real_count": len(real_results),
            "total_group_matches": sum(6 for _ in self.groups),
            "knockout_matches": sum(len([match for match in round_matches if match]) for round_matches in knockout),
            "third_place": 1 if third_place else 0,
        }

        result = {
            "groups": groups_data,
            "third_placed": all_third,
            "best_thirds": best_thirds,
            "knockout": knockout,
            "third_place": third_place,
            "champion": champion,
            "stats": stats,
        }
        if debug and self.last_match_debugs:
            result["debug"] = self.last_match_debugs
        return result

    def _load_matches(self) -> dict[str, object]:
        if not self.matches_file or not self.matches_file.exists():
            return {"completed": []}
        with self.matches_file.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _real_group_results(self, matches_data: dict[str, object]) -> dict[tuple[str, str, str], tuple[int, int]]:
        real_results: dict[tuple[str, str, str], tuple[int, int]] = {}
        for match in matches_data.get("completed", []):
            home_name = self._map_team_name(match.get("home", {}).get("name", ""))
            away_name = self._map_team_name(match.get("away", {}).get("name", ""))
            group_id = str(match.get("group", "")).replace("Group ", "")
            real_results[(group_id, home_name, away_name)] = (
                int(match.get("home", {}).get("score", 0)),
                int(match.get("away", {}).get("score", 0)),
            )
        return real_results

    def _get_real_result(
        self,
        real_results: dict[tuple[str, str, str], tuple[int, int]],
        group_id: str,
        team1: str,
        team2: str,
    ) -> tuple[int, int] | None:
        key = (group_id, team1, team2)
        if key in real_results:
            return real_results[key]
        reverse_key = (group_id, team2, team1)
        if reverse_key in real_results:
            goals1, goals2 = real_results[reverse_key]
            return goals2, goals1
        return None

    def _resolve_knockout(
        self,
        group_winners: dict[str, str],
        group_runners: dict[str, str],
        best_thirds: list[tuple[object, ...]],
    ) -> list[list[dict[str, object] | None]]:
        slots = [
            "3ABCDF",
            "3CDFGH",
            "3BEFIJ",
            "3AEHIJ",
            "3CEFHI",
            "3EHIJK",
            "3EFGLI",
            "3DEIJL",
        ]
        thirds_map = {
            slot: best_thirds[index][1] if index < len(best_thirds) else "TBD"
            for index, slot in enumerate(slots)
        }
        bracket = [
            ("1E", "3ABCDF"),
            ("1I", "3CDFGH"),
            ("2A", "2B"),
            ("1F", "2C"),
            ("2K", "2L"),
            ("1H", "2J"),
            ("1D", "3BEFIJ"),
            ("1G", "3AEHIJ"),
            ("1C", "2F"),
            ("2E", "2I"),
            ("1A", "3CEFHI"),
            ("1L", "3EHIJK"),
            ("1J", "2H"),
            ("2D", "2G"),
            ("1B", "3EFGLI"),
            ("1K", "3DEIJL"),
        ]

        def resolve_team(code: str) -> str:
            if code.startswith("1"):
                return group_winners.get(code[1:], "TBD")
            if code.startswith("2"):
                return group_runners.get(code[1:], "TBD")
            return thirds_map.get(code, "TBD")

        round_names = ["R32", "R16", "QF", "SF", "Final"]
        knockout: list[list[dict[str, object] | None]] = []
        current_pairs = [(resolve_team(pair[0]), resolve_team(pair[1])) for pair in bracket]
        for round_name in round_names:
            matches = []
            next_pairs = []
            for team1, team2 in current_pairs:
                if team1 == "TBD" or team2 == "TBD":
                    matches.append(None)
                    next_pairs.append(None)
                    continue
                goals1, goals2 = self.match_engine.simulate_match(
                    team1,
                    team2,
                    can_draw=(round_name == "R32"),
                )
                self._capture_debug(self._debug)
                self.match_engine.notify_match(team1, team2, goals1, goals2, False)
                winner = team1 if goals1 > goals2 else (team2 if goals2 > goals1 else random.choice([team1, team2]))
                home_minutes, away_minutes = self.generate_goal_minutes(goals1, goals2)
                matches.append(
                    {
                        "home": team1,
                        "away": team2,
                        "home_goals": goals1,
                        "away_goals": goals2,
                        "home_goal_minutes": home_minutes,
                        "away_goal_minutes": away_minutes,
                        "winner": winner,
                        "is_real": False,
                    }
                )
                next_pairs.append(winner)
            knockout.append(matches)
            current_pairs = [
                (next_pairs[index], next_pairs[index + 1])
                for index in range(0, len(next_pairs) - 1, 2)
                if next_pairs[index] and next_pairs[index + 1]
            ]
        return knockout

    def _third_place_match(self, knockout: list[list[dict[str, object] | None]]) -> dict[str, object] | None:
        semi_finals = knockout[3] if len(knockout) > 3 else []
        semi_losers = []
        for match in semi_finals:
            if not match:
                continue
            winner = match["winner"]
            semi_losers.append(match["away"] if winner == match["home"] else match["home"])
        if len(semi_losers) != 2:
            return None
        team1, team2 = semi_losers
        goals1, goals2 = self.match_engine.simulate_match(team1, team2, can_draw=False)
        self._capture_debug(self._debug)
        self.match_engine.notify_match(team1, team2, goals1, goals2, False)
        home_minutes, away_minutes = self.generate_goal_minutes(goals1, goals2)
        winner = team1 if goals1 > goals2 else team2
        return {
            "home": team1,
            "away": team2,
            "home_goals": goals1,
            "away_goals": goals2,
            "home_goal_minutes": home_minutes,
            "away_goal_minutes": away_minutes,
            "winner": winner,
            "is_real": False,
        }

    def _capture_debug(self, enabled: bool) -> None:
        if not enabled:
            return
        debug_text = getattr(self.match_engine, "last_match_debug", "")
        if debug_text:
            self.last_match_debugs.append(debug_text)

    def _map_team_name(self, name: str) -> str:
        return self.team_name_map.get(name, name)

    @staticmethod
    def _generate_goals(goals1: int, goals2: int) -> tuple[list[int], list[int]]:
        minutes = list(range(1, 91))
        random.shuffle(minutes)
        home_goals = sorted(minutes[:goals1])
        away_goals = sorted(minutes[goals1 : goals1 + goals2])
        return home_goals, away_goals
