"""Verify every Premier League data artifact is stamped for the current season.

Club-keyed payloads (epl_teams.json, pl_rosters.json) carry the stamp under the
reserved "_competition" key so a "_" prefix keeps club-iteration consumers from
mistaking the stamp for a 21st club. Named-payload files (pl_matches.json,
epl_odds.json, epl_title_odds.json) carry the stamp fields at the top level.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent))

from fifa_data.competitions import get_competition
from fifa_data.competitions.premier_league import (
    EPL_COMPETITION_FORMAT,
    EPL_SEASON,
    EPL_SEASON_LABEL,
)

D = HERE / "data"
print(f"declared season      : {EPL_SEASON_LABEL} ({EPL_SEASON}, format={EPL_COMPETITION_FORMAT})")

# reserved-key payloads vs named-key payloads
CLUB_KEYED = ("epl_teams.json", "pl_rosters.json")
NAMED_KEYED = ("pl_matches.json", "epl_odds.json", "epl_title_odds.json")

failures: list[str] = []


def stamp_of(data: dict) -> dict:
    reserved = data.get("_competition")
    if isinstance(reserved, dict):
        return reserved
    return data


for name in CLUB_KEYED + NAMED_KEYED:
    path = D / name
    if not path.exists():
        print(f"  {name:<22} MISSING")
        failures.append(f"{name}: missing")
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    stamp = stamp_of(data)
    season_ok = stamp.get("season") == EPL_SEASON
    comp_ok = stamp.get("competition") == EPL_SEASON_LABEL
    fmt_ok = stamp.get("competition_format") == EPL_COMPETITION_FORMAT
    ok = season_ok and comp_ok and fmt_ok
    if not ok:
        failures.append(f"{name}: season={stamp.get('season')!r} competition={stamp.get('competition')!r}")
    print(f"  {name:<22} season={str(stamp.get('season')):<10} competition_format={str(stamp.get('competition_format')):<8} {'OK' if ok else 'STALE'}")

# the reserved key must not be mistaken for a club
for name in CLUB_KEYED:
    path = D / name
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    clubs = [key for key in data if not key.startswith("_")]
    print(f"  {name:<22} clubs={len(clubs)} (no '_' key counted as club)")
    if len(clubs) != 20:
        failures.append(f"{name}: expected 20 clubs, found {len(clubs)}")

config = get_competition("pl", HERE)
label_ok = config.competition_label == EPL_SEASON_LABEL
print(f"registry label       : {config.competition_label} {'OK' if label_ok else 'MISMATCH'}")
if not label_ok:
    failures.append(f"registry label {config.competition_label!r} != {EPL_SEASON_LABEL!r}")

if failures:
    print("\nFAIL")
    for item in failures:
        print(f"  - {item}")
    raise SystemExit(1)
print("\nAll Premier League artifacts stamped for", EPL_SEASON)
