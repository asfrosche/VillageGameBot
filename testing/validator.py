"""Runtime command validation — checks that commands exist, have help, etc."""

from __future__ import annotations

import ast
import re
from typing import Any

from ._path_utils import file_to_module
from .auditor import discover_all
from .models import TestResult


def validate_command(
    cog_class: type | None,
    command_name: str,
    is_slash: bool,
    file_path: str,
) -> TestResult:
    """Validates a single command's metadata."""
    result = TestResult(command=command_name, cog=file_path)

    # Check existence
    result.exists = False
    if cog_class:
        for name, method in cog_class.__dict__.items():
            if hasattr(method, "__discord_app_commands_command__") or hasattr(method, "__commands_command__"):
                if name == command_name or name == command_name:
                    result.exists = True
                    break

    # Check help text
    if result.exists and cog_class and command_name in dir(cog_class):
        method = getattr(cog_class, command_name)
        doc = getattr(method, "help", None) or getattr(method, "__doc__", None)
        result.help_text_ok = bool(doc and len(doc.strip()) > 0)

    return result


def validate_all_commands() -> list[TestResult]:
    """Validate every discovered command."""
    cogs = discover_all()
    results = []
    for canonical, cog_info in cogs.items():
        try:
            mod_name = file_to_module(cog_info.file)
            import importlib
            mod = importlib.import_module(mod_name)
            cog_cls = None
            if cog_info.cog_class and hasattr(mod, cog_info.cog_class):
                cog_cls = getattr(mod, cog_info.cog_class)
        except Exception as e:
            # Can't import, do basic validation
            cog_cls = None

        for cmd in cog_info.prefix_commands:
            r = validate_command(cog_cls, cmd, False, canonical)
            results.append(r)
        for cmd in cog_info.slash_commands:
            r = validate_command(cog_cls, cmd, True, canonical)
            results.append(r)

    return results
