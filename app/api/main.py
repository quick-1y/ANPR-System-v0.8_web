from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.container import AppContainer, WEB_DIR
from app.api.routers.channels import router as channels_router
from app.api.routers.controllers import router as controllers_router
from app.api.routers.debug import router as debug_router
from app.api.routers.events import router as events_router
from app.api.routers.lists import router as lists_router
from app.api.routers.settings import router as settings_router
from app.api.routers.storage import router as storage_router
from app.api.routers.system import router as system_router


app = FastAPI(title="ANPR Core API", version="0.8-stage8")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

app.include_router(system_router)
app.include_router(storage_router)
app.include_router(channels_router)
app.include_router(events_router)
app.include_router(debug_router)
app.include_router(controllers_router)
app.include_router(lists_router)
app.include_router(settings_router)


@app.on_event("startup")
async def startup() -> None:
    container = AppContainer.build()
    await container.startup()
    app.state.container = container


@app.on_event("shutdown")
def shutdown() -> None:
    container: AppContainer | None = getattr(app.state, "container", None)
    if container is not None:
        container.shutdown()
