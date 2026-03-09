from __future__ import annotations

from typing import Optional, Protocol


class EventSinkPort(Protocol):
    def insert_event(
        self,
        *,
        channel: str,
        plate: str,
        country: Optional[str],
        confidence: float,
        source: str,
        timestamp: str,
        direction: Optional[str],
    ) -> int: ...
