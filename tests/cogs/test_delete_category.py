"""Tests for `.deletecategory` and its category lookup helper."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs import help_misc_cog


def _make_category(name="ROLES", category_id=100, channel_names=("rc-1", "rc-2")):
    category = MagicMock()
    category.name = name
    category.id = category_id
    category.channels = []
    for channel_name in channel_names:
        channel = MagicMock()
        channel.name = channel_name
        channel.delete = AsyncMock()
        category.channels.append(channel)
    category.delete = AsyncMock()
    return category


def _make_ctx(categories, admin=True, current_category=None):
    ctx = MagicMock()
    ctx.author.guild_permissions.administrator = admin
    ctx.guild.categories = categories
    ctx.channel.category = current_category
    ctx.send = AsyncMock()
    return ctx


class _FakeConfirmView:
    def __init__(self, ctx, confirmed=True):
        self.ctx = ctx
        self.confirmed = confirmed
        self.message = None

    async def wait(self):
        return True


async def _run_command(ctx, category=None, confirmed=True):
    def factory(view_ctx):
        return _FakeConfirmView(view_ctx, confirmed=confirmed)

    cog = help_misc_cog.Other(MagicMock())
    with patch.object(help_misc_cog, "ConfirmDeleteView", factory):
        await help_misc_cog.Other.deletecategory.callback(
            cog, ctx, category=category
        )


class TestFindCategory:
    def test_exact_name(self):
        category = _make_category("ROLES")
        found, error = help_misc_cog.find_category(MagicMock(categories=[category]), "ROLES")
        assert found is category
        assert error is None

    def test_case_insensitive(self):
        category = _make_category("ROLES")
        found, error = help_misc_cog.find_category(MagicMock(categories=[category]), "roles")
        assert found is category
        assert error is None

    def test_partial_name(self):
        category = _make_category("DEAD ROLECHATS")
        found, error = help_misc_cog.find_category(MagicMock(categories=[category]), "dead")
        assert found is category
        assert error is None

    def test_by_id(self):
        category = _make_category("ROLES", category_id=4242)
        found, error = help_misc_cog.find_category(MagicMock(categories=[category]), "4242")
        assert found is category
        assert error is None

    def test_ambiguous_partial_returns_error(self):
        categories = [
            _make_category("RC ONE", category_id=1),
            _make_category("RC TWO", category_id=2),
        ]
        found, error = help_misc_cog.find_category(MagicMock(categories=categories), "rc")
        assert found is None
        assert "Multiple categories match" in error
        assert "RC ONE" in error and "RC TWO" in error

    def test_missing_returns_error(self):
        found, error = help_misc_cog.find_category(MagicMock(categories=[]), "nope")
        assert found is None
        assert "couldn't find" in error


class TestConfirmDeleteView:
    @pytest.mark.asyncio
    async def test_initialises_ui_children(self):
        view = help_misc_cog.ConfirmDeleteView(MagicMock())
        assert isinstance(view, discord.ui.View)
        assert len(view.children) == 2
        assert view.timeout == 30


class TestDeleteCategoryCommand:
    @pytest.mark.asyncio
    async def test_deletes_category_and_every_channel(self):
        category = _make_category()
        ctx = _make_ctx([category])

        await _run_command(ctx, category="ROLES")

        for channel in category.channels:
            channel.delete.assert_awaited_once()
        category.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_current_channel_category_without_argument(self):
        category = _make_category()
        ctx = _make_ctx([category], current_category=category)

        await _run_command(ctx)

        category.delete.assert_awaited_once()
        for channel in category.channels:
            channel.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_keeps_everything(self):
        category = _make_category()
        ctx = _make_ctx([category])

        await _run_command(ctx, category="ROLES", confirmed=False)

        category.delete.assert_not_awaited()
        for channel in category.channels:
            channel.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_admin_denied(self):
        category = _make_category()
        ctx = _make_ctx([category], admin=False)

        await _run_command(ctx, category="ROLES")

        category.delete.assert_not_awaited()
        ctx.send.assert_awaited_once()
        assert "perms" in ctx.send.await_args.args[0]

    @pytest.mark.asyncio
    async def test_no_category_and_no_argument(self):
        ctx = _make_ctx([], current_category=None)

        await _run_command(ctx)

        ctx.send.assert_awaited_once()
        assert "doesn't have a category" in ctx.send.await_args.args[0]

    @pytest.mark.asyncio
    async def test_unknown_category_reports_error(self):
        ctx = _make_ctx([])

        await _run_command(ctx, category="nope")

        ctx.send.assert_awaited_once()
        assert "couldn't find" in ctx.send.await_args.args[0]

    @pytest.mark.asyncio
    async def test_continues_after_a_channel_fails(self):
        category = _make_category(channel_names=("rc-1", "rc-2"))
        category.channels[0].delete = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(), "boom")
        )
        ctx = _make_ctx([category])

        await _run_command(ctx, category="ROLES")

        category.channels[1].delete.assert_awaited_once()
        category.delete.assert_awaited_once()
        texts = [call.args[0] for call in ctx.send.await_args_list if call.args]
        assert any("rc-1" in text for text in texts)
