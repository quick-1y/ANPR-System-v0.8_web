from __future__ import annotations

import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from .logging_manager import get_logger

logger = get_logger(__name__)
_SCHEMA_SQL_PATH = Path(__file__).resolve().parents[2] / "database" / "postgres" / "schema.sql"


class StorageUnavailableError(RuntimeError):
    """БД PostgreSQL временно недоступна."""


class PostgresEventDatabase:
    """PostgreSQL-only хранилище событий с ленивым bootstrap схемы."""

    def __init__(self, dsn: str) -> None:
        self.dsn = str(dsn or "").strip()
        if not self.dsn:
            raise ValueError("postgres_dsn обязателен")
        self._init_lock = threading.Lock()
        self._initialized = False

    @staticmethod
    def _to_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row[0],
            "timestamp": row[1],
            "channel_id": row[2],
            "channel": row[3],
            "plate": row[4],
            "country": row[5],
            "confidence": row[6],
            "source": row[7],
            "frame_path": row[8],
            "plate_path": row[9],
            "direction": row[10],
        }

    def _connect(self):
        import psycopg  # type: ignore

        return psycopg.connect(self.dsn)

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            try:
                query = _SCHEMA_SQL_PATH.read_text(encoding="utf-8")
            except OSError as exc:
                raise StorageUnavailableError(f"Не удалось прочитать SQL-схему {_SCHEMA_SQL_PATH}: {exc}") from exc
            try:
                with self._connect() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(query)
                    conn.commit()
            except Exception as exc:  # noqa: BLE001
                raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
            self._initialized = True

    def insert_event(
        self,
        channel: str,
        plate: str,
        channel_id: Optional[int] = None,
        country: Optional[str] = None,
        confidence: float = 0.0,
        source: str = "",
        timestamp: Optional[str] = None,
        frame_path: Optional[str] = None,
        plate_path: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> int:
        self._ensure_schema()
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        (
                            "INSERT INTO events (timestamp, channel_id, channel, plate, country, confidence, source, frame_path, plate_path, direction) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
                        ),
                        (ts, channel_id, channel, plate, country, confidence, source, frame_path, plate_path, direction),
                    )
                    row = cursor.fetchone()
                conn.commit()
            return int(row[0]) if row else 0
        except StorageUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def fetch_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT id, timestamp, channel_id, channel, plate, country, confidence, source, frame_path, plate_path, direction "
                        "FROM events ORDER BY timestamp DESC LIMIT %s",
                        (limit,),
                    )
                    return [self._to_dict(row) for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def fetch_by_id(self, event_id: int) -> Optional[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT id, timestamp, channel_id, channel, plate, country, confidence, source, frame_path, plate_path, direction FROM events WHERE id = %s",
                        (int(event_id),),
                    )
                    row = cursor.fetchone()
                    return self._to_dict(row) if row else None
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def delete_before(self, cutoff_iso: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM events WHERE timestamp < %s RETURNING id, frame_path, plate_path",
                        (cutoff_iso,),
                    )
                    rows = cursor.fetchall()
                conn.commit()
            return [{"id": row[0], "frame_path": row[1], "plate_path": row[2]} for row in rows]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc


    def fetch_last_plates_by_channel_ids(self, channel_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        self._ensure_schema()
        ids = sorted({int(channel_id) for channel_id in channel_ids if channel_id is not None})
        if not ids:
            return {}
        query = (
            "SELECT DISTINCT ON (channel_id) channel_id, plate, timestamp, country, confidence, direction "
            "FROM events WHERE channel_id = ANY(%s) AND channel_id IS NOT NULL "
            "ORDER BY channel_id, timestamp DESC"
        )
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (ids,))
                    rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
        return {
            int(row[0]): {
                "plate": row[1],
                "timestamp": row[2],
                "country": row[3],
                "confidence": row[4],
                "direction": row[5],
            }
            for row in rows
        }

    def fetch_for_export(self, *, start: Optional[str] = None, end: Optional[str] = None, channel: Optional[str] = None) -> list[dict[str, Any]]:
        self._ensure_schema()
        filters: list[str] = []
        params: list[Any] = []
        if start:
            filters.append("timestamp >= %s")
            params.append(start)
        if end:
            filters.append("timestamp <= %s")
            params.append(end)
        if channel:
            filters.append("channel = %s")
            params.append(channel)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = (
            "SELECT id, timestamp, channel_id, channel, plate, country, confidence, source, frame_path, plate_path, direction "
            f"FROM events {where} ORDER BY timestamp DESC"
        )
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    return [self._to_dict(row) for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc


__all__ = ["PostgresEventDatabase", "StorageUnavailableError"]
