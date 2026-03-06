from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from anpr.infrastructure.logging_manager import get_logger
from anpr.infrastructure.storage import EventDatabase

logger = get_logger(__name__)


@dataclass
class ChannelMetrics:
    state: str = "stopped"
    reconnect_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    fps: float = 0.0
    latency_ms: float = 0.0
    last_event_at: Optional[str] = None
    last_error: Optional[str] = None


@dataclass
class ChannelContext:
    channel: Dict[str, Any]
    thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    metrics: ChannelMetrics = field(default_factory=ChannelMetrics)


class ChannelProcessor:
    def __init__(self, event_callback, db_path: str, plate_settings: Dict[str, Any] | None = None) -> None:
        self._event_callback = event_callback
        self._contexts: Dict[int, ChannelContext] = {}
        self._lock = threading.RLock()
        self._db = EventDatabase(db_path)
        self._plate_settings = plate_settings or {}

    def list_states(self) -> Dict[int, ChannelMetrics]:
        with self._lock:
            return {cid: ctx.metrics for cid, ctx in self._contexts.items()}

    def ensure_channel(self, channel: Dict[str, Any]) -> None:
        channel_id = int(channel["id"])
        with self._lock:
            if channel_id not in self._contexts:
                self._contexts[channel_id] = ChannelContext(channel=channel)
            else:
                self._contexts[channel_id].channel = channel

    def remove_channel(self, channel_id: int) -> None:
        self.stop(channel_id)
        with self._lock:
            self._contexts.pop(channel_id, None)

    def start(self, channel_id: int) -> None:
        with self._lock:
            ctx = self._contexts[channel_id]
            if ctx.thread and ctx.thread.is_alive():
                return
            ctx.stop_event.clear()
            ctx.metrics.state = "starting"
            ctx.thread = threading.Thread(target=self._run_channel, args=(channel_id,), daemon=True, name=f"channel-{channel_id}")
            ctx.thread.start()

    def stop(self, channel_id: int) -> None:
        with self._lock:
            ctx = self._contexts.get(channel_id)
            if not ctx:
                return
            ctx.stop_event.set()
            thread = ctx.thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        with self._lock:
            if channel_id in self._contexts:
                self._contexts[channel_id].metrics.state = "stopped"

    def restart(self, channel_id: int) -> None:
        self.stop(channel_id)
        self.start(channel_id)

    def _run_channel(self, channel_id: int) -> None:
        import cv2

        with self._lock:
            ctx = self._contexts[channel_id]
            channel = dict(ctx.channel)
            stop_event = ctx.stop_event
            metrics = ctx.metrics
        metrics.state = "running"

        cap = None
        try:
            from anpr.pipeline.factory import build_components

            pipeline, detector = build_components(
                best_shots=int(channel.get("best_shots", 3)),
                cooldown_seconds=int(channel.get("cooldown_seconds", 5)),
                min_confidence=float(channel.get("ocr_min_confidence", 0.6)),
                plate_config=self._plate_settings,
                direction_config=channel.get("direction", {}),
                min_plate_size=channel.get("min_plate_size"),
                max_plate_size=channel.get("max_plate_size"),
                size_filter_enabled=bool(channel.get("size_filter_enabled", True)),
            )
            cap = cv2.VideoCapture(str(channel.get("source", "0")))
            if not cap.isOpened():
                raise RuntimeError(f"Не удалось открыть источник {channel.get('source')}")

            frames = 0
            window_start = time.monotonic()
            while not stop_event.is_set():
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    metrics.timeout_count += 1
                    metrics.reconnect_count += 1
                    cap.release()
                    time.sleep(1)
                    cap = cv2.VideoCapture(str(channel.get("source", "0")))
                    continue
                detections = detector.track(frame)
                results = pipeline.process_frame(frame, detections)
                for detection in results:
                    plate = detection.get("text")
                    if not plate:
                        continue
                    event = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "channel": channel.get("name", f"Канал {channel_id}"),
                        "channel_id": channel_id,
                        "plate": plate,
                        "country": detection.get("country"),
                        "confidence": float(detection.get("confidence", 0.0)),
                        "source": str(channel.get("source", "")),
                        "direction": detection.get("direction", "UNKNOWN"),
                    }
                    self._db.insert_event(**{k: event[k] for k in ("channel", "plate", "country", "confidence", "source", "timestamp", "direction")})
                    self._event_callback(event)
                    metrics.last_event_at = event["timestamp"]
                frames += 1
                elapsed = time.monotonic() - window_start
                if elapsed >= 1.0:
                    metrics.fps = frames / elapsed
                    frames = 0
                    window_start = time.monotonic()
                metrics.latency_ms = (time.monotonic() - started) * 1000.0
        except Exception as exc:  # noqa: BLE001
            metrics.state = "error"
            metrics.error_count += 1
            metrics.last_error = str(exc)
            logger.exception("Ошибка канала %s", channel_id)
        finally:
            metrics.state = "stopped"
            if cap is not None:
                cap.release()
