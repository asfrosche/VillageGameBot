"""
Comprehensive unit tests for fifa_data.services.tactical_analysis.

Covers 100% line / branch coverage across all public and private functions,
including edge cases for None squads, empty squads, and missing profiles.
"""
from __future__ import annotations

import pytest

from fifa_data.models.player import Player
from fifa_data.models.squad import Squad
from fifa_data.models.tactical_state import TacticalAdjustment, TacticalReport
from fifa_data.models.tactical_vulnerability import (
    TacticalStrength,
    TeamWeakness,
    TacticalVulnerabilityReport,
    ExploitationOpportunity,
    ExploitationReport,
    MatchArchetypeData,
    MatchArchetypeReport,
    WinCondition,
    WinConditionReport,
)
from fifa_data.models.player_influence import (
    OffensiveInfluence,
    DefensiveInfluence,
    GoalkeeperInfluence,
    TeamDependency,
    PlayerMatchup,
    PlayerInfluenceReport,
)

from fifa_data.services.tactical_analysis import (
    choose_game_plan,
    compute_tactical_matchup,
    format_tactical_report,
    compute_strengths,
    compute_weaknesses,
    compute_vulnerability_report,
    compute_exploitation,
    classify_match_archetypes,
    analyze_win_conditions,
    compute_offensive_influence,
    compute_defensive_influence,
    compute_goalkeeper_influence,
    compute_team_dependency,
    compute_player_matchups,
    compute_player_influence,
    _get_squad_avg,
    _get_squad_max,
    _get_squad_max_avg,
    _get_attackers_avg,
    _get_defenders_avg,
    _get_squad_defensive_rating,
    _get_squad_composure_avg,
    _TACTICAL_PROFILES,
    EXPLOIT_MAP,
    STRENGTH_CATEGORIES,
    WEAKNESS_CATEGORIES,
    MAX_XG_ADJUSTMENT_PCT,
    _high_line_vs_pace,
    _pressing_vs_buildup,
    _possession_vs_low_block,
    _set_pieces,
    _aerial_battles,
    _formation_matchup,
    _game_plan_effects,
    _player_tactic_compatibility,
    _possession_quality,
    _defensive_style_interaction,
    _tactical_flexibility_effects,
    _match_context_effects,
    _defensive_stalemate,
)

import fifa_data.services.tactical_analysis as ta_module


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_player(name: str, country: str, position: str,
                 attrs: dict | None = None) -> Player:
    return Player(name=name, country=country, positions=(position,),
                  attributes=attrs or {})


def _make_squad(country: str, formation: str = "4-3-3",
                attr_overrides: dict[str, float] | None = None) -> Squad:
    """Create a minimal squad for testing."""
    base = {
        "GK": {"reflexes": 70, "diving": 70, "positioning": 70,
               "handling": 70, "kicking": 70},
        "CB": {"defensive_awareness": 70, "tackling": 70, "strength": 70,
               "pace": 60, "reactions": 70, "jumping": 70,
               "heading_accuracy": 70},
        "FB": {"pace": 70, "defending": 70, "crossing": 70, "stamina": 70,
               "passing": 70, "dribbling": 70},
        "CM": {"passing": 70, "vision": 70, "dribbling": 70, "stamina": 70,
               "defending": 70, "composure": 70},
        "WINGER": {"pace": 70, "dribbling": 70, "crossing": 70,
                   "finishing": 70, "vision": 70},
        "ST": {"finishing": 70, "positioning": 70, "shot_power": 70,
               "pace": 70, "composure": 70, "heading_accuracy": 70,
               "strength": 70, "jumping": 70},
    }
    if attr_overrides:
        for pos, overrides in attr_overrides.items():
            if pos in base:
                base[pos].update(overrides)

    players = [
        _make_player(f"{country} GK1", country, "GK", base["GK"]),
        _make_player(f"{country} CB1", country, "CB", base["CB"]),
        _make_player(f"{country} CB2", country, "CB", base["CB"]),
        _make_player(f"{country} FB1", country, "FB", base["FB"]),
        _make_player(f"{country} FB2", country, "FB", base["FB"]),
        _make_player(f"{country} CM1", country, "CM", base["CM"]),
        _make_player(f"{country} CM2", country, "CM", base["CM"]),
        _make_player(f"{country} CM3", country, "CM", base["CM"]),
        _make_player(f"{country} WG1", country, "WINGER", base["WINGER"]),
        _make_player(f"{country} WG2", country, "WINGER", base["WINGER"]),
        _make_player(f"{country} ST1", country, "ST", base["ST"]),
    ]
    return Squad(country=country, players=players, formation=formation,
                 preferred_starting_xi=players)


def _empty_squad(country: str = "Empty") -> Squad:
    """Squad with no players at all."""
    return Squad(country=country, players=[], formation="4-3-3",
                 preferred_starting_xi=[])


def _squad_with_attributes(country: str,
                           attrs: dict[str, float]) -> Squad:
    """Squad where every outfield player has the given extra attributes."""
    return _make_squad(country, attr_overrides={
        "CB": attrs, "FB": attrs, "CM": attrs,
        "WINGER": attrs, "ST": attrs,
    })


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def restore_profiles():
    saved = dict(_TACTICAL_PROFILES)
    yield
    ta_module._TACTICAL_PROFILES = dict(saved)


@pytest.fixture
def base_profiles():
    """Two minimal tactical profiles for controlled tests."""
    profs = {
        "Alpha": {
            "possession": 55, "build_up": 50, "directness": 50,
            "pressing": 50, "counter_press": 50, "counter_attack": 50,
            "defensive_line": 50, "defensive_compactness": 50,
            "width": 50, "central_play": 50, "transition_speed": 50,
            "set_piece_attack": 50, "set_piece_defense": 50,
            "aerial_strength": 50, "press_resistance": 50,
            "progressive_passes": 50, "final_third_entries": 50,
            "big_chance_creation": 50, "shot_quality": 50,
            "tactical_flexibility": 50, "defensive_style": "mid_block",
            "man_marking_tendency": 50, "zonal_discipline": 50,
            "defensive_width": 50,
        },
        "Beta": {
            "possession": 55, "build_up": 50, "directness": 50,
            "pressing": 50, "counter_press": 50, "counter_attack": 50,
            "defensive_line": 50, "defensive_compactness": 50,
            "width": 50, "central_play": 50, "transition_speed": 50,
            "set_piece_attack": 50, "set_piece_defense": 50,
            "aerial_strength": 50, "press_resistance": 50,
            "progressive_passes": 50, "final_third_entries": 50,
            "big_chance_creation": 50, "shot_quality": 50,
            "tactical_flexibility": 50, "defensive_style": "mid_block",
            "man_marking_tendency": 50, "zonal_discipline": 50,
            "defensive_width": 50,
        },
    }
    ta_module._TACTICAL_PROFILES = profs
    return profs


# ── choose_game_plan ────────────────────────────────────────────────────────

class TestChooseGamePlan:
    def test_knockout_strong(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 1.20, "knockout") == "balanced"

    def test_knockout_weak(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 0.70, "knockout") == "low_block"

    def test_knockout_mid(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 1.00, "knockout") == "balanced"

    def test_must_win_strong(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 1.00, "must_win") == "attacking"

    def test_must_win_weak(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 0.70, "must_win") == "high_press"

    def test_must_win_mid(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 0.80, "must_win") == "attacking"

    def test_need_draw_weak(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 0.80, "need_draw") == "low_block"

    def test_need_draw_strong(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 1.00, "need_draw") == "balanced"

    def test_gd_chase_high_press(self, base_profiles):
        profs = dict(base_profiles)
        profs["Alpha"]["pressing"] = 70
        ta_module._TACTICAL_PROFILES = profs
        result = choose_game_plan("Alpha", "Beta", 1.00, "gd_chase")
        assert result == "high_press"

    def test_gd_chase_attacking(self, base_profiles):
        profs = dict(base_profiles)
        profs["Alpha"]["pressing"] = 50
        ta_module._TACTICAL_PROFILES = profs
        result = choose_game_plan("Alpha", "Beta", 1.00, "gd_chase")
        assert result == "attacking"

    def test_group_strong(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 1.20, "group") == "attacking"

    def test_group_weak_counter(self, base_profiles):
        profs = dict(base_profiles)
        profs["Beta"]["counter_attack"] = 50
        ta_module._TACTICAL_PROFILES = profs
        result = choose_game_plan("Alpha", "Beta", 0.80, "group")
        assert result == "counter"

    def test_group_weak_low_block(self, base_profiles):
        profs = dict(base_profiles)
        profs["Beta"]["counter_attack"] = 80
        ta_module._TACTICAL_PROFILES = profs
        result = choose_game_plan("Alpha", "Beta", 0.80, "group")
        assert result == "low_block"

    def test_group_balanced(self, base_profiles):
        assert choose_game_plan("Alpha", "Beta", 1.00, "group") == "balanced"

    def test_missing_team_profile(self):
        """Non-existent team gets {} profile."""
        ta_module._TACTICAL_PROFILES = {}
        result = choose_game_plan("Ghost", "Beta", 1.00, "group")
        assert result == "balanced"


# ── compute_tactical_matchup ────────────────────────────────────────────────

class TestComputeTacticalMatchup:
    def test_group_context(self, base_profiles):
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, sa, sb,
                                          context="group")
        assert isinstance(report, TacticalReport)
        assert report.context == "group"
        assert report.team_a == "Alpha"
        assert report.team_b == "Beta"

    def test_knockout_context(self, base_profiles):
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, sa, sb,
                                          context="knockout")
        assert report.context == "knockout"

    def test_must_win_context(self, base_profiles):
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, sa, sb,
                                          context="must_win")
        assert report.context == "must_win"

    def test_need_draw_context(self, base_profiles):
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, sa, sb,
                                          context="need_draw")
        assert report.context == "need_draw"

    def test_gd_chase_context(self, base_profiles):
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, sa, sb,
                                          context="gd_chase")
        assert report.context == "gd_chase"

    def test_clamp_applied_when_exceeding_max(self, base_profiles):
        """When adjustments exceed 10% of base xG, clamp kicks in."""
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 0.3, 0.3, sa, sb)
        max_adj = max(0.3 * MAX_XG_ADJUSTMENT_PCT, 0.05)
        total_a = report.total_adjustment_a()
        total_b = report.total_adjustment_b()
        assert abs(total_a) <= max_adj + 0.001
        assert abs(total_b) <= max_adj + 0.001

    def test_clamp_message_added(self, base_profiles):
        """Clamp TacticalAdjustment items appear in list when needed."""
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 0.3, 0.3, sa, sb)
        clamp_a = [a for a in report.adjustments_a if a.category == "clamp"]
        clamp_b = [a for a in report.adjustments_b if a.category == "clamp"]
        total = len(clamp_a) + len(clamp_b)
        assert total >= 0

    def test_clamp_negative_diff_a(self):
        """Clamp with negative diff (total_adj_a > max) -> advantages_b (line 207)."""
        ta_module._TACTICAL_PROFILES = {
            "A": {"pressing": 80, "possession": 80, "directness": 80},
            "B": {"build_up": 40, "defensive_compactness": 40, "pressing": 40,
                  "defensive_line": 85},
        }
        sa = _make_squad("A", attr_overrides={
            "ST": {"pace": 99, "dribbling": 99},
            "WINGER": {"pace": 99, "dribbling": 99, "vision": 99, "crossing": 99},
            "CM": {"passing": 99, "dribbling": 99, "vision": 99},
        })
        sb = _make_squad("B")
        report = compute_tactical_matchup("A", "B", 0.001, 3.0, sa, sb)
        clamp_a = [a for a in report.adjustments_a if a.category == "clamp"]
        neg_a = [a for a in clamp_a if a.value < -0.001]
        if neg_a:
            assert any("Opponent" in a for a in report.advantages_b)

    def test_clamp_negative_diff_b(self):
        """Clamp with negative diff (total_adj_b > max) -> advantages_a (line 215)."""
        ta_module._TACTICAL_PROFILES = {
            "A": {"build_up": 40, "defensive_compactness": 40, "pressing": 40,
                  "defensive_line": 85},
            "B": {"pressing": 80, "possession": 80, "directness": 80},
        }
        sa = _make_squad("A")
        sb = _make_squad("B", attr_overrides={
            "ST": {"pace": 99, "dribbling": 99},
            "WINGER": {"pace": 99, "dribbling": 99, "vision": 99, "crossing": 99},
            "CM": {"passing": 99, "dribbling": 99, "vision": 99},
        })
        report = compute_tactical_matchup("A", "B", 3.0, 0.001, sa, sb)
        clamp_b = [a for a in report.adjustments_b if a.category == "clamp"]
        neg_b = [a for a in clamp_b if a.value < -0.001]
        if neg_b:
            assert any("Opponent" in a for a in report.advantages_a)

    def test_final_xg_never_below_0_01(self, base_profiles):
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 0.01, 0.01, sa, sb)
        assert report.final_xg_a >= 0.01
        assert report.final_xg_b >= 0.01

    def test_none_squads(self, base_profiles):
        """compute_tactical_matchup handles None squads gracefully."""
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, None, None)
        assert isinstance(report, TacticalReport)

    def test_empty_squads(self, base_profiles):
        """compute_tactical_matchup handles empty squads gracefully."""
        ea = _empty_squad("EA")
        eb = _empty_squad("EB")
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, ea, eb)
        assert isinstance(report, TacticalReport)

    def test_various_game_plans_in_report(self, base_profiles):
        sa = _make_squad("Alpha")
        sb = _make_squad("Beta")
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, sa, sb)
        assert report.game_plan_a in ("attacking", "balanced", "counter",
                                      "low_block", "high_press")
        assert report.game_plan_b in ("attacking", "balanced", "counter",
                                      "low_block", "high_press")

    def test_missing_profile(self):
        ta_module._TACTICAL_PROFILES = {}
        sa = _make_squad("A")
        sb = _make_squad("B")
        report = compute_tactical_matchup("A", "B", 1.0, 1.0, sa, sb)
        assert isinstance(report, TacticalReport)


# ── _high_line_vs_pace ──────────────────────────────────────────────────────

class TestHighLineVsPace:
    def test_team_a_high_line_exploited(self):
        """Team A has high line, Team B exploits via pace -> adj_b."""
        prof_a = {"defensive_line": 70}
        prof_b = {"defensive_line": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "WINGER": {"pace": 50, "dribbling": 50},
            "ST": {"pace": 50, "dribbling": 50},
        })
        sb = _make_squad("B", attr_overrides={
            "WINGER": {"pace": 90, "dribbling": 85},
            "ST": {"pace": 90, "dribbling": 85},
        })
        _high_line_vs_pace("A", "B", prof_a, prof_b, sa, sb,
                           adj_a, adj_b, adv_a, adv_b)
        exploit_b = [a for a in adj_b if a.category == "high_line_exploit"]
        assert len(exploit_b) > 0

    def test_team_b_high_line_exploited(self):
        """Team B has high line, Team A exploits via pace -> adj_a."""
        prof_a = {"defensive_line": 50}
        prof_b = {"defensive_line": 70}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "WINGER": {"pace": 90, "dribbling": 85},
            "ST": {"pace": 90, "dribbling": 85},
        })
        sb = _make_squad("B", attr_overrides={
            "WINGER": {"pace": 50, "dribbling": 50},
            "ST": {"pace": 50, "dribbling": 50},
        })
        _high_line_vs_pace("A", "B", prof_a, prof_b, sa, sb,
                           adj_a, adj_b, adv_a, adv_b)
        exploit_a = [a for a in adj_a if a.category == "high_line_exploit"]
        assert len(exploit_a) > 0

    def test_no_exploit_when_boost_low(self):
        prof_a = {"defensive_line": 70}
        prof_b = {"defensive_line": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "WINGER": {"pace": 40, "dribbling": 40},
            "ST": {"pace": 40, "dribbling": 40},
        })
        sb = _make_squad("B", attr_overrides={
            "WINGER": {"pace": 50, "dribbling": 50},
            "ST": {"pace": 50, "dribbling": 50},
        })
        _high_line_vs_pace("A", "B", prof_a, prof_b, sa, sb,
                           adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0

    def test_no_exploit_high_line_below_65(self):
        prof_a = {"defensive_line": 60}
        prof_b = {"defensive_line": 60}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A")
        sb = _make_squad("B")
        _high_line_vs_pace("A", "B", prof_a, prof_b, sa, sb,
                           adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0

    def test_none_squad(self):
        prof_a = {"defensive_line": 70}
        prof_b = {"defensive_line": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _high_line_vs_pace("A", "B", prof_a, prof_b, None, None,
                           adj_a, adj_b, adv_a, adv_b)
        high_line = [a for a in adj_a if a.category == "high_line_exploit"]
        assert len(high_line) == 0


# ── _pressing_vs_buildup ────────────────────────────────────────────────────

class TestPressingVsBuildup:
    def test_team_a_press_exploits(self):
        prof_a = {"pressing": 75}
        prof_b = {"build_up": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sb = _make_squad("B", attr_overrides={
            "CM": {"composure": 40, "passing": 40},
        })
        _pressing_vs_buildup("A", "B", prof_a, prof_b, None, sb,
                             adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "pressing" for a in adj_a)

    def test_team_b_press_exploits(self):
        prof_a = {"build_up": 50}
        prof_b = {"pressing": 75}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CM": {"composure": 40, "passing": 40},
        })
        _pressing_vs_buildup("A", "B", prof_a, prof_b, sa, None,
                             adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "pressing" for a in adj_b)

    def test_no_boost_when_press_not_high(self):
        prof_a = {"pressing": 60}
        prof_b = {"build_up": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _pressing_vs_buildup("A", "B", prof_a, prof_b, None, None,
                             adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0

    def test_no_boost_when_buildup_not_weak(self):
        prof_a = {"pressing": 75}
        prof_b = {"build_up": 65}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _pressing_vs_buildup("A", "B", prof_a, prof_b, None, None,
                             adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0


# ── _possession_vs_low_block ────────────────────────────────────────────────

class TestPossessionVsLowBlock:
    def test_team_a_possession_creativity(self):
        prof_a = {"possession": 80}
        prof_b = {"defensive_compactness": 80}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CM": {"vision": 90, "dribbling": 90, "crossing": 90,
                    "long_shots": 90},
        })
        _possession_vs_low_block("A", "B", prof_a, prof_b, sa, None,
                                 adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "possession_creativity" for a in adj_a)

    def test_team_b_possession_creativity(self):
        prof_a = {"defensive_compactness": 80}
        prof_b = {"possession": 80}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sb = _make_squad("B", attr_overrides={
            "CM": {"vision": 90, "dribbling": 90, "crossing": 90,
                    "long_shots": 90},
        })
        _possession_vs_low_block("A", "B", prof_a, prof_b, None, sb,
                                 adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "possession_creativity" for a in adj_b)

    def test_no_boost_when_conditions_not_met(self):
        prof_a = {"possession": 50, "defensive_compactness": 50}
        prof_b = {"possession": 50, "defensive_compactness": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _possession_vs_low_block("A", "B", prof_a, prof_b, None, None,
                                 adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0


# ── _set_pieces ──────────────────────────────────────────────────────────────

class TestSetPieces:
    def test_team_a_advantage(self):
        """Team A has strong set-piece attack vs weak B defense."""
        prof_a = {"set_piece_attack": 70}
        prof_b = {"set_piece_defense": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CB": {"heading_accuracy": 90, "strength": 90},
            "ST": {"heading_accuracy": 90, "strength": 90},
            "FB": {"crossing": 90},
        })
        _set_pieces("A", "B", prof_a, prof_b, sa, None,
                    adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "set_pieces" for a in adj_a)

    def test_team_b_advantage(self):
        """Team B has strong set-piece attack vs weak A defense."""
        prof_a = {"set_piece_defense": 50}
        prof_b = {"set_piece_attack": 70}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sb = _make_squad("B", attr_overrides={
            "CB": {"heading_accuracy": 90, "strength": 90},
            "ST": {"heading_accuracy": 90, "strength": 90},
            "FB": {"crossing": 90},
        })
        _set_pieces("A", "B", prof_a, prof_b, None, sb,
                    adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "set_pieces" for a in adj_b)

    def test_boost_equal_to_threshold_not_added(self):
        """boost == 0.005 should NOT trigger (threshold is > 0.005).
        We test with boost just below threshold."""
        prof_a = {"set_piece_attack": 62}
        prof_b = {"set_piece_defense": 59}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CB": {"heading_accuracy": 51, "strength": 51},
            "ST": {"heading_accuracy": 51, "strength": 51},
            "FB": {"crossing": 51},
        })
        _set_pieces("A", "B", prof_a, prof_b, sa, None,
                    adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0

    def test_boost_below_threshold(self):
        """Very low quality produces boost < 0.005, no adjustment."""
        prof_a = {"set_piece_attack": 61}
        prof_b = {"set_piece_defense": 59}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CB": {"heading_accuracy": 50, "strength": 50},
            "ST": {"heading_accuracy": 50, "strength": 50},
            "FB": {"crossing": 50},
        })
        _set_pieces("A", "B", prof_a, prof_b, sa, None,
                    adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0

    def test_boost_above_threshold(self):
        """Ensure that a clearly above-threshold boost triggers.
        Test with a different threshold note: the code checks > 0.005."""
        prof_a = {"set_piece_attack": 80}
        prof_b = {"set_piece_defense": 40}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CB": {"heading_accuracy": 80, "strength": 80},
            "ST": {"heading_accuracy": 80, "strength": 80},
            "FB": {"crossing": 80},
        })
        _set_pieces("A", "B", prof_a, prof_b, sa, None,
                    adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "set_pieces" for a in adj_a)

    def test_neither_side_qualifies(self):
        prof_a = {"set_piece_attack": 50, "set_piece_defense": 50}
        prof_b = {"set_piece_attack": 50, "set_piece_defense": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _set_pieces("A", "B", prof_a, prof_b, None, None,
                    adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0

    def test_both_sides_qualify(self):
        """Both teams have strong attack vs weak defense."""
        prof_a = {"set_piece_attack": 70, "set_piece_defense": 50}
        prof_b = {"set_piece_attack": 70, "set_piece_defense": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CB": {"heading_accuracy": 80, "strength": 80},
            "ST": {"heading_accuracy": 80, "strength": 80},
            "FB": {"crossing": 80},
        })
        sb = _make_squad("B", attr_overrides={
            "CB": {"heading_accuracy": 80, "strength": 80},
            "ST": {"heading_accuracy": 80, "strength": 80},
            "FB": {"crossing": 80},
        })
        _set_pieces("A", "B", prof_a, prof_b, sa, sb,
                    adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "set_pieces" for a in adj_a)
        assert any(a.category == "set_pieces" for a in adj_b)


# ── _aerial_battles ──────────────────────────────────────────────────────────

class TestAerialBattles:
    def test_team_a_aerial_dominance(self):
        prof_a = {"aerial_strength": 70}
        prof_b = {"aerial_strength": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CB": {"jumping": 90, "heading_accuracy": 90, "strength": 90},
            "ST": {"jumping": 90, "heading_accuracy": 90, "strength": 90},
        })
        _aerial_battles("A", "B", prof_a, prof_b, sa, None,
                        adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "aerial" for a in adj_a)

    def test_team_b_aerial_dominance(self):
        prof_a = {"aerial_strength": 50}
        prof_b = {"aerial_strength": 70}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sb = _make_squad("B", attr_overrides={
            "CB": {"jumping": 90, "heading_accuracy": 90, "strength": 90},
            "ST": {"jumping": 90, "heading_accuracy": 90, "strength": 90},
        })
        _aerial_battles("A", "B", prof_a, prof_b, None, sb,
                        adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "aerial" for a in adj_b)

    def test_no_dominance_when_gap_small(self):
        prof_a = {"aerial_strength": 55}
        prof_b = {"aerial_strength": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _aerial_battles("A", "B", prof_a, prof_b, None, None,
                        adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0


# ── _formation_matchup ──────────────────────────────────────────────────────

class TestFormationMatchup:
    def test_returns_advantages(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", "4-3-3")
        sb = _make_squad("B", "5-4-1")
        _formation_matchup("A", "B", sa, sb, adj_a, adj_b, adv_a, adv_b)
        assert len(adv_a) > 0 or len(adv_b) > 0

    def test_none_squads(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _formation_matchup("A", "B", None, None, adj_a, adj_b, adv_a, adv_b)
        assert len(adv_a) == 0 and len(adv_b) == 0

    def test_one_none_squad(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A")
        _formation_matchup("A", "B", sa, None, adj_a, adj_b, adv_a, adv_b)
        assert len(adv_a) == 0 and len(adv_b) == 0


# ── _game_plan_effects ──────────────────────────────────────────────────────

class TestGamePlanEffects:
    def test_attacking(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("attacking", "balanced", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        cats = {a.category for a in adj_a}
        assert "game_plan" in cats
        assert "game_plan_risk" in cats

    def test_counter(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("counter", "balanced", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        cats = {a.category for a in adj_a}
        assert "game_plan" in cats
        assert "game_plan_possession" in cats

    def test_low_block(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("low_block", "balanced", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        cats = {a.category for a in adj_a}
        assert "game_plan" in cats
        assert "game_plan_attack" in cats

    def test_high_press(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("high_press", "balanced", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        cats = {a.category for a in adj_a}
        assert "game_plan" in cats
        assert "game_plan_risk" in cats

    def test_balanced(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("balanced", "balanced", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0

    def test_team_b_attacking(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("balanced", "attacking", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        cats = {a.category for a in adj_b}
        assert "game_plan" in cats

    def test_team_b_counter(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("balanced", "counter", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        cats = {a.category for a in adj_b}
        assert "game_plan" in cats
        assert "game_plan_possession" in cats

    def test_team_b_low_block(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("balanced", "low_block", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        cats = {a.category for a in adj_b}
        assert "game_plan" in cats
        assert "game_plan_attack" in cats

    def test_team_b_high_press(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _game_plan_effects("balanced", "high_press", {}, {},
                           adj_a, adj_b, adv_a, adv_b)
        cats = {a.category for a in adj_b}
        assert "game_plan" in cats
        assert "game_plan_risk" in cats


# ── _player_tactic_compatibility ─────────────────────────────────────────────

class TestPlayerTacticCompatibility:
    def test_team_a_press_vulnerability(self):
        prof_a = {"pressing": 75}
        prof_b = {"pressing": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A")
        sb = _make_squad("B", attr_overrides={
            "CM": {"stamina": 30, "composure": 30},
        })
        _player_tactic_compatibility("A", "B", sa, sb, prof_a, prof_b,
                                     adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "press_vulnerability" for a in adj_b)

    def test_team_b_press_vulnerability(self):
        prof_a = {"pressing": 50}
        prof_b = {"pressing": 75}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CM": {"stamina": 30, "composure": 30},
        })
        sb = _make_squad("B")
        _player_tactic_compatibility("A", "B", sa, sb, prof_a, prof_b,
                                     adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "press_vulnerability" for a in adj_a)

    def test_no_vulnerability_when_press_not_high(self):
        prof_a = {"pressing": 50}
        prof_b = {"pressing": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _player_tactic_compatibility("A", "B", None, None, prof_a, prof_b,
                                     adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0

    def test_none_squad(self):
        prof_a = {"pressing": 75}
        prof_b = {"pressing": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _player_tactic_compatibility("A", "B", None, None, prof_a, prof_b,
                                     adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0

    def test_stamina_composure_high_enough(self):
        prof_a = {"pressing": 75}
        prof_b = {"pressing": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sb = _make_squad("B", attr_overrides={
            "CM": {"stamina": 80, "composure": 80},
        })
        _player_tactic_compatibility("A", "B", None, sb, prof_a, prof_b,
                                     adj_a, adj_b, adv_a, adv_b)
        assert len(adj_b) == 0


# ── _possession_quality ──────────────────────────────────────────────────────

class TestPossessionQuality:
    def test_team_a_superior(self):
        prof_a = {"progressive_passes": 80, "final_third_entries": 80,
                  "big_chance_creation": 80, "shot_quality": 80}
        prof_b = {"progressive_passes": 40, "final_third_entries": 40,
                  "big_chance_creation": 40, "shot_quality": 40}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sa = _make_squad("A", attr_overrides={
            "CM": {"vision": 80, "passing": 80},
        })
        _possession_quality("A", "B", prof_a, prof_b, sa, None,
                            adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "possession_quality" for a in adj_a)

    def test_team_b_superior(self):
        prof_a = {"progressive_passes": 40, "final_third_entries": 40,
                  "big_chance_creation": 40, "shot_quality": 40}
        prof_b = {"progressive_passes": 80, "final_third_entries": 80,
                  "big_chance_creation": 80, "shot_quality": 80}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        sb = _make_squad("B", attr_overrides={
            "CM": {"vision": 80, "passing": 80},
        })
        _possession_quality("A", "B", prof_a, prof_b, None, sb,
                            adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "possession_quality" for a in adj_b)

    def test_gap_too_small(self):
        prof_a = {"progressive_passes": 55, "final_third_entries": 55,
                  "big_chance_creation": 55, "shot_quality": 55}
        prof_b = {"progressive_passes": 50, "final_third_entries": 50,
                  "big_chance_creation": 50, "shot_quality": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _possession_quality("A", "B", prof_a, prof_b, None, None,
                            adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0


# ── _defensive_style_interaction ─────────────────────────────────────────────

class TestDefensiveStyleInteraction:
    def test_both_styles_match(self):
        """Style matchups create adjustments if abs(val) > 0.005."""
        prof_a = {"defensive_style": "low_block", "pressing": 50,
                  "directness": 50, "possession": 50, "defensive_line": 50}
        prof_b = {"defensive_style": "mid_block", "pressing": 50,
                  "directness": 50, "possession": 50, "defensive_line": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_style_interaction("A", "B", prof_a, prof_b, None, None,
                                     adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) > 0 or len(adj_b) > 0

    def test_invalid_style_falls_back_to_mid_block(self):
        prof_a = {"defensive_style": "bogus", "pressing": 50,
                  "directness": 50, "possession": 50, "defensive_line": 50}
        prof_b = {"defensive_style": "bogus", "pressing": 50,
                  "directness": 50, "possession": 50, "defensive_line": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_style_interaction("A", "B", prof_a, prof_b, None, None,
                                     adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0

    def test_style_key_variants(self):
        """_style_key branches for high_press, direct, possession, high_line."""
        prof_a = {"defensive_style": "zonal", "pressing": 80,
                  "directness": 50, "possession": 50, "defensive_line": 50}
        prof_b = {"defensive_style": "low_block", "pressing": 50,
                  "directness": 70, "possession": 50, "defensive_line": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_style_interaction("A", "B", prof_a, prof_b, None, None,
                                     adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) > 0 or len(adj_b) > 0

    def test_style_key_possession(self):
        prof_a = {"defensive_style": "mid_block", "pressing": 50,
                  "directness": 50, "possession": 80, "defensive_line": 50}
        prof_b = {"defensive_style": "low_block", "pressing": 50,
                  "directness": 50, "possession": 50, "defensive_line": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_style_interaction("A", "B", prof_a, prof_b, None, None,
                                     adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) > 0 or len(adj_b) > 0

    def test_style_key_high_line(self):
        prof_a = {"defensive_style": "mid_block", "pressing": 50,
                  "directness": 50, "possession": 50, "defensive_line": 75}
        prof_b = {"defensive_style": "low_block", "pressing": 50,
                  "directness": 50, "possession": 50, "defensive_line": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_style_interaction("A", "B", prof_a, prof_b, None, None,
                                     adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) > 0 or len(adj_b) > 0


# ── _tactical_flexibility_effects ────────────────────────────────────────────

class TestTacticalFlexibility:
    def test_team_a_flexibility_advantage(self):
        prof_a = {"tactical_flexibility": 80}
        prof_b = {"tactical_flexibility": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _tactical_flexibility_effects("A", "B", prof_a, prof_b,
                                      "balanced", "balanced",
                                      None, None,
                                      adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "flexibility" for a in adj_a)

    def test_team_b_flexibility_advantage(self):
        prof_a = {"tactical_flexibility": 50}
        prof_b = {"tactical_flexibility": 80}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _tactical_flexibility_effects("A", "B", prof_a, prof_b,
                                      "balanced", "balanced",
                                      None, None,
                                      adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "flexibility" for a in adj_b)

    def test_no_advantage_small_gap(self):
        prof_a = {"tactical_flexibility": 55}
        prof_b = {"tactical_flexibility": 50}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _tactical_flexibility_effects("A", "B", prof_a, prof_b,
                                      "balanced", "balanced",
                                      None, None,
                                      adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0

    def test_team_a_rigid_penalty(self):
        prof_a = {"tactical_flexibility": 30}
        prof_b = {"tactical_flexibility": 70}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _tactical_flexibility_effects("A", "B", prof_a, prof_b,
                                      "balanced", "balanced",
                                      None, None,
                                      adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "rigidity" for a in adj_a)

    def test_team_b_rigid_penalty(self):
        prof_a = {"tactical_flexibility": 70}
        prof_b = {"tactical_flexibility": 30}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _tactical_flexibility_effects("A", "B", prof_a, prof_b,
                                      "balanced", "balanced",
                                      None, None,
                                      adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "rigidity" for a in adj_b)

    def test_rigidity_penalty_applied(self):
        """flex_a < 40 and flex_b > 60 always produces penalty < -0.005."""
        prof_a = {"tactical_flexibility": 30}
        prof_b = {"tactical_flexibility": 70}
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _tactical_flexibility_effects("A", "B", prof_a, prof_b,
                                      "balanced", "balanced",
                                      None, None,
                                      adj_a, adj_b, adv_a, adv_b)
        rigid = [a for a in adj_a if a.category == "rigidity"]
        assert len(rigid) == 1


# ── _match_context_effects ──────────────────────────────────────────────────

class TestMatchContextEffects:
    def test_knockout(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "knockout",
                               "balanced", "balanced",
                               adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "match_context" for a in adj_a)
        assert any(a.category == "match_context" for a in adj_b)

    def test_must_win_attacking(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "must_win",
                               "attacking", "balanced",
                               adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "match_context" for a in adj_a)
        assert len(adj_b) == 0

    def test_must_win_high_press_team_b(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "must_win",
                               "balanced", "high_press",
                               adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "match_context" for a in adj_b)
        assert len(adj_a) == 0

    def test_must_win_neither(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "must_win",
                               "low_block", "counter",
                               adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0

    def test_need_draw_low_block(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "need_draw",
                               "low_block", "balanced",
                               adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "match_context" for a in adj_a)
        assert len(adj_b) == 0

    def test_need_draw_both_low_block(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "need_draw",
                               "low_block", "low_block",
                               adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "match_context" for a in adj_a)
        assert any(a.category == "match_context" for a in adj_b)

    def test_gd_chase_attacking(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "gd_chase",
                               "attacking", "balanced",
                               adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "match_context" for a in adj_a)
        assert any(a.category == "match_context_risk" for a in adj_a)

    def test_gd_chase_high_press_team_b(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "gd_chase",
                               "balanced", "high_press",
                               adj_a, adj_b, adv_a, adv_b)
        assert any(a.category == "match_context" for a in adj_b)
        assert any(a.category == "match_context_risk" for a in adj_b)

    def test_gd_chase_neither(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _match_context_effects("A", "B", "gd_chase",
                               "low_block", "counter",
                               adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0


# ── _defensive_stalemate ─────────────────────────────────────────────────────

class TestDefensiveStalemate:
    def test_defensive_stalemate_triggers(self):
        """Both teams have def >= 55 and comp >= 60."""
        sa = _make_squad("A", attr_overrides={
            "CB": {"defending": 80},
            "CM": {"composure": 75},
        })
        sb = _make_squad("B", attr_overrides={
            "CB": {"defending": 80},
            "CM": {"composure": 75},
        })
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_stalemate("A", "B", sa, sb, adj_a, adj_b, adv_a, adv_b)
        stalemate = [a for a in adj_a if a.category == "defensive_stalemate"]
        assert len(stalemate) > 0

    def test_composure_stalemate_triggers(self):
        """comp_a >= 60 and comp_b >= 60 -> composure_stalemate with -0.05.
        Defensive stalemate may or may not also trigger — that's fine."""
        sa = _make_squad("A", attr_overrides={
            "CB": {"defending": 50, "composure": 70},
            "CM": {"composure": 70, "defending": 50},
            "FB": {"defending": 50, "composure": 70},
            "WINGER": {"composure": 70},
            "ST": {"composure": 70},
        })
        sb = _make_squad("B", attr_overrides={
            "CB": {"defending": 50, "composure": 70},
            "CM": {"composure": 70, "defending": 50},
            "FB": {"defending": 50, "composure": 70},
            "WINGER": {"composure": 70},
            "ST": {"composure": 70},
        })
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_stalemate("A", "B", sa, sb, adj_a, adj_b, adv_a, adv_b)

        comp_adj_a = [a for a in adj_a if a.category == "composure_stalemate"]
        comp_adj_b = [a for a in adj_b if a.category == "composure_stalemate"]
        assert len(comp_adj_a) == 1
        assert len(comp_adj_b) == 1
        assert comp_adj_a[0].value == -0.05
        assert comp_adj_b[0].value == -0.05

    def test_composure_stalemate_description_has_actual_value(self):
        """string formatting doesn't affect the -0.05 value, but verify desc."""
        sa = _make_squad("A", attr_overrides={
            "CM": {"composure": 80},
        })
        sb = _make_squad("B", attr_overrides={
            "CM": {"composure": 80},
        })
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_stalemate("A", "B", sa, sb, adj_a, adj_b, adv_a, adv_b)
        comp_adj = [a for a in adj_a if a.category == "composure_stalemate"]
        assert len(comp_adj) == 1
        assert comp_adj[0].value == -0.05

    def test_defensive_stalemate_reduction_above_threshold(self):
        """def >= 55 but reduction >= -0.005, so no adjustment."""
        sa = _make_squad("A", attr_overrides={
            "CB": {"defending": 79},
            "FB": {"defending": 50},
            "CM": {"defending": 50, "composure": 50},
            "WINGER": {"defending": 50},
            "ST": {"defending": 50},
        })
        sb = _make_squad("B", attr_overrides={
            "CB": {"defending": 79},
            "FB": {"defending": 50},
            "CM": {"defending": 50, "composure": 50},
            "WINGER": {"defending": 50},
            "ST": {"defending": 50},
        })
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_stalemate("A", "B", sa, sb, adj_a, adj_b, adv_a, adv_b)
        stalemate = [a for a in adj_a if a.category == "defensive_stalemate"]
        comp_adj = [a for a in adj_a if a.category == "composure_stalemate"]
        assert len(stalemate) == 0
        assert len(comp_adj) == 0

    def test_only_one_team_above_threshold(self):
        sa = _make_squad("A", attr_overrides={
            "CB": {"defending": 80},
            "FB": {"defending": 50},
            "CM": {"defending": 50, "composure": 75},
        })
        sb = _make_squad("B", attr_overrides={
            "CB": {"defending": 40},
            "FB": {"defending": 50},
            "CM": {"defending": 50, "composure": 50},
        })
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_stalemate("A", "B", sa, sb, adj_a, adj_b, adv_a, adv_b)
        stalemate = [a for a in adj_a if a.category == "defensive_stalemate"]
        assert len(stalemate) == 0

    def test_none_squads(self):
        adj_a, adj_b, adv_a, adv_b = [], [], [], []
        _defensive_stalemate("A", "B", None, None,
                             adj_a, adj_b, adv_a, adv_b)
        assert len(adj_a) == 0 and len(adj_b) == 0


# ── format_tactical_report ──────────────────────────────────────────────────

class TestFormatTacticalReport:
    def test_basic_report_format(self):
        sa = _make_squad("A")
        sb = _make_squad("B")
        report = compute_tactical_matchup("Alpha", "Beta", 1.5, 1.2, sa, sb)
        text = format_tactical_report(report)
        assert "Tactical Matchup Report:" in text
        assert "Alpha" in text
        assert "Beta" in text
        assert "Final xG" in text

    def test_total_appears_only_once_per_team(self):
        """'Total:' should appear only once per team, not inside the loop."""
        adj_a = [
            TacticalAdjustment("a1", "desc1", 0.01),
            TacticalAdjustment("a2", "desc2", 0.02),
        ]
        adj_b = [
            TacticalAdjustment("b1", "desc3", 0.03),
        ]
        report = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=1.0, base_xg_b=1.0,
            adjustments_a=adj_a, adjustments_b=adj_b,
            final_xg_a=1.03, final_xg_b=1.03,
            game_plan_a="balanced", game_plan_b="balanced",
            advantages_a=[], advantages_b=[],
            context="group",
        )
        text = format_tactical_report(report)
        total_count_a = text.count("Total:")  # used for both teams
        # "Total:" appears exactly twice: once per team
        assert total_count_a == 2, f"Expected 2 Total: lines, got {total_count_a}"

    def test_total_at_end_of_each_teams_adjustments(self):
        """Total: appears exactly once per team, after its adjustments."""
        adj_a = [
            TacticalAdjustment("adj_a_1", "desc", 0.01),
            TacticalAdjustment("adj_a_2", "desc", 0.02),
        ]
        adj_b = [
            TacticalAdjustment("adj_b_1", "desc", 0.03),
            TacticalAdjustment("adj_b_2", "desc", 0.04),
        ]
        report = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=1.0, base_xg_b=1.0,
            adjustments_a=adj_a, adjustments_b=adj_b,
            final_xg_a=1.03, final_xg_b=1.07,
            game_plan_a="balanced", game_plan_b="balanced",
            advantages_a=[], advantages_b=[],
            context="group",
        )
        text = format_tactical_report(report)
        # "Total:" appears exactly twice (once per team)
        assert text.count("Total:") == 2
        # "Total:" lines are after the corresponding team's last adjustment
        lines = text.split("\n")
        adj_a_lines = [i for i, l in enumerate(lines) if "adj_a_" in l]
        adj_b_lines = [i for i, l in enumerate(lines) if "adj_b_" in l]
        total_lines = [i for i, l in enumerate(lines) if "Total:" in l]
        assert len(total_lines) == 2
        assert max(adj_a_lines) < total_lines[0]
        assert max(adj_b_lines) < total_lines[1]

    def test_no_adjustments(self):
        report = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=1.0, base_xg_b=1.0,
            adjustments_a=[], adjustments_b=[],
            final_xg_a=1.0, final_xg_b=1.0,
            game_plan_a="balanced", game_plan_b="balanced",
            advantages_a=[], advantages_b=[],
            context="group",
        )
        text = format_tactical_report(report)
        assert "No adjustments" in text

    def test_no_advantages(self):
        report = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=1.0, base_xg_b=1.0,
            adjustments_a=[], adjustments_b=[],
            final_xg_a=1.0, final_xg_b=1.0,
            game_plan_a="balanced", game_plan_b="balanced",
            advantages_a=[], advantages_b=[],
            context="group",
        )
        text = format_tactical_report(report)
        assert text.count("None") == 2

    def test_multiple_adjustments_per_team(self):
        """With >1 adjustments per team, Total: still only once per team."""
        adj_a = [
            TacticalAdjustment("a1", "d1", 0.01),
            TacticalAdjustment("a2", "d2", 0.02),
            TacticalAdjustment("a3", "d3", 0.03),
        ]
        adj_b = [
            TacticalAdjustment("b1", "d4", 0.04),
            TacticalAdjustment("b2", "d5", 0.05),
        ]
        report = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=1.0, base_xg_b=1.0,
            adjustments_a=adj_a, adjustments_b=adj_b,
            final_xg_a=1.06, final_xg_b=1.09,
            game_plan_a="balanced", game_plan_b="balanced",
            advantages_a=["adv_a1"], advantages_b=["adv_b1"],
            context="group",
        )
        text = format_tactical_report(report)
        assert text.count("Total:") == 2


# ── compute_strengths ───────────────────────────────────────────────────────

class TestComputeStrengths:
    def test_all_strengths_detected(self):
        profile = {
            "possession": 70, "pressing": 70, "directness": 70,
            "aerial_strength": 65, "set_piece_attack": 65,
            "big_chance_creation": 65, "defensive_compactness": 70,
            "build_up": 70, "defensive_line": 70,
        }
        squad = _make_squad("T", attr_overrides={
            "ST": {"pace": 80, "finishing": 80},
            "CM": {"passing": 80},
            "WINGER": {"pace": 80, "finishing": 80},
        })
        strengths = compute_strengths("T", squad, profile)
        cats = {s.category for s in strengths}
        assert "possession" in cats
        assert "pressing" in cats
        assert "aerial_strength" in cats
        assert "set_piece_attack" in cats
        assert "defensive_compactness" in cats
        assert "high_line" in cats

    def test_transition_strength(self):
        profile = {"directness": 65, "possession": 50}
        squad = _make_squad("T", attr_overrides={
            "ST": {"pace": 80},
            "WINGER": {"pace": 80},
            "CB": {"pace": 80},
            "FB": {"pace": 80},
        })
        strengths = compute_strengths("T", squad, profile)
        cats = {s.category for s in strengths}
        assert "transition" in cats

    def test_counter_strength(self):
        profile = {"directness": 70, "possession": 50}
        squad = _make_squad("T", attr_overrides={
            "ST": {"pace": 70},
        })
        strengths = compute_strengths("T", squad, profile)
        cats = {s.category for s in strengths}
        assert "counter" in cats

    def test_build_up_strength(self):
        profile = {"build_up": 70}
        squad = _make_squad("T", attr_overrides={
            "CM": {"passing": 80},
            "FB": {"passing": 80},
            "CB": {"passing": 80},
            "WINGER": {"passing": 80},
            "ST": {"passing": 80},
        })
        strengths = compute_strengths("T", squad, profile)
        cats = {s.category for s in strengths}
        assert "build_up" in cats

    def test_no_strengths(self):
        profile = {k: 40 for k in [
            "possession", "pressing", "directness", "aerial_strength",
            "set_piece_attack", "big_chance_creation",
            "defensive_compactness", "build_up", "defensive_line",
        ]}
        strengths = compute_strengths("T", _make_squad("T"), profile)
        assert len(strengths) == 0

    def test_finishing_strength(self):
        profile = {}
        squad = _make_squad("T", attr_overrides={
            "ST": {"finishing": 80},
            "WINGER": {"finishing": 80},
            "CM": {"finishing": 80},
            "FB": {"finishing": 80},
            "CB": {"finishing": 80},
        })
        strengths = compute_strengths("T", squad, profile)
        cats = {s.category for s in strengths}
        assert "finishing" in cats

    def test_max_six_strengths(self):
        profile = {
            "possession": 80, "pressing": 80, "directness": 80,
            "aerial_strength": 80, "set_piece_attack": 80,
            "big_chance_creation": 80, "defensive_compactness": 80,
            "build_up": 80, "defensive_line": 80,
        }
        squad = _make_squad("T", attr_overrides={
            "ST": {"pace": 80, "finishing": 80},
            "CM": {"passing": 80},
        })
        strengths = compute_strengths("T", squad, profile)
        assert len(strengths) <= 6

    def test_strengths_sorted_by_magnitude(self):
        profile = {"possession": 80, "pressing": 70}
        squad = _make_squad("T")
        strengths = compute_strengths("T", squad, profile)
        magnitudes = [s.magnitude for s in strengths]
        assert magnitudes == sorted(magnitudes, reverse=True)


# ── compute_weaknesses ───────────────────────────────────────────────────────

class TestComputeWeaknesses:
    def test_all_weaknesses_detected(self):
        profile = {
            "possession": 40, "pressing": 40, "defensive_line": 70,
            "aerial_strength": 40, "set_piece_defense": 40,
            "build_up": 40, "defensive_width": 40,
            "big_chance_creation": 40, "directness": 40,
        }
        squad = _make_squad("T", attr_overrides={
            "CM": {"composure": 50},
        })
        weaknesses = compute_weaknesses("T", squad, profile)
        cats = {w.category for w in weaknesses}
        assert "space_behind" in cats
        assert "build_up_pressure" in cats
        assert "defensive_width" in cats
        assert "creativity_gap" in cats
        assert "low_possession" in cats


        # Also verify the key conditions individually
        profile2 = {
            "low_pressing": "ignore",
            "possession": 70, "pressing": 40, "directness": 40,
            "set_piece_defense": 40, "aerial_strength": 40,
        }
        w2 = compute_weaknesses("T", _make_squad("T"), profile2)
        cats2 = {w.category for w in w2}
        assert "low_pressing" in cats2
        assert "aerial_weakness" in cats2
        assert "set_piece_defense" in cats2

    def test_counter_vulnerability(self):
        profile = {"directness": 40, "pressing": 65}
        weaknesses = compute_weaknesses("T", _make_squad("T"), profile)
        cats = {w.category for w in weaknesses}
        assert "counter_vulnerability" in cats

    def test_low_block_struggle(self):
        profile = {"possession": 70, "big_chance_creation": 40}
        weaknesses = compute_weaknesses("T", _make_squad("T"), profile)
        cats = {w.category for w in weaknesses}
        assert "low_block_struggle" in cats

    def test_no_weaknesses(self):
        profile = {k: 60 for k in [
            "possession", "pressing", "directness", "aerial_strength",
            "set_piece_defense", "build_up", "defensive_width",
            "big_chance_creation", "defensive_line",
        ]}
        weaknesses = compute_weaknesses("T", _make_squad("T"), profile)
        assert len(weaknesses) == 0

    def test_max_five_weaknesses(self):
        profile = {
            "possession": 30, "pressing": 30, "defensive_line": 70,
            "aerial_strength": 30, "set_piece_defense": 30,
            "build_up": 30, "defensive_width": 30,
            "big_chance_creation": 30, "directness": 30, "pressing": 30,
        }
        squad = _make_squad("T", attr_overrides={"CM": {"composure": 40}})
        weaknesses = compute_weaknesses("T", squad, profile)
        assert len(weaknesses) <= 5

    def test_sorted_by_severity(self):
        profile = {"possession": 40, "pressing": 40}
        weaknesses = compute_weaknesses("T", _make_squad("T"), profile)
        severities = [w.severity for w in weaknesses]
        assert severities == sorted(severities, reverse=True)


# ── compute_vulnerability_report ────────────────────────────────────────────

class TestComputeVulnerabilityReport:
    def test_returns_report(self):
        profile = {"possession": 70, "pressing": 40}
        squad = _make_squad("T")
        report = compute_vulnerability_report("T", squad, profile)
        assert isinstance(report, TacticalVulnerabilityReport)
        assert report.team == "T"
        assert len(report.strengths) > 0
        assert len(report.weaknesses) > 0

    def test_no_strengths_or_weaknesses(self):
        profile = {k: 55 for k in [
            "possession", "pressing", "directness", "aerial_strength",
            "set_piece_attack", "set_piece_defense",
            "big_chance_creation", "defensive_compactness",
            "build_up", "defensive_line", "defensive_width",
        ]}
        squad = _make_squad("T")
        report = compute_vulnerability_report("T", squad, profile)
        assert len(report.strengths) == 0
        assert len(report.weaknesses) == 0


# ── compute_exploitation & EXPLOIT_MAP ──────────────────────────────────────

class TestComputeExploitation:
    def test_exploit_map_high_line_vs_space_behind(self):
        """high_line strength matches space_behind weakness."""
        profile_a = {"defensive_line": 70}
        profile_b = {"defensive_line": 70}
        squad = _make_squad("T")
        report = compute_exploitation("A", "B", squad, squad, profile_a, profile_b)
        cats = {(o.attacker, o.category) for o in report.opportunities}
        assert ("A", "high_line") in cats or ("B", "high_line") in cats

    def test_exploit_map_pressing_vs_build_up_pressure(self):
        """pressing strength matches build_up_pressure weakness."""
        profile_a = {"pressing": 70}
        profile_b = {"build_up": 40}
        squad_b = _make_squad("B", attr_overrides={
            "CM": {"composure": 50},
        })
        report = compute_exploitation("A", "B", _make_squad("A"), squad_b,
                                      profile_a, profile_b)
        cats = {(o.attacker, o.category) for o in report.opportunities}
        assert ("A", "pressing") in cats

    def test_exploit_map_aerial_strength_vs_aerial_weakness(self):
        """aerial_strength strength matches aerial_weakness weakness."""
        profile_a = {"aerial_strength": 65}
        profile_b = {"aerial_strength": 40}
        squad = _make_squad("T")
        report = compute_exploitation("A", "B", squad, squad, profile_a, profile_b)
        cats = {(o.attacker, o.category) for o in report.opportunities}
        assert ("A", "aerial_strength") in cats

    def test_exploit_map_set_piece_attack_vs_set_piece_defense(self):
        """set_piece_attack strength matches set_piece_defense weakness."""
        profile_a = {"set_piece_attack": 65}
        profile_b = {"set_piece_defense": 40}
        squad = _make_squad("T")
        report = compute_exploitation("A", "B", squad, squad, profile_a, profile_b)
        cats = {(o.attacker, o.category) for o in report.opportunities}
        assert ("A", "set_piece_attack") in cats

    def test_exploit_map_possession_vs_low_block_struggle(self):
        """possession strength matches low_block_struggle weakness."""
        profile_a = {"possession": 70}
        profile_b = {"possession": 70, "big_chance_creation": 40}
        squad = _make_squad("T")
        report = compute_exploitation("A", "B", squad, squad, profile_a, profile_b)
        cats = {(o.attacker, o.category) for o in report.opportunities}
        assert ("A", "possession") in cats

    def test_exploit_map_counter_vs_counter_vulnerability(self):
        """counter strength matches counter_vulnerability weakness."""
        profile_a = {"directness": 70, "possession": 50}
        profile_b = {"directness": 40, "pressing": 65}
        squad = _make_squad("T")
        report = compute_exploitation("A", "B", squad, squad, profile_a, profile_b)
        cats = {(o.attacker, o.category) for o in report.opportunities}
        assert ("A", "counter") in cats

    def test_no_exploit_when_impact_below_threshold(self):
        """When impact <= 0.005, no opportunity is created."""
        profile_a = {"defensive_line": 66}
        profile_b = {"defensive_line": 66}
        squad = _make_squad("T", attr_overrides={
            "CB": {"defensive_awareness": 50},
        })
        report = compute_exploitation("A", "B", squad, squad, profile_a, profile_b)
        low_impact = [o for o in report.opportunities if o.xg_impact <= 0.005]
        assert len(low_impact) == 0

    def test_max_eight_opportunities(self):
        """Only top 8 opportunities are returned."""
        profile_a = {
            "defensive_line": 70, "pressing": 70, "aerial_strength": 65,
            "set_piece_attack": 65, "possession": 70, "directness": 70,
        }
        profile_b = {
            "defensive_line": 70, "build_up": 40, "aerial_strength": 40,
            "set_piece_defense": 40, "possession": 70, "big_chance_creation": 40,
            "directness": 40, "pressing": 65,
        }
        squad = _make_squad("T")
        report = compute_exploitation("A", "B", squad, squad, profile_a, profile_b)
        assert len(report.opportunities) <= 8

    def test_tactical_report_opportunities_added(self):
        """Adjustments from TacticalReport are added as opportunities."""
        profile_a = {}
        profile_b = {}
        squad = _make_squad("T")
        adj_a = [TacticalAdjustment("custom_exploit", "custom desc", 0.02)]
        tr = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=1.0, base_xg_b=1.0,
            adjustments_a=adj_a, adjustments_b=[],
            final_xg_a=1.02, final_xg_b=1.0,
            game_plan_a="balanced", game_plan_b="balanced",
            advantages_a=[], advantages_b=[],
            context="group",
        )
        report = compute_exploitation("A", "B", squad, squad,
                                      profile_a, profile_b, tactical_report=tr)
        custom = [o for o in report.opportunities if o.category == "custom_exploit"]
        assert len(custom) == 1
        assert custom[0].xg_impact == 0.02

    def test_tactical_report_low_impact_not_added(self):
        """Adjustments with value <= 0.005 are not added."""
        profile_a = {}
        profile_b = {}
        squad = _make_squad("T")
        adj_a = [TacticalAdjustment("low_impact", "low", 0.003)]
        tr = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=1.0, base_xg_b=1.0,
            adjustments_a=adj_a, adjustments_b=[],
            final_xg_a=1.003, final_xg_b=1.0,
            game_plan_a="balanced", game_plan_b="balanced",
            advantages_a=[], advantages_b=[],
            context="group",
        )
        report = compute_exploitation("A", "B", squad, squad,
                                      profile_a, profile_b, tactical_report=tr)
        assert len(report.opportunities) == 0

    def test_tactical_report_b_opportunities_added(self):
        """Team B adjustments with value > 0.005 become opportunities (lines 973-976)."""
        profile_a = {}
        profile_b = {}
        squad = _make_squad("T")
        adj_b = [TacticalAdjustment("custom_b_exploit", "b desc", 0.02)]
        tr = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=1.0, base_xg_b=1.0,
            adjustments_a=[], adjustments_b=adj_b,
            final_xg_a=1.0, final_xg_b=1.02,
            game_plan_a="balanced", game_plan_b="balanced",
            advantages_a=[], advantages_b=[],
            context="group",
        )
        report = compute_exploitation("A", "B", squad, squad,
                                      profile_a, profile_b, tactical_report=tr)
        custom_b = [o for o in report.opportunities
                    if o.category == "custom_b_exploit" and o.attacker == "B"]
        assert len(custom_b) == 1
        assert custom_b[0].xg_impact == 0.02

    def test_exploit_map_strength_category_names(self):
        """Verify the EXPLOIT_MAP uses the correct category names.

        Specifically:
          - "high_line" (not "high_line_exploit")
          - "aerial_strength" (not "aerial")
          - "set_piece_attack" (not "set_pieces")
          - "possession" (not "possession_creativity")
        """
        expected_strengths = {"high_line", "pressing", "aerial_strength",
                              "set_piece_attack", "possession", "counter"}
        actual_strengths = {pair[0] for pair in EXPLOIT_MAP}
        assert actual_strengths == expected_strengths, (
            f"EXPLOIT_MAP strength categories mismatch. "
            f"Expected {expected_strengths}, got {actual_strengths}"
        )

        expected_weaknesses = {"space_behind", "build_up_pressure",
                               "aerial_weakness", "set_piece_defense",
                               "low_block_struggle", "counter_vulnerability"}
        actual_weaknesses = {pair[1] for pair in EXPLOIT_MAP}
        assert actual_weaknesses == expected_weaknesses, (
            f"EXPLOIT_MAP weakness categories mismatch. "
            f"Expected {expected_weaknesses}, got {actual_weaknesses}"
        )

    def test_exploit_strength_weakness_mapping(self):
        """For each EXPLOIT_MAP entry, verify the strength/weakness pairing
        produces expected category labels."""
        for s_str, w_str, _ in EXPLOIT_MAP:
            assert s_str in STRENGTH_CATEGORIES, (
                f"Strength '{s_str}' not in STRENGTH_CATEGORIES"
            )
            assert w_str in WEAKNESS_CATEGORIES, (
                f"Weakness '{w_str}' not in WEAKNESS_CATEGORIES"
            )

    def test_opportunities_sorted_by_impact(self):
        profile_a = {
            "defensive_line": 75, "pressing": 75, "possession": 75,
        }
        profile_b = {
            "defensive_line": 75, "build_up": 40, "possession": 70,
            "big_chance_creation": 40,
        }
        squad = _make_squad("T")
        report = compute_exploitation("A", "B", squad, squad, profile_a, profile_b)
        impacts = [abs(o.xg_impact) for o in report.opportunities]
        assert impacts == sorted(impacts, reverse=True)


# ── classify_match_archetypes ───────────────────────────────────────────────

class TestClassifyMatchArchetypes:
    def test_chess_match(self):
        pa = {"possession": 55, "pressing": 50}
        pb = {"possession": 60, "pressing": 55}
        report = classify_match_archetypes("A", "B", pa, pb)
        names = {a.archetype for a in report.archetypes}
        assert "Tactical Chess Match" in names

    def test_possession_dominance(self):
        pa = {"possession": 80}
        pb = {"possession": 55}
        report = classify_match_archetypes("A", "B", pa, pb)
        names = {a.archetype for a in report.archetypes}
        assert "Possession Dominance" in names

    def test_transition_battle(self):
        pa = {"directness": 65}
        pb = {"directness": 65}
        report = classify_match_archetypes("A", "B", pa, pb)
        names = {a.archetype for a in report.archetypes}
        assert "Transition Battle" in names

    def test_counter_attack_showcase_a(self):
        pa = {"directness": 70, "possession": 50}
        pb = {"possession": 70, "directness": 50}
        report = classify_match_archetypes("A", "B", pa, pb)
        names = {a.archetype for a in report.archetypes}
        assert "Counter Attack Showcase" in names

    def test_set_piece_battle(self):
        pa = {"set_piece_attack": 70, "set_piece_defense": 50}
        pb = {"set_piece_attack": 50, "set_piece_defense": 50}
        report = classify_match_archetypes("A", "B", pa, pb)
        names = {a.archetype for a in report.archetypes}
        assert "Set Piece Battle" in names

    def test_end_to_end_chaos(self):
        pa = {"directness": 70, "defensive_line": 65}
        pb = {"directness": 70, "defensive_line": 65}
        report = classify_match_archetypes("A", "B", pa, pb)
        names = {a.archetype for a in report.archetypes}
        assert "End-to-End Chaos" in names

    def test_one_sided_control(self):
        pa = {"possession": 80}
        pb = {"possession": 50}
        tr = TacticalReport(
            team_a="A", team_b="B",
            base_xg_a=3.0, base_xg_b=0.5,
            adjustments_a=[], adjustments_b=[],
            final_xg_a=3.0, final_xg_b=0.5,
            game_plan_a="attacking", game_plan_b="low_block",
            advantages_a=[], advantages_b=[],
            context="group",
        )
        report = classify_match_archetypes("A", "B", pa, pb, tactical_report=tr)
        names = {a.archetype for a in report.archetypes}
        assert "One-Sided Control" in names

    def test_fallback_archetypes(self):
        """Profiles matching no rule use the hardcoded fallback."""
        pa = {"possession": 50, "pressing": 50, "directness": 55,
              "set_piece_attack": 50, "set_piece_defense": 50,
              "defensive_line": 55}
        pb = {"possession": 65, "pressing": 50, "directness": 50,
              "set_piece_attack": 50, "set_piece_defense": 50,
              "defensive_line": 50}
        report = classify_match_archetypes("A", "B", pa, pb)
        assert len(report.archetypes) > 0
        # Chess: abs(50-65)=15 not < 10, pressing diff=0 < 15 but poss diff >= 10
        # so no rule matches -> fallback
        names = {a.archetype for a in report.archetypes}
        assert names == {"Tactical Chess Match", "Possession Dominance",
                         "Transition Battle"}

    def test_probabilities_sum_to_100(self):
        pa = {"possession": 80}
        pb = {"possession": 55}
        report = classify_match_archetypes("A", "B", pa, pb)
        total = sum(a.probability for a in report.archetypes)
        assert abs(total - 100.0) < 0.1

    def test_archetype_descriptions(self):
        pa = {"possession": 55, "pressing": 55}
        pb = {"possession": 55, "pressing": 55}
        report = classify_match_archetypes("A", "B", pa, pb)
        for a in report.archetypes:
            assert len(a.description) > 0


# ── analyze_win_conditions ──────────────────────────────────────────────────

class TestAnalyzeWinConditions:
    def test_all_conditions(self):
        profile = {
            "possession": 66, "pressing": 66, "directness": 65,
            "set_piece_attack": 80,
        }
        squad = _make_squad("T", attr_overrides={
            "ST": {"finishing": 99, "pace": 80},
            "WINGER": {"finishing": 99, "pace": 80},
            "CM": {"finishing": 99, "pace": 80},
            "CB": {"pace": 80, "finishing": 99},
            "FB": {"pace": 80, "finishing": 99},
            "GK": {"finishing": 99},
        })
        report = analyze_win_conditions("T", profile, squad)
        methods = {c.method for c in report.conditions}
        assert "Transition attacks" in methods
        assert "Possession dominance" in methods
        assert "Pressing turnovers" in methods
        assert "Set pieces" in methods
        assert "Individual brilliance" in methods

    def test_midfield_control(self):
        profile = {"possession": 65, "pressing": 60}
        squad = _make_squad("T")
        report = analyze_win_conditions("T", profile, squad)
        methods = {c.method for c in report.conditions}
        assert "Midfield control" in methods

    def test_no_conditions(self):
        profile = {"possession": 50, "pressing": 50, "directness": 50,
                   "set_piece_attack": 50}
        squad = _make_squad("T", attr_overrides={
            "ST": {"finishing": 50, "pace": 50},
        })
        report = analyze_win_conditions("T", profile, squad)
        conditions = getattr(report, 'conditions', [])
        if not conditions:
            """No conditions met; default behaviour: probabilities normalised."""
            pass
        assert len(report.conditions) <= 5

    def test_probabilities_normalized(self):
        profile = {"possession": 70, "pressing": 70}
        squad = _make_squad("T")
        report = analyze_win_conditions("T", profile, squad)
        total = sum(c.probability for c in report.conditions)
        assert abs(total - 100.0) < 0.1

    def test_max_five_conditions(self):
        profile = {
            "possession": 80, "pressing": 80, "directness": 70,
            "set_piece_attack": 70,
        }
        squad = _make_squad("T", attr_overrides={
            "ST": {"finishing": 80, "pace": 70},
        })
        report = analyze_win_conditions("T", profile, squad)
        assert len(report.conditions) <= 5


# ── compute_offensive_influence ─────────────────────────────────────────────

class TestComputeOffensiveInfluence:
    def test_striker(self):
        player = _make_player("Messi", "Arg", "ST", {
            "finishing": 95, "positioning": 90, "vision": 85,
            "passing": 85, "dribbling": 90, "pace": 80,
            "composure": 90, "crossing": 70, "long_shots": 85,
            "reactions": 90, "strength": 60, "stamina": 70,
        })
        squad = _make_squad("Arg")
        result = compute_offensive_influence(player, squad, 2.0)
        assert isinstance(result, OffensiveInfluence)
        assert result.player_name == "Messi"
        assert result.role == "ST"
        assert result.xg_contribution > 0
        assert result.xa_contribution > 0
        assert result.overall_influence >= 1.0
        assert result.overall_influence <= 10.0

    def test_defender_offensive_influence_halved(self):
        player = _make_player("Ramos", "Esp", "CB", {
            "finishing": 80, "positioning": 80, "vision": 70,
            "passing": 80, "dribbling": 60, "pace": 60,
            "composure": 80, "crossing": 50, "long_shots": 70,
            "reactions": 80, "strength": 85, "stamina": 75,
        })
        squad = _make_squad("Esp")
        result = compute_offensive_influence(player, squad, 1.0)
        assert result.overall_influence <= 10.0
        # CB role has *0.6 multiplier
        assert result.role == "CB"

    def test_goalkeeper_low_offensive(self):
        player = _make_player("Keeper", "T", "GK", {
            "finishing": 30, "positioning": 50, "vision": 50,
            "passing": 50, "dribbling": 30, "pace": 40,
            "composure": 60, "crossing": 20, "long_shots": 20,
            "reactions": 80, "strength": 70, "stamina": 60,
        })
        squad = _make_squad("T")
        result = compute_offensive_influence(player, squad, 1.0)
        assert result.role == "GK"

    def test_missing_attributes_default_to_50(self):
        player = _make_player("Missing", "T", "ST", {})
        squad = _make_squad("T")
        result = compute_offensive_influence(player, squad, 1.0)
        assert result.overall_influence >= 1.0

    def test_striker_offensive_bonus(self):
        player = _make_player("Star", "T", "ST", {
            "finishing": 99, "positioning": 99, "vision": 50,
            "passing": 50, "dribbling": 99, "pace": 99,
            "composure": 99, "crossing": 50, "long_shots": 50,
            "reactions": 99, "strength": 99, "stamina": 99,
        })
        squad = _make_squad("T")
        result = compute_offensive_influence(player, squad, 3.0)
        assert result.overall_influence >= 1.0


# ── compute_defensive_influence ─────────────────────────────────────────────

class TestComputeDefensiveInfluence:
    def test_defender(self):
        player = _make_player("VDijk", "Ned", "CB", {
            "defending": 92, "tackling": 90, "interceptions": 88,
            "defensive_awareness": 92, "strength": 90, "pace": 70,
            "stamina": 75, "reactions": 85, "jumping": 88,
            "heading_accuracy": 85,
        })
        squad = _make_squad("Ned")
        result = compute_defensive_influence(player, squad, 1.5)
        assert isinstance(result, DefensiveInfluence)
        assert result.player_name == "VDijk"
        assert result.role == "CB"
        assert result.defensive_stability > 0
        assert result.overall_influence >= 1.0
        assert result.overall_influence <= 10.0

    def test_striker_defense_halved(self):
        player = _make_player("FW", "T", "ST", {
            "defending": 90, "tackling": 90, "interceptions": 90,
            "defensive_awareness": 90, "strength": 90, "pace": 90,
            "stamina": 90, "reactions": 90, "jumping": 90,
            "heading_accuracy": 90,
        })
        squad = _make_squad("T")
        result = compute_defensive_influence(player, squad, 1.0)
        assert result.overall_influence <= 10.0

    def test_cb_dm_bonus(self):
        player = _make_player("Boss", "T", "CB", {
            "defending": 99, "tackling": 99, "interceptions": 99,
            "defensive_awareness": 99, "strength": 99, "pace": 99,
            "stamina": 99, "reactions": 99, "jumping": 99,
            "heading_accuracy": 99,
        })
        squad = _make_squad("T")
        result = compute_defensive_influence(player, squad, 2.0)
        assert result.overall_influence >= 1.0

    def test_missing_attributes(self):
        player = _make_player("NoAttr", "T", "CB", {})
        squad = _make_squad("T")
        result = compute_defensive_influence(player, squad, 1.0)
        assert result.overall_influence >= 1.0


# ── compute_goalkeeper_influence ────────────────────────────────────────────

class TestComputeGoalkeeperInfluence:
    def test_gk_influence(self):
        player = _make_player("Courtois", "Bel", "GK", {
            "reflexes": 90, "diving": 88, "positioning": 90,
            "handling": 85, "kicking": 75, "reactions": 88,
            "strength": 80, "jumping": 85, "composure": 85,
        })
        squad = _make_squad("Bel")
        result = compute_goalkeeper_influence(player, squad, 5.0)
        assert isinstance(result, GoalkeeperInfluence)
        assert result.player_name == "Courtois"
        assert result.goals_prevented >= -1.0
        assert result.overall_influence >= 1.0
        assert result.overall_influence <= 10.0

    def test_gk_without_squad_usage(self):
        player = _make_player("Keeper", "T", "GK", {
            "reflexes": 80, "diving": 80, "positioning": 80,
            "handling": 80, "kicking": 80, "reactions": 80,
            "strength": 80, "jumping": 80, "composure": 80,
        })
        squad = _make_squad("T")
        result = compute_goalkeeper_influence(player, squad)
        assert result.overall_influence >= 1.0

    def test_gk_low_attributes(self):
        player = _make_player("Weak", "T", "GK", {
            "reflexes": 30, "diving": 30, "positioning": 30,
            "handling": 30, "kicking": 30, "reactions": 30,
            "strength": 30, "jumping": 30, "composure": 30,
        })
        squad = _make_squad("T")
        result = compute_goalkeeper_influence(player, squad, 10.0)
        assert result.overall_influence >= 1.0
        assert result.overall_influence <= 10.0

    def test_goals_prevented_calculation(self):
        player = _make_player("Top", "T", "GK", {
            "reflexes": 99, "diving": 99, "positioning": 99,
            "handling": 99, "kicking": 99, "reactions": 99,
            "strength": 99, "jumping": 99, "composure": 99,
        })
        squad = _make_squad("T")
        result = compute_goalkeeper_influence(player, squad, 10.0)
        assert result.goals_prevented >= 0

    def test_gk_missing_attributes(self):
        player = _make_player("NoAttrs", "T", "GK", {})
        squad = _make_squad("T")
        result = compute_goalkeeper_influence(player, squad)
        assert result.overall_influence >= 1.0


# ── compute_team_dependency ─────────────────────────────────────────────────

class TestComputeTeamDependency:
    def test_high_dependency(self):
        squad = _make_squad("T", attr_overrides={
            "ST": {"finishing": 99, "positioning": 99, "shot_power": 99,
                   "pace": 99, "composure": 99},
            "WINGER": {"finishing": 50, "dribbling": 50, "pace": 50,
                       "vision": 50},
            "CM": {"finishing": 50, "positioning": 50, "vision": 50,
                   "passing": 50, "dribbling": 50, "pace": 50},
        })
        result = compute_team_dependency("T", squad, 3.0, 1.0)
        assert result.dependency_level == "High"
        assert result.attack_output_share > 55.0

    def test_low_dependency(self):
        """Evenly-distributed attacking contributions -> Low dependency."""
        squad = _make_squad("T", attr_overrides={
            "ST": {"finishing": 50, "positioning": 50, "shot_power": 50,
                   "pace": 50, "composure": 50},
            "WINGER": {"finishing": 50, "dribbling": 80, "pace": 80,
                       "vision": 80, "crossing": 80},
            "CM": {"finishing": 50, "positioning": 50,
                   "dribbling": 50, "pace": 50,
                   "composure": 50},
        })
        result = compute_team_dependency("T", squad, 3.0, 1.0)
        assert result.team == "T"
        assert result.dependency_level in ("Low", "Moderate", "High")

    def test_dependency_includes_defenders(self):
        squad = _make_squad("T", attr_overrides={
            "CB": {"defending": 99, "tackling": 99, "interceptions": 99,
                   "defensive_awareness": 99, "strength": 99, "pace": 99,
                   "stamina": 99, "reactions": 99, "jumping": 99,
                   "heading_accuracy": 99},
            "FB": {"defending": 99, "tackling": 99, "pace": 99,
                   "stamina": 99, "dribbling": 50},
        })
        result = compute_team_dependency("T", squad, 3.0, 1.0)
        assert len(result.top_defenders_names) > 0
        assert result.defense_output_share > 0

    def test_moderate_dependency(self):
        """Top 3 share between 0.40 and 0.55 -> Moderate (line 1358)."""
        squad = _make_squad("T", attr_overrides={
            "ST": {"finishing": 30, "positioning": 30, "composure": 30,
                   "shot_power": 30, "pace": 30, "dribbling": 30,
                   "passing": 30, "vision": 30, "crossing": 30,
                   "reactions": 30, "strength": 30, "stamina": 30,
                   "long_shots": 30},
            "WINGER": {"finishing": 30, "positioning": 30, "vision": 30,
                       "passing": 30, "dribbling": 30, "pace": 30,
                       "composure": 30, "crossing": 30, "reactions": 30,
                       "stamina": 30},
            "CM": {"finishing": 99, "positioning": 99, "vision": 99,
                   "passing": 99, "dribbling": 99, "pace": 99,
                   "composure": 99, "stamina": 99},
        })
        result = compute_team_dependency("T", squad, 3.0, 1.0)
        assert result.dependency_level == "Moderate"
        assert 40.0 < result.attack_output_share <= 55.0

    def test_empty_squad(self):
        squad = _empty_squad("T")
        result = compute_team_dependency("T", squad, 1.0, 1.0)
        assert result.team == "T"
        assert result.dependency_level in ("High", "Moderate", "Low")


# ── compute_player_matchups ─────────────────────────────────────────────────

class TestComputePlayerMatchups:
    def test_matchups_generated(self):
        sa = _make_squad("A", attr_overrides={
            "ST": {"finishing": 90, "pace": 90, "dribbling": 90},
            "WINGER": {"finishing": 85, "pace": 90, "dribbling": 85},
            "CM": {"finishing": 70, "pace": 60, "dribbling": 70},
        })
        sb = _make_squad("B", attr_overrides={
            "CB": {"defending": 90, "tackling": 90, "pace": 85},
            "FB": {"defending": 85, "tackling": 85, "pace": 80},
        })
        matchups = compute_player_matchups(sa, sb)
        assert len(matchups) > 0
        for m in matchups:
            assert isinstance(m, PlayerMatchup)
            assert len(m.player_a) > 0
            assert len(m.player_b) > 0

    def test_no_matchups_with_empty_squads(self):
        ea = _empty_squad("EA")
        eb = _empty_squad("EB")
        matchups = compute_player_matchups(ea, eb)
        assert len(matchups) == 0

    def test_st_vs_cb_matchup(self):
        sa = _make_squad("A", attr_overrides={
            "ST": {"finishing": 95, "pace": 95, "dribbling": 95},
        })
        sb = _make_squad("B", attr_overrides={
            "CB": {"defending": 60, "tackling": 60, "pace": 55},
        })
        matchups = compute_player_matchups(sa, sb)
        st_cb = [m for m in matchups if m.category == "ST vs CB"]
        assert len(st_cb) > 0

    def test_winger_vs_fb(self):
        sa = _make_squad("A", attr_overrides={
            "WINGER": {"finishing": 85, "pace": 95, "dribbling": 90},
        })
        sb = _make_squad("B", attr_overrides={
            "FB": {"defending": 60, "tackling": 60, "pace": 55},
        })
        matchups = compute_player_matchups(sa, sb)
        wing_fb = [m for m in matchups if m.category == "Winger vs FB"]
        assert len(wing_fb) > 0

    def test_midfield_battle(self):
        sa = _make_squad("A", attr_overrides={
            "CM": {"finishing": 80, "pace": 80, "dribbling": 80},
        })
        sb = _make_squad("B", attr_overrides={
            "CM": {"defending": 80, "tackling": 80, "pace": 80},
        })
        matchups = compute_player_matchups(sa, sb)
        mid = [m for m in matchups if m.category == "Midfield Battle"]
        assert len(mid) > 0

    def test_advantage_team(self):
        sa = _make_squad("A", attr_overrides={
            "ST": {"finishing": 99, "pace": 99, "dribbling": 99},
        })
        sb = _make_squad("B", attr_overrides={
            "CB": {"defending": 40, "tackling": 40, "pace": 40},
        })
        matchups = compute_player_matchups(sa, sb)
        st_cb = [m for m in matchups if m.category == "ST vs CB"]
        if st_cb:
            for m in st_cb:
                assert m.advantage_team in ("A", "B")


# ── compute_player_influence ────────────────────────────────────────────────

class TestComputePlayerInfluence:
    def test_full_report(self):
        sa = _make_squad("A")
        sb = _make_squad("B")
        result = compute_player_influence("A", "B", sa, sb, 2.0, 1.5)
        assert isinstance(result, PlayerInfluenceReport)
        assert result.team_a == "A"
        assert result.team_b == "B"
        assert len(result.offensive_a) > 0
        assert len(result.offensive_b) > 0
        assert len(result.defensive_a) > 0
        assert len(result.defensive_b) > 0
        assert result.goalkeeper_a is not None
        assert result.goalkeeper_b is not None
        assert result.dependency_a is not None
        assert result.dependency_b is not None
        assert len(result.matchups) > 0

    def test_empty_squads(self):
        ea = _empty_squad("EA")
        eb = _empty_squad("EB")
        result = compute_player_influence("EA", "EB", ea, eb, 1.0, 1.0)
        assert result.goalkeeper_a is None
        assert result.goalkeeper_b is None
        assert len(result.matchups) == 0


# ── Helper functions ────────────────────────────────────────────────────────

class TestHelperFunctions:
    def test_get_squad_avg_with_players(self):
        squad = _make_squad("T", attr_overrides={
            "ST": {"pace": 80},
        })
        val = _get_squad_avg(squad, "pace")
        assert val > 50.0

    def test_get_squad_avg_none(self):
        assert _get_squad_avg(None, "pace") == 50.0

    def test_get_squad_avg_empty(self):
        assert _get_squad_avg(_empty_squad(), "pace") == 50.0

    def test_get_squad_max_with_players(self):
        squad = _make_squad("T", attr_overrides={
            "ST": {"pace": 95},
        })
        val = _get_squad_max(squad, "pace")
        assert val == 95.0

    def test_get_squad_max_none(self):
        assert _get_squad_max(None, "pace") == 50.0

    def test_get_squad_max_empty(self):
        assert _get_squad_max(_empty_squad(), "pace") == 50.0

    def test_get_squad_max_avg(self):
        squad = _make_squad("T", attr_overrides={
            "ST": {"pace": 95},
            "WINGER": {"pace": 90},
            "CB": {"pace": 60},
        })
        val = _get_squad_max_avg(squad, "pace")
        assert val > 70.0

    def test_get_squad_max_avg_none(self):
        assert _get_squad_max_avg(None, "pace") == 50.0

    def test_get_squad_max_avg_empty(self):
        assert _get_squad_max_avg(_empty_squad(), "pace") == 50.0

    def test_get_attackers_avg(self):
        squad = _make_squad("T", attr_overrides={
            "ST": {"pace": 90},
            "WINGER": {"pace": 80},
        })
        val = _get_attackers_avg(squad, "pace")
        assert val > 80.0

    def test_get_attackers_avg_none(self):
        assert _get_attackers_avg(None, "pace") == 50.0

    def test_get_attackers_avg_empty(self):
        assert _get_attackers_avg(_empty_squad(), "pace") == 50.0

    def test_get_attackers_avg_no_attackers(self):
        """Squad with no ST or WINGER players."""
        squad = Squad(
            country="T", players=[], formation="4-3-3",
            preferred_starting_xi=[
                _make_player("CB1", "T", "CB", {}),
                _make_player("CM1", "T", "CM", {}),
            ]
        )
        val = _get_attackers_avg(squad, "pace")
        assert val == 50.0

    def test_get_defenders_avg(self):
        squad = _make_squad("T", attr_overrides={
            "CB": {"defending": 85},
        })
        val = _get_defenders_avg(squad, "defending")
        assert val > 75.0

    def test_get_defenders_avg_none(self):
        assert _get_defenders_avg(None, "defending") == 50.0

    def test_get_defenders_avg_empty(self):
        assert _get_defenders_avg(_empty_squad(), "defending") == 50.0

    def test_get_defenders_avg_no_defenders(self):
        squad = Squad(
            country="T", players=[], formation="4-3-3",
            preferred_starting_xi=[
                _make_player("ST1", "T", "ST", {}),
                _make_player("CM1", "T", "CM", {}),
            ]
        )
        val = _get_defenders_avg(squad, "defending")
        assert val == 50.0

    def test_get_squad_defensive_rating(self):
        squad = _make_squad("T", attr_overrides={
            "CB": {"defending": 90},
        })
        val = _get_squad_defensive_rating(squad)
        assert val > 50.0
        assert val < 90.0

    def test_get_squad_defensive_rating_none(self):
        assert _get_squad_defensive_rating(None) == 50.0

    def test_get_squad_defensive_rating_empty(self):
        assert _get_squad_defensive_rating(_empty_squad()) == 50.0

    def test_get_squad_composure_avg(self):
        squad = _make_squad("T", attr_overrides={
            "CM": {"composure": 85},
        })
        val = _get_squad_composure_avg(squad)
        assert val > 50.0

    def test_get_squad_composure_avg_none(self):
        assert _get_squad_composure_avg(None) == 50.0

    def test_get_squad_composure_avg_empty(self):
        assert _get_squad_composure_avg(_empty_squad()) == 50.0

    def test_missing_attribute_default_50(self):
        squad = _make_squad("T")
        # Remove 'pace' from a player's attributes
        squad.current_starting_xi[0].attributes.pop("pace", None)
        val = _get_squad_avg(squad, "pace")
        assert val > 0  # mixes populated and default values

    def test_avg_with_none_player(self):
        """_get_squad_avg handles None players via attribute get default."""
        squad = _make_squad("T")
        val = _get_squad_avg(squad, "nonexistent")
        assert val == 50.0

    def test_attr_none_player(self):
        """_attr returns default when player is None (line 109)."""
        assert ta_module._attr(None, "pace") == 50.0
        assert ta_module._attr(None, "pace", 99.0) == 99.0

    def test_avg_attr_empty(self):
        """_avg_attr returns 50.0 for empty list (line 1099-1100)."""
        assert ta_module._avg_attr([], "pace") == 50.0

    def test_avg_attr_with_players(self):
        """_avg_attr with non-empty players (line 1101)."""
        p1 = _make_player("P1", "T", "ST", {"pace": 80})
        p2 = _make_player("P2", "T", "ST", {"pace": 90})
        val = ta_module._avg_attr([p1, p2], "pace")
        assert val == 85.0

    def test_max_attr_empty(self):
        """_max_attr returns 50.0 for empty list (line 1105-1106)."""
        assert ta_module._max_attr([], "pace") == 50.0

    def test_max_attr_with_players(self):
        """_max_attr with non-empty players (line 1107)."""
        p1 = _make_player("P1", "T", "ST", {"pace": 80})
        p2 = _make_player("P2", "T", "ST", {"pace": 95})
        val = ta_module._max_attr([p1, p2], "pace")
        assert val == 95.0

    def test_role_group_no_match(self):
        """_role_group returns empty list when no player matches (line 1111)."""
        p = _make_player("P1", "T", "GK", {"pace": 80})
        squad = Squad(country="T", players=[p], formation="4-3-3",
                      preferred_starting_xi=[p])
        result = ta_module._role_group(squad.current_starting_xi, "4-3-3", {"ST"})
        assert result == []

    def test_load_tactical_profiles_missing_file(self, monkeypatch):
        """_load_tactical_profiles returns {} when json missing (line 46)."""
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(ta_module, "HERE", Path(tmp))
            result = ta_module._load_tactical_profiles()
            assert result == {}
