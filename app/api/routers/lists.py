from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from anpr.infrastructure.storage import StorageUnavailableError
from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import EntryPayload, ListPayload

router = APIRouter()


@router.get("/api/lists")
def list_plate_lists(container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.list_lists()
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/lists")
def create_plate_list(payload: ListPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        list_id = container.lists_db.create_list(payload.name, payload.type)
        return {"id": list_id, "name": payload.name, "type": payload.type}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.get("/api/lists/{list_id}/entries")
def list_entries(list_id: int, container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    try:
        return container.lists_db.list_entries(list_id)
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc


@router.post("/api/lists/{list_id}/entries")
def add_entry(list_id: int, payload: EntryPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    try:
        entry_id = container.lists_db.add_entry(list_id=list_id, plate=payload.plate, comment=payload.comment)
        if not entry_id:
            raise HTTPException(status_code=409, detail="Номер уже существует или пуст")
        return {"id": entry_id}
    except StorageUnavailableError as exc:
        raise container.storage_503(exc) from exc
