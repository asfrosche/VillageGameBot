from __future__ import annotations

import json
import logging
from pathlib import Path

from ...models.player import Availability, Player
from ...models.squad_data import SquadData
from .base_provider import SquadProvider, validate_squad_data

logger = logging.getLogger(__name__)

LINEUPS_PATH = Path(__file__).resolve().parents[3] / "fifa_data" / "data" / "known_lineups.json"

KNOWN_NAME_VARIANTS = {
    "United States": {"USA"},
    "USA": {"United States"},
    "Cape Verde": {"Cabo Verde"},
    "Cabo Verde": {"Cape Verde"},
    "Korea Republic": {"South Korea"},
    "South Korea": {"Korea Republic"},
    "Czechia": {"Czech Republic"},
    "Czech Republic": {"Czechia"},
    "Türkiye": {"Turkey"},
    "Turkey": {"Türkiye"},
    "IR Iran": {"Iran"},
    "Iran": {"IR Iran"},
    "Bosnia-Herzegovina": {"Bosnia and Herzegovina"},
    "Bosnia and Herzegovina": {"Bosnia-Herzegovina"},
}


def _resolve_team_name(team: str, known_teams: set[str]) -> str | None:
    lower = team.lower().strip()
    if team in known_teams:
        return team
    for known in known_teams:
        if known.lower() == lower:
            return known
    variants = KNOWN_NAME_VARIANTS.get(team, set())
    for v in variants:
        if v in known_teams:
            return v
    for known in known_teams:
        if known.lower() in lower or lower in known.lower():
            return known
    return None


def _make_name(first: str, last: str, seen: set[str]) -> str:
    """Build a unique player name to avoid validation duplicate errors."""
    name = last if last else first
    if name not in seen:
        seen.add(name)
        return name
    disambiguated = f"{first} {last}" if first else f"{name}_{len(seen)}"
    if disambiguated not in seen:
        seen.add(disambiguated)
        return disambiguated
    n = 1
    while True:
        candidate = f"{disambiguated} ({n})"
        if candidate not in seen:
            seen.add(candidate)
            return candidate


class StaticLineupProvider(SquadProvider):

    def __init__(self) -> None:
        self._data: dict = {}
        self._known_teams: set[str] = set()
        self._loaded = False

    @property
    def name(self) -> str:
        return "Static"

    def is_available(self) -> bool:
        self._ensure_loaded()
        return len(self._data) > 0

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if LINEUPS_PATH.exists():
                raw = json.loads(LINEUPS_PATH.read_text(encoding="utf-8"))
                self._data = raw
                self._known_teams = set(raw.keys())
                logger.info("StaticLineupProvider: loaded %d teams", len(self._data))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("StaticLineupProvider: failed to load %s: %s", LINEUPS_PATH, e)

    async def get_starting_xi(
        self, team: str, fixture_id: str | None = None,
    ) -> SquadData | None:
        self._ensure_loaded()
        resolved = _resolve_team_name(team, self._known_teams)
        if not resolved or resolved not in self._data:
            return None

        team_data = self._data[resolved]
        rounds_data = team_data.get("rounds", {})
        if not rounds_data:
            return None

        latest_round = max(rounds_data.keys(), key=lambda r: int(r) if r.isdigit() else 0)
        rd = rounds_data[latest_round]

        xi_raw = rd.get("starting_xi", [])
        subs_raw = rd.get("subs", [])

        if len(xi_raw) < 11:
            return None

        formation = rd.get("formation_hint", "4-4-2")

        seen_names: set[str] = set()
        starters = [
            Player(
                name=_make_name(p.get("firstName", ""), p["name"], seen_names),
                country=resolved,
                positions=(p["position"],),
                fantasy_id=p.get("fantasy_id"),
            )
            for p in xi_raw[:11]
        ]

        bench = [
            Player(
                name=_make_name(p.get("firstName", ""), p["name"], seen_names),
                country=resolved,
                positions=(p["position"],),
                fantasy_id=p.get("fantasy_id"),
            )
            for p in subs_raw
        ]

        squad_data = SquadData(
            team=resolved,
            formation=formation,
            starting_xi=starters,
            bench=bench,
            squad=starters + bench,
            provider="Static",
        )

        vr = validate_squad_data(squad_data)
        if not vr.valid:
            logger.warning("StaticLineup validation failed for %s: %s", resolved, vr.reason)
            return None

        return squad_data

    async def get_squad(self, team: str) -> list[Player] | None:
        data = await self.get_starting_xi(team)
        if data:
            return data.squad
        return None
