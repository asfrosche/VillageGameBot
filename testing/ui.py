"""Discord UI components for the testing framework — embeds, views, pagination."""

from __future__ import annotations

import math
from typing import Any

import discord


def progress_bar(pct: float, width: int = 10) -> str:
    """Render a progress bar string like ████░░░░░░."""
    filled = round(pct / 100 * width)
    empty = width - filled
    return "█" * filled + "░" * empty


def status_emoji(pct: float) -> str:
    if pct >= 80:
        return "🟢"
    elif pct >= 40:
        return "🟡"
    return "🔴"


def build_audit_embed(summary: dict, cogs: list[tuple[str, float]]) -> discord.Embed:
    embed = discord.Embed(
        title="🔍 BOT AUDIT",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Total Cogs", value=str(summary["cogs_total"]), inline=True)
    embed.add_field(name="Total Commands", value=str(summary["total_commands"]), inline=True)
    embed.add_field(name="Cogs with Tests", value=str(summary["cogs_with_tests"]), inline=True)

    pct = summary["overall_coverage"]
    embed.add_field(
        name=f"Overall Coverage {status_emoji(pct)}",
        value=f"{progress_bar(pct, 15)} **{pct}%**",
        inline=False,
    )

    cov_text = "\n".join(
        f"{status_emoji(pct)} **{name}** {progress_bar(pct)} {pct}%"
        for name, pct in cogs[:15]
    )
    if cogs:
        embed.add_field(name="Cog Coverage (worst first)", value=cov_text or "No cogs", inline=False)

    return embed


def build_cog_detail_embed(canonical: str, info: Any, cov: Any) -> discord.Embed:
    embed = discord.Embed(
        title=f"📋 {info.name} Cog",
        color=discord.Color.teal(),
        description=f"**File:** `{info.file}`",
    )
    embed.add_field(name="Cog Class", value=info.cog_class or "N/A", inline=True)
    embed.add_field(name="Lines", value=str(info.line_count), inline=True)

    if cov:
        pct = cov.estimated_overall
        embed.add_field(
            name=f"Coverage {status_emoji(pct)}",
            value=f"{progress_bar(pct, 12)} **{pct}%**",
            inline=False,
        )
        embed.add_field(
            name="Commands",
            value=f"Tested: {cov.tested_commands}/{cov.total_commands}",
            inline=True,
        )
        embed.add_field(
            name="Helpers",
            value=f"Tested: {cov.tested_helpers}/{cov.total_helpers} (est.)",
            inline=True,
        )

    embed.add_field(name="Prefix Commands", value=str(len(info.prefix_commands)), inline=True)
    embed.add_field(name="Slash Commands", value=str(len(info.slash_commands)), inline=True)
    embed.add_field(name="Listeners", value=str(len(info.listeners)), inline=True)
    embed.add_field(name="Views", value=str(len(info.views)), inline=True)
    embed.add_field(name="Modals", value=str(len(info.modals)), inline=True)
    embed.add_field(name="Selects", value=str(len(info.selects)), inline=True)
    embed.add_field(name="Tasks", value=str(len(info.tasks)), inline=True)
    embed.add_field(name="Methods", value=f"{info.total_methods} ({info.public_methods} pub, {info.private_methods} priv)", inline=True)

    if info.prefix_commands:
        embed.add_field(
            name="Prefix Commands",
            value=", ".join(f"`{c}`" for c in info.prefix_commands[:20]),
            inline=False,
        )
    if info.slash_commands:
        embed.add_field(
            name="Slash Commands",
            value=", ".join(f"`{c}`" for c in info.slash_commands[:20]),
            inline=False,
        )
    if cov and cov.test_files:
        embed.add_field(
            name="Test Files",
            value="\n".join(f"`{f}`" for f in cov.test_files),
            inline=False,
        )

    return embed


def build_coverage_embed(summary: dict, sorted_cogs: list[tuple[str, Any]]) -> discord.Embed:
    embed = discord.Embed(
        title="📊 Test Coverage Report",
        color=discord.Color.green(),
    )
    pct = summary["overall_coverage"]
    embed.description = (
        f"{status_emoji(pct)} **Project Coverage: {progress_bar(pct, 15)} {pct}%**\n"
        f"Commands: {summary['tested_commands']}/{summary['total_commands']} ({summary['command_coverage']}%) | "
        f"Helpers: ~{summary['tested_helpers']}/{summary['total_helpers']} ({summary['helper_coverage']}%)"
    )

    embed.add_field(name="Total Cogs", value=str(summary["cogs_total"]), inline=True)
    embed.add_field(name="Cogs with Tests", value=str(summary["cogs_with_tests"]), inline=True)

    lines = []
    for name, cov in sorted_cogs[:25]:
        p = cov.estimated_overall
        lines.append(f"{status_emoji(p)} **{name}** {progress_bar(p)} {p}%")
    if lines:
        embed.add_field(name="Per-Cog Coverage", value="\n".join(lines), inline=False)

    return embed


def build_test_result_embed(results: list[tuple[str, bool, str]]) -> discord.Embed:
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    embed = discord.Embed(
        title=f"🧪 Test Results ({passed}/{total} passed)",
        color=discord.Color.green() if passed == total else discord.Color.orange(),
    )
    for name, ok, detail in results:
        icon = "✅" if ok else "❌"
        embed.add_field(name=f"{icon} {name}", value=detail or "OK", inline=False)
    return embed


def build_error_embed(record: Any) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚠️ Error: {record.id}",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Cog", value=record.cog, inline=True)
    embed.add_field(name="Command", value=record.command, inline=True)
    embed.add_field(name="Runtime", value=f"{record.runtime_ms}ms", inline=True)
    embed.add_field(name="User", value=record.user, inline=True)
    embed.add_field(name="Guild", value=record.guild, inline=True)
    embed.add_field(name="Exception", value=f"`{record.exception[:500]}`", inline=False)
    embed.add_field(name="Args", value=f"`{record.args[:300]}`" if record.args else "None", inline=False)
    tb = record.traceback[-1000:]
    embed.add_field(name="Traceback (last 1000 chars)", value=f"```{tb}```", inline=False)
    return embed


def build_stats_embed(summary: dict, errors: list) -> discord.Embed:
    embed = discord.Embed(
        title="📈 Testing Framework Stats",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Cogs Discovered", value=str(summary["cogs_total"]), inline=True)
    embed.add_field(name="Commands Found", value=str(summary["total_commands"]), inline=True)
    embed.add_field(name="Cogs with Tests", value=str(summary["cogs_with_tests"]), inline=True)
    embed.add_field(name="Command Coverage", value=f"{summary['command_coverage']}%", inline=True)
    embed.add_field(name="Helper Coverage (est.)", value=f"{summary['helper_coverage']}%", inline=True)
    embed.add_field(name="Tracked Errors", value=str(len(errors)), inline=True)
    return embed


class PaginatedView(discord.ui.View):
    """Generic paginated view for navigating lists."""

    def __init__(self, pages: list[discord.Embed], author_id: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author_id = author_id
        self.current = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    def _update_buttons(self):
        self.first_page.disabled = self.current <= 0
        self.prev_page.disabled = self.current <= 0
        self.next_page.disabled = self.current >= len(self.pages) - 1
        self.last_page.disabled = self.current >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your interaction.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.grey)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[0], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.grey)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label=f"0/0", style=discord.ButtonStyle.grey, disabled=True)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.grey)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.grey)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = len(self.pages) - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[-1], view=self)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass
