import json, sys, os

KEYS = {
    "expectedGoals": "xg", "totalShotsOnGoal": "shots",
    "shotsOnGoal": "shots_on_target", "ballPossession": "possession",
    "cornerKicks": "corners", "yellowCards": "yellow_cards",
    "redCards": "red_cards", "fouls": "fouls", "passes": "passes",
    "interceptionWon": "interceptions", "totalTackle": "tackles",
}

mid = int(sys.argv[1])
data = json.loads(sys.stdin.read())
for period_block in data.get("statistics", []):
    if period_block.get("period") == "ALL":
        h, a = {}, {}
        for group in period_block.get("groups", []):
            for item in group.get("statisticsItems", []):
                k = item["key"]
                if k in KEYS:
                    h[KEYS[k]] = item.get("homeValue", 0)
                    a[KEYS[k]] = item.get("awayValue", 0)
        out = {"match_id": mid, "home": h, "away": a}
        os.makedirs("may/fifa_data/data/raw", exist_ok=True)
        with open(f"may/fifa_data/data/raw/match_{mid}.json", "w") as f:
            json.dump(out, f)
        print(f"Saved match {mid}")
        sys.exit(0)
print(f"No ALL period found for {mid}")
