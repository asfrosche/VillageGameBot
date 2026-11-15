"""Data models for the testing framework."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CogInfo:
    name: str
    file: str
    cog_class: str | None = None
    prefix_commands: list[str] = field(default_factory=list)
    slash_commands: list[str] = field(default_factory=list)
    context_menus: list[str] = field(default_factory=list)
    listeners: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    views: list[str] = field(default_factory=list)
    modals: list[str] = field(default_factory=list)
    selects: list[str] = field(default_factory=list)
    public_methods: int = 0
    private_methods: int = 0
    total_methods: int = 0
    line_count: int = 0


@dataclass
class CommandInfo:
    cog: str
    name: str
    is_slash: bool = False
    is_prefix: bool = False
    aliases: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    has_help: bool = False
    permissions: list[str] = field(default_factory=list)
    cooldowns: list[str] = field(default_factory=list)
    autocomplete: list[str] = field(default_factory=list)
    line_number: int = 0


@dataclass
class TestResult:
    command: str
    cog: str
    passed: bool = False
    exists: bool = True
    help_text_ok: bool = False
    parameters_ok: bool = False
    permissions_ok: bool = False
    embed_builds: bool = False
    view_instantiates: bool = False
    error: str | None = None


@dataclass
class CoverageInfo:
    cog: str
    tested_commands: int = 0
    total_commands: int = 0
    tested_helpers: int = 0
    total_helpers: int = 0
    test_files: list[str] = field(default_factory=list)
    estimated_overall: float = 0.0

    @property
    def command_coverage(self) -> float:
        if self.total_commands == 0:
            return 100.0
        return round(self.tested_commands / self.total_commands * 100, 1)

    @property
    def helper_coverage(self) -> float:
        if self.total_helpers == 0:
            return 100.0
        return round(self.tested_helpers / self.total_helpers * 100, 1)


@dataclass
class ErrorRecord:
    id: str
    timestamp: str
    cog: str
    command: str
    guild: str
    user: str
    args: str
    runtime_ms: float
    exception: str
    traceback: str

    def to_dict(self) -> dict:
        return self.__dict__

    @classmethod
    def from_dict(cls, d: dict) -> ErrorRecord:
        return cls(**d)


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ERRORS_FILE = os.path.join(DATA_DIR, "errors.json")


def load_errors() -> list[ErrorRecord]:
    if not os.path.exists(ERRORS_FILE):
        return []
    with open(ERRORS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return [ErrorRecord.from_dict(e) for e in data]


def save_errors(errors: list[ErrorRecord]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ERRORS_FILE, "w", encoding="utf-8") as f:
        json.dump([e.to_dict() for e in errors], f, indent=2, ensure_ascii=False)
