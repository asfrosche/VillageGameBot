# How to Fetch FIFA Fantasy Data

The draft cog uses live data from `play.fifa.com` at runtime (cached for 2 minutes), but the local JSON snapshots in this directory are useful for offline reference or debugging.

## Source URLs

- **Players**: https://play.fifa.com/json/fantasy/players.json
- **Squads (teams)**: https://play.fifa.com/json/fantasy/squads.json

## How to Download (Any Method)

### Option 1 — cURL

```bash
curl -o players.json https://play.fifa.com/json/fantasy/players.json
curl -o squads.json https://play.fifa.com/json/fantasy/squads.json
```

### Option 2 — PowerShell

```powershell
Invoke-WebRequest -Uri "https://play.fifa.com/json/fantasy/players.json" -OutFile "players.json"
Invoke-WebRequest -Uri "https://play.fifa.com/json/fantasy/squads.json" -OutFile "squads.json"
```

### Option 3 — Python One-liner

```python
import urllib.request, json
urls = {"players.json": "https://play.fifa.com/json/fantasy/players.json",
        "squads.json": "https://play.fifa.com/json/fantasy/squads.json"}
for fname, url in urls.items():
    with urllib.request.urlopen(url) as r, open(fname, "wb") as f:
        f.write(r.read())
```

## Data Structure

### players.json
Array of player objects. Key fields:
- `id` — unique player ID
- `firstName`, `lastName`, `knownName` — player name
- `squadId` — FK to squads.json
- `position` — `"GK"`, `"DEF"`, `"MID"`, `"FWD"`
- `price` — fantasy price
- `status` — `"playing"`, `"transferred"`, etc.
- `stats.totalPoints` — fantasy points total
- `stats.lastRoundPoints` — points from the most recent match
- `stats.roundPoints` — dict of round → points (e.g. `{"1": 9}`)

### squads.json
Array of squad objects. Key fields:
- `id` — squad ID (matches `squadId` in players.json)
- `name` — full team name (e.g. `"Argentina"`)
- `abbr` — 3-letter abbreviation (e.g. `"ARG"`)

## When to Refresh

Refresh whenever you want an offline snapshot. The bot itself fetches live data on every `.draftpoints` / `.playerpoints` command, so the local files are optional.
