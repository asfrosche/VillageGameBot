from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import (
    CommandEvent,
    CommandStats,
    DailyUsage,
    ErrorRecord,
    command_stats_to_row,
    daily_usage_to_row,
    row_to_command_stats,
)


class AnalyticsDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS command_stats (
                command_name    TEXT PRIMARY KEY,
                cog_name        TEXT,
                total_execs     INTEGER DEFAULT 0,
                total_failures  INTEGER DEFAULT 0,
                first_used      TIMESTAMP,
                last_used       TIMESTAMP,
                total_duration  REAL DEFAULT 0,
                min_duration    REAL,
                max_duration    REAL,
                recent_durations TEXT DEFAULT '[]',
                unique_users    INTEGER DEFAULT 0,
                user_ids        TEXT DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS daily_usage (
                date            TEXT,
                command_name    TEXT,
                cog_name        TEXT,
                executions      INTEGER DEFAULT 0,
                failures        INTEGER DEFAULT 0,
                total_duration  REAL DEFAULT 0,
                unique_users    INTEGER DEFAULT 0,
                user_ids        TEXT DEFAULT '[]',
                PRIMARY KEY (date, command_name)
            );

            CREATE TABLE IF NOT EXISTS weekly_usage (
                week_start      TEXT,
                command_name    TEXT,
                cog_name        TEXT,
                executions      INTEGER DEFAULT 0,
                failures        INTEGER DEFAULT 0,
                total_duration  REAL DEFAULT 0,
                unique_users    INTEGER DEFAULT 0,
                user_ids        TEXT DEFAULT '[]',
                PRIMARY KEY (week_start, command_name)
            );

            CREATE TABLE IF NOT EXISTS error_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TIMESTAMP,
                command_name    TEXT,
                cog_name        TEXT,
                exception_type  TEXT,
                traceback       TEXT,
                user_id         TEXT,
                guild_id        TEXT
            );
        """)
        conn.commit()

    def upsert_command_stats(self, event: CommandEvent) -> None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM command_stats WHERE command_name = ?", (event.command_name,)
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO command_stats
                   (command_name, cog_name, total_execs, total_failures, first_used, last_used,
                    total_duration, min_duration, max_duration, recent_durations, unique_users, user_ids)
                   VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    event.command_name,
                    event.cog_name,
                    1 if not event.success else 0,
                    event.timestamp.isoformat(),
                    event.timestamp.isoformat(),
                    event.duration_ms,
                    event.duration_ms,
                    event.duration_ms,
                    json.dumps([event.duration_ms]),
                    json.dumps([event.user_id]) if event.user_id else "[]",
                ),
            )
        else:
            users = set(json.loads(row["user_ids"]))
            if event.user_id:
                users.add(event.user_id)
            recent: list[float] = json.loads(row["recent_durations"])
            recent.append(event.duration_ms)
            if len(recent) > 1000:
                recent = recent[-1000:]
            conn.execute(
                """UPDATE command_stats SET
                    cog_name = ?,
                    total_execs = total_execs + 1,
                    total_failures = total_failures + ?,
                    last_used = ?,
                    total_duration = total_duration + ?,
                    min_duration = CASE WHEN ? < min_duration THEN ? ELSE min_duration END,
                    max_duration = CASE WHEN ? > max_duration THEN ? ELSE max_duration END,
                    recent_durations = ?,
                    unique_users = ?,
                    user_ids = ?
                   WHERE command_name = ?""",
                (
                    event.cog_name or row["cog_name"],
                    1 if not event.success else 0,
                    event.timestamp.isoformat(),
                    event.duration_ms,
                    event.duration_ms,
                    event.duration_ms,
                    event.duration_ms,
                    event.duration_ms,
                    json.dumps(recent),
                    len(users),
                    json.dumps(list(users)),
                    event.command_name,
                ),
            )
        conn.commit()

    def upsert_daily_usage(self, event: CommandEvent) -> None:
        conn = self._get_conn()
        date_str = event.timestamp.strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT * FROM daily_usage WHERE date = ? AND command_name = ?",
            (date_str, event.command_name),
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO daily_usage
                   (date, command_name, cog_name, executions, failures, total_duration, unique_users, user_ids)
                   VALUES (?, ?, ?, 1, ?, ?, 1, ?)""",
                (
                    date_str,
                    event.command_name,
                    event.cog_name,
                    1 if not event.success else 0,
                    event.duration_ms,
                    json.dumps([event.user_id]) if event.user_id else "[]",
                ),
            )
        else:
            users = set(json.loads(row["user_ids"]))
            if event.user_id:
                users.add(event.user_id)
            conn.execute(
                """UPDATE daily_usage SET
                    executions = executions + 1,
                    failures = failures + ?,
                    total_duration = total_duration + ?,
                    unique_users = ?,
                    user_ids = ?
                   WHERE date = ? AND command_name = ?""",
                (
                    1 if not event.success else 0,
                    event.duration_ms,
                    len(users),
                    json.dumps(list(users)),
                    date_str,
                    event.command_name,
                ),
            )

        monday = (event.timestamp - timedelta(days=event.timestamp.weekday())).strftime("%Y-%m-%d")
        wrow = conn.execute(
            "SELECT * FROM weekly_usage WHERE week_start = ? AND command_name = ?",
            (monday, event.command_name),
        ).fetchone()
        if wrow is None:
            conn.execute(
                """INSERT INTO weekly_usage
                   (week_start, command_name, cog_name, executions, failures, total_duration, unique_users, user_ids)
                   VALUES (?, ?, ?, 1, ?, ?, 1, ?)""",
                (
                    monday,
                    event.command_name,
                    event.cog_name,
                    1 if not event.success else 0,
                    event.duration_ms,
                    json.dumps([event.user_id]) if event.user_id else "[]",
                ),
            )
        else:
            wusers = set(json.loads(wrow["user_ids"]))
            if event.user_id:
                wusers.add(event.user_id)
            conn.execute(
                """UPDATE weekly_usage SET
                    executions = executions + 1,
                    failures = failures + ?,
                    total_duration = total_duration + ?,
                    unique_users = ?,
                    user_ids = ?
                   WHERE week_start = ? AND command_name = ?""",
                (
                    1 if not event.success else 0,
                    event.duration_ms,
                    len(wusers),
                    json.dumps(list(wusers)),
                    monday,
                    event.command_name,
                ),
            )
        conn.commit()

    def insert_error(self, error: ErrorRecord) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO error_log (timestamp, command_name, cog_name, exception_type, traceback, user_id, guild_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                error.timestamp.isoformat(),
                error.command_name,
                error.cog_name,
                error.exception_type,
                error.traceback,
                error.user_id,
                error.guild_id,
            ),
        )
        conn.execute(
            "DELETE FROM error_log WHERE id NOT IN (SELECT id FROM error_log ORDER BY id DESC LIMIT 10000)"
        )
        conn.commit()

    def get_overview(self) -> dict[str, Any]:
        conn = self._get_conn()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        total = conn.execute("SELECT SUM(total_execs) as v FROM command_stats").fetchone()
        active = conn.execute(
            "SELECT COUNT(*) as v FROM command_stats WHERE total_execs > 0"
        ).fetchone()
        today_row = conn.execute(
            "SELECT SUM(executions) as v FROM daily_usage WHERE date = ?", (today,)
        ).fetchone()
        week_row = conn.execute(
            "SELECT SUM(executions) as v FROM daily_usage WHERE date >= ?", (week_ago,)
        ).fetchone()
        avg_row = conn.execute(
            "SELECT AVG(total_duration / CAST(total_execs AS REAL)) as v FROM command_stats WHERE total_execs > 0"
        ).fetchone()
        fail_row = conn.execute(
            "SELECT CAST(SUM(total_failures) AS REAL) / CAST(SUM(total_execs) AS REAL) * 100 as v FROM command_stats WHERE total_execs > 0"
        ).fetchone()

        return {
            "total_commands": total["v"] or 0,
            "active_commands": active["v"] or 0,
            "commands_today": today_row["v"] or 0,
            "commands_this_week": week_row["v"] or 0,
            "avg_time_ms": round(avg_row["v"] or 0, 1),
            "error_rate": round(fail_row["v"] or 0, 2),
        }

    def get_commands(
        self, sort: str = "total_execs", order: str = "desc", search: str = "", page: int = 1, per_page: int = 50
    ) -> list[dict[str, Any]]:
        conn = self._get_conn()
        allowed_sort = {
            "total_execs", "cog_name", "command_name", "unique_users",
            "last_used", "total_duration", "total_failures"
        }
        sort_col = sort if sort in allowed_sort else "total_execs"
        direction = "DESC" if order == "desc" else "ASC"

        where = ""
        params: list[Any] = []
        if search:
            where = "WHERE command_name LIKE ? OR cog_name LIKE ?"
            params = [f"%{search}%", f"%{search}%"]

        count = conn.execute(
            f"SELECT COUNT(*) as v FROM command_stats {where}", params
        ).fetchone()["v"]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM command_stats {where} ORDER BY {sort_col} {direction} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        items = []
        for row in rows:
            recent = json.loads(row["recent_durations"]) if row["recent_durations"] else []
            recent_sorted = sorted(recent)
            p50 = recent_sorted[len(recent_sorted) // 2] if recent_sorted else 0
            p95 = recent_sorted[int(len(recent_sorted) * 0.95)] if recent_sorted else 0
            p99 = recent_sorted[int(len(recent_sorted) * 0.99)] if recent_sorted else 0
            avg = (row["total_duration"] / row["total_execs"]) if row["total_execs"] > 0 else 0
            items.append({
                "command_name": row["command_name"],
                "cog_name": row["cog_name"],
                "total_execs": row["total_execs"],
                "total_failures": row["total_failures"],
                "unique_users": row["unique_users"],
                "first_used": row["first_used"],
                "last_used": row["last_used"],
                "avg_time_ms": round(avg, 1),
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "p99_ms": round(p99, 1),
                "min_duration": row["min_duration"],
                "max_duration": row["max_duration"],
            })

        return {"items": items, "total": count, "page": page, "per_page": per_page}

    def get_command_detail(self, name: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM command_stats WHERE command_name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        daily = conn.execute(
            "SELECT * FROM daily_usage WHERE command_name = ? ORDER BY date DESC LIMIT 90",
            (name,),
        ).fetchall()
        recent = json.loads(row["recent_durations"]) if row["recent_durations"] else []
        recent_sorted = sorted(recent)
        return {
            "command_name": row["command_name"],
            "cog_name": row["cog_name"],
            "total_execs": row["total_execs"],
            "total_failures": row["total_failures"],
            "unique_users": row["unique_users"],
            "first_used": row["first_used"],
            "last_used": row["last_used"],
            "avg_time_ms": round((row["total_duration"] / row["total_execs"]) if row["total_execs"] > 0 else 0, 1),
            "p50_ms": round(recent_sorted[len(recent_sorted) // 2] if recent_sorted else 0, 1),
            "p95_ms": round(recent_sorted[int(len(recent_sorted) * 0.95)] if recent_sorted else 0, 1),
            "p99_ms": round(recent_sorted[int(len(recent_sorted) * 0.99)] if recent_sorted else 0, 1),
            "min_duration": row["min_duration"],
            "max_duration": row["max_duration"],
            "daily_usage": [
                {"date": d["date"], "executions": d["executions"], "failures": d["failures"]}
                for d in daily
            ],
        }

    def get_errors(self, command_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_conn()
        if command_name:
            rows = conn.execute(
                "SELECT * FROM error_log WHERE command_name = ? ORDER BY id DESC LIMIT ?",
                (command_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM error_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "command_name": r["command_name"],
                "cog_name": r["cog_name"],
                "exception_type": r["exception_type"],
                "traceback": r["traceback"],
                "user_id": r["user_id"],
                "guild_id": r["guild_id"],
            }
            for r in rows
        ]

    def get_feature_health(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM command_stats WHERE total_execs > 0").fetchall()
        now = datetime.utcnow()
        results = []
        for row in rows:
            last = datetime.fromisoformat(row["last_used"]) if row["last_used"] else now
            first = datetime.fromisoformat(row["first_used"]) if row["first_used"] else now
            days_since_last = (now - last).days
            days_since_first = max((now - first).days, 1)
            freq = row["total_execs"] / days_since_first
            users = row["unique_users"]

            recent_30d = conn.execute(
                "SELECT SUM(executions) as v FROM daily_usage WHERE command_name = ? AND date >= ?",
                (row["command_name"], (now - timedelta(days=30)).strftime("%Y-%m-%d")),
            ).fetchone()["v"] or 0
            recent_90d = conn.execute(
                "SELECT SUM(executions) as v FROM daily_usage WHERE command_name = ? AND date >= ?",
                (row["command_name"], (now - timedelta(days=90)).strftime("%Y-%m-%d")),
            ).fetchone()["v"] or 0

            trend_scores = conn.execute(
                "SELECT executions FROM weekly_usage WHERE command_name = ? ORDER BY week_start DESC LIMIT 4",
                (row["command_name"],),
            ).fetchall()
            trend = "stable"
            if len(trend_scores) >= 2:
                halves = len(trend_scores) // 2
                first_half = sum(r["executions"] for r in trend_scores[halves:])
                second_half = sum(r["executions"] for r in trend_scores[:halves])
                if second_half > first_half * 1.2:
                    trend = "increasing"
                elif second_half < first_half * 0.8:
                    trend = "declining"

            score = 0
            score += max(0, 30 - days_since_last)
            score += min(freq * 3, 25)
            score += min(users * 1.5, 25)
            score += 20 if trend == "increasing" else 10 if trend == "stable" else 0
            score = max(0, min(100, int(score)))

            if score >= 80:
                rec = "KEEP"
            elif score >= 60:
                rec = "MONITOR"
            elif score >= 40:
                rec = "REVIEW"
            elif score >= 20:
                rec = "DEPRECATE"
            else:
                rec = "DELETE"

            results.append({
                "command_name": row["command_name"],
                "cog_name": row["cog_name"],
                "health_score": score,
                "total_execs": row["total_execs"],
                "unique_users": row["unique_users"],
                "last_used": row["last_used"],
                "first_used": row["first_used"],
                "executions_30d": recent_30d,
                "executions_90d": recent_90d,
                "trend": trend,
                "recommendation": rec,
            })

        results.sort(key=lambda x: x["health_score"])
        return results

    def get_cog_stats(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                cog_name,
                SUM(total_execs) as total_execs,
                SUM(total_failures) as total_failures,
                COUNT(*) as active_commands,
                AVG(total_duration / CAST(total_execs AS REAL)) as avg_latency
            FROM command_stats
            WHERE cog_name IS NOT NULL AND total_execs > 0
            GROUP BY cog_name
            ORDER BY total_execs DESC
        """).fetchall()
        total_all = sum(r["total_execs"] for r in rows) or 1
        return [
            {
                "cog_name": r["cog_name"],
                "total_execs": r["total_execs"],
                "pct": round(r["total_execs"] / total_all * 100, 1),
                "active_commands": r["active_commands"],
                "avg_latency_ms": round(r["avg_latency"] or 0, 1),
                "failure_rate": round(
                    (r["total_failures"] / r["total_execs"] * 100) if r["total_execs"] > 0 else 0, 2
                ),
            }
            for r in rows
        ]

    def get_performance_over_time(self, days: int = 30) -> list[dict[str, Any]]:
        conn = self._get_conn()
        start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT date,
                      SUM(executions) as execs,
                      SUM(total_duration) / CAST(SUM(executions) AS REAL) as avg_time,
                      SUM(failures) as fails
               FROM daily_usage
               WHERE date >= ?
               GROUP BY date
               ORDER BY date""",
            (start,),
        ).fetchall()
        return [
            {
                "date": r["date"],
                "executions": r["execs"],
                "avg_time_ms": round(r["avg_time"] or 0, 1),
                "failures": r["fails"] or 0,
            }
            for r in rows
        ]

    def get_slowest_commands(self, limit: int = 25) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT command_name, cog_name, total_execs,
                      total_duration / CAST(total_execs AS REAL) as avg_time
               FROM command_stats
               WHERE total_execs > 0
               ORDER BY avg_time DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "command_name": r["command_name"],
                "cog_name": r["cog_name"],
                "avg_time_ms": round(r["avg_time"], 1),
                "total_execs": r["total_execs"],
            }
            for r in rows
        ]

    def get_error_summary(self) -> dict[str, Any]:
        conn = self._get_conn()
        by_type = conn.execute(
            "SELECT exception_type, COUNT(*) as count FROM error_log GROUP BY exception_type ORDER BY count DESC"
        ).fetchall()
        by_command = conn.execute(
            "SELECT command_name, COUNT(*) as count FROM error_log GROUP BY command_name ORDER BY count DESC LIMIT 10"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as v FROM error_log").fetchone()["v"]
        return {
            "total_errors": total,
            "by_type": [{"type": r["exception_type"], "count": r["count"]} for r in by_type],
            "by_command": [{"command": r["command_name"], "count": r["count"]} for r in by_command],
        }
