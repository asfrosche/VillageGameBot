import unittest
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(HERE)
FIFA_DATA = os.path.join(MAY_DIR, "fifa_data")
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, FIFA_DATA)

from cogs.draft_cog import (
    get_roster_counts, get_country_counts, get_remaining_slots,
    can_add_position, can_add_country, is_player_drafted,
    generate_snake_order, get_current_owner, get_next_owners,
    COUNTRY_LIST, COUNTRY_TO_SIM, SIM_TO_COUNTRY,
    country_to_sim, sim_to_country,
)

# Load GROUPS directly from worldcupsimulator.py (avoids relative import issues)
sim_path = os.path.join(FIFA_DATA, "worldcupsimulator.py")
with open(sim_path, "r", encoding="utf-8") as f:
    content = f.read()
data_block = content.split("RAW_ROSTERS")[0]
data_block = data_block.replace("from numpy.random import poisson\n", "")
sim_ns = {}
exec(data_block, sim_ns)
GROUPS = sim_ns.get("GROUPS", {})


class TestRosterCounts(unittest.TestCase):
    def test_empty_roster(self):
        counts = get_roster_counts([])
        self.assertEqual(counts, {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0})

    def test_single_player(self):
        players = [{"name": "Messi", "position": "FWD", "country": "Argentina"}]
        counts = get_roster_counts(players)
        self.assertEqual(counts, {"GK": 0, "DEF": 0, "MID": 0, "FWD": 1})

    def test_multiple_positions(self):
        players = [
            {"name": "A", "position": "GK", "country": "X"},
            {"name": "B", "position": "DEF", "country": "X"},
            {"name": "C", "position": "MID", "country": "X"},
            {"name": "D", "position": "FWD", "country": "X"},
        ]
        counts = get_roster_counts(players)
        self.assertEqual(counts, {"GK": 1, "DEF": 1, "MID": 1, "FWD": 1})


class TestCountryCounts(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(get_country_counts([]), {})

    def test_country_count(self):
        players = [
            {"name": "A", "country": "Brazil", "position": "FWD"},
            {"name": "B", "country": "Brazil", "position": "MID"},
            {"name": "C", "country": "Argentina", "position": "DEF"},
        ]
        counts = get_country_counts(players)
        self.assertEqual(counts, {"Brazil": 2, "Argentina": 1})

    def test_max_per_country(self):
        players = [
            {"name": "A", "country": "Brazil", "position": "FWD"},
            {"name": "B", "country": "Brazil", "position": "MID"},
        ]
        self.assertFalse(can_add_country(players, "Brazil"))
        self.assertTrue(can_add_country(players, "Argentina"))


class TestCanAddPosition(unittest.TestCase):
    def test_all_positions_filled(self):
        players = [
            {"name": "A", "position": "GK", "country": "X"},
            {"name": "B", "position": "DEF", "country": "X"},
            {"name": "C", "position": "DEF", "country": "X"},
            {"name": "D", "position": "DEF", "country": "X"},
            {"name": "E", "position": "MID", "country": "X"},
            {"name": "F", "position": "MID", "country": "X"},
            {"name": "G", "position": "FWD", "country": "X"},
        ]
        # GK is at max (1/1), can't add more
        self.assertFalse(can_add_position(players, "GK"))
        for pos in ["DEF", "MID", "FWD"]:
            self.assertTrue(can_add_position(players, pos), f"{pos} should be addable")

    def test_positions_at_max(self):
        players = [
            {"name": "A", "position": "GK", "country": "X"},
            {"name": "B", "position": "DEF", "country": "X"},
            {"name": "C", "position": "DEF", "country": "X"},
            {"name": "D", "position": "DEF", "country": "X"},
            {"name": "E", "position": "DEF", "country": "X"},
            {"name": "F", "position": "DEF", "country": "X"},
            {"name": "G", "position": "MID", "country": "X"},
            {"name": "H", "position": "MID", "country": "X"},
            {"name": "I", "position": "MID", "country": "X"},
            {"name": "J", "position": "MID", "country": "X"},
            {"name": "K", "position": "MID", "country": "X"},
        ]
        self.assertFalse(can_add_position(players, "DEF"))
        self.assertFalse(can_add_position(players, "MID"))

    def test_remaining_slots_exact(self):
        players = [
            {"name": "A", "position": "GK", "country": "X"},
            {"name": "B", "position": "DEF", "country": "X"},
            {"name": "C", "position": "DEF", "country": "X"},
            {"name": "D", "position": "DEF", "country": "X"},
            {"name": "E", "position": "MID", "country": "X"},
            {"name": "F", "position": "MID", "country": "X"},
        ]
        slots = get_remaining_slots(players)
        self.assertEqual(slots["GK"]["remaining"], 0)
        self.assertEqual(slots["DEF"]["remaining"], 2)
        self.assertEqual(slots["MID"]["remaining"], 3)
        self.assertEqual(slots["FWD"]["remaining"], 3)

    def test_remaining_slots_enforces_minimums(self):
        players = [
            {"name": "A", "position": "GK", "country": "X"},
            {"name": "B", "position": "DEF", "country": "X"},
            {"name": "C", "position": "DEF", "country": "X"},
            {"name": "D", "position": "DEF", "country": "X"},
            {"name": "E", "position": "MID", "country": "X"},
            {"name": "F", "position": "MID", "country": "X"},
        ]
        # 6 players, 4 remaining slots must fill: 1 GK min, 0 DEF min, 0 MID min, 1 FWD min = 2 min
        # Adding FWD: 4 remaining >= 1 min (GK already at 1) → OK
        self.assertTrue(can_add_position(players, "FWD"))
        # GK already at max (1/1)
        self.assertFalse(can_add_position(players, "GK"))


class TestIsPlayerDrafted(unittest.TestCase):
    def test_drafted_player_found(self):
        draft = {"pick_history": [
            {"name": "Messi", "position": "FWD", "country": "Argentina", "pick_number": 1},
        ]}
        self.assertTrue(is_player_drafted(draft, "Messi"))
        self.assertFalse(is_player_drafted(draft, "Ronaldo"))

    def test_drafted_case_insensitive(self):
        draft = {"pick_history": [
            {"name": "Messi", "position": "FWD", "country": "Argentina", "pick_number": 1},
        ]}
        self.assertTrue(is_player_drafted(draft, "messi"))
        self.assertTrue(is_player_drafted(draft, " MESSI "))


class TestGenerateSnakeOrder(unittest.TestCase):
    def test_empty_managers(self):
        self.assertEqual(generate_snake_order([]), [])

    def test_single_manager(self):
        order = generate_snake_order([1])
        self.assertEqual(len(order), 11)
        self.assertEqual(order, [1] * 11)

    def test_two_managers(self):
        managers = [1, 2]
        order = generate_snake_order(managers)
        self.assertEqual(len(order), 22)
        self.assertEqual(order[0], 1)
        self.assertEqual(order[1], 2)
        self.assertEqual(order[2], 2)
        self.assertEqual(order[3], 1)

    def test_three_managers(self):
        managers = [1, 2, 3]
        order = generate_snake_order(managers)
        self.assertEqual(len(order), 33)


class TestGetCurrentOwner(unittest.TestCase):
    def test_first_pick(self):
        draft = {"snake_order": [1, 2, 3, 1, 2, 3], "current_index": 0}
        self.assertEqual(get_current_owner(draft), 1)

    def test_middle_pick(self):
        draft = {"snake_order": [1, 2, 3, 1, 2, 3], "current_index": 3}
        self.assertEqual(get_current_owner(draft), 1)

    def test_at_end_returns_none(self):
        draft = {"snake_order": [1, 2, 3], "current_index": 3}
        self.assertIsNone(get_current_owner(draft))

    def test_beyond_end(self):
        draft = {"snake_order": [1, 2, 3], "current_index": 10}
        self.assertIsNone(get_current_owner(draft))


class TestGetNextOwners(unittest.TestCase):
    def test_next_owners_basic(self):
        draft = {"snake_order": [1, 2, 3, 1, 2, 3], "current_index": 0}
        self.assertEqual(get_next_owners(draft, 2), [2, 3])

    def test_next_owners_at_end(self):
        draft = {"snake_order": [1, 2, 3], "current_index": 2}
        self.assertEqual(get_next_owners(draft, 2), [])

    def test_next_owners_near_end(self):
        draft = {"snake_order": [1, 2, 3, 1, 2, 3], "current_index": 4}
        self.assertEqual(get_next_owners(draft, 2), [3])


class TestCountryNameMapping(unittest.TestCase):
    def test_mapping_contains_all_mismatches(self):
        expected = {
            "South Korea": "Korea Republic",
            "Czech Republic": "Czechia",
            "Turkey": "Türkiye",
            "Iran": "IR Iran",
            "Cabo Verde": "Cape Verde",
        }
        for draft_name, sim_name in expected.items():
            self.assertEqual(country_to_sim(draft_name), sim_name)
            self.assertEqual(sim_to_country(sim_name), draft_name)

    def test_identity_mapping(self):
        self.assertEqual(country_to_sim("Brazil"), "Brazil")
        self.assertEqual(sim_to_country("Brazil"), "Brazil")

    def test_all_group_teams_exist_in_draft_country_list(self):
        simulation_teams = set()
        for group_teams in GROUPS.values():
            simulation_teams.update(group_teams)
        draft_sim_names = {country_to_sim(n) for n, _, _ in COUNTRY_LIST}
        missing_in_draft = simulation_teams - draft_sim_names
        expected_non_draft = {"Scotland", "New Zealand", "Bosnia-Herzegovina"}
        self.assertEqual(
            missing_in_draft,
            expected_non_draft,
            f"Teams in simulation without draft counterparts: {missing_in_draft - expected_non_draft}"
        )

    def test_all_country_list_names_map_to_simulation(self):
        simulation_teams = set()
        for group_teams in GROUPS.values():
            simulation_teams.update(group_teams)
        unmapped = []
        for name, _, _ in COUNTRY_LIST:
            sim_name = country_to_sim(name)
            if sim_name not in simulation_teams:
                unmapped.append(f"'{name}' -> '{sim_name}'")
        # 48 teams in simulation groups — not all COUNTRY_LIST teams qualified
        # Allow a reasonable number (6-8 expected non-qualifiers from 52 entries)
        self.assertLessEqual(
            len(unmapped), 10,
            f"Too many teams not in simulation: {unmapped}"
        )


class TestParseSimulationArgs(unittest.TestCase):
    @staticmethod
    def parse(args):
        from cogs.draft_cog import DraftCog
        return DraftCog._parse_simulation_args(None, args)

    def test_no_args_returns_v1_defaults(self):
        model, presentation, debug = self.parse(None)
        self.assertEqual(model, "v1")
        self.assertEqual(presentation, "fast")
        self.assertFalse(debug)

        model, presentation, debug = self.parse("")
        self.assertEqual(model, "v1")

    def test_v4_model(self):
        model, presentation, debug = self.parse("v4")
        self.assertEqual(model, "v4")

    def test_animated_presentation(self):
        model, presentation, debug = self.parse("animated")
        self.assertEqual(presentation, "animated")

    def test_debug_flag(self):
        model, presentation, debug = self.parse("debug")
        self.assertTrue(debug)

    def test_v4_animated(self):
        model, presentation, debug = self.parse("v4 animated")
        self.assertEqual(model, "v4")
        self.assertEqual(presentation, "animated")

    def test_v4_debug(self):
        model, presentation, debug = self.parse("v4 debug")
        self.assertEqual(model, "v4")
        self.assertTrue(debug)

    def test_invalid_arg_returns_error(self):
        result = self.parse("invalid")
        self.assertIsNone(result[0])
        self.assertIn("Usage", result[1])

    def test_partially_invalid_args(self):
        result = self.parse("v4 bogus")
        self.assertIsNone(result[0])


if __name__ == "__main__":
    unittest.main()
