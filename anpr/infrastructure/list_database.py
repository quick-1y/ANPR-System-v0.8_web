from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Dict, Iterable, Optional

from anpr.infrastructure.storage import StorageUnavailableError

LIST_TYPES = OrderedDict([
    ("white", "Белый список"),
    ("black", "Черный список"),
])


def normalize_plate(value: str) -> str:
    return "".join(str(value or "").upper().split())


class ListDatabase:
    """PostgreSQL-only хранилище списков номеров."""

    def __init__(self, dsn: str) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise ValueError("postgres_dsn обязателен")
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self):
        import psycopg  # type: ignore

        return psycopg.connect(self._dsn)

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            query = """
            CREATE TABLE IF NOT EXISTS plate_lists (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plate_list_entries (
                id BIGSERIAL PRIMARY KEY,
                list_id BIGINT NOT NULL REFERENCES plate_lists(id) ON DELETE CASCADE,
                plate TEXT NOT NULL,
                plate_normalized TEXT NOT NULL,
                comment TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_plate_lists_type ON plate_lists(type);
            CREATE INDEX IF NOT EXISTS idx_plate_entries_plate ON plate_list_entries(plate_normalized);
            CREATE INDEX IF NOT EXISTS idx_plate_entries_list ON plate_list_entries(list_id);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_plate_entries_list_plate ON plate_list_entries(list_id, plate_normalized);
            """
            try:
                with self._connect() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(query)
                    conn.commit()
            except Exception as exc:  # noqa: BLE001
                raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
            self._initialized = True

    def list_lists(self) -> list[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT l.id, l.name, l.type, COUNT(e.id) AS entries_count
                    FROM plate_lists l
                    LEFT JOIN plate_list_entries e ON e.list_id = l.id
                    GROUP BY l.id
                    ORDER BY l.name
                    """
                )
                return [
                    {"id": row[0], "name": row[1], "type": row[2], "entries_count": row[3]}
                    for row in cursor.fetchall()
                ]


    def create_list(self, name: str, list_type: str) -> int:
        self._ensure_schema()
        list_type = list_type if list_type in LIST_TYPES else "white"
        name = (name or "").strip() or "Новый список"
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO plate_lists (name, type) VALUES (%s, %s) RETURNING id", (name, list_type))
                row = cursor.fetchone()
            conn.commit()
        return int(row[0]) if row else 0



    def list_entries(self, list_id: int) -> list[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, plate, comment FROM plate_list_entries WHERE list_id = %s ORDER BY plate",
                    (int(list_id),),
                )
                return [{"id": row[0], "plate": row[1], "comment": row[2]} for row in cursor.fetchall()]

    def add_entry(self, list_id: int, plate: str, comment: str = "") -> Optional[int]:
        self._ensure_schema()
        normalized = normalize_plate(plate)
        if not normalized:
            return None
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO plate_list_entries (list_id, plate, plate_normalized, comment)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (list_id, plate_normalized) DO NOTHING
                    RETURNING id
                    """,
                    (int(list_id), plate.strip(), normalized, (comment or "").strip()),
                )
                row = cursor.fetchone()
            conn.commit()
        return int(row[0]) if row else None


    def plate_in_list_type(self, plate: str, list_type: str) -> bool:
        self._ensure_schema()
        normalized = normalize_plate(plate)
        if not normalized:
            return False
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM plate_list_entries e
                    JOIN plate_lists l ON l.id = e.list_id
                    WHERE e.plate_normalized = %s AND l.type = %s
                    LIMIT 1
                    """,
                    (normalized, list_type),
                )
                return cursor.fetchone() is not None

    def plate_in_lists(self, plate: str, list_ids: Iterable[int]) -> bool:
        self._ensure_schema()
        normalized = normalize_plate(plate)
        ids = [int(list_id) for list_id in list_ids if int(list_id) > 0]
        if not normalized or not ids:
            return False
        placeholders = ",".join(["%s"] * len(ids))
        query = f"SELECT 1 FROM plate_list_entries WHERE plate_normalized = %s AND list_id IN ({placeholders}) LIMIT 1"
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, [normalized, *ids])
                return cursor.fetchone() is not None



__all__ = ["ListDatabase", "LIST_TYPES", "normalize_plate"]
