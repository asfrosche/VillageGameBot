"""Tests for analytics data models and conversion functions."""

import json
from datetime import datetime

from utils.analytics.models import (
    CommandEvent,
    CommandStats,
    DailyUsage,
    CogStats,
    ErrorRecord,
    command_stats_to_row,
    row_to_command_stats,
    daily_usage_to_row,
)


class TestCommandEvent:
    def test_defaults(self):
        now = datetime.utcnow()
        e = CommandEvent("test_cmd", "TestCog", now, 123.4, True)
        assert e.command_name == "test_cmd"
        assert e.cog_name == "TestCog"
        assert e.timestamp == now
        assert e.duration_ms == 123.4
        assert e.success is True
        assert e.user_id is None
        assert e.guild_id is None
        assert e.error_type is None
        assert e.error_traceback is None
        assert e.bot_version == ""
        assert e.git_commit == ""

    def test_to_posthog_success(self):
        now = datetime.utcnow()
        e = CommandEvent("ping", "Utility", now, 50.0, True, user_id="123", guild_id="456")
        d = e.to_posthog()
        assert d["command_name"] == "ping"
        assert d["cog_name"] == "Utility"
        assert d["duration_ms"] == 50.0
        assert d["success"] is True
        assert d["error_type"] is None
        assert d["user_id"] == "123"
        assert d["guild_id"] == "456"

    def test_to_posthog_failure(self):
        now = datetime.utcnow()
        e = CommandEvent("ping", None, now, 12.3, False, error_type="ValueError", error_traceback="trace")
        d = e.to_posthog()
        assert d["success"] is False
        assert d["error_type"] == "ValueError"


class TestErrorRecord:
    def test_defaults(self):
        now = datetime.utcnow()
        err = ErrorRecord(now, "cmd", "Cog", "TypeError", "tb")
        assert err.timestamp == now
        assert err.command_name == "cmd"
        assert err.cog_name == "Cog"
        assert err.exception_type == "TypeError"
        assert err.traceback == "tb"
        assert err.user_id is None
        assert err.guild_id is None

    def test_with_ids(self):
        err = ErrorRecord(datetime.utcnow(), "cmd", None, "E", "tb", user_id="u1", guild_id="g1")
        assert err.user_id == "u1"
        assert err.guild_id == "g1"


class TestCommandStats:
    def test_defaults(self):
        s = CommandStats("cmd")
        assert s.command_name == "cmd"
        assert s.cog_name is None
        assert s.total_execs == 0
        assert s.total_failures == 0
        assert s.first_used is None
        assert s.last_used is None
        assert s.total_duration == 0.0
        assert s.min_duration is None
        assert s.max_duration is None
        assert s.recent_durations == []
        assert s.unique_users == 0
        assert s.user_ids == set()

    def test_with_values(self):
        now = datetime.utcnow()
        s = CommandStats("cmd", "Cog", 10, 2, now, now, 500.0, 1.0, 100.0, [1, 2, 3], 5, {"a", "b"})
        assert s.total_execs == 10
        assert s.total_failures == 2
        assert s.total_duration == 500.0
        assert s.min_duration == 1.0
        assert s.max_duration == 100.0
        assert s.recent_durations == [1, 2, 3]
        assert s.unique_users == 5
        assert s.user_ids == {"a", "b"}


class TestDailyUsage:
    def test_defaults(self):
        d = DailyUsage("2024-01-01", "cmd")
        assert d.date == "2024-01-01"
        assert d.command_name == "cmd"
        assert d.executions == 0
        assert d.failures == 0

    def test_with_values(self):
        d = DailyUsage("2024-01-01", "cmd", "Cog", 5, 1, 100.0, 3, {"x", "y"})
        assert d.executions == 5
        assert d.failures == 1
        assert d.unique_users == 3
        assert d.user_ids == {"x", "y"}


class TestCogStats:
    def test_defaults(self):
        c = CogStats("MyCog")
        assert c.cog_name == "MyCog"
        assert c.total_execs == 0
        assert c.active_commands == 0
        assert c.avg_latency_ms == 0.0
        assert c.failure_rate == 0.0

    def test_with_values(self):
        c = CogStats("MyCog", 100, 5, 8, 50.0, 2.5)
        assert c.total_execs == 100
        assert c.active_commands == 5
        assert c.total_commands == 8
        assert c.avg_latency_ms == 50.0
        assert c.failure_rate == 2.5


class TestConversions:
    def test_command_stats_roundtrip(self):
        now = datetime.utcnow()
        s = CommandStats("cmd", "Cog", 10, 2, now, now, 500.0, 1.0, 100.0, [1, 2, 3], 5, {"a", "b"})
        row = command_stats_to_row(s)
        assert row["command_name"] == "cmd"
        assert row["cog_name"] == "Cog"
        assert row["total_execs"] == 10
        assert row["total_failures"] == 2
        assert row["total_duration"] == 500.0
        assert row["min_duration"] == 1.0
        assert row["max_duration"] == 100.0
        assert row["unique_users"] == 5
        assert json.loads(row["recent_durations"]) == [1, 2, 3]
        assert json.loads(row["user_ids"]) == ["a", "b"]

        s2 = row_to_command_stats(row)
        assert s2.command_name == s.command_name
        assert s2.cog_name == s.cog_name
        assert s2.total_execs == s.total_execs
        assert s2.total_failures == s.total_failures
        assert s2.total_duration == s.total_duration
        assert s2.min_duration == s.min_duration
        assert s2.max_duration == s.max_duration
        assert s2.recent_durations == s.recent_durations
        assert s2.unique_users == s.unique_users
        assert s2.user_ids == s.user_ids

    def test_command_stats_row_nulls(self):
        row = {
            "command_name": "cmd",
            "cog_name": None,
            "total_execs": 0,
            "total_failures": 0,
            "first_used": None,
            "last_used": None,
            "total_duration": 0.0,
            "min_duration": None,
            "max_duration": None,
            "recent_durations": "[]",
            "unique_users": 0,
            "user_ids": "[]",
        }
        s = row_to_command_stats(row)
        assert s.first_used is None
        assert s.last_used is None
        assert s.min_duration is None
        assert s.max_duration is None
        assert s.recent_durations == []
        assert s.user_ids == set()

    def test_daily_usage_to_row(self):
        d = DailyUsage("2024-01-01", "cmd", "Cog", 5, 1, 100.0, 3, {"x", "y"})
        row = daily_usage_to_row(d)
        assert row["date"] == "2024-01-01"
        assert row["command_name"] == "cmd"
        assert row["cog_name"] == "Cog"
        assert row["executions"] == 5
        assert row["failures"] == 1
        assert row["total_duration"] == 100.0
        assert row["unique_users"] == 3
        assert sorted(json.loads(row["user_ids"])) == ["x", "y"]
