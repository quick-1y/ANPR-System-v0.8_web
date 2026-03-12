from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict

from fastapi import FastAPI, Request

from anpr.infrastructure.settings_manager import SettingsManager
from anpr.infrastructure.storage import StorageUnavailableError
from app.shared.data_lifecycle import DataLifecycleService, RetentionPolicy
from common.logging import configure_logging, get_logger

logger = get_logger(__name__)


class RetentionScheduler:
    def __init__(self, lifecycle: DataLifecycleService) -> None:
        self._lifecycle = lifecycle
        self._task: asyncio.Task[Any] | None = None
        self._last_run: Dict[str, int] | None = None

    async def _loop(self) -> None:
        while True:
            policy = self._lifecycle.policy
            if policy.auto_cleanup_enabled:
                logger.info("Запуск retention cycle (interval_minutes=%s)", policy.cleanup_interval_minutes)
                try:
                    self._last_run = self._lifecycle.run_retention_cycle()
                except StorageUnavailableError:
                    logger.exception("Ошибка retention cycle")
                    self._last_run = {"status": "error"}
            await asyncio.sleep(max(60, policy.cleanup_interval_minutes * 60))

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    @property
    def last_run(self) -> Dict[str, int] | None:
        return self._last_run


@dataclass
class WorkerContainer:
    settings: SettingsManager
    lifecycle: DataLifecycleService
    scheduler: RetentionScheduler

    @classmethod
    def build(cls) -> "WorkerContainer":
        settings = SettingsManager()
        configure_logging(settings.get_logging_config(), service_name="worker")
        storage = settings.get_storage_settings()
        policy = RetentionPolicy.from_storage(storage)
        lifecycle = DataLifecycleService(
            screenshots_dir=settings.get_screenshot_dir(),
            policy=policy,
            postgres_dsn=str(storage.get("postgres_dsn", "")).strip(),
        )
        scheduler = RetentionScheduler(lifecycle)
        return cls(settings=settings, lifecycle=lifecycle, scheduler=scheduler)


app = FastAPI(title="ANPR Retention Worker", version="0.8-stage7")


def _get_container(request: Request) -> WorkerContainer:
    return request.app.state.container


@app.on_event("startup")
async def startup() -> None:
    container = WorkerContainer.build()
    app.state.container = container
    logger.info("Retention worker startup")
    container.scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    logger.info("Retention worker shutdown")
    container: WorkerContainer | None = getattr(app.state, "container", None)
    if container is not None:
        container.scheduler.stop()


@app.get("/worker/health")
def health(request: Request) -> Dict[str, Any]:
    container = _get_container(request)
    return {
        "status": "ok",
        "policy": container.lifecycle.policy.to_storage(),
        "last_run": container.scheduler.last_run,
    }


@app.post("/worker/retention/run")
def run_retention(request: Request) -> Dict[str, Any]:
    container = _get_container(request)
    logger.info("Ручной запуск retention endpoint")
    try:
        result = container.lifecycle.run_retention_cycle()
        return {"status": "ok", **result}
    except StorageUnavailableError as exc:
        logger.exception("Ошибка retention cycle при ручном запуске")
        return {"status": "error", "detail": str(exc)}


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "retention-worker",
        "status": "ok",
        "health": "/worker/health",
        "run_retention": "/worker/retention/run",
    }


@app.get("/favicon.ico")
def favicon() -> Dict[str, str]:
    return {"status": "no-favicon"}
