from __future__ import annotations

import logging

from .db import AnalyticsDB
from .models import CommandEvent, ErrorRecord
from .provider import AnalyticsProvider

logger = logging.getLogger("analytics.local")


class LocalDBProvider(AnalyticsProvider):
    def __init__(self, db_path: str):
        self.db = AnalyticsDB(db_path)

    async def initialize(self) -> None:
        self.db.initialize()
        logger.info("Local analytics DB initialized at %s", self.db.db_path)

    async def shutdown(self) -> None:
        conn = self.db._get_conn()
        conn.close()
        logger.info("Local analytics DB closed")

    async def capture(self, event: CommandEvent) -> None:
        try:
            self.db.upsert_command_stats(event)
            self.db.upsert_daily_usage(event)
        except Exception:
            logger.exception("Failed to update local analytics DB")

    async def record_error(self, error: ErrorRecord) -> None:
        try:
            self.db.insert_error(error)
        except Exception:
            logger.exception("Failed to insert error into local analytics DB")
