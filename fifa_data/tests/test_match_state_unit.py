import pytest

from fifa_data.models.match_state import (
    MatchPhase,
    MatchState,
    PhaseStats,
    ScorelineState,
)


# ============================================================
# PhaseStats
# ============================================================

class TestPhaseStats:
    def test_default_construction(self):
        ps = PhaseStats()
        assert ps.possession == 50.0
        assert ps.attacks == 0
        assert ps.dangerous_attacks == 0
        assert ps.shots == 0
        assert ps.shots_on_target == 0
        assert ps.big_chances == 0
        assert ps.xg == 0.0
        assert ps.goals == 0
        assert ps.corners == 0
        assert ps.fouls == 0
        assert ps.yellow_cards == 0
        assert ps.red_cards == 0

    def test_custom_values(self):
        ps = PhaseStats(
            possession=60.0,
            attacks=10,
            dangerous_attacks=5,
            shots=8,
            shots_on_target=3,
            big_chances=2,
            xg=1.5,
            goals=1,
            corners=4,
            fouls=6,
            yellow_cards=2,
            red_cards=0,
        )
        assert ps.possession == 60.0
        assert ps.attacks == 10
        assert ps.dangerous_attacks == 5
        assert ps.shots == 8
        assert ps.shots_on_target == 3
        assert ps.big_chances == 2
        assert ps.xg == 1.5
        assert ps.goals == 1
        assert ps.corners == 4
        assert ps.fouls == 6
        assert ps.yellow_cards == 2
        assert ps.red_cards == 0


# ============================================================
# ScorelineState – unit / branch / regression
# ============================================================

class TestScorelineState:
    def test_is_draw_true(self):
        s = ScorelineState(goals_a=2, goals_b=2)
        assert s.is_draw is True

    def test_is_draw_false(self):
        s = ScorelineState(goals_a=2, goals_b=1)
        assert s.is_draw is False

    def test_goal_difference_positive(self):
        s = ScorelineState(goals_a=3, goals_b=1)
        assert s.goal_difference == 2

    def test_goal_difference_negative(self):
        s = ScorelineState(goals_a=1, goals_b=3)
        assert s.goal_difference == -2

    def test_goal_difference_zero(self):
        s = ScorelineState(goals_a=0, goals_b=0)
        assert s.goal_difference == 0

    # --- description_for_team / team A ---------------------------------

    def test_description_for_team_a_winning_2plus(self):
        s = ScorelineState(goals_a=3, goals_b=0)
        assert s.description_for_team("A", "A", "B") == "winning_2+"

    def test_description_for_team_a_winning_1(self):
        s = ScorelineState(goals_a=1, goals_b=0)
        assert s.description_for_team("A", "A", "B") == "winning"

    def test_description_for_team_a_trailing_2plus(self):
        s = ScorelineState(goals_a=0, goals_b=3)
        assert s.description_for_team("A", "A", "B") == "trailing_2+"

    def test_description_for_team_a_trailing_1(self):
        s = ScorelineState(goals_a=0, goals_b=1)
        assert s.description_for_team("A", "A", "B") == "trailing"

    def test_description_for_team_a_drawing(self):
        s = ScorelineState(goals_a=1, goals_b=1)
        assert s.description_for_team("A", "A", "B") == "drawing"

    # --- description_for_team / team B ---------------------------------

    def test_description_for_team_b_winning_2plus(self):
        s = ScorelineState(goals_a=0, goals_b=3)
        assert s.description_for_team("B", "A", "B") == "winning_2+"

    def test_description_for_team_b_winning_1(self):
        s = ScorelineState(goals_a=0, goals_b=1)
        assert s.description_for_team("B", "A", "B") == "winning"

    def test_description_for_team_b_trailing_2plus(self):
        s = ScorelineState(goals_a=3, goals_b=0)
        assert s.description_for_team("B", "A", "B") == "trailing_2+"

    def test_description_for_team_b_trailing_1(self):
        s = ScorelineState(goals_a=1, goals_b=0)
        assert s.description_for_team("B", "A", "B") == "trailing"

    def test_description_for_team_b_drawing(self):
        s = ScorelineState(goals_a=1, goals_b=1)
        assert s.description_for_team("B", "A", "B") == "drawing"

    # --- trailing_by_two_plus -------------------------------------------

    def test_trailing_by_two_plus_team_a_true(self):
        s = ScorelineState(goals_a=0, goals_b=2)
        assert s.trailing_by_two_plus("A", "A", "B") is True

    def test_trailing_by_two_plus_team_a_false(self):
        s = ScorelineState(goals_a=1, goals_b=2)
        assert s.trailing_by_two_plus("A", "A", "B") is False

    def test_trailing_by_two_plus_team_a_false_when_leading(self):
        s = ScorelineState(goals_a=2, goals_b=0)
        assert s.trailing_by_two_plus("A", "A", "B") is False

    def test_trailing_by_two_plus_team_b_true(self):
        s = ScorelineState(goals_a=3, goals_b=1)
        assert s.trailing_by_two_plus("B", "A", "B") is True

    def test_trailing_by_two_plus_team_b_false(self):
        s = ScorelineState(goals_a=2, goals_b=1)
        assert s.trailing_by_two_plus("B", "A", "B") is False

    def test_trailing_by_two_plus_team_b_false_when_leading(self):
        s = ScorelineState(goals_a=0, goals_b=2)
        assert s.trailing_by_two_plus("B", "A", "B") is False

    # --- edge cases -----------------------------------------------------

    def test_description_zero_goals(self):
        s = ScorelineState(goals_a=0, goals_b=0)
        assert s.description_for_team("A", "A", "B") == "drawing"
        assert s.description_for_team("B", "A", "B") == "drawing"

    def test_trailing_by_two_plus_exact_two(self):
        s = ScorelineState(goals_a=0, goals_b=2)
        assert s.trailing_by_two_plus("A", "A", "B") is True

    def test_trailing_by_two_plus_large_margin(self):
        s = ScorelineState(goals_a=0, goals_b=5)
        assert s.trailing_by_two_plus("A", "A", "B") is True

    def test_trailing_by_two_plus_team_b_exact_two(self):
        s = ScorelineState(goals_a=2, goals_b=0)
        assert s.trailing_by_two_plus("B", "A", "B") is True


# ============================================================
# MatchState – unit tests
# ============================================================

class TestMatchState:
    # --- construction ---------------------------------------------------

    def test_default_construction(self):
        ms = MatchState(team_a="A", team_b="B")
        assert ms.team_a == "A"
        assert ms.team_b == "B"
        assert ms.team_a_players == {}
        assert ms.team_b_players == {}
        assert isinstance(ms.scoreline, ScorelineState)
        assert ms.scoreline.goals_a == 0
        assert ms.scoreline.goals_b == 0
        assert ms.momentum_a == 0.0
        assert ms.momentum_b == 0.0
        assert ms.current_phase == MatchPhase.EARLY_FIRST_HALF
        assert ms.minute == 0.0
        assert ms.game_plan_a == "balanced"
        assert ms.game_plan_b == "balanced"
        assert ms.game_plan_history_a == []
        assert ms.game_plan_history_b == []
        assert ms.events == []
        assert ms.substitutions == []
        assert ms.phase_stats_a == {}
        assert ms.phase_stats_b == {}
        assert ms.is_extra_time is False
        assert ms.is_penalty_shootout is False
        assert ms.red_card_count_a == 0
        assert ms.red_card_count_b == 0
        assert ms.total_possession_a == 0.0
        assert ms.total_possession_b == 0.0
        assert ms.phase_count == 0

    def test_custom_construction(self):
        ms = MatchState(
            team_a="Home",
            team_b="Away",
            current_phase=MatchPhase.LATE_SECOND_HALF,
            minute=80.0,
            is_extra_time=True,
            is_penalty_shootout=False,
            red_card_count_a=1,
        )
        assert ms.team_a == "Home"
        assert ms.team_b == "Away"
        assert ms.current_phase == MatchPhase.LATE_SECOND_HALF
        assert ms.minute == 80.0
        assert ms.is_extra_time is True
        assert ms.red_card_count_a == 1

    # --- get_player_state -----------------------------------------------

    def test_get_player_state_found_team_a(self):
        from fifa_data.models.player_match_state import PlayerMatchState
        p = PlayerMatchState(player_name="Messi", country="ARG", position="ST")
        ms = MatchState(team_a="ARG", team_b="BRA", team_a_players={"Messi": p})
        result = ms.get_player_state("ARG", "Messi")
        assert result is p

    def test_get_player_state_found_team_b(self):
        from fifa_data.models.player_match_state import PlayerMatchState
        p = PlayerMatchState(player_name="Neymar", country="BRA", position="ST")
        ms = MatchState(team_a="ARG", team_b="BRA", team_b_players={"Neymar": p})
        result = ms.get_player_state("BRA", "Neymar")
        assert result is p

    def test_get_player_state_missing_player(self):
        ms = MatchState(team_a="ARG", team_b="BRA")
        result = ms.get_player_state("ARG", "Messi")
        assert result is None

    def test_get_player_state_missing_team(self):
        ms = MatchState(team_a="ARG", team_b="BRA")
        result = ms.get_player_state("FRA", "Mbappe")
        assert result is None

    def test_get_player_state_empty_pool(self):
        ms = MatchState(team_a="ARG", team_b="BRA", team_a_players={})
        assert ms.get_player_state("ARG", "Messi") is None

    # --- get_team_energy_avg --------------------------------------------

    def test_get_team_energy_avg_empty_pool_returns_100(self):
        ms = MatchState(team_a="A", team_b="B")
        assert ms.get_team_energy_avg("A") == 100.0
        assert ms.get_team_energy_avg("B") == 100.0

    def test_get_team_energy_avg_all_players(self):
        from fifa_data.models.player_match_state import PlayerMatchState
        p1 = PlayerMatchState(player_name="X", country="A", position="CM", energy=90.0)
        p2 = PlayerMatchState(player_name="Y", country="A", position="CM", energy=70.0)
        ms = MatchState(team_a="A", team_b="B", team_a_players={"X": p1, "Y": p2})
        assert ms.get_team_energy_avg("A") == 80.0

    def test_get_team_energy_avg_excludes_substituted(self):
        from fifa_data.models.player_match_state import PlayerMatchState
        p1 = PlayerMatchState(player_name="X", country="A", position="CM", energy=90.0)
        p2 = PlayerMatchState(
            player_name="Y", country="A", position="CM",
            energy=70.0, was_substituted=True,
        )
        ms = MatchState(team_a="A", team_b="B", team_a_players={"X": p1, "Y": p2})
        assert ms.get_team_energy_avg("A") == 90.0

    def test_get_team_energy_avg_all_substituted_returns_100(self):
        from fifa_data.models.player_match_state import PlayerMatchState
        p1 = PlayerMatchState(
            player_name="X", country="A", position="CM",
            energy=90.0, was_substituted=True,
        )
        p2 = PlayerMatchState(
            player_name="Y", country="A", position="CM",
            energy=70.0, was_substituted=True,
        )
        ms = MatchState(team_a="A", team_b="B", team_a_players={"X": p1, "Y": p2})
        assert ms.get_team_energy_avg("A") == 100.0

    def test_get_team_energy_avg_team_b(self):
        from fifa_data.models.player_match_state import PlayerMatchState
        p = PlayerMatchState(player_name="Z", country="B", position="ST", energy=85.0)
        ms = MatchState(team_a="A", team_b="B", team_b_players={"Z": p})
        assert ms.get_team_energy_avg("B") == 85.0

    def test_get_team_energy_avg_empty_team_b(self):
        ms = MatchState(team_a="A", team_b="B")
        assert ms.get_team_energy_avg("B") == 100.0

    # --- record_phase ---------------------------------------------------

    def test_record_phase_creates_stats(self):
        ms = MatchState(team_a="A", team_b="B")
        assert ms.phase_count == 0
        ms.record_phase()
        assert ms.phase_count == 1
        key = MatchPhase.EARLY_FIRST_HALF.value
        assert key in ms.phase_stats_a
        assert key in ms.phase_stats_b
        assert isinstance(ms.phase_stats_a[key], PhaseStats)
        assert isinstance(ms.phase_stats_b[key], PhaseStats)

    def test_record_phase_does_not_overwrite_existing(self):
        ms = MatchState(team_a="A", team_b="B")
        key = MatchPhase.EARLY_FIRST_HALF.value
        ms.phase_stats_a[key] = PhaseStats(possession=70.0)
        ms.phase_stats_b[key] = PhaseStats(possession=30.0)
        ms.record_phase()
        assert ms.phase_stats_a[key].possession == 70.0
        assert ms.phase_stats_b[key].possession == 30.0
        assert ms.phase_count == 1

    def test_record_phase_multiple_phases(self):
        ms = MatchState(team_a="A", team_b="B")
        ms.record_phase()
        ms.current_phase = MatchPhase.MID_FIRST_HALF
        ms.record_phase()
        assert ms.phase_count == 2
        assert MatchPhase.EARLY_FIRST_HALF.value in ms.phase_stats_a
        assert MatchPhase.MID_FIRST_HALF.value in ms.phase_stats_a

    # --- get_current_phase_stats ----------------------------------------

    def test_get_current_phase_stats_team_a_creates_if_missing(self):
        ms = MatchState(team_a="A", team_b="B")
        key = MatchPhase.EARLY_FIRST_HALF.value
        assert key not in ms.phase_stats_a
        ps = ms.get_current_phase_stats("A")
        assert isinstance(ps, PhaseStats)
        assert key in ms.phase_stats_a

    def test_get_current_phase_stats_team_b_creates_if_missing(self):
        ms = MatchState(team_a="A", team_b="B")
        key = MatchPhase.EARLY_FIRST_HALF.value
        assert key not in ms.phase_stats_b
        ps = ms.get_current_phase_stats("B")
        assert isinstance(ps, PhaseStats)
        assert key in ms.phase_stats_b

    def test_get_current_phase_stats_team_a_returns_existing(self):
        ms = MatchState(team_a="A", team_b="B")
        key = MatchPhase.EARLY_FIRST_HALF.value
        existing = PhaseStats(possession=65.0)
        ms.phase_stats_a[key] = existing
        ps = ms.get_current_phase_stats("A")
        assert ps is existing
        assert ps.possession == 65.0

    def test_get_current_phase_stats_team_b_returns_existing(self):
        ms = MatchState(team_a="A", team_b="B")
        key = MatchPhase.EARLY_FIRST_HALF.value
        existing = PhaseStats(possession=35.0)
        ms.phase_stats_b[key] = existing
        ps = ms.get_current_phase_stats("B")
        assert ps is existing
        assert ps.possession == 35.0

    def test_get_current_phase_stats_different_phase_creates_new(self):
        ms = MatchState(team_a="A", team_b="B")
        ms.current_phase = MatchPhase.LATE_SECOND_HALF
        key = MatchPhase.LATE_SECOND_HALF.value
        assert key not in ms.phase_stats_a
        ps = ms.get_current_phase_stats("A")
        assert isinstance(ps, PhaseStats)
        assert key in ms.phase_stats_a

    # --- phases property ------------------------------------------------

    def test_phases_empty(self):
        ms = MatchState(team_a="A", team_b="B")
        assert ms.phases == []

    def test_phases_with_recorded(self):
        ms = MatchState(team_a="A", team_b="B")
        ms.phase_stats_a["0-15"] = PhaseStats()
        ms.phase_stats_a["15-30"] = PhaseStats()
        assert ms.phases == ["0-15", "15-30"]

    def test_phases_only_from_phase_stats_a(self):
        ms = MatchState(team_a="A", team_b="B")
        ms.phase_stats_a["0-15"] = PhaseStats()
        ms.phase_stats_b["15-30"] = PhaseStats()
        assert ms.phases == ["0-15"]

    # --- is_knockout / set_knockout -------------------------------------

    def test_is_knockout_defaults_false(self):
        ms = MatchState(team_a="A", team_b="B")
        assert ms.is_knockout() is False

    def test_set_knockout_is_noop(self):
        ms = MatchState(team_a="A", team_b="B")
        ms.set_knockout()
        assert True  # just verify no exception

    # --- edge cases -----------------------------------------------------

    def test_get_player_state_with_empty_team_b_pool(self):
        from fifa_data.models.player_match_state import PlayerMatchState
        p = PlayerMatchState(player_name="P1", country="A", position="GK")
        ms = MatchState(
            team_a="A", team_b="B",
            team_a_players={"P1": p},
            team_b_players={},
        )
        assert ms.get_player_state("A", "P1") is p
        assert ms.get_player_state("A", "Nobody") is None
        assert ms.get_player_state("B", "P1") is None

    def test_scoreline_accessed_via_match_state(self):
        ms = MatchState(team_a="A", team_b="B")
        ms.scoreline.goals_a = 3
        ms.scoreline.goals_b = 0
        assert ms.scoreline.is_draw is False
        assert ms.scoreline.goal_difference == 3
        assert ms.scoreline.description_for_team("A", "A", "B") == "winning_2+"

    def test_record_phase_and_get_stats_integration(self):
        ms = MatchState(team_a="Home", team_b="Away")
        ms.record_phase()
        ps_a = ms.get_current_phase_stats("Home")
        ps_b = ms.get_current_phase_stats("Away")
        assert ps_a.possession == 50.0
        assert ps_b.possession == 50.0
        ps_a.possession = 55.0
        ps_b.possession = 45.0
        assert ms.phase_stats_a[MatchPhase.EARLY_FIRST_HALF.value].possession == 55.0
        assert ms.phase_stats_b[MatchPhase.EARLY_FIRST_HALF.value].possession == 45.0

    def test_phases_after_multiple_recordings(self):
        ms = MatchState(team_a="A", team_b="B")
        ms.record_phase()
        ms.current_phase = MatchPhase.MID_FIRST_HALF
        ms.record_phase()
        ms.current_phase = MatchPhase.LATE_FIRST_HALF
        ms.record_phase()
        assert ms.phases == [
            MatchPhase.EARLY_FIRST_HALF.value,
            MatchPhase.MID_FIRST_HALF.value,
            MatchPhase.LATE_FIRST_HALF.value,
        ]
        assert ms.phase_count == 3
