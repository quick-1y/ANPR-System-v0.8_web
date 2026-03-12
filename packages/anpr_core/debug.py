from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class DebugSettings:
    show_detection_boxes: bool = False
    show_ocr_text: bool = False
    show_direction_tracks: bool = False
    show_channel_metrics: bool = True
    log_panel_enabled: bool = False

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "DebugSettings":
        data = payload or {}
        return cls(
            show_detection_boxes=bool(data.get("show_detection_boxes", False)),
            show_ocr_text=bool(data.get("show_ocr_text", False)),
            show_direction_tracks=bool(data.get("show_direction_tracks", False)),
            show_channel_metrics=bool(data.get("show_channel_metrics", True)),
            log_panel_enabled=bool(data.get("log_panel_enabled", False)),
        )

    def to_dict(self) -> Dict[str, bool]:
        return {
            "show_detection_boxes": self.show_detection_boxes,
            "show_ocr_text": self.show_ocr_text,
            "show_direction_tracks": self.show_direction_tracks,
            "show_channel_metrics": self.show_channel_metrics,
            "log_panel_enabled": self.log_panel_enabled,
        }

    @property
    def overlay_enabled(self) -> bool:
        return any(
            [
                self.show_detection_boxes,
                self.show_ocr_text,
                self.show_direction_tracks,
                self.show_channel_metrics,
            ]
        )


@dataclass
class ChannelStageTimings:
    detection_ms: float = 0.0
    ocr_ms: float = 0.0
    postprocess_ms: float = 0.0


@dataclass
class ChannelDebugState:
    channel_id: int
    updated_at: Optional[str] = None
    last_bbox: Optional[tuple[int, int, int, int]] = None
    last_ocr_text: Optional[str] = None
    last_direction: Optional[str] = None
    track_points: Deque[tuple[int, int]] = field(default_factory=lambda: deque(maxlen=40))
    stage_timings: ChannelStageTimings = field(default_factory=ChannelStageTimings)
    last_object_update_mono: float = 0.0
    last_ocr_update_mono: float = 0.0
    track_histories: Dict[str, Deque[tuple[int, int]]] = field(default_factory=dict)
    active_track_key: str = ""
    fallback_track_seq: int = 0

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


class DebugOverlayRenderer:
    def render(
        self,
        frame: np.ndarray,
        *,
        settings: DebugSettings,
        state: ChannelDebugState,
        metrics: Any,
    ) -> np.ndarray:
        import cv2

        if not settings.overlay_enabled:
            return frame

        canvas = frame.copy()
        if settings.show_detection_boxes and state.last_bbox:
            x1, y1, x2, y2 = state.last_bbox
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (48, 214, 90), 2)

        if settings.show_ocr_text and state.last_ocr_text:
            anchor_x, anchor_y = 12, 28
            if state.last_bbox:
                anchor_x = max(8, state.last_bbox[0])
                anchor_y = max(20, state.last_bbox[1] - 8)
            cv2.putText(
                canvas,
                f"OCR: {state.last_ocr_text}",
                (anchor_x, anchor_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (232, 168, 56),
                2,
                cv2.LINE_AA,
            )

        if settings.show_direction_tracks:
            points = list(state.track_points)
            if len(points) >= 2:
                for idx in range(1, len(points)):
                    cv2.line(canvas, points[idx - 1], points[idx], (255, 210, 86), 2)
            if len(points) >= 3 and state.last_direction:
                px, py = points[-1]
                cv2.putText(
                    canvas,
                    f"DIR: {state.last_direction}",
                    (max(8, px - 20), max(20, py - 12)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 210, 86),
                    2,
                    cv2.LINE_AA,
                )

        if settings.show_channel_metrics:
            self._draw_metrics(canvas, metrics, state)

        return canvas

    @staticmethod
    def _draw_metrics(frame: np.ndarray, metrics: Any, state: ChannelDebugState) -> None:
        import cv2

        rows = [
            f"State: {getattr(metrics, 'state', 'unknown')}",
            f"FPS: {getattr(metrics, 'fps', 0.0):.2f}",
            f"Latency: {getattr(metrics, 'latency_ms', 0.0):.1f}ms",
            f"Reconnect: {getattr(metrics, 'reconnect_count', 0)}",
            f"Timeouts: {getattr(metrics, 'timeout_count', 0)}",
            f"Empty/Fail: {getattr(metrics, 'empty_frames', 0)}/{getattr(metrics, 'failed_frames', 0)}",
            f"Skipped D/M: {getattr(metrics, 'detector_skipped_frames', 0)}/{getattr(metrics, 'motion_skipped_frames', 0)}",
            f"Detect: {state.stage_timings.detection_ms:.1f}ms",
            f"OCR: {state.stage_timings.ocr_ms:.1f}ms",
            f"Post: {state.stage_timings.postprocess_ms:.1f}ms",
        ]
        y = 18
        for row in rows:
            cv2.putText(frame, row, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 236, 255), 1, cv2.LINE_AA)
            y += 16


class DebugRegistry:
    def __init__(self, initial_settings: Dict[str, Any] | None = None, *, state_ttl_seconds: float = 2.0) -> None:
        self._lock = threading.RLock()
        self._settings = DebugSettings.from_dict(initial_settings)
        self._channels: Dict[int, ChannelDebugState] = {}
        self._state_ttl_seconds = max(0.2, float(state_ttl_seconds))

    def get_settings(self) -> DebugSettings:
        with self._lock:
            return self._settings

    def update_settings(self, settings_payload: Dict[str, Any] | DebugSettings) -> DebugSettings:
        with self._lock:
            if isinstance(settings_payload, DebugSettings):
                self._settings = settings_payload
            else:
                self._settings = DebugSettings.from_dict(settings_payload)
            return self._settings

    def ensure_channel_state(self, channel_id: int) -> ChannelDebugState:
        with self._lock:
            if channel_id not in self._channels:
                self._channels[channel_id] = ChannelDebugState(channel_id=channel_id)
            return self._channels[channel_id]

    def remove_channel_state(self, channel_id: int) -> None:
        with self._lock:
            self._channels.pop(channel_id, None)

    def update_stage_timings(self, channel_id: int, *, detection_ms: float, ocr_ms: float, postprocess_ms: float) -> None:
        with self._lock:
            state = self.ensure_channel_state(channel_id)
            state.stage_timings.detection_ms = float(detection_ms)
            state.stage_timings.ocr_ms = float(ocr_ms)
            state.stage_timings.postprocess_ms = float(postprocess_ms)
            state.touch()

    def update_from_detections(self, channel_id: int, detections: List[Dict[str, Any]]) -> None:
        now = time.monotonic()
        with self._lock:
            state = self.ensure_channel_state(channel_id)
            if not detections:
                self._cleanup_stale_locked(state, now)
                return

            best_detection: Optional[Dict[str, Any]] = None
            best_track_key = ""
            best_len = -1

            for det in detections:
                bbox = det.get("bbox")
                if not bbox or len(bbox) < 4:
                    continue
                x1, y1, x2, y2 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
                if x2 <= x1 or y2 <= y1:
                    continue
                center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                raw_track_id = det.get("track_id")
                if raw_track_id is not None:
                    track_key = f"track:{int(raw_track_id)}"
                else:
                    track_key = self._resolve_fallback_track_key(state, center)
                history = state.track_histories.setdefault(track_key, deque(maxlen=40))
                history.append(center)
                h_len = len(history)
                if h_len > best_len:
                    best_len = h_len
                    best_detection = {"bbox": (x1, y1, x2, y2), "direction": det.get("direction")}
                    best_track_key = track_key

            if best_detection is None:
                self._cleanup_stale_locked(state, now)
                return

            state.last_bbox = best_detection["bbox"]
            state.active_track_key = best_track_key
            state.track_points = deque(state.track_histories.get(best_track_key, deque()), maxlen=40)
            state.last_object_update_mono = now
            explicit_direction = str(best_detection.get("direction") or "").strip().upper()
            if explicit_direction and explicit_direction != "UNKNOWN":
                state.last_direction = explicit_direction
            else:
                state.last_direction = self._estimate_direction(state.track_points)
            state.touch()
            self._cleanup_stale_locked(state, now)

    def update_from_pipeline_results(self, channel_id: int, detections: List[Dict[str, Any]]) -> None:
        now = time.monotonic()
        with self._lock:
            state = self.ensure_channel_state(channel_id)
            for det in detections:
                text = str(det.get("text") or "").strip()
                if text and text.upper() != "НЕЧИТАЕМО":
                    state.last_ocr_text = text
                    state.last_ocr_update_mono = now
                    break
            self._cleanup_stale_locked(state, now)
            state.touch()

    def cleanup_stale(self, channel_id: int) -> None:
        now = time.monotonic()
        with self._lock:
            state = self.ensure_channel_state(channel_id)
            self._cleanup_stale_locked(state, now)

    def get_channel_state_snapshot(self, channel_id: int) -> ChannelDebugState:
        now = time.monotonic()
        with self._lock:
            state = self.ensure_channel_state(channel_id)
            self._cleanup_stale_locked(state, now)
            clone = ChannelDebugState(channel_id=state.channel_id)
            clone.updated_at = state.updated_at
            clone.last_bbox = state.last_bbox
            clone.last_ocr_text = state.last_ocr_text
            clone.last_direction = state.last_direction
            clone.track_points = deque(state.track_points, maxlen=40)
            clone.stage_timings = ChannelStageTimings(
                detection_ms=state.stage_timings.detection_ms,
                ocr_ms=state.stage_timings.ocr_ms,
                postprocess_ms=state.stage_timings.postprocess_ms,
            )
            clone.last_object_update_mono = state.last_object_update_mono
            clone.last_ocr_update_mono = state.last_ocr_update_mono
            clone.active_track_key = state.active_track_key
            return clone

    def list_channel_states(self) -> Dict[int, Dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            for state in self._channels.values():
                self._cleanup_stale_locked(state, now)
            return {channel_id: self._state_to_dict(state) for channel_id, state in self._channels.items()}

    def _cleanup_stale_locked(self, state: ChannelDebugState, now: float) -> None:
        ttl = self._state_ttl_seconds
        if state.last_object_update_mono and (now - state.last_object_update_mono) > ttl:
            state.last_bbox = None
            state.last_direction = None
            state.track_points.clear()
            state.track_histories.clear()
            state.active_track_key = ""
        if state.last_ocr_update_mono and (now - state.last_ocr_update_mono) > ttl:
            state.last_ocr_text = None

    @staticmethod
    def _estimate_direction(track_points: Deque[tuple[int, int]]) -> Optional[str]:
        if len(track_points) < 3:
            return None
        start_x, start_y = track_points[0]
        end_x, end_y = track_points[-1]
        dx = end_x - start_x
        dy = end_y - start_y
        if abs(dx) < 8 and abs(dy) < 8:
            return None
        if abs(dx) >= abs(dy):
            return "RIGHT" if dx > 0 else "LEFT"
        return "DOWN" if dy > 0 else "UP"

    @staticmethod
    def _distance_sq(a: tuple[int, int], b: tuple[int, int]) -> int:
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        return dx * dx + dy * dy

    def _resolve_fallback_track_key(self, state: ChannelDebugState, center: tuple[int, int]) -> str:
        nearest_key: Optional[str] = None
        nearest_dist = 9_999_999
        max_match_dist_sq = 90 * 90
        for key, history in state.track_histories.items():
            if not key.startswith("fallback:") or not history:
                continue
            dist = self._distance_sq(center, history[-1])
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_key = key
        if nearest_key is not None and nearest_dist <= max_match_dist_sq:
            return nearest_key
        state.fallback_track_seq += 1
        return f"fallback:{state.fallback_track_seq}"

    @staticmethod
    def _state_to_dict(state: ChannelDebugState) -> Dict[str, Any]:
        return {
            "channel_id": state.channel_id,
            "updated_at": state.updated_at,
            "last_bbox": list(state.last_bbox) if state.last_bbox else None,
            "last_ocr_text": state.last_ocr_text,
            "last_direction": state.last_direction,
            "track_points": [list(item) for item in state.track_points],
            "stage_timings": {
                "detection_ms": state.stage_timings.detection_ms,
                "ocr_ms": state.stage_timings.ocr_ms,
                "postprocess_ms": state.stage_timings.postprocess_ms,
            },
        }


@dataclass
class DebugLogEntry:
    id: int
    timestamp: str
    level: str
    logger: str
    message: str
    service: str
    channel_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
            "service": self.service,
            "channel_id": self.channel_id,
        }


class DebugLogBus:
    def __init__(self, capacity: int = 1000) -> None:
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._buffer: Deque[DebugLogEntry] = deque(maxlen=max(100, int(capacity)))
        self._seq = 0

    def publish(self, *, level: str, logger_name: str, message: str, service: str, channel_id: Optional[int]) -> DebugLogEntry:
        with self._condition:
            self._seq += 1
            entry = DebugLogEntry(
                id=self._seq,
                timestamp=datetime.now(timezone.utc).isoformat(),
                level=level,
                logger=logger_name,
                message=message,
                service=service,
                channel_id=channel_id,
            )
            self._buffer.append(entry)
            self._condition.notify_all()
            return entry

    def snapshot(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._buffer)[-max(1, min(2000, int(limit))):]
            return [item.to_dict() for item in items]

    def wait_for_entries(self, last_id: int, timeout: float = 15.0) -> List[Dict[str, Any]]:
        with self._condition:
            if self._seq <= last_id:
                self._condition.wait(timeout=timeout)
            return [item.to_dict() for item in self._buffer if item.id > last_id]
