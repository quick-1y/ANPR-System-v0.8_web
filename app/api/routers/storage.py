from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.api.container import AppContainer
from app.api.deps import get_container

router = APIRouter()


@router.get("/api/storage/status")
def storage_status(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    return container.db_status()
