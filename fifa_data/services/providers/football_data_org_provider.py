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

BASE_URL = "https://api.football-data.org/v4"
CACHE_DIR = Path(__file__).resolve().parents[3] / "fifa_data" / "data" / "provider_cache"
TEAM_CACHE = CACHE_DIR / "football_data_teams.json"
LINEUP_CACHE = CACHE_DIR / "football_data_lineups.json"

_HEADERS = {
    "X-Auth-Token": "",
    "User-Agent": "opencode-fifa-simulator/1.0",
}


class FootballDataOrgProvider(SquadProvider):

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("FOOTBALL_DATA_ORG_API_KEY", "")
        _HEADERS["X-Auth-Token"] = self._api_key
        self._team_ids: dict[str, int] = {}
        self._session: aiohttp.ClientSession | None = None
        self._last_request: float = 0.0

    @property
    def name(self) -> str:
        return "Football-Data.org"

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=_HEADERS)
        return self._session

    async def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < 6.5:
            await asyncio.sleep(6.5 - elapsed)
        self._last_request = time.time()

    async def _fetch_json(self, url: str) -> dict[str, Any] | None:
        await self._throttle()
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 429:
                    logger.warning("Football-Data.org rate-limited")
                    return None
                if resp.status == 403:
                    logger.warning("Football-Data.org forbidden (check API key)")
                    return None
                if resp.status != 200:
                    logger.warning("Football-Data.org %s returned %s", url, resp.status)
                    return None
                return await resp.json()
        except Exception as e:
            logger.warning("Football-Data.org fetch error %s: %s", url, e)
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
        url = f"{BASE_URL}/teams?limit=50"
        data = await self._fetch_json(url)
        if not data:
            return None

        teams = data.get("teams", [])
        ql = query.lower()
        for t in teams:
            name = (t.get("name") or "").lower()
            short = (t.get("shortName") or "").lower()
            tla = (t.get("tla") or "").lower()
            if ql in (name, short, tla):
                return t.get("id")

        for t in teams:
            name = (t.get("name") or "").lower()
            alt = (t.get("shortName") or "").lower()
            q_words = set(ql.split())
            name_words = set(name.split())
            if q_words & name_words:
                return t.get("id")
        return None

    # ── Squad / Lineup ───────────────────────────────────────────

    async def get_starting_xi(
        self, team: str, fixture_id: str | None = None,
    ) -> SquadData | None:
        team_id = await self._resolve_team_id(team)
        if not team_id:
            logger.warning("Football-Data.org: could not resolve team ID for %s", team)
            return None

        squad_players = await self._fetch_squad(team, team_id)
        if not squad_players:
            return None

        formation = ""
        if fixture_id and fixture_id.isdigit():
            lineup_data = await self._lineup_from_match(int(fixture_id))
            if lineup_data:
                starters, bench, formation = lineup_data
            else:
                starters = self._infer_starting_xi(squad_players)
                bench = [p for p in squad_players if p not in starters]
        else:
            latest = await self._latest_match(team_id)
            if latest:
                lineup_data = await self._lineup_from_match(latest)
                if lineup_data:
                    starters, bench, formation = lineup_data
                else:
                    starters = self._infer_starting_xi(squad_players)
                    bench = [p for p in squad_players if p not in starters]
            else:
                starters = self._infer_starting_xi(squad_players)
                bench = [p for p in squad_players if p not in starters]

        if len(starters) < 11:
            return None

        data = SquadData(
            team=team,
            formation=formation,
            starting_xi=starters[:11],
            bench=bench,
            squad=squad_players,
            provider="Football-Data.org",
            source_fixture_id=fixture_id,
        )
        vr = validate_squad_data(data)
        if not vr.valid:
            logger.warning("Football-Data.org lineup validation failed: %s", vr.reason)
            return None
        return data

    async def get_squad(self, team: str) -> list[Player] | None:
        team_id = await self._resolve_team_id(team)
        if not team_id:
            return None
        return await self._fetch_squad(team, team_id)

    async def _fetch_squad(self, team: str, team_id: int) -> list[Player] | None:
        url = f"{BASE_URL}/teams/{team_id}"
        data = await self._fetch_json(url)
        if not data:
            return None
        squad_raw = data.get("squad", [])
        if not squad_raw:
            return None
        result: list[Player] = []
        for p in squad_raw:
            player = self._player_from_fdo(p, team)
            if player:
                result.append(player)
        return result if result else None

    async def _latest_match(self, team_id: int) -> int | None:
        url = f"{BASE_URL}/teams/{team_id}/matches?limit=1&status=FINISHED"
        data = await self._fetch_json(url)
        if not data:
            return None
        matches = data.get("matches", [])
        if not matches:
            return None
        return matches[0].get("id")

    async def _lineup_from_match(self, match_id: int) -> tuple[list[Player], list[Player], str] | None:
        url = f"{BASE_URL}/matches/{match_id}"
        data = await self._fetch_json(url)
        if not data:
            return None
        try:
            match = data
            home = match.get("homeTeam", {})
            away = match.get("awayTeam", {})
            home_lineup = home.get("lineup", [])
            away_lineup = away.get("lineup", [])
            if not home_lineup and not away_lineup:
                return None
            formation = ""
            all_lineup = home_lineup or away_lineup
            if all_lineup:
                formation = (all_lineup[0].get("formation") or "")

            starters: list[Player] = []
            bench: list[Player] = []
            for item in all_lineup:
                pos = self._fdo_positions(item.get("position", "SUB"))
                player = Player(
                    name=(item.get("name") or "").strip(),
                    country="",
                    positions=pos,
                    roster_rating=None,
                    attributes={},
                    availability=Availability(),
                )
                if item.get("type") == "bench":
                    bench.append(player)
                else:
                    starters.append(player)

            return starters, bench, formation
        except Exception as e:
            logger.warning("Football-Data.org lineup parse error: %s", e)
            return None

    def _infer_starting_xi(self, players: list[Player]) -> list[Player]:
        gks = [p for p in players if "GK" in p.normalized_positions()]
        defs = [p for p in players if "DEF" in p.normalized_positions()]
        mids = [p for p in players if "MID" in p.normalized_positions()]
        fwds = [p for p in players if "FWD" in p.normalized_positions()]
        others = [p for p in players if not any(pos in ("GK", "DEF", "MID", "FWD") for pos in p.normalized_positions())]

        xi: list[Player] = []
        xi.extend(gks[:1])
        xi.extend(defs[:4])
        xi.extend(mids[:4])
        xi.extend(fwds[:3])

        if len(xi) < 11:
            remaining = [p for p in players if p not in xi]
            xi.extend(remaining[:11 - len(xi)])

        return xi[:11]

    def _player_from_fdo(self, data: dict[str, Any], country: str) -> Player | None:
        name = (data.get("name") or "").strip()
        if not name:
            return None
        positions = self._fdo_positions(data.get("position", "SUB"))
        return Player(
            name=name,
            country=country,
            positions=positions,
            roster_rating=None,
            attributes={},
            availability=Availability(),
        )

    @staticmethod
    def _fdo_positions(pos: str) -> tuple[str, ...]:
        mapping: dict[str, tuple[str, ...]] = {
            "GOALKEEPER": ("GK",),
            "DEFENDER": ("DEF",),
            "MIDFIELD": ("MID",),
            "MIDFIELDER": ("MID",),
            "ATTACKER": ("FWD",),
            "FORWARD": ("FWD",),
            "GK": ("GK",),
            "DEF": ("DEF",),
            "MID": ("MID",),
            "FWD": ("FWD",),
        }
        key = pos.upper().strip()
        if key in mapping:
            return mapping[key]
        return ("MID",)

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
