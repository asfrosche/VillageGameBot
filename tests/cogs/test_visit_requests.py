"""Tests for player visit requests: `.move` / `.knock` by number or name, posted to the actions log
for Overseers to Confirm or Deny."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import actions_logging_cog, moving_cog
from utils.house_lookup import house_match


def house(name):
    ch = MagicMock()
    ch.name = name
    ch.mention = f"#{name}"
    return ch


HOUSES = [
    house("🏡│house-23"),
    house("🏡│house-7"),
    house("🏡│tower"),
    house("🏡│north-tower"),
    house("🏡│harbour-view"),
    house("🏡│harbour-lane"),
]


class TestHouseMatch:
    def test_number_matches_house_dash_number(self):
        ch, err = house_match(HOUSES, "23")
        assert err is None and ch.name == "🏡│house-23"

    def test_hash_prefix_is_ignored(self):
        ch, _ = house_match(HOUSES, "#7")
        assert ch.name == "🏡│house-7"

    def test_unknown_number_reports_it(self):
        ch, err = house_match(HOUSES, "99")
        assert ch is None and "99" in err

    def test_exact_name_matches(self):
        ch, _ = house_match(HOUSES, "tower")
        assert ch.name == "🏡│tower"  # exact beats the partial match to north-tower

    def test_partial_name_matches_when_unique(self):
        ch, _ = house_match(HOUSES, "north")
        assert ch.name == "🏡│north-tower"

    def test_ambiguous_partial_name_lists_the_options(self):
        ch, err = house_match(HOUSES, "harbour")
        assert ch is None
        assert "harbour-view" in err and "harbour-lane" in err

    def test_unknown_name_reports_it(self):
        ch, err = house_match(HOUSES, "castle")
        assert ch is None and "castle" in err

    def test_empty_query_asks_for_one(self):
        ch, err = house_match(HOUSES, "  ")
        assert ch is None and err


def player_ctx(channel_category, roles, guild, guild_data_roles=None):
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = MagicMock()
    ctx.author.roles = roles
    ctx.author.guild_permissions.administrator = False
    ctx.channel = MagicMock()
    ctx.channel.category = channel_category
    ctx.channel.mention = "#rc"
    ctx.message.created_at.timestamp.return_value = 1_700_000_000
    ctx.message.jump_url = "https://discord.test/m"
    ctx.send = AsyncMock()
    return ctx


GUILD_DATA = {
    "rc_category_name": "ROLES",
    "alt_category_name": "ALTs",
    "dead_rc_category_name": "DEAD RC",
    "alive_role_name": "Alive",
    "sponsor_role_name": "Sponsor",
    "alt_role_name": "Alt",
    "dead_role_name": "Dead",
    "houses_category_name": "HOUSES",
    "house_prefix": "🏡│house-",
}


def make_guild(alive, categories):
    guild = MagicMock()
    guild.roles = [alive]
    guild.categories = categories
    return guild


class TestPlayerRouting:
    def _setup(self, *, admin=False, in_rc=True):
        alive = MagicMock()
        alive.name = "Alive"
        rc = MagicMock()
        rc.name = "ROLES"
        houses = MagicMock()
        houses.name = "HOUSES"
        houses.channels = HOUSES
        guild = make_guild(alive, [rc, houses])
        ctx = player_ctx(rc if in_rc else None, [alive], guild)
        ctx.author.guild_permissions.administrator = admin
        bot = MagicMock()
        actions = MagicMock()
        actions.create_visit_request = AsyncMock(return_value=True)
        bot.get_cog.return_value = actions
        cog = object.__new__(moving_cog.Moving)
        cog.bot = bot
        return cog, ctx, actions

    def test_player_move_by_name_is_sent_for_approval(self):
        cog, ctx, actions = self._setup()
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(moving_cog.Moving.move.callback(cog, ctx, "tower"))
        actions.create_visit_request.assert_awaited_once()
        args = actions.create_visit_request.await_args.args
        assert args[1] == "move" and args[2].name == "🏡│tower" and args[3] == "tower"

    def test_player_knock_by_number_is_sent_for_approval(self):
        cog, ctx, actions = self._setup()
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(moving_cog.Moving.knock.callback(cog, ctx, "23"))
        args = actions.create_visit_request.await_args.args
        assert args[1] == "knock" and args[2].name == "🏡│house-23"

    def test_player_outside_a_rolechat_is_refused(self):
        cog, ctx, actions = self._setup(in_rc=False)
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(moving_cog.Moving.move.callback(cog, ctx, "23"))
        actions.create_visit_request.assert_not_awaited()
        assert "RoleChat" in ctx.send.await_args.args[0]

    def test_admin_still_acts_immediately_and_is_not_routed(self):
        cog, ctx, actions = self._setup(admin=True)
        cog._request_visit = AsyncMock()
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(moving_cog.Moving.move.callback(cog, ctx, "99"))
        cog._request_visit.assert_not_awaited()
        assert "Channel not found" in ctx.send.await_args.args[0]


class TestRequestPosting:
    def _build(self):
        async def make():
            log_message = MagicMock()
            log_message.edit = AsyncMock()
            user_message = MagicMock()
            user_message.edit = AsyncMock()
            log_channel = MagicMock()
            log_channel.name = "actions-log"
            log_channel.send = AsyncMock(return_value=log_message)
            guild = MagicMock()
            guild.text_channels = [log_channel]
            guild.roles = []
            ctx = player_ctx(MagicMock(), [], guild)
            ctx.author.display_name = "coconut"
            ctx.author.display_avatar.url = "https://cdn.test/a.png"
            ctx.channel.send = AsyncMock(return_value=user_message)
            cog = object.__new__(actions_logging_cog.ActionsLogging)
            house_ch = house("🏡│tower")
            data = dict(GUILD_DATA, actions_log_channel_name="actions-log", overseer_role_name="Overseer")
            with patch.object(actions_logging_cog, "load_guild_data", return_value=data):
                ok = await cog.create_visit_request(ctx, "move", house_ch, "tower")
            return ok, log_channel, log_message, user_message, ctx
        return asyncio.run(make())

    def test_request_is_posted_to_the_log_with_buttons_for_overseers(self):
        ok, log_channel, log_message, user_message, ctx = self._build()
        assert ok is True
        log_channel.send.assert_awaited_once()
        log_view = log_message.edit.await_args.kwargs["view"]
        assert isinstance(log_view, actions_logging_cog.VisitActionView)
        assert log_view.approver_only is True
        assert log_view.action_type == "move"
        assert log_view.requester is ctx.author

    def test_player_gets_a_cancel_only_view_in_their_channel(self):
        ok, log_channel, log_message, user_message, ctx = self._build()
        user_view = user_message.edit.await_args.kwargs["view"]
        assert isinstance(user_view, actions_logging_cog.CancelOnlyView)

    def test_missing_log_channel_is_reported(self):
        async def make():
            guild = MagicMock()
            guild.text_channels = []
            guild.roles = []
            ctx = player_ctx(MagicMock(), [], guild)
            cog = object.__new__(actions_logging_cog.ActionsLogging)
            with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, actions_log_channel_name="missing")):
                return await cog.create_visit_request(ctx, "move", house("🏡│tower"), "tower"), ctx
        ok, ctx = asyncio.run(make())
        assert ok is False
        assert "not set up" in ctx.send.await_args.args[0]


def interaction(user, guild):
    inter = MagicMock()
    inter.user = user
    inter.guild = guild
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.response.edit_message = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.client = MagicMock()
    return inter


class TestApproval:
    def _view(self, requester):
        async def make():
            view = actions_logging_cog.VisitActionView(
                user_embed=MagicMock(channel=MagicMock()),
                log_embed=MagicMock(),
                user_embed_obj=MagicMock(),
                log_embed_obj=MagicMock(),
                target_house=house("🏡│tower"),
                house_number=None,
                action_type="move",
                requester=requester,
                approver_only=True,
            )
            return view
        return asyncio.run(make())

    def _guild(self):
        overseer = MagicMock()
        overseer.name = "Overseer"
        guild = MagicMock()
        guild.roles = [overseer]
        return guild, overseer

    def test_player_cannot_approve_their_own_request(self):
        guild, overseer = self._guild()
        requester = MagicMock()
        requester.roles = []
        requester.guild_permissions.administrator = False
        view = self._view(requester)
        inter = interaction(requester, guild)
        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")):
            ok = asyncio.run(view._check_approver(inter))
        assert ok is False
        assert "Only Overseers" in inter.response.send_message.await_args.args[0]

    def test_overseer_can_approve(self):
        guild, overseer = self._guild()
        requester = MagicMock()
        requester.roles = []
        requester.guild_permissions.administrator = False
        clicker = MagicMock()
        clicker.roles = [overseer]
        clicker.guild_permissions.administrator = False
        view = self._view(requester)
        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")):
            ok = asyncio.run(view._check_approver(interaction(clicker, guild)))
        assert ok is True

    def test_approved_visit_runs_for_the_requester_not_the_clicker(self):
        guild, overseer = self._guild()
        requester = MagicMock(name="requester")
        requester.roles = []
        requester.guild_permissions.administrator = False
        clicker = MagicMock(name="overseer")
        clicker.roles = [overseer]
        clicker.guild_permissions.administrator = False
        view = self._view(requester)
        moving = MagicMock()
        moving.process_move = AsyncMock()
        bot_client = MagicMock()
        bot_client.get_cog.return_value = moving
        inter = interaction(clicker, guild)
        inter.client = bot_client
        inter.message = MagicMock()
        view.update_embed = AsyncMock()
        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")):
            asyncio.run(view._execute_visit(inter))
        ctx = moving.process_move.await_args.args[0]
        assert ctx.author is requester


class TestOverseersAreNotLogged:
    def _overseer_ctx(self):
        alive = MagicMock()
        alive.name = "Alive"
        overseer = MagicMock()
        overseer.name = "Overseer"
        rc = MagicMock()
        rc.name = "ROLES"
        houses = MagicMock()
        houses.name = "HOUSES"
        houses.channels = HOUSES
        guild = make_guild(alive, [rc, houses])
        guild.roles = [alive, overseer]
        ctx = player_ctx(rc, [overseer], guild)
        ctx.author.guild_permissions.administrator = False  # Overseer role only, no admin permission
        bot = MagicMock()
        actions = MagicMock()
        actions.create_visit_request = AsyncMock(return_value=True)
        bot.get_cog.return_value = actions
        cog = object.__new__(moving_cog.Moving)
        cog.bot = bot
        return cog, ctx, actions

    def test_overseer_move_is_not_sent_to_the_actions_log(self):
        cog, ctx, actions = self._overseer_ctx()
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(moving_cog.Moving.move.callback(cog, ctx, "99"))
        actions.create_visit_request.assert_not_awaited()
        assert "Channel not found" in ctx.send.await_args.args[0]

    def test_overseer_knock_is_not_sent_to_the_actions_log(self):
        cog, ctx, actions = self._overseer_ctx()
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(moving_cog.Moving.knock.callback(cog, ctx, "nosuchhouse"))
        actions.create_visit_request.assert_not_awaited()

    def test_player_without_overseer_role_is_still_sent_for_approval(self):
        cog, ctx, actions = TestPlayerRouting()._setup()
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(moving_cog.Moving.move.callback(cog, ctx, "tower"))
        actions.create_visit_request.assert_awaited_once()


class TestClosestHouse:
    def test_typo_finds_the_closest_house(self):
        from utils.house_lookup import closest_house
        clinic = house("🏥│clinic")
        assert closest_house([clinic, house("🏡│tower")], "clinc") is clinic

    def test_numbers_never_get_a_suggestion(self):
        from utils.house_lookup import closest_house
        assert closest_house(HOUSES, "99") is None

    def test_unrelated_text_gets_no_suggestion(self):
        from utils.house_lookup import closest_house
        assert closest_house(HOUSES, "castle") is None

    def test_clinic_and_house_18_resolve_directly(self):
        clinic = house("🏥│clinic")
        h18 = house("🏡│house-18")
        assert house_match([clinic, h18], "clinic")[0] is clinic
        assert house_match([clinic, h18], "18")[0] is h18


class TestSuggestionConfirmation:
    def _ctx(self):
        alive = MagicMock()
        alive.name = "Alive"
        rc = MagicMock()
        rc.name = "ROLES"
        clinic = house("🏥│clinic")
        houses = MagicMock()
        houses.name = "HOUSES"
        houses.channels = [clinic]
        guild = make_guild(alive, [rc, houses])
        ctx = player_ctx(rc, [alive], guild)
        return ctx, clinic

    def _run(self, ctx, cog, query, answer):
        async def fake_confirm(self_, ctx_, q, suggestion):
            return answer
        cog._confirm_suggestion = fake_confirm.__get__(cog)
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            asyncio.run(moving_cog.Moving._request_visit(cog, ctx, "knock", query))

    def test_typo_is_suggested_and_a_yes_sends_the_request_for_that_house(self):
        ctx, clinic = self._ctx()
        actions = MagicMock()
        actions.create_visit_request = AsyncMock(return_value=True)
        cog = object.__new__(moving_cog.Moving)
        cog.bot = MagicMock()
        cog.bot.get_cog.return_value = actions
        self._run(ctx, cog, "clinc", True)
        args = actions.create_visit_request.await_args.args
        assert args[2] is clinic

    def test_a_no_sends_nothing(self):
        ctx, clinic = self._ctx()
        actions = MagicMock()
        actions.create_visit_request = AsyncMock(return_value=True)
        cog = object.__new__(moving_cog.Moving)
        cog.bot = MagicMock()
        cog.bot.get_cog.return_value = actions
        self._run(ctx, cog, "clinc", False)
        actions.create_visit_request.assert_not_awaited()


class TestRenamedHouseCommands:
    def test_player_renknock_goes_through_the_request_path(self):
        alive = MagicMock()
        alive.name = "Alive"
        rc = MagicMock()
        rc.name = "ROLES"
        guild = make_guild(alive, [rc])
        ctx = player_ctx(rc, [alive], guild)
        ctx.author.guild_permissions.administrator = False
        cog = object.__new__(moving_cog.Moving)
        cog._request_visit = AsyncMock()
        asyncio.run(moving_cog.Moving.renknock.callback(cog, ctx, "clinic"))
        cog._request_visit.assert_awaited_once_with(ctx, "renknock", "clinic")

    def test_player_renmove_goes_through_the_request_path(self):
        alive = MagicMock()
        alive.name = "Alive"
        rc = MagicMock()
        rc.name = "ROLES"
        guild = make_guild(alive, [rc])
        ctx = player_ctx(rc, [alive], guild)
        ctx.author.guild_permissions.administrator = False
        cog = object.__new__(moving_cog.Moving)
        cog._request_visit = AsyncMock()
        asyncio.run(moving_cog.Moving.renmove.callback(cog, ctx, "clinic"))
        cog._request_visit.assert_awaited_once_with(ctx, "renmove", "clinic")


class TestConfirmMarksCompleted:
    def _view(self):
        async def make():
            return actions_logging_cog.VisitActionView(
                user_embed=MagicMock(channel=MagicMock(id=5)),
                log_embed=MagicMock(),
                user_embed_obj=MagicMock(),
                log_embed_obj=MagicMock(),
                target_house=house("🏡│tower"),
                house_number=None,
                action_type="knock",
                requester=MagicMock(),
                approver_only=True,
            )
        return asyncio.run(make())

    def _interaction(self, overseer_role):
        inter = MagicMock()
        inter.user.roles = [overseer_role]
        inter.user.guild_permissions.administrator = False
        inter.user.display_name = "ov"
        inter.guild.id = 1
        inter.guild.roles = [overseer_role]
        inter.response.defer = AsyncMock()
        inter.response.is_done = MagicMock(return_value=True)  # after defer
        inter.response.edit_message = AsyncMock(side_effect=AssertionError("must not use response after defer"))
        inter.response.send_message = AsyncMock()
        inter.message = MagicMock()
        inter.message.edit = AsyncMock()
        inter.followup.send = AsyncMock()
        return inter

    def test_confirm_marks_completed_and_removes_buttons_after_defer(self):
        overseer = MagicMock()
        overseer.name = "Overseer"
        view = self._view()
        inter = self._interaction(overseer)
        view._execute_visit = AsyncMock(return_value=True)
        view.update_embed = actions_logging_cog.ActionButtons.update_embed.__get__(view)
        view.user_embed.edit = AsyncMock()
        view.log_embed.edit = AsyncMock()
        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")), \
                patch.object(actions_logging_cog, "check_channel_warning", return_value=("", False)), \
                patch.object(actions_logging_cog, "save_guild_data"):
            asyncio.run(actions_logging_cog.VisitActionView.confirm_visit(view, inter, MagicMock()))
        assert inter.message.edit.await_count >= 1
        assert view.executed is True
        assert view.is_finished()

    def test_second_confirm_does_not_run_the_visit_again(self):
        overseer = MagicMock()
        overseer.name = "Overseer"
        view = self._view()
        view.executed = True
        inter = self._interaction(overseer)
        view._execute_visit = AsyncMock(return_value=True)
        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")), \
                patch.object(actions_logging_cog, "check_channel_warning", return_value=("", False)):
            asyncio.run(actions_logging_cog.VisitActionView.confirm_visit(view, inter, MagicMock()))
        view._execute_visit.assert_not_awaited()
        assert "already" in inter.response.send_message.await_args.args[0]


class TestDoubleClickIsRefused:
    def test_two_confirms_at_once_run_the_visit_once(self):
        overseer = MagicMock()
        overseer.name = "Overseer"
        view = TestConfirmMarksCompleted()._view()
        inter = TestConfirmMarksCompleted()._interaction(overseer)
        calls = []

        async def slow_execute(interaction):
            calls.append(1)
            await asyncio.sleep(0.05)  # the visit is still running when the second click arrives
            return True

        view._execute_visit = slow_execute
        view.update_embed = AsyncMock()
        second = TestConfirmMarksCompleted()._interaction(overseer)

        async def both():
            await asyncio.gather(
                actions_logging_cog.VisitActionView.confirm_visit(view, inter, MagicMock()),
                actions_logging_cog.VisitActionView.confirm_visit(view, second, MagicMock()),
            )

        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")), \
                patch.object(actions_logging_cog, "check_channel_warning", return_value=("", False)):
            asyncio.run(both())
        assert len(calls) == 1
        assert "in progress" in second.response.send_message.await_args.args[0] or "already" in second.response.send_message.await_args.args[0]

    def test_deny_after_confirm_is_refused(self):
        overseer = MagicMock()
        overseer.name = "Overseer"
        view = TestConfirmMarksCompleted()._view()
        view.executed = True
        inter = TestConfirmMarksCompleted()._interaction(overseer)
        view.update_embed = AsyncMock()
        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")):
            asyncio.run(actions_logging_cog.VisitActionView.deny_visit(view, inter, MagicMock()))
        view.update_embed.assert_not_awaited()


class TestConfirmButtonDisabled:
    def test_buttons_are_greyed_out_when_confirm_is_clicked(self):
        overseer = MagicMock()
        overseer.name = "Overseer"
        view = TestConfirmMarksCompleted()._view()
        inter = TestConfirmMarksCompleted()._interaction(overseer)
        seen = []

        async def capture_execute(interaction):
            seen.append([c.disabled for c in view.children])
            return True

        view._execute_visit = capture_execute
        view.update_embed = AsyncMock()
        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")),                 patch.object(actions_logging_cog, "check_channel_warning", return_value=("", False)):
            asyncio.run(actions_logging_cog.VisitActionView.confirm_visit(view, inter, MagicMock()))
        assert seen and all(seen[0])

    def test_buttons_come_back_if_the_visit_fails(self):
        overseer = MagicMock()
        overseer.name = "Overseer"
        view = TestConfirmMarksCompleted()._view()
        inter = TestConfirmMarksCompleted()._interaction(overseer)
        view._execute_visit = AsyncMock(return_value=False)
        with patch.object(actions_logging_cog, "load_guild_data", return_value=dict(GUILD_DATA, overseer_role_name="Overseer")),                 patch.object(actions_logging_cog, "check_channel_warning", return_value=("", False)):
            asyncio.run(actions_logging_cog.VisitActionView.confirm_visit(view, inter, MagicMock()))
        assert view.executed is False
        assert not any(c.disabled for c in view.children)


class TestVisitTargetsAreHousesOnly:
    def _ctx(self, target_channel):
        alive = MagicMock()
        alive.name = "Alive"
        houses = MagicMock()
        houses.name = "HOUSES"
        guild = MagicMock()
        guild.categories = [houses]
        guild.roles = [alive]
        guild.get_channel.return_value = target_channel
        ctx = player_ctx(None, [alive], guild)
        ctx.author.guild_permissions.administrator = True
        return ctx, houses

    def test_mention_of_a_non_house_channel_is_refused(self):
        other = MagicMock()
        other.category = MagicMock(name="ROLES")
        ctx, houses = self._ctx(other)
        cog = object.__new__(moving_cog.Moving)
        with patch.object(moving_cog, "load_guild_data", return_value=GUILD_DATA):
            result = asyncio.run(cog._house_from_arg(ctx, "<#123>"))
        assert result is None
        assert "Houses category" in ctx.send.await_args.args[0]

    def test_mention_of_a_house_is_accepted(self):
        ctx, houses = self._ctx(None)
        house_ch = MagicMock()
        house_ch.category = houses
        ctx.guild.get_channel.return_value = house_ch
        cog = object.__new__(moving_cog.Moving)
        with patch.object(moving_cog, "load_guild_data", return_value=dict(GUILD_DATA, houses_category_name="HOUSES")):
            result = asyncio.run(cog._house_from_arg(ctx, "<#123>"))
        assert result is house_ch
