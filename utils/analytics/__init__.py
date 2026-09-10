from .config import AnalyticsConfig
from .service import AnalyticsService


_service: AnalyticsService | None = None


def get_analytics_service() -> AnalyticsService | None:
    return _service


def init_analytics(config: AnalyticsConfig | None = None) -> AnalyticsService | None:
    global _service
    cfg = config or AnalyticsConfig.from_env()
    if not cfg.enabled:
        return None
    _service = AnalyticsService(cfg)
    return _service
