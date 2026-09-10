"""Shared match configuration for the FIFA simulation engine.

Consolidates MATCHES_TEAM_MAP and update_elo_from_matches()
previously duplicated between worldcupsimulator.py and simulation_service.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]

MATCHES_TEAM_MAP: dict[str, str] = {
    "USA": "United States",
    "Cabo Verde": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "South Korea": "Korea Republic",
    "Czech Republic": "Czechia",
    "Turkey": "Türkiye",
    "Iran": "IR Iran",
}


def update_elo_from_matches(
    team_metrics: dict[str, dict[str, float]],
    matches_file: str | None = None,
) -> None:
    """Update ELO/PELE ratings based on completed match results."""
    if matches_file is None:
        matches_file = str(HERE / "data" / "matches.json")
    with open(matches_file, encoding="utf-8") as f:
        data = json.load(f)
    completed = data.get("completed", [])
    k_elo = 20
    k_pele = 20
    for match in completed:
        home_name = MATCHES_TEAM_MAP.get(match["home"]["name"], match["home"]["name"])
        away_name = MATCHES_TEAM_MAP.get(match["away"]["name"], match["away"]["name"])
        if home_name not in team_metrics or away_name not in team_metrics:
            continue
        home_goals = match["home"]["score"]
        away_goals = match["away"]["score"]
        r1 = (team_metrics[home_name]["ELO"] + team_metrics[home_name]["PELE"]) / 2
        r2 = (team_metrics[away_name]["ELO"] + team_metrics[away_name]["PELE"]) / 2
        we1 = 1 / (1 + 10 ** ((r2 - r1) / 400))
        if home_goals > away_goals:
            w1 = 1.0
        elif home_goals < away_goals:
            w1 = 0.0
        else:
            w1 = 0.5
        gd = abs(home_goals - away_goals)
        if gd <= 1:
            g_mult = 1.0
        elif gd == 2:
            g_mult = 1.5
        else:
            g_mult = 2.0
        delta = (w1 - we1) * g_mult
        team_metrics[home_name]["ELO"] = round(team_metrics[home_name]["ELO"] + k_elo * delta)
        team_metrics[away_name]["ELO"] = round(team_metrics[away_name]["ELO"] - k_elo * delta)
        team_metrics[home_name]["PELE"] = round(team_metrics[home_name]["PELE"] + k_pele * delta)
        team_metrics[away_name]["PELE"] = round(team_metrics[away_name]["PELE"] - k_pele * delta)
