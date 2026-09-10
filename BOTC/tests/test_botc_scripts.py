"""Tests for BOTC/cogs/scripts.py — module data, helpers, and cog structure."""

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

from cogs.scripts import (
    ScriptsView,
    _script_download_url,
    EDITION_KEYS,
    ScriptsCog,
    setup,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Module-level data
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleData:
    def test_edition_keys(self):
        assert EDITION_KEYS == ["tb", "bmr", "snv"]


# ═══════════════════════════════════════════════════════════════════════════
# 2. _script_download_url
# ═══════════════════════════════════════════════════════════════════════════

class TestScriptDownloadUrl:
    def test_tb_url(self):
        url = _script_download_url("tb")
        assert "botcscripts.com" in url
        assert "35930" in url

    def test_bmr_url(self):
        url = _script_download_url("bmr")
        assert "botcscripts.com" in url
        assert "35931" in url

    def test_snv_url(self):
        url = _script_download_url("snv")
        assert "botcscripts.com" in url
        assert "35932" in url

    def test_unknown_returns_empty(self):
        assert _script_download_url("unknown") == ""


# ═══════════════════════════════════════════════════════════════════════════
# 3. ScriptsView — test via class introspection and inline event loop
# ═══════════════════════════════════════════════════════════════════════════

class TestScriptsView:
    def test_class_inherits_from_view(self):
        assert issubclass(ScriptsView, discord.ui.View)

    def test_has_three_edition_buttons(self):

        async def _test():
            view = ScriptsView(author_id=123)
            btns = [c for c in view.children if isinstance(c, discord.ui.Button) and not c.url]
            assert len(btns) == 3

        asyncio.run(_test())

    def test_buttons_have_expected_labels(self):

        async def _test():
            view = ScriptsView(author_id=123)
            labels = [c.label for c in view.children]
            assert "TB" in labels
            assert "BMR" in labels
            assert "SNV" in labels

        asyncio.run(_test())

    def test_interaction_check_allows_author(self):

        async def _test():
            view = ScriptsView(author_id=123)
            i = AsyncMock()
            i.user.id = 123
            assert await view.interaction_check(i) is True

        asyncio.run(_test())

    def test_interaction_check_denies_others(self):

        async def _test():
            view = ScriptsView(author_id=123)
            i = AsyncMock()
            i.user.id = 999
            assert await view.interaction_check(i) is False

        asyncio.run(_test())

    def test_timeout_is_set(self):

        async def _test():
            view = ScriptsView(author_id=123)
            assert view.timeout == 120

        asyncio.run(_test())


# ═══════════════════════════════════════════════════════════════════════════
# 4. ScriptsCog
# ═══════════════════════════════════════════════════════════════════════════

class TestScriptsCog:
    def test_cog_class_exists(self):
        assert ScriptsCog.__name__ == "ScriptsCog"

    def test_prefix_command_exists(self):
        bot = MagicMock()
        cog = ScriptsCog(bot)
        names = {c.name for c in cog.get_commands()}
        assert "scripts" in names

    def test_app_command_exists(self):
        bot = MagicMock()
        cog = ScriptsCog(bot)
        cmds = cog.__cog_app_commands__ if hasattr(cog, '__cog_app_commands__') else []
        assert any(c.name == "scripts" for c in cmds)

    def test_setup_is_async(self):
        assert asyncio.iscoroutinefunction(setup)
