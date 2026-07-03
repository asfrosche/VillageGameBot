"""Coverage analysis — maps existing tests to cogs and commands."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .auditor import discover_all, collect_all_commands
from .models import CoverageInfo

PROJECT_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_DIRS = [
    PROJECT_DIR / "cogs" / "tests",
    PROJECT_DIR / "BOTC" / "tests",
    PROJECT_DIR / "fifa_data" / "tests",
    Path(__file__).parent / "tests",
]


def _find_test_files() -> dict[str, list[str]]:
    """Read existing test files across all domain test dirs and map them to cogs they test."""
    cog_tests: dict[str, list[str]] = {}
    for td in TEST_DIRS:
        if not td.exists():
            continue
        for f in td.glob("test_*.py"):
            code = f.read_text(encoding="utf-8")
            # Find which cogs are imported: from X.cogs import Y
            imports = re.findall(r"(?:from\s+[\w.]+\.cogs|from\s+BOTC\.cogs)\s+import\s+(\w+)", code)
            # Also match "from cogs import X" (no dot after cogs)
            imports += re.findall(r"from\s+cogs\s+import\s+(\w+)", code)
            # Match imports of BOTC utils
            imports += re.findall(r"(?:from|import)\s+[\w.]*BOTC/utils", code)
            if "draft" in f.name or "draft" in code.lower():
                imports.append("draft_cog")
            if "botc" in f.name or "botc" in code.lower():
                imports.append("botc")
            if "game" in f.name and "botc" in code.lower():
                imports.append("game")  # BOTC game
            if "nightorder" in f.name or "night" in code.lower():
                imports.append("nightorder")
            if "script_image" in f.name:
                imports.append("script_image")
            # Default: use filename to guess
            if not imports:
                stem = re.sub(r"^test_", "", f.stem)
                imports = [stem]

            for imp in set(imports):
                cog_tests.setdefault(imp, []).append(f.name)

    return cog_tests


def _find_test_file(name: str) -> Path | None:
    """Find a test file by name across all domain test directories."""
    for td in TEST_DIRS:
        p = td / name
        if p.exists():
            return p
    return None


def _estimate_tested_commands(cog_key: str, test_files: list[str], total_commands: int) -> int:
    """Estimate how many commands have tests based on test file content."""
    if not test_files or total_commands == 0:
        return 0
    tested: set[str] = set()
    for tf in test_files:
        tf_path = _find_test_file(tf)
        if tf_path is None:
            continue
        code = tf_path.read_text(encoding="utf-8")
        # Check for explicit command name mentions
        for m in re.finditer(r"(?:test_|def test_)(\w+)", code):
            tested.add(m.group(1))
        # Check for test class names that indicate command tests
        for m in re.finditer(r"class Test(\w+)", code):
            tested.add(m.group(1))
    # cap at total_commands so we never report > 100%
    return min(len(tested), total_commands)


def analyze_coverage() -> dict[str, CoverageInfo]:
    """Build coverage info for every cog."""
    cogs = discover_all()
    test_map = _find_test_files()
    results: dict[str, CoverageInfo] = {}

    for canonical, cog in cogs.items():
        test_files = test_map.get(canonical, [])
        total_cmds = len(cog.prefix_commands) + len(cog.slash_commands)
        # Estimate tested commands based on test file presence and content
        tested_cmds = _estimate_tested_commands(canonical, test_files, total_cmds)

        # Rough helper coverage: if a test file exists for this cog, assume 50%
        # of public methods are exercised; if not, 0%.
        if test_files:
            estimated_helpers = max(1, int(cog.public_methods * 0.5))
        else:
            estimated_helpers = 0

        # Overall: weighted average of command and helper coverage
        total_testable = total_cmds + cog.public_methods
        if total_testable == 0 and test_files:
            overall = 100.0
        elif total_testable == 0:
            overall = 0.0
        else:
            cmd_score = tested_cmds / max(total_cmds, 1)
            helper_score = estimated_helpers / max(cog.public_methods, 1)
            overall = round((cmd_score * total_cmds + helper_score * cog.public_methods) / total_testable * 100, 1)

        results[canonical] = CoverageInfo(
            cog=canonical,
            tested_commands=tested_cmds,
            total_commands=total_cmds,
            tested_helpers=estimated_helpers,
            total_helpers=cog.public_methods,
            test_files=test_files,
            estimated_overall=overall,
        )

    return results


def get_project_summary() -> dict:
    """Aggregate project-wide coverage stats."""
    results = analyze_coverage()
    total_cmds = sum(c.total_commands for c in results.values())
    tested_cmds = sum(c.tested_commands for c in results.values())
    total_helpers = sum(c.total_helpers for c in results.values())
    tested_helpers = sum(c.tested_helpers for c in results.values())
    cogs_with_tests = sum(1 for c in results.values() if c.test_files)
    cogs_total = len(results)

    cmd_cov = round(tested_cmds / max(total_cmds, 1) * 100, 1)
    helper_cov = round(tested_helpers / max(total_helpers, 1) * 100, 1)
    total_testable = total_cmds + total_helpers
    total_tested = tested_cmds + tested_helpers
    overall = round(total_tested / max(total_testable, 1) * 100, 1)

    return {
        "cogs_total": cogs_total,
        "cogs_with_tests": cogs_with_tests,
        "total_commands": total_cmds,
        "tested_commands": tested_cmds,
        "total_helpers": total_helpers,
        "tested_helpers": tested_helpers,
        "command_coverage": cmd_cov,
        "helper_coverage": helper_cov,
        "overall_coverage": overall,
    }
