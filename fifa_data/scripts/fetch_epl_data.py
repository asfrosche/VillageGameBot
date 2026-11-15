"""Fetch live 2025-26 Premier League data into ``fifa_data/data/``.

Sources (all optional except the FPL API):
  * FPL API (free, no key): bootstrap-static + fixtures
  * Premier League API (free, no key): real per-match starting XIs (--lineups)
  * football-data.org v4 (key in FOOTBALL_DATA_API_KEY): real PL fixtures/results
  * ClubElo api.clubelo.com: season-start elo per club
  * The Odds API (key in ODDS_API_KEY): h2h/totals market odds
  * Understat xG (optional, --include-xg): team xG/xGA correction data

Every source failure is non-fatal; existing files are kept as fallback.

Usage:
    python -m fifa_data.scripts.fetch_epl_data --season 2025
    python -m fifa_data.scripts.fetch_epl_data --lineups --odds
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "data"


def log(message: str) -> None:
    print(f"[fetch_epl_data] {message}")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, AttributeError):
        return {}


def _get(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> Any:
    import urllib.request

    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _canonical(name: str) -> str:
    from ..competitions.premier_league import canonical_team_name

    return canonical_team_name(name)


FPL_POSITION_MAP = {"1": "GK", "2": "DF", "3": "MF", "4": "AT"}
FPL_TEAM_ALIASES = {
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Brighton & Hove Albion": "Brighton & Hove Albion",
    "Brighton": "Brighton & Hove Albion",
    "Tottenham": "Tottenham Hotspur",
    "Nott'm Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    "Man United": "Manchester United",
    "Man Utd": "Manchester United",
    "Man City": "Manchester City",
    "Newcastle": "Newcastle United",
    "West Ham": "West Ham United",
    "Wolverhampton": "Wolverhampton Wanderers",
    "Wolves": "Wolverhampton Wanderers",
    "Leeds": "Leeds United",
}
CLUBELO_TEAM_ALIASES = {
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Newcastle Utd": "Newcastle United",
    "Tottenham": "Tottenham Hotspur",
    "Wolves": "Wolverhampton Wanderers",
    "Nott'm Forest": "Nottingham Forest",
    "West Ham": "West Ham United",
    "Brighton": "Brighton & Hove Albion",
    "Leeds": "Leeds United",
}


def _map_fpl_team(name: str) -> str:
    mapped = FPL_TEAM_ALIASES.get(name, _canonical(name))
    return FPL_TEAM_ALIASES.get(mapped, mapped)


def _tier_from_rating(rating: float) -> str:
    if rating >= 85:
        return "SUPERSTAR"
    if rating >= 82:
        return "STAR"
    if rating >= 79:
        return "STARTER"
    if rating >= 74:
        return "WISSEL"
    return "RESERVE"


# ── FPL ───────────────────────────────────────────────────────────


def fetch_fpl() -> tuple[dict[str, Any], list[Any]]:
    bootstrap = _get("https://fantasy.premierleague.com/api/bootstrap-static/")
    fixtures = _get("https://fantasy.premierleague.com/api/fixtures/")
    return bootstrap, fixtures


def build_teams_file(bootstrap: dict[str, Any]) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    teams_file = DATA / "epl_teams.json"
    if teams_file.exists():
        try:
            existing = json.loads(teams_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    seen: dict[str, int] = {}
    for team in bootstrap.get("teams", []):
        name = _map_fpl_team(str(team.get("name", "")))
        seen[name] = int(team.get("id", 0))
    output: dict[str, Any] = {}
    for canonical in sorted(seen):
        previous = existing.get(canonical, {})
        output[canonical] = {
            "name": canonical,
            "code": previous.get("code") or canonical[:3].upper(),
            "elo": previous.get("elo"),
            "fpl_id": seen.get(canonical, previous.get("fpl_id")),
        }
    from ..competitions.premier_league import _RESERVED_META_KEY, _competition_stamp

    payload = {**output, _RESERVED_META_KEY: {**_competition_stamp(), "_reserved": True}}
    DATA.joinpath("epl_teams.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote epl_teams.json ({len(output)} clubs, fpl ids for {len(seen)})")
    return output


def build_matches_file(fixtures: list[Any], season: int) -> dict[str, Any]:
    completed: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    for match in fixtures:
        home_id = match.get("team_h")
        away_id = match.get("team_a")
        fpl_teams = DATA / "epl_teams.json"
        name_by_id: dict[int, str] = {}
        if fpl_teams.exists():
            try:
                for info in json.loads(fpl_teams.read_text(encoding="utf-8")).values():
                    if info.get("fpl_id") is not None:
                        name_by_id[int(info["fpl_id"])] = info["name"]
            except (json.JSONDecodeError, OSError, ValueError):
                name_by_id = {}
        home_name = name_by_id.get(home_id, f"TBD{home_id}")
        away_name = name_by_id.get(away_id, f"TBD{away_id}")
        finished = bool(match.get("finished"))
        home_score = match.get("team_h_score")
        away_score = match.get("team_a_score")
        matchday = match.get("event")
        record = {
            "id": f"pl_{match.get('code') or match.get('id')}",
            "date": match.get("kickoff_time") or "",
            "stage": "Regular Season",
            "group": None,
            "matchday": matchday,
            "home": {"name": home_name, "score": home_score if finished else None, "id": home_id, "players": []},
            "away": {"name": away_name, "score": away_score if finished else None, "id": away_id, "players": []},
            "winner": None,
            "status": 0 if finished else 1,
        }
        if finished and home_score is not None and away_score is not None:
            record["winner"] = home_name if home_score > away_score else (away_name if away_score > home_score else None)
            completed.append(record)
        else:
            upcoming.append(record)

    completed.sort(key=lambda item: item.get("date", ""))
    upcoming.sort(key=lambda item: item.get("matchday") is None or item.get("matchday", 0))
    season_label = f"{season}/{str(season + 1).zfill(2)}"
    from ..competitions.premier_league import EPL_COMPETITION_FORMAT

    matches = {
        "competition": f"Premier League {season_label}",
        "season": season_label,
        "competition_format": EPL_COMPETITION_FORMAT,
        "last_updated": "",
        "completed_count": len(completed),
        "upcoming_count": len(upcoming),
        "completed": completed,
        "upcoming": upcoming,
    }
    DATA.joinpath("pl_matches.json").write_text(json.dumps(matches, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote pl_matches.json: {len(completed)} completed / {len(upcoming)} upcoming")
    return matches


def _fpl_position_name(position_id: int) -> str:
    """Map the FPL element_type ids to player-position codes."""
    return {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(int(position_id), "MID")


def _fpl_full_name(element: dict[str, Any]) -> str:
    """The full display name (first + second) for an FPL element."""
    first = str(element.get("first_name") or "").strip()
    second = str(element.get("second_name") or "").strip()
    return f"{first} {second}".strip() or str(element.get("web_name") or "")


def _team_name_by_id() -> dict[int, str]:
    """Map FPL team ids to canonical Premier League club names."""
    fpl_teams = DATA / "epl_teams.json"
    name_by_id: dict[int, str] = {}
    if not fpl_teams.exists():
        return name_by_id
    try:
        for info in json.loads(fpl_teams.read_text(encoding="utf-8")).values():
            if info.get("fpl_id") is not None:
                name_by_id[int(info["fpl_id"])] = info["name"]
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        pass
    return name_by_id


def _fc26_by_name(fc26: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Index Premier League fc26 entries by canonical team, then by name.

    Scoped by team so a surname shared by two clubs' players (e.g. "Palmer")
    does not mis-attribute one club's rating to the other's player.
    """
    from ..services.v2_data_loader import normalize_name

    def norm_key(value: str) -> str:
        return normalize_name(str(value or ""))

    index: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in fc26.values():
        if str(entry.get("league") or "") != "Premier League":
            continue
        team = _map_fpl_team(str(entry.get("team") or ""))
        if not team:
            continue
        for candidate in (
            entry.get("fullName"),
            entry.get("name"),
            entry.get("commonName"),
            entry.get("player_name"),
        ):
            key = norm_key(candidate)
            if key:
                index.setdefault(team, {})[key] = entry
    return index


def _fc26_for_element(
    element: dict[str, Any],
    team: str,
    fc26_teams: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    """The fc26 entry for an FPL element, if any, scoped to its club."""
    from ..services.v2_data_loader import normalize_name

    team_index = fc26_teams.get(team)
    if not team_index:
        return None
    for candidate in (_fpl_full_name(element), str(element.get("web_name") or "")):
        entry = team_index.get(normalize_name(candidate))
        if entry:
            return entry
    return None


def build_squads_file(bootstrap: dict[str, Any]) -> None:
    """Write pl_squads.json (id + name + abbr per Premier League club).

    The id used here is the FPL team id, and pl_players.json refers to clubs
    through that same id, so the two files line up for the v2 loader.
    """
    from ..competitions.premier_league import _is_metadata_key

    squads = []
    for team in bootstrap.get("teams", []):
        name = _map_fpl_team(str(team.get("name", "")))
        if not name:
            continue
        squads.append(
            {
                "id": int(team.get("id", 0)),
                "name": name,
                "abbr": str(team.get("short_name", "")).upper() or name[:3].upper(),
            }
        )
    squads.sort(key=lambda squad: squad["name"])
    DATA.joinpath("pl_squads.json").write_text(json.dumps(squads, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote pl_squads.json ({len(squads)} squads, none reserved metadata)")


def build_players_file(bootstrap: dict[str, Any], fc26: dict[str, Any] | None = None) -> None:
    """Write pl_players.json in the v2 loader's fantasy-player format.

    Includes real FPL positions (element_type), prices, statuses and per-match
    stats for every element, plus the fc26 fine-grained attributes where they
    match (matched by full or common name so surnames alias across sources).
    """
    fc26 = fc26 if fc26 is not None else _load_json(DATA / "fc26_ratings.json")
    fc26_index = _fc26_by_name(fc26)
    team_by_id = _team_name_by_id()

    players = []
    for element in bootstrap.get("elements", []):
        first = str(element.get("first_name") or "").strip()
        second = str(element.get("second_name") or "").strip()
        full_name = _fpl_full_name(element)
        position = _fpl_position_name(int(element.get("element_type", 0)))
        cost_value = _to_float(element.get("now_cost"), 50.0) / 10.0

        stats: dict[str, Any] = {}
        for stat in (
            "minutes", "goals_scored", "assists", "clean_sheets", "saves",
            "bonus", "bps", "form", "points_per_game", "total_points",
            "selected_by_percent", "expected_goals", "expected_assists",
            "expected_goal_involvements",
        ):
            if element.get(stat) is not None:
                stats[stat] = element[stat]

        matched = None
        team_name = team_by_id.get(int(element.get("team", 0)))
        if fc26_index and team_name:
            matched = _fc26_for_element(element, team_name, fc26_index)

        attributes = {}
        if matched:
            raw_attrs = matched.get("attributes")
            if isinstance(raw_attrs, dict):
                attributes = dict(raw_attrs)

        players.append(
            {
                "id": int(element.get("id", 0)),
                "squadId": int(element.get("team", 0)),
                "firstName": first,
                "lastName": second,
                "shortName": str(element.get("web_name") or ""),
                "position": position,
                "price": cost_value,
                "status": element.get("status"),
                "stats": stats,
                "attributes": attributes,
            }
        )

    DATA.joinpath("pl_players.json").write_text(json.dumps(players, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote pl_players.json ({len(players)} players across {len(bootstrap.get('teams', []))} clubs)")


def _load_fc26() -> dict[str, Any]:
    data = _load_json(DATA / "fc26_ratings.json")
    return data if isinstance(data, dict) else {}


def build_rosters_file(bootstrap: dict[str, Any]) -> None:
    """Write pl_rosters.json from the FPL bootstrap.

    Players are grouped into the coarse GK/DF/MF/AT buckets the v2 loader
    expects, but named with their full names (not FPL short names) so the
    fc26 ratings and fine-grained attributes attach reliably. Where an fc26
    rating exists it wins; otherwise a price-plus-form rating is used.
    """
    name_by_id = _team_name_by_id()

    fc26 = _load_fc26()
    fc26_index = _fc26_by_name(fc26)

    element_type_name = {1: "GK", 2: "DF", 3: "MF", 4: "AT"}
    rosters: dict[str, dict[str, list[Any]]] = {}
    for element in bootstrap.get("elements", []):
        team_id = int(element.get("team", 0))
        team = name_by_id.get(team_id)
        if not team:
            continue
        position = element_type_name.get(int(element.get("element_type", 0)))
        if not position:
            continue
        name = _fpl_full_name(element)
        if not name:
            continue
        rating = _rating_for(element, team, fc26_index)
        record = (name, _tier_from_rating(rating), rating)
        rosters.setdefault(team, {}).setdefault(position, []).append(record)

    for group in rosters.values():
        for position in group:
            group[position] = sorted(group[position], key=lambda record: (-record[2], str(record[0])))

    from ..competitions.premier_league import _RESERVED_META_KEY, _competition_stamp

    payload = {**rosters, _RESERVED_META_KEY: {**_competition_stamp(), "_reserved": True}}
    DATA.joinpath("pl_rosters.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote pl_rosters.json for {len(rosters)} clubs ({sum(len(g['GK']) + len(g['DF']) + len(g['MF']) + len(g['AT']) for g in rosters.values())} players)")


def _rating_for(
    element: dict[str, Any],
    team: str,
    fc26_index: dict[str, dict[str, dict[str, Any]]],
) -> float:
    """Best rating for one FPL element: fc26 overall, else price + form.

    The fc26 rating is the real one and wins. For the rest, the rating is
    derived from FPL price with a modest points-per-game boost, clamped to the
    engine's usable band.
    """
    matched = _fc26_for_element(element, team, fc26_index)
    if matched and matched.get("overall") is not None:
        return float(matched["overall"])

    cost_value = _to_float(element.get("now_cost"), 50.0) / 10.0
    points_per_game = _to_float(element.get("points_per_game"), 0.0)
    rating = 46.0 + cost_value * 2.4 + points_per_game * 1.2
    return max(56.0, min(90.0, rating))


def _name_key(name: str) -> str:
    """Fold a player name to comparable words (accents/punctuation dropped).

    Word boundaries are preserved, because matching relies on the surname.
    """
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_only = decomposed.encode("ascii", "ignore").decode().lower()
    spaced = "".join(char if char.isalpha() else " " for char in ascii_only)
    return " ".join(spaced.split())


def _is_same_player(existing_name: str, candidate_name: str) -> bool:
    """True when two roster entries are the same human.

    The two sources disagree on naming: FPL gives surnames only ("Raya",
    "Haaland", "Son") while FC26 gives full names ("David Raya", "Erling
    Haaland", "Heung-min Son"). Treating those as different people lists the
    same player twice and lets a synthetic reserve rating masquerade as a real
    squad option.

    Matched on the surname (final token) so it works in both name orders, and
    only when that surname is long enough to be distinctive.
    """
    existing = _name_key(existing_name).split()
    candidate = _name_key(candidate_name).split()
    if not existing or not candidate:
        return False
    if "".join(existing) == "".join(candidate):
        return True
    if len(existing) > 1 and len(candidate) > 1 and sorted(existing) == sorted(candidate):
        # Reversed name order ("Ao Tanaka" vs "Tanaka Ao") is the same player.
        return True
    existing_surname = existing[-1]
    candidate_surname = candidate[-1]
    if existing_surname == candidate_surname and (
        len(existing_surname) >= 4 or len(existing) == 1 or len(candidate) == 1
    ):
        return True
    # Compound surnames: "David Raya Martín" vs "David Raya" (FPL) share the
    # non-first token "raya"; but "Gabriel" vs "Gabriel Martinelli" do not, so
    # a mere shared first name never merges two different players.
    shorter, longer = sorted((existing, candidate), key=len)
    shared_surname_tokens = set(shorter[1:]) & set(longer)
    return any(len(token) >= 3 for token in shared_surname_tokens)


def _pick_better_player(current: list, candidate: list) -> list:
    """Choose which of two same-player records to keep.

    Prefers the higher rating (a real fc26 figure beats a synthetic
    price-form one), then the more complete name as a tie-break.
    """
    current_rating, candidate_rating = float(current[2]), float(candidate[2])
    if candidate_rating > current_rating:
        return candidate
    if candidate_rating < current_rating:
        return current
    current_name, candidate_name = str(current[0]), str(candidate[0])
    if len(candidate_name) > len(current_name):
        return candidate
    return current


def _dedupe_position_bucket(records: list) -> list:
    """Collapse entries in one club/position that are the same real player.

    The FPL and fc26 sources name the same players differently, so a merged
    roster can otherwise list someone twice ("David Raya" and "Raya"), with the
    weaker synthetic entry able to win a selection it should not.
    """
    kept: list[list] = []
    for record in records:
        for index, existing in enumerate(kept):
            if _is_same_player(existing[0], record[0]):
                kept[index] = _pick_better_player(existing, record)
                break
        else:
            kept.append(record)
    return kept


def fill_rosters_from_fc26() -> None:
    """Merge any missing fc26-only clubs/players into pl_rosters.json."""
    from ..competitions.premier_league import _is_metadata_key, build_pl_rosters_from_fc26

    path = DATA / "pl_rosters.json"
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    fc26_rosters = build_pl_rosters_from_fc26(DATA.parent if DATA.name == "data" else None)
    merged = dict(existing)
    for team, groups in fc26_rosters.items():
        if team not in merged:
            continue
        target = merged.setdefault(team, {k: [] for k in ("GK", "DF", "MF", "AT")})
        for position, records in groups.items():
            bucket = target.setdefault(position, [])
            for record in records:
                match = next(
                    (i for i, kept in enumerate(bucket) if _is_same_player(kept[0], record[0])),
                    None,
                )
                if match is None:
                    bucket.append(record)
                else:
                    bucket[match] = _pick_better_player(bucket[match], record)
    duplicates_removed = 0
    for team, groups in merged.items():
        if _is_metadata_key(team):
            continue
        for position, records in list(groups.items()):
            before = len(records)
            deduped = _dedupe_position_bucket(records)
            duplicates_removed += before - len(deduped)
            merged[team][position] = sorted(
                deduped, key=lambda record: (-float(record[2]), str(record[0]))
            )
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    log(
        f"merged fc26 fallbacks into pl_rosters.json "
        f"({sum(1 for team in merged if not _is_metadata_key(team))} clubs, "
        f"{duplicates_removed} alias duplicates collapsed)"
    )


# ── Optional sources ──────────────────────────────────────────────


def fetch_club_elo() -> dict[str, Any]:
    from ..competitions.premier_league import EPL_ELO

    elo_map: dict[str, Any] = {}
    names = {
        "Arsenal": "Arsenal", "Aston Villa": "AstonVilla", "Bournemouth": "Bournemouth",
        "Brentford": "Brentford", "Brighton & Hove Albion": "Brighton", "Chelsea": "Chelsea",
        "Coventry City": "Coventry", "Crystal Palace": "CrystalPalace", "Everton": "Everton",
        "Fulham": "Fulham", "Hull City": "HullCity", "Ipswich Town": "Ipswich",
        "Leeds United": "Leeds", "Liverpool": "Liverpool", "Manchester City": "ManCity",
        "Manchester United": "ManUnited", "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'mForest",
        "Sunderland": "Sunderland", "Tottenham Hotspur": "Tottenham",
    }
    for team, clubelo_name in names.items():
        try:
            data = _get(f"https://api.clubelo.com/{clubelo_name}", timeout=6)
            if isinstance(data, dict) and data.get("Elo") is not None:
                elo_map[team] = {"elo": float(data["Elo"]), "source": "clubelo"}
        except Exception:
            continue
    if elo_map:
        DATA.joinpath("club_elo.json").write_text(json.dumps(elo_map, indent=2), encoding="utf-8")
        teams_file = DATA / "epl_teams.json"
        if teams_file.exists():
            try:
                teams = json.loads(teams_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                teams = {}
            changed = False
            for team, info in elo_map.items():
                if team in teams:
                    teams[team]["elo"] = info["elo"]
                    changed = True
            if changed:
                teams_file.write_text(json.dumps(teams, indent=2), encoding="utf-8")
        log(f"wrote club_elo.json ({len(elo_map)} clubs)")
    else:
        log("club elo unavailable; keeping existing/default ratings")
    return elo_map


def fetch_odds() -> None:
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        log("ODDS_API_KEY not set — writing built-in market odds")
        _write_builtin_odds()
        return
    try:
        data = _get(
            "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
            {"apikey": api_key, "regions": "uk", "markets": "h2h,totals", "oddsFormat": "decimal"},
        )
    except Exception as exc:
        log(f"odds fetch failed ({exc}); using built-in odds")
        _write_builtin_odds()
        return
    matches: list[dict[str, Any]] = []
    for event in data:
        home = _map_fpl_team(str(event.get("home_team", "")))
        away = _map_fpl_team(str(event.get("away_team", "")))
        h2h = next((m for m in event.get("bookmakers", []) for m in m.get("markets", []) if m.get("key") == "h2h"), None)
        if not h2h:
            continue
        outcomes = {str(outcome.get("name", "")): outcome.get("price") for outcome in h2h.get("outcomes", [])}
        odds_map = {_canonical(k): v for k, v in outcomes.items()}
        home_win = odds_map.get(home)
        draw = odds_map.get("Draw")
        away_win = odds_map.get(away)
        if home_win and draw and away_win:
            matches.append(
                {"home": home, "away": away, "home_win": float(home_win), "draw": float(draw), "away_win": float(away_win), "source": "theoddsapi"}
            )
    if not matches:
        log("no h2h odds parsed; using built-in odds")
        _write_builtin_odds()
        return
    from ..competitions.premier_league import _competition_stamp

    DATA.joinpath("epl_odds.json").write_text(json.dumps({"matches": matches, **_competition_stamp()}, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote epl_odds.json ({len(matches)} fixtures)")


def _write_builtin_odds() -> None:
    from ..competitions.premier_league import EPL_CLUBS

    matches = []
    for i in range(0, len(EPL_CLUBS), 2):
        if i + 1 >= len(EPL_CLUBS):
            break
        matches.append(
            {
                "home": EPL_CLUBS[i],
                "away": EPL_CLUBS[i + 1],
                "home_win": 2.4,
                "draw": 3.3,
                "away_win": 2.9,
                "source": "builtin",
            }
        )
    from ..competitions.premier_league import _competition_stamp

    DATA.joinpath("epl_odds.json").write_text(json.dumps({"matches": matches, **_competition_stamp()}, indent=2), encoding="utf-8")


# ── Real lineups ──────────────────────────────────────────────────

PL_API_BASE = "https://footballapi.pulselive.com/football"
PL_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
    "Origin": "https://www.premierleague.com",
    "Referer": "https://www.premierleague.com/matchcentre/",
    "Accept": "application/json",
}
PL_MATCH_IDS = DATA / "pl_match_ids.json"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1"


def _pl_get(url: str, timeout: int = 20) -> Any:
    import urllib.request

    try:
        request = urllib.request.Request(url, headers=PL_API_HEADERS)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        log(f"Premier League API fetch failed {url}: {exc}")
        return None


def _pl_match_ids(force: bool = False) -> dict[str, int]:
    """Map our fixture codes (``pl_<opta>``) to Premier League API match ids.

    The fixture feed exposes ``altIds.opta`` (e.g. ``g2645195``), which is
    exactly the code stored in pl_matches.json, so each record maps 1:1.
    """
    if not force and PL_MATCH_IDS.exists():
        try:
            return json.loads(PL_MATCH_IDS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    ids: dict[str, int] = {}
    page, page_size = 0, 50
    while page < 16:
        payload = _pl_get(
            f"{PL_API_BASE}/fixtures?comps=1&compSeasons=841&page={page}"
            f"&pageSize={page_size}&altIds=true"
        )
        if not isinstance(payload, dict):
            break
        content = payload.get("content", [])
        for fixture in content:
            alt = str((fixture.get("altIds") or {}).get("opta", "")).lstrip("g")
            if alt:
                ids[alt] = int(fixture["id"])
        if len(content) < page_size:
            break
        page += 1
    if ids:
        PL_MATCH_IDS.write_text(json.dumps(ids, indent=0, sort_keys=True), encoding="utf-8")
        log(f"cached {len(ids)} Premier League API match ids")
    return ids


def _parse_pl_fixture(payload: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    """Extract confirmed XIs from a Premier League API fixture response."""
    teams = payload.get("teams", [])
    team_lists = payload.get("teamLists", [])
    if not isinstance(teams, list) or not isinstance(team_lists, list) or len(team_lists) != 2:
        return None
    result: dict[str, dict[str, Any]] = {}
    for team_entry, team_list in zip(teams, team_lists):
        team_object = team_entry.get("team", {}) or {}
        name = (
            team_object.get("name")
            or team_object.get("shortClubname")
            or (team_object.get("club", {}) or {}).get("name")
            or ""
        ).strip()
        lineup = team_list.get("lineup", [])
        if not isinstance(lineup, list) or len(lineup) < 11:
            return None
        names = [
            str((entry.get("name", {}) or {}).get("display"))
            for entry in lineup
            if (entry.get("name", {}) or {}).get("display")
        ]
        if len(names) < 11:
            return None
        formation = (team_list.get("formation", {}) or {}).get("label") or ""
        result[name] = {
            "xi": [{"name": n, "position": ""} for n in names],
            "formation": str(formation),
        }
    return result or None


def _pl_starters(match_id: int) -> dict[str, dict[str, Any]] | None:
    """Confirmed starting XIs for one Premier League API match."""
    payload = _pl_get(f"{PL_API_BASE}/fixtures/{match_id}")
    if not isinstance(payload, dict):
        return None
    return _parse_pl_fixture(payload)


def _try_get(url: str, timeout: int = 20) -> Any:
    try:
        return _get(url, timeout=timeout)
    except Exception as exc:
        log(f"ESPN fetch failed {url}: {exc}")
        return None


def _names_overlap(a: str, b: str) -> bool:
    return bool(set(_name_key(a).split()) & set(_name_key(b).split()))


def _same_teams(a: str, b: str, home: str, away: str) -> bool:
    return (_names_overlap(a, home) and _names_overlap(b, away)) or (
        _names_overlap(a, away) and _names_overlap(b, home)
    )


def _espn_event_id(home: str, away: str, date_iso: str) -> str | None:
    """The ESPN event id for a completed PL fixture, via the scoreboard.

    Search a three-day window around the kickoff so timezone offsets between
    the recorded UTC kickoff and ESPN's (US-facing) daily boards can't miss it.
    """
    from datetime import datetime as _dt, timedelta as _td

    try:
        day = _dt.fromisoformat(str(date_iso).replace("Z", "+00:00")).date()
    except ValueError:
        return None
    for offset in (0, -1, 1):
        day_key = (day + _td(days=offset)).strftime("%Y%m%d")
        payload = _try_get(f"{ESPN_BASE}/scoreboard?dates={day_key}")
        if not isinstance(payload, dict):
            continue
        for event in payload.get("events", []):
            competitions = event.get("competitions", [{}])
            competitors = competitions[0].get("competitors", []) if competitions else []
            if len(competitors) != 2:
                continue
            names = [comp.get("team", {}).get("displayName", "") for comp in competitors]
            if _same_teams(names[0], names[1], home, away):
                return str(event.get("id"))
    return None


def _espn_starters(event_id: str) -> dict[str, dict[str, Any]] | None:
    """Real starting XIs for one ESPN event: teamName -> xi + formation."""
    payload = _try_get(f"{ESPN_BASE}/summary?event={event_id}")
    if not isinstance(payload, dict):
        return None
    rosters = payload.get("rosters")
    if not isinstance(rosters, list):
        return None
    result: dict[str, dict[str, Any]] = {}
    for team in rosters:
        name = (team.get("team", {}).get("displayName") or "").strip()
        athletes = team.get("roster") or team.get("athletes") or []
        xi: list[dict[str, str]] = []
        for athlete_entry in athletes:
            if not athlete_entry.get("starter"):
                continue
            athlete = athlete_entry.get("athlete", {}) or {}
            player_name = (
                athlete.get("displayName")
                or athlete.get("shortName")
                or athlete.get("fullName")
                or ""
            ).strip()
            position = (athlete_entry.get("position", {}) or {}).get("abbreviation", "")
            if player_name:
                xi.append({"name": player_name, "position": str(position)})
        if len(xi) < 11:
            log(f"ESPN event {event_id}: {name} only {len(xi)} starters — skipping")
            return None
        result[name] = {"xi": xi, "formation": _formation_from_xi(xi)}
    return result or None


def _formation_from_xi(xi: list[dict[str, str]]) -> str:
    def _bucket(position: str) -> str | None:
        pos = str(position).upper()
        if pos.startswith(("SB", "SU", "RE")):  # subs/reserves are never starters here
            return None
        if pos in ("LB", "RB", "CB", "LWB", "RWB") or pos.startswith(("CD", "DF")):
            return "D"
        if pos in ("CM", "DM", "LM", "RM", "AM", "CAM", "MF") or pos.startswith("MD"):
            return "M"
        if pos.startswith(("ST", "CF", "LW", "RW", "SS", "FW")):
            return "F"
        return None

    counts = {"D": 0, "M": 0, "F": 0}
    for entry in xi:
        bucket = _bucket(entry.get("position", ""))
        if bucket:
            counts[bucket] += 1
    formation = f"{counts['D']}-{counts['M']}-{counts['F']}"
    return formation if sum(counts.values()) == 10 else "4-3-3"


def _roster_names_per_team() -> dict[str, list[str]]:
    """Canonical roster player names per club, from pl_rosters.json."""
    rosters = _load_json(DATA / "pl_rosters.json")
    names: dict[str, list[str]] = {}
    for team, groups in rosters.items():
        if not isinstance(groups, dict) or str(team).startswith("_"):
            continue
        for records in groups.values():
            if not isinstance(records, list):
                continue
            for record in records:
                names.setdefault(team, [])
                name = str(record[0]) if isinstance(record, (list, tuple)) else str(record)
                if name:
                    names[team].append(name)
    return names


def _canonical_name(name: str, roster_names: list[str]) -> str:
    """Map an ESPN lineup name onto our roster naming where we can.

    Exact (accent/punctuation folded) match first; otherwise a unique surname
    match, so "Kjell Scherpen" resolves to the roster's spelling when present.
    """
    from ..services.v2_data_loader import normalize_name

    key = normalize_name(name)
    exact = {normalize_name(candidate): candidate for candidate in roster_names}
    if key in exact:
        return exact[key]
    surname = _name_key(name).split()
    surname = surname[-1] if surname else ""
    if len(surname) >= 3:
        matches = [
            candidate
            for candidate in roster_names
            if _name_key(candidate).split()
            and _name_key(candidate).split()[-1] == surname
        ]
        if len(matches) == 1:
            return matches[0]
    return name


def populate_epl_lineups() -> dict[str, Any]:
    """Fill each completed fixture's home/away ``players`` with real XIs.

    Primary source is the Premier League's own public (keyless) API, keyed off
    the fixture codes already stored in pl_matches.json; ESPN is the fallback.
    Lineups only exist for matches that have actually been played, so upcoming
    fixtures are left untouched. Already-populated matches are skipped.
    """
    from ..competitions.premier_league import _competition_stamp

    matches_path = DATA / "pl_matches.json"
    matches = _load_json(matches_path)
    if not matches:
        raise FileNotFoundError(f"{matches_path} not found; run fetch first")

    roster_names = _roster_names_per_team()
    match_ids = _pl_match_ids()
    completed = matches.get("completed", [])
    filled = skipped = failed = unmatched = 0

    def _merge_into(sides: dict[str, dict[str, Any]]) -> int:
        merged = 0
        for side in ("home", "away"):
            team_name = match[side]["name"]
            target = next(
                (lu for key, lu in sides.items() if _names_overlap(key, team_name)),
                None,
            )
            if not target:
                continue
            canonical_names = roster_names.get(team_name, [])
            match[side]["formation"] = target["formation"]
            match[side]["players"] = [
                {"name": _canonical_name(entry["name"], canonical_names)}
                for entry in target["xi"]
            ]
            merged += 1
        return merged

    for match in completed:
        if match.get("home", {}).get("players") or match.get("away", {}).get("players"):
            skipped += 1
            continue
        code = str(match.get("id", "")).replace("pl_", "")
        sides: dict[str, dict[str, Any]] | None = None
        if code:
            match_id = match_ids.get(code)
            if match_id:
                sides = _pl_starters(int(match_id))
        if not sides:
            home, away = match["home"]["name"], match["away"]["name"]
            event_id = _espn_event_id(home, away, match.get("date", ""))
            if not event_id:
                failed += 1
                continue
            sides = _espn_starters(event_id)
        if not sides:
            failed += 1
            continue
        merged = _merge_into(sides)
        if merged:
            filled += 1
        else:
            unmatched += 1

    matches["last_updated"] = _competition_stamp().get("stamp", "")
    matches_path.write_text(json.dumps(matches, indent=2, ensure_ascii=False), encoding="utf-8")
    log(
        f"populated {filled} completed fixtures with real lineups "
        f"({skipped} already filled, {failed} no source, {unmatched} unmatched sides)"
    )
    return {"filled": filled, "skipped": skipped, "failed": failed, "unmatched": unmatched}


# ── Main ──────────────────────────────────────────────────────────


def refresh(
    season: int = 2026,
    include_xg: bool = False,
    odds: bool = False,
    minimal: bool = False,
    lineups: bool = False,
) -> None:
    """Refresh Premier League data files. Used by CLI and in-bot invocations."""
    DATA.mkdir(parents=True, exist_ok=True)

    try:
        bootstrap, fixtures = fetch_fpl()
    except Exception as exc:
        log(f"FPL fetch failed ({exc}); ensuring offline defaults exist")
        from ..competitions.premier_league import write_default_pl_files

        write_default_pl_files(HERE)
        fill_rosters_from_fc26()
        _write_builtin_odds()
        return

    build_teams_file(bootstrap)
    build_matches_file(fixtures, season)
    build_squads_file(bootstrap)
    fc26 = _load_fc26()
    build_players_file(bootstrap, fc26)
    build_rosters_file(bootstrap)
    fill_rosters_from_fc26()

    if not minimal:
        try:
            fetch_club_elo()
        except Exception as exc:
            log(f"club elo failed ({exc})")
    if odds:
        fetch_odds()
    elif not minimal:
        log("skipping odds (pass --odds to fetch)")
    if lineups:
        try:
            populate_epl_lineups()
        except FileNotFoundError as exc:
            log(f"lineups skipped: {exc}")
    log("done")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Premier League data for the simulator.")
    parser.add_argument("--season", type=int, default=2026, help="Season start year (default: current)")
    parser.add_argument("--odds", action="store_true", help="Fetch market odds (requires ODDS_API_KEY)")
    parser.add_argument("--include-xg", action="store_true", help="Fetch Understat xG data (experimental)")
    parser.add_argument("--minimal", action="store_true", help="Skip optional sources (FPL only)")
    parser.add_argument("--lineups", action="store_true", help="Populate completed fixtures with real starting XIs (Premier League API, no key)")
    args = parser.parse_args()

    refresh(
        season=args.season,
        include_xg=args.include_xg,
        odds=args.odds,
        minimal=args.minimal,
        lineups=args.lineups,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())