"""Tests for analytics configuration."""

import os

from utils.analytics.config import AnalyticsConfig


class TestAnalyticsConfig:
    def test_defaults(self):
        cfg = AnalyticsConfig()
        assert cfg.enabled is True
        assert cfg.posthog_api_key is None
        assert cfg.posthog_host == "https://eu.posthog.com"
        assert cfg.db_path == "./data/analytics.db"
        assert cfg.dashboard_enabled is True
        assert cfg.dashboard_host == "0.0.0.0"
        assert cfg.dashboard_port == 8712
        assert cfg.dashboard_url == ""
        assert cfg.dashboard_password == ""
        assert cfg.bot_version == ""
        assert cfg.git_commit == ""

    def test_disabled(self):
        cfg = AnalyticsConfig(enabled=False)
        assert cfg.enabled is False

    def test_custom_values(self):
        cfg = AnalyticsConfig(
            enabled=False,
            posthog_api_key="phc_key",
            posthog_host="https://app.posthog.com",
            db_path="/tmp/test.db",
            dashboard_enabled=False,
            dashboard_host="0.0.0.0",
            dashboard_port=9999,
            dashboard_url="https://dash.example.com",
            dashboard_password="secret",
            bot_version="1.2.3",
        )
        assert cfg.enabled is False
        assert cfg.posthog_api_key == "phc_key"
        assert cfg.posthog_host == "https://app.posthog.com"
        assert cfg.db_path == "/tmp/test.db"
        assert cfg.dashboard_enabled is False
        assert cfg.dashboard_host == "0.0.0.0"
        assert cfg.dashboard_port == 9999
        assert cfg.dashboard_url == "https://dash.example.com"
        assert cfg.dashboard_password == "secret"
        assert cfg.bot_version == "1.2.3"

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("ANALYTICS_ENABLED", "false")
        monkeypatch.setenv("POSTHOG_API_KEY", "phc_test")
        monkeypatch.setenv("POSTHOG_HOST", "https://custom.example.com")
        monkeypatch.setenv("ANALYTICS_DB_PATH", "/custom/path.db")
        monkeypatch.setenv("ANALYTICS_DASHBOARD_ENABLED", "false")
        monkeypatch.setenv("ANALYTICS_DASHBOARD_HOST", "0.0.0.0")
        monkeypatch.setenv("ANALYTICS_DASHBOARD_PORT", "9000")
        monkeypatch.setenv("ANALYTICS_DASHBOARD_URL", "https://dash.example.com")
        monkeypatch.setenv("ANALYTICS_DASHBOARD_PASSWORD", "hunter2")
        monkeypatch.setenv("BOT_VERSION", "2.0.0")

        cfg = AnalyticsConfig.from_env()
        assert cfg.enabled is False
        assert cfg.posthog_api_key == "phc_test"
        assert cfg.posthog_host == "https://custom.example.com"
        assert cfg.db_path == "/custom/path.db"
        assert cfg.dashboard_enabled is False
        assert cfg.dashboard_host == "0.0.0.0"
        assert cfg.dashboard_port == 9000
        assert cfg.dashboard_url == "https://dash.example.com"
        assert cfg.dashboard_password == "hunter2"
        assert cfg.bot_version == "2.0.0"

    def test_from_env_defaults(self, monkeypatch):
        monkeypatch.delenv("ANALYTICS_ENABLED", raising=False)
        monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
        monkeypatch.delenv("ANALYTICS_DB_PATH", raising=False)

        cfg = AnalyticsConfig.from_env()
        assert cfg.enabled is True
        assert cfg.posthog_api_key is None
        assert cfg.db_path == "./data/analytics.db"
