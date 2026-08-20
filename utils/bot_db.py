import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "db")
DB_PATH = os.path.join(DB_DIR, "bot.db")

_DB_READY = False
_MIGRATION_ATTEMPTED = False


def _connect() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_ready() -> None:
    global _DB_READY, _MIGRATION_ATTEMPTED
    if not _DB_READY:
        init_db()
        _DB_READY = True

    # Best-effort one-time migration; safe to call even if already done.
    if not _MIGRATION_ATTEMPTED:
        _MIGRATION_ATTEMPTED = True
        migrate_legacy_json()


def init_db() -> None:
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_visit_rc_allocation (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                day_normal INTEGER NOT NULL DEFAULT 0,
                day_forced INTEGER NOT NULL DEFAULT 0,
                day_stealth INTEGER NOT NULL DEFAULT 0,
                night_normal INTEGER NOT NULL DEFAULT 0,
                night_forced INTEGER NOT NULL DEFAULT 0,
                night_stealth INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_visit_rc_usage (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                normal_used INTEGER NOT NULL DEFAULT 0,
                forced_used INTEGER NOT NULL DEFAULT 0,
                stealth_used INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_data (
                guild_id INTEGER PRIMARY KEY,
                data_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_packages (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                package_ids TEXT NOT NULL,
                card_id INTEGER,
                updated_by INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS target_channels (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meeting_blocked_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meeting_cooldowns (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                cooldown_until TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        # Dashboard / role info
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_dashboards (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                team TEXT NOT NULL,
                visits_normal INTEGER NOT NULL DEFAULT 0,
                visits_forced INTEGER NOT NULL DEFAULT 0,
                visits_stealth INTEGER NOT NULL DEFAULT 0,
                visit_blocked INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_passive_abilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                description TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_active_abilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL
            )
            """
        )

        # Actions logging (confirmed done actions)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS actions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                player_id INTEGER,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                marked_at TEXT NOT NULL,
                marked_by_id INTEGER NOT NULL
            )
            """
        )

        # Invites tracking (migrated from invites.db)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                guild_id INTEGER NOT NULL,
                invite_code TEXT NOT NULL,
                uses INTEGER NOT NULL,
                PRIMARY KEY (guild_id, invite_code)
            )
            """
        )

        # Deadlist (migrated from deadlist.db)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS deadlist (
                player TEXT NOT NULL,
                team TEXT NOT NULL,
                role TEXT NOT NULL,
                server INTEGER NOT NULL
            )
            """
        )

        conn.commit()


def migrate_legacy_json() -> None:
    """
    Migrate legacy JSON files from `db/` into `db/bot.db`.

    This migrates:
    - `db/<guild_id>.json` guild settings files
    - `db/target_channels.json`
    - `db/blocked_users.json`
    - `db/meeting_cooldowns.json`

    After successful migration, files are moved into `db/legacy_json/`.
    """
    # Ensure tables exist (but do not trigger nested migrations)
    init_db()

    legacy_dir = os.path.join(DB_DIR, "legacy_json")
    guild_backup_dir = os.path.join(legacy_dir, "guild_data")
    os.makedirs(guild_backup_dir, exist_ok=True)

    # Migrate `db/<guild_id>.json`
    guild_json_re = re.compile(r"^\d+\.json$")
    for name in os.listdir(DB_DIR):
        if not guild_json_re.match(name):
            continue
        src = os.path.join(DB_DIR, name)
        try:
            with open(src, "r", encoding="utf-8") as f:
                data = json.load(f)
            guild_id = int(os.path.splitext(name)[0])
            upsert_guild_data(guild_id, data)
            dst = os.path.join(guild_backup_dir, name)
            os.replace(src, dst)
        except Exception:
            # If a file can't be migrated, leave it in place.
            continue

    # Migrate `target_channels.json`
    _migrate_single_json_file(
        filename="target_channels.json",
        mover_target=os.path.join(legacy_dir, "target_channels.json"),
        handler=_migrate_target_channels_json,
    )

    # Migrate meeting json files
    _migrate_single_json_file(
        filename="blocked_users.json",
        mover_target=os.path.join(legacy_dir, "blocked_users.json"),
        handler=_migrate_blocked_users_json,
    )
    _migrate_single_json_file(
        filename="meeting_cooldowns.json",
        mover_target=os.path.join(legacy_dir, "meeting_cooldowns.json"),
        handler=_migrate_meeting_cooldowns_json,
    )


def _migrate_single_json_file(*, filename: str, mover_target: str, handler) -> None:
    src = os.path.join(DB_DIR, filename)
    if not os.path.exists(src):
        return
    try:
        with open(src, "r", encoding="utf-8") as f:
            payload = json.load(f)
        handler(payload)
        os.makedirs(os.path.dirname(mover_target), exist_ok=True)
        os.replace(src, mover_target)
    except Exception:
        # Leave it if migration fails.
        return


def _migrate_target_channels_json(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    for guild_id_str, channel_id in payload.items():
        try:
            set_target_channel(int(guild_id_str), int(channel_id))
        except Exception:
            continue


def _migrate_blocked_users_json(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    for guild_id_str, user_ids in payload.items():
        try:
            guild_id = int(guild_id_str)
        except Exception:
            continue
        if not isinstance(user_ids, list):
            continue
        for user_id in user_ids:
            try:
                add_blocked_user(guild_id, int(user_id))
            except Exception:
                continue


def _migrate_meeting_cooldowns_json(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    for guild_id_str, users in payload.items():
        try:
            guild_id = int(guild_id_str)
        except Exception:
            continue
        if not isinstance(users, dict):
            continue
        for user_id_str, ts in users.items():
            try:
                user_id = int(user_id_str)
                cooldown_until = datetime.fromisoformat(ts)
                set_meeting_cooldown(guild_id, user_id, cooldown_until)
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Guild data
# ---------------------------------------------------------------------------


def get_guild_data(guild_id: int) -> dict | None:
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            "SELECT data_json FROM guild_data WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        if not row:
            return None
        return json.loads(row["data_json"])


def upsert_guild_data(guild_id: int, data: dict) -> None:
    _ensure_ready()
    data_json = json.dumps(data, ensure_ascii=False)
    updated_at = datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO guild_data (guild_id, data_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                data_json = excluded.data_json,
                updated_at = excluded.updated_at
            """,
            (guild_id, data_json, updated_at),
        )
        conn.commit()


def delete_guild_data(guild_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute("DELETE FROM guild_data WHERE guild_id = ?", (guild_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Role package references
# ---------------------------------------------------------------------------


def save_role_package(
    channel_id: int,
    guild_id: int,
    package_message_ids: list[int],
    role_card_message_id: int | None,
    updated_by: int,
) -> None:
    """Persist the message references that make up one Role Chat package."""
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO role_packages
                (channel_id, guild_id, package_ids, card_id, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                package_ids = excluded.package_ids,
                card_id = excluded.card_id,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (
                channel_id,
                guild_id,
                json.dumps([int(value) for value in package_message_ids]),
                role_card_message_id,
                updated_by,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()


def get_role_package(channel_id: int) -> dict | None:
    """Return one persisted Role Chat package, if registered."""
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM role_packages WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["package_ids"] = [int(value) for value in json.loads(result["package_ids"])]
    except (TypeError, ValueError, json.JSONDecodeError):
        result["package_ids"] = []
    return result


def get_role_packages(guild_id: int) -> list[dict]:
    """Return all Role Chat packages registered in a guild."""
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM role_packages WHERE guild_id = ? ORDER BY channel_id",
            (guild_id,),
        ).fetchall()
    packages = []
    for row in rows:
        result = dict(row)
        try:
            result["package_ids"] = [int(value) for value in json.loads(result["package_ids"])]
        except (TypeError, ValueError, json.JSONDecodeError):
            result["package_ids"] = []
        packages.append(result)
    return packages


def delete_role_package(channel_id: int) -> None:
    """Delete a Role Chat package reference."""
    _ensure_ready()
    with _connect() as conn:
        conn.execute("DELETE FROM role_packages WHERE channel_id = ?", (channel_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# SendRole target channels
# ---------------------------------------------------------------------------


def get_target_channel(guild_id: int) -> int | None:
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            "SELECT channel_id FROM target_channels WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return int(row["channel_id"]) if row else None


def set_target_channel(guild_id: int, channel_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO target_channels (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
            """,
            (guild_id, channel_id),
        )
        conn.commit()


def delete_target_channel(guild_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute("DELETE FROM target_channels WHERE guild_id = ?", (guild_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Meeting: blocked users
# ---------------------------------------------------------------------------


def get_blocked_users(guild_id: int) -> list[int]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id FROM meeting_blocked_users WHERE guild_id = ? ORDER BY user_id ASC",
            (guild_id,),
        ).fetchall()
        return [int(r["user_id"]) for r in rows]


def add_blocked_user(guild_id: int, user_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO meeting_blocked_users (guild_id, user_id)
            VALUES (?, ?)
            """,
            (guild_id, user_id),
        )
        conn.commit()


def remove_blocked_user(guild_id: int, user_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            "DELETE FROM meeting_blocked_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Meeting: cooldowns
# ---------------------------------------------------------------------------


def get_meeting_cooldown_until(guild_id: int, user_id: int) -> datetime | None:
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            "SELECT cooldown_until FROM meeting_cooldowns WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row["cooldown_until"])
        except Exception:
            return None


def set_meeting_cooldown(guild_id: int, user_id: int, cooldown_until: datetime) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO meeting_cooldowns (guild_id, user_id, cooldown_until)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET cooldown_until = excluded.cooldown_until
            """,
            (guild_id, user_id, cooldown_until.isoformat()),
        )
        conn.commit()


def clear_meeting_cooldown(guild_id: int, user_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            "DELETE FROM meeting_cooldowns WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        conn.commit()


def list_meeting_cooldowns(guild_id: int) -> list[tuple[int, datetime]]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, cooldown_until FROM meeting_cooldowns WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        out: list[tuple[int, datetime]] = []
        for r in rows:
            try:
                out.append((int(r["user_id"]), datetime.fromisoformat(r["cooldown_until"])))
            except Exception:
                continue
        return out


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Role dashboard helpers
# ---------------------------------------------------------------------------


def upsert_role_dashboard(
    guild_id: int,
    channel_id: int,
    *,
    name: str,
    team: str,
    visits_normal: int,
    visits_forced: int,
    visits_stealth: int,
) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO role_dashboards (
                guild_id, channel_id, name, team,
                visits_normal, visits_forced, visits_stealth
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                name = excluded.name,
                team = excluded.team,
                visits_normal = excluded.visits_normal,
                visits_forced = excluded.visits_forced,
                visits_stealth = excluded.visits_stealth
            """,
            (
                guild_id,
                channel_id,
                name,
                team,
                max(0, int(visits_normal)),
                max(0, int(visits_forced)),
                max(0, int(visits_stealth)),
            ),
        )
        conn.commit()


def get_role_dashboard(guild_id: int, channel_id: int) -> dict | None:
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT name, team, visits_normal, visits_forced, visits_stealth, visit_blocked
            FROM role_dashboards
            WHERE guild_id = ? AND channel_id = ?
            """,
            (guild_id, channel_id),
        ).fetchone()
        if not row:
            return None
        return {
            "name": row["name"],
            "team": row["team"],
            "visits_normal": int(row["visits_normal"]),
            "visits_forced": int(row["visits_forced"]),
            "visits_stealth": int(row["visits_stealth"]),
            "visit_blocked": bool(row["visit_blocked"]),
        }


def set_visit_block(guild_id: int, channel_id: int, blocked: bool) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO role_dashboards (
                guild_id, channel_id, name, team,
                visits_normal, visits_forced, visits_stealth, visit_blocked
            )
            VALUES (?, ?, '', '', 0, 0, 0, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET visit_blocked = excluded.visit_blocked
            """,
            (guild_id, channel_id, 1 if blocked else 0),
        )
        conn.commit()


def set_visits(
    guild_id: int,
    channel_id: int,
    *,
    normal: int = 0,
    forced: int = 0,
    stealth: int = 0,
) -> bool:
    """Set absolute visit counts for a role dashboard. Returns True if a row was updated."""
    _ensure_ready()
    n = max(0, int(normal))
    f = max(0, int(forced))
    s = max(0, int(stealth))
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE role_dashboards
            SET visits_normal = ?, visits_forced = ?, visits_stealth = ?
            WHERE guild_id = ? AND channel_id = ?
            """,
            (n, f, s, guild_id, channel_id),
        )
        conn.commit()
        return cur.rowcount > 0


def adjust_visits(
    guild_id: int,
    channel_id: int,
    *,
    delta_normal: int = 0,
    delta_forced: int = 0,
    delta_stealth: int = 0,
) -> dict | None:
    """
    Adjust visit counts; clamps to >= 0. Returns updated dashboard dict or None.
    """
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, team, visits_normal, visits_forced, visits_stealth, visit_blocked
            FROM role_dashboards
            WHERE guild_id = ? AND channel_id = ?
            """,
            (guild_id, channel_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        vn = max(0, int(row["visits_normal"]) + int(delta_normal))
        vf = max(0, int(row["visits_forced"]) + int(delta_forced))
        vs = max(0, int(row["visits_stealth"]) + int(delta_stealth))
        cur.execute(
            """
            UPDATE role_dashboards
            SET visits_normal = ?, visits_forced = ?, visits_stealth = ?
            WHERE guild_id = ? AND channel_id = ?
            """,
            (vn, vf, vs, guild_id, channel_id),
        )
        conn.commit()
        return {
            "name": row["name"],
            "team": row["team"],
            "visits_normal": vn,
            "visits_forced": vf,
            "visits_stealth": vs,
            "visit_blocked": bool(row["visit_blocked"]),
        }


def replace_passive_abilities(guild_id: int, channel_id: int, abilities: list[str]) -> None:
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM role_passive_abilities WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        for idx, desc in enumerate(abilities, start=1):
            cur.execute(
                """
                INSERT INTO role_passive_abilities (guild_id, channel_id, position, description)
                VALUES (?, ?, ?, ?)
                """,
                (guild_id, channel_id, idx, desc),
            )
        conn.commit()


def replace_active_abilities(
    guild_id: int,
    channel_id: int,
    abilities: list[tuple[str, str]],
) -> None:
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM role_active_abilities WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        for idx, (category, desc) in enumerate(abilities, start=1):
            cur.execute(
                """
                INSERT INTO role_active_abilities (guild_id, channel_id, position, category, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, channel_id, idx, category, desc),
            )
        conn.commit()


def get_role_abilities(
    guild_id: int,
    channel_id: int,
) -> tuple[list[str], list[tuple[str, str]]]:
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT position, description
            FROM role_passive_abilities
            WHERE guild_id = ? AND channel_id = ?
            ORDER BY position ASC
            """,
            (guild_id, channel_id),
        )
        passives = [row["description"] for row in cur.fetchall()]

        cur.execute(
            """
            SELECT position, category, description
            FROM role_active_abilities
            WHERE guild_id = ? AND channel_id = ?
            ORDER BY position ASC
            """,
            (guild_id, channel_id),
        )
        actives = [(row["category"], row["description"]) for row in cur.fetchall()]

        return passives, actives


def modify_passive_ability(
    guild_id: int,
    channel_id: int,
    index: int,
    *,
    new_description: str | None = None,
    remove: bool = False,
) -> list[str]:
    """
    Modify or remove a passive ability by 1-based index. Returns new list.
    """
    passives, actives = get_role_abilities(guild_id, channel_id)
    if index < 1 or index > len(passives):
        raise IndexError("Invalid passive ability index")
    if remove:
        del passives[index - 1]
    elif new_description is not None:
        passives[index - 1] = new_description
    replace_passive_abilities(guild_id, channel_id, passives)
    return passives


def modify_active_ability(
    guild_id: int,
    channel_id: int,
    index: int,
    *,
    new_category: str | None = None,
    new_description: str | None = None,
    remove: bool = False,
) -> list[tuple[str, str]]:
    """
    Modify or remove an active ability by 1-based index. Returns new list.
    """
    passives, actives = get_role_abilities(guild_id, channel_id)
    if index < 1 or index > len(actives):
        raise IndexError("Invalid active ability index")
    if remove:
        del actives[index - 1]
    else:
        category, desc = actives[index - 1]
        if new_category is not None:
            category = new_category
        if new_description is not None:
            desc = new_description
        actives[index - 1] = (category, desc)
    replace_active_abilities(guild_id, channel_id, actives)
    return actives


# ---------------------------------------------------------------------------
# Actions log helpers
# ---------------------------------------------------------------------------


def insert_action_log(
    guild_id: int,
    channel_id: int,
    *,
    player_id: int | None,
    message: str,
    created_at: datetime,
    marked_at: datetime,
    marked_by_id: int,
) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO actions_log (
                guild_id, channel_id, player_id, message,
                created_at, marked_at, marked_by_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                player_id,
                message,
                created_at.isoformat(),
                marked_at.isoformat(),
                marked_by_id,
            ),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Auto-visit RC allocation helpers
# ---------------------------------------------------------------------------


def get_auto_visit_rc_allocation(guild_id: int, channel_id: int) -> dict | None:
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT day_normal, day_forced, day_stealth,
                   night_normal, night_forced, night_stealth
            FROM auto_visit_rc_allocation
            WHERE guild_id = ? AND channel_id = ?
            """,
            (guild_id, channel_id),
        ).fetchone()
        if not row:
            return None
        return {
            "day_normal": int(row["day_normal"]),
            "day_forced": int(row["day_forced"]),
            "day_stealth": int(row["day_stealth"]),
            "night_normal": int(row["night_normal"]),
            "night_forced": int(row["night_forced"]),
            "night_stealth": int(row["night_stealth"]),
        }


def upsert_auto_visit_rc_allocation(
    guild_id: int,
    channel_id: int,
    *,
    day_normal: int = 0,
    day_forced: int = 0,
    day_stealth: int = 0,
    night_normal: int = 0,
    night_forced: int = 0,
    night_stealth: int = 0,
) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auto_visit_rc_allocation (
                guild_id, channel_id,
                day_normal, day_forced, day_stealth,
                night_normal, night_forced, night_stealth
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                day_normal = excluded.day_normal,
                day_forced = excluded.day_forced,
                day_stealth = excluded.day_stealth,
                night_normal = excluded.night_normal,
                night_forced = excluded.night_forced,
                night_stealth = excluded.night_stealth
            """,
            (
                guild_id, channel_id,
                max(0, int(day_normal)),
                max(0, int(day_forced)),
                max(0, int(day_stealth)),
                max(0, int(night_normal)),
                max(0, int(night_forced)),
                max(0, int(night_stealth)),
            ),
        )
        conn.commit()


def add_to_auto_visit_rc_allocation(
    guild_id: int,
    channel_id: int,
    *,
    day_normal: int = 0,
    day_forced: int = 0,
    day_stealth: int = 0,
    night_normal: int = 0,
    night_forced: int = 0,
    night_stealth: int = 0,
) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auto_visit_rc_allocation (
                guild_id, channel_id,
                day_normal, day_forced, day_stealth,
                night_normal, night_forced, night_stealth
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                day_normal = MAX(0, auto_visit_rc_allocation.day_normal + excluded.day_normal),
                day_forced = MAX(0, auto_visit_rc_allocation.day_forced + excluded.day_forced),
                day_stealth = MAX(0, auto_visit_rc_allocation.day_stealth + excluded.day_stealth),
                night_normal = MAX(0, auto_visit_rc_allocation.night_normal + excluded.night_normal),
                night_forced = MAX(0, auto_visit_rc_allocation.night_forced + excluded.night_forced),
                night_stealth = MAX(0, auto_visit_rc_allocation.night_stealth + excluded.night_stealth)
            """,
            (
                guild_id, channel_id,
                max(0, int(day_normal)),
                max(0, int(day_forced)),
                max(0, int(day_stealth)),
                max(0, int(night_normal)),
                max(0, int(night_forced)),
                max(0, int(night_stealth)),
            ),
        )
        conn.commit()


def delete_auto_visit_rc_allocation(guild_id: int, channel_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            "DELETE FROM auto_visit_rc_allocation WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        conn.commit()


def list_auto_visit_rc_allocations(guild_id: int) -> list[dict]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT channel_id, day_normal, day_forced, day_stealth,
                   night_normal, night_forced, night_stealth
            FROM auto_visit_rc_allocation
            WHERE guild_id = ?
            ORDER BY channel_id ASC
            """,
            (guild_id,),
        ).fetchall()
        return [
            {
                "channel_id": int(r["channel_id"]),
                "day_normal": int(r["day_normal"]),
                "day_forced": int(r["day_forced"]),
                "day_stealth": int(r["day_stealth"]),
                "night_normal": int(r["night_normal"]),
                "night_forced": int(r["night_forced"]),
                "night_stealth": int(r["night_stealth"]),
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Auto-visit RC usage helpers
# ---------------------------------------------------------------------------


def get_auto_visit_rc_usage(guild_id: int, channel_id: int) -> dict | None:
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT normal_used, forced_used, stealth_used
            FROM auto_visit_rc_usage
            WHERE guild_id = ? AND channel_id = ?
            """,
            (guild_id, channel_id),
        ).fetchone()
        if not row:
            return None
        return {
            "normal_used": int(row["normal_used"]),
            "forced_used": int(row["forced_used"]),
            "stealth_used": int(row["stealth_used"]),
        }


def increment_auto_visit_rc_usage(
    guild_id: int,
    channel_id: int,
    *,
    delta_normal: int = 0,
    delta_forced: int = 0,
    delta_stealth: int = 0,
) -> dict:
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO auto_visit_rc_usage (guild_id, channel_id, normal_used, forced_used, stealth_used)
            VALUES (?, ?, 0, 0, 0)
            ON CONFLICT(guild_id, channel_id) DO NOTHING
            """,
            (guild_id, channel_id),
        )
        cur.execute(
            """
            UPDATE auto_visit_rc_usage
            SET normal_used = MAX(0, normal_used + ?),
                forced_used = MAX(0, forced_used + ?),
                stealth_used = MAX(0, stealth_used + ?)
            WHERE guild_id = ? AND channel_id = ?
            """,
            (delta_normal, delta_forced, delta_stealth, guild_id, channel_id),
        )
        conn.commit()
        row = cur.execute(
            "SELECT normal_used, forced_used, stealth_used FROM auto_visit_rc_usage WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        ).fetchone()
        return {
            "normal_used": int(row["normal_used"]),
            "forced_used": int(row["forced_used"]),
            "stealth_used": int(row["stealth_used"]),
        }


def reset_all_auto_visit_rc_usage(guild_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute("DELETE FROM auto_visit_rc_usage WHERE guild_id = ?", (guild_id,))
        conn.commit()


def reset_auto_visit_rc_usage(guild_id: int, channel_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            "DELETE FROM auto_visit_rc_usage WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Actions log helpers
# ---------------------------------------------------------------------------


def get_actions_for_channel(
    guild_id: int,
    channel_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, player_id, message, created_at, marked_at, marked_by_id
            FROM actions_log
            WHERE guild_id = ? AND channel_id = ?
            ORDER BY marked_at DESC
            LIMIT ? OFFSET ?
            """,
            (guild_id, channel_id, limit, offset),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            out.append(
                {
                    "id": int(r["id"]),
                    "player_id": int(r["player_id"]) if r["player_id"] is not None else None,
                    "message": r["message"],
                    "created_at": r["created_at"],
                    "marked_at": r["marked_at"],
                    "marked_by_id": int(r["marked_by_id"]),
                }
            )
        return out


# ---------------------------------------------------------------------------
# Invites tracking (consolidated from invites.db)
# ---------------------------------------------------------------------------


def load_invites(guild_id: int) -> dict[str, int]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT invite_code, uses FROM invites WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return {r["invite_code"]: int(r["uses"]) for r in rows}


def save_invites(guild_id: int, invites: dict[str, int]) -> None:
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM invites WHERE guild_id = ?", (guild_id,))
        for code, uses in invites.items():
            cur.execute(
                "INSERT INTO invites (guild_id, invite_code, uses) VALUES (?, ?, ?)",
                (guild_id, code, uses),
            )
        conn.commit()


def delete_guild_invites(guild_id: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute("DELETE FROM invites WHERE guild_id = ?", (guild_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Deadlist (consolidated from deadlist.db)
# ---------------------------------------------------------------------------


def add_player(player: str, team: str, role: str, server: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO deadlist (player, team, role, server) VALUES (?, ?, ?, ?)",
            (player, team, role, server),
        )
        conn.commit()


def remove_player(player: str, server: int) -> int:
    _ensure_ready()
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM deadlist WHERE player = ? AND server = ?",
            (player, server),
        )
        conn.commit()
        return cursor.rowcount


def get_team_players(team: str, server: int) -> list[tuple[str, str]]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT player, role FROM deadlist WHERE team = ? AND server = ?",
            (team, server),
        ).fetchall()
        return [(r["player"], r["role"]) for r in rows]


def delete_guild_deadlist(server: int) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute("DELETE FROM deadlist WHERE server = ?", (server,))
        conn.commit()
