from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.player import Player
from ..models.squad_data import SquadData
from .providers import (
    ApiFootballProvider,
    FootballDataOrgProvider,
    SofascoreProvider,
    SquadProvider,
    StaticLineupProvider,
    TheSportsDBProvider,
)
from .providers.base_provider import validate_squad_data

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "lineup_cache"


@dataclass
class ProviderResult:
    provider: str
    success: bool
    formation: str
    player_count: int
    bench_count: int
    validation: str
    elapsed: float


@dataclass
class LineupResult:
    team: str
    formation: str = ""
    starting_xi: list[Player] = field(default_factory=list)
    bench: list[Player] = field(default_factory=list)
    squad: list[Player] = field(default_factory=list)
    provider: str = "fallback"
    fixture_id: str | None = None
    provider_results: list[ProviderResult] = field(default_factory=list)


class LineupService:

    def __init__(self) -> None:
        self._providers: list[SquadProvider] = []
        self._init_providers()
        self._cache: dict[str, LineupResult] = {}
        self._team_id_cache: dict[str, Any] = {}
        self._load_disk_cache()

    def _init_providers(self) -> None:
        self._providers = [
            StaticLineupProvider(),
            SofascoreProvider(),
            FootballDataOrgProvider(),
            ApiFootballProvider(),
            TheSportsDBProvider(),
        ]

    @property
    def providers(self) -> list[SquadProvider]:
        return list(self._providers)

    @property
    def available_providers(self) -> list[SquadProvider]:
        return [p for p in self._providers if p.is_available()]

    # ── Main entry point ─────────────────────────────────────────

    async def get_starting_xi(
        self,
        team: str,
        fixture_id: str | None = None,
        force_refresh: bool = False,
    ) -> LineupResult:
        cache_key = self._cache_key(team, fixture_id)
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        result = LineupResult(team=team, fixture_id=fixture_id)
        available = self.available_providers

        if not available:
            logger.warning("No providers available; returning empty lineup")
            self._cache[cache_key] = result
            return result

        for provider in available:
            start = time.time()
            try:
                pname = provider.name
                data = await provider.get_starting_xi(team, fixture_id)
                elapsed = time.time() - start

                if data is None:
                    result.provider_results.append(ProviderResult(
                        provider=pname, success=False,
                        formation="", player_count=0, bench_count=0,
                        validation="No data returned", elapsed=round(elapsed, 3),
                    ))
                    continue

                vr = validate_squad_data(data)
                if vr.valid:
                    result.team = data.team
                    result.formation = data.formation
                    result.starting_xi = data.starting_xi
                    result.bench = data.bench
                    result.squad = data.squad
                    result.provider = pname
                    result.fixture_id = data.source_fixture_id or fixture_id
                    result.provider_results.append(ProviderResult(
                        provider=pname, success=True,
                        formation=data.formation,
                        player_count=len(data.starting_xi),
                        bench_count=len(data.bench),
                        validation="OK",
                        elapsed=round(elapsed, 3),
                    ))
                    self._cache[cache_key] = result
                    self._save_disk_cache_entry(cache_key, result)
                    return result
                else:
                    result.provider_results.append(ProviderResult(
                        provider=pname, success=False,
                        formation=data.formation,
                        player_count=len(data.starting_xi),
                        bench_count=len(data.bench),
                        validation=vr.reason,
                        elapsed=round(elapsed, 3),
                    ))
            except Exception as e:
                elapsed = time.time() - start
                result.provider_results.append(ProviderResult(
                    provider=provider.name, success=False,
                    formation="", player_count=0, bench_count=0,
                    validation=f"Error: {e}", elapsed=round(elapsed, 3),
                ))
                logger.warning("Provider %s error for %s: %s", provider.name, team, e)

        self._cache[cache_key] = result
        return result

    def get_cached(self, team: str, fixture_id: str | None = None) -> LineupResult | None:
        return self._cache.get(self._cache_key(team, fixture_id))

    def invalidate_cache(self, team: str | None = None, fixture_id: str | None = None) -> None:
        if team is None:
            self._cache.clear()
            return
        key = self._cache_key(team, fixture_id)
        self._cache.pop(key, None)

    def clear_all_caches(self) -> None:
        self._cache.clear()
        if CACHE_DIR.exists():
            import shutil
            shutil.rmtree(CACHE_DIR)

    # ── Provider comparison ──────────────────────────────────────

    async def compare_providers(
        self, team: str, fixture_id: str | None = None,
    ) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        for provider in self.available_providers:
            start = time.time()
            try:
                data = await provider.get_starting_xi(team, fixture_id)
                elapsed = time.time() - start
                if data:
                    vr = validate_squad_data(data)
                    results.append(ProviderResult(
                        provider=provider.name, success=vr.valid,
                        formation=data.formation,
                        player_count=len(data.starting_xi),
                        bench_count=len(data.bench),
                        validation=vr.reason,
                        elapsed=round(elapsed, 3),
                    ))
                else:
                    results.append(ProviderResult(
                        provider=provider.name, success=False,
                        formation="", player_count=0, bench_count=0,
                        validation="No data", elapsed=round(elapsed, 3),
                    ))
            except Exception as e:
                results.append(ProviderResult(
                    provider=provider.name, success=False,
                    formation="", player_count=0, bench_count=0,
                    validation=str(e), elapsed=0,
                ))
        return results

    # ── Integration with v2_data_loader ─────────────────────────

    async def enhance_squads(
        self,
        data_dir: str | os.PathLike[str] | None = None,
        team_names: list[str] | None = None,
        max_concurrent: int = 12,
    ) -> dict[str, Any]:
        """Load squads via v2_data_loader, then overlay provider lineups."""
        from .v2_data_loader import load_v2_squads

        base = load_v2_squads(data_dir=data_dir, team_names=team_names)
        if team_names is None:
            team_names = list(base.keys())

        overrides: dict[str, LineupResult] = {}
        import asyncio

        sem = asyncio.Semaphore(max_concurrent)

        async def _fetch(team: str) -> None:
            async with sem:
                result = await self.get_starting_xi(team)
                if result and result.provider != "fallback" and len(result.starting_xi) == 11:
                    overrides[team] = result

        await asyncio.gather(*[_fetch(t) for t in team_names])

        if not overrides:
            return base

        return load_v2_squads(
            data_dir=data_dir, team_names=team_names,
            lineup_overrides=overrides,
        )

    # ── Cache helpers ────────────────────────────────────────────

    def _cache_key(self, team: str, fixture_id: str | None) -> str:
        return f"{team.lower().strip()}|{fixture_id or ''}"

    def _disk_cache_path(self, key: str) -> Path:
        safe = key.replace(" ", "_").replace("|", "__")
        return CACHE_DIR / f"{safe}.json"

    def _save_disk_cache_entry(self, key: str, result: LineupResult) -> None:
        if not result.provider or result.provider == "fallback":
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._disk_cache_path(key)
            path.write_text(json.dumps({
                "team": result.team,
                "formation": result.formation,
                "provider": result.provider,
                "fixture_id": result.fixture_id,
                "starting_xi": [
                    {"name": p.name, "country": p.country, "positions": list(p.positions)}
                    for p in result.starting_xi
                ],
                "bench": [
                    {"name": p.name, "country": p.country, "positions": list(p.positions)}
                    for p in result.bench
                ],
            }, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _load_disk_cache(self) -> None:
        if not CACHE_DIR.exists():
            return
        for path in CACHE_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                team = data.get("team", "")
                provider = data.get("provider", "cache")
                formation = data.get("formation", "")
                xi = [Player(**{**p, "positions": tuple(p["positions"])}) for p in data.get("starting_xi", [])]
                bench = [Player(**{**p, "positions": tuple(p["positions"])}) for p in data.get("bench", [])]
                fixture_id = data.get("fixture_id")

                if xi:
                    key = self._cache_key(team, fixture_id)
                    self._cache[key] = LineupResult(
                        team=team, formation=formation,
                        starting_xi=xi, bench=bench,
                        squad=xi + bench, provider=provider,
                        fixture_id=fixture_id,
                    )
            except (OSError, json.JSONDecodeError, KeyError):
                pass

    async def close(self) -> None:
        for p in self._providers:
            try:
                await p.close()
            except Exception:
                pass
