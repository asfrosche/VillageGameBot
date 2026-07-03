"""Tests for BOTC/cogs/jinx.py — cog structure and setup."""

import os
import sys
from unittest.mock import MagicMock

import asyncio
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, os.path.join(MAY_DIR, "BOTC"))

from cogs.jinx import JinxCog, setup


class TestJinxCog:
    def test_cog_class_exists(self):
        assert JinxCog.__name__ == "JinxCog"

    def test_cog_has_commands(self):
        bot = MagicMock()
        cog = JinxCog(bot)
        assert len(cog.get_commands()) >= 1

    def test_prefix_command_exists(self):
        bot = MagicMock()
        cog = JinxCog(bot)
        names = {c.name for c in cog.get_commands()}
        assert "jinx" in names

    def test_app_command_exists(self):
        bot = MagicMock()
        cog = JinxCog(bot)
        cmds = cog.__cog_app_commands__ if hasattr(cog, '__cog_app_commands__') else []
        assert any(c.name == "jinx" for c in cmds)

    def test_has_aliases(self):
        bot = MagicMock()
        cog = JinxCog(bot)
        for cmd in cog.get_commands():
            if cmd.name == "jinx":
                assert cmd.aliases == ["botcjinx"]

    def test_setup_is_async(self):
        assert asyncio.iscoroutinefunction(setup)
