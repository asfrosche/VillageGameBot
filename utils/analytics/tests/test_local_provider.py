"""Tests for LocalDBProvider."""

import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest

from utils.analytics.local_provider import LocalDBProvider
from utils.analytics.models import CommandEvent, ErrorRecord


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestLocalDBProvider:
    def test_initialize_creates_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        provider = LocalDBProvider(db_path)
        assert provider.db.db_path == db_path

    def test_initialize_creates_db_file(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        provider = LocalDBProvider(db_path)
        _run(provider.initialize())
        assert tmp_path.joinpath("test.db").exists()

    def test_capture_stores_command_stats_and_daily_usage(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        provider = LocalDBProvider(db_path)
        _run(provider.initialize())

        event = CommandEvent("ping", "Utility", datetime.utcnow(), 50.0, True)
        _run(provider.capture(event))

        ov = provider.db.get_overview()
        assert ov["total_commands"] == 1
        assert ov["active_commands"] == 1

        cmds = provider.db.get_commands()
        assert cmds["items"][0]["command_name"] == "ping"

    def test_capture_multiple_commands(self, tmp_path):
        db_path = str(tmp_path / "multi.db")
        provider = LocalDBProvider(db_path)
        _run(provider.initialize())

        _run(provider.capture(CommandEvent("ping", "Utility", datetime.utcnow(), 10.0, True)))
        _run(provider.capture(CommandEvent("hello", "Utility", datetime.utcnow(), 20.0, True)))
        _run(provider.capture(CommandEvent("ping", "Utility", datetime.utcnow(), 15.0, True)))

        ov = provider.db.get_overview()
        assert ov["total_commands"] == 3
        assert ov["active_commands"] == 2

    def test_capture_records_failure_event(self, tmp_path):
        db_path = str(tmp_path / "fail.db")
        provider = LocalDBProvider(db_path)
        _run(provider.initialize())

        event = CommandEvent("fail_cmd", "TestCog", datetime.utcnow(), 5.0, False,
                             error_type="ValueError", error_traceback="traceback here")
        _run(provider.capture(event))

        cmds = provider.db.get_commands()
        assert cmds["items"][0]["total_failures"] == 1

    def test_record_error_inserts_into_error_log(self, tmp_path):
        db_path = str(tmp_path / "err.db")
        provider = LocalDBProvider(db_path)
        _run(provider.initialize())

        error = ErrorRecord(datetime.utcnow(), "bad_cmd", "TestCog", "RuntimeError", "some tb", user_id="1", guild_id="2")
        _run(provider.record_error(error))

        errs = provider.db.get_errors()
        assert len(errs) == 1
        assert errs[0]["command_name"] == "bad_cmd"
        assert errs[0]["exception_type"] == "RuntimeError"

    def test_record_error_handles_exception(self, tmp_path):
        db_path = str(tmp_path / "err2.db")
        provider = LocalDBProvider(db_path)

        with patch.object(provider.db, "insert_error", side_effect=Exception("db fail")):
            error = ErrorRecord(datetime.utcnow(), "cmd", None, "E", "")
            _run(provider.record_error(error))

    def test_capture_handles_exception(self, tmp_path):
        db_path = str(tmp_path / "capture_fail.db")
        provider = LocalDBProvider(db_path)

        with patch.object(provider.db, "upsert_command_stats", side_effect=Exception("db fail")):
            event = CommandEvent("ping", "Utility", datetime.utcnow(), 10.0, True)
            _run(provider.capture(event))

    def test_shutdown_completes_without_error(self, tmp_path):
        db_path = str(tmp_path / "shutdown.db")
        provider = LocalDBProvider(db_path)
        _run(provider.initialize())

        _run(provider.shutdown())
