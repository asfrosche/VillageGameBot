"""Deep tests for Follow system: _move_followers, _remove_followers_from_house,
after_movement_update, cycle detection, stealth, multi-house warnings."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import discord

from cogs import surveillance_cog


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_guild(guild_id=1):
    guild = MagicMock()
    guild.id = guild_id
    guild.get_member = MagicMock(return_value=None)
    guild.text_channels = []
    guild.categories = []
    return guild


def _make_member(member_id, roles=None):
    m = MagicMock()
    m.id = member_id
    m.mention = f"<@{member_id}>"
    m.display_name = f"Player{member_id}"
    m.name = f"player{member_id}"
    m.roles = roles or []
    return m


def _make_role(name):
    r = MagicMock()
    r.name = name
    return r


def _make_channel(ch_id, name="house-1", category=None):
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = ch_id
    ch.name = name
    ch.category = category
    ch.mention = f"<#{ch_id}>"
    ch.permissions_for = MagicMock(return_value=MagicMock(send_messages=False, read_messages=False))
    ch.set_permissions = AsyncMock()
    ch.send = AsyncMock()
    return ch


def _make_guild_data(follows=None, houses_category_name="HOUSES",
                     alive_role_name="Alive", sponsor_role_name="Sponsor",
                     dead_role_name="Dead", alt_role_name="Alt",
                     log_channel_name="log-visits"):
    return {
        "player_follows": follows or {},
        "houses_category_name": houses_category_name,
        "alive_role_name": alive_role_name,
        "sponsor_role_name": sponsor_role_name,
        "dead_role_name": dead_role_name,
        "alt_role_name": alt_role_name,
        "log_channel_name": log_channel_name,
        "player_stalks": {},
    }


# ── _check_follow_cycle ──────────────────────────────────────────────────────

class TestCheckFollowCycle:
    def test_empty_follows_no_cycle(self):
        assert surveillance_cog.Surveillance._check_follow_cycle({}, "1", "2") is False

    def test_direct_cycle(self):
        follows = {"1": {"target": "2"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "2", "1") is True

    def test_chain_cycle(self):
        follows = {"1": {"target": "2"}, "2": {"target": "3"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "3", "1") is True

    def test_no_cycle_different_chain(self):
        follows = {"1": {"target": "2"}, "2": {"target": "3"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "3", "4") is False

    def test_self_follow_detected(self):
        # The follow command prevents self-follows before calling this,
        # but the cycle check also catches it as a safety net
        follows = {}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "1", "1") is True

    def test_long_chain_cycle(self):
        follows = {"1": {"target": "2"}, "2": {"target": "3"}, "3": {"target": "4"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "4", "1") is True

    def test_separate_chains_no_cross(self):
        follows = {"1": {"target": "2"}, "3": {"target": "4"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "2", "3") is False

    def test_self_referential_blocks_others(self):
        # If 1 follows 1 (shouldn't happen but safety), 2 following 1 is caught
        follows = {"1": {"target": "1"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "2", "1") is True

    def test_3way_cycle(self):
        follows = {"1": {"target": "2"}, "2": {"target": "3"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "3", "1") is True

    def test_no_cycle_unrelated_target(self):
        follows = {"1": {"target": "2"}}
        assert surveillance_cog.Surveillance._check_follow_cycle(follows, "1", "3") is False


# ── _move_followers ──────────────────────────────────────────────────────────

class TestMoveFollowers:
    def _build_setup(self):
        alive_role = _make_role("Alive")
        sponsor_role = _make_role("Sponsor")
        dead_role = _make_role("Dead")
        alt_role = _make_role("Alt")

        guild = _make_guild()
        guild.roles = [alive_role, sponsor_role, dead_role, alt_role]

        house_cat = MagicMock()
        house_cat.name = "HOUSES"

        house1 = _make_channel(100, "house-1", house_cat)
        house2 = _make_channel(200, "house-2", house_cat)
        house_cat.channels = [house1, house2]

        log_ch = _make_channel(300, "log-visits")
        guild.categories = [house_cat]
        guild.text_channels = [log_ch]

        target = _make_member(10, roles=[alive_role])
        follower = _make_member(20, roles=[alive_role])

        # follower in house1, target in house2
        def perms_h1(member):
            if member.id == 20:
                return MagicMock(send_messages=True)
            return MagicMock(send_messages=False)

        def perms_h2(member):
            if member.id == 10:
                return MagicMock(send_messages=True)
            return MagicMock(send_messages=False)

        house1.permissions_for = perms_h1
        house2.permissions_for = perms_h2

        guild.get_member = lambda mid: {10: target, 20: follower}.get(mid)

        guild_data = _make_guild_data(follows={"20": {"target": "10", "stealth": False}})

        return guild, guild_data, target, follower, house1, house2, log_ch, alive_role

    @pytest.mark.asyncio
    async def test_follower_moves_with_target(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        house1.set_permissions.assert_called_once_with(follower, overwrite=None)
        house2.set_permissions.assert_called_once_with(follower, read_messages=True, send_messages=True)

    @pytest.mark.asyncio
    async def test_follower_gets_join_leave_messages(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        house1.send.assert_called_once()
        house2.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_stealth_follower_no_messages(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        guild_data["player_follows"]["20"]["stealth"] = True
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        house1.send.assert_not_called()
        house2.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_target_stealth_suppresses_all(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target, is_stealth=True)

        house1.send.assert_not_called()
        house2.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_in_house_no_move(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        # Make follower already in house2
        def perms(member):
            if member.id == 20:
                return MagicMock(send_messages=True)
            return MagicMock(send_messages=False)
        house2.permissions_for = perms

        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        house1.set_permissions.assert_not_called()
        house2.set_permissions.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_followers_no_action(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        guild_data["player_follows"] = {}
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        house1.set_permissions.assert_not_called()
        house2.set_permissions.assert_not_called()

    @pytest.mark.asyncio
    async def test_follower_not_found_skipped(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        guild_data["player_follows"] = {"999": {"target": "10", "stealth": False}}
        guild.get_member = lambda mid: None

        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)
        house1.set_permissions.assert_not_called()

    @pytest.mark.asyncio
    async def test_follower_wrong_role_skipped(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        follower.roles = []
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        house1.set_permissions.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_house_warning(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        # Follower in both houses
        def perms_any(member):
            if member.id == 20:
                return MagicMock(send_messages=True)
            return MagicMock(send_messages=False)
        house1.permissions_for = perms_any
        house2.permissions_for = perms_any

        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        house1.set_permissions.assert_not_called()
        house2.set_permissions.assert_not_called()
        log_ch.send.assert_called()
        warn_msg = log_ch.send.call_args[0][0]
        assert "multiple houses" in warn_msg

    @pytest.mark.asyncio
    async def test_log_embed_sent(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        assert log_ch.send.call_count >= 1
        embed_kw = log_ch.send.call_args_list[-1].kwargs.get("embed")
        assert embed_kw is not None
        assert embed_kw.title == "Follower moved"

    @pytest.mark.asyncio
    async def test_no_log_channel_no_error(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        guild.text_channels = []
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

    @pytest.mark.asyncio
    async def test_no_category_no_error(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        guild.categories = []
        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

    @pytest.mark.asyncio
    async def test_multiple_followers_all_move(self):
        guild, guild_data, target, follower, house1, house2, log_ch, alive_role = self._build_setup()
        follower2 = _make_member(30, roles=[alive_role])
        guild.get_member = lambda mid: {10: target, 20: follower, 30: follower2}.get(mid)
        guild_data["player_follows"]["30"] = {"target": "10", "stealth": False}

        def perms_h1(member):
            if member.id in (20, 30):
                return MagicMock(send_messages=True)
            return MagicMock(send_messages=False)
        house1.permissions_for = perms_h1

        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        assert house1.set_permissions.call_count == 2
        assert house2.set_permissions.call_count == 2

    @pytest.mark.asyncio
    async def test_unrelated_follower_not_moved(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        # Add follower for a different target
        guild_data["player_follows"]["50"] = {"target": "99", "stealth": False}
        follower_other = _make_member(50, roles=[_make_role("Alive")])
        guild.get_member = lambda mid: {10: target, 20: follower, 50: follower_other}.get(mid)

        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        # Only follower (20) should be moved, not follower_other (50)
        assert house1.set_permissions.call_count == 1
        assert house2.set_permissions.call_count == 1

    @pytest.mark.asyncio
    async def test_sponsor_follower_moves(self):
        guild, guild_data, target, follower, house1, house2, log_ch, _ = self._build_setup()
        sponsor_role = next(r for r in guild.roles if r.name == "Sponsor")
        follower.roles = [sponsor_role]

        await surveillance_cog.Surveillance._move_followers(None, guild, guild_data, target)

        house1.set_permissions.assert_called_once()
        house2.set_permissions.assert_called_once()


# ── _remove_followers_from_house ─────────────────────────────────────────────

class TestRemoveFollowersFromHouse:
    @pytest.mark.asyncio
    async def test_removes_followers_from_house(self):
        guild = _make_guild()
        alive_role = _make_role("Alive")
        target = _make_member(10, roles=[alive_role])
        follower = _make_member(20, roles=[alive_role])

        house = _make_channel(100, "house-1")
        house.permissions_for = lambda m: MagicMock(send_messages=(m.id == 20))

        guild.get_member = lambda mid: {10: target, 20: follower}.get(mid)

        guild_data = _make_guild_data(follows={"20": {"target": "10", "stealth": False}})

        await surveillance_cog.Surveillance._remove_followers_from_house(
            None, guild, guild_data, [target], house
        )

        house.set_permissions.assert_called_once_with(follower, overwrite=None)
        house.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_stealth_no_messages(self):
        guild = _make_guild()
        alive_role = _make_role("Alive")
        target = _make_member(10, roles=[alive_role])
        follower = _make_member(20, roles=[alive_role])

        house = _make_channel(100, "house-1")
        house.permissions_for = lambda m: MagicMock(send_messages=(m.id == 20))

        guild.get_member = lambda mid: {10: target, 20: follower}.get(mid)

        guild_data = _make_guild_data(follows={"20": {"target": "10", "stealth": False}})

        await surveillance_cog.Surveillance._remove_followers_from_house(
            None, guild, guild_data, [target], house, is_stealth=True
        )

        house.set_permissions.assert_called_once()
        house.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_followers_no_action(self):
        guild = _make_guild()
        alive_role = _make_role("Alive")
        target = _make_member(10, roles=[alive_role])

        house = _make_channel(100, "house-1")
        house.set_permissions = AsyncMock()

        guild_data = _make_guild_data(follows={})

        await surveillance_cog.Surveillance._remove_followers_from_house(
            None, guild, guild_data, [target], house
        )

        house.set_permissions.assert_not_called()

    @pytest.mark.asyncio
    async def test_follower_not_in_house_not_removed(self):
        guild = _make_guild()
        alive_role = _make_role("Alive")
        target = _make_member(10, roles=[alive_role])
        follower = _make_member(20, roles=[alive_role])

        house = _make_channel(100, "house-1")
        house.permissions_for = lambda m: MagicMock(send_messages=False)

        guild.get_member = lambda mid: {10: target, 20: follower}.get(mid)

        guild_data = _make_guild_data(follows={"20": {"target": "10", "stealth": False}})

        await surveillance_cog.Surveillance._remove_followers_from_house(
            None, guild, guild_data, [target], house
        )

        house.set_permissions.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_targets_cleanup(self):
        guild = _make_guild()
        alive_role = _make_role("Alive")
        target1 = _make_member(10, roles=[alive_role])
        target2 = _make_member(11, roles=[alive_role])
        follower1 = _make_member(20, roles=[alive_role])
        follower2 = _make_member(21, roles=[alive_role])

        house = _make_channel(100, "house-1")
        house.permissions_for = lambda m: MagicMock(send_messages=(m.id in (20, 21)))

        guild.get_member = lambda mid: {10: target1, 11: target2, 20: follower1, 21: follower2}.get(mid)

        guild_data = _make_guild_data(follows={
            "20": {"target": "10", "stealth": False},
            "21": {"target": "11", "stealth": False},
        })

        await surveillance_cog.Surveillance._remove_followers_from_house(
            None, guild, guild_data, [target1, target2], house
        )

        assert house.set_permissions.call_count == 2


# ── after_movement_update ────────────────────────────────────────────────────

class TestAfterMovementUpdate:
    @pytest.mark.asyncio
    async def test_calls_move_followers_with_target(self):
        with patch("cogs.surveillance_cog.load_guild_data") as mock_load:
            mock_load.return_value = _make_guild_data()
            guild = _make_guild()
            target = _make_member(10)
            ctx = MagicMock()
            ctx.guild = guild
            ctx.bot = MagicMock()

            mock_cog = AsyncMock()
            ctx.bot.get_cog.return_value = mock_cog

            await surveillance_cog.after_movement_update(ctx, target_member=target)

            mock_cog.after_movement_update.assert_called_once_with(
                guild, mock_load.return_value, target_member=target
            )

    @pytest.mark.asyncio
    async def test_calls_without_target(self):
        with patch("cogs.surveillance_cog.load_guild_data") as mock_load:
            mock_load.return_value = _make_guild_data()
            guild = _make_guild()
            ctx = MagicMock()
            ctx.guild = guild
            ctx.bot = MagicMock()

            mock_cog = AsyncMock()
            ctx.bot.get_cog.return_value = mock_cog

            await surveillance_cog.after_movement_update(ctx)

            mock_cog.after_movement_update.assert_called_once_with(
                guild, mock_load.return_value, target_member=None
            )

    @pytest.mark.asyncio
    async def test_no_guild_data_no_crash(self):
        with patch("cogs.surveillance_cog.load_guild_data") as mock_load:
            mock_load.return_value = None
            ctx = MagicMock()
            ctx.guild = _make_guild()

            await surveillance_cog.after_movement_update(ctx)

    @pytest.mark.asyncio
    async def test_no_surveillance_cog_no_crash(self):
        with patch("cogs.surveillance_cog.load_guild_data") as mock_load:
            mock_load.return_value = _make_guild_data()
            ctx = MagicMock()
            ctx.guild = _make_guild()
            ctx.bot = MagicMock()
            ctx.bot.get_cog.return_value = None

            await surveillance_cog.after_movement_update(ctx, target_member=_make_member(10))


# ── Import chain & no duplicates ─────────────────────────────────────────────

class TestImportChain:
    def test_moving_cog_imports_from_surveillance(self):
        import importlib
        mod = importlib.import_module("cogs.moving_cog")
        assert hasattr(mod, "after_movement_update")

    def test_no_track_stalk_utils_import(self):
        import importlib
        mod = importlib.import_module("cogs.moving_cog")
        src = importlib.util.find_spec("cogs.moving_cog").origin
        with open(src, encoding="utf-8") as f:
            content = f.read()
        assert "track_stalk_utils" not in content

    def test_no_duplicate_follow_in_moving(self):
        import importlib
        mod = importlib.import_module("cogs.moving_cog")
        assert not hasattr(mod.Moving, "follow")
        assert not hasattr(mod.Moving, "unfollow")
        assert not hasattr(mod.Moving, "followlist")
        assert not hasattr(mod.Moving, "unfollowall")
        assert not hasattr(mod.Moving, "_move_followers")
        assert not hasattr(mod.Moving, "_check_cycle")
        assert not hasattr(mod.Moving, "_save_follows")
        assert not hasattr(mod.Moving, "_remove_follows_for")

    def test_surveillance_has_all_follow_commands(self):
        import importlib
        mod = importlib.import_module("cogs.surveillance_cog")
        assert hasattr(mod.Surveillance, "follow")
        assert hasattr(mod.Surveillance, "unfollow")
        assert hasattr(mod.Surveillance, "followlist")
        assert hasattr(mod.Surveillance, "unfollowall")
        assert hasattr(mod.Surveillance, "_move_followers")
        assert hasattr(mod.Surveillance, "_check_follow_cycle")
        assert hasattr(mod.Surveillance, "_save_follows")
        assert hasattr(mod.Surveillance, "_remove_follows_for")
        assert hasattr(mod.Surveillance, "_remove_followers_from_house")

    def test_surveillance_has_track_stalk(self):
        import importlib
        mod = importlib.import_module("cogs.surveillance_cog")
        assert hasattr(mod.Surveillance, "track")
        assert hasattr(mod.Surveillance, "untrack")
        assert hasattr(mod.Surveillance, "stalk")
        assert hasattr(mod.Surveillance, "unstalk")
        assert hasattr(mod.Surveillance, "unstalkall")
        assert hasattr(mod.Surveillance, "stalklist")

    def test_after_movement_update_in_surveillance_module(self):
        import importlib
        mod = importlib.import_module("cogs.surveillance_cog")
        assert callable(getattr(mod, "after_movement_update", None))

    def test_no_track_stalk_utils_file(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "track_stalk_utils.py")
        assert not os.path.exists(path)

    def test_data_utils_has_player_follows(self):
        from cogs.data_utils import base_variables
        assert "player_follows" in base_variables
        assert base_variables["player_follows"] == {}

    def test_moving_cog_has_all_movement_commands(self):
        import importlib
        mod = importlib.import_module("cogs.moving_cog")
        assert hasattr(mod.Moving, "add")
        assert hasattr(mod.Moving, "remove")
        assert hasattr(mod.Moving, "move")
        assert hasattr(mod.Moving, "renmove")
        assert hasattr(mod.Moving, "knock")
        assert hasattr(mod.Moving, "renknock")
        assert hasattr(mod.Moving, "pendingknock")
        assert hasattr(mod.Moving, "pcadd")
        assert hasattr(mod.Moving, "pcremove")
        assert hasattr(mod.Moving, "addhere")

    def test_help_surveillance_exists(self):
        import importlib
        mod = importlib.import_module("cogs.help_misc_cog")
        assert hasattr(mod.Other, "help_surveillance")
