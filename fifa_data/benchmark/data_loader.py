"""V5 Benchmark - Real Match Data Loader.

Loads actual World Cup 2026 match results from matches.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIFA_DATA = HERE.parent
MATCHES_FILE = FIFA_DATA / "data" / "matches.json"

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


def _map_name(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)


def load_real_matches() -> list[dict]:
    """Load all completed real matches from matches.json.

    Returns list of dicts with:
        id, date, stage, group, home, away, home_goals, away_goals,
        home_name, away_name, winner_id
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
