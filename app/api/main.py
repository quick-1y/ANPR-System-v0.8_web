from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from anpr.infrastructure.controller_service import ControllerService
from anpr.infrastructure.list_database import ListDatabase
from anpr.infrastructure.logging_manager import get_logger
from anpr.infrastructure.settings_manager import SettingsManager
from anpr.infrastructure.storage import PostgresEventDatabase, StorageUnavailableError
from app.api.data_lifecycle import DataLifecycleService, RetentionPolicy
from packages.anpr_core.channel_runtime import ChannelProcessor
from packages.anpr_core.event_bus import EventBus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "app" / "web"
logger = get_logger(__name__)


class ChannelPayload(BaseModel):
    name: str
    source: str
    enabled: bool = True
    roi_enabled: bool = True
    region: Dict[str, Any] | None = None


class ROIRegionPayload(BaseModel):
    unit: str = Field(default="percent", pattern="^(px|percent)$")
    points: List[Dict[str, float]] = Field(default_factory=list)


class PlateSizePayload(BaseModel):
    width: int = Field(ge=1, le=4000)
    height: int = Field(ge=1, le=4000)


class ChannelConfigPayload(BaseModel):
    name: str
    source: str
    enabled: bool = True
    controller_id: Optional[int] = None
    controller_relay: int = Field(default=0, ge=0, le=1)
    controller_action: str = Field(default="on", pattern="^(on|off|pulse)$")
    list_filter_mode: str = Field(default="all", pattern="^(all|whitelist|custom)$")
    list_filter_list_ids: List[int] = Field(default_factory=list)
    detection_mode: str = Field(default="motion", pattern="^(always|motion)$")
    motion_threshold: float = Field(default=0.01, ge=0.0, le=1.0)
    motion_frame_stride: int = Field(default=1, ge=1, le=30)
    motion_activation_frames: int = Field(default=3, ge=1, le=120)
    motion_release_frames: int = Field(default=6, ge=1, le=120)
    detector_frame_stride: int = Field(default=2, ge=1, le=30)
    size_filter_enabled: bool = True
    min_plate_size: PlateSizePayload = Field(default_factory=lambda: PlateSizePayload(width=80, height=20))
    max_plate_size: PlateSizePayload = Field(default_factory=lambda: PlateSizePayload(width=600, height=240))
    best_shots: int = Field(default=3, ge=1, le=20)
    cooldown_seconds: int = Field(default=5, ge=0, le=300)
    ocr_min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    roi_enabled: bool = True
    region: ROIRegionPayload = Field(default_factory=ROIRegionPayload)


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



class ExportBundlePayload(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    channel: Optional[str] = None
    include_media: bool = True


class ReconnectSignalLossPayload(BaseModel):
    enabled: bool = True
    frame_timeout_seconds: int = Field(default=5, ge=1, le=300)
    retry_interval_seconds: int = Field(default=5, ge=1, le=300)


class ReconnectPeriodicPayload(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=1, le=1440)


class ReconnectPayload(BaseModel):
    signal_loss: ReconnectSignalLossPayload
    periodic: ReconnectPeriodicPayload


class StoragePayload(BaseModel):
    postgres_dsn: Optional[str] = None
    screenshots_dir: str
    logs_dir: str
    auto_cleanup_enabled: bool
    cleanup_interval_minutes: int = Field(ge=1, le=1440)
    events_retention_days: int = Field(ge=1, le=3650)
    media_retention_days: int = Field(ge=1, le=3650)
    max_screenshots_mb: int = Field(ge=128, le=1024 * 1024)
    export_dir: str


class LoggingPayload(BaseModel):
    level: str = Field(pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    retention_days: int = Field(ge=1, le=3650)


class TimePayload(BaseModel):
    timezone: str
    offset_minutes: int = Field(ge=-720, le=720)


class PlatesPayload(BaseModel):
    config_dir: str
    enabled_countries: List[str] = Field(default_factory=list)


class DebugPayload(BaseModel):
    show_detection_boxes: bool = False
    show_ocr_text: bool = False
    show_direction_tracks: bool = False
    show_channel_metrics: bool = True
    log_panel_enabled: bool = False


class GlobalSettingsPayload(BaseModel):
    grid: str
    theme: str
    reconnect: ReconnectPayload
    storage: StoragePayload
    logging: LoggingPayload
    time: TimePayload
    plates: PlatesPayload
    debug: DebugPayload


settings = SettingsManager()


def _create_events_db() -> PostgresEventDatabase:
    storage = settings.get_storage_settings()
    return PostgresEventDatabase(str(storage.get("postgres_dsn", "")).strip())


events_db = _create_events_db()
lists_db = ListDatabase(str(settings.get_storage_settings().get("postgres_dsn", "")).strip())
controller_service = ControllerService()
event_bus = EventBus()
MAIN_LOOP: asyncio.AbstractEventLoop | None = None
STREAM_SHUTDOWN = asyncio.Event()


def _create_processor() -> ChannelProcessor:
    return ChannelProcessor(
        event_callback=_publish_event_sync,
        plate_settings=settings.get_plate_settings(),
        storage_settings=settings.get_storage_settings(),
    )


def _build_lifecycle() -> DataLifecycleService:
    storage = settings.get_storage_settings()
    policy = RetentionPolicy.from_storage(storage)
    return DataLifecycleService(
        screenshots_dir=settings.get_screenshot_dir(),
        policy=policy,
        postgres_dsn=str(storage.get("postgres_dsn", "")).strip(),
    )




def _storage_503(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"PostgreSQL недоступен: {exc}")


def _db_status() -> Dict[str, Any]:
    try:
        events_db.fetch_recent(limit=1)
        return {"status": "ok", "backend": "postgresql"}
    except StorageUnavailableError as exc:
        return {"status": "degraded", "backend": "postgresql", "detail": str(exc)}

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


def _restart_channel_if_running(channel_id: int) -> None:
    metric = processor.list_states().get(channel_id)
    if metric and metric.state == "running":
        processor.restart(channel_id)


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
    STREAM_SHUTDOWN.clear()
    for channel in settings.get_channels():
        processor.ensure_channel(channel)
        if channel.get("enabled", True):
            processor.start(int(channel["id"]))


@app.on_event("shutdown")
def shutdown_channels() -> None:
    STREAM_SHUTDOWN.set()
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


@app.get("/api/storage/status")
def storage_status() -> Dict[str, Any]:
    return _db_status()


@app.get("/api/system/resources")
def system_resources() -> Dict[str, float]:
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": float(psutil.cpu_percent(interval=None)),
        "ram_percent": float(vm.percent),
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


@app.get("/api/channels/{channel_id}/snapshot.jpg")
def channel_snapshot(channel_id: int) -> Response:
    channels = {int(item["id"]): item for item in settings.get_channels()}
    if channel_id not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")

    frame, _ = processor.get_preview_frame(channel_id)
    if not frame:
        metrics = processor.list_states().get(channel_id)
        detail = "Preview кадр ещё не готов"
        if metrics and metrics.last_error:
            detail = f"Preview недоступен: {metrics.last_error}"
        raise HTTPException(status_code=503, detail=detail)
    return Response(content=frame, media_type="image/jpeg")


@app.get("/api/channels/{channel_id}/preview/status")
def channel_preview_status(channel_id: int) -> Dict[str, Any]:
    channels = {int(item["id"]): item for item in settings.get_channels()}
    if channel_id not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")

    metrics = processor.list_states().get(channel_id)
    frame, frame_ts = processor.get_preview_frame(channel_id)
    return {
        "channel_id": channel_id,
        "state": metrics.state if metrics else "unknown",
        "preview_ready": bool(frame),
        "last_frame_unix": frame_ts,
        "last_frame_at": metrics.preview_last_frame_at if metrics else None,
        "last_error": metrics.last_error if metrics else None,
    }


@app.get("/api/channels/{channel_id}/preview.mjpg")
async def channel_preview_stream(channel_id: int, request: Request) -> StreamingResponse:
    channels = {int(item["id"]): item for item in settings.get_channels()}
    if channel_id not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")

    async def frame_generator():
        last_ts = 0.0
        while not STREAM_SHUTDOWN.is_set():
            if await request.is_disconnected():
                break
            frame, frame_ts = processor.get_preview_frame(channel_id)
            if frame and frame_ts > last_ts:
                last_ts = frame_ts
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                    + frame
                    + b"\r\n"
                )
            else:
                await asyncio.sleep(0.08)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


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

    saved_channel = next(
        (item for item in settings.get_channels() if int(item.get("id", 0)) == next_id),
        None,
    )
    if saved_channel is None:
        raise HTTPException(status_code=500, detail="Не удалось сохранить канал")

    processor.ensure_channel(saved_channel)
    if saved_channel.get("enabled", True):
        processor.start(next_id)
    return saved_channel


@app.put("/api/channels/{channel_id}")
def update_channel(channel_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    channels = settings.get_channels()
    for idx, channel in enumerate(channels):
        if int(channel["id"]) == channel_id:
            was_enabled = bool(channels[idx].get("enabled", True))
            channels[idx].update(payload)
            settings.save_channels(channels)
            processor.ensure_channel(channels[idx])
            if "enabled" in payload:
                if bool(channels[idx].get("enabled", True)):
                    processor.start(channel_id)
                else:
                    processor.stop(channel_id)
            else:
                _restart_channel_if_running(channel_id)
            return channels[idx]
    raise HTTPException(status_code=404, detail="Канал не найден")


@app.get("/api/channels/{channel_id}/config")
def get_channel_config(channel_id: int) -> Dict[str, Any]:
    for channel in settings.get_channels():
        if int(channel.get("id", 0)) == channel_id:
            return channel
    raise HTTPException(status_code=404, detail="Канал не найден")


@app.put("/api/channels/{channel_id}/config")
def put_channel_config(channel_id: int, payload: ChannelConfigPayload) -> Dict[str, Any]:
    data = payload.model_dump()
    data["min_plate_size"] = payload.min_plate_size.model_dump()
    data["max_plate_size"] = payload.max_plate_size.model_dump()
    data["region"] = payload.region.model_dump()
    return update_channel(channel_id, data)


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
    try:
        rows = events_db.fetch_recent(limit=limit)
        return [dict(row) for row in rows]
    except StorageUnavailableError as exc:
        raise _storage_503(exc) from exc


def _fetch_event_by_id(event_id: int) -> Dict[str, Any] | None:
    try:
        row = events_db.fetch_by_id(event_id)
    except StorageUnavailableError as exc:
        raise _storage_503(exc) from exc
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)


@app.get("/api/events/item/{event_id}")
def get_event(event_id: int) -> Dict[str, Any]:
    event = _fetch_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    return event


@app.get("/api/events/item/{event_id}/media/{kind}")
def get_event_media(event_id: int, kind: str) -> FileResponse:
    event = _fetch_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    if kind not in {"frame", "plate"}:
        raise HTTPException(status_code=400, detail="kind должен быть frame или plate")
    media_path = str(event.get("frame_path" if kind == "frame" else "plate_path") or "").strip()
    if not media_path:
        raise HTTPException(status_code=404, detail="Изображение для события отсутствует")
    path_obj = Path(media_path)
    if not path_obj.is_file():
        raise HTTPException(status_code=404, detail="Файл изображения не найден")
    return FileResponse(path=path_obj, media_type="image/jpeg")


@app.get("/api/events/stream")
async def stream_events(request: Request) -> StreamingResponse:
    queue = await event_bus.subscribe()

    async def generator():
        started_at = time.monotonic()
        max_stream_seconds = 3.0
        try:
            while not STREAM_SHUTDOWN.is_set():
                if await request.is_disconnected():
                    break
                if (time.monotonic() - started_at) >= max_stream_seconds:
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
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
    try:
        return lists_db.list_lists()
    except StorageUnavailableError as exc:
        raise _storage_503(exc) from exc


@app.post("/api/lists")
def create_plate_list(payload: ListPayload) -> Dict[str, Any]:
    try:
        list_id = lists_db.create_list(payload.name, payload.type)
        return {"id": list_id, "name": payload.name, "type": payload.type}
    except StorageUnavailableError as exc:
        raise _storage_503(exc) from exc


@app.get("/api/lists/{list_id}/entries")
def list_entries(list_id: int) -> List[Dict[str, Any]]:
    try:
        return lists_db.list_entries(list_id)
    except StorageUnavailableError as exc:
        raise _storage_503(exc) from exc


@app.post("/api/lists/{list_id}/entries")
def add_entry(list_id: int, payload: EntryPayload) -> Dict[str, Any]:
    try:
        entry_id = lists_db.add_entry(list_id=list_id, plate=payload.plate, comment=payload.comment)
        if not entry_id:
            raise HTTPException(status_code=409, detail="Номер уже существует или пуст")
        return {"id": entry_id}
    except StorageUnavailableError as exc:
        raise _storage_503(exc) from exc


@app.get("/api/data/policy")
def get_data_policy() -> Dict[str, Any]:
    return lifecycle.policy.to_storage()


@app.put("/api/data/policy")
def update_data_policy(payload: RetentionPolicyPayload) -> Dict[str, Any]:
    policy = RetentionPolicy(**payload.model_dump())
    lifecycle.update_policy(policy)
    settings.save_storage_settings(policy.to_storage())
    return {"status": "updated", "policy": policy.to_storage()}


@app.get("/api/settings")
def get_global_settings() -> Dict[str, Any]:
    return {
        "grid": settings.get_grid(),
        "theme": settings.get_theme(),
        "reconnect": settings.get_reconnect(),
        "storage": settings.get_storage_settings(),
        "logging": settings.get_logging_config(),
        "time": settings.get_time_settings(),
        "plates": settings.get_plate_settings(),
        "debug": settings.get_debug_settings(),
    }


@app.put("/api/settings")
def put_global_settings(payload: GlobalSettingsPayload) -> Dict[str, Any]:
    settings.save_grid(payload.grid)
    settings.save_theme(payload.theme)
    settings.save_reconnect(payload.reconnect.model_dump())
    settings.save_storage_settings(payload.storage.model_dump())
    settings.save_time_settings(payload.time.model_dump())
    settings.save_plate_settings(payload.plates.model_dump())
    settings.save_debug_settings(payload.debug.model_dump())
    settings.save_logging_config(payload.logging.model_dump())

    global events_db, lifecycle, lists_db
    events_db = _create_events_db()
    lifecycle = _build_lifecycle()
    lists_db = ListDatabase(str(settings.get_storage_settings().get("postgres_dsn", "")).strip())
    _restart_processor_for_settings()
    return get_global_settings()


@app.post("/api/data/retention/run")
def run_retention() -> Dict[str, Any]:
    try:
        result = lifecycle.run_retention_cycle()
        return {"status": "ok", **result}
    except StorageUnavailableError as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/api/data/export/events.csv")
def export_events_csv(start: Optional[str] = None, end: Optional[str] = None, channel: Optional[str] = None) -> FileResponse:
    try:
        path = lifecycle.export_events_csv(start=start, end=end, channel=channel)
        return FileResponse(path=path, filename=Path(path).name, media_type="text/csv")
    except StorageUnavailableError as exc:
        raise _storage_503(exc) from exc


@app.post("/api/data/export/bundle")
def export_events_bundle(payload: ExportBundlePayload) -> FileResponse:
    try:
        path = lifecycle.export_events_bundle(
            start=payload.start,
            end=payload.end,
            channel=payload.channel,
            include_media=payload.include_media,
        )
        return FileResponse(path=path, filename=Path(path).name, media_type="application/zip")
    except StorageUnavailableError as exc:
        raise _storage_503(exc) from exc
