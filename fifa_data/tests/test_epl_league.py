"""Premier League repurposing tests.

Checks the competition registry, the LeagueOrchestrator table invariants for
every engine model, and the live-result merge onto the real fixture list.
"""

from pathlib import Path
import random

import pytest

from fifa_data.competitions import get_competition, list_competitions
from fifa_data.services.simulation_service import run_simulation

HERE = Path(__file__).resolve().parents[1]
MATCHES_FILE = HERE / "data" / "pl_matches.json"

LEAGUE_TEAMS = 20
SEASON_MATCHES = LEAGUE_TEAMS * (LEAGUE_TEAMS - 1)
MATCHDAYS = 38


def _real_completed_count() -> int:
    if not MATCHES_FILE.exists():
        return 0
    import json

    with MATCHES_FILE.open(encoding="utf-8") as handle:
        return len(json.load(handle).get("completed", []))


@pytest.fixture(autouse=True)
def _seeded():
    random.seed(2026)
    yield


def test_registry_resolves_pl_aliases():
    for name in ("pl", "epl", "premier-league", "premier_league", "premier"):
        config = get_competition(name, HERE)
        assert config.format == "league"
        assert len(config.teams) == LEAGUE_TEAMS


def test_registry_worldcup_untouched():
    config = get_competition("world-cup", HERE)
    assert config.format == "groups_knockout"
    assert "worldcup" in {a.lower() for a in list_competitions()}


def test_league_has_expected_clubs():
    config = get_competition("pl", HERE)
    expected = {
        "Arsenal",
        "Aston Villa",
        "Manchester City",
        "Manchester United",
        "Liverpool",
        "Chelsea",
        "Tottenham Hotspur",
    }
    assert expected <= set(config.teams)
    assert len(config.teams) == LEAGUE_TEAMS
    assert all(len(code) == 3 for code in config.codes.values())


@pytest.mark.parametrize("model", ["v1", "v2", "v3", "v4", "v5", "v6"])
def test_every_model_simulates_full_league(model):
    result = run_simulation(model, competition="pl")
    assert result["format"] == "league"
    assert len(result["matches"]) == SEASON_MATCHES
    assert result["matchdays"] == MATCHDAYS
    for team, row in result["table"]:
        assert row["played"] == MATCHDAYS, team


def test_table_invariants_v1():
    result = run_simulation("v1", competition="pl")
    for team, row in result["table"]:
        assert row["played"] == MATCHDAYS, team
        assert row["won"] + row["drawn"] + row["lost"] == row["played"], team
        assert row["gd"] == row["gf"] - row["ga"], team
        assert row["pts"] == 3 * row["won"] + row["drawn"], team
    pts = [row["pts"] for _, row in result["table"]]
    assert pts == sorted(pts, reverse=True)
    assert result["table"][0][0] == result["champion"]
    assert len(result["top4"]) == 4
    assert len(result["relegated"]) == 3
    assert set(result["top4"]).isdisjoint(result["relegated"])


def test_no_worldcup_strings_in_league_output():
    result = run_simulation("v1", competition="pl")
    assert result["champion"] not in ("", None)
    joined = " ".join(f"{team} {row!r}" for team, row in result["table"])
    assert "Group" not in joined
    assert "World" not in joined
    matchdays = {m["matchday"] for m in result["matches"]}
    assert matchdays <= set(range(1, MATCHDAYS + 1))


def test_real_results_merge_onto_fixture_list():
    real = _real_completed_count()
    if not real:
        pytest.skip("no pl_matches.json completed results available")
    result = run_simulation("v1", competition="pl")
    merged = result["stats"]["real_results_used"]
    assert merged == real, f"expected {real} real results merged, got {merged}"
    real_by_pair = {}
    import json

    with MATCHES_FILE.open(encoding="utf-8") as handle:
        data = json.load(handle)
    for match in data["completed"]:
        home = match["home"]["name"]
        away = match["away"]["name"]
        real_by_pair[(home, away)] = (
            int(match["home"].get("score", 0)),
            int(match["away"].get("score", 0)),
        )
    simulated = {m["home"] + "|" + m["away"]: m for m in result["matches"] if not m["is_real"]}
    for (home, away), score in real_by_pair.items():
        assert not any(
            m["home"] == home and m["away"] == away and not m["is_real"] for m in result["matches"]
        ), f"real fixture simulated: {home} vs {away}"


def test_synthetic_odds_are_probabilities():
    from fifa_data.scripts.odds_watcher import synthetic_odds_for_fixtures

    rows = synthetic_odds_for_fixtures()
    assert rows
    for row in rows:
        assert row["home"] != row["away"]
        inv = 1.0 / row["home_win"] + 1.0 / row["draw"] + 1.0 / row["away_win"]
        assert 0.9 <= inv <= 1.35, row
        assert row["home_win"] > 1.0
        assert row["draw"] > 1.0
        assert row["away_win"] > 1.0