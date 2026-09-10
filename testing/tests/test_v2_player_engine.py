from pathlib import Path
import random
import unittest

import numpy as np

from fifa_data.engines.v1_elo_engine import V1EloMatchEngine
from fifa_data.engines.v2_player_engine import V2PlayerMatchEngine
from fifa_data.models.player import Player
from fifa_data.models.team_strength import TeamStrength, build_team_strength, role_for_player, role_rating
from fifa_data.services.simulation_service import run_simulation
from fifa_data.services.v2_data_loader import load_v2_squads


def reference_v1_sim_match(metrics, team1, team2, can_draw=True):
    r1 = (metrics[team1]["ELO"] + metrics[team1]["PELE"]) / 2
    r2 = (metrics[team2]["ELO"] + metrics[team2]["PELE"]) / 2
    raw_delta = r1 - r2
    upset_factor = max(0.4, min(1.6, 1.0 + (raw_delta / 800.0)))
    lam1 = 1.1 * upset_factor
    lam2 = 1.1 * (2.0 - upset_factor)
    g1 = np.random.poisson(max(0.05, lam1))
    g2 = np.random.poisson(max(0.05, lam2))
    if not can_draw and g1 == g2:
        g1_et = np.random.poisson(lam1 * 0.3)
        g2_et = np.random.poisson(lam2 * 0.3)
        if g1_et != g2_et:
            g1 += g1_et
            g2 += g2_et
        else:
            if random.random() < (0.50 + (raw_delta * 0.0005)):
                g1 += 1
            else:
                g2 += 1
    return int(g1), int(g2)


class PlayerRatingTests(unittest.TestCase):
    def test_better_attributes_produce_better_positional_ratings(self):
        strong = Player(
            name="Strong Striker",
            country="Test",
            positions=("FWD",),
            attributes={
                "finishing": 95,
                "positioning": 92,
                "shot_power": 90,
                "pace": 88,
                "composure": 91,
            },
        )
        weak = Player(
            name="Weak Striker",
            country="Test",
            positions=("FWD",),
            attributes={
                "finishing": 55,
                "positioning": 52,
                "shot_power": 50,
                "pace": 58,
                "composure": 51,
            },
        )
        self.assertGreater(role_rating(strong, "ST"), role_rating(weak, "ST"))


class SquadLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.squads = load_v2_squads("fifa_data")

    def test_all_world_cup_teams_have_valid_squads_and_starting_xi(self):
        self.assertEqual(len(self.squads), 48)
        for squad in self.squads.values():
            self.assertGreaterEqual(len(squad.players), 23)
            self.assertEqual(len(squad.current_starting_xi), 11)

    def test_starting_xi_has_no_duplicate_players(self):
        for squad in self.squads.values():
            names = [player.name for player in squad.current_starting_xi]
            self.assertEqual(len(names), len(set(names)))


class LineupLogicTests(unittest.TestCase):
    def test_replacement_logic_selects_appropriate_substitute_without_duplicates(self):
        squads = load_v2_squads(str(Path(__file__).resolve().parents[2] / "fifa_data"))
        squad = squads["France"]
        original_names = {player.name for player in squad.current_starting_xi}
        attacker = next(player for player in squad.current_starting_xi if role_for_player(player, squad.formation) in {"ST", "WINGER"})
        replacement = squad.replace_player(attacker)

        self.assertIsNotNone(replacement)
        self.assertNotIn(replacement.name, original_names)
        self.assertEqual(len(squad.current_starting_xi), 11)
        self.assertEqual(len({player.name for player in squad.current_starting_xi}), 11)
        self.assertIn(role_for_player(replacement, squad.formation), {"ST", "WINGER"})


class TeamStrengthTests(unittest.TestCase):
    def test_stronger_players_create_stronger_team_ratings(self):
        strong_attacker = Player(
            name="Strong Attacker",
            country="Test",
            positions=("FWD",),
            attributes={
                "finishing": 95,
                "positioning": 92,
                "shot_power": 90,
                "pace": 88,
                "composure": 91,
            },
        )
        weak_attacker = Player(
            name="Weak Attacker",
            country="Test",
            positions=("FWD",),
            attributes={
                "finishing": 55,
                "positioning": 52,
                "shot_power": 50,
                "pace": 58,
                "composure": 51,
            },
        )
        strong = self._team_strength(strong_attacker)
        weak = self._team_strength(weak_attacker)
        self.assertGreater(strong.attack_rating, weak.attack_rating)

    def _team_strength(self, attacker):
        gk = Player("GK", "Test", ("GK",), {"reflexes": 80, "diving": 80, "positioning": 80, "handling": 80, "kicking": 80})
        defenders = [
            Player(f"CB{i}", "Test", ("CB",), {"defensive_awareness": 80, "tackling": 80, "strength": 80, "pace": 80, "reactions": 80})
            for i in range(4)
        ]
        midfielders = [
            Player(f"CM{i}", "Test", ("MID",), {"passing": 80, "vision": 80, "dribbling": 80, "stamina": 80, "defending": 80})
            for i in range(3)
        ]
        return build_team_strength("Test", [gk, *defenders, *midfielders, attacker], "4-3-3")


class MatchEngineTests(unittest.TestCase):
    def test_v1_output_matches_reference_formula(self):
        metrics = {
            "A": {"ELO": 2000, "PELE": 2000},
            "B": {"ELO": 1900, "PELE": 1900},
            "C": {"ELO": 1800, "PELE": 1800},
        }
        random.seed(1234)
        np.random.seed(1234)
        reference_scores = [reference_v1_sim_match(metrics, "A", "B", True), reference_v1_sim_match(metrics, "A", "C", False)]
        random.seed(1234)
        np.random.seed(1234)
        engine = V1EloMatchEngine(metrics)
        engine_scores = [engine.simulate_match("A", "B", True), engine.simulate_match("A", "C", False)]
        self.assertEqual(reference_scores, engine_scores)

    def test_stronger_attacks_produce_higher_expected_goals(self):
        engine = V2PlayerMatchEngine(squads={})
        strong = TeamStrength("Strong", "4-3-3", 95, 90, 70, 70, [], {})
        weak = TeamStrength("Weak", "4-3-3", 70, 70, 90, 90, [], {})
        strong_lambda, weak_lambda = engine.expected_goals(strong, weak)
        self.assertGreater(strong_lambda, weak_lambda)

    def test_run_simulation_supports_v1_and_v2_models(self):
        v1_result = run_simulation(model="v1")
        v2_result = run_simulation(model="v2", debug=True)
        self.assertIn("groups", v1_result)
        self.assertIn("groups", v2_result)
        self.assertGreater(len(v2_result.get("debug", [])), 0)


if __name__ == "__main__":
    unittest.main()
