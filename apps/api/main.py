from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from anpr.infrastructure.controller_service import ControllerService
from anpr.infrastructure.list_database import ListDatabase
from anpr.infrastructure.logging_manager import get_logger
from anpr.infrastructure.settings_manager import SettingsManager
from anpr.infrastructure.storage import EventDatabase, PostgresEventDatabase
from apps.api.data_lifecycle import DataLifecycleService, RetentionPolicy
from packages.anpr_core.channel_runtime import ChannelProcessor
from packages.anpr_core.event_bus import EventBus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "apps" / "web"
logger = get_logger(__name__)


class ChannelPayload(BaseModel):
    name: str
    source: str
    enabled: bool = True
    roi_enabled: bool = True
    region: Dict[str, Any] | None = None


class ChannelOCRPayload(BaseModel):
    best_shots: int = Field(ge=1, le=20)
    cooldown_seconds: int = Field(ge=0, le=300)
    ocr_min_confidence: float = Field(ge=0.0, le=1.0)


class ChannelFilterPayload(BaseModel):
    list_filter_mode: str = Field(pattern="^(all|whitelist|custom)$")
    list_filter_list_ids: List[int] = []
    size_filter_enabled: bool = True
    min_plate_size: Dict[str, int] = {"width": 80, "height": 20}
    max_plate_size: Dict[str, int] = {"width": 600, "height": 240}


class ControllerPayload(BaseModel):
    name: str
    type: str = "DTWONDER2CH"
    address: str
    password: str = "0"
    relays: List[Dict[str, Any]]


class ControllerTestPayload(BaseModel):
    relay_index: int = Field(ge=0, le=1)
    is_on: bool = True


class ListPayload(BaseModel):
    name: str
    type: str = "white"


class EntryPayload(BaseModel):
    plate: str
    comment: str = ""


class RetentionPolicyPayload(BaseModel):
    auto_cleanup_enabled: bool = True
    cleanup_interval_minutes: int = 30
    events_retention_days: int = 30
    media_retention_days: int = 14
    max_screenshots_mb: int = 4096
    export_dir: str = "data/exports"


class DualWritePayload(BaseModel):
    dual_write_enabled: bool = False
    postgres_dsn: str = ""


class ExportBundlePayload(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    channel: Optional[str] = None
    include_media: bool = True


settings = SettingsManager()


def _create_events_db() -> EventDatabase | PostgresEventDatabase:
    storage = settings.get_storage_settings()
    postgres_dsn = str(storage.get("postgres_dsn", "")).strip()
    if postgres_dsn:
        try:
            return PostgresEventDatabase(postgres_dsn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PostgreSQL недоступен, fallback на SQLite events DB: %s", exc)
    return EventDatabase(settings.get_db_path())


events_db = _create_events_db()
lists_db = ListDatabase(settings.get_db_path())
controller_service = ControllerService()
event_bus = EventBus()
MAIN_LOOP: asyncio.AbstractEventLoop | None = None


def _create_processor() -> ChannelProcessor:
    return ChannelProcessor(
        event_callback=_publish_event_sync,
        db_path=settings.get_db_path(),
        plate_settings=settings.get_plate_settings(),
        storage_settings=settings.get_storage_settings(),
    )


def _build_lifecycle() -> DataLifecycleService:
    storage = settings.get_storage_settings()
    policy = RetentionPolicy.from_storage(storage)
    return DataLifecycleService(
        db_path=settings.get_db_path(),
        screenshots_dir=settings.get_screenshot_dir(),
        policy=policy,
        postgres_dsn=str(storage.get("postgres_dsn", "")).strip(),
    )


def _publish_event_sync(event: Dict[str, Any]) -> None:
    if MAIN_LOOP and MAIN_LOOP.is_running():
        MAIN_LOOP.call_soon_threadsafe(asyncio.create_task, event_bus.publish(event))


def _restart_processor_for_settings() -> None:
    global processor
    channels = settings.get_channels()
    enabled_ids = [int(item["id"]) for item in channels if item.get("enabled", True)]
    for channel in channels:
        try:
            processor.stop(int(channel["id"]))
        except Exception:
            pass
    processor = _create_processor()
    for channel in channels:
        processor.ensure_channel(channel)
    for channel_id in enabled_ids:
        processor.start(channel_id)


processor = _create_processor()
lifecycle = _build_lifecycle()

app = FastAPI(title="ANPR Core API", version="0.8-stage8")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


@app.on_event("startup")
async def bootstrap_channels() -> None:
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    for channel in settings.get_channels():
        processor.ensure_channel(channel)
        if channel.get("enabled", True):
            processor.start(int(channel["id"]))


@app.on_event("shutdown")
def shutdown_channels() -> None:
    for channel in settings.get_channels():
        processor.stop(int(channel["id"]))


@app.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    metrics = processor.list_states()
    return {
        "status": "ok",
        "channels_total": len(settings.get_channels()),
        "channels_running": sum(1 for item in metrics.values() if item.state == "running"),
    }


@app.get("/api/channels")
def list_channels() -> List[Dict[str, Any]]:
    channels = settings.get_channels()
    metrics = processor.list_states()
    for channel in channels:
        channel_metrics = metrics.get(int(channel["id"]))
        if channel_metrics:
            channel["metrics"] = channel_metrics.__dict__
    return channels


@app.get("/api/channels/{channel_id}/health")
def channel_health(channel_id: int) -> Dict[str, Any]:
    channels = {int(item["id"]): item for item in settings.get_channels()}
    if channel_id not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")
    metrics = processor.list_states().get(channel_id)
    return {
        "channel": channels[channel_id],
        "metrics": metrics.__dict__ if metrics else {"state": "unknown"},
    }

@app.get("/api/telemetry/channels")
def channels_telemetry() -> List[Dict[str, Any]]:
    channels = {int(item["id"]): item for item in settings.get_channels()}
    metrics = processor.list_states()
    items: List[Dict[str, Any]] = []
    for channel_id, metric in metrics.items():
        items.append(
            {
                "channel_id": channel_id,
                "name": channels.get(channel_id, {}).get("name", f"channel-{channel_id}"),
                "state": metric.state,
                "fps": metric.fps,
                "latency_ms": metric.latency_ms,
                "reconnect_count": metric.reconnect_count,
                "timeout_count": metric.timeout_count,
                "error_count": metric.error_count,
                "last_event_at": metric.last_event_at,
                "last_error": metric.last_error,
            }
        )
    return items


@app.post("/api/channels")
def create_channel(payload: ChannelPayload) -> Dict[str, Any]:
    channels = settings.get_channels()
    next_id = max([int(item.get("id", 0)) for item in channels] + [0]) + 1
    channel = {
        "id": next_id,
        "name": payload.name,
        "source": payload.source,
        "enabled": payload.enabled,
        "roi_enabled": payload.roi_enabled,
        "region": payload.region or {"unit": "percent", "points": []},
    }
    channels.append(channel)
    settings.save_channels(channels)
    processor.ensure_channel(channel)
    return channel


@app.put("/api/channels/{channel_id}")
def update_channel(channel_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    channels = settings.get_channels()
    for idx, channel in enumerate(channels):
        if int(channel["id"]) == channel_id:
            channels[idx].update(payload)
            settings.save_channels(channels)
            processor.ensure_channel(channels[idx])
            return channels[idx]
    raise HTTPException(status_code=404, detail="Канал не найден")


@app.put("/api/channels/{channel_id}/ocr")
def update_channel_ocr(channel_id: int, payload: ChannelOCRPayload) -> Dict[str, Any]:
    return update_channel(channel_id, payload.model_dump())


@app.put("/api/channels/{channel_id}/filter")
def update_channel_filter(channel_id: int, payload: ChannelFilterPayload) -> Dict[str, Any]:
    return update_channel(channel_id, payload.model_dump())


@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: int) -> Dict[str, str]:
    channels = [item for item in settings.get_channels() if int(item["id"]) != channel_id]
    settings.save_channels(channels)
    processor.remove_channel(channel_id)
    return {"status": "deleted"}


@app.post("/api/channels/{channel_id}/start")
def start_channel(channel_id: int) -> Dict[str, str]:
    processor.start(channel_id)
    return {"status": "running"}


@app.post("/api/channels/{channel_id}/stop")
def stop_channel(channel_id: int) -> Dict[str, str]:
    processor.stop(channel_id)
    return {"status": "stopped"}


@app.post("/api/channels/{channel_id}/restart")
def restart_channel(channel_id: int) -> Dict[str, str]:
    processor.restart(channel_id)
    return {"status": "restarted"}


@app.get("/api/events")
def list_events(limit: int = 100) -> List[Dict[str, Any]]:
    rows = events_db.fetch_recent(limit=limit)
    return [dict(row) for row in rows]


@app.get("/api/events/stream")
async def stream_events() -> StreamingResponse:
    queue = await event_bus.subscribe()

    async def generator():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await event_bus.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/controllers")
def list_controllers() -> List[Dict[str, Any]]:
    return settings.get_controllers()


@app.post("/api/controllers")
def create_controller(payload: ControllerPayload) -> Dict[str, Any]:
    controllers = settings.get_controllers()
    next_id = max([int(item.get("id", 0)) for item in controllers] + [0]) + 1
    controller = {"id": next_id, **payload.model_dump()}
    controllers.append(controller)
    settings.save_controllers(controllers)
    return controller


@app.put("/api/controllers/{controller_id}")
def update_controller(controller_id: int, payload: ControllerPayload) -> Dict[str, Any]:
    controllers = settings.get_controllers()
    for idx, controller in enumerate(controllers):
        if int(controller.get("id", 0)) == controller_id:
            controllers[idx].update(payload.model_dump())
            settings.save_controllers(controllers)
            return controllers[idx]
    raise HTTPException(status_code=404, detail="Контроллер не найден")


@app.delete("/api/controllers/{controller_id}")
def delete_controller(controller_id: int) -> Dict[str, str]:
    controllers = [item for item in settings.get_controllers() if int(item.get("id", 0)) != controller_id]
    settings.save_controllers(controllers)
    return {"status": "deleted"}


@app.post("/api/controllers/{controller_id}/test")
def test_controller(controller_id: int, payload: ControllerTestPayload) -> Dict[str, Any]:
    for controller in settings.get_controllers():
        if int(controller.get("id", 0)) == controller_id:
            url = controller_service.send_command(controller, payload.relay_index, payload.is_on, reason="api-test")
            return {"status": "sent" if url else "skipped", "url": url}
    raise HTTPException(status_code=404, detail="Контроллер не найден")


@app.get("/api/lists")
def list_plate_lists() -> List[Dict[str, Any]]:
    return lists_db.list_lists()


@app.post("/api/lists")
def create_plate_list(payload: ListPayload) -> Dict[str, Any]:
    list_id = lists_db.create_list(payload.name, payload.type)
    return {"id": list_id, "name": payload.name, "type": payload.type}


@app.get("/api/lists/{list_id}/entries")
def list_entries(list_id: int) -> List[Dict[str, Any]]:
    return lists_db.list_entries(list_id)


@app.post("/api/lists/{list_id}/entries")
def add_entry(list_id: int, payload: EntryPayload) -> Dict[str, Any]:
    entry_id = lists_db.add_entry(list_id=list_id, plate=payload.plate, comment=payload.comment)
    if not entry_id:
        raise HTTPException(status_code=409, detail="Номер уже существует или пуст")
    return {"id": entry_id}


@app.get("/api/data/policy")
def get_data_policy() -> Dict[str, Any]:
    return lifecycle.policy.to_storage()


@app.put("/api/data/policy")
def update_data_policy(payload: RetentionPolicyPayload) -> Dict[str, Any]:
    policy = RetentionPolicy(**payload.model_dump())
    lifecycle.update_policy(policy)
    settings.save_storage_settings(policy.to_storage())
    return {"status": "updated", "policy": policy.to_storage()}


@app.get("/api/storage/dual-write")
def get_dual_write() -> Dict[str, Any]:
    storage = settings.get_storage_settings()
    return {
        "dual_write_enabled": bool(storage.get("dual_write_enabled", False)),
        "postgres_dsn": str(storage.get("postgres_dsn", "")),
        "postgres_primary": bool(str(storage.get("postgres_dsn", "")).strip()),
    }


@app.put("/api/storage/dual-write")
def update_dual_write(payload: DualWritePayload) -> Dict[str, Any]:
    if not payload.postgres_dsn.strip():
        raise HTTPException(status_code=422, detail="postgres_dsn обязателен: PostgreSQL является primary backend")
    settings.save_storage_settings(payload.model_dump())
    _restart_processor_for_settings()
    global events_db, lifecycle
    events_db = _create_events_db()
    lifecycle = _build_lifecycle()
    return {"status": "updated", **payload.model_dump(), "postgres_primary": True}


@app.post("/api/data/retention/run")
def run_retention() -> Dict[str, Any]:
    result = lifecycle.run_retention_cycle()
    return {"status": "ok", **result}


@app.get("/api/data/export/events.csv")
def export_events_csv(start: Optional[str] = None, end: Optional[str] = None, channel: Optional[str] = None) -> FileResponse:
    path = lifecycle.export_events_csv(start=start, end=end, channel=channel)
    return FileResponse(path=path, filename=Path(path).name, media_type="text/csv")


@app.post("/api/data/export/bundle")
def export_events_bundle(payload: ExportBundlePayload) -> FileResponse:
    path = lifecycle.export_events_bundle(
        start=payload.start,
        end=payload.end,
        channel=payload.channel,
        include_media=payload.include_media,
    )
    return FileResponse(path=path, filename=Path(path).name, media_type="application/zip")
