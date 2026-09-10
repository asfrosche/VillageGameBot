"""Error tracking — captures command exceptions with persistence."""

from __future__ import annotations

import json
import os
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from .models import ErrorRecord, load_errors, save_errors


_error_buffer: list[ErrorRecord] = []
_counter = 0


def capture_error(
    cog: str,
    command: str,
    guild: str,
    user: str,
    args: str,
    runtime_ms: float,
    exception: Exception,
) -> ErrorRecord:
    global _counter
    _counter += 1
    now = datetime.now(timezone.utc)
    record = ErrorRecord(
        id=f"ERR-{int(now.timestamp())}-{_counter}",
        timestamp=now.isoformat(),
        cog=cog,
        command=command,
        guild=str(guild),
        user=str(user),
        args=str(args)[:500],
        runtime_ms=round(runtime_ms, 2),
        exception=f"{type(exception).__name__}: {exception}",
        traceback="".join(traceback.format_exception(type(exception), exception, exception.__traceback__)),
    )
    _error_buffer.append(record)
    # Persist every 10 errors
    if len(_error_buffer) >= 10:
        flush_errors()
    return record


def flush_errors():
    global _error_buffer
    if not _error_buffer:
        return
    existing = load_errors()
    existing.extend(_error_buffer)
    save_errors(existing)
    _error_buffer = []


def get_all_errors() -> list[ErrorRecord]:
    flushed = load_errors()
    return flushed + _error_buffer


def get_error(error_id: str) -> ErrorRecord | None:
    for err in get_all_errors():
        if err.id == error_id:
            return err
    return None


def clear_errors():
    global _error_buffer
    _error_buffer = []
    save_errors([])


def get_failed_commands() -> list[str]:
    """Return list of unique (cog, command) pairs that have failed."""
    pairs = set()
    for err in get_all_errors():
        pairs.add((err.cog, err.command))
    return sorted([f"{c}/{cmd}" for c, cmd in pairs])
