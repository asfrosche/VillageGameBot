from __future__ import annotations

import os


class AnalyticsConfig:
    def __init__(
        self,
        enabled: bool = True,
        posthog_api_key: str | None = None,
        posthog_host: str = "https://eu.posthog.com",
        db_path: str = "./data/analytics.db",
        dashboard_enabled: bool = True,
        dashboard_host: str = "0.0.0.0",
        dashboard_port: int = 8712,
        dashboard_url: str = "",
        dashboard_password: str = "",
        dashboard_tunnel_enabled: bool = False,
        bot_version: str = "",
        git_commit: str = "",
    ):
        self.enabled = enabled
        self.posthog_api_key = posthog_api_key
        self.posthog_host = posthog_host
        self.db_path = db_path
        self.dashboard_enabled = dashboard_enabled
        self.dashboard_host = dashboard_host
        self.dashboard_port = dashboard_port
        self.dashboard_url = dashboard_url
        self.dashboard_password = dashboard_password
        self.dashboard_tunnel_enabled = dashboard_tunnel_enabled
        self.bot_version = bot_version
        self.git_commit = git_commit

    @classmethod
    def from_env(cls) -> AnalyticsConfig:
        import subprocess
        git_commit = ""
        try:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
            ).strip()
        except Exception:
            pass
        return cls(
            enabled=os.getenv("ANALYTICS_ENABLED", "true").lower() == "true",
            posthog_api_key=os.getenv("POSTHOG_API_KEY"),
            posthog_host=os.getenv("POSTHOG_HOST", "https://eu.posthog.com"),
            db_path=os.getenv("ANALYTICS_DB_PATH", "./data/analytics.db"),
            dashboard_enabled=os.getenv("ANALYTICS_DASHBOARD_ENABLED", "true").lower() == "true",
            dashboard_host=os.getenv("ANALYTICS_DASHBOARD_HOST", "0.0.0.0"),
            dashboard_port=int(os.getenv("ANALYTICS_DASHBOARD_PORT", "8712")),
            dashboard_url=os.getenv("ANALYTICS_DASHBOARD_URL", ""),
            dashboard_password=os.getenv("ANALYTICS_DASHBOARD_PASSWORD", ""),
            dashboard_tunnel_enabled=os.getenv("ANALYTICS_DASHBOARD_TUNNEL", "false").lower() == "true",
            bot_version=os.getenv("BOT_VERSION", ""),
            git_commit=git_commit,
        )
