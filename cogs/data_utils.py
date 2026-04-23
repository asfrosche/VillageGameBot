import os
import json
import sqlite3

base_variables = {
    "overseer_role_name": 'Overseer',
    "alive_role_name": 'Alive',
    "sponsor_role_name": 'Sponsor',
    "spectator_role_name": 'Spectator',
    "dead_role_name": 'Dead',
    "alt_role_name": 'Alt',
    "log_channel_name": 'log-visits',
    "actions_log_channel_name": 'log-actions',
    "edit_del_logs": 'edit-and-del-logs',
    "join_and_leave_logs": 'join-leave-logs',
    "announcements_channel_name": '❗│announcements',
    "map_channel_name": '🗺│map',
    "daydiscussion_channel_name": '🌞│day-discussion',
    "megaphone_channel_name": '📢│megaphone',
    "lynch_channel_name1": '🗳│vote-session-1',
    "lynch_channel_name2": '🗳│vote-session-2',
    "leader_channel_name": '👑│leader-election',
    "vote_count_name": '📊│vote-count',
    "house_prefix": '🏡│house-',
    "overseer_category_name": 'OVERSEER',
    "atg_category_name": 'ABOUT THE GAME',
    "chats_category_name": 'CHATS',
    "os_relations_category_name": 'OVERSEER RELATIONS',
    "daychat_category_name": 'DAYCHAT',
    "nominations_category_name": 'NOMINATIONS',
    "publc_category_name": 'PUBLIC CHANNELS',
    "privc_category_name": 'PRIVATE CHANNELS',
    "houses_category_name": 'HOUSES',
    "rc_category_name": 'ROLES',
    "alt_category_name": 'ALTS',
    "dead_rc_category_name": 'DEAD RC',
    "inaccessible_houses_category_name": 'INACCESSIBLE HOUSES',
    "old_pcs_category_name": 'OLD PCS',
    "whisper_logs_channel_name": 'whisper-logs',
    "whisper_response": 'whisper',
    "fireworks_response": 'fireworks',
    "move_in_response": 'move in',
    "timeout_duration": 10800,
    "showwhispersender": False,
    "autojoinifempty": False,
    "autojoinknockexpired": False,
    "maxmembersinhome": 50,
    "refuseresponse": 1,
    "voteinrc": False,
    "dead_count": False,
    "alt_count": False,
    "show_dead_on_refuse": False,
    "show_alt_on_refuse": False,
    "can_dead_open": False,
    "can_alt_open": False,
    "member_homes": {},
    "infos": {},
    "lynch_votes1": {},
    "lynch_votes2": {},
    "leader_votes": {},
    "vote_value" : [],
    "houselist": {}
}

def load_guild_data(guild_id):
    guild_data_file = os.path.join("db", f"{guild_id}.json")
    if os.path.exists(guild_data_file):
        with open(guild_data_file, "r") as f:
            return json.load(f)
    else:
        return None

def save_guild_data(guild_id, data):
    guild_data_file = os.path.join("db", f"{guild_id}.json")
    with open(guild_data_file, "w") as f:
        json.dump(data, f, indent=4)

invites_db_path = 'db/invites.db'

def init_invites_db():
    conn = sqlite3.connect(invites_db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS invites (
                    guild_id INTEGER,
                    invite_code TEXT,
                    uses INTEGER,
                    PRIMARY KEY (guild_id, invite_code)
                )''')
    conn.commit()
    conn.close()

def load_invites(guild_id):
    conn = sqlite3.connect(invites_db_path)
    c = conn.cursor()
    c.execute('SELECT invite_code, uses FROM invites WHERE guild_id = ?', (guild_id,))
    invites = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return invites

def save_invites(guild_id, invites):
    conn = sqlite3.connect(invites_db_path)
    c = conn.cursor()
    c.execute('DELETE FROM invites WHERE guild_id = ?', (guild_id,))
    for code, uses in invites.items():
        c.execute('INSERT INTO invites (guild_id, invite_code, uses) VALUES (?, ?, ?)', (guild_id, code, uses))
    conn.commit()
    conn.close()

deadlist_db_path = 'db/deadlist.db'

def init_deadlist_db():
    conn = sqlite3.connect(deadlist_db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS deadlist (
                    player TEXT,
                    team TEXT,
                    role TEXT,
                    server INTEGER
                )''')
    conn.commit()
    conn.close()

def add_player(player, team, role, server):
    conn = sqlite3.connect(deadlist_db_path)
    c = conn.cursor()
    c.execute("INSERT INTO deadlist (player, team, role, server) VALUES (?, ?, ?, ?)", 
                (player, team, role, server))
    conn.commit()
    conn.close()

def remove_player(player, server):
    conn = sqlite3.connect(deadlist_db_path)
    c = conn.cursor()
    c.execute("DELETE FROM deadlist WHERE player=? AND server=?", 
                (player, server))
    conn.commit()
    conn.close()

def get_team_players(team, server):
    conn = sqlite3.connect(deadlist_db_path)
    c = conn.cursor()
    c.execute("SELECT player, role FROM deadlist WHERE team=? AND server=?", 
                (team, server))
    results = c.fetchall()
    conn.close()
    return results