import os
import discord
from discord.ext import commands
import sqlite3
import math
from typing import Optional, List, Tuple
import re
import asyncio
from contextlib import contextmanager
from difflib import SequenceMatcher


# ============================================================================
# CONFIGURATION
# ============================================================================

LIBRARIAN_IDS = [321117543378976771, 365954082281881600, 887214529170268190, 1082939271914201199, 1234829080898310197, 320504417520582664, 197169839863758848, 450772749829537793, 570023325653270548, 691180618402234399, 538814265599983617, 319848617814917120, 556911428712398869, 9556911428712398869, 629760692660207626, 514728129395294210, 760039727314239488]
EMBED_COLOR = 0xff3fb9
EMBED_FOOTER_TEXT = "Village Game"
EMBED_FOOTER_ICON = None

TEAMS = {
    1: "Village",
    2: "Evil",
    3: "Random Killer",
    4: "Neutral",
    5: "Bonus/Extra"
}

def add_fields_paginated(embed: discord.Embed, name: str, lines: list, inline: bool = False):
    """Add lines of text across multiple embed fields if they exceed 1024 chars.
    The first field uses `name`, subsequent ones use `name (cont.)`."""
    current = ""
    field_index = 0
    for line in lines:
        if len(current) + len(line) > 1024:
            embed.add_field(
                name=name if field_index == 0 else f"{name} (cont.)",
                value=current or "\u200b",
                inline=inline,
            )
            field_index += 1
            current = line
        else:
            current += line
    if current or field_index == 0:
        embed.add_field(
            name=name if field_index == 0 else f"{name} (cont.)",
            value=current or "*No content.*",
            inline=inline,
        )

# ============================================================================
# DATABASE CLASS
# ============================================================================

class LibraryDatabase:
    def __init__(self, db_path: str = "db/roles_library.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()

    @contextmanager
    def _connect(self):
        """Context manager for database connections. Always use this instead of
        calling sqlite3.connect() directly — it guarantees the connection is
        closed and sets row_factory so columns can be accessed by name."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_database(self):
        """Initialize database and create tables."""
        with self._connect() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='roles'")
            table_exists = cursor.fetchone() is not None

            if table_exists:
                cursor.execute("PRAGMA table_info(roles)")
                column_names = [col["name"] for col in cursor.fetchall()]

                if "count" in column_names:
                    count_index = column_names.index("count")
                    desc1_index = column_names.index("description1") if "description1" in column_names else -1

                    if desc1_index > 0 and count_index < desc1_index:
                        print("⚠️  Detected wrong column order. Starting migration...")
                        self._migrate_database(conn, cursor)
                        print("✅ Migration completed successfully!")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS roles (
                    game_number INTEGER NOT NULL,
                    game_name TEXT NOT NULL,
                    role_id INTEGER NOT NULL,
                    role_name TEXT NOT NULL,
                    team INTEGER NOT NULL,
                    player_name TEXT,
                    player_id INTEGER,
                    sponsor_name TEXT,
                    sponsor_id INTEGER,
                    win BOOLEAN DEFAULT 0,
                    description1 TEXT,
                    description2 TEXT,
                    description3 TEXT,
                    description4 TEXT,
                    count BOOLEAN DEFAULT 1,
                    mvp BOOLEAN DEFAULT 0,
                    PRIMARY KEY (game_number, role_id)
                )
            """)

            # Migrate existing databases that are missing the mvp column
            cursor.execute("PRAGMA table_info(roles)")
            existing_cols = [col["name"] for col in cursor.fetchall()]
            if "mvp" not in existing_cols:
                cursor.execute("ALTER TABLE roles ADD COLUMN mvp BOOLEAN DEFAULT 0")
                conn.commit()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS game_hosts (
                    game_number INTEGER NOT NULL,
                    host_name TEXT NOT NULL,
                    host_id INTEGER,
                    count BOOLEAN DEFAULT 1,
                    PRIMARY KEY (game_number, host_name)
                )
            """)

            conn.commit()

    def _migrate_database(self, conn, cursor):
        """Migrate database to fix column order (count must come after descriptions)."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles_new (
                game_number INTEGER NOT NULL,
                game_name TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                role_name TEXT NOT NULL,
                team INTEGER NOT NULL,
                player_name TEXT,
                player_id INTEGER,
                sponsor_name TEXT,
                sponsor_id INTEGER,
                win BOOLEAN DEFAULT 0,
                description1 TEXT,
                description2 TEXT,
                description3 TEXT,
                description4 TEXT,
                count BOOLEAN DEFAULT 1,
                mvp BOOLEAN DEFAULT 0,
                PRIMARY KEY (game_number, role_id)
            )
        """)
        cursor.execute("""
            INSERT INTO roles_new
            (game_number, game_name, role_id, role_name, team, player_name,
             player_id, sponsor_name, sponsor_id, win, description1, description2,
             description3, description4, count)
            SELECT
                game_number, game_name, role_id, role_name, team, player_name,
                player_id, sponsor_name, sponsor_id, win, description1, description2,
                description3, description4, count
            FROM roles
        """)
        cursor.execute("DROP TABLE roles")
        cursor.execute("ALTER TABLE roles_new RENAME TO roles")
        conn.commit()

    # -------------------------------------------------------------------------
    # Role / game writes
    # -------------------------------------------------------------------------

    def get_next_role_id(self, game_number: int) -> int:
        """Get next available role_id for a game."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(role_id) FROM roles WHERE game_number = ?", (game_number,))
            result = cursor.fetchone()[0]
            return (result + 1) if result is not None else 1

    def add_role(self, game_number: int, game_name: str, role_id: int,
                 role_name: str, team: int, player_name: Optional[str] = None,
                 player_id: Optional[int] = None, sponsor_name: Optional[str] = None,
                 sponsor_id: Optional[int] = None, description1: Optional[str] = None):
        """Add or replace a role."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO roles
                (game_number, game_name, role_id, role_name, team, player_name,
                 player_id, sponsor_name, sponsor_id, description1, win, count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
            """, (game_number, game_name, role_id, role_name, team, player_name,
                  player_id, sponsor_name, sponsor_id, description1))
            conn.commit()

    def update_field(self, game_number: int, role_id: int, field: str, value):
        """Update a specific field for a role."""
        valid_fields = [
            "team", "player_name", "player_id", "sponsor_name", "sponsor_id",
            "description1", "description2", "description3", "description4",
            "role_name", "win", "count", "mvp",
        ]
        if field not in valid_fields:
            raise ValueError(f"Invalid field: {field}")
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE roles SET {field} = ? WHERE game_number = ? AND role_id = ?",
                (value, game_number, role_id),
            )
            conn.commit()

    def update_game_count(self, game_number: int, count_value: int):
        """Include or exclude an entire game from stats."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE roles SET count = ? WHERE game_number = ?", (count_value, game_number))
            conn.commit()

    def delete_role(self, game_number: int, role_id: int):
        """Delete a single role."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM roles WHERE game_number = ? AND role_id = ?", (game_number, role_id))
            conn.commit()

    def delete_game(self, game_number: int):
        """Delete an entire game and all its roles."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM roles WHERE game_number = ?", (game_number,))
            conn.commit()

    def set_winners(self, game_number: int, winning_teams: List[int]):
        """Set winning teams for a game."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE roles SET win = 0 WHERE game_number = ?", (game_number,))
            if winning_teams:
                placeholders = ",".join("?" * len(winning_teams))
                cursor.execute(
                    f"UPDATE roles SET win = 1 WHERE game_number = ? AND team IN ({placeholders})",
                    [game_number] + winning_teams,
                )
            conn.commit()

    def add_hosts(self, game_number: int, hosts: list):
        """Add or replace host entries for a game (max 5)."""
        with self._connect() as conn:
            cursor = conn.cursor()
            for member in hosts[:5]:
                cursor.execute("""
                    INSERT OR REPLACE INTO game_hosts (game_number, host_name, host_id, count)
                    VALUES (?, ?, ?, 1)
                """, (game_number, member.display_name, member.id))
            conn.commit()

    # -------------------------------------------------------------------------
    # Reads — games / roles
    # -------------------------------------------------------------------------

    def get_all_games(self) -> List[Tuple[int, str]]:
        """Return all games ordered newest first."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT game_number, game_name FROM roles ORDER BY game_number DESC")
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_winning_teams(self, game_number: int) -> List[str]:
        """Return names of winning teams for a game."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT team FROM roles WHERE game_number = ? AND win = 1",
                (game_number,),
            )
            return [TEAMS.get(row[0], "Unknown") for row in cursor.fetchall()]

    def get_roles_by_team(self, game_number: int, team: int) -> List[Tuple]:
        """Return (role_id, role_name, player_name, count) for a team."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role_id, role_name, player_name, count FROM roles "
                "WHERE game_number = ? AND team = ? ORDER BY role_id",
                (game_number, team),
            )
            return cursor.fetchall()

    def get_role_details(self, game_number: int, role_id: int) -> Optional[dict]:
        """Return all fields for a single role as a dict, or None."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM roles WHERE game_number = ? AND role_id = ?",
                (game_number, role_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_game_players(self, game_number: int):
        """Return (player_name, sponsor_name, team, win) rows for counted non-bonus players."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT player_name, sponsor_name, team, win
                FROM roles
                WHERE game_number = ? AND player_id IS NOT NULL AND count = 1 AND team != 5
            """, (game_number,))
            return cursor.fetchall()

    def get_game_summary(self, game_number: int):
        """Return team counts, total roles, and winning teams for a game."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT team, COUNT(*) AS cnt FROM roles WHERE game_number = ? GROUP BY team",
                (game_number,),
            )
            team_counts = {row["team"]: row["cnt"] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) FROM roles WHERE game_number = ?", (game_number,))
            total_roles = cursor.fetchone()[0]

            cursor.execute(
                "SELECT DISTINCT team FROM roles WHERE game_number = ? AND win = 1",
                (game_number,),
            )
            winning_teams = [row[0] for row in cursor.fetchall()]

        return {"team_counts": team_counts, "total_roles": total_roles, "winning_teams": winning_teams}

    def get_hosts_for_game(self, game_number: int):
        """Return host names for a game."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT host_name FROM game_hosts WHERE game_number = ? AND count = 1",
                (game_number,),
            )
            return [row[0] for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    def search_roles_fuzzy(self, query: str, limit: int = 25) -> List[dict]:
        """LIKE-based search across role name, player name, and sponsor name."""
        with self._connect() as conn:
            cursor = conn.cursor()
            q = f"%{query.lower()}%"
            cursor.execute("""
                SELECT * FROM roles
                WHERE LOWER(role_name) LIKE ?
                   OR LOWER(player_name) LIKE ?
                   OR LOWER(sponsor_name) LIKE ?
                ORDER BY game_number DESC
                LIMIT ?
            """, (q, q, q, limit))
            return [dict(row) for row in cursor.fetchall()]

    def search_roles_by_player_name(self, player_name: str) -> List[dict]:
        """Exact (case-insensitive) player name search across all games."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM roles WHERE LOWER(player_name) = LOWER(?)", (player_name,))
            return [dict(row) for row in cursor.fetchall()]

    def search_roles_by_player_id(self, player_id: int) -> List[dict]:
        """Player ID search across all games."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM roles WHERE player_id = ?", (player_id,))
            return [dict(row) for row in cursor.fetchall()]

    def search_roles_by_sponsor_name(self, sponsor_name: str) -> List[dict]:
        """Exact (case-insensitive) sponsor name search across all games."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM roles WHERE LOWER(sponsor_name) = LOWER(?)", (sponsor_name,))
            return [dict(row) for row in cursor.fetchall()]

    def search_roles_by_sponsor_id(self, sponsor_id: int) -> List[dict]:
        """Sponsor ID search across all games."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM roles WHERE sponsor_id = ?", (sponsor_id,))
            return [dict(row) for row in cursor.fetchall()]

    # Deprecated — kept for backward compatibility
    def search_role_by_name(self, game_number: int, role_name: str) -> Optional[dict]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM roles WHERE game_number = ? AND LOWER(role_name) = LOWER(?)",
                (game_number, role_name),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    # Deprecated — kept for backward compatibility
    def search_roles_by_name_all(self, role_name: str) -> List[dict]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM roles WHERE LOWER(role_name) = LOWER(?)", (role_name,))
            return [dict(row) for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Player stats
    # -------------------------------------------------------------------------

    def get_player_stats(self, player_id: int) -> dict:
        """Return a full stats dict for a player using minimal round-trips."""
        with self._connect() as conn:
            cursor = conn.cursor()

            # All player-side stats + per-team breakdown in one query
            cursor.execute("""
                SELECT
                    COUNT(DISTINCT game_number) AS games_as_player,
                    SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins_as_player,
                    SUM(CASE WHEN team = 1 THEN 1 ELSE 0 END) AS village_total,
                    SUM(CASE WHEN team = 1 AND win = 1 THEN 1 ELSE 0 END) AS village_wins,
                    SUM(CASE WHEN team = 2 THEN 1 ELSE 0 END) AS evil_total,
                    SUM(CASE WHEN team = 2 AND win = 1 THEN 1 ELSE 0 END) AS evil_wins,
                    SUM(CASE WHEN team = 3 THEN 1 ELSE 0 END) AS rk_total,
                    SUM(CASE WHEN team = 3 AND win = 1 THEN 1 ELSE 0 END) AS rk_wins,
                    SUM(CASE WHEN team = 4 THEN 1 ELSE 0 END) AS neutral_total,
                    SUM(CASE WHEN team = 4 AND win = 1 THEN 1 ELSE 0 END) AS neutral_wins,
                    SUM(CASE WHEN team = 5 THEN 1 ELSE 0 END) AS bonus_total,
                    SUM(CASE WHEN team = 5 AND win = 1 THEN 1 ELSE 0 END) AS bonus_wins,
                    SUM(CASE WHEN mvp = 1 AND team != 5 THEN 1 ELSE 0 END) AS total_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 1 THEN 1 ELSE 0 END) AS village_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 2 THEN 1 ELSE 0 END) AS evil_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 3 THEN 1 ELSE 0 END) AS rk_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 4 THEN 1 ELSE 0 END) AS neutral_mvps
                FROM roles
                WHERE player_id = ? AND count = 1
            """, (player_id,))
            pr = cursor.fetchone()

            # Sponsor stats
            cursor.execute("""
                SELECT
                    COUNT(DISTINCT game_number) AS games_as_sponsor,
                    SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins_as_sponsor
                FROM roles
                WHERE sponsor_id = ? AND count = 1 AND team != 5
            """, (player_id,))
            sr = cursor.fetchone()

            # Unique participations — counts a game only once even if the person
            # was both player AND sponsor in the same game.
            cursor.execute("""
                SELECT COUNT(DISTINCT game_number)
                FROM roles
                WHERE (player_id = ? OR sponsor_id = ?) AND count = 1 AND team != 5
            """, (player_id, player_id))
            total_participations = cursor.fetchone()[0]

            # Total counted non-bonus games in the database
            cursor.execute("SELECT COUNT(DISTINCT game_number) FROM roles WHERE count = 1 AND team != 5")
            total_games = cursor.fetchone()[0]

            # Village winstreak
            cursor.execute("""
                SELECT game_number, win FROM roles
                WHERE player_id = ? AND count = 1 AND team = 1
                ORDER BY game_number ASC
            """, (player_id,))
            streak_rows = cursor.fetchall()

            # Overall streaks and form
            cursor.execute("""
                SELECT win FROM roles
                WHERE player_id = ? AND count = 1 AND team != 5
                ORDER BY game_number ASC
            """, (player_id,))
            all_streak_rows = cursor.fetchall()

        games_as_player = pr["games_as_player"] or 0
        wins_as_player = pr["wins_as_player"] or 0
        games_as_sponsor = sr["games_as_sponsor"] or 0
        wins_as_sponsor = sr["wins_as_sponsor"] or 0

        longest_winstreak = current_streak = 0
        for row in streak_rows:
            if row["win"] == 1:
                current_streak += 1
                longest_winstreak = max(longest_winstreak, current_streak)
            else:
                current_streak = 0

        ws = ls = cws = cls = 0
        form_list = []
        for row in all_streak_rows:
            if row["win"] == 1:
                cws += 1
                cls = 0
                ws = max(ws, cws)
                form_list.append("W")
            else:
                cls += 1
                cws = 0
                ls = max(ls, cls)
                form_list.append("L")
        
        form_str = " ".join(form_list[-5:]) if form_list else ""

        team_stats = {
            TEAMS[1]: {"total": pr["village_total"] or 0, "wins": pr["village_wins"] or 0},
            TEAMS[2]: {"total": pr["evil_total"] or 0,   "wins": pr["evil_wins"] or 0},
            TEAMS[3]: {"total": pr["rk_total"] or 0,     "wins": pr["rk_wins"] or 0},
            TEAMS[4]: {"total": pr["neutral_total"] or 0,"wins": pr["neutral_wins"] or 0},
            TEAMS[5]: {"total": pr["bonus_total"] or 0,  "wins": pr["bonus_wins"] or 0},
        }

        return {
            "games_as_player": games_as_player,
            "games_as_sponsor": games_as_sponsor,
            "total_games": total_games,
            "total_participations": total_participations,
            "participation_rate": (total_participations / total_games * 100) if total_games else 0,
            "wins_as_player": wins_as_player,
            "wins_as_sponsor": wins_as_sponsor,
            "total_wins": wins_as_player,
            "winrate": (wins_as_player / games_as_player * 100) if games_as_player else 0,
            "team_stats": team_stats,
            "longest_winstreak": longest_winstreak,
            "ws": ws,
            "ls": ls,
            "cws": cws,
            "cls": cls,
            "form": form_str,
            "total_mvps": pr["total_mvps"] or 0,
            "village_mvps": pr["village_mvps"] or 0,
            "evil_mvps": pr["evil_mvps"] or 0,
            "rk_mvps": pr["rk_mvps"] or 0,
            "neutral_mvps": pr["neutral_mvps"] or 0,
        }

    def get_all_players_stats(self) -> List[dict]:
        """Return aggregated stats for every player."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    player_id, MAX(player_name) AS player_name, COUNT(*) AS games,
                    SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN team = 1 THEN 1 ELSE 0 END) AS village_games,
                    SUM(CASE WHEN team = 1 AND win = 1 THEN 1 ELSE 0 END) AS village_wins,
                    SUM(CASE WHEN team = 2 THEN 1 ELSE 0 END) AS evil_games,
                    SUM(CASE WHEN team = 2 AND win = 1 THEN 1 ELSE 0 END) AS evil_wins,
                    SUM(CASE WHEN team = 3 THEN 1 ELSE 0 END) AS rk_games,
                    SUM(CASE WHEN team = 3 AND win = 1 THEN 1 ELSE 0 END) AS rk_wins,
                    SUM(CASE WHEN team = 4 THEN 1 ELSE 0 END) AS neutral_games,
                    SUM(CASE WHEN team = 4 AND win = 1 THEN 1 ELSE 0 END) AS neutral_wins,
                    SUM(CASE WHEN mvp = 1 AND team != 5 THEN 1 ELSE 0 END) AS total_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 1 THEN 1 ELSE 0 END) AS village_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 2 THEN 1 ELSE 0 END) AS evil_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 3 THEN 1 ELSE 0 END) AS rk_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 4 THEN 1 ELSE 0 END) AS neutral_mvps
                FROM roles
                WHERE player_id IS NOT NULL AND count = 1 AND team != 5
                GROUP BY player_id
            """)
            rows = cursor.fetchall()

            cursor.execute("""
                SELECT game_number, MIN(player_id) AS player_id
                FROM roles
                WHERE win = 1 AND player_id IS NOT NULL AND count = 1 AND team != 5
                GROUP BY game_number
                HAVING COUNT(*) = 1
            """)
            solo_rows = cursor.fetchall()

            # Streak tracking for all players
            cursor.execute("""
                SELECT player_id, win FROM roles
                WHERE player_id IS NOT NULL AND count = 1 AND team != 5
                ORDER BY player_id, game_number ASC
            """)
            game_rows = cursor.fetchall()

        solo_map: dict = {}
        for row in solo_rows:
            pid = row["player_id"]
            if pid:
                solo_map[pid] = solo_map.get(pid, 0) + 1

        streak_map = {}
        for row in game_rows:
            pid = row["player_id"]
            win = row["win"]
            if pid not in streak_map:
                streak_map[pid] = {"ws_max": 0, "ws_curr": 0, "ws_freq": 0, "ls_max": 0, "ls_curr": 0, "ls_freq": 0}
            
            s = streak_map[pid]
            if win == 1:
                s["ws_curr"] += 1
                s["ls_curr"] = 0
                if s["ws_curr"] > s["ws_max"]:
                    s["ws_max"] = s["ws_curr"]
                    s["ws_freq"] = 1
                elif s["ws_curr"] == s["ws_max"] and s["ws_max"] > 0:
                    s["ws_freq"] += 1
            else:
                s["ls_curr"] += 1
                s["ws_curr"] = 0
                if s["ls_curr"] > s["ls_max"]:
                    s["ls_max"] = s["ls_curr"]
                    s["ls_freq"] = 1
                elif s["ls_curr"] == s["ls_max"] and s["ls_max"] > 0:
                    s["ls_freq"] += 1

        stats = []
        for row in rows:
            pid = row["player_id"]
            if not pid:
                continue
            games = row["games"] or 0
            wins = row["wins"] or 0
            vg = row["village_games"] or 0
            vw = row["village_wins"] or 0
            eg = row["evil_games"] or 0
            ew = row["evil_wins"] or 0
            rg = row["rk_games"] or 0
            rw = row["rk_wins"] or 0
            ng = row["neutral_games"] or 0
            nw = row["neutral_wins"] or 0
            tm = row["total_mvps"] or 0
            vm = row["village_mvps"] or 0
            em = row["evil_mvps"] or 0
            rm = row["rk_mvps"] or 0
            nm = row["neutral_mvps"] or 0
            stats.append({
                "player_id": pid,
                "player_name": row["player_name"] or f"User-{pid}",
                "games": games,
                "wins": wins,
                "winrate": (wins / games * 100) if games > 0 else 0.0,
                "village_games": vg, "village_wins": vw,
                "village_wr": (vw / vg * 100) if vg > 0 else 0.0,
                "evil_games": eg, "evil_wins": ew,
                "evil_wr": (ew / eg * 100) if eg > 0 else 0.0,
                "rk_games": rg, "rk_wins": rw,
                "rk_wr": (rw / rg * 100) if rg > 0 else 0.0,
                "neutral_games": ng, "neutral_wins": nw,
                "neutral_wr": (nw / ng * 100) if ng > 0 else 0.0,
                "solo_wins": solo_map.get(pid, 0),
                "total_mvps": tm,
                "village_mvps": vm,
                "evil_mvps": em,
                "rk_mvps": rm,
                "neutral_mvps": nm,
                "ws_max": streak_map.get(pid, {}).get("ws_max", 0),
                "ws_freq": streak_map.get(pid, {}).get("ws_freq", 0),
                "ls_max": streak_map.get(pid, {}).get("ls_max", 0),
                "ls_freq": streak_map.get(pid, {}).get("ls_freq", 0),
            })

        return stats

    def get_winrate_stats(self) -> dict:
        """Return win/loss totals and winrate per team."""
        with self._connect() as conn:
            cursor = conn.cursor()
            stats = {}
            for team_id, team_name in TEAMS.items():
                if team_id == 5:
                    continue
                cursor.execute("""
                    SELECT COUNT(*) AS total,
                        SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins
                    FROM roles
                    WHERE team = ? AND count = 1
                """, (team_id,))
                row = cursor.fetchone()
                total = row["total"]
                wins = row["wins"] or 0
                stats[team_name] = {
                    "total": total,
                    "wins": wins,
                    "winrate": (wins / total * 100) if total else 0.0,
                }
        return stats

    def get_first_game_played(self, player_id: int):
        """Return (game_number, game_name) of the first counted game for a player."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT game_number, game_name FROM roles
                WHERE player_id = ? AND count = 1 AND team != 5
                ORDER BY game_number ASC LIMIT 1
            """, (player_id,))
            row = cursor.fetchone()
            return (row["game_number"], row["game_name"]) if row else (None, None)

    def get_games_played(self, player_id: int):
        """Return an ordered list of game numbers the player appeared in."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT game_number FROM roles
                WHERE player_id = ? AND count = 1 AND team != 5
                ORDER BY game_number ASC
            """, (player_id,))
            return [row[0] for row in cursor.fetchall()]

    def get_player_game_history(self, player_id: int):
        """Return full ordered game history for a player."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT game_number, game_name, role_id, role_name, team, win, mvp
                FROM roles
                WHERE player_id = ? AND count = 1 AND team != 5
                ORDER BY game_number ASC
            """, (player_id,))
            return [
                {
                    "game_number": row["game_number"],
                    "game_name": row["game_name"],
                    "role_id": row["role_id"],
                    "role_name": row["role_name"],
                    "team": row["team"],
                    "result": "🏆 Win" if row["win"] == 1 else "❌ Loss",
                    "mvp": row["mvp"] == 1,
                }
                for row in cursor.fetchall()
            ]

    # -------------------------------------------------------------------------
    # Allies / nemeses (shared helpers)
    # -------------------------------------------------------------------------

    def _get_teammate_rows(self, player_id: int):
        """Return same-team co-occurrence rows for ally computation."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                WITH shared_games AS (
                    SELECT
                        r1.game_number AS game_number,
                        r2.player_id AS ally_player_id,
                        MAX(CASE WHEN r1.win = 1 AND r2.win = 1 THEN 1 ELSE 0 END) AS win_together
                    FROM roles r1
                    JOIN roles r2 ON r1.game_number = r2.game_number
                    WHERE r1.player_id = ?
                      AND r2.player_id IS NOT NULL
                      AND r2.player_id != r1.player_id
                      AND r1.team = r2.team
                      AND r1.count = 1 AND r2.count = 1
                      AND r1.team != 5 AND r2.team != 5
                    GROUP BY r1.game_number, r2.player_id
                )
                SELECT
                    ally_player_id AS player_id,
                    SUM(win_together) AS wins_together,
                    COUNT(*) AS games_together
                FROM shared_games
                GROUP BY ally_player_id
            """, (player_id,))
            agg_rows = cursor.fetchall()

            cursor.execute("""
                SELECT player_id, player_name
                FROM roles
                WHERE player_id IS NOT NULL
                  AND player_name IS NOT NULL
                  AND player_name != ''
                ORDER BY player_id, game_number DESC, role_id DESC
            """)
            latest_names: dict[int, str] = {}
            for row in cursor.fetchall():
                pid = row["player_id"]
                if pid not in latest_names:
                    latest_names[pid] = row["player_name"]

            return [
                (row["player_id"], latest_names.get(row["player_id"], f"Player {row['player_id']}"), row["wins_together"], row["games_together"])
                for row in agg_rows
            ]

    def _get_opponent_rows(self, player_id: int):
        """Return opposing-team co-occurrence rows for nemesis computation."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    r2.player_id,
                    r2.player_name,
                    SUM(CASE WHEN r2.win = 1 AND r1.win = 0 THEN 1 ELSE 0 END) AS losses_to,
                    COUNT(*) AS games_together
                FROM roles r1
                JOIN roles r2 ON r1.game_number = r2.game_number
                WHERE r1.player_id = ?
                  AND r2.player_id != r1.player_id
                  AND r1.team != r2.team
                  AND r1.count = 1 AND r2.count = 1
                  AND r1.team != 5 AND r2.team != 5
                GROUP BY r2.player_id, r2.player_name
            """, (player_id,))
            return cursor.fetchall()

    def _get_player_game_count(self, player_id: int) -> int:
        """Return total counted non-bonus games for a player."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT game_number) FROM roles
                WHERE player_id = ? AND count = 1 AND team != 5
            """, (player_id,))
            return cursor.fetchone()[0] or 0

    @staticmethod
    def _rank_rows(rows, threshold: int, top_n: int, key_fn, reverse=True):
        """Sort and fill rows into strong / backup / tiny tiers."""
        MIN_SAMPLE = 5
        strong, backup, tiny = [], [], []
        for pid, pname, primary_stat, games in rows:
            if games <= 0:
                continue
            rate = primary_stat / games
            entry = (pid, pname, primary_stat, games, rate)
            if primary_stat >= threshold:
                strong.append(entry)
            elif games >= MIN_SAMPLE:
                backup.append(entry)
            else:
                tiny.append(entry)

        for bucket in (strong, backup, tiny):
            bucket.sort(key=key_fn, reverse=reverse)

        result = strong[:]
        if len(result) < top_n:
            result.extend(backup[: top_n - len(result)])
        if len(result) < top_n:
            result.extend(tiny[: top_n - len(result)])
        return result[:top_n]

    def get_top_allies2(self, player_id: int):
        total = self._get_player_game_count(player_id)
        if total == 0:
            return []
        threshold = math.ceil(total * 0.15)
        rows = self._get_teammate_rows(player_id)
        return self._rank_rows(rows, threshold, 5, key_fn=lambda x: (x[4], x[3]), reverse=True)

    def get_worst_allies2(self, player_id: int):
        """Return the 5 worst same-team allies, sorted ascending by winrate (lowest first).

        Unlike get_top_allies2, the tuple returned is still (pid, pname, wins, games, wr)
        so callers can display winrate consistently. The "strong" tier threshold is based
        on losses (games - wins), not wins — many losses together = definitively a bad ally.
        """
        total = self._get_player_game_count(player_id)
        if total == 0:
            return []
        threshold = math.ceil(total * 0.15)
        MIN_SAMPLE = 5
        TOP_N = 5

        strong, backup, tiny = [], [], []
        for pid, pname, wins, games in self._get_teammate_rows(player_id):
            if games <= 0:
                continue
            wr = wins / games
            entry = (pid, pname, wins, games, wr)
            # Threshold on losses, not wins — many losses = confirmed bad ally
            if (games - wins) >= threshold:
                strong.append(entry)
            elif games >= MIN_SAMPLE:
                backup.append(entry)
            else:
                tiny.append(entry)

        # Ascending by WR (lowest WR = worst ally first), then descending by games for ties
        for bucket in (strong, backup, tiny):
            bucket.sort(key=lambda x: (x[4], -x[3]))

        result = strong[:]
        if len(result) < TOP_N:
            result.extend(backup[: TOP_N - len(result)])
        if len(result) < TOP_N:
            result.extend(tiny[: TOP_N - len(result)])
        return result[:TOP_N]

    def get_top_nemeses2(self, player_id: int):
        total = self._get_player_game_count(player_id)
        if total == 0:
            return []
        threshold = math.ceil(total * 0.15)
        rows = self._get_opponent_rows(player_id)
        return self._rank_rows(rows, threshold, 5, key_fn=lambda x: (x[4], x[3]), reverse=True)

    def get_all_allies2(self, player_id: int):
        total = self._get_player_game_count(player_id)
        if total == 0:
            return []
        threshold = math.ceil(total * 0.15)
        rows = self._get_teammate_rows(player_id)
        return self._rank_rows(rows, threshold, len(rows), key_fn=lambda x: (x[4], x[3]), reverse=True)

    def get_all_worst_allies2(self, player_id: int):
        total = self._get_player_game_count(player_id)
        if total == 0:
            return []
        threshold = math.ceil(total * 0.15)
        MIN_SAMPLE = 5

        strong, backup, tiny = [], [], []
        for pid, pname, wins, games in self._get_teammate_rows(player_id):
            if games <= 0:
                continue
            wr = wins / games
            entry = (pid, pname, wins, games, wr)
            if (games - wins) >= threshold:
                strong.append(entry)
            elif games >= MIN_SAMPLE:
                backup.append(entry)
            else:
                tiny.append(entry)

        for bucket in (strong, backup, tiny):
            bucket.sort(key=lambda x: (x[4], -x[3]))

        result = strong[:]
        result.extend(backup)
        result.extend(tiny)
        return result

    def get_all_nemeses2(self, player_id: int):
        total = self._get_player_game_count(player_id)
        if total == 0:
            return []
        threshold = math.ceil(total * 0.15)
        rows = self._get_opponent_rows(player_id)
        return self._rank_rows(rows, threshold, len(rows), key_fn=lambda x: (x[4], x[3]), reverse=True)

    # -------------------------------------------------------------------------
    # Account management
    # -------------------------------------------------------------------------

    def find_accounts_by_name(self, name: str):
        """Return [(id, name)] for every account matching the given name."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT player_id, player_name FROM roles
                WHERE LOWER(player_name) = LOWER(?) AND player_id IS NOT NULL
            """, (name,))
            players = cursor.fetchall()
            cursor.execute("""
                SELECT DISTINCT sponsor_id, sponsor_name FROM roles
                WHERE LOWER(sponsor_name) = LOWER(?) AND sponsor_id IS NOT NULL
            """, (name,))
            sponsors = cursor.fetchall()

        accounts: dict = {}
        for row in players + sponsors:
            accounts[row[0]] = row[1]
        return list(accounts.items())

    def merge_accounts(self, source_id: int, target_id: int, target_name: str):
        """Move all stats from source account to target account."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE roles SET player_id = ?, player_name = ? WHERE player_id = ?",
                (target_id, target_name, source_id),
            )
            cursor.execute(
                "UPDATE roles SET sponsor_id = ?, sponsor_name = ? WHERE sponsor_id = ?",
                (target_id, target_name, source_id),
            )
            conn.commit()

    def get_account_stat_counts(self, discord_id: int):
        """Return (player_rows, sponsor_rows) for a Discord ID."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM roles WHERE player_id = ?", (discord_id,))
            player_rows = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM roles WHERE sponsor_id = ?", (discord_id,))
            sponsor_rows = cursor.fetchone()[0]
        return player_rows, sponsor_rows

    def sync_account_name(
        self,
        discord_id: int,
        new_name: str,
        *,
        include_player: bool = True,
        include_sponsor: bool = True,
    ) -> Tuple[int, int]:
        """Update stored player/sponsor names for a given Discord ID.
        Returns (updated_player_rows, updated_sponsor_rows)."""
        with self._connect() as conn:
            cursor = conn.cursor()
            updated_player = updated_sponsor = 0
            if include_player:
                cursor.execute(
                    "UPDATE roles SET player_name = ? WHERE player_id = ?",
                    (new_name, discord_id),
                )
                updated_player = cursor.rowcount
            if include_sponsor:
                cursor.execute(
                    "UPDATE roles SET sponsor_name = ? WHERE sponsor_id = ?",
                    (new_name, discord_id),
                )
                updated_sponsor = cursor.rowcount
            conn.commit()
        return updated_player, updated_sponsor

    def migrate_account_by_id(self, old_id: int, new_id: int, new_name: str):
        """Re-key all rows from old_id to new_id."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE roles SET player_id = ?, player_name = ? WHERE player_id = ?",
                (new_id, new_name, old_id),
            )
            cursor.execute(
                "UPDATE roles SET sponsor_id = ?, sponsor_name = ? WHERE sponsor_id = ?",
                (new_id, new_name, old_id),
            )
            conn.commit()

    def assign_player_id(self, player_name: str, new_id: int):
        """Set player_id for all rows matching player_name where it is currently unset."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE roles SET player_id = ?
                WHERE LOWER(player_name) = LOWER(?) AND (player_id IS NULL OR player_id = 0)
            """, (new_id, player_name))
            conn.commit()

    def get_players_missing_ids(self) -> List[str]:
        """Return distinct player names with no Discord ID assigned anywhere in the DB."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT player_name FROM roles
                WHERE player_name IS NOT NULL AND (player_id IS NULL OR player_id = 0)
                AND LOWER(player_name) NOT IN (
                    SELECT LOWER(player_name) FROM roles
                    WHERE player_name IS NOT NULL AND player_id IS NOT NULL AND player_id != 0
                )
            """)
            return [row[0] for row in cursor.fetchall()]

    def get_all_account_ids(self) -> List[int]:
        """Return all distinct player_id and sponsor_id values in the database."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT player_id FROM roles WHERE player_id IS NOT NULL
                UNION
                SELECT DISTINCT sponsor_id FROM roles WHERE sponsor_id IS NOT NULL
            """)
            return [row[0] for row in cursor.fetchall() if row[0] is not None]


# ============================================================================
# UI VIEWS
# ============================================================================

class GameSelectView(discord.ui.View):
    """View for selecting a game."""
    def __init__(self, games: List[Tuple[int, str]], db, page: int = 0):
        super().__init__(timeout=300)
        self.games = games
        self.db = db
        self.page = page
        self.max_page = math.ceil(len(games) / 10) - 1

        if self.max_page > 0:
            self.prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.primary, disabled=True)
            self.prev_btn.callback = self.prev_page
            self.add_item(self.prev_btn)

            self.next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary)
            self.next_btn.callback = self.next_page
            self.add_item(self.next_btn)

    def get_embed(self) -> discord.Embed:
        start_idx = self.page * 10
        end_idx = min(start_idx + 10, len(self.games))
        page_games = self.games[start_idx:end_idx]

        embed = discord.Embed(
            title="📚 Game Library - Select a Game",
            description="Use the input field below to enter the game number you want to view.",
            color=EMBED_COLOR,
        )

        games_text = ""
        for game_num, game_name in page_games:
            winners = self.db.get_winning_teams(game_num)
            winner_str = f" | 🏆 {', '.join(winners)}" if winners else ""
            games_text += f"**{game_num}** | {game_name.replace('-', ' ').title()}{winner_str}\n"

        embed.add_field(name="Available Games", value=games_text, inline=False)

        if self.max_page > 0:
            embed.set_footer(text=f"{EMBED_FOOTER_TEXT} | Page {self.page + 1}/{self.max_page + 1}", icon_url=EMBED_FOOTER_ICON)
        else:
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        return embed

    async def prev_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self.update_view(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        await self.update_view(interaction)

    async def update_view(self, interaction: discord.Interaction):
        if self.max_page > 0:
            self.prev_btn.disabled = (self.page == 0)
            self.next_btn.disabled = (self.page == self.max_page)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢 Enter Game Number", style=discord.ButtonStyle.success, row=1)
    async def open_game_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GameNumberModal(self.games, self.db)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔍 Search", style=discord.ButtonStyle.primary, row=1)
    async def open_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = InteractiveSearchView(self.db)
        embed = discord.Embed(
            title="🔍 Search Library",
            description=(
                "Search by:\n"
                "• Role name (fuzzy)\n"
                "• Game number\n"
                "• Game number + role name\n\n"
                "Examples:\n"
                "`.lib search doctor`\n"
                "`.lib search 12`\n"
                "`.lib search 12 doctor`"
            ),
            color=EMBED_COLOR,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class GameNumberModal(discord.ui.Modal, title="Enter Game Number"):
    """Modal for entering game number."""
    def __init__(self, games: List[Tuple[int, str]], db):
        super().__init__()
        self.games = games
        self.db = db

    game_number = discord.ui.TextInput(
        label="Game Number",
        placeholder="Enter the game number...",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            game_num = int(self.game_number.value)
            game_data = next((g for g in self.games if g[0] == game_num), None)
            if game_data:
                view = TeamSelectView(game_num, game_data[1], self.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                await interaction.response.send_message("❌ Game not found! Please enter a valid game number.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class TeamSelectView(discord.ui.View):
    """View for selecting team and browsing roles."""
    def __init__(self, game_number: int, game_name: str, db, selected_team: int = 1):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.selected_team = selected_team
        self.db = db

    def get_embed(self) -> discord.Embed:
        roles_basic = self.db.get_roles_by_team(self.game_number, self.selected_team)

        embed = discord.Embed(
            title=f"🎮 {self.game_number}-{self.game_name.replace('-', ' ').title()}",
            description=f"**Team: {TEAMS[self.selected_team]}**\n\nSelect a team from the dropdown or enter a role ID below.",
            color=EMBED_COLOR,
        )

        if roles_basic:
            lines = []
            for role_id, role_name, player_name, count_flag in roles_basic:
                role_details = self.db.get_role_details(self.game_number, role_id)
                if role_details and role_details.get("count", 1):
                    is_mvp = bool(role_details.get("mvp"))
                    if role_details["win"]:
                        win_emoji = "🏆⭐" if is_mvp else "🏆"
                    else:
                        win_emoji = "❌⭐" if is_mvp else "❌"
                    emoji_part = f" {win_emoji}"
                else:
                    emoji_part = ""
                player_str = f" - {player_name}{emoji_part}" if player_name else ""
                lines.append(f"**{role_id}** - {role_name}{player_str}\n")

            add_fields_paginated(embed, f"Roles ({len(roles_basic)})", lines)
        else:
            embed.add_field(name="Roles", value="*No roles found for this team.*", inline=False)

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        return embed

    async def rebuild_view(self, interaction: discord.Interaction):
        new_view = TeamSelectView(self.game_number, self.game_name, self.db, self.selected_team)
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)

    @discord.ui.select(
        placeholder="Select a team...",
        options=[
            discord.SelectOption(label="Village", value="1", emoji="🏘️"),
            discord.SelectOption(label="Evil", value="2", emoji="😈"),
            discord.SelectOption(label="Random Killer", value="3", emoji="🔪"),
            discord.SelectOption(label="Neutral", value="4", emoji="⚖️"),
            discord.SelectOption(label="Bonus/Extra", value="5", emoji="⭐"),
        ],
        row=0,
    )
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_team = int(select.values[0])
        new_view = TeamSelectView(self.game_number, self.game_name, self.db, self.selected_team)
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)

    @discord.ui.button(label="🔢 Enter Role ID", style=discord.ButtonStyle.primary, row=2)
    async def enter_role_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RoleIDModal(self.game_number, self.game_name, self.db))

    @discord.ui.button(label="👥 Show Players", style=discord.ButtonStyle.success, row=2)
    async def show_players(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = GamePlayersView(self.game_number, self.game_name, self.db, self.selected_team)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="↩️ Back to Games", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        games = self.db.get_all_games()
        view = GameSelectView(games, self.db)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class GamePlayersView(discord.ui.View):
    """View for displaying game players."""
    def __init__(self, game_number: int, game_name: str, db, previous_team: int = 1, selected_filter: str = "all"):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.db = db
        self.previous_team = previous_team
        self.selected_filter = selected_filter
        self.page = 0
        self.page_size = 10
        self._rebuild_lists()

    def _rebuild_lists(self):
        winners, losers = [], []
        for player_name, sponsor_name, team, win in self.db.get_game_players(self.game_number):
            team_name = TEAMS.get(team, "Unknown")
            base = player_name or "Unknown"
            if sponsor_name:
                base = f"{base} + {sponsor_name}"
            display = f"{base} - {team_name}"
            (winners if win == 1 else losers).append(display)
        self._winners = winners
        self._losers = losers

    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"👥 {self.game_name.replace('-', ' ').title()} - Players",
            color=EMBED_COLOR,
        )

        if self.selected_filter == "all":
            start = self.page * self.page_size
            end = start + self.page_size
            winners_lines = [f"{w}\n" for w in self._winners[start:end]] or ["*No winners*"]
            losers_lines = [f"{l}\n" for l in self._losers[start:end]] or ["*No losers*"]
            add_fields_paginated(embed, "🏆 Winners", winners_lines)
            add_fields_paginated(embed, "❌ Losers", losers_lines)
        else:
            team_id = int(self.selected_filter)
            team_name = TEAMS.get(team_id, "Unknown")
            team_lines = []
            for player_name, sponsor_name, team, win in self.db.get_game_players(self.game_number):
                if team == team_id:
                    win_emoji = "🏆" if win == 1 else "❌"
                    base = player_name or "Unknown"
                    if sponsor_name:
                        base = f"{base} + {sponsor_name}"
                    team_lines.append(f"{win_emoji} {base}\n")
            add_fields_paginated(embed, f"{team_name} Team", team_lines or ["*No players on this team*"])

        if self.selected_filter == "all":
            max_items = max(len(self._winners), len(self._losers))
            max_page = max(0, (max_items - 1) // self.page_size)
            footer_extra = f" | Page {self.page + 1}/{max_page + 1}" if max_items > self.page_size else ""
        else:
            footer_extra = ""
        embed.set_footer(text=f"{EMBED_FOOTER_TEXT}{footer_extra}", icon_url=EMBED_FOOTER_ICON)
        return embed

    @discord.ui.select(
        placeholder="Filter by...",
        options=[
            discord.SelectOption(label="All Players (Winners/Losers)", value="all", emoji="👥"),
            discord.SelectOption(label="Village Team", value="1", emoji="🏘️"),
            discord.SelectOption(label="Evil Team", value="2", emoji="😈"),
            discord.SelectOption(label="Random Killer Team", value="3", emoji="🔪"),
            discord.SelectOption(label="Neutral Team", value="4", emoji="⚖️"),
            discord.SelectOption(label="Bonus/Extra Team", value="5", emoji="⭐"),
        ],
        row=0,
    )
    async def filter_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_filter = select.values[0]
        self.page = 0
        if self.selected_filter == "all":
            self._rebuild_lists()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="◀ Prev Page", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_filter != "all":
            await interaction.response.send_message("Pagination is only available when viewing all players.", ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next Page ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_filter != "all":
            await interaction.response.send_message("Pagination is only available when viewing all players.", ephemeral=True)
            return
        max_items = max(len(self._winners), len(self._losers))
        max_page = max(0, (max_items - 1) // self.page_size)
        if self.page < max_page:
            self.page += 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="↩️ Back to Roles", style=discord.ButtonStyle.secondary, row=1)
    async def back_to_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TeamSelectView(self.game_number, self.game_name, self.db, selected_team=self.previous_team)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class RoleIDModal(discord.ui.Modal, title="Enter Role ID"):
    """Modal for entering role ID."""
    def __init__(self, game_number: int, game_name: str, db):
        super().__init__()
        self.game_number = game_number
        self.game_name = game_name
        self.db = db

    role_id = discord.ui.TextInput(label="Role ID", placeholder="Enter the role ID...", required=True, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
            role_data = self.db.get_role_details(self.game_number, role_id)
            if role_data:
                roles = self.db.get_roles_by_team(self.game_number, role_data["team"])
                index = next(i for i, r in enumerate(roles) if r[0] == role_id)
                view = RoleDescriptionView(self.game_number, self.game_name, roles, index, self.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                await interaction.response.send_message("❌ Role not found! Please enter a valid role ID.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class RoleDescriptionView(discord.ui.View):
    """View for displaying role descriptions."""
    def __init__(self, game_number: int, game_name: str, roles: list, current_index: int, db):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.roles = roles
        self.current_index = current_index
        self.db = db
        self.current_desc = 1
        self._update_available_descs()

    def _update_available_descs(self):
        role_data = self.get_role_data()
        self.available_descs = [
            i for i in range(1, 5)
            if role_data.get(f"description{i}") and str(role_data[f"description{i}"]).strip()
        ]
        if not self.available_descs:
            self.available_descs = [1]
        if self.current_desc not in self.available_descs:
            self.current_desc = self.available_descs[0]

    def get_role_data(self):
        role_id = self.roles[self.current_index][0]
        return self.db.get_role_details(self.game_number, role_id)

    def get_embed(self) -> discord.Embed:
        role = self.get_role_data()
        description = role.get(f"description{self.current_desc}") or "*No description available.*"
        if not str(description).strip():
            description = "*No description available.*"

        embed = discord.Embed(title=f"📜 {role['role_name']}", description=description, color=EMBED_COLOR)

        info_text = f"**Game:** {self.game_number}-{self.game_name.replace('-', ' ').title()}\n"
        info_text += f"**Role ID:** {role['role_id']}\n"
        info_text += f"**Team:** {TEAMS[role['team']]}\n"
        if role.get("player_name"):
            info_text += f"**Player:** {role['player_name']}\n"
        if role.get("sponsor_name"):
            info_text += f"**Sponsor:** {role['sponsor_name']}\n"
        info_text += f"**Result:** {'✅ Winner' if role['win'] else '❌ Loss'}\n"
        info_text += f"**MVP:** {'⭐ Yes' if role.get('mvp') else '—'}"

        embed.add_field(name="Role Information", value=info_text, inline=False)

        max_desc = max(self.available_descs)
        embed.set_footer(
            text=f"{EMBED_FOOTER_TEXT} | Description {self.current_desc}/{max_desc} | Role {self.current_index + 1}/{len(self.roles)}",
            icon_url=EMBED_FOOTER_ICON,
        )
        return embed

    @discord.ui.button(label="◀ Desc", style=discord.ButtonStyle.primary, row=0)
    async def prev_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        idx = self.available_descs.index(self.current_desc)
        if idx > 0:
            self.current_desc = self.available_descs[idx - 1]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Desc ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        idx = self.available_descs.index(self.current_desc)
        if idx < len(self.available_descs) - 1:
            self.current_desc = self.available_descs[idx + 1]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="◀◀ Role", style=discord.ButtonStyle.secondary, row=1)
    async def prev_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0:
            self.current_index -= 1
            self._update_available_descs()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Role ▶▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.roles) - 1:
            self.current_index += 1
            self._update_available_descs()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="↩️ Back to Roles", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_role = self.get_role_data()
        view = TeamSelectView(self.game_number, self.game_name, self.db, selected_team=current_role["team"])
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class LeaderboardView(discord.ui.View):
    """Leaderboard view."""
    def __init__(self, stats, min_games: int = 10, sort_mode: str = "winrate", page: int = 0):
        super().__init__(timeout=300)
        self.raw_stats = stats
        self.min_games = min_games
        self.sort_mode = sort_mode
        self.page = page
        self.page_size = 10

    def get_sorted_players(self) -> List[dict]:
        # Use min_games=2 if sorting by streaks as requested, otherwise use set min_games
        min_g = 2 if self.sort_mode in ["win_streak", "loss_streak"] else self.min_games
        players = [p for p in self.raw_stats if p["games"] >= min_g]
        key_map = {
            "games":       lambda p: (-p["games"], -p["wins"], -p["winrate"]),
            "winrate":     lambda p: (-p["winrate"], -p["wins"], -p["games"]),
            "win_streak":  lambda p: (-p.get("ws_max", 0), -p.get("ws_freq", 0), -p["winrate"]),
            "loss_streak": lambda p: (-p.get("ls_max", 0), -p.get("ls_freq", 0), p["winrate"]),
            "village_wr":  lambda p: (-p.get("village_wr", 0), -p.get("village_wins", 0), -p.get("village_games", 0)),
            "evil_wr":     lambda p: (-p.get("evil_wr", 0), -p.get("evil_wins", 0), -p.get("evil_games", 0)),
            "rk_wr":       lambda p: (-p.get("rk_wr", 0), -p.get("rk_wins", 0), -p.get("rk_games", 0)),
            "neutral_wr":  lambda p: (-p.get("neutral_wr", 0), -p.get("neutral_wins", 0), -p.get("neutral_games", 0)),
            "solo_wins":   lambda p: (-p.get("solo_wins", 0), -p["wins"], -p["games"]),
            "name":        lambda p: p["player_name"].lower(),
            # MVP sort modes
            "mvp_total":   lambda p: (-p.get("total_mvps", 0), -p["wins"], -p["games"]),
            "mvp_village": lambda p: (-p.get("village_mvps", 0), -p.get("village_wins", 0), -p.get("village_games", 0)),
            "mvp_evil":    lambda p: (-p.get("evil_mvps", 0), -p.get("evil_wins", 0), -p.get("evil_games", 0)),
            "mvp_rk":      lambda p: (-p.get("rk_mvps", 0), -p.get("rk_wins", 0), -p.get("rk_games", 0)),
            "mvp_neutral": lambda p: (-p.get("neutral_mvps", 0), -p.get("neutral_wins", 0), -p.get("neutral_games", 0)),
            # Win-count sort modes
            "village_wins": lambda p: (-p.get("village_wins", 0), -p.get("village_wr", 0), -p.get("village_games", 0)),
            "evil_wins":    lambda p: (-p.get("evil_wins", 0), -p.get("evil_wr", 0), -p.get("evil_games", 0)),
            "other_wins":   lambda p: (-(p.get("rk_wins", 0) + p.get("neutral_wins", 0)), -p["wins"], -p["games"]),
        }
        key = key_map.get(self.sort_mode, key_map["winrate"])
        players.sort(key=key)
        return players

    def get_embed(self) -> discord.Embed:
        players = self.get_sorted_players()
        total = len(players)

        embed = discord.Embed(title=f"🏆 Leaderboard — {self.min_games}+ Games", color=EMBED_COLOR)

        if total == 0:
            embed.description = "No players match this filter."
            return embed

        max_page = max(0, (total - 1) // self.page_size)
        self.page = min(self.page, max_page)

        start = self.page * self.page_size
        page_players = players[start:start + self.page_size]

        sort_labels = {
            "winrate": "Winrate", "name": "Alphabetical", "games": "Games Played",
            "win_streak": "Win Streak", "loss_streak": "Loss Streak",
            "village_wr": "Village Winrate", "evil_wr": "Evil Winrate",
            "rk_wr": "RK Winrate", "neutral_wr": "Neutral Winrate", "solo_wins": "Solo Wins",
            "mvp_total": "Total MVPs", "mvp_village": "Village MVPs",
            "mvp_evil": "Evil MVPs", "mvp_rk": "RK MVPs", "mvp_neutral": "Neutral MVPs",
            "village_wins": "Village Wins", "evil_wins": "Evil Wins", "other_wins": "RK+Neutral Wins",
        }

        desc_lines = []
        for idx, p in enumerate(page_players, start=start + 1):
            line = f"**#{idx} — {p['player_name']}**\n"
            line += f"Games: {p['games']} | Wins: {p['wins']} | WR: {p['winrate']:.1f}%\n"
            if self.sort_mode == "village_wr":
                line += f"Village WR: {p.get('village_wr', 0):.1f}% ({p.get('village_wins', 0)}W / {p.get('village_games', 0)}G)\n"
            elif self.sort_mode == "evil_wr":
                line += f"Evil WR: {p.get('evil_wr', 0):.1f}% ({p.get('evil_wins', 0)}W / {p.get('evil_games', 0)}G)\n"
            elif self.sort_mode == "rk_wr":
                line += f"RK WR: {p.get('rk_wr', 0):.1f}% ({p.get('rk_wins', 0)}W / {p.get('rk_games', 0)}G)\n"
            elif self.sort_mode == "neutral_wr":
                line += f"Neutral WR: {p.get('neutral_wr', 0):.1f}% ({p.get('neutral_wins', 0)}W / {p.get('neutral_games', 0)}G)\n"
            elif self.sort_mode == "win_streak":
                line += f"Longest WS: {p.get('ws_max', 0)} ({p.get('ws_freq', 0)}x)\n"
            elif self.sort_mode == "loss_streak":
                line += f"Longest LS: {p.get('ls_max', 0)} ({p.get('ls_freq', 0)}x)\n"
            elif self.sort_mode == "solo_wins":
                line += f"Solo Wins: {p.get('solo_wins', 0)}\n"
            elif self.sort_mode == "mvp_total":
                line += f"⭐ Total MVPs: {p.get('total_mvps', 0)}\n"
            elif self.sort_mode == "mvp_village":
                line += f"⭐ Village MVPs: {p.get('village_mvps', 0)} (Village: {p.get('village_wins', 0)}W / {p.get('village_games', 0)}G)\n"
            elif self.sort_mode == "mvp_evil":
                line += f"⭐ Evil MVPs: {p.get('evil_mvps', 0)} (Evil: {p.get('evil_wins', 0)}W / {p.get('evil_games', 0)}G)\n"
            elif self.sort_mode == "mvp_rk":
                line += f"⭐ RK MVPs: {p.get('rk_mvps', 0)} (RK: {p.get('rk_wins', 0)}W / {p.get('rk_games', 0)}G)\n"
            elif self.sort_mode == "mvp_neutral":
                line += f"⭐ Neutral MVPs: {p.get('neutral_mvps', 0)} (Neutral: {p.get('neutral_wins', 0)}W / {p.get('neutral_games', 0)}G)\n"
            elif self.sort_mode == "village_wins":
                line += f"Village Wins: {p.get('village_wins', 0)} / {p.get('village_games', 0)}G ({p.get('village_wr', 0):.1f}%)\n"
            elif self.sort_mode == "evil_wins":
                line += f"Evil Wins: {p.get('evil_wins', 0)} / {p.get('evil_games', 0)}G ({p.get('evil_wr', 0):.1f}%)\n"
            elif self.sort_mode == "other_wins":
                other_w = p.get("rk_wins", 0) + p.get("neutral_wins", 0)
                other_g = p.get("rk_games", 0) + p.get("neutral_games", 0)
                line += f"RK+Neutral Wins: {other_w} / {other_g}G\n"
            desc_lines.append(line)

        embed.description = "\n".join(desc_lines)
        min_g = 2 if self.sort_mode in ["win_streak", "loss_streak"] else self.min_games
        embed.set_footer(
            text=f"{EMBED_FOOTER_TEXT} | {min_g}+ games | Sorted by {sort_labels.get(self.sort_mode, 'Winrate')} | Page {self.page + 1}/{max_page + 1}",
            icon_url=EMBED_FOOTER_ICON,
        )
        return embed

    @discord.ui.select(
        placeholder="Sort by...",
        options=[
            discord.SelectOption(label="Winrate", value="winrate"),
            discord.SelectOption(label="Alphabetical (A–Z)", value="name"),
            discord.SelectOption(label="Games Played", value="games"),
            discord.SelectOption(label="Win Streak", value="win_streak"),
            discord.SelectOption(label="Loss Streak", value="loss_streak"),
            discord.SelectOption(label="Village Winrate", value="village_wr"),
            discord.SelectOption(label="Evil Winrate", value="evil_wr"),
            discord.SelectOption(label="RK Winrate", value="rk_wr"),
            discord.SelectOption(label="Neutral Winrate", value="neutral_wr"),
            discord.SelectOption(label="Solo Wins", value="solo_wins"),
            discord.SelectOption(label="⭐ Total MVPs", value="mvp_total"),
            discord.SelectOption(label="⭐ Village MVPs", value="mvp_village"),
            discord.SelectOption(label="⭐ Evil MVPs", value="mvp_evil"),
            discord.SelectOption(label="⭐ RK MVPs", value="mvp_rk"),
            discord.SelectOption(label="⭐ Neutral MVPs", value="mvp_neutral"),
            discord.SelectOption(label="Village Wins (count)", value="village_wins"),
            discord.SelectOption(label="Evil Wins (count)", value="evil_wins"),
            discord.SelectOption(label="RK + Neutral Wins", value="other_wins"),
        ],
        row=0,
    )
    async def sort_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.sort_mode = select.values[0]
        self.page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢 Set Min Games", style=discord.ButtonStyle.primary, row=1)
    async def set_min_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MinGamesModal(self))

    @discord.ui.button(label="◀ Prev Page", style=discord.ButtonStyle.secondary, row=2)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next Page ▶", style=discord.ButtonStyle.secondary, row=2)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        max_page = max(0, (len(self.get_sorted_players()) - 1) // self.page_size)
        if self.page < max_page:
            self.page += 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class GameHistoryView(discord.ui.View):
    def __init__(self, history, player_name, page=0):
        super().__init__(timeout=300)
        self.history = history
        self.player_name = player_name
        self.page = page
        self.page_size = 10

    def get_embed(self):
        total_pages = max(1, (len(self.history) - 1) // self.page_size + 1)
        start = self.page * self.page_size
        items = self.history[start:start + self.page_size]

        embed = discord.Embed(title=f"📜 Game History — {self.player_name}", color=EMBED_COLOR)

        if not items:
            embed.description = "*No games found.*"
            return embed

        desc = ""
        for h in items:
            mvp_line = "• **MVP:** ⭐ Yes\n" if h.get("mvp") else ""
            desc += (
                f"**Game {h['game_number']} — {h['game_name'].replace('-', ' ').title()}**\n"
                f"• Role: {h['role_name']} (ID: {h['role_id']})\n"
                f"• Team: {TEAMS.get(h['team'], 'Unknown')}\n"
                f"• Result: {h['result']}\n"
                f"{mvp_line}\n"
            )

        embed.description = desc
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages}")
        return embed

    async def update(self, interaction):
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction, button):
        if self.page > 0:
            self.page -= 1
        await self.update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        max_page = (len(self.history) - 1) // self.page_size
        if self.page < max_page:
            self.page += 1
        await self.update(interaction)


class MinGamesModal(discord.ui.Modal, title="Set Minimum Games"):
    """Modal for minimum games filter."""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        self.min_games_input = discord.ui.TextInput(
            label="Minimum Games",
            placeholder="Enter minimum number of games (e.g., 10)...",
            required=True,
            max_length=3,
            default=str(parent_view.min_games),
        )
        self.add_item(self.min_games_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.min_games_input.value)
            if not 0 <= value <= 1000:
                await interaction.response.send_message("❌ Minimum games must be between 0 and 1000!", ephemeral=True)
                return
            self.parent_view.min_games = value
            self.parent_view.page = 0
            await interaction.response.edit_message(embed=self.parent_view.get_embed(), view=self.parent_view)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class InteractiveSearchView(discord.ui.View):
    """Interactive search view."""
    def __init__(self, db):
        super().__init__(timeout=300)
        self.db = db
        self.selected_team = None

    @discord.ui.select(
        placeholder="Select a team (optional)...",
        options=[
            discord.SelectOption(label="Village", value="1", emoji="🏘️"),
            discord.SelectOption(label="Evil", value="2", emoji="😈"),
            discord.SelectOption(label="Random Killer", value="3", emoji="🔪"),
            discord.SelectOption(label="Neutral", value="4", emoji="⚖️"),
            discord.SelectOption(label="Bonus/Extra", value="5", emoji="⭐"),
        ],
        row=0,
    )
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_team = int(select.values[0])
        await interaction.response.send_message(
            f"✅ Selected team: {TEAMS[self.selected_team]}\nNow enter a game number or role name using the buttons below.",
            ephemeral=True,
        )

    @discord.ui.button(label="🔢 Enter Game Number", style=discord.ButtonStyle.primary, row=1)
    async def enter_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchGameModal(self))

    @discord.ui.button(label="📝 Enter Role Name", style=discord.ButtonStyle.primary, row=1)
    async def enter_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchRoleModal(self))

    @discord.ui.button(label="👤 Enter Player Name", style=discord.ButtonStyle.primary, row=2)
    async def enter_player_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchPlayerNameModal(self))

    @discord.ui.button(label="🆔 Enter Player ID", style=discord.ButtonStyle.primary, row=2)
    async def enter_player_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchPlayerIDModal(self))

    @discord.ui.button(label="💼 Enter Sponsor Name", style=discord.ButtonStyle.primary, row=3)
    async def enter_sponsor_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchSponsorNameModal(self))

    @discord.ui.button(label="🔖 Enter Sponsor ID", style=discord.ButtonStyle.primary, row=3)
    async def enter_sponsor_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchSponsorIDModal(self))


class SearchGameModal(discord.ui.Modal, title="Enter Game Number"):
    """Modal for searching by game."""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    game_num = discord.ui.TextInput(label="Game Number", placeholder="Enter game number...", required=True, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            game_number = int(self.game_num.value)
            games = self.parent_view.db.get_all_games()
            game_data = next((g for g in games if g[0] == game_number), None)
            if game_data:
                selected_team = self.parent_view.selected_team or 1
                view = TeamSelectView(game_number, game_data[1], self.parent_view.db, selected_team=selected_team)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                await interaction.response.send_message("❌ Game not found!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class SearchRoleModal(discord.ui.Modal, title="Enter Role Name"):
    """Modal for searching by role name (fuzzy)."""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    role_name = discord.ui.TextInput(
        label="Role Name (partial or typo OK)",
        placeholder="e.g. doctor, doc, vig, kill...",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        query = self.role_name.value.strip()
        all_roles = self.parent_view.db.search_roles_fuzzy(query)

        def score(name):
            return SequenceMatcher(None, query.lower(), (name or "").lower()).ratio()

        all_roles.sort(
            key=lambda r: max(score(r["role_name"]), score(r["player_name"] or ""), score(r["sponsor_name"] or "")),
            reverse=True,
        )

        if self.parent_view.selected_team:
            all_roles = [r for r in all_roles if r["team"] == self.parent_view.selected_team]

        if not all_roles:
            await interaction.response.send_message(f"❌ No roles matching '{query}' found.", ephemeral=True)
            return

        if len(all_roles) == 1:
            role = all_roles[0]
            roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], roles, index, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
            return

        view = RoleSelectionView(all_roles, self.parent_view.db)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class SearchPlayerNameModal(discord.ui.Modal, title="Enter Player Name"):
    """Modal for searching by player name."""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    player_name = discord.ui.TextInput(label="Player Name", placeholder="Enter player name...", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        all_roles = self.parent_view.db.search_roles_by_player_name(self.player_name.value)
        filtered_roles = [r for r in all_roles if r["team"] == self.parent_view.selected_team] if self.parent_view.selected_team else all_roles

        if not filtered_roles:
            await interaction.response.send_message(f"❌ No roles found for player '{self.player_name.value}'!", ephemeral=True)
            return

        if len(filtered_roles) == 1:
            role = filtered_roles[0]
            roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], roles, index, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        else:
            view = RoleSelectionView(filtered_roles, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


class SearchPlayerIDModal(discord.ui.Modal, title="Enter Player ID"):
    """Modal for searching by player ID."""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    player_id = discord.ui.TextInput(label="Player ID", placeholder="Enter player ID...", required=True, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            pid = int(self.player_id.value)
            all_roles = self.parent_view.db.search_roles_by_player_id(pid)
            filtered_roles = [r for r in all_roles if r["team"] == self.parent_view.selected_team] if self.parent_view.selected_team else all_roles

            if not filtered_roles:
                await interaction.response.send_message(f"❌ No roles found for player ID '{pid}'!", ephemeral=True)
                return

            if len(filtered_roles) == 1:
                role = filtered_roles[0]
                roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
                index = next(i for i, r in enumerate(roles) if r[0] == role["role_id"])
                view = RoleDescriptionView(role["game_number"], role["game_name"], roles, index, self.parent_view.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                view = RoleSelectionView(filtered_roles, self.parent_view.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid player ID!", ephemeral=True)


class SearchSponsorNameModal(discord.ui.Modal, title="Enter Sponsor Name"):
    """Modal for searching by sponsor name."""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    sponsor_name = discord.ui.TextInput(label="Sponsor Name", placeholder="Enter sponsor name...", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        all_roles = self.parent_view.db.search_roles_by_sponsor_name(self.sponsor_name.value)
        filtered_roles = [r for r in all_roles if r["team"] == self.parent_view.selected_team] if self.parent_view.selected_team else all_roles

        if not filtered_roles:
            await interaction.response.send_message(f"❌ No roles found for sponsor '{self.sponsor_name.value}'!", ephemeral=True)
            return

        if len(filtered_roles) == 1:
            role = filtered_roles[0]
            roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], roles, index, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        else:
            view = RoleSelectionView(filtered_roles, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


class SearchSponsorIDModal(discord.ui.Modal, title="Enter Sponsor ID"):
    """Modal for searching by sponsor ID."""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    sponsor_id = discord.ui.TextInput(label="Sponsor ID", placeholder="Enter sponsor ID...", required=True, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            sid = int(self.sponsor_id.value)
            all_roles = self.parent_view.db.search_roles_by_sponsor_id(sid)
            filtered_roles = [r for r in all_roles if r["team"] == self.parent_view.selected_team] if self.parent_view.selected_team else all_roles

            if not filtered_roles:
                await interaction.response.send_message(f"❌ No roles found for sponsor ID '{sid}'!", ephemeral=True)
                return

            if len(filtered_roles) == 1:
                role = filtered_roles[0]
                roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
                index = next(i for i, r in enumerate(roles) if r[0] == role["role_id"])
                view = RoleDescriptionView(role["game_number"], role["game_name"], roles, index, self.parent_view.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                view = RoleSelectionView(filtered_roles, self.parent_view.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid sponsor ID!", ephemeral=True)


class RoleSelectionView(discord.ui.View):
    """View for selecting from multiple roles."""
    def __init__(self, roles: List[dict], db, page: int = 0):
        super().__init__(timeout=300)
        self.roles = roles
        self.db = db
        self.page = page
        self.page_size = 10
        self.max_page = math.ceil(len(roles) / self.page_size) - 1

        if self.max_page > 0:
            self.prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.primary, disabled=True)
            self.prev_btn.callback = self.prev_page
            self.add_item(self.prev_btn)

            self.next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary)
            self.next_btn.callback = self.next_page
            self.add_item(self.next_btn)

    def get_embed(self) -> discord.Embed:
        start_idx = self.page * self.page_size
        end_idx = min(start_idx + self.page_size, len(self.roles))
        page_roles = self.roles[start_idx:end_idx]

        embed = discord.Embed(
            title="🔍 Search Results - Multiple Roles Found",
            description="Select a role by entering its number below.",
            color=EMBED_COLOR,
        )

        lines = []
        for idx, role in enumerate(page_roles, start=start_idx + 1):
            game_label = f"{role['game_number']}-{role['game_name'].replace('-', ' ').title()}"
            player = role.get("player_name") or "Unknown"
            lines.append(f"**{idx}. |** {game_label} **|** {TEAMS[role['team']]} - {role['role_name']} - {player}\n")

        add_fields_paginated(embed, "Roles", lines)

        if self.max_page > 0:
            embed.set_footer(text=f"{EMBED_FOOTER_TEXT} | Page {self.page + 1}/{self.max_page + 1}", icon_url=EMBED_FOOTER_ICON)
        else:
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        return embed

    async def prev_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self.update_view(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        await self.update_view(interaction)

    async def update_view(self, interaction: discord.Interaction):
        if self.max_page > 0:
            self.prev_btn.disabled = (self.page == 0)
            self.next_btn.disabled = (self.page == self.max_page)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢 Enter Selection Number", style=discord.ButtonStyle.success, row=2)
    async def select_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RoleSelectionModal(self.roles, self.db))


class RoleSelectionModal(discord.ui.Modal, title="Select Role"):
    """Modal for selecting role from list."""
    def __init__(self, roles: List[dict], db):
        super().__init__()
        self.roles = roles
        self.db = db

    selection = discord.ui.TextInput(
        label="Selection Number",
        placeholder="Enter the number of the role...",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            idx = int(self.selection.value) - 1
            if 0 <= idx < len(self.roles):
                role = self.roles[idx]
                team_roles = self.db.get_roles_by_team(role["game_number"], role["team"])
                role_index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
                view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, role_index, self.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                await interaction.response.send_message("❌ Invalid selection number!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class StatsView(discord.ui.View):
    """View with leaderboard and game history buttons."""
    def __init__(self, db, target_member):
        super().__init__(timeout=300)
        self.db = db
        self.target = target_member

    @discord.ui.button(label="🏆 View Leaderboard", style=discord.ButtonStyle.primary)
    async def show_leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        stats = self.db.get_all_players_stats()
        if not stats:
            await interaction.response.send_message("❌ No player data found.", ephemeral=True)
            return
        view = LeaderboardView(stats)
        await interaction.response.send_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="📜 View Game History", style=discord.ButtonStyle.secondary)
    async def show_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        history = self.db.get_player_game_history(self.target.id)
        if not history:
            await interaction.response.send_message("📜 No recorded game history.", ephemeral=True)
            return
        view = GameHistoryView(history, self.target.display_name)
        await interaction.response.send_message(embed=view.get_embed(), view=view)


class MissingIDPageView(discord.ui.View):
    def __init__(self, cog, missing_players, page=0):
        super().__init__(timeout=300)
        self.cog = cog
        self.missing = sorted(missing_players, key=lambda x: x.lower())
        self.page = page
        self.page_size = 25
        self.max_page = (len(self.missing) - 1) // self.page_size

        start = page * self.page_size
        page_names = self.missing[start:start + self.page_size]
        self.visible_names = page_names

        self.dropdown = discord.ui.Select(
            placeholder=f"Select player ({len(self.missing)} total)",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=name, value=name) for name in page_names],
        )
        self.dropdown.callback = self.select_player
        self.add_item(self.dropdown)

        if page > 0:
            prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

        if page < self.max_page:
            next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    async def select_player(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AssignIDModal(self.cog, self.dropdown.values[0]))

    async def prev_page(self, interaction: discord.Interaction):
        new_view = MissingIDPageView(self.cog, self.missing, self.page - 1)
        new_embed = self.cog.generate_missingid_embed(new_view.visible_names, new_view.page, new_view.max_page)
        await interaction.response.edit_message(embed=new_embed, view=new_view)

    async def next_page(self, interaction: discord.Interaction):
        new_view = MissingIDPageView(self.cog, self.missing, self.page + 1)
        new_embed = self.cog.generate_missingid_embed(new_view.visible_names, new_view.page, new_view.max_page)
        await interaction.response.edit_message(embed=new_embed, view=new_view)


class AssignIDModal(discord.ui.Modal, title="Assign Discord ID"):
    def __init__(self, cog, player_name):
        super().__init__()
        self.cog = cog
        self.player_name = player_name

        self.discord_id = discord.ui.TextInput(
            label=f"Assign ID to {player_name}",
            placeholder="123456789012345678",
            max_length=20,
            required=True,
        )
        self.add_item(self.discord_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_id = int(self.discord_id.value)
        except ValueError:
            await interaction.response.send_message("❌ Invalid ID.", ephemeral=True)
            return

        self.cog.db.assign_player_id(self.player_name, new_id)
        await interaction.response.send_message(
            f"✅ Updated **{self.player_name}** → `{new_id}`",
            ephemeral=False,
        )

# ---------------------------
# RelationsView
# ---------------------------
class RelationsView(discord.ui.View):
    def __init__(self, ctx, player, allies, worst, nemesis):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.player = player
        self.allies = allies
        self.worst = worst
        self.nemesis = nemesis

    def build_embed(self, title, data):
        embed = discord.Embed(title=title, color=discord.Color.blurple())

        if not data:
            embed.description = "No data found."
            return embed

        lines = []
        for i, (name, score, win_pct) in enumerate(data, 1):
            lines.append(f"**{i}. {name}** — {score} ({win_pct}%)")

        embed.description = "\n".join(lines[:25])  # Discord limit safety
        return embed

    @discord.ui.button(label="Allies", style=discord.ButtonStyle.success)
    async def allies_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.build_embed(f"Allies of {self.player}", self.allies),
            view=self
        )

    @discord.ui.button(label="Worst", style=discord.ButtonStyle.danger)
    async def worst_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.build_embed(f"Worst Allies of {self.player}", self.worst),
            view=self
        )

    @discord.ui.button(label="Nemesis", style=discord.ButtonStyle.secondary)
    async def nemesis_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.build_embed(f"Nemesis of {self.player}", self.nemesis),
            view=self
        )

# ============================================================================
# COMMANDS COG
# ============================================================================

class GameLibrary(commands.Cog):
    """Main cog for game library."""
    def __init__(self, bot):
        self.bot = bot
        self.db = LibraryDatabase()

    def is_librarian(self, user_id: int) -> bool:
        return user_id in LIBRARIAN_IDS

    def generate_missingid_embed(self, names, page, max_page):
        listed = "\n".join([f"• {n}" for n in names])
        return discord.Embed(
            title="Players Missing Discord IDs",
            description=f"Page **{page + 1}/{max_page + 1}**\n\n{listed}",
            color=EMBED_COLOR,
        )

    def get_game_info_from_channel(self, channel: discord.TextChannel) -> Optional[Tuple[int, str]]:
        if not channel.category or channel.category.name != "📖 Library B":
            return None
        try:
            parts = channel.name.split("│", 1)
            if len(parts) == 2:
                return (int(parts[0].strip()), parts[1].strip())
        except (ValueError, AttributeError):
            pass
        return None

    # -------------------------------------------------------------------------
    # lib group
    # -------------------------------------------------------------------------

    @commands.group(name="lib", invoke_without_command=True)
    async def lib(self, ctx):
        """Browse game library."""
        games = self.db.get_all_games()
        if not games:
            await ctx.send("❌ The library is empty!")
            return
        view = GameSelectView(games, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    @lib.command(name="add")
    async def lib_add(self, ctx, role_name: str, team: Optional[int] = None, *args):
        """
        Add a role or hosts to the game.

        ROLE:   .lib add <role_name> <team> [@player] [@sponsor]
        HOST:   .lib add host @host1 @host2 ...
        """
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission to use this command!")
            return

        game_info = self.get_game_info_from_channel(ctx.channel)
        if not game_info:
            await ctx.send("❌ This command must be used in a Library game channel!")
            return

        game_number, game_name = game_info

        # --- HOST MODE ---
        if role_name.lower() == "host":
            mention_ids = [int(i) for i in re.findall(r"<@!?(\d+)>", ctx.message.content)]
            if not mention_ids:
                await ctx.send("❌ Please mention at least one host.")
                return
            if len(mention_ids) > 5:
                await ctx.send("❌ Maximum of 5 hosts per game.")
                return

            hosts = []
            for mid in mention_ids:
                try:
                    hosts.append(await ctx.guild.fetch_member(mid))
                except Exception:
                    pass

            if not hosts:
                await ctx.send("❌ Could not resolve mentioned users.")
                return

            self.db.add_hosts(game_number, hosts)
            embed = discord.Embed(
                title="🎤 Hosts Added",
                description=", ".join(m.display_name for m in hosts),
                color=discord.Color.green(),
            )
            embed.add_field(name="Game", value=f"{game_number} | {game_name}")
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
            return

        # --- ROLE MODE ---
        if team is None:
            await ctx.send("❌ Usage: .lib add <role_name> <team> [@player] [@sponsor]")
            return

        if team not in TEAMS:
            await ctx.send(f"❌ Invalid team! Use: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}")
            return

        role_id = self.db.get_next_role_id(game_number)
        mention_ids = [int(i) for i in re.findall(r"<@!?(\d+)>", ctx.message.content)]

        mentioned_members = []
        for mid in mention_ids:
            try:
                mentioned_members.append(await ctx.guild.fetch_member(mid))
            except Exception:
                pass

        player_name = player_id = sponsor_name = sponsor_id = None
        args_list = list(args)
        idx = mention_idx = 0

        if idx < len(args_list) and args_list[idx].startswith("<@") and mention_idx < len(mentioned_members):
            m = mentioned_members[mention_idx]
            player_name, player_id = m.display_name, m.id
            mention_idx += 1
            idx += 1

        if idx < len(args_list) and args_list[idx].startswith("<@") and mention_idx < len(mentioned_members):
            m = mentioned_members[mention_idx]
            sponsor_name, sponsor_id = m.display_name, m.id

        description1 = None
        if ctx.message.reference:
            try:
                replied = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                description1 = replied.content
            except Exception:
                pass

        try:
            self.db.add_role(
                game_number=game_number, game_name=game_name, role_id=role_id,
                role_name=role_name, team=team, player_name=player_name,
                player_id=player_id, sponsor_name=sponsor_name,
                sponsor_id=sponsor_id, description1=description1,
            )

            embed = discord.Embed(
                title="✅ Role Added",
                description=f"**{role_name}** (ID: {role_id})",
                color=discord.Color.green(),
            )
            embed.add_field(name="Game", value=f"{game_number} | {game_name}")
            embed.add_field(name="Team", value=TEAMS[team])
            if player_name:
                embed.add_field(name="Player", value=player_name)
            if sponsor_name:
                embed.add_field(name="Sponsor", value=sponsor_name)
            if description1:
                preview = description1[:200] + ("..." if len(description1) > 200 else "")
                embed.add_field(name="Description", value=preview, inline=False)
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Error adding role: `{e}`")

    def generate_team_pie_chart(self, team_counts: dict, game_number: int):
        import matplotlib.pyplot as plt
        teams = [TEAMS.get(tid, "Unknown") for tid, cnt in team_counts.items() if cnt > 0]
        counts = [cnt for cnt in team_counts.values() if cnt > 0]
        plt.figure()
        plt.pie(counts, labels=teams, autopct="%1.1f%%")
        plt.title(f"Game {game_number} — Team Distribution")
        file_path = f"game_{game_number}_distribution.png"
        plt.savefig(file_path)
        plt.close()
        return file_path

    @lib.command(name="summary")
    async def lib_summary(self, ctx, game_number: int):
        """Show game summary with pie chart."""
        summary = self.db.get_game_summary(game_number)
        if not summary or summary["total_roles"] == 0:
            await ctx.send("❌ Game not found or empty.")
            return

        team_lines = "".join(
            f"**{TEAMS[tid]}:** {summary['team_counts'].get(tid, 0)} roles\n"
            for tid in TEAMS
        )
        winner_names = [TEAMS[t] for t in summary["winning_teams"]]
        winner_text = ", ".join(winner_names) if winner_names else "Not set"

        embed = discord.Embed(title=f"📊 Game {game_number} Summary", color=EMBED_COLOR)
        embed.add_field(name="📦 Role Distribution", value=team_lines, inline=False)
        embed.add_field(name="👥 Total Roles", value=str(summary["total_roles"]))
        embed.add_field(name="🏆 Winning Team(s)", value=winner_text)

        hosts = self.db.get_hosts_for_game(game_number)
        if hosts:
            embed.add_field(name="🎤 Host(s)", value=", ".join(hosts), inline=False)

        chart_path = self.generate_team_pie_chart(summary["team_counts"], game_number)
        file = discord.File(chart_path, filename="distribution.png")
        embed.set_image(url="attachment://distribution.png")
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        await ctx.send(embed=embed, file=file)
        if os.path.exists(chart_path):
            os.remove(chart_path)

    @lib.command(name="edit")
    async def lib_edit(self, ctx, field: str, game_number: int, role_id_or_value: str, *, value: str = None):
        """Edit role field — Usage: .lib edit <field> <game#> <role_id> <value>"""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return

        # gamecount shortcut
        if field.lower() == "gamecount":
            try:
                count_value = int(role_id_or_value)
                if count_value not in [0, 1]:
                    await ctx.send("❌ Invalid value for gamecount! Use: 1 (yes) or 0 (no)")
                    return
                self.db.update_game_count(game_number, count_value)
                embed = discord.Embed(
                    title="✅ Game Count Updated",
                    description=f"All roles in game {game_number} set to count = {count_value}.",
                    color=discord.Color.green(),
                )
                embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
                await ctx.send(embed=embed)
                return
            except ValueError:
                await ctx.send("❌ Invalid value!")
                return

        try:
            role_id = int(role_id_or_value)
        except ValueError:
            await ctx.send("❌ Invalid role ID!")
            return

        valid_fields = [
            "team", "player_name", "player_id", "sponsor_name", "sponsor_id",
            "description1", "description2", "description3", "description4",
            "role_name", "win", "count", "mvp",
        ]
        if field.lower() not in valid_fields:
            await ctx.send(f"❌ Invalid field! Valid: {', '.join(valid_fields + ['gamecount'])}")
            return

        if field.lower() in ["description1", "description2", "description3", "description4"]:
            if ctx.message.reference:
                try:
                    replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    value = replied_message.content
                except Exception:
                    if not value:
                        await ctx.send("❌ Could not fetch reply and no value provided!")
                        return
            elif not value:
                await ctx.send("❌ Please provide value or reply to message!")
                return
        elif not value:
            await ctx.send("❌ Please provide a value!")
            return

        try:
            if field.lower() in ["team", "player_id", "sponsor_id"]:
                value = int(value)
                if field.lower() == "team" and value not in TEAMS:
                    await ctx.send(f"❌ Invalid team! Use: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}")
                    return
            elif field.lower() in ["win", "count", "mvp"]:
                value = int(value)
                if value not in [0, 1]:
                    await ctx.send(f"❌ Invalid value for {field}! Use: 1 (yes) or 0 (no)")
                    return

            self.db.update_field(game_number, role_id, field.lower(), value)

            embed = discord.Embed(
                title="✅ Role Updated",
                description=f"Field **{field}** updated for role ID {role_id} in game {game_number}.",
                color=discord.Color.green(),
            )
            if field.lower() in ["description1", "description2", "description3", "description4"]:
                preview = str(value)[:100] + ("..." if len(str(value)) > 100 else "")
                embed.add_field(name="New Value (Preview)", value=f"```{preview}```")
            elif field.lower() in ["win", "count"]:
                embed.add_field(name="New Value", value="✅ Yes" if value == 1 else "❌ No")
            elif field.lower() == "mvp":
                embed.add_field(name="New Value", value="⭐ MVP" if value == 1 else "— Not MVP")
            else:
                embed.add_field(name="New Value", value=str(value)[:1024])
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except ValueError as e:
            await ctx.send(f"❌ Invalid value type! {e}")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @lib.command(name="delete")
    async def lib_delete(self, ctx, game_number: int, role_id: int):
        """Delete role — Usage: .lib delete <game#> <role_id>"""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return

        role = self.db.get_role_details(game_number, role_id)
        if not role:
            await ctx.send(f"❌ Role ID {role_id} not found in game {game_number}!")
            return

        try:
            self.db.delete_role(game_number, role_id)
            embed = discord.Embed(
                title="✅ Role Deleted",
                description=f"Role **{role['role_name']}** (ID: {role_id}) deleted from game {game_number}.",
                color=discord.Color.green(),
            )
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @lib.command(name="deletegame")
    async def lib_deletegame(self, ctx, game_number: int):
        """Delete entire game — Usage: .lib deletegame <game#>"""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return

        game_data = next((g for g in self.db.get_all_games() if g[0] == game_number), None)
        if not game_data:
            await ctx.send(f"❌ Game {game_number} not found!")
            return

        try:
            self.db.delete_game(game_number)
            embed = discord.Embed(
                title="✅ Game Deleted",
                description=f"Game {game_number} ({game_data[1]}) and all roles deleted.",
                color=discord.Color.green(),
            )
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @lib.command(name="setwin")
    async def lib_setwin(self, ctx, game_number: int, *teams: int):
        """Set winners — Usage: .lib setwin <game#> <team1> [team2]..."""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return

        invalid_teams = [t for t in teams if t not in TEAMS]
        if invalid_teams:
            await ctx.send(f"❌ Invalid teams: {', '.join(map(str, invalid_teams))}\nValid: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}")
            return

        try:
            self.db.set_winners(game_number, list(teams))
            team_names = [TEAMS[t] for t in teams] if teams else ["None"]
            embed = discord.Embed(
                title="✅ Winners Set",
                description=f"Winners set for game {game_number}.",
                color=discord.Color.green(),
            )
            embed.add_field(name="Winning Team(s)", value=", ".join(team_names))
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @lib.command(name="search")
    async def lib_search(self, ctx, *args):
        """Search roles (fuzzy). Supports: .lib search, .lib search <name>, .lib search <game#>, .lib search <game#> <name>"""
        if not args:
            view = InteractiveSearchView(self.db)
            embed = discord.Embed(
                title="🔍 Search Library",
                description=(
                    "Search by:\n"
                    "• Role name (fuzzy)\n"
                    "• Game number\n"
                    "• Game number + role name\n\n"
                    "Examples:\n"
                    "`.lib search doctor`\n"
                    "`.lib search 12`\n"
                    "`.lib search 12 doctor`"
                ),
                color=EMBED_COLOR,
            )
            await ctx.send(embed=embed, view=view)
            return

        if len(args) == 1 and args[0].isdigit():
            game_number = int(args[0])
            game = next((g for g in self.db.get_all_games() if g[0] == game_number), None)
            if not game:
                await ctx.send("❌ Game not found.")
                return
            view = TeamSelectView(game_number, game[1], self.db)
            await ctx.send(embed=view.get_embed(), view=view)
            return

        if args[0].isdigit():
            game_number = int(args[0])
            query = " ".join(args[1:]).strip()
            if not query:
                await ctx.send("❌ Please provide a role name to search.")
                return
            roles = [r for r in self.db.search_roles_fuzzy(query) if r["game_number"] == game_number]
        else:
            query = " ".join(args).strip()
            roles = self.db.search_roles_fuzzy(query)

        def score(name):
            return SequenceMatcher(None, query.lower(), (name or "").lower()).ratio()

        roles.sort(
            key=lambda r: max(score(r["role_name"]), score(r["player_name"] or ""), score(r["sponsor_name"] or "")),
            reverse=True,
        )

        if not roles:
            await ctx.send("❌ No matching roles found.")
            return

        if len(roles) == 1:
            role = roles[0]
            team_roles = self.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, index, self.db)
            await ctx.send(embed=view.get_embed(), view=view)
            return

        view = RoleSelectionView(roles, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    @lib.command(name="idsearch")
    async def lib_idsearch(self, ctx, game_number: int, role_id: int):
        """Jump to a role by ID — Usage: .lib idsearch <game#> <role_id>"""
        role_data = self.db.get_role_details(game_number, role_id)
        if not role_data:
            await ctx.send(f"❌ Role ID {role_id} not found in game {game_number}!")
            return
        roles = self.db.get_roles_by_team(game_number, role_data["team"])
        index = next(i for i, r in enumerate(roles) if r[0] == role_id)
        view = RoleDescriptionView(game_number, role_data["game_name"], roles, index, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    @lib.command(name="migrateaccount")
    async def lib_migrateaccount(self, ctx, old_identifier: str, new_member: discord.Member):
        """
        Migrate stats from old account (name OR id) to a new Discord account.

        Examples:
        .lib migrateaccount "OldName" @NewUser
        .lib migrateaccount 123456789 @NewUser
        """
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return

        db = self.db
        old_id = None

        if old_identifier.isdigit():
            old_id = int(old_identifier)
        else:
            matches = db.find_accounts_by_name(old_identifier)
            if len(matches) == 0:
                await ctx.send("❌ No accounts found with that name.")
                return

            if len(matches) > 1:
                msg = "⚠️ Multiple accounts found. Reply with the number:\n\n"
                for i, (pid, pname) in enumerate(matches, start=1):
                    msg += f"**{i}.** {pname} (`{pid}`)\n"
                await ctx.send(msg)

                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

                try:
                    reply = await self.bot.wait_for("message", check=check, timeout=30)
                    choice = int(reply.content)
                    if choice < 1 or choice > len(matches):
                        await ctx.send("❌ Invalid selection.")
                        return
                    old_id = matches[choice - 1][0]
                except asyncio.TimeoutError:
                    await ctx.send("⌛ Timed out. Migration cancelled.")
                    return
            else:
                old_id = matches[0][0]

        if old_id == new_member.id:
            await ctx.send("❌ Source and target accounts are the same.")
            return

        old_player_rows, old_sponsor_rows = db.get_account_stat_counts(old_id)
        if old_player_rows == 0 and old_sponsor_rows == 0:
            await ctx.send("⚠️ Warning: Source account has no stats recorded.")

        new_player_rows, new_sponsor_rows = db.get_account_stat_counts(new_member.id)
        if new_player_rows > 0 or new_sponsor_rows > 0:
            await ctx.send("⚠️ Target account already has stats.\nUse `.lib mergeaccount` instead.")
            return

        preview = (
            "⚠️ **ACCOUNT MIGRATION CONFIRMATION** ⚠️\n\n"
            "**SOURCE (Will lose stats reference)**\n"
            f"`{old_id}`\n"
            f"{old_player_rows} player games | {old_sponsor_rows} sponsor games\n\n"
            "**TARGET (Will receive stats)**\n"
            f"{new_member.display_name} (`{new_member.id}`)\n\n"
            "Type **MIGRATE** to confirm\nType **CANCEL** to abort\n(Times out in 30s)"
        )
        await ctx.send(preview)

        def confirm_check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.upper() in ["MIGRATE", "CANCEL"]

        try:
            reply = await self.bot.wait_for("message", check=confirm_check, timeout=30)
            if reply.content.upper() == "CANCEL":
                await ctx.send("❌ Migration cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("⌛ Migration confirmation timed out.")
            return

        db.migrate_account_by_id(old_id, new_member.id, new_member.display_name)
        await ctx.send(f"✅ Migration complete → **{new_member.display_name}** now owns old stats.")

    @lib.command(name="mergeaccount")
    async def mergeaccount(self, ctx, source_input: str, target_input: str):
        """Merge two accounts. Source stats will be absorbed into target."""
        db = self.db

        async def resolve_account(user_input, label):
            if ctx.message.mentions:
                for m in ctx.message.mentions:
                    if user_input in [m.mention, str(m.id)]:
                        return m.id, m.display_name
            if user_input.isdigit():
                return int(user_input), f"User-{user_input}"
            matches = db.find_accounts_by_name(user_input)
            if not matches:
                await ctx.send(f"❌ No matches found for `{user_input}`")
                return None, None
            if len(matches) == 1:
                return matches[0][0], matches[0][1]
            msg = f"🔎 Multiple matches for **{label}** `{user_input}`:\n\n"
            for i, (pid, pname) in enumerate(matches[:10], 1):
                msg += f"{i}. **{pname}** ({pid})\n"
            msg += "\nReply with the number."
            await ctx.send(msg)

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

            try:
                reply = await self.bot.wait_for("message", check=check, timeout=30)
                idx = int(reply.content) - 1
                if 0 <= idx < len(matches):
                    return matches[idx][0], matches[idx][1]
            except Exception:
                pass
            await ctx.send("❌ Selection failed.")
            return None, None

        source_id, source_name = await resolve_account(source_input, "SOURCE")
        if not source_id:
            return

        target_id, target_name = await resolve_account(target_input, "TARGET")
        if not target_id:
            return

        if source_id == target_id:
            await ctx.send("❌ Source and target accounts are the same.")
            return

        src_player, src_sponsor = db.get_account_stat_counts(source_id)
        tgt_player, tgt_sponsor = db.get_account_stat_counts(target_id)

        preview = (
            "⚠️ **MERGE CONFIRMATION** ⚠️\n\n"
            "**SOURCE (Will be absorbed)**\n"
            f"{source_name} (`{source_id}`)\n"
            f"{src_player} player games | {src_sponsor} sponsor games\n\n"
            "**TARGET (Will keep everything)**\n"
            f"{target_name} (`{target_id}`)\n"
            f"{tgt_player} player games | {tgt_sponsor} sponsor games\n\n"
            "Type **MERGE** to confirm\nType **CANCEL** to abort\n(Times out in 30s)"
        )
        await ctx.send(preview)

        def confirm_check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.upper() in ["MERGE", "CANCEL"]

        try:
            reply = await self.bot.wait_for("message", check=confirm_check, timeout=30)
            if reply.content.upper() == "CANCEL":
                await ctx.send("❌ Merge cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("⌛ Merge confirmation timed out.")
            return

        try:
            db.merge_accounts(source_id, target_id, target_name)
            await ctx.send(f"✅ Merge complete!\nMoved all stats from **{source_name}** → **{target_name}**")
        except Exception as e:
            await ctx.send("❌ Merge failed. Contact admin.")
            print("Merge error:", e)

    @lib.command(name="syncname")
    async def lib_syncname(self, ctx, member: discord.Member, scope: str = "both"):
        """
        Sync stored name for a single account.

        Usage:
        .lib syncname @User
        .lib syncname @User player
        .lib syncname @User sponsor
        .lib syncname @User both
        """
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return

        scope = scope.lower()
        include_player = scope in ("player", "both")
        include_sponsor = scope in ("sponsor", "both")

        if not include_player and not include_sponsor:
            await ctx.send("❌ Scope must be one of: `player`, `sponsor`, `both`.")
            return

        updated_player, updated_sponsor = self.db.sync_account_name(
            member.id, member.display_name,
            include_player=include_player, include_sponsor=include_sponsor,
        )

        if updated_player == 0 and updated_sponsor == 0:
            await ctx.send(f"ℹ️ No stored stats found for **{member.display_name}** (by player_id / sponsor_id).")
            return

        parts = []
        if include_player:
            parts.append(f"{updated_player} player rows")
        if include_sponsor:
            parts.append(f"{updated_sponsor} sponsor rows")

        await ctx.send(f"✅ Synced stored name for **{member.display_name}** across {', '.join(parts)}.")

    @lib.command(name="bulksyncnames")
    async def lib_bulksyncnames(self, ctx):
        """Bulk-sync stored names for all known accounts using their current Discord display names."""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return

        all_ids = self.db.get_all_account_ids()
        if not all_ids:
            await ctx.send("ℹ️ No accounts with stored IDs were found to sync.")
            return

        await ctx.send(
            f"⚠️ This will sync stored names for all known accounts in this server.\n"
            f"Total IDs detected: **{len(all_ids)}**\n\n"
            "Type **CONFIRM** to proceed or **CANCEL** to abort. (30s timeout)"
        )

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.upper() in ["CONFIRM", "CANCEL"]

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=30)
            if reply.content.upper() == "CANCEL":
                await ctx.send("❌ Bulk sync cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("⌛ Bulk sync confirmation timed out.")
            return

        total_player_updates = total_sponsor_updates = missing_members = 0

        for discord_id in all_ids:
            try:
                member = ctx.guild.get_member(discord_id) or await ctx.guild.fetch_member(discord_id)
            except Exception:
                member = None

            if not member:
                missing_members += 1
                continue

            up, us = self.db.sync_account_name(discord_id, member.display_name)
            total_player_updates += up
            total_sponsor_updates += us

        msg = (
            f"✅ Bulk name sync complete.\n"
            f"Updated **{total_player_updates}** player rows and **{total_sponsor_updates}** sponsor rows.\n"
        )
        if missing_members:
            msg += f"⚠️ {missing_members} IDs were not found in this server (users may have left or never joined)."

        await ctx.send(msg)

    @lib.command(name="help")
    async def lib_help(self, ctx):
        """Display help."""
        embed = discord.Embed(
            title="📚 Game Library — Help",
            description="Browse roles, view stats, manage library.",
            color=EMBED_COLOR,
        )

        embed.add_field(name="🔍 Browse & Search", value=(
            "**`.lib`**\nOpen interactive game browser\n\n"
            "**`.lib search`**\nInteractive fuzzy search (roles, players, sponsors)\n\n"
            "**`.lib search <role name>`**\nFuzzy role search across all games\n\n"
            "**`.lib search <game#>`**\nJump directly to a game\n\n"
            "**`.lib search <game#> <role name>`**\nSearch within a specific game\n\n"
            "**`.lib idsearch <game#> <role_id>`**\nJump directly to a role by ID\n\n"
            "**`.lib summary <game#>`**\nShow game summary + team pie chart"
        ), inline=False)

        embed.add_field(name="📊 Statistics", value=(
            "**`.stats`** or **`.stats @player`**\nView player statistics including ⭐ MVPs\n\n"
            "**`.winrate`**\nView overall team winrates"
        ), inline=False)

        if self.is_librarian(ctx.author.id):
            embed.add_field(name="🔧 Role Management", value=(
                "**`.lib add <role_name> <team> [@player] [@sponsor]`**\nAdd a role (reply for description)\n\n"
                "**`.lib edit <field> <game#> <role_id> <value>`**\n"
                "Edit: team, role_name, player_name, player_id,\n"
                "sponsor_name, sponsor_id, description1-4, win, count, **mvp**\n\n"
                "**`.lib delete <game#> <role_id>`**\nDelete a role"
            ), inline=False)

            embed.add_field(name="🎮 Game Control", value=(
                "**`.lib edit gamecount <game#> <0|1>`**\nInclude/exclude game from stats\n\n"
                "**`.lib setwin <game#> <team> [team2]...`**\nSet winning team(s)\n\n"
                "**`.lib deletegame <game#>`**\nDelete entire game"
            ), inline=False)

            embed.add_field(name="👤 Account Tools", value=(
                "**`.lib migrateaccount <old_name|old_id> @new_user`**\nMove stats to a new account (with preview)\n\n"
                "**`.lib mergeaccount <source> <target>`**\nMerge two accounts (confirmation required)\n\n"
                "**`.lib syncname @user [player|sponsor|both]`**\nSync stored name for a single account\n\n"
                "**`.lib bulksyncnames`**\nBulk-sync stored names for all known accounts"
            ), inline=False)

        team_info = " • ".join([f"**{id}** = {name}" for id, name in TEAMS.items()])
        embed.add_field(name="🎯 Team IDs", value=team_info, inline=False)
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        await ctx.send(embed=embed)

    # -------------------------------------------------------------------------
    # Standalone commands
    # -------------------------------------------------------------------------

    @commands.has_permissions(administrator=True)
    @commands.command(name="missingids")
    async def missing_ids(self, ctx):
        """Show players missing Discord IDs with pagination."""
        if not self.db.get_all_games():
            await ctx.send("❌ The library is empty! No games have been recorded yet.")
            return
        missing = self.db.get_players_missing_ids()

        if not missing:
            await ctx.send("✅ All players have IDs assigned.")
            return

        view = MissingIDPageView(self, missing, page=0)
        embed = self.generate_missingid_embed(view.visible_names, 0, view.max_page)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="stats")
    async def stats(self, ctx, *, member_input: str = None):
        """View player stats — Usage: .stats or .stats @player or .stats PlayerName"""
        member = None

        if not member_input:
            member = ctx.author
        else:
            mention_match = re.search(r"<@!?(\d+)>", member_input)
            if mention_match:
                try:
                    member = await ctx.guild.fetch_member(int(mention_match.group(1)))
                except Exception:
                    member = None

        if not member and member_input:
            lowered = member_input.lower()
            for m in ctx.guild.members:
                if m.display_name.lower() == lowered or m.name.lower() == lowered:
                    member = m
                    break

        if not member and member_input:
            matches = self.db.find_accounts_by_name(member_input)

            if len(matches) == 0:
                await ctx.send("❌ No player found with that name.")
                return

            if len(matches) > 1:
                msg = "⚠️ Multiple matches found. Reply with number:\n\n"
                for i, (pid, pname) in enumerate(matches, start=1):
                    msg += f"**{i}.** {pname} (`{pid}`)\n"
                await ctx.send(msg)

                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

                try:
                    reply = await self.bot.wait_for("message", check=check, timeout=30)
                    choice = int(reply.content)
                    if choice < 1 or choice > len(matches):
                        await ctx.send("❌ Invalid selection.")
                        return
                    chosen_id, chosen_name = matches[choice - 1]
                except asyncio.TimeoutError:
                    await ctx.send("⌛ Timed out.")
                    return
            else:
                chosen_id, chosen_name = matches[0]

            class FakeMember:
                def __init__(self, id, name, avatar):
                    self.id = id
                    self.display_name = name
                    self.display_avatar = avatar

            member = FakeMember(chosen_id, chosen_name, ctx.author.display_avatar)

        if not member:
            await ctx.send("❌ Could not resolve player.")
            return

        stats = self.db.get_player_stats(member.id)

        if stats["total_participations"] == 0:
            await ctx.send(f"❌ No statistics found for {member.display_name}!")
            return

        embed = discord.Embed(title=f"📊 {member.display_name}", color=EMBED_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)

        first_game_num, first_game_name = self.db.get_first_game_played(member.id)
        first_game_line = (
            f"**First Game:** {first_game_num} — {first_game_name}\n"
            if first_game_num
            else "**First Game:** Unknown\n"
        )

        games_list = self.db.get_games_played(member.id)
        if len(games_list) >= 2:
            gaps = [games_list[i + 1] - games_list[i] for i in range(len(games_list) - 1)]
            avg_gap = sum(gaps) / len(gaps)
            total_from_start = max(games_list) - min(games_list) + 1
            participation_after_join = (len(games_list) / total_from_start) * 100
            avg_gap_line = f"**Avg Gap:** {avg_gap:.2f} games\n**Participation After Joining:** {participation_after_join:.1f}%\n"
        else:
            avg_gap_line = "**Avg Gap:** Not enough data\n"

        top_allies = self.db.get_top_allies2(member.id)
        ally_text = (
            "".join(f"• **{pname}** — {wr * 100:.1f}% WR ({wins}W / {games}G)\n"
                    for pid, pname, wins, games, wr in top_allies)
            or "*No strong allies found.*"
        )

        worst_allies = self.db.get_worst_allies2(member.id)
        worst_text = (
            "".join(f"• **{pname}** — {wr * 100:.1f}% WR ({wins}W / {games}G)\n"
                    for pid, pname, wins, games, wr in worst_allies)
            or "*No cursed alliances detected.*"
        )

        top_nemeses = self.db.get_top_nemeses2(member.id)
        nem_text = (
            "".join(f"• **{pname}** — {lr * 100:.1f}% Loss ({losses}L / {games}G)\n"
                    for pid, pname, losses, games, lr in top_nemeses)
            or "*No strong nemeses found.*"
        )

        overall = first_game_line + avg_gap_line
        overall += f"**Games:** {stats['games_as_player']} played · {stats['games_as_sponsor']} sponsored\n"
        overall += f"**Wins:** {stats['wins_as_player']}W (player) · {stats['wins_as_sponsor']}W (sponsor)\n"
        overall += f"**Winrate:** {stats['winrate']:.1f}% · **Participations:** {stats['total_participations']} ({stats['participation_rate']:.1f}%)\n"
        overall += f"**Village WS:** {stats.get('longest_winstreak', 0)}"

        embed.add_field(name="📈 Overall", value=overall, inline=False)

        # MVP breakdown field
        total_mvps = stats.get("total_mvps", 0)
        mvp_parts = []
        if stats.get("village_mvps", 0): mvp_parts.append(f"🏘️ Village: {stats['village_mvps']}")
        if stats.get("evil_mvps", 0):   mvp_parts.append(f"😈 Evil: {stats['evil_mvps']}")
        if stats.get("rk_mvps", 0):     mvp_parts.append(f"🔪 RK: {stats['rk_mvps']}")
        if stats.get("neutral_mvps", 0):mvp_parts.append(f"⚖️ Neutral: {stats['neutral_mvps']}")
        mvp_value = f"**Total:** ⭐ {total_mvps}\n" + ("\n".join(mvp_parts) if mvp_parts else "*No team breakdown*")
        embed.add_field(name="⭐ MVPs", value=mvp_value, inline=True)

        embed.add_field(
            name="📊 Streaks",
            value=(
                f"Best: {stats['ws']}W / {stats['ls']}L\n"
                f"Now: +{stats['cws']} / -{stats['cls']}\n"
                f"Form: {stats['form'] or '—'}"
            ),
            inline=True,
        )

        for team_name, team_data in stats["team_stats"].items():
            if team_data["total"] > 0 and team_name != "Bonus/Extra":
                team_winrate = team_data["wins"] / team_data["total"] * 100
                embed.add_field(
                    name=team_name,
                    value=f"{team_data['wins']}W/{team_data['total']}G ({team_winrate:.0f}%)",
                    inline=True,
                )

        embed.add_field(name="🟦 Top 5 Allies", value=ally_text, inline=False)
        embed.add_field(name="🟥 Top 5 Nemeses", value=nem_text, inline=False)
        embed.add_field(name="☠️ Worst Allies", value=worst_text, inline=False)
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        await ctx.send(embed=embed, view=StatsView(self.db, member))

    @commands.command(name="winrate")
    async def winrate(self, ctx):
        """View overall team winrates."""
        stats = self.db.get_winrate_stats()
        embed = discord.Embed(
            title="📊 Team Winrate Statistics",
            description="Overall performance across all games",
            color=EMBED_COLOR,
        )
        for team_name, data in stats.items():
            embed.add_field(
                name=team_name,
                value=f"**Games:** {data['total']}\n**Wins:** {data['wins']}\n**Winrate:** {data['winrate']:.1f}%",
                inline=True,
            )
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        await ctx.send(embed=embed)

    @commands.command(name="relations")
    async def relations(self, ctx, member: discord.Member = None):
        """View full list of allies, worst allies, and nemeses - Usage: .relations [@player]"""
        if member is None:
            member = ctx.author

        allies = self.db.get_all_allies2(member.id)
        worst_allies = self.db.get_all_worst_allies2(member.id)
        nemeses = self.db.get_all_nemeses2(member.id)

        if not allies and not worst_allies and not nemeses:
            await ctx.send(f"❌ No relation data found for {member.display_name}!")
            return

        def format_rows(rows, is_loss=False):
            return [(x[1], f"{x[2]}{'L' if is_loss else 'W'} / {x[3]}G", f"{x[4]*100:.1f}") for x in rows]

        view = RelationsView(
            ctx=ctx,
            player=member.display_name,
            allies=format_rows(allies),
            worst=format_rows(worst_allies),
            nemesis=format_rows(nemeses, is_loss=True)
        )
        
        embed = view.build_embed(f"Allies of {member.display_name}", view.allies)
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(GameLibrary(bot))
