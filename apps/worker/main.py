from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import FastAPI

from anpr.infrastructure.settings_manager import SettingsManager
from apps.api.data_lifecycle import DataLifecycleService, RetentionPolicy


class RetentionScheduler:
    def __init__(self, lifecycle: DataLifecycleService) -> None:
        self._lifecycle = lifecycle
        self._task: asyncio.Task[Any] | None = None
        self._last_run: Dict[str, int] | None = None

    async def _loop(self) -> None:
        while True:
            policy = self._lifecycle.policy
            if policy.auto_cleanup_enabled:
                self._last_run = self._lifecycle.run_retention_cycle()
            await asyncio.sleep(max(60, policy.cleanup_interval_minutes * 60))

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    @property
    def last_run(self) -> Dict[str, int] | None:
        return self._last_run


settings = SettingsManager()
storage = settings.get_storage_settings()
policy = RetentionPolicy.from_storage(storage)
lifecycle = DataLifecycleService(
    db_path=settings.get_db_path(),
    screenshots_dir=settings.get_screenshot_dir(),
    policy=policy,
    postgres_dsn=str(storage.get("postgres_dsn", "")).strip(),
)
scheduler = RetentionScheduler(lifecycle)

app = FastAPI(title="ANPR Retention Worker", version="0.8-stage7")


@app.on_event("startup")
async def startup() -> None:
    scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    scheduler.stop()


@app.get("/worker/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "policy": lifecycle.policy.to_storage(),
        "last_run": scheduler.last_run,
    }


@app.post("/worker/retention/run")
def run_retention() -> Dict[str, Any]:
    result = lifecycle.run_retention_cycle()
    return {"status": "ok", **result}


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
