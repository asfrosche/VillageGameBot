from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CommandEvent:
    command_name: str
    cog_name: str | None
    timestamp: datetime
    duration_ms: float
    success: bool
    user_id: str | None = None
    guild_id: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None
    bot_version: str = ""
    git_commit: str = ""

    def to_posthog(self) -> dict[str, Any]:
        return {
            "command_name": self.command_name,
            "cog_name": self.cog_name,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error_type": self.error_type,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "bot_version": self.bot_version,
            "git_commit": self.git_commit,
        }


@dataclass
class ErrorRecord:
    timestamp: datetime
    command_name: str
    cog_name: str | None
    exception_type: str
    traceback: str
    user_id: str | None = None
    guild_id: str | None = None


@dataclass
class CommandStats:
    command_name: str
    cog_name: str | None = None
    total_execs: int = 0
    total_failures: int = 0
    first_used: datetime | None = None
    last_used: datetime | None = None
    total_duration: float = 0.0
    min_duration: float | None = None
    max_duration: float | None = None
    recent_durations: list[float] = field(default_factory=list)
    unique_users: int = 0
    user_ids: set[str] = field(default_factory=set)


@dataclass
class DailyUsage:
    date: str
    command_name: str
    cog_name: str | None = None
    executions: int = 0
    failures: int = 0
    total_duration: float = 0.0
    unique_users: int = 0
    user_ids: set[str] = field(default_factory=set)


@dataclass
class CogStats:
    cog_name: str
    total_execs: int = 0
    active_commands: int = 0
    total_commands: int = 0
    avg_latency_ms: float = 0.0
    failure_rate: float = 0.0


def command_stats_to_row(s: CommandStats) -> dict[str, Any]:
    return {
        "command_name": s.command_name,
        "cog_name": s.cog_name,
        "total_execs": s.total_execs,
        "total_failures": s.total_failures,
        "first_used": s.first_used.isoformat() if s.first_used else None,
        "last_used": s.last_used.isoformat() if s.last_used else None,
        "total_duration": s.total_duration,
        "min_duration": s.min_duration,
        "max_duration": s.max_duration,
        "recent_durations": json.dumps(s.recent_durations[-1000:]),
        "unique_users": s.unique_users,
        "user_ids": json.dumps(list(s.user_ids)),
    }


def row_to_command_stats(row: dict[str, Any]) -> CommandStats:
    return CommandStats(
        command_name=row["command_name"],
        cog_name=row.get("cog_name"),
        total_execs=row["total_execs"],
        total_failures=row["total_failures"],
        first_used=datetime.fromisoformat(row["first_used"]) if row.get("first_used") else None,
        last_used=datetime.fromisoformat(row["last_used"]) if row.get("last_used") else None,
        total_duration=row["total_duration"],
        min_duration=row.get("min_duration"),
        max_duration=row.get("max_duration"),
        recent_durations=json.loads(row.get("recent_durations", "[]")),
        unique_users=row["unique_users"],
        user_ids=set(json.loads(row.get("user_ids", "[]"))),
    )


def daily_usage_to_row(d: DailyUsage) -> dict[str, Any]:
    return {
        "date": d.date,
        "command_name": d.command_name,
        "cog_name": d.cog_name,
        "executions": d.executions,
        "failures": d.failures,
        "total_duration": d.total_duration,
        "unique_users": d.unique_users,
        "user_ids": json.dumps(list(d.user_ids)),
    }
