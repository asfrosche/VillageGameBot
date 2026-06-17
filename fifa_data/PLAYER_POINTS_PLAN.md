# FIFA Fantasy Draft Analytics System

## Overview

Build a fantasy analytics system for the FIFA World Cup Fantasy Draft Discord bot.

The system should:

- Load all drafted teams from `may/draft_data.json`
- Fetch live FIFA fantasy player data
- Match drafted players to FIFA players
- Calculate team scores
- Generate live standings
- Provide player, team, and draft analytics

The implementation should use a reusable service layer so Discord commands only handle displaying the data.

---

# Architecture

Create:

```
services/fantasy_service.py
```

This service is responsible for all fantasy logic.

Responsibilities:

- Load draft data
- Fetch and cache FIFA data
- Match draft players to FIFA players
- Calculate player and team statistics
- Provide analytics used by Discord commands

---

# Data Sources

## Draft Data

File:

```
may/draft_data.json
```

Expected structure:

```
teams:
  user_id:
    username
    players:
      - name
      - country
      - position
```

---

## FIFA Player Data

Source:

```
https://play.fifa.com/json/fantasy/players.json
```

Required fields:

- id
- firstName
- lastName
- knownName
- squadId
- position
- price
- stats.totalPoints
- stats.gamesPlayed
- stats.roundPoints

---

## FIFA Squad Data

Source:

```
https://play.fifa.com/json/fantasy/squads.json
```

Used to map:

```
squadId -> country name + abbreviation
```

---

# FIFA Data Caching

Cache FIFA API responses locally.

Example:

```
fifa_cache/
    players.json
    squads.json
```

Cache duration:

```
120 seconds
```

Behavior:

- Attempt to fetch live data first.
- If the API fails, fall back to the most recent cache.
- Never fail the command because the FIFA API is unavailable.

---

# Player Matching System

The system must match draft player names to FIFA player records.

## Matching Order

### 1. Manual Alias Overrides

Maintain a dictionary of known draft mistakes.

Examples:

```
Kyllian mbappe -> Kylian Mbappe
Christiano Ronaldo -> Cristiano Ronaldo
Vini Jr -> Vinicius Junior
T Curtois -> Thibaut Courtois
F Valverde -> Federico Valverde
De Jong -> Frenkie de Jong
```

---

### 2. Normalize Names

Normalize by:

- Lowercase
- Remove accents
- Remove punctuation
- Remove extra spaces

Example:

```
Kylian Mbappé
becomes
kylian mbappe
```

---

### 3. Exact Match

Compare normalized names directly.

---

### 4. Name and Alias Matching

Check:

- Full name (`firstName + lastName`)
- `knownName`

Examples:

```
Pedri -> Pedro González López
Gakpo -> Cody Gakpo
```

---

### 5. Partial Match

Allow substring matches.

Example:

```
de jong
matches
frenkie de jong
```

---

### 6. Fuzzy Matching

Use similarity scoring (for example `difflib`) as the final fallback.

Examples:

```
mbappe -> Kylian Mbappé
ronaldo -> Cristiano Ronaldo
```

If multiple strong matches exist, return suggestions instead of choosing the wrong player.

Example:

```
Did you mean:
1. Cristiano Ronaldo
2. Ronaldo Nazário
```

---

### 7. Failed Match Handling

Do not crash.

For draft calculations:

```
NOT FOUND
Points: 0
```

Log a warning containing the unmatched player name.

---

# Internal Player Model

Each resolved player should contain:

```
{
    name,
    country,
    country_abbreviation,
    position,
    price,
    games_played,
    total_points,
    round_points
}
```

---

# Discord Commands

## `.standings`

Shows all managers ranked by total fantasy points.

Display:

- Rank
- Username
- Total team points
- Total games played by the squad
- Average points per player

Example:

```
🏆 Draft Standings

1. Alex
   Points: 324
   Games: 46
   Average: 29.4

2. John
   Points: 302
   Games: 43
   Average: 27.5
```

---

## `.team @user`

Displays the complete drafted team.

For every player show:

- Name
- Country
- Position
- Games played
- Total fantasy points

Example:

```
⚽ Alex's Team

Kylian Mbappé 🇫🇷
FWD | Games: 5 | 54 pts

Lamine Yamal 🇪🇸
MID | Games: 5 | 62 pts

...

----------------

Team Total: 324 pts
Total Games: 46
Average: 29.4 pts/player
```

---

## `.player <name>`

Search any FIFA fantasy player using fuzzy matching.

Examples:

```
.player mbappe
.player kyllian mbappe
.player vini jr
.player de jong
.player ronaldo
```

Display:

```
Kylian Mbappé 🇫🇷

Position: FWD
Price: $11.5m

Games Played: 5

Total Points: 54

Round Breakdown:

MD1: 8
MD2: 12
MD3: 9
R16: 15
QF: 10
```

If multiple players are possible, show suggestions.

---

## `.topplayers [position]`

Shows the highest scoring FIFA fantasy players.

Supported commands:

```
.topplayers

.topplayers GK
.topplayers DEF
.topplayers MID
.topplayers FWD
```

Display:

```
🏅 Top Players

1. Lamine Yamal 🇪🇸 MID - 62 pts
2. Kylian Mbappé 🇫🇷 FWD - 54 pts
3. Achraf Hakimi 🇲🇦 DEF - 49 pts
```

Allow sorting by total fantasy points descending.

---

## `.teamvalue @user`

Shows draft quality analysis.

Display:

- Total points by position
- Highest scoring player
- Lowest scoring player
- Average points per player

Example:

```
Alex's Draft Summary

GK:
20 pts

DEF:
88 pts

MID:
156 pts

FWD:
60 pts

Best Pick:
Lamine Yamal - 62 pts

Worst Pick:
Player X - 4 pts

Average:
29.4 pts/player
```

---

# Fantasy Service API

Implement the following methods:

```python
get_leaderboard()

get_team(user_id)

search_player(query)

get_top_players(position=None)

get_team_value(user_id)
```

---

# Implementation Order

## Foundation

1. Create `FantasyService`
2. Implement FIFA API client and caching
3. Load draft data
4. Build player normalization and matching
5. Build player statistics model
6. Calculate team totals

---

## Discord Commands

Implement in this order:

1. `.standings`
2. `.team`
3. `.player`
4. `.topplayers`
5. `.teamvalue`

---

# Error Handling

The system must handle:

- FIFA API downtime by using cached data
- Missing players without crashing
- Invalid usernames or Discord IDs
- Ambiguous player searches by returning suggestions
- Empty or missing statistics gracefully

---

# Acceptance Criteria

The implementation is complete when:

- Every drafted team can be scored automatically.
- Team totals equal the sum of individual player points.
- All Discord commands return valid responses.
- Player searches work with misspellings and abbreviations.
- FIFA data updates automatically using the cache.
- The system can be extended with future commands without rewriting core logic.

---

# Non-Goals (V1)

Do not implement:

- Tournament prediction
- Remaining match calculations
- Ownership statistics
- Matchups between users
- Historical score tracking
- Manual score updates

The system should only report the current state of FIFA fantasy data.