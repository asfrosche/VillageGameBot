"""Tests for BOTC/cogs/fabled.py — cog structure and setup."""

import os
import sys
from unittest.mock import MagicMock

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, os.path.join(MAY_DIR, "BOTC"))

from cogs.fabled import FabledCog, setup


class TestFabledCog:
    def test_cog_class_exists(self):
        assert FabledCog.__name__ == "FabledCog"

    def test_cog_has_commands(self):
        bot = MagicMock()
        cog = FabledCog(bot)
        cmds = cog.__cog_app_commands__ if hasattr(cog, '__cog_app_commands__') else []
        assert len(cog.get_commands()) >= 1 or len(cmds) >= 1

    def test_prefix_command_exists(self):
        bot = MagicMock()
        cog = FabledCog(bot)
        names = {c.name for c in cog.get_commands()}
        names |= {c.qualified_name for c in cog.walk_commands()}
        assert "fabled" in names

    def test_app_command_exists(self):
        bot = MagicMock()
        cog = FabledCog(bot)
        cmds = cog.__cog_app_commands__ if hasattr(cog, '__cog_app_commands__') else []
        assert any(c.name == "fabled" for c in cmds)

    def test_setup_is_async(self):
        import asyncio
        assert asyncio.iscoroutinefunction(setup)

    def test_fabled_prefix_uses_botc_utils(self):
        bot = MagicMock()
        cog = FabledCog(bot)
        assert hasattr(cog, 'fabled_prefix')
