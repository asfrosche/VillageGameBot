import json
import os
import sys
import asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
FIFA_DATA = os.path.dirname(HERE)  # fifa_data/
sys.path.insert(0, FIFA_DATA)

from services.fantasy_service import FantasyService

DRAFT_FILE = os.path.join(FIFA_DATA, "data", "draft_data.json")
FIFA_PLAYERS_FILE = os.path.join(FIFA_DATA, "data", "players.json")
FIFA_SQUADS_FILE = os.path.join(FIFA_DATA, "data", "squads.json")


def load_local_fifa():
    if os.path.exists(FIFA_PLAYERS_FILE):
        with open(FIFA_PLAYERS_FILE, "r", encoding="utf-8") as f:
            players = json.load(f)
        squads = {}
        if os.path.exists(FIFA_SQUADS_FILE):
            with open(FIFA_SQUADS_FILE, "r", encoding="utf-8") as f:
                squads_raw = json.load(f)
            squads = {s["id"]: s for s in squads_raw}
        return players, squads
    return None, None


async def main():
    draft = None
    if os.path.exists(DRAFT_FILE):
        with open(DRAFT_FILE, "r", encoding="utf-8") as f:
            draft = json.load(f)
    if not draft:
        print("No draft_data.json found.")
        return

    gid = list(draft.keys())[0]
    draft_data = draft[gid]

    service = FantasyService()

    local_players, local_squads = load_local_fifa()
    if local_players:
        service._players = local_players
        service._squads = local_squads
        print(f"Loaded {len(local_players)} players from local {FIFA_PLAYERS_FILE}")
    else:
        print("Local players.json not found, fetching from play.fifa.com...")
        await service.fetch_data()

    total_picks = 0
    matched = 0
    unmatched_names = []

    for uid_str, team in draft_data["teams"].items():
        for player in team["players"]:
            total_picks += 1
            match = service.match_player(player["name"])
            if match:
                player["fifa_id"] = match["id"]
                player["fifa_name"] = match.get("knownName") or f"{match['firstName']} {match['lastName']}"
                matched += 1
            else:
                player["fifa_id"] = None
                player["fifa_name"] = None
                unmatched_names.append(player["name"])

    draft[gid] = draft_data

    with open(DRAFT_FILE, "w", encoding="utf-8") as f:
        json.dump(draft, f, indent=2, ensure_ascii=False)

    import sys
    print(f"\n{'='*50}")
    print(f"Total picks: {total_picks}")
    print(f"Matched: {matched}")
    print(f"Unmatched: {len(unmatched_names)}")
    if unmatched_names:
        print(f"\nUnmatched players ({len(unmatched_names)}):")
        for name in unmatched_names:
            safe = name.encode(sys.stdout.encoding, errors="replace").decode(sys.stdout.encoding)
            print(f"  - {safe}")
    print(f"{'='*50}")
    print(f"Updated: {DRAFT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
