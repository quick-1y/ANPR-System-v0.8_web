from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from anpr.infrastructure.storage import StorageUnavailableError
from fastapi.responses import Response, StreamingResponse

from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import ChannelConfigPayload, ChannelFilterPayload, ChannelOCRPayload, ChannelPayload

router = APIRouter()


@router.get("/api/channels")
def list_channels(container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    channels = container.settings.get_channels()
    metrics = container.processor.list_states()
    debug_states = container.processor.list_debug_states()
    for channel in channels:
        channel_id = int(channel["id"])
        channel_metrics = metrics.get(channel_id)
        if channel_metrics:
            channel["metrics"] = channel_metrics.__dict__
        channel["debug_state"] = debug_states.get(channel_id, {})
    return channels


@router.get("/api/channels/last-plates")
def channels_last_plates(container: AppContainer = Depends(get_container)) -> Dict[int, Dict[str, Any]]:
    channel_ids = [int(item.get("id", 0)) for item in container.settings.get_channels() if int(item.get("id", 0)) > 0]
    try:
        return container.events_db.fetch_last_plates_by_channel_ids(channel_ids)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/channels/{channel_id}/snapshot.jpg")
def channel_snapshot(channel_id: int, container: AppContainer = Depends(get_container)) -> Response:
    channels = {int(item["id"]): item for item in container.settings.get_channels()}
    if channel_id not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")

    frame, _ = container.processor.get_preview_frame(channel_id)
    if not frame:
        metrics = container.processor.list_states().get(channel_id)
        detail = "Preview кадр ещё не готов"
        if metrics and metrics.last_error:
            detail = f"Preview недоступен: {metrics.last_error}"
        raise HTTPException(status_code=503, detail=detail)
    return Response(content=frame, media_type="image/jpeg")


@router.get("/api/channels/{channel_id}/preview/status")
def channel_preview_status(channel_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    channels = {int(item["id"]): item for item in container.settings.get_channels()}
    if channel_id not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")

    metrics = container.processor.list_states().get(channel_id)
    frame, frame_ts = container.processor.get_preview_frame(channel_id)
    return {
        "channel_id": channel_id,
        "state": metrics.state if metrics else "unknown",
        "preview_ready": bool(frame),
        "last_frame_unix": frame_ts,
        "last_frame_at": metrics.preview_last_frame_at if metrics else None,
        "last_error": metrics.last_error if metrics else None,
    }


@router.get("/api/channels/{channel_id}/preview.mjpg")
async def channel_preview_stream(channel_id: int, request: Request, container: AppContainer = Depends(get_container)) -> StreamingResponse:
    channels = {int(item["id"]): item for item in container.settings.get_channels()}
    if channel_id not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")

    async def frame_generator():
        last_ts = 0.0
        while not container.stream_shutdown.is_set():
            if await request.is_disconnected():
                break
            frame, frame_ts = container.processor.get_preview_frame(channel_id)
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


@router.get("/api/channels/{channel_id}/health")
def channel_health(channel_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    channels = {int(item["id"]): item for item in container.settings.get_channels()}
    if channel_id not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")
    metrics = container.processor.list_states().get(channel_id)
    return {
        "channel": channels[channel_id],
        "metrics": metrics.__dict__ if metrics else {"state": "unknown"},
    }


@router.post("/api/channels")
def create_channel(payload: ChannelPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    channels = container.settings.get_channels()
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
    container.settings.save_channels(channels)

    saved_channel = next(
        (item for item in container.settings.get_channels() if int(item.get("id", 0)) == next_id),
        None,
    )
    if saved_channel is None:
        raise HTTPException(status_code=500, detail="Не удалось сохранить канал")

    container.processor.ensure_channel(saved_channel)
    container.processor.stop(next_id)
    return saved_channel


@router.put("/api/channels/{channel_id}")
def update_channel(channel_id: int, payload: Dict[str, Any], container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    channels = container.settings.get_channels()
    for idx, channel in enumerate(channels):
        if int(channel["id"]) == channel_id:
            channels[idx].update(payload)
            container.settings.save_channels(channels)
            container.processor.ensure_channel(channels[idx])
            container.sync_channel_runtime(channel_id, bool(channels[idx].get("enabled", True)))
            return channels[idx]
    raise HTTPException(status_code=404, detail="Канал не найден")


@router.get("/api/channels/{channel_id}/config")
def get_channel_config(channel_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    for channel in container.settings.get_channels():
        if int(channel.get("id", 0)) == channel_id:
            return channel
    raise HTTPException(status_code=404, detail="Канал не найден")


@router.put("/api/channels/{channel_id}/config")
def put_channel_config(channel_id: int, payload: ChannelConfigPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    data = payload.model_dump(exclude_none=True)
    data["min_plate_size"] = payload.min_plate_size.model_dump()
    data["max_plate_size"] = payload.max_plate_size.model_dump()
    data["region"] = payload.region.model_dump()
    container.validate_channel_controller_binding(data)
    return update_channel(channel_id, data, container)


@router.put("/api/channels/{channel_id}/ocr")
def update_channel_ocr(channel_id: int, payload: ChannelOCRPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return update_channel(channel_id, payload.model_dump(), container)


@router.put("/api/channels/{channel_id}/filter")
def update_channel_filter(channel_id: int, payload: ChannelFilterPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return update_channel(channel_id, payload.model_dump(), container)


@router.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, str]:
    channels = [item for item in container.settings.get_channels() if int(item["id"]) != channel_id]
    container.settings.save_channels(channels)
    container.processor.remove_channel(channel_id)
    return {"status": "deleted"}


@router.post("/api/channels/{channel_id}/start")
def start_channel(channel_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, str]:
    container.processor.start(channel_id)
    return {"status": "running"}


@router.post("/api/channels/{channel_id}/stop")
def stop_channel(channel_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, str]:
    container.processor.stop(channel_id)
    return {"status": "stopped"}


@router.post("/api/channels/{channel_id}/restart")
def restart_channel(channel_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, str]:
    container.processor.restart(channel_id)
    return {"status": "restarted"}
