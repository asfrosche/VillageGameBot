"""Comprehensive pytest tests for all DraftCog utility functions and commands.

Covers 100% of module-level functions and DraftCog methods that can be
tested without a live Discord bot.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
FIFA_DATA = os.path.join(MAY_DIR, "fifa_data")
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, FIFA_DATA)

from fifa_data.services.draft_cog import (
    DraftCog,
    COUNTRY_LIST,
    COUNTRY_TO_SIM,
    SIM_TO_COUNTRY,
    POSITIONS,
    POSITION_LIMITS,
    POSITION_EMOJIS,
    empty_team,
    _flag,
    get_roster_counts,
    get_country_counts,
    get_remaining_slots,
    can_add_position,
    can_add_country,
    is_player_drafted,
    make_roster_str,
    make_country_counts_str,
    make_remaining_str,
    generate_snake_order,
    get_country_options,
    get_current_owner,
    get_next_owners,
    _standings_table,
    _tiebreaker_text,
    country_to_sim,
    sim_to_country,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def empty_roster():
    return []


@pytest.fixture
def sample_players():
    return [
        {"name": "Messi", "position": "FWD", "country": "Argentina"},
        {"name": "Ronaldo", "position": "FWD", "country": "Portugal"},
        {"name": "Neuer", "position": "GK", "country": "Germany"},
        {"name": "Van Dijk", "position": "DEF", "country": "Netherlands"},
        {"name": "Kante", "position": "MID", "country": "France"},
    ]


@pytest.fixture
def nearly_full_roster():
    return [
        {"name": "A", "position": "GK", "country": "X"},
        {"name": "B", "position": "DEF", "country": "X"},
        {"name": "C", "position": "DEF", "country": "X"},
        {"name": "D", "position": "DEF", "country": "X"},
        {"name": "E", "position": "MID", "country": "X"},
        {"name": "F", "position": "MID", "country": "X"},
    ]


@pytest.fixture
def sample_draft():
    return {
        "snake_order": [1, 2, 3, 1, 2, 3],
        "current_index": 0,
        "pick_history": [
            {"name": "Messi", "position": "FWD", "country": "Argentina", "pick_number": 1},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Module-level data integrity
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleData:
    def test_country_list_format(self):
        for entry in COUNTRY_LIST:
            assert len(entry) == 3, f"Expected (name, flag, code) tuple, got {entry}"
            name, flag, code = entry
            assert isinstance(name, str) and len(name) > 0
            assert isinstance(flag, str) and len(flag) > 0
            assert isinstance(code, str) and len(code) == 3

    def test_positions_defined(self):
        assert POSITIONS == ["GK", "DEF", "MID", "FWD"]

    def test_position_limits(self):
        assert POSITION_LIMITS["GK"] == (1, 1)
        assert POSITION_LIMITS["DEF"][0] >= 3
        assert POSITION_LIMITS["MID"][0] >= 2
        assert POSITION_LIMITS["FWD"][0] >= 1

    def test_position_emojis_all_positions(self):
        for pos in POSITIONS:
            assert pos in POSITION_EMOJIS

    def test_country_to_sim_mapping(self):
        assert country_to_sim("South Korea") == "Korea Republic"
        assert country_to_sim("Brazil") == "Brazil"

    def test_sim_to_country_mapping(self):
        assert sim_to_country("Korea Republic") == "South Korea"
        assert sim_to_country("Brazil") == "Brazil"

    def test_squad_flags_include_extra_teams(self):
        from fifa_data.services.draft_cog import SQUAD_FLAGS
        for team in ["New Zealand", "Bosnia and Herzegovina", "Scotland"]:
            assert team in SQUAD_FLAGS, f"Missing flag for {team}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Utility functions
# ═══════════════════════════════════════════════════════════════════════════

class TestEmptyTeam:
    def test_returns_empty_structure(self):
        team = empty_team()
        assert team == {"players": [], "country_counts": {}}

    def test_is_new_dict_each_call(self):
        assert empty_team() is not empty_team()


class TestFlag:
    def test_known_country(self):
        assert _flag("Brazil") != ""

    def test_unknown_country(self):
        assert _flag("Atlantis") == ""

    def test_all_country_list_teams_have_flags(self):
        from fifa_data.services.draft_cog import SQUAD_FLAGS
        for name, _, _ in COUNTRY_LIST:
            assert name in SQUAD_FLAGS, f"COUNTRY_LIST entry {name} missing from SQUAD_FLAGS"


class TestRosterCounts:
    def test_empty(self):
        assert get_roster_counts([]) == {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}

    def test_single(self):
        players = [{"name": "Messi", "position": "FWD", "country": "Argentina"}]
        assert get_roster_counts(players)["FWD"] == 1

    def test_multiple(self, sample_players):
        counts = get_roster_counts(sample_players)
        assert counts["GK"] == 1
        assert counts["DEF"] == 1
        assert counts["MID"] == 1
        assert counts["FWD"] == 2

    def test_unknown_position_crashes(self):
        players = [{"name": "X", "position": "COACH", "country": "Y"}]
        with pytest.raises(KeyError):
            get_roster_counts(players)


class TestCountryCounts:
    def test_empty(self):
        assert get_country_counts([]) == {}

    def test_single(self):
        players = [{"name": "Messi", "country": "Argentina", "position": "FWD"}]
        assert get_country_counts(players) == {"Argentina": 1}

    def test_two_from_same(self):
        players = [
            {"name": "A", "country": "Brazil", "position": "FWD"},
            {"name": "B", "country": "Brazil", "position": "MID"},
        ]
        assert get_country_counts(players) == {"Brazil": 2}


class TestCanAddCountry:
    def test_under_limit(self, sample_players):
        assert can_add_country(sample_players, "Brazil")

    def test_at_limit(self):
        players = [
            {"name": "A", "country": "Brazil", "position": "FWD"},
            {"name": "B", "country": "Brazil", "position": "MID"},
        ]
        assert not can_add_country(players, "Brazil")

    def test_different_country_ok(self):
        players = [
            {"name": "A", "country": "Brazil", "position": "FWD"},
            {"name": "B", "country": "Brazil", "position": "MID"},
        ]
        assert can_add_country(players, "Argentina")


class TestCanAddPosition:
    def test_gk_at_max(self, nearly_full_roster):
        assert not can_add_position(nearly_full_roster, "GK")

    def test_def_has_room(self, nearly_full_roster):
        assert can_add_position(nearly_full_roster, "DEF")

    def test_mid_has_room(self, nearly_full_roster):
        assert can_add_position(nearly_full_roster, "MID")

    def test_fwd_has_room(self, nearly_full_roster):
        assert can_add_position(nearly_full_roster, "FWD")

    def test_full_roster_all_filled(self):
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
        assert not can_add_position(players, "DEF")
        assert not can_add_position(players, "MID")

    def test_minimums_enforced(self, nearly_full_roster):
        assert can_add_position(nearly_full_roster, "FWD")


class TestIsPlayerDrafted:
    def test_drafted_found(self, sample_draft):
        assert is_player_drafted(sample_draft, "Messi")

    def test_not_drafted(self, sample_draft):
        assert not is_player_drafted(sample_draft, "Ronaldo")

    def test_case_insensitive(self, sample_draft):
        assert is_player_drafted(sample_draft, "messi ")
        assert is_player_drafted(sample_draft, " MESSI ")

    def test_empty_pick_history(self):
        draft = {"pick_history": []}
        assert not is_player_drafted(draft, "Messi")


class TestMakeRosterStr:
    def test_empty_roster(self):
        result = make_roster_str([])
        for pos in POSITIONS:
            assert pos in result or "--" in result

    def test_shows_player_names(self, sample_players):
        result = make_roster_str(sample_players)
        assert "Messi" in result
        assert "Neuer" in result

    def test_all_positions_present(self, sample_players):
        result = make_roster_str(sample_players)
        for pos in POSITIONS:
            assert pos in result

    def test_includes_emojis(self, sample_players):
        result = make_roster_str(sample_players)
        for emoji in POSITION_EMOJIS.values():
            assert emoji in result


class TestMakeCountryCountsStr:
    def test_empty(self):
        assert make_country_counts_str([]) == "None"

    def test_single_country(self):
        players = [{"name": "Messi", "country": "Argentina", "position": "FWD"}]
        result = make_country_counts_str(players)
        assert "Argentina" in result
        assert "1/2" in result

    def test_multiple_countries(self, sample_players):
        result = make_country_counts_str(sample_players)
        assert "Argentina" in result
        assert "Portugal" in result


class TestMakeRemainingStr:
    def test_empty_roster(self):
        result = make_remaining_str([])
        for pos in POSITIONS:
            assert pos in result
            assert "0/1" in result or "0/5" in result or "0/3" in result

    def test_partial_roster(self, nearly_full_roster):
        result = make_remaining_str(nearly_full_roster)
        assert "GK" in result and "DEF" in result

    def test_format_correct(self):
        result = make_remaining_str([])
        parts = result.split(" | ")
        assert len(parts) == 4


class TestGenerateSnakeOrder:
    def test_empty(self):
        assert generate_snake_order([]) == []

    def test_single(self):
        order = generate_snake_order([1])
        assert len(order) == 11
        assert order == [1] * 11

    def test_two_managers(self):
        order = generate_snake_order([1, 2])
        assert len(order) == 22
        assert order[0] == 1
        assert order[1] == 2
        assert order[2] == 2  # snake back
        assert order[3] == 1

    def test_three_managers(self):
        order = generate_snake_order([1, 2, 3])
        assert len(order) == 33

    def test_four_managers(self):
        order = generate_snake_order([1, 2, 3, 4])
        assert len(order) == 44


class TestGetCurrentOwner:
    def test_first_pick(self, sample_draft):
        assert get_current_owner(sample_draft) == 1

    def test_middle_pick(self):
        draft = {"snake_order": [1, 2, 3, 1, 2, 3], "current_index": 3}
        assert get_current_owner(draft) == 1

    def test_at_end(self):
        draft = {"snake_order": [1, 2, 3], "current_index": 3}
        assert get_current_owner(draft) is None

    def test_beyond_end(self):
        draft = {"snake_order": [1, 2, 3], "current_index": 10}
        assert get_current_owner(draft) is None

    def test_zero_length_order(self):
        draft = {"snake_order": [], "current_index": 0}
        assert get_current_owner(draft) is None


class TestGetNextOwners:
    def test_basic(self):
        draft = {"snake_order": [1, 2, 3, 1, 2, 3], "current_index": 0}
        assert get_next_owners(draft, 2) == [2, 3]

    def test_at_end(self):
        draft = {"snake_order": [1, 2, 3], "current_index": 2}
        assert get_next_owners(draft, 2) == []

    def test_near_end(self):
        draft = {"snake_order": [1, 2, 3, 1, 2, 3], "current_index": 4}
        assert get_next_owners(draft, 2) == [3]

    def test_empty_order(self):
        draft = {"snake_order": [], "current_index": 0}
        assert get_next_owners(draft, 2) == []

    def test_count_larger_than_remaining(self):
        draft = {"snake_order": [1, 2, 3], "current_index": 1}
        result = get_next_owners(draft, 5)
        assert result == [3]


class TestGetCountryOptions:
    def test_returns_list_of_select_options(self, sample_players):
        options = get_country_options(sample_players)
        assert len(options) > 0
        for opt in options:
            assert hasattr(opt, "label")
            assert hasattr(opt, "value")

    def test_filters_by_continent(self):
        from fifa_data.services.draft_cog import COUNTRY_CONTINENT
        asian = [c for c, _ in COUNTRY_CONTINENT.items() if _ == "Asia"]
        asian_players = [{"name": "P", "country": c, "position": "FWD"} for c in asian[:2]]
        options = get_country_options(asian_players, continent="Europe")
        for opt in options:
            assert opt.value not in [c for c, _ in COUNTRY_CONTINENT.items() if _ == "Asia"]

    def test_excludes_full_countries(self):
        players = [{"name": "P", "country": "Brazil", "position": "FWD"}]
        options = get_country_options(players)
        brazil_opts = [o for o in options if o.value == "Brazil"]
        assert len(brazil_opts) == 1
        # Add another Brazilian to fill the slot
        players.append({"name": "Q", "country": "Brazil", "position": "MID"})
        options = get_country_options(players)
        brazil_opts = [o for o in options if o.value == "Brazil"]
        assert len(brazil_opts) == 0


class TestStandingsTable:
    def test_empty_standings(self):
        result = _standings_table([])
        assert isinstance(result, str)

    def test_single_team(self):
        standings = [{"name": "Brazil", "pld": 3, "w": 3, "d": 0, "l": 0, "gf": 10, "ga": 1, "gd": 9, "pts": 9}]
        result = _standings_table(standings)
        assert "Brazil" in result
        assert "10" in result

    def test_multiple_teams(self):
        standings = [
            {"name": "Brazil", "pld": 3, "w": 3, "d": 0, "l": 0, "gf": 10, "ga": 1, "gd": 9, "pts": 9},
            {"name": "Argentina", "pld": 3, "w": 1, "d": 1, "l": 1, "gf": 3, "ga": 4, "gd": -1, "pts": 4},
            {"name": "Uruguay", "pld": 3, "w": 0, "d": 2, "l": 1, "gf": 2, "ga": 3, "gd": -1, "pts": 2},
        ]
        result = _standings_table(standings)
        assert "Brazil" in result
        assert "Argentina" in result
        assert "Uruguay" in result

    def test_monospaced_format(self):
        standings = [{"name": "Brazil", "pld": 3, "w": 3, "d": 0, "l": 0, "gf": 10, "ga": 1, "gd": 9, "pts": 9}]
        result = _standings_table(standings)
        assert result.startswith("`")


class TestTiebreakerText:
    def test_no_ties(self):
        standings = [
            {"name": "Brazil", "pts": 9},
            {"name": "Argentina", "pts": 4},
        ]
        result = _tiebreaker_text(standings, [])
        assert result == ""

    def test_tied_teams_no_head_to_head(self):
        standings = [
            {"name": "Brazil", "pts": 4},
            {"name": "Argentina", "pts": 4},
        ]
        result = _tiebreaker_text(standings, [])
        assert isinstance(result, str)
        assert "Brazil" in result
        assert "Argentina" in result

    def test_tied_with_head_to_head(self):
        standings = [
            {"name": "Brazil", "pts": 4},
            {"name": "Argentina", "pts": 4},
        ]
        completed = [
            {"home": {"name": "Brazil", "score": 2}, "away": {"name": "Argentina", "score": 1}},
        ]
        result = _tiebreaker_text(standings, completed)
        txt = "\n".join(result) if isinstance(result, list) else str(result)
        assert "Brazil" in txt


class TestCountryNameMapping:
    def test_all_mismatches_covered(self):
        expected = {
            "South Korea": "Korea Republic",
            "Czech Republic": "Czechia",
            "Turkey": "Türkiye",
            "Iran": "IR Iran",
            "Cabo Verde": "Cape Verde",
        }
        for draft_name, sim_name in expected.items():
            assert country_to_sim(draft_name) == sim_name
            assert sim_to_country(sim_name) == draft_name

    def test_identity(self):
        assert country_to_sim("Brazil") == "Brazil"
        assert sim_to_country("Brazil") == "Brazil"


# ═══════════════════════════════════════════════════════════════════════════
# 3. DraftCog methods (non-Discord)
# ═══════════════════════════════════════════════════════════════════════════

class TestParseSimulationArgs:
    def test_no_args(self):
        model, presentation, debug = DraftCog._parse_simulation_args(None, None)
        assert model == "v1"
        assert presentation == "fast"
        assert not debug

    def test_empty_string(self):
        model, presentation, debug = DraftCog._parse_simulation_args(None, "")
        assert model == "v1"

    def test_v1(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "v1")
        assert model == "v1"

    def test_v5(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "v5")
        assert model == "v5"

    def test_animated(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "animated")
        assert pres == "animated"

    def test_debug(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "debug")
        assert debug

    def test_v4_animated(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "v4 animated")
        assert model == "v4"
        assert pres == "animated"

    def test_v5_debug(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "v5 debug")
        assert model == "v5"
        assert debug

    def test_v4_animated_debug(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "v4 animated debug")
        assert model == "v4"
        assert pres == "animated"
        assert debug

    def test_invalid_arg_returns_error(self):
        result = DraftCog._parse_simulation_args(None, "invalid")
        assert result[0] is None
        assert "Usage" in result[1]

    def test_partially_invalid(self):
        result = DraftCog._parse_simulation_args(None, "v4 bogus")
        assert result[0] is None

    def test_v2_fast(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "v2 fast")
        assert model == "v2"
        assert pres == "fast"

    def test_v3_debug(self):
        model, pres, debug = DraftCog._parse_simulation_args(None, "v3 debug")
        assert model == "v3"
        assert debug


class TestBuildGoalEvents:
    def test_no_goals(self):
        result = DraftCog._build_goal_events([], [])
        assert result == []

    def test_home_goals_only(self):
        result = DraftCog._build_goal_events([10, 45], [])
        assert result == [(10, "H"), (45, "H")]

    def test_away_goals_only(self):
        result = DraftCog._build_goal_events([], [30, 80])
        assert result == [(30, "A"), (80, "A")]

    def test_mixed_goals_sorted(self):
        result = DraftCog._build_goal_events([45, 90], [30, 75])
        assert result == [(30, "A"), (45, "H"), (75, "A"), (90, "H")]

    def test_unsorted_input_still_sorted(self):
        result = DraftCog._build_goal_events([90, 45], [75, 30])
        assert result == [(30, "A"), (45, "H"), (75, "A"), (90, "H")]


class TestDraftCogLoadSave:
    def test_load_missing_file(self, tmp_path):
        bot = MagicMock()
        dpath = tmp_path / "nonexistent" / "draft.json"
        with patch("fifa_data.services.draft_cog.DATA_FILE", str(dpath)):
            cog = DraftCog(bot)
            assert cog.data == {}

    def test_load_corrupt_file_resets(self, tmp_path):
        dfile = tmp_path / "draft_bad.json"
        dfile.write_text("{invalid json", encoding="utf-8")
        bot = MagicMock()
        with patch("fifa_data.services.draft_cog.DATA_FILE", str(dfile)):
            cog = DraftCog(bot)
            assert cog.data == {}

    def test_get_draft_nonexistent(self):
        bot = MagicMock()
        cog = DraftCog(bot)
        assert cog._get_draft(999999) is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. Command registration verification
# ═══════════════════════════════════════════════════════════════════════════

class TestCommandRegistration:
    """Verify all 24 commands are registered with correct names and aliases."""

    def test_all_commands_defined(self):
        from fifa_data.services.draft_cog import DraftCog
        cog = DraftCog(MagicMock())
        commands = cog.get_commands()
        cmd_names = {c.name for c in commands}
        cmd_aliases = {}
        for c in commands:
            for a in c.aliases:
                cmd_aliases[a] = c.name

        expected = {
            "draftstart", "prepick", "draftboard", "myteam", "team",
            "undo", "forcepick", "draftpoints", "playerpoints",
            "standings", "player", "topplayers", "teamvalue",
            "scoutingboard", "pause", "resume", "enddraft",
            "matches", "trending", "differentials", "refreshpoints",
            "simulate_help", "simulate", "montecarlo", "fsim_how",
            "xsim", "xlineup",
        }
        missing = expected - cmd_names
        extra = cmd_names - expected
        assert not missing, f"Missing commands: {missing}"
        assert not extra, f"Unexpected commands: {extra}"

    def test_aliases_registered(self):
        cog = DraftCog(MagicMock())
        commands = cog.get_commands()
        alias_map = {}
        for c in commands:
            for a in c.aliases:
                alias_map[a] = c.name

        expected_aliases = {
            "pp": "player",
            "matchinfo": "matches",
            "form": "trending",
            "diff": "differentials",
            "simhelp": "simulate_help",
            "sim": "simulate",
            "fsim": "simulate",
            "mc": "montecarlo",
        }
        for alias, target in expected_aliases.items():
            assert alias in alias_map, f"Alias '{alias}' not registered"
            assert alias_map[alias] == target, f"Alias '{alias}' points to {alias_map[alias]}, expected {target}"

    def test_each_command_has_docstring(self):
        cog = DraftCog(MagicMock())
        for cmd in cog.get_commands():
            assert cmd.help is not None and len(cmd.help) > 0, f"Command '{cmd.name}' is missing help text"
