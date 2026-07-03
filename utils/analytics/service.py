from __future__ import annotations

import asyncio
import logging

from .config import AnalyticsConfig
from .local_provider import LocalDBProvider
from .models import CommandEvent, ErrorRecord
from .posthog_provider import PostHogProvider
from .provider import AnalyticsProvider

logger = logging.getLogger("analytics.service")


class AnalyticsService:
    def __init__(self, config: AnalyticsConfig):
        self.config = config
        self._providers: list[AnalyticsProvider] = []
        self._enabled = True

    async def initialize(self) -> None:
        if not self.config.enabled:
            self._enabled = False
            logger.info("Analytics disabled by configuration")
            return

        self._providers.append(LocalDBProvider(self.config.db_path))

        if self.config.posthog_api_key:
            self._providers.append(
                PostHogProvider(self.config.posthog_api_key, self.config.posthog_host)
            )
        else:
            logger.info("No PostHog API key — PostHog provider skipped")

        for p in self._providers:
            try:
                await p.initialize()
            except Exception:
                logger.exception("Failed to initialize analytics provider %s", type(p).__name__)

        logger.info("Analytics service initialized with %d provider(s)", len(self._providers))

    async def shutdown(self) -> None:
        for p in self._providers:
            try:
                await p.shutdown()
            except Exception:
                logger.exception("Failed to shutdown analytics provider %s", type(p).__name__)
        self._providers.clear()

    async def record_execution(self, event: CommandEvent) -> None:
        if not self._enabled:
            return
        for p in self._providers:
            try:
                await p.capture(event)
            except Exception:
                logger.exception("Provider %s failed to capture event", type(p).__name__)

    async def record_failure(self, event: CommandEvent) -> None:
        if not self._enabled:
            return
        for p in self._providers:
            try:
                await p.capture(event)
                if event.error_type:
                    error_record = ErrorRecord(
                        timestamp=event.timestamp,
                        command_name=event.command_name,
                        cog_name=event.cog_name,
                        exception_type=event.error_type,
                        traceback=event.error_traceback or "",
                        user_id=event.user_id,
                        guild_id=event.guild_id,
                    )
                    await p.record_error(error_record)
            except Exception:
                logger.exception("Provider %s failed to record failure", type(p).__name__)

    async def record_error(self, error: ErrorRecord) -> None:
        if not self._enabled:
            return
        for p in self._providers:
            try:
                await p.record_error(error)
            except Exception:
                logger.exception("Provider %s failed to record error", type(p).__name__)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def disable(self) -> None:
        self._enabled = False
        logger.info("Analytics disabled")

    def enable(self) -> None:
        self._enabled = True
        logger.info("Analytics enabled")
