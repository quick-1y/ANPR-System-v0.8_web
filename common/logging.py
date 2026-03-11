from __future__ import annotations

import logging
import os
import queue
import re
import threading
from datetime import datetime, timedelta
from logging.handlers import QueueHandler, QueueListener
from typing import Any, Optional

LOG_FILENAME_TIME_FORMAT = "%Y-%m-%d_%H-00"
DEFAULT_LEVEL = "INFO"
DEFAULT_LOG_DIR = "logs"
DEFAULT_RETENTION_DAYS = 30
CLEANUP_INTERVAL_SECONDS = 3600

_STATE_LOCK = threading.RLock()
_LOG_QUEUE: queue.Queue[logging.LogRecord] | None = None
_QUEUE_LISTENER: QueueListener | None = None
_CLEANUP_THREAD: threading.Thread | None = None
_CLEANUP_STOP: threading.Event | None = None
_FILE_HANDLER: logging.Handler | None = None
_CONSOLE_HANDLER: logging.Handler | None = None
_CURRENT_SERVICE_NAME = "app"


class ServiceNameFilter(logging.Filter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "service", None):
            record.service = self._service_name
        return True


class HourlyFileHandler(logging.Handler):
    """Файловый обработчик с ротацией по часу и service-prefix в имени файла."""

    def __init__(self, log_dir: str, service_name: str, encoding: str = "utf-8") -> None:
        super().__init__()
        self.log_dir = log_dir
        self.service_name = _normalize_service_name(service_name)
        self.encoding = encoding
        self._stream: Optional[object] = None
        self._current_period_start: Optional[datetime] = None
        self._lock = threading.RLock()
        os.makedirs(self.log_dir, exist_ok=True)
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

    @staticmethod
    def _period_start(current_time: datetime) -> datetime:
        return current_time.replace(minute=0, second=0, microsecond=0)

    def _build_filename(self, period_start: datetime) -> str:
        return f"{self.service_name}_{period_start.strftime(LOG_FILENAME_TIME_FORMAT)}.log"

    def _open_stream(self, current_time: datetime) -> None:
        period_start = self._period_start(current_time)
        if self._current_period_start == period_start and self._stream is not None:
            return
        if self._stream is not None:
            self._stream.close()
        filename = self._build_filename(period_start)
        path = os.path.join(self.log_dir, filename)
        self._stream = open(path, "a", encoding=self.encoding)
        self._current_period_start = period_start


def _normalize_service_name(service_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(service_name or "app")).strip("_")
    return normalized or "app"


def _resolve_level(level_value: Any) -> int:
    level_name = str(level_value or DEFAULT_LEVEL).upper()
    if level_name == "ALL":
        return logging.NOTSET
    resolved = getattr(logging, level_name, None)
    return resolved if isinstance(resolved, int) else logging.INFO


def _cleanup_old_logs(log_dir: str, retention_days: int) -> int:
    if retention_days <= 0 or not os.path.isdir(log_dir):
        return 0

    now = datetime.now().astimezone()
    cutoff = now - timedelta(days=retention_days)
    removed = 0
    for entry in os.listdir(log_dir):
        if not entry.endswith(".log"):
            continue
        match = re.match(r"^[a-zA-Z0-9_-]+_(\d{4}-\d{2}-\d{2}_\d{2}-00)\.log$", entry)
        if not match:
            continue
        try:
            log_time = datetime.strptime(match.group(1), LOG_FILENAME_TIME_FORMAT).replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
        if log_time <= cutoff:
            try:
                os.remove(os.path.join(log_dir, entry))
                removed += 1
            except OSError:
                continue
    return removed


def _cleanup_loop(log_dir: str, retention_days: int, stop_event: threading.Event) -> None:
    logger = logging.getLogger(__name__)
    while not stop_event.wait(timeout=CLEANUP_INTERVAL_SECONDS):
        removed = _cleanup_old_logs(log_dir, retention_days)
        if removed:
            logger.info("Удалено устаревших логов: %s", removed)


def _close_handler(handler: logging.Handler | None) -> None:
    if handler is None:
        return
    try:
        handler.flush()
    except Exception:
        pass
    try:
        handler.close()
    except Exception:
        pass


def _stop_runtime_threads() -> None:
    global _QUEUE_LISTENER, _CLEANUP_THREAD, _CLEANUP_STOP, _FILE_HANDLER, _CONSOLE_HANDLER

    if _QUEUE_LISTENER is not None:
        _QUEUE_LISTENER.stop()
        _QUEUE_LISTENER = None

    _close_handler(_FILE_HANDLER)
    _close_handler(_CONSOLE_HANDLER)
    _FILE_HANDLER = None
    _CONSOLE_HANDLER = None

    if _CLEANUP_STOP is not None:
        _CLEANUP_STOP.set()

    if _CLEANUP_THREAD is not None and _CLEANUP_THREAD.is_alive():
        _CLEANUP_THREAD.join(timeout=2.0)

    _CLEANUP_THREAD = None
    _CLEANUP_STOP = None


def configure_logging(config: dict[str, Any] | None, *, service_name: str) -> None:
    global _LOG_QUEUE, _QUEUE_LISTENER, _CLEANUP_THREAD, _CLEANUP_STOP, _FILE_HANDLER, _CONSOLE_HANDLER, _CURRENT_SERVICE_NAME

    config = config or {}
    level_name = str(config.get("level", DEFAULT_LEVEL)).upper()
    level = _resolve_level(level_name)
    retention_days = int(config.get("retention_days", DEFAULT_RETENTION_DAYS))
    log_dir = str(config.get("logs_dir") or DEFAULT_LOG_DIR)
    normalized_service = _normalize_service_name(service_name)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(service)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    with _STATE_LOCK:
        _stop_runtime_threads()

        _CURRENT_SERVICE_NAME = normalized_service
        _LOG_QUEUE = queue.Queue(-1)

        queue_handler = QueueHandler(_LOG_QUEUE)

        service_filter = ServiceNameFilter(normalized_service)

        file_handler = HourlyFileHandler(log_dir=log_dir, service_name=normalized_service)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(service_filter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(service_filter)

        _FILE_HANDLER = file_handler
        _CONSOLE_HANDLER = console_handler

        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.filters.clear()
        root_logger.setLevel(level)
        root_logger.addHandler(queue_handler)

        _QUEUE_LISTENER = QueueListener(_LOG_QUEUE, file_handler, console_handler, respect_handler_level=True)
        _QUEUE_LISTENER.start()

        if retention_days > 0:
            removed = _cleanup_old_logs(log_dir, retention_days)
            if removed:
                logging.getLogger(__name__).info("Удалено устаревших логов при запуске: %s", removed)

        if retention_days > 0:
            _CLEANUP_STOP = threading.Event()
            _CLEANUP_THREAD = threading.Thread(
                target=_cleanup_loop,
                args=(log_dir, retention_days, _CLEANUP_STOP),
                daemon=True,
                name="logging-cleanup",
            )
            _CLEANUP_THREAD.start()

        logging.getLogger(__name__).info(
            "Logging configured (service=%s, level=%s, logs_dir=%s, retention_days=%s)",
            normalized_service,
            level_name,
            log_dir,
            retention_days,
        )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_perf_stage(
    logger: logging.Logger,
    channel: str,
    stage: str,
    duration_ms: float,
    level: int = logging.DEBUG,
    **extra: Any,
) -> None:
    payload = {"channel": channel, "stage": stage, "duration_ms": round(float(duration_ms), 2)}
    payload.update(extra)
    parts = [f"{key}={value}" for key, value in payload.items()]
    logger.log(level, "perf %s", " ".join(parts))
