from __future__ import annotations

from typing import Any, Optional

from anpr.infrastructure.logging_manager import get_logger
from anpr.infrastructure.storage import EventDatabase

logger = get_logger(__name__)


class DualEventSink:
    """Пишет события в SQLite и опционально в PostgreSQL (dual-write подготовка)."""

    def __init__(self, sqlite_db_path: str, dual_write_enabled: bool = False, postgres_dsn: str = "") -> None:
        self._sqlite = EventDatabase(sqlite_db_path)
        self._dual_write_enabled = bool(dual_write_enabled)
        self._postgres_dsn = str(postgres_dsn or "").strip()

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
        sqlite_id = self._sqlite.insert_event(
            channel=channel,
            plate=plate,
            country=country,
            confidence=confidence,
            source=source,
            timestamp=timestamp,
            direction=direction,
        )

        if self._dual_write_enabled and self._postgres_dsn:
            self._write_postgres(
                channel=channel,
                plate=plate,
                country=country,
                confidence=confidence,
                source=source,
                timestamp=timestamp,
                direction=direction,
            )

        return sqlite_id

    def _write_postgres(
        self,
        *,
        channel: str,
        plate: str,
        country: Optional[str],
        confidence: float,
        source: str,
        timestamp: str,
        direction: Optional[str],
    ) -> None:
        try:
            import psycopg  # type: ignore
        except Exception:
            logger.warning("Dual-write включён, но psycopg недоступен. Запись в PostgreSQL пропущена.")
            return

        query = (
            "INSERT INTO events (timestamp, channel, plate, country, confidence, source, direction) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)"
        )
        try:
            with psycopg.connect(self._postgres_dsn) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (timestamp, channel, plate, country, confidence, source, direction))
                conn.commit()
        except Exception as exc:
            logger.warning("Ошибка dual-write в PostgreSQL: %s", exc)
