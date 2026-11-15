import asyncio
from typing import Optional

import discord
from discord.ext import commands

from cogs.data_utils import load_guild_data, save_guild_data
from utils.embeds import error_embed, info_embed

# Reorder/Delete render one button per pin; Discord caps a view at 25 components,
# so those modes page through the pins this many at a time.
PAGE_SIZE = 15


def merge_reorder_sequence(sequence, order):
    """Pins clicked in the reorder view go first; unclicked pins keep their order after them."""
    sequence = list(sequence)
    return sequence + [mid for mid in order if mid not in sequence]


class PinsManagerView(discord.ui.View):
    def __init__(self, bot, guild_id: int, channel_id: int, mode: str = "main", sequence: list = None):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.mode = mode
        self.sequence = sequence or []
        self.page = 0
        self._pin_cache = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms and perms.manage_messages:
            return True
        await interaction.response.send_message("You need Manage Messages to change pins.", ephemeral=True)
        return False

    def _page_bounds(self, order):
        pages = max(1, -(-len(order) // PAGE_SIZE))
        self.page = min(max(self.page, 0), pages - 1)
        start = self.page * PAGE_SIZE
        return start, min(start + PAGE_SIZE, len(order)), pages

    def _add_nav(self, pages):
        if pages <= 1:
            return
        self.add_item(PageButton(label="◀ Prev", delta=-1, disabled=self.page == 0))
        self.add_item(PageButton(label="Next ▶", delta=1, disabled=self.page >= pages - 1))

    async def _message(self, channel, mid):
        """Return the pinned message *mid*. One pins() call per render replaces a request per pin,
        which kept button replies past Discord's 3-second limit on channels with many pins."""
        if self._pin_cache is None:
            try:
                self._pin_cache = {m.id: m for m in await channel.pins()}
            except Exception:
                self._pin_cache = {}  # fall back to one fetch per pin
        msg = self._pin_cache.get(mid)
        if msg is None:
            msg = await channel.fetch_message(mid)  # not pinned any more, or a stale entry
        return msg

    def _get_order(self):
        self._pin_cache = None
        guild_data = load_guild_data(self.guild_id) or {}
        pins_manager = guild_data.setdefault("pins_manager", {})
        order = pins_manager.get(str(self.channel_id)) or []
        return guild_data, pins_manager, order

    def _save_order(self, guild_data, pins_manager, order):
        pins_manager[str(self.channel_id)] = order
        save_guild_data(self.guild_id, guild_data)

    async def _build_main(self, interaction: discord.Interaction, notice: str = None):
        guild_data, pins_manager, order = self._get_order()
        channel = interaction.channel
        if not order:
            description = "No pins in saved order. Use `Refresh` to sync from current pinned messages."
            if notice:
                description = f"{notice}\n\n{description}"
            embed = info_embed(
                title=f"📌 Pins Manager • #{getattr(channel, 'name', 'channel')}",
                description=description,
            )
            self.clear_items()
            self.add_item(MainButton(label="Refresh", style=discord.ButtonStyle.secondary, custom_id="pins:refresh"))
            self.add_item(MainButton(label="Close", style=discord.ButtonStyle.secondary, custom_id="pins:close"))
            await interaction.response.edit_message(embed=embed, view=self)
            return

        lines = []
        for idx, mid in enumerate(order, 1):
            try:
                msg = await self._message(channel, mid)
                preview = msg.content.replace("\n", " ") if msg.content else ""
                if not preview and msg.embeds:
                    preview = msg.embeds[0].title or msg.embeds[0].description or "(embed)"
                if not preview and msg.attachments:
                    preview = "(attachment)"
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(f"**{idx})** [{preview}]({msg.jump_url}) • {msg.author.mention}")
            except (discord.NotFound, discord.HTTPException):
                lines.append(f"**{idx})** *(deleted/missing)* (id: {mid})")

        description = "\n".join(lines)
        if len(description) > 3900:
            description = description[:3900].rsplit("\n", 1)[0] + "\n… (more pins hidden)"
        if notice:
            description = f"{notice}\n\n{description}"
        embed = info_embed(
            title=f"📌 Pins Manager • #{getattr(channel, 'name', 'channel')}",
            description=description,
        )
        self.clear_items()
        self.add_item(MainButton(label="Reorder", style=discord.ButtonStyle.primary, custom_id="pins:reorder_mode"))
        self.add_item(MainButton(label="Delete", style=discord.ButtonStyle.danger, custom_id="pins:delete_mode"))
        self.add_item(MainButton(label="Apply to Discord", style=discord.ButtonStyle.success, custom_id="pins:apply_confirm"))
        self.add_item(MainButton(label="Refresh", style=discord.ButtonStyle.secondary, custom_id="pins:refresh"))
        self.add_item(MainButton(label="Close", style=discord.ButtonStyle.secondary, custom_id="pins:close"))
        await interaction.response.edit_message(embed=embed, view=self)

    async def _build_reorder(self, interaction: discord.Interaction):
        guild_data, pins_manager, order = self._get_order()
        channel = interaction.channel
        if not order:
            await self._build_main(interaction)
            return

        start, end, pages = self._page_bounds(order)
        seq_str = " -> ".join(str(order.index(mid) + 1) for mid in self.sequence) if self.sequence else "(none)"
        lines = []
        for idx, mid in enumerate(order[start:end], start + 1):
            try:
                msg = await self._message(channel, mid)
                preview = msg.content.replace("\n", " ") if msg.content else ""
                if not preview and msg.embeds:
                    preview = msg.embeds[0].title or msg.embeds[0].description or "(embed)"
                if not preview and msg.attachments:
                    preview = "(attachment)"
                if len(preview) > 60:
                    preview = preview[:57] + "..."
                lines.append(f"**{idx})** {preview} • {msg.author.mention}")
            except (discord.NotFound, discord.HTTPException):
                lines.append(f"**{idx})** *(deleted/missing)*")

        embed = info_embed(
            title=f"📌 Reordering • #{getattr(channel, 'name', 'channel')} (page {self.page + 1}/{pages})",
            description=(
                "Click pins in the order you want them to appear, then press **Done**. "
                "Unclicked pins stay after them.\n"
                "Then use **Apply to Discord** on the main screen to push the order "
                "to the real pinned list.\n"
                f"Sequence: {seq_str}\n\n" + "\n".join(lines)
            ),
        )
        self.clear_items()
        for idx, mid in enumerate(order[start:end], start + 1):
            self.add_item(ReorderPinButton(label=f"{idx})", mid=mid, index=idx))
        self._add_nav(pages)
        if self.sequence:
            self.add_item(ReorderActionButton(label="Undo last", style=discord.ButtonStyle.secondary, custom_id="pins:reorder_undo"))
            self.add_item(ReorderActionButton(label="Reset", style=discord.ButtonStyle.secondary, custom_id="pins:reorder_reset"))
        self.add_item(ReorderActionButton(label="Done", style=discord.ButtonStyle.success, custom_id="pins:reorder_done"))
        self.add_item(ReorderActionButton(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="pins:reorder_cancel"))
        await interaction.response.edit_message(embed=embed, view=self)

    async def _build_delete(self, interaction: discord.Interaction):
        guild_data, pins_manager, order = self._get_order()
        channel = interaction.channel
        if not order:
            await self._build_main(interaction)
            return

        start, end, pages = self._page_bounds(order)
        lines = []
        for idx, mid in enumerate(order[start:end], start + 1):
            try:
                msg = await self._message(channel, mid)
                preview = msg.content.replace("\n", " ") if msg.content else ""
                if not preview and msg.embeds:
                    preview = msg.embeds[0].title or msg.embeds[0].description or "(embed)"
                if not preview and msg.attachments:
                    preview = "(attachment)"
                if len(preview) > 60:
                    preview = preview[:57] + "..."
                lines.append(f"**{idx})** {preview} • {msg.author.mention}")
            except (discord.NotFound, discord.HTTPException):
                lines.append(f"**{idx})** *(deleted/missing)*")

        embed = info_embed(
            title=f"📌 Delete pins • #{getattr(channel, 'name', 'channel')} (page {self.page + 1}/{pages})",
            description="Click a pin to unpin and remove it from this list.\n\n" + "\n".join(lines),
        )
        self.clear_items()
        for idx, mid in enumerate(order[start:end], start + 1):
            self.add_item(DeletePinButton(label=f"X {idx})", mid=mid))
        self._add_nav(pages)
        self.add_item(DeleteActionButton(label="Back", style=discord.ButtonStyle.secondary, custom_id="pins:delete_back"))
        await interaction.response.edit_message(embed=embed, view=self)

    async def _apply_native(self, interaction: discord.Interaction):
        guild_data, pins_manager, order = self._get_order()
        channel = interaction.channel
        if not order:
            await self._build_main(interaction, notice="⚠️ No pins to apply.")
            return
        try:
            pinned = await channel.pins()
        except Exception:
            await self._build_main(
                interaction,
                notice="⚠️ Couldn't read the pinned messages (missing **Manage Messages**?).",
            )
            return

        by_id = {m.id: m for m in pinned}
        # Keep the saved order first, then append pins that were added outside
        # the manager so applying never silently drops them.
        ordered = [by_id[mid] for mid in order if mid in by_id]
        known = {m.id for m in ordered}
        ordered.extend(m for m in pinned if m.id not in known)
        if not ordered:
            await self._build_main(interaction, notice="⚠️ None of the saved pins are still pinned.")
            return

        failed = []
        for m in pinned:
            try:
                await m.unpin()
            except Exception:
                failed.append(m.id)
        await asyncio.sleep(0.4)
        # Discord shows the most recently pinned message at the top, so the
        # first pin in `ordered` has to be pinned last.
        for m in reversed(ordered):
            try:
                await m.pin()
            except Exception:
                failed.append(m.id)

        # Save what Discord actually ended up with, not what we hoped for.
        try:
            native = await channel.pins()
            new_order = [m.id for m in native] or [m.id for m in ordered]
        except Exception:
            new_order = [m.id for m in ordered]
        self._save_order(guild_data, pins_manager, new_order)

        notice = f"✅ Applied **{len(ordered)}** pin(s) to Discord."
        if failed:
            notice += (
                f"\n⚠️ {len(failed)} pin/unpin operation(s) failed "
                "(missing permission or rate limit). Use **Refresh** to resync."
            )
        await self._build_main(interaction, notice=notice)


class MainButton(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle, custom_id: str):
        super().__init__(label=label, style=style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        view: PinsManagerView = self.view
        if self.custom_id == "pins:reorder_mode":
            view.mode = "reorder"
            view.sequence = []
            view.page = 0
            await view._build_reorder(interaction)
        elif self.custom_id == "pins:delete_mode":
            view.mode = "delete"
            view.page = 0
            await view._build_delete(interaction)
        elif self.custom_id == "pins:apply_confirm":
            confirm = ConfirmApplyView(view.bot, view.guild_id, view.channel_id)
            embed = info_embed(title="Apply to native pins", description="This will unpin everything currently pinned and repin in the saved order. Continue?")
            await interaction.response.edit_message(embed=embed, view=confirm)
        elif self.custom_id == "pins:refresh":
            guild_data = load_guild_data(view.guild_id) or {}
            pins_manager = guild_data.setdefault("pins_manager", {})
            channel = interaction.channel
            try:
                current = await channel.pins()
            except Exception:
                current = []
            current_ids = [m.id for m in current]
            saved_order = list(pins_manager.get(str(view.channel_id)) or [])
            kept = [mid for mid in saved_order if mid in current_ids]
            for mid in current_ids:
                if mid not in kept:
                    kept.append(mid)
            pins_manager[str(view.channel_id)] = kept
            save_guild_data(view.guild_id, guild_data)
            await view._build_main(interaction)
        elif self.custom_id == "pins:close":
            try:
                await interaction.message.delete()
            except Exception:
                pass


class ReorderPinButton(discord.ui.Button):
    def __init__(self, label: str, mid: int, index: int):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=f"pins:rp:{mid}")
        self.mid = mid
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: PinsManagerView = self.view
        if self.mid in view.sequence:
            await interaction.response.defer()
            return
        view.sequence.append(self.mid)
        await view._build_reorder(interaction)


class ReorderActionButton(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle, custom_id: str):
        super().__init__(label=label, style=style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        view: PinsManagerView = self.view
        if self.custom_id == "pins:reorder_undo":
            if view.sequence:
                view.sequence.pop()
            await view._build_reorder(interaction)
        elif self.custom_id == "pins:reorder_reset":
            view.sequence = []
            await view._build_reorder(interaction)
        elif self.custom_id == "pins:reorder_cancel":
            view.mode = "main"
            view.sequence = []
            await view._build_main(interaction)
        elif self.custom_id == "pins:reorder_done":
            if not view.sequence:
                await interaction.response.edit_message(embed=error_embed(description="Click pins in the order you want first."), view=view)
                return
            guild_data, pins_manager, order = view._get_order()
            new_order = merge_reorder_sequence(view.sequence, order)
            pins_manager[str(view.channel_id)] = new_order
            save_guild_data(view.guild_id, guild_data)
            view.mode = "main"
            view.sequence = []
            await view._build_main(interaction)


class DeletePinButton(discord.ui.Button):
    def __init__(self, label: str, mid: int):
        super().__init__(label=label, style=discord.ButtonStyle.danger, custom_id=f"pins:dp:{mid}")
        self.mid = mid

    async def callback(self, interaction: discord.Interaction):
        view: PinsManagerView = self.view
        guild_data, pins_manager, order = view._get_order()
        channel = interaction.channel
        try:
            msg = await channel.fetch_message(self.mid)
            try:
                await msg.unpin()
            except Exception:
                pass
        except Exception:
            pass
        new_order = [mid for mid in order if mid != self.mid]
        pins_manager[str(view.channel_id)] = new_order
        save_guild_data(view.guild_id, guild_data)
        await view._build_delete(interaction)


class DeleteActionButton(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle, custom_id: str):
        super().__init__(label=label, style=style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        view: PinsManagerView = self.view
        if self.custom_id == "pins:delete_back":
            view.mode = "main"
            await view._build_main(interaction)


class PageButton(discord.ui.Button):
    def __init__(self, label: str, delta: int, disabled: bool):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction):
        view: PinsManagerView = self.view
        view.page += self.delta
        if view.mode == "reorder":
            await view._build_reorder(interaction)
        else:
            await view._build_delete(interaction)


class ConfirmApplyView(discord.ui.View):
    def __init__(self, bot, guild_id: int, channel_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms and perms.manage_messages:
            return True
        await interaction.response.send_message("You need Manage Messages to change pins.", ephemeral=True)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PinsManagerView(self.bot, self.guild_id, self.channel_id)
        await view._apply_native(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PinsManagerView(self.bot, self.guild_id, self.channel_id)
        await view._build_main(interaction)


class UnpinAllView(discord.ui.View):
    """Yes/No confirmation for .unpinall. Only the person who asked can answer."""

    def __init__(self, invoker, count: int):
        super().__init__(timeout=60)
        self.invoker = invoker
        self.count = count
        self.result: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Unpin all", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        self.stop()
        await interaction.response.edit_message(content="Unpinning…", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        self.stop()
        await interaction.response.edit_message(content="Cancelled. Nothing was unpinned.", view=None)


class PinsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="unpinall", aliases=["unpin-all"])
    @commands.guild_only()
    async def unpinall(self, ctx, channel: discord.TextChannel = None):
        """Remove every pin from a channel (default: this one). Needs Manage Messages; asks to confirm."""
        if not ctx.author.guild_permissions.manage_messages:
            return await ctx.send(embed=error_embed(description="You need Manage Messages to use this."), delete_after=5)
        target = channel or ctx.channel
        try:
            pins = await target.pins()
        except discord.HTTPException:
            return await ctx.send(f"Could not read the pins in {target.mention}.")
        if not pins:
            return await ctx.send(f"{target.mention} has no pinned messages.")

        view = UnpinAllView(ctx.author, len(pins))
        prompt = await ctx.send(
            f"This will unpin **{len(pins)}** message(s) in {target.mention}. This cannot be undone. Continue?",
            view=view,
        )
        await view.wait()
        if view.result is None:
            return await prompt.edit(content="Timed out. Nothing was unpinned.", view=None)
        if view.result is False:
            return

        failed = 0
        for message in pins:
            try:
                await message.unpin()
            except discord.HTTPException:
                failed += 1

        # The saved manager order for this channel no longer matches anything, so drop it.
        guild_data = load_guild_data(ctx.guild.id) or {}
        guild_data.setdefault("pins_manager", {}).pop(str(target.id), None)
        save_guild_data(ctx.guild.id, guild_data)

        done = len(pins) - failed
        report = f"Unpinned **{done}** message(s) in {target.mention}."
        if failed:
            report += f" {failed} could not be unpinned (missing permission or rate limit)."
        await ctx.send(report)

    @commands.command(name="pins")
    @commands.guild_only()
    async def pins(self, ctx):
        if not ctx.author.guild_permissions.manage_messages:
            await ctx.send(embed=error_embed(description="You need Manage Messages to use this."), delete_after=5)
            return
        guild_data = load_guild_data(ctx.guild.id) or {}
        pins_manager = guild_data.setdefault("pins_manager", {})
        key = str(ctx.channel.id)
        order = pins_manager.get(key)
        if not order:
            try:
                pins = await ctx.channel.pins()
            except Exception:
                pins = []
            order = [m.id for m in pins]
            pins_manager[key] = order
            save_guild_data(ctx.guild.id, guild_data)
        view = PinsManagerView(self.bot, ctx.guild.id, ctx.channel.id)
        embed = info_embed(title=f"📌 Pins Manager • #{ctx.channel.name}", description="Loading...")
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view._build_main(await self._fake_interaction(ctx, msg, view))

    async def _fake_interaction(self, ctx, msg, view):
        class FakeInteraction:
            def __init__(self, ctx, msg, view):
                self.guild = ctx.guild
                self.channel = ctx.channel
                self.user = ctx.author
                self.message = msg
                self.response = self
                self.data = {}

            async def edit_message(self, **kwargs):
                return await msg.edit(**kwargs)

            async def send_message(self, **kwargs):
                return await ctx.send(**kwargs)

            async def defer(self):
                pass

        return FakeInteraction(ctx, msg, view)


async def setup(bot):
    await bot.add_cog(PinsCog(bot))
