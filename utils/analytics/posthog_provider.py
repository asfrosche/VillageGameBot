from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from .models import CommandEvent, ErrorRecord
from .provider import AnalyticsProvider

logger = logging.getLogger("analytics.posthog")


class PostHogProvider(AnalyticsProvider):
    def __init__(self, api_key: str, host: str = "https://eu.posthog.com"):
        self.api_key = api_key
        self.host = host
        self._client = None
        self._executor = ThreadPoolExecutor(max_workers=1)

    async def initialize(self) -> None:
        try:
            import posthog
            posthog.api_key = self.api_key
            posthog.host = self.host
            self._client = posthog
            logger.info("PostHog provider initialized (host=%s)", self.host)
        except ImportError:
            logger.warning("posthog package not installed — PostHog provider disabled")
            self._client = None

    async def shutdown(self) -> None:
        if self._client:
            self._client.shutdown()
        self._executor.shutdown(wait=False)

    async def capture(self, event: CommandEvent) -> None:
        if self._client is None:
            return
        try:
            distinct_id = event.user_id or "unknown"
            props = event.to_posthog()
            self._executor.submit(self._client.capture, distinct_id, "command_executed" if event.success else "command_failed", props)
        except Exception:
            logger.exception("Failed to send event to PostHog")

    async def record_error(self, error: ErrorRecord) -> None:
        if self._client is None:
            return
        try:
            distinct_id = error.user_id or "unknown"
            self._executor.submit(
                self._client.capture,
                distinct_id,
                "command_error",
                {
                    "command_name": error.command_name,
                    "cog_name": error.cog_name,
                    "exception_type": error.exception_type,
                    "user_id": error.user_id,
                    "guild_id": error.guild_id,
                },
            )
        except Exception:
            logger.exception("Failed to send error to PostHog")
