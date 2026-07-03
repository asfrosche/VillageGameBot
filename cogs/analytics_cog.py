from __future__ import annotations

import socket
import threading
from datetime import datetime

import discord
from discord.ext import commands

from utils.analytics import get_analytics_service
from utils.analytics.db import AnalyticsDB


class AnalyticsCog(commands.Cog):
    """Internal analytics commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._dashboard_timer: threading.Timer | None = None

    def _ensure_dashboard(self) -> None:
        svc = get_analytics_service()
        if not svc or not svc.config.dashboard_enabled:
            return
        from analytics_dashboard import main as dash
        if dash._thread is None or not dash._thread.is_alive():
            from analytics_dashboard.config import DashboardConfig
            cfg = DashboardConfig(
                enabled=True,
                host=svc.config.dashboard_host,
                port=svc.config.dashboard_port,
                password=svc.config.dashboard_password,
                analytics_db_path=svc.config.db_path,
            )
            dash.start_dashboard(cfg)
        else:
            dash.start_dashboard()

    @staticmethod
    def _reachable_url() -> str:
        svc = get_analytics_service()
        if svc and svc.config.dashboard_url:
            return svc.config.dashboard_url
        port = svc.config.dashboard_port if svc else 8712
        try:
            ip = socket.gethostbyname(socket.gethostname())
            if ip.startswith("127."):
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.1)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
        except Exception:
            ip = "<server-ip>"
        return f"http://{ip}:{port}"

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

    @commands.command(name="analytics", aliases=["astats"])
    async def analytics(self, ctx: commands.Context):
        """Show analytics summary with key metrics."""
        svc = get_analytics_service()
        if not svc or not svc.enabled:
            await ctx.send("Analytics is disabled.")
            return

        db = self._db
        if db is None:
            await ctx.send("Analytics database not available.")
            return

        ov = db.get_overview()
        cmds_data = db.get_commands(sort="total_execs", order="desc", per_page=5)
        slow = db.get_slowest_commands(limit=5)
        errors_data = db.get_error_summary()
        cogs_data = db.get_cog_stats()

        embed = discord.Embed(
            title="Analytics Summary",
            color=0x7C5CFC,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Total Executions", value=str(ov["total_commands"]), inline=True)
        embed.add_field(name="Active Commands", value=str(ov["active_commands"]), inline=True)
        embed.add_field(name="Avg Time", value=f'{ov["avg_time_ms"]}ms', inline=True)
        embed.add_field(name="Today", value=str(ov["commands_today"]), inline=True)
        embed.add_field(name="This Week", value=str(ov["commands_this_week"]), inline=True)
        embed.add_field(name="Error Rate", value=f'{ov["error_rate"]}%', inline=True)

        top = "\n".join(
            f"`{c['command_name']}` — {c['total_execs']}x ({c['avg_time_ms']}ms)"
            for c in cmds_data["items"][:5]
        )
        if top:
            embed.add_field(name="Most Used", value=top, inline=False)

        slowest = "\n".join(
            f"`{c['command_name']}` — {c['avg_time_ms']}ms ({c['total_execs']}x)"
            for c in slow[:5]
        )
        if slowest:
            embed.add_field(name="Slowest", value=slowest, inline=False)

        if errors_data["total_errors"] > 0:
            err_summary = "\n".join(
                f"`{e['type']}` — {e['count']}x"
                for e in errors_data["by_type"][:3]
            )
            embed.add_field(name="Top Errors", value=err_summary, inline=False)

        cog_summary = "\n".join(
            f"`{c['cog_name']}` — {c['total_execs']}x ({c['pct']}%)"
            for c in cogs_data[:5]
        )
        if cog_summary:
            embed.add_field(name="Top Cogs", value=cog_summary, inline=False)

        embed.add_field(name="Dashboard", value=self._reachable_url(), inline=False)
        embed.set_footer(text="Dashboard auto-shuts down after 10 minutes")

        await ctx.send(embed=embed)

        self._ensure_dashboard()


async def setup(bot: commands.Bot):
    await bot.add_cog(AnalyticsCog(bot))
