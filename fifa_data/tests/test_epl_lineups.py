"""ESPN-based real EPL lineup population tests.

The live fetcher hits ESPN without an API key; these tests cover the offline
parts (team/event matching, name canonicalisation, starter extraction,
formation inference) and the merge step, which are repopulated from committed
fixture/roster data rather than the network.
"""

import json
from pathlib import Path

import pytest

from fifa_data.scripts.fetch_epl_data import (
    _canonical_name,
    _formation_from_xi,
    _parse_pl_fixture,
    _same_teams,
    populate_epl_lineups,
)
from fifa_data.services.v2_data_loader import _extract_lineup

HERE = Path(__file__).resolve().parents[1]


def test_team_matching_handles_reversed_fixtures():
    assert _same_teams("Ipswich Town", "Sunderland", "Ipswich Town", "Sunderland")
    assert _same_teams("Sunderland", "Ipswich Town", "Ipswich Town", "Sunderland")
    assert not _same_teams("Arsenal", "Coventry City", "Ipswich Town", "Sunderland")
    assert _same_teams("Brighton & Hove Albion", "Arsenal", "Arsenal", "Brighton & Hove Albion")


def test_formation_inferred_from_starter_positions():
    xi = [
        {"name": "A", "position": "G"},
        {"name": "B", "position": "CD-R"},
        {"name": "C", "position": "CD-L"},
        {"name": "D", "position": "LB"},
        {"name": "E", "position": "RB"},
        {"name": "F", "position": "CM"},
        {"name": "G", "position": "DM"},
        {"name": "H", "position": "AM"},
        {"name": "I", "position": "RM"},
        {"name": "J", "position": "LM"},
        {"name": "K", "position": "ST"},
    ]
    assert _formation_from_xi(xi) == "4-5-1"
    assert _formation_from_xi(xi[:9]) == "4-3-3"


def test_canonical_name_resolves_roster_spelling():
    roster = ["David Raya", "Kai Havertz", "Mikel Merino", "Bukayo Saka"]
    assert _canonical_name("David Raya", roster) == "David Raya"
    assert _canonical_name("M. Merino", roster) == "Mikel Merino"
    # Unknown players fall through unchanged so the loader top-fills them.
    assert _canonical_name("Nobody Else", roster) == "Nobody Else"


def test_extract_lineup_reads_populated_players():
    match = {
        "players": [
            {"name": "David Raya"},
            {"name": "Kai Havertz"},
            {"name": "Bukayo Saka"},
        ]
    }
    names, formation = _extract_lineup({"players": match["players"], "formation": "4-3-3"})
    assert names == ["David Raya", "Kai Havertz", "Bukayo Saka"]
    assert formation == "4-3-3"


def test_parse_pl_fixture_extracts_both_lineups():
    payload = {
        "teams": [
            {"team": {"name": "Leeds United"}, "score": 0},
            {"team": {"name": "Crystal Palace"}, "score": 0},
        ],
        "teamLists": [
            {
                "team": None,
                "formation": {"label": "3-4-2-1"},
                "lineup": [
                    {"name": {"display": "Ao Tanaka"}},
                    {"name": {"display": "Dominic Calvert-Lewin"}},
                    {"name": {"display": "Ethan Ampadu"}},
                    {"name": {"display": "Illan Meslier"}},
                    {"name": {"display": "Georginio Rutter"}},
                    {"name": {"display": "Manor Solomon"}},
                    {"name": {"display": "Leif Davis"}},
                    {"name": {"display": "Daniel James"}},
                    {"name": {"display": "Pascal Struijk"}},
                    {"name": {"display": "Adam Armstrong"}},
                    {"name": {"display": "Archie Gray"}},
                ],
            },
            {
                "team": None,
                "formation": {"label": "4-2-3-1"},
                "lineup": [
                    {"name": {"display": "Adam Wharton"}},
                    {"name": {"display": "Tyrick Mitchell"}},
                    {"name": {"display": "Yéremy Pino"}},
                    {"name": {"display": "Dean Henderson"}},
                    {"name": {"display": "Marc Guéhi"}},
                    {"name": {"display": "Maxence Lacroix"}},
                    {"name": {"display": "Daniel Muñoz"}},
                    {"name": {"display": "Will Hughes"}},
                    {"name": {"display": "Cheick Doucouré"}},
                    {"name": {"display": "Jean-Philippe Mateta"}},
                    {"name": {"display": "Eberechi Eze"}},
                ],
            },
        ],
    }
    lineups = _parse_pl_fixture(payload)
    assert lineups["Leeds United"]["formation"] == "3-4-2-1"
    assert lineups["Leeds United"]["xi"][0]["name"] == "Ao Tanaka"
    assert lineups["Crystal Palace"]["formation"] == "4-2-3-1"
    assert lineups["Crystal Palace"]["xi"][2]["name"] == "Yéremy Pino"

    incomplete = dict(payload)
    incomplete["teamLists"][0]["lineup"] = [{"name": {"display": "Only One"}}]
    assert _parse_pl_fixture(incomplete) is None


def test_populate_skips_filled_and_writes_new(monkeypatch, tmp_path):
    import fifa_data.scripts.fetch_epl_data as fetcher

    matches = {
        "competition": "Premier League 2026/27",
        "last_updated": "",
        "completed": [
            {
                "id": "pl_1",
                "date": "2026-08-21T19:00:00Z",
                "stage": "Regular Season",
                "group": None,
                "matchday": 1,
                "home": {"name": "Arsenal", "score": 3, "id": 1, "players": []},
                "away": {"name": "Coventry City", "score": 1, "id": 7, "players": []},
                "winner": "Arsenal",
                "status": 0,
            },
            {
                "id": "pl_2",
                "date": "2026-08-22T14:00:00Z",
                "stage": "Regular Season",
                "group": None,
                "matchday": 1,
                "home": {"name": "Everton", "score": 0, "id": 9, "players": [{"name": "James Tarkowski"}]},
                "away": {"name": "Crystal Palace", "score": 0, "id": 8, "players": [{"name": "Dean Henderson"}]},
                "winner": None,
                "status": 0,
            },
        ],
    }
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "pl_matches.json").write_text(json.dumps(matches), encoding="utf-8")
    (data_dir / "pl_rosters.json").write_text(
        json.dumps({
            "Arsenal": {"GK": [["David Raya", "STAR", 87.0]], "DF": [["Ben White", "STAR", 84.0]]},
            "Coventry City": {"GK": [["Carl Rushworth", "STARTER", 76.0]], "DF": [["Bobby Thomas", "STARTER", 70.0]]},
        }),
        encoding="utf-8",
    )

    calls = []
    real_data_dir = fetcher.DATA
    fetcher.DATA = data_dir

    def fake_event_id(home, away, date_iso):
        calls.append((home, away, date_iso))
        return "401879301" if home == "Arsenal" else None

    def fake_starters(event_id):
        return {
            "Arsenal": {
                "xi": [
                    {"name": "David Raya", "position": "G"},
                    {"name": "Ben White", "position": "CD-R"},
                ],
                "formation": "5-4-1",
            },
        }

    monkeypatch.setattr(fetcher, "_espn_event_id", fake_event_id)
    monkeypatch.setattr(fetcher, "_espn_starters", fake_starters)
    monkeypatch.setattr(fetcher, "_pl_match_ids", lambda force=False: {})
    try:
        result = populate_epl_lineups()
    finally:
        fetcher.DATA = real_data_dir

    assert result == {"filled": 1, "skipped": 1, "failed": 0, "unmatched": 0}
    written = json.loads((data_dir / "pl_matches.json").read_text(encoding="utf-8"))
    arsenal = written["completed"][0]["home"]
    assert [p["name"] for p in arsenal["players"]] == ["David Raya", "Ben White"]
    assert written["completed"][0]["home"]["formation"] == "5-4-1"
    # Already-populated fixture and unreachable fixture are untouched.
    everton = written["completed"][1]
    assert everton["home"]["players"] == [{"name": "James Tarkowski"}]
    assert everton["away"]["players"] == [{"name": "Dean Henderson"}]