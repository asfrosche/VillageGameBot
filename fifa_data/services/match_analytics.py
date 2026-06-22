import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import aiohttp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COMPETITION_ID = "17"
SEASON_ID = "285023"
FIFA_API_URL = "https://api.fifa.com/api/v3/calendar/matches"
FANTASY_PLAYERS_URL = "https://play.fifa.com/json/fantasy/players.json"
FANTASY_SQUADS_URL = "https://play.fifa.com/json/fantasy/squads.json"


async def fetch_and_cache_data():
    """Fetch live match data from FIFA API and cache to disk."""
    async with aiohttp.ClientSession() as session:
        params = {"idCompetition": COMPETITION_ID, "idSeason": SEASON_ID, "count": 200}
        async with session.get(FIFA_API_URL, params=params, timeout=15) as r:
            match_data = await r.json()
        async with session.get(FANTASY_PLAYERS_URL, timeout=15) as r:
            players = await r.json()
        async with session.get(FANTASY_SQUADS_URL, timeout=15) as r:
            squads_raw = await r.json()

    results = match_data.get("Results", [])
    completed, upcoming = [], []
    for m in results:
        status = m.get("MatchStatus")
        home_data = m.get("Home") or {}
        away_data = m.get("Away") or {}
        home = (home_data.get("TeamName") or [{}])[0].get("Description", "?")
        away = (away_data.get("TeamName") or [{}])[0].get("Description", "?")
        hs = m.get("HomeTeamScore")
        aas = m.get("AwayTeamScore")
        entry = {
            "id": m.get("IdMatch"),
            "date": m.get("Date", "?"),
            "stage": (m.get("StageName") or [{}])[0].get("Description") if m.get("StageName") else None,
            "group": (m.get("GroupName") or [{}])[0].get("Description") if m.get("GroupName") else None,
            "home": {"name": home, "score": hs, "id": home_data.get("IdTeam")},
            "away": {"name": away, "score": aas, "id": away_data.get("IdTeam")},
            "winner": m.get("Winner"),
            "status": status,
        }
        (completed if status == 0 else upcoming).append(entry)

    matches_out = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "completed_count": len(completed),
        "upcoming_count": len(upcoming),
        "competition": "FIFA World Cup 2026",
        "completed": completed,
        "upcoming": upcoming,
    }
    data_dir = os.path.join(HERE, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "matches.json"), "w", encoding="utf-8") as f:
        json.dump(matches_out, f, indent=2, ensure_ascii=False)
    with open(os.path.join(data_dir, "players.json"), "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)
    with open(os.path.join(data_dir, "squads.json"), "w", encoding="utf-8") as f:
        json.dump(squads_raw, f, indent=2, ensure_ascii=False)
    print(f"Fetched {len(completed)} completed + {len(upcoming)} upcoming matches")

KNOWN_NAME_VARIANTS = {
    "United States": {"USA"},
    "USA": {"United States"},
    "Cape Verde": {"Cabo Verde"},
    "Cabo Verde": {"Cape Verde"},
    "Korea Republic": {"South Korea"},
    "South Korea": {"Korea Republic"},
    "Czechia": {"Czech Republic"},
    "Czech Republic": {"Czechia"},
    "Türkiye": {"Turkey"},
    "Turkey": {"Türkiye"},
    "IR Iran": {"Iran"},
    "Iran": {"IR Iran"},
    "Bosnia-Herzegovina": {"Bosnia and Herzegovina"},
    "Bosnia and Herzegovina": {"Bosnia-Herzegovina"},
}


def expand_name_variants(name):
    """Return the name plus all known API name variants for this team."""
    result = {name}
    direct = KNOWN_NAME_VARIANTS.get(name, set())
    result.update(direct)
    for k, v in KNOWN_NAME_VARIANTS.items():
        if name in v:
            result.add(k)
    return result


def squad_to_match_name(name):
    variants = expand_name_variants(name) - {name}
    return next(iter(variants), name)


def match_to_squad_name(name):
    variants = expand_name_variants(name) - {name}
    return next(iter(variants), name)


def get_squad_games_played():
    """Return (squad_games, max_games) — how many group matches each squad has played."""
    try:
        matches, players, squads, name_to_id = load_data()
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, 0
    completed = matches.get("completed", [])
    squad_games = {}
    for m in completed:
        stage = m.get("stage", "")
        if stage != "First Stage":
            continue
        for side in ("home", "away"):
            name = m[side]["name"]
            for variant in expand_name_variants(name):
                squad_games[variant] = squad_games.get(variant, 0) + 1
    for sid, s in squads.items():
        if s["name"] not in squad_games:
            squad_games[s["name"]] = 0
    max_games = max(squad_games.values()) if squad_games else 0
    return squad_games, max_games


def get_squad_remaining():
    """Return set of squad names that still have games to play."""
    try:
        matches, players, squads, name_to_id = load_data()
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    upcoming = matches.get("upcoming", [])

    remaining = set()
    for m in upcoming:
        for side in ("home", "away"):
            name = m[side]["name"]
            remaining.update(expand_name_variants(name))
            # Cross-reference against fantasy squad names
            name_lower = name.lower()
            for sid, squad in squads.items():
                if squad["name"].lower() == name_lower:
                    remaining.add(squad["name"])

    return remaining

def load_data():
    with open(os.path.join(HERE, "data", "matches.json"), "r", encoding="utf-8") as f:
        matches = json.load(f)
    with open(os.path.join(HERE, "data", "players.json"), "r", encoding="utf-8") as f:
        players = json.load(f)
    with open(os.path.join(HERE, "data", "squads.json"), "r", encoding="utf-8") as f:
        squads_raw = json.load(f)
    squads = {s["id"]: s for s in squads_raw}
    squad_map = {s["id"]: s["name"] for s in squads_raw}
    # Build direct name-to-ID mapping (handle encoding variations)
    name_to_id = {}
    for s in squads_raw:
        name = s["name"]
        name_to_id[name] = s["id"]
        name_to_id[name.lower()] = s["id"]
    return matches, players, squads, name_to_id


def build_squad_player_map(players):
    squad_players = defaultdict(list)
    for p in players:
        squad_players[p["squadId"]].append(p)
    return squad_players


def get_top_scorers_for_squad(squad_players, squad_id, limit=3):
    players = squad_players.get(squad_id, [])
    scorers = []
    for p in players:
        stats = p.get("stats", {})
        total = stats.get("totalPoints", 0)
        if total == 0:
            continue
        name = p.get("knownName") or f"{p['firstName']} {p['lastName']}"
        pos = p.get("position", "")
        price = p.get("price", 0)
        owned = p.get("percentSelected", 0)
        rp = stats.get("roundPoints", {})
        rp_dict = rp if isinstance(rp, dict) else {}
        n_rounds = len(rp_dict)
        avg = round(total / max(n_rounds, 1), 1)
        scorers.append((total, name, pos, price, owned, avg))
    scorers.sort(key=lambda x: x[0], reverse=True)
    return scorers[:limit]


def match_round_map():
    matches, players, squads, name_to_id = load_data()
    completed = matches.get("completed", [])
    rev_map = name_to_id
    def resolve_match_squad(name):
        mapped = match_to_squad_name(name)
        if mapped in rev_map:
            return rev_map[mapped]
        for sq_name, sq_id in rev_map.items():
            if name.lower() in sq_name.lower() or sq_name.lower() in name.lower():
                return sq_id
        return None
    round_info = {}
    for rnd in ["1", "2"]:
        round_info[rnd] = []
        for m in completed:
            h_sid = resolve_match_squad(m["home"]["name"])
            a_sid = resolve_match_squad(m["away"]["name"])
            if h_sid and a_sid:
                round_info[rnd].append({
                    "home": {"name": m["home"]["name"], "score": m["home"]["score"], "squad_id": h_sid},
                    "away": {"name": m["away"]["name"], "score": m["away"]["score"], "squad_id": a_sid},
                    "group": m.get("group", ""),
                    "date": m.get("date", ""),
                    "id": m.get("id", ""),
                })
    return round_info


def get_match_analytics(limit_matches=4):
    matches, players, squads, name_to_id = load_data()
    completed = matches.get("completed", [])
    upcoming = matches.get("upcoming", [])
    squad_players = build_squad_player_map(players)

    def resolve_squad_id(match_name):
        if match_name in name_to_id:
            return name_to_id[match_name]
        ml = match_name.lower()
        if ml in name_to_id:
            return name_to_id[ml]
        for n, sid in name_to_id.items():
            if isinstance(n, str) and (ml in n.lower() or n.lower() in ml):
                return sid
        return None

    match_reports = []
    sorted_completed = sorted(completed, key=lambda x: x.get("date", ""))
    for m in sorted_completed[-limit_matches:]:
        h_id = resolve_squad_id(m["home"]["name"])
        a_id = resolve_squad_id(m["away"]["name"])
        h_scorers = get_top_scorers_for_squad(squad_players, h_id) if h_id else []
        a_scorers = get_top_scorers_for_squad(squad_players, a_id) if a_id else []
        match_reports.append({
            "home": m["home"]["name"],
            "away": m["away"]["name"],
            "home_score": m["home"]["score"],
            "away_score": m["away"]["score"],
            "group": m.get("group", ""),
            "date": m.get("date", ""),
            "home_scorers": h_scorers,
            "away_scorers": a_scorers,
        })

    upcoming_reports = []
    for m in upcoming[:4]:
        upcoming_reports.append({
            "home": m["home"]["name"],
            "away": m["away"]["name"],
            "group": m.get("group", ""),
            "date": m.get("date", ""),
        })

    return match_reports, upcoming_reports


def get_form_players(position=None, limit=10):
    _, players, squads, _ = load_data()
    squad_map = {s["id"]: s["name"] for s in squads.values()}
    result = []
    for p in players:
        if position and p.get("position", "") != position:
            continue
        stats = p.get("stats", {})
        total = stats.get("totalPoints", 0)
        if total == 0:
            continue
        form = stats.get("form", 0)
        last = stats.get("lastRoundPoints", 0)
        rp = stats.get("roundPoints", {})
        rp_dict = rp if isinstance(rp, dict) else {}
        rounds_played = len(rp_dict)
        name = p.get("knownName") or f"{p['firstName']} {p['lastName']}"
        squad_name = squad_map.get(p.get("squadId", 0), "?")
        result.append({
            "name": name,
            "position": p.get("position", ""),
            "squad": squad_name,
            "total": total,
            "form": form,
            "last": last,
            "rounds_played": rounds_played,
            "price": p.get("price", 0),
            "owned": p.get("percentSelected", 0),
            "avg": round(total / max(rounds_played, 1), 1),
        })
    result.sort(key=lambda x: x["form"], reverse=True)
    return result[:limit]


def get_differentials(limit=10):
    _, players, squads, _ = load_data()
    squad_map = {s["id"]: s["name"] for s in squads.values()}
    result = []
    for p in players:
        stats = p.get("stats", {})
        total = stats.get("totalPoints", 0)
        if total < 5:
            continue
        owned = p.get("percentSelected", 0)
        rp = stats.get("roundPoints", {})
        rp_dict = rp if isinstance(rp, dict) else {}
        n_rounds = len(rp_dict)
        name = p.get("knownName") or f"{p['firstName']} {p['lastName']}"
        squad_name = squad_map.get(p.get("squadId", 0), "?")
        diff_score = total * (1 - owned / 100)
        result.append({
            "name": name,
            "position": p.get("position", ""),
            "squad": squad_name,
            "total": total,
            "owned": owned,
            "price": p.get("price", 0),
            "diff_score": round(diff_score, 1),
            "avg": round(total / max(n_rounds, 1), 1),
        })
    result.sort(key=lambda x: x["diff_score"], reverse=True)
    return result[:limit]

def get_matches_for_team(team_name):
    matches, _, _, _ = load_data()
    completed = matches.get("completed", [])
    upcoming = matches.get("upcoming", [])
    team_results = []
    for m in completed:
        if m["home"]["name"].lower() == team_name.lower() or m["away"]["name"].lower() == team_name.lower():
            team_results.append(m)
    team_upcoming = []
    for m in upcoming:
        if m["home"]["name"].lower() == team_name.lower() or m["away"]["name"].lower() == team_name.lower():
            team_upcoming.append(m)
    return team_results, team_upcoming


def get_group_standings(group_letter):
    """Return standings table + completed/upcoming matches for a group (A-L)."""
    matches, players, squads, name_to_id = load_data()
    completed = matches.get("completed", [])
    upcoming = matches.get("upcoming", [])

    group_tag = f"Group {group_letter.upper()}"

    team_stats = {}
    for s in squads.values():
        if s["group"].upper() == group_letter.upper():
            team_stats[s["name"]] = {
                "name": s["name"], "pld": 0, "w": 0, "d": 0, "l": 0,
                "gf": 0, "ga": 0, "gd": 0, "pts": 0,
            }

    group_completed = []
    for m in completed:
        if m.get("group") != group_tag:
            continue
        group_completed.append(m)
        home = m["home"]["name"]
        away = m["away"]["name"]
        hs = m["home"]["score"]
        aas = m["away"]["score"]
        if home in team_stats:
            team_stats[home]["pld"] += 1
            team_stats[home]["gf"] += hs
            team_stats[home]["ga"] += aas
            if hs > aas:
                team_stats[home]["w"] += 1
                team_stats[home]["pts"] += 3
            elif hs == aas:
                team_stats[home]["d"] += 1
                team_stats[home]["pts"] += 1
            else:
                team_stats[home]["l"] += 1
        if away in team_stats:
            team_stats[away]["pld"] += 1
            team_stats[away]["gf"] += aas
            team_stats[away]["ga"] += hs
            if aas > hs:
                team_stats[away]["w"] += 1
                team_stats[away]["pts"] += 3
            elif aas == hs:
                team_stats[away]["d"] += 1
                team_stats[away]["pts"] += 1
            else:
                team_stats[away]["l"] += 1

    for t in team_stats.values():
        t["gd"] = t["gf"] - t["ga"]

    standings = sorted(team_stats.values(), key=lambda x: (-x["pts"], -x["gd"], -x["gf"]))

    group_upcoming = [m for m in upcoming if m.get("group") == group_tag]

    return standings, group_completed, group_upcoming
