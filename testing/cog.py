"""testing/cog.py — Developer testing framework cog.

Commands:
.test        — Dashboard
.test audit  — Project audit
.test audit <cog> — Per-cog audit
.test coverage  — Coverage report
.test list      — List all commands
.test run       — Run all tests
.test run <cog> — Run cog tests
.test history   — Failed command history
.test errors    — Error log
.test error <id> — Show specific error
.test commands  — List all commands
.test cogs      — List all cogs
.test stats     — Framework statistics
.test logs      — View error logs
.test clearlogs — Clear error logs
"""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
import time
from typing import Any

import discord
from discord.ext import commands

from testing._path_utils import file_to_module
from testing.auditor import discover_all, collect_all_commands
from testing.coverage import analyze_coverage, get_project_summary
from testing.errors import capture_error, get_all_errors, get_error, clear_errors, flush_errors
from testing.ui import (
    PaginatedView,
    build_audit_embed,
    build_cog_detail_embed,
    build_coverage_embed,
    build_error_embed,
    build_stats_embed,
    status_emoji,
    progress_bar,
)
from testing.generator import generate_cog_test


class TestingCog(commands.Cog):
    """Developer testing, audit, coverage, and validation framework."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._test_results_cache: dict[str, Any] = {}

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_cog_class(self, canonical: str) -> type | None:
        """Dynamically import and return a cog class by canonical name."""
        cogs = discover_all()
        info = cogs.get(canonical)
        if not info or not info.cog_class:
            return None
        try:
            mod_name = file_to_module(info.file)
            mod = importlib.import_module(mod_name)
            return getattr(mod, info.cog_class)
        except Exception:
            return None

    def _run_pytest(self, args: list[str] | None = None) -> tuple[int, str, str]:
        """Run pytest and return (returncode, stdout, stderr)."""
        cmd = [sys.executable, "-m", "pytest"]
        if args:
            cmd.extend(args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timed out"
        except FileNotFoundError:
            return -2, "", "pytest not found"

    # ── Dashboard ────────────────────────────────────────────────────────────

    @commands.command(name="test")
    async def test_dashboard(self, ctx: commands.Context, *, args: str | None = None):
        """Developer testing dashboard. Use `.test help` for details."""
        if ctx.author.id not in (691180618402234399, 450772749829537793):  # asfro, bidet
            await ctx.send("❌ This command is restricted to the bot developers.")
            return
        parts = args.strip().split() if args else []
        if not parts:
            await self._show_dashboard(ctx)
            return

        subcmd = parts[0].lower()
        rest = " ".join(parts[1:])

        subcommands = {
            "audit": self._cmd_audit,
            "coverage": self._cmd_coverage,
            "list": self._cmd_list,
            "run": self._cmd_run,
            "history": self._cmd_history,
            "errors": self._cmd_errors,
            "error": self._cmd_error_detail,
            "commands": self._cmd_commands,
            "cogs": self._cmd_cogs,
            "stats": self._cmd_stats,
            "logs": self._cmd_errors,
            "clearlogs": self._cmd_clearlogs,
            "help": self._cmd_help,
        }

        handler = subcommands.get(subcmd)
        if not handler:
            await ctx.send(f"Unknown subcommand `{subcmd}`. Use `.test help`.")
            return

        await handler(ctx, rest)

    async def _show_dashboard(self, ctx: commands.Context):
        summary = get_project_summary()
        cogs = discover_all()
        embed = discord.Embed(
            title="🧪 Developer Testing Dashboard",
            color=discord.Color.blurple(),
            description=(
                f"**Overall Coverage:** {progress_bar(summary['overall_coverage'], 15)} {summary['overall_coverage']}%\n"
                f"**Cogs:** {summary['cogs_total']} | **Commands:** {summary['total_commands']}\n"
                f"**Test Files:** {summary['cogs_with_tests']} cogs have tests"
            ),
        )
        embed.add_field(
            name="Commands",
            value=(
                "`.test audit` — Full project audit\n"
                "`.test audit <cog>` — Per-cog audit\n"
                "`.test coverage` — Coverage report\n"
                "`.test run` — Run all tests\n"
                "`.test run <cog>` — Run cog tests\n"
                "`.test list` — List all commands\n"
                "`.test cogs` — List all cogs\n"
                "`.test errors` — View errors\n"
                "`.test error <id>` — Error details\n"
                "`.test stats` — Framework stats\n"
                "`.test clearlogs` — Clear errors\n"
                "`.test help` — Full help"
            ),
            inline=False,
        )
        errors = get_all_errors()
        if errors:
            embed.set_footer(text=f"⚠ {len(errors)} tracked errors — use `.test errors` to view")
        await ctx.send(embed=embed)

    async def _cmd_help(self, ctx: commands.Context, _: str):
        embed = discord.Embed(
            title="🧪 Testing Framework Help",
            color=discord.Color.teal(),
            description="All commands use the `.test` prefix.",
        )
        help_text = {
            "audit [cog]": "Full project audit or per-cog detail",
            "coverage": "Coverage report per cog with progress bars",
            "list": "List every command grouped by cog",
            "run [cog|cmd]": "Run tests (all, by cog, or by command)",
            "history": "Show commands that have failed at runtime",
            "errors": "Show all tracked runtime errors",
            "error <id>": "Show full details for a specific error",
            "commands": "List all commands",
            "cogs": "List all discovered cogs",
            "stats": "Framework statistics",
            "logs": "Alias for errors",
            "clearlogs": "Clear all error logs",
        }
        for name, desc in help_text.items():
            embed.add_field(name=f"`.test {name}`", value=desc, inline=False)
        await ctx.send(embed=embed)

    # ── Audit ────────────────────────────────────────────────────────────────

    async def _cmd_audit(self, ctx: commands.Context, arg: str):
        if arg:
            await self._audit_cog(ctx, arg)
        else:
            await self._audit_all(ctx)

    async def _audit_all(self, ctx: commands.Context):
        summary = get_project_summary()
        cogs = discover_all()
        coverage = analyze_coverage()

        sorted_cogs = sorted(coverage.items(), key=lambda x: x[1].estimated_overall)
        cog_pcts = [(name, cov.estimated_overall) for name, cov in sorted_cogs]

        embed = build_audit_embed(summary, cog_pcts)
        await ctx.send(embed=embed)

    async def _audit_cog(self, ctx: commands.Context, canonical: str):
        cogs = discover_all()
        coverage = analyze_coverage()

        # Fuzzy find the cog
        matches = [k for k in cogs if canonical.lower() in k.lower()]
        if not matches:
            await ctx.send(f"No cog matching `{canonical}`. Use `.test cogs` to list all.")
            return

        canonical = matches[0]
        info = cogs[canonical]
        cov = coverage.get(canonical)
        embed = build_cog_detail_embed(canonical, info, cov)
        await ctx.send(embed=embed)

    # ── Coverage ─────────────────────────────────────────────────────────────

    async def _cmd_coverage(self, ctx: commands.Context, _: str):
        summary = get_project_summary()
        coverage = analyze_coverage()
        sorted_cogs = sorted(coverage.items(), key=lambda x: x[1].estimated_overall)
        embed = build_coverage_embed(summary, sorted_cogs)
        await ctx.send(embed=embed)

    # ── List ─────────────────────────────────────────────────────────────────

    async def _cmd_list(self, ctx: commands.Context, _: str):
        cogs = discover_all()
        lines = []
        for canonical, info in sorted(cogs.items()):
            all_cmds = info.prefix_commands + info.slash_commands
            if all_cmds:
                lines.append(f"**{info.name}** ({len(all_cmds)}): " + ", ".join(f"`{c}`" for c in all_cmds[:10]))
                if len(all_cmds) > 10:
                    lines[-1] += f" +{len(all_cmds) - 10} more"

        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) > 3900:
                chunks.append(current)
                current = line + "\n"
            else:
                current += line + "\n"
        if current:
            chunks.append(current)

        pages = []
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"📋 All Commands ({sum(len(v.prefix_commands) + len(v.slash_commands) for v in cogs.values())} total)",
                description=chunk[:4096],
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"Page {i + 1}/{len(chunks)}")
            pages.append(embed)

        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            view = PaginatedView(pages, ctx.author.id)
            view.page_indicator.label = f"1/{len(pages)}"
            msg = await ctx.send(embed=pages[0], view=view)
            view.message = msg

    # ── Run Tests ────────────────────────────────────────────────────────────

    async def _cmd_run(self, ctx: commands.Context, arg: str):
        await ctx.send("⏳ Running tests...")
        loop = asyncio.get_event_loop()

        if not arg:
            # Run all tests
            rc, stdout, stderr = await loop.run_in_executor(None, self._run_pytest, None)
        else:
            # Check if it matches a cog or a specific test file
            cogs = discover_all()
            matches = [k for k in cogs if arg.lower() in k.lower()]

            if matches:
                canonical = matches[0]
                test_file = f"testing/tests/test_{canonical}.py"
                rc, stdout, stderr = await loop.run_in_executor(
                    None, self._run_pytest, ["-v", test_file, "--tb=short"]
                )
            else:
                # Try as a specific test name
                rc, stdout, stderr = await loop.run_in_executor(
                    None, self._run_pytest, ["-v", "-k", arg, "--tb=short"]
                )

        embed = discord.Embed(
            title="🧪 Test Results",
            color=discord.Color.green() if rc == 0 else discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Exit Code", value=str(rc), inline=True)

        # Parse pytest summary
        for line in (stdout + stderr).split("\n"):
            if "passed" in line and "failed" in line:
                embed.add_field(name="Summary", value=f"```{line.strip()}```", inline=False)
                break
            if "passed" in line and "=" in line:
                embed.add_field(name="Summary", value=f"```{line.strip()}```", inline=False)

        output = (stdout + stderr)[-1500:]
        if output:
            embed.add_field(name="Details", value=f"```{output[:1500]}```", inline=False)

        await ctx.send(embed=embed)

    # ── History & Errors ─────────────────────────────────────────────────────

    async def _cmd_history(self, ctx: commands.Context, _: str):
        failed = []
        # Check error history
        errors = get_all_errors()
        seen = set()
        for err in errors:
            key = f"{err.cog}/{err.command}"
            if key not in seen:
                seen.add(key)
                failed.append(key)

        if not failed:
            await ctx.send("No failed commands recorded. 🎉")
            return

        embed = discord.Embed(
            title="📜 Failed Command History",
            color=discord.Color.orange(),
            description="\n".join(f"⚠️ `{f}`" for f in failed[-20:]),
        )
        if len(failed) > 20:
            embed.set_footer(text=f"Showing last 20 of {len(failed)}")

        await ctx.send(embed=embed)

    async def _cmd_errors(self, ctx: commands.Context, _: str):
        errors = get_all_errors()
        if not errors:
            await ctx.send("No errors recorded. 🎉")
            return

        # Show last 10 errors in embeds
        pages = []
        for err in errors[-10:]:
            pages.append(build_error_embed(err))

        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            view = PaginatedView(pages, ctx.author.id)
            view.page_indicator.label = f"1/{len(pages)}"
            msg = await ctx.send(embed=pages[0], view=view)
            view.message = msg

    async def _cmd_error_detail(self, ctx: commands.Context, error_id: str):
        error_id = error_id.strip()
        if not error_id:
            await ctx.send("Usage: `.test error <error_id>`")
            return

        record = get_error(error_id)
        if not record:
            await ctx.send(f"No error found with ID `{error_id}`.")
            return

        await ctx.send(embed=build_error_embed(record))

    async def _cmd_clearlogs(self, ctx: commands.Context, _: str):
        clear_errors()
        await ctx.send("✅ All error logs cleared.")

    # ── Commands & Cogs listing ──────────────────────────────────────────────

    async def _cmd_commands(self, ctx: commands.Context, _: str):
        all_cmds = collect_all_commands()
        total = sum(len(cmds) for cmds in all_cmds.values())
        lines = []
        for canonical, cmds in sorted(all_cmds.items()):
            cogs = discover_all()
            info = cogs.get(canonical)
            name = info.name if info else canonical
            cmd_names = [f"`{'/' if c.is_slash else '.'}{c.name}`" for c in cmds]
            lines.append(f"**{name}** ({len(cmds)}): {', '.join(cmd_names[:15])}")

        embed = discord.Embed(
            title=f"📝 All Commands ({total} total)",
            description="\n".join(lines[:30]),
            color=discord.Color.blue(),
        )
        if len(lines) > 30:
            embed.set_footer(text=f"Showing 30 of {len(lines)} cogs — use `.test list` for full list")
        await ctx.send(embed=embed)

    async def _cmd_cogs(self, ctx: commands.Context, _: str):
        cogs = discover_all()
        embed = discord.Embed(
            title="🤖 Discovered Cogs",
            color=discord.Color.teal(),
            description=f"**{len(cogs)} total**",
        )
        lines = []
        for canonical, info in sorted(cogs.items()):
            n_cmds = len(info.prefix_commands) + len(info.slash_commands)
            icon = "🔧" if n_cmds > 0 else "📦"
            lines.append(f"{icon} **{info.name}** — `{canonical}` ({n_cmds} cmds, {info.total_methods} methods)")

        for i in range(0, len(lines), 15):
            chunk = lines[i:i + 15]
            embed.add_field(
                name=f"Cogs ({i + 1}-{min(i + 15, len(lines))})",
                value="\n".join(chunk),
                inline=False,
            )
        await ctx.send(embed=embed)

    # ── Stats ────────────────────────────────────────────────────────────────

    async def _cmd_stats(self, ctx: commands.Context, _: str):
        summary = get_project_summary()
        errors = get_all_errors()
        cogs = discover_all()

        embed = build_stats_embed(summary, errors)

        # Add recent errors
        if errors:
            recent = errors[-5:]
            err_text = "\n".join(
                f"`{e.id}` — {e.cog}/{e.command}: {e.exception[:60]}"
                for e in recent
            )
            embed.add_field(
                name=f"Recent Errors (last {len(recent)})",
                value=err_text[:1024],
                inline=False,
            )

        await ctx.send(embed=embed)

    # ── Error tracking interceptor ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        """Capture command errors for the testing framework."""
        # Ignore CheckFailure and CommandNotFound — these are normal
        if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
            return

        cog_name = ctx.cog.__class__.__name__ if ctx.cog else "unknown"
        cmd_name = ctx.command.name if ctx.command else "unknown"
        start = time.time()

        record = capture_error(
            cog=cog_name,
            command=cmd_name,
            guild=ctx.guild.id if ctx.guild else "DM",
            user=ctx.author.id,
            args=ctx.message.content[:200] if ctx.message else "",
            runtime_ms=(time.time() - start) * 1000,
            exception=error,
        )

        # Flush immediately for critical errors
        if isinstance(error, (commands.CommandInvokeError, commands.ConversionError)):
            flush_errors()


async def setup(bot: commands.Bot):
    await bot.add_cog(TestingCog(bot))
