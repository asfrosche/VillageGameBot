from utils import bot_db as _bot_db

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
    "current_houses": {},
    "infos": {},
    "lynch_votes1": {},
    "lynch_votes2": {},
    "leader_votes": {},
    "vote_value" : [],
    "houselist": {},
    "dashboard_enabled": False,
    "economy_collect_amount": 250,
    # Meeting system (per-guild)
    "meeting_enabled": False,
    "meeting_channel_id": None,
    "target_guild_id": None,
    "meeting_category_id": None,
    # Message tracking (per-guild; channel = day discussion by default)
    "message_tracking_enabled": False,
    "tracked_message_counts": {},
    "narration_color": 0xdc143c,
    "narration_log_channel_name": "✍️│commentary",
}

def load_guild_data(guild_id):
    _ensure_db_ready()
    return _bot_db.get_guild_data(int(guild_id))

def save_guild_data(guild_id, data):
    _ensure_db_ready()
    _bot_db.upsert_guild_data(int(guild_id), data)


def delete_guild_data(guild_id):
    _ensure_db_ready()
    _bot_db.delete_guild_data(int(guild_id))


_DB_READY = False


def _ensure_db_ready() -> None:
    global _DB_READY
    if _DB_READY:
        return
    _bot_db.init_db()
    _bot_db.migrate_legacy_json()
    _DB_READY = True

def init_invites_db():
    pass

def load_invites(guild_id):
    return _bot_db.load_invites(guild_id)

def save_invites(guild_id, invites):
    _bot_db.save_invites(guild_id, invites)

def delete_guild_invites(guild_id):
    _bot_db.delete_guild_invites(guild_id)

def init_deadlist_db():
    pass

def add_player(player, team, role, server):
    _bot_db.add_player(player, team, role, server)

def remove_player(player, server):
    _bot_db.remove_player(player, server)

def get_team_players(team, server):
    return _bot_db.get_team_players(team, server)

def delete_guild_deadlist(server):
    _bot_db.delete_guild_deadlist(server)