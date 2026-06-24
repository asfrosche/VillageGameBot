"""
FC 26 Player Ratings Fetcher
=============================
Fetches and caches EA SPORTS FC 26 player ratings from the official website.

Data Source:
  - Main listing:  https://www.ea.com/games/ea-sports-fc/ratings?page=N
  - Player page:   https://www.ea.com/games/ea-sports-fc/ratings/player-ratings/{slug}/{player_id}

Usage:
    from fc26_fetcher import Fc26Fetcher
    fetcher = Fc26Fetcher()
    ratings = fetcher.lookup_player("Kylian Mbappé", "France")
    print(ratings)  # {'overall': 91, 'pace': 97, 'finishing': 90, ...}
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
from rapidfuzz import fuzz
from tqdm import tqdm

HERE = Path(__file__).resolve().parents[1]
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

# Character mapping for slug generation (handles Turkish, Scandinavian, etc.)
_CHAR_MAP = {
    ord("ı"): "i", ord("İ"): "i",
    ord("ğ"): "g", ord("Ğ"): "g",
    ord("ü"): "u", ord("Ü"): "u",
    ord("ş"): "s", ord("Ş"): "s",
    ord("ö"): "o", ord("Ö"): "o",
    ord("ç"): "c", ord("Ç"): "c",
    ord("ə"): "e", ord("Ə"): "e",
    ord("ñ"): "n", ord("Ñ"): "n",
    ord("æ"): "ae", ord("Æ"): "ae",
    ord("ø"): "o", ord("Ø"): "o",
    ord("å"): "a", ord("Å"): "a",
    ord("ß"): "ss",
}

# EA FC 26 stat code → simulation attribute name mapping
EA_STAT_TO_SIM: dict[str, str | None] = {
    "pac": "pace",
    "sho": "finishing",
    "pas": "passing",
    "dri": "dribbling",
    "def": "defending",
    "phy": "physical",
    "acceleration": "pace",
    "sprintSpeed": "pace",
    "finishing": "finishing",
    "shotPower": "shot_power",
    "longShots": "long_shots",
    "positioning": "positioning",
    "volleys": None,
    "penalties": "penalties",
    "vision": "vision",
    "crossing": "crossing",
    "shortPassing": "passing",
    "longPassing": "passing",
    "curve": None,
    "freeKickAccuracy": "free_kick_accuracy",
    "agility": "agility",
    "balance": "balance",
    "reactions": "reactions",
    "ballControl": "dribbling",
    "dribbling": "dribbling",
    "composure": "composure",
    "interceptions": "interceptions",
    "headingAccuracy": "heading_accuracy",
    "defensiveAwareness": "defensive_awareness",
    "standingTackle": "tackling",
    "slidingTackle": "tackling",
    "jumping": "jumping",
    "stamina": "stamina",
    "strength": "strength",
    "aggression": "aggression",
    "gkDiving": "diving",
    "gkHandling": "handling",
    "gkKicking": "kicking",
    "gkPositioning": "positioning",
    "gkReflexes": "reflexes",
}

# Stats that directly contribute to simulation formulas
SIM_FORMULA_STATS = {
    "pace", "finishing", "passing", "dribbling", "defending", "physical",
    "positioning", "shot_power", "composure", "crossing", "vision",
    "stamina", "interceptions", "defensive_awareness", "tackling",
    "strength", "reactions", "reflexes", "diving", "handling", "kicking",
    "penalties", "free_kick_accuracy", "agility", "balance", "jumping",
    "aggression", "heading_accuracy",
}


def normalize_player_name(name: str) -> str:
    """Normalize a player name for comparison."""
    name = name.translate(_CHAR_MAP)
    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9']+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def name_to_slug(name: str) -> str:
    """Convert a player name to a URL slug matching EA's format."""
    name = name.translate(_CHAR_MAP)
    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = normalized.replace("'", "").replace("'", "")
    normalized = re.sub(r"[^a-z0-9\s-]", "", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    return normalized.strip("-")


def map_ea_stats(ea_player: dict[str, Any]) -> dict[str, float]:
    """Map EA FC 26 player stats to simulation attribute names."""
    stats_raw = ea_player.get("stats", {})
    attributes: dict[str, float] = {}

    for ea_key, sim_key in EA_STAT_TO_SIM.items():
        if sim_key is None:
            continue
        value_obj = stats_raw.get(ea_key)
        if isinstance(value_obj, dict):
            value = value_obj.get("value")
        elif isinstance(value_obj, (int, float)):
            value = value_obj
        else:
            value = None
        if value is not None:
            existing = attributes.get(sim_key)
            if existing is None:
                attributes[sim_key] = float(value)
            else:
                attributes[sim_key] = max(existing, float(value))

    return attributes


def extract_next_data(html: str) -> dict | None:
    """Extract __NEXT_DATA__ JSON from a page's HTML."""
    match = NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def parse_player_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a player from a ratingDetails item (main listing page)."""
    if not item or not item.get("id"):
        return None
    stats_raw = item.get("stats", {})
    position = item.get("position") or {}
    nationality = item.get("nationality") or {}
    team = item.get("team") or {}
    return {
        "id": item["id"],
        "firstName": item.get("firstName", ""),
        "lastName": item.get("lastName", ""),
        "commonName": item.get("commonName"),
        "fullName": _full_name(item),
        "overallRating": item.get("overallRating"),
        "position": position.get("shortLabel", ""),
        "nationality": nationality.get("label", ""),
        "nationalityId": nationality.get("id"),
        "team": team.get("label", ""),
        "league": item.get("leagueName", ""),
        "pace": _get_stat(stats_raw, "pac"),
        "shooting": _get_stat(stats_raw, "sho"),
        "passing": _get_stat(stats_raw, "pas"),
        "dribbling": _get_stat(stats_raw, "dri"),
        "defending": _get_stat(stats_raw, "def"),
        "physical": _get_stat(stats_raw, "phy"),
    }


def _full_name(item: dict[str, Any]) -> str:
    if item.get("commonName"):
        return str(item["commonName"])
    first = item.get("firstName", "")
    last = item.get("lastName", "")
    return f"{first} {last}".strip()


def _get_stat(stats: dict[str, Any], key: str) -> int | None:
    val = stats.get(key)
    if isinstance(val, dict):
        return val.get("value")
    if isinstance(val, (int, float)):
        return int(val)
    return None


class Fc26Fetcher:
    """Fetches and caches EA SPORTS FC 26 player ratings."""

    BASE_URL = "https://www.ea.com/games/ea-sports-fc/ratings"
    PLAYER_PAGE_URL = "https://www.ea.com/games/ea-sports-fc/ratings/player-ratings/{slug}/{player_id}"

    def __init__(
        self,
        cache_dir: str | os.PathLike[str] | None = None,
        request_delay: float = 0.3,
        max_workers: int = 4,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else HERE
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.request_delay = request_delay
        self.max_workers = max_workers

        self.ratings_index_path = self.cache_dir / "data" / "fc26_player_index.json"
        self.ratings_cache_path = self.cache_dir / "data" / "fc26_ratings_cache.json"

        self.player_index: dict[str, dict[str, Any]] = {}
        self.ratings_cache: dict[int, dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._client: httpx.Client | None = None

        self._load_cache()

    # ── HTTP ────────────────────────────────────────────────────────

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=30,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                },
            )
        return self._client

    def _fetch(self, url: str) -> str | None:
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            err = str(e).encode("ascii", "replace").decode("ascii")
            tqdm.write(f"  [HTTP Error] {err}")
            return None

    def _save_ratings_cache(self) -> None:
        with self._cache_lock:
            with open(self.ratings_cache_path, "w", encoding="utf-8") as f:
                json.dump(dict(self.ratings_cache), f, indent=2, ensure_ascii=False)

    def _delay(self) -> None:
        if self.request_delay > 0:
            time.sleep(self.request_delay)

    # ── CACHE ───────────────────────────────────────────────────────

    def _load_cache(self) -> None:
        if self.ratings_index_path.exists():
            try:
                with open(self.ratings_index_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.player_index = {normalize_player_name(k): v for k, v in raw.items()}
            except Exception:
                self.player_index = {}

        if self.ratings_cache_path.exists():
            try:
                with open(self.ratings_cache_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.ratings_cache = {int(k): v for k, v in raw.items()}
            except Exception:
                self.ratings_cache = {}

    def _save_player_index(self) -> None:
        with open(self.ratings_index_path, "w", encoding="utf-8") as f:
            json.dump(self.player_index, f, indent=2, ensure_ascii=False)

    def _save_ratings_cache(self) -> None:
        with open(self.ratings_cache_path, "w", encoding="utf-8") as f:
            json.dump(self.ratings_cache, f, indent=2, ensure_ascii=False)

    # ── PLAYER INDEX BUILDER ────────────────────────────────────────

    def build_player_index(self, max_pages: int = 200) -> int:
        """Scrape the EA FC 26 main ratings listing to build a player name→ID index.

        Args:
            max_pages: Maximum number of pages to scrape (179 ≈ all 17,873 players).

        Returns:
            Number of players added to the index.
        """
        total_before = len(self.player_index)

        for page_num in range(1, max_pages + 1):
            url = f"{self.BASE_URL}?page={page_num}"
            tqdm.write(f"  Page {page_num}...")
            html = self._fetch(url)
            if not html:
                tqdm.write(f"  Stopping at page {page_num} (fetch failed)")
                break

            data = extract_next_data(html)
            if not data:
                tqdm.write(f"  Stopping at page {page_num} (no __NEXT_DATA__)")
                break

            page_props = data.get("props", {}).get("pageProps", {})
            rating_details = page_props.get("ratingDetails", {})
            items = rating_details.get("items", [])

            if not items:
                tqdm.write(f"  Stopping at page {page_num} (no items)")
                break

            added = 0
            for item in items:
                entry = parse_player_from_item(item)
                if not entry:
                    continue
                key = normalize_player_name(entry["fullName"])
                if key not in self.player_index:
                    self.player_index[key] = entry
                    added += 1

            tqdm.write(f"    Added {added} new players (total: {len(self.player_index)})")

            if len(items) < 100:
                tqdm.write(f"  Last page reached (only {len(items)} items)")
                break

            self._delay()

        self._save_player_index()
        return len(self.player_index) - total_before

    # ── PLAYER LOOKUP ───────────────────────────────────────────────

    def search_player(self, name: str, min_score: int = 85) -> list[tuple[dict[str, Any], int]]:
        """Search for a player by name in the index using fuzzy matching.

        Args:
            name: The player name to search for.
            min_score: Minimum fuzzy match score (0-100).

        Returns:
            List of (player_entry, score) tuples, sorted by score descending.
        """
        query = normalize_player_name(name)
        if not self.player_index:
            return []

        results: list[tuple[dict[str, Any], int]] = []
        for key, entry in self.player_index.items():
            score = fuzz.token_sort_ratio(query, key)
            if score >= min_score:
                results.append((entry, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def lookup_player(
        self, name: str, country: str | None = None, min_score: int = 85
    ) -> dict[str, Any] | None:
        """Look up a player's FC 26 ratings by name (and optionally country).

        Args:
            name: Player name.
            country: Country name to disambiguate.
            min_score: Minimum fuzzy match score.

        Returns:
            Player ratings dict or None if not found.
        """
        results = self.search_player(name, min_score)
        if not results:
            return None

        if country and len(results) > 1:
            country_norm = normalize_player_name(country)
            for entry, _ in results:
                entry_country = normalize_player_name(entry.get("nationality", ""))
                if entry_country == country_norm:
                    return self.fetch_full_ratings(entry["id"], entry.get("fullName", name))
            for entry, _ in results:
                entry_country = normalize_player_name(entry.get("nationality", ""))
                if country_norm in entry_country or entry_country in country_norm:
                    return self.fetch_full_ratings(entry["id"], entry.get("fullName", name))

        entry = results[0][0]
        return self.fetch_full_ratings(entry["id"], entry.get("fullName", name))

    # ── FULL RATINGS FETCH ──────────────────────────────────────────

    def fetch_full_ratings(self, player_id: int, display_name: str = "") -> dict[str, Any] | None:
        """Fetch full player ratings from the individual player page.

        Args:
            player_id: EA FC 26 player ID.
            display_name: Player name for slug construction (optional).

        Returns:
            Dict with keys: overall, attributes{sim_keys}, plus metadata.
        """
        with self._cache_lock:
            cached = self.ratings_cache.get(player_id)
            if cached is not None:
                return cached

        slug = name_to_slug(display_name) if display_name else str(player_id)
        url = self.PLAYER_PAGE_URL.format(slug=slug, player_id=player_id)

        html = self._fetch(url)
        if not html:
            return None

        data = extract_next_data(html)
        if not data:
            return None

        page_props = data.get("props", {}).get("pageProps", {})
        entries = page_props.get("ratingsEntries", {})
        items = entries.get("items", [])

        if not items:
            return None

        player = items[0]
        result = self._build_rating_result(player)
        if result["overall"] is not None:
            with self._cache_lock:
                self.ratings_cache[player_id] = result
        return result

    def _build_rating_result(self, player: dict[str, Any]) -> dict[str, Any]:
        """Build a ratings result dict from a player item."""
        attrs = map_ea_stats(player)
        full_name = _full_name(player)
        alt_positions = player.get("alternatePositions") or []
        position = player.get("position") or {}
        nationality = player.get("nationality") or {}
        team = player.get("team") or {}

        return {
            "id": player.get("id"),
            "fullName": full_name,
            "firstName": player.get("firstName", ""),
            "lastName": player.get("lastName", ""),
            "commonName": player.get("commonName"),
            "overall": player.get("overallRating"),
            "position": position.get("shortLabel", ""),
            "positionLabel": position.get("label", ""),
            "nationality": nationality.get("label", ""),
            "team": team.get("label", ""),
            "league": player.get("leagueName", ""),
            "skillMoves": player.get("skillMoves"),
            "weakFoot": player.get("weakFootAbility"),
            "height": player.get("height"),
            "weight": player.get("weight"),
            "alternatePositions": [ap.get("shortLabel", "") for ap in alt_positions],
            "attributes": attrs,
        }

    # ── BULK LOOKUP ─────────────────────────────────────────────────

    def bulk_lookup(
        self,
        players: list[tuple[str, str | None]],
        min_score: int = 85,
    ) -> dict[str, dict[str, Any] | None]:
        """Look up multiple players by (name, country) pairs.

        Args:
            players: List of (name, country) tuples.
            min_score: Minimum fuzzy match score.

        Returns:
            Dict mapping normalized names to results or None.
        """
        results: dict[str, dict[str, Any] | None] = {}

        for name, country in tqdm(players, desc="Looking up players"):
            result = self.lookup_player(name, country, min_score)
            key = normalize_player_name(name)
            results[key] = result

        return results

    def fetch_missing_ratings(self, max_workers: int | None = None) -> int:
        """Fetch full ratings for all players in the index that are not yet cached.

        Args:
            max_workers: Number of concurrent workers.

        Returns:
            Number of players fetched.
        """
        to_fetch = []
        for key, entry in self.player_index.items():
            pid = entry.get("id")
            if pid is None:
                continue
            if pid not in self.ratings_cache:
                full_name = entry.get("fullName", "")
                to_fetch.append((pid, full_name))

        if not to_fetch:
            return 0

        nw = max_workers or self.max_workers
        fetched = 0
        with ThreadPoolExecutor(max_workers=nw) as pool:
            fut_map = {
                pool.submit(self.fetch_full_ratings, pid, name): (pid, name)
                for pid, name in to_fetch
            }
            for future in tqdm(as_completed(fut_map), total=len(fut_map), desc="Fetching ratings"):
                pid, name = fut_map[future]
                try:
                    result = future.result()
                    if result:
                        fetched += 1
                except Exception as e:
                    tqdm.write(f"  Error fetching {name} (ID {pid}): {e}")

        return fetched

    # ── EXPORT ──────────────────────────────────────────────────────

    def export_ratings(self, output_path: str | os.PathLike[str] | None = None, only_cached: bool = True) -> dict[str, dict[str, Any]]:
        """Export cached ratings as a name-keyed dict.

        Args:
            output_path: Optional path to write the JSON file.
            only_cached: If True, only export players already in the cache (no new fetches).

        Returns:
            Dict mapping normalized player names to their ratings.
        """
        export: dict[str, dict[str, Any]] = {}
        for key, entry in self.player_index.items():
            pid = entry.get("id")
            if pid is None:
                continue
            with self._cache_lock:
                rating = self.ratings_cache.get(pid)
            if rating is None and not only_cached:
                rating = self.fetch_full_ratings(pid, entry.get("fullName", ""))
            if rating:
                export[key] = rating

        # Also include any cached ratings for players not in the index
        with self._cache_lock:
            for pid, rating in self.ratings_cache.items():
                norm_key = normalize_player_name(rating.get("fullName", ""))
                if norm_key and norm_key not in export:
                    export[norm_key] = rating

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(export, f, indent=2, ensure_ascii=False)

        return export

    def export_missing_report(
        self,
        wanted_names: list[str],
        output_path: str | os.PathLike[str] | None = None,
    ) -> dict[str, str]:
        """Generate a report of names not found in the FC 26 index.

        Args:
            wanted_names: List of player names to check.
            output_path: Optional path to write the JSON report.

        Returns:
            Dict mapping search names to reason (found/not_found).
        """
        report: dict[str, str] = {}
        for name in wanted_names:
            key = normalize_player_name(name)
            if key in self.player_index:
                report[name] = "found"
            else:
                matches = self.search_player(name, min_score=70)
                if matches:
                    best = matches[0]
                    report[name] = f"partial_match:{best[0].get('fullName','?')}(score={best[1]})"
                else:
                    report[name] = "not_found"

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

        return report
