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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS economy_accounts (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                wallet INTEGER NOT NULL DEFAULT 0,
                bank INTEGER NOT NULL DEFAULT 0,
                last_collect_at TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS economy_shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price INTEGER NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS economy_inventory (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, item_id),
                FOREIGN KEY (item_id) REFERENCES economy_shop_items(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS economy_channel_balance (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                balance INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS economy_channel_inventory (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id, item_id),
                FOREIGN KEY (item_id) REFERENCES economy_shop_items(id) ON DELETE CASCADE
            )
            """
        )

        # Deduplicate shop items before creating unique index
        cur.execute("""
            DELETE FROM economy_shop_items
            WHERE id NOT IN (
                SELECT MIN(id) FROM economy_shop_items GROUP BY guild_id, name
            )
        """)
        # Unique constraint on shop item names per guild (prevents duplicates)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_items_guild_name ON economy_shop_items(guild_id, name)")

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
# Economy helpers
# ---------------------------------------------------------------------------


def get_economy_account(guild_id: int, user_id: int) -> tuple[int, int]:
    """
    Returns (wallet, bank). Ensures a row exists.
    """
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO economy_accounts (guild_id, user_id, wallet, bank)
            VALUES (?, ?, 0, 0)
            """,
            (guild_id, user_id),
        )
        conn.commit()
        cur.execute(
            "SELECT wallet, bank FROM economy_accounts WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return 0, 0
        return int(row["wallet"]), int(row["bank"])


def set_economy_account(
    guild_id: int,
    user_id: int,
    wallet: int,
    bank: int,
    *,
    last_collect_at: datetime | None = None,
) -> None:
    _ensure_ready()
    wallet = max(0, int(wallet))
    bank = max(0, int(bank))
    ts = last_collect_at.isoformat() if last_collect_at else None
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO economy_accounts (guild_id, user_id, wallet, bank, last_collect_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                wallet = excluded.wallet,
                bank = excluded.bank,
                last_collect_at = COALESCE(excluded.last_collect_at, economy_accounts.last_collect_at)
            """,
            (guild_id, user_id, wallet, bank, ts),
        )
        conn.commit()


def update_economy_balance(
    guild_id: int,
    user_id: int,
    *,
    delta_wallet: int = 0,
    delta_bank: int = 0,
) -> tuple[int, int]:
    """
    Atomically adjust wallet/bank; clamps to >= 0. Returns new (wallet, bank).
    """
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO economy_accounts (guild_id, user_id, wallet, bank) VALUES (?, ?, 0, 0)",
            (guild_id, user_id),
        )
        cur.execute(
            """
            UPDATE economy_accounts
            SET wallet = MAX(0, wallet + ?),
                bank = MAX(0, bank + ?)
            WHERE guild_id = ? AND user_id = ?
            """,
            (delta_wallet, delta_bank, guild_id, user_id),
        )
        conn.commit()
        row = cur.execute(
            "SELECT wallet, bank FROM economy_accounts WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return (int(row["wallet"]), int(row["bank"])) if row else (0, 0)


def transfer_economy_balance(guild_id: int, from_user_id: int, to_user_id: int, amount: int) -> bool:
    """
    Atomic wallet-to-wallet transfer between two users.
    Deducts from sender wallet (fails if insufficient), adds to recipient wallet.
    Returns True if transfer succeeded.
    """
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO economy_accounts (guild_id, user_id, wallet, bank) VALUES (?, ?, 0, 0)",
            (guild_id, from_user_id),
        )
        cur.execute(
            "INSERT OR IGNORE INTO economy_accounts (guild_id, user_id, wallet, bank) VALUES (?, ?, 0, 0)",
            (guild_id, to_user_id),
        )
        cur.execute(
            "UPDATE economy_accounts SET wallet = wallet - ? WHERE guild_id = ? AND user_id = ? AND wallet >= ?",
            (amount, guild_id, from_user_id, amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False
        cur.execute(
            "UPDATE economy_accounts SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, to_user_id),
        )
        conn.commit()
        return True


def get_last_collect_at(guild_id: int, user_id: int) -> datetime | None:
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            "SELECT last_collect_at FROM economy_accounts WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if not row or not row["last_collect_at"]:
            return None
        try:
            return datetime.fromisoformat(row["last_collect_at"])
        except Exception:
            return None


def set_last_collect_at(guild_id: int, user_id: int, when: datetime) -> None:
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO economy_accounts (guild_id, user_id, wallet, bank, last_collect_at)
            VALUES (?, ?, 0, 0, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET last_collect_at = excluded.last_collect_at
            """,
            (guild_id, user_id, when.isoformat()),
        )
        conn.commit()


def get_shop_items(guild_id: int) -> list[dict]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, description, price, is_default
            FROM economy_shop_items
            WHERE guild_id = ?
            ORDER BY price ASC, name ASC
            """,
            (guild_id,),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "description": r["description"] or "",
                "price": int(r["price"]),
                "is_default": bool(r["is_default"]),
            }
            for r in rows
        ]


def add_shop_item(
    guild_id: int,
    name: str,
    description: str,
    price: int,
    *,
    is_default: bool = False,
) -> int:
    _ensure_ready()
    price = max(0, int(price))
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO economy_shop_items (guild_id, name, description, price, is_default)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, name) DO NOTHING
            """,
            (guild_id, name, description, price, 1 if is_default else 0),
        )
        item_id = cur.lastrowid
        if item_id is None:
            row = cur.execute(
                "SELECT id FROM economy_shop_items WHERE guild_id = ? AND name = ?",
                (guild_id, name),
            ).fetchone()
            item_id = int(row["id"]) if row else 0
        conn.commit()
        return int(item_id)


def remove_shop_item(guild_id: int, item_id: int) -> bool:
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM economy_shop_items WHERE guild_id = ? AND id = ?",
            (guild_id, item_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted


def get_inventory(guild_id: int, user_id: int) -> list[dict]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.item_id, i.quantity, s.name, s.description
            FROM economy_inventory i
            JOIN economy_shop_items s ON s.id = i.item_id
            WHERE i.guild_id = ? AND i.user_id = ? AND i.quantity > 0
            ORDER BY s.name ASC
            """,
            (guild_id, user_id),
        ).fetchall()
        return [
            {
                "item_id": int(r["item_id"]),
                "name": r["name"],
                "description": r["description"] or "",
                "quantity": int(r["quantity"]),
            }
            for r in rows
        ]


def add_inventory_item(guild_id: int, user_id: int, item_id: int, delta_qty: int) -> int:
    """
    Atomically adjust quantity for a given item; returns new quantity. Clamps to >= 0.
    """
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO economy_inventory (guild_id, user_id, item_id, quantity) VALUES (?, ?, ?, 0)",
            (guild_id, user_id, item_id),
        )
        cur.execute(
            "UPDATE economy_inventory SET quantity = MAX(0, quantity + ?) WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (delta_qty, guild_id, user_id, item_id),
        )
        conn.commit()
        row = cur.execute(
            "SELECT quantity FROM economy_inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (guild_id, user_id, item_id),
        ).fetchone()
        return int(row["quantity"]) if row else 0


# Channel-based economy (rolechat balance & inventory)
def get_economy_channel_balance(guild_id: int, channel_id: int) -> int:
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            "SELECT balance FROM economy_channel_balance WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        ).fetchone()
        return int(row["balance"]) if row else 0


def update_economy_channel_balance(guild_id: int, channel_id: int, delta: int) -> int:
    """Atomically adjust channel balance; clamps to >= 0. Returns new balance."""
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO economy_channel_balance (guild_id, channel_id, balance) VALUES (?, ?, 0)",
            (guild_id, channel_id),
        )
        cur.execute(
            "UPDATE economy_channel_balance SET balance = MAX(0, balance + ?) WHERE guild_id = ? AND channel_id = ?",
            (delta, guild_id, channel_id),
        )
        conn.commit()
        row = cur.execute(
            "SELECT balance FROM economy_channel_balance WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        ).fetchone()
        return int(row["balance"]) if row else 0


def set_economy_channel_balance(guild_id: int, channel_id: int, value: int) -> int:
    """Set channel balance to an exact value (clamped >= 0). Returns new balance."""
    _ensure_ready()
    value = max(0, int(value))
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO economy_channel_balance (guild_id, channel_id, balance) VALUES (?, ?, 0)",
            (guild_id, channel_id),
        )
        cur.execute(
            "UPDATE economy_channel_balance SET balance = ? WHERE guild_id = ? AND channel_id = ?",
            (value, guild_id, channel_id),
        )
        conn.commit()
        return value


def clear_channel_inventory(guild_id: int, channel_id: int) -> int:
    """Delete all inventory rows for a channel. Returns number of rows deleted."""
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM economy_channel_inventory WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        conn.commit()
        return cur.rowcount


def get_top_economy_channels(guild_id: int, limit: int = 10) -> list[dict]:
    """Return top channels by balance, descending."""
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT channel_id, balance
            FROM economy_channel_balance
            WHERE guild_id = ? AND balance > 0
            ORDER BY balance DESC
            LIMIT ?
            """,
            (guild_id, limit),
        ).fetchall()
        return [
            {"channel_id": int(r["channel_id"]), "balance": int(r["balance"])}
            for r in rows
        ]


def get_inventory_channel(guild_id: int, channel_id: int) -> list[dict]:
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.item_id, i.quantity, s.name, s.description
            FROM economy_channel_inventory i
            JOIN economy_shop_items s ON s.id = i.item_id
            WHERE i.guild_id = ? AND i.channel_id = ? AND i.quantity > 0
            ORDER BY s.name ASC
            """,
            (guild_id, channel_id),
        ).fetchall()
        return [
            {
                "item_id": int(r["item_id"]),
                "name": r["name"],
                "description": r["description"] or "",
                "quantity": int(r["quantity"]),
            }
            for r in rows
        ]


def add_inventory_item_channel(guild_id: int, channel_id: int, item_id: int, delta_qty: int) -> int:
    """Atomically adjust channel inventory quantity; clamps to >= 0. Returns new quantity."""
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO economy_channel_inventory (guild_id, channel_id, item_id, quantity) VALUES (?, ?, ?, 0)",
            (guild_id, channel_id, item_id),
        )
        cur.execute(
            "UPDATE economy_channel_inventory SET quantity = MAX(0, quantity + ?) WHERE guild_id = ? AND channel_id = ? AND item_id = ?",
            (delta_qty, guild_id, channel_id, item_id),
        )
        conn.commit()
        row = cur.execute(
            "SELECT quantity FROM economy_channel_inventory WHERE guild_id = ? AND channel_id = ? AND item_id = ?",
            (guild_id, channel_id, item_id),
        ).fetchone()
        return int(row["quantity"]) if row else 0


def buy_shop_item(guild_id: int, channel_id: int, item_id: int, price: int, quantity: int = 1) -> tuple[bool, int]:
    """
    Atomic purchase: deduct balance and add inventory in one transaction.
    Returns (success, new_quantity).
    """
    _ensure_ready()
    total_cost = price * quantity
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO economy_channel_balance (guild_id, channel_id, balance) VALUES (?, ?, 0)",
            (guild_id, channel_id),
        )
        cur.execute(
            "INSERT OR IGNORE INTO economy_channel_inventory (guild_id, channel_id, item_id, quantity) VALUES (?, ?, ?, 0)",
            (guild_id, channel_id, item_id),
        )
        cur.execute(
            "UPDATE economy_channel_balance SET balance = balance - ? WHERE guild_id = ? AND channel_id = ? AND balance >= ?",
            (total_cost, guild_id, channel_id, total_cost),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False, 0
        cur.execute(
            "UPDATE economy_channel_inventory SET quantity = quantity + ? WHERE guild_id = ? AND channel_id = ? AND item_id = ?",
            (quantity, guild_id, channel_id, item_id),
        )
        conn.commit()
        row = cur.execute(
            "SELECT quantity FROM economy_channel_inventory WHERE guild_id = ? AND channel_id = ? AND item_id = ?",
            (guild_id, channel_id, item_id),
        ).fetchone()
        return True, int(row["quantity"]) if row else 0


def transfer_channel_balance(guild_id: int, from_channel_id: int, to_channel_id: int, amount: int) -> bool:
    """
    Atomic transfer between two channel balances.
    Deducts from source (fails if insufficient), adds to destination.
    Returns True if transfer succeeded.
    """
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO economy_channel_balance (guild_id, channel_id, balance) VALUES (?, ?, 0)",
            (guild_id, from_channel_id),
        )
        cur.execute(
            "INSERT OR IGNORE INTO economy_channel_balance (guild_id, channel_id, balance) VALUES (?, ?, 0)",
            (guild_id, to_channel_id),
        )
        cur.execute(
            "UPDATE economy_channel_balance SET balance = balance - ? WHERE guild_id = ? AND channel_id = ? AND balance >= ?",
            (amount, guild_id, from_channel_id, amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False
        cur.execute(
            "UPDATE economy_channel_balance SET balance = balance + ? WHERE guild_id = ? AND channel_id = ?",
            (amount, guild_id, to_channel_id),
        )
        conn.commit()
        return True


# Shop by name (partial match, strip emoji)
def _normalize_name_for_match(name: str) -> str:
    import re
    return re.sub(r"\s+", "", re.sub(r"[^\w\s]", "", name)).lower()


def get_shop_item_by_name(guild_id: int, name_substring: str) -> dict | None:
    """Return first shop item whose name contains name_substring (case-insensitive, emoji stripped)."""
    _ensure_ready()
    key = _normalize_name_for_match(name_substring)
    if not key:
        return None
    items = get_shop_items(guild_id)
    for it in items:
        if key in _normalize_name_for_match(it["name"]):
            return it
    return None


def update_shop_item_by_name(guild_id: int, item_name: str, *, price: int | None = None, name: str | None = None, description: str | None = None) -> bool:
    _ensure_ready()
    item = get_shop_item_by_name(guild_id, item_name)
    if not item:
        return False
    with _connect() as conn:
        cur = conn.cursor()
        updates = []
        params = []
        if price is not None:
            updates.append("price = ?")
            params.append(max(0, int(price)))
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if not updates:
            return True
        params.append(guild_id)
        params.append(item["id"])
        cur.execute(
            f"UPDATE economy_shop_items SET {', '.join(updates)} WHERE guild_id = ? AND id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0


def remove_shop_item_by_name(guild_id: int, item_name: str) -> bool:
    item = get_shop_item_by_name(guild_id, item_name)
    if not item:
        return False
    return remove_shop_item(guild_id, item["id"])


def get_top_economy_users(guild_id: int, limit: int = 10) -> list[dict]:
    """
    Return top users by total (wallet + bank), descending.
    Each entry: {user_id, wallet, bank, total}.
    """
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT user_id, wallet, bank
            FROM economy_accounts
            WHERE guild_id = ? AND (wallet + bank) > 0
            ORDER BY (wallet + bank) DESC
            LIMIT ?
            """,
            (guild_id, limit),
        ).fetchall()
        return [
            {
                "user_id": int(r["user_id"]),
                "wallet": int(r["wallet"]),
                "bank": int(r["bank"]),
                "total": int(r["wallet"]) + int(r["bank"]),
            }
            for r in rows
        ]


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
