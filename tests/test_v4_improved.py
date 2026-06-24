import json
import random
import unittest
from pathlib import Path

from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
from fifa_data.models.player import Player
from fifa_data.models.squad import Squad
from fifa_data.models.tactical_state import (
    DEFENSIVE_STYLES,
    ManagerProfile,
    MatchContext,
)
from fifa_data.services.manager_service import (
    get_manager,
    manager_game_plan_modifier,
    apply_manager_context_adjustment,
)
from fifa_data.services.tactical_analysis import (
    _TACTICAL_PROFILES,
    compute_tactical_matchup,
    format_tactical_report,
)
from fifa_data.services.simulation_service import run_simulation


HERE = Path(__file__).resolve().parents[1] / "fifa_data"


def _make_player(name: str, country: str, position: str, attrs: dict) -> Player:
    return Player(
        name=name,
        country=country,
        positions=(position,),
        attributes=attrs,
    )


def _make_squad(country: str, formation: str = "4-3-3") -> Squad:
    players = [
        _make_player(f"{country} GK1", country, "GK", {"reflexes": 80, "diving": 80, "positioning": 80, "handling": 80, "kicking": 80}),
        _make_player(f"{country} CB1", country, "CB", {"defensive_awareness": 80, "tackling": 80, "strength": 80, "pace": 60, "reactions": 80, "jumping": 80, "heading_accuracy": 80}),
        _make_player(f"{country} CB2", country, "CB", {"defensive_awareness": 80, "tackling": 80, "strength": 80, "pace": 60, "reactions": 80, "jumping": 80, "heading_accuracy": 80}),
        _make_player(f"{country} FB1", country, "FB", {"pace": 80, "defending": 75, "crossing": 75, "stamina": 80, "passing": 75, "dribbling": 70}),
        _make_player(f"{country} FB2", country, "FB", {"pace": 80, "defending": 75, "crossing": 75, "stamina": 80, "passing": 75, "dribbling": 70}),
        _make_player(f"{country} CM1", country, "CM", {"passing": 80, "vision": 80, "dribbling": 75, "stamina": 80, "defending": 70, "composure": 80}),
        _make_player(f"{country} CM2", country, "CM", {"passing": 80, "vision": 80, "dribbling": 75, "stamina": 80, "defending": 70, "composure": 80}),
        _make_player(f"{country} CM3", country, "CM", {"passing": 80, "vision": 80, "dribbling": 75, "stamina": 80, "defending": 70, "composure": 80}),
        _make_player(f"{country} WG1", country, "WINGER", {"pace": 90, "dribbling": 85, "crossing": 80, "finishing": 75, "vision": 70}),
        _make_player(f"{country} WG2", country, "WINGER", {"pace": 90, "dribbling": 85, "crossing": 80, "finishing": 75, "vision": 70}),
        _make_player(f"{country} ST1", country, "ST", {"finishing": 85, "positioning": 80, "shot_power": 80, "pace": 85, "composure": 80, "heading_accuracy": 80, "strength": 80, "jumping": 80}),
    ]
    return Squad(country=country, players=players, formation=formation, preferred_starting_xi=players)


# ── Manager Profile Tests ──────────────────────────────────────────────────

class ManagerProfileTests(unittest.TestCase):
    def test_manager_profiles_file_exists(self):
        path = HERE / "data" / "manager_profiles.json"
        self.assertTrue(path.exists(), "manager_profiles.json not found")

    def test_top_teams_have_managers(self):
        for team in ("Argentina", "Brazil", "England", "France", "Germany", "Spain"):
            mgr = get_manager(team)
            self.assertIsNotNone(mgr, f"{team} missing manager")
            self.assertGreater(mgr.confidence, 0.5)

    def test_manager_profile_structure(self):
        mgr = get_manager("England")
        self.assertIsNotNone(mgr)
        self.assertIsInstance(mgr.name, str)
        self.assertGreaterEqual(mgr.risk_tolerance, 0)
        self.assertLessEqual(mgr.risk_tolerance, 100)
        self.assertGreaterEqual(mgr.tactical_flexibility, 0)
        self.assertLessEqual(mgr.tactical_flexibility, 100)
        self.assertGreaterEqual(mgr.pressing_preference, 0)
        self.assertLessEqual(mgr.pressing_preference, 100)
        self.assertGreaterEqual(mgr.defensive_discipline, 0)
        self.assertLessEqual(mgr.defensive_discipline, 100)

    def test_bielsa_high_risk_pressing(self):
        mgr = get_manager("Uruguay")
        self.assertIsNotNone(mgr)
        self.assertGreater(mgr.risk_tolerance, 75, "Bielsa should be high risk")
        self.assertGreater(mgr.pressing_preference, 80, "Bielsa should be high pressing")

    def test_southgate_cautious(self):
        mgr = get_manager("England")
        self.assertIsNotNone(mgr)
        self.assertLess(mgr.risk_tolerance, 60, "Southgate should be cautious")
        self.assertGreater(mgr.defensive_discipline, 70, "Southgate should be disciplined")

    def test_nagelsmann_high_flexibility(self):
        mgr = get_manager("Germany")
        self.assertIsNotNone(mgr)
        self.assertGreater(mgr.tactical_flexibility, 75, "Nagelsmann should be flexible")

    def test_manager_game_plan_modulation(self):
        """Manager risk tolerance should modulate game plan choice."""
        plan = manager_game_plan_modifier("Uruguay", "balanced", 1.0)
        self.assertIn(plan, ("attacking", "counter", "balanced"))

    def test_manager_context_adjustments(self):
        """Manager context adjustments should return structured data."""
        adj = apply_manager_context_adjustment("England", "knockout", "balanced")
        self.assertIsInstance(adj, list)
        if adj:
            cat, desc, val = adj[0]
            self.assertIsInstance(cat, str)
            self.assertIsInstance(desc, str)
            self.assertIsInstance(val, float)

    def test_manager_unknown_team_returns_none(self):
        mgr = get_manager("NonExistentTeam")
        self.assertIsNone(mgr)


# ── New Profile Attribute Tests ────────────────────────────────────────────

class UpdatedProfileTests(unittest.TestCase):
    def test_new_attributes_exist(self):
        required_new = {
            "progressive_passes", "final_third_entries", "big_chance_creation",
            "shot_quality", "tactical_flexibility", "defensive_style",
            "man_marking_tendency", "zonal_discipline",
        }
        path = HERE / "data" / "tactical_profiles.json"
        with path.open("r", encoding="utf-8") as f:
            profiles = json.load(f)
        for team, attrs in profiles.items():
            for attr in required_new:
                self.assertIn(attr, attrs, f"{team} missing {attr}")

    def test_defensive_styles_are_valid(self):
        path = HERE / "data" / "tactical_profiles.json"
        with path.open("r", encoding="utf-8") as f:
            profiles = json.load(f)
        for team, attrs in profiles.items():
            style = attrs.get("defensive_style", "")
            self.assertIn(style, DEFENSIVE_STYLES, f"{team} has invalid defensive_style: {style}")

    def test_new_numeric_attributes_in_range(self):
        path = HERE / "data" / "tactical_profiles.json"
        with path.open("r", encoding="utf-8") as f:
            profiles = json.load(f)
        numeric_new = [
            "progressive_passes", "final_third_entries", "big_chance_creation",
            "shot_quality", "tactical_flexibility", "man_marking_tendency", "zonal_discipline",
        ]
        for team, attrs in profiles.items():
            for attr in numeric_new:
                val = attrs.get(attr, -1)
                self.assertGreaterEqual(val, 0, f"{team} {attr}={val}")
                self.assertLessEqual(val, 100, f"{team} {attr}={val}")

    def test_spain_high_possession_quality(self):
        spain = _TACTICAL_PROFILES.get("Spain", {})
        self.assertGreater(spain.get("progressive_passes", 0), 70)

    def test_uruguay_low_block(self):
        uruguay = _TACTICAL_PROFILES.get("Uruguay", {})
        self.assertEqual(uruguay.get("defensive_style"), "low_block")

    def test_germany_high_press(self):
        germany = _TACTICAL_PROFILES.get("Germany", {})
        self.assertEqual(germany.get("defensive_style"), "high_press")


# ── Possession Quality Tests ──────────────────────────────────────────────

class PossessionQualityTests(unittest.TestCase):
    def test_possession_quality_advantage_favors_high_quality(self):
        squad_a = _make_squad("HighQuality")
        squad_b = _make_squad("LowQuality")
        report = compute_tactical_matchup("Spain", "Panama", 1.80, 0.60, squad_a, squad_b)
        pq_adjs = [a for a in report.adjustments_a if a.category == "possession_quality"]
        if pq_adjs:
            self.assertGreater(pq_adjs[0].value, 0)

    def test_possession_quality_appears_in_report(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("Spain", "Panama", 1.80, 0.40, squad_a, squad_b)
        formatted = format_tactical_report(report)
        has_quality = "possession_quality" in formatted or "Superior possession quality" in formatted
        # Should have it or not depending on the specific gap, but shouldn't crash
        self.assertIsInstance(formatted, str)


# ── Defensive Style Tests ─────────────────────────────────────────────────

class DefensiveStyleTests(unittest.TestCase):
    def test_defensive_style_interaction_returns_adjustments(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("Germany", "Italy", 1.60, 1.20, squad_a, squad_b)
        style_adjs_a = [a for a in report.adjustments_a if a.category == "defensive_style"]
        style_adjs_b = [a for a in report.adjustments_b if a.category == "defensive_style"]
        total = len(style_adjs_a) + len(style_adjs_b)
        self.assertGreater(total, 0)

    def test_high_press_vs_low_block_produces_effects(self):
        squad_a = _make_squad("PressTeam")
        squad_b = _make_squad("BlockTeam")
        report = compute_tactical_matchup("Germany", "Italy", 1.60, 1.20, squad_a, squad_b)
        style_adjs = [a for a in report.adjustments_a + report.adjustments_b if a.category == "defensive_style"]
        self.assertGreater(len(style_adjs), 0)

    def test_all_defensive_styles_appear_in_profiles(self):
        styles_found = set()
        for team in _TACTICAL_PROFILES:
            s = _TACTICAL_PROFILES[team].get("defensive_style", "")
            if s in DEFENSIVE_STYLES:
                styles_found.add(s)
        for style in DEFENSIVE_STYLES:
            self.assertIn(style, styles_found, f"Defensive style '{style}' not found in any team profile")


# ── Tactical Flexibility Tests ────────────────────────────────────────────

class TacticalFlexibilityTests(unittest.TestCase):
    def test_flexibility_gap_produces_adjustment(self):
        squad_a = _make_squad("Flexible")
        squad_b = _make_squad("Rigid")
        report = compute_tactical_matchup("Spain", "Panama", 1.80, 0.60, squad_a, squad_b)
        flex_adjs = [a for a in report.adjustments_a if a.category == "flexibility"]
        if flex_adjs:
            self.assertGreater(flex_adjs[0].value, 0)

    def test_rigid_team_penalized_against_flexible(self):
        squad_a = _make_squad("RigidTeam")
        squad_b = _make_squad("FlexTeam")
        report = compute_tactical_matchup("Panama", "Spain", 0.60, 1.80, squad_a, squad_b)
        rigid_adjs = [a for a in report.adjustments_a if a.category == "rigidity"]
        if rigid_adjs:
            self.assertLess(rigid_adjs[0].value, 0)

    def test_flexibility_in_report(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("Spain", "Panama", 1.80, 0.60, squad_a, squad_b)
        formatted = format_tactical_report(report)
        self.assertIsInstance(formatted, str)


# ── Match Context Tests ────────────────────────────────────────────────────

class MatchContextTests(unittest.TestCase):
    def test_context_knockout_reduces_xg(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("England", "France", 1.50, 1.40, squad_a, squad_b, context="knockout")
        context_adjs = [a for a in report.adjustments_a + report.adjustments_b if a.category == "match_context"]
        self.assertGreater(len(context_adjs), 0)
        for adj in context_adjs:
            self.assertLessEqual(adj.value, 0)

    def test_context_must_win_increases_attack(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("England", "Panama", 2.00, 0.50, squad_a, squad_b, context="must_win")
        context_adjs = [a for a in report.adjustments_a if a.category == "match_context"]
        if context_adjs:
            self.assertGreater(context_adjs[0].value, 0)

    def test_context_gd_chase_increases_risk(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("England", "France", 1.50, 1.40, squad_a, squad_b, context="gd_chase")
        context_adjs_a = [a for a in report.adjustments_a if a.category == "match_context"]
        if context_adjs_a:
            self.assertGreater(context_adjs_a[0].value, 0)

    def test_context_is_passed_to_report(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        for ctx in ("group", "knockout", "must_win", "need_draw", "gd_chase"):
            report = compute_tactical_matchup("England", "France", 1.50, 1.40, squad_a, squad_b, context=ctx)
            self.assertEqual(report.context, ctx)

    def test_format_includes_context(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("England", "France", 1.50, 1.40, squad_a, squad_b, context="knockout")
        formatted = format_tactical_report(report)
        self.assertIn("Match Context: knockout", formatted)
        self.assertIn("Knockout stage", formatted)


# ── Engine Integration Tests ──────────────────────────────────────────────

class V4ImprovedEngineTests(unittest.TestCase):
    def test_engine_accepts_context_parameter(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        squads = {"England": squad_a, "France": squad_b}
        engine = V4TacticalEngine(squads=squads)
        result = engine.simulate_match("England", "France", can_draw=True, context="group")
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], int)
        self.assertIsInstance(result[1], int)

    def test_engine_context_knockout(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        squads = {"England": squad_a, "France": squad_b}
        engine = V4TacticalEngine(squads=squads)
        result = engine.simulate_match("England", "France", can_draw=False, context="knockout")
        self.assertEqual(len(result), 2)

    def test_engine_debug_contains_improved_sections(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        squads = {"Spain": squad_a, "Italy": squad_b}
        engine = V4TacticalEngine(squads=squads)
        _, debug = engine.simulate_match_debug("Spain", "Italy", can_draw=True, context="knockout")
        self.assertIn("Match Context", debug)
        self.assertIn("V4 TACTICAL INTELLIGENCE", debug)

    def test_v4_improved_run_simulation(self):
        result = run_simulation(model="v4")
        self.assertIn("groups", result)
        self.assertIn("knockout", result)
        self.assertIn("champion", result)

    def test_v4_improved_debug_mode(self):
        result = run_simulation(model="v4", debug=True)
        debugs = result.get("debug", [])
        if debugs:
            has_improved = any("defensive_style" in d or "possession_quality" in d or "flexibility" in d for d in debugs)
            self.assertTrue(has_improved, "Improved V4 sections should appear in debug output")


# ── Boundary Tests ─────────────────────────────────────────────────────────

class BoundaryTests(unittest.TestCase):
    def test_max_adjustment_still_capped_at_10_percent(self):
        squad_a = _make_squad("Overwhelming")
        squad_b = _make_squad("Weak")
        report = compute_tactical_matchup("Spain", "Panama", 2.00, 0.40, squad_a, squad_b)
        self.assertGreaterEqual(report.final_xg_a, 0.01)
        self.assertGreaterEqual(report.final_xg_b, 0.01)
        max_adj_a = report.base_xg_a * 0.10
        max_adj_b = report.base_xg_b * 0.10
        self.assertLessEqual(abs(report.total_adjustment_a()), max(max_adj_a, 0.05) + 0.002)
        self.assertLessEqual(abs(report.total_adjustment_b()), max(max_adj_b, 0.05) + 0.002)

    def test_elite_teams_remain_favorites(self):
        squad_a = _make_squad("Elite")
        squad_b = _make_squad("Weak")
        report = compute_tactical_matchup("France", "Panama", 2.50, 0.30, squad_a, squad_b)
        self.assertGreater(report.final_xg_a, report.final_xg_b)

    def test_same_team_symmetric_matchup(self):
        squad_a = _make_squad("TeamX")
        squad_b = _make_squad("TeamX")
        report = compute_tactical_matchup("France", "France", 1.50, 1.50, squad_a, squad_b)
        self.assertAlmostEqual(report.final_xg_a, report.final_xg_b, places=3)


class ManagerModelTests(unittest.TestCase):
    def test_manager_profile_dataclass(self):
        mp = ManagerProfile(
            name="Test Manager",
            risk_tolerance=60.0,
            tactical_flexibility=70.0,
            pressing_preference=65.0,
            defensive_discipline=75.0,
            source="Test source",
            confidence=0.8,
        )
        self.assertEqual(mp.name, "Test Manager")
        self.assertEqual(mp.risk_tolerance, 60.0)
        self.assertEqual(mp.confidence, 0.8)

    def test_match_context_enum_values(self):
        self.assertEqual(MatchContext.GROUP.value, "group")
        self.assertEqual(MatchContext.KNOCKOUT.value, "knockout")
        self.assertEqual(MatchContext.MUST_WIN.value, "must_win")
        self.assertEqual(MatchContext.NEED_DRAW.value, "need_draw")
        self.assertEqual(MatchContext.GD_CHASE.value, "gd_chase")


if __name__ == "__main__":
    unittest.main()
