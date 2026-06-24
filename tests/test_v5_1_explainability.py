from __future__ import annotations

import unittest

from fifa_data.models.player import Player
from fifa_data.models.squad import Squad
from fifa_data.models.player_influence import (
    OffensiveInfluence, DefensiveInfluence, GoalkeeperInfluence,
    TeamDependency, PlayerMatchup, PlayerInfluenceReport,
)
from fifa_data.models.tactical_vulnerability import (
    TacticalStrength, TeamWeakness, TacticalVulnerabilityReport,
    ExploitationOpportunity, ExploitationReport,
    MatchArchetypeData, MatchArchetypeReport,
    WinCondition, WinConditionReport,
)
from fifa_data.models.market_comparison import (
    MarketOdds, NormalizedMarket, ModelVsMarketEntry, ModelVsMarketComparison,
    ValueLevel, ConsensusLevel, ConsensusData, ValueDetection,
)
from fifa_data.services.tactical_analysis import (
    compute_offensive_influence,
    compute_defensive_influence,
    compute_goalkeeper_influence,
    compute_team_dependency,
    compute_player_matchups,
    compute_player_influence,
    compute_strengths,
    compute_weaknesses,
    compute_vulnerability_report,
    compute_exploitation,
    classify_match_archetypes,
    analyze_win_conditions,
)
from fifa_data.services.market_odds_service import (
    normalize_odds,
    get_market_odds_for_teams,
    compute_normalized_market,
    compute_model_vs_market,
    detect_value,
    compute_value_detections,
)
from fifa_data.services.model_confidence_service import compute_confidence


def _make_player(name: str, country: str, position: str, attrs: dict) -> Player:
    return Player(
        name=name,
        country=country,
        positions=(position,),
        attributes=attrs,
    )


def _make_squad(
    country: str,
    formation: str = "4-3-3",
    rating: float = 80.0,
) -> Squad:
    attrs = {
        "pace": rating, "dribbling": rating, "passing": rating,
        "finishing": rating, "shot_power": rating, "positioning": rating,
        "defending": rating, "defensive_awareness": rating, "tackling": rating,
        "strength": rating, "reactions": rating, "composure": rating,
        "vision": rating, "crossing": rating, "stamina": rating,
        "physical": rating, "aggression": rating, "interceptions": rating,
        "heading_accuracy": rating, "jumping": rating, "long_shots": rating,
        "reflexes": rating, "diving": rating, "handling": rating, "kicking": rating,
        "work_rate": 70, "pressing": rating, "penalties": rating,
        "leadership": 50, "experience": 50, "age": 27, "penalty_save": rating,
    }

    starters = [
        _make_player(f"{country} GK1", country, "GK", {**attrs, "reflexes": rating, "diving": rating, "positioning": rating, "handling": rating, "kicking": rating}),
        _make_player(f"{country} CB1", country, "CB", {**attrs, "defensive_awareness": rating, "tackling": rating, "strength": rating}),
        _make_player(f"{country} CB2", country, "CB", {**attrs, "defensive_awareness": rating, "tackling": rating, "strength": rating}),
        _make_player(f"{country} FB1", country, "FB", {**attrs, "pace": rating, "defending": rating, "crossing": rating, "stamina": rating}),
        _make_player(f"{country} FB2", country, "FB", {**attrs, "pace": rating, "defending": rating, "crossing": rating, "stamina": rating}),
        _make_player(f"{country} CM1", country, "CM", {**attrs, "passing": rating, "vision": rating, "dribbling": rating}),
        _make_player(f"{country} CM2", country, "CM", {**attrs, "passing": rating, "vision": rating, "dribbling": rating}),
        _make_player(f"{country} CM3", country, "CM", {**attrs, "passing": rating, "vision": rating, "dribbling": rating}),
        _make_player(f"{country} WG1", country, "WINGER", {**attrs, "pace": rating + 5, "dribbling": rating, "crossing": rating}),
        _make_player(f"{country} WG2", country, "WINGER", {**attrs, "pace": rating + 5, "dribbling": rating, "crossing": rating}),
        _make_player(f"{country} ST1", country, "ST", {**attrs, "finishing": rating + 5, "positioning": rating, "shot_power": rating}),
    ]
    return Squad(country=country, players=starters, formation=formation, preferred_starting_xi=starters)


class PlayerInfluenceServiceTests(unittest.TestCase):
    def setUp(self):
        self.squad = _make_squad("France", "4-3-3", 80.0)
        self.player = self.squad.current_starting_xi[10]  # ST
        self.gk = self.squad.current_starting_xi[0]  # GK
        self.cb = self.squad.current_starting_xi[1]  # CB

    def test_offensive_influence_st(self):
        inf = compute_offensive_influence(self.player, self.squad, 2.5)
        self.assertIsInstance(inf, OffensiveInfluence)
        self.assertEqual(inf.player_name, "France ST1")
        self.assertEqual(inf.role, "ST")
        self.assertGreater(inf.overall_influence, 0)
        self.assertGreater(inf.xg_contribution, 0)
        self.assertGreater(inf.chance_creation, 0)
        self.assertIn("finishing", inf.breakdown)

    def test_offensive_influence_gk(self):
        inf = compute_offensive_influence(self.gk, self.squad, 2.5)
        self.assertEqual(inf.role, "GK")
        self.assertLessEqual(inf.overall_influence, 6.0)

    def test_defensive_influence_cb(self):
        inf = compute_defensive_influence(self.cb, self.squad, 1.5)
        self.assertIsInstance(inf, DefensiveInfluence)
        self.assertEqual(inf.role, "CB")
        self.assertGreater(inf.overall_influence, 0)
        self.assertGreater(inf.defensive_stability, 0)
        self.assertGreater(inf.tackling_rating, 0)

    def test_defensive_influence_st(self):
        st = self.squad.current_starting_xi[10]
        inf = compute_defensive_influence(st, self.squad, 1.5)
        self.assertLessEqual(inf.overall_influence, 5.0)

    def test_goalkeeper_influence(self):
        inf = compute_goalkeeper_influence(self.gk, self.squad, 5.0)
        self.assertIsInstance(inf, GoalkeeperInfluence)
        self.assertGreaterEqual(inf.overall_influence, 1.0)
        self.assertGreaterEqual(inf.save_expectation, 0)
        self.assertIn("reflexes", inf.breakdown)

    def test_team_dependency(self):
        dep = compute_team_dependency("France", self.squad, 2.5, 1.5)
        self.assertIsInstance(dep, TeamDependency)
        self.assertEqual(dep.team, "France")
        self.assertGreater(dep.attack_output_share, 0)
        self.assertIn(dep.dependency_level, ("High", "Moderate", "Low"))
        self.assertEqual(len(dep.top_attackers_names), 3)
        self.assertEqual(len(dep.top_defenders_names), 3)

    def test_team_dependency_high_stars(self):
        squad_high = _make_squad("High", "4-3-3", 90.0)
        dep = compute_team_dependency("High", squad_high, 3.0, 1.0)
        self.assertIsNotNone(dep)
        self.assertGreater(dep.attack_output_share, 0)

    def test_player_matchups(self):
        squad_b = _make_squad("Spain", "4-3-3", 75.0)
        matchups = compute_player_matchups(self.squad, squad_b)
        self.assertIsInstance(matchups, list)
        self.assertGreater(len(matchups), 0)
        for m in matchups:
            self.assertIsInstance(m, PlayerMatchup)
            self.assertIn(m.category, ("ST vs CB", "Winger vs FB", "Midfield Battle"))
            self.assertIn(m.advantage_team, ("France", "Spain"))

    def test_compute_player_influence(self):
        squad_b = _make_squad("Spain", "4-3-3", 75.0)
        report = compute_player_influence("France", "Spain", self.squad, squad_b, 2.5, 1.8)
        self.assertIsInstance(report, PlayerInfluenceReport)
        self.assertEqual(report.team_a, "France")
        self.assertEqual(report.team_b, "Spain")
        self.assertEqual(len(report.offensive_a), 11)
        self.assertEqual(len(report.offensive_b), 11)
        self.assertEqual(len(report.defensive_a), 11)
        self.assertEqual(len(report.defensive_b), 11)
        self.assertIsNotNone(report.goalkeeper_a)
        self.assertIsNotNone(report.goalkeeper_b)
        self.assertIsNotNone(report.dependency_a)
        self.assertIsNotNone(report.dependency_b)
        self.assertGreater(len(report.matchups), 0)

    def test_top_attackers(self):
        squad_b = _make_squad("Spain", "4-3-3", 75.0)
        report = compute_player_influence("France", "Spain", self.squad, squad_b, 2.5, 1.8)
        top = report.top_attackers("France", 3)
        self.assertEqual(len(top), 3)
        for p in top:
            self.assertIsInstance(p, OffensiveInfluence)
        # top attackers from France should be sorted by influence descending
        self.assertGreaterEqual(top[0].overall_influence, top[1].overall_influence)

    def test_top_defenders(self):
        squad_b = _make_squad("Spain", "4-3-3", 75.0)
        report = compute_player_influence("France", "Spain", self.squad, squad_b, 2.5, 1.8)
        top = report.top_defenders("France", 3)
        self.assertEqual(len(top), 3)
        for p in top:
            self.assertIsInstance(p, DefensiveInfluence)

    def test_top_matchups(self):
        squad_b = _make_squad("Spain", "4-3-3", 75.0)
        report = compute_player_influence("France", "Spain", self.squad, squad_b, 2.5, 1.8)
        top = report.top_matchups(3)
        self.assertEqual(len(top), 3)
        if top:
            self.assertIsInstance(top[0], PlayerMatchup)


class TacticalVulnerabilityServiceTests(unittest.TestCase):
    def setUp(self):
        self.squad = _make_squad("France", "4-3-3", 80.0)
        self.profile = {
            "possession": 68, "pressing": 55, "directness": 60,
            "defensive_line": 62, "aerial_strength": 58,
            "set_piece_attack": 52, "set_piece_defense": 55,
            "big_chance_creation": 60, "defensive_compactness": 65,
            "build_up": 65, "defensive_width": 55,
        }

    def test_compute_strengths(self):
        strengths = compute_strengths("France", self.squad, self.profile)
        self.assertIsInstance(strengths, list)
        self.assertGreater(len(strengths), 0)
        self.assertLessEqual(len(strengths), 6)
        for s in strengths:
            self.assertIsInstance(s, TacticalStrength)
            self.assertGreater(s.magnitude, 0)

    def test_compute_strengths_low_team(self):
        low_profile = {k: 40 for k in self.profile}
        weak_squad = _make_squad("Low", "4-3-3", 50.0)
        strengths = compute_strengths("Low", weak_squad, low_profile)
        self.assertEqual(len(strengths), 0)

    def test_compute_weaknesses(self):
        weaknesses = compute_weaknesses("France", self.squad, self.profile)
        self.assertIsInstance(weaknesses, list)
        self.assertLessEqual(len(weaknesses), 5)

    def test_compute_weaknesses_weak_team(self):
        low_profile = {k: 40 for k in self.profile}
        weaknesses = compute_weaknesses("Low", self.squad, low_profile)
        self.assertGreater(len(weaknesses), 0)

    def test_compute_vulnerability_report(self):
        report = compute_vulnerability_report("France", self.squad, self.profile)
        self.assertIsInstance(report, TacticalVulnerabilityReport)
        self.assertEqual(report.team, "France")
        self.assertGreater(len(report.strengths), 0)

    def test_compute_exploitation(self):
        squad_b = _make_squad("Spain", "4-3-3", 75.0)
        profile_b = {k: v - 10 for k, v in self.profile.items()}
        report = compute_exploitation("France", "Spain", self.squad, squad_b, self.profile, profile_b)
        self.assertIsInstance(report, ExploitationReport)
        self.assertEqual(report.team_a, "France")
        self.assertEqual(report.team_b, "Spain")
        self.assertIsInstance(report.vulnerabilities_a, TacticalVulnerabilityReport)
        self.assertIsInstance(report.vulnerabilities_b, TacticalVulnerabilityReport)

    def test_classify_match_archetypes(self):
        profile_b = {k: v - 5 for k, v in self.profile.items()}
        report = classify_match_archetypes("France", "Spain", self.profile, profile_b)
        self.assertIsInstance(report, MatchArchetypeReport)
        self.assertGreater(len(report.archetypes), 0)
        for a in report.archetypes:
            self.assertIsInstance(a, MatchArchetypeData)
            self.assertGreater(a.probability, 0)

    def test_classify_match_archetypes_transition(self):
        fast_profile = {**self.profile, "directness": 75, "possession": 45}
        fast_profile_b = {**self.profile, "directness": 70, "possession": 50}
        report = classify_match_archetypes("Fast", "FastB", fast_profile, fast_profile_b)
        self.assertGreater(len(report.archetypes), 0)
        names = [a.archetype for a in report.archetypes]
        self.assertIn("Transition Battle", names)

    def test_analyze_win_conditions(self):
        report = analyze_win_conditions("France", self.profile, self.squad)
        self.assertIsInstance(report, WinConditionReport)
        self.assertEqual(report.team, "France")
        self.assertGreater(len(report.conditions), 0)
        total_prob = sum(c.probability for c in report.conditions)
        self.assertAlmostEqual(total_prob, 100.0, delta=1)

    def test_analyze_win_conditions_weak_team(self):
        low_profile = {k: 40 for k in self.profile}
        weak_squad = _make_squad("Low", "4-3-3", 50.0)
        report = analyze_win_conditions("Low", low_profile, weak_squad)
        self.assertEqual(len(report.conditions), 0)


class MarketOddsServiceTests(unittest.TestCase):
    def test_normalize_odds(self):
        h, d, a = normalize_odds(2.0, 3.4, 3.8)
        total = h + d + a
        self.assertAlmostEqual(total, 1.0, places=5)
        self.assertGreater(h, 0)
        self.assertGreater(d, 0)
        self.assertGreater(a, 0)

    def test_normalize_odds_heavy_favorite(self):
        h, d, a = normalize_odds(1.2, 6.0, 12.0)
        total = h + d + a
        self.assertAlmostEqual(total, 1.0, places=5)
        self.assertGreater(h, d)
        self.assertGreater(h, a)

    def test_get_market_odds_for_known_teams(self):
        odds_list = get_market_odds_for_teams("France", "Spain")
        self.assertGreater(len(odds_list), 0)
        for odds in odds_list:
            self.assertIsInstance(odds, MarketOdds)
            self.assertGreater(odds.home_decimal, 1.0)
            self.assertGreater(odds.draw_decimal, 1.0)
            self.assertGreater(odds.away_decimal, 1.0)
            self.assertGreater(odds.total_implied, 0)

    def test_get_market_odds_for_unknown_teams(self):
        odds_list = get_market_odds_for_teams("Unknown", "Teams")
        self.assertEqual(len(odds_list), 1)
        self.assertEqual(odds_list[0].source, "Default")

    def test_compute_normalized_market(self):
        odds_list = get_market_odds_for_teams("France", "Spain")
        market = compute_normalized_market(odds_list)
        self.assertIsInstance(market, NormalizedMarket)
        self.assertEqual(market.sources_used, len(odds_list))
        total = market.home_prob + market.draw_prob + market.away_prob
        self.assertAlmostEqual(total, 100.0, delta=1)

    def test_compute_model_vs_market(self):
        odds_list = get_market_odds_for_teams("France", "Spain")
        comparison = compute_model_vs_market("France", "Spain", 45.0, 28.0, 27.0, odds_list)
        self.assertIsInstance(comparison, ModelVsMarketComparison)
        self.assertEqual(comparison.team_a, "France")
        self.assertEqual(comparison.team_b, "Spain")
        self.assertEqual(len(comparison.entries), 3)
        self.assertIsNotNone(comparison.market)
        self.assertIsNotNone(comparison.consensus)

    def test_model_vs_market_edges(self):
        comparison = compute_model_vs_market("France", "Spain", 60.0, 20.0, 20.0)
        france_entry = next(e for e in comparison.entries if e.team == "France")
        self.assertIsNotNone(france_entry)
        self.assertIsInstance(france_entry.value_level, ValueLevel)

    def test_detect_value_strong(self):
        entry = ModelVsMarketEntry(team="France", model_prob=50, market_prob=42, edge=0.08)
        value = detect_value(entry)
        self.assertIsInstance(value, ValueDetection)
        self.assertEqual(value.level, ValueLevel.STRONG)
        self.assertIn("significant value", value.description)

    def test_detect_value_no_value(self):
        entry = ModelVsMarketEntry(team="France", model_prob=45, market_prob=44, edge=0.01)
        value = detect_value(entry)
        self.assertEqual(value.level, ValueLevel.NO_VALUE)
        self.assertIn("fairly priced", value.description)

    def test_detect_value_negative(self):
        entry = ModelVsMarketEntry(team="Spain", model_prob=20, market_prob=30, edge=-0.10)
        value = detect_value(entry)
        self.assertEqual(value.level, ValueLevel.NEGATIVE)
        self.assertIn("overvalued", value.description)

    def test_compute_value_detections(self):
        comparison = compute_model_vs_market("France", "Spain", 55.0, 25.0, 20.0)
        detections = compute_value_detections(comparison)
        self.assertEqual(len(detections), 3)
        for d in detections:
            self.assertIsInstance(d, ValueDetection)


class ModelConfidenceServiceTests(unittest.TestCase):
    def setUp(self):
        from fifa_data.services.simulation_report import MonteCarloResult, V4ReportData, TacticalAdjustmentData
        self.mc = MonteCarloResult(
            wins_a=550, wins_b=250, draws=200, total=1000,
            avg_xg_a=1.8, avg_xg_b=1.2,
            top_scores=[((1, 0), 120), ((1, 1), 100), ((2, 1), 80)],
            min_goals_a=0, max_goals_a=5, min_goals_b=0, max_goals_b=4,
        )
        self.v4 = V4ReportData(
            base_xg_a=1.5, base_xg_b=1.2,
            final_xg_a=1.8, final_xg_b=1.2,
            game_plan_a="balanced", game_plan_b="counter",
            advantages_a=["Midfield control"],
            adjustments_a=[TacticalAdjustmentData("possession", "Press resistance", 0.15)],
        )

    def test_compute_confidence_basic(self):
        result = compute_confidence(self.mc)
        self.assertIn("score", result)
        self.assertIn("level", result)
        self.assertIn("factors", result)
        self.assertIn("upset_probability", result)
        self.assertIn("volatility", result)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertIn(result["level"], ("Very High", "High", "Moderate", "Low", "Very Low"))
        self.assertGreaterEqual(len(result["factors"]), 5)

    def test_compute_confidence_with_all_data(self):
        from fifa_data.models.player_influence import TeamDependency
        from fifa_data.services.market_odds_service import compute_model_vs_market

        dep = TeamDependency(
            team="France", top_n_attackers=3,
            attack_output_share=52.0,
            top_attackers_names=["ST1", "WG1", "WG2"],
            dependency_level="Moderate",
            top_n_defenders=3, defense_output_share=45.0,
            top_defenders_names=["CB1", "CB2", "FB1"],
        )
        market = compute_model_vs_market("France", "Spain", 55.0, 20.0, 25.0)
        result = compute_confidence(
            self.mc, self.v4, dependency=dep, market_comparison=market, simulations=1000,
        )
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_high_variance_lower_confidence(self):
        volatile_mc = self.mc.__class__(
            wins_a=400, wins_b=350, draws=250, total=1000,
            avg_xg_a=1.5, avg_xg_b=1.4,
            top_scores=[((1, 1), 60), ((2, 2), 55), ((0, 0), 50)],
        )
        result = compute_confidence(volatile_mc)
        self.assertGreaterEqual(result["score"], 0)

    def test_upset_probability(self):
        result = compute_confidence(self.mc)
        self.assertGreaterEqual(result["upset_probability"], 0)
        self.assertLessEqual(result["upset_probability"], 100)

    def test_volatility(self):
        result = compute_confidence(self.mc)
        self.assertGreaterEqual(result["volatility"], 0)
        self.assertLessEqual(result["volatility"], 100)

    def test_confidence_label_variation(self):
        mc_low = self.mc.__class__(
            wins_a=300, wins_b=350, draws=350, total=1000,
            avg_xg_a=1.0, avg_xg_b=1.1,
            top_scores=[((1, 1), 80), ((0, 0), 70), ((2, 1), 60), ((1, 0), 50), ((0, 1), 50)],
        )
        result = compute_confidence(mc_low)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertIn(result["level"], ("Very Low", "Low", "Moderate", "High", "Very High"))


class ValueLevelEdgeCases(unittest.TestCase):
    def test_value_level_strong(self):
        self.assertEqual(ModelVsMarketEntry(team="A", model_prob=50, market_prob=44, edge=0.06).value_level, ValueLevel.STRONG)

    def test_value_level_moderate(self):
        self.assertEqual(ModelVsMarketEntry(team="A", model_prob=50, market_prob=47, edge=0.03).value_level, ValueLevel.MODERATE)

    def test_value_level_no_value(self):
        self.assertEqual(ModelVsMarketEntry(team="A", model_prob=50, market_prob=49, edge=0.01).value_level, ValueLevel.NO_VALUE)

    def test_value_level_negative(self):
        self.assertEqual(ModelVsMarketEntry(team="A", model_prob=30, market_prob=40, edge=-0.10).value_level, ValueLevel.NEGATIVE)


class IntegrationTests(unittest.TestCase):
    def test_end_to_end_player_to_confidence(self):
        from fifa_data.services.simulation_report import MonteCarloResult

        squad_a = _make_squad("France", "4-3-3", 85.0)
        squad_b = _make_squad("Spain", "4-3-3", 75.0)
        report = compute_player_influence("France", "Spain", squad_a, squad_b, 2.2, 1.5)

        self.assertEqual(len(report.offensive_a), 11)
        self.assertEqual(len(report.defensive_b), 11)
        self.assertIsNotNone(report.dependency_a)
        self.assertIsNotNone(report.dependency_b)
        self.assertGreater(len(report.matchups), 0)

        mc = MonteCarloResult(
            wins_a=600, wins_b=200, draws=200, total=1000,
            avg_xg_a=2.0, avg_xg_b=1.2,
            top_scores=[((2, 0), 100), ((1, 0), 90), ((2, 1), 80)],
        )
        from fifa_data.services.market_odds_service import compute_model_vs_market
        market = compute_model_vs_market("France", "Spain", 60.0, 20.0, 20.0)

        result = compute_confidence(
            mc, dependency=report.dependency_a,
            market_comparison=market, simulations=1000,
        )
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertGreater(len(result["factors"]), 0)


if __name__ == "__main__":
    unittest.main()
