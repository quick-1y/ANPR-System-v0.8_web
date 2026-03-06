from __future__ import annotations

import csv
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zipfile import ZIP_DEFLATED, ZipFile

from anpr.infrastructure.logging_manager import get_logger
from anpr.infrastructure.storage import PostgresEventDatabase

logger = get_logger(__name__)


@dataclass
class RetentionPolicy:
    auto_cleanup_enabled: bool = True
    cleanup_interval_minutes: int = 30
    events_retention_days: int = 30
    media_retention_days: int = 14
    max_screenshots_mb: int = 4096
    export_dir: str = "data/exports"

    @classmethod
    def from_storage(cls, storage: Dict[str, Any]) -> "RetentionPolicy":
        return cls(
            auto_cleanup_enabled=bool(storage.get("auto_cleanup_enabled", True)),
            cleanup_interval_minutes=max(1, int(storage.get("cleanup_interval_minutes", 30))),
            events_retention_days=max(1, int(storage.get("events_retention_days", 30))),
            media_retention_days=max(1, int(storage.get("media_retention_days", 14))),
            max_screenshots_mb=max(256, int(storage.get("max_screenshots_mb", 4096))),
            export_dir=str(storage.get("export_dir", "data/exports")),
        )

    def to_storage(self) -> Dict[str, Any]:
        return {
            "auto_cleanup_enabled": bool(self.auto_cleanup_enabled),
            "cleanup_interval_minutes": int(self.cleanup_interval_minutes),
            "events_retention_days": int(self.events_retention_days),
            "media_retention_days": int(self.media_retention_days),
            "max_screenshots_mb": int(self.max_screenshots_mb),
            "export_dir": str(self.export_dir),
        }


class DataLifecycleService:
    def __init__(self, db_path: str, screenshots_dir: str, policy: RetentionPolicy, postgres_dsn: str = "") -> None:
        self.db_path = db_path
        self.screenshots_dir = Path(screenshots_dir)
        self.policy = policy
        self.postgres_dsn = str(postgres_dsn or "").strip()
        self.pg_events = None
        if self.postgres_dsn:
            try:
                self.pg_events = PostgresEventDatabase(self.postgres_dsn)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PostgreSQL lifecycle backend недоступен, fallback на SQLite: %s", exc)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        Path(self.policy.export_dir).mkdir(parents=True, exist_ok=True)

    def update_policy(self, policy: RetentionPolicy) -> None:
        self.policy = policy
        Path(self.policy.export_dir).mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _safe_unlink(path: Optional[str]) -> bool:
        if not path:
            return False
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def cleanup_old_events(self) -> Dict[str, int]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.policy.events_retention_days)
        cutoff_iso = cutoff.isoformat()

        deleted_files = 0
        if self.pg_events:
            rows = self.pg_events.delete_before(cutoff_iso)
            for row in rows:
                deleted_files += int(self._safe_unlink(row.get("frame_path")))
                deleted_files += int(self._safe_unlink(row.get("plate_path")))
            return {"deleted_events": len(rows), "deleted_media_files": deleted_files}

        cutoff_sqlite = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, frame_path, plate_path FROM events WHERE datetime(timestamp) < datetime(?)",
                (cutoff_sqlite,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            for row in rows:
                deleted_files += int(self._safe_unlink(row["frame_path"]))
                deleted_files += int(self._safe_unlink(row["plate_path"]))
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids)
                conn.commit()
        return {"deleted_events": len(ids), "deleted_media_files": deleted_files}

    def cleanup_old_media(self) -> Dict[str, int]:
        cutoff = time.time() - self.policy.media_retention_days * 86400
        deleted = 0
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            for file_path in self.screenshots_dir.rglob(ext):
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                        deleted += 1
                except OSError:
                    continue
        return {"deleted_orphan_media": deleted}

    def enforce_storage_limit(self) -> Dict[str, int]:
        max_bytes = self.policy.max_screenshots_mb * 1024 * 1024
        files: list[tuple[float, Path, int]] = []
        total = 0
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            for file_path in self.screenshots_dir.rglob(ext):
                try:
                    stat = file_path.stat()
                except OSError:
                    continue
                total += stat.st_size
                files.append((stat.st_mtime, file_path, stat.st_size))

        if total <= max_bytes:
            return {"deleted_for_limit": 0}

        files.sort(key=lambda item: item[0])
        deleted = 0
        for _, path, size in files:
            if total <= max_bytes:
                break
            try:
                path.unlink()
                total -= size
                deleted += 1
            except OSError:
                continue
        return {"deleted_for_limit": deleted}

    def run_retention_cycle(self) -> Dict[str, int]:
        result = {}
        result.update(self.cleanup_old_events())
        result.update(self.cleanup_old_media())
        result.update(self.enforce_storage_limit())
        return result

    def export_events_csv(self, *, start: Optional[str] = None, end: Optional[str] = None, channel: Optional[str] = None) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        export_path = Path(self.policy.export_dir) / f"events_{ts}.csv"

        if self.pg_events:
            rows = self.pg_events.fetch_for_export(start=start, end=end, channel=channel)
            fieldnames = ["id", "timestamp", "channel", "plate", "country", "confidence", "source", "frame_path", "plate_path", "direction"]
            with export_path.open("w", newline="", encoding="utf-8") as file_obj:
                writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            return str(export_path)

        query = "SELECT * FROM events"
        filters = []
        params: list[str] = []
        if start:
            filters.append("datetime(timestamp) >= datetime(?)")
            params.append(start)
        if end:
            filters.append("datetime(timestamp) <= datetime(?)")
            params.append(end)
        if channel:
            filters.append("channel = ?")
            params.append(channel)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY datetime(timestamp) DESC"

        with self._connect() as conn, export_path.open("w", newline="", encoding="utf-8") as file_obj:
            rows = conn.execute(query, params).fetchall()
            if not rows:
                file_obj.write("id,timestamp,channel,plate,country,confidence,source,frame_path,plate_path,direction\n")
                return str(export_path)
            writer = csv.DictWriter(file_obj, fieldnames=rows[0].keys())
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))
        return str(export_path)

    def export_events_bundle(self, *, start: Optional[str] = None, end: Optional[str] = None, channel: Optional[str] = None, include_media: bool = True) -> str:
        csv_path = Path(self.export_events_csv(start=start, end=end, channel=channel))
        bundle_path = csv_path.with_suffix(".zip")

        media_paths: set[Path] = set()
        if include_media:
            if self.pg_events:
                for row in self.pg_events.fetch_for_export(start=start, end=end, channel=channel):
                    for key in ("frame_path", "plate_path"):
                        raw = row.get(key)
                        if raw:
                            media_paths.add(Path(str(raw)))
            else:
                with self._connect() as conn:
                    rows = conn.execute("SELECT frame_path, plate_path FROM events").fetchall()
                    for row in rows:
                        for key in ("frame_path", "plate_path"):
                            raw = row[key]
                            if raw:
                                media_paths.add(Path(str(raw)))

        with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
            archive.write(csv_path, arcname=csv_path.name)
            if include_media:
                for media_path in sorted(media_paths):
                    if not media_path.exists() or not media_path.is_file():
                        continue
                    try:
                        archive.write(media_path, arcname=f"media/{media_path.name}")
                    except OSError:
                        continue
        try:
            csv_path.unlink()
        except OSError:
            pass
        return str(bundle_path)

    @staticmethod
    def rotate_export_dir(export_dir: str, max_files: int = 200) -> Dict[str, int]:
        base = Path(export_dir)
        if not base.exists():
            return {"deleted_exports": 0}
        files = [item for item in base.iterdir() if item.is_file()]
        if len(files) <= max_files:
            return {"deleted_exports": 0}

        files.sort(key=lambda item: item.stat().st_mtime)
        to_delete = files[: len(files) - max_files]
        deleted = 0
        for file_path in to_delete:
            try:
                file_path.unlink()
                deleted += 1
            except OSError:
                continue
        return {"deleted_exports": deleted}


__all__ = ["RetentionPolicy", "DataLifecycleService"]
