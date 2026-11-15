from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .base import CompetitionConfig

HERE = Path(__file__).resolve().parents[1]

# ── Canonical club set (2026-27 Premier League) ───────────────────
# Promoted 2026-27 (per live FPL API): Coventry City, Hull City, Ipswich Town;
# relegated 2025-26: Burnley, West Ham United, Wolverhampton Wanderers.
EPL_CLUBS = [
    "Arsenal",
    "Aston Villa",
    "Bournemouth",
    "Brentford",
    "Brighton & Hove Albion",
    "Chelsea",
    "Coventry City",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Hull City",
    "Ipswich Town",
    "Leeds United",
    "Liverpool",
    "Manchester City",
    "Manchester United",
    "Newcastle United",
    "Nottingham Forest",
    "Sunderland",
    "Tottenham Hotspur",
]

# Alias → canonical club name (fc26, FPL, football-data.org, odds providers).
TEAM_NAME_MAP: dict[str, str] = {
    "AFC Bournemouth": "Bournemouth",
    "Bournemouth": "Bournemouth",
    "Brighton": "Brighton & Hove Albion",
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Brighton & Hove Albion": "Brighton & Hove Albion",
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Liverpool": "Liverpool",
    "Chelsea": "Chelsea",
    "Man Utd": "Manchester United",
    "Man United": "Manchester United",
    "Manchester United": "Manchester United",
    "MUFC": "Manchester United",
    "Coventry City": "Coventry City",
    "Coventry": "Coventry City",
    "Hull City": "Hull City",
    "Hull": "Hull City",
    "Ipswich Town": "Ipswich Town",
    "Ipswich": "Ipswich Town",
    "Manchester City": "Manchester City",
    "Man City": "Manchester City",
    "Newcastle Utd": "Newcastle United",
    "Newcastle": "Newcastle United",
    "Newcastle United": "Newcastle United",
    "Nott'm Forest": "Nottingham Forest",
    "Nottm Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    "Spurs": "Tottenham Hotspur",
    "Tottenham": "Tottenham Hotspur",
    "Tottenham Hotspur": "Tottenham Hotspur",
    "West Ham": "West Ham United",
    "West Ham United": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
    "Wolverhampton": "Wolverhampton Wanderers",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",
"Leeds": "Leeds United",
    "Leeds United": "Leeds United",
    "Burnley": "Burnley",
    "Fulham": "Fulham",
    "Everton": "Everton",
    "Crystal Palace": "Crystal Palace",
    "Brentford": "Brentford",
    "Sunderland": "Sunderland",
}

# FC26 rating file team name → canonical club.
FC26_TEAM_TO_CANONICAL: dict[str, str] = {
    "AFC Bournemouth": "Bournemouth",
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Brentford": "Brentford",
    "Brighton": "Brighton & Hove Albion",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Leeds United": "Leeds United",
    "Liverpool": "Liverpool",
    "Man City": "Manchester City",
    "Manchester City": "Manchester City",
    "Man Utd": "Manchester United",
    "Newcastle Utd": "Newcastle United",
    "Nott'm Forest": "Nottingham Forest",
    "Spurs": "Tottenham Hotspur",
    "Sunderland": "Sunderland",
    "West Ham": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
}

# ── Season stamp ───────────────────────────────────────────────
# Single canonical season for all Premier League data artifacts. Every PL
# writer embeds it so each file is self-describing (not just the registry).
EPL_SEASON_LABEL: str = "Premier League 2026/2027"
EPL_SEASON = "2026/2027"
EPL_COMPETITION_FORMAT = "league"

# Reserved metadata key for club-keyed payload files (epl_teams.json,
# pl_rosters.json). Prefixed with "_" so club-iteration consumers can skip it
# instead of mistaking the stamp for a 21st club.
_RESERVED_META_KEY = "_competition"


def _competition_stamp() -> dict[str, str]:
    return {
        "competition": EPL_SEASON_LABEL,
        "season": EPL_SEASON,
        "competition_format": EPL_COMPETITION_FORMAT,
    }


def _is_metadata_key(key: str) -> bool:
    return key.startswith("_")


THREE_LETTER_CODES: dict[str, str] = {
    "Arsenal": "ARS",
    "Aston Villa": "AVL",
    "Bournemouth": "BOU",
    "Brentford": "BRE",
    "Brighton & Hove Albion": "BHA",
    "Burnley": "BUR",
    "Chelsea": "CHE",
    "Coventry City": "COV",
    "Crystal Palace": "CRY",
    "Everton": "EVE",
    "Fulham": "FUL",
    "Hull City": "HUL",
    "Ipswich Town": "IPS",
    "Leeds United": "LEE",
    "Liverpool": "LIV",
    "Manchester City": "MCI",
    "Manchester United": "MUN",
    "Newcastle United": "NEW",
    "Nottingham Forest": "NFO",
    "Sunderland": "SUN",
    "Tottenham Hotspur": "TOT",
    "West Ham United": "WHU",
    "Wolverhampton Wanderers": "WOL",
}

# ClubElo-style season-start ratings (2026-27 snapshot). Live data (ClubElo)
# overrides these when available via data/club_elo.json.
EPL_ELO: dict[str, float] = {
    "Arsenal": 1954,
    "Aston Villa": 1892,
    "Bournemouth": 1857,
    "Brentford": 1846,
    "Brighton & Hove Albion": 1864,
    "Chelsea": 1938,
    "Coventry City": 1740,
    "Crystal Palace": 1844,
    "Everton": 1800,
    "Fulham": 1835,
    "Hull City": 1735,
    "Ipswich Town": 1745,
    "Leeds United": 1785,
    "Liverpool": 2015,
    "Manchester City": 1993,
    "Manchester United": 1899,
    "Newcastle United": 1907,
    "Nottingham Forest": 1878,
    "Sunderland": 1770,
    "Tottenham Hotspur": 1896,
}

HOME_ELO_BONUS = 45.0
LEAGUE_MATCHDAYS = 38
LEAGUE_TEAM_COUNT = 20

RAW_POSITION_FROM_FC26 = {
    "GK": "GK",
    "CB": "DF",
    "RB": "DF",
    "LB": "DF",
    "CDM": "MF",
    "CM": "MF",
    "CAM": "MF",
    "RM": "MF",
    "LM": "MF",
    "ST": "AT",
    "RW": "AT",
    "LW": "AT",
    "CF": "AT",
}


def canonical_team_name(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)


def fc26_team_to_canonical(name: str) -> str:
    return FC26_TEAM_TO_CANONICAL.get(name, name)


def _tier_from_rating(rating: float) -> str:
    if rating >= 85:
        return "SUPERSTAR"
    if rating >= 82:
        return "STAR"
    if rating >= 79:
        return "STARTER"
    if rating >= 74:
        return "WISSEL"
    return "RESERVE"


def build_pl_rosters_from_fc26(data_dir: str | Path | None = None) -> dict[str, dict[str, list[tuple[Any, ...]]]]:
    """Build RAW_ROSTERS-style squads straight from fc26_ratings.json.

    Used as the offline default when the live fetcher has not produced
    data/pl_rosters.json yet.
    """
    if data_dir:
        path = Path(data_dir) / "data" / "fc26_ratings.json"
    else:
        path = HERE / "data" / "fc26_ratings.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        ratings = json.load(f)

    rosters: dict[str, dict[str, list[tuple[Any, ...]]]] = {
        team: {"GK": [], "DF": [], "MF": [], "AT": []} for team in EPL_CLUBS
    }
    for _, entry in ratings.items():
        if entry.get("league") != "Premier League":
            continue
        team = fc26_team_to_canonical(str(entry.get("team", "")))
        if team not in rosters:
            continue
        raw_position = RAW_POSITION_FROM_FC26.get(str(entry.get("position", "")))
        if not raw_position:
            continue
        name = str(
            entry.get("name")
            or entry.get("player_name")
            or entry.get("commonName")
            or entry.get("fullName")
            or ""
        )
        if not name:
            continue
        overall = float(entry.get("overall", 72) or 72)
        rosters[team][raw_position].append((name, _tier_from_rating(overall), overall))

    def _sort(records):
        return sorted(records, key=lambda record: (-record[2], str(record[0])))

    return {team: {pos: _sort(items) for pos, items in position_groups.items()} for team, position_groups in rosters.items()}


def write_default_pl_files(data_dir: str | Path | None = None) -> None:
    """Materialise the offline defaults so simulations work without network."""
    if data_dir:
        data = Path(data_dir) / "data"
    else:
        data = HERE / "data"
    data.mkdir(parents=True, exist_ok=True)

    teams_file = data / "epl_teams.json"
    if not teams_file.exists():
        teams = {
            team: {
                "name": team,
                "code": THREE_LETTER_CODES[team],
                "elo": EPL_ELO.get(team, 1800),
                "fpl_id": None,
            }
            for team in EPL_CLUBS
        }
        teams_file.write_text(json.dumps(teams, indent=2), encoding="utf-8")

    rosters_file = data / "pl_rosters.json"
    if not rosters_file.exists():
        rosters = build_pl_rosters_from_fc26(data_dir)
        rosters_file.write_text(json.dumps(rosters, indent=2), encoding="utf-8")


def _team_names_and_metrics(data_dir: Path) -> tuple[list[str], list[str], dict[str, dict[str, float]]]:
    teams_file = data_dir / "data" / "epl_teams.json"
    if not teams_file.exists():
        return EPL_CLUBS, EPL_CLUBS, {}

    try:
        teams = json.loads(teams_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        teams = {}
    if not teams:
        return EPL_CLUBS, EPL_CLUBS, {}

    metric_teams: dict[str, dict[str, float]] = {}
    order: list[str] = []
    for raw_name, info in teams.items():
        if _is_metadata_key(raw_name):
            continue
        team = canonical_team_name(str(info.get("name") or raw_name))
        if team not in metric_teams:
            metric_teams[team] = {}
            order.append(team)
        elo = float(info.get("elo") or EPL_ELO.get(team, 1800))
        metric_teams[team]["ELO"] = elo
        metric_teams[team]["PELE"] = float(info.get("pele") or elo - 60)
    return order, order, metric_teams


def _competition_label(data_dir: Path) -> str:
    label = "Premier League 2026-27"
    matches_file = data_dir / "data" / "pl_matches.json"
    if matches_file.exists():
        try:
            header = json.loads(matches_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            header = {}
        season = header.get("competition")
        if season:
            label = season
        else:
            completed = header.get("completed")
            if completed:
                label = "Premier League"
    return label


def get_pl_config(data_dir: str | Path | None = None) -> CompetitionConfig:
    base = Path(data_dir) if data_dir else HERE
    order, teams, metrics = _team_names_and_metrics(base)
    if not metrics:
        metrics = {
            team: {"ELO": EPL_ELO.get(team, 1800), "PELE": EPL_ELO.get(team, 1800) - 60}
            for team in EPL_CLUBS
        }
        order = EPL_CLUBS
        teams = EPL_CLUBS

    return CompetitionConfig(
        name="premier-league",
        format="league",
        teams=order,
        team_metrics=metrics,
        codes={team: THREE_LETTER_CODES.get(team, team[:3].upper()) for team in teams},
        team_name_map=TEAM_NAME_MAP,
        matches_file=str(base / "data" / "pl_matches.json"),
        rosters_file=str(base / "data" / "pl_rosters.json"),
        players_file=str(base / "data" / "pl_players.json"),
        squads_file=str(base / "data" / "pl_squads.json"),
        form_cache_file=str(base / "data" / "pl_form_cache.json"),
        national_data=False,
        home_elo_bonus=HOME_ELO_BONUS,
        matchdays=LEAGUE_MATCHDAYS,
        competition_label=_competition_label(base),
        stage_names=["Premier League Season", "Standings Resolution"],
    )