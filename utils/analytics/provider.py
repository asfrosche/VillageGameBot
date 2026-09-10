from __future__ import annotations

from abc import ABC, abstractmethod

from .models import CommandEvent, ErrorRecord


class AnalyticsProvider(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        ...

    @abstractmethod
    async def capture(self, event: CommandEvent) -> None:
        ...

    @abstractmethod
    async def record_error(self, error: ErrorRecord) -> None:
        ...
