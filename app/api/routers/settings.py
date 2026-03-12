from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from anpr.infrastructure.storage import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import ExportBundlePayload, GlobalSettingsPayload, RetentionPolicyPayload
from app.shared.data_lifecycle import RetentionPolicy
from common.logging import configure_logging, get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/api/data/policy")
def get_data_policy(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return container.lifecycle.policy.to_storage()


@router.put("/api/data/policy")
def update_data_policy(payload: RetentionPolicyPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    policy = RetentionPolicy(**payload.model_dump())
    container.lifecycle.update_policy(policy)
    container.settings.save_storage_settings(policy.to_storage())
    return {"status": "updated", "policy": policy.to_storage()}


@router.get("/api/settings")
def get_global_settings(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return {
        "grid": container.settings.get_grid(),
        "theme": container.settings.get_theme(),
        "reconnect": container.settings.get_reconnect(),
        "storage": container.settings.get_storage_settings(),
        "logging": container.settings.get_logging_config(),
        "time": container.settings.get_time_settings(),
        "plates": container.settings.get_plate_settings(),
        "debug": container.settings.get_debug_settings(),
    }


@router.put("/api/settings")
def put_global_settings(payload: GlobalSettingsPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    container.settings.save_grid(payload.grid)
    container.settings.save_theme(payload.theme)
    reconnect_config = payload.reconnect.model_dump()
    container.settings.save_reconnect(reconnect_config)
    try:
        container.processor.update_reconnect_settings(reconnect_config)
    except Exception:
        logger.exception("Не удалось обновить reconnect-настройки активного processor")
    container.settings.save_storage_settings(payload.storage.model_dump())
    container.settings.save_time_settings(payload.time.model_dump())
    container.settings.save_plate_settings(payload.plates.model_dump())
    debug_payload = payload.debug.model_dump()
    container.settings.save_debug_settings(debug_payload)
    container.processor.update_debug_settings(debug_payload)
    container.settings.save_logging_config(payload.logging.model_dump())
    configure_logging(container.settings.get_logging_config(), service_name="api")

    container.refresh_storage_clients()
    container.restart_processor_for_settings()
    return get_global_settings(container)


@router.post("/api/data/retention/run")
def run_retention(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        result = container.lifecycle.run_retention_cycle()
        return {"status": "ok", **result}
    except StorageUnavailableError as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/api/data/export/events.csv")
def export_events_csv(
    start: Optional[str] = None,
    end: Optional[str] = None,
    channel: Optional[str] = None,
    container: AppContainer = Depends(get_container),
) -> FileResponse:
    try:
        path = container.lifecycle.export_events_csv(start=start, end=end, channel=channel)
        return FileResponse(path=path, filename=Path(path).name, media_type="text/csv")
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/data/export/bundle")
def export_events_bundle(payload: ExportBundlePayload, container: AppContainer = Depends(get_container)) -> FileResponse:
    try:
        path = container.lifecycle.export_events_bundle(
            start=payload.start,
            end=payload.end,
            channel=payload.channel,
            include_media=payload.include_media,
        )
        return FileResponse(path=path, filename=Path(path).name, media_type="application/zip")
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
