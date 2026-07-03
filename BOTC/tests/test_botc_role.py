"""Tests for BOTC/cogs/role.py — cog structure, RoleView, and helpers."""

import os
import sys
from unittest.mock import MagicMock, AsyncMock

import asyncio
import discord
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, os.path.join(MAY_DIR, "BOTC"))

from cogs.role import RoleView, _get_night_roles, RoleCog, setup


# ═══════════════════════════════════════════════════════════════════════════
# 1. _get_night_roles helper
# ═══════════════════════════════════════════════════════════════════════════

class TestGetNightRoles:
    def test_returns_list_with_role_when_position_set(self):
        role = {"name": "Washerwoman", "firstNight": 1}
        result = _get_night_roles("firstNight", role)
        assert result == [role]

    def test_returns_list_with_role_other_night(self):
        role = {"name": "Imp", "otherNight": 2}
        result = _get_night_roles("otherNight", role)
        assert result == [role]

    def test_returns_empty_when_position_zero(self):
        role = {"name": "Washerwoman", "firstNight": 0}
        result = _get_night_roles("firstNight", role)
        assert result == []

    def test_returns_empty_when_position_missing(self):
        role = {"name": "TestRole"}
        result = _get_night_roles("firstNight", role)
        assert result == []

    def test_returns_empty_when_position_not_int(self):
        role = {"name": "TestRole", "firstNight": "none"}
        result = _get_night_roles("firstNight", role)
        assert result == []

    def test_returns_empty_when_position_negative(self):
        role = {"name": "TestRole", "firstNight": -1}
        result = _get_night_roles("firstNight", role)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. RoleView — test via class introspection (no instance needed)
# ═══════════════════════════════════════════════════════════════════════════

class TestRoleView:
    def test_class_inherits_from_view(self):
        assert issubclass(RoleView, discord.ui.View)

    def test_view_has_expected_methods(self):
        assert hasattr(RoleView, 'jinxes')
        assert hasattr(RoleView, 'night_order')
        assert hasattr(RoleView, 'aliases')
        assert hasattr(RoleView, 'back')
        assert hasattr(RoleView, '_disable_all')
        assert hasattr(RoleView, '_respond')
        assert hasattr(RoleView, 'interaction_check')

    def test_interaction_check_logic(self):
        """Verify the method returns True for author, False for others."""
        role = {"name": "Washerwoman", "id": "f0"}

        async def _test():
            view = RoleView(role, author_id=123)
            i1 = AsyncMock()
            i1.user.id = 123
            assert await view.interaction_check(i1) is True

            i2 = AsyncMock()
            i2.user.id = 999
            assert await view.interaction_check(i2) is False

            view2 = RoleView(role, author_id=456)
            i3 = AsyncMock()
            i3.user.id = 456
            assert await view2.interaction_check(i3) is True

        asyncio.run(_test())

    def test_wiki_button_url_contains_role_name(self):

        async def _test():
            role = {"name": "Washerwoman", "id": "f0"}
            view = RoleView(role, author_id=123)
            wiki_btns = [c for c in view.children if isinstance(c, discord.ui.Button) and c.url]
            assert len(wiki_btns) == 1
            assert "Washerwoman" in wiki_btns[0].url

        asyncio.run(_test())

    def test_has_button_labels(self):

        async def _test():
            role = {"name": "Washerwoman", "id": "f0"}
            view = RoleView(role, author_id=123)
            labels = [c.label for c in view.children]
            assert "Jinxes" in labels
            assert "Night Order" in labels
            assert "Aliases" in labels
            assert "Back to Role" in labels

        asyncio.run(_test())


# ═══════════════════════════════════════════════════════════════════════════
# 3. RoleCog
# ═══════════════════════════════════════════════════════════════════════════

class TestRoleCog:
    def test_cog_class_exists(self):
        assert RoleCog.__name__ == "RoleCog"

    def test_prefix_command_exists(self):
        bot = MagicMock()
        cog = RoleCog(bot)
        names = {c.name for c in cog.get_commands()}
        assert "rr" in names

    def test_prefix_command_has_alias(self):
        bot = MagicMock()
        cog = RoleCog(bot)
        for cmd in cog.get_commands():
            if cmd.name == "rr":
                assert "botcrole" in cmd.aliases

    def test_app_command_exists(self):
        bot = MagicMock()
        cog = RoleCog(bot)
        cmds = cog.__cog_app_commands__ if hasattr(cog, '__cog_app_commands__') else []
        assert any(c.name == "role" for c in cmds)

    def test_setup_is_async(self):
        assert asyncio.iscoroutinefunction(setup)
