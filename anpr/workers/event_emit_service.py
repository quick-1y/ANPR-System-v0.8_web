from __future__ import annotations

from typing import Callable
import time

import cv2
from PyQt5 import QtGui

from anpr.infrastructure.event_writer import EventWriter


class EventEmitService:
    """Сервис записи и публикации событий канала."""

    def __init__(self, event_writer: EventWriter, event_emit: Callable[[dict], None]) -> None:
        self._event_writer = event_writer
        self._event_emit = event_emit

    @staticmethod
    def to_qimage(frame, *, is_rgb: bool = False):
        if frame is None or frame.size == 0:
            return None
        rgb_frame = frame if is_rgb else cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb_frame.shape
        bytes_per_line = channels * width
        return QtGui.QImage(rgb_frame.data, width, height, bytes_per_line, QtGui.QImage.Format_RGB888).copy()

    async def persist_and_emit(self, source: str, results: list[dict], channel_name: str, frame, rgb_frame) -> dict:
        started = time.monotonic()
        events = await self._event_writer.write_events(source, results, channel_name, frame)
        for event in events:
            event["frame_image"] = self.to_qimage(rgb_frame, is_rgb=True)
            bbox = event.get("bbox") or ()
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                x1, y1, x2, y2 = bbox
                plate_crop = frame[y1:y2, x1:x2] if frame is not None else None
            else:
                plate_crop = None
            event["plate_image"] = self.to_qimage(plate_crop)
        for event in events:
            self._event_emit(event)
        return {"persist_ms": (time.monotonic() - started) * 1000.0, "events_count": len(events)}

