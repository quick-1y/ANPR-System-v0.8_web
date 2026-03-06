from __future__ import annotations

import csv
import os
import sqlite3
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional


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
    """Эксплуатационный data layer: retention, rotation и export."""

    def __init__(self, db_path: str, screenshots_dir: str, policy: RetentionPolicy) -> None:
        self.db_path = db_path
        self.screenshots_dir = Path(screenshots_dir)
        self.policy = policy
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
    def _safe_delete(path: Optional[str]) -> bool:
        if not path:
            return False
        try:
            candidate = Path(path)
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
                return True
        except Exception:
            return False
        return False

    def cleanup_old_events(self) -> Dict[str, int]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.policy.events_retention_days)
        cutoff_iso = cutoff.isoformat()
        deleted_files = 0

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, frame_path, plate_path FROM events WHERE datetime(timestamp) < datetime(?)",
                (cutoff_iso,),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            for row in rows:
                deleted_files += int(self._safe_delete(row["frame_path"]))
                deleted_files += int(self._safe_delete(row["plate_path"]))

            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids)
                conn.commit()

        return {"deleted_events": len(ids), "deleted_media_files": deleted_files}

    def cleanup_old_media(self) -> Dict[str, int]:
        cutoff = time.time() - self.policy.media_retention_days * 86400
        removed = 0
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            for file_path in self.screenshots_dir.rglob(ext):
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                        removed += 1
                except FileNotFoundError:
                    continue
        return {"removed_old_media_files": removed}

    def rotate_media_by_size(self) -> Dict[str, int]:
        max_bytes = self.policy.max_screenshots_mb * 1024 * 1024
        files = []
        total = 0
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            for file_path in self.screenshots_dir.rglob(ext):
                try:
                    stat = file_path.stat()
                except FileNotFoundError:
                    continue
                total += stat.st_size
                files.append((file_path, stat.st_mtime, stat.st_size))

        if total <= max_bytes:
            return {"rotated_media_files": 0}

        files.sort(key=lambda item: item[1])
        removed = 0
        for file_path, _, size in files:
            if total <= max_bytes:
                break
            try:
                file_path.unlink()
                total -= size
                removed += 1
            except FileNotFoundError:
                continue
        return {"rotated_media_files": removed}

    def run_retention_cycle(self) -> Dict[str, int]:
        result = {}
        result.update(self.cleanup_old_events())
        result.update(self.cleanup_old_media())
        result.update(self.rotate_media_by_size())
        return result

    def export_events_csv(self, *, start: Optional[str] = None, end: Optional[str] = None, channel: Optional[str] = None) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        export_path = Path(self.policy.export_dir) / f"events_{ts}.csv"

        query = "SELECT * FROM events"
        filters = []
        params: list[Any] = []
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

        with self._connect() as conn, export_path.open("w", encoding="utf-8", newline="") as file:
            rows = conn.execute(query, params).fetchall()
            writer = csv.writer(file, delimiter=";")
            writer.writerow(["id", "timestamp", "channel", "plate", "country", "confidence", "source", "frame_path", "plate_path", "direction"])
            for row in rows:
                writer.writerow([row["id"], row["timestamp"], row["channel"], row["plate"], row["country"], row["confidence"], row["source"], row["frame_path"], row["plate_path"], row["direction"]])

        return str(export_path)

    def export_events_bundle(self, *, start: Optional[str] = None, end: Optional[str] = None, channel: Optional[str] = None, include_media: bool = True) -> str:
        csv_path = Path(self.export_events_csv(start=start, end=end, channel=channel))
        bundle_path = csv_path.with_suffix(".zip")

        with self._connect() as conn, zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(csv_path, arcname=csv_path.name)
            if include_media:
                rows = conn.execute("SELECT frame_path, plate_path FROM events").fetchall()
                added: set[str] = set()
                for row in rows:
                    for media_path in (row["frame_path"], row["plate_path"]):
                        if not media_path or media_path in added:
                            continue
                        path = Path(media_path)
                        if path.exists() and path.is_file():
                            try:
                                archive.write(path, arcname=f"media/{path.name}")
                                added.add(media_path)
                            except FileNotFoundError:
                                continue

        return str(bundle_path)
