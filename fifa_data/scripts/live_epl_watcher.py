"""Live Premier League results/fixtures watcher.

Polls the FPL/football-data sources at an interval, diffs the result set and
merges only changed/new records into ``data/pl_matches.json``, preserving any
manually curated entries. On detecting newly completed matches it hot-updates
the persisted ELO table (``data/epl_teams.json``) using the same
``update_elo_from_matches`` utility the bot already uses.

CLI:
    python -m fifa_data.scripts.live_epl_watcher --once
    python -m fifa_data.scripts.live_epl_watcher --interval 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "data"
MATCHES_FILE = DATA / "pl_matches.json"
TEAMS_FILE = DATA / "epl_teams.json"


def _log(message: str) -> None:
    print(f"[live_epl_watcher] {message}")


def _merge_matches(existing: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
    """Merge fetched fixtures into the existing file, keeping curated entries."""
    merged_completed: dict[str, dict[str, Any]] = {}
    curated: list[dict[str, Any]] = []
    for match in existing.get("completed", []):
        match_id = str(match.get("id"))
        if match_id and match_id.startswith("pl_"):
            merged_completed[match_id] = match
        else:
            curated.append(match)
    for match in fetched.get("completed", []):
        match_id = str(match.get("id"))
        if match_id:
            merged_completed[match_id] = match
    completed = sorted(merged_completed.values(), key=lambda m: str(m.get("date", "")))

    fetched_ids = {str(m.get("id")) for m in fetched.get("upcoming", [])}
    upcoming = [m for m in fetched.get("upcoming", []) if not m.get("finished", False)]

    return {
        "competition": fetched.get("competition") or existing.get("competition", "Premier League"),
        "last_live_update": fetched.get("last_updated", ""),
        "completed_count": len(completed) + len(curated),
        "upcoming_count": len(upcoming),
        "completed": curated + completed,
        "upcoming": upcoming,
    }


def refresh_fixtures() -> dict[str, Any] | None:
    """Merge latest FPL fixtures into pl_matches.json. Returns the merged data."""
    from . import fetch_epl_data

    existing: dict[str, Any] = {"competition": "Premier League", "completed": [], "upcoming": []}
    if MATCHES_FILE.exists():
        try:
            existing = json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {"competition": "Premier League", "completed": [], "upcoming": []}

    try:
        bootstrap, fixtures = fetch_epl_data.fetch_fpl()
    except Exception as exc:
        _log(f"FPL fetch failed: {exc}")
        return None

    if not TEAMS_FILE.exists():
        fetch_epl_data.build_teams_file(bootstrap)
    fetched = fetch_epl_data.build_matches_file(fixtures, _season_from(existing))
    merged = _merge_matches(existing, fetched)
    merged["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    MATCHES_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"merged {len(merged['completed'])} completed, {len(merged['upcoming'])} upcoming")
    return merged


def _season_from(existing: dict[str, Any]) -> int:
    competition = str(existing.get("competition", ""))
    import re

    match = re.search(r"(\d{4})", competition)
    return int(match.group(1)) if match else 2026


def hot_update_elo() -> int:
    """Apply only newly-completed real results to epl_teams.json ELO ratings."""
    if not MATCHES_FILE.exists() or not TEAMS_FILE.exists():
        return 0
    from ..services._match_config import update_elo_from_matches

    progress_file = DATA / "pl_elo_progress.json"
    applied: set[str] = set()
    if progress_file.exists():
        try:
            applied = set(json.loads(progress_file.read_text(encoding="utf-8")).get("applied", []))
        except (json.JSONDecodeError, OSError):
            applied = set()

    matches_data = json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
    completed = matches_data.get("completed", [])
    fresh = [m for m in completed if str(m.get("id")) not in applied]
    if not fresh:
        _log("no new results to apply")
        return 0

    from ..competitions.premier_league import _is_metadata_key

    teams = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    metrics = {
        team: {
            "ELO": float(info.get("elo") or 1800),
            "PELE": float(info.get("pele") or (float(info.get("elo") or 1800) - 60)),
        }
        for team, info in teams.items()
        if not _is_metadata_key(team)
    }
    before = {t: metrics[t]["ELO"] for t in metrics}
    update_elo_from_matches(metrics, team_name_map={}, matches={"completed": fresh})
    changed = 0
    for team, row in metrics.items():
        if abs(row["ELO"] - before[team]) > 0:
            teams[team]["elo"] = row["ELO"]
            teams[team]["pele"] = row["PELE"]
            changed += 1
    if changed:
        TEAMS_FILE.write_text(json.dumps(teams, indent=2, ensure_ascii=False), encoding="utf-8")
    applied.update(str(m.get("id")) for m in fresh)
    progress_file.write_text(json.dumps({"applied": sorted(applied)}, indent=2), encoding="utf-8")
    _log(f"elo hot-updated for {changed} clubs across {len(fresh)} new matches")
    return changed


def run_forever(interval_minutes: int = 20, once: bool = False) -> None:
    while True:
        merged = refresh_fixtures()
        if merged:
            hot_update_elo()
        if once:
            break
        _log(f"sleeping {interval_minutes} min")
        time.sleep(interval_minutes * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Premier League fixtures watcher.")
    parser.add_argument("--once", action="store_true", help="Run a single refresh cycle and exit")
    parser.add_argument("--interval", type=int, default=20, help="Poll interval in minutes")
    parser.add_argument("--no-elo", action="store_true", help="Skip the Elo hot-update step")
    args = parser.parse_args()

    merged = refresh_fixtures()
    if merged and not args.no_elo:
        hot_update_elo()
    if args.once:
        return 0
    _log("running daemon loop (Ctrl+C to stop)")
    while True:
        time.sleep(args.interval * 60)
        merged = refresh_fixtures()
        if merged and not args.no_elo:
            hot_update_elo()
    return 0


if __name__ == "__main__":
    sys.exit(main())