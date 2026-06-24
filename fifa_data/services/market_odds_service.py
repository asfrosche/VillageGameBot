from __future__ import annotations

from typing import Any

from ..models.market_comparison import (
    MarketOdds,
    NormalizedMarket,
    ModelVsMarketEntry,
    ModelVsMarketComparison,
    ValueDetection,
    ValueLevel,
    ConsensusData,
    ConsensusLevel,
)


# ── Built-in market odds profiles for major teams ────────────────
# Format: {team_name: (home_decimal, draw_decimal, away_decimal)}
# These are representative pre-match odds from major sportsbooks.
# In production, replace with live API data from Pinnacle/Bet365/DraftKings.

BUILTIN_MARKET_ODDS: dict[str, tuple[float, float, float]] = {
    "Argentina": (1.72, 3.60, 5.00),
    "Brazil": (1.65, 3.75, 5.50),
    "France": (1.80, 3.50, 4.75),
    "England": (1.85, 3.45, 4.50),
    "Spain": (2.10, 3.30, 3.80),
    "Germany": (2.00, 3.40, 4.00),
    "Portugal": (2.20, 3.25, 3.60),
    "Netherlands": (2.15, 3.30, 3.70),
    "Italy": (2.30, 3.20, 3.50),
    "Belgium": (2.40, 3.15, 3.40),
    "Croatia": (2.80, 3.10, 3.00),
    "Uruguay": (3.00, 3.05, 2.85),
    "Morocco": (3.50, 3.00, 2.60),
    "Japan": (4.00, 3.40, 2.20),
    "Senegal": (3.80, 3.20, 2.30),
    "Switzerland": (3.20, 3.10, 2.70),
    "USA": (3.60, 3.30, 2.40),
    "Mexico": (4.20, 3.40, 2.10),
    "Denmark": (2.60, 3.15, 3.10),
    "Poland": (3.40, 3.10, 2.55),
    "Sweden": (3.30, 3.10, 2.60),
    "South Korea": (5.50, 3.80, 1.75),
    "Colombia": (2.70, 3.10, 3.00),
    "Nigeria": (4.50, 3.50, 2.00),
}

# Multiple sportsbook sources with slight variations
MARKET_SOURCES = [
    {"source": "Pinnacle", "offset": 0.0},
    {"source": "Bet365", "offset": 0.02},
    {"source": "DraftKings", "offset": -0.01},
    {"source": "FanDuel", "offset": 0.01},
    {"source": "BetMGM", "offset": 0.015},
]


def _decimal_to_implied(decimal: float) -> float:
    if decimal <= 1.0:
        return 0.0
    return 1.0 / decimal


def _remove_vig(probs: list[float]) -> list[float]:
    total = sum(probs)
    if total <= 0:
        return probs
    return [p / total for p in probs]


def normalize_odds(
    home_decimal: float,
    draw_decimal: float,
    away_decimal: float,
) -> tuple[float, float, float]:
    raw = [
        _decimal_to_implied(home_decimal),
        _decimal_to_implied(draw_decimal),
        _decimal_to_implied(away_decimal),
    ]
    return tuple(_remove_vig(raw))  # type: ignore


def get_market_odds_for_teams(team_a: str, team_b: str) -> list[MarketOdds]:
    if team_a in BUILTIN_MARKET_ODDS and team_b in BUILTIN_MARKET_ODDS:
        odds_a = BUILTIN_MARKET_ODDS[team_a]
        odds_b = BUILTIN_MARKET_ODDS[team_b]
        avg_home = (odds_a[0] + odds_b[2]) / 2
        avg_draw = (odds_a[1] + odds_b[1]) / 2
        avg_away = (odds_a[2] + odds_b[0]) / 2

        results = []
        for src in MARKET_SOURCES:
            offset = src["offset"]
            h = round(avg_home * (1 - offset), 2)
            d = round(avg_draw * (1 - offset), 2)
            a = round(avg_away * (1 - offset), 2)
            results.append(MarketOdds(
                source=src["source"],
                home_decimal=h,
                draw_decimal=d,
                away_decimal=a,
                home_implied=round(_decimal_to_implied(h) * 100, 2),
                draw_implied=round(_decimal_to_implied(d) * 100, 2),
                away_implied=round(_decimal_to_implied(a) * 100, 2),
            ))
        return results

    base_home = 2.50
    base_draw = 3.20
    base_away = 3.00

    return [MarketOdds(
        source="Default",
        home_decimal=base_home,
        draw_decimal=base_draw,
        away_decimal=base_away,
        home_implied=round(_decimal_to_implied(base_home) * 100, 2),
        draw_implied=round(_decimal_to_implied(base_draw) * 100, 2),
        away_implied=round(_decimal_to_implied(base_away) * 100, 2),
    )]


def compute_normalized_market(odds_list: list[MarketOdds]) -> NormalizedMarket:
    if not odds_list:
        return NormalizedMarket(home_prob=33.3, draw_prob=33.3, away_prob=33.3)

    home_probs = []
    draw_probs = []
    away_probs = []
    for odds in odds_list:
        h, d, a = normalize_odds(odds.home_decimal, odds.draw_decimal, odds.away_decimal)
        home_probs.append(h)
        draw_probs.append(d)
        away_probs.append(a)

    avg_h = sum(home_probs) / len(home_probs) * 100
    avg_d = sum(draw_probs) / len(draw_probs) * 100
    avg_a = sum(away_probs) / len(away_probs) * 100

    total = avg_h + avg_d + avg_a
    if total > 0:
        avg_h = avg_h / total * 100
        avg_d = avg_d / total * 100
        avg_a = avg_a / total * 100

    return NormalizedMarket(
        home_prob=round(avg_h, 1),
        draw_prob=round(avg_d, 1),
        away_prob=round(avg_a, 1),
        sources_used=len(odds_list),
        source_names=[o.source for o in odds_list],
    )


def compute_model_vs_market(
    team_a: str,
    team_b: str,
    model_win_a: float,
    model_draw: float,
    model_win_b: float,
    odds_list: list[MarketOdds] | None = None,
) -> ModelVsMarketComparison:
    if odds_list is None:
        odds_list = get_market_odds_for_teams(team_a, team_b)

    market = compute_normalized_market(odds_list)

    entries = [
        ModelVsMarketEntry(
            team=team_a,
            model_prob=model_win_a,
            market_prob=market.home_prob,
            edge=round((model_win_a - market.home_prob) / 100.0, 4),
        ),
        ModelVsMarketEntry(
            team="Draw",
            model_prob=model_draw,
            market_prob=market.draw_prob,
            edge=round((model_draw - market.draw_prob) / 100.0, 4),
        ),
        ModelVsMarketEntry(
            team=team_b,
            model_prob=model_win_b,
            market_prob=market.away_prob,
            edge=round((model_win_b - market.away_prob) / 100.0, 4),
        ),
    ]

    consensus_raw_h = [o.home_implied for o in odds_list]
    consensus_raw_d = [o.draw_implied for o in odds_list]
    consensus_raw_a = [o.away_implied for o in odds_list]

    def _consensus_level(vals: list[float]) -> ConsensusLevel:
        if len(vals) < 2:
            return ConsensusLevel.WEAK
        spread = max(vals) - min(vals)
        if spread < 3:
            return ConsensusLevel.STRONG
        if spread < 7:
            return ConsensusLevel.MODERATE
        return ConsensusLevel.WEAK

    consensus = ConsensusData(
        market_count=len(odds_list),
        home_range=(min(consensus_raw_h), max(consensus_raw_h)) if consensus_raw_h else (0, 0),
        draw_range=(min(consensus_raw_d), max(consensus_raw_d)) if consensus_raw_d else (0, 0),
        away_range=(min(consensus_raw_a), max(consensus_raw_a)) if consensus_raw_a else (0, 0),
        home_consensus=_consensus_level(consensus_raw_h),
        draw_consensus=_consensus_level(consensus_raw_d),
        away_consensus=_consensus_level(consensus_raw_a),
        source_details=[
            {"source": o.source, "home": o.home_decimal, "draw": o.draw_decimal, "away": o.away_decimal}
            for o in odds_list
        ],
    )

    return ModelVsMarketComparison(
        team_a=team_a,
        team_b=team_b,
        entries=entries,
        market=market,
        consensus=consensus,
    )


def detect_value(market_entry: ModelVsMarketEntry) -> ValueDetection:
    description = ""
    if market_entry.edge >= 0.05:
        description = f"Model sees significant value on {market_entry.team} (+{market_entry.edge:.1%} vs market)"
    elif market_entry.edge >= 0.03:
        description = f"Moderate value detected on {market_entry.team} (+{market_entry.edge:.1%})"
    elif market_entry.edge >= -0.01:
        description = f"{market_entry.team} is fairly priced"
    else:
        description = f"{market_entry.team} is overvalued by the market ({market_entry.edge:.1%})"

    return ValueDetection(
        team=market_entry.team,
        edge=market_entry.edge,
        level=market_entry.value_level,
        description=description,
    )


def compute_value_detections(comparison: ModelVsMarketComparison) -> list[ValueDetection]:
    return [detect_value(entry) for entry in comparison.entries]
