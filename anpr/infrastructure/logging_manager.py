# /anpr/infrastructure/logging_manager.py
"""Централизованная настройка логирования приложения."""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from datetime import datetime, timedelta
from logging.handlers import QueueHandler, QueueListener
from typing import Any, Dict, Optional

LOG_FILENAME_FORMAT = "%Y-%m-%d_%H-00.log"


class HourlyFileHandler(logging.Handler):
    """Файловый обработчик, который создаёт новый файл каждый час."""

    def __init__(self, log_dir: str, encoding: str = "utf-8") -> None:
        super().__init__()
        self.log_dir = log_dir
        self.encoding = encoding
        self._stream: Optional[object] = None
        self._current_period_start: Optional[datetime] = None
        self._lock = threading.RLock()
        self._ensure_log_dir()
        self._open_stream(datetime.now().astimezone())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            with self._lock:
                self._open_stream(datetime.now().astimezone())
                if self._stream is not None:
                    self._stream.write(f"{message}\n")
                    self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        super().close()

    def _ensure_log_dir(self) -> None:
        os.makedirs(self.log_dir, exist_ok=True)

    @staticmethod
    def _period_start(current_time: datetime) -> datetime:
        return current_time.replace(minute=0, second=0, microsecond=0)

    def _open_stream(self, current_time: datetime) -> None:
        period_start = self._period_start(current_time)
        if self._current_period_start == period_start and self._stream is not None:
            return
        if self._stream is not None:
            self._stream.close()
        filename = period_start.strftime(LOG_FILENAME_FORMAT)
        path = os.path.join(self.log_dir, filename)
        self._stream = open(path, "a", encoding=self.encoding)
        self._current_period_start = period_start


def _cleanup_old_logs(log_dir: str, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    if not os.path.exists(log_dir):
        return 0

    now = datetime.now().astimezone()
    cutoff = now - timedelta(days=retention_days)
    removed = 0
    for entry in os.listdir(log_dir):
        if not entry.endswith(".log"):
            continue
        try:
            log_time = datetime.strptime(entry, LOG_FILENAME_FORMAT).replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
        if log_time <= cutoff:
            try:
                os.remove(os.path.join(log_dir, entry))
                removed += 1
            except OSError:
                continue
    return removed


class LoggingManager:
    """Создает согласованный стек логирования для GUI, пайплайна и фоновых потоков."""

    DEFAULT_LEVEL = "INFO"
    DEFAULT_LOG_DIR = "logs"
    DEFAULT_RETENTION_DAYS = 30

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
        self._listener: Optional[QueueListener] = None
        self._configure()

    def _configure(self) -> None:
        level_name = str(self.config.get("level", self.DEFAULT_LEVEL)).upper()
        level = getattr(logging, level_name, logging.INFO)
        log_dir = str(self.config.get("logs_dir") or self.DEFAULT_LOG_DIR)
        retention_days = int(self.config.get("retention_days", self.DEFAULT_RETENTION_DAYS))

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

        file_handler = HourlyFileHandler(log_dir)
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        queue_handler = QueueHandler(self._queue)
        root_logger = logging.getLogger()
        root_logger.setLevel(level)
        root_logger.handlers.clear()
        root_logger.addHandler(queue_handler)

        if self._listener is not None:
            self._listener.stop()
        self._listener = QueueListener(self._queue, file_handler, console_handler, respect_handler_level=True)
        self._listener.start()

        if retention_days > 0:
            cleanup_thread = threading.Thread(
                target=self._cleanup_loop, args=(log_dir, retention_days), daemon=True
            )
            cleanup_thread.start()

        logging.getLogger(__name__).debug(
            "Logging configured (level=%s, log_dir=%s, retention_days=%s)",
            level_name,
            log_dir,
            retention_days,
        )

    def _cleanup_loop(self, log_dir: str, retention_days: int) -> None:
        logger = logging.getLogger(__name__)
        while True:
            removed = _cleanup_old_logs(log_dir, retention_days)
            if removed:
                logger.info("Удалено устаревших логов: %s", removed)
            time.sleep(3600)


def get_logger(name: str) -> logging.Logger:
    """Утилита для получения именованного логгера."""

    return logging.getLogger(name)


def log_perf_stage(
    logger: logging.Logger,
    channel: str,
    stage: str,
    duration_ms: float,
    level: int = logging.DEBUG,
    **extra: Any,
) -> None:
    """Структурированный perf-лог стадии обработки.

    По умолчанию такие сообщения пишутся в DEBUG, чтобы не засорять INFO-лог
    при потоковой детекции на нескольких каналах.
    """

    payload = {"channel": channel, "stage": stage, "duration_ms": round(float(duration_ms), 2)}
    payload.update(extra)
    parts = [f"{key}={value}" for key, value in payload.items()]
    logger.log(level, "perf %s", " ".join(parts))
