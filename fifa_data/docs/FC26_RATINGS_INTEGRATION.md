# FC 26 Ratings Integration

Replaces synthetic placeholder ratings with real EA SPORTS FC 26 attributes.

## Files

| File | What it does |
|------|-------------|
| `fc26_fetcher.py` | Scrapes EA's official FC 26 ratings site. Builds a player name→ID index (179 pages, ~18k players), fuzzy-matches World Cup names, fetches individual pages with 29 attributes each, caches results. |
| `populate_fc26_ratings.py` | Gathers all 1,273 World Cup player names from rosters + match lineups, calls `fc26_fetcher` to match & fetch, writes `fc26_ratings.json` and `fc26_missing_players.json`. |
| `fc26_ratings.json` | Cached full ratings for matched players (name → {overall, attributes}). |
| `fc26_missing_players.json` | Unmatched player names with reason codes (not_in_index / below_threshold / fetch_failed). |
| `services/v2_data_loader.py` | Modified: `_load_fc26_ratings()` lazily loads the cache; `_apply_fc26_ratings()` overrides player attributes with real FC 26 data via `dataclasses.replace`. Synthetic attribute generation removed – players without FC 26 data get `{}`. |

## Coverage

- **1,273** World Cup players searched
- **927** matched (73%) — 962 found in index, 927 fetched successfully, ~35 with 404 errors
- **822 of 1,530** squad slots (53.7%) now carry real FC 26 ratings

## How it works

1. `load_v2_squads()` builds each squad normally
2. Each player passes through `_apply_fc26_ratings()`
3. If FC 26 data exists → attributes + roster_rating are overwritten with real EA stats
4. If no FC 26 data → attributes stay `{}` (no synthetic fallback)

## Missing players

`fc26_missing_players.json` lists all unmatched players by reason:
- `not_in_index`: name didn't appear in the 18k EA player database
- `below_threshold`: fuzzy match found but similarity < 85%
- `fetch_failed`: matched but individual page returned 404

To improve coverage, re-run `populate_fc26_ratings.py` — it will skip already-cached players.
