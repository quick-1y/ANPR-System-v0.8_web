from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import DebugPayload

router = APIRouter()


@router.get("/api/debug/settings")
def get_debug_settings(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return container.processor.get_debug_settings()


@router.put("/api/debug/settings")
def put_debug_settings(payload: DebugPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    body = payload.model_dump()
    container.settings.save_debug_settings(body)
    return container.processor.update_debug_settings(body)


@router.get("/api/debug/channels")
def debug_channels(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    metrics = container.processor.list_states()
    states = container.processor.list_debug_states()
    return {
        "settings": container.processor.get_debug_settings(),
        "channels": [
            {
                "channel_id": channel_id,
                "metrics": metric.__dict__,
                "debug_state": states.get(channel_id, {}),
            }
            for channel_id, metric in metrics.items()
        ],
    }


@router.get("/api/debug/state")
def debug_state(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return {
        "settings": container.processor.get_debug_settings(),
        "channel_states": container.processor.list_debug_states(),
    }


@router.get("/api/debug/logs")
def debug_logs(limit: int = 200, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return {"items": container.debug_log_bus.snapshot(limit=limit)}


@router.get("/api/debug/logs/stream")
async def stream_debug_logs(request: Request, last_id: int = 0, container: AppContainer = Depends(get_container)) -> StreamingResponse:
    async def generator():
        cursor = max(0, int(last_id))
        yield "retry: 2000\n\n"
        while not container.stream_shutdown.is_set():
            if await request.is_disconnected():
                break
            items = await asyncio.to_thread(container.debug_log_bus.wait_for_entries, cursor, 15.0)
            if not items:
                yield ": ping\n\n"
                continue
            for item in items:
                cursor = max(cursor, int(item.get("id", cursor)))
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
