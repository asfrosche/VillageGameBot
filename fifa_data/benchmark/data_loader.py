"""V5 Benchmark - Real Match Data Loader.

Loads actual World Cup 2026 match results from matches.json
and real match statistics from match_stats.json (Sofascore).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIFA_DATA = HERE.parent
MATCHES_FILE = FIFA_DATA / "data" / "matches.json"
MATCH_STATS_FILE = FIFA_DATA / "data" / "match_stats.json"

TEAM_NAME_MAP = {
    "USA": "United States",
    "Cabo Verde": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "South Korea": "Korea Republic",
    "Czech Republic": "Czechia",
    "Turkey": "\u00dc\u00fcrkiye",
    "Iran": "IR Iran",
    "Ivory Coast": "C\u00f4te d'Ivoire",
}

_STATS_KEY_MAP = {
    "xg_home": "real_xg_home",
    "xg_away": "real_xg_away",
    "shots_home": "real_shots_home",
    "shots_away": "real_shots_away",
    "shots_on_target_home": "real_sot_home",
    "shots_on_target_away": "real_sot_away",
    "possession_home": "real_possession_home",
    "possession_away": "real_possession_away",
    "corners_home": "real_corners_home",
    "corners_away": "real_corners_away",
    "yellow_cards_home": "real_yellows_home",
    "yellow_cards_away": "real_yellows_away",
    "red_cards_home": "real_reds_home",
    "red_cards_away": "real_reds_away",
    "fouls_home": "real_fouls_home",
    "fouls_away": "real_fouls_away",
    "ppda_home": "real_ppda_home",
    "ppda_away": "real_ppda_away",
}


def _map_name(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)


def _load_match_stats() -> dict[tuple[str, str], dict]:
    """Load real match stats from match_stats.json, keyed by (home, away).

    Builds a reverse mapping so that lookup works regardless of which
    name variant is used in matches.json vs match_stats.json.
    """
    if not MATCH_STATS_FILE.exists():
        return {}
    with open(MATCH_STATS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    reverse_map = {}
    for canonical, variant in TEAM_NAME_MAP.items():
        reverse_map[variant] = canonical
        reverse_map[variant.lower()] = canonical

    lookup = {}
    for s in data:
        home = s.get("home", "")
        away = s.get("away", "")
        mapped = {}
        for src, dst in _STATS_KEY_MAP.items():
            if src in s and s[src] is not None:
                mapped[dst] = s[src]
        lookup[(home, away)] = mapped
        lookup[(home.lower(), away.lower())] = mapped
        ch = reverse_map.get(home, home)
        ca = reverse_map.get(away, away)
        if ch != home or ca != away:
            lookup[(ch, ca)] = mapped
            lookup[(ch.lower(), ca.lower())] = mapped
    return lookup


def load_real_matches() -> list[dict]:
    """Load all completed real matches from matches.json.

    Returns list of dicts with:
        id, date, stage, group, home, away, home_goals, away_goals,
        home_name, away_name, winner_id
        plus real_* stats from match_stats.json when available.
    """
    with open(MATCHES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    matches = []
    for m in data.get("completed", []):
        home_name = _map_name(m.get("home", {}).get("name", ""))
        away_name = _map_name(m.get("away", {}).get("name", ""))
        matches.append({
            "id": m.get("id", ""),
            "date": m.get("date", ""),
            "stage": m.get("stage", ""),
            "group": m.get("group", ""),
            "home_name": home_name,
            "away_name": away_name,
            "home_goals": int(m.get("home", {}).get("score", 0)),
            "away_goals": int(m.get("away", {}).get("score", 0)),
            "winner_id": m.get("winner"),
        })

    stats_lookup = _load_match_stats()
    for m in matches:
        key = (m["home_name"], m["away_name"])
        if key in stats_lookup:
            m.update(stats_lookup[key])
        else:
            key_lower = (m["home_name"].lower(), m["away_name"].lower())
            if key_lower in stats_lookup:
                m.update(stats_lookup[key_lower])
            else:
                key_rev = (m["away_name"], m["home_name"])
                if key_rev in stats_lookup:
                    m.update(stats_lookup[key_rev])
                else:
                    key_rev_lower = (m["away_name"].lower(), m["home_name"].lower())
                    if key_rev_lower in stats_lookup:
                        m.update(stats_lookup[key_rev_lower])

    return matches


def load_groups() -> dict[str, list[str]]:
    """Load group definitions from worldcupsimulator.py."""
    from fifa_data.services.simulation_service import GROUPS
    return dict(GROUPS)


def load_team_metrics() -> dict[str, dict[str, float]]:
    """Load team metrics from worldcupsimulator.py."""
    from fifa_data.services.simulation_service import TEAM_METRICS
    return dict(TEAM_METRICS)


def get_stage_category(stage: str, group: str) -> str:
    """Categorize a match into a stage category for analysis."""
    stage_lower = stage.lower()
    if "first stage" in stage_lower or "group" in stage_lower:
        return "Group Stage"
    if "round of 32" in stage_lower or "r32" in stage_lower:
        return "Round of 32"
    if "round of 16" in stage_lower or "r16" in stage_lower:
        return "Round of 16"
    if "quarter" in stage_lower or "qf" in stage_lower:
        return "Quarterfinals"
    if "semi" in stage_lower or "sf" in stage_lower:
        return "Semifinals"
    if "third" in stage_lower:
        return "Third Place"
    if "final" in stage_lower:
        return "Final"
    return "Other"
