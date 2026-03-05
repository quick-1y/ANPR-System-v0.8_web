#!/usr/bin/env python3
# /anpr/infrastructure/list_database.py
from __future__ import annotations

import csv
import os
import sqlite3
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional

from anpr.infrastructure.logging_manager import get_logger

logger = get_logger(__name__)

LIST_TYPES = OrderedDict([
    ("white", "Белый список"),
    ("black", "Черный список"),
])


def normalize_plate(value: str) -> str:
    return "".join(str(value or "").upper().split())


class ListDatabase:
    """SQLite-хранилище списков номеров и их записей."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plate_lists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plate_list_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id INTEGER NOT NULL,
                    plate TEXT NOT NULL,
                    plate_normalized TEXT NOT NULL,
                    comment TEXT,
                    FOREIGN KEY(list_id) REFERENCES plate_lists(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plate_lists_type ON plate_lists(type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plate_entries_plate ON plate_list_entries(plate_normalized)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plate_entries_list ON plate_list_entries(list_id)"
            )
            conn.commit()

    def list_lists(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT l.id, l.name, l.type, COUNT(e.id) AS entries_count
                FROM plate_lists l
                LEFT JOIN plate_list_entries e ON e.list_id = l.id
                GROUP BY l.id
                ORDER BY l.name
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_list(self, list_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id, name, type FROM plate_lists WHERE id = ?",
                (int(list_id),),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def create_list(self, name: str, list_type: str) -> int:
        list_type = list_type if list_type in LIST_TYPES else "white"
        name = (name or "").strip() or "Новый список"
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO plate_lists (name, type) VALUES (?, ?)",
                (name, list_type),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_list(self, list_id: int, name: str, list_type: str) -> None:
        list_type = list_type if list_type in LIST_TYPES else "white"
        name = (name or "").strip() or "Новый список"
        with self._connect() as conn:
            conn.execute(
                "UPDATE plate_lists SET name = ?, type = ? WHERE id = ?",
                (name, list_type, int(list_id)),
            )
            conn.commit()

    def delete_list(self, list_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM plate_lists WHERE id = ?", (int(list_id),))
            conn.commit()

    def list_entries(self, list_id: int) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, plate, comment
                FROM plate_list_entries
                WHERE list_id = ?
                ORDER BY plate
                """,
                (int(list_id),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def add_entry(self, list_id: int, plate: str, comment: str = "") -> Optional[int]:
        normalized = normalize_plate(plate)
        if not normalized:
            return None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id FROM plate_list_entries
                WHERE list_id = ? AND plate_normalized = ?
                """,
                (int(list_id), normalized),
            )
            if cursor.fetchone():
                return None
            cursor = conn.execute(
                """
                INSERT INTO plate_list_entries (list_id, plate, plate_normalized, comment)
                VALUES (?, ?, ?, ?)
                """,
                (int(list_id), plate.strip(), normalized, (comment or "").strip()),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_entry(self, entry_id: int, plate: str, comment: str = "") -> None:
        normalized = normalize_plate(plate)
        if not normalized:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE plate_list_entries
                SET plate = ?, plate_normalized = ?, comment = ?
                WHERE id = ?
                """,
                (plate.strip(), normalized, (comment or "").strip(), int(entry_id)),
            )
            conn.commit()

    def delete_entry(self, entry_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM plate_list_entries WHERE id = ?", (int(entry_id),))
            conn.commit()

    def plate_in_list_type(self, plate: str, list_type: str) -> bool:
        normalized = normalize_plate(plate)
        if not normalized:
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT 1
                FROM plate_list_entries e
                JOIN plate_lists l ON l.id = e.list_id
                WHERE e.plate_normalized = ? AND l.type = ?
                LIMIT 1
                """,
                (normalized, list_type),
            )
            return cursor.fetchone() is not None

    def plate_in_lists(self, plate: str, list_ids: Iterable[int]) -> bool:
        normalized = normalize_plate(plate)
        ids = [int(list_id) for list_id in list_ids if int(list_id) > 0]
        if not normalized or not ids:
            return False
        placeholders = ",".join("?" for _ in ids)
        query = (
            "SELECT 1 FROM plate_list_entries "
            f"WHERE plate_normalized = ? AND list_id IN ({placeholders}) LIMIT 1"
        )
        with self._connect() as conn:
            cursor = conn.execute(query, [normalized, *ids])
            return cursor.fetchone() is not None

    def export_lists(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow(["list_name", "list_type", "plate", "comment"])
            for lst in self.list_lists():
                list_name = lst.get("name") or ""
                list_type = lst.get("type") or "white"
                entries = self.list_entries(int(lst["id"]))
                if not entries:
                    writer.writerow([list_name, list_type, "", ""])
                    continue
                for entry in entries:
                    writer.writerow(
                        [
                            list_name,
                            list_type,
                            entry.get("plate") or "",
                            entry.get("comment") or "",
                        ]
                    )

    def import_lists(self, path: str) -> Dict[str, int]:
        summary = {"lists_added": 0, "entries_added": 0}
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file, delimiter=";")
            for row in reader:
                name = str(row.get("list_name") or "Новый список").strip()
                list_type = str(row.get("list_type") or "white").strip()
                plate = str(row.get("plate") or "").strip()
                comment = str(row.get("comment") or "").strip()
                existing_id = self._find_list_id(name, list_type)
                list_id = existing_id or self.create_list(name, list_type)
                if existing_id is None:
                    summary["lists_added"] += 1
                if plate:
                    entry_id = self.add_entry(list_id, plate, comment)
                    if entry_id:
                        summary["entries_added"] += 1
        return summary

    def _find_list_id(self, name: str, list_type: str) -> Optional[int]:
        list_type = list_type if list_type in LIST_TYPES else "white"
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id FROM plate_lists WHERE name = ? AND type = ?",
                (name.strip(), list_type),
            )
            row = cursor.fetchone()
            return int(row["id"]) if row else None


__all__ = ["ListDatabase", "LIST_TYPES", "normalize_plate"]
