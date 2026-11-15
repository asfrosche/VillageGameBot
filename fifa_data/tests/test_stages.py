"""Stage-pipeline tests.

Every competition is driven by one shared logical loop (``StagePipeline``), but
each supplies its OWN stage list. The World Cup keeps its tournament ladder
(group stage, knockout rounds, play-off); the Premier League runs a separate
loop (season, then standings resolution). Nothing about the World Cup stages
may leak into a league run.
"""

import random

import pytest

from fifa_data.competitions import get_competition, list_competitions
from fifa_data.services.simulation_service import run_simulation, simulate_stage

HERE = __import__("fifa_data.competitions", fromlist=["x"]).__path__[0]


@pytest.fixture(autouse=True)
def _seeded():
    random.seed(2026)
    yield


def _competition_root() -> str:
    import pathlib

    return str(pathlib.Path(__file__).resolve().parents[1])


def test_worldcup_advertises_its_tournament_stages():
    config = get_competition("worldcup", _competition_root())
    assert config.stage_names == [
        "Group Stage",
        "Round of 32",
        "Round of 16",
        "Quarter-Finals",
        "Semi-Finals",
        "Final",
        "Third-Place Play-off",
    ]
    result = run_simulation("v1", competition="worldcup")
    assert result["stages"] == config.stage_names


def test_premier_league_has_separate_stage_loop():
    config = get_competition("pl", _competition_root())
    assert config.stage_names == ["Premier League Season", "Standings Resolution"]
    assert not any("Group" in s or "Round" in s or "Final" in s for s in config.stage_names)
    result = run_simulation("v1", competition="pl")
    assert result["stages"] == config.stage_names


def test_stage_loop_isolation_no_worldcup_stages_in_league():
    """The league loop must never execute a World Cup stage."""
    config = get_competition("pl", _competition_root())
    league_stages = set(config.stage_names)
    wc_stages = set(get_competition("worldcup", _competition_root()).stage_names)
    assert league_stages.isdisjoint(wc_stages)
    result = run_simulation("v3", competition="pl")
    assert result["stages"] == ["Premier League Season", "Standings Resolution"]


def test_partial_worldcup_group_stage_checkpoint():
    result = simulate_stage("v1", stage="Group Stage", competition="worldcup")
    assert result["is_partial"] is True
    assert result["completed_stages"] == ["Group Stage"]
    assert result["format"] == "groups_knockout"
    assert "groups" in result
    assert "knockout" not in result
    assert all(len(g["matches"]) == 6 for g in result["groups"].values())


def test_partial_knockout_rounds_grow():
    r32 = simulate_stage("v1", stage="Round of 32", competition="worldcup")
    r16 = simulate_stage("v1", stage="Round of 16", competition="worldcup")
    assert len(r32["knockout"]) == 1
    assert len(r16["knockout"]) == 2
    assert r16["is_partial"] is True
    assert r16["champion"] is None


def test_full_stage_run_equals_run_simulation():
    full = simulate_stage("v1", stage="Final", competition="worldcup")
    assert "champion" in full
    assert full["completed_stages"][-1] == "Final"
    # run through the final stage => same shape as a normal run
    result = run_simulation("v1", competition="worldcup")
    assert set(full) >= {"groups", "knockout", "champion", "stats", "stages"}
    assert full["knockout"] == result["knockout"] or full["champion"] == result["champion"] is None or full["champion"]


def test_partial_league_season_checkpoint():
    random.seed(99)
    result = simulate_stage("v1", stage="Premier League Season", competition="pl")
    assert result["is_partial"] is True
    assert result["completed_stages"] == ["Premier League Season"]
    assert len(result["matches"]) == 20 * 19
    assert "champion" not in result
    assert "table" not in result


def test_league_season_then_resolution_completes():
    simulate_stage("v1", stage="Premier League Season", competition="pl")  # warm form cache
    import numpy as np

    random.seed(5)
    np.random.seed(5)
    season = simulate_stage("v1", stage="Premier League Season", competition="pl")
    random.seed(5)
    np.random.seed(5)
    full = run_simulation("v1", competition="pl")
    assert full["stages"] == ["Premier League Season", "Standings Resolution"]
    # Same seed => the resolution just wraps the season's matches.
    assert [(m["home"], m["away"], m["home_goals"], m["away_goals"]) for m in season["matches"]] == [
        (m["home"], m["away"], m["home_goals"], m["away_goals"]) for m in full["matches"]
    ]
    assert full["table"][0][0] == full["champion"]


def test_unknown_stage_rejected():
    with pytest.raises(ValueError):
        simulate_stage("v1", stage="Round of 128", competition="worldcup")
    with pytest.raises(ValueError):
        simulate_stage("v1", stage="Group Stage", competition="pl")


def test_league_loop_completed_runs_have_no_partial_flags():
    result = run_simulation("v5", competition="pl")
    assert "is_partial" not in result
    assert "completed_stages" not in result