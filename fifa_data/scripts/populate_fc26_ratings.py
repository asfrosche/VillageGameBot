"""
Populate FC 26 Ratings for World Cup Players
===============================================
Reads all World Cup player names from RAW_ROSTERS, looks up their EA FC 26 ratings,
and caches the results. Uses concurrent fetches for efficiency.

Outputs:
  - fc26_ratings.json          → Map of player names → full FC 26 ratings
  - fc26_ratings_cache.json    → Raw ratings cache (keyed by player ID)
  - fc26_player_index.json     → EA FC 26 player index (name → basic info)
  - fc26_missing_players.json  → Players not found in the EA FC 26 database

Usage:
    python populate_fc26_ratings.py [--rebuild-index] [--max-pages N]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from tqdm import tqdm

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from services.fc26_fetcher import Fc26Fetcher, normalize_player_name


def load_raw_rosters(path: Path) -> dict[str, list[tuple[str, str, float]]]:
    """Extract all player records from RAW_ROSTERS in worldcupsimulator.py."""
    content = path.read_text(encoding="utf-8")
    start = content.index("RAW_ROSTERS = {")
    end = content.index("\n\n# STANDARD SQUAD PARSER ENGINE", start)
    raw_text = content[start + len("RAW_ROSTERS ="): end].strip()
    rosters = ast.literal_eval(raw_text)

    players: list[tuple[str, str, float]] = []
    for team_name, positions in rosters.items():
        for position, records in positions.items():
            for record in records:
                name, tier, rating = _parse_raw_record(record)
                players.append((str(name), str(team_name), float(rating)))
    return players


def _parse_raw_record(record: Any) -> tuple[str, str, float]:
    if isinstance(record, tuple):
        return str(record[0]), str(record[1]) if len(record) >= 2 else "BASIS", float(record[2]) if len(record) >= 3 else 75.0
    return str(record), "BASIS", 75.0


def load_lineup_players(matches_path: Path) -> list[str]:
    """Extract all player names from match lineups."""
    if not matches_path.exists():
        return []
    with open(matches_path, "r", encoding="utf-8") as f:
        matches_data = json.load(f)

    names: list[str] = []
    for match_type in ("completed", "upcoming", "live"):
        for match in matches_data.get(match_type, []):
            for side in ("home", "away"):
                side_data = match.get(side, {})
                for key in ("lineup", "lineups", "starting_xi", "startingXI", "startingLineup"):
                    value = side_data.get(key)
                    if isinstance(value, list):
                        names.extend(str(item) for item in value if item)
                for key in ("players", "lineupPlayers"):
                    value = side_data.get(key)
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                n = item.get("name") or item.get("playerName") or item.get("displayName")
                                if n:
                                    names.append(str(n))
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate FC 26 ratings for World Cup players")
    parser.add_argument("--rebuild-index", action="store_true", help="Force rebuild of player index")
    parser.add_argument("--max-pages", type=int, default=200, help="Max pages to scrape for index (default: 200 = full)")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent workers for individual page fetches (default: 8)")
    args = parser.parse_args()

    ratings_output = HERE.parent / "data" / "fc26_ratings.json"
    missing_output = HERE.parent / "data" / "fc26_missing_players.json"

    fetcher = Fc26Fetcher(cache_dir=HERE.parent, request_delay=0.3)

    # ── Step 1: Gather all World Cup player names ─────────────────
    tqdm.write("Step 1: Gathering World Cup player names...")
    roster_players = load_raw_rosters(HERE.parent / "worldcupsimulator.py")
    lineup_names = load_lineup_players(HERE.parent / "data" / "matches.json")

    all_names: list[tuple[str, str | None]] = [
        (str(name), str(country)) for name, country, _ in roster_players
    ]

    seen = set(normalize_player_name(n) for n, _ in all_names)
    for name in lineup_names:
        key = normalize_player_name(name)
        if key not in seen:
            seen.add(key)
            all_names.append((name, None))

    tqdm.write(f"  RAW_ROSTERS players:   {len(roster_players)}")
    tqdm.write(f"  Lineup-only names:     {len(all_names) - len(roster_players)}")
    tqdm.write(f"  Total unique players:  {len(all_names)}")

    # ── Step 2: Build player index ────────────────────────────────
    if args.rebuild_index or not fetcher.player_index:
        tqdm.write(f"\nStep 2: Building EA FC 26 player index ({args.max_pages} pages max)...")
        added = fetcher.build_player_index(max_pages=args.max_pages)
        tqdm.write(f"  Index built: {len(fetcher.player_index)} players (+{added} new)")
    else:
        tqdm.write(f"\nStep 2: Using existing player index: {len(fetcher.player_index)} players")

    # ── Step 3: Find index matches for each player ────────────────
    tqdm.write("\nStep 3: Matching World Cup players to FC 26 index...")
    matched_players: list[tuple[str, Any, int]] = []  # (name, player_index_entry, score)
    unmatched_names: list[tuple[str, str | None]] = []

    for name, country in tqdm(all_names, desc="Matching"):
        results = fetcher.search_player(name, min_score=85)
        if not results:
            # Try lower threshold for harder matches
            results = fetcher.search_player(name, min_score=75)

        if not results:
            unmatched_names.append((name, country))
            continue

        # Only accept high-confidence matches for individual page fetching
        best_score = results[0][1]
        if best_score < 80:
            unmatched_names.append((name, country))
            continue

        if country and len(results) > 1:
            country_norm = normalize_player_name(country)
            best_entry = None
            best_score = 0
            for entry, score in results:
                entry_country = normalize_player_name(entry.get("nationality", ""))
                if entry_country == country_norm:
                    best_entry = entry
                    best_score = score
                    break
            if best_entry is not None:
                matched_players.append((name, best_entry, best_score))
            else:
                matched_players.append((name, results[0][0], results[0][1]))
        else:
            matched_players.append((name, results[0][0], results[0][1]))

    tqdm.write(f"  Matched:  {len(matched_players)}")
    tqdm.write(f"  Unmatched: {len(unmatched_names)}")

    # ── Step 4: Batch-fetch full ratings with concurrency ─────────
    ids_to_fetch: list[tuple[int, str]] = []
    for name, entry, _ in matched_players:
        pid = entry.get("id")
        if pid and pid not in fetcher.ratings_cache:
            ids_to_fetch.append((pid, entry.get("fullName", name)))

    tqdm.write(f"\nStep 4: Fetching full ratings for {len(ids_to_fetch)} players...")
    tqdm.write(f"  Using {args.workers} concurrent workers...")

    fetched_count = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fut_map = {
            pool.submit(fetcher.fetch_full_ratings, pid, name): (pid, name)
            for pid, name in ids_to_fetch
        }
        for future in tqdm(as_completed(fut_map), total=len(fut_map), desc="Fetching"):
            pid, pid_name = fut_map[future]
            try:
                result = future.result()
                if result:
                    fetched_count += 1
            except Exception as e:
                err = str(e).encode("ascii", "replace").decode("ascii")
                tqdm.write(f"  Error: {err}")

    tqdm.write(f"  Fetched {fetched_count} full ratings")

    # Save the cache after all concurrent fetches
    fetcher._save_ratings_cache()

    # ── Step 5: Generate missing report ───────────────────────────
    tqdm.write("\nStep 5: Generating missing player report...")
    found_names: set[str] = set()
    for name, entry, _ in matched_players:
        pid = entry.get("id")
        if pid and pid in fetcher.ratings_cache:
            found_names.add(normalize_player_name(name))

    report: dict[str, str] = {}
    for name, _ in unmatched_names:
        report[name] = "not_found"
    for name, country in all_names:
        key = normalize_player_name(name)
        if key not in found_names:
            if name not in report:
                matches = fetcher.search_player(name, min_score=70)
                if matches:
                    best = matches[0]
                    report[name] = f"partial:{best[0].get('fullName','?')}(score={best[1]})"
                else:
                    report[name] = "not_found"

    with open(missing_output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ── Step 6: Export ratings ────────────────────────────────────
    tqdm.write(f"\nStep 6: Exporting ratings to {ratings_output}...")
    export = fetcher.export_ratings(output_path=ratings_output, only_cached=True)
    tqdm.write(f"  Exported {len(export)} player ratings")

    # ── Summary ───────────────────────────────────────────────────
    tqdm.write("\n" + "=" * 60)
    tqdm.write("POPULATION SUMMARY")
    tqdm.write("=" * 60)
    tqdm.write(f"  World Cup players:         {len(all_names)}")
    tqdm.write(f"  Index matched:             {len(matched_players)}")
    tqdm.write(f"  Full ratings fetched:      {len(export)}")
    tqdm.write(f"  Not found in FC 26:        {len(report)}")
    tqdm.write(f"  Player index size:         {len(fetcher.player_index)}")
    tqdm.write(f"  Ratings cache size:        {len(fetcher.ratings_cache)}")
    tqdm.write(f"  Ratings file:              {ratings_output}")
    tqdm.write(f"  Missing report:            {missing_output}")
    tqdm.write("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
