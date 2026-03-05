from __future__ import annotations

import asyncio
from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import Any, Awaitable, Callable, Optional, Tuple

import cv2
import numpy as np

from anpr.infrastructure.logging_manager import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SharedFrameInfo:
    name: str
    shape: Tuple[int, int, int]
    dtype: str


class InferenceLimiter:
    """Пропускает лишние кадры для инференса детектора."""

    def __init__(self, stride: int) -> None:
        self.stride = max(1, stride)
        self._counter = 0

    def allow(self) -> bool:
        should_run = self._counter == 0
        self._counter = (self._counter + 1) % self.stride
        return should_run


def create_shared_frame(frame: cv2.Mat) -> tuple[SharedFrameInfo, shared_memory.SharedMemory]:
    contiguous = np.ascontiguousarray(frame)
    shm = shared_memory.SharedMemory(create=True, size=contiguous.nbytes)
    shm_array = np.ndarray(contiguous.shape, dtype=contiguous.dtype, buffer=shm.buf)
    shm_array[:] = contiguous
    info = SharedFrameInfo(name=shm.name, shape=contiguous.shape, dtype=str(contiguous.dtype))
    return info, shm


class InferenceScheduler:
    """Планирует инференс с поддержкой stride и shared memory."""

    def __init__(self, stride: int, use_shared_memory: bool) -> None:
        self._limiter = InferenceLimiter(stride)
        self._use_shared_memory = use_shared_memory

    def allow(self) -> bool:
        return self._limiter.allow()

    async def run(
        self,
        run_plain: Callable[[cv2.Mat, cv2.Mat, tuple[int, int, int, int], dict[str, Any]], Awaitable[tuple[list[dict], list[dict]]]],
        run_shared: Callable[[SharedFrameInfo, SharedFrameInfo, tuple[int, int, int, int], dict[str, Any]], Awaitable[tuple[list[dict], list[dict]]]],
        frame: cv2.Mat,
        roi_frame: cv2.Mat,
        roi_rect: tuple[int, int, int, int],
        config: dict[str, Any],
    ) -> tuple[list[dict], list[dict]]:
        if not self._use_shared_memory:
            return await run_plain(frame, roi_frame, roi_rect, config)

        frame_info = roi_info = None
        frame_shm = roi_shm = None
        try:
            frame_info, frame_shm = create_shared_frame(frame)
            roi_info, roi_shm = create_shared_frame(roi_frame)
            return await run_shared(frame_info, roi_info, roi_rect, config)
        except Exception as exc:
            logger.warning("Shared memory отключена: %s", exc)
            return await run_plain(frame, roi_frame, roi_rect, config)
        finally:
            for shm in (frame_shm, roi_shm):
                if shm is None:
                    continue
                try:
                    shm.close()
                    shm.unlink()
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    logger.debug("Ошибка освобождения shared memory: %s", exc)
