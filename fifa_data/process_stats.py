import json, os, glob

NAME_MAP = {
    "USA": "United States", "Cabo Verde": "Cape Verde",
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "South Korea": "Korea Republic", "Czech Republic": "Czechia",
    "Turkey": "Türkiye", "Iran": "IR Iran",
    "Ivory Coast": "Côte d'Ivoire", "Cote d'Ivoire": "Côte d'Ivoire",
}

def map_name(n):
    return NAME_MAP.get(n, n)

with open("may/fifa_data/data/matches_raw.json") as f:
    matches = json.load(f)

match_map = {m["id"]: m for m in matches}
results = []

for fp in sorted(glob.glob("may/fifa_data/data/raw/match_*.json")):
    mid = int(os.path.basename(fp).replace("match_", "").replace(".json", ""))
    if mid not in match_map:
        continue
    m = match_map[mid]
    with open(fp) as f:
        data = json.load(f)

    h = data.get("home", {})
    a = data.get("away", {})
    if not h or not a:
        print(f"WARNING: missing home/away for {mid}")
        continue

    home = map_name(m["home"])
    away = map_name(m["away"])
    gh, ga = m["hg"], m["ag"]

    int_h, tk_h = h.get("interceptions", 0), h.get("tackles", 0)
    int_a, tk_a = a.get("interceptions", 0), a.get("tackles", 0)
    ppda_h = round(a["passes"] / (int_h + tk_h), 2) if (int_h + tk_h) else None
    ppda_a = round(h["passes"] / (int_a + tk_a), 2) if (int_a + tk_a) else None

    results.append({
        "match_id": mid, "home": home, "away": away,
        "goals_home": gh, "goals_away": ga,
        "xg_home": h.get("xg"), "xg_away": a.get("xg"),
        "shots_home": h.get("shots"), "shots_away": a.get("shots"),
        "shots_on_target_home": h.get("shots_on_target"),
        "shots_on_target_away": a.get("shots_on_target"),
        "possession_home": h.get("possession"), "possession_away": a.get("possession"),
        "corners_home": h.get("corners"), "corners_away": a.get("corners"),
        "yellow_cards_home": h.get("yellow_cards", 0),
        "yellow_cards_away": a.get("yellow_cards", 0),
        "red_cards_home": h.get("red_cards", 0),
        "red_cards_away": a.get("red_cards", 0),
        "fouls_home": h.get("fouls"), "fouls_away": a.get("fouls"),
        "passes_home": h.get("passes"), "passes_away": a.get("passes"),
        "tackles_home": h.get("tackles"), "tackles_away": a.get("tackles"),
        "interceptions_home": h.get("interceptions"),
        "interceptions_away": a.get("interceptions"),
        "ppda_home": ppda_h, "ppda_away": ppda_a,
    })

results.sort(key=lambda x: list(match_map.keys()).index(x["match_id"]) if x["match_id"] in match_map else 999)

out_path = "may/fifa_data/data/match_stats.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"Done! Wrote {len(results)} matches to {out_path}")
