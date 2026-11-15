"""Tests for Surveillance cog (Follow + Track + Stalk)."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import discord

from cogs import surveillance_cog


class TestSurveillance:
    """Validate all commands exist and have required metadata."""

    def test_follow_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'follow')

    def test_follow_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'follow')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_unfollow_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'unfollow')

    def test_unfollow_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'unfollow')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_followlist_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'followlist')

    def test_followlist_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'followlist')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_unfollowall_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'unfollowall')

    def test_unfollowall_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'unfollowall')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_track_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'track')

    def test_track_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'track')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_untrack_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'untrack')

    def test_untrack_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'untrack')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_stalk_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'stalk')

    def test_stalk_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'stalk')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_unstalk_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'unstalk')

    def test_unstalk_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'unstalk')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_unstalkall_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'unstalkall')

    def test_unstalkall_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'unstalkall')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_stalklist_exists(self):
        assert hasattr(surveillance_cog.Surveillance, 'stalklist')

    def test_stalklist_has_help(self):
        method = getattr(surveillance_cog.Surveillance, 'stalklist')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    def test_check_follow_cycle(self):
        follows = {}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "1", "2") is False

    def test_check_follow_cycle_direct(self):
        follows = {"1": {"target": "2"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "2", "1") is False

    def test_check_follow_cycle_chain(self):
        follows = {"1": {"target": "2"}, "2": {"target": "3"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "3", "1") is True

    def test_check_follow_cycle_no_cycle(self):
        follows = {"1": {"target": "2"}, "2": {"target": "3"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "3", "4") is False
