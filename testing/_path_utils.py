"""Shared path utilities for the testing framework.

Consolidates import-resolution logic previously duplicated across:
- testing/auditor.py   — COGS_DIR, BOTC_DIR, FIFA_DIR
- testing/cog.py       — _get_cog_class()
- testing/validator.py — validate_all_commands()
- testing/generator.py — _module_import_for()
"""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the absolute path to the project root (may/ directory)."""
    return Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def file_to_module(file_path: str) -> str:
    """Convert an absolute cog file path to a dotted module name.

    Examples:
        /path/to/may/cogs/foo_cog.py  →  "cogs.foo_cog"
        /path/to/may/BOTC/cogs/bar.py →  "BOTC.cogs.bar"
    """
    p = Path(file_path)
    parts = p.parts
    for i, part in enumerate(parts):
        if part in ("cogs", "BOTC"):
            mod_parts = [p.replace(".py", "") for p in parts[i:]]
            return ".".join(mod_parts)
    return p.stem
