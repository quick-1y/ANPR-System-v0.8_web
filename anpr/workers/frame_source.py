from __future__ import annotations

import asyncio
from typing import Callable, Optional

import cv2

from anpr.infrastructure.logging_manager import get_logger

logger = get_logger(__name__)


class FrameSource:
    """Управляет подключением и чтением кадров видеопотока."""

    def __init__(
        self,
        source: str,
        reconnect_enabled: bool,
        retry_interval_seconds: float,
        should_continue: Callable[[], bool],
        status_emit: Callable[[str], None],
    ) -> None:
        self.source = source
        self.reconnect_enabled = reconnect_enabled
        self.retry_interval_seconds = retry_interval_seconds
        self.should_continue = should_continue
        self.status_emit = status_emit

    def open_capture(self) -> Optional[cv2.VideoCapture]:
        try:
            capture = cv2.VideoCapture(int(self.source) if self.source.isnumeric() else self.source)
            if not capture.isOpened():
                logger.warning("Не удалось открыть источник: %s", self.source)
                return None
            return capture
        except Exception as exc:
            logger.error("Ошибка открытия источника %s: %s", self.source, exc)
            return None

    async def open_with_retries(self) -> Optional[cv2.VideoCapture]:
        while self.should_continue():
            capture = await asyncio.to_thread(self.open_capture)
            if capture is not None:
                self.status_emit("")
                return capture

            if not self.reconnect_enabled:
                self.status_emit("Нет сигнала")
                return None

            self.status_emit(f"Нет сигнала, повтор через {int(self.retry_interval_seconds)}с")
            await asyncio.sleep(max(0.1, self.retry_interval_seconds))
        return None
