from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from anpr.infrastructure.storage import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container

router = APIRouter()


@router.get("/api/events")
def list_events(limit: int = 100, container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    try:
        rows = container.events_db.fetch_recent(limit=limit)
        return [dict(row) for row in rows]
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


def _fetch_event_by_id(container: AppContainer, event_id: int) -> Dict[str, Any] | None:
    try:
        row = container.events_db.fetch_by_id(event_id)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)


@router.get("/api/events/item/{event_id}")
def get_event(event_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    event = _fetch_event_by_id(container, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    return event


@router.get("/api/events/item/{event_id}/media/{kind}")
def get_event_media(event_id: int, kind: str, container: AppContainer = Depends(get_container)) -> FileResponse:
    event = _fetch_event_by_id(container, event_id)
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


@router.get("/api/events/stream")
async def stream_events(request: Request, container: AppContainer = Depends(get_container)) -> StreamingResponse:
    queue = await container.event_bus.subscribe()

    async def generator():
        try:
            yield "retry: 3000\n\n"
            while not container.stream_shutdown.is_set():
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await container.event_bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
