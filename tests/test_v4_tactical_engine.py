import dataclasses
import json
import random
import unittest
from pathlib import Path

import numpy as np

from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
from fifa_data.models.player import Player
from fifa_data.models.squad import Squad
from fifa_data.services.tactical_matchup_service import compute_tactical_matchup, format_tactical_report
from fifa_data.services.formation_service import get_formation_profile, formation_matchup_advantages
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
    """Create a minimal squad for testing with known FC26-style attributes."""
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


class TacticalProfileTests(unittest.TestCase):
    def test_all_48_teams_have_profiles(self):
        path = HERE / "data" / "tactical_profiles.json"
        self.assertTrue(path.exists())
        with path.open("r", encoding="utf-8") as f:
            profiles = json.load(f)
        self.assertEqual(len(profiles), 48)

    def test_all_attributes_are_valid(self):
        path = HERE / "data" / "tactical_profiles.json"
        with path.open("r", encoding="utf-8") as f:
            profiles = json.load(f)
        required = {"possession", "build_up", "directness", "pressing", "counter_press",
                     "counter_attack", "defensive_line", "defensive_compactness", "width",
                     "central_play", "transition_speed", "set_piece_attack", "set_piece_defense",
                     "aerial_strength", "press_resistance"}
        for team, attrs in profiles.items():
            for attr in required:
                self.assertIn(attr, attrs, f"{team} missing {attr}")
                val = attrs[attr]
                self.assertGreaterEqual(val, 0, f"{team} {attr}={val}")
                self.assertLessEqual(val, 100, f"{team} {attr}={val}")


class FormationServiceTests(unittest.TestCase):
    def test_known_formations_return_profile(self):
        for f in ["4-3-3", "4-2-3-1", "4-4-2", "3-4-3", "3-5-2", "5-3-2", "5-4-1"]:
            prof = get_formation_profile(f)
            self.assertEqual(prof.name, f)

    def test_unknown_formation_falls_back(self):
        prof = get_formation_profile("2-3-5")
        self.assertIsNotNone(prof)

    def test_formation_matchup_returns_advantages(self):
        adv_a, adv_b = formation_matchup_advantages("4-3-3", "5-4-1")
        self.assertGreater(len(adv_a), 0)

    def test_balanced_matchup_returns_few_advantages(self):
        adv_a, adv_b = formation_matchup_advantages("4-3-3", "4-3-3")
        self.assertEqual(len(adv_a), 0)
        self.assertEqual(len(adv_b), 0)


class TacticalMatchupTests(unittest.TestCase):
    def test_high_line_exploited_by_pace(self):
        """Fast counter team vs high line should get a measurable increase."""
        squad_a = _make_squad("HighLineTeam")
        squad_b = _make_squad("FastTeam")
        report = compute_tactical_matchup("Spain", "Senegal", 1.50, 1.20, squad_a, squad_b)
        has_high_line_adj = any(
            adj.category == "high_line_exploit"
            for adj in report.adjustments_a + report.adjustments_b
        )
        self.assertTrue(has_high_line_adj)

    def test_strong_press_vs_weak_buildup(self):
        """Pressing team should gain chances vs weak buildup."""
        weak_players = [
            _make_player("WGK", "WeakBuild", "GK", {"reflexes": 70, "diving": 70, "positioning": 70, "handling": 70, "kicking": 70}),
            _make_player("WCB1", "WeakBuild", "CB", {"defensive_awareness": 70, "tackling": 70, "strength": 70, "pace": 60, "reactions": 70}),
            _make_player("WCB2", "WeakBuild", "CB", {"defensive_awareness": 70, "tackling": 70, "strength": 70, "pace": 60, "reactions": 70}),
            _make_player("WFB1", "WeakBuild", "FB", {"pace": 70, "defending": 70, "crossing": 70, "stamina": 70, "passing": 50, "dribbling": 50}),
            _make_player("WFB2", "WeakBuild", "FB", {"pace": 70, "defending": 70, "crossing": 70, "stamina": 70, "passing": 50, "dribbling": 50}),
            _make_player("WCM1", "WeakBuild", "CM", {"passing": 50, "vision": 50, "dribbling": 50, "stamina": 70, "defending": 60, "composure": 50}),
            _make_player("WCM2", "WeakBuild", "CM", {"passing": 50, "vision": 50, "dribbling": 50, "stamina": 70, "defending": 60, "composure": 50}),
            _make_player("WCM3", "WeakBuild", "CM", {"passing": 50, "vision": 50, "dribbling": 50, "stamina": 70, "defending": 60, "composure": 50}),
            _make_player("WWG1", "WeakBuild", "WINGER", {"pace": 70, "dribbling": 60, "crossing": 60, "finishing": 60, "vision": 50}),
            _make_player("WWG2", "WeakBuild", "WINGER", {"pace": 70, "dribbling": 60, "crossing": 60, "finishing": 60, "vision": 50}),
            _make_player("WST1", "WeakBuild", "ST", {"finishing": 60, "positioning": 60, "shot_power": 60, "pace": 65, "composure": 50}),
        ]
        squad_b = Squad(country="WeakBuild", players=weak_players, formation="4-3-3", preferred_starting_xi=weak_players)
        squad_a = _make_squad("PressTeam")

        report = compute_tactical_matchup("Germany", "Panama", 1.80, 0.60, squad_a, squad_b)
        press_adj = [adj for adj in report.adjustments_a if adj.category == "pressing"]
        self.assertGreater(len(press_adj), 0, "Pressing adjustment should exist")

    def test_set_piece_mismatch(self):
        """Strong set-piece team vs weak aerial defense should increase set-piece xG."""
        sp_players = [
            _make_player("SGK", "SPTeam", "GK", {"reflexes": 70, "diving": 70, "positioning": 70, "handling": 70, "kicking": 70}),
            _make_player("SCB1", "SPTeam", "CB", {"defensive_awareness": 70, "tackling": 70, "strength": 80, "pace": 60, "reactions": 70, "jumping": 85, "heading_accuracy": 85}),
            _make_player("SCB2", "SPTeam", "CB", {"defensive_awareness": 70, "tackling": 70, "strength": 80, "pace": 60, "reactions": 70, "jumping": 85, "heading_accuracy": 85}),
            _make_player("SFB1", "SPTeam", "FB", {"pace": 70, "defending": 70, "crossing": 85, "stamina": 80, "passing": 75, "dribbling": 70}),
            _make_player("SFB2", "SPTeam", "FB", {"pace": 70, "defending": 70, "crossing": 85, "stamina": 80, "passing": 75, "dribbling": 70}),
            _make_player("SCM1", "SPTeam", "CM", {"passing": 80, "vision": 80, "dribbling": 75, "stamina": 80, "defending": 70, "composure": 80}),
            _make_player("SCM2", "SPTeam", "CM", {"passing": 80, "vision": 80, "dribbling": 75, "stamina": 80, "defending": 70, "composure": 80}),
            _make_player("SCM3", "SPTeam", "CM", {"passing": 80, "vision": 80, "dribbling": 75, "stamina": 80, "defending": 70, "composure": 80}),
            _make_player("SWG1", "SPTeam", "WINGER", {"pace": 70, "dribbling": 70, "crossing": 85, "finishing": 70, "vision": 80}),
            _make_player("SWG2", "SPTeam", "WINGER", {"pace": 70, "dribbling": 70, "crossing": 85, "finishing": 70, "vision": 80}),
            _make_player("SST1", "SPTeam", "ST", {"finishing": 80, "positioning": 80, "shot_power": 80, "pace": 70, "composure": 80, "heading_accuracy": 88, "strength": 85, "jumping": 88}),
        ]
        squad_a = Squad(country="SPTeam", players=sp_players, formation="4-3-3", preferred_starting_xi=sp_players)
        squad_b = _make_squad("WeakSP")
        report = compute_tactical_matchup("England", "Panama", 1.60, 0.70, squad_a, squad_b)
        sp_adj = [adj for adj in report.adjustments_a if adj.category == "set_pieces"]
        self.assertGreater(len(sp_adj), 0, "Set-piece adjustment should exist")

    def test_possession_vs_low_block(self):
        """Possession team vs low block should get creativity-based adjustment."""
        squad_a = _make_squad("PossessionTeam")
        squad_b = _make_squad("LowBlockTeam")
        report = compute_tactical_matchup("Spain", "Tunisia", 1.90, 0.60, squad_a, squad_b)
        poss_adj = [adj for adj in report.adjustments_a if adj.category == "possession_creativity"]
        self.assertGreater(len(poss_adj), 0)

    def test_adjustments_stay_within_10_percent(self):
        """Tactical adjustments should respect ±10% xG cap."""
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("France", "Panama", 2.00, 0.40, squad_a, squad_b)
        self.assertGreaterEqual(report.final_xg_a, 0.01)
        self.assertGreaterEqual(report.final_xg_b, 0.01)
        max_adj_a = report.base_xg_a * 0.10
        max_adj_b = report.base_xg_b * 0.10
        self.assertLessEqual(abs(report.total_adjustment_a()), max(max_adj_a, 0.05) + 0.001)
        self.assertLessEqual(abs(report.total_adjustment_b()), max(max_adj_b, 0.05) + 0.001)

    def test_balanced_matchup_minimal_adjustments(self):
        """Two similar teams should get minimal tactical adjustments."""
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("France", "England", 1.50, 1.40, squad_a, squad_b)
        total_adj = abs(report.total_adjustment_a()) + abs(report.total_adjustment_b())
        self.assertLess(total_adj, 0.30)

    def test_elite_teams_remain_favorites_after_tactical_adjustments(self):
        """Elite teams should still be favorites after tactical adjustments."""
        squad_a = _make_squad("Elite")
        squad_b = _make_squad("Weak")
        report = compute_tactical_matchup("France", "Panama", 2.50, 0.30, squad_a, squad_b)
        self.assertGreater(report.final_xg_a, report.final_xg_b)


class TacticalReportFormatTests(unittest.TestCase):
    def test_format_tactical_report_returns_string(self):
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        report = compute_tactical_matchup("France", "England", 1.50, 1.40, squad_a, squad_b)
        formatted = format_tactical_report(report)
        self.assertIsInstance(formatted, str)
        self.assertIn("Tactical Matchup Report", formatted)
        self.assertIn("France", formatted)
        self.assertIn("England", formatted)
        self.assertIn("Final xG", formatted)


class V4EngineTests(unittest.TestCase):
    def test_v4_expected_goals_directly(self):
        """Test expected goals with squads passed directly to engine."""
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        squads = {"France": squad_a, "England": squad_b}
        engine = V4TacticalEngine(squads=squads)
        xg1, xg2 = engine.expected_goals("France", "England")
        self.assertGreater(xg1, 0)
        self.assertGreater(xg2, 0)

    def test_v4_simulation_with_squads(self):
        """Test V4 simulate_match with squads passed directly."""
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        squads = {"France": squad_a, "England": squad_b}
        engine = V4TacticalEngine(squads=squads)
        result = engine.simulate_match("France", "England", can_draw=True)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], int)
        self.assertIsInstance(result[1], int)

    def test_v4_debug_contains_tactical_section(self):
        """Debug output should contain V4 tactical intelligence."""
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        squads = {"Spain": squad_a, "Morocco": squad_b}
        engine = V4TacticalEngine(squads=squads)
        _, debug = engine.simulate_match_debug("Spain", "Morocco", can_draw=True)
        self.assertIn("V4 TACTICAL INTELLIGENCE", debug)

    def test_v4_run_simulation(self):
        """Full V4 tournament simulation should execute."""
        result = run_simulation(model="v4")
        self.assertIn("groups", result)
        self.assertIn("knockout", result)
        self.assertIn("champion", result)

    def test_v4_debug_mode_contains_tactical_data(self):
        """Debug mode results should contain tactical data."""
        result = run_simulation(model="v4", debug=True)
        debugs = result.get("debug", [])
        if debugs:
            has_tactical = any("V4 TACTICAL INTELLIGENCE" in d for d in debugs)
            self.assertTrue(has_tactical)

    def test_knockout_match_with_squads(self):
        """Knockout match should resolve to a winner."""
        squad_a = _make_squad("TeamA")
        squad_b = _make_squad("TeamB")
        squads = {"France": squad_a, "England": squad_b}
        engine = V4TacticalEngine(squads=squads)
        result = engine.simulate_match("France", "England", can_draw=False)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
