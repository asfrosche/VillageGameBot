import os
import discord
from discord.ext import commands
import sqlite3
import math
from typing import Optional, List, Tuple
import re
import asyncio
from difflib import SequenceMatcher


# ============================================================================
# CONFIGURATION
# ============================================================================

LIBRARIAN_IDS = [365954082281881600, 887214529170268190, 1082939271914201199, 1234829080898310197, 320504417520582664,197169839863758848, 450772749829537793, 570023325653270548, 691180618402234399, 538814265599983617, 319848617814917120]
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

# ============================================================================
# DATABASE CLASS
# ============================================================================

class LibraryDatabase:
    def __init__(self, db_path: str = "db/roles_library.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """Initialize database and create tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if table exists and needs migration
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='roles'")
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            # Check current structure
            cursor.execute("PRAGMA table_info(roles)")
            columns = [(col[1], col[2]) for col in cursor.fetchall()]
            column_names = [col[0] for col in columns]
            
            # Check if count is in wrong position (before descriptions)
            if 'count' in column_names:
                count_index = column_names.index('count')
                desc1_index = column_names.index('description1') if 'description1' in column_names else -1
                
                # If count comes before description1, we need to migrate
                if desc1_index > 0 and count_index < desc1_index:
                    print("⚠️  Detected wrong column order. Starting migration...")
                    self._migrate_database(conn, cursor)
                    print("✅ Migration completed successfully!")
        
        # Create table with correct structure if it doesn't exist
        cursor.execute('''
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
                PRIMARY KEY (game_number, role_id)
            )
        ''')

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
        conn.close()
    

    def _migrate_database(self, conn, cursor):
        """Migrate database to fix column order"""
        # Create new table with correct structure
        cursor.execute('''
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
                PRIMARY KEY (game_number, role_id)
            )
        ''')
        
        # Copy data with correct column mapping
        # OLD: game_number, game_name, role_id, role_name, team, player_name, 
        #      player_id, sponsor_name, sponsor_id, win, count, desc1, desc2, desc3, desc4
        # NEW: game_number, game_name, role_id, role_name, team, player_name,
        #      player_id, sponsor_name, sponsor_id, win, desc1, desc2, desc3, desc4, count
        
        cursor.execute('''
            INSERT INTO roles_new 
            (game_number, game_name, role_id, role_name, team, player_name, 
            player_id, sponsor_name, sponsor_id, win, description1, description2, 
            description3, description4, count)
            SELECT 
                game_number, game_name, role_id, role_name, team, player_name, 
                player_id, sponsor_name, sponsor_id, win, description1, description2, 
                description3, description4, count
            FROM roles
        ''')
        
        # Drop old table
        cursor.execute('DROP TABLE roles')
        
        # Rename new table
        cursor.execute('ALTER TABLE roles_new RENAME TO roles')
        
        conn.commit()

    def get_next_role_id(self, game_number: int) -> int:
        """Get next available role_id for a game"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(role_id) FROM roles WHERE game_number = ?", (game_number,))
        result = cursor.fetchone()[0]
        conn.close()
        return (result + 1) if result is not None else 1

    def add_hosts(self, game_number: int, hosts: list[discord.Member]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for member in hosts[:5]:
            cursor.execute("""
                INSERT OR REPLACE INTO game_hosts
                (game_number, host_name, host_id, count)
                VALUES (?, ?, ?, 1)
            """, (game_number, member.display_name, member.id))

        conn.commit()
        conn.close()

    def find_accounts_by_name(self, name: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT player_id, player_name
            FROM roles
            WHERE LOWER(player_name) = LOWER(?)
            AND player_id IS NOT NULL
        """, (name,))
        players = cursor.fetchall()

        cursor.execute("""
            SELECT DISTINCT sponsor_id, sponsor_name
            FROM roles
            WHERE LOWER(sponsor_name) = LOWER(?)
            AND sponsor_id IS NOT NULL
        """, (name,))
        sponsors = cursor.fetchall()

        conn.close()

        accounts = {}
        for pid, pname in players + sponsors:
            accounts[pid] = pname

        return [(pid, pname) for pid, pname in accounts.items()]

    def merge_accounts(self, source_id: int, target_id: int, target_name: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Player stats
        cursor.execute("""
            UPDATE roles
            SET player_id = ?, player_name = ?
            WHERE player_id = ?
        """, (target_id, target_name, source_id))

        # Sponsor stats
        cursor.execute("""
            UPDATE roles
            SET sponsor_id = ?, sponsor_name = ?
            WHERE sponsor_id = ?
        """, (target_id, target_name, source_id))

        conn.commit()
        conn.close()

    
    def get_account_stat_counts(self, discord_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM roles WHERE player_id = ?",
            (discord_id,)
        )
        player_rows = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM roles WHERE sponsor_id = ?",
            (discord_id,)
        )
        sponsor_rows = cursor.fetchone()[0]

        conn.close()
        return player_rows, sponsor_rows


    def migrate_account_by_id(self, old_id: int, new_id: int, new_name: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE roles
            SET player_id = ?, player_name = ?
            WHERE player_id = ?
        """, (new_id, new_name, old_id))

        cursor.execute("""
            UPDATE roles
            SET sponsor_id = ?, sponsor_name = ?
            WHERE sponsor_id = ?
        """, (new_id, new_name, old_id))

        conn.commit()
        conn.close()



    
    def add_role(self, game_number: int, game_name: str, role_id: int, 
                 role_name: str, team: int, player_name: Optional[str] = None,
                 player_id: Optional[int] = None, sponsor_name: Optional[str] = None, 
                 sponsor_id: Optional[int] = None, description1: Optional[str] = None):
        """Add or replace a role"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO roles 
            (game_number, game_name, role_id, role_name, team, player_name, 
             player_id, sponsor_name, sponsor_id, description1, win, count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
        ''', (game_number, game_name, role_id, role_name, team, player_name, 
              player_id, sponsor_name, sponsor_id, description1))
        conn.commit()
        conn.close()
    
    def update_field(self, game_number: int, role_id: int, field: str, value):
        """Update a specific field"""
        valid_fields = ['team', 'player_name', 'player_id', 'sponsor_name', 
                       'sponsor_id', 'description1', 'description2', 
                       'description3', 'description4', 'role_name', 'win', 'count']
        
        if field not in valid_fields:
            raise ValueError(f"Invalid field: {field}")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = f"UPDATE roles SET {field} = ? WHERE game_number = ? AND role_id = ?"
        cursor.execute(query, (value, game_number, role_id))
        conn.commit()
        conn.close()
    
    def update_game_count(self, game_number: int, count_value: int):
        """Update count field for all roles in a game"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE roles SET count = ? WHERE game_number = ?", (count_value, game_number))
        conn.commit()
        conn.close()
    
    def delete_role(self, game_number: int, role_id: int):
        """Delete a role"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM roles WHERE game_number = ? AND role_id = ?", (game_number, role_id))
        conn.commit()
        conn.close()
    
    def delete_game(self, game_number: int):
        """Delete entire game"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM roles WHERE game_number = ?", (game_number,))
        conn.commit()
        conn.close()
    
    def set_winners(self, game_number: int, winning_teams: List[int]):
        """Set winning teams"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE roles SET win = 0 WHERE game_number = ?", (game_number,))
        if winning_teams:
            placeholders = ','.join('?' * len(winning_teams))
            cursor.execute(
                f"UPDATE roles SET win = 1 WHERE game_number = ? AND team IN ({placeholders})", 
                [game_number] + winning_teams
            )
        conn.commit()
        conn.close()
    
    def get_all_games(self) -> List[Tuple[int, str]]:
        """Get all games"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT game_number, game_name FROM roles ORDER BY game_number")
        games = cursor.fetchall()
        conn.close()
        return games
    
    def get_winning_teams(self, game_number: int) -> List[str]:
        """Get winning team names"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT team FROM roles WHERE game_number = ? AND win = 1", (game_number,))
        teams = [TEAMS.get(row[0], "Unknown") for row in cursor.fetchall()]
        conn.close()
        return teams
    
    def get_roles_by_team(self, game_number: int, team: int) -> List[Tuple]:
        """Get roles for a team with player names"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role_id, role_name, player_name FROM roles WHERE game_number = ? AND team = ? ORDER BY role_id", 
            (game_number, team)
        )
        roles = cursor.fetchall()
        conn.close()
        return roles
    
    def get_role_details(self, game_number: int, role_id: int) -> Optional[dict]:
        """Get role details"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE game_number = ? AND role_id = ?", (game_number, role_id))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'game_number': row[0],
                'game_name': row[1],
                'role_id': row[2],
                'role_name': row[3],
                'team': row[4],
                'player_name': row[5],
                'player_id': row[6],
                'sponsor_name': row[7],
                'sponsor_id': row[8],
                'win': row[9],
                'description1': row[10],  # ← CORRETTO!
                'description2': row[11],  # ← CORRETTO!
                'description3': row[12],  # ← CORRETTO!
                'description4': row[13],  # ← CORRETTO!
                'count': row[14]          # ← SPOSTATO ALLA FINE!
            }
        return None
    
    # DEPRECATED — do not use, kept for backward compatibility
    def search_role_by_name(self, game_number: int, role_name: str) -> Optional[dict]:
        """Search role by name in game"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM roles WHERE game_number = ? AND LOWER(role_name) = LOWER(?)", 
            (game_number, role_name)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'game_number': row[0], 'game_name': row[1], 'role_id': row[2],
                'role_name': row[3], 'team': row[4], 'player_name': row[5],
                'player_id': row[6], 'sponsor_name': row[7], 'sponsor_id': row[8],
                'win': row[9], 'description1': row[10], 'description2': row[11],
                'description3': row[12], 'description4': row[13], 'count': row[14]
            }
        return None
    
    # DEPRECATED — do not use, kept for backward compatibility
    def search_roles_by_name_all(self, role_name: str) -> List[dict]:
        """Search roles across all games"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE LOWER(role_name) = LOWER(?)", (role_name,))
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'game_number': row[0], 'game_name': row[1], 'role_id': row[2],
            'role_name': row[3], 'team': row[4], 'player_name': row[5],
            'player_id': row[6], 'sponsor_name': row[7], 'sponsor_id': row[8],
            'win': row[9], 'description1': row[10], 'description2': row[11],
            'description3': row[12], 'description4': row[13], 'count': row[14]
        } for row in rows]
    
    def search_roles_by_player_name(self, player_name: str) -> List[dict]:
        """Search roles by player name across all games"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE LOWER(player_name) = LOWER(?)", (player_name,))
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'game_number': row[0], 'game_name': row[1], 'role_id': row[2],
            'role_name': row[3], 'team': row[4], 'player_name': row[5],
            'player_id': row[6], 'sponsor_name': row[7], 'sponsor_id': row[8],
            'win': row[9], 'description1': row[10], 'description2': row[11],
            'description3': row[12], 'description4': row[13], 'count': row[14]
        } for row in rows]

    def search_roles_by_player_id(self, player_id: int) -> List[dict]:
        """Search roles by player ID across all games"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE player_id = ?", (player_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'game_number': row[0], 'game_name': row[1], 'role_id': row[2],
            'role_name': row[3], 'team': row[4], 'player_name': row[5],
            'player_id': row[6], 'sponsor_name': row[7], 'sponsor_id': row[8],
            'win': row[9], 'description1': row[10], 'description2': row[11],
            'description3': row[12], 'description4': row[13], 'count': row[14]
        } for row in rows]

    def search_roles_by_sponsor_name(self, sponsor_name: str) -> List[dict]:
        """Search roles by sponsor name across all games"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE LOWER(sponsor_name) = LOWER(?)", (sponsor_name,))
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'game_number': row[0], 'game_name': row[1], 'role_id': row[2],
            'role_name': row[3], 'team': row[4], 'player_name': row[5],
            'player_id': row[6], 'sponsor_name': row[7], 'sponsor_id': row[8],
            'win': row[9], 'description1': row[10], 'description2': row[11],
            'description3': row[12], 'description4': row[13], 'count': row[14]
        } for row in rows]

    def search_roles_by_sponsor_id(self, sponsor_id: int) -> List[dict]:
        """Search roles by sponsor ID across all games"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE sponsor_id = ?", (sponsor_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'game_number': row[0], 'game_name': row[1], 'role_id': row[2],
            'role_name': row[3], 'team': row[4], 'player_name': row[5],
            'player_id': row[6], 'sponsor_name': row[7], 'sponsor_id': row[8],
            'win': row[9], 'description1': row[10], 'description2': row[11],
            'description3': row[12], 'description4': row[13], 'count': row[14]
        } for row in rows]

    def get_game_players(self, game_number: int):
        """Get all players for a game (counted games only)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT player_name, sponsor_name, team, win
            FROM roles
            WHERE game_number = ?
            AND player_id IS NOT NULL
            AND count = 1
            AND team != 5
            """,
            (game_number,)
        )
        rows = cursor.fetchall()
        conn.close()
        return rows

    
    def get_all_players_stats(self) -> List[dict]:
        """Get stats for all players"""
        conn = sqlite3.connect(self.db_path)
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
                SUM(CASE WHEN team = 4 AND win = 1 THEN 1 ELSE 0 END) AS neutral_wins
            FROM roles 
            WHERE player_id IS NOT NULL 
                AND count = 1
                AND team != 5
            GROUP BY player_id
        """)
        rows = cursor.fetchall()
        
        cursor.execute("""
                SELECT game_number, MIN(player_id) AS player_id
                FROM roles 
                WHERE win = 1 
                AND player_id IS NOT NULL 
                AND count = 1
                AND team != 5
                GROUP BY game_number 
                HAVING COUNT(*) = 1
            """)
        solo_rows = cursor.fetchall()
        conn.close()
        
        solo_map = {}
        for _, pid in solo_rows:
            if pid:
                solo_map[pid] = solo_map.get(pid, 0) + 1
        
        stats = []
        for (pid, pname, games, wins, vg, vw, eg, ew, rg, rw, ng, nw) in rows:
            if not pid:
                continue
            
            games = games or 0
            wins = wins or 0
            stats.append({
                "player_id": pid,
                "player_name": pname or f"User-{pid}",
                "games": games,
                "wins": wins,
                "winrate": (wins / games * 100) if games > 0 else 0.0,
                "village_games": vg or 0,
                "village_wins": vw or 0,
                "village_wr": (vw / vg * 100) if vg > 0 else 0.0,
                "evil_games": eg or 0,
                "evil_wins": ew or 0,
                "evil_wr": (ew / eg * 100) if eg > 0 else 0.0,
                "rk_games": rg or 0,
                "rk_wins": rw or 0,
                "rk_wr": (rw / rg * 100) if rg > 0 else 0.0,
                "neutral_games": ng or 0,
                "neutral_wins": nw or 0,
                "neutral_wr": (nw / ng * 100) if ng > 0 else 0.0,
                "solo_wins": solo_map.get(pid, 0)
            })
        
        return stats
    
    def get_winrate_stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}
        for team_id, team_name in TEAMS.items():
            if team_id == 5:
                continue
            cursor.execute("""
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins
                FROM roles
                WHERE team = ?
                AND count = 1
            """, (team_id,))

            total, wins = cursor.fetchone()
            stats[team_name] = {
                "total": total,
                "wins": wins or 0,
                "winrate": (wins / total * 100) if total else 0.0
            }

        conn.close()
        return stats

    
    def get_player_stats(self, player_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(DISTINCT game_number)
            FROM roles
            WHERE player_id = ? AND count = 1 AND team != 5
        """, (player_id,))
        games_as_player = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(DISTINCT game_number)
            FROM roles
            WHERE sponsor_id = ? AND count = 1 AND team != 5
        """, (player_id,))
        games_as_sponsor = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(DISTINCT game_number)
            FROM roles
            WHERE count = 1 AND team != 5
        """)
        total_games = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM roles
            WHERE player_id = ? AND win = 1 AND count = 1 AND team != 5
        """, (player_id,))
        wins_as_player = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM roles
            WHERE sponsor_id = ? AND win = 1 AND count = 1 AND team != 5
        """, (player_id,))
        wins_as_sponsor = cursor.fetchone()[0]

        team_stats = {}
        for team_id, team_name in TEAMS.items():
            cursor.execute("""
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins
                FROM roles
                WHERE player_id = ?
                AND team = ?
                AND count = 1
                AND team != 5
            """, (player_id, team_id))
            total, wins = cursor.fetchone()
            team_stats[team_name] = {"total": total, "wins": wins or 0}

        conn.close()

        total_participations = games_as_player + games_as_sponsor
        total_wins = wins_as_player + wins_as_sponsor

        return {
            "games_as_player": games_as_player,
            "games_as_sponsor": games_as_sponsor,
            "total_games": total_games,
            "total_participations": total_participations,
            "participation_rate": (total_participations / total_games * 100) if total_games else 0,
            "wins_as_player": wins_as_player,
            "wins_as_sponsor": wins_as_sponsor,
            "total_wins": total_wins,
            "winrate": (total_wins / total_participations * 100) if total_participations else 0,
            "team_stats": team_stats
        }

    
    def get_first_game_played(self, player_id: int):
        """Get first counted game player appeared in"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT game_number, game_name
            FROM roles
            WHERE player_id = ?
            AND count = 1
            AND team != 5
            ORDER BY game_number ASC
            LIMIT 1
            """,
            (player_id,)
        )
        row = cursor.fetchone()
        conn.close()
        return row if row else (None, None)

    
    def get_games_played(self, player_id: int):
        """Get list of counted games player appeared in"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT game_number
            FROM roles
            WHERE player_id = ?
            AND count = 1
            AND team != 5
            ORDER BY game_number ASC
            """,
            (player_id,)
        )
        games = [r[0] for r in cursor.fetchall()]
        conn.close()
        return games


    def get_player_game_history(self, player_id: int):
        """Return full ordered game history for a player."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                game_number,
                game_name,
                role_id,
                role_name,
                team,
                win
            FROM roles
            WHERE player_id = ?
                AND count = 1
                AND team != 5
            ORDER BY game_number ASC
        """, (player_id,))


        rows = cursor.fetchall()
        conn.close()

        history = []
        for gnum, gname, rid, rname, team, win in rows:
            history.append({
                "game_number": gnum,
                "game_name": gname,
                "role_id": rid,
                "role_name": rname,
                "team": team,
                "result": "🏆 Win" if win == 1 else "❌ Loss"
            })

        return history

    def get_top_allies(self, player_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                r2.player_id,
                r2.player_name,
                SUM(CASE WHEN r1.win = 1 AND r2.win = 1 THEN 1 ELSE 0 END) AS wins_together,
                COUNT(*) AS games_together
            FROM roles r1
            JOIN roles r2 ON r1.game_number = r2.game_number
            WHERE r1.player_id = ?
            AND r2.player_id != r1.player_id
            AND r1.team = r2.team
            AND r1.count = 1 AND r2.count = 1
            AND r1.team != 5
            AND r2.team != 5
            GROUP BY r2.player_id, r2.player_name
            HAVING wins_together > 0
            ORDER BY wins_together DESC, games_together ASC
            LIMIT 3
        """, (player_id,))

        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_top_allies2(self, player_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        MIN_SAMPLE = 5
        TOP_N = 5

        # Total games YOU played (as player only)
        cursor.execute("""
            SELECT COUNT(DISTINCT game_number)
            FROM roles
            WHERE player_id = ?
            AND count = 1
            AND team != 5
        """, (player_id,))
        total_games = cursor.fetchone()[0] or 0

        if total_games == 0:
            conn.close()
            return []

        threshold = math.ceil(total_games * 0.15)

        cursor.execute("""
            SELECT 
                r2.player_id,
                r2.player_name,
                SUM(CASE WHEN r1.win = 1 AND r2.win = 1 THEN 1 ELSE 0 END) AS wins_together,
                COUNT(*) AS games_together
            FROM roles r1
            JOIN roles r2 
                ON r1.game_number = r2.game_number
            WHERE r1.player_id = ?
            AND r2.player_id != r1.player_id
            AND r1.team = r2.team
            AND r1.count = 1
            AND r2.count = 1
            AND r1.team != 5
            AND r2.team != 5
            GROUP BY r2.player_id, r2.player_name
        """, (player_id,))

        rows = cursor.fetchall()
        conn.close()

        strong = []
        backup = []
        tiny = []

        for pid, pname, wins, games in rows:
            if games <= 0:
                continue

            wr = wins / games
            row_data = (pid, pname, wins, games, wr)

            if wins >= threshold:
                strong.append(row_data)
            elif games >= MIN_SAMPLE:
                backup.append(row_data)
            else:
                tiny.append(row_data)

        strong.sort(key=lambda x: (x[4], x[3]), reverse=True)
        backup.sort(key=lambda x: (x[4], x[3]), reverse=True)
        tiny.sort(key=lambda x: (x[4], x[3]), reverse=True)


        result = strong

        if len(result) < TOP_N:
            result.extend(backup[:TOP_N - len(result)])

        if len(result) < TOP_N:
            result.extend(tiny[:TOP_N - len(result)])

        return result[:TOP_N]

    def get_worst_allies2(self, player_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        MIN_SAMPLE = 5
        TOP_N = 5

        # Total games YOU played (as player only)
        cursor.execute("""
            SELECT COUNT(DISTINCT game_number)
            FROM roles
            WHERE player_id = ?
            AND count = 1
            AND team != 5
        """, (player_id,))
        total_games = cursor.fetchone()[0] or 0

        if total_games == 0:
            conn.close()
            return []

        threshold = math.ceil(total_games * 0.15)

        cursor.execute("""
            SELECT 
                r2.player_id,
                r2.player_name,
                SUM(CASE WHEN r1.win = 1 AND r2.win = 1 THEN 1 ELSE 0 END) AS wins_together,
                COUNT(*) AS games_together
            FROM roles r1
            JOIN roles r2 
                ON r1.game_number = r2.game_number
            WHERE r1.player_id = ?
            AND r2.player_id != r1.player_id
            AND r1.team = r2.team
            AND r1.count = 1
            AND r2.count = 1
            AND r1.team != 5
            AND r2.team != 5
            GROUP BY r2.player_id, r2.player_name
        """, (player_id,))

        rows = cursor.fetchall()
        conn.close()

        strong = []
        backup = []
        tiny = []

        for pid, pname, wins, games in rows:
            if games <= 0:
                continue

            wr = wins / games
            row_data = (pid, pname, wins, games, wr)

            # Worst ally = strong if MANY losses (reverse threshold)
            if (games - wins) >= threshold:
                strong.append(row_data)
            elif games >= MIN_SAMPLE:
                backup.append(row_data)
            else:
                tiny.append(row_data)

        # 🔥 Reverse sorting (lowest WR first)
        strong.sort(key=lambda x: (x[4], -x[3]))
        backup.sort(key=lambda x: (x[4], -x[3]))
        tiny.sort(key=lambda x: (x[4], -x[3]))

        result = strong

        if len(result) < TOP_N:
            result.extend(backup[:TOP_N - len(result)])

        if len(result) < TOP_N:
            result.extend(tiny[:TOP_N - len(result)])

        return result[:TOP_N]


    def get_top_nemeses2(self, player_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        MIN_SAMPLE = 5
        TOP_N = 5

        cursor.execute("""
            SELECT COUNT(DISTINCT game_number)
            FROM roles
            WHERE player_id = ?
            AND count = 1
            AND team != 5
        """, (player_id,))
        total_games = cursor.fetchone()[0] or 0

        if total_games == 0:
            conn.close()
            return []

        threshold = math.ceil(total_games * 0.15)

        cursor.execute("""
            SELECT 
                r2.player_id,
                r2.player_name,
                SUM(CASE WHEN r2.win = 1 AND r1.win = 0 THEN 1 ELSE 0 END) AS losses_to,
                COUNT(*) AS games_together
            FROM roles r1
            JOIN roles r2 
                ON r1.game_number = r2.game_number
            WHERE r1.player_id = ?
            AND r2.player_id != r1.player_id
            AND r1.team != r2.team
            AND r1.count = 1
            AND r2.count = 1
            AND r1.team != 5
            AND r2.team != 5
            GROUP BY r2.player_id, r2.player_name
        """, (player_id,))

        rows = cursor.fetchall()
        conn.close()

        strong = []
        backup = []
        tiny = []

        for pid, pname, losses, games in rows:
            if games <= 0:
                continue

            lr = losses / games
            row_data = (pid, pname, losses, games, lr)

            if losses >= threshold:
                strong.append(row_data)
            elif games >= MIN_SAMPLE:
                backup.append(row_data)
            else:
                tiny.append(row_data)

        strong.sort(key=lambda x: (x[4], x[3]), reverse=True)
        backup.sort(key=lambda x: (x[4], x[3]), reverse=True)
        tiny.sort(key=lambda x: (x[4], x[3]), reverse=True)

        result = strong

        if len(result) < TOP_N:
            result.extend(backup[:TOP_N - len(result)])

        if len(result) < TOP_N:
            result.extend(tiny[:TOP_N - len(result)])

        return result[:TOP_N]



    def get_top_nemeses(self, player_id: int):
        conn = sqlite3.connect(self.db_path)
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
            AND r1.team != 5
            AND r2.team != 5
            GROUP BY r2.player_id, r2.player_name
            HAVING losses_to > 0
            ORDER BY losses_to DESC, games_together ASC
            LIMIT 3
        """, (player_id,))

        rows = cursor.fetchall()
        conn.close()
        return rows
    
    def search_roles_fuzzy(self, query: str, limit: int = 25) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        q = f"%{query.lower()}%"
        cursor.execute("""
            SELECT *
            FROM roles
            WHERE (
                LOWER(role_name) LIKE ?
                OR LOWER(player_name) LIKE ?
                OR LOWER(sponsor_name) LIKE ?
            )
            ORDER BY game_number DESC
            LIMIT ?
        """, (q, q, q, limit))


        rows = cursor.fetchall()
        conn.close()

        return [{
            'game_number': row[0], 'game_name': row[1], 'role_id': row[2],
            'role_name': row[3], 'team': row[4], 'player_name': row[5],
            'player_id': row[6], 'sponsor_name': row[7], 'sponsor_id': row[8],
            'win': row[9], 'description1': row[10], 'description2': row[11],
            'description3': row[12], 'description4': row[13], 'count': row[14]
        } for row in rows]

    def get_game_summary(self, game_number: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Count roles per team
        cursor.execute("""
            SELECT team, COUNT(*)
            FROM roles
            WHERE game_number = ?
            GROUP BY team
        """, (game_number,))
        team_counts = dict(cursor.fetchall())

        # Total roles
        cursor.execute("""
            SELECT COUNT(*)
            FROM roles
            WHERE game_number = ?
        """, (game_number,))
        total_roles = cursor.fetchone()[0]

        # Winning teams
        cursor.execute("""
            SELECT DISTINCT team
            FROM roles
            WHERE game_number = ?
            AND win = 1
        """, (game_number,))
        winning_teams = [row[0] for row in cursor.fetchall()]

        conn.close()

        return {
            "team_counts": team_counts,
            "total_roles": total_roles,
            "winning_teams": winning_teams
        }

    def get_hosts_for_game(self, game_number: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT host_name
            FROM game_hosts
            WHERE game_number = ?
            AND count = 1
        """, (game_number,))

        rows = cursor.fetchall()
        conn.close()

        return [r[0] for r in rows]
    


# ============================================================================
# UI VIEWS
# ============================================================================

class GameSelectView(discord.ui.View):
    """View for selecting a game"""
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
            color=EMBED_COLOR
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


class GameNumberModal(discord.ui.Modal, title="Enter Game Number"):
    """Modal for entering game number"""
    def __init__(self, games: List[Tuple[int, str]], db):
        super().__init__()
        self.games = games
        self.db = db
    
    game_number = discord.ui.TextInput(
        label="Game Number",
        placeholder="Enter the game number...",
        required=True,
        max_length=5
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            game_num = int(self.game_number.value)
            game_data = next((g for g in self.games if g[0] == game_num), None)
            
            if game_data:
                view = TeamSelectView(game_num, game_data[1], self.db)
                embed = view.get_embed()
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                await interaction.response.send_message("❌ Game not found! Please enter a valid game number.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class TeamSelectView(discord.ui.View):
    """View for selecting team and browsing roles"""
    def __init__(self, game_number: int, game_name: str, db, selected_team: int = 1, page: int = 0):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.selected_team = selected_team
        self.db = db
        self.page = page
        self.roles_per_page = 20
        
        roles = self.db.get_roles_by_team(self.game_number, self.selected_team)
        self.max_page = max(0, math.ceil(len(roles) / self.roles_per_page) - 1)
        
        if self.max_page > 0:
            self.prev_btn = discord.ui.Button(label="◀ Prev Page", style=discord.ButtonStyle.secondary, disabled=(self.page == 0), row=1)
            self.prev_btn.callback = self.prev_page
            self.add_item(self.prev_btn)
            
            self.next_btn = discord.ui.Button(label="Next Page ▶", style=discord.ButtonStyle.secondary, disabled=(self.page == self.max_page), row=1)
            self.next_btn.callback = self.next_page
            self.add_item(self.next_btn)
    
    def get_embed(self) -> discord.Embed:
        roles_basic = self.db.get_roles_by_team(self.game_number, self.selected_team)
        
        embed = discord.Embed(
            title=f"🎮 {self.game_name.replace('-', ' ').title()}",
            description=f"**Team: {TEAMS[self.selected_team]}**\n\nSelect a team from the dropdown or enter a role ID below.",
            color=EMBED_COLOR
        )
        
        if roles_basic:
            start_idx = self.page * self.roles_per_page
            end_idx = min(start_idx + self.roles_per_page, len(roles_basic))
            page_roles = roles_basic[start_idx:end_idx]
            
            roles_text = ""
            for role_id, role_name, player_name in page_roles:
                role_details = self.db.get_role_details(self.game_number, role_id)
                win_emoji = "🏆" if role_details and role_details['win'] else "❌"
                player_str = f" - {player_name} {win_emoji}" if player_name else ""
                roles_text += f"**{role_id}** - {role_name}{player_str}\n"
            
            field_name = f"Roles ({start_idx + 1}-{end_idx} of {len(roles_basic)})" if len(roles_basic) > self.roles_per_page else "Roles"
            embed.add_field(name=field_name, value=roles_text, inline=False)
        else:
            embed.add_field(name="Roles", value="*No roles found for this team.*", inline=False)
        
        footer_text = EMBED_FOOTER_TEXT
        if self.max_page > 0:
            footer_text += f" | Page {self.page + 1}/{self.max_page + 1}"
        embed.set_footer(text=footer_text, icon_url=EMBED_FOOTER_ICON)
        
        return embed
    
    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            await self.rebuild_view(interaction)
    
    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.max_page:
            self.page += 1
            await self.rebuild_view(interaction)
    
    async def rebuild_view(self, interaction: discord.Interaction):
        new_view = TeamSelectView(self.game_number, self.game_name, self.db, self.selected_team, self.page)
        embed = new_view.get_embed()
        await interaction.response.edit_message(embed=embed, view=new_view)
    
    @discord.ui.select(
        placeholder="Select a team...",
        options=[
            discord.SelectOption(label="Village", value="1", emoji="🏘️"),
            discord.SelectOption(label="Evil", value="2", emoji="😈"),
            discord.SelectOption(label="Random Killer", value="3", emoji="🔪"),
            discord.SelectOption(label="Neutral", value="4", emoji="⚖️"),
            discord.SelectOption(label="Bonus/Extra", value="5", emoji="⭐"),
        ],
        row=0
    )
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_team = int(select.values[0])
        self.page = 0
        new_view = TeamSelectView(self.game_number, self.game_name, self.db, self.selected_team, 0)
        embed = new_view.get_embed()
        await interaction.response.edit_message(embed=embed, view=new_view)
    
    @discord.ui.button(label="🔢 Enter Role ID", style=discord.ButtonStyle.primary, row=2)
    async def enter_role_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RoleIDModal(self.game_number, self.game_name, self.db)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="👥 Show Players", style=discord.ButtonStyle.success, row=2)
    async def show_players(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = GamePlayersView(self.game_number, self.game_name, self.db, self.selected_team)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)
    
    @discord.ui.button(label="↩️ Back to Games", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        games = self.db.get_all_games()
        view = GameSelectView(games, self.db)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class GamePlayersView(discord.ui.View):
    """View for displaying game players"""
    def __init__(self, game_number: int, game_name: str, db, previous_team: int = 1, selected_filter: str = "all"):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.db = db
        self.previous_team = previous_team
        self.selected_filter = selected_filter
    
    def get_embed(self) -> discord.Embed:
        players_data = self.db.get_game_players(self.game_number)
        
        embed = discord.Embed(
            title=f"👥 {self.game_name.replace('-', ' ').title()} - Players",
            color=EMBED_COLOR
        )
        
        if self.selected_filter == "all":
            winners = []
            losers = []
            
            for player_name, sponsor_name, team, win in players_data:
                team_name = TEAMS.get(team, "Unknown")
                display = f"{player_name} (player) + {sponsor_name} (sponsor) - {team_name}" if sponsor_name else f"{player_name} - {team_name}"
                
                if win == 1:
                    winners.append(display)
                else:
                    losers.append(display)
            
            winners_text = "\n".join(winners) if winners else "*No winners*"
            losers_text = "\n".join(losers) if losers else "*No losers*"
            
            embed.add_field(name="🏆 Winners", value=winners_text, inline=False)
            embed.add_field(name="❌ Losers", value=losers_text, inline=False)
        else:
            team_id = int(self.selected_filter)
            team_name = TEAMS.get(team_id, "Unknown")
            
            team_players = []
            for player_name, sponsor_name, team, win in players_data:
                if team == team_id:
                    win_emoji = "🏆" if win == 1 else "❌"
                    display = f"{win_emoji} {player_name} (player) + {sponsor_name} (sponsor)" if sponsor_name else f"{win_emoji} {player_name}"
                    team_players.append(display)
            
            players_text = "\n".join(team_players) if team_players else "*No players on this team*"
            embed.add_field(name=f"{team_name} Team", value=players_text, inline=False)
        
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
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
        row=0
    )
    async def filter_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_filter = select.values[0]
        embed = self.get_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="↩️ Back to Roles", style=discord.ButtonStyle.secondary, row=1)
    async def back_to_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TeamSelectView(self.game_number, self.game_name, self.db, selected_team=self.previous_team)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class RoleIDModal(discord.ui.Modal, title="Enter Role ID"):
    """Modal for entering role ID"""
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
                embed = view.get_embed()
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                await interaction.response.send_message("❌ Role not found! Please enter a valid role ID.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class RoleDescriptionView(discord.ui.View):
    """View for displaying role descriptions"""
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
        """Update available descriptions"""
        role_data = self.get_role_data()
        self.available_descs = []
        
        for i in range(1, 5):
            desc = role_data.get(f'description{i}')
            if desc and str(desc).strip():
                self.available_descs.append(i)
        
        if not self.available_descs:
            self.available_descs = [1]
        
        if self.current_desc not in self.available_descs:
            self.current_desc = self.available_descs[0]
    
    def get_role_data(self):
        role_id = self.roles[self.current_index][0]
        return self.db.get_role_details(self.game_number, role_id)
    
    def get_embed(self) -> discord.Embed:
        role = self.get_role_data()
        description = role.get(f'description{self.current_desc}', "*No description available.*")
        
        if not description or not str(description).strip():
            description = "*No description available.*"
        
        embed = discord.Embed(title=f"📜 {role['role_name']}", description=description, color=EMBED_COLOR)
        
        info_text = f"**Game:** {self.game_name.replace('-', ' ').title()}\n"
        info_text += f"**Role ID:** {role['role_id']}\n"
        info_text += f"**Team:** {TEAMS[role['team']]}\n"
        
        if role.get('player_name'):
            info_text += f"**Player:** {role['player_name']}\n"
        if role.get('sponsor_name'):
            info_text += f"**Sponsor:** {role['sponsor_name']}\n"
        
        win_status = "✅ Winner" if role['win'] else "❌ Loss"
        info_text += f"**Result:** {win_status}"
        
        embed.add_field(name="Role Information", value=info_text, inline=False)
        
        max_desc = max(self.available_descs) if self.available_descs else 1
        footer_text = f"{EMBED_FOOTER_TEXT} | Description {self.current_desc}/{max_desc} | Role {self.current_index + 1}/{len(self.roles)}"
        embed.set_footer(text=footer_text, icon_url=EMBED_FOOTER_ICON)
        
        return embed
    
    @discord.ui.button(label="◀ Desc", style=discord.ButtonStyle.primary, row=0)
    async def prev_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_idx = self.available_descs.index(self.current_desc)
        if current_idx > 0:
            self.current_desc = self.available_descs[current_idx - 1]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    @discord.ui.button(label="Desc ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_idx = self.available_descs.index(self.current_desc)
        if current_idx < len(self.available_descs) - 1:
            self.current_desc = self.available_descs[current_idx + 1]
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
        view = TeamSelectView(self.game_number, self.game_name, self.db, selected_team=current_role['team'])
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class LeaderboardView(discord.ui.View):
    """Leaderboard view"""
    def __init__(self, stats, min_games: int = 10, sort_mode: str = "winrate", page: int = 0):
        super().__init__(timeout=300)
        self.raw_stats = stats
        self.min_games = min_games
        self.sort_mode = sort_mode
        self.page = page
        self.page_size = 10
    
    def get_sorted_players(self) -> List[dict]:
        players = [p for p in self.raw_stats if p["games"] >= self.min_games]

        if self.sort_mode == "games":
            key = lambda p: (-p["games"], -p["wins"], -p["winrate"])
        elif self.sort_mode == "village_wr":
            key = lambda p: (-p.get("village_wr", 0.0), -p.get("village_wins", 0), -p.get("village_games", 0))
        elif self.sort_mode == "evil_wr":
            key = lambda p: (-p.get("evil_wr", 0.0), -p.get("evil_wins", 0), -p.get("evil_games", 0))
        elif self.sort_mode == "rk_wr":
            key = lambda p: (-p.get("rk_wr", 0.0), -p.get("rk_wins", 0), -p.get("rk_games", 0))
        elif self.sort_mode == "neutral_wr":
            key = lambda p: (-p.get("neutral_wr", 0.0), -p.get("neutral_wins", 0), -p.get("neutral_games", 0))
        elif self.sort_mode == "solo_wins":
            key = lambda p: (-p.get("solo_wins", 0), -p["wins"], -p["games"])
        elif self.sort_mode == "name":
            key = lambda p: p["player_name"].lower()
        else:
            key = lambda p: (-p["winrate"], -p["wins"], -p["games"])

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
        if self.page > max_page:
            self.page = max_page
        
        start = self.page * self.page_size
        end = start + self.page_size
        page_players = players[start:end]
        
        desc_lines = []
        for idx, p in enumerate(page_players, start=start + 1):
            line = f"**#{idx} — {p['player_name']}**\n"
            line += f"Games: {p['games']} | Wins: {p['wins']} | WR: {p['winrate']:.1f}%\n"
            
            if self.sort_mode == "village_wr":
                line += f"Village WR: {p.get('village_wr', 0.0):.1f}% ({p.get('village_wins', 0)}W / {p.get('village_games', 0)}G)\n"
            elif self.sort_mode == "evil_wr":
                line += f"Evil WR: {p.get('evil_wr', 0.0):.1f}% ({p.get('evil_wins', 0)}W / {p.get('evil_games', 0)}G)\n"
            elif self.sort_mode == "rk_wr":
                line += f"RK WR: {p.get('rk_wr', 0.0):.1f}% ({p.get('rk_wins', 0)}W / {p.get('rk_games', 0)}G)\n"
            elif self.sort_mode == "neutral_wr":
                line += f"Neutral WR: {p.get('neutral_wr', 0.0):.1f}% ({p.get('neutral_wins', 0)}W / {p.get('neutral_games', 0)}G)\n"
            elif self.sort_mode == "solo_wins":
                line += f"Solo Wins: {p.get('solo_wins', 0)}\n"
            
            desc_lines.append(line)
        
        embed.description = "\n".join(desc_lines)
        
        sort_labels = {
            "winrate": "Winrate",
            "name": "Alphabetical",
            "games": "Games Played", 
            "village_wr": "Village Winrate",
            "evil_wr": "Evil Winrate", 
            "rk_wr": "RK Winrate", 
            "neutral_wr": "Neutral Winrate", 
            "solo_wins": "Solo Wins"
        }
        sort_label = sort_labels.get(self.sort_mode, "Winrate")
        footer = f"{EMBED_FOOTER_TEXT} | {self.min_games}+ games | Sorted by {sort_label} | Page {self.page + 1}/{max_page + 1}"
        embed.set_footer(text=footer, icon_url=EMBED_FOOTER_ICON)
        
        return embed
    
    @discord.ui.select(
        placeholder="Sort by...",
        options=[
            discord.SelectOption(label="Winrate", value="winrate"),
            discord.SelectOption(label="Alphabetical (A–Z)", value="name"),
            discord.SelectOption(label="Games Played", value="games"),
            discord.SelectOption(label="Village Winrate", value="village_wr"),
            discord.SelectOption(label="Evil Winrate", value="evil_wr"),
            discord.SelectOption(label="RK Winrate", value="rk_wr"),
            discord.SelectOption(label="Neutral Winrate", value="neutral_wr"),
            discord.SelectOption(label="Solo Wins", value="solo_wins"),
        ],
        row=0
    )
    async def sort_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.sort_mode = select.values[0]
        self.page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    @discord.ui.button(label="🔢 Set Min Games", style=discord.ButtonStyle.primary, row=1)
    async def set_min_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = MinGamesModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="◀ Prev Page", style=discord.ButtonStyle.secondary, row=2)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    @discord.ui.button(label="Next Page ▶", style=discord.ButtonStyle.secondary, row=2)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        players = self.get_sorted_players()
        max_page = max(0, (len(players) - 1) // self.page_size)
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
        end = start + self.page_size
        items = self.history[start:end]

        embed = discord.Embed(
            title=f"📜 Game History — {self.player_name}",
            color=EMBED_COLOR
        )

        if not items:
            embed.description = "*No games found.*"
            return embed

        desc = ""
        for h in items:
            desc += (
                f"**Game {h['game_number']} — {h['game_name'].replace('-', ' ').title()}**\n"
                f"• Role: {h['role_name']} (ID: {h['role_id']})\n"
                f"• Team: {TEAMS.get(h['team'], 'Unknown')}\n"
                f"• Result: {h['result']}\n\n"
            )

        embed.description = desc
        embed.set_footer(text=f"Page {self.page+1}/{total_pages}")

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
    """Modal for minimum games filter"""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        self.min_games_input = discord.ui.TextInput(
            label="Minimum Games",
            placeholder="Enter minimum number of games (e.g., 10)...",
            required=True,
            max_length=3,
            default=str(parent_view.min_games)
        )
        self.add_item(self.min_games_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            min_games_value = int(self.min_games_input.value)
            if min_games_value < 0 or min_games_value > 1000:
                await interaction.response.send_message("❌ Minimum games must be between 0 and 1000!", ephemeral=True)
                return
            
            self.parent_view.min_games = min_games_value
            self.parent_view.page = 0
            embed = self.parent_view.get_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent_view)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class InteractiveSearchView(discord.ui.View):
    """Interactive search view"""
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
        row=0
    )
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_team = int(select.values[0])
        await interaction.response.send_message(
            f"✅ Selected team: {TEAMS[self.selected_team]}\nNow enter a game number or role name using the buttons below.",
            ephemeral=True
        )
    
    @discord.ui.button(label="🔢 Enter Game Number", style=discord.ButtonStyle.primary, row=1)
    async def enter_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SearchGameModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="📝 Enter Role Name", style=discord.ButtonStyle.primary, row=1)
    async def enter_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SearchRoleModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="👤 Enter Player Name", style=discord.ButtonStyle.primary, row=2)
    async def enter_player_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SearchPlayerNameModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🆔 Enter Player ID", style=discord.ButtonStyle.primary, row=2)
    async def enter_player_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SearchPlayerIDModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="💼 Enter Sponsor Name", style=discord.ButtonStyle.primary, row=3)
    async def enter_sponsor_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SearchSponsorNameModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔖 Enter Sponsor ID", style=discord.ButtonStyle.primary, row=3)
    async def enter_sponsor_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SearchSponsorIDModal(self)
        await interaction.response.send_modal(modal)


class SearchGameModal(discord.ui.Modal, title="Enter Game Number"):
    """Modal for searching by game"""
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
                embed = view.get_embed()
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                await interaction.response.send_message("❌ Game not found!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class SearchRoleModal(discord.ui.Modal, title="Enter Role Name"):
    """Modal for searching by role name (fuzzy)"""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    role_name = discord.ui.TextInput(
        label="Role Name (partial or typo OK)",
        placeholder="e.g. doctor, doc, vig, kill...",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        query = self.role_name.value.strip()

        # 🔥 SINGLE SOURCE OF TRUTH
        all_roles = self.parent_view.db.search_roles_fuzzy(query)
        def score(name):
            return SequenceMatcher(None, query.lower(), (name or "").lower()).ratio()


        all_roles.sort(
            key=lambda r: max(
                score(r['role_name']),
                score(r['player_name'] or ""),
                score(r['sponsor_name'] or "")
            ),
            reverse=True
        )



        # Optional team filter
        if self.parent_view.selected_team:
            all_roles = [r for r in all_roles if r['team'] == self.parent_view.selected_team]

        if not all_roles:
            await interaction.response.send_message(
                f"❌ No roles matching '{query}' found.",
                ephemeral=True
            )
            return

        # One result → jump directly
        if len(all_roles) == 1:
            role = all_roles[0]
            roles = self.parent_view.db.get_roles_by_team(role['game_number'], role['team'])
            index = next(i for i, r in enumerate(roles) if r[0] == role['role_id'])

            view = RoleDescriptionView(
                role['game_number'],
                role['game_name'],
                roles,
                index,
                self.parent_view.db
            )
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
            return

        # Multiple → selection list
        view = RoleSelectionView(all_roles, self.parent_view.db)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)



class SearchPlayerNameModal(discord.ui.Modal, title="Enter Player Name"):
    """Modal for searching by player name"""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    
    player_name = discord.ui.TextInput(label="Player Name", placeholder="Enter player name...", required=True, max_length=100)
    
    async def on_submit(self, interaction: discord.Interaction):
        player_name = self.player_name.value
        all_roles = self.parent_view.db.search_roles_by_player_name(player_name)
        
        if self.parent_view.selected_team:
            filtered_roles = [r for r in all_roles if r['team'] == self.parent_view.selected_team]
        else:
            filtered_roles = all_roles
        
        if not filtered_roles:
            await interaction.response.send_message(f"❌ No roles found for player '{player_name}'!", ephemeral=True)
            return
        
        if len(filtered_roles) == 1:
            role = filtered_roles[0]
            roles = self.parent_view.db.get_roles_by_team(role['game_number'], role['team'])
            index = next(i for i, r in enumerate(roles) if r[0] == role['role_id'])
            view = RoleDescriptionView(role['game_number'], role['game_name'], roles, index, self.parent_view.db)
            embed = view.get_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            view = RoleSelectionView(filtered_roles, self.parent_view.db)
            embed = view.get_embed()
            await interaction.response.edit_message(embed=embed, view=view)


class SearchPlayerIDModal(discord.ui.Modal, title="Enter Player ID"):
    """Modal for searching by player ID"""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    
    player_id = discord.ui.TextInput(label="Player ID", placeholder="Enter player ID...", required=True, max_length=20)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            pid = int(self.player_id.value)
            all_roles = self.parent_view.db.search_roles_by_player_id(pid)
            
            if self.parent_view.selected_team:
                filtered_roles = [r for r in all_roles if r['team'] == self.parent_view.selected_team]
            else:
                filtered_roles = all_roles
            
            if not filtered_roles:
                await interaction.response.send_message(f"❌ No roles found for player ID '{pid}'!", ephemeral=True)
                return
            
            if len(filtered_roles) == 1:
                role = filtered_roles[0]
                roles = self.parent_view.db.get_roles_by_team(role['game_number'], role['team'])
                index = next(i for i, r in enumerate(roles) if r[0] == role['role_id'])
                view = RoleDescriptionView(role['game_number'], role['game_name'], roles, index, self.parent_view.db)
                embed = view.get_embed()
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                view = RoleSelectionView(filtered_roles, self.parent_view.db)
                embed = view.get_embed()
                await interaction.response.edit_message(embed=embed, view=view)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid player ID!", ephemeral=True)


class SearchSponsorNameModal(discord.ui.Modal, title="Enter Sponsor Name"):
    """Modal for searching by sponsor name"""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    
    sponsor_name = discord.ui.TextInput(label="Sponsor Name", placeholder="Enter sponsor name...", required=True, max_length=100)
    
    async def on_submit(self, interaction: discord.Interaction):
        sponsor_name = self.sponsor_name.value
        all_roles = self.parent_view.db.search_roles_by_sponsor_name(sponsor_name)
        
        if self.parent_view.selected_team:
            filtered_roles = [r for r in all_roles if r['team'] == self.parent_view.selected_team]
        else:
            filtered_roles = all_roles
        
        if not filtered_roles:
            await interaction.response.send_message(f"❌ No roles found for sponsor '{sponsor_name}'!", ephemeral=True)
            return
        
        if len(filtered_roles) == 1:
            role = filtered_roles[0]
            roles = self.parent_view.db.get_roles_by_team(role['game_number'], role['team'])
            index = next(i for i, r in enumerate(roles) if r[0] == role['role_id'])
            view = RoleDescriptionView(role['game_number'], role['game_name'], roles, index, self.parent_view.db)
            embed = view.get_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            view = RoleSelectionView(filtered_roles, self.parent_view.db)
            embed = view.get_embed()
            await interaction.response.edit_message(embed=embed, view=view)


class SearchSponsorIDModal(discord.ui.Modal, title="Enter Sponsor ID"):
    """Modal for searching by sponsor ID"""
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    
    sponsor_id = discord.ui.TextInput(label="Sponsor ID", placeholder="Enter sponsor ID...", required=True, max_length=20)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            sid = int(self.sponsor_id.value)
            all_roles = self.parent_view.db.search_roles_by_sponsor_id(sid)
            
            if self.parent_view.selected_team:
                filtered_roles = [r for r in all_roles if r['team'] == self.parent_view.selected_team]
            else:
                filtered_roles = all_roles
            
            if not filtered_roles:
                await interaction.response.send_message(f"❌ No roles found for sponsor ID '{sid}'!", ephemeral=True)
                return
            
            if len(filtered_roles) == 1:
                role = filtered_roles[0]
                roles = self.parent_view.db.get_roles_by_team(role['game_number'], role['team'])
                index = next(i for i, r in enumerate(roles) if r[0] == role['role_id'])
                view = RoleDescriptionView(role['game_number'], role['game_name'], roles, index, self.parent_view.db)
                embed = view.get_embed()
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                view = RoleSelectionView(filtered_roles, self.parent_view.db)
                embed = view.get_embed()
                await interaction.response.edit_message(embed=embed, view=view)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid sponsor ID!", ephemeral=True)
            

class RoleSelectionView(discord.ui.View):
    """View for selecting from multiple roles"""
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
            color=EMBED_COLOR
        )
        
        roles_text = ""
        for idx, role in enumerate(page_roles, start=start_idx + 1):
            game_name = role['game_name'].replace('-', ' ').title()
            team = TEAMS[role['team']]
            player = role.get('player_name', 'Unknown')
            roles_text += f"**{idx}.** Game {role['game_number']} ({game_name}) - {team} - {player}\n"
        
        embed.add_field(name="Roles", value=roles_text, inline=False)
        
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
        modal = RoleSelectionModal(self.roles, self.db)
        await interaction.response.send_modal(modal)


class RoleSelectionModal(discord.ui.Modal, title="Select Role"):
    """Modal for selecting role from list"""
    def __init__(self, roles: List[dict], db):
        super().__init__()
        self.roles = roles
        self.db = db
    
    selection = discord.ui.TextInput(label="Selection Number", placeholder="Enter the number of the role...", required=True, max_length=5)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            idx = int(self.selection.value) - 1
            
            if 0 <= idx < len(self.roles):
                role = self.roles[idx]
                team_roles = self.db.get_roles_by_team(role['game_number'], role['team'])
                role_index = next(i for i, r in enumerate(team_roles) if r[0] == role['role_id'])
                view = RoleDescriptionView(role['game_number'], role['game_name'], team_roles, role_index, self.db)
                embed = view.get_embed()
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                await interaction.response.send_message("❌ Invalid selection number!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)


class StatsView(discord.ui.View):
    """View with leaderboard button"""
    def __init__(self, db, target_member: discord.Member):
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
        embed = view.get_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @discord.ui.button(label="📜 View Game History", style=discord.ButtonStyle.secondary)
    async def show_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        history = self.db.get_player_game_history(self.target.id)

        if not history:
            await interaction.response.send_message(
                "📜 No recorded game history.",
                ephemeral=True
            )
            return

        view = GameHistoryView(history, self.target.display_name)
        embed = view.get_embed()

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=False
        )



class MissingIDPageView(discord.ui.View):
    def __init__(self, cog, missing_players, page=0):
        super().__init__(timeout=300)
        self.cog = cog
        self.missing = sorted(missing_players, key=lambda x: x.lower())  # alphabetical
        self.page = page
        self.page_size = 25
        self.max_page = (len(self.missing) - 1) // self.page_size

        # Build dropdown for this page
        start = page * self.page_size
        end = start + self.page_size
        
        page_names = self.missing[start:end]

        # Dropdown options
        options = [
            discord.SelectOption(label=name, value=name)
            for name in page_names
        ]

        self.dropdown = discord.ui.Select(
            placeholder=f"Select player ({len(self.missing)} total)",
            min_values=1,
            max_values=1,
            options=options
        )
        self.dropdown.callback = self.select_player
        self.add_item(self.dropdown)

        # Pagination buttons
        if page > 0:
            prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

        if page < self.max_page:
            next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        # Store visible names for embed rendering
        self.visible_names = page_names

    async def select_player(self, interaction: discord.Interaction):
        selected_name = self.dropdown.values[0]
        await interaction.response.send_modal(AssignIDModal(self.cog, selected_name))

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
        except:
            await interaction.response.send_message("❌ Invalid ID.", ephemeral=True)
            return

        conn = sqlite3.connect(self.cog.db.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE roles
            SET player_id = ?
            WHERE LOWER(player_name) = LOWER(?) AND (player_id IS NULL OR player_id = 0)
        """, (new_id, self.player_name))

        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"✅ Updated **{self.player_name}** → `{new_id}`",
            ephemeral=False
        )


# ============================================================================
# COMMANDS COG
# ============================================================================

class GameLibrary(commands.Cog):
    """Main cog for game library"""
    def __init__(self, bot):
        self.bot = bot
        self.db = LibraryDatabase()
    
    def is_librarian(self, user_id: int) -> bool:
        return user_id in LIBRARIAN_IDS
    
    def generate_missingid_embed(self, names, page, max_page):
        listed = "\n".join([f"• {n}" for n in names])
        embed = discord.Embed(
            title="Players Missing Discord IDs",
            description=f"Page **{page+1}/{max_page+1}**\n\n{listed}",
            color=EMBED_COLOR
        )
        return embed
    
    def get_game_info_from_channel(self, channel: discord.TextChannel) -> Optional[Tuple[int, str]]:
        if not channel.category or channel.category.name != "📖 Library B":
            return None
        
        try:
            parts = channel.name.split("│", 1)
            if len(parts) == 2:
                game_number = int(parts[0].strip())
                game_name = parts[1].strip()
                return (game_number, game_name)
        except (ValueError, AttributeError):
            pass
        
        return None
    
    @commands.group(name="lib", invoke_without_command=True)
    async def lib(self, ctx):
        """Browse game library"""
        games = self.db.get_all_games()
        if not games:
            await ctx.send("❌ The library is empty!")
            return
        
        view = GameSelectView(games, self.db)
        embed = view.get_embed()
        await ctx.send(embed=embed, view=view)

    @lib.command(name="add")
    async def lib_add(self, ctx, role_name: str, team: Optional[int] = None, *args):
        """
        Usage:

        ROLE:
        .lib add <role_name> <team> [@player] [@sponsor]

        HOST:
        .lib add host @host1 @host2 ...
        """

        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission to use this command!")
            return

        game_info = self.get_game_info_from_channel(ctx.channel)
        if not game_info:
            await ctx.send("❌ This command must be used in a Library game channel!")
            return

        game_number, game_name = game_info

        # ==========================================================
        # HOST MODE
        # ==========================================================
        if role_name.lower() == "host":
            mention_pattern = r'<@!?(\d+)>'
            mention_ids = [int(i) for i in re.findall(mention_pattern, ctx.message.content)]

            if not mention_ids:
                await ctx.send("❌ Please mention at least one host.")
                return

            if len(mention_ids) > 5:
                await ctx.send("❌ Maximum of 5 hosts per game.")
                return

            hosts = []
            for mid in mention_ids:
                try:
                    member = await ctx.guild.fetch_member(mid)
                    hosts.append(member)
                except:
                    pass

            if not hosts:
                await ctx.send("❌ Could not resolve mentioned users.")
                return

            self.db.add_hosts(game_number, hosts)

            embed = discord.Embed(
                title="🎤 Hosts Added",
                description=", ".join(m.display_name for m in hosts),
                color=discord.Color.green()
            )
            embed.add_field(name="Game", value=f"{game_number} | {game_name}")
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

            await ctx.send(embed=embed)
            return

        # ==========================================================
        # ROLE MODE
        # ==========================================================

        if team is None:
            await ctx.send("❌ Usage: .lib add <role_name> <team> [@player] [@sponsor]")
            return

        if team not in TEAMS:
            await ctx.send(
                f"❌ Invalid team! Use: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}"
            )
            return

        role_id = self.db.get_next_role_id(game_number)

        mention_pattern = r'<@!?(\d+)>'
        mention_ids = [int(i) for i in re.findall(mention_pattern, ctx.message.content)]

        mentioned_members = []
        for mid in mention_ids:
            try:
                member = await ctx.guild.fetch_member(mid)
                mentioned_members.append(member)
            except:
                pass

        player_name = player_id = sponsor_name = sponsor_id = None
        args_list = list(args)
        idx = mention_idx = 0

        # Player
        if idx < len(args_list):
            if args_list[idx].startswith('<@') and mention_idx < len(mentioned_members):
                m = mentioned_members[mention_idx]
                player_name = m.display_name
                player_id = m.id
                mention_idx += 1
                idx += 1

        # Sponsor
        if idx < len(args_list):
            if args_list[idx].startswith('<@') and mention_idx < len(mentioned_members):
                m = mentioned_members[mention_idx]
                sponsor_name = m.display_name
                sponsor_id = m.id

        # Description from reply
        description1 = None
        if ctx.message.reference:
            try:
                replied = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                description1 = replied.content
            except:
                pass

        try:
            self.db.add_role(
                game_number=game_number,
                game_name=game_name,
                role_id=role_id,
                role_name=role_name,
                team=team,
                player_name=player_name,
                player_id=player_id,
                sponsor_name=sponsor_name,
                sponsor_id=sponsor_id,
                description1=description1
            )

            embed = discord.Embed(
                title="✅ Role Added",
                description=f"**{role_name}** (ID: {role_id})",
                color=discord.Color.green()
            )

            embed.add_field(name="Game", value=f"{game_number} | {game_name}")
            embed.add_field(name="Team", value=TEAMS[team])

            if player_name:
                embed.add_field(name="Player", value=player_name)

            if sponsor_name:
                embed.add_field(name="Sponsor", value=sponsor_name)

            if description1:
                embed.add_field(
                    name="Description",
                    value=description1[:200] + ("..." if len(description1) > 200 else ""),
                    inline=False
                )

            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Error adding role: `{e}`")

    
    # @lib.command(name="add")
    # async def lib_add(self, ctx, role_name: str, team: int, *args):
    #     """Add new role - Usage: .lib add <role_name> <team> [@player] [@sponsor]"""
    #     if not self.is_librarian(ctx.author.id):
    #         await ctx.send("❌ You don't have permission to use this command!")
    #         return
        
    #     game_info = self.get_game_info_from_channel(ctx.channel)
    #     if not game_info:
    #         await ctx.send("❌ This command must be used in a Library channel (format: 'number│name')!")
    #         return
        
    #     game_number, game_name = game_info
        
    #     if team not in TEAMS:
    #         await ctx.send(f"❌ Invalid team! Use: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}")
    #         return
        
    #     role_id = self.db.get_next_role_id(game_number)
        
    #     # Parse mentions
    #     mention_pattern = r'<@!?(\d+)>'
    #     mention_ids = [int(id) for id in re.findall(mention_pattern, ctx.message.content)]
        
    #     mentioned_members = []
    #     for mention_id in mention_ids:
    #         try:
    #             member = await ctx.guild.fetch_member(mention_id)
    #             mentioned_members.append(member)
    #         except:
    #             pass
        
    #     # Parse player/sponsor
    #     player_name = player_id = sponsor_name = sponsor_id = None
    #     args_list = list(args)
    #     idx = mention_idx = 0
        
    #     # Player
    #     if idx < len(args_list):
    #         if args_list[idx].startswith('<@') and mention_idx < len(mentioned_members):
    #             player_member = mentioned_members[mention_idx]
    #             player_name = player_member.display_name
    #             player_id = player_member.id
    #             mention_idx += 1
    #             idx += 1
    #         else:
    #             player_name = args_list[idx]
    #             idx += 1
    #             if idx < len(args_list):
    #                 try:
    #                     player_id = int(args_list[idx])
    #                     if player_id == 0:
    #                         player_id = None
    #                     idx += 1
    #                 except ValueError:
    #                     pass
        
    #     # Sponsor
    #     if idx < len(args_list):
    #         if args_list[idx].startswith('<@') and mention_idx < len(mentioned_members):
    #             sponsor_member = mentioned_members[mention_idx]
    #             sponsor_name = sponsor_member.display_name
    #             sponsor_id = sponsor_member.id
    #         else:
    #             sponsor_name = args_list[idx]
    #             idx += 1
    #             if idx < len(args_list):
    #                 try:
    #                     sponsor_id = int(args_list[idx])
    #                     if sponsor_id == 0:
    #                         sponsor_id = None
    #                 except ValueError:
    #                     pass
        
    #     # Get description from reply
    #     description1 = None
    #     if ctx.message.reference:
    #         try:
    #             replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    #             description1 = replied_message.content
    #         except:
    #             pass
        
    #     try:
    #         self.db.add_role(game_number, game_name, role_id, role_name, team, player_name, player_id, sponsor_name, sponsor_id, description1)
            
    #         embed = discord.Embed(
    #             title="✅ Role Added Successfully",
    #             description=f"**{role_name}** (ID: {role_id}) has been added to the library.",
    #             color=discord.Color.green()
    #         )
    #         embed.add_field(name="Game", value=f"{game_number} | {game_name}")
    #         embed.add_field(name="Role ID", value=str(role_id))
    #         embed.add_field(name="Team", value=TEAMS[team])
            
    #         if player_name:
    #             player_info = f"{player_name}" + (f" (ID: {player_id})" if player_id else " (No ID)")
    #             embed.add_field(name="Player", value=player_info)
            
    #         if sponsor_name:
    #             sponsor_info = f"{sponsor_name}" + (f" (ID: {sponsor_id})" if sponsor_id else " (No ID)")
    #             embed.add_field(name="Sponsor", value=sponsor_info)
            
    #         if description1:
    #             desc_preview = description1[:100] + "..." if len(description1) > 100 else description1
    #             embed.add_field(name="Description 1 Added", value=desc_preview, inline=False)
            
    #         embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
    #         await ctx.send(embed=embed)
    #     except Exception as e:
    #         await ctx.send(f"❌ Error adding role: {str(e)}")
    def generate_team_pie_chart(self, team_counts: dict, game_number: int):
        import matplotlib.pyplot as plt

        teams = []
        counts = []

        for team_id, count in team_counts.items():
            if count > 0:
                teams.append(TEAMS.get(team_id, "Unknown"))
                counts.append(count)

        plt.figure()
        plt.pie(counts, labels=teams, autopct='%1.1f%%')
        plt.title(f"Game {game_number} — Team Distribution")
        file_path = f"game_{game_number}_distribution.png"
        plt.savefig(file_path)
        plt.close()

        return file_path

    @lib.command(name="summary")
    async def lib_summary(self, ctx, game_number: int):
        """Show game summary with pie chart"""

        summary = self.db.get_game_summary(game_number)

        if not summary or summary["total_roles"] == 0:
            await ctx.send("❌ Game not found or empty.")
            return

        # Build role distribution text
        team_lines = ""
        for team_id, team_name in TEAMS.items():
            count = summary["team_counts"].get(team_id, 0)
            team_lines += f"**{team_name}:** {count} roles\n"

        # Determine winners
        winners = summary["winning_teams"]
        if winners:
            winner_names = [TEAMS[t] for t in winners]
            winner_text = ", ".join(winner_names)
        else:
            winner_text = "Not set"

        # Create embed FIRST
        embed = discord.Embed(
            title=f"📊 Game {game_number} Summary",
            color=EMBED_COLOR
        )

        embed.add_field(name="📦 Role Distribution", value=team_lines, inline=False)
        embed.add_field(name="👥 Total Roles", value=str(summary["total_roles"]))
        embed.add_field(name="🏆 Winning Team(s)", value=winner_text)

        # 🔥 Add Hosts (NOW it exists)
        hosts = self.db.get_hosts_for_game(game_number)
        if hosts:
            embed.add_field(
                name="🎤 Host(s)",
                value=", ".join(hosts),
                inline=False
            )

        # Generate Pie Chart
        chart_path = self.generate_team_pie_chart(
            summary["team_counts"],
            game_number
        )

        file = discord.File(chart_path, filename="distribution.png")
        embed.set_image(url="attachment://distribution.png")

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        await ctx.send(embed=embed, file=file)

        # Clean up image file
        import os
        if os.path.exists(chart_path):
            os.remove(chart_path)


    
    @lib.command(name="edit")
    async def lib_edit(self, ctx, field: str, game_number: int, role_id_or_value: str, *, value: str = None):
        """Edit role field - Usage: .lib edit <field> <game#> <role_id> <value>"""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return
        
        # Handle gamecount
        if field.lower() == 'gamecount':
            try:
                count_value = int(role_id_or_value)
                if count_value not in [0, 1]:
                    await ctx.send("❌ Invalid value for gamecount! Use: 1 (yes) or 0 (no)")
                    return
                
                self.db.update_game_count(game_number, count_value)
                
                embed = discord.Embed(
                    title="✅ Game Count Updated",
                    description=f"All roles in game {game_number} set to count = {count_value}.",
                    color=discord.Color.green()
                )
                embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
                await ctx.send(embed=embed)
                return
            except ValueError:
                await ctx.send("❌ Invalid value!")
                return
        
        # Normal editing
        try:
            role_id = int(role_id_or_value)
        except ValueError:
            await ctx.send("❌ Invalid role ID!")
            return
        
        valid_fields = ['team', 'player_name', 'player_id', 'sponsor_name', 'sponsor_id', 
                       'description1', 'description2', 'description3', 'description4', 'role_name', 'win', 'count']
        
        if field.lower() not in valid_fields:
            await ctx.send(f"❌ Invalid field! Valid: {', '.join(valid_fields + ['gamecount'])}")
            return
        
        # Get value from reply for descriptions
        if field.lower() in ['description1', 'description2', 'description3', 'description4']:
            if ctx.message.reference:
                try:
                    replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    value = replied_message.content
                except:
                    if not value:
                        await ctx.send("❌ Could not fetch reply and no value provided!")
                        return
            elif not value:
                await ctx.send("❌ Please provide value or reply to message!")
                return
        else:
            if not value:
                await ctx.send("❌ Please provide a value!")
                return
        
        try:
            if field.lower() in ['team', 'player_id', 'sponsor_id']:
                value = int(value)
                if field.lower() == 'team' and value not in TEAMS:
                    await ctx.send(f"❌ Invalid team! Use: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}")
                    return
            elif field.lower() in ['win', 'count']:
                value = int(value)
                if value not in [0, 1]:
                    await ctx.send(f"❌ Invalid value for {field}! Use: 1 (yes) or 0 (no)")
                    return
            
            self.db.update_field(game_number, role_id, field.lower(), value)
            
            embed = discord.Embed(
                title="✅ Role Updated",
                description=f"Field **{field}** updated for role ID {role_id} in game {game_number}.",
                color=discord.Color.green()
            )
            
            if field.lower() in ['description1', 'description2', 'description3', 'description4']:
                preview = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                embed.add_field(name="New Value (Preview)", value=f"```{preview}```")
            elif field.lower() in ['win', 'count']:
                status_text = "✅ Yes" if value == 1 else "❌ No"
                embed.add_field(name="New Value", value=status_text)
            else:
                embed.add_field(name="New Value", value=str(value)[:1024])
            
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except ValueError as e:
            await ctx.send(f"❌ Invalid value type! {str(e)}")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
    
    @lib.command(name="delete")
    async def lib_delete(self, ctx, game_number: int, role_id: int):
        """Delete role - Usage: .lib delete <game#> <role_id>"""
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
                color=discord.Color.green()
            )
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
    
    @lib.command(name="deletegame")
    async def lib_deletegame(self, ctx, game_number: int):
        """Delete entire game - Usage: .lib deletegame <game#>"""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return
        
        games = self.db.get_all_games()
        game_data = next((g for g in games if g[0] == game_number), None)
        if not game_data:
            await ctx.send(f"❌ Game {game_number} not found!")
            return
        
        try:
            self.db.delete_game(game_number)
            embed = discord.Embed(
                title="✅ Game Deleted",
                description=f"Game {game_number} ({game_data[1]}) and all roles deleted.",
                color=discord.Color.green()
            )
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
    
    @lib.command(name="setwin")
    async def lib_setwin(self, ctx, game_number: int, *teams: int):
        """Set winners - Usage: .lib setwin <game#> <team1> [team2]..."""
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
                color=discord.Color.green()
            )
            embed.add_field(name="Winning Team(s)", value=", ".join(team_names))
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
    
    @lib.command(name="search")
    async def lib_search(self, ctx, *args):
        """Search roles easily (fuzzy)"""

        # No args → interactive
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
                color=EMBED_COLOR
            )
            await ctx.send(embed=embed, view=view)
            return

        # Game-only
        if len(args) == 1 and args[0].isdigit():
            game_number = int(args[0])
            game = next((g for g in self.db.get_all_games() if g[0] == game_number), None)

            if not game:
                await ctx.send("❌ Game not found.")
                return

            view = TeamSelectView(game_number, game[1], self.db)
            await ctx.send(embed=view.get_embed(), view=view)
            return

        # Role-name fuzzy search (global or scoped)
        if args[0].isdigit():
            game_number = int(args[0])
            query = " ".join(args[1:]).strip()
            if not query:
                await ctx.send("❌ Please provide a role name to search.")
                return

            roles = [r for r in self.db.search_roles_fuzzy(query) if r['game_number'] == game_number]
            def score(name):
                return SequenceMatcher(None, query.lower(), (name or "").lower()).ratio()


            roles.sort(
                key=lambda r: max(
                    score(r['role_name']),
                    score(r['player_name'] or ""),
                    score(r['sponsor_name'] or "")
                ),
                reverse=True
            )


        else:
            query = " ".join(args).strip()
            roles = self.db.search_roles_fuzzy(query)
            def score(name):
                return SequenceMatcher(None, query.lower(), (name or "").lower()).ratio()

            roles.sort(
                key=lambda r: max(
                    score(r['role_name']),
                    score(r['player_name'] or ""),
                    score(r['sponsor_name'] or "")
                ),
                reverse=True
            )



        if not roles:
            await ctx.send("❌ No matching roles found.")
            return

        if len(roles) == 1:
            role = roles[0]
            team_roles = self.db.get_roles_by_team(role['game_number'], role['team'])
            index = next(i for i, r in enumerate(team_roles) if r[0] == role['role_id'])
            view = RoleDescriptionView(
                role['game_number'], role['game_name'], team_roles, index, self.db
            )
            await ctx.send(embed=view.get_embed(), view=view)
            return

        view = RoleSelectionView(roles, self.db)
        await ctx.send(embed=view.get_embed(), view=view)


    
    @lib.command(name="idsearch")
    async def lib_idsearch(self, ctx, game_number: int, role_id: int):
        """Search by ID - Usage: .lib idsearch <game#> <role_id>"""
        role_data = self.db.get_role_details(game_number, role_id)
        if not role_data:
            await ctx.send(f"❌ Role ID {role_id} not found in game {game_number}!")
            return
        
        roles = self.db.get_roles_by_team(game_number, role_data["team"])
        index = next(i for i, r in enumerate(roles) if r[0] == role_id)
        view = RoleDescriptionView(game_number, role_data["game_name"], roles, index, self.db)
        embed = view.get_embed()
        await ctx.send(embed=embed, view=view)

    @lib.command(name="migrateaccount")
    async def lib_migrateaccount(self, ctx, old_identifier: str, new_member: discord.Member):
        """
        Migrate stats from old account (name OR id) → new Discord account

        Examples:
        .lib migrateaccount "OldName" @NewUser
        .lib migrateaccount 123456789 @NewUser
        """

        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ You don't have permission!")
            return

        db = self.db
        old_id = None

        # =====================
        # Try treat as ID first
        # =====================
        if old_identifier.isdigit():
            old_id = int(old_identifier)

        # =====================
        # Otherwise treat as NAME
        # =====================
        else:
            matches = db.find_accounts_by_name(old_identifier)

            if len(matches) == 0:
                await ctx.send("❌ No accounts found with that name.")
                return

            # MULTIPLE MATCHES → ASK USER
            if len(matches) > 1:
                msg = "⚠️ Multiple accounts found. Reply with the number:\n\n"

                for i, (pid, pname) in enumerate(matches, start=1):
                    msg += f"**{i}.** {pname} (`{pid}`)\n"

                await ctx.send(msg)

                def check(m):
                    return (
                        m.author == ctx.author and
                        m.channel == ctx.channel and
                        m.content.isdigit()
                    )

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

        # =====================
        # SAME ACCOUNT CHECK
        # =====================
        if old_id == new_member.id:
            await ctx.send("❌ Source and target accounts are the same.")
            return

        # =====================
        # SOURCE HAS STATS CHECK
        # =====================
        old_player_rows, old_sponsor_rows = db.get_account_stat_counts(old_id)

        if old_player_rows == 0 and old_sponsor_rows == 0:
            await ctx.send("⚠️ Warning: Source account has no stats recorded.")

        # =====================
        # SAFETY CHECK (TARGET HAS STATS)
        # =====================
        new_id = new_member.id

        player_rows, sponsor_rows = db.get_account_stat_counts(new_id)

        if player_rows > 0 or sponsor_rows > 0:
            await ctx.send(
                "⚠️ Target account already has stats.\n"
                "Use `.lib mergeaccounts` instead."
            )
            return

        # =====================
        # MIGRATE
        # =====================
        db.migrate_account_by_id(
            old_id,
            new_id,
            new_member.display_name
        )

        await ctx.send(
            f"✅ Migration complete → **{new_member.display_name}** now owns old stats."
        )

    
    @lib.command(name="help")
    async def lib_help(self, ctx):
        """Display help"""
        embed = discord.Embed(
            title="📚 Game Library — Help",
            description="Browse roles, view stats, manage library.",
            color=EMBED_COLOR
        )

        # =========================
        # 🔍 Browse & Search
        # =========================
        basic = (
            "**`.lib`**\n"
            "Open interactive game browser\n\n"
            "**`.lib search`**\n"
            "Interactive fuzzy search (roles, players, sponsors)\n\n"
            "**`.lib search <role name>`**\n"
            "Fuzzy role search across all games\n\n"
            "**`.lib search <game#>`**\n"
            "Jump directly to a game\n\n"
            "**`.lib search <game#> <role name>`**\n"
            "Search within a specific game\n\n"
            "**`.lib idsearch <game#> <role_id>`**\n"
            "Jump directly to a role by ID\n\n"
            "**`.lib summary <game#>`**\n"
            "Show game summary + team pie chart"
        )

        embed.add_field(name="🔍 Browse & Search", value=basic, inline=False)

        # =========================
        # 📊 Statistics
        # =========================
        stats = (
            "**`.stats`** or **`.stats @player`**\n"
            "View player statistics\n\n"
            "**`.winrate`**\n"
            "View overall team winrates"
        )

        embed.add_field(name="📊 Statistics", value=stats, inline=False)

        # =========================
        # 🔧 Librarian Only
        # =========================
        if self.is_librarian(ctx.author.id):

            role_mgmt = (
                "**`.lib add <role_name> <team> [@player] [@sponsor]`**\n"
                "Add a role (reply for description)\n\n"
                "**`.lib edit <field> <game#> <role_id> <value>`**\n"
                "Edit: team, role_name, player_name, player_id,\n"
                "sponsor_name, sponsor_id, description1-4, win, count\n\n"
                "**`.lib delete <game#> <role_id>`**\n"
                "Delete a role"
            )

            game_mgmt = (
                "**`.lib edit gamecount <game#> <0|1>`**\n"
                "Include/exclude game from stats\n\n"
                "**`.lib setwin <game#> <team> [team2]...`**\n"
                "Set winning team(s)\n\n"
                "**`.lib deletegame <game#>`**\n"
                "Delete entire game"
            )

            account_tools = (
                "**`.lib migrateaccount <old_name|old_id> @new_user`**\n"
                "Move stats to a new account\n\n"
                "**`.lib mergeaccount <source> <target>`**\n"
                "Merge two accounts (confirmation required)"
            )

            embed.add_field(name="🔧 Role Management", value=role_mgmt, inline=False)
            embed.add_field(name="🎮 Game Control", value=game_mgmt, inline=False)
            embed.add_field(name="👤 Account Tools", value=account_tools, inline=False)

        # =========================
        # 🎯 Team IDs
        # =========================
        team_info = " • ".join([f"**{id}** = {name}" for id, name in TEAMS.items()])
        embed.add_field(name="🎯 Team IDs", value=team_info, inline=False)

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        await ctx.send(embed=embed)

    @commands.has_permissions(administrator=True)
    @commands.command(name="missingids")
    async def missing_ids(self, ctx):
        """Show players missing IDs with pagination and alphabetical sorting."""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT player_name
            FROM roles
            WHERE player_name IS NOT NULL
            AND (player_id IS NULL OR player_id = 0)
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await ctx.send("✅ All players have IDs assigned.")
            return

        missing = [r[0] for r in rows]

        view = MissingIDPageView(self, missing, page=0)
        embed = self.generate_missingid_embed(view.visible_names, 0, view.max_page)

        await ctx.send(embed=embed, view=view)

    @lib.command(name="mergeaccount")
    async def mergeaccount(self, ctx, source_input: str, target_input: str):
        """
        Merge two accounts.
        Source account stats will be moved into target account.
        """

        import asyncio

        db = self.db

        # ---------- RESOLVE HELPER ----------
        async def resolve_account(user_input, label):
            # If mention
            if ctx.message.mentions:
                for m in ctx.message.mentions:
                    if user_input in [m.mention, str(m.id)]:
                        return m.id, m.display_name

            # If numeric ID
            if user_input.isdigit():
                return int(user_input), f"User-{user_input}"

            # Otherwise treat as name search
            matches = db.find_accounts_by_name(user_input)

            if not matches:
                await ctx.send(f"❌ No matches found for `{user_input}`")
                return None, None

            if len(matches) == 1:
                return matches[0][0], matches[0][1]

            # Multiple matches → ask user
            msg = f"🔎 Multiple matches for **{label}** `{user_input}`:\n\n"
            for i, (pid, pname) in enumerate(matches[:10], 1):
                msg += f"{i}. **{pname}** ({pid})\n"

            msg += "\nReply with the number."

            await ctx.send(msg)

            def check(m):
                return (
                    m.author == ctx.author
                    and m.channel == ctx.channel
                    and m.content.isdigit()
                )

            try:
                reply = await self.bot.wait_for("message", check=check, timeout=30)
                idx = int(reply.content) - 1
                if 0 <= idx < len(matches):
                    return matches[idx][0], matches[idx][1]
            except:
                pass

            await ctx.send("❌ Selection failed.")
            return None, None

        # ---------- RESOLVE SOURCE ----------
        source_id, source_name = await resolve_account(source_input, "SOURCE")
        if not source_id:
            return

        # ---------- RESOLVE TARGET ----------
        target_id, target_name = await resolve_account(target_input, "TARGET")
        if not target_id:
            return

        # ---------- SAFETY CHECK ----------
        if source_id == target_id:
            await ctx.send("❌ Source and target accounts are the same.")
            return

        # ---------- PREVIEW STATS ----------
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
            "Type **MERGE** to confirm\n"
            "Type **CANCEL** to abort\n"
            "(Times out in 30s)"
        )

        await ctx.send(preview)

        def confirm_check(m):
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and m.content.upper() in ["MERGE", "CANCEL"]
            )

        try:
            reply = await self.bot.wait_for("message", check=confirm_check, timeout=30)

            if reply.content.upper() == "CANCEL":
                await ctx.send("❌ Merge cancelled.")
                return

        except asyncio.TimeoutError:
            await ctx.send("⌛ Merge confirmation timed out.")
            return

        # ---------- EXECUTE MERGE ----------
        try:
            db.merge_accounts(source_id, target_id, target_name)

            await ctx.send(
                f"✅ Merge complete!\n"
                f"Moved all stats from **{source_name}** → **{target_name}**"
            )

        except Exception as e:
            await ctx.send("❌ Merge failed. Contact admin.")
            print("Merge error:", e)



    @commands.command(name="winrate")
    async def winrate(self, ctx):
        """View team winrates"""
        stats = self.db.get_winrate_stats()
        
        embed = discord.Embed(title="📊 Team Winrate Statistics", description="Overall performance across all games", color=EMBED_COLOR)
        
        for team_name, data in stats.items():
            value = f"**Games:** {data['total']}\n**Wins:** {data['wins']}\n**Winrate:** {data['winrate']:.1f}%"
            embed.add_field(name=team_name, value=value, inline=True)
        
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        await ctx.send(embed=embed)

    @commands.command(name="stats")
    async def stats(self, ctx, *, member_input: str = None):
        """View player stats (mentions OR text name)"""

        member = None

        # ------------------------
        # 1️⃣ No input → self
        # ------------------------
        if not member_input:
            member = ctx.author

        # ------------------------
        # 2️⃣ Mention parse
        # ------------------------
        else:
            mention_match = re.search(r'<@!?(\d+)>', member_input)

            if mention_match:
                try:
                    member = await ctx.guild.fetch_member(int(mention_match.group(1)))
                except:
                    member = None

        # ------------------------
        # 3️⃣ Exact guild name match
        # ------------------------
        if not member and member_input:
            lowered = member_input.lower()

            for m in ctx.guild.members:
                if m.display_name.lower() == lowered or m.name.lower() == lowered:
                    member = m
                    break

        # ------------------------
        # 4️⃣ DB fallback search
        # ------------------------
        if not member and member_input:
            matches = self.db.find_accounts_by_name(member_input)

            if len(matches) == 0:
                await ctx.send("❌ No player found with that name.")
                return

            # Multiple matches → ask user
            if len(matches) > 1:
                msg = "⚠️ Multiple matches found. Reply with number:\n\n"

                for i, (pid, pname) in enumerate(matches, start=1):
                    msg += f"**{i}.** {pname} (`{pid}`)\n"

                await ctx.send(msg)

                def check(m):
                    return (
                        m.author == ctx.author and
                        m.channel == ctx.channel and
                        m.content.isdigit()
                    )

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

            # Fake member object so rest of stats logic stays identical
            class FakeMember:
                def __init__(self, id, name, avatar):
                    self.id = id
                    self.display_name = name
                    self.display_avatar = avatar

            member = FakeMember(
                chosen_id,
                chosen_name,
                ctx.author.display_avatar
            )

        # ------------------------
        # Final safety
        # ------------------------
        if not member:
            await ctx.send("❌ Could not resolve player.")
            return

        # ==============================
        # 🔥 ORIGINAL STATS LOGIC BELOW
        # ==============================

        stats = self.db.get_player_stats(member.id)

        if stats['total_participations'] == 0:
            await ctx.send(f"❌ No statistics found for {member.display_name}!")
            return

        embed = discord.Embed(title=f"📊 {member.display_name}", color=EMBED_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)

        # First game
        first_game_num, first_game_name = self.db.get_first_game_played(member.id)
        first_game_line = f"**First Game:** {first_game_num} — {first_game_name}\n" if first_game_num else "**First Game:** Unknown\n"

        # Avg gap
        games_list = self.db.get_games_played(member.id)
        if len(games_list) >= 2:
            gaps = [games_list[i+1] - games_list[i] for i in range(len(games_list)-1)]
            avg_gap = sum(gaps) / len(gaps)
            total_from_start = max(games_list) - min(games_list) + 1
            participation_after_join = (len(games_list) / total_from_start) * 100
            avg_gap_line = f"**Avg Gap:** {avg_gap:.2f} games\n**Participation After Joining:** {participation_after_join:.1f}%\n"
        else:
            avg_gap_line = "**Avg Gap:** Not enough data\n"

        # Allies
        top_allies = self.db.get_top_allies2(member.id)

        if top_allies:
            ally_text = ""
            for pid, pname, wins, games, wr in top_allies:
                ally_text += f"• **{pname}** — {wr*100:.1f}% WR ({wins}W / {games}G)\n"
        else:
            ally_text = "*No strong allies found.*"

        
        # Worst Allies
        worst_allies = self.db.get_worst_allies2(member.id)

        if worst_allies:
            worst_text = ""
            for pid, pname, wins, games, wr in worst_allies:
                worst_text += f"• **{pname}** — {wr*100:.1f}% WR ({wins}W / {games}G)\n"
        else:
            worst_text = "*No cursed alliances detected.*"


        # Nemeses
        top_nemeses = self.db.get_top_nemeses2(member.id)

        if top_nemeses:
            nem_text = ""
            for pid, pname, losses, games, lr in top_nemeses:
                nem_text += f"• **{pname}** — {lr*100:.1f}% Loss ({losses}L / {games}G)\n"
        else:
            nem_text = "*No strong nemeses found.*"

        overall = first_game_line + avg_gap_line + "\n"
        overall += f"**Total Participations:** {stats['total_participations']} ({stats['participation_rate']:.1f}% of all games)\n"
        overall += f"**As Player:** {stats['games_as_player']}\n**As Sponsor:** {stats['games_as_sponsor']}\n"
        overall += f"**Total Wins:** {stats['total_wins']}\n**Overall Winrate:** {stats['winrate']:.1f}%"

        embed.add_field(name="📈 Overall Statistics", value=overall, inline=False)

        wins = f"**Wins as Player:** {stats['wins_as_player']}\n**Wins as Sponsor:** {stats['wins_as_sponsor']}"
        embed.add_field(name="🏆 Wins Breakdown", value=wins, inline=False)

        for team_name, team_data in stats['team_stats'].items():
            if team_data['total'] > 0:
                team_winrate = (team_data['wins'] / team_data['total'] * 100) if team_data['total'] > 0 else 0
                value = f"**Games:** {team_data['total']}\n**Wins:** {team_data['wins']}\n**Winrate:** {team_winrate:.1f}%"
                embed.add_field(name=team_name, value=value, inline=True)

        embed.add_field(name="🟦 Top 5 Allies", value=ally_text, inline=False)
        embed.add_field(name="🟥 Top 5 Nemeses", value=nem_text, inline=False)
        embed.add_field(name="☠️ Worst Allies", value=worst_text, inline=False)


        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        view = StatsView(self.db, member)
        await ctx.send(embed=embed, view=view)

    
    @commands.command(name="stats123")
    async def stats123(self, ctx, member: discord.Member = None):
        """View player stats - Usage: .stats [@player]"""
        if member is None:
            member = ctx.author
        
        stats = self.db.get_player_stats(member.id)
        
        if stats['total_participations'] == 0:
            await ctx.send(f"❌ No statistics found for {member.display_name}!")
            return
        
        embed = discord.Embed(title=f"📊 {member.display_name}", color=EMBED_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        # First game
        first_game_num, first_game_name = self.db.get_first_game_played(member.id)
        first_game_line = f"**First Game:** {first_game_num} — {first_game_name}\n" if first_game_num else "**First Game:** Unknown\n"
        
        # Avg gap
        games_list = self.db.get_games_played(member.id)
        if len(games_list) >= 2:
            gaps = [games_list[i+1] - games_list[i] for i in range(len(games_list)-1)]
            avg_gap = sum(gaps) / len(gaps)
            total_from_start = max(games_list) - min(games_list) + 1
            participation_after_join = (len(games_list) / total_from_start) * 100
            avg_gap_line = f"**Avg Gap:** {avg_gap:.2f} games\n**Participation After Joining:** {participation_after_join:.1f}%\n"
        else:
            avg_gap_line = "**Avg Gap:** Not enough data\n"
        
        # # Best ally
        # ally_id, ally_name, ally_wins = self.db.get_best_ally(member.id)
        # best_ally_line = f"**Best Ally:** {ally_name} ({ally_wins} wins)\n" if ally_id else "**Best Ally:** None\n"
        
        # # Nemesis
        # nemesis_id, nemesis_name, nemesis_losses = self.db.get_nemesis(member.id)
        # nemesis_line = f"**Nemesis:** {nemesis_name} ({nemesis_losses} losses)\n" if nemesis_id else "**Nemesis:** None\n"
        # --- TOP ALLIES ---
       # top_allies = self.db.get_top_allies(member.id)
        #if top_allies:
          #  ally_text = ""
         #   for pid, pname, wins_together, games_together in top_allies:
           #     ally_text += f"• **{pname}** — {wins_together} wins / {games_together} games together\n"
        #else:
         #   ally_text = "*No allies found.*"

        top_allies = self.db.get_top_allies2(member.id)

        if top_allies:
            ally_text = ""
            for pid, pname, wins, games, wr in top_allies:
                ally_text += f"• **{pname}** — {wr*100:.1f}% WR ({wins}W / {games}G)\n"
        else:
            ally_text = "*No strong allies found.*"


        # --- TOP NEMESES ---
        #top_nemeses = self.db.get_top_nemeses(member.id)
        #if top_nemeses:
         #   nem_text = ""
          #  for pid, pname, losses_to, games_together in top_nemeses:
           #     nem_text += f"• **{pname}** — {losses_to} losses / {games_together} games together\n"
        #else:
         #   nem_text = "*No nemeses found.*"
        top_nemeses = self.db.get_top_nemeses2(member.id)

        if top_nemeses:
            nem_text = ""
            for pid, pname, losses, games, lr in top_nemeses:
                nem_text += f"• **{pname}** — {lr*100:.1f}% Loss ({losses}L / {games}G)\n"
        else:
            nem_text = "*No strong nemeses found.*"


        # overall = first_game_line + avg_gap_line + best_ally_line + nemesis_line + "\n"
        overall = first_game_line + avg_gap_line + "\n"

        overall += f"**Total Participations:** {stats['total_participations']} ({stats['participation_rate']:.1f}% of all games)\n"
        overall += f"**As Player:** {stats['games_as_player']}\n**As Sponsor:** {stats['games_as_sponsor']}\n"
        overall += f"**Total Wins:** {stats['total_wins']}\n**Overall Winrate:** {stats['winrate']:.1f}%"
        embed.add_field(name="📈 Overall Statistics", value=overall, inline=False)
        
        wins = f"**Wins as Player:** {stats['wins_as_player']}\n**Wins as Sponsor:** {stats['wins_as_sponsor']}"
        embed.add_field(name="🏆 Wins Breakdown", value=wins, inline=False)
        
        for team_name, team_data in stats['team_stats'].items():
            if team_data['total'] > 0:
                team_winrate = (team_data['wins'] / team_data['total'] * 100) if team_data['total'] > 0 else 0
                value = f"**Games:** {team_data['total']}\n**Wins:** {team_data['wins']}\n**Winrate:** {team_winrate:.1f}%"
                embed.add_field(name=team_name, value=value, inline=True)
        
        embed.add_field(name="🟦 Top 3 Allies", value=ally_text, inline=False)
        embed.add_field(name="🟥 Top 3 Nemeses", value=nem_text, inline=False)

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        
        view = StatsView(self.db, member)
        await ctx.send(embed=embed, view=view)



async def setup(bot):
    await bot.add_cog(GameLibrary(bot))