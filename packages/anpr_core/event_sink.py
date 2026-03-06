from __future__ import annotations

from typing import Optional

from anpr.infrastructure.logging_manager import get_logger
from anpr.infrastructure.storage import EventDatabase, PostgresEventDatabase

logger = get_logger(__name__)


class DualEventSink:
    """PostgreSQL-first sink with optional SQLite compatibility write."""

    def __init__(self, sqlite_db_path: str, dual_write_enabled: bool = False, postgres_dsn: str = "") -> None:
        self._sqlite = EventDatabase(sqlite_db_path)
        self._sqlite_compat_write_enabled = bool(dual_write_enabled)
        self._postgres_dsn = str(postgres_dsn or "").strip()
        self._postgres = None
        if self._postgres_dsn:
            try:
                self._postgres = PostgresEventDatabase(self._postgres_dsn)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PostgreSQL backend недоступен, fallback на SQLite compatibility mode: %s", exc)

        if not self._postgres:
            logger.warning("postgres_dsn не задан/недоступен: используется SQLite compatibility mode (не рекомендуется для production)")

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
    ) -> int:
        if self._postgres:
            event_id = self._postgres.insert_event(
                channel=channel,
                plate=plate,
                country=country,
                confidence=confidence,
                source=source,
                timestamp=timestamp,
                direction=direction,
            )
            if self._sqlite_compat_write_enabled:
                try:
                    self._sqlite.insert_event(
                        channel=channel,
                        plate=plate,
                        country=country,
                        confidence=confidence,
                        source=source,
                        timestamp=timestamp,
                        direction=direction,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("SQLite compatibility write error: %s", exc)
            return int(event_id)

        return self._sqlite.insert_event(
            channel=channel,
            plate=plate,
            country=country,
            confidence=confidence,
            source=source,
            timestamp=timestamp,
            direction=direction,
        )
