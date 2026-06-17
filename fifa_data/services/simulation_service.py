import json
import os
import random
from numpy.random import poisson

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MATCHES_TEAM_MAP = {
    "USA": "United States",
    "Cabo Verde": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
}

TEAM_METRICS = {}
GROUPS = {}

def _load_worldcup_data():
    path = os.path.join(HERE, "worldcupsimulator.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    data_block = content.split("RAW_ROSTERS")[0]
    data_block = data_block.replace("from numpy.random import poisson\n", "")
    g = {"TEAM_METRICS": TEAM_METRICS, "GROUPS": GROUPS}
    exec(data_block, g)
    TEAM_METRICS.update(g.get("TEAM_METRICS", {}))
    GROUPS.update(g.get("GROUPS", {}))
    return TEAM_METRICS, GROUPS

TEAM_METRICS, GROUPS = _load_worldcup_data()

def reset_metrics():
    _load_worldcup_data()

def update_elo_from_matches(matches_file=None):
    if matches_file is None:
        matches_file = os.path.join(HERE, "matches.json")
    with open(matches_file, encoding="utf-8") as f:
        data = json.load(f)
    completed = data.get("completed", [])
    k_elo = 20
    k_pele = 20
    for match in completed:
        home_name = MATCHES_TEAM_MAP.get(match["home"]["name"], match["home"]["name"])
        away_name = MATCHES_TEAM_MAP.get(match["away"]["name"], match["away"]["name"])
        if home_name not in TEAM_METRICS or away_name not in TEAM_METRICS:
            continue
        home_goals = match["home"]["score"]
        away_goals = match["away"]["score"]
        r1 = (TEAM_METRICS[home_name]["ELO"] + TEAM_METRICS[home_name]["PELE"]) / 2
        r2 = (TEAM_METRICS[away_name]["ELO"] + TEAM_METRICS[away_name]["PELE"]) / 2
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
        TEAM_METRICS[home_name]["ELO"] = round(TEAM_METRICS[home_name]["ELO"] + k_elo * delta)
        TEAM_METRICS[away_name]["ELO"] = round(TEAM_METRICS[away_name]["ELO"] - k_elo * delta)
        TEAM_METRICS[home_name]["PELE"] = round(TEAM_METRICS[home_name]["PELE"] + k_pele * delta)
        TEAM_METRICS[away_name]["PELE"] = round(TEAM_METRICS[away_name]["PELE"] - k_pele * delta)

def sim_match(t1, t2, can_draw=True):
    r1 = (TEAM_METRICS[t1]["ELO"] + TEAM_METRICS[t1]["PELE"]) / 2
    r2 = (TEAM_METRICS[t2]["ELO"] + TEAM_METRICS[t2]["PELE"]) / 2
    raw_delta = r1 - r2
    upset_factor = max(0.4, min(1.6, 1.0 + (raw_delta / 800.0)))
    lam1 = 1.1 * upset_factor
    lam2 = 1.1 * (2.0 - upset_factor)
    g1 = poisson(max(0.05, lam1))
    g2 = poisson(max(0.05, lam2))
    if not can_draw and g1 == g2:
        g1_et = poisson(lam1 * 0.3)
        g2_et = poisson(lam2 * 0.3)
        if g1_et != g2_et:
            g1 += g1_et
            g2 += g2_et
        else:
            if random.random() < (0.50 + (raw_delta * 0.0005)):
                g1 += 1
            else:
                g2 += 1
    return int(g1), int(g2)

def generate_goals(g1, g2):
    """Generate goal minutes for a given final score."""
    minutes = list(range(1, 91))
    random.shuffle(minutes)
    h_goals = sorted(minutes[:g1])
    a_goals = sorted(minutes[g1:g1+g2])
    return h_goals, a_goals

def run_simulation():
    """Run the full simulation and return structured data."""
    update_elo_from_matches()
    matches_file = os.path.join(HERE, "matches.json")
    with open(matches_file, encoding="utf-8") as f:
        matches_data = json.load(f)

    real_results = {}
    for m in matches_data["completed"]:
        h = MATCHES_TEAM_MAP.get(m["home"]["name"], m["home"]["name"])
        a = MATCHES_TEAM_MAP.get(m["away"]["name"], m["away"]["name"])
        g = m["group"].replace("Group ", "")
        real_results[(g, h, a)] = (m["home"]["score"], m["away"]["score"])

    def get_real(gid, t1, t2):
        key = (gid, t1, t2)
        key_rev = (gid, t2, t1)
        if key in real_results:
            return real_results[key]
        if key_rev in real_results:
            g1, g2 = real_results[key_rev]
            return (g2, g1)
        return None

    groups_data = {}
    group_winners = {}
    group_runners = {}
    all_third = []

    for gid in sorted(GROUPS.keys()):
        teams = GROUPS[gid]
        table = {t: {"pts": 0, "gd": 0, "gf": 0, "ga": 0} for t in teams}
        match_list = [
            (teams[0], teams[1]), (teams[2], teams[3]),
            (teams[0], teams[2]), (teams[3], teams[1]),
            (teams[1], teams[2]), (teams[3], teams[0]),
        ]
        matches = []
        for t1, t2 in match_list:
            r = get_real(gid, t1, t2)
            if r:
                g1, g2 = r
                is_real = True
            else:
                g1, g2 = sim_match(t1, t2, can_draw=True)
                is_real = False
            hg, ag = generate_goals(g1, g2)
            matches.append({
                "home": t1, "away": t2,
                "home_goals": g1, "away_goals": g2,
                "home_goal_minutes": hg,
                "away_goal_minutes": ag,
                "is_real": is_real,
            })
            table[t1]["pts"] += 3 if g1 > g2 else (1 if g1 == g2 else 0)
            table[t2]["pts"] += 3 if g2 > g1 else (1 if g1 == g2 else 0)
            table[t1]["gd"] += g1 - g2
            table[t2]["gd"] += g2 - g1
            table[t1]["gf"] += g1
            table[t2]["gf"] += g2

        sorted_teams = sorted(table.items(), key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"]), reverse=True)
        table_display = [(rank, t, d["pts"], d["gd"], d["gf"]) for rank, (t, d) in enumerate(sorted_teams, 1)]
        group_winners[gid] = sorted_teams[0][0]
        group_runners[gid] = sorted_teams[1][0]
        all_third.append((gid, sorted_teams[2][0], sorted_teams[2][1]["pts"], sorted_teams[2][1]["gd"], sorted_teams[2][1]["gf"]))

        groups_data[gid] = {
            "matches": matches,
            "table": table_display,
        }

    all_third.sort(key=lambda x: (x[2], x[3], x[4]), reverse=True)
    best_thirds = all_third[:8]

    # Bracket
    SLOTS = ["3ABCDF", "3CDFGH", "3BEFIJ", "3AEHIJ", "3CEFHI", "3EHIJK", "3EFGLI", "3DEIJL"]
    thirds_map = {}
    for i, slot in enumerate(SLOTS):
        thirds_map[slot] = best_thirds[i][1] if i < len(best_thirds) else "TBD"

    BRACKET = [
        ("1E", "3ABCDF"), ("1I", "3CDFGH"), ("2A", "2B"), ("1F", "2C"),
        ("2K", "2L"), ("1H", "2J"), ("1D", "3BEFIJ"), ("1G", "3AEHIJ"),
        ("1C", "2F"), ("2E", "2I"), ("1A", "3CEFHI"), ("1L", "3EHIJK"),
        ("1J", "2H"), ("2D", "2G"), ("1B", "3EFGLI"), ("1K", "3DEIJL"),
    ]

    def resolve_team(code):
        if code.startswith("1"):
            return group_winners.get(code[1:], "TBD")
        if code.startswith("2"):
            return group_runners.get(code[1:], "TBD")
        return thirds_map.get(code, "TBD")

    round_names = ["R32", "R16", "QF", "SF", "Final"]
    KO_MATCHES = []
    current_pairs = [(resolve_team(p1), resolve_team(p2)) for p1, p2 in BRACKET]
    for rnd_name in round_names:
        matches = []
        next_pairs = []
        for t1, t2 in current_pairs:
            if t1 == "TBD" or t2 == "TBD":
                matches.append(None)
                next_pairs.append(None)
                continue
            g1, g2 = sim_match(t1, t2, can_draw=(rnd_name == "R32"))
            winner = t1 if g1 > g2 else (t2 if g2 > g1 else random.choice([t1, t2]))
            hg, ag = generate_goals(g1, g2)
            matches.append({
                "home": t1, "away": t2,
                "home_goals": g1, "away_goals": g2,
                "home_goal_minutes": hg,
                "away_goal_minutes": ag,
                "winner": winner,
                "is_real": False,
            })
            next_pairs.append(winner)
        KO_MATCHES.append(matches)
        current_pairs = [(next_pairs[i], next_pairs[i+1]) for i in range(0, len(next_pairs)-1, 2) if next_pairs[i] and next_pairs[i+1]]

    # Third place
    sf = KO_MATCHES[3]
    semi_losers = []
    sf_winners = []
    for m in sf:
        if m:
            sf_winners.append(m["winner"])
            semi_losers.append(m["away"] if m["winner"] == m["home"] else m["home"])
    third_place = None
    if len(semi_losers) == 2:
        tp1, tp2 = semi_losers
        tp_g1, tp_g2 = sim_match(tp1, tp2, can_draw=False)
        tp_hg, tp_ag = generate_goals(tp_g1, tp_g2)
        tp_winner = tp1 if tp_g1 > tp_g2 else tp2
        third_place = {
            "home": tp1, "away": tp2,
            "home_goals": tp_g1, "away_goals": tp_g2,
            "home_goal_minutes": tp_hg,
            "away_goal_minutes": tp_ag,
            "winner": tp_winner,
            "is_real": False,
        }

    # Final
    final = KO_MATCHES[4]
    champion = None
    if sf_winners and len(final) >= 1 and final[0]:
        champion = final[0]["winner"]

    stats = {
        "real_count": len(real_results),
        "total_group_matches": sum(6 for _ in GROUPS),
        "knockout_matches": sum(len([m for m in rd if m]) for rd in KO_MATCHES),
        "third_place": 1 if third_place else 0,
    }

    return {
        "groups": groups_data,
        "third_placed": all_third,
        "best_thirds": best_thirds,
        "knockout": KO_MATCHES,
        "third_place": third_place,
        "champion": champion,
        "stats": stats,
    }
