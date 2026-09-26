"""Auction database layer.

Persists the single live blind auction per guild so it survives a bot
restart. On boot, the cog rehydrates each row and re-posts the board.
"""

import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "db")
DB_PATH = os.path.join(DB_DIR, "auction.db")

_DB_READY = False


def _connect() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_ready() -> None:
    global _DB_READY
    if not _DB_READY:
        init_auction_db()
        _DB_READY = True


def init_auction_db() -> None:
    os.makedirs(DB_DIR, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auction_live (
                guild_id INTEGER PRIMARY KEY,
                ends_at INTEGER NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )


def save_live_auction(guild_id: int, ends_at_ts: int, payload: dict) -> None:
    """Upsert the live auction for a guild."""
    _ensure_ready()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auction_live (guild_id, ends_at, payload) VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET ends_at = ?, payload = ?
            """,
            (guild_id, ends_at_ts, json.dumps(payload), ends_at_ts, json.dumps(payload)),
        )


def get_live_auction(guild_id: int) -> dict | None:
    """Return the live auction payload for a guild, or None."""
    _ensure_ready()
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM auction_live WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row["payload"])


def get_all_live_auctions() -> list[dict]:
    """Return all stored live auctions."""
    _ensure_ready()
    with _connect() as conn:
        rows = conn.execute("SELECT guild_id, payload FROM auction_live").fetchall()
    return [{"guild_id": int(r["guild_id"]), "payload": json.loads(r["payload"])} for r in rows]


def delete_live_auction(guild_id: int) -> None:
    """Remove the stored auction for a guild (called on close/cancel)."""
    _ensure_ready()
    with _connect() as conn:
        conn.execute("DELETE FROM auction_live WHERE guild_id = ?", (guild_id,))