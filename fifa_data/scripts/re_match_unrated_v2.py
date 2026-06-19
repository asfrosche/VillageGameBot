"""Re-match all 169 unrated lineup players using fuzzy matching + fallback fetch.
Handles Korean name reversal (Son Heung-min -> Heung Min Son), accented chars, etc."""
import json
import sys
import unicodedata
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidfuzz import fuzz
from pathlib import Path
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# ── Normalization (matches fc26_fetcher.py) ──────────────────────
_CHAR_MAP = str.maketrans({
    'ş': 's', 'Ş': 'S', 'ç': 'c', 'Ç': 'C', 'ü': 'u', 'Ü': 'U',
    'ö': 'o', 'Ö': 'O', 'ğ': 'g', 'Ğ': 'G', 'ı': 'i', 'İ': 'I',
    'ə': 'e', 'Ə': 'E', 'š': 's', 'č': 'c', 'ř': 'r', 'ž': 'z',
    'ý': 'y', 'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
    'ň': 'n', 'ď': 'd', 'ť': 't', 'ľ': 'l', 'ä': 'a', 'ë': 'e',
    'ø': 'o', 'Ø': 'O', 'æ': 'ae', 'å': 'a', 'ñ': 'n', 'ß': 'ss',
    'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'À': 'A',
    'È': 'E', 'Ì': 'I', 'Ò': 'O', 'Ù': 'U', 'Â': 'A', 'Ê': 'E',
    'Î': 'I', 'Ô': 'O', 'Û': 'U', 'Ã': 'A', 'Õ': 'O', 'Ñ': 'N',
})

def normalize(name):
    name = name.translate(_CHAR_MAP)
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
    ascii_str = ascii_str.lower().strip()
    ascii_str = re.sub(r"[^a-z0-9']+", ' ', ascii_str)
    return re.sub(r'\s+', ' ', ascii_str).strip()

def name_to_slug(name):
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    name = name.lower().strip().replace("'", "").replace("'", "")
    name = re.sub(r"[^a-z0-9\s-]", '', name)
    name = re.sub(r'\s+', '-', name)
    return name.strip('-')

# ── Load data ────────────────────────────────────────────────────
print("Loading fc26_ratings.json...")
with open(HERE / 'fc26_ratings.json', 'r', encoding='utf-8') as f:
    ratings = json.load(f)

print("Loading fc26_ratings_cache.json...")
with open(HERE / 'fc26_ratings_cache.json', 'r', encoding='utf-8') as f:
    cache = json.load(f)

print("Loading fc26_player_index.json...")
with open(HERE / 'fc26_player_index.json', 'r', encoding='utf-8') as f:
    index = json.load(f)

# ── Get all lineup player names ──────────────────────────────────
lineup_players = set()
with open(HERE / 'round1_lineups.txt', 'r', encoding='utf-8') as f:
    for line in f:
        m = re.match(r'^\s*\d+\.\s+(.+)', line.strip())
        if m:
            name = m.group(1).strip()
            if name:
                lineup_players.add(name)

print(f"Total lineup players: {len(lineup_players)}")

# ── Phase 1: Fuzzy match lineup names against existing ratings ────
print("\n=== Phase 1: Fuzzy match lineup names vs fc26_ratings.json ===")
ratings_norm = {normalize(k): k for k in ratings}
ratings_indexed = list(ratings_norm.keys())

matched_in_ratings = {}  # lineup_name -> ratings_key
still_unmatched = []

for name in sorted(lineup_players):
    norm = normalize(name)
    
    # Direct match
    if norm in ratings_norm:
        matched_in_ratings[name] = ratings_norm[norm]
        continue
    
    # Token sort ratio (handles word reordering like "son heung min" -> "heung min son")
    best_score = 0
    best_key = None
    for rn in ratings_indexed:
        score = fuzz.token_sort_ratio(norm, rn)
        if score > best_score:
            best_score = score
            best_key = rn
    
    if best_score >= 90:
        matched_in_ratings[name] = ratings_norm[best_key]
    elif best_score >= 80:
        # Manual review needed for 80-90 range
        matched_in_ratings[name] = ratings_norm[best_key]
        print(f"  [80-90] {name} -> {ratings_norm[best_key]} (score={best_score:.0f})")
    else:
        still_unmatched.append(name)

print(f"  Matched in ratings: {len(matched_in_ratings)}")
print(f"  Still unmatched: {len(still_unmatched)}")

# ── Phase 2: Check player index for still-unmatched players ──────
print("\n=== Phase 2: Check fc26_player_index.json ===")
index_norm = {normalize(k): k for k in index}
index_names = list(index_norm.keys())

found_in_index = {}  # lineup_name -> index_entry
truly_missing = []

for name in still_unmatched:
    norm = normalize(name)
    
    # Direct match in index
    if norm in index_norm:
        found_in_index[name] = index[index_norm[norm]]
        continue
    
    # Token sort ratio
    best_score = 0
    best_key = None
    for idx_norm_name in index_names:
        score = fuzz.token_sort_ratio(norm, idx_norm_name)
        if score > best_score:
            best_score = score
            best_key = idx_norm_name
    
    if best_score >= 85:
        found_in_index[name] = index[index_norm[best_key]]
        print(f"  [index] {name} -> {index_norm[best_key]} (score={best_score:.0f})")
    elif best_score >= 75:
        # Check if nationality helps
        entry = index[index_norm[best_key]]
        print(f"  [LO] {name} -> {index_norm[best_key]} (score={best_score:.0f})")
        found_in_index[name] = entry
    else:
        truly_missing.append(name)

print(f"  Found in index: {len(found_in_index)}")
print(f"  Truly missing: {len(truly_missing)}")

# ── Phase 3: Fetch full ratings for index-found players ──────────
print("\n=== Phase 3: Fetch full ratings for newly found players ===")
newly_fetched = {}  # name -> ratings

# Collect IDs to fetch (not already in cache)
ids_to_fetch = {}  # player_id -> (name, slug_name)
for name, entry in found_in_index.items():
    pid = entry.get('id')
    if pid and str(pid) not in cache:
        display = entry.get('fullName', entry.get('commonName', name))
        ids_to_fetch[pid] = (name, display)

# Also check if already in cache but not in ratings
for name, entry in found_in_index.items():
    pid = entry.get('id')
    if pid and str(pid) in cache:
        # Already in cache but wasn't matched in ratings - add it
        newly_fetched[name] = cache[str(pid)]

print(f"  IDs to fetch: {len(ids_to_fetch)}")
print(f"  Already cached: {len(newly_fetched)}")

# Try fetching with multiple slug variations
def try_fetch_ratings(pid, display_name):
    """Try fetching a player's ratings page with multiple slug variations."""
    base_url = "https://www.ea.com/games/ea-sports-fc/ratings/en-us/player-ratings"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    # Try different slug variations
    slug_variations = [
        name_to_slug(display_name),
        name_to_slug(display_name.replace(' ', '-')),
    ]
    # Also try without slug (just ID)
    slug_variations.append(str(pid))
    
    for slug in slug_variations:
        if not slug:
            continue
        url = f"{base_url}/{slug}/{pid}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', resp.text)
                if match:
                    data = json.loads(match.group(1))
                    try:
                        player = data['props']['pageProps']['playerRatingsData']['player']
                        if player and player.get('ratings'):
                            return player
                    except:
                        pass
        except:
            pass
    return None

fetched_count = 0
batch_size = 5
fetch_list = list(ids_to_fetch.items())

for i in range(0, len(fetch_list), batch_size):
    batch = fetch_list[i:i+batch_size]
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = {executor.submit(try_fetch_ratings, pid, display): (pid, name) 
                   for pid, (name, display) in batch}
        for future in as_completed(futures):
            pid, name = futures[future]
            result = future.result()
            if result:
                # Map ratings
                from services.fc26_fetcher import map_ea_stats
                attrs = map_ea_stats(result)
                entry = {
                    "id": result.get("id"),
                    "fullName": result.get("firstName", "") + " " + result.get("lastName", ""),
                    "overall": result.get("overallRating"),
                    "position": result.get("position", {}).get("shortLabel", ""),
                    "nationality": result.get("nationality", {}).get("label", ""),
                    "team": result.get("team", {}).get("label", ""),
                    "attributes": attrs,
                }
                newly_fetched[name] = entry
                fetched_count += 1
                # Update cache
                cache[str(pid)] = entry
                print(f"  FETCHED: {name} (id={pid}, ovr={entry['overall']})")
    time.sleep(0.5)

print(f"  Newly fetched: {fetched_count}")

# ── Phase 4: Compile final results ───────────────────────────────
print("\n=== Final Results ===")

# Build final ratings dict (merge existing + newly matched + newly fetched)
final_ratings = dict(ratings)

# Add newly matched (keyed by lineup name)
for lineup_name, ratings_key in matched_in_ratings.items():
    # Key by both the original name and the normalized version
    final_ratings[lineup_name] = ratings[ratings_key]

# Add newly fetched
for name, entry in newly_fetched.items():
    final_ratings[name] = entry

# Final check: which lineup players are still missing?
final_unrated = []
for name in sorted(lineup_players):
    norm = normalize(name)
    found = False
    for rk in final_ratings:
        if normalize(rk) == norm or fuzz.token_sort_ratio(norm, normalize(rk)) >= 90:
            found = True
            break
    if not found:
        final_unrated.append(name)

print(f"  Total ratings now: {len(final_ratings)}")
print(f"  Previously rated: {len(ratings)}")
print(f"  Added: {len(final_ratings) - len(ratings)}")
print(f"  Still unrated lineup players: {len(final_unrated)}")
print()
print("=== STILL UNRATED ===")
for p in truly_missing:
    print(f"  {p}")

# ── Save results ─────────────────────────────────────────────────
with open(HERE / 'fc26_ratings.json', 'w', encoding='utf-8') as f:
    json.dump(final_ratings, f, indent=2, ensure_ascii=False)

with open(HERE / 'fc26_ratings_cache.json', 'w', encoding='utf-8') as f:
    json.dump(cache, f, indent=2, ensure_ascii=False)

# Save still-missing list
missing_report = {}
for p in truly_missing:
    missing_report[p] = "not_found"
for p in final_unrated:
    if p not in missing_report:
        missing_report[p] = "not_found"
with open(HERE / 'fc26_lineup_missing.json', 'w', encoding='utf-8') as f:
    json.dump(missing_report, f, indent=2, ensure_ascii=False)

print(f"\nResults saved to fc26_ratings.json, fc26_ratings_cache.json, fc26_lineup_missing.json")
print(f"Total ratings: {len(final_ratings)}")
