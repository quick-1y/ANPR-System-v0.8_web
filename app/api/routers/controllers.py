from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.container import AppContainer
from app.api.deps import get_container
from app.api.schemas import ControllerPayload, ControllerTestPayload

router = APIRouter()


@router.get("/api/controllers")
def list_controllers(container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    return container.settings.get_controllers()


@router.post("/api/controllers")
def create_controller(payload: ControllerPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    controllers = container.settings.get_controllers()
    next_id = max([int(item.get("id", 0)) for item in controllers] + [0]) + 1
    controller = {"id": next_id, **payload.model_dump()}
    controllers.append(controller)
    container.validate_global_hotkeys(controllers)
    container.settings.save_controllers(controllers)
    return controller


@router.put("/api/controllers/{controller_id}")
def update_controller(controller_id: int, payload: ControllerPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    controllers = container.settings.get_controllers()
    for idx, controller in enumerate(controllers):
        if int(controller.get("id", 0)) == controller_id:
            controllers[idx].update(payload.model_dump())
            container.validate_global_hotkeys(controllers)
            container.settings.save_controllers(controllers)
            return controllers[idx]
    raise HTTPException(status_code=404, detail="Контроллер не найден")


@router.delete("/api/controllers/{controller_id}")
def delete_controller(controller_id: int, container: AppContainer = Depends(get_container)) -> Dict[str, str]:
    channels_using_controller = [
        int(channel.get("id", 0))
        for channel in container.settings.get_channels()
        if channel.get("controller_id") is not None and int(channel.get("controller_id", 0)) == controller_id
    ]
    if channels_using_controller:
        used_in = ", ".join(str(item) for item in channels_using_controller)
        raise HTTPException(
            status_code=409,
            detail=f"Контроллер используется в каналах: {used_in}. Сначала отвяжите его в настройках каналов.",
        )
    controllers = [item for item in container.settings.get_controllers() if int(item.get("id", 0)) != controller_id]
    container.settings.save_controllers(controllers)
    return {"status": "deleted"}


@router.post("/api/controllers/{controller_id}/test")
def test_controller(controller_id: int, payload: ControllerTestPayload, container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    for controller in container.settings.get_controllers():
        if int(controller.get("id", 0)) == controller_id:
            url = container.controller_service.send_command(controller, payload.relay_index, payload.is_on, reason="api-test")
            return {"status": "sent" if url else "skipped", "url": url}
    raise HTTPException(status_code=404, detail="Контроллер не найден")
