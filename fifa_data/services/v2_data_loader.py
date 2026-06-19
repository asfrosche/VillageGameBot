from __future__ import annotations

import ast
import dataclasses
import difflib
import json
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..models.player import Availability, Player
from ..models.squad import Squad
from ..models.team_strength import infer_formation

HERE = Path(__file__).resolve().parents[1]

# Lazy-loaded FC 26 ratings cache
_FC26_RATINGS: dict[str, dict[str, Any]] | None = None

SQUAD_TO_TEAM_NAME = {
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Cabo Verde": "Cape Verde",
    "USA": "United States",
}

TEAM_TO_SQUAD_NAME = {value: key for key, value in SQUAD_TO_TEAM_NAME.items()}

RAW_POSITION_TO_PLAYER_POSITION = {
    "GK": "GK",
    "DF": "DEF",
    "MF": "MID",
    "AT": "FWD",
}

TIER_PRIORITY = {
    "SUPERSTAR": 4,
    "STAR": 3,
    "STARTER": 2,
    "WISSEL": 1,
    "BASIS": 1,
    "RESERVE": 0,
}

# ── FC 26 Ratings Integration ──────────────────────────────────────


def _load_fc26_ratings() -> dict[str, dict[str, Any]]:
    """Lazily load FC 26 ratings from fc26_ratings.json.

    Keys are normalized via normalize_name() so lookup works regardless of
    diacritics, casing, or whitespace differences.
    """
    global _FC26_RATINGS
    if _FC26_RATINGS is not None:
        return _FC26_RATINGS
    path = HERE / "data" / "fc26_ratings.json"
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            _FC26_RATINGS = {normalize_name(k): v for k, v in raw.items()}
        except Exception:
            _FC26_RATINGS = {}
    else:
        _FC26_RATINGS = {}
    return _FC26_RATINGS


def _apply_fc26_ratings(player: Player) -> Player:
    """Upgrade a Player with FC 26 ratings if available. Returns the original player if no FC 26 data found."""
    ratings = _load_fc26_ratings()
    key = normalize_name(player.name)
    entry = ratings.get(key)
    if not entry:
        return player

    fc26_attrs = entry.get("attributes")
    fc26_overall = entry.get("overall")

    if not fc26_attrs and fc26_overall is None:
        return player

    if not fc26_attrs:
        return player

    new_attrs = {**player.attributes}
    if fc26_overall is not None:
        new_attrs["overall"] = float(fc26_overall)

    for sim_key, value in fc26_attrs.items():
        new_attrs[sim_key] = float(value)

    new_roster_rating = float(fc26_overall) if fc26_overall is not None else player.roster_rating

    return dataclasses.replace(
        player,
        attributes=new_attrs,
        roster_rating=new_roster_rating,
    )


def load_worldcup_data(worldcup_file: str | os.PathLike[str] | None = None) -> tuple[dict[str, dict[str, float]], dict[str, list[str]], dict[str, dict[str, list[tuple[Any, ...]]]]]:
    path = Path(worldcup_file) if worldcup_file else HERE / "worldcupsimulator.py"
    content = path.read_text(encoding="utf-8")
    data_block = content.split("RAW_ROSTERS")[0]
    data_block = data_block.replace("from numpy.random import poisson\n", "")
    namespace: dict[str, Any] = {}
    exec(data_block, namespace)
    raw_rosters = _load_raw_rosters(path)
    return namespace.get("TEAM_METRICS", {}), namespace.get("GROUPS", {}), raw_rosters


def load_v2_squads(
    data_dir: str | os.PathLike[str] | None = None,
    matches_file: str | os.PathLike[str] | None = None,
    team_names: list[str] | None = None,
) -> dict[str, Squad]:
    base_dir = Path(data_dir) if data_dir else HERE
    matches_path = Path(matches_file) if matches_file else base_dir / "data" / "matches.json"
    players_raw = _load_json(base_dir / "data" / "players.json")
    squads_raw = _load_json(base_dir / "data" / "squads.json")
    raw_rosters = _load_raw_rosters(base_dir / "worldcupsimulator.py")
    matches_data = _load_json(matches_path) if matches_path.exists() else {"completed": []}

    if team_names is None:
        team_metrics, _, _ = load_worldcup_data(base_dir / "worldcupsimulator.py")
        team_names = list(team_metrics.keys())

    squad_by_id = {squad["id"]: squad for squad in squads_raw}
    team_to_squad_id = _build_team_to_squad_id(squads_raw)
    fantasy_by_squad = _group_players_by_squad(players_raw)

    squads: dict[str, Squad] = {}
    for team in team_names:
        squad_id = team_to_squad_id.get(team)
        fantasy_players = fantasy_by_squad.get(squad_id, []) if squad_id is not None else []
        raw_records = raw_rosters.get(team, {})
        players = _build_players(team, fantasy_players, raw_records)
        players = [_apply_fc26_ratings(player) for player in players]
        lineup_names, formation = _lineup_from_completed_matches(team, matches_data)
        if not lineup_names:
            lineup_names, formation = _preferred_lineup_from_raw(team, raw_records, players)
        preferred_xi = _players_from_names(lineup_names, players)
        if len(preferred_xi) < 11:
            preferred_xi.extend(_fill_lineup(preferred_xi, players))
        preferred_xi = _dedupe_players(preferred_xi)[:11]
        if not formation:
            formation = infer_formation(preferred_xi) if len(preferred_xi) == 11 else "4-3-3"
        squads[team] = Squad(
            country=team,
            players=players,
            formation=formation,
            preferred_starting_xi=preferred_xi,
        )
    return squads


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_raw_rosters(path: Path) -> dict[str, dict[str, list[tuple[Any, ...]]]]:
    content = path.read_text(encoding="utf-8")
    start = content.index("RAW_ROSTERS = {")
    end = content.index("\n\n# STANDARD SQUAD PARSER ENGINE", start)
    raw_text = content[start + len("RAW_ROSTERS ="): end].strip()
    return ast.literal_eval(raw_text)


def _build_team_to_squad_id(squads_raw: list[dict[str, Any]]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for squad in squads_raw:
        squad_name = squad["name"]
        mapping[squad_name] = squad["id"]
        mapping[squad_name.lower()] = squad["id"]
        mapping[squad.get("abbr", "").lower()] = squad["id"]
        team_name = SQUAD_TO_TEAM_NAME.get(squad_name, squad_name)
        mapping[team_name] = squad["id"]
        mapping[team_name.lower()] = squad["id"]
    return mapping


def _group_players_by_squad(players_raw: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players_raw:
        grouped[int(player.get("squadId", 0))].append(player)
    return grouped


def _build_players(
    team: str,
    fantasy_players: list[dict[str, Any]],
    raw_records: dict[str, list[tuple[Any, ...]]],
) -> list[Player]:
    fantasy_index = _index_fantasy_players(fantasy_players)
    players_by_name: dict[str, Player] = {}

    for raw_position, records in raw_records.items():
        player_position = RAW_POSITION_TO_PLAYER_POSITION.get(raw_position, raw_position)
        for index, record in enumerate(records):
            name, tier, rating = _parse_raw_record(record)
            fantasy_player = _match_fantasy_player(name, fantasy_index)
            player = _player_from_fantasy(
                fantasy_player,
                country=team,
                position=player_position,
                roster_rating=rating,
                roster_tier=tier,
            )
            if player is None:
                player = Player(
                    name=name,
                    country=team,
                    positions=(player_position,),
                    attributes={},
                    roster_rating=rating,
                    roster_tier=tier,
                )
            players_by_name[normalize_name(player.name)] = player

    for fantasy_player in fantasy_players:
        name = _full_player_name(fantasy_player)
        key = normalize_name(name)
        if key in players_by_name:
            continue
        player = _player_from_fantasy(
            fantasy_player,
            country=team,
            position=fantasy_player.get("position", "MID"),
        )
        if player is not None:
            players_by_name[key] = player

    return sorted(players_by_name.values(), key=lambda player: (player.roster_tier or "", player.name))


def _index_fantasy_players(players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for player in players:
        names = [_full_player_name(player)]
        if player.get("knownName"):
            names.append(str(player["knownName"]))
        for name in names:
            index[normalize_name(name)] = player
    return index


def _match_fantasy_player(
    name: str,
    fantasy_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    key = normalize_name(name)
    if key in fantasy_index:
        return fantasy_index[key]
    matches = difflib.get_close_matches(key, fantasy_index.keys(), n=1, cutoff=0.88)
    return fantasy_index[matches[0]] if matches else None


def _player_from_fantasy(
    fantasy_player: dict[str, Any] | None,
    country: str,
    position: str,
    roster_rating: float | None = None,
    roster_tier: str | None = None,
) -> Player | None:
    if fantasy_player is None:
        return None
    name = _full_player_name(fantasy_player)
    fantasy_position = fantasy_player.get("position")
    positions = _merge_positions(position, fantasy_position)
    attributes = _extract_attributes(fantasy_player) or {}
    stats = fantasy_player.get("stats", {}) if isinstance(fantasy_player.get("stats", {}), dict) else {}
    return Player(
        name=name,
        country=country,
        positions=positions,
        attributes=attributes,
        fantasy_id=fantasy_player.get("id"),
        squad_id=fantasy_player.get("squadId"),
        roster_rating=roster_rating,
        roster_tier=roster_tier,
        price=float(fantasy_player.get("price", 0) or 0),
        status=fantasy_player.get("status"),
        stats=stats,
    )


def _extract_attributes(fantasy_player: dict[str, Any]) -> dict[str, float]:
    for key in ("attributes", "eaAttributes", "EAFCAttributes", "traits"):
        raw = fantasy_player.get(key)
        if isinstance(raw, dict):
            return {normalize_attribute_name(str(k)): float(v) for k, v in raw.items()}
    return {}


def _synthetic_attributes(
    position: str,
    roster_rating: float | None,
    fantasy_player: dict[str, Any] | None,
) -> dict[str, float]:
    base = float(roster_rating or 72)
    if fantasy_player:
        stats = fantasy_player.get("stats", {}) if isinstance(fantasy_player.get("stats", {}), dict) else {}
        base += min(float(stats.get("totalPoints", 0) or 0) / 8.0, 8.0)
        base += min(float(stats.get("form", 0) or 0), 4.0)
        base += min(float(fantasy_player.get("price", 0) or 0) * 1.5, 8.0)
    base = max(45.0, min(94.0, base))
    spread = 3.0
    normalized_position = RAW_POSITION_TO_PLAYER_POSITION.get(position.upper(), position.upper())
    if normalized_position == "GK":
        return {
            "reflexes": base + spread,
            "diving": base + 1,
            "positioning": base + 2,
            "handling": base,
            "kicking": base - 2,
        }
    if normalized_position == "DEF":
        return {
            "defensive_awareness": base + 3,
            "tackling": base + 2,
            "strength": base + 1,
            "pace": base - 1,
            "reactions": base,
            "interceptions": base + 2,
            "physical": base + 1,
            "crossing": base - 3,
            "passing": base - 2,
            "dribbling": base - 3,
            "stamina": base,
        }
    if normalized_position == "MID":
        return {
            "passing": base + 3,
            "vision": base + 2,
            "dribbling": base + 1,
            "stamina": base + 2,
            "defending": base - 1,
            "interceptions": base,
            "physical": base,
            "crossing": base - 2,
            "pace": base - 1,
            "finishing": base - 3,
            "composure": base,
            "shot_power": base - 2,
            "positioning": base - 2,
        }
    return {
        "finishing": base + 2,
        "positioning": base + 1,
        "shot_power": base + 1,
        "pace": base + 2,
        "composure": base,
        "dribbling": base + 1,
        "crossing": base - 1,
        "vision": base - 2,
    }


def _parse_raw_record(record: tuple[Any, ...] | Any) -> tuple[str, str, float]:
    if isinstance(record, tuple):
        name = str(record[0])
        tier = str(record[1]) if len(record) >= 2 else "BASIS"
        rating = float(record[2]) if len(record) >= 3 else 75.0
        return name, tier, rating
    return str(record), "BASIS", 75.0


def _full_player_name(player: dict[str, Any]) -> str:
    if player.get("knownName"):
        return str(player["knownName"])
    return f"{player.get('firstName', '')} {player.get('lastName', '')}".strip()


def _merge_positions(*positions: str | None) -> tuple[str, ...]:
    merged: list[str] = []
    for position in positions:
        if not position:
            continue
        normalized = str(position).upper()
        if normalized not in merged:
            merged.append(normalized)
    return tuple(merged) or ("MID",)


def _lineup_from_completed_matches(
    team: str,
    matches_data: dict[str, Any],
) -> tuple[list[str], str | None]:
    completed = matches_data.get("completed", [])
    team_matches = []
    for match in completed:
        home_name = str(match.get("home", {}).get("name", ""))
        away_name = str(match.get("away", {}).get("name", ""))
        if home_name.lower() == team.lower() or away_name.lower() == team.lower():
            team_matches.append(match)
    team_matches.sort(key=lambda item: item.get("date", ""))

    for match in reversed(team_matches):
        side = "home" if str(match.get("home", {}).get("name", "")).lower() == team.lower() else "away"
        lineup, formation = _extract_lineup(match.get(side, {}))
        if lineup:
            return lineup, formation
    return [], None


def _extract_lineup(side_data: dict[str, Any]) -> tuple[list[str], str | None]:
    formation = side_data.get("formation") or side_data.get("formations")
    formation = str(formation) if formation else None
    for key in (
        "lineup",
        "lineups",
        "starting_xi",
        "startingXI",
        "startingLineup",
        "starting_eleven",
    ):
        value = side_data.get(key)
        parsed = _parse_lineup_value(value)
        if parsed:
            return parsed, formation
    for key in ("players", "lineupPlayers"):
        value = side_data.get(key)
        if isinstance(value, list):
            parsed = []
            for item in value:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("playerName") or item.get("displayName")
                    if item.get("starter", True) or item.get("isStarter", True):
                        parsed.append(str(name))
                elif item:
                    parsed.append(str(item))
            if parsed:
                return parsed, formation
    return [], formation


def _parse_lineup_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        for key in ("players", "lineup", "starting_xi", "names"):
            if key in value:
                parsed = _parse_lineup_value(value[key])
                if parsed:
                    return parsed
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"[,;\n]", value) if part.strip()]
    return []


def _preferred_lineup_from_raw(
    team: str,
    raw_records: dict[str, list[tuple[Any, ...]]],
    players: list[Player],
) -> tuple[list[str], str]:
    if not raw_records:
        fallback = _fallback_lineup_from_players(players)
        return [player.name for player in fallback], "4-3-3"

    formation = _formation_from_raw_counts(raw_records)
    counts = _formation_counts(formation)
    selected: list[str] = []
    selected.extend(_select_from_raw_position(raw_records.get("GK", []), 1))
    selected.extend(_select_from_raw_position(raw_records.get("DF", []), counts["DF"]))
    selected.extend(_select_from_raw_position(raw_records.get("MF", []), counts["MF"]))
    selected.extend(_select_from_raw_position(raw_records.get("AT", []), counts["AT"]))
    return selected, formation


def _formation_from_raw_counts(raw_records: dict[str, list[tuple[Any, ...]]]) -> str:
    defense = len(raw_records.get("DF", []))
    midfield = len(raw_records.get("MF", []))
    attack = len(raw_records.get("AT", []))
    if defense >= 4 and attack >= 3 and midfield >= 3:
        return "4-3-3"
    if defense >= 4 and attack >= 2 and midfield >= 4:
        return "4-2-3-1"
    if defense >= 3 and attack >= 3:
        return "3-4-3"
    if defense >= 5 and attack >= 2:
        return "5-3-2"
    return "4-4-2"


def _formation_counts(formation: str) -> dict[str, int]:
    parts = [int(part) for part in formation.split("-") if part.isdigit()]
    if len(parts) == 4:
        return {"DF": parts[0], "DM": parts[1], "MF": parts[2], "AT": parts[3]}
    return {"DF": parts[0], "MF": parts[1], "AT": parts[2], "DM": 0}


def _select_from_raw_position(records: list[tuple[Any, ...]], count: int) -> list[str]:
    ranked = []
    for index, record in enumerate(records):
        name, tier, rating = _parse_raw_record(record)
        ranked.append((TIER_PRIORITY.get(tier, 0), rating, -index, name))
    ranked.sort(reverse=True)
    return [name for _, _, _, name in ranked[:count]]


def _players_from_names(names: list[str], players: list[Player]) -> list[Player]:
    by_name = {normalize_name(player.name): player for player in players}
    selected: list[Player] = []
    for name in names:
        key = normalize_name(name)
        if key in by_name:
            selected.append(by_name[key])
    return selected


def _fill_lineup(current: list[Player], players: list[Player]) -> list[Player]:
    used = {normalize_name(player.name) for player in current}
    return [
        player
        for player in players
        if normalize_name(player.name) not in used
    ][: 11 - len(current)]


def _fallback_lineup_from_players(players: list[Player]) -> list[Player]:
    selected: list[Player] = []
    for position_group in ("GK", "DEF", "MID", "FWD"):
        group = [
            player
            for player in players
            if any(position_group in normalized for normalized in player.normalized_positions())
        ]
        group.sort(key=lambda player: (player.roster_rating or 0, player.price), reverse=True)
        selected.extend(group)
    return _dedupe_players(selected)[:11]


def _dedupe_players(players: list[Player]) -> list[Player]:
    seen: set[str] = set()
    deduped: list[Player] = []
    for player in players:
        key = normalize_name(player.name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(player)
    return deduped


def normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_attribute_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")
