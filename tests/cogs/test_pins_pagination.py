"""Tests for the .pins manager: permission gate, paging, and the component limit.

Discord caps a view at 25 components. Reorder and Delete render one button per pin, so with
more than about 21 pins the view used to raise. These tests pin down the paging that fixed it.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs import pins_cog


def run(coro):
    return asyncio.run(coro)


def make_interaction(manage_messages=True):
    interaction = MagicMock()
    interaction.user.guild_permissions.manage_messages = manage_messages
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    return interaction


def make_channel(pin_ids):
    channel = MagicMock()
    channel.name = "general"

    async def fetch_message(mid):
        msg = MagicMock()
        msg.content = f"pin {mid}"
        msg.embeds = []
        msg.attachments = []
        msg.author.mention = "@author"
        msg.jump_url = "https://discord.test/x"
        return msg

    channel.fetch_message = AsyncMock(side_effect=fetch_message)
    channel.pins = AsyncMock(return_value=[])
    return channel


class TestPageBounds:
    def make_view(self, page=0):
        async def build():
            view = pins_cog.PinsManagerView(MagicMock(), 1, 2)
            view.page = page
            return view
        return run(build())

    def test_first_page_of_forty_pins(self):
        view = self.make_view()
        assert view._page_bounds(list(range(40))) == (0, pins_cog.PAGE_SIZE, 3)

    def test_last_page_holds_the_remainder(self):
        view = self.make_view(page=2)
        start, end, pages = view._page_bounds(list(range(40)))
        assert (start, end, pages) == (30, 40, 3)

    def test_out_of_range_page_is_clamped_to_last(self):
        view = self.make_view(page=99)
        assert view._page_bounds(list(range(40)))[0] == 30
        assert view.page == 2

    def test_negative_page_is_clamped_to_first(self):
        view = self.make_view(page=-5)
        assert view._page_bounds(list(range(40)))[0] == 0
        assert view.page == 0

    def test_no_pins_is_one_empty_page(self):
        view = self.make_view()
        assert view._page_bounds([]) == (0, 0, 1)

    def test_page_size_keeps_a_full_page_under_discord_limit(self):
        # 15 pin buttons + Prev + Next + Undo + Reset + Done + Cancel must stay within 25.
        assert pins_cog.PAGE_SIZE + 2 + 4 <= 25
        assert pins_cog.PAGE_SIZE + 2 + 1 <= 25  # delete mode: Prev + Next + Back


class TestPermissionGate:
    def test_user_with_manage_messages_is_allowed(self):
        async def check():
            view = pins_cog.PinsManagerView(MagicMock(), 1, 2)
            return await view.interaction_check(make_interaction(manage_messages=True))
        assert run(check()) is True

    def test_user_without_manage_messages_is_refused_ephemerally(self):
        async def check():
            view = pins_cog.PinsManagerView(MagicMock(), 1, 2)
            interaction = make_interaction(manage_messages=False)
            allowed = await view.interaction_check(interaction)
            return allowed, interaction
        allowed, interaction = run(check())
        assert allowed is False
        interaction.response.send_message.assert_awaited_once()
        assert interaction.response.send_message.await_args.kwargs.get("ephemeral") is True

    def test_confirm_view_has_the_same_gate(self):
        async def check():
            view = pins_cog.ConfirmApplyView(MagicMock(), 1, 2)
            return await view.interaction_check(make_interaction(manage_messages=False))
        assert run(check()) is False


class TestReorderAndDeleteFit:
    def build(self, mode, pin_count):
        order = list(range(1, pin_count + 1))

        async def go():
            view = pins_cog.PinsManagerView(MagicMock(), 1, 2)
            view.mode = mode
            channel = make_channel(order)
            interaction = make_interaction()
            interaction.channel = channel
            guild_data = {"pins_manager": {"2": order}}
            with patch.object(pins_cog, "load_guild_data", return_value=guild_data), \
                    patch.object(pins_cog, "save_guild_data"):
                if mode == "reorder":
                    await view._build_reorder(interaction)
                else:
                    await view._build_delete(interaction)
            return view

        return run(go())

    def test_reorder_with_fifty_pins_fits_and_pages(self):
        view = self.build("reorder", 50)
        assert len(view.children) <= 25
        assert any(isinstance(c, pins_cog.PageButton) and c.delta == 1 for c in view.children)

    def test_delete_with_fifty_pins_fits_and_pages(self):
        view = self.build("delete", 50)
        assert len(view.children) <= 25
        page_buttons = [c for c in view.children if isinstance(c, pins_cog.PageButton)]
        assert len(page_buttons) == 2

    def test_small_list_has_no_paging_buttons(self):
        view = self.build("reorder", 5)
        assert not any(isinstance(c, pins_cog.PageButton) for c in view.children)

    def test_first_page_disables_prev(self):
        view = self.build("delete", 50)
        prev = next(c for c in view.children if isinstance(c, pins_cog.PageButton) and c.delta == -1)
        assert prev.disabled is True


class TestPageButton:
    def test_next_moves_forward_one_page_in_reorder_mode(self):
        async def go():
            view = pins_cog.PinsManagerView(MagicMock(), 1, 2)
            view.mode = "reorder"
            view._build_reorder = AsyncMock()
            view._build_delete = AsyncMock()
            button = pins_cog.PageButton("Next", 1, False)
            button._view = view
            await button.callback(make_interaction())
            return view
        view = run(go())
        assert view.page == 1
        view._build_reorder.assert_awaited_once()
        view._build_delete.assert_not_awaited()

    def test_prev_in_delete_mode_uses_delete_builder(self):
        async def go():
            view = pins_cog.PinsManagerView(MagicMock(), 1, 2)
            view.mode = "delete"
            view.page = 2
            view._build_reorder = AsyncMock()
            view._build_delete = AsyncMock()
            button = pins_cog.PageButton("Prev", -1, False)
            button._view = view
            await button.callback(make_interaction())
            return view
        view = run(go())
        assert view.page == 1
        view._build_delete.assert_awaited_once()
        view._build_reorder.assert_not_awaited()


class TestOneLookupPerRender:
    def test_forty_pins_render_with_one_pins_call_and_no_per_pin_fetches(self):
        order = list(range(1, 41))
        pinned = []
        for mid in order:
            m = MagicMock()
            m.id = mid
            m.content = f"pin {mid}"
            m.embeds = []
            m.attachments = []
            m.author.mention = "@a"
            m.jump_url = "https://discord.test/x"
            pinned.append(m)
        channel = make_channel(order)
        channel.pins = AsyncMock(return_value=pinned)

        async def go():
            view = pins_cog.PinsManagerView(MagicMock(), 1, 2)
            view.mode = "reorder"
            interaction = make_interaction()
            interaction.channel = channel
            with patch.object(pins_cog, "load_guild_data", return_value={"pins_manager": {"2": order}}), \
                    patch.object(pins_cog, "save_guild_data"):
                await view._build_reorder(interaction)
            return interaction

        interaction = asyncio.run(go())
        channel.pins.assert_awaited_once()
        channel.fetch_message.assert_not_awaited()
        interaction.response.edit_message.assert_awaited_once()
