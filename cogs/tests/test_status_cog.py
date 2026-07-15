"""Deep tests for the Moderator Status System."""

import pytest
import asyncio
import discord
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from cogs import status_cog
from cogs.status_cog import (
    BUILTIN_STATUSES,
    _channel_entry,
    get_channel_statuses,
    has_status,
    set_status,
    remove_status,
    clear_all_statuses,
    add_custom_status,
    remove_custom_status,
    build_status_description,
    check_dead_warning,
    check_move_warning,
    check_knock_warning,
    check_visitblock,
    check_visitblock_warning,
    check_channel_warning,
    StatusManagerView,
    StatusWarningConfirmView,
    StatusListClearView,
    ClearConfirmView,
    CustomStatusModal,
    _build_statuslist_content,
    _build_statuslist_view,
    _build_status_embed,
)


def _gd(cs=None):
    return {"channel_statuses": cs or {}}


def _ch(ch_id, name="alice-rc"):
    ch = MagicMock()
    ch.id = ch_id
    ch.name = name
    ch.mention = f"<#{ch_id}>"
    return ch


def _guild(channels=None):
    g = MagicMock()
    g.id = 100
    g.get_channel = MagicMock(side_effect=lambda c: (channels or {}).get(c))
    return g


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _call(fn, *a, **kw):
    return fn(*a, **kw)


def _make_view(cls, *args, **kwargs):
    """Instantiate a discord.ui.View subclass (needs a running event loop)."""
    result = [None]
    async def _create():
        result[0] = cls(*args, **kwargs)
    asyncio.run(_create())
    return result[0]


# ── Storage ──────────────────────────────────────────────────────────────────

class TestChannelEntry:
    def test_creates(self):
        gd = _gd()
        e = _channel_entry(gd, 111)
        assert e == {}
        assert "111" in gd["channel_statuses"]

    def test_returns_existing(self):
        gd = _gd({"111": {"protection": {"timestamp": 100, "moderator": 1}}})
        assert "protection" in _channel_entry(gd, 111)

    def test_independent(self):
        gd = _gd()
        e1 = _channel_entry(gd, 100)
        e2 = _channel_entry(gd, 200)
        e1["x"] = True
        assert "x" not in e2

    def test_coercion(self):
        gd = _gd()
        _channel_entry(gd, 42)
        _channel_entry(gd, "42")
        assert "42" in gd["channel_statuses"]


class TestGetChannelStatuses:
    def test_empty(self):
        assert get_channel_statuses(_gd(), 999) == {}

    def test_returns_copy(self):
        gd = _gd({"111": {"roleblock": {"timestamp": 5, "moderator": 1}}})
        s = get_channel_statuses(gd, 111)
        s["injected"] = True
        assert "injected" not in gd["channel_statuses"]["111"]


class TestHasStatus:
    def test_false(self):
        assert has_status(_gd(), 1, "protection") is False

    def test_true(self):
        gd = _gd({"1": {"protection": {"timestamp": 0, "moderator": 0}}})
        assert has_status(gd, 1, "protection") is True

    def test_wrong_key(self):
        gd = _gd({"1": {"roleblock": {"timestamp": 0, "moderator": 0}}})
        assert has_status(gd, 1, "protection") is False


class TestSetStatus:
    def test_adds(self):
        gd = _gd()
        set_status(gd, 1, "protection", moderator_id=42)
        assert has_status(gd, 1, "protection")
        assert _channel_entry(gd, 1)["protection"]["moderator"] == 42
        assert isinstance(_channel_entry(gd, 1)["protection"]["timestamp"], int)

    def test_overwrites(self):
        gd = _gd({"1": {"protection": {"timestamp": 1, "moderator": 1}}})
        set_status(gd, 1, "protection", moderator_id=2)
        assert _channel_entry(gd, 1)["protection"]["moderator"] == 2

    def test_timestamp_valid(self):
        before = int(datetime.now(timezone.utc).timestamp())
        gd = _gd()
        set_status(gd, 1, "immunity", moderator_id=1)
        ts = _channel_entry(gd, 1)["immunity"]["timestamp"]
        after = int(datetime.now(timezone.utc).timestamp())
        assert before <= ts <= after


class TestRemoveStatus:
    def test_removes(self):
        gd = _gd({"1": {"protection": {"timestamp": 0, "moderator": 0}}})
        remove_status(gd, 1, "protection")
        assert not has_status(gd, 1, "protection")

    def test_no_error_absent(self):
        remove_status(_gd(), 1, "protection")

    def test_others_unaffected(self):
        gd = _gd({"1": {"protection": {"timestamp": 0, "moderator": 0},
                         "roleblock": {"timestamp": 0, "moderator": 0}}})
        remove_status(gd, 1, "protection")
        assert has_status(gd, 1, "roleblock")


class TestClearAllStatuses:
    def test_clears(self):
        gd = _gd({"1": {"protection": {"timestamp": 0, "moderator": 0},
                         "custom": [{"text": "x", "timestamp": 0, "moderator": 0}]}})
        clear_all_statuses(gd, 1)
        assert "1" not in gd["channel_statuses"]

    def test_no_error(self):
        clear_all_statuses(_gd(), 999)

    def test_others_unaffected(self):
        gd = _gd({"1": {"protection": {"timestamp": 0, "moderator": 0}},
                   "2": {"roleblock": {"timestamp": 0, "moderator": 0}}})
        clear_all_statuses(gd, 1)
        assert "2" in gd["channel_statuses"]


class TestAddCustomStatus:
    def test_adds(self):
        gd = _gd()
        add_custom_status(gd, 1, "Cannot be poisoned", 42)
        c = _channel_entry(gd, 1)["custom"][0]
        assert c["text"] == "Cannot be poisoned"
        assert c["moderator"] == 42

    def test_multiple(self):
        gd = _gd()
        add_custom_status(gd, 1, "A", 1)
        add_custom_status(gd, 1, "B", 2)
        assert len(_channel_entry(gd, 1)["custom"]) == 2

    def test_preserves_builtins(self):
        gd = _gd({"1": {"protection": {"timestamp": 0, "moderator": 0}}})
        add_custom_status(gd, 1, "text", 1)
        assert has_status(gd, 1, "protection")


class TestRemoveCustomStatus:
    def test_by_index(self):
        gd = _gd()
        add_custom_status(gd, 1, "A", 1)
        add_custom_status(gd, 1, "B", 1)
        add_custom_status(gd, 1, "C", 1)
        remove_custom_status(gd, 1, 1)
        texts = [c["text"] for c in _channel_entry(gd, 1)["custom"]]
        assert texts == ["A", "C"]

    def test_out_of_range(self):
        gd = _gd()
        add_custom_status(gd, 1, "A", 1)
        remove_custom_status(gd, 1, 99)
        assert len(_channel_entry(gd, 1)["custom"]) == 1

    def test_negative(self):
        gd = _gd()
        add_custom_status(gd, 1, "A", 1)
        remove_custom_status(gd, 1, -1)
        assert len(_channel_entry(gd, 1)["custom"]) == 1

    def test_cleans_empty_list(self):
        gd = _gd()
        add_custom_status(gd, 1, "A", 1)
        remove_custom_status(gd, 1, 0)
        assert "custom" not in _channel_entry(gd, 1)

    def test_preserves_builtins(self):
        gd = _gd({"1": {"roleblock": {"timestamp": 0, "moderator": 0}}})
        add_custom_status(gd, 1, "text", 1)
        remove_custom_status(gd, 1, 0)
        assert has_status(gd, 1, "roleblock")


# ── Description ──────────────────────────────────────────────────────────────

class TestBuildStatusDescription:
    def test_empty(self):
        assert build_status_description(_gd(), 999) == "No active statuses."

    def test_single_builtin(self):
        gd = _gd({"1": {"protection": {"timestamp": 1700000000, "moderator": 42}}})
        d = build_status_description(gd, 1)
        assert "🛡 Protection" in d
        assert "<t:1700000000:t>" in d

    def test_multiple_builtins(self):
        gd = _gd({"1": {"protection": {"timestamp": 100, "moderator": 1},
                         "roleblock": {"timestamp": 200, "moderator": 2}}})
        d = build_status_description(gd, 1)
        assert "🛡 Protection" in d
        assert "⛔ Roleblock" in d

    def test_custom(self):
        gd = _gd({"1": {"custom": [{"text": "Poison immune", "timestamp": 300, "moderator": 1}]}})
        d = build_status_description(gd, 1)
        assert "📝 Poison immune" in d

    def test_mixed(self):
        gd = _gd({"1": {"protection": {"timestamp": 100, "moderator": 1},
                         "custom": [{"text": "No visit", "timestamp": 200, "moderator": 2}]}})
        d = build_status_description(gd, 1)
        assert "🛡 Protection" in d
        assert "📝 No visit" in d


# ── Warnings ─────────────────────────────────────────────────────────────────

class TestCheckDeadWarning:
    def test_empty(self):
        assert check_dead_warning(_gd(), 1) is None

    def test_protection(self):
        w = check_dead_warning(_gd({"1": {"protection": {"timestamp": 1700000000, "moderator": 1}}}), 1)
        assert "🛡 Protection" in w

    def test_roleblock_ignored(self):
        gd = _gd({"1": {"roleblock": {"timestamp": 100, "moderator": 1}}})
        assert check_dead_warning(gd, 1) is None


class TestCheckMoveWarning:
    def test_empty(self):
        assert check_move_warning(_gd(), 1) is None

    def test_stealth(self):
        w = check_move_warning(_gd({"1": {"stealth": {"timestamp": 1700000000, "moderator": 1}}}), 1)
        assert "🌑 Stealth" in w

    def test_visitblock_ignored(self):
        gd = _gd({"1": {"visitblock": {"timestamp": 100, "moderator": 1}}})
        assert check_move_warning(gd, 1) is None

    def test_other_ignored(self):
        gd = _gd({"1": {"protection": {"timestamp": 100, "moderator": 1}}})
        assert check_move_warning(gd, 1) is None


class TestCheckKnockWarning:
    def test_delegates(self):
        gd = _gd({"1": {"stealth": {"timestamp": 500, "moderator": 1}}})
        assert check_knock_warning(gd, 1) == check_move_warning(gd, 1)

    def test_none(self):
        assert check_knock_warning(_gd(), 1) is None


class TestCheckVisitblock:
    def test_true_when_blocked(self):
        gd = _gd({"1": {"visitblock": {"timestamp": 100, "moderator": 1}}})
        assert check_visitblock(gd, 1) is True

    def test_false_when_empty(self):
        assert check_visitblock(_gd(), 1) is False

    def test_false_for_other_status(self):
        gd = _gd({"1": {"protection": {"timestamp": 100, "moderator": 1}}})
        assert check_visitblock(gd, 1) is False


class TestCheckVisitblockWarning:
    def test_empty(self):
        assert check_visitblock_warning(_gd(), 1) is None

    def test_visitblock(self):
        w = check_visitblock_warning(_gd({"1": {"visitblock": {"timestamp": 1700000000, "moderator": 1}}}), 1)
        assert "👣 Visit Block" in w

    def test_stealth_ignored(self):
        gd = _gd({"1": {"stealth": {"timestamp": 100, "moderator": 1}}})
        assert check_visitblock_warning(gd, 1) is None

    def test_other_ignored(self):
        gd = _gd({"1": {"protection": {"timestamp": 100, "moderator": 1}}})
        assert check_visitblock_warning(gd, 1) is None


class TestCheckChannelWarning:
    def test_with_warning(self):
        gd = _gd({"1": {"protection": {"timestamp": 100, "moderator": 1}}})
        t, h = check_channel_warning(gd, 1, check_dead_warning)
        assert h is True and "🛡 Protection" in t

    def test_without(self):
        t, h = check_channel_warning(_gd(), 1, check_dead_warning)
        assert h is False and t is None


# ── Views ────────────────────────────────────────────────────────────────────

class TestStatusManagerView:
    def test_check_owner(self):
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        i = MagicMock()
        i.user.id = 42
        assert _run(v.interaction_check(i)) is True

    def test_check_rejects(self):
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        i = AsyncMock()
        i.user.id = 99
        assert _run(v.interaction_check(i)) is False

    def test_toggle_buttons_active(self):
        gd = _gd({"100": {"protection": {"timestamp": 0, "moderator": 0},
                           "roleblock": {"timestamp": 0, "moderator": 0}}})
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        v._toggle_buttons(gd)
        keys = list(BUILTIN_STATUSES.keys())
        for idx, child in enumerate(v.children):
            if idx < len(keys):
                expected = discord.ButtonStyle.success if keys[idx] in ("protection", "roleblock") else discord.ButtonStyle.secondary
                assert child.style == expected

    def test_toggle_buttons_all_inactive(self):
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        v._toggle_buttons(_gd())
        for child in v.children[:6]:
            assert child.style == discord.ButtonStyle.secondary

    def test_button_count(self):
        assert len(_make_view(StatusManagerView, 100, "x", 1).children) == 9

    def test_toggle_adds(self):
        gd = _gd()
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        i = MagicMock()
        i.user.id = 42
        i.guild_id = 100
        i.response = AsyncMock()
        with patch("cogs.status_cog.load_guild_data", return_value=gd), \
             patch("cogs.status_cog.save_guild_data"):
            _run(v._toggle(i, "protection"))
        assert has_status(gd, 100, "protection")

    def test_toggle_removes(self):
        gd = _gd({"100": {"protection": {"timestamp": 0, "moderator": 0}}})
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        i = MagicMock()
        i.user.id = 42
        i.guild_id = 100
        i.response = AsyncMock()
        with patch("cogs.status_cog.load_guild_data", return_value=gd), \
             patch("cogs.status_cog.save_guild_data"):
            _run(v._toggle(i, "protection"))
        assert not has_status(gd, 100, "protection")

    def test_toggle_rejects_wrong_user(self):
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        i = AsyncMock()
        i.user.id = 99
        _run(v._toggle(i, "protection"))
        i.response.send_message.assert_called_once()


class TestStatusWarningConfirmView:
    def test_initial(self):
        assert _make_view(StatusWarningConfirmView, 42).confirmed is False

    def test_check_owner(self):
        v = _make_view(StatusWarningConfirmView, 42)
        i = MagicMock()
        i.user.id = 42
        assert _run(v.interaction_check(i)) is True

    def test_check_rejects(self):
        v = _make_view(StatusWarningConfirmView, 42)
        i = AsyncMock()
        i.user.id = 99
        assert _run(v.interaction_check(i)) is False

    def test_confirm(self):
        v = _make_view(StatusWarningConfirmView, 42)
        i = MagicMock()
        i.user.id = 42
        i.response = AsyncMock()
        _run(v.children[0].callback(i))
        assert v.confirmed is True

    def test_cancel(self):
        v = _make_view(StatusWarningConfirmView, 42)
        i = MagicMock()
        i.user.id = 42
        i.response = AsyncMock()
        _run(v.children[1].callback(i))
        assert v.confirmed is False


class TestClearConfirmView:
    def test_confirm_clears(self):
        gd = _gd({"100": {"protection": {"timestamp": 0, "moderator": 0}}})
        mv = _make_view(StatusManagerView, 100, "alice-rc", 42)
        cv = _make_view(ClearConfirmView, mv)
        i = MagicMock()
        i.user.id = 42
        i.guild_id = 100
        i.response = AsyncMock()
        with patch("cogs.status_cog.load_guild_data", return_value=gd), \
             patch("cogs.status_cog.save_guild_data"):
            _run(cv.children[0].callback(i))
        assert "100" not in gd["channel_statuses"]

    def test_cancel(self):
        mv = _make_view(StatusManagerView, 100, "alice-rc", 42)
        cv = _make_view(ClearConfirmView, mv)
        i = MagicMock()
        i.user.id = 42
        i.response = AsyncMock()
        _run(cv.children[1].callback(i))
        i.response.edit_message.assert_called_once()

    def test_rejects_wrong_user(self):
        mv = _make_view(StatusManagerView, 100, "alice-rc", 42)
        cv = _make_view(ClearConfirmView, mv)
        i = AsyncMock()
        i.user.id = 99
        _run(cv.children[0].callback(i))
        i.response.send_message.assert_called_once()


class TestStatusListClearView:
    def _entries(self):
        return [
            (100, "protection", 1700000000, 1, None),
            (100, "roleblock", 1700000100, 2, None),
            (100, "custom", 1700000200, 3, 0),
        ]

    def _guild(self):
        return _guild({100: _ch(100, "gorillas-rc")})

    def test_button_count(self):
        assert len(_make_view(StatusListClearView, self._entries(), 42, self._guild()).children) == 3

    def test_button_labels(self):
        v = _make_view(StatusListClearView, self._entries(), 42, self._guild())
        labels = [b.label for b in v.children]
        assert labels == ["gorilla#1", "gorilla#2", "gorilla#3"]

    def test_button_styles(self):
        for btn in _make_view(StatusListClearView, self._entries(), 42, self._guild()).children:
            assert btn.style == discord.ButtonStyle.danger

    def test_removes_builtin(self):
        gd = _gd({"100": {"protection": {"timestamp": 1700000000, "moderator": 1},
                           "roleblock": {"timestamp": 1700000100, "moderator": 2}}})
        v = _make_view(StatusListClearView, self._entries(), 42, self._guild())
        i = MagicMock()
        i.user.id = 42
        i.guild_id = 100
        i.response = AsyncMock()
        with patch("cogs.status_cog.load_guild_data", return_value=gd), \
             patch("cogs.status_cog.save_guild_data"):
            _run(v._make_callback(0)(i))
        assert not has_status(gd, 100, "protection")
        assert has_status(gd, 100, "roleblock")

    def test_removes_custom(self):
        gd = _gd({"100": {"custom": [
            {"text": "A", "timestamp": 100, "moderator": 1},
            {"text": "B", "timestamp": 200, "moderator": 2},
        ]}})
        v = _make_view(StatusListClearView, self._entries(), 42, self._guild())
        i = MagicMock()
        i.user.id = 42
        i.guild_id = 100
        i.response = AsyncMock()
        with patch("cogs.status_cog.load_guild_data", return_value=gd), \
             patch("cogs.status_cog.save_guild_data"):
            _run(v._make_callback(2)(i))
        custom = _channel_entry(gd, 100).get("custom", [])
        assert len(custom) == 1 and custom[0]["text"] == "B"

    def test_rejects_wrong_user(self):
        v = _make_view(StatusListClearView, self._entries(), 42, self._guild())
        i = AsyncMock()
        i.user.id = 99
        _run(v._make_callback(0)(i))
        i.response.send_message.assert_called_once()


# ── Statuslist ───────────────────────────────────────────────────────────────

class TestBuildStatuslistContent:
    def test_empty(self):
        assert _build_statuslist_content(_gd(), _guild()) is None

    def test_empty_statuses_filtered(self):
        assert _build_statuslist_content(_gd({"1": {}}), _guild()) is None

    def test_single_channel(self):
        ch = _ch(100)
        content = _build_statuslist_content(
            _gd({"100": {"protection": {"timestamp": 1700000000, "moderator": 1}}}),
            _guild({100: ch}))
        assert "<#100>" in content
        assert "🛡 Protection" in content

    def test_multiple_channels(self):
        content = _build_statuslist_content(
            {"channel_statuses": {
                "100": {"protection": {"timestamp": 1, "moderator": 1}},
                "200": {"roleblock": {"timestamp": 2, "moderator": 2}},
            }},
            _guild({100: _ch(100), 200: _ch(200, "bob-rc")}))
        assert "────────────────────" in content
        assert "<#100>" in content and "<#200>" in content

    def test_custom_included(self):
        content = _build_statuslist_content(
            _gd({"100": {"custom": [{"text": "Poison immune", "timestamp": 500, "moderator": 1}]}}),
            _guild({100: _ch(100, "charlie-rc")}))
        assert "📝 Poison immune" in content

    def test_deleted_channel_fallback(self):
        content = _build_statuslist_content(
            _gd({"999": {"protection": {"timestamp": 1, "moderator": 1}}}),
            _guild({}))
        assert "#999" in content


class TestBuildStatuslistView:
    def test_none_when_empty(self):
        assert _build_statuslist_view(_gd(), 42, _guild()) is None

    def test_builds(self):
        gd = _gd({"100": {"protection": {"timestamp": 1, "moderator": 1},
                           "custom": [{"text": "x", "timestamp": 2, "moderator": 2}]}})
        v = _run(_call(_build_statuslist_view, gd, 42, _guild({100: _ch(100)})))
        assert isinstance(v, StatusListClearView)
        assert len(v.children) == 2

    def test_entries_correct(self):
        gd = _gd({"100": {"protection": {"timestamp": 100, "moderator": 42},
                           "custom": [{"text": "test", "timestamp": 200, "moderator": 99}]}})
        v = _run(_call(_build_statuslist_view, gd, 42, _guild({100: _ch(100)})))
        assert v._entries[0] == (100, "protection", 100, 42, None)
        assert v._entries[1] == (100, "custom", 200, 99, 0)


# ── Embed ────────────────────────────────────────────────────────────────────

class TestBuildStatusEmbed:
    def test_title(self):
        gd = _gd({"100": {"protection": {"timestamp": 1, "moderator": 1}}})
        e = _build_status_embed("alice-rc", 100, gd)
        assert "alice-rc" in e.title

    def test_description(self):
        gd = _gd({"100": {"protection": {"timestamp": 1, "moderator": 1}}})
        e = _build_status_embed("alice-rc", 100, gd)
        assert "🛡 Protection" in e.description


# ── Modal ────────────────────────────────────────────────────────────────────

class TestCustomStatusModal:
    def test_view_ref(self):
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        m = _make_view(CustomStatusModal, v)
        assert m.view is v

    def test_has_input(self):
        v = _make_view(StatusManagerView, 100, "x", 1)
        m = _make_view(CustomStatusModal, v)
        assert len(m.children) == 1
        assert m.children[0].max_length == 200

    def test_on_submit(self):
        gd = _gd()
        v = _make_view(StatusManagerView, 100, "alice-rc", 42)
        m = _make_view(CustomStatusModal, v)
        m.children[0]._value = "Cannot be poisoned"
        i = MagicMock()
        i.guild_id = 100
        i.user.id = 42
        i.response = AsyncMock()
        with patch("cogs.status_cog.load_guild_data", return_value=gd), \
             patch("cogs.status_cog.save_guild_data"):
            _run(m.on_submit(i))
        custom = _channel_entry(gd, 100).get("custom", [])
        assert len(custom) == 1 and custom[0]["text"] == "Cannot be poisoned"


# ── Cog commands exist ──────────────────────────────────────────────────────

class TestCogCommands:
    def test_status_exists(self):
        assert hasattr(status_cog.Status, "status")

    def test_status_has_help(self):
        m = getattr(status_cog.Status, "status")
        assert getattr(m, "help", None) or getattr(m, "__doc__", None)

    def test_statuslist_exists(self):
        assert hasattr(status_cog.Status, "statuslist")

    def test_statuslist_has_help(self):
        m = getattr(status_cog.Status, "statuslist")
        assert getattr(m, "help", None) or getattr(m, "__doc__", None)
