# presets_cog.py
import discord
import asyncio
import sqlite3
from datetime import datetime
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
from typing import Dict, List, Any, Optional
import os

from cogs.data_utils import load_guild_data, save_guild_data

# Configuration
ITEMS_PER_PAGE = 10
MAX_PRESET_LENGTH = 1000
MIN_PRESET_LENGTH = 1
EMBED_COLOR = 0xff3fb9
FOOTER_TEXT = "Village Game"
DB_PATH = "db/presets.db"

ABILITY_CATEGORIES = ["Lethal", "Curing", "Manipulation (Control, Redirect)", "Manipulation (Other)", "Blocking", "Transportation and Comms", "Information", "Other"]

CATEGORY_DISPLAY = {
    "Lethal": "Lethal",
    "Curing": "Curing",
    "Manipulation (Control, Redirect)": "Manipulation (Control, Redirect)",
    "Manipulation (Other)": "Manipulation (Other)",
    "Blocking": "Blocking",
    "Transportation and Comms": "Transportation and Comms",
    "Information": "Information",
    "Other": "Other",
    "Manip": "Manipulation (Other)",
    "Pcs": "Transportation and Comms",
    "Transportation": "Transportation and Comms",
    "Info": "Information",
    "Economy": "Other",
    None: "Uncategorized",
}

DEFAULT_CATEGORY_ORDER = [
    "Manipulation (Control, Redirect)",
    "Blocking",
    "Manipulation (Other)",
    "Lethal",
    "Curing",
    "Transportation and Comms",
    "Information",
    "Other",
]


def resolve_category_display(stored_cat, custom_categories=None):
    if stored_cat is None:
        return "Uncategorized"
    display = CATEGORY_DISPLAY.get(stored_cat)
    if display:
        return display
    if custom_categories and stored_cat in custom_categories:
        return stored_cat
    return "Other"

# Ensure DB dir exists
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Create DB & table if missing
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS presets (
    guild_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    preset_id INTEGER NOT NULL,
    preset_info TEXT NOT NULL,
    position INTEGER NOT NULL,
    category TEXT,
    PRIMARY KEY (guild_id, preset_id)
)
""")
# Add category column if missing (migration for existing DBs)
try:
    cursor.execute("ALTER TABLE presets ADD COLUMN category TEXT")
except sqlite3.OperationalError:
    pass  # column already exists
conn.commit()
conn.close()


def _guild_key(ctx: commands.Context) -> str:
    return str(ctx.guild.id)


class Presets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # per-guild locks to avoid concurrent writes
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    # ------------- Category order (guild_data) helpers -------------
    def _get_category_order(self, guild_id: str) -> List[str]:
        gid = int(guild_id)
        data = load_guild_data(gid)
        if data and data.get("preset_category_order"):
            order = list(data["preset_category_order"])
        else:
            order = list(DEFAULT_CATEGORY_ORDER)
        disabled = self._get_disabled_default_categories(guild_id)
        order = [c for c in order if c not in disabled]
        custom = self._get_custom_categories(guild_id)
        for c in custom:
            if c not in order:
                order.append(c)
        return order

    def _set_category_order(self, guild_id: str, order: List[str]) -> None:
        gid = int(guild_id)
        data = load_guild_data(gid) or {}
        data["preset_category_order"] = order
        save_guild_data(gid, data)

    # ------------- Custom category helpers -------------
    def _get_custom_categories(self, guild_id: str) -> List[str]:
        data = load_guild_data(int(guild_id)) or {}
        return list(data.get("preset_custom_categories", []))

    def _set_custom_categories(self, guild_id: str, cats: List[str]) -> None:
        data = load_guild_data(int(guild_id)) or {}
        data["preset_custom_categories"] = cats
        save_guild_data(int(guild_id), data)

    def _get_disabled_default_categories(self, guild_id: str) -> List[str]:
        data = load_guild_data(int(guild_id)) or {}
        return list(data.get("preset_disabled_default_categories", []))

    def _set_disabled_default_categories(self, guild_id: str, cats: List[str]) -> None:
        data = load_guild_data(int(guild_id)) or {}
        data["preset_disabled_default_categories"] = cats
        save_guild_data(int(guild_id), data)

    def _get_all_categories(self, guild_id: str) -> List[str]:
        disabled = self._get_disabled_default_categories(guild_id)
        custom = self._get_custom_categories(guild_id)
        enabled_defaults = [c for c in ABILITY_CATEGORIES if c not in disabled]
        return enabled_defaults + [c for c in custom if c not in ABILITY_CATEGORIES]

    # ------------- DB helpers -------------
    def _load_presets(self, guild_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT preset_id, channel_id, preset_info, position, category FROM presets WHERE guild_id = ? ORDER BY position",
            (guild_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "preset_id": str(r[0]),
                "channel_id": r[1],
                "preset_info": r[2],
                "position": r[3],
                "category": r[4] if len(r) > 4 else None,
            }
            for r in rows
        ]

    async def _save_preset(
        self,
        guild_id: str,
        channel_id: str,
        preset_info: str,
        category: Optional[str] = None,
    ):
        lock = self._get_lock(guild_id)
        async with lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(preset_id) FROM presets WHERE guild_id = ?", (guild_id,))
            max_id = cursor.fetchone()[0] or 0
            cursor.execute("SELECT MAX(position) FROM presets WHERE guild_id = ?", (guild_id,))
            max_pos = cursor.fetchone()[0] or 0
            cursor.execute(
                "INSERT INTO presets (guild_id, channel_id, preset_id, preset_info, position, category) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, channel_id, max_id + 1, preset_info, max_pos + 1, category),
            )
            conn.commit()
            conn.close()

    async def _update_preset(self, guild_id: str, preset_id: str, new_info: str):
        lock = self._get_lock(guild_id)
        async with lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("UPDATE presets SET preset_info = ? WHERE guild_id = ? AND preset_id = ?", (new_info, guild_id, preset_id))
            conn.commit()
            conn.close()

    async def _remove_preset(self, guild_id: str, preset_id: str):
        lock = self._get_lock(guild_id)
        async with lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM presets WHERE guild_id = ? AND preset_id = ?", (guild_id, preset_id))
            conn.commit()
            conn.close()
            # renumber positions
            await self._reorder_positions(guild_id)

    async def _reorder_positions(self, guild_id: str):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT preset_id FROM presets WHERE guild_id = ? ORDER BY position", (guild_id,))
        rows = cursor.fetchall()
        for idx, (pid,) in enumerate(rows, start=1):
            cursor.execute("UPDATE presets SET position = ? WHERE guild_id = ? AND preset_id = ?", (idx, guild_id, pid))
        conn.commit()
        conn.close()

    async def _swap_positions_by_pids(self, guild_id: str, pid_a: str, pid_b: str):
        lock = self._get_lock(guild_id)
        async with lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT position FROM presets WHERE guild_id = ? AND preset_id = ?", (guild_id, pid_a))
            ra = cursor.fetchone()
            cursor.execute("SELECT position FROM presets WHERE guild_id = ? AND preset_id = ?", (guild_id, pid_b))
            rb = cursor.fetchone()
            if not ra or not rb:
                conn.close()
                return False
            pos_a = ra[0]
            pos_b = rb[0]
            cursor.execute("UPDATE presets SET position = ? WHERE guild_id = ? AND preset_id = ?", (pos_b, guild_id, pid_a))
            cursor.execute("UPDATE presets SET position = ? WHERE guild_id = ? AND preset_id = ?", (pos_a, guild_id, pid_b))
            conn.commit()
            conn.close()
            return True

    async def _remove_all_for_guild(self, guild_id: str):
        lock = self._get_lock(guild_id)
        async with lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM presets WHERE guild_id = ?", (guild_id,))
            conn.commit()
            conn.close()

    # ------------- UI helpers -------------
    def _build_pages(self, presets: List[Dict[str, Any]], channel_id: str, guild_id: str = "") -> List[str]:
        filtered = [p for p in presets if p["channel_id"] == channel_id]
        custom_cats = self._get_custom_categories(guild_id) if guild_id else None
        pages: List[str] = []
        for i in range(0, len(filtered), ITEMS_PER_PAGE):
            chunk = filtered[i:i + ITEMS_PER_PAGE]
            lines = []
            for j, p in enumerate(chunk):
                text = p['preset_info'][:297] + '...' if len(p['preset_info']) > 300 else p['preset_info']
                display = resolve_category_display(p.get("category"), custom_cats)
                cat_badge = f" `[{display}]`" if display != "Uncategorized" else ""
                lines.append(f"**{i + j + 1}.**{cat_badge} {text}")
            pages.append("\n".join(lines) if lines else "No presets on this channel.")
        if not pages:
            pages = ["No presets on this channel."]
        return pages

    def _embed_for_page(self, page_text: str, page_index: int, total_pages: int) -> discord.Embed:
        embed = discord.Embed(
            title="Presets List",
            description=page_text,
            color=EMBED_COLOR,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"{FOOTER_TEXT} — Page {page_index + 1}/{total_pages}")
        return embed

    def _build_guild_pages(self, presets: List[Dict[str, Any]], guild_id: str = "") -> List[str]:
        custom_cats = self._get_custom_categories(guild_id) if guild_id else None
        pages: List[str] = []
        prev_display: Optional[str] = None
        for i in range(0, len(presets), ITEMS_PER_PAGE):
            chunk = presets[i:i + ITEMS_PER_PAGE]
            lines: List[str] = []
            for j, p in enumerate(chunk):
                display = resolve_category_display(p.get("category"), custom_cats)
                if display != prev_display:
                    lines.append(f"**__{display}__**")
                    prev_display = display
                preview = p['preset_info'] if len(p['preset_info']) <= 300 else p['preset_info'][:297] + '...'
                lines.append(f"**{i + j + 1}.** <#{p['channel_id']}> — {preview}")
            pages.append("\n".join(lines) if lines else "No presets.")
        if not pages:
            pages = ["No presets."]
        return pages

    async def _temp_disable_then_restore(self, message: discord.Message, view: View, button: Button, *, disabled: bool = True):
        """
        Disable `button` in `view`, edit the message to reflect it, and return
        an inner restore coroutine to call when done.
        """
        prev_state = button.disabled
        button.disabled = disabled
        try:
            await message.edit(view=view)
        except Exception:
            pass

        async def _restore():
            button.disabled = prev_state
            try:
                await message.edit(view=view)
            except Exception:
                pass

        return _restore

    # ------------- Core UI builder -------------

    async def _open_preset_view_for_channel(self, sender, channel: discord.TextChannel):
        """
        Internal helper to open the preset menu for a given channel.

        `sender` is either a Context or an Interaction.
        """
        if isinstance(sender, commands.Context):
            guild = sender.guild
        else:
            guild = sender.guild

        guild_id = str(guild.id)
        presets = self._load_presets(guild_id)
        channel_id = str(channel.id)
        pages = self._build_pages(presets, channel_id, guild_id)
        current_page = 0
        embed = self._embed_for_page(pages[current_page], current_page, len(pages))
        if isinstance(sender, commands.Context):
            message = await sender.send(embed=embed)
        else:
            await sender.response.send_message(embed=embed)
            message = await sender.original_response()

        view = View(timeout=180)
        prev_btn = Button(emoji="⬅️", style=discord.ButtonStyle.secondary)
        next_btn = Button(emoji="➡️", style=discord.ButtonStyle.secondary)
        add_btn = Button(label="Add", style=discord.ButtonStyle.success, emoji="➕")
        remove_btn = Button(label="Remove", style=discord.ButtonStyle.danger, emoji="➖")
        edit_btn = Button(label="Edit", style=discord.ButtonStyle.primary, emoji="✏️")
        close_btn = Button(label="Close", style=discord.ButtonStyle.secondary)

        # local helper that refreshes the main message embed/view
        async def refresh():
            nonlocal pages, presets, current_page
            presets = self._load_presets(guild_id)
            pages = self._build_pages(presets, channel_id, guild_id)
            if current_page >= len(pages):
                current_page = len(pages) - 1 if pages else 0
            try:
                await message.edit(embed=self._embed_for_page(pages[current_page], current_page, len(pages)), view=view)
            except Exception:
                pass

        async def prev_cb(i: discord.Interaction):
            try:
                await i.response.defer()
                nonlocal current_page
                if current_page > 0:
                    current_page -= 1
                    await refresh()
            except Exception:
                pass

        async def next_cb(i: discord.Interaction):
            try:
                await i.response.defer()
                nonlocal current_page
                if current_page < len(pages) - 1:
                    current_page += 1
                    await refresh()
            except Exception:
                pass

        async def close_cb(i: discord.Interaction):
            try:
                await i.response.defer()
                try:
                    await message.delete()
                except Exception:
                    pass
            except Exception:
                pass

        # ---- Modal classes ----
        # We'll capture `self` into `cog` to use inside modal definitions (closures).
        cog = self

        class AddPresetModal(Modal, title="Add Preset"):
            preset_text = TextInput(label="Preset Text", style=discord.TextStyle.paragraph, min_length=MIN_PRESET_LENGTH, max_length=MAX_PRESET_LENGTH)

            def __init__(self, *, category: Optional[str] = None, restore=None):
                super().__init__()
                self._category = category
                self._restore = restore

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    await cog._save_preset(guild_id, channel_id, str(self.preset_text), category=self._category)
                    await interaction.response.defer()
                    await refresh()
                finally:
                    if self._restore:
                        try:
                            await self._restore()
                        except Exception:
                            pass

            async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
                try:
                    await interaction.response.send_message("An error occurred while saving the preset.", ephemeral=True)
                except Exception:
                    pass
                if self._restore:
                    try:
                        await self._restore()
                    except Exception:
                        pass

        class EditPresetModal(Modal, title="Edit Preset"):
            new_text = TextInput(label="New Preset Text", style=discord.TextStyle.paragraph, min_length=MIN_PRESET_LENGTH, max_length=MAX_PRESET_LENGTH)

            def __init__(self, preset_id: str, *, restore=None):
                super().__init__()
                self.preset_id = preset_id
                self._restore = restore

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    await cog._update_preset(guild_id, self.preset_id, str(self.new_text))
                    await interaction.response.defer()
                    await refresh()
                finally:
                    if self._restore:
                        try:
                            await self._restore()
                        except Exception:
                            pass

            async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
                try:
                    await interaction.response.send_message("An error occurred while updating the preset.", ephemeral=True)
                except Exception:
                    pass
                if self._restore:
                    try:
                        await self._restore()
                    except Exception:
                        pass

        # ---- Callbacks ----
        async def add_cb(i: discord.Interaction):
            all_cats = self._get_all_categories(guild_id)
            options = [
                discord.SelectOption(label="❓ Not Sure / Uncategorized", value="__none__"),
            ]
            for cat in all_cats:
                options.append(discord.SelectOption(label=cat, value=cat))

            select = Select(placeholder="Choose an ability category (optional)", options=options, min_values=1, max_values=1)

            async def sel_cb(sel_i: discord.Interaction):
                if not sel_i.data or "values" not in sel_i.data or not sel_i.data["values"]:
                    await sel_i.response.send_message("No option selected.", ephemeral=True)
                    return
                chosen = sel_i.data["values"][0]
                category = None if chosen == "__none__" else chosen
                restore = await self._temp_disable_then_restore(message, view, add_btn)
                try:
                    modal = AddPresetModal(category=category, restore=restore)
                    await sel_i.response.send_modal(modal)
                except Exception:
                    await restore()
                    try:
                        await sel_i.followup.send("Failed to open modal.", ephemeral=True)
                    except Exception:
                        pass

            select.callback = sel_cb
            v = View(timeout=60)
            v.add_item(select)
            await i.response.send_message(
                "Choose an ability category *(optional — pick 'Not Sure' to skip)*:",
                view=v,
                ephemeral=True,
            )

        async def remove_cb(i: discord.Interaction):
            try:
                # Build selection from the channel's presets
                channel_presets = [p for p in self._load_presets(guild_id) if p["channel_id"] == channel_id]
                if not channel_presets:
                    await i.response.send_message("No presets to remove.", ephemeral=True)
                    return

                options = []
                for idx, p in enumerate(channel_presets):
                    preset_preview = p['preset_info'][:50] + "..." if len(p['preset_info']) > 50 else p['preset_info']
                    options.append(discord.SelectOption(
                        label=f"Preset #{idx+1}: {preset_preview}", 
                        value=p['preset_id']
                    ))

                select = Select(placeholder="Select preset to remove", options=options, min_values=1, max_values=1)

                async def sel_cb(sel_i: discord.Interaction):
                    try:
                        if not sel_i.data or "values" not in sel_i.data or not sel_i.data["values"]:
                            await sel_i.response.send_message("No preset selected.", ephemeral=True)
                            return
                        
                        pid = sel_i.data["values"][0]
                        await self._remove_preset(guild_id, pid)
                        await sel_i.response.defer()
                        await refresh()
                    except Exception as e:
                        try:
                            if not sel_i.response.is_done():
                                await sel_i.response.send_message("Error removing preset.", ephemeral=True)
                            else:
                                await sel_i.followup.send("Error removing preset.", ephemeral=True)
                        except:
                            pass

                select.callback = sel_cb
                v = View(timeout=60)
                v.add_item(select)
                await i.response.send_message("Choose preset to remove:", view=v, ephemeral=True)
            except Exception as e:
                try:
                    if not i.response.is_done():
                        await i.response.send_message("Error loading presets for removal.", ephemeral=True)
                    else:
                        await i.followup.send("Error loading presets for removal.", ephemeral=True)
                except:
                    pass

        async def edit_cb(i: discord.Interaction):
            try:
                channel_presets = [p for p in self._load_presets(guild_id) if p["channel_id"] == channel_id]
                if not channel_presets:
                    await i.response.send_message("No presets to edit.", ephemeral=True)
                    return

                options = []
                for idx, p in enumerate(channel_presets):
                    preset_preview = p['preset_info'][:50] + "..." if len(p['preset_info']) > 50 else p['preset_info']
                    options.append(discord.SelectOption(
                        label=f"Preset #{idx+1}: {preset_preview}", 
                        value=p['preset_id']
                    ))

                select = Select(placeholder="Select preset to edit", options=options, min_values=1, max_values=1)

                async def sel_cb(sel_i: discord.Interaction):
                    try:
                        if not sel_i.data or "values" not in sel_i.data or not sel_i.data["values"]:
                            await sel_i.response.send_message("No preset selected.", ephemeral=True)
                            return
                        
                        pid = sel_i.data["values"][0]
                        # disable edit button while opening modal; restore will be handled in modal callbacks
                        restore = await self._temp_disable_then_restore(message, view, edit_btn)
                        try:
                            modal = EditPresetModal(pid, restore=restore)
                            await sel_i.response.send_modal(modal)
                        except Exception:
                            # ensure restore if modal send fails
                            await restore()
                            try:
                                await sel_i.followup.send("Failed to open edit modal.", ephemeral=True)
                            except:
                                pass
                    except Exception as e:
                        try:
                            if not sel_i.response.is_done():
                                await sel_i.response.send_message("Error opening edit modal.", ephemeral=True)
                            else:
                                await sel_i.followup.send("Error opening edit modal.", ephemeral=True)
                        except:
                            pass

                select.callback = sel_cb
                v = View(timeout=60)
                v.add_item(select)
                await i.response.send_message("Choose preset to edit:", view=v, ephemeral=True)
            except Exception as e:
                try:
                    if not i.response.is_done():
                        await i.response.send_message("Error loading presets for editing.", ephemeral=True)
                    else:
                        await i.followup.send("Error loading presets for editing.", ephemeral=True)
                except:
                    pass

        # bind callbacks
        prev_btn.callback = prev_cb
        next_btn.callback = next_cb
        close_btn.callback = close_cb
        add_btn.callback = add_cb
        remove_btn.callback = remove_cb
        edit_btn.callback = edit_cb

        # add to view
        view.add_item(prev_btn)
        view.add_item(next_btn)
        view.add_item(add_btn)
        view.add_item(edit_btn)
        view.add_item(remove_btn)
        view.add_item(close_btn)
        await message.edit(view=view)

    # ------------- Commands -------------
    @commands.command(name="preset")
    async def preset(self, ctx: commands.Context):
        """Open the preset menu for this channel."""
        await self._open_preset_view_for_channel(ctx, ctx.channel)

    async def open_presets_for_interaction(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Entry point used from the dashboard button."""
        await self._open_preset_view_for_channel(interaction, channel)

    # ---------- Admin command: reorder / manage all presets ----------
    @commands.command(name="ospreset")
    @commands.has_permissions(administrator=True)
    async def ospreset(self, ctx: commands.Context):
        """View, reorder, or remove all presets (admin only)."""
        guild_id = _guild_key(ctx)
        presets = self._load_presets(guild_id)

        # Sort by configured category order (uncategorized last)
        category_order = self._get_category_order(guild_id)
        order_idx = {c: i for i, c in enumerate(category_order)}
        _sort_custom_cats = self._get_custom_categories(guild_id)

        def _preset_sort_key(p):
            display = resolve_category_display(p.get("category"), _sort_custom_cats)
            if display == "Uncategorized":
                return (len(category_order), p.get("position", 0))
            idx = order_idx.get(display, len(category_order))
            return (idx, p.get("position", 0))

        presets.sort(key=_preset_sort_key)

        def _embed_for_guild_page(page_text: str, page_index: int, total_pages: int) -> discord.Embed:
            embed = discord.Embed(title="All Presets", description=page_text, color=EMBED_COLOR, timestamp=datetime.utcnow())
            embed.set_footer(text=f"{FOOTER_TEXT} — Page {page_index + 1}/{total_pages}")
            return embed

        pages = self._build_guild_pages(presets, guild_id)
        current_page = 0
        embed = _embed_for_guild_page(pages[current_page], current_page, len(pages))
        msg = await ctx.send(embed=embed)

        view = View(timeout=180)
        prev_btn = Button(emoji="⬅️", style=discord.ButtonStyle.secondary)
        next_btn = Button(emoji="➡️", style=discord.ButtonStyle.secondary)
        swap_btn = Button(label="Swap Two", style=discord.ButtonStyle.primary, emoji="🔃")
        remove_btn = Button(label="Remove", style=discord.ButtonStyle.danger, emoji="➖")
        reset_btn = Button(label="Reset All", style=discord.ButtonStyle.danger, emoji="⚠️")
        close_btn = Button(label="Close", style=discord.ButtonStyle.secondary)

        async def refresh():
            nonlocal presets, pages, current_page
            presets = self._load_presets(guild_id)
            presets.sort(key=_preset_sort_key)
            pages = self._build_guild_pages(presets, guild_id)
            if current_page >= len(pages):
                current_page = len(pages) - 1 if pages else 0
            try:
                await msg.edit(embed=_embed_for_guild_page(pages[current_page], current_page, len(pages)), view=view)
            except Exception:
                pass

        async def prev_cb(i: discord.Interaction):
            try:
                await i.response.defer()
                nonlocal current_page
                if current_page > 0:
                    current_page -= 1
                    await refresh()
            except Exception:
                pass

        async def next_cb(i: discord.Interaction):
            try:
                await i.response.defer()
                nonlocal current_page
                if current_page < len(pages) - 1:
                    current_page += 1
                    await refresh()
            except Exception:
                pass

        async def close_cb(i: discord.Interaction):
            try:
                await i.response.defer()
                try:
                    await msg.delete()
                except Exception:
                    pass
            except Exception:
                pass

        async def swap_cb(i: discord.Interaction):
            try:
                presets_now = self._load_presets(guild_id)
                presets_now.sort(key=_preset_sort_key)
                if len(presets_now) < 2:
                    await i.response.send_message("Need at least 2 presets to swap.", ephemeral=True)
                    return
                    
                options = []
                for idx, p in enumerate(presets_now):
                    preview = p['preset_info'][:80] + ('...' if len(p['preset_info']) > 80 else '')
                    options.append(discord.SelectOption(label=f"{idx+1}. {preview}", value=p['preset_id']))
                
                select = Select(placeholder="Select two to swap", options=options[:25], min_values=2, max_values=min(2, len(options)))

                async def sel_cb(sel_i: discord.Interaction):
                    try:
                        vals = sel_i.data.get('values', [])
                        if len(vals) != 2:
                            await sel_i.response.send_message("Please select exactly two presets.", ephemeral=True)
                            return
                        ok = await self._swap_positions_by_pids(guild_id, vals[0], vals[1])
                        if not ok:
                            await sel_i.response.send_message("Swap failed (presets may have been deleted).", ephemeral=True)
                            return
                        await sel_i.response.defer()
                        await refresh()
                    except Exception as e:
                        try:
                            if not sel_i.response.is_done():
                                await sel_i.response.send_message("Error swapping presets.", ephemeral=True)
                            else:
                                await sel_i.followup.send("Error swapping presets.", ephemeral=True)
                        except:
                            pass

                select.callback = sel_cb
                v = View(timeout=60)
                v.add_item(select)
                await i.response.send_message("Choose two presets to swap:", view=v, ephemeral=True)
            except Exception as e:
                try:
                    if not i.response.is_done():
                        await i.response.send_message("Error loading presets for swapping.", ephemeral=True)
                    else:
                        await i.followup.send("Error loading presets for swapping.", ephemeral=True)
                except:
                    pass

        async def remove_cb_os(i: discord.Interaction):
            try:
                presets_now = self._load_presets(guild_id)
                presets_now.sort(key=_preset_sort_key)
                if not presets_now:
                    await i.response.send_message("No presets to remove.", ephemeral=True)
                    return
                    
                options = []
                for idx, p in enumerate(presets_now):
                    preview = p['preset_info'][:80] + ('...' if len(p['preset_info']) > 80 else '')
                    options.append(discord.SelectOption(label=f"{idx+1}. {preview}", value=p['preset_id']))
                
                select = Select(placeholder="Select preset to remove", options=options[:25], min_values=1, max_values=1)

                async def sel_cb(sel_i: discord.Interaction):
                    try:
                        vals = sel_i.data.get('values', [])
                        if not vals:
                            await sel_i.response.send_message("No preset selected.", ephemeral=True)
                            return
                        pid = vals[0]
                        await self._remove_preset(guild_id, pid)
                        await sel_i.response.defer()
                        await refresh()
                    except Exception as e:
                        try:
                            if not sel_i.response.is_done():
                                await sel_i.response.send_message("Error removing preset.", ephemeral=True)
                            else:
                                await sel_i.followup.send("Error removing preset.", ephemeral=True)
                        except:
                            pass

                select.callback = sel_cb
                v = View(timeout=60)
                v.add_item(select)
                await i.response.send_message("Choose preset to remove:", view=v, ephemeral=True)
            except Exception as e:
                try:
                    if not i.response.is_done():
                        await i.response.send_message("Error loading presets for removal.", ephemeral=True)
                    else:
                        await i.followup.send("Error loading presets for removal.", ephemeral=True)
                except:
                    pass

        async def reset_cb(i: discord.Interaction):
            confirm_view = View(timeout=30)

            async def confirm_btn_cb(ci: discord.Interaction):
                if ci.user.id != ctx.author.id:
                    await ci.response.send_message("This is not your confirmation.", ephemeral=True)
                    return
                try:
                    await self._remove_all_for_guild(guild_id)
                    await ci.response.defer()
                    await refresh()
                except Exception as e:
                    try:
                        if not ci.response.is_done():
                            await ci.response.send_message("Error resetting presets.", ephemeral=True)
                        else:
                            await ci.followup.send("Error resetting presets.", ephemeral=True)
                    except:
                        pass

            async def cancel_btn_cb(ci: discord.Interaction):
                if ci.user.id != ctx.author.id:
                    await ci.response.send_message("This is not your confirmation.", ephemeral=True)
                    return
                await ci.response.edit_message(content="Cancelled.", view=None)

            confirm_btn = Button(label="✔ Yes", style=discord.ButtonStyle.green)
            cancel_btn = Button(label="❌ No", style=discord.ButtonStyle.red)
            confirm_btn.callback = confirm_btn_cb
            cancel_btn.callback = cancel_btn_cb
            confirm_view.add_item(confirm_btn)
            confirm_view.add_item(cancel_btn)

            async def on_timeout():
                try:
                    await i.edit_original_response(content="Timed out.", view=None)
                except:
                    pass

            confirm_view.on_timeout = on_timeout
            await i.response.send_message("Are you sure you want to reset all presets?", view=confirm_view, ephemeral=True)

        prev_btn.callback = prev_cb
        next_btn.callback = next_cb
        swap_btn.callback = swap_cb
        remove_btn.callback = remove_cb_os
        reset_btn.callback = reset_cb
        close_btn.callback = close_cb

        view.add_item(prev_btn)
        view.add_item(next_btn)
        view.add_item(swap_btn)
        view.add_item(remove_btn)
        view.add_item(reset_btn)
        view.add_item(close_btn)
        await msg.edit(view=view)

    # ---------- Admin command: manage category order ----------
    @commands.command(name="ospresetsort")
    @commands.has_permissions(administrator=True)
    async def ospresetsort(self, ctx: commands.Context):
        """Reorder the display order of preset categories (admin only)."""
        guild_id = _guild_key(ctx)
        category_order = self._get_category_order(guild_id)
        selected_index = 0  # index of currently selected category in the dropdown

        def _embed(order, sel_idx):
            lines = []
            for i, c in enumerate(order):
                prefix = "**▸** " if i == sel_idx else f"{i+1}. "
                lines.append(f"{prefix}{c}")
            lines.append("")
            lines.append("Use the dropdown + Up/Down buttons to reorder.")
            emb = discord.Embed(
                title="Category Order",
                description="\n".join(lines),
                color=EMBED_COLOR,
                timestamp=datetime.utcnow(),
            )
            emb.set_footer(text=FOOTER_TEXT)
            return emb

        msg = await ctx.send(embed=_embed(category_order, selected_index))

        view = View(timeout=180)

        # Dropdown showing all categories (select the one to move)
        cat_options = [
            discord.SelectOption(label=c, value=str(i))
            for i, c in enumerate(category_order)
        ]
        cat_select = Select(placeholder="Select a category to move", options=cat_options, min_values=1, max_values=1)

        up_btn = Button(emoji="⬆️", style=discord.ButtonStyle.secondary, label="Up")
        down_btn = Button(emoji="⬇️", style=discord.ButtonStyle.secondary, label="Down")
        reset_btn = Button(label="Reset to Default", style=discord.ButtonStyle.danger, emoji="↩️")
        close_btn = Button(label="Close", style=discord.ButtonStyle.secondary)

        async def refresh():
            nonlocal category_order, selected_index
            new_order = self._get_category_order(guild_id)
            category_order = new_order
            if selected_index >= len(category_order):
                selected_index = 0
            # update dropdown options
            cat_select.options = [
                discord.SelectOption(label=c, value=str(i))
                for i, c in enumerate(category_order)
            ]
            try:
                await msg.edit(embed=_embed(category_order, selected_index), view=view)
            except Exception:
                pass

        async def select_cb(i: discord.Interaction):
            if not i.data or "values" not in i.data or not i.data["values"]:
                await i.response.defer()
                return
            nonlocal selected_index
            selected_index = int(i.data["values"][0])
            await i.response.defer()
            await refresh()

        async def up_cb(i: discord.Interaction):
            nonlocal selected_index
            if selected_index <= 0:
                await i.response.send_message("Already at the top.", ephemeral=True)
                return
            # swap with the one above
            new_order = list(category_order)
            new_order[selected_index], new_order[selected_index - 1] = new_order[selected_index - 1], new_order[selected_index]
            self._set_category_order(guild_id, new_order)
            selected_index -= 1
            await i.response.defer()
            await refresh()

        async def down_cb(i: discord.Interaction):
            nonlocal selected_index
            if selected_index >= len(category_order) - 1:
                await i.response.send_message("Already at the bottom.", ephemeral=True)
                return
            new_order = list(category_order)
            new_order[selected_index], new_order[selected_index + 1] = new_order[selected_index + 1], new_order[selected_index]
            self._set_category_order(guild_id, new_order)
            selected_index += 1
            await i.response.defer()
            await refresh()

        async def reset_cb(i: discord.Interaction):
            self._set_category_order(guild_id, list(DEFAULT_CATEGORY_ORDER))
            nonlocal selected_index
            selected_index = 0
            await i.response.defer()
            await refresh()

        async def close_cb(i: discord.Interaction):
            try:
                await i.response.defer()
                await msg.delete()
            except Exception:
                pass

        cat_select.callback = select_cb
        up_btn.callback = up_cb
        down_btn.callback = down_cb
        reset_btn.callback = reset_cb
        close_btn.callback = close_cb

        view.add_item(cat_select)
        view.add_item(up_btn)
        view.add_item(down_btn)
        view.add_item(reset_btn)
        view.add_item(close_btn)
        await msg.edit(view=view)

    # ---------- Admin command: manage custom categories ----------
    @commands.command(name="ospresetcategories")
    @commands.has_permissions(administrator=True)
    async def ospresetcategories(self, ctx: commands.Context):
        """Add or remove custom preset categories for this server."""
        guild_id = _guild_key(ctx)
        custom_cats = self._get_custom_categories(guild_id)

        def _embed(custom):
            disabled = self._get_disabled_default_categories(guild_id)
            lines = ["**Default Categories:**"]
            for c in ABILITY_CATEGORIES:
                if c in disabled:
                    lines.append(f"~{c}~ *(disabled)*")
                else:
                    lines.append(f"{c}")
            lines.append("")
            lines.append("**Custom Categories:**")
            if custom:
                for i, c in enumerate(custom):
                    lines.append(f"{i+1}. {c}")
            else:
                lines.append("*(none — use Add to create one)*")
            lines.append("")
            emb = discord.Embed(
                title="Preset Categories",
                description="\n".join(lines),
                color=EMBED_COLOR,
                timestamp=datetime.utcnow(),
            )
            emb.set_footer(text=FOOTER_TEXT)
            return emb

        msg = await ctx.send(embed=_embed(custom_cats))

        view = View(timeout=180)
        add_btn = Button(label="Add Category", style=discord.ButtonStyle.success, emoji="➕")
        remove_btn = Button(label="Remove Category", style=discord.ButtonStyle.danger, emoji="➖")
        close_btn = Button(label="Close", style=discord.ButtonStyle.secondary)

        async def refresh(interaction=None, components=None, resolved=None):
            nonlocal custom_cats
            custom_cats = self._get_custom_categories(guild_id)
            try:
                await msg.edit(embed=_embed(custom_cats), view=view)
            except Exception as e:
                print(f"[DEBUG ospresetcategories] refresh error: {e}")
                pass

        async def add_cb(i: discord.Interaction):
            modal = AddCategoryModal(cog=self, guild_id=guild_id, refresh_cb=refresh)
            await i.response.send_modal(modal)

        async def remove_cb(i: discord.Interaction):
            nonlocal custom_cats
            all_cats = self._get_all_categories(guild_id)
            if not all_cats:
                await i.response.send_message("No categories to remove.", ephemeral=True)
                return
            options = [discord.SelectOption(label=c, value=c) for c in all_cats]
            select = Select(placeholder="Pick a category to remove/disable", options=options, min_values=1, max_values=1)

            async def sel_cb(sel_i: discord.Interaction):
                if not sel_i.data or "values" not in sel_i.data or not sel_i.data["values"]:
                    await sel_i.response.defer()
                    return
                cat_to_remove = sel_i.data["values"][0]
                is_default = cat_to_remove in ABILITY_CATEGORIES
                # Find presets using this category
                presets = self._load_presets(guild_id)
                affected = [p for p in presets if p.get("category") == cat_to_remove]
                if affected:
                    # Ask which category to reassign them to
                    remaining = [c for c in self._get_all_categories(guild_id) if c != cat_to_remove]
                    reassign_opts = [discord.SelectOption(label=c, value=c) for c in remaining]
                    reassign_opts.append(discord.SelectOption(label="Uncategorized (no category)", value="__none__"))
                    reassign_sel = Select(
                        placeholder=f"Reassign {len(affected)} preset(s) to...",
                        options=reassign_opts, min_values=1, max_values=1,
                    )

                    async def reassign_cb(r_i: discord.Interaction):
                        if not r_i.data or "values" not in r_i.data or not r_i.data["values"]:
                            await r_i.response.defer()
                            return
                        target = r_i.data["values"][0]
                        new_cat = None if target == "__none__" else target
                        conn = sqlite3.connect(DB_PATH)
                        try:
                            conn.execute(
                                "UPDATE presets SET category = ? WHERE guild_id = ? AND category = ?",
                                (new_cat, guild_id, cat_to_remove),
                            )
                            conn.commit()
                        finally:
                            conn.close()
                        await _do_remove(cat_to_remove, is_default)
                        await r_i.response.defer()
                        await refresh()

                    reassign_sel.callback = reassign_cb
                    rv = View(timeout=60)
                    rv.add_item(reassign_sel)
                    try:
                        await sel_i.response.send_message(
                            f"**{len(affected)} preset(s)** use `{cat_to_remove}`. Choose a new category:",
                            view=rv, ephemeral=True,
                        )
                    except Exception:
                        pass
                else:
                    await _do_remove(cat_to_remove, is_default)
                    await sel_i.response.defer()
                    await refresh()

            async def _do_remove(cat: str, is_default: bool):
                if is_default:
                    disabled = self._get_disabled_default_categories(guild_id)
                    if cat not in disabled:
                        disabled.append(cat)
                        self._set_disabled_default_categories(guild_id, disabled)
                else:
                    remaining = [c for c in self._get_custom_categories(guild_id) if c != cat]
                    self._set_custom_categories(guild_id, remaining)
                order = self._get_category_order(guild_id)
                if cat in order:
                    order.remove(cat)
                    self._set_category_order(guild_id, order)

            select.callback = sel_cb
            v = View(timeout=60)
            v.add_item(select)
            await i.response.send_message("Select a category to remove/disable:", view=v, ephemeral=True)

        async def close_cb(i: discord.Interaction):
            try:
                await i.response.defer()
                await msg.delete()
            except Exception:
                pass

        class AddCategoryModal(Modal, title="Add Custom Category"):
            def __init__(self, cog, guild_id, refresh_cb):
                super().__init__()
                self.name_input = TextInput(label="Category name", max_length=50)
                self.add_item(self.name_input)
                self._cog = cog
                self._guild_id = guild_id
                self._refresh_view = refresh_cb

            async def on_submit(self, interaction: discord.Interaction):
                name = self.name_input.value.strip()
                print(f"[DEBUG ospresetcategories] Submitted name='{name}'")
                if not name:
                    return await interaction.response.send_message("Name cannot be empty.", ephemeral=True)
                # Check if it's a disabled default — re-enable it
                disabled = self._cog._get_disabled_default_categories(self._guild_id)
                if name in disabled:
                    disabled.remove(name)
                    self._cog._set_disabled_default_categories(self._guild_id, disabled)
                    print(f"[DEBUG ospresetcategories] Re-enabled default category '{name}'")
                    await interaction.response.defer()
                    await self._refresh_view()
                    return
                all_cats = self._cog._get_all_categories(self._guild_id)
                if name in all_cats:
                    return await interaction.response.send_message(f"Category `{name}` already exists.", ephemeral=True)
                current = self._cog._get_custom_categories(self._guild_id)
                current.append(name)
                self._cog._set_custom_categories(self._guild_id, current)
                print(f"[DEBUG ospresetcategories] Added category '{name}' to guild {self._guild_id}")
                await interaction.response.defer()
                await self._refresh_view()

            async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
                print(f"[ERROR ospresetcategories modal] {error}")
                try:
                    await interaction.response.send_message(f"Error: {error}", ephemeral=True)
                except Exception:
                    pass

        add_btn.callback = add_cb
        remove_btn.callback = remove_cb
        close_btn.callback = close_cb

        view.add_item(add_btn)
        view.add_item(remove_btn)
        view.add_item(close_btn)
        await msg.edit(view=view)