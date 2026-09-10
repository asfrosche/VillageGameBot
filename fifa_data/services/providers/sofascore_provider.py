from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import aiohttp

from ...models.player import Availability, Player
from ...models.squad_data import SquadData
from .base_provider import SquadProvider, validate_squad_data

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sofascore.com/api/v1"
CACHE_DIR = Path(__file__).resolve().parents[3] / "fifa_data" / "data" / "provider_cache"
TEAM_ID_CACHE = CACHE_DIR / "sofascore_team_ids.json"
LINEUP_CACHE = CACHE_DIR / "sofascore_lineups.json"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}


class SofascoreProvider(SquadProvider):

    def __init__(self) -> None:
        self._team_ids: dict[str, int] = {}
        self._session: aiohttp.ClientSession | None = None
        self._rate_limit: float = 0.0
        self._last_request: float = 0.0

    @property
    def name(self) -> str:
        return "Sofascore"

    def is_available(self) -> bool:
        return True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=_HEADERS)
        return self._session

    async def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request = time.time()

    async def _fetch_json(self, url: str) -> dict[str, Any] | None:
        await self._throttle()
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 429:
                    logger.warning("Sofascore rate-limited on %s", url)
                    self._rate_limit = max(self._rate_limit, 2.0)
                    return None
                if resp.status != 200:
                    logger.warning("Sofascore %s returned %s", url, resp.status)
                    return None
                self._rate_limit = max(0.3, self._rate_limit * 0.9)
                return await resp.json()
        except Exception as e:
            logger.warning("Sofascore fetch error %s: %s", url, e)
            return None

    # ── Team ID resolution ───────────────────────────────────────

    async def _resolve_team_id(self, team: str) -> int | None:
        key = team.lower().strip()
        if key in self._team_ids:
            return self._team_ids[key]

        ids = self._load_cache(TEAM_ID_CACHE)
        if key in ids:
            self._team_ids[key] = ids[key]
            return ids[key]

        team_id = await self._search_team(team)
        if team_id:
            self._team_ids[key] = team_id
            self._save_cache(TEAM_ID_CACHE, key, team_id)
            return team_id
        return None

    async def _search_team(self, query: str) -> int | None:
        url = f"{BASE_URL}/search/all?q={query}"
        data = await self._fetch_json(url)
        if not data:
            alt = query.replace("-", " ").replace("  ", " ")
            if alt != query:
                url = f"{BASE_URL}/search/all?q={alt}"
                data = await self._fetch_json(url)
            if not data:
                return None

        try:
            results = data.get("results", [])
            team_results = [r for r in results if r.get("type") == "team"]
            for entry in team_results:
                entity = entry.get("entity", {})
                name = ((entity.get("name") or "") + " " + (entity.get("shortName") or "")).lower()
                qw = query.lower()
                if qw in name:
                    return entity.get("id")
            if team_results:
                return team_results[0].get("entity", {}).get("id")
        except Exception as e:
            logger.warning("Sofascore search parse error: %s", e)
        return None

    # ── Squad / Lineup ───────────────────────────────────────────

    async def get_starting_xi(
        self, team: str, fixture_id: str | None = None,
    ) -> SquadData | None:
        team_id = await self._resolve_team_id(team)
        if not team_id:
            logger.warning("Sofascore: could not resolve team ID for %s", team)
            return None

        if fixture_id:
            data = await self._lineup_from_fixture(team, str(fixture_id))
            if data and validate_squad_data(data).valid:
                return data

        return await self._lineup_from_latest_match(team, team_id)

    async def get_squad(self, team: str) -> list[Player] | None:
        team_id = await self._resolve_team_id(team)
        if not team_id:
            return None
        return await self._fetch_squad(team, team_id)

    async def _fetch_squad(self, team: str, team_id: int) -> list[Player] | None:
        url = f"{BASE_URL}/team/{team_id}/players"
        data = await self._fetch_json(url)
        if not data:
            return None
        players = data.get("players", [])
        if not players:
            return None
        result: list[Player] = []
        for p in players:
            player = self._player_from_sofascore(p, team)
            if player:
                result.append(player)
        return result if result else None

    async def _lineup_from_fixture(
        self, team: str, fixture_id: str,
    ) -> SquadData | None:
        url = f"{BASE_URL}/event/{fixture_id}/lineups"
        data = await self._fetch_json(url)
        if not data:
            return None
        return self._parse_lineup_response(team, data, fixture_id)

    async def _lineup_from_latest_match(
        self, team: str, team_id: int,
    ) -> SquadData | None:
        url = f"{BASE_URL}/team/{team_id}/events/latest/0"
        data = await self._fetch_json(url)
        if not data:
            return None
        events = data.get("events", [])
        if not events:
            return None
        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue
            lineup = await self._lineup_from_fixture(team, str(event_id))
            if lineup and validate_squad_data(lineup).valid:
                return lineup
        return None

    def _parse_lineup_response(
        self, team: str, data: dict[str, Any], fixture_id: str,
    ) -> SquadData | None:
        try:
            lineups = data.get("lineups", [])
            if not lineups:
                return None

            team_lower = team.lower()
            side = None
            for lu in lineups:
                tname = (lu.get("teamName") or "").lower()
                if team_lower in tname or tname in team_lower:
                    side = lu
                    break
            if not side:
                side = lineups[0]

            formation = side.get("formation", "")
            confirmed_raw = side.get("confirmed", [])
            bench_raw = side.get("bench", [])

            if not confirmed_raw:
                return None

            starters: list[Player] = []
            for item in confirmed_raw:
                player = self._player_from_lineup_item(item, team)
                if player:
                    starters.append(player)

            bench_players: list[Player] = []
            for item in bench_raw:
                player = self._player_from_lineup_item(item, team)
                if player:
                    bench_players.append(player)

            if len(starters) < 11:
                return None

            squad_data = SquadData(
                team=team,
                formation=formation,
                starting_xi=starters[:11],
                bench=bench_players,
                squad=starters + bench_players,
                provider="Sofascore",
                source_fixture_id=fixture_id,
            )

            vr = validate_squad_data(squad_data)
            if not vr.valid:
                logger.warning("Sofascore lineup validation failed: %s", vr.reason)
                return None

            return squad_data
        except Exception as e:
            logger.warning("Sofascore parse error: %s", e)
            return None

    # ── Player construction ──────────────────────────────────────

    def _player_from_lineup_item(
        self, item: dict[str, Any], country: str,
    ) -> Player | None:
        name = (item.get("name") or "").strip()
        if not name:
            return None
        positions_raw = item.get("position", "SUB")
        positions = self._sofascore_positions(positions_raw)
        rating = item.get("rating")
        return Player(
            name=name,
            country=country,
            positions=positions,
            roster_rating=float(rating) if rating is not None else None,
            attributes={},
            availability=Availability(),
        )

    def _player_from_sofascore(
        self, data: dict[str, Any], country: str,
    ) -> Player | None:
        name = (data.get("name") or "").strip()
        if not name:
            return None
        positions_raw = data.get("position", "SUB")
        positions = self._sofascore_positions(positions_raw)
        return Player(
            name=name,
            country=country,
            positions=positions,
            roster_rating=None,
            attributes={},
            availability=Availability(),
        )

    @staticmethod
    def _sofascore_positions(pos: str) -> tuple[str, ...]:
        mapping: dict[str, tuple[str, ...]] = {
            "G": ("GK",),
            "D": ("DEF",),
            "M": ("MID",),
            "F": ("FWD",),
            "GK": ("GK",),
            "DEF": ("DEF",),
            "MID": ("MID",),
            "FWD": ("FWD",),
            "SUB": ("SUB",),
        }
        key = pos.upper().strip()[:3]
        if key in mapping:
            return mapping[key]
        return (key,)

    # ── Cache helpers ────────────────────────────────────────────

    def _load_cache(self, path: Path) -> dict[str, Any]:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _save_cache(self, path: Path, key: str, value: Any) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache = self._load_cache(path)
            cache[key] = value
            path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
