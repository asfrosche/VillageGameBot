"""Tests for the Status Panel cog (.statuspanel — Online/AFK member board)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands

from cogs import status_panel_cog


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_view(cls, *args, **kwargs):
    """Instantiate a discord.ui.View subclass (needs a running event loop)."""
    result = [None]
    async def _create():
        result[0] = cls(*args, **kwargs)
    asyncio.run(_create())
    return result[0]


def _gd(members=None):
    data = {}
    if members:
        data["status_panel"] = {"members": dict(members)}
    return data


class TestHelpers:
    """Data helpers (panel_state / get_member_status)."""

    def test_panel_state_creates_keys(self):
        gd = {}
        panel = status_panel_cog.panel_state(gd)
        assert panel["members"] == {}
        assert gd["status_panel"]["members"] == {}

    def test_panel_state_preserves_existing(self):
        gd = {"status_panel": {"members": {"111": "online"}, "extra": True}}
        panel = status_panel_cog.panel_state(gd)
        assert panel["members"]["111"] == "online"
        assert panel.get("extra") is True

    def test_get_member_status(self):
        gd = {"status_panel": {"members": {"111": "online", "222": "afk"}}}
        assert status_panel_cog.get_member_status(gd, "111") == "online"
        assert status_panel_cog.get_member_status(gd, 111) == "online"
        assert status_panel_cog.get_member_status(gd, "999") is None

    def test_member_name_fallback_and_nickname(self):
        guild = MagicMock()
        member = MagicMock()
        member.nick = "Nickname"
        member.display_name = "Display"
        guild.get_member.return_value = member
        assert status_panel_cog._member_name(guild, "111") == "Nickname"
        assert status_panel_cog._member_name(None, "111", "Fallback") == "Fallback"


class TestBuildPanelContent:
    """Plain-text content builder output (no embed)."""

    def test_empty_panel(self):
        content = status_panel_cog.build_panel_content({})
        assert "No members yet" in content

    def test_member_counts(self):
        gd = _gd({"100": "online", "200": "afk", "300": "online"})
        content = status_panel_cog.build_panel_content(gd)
        assert "2 online" in content
        assert "1 afk" in content

    def test_toggle_label_online(self):
        assert status_panel_cog._toggle_label("Alice", "online").endswith("🟢 Online")

    def test_toggle_label_afk(self):
        assert status_panel_cog._toggle_label("Bob", "afk").endswith("🌙 AFK")


class TestStatusPanelCog:
    """Command registration and permissions."""

    def test_command_exists(self):
        assert hasattr(status_panel_cog.StatusPanel, "statuspanel")

    def test_command_has_help(self):
        method = getattr(status_panel_cog.StatusPanel, "statuspanel")
        doc = getattr(method, "help", None) or getattr(method, "__doc__", None)
        assert doc is not None and len(doc.strip()) > 0

    def test_command_requires_admin(self):
        method = getattr(status_panel_cog.StatusPanel, "statuspanel")
        checks = getattr(method, "checks", None)
        assert checks is not None, "Command should have permission checks"

    def test_command_registered_on_cog(self):
        cog = status_panel_cog.StatusPanel(None)
        names = {c.name for c in cog.get_commands()}
        assert "statuspanel" in names

    def test_on_ready_registers_views(self):
        cog = status_panel_cog.StatusPanel(MagicMock())
        assert not cog._registered
        _run(cog.on_ready())
        assert cog._registered

    def test_on_ready_no_bot_noop(self):
        cog = status_panel_cog.StatusPanel(None)
        _run(cog.on_ready())
        assert cog._registered


class TestStatusPanelView:
    """View construction and callback guards."""

    def test_empty_panel_only_admin_buttons(self):
        with patch("cogs.status_panel_cog.load_guild_data", return_value={}):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
        assert len(view.children) == 2  # Add Member, Remove
        assert {c.row for c in view.children} == {4}

    def test_single_member_is_one_toggle_button(self):
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"111": "online"})):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
        assert len(view.children) == 3  # 1 toggle + Add + Remove

    def test_member_buttons_flow_across_rows(self):
        members = {str(i): "online" for i in range(7)}
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd(members)):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
        member_buttons = [c for c in view.children if c.row != 4]
        assert len(member_buttons) == 7
        assert len({c.row for c in member_buttons}) == 2
        assert status_panel_cog.MAX_MEMBERS == 20

    def test_more_than_max_members_capped(self):
        members = {str(i): "online" for i in range(25)}
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd(members)):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
        member_buttons = [c for c in view.children if c.row != 4]
        assert len(member_buttons) == status_panel_cog.MAX_MEMBERS

    def test_add_mode_shows_user_select_and_cancel(self):
        with patch("cogs.status_panel_cog.load_guild_data", return_value={}):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123, mode="add")
        assert len(view.children) == 2

    def test_remove_mode_shows_all_members_in_select(self):
        with patch("cogs.status_panel_cog.load_guild_data",
                   return_value=_gd({"111": "online", "222": "afk"})):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123, mode="remove")
        assert len(view.children) == 2
        sel = view.children[0]
        assert len(sel.options) == 2

    def test_toggle_denied_for_other_user(self):
        interaction = MagicMock()
        interaction.user = MagicMock()
        interaction.user.id = 999
        interaction.response.send_message = AsyncMock()
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"111": "online"})):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            _run(view._make_toggle_cb(111)(interaction))
        interaction.response.send_message.assert_awaited_once()
        assert "own status" in interaction.response.send_message.call_args[0][0]

    def test_toggle_flips_online_to_afk(self):
        interaction = MagicMock()
        interaction.user = MagicMock()
        interaction.user.id = 111
        interaction.response.edit_message = AsyncMock()
        interaction.message = MagicMock()
        interaction.message.id = 55
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"111": "online"})), \
             patch("cogs.status_panel_cog.save_guild_data") as mock_save:
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            _run(view._make_toggle_cb(111)(interaction))
        mock_save.assert_called_once()
        args = mock_save.call_args[0]
        assert args[0] == 123
        assert args[1]["status_panel"]["members"]["111"] == "afk"
        interaction.response.edit_message.assert_awaited_once()
        # toggling an AFK member goes back to Online
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"111": "afk"})), \
             patch("cogs.status_panel_cog.save_guild_data") as mock_save2:
            view2 = _make_view(status_panel_cog.StatusPanelView, None, 123)
            _run(view2._make_toggle_cb(111)(interaction))
        assert mock_save2.call_args[0][1]["status_panel"]["members"]["111"] == "online"

    def test_toggle_member_no_longer_on_panel(self):
        interaction = MagicMock()
        interaction.user = MagicMock()
        interaction.user.id = 111
        interaction.response.send_message = AsyncMock()
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"222": "afk"})):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            _run(view._make_toggle_cb(111)(interaction))
        interaction.response.send_message.assert_awaited_once()
        assert "no longer" in interaction.response.send_message.call_args[0][0]

    def test_add_btn_denies_non_admin(self):
        interaction = MagicMock()
        interaction.user.guild_permissions.administrator = False
        interaction.response.send_message = AsyncMock()
        with patch("cogs.status_panel_cog.load_guild_data", return_value={}):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            _run(view._make_add_btn_cb()(interaction))
        interaction.response.send_message.assert_awaited_once()
        assert "Admins only" in interaction.response.send_message.call_args[0][0]

    def test_remove_btn_denies_non_admin(self):
        interaction = MagicMock()
        interaction.user.guild_permissions.administrator = False
        interaction.response.send_message = AsyncMock()
        with patch("cogs.status_panel_cog.load_guild_data", return_value={}):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            _run(view._make_remove_btn_cb()(interaction))
        interaction.response.send_message.assert_awaited_once()
        assert "Admins only" in interaction.response.send_message.call_args[0][0]

    def test_add_user_duplicate_rejected(self):
        interaction = MagicMock()
        interaction.user.guild_permissions.administrator = True
        interaction.data = {"values": ["111"]}
        interaction.response.send_message = AsyncMock()
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"111": "online"})):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            select = MagicMock()
            _run(view._add_user_cb(select)(interaction))
        interaction.response.send_message.assert_awaited_once()
        assert "already on the panel" in interaction.response.send_message.call_args[0][0]

    def test_add_user_when_full_rejected(self):
        full = _gd({str(i): "online" for i in range(status_panel_cog.MAX_MEMBERS)})
        interaction = MagicMock()
        interaction.user.guild_permissions.administrator = True
        interaction.data = {"values": ["999"]}
        interaction.response.send_message = AsyncMock()
        with patch("cogs.status_panel_cog.load_guild_data", return_value=full):
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            select = MagicMock()
            _run(view._add_user_cb(select)(interaction))
        interaction.response.send_message.assert_awaited_once()
        assert "full" in interaction.response.send_message.call_args[0][0]

    def test_add_user_adds_default_online(self):
        interaction = MagicMock()
        interaction.user.guild_permissions.administrator = True
        interaction.data = {"values": ["222"]}
        interaction.response.edit_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.message = MagicMock()
        interaction.message.id = 55
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"111": "online"})) as mock_load, \
             patch("cogs.status_panel_cog.save_guild_data") as mock_save:
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            select = MagicMock()
            _run(view._add_user_cb(select)(interaction))
        assert mock_load.call_count >= 1
        saved = mock_save.call_args[0][1]
        assert saved["status_panel"]["members"]["222"] == "online"
        assert saved["status_panel"]["members"]["111"] == "online"
        interaction.response.edit_message.assert_awaited_once()

    def test_remove_member_deletes(self):
        interaction = MagicMock()
        interaction.user.guild_permissions.administrator = True
        interaction.data = {"values": ["111"]}
        interaction.response.edit_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.message = MagicMock()
        interaction.message.id = 55
        with patch("cogs.status_panel_cog.load_guild_data",
                   return_value=_gd({"111": "online", "222": "afk"})), \
             patch("cogs.status_panel_cog.save_guild_data") as mock_save:
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            select = MagicMock()
            _run(view._remove_member_cb(select)(interaction))
        saved = mock_save.call_args[0][1]
        assert "111" not in saved["status_panel"]["members"]
        assert "222" in saved["status_panel"]["members"]
        interaction.response.edit_message.assert_awaited_once()

    def test_interaction_check_allows_admin_and_member(self):
        admin = MagicMock()
        admin.user.guild_permissions.administrator = True
        admin.user.id = 500
        member = MagicMock()
        member.user.guild_permissions.administrator = False
        member.user.id = 111
        outsider = MagicMock()
        outsider.user.guild_permissions.administrator = False
        outsider.user.id = 999
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"111": "online"})) as mock_load:
            view = _make_view(status_panel_cog.StatusPanelView, None, 123)
            assert _run(view.interaction_check(admin)) is True
            assert _run(view.interaction_check(member)) is True
            outsider.response.send_message = AsyncMock()
            assert _run(view.interaction_check(outsider)) is False
            outsider.response.send_message.assert_awaited_once()

    def test_edit_panel_reregisters_view(self):
        bot = MagicMock()
        interaction = MagicMock()
        interaction.message = MagicMock()
        interaction.message.id = 55
        interaction.guild = MagicMock()
        interaction.response.edit_message = AsyncMock()
        with patch("cogs.status_panel_cog.load_guild_data", return_value=_gd({"111": "online"})):
            view = _make_view(status_panel_cog.StatusPanelView, bot, 123)
            _run(view._edit_panel(interaction))
        interaction.response.edit_message.assert_awaited_once()
        bot.remove_view.assert_called_once()
        bot.add_view.assert_called_once()
        assert bot.add_view.call_args[1]["message_id"] == 55