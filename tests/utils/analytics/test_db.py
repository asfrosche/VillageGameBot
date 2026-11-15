"""Tests for AnalyticsDB."""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from utils.analytics.db import AnalyticsDB
from utils.analytics.models import CommandEvent, ErrorRecord


@pytest.fixture
def db(tmp_path):
    """Create a fresh AnalyticsDB backed by a temp file."""
    d = AnalyticsDB(str(tmp_path / "test.db"))
    d.initialize()
    return d


@pytest.fixture
def sample_event():
    return CommandEvent("ping", "Utility", datetime.utcnow(), 50.0, True, user_id="1", guild_id="10")


class TestAnalyticsDBInit:
    def test_creates_db_file(self, tmp_path):
        db_path = str(tmp_path / "init.db")
        d = AnalyticsDB(db_path)
        d.initialize()
        assert tmp_path.joinpath("init.db").exists()

    def test_creates_all_tables(self, tmp_path):
        d = AnalyticsDB(str(tmp_path / "tables.db"))
        d.initialize()
        conn = d._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [r["name"] for r in tables]
        assert "command_stats" in names
        assert "daily_usage" in names
        assert "weekly_usage" in names
        assert "error_log" in names


class TestUpsertCommandStats:
    def test_insert_new_command(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        detail = db.get_command_detail("ping")
        assert detail["total_execs"] == 1
        assert detail["total_failures"] == 0
        assert detail["unique_users"] == 1

    def test_update_existing_command(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        e2 = CommandEvent("ping", "Utility", datetime.utcnow(), 25.0, True, user_id="1", guild_id="10")
        db.upsert_command_stats(e2)
        detail = db.get_command_detail("ping")
        assert detail["total_execs"] == 2
        assert detail["avg_time_ms"] == 37.5

    def test_tracks_unique_users(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        e2 = CommandEvent("ping", "Utility", datetime.utcnow(), 10.0, True, user_id="2", guild_id="10")
        db.upsert_command_stats(e2)
        detail = db.get_command_detail("ping")
        assert detail["unique_users"] == 2

    def test_tracks_failures(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        e2 = CommandEvent("ping", "Utility", datetime.utcnow(), 5.0, False, user_id="1")
        db.upsert_command_stats(e2)
        detail = db.get_command_detail("ping")
        assert detail["total_execs"] == 2
        assert detail["total_failures"] == 1

    def test_updates_cog_name(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        e2 = CommandEvent("ping", "NewCog", datetime.utcnow(), 10.0, True)
        db.upsert_command_stats(e2)
        detail = db.get_command_detail("ping")
        assert detail["cog_name"] == "NewCog"

    def test_maintains_recent_durations(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        for i in range(5):
            e = CommandEvent("ping", "Utility", datetime.utcnow(), float(i * 10), True)
            db.upsert_command_stats(e)
        detail = db.get_command_detail("ping")
        assert isinstance(detail["p50_ms"], float)
        assert detail["total_execs"] == 6


class TestUpsertDailyUsage:
    def test_inserts_new_day(self, db, sample_event):
        db.upsert_daily_usage(sample_event)
        conn = db._get_conn()
        row = conn.execute(
            "SELECT * FROM daily_usage WHERE command_name = ?", ("ping",)
        ).fetchone()
        assert row["executions"] == 1

    def test_updates_existing_day(self, db, sample_event):
        db.upsert_daily_usage(sample_event)
        db.upsert_daily_usage(sample_event)
        conn = db._get_conn()
        row = conn.execute(
            "SELECT * FROM daily_usage WHERE command_name = ?", ("ping",)
        ).fetchone()
        assert row["executions"] == 2

    def test_tracks_unique_users_per_day(self, db, sample_event):
        db.upsert_daily_usage(sample_event)
        e2 = CommandEvent("ping", "Utility", datetime.utcnow(), 10.0, True, user_id="2")
        db.upsert_daily_usage(e2)
        conn = db._get_conn()
        row = conn.execute(
            "SELECT * FROM daily_usage WHERE command_name = ?", ("ping",)
        ).fetchone()
        assert row["unique_users"] == 2

    def test_updates_weekly_usage(self, db, sample_event):
        db.upsert_daily_usage(sample_event)
        conn = db._get_conn()
        rows = conn.execute("SELECT * FROM weekly_usage WHERE command_name = ?", ("ping",)).fetchall()
        assert len(rows) == 1
        assert rows[0]["executions"] == 1


class TestInsertError:
    def test_inserts_error(self, db):
        error = ErrorRecord(datetime.utcnow(), "bad_cmd", "TestCog", "ValueError", "traceback here")
        db.insert_error(error)
        errs = db.get_errors()
        assert len(errs) == 1
        assert errs[0]["command_name"] == "bad_cmd"
        assert errs[0]["exception_type"] == "ValueError"

    def test_insert_errors(self, db):
        for i in range(5):
            e = ErrorRecord(datetime.utcnow(), f"cmd_{i}", None, "E", "")
            db.insert_error(e)
        errs = db.get_errors(limit=100)
        assert len(errs) == 5


class TestGetOverview:
    def test_empty_db(self, db):
        ov = db.get_overview()
        assert ov["total_commands"] == 0
        assert ov["active_commands"] == 0
        assert ov["commands_today"] == 0
        assert ov["error_rate"] == 0.0

    def test_with_data(self, db):
        e = CommandEvent("ping", "Utility", datetime.utcnow(), 50.0, True)
        db.upsert_command_stats(e)
        db.upsert_daily_usage(e)
        ov = db.get_overview()
        assert ov["total_commands"] == 1
        assert ov["active_commands"] == 1
        assert ov["commands_today"] == 1

    def test_avg_time(self, db):
        for ms in [10, 20, 30]:
            e = CommandEvent("ping", "Utility", datetime.utcnow(), float(ms), True)
            db.upsert_command_stats(e)
        ov = db.get_overview()
        assert ov["avg_time_ms"] == 20.0


class TestGetCommands:
    def test_with_data(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        result = db.get_commands()
        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["command_name"] == "ping"

    def test_search_filter(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        e2 = CommandEvent("hello", "Utility", datetime.utcnow(), 10.0, True)
        db.upsert_command_stats(e2)
        result = db.get_commands(search="ping")
        assert result["total"] == 1
        assert result["items"][0]["command_name"] == "ping"

    def test_pagination(self, db):
        for i in range(10):
            e = CommandEvent(f"cmd_{i}", "Test", datetime.utcnow(), float(i), True)
            db.upsert_command_stats(e)
        page1 = db.get_commands(per_page=3, page=1)
        assert len(page1["items"]) == 3
        assert page1["total"] == 10
        page2 = db.get_commands(per_page=3, page=2)
        assert len(page2["items"]) == 3

    def test_sort_by_execs(self, db):
        for i in range(3):
            for _ in range(i + 1):
                e = CommandEvent(f"cmd_{i}", "Test", datetime.utcnow(), float(i * 10), True)
                db.upsert_command_stats(e)
        result = db.get_commands(sort="total_execs", order="desc")
        assert result["items"][0]["total_execs"] == 3
        assert result["items"][-1]["total_execs"] == 1

    def test_empty_db(self, db):
        result = db.get_commands()
        assert result["total"] == 0
        assert len(result["items"]) == 0


class TestGetCommandDetail:
    def test_returns_none_for_missing(self, db):
        assert db.get_command_detail("nonexistent") is None

    def test_returns_detail(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        detail = db.get_command_detail("ping")
        assert detail["command_name"] == "ping"
        assert detail["total_execs"] == 1
        assert len(detail["daily_usage"]) == 0

    def test_includes_daily_usage(self, db, sample_event):
        db.upsert_command_stats(sample_event)
        db.upsert_daily_usage(sample_event)
        detail = db.get_command_detail("ping")
        assert len(detail["daily_usage"]) == 1
        assert detail["daily_usage"][0]["executions"] == 1


class TestGetErrors:
    def test_empty(self, db):
        assert db.get_errors() == []

    def test_returns_recent_first(self, db):
        for i in range(3):
            e = ErrorRecord(datetime.utcnow(), "cmd", None, "E", f"tb_{i}")
            db.insert_error(e)
        errs = db.get_errors(limit=10)
        assert len(errs) == 3
        assert errs[0]["id"] > errs[-1]["id"]

    def test_filter_by_command(self, db):
        db.insert_error(ErrorRecord(datetime.utcnow(), "cmd_a", None, "E", ""))
        db.insert_error(ErrorRecord(datetime.utcnow(), "cmd_b", None, "E", ""))
        errs = db.get_errors(command_name="cmd_a")
        assert len(errs) == 1
        assert errs[0]["command_name"] == "cmd_a"


class TestGetCogStats:
    def test_empty(self, db):
        assert db.get_cog_stats() == []

    def test_with_data(self, db):
        e = CommandEvent("ping", "Utility", datetime.utcnow(), 50.0, True)
        db.upsert_command_stats(e)
        stats = db.get_cog_stats()
        assert len(stats) == 1
        assert stats[0]["cog_name"] == "Utility"
        assert stats[0]["total_execs"] == 1
        assert stats[0]["pct"] == 100.0

    def test_multiple_cogs(self, db):
        db.upsert_command_stats(CommandEvent("ping", "Utility", datetime.utcnow(), 10.0, True))
        db.upsert_command_stats(CommandEvent("hello", "Fun", datetime.utcnow(), 20.0, True))
        stats = db.get_cog_stats()
        assert len(stats) == 2
        assert stats[0]["total_execs"] == 1
        total_pct = sum(s["pct"] for s in stats)
        assert total_pct == pytest.approx(100.0)


class TestGetSlowestCommands:
    def test_empty(self, db):
        assert db.get_slowest_commands() == []

    def test_returns_slowest_first(self, db):
        db.upsert_command_stats(CommandEvent("fast", "Test", datetime.utcnow(), 10.0, True))
        db.upsert_command_stats(CommandEvent("slow", "Test", datetime.utcnow(), 100.0, True))
        slow = db.get_slowest_commands()
        assert slow[0]["command_name"] == "slow"
        assert slow[1]["command_name"] == "fast"


class TestGetErrorSummary:
    def test_empty(self, db):
        summary = db.get_error_summary()
        assert summary["total_errors"] == 0
        assert summary["by_type"] == []
        assert summary["by_command"] == []

    def test_with_data(self, db):
        db.insert_error(ErrorRecord(datetime.utcnow(), "cmd1", None, "ValueError", ""))
        db.insert_error(ErrorRecord(datetime.utcnow(), "cmd1", None, "ValueError", ""))
        db.insert_error(ErrorRecord(datetime.utcnow(), "cmd2", None, "RuntimeError", ""))
        summary = db.get_error_summary()
        assert summary["total_errors"] == 3
        assert summary["by_type"][0]["type"] == "ValueError"
        assert summary["by_type"][0]["count"] == 2
        assert summary["by_command"][0]["command"] == "cmd1"
        assert summary["by_command"][0]["count"] == 2


class TestGetFeatureHealth:
    def test_empty(self, db):
        assert db.get_feature_health() == []

    def test_returns_all_commands(self, db):
        e = CommandEvent("ping", "Utility", datetime.utcnow(), 10.0, True)
        db.upsert_command_stats(e)
        health = db.get_feature_health()
        assert len(health) == 1
        assert health[0]["command_name"] == "ping"

    def test_health_score_is_within_range(self, db):
        e = CommandEvent("ping", "Utility", datetime.utcnow(), 10.0, True)
        db.upsert_command_stats(e)
        health = db.get_feature_health()
        assert 0 <= health[0]["health_score"] <= 100


class TestGetPerformanceOverTime:
    def test_empty(self, db):
        assert db.get_performance_over_time() == []

    def test_returns_data_within_range(self, db):
        e = CommandEvent("ping", "Utility", datetime.utcnow(), 10.0, True)
        db.upsert_command_stats(e)
        db.upsert_daily_usage(e)
        perf = db.get_performance_over_time(days=30)
        assert len(perf) >= 1
        assert perf[0]["executions"] >= 1


class TestThreadSafety:
    def test_multiple_connections(self, tmp_path):
        import threading
        db_path = str(tmp_path / "threads.db")
        d = AnalyticsDB(db_path)
        d.initialize()
        results = []

        def worker(n):
            local_db = AnalyticsDB(db_path)
            local_db.initialize()
            e = CommandEvent(f"cmd_{n}", "Test", datetime.utcnow(), float(n), True)
            local_db.upsert_command_stats(e)
            results.append(local_db.get_command_detail(f"cmd_{n}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5
