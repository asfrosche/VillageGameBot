"""Auto-discovery engine — introspects every cog in the project."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from ._path_utils import project_root
from .models import CogInfo, CommandInfo

COGS_DIR = project_root() / "cogs"
BOTC_DIR = project_root() / "BOTC" / "cogs"
FIFA_DIR = project_root() / "fifa_data" / "services"


def _parse_file(path: Path) -> dict[str, Any]:
    """Parse a Python file with AST and regex for Discord-specific patterns."""
    code = path.read_text(encoding="utf-8")
    lines = code.split("\n")

    info: dict[str, Any] = {
        "file": str(path),
        "line_count": len(lines),
        "cog_class": None,
        "prefix_commands": [],
        "slash_commands": [],
        "context_menus": [],
        "listeners": [],
        "tasks": [],
        "views": [],
        "modals": [],
        "selects": [],
        "public_methods": 0,
        "private_methods": 0,
        "total_methods": 0,
    }

    # Cog class
    m = re.search(r"class\s+(\w+)\(.*commands\.Cog\)", code)
    if m:
        info["cog_class"] = m.group(1)

    # Views, Modals, Selects
    for pattern, key in [
        (r"class\s+(\w+)\(.*(?:ui\.View|discord\.ui\.View)\)", "views"),
        (r"class\s+(\w+)\(.*(?:ui\.Modal|discord\.ui\.Modal)\)", "modals"),
        (r"class\s+(\w+)\(.*(?:ui\.Select|discord\.ui\.Select)\)", "selects"),
    ]:
        info[key] = [m.group(1) for m in re.finditer(pattern, code)]

    # Commands — line-by-line parser, tracking multi-line decorator parens
    awaiting_prefix = False
    awaiting_slash = False
    paren_depth = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Skip blank lines
        if not stripped:
            i += 1
            continue

        if stripped.startswith("@commands.command"):
            awaiting_prefix = True
            awaiting_slash = False
            paren_depth = stripped.count("(") - stripped.count(")")
        elif stripped.startswith("@app_commands.command"):
            awaiting_slash = True
            awaiting_prefix = False
            paren_depth = stripped.count("(") - stripped.count(")")
        elif awaiting_prefix or awaiting_slash:
            # We're between a command decorator and a def
            if paren_depth > 0:
                # Still inside multi-line decorator args
                paren_depth += stripped.count("(") - stripped.count(")")
            elif stripped.startswith("@"):
                # Another decorator before def — keep waiting
                paren_depth = stripped.count("(") - stripped.count(")")
            elif (stripped.startswith("async def ") or stripped.startswith("def ")):
                name = stripped.split("(")[0].replace("async def ", "").replace("def ", "").strip()
                if awaiting_prefix:
                    info["prefix_commands"].append(name)
                else:
                    info["slash_commands"].append(name)
                awaiting_prefix = False
                awaiting_slash = False
                paren_depth = 0
            elif stripped.startswith("#"):
                pass  # comments are fine
            else:
                # Non-decorator, non-def, non-comment — reset
                awaiting_prefix = False
                awaiting_slash = False
                paren_depth = 0
        i += 1

    # Context menus
    for m in re.finditer(
        r"@app_commands\.context_menu\(.*?\)\s*\n\s+(?:async\s+)?def\s+(\w+)",
        code,
    ):
        info["context_menus"].append(m.group(1))

    # Listeners
    for m in re.finditer(r"@commands\.(?:Cog\.)?listener\s*\(.*?\)\s*\n\s+(?:async\s+)?def\s+(\w+)", code):
        info["listeners"].append(m.group(1))
    for m in re.finditer(r"bot\.add_listener\(self\.(\w+)", code):
        info["listeners"].append(m.group(1))

    # Tasks
    for m in re.finditer(r"@tasks\.loop\(.*?\)\s*\n\s+(?:async\s+)?def\s+(\w+)", code):
        info["tasks"].append(m.group(1))

    # Methods
    all_defs = re.findall(r"^\s+def ", code, re.MULTILINE)
    priv_defs = re.findall(r"^\s+def _", code, re.MULTILINE)
    info["total_methods"] = len(all_defs)
    info["private_methods"] = len(priv_defs)
    info["public_methods"] = len(all_defs) - len(priv_defs)

    return info


def _get_cog_name(path: Path) -> str:
    """Derive a human-readable cog name from a file path."""
    stem = path.stem
    # Remove _cog suffix
    name = re.sub(r"_cog$", "", stem)
    return name.replace("_", " ").title().strip()


def discover_all() -> dict[str, CogInfo]:
    """Discover every cog file and return a dict of CogInfo keyed by name."""
    cogs: dict[str, CogInfo] = {}
    for d in [COGS_DIR, BOTC_DIR, FIFA_DIR]:
        if not d.exists():
            continue
        for fpath in sorted(d.glob("*.py")):
            if fpath.name.startswith("__"):
                continue
            if fpath.stem == "worldcupsimulator":
                continue
            raw = _parse_file(fpath)
            if raw["cog_class"] is None:
                continue
            name = _get_cog_name(fpath)
            # Use filename stem as canonical name
            canonical = fpath.stem
            cogs[canonical] = CogInfo(
                name=name,
                file=str(fpath),
                cog_class=raw["cog_class"],
                prefix_commands=raw["prefix_commands"],
                slash_commands=raw["slash_commands"],
                context_menus=raw["context_menus"],
                listeners=raw["listeners"],
                tasks=raw["tasks"],
                views=raw["views"],
                modals=raw["modals"],
                selects=raw["selects"],
                public_methods=raw["public_methods"],
                private_methods=raw["private_methods"],
                total_methods=raw["total_methods"],
                line_count=raw["line_count"],
            )
    return cogs


def collect_all_commands() -> dict[str, list[CommandInfo]]:
    """Return all commands grouped by cog file stem."""
    result: dict[str, list[CommandInfo]] = {}
    for canonical, cog in discover_all().items():
        cmds = []
        for name in cog.prefix_commands:
            cmds.append(CommandInfo(cog=canonical, name=name, is_prefix=True))
        for name in cog.slash_commands:
            cmds.append(CommandInfo(cog=canonical, name=name, is_slash=True))
        result[canonical] = cmds
    return result
