from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

@dataclass(frozen=True)
class DebugSettings:
    show_channel_metrics: bool = True
    log_panel_enabled: bool = False

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "DebugSettings":
        data = payload or {}
        return cls(
            show_channel_metrics=bool(data.get("show_channel_metrics", True)),
            log_panel_enabled=bool(data.get("log_panel_enabled", False)),
        )

    def to_dict(self) -> Dict[str, bool]:
        return {
            "show_channel_metrics": self.show_channel_metrics,
            "log_panel_enabled": self.log_panel_enabled,
        }


@dataclass
class ChannelStageTimings:
    detection_ms: float = 0.0
    ocr_ms: float = 0.0
    postprocess_ms: float = 0.0


@dataclass
class ChannelDebugState:
    channel_id: int
    updated_at: Optional[str] = None
    frame_size: Optional[tuple[int, int]] = None
    last_bbox_norm: Optional[tuple[float, float, float, float]] = None
    last_ocr_text: Optional[str] = None
    last_direction: Optional[str] = None
    stage_timings: ChannelStageTimings = field(default_factory=ChannelStageTimings)
    last_object_update_mono: float = 0.0
    last_ocr_update_mono: float = 0.0

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


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

    def update_from_detections(
        self,
        channel_id: int,
        detections: List[Dict[str, Any]],
        *,
        frame_shape: tuple[int, ...],
    ) -> None:
        now = time.monotonic()
        frame_height, frame_width = frame_shape[:2]
        if frame_width <= 0 or frame_height <= 0:
            return
        with self._lock:
            state = self.ensure_channel_state(channel_id)
            if not detections:
                self._cleanup_stale_locked(state, now)
                return

            best_detection: Optional[Dict[str, Any]] = None
            best_area = -1
            for det in detections:
                bbox = det.get("bbox")
                if not bbox or len(bbox) < 4:
                    continue
                x1, y1, x2, y2 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
                if x2 <= x1 or y2 <= y1:
                    continue
                area = (x2 - x1) * (y2 - y1)
                if area > best_area:
                    best_area = area
                    best_detection = {"bbox": (x1, y1, x2, y2), "direction": det.get("direction")}

            if best_detection is None:
                self._cleanup_stale_locked(state, now)
                return

            x1, y1, x2, y2 = best_detection["bbox"]
            state.frame_size = (frame_width, frame_height)
            state.last_bbox_norm = (
                max(0.0, min(1.0, x1 / frame_width)),
                max(0.0, min(1.0, y1 / frame_height)),
                max(0.0, min(1.0, x2 / frame_width)),
                max(0.0, min(1.0, y2 / frame_height)),
            )
            state.last_object_update_mono = now
            explicit_direction = str(best_detection.get("direction") or "").strip().upper()
            state.last_direction = explicit_direction or None
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

    def list_channel_states(self) -> Dict[int, Dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            for state in self._channels.values():
                self._cleanup_stale_locked(state, now)
            return {channel_id: self._state_to_dict(state) for channel_id, state in self._channels.items()}

    def _cleanup_stale_locked(self, state: ChannelDebugState, now: float) -> None:
        ttl = self._state_ttl_seconds
        if state.last_object_update_mono and (now - state.last_object_update_mono) > ttl:
            state.frame_size = None
            state.last_bbox_norm = None
            state.last_direction = None
        if state.last_ocr_update_mono and (now - state.last_ocr_update_mono) > ttl:
            state.last_ocr_text = None

    @staticmethod
    def _state_to_dict(state: ChannelDebugState) -> Dict[str, Any]:
        return {
            "channel_id": state.channel_id,
            "updated_at": state.updated_at,
            "overlay": {
                "frame_size": {
                    "width": state.frame_size[0],
                    "height": state.frame_size[1],
                }
                if state.frame_size
                else None,
                "bbox_norm": list(state.last_bbox_norm) if state.last_bbox_norm else None,
                "ocr_text": state.last_ocr_text,
                "direction": state.last_direction,
            },
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
