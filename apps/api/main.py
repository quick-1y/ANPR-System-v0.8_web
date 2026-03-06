from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from anpr.infrastructure.list_database import ListDatabase
from anpr.infrastructure.settings_manager import SettingsManager
from anpr.infrastructure.storage import EventDatabase
from apps.api.data_lifecycle import DataLifecycleService, RetentionPolicy
from packages.anpr_core.channel_runtime import ChannelProcessor
from packages.anpr_core.event_bus import EventBus


class ChannelPayload(BaseModel):
    name: str
    source: str
    enabled: bool = True
    roi_enabled: bool = True
    region: Dict[str, Any] | None = None


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


settings = SettingsManager()
events_db = EventDatabase(settings.get_db_path())
lists_db = ListDatabase(settings.get_db_path())
event_bus = EventBus()
MAIN_LOOP: asyncio.AbstractEventLoop | None = None
RETENTION_TASK: asyncio.Task[Any] | None = None


def _build_lifecycle() -> DataLifecycleService:
    policy = RetentionPolicy.from_storage(settings.get_storage_settings())
    return DataLifecycleService(
        db_path=settings.get_db_path(),
        screenshots_dir=settings.get_screenshot_dir(),
        policy=policy,
    )


def _publish_event_sync(event: Dict[str, Any]) -> None:
    if MAIN_LOOP and MAIN_LOOP.is_running():
        MAIN_LOOP.call_soon_threadsafe(asyncio.create_task, event_bus.publish(event))


processor = ChannelProcessor(event_callback=_publish_event_sync, db_path=settings.get_db_path(), plate_settings=settings.get_plate_settings())
lifecycle = _build_lifecycle()


app = FastAPI(title="ANPR Core API", version="0.8-stage6")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/web", StaticFiles(directory="apps/web", html=True), name="web")


async def retention_loop() -> None:
    while True:
        policy = lifecycle.policy
        if policy.auto_cleanup_enabled:
            lifecycle.run_retention_cycle()
        await asyncio.sleep(max(60, policy.cleanup_interval_minutes * 60))


@app.on_event("startup")
async def bootstrap_channels() -> None:
    global MAIN_LOOP, RETENTION_TASK
    MAIN_LOOP = asyncio.get_running_loop()
    for channel in settings.get_channels():
        processor.ensure_channel(channel)
        if channel.get("enabled", True):
            processor.start(int(channel["id"]))
    RETENTION_TASK = asyncio.create_task(retention_loop())


@app.on_event("shutdown")
def shutdown_channels() -> None:
    global RETENTION_TASK
    for channel in settings.get_channels():
        processor.stop(int(channel["id"]))
    if RETENTION_TASK:
        RETENTION_TASK.cancel()


@app.get("/")
def root() -> FileResponse:
    return FileResponse(Path("apps/web/index.html"))


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
    return [dict(row) for row in events_db.fetch_recent(limit=limit)]


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
