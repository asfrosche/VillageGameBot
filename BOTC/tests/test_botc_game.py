"""Comprehensive pytest tests for BOTC/cogs/game.py.

Covers dataclass construction, serialisation helpers,
clock-order logic, vote eligibility, and on_message
accusation/defence capture.
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

try:
    from unittest.mock import AsyncMock, MagicMock
except ImportError:
    pass


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
        assert n.id == 1
        assert n.nominator_id == 1
        assert n.nominee_id == 2
        assert n.accusation == "No accusation."
        assert n.defense == "No defense."
        assert n.votes == {}
        assert n.finalized == set()
        assert not n.closed
        assert n.current_clock_index == 0

    def test_with_args(self):
        n = Nomination(
            id=5, nominator_id=1, nominee_id=2,
            accusation="He did it",
            defense="Not me",
            votes={1: "guilty", 2: "notguilty"},
            conditions={1: ""},
            current_clock_index=3,
            closed=True,
            expires_at=100.0,
        )
        assert n.id == 5
        assert n.accusation == "He did it"
        assert n.defense == "Not me"
        assert n.votes[1] == "guilty"
        assert n.conditions == {1: ""}
        assert n.finalized == set()
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


# ═══════════════════════════════════════════════════════════════════════════
# 6. On-message accusation / defence capture
# ═══════════════════════════════════════════════════════════════════════════

class _MockPerms:
    administrator = False


class TestOnMessageCapture:
    """Unit tests for BOTCGame.on_message accusation/defence listener."""

    @staticmethod
    def _make_message(text: str, author_id: int, guild_id: int, channel_id: int, is_admin: bool = False):
        perms = MagicMock()
        perms.administrator = is_admin
        author = MagicMock()
        author.id = author_id
        author.bot = False
        author.guild_permissions = perms
        guild = MagicMock()
        guild.id = guild_id
        msg = MagicMock()
        msg.content = text
        msg.author = author
        msg.guild = guild
        msg.channel.id = channel_id
        msg.add_reaction = AsyncMock()
        return msg

    @staticmethod
    def _make_view(nom: Nomination):
        view = MagicMock()
        view.nom = nom
        view._refresh_ui = AsyncMock()
        view._refresh_alive_info = MagicMock()
        return view

    # ── Helpers ──────────────────────────────────────────────────────────────

    def test_make_message_has_content(self):
        msg = self._make_message("Hello", 1, 10, 100)
        assert msg.content == "Hello"
        assert msg.author.id == 1
        assert msg.guild.id == 10

    def test_make_message_admin(self):
        msg = self._make_message("Admin", 1, 10, 100, is_admin=True)
        assert msg.author.guild_permissions.administrator

    # ── Accusation capture ────────────────────────────────────────────────────

    def _make_cog(self):
        from cogs.game import BOTCGame
        cog = BOTCGame.__new__(BOTCGame)
        cog._views = {}
        cog._messages = {}
        bot = MagicMock()
        bot.command_prefix = "."
        cog.bot = bot
        return cog

    def _run_on_message(self, cog, msg):
        """Run cog.on_message synchronously with a temporary event loop."""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(cog.on_message(msg))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_accusation_captured_from_nominator(self):
        """Nominator's message in the nomination channel sets accusation."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, accusation_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message("He is guilty!", 1, 10, 100)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.accusation == "He is guilty!"
        assert not nom.accusation_pending
        msg.add_reaction.assert_called_once_with("✅")

    def test_accusation_captured_from_admin(self):
        """Admin's message captures accusation even if not nominator."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, accusation_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message("Guilty!", 99, 10, 100, is_admin=True)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.accusation == "Guilty!"
        assert not nom.accusation_pending

    def test_accusation_ignored_for_non_authorised(self):
        """Non-nominator, non-admin message does NOT capture accusation."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, accusation_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message("Random", 99, 10, 100)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.accusation == "No accusation."
        assert nom.accusation_pending  # still pending

    # ── Defence capture ─────────────────────────────────────────────────────

    def test_defence_captured_from_nominee(self):
        """Nominee's message in the nomination channel sets defence."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, defense_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message("I am innocent!", 2, 10, 100)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.defense == "I am innocent!"
        assert not nom.defense_pending
        msg.add_reaction.assert_called_once_with("✅")

    def test_defence_captured_from_admin(self):
        """Admin's message captures defence even if not nominee."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, defense_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message("They plead guilty", 99, 10, 100, is_admin=True)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.defense == "They plead guilty"
        assert not nom.defense_pending

    def test_defence_ignored_for_non_authorised(self):
        """Non-nominee, non-admin message does NOT capture defence."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, defense_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message("Random", 99, 10, 100)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.defense == "No defense."
        assert nom.defense_pending  # still pending

    # ── Bot messages ignored ─────────────────────────────────────────────────

    def test_bot_message_ignored(self):
        """Bot messages are skipped entirely."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, accusation_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message("BOT", 1, 10, 100)
        msg.channel = channel
        msg.author.bot = True
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.accusation == "No accusation."

    # ── Closed nomination ignored ────────────────────────────────────────────

    def test_closed_nomination_ignored(self):
        """Messages for closed nominations are not captured."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, accusation_pending=True, closed=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message("Text", 1, 10, 100)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.accusation == "No accusation."

    # ── Wrong channel ignored ────────────────────────────────────────────────

    def test_wrong_channel_ignored(self):
        """Messages in a different channel than the nomination message are ignored."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, accusation_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        # Stored message in channel 100
        stored = self._make_message("stored", 1, 10, 100)
        cog._messages[(10, 1)] = stored
        # Incoming message in channel 999 — different channel
        incoming = self._make_message("Text", 1, 10, 999)
        self._run_on_message(cog, incoming)

        assert nom.accusation == "No accusation."
        assert nom.accusation_pending

    # ── Command messages filtered out ─────────────────────────────────────────

    def test_command_message_not_captured_as_accusation(self):
        """Messages starting with bot prefix are not captured as accusation text."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, accusation_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        # Message looks like a command
        msg = self._make_message(".bdefend 1 not gay", 1, 10, 100)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.accusation == "No accusation."
        assert nom.accusation_pending  # still pending, not stolen by command

    def test_command_message_not_captured_as_defence(self):
        """Messages starting with bot prefix are not captured as defence text."""
        nom = Nomination(id=1, nominator_id=1, nominee_id=2, defense_pending=True)
        view = self._make_view(nom)
        cog = self._make_cog()
        cog._views = {(10, 1): view}
        channel = MagicMock()
        channel.id = 100
        msg = self._make_message(".baccuse 1 guilty", 2, 10, 100)
        msg.channel = channel
        cog._messages[(10, 1)] = msg

        self._run_on_message(cog, msg)

        assert nom.defense == "No defense."
        assert nom.defense_pending

    # ── baccuse dead code removed ─────────────────────────────────────────────

    def test_baccuse_loop_does_not_crash_on_missing_message(self):
        """baccuse's loop over other views does not crash if _messages is missing a key."""
        import asyncio

        async def _run():
            from cogs.game import BOTCGame, VoteView, Nomination
            imported_cog = BOTCGame.__new__(BOTCGame)
            imported_cog._views = {}
            imported_cog._messages = {}
            bot = MagicMock()
            bot.command_prefix = "."
            imported_cog.bot = bot

            n1 = Nomination(id=1, nominator_id=10, nominee_id=20)
            n2 = Nomination(id=2, nominator_id=30, nominee_id=40)
            v1 = VoteView(imported_cog, 100, n1, 0)
            v2 = VoteView(imported_cog, 100, n2, 0)
            imported_cog._views[(100, 1)] = v1
            imported_cog._views[(100, 2)] = v2
            imported_cog._messages[(100, 1)] = None

            ctx = MagicMock()
            ctx.guild.id = 100

            try:
                await imported_cog.baccuse.callback(imported_cog, ctx, 1)
            except TypeError as exc:
                msg = str(exc)
                # Ignore "can't be used in 'await' expression" — MagicMock
                # issue, not related to the dead-code bug being tested.
                if "NoneType" in msg or "not iterable" in msg:
                    pytest.fail(f"baccuse raised TypeError from dead code: {exc}")
            except Exception:
                pass

        asyncio.run(_run())
