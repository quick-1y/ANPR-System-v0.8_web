from __future__ import annotations

from typing import Any, Dict, List

import psutil
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.container import AppContainer, WEB_DIR
from app.api.deps import get_container

router = APIRouter()


@router.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@router.get("/api/health")
def health(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    metrics = container.processor.list_states()
    return {
        "status": "ok",
        "channels_total": len(container.settings.get_channels()),
        "channels_running": sum(1 for item in metrics.values() if item.state == "running"),
    }


@router.get("/api/system/resources")
def system_resources() -> Dict[str, float]:
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": float(psutil.cpu_percent(interval=None)),
        "ram_percent": float(vm.percent),
    }


@router.get("/api/telemetry/channels")
def channels_telemetry(container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    channels = {int(item["id"]): item for item in container.settings.get_channels()}
    metrics = container.processor.list_states()
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
