import copy

import discord

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
    "os_questions_log_channel_name": 'log-actions',
    "economy_log_channel_name": 'logs-economy',
    "edit_del_logs": 'edit-and-del-logs',
    "join_and_leave_logs": 'join-leave-logs',
    "announcements_channel_name": '❗│announcements',
    "map_channel_name": '🗺│map',
    "daydiscussion_channel_name": '🌞│day-discussion',
    "megaphone_channel_name": '📢│megaphone',
    "lynch_channel_name1": '🗳│vote-session-1',
    "lynch_channel_name2": '🗳│vote-session-2',
    "lynch_channel_name3": '🗳│vote-session-3',
    "lynch_channel_name4": '🗳│vote-session-4',
    "lynch_channel_name5": '🗳│vote-session-5',
    "lynch_channel_name6": '🗳│vote-session-6',
    "leader_channel_name": '👑│leader-election',
    "leader_channel_name2": '👑│leader-election-2',
    "lynch_channel_id1": None,
    "lynch_channel_id2": None,
    "lynch_channel_id3": None,
    "lynch_channel_id4": None,
    "lynch_channel_id5": None,
    "lynch_channel_id6": None,
    "leader_channel_id": None,
    "leader_channel_id2": None,
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
    "auto_pin_corpse": True,
    "day_end_time": None,
    "lynch_end_time": None,
    "presets_end_time": None,
    "member_homes": {},
    "current_houses": {},
    "infos": {},
    "lynch_votes1": {},
    "lynch_votes2": {},
    "lynch_votes3": {},
    "lynch_votes4": {},
    "lynch_votes5": {},
    "lynch_votes6": {},
    "leader_votes": {},
    "leader_votes2": {},
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
    "server_message_laps": [],
    "server_message_lap_counter": 0,
    "narration_color": 0xdc143c,
    "narration_log_channel_name": "✍️│commentary",
    "player_follows": {},
    "player_stalks": {},
    "channel_statuses": {},
    "locked_houses": {},
    "player_slots": {},
    "channel_slots": {},
    "skipnight_sessions": {},
    "pick_sessions": {},
    "stickies": {},
    # Action completion tracking
    "completed_actions": {},  # user_id -> count
    "completed_askos": {},  # user_id -> count
}

def load_guild_data(guild_id):
    _ensure_db_ready()
    data = _bot_db.get_guild_data(int(guild_id))
    if data is None:
        return None
    # Back-fill keys added after this guild was first saved (e.g. leader_votes2),
    # so older guilds don't hit KeyError on newly introduced settings.
    missing = [key for key in base_variables if key not in data]
    if missing:
        for key in missing:
            data[key] = copy.deepcopy(base_variables[key])
        try:
            _bot_db.upsert_guild_data(int(guild_id), data)
        except Exception:
            pass
    return data

def save_guild_data(guild_id, data):
    _ensure_db_ready()
    _bot_db.upsert_guild_data(int(guild_id), data)


def delete_guild_data(guild_id):
    _ensure_db_ready()
    _bot_db.delete_guild_data(int(guild_id))


# Number of lynch (vote) sessions. Sessions 1-6 are first-class; the extra
# ones live in the same DAYCHAT category as the original four.
LYNCH_SESSION_COUNT = 6
LYNCH_SESSION_NAME_KEYS = tuple(
    f"lynch_channel_name{i}" for i in range(1, LYNCH_SESSION_COUNT + 1)
)
LYNCH_SESSION_VOTE_KEYS = tuple(
    f"lynch_votes{i}" for i in range(1, LYNCH_SESSION_COUNT + 1)
)

# Maps the stored *name* key of a lynch-style channel to its ID key.
LYNCH_CHANNEL_ID_KEYS = {
    "lynch_channel_name1": "lynch_channel_id1",
    "lynch_channel_name2": "lynch_channel_id2",
    "lynch_channel_name3": "lynch_channel_id3",
    "lynch_channel_name4": "lynch_channel_id4",
    "lynch_channel_name5": "lynch_channel_id5",
    "lynch_channel_name6": "lynch_channel_id6",
    "leader_channel_name": "leader_channel_id",
    "leader_channel_name2": "leader_channel_id2",
}


def get_lynch_channel(guild, guild_data, name_key):
    """Resolve a lynch/leader channel by ID first, then fall back to its name.

    Channel IDs are stable across renames, so a renamed session keeps working.
    The name lookup is a fallback for guilds set up before IDs were stored; on
    a successful name match the ID is back-filled once so later renames are safe.
    """
    id_key = LYNCH_CHANNEL_ID_KEYS[name_key]
    channel_id = guild_data.get(id_key)
    if channel_id:
        try:
            channel = guild.get_channel(int(channel_id))
        except (TypeError, ValueError):
            channel = None
        if channel is not None:
            return channel
    name = guild_data.get(name_key)
    if not name:
        return None
    channel = discord.utils.get(guild.channels, name=name)
    if channel is not None and channel.id != channel_id:
        # Back-fill (or repair a stale ID) so later renames keep working.
        guild_data[id_key] = channel.id
        try:
            save_guild_data(guild.id, guild_data)
        except Exception:
            pass
    return channel


def resolve_lynch_channels(guild, guild_data):
    """Return every configured lynch session channel, in session order."""
    return [get_lynch_channel(guild, guild_data, key) for key in LYNCH_SESSION_NAME_KEYS]


def set_lynch_channel(guild_data, name_key, channel):
    """Point a lynch-style channel key at *channel*, storing name *and* ID."""
    id_key = LYNCH_CHANNEL_ID_KEYS[name_key]
    guild_data[name_key] = channel.name
    guild_data[id_key] = channel.id


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
    return _bot_db.remove_player(player, server)

def get_team_players(team, server):
    return _bot_db.get_team_players(team, server)

def delete_guild_deadlist(server):
    _bot_db.delete_guild_deadlist(server)