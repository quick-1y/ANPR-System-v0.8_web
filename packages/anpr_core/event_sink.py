from __future__ import annotations

from typing import Optional

from anpr.infrastructure.storage import PostgresEventDatabase


class EventSink:
    """PostgreSQL-only sink для записи событий."""

    def __init__(self, postgres_dsn: str) -> None:
        self._postgres = PostgresEventDatabase(postgres_dsn)

    def insert_event(
        self,
        *,
        channel: str,
        plate: str,
        country: Optional[str],
        channel_id: Optional[int],
        confidence: float,
        source: str,
        timestamp: str,
        frame_path: Optional[str],
        plate_path: Optional[str],
        direction: Optional[str],
    ) -> int:
        return self._postgres.insert_event(
            channel=channel,
            plate=plate,
            country=country,
            channel_id=channel_id,
            confidence=confidence,
            source=source,
            timestamp=timestamp,
            frame_path=frame_path,
            plate_path=plate_path,
            direction=direction,
        )
