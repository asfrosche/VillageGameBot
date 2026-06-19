"""Precise re-match of lineup players vs fc26_ratings using token_sort_ratio >= 95.
This handles Korean name reversal (Son Heung-min -> Heung Min Son) without false positives."""
import json, sys, unicodedata, re, requests, time
from rapidfuzz import fuzz
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent

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

def load_lineup_players():
    players = set()
    with open(HERE / 'round1_lineups.txt', 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^\s*\d+\.\s+(.+)', line.strip())
            if m:
                name = m.group(1).strip()
                if name:
                    players.add(name)
    return sorted(players)

lineup_players = load_lineup_players()
print(f"Total lineup players: {len(lineup_players)}")

# Load ratings
with open(HERE / 'fc26_ratings.json', 'r', encoding='utf-8') as f:
    ratings = json.load(f)
print(f"Existing ratings: {len(ratings)}")

# ── Phase 1: Match lineup names to existing ratings ──────────────
print("\n=== Phase 1: token_sort_ratio >= 95 match ===")
ratings_items = list(ratings.items())  # (key, entry)
already_rated = set()
new_lineup_matches = {}  # lineup_name -> ratings_key

for name in lineup_players:
    norm = normalize(name)
    best_score = 0
    best_key = None
    
    for rk, rentry in ratings_items:
        rk_norm = normalize(rk)
        score = fuzz.token_sort_ratio(norm, rk_norm)
        if score > best_score:
            best_score = score
            best_key = rk
    
    if best_score >= 95:
        already_rated.add(name)
        new_lineup_matches[name] = best_key
    else:
        new_lineup_matches[name] = None

# Separate high and low confidence
high_conf = {n: k for n, k in new_lineup_matches.items() if k is not None}
low_conf_names = [n for n, k in new_lineup_matches.items() if k is None]

print(f"  Matched (>=95): {len(high_conf)}")
print(f"  Still unmatched: {len(low_conf_names)}")

# Show the matches
for ln, rk in sorted(high_conf.items()):
    if normalize(ln) != normalize(rk):
        print(f"    {ln} -> {rk}")

# ── Phase 2: Try partial name match for remaining ────────────────
print("\n=== Phase 2: Check player_index for unmatched ===")
with open(HERE / 'fc26_player_index.json', 'r', encoding='utf-8') as f:
    index = json.load(f)
with open(HERE / 'fc26_ratings_cache.json', 'r', encoding='utf-8') as f:
    cache = json.load(f)

index_items = list(index.items())

found_in_index = {}  # lineup_name -> index_entry
truly_missing = []

for name in low_conf_names:
    norm = normalize(name)
    best_score = 0
    best_entry = None
    
    for ik, ientry in index_items:
        # Try fullName
        fn = ientry.get('fullName', '')
        score = fuzz.token_sort_ratio(norm, normalize(fn))
        if score > best_score:
            best_score = score
            best_entry = ientry
        
        # Try commonName if different
        cn = ientry.get('commonName', '') or ''
        if cn != fn:
            score2 = fuzz.token_sort_ratio(norm, normalize(cn))
            if score2 > best_score:
                best_score = score2
                best_entry = ientry
    
    if best_score >= 90 and best_entry:
        found_in_index[name] = best_entry
        print(f"  [index] {name} -> {best_entry.get('fullName','?')} (score={best_score:.0f})")
    else:
        truly_missing.append(name)

print(f"  Found in index: {len(found_in_index)}")
print(f"  Truly missing: {len(truly_missing)}")

# ── Phase 3: Fetch ratings for index-found players ───────────────
print("\n=== Phase 3: Fetch ratings for index-found players ===")

def name_to_slug(name):
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    name = name.lower().strip().replace("'", "").replace("'", "")
    name = re.sub(r"[^a-z0-9\s-]", '', name)
    name = re.sub(r'\s+', '-', name)
    return name.strip('-')

def try_fetch(pid, display_name):
    base = "https://www.ea.com/games/ea-sports-fc/ratings/en-us/player-ratings"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    slugs = set()
    if display_name:
        slugs.add(name_to_slug(display_name))
        # Try with common name
        if ' ' in display_name:
            parts = display_name.split()
            if len(parts) >= 2:
                slugs.add(name_to_slug(' '.join(parts)))
    slugs.add(str(pid))
    
    for slug in slugs:
        try:
            r = requests.get(f"{base}/{slug}/{pid}", headers=headers, timeout=10)
            if r.status_code == 200:
                match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', r.text)
                if match:
                    data = json.loads(match.group(1))
                    pl = data['props']['pageProps']['playerRatingsData']['player']
                    if pl and pl.get('ratings'):
                        return pl
        except:
            pass
    return None

# Import map_ea_stats
sys.path.insert(0, str(HERE.parent))
from services.fc26_fetcher import map_ea_stats

newly_fetched = {}
ids_to_fetch = []

for name, entry in found_in_index.items():
    pid = entry.get('id')
    if pid and str(pid) not in cache:
        display = entry.get('fullName') or entry.get('commonName') or name
        ids_to_fetch.append((pid, name, display))
    elif pid:
        # Already cached but not in ratings - add it
        newly_fetched[name] = cache[str(pid)]

print(f"  Already cached: {len(newly_fetched)}")
print(f"  To fetch: {len(ids_to_fetch)}")

if ids_to_fetch:
    batch_size = 5
    for i in range(0, len(ids_to_fetch), batch_size):
        batch = ids_to_fetch[i:i+batch_size]
        with ThreadPoolExecutor(max_workers=batch_size) as pool:
            fut_map = {pool.submit(try_fetch, pid, display): (pid, name) for pid, name, display in batch}
            for f in as_completed(fut_map):
                pid, name = fut_map[f]
                result = f.result()
                if result:
                    attrs = map_ea_stats(result)
                    entry = {
                        "id": result.get("id"),
                        "fullName": f"{result.get('firstName','')} {result.get('lastName','')}",
                        "overall": result.get("overallRating"),
                        "attributes": attrs,
                    }
                    newly_fetched[name] = entry
                    cache[str(pid)] = entry
                    print(f"    FETCHED: {name} (ovr={entry['overall']})")
        time.sleep(0.5)
    
    # Save updated cache
    with open(HERE / 'fc26_ratings_cache.json', 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

print(f"  Newly fetched: {len(newly_fetched)}")

# ── Final: Build final ratings dict ──────────────────────────────
final_ratings = dict(ratings)

# Add high-confidence lineup name -> ratings
for ln, rk in high_conf.items():
    final_ratings[ln] = ratings[rk]

# Add newly fetched
for name, entry in newly_fetched.items():
    final_ratings[name] = entry

# Final check: which lineup players still unrated?
final_unrated = []
for name in lineup_players:
    norm = normalize(name)
    found = False
    for fk in final_ratings:
        if fuzz.token_sort_ratio(norm, normalize(fk)) >= 95:
            found = True
            break
    if not found:
        final_unrated.append(name)

print(f"\n=== Final ===")
print(f"  Total ratings: {len(final_ratings)}")
print(f"  Added to ratings: {len(final_ratings) - 927}")
print(f"  Still unrated lineup players: {len(final_unrated)}")

print("\n=== UNRATED ===")
for p in final_unrated:
    print(f"  {p}")

# Save
with open(HERE / 'fc26_ratings.json', 'w', encoding='utf-8') as f:
    json.dump(final_ratings, f, indent=2, ensure_ascii=False)

with open(HERE / 'fc26_lineup_missing.json', 'w', encoding='utf-8') as f:
    json.dump(final_unrated, f, indent=2, ensure_ascii=False)

print(f"\nSaved fc26_ratings.json ({len(final_ratings)} entries), fc26_lineup_missing.json")
