"""Comprehensive pytest tests for BOTC/cogs/game.py.

Covers dataclass construction, serialisation helpers,
clock-order logic, and vote eligibility.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, os.path.join(MAY_DIR, "BOTC"))

from cogs.game import (
    PlayerState,
    Nomination,
    GameState,
    _load_state,
    _save_state,
    get_clock_order,
    can_vote,
    _username,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Dataclass construction and defaults
# ═══════════════════════════════════════════════════════════════════════════

class TestPlayerState:
    def test_default_alive(self):
        p = PlayerState(user_id=123)
        assert p.user_id == 123
        assert not p.dead
        assert not p.has_dead_vote
        assert p.sponsor_id is None

    def test_dead_player(self):
        p = PlayerState(user_id=1, dead=True, has_dead_vote=True)
        assert p.dead
        assert p.has_dead_vote

    def test_sponsored_player(self):
        p = PlayerState(user_id=2, sponsor_id=1)
        assert p.sponsor_id == 1


class TestNomination:
    def test_defaults(self):
        n = Nomination(id=1, nominator_id=1, nominee_id=2)
        assert n.nominator_id == 1
        assert n.nominee_id == 2
        assert n.accusation == "No accusation."
        assert n.defense == "No defense."
        assert n.votes == {}
        assert not n.closed
        assert n.current_clock_index == 0

    def test_with_args(self):
        n = Nomination(
            id=5,
            nominator_id=1, nominee_id=2,
            accusation="He did it",
            defense="Not me",
            votes={1: True, 2: False},
            current_clock_index=3,
            closed=True,
            expires_at=100.0,
        )
        assert n.accusation == "He did it"
        assert n.defense == "Not me"
        assert n.votes[1] is True
        assert n.current_clock_index == 3
        assert n.closed
        assert n.expires_at == 100.0


class TestGameState:
    def test_defaults(self):
        gs = GameState()
        assert gs.seating_order == []
        assert gs.players == {}

    def test_with_seating(self):
        gs = GameState(seating_order=[1, 2, 3])
        assert gs.seating_order == [1, 2, 3]

    def test_with_players(self):
        p = PlayerState(user_id=1)
        gs = GameState(players={1: p})
        assert gs.players[1].user_id == 1


# ═══════════════════════════════════════════════════════════════════════════
# 2. Serialisation helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadSaveState:
    def test_load_missing_file(self, tmp_path):
        from cogs import game as gmod
        original = gmod.STATE_FILE
        gmod.STATE_FILE = str(tmp_path / "nonexistent.json")
        try:
            assert gmod._load_state() == {}
        finally:
            gmod.STATE_FILE = original

    def test_save_and_load_full_cycle(self, tmp_path):
        from cogs import game as gmod
        original = gmod.STATE_FILE
        state_file = tmp_path / "game_state.json"
        gmod.STATE_FILE = str(state_file)
        try:
            states = {
                1: GameState(
                    seating_order=[10, 20, 30],
                    players={
                        10: PlayerState(user_id=10, dead=True, has_dead_vote=True),
                        20: PlayerState(user_id=20, dead=False),
                        30: PlayerState(user_id=30, sponsor_id=10),
                    },
                ),
            }
            gmod._save_state(states)
            assert state_file.exists()

            loaded = gmod._load_state()
            assert 1 in loaded
            gs = loaded[1]
            assert gs.seating_order == [10, 20, 30]
            assert 10 in gs.players
            assert gs.players[10].dead
            assert gs.players[10].has_dead_vote
            assert gs.players[30].sponsor_id == 10
        finally:
            gmod.STATE_FILE = original

    def test_save_empty_state(self, tmp_path):
        from cogs import game as gmod
        original = gmod.STATE_FILE
        gmod.STATE_FILE = str(tmp_path / "empty.json")
        try:
            gmod._save_state({})
            assert gmod._load_state() == {}
        finally:
            gmod.STATE_FILE = original

    def test_load_removes_is_sponsor_backward_compat(self, tmp_path):
        """Backward compat: is_sponsor key was removed from PlayerState."""
        from cogs import game as gmod
        state_file = tmp_path / "compat.json"
        raw = {
            "1": {
                "seating_order": [100],
                "players": {
                    "100": {
                        "user_id": 100,
                        "dead": False,
                        "has_dead_vote": False,
                        "sponsor_id": None,
                        "is_sponsor": False,
                    },
                },
            },
        }
        state_file.write_text(json.dumps(raw), encoding="utf-8")
        gmod.STATE_FILE = str(state_file)
        try:
            loaded = gmod._load_state()
            gs = loaded[1]
            p = gs.players[100]
            assert p.user_id == 100
            assert not hasattr(p, "is_sponsor")
        finally:
            gmod.STATE_FILE = str(tmp_path / "reset.json")

    def test_save_state_includes_all_fields(self, tmp_path):
        from cogs import game as gmod
        state_file = tmp_path / "fields.json"
        gmod.STATE_FILE = str(state_file)
        try:
            states = {
                42: GameState(
                    seating_order=[1, 2],
                    players={
                        1: PlayerState(user_id=1, dead=True, has_dead_vote=False, sponsor_id=2),
                    },
                ),
            }
            gmod._save_state(states)
            raw = json.loads(state_file.read_text(encoding="utf-8"))
            p = raw["42"]["players"]["1"]
            assert p["user_id"] == 1
            assert p["dead"] is True
            assert p["has_dead_vote"] is False
            assert p["sponsor_id"] == 2
        finally:
            gmod.STATE_FILE = str(tmp_path / "reset.json")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Clock-order logic
# ═══════════════════════════════════════════════════════════════════════════

class TestGetClockOrder:
    def test_nominee_first_in_seating(self):
        assert get_clock_order([1, 2, 3, 4], 1) == [2, 3, 4, 1]

    def test_nominee_last_in_seating(self):
        assert get_clock_order([1, 2, 3, 4], 4) == [1, 2, 3, 4]

    def test_nominee_middle(self):
        assert get_clock_order([1, 2, 3, 4, 5], 3) == [4, 5, 1, 2, 3]

    def test_two_players(self):
        assert get_clock_order([1, 2], 1) == [2, 1]

    def test_value_error_if_missing(self):
        with pytest.raises(ValueError):
            get_clock_order([1, 2, 3], 99)

    def test_clock_order_length(self):
        seating = [10, 20, 30, 40, 50]
        result = get_clock_order(seating, 30)
        assert len(result) == len(seating)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Vote eligibility
# ═══════════════════════════════════════════════════════════════════════════

class TestCanVote:
    def test_live_player_can_vote(self):
        assert can_vote(PlayerState(user_id=1))

    def test_dead_with_vote_can_vote(self):
        assert can_vote(PlayerState(user_id=1, dead=True, has_dead_vote=True))

    def test_dead_without_vote_cannot_vote(self):
        assert not can_vote(PlayerState(user_id=1, dead=True, has_dead_vote=False))

    def test_none_player_cannot_vote(self):
        assert not can_vote(None)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Misc helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestUsername:
    def test_format(self):
        assert _username(12345) == "<@12345>"
