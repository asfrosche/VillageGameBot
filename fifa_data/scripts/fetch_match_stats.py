"""Fetch real match statistics from Sofascore API for all completed WC2026 matches."""
import json
import sys
import time
from pathlib import Path

try:
    import urllib.request
except ImportError:
    print("urllib not available")
    sys.exit(1)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MATCHES_FILE = DATA_DIR / "matches.json"
OUTPUT_FILE = DATA_DIR / "match_stats.json"

TOURNAMENT_ID = 16
SEASON_ID = 58210
BASE_URL = "https://api.sofascore.com/api/v1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

TEAM_NAME_MAP = {
    "USA": "United States",
    "Cabo Verde": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "South Korea": "Korea Republic",
    "Czech Republic": "Czechia",
    "Turkey": "Türkiye",
    "Iran": "IR Iran",
    "Ivory Coast": "Côte d'Ivoire",
    "Cote d'Ivoire": "Côte d'Ivoire",
}

REVERSE_NAME_MAP = {v: k for k, v in TEAM_NAME_MAP.items()}


def _map_name(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)


def _reverse_map(name: str) -> str:
    return REVERSE_NAME_MAP.get(name, name)


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_completed_match_ids() -> list[dict]:
    all_matches = []
    page = 0
    while True:
        url = f"{BASE_URL}/unique-tournament/{TOURNAMENT_ID}/season/{SEASON_ID}/events/last/{page}"
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"  Error fetching page {page}: {e}")
            break
        events = data.get("events", [])
        if not events:
            break
        for ev in events:
            status_code = ev.get("status", {}).get("code", 0)
            if status_code in (100, 110, 120):
                home_name = ev.get("homeTeam", {}).get("name", "")
                away_name = ev.get("awayTeam", {}).get("name", "")
                home_score = ev.get("homeScore", {}).get("current", 0)
                away_score = ev.get("awayScore", {}).get("current", 0)
                all_matches.append({
                    "sofascore_id": ev["id"],
                    "home": _map_name(home_name),
                    "away": _map_name(away_name),
                    "home_goals": home_score,
                    "away_goals": away_score,
                    "status_code": status_code,
                })
        if not data.get("hasNextPage", False):
            break
        page += 1
        time.sleep(0.3)
    return all_matches


def fetch_match_stats(match_id: int) -> dict | None:
    url = f"{BASE_URL}/event/{match_id}/statistics"
    try:
        data = fetch_json(url)
    except Exception as e:
        print(f"  Error fetching stats for {match_id}: {e}")
        return None

    stats = {"xg_home": None, "xg_away": None,
             "shots_home": None, "shots_away": None,
             "sot_home": None, "sot_away": None,
             "possession_home": None, "possession_away": None,
             "corners_home": None, "corners_away": None,
             "yellows_home": None, "yellows_away": None,
             "reds_home": None, "reds_away": None,
             "fouls_home": None, "fouls_away": None,
             "passes_home": None, "passes_away": None,
             "interceptions_home": None, "interceptions_away": None,
             "tackles_home": None, "tackles_away": None}

    for period_data in data.get("statistics", []):
        if period_data.get("period") != "ALL":
            continue
        for group in period_data.get("groups", []):
            for item in group.get("statisticsItems", []):
                key = item.get("key", "")
                hv = item.get("homeValue")
                av = item.get("awayValue")
                if hv is None or av is None:
                    continue
                if key == "expectedGoals":
                    stats["xg_home"] = round(float(hv), 3)
                    stats["xg_away"] = round(float(av), 3)
                elif key == "totalShotsOnGoal":
                    stats["shots_home"] = int(hv)
                    stats["shots_away"] = int(av)
                elif key == "shotsOnGoal":
                    stats["sot_home"] = int(hv)
                    stats["sot_away"] = int(av)
                elif key == "ballPossession":
                    stats["possession_home"] = int(hv)
                    stats["possession_away"] = int(av)
                elif key == "cornerKicks":
                    stats["corners_home"] = int(hv)
                    stats["corners_away"] = int(av)
                elif key == "yellowCards":
                    stats["yellows_home"] = int(hv)
                    stats["yellows_away"] = int(av)
                elif key == "redCards":
                    stats["reds_home"] = int(hv)
                    stats["reds_away"] = int(av)
                elif key == "fouls":
                    stats["fouls_home"] = int(hv)
                    stats["fouls_away"] = int(av)
                elif key == "passes":
                    stats["passes_home"] = int(hv)
                    stats["passes_away"] = int(av)
                elif key == "interceptionWon":
                    stats["interceptions_home"] = int(hv)
                    stats["interceptions_away"] = int(av)
                elif key == "totalTackle":
                    stats["tackles_home"] = int(hv)
                    stats["tackles_away"] = int(av)
        break

    if (stats["passes_home"] is not None and stats["interceptions_home"] is not None
            and stats["tackles_home"] is not None and stats["passes_away"] is not None
            and stats["interceptions_away"] is not None and stats["tackles_away"] is not None):
        da_home = stats["interceptions_home"] + stats["tackles_home"]
        da_away = stats["interceptions_away"] + stats["tackles_away"]
        if da_home > 0:
            stats["ppda_home"] = round(stats["passes_away"] / da_home, 2)
        if da_away > 0:
            stats["ppda_away"] = round(stats["passes_home"] / da_away, 2)

    return stats


def main():
    print("Fetching completed match IDs from Sofascore...")
    matches = get_completed_match_ids()
    print(f"Found {len(matches)} completed matches")

    results = []
    for i, m in enumerate(matches):
        mid = m["sofascore_id"]
        print(f"  [{i+1}/{len(matches)}] {m['home']} vs {m['away']} (ID: {mid})")
        stats = fetch_match_stats(mid)
        time.sleep(0.4)
        if stats:
            results.append({
                "sofascore_id": mid,
                "home": m["home"],
                "away": m["away"],
                "home_goals": m["home_goals"],
                "away_goals": m["away_goals"],
                **stats,
            })
        else:
            results.append({
                "sofascore_id": mid,
                "home": m["home"],
                "away": m["away"],
                "home_goals": m["home_goals"],
                "away_goals": m["away_goals"],
            })

    OUTPUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {len(results)} match stats to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
