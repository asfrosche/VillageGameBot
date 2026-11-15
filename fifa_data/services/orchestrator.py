from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Callable

from ..engines.base_engine import MatchEngine
from .stages import Stage, StageContext, StagePipeline

# World Cup flow: the tournament stages the original simulator already had
# (group stage, then a knockout ladder down to the final, plus the play-off).
WORLDCUP_STAGES = [
    "Group Stage",
    "Round of 32",
    "Round of 16",
    "Quarter-Finals",
    "Semi-Finals",
    "Final",
    "Third-Place Play-off",
]

# Premier League flow: its own logical loop. The double round-robin season is
# the "group stage" equivalent; resolving the table (title, Europe, relegation)
# is the finale. Nothing from the World Cup list appears here.
PREMIER_LEAGUE_STAGES = [
    "Premier League Season",
    "Standings Resolution",
]


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
        """Run the whole World Cup through its stage loop."""
        return self.run_through(WORLDCUP_STAGES[-1], debug=debug)

    def run_through(self, stage_name: str, debug: bool = False) -> dict[str, object]:
        """Run the stage pipeline up to and including ``stage_name``.

        This is the same logical loop as :meth:`run` but lets the caller stop
        at any checkpoint (e.g. "Group Stage") and inspect the partial output.
        """
        self.last_match_debugs = []
        self._debug = debug
        stages = self._stages()
        pipeline = StagePipeline(stages)
        ctx = StageContext(orchestrator=self, debug=debug, matches_data=self._load_matches())
        completed = pipeline.run(ctx, stop_after=stage_name)
        return self._assemble(ctx, stages, completed)

    def _stages(self) -> list[Stage]:
        return [
            _WorldCupGroupStage(),
            _WorldCupKnockoutRoundStage("Round of 32", "R32"),
            _WorldCupKnockoutRoundStage("Round of 16", "R16"),
            _WorldCupKnockoutRoundStage("Quarter-Finals", "QF"),
            _WorldCupKnockoutRoundStage("Semi-Finals", "SF"),
            _WorldCupKnockoutRoundStage("Final", "Final"),
            _WorldCupThirdPlaceStage(),
        ]

    def valid_stages(self) -> list[str]:
        return [stage.name for stage in self._stages()]

    def _assemble(
        self,
        ctx: StageContext,
        stages: list[Stage],
        completed: list[str],
    ) -> dict[str, object]:
        out = ctx.outputs
        result: dict[str, object] = {}
        group_output = out.get("Group Stage")
        if group_output:
            result["groups"] = group_output["groups"]
            result["third_placed"] = group_output["third_placed"]
            result["best_thirds"] = group_output["best_thirds"]
        knockout = ctx.state.get("knockout")
        if knockout is not None:
            result["knockout"] = knockout
            result["third_place"] = out.get("Third-Place Play-off")
            champion = None
            if len(knockout) >= 5 and knockout[4] and knockout[4][0]:
                champion = knockout[4][0]["winner"]
            result["champion"] = champion
        result["stats"] = {
            "real_count": ctx.state.get("real_group_count", 0) + ctx.state.get("real_ko_count", 0),
            "total_group_matches": sum(6 for _ in self.groups),
            "knockout_matches": sum(
                len([match for match in round_matches if match]) for round_matches in (knockout or [])
            ),
            "third_place": 1 if out.get("Third-Place Play-off") else 0,
        }
        result["stages"] = [stage.name for stage in stages]
        if len(completed) < len(stages):
            result["completed_stages"] = completed
            result["is_partial"] = True
        if debug := self._debug:
            if self.last_match_debugs:
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

    def _real_knockout_results(self, matches_data: dict[str, object]) -> dict[tuple[str, str], tuple[int, int]]:
        """Build a lookup of all completed matches by (team1, team2) regardless of stage."""
        results: dict[tuple[str, str], tuple[int, int]] = {}
        for match in matches_data.get("completed", []):
            home = self._map_team_name(match.get("home", {}).get("name", ""))
            away = self._map_team_name(match.get("away", {}).get("name", ""))
            hs = int(match.get("home", {}).get("score", 0))
            aas = int(match.get("away", {}).get("score", 0))
            results[(home, away)] = (hs, aas)
        return results

    def _knockout_pairs(
        self,
        group_winners: dict[str, str],
        group_runners: dict[str, str],
        best_thirds: list[tuple[object, ...]],
    ) -> list[tuple[str, str]]:
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

        return [(resolve_team(pair[0]), resolve_team(pair[1])) for pair in bracket]

    def _play_knockout_round(
        self,
        round_key: str,
        current_pairs: list[tuple[str, str]],
        real_ko: dict[tuple[str, str], tuple[int, int]],
    ) -> dict[str, object]:
        matches: list[dict[str, object] | None] = []
        next_pairs: list[str | None] = []
        for team1, team2 in current_pairs:
            if team1 == "TBD" or team2 == "TBD":
                matches.append(None)
                next_pairs.append(None)
                continue
            key = (team1, team2)
            rev_key = (team2, team1)
            if key in real_ko:
                goals1, goals2 = real_ko[key]
                is_real = True
            elif rev_key in real_ko:
                g2, g1 = real_ko[rev_key]
                goals1, goals2 = g1, g2
                is_real = True
            else:
                goals1, goals2 = self.match_engine.simulate_match(
                    team1,
                    team2,
                    can_draw=(round_key == "R32"),
                )
                is_real = False
                self._capture_debug(self._debug)
            self.match_engine.notify_match(team1, team2, goals1, goals2, is_real)
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
                    "is_real": is_real,
                }
            )
            next_pairs.append(winner)
        next_round_pairs = [
            (next_pairs[index], next_pairs[index + 1])
            for index in range(0, len(next_pairs) - 1, 2)
            if next_pairs[index] and next_pairs[index + 1]
        ]
        return {"matches": matches, "next_pairs": next_round_pairs}

    def _resolve_knockout(
        self,
        group_winners: dict[str, str],
        group_runners: dict[str, str],
        best_thirds: list[tuple[object, ...]],
        real_ko_results: dict[tuple[str, str], tuple[int, int]] | None = None,
    ) -> list[list[dict[str, object] | None]]:
        real_ko = real_ko_results or {}
        current_pairs = self._knockout_pairs(group_winners, group_runners, best_thirds)
        knockout: list[list[dict[str, object] | None]] = []
        for round_key in ("R32", "R16", "QF", "SF", "Final"):
            played = self._play_knockout_round(round_key, current_pairs, real_ko)
            knockout.append(played["matches"])
            current_pairs = played["next_pairs"]
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


class _WorldCupGroupStage(Stage):
    """Group phase: every nation plays three round-robin games and is ranked."""

    name = "Group Stage"

    def run(self, ctx: StageContext) -> dict[str, object]:
        orch = ctx.orchestrator
        real_group_results = orch._real_group_results(ctx.matches_data)
        real_ko_results = orch._real_knockout_results(ctx.matches_data)
        ctx.state["real_group_count"] = len(real_group_results)
        ctx.state["real_ko_count"] = len(real_ko_results)

        groups_data = {}
        group_winners = {}
        group_runners = {}
        all_third = []

        for gid in sorted(orch.groups.keys()):
            teams = orch.groups[gid]
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
                real = orch._get_real_result(real_group_results, gid, team1, team2)
                if real:
                    goals1, goals2 = real
                    is_real = True
                else:
                    goals1, goals2 = orch.match_engine.simulate_match(team1, team2, can_draw=True)
                    is_real = False
                    orch._capture_debug(ctx.debug)
                orch.match_engine.notify_match(team1, team2, goals1, goals2, is_real)
                home_minutes, away_minutes = orch.generate_goal_minutes(goals1, goals2)
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
        ctx.state["group_winners"] = group_winners
        ctx.state["group_runners"] = group_runners
        ctx.state["best_thirds"] = best_thirds
        ctx.state["real_ko_results"] = real_ko_results
        ctx.state["current_pairs"] = orch._knockout_pairs(group_winners, group_runners, best_thirds)
        return {"groups": groups_data, "third_placed": all_third, "best_thirds": best_thirds}


class _WorldCupKnockoutRoundStage(Stage):
    """One knockout round; winners feed the next round's fixtures."""

    def __init__(self, name: str, round_key: str) -> None:
        self.name = name
        self.round_key = round_key

    def run(self, ctx: StageContext) -> list[dict[str, object] | None]:
        orch = ctx.orchestrator
        real_ko = ctx.state.get("real_ko_results", {})
        current_pairs = ctx.state.get("current_pairs", [])
        played = orch._play_knockout_round(self.round_key, current_pairs, real_ko)
        ctx.state["current_pairs"] = played["next_pairs"]
        knockout = ctx.state.setdefault("knockout", [])
        knockout.append(played["matches"])
        return played["matches"]


class _WorldCupThirdPlaceStage(Stage):
    """Losers of the semi-finals meet once more for bronze."""

    name = "Third-Place Play-off"

    def run(self, ctx: StageContext) -> dict[str, object] | None:
        knockout = ctx.state.get("knockout")
        if not knockout:
            return None
        return ctx.orchestrator._third_place_match(knockout)


class LeagueOrchestrator:
    """Double round-robin league simulator (Premier League style).

    Mirrors the ``TournamentOrchestrator.run()`` output shapes: completed
    matches from the league's matches file are replayed with their real
    scorelines, everything else is simulated by the given match engine.

    Home advantage is applied as a temporary Elo nudge around each simulated
    home fixture so the shared ``team_metrics`` table is never mutated.
    """

    def __init__(
        self,
        teams: list[str],
        match_engine: MatchEngine,
        matches_file: str | os.PathLike[str] | None = None,
        team_name_map: dict[str, str] | None = None,
        home_elo_bonus: float = 45.0,
        generate_goal_minutes: Callable[[int, int], tuple[list[int], list[int]]] | None = None,
    ) -> None:
        self.teams = list(teams)
        self.match_engine = match_engine
        self.matches_file = Path(matches_file) if matches_file else None
        self.team_name_map = team_name_map or {}
        self.home_elo_bonus = home_elo_bonus
        self.generate_goal_minutes = generate_goal_minutes or TournamentOrchestrator._generate_goals
        self.last_match_debugs: list[str] = []
        self._debug: bool = False

    def run(self, debug: bool = False) -> dict[str, object]:
        """Run the whole Premier League season through its own stage loop."""
        return self.run_through(PREMIER_LEAGUE_STAGES[-1], debug=debug)

    def run_through(self, stage_name: str, debug: bool = False) -> dict[str, object]:
        """Run the league stage pipeline up to and including ``stage_name``.

        The league has its own logical loop ("Premier League Season" then
        "Standings Resolution") - it never touches the World Cup stages.
        """
        self.last_match_debugs = []
        self._debug = debug
        stages = self._stages()
        pipeline = StagePipeline(stages)
        ctx = StageContext(orchestrator=self, debug=debug, matches_data=self._load_matches())
        completed = pipeline.run(ctx, stop_after=stage_name)
        return self._assemble(ctx, stages, completed)

    def _stages(self) -> list[Stage]:
        return [_LeagueSeasonStage(), _LeagueResolutionStage()]

    def valid_stages(self) -> list[str]:
        return [stage.name for stage in self._stages()]

    def _assemble(
        self,
        ctx: StageContext,
        stages: list[Stage],
        completed: list[str],
    ) -> dict[str, object]:
        season = ctx.outputs.get("Premier League Season")
        resolution = ctx.outputs.get("Standings Resolution")
        result: dict[str, object] = {"competition": "league"}
        if resolution:
            result["table"] = resolution["table"]
        if season:
            result["matches"] = season["matches"]
        if resolution:
            result["champion"] = resolution["champion"]
            result["top4"] = resolution["top4"]
            result["relegated"] = resolution["relegated"]
            result["stats"] = resolution["stats"]
        if season:
            result["matchdays"] = season["matchday_count"]
        result["stages"] = [stage.name for stage in stages]
        if len(completed) < len(stages):
            result["completed_stages"] = completed
            result["is_partial"] = True
        if debug := self._debug:
            if self.last_match_debugs:
                result["debug"] = self.last_match_debugs
        return result

    # ── Fixture generation ────────────────────────────────────────

    def _fixture_list(self, real_results: dict[tuple[str, str], tuple[int, int]]) -> list[tuple[int, str, str]]:
        """Fixture list for the season.

        Prefers the competition's real fixture list (completed + upcoming from
        the matches file) so live results merge onto the correct matchdays.
        Falls back to a circle-method round robin when the file is missing or
        does not cover the whole season.
        """
        required = len(self.teams) * (len(self.teams) - 1)
        data = self._load_matches()
        pairs: list[tuple[int, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for match in list(data.get("upcoming", [])) + list(data.get("completed", [])):
            home = self._map_team_name(str(match.get("home", {}).get("name", "")))
            away = self._map_team_name(str(match.get("away", {}).get("name", "")))
            if not home or not away or home == away:
                continue
            if (home, away) in seen:
                continue
            seen.add((home, away))
            matchday = match.get("matchday")
            try:
                matchday = int(matchday) if matchday is not None else 0
            except (TypeError, ValueError):
                matchday = 0
            pairs.append((matchday, home, away))

        covered = len(pairs)
        self.matchday_count = max([md for md, _, _ in pairs] or [0])
        if covered >= required:
            pairs.sort(key=lambda item: (item[0] or 0, item[1], item[2]))
            return pairs
        if self.matchday_count < 38:
            self.matchday_count = 38

        generated = self._fixtures()
        gap = required - covered
        if gap <= 0:
            return pairs
        addition: list[tuple[int, str, str]] = []
        matchday = self.matchday_count + 1
        for md, home, away in generated:
            if (home, away) not in seen and len(addition) < gap:
                addition.append((matchday, home, away))
            seen.add((home, away))
        return pairs + addition

    def _fixtures(self) -> list[tuple[int, str, str]]:
        """Circle-method double round robin used to fill in missing fixtures."""
        n = len(self.teams)
        if n < 3:
            raise ValueError("League needs at least 3 teams to build fixtures")
        odd = n % 2 == 1
        working = list(self.teams)
        if odd:
            working = working + ["BYE"]
        schedule = self._circle_schedule(working)
        fixtures: list[tuple[int, str, str]] = []
        for day, pairs in enumerate(schedule, start=1):
            for home, away in pairs:
                if home == "BYE" or away == "BYE":
                    continue
                fixtures.append((day * 2 - 1, home, away))
        for day, pairs in enumerate(schedule, start=1):
            for home, away in pairs:
                if home == "BYE" or away == "BYE":
                    continue
                fixtures.append((day * 2, away, home))
        self.matchday_count = 2 * (n - 1)
        fixtures.sort(key=lambda item: item[0])
        return fixtures

    @staticmethod
    def _circle_schedule(teams: list[str]) -> list[list[tuple[str, str]]]:
        n = len(teams)
        rotated = list(teams)
        schedule: list[list[tuple[str, str]]] = []
        for turn in range(n - 1):
            pairs: list[tuple[str, str]] = []
            for i in range(n // 2):
                home = rotated[i]
                away = rotated[n - 1 - i]
                if i == 0 and turn % 2 == 1:
                    home, away = away, home
                pairs.append((home, away))
            schedule.append(pairs)
            rotated = [rotated[0], rotated[-1]] + rotated[1:-1]
        return schedule

    # ── Simulation + real results ─────────────────────────────────

    def _simulate(self, home: str, away: str) -> tuple[int, int]:
        metrics = getattr(self.match_engine, "team_metrics", None)
        if not metrics or home not in metrics:
            return self.match_engine.simulate_match(home, away, can_draw=True)
        entry = metrics[home]
        original = entry.get("ELO")
        if original is None:
            return self.match_engine.simulate_match(home, away, can_draw=True)
        entry["ELO"] = original + self.home_elo_bonus
        try:
            return self.match_engine.simulate_match(home, away, can_draw=True)
        finally:
            entry["ELO"] = original

    def _real_results(self) -> dict[tuple[str, str], tuple[int, int]]:
        data = self._load_matches()
        results: dict[tuple[str, str], tuple[int, int]] = {}
        for match in data.get("completed", []):
            home = self._map_team_name(match.get("home", {}).get("name", ""))
            away = self._map_team_name(match.get("away", {}).get("name", ""))
            if not home or not away:
                continue
            results[(home, away)] = (
                int(match.get("home", {}).get("score", 0)),
                int(match.get("away", {}).get("score", 0)),
            )
        return results

    def _load_matches(self) -> dict[str, object]:
        if not self.matches_file or not self.matches_file.exists():
            return {"completed": []}
        with self.matches_file.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _update_table(self, home_row: dict[str, int], away_row: dict[str, int], goals1: int, goals2: int) -> None:
        for row, scored, conceded in ((home_row, goals1, goals2), (away_row, goals2, goals1)):
            row["played"] += 1
            row["gf"] += scored
            row["ga"] += conceded
            row["gd"] = row["gf"] - row["ga"]
            if scored > conceded:
                row["won"] += 1
                row["pts"] += 3
            elif scored == conceded:
                row["drawn"] += 1
                row["pts"] += 1
            else:
                row["lost"] += 1

    @staticmethod
    def _attach_form(table: dict[str, dict[str, object]], matches: list[dict[str, object]]) -> None:
        results: dict[str, list[str]] = {}
        for match in matches:
            home = match["home"]
            away = match["away"]
            winner = match["winner"]
            home_result = "W" if winner == home else ("D" if winner == "DRAW" else "L")
            away_result = "W" if winner == away else ("D" if winner == "DRAW" else "L")
            results.setdefault(home, []).append(home_result)
            results.setdefault(away, []).append(away_result)
        for team, history in results.items():
            if team in table:
                last_five = history[-5:] if len(history) >= 5 else history
                table[team]["form"] = "".join(reversed(last_five))

    def _capture_debug(self, enabled: bool) -> None:
        if not enabled:
            return
        debug_text = getattr(self.match_engine, "last_match_debug", "")
        if debug_text:
            self.last_match_debugs.append(debug_text)

    def _map_team_name(self, name: str) -> str:
        return self.team_name_map.get(name, name)


class _LeagueSeasonStage(Stage):
    """Premier League season: the double round-robin across 38 matchdays.

    This is the league's "group stage" equivalent - every club plays the other
    19 home and away, accumulating one running table.
    """

    name = "Premier League Season"

    def run(self, ctx: StageContext) -> dict[str, object]:
        orch = ctx.orchestrator
        real_results = orch._real_results()
        fixtures = orch._fixture_list(real_results)
        table = {
            team: {"played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}
            for team in orch.teams
        }
        matches = []

        for matchday, home, away in fixtures:
            real = real_results.get((home, away))
            if real is not None:
                goals1, goals2 = real
                is_real = True
                home_minutes = [random.randint(1, 90) for _ in range(int(goals1))]
                away_minutes = [random.randint(1, 90) for _ in range(int(goals2))]
            else:
                goals1, goals2 = orch._simulate(home, away)
                is_real = False
                home_minutes, away_minutes = orch.generate_goal_minutes(goals1, goals2)
            orch.match_engine.notify_match(home, away, goals1, goals2, is_real)
            winner = home if goals1 > goals2 else (away if goals2 > goals1 else "DRAW")
            matches.append(
                {
                    "matchday": matchday,
                    "home": home,
                    "away": away,
                    "home_goals": goals1,
                    "away_goals": goals2,
                    "home_goal_minutes": home_minutes,
                    "away_goal_minutes": away_minutes,
                    "winner": winner,
                    "is_real": is_real,
                }
            )
            orch._update_table(table[home], table[away], goals1, goals2)
            orch._capture_debug(ctx.debug)

        return {"table": table, "matches": matches, "matchday_count": orch.matchday_count}


class _LeagueResolutionStage(Stage):
    """Read the season's table and settle the outcomes: title, Europe, relegation."""

    name = "Standings Resolution"

    def run(self, ctx: StageContext) -> dict[str, object]:
        orch = ctx.orchestrator
        season = ctx.outputs["Premier League Season"]
        table = dict(season["table"])
        matches = season["matches"]
        orch._attach_form(table, matches)
        ranked = sorted(
            table.items(),
            key=lambda item: (-item[1]["pts"], -item[1]["gd"], -item[1]["gf"], item[0]),
        )
        champion = ranked[0][0] if ranked else None
        return {
            "table": ranked,
            "champion": champion,
            "top4": [team for team, _ in ranked[:4]],
            "relegated": [team for team, _ in ranked[-3:]],
            "stats": {
                "matches": sum(1 for m in matches if m["winner"] != "DRAW"),
                "draws": sum(1 for m in matches if m["winner"] == "DRAW"),
                "real_results_used": sum(1 for m in matches if m["is_real"]),
            },
        }
