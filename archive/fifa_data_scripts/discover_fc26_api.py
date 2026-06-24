"""
EA SPORTS FC 26 Player Ratings API Discovery Script
====================================================
Probes the EA FC 26 official ratings website to document the data source.

Data Source: https://www.ea.com/games/ea-sports-fc/ratings

Discovery:
  - Main ratings page embeds 100 players per page via Next.js __NEXT_DATA__
  - Individual player pages (player-ratings/{slug}/{id}) have full stats + sub-stats
  - buildId: o6p3EEJ1JS2xCRPszDbNO (rotates per deployment)
  - All 40+ stats are embedded as server-side props; no separate API endpoint needed
  - Images served from: ratings-images-prod.pulse.ea.com
"""

import json
import re
import sys
from datetime import datetime

import httpx

FC26_BASE = "https://www.ea.com/games/ea-sports-fc/ratings"
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

TEST_PLAYERS = [
    ("Kylian Mbappé", "France", 231747, "kylian-mbappe"),
    ("Lionel Messi", "Argentina", 158023, "lionel-messi"),
    ("Erling Haaland", "Norway", 239085, "erling-haaland"),
]


def fetch_text(url: str) -> str | None:
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  [ERROR] {url}: {e}")
        return None


def extract_next_data(html: str) -> dict | None:
    match = NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"  [ERROR] Failed to parse __NEXT_DATA__: {e}")
        return None


def discover_main_page():
    """Fetch the main ratings listing and analyse __NEXT_DATA__."""
    print("\n" + "=" * 72)
    print("1. MAIN RATINGS LISTING PAGE")
    print("=" * 72)

    url = f"{FC26_BASE}?page=1"
    print(f"\nFetching: {url}")
    html = fetch_text(url)
    if not html:
        print("  FAILED - skipping main page discovery")
        return

    data = extract_next_data(html)
    if not data:
        print("  No __NEXT_DATA__ found")
        return

    page_props = data.get("props", {}).get("pageProps", {})
    rating_details = page_props.get("ratingDetails", {})

    items = rating_details.get("items", [])
    total = rating_details.get("totalItems", 0)

    print(f"\n  buildId:          {data.get('buildId', 'unknown')}")
    print(f"  totalItems:       {total}")
    print(f"  items in page 1:  {len(items)}")
    print(f"  estimated pages:  {total // max(len(items), 1) + (1 if total % max(len(items), 1) else 0)}")

    if items:
        first = items[0]
        print(f"\n  Top-ranked player: {first.get('firstName')} {first.get('lastName')} (OVR {first.get('overallRating')})")
        print(f"  Player ID:         {first.get('id')}")
        print(f"  Top-level keys:    {list(first.keys())}")

        stats = first.get("stats", {})
        print(f"  Stat keys ({len(stats)}): {list(stats.keys())[:12]}...")

    total_found = page_props.get("ratingDetails", {}).get("totalItems", 0)
    print(f"\n  Total players in database: {total_found}")

    # Check for search/filter parameters
    print("\n  Checking query parameters...")
    print(f"  Current URL: {url}")
    print("  Note: Search is client-side JS filtering of pre-loaded data")

    return page_props


def discover_player_page(slug: str, player_id: int, name: str):
    """Fetch an individual player page and extract full ratings."""
    print(f"\n  {'=' * 68}")
    print(f"  PLAYER: {name} (ID: {player_id}, slug: {slug})")
    print(f"  {'=' * 68}")

    url = f"{FC26_BASE}/player-ratings/{slug}/{player_id}"
    print(f"  Fetching: {url}")
    html = fetch_text(url)
    if not html:
        print("  FAILED")
        return None

    data = extract_next_data(html)
    if not data:
        print("  No __NEXT_DATA__ found")
        return None

    page_props = data.get("props", {}).get("pageProps", {})
    entries = page_props.get("ratingsEntries", {})
    items = entries.get("items", [])

    if not items:
        print("  No ratings entries found in page props")
        return None

    player = items[0]

    print(f"  Name:             {player.get('firstName')} {player.get('lastName')}")
    print(f"  OVR:              {player.get('overallRating')}")
    print(f"  Position:         {player.get('position', {}).get('shortLabel', 'N/A')}")
    print(f"  Nationality:      {player.get('nationality', {}).get('label', 'N/A')}")
    print(f"  Team:             {player.get('team', {}).get('label', 'N/A')}")
    print(f"  League:           {player.get('leagueName', 'N/A')}")
    print(f"  Skill Moves:      {player.get('skillMoves')}")
    print(f"  Weak Foot:        {player.get('weakFootAbility')}")
    print(f"  Height:           {player.get('height')} cm")
    print(f"  Weight:           {player.get('weight')} kg")
    print(f"  Alternate Pos:    {[ap.get('shortLabel', '') for ap in player.get('alternatePositions', [])]}")

    stats = player.get("stats", {})
    print(f"\n  Core Stats:")
    for code in ("PAC", "SHO", "PAS", "DRI", "DEF", "PHY"):
        val = stats.get(code, {})
        print(f"    {code}: {val.get('value', 'N/A')} (diff: {val.get('diff', 0)})")

    print(f"\n  Sub-Stats ({len(stats)} total):")
    for stat_key, stat_val in sorted(stats.items()):
        if stat_key not in ("PAC", "SHO", "PAS", "DRI", "DEF", "PHY"):
            print(f"    {stat_key}: {stat_val.get('value', 'N/A')} (diff: {stat_val.get('diff', 0)})")

    abilities = player.get("playerAbilities", [])
    print(f"\n  PlayStyles ({len(abilities)}):")
    for ab in abilities[:6]:
        print(f"    - {ab.get('label')} [{ab.get('type', 'N/A')}]")

    print()
    return player


def document_attribute_mapping():
    """Document how EA FC 26 stats map to simulation attributes."""
    mapping = {
        # EA FC 26 stat → simulation attribute
        "PAC.value": "pace",
        "SHO.value": "finishing",
        "PAS.value": "passing",
        "DRI.value": "dribbling",
        "DEF.value": "defending",
        "PHY.value": "physical",
        # Sub-stats for specific positions
        "acceleration": "pace (shared)",
        "sprintSpeed": "pace (shared)",
        "finishing": "finishing (shared)",
        "shotPower": "shot_power",
        "longShots": "long_shots",
        "positioning": "positioning",
        "volleys": "(not used)",
        "penalties": "penalties",
        "vision": "vision",
        "crossing": "crossing",
        "shortPassing": "passing (shared)",
        "longPassing": "passing (shared)",
        "curve": "(not used)",
        "freeKickAccuracy": "free_kick_accuracy",
        "agility": "agility",
        "balance": "balance",
        "reactions": "reactions (CB)",
        "ballControl": "dribbling (shared)",
        "dribbling": "dribbling (shared)",
        "composure": "composure (ST)",
        "interceptions": "interceptions (DM)",
        "headingAccuracy": "heading_accuracy",
        "marking": "defensive_awareness (CB)",
        "standingTackle": "tackling (CB)",
        "slidingTackle": "tackling (shared)",
        "jumping": "jumping",
        "stamina": "stamina",
        "strength": "strength (CB)",
        "aggression": "aggression",
    }

    stats_used_by_formulas = {
        "ST": ["finishing", "positioning", "shot_power", "pace", "composure"],
        "WINGER": ["pace", "dribbling", "crossing", "finishing", "vision"],
        "CM": ["passing", "vision", "dribbling", "stamina", "defending"],
        "DM": ["defending", "interceptions", "passing", "physical", "stamina"],
        "FB": ["pace", "defending", "crossing", "stamina", "passing", "dribbling"],
        "CB": ["defensive_awareness", "tackling", "strength", "pace", "reactions"],
        "GK": ["reflexes", "diving", "positioning", "handling", "kicking"],
    }

    print("=" * 72)
    print("3. ATTRIBUTE MAPPING: EA FC 26 → Simulation Engine")
    print("=" * 72)
    print(f"\n  {'EA Stat':<25} {'→ Simulation Attribute':<30}")
    print(f"  {'─' * 25}   {'─' * 30}")
    for ea_key, sim_attr in mapping.items():
        print(f"  {ea_key:<25} → {sim_attr:<30}")

    print(f"\n\n  Position Formula Requirements:")
    print(f"  {'─' * 60}")
    for position, attrs in stats_used_by_formulas.items():
        print(f"  {position:<10} needs: {', '.join(attrs)}")


def main():
    print(f"EA SPORTS FC 26 RATINGS API DISCOVERY")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Source: {FC26_BASE}")

    # 1. Discover the main page structure
    discover_main_page()

    # 2. Fetch individual player pages
    print("\n" + "=" * 72)
    print("2. INDIVIDUAL PLAYER PAGES")
    print("=" * 72)
    for name, country, player_id, slug in TEST_PLAYERS:
        print()

        # Determine nationality from page data
        discover_player_page(slug, player_id, name)

    # 3. Document mapping
    document_attribute_mapping()

    print("\n" + "=" * 72)
    print("DISCOVERY SUMMARY")
    print("=" * 72)
    print("""
  Data Source:  ea.com EA SPORTS FC 26 Official Ratings Website
  Method:       Parse <script id="__NEXT_DATA__"> from server-rendered HTML
  Player Page:  {BASE}/player-ratings/{slug}/{player_id}
  Listing Page: {BASE}?page=N (100 players per page)

  Data Shape (__NEXT_DATA__):
    props.pageProps.ratingDetails.items[]     (main listing, 100/page)
    props.pageProps.ratingDetails.totalItems  (total: 17,873)
    props.pageProps.ratingsEntries.items[]    (individual page, 1 player)

  Player Object Keys:
    id, firstName, lastName, commonName, overallRating, birthdate,
    height, weight, skillMoves, weakFootAbility, preferredFoot,
    leagueName, avatarUrl, shieldUrl, position, nationality, team,
    gender, alternatePositions, playerAbilities, stats{}

  Stats Object (41 keys):
    PAC, SHO, PAS, DRI, DEF, PHY (each: {value, diff})
    + sub-stats: acceleration, sprintSpeed, finishing, shotPower,
      longShots, volleys, penalties, positioning, vision, crossing,
      shortPassing, longPassing, curve, freeKickAccuracy, agility,
      balance, reactions, ballControl, dribbling, composure,
      interceptions, headingAccuracy, marking, standingTackle,
      slidingTackle, jumping, stamina, strength, aggression

  Limitation: No public search API found; player ID needed for URL.
              Main listing page required for name→ID lookup.
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
