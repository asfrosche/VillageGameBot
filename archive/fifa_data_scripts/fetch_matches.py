import aiohttp
import asyncio
import json
import os
from datetime import datetime

COMPETITION_ID = "17"
SEASON_ID = "285023"
BASE_URL = "https://api.fifa.com/api/v3/calendar/matches"

HERE = os.path.dirname(os.path.abspath(__file__))
MATCHES_FILE = os.path.join(HERE, "data", "matches.json")
PLAYERS_FILE = os.path.join(HERE, "data", "players.json")
SQUADS_FILE = os.path.join(HERE, "data", "squads.json")

FANTASY_PLAYERS_URL = "https://play.fifa.com/json/fantasy/players.json"
FANTASY_SQUADS_URL = "https://play.fifa.com/json/fantasy/squads.json"


async def fetch_matches():
    async with aiohttp.ClientSession() as s:
        params = {
            "idCompetition": COMPETITION_ID,
            "idSeason": SEASON_ID,
            "count": 200,
        }
        async with s.get(BASE_URL, params=params, timeout=15) as r:
            data = await r.json()
    return data.get("Results", [])


async def fetch_fantasy_data():
    async with aiohttp.ClientSession() as s:
        async with s.get(FANTASY_PLAYERS_URL, timeout=15) as r:
            players = await r.json()
        async with s.get(FANTASY_SQUADS_URL, timeout=15) as r:
            squads = await r.json()
    return players, squads


def store_matches(matches):
    completed = []
    upcoming = []
    for m in matches:
        status = m.get("MatchStatus")
        home_data = m.get("Home") or {}
        away_data = m.get("Away") or {}
        home = (home_data.get("TeamName") or [{}])[0].get("Description", "?")
        away = (away_data.get("TeamName") or [{}])[0].get("Description", "?")
        hs = m.get("HomeTeamScore")
        as_ = m.get("AwayTeamScore")
        date = m.get("Date", "?")
        entry = {
            "id": m.get("IdMatch"),
            "date": date,
            "stage": (m.get("StageName") or [{}])[0].get("Description") if m.get("StageName") else None,
            "group": (m.get("GroupName") or [{}])[0].get("Description") if m.get("GroupName") else None,
            "home": {
                "name": home, "score": hs, "id": home_data.get("IdTeam"),
                "players": home_data.get("Players", []),
            },
            "away": {
                "name": away, "score": as_, "id": away_data.get("IdTeam"),
                "players": away_data.get("Players", []),
            },
            "winner": m.get("Winner"),
            "status": status,
        }
        if status == 0:
            completed.append(entry)
        else:
            upcoming.append(entry)

    output = {
        "last_updated": datetime.utcnow().isoformat(),
        "completed_count": len(completed),
        "upcoming_count": len(upcoming),
        "competition": "FIFA World Cup 2026",
        "completed": completed,
        "upcoming": upcoming,
    }
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(completed)} completed + {len(upcoming)} upcoming matches to matches.json")
    return output


def store_fantasy_data(players, squads):
    with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)
    with open(SQUADS_FILE, "w", encoding="utf-8") as f:
        json.dump(squads, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(players)} players and {len(squads)} squads")


async def main():
    print("Fetching 2026 World Cup match data...")
    matches = await fetch_matches()
    store_matches(matches)

    print("Fetching fantasy player data...")
    players, squads = await fetch_fantasy_data()
    store_fantasy_data(players, squads)

    print("Done.")


if __name__ == "__main__":
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
