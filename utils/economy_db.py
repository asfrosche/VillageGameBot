"""Economy database layer.

All economy tables and functions live in their own database file
(``db/economy.db``), separate from the general-purpose ``db/bot.db``.

On first use, the schema is created and any economy data that previously
lived inside ``bot.db`` is migrated over (preserving IDs and relationships).
After that, economy code reads/writes ONLY from ``economy.db``.
"""

import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "db")
DB_PATH = os.path.join(DB_DIR, "economy.db")

# Versioned marker used to record a successful bot.db -> economy.db migration.
MIGRATION_MARKER_KEY = "bot_db_economy_tables"
MIGRATION_VERSION = "1"

# Order matters: shop items are referenced (via FK) by the inventory tables,
# so they must be copied first.
MIGRATION_TABLES = [
    "economy_shop_items",
    "economy_removed_default_items",
    "economy_accounts",
    "economy_inventory",
    "economy_channel_balance",
    "economy_channel_inventory",
]

_DB_READY = False
_BOT_DB_MIGRATED = False


def _connect() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_ready() -> None:
    global _DB_READY, _BOT_DB_MIGRATED
    if not _DB_READY:
        init_db()
        _DB_READY = True

    # One-time migration of any legacy economy tables living in bot.db.
    if not _BOT_DB_MIGRATED:
        _BOT_DB_MIGRATED = True
        _migrate_from_bot_db()


def init_db() -> None:
    with _connect() as conn:
        cur = conn.cursor()
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
            CREATE TABLE IF NOT EXISTS economy_removed_default_items (
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (guild_id, name)
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS migration_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
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

        conn.commit()


def _get_migration_marker() -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM migration_meta WHERE key = ?",
            (MIGRATION_MARKER_KEY,),
        ).fetchone()
        return row["value"] if row else None


def _set_migration_marker() -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO migration_meta (key, value) VALUES (?, ?)",
            (MIGRATION_MARKER_KEY, MIGRATION_VERSION),
        )
        conn.commit()


def _migrate_from_bot_db() -> None:
    """Copy economy tables from bot.db into economy.db (idempotent).

    Safe to run multiple times: existing economy.db rows are never
    overwritten or duplicated, and the old bot.db data is left untouched
    (it simply stops being used by economy code).
    """
    from utils import bot_db as _bot_db

    src_path = _bot_db.DB_PATH
    if not os.path.exists(src_path):
        return
    try:
        if _get_migration_marker() is not None:
            return
        src = sqlite3.connect(src_path)
        try:
            src.row_factory = sqlite3.Row
            src_tables = {
                r["name"]
                for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            with _connect() as conn:
                for table in MIGRATION_TABLES:
                    if table not in src_tables:
                        continue
                    columns = [
                        r["name"]
                        for r in src.execute(f"PRAGMA table_info({table})").fetchall()
                    ]
                    if not columns:
                        continue
                    col_list = ", ".join(columns)
                    placeholders = ", ".join("?" for _ in columns)
                    # Only keep inventory rows whose referenced shop item still
                    # exists, so FK relationships stay valid in the new DB.
                    if table == "economy_inventory":
                        guard = " WHERE item_id IN (SELECT id FROM economy_shop_items WHERE guild_id = economy_inventory.guild_id)"
                    elif table == "economy_channel_inventory":
                        guard = " WHERE item_id IN (SELECT id FROM economy_shop_items WHERE guild_id = economy_channel_inventory.guild_id)"
                    else:
                        guard = ""
                    rows = src.execute(f"SELECT {col_list} FROM {table}{guard}").fetchall()
                    for row in rows:
                        try:
                            conn.execute(
                                f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                                tuple(row),
                            )
                        except sqlite3.Error:
                            # Skip any single bad row rather than aborting; the
                            # marker stays unset until every table succeeds.
                            continue
                # Write the marker on the same connection/transaction: opening a
                # second connection here would hit "database is locked" while
                # this connection still holds an uncommitted write transaction.
                conn.execute(
                    "INSERT OR REPLACE INTO migration_meta (key, value) VALUES (?, ?)",
                    (MIGRATION_MARKER_KEY, MIGRATION_VERSION),
                )
        finally:
            src.close()
    except sqlite3.Error:
        # Leave the marker unset so a later run retries.
        return


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
    if amount <= 0:
        return False
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
    if not name or not name.strip():
        return 0
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
        conn.commit()
        # Resolve the item id by name: lastrowid is unreliable (returns 0) when
        # ON CONFLICT DO NOTHING skips a duplicate insert, so always look it up.
        row = cur.execute(
            "SELECT id FROM economy_shop_items WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        ).fetchone()
        return int(row["id"]) if row else 0


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


def _record_removed_default_item(guild_id: int, name: str) -> None:
    """Tombstone a removed default item so the auto-seeder does not re-add it."""
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO economy_removed_default_items (guild_id, name)
            VALUES (?, ?)
            """,
            (guild_id, name),
        )
        conn.commit()


def get_removed_default_items(guild_id: int) -> set[str]:
    """Return names of default shop items that were intentionally removed by an admin."""
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name FROM economy_removed_default_items WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return {r["name"] for r in rows}


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
    try:
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
    except sqlite3.IntegrityError:
        # Item was deleted between lookup and add; nothing to adjust.
        return 0


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
    try:
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
    except sqlite3.IntegrityError:
        # Item was deleted between lookup and add; nothing to adjust.
        return 0


def buy_shop_item(guild_id: int, channel_id: int, item_id: int, price: int, quantity: int = 1) -> tuple[bool, int]:
    """
    Atomic purchase: deduct balance and add inventory in one transaction.
    Returns (success, new_quantity). On any failure (insufficient balance or
    item deleted mid-purchase) nothing is changed.
    """
    _ensure_ready()
    if quantity <= 0:
        return False, 0
    total_cost = price * quantity
    with _connect() as conn:
        cur = conn.cursor()
        try:
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
        except sqlite3.IntegrityError:
            # Item was deleted while the purchase was in flight; roll back so the
            # balance deduction is not persisted without the item being received.
            conn.rollback()
            return False, 0


def transfer_channel_balance(guild_id: int, from_channel_id: int, to_channel_id: int, amount: int) -> bool:
    """
    Atomic transfer between two channel balances.
    Deducts from source (fails if insufficient), adds to destination.
    Returns True if transfer succeeded.
    """
    _ensure_ready()
    if amount <= 0:
        return False
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
    if name is not None and not name.strip():
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
        try:
            cur.execute(
                f"UPDATE economy_shop_items SET {', '.join(updates)} WHERE guild_id = ? AND id = ?",
                params,
            )
        except sqlite3.IntegrityError:
            # Renaming to a name that already exists in this guild (or a
            # duplicate from a race) must not crash the caller.
            return False
        ok = cur.rowcount > 0
        conn.commit()
        # Renaming a default item away must not let the seeder resurrect the
        # original default name, so tombstone the old (default) name.
        if ok and name is not None and item.get("is_default") and name != item["name"]:
            _record_removed_default_item(guild_id, item["name"])
        return ok


def remove_shop_item_by_name(guild_id: int, item_name: str) -> bool:
    item = get_shop_item_by_name(guild_id, item_name)
    if not item:
        return False
    deleted = remove_shop_item(guild_id, item["id"])
    if deleted and item.get("is_default"):
        _record_removed_default_item(guild_id, item["name"])
    return deleted


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
