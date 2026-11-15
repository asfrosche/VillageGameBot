"""Tests for .role check: no channel argument, players and sponsors check their own RoleChat, no prompts."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from cogs import role_package_cog

GUILD_DATA = {"alive_role_name": "Alive", "sponsor_role_name": "Sponsor", "overseer_role_name": "Overseer"}


def make_ctx(roles, *, admin=False, channel_is_rc=True):
    alive = MagicMock()
    alive.name = "Alive"
    sponsor = MagicMock()
    sponsor.name = "Sponsor"
    overseer = MagicMock()
    overseer.name = "Overseer"
    guild = MagicMock()
    guild.roles = [alive, sponsor, overseer]
    ctx = MagicMock()
    ctx.guild = guild
    ctx.channel = MagicMock()
    ctx.channel.id = 77
    ctx.author = MagicMock()
    ctx.author.roles = [{"alive": alive, "sponsor": sponsor, "overseer": overseer}[r] for r in roles]
    ctx.author.guild_permissions.administrator = admin
    ctx.author.guild = guild
    ctx.send = AsyncMock()
    return ctx, alive, sponsor, overseer


def run(ctx, is_rc=True):
    cog = object.__new__(role_package_cog.RolePackageCog)
    cog.bot = MagicMock()
    cog.bot.wait_for = AsyncMock(side_effect=AssertionError("no prompt should be sent"))
    display = AsyncMock()
    cog._role_check_display = display
    cog._guild_data = MagicMock(return_value=GUILD_DATA)
    with patch.object(role_package_cog, "get_role_package", return_value=None), \
            patch.object(cog, "_is_role_chat", return_value=is_rc):
        asyncio.run(role_package_cog.RolePackageCog.role_check.callback(cog, ctx))
    return display, cog.bot.wait_for


class TestRoleCheck:
    def test_alive_player_checks_their_own_role_chat_without_a_prompt(self):
        ctx, *_ = make_ctx(["alive"])
        display, wait_for = run(ctx, is_rc=True)
        display.assert_awaited_once()
        assert display.await_args.args[1] is ctx.channel
        wait_for.assert_not_awaited()

    def test_sponsor_checks_their_own_role_chat_without_a_prompt(self):
        ctx, *_ = make_ctx(["sponsor"])
        display, wait_for = run(ctx, is_rc=True)
        display.assert_awaited_once()
        wait_for.assert_not_awaited()

    def test_player_outside_a_role_chat_is_refused(self):
        ctx, *_ = make_ctx(["alive"])
        display, wait_for = run(ctx, is_rc=False)
        display.assert_not_awaited()
        assert "Only players and sponsors" in ctx.send.await_args.args[0]

    def test_overseer_checks_the_channel_without_a_prompt(self):
        ctx, *_ = make_ctx(["overseer"])
        display, wait_for = run(ctx, is_rc=False)
        display.assert_awaited_once()
        wait_for.assert_not_awaited()

    def test_admin_checks_the_channel_without_a_prompt(self):
        ctx, *_ = make_ctx([], admin=True)
        display, wait_for = run(ctx, is_rc=False)
        display.assert_awaited_once()
        wait_for.assert_not_awaited()

    def test_someone_with_no_player_or_staff_role_is_refused(self):
        ctx, *_ = make_ctx([])
        display, wait_for = run(ctx, is_rc=True)
        display.assert_not_awaited()
        assert "Only players and sponsors" in ctx.send.await_args.args[0]

    def test_channel_argument_is_no_longer_accepted(self):
        import inspect
        params = list(inspect.signature(role_package_cog.RolePackageCog.role_check.callback).parameters)
        assert params == ["self", "ctx"]
