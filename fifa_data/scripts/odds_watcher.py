"""Market-odds agent for the Premier League simulator.

Polls a live odds source (TheOddsAPI ``soccer_epl`` h2h, or API-Football
league 39 as an alternative) and writes:
  * ``data/epl_odds.json``         — the exact schema ``v6``'s
    ``load_market_odds_from_file`` consumes (``matches: [{home, away,
    home_win, draw, away_win, source}]``).
  * ``data/epl_title_odds.json``   — per-club title-odds derivative used for
    Monte Carlo cross-checks.

If no API key is available the file is populated with synthetic ELO-based
odds so the downstream engines keep working (same fallback as the WC path).

CLI:
    python -m fifa_data.scripts.odds_watcher --once
    python -m fifa_data.scripts.odds_watcher --interval 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "data"


def _log(message: str) -> None:
    print(f"[odds_watcher] {message}")


def _get(url: str, headers: dict[str, str] | None = None, params: dict[str, str] | None = None, timeout: int = 20) -> Any:
    import urllib.parse
    import urllib.request

    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _canonical(name: str) -> str:
    from ..competitions.premier_league import canonical_team_name

    return canonical_team_name(name)


def _de_vig(home: float, draw: float, away: float) -> tuple[float, float, float]:
    from ..services.market_odds_service import _decimal_to_implied, _remove_vig

    probs = _remove_vig([_decimal_to_implied(float(home)), _decimal_to_implied(float(draw)), _decimal_to_implied(float(away))])
    if not probs or min(probs) <= 0:
        return float(home), float(draw), float(away)
    return [round(1.0 / p, 4) for p in probs]  # type: ignore[return-value]


def fetch_theoddsapi(api_key: str) -> list[dict[str, Any]]:
    data = _get(
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        params={"apiKey": api_key, "regions": "eu,uk", "markets": "h2h", "oddsFormat": "decimal"},
    )
    matches: list[dict[str, Any]] = []
    for event in data:
        home = _canonical(str(event.get("home_team", "")))
        away = _canonical(str(event.get("away_team", "")))
        if home not in _pl_clubs() or away not in _pl_clubs():
            continue
        best: tuple[float, float, float] | None = None
        best_quality = 1e9
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = {outcome.get("name"): outcome.get("price") for outcome in market.get("outcomes", [])}
                h = outcomes.get(home)
                d = outcomes.get("Draw")
                a = outcomes.get(away)
                if h and d and a:
                    hw, dr, aw = _de_vig(h, d, a)
                    quality = abs((1.0 / hw) + (1.0 / dr) + (1.0 / aw) - 1.0)
                    if quality < best_quality:
                        best_quality = quality
                        best = (hw, dr, aw)
                        best_source = str(bookmaker.get("key", "theoddsapi"))
        if best:
            matches.append(
                {"home": home, "away": away, "home_win": best[0], "draw": best[1], "away_win": best[2], "source": best_source}
            )
    return matches


def fetch_api_football(api_key: str, season: int = 2026) -> list[dict[str, Any]]:
    """API-Football /odds league=39 (premium access only)."""
    headers = {"x-apisports-key": api_key}
    data = _get("https://v3.football.api-sports.io/odds", headers=headers, params={"league": "39", "season": str(season), "bookmaker": "5", "page": "1"})
    matches: list[dict[str, Any]] = []
    for fixture in data.get("response", []):
        fixture_info = fixture.get("fixture", {})
        teams = fixture.get("teams", {})
        home = _canonical(str(teams.get("home", {}).get("name", "")))
        away = _canonical(str(teams.get("away", {}).get("name", "")))
        h2h = next((odd for odd in fixture.get("bookmakers", [])[0].get("bets", []) if odd.get("name") == "Match Winner"), None)
        if not h2h:
            continue
        values = {v.get("value"): v.get("odd") for v in h2h.get("values", [])}
        h, d, a = values.get("Home"), values.get("Draw"), values.get("Away")
        if h and d and a and home and away:
            hw, dr, aw = _de_vig(h, d, a)
            matches.append({"home": home, "away": away, "home_win": hw, "draw": dr, "away_win": aw, "source": "api-football"})
    return matches


def _pl_clubs() -> set[str]:
    from ..competitions.premier_league import EPL_CLUBS

    return set(EPL_CLUBS)


def synthetic_odds_for_fixtures() -> list[dict[str, Any]]:
    from ..competitions.premier_league import EPL_CLUBS
    from ..competitions import get_competition
    from ..services._match_config import update_elo_from_matches
    from math import exp

    config = get_competition("premier-league", HERE)
    metrics = config.team_metrics
    update_elo_from_matches(metrics, config.matches_file, config.team_name_map)
    matches = []
    n = len(EPL_CLUBS)
    draw_prob = 0.26
    for i in range(0, n, 2):
        if i + 1 >= n:
            break
        home, away = EPL_CLUBS[i], EPL_CLUBS[i + 1]
        home_rating = (metrics.get(home, {}).get("ELO", 1800) + metrics.get(home, {}).get("PELE", 1740)) / 2
        away_rating = (metrics.get(away, {}).get("ELO", 1800) + metrics.get(away, {}).get("PELE", 1740)) / 2
        raw_home = 1.0 / (1.0 + exp(-(home_rating + 45 - away_rating) / 200.0))
        raw_away = 1.0 / (1.0 + exp(-(away_rating - home_rating) / 200.0))
        p_home = (1.0 - draw_prob) * raw_home
        p_away = (1.0 - draw_prob) * raw_away
        total = p_home + p_away + draw_prob
        p_home /= total
        p_away /= total
        p_draw = draw_prob / total
        matches.append(
            {
                "home": home,
                "away": away,
                "home_win": round(1.0 / max(0.01, p_home), 4),
                "draw": round(1.0 / max(0.01, p_draw), 4),
                "away_win": round(1.0 / max(0.01, p_away), 4),
                "source": "synthetic-elo",
            }
        )
    return matches


def write_odds(matches: list[dict[str, Any]]) -> None:
    from ..competitions.premier_league import _competition_stamp

    DATA.mkdir(parents=True, exist_ok=True)
    DATA.joinpath("epl_odds.json").write_text(json.dumps({"matches": matches, **_competition_stamp()}, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"wrote epl_odds.json ({len(matches)} fixtures)")


def write_title_odds(matches: list[dict[str, Any]]) -> None:
    """Derive a per-club title-odds approximation from match win probabilities."""
    share: dict[str, float] = {}
    total = 0.0
    for match in matches:
        for team, price in ((match["home"], match["home_win"]), (match["away"], match["away_win"])):
            prob = 1.0 / max(1.01, float(price))
            share[team] = share.get(team, 0.0) + prob
            total += prob
    if total <= 0:
        return
    title = {team: round(100.0 * p / total, 3) for team, p in sorted(share.items())}
    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "Approximation: each club's implied h2h win probability normalized across fixtures.",
        "title_prob_pct": title,
    }
    from ..competitions.premier_league import _competition_stamp

    DATA.joinpath("epl_title_odds.json").write_text(json.dumps({**output, **_competition_stamp()}, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"wrote epl_title_odds.json ({len(title)} clubs)")


def refresh(once_only: bool = False) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    football_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if odds_key:
        try:
            matches = fetch_theoddsapi(odds_key)
        except Exception as exc:
            _log(f"theoddsapi failed ({exc}); trying api-football")
        if matches:
            write_odds(matches)
            write_title_odds(matches)
            return matches
    if football_key:
        try:
            matches = fetch_api_football(football_key)
        except Exception as exc:
            _log(f"api-football failed ({exc})")
        if matches:
            write_odds(matches)
            write_title_odds(matches)
            return matches
    matches = synthetic_odds_for_fixtures()
    write_odds(matches)
    write_title_odds(matches)
    _log("no live odds source — wrote synthetic ELO odds")
    return matches


def run_forever(interval_minutes: int = 60) -> None:
    while True:
        refresh()
        _log(f"sleeping {interval_minutes} min")
        time.sleep(interval_minutes * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Premier League market-odds agent.")
    parser.add_argument("--once", action="store_true", help="Run a single refresh cycle and exit")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in minutes")
    args = parser.parse_args()

    refresh()
    if args.once:
        return 0
    run_forever(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())