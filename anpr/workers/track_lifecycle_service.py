from __future__ import annotations

import time
from collections import deque

import cv2
import numpy as np

from anpr.pipeline.anpr_pipeline import TrackDirectionEstimator


class TrackLifecycleService:
    def __init__(self, history_size: int = 32, stale_seconds: float = 3.0) -> None:
        self._track_history: dict[int, deque[tuple[int, int]]] = {}
        self._track_last_seen: dict[int, float] = {}
        self._track_directions: dict[int, str] = {}
        self._track_history_size = history_size
        self._track_stale_seconds = stale_seconds

    def update(self, detections: list[dict]) -> None:
        now = time.monotonic()
        for det in detections:
            track_id = det.get("track_id")
            bbox = det.get("bbox")
            if track_id is None or not bbox or len(bbox) != 4:
                continue
            cx = int((bbox[0] + bbox[2]) / 2)
            cy = int((bbox[1] + bbox[3]) / 2)
            history = self._track_history.setdefault(int(track_id), deque(maxlen=self._track_history_size))
            history.append((cx, cy))
            self._track_last_seen[int(track_id)] = now
            if det.get("direction"):
                self._track_directions[int(track_id)] = str(det.get("direction"))

    @staticmethod
    def draw_label(frame: cv2.Mat, text: str, origin: tuple[int, int]) -> None:
        if not text:
            return
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.6
        thickness = 2
        text_size, _ = cv2.getTextSize(text, font, scale, thickness)
        x, y = origin
        x = max(0, x)
        y = max(text_size[1] + 4, y)
        cv2.rectangle(frame, (x, y - text_size[1] - 6), (x + text_size[0] + 8, y + 4), (0, 0, 0), -1)
        cv2.putText(frame, text, (x + 4, y - 2), font, scale, (0, 255, 0), thickness)

    def draw(self, frame: cv2.Mat) -> None:
        now = time.monotonic()
        stale_tracks = [tid for tid, last in self._track_last_seen.items() if now - last > self._track_stale_seconds]
        for tid in stale_tracks:
            self._track_history.pop(tid, None)
            self._track_last_seen.pop(tid, None)
            self._track_directions.pop(tid, None)

        direction_colors = {"APPROACHING": (0, 200, 0), "RECEDING": (220, 0, 0), "UNKNOWN": (200, 200, 0)}
        for track_id, history in self._track_history.items():
            if not history:
                continue
            points = np.array(history, dtype=np.int32)
            direction = self._track_directions.get(track_id, TrackDirectionEstimator.UNKNOWN)
            color = direction_colors.get(direction, (180, 180, 180))
            if len(points) > 1:
                cv2.polylines(frame, [points.reshape(-1, 1, 2)], False, color, 2)
            tail_x, tail_y = points[-1]
            cv2.circle(frame, (int(tail_x), int(tail_y)), 4, color, -1)
            self.draw_label(frame, f"#{track_id} {direction}", (int(tail_x) + 6, int(tail_y) - 6))
