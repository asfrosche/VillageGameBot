import json, urllib.request, time

# Team name mapping
NAME_MAP = {
    "USA": "United States", "Cabo Verde": "Cape Verde",
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "South Korea": "Korea Republic", "Czech Republic": "Czechia",
    "Turkey": "Türkiye", "Iran": "IR Iran",
    "Ivory Coast": "Côte d'Ivoire", "Cote d'Ivoire": "Côte d'Ivoire",
    "DR Congo": "DR Congo",
}

KEYS = ["expectedGoals", "totalShotsOnGoal", "shotsOnGoal", "ballPossession",
        "cornerKicks", "yellowCards", "redCards", "fouls", "passes",
        "interceptionWon", "totalTackle"]

def map_name(n):
    return NAME_MAP.get(n, n)

def extract_all_period(data):
    for period_block in data.get("statistics", []):
        if period_block.get("period") == "ALL":
            stats = {}
            for group in period_block.get("groups", []):
                for item in group.get("statisticsItems", []):
                    k = item["key"]
                    if k in KEYS:
                        stats[k] = item.get("homeValue", 0)
                        stats[f"{k}_away"] = item.get("awayValue", 0)
            return stats
    return {}

def fetch_stats(match_id):
    url = f"https://api.sofascore.com/api/v1/event/{match_id}/statistics"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  FAILED {match_id}: {e}")
        return None

# Load matches
with open("may/fifa_data/data/matches_raw.json") as f:
    matches = json.load(f)

results = []
for i, m in enumerate(matches):
    mid = m["id"]
    print(f"[{i+1}/30] {m['home']} vs {m['away']} ({mid})...")
    data = fetch_stats(mid)
    if not data:
        continue
    s = extract_all_period(data)
    if not s:
        print(f"  WARNING: no ALL period data")
        continue

    home = map_name(m["home"])
    away = map_name(m["away"])
    gh, ga = m["hg"], m["ag"]
    int_h, tk_h = s.get("interceptionWon", 0), s.get("totalTackle", 0)
    int_a, tk_a = s.get("interceptionWon_away", 0), s.get("totalTackle_away", 0)
    ppda_h = round(s["passes_away"] / (int_h + tk_h), 2) if (int_h + tk_h) else None
    ppda_a = round(s["passes"] / (int_a + tk_a), 2) if (int_a + tk_a) else None

    results.append({
        "match_id": mid, "home": home, "away": away,
        "goals_home": gh, "goals_away": ga,
        "xg_home": s.get("expectedGoals"), "xg_away": s.get("expectedGoals_away"),
        "shots_home": s.get("totalShotsOnGoal"), "shots_away": s.get("totalShotsOnGoal_away"),
        "shots_on_target_home": s.get("shotsOnGoal"), "shots_on_target_away": s.get("shotsOnGoal_away"),
        "possession_home": s.get("ballPossession"), "possession_away": s.get("ballPossession_away"),
        "corners_home": s.get("cornerKicks"), "corners_away": s.get("cornerKicks_away"),
        "yellow_cards_home": s.get("yellowCards"), "yellow_cards_away": s.get("yellowCards_away"),
        "red_cards_home": s.get("redCards", 0), "red_cards_away": s.get("redCards_away", 0),
        "fouls_home": s.get("fouls"), "fouls_away": s.get("fouls_away"),
        "passes_home": s.get("passes"), "passes_away": s.get("passes_away"),
        "tackles_home": s.get("totalTackle"), "tackles_away": s.get("totalTackle_away"),
        "interceptions_home": s.get("interceptionWon"), "interceptions_away": s.get("interceptionWon_away"),
        "ppda_home": ppda_h, "ppda_away": ppda_a,
    })
    time.sleep(0.3)

out_path = "may/fifa_data/data/match_stats.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nDone! Wrote {len(results)} matches to {out_path}")
