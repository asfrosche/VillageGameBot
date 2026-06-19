"""Re-match unrated lineup players against FC 26 player index with aggressive strategy.
Handles name reversal, partial matching, and fallback fetches."""
import json, os
import sys
import unicodedata
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from pathlib import Path
from rapidfuzz import fuzz, process

HERE = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding='utf-8')

# --- Configuration ---
EA_BASE = "https://www.ea.com/ea-sports-fc/ultimate-team/web-app"
EA_RATINGS = "https://www.ea.com/games/ea-sports-fc/ratings"
MIN_FUZZY_SCORE = 75  # lower threshold than original 85

# --- Normalization ---
def normalize(name):
    nfkd = unicodedata.normalize('NFKD', name)
    return nfkd.encode('ASCII', 'ignore').decode('ASCII').lower().strip()

def normalize_for_match(name):
    """Normalize and remove hyphens for matching."""
    return normalize(name).replace('-', ' ')

# --- Load data ---
print("Loading fc26_ratings.json...")
with open(HERE / 'fc26_ratings.json', 'r', encoding='utf-8') as f:
    existing_ratings = json.load(f)

print("Loading fc26_player_index.json...")
with open(HERE / 'fc26_player_index.json', 'r', encoding='utf-8') as f:
    player_index = json.load(f)

print("Loading fc26_missing_players.json...")
with open(HERE / 'fc26_missing_players.json', 'r', encoding='utf-8') as f:
    missing_players = json.load(f)

# --- Build normalized lookup for existing ratings ---
existing_norm = {normalize_for_match(k): k for k in existing_ratings}

# --- Get all 169 unrated lineup players ---
def get_unrated_lineup_players():
    players = set()
    with open(HERE / 'round1_lineups.txt', 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^\s*\d+\.\s+(.+)', line.strip())
            if m:
                name = m.group(1).strip()
                if name and normalize_for_match(name) not in existing_norm:
                    players.add(name)
    return sorted(players)

unrated = get_unrated_lineup_players()
print(f"\nTotal unrated lineup players to match: {len(unrated)}")

# --- Strategy 1: Aggressive fuzzy match against player_index ---
print("\n=== Strategy 1: Aggressive fuzzy match against player index ===")
index_names = list(player_index.keys())
index_normalized = {normalize_for_match(k): k for k in index_names}

newly_matched = {}  # world_cup_name -> index_key
newly_matched_info = {}  # world_cup_name -> index_entry

for wc_name in unrated:
    wc_norm = normalize_for_match(wc_name)
    
    # Direct check
    if wc_norm in index_normalized:
        idx_key = index_normalized[wc_norm]
        newly_matched[wc_name] = idx_key
        newly_matched_info[wc_name] = player_index[idx_key]
        continue
    
    # Token sort ratio (handles word reordering)
    best_score = 0
    best_match = None
    for idx_name in index_names:
        score = fuzz.token_sort_ratio(wc_norm, normalize_for_match(idx_name))
        if score > best_score:
            best_score = score
            best_match = idx_name
    
    if best_score >= MIN_FUZZY_SCORE:
        newly_matched[wc_name] = best_match
        newly_matched_info[wc_name] = player_index[best_match]

print(f"  Newly matched via index: {len(newly_matched)}")
for wc_name, idx_key in sorted(newly_matched.items()):
    print(f"    {wc_name} -> {idx_key} (score: {best_score})")

# --- Strategy 2: Try fetching player detail page for close matches ---
# For players still not found, try fetching the EA player ratings page
# using slug-based URL construction

still_missing = [p for p in unrated if p not in newly_matched]
print(f"\n=== Strategy 2: Web fetch for still-missing players ===")
print(f"  Still missing: {len(still_missing)}")

# --- Helper to build slug from name ---
def make_slug(name):
    """Convert player name to EA slug format."""
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ASCII', 'ignore').decode('ASCII')
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9\s-]', '', name)
    name = re.sub(r'[\s-]+', '-', name)
    return name

# Try fetching player pages by name
def try_fetch_player(wc_name):
    """Try to fetch a player's ratings page from EA."""
    slug = make_slug(wc_name)
    url = f"https://www.ea.com/games/ea-sports-fc/ratings/en-us/player-ratings/{slug}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            # Try to extract __NEXT_DATA__
            import html
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', resp.text)
            if match:
                data = json.loads(match.group(1))
                # Navigate to find player data
                try:
                    props = data.get('props', {}).get('pageProps', {})
                    player = props.get('playerRatingsData', {}).get('player', {})
                    if player and player.get('ratings'):
                        return wc_name, player
                except:
                    pass
    except:
        pass
    return wc_name, None

# Try fetching in batches with rate limiting
fetched_results = {}
batch_size = 5
for i in range(0, len(still_missing), batch_size):
    batch = still_missing[i:i+batch_size]
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(try_fetch_player, name): name for name in batch}
        for future in as_completed(futures):
            wc_name, player_data = future.result()
            if player_data:
                fetched_results[wc_name] = player_data
                print(f"  FETCHED: {wc_name}")
    time.sleep(1)  # rate limit

# --- Strategy 3: Try alternative slug variations ---
for wc_name in still_missing:
    if wc_name in fetched_results:
        continue
    # Try reversed name slug
    parts = wc_name.replace('-', ' ').split()
    if len(parts) >= 2:
        rev_name = ' '.join(reversed(parts))
        _, result = try_fetch_player(rev_name)
        if result:
            fetched_results[wc_name] = result
            print(f"  FETCHED (reversed): {wc_name} as {rev_name}")
            time.sleep(0.5)

print(f"\n  Fetched via web: {len(fetched_results)}")

# --- Compile results ---
total_new = len(newly_matched) + len(fetched_results)
print(f"\n=== Summary ===")
print(f"  Total newly matched: {total_new}")
print(f"  Still unrated: {len(unrated) - total_new}")

# --- Output newly matched for next step (fetch full ratings) ---
output = {
    "newly_matched_via_index": {k: v for k, v in newly_matched.items()},
    "newly_matched_via_fetch": {k: v for k, v in fetched_results.items()},
    "still_missing": [p for p in unrated if p not in newly_matched and p not in fetched_results]
}

with open(HERE / 'fc26_new_matches.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\nResults saved to fc26_new_matches.json")
