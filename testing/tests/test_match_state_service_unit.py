from __future__ import annotations

import pytest
from fifa_data.services.match_state_service import MatchStateService
from fifa_data.models.match_state import (
    MatchPhase, MatchState, EXTRA_TIME_PHASES, PHASE_ORDER,
)
from fifa_data.models.player import Player
from fifa_data.models.player_match_state import PlayerMatchState
from fifa_data.models.squad import Squad
from fifa_data.models.tactical_state import ManagerProfile


@pytest.fixture
def service():
    return MatchStateService()


@pytest.fixture
def state():
    return MatchState(team_a="Brazil", team_b="Germany")


@pytest.fixture
def squad():
    players = [
        Player(name=f"Player{i}", country="Brazil", positions=("GK",) if i == 0 else ("CB",),
               attributes={"reflexes": 60.0, "diving": 50.0, "positioning": 50.0, "handling": 50.0, "defending": 50.0, "pace": 50.0})
        for i in range(11)
    ]
    return Squad(country="Brazil", players=players, formation="4-4-2", preferred_starting_xi=list(players))


class TestInitializeMatchState:
    def test_initializes_with_players(self, service, squad):
        state = service.initialize_match_state("Brazil", "Germany", squad, squad)
        assert len(state.team_a_players) == 11
        assert len(state.team_b_players) == 11


class TestAdvancePhase:
    def test_advances_through_phases(self, service, state):
        state.current_phase = MatchPhase.EARLY_FIRST_HALF
        for _ in range(5):
            service.advance_phase(state)
        assert state.current_phase == MatchPhase.LATE_SECOND_HALF

    def test_advance_to_extratime_from_normal(self, service, state):
        state.current_phase = MatchPhase.LATE_SECOND_HALF
        service.advance_phase(state, is_extra_time=True)
        assert state.current_phase == MatchPhase.EXTRA_TIME_FIRST

    def test_advance_extratime_phases(self, service, state):
        state.current_phase = MatchPhase.EXTRA_TIME_FIRST
        service.advance_phase(state, is_extra_time=True)
        assert state.current_phase == MatchPhase.EXTRA_TIME_SECOND

    def test_advance_extra_time_stays_at_last(self, service, state):
        state.current_phase = MatchPhase.EXTRA_TIME_SECOND
        service.advance_phase(state, is_extra_time=True)
        assert state.current_phase == MatchPhase.EXTRA_TIME_SECOND

    def test_advance_invalid_phase_resets(self, service, state):
        state.current_phase = "BAD_PHASE"
        service.advance_phase(state)
        assert state.current_phase == MatchPhase.EARLY_FIRST_HALF


class TestDeterminePhaseMinutes:
    def test_regular_phase(self, service):
        assert service.determine_phase_minutes(MatchPhase.EARLY_FIRST_HALF) == 15

    def test_extra_time_phase(self, service):
        assert service.determine_phase_minutes(MatchPhase.EXTRA_TIME_FIRST) == 15

    def test_extra_time_second_phase(self, service):
        assert service.determine_phase_minutes(MatchPhase.EXTRA_TIME_SECOND) == 15


class TestGetScorelineState:
    def test_winning(self, service, state):
        state.scoreline.goals_a = 2
        state.scoreline.goals_b = 0
        assert service.get_scoreline_state("Brazil", state) == "winning_2+"

    def test_drawing(self, service, state):
        assert service.get_scoreline_state("Brazil", state) == "drawing"


class TestGetRelativeStrength:
    def test_normal(self, service):
        r1, r2 = service.get_relative_strength(2.0, 1.0)
        assert abs(r1 - 2/3) < 0.001
        assert abs(r2 - 1/3) < 0.001

    def test_zero_total(self, service):
        r1, r2 = service.get_relative_strength(0, 0)
        assert r1 == 0.5
        assert r2 == 0.5

    def test_negative_protection(self, service):
        r1, r2 = service.get_relative_strength(-1, -1)
        assert r1 == 0.5
        assert r2 == 0.5


class TestCalculatePossession:
    def test_balanced_vs_balanced(self, service):
        p = service.calculate_possession(1.5, 1.0, "balanced", "balanced", 0, 0)
        assert 0.2 <= p <= 0.8

    def test_high_press_vs_low_block(self, service):
        p = service.calculate_possession(1.5, 1.0, "high_press", "low_block", 0, 0)
        assert p > 0.45

    def test_with_red_cards(self, service):
        p = service.calculate_possession(1.5, 1.0, "balanced", "balanced", 1, 0)
        assert 0.2 <= p <= 0.8

    def test_park_the_bus_possession(self, service):
        p = service.calculate_possession(0.5, 2.0, "park_the_bus", "attacking", 0, 0)
        assert 0.2 <= p <= 0.8


class TestEvaluateManagerReaction:
    def test_no_manager_trailing_attacks(self, service):
        result = service.evaluate_manager_reaction(None, "trailing", 60, "balanced")
        assert result == "attacking"

    def test_no_manager_winning_switches_to_counter(self, service):
        result = service.evaluate_manager_reaction(None, "winning", 75, "balanced")
        assert result == "counter"

    def test_trailing_with_manager_at_60(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=60, tactical_flexibility=70, defensive_discipline=50, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "trailing", 65, "balanced")
        assert result == "attacking"

    def test_trailing_low_risk_no_switch(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=40, tactical_flexibility=70, defensive_discipline=50, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "trailing", 60, "balanced")
        assert result is None

    def test_trailing_2plus_attacking(self, service):
        result = service.evaluate_manager_reaction(None, "trailing_2+", 55, "balanced")
        assert result == "attacking"

    def test_trailing_2plus_early_no_switch(self, service):
        result = service.evaluate_manager_reaction(None, "trailing_2+", 45, "balanced")
        assert result is None

    def test_drawing_no_change(self, service):
        result = service.evaluate_manager_reaction(None, "drawing", 45, "balanced")
        assert result is None

    def test_no_change_before_minute(self, service):
        result = service.evaluate_manager_reaction(None, "trailing", 45, "balanced")
        assert result is None

    def test_low_flex_does_not_block_urgent_change(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=70, tactical_flexibility=30, defensive_discipline=50, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "trailing", 70, "balanced")
        assert result == "attacking"

    def test_low_flex_blocks_non_urgent_change(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=40, tactical_flexibility=30, defensive_discipline=50, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "trailing", 55, "counter")
        assert result is None

    def test_high_risk_managers_trailing_to_attacking(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=70, tactical_flexibility=70, defensive_discipline=50, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "trailing", 60, "balanced")
        assert result == "attacking"

    def test_winning_stays_at_low_block(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=50, tactical_flexibility=60, defensive_discipline=75, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "winning", 80, "low_block")
        assert result == "low_block"

    def test_winning_goes_counter_with_good_discipline(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=50, tactical_flexibility=70, defensive_discipline=68, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "winning", 80, "balanced")
        assert result == "counter"

    def test_winning_goes_low_block_with_great_discipline(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=50, tactical_flexibility=70, defensive_discipline=75, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "winning", 85, "counter")
        assert result == "low_block"

    def test_winning_early_no_change(self, service):
        result = service.evaluate_manager_reaction(None, "winning", 65, "balanced")
        assert result is None

    def test_drawing_high_risk_attacking_change(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=70, tactical_flexibility=70, defensive_discipline=50, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "drawing", 80, "balanced")
        assert result == "attacking"

    def test_drawing_low_risk_no_change(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=50, tactical_flexibility=70, defensive_discipline=50, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "drawing", 70, "balanced")
        assert result is None

    def test_trailing_no_change_when_already_attacking(self, service):
        result = service.evaluate_manager_reaction(None, "trailing", 75, "attacking")
        assert result is None

    def test_low_flex_current_not_balanced_returns_none(self, service):
        manager = ManagerProfile(name="M", risk_tolerance=40, tactical_flexibility=30, defensive_discipline=50, pressing_preference=50)
        result = service.evaluate_manager_reaction(manager, "drawing", 80, "counter")
        assert result is None
