import asyncio
import json
import os
import ssl
from collections import defaultdict
from datetime import datetime, timezone

import aiohttp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COMPETITION_ID = "17"
SEASON_ID = "285023"
FIFA_API_URL = "https://api.fifa.com/api/v3/calendar/matches"
FANTASY_PLAYERS_URL = "https://play.fifa.com/json/fantasy/players.json"
FANTASY_SQUADS_URL = "https://play.fifa.com/json/fantasy/squads.json"

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


async def _fetch_json(session: aiohttp.ClientSession, url: str, params: dict | None = None) -> dict | list:
    """Fetch JSON with retry and timeout."""
    last_exc = None
    for attempt in range(3):
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as r:
                return await r.json()
        except Exception as e:
            last_exc = e
            await asyncio.sleep(1)
    raise last_exc or Exception(f"Failed to fetch {url}")


async def fetch_and_cache_data():
    """Fetch live match data from FIFA API and cache to disk."""
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=_SSL_CTX)) as session:
        params = {"idCompetition": COMPETITION_ID, "idSeason": SEASON_ID, "count": 200}
        match_data = await _fetch_json(session, FIFA_API_URL, params=params)
        players = await _fetch_json(session, FANTASY_PLAYERS_URL)
        squads_raw = await _fetch_json(session, FANTASY_SQUADS_URL)

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
            "home": {
                "name": home, "score": hs, "id": home_data.get("IdTeam"),
                "players": home_data.get("Players", []),
            },
            "away": {
                "name": away, "score": aas, "id": away_data.get("IdTeam"),
                "players": away_data.get("Players", []),
            },
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

    # Verify data was actually updated
    eliminated = [s for s in squads_raw if s.get("isEliminated")]
    print(f"Fetched {len(completed)} completed + {len(upcoming)} upcoming matches, {len(eliminated)} teams eliminated")

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
    raw_counts = {}
    for m in completed:
        stage = m.get("stage", "")
        if stage != "First Stage":
            continue
        for side in ("home", "away"):
            name = m[side]["name"]
            raw_counts[name] = raw_counts.get(name, 0) + 1
    squad_games = {}
    for sid, s in squads.items():
        sn = s["name"]
        variants = expand_name_variants(sn)
        count = max(raw_counts.get(v, 0) for v in variants)
        squad_games[sn] = count
    max_games = max(squad_games.values()) if squad_games else 0
    return squad_games, max_games


def get_squad_remaining():
    """Return set of squad names that still have group-stage games to play."""
    try:
        matches, players, squads, name_to_id = load_data()
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    upcoming = matches.get("upcoming", [])

    remaining = set()
    for m in upcoming:
        stage = m.get("stage", "")
        if stage != "First Stage":
            continue
        for side in ("home", "away"):
            name = m[side]["name"]
            for sid, squad in squads.items():
                if name.lower() == squad["name"].lower():
                    remaining.add(squad["name"])
                    break
                variants = expand_name_variants(squad["name"])
                if name in variants:
                    remaining.add(squad["name"])
                    break

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


DATA_MAX_AGE = 7200  # seconds (2 hours)

def is_data_stale():
    """Check if cached match data is older than DATA_MAX_AGE."""
    data_dir = os.path.join(HERE, "data")
    matches_path = os.path.join(data_dir, "matches.json")
    if not os.path.exists(matches_path):
        return True
    age = datetime.now(timezone.utc).timestamp() - os.path.getmtime(matches_path)
    return age > DATA_MAX_AGE


async def ensure_fresh_data():
    """Re-fetch match data from FIFA API if cached version is stale."""
    if is_data_stale():
        print("Match data stale, refreshing...")
        await fetch_and_cache_data()


def get_eliminated_set():
    """Return set of team names eliminated from the tournament.

    Derives eliminations from knockout match results (any team that lost
    a knockout match is eliminated). Also includes teams marked as
    eliminated by the FIFA fantasy API.
    """
    eliminated = set()
    try:
        matches, _, squads, name_to_id = load_data()
    except Exception:
        return set()

    # Teams marked eliminated by the API
    for s in squads.values():
        if s.get("isEliminated"):
            eliminated.add(s["name"])

    # Compute from knockout match results
    KO_STAGES = {"Round of 32", "Round of 16", "Quarter-final", "Semi-final", "Play-off for third place", "Final"}
    completed = matches.get("completed", [])
    for m in completed:
        stage = m.get("stage", "")
        if stage not in KO_STAGES:
            continue
        winner_id = m.get("winner")
        home_name = m["home"]["name"]
        away_name = m["away"]["name"]
        home_id = m["home"].get("id")
        away_id = m["away"].get("id")
        # The loser is eliminated
        if winner_id and winner_id == home_id:
            eliminated.add(away_name)
        elif winner_id and winner_id == away_id:
            eliminated.add(home_name)
        elif winner_id is None and m["home"]["score"] is not None:
            # Penalty shootout winner marked via home/away id;
            # fallback: if scores differ, the lower score loses
            hs = m["home"].get("score")
            aws = m["away"].get("score")
            if hs is not None and aws is not None and hs != aws:
                eliminated.add(home_name if hs < aws else away_name)

    return eliminated


def is_team_eliminated(team_name):
    """Check if a specific team has been eliminated."""
    return team_name in get_eliminated_set()


def get_tournament_phase():
    """Return a string describing the current tournament phase."""
    try:
        matches, _, _, _ = load_data()
    except Exception:
        return "unknown"
    completed = matches.get("completed", [])
    upcoming = matches.get("upcoming", [])

    # Tournament order: earliest stage first
    stage_order = ["First Stage", "Round of 32", "Round of 16",
                   "Quarter-final", "Semi-final", "Play-off for third place", "Final"]

    # Find the earliest stage with any upcoming matches — that's the current phase
    for stage in stage_order:
        if any(m.get("stage") == stage for m in upcoming):
            return stage  # some matches done, some left — this is the current phase

    # No upcoming matches at all — tournament may be over
    # Find the latest stage that has completed matches
    for stage in reversed(stage_order):
        if any(m.get("stage") == stage for m in completed):
            return stage

    return "unknown"
