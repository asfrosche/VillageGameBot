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

BASE_URL = "https://www.thesportsdb.com/api/v1/json"
CACHE_DIR = Path(__file__).resolve().parents[3] / "fifa_data" / "data" / "provider_cache"
TEAM_CACHE = CACHE_DIR / "thesportsdb_teams.json"


class TheSportsDBProvider(SquadProvider):

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("THESPORTSDB_API_KEY", "3")
        self._team_ids: dict[str, int] = {}
        self._session: aiohttp.ClientSession | None = None
        self._last_request: float = 0.0

    @property
    def name(self) -> str:
        return "TheSportsDB"

    def is_available(self) -> bool:
        return True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < 1.5:
            await asyncio.sleep(1.5 - elapsed)
        self._last_request = time.time()

    async def _fetch_json(self, url: str) -> dict[str, Any] | None:
        await self._throttle()
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("TheSportsDB %s returned %s", url, resp.status)
                    return None
                return await resp.json()
        except Exception as e:
            logger.warning("TheSportsDB fetch error %s: %s", url, e)
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
        url = f"{BASE_URL}/{self._api_key}/searchteams.php?t={query}"
        data = await self._fetch_json(url)
        if not data:
            return None
        try:
            teams = data.get("teams", [])
            if not teams:
                return None
            return int(teams[0].get("idTeam", 0)) or None
        except Exception:
            return None

    # ── Squad / Lineup ───────────────────────────────────────────

    async def get_starting_xi(
        self, team: str, fixture_id: str | None = None,
    ) -> SquadData | None:
        team_id = await self._resolve_team_id(team)
        if not team_id:
            logger.warning("TheSportsDB: could not resolve team ID for %s", team)
            return None

        players = await self._fetch_players(team, team_id)
        if not players or len(players) < 11:
            return None

        starters = self._infer_starting_xi(players)
        bench = [p for p in players if p not in starters]

        formation = ""
        if fixture_id:
            events = await self._fetch_events(team_id)
            for ev in events or []:
                fid = ev.get("idEvent")
                if fid and str(fid) == fixture_id:
                    formation = ev.get("strFormation", "")
                    break

        data = SquadData(
            team=team,
            formation=formation,
            starting_xi=starters[:11],
            bench=bench,
            squad=players,
            provider="TheSportsDB",
            source_fixture_id=fixture_id,
        )
        vr = validate_squad_data(data)
        return data if vr.valid else None

    async def get_squad(self, team: str) -> list[Player] | None:
        team_id = await self._resolve_team_id(team)
        if not team_id:
            return None
        return await self._fetch_players(team, team_id)

    async def _fetch_players(self, team: str, team_id: int) -> list[Player] | None:
        url = f"{BASE_URL}/{self._api_key}/lookup_all_players.php?id={team_id}"
        data = await self._fetch_json(url)
        if not data:
            return None
        try:
            players_raw = data.get("player", [])
            if not players_raw:
                return None
            result: list[Player] = []
            for p in players_raw:
                name = (p.get("strPlayer") or "").strip()
                if not name:
                    continue
                pos = (p.get("strPosition") or "MID").strip()
                positions = self._tsdb_positions(pos)
                result.append(Player(
                    name=name,
                    country=team,
                    positions=positions,
                    roster_rating=None,
                    attributes={},
                    availability=Availability(),
                ))
            return result if result else None
        except Exception as e:
            logger.warning("TheSportsDB players parse error: %s", e)
            return None

    async def _fetch_events(self, team_id: int) -> list[dict[str, Any]]:
        url = f"{BASE_URL}/{self._api_key}/eventslast.php?id={team_id}"
        data = await self._fetch_json(url)
        if data:
            return data.get("results", [])
        return []

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

    @staticmethod
    def _tsdb_positions(pos: str) -> tuple[str, ...]:
        mapping: dict[str, tuple[str, ...]] = {
            "GOALKEEPER": ("GK",), "GK": ("GK",), "GOALIE": ("GK",),
            "DEFENDER": ("DEF",), "DEF": ("DEF",), "DEFENCE": ("DEF",),
            "MIDFIELDER": ("MID",), "MID": ("MID",), "MIDFIELD": ("MID",),
            "FORWARD": ("FWD",), "FWD": ("FWD",), "STRIKER": ("FWD",), "ATTACKER": ("FWD",),
        }
        return mapping.get(pos.upper().strip(), ("MID",))

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
