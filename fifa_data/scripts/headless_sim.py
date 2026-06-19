import json, os, random, math
from numpy.random import poisson

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "..", "worldcupsimulator.py"), encoding="utf-8") as f:
    content = f.read()
data_block = content.split("RAW_ROSTERS")[0]
data_block = data_block.replace("from numpy.random import poisson\n", "")
exec(data_block, globals())

MATCHES_TEAM_MAP = {
    "USA": "United States",
    "Cabo Verde": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
}

def update_elo_from_matches(matches_file=os.path.join(HERE, "..", "data", "matches.json")):
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
    return g1, g2

update_elo_from_matches()

with open(os.path.join(HERE, "..", "data", "matches.json"), encoding="utf-8") as f:
    matches_data = json.load(f)

real_results = {}
for m in matches_data["completed"]:
    h = MATCHES_TEAM_MAP.get(m["home"]["name"], m["home"]["name"])
    a = MATCHES_TEAM_MAP.get(m["away"]["name"], m["away"]["name"])
    g = m["group"].replace("Group ", "")
    real_results[(g, h, a)] = (m["home"]["score"], m["away"]["score"])

def get_real(gid, t1, t2):
    key, key_rev = (gid, t1, t2), (gid, t2, t1)
    if key in real_results:
        return real_results[key]
    if key_rev in real_results:
        g1, g2 = real_results[key_rev]
        return (g2, g1)
    return None

# ─────────────────────── HEADER ───────────────────────
W = 78
print("\n" + "=" * W)
print("  WORLD CUP 2026 — SIMULATION")
print("  Elo ratings from betting odds + 16 real results baked in")
print("=" * W)

# ─────────────────────── GROUP STAGE ───────────────────────
group_winners = {}
group_runners = {}
third_placed = []

for gid in sorted(GROUPS.keys()):
    teams = GROUPS[gid]
    table = {t: {"pts": 0, "gd": 0, "gf": 0, "ga": 0} for t in teams}
    match_list = [(teams[0], teams[1]), (teams[2], teams[3]),
                  (teams[0], teams[2]), (teams[3], teams[1]),
                  (teams[1], teams[2]), (teams[3], teams[0])]
    match_lines = []
    for t1, t2 in match_list:
        r = get_real(gid, t1, t2)
        if r:
            g1, g2 = r
            tag = "R"
        else:
            g1, g2 = sim_match(t1, t2, can_draw=True)
            tag = " "
        match_lines.append((t1, g1, g2, t2, tag))
        table[t1]["pts"] += 3 if g1 > g2 else (1 if g1 == g2 else 0)
        table[t2]["pts"] += 3 if g2 > g1 else (1 if g1 == g2 else 0)
        table[t1]["gd"] += g1 - g2
        table[t2]["gd"] += g2 - g1
        table[t1]["gf"] += g1; table[t1]["ga"] += g2
        table[t2]["gf"] += g2; table[t2]["ga"] += g1

    sorted_teams = sorted(table.items(), key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"]), reverse=True)

    print(f"\n  ┌─ Group {gid} ")
    print(f"  │")
    for t1, g1, g2, t2, tag in match_lines:
        label = " [REAL]" if tag == "R" else ""
        print(f"  │   {t1:<25s} {g1}-{g2}  {t2}{label}")
    print(f"  │")
    print(f"  │   {'':>25s}  PTS   GD   GF")
    colors = ["32", "34", "33", "31"]  # green, blue, yellow, red
    for rank, (t, d) in enumerate(sorted_teams, 1):
        print(f"  │  {rank}. {t:<23s} {d['pts']:>2d}  {d['gd']:+>3d}  {d['gf']}")
    print(f"  └───" + "─" * 40)

    group_winners[gid] = sorted_teams[0][0]
    group_runners[gid] = sorted_teams[1][0]
    third_placed.append((gid, sorted_teams[2][0], sorted_teams[2][1]["pts"], sorted_teams[2][1]["gd"], sorted_teams[2][1]["gf"]))

# ─────────────────────── BEST THIRD-PLACED ───────────────────────
third_placed.sort(key=lambda x: (x[2], x[3], x[4]), reverse=True)
best_thirds = third_placed[:8]

print(f"\n  ┌─ Best 3rd-Placed Teams (top 8 advance)")
print(f"  │")
for rank, (gid, t, pts, gd, gf) in enumerate(third_placed, 1):
    mark = " QUALIFY" if rank <= 8 else " ELIM."
    print(f"  │  {rank:>2d}. Group {gid}  {t:<25s} {pts:>2d} pts  {gd:+>3d} GD  {gf} GF{mark}")
print(f"  └───" + "─" * 40)

# ─────────────────────── KNOCKOUT BRACKET ───────────────────────
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

# Build the bracket tree data
round_names = ["Round of 32", "Round of 16", "Quarter-Finals", "Semi-Finals", "Final"]
round_match_data = []  # list of lists, each entry: (t1, t2, g1, g2, winner)

current_pairs = [(resolve_team(p1), resolve_team(p2)) for p1, p2 in BRACKET]
for rnd_name in round_names:
    matches = []
    next_pairs = []
    for t1, t2 in current_pairs:
        if t1 == "TBD" or t2 == "TBD":
            matches.append((t1, t2, None, None, None))
            next_pairs.append(None)
            continue
        g1, g2 = sim_match(t1, t2, can_draw=(rnd_name == "Round of 32"))
        winner = t1 if g1 > g2 else (t2 if g2 > g1 else random.choice([t1, t2]))
        matches.append((t1, t2, g1, g2, winner))
        next_pairs.append(winner)
    round_match_data.append(matches)
    current_pairs = [(next_pairs[i], next_pairs[i+1]) for i in range(0, len(next_pairs)-1, 2) if next_pairs[i] and next_pairs[i+1]]

# Extract results for bracket display
r32 = round_match_data[0]
r16 = round_match_data[1]
qf  = round_match_data[2]
sf  = round_match_data[3]
fin = round_match_data[4]

# Collect semi losers and finalists
semi_losers = []
sf_winners = []
for t1, t2, g1, g2, w in sf:
    if w:
        sf_winners.append(w)
        semi_losers.append(t2 if w == t1 else t1)

# Third place
if len(semi_losers) == 2:
    tp1, tp2 = semi_losers
    tp_g1, tp_g2 = sim_match(tp1, tp2, can_draw=False)
    tp_winner = tp1 if tp_g1 > tp_g2 else tp2
else:
    tp1 = tp2 = tp_g1 = tp_g2 = tp_winner = None

# Final
if sf_winners:
    ft1, ft2 = sf_winners
    if len(fin) >= 1 and fin[0][4]:
        f_g1, f_g2 = fin[0][2], fin[0][3]
        champ = fin[0][4]
    else:
        f_g1, f_g2 = sim_match(ft1, ft2, can_draw=False)
        champ = ft1 if f_g1 > f_g2 else ft2
else:
    ft1 = ft2 = f_g1 = f_g2 = champ = None

# ─────────────────────── BRACKET VISUALIZATION ───────────────────────
print(f"\n{'=' * W}")
print("  KNOCKOUT BRACKET")
print(f"{'=' * W}")

def bracket_line(label, t1, t2=None):
    if t2 is None:
        return f"  {label:<15s} {t1}"
    return f"  {label:<15s} {t1:<20s} vs  {t2}"

all_rounds = [r32, r16, qf, sf, fin]
round_labels = ["R32", "R16", "QF", "SF", "F"]
header_labels = ["Round of 32", "Round of 16", "Quarter-Finals", "Semi-Finals", "Final"]

# Title per round
for ri, (label, matches) in enumerate(zip(header_labels, all_rounds)):
    print(f"\n  ┌─ {label} ({len(matches)} matches)")
    print(f"  │")
    for i, (t1, t2, g1, g2, w) in enumerate(matches, 1):
        if t1 == "TBD" or t2 == "TBD":
            print(f"  │  {i:>2d}. TBD")
            continue
        score = f"{g1}-{g2}" if g1 is not None else "?-?"
        print(f"  │  {i:>2d}. {t1:<24s} {score}  {t2:<24s}  -->  {w if w else 'TBD'}")
    print(f"  └───" + "─" * 50)

# Third place
if tp_winner:
    print(f"\n  ┌─ Third Place Play-Off")
    print(f"  │")
    print(f"  │     {tp1:<24s} {tp_g1}-{tp_g2}  {tp2:<24s}  -->  {tp_winner}")
    print(f"  └───" + "─" * 50)

# Champion
if champ:
    print(f"\n  ╔{'═' * (W-4)}╗")
    mid = (W - 4 - len(champ) - 24) // 2
    print(f"  ║{' ' * mid} WORLD CUP 2026 CHAMPION: {champ.upper()}!{' ' * mid}║")
    print(f"  ╚{'═' * (W-4)}╝")
else:
    print(f"\n  Champion: TBD")

# Stats
real_count = len(real_results)
total_group = sum(6 for g in GROUPS)
sim_count = total_group - real_count
print(f"\n  Matches: {real_count} real results + {sim_count} simulated group + {len(r32)+len(r16)+len(qf)+len(sf)+len(fin)+1} knockout = {real_count+sim_count+len(r32)+len(r16)+len(qf)+len(sf)+len(fin)+1} total")
