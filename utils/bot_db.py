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
            """
            INSERT OR IGNORE INTO economy_accounts (guild_id, user_id, wallet, bank)
            VALUES (?, ?, 0, 0)
            """,
            (guild_id, user_id),
        )
        cur.execute(
            "SELECT wallet, bank FROM economy_accounts WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cur.fetchone()
        wallet = int(row["wallet"]) if row else 0
        bank = int(row["bank"]) if row else 0
        wallet = max(0, wallet + int(delta_wallet))
        bank = max(0, bank + int(delta_bank))
        cur.execute(
            "UPDATE economy_accounts SET wallet = ?, bank = ? WHERE guild_id = ? AND user_id = ?",
            (wallet, bank, guild_id, user_id),
        )
        conn.commit()
        return wallet, bank


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
            """,
            (guild_id, name, description, price, 1 if is_default else 0),
        )
        item_id = cur.lastrowid
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
    Adjust quantity for a given item; returns new quantity.
    """
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO economy_inventory (guild_id, user_id, item_id, quantity)
            VALUES (?, ?, ?, 0)
            """,
            (guild_id, user_id, item_id),
        )
        cur.execute(
            """
            SELECT quantity FROM economy_inventory
            WHERE guild_id = ? AND user_id = ? AND item_id = ?
            """,
            (guild_id, user_id, item_id),
        )
        row = cur.fetchone()
        qty = int(row["quantity"]) if row else 0
        qty = max(0, qty + int(delta_qty))
        cur.execute(
            """
            UPDATE economy_inventory
            SET quantity = ?
            WHERE guild_id = ? AND user_id = ? AND item_id = ?
            """,
            (qty, guild_id, user_id, item_id),
        )
        conn.commit()
        return qty


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
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO economy_channel_balance (guild_id, channel_id, balance)
            VALUES (?, ?, 0)
            """,
            (guild_id, channel_id),
        )
        cur.execute(
            "SELECT balance FROM economy_channel_balance WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        row = cur.fetchone()
        bal = int(row["balance"]) if row else 0
        bal = max(0, bal + int(delta))
        cur.execute(
            "UPDATE economy_channel_balance SET balance = ? WHERE guild_id = ? AND channel_id = ?",
            (bal, guild_id, channel_id),
        )
        conn.commit()
        return bal


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
    _ensure_ready()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO economy_channel_inventory (guild_id, channel_id, item_id, quantity)
            VALUES (?, ?, ?, 0)
            """,
            (guild_id, channel_id, item_id),
        )
        cur.execute(
            "SELECT quantity FROM economy_channel_inventory WHERE guild_id = ? AND channel_id = ? AND item_id = ?",
            (guild_id, channel_id, item_id),
        )
        row = cur.fetchone()
        qty = int(row["quantity"]) if row else 0
        qty = max(0, qty + int(delta_qty))
        cur.execute(
            """
            UPDATE economy_channel_inventory SET quantity = ?
            WHERE guild_id = ? AND channel_id = ? AND item_id = ?
            """,
            (qty, guild_id, channel_id, item_id),
        )
        conn.commit()
        return qty


# Shop by name (partial match, strip emoji)
def _normalize_name_for_match(name: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", name)).strip().lower()


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


