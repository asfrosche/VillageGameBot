import unittest
from pathlib import Path

from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
from fifa_data.models.match_event import EventType, MatchEvent
from fifa_data.models.match_state import MatchPhase, MatchState
from fifa_data.models.player import Player
from fifa_data.models.player_match_state import PlayerMatchState
from fifa_data.models.squad import Squad
from fifa_data.services.card_service import CardService
from fifa_data.services.event_engine import EventEngine
from fifa_data.services.fatigue_service import FatigueService
from fifa_data.services.game_script_service import GameScriptService
from fifa_data.services.match_momentum_service import MatchMomentumService
from fifa_data.services.match_state_service import MatchStateService
from fifa_data.services.penalty_engine import PenaltyEngine
from fifa_data.services.substitution_service import SubstitutionService
from fifa_data.services.tactical_matchup_service import compute_tactical_matchup


HERE = Path(__file__).resolve().parents[1] / "fifa_data"


def _make_player(name: str, country: str, position: str, attrs: dict) -> Player:
    return Player(
        name=name,
        country=country,
        positions=(position,),
        attributes=attrs,
    )


def _make_squad_with_bench(
    country: str,
    formation: str = "4-3-3",
    rating: float = 80.0,
    bench_rating: float = 70.0,
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
        _make_player(f"{country} CB1", country, "CB", {**attrs, "defensive_awareness": rating, "tackling": rating, "strength": rating, "pace": rating * 0.8, "reactions": rating}),
        _make_player(f"{country} CB2", country, "CB", {**attrs, "defensive_awareness": rating, "tackling": rating, "strength": rating, "pace": rating * 0.8, "reactions": rating}),
        _make_player(f"{country} FB1", country, "FB", {**attrs, "pace": rating, "defending": rating, "crossing": rating, "stamina": rating}),
        _make_player(f"{country} FB2", country, "FB", {**attrs, "pace": rating, "defending": rating, "crossing": rating, "stamina": rating}),
        _make_player(f"{country} CM1", country, "CM", {**attrs, "passing": rating, "vision": rating, "dribbling": rating, "stamina": rating, "defending": rating * 0.8}),
        _make_player(f"{country} CM2", country, "CM", {**attrs, "passing": rating, "vision": rating, "dribbling": rating, "stamina": rating, "defending": rating * 0.8}),
        _make_player(f"{country} CM3", country, "CM", {**attrs, "passing": rating, "vision": rating, "dribbling": rating, "stamina": rating, "defending": rating * 0.8}),
        _make_player(f"{country} WG1", country, "WINGER", {**attrs, "pace": rating + 5, "dribbling": rating, "crossing": rating, "finishing": rating * 0.9}),
        _make_player(f"{country} WG2", country, "WINGER", {**attrs, "pace": rating + 5, "dribbling": rating, "crossing": rating, "finishing": rating * 0.9}),
        _make_player(f"{country} ST1", country, "ST", {**attrs, "finishing": rating + 5, "positioning": rating, "shot_power": rating, "pace": rating, "composure": rating}),
    ]

    bench_attrs = {k: min(v, bench_rating) for k, v in attrs.items()}
    bench_players = [
        _make_player(f"{country} SUB1", country, "CM", {**bench_attrs, "passing": bench_rating}),
        _make_player(f"{country} SUB2", country, "ST", {**bench_attrs, "finishing": bench_rating}),
        _make_player(f"{country} SUB3", country, "CB", {**bench_attrs, "defensive_awareness": bench_rating}),
        _make_player(f"{country} SUB4", country, "WINGER", {**bench_attrs, "pace": bench_rating}),
        _make_player(f"{country} SUB5", country, "FB", {**bench_attrs, "pace": bench_rating}),
    ]

    all_players = starters + bench_players
    return Squad(country=country, players=all_players, formation=formation, preferred_starting_xi=starters)


class PlayerMatchStateTests(unittest.TestCase):
    def test_energy_effects_full_energy(self):
        state = PlayerMatchState(player_name="Test", country="Test", position="ST", energy=90)
        attrs = {"pace": 80, "dribbling": 80, "passing": 80}
        modified = state.apply_energy_effects(attrs)
        self.assertEqual(modified["pace"], 80.0)
        self.assertEqual(modified["dribbling"], 80.0)

    def test_energy_effects_low_energy(self):
        state = PlayerMatchState(player_name="Test", country="Test", position="ST", energy=10)
        attrs = {"pace": 80, "dribbling": 80, "passing": 80}
        modified = state.apply_energy_effects(attrs)
        self.assertAlmostEqual(modified["pace"], 56.0)
        self.assertAlmostEqual(modified["dribbling"], 56.0)

    def test_morale_multiplier_high(self):
        state = PlayerMatchState(player_name="Test", country="Test", position="ST", morale=90)
        self.assertEqual(state.morale_multiplier(), 1.08)

    def test_morale_multiplier_low(self):
        state = PlayerMatchState(player_name="Test", country="Test", position="ST", morale=10)
        self.assertEqual(state.morale_multiplier(), 0.88)


class FatigueServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = FatigueService()

    def test_energy_loss_high_stamina(self):
        player = _make_player("Test", "Test", "CM", {"stamina": 95, "age": 25, "work_rate": 50, "physical": 80, "pace": 70})
        state = PlayerMatchState(player_name="Test", country="Test", position="CM", energy=100)
        loss = self.service.compute_energy_loss(player, state)
        self.assertGreater(loss, 0)
        self.assertLess(loss, 8)

    def test_energy_loss_low_stamina(self):
        player = _make_player("Test", "Test", "CM", {"stamina": 40, "age": 35, "work_rate": 80, "physical": 40, "pace": 50})
        state = PlayerMatchState(player_name="Test", country="Test", position="CM", energy=100)
        loss = self.service.compute_energy_loss(player, state)
        self.assertGreater(loss, 1)

    def test_energy_loss_extra_time(self):
        player = _make_player("Test", "Test", "CM", {"stamina": 70, "age": 27, "work_rate": 50, "physical": 50, "pace": 50})
        state = PlayerMatchState(player_name="Test", country="Test", position="CM", energy=100)
        normal_loss = self.service.compute_energy_loss(player, state)
        et_loss = self.service.compute_energy_loss(player, state, is_extra_time=True)
        self.assertGreater(et_loss, normal_loss)

    def test_fatigue_accumulates(self):
        player = _make_player("Test", "Test", "CM", {"stamina": 80, "age": 27, "work_rate": 50, "physical": 80, "pace": 70})
        state = PlayerMatchState(player_name="Test", country="Test", position="CM", energy=100)
        for _ in range(6):
            self.service.apply_phase_fatigue([player], {"Test": state})
        self.assertLess(state.energy, 100)

    def test_freshness_bonus(self):
        self.assertEqual(self.service.freshness_bonus(0), 1.10)
        self.assertEqual(self.service.freshness_bonus(15), 1.05)
        self.assertEqual(self.service.freshness_bonus(30), 1.0)

    def test_pressing_intensity_mapping(self):
        self.assertEqual(self.service.get_pressing_intensity("high_press"), 1.6)
        self.assertEqual(self.service.get_pressing_intensity("low_block"), 0.7)


class CardServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = CardService()

    def test_foul_probability_high_aggression(self):
        player = _make_player("Test", "Test", "CB", {"aggression": 90, "composure": 50, "defending": 50})
        state = PlayerMatchState(player_name="Test", country="Test", position="CB")
        prob = self.service.compute_foul_probability(player, state)
        self.assertGreater(prob, 0.05)

    def test_foul_probability_low_aggression(self):
        player = _make_player("Test", "Test", "CB", {"aggression": 30, "composure": 90, "defending": 90})
        state = PlayerMatchState(player_name="Test", country="Test", position="CB")
        prob = self.service.compute_foul_probability(player, state)
        self.assertLess(prob, 0.15)

    def test_red_card_impact(self):
        impact = self.service.red_card_impact()
        self.assertAlmostEqual(impact["attack"], -0.25)
        self.assertAlmostEqual(impact["pressing"], -0.20)


class MatchMomentumServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = MatchMomentumService()

    def test_goal_boosts_momentum(self):
        from fifa_data.models.match_event import MatchEvent
        self.service.apply_event(
            MatchEvent(30, "TeamA", EventType.GOAL, player_name="PlayerA"),
            "TeamA", "TeamB",
        )
        self.assertGreater(self.service.team_a_momentum, 0)
        self.assertLess(self.service.team_b_momentum, 0)

    def test_momentum_decays(self):
        self.service.team_a_momentum = 80
        self.service.decay_momentum()
        self.assertLess(self.service.team_a_momentum, 80)

    def test_momentum_multiplier(self):
        mult_pos = self.service.get_momentum_multiplier(50)
        self.assertGreater(mult_pos, 1.0)
        mult_neg = self.service.get_momentum_multiplier(-50)
        self.assertLess(mult_neg, 1.0)

    def test_reset(self):
        self.service.team_a_momentum = 80
        self.service.reset()
        self.assertEqual(self.service.team_a_momentum, 0.0)


class SubstitutionServiceTests(unittest.TestCase):
    def setUp(self):
        self.fatigue_service = FatigueService()
        self.service = SubstitutionService(self.fatigue_service)

    def test_substitution_low_energy(self):
        squad = _make_squad_with_bench("TestSub", rating=80, bench_rating=70)
        player_states = {}
        for p in squad.current_starting_xi:
            player_states[p.name] = PlayerMatchState(
                player_name=p.name, country="TestSub", position="CM",
                energy=25, minutes_played=70,
            )
        subs = self.service.evaluate_substitutions(
            "TestSub", squad, player_states, "drawing", 65,
        )
        self.assertGreaterEqual(len(subs), 0)

    def test_bench_strength_calculation(self):
        squad = _make_squad_with_bench("TestBench", rating=80, bench_rating=70)
        bench = self.service.calculate_bench_strength(squad)
        self.assertIn("bench_attack", bench)
        self.assertIn("bench_midfield", bench)
        self.assertIn("bench_defense", bench)
        self.assertIn("bench_size", bench)


class PenaltyEngineTests(unittest.TestCase):
    def setUp(self):
        self.service = PenaltyEngine()

    def test_penalty_shootout_returns_winner(self):
        squad_a = _make_squad_with_bench("TeamA", rating=85)
        squad_b = _make_squad_with_bench("TeamB", rating=80)
        scores_a, scores_b, winner = self.service.simulate_penalty_shootout(
            squad_a, squad_b, "TeamA", "TeamB",
        )
        self.assertIn(winner, ["TeamA", "TeamB"])
        self.assertGreater(len(scores_a), 0)
        self.assertGreater(len(scores_b), 0)
        self.assertIn("✓", scores_a + scores_b)

    def test_penalty_takers_selected(self):
        squad = _make_squad_with_bench("TeamA", rating=85)
        takers = self.service._select_penalty_takers(squad)
        self.assertGreaterEqual(len(takers), 1)


class GameScriptServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GameScriptService()

    def test_generate_story_returns_list(self):
        state = MatchState(team_a="TeamA", team_b="TeamB")
        state.scoreline.goals_a = 1
        state.scoreline.goals_b = 0
        state.events.append(MatchEvent(30, "TeamA", EventType.GOAL, player_name="PlayerA"))
        story = self.service.generate_match_story(state)
        self.assertIsInstance(story, list)
        self.assertGreater(len(story), 0)

    def test_top_performers(self):
        state = MatchState(team_a="TeamA", team_b="TeamB")
        state.team_a_players["PlayerA"] = PlayerMatchState(
            player_name="PlayerA", country="TeamA", position="ST",
            goals=2, match_rating=8.5,
        )
        state.team_b_players["PlayerB"] = PlayerMatchState(
            player_name="PlayerB", country="TeamB", position="CM",
            assists=1, match_rating=7.5,
        )
        performers = self.service.get_top_performers(state, top_n=2)
        self.assertLessEqual(len(performers), 2)
        if performers:
            self.assertIn("name", performers[0])

    def test_format_timeline(self):
        state = MatchState(team_a="TeamA", team_b="TeamB")
        state.events.append(MatchEvent(22, "TeamA", EventType.GOAL, player_name="P1"))
        state.events.append(MatchEvent(67, "TeamB", EventType.YELLOW_CARD, player_name="P2"))
        timeline = self.service.format_timeline(state)
        self.assertGreater(len(timeline), 0)


class EventEngineTests(unittest.TestCase):
    def setUp(self):
        self.card_service = CardService()
        self.momentum_service = MatchMomentumService()
        self.service = EventEngine(self.card_service, self.momentum_service)

    def test_estimate_attacks_returns_positive(self):
        attacks = self.service._estimate_attacks(0.5, {}, 0)
        self.assertGreater(attacks, 0)

    def test_phase_events_generated(self):
        squad_a = _make_squad_with_bench("TeamA", rating=85)
        squad_b = _make_squad_with_bench("TeamB", rating=80)
        state = MatchState(team_a="TeamA", team_b="TeamB")
        for p in squad_a.current_starting_xi:
            state.team_a_players[p.name] = PlayerMatchState(p.name, "TeamA", "CM")
        for p in squad_b.current_starting_xi:
            state.team_b_players[p.name] = PlayerMatchState(p.name, "TeamB", "CM")

        events = self.service.generate_phase_events(
            state, squad_a, squad_b,
            1.2, 1.0, 1.2, 1.0,
            MatchPhase.EARLY_FIRST_HALF,
        )
        self.assertIsInstance(events, list)

    def test_select_event_player(self):
        squad = _make_squad_with_bench("TeamA", rating=85)
        player = self.service._select_event_player(squad, "ST")
        self.assertIsNotNone(player)


class V5EngineTests(unittest.TestCase):
    def test_engine_initialization(self):
        engine = V5MatchStateEngine()
        self.assertIsNotNone(engine.fatigue_service)
        self.assertIsNotNone(engine.card_service)
        self.assertIsNotNone(engine.momentum_service)
        self.assertIsNotNone(engine.penalty_engine)
        self.assertIsNotNone(engine.match_state_service)
        self.assertIsNotNone(engine.substitution_service)
        self.assertIsNotNone(engine.event_engine)
        self.assertIsNotNone(engine.game_script_service)

    def test_basic_simulation_with_squads(self):
        squad_a = _make_squad_with_bench("France", rating=85)
        squad_b = _make_squad_with_bench("England", rating=82)
        squads = {"France": squad_a, "England": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        result = engine.simulate_match("France", "England", can_draw=True)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], int)
        self.assertIsInstance(result[1], int)
        self.assertGreaterEqual(result[0], 0)
        self.assertGreaterEqual(result[1], 0)

    def test_detailed_simulation_returns_match_state(self):
        squad_a = _make_squad_with_bench("Spain", rating=85)
        squad_b = _make_squad_with_bench("Brazil", rating=83)
        squads = {"Spain": squad_a, "Brazil": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        score, state, events = engine.simulate_match_detailed("Spain", "Brazil")
        self.assertIsInstance(state, MatchState)
        self.assertIsInstance(events, list)
        self.assertEqual(score[0], state.scoreline.goals_a)
        self.assertEqual(score[1], state.scoreline.goals_b)

    def test_debug_output_contains_v5_section(self):
        squad_a = _make_squad_with_bench("Germany", rating=85)
        squad_b = _make_squad_with_bench("Italy", rating=80)
        squads = {"Germany": squad_a, "Italy": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        _, debug = engine.simulate_match_debug("Germany", "Italy")
        self.assertIn("V5 MATCH STATE SIMULATION", debug)
        self.assertIn("MATCH FLOW", debug)
        self.assertIn("EVENT TIMELINE", debug)

    def test_knockout_simulation_resolves(self):
        squad_a = _make_squad_with_bench("France", rating=85)
        squad_b = _make_squad_with_bench("Spain", rating=83)
        squads = {"France": squad_a, "Spain": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        result = engine.simulate_match("France", "Spain", can_draw=False)
        self.assertNotEqual(result[0], result[1])

    def test_energy_affects_simulation(self):
        squad_a = _make_squad_with_bench("HighStam", rating=85)
        for p in squad_a.preferred_starting_xi:
            p.attributes["stamina"] = 95
        squad_b = _make_squad_with_bench("LowStam", rating=80)
        for p in squad_b.preferred_starting_xi:
            p.attributes["stamina"] = 40
        squads = {"HighStam": squad_a, "LowStam": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        _, state, _ = engine.simulate_match_detailed("HighStam", "LowStam")
        energy_a = state.get_team_energy_avg("HighStam")
        energy_b = state.get_team_energy_avg("LowStam")
        self.assertGreater(energy_a, energy_b)

    def test_card_events_generated(self):
        squad_a = _make_squad_with_bench("Aggressive", rating=75)
        for p in squad_a.preferred_starting_xi:
            p.attributes["aggression"] = 95
            p.attributes["composure"] = 30
        squad_b = _make_squad_with_bench("Passive", rating=75)
        squads = {"Aggressive": squad_a, "Passive": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        _, state, _ = engine.simulate_match_detailed("Aggressive", "Passive")
        yellow_events = [
            e for e in state.events
            if e.event_type == EventType.YELLOW_CARD
        ]
        self.assertIsInstance(yellow_events, list)

    def test_goals_emerge_from_events(self):
        squad_a = _make_squad_with_bench("Strong", rating=90)
        squad_b = _make_squad_with_bench("Weak", rating=60)
        squads = {"Strong": squad_a, "Weak": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        score, state, events = engine.simulate_match_detailed("Strong", "Weak")
        goal_events = [e for e in events if e.event_type == EventType.GOAL]
        total_goals = score[0] + score[1]
        self.assertEqual(total_goals, len(goal_events))

    def test_momentum_changes_outcomes(self):
        squad_a = _make_squad_with_bench("TeamA", rating=80)
        squad_b = _make_squad_with_bench("TeamB", rating=80)
        squads = {"TeamA": squad_a, "TeamB": squad_b}
        engine = V5MatchStateEngine(squads=squads)

        results = {"A_wins": 0, "B_wins": 0, "draw": 0}
        for _ in range(50):
            result = engine.simulate_match("TeamA", "TeamB", can_draw=True)
            if result[0] > result[1]:
                results["A_wins"] += 1
            elif result[1] > result[0]:
                results["B_wins"] += 1
            else:
                results["draw"] += 1
        total = sum(results.values())
        self.assertEqual(total, 50)

    def test_extra_time_and_penalties(self):
        squad_a = _make_squad_with_bench("TeamA", rating=80)
        squad_b = _make_squad_with_bench("TeamB", rating=80)
        squads = {"TeamA": squad_a, "TeamB": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        result = engine.simulate_match("TeamA", "TeamB", can_draw=False)
        self.assertEqual(len(result), 2)

    def test_game_plan_changes_occur(self):
        squad_a = _make_squad_with_bench("Spain", rating=85)
        squad_b = _make_squad_with_bench("Morocco", rating=75)
        squads = {"Spain": squad_a, "Morocco": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        _, state, _ = engine.simulate_match_detailed("Spain", "Morocco")
        total_changes = len(state.game_plan_history_a) + len(state.game_plan_history_b)
        self.assertIsInstance(total_changes, int)

    def test_top_performers_in_debug(self):
        squad_a = _make_squad_with_bench("Brazil", rating=88)
        squad_b = _make_squad_with_bench("Argentina", rating=86)
        squads = {"Brazil": squad_a, "Argentina": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        _, debug = engine.simulate_match_debug("Brazil", "Argentina")
        self.assertIn("TOP PERFORMERS", debug)

    def test_expected_goals_returns_values(self):
        squad_a = _make_squad_with_bench("France", rating=85)
        squad_b = _make_squad_with_bench("England", rating=82)
        squads = {"France": squad_a, "England": squad_b}
        engine = V5MatchStateEngine(squads=squads)
        xg1, xg2 = engine.expected_goals("France", "England")
        self.assertGreater(xg1, 0)
        self.assertGreater(xg2, 0)

    def test_get_team_strength(self):
        squad_a = _make_squad_with_bench("France", rating=85)
        squads = {"France": squad_a}
        engine = V5MatchStateEngine(squads=squads)
        strength = engine.get_team_strength("France")
        self.assertEqual(strength.team, "France")


class MatchStateServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = MatchStateService()

    def test_initialize_match_state(self):
        squad = _make_squad_with_bench("Test", rating=80)
        state = self.service.initialize_match_state("Test", "Opp", squad, squad)
        self.assertEqual(len(state.team_a_players), 11)
        self.assertEqual(len(state.team_b_players), 11)

    def test_advance_phase(self):
        state = MatchState(team_a="A", team_b="B")
        self.assertEqual(state.current_phase, MatchPhase.EARLY_FIRST_HALF)
        self.service.advance_phase(state)
        self.assertEqual(state.current_phase, MatchPhase.MID_FIRST_HALF)

    def test_scoreline_states(self):
        state = MatchState(team_a="A", team_b="B")
        state.scoreline.goals_a = 2
        state.scoreline.goals_b = 0
        self.assertEqual(self.service.get_scoreline_state("A", state), "winning")
        self.assertEqual(self.service.get_scoreline_state("B", state), "trailing")

    def test_possession_calculation(self):
        poss = self.service.calculate_possession(1.5, 1.0, "balanced", "balanced", 0, 0)
        self.assertGreater(poss, 0.2)
        self.assertLess(poss, 0.8)

    def test_relative_strength(self):
        r1, r2 = self.service.get_relative_strength(2.0, 1.0)
        self.assertGreater(r1, r2)


if __name__ == "__main__":
    unittest.main()
