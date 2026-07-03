from __future__ import annotations

import os
from pathlib import Path

from utils.analytics.db import AnalyticsDB

_db_instance: AnalyticsDB | None = None


def get_db_path() -> str:
    return os.getenv("ANALYTICS_DB_PATH", "./data/analytics.db")


def get_db():
    global _db_instance
    if _db_instance is None:
        p = get_db_path()
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        _db_instance = AnalyticsDB(p)
        _db_instance.initialize()
    return _db_instance
