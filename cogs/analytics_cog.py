from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime

logger = logging.getLogger("analytics.cog")

import discord
from discord.ext import commands

from utils.analytics import get_analytics_service
from utils.analytics.db import AnalyticsDB


_TRACEBACK_FILE_RE = re.compile(r'File "([^"]+)", line (\d+)')


def _extract_source_location(tb: str) -> tuple[str | None, int | None]:
    """Extract the first source file path and line number from a traceback string."""
    m = _TRACEBACK_FILE_RE.search(tb)
    if m:
        return m.group(1), int(m.group(2))
    return None, None


def _shorten_path(path: str | None) -> str | None:
    """Shorten a file path to just the last two components for display."""
    if path is None:
        return None
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]


def _format_duration(seconds: float) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms/1000:.2f}s"
    return f"{ms:.0f}ms"


def _extract_error_message(tb: str, exc_type: str) -> str:
    """Extract the actual error message from a traceback string.

    Parses the last line matching ``ExceptionType: message`` and
    returns the message portion only.  Falls back to the exception
    type or the last traceback line.
    """
    if not tb:
        return exc_type
    lines = [l.strip() for l in tb.strip().split("\n") if l.strip()]
    if not lines:
        return exc_type
    for line in reversed(lines):
        if exc_type and line.startswith(exc_type):
            msg = line[len(exc_type):].lstrip(": ")
            return msg if msg else exc_type
    return lines[-1]


def _human_timestamp(iso_str: str | None, _now: datetime | None = None) -> str:
    """Convert an ISO timestamp to a human-friendly relative time."""
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return iso_str[:19] if iso_str else "?"

    now = _now or datetime.utcnow()
    diff = now - dt
    secs = int(diff.total_seconds())

    if secs < 60:
        return "just now"
    if secs < 3600:
        m = secs // 60
        return f"{m} min ago"

    # Same-day → absolute, not "N hours ago"
    if dt.date() == now.date():
        return f"Today {dt.strftime('%I:%M %p').lstrip('0').lower()}"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if secs < 172800:
        return f"Yesterday {dt.strftime('%I:%M %p').lstrip('0').lower()}"

    return dt.strftime("%b %d %I:%M %p").lstrip("0").replace(" 0", " ")


def _clean_cmd_name(name: str | None, max_len: int | None = None) -> str:
    """Return a cleaned-up command name, replacing 'unknown' and truncating if needed."""
    if not name or name.strip().lower() == "unknown":
        return "Unknown Command"
    if max_len and len(name) > max_len:
        return name[:max_len] + "…"
    return name


_DEV_IDS = {450772749829537793, 691180618402234399}


def _dev_only():
    return commands.check(lambda ctx: ctx.author.id in _DEV_IDS)


# ── Modals ──────────────────────────────────────────────────────────

class CommandFilterModal(discord.ui.Modal):
    """Filter commands by name or toggle sort mode."""

    def __init__(self, view: AnalyticsView):
        super().__init__(title="Command Filters", timeout=60)
        self.view = view
        self.query = discord.ui.TextInput(
            label="Search (command or cog name)",
            placeholder="Leave blank to keep current filter",
            required=False,
            max_length=100,
        )
        self.add_item(self.query)
        self.sort = discord.ui.TextInput(
            label="Sort: failure_rate / total_execs / avg_time",
            placeholder="failure_rate",
            required=False,
            max_length=20,
        )
        self.add_item(self.sort)

    async def on_submit(self, interaction: discord.Interaction):
        if self.query.value.strip():
            self.view._cmd_search = self.query.value.strip()
        if self.sort.value.strip() in ("failure_rate", "total_execs", "avg_time_ms"):
            self.view._cmd_sort = self.sort.value.strip()
        self.view._cmd_page = 1
        db = self.view.cog._db
        embed = self.view._build_page("commands", db)
        await interaction.response.edit_message(embed=embed, view=self.view)


class ErrorFilterModal(discord.ui.Modal):
    """Filter errors by command name."""

    def __init__(self, view: AnalyticsView):
        super().__init__(title="Error Filters", timeout=60)
        self.view = view
        self.query = discord.ui.TextInput(
            label="Filter by command name",
            placeholder="e.g. analytics, or leave blank to clear",
            required=False,
            max_length=100,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        self.view._err_filter = self.query.value.strip() or None
        self.view._err_page = 1
        self.view._err_viewing = None
        db = self.view.cog._db
        embed = self.view._build_page("errors", db)
        await interaction.response.edit_message(embed=embed, view=self.view)


# ── Standalone pagination view (used by .failures) ─────────────────

class ErrorPaginationView(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed], author_id: int):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.author_id = author_id
        self.current = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.current <= 0
        self.next_button.disabled = self.current >= len(self.embeds) - 1

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, _):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        self.current -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        self.current += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


# ── Main dashboard view ────────────────────────────────────────────

class AnalyticsView(discord.ui.View):
    """Interactive analytics dashboard with four pages."""

    def __init__(self, cog: AnalyticsCog, author_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author_id
        self.message: discord.Message | None = None
        self._current_page = "summary"
        self._cmd_search: str | None = None
        self._cmd_sort: str = "failure_rate"
        self._err_filter: str | None = None
        self._cmd_page = 1
        self._cmd_total_pages = 1
        self._err_page = 1
        self._err_total_pages = 1
        self._err_viewing: int | None = None
        self._err_chunk: list[dict] = []

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in _DEV_IDS:
            await interaction.response.send_message("You are not authorised to use this dashboard.", ephemeral=True)
            return False
        return True

    # ── Page selection (row 0) ─────────────────────────────────────

    @discord.ui.select(
        placeholder="Select a page…",
        options=[
            discord.SelectOption(label="Summary", value="summary", emoji="📊",
                                 description="Health status and actionable issues"),
            discord.SelectOption(label="Commands", value="commands", emoji="📋",
                                 description="Per-command stats sorted by failure rate"),
            discord.SelectOption(label="Recent Errors", value="errors", emoji="⚠️",
                                 description="Newest errors with messages and source location"),
            discord.SelectOption(label="Health", value="health", emoji="💚",
                                 description="Uptime, latency, memory and cog totals"),
        ],
        row=0,
    )
    async def page_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self._current_page = select.values[0]
        self._err_viewing = None
        db = self.cog._db
        embed = self._build_page(self._current_page, db)
        await interaction.response.edit_message(embed=embed, view=self)

    # ── Row 1: navigation buttons ─────────────────────────────────

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def nav_prev(self, interaction: discord.Interaction, _):
        if self._current_page == "errors" and self._err_viewing is not None:
            self._err_viewing = None          # back to error list
        else:
            self._page_nav(-1)
        db = self.cog._db
        embed = self._build_page(self._current_page, db)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction: discord.Interaction, _):
        db = self.cog._db
        if db is None:
            await interaction.response.send_message("Database not available.", ephemeral=True)
            return
        embed = self._build_page(self._current_page, db)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def nav_next(self, interaction: discord.Interaction, _):
        self._page_nav(1)
        db = self.cog._db
        embed = self._build_page(self._current_page, db)
        await interaction.response.edit_message(embed=embed, view=self)

    # ── Row 2: action buttons ─────────────────────────────────────

    @discord.ui.button(label="🔍 Filter", style=discord.ButtonStyle.primary, row=2)
    async def filter_btn(self, interaction: discord.Interaction, _):
        if self._current_page == "commands":
            modal = CommandFilterModal(self)
            await interaction.response.send_modal(modal)
        elif self._current_page == "errors":
            modal = ErrorFilterModal(self)
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message(
                "Filter is available on Commands and Errors pages.", ephemeral=True)

    @discord.ui.button(label="⏱ Avg Time", style=discord.ButtonStyle.secondary, row=2)
    async def sort_time_btn(self, interaction: discord.Interaction, _):
        self._current_page = "commands"
        self._cmd_sort = "avg_time_ms"
        self._cmd_page = 1
        db = self.cog._db
        embed = self._build_page("commands", db)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📈 Most Used", style=discord.ButtonStyle.secondary, row=2)
    async def sort_usage_btn(self, interaction: discord.Interaction, _):
        self._current_page = "commands"
        self._cmd_sort = "total_execs"
        self._cmd_page = 1
        db = self.cog._db
        embed = self._build_page("commands", db)
        await interaction.response.edit_message(embed=embed, view=self)

    # ── Row 3: error picker (only active on Errors page) ──────────

    @discord.ui.select(
        placeholder="Select an error to inspect…",
        options=[discord.SelectOption(label="—", value="__none__")],
        row=3,
    )
    async def error_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "__back__":
            self._err_viewing = None
        elif val != "__none__":
            self._err_viewing = int(val)
        db = self.cog._db
        embed = self._build_page(self._current_page, db)
        await interaction.response.edit_message(embed=embed, view=self)

    # ── Internal helpers ──────────────────────────────────────────

    def _page_nav(self, direction: int):
        page = self._current_page
        if page == "errors" and self._err_viewing is not None:
            return
        if page == "commands":
            new = self._cmd_page + direction
            if 1 <= new <= self._cmd_total_pages:
                self._cmd_page = new
        elif page == "errors":
            new = self._err_page + direction
            if 1 <= new <= self._err_total_pages:
                self._err_page = new

    def _update_page_nav(self):
        page = self._current_page
        self.nav_prev.disabled = True
        self.nav_next.disabled = True
        if page == "errors" and self._err_viewing is not None:
            self.nav_prev.disabled = False   # acts as "back"
            self.nav_next.disabled = True
            return
        if page == "commands":
            self.nav_prev.disabled = self._cmd_page <= 1
            self.nav_next.disabled = self._cmd_page >= self._cmd_total_pages
        elif page == "errors":
            self.nav_prev.disabled = self._err_page <= 1
            self.nav_next.disabled = self._err_page >= self._err_total_pages

    def _update_error_select(self):
        """Refresh the error-select dropdown to match the current page state."""
        error_row = self.error_select
        if self._current_page == "errors":
            if self._err_viewing is not None:
                error_row.options = [discord.SelectOption(label="← Back to error list", value="__back__")]
                error_row.placeholder = f"Viewing error #{self._err_viewing}"
            else:
                error_row.placeholder = "Select an error to inspect…"
                opts = []
                for e in self._err_chunk:
                    exc_msg = _extract_error_message(e.get("traceback") or "", e["exception_type"])
                    cn = _clean_cmd_name(e["command_name"], 20)
                    label = f"#{e['id']} — {cn} — {exc_msg[:60]}"
                    if len(label) > 100:
                        label = label[:97] + "…"
                    opts.append(discord.SelectOption(label=label, value=str(e["id"])))
                error_row.options = opts or [discord.SelectOption(label="No errors", value="__none__")]
            error_row.disabled = False
        else:
            error_row.options = [discord.SelectOption(label="—", value="__none__")]
            error_row.placeholder = "Only available on Errors page"
            error_row.disabled = True

    # ── Page dispatcher ────────────────────────────────────────────

    def _build_page(self, page: str, db: AnalyticsDB | None) -> discord.Embed:
        if db is None:
            embed = discord.Embed(title="Debug Dashboard", color=0x7C5CFC)
            embed.description = "Database not available."
            return embed

        if page == "errors" and self._err_viewing is not None:
            embed = self._build_error_detail(db)
        else:
            builders = {
                "summary": self._build_summary,
                "commands": self._build_commands,
                "errors": self._build_recent_errors,
                "health": self._build_health,
            }
            builder = builders.get(page)
            embed = builder(db) if builder else discord.Embed(title="Unknown Page", color=0x7C5CFC)

        self._update_error_select()
        self._update_page_nav()
        return embed

    # ════════════════════════════════════════════════════════════════
    #  PAGE BUILDERS
    # ════════════════════════════════════════════════════════════════

    # ── Summary ────────────────────────────────────────────────────

    def _build_summary(self, db: AnalyticsDB) -> discord.Embed:
        bot = self.cog.bot
        latency = bot.latency * 1000
        recent_errs = db.get_recent_error_count(minutes=60)
        svc = get_analytics_service()
        analytics_ok = svc is not None and svc.enabled
        latency_ok = latency < 200
        uptime_secs = (datetime.utcnow() - self.cog.start_time).total_seconds()
        uptime_str = _format_duration(uptime_secs)

        # ── Health status ──────────────────────────────────────────
        if recent_errs > 0:
            status = "🔴 **Critical Issues**"
            status_color = 0xE74C3C
        elif not analytics_ok or not latency_ok:
            status = "🟡 **Warnings**"
            status_color = 0xF1C40F
        else:
            status = "🟢 **Healthy**"
            status_color = 0x2ECC71

        embed = discord.Embed(title="Summary — Status Dashboard", colour=status_color)
        embed.description = (
            f"{status}\n"
            f"⚡ {latency:.0f} ms  ·  ⏱ {uptime_str}  ·  ❌ {recent_errs} error{'s' if recent_errs != 1 else ''} (1h)"
        )

        # ── Needs Attention (recent-first) ─────────────────────────
        recent_cmd_set: set[str] = set()
        for e in db.get_errors(limit=50):
            recent_cmd_set.add(e["command_name"])

        recent_issues: list[str] = []
        historical_issues: list[str] = []

        failing_list = db.get_most_failing_commands(limit=5)
        for f in failing_list:
            cn = _clean_cmd_name(f["command_name"])
            icon = "🔴" if f["failure_rate"] >= 75 else "🟠" if f["failure_rate"] >= 25 else "🟡"
            line = f"{icon} `{cn}` — {f['failure_rate']}% fail ({f['total_failures']}/{f['total_execs']})"
            if f["command_name"] in recent_cmd_set:
                recent_issues.append(f"{icon} **ACTIVE** — `{cn}` — {f['failure_rate']}% fail ({f['total_failures']}/{f['total_execs']})")
            else:
                historical_issues.append(line)

        slow_list = db.get_slowest_commands(limit=3)
        for s in slow_list:
            if any(f["command_name"] == s["command_name"] for f in failing_list):
                continue
            cn = _clean_cmd_name(s["command_name"])
            icon = "🔴" if s["avg_time_ms"] >= 5000 else "🟠" if s["avg_time_ms"] >= 2000 else "🟡"
            line = f"{icon} `{cn}` — {_fmt_ms(s['avg_time_ms'])} avg"
            if s["command_name"] in recent_cmd_set:
                recent_issues.append(f"{icon} **ACTIVE** — `{cn}` — {_fmt_ms(s['avg_time_ms'])} avg")
            else:
                historical_issues.append(line)

        issues = recent_issues + historical_issues

        if issues:
            embed.add_field(
                name="🚨 Needs Attention",
                value="\n".join(issues[:6])[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="✅ Status",
                value="✅ Nothing currently requires attention.",
                inline=False,
            )

        # ── Recent errors short-list ────────────────────────────────
        recent = db.get_errors(limit=3)
        if recent:
            lines = []
            for e in recent:
                exc_msg = _extract_error_message(e.get("traceback") or "", e["exception_type"])
                src_file, src_line = _extract_source_location(e.get("traceback") or "")
                loc = ""
                if src_file:
                    loc = f" 📍`{_shorten_path(src_file)}:{src_line}`"
                cn = _clean_cmd_name(e["command_name"], 25)
                lines.append(
                    f"`#{e['id']}` `{cn}` — `{exc_msg[:60]}`{loc} — {_human_timestamp(e['timestamp'])}"
                )
            embed.add_field(
                name=f"🕐 Recent ({len(recent)})",
                value="\n".join(lines)[:1024],
                inline=False,
            )

        embed.set_footer(text="Use the page selector above to drill down")
        return embed

    # ── Commands ───────────────────────────────────────────────────

    def _build_commands(self, db: AnalyticsDB) -> discord.Embed:
        per_page = 10
        cmds_data = db.get_commands(
            sort=self._cmd_sort, order="desc",
            search=self._cmd_search or "",
            page=self._cmd_page, per_page=per_page,
        )
        self._cmd_total_pages = max((cmds_data["total"] - 1) // per_page + 1, 1)
        if self._cmd_page > self._cmd_total_pages:
            self._cmd_page = self._cmd_total_pages

        embed = discord.Embed(title="Commands", color=0x3498DB)
        if self._cmd_search:
            embed.title += f" — filtered: `{self._cmd_search}`"
        sort_label = {
            "failure_rate": "failure rate",
            "total_execs": "usage",
            "avg_time_ms": "avg time",
        }.get(self._cmd_sort, self._cmd_sort)
        footer = (
            f"Sorted by {sort_label}  ·  Page {self._cmd_page}/{self._cmd_total_pages}"
            f"  ·  {cmds_data['total']} commands  ·  🔍 Filter to search"
        )

        if not cmds_data["items"]:
            embed.description = "No commands found."
            embed.set_footer(text=footer)
            return embed

        lines = []
        for c in cmds_data["items"]:
            if not c["command_name"] or c["command_name"].strip().lower() == "unknown":
                continue
            rate = c.get("failure_rate", 0)
            indicator = "🟢" if rate == 0 else "🟡" if rate < 10 else "🟠" if rate < 50 else "🔴"
            cn = _clean_cmd_name(c["command_name"], 25)

            lines.append(
                f"{indicator} `{cn}`\n"
                f"    └ {c['failure_rate']}% fail  ·  {c['total_execs']}x  ·  "
                f"avg {_fmt_ms(c['avg_time_ms'])}  ·  p95 {_fmt_ms(c['p95_ms'])}  ·  👤 {c['unique_users']}"
            )

        if not lines:
            embed.description = "No commands found."
            embed.set_footer(text=footer)
            return embed

        embed.description = "\n".join(lines)
        embed.set_footer(text=footer)
        return embed

    # ── Recent Errors ──────────────────────────────────────────────

    def _build_recent_errors(self, db: AnalyticsDB) -> discord.Embed:
        embed = discord.Embed(title="Recent Errors", color=0xE74C3C)

        if self._err_filter:
            embed.title += f" — filtered: `{self._err_filter}`"

        per_page = 4
        errs = db.get_errors(command_name=self._err_filter, limit=200)
        self._err_total_pages = max((len(errs) - 1) // per_page + 1, 1)
        if self._err_page > self._err_total_pages:
            self._err_page = self._err_total_pages
        start = (self._err_page - 1) * per_page
        chunk = errs[start:start + per_page]
        self._err_chunk = chunk

        if not chunk:
            embed.description = "No errors recorded."
            embed.set_footer(text="Use 🔍 Filter to search by command name")
            return embed

        for e in chunk:
            exc_msg = _extract_error_message(e.get("traceback") or "", e["exception_type"])
            src_file, src_line = _extract_source_location(e.get("traceback") or "")
            loc = ""
            if src_file:
                loc = f" 📍`{_shorten_path(src_file)}:{src_line}`"
            cn = _clean_cmd_name(e["command_name"], 25)
            value = (
                f"**{e['exception_type']}**  ·  🕐 {_human_timestamp(e.get('timestamp'))}\n"
                f"⚙️ {e['cog_name'] or '?'}  ·  👤 {e['user_id'] or '?'}  ·  🏠 {e['guild_id'] or '?'}"
                f"{loc}"
            )
            embed.add_field(
                name=f"`#{e['id']}` `{cn}` — {exc_msg[:200]}",
                value=value[:1024],
                inline=False,
            )

        embed.set_footer(
            text=f"Page {self._err_page}/{self._err_total_pages}  ·  {len(errs)} errors"
            f"  ·  Select an error below to inspect"
        )
        return embed

    # ── Error Detail (drill-down) ──────────────────────────────────

    def _build_error_detail(self, db: AnalyticsDB) -> discord.Embed:
        errs = db.get_errors(limit=200)
        target = next((e for e in errs if e["id"] == self._err_viewing), None)
        if target is None:
            self._err_viewing = None
            return self._build_recent_errors(db)

        tb = target.get("traceback") or ""
        exc_msg = _extract_error_message(tb, target["exception_type"])
        src_file, src_line = _extract_source_location(tb)
        loc = f"`{_shorten_path(src_file)}:{src_line}`" if src_file else "?"

        embed = discord.Embed(
            title=f"Error #{target['id']} — `{_clean_cmd_name(target['command_name'])}`",
            color=0xE74C3C,
        )
        embed.description = (
            f"```{exc_msg[:1020]}```\n\n"
            f"**{target['exception_type']}**\n"
            f"📍 {loc}  ·  🕐 {_human_timestamp(target.get('timestamp'))}\n"
            f"⚙️ {target['cog_name'] or '?'}  ·  "
            f"👤 {target['user_id'] or '?'}  ·  "
            f"🏠 {target['guild_id'] or '?'}"
        )
        embed.set_footer(text="◀ Back to error list")
        return embed

    # ── Health ─────────────────────────────────────────────────────

    def _build_health(self, db: AnalyticsDB) -> discord.Embed:
        bot = self.cog.bot
        latency = bot.latency * 1000
        uptime_secs = (datetime.utcnow() - self.cog.start_time).total_seconds()
        uptime_str = _format_duration(uptime_secs)
        recent_errs = db.get_recent_error_count(minutes=60)
        svc = get_analytics_service()
        analytics_ok = svc is not None and svc.enabled

        # Status summary
        status_text: str
        summary_line: str
        if recent_errs > 0:
            badge = "🔴"
            status_text = "Critical Issues"
            summary_line = "Some system checks failed"
        elif not analytics_ok or latency >= 500:
            badge = "🟡"
            status_text = "Warning"
            summary_line = "Some system checks failed"
        else:
            badge = "🟢"
            status_text = "Healthy"
            summary_line = "All system checks passed"
        embed_colour = 0xE74C3C if badge == "🔴" else 0xF1C40F if badge == "🟡" else 0x2ECC71

        embed = discord.Embed(title="Bot Health", colour=embed_colour)
        embed.description = f"{badge} **{status_text}**\n{summary_line}"

        # Metrics
        lat_emoji = "🟢" if latency < 200 else "🟡" if latency < 500 else "🔴"
        embed.add_field(name="⚡ Latency", value=f"{lat_emoji} {latency:.0f} ms", inline=True)
        embed.add_field(name="⏱ Uptime", value=uptime_str, inline=True)
        embed.add_field(name="🧠 Memory", value=_get_memory_str(), inline=True)

        # DB size
        try:
            size_bytes = os.path.getsize(db.db_path)
            if size_bytes < 1024:
                db_size = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                db_size = f"{size_bytes / 1024:.1f} KB"
            else:
                db_size = f"{size_bytes / 1024 / 1024:.1f} MB"
        except Exception:
            db_size = "?"
        embed.add_field(name="💾 Database", value=db_size, inline=True)

        # Totals
        cog_count = len(bot.cogs)
        cmd_count = len(bot.commands)
        embed.add_field(
            name="📦 Loaded",
            value=f"{cog_count} Cogs\n{cmd_count} Commands",
            inline=True,
        )
        embed.add_field(
            name="✅ System Checks",
            value=f"{'✅' if analytics_ok else '❌'} Analytics: {'Enabled' if analytics_ok else 'Disabled'}\n"
                  f"{'✅' if recent_errs == 0 else '❌'} Errors (1h): {recent_errs}",
            inline=True,
        )

        embed.set_footer(text="Refresh to update")
        return embed

    # ── Timeout ────────────────────────────────────────────────────

    async def on_timeout(self):
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


# ── Helpers that need to be defined after AnalyticsView ────────────

def _get_memory_str() -> str:
    """Return a human-readable memory string using psutil or /proc."""
    try:
        import psutil
        proc = psutil.Process()
        mem_mb = proc.memory_info().rss / 1024 / 1024
        return f"{mem_mb:.0f} MB"
    except ImportError:
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return line.split()[1] + " KB"
        except Exception:
            pass
    return "N/A"


# ── Cog ────────────────────────────────────────────────────────────

class AnalyticsCog(commands.Cog):
    """Internal analytics commands. Restricted to bot developers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = datetime.utcnow()

    @property
    def _db(self) -> AnalyticsDB | None:
        svc = get_analytics_service()
        if svc is None or not svc._providers:
            return None
        from utils.analytics.local_provider import LocalDBProvider
        for p in svc._providers:
            if isinstance(p, LocalDBProvider):
                return p.db
        return None

    @_dev_only()
    @commands.command(name="analytics", aliases=["astats"])
    async def analytics(self, ctx: commands.Context):
        """Debug dashboard: health, commands, recent errors, and bot status."""
        svc = get_analytics_service()
        if not svc or not svc.enabled:
            await ctx.send("Analytics is disabled.")
            return

        db = self._db
        if db is None:
            await ctx.send("Analytics database not available.")
            return

        view = AnalyticsView(self, ctx.author.id)
        embed = view._build_page("summary", db)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @_dev_only()
    @commands.command(name="analyticsreset")
    async def analyticsreset(self, ctx: commands.Context):
        """Reset all analytics error records. Requires CONFIRM."""
        svc = get_analytics_service()
        if not svc or not svc.enabled:
            await ctx.send("Analytics is disabled.")
            return

        db = self._db
        if db is None:
            await ctx.send("Analytics database not available.")
            return

        await ctx.send(
            "⚠️ **Reset All Error Records**\n"
            "Type `CONFIRM` in this channel to permanently delete every error. "
            "This request expires in 30 seconds."
        )

        def check(m):
            return (
                m.author.id == ctx.author.id
                and m.channel.id == ctx.channel.id
                and m.content.strip() == "CONFIRM"
            )

        try:
            await self.bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("Reset cancelled (timeout).")
            return

        db.clear_errors()
        await ctx.send("✅ All analytics error records have been cleared.")

    @_dev_only()
    @commands.command(name="failures")
    async def failures(self, ctx: commands.Context, *, command_name: str = None):
        """Show commands with failures and their details. Use `.failures <command>` for per-command detail."""
        svc = get_analytics_service()
        if not svc or not svc.enabled:
            await ctx.send("Analytics is disabled.")
            return

        db = self._db
        if db is None:
            await ctx.send("Analytics database not available.")
            return

        if command_name:
            cmd = command_name.strip().removeprefix(".")
            errs = db.get_errors(command_name=cmd, limit=100)
            if not errs:
                await ctx.send(f"No errors found for `{cmd}`.")
                return

            per_page = 5
            pages = []
            for i in range(0, len(errs), per_page):
                chunk = errs[i:i + per_page]
                embed = discord.Embed(
                    title=f"Errors for `{cmd}`",
                    color=0xE74C3C,
                )
                for e in chunk:
                    exc_msg = _extract_error_message(
                        e.get("traceback") or "", e["exception_type"]
                    )
                    src_file, src_line = _extract_source_location(e.get("traceback") or "")
                    loc = ""
                    if src_file:
                        loc = f" 📍`{_shorten_path(src_file)}:{src_line}`"
                    value = (
                        f"**{e['exception_type']}**  ·  🕐 {_human_timestamp(e.get('timestamp'))}\n"
                        f"`{exc_msg[:200]}`\n"
                        f"⚙️ {e['cog_name'] or '?'}  ·  👤 {e['user_id'] or '?'}  ·  🏠 {e['guild_id'] or '?'}{loc}"
                    )
                    embed.add_field(
                        name=f"#{e['id']} — {_clean_cmd_name(e['command_name'], 25)}",
                        value=value[:1024],
                        inline=False,
                    )
                total_p = (len(errs) - 1) // per_page + 1
                embed.set_footer(text=f"Page {i // per_page + 1}/{total_p}  ·  {len(errs)} errors")
                pages.append(embed)

            view = ErrorPaginationView(pages, ctx.author.id)
            view.message = await ctx.send(embed=pages[0], view=view)
        else:
            summary = db.get_error_summary()
            recent = db.get_errors(limit=10)

            embed = discord.Embed(
                title="Error Summary",
                color=0xE74C3C,
            )
            embed.add_field(name="Total Errors", value=str(summary["total_errors"]), inline=True)

            by_cmd = summary.get("by_command", [])
            if by_cmd:
                lines = "\n".join(
                    f"`{_clean_cmd_name(c['command'])}` — {c['count']}x"
                    for c in by_cmd[:10]
                )
                embed.add_field(name="Commands with Errors", value=lines[:1024], inline=False)

            by_type = summary.get("by_type", [])
            if by_type:
                lines = "\n".join(
                    f"`{t['type']}` — {t['count']}x"
                    for t in by_type[:5]
                )
                embed.add_field(name="Error Types", value=lines[:1024], inline=False)

            if recent:
                lines = "\n".join(
                    f"`#{e['id']}` `{_clean_cmd_name(e['command_name'], 25)}` — {e['exception_type']}"
                    for e in recent[:5]
                )
                embed.add_field(name="Recent Errors", value=lines[:1024], inline=False)

            embed.set_footer(text="Use `.failures <command_name>` for per-command details")
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AnalyticsCog(bot))
