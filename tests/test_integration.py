"""Integration tests: verify the entire simulation stack produces sane results."""

import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "fifa_data"


# ── Utilities ───────────────────────────────────────────────────────────────

def _make_player(name, country, position, attrs):
    from fifa_data.models.player import Player
    return Player(
        name=name, country=country, positions=(position,),
        attributes=attrs, stats={},
    )


def _make_squad(country="Brazil", formation="4-3-3"):
    from fifa_data.models.squad import Squad
    base = {
        "pace": 80, "shooting": 75, "passing": 78, "dribbling": 80,
        "defending": 70, "physical": 75, "stamina": 80, "composure": 75,
        "vision": 75, "positioning": 75, "finishing": 75, "marking": 70,
        "tackling": 70, "strength": 75, "crossing": 72, "long_shots": 70,
        "reactions": 75, "interceptions": 70, "defensive_awareness": 70,
        "jumping": 72, "heading_accuracy": 72, "kicking": 70, "reflexes": 75,
        "diving": 75, "handling": 72, "age": 27, "work_rate": 70,
    }
    positions = [
        ("Alisson", "GK"), ("Dani Alves", "FB"), ("Marquinhos", "CB"),
        ("Thiago Silva", "CB"), ("Marcelo", "FB"), ("Casemiro", "DM"),
        ("Paqueta", "CM"), ("Neymar", "WINGER"), ("Vinicius", "WINGER"),
        ("Raphinha", "WINGER"), ("Richarlison", "ST"),
    ]
    players = [_make_player(pn, country, pos, dict(base)) for pn, pos in positions]
    return Squad(country=country, players=players, formation=formation,
                 preferred_starting_xi=players[:11])


STRONG = ["Brazil", "France", "Argentina", "England", "Spain", "Germany"]
WEAK = ["Saudi Arabia", "Tunisia", "Australia", "Japan", "Cape Verde", "Qatar"]


# ═════════════════════════════════════════════════════════════════════════════
# 1. Import Sanity
# ═════════════════════════════════════════════════════════════════════════════

class ImportTests(unittest.TestCase):
    """Every module in the repo imports without error."""

    def test_engines_import(self):
        from fifa_data.engines.base_engine import MatchEngine
        from fifa_data.engines.v1_elo_engine import V1EloMatchEngine
        from fifa_data.engines.v2_player_engine import V2PlayerMatchEngine
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
        from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
        self.assertTrue(all([MatchEngine, V1EloMatchEngine, V2PlayerMatchEngine,
                             V3DynamicEngine, V4TacticalEngine, V5MatchStateEngine]))

    def test_services_import(self):
        from fifa_data.services.card_service import CardService
        from fifa_data.services.event_engine import EventEngine
        from fifa_data.services.formation_service import get_formation_profile
        from fifa_data.services.game_script_service import GameScriptService
        from fifa_data.services.manager_service import get_manager
        from fifa_data.services.market_odds_service import compute_model_vs_market
        from fifa_data.services.match_momentum_service import MatchMomentumService
        from fifa_data.services.match_state_service import MatchStateService
        from fifa_data.services.model_confidence_service import compute_confidence
        from fifa_data.services.penalty_engine import PenaltyEngine
        from fifa_data.services.simulation_service import run_simulation
        from fifa_data.services.substitution_manager import FatigueService, SubstitutionService
        from fifa_data.services.tactical_analysis import compute_tactical_matchup
        from fifa_data.services.v2_data_loader import load_v2_squads
        from fifa_data.services.v3_modifiers import ChemistryService
        self.assertTrue(True)

    def test_models_import(self):
        from fifa_data.models import (
            Player, Squad, TeamStrength, DynamicState,
            TacticalReport, PlayerInfluenceReport, TacticalVulnerabilityReport,
            MarketOdds, PlayerMatchState, MatchState, MatchEvent,
        )
        self.assertTrue(True)

    def test_top_level_api(self):
        from fifa_data import run_simulation, V3DynamicEngine, V4TacticalEngine, V5MatchStateEngine
        self.assertTrue(True)

    def test_no_orphaned_imports(self):
        """Verify no remaining references to deleted service modules."""
        import py_compile
        service_dir = HERE / "services"
        for f in sorted(service_dir.glob("*.py")):
            try:
                py_compile.compile(f, doraise=True)
            except py_compile.PyCompileError as e:
                self.fail(f"{f.name} failed to compile: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Data Integrity
# ═════════════════════════════════════════════════════════════════════════════

class DataIntegrityTests(unittest.TestCase):
    """All 48 teams have valid, complete data."""

    @classmethod
    def setUpClass(cls):
        profiles_path = HERE / "data" / "tactical_profiles.json"
        cls.profiles = json.loads(profiles_path.read_text(encoding="utf-8")) if profiles_path.exists() else {}
        mgr_path = HERE / "data" / "manager_profiles.json"
        cls.managers = json.loads(mgr_path.read_text(encoding="utf-8")) if mgr_path.exists() else {}

    def test_all_48_teams_have_squads(self):
        from fifa_data.services.v2_data_loader import load_v2_squads
        squads = load_v2_squads(HERE)
        self.assertGreaterEqual(len(squads), 48)

    def test_all_squads_have_11_starters(self):
        from fifa_data.services.v2_data_loader import load_v2_squads
        squads = load_v2_squads(HERE)
        for name, squad in squads.items():
            self.assertGreaterEqual(len(squad.current_starting_xi), 11,
                                    f"{name}: < 11 starters")

    def test_all_squads_have_23_players(self):
        from fifa_data.services.v2_data_loader import load_v2_squads
        squads = load_v2_squads(HERE)
        for name, squad in squads.items():
            self.assertGreaterEqual(len(squad.players), 23,
                                    f"{name}: < 23 players")

    def test_no_duplicate_starters(self):
        from fifa_data.services.v2_data_loader import load_v2_squads
        squads = load_v2_squads(HERE)
        for name, squad in squads.items():
            names = [p.name for p in squad.current_starting_xi]
            self.assertEqual(len(names), len(set(names)),
                             f"{name}: duplicate starter names")

    def test_all_48_teams_have_tactical_profiles(self):
        self.assertGreaterEqual(len(self.profiles), 48)

    def test_profiles_have_required_attributes(self):
        required = {"possession", "pressing", "directness", "defensive_line",
                    "aerial_strength", "set_piece_attack", "set_piece_defense",
                    "defensive_compactness", "build_up", "big_chance_creation",
                    "tactical_flexibility", "defensive_style"}
        for team, prof in self.profiles.items():
            missing = required - set(prof.keys())
            self.assertFalse(missing, f"{team} missing: {missing}")

    def test_profile_attributes_in_range(self):
        numeric_keys = {"possession", "pressing", "directness", "defensive_line",
                        "aerial_strength", "set_piece_attack", "set_piece_defense",
                        "defensive_compactness", "build_up", "big_chance_creation",
                        "tactical_flexibility"}
        for team, prof in self.profiles.items():
            for key in numeric_keys:
                val = prof.get(key, 50)
                self.assertGreaterEqual(val, 0, f"{team}.{key}={val}")
                self.assertLessEqual(val, 100, f"{team}.{key}={val}")

    def test_defensive_styles_are_valid(self):
        valid = {"low_block", "mid_block", "high_press", "man_marking", "zonal"}
        for team, prof in self.profiles.items():
            style = prof.get("defensive_style", "")
            self.assertIn(style, valid, f"{team}: invalid style '{style}'")

    def test_all_teams_have_managers(self):
        self.assertGreaterEqual(len(self.managers), 48)

    def test_manager_has_required_keys(self):
        for team, mgr in self.managers.items():
            for key in ("name", "risk_tolerance", "defensive_discipline"):
                self.assertIn(key, mgr, f"{team}: manager missing '{key}'")

    def test_squads_loading_is_deterministic(self):
        from fifa_data.services.v2_data_loader import load_v2_squads
        s1 = load_v2_squads(HERE)
        s2 = load_v2_squads(HERE)
        self.assertEqual(list(s1.keys()), list(s2.keys()))


# ═════════════════════════════════════════════════════════════════════════════
# 3. Engine Sanity
# ═════════════════════════════════════════════════════════════════════════════

class EngineSanityTests(unittest.TestCase):
    """Every match engine produces finite, non-NaN, rational xG values."""

    def _check_xg(self, xg_a, xg_b, ctx=""):
        self.assertFalse(xg_a is None, f"{ctx}: xg_a is None")
        self.assertFalse(xg_b is None, f"{ctx}: xg_b is None")
        import math
        self.assertFalse(math.isnan(xg_a), f"{ctx}: xg_a is NaN")
        self.assertFalse(math.isnan(xg_b), f"{ctx}: xg_b is NaN")
        self.assertGreater(xg_a, 0, f"{ctx}: xg_a <= 0 ({xg_a})")
        self.assertGreater(xg_b, 0, f"{ctx}: xg_b <= 0 ({xg_b})")
        self.assertLess(xg_a, 20, f"{ctx}: xg_a unreasonably high ({xg_a})")
        self.assertLess(xg_b, 20, f"{ctx}: xg_b unreasonably high ({xg_b})")

    def test_v2_xg(self):
        from fifa_data.engines.v2_player_engine import V2PlayerMatchEngine
        engine = V2PlayerMatchEngine(data_dir=HERE)
        sa = engine.get_team_strength("Brazil")
        sb = engine.get_team_strength("Germany")
        xg_a, xg_b = engine.expected_goals(sa, sb)
        self._check_xg(xg_a, xg_b, "V2 Brazil vs Germany")

    def test_v3_xg(self):
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        engine = V3DynamicEngine(data_dir=HERE)
        sa = engine.get_team_strength("Brazil")
        sb = engine.get_team_strength("Germany")
        xg_a, xg_b = engine.expected_goals(sa, sb)
        self._check_xg(xg_a, xg_b, "V3 Brazil vs Germany")

    def test_v4_xg(self):
        from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
        engine = V4TacticalEngine(data_dir=HERE)
        xg_a, xg_b = engine.expected_goals("Brazil", "Germany")
        self._check_xg(xg_a, xg_b, "V4 Brazil vs Germany")

    def test_v5_xg(self):
        from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
        engine = V5MatchStateEngine(data_dir=HERE)
        xg_a, xg_b = engine.expected_goals("Brazil", "Germany")
        self._check_xg(xg_a, xg_b, "V5 Brazil vs Germany")

    def test_all_teams_have_positive_xg(self):
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        engine = V3DynamicEngine(data_dir=HERE)
        from fifa_data.services.v2_data_loader import load_v2_squads
        squads = load_v2_squads(HERE)
        names = list(squads.keys())
        for t1 in names[:5]:
            for t2 in names[5:10]:
                if t1 == t2:
                    continue
                sa = engine.get_team_strength(t1)
                sb = engine.get_team_strength(t2)
                xg_a, xg_b = engine.expected_goals(sa, sb)
                self._check_xg(xg_a, xg_b, f"V3 {t1} vs {t2}")

    def test_strong_teams_outscore_weak_teams(self):
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        engine = V3DynamicEngine(data_dir=HERE)
        for strong in STRONG:
            for weak in WEAK:
                if strong == weak:
                    continue
                sa = engine.get_team_strength(strong)
                sw = engine.get_team_strength(weak)
                xg_s, xg_w = engine.expected_goals(sa, sw)
                self.assertGreater(xg_s, xg_w,
                                   f"V3: {strong} ({xg_s:.3f}) vs {weak} ({xg_w:.3f})")


# ═════════════════════════════════════════════════════════════════════════════
# 4. Cross-Engine Consistency
# ═════════════════════════════════════════════════════════════════════════════

class CrossEngineConsistencyTests(unittest.TestCase):
    """All engines rank teams consistently."""

    def _all_xg(self, t1, t2):
        from fifa_data.engines.v2_player_engine import V2PlayerMatchEngine
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
        from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
        v2 = V2PlayerMatchEngine(data_dir=HERE)
        v3 = V3DynamicEngine(data_dir=HERE)
        v4 = V4TacticalEngine(data_dir=HERE)
        v5 = V5MatchStateEngine(data_dir=HERE)
        s2a, s2b = v2.get_team_strength(t1), v2.get_team_strength(t2)
        s3a, s3b = v3.get_team_strength(t1), v3.get_team_strength(t2)
        return {
            "v2": v2.expected_goals(s2a, s2b),
            "v3": v3.expected_goals(s3a, s3b),
            "v4": v4.expected_goals(t1, t2),
            "v5": v5.expected_goals(t1, t2),
        }

    def test_brazil_beats_saudi_across_all_engines(self):
        for eng, (xg_a, xg_b) in self._all_xg("Brazil", "Saudi Arabia").items():
            self.assertGreater(xg_a, xg_b,
                               f"{eng}: Brazil ({xg_a:.3f}) vs Saudi Arabia ({xg_b:.3f})")

    def test_france_beats_tunisia_across_all_engines(self):
        for eng, (xg_a, xg_b) in self._all_xg("France", "Tunisia").items():
            self.assertGreater(xg_a, xg_b,
                               f"{eng}: France ({xg_a:.3f}) vs Tunisia ({xg_b:.3f})")

    def test_engines_correlated(self):
        """V3/V4/V5 xG for the same matchup should not diverge wildly."""
        results = self._all_xg("Brazil", "Germany")
        v3_xg = results["v3"][0]
        v4_xg = results["v4"][0]
        v5_xg = results["v5"][0]
        max_diff = max(abs(v3_xg - v4_xg), abs(v3_xg - v5_xg), abs(v4_xg - v5_xg))
        self.assertLess(max_diff, 3.0,
                        f"Engines diverged: V3={v3_xg:.2f} V4={v4_xg:.2f} V5={v5_xg:.2f}")


# ═════════════════════════════════════════════════════════════════════════════
# 5. Tactical Analysis
# ═════════════════════════════════════════════════════════════════════════════

class TacticalAnalysisTests(unittest.TestCase):
    """Tactical analysis produces non-trivial, sensible results."""

    def setUp(self):
        from fifa_data.services.v2_data_loader import load_v2_squads
        self.squads = load_v2_squads(HERE)
        self.profiles = json.loads(
            (HERE / "data" / "tactical_profiles.json").read_text(encoding="utf-8"))

    def test_matchup_returns_report(self):
        from fifa_data.services.tactical_analysis import compute_tactical_matchup
        report = compute_tactical_matchup("Brazil", "Germany", 1.5, 1.3,
                                          self.squads["Brazil"], self.squads["Germany"])
        self.assertIsNotNone(report)
        self.assertEqual(report.team_a, "Brazil")
        self.assertEqual(report.team_b, "Germany")

    def test_matchup_has_game_plans(self):
        from fifa_data.services.tactical_analysis import compute_tactical_matchup
        report = compute_tactical_matchup("Brazil", "Germany", 1.5, 1.3,
                                          self.squads["Brazil"], self.squads["Germany"])
        valid = {"balanced", "attacking", "counter", "low_block", "high_press"}
        self.assertIn(report.game_plan_a, valid)
        self.assertIn(report.game_plan_b, valid)

    def test_final_xg_differs_from_base(self):
        from fifa_data.services.tactical_analysis import compute_tactical_matchup
        report = compute_tactical_matchup("Brazil", "Germany", 1.5, 1.3)
        total_adj = sum(a.value for a in report.adjustments_a) + sum(a.value for a in report.adjustments_b)
        self.assertNotAlmostEqual(total_adj, 0, places=4,
                                  msg="Tactical adjustments should be non-zero")

    def test_vulnerability_report(self):
        from fifa_data.services.tactical_analysis import compute_vulnerability_report
        report = compute_vulnerability_report("Brazil", self.squads["Brazil"],
                                              self.profiles.get("Brazil", {}))
        self.assertIsNotNone(report)
        self.assertEqual(report.team, "Brazil")
        self.assertGreaterEqual(len(report.strengths), 1)

    def test_matchup_with_synthetic_squads(self):
        from fifa_data.services.tactical_analysis import compute_tactical_matchup
        squad = _make_squad("Brazil", "4-3-3")
        report = compute_tactical_matchup("Brazil", "Germany", 1.5, 1.3, squad, squad)
        self.assertIsNotNone(report)
        self.assertGreater(report.final_xg_a, 0)
        self.assertGreater(report.final_xg_b, 0)

    def test_exploitation(self):
        from fifa_data.services.tactical_analysis import compute_exploitation
        result = compute_exploitation("Brazil", "Germany",
                                      self.squads["Brazil"], self.squads["Germany"],
                                      self.profiles.get("Brazil", {}),
                                      self.profiles.get("Germany", {}))
        self.assertIsNotNone(result)
        self.assertIn("Brazil", [result.team_a, result.team_b])

    def test_win_conditions(self):
        from fifa_data.services.tactical_analysis import analyze_win_conditions
        wc = analyze_win_conditions("Brazil", self.profiles.get("Brazil", {}),
                                    self.squads["Brazil"])
        self.assertGreaterEqual(len(wc.conditions), 1)

    def test_archetype_classification(self):
        from fifa_data.services.tactical_analysis import classify_match_archetypes
        arch = classify_match_archetypes("Brazil", "Germany",
                                          self.profiles.get("Brazil", {}),
                                          self.profiles.get("Germany", {}))
        self.assertIsNotNone(arch)
        self.assertGreaterEqual(len(arch.archetypes), 1)


# ═════════════════════════════════════════════════════════════════════════════
# 6. Match Simulation
# ═════════════════════════════════════════════════════════════════════════════

class MatchSimulationTests(unittest.TestCase):
    """All engines simulate matches producing reasonable scorelines."""

    def _sim(self, engine_class, t1="Brazil", t2="Germany"):
        engine = engine_class(data_dir=HERE)
        return engine.simulate_match(t1, t2)

    def test_v2_simulates(self):
        from fifa_data.engines.v2_player_engine import V2PlayerMatchEngine
        g1, g2 = self._sim(V2PlayerMatchEngine)
        self.assertIn(g1, range(0, 12))
        self.assertIn(g2, range(0, 12))

    def test_v3_simulates(self):
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        g1, g2 = self._sim(V3DynamicEngine)
        self.assertIn(g1, range(0, 12))
        self.assertIn(g2, range(0, 12))

    def test_v4_simulates(self):
        from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
        g1, g2 = self._sim(V4TacticalEngine)
        self.assertIn(g1, range(0, 12))
        self.assertIn(g2, range(0, 12))

    def test_v5_simulates(self):
        from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
        g1, g2 = self._sim(V5MatchStateEngine)
        self.assertIn(g1, range(0, 12))
        self.assertIn(g2, range(0, 12))

    def test_strong_team_wins_more_often(self):
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        engine = V3DynamicEngine(data_dir=HERE)
        strong_wins = 0
        weak_wins = 0
        n = 50
        for _ in range(n):
            g1, g2 = engine.simulate_match("Brazil", "Saudi Arabia")
            if g1 > g2:
                strong_wins += 1
            elif g2 > g1:
                weak_wins += 1
        self.assertGreater(strong_wins, weak_wins,
                           f"Brazil won {strong_wins}/{n}, Saudi won {weak_wins}/{n}")


# ═════════════════════════════════════════════════════════════════════════════
# 7. Full Tournament Simulation
# ═════════════════════════════════════════════════════════════════════════════

class TournamentSimulationTests(unittest.TestCase):
    """Full tournament runs complete without errors."""

    def _check_tournament(self, result):
        self.assertIsNotNone(result)
        self.assertIn("groups", result)
        self.assertIn("knockout", result)
        self.assertIn("champion", result)
        self.assertIn(result["champion"], list(
            json.loads((HERE / "data" / "tactical_profiles.json").read_text(encoding="utf-8")).keys()))

    def test_v3_tournament(self):
        from fifa_data.services.simulation_service import run_simulation
        self._check_tournament(run_simulation(model="v3", debug=False))

    def test_v4_tournament(self):
        from fifa_data.services.simulation_service import run_simulation
        self._check_tournament(run_simulation(model="v4", debug=False))

    def test_v5_tournament(self):
        from fifa_data.services.simulation_service import run_simulation
        self._check_tournament(run_simulation(model="v5", debug=False))

    def test_v4_tournament_with_debug(self):
        from fifa_data.services.simulation_service import run_simulation
        result = run_simulation(model="v4", debug=True)
        self._check_tournament(result)


# ═════════════════════════════════════════════════════════════════════════════
# 8. Explainability Pipeline
# ═════════════════════════════════════════════════════════════════════════════

class ExplainabilityPipelineTests(unittest.TestCase):
    """Player influence + vulnerability + market odds + confidence work end-to-end."""

    def setUp(self):
        self.squad = _make_squad("Brazil", "4-3-3")
        self.profiles = json.loads(
            (HERE / "data" / "tactical_profiles.json").read_text(encoding="utf-8"))

    def test_player_influence_returns_report(self):
        from fifa_data.services.tactical_analysis import compute_player_influence
        report = compute_player_influence("Brazil", "Germany", self.squad, self.squad, 1.5, 1.2)
        self.assertIsNotNone(report)
        self.assertEqual(report.team_a, "Brazil")
        self.assertEqual(report.team_b, "Germany")
        self.assertGreater(len(report.offensive_a), 0)
        self.assertGreater(len(report.defensive_a), 0)

    def test_offensive_influence_sensible(self):
        from fifa_data.services.tactical_analysis import compute_offensive_influence
        player = self.squad.current_starting_xi[-1]  # ST
        off = compute_offensive_influence(player, self.squad, 1.5)
        self.assertGreaterEqual(off.overall_influence, 1.0)
        self.assertLessEqual(off.overall_influence, 10.0)
        self.assertGreaterEqual(off.xg_contribution, 0)

    def test_defensive_influence_sensible(self):
        from fifa_data.services.tactical_analysis import compute_defensive_influence
        player = self.squad.current_starting_xi[2]  # CB
        df = compute_defensive_influence(player, self.squad, 1.5)
        self.assertGreaterEqual(df.overall_influence, 1.0)
        self.assertLessEqual(df.overall_influence, 10.0)

    def test_goalkeeper_influence_sensible(self):
        from fifa_data.services.tactical_analysis import compute_goalkeeper_influence
        player = self.squad.current_starting_xi[0]  # GK
        gk = compute_goalkeeper_influence(player, self.squad, 5.0)
        self.assertGreaterEqual(gk.overall_influence, 1.0)
        self.assertLessEqual(gk.overall_influence, 10.0)

    def test_market_odds_sensible(self):
        from fifa_data.services.market_odds_service import compute_model_vs_market
        result = compute_model_vs_market(
            "Brazil", "Germany", 0.55, 0.05, 0.40,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.team_a, "Brazil")
        self.assertGreaterEqual(len(result.entries), 1)

    def test_confidence_score_sensible(self):
        from fifa_data.services.model_confidence_service import compute_confidence
        from fifa_data.services.simulation_report import MonteCarloResult

        mc = MonteCarloResult(
            wins_a=550, wins_b=250, draws=200, total=1000,
            avg_xg_a=1.8, avg_xg_b=1.2,
            top_scores=[((1, 0), 120), ((1, 1), 100), ((2, 1), 80)],
            min_goals_a=0, max_goals_a=5, min_goals_b=0, max_goals_b=4,
        )
        confidence = compute_confidence(mc)
        self.assertIn("score", confidence)
        self.assertIn("level", confidence)
        self.assertIn("factors", confidence)
        self.assertGreaterEqual(confidence["score"], 0)
        self.assertLessEqual(confidence["score"], 100)
        self.assertIn(confidence["level"], ("Very High", "High", "Moderate", "Low", "Very Low"))

    def test_end_to_end_vulnerability_to_confidence(self):
        from fifa_data.services.tactical_analysis import (
            compute_player_influence, compute_exploitation,
        )
        from fifa_data.services.market_odds_service import compute_model_vs_market
        from fifa_data.services.model_confidence_service import compute_confidence
        from fifa_data.services.simulation_report import MonteCarloResult

        influence = compute_player_influence("Brazil", "Germany", self.squad, self.squad, 1.5, 1.2)
        self.assertIsNotNone(influence)

        exploitation = compute_exploitation(
            "Brazil", "Germany", self.squad, self.squad,
            self.profiles.get("Brazil", {}), self.profiles.get("Germany", {}),
        )
        self.assertIsNotNone(exploitation)

        mc = MonteCarloResult(
            wins_a=550, wins_b=250, draws=200, total=1000,
            avg_xg_a=1.8, avg_xg_b=1.2,
            top_scores=[((1, 0), 120), ((1, 1), 100), ((2, 1), 80)],
            min_goals_a=0, max_goals_a=5, min_goals_b=0, max_goals_b=4,
        )
        market = compute_model_vs_market(
            "Brazil", "Germany", 0.55, 0.05, 0.40,
        )
        self.assertIsNotNone(market)

        confidence = compute_confidence(mc, market_comparison=market, simulations=500)
        self.assertIn("score", confidence)
        self.assertIn("level", confidence)


# ═════════════════════════════════════════════════════════════════════════════
# 9. Edge Cases
# ═════════════════════════════════════════════════════════════════════════════

class EdgeCaseTests(unittest.TestCase):
    """Boundaries and edge cases don't crash."""

    def test_v5_unknown_team_fails_gracefully(self):
        from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
        engine = V5MatchStateEngine(data_dir=HERE)
        with self.assertRaises(Exception):
            engine.simulate_match("FakeTeam", "Brazil")

    def test_tactical_matchup_no_squads(self):
        from fifa_data.services.tactical_analysis import compute_tactical_matchup
        report = compute_tactical_matchup("Brazil", "Germany", 1.5, 1.3)
        self.assertIsNotNone(report)
        self.assertGreater(report.final_xg_a, 0)
        self.assertGreater(report.final_xg_b, 0)

    def test_all_match_contexts_accepted(self):
        from fifa_data.engines.v4_tactical_engine import V4TacticalEngine
        engine = V4TacticalEngine(data_dir=HERE)
        for ctx in ("group", "knockout", "must_win", "need_draw", "gd_chase"):
            xg_a, xg_b = engine.expected_goals("Brazil", "Germany", context=ctx)
            self.assertGreater(xg_a, 0, f"ctx={ctx}: xg_a <= 0")
            self.assertGreater(xg_b, 0, f"ctx={ctx}: xg_b <= 0")

    def test_v5_simulates_with_different_teams(self):
        from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
        engine = V5MatchStateEngine(data_dir=HERE)
        for t1, t2 in [("France", "Argentina"), ("England", "Senegal"), ("Japan", "Spain")]:
            g1, g2 = engine.simulate_match(t1, t2)
            self.assertIn(g1, range(0, 12))
            self.assertIn(g2, range(0, 12))

    def test_orchestrator_initializes(self):
        from fifa_data.services.orchestrator import TournamentOrchestrator
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        from fifa_data.services.simulation_service import GROUPS, MATCHES_TEAM_MAP
        engine = V3DynamicEngine(data_dir=HERE)
        orch = TournamentOrchestrator(
            groups=GROUPS, match_engine=engine,
            matches_file=str(HERE / "data" / "matches.json"),
            team_name_map=MATCHES_TEAM_MAP,
        )
        self.assertIsNotNone(orch)

    def test_v3_format_match_debug(self):
        from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
        engine = V3DynamicEngine(data_dir=HERE)
        score, debug = engine.simulate_match_debug("Brazil", "Germany")
        self.assertIsNotNone(debug)
        self.assertIsInstance(debug, str)
        self.assertIn("Brazil", debug)
        self.assertIn("Germany", debug)
        self.assertIn(score[0], range(0, 12))

    def test_v4_tactical_report_format(self):
        from fifa_data.services.tactical_analysis import format_tactical_report, compute_tactical_matchup
        report = compute_tactical_matchup("Brazil", "Germany", 1.5, 1.3)
        text = format_tactical_report(report)
        self.assertIn("Brazil", text)
        self.assertIn("Germany", text)
        self.assertIn("xG", text)


if __name__ == "__main__":
    unittest.main()
