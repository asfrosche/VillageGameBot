"""Comprehensive tests for the `testing/` framework itself."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from testing.models import (
    CogInfo,
    CommandInfo,
    CoverageInfo,
    ErrorRecord,
    load_errors,
    save_errors,
)
from testing.errors import capture_error, get_all_errors, get_error, clear_errors, flush_errors, get_failed_commands
from testing.ui import progress_bar, status_emoji
from testing.auditor import discover_all, _get_cog_name, collect_all_commands
from testing.coverage import get_project_summary, analyze_coverage, _find_test_files
from testing.generator import generate_cog_test, generate_all_missing_tests, _module_import_for


# ── Models ────────────────────────────────────────────────────────────────────

class TestCogInfo:
    def test_defaults(self):
        c = CogInfo(name="Test", file="/path/to/test.py")
        assert c.name == "Test"
        assert c.cog_class is None
        assert c.prefix_commands == []
        assert c.slash_commands == []

    def test_with_values(self):
        c = CogInfo(
            name="Test",
            file="/path/to/test.py",
            cog_class="TestCog",
            prefix_commands=["cmd1", "cmd2"],
            total_methods=5,
        )
        assert c.cog_class == "TestCog"
        assert len(c.prefix_commands) == 2


class TestCommandInfo:
    def test_defaults(self):
        c = CommandInfo(cog="test", name="hello")
        assert c.cog == "test"
        assert c.name == "hello"
        assert not c.is_slash
        assert not c.is_prefix


class TestCoverageInfo:
    def test_command_coverage_100(self):
        c = CoverageInfo(cog="test", tested_commands=5, total_commands=5)
        assert c.command_coverage == 100.0

    def test_command_coverage_half(self):
        c = CoverageInfo(cog="test", tested_commands=3, total_commands=6)
        assert c.command_coverage == 50.0

    def test_command_coverage_zero_total(self):
        c = CoverageInfo(cog="test", total_commands=0)
        assert c.command_coverage == 100.0

    def test_helper_coverage(self):
        c = CoverageInfo(cog="test", tested_helpers=2, total_helpers=8)
        assert c.helper_coverage == 25.0


class TestErrorRecord:
    def test_roundtrip_dict(self):
        e = ErrorRecord(
            id="ERR-1",
            timestamp="2024-01-01",
            cog="TestCog",
            command="testcmd",
            guild="123",
            user="456",
            args="!test",
            runtime_ms=10.5,
            exception="ValueError: test",
            traceback="Traceback...",
        )
        d = e.to_dict()
        e2 = ErrorRecord.from_dict(d)
        for field in e.__dataclass_fields__:
            assert getattr(e, field) == getattr(e2, field)

    def test_load_errors_nonexistent_file(self):
        result = load_errors()
        assert result == []

    def test_save_and_load_errors(self):
        errors = [
            ErrorRecord(
                id="ERR-1", timestamp="now", cog="C", command="c",
                guild="1", user="2", args="", runtime_ms=0,
                exception="E", traceback="",
            )
        ]
        save_errors(errors)
        loaded = load_errors()
        assert len(loaded) == 1
        assert loaded[0].id == "ERR-1"


# ── Errors ─────────────────────────────────────────────────────────────────────

class TestErrorFunctions:
    def teardown_method(self):
        clear_errors()

    def test_capture_error(self):
        try:
            raise ValueError("test error")
        except ValueError as e:
            record = capture_error("TestCog", "cmd", "guild1", "user1", "!cmd", 5.0, e)
        assert record.cog == "TestCog"
        assert record.command == "cmd"
        assert "ValueError" in record.exception

    def test_get_error_by_id(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError as e:
            record = capture_error("C", "c", "g", "u", "", 0, e)
        found = get_error(record.id)
        assert found is not None
        assert found.id == record.id

    def test_get_error_not_found(self):
        assert get_error("NONEXISTENT") is None

    def test_clear_errors(self):
        try:
            raise Exception("x")
        except Exception as e:
            capture_error("C", "c", "g", "u", "", 0, e)
        clear_errors()
        assert get_all_errors() == []

    def test_flush_errors(self):
        clear_errors()
        for i in range(5):
            try:
                raise Exception(f"err{i}")
            except Exception as e:
                capture_error("C", "c", "g", "u", "", 0, e)
        flush_errors()
        assert len(get_all_errors()) == 5

    def test_get_failed_commands(self):
        clear_errors()
        try:
            raise Exception("x")
        except Exception as e:
            capture_error("CogA", "cmd1", "g", "u", "", 0, e)
            capture_error("CogB", "cmd2", "g", "u", "", 0, e)
        failed = get_failed_commands()
        assert "CogA/cmd1" in failed
        assert "CogB/cmd2" in failed


# ── UI helpers ──────────────────────────────────────────────────────────────────

class TestProgressBar:
    def test_full(self):
        assert progress_bar(100, 10) == "█" * 10

    def test_half(self):
        assert progress_bar(50, 10) == "█" * 5 + "░" * 5

    def test_zero(self):
        assert progress_bar(0, 10) == "░" * 10

    def test_rounding(self):
        bar = progress_bar(33, 10)
        assert bar.count("█") == 3
        assert bar.count("░") == 7


class TestStatusEmoji:
    def test_green(self):
        assert status_emoji(100) == "🟢"
        assert status_emoji(80) == "🟢"

    def test_yellow(self):
        assert status_emoji(79) == "🟡"
        assert status_emoji(40) == "🟡"

    def test_red(self):
        assert status_emoji(39) == "🔴"
        assert status_emoji(0) == "🔴"


# ── Auditor ─────────────────────────────────────────────────────────────────────

class TestGetCogName:
    def test_removes_cog_suffix(self):
        assert _get_cog_name(Path("/x/economy_cog.py")) == "Economy"

    def test_handles_no_suffix(self):
        name = _get_cog_name(Path("/x/game.py"))
        assert name == "Game"

    def test_handles_empty(self):
        name = _get_cog_name(Path("/x/__init__.py"))
        assert name == "Init"


class TestDiscoverAll:
    def test_discovers_cogs(self):
        cogs = discover_all()
        assert len(cogs) > 0
        # Should find draft_cog
        assert "draft_cog" in cogs
        # Should find BOTC game
        assert "game" in cogs

    def test_cog_has_commands(self):
        cogs = discover_all()
        draft = cogs.get("draft_cog")
        assert draft is not None
        assert len(draft.prefix_commands) > 0

    def test_cog_info_structure(self):
        cogs = discover_all()
        key = next(k for k in cogs if cogs[k].cog_class is not None)
        info = cogs[key]
        assert info.name
        assert info.file
        assert info.cog_class
        assert isinstance(info.prefix_commands, list)
        assert isinstance(info.slash_commands, list)
        assert isinstance(info.views, list)
        assert info.total_methods >= 0
        assert info.line_count > 0


class TestCollectAllCommands:
    def test_returns_dict(self):
        result = collect_all_commands()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_command_info_has_name(self):
        result = collect_all_commands()
        cmds = next(iter(result.values()))
        if cmds:
            cmd = cmds[0]
            assert cmd.name
            assert cmd.cog


# ── Coverage ────────────────────────────────────────────────────────────────────

class TestFindTestFiles:
    def test_returns_dict(self):
        result = _find_test_files()
        assert isinstance(result, dict)
        # Should find at least one cog with test files
        assert len(result) > 0


class TestAnalyzeCoverage:
    def test_returns_all_cogs(self):
        result = analyze_coverage()
        assert len(result) == 45

    def test_each_cog_has_coverage_info(self):
        result = analyze_coverage()
        for canonical, cov in result.items():
            assert cov.cog == canonical
            assert cov.total_commands >= 0
            assert cov.tested_commands >= 0
            assert cov.estimated_overall >= 0

    def test_draft_cog_has_tests(self):
        result = analyze_coverage()
        draft = result.get("draft_cog")
        assert draft is not None
        assert len(draft.test_files) > 0


class TestProjectSummary:
    def test_keys_exist(self):
        s = get_project_summary()
        assert s["cogs_total"] == 45
        assert s["total_commands"] > 0
        assert s["tested_commands"] >= 0
        assert s["command_coverage"] >= 0
        assert s["helper_coverage"] >= 0
        assert s["overall_coverage"] >= 0

    def test_all_cogs_covered(self):
        s = get_project_summary()
        assert s["cogs_with_tests"] >= 1
        assert s["cogs_with_tests"] <= s["cogs_total"]


# ── Generator ───────────────────────────────────────────────────────────────────

class TestModuleImportFor:
    def test_botc_cog(self):
        line, alias = _module_import_for("/fake/path/BOTC/cogs/game.py")
        assert "BOTC.cogs" in line
        assert alias == "game"

    def test_regular_cog(self):
        line, alias = _module_import_for("/fake/path/cogs/economy_cog.py")
        assert "cogs" in line
        assert alias == "economy_cog"

    def test_unknown_path(self):
        line, alias = _module_import_for("/somewhere/else/module.py")
        assert "import" in line
        assert alias == "module"


class TestGenerateCogTest:
    def test_returns_none_for_nonexistent(self):
        assert generate_cog_test("nonexistent_cog") is None


# ── Validator ────────────────────────────────────────────────────────────────────

class TestValidator:
    def test_validate_command_none_cog(self):
        from testing.validator import validate_command
        result = validate_command(None, "testcmd", False, "test")
        assert result.command == "testcmd"
        assert not result.exists

    def test_validate_all_commands_returns_list(self):
        from testing.validator import validate_all_commands
        results = validate_all_commands()
        assert len(results) > 0
        for r in results:
            assert isinstance(r.exists, bool)


# ── Audit embed smoke tests (no Discord client needed) ─────────────────────────

class TestBuildEmbeds:
    def test_audit_embed_creates(self):
        from testing.ui import build_audit_embed
        summary = {
            "cogs_total": 44, "cogs_with_tests": 44,
            "total_commands": 296, "tested_commands": 296,
            "total_helpers": 217, "tested_helpers": 125,
            "command_coverage": 100.0, "helper_coverage": 57.6,
            "overall_coverage": 82.1,
        }
        cogs = [("test", 50.0), ("test2", 100.0)]
        embed = build_audit_embed(summary, cogs)
        assert embed.title == "🔍 BOT AUDIT"
        assert len(embed.fields) > 0

    def test_coverage_embed_creates(self):
        from testing.ui import build_coverage_embed
        from testing.models import CoverageInfo
        summary = {
            "cogs_total": 44, "cogs_with_tests": 44,
            "total_commands": 296, "tested_commands": 296,
            "total_helpers": 217, "tested_helpers": 125,
            "command_coverage": 100.0, "helper_coverage": 57.6,
            "overall_coverage": 82.1,
        }
        cov = CoverageInfo(cog="test", tested_commands=5, total_commands=5, estimated_overall=100.0)
        embed = build_coverage_embed(summary, [("test", cov)])
        assert embed.title == "📊 Test Coverage Report"

    def test_error_embed_creates(self):
        from testing.ui import build_error_embed
        record = ErrorRecord(
            id="ERR-TEST", timestamp="now", cog="Cog",
            command="cmd", guild="1", user="2", args="",
            runtime_ms=0, exception="TestError", traceback="tb",
        )
        embed = build_error_embed(record)
        assert record.id in embed.title

    def test_stats_embed_creates(self):
        from testing.ui import build_stats_embed
        embed = build_stats_embed({
            "cogs_total": 44, "cogs_with_tests": 44,
            "total_commands": 296, "total_helpers": 217,
            "command_coverage": 100.0, "helper_coverage": 57.6,
        }, [])
        assert embed.title == "📈 Testing Framework Stats"

    def test_test_result_embed_creates(self):
        from testing.ui import build_test_result_embed
        embed = build_test_result_embed([("cmd1", True, "OK"), ("cmd2", False, "Failed")])
        assert "passed" in embed.title
        assert "2" in embed.title
