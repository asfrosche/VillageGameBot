from __future__ import annotations

import os


class DashboardConfig:
    def __init__(
        self,
        enabled: bool = True,
        host: str = "0.0.0.0",
        port: int = 8712,
        password: str = "",
        analytics_db_path: str = "./data/analytics.db",
        tunnel_enabled: bool = False,
    ):
        self.enabled = enabled
        self.host = host
        self.port = port
        self.password = password
        self.analytics_db_path = analytics_db_path
        self.tunnel_enabled = tunnel_enabled

    @classmethod
    def from_env(cls) -> DashboardConfig:
        return cls(
            enabled=os.getenv("ANALYTICS_DASHBOARD_ENABLED", "true").lower() == "true",
            host=os.getenv("ANALYTICS_DASHBOARD_HOST", "0.0.0.0"),
            port=int(os.getenv("ANALYTICS_DASHBOARD_PORT", "8712")),
            password=os.getenv("ANALYTICS_DASHBOARD_PASSWORD", ""),
            analytics_db_path=os.getenv("ANALYTICS_DB_PATH", "./data/analytics.db"),
            tunnel_enabled=os.getenv("ANALYTICS_DASHBOARD_TUNNEL", "false").lower() == "true",
        )
