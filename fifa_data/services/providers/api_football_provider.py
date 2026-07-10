from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import aiohttp

from ...models.player import Availability, Player
from ...models.squad_data import SquadData
from .base_provider import SquadProvider, validate_squad_data

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"
CACHE_DIR = Path(__file__).resolve().parents[3] / "fifa_data" / "data" / "provider_cache"
TEAM_CACHE = CACHE_DIR / "api_football_teams.json"
LINEUP_CACHE = CACHE_DIR / "api_football_lineups.json"

_HEADERS: dict[str, str] = {
    "x-rapidapi-key": "",
    "x-rapidapi-host": "v3.football.api-sports.io",
}


class ApiFootballProvider(SquadProvider):

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("RAPIDAPI_KEY", "")
        _HEADERS["x-rapidapi-key"] = self._api_key
        self._team_ids: dict[str, int] = {}
        self._session: aiohttp.ClientSession | None = None
        self._last_request: float = 0.0

    @property
    def name(self) -> str:
        return "API-Football"

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=_HEADERS)
        return self._session

    async def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < 1.1:
            await asyncio.sleep(1.1 - elapsed)
        self._last_request = time.time()

    async def _fetch_json(self, url: str) -> dict[str, Any] | None:
        await self._throttle()
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 429:
                    logger.warning("API-Football rate-limited")
                    return None
                if resp.status != 200:
                    logger.warning("API-Football %s returned %s", url, resp.status)
                    return None
                return await resp.json()
        except Exception as e:
            logger.warning("API-Football fetch error %s: %s", url, e)
            return None

    # ── Team ID resolution ───────────────────────────────────────

    async def _resolve_team_id(self, team: str) -> int | None:
        key = team.lower().strip()
        if key in self._team_ids:
            return self._team_ids[key]

        cache = self._load_cache(TEAM_CACHE)
        if key in cache:
            self._team_ids[key] = cache[key]
            return cache[key]

        team_id = await self._search_team(team)
        if team_id:
            self._team_ids[key] = team_id
            self._save_cache(TEAM_CACHE, key, team_id)
            return team_id
        return None

    async def _search_team(self, query: str) -> int | None:
        url = f"{BASE_URL}/teams?search={query}"
        data = await self._fetch_json(url)
        if not data:
            alt = query.replace("-", " ").replace("  ", " ")
            if alt != query:
                url = f"{BASE_URL}/teams?search={alt}"
                data = await self._fetch_json(url)
            if not data:
                return None

        try:
            response = data.get("response", [])
            if not response:
                return None
            return response[0].get("team", {}).get("id")
        except Exception as e:
            logger.warning("API-Football search parse error: %s", e)
            return None

    # ── Squad / Lineup ───────────────────────────────────────────

    async def get_starting_xi(
        self, team: str, fixture_id: str | None = None,
    ) -> SquadData | None:
        team_id = await self._resolve_team_id(team)
        if not team_id:
            logger.warning("API-Football: could not resolve team ID for %s", team)
            return None

        league = 1  # World Cup
        season = 2026

        if fixture_id and fixture_id.isdigit():
            data = await self._lineup_from_fixture(int(fixture_id))
            if data:
                return data

        lineup_data = await self._lineup_from_team_fixture(team, team_id, league, season)
        if lineup_data:
            return lineup_data

        squad_players = await self._fetch_squad(team, team_id)
        if not squad_players or len(squad_players) < 11:
            return None

        starters = self._infer_starting_xi(squad_players)
        bench = [p for p in squad_players if p not in starters]

        data = SquadData(
            team=team,
            formation="",
            starting_xi=starters[:11],
            bench=bench,
            squad=squad_players,
            provider="API-Football (inferred)",
        )
        vr = validate_squad_data(data)
        return data if vr.valid else None

    async def get_squad(self, team: str) -> list[Player] | None:
        team_id = await self._resolve_team_id(team)
        if not team_id:
            return None
        return await self._fetch_squad(team, team_id)

    async def _fetch_squad(self, team: str, team_id: int) -> list[Player] | None:
        url = f"{BASE_URL}/players/squads?team={team_id}"
        data = await self._fetch_json(url)
        if not data:
            return None
        try:
            response = data.get("response", [])
            if not response:
                return None
            players = response[0].get("players", [])
            result: list[Player] = []
            for p in players:
                player = self._player_from_api(p, team)
                if player:
                    result.append(player)
            return result if result else None
        except Exception as e:
            logger.warning("API-Football squad parse error: %s", e)
            return None

    async def _lineup_from_fixture(self, fixture_id: int) -> SquadData | None:
        url = f"{BASE_URL}/fixtures/lineups?fixture={fixture_id}"
        data = await self._fetch_json(url)
        if not data:
            return None
        return self._parse_lineups(data)

    async def _lineup_from_team_fixture(
        self, team: str, team_id: int, league: int, season: int,
    ) -> SquadData | None:
        url = f"{BASE_URL}/fixtures?team={team_id}&league={league}&season={season}&last=1"
        data = await self._fetch_json(url)
        if not data:
            return None
        try:
            response = data.get("response", [])
            if not response:
                return None
            fixture_id = response[0].get("fixture", {}).get("id")
            if fixture_id:
                return await self._lineup_from_fixture(fixture_id)
        except Exception as e:
            logger.warning("API-Football team fixture parse error: %s", e)
        return None

    def _parse_lineups(self, data: dict[str, Any]) -> SquadData | None:
        try:
            response = data.get("response", [])
            for lineup in response:
                team_name = (lineup.get("team", {}).get("name") or "").lower()
                formation = lineup.get("formation", "")
                start_xi = lineup.get("startXI", [])
                substitutes = lineup.get("substitutes", [])
                if not start_xi:
                    continue

                starters: list[Player] = []
                for item in start_xi:
                    pdata = item.get("player", {})
                    player = self._player_from_lineup(pdata, team_name)
                    if player:
                        starters.append(player)

                bench: list[Player] = []
                for item in substitutes:
                    pdata = item.get("player", {})
                    player = self._player_from_lineup(pdata, team_name)
                    if player:
                        bench.append(player)

                if len(starters) < 11:
                    continue

                data_obj = SquadData(
                    team=team_name.title(),
                    formation=formation,
                    starting_xi=starters[:11],
                    bench=bench,
                    squad=starters + bench,
                    provider="API-Football",
                )
                vr = validate_squad_data(data_obj)
                if vr.valid:
                    return data_obj
            return None
        except Exception as e:
            logger.warning("API-Football lineup parse error: %s", e)
            return None

    def _player_from_lineup(self, pdata: dict[str, Any], country: str) -> Player | None:
        name = (pdata.get("name") or "").strip()
        if not name:
            return None
        pos = pdata.get("position", "SUB")
        number = pdata.get("number")
        grid = pdata.get("grid", "")
        positions = self._api_positions(pos)
        return Player(
            name=name,
            country=country,
            positions=positions,
            roster_rating=float(number) if number else None,
            attributes={},
            availability=Availability(),
        )

    def _player_from_api(self, pdata: dict[str, Any], country: str) -> Player | None:
        name = (pdata.get("name") or "").strip()
        if not name:
            return None
        pos = pdata.get("position", "SUB")
        positions = self._api_positions(pos)
        return Player(
            name=name,
            country=country,
            positions=positions,
            roster_rating=None,
            attributes={},
            availability=Availability(),
        )

    @staticmethod
    def _api_positions(pos: str) -> tuple[str, ...]:
        mapping: dict[str, tuple[str, ...]] = {
            "G": ("GK",), "D": ("DEF",), "M": ("MID",), "F": ("FWD",),
            "GK": ("GK",), "DEF": ("DEF",), "MID": ("MID",), "FWD": ("FWD",),
            "GOALKEEPER": ("GK",), "DEFENDER": ("DEF",),
            "MIDFIELDER": ("MID",), "FORWARD": ("FWD",),
            "ATTACKER": ("FWD",),
        }
        return mapping.get(pos.upper().strip(), ("MID",))

    def _infer_starting_xi(self, players: list[Player]) -> list[Player]:
        gks = [p for p in players if "GK" in p.normalized_positions()]
        defs = [p for p in players if "DEF" in p.normalized_positions()]
        mids = [p for p in players if "MID" in p.normalized_positions()]
        fwds = [p for p in players if "FWD" in p.normalized_positions()]
        xi: list[Player] = []
        xi.extend(gks[:1])
        xi.extend(defs[:4])
        xi.extend(mids[:4])
        xi.extend(fwds[:3])
        if len(xi) < 11:
            remaining = [p for p in players if p not in xi]
            xi.extend(remaining[:11 - len(xi)])
        return xi[:11]

    # ── Cache ────────────────────────────────────────────────────

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
