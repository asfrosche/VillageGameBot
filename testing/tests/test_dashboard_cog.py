"""Tests for Dashboard cog.

The previous version of this file asserted 12 commands (dashboard_toggle, setrole,
add/remove_passive_ability, add/remove_active_ability, visitblock, checkvb,
setvisits, addvisits, removevisits, actionlog). None of them exist anywhere in the
codebase — not in this cog, not in any other — so those tests could never pass and
only asserted a UI that had been removed. They also asserted "has help" via
``getattr(method, 'help')``, which returns discord.py's protocol stub rather than
real help text, so the check passed regardless of whether a docstring existed.

These tests cover the commands the cog actually registers.
"""

import asyncio

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import discord

from cogs import dashboard_cog

EXPECTED_COMMANDS = {
    "dashboard_cmd": "dashboard",
    "view_or_edit_status": "statuss",
    "unlock_ability_cmd": "unlockability",
}


class TestDashboard:
    """Validate the cog's real commands exist and are registered under the right names."""

    @pytest.mark.parametrize("attr,command_name", sorted(EXPECTED_COMMANDS.items()))
    def test_command_exists(self, attr, command_name):
        """Each expected command method is present on the cog."""
        assert hasattr(dashboard_cog.Dashboard, attr), f"Dashboard.{attr} is missing"

    @pytest.mark.parametrize("attr,command_name", sorted(EXPECTED_COMMANDS.items()))
    def test_command_registered_name(self, attr, command_name):
        """Each command is registered under the name players actually type."""
        cmd = getattr(dashboard_cog.Dashboard, attr)
        assert isinstance(cmd, discord.ext.commands.Command)
        assert cmd.name == command_name

    @pytest.mark.parametrize("attr,command_name", sorted(EXPECTED_COMMANDS.items()))
    def test_command_is_coroutine(self, attr, command_name):
        """Each command's callback is awaitable."""
        cmd = getattr(dashboard_cog.Dashboard, attr)
        assert asyncio.iscoroutinefunction(cmd.callback)

    def test_no_unknown_commands_asserted(self):
        """Guard against re-adding tests for commands that do not exist.

        If a command is genuinely reintroduced, add it to EXPECTED_COMMANDS above
        rather than restoring an ad-hoc existence check.
        """
        for gone in ("dashboard_toggle", "setrole", "visitblock", "checkvb", "setvisits",
                     "addvisits", "removevisits", "actionlog", "add_passive_ability",
                     "remove_passive_ability", "add_active_ability", "remove_active_ability"):
            assert not hasattr(dashboard_cog.Dashboard, gone), (
                f"Dashboard.{gone} exists again — update EXPECTED_COMMANDS to cover it"
            )
