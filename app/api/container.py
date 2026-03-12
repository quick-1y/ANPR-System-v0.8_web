from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException

from anpr.infrastructure.list_database import ListDatabase
from anpr.infrastructure.settings_manager import SettingsManager
from anpr.infrastructure.storage import PostgresEventDatabase, StorageUnavailableError
from app.shared.data_lifecycle import DataLifecycleService, RetentionPolicy
from common.logging import configure_logging, get_live_log_bus, get_logger
from controllers import ControllerAutomationService, ControllerService
from packages.anpr_core.debug import DebugRegistry
from packages.anpr_core.event_bus import EventBus

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "app" / "web"


@dataclass
class AppContainer:
    settings: SettingsManager
    events_db: PostgresEventDatabase
    lists_db: ListDatabase
    controller_service: ControllerService
    controller_automation: ControllerAutomationService
    event_bus: EventBus
    debug_registry: DebugRegistry
    debug_log_bus: Any
    processor: Any
    lifecycle: DataLifecycleService
    main_loop: asyncio.AbstractEventLoop | None
    stream_shutdown: asyncio.Event

    @classmethod
    def build(cls) -> "AppContainer":
        settings = SettingsManager()
        configure_logging(settings.get_logging_config(), service_name="api")

        storage = settings.get_storage_settings()
        events_db = PostgresEventDatabase(str(storage.get("postgres_dsn", "")).strip())
        lists_db = ListDatabase(str(storage.get("postgres_dsn", "")).strip())
        controller_service = ControllerService()
        event_bus = EventBus()
        debug_registry = DebugRegistry(settings.get_debug_settings())
        debug_log_bus = get_live_log_bus()

        container = cls(
            settings=settings,
            events_db=events_db,
            lists_db=lists_db,
            controller_service=controller_service,
            controller_automation=None,  # type: ignore[arg-type]
            event_bus=event_bus,
            debug_registry=debug_registry,
            debug_log_bus=debug_log_bus,
            processor=None,  # type: ignore[arg-type]
            lifecycle=None,  # type: ignore[arg-type]
            main_loop=None,
            stream_shutdown=asyncio.Event(),
        )
        container.controller_automation = ControllerAutomationService(
            controller_service,
            get_channels=settings.get_channels,
            get_controllers=settings.get_controllers,
            plate_in_list_type=lists_db.plate_in_list_type,
            plate_in_lists=lists_db.plate_in_lists,
        )
        container.processor = container._create_processor()
        container.lifecycle = container._build_lifecycle()
        return container

    def _create_processor(self) -> Any:
        from packages.anpr_core.channel_runtime import ChannelProcessor

        return ChannelProcessor(
            event_callback=self.publish_event_sync,
            plate_settings=self.settings.get_plate_settings(),
            storage_settings=self.settings.get_storage_settings(),
            reconnect_settings=self.settings.get_reconnect(),
            debug_registry=self.debug_registry,
        )

    def _build_lifecycle(self) -> DataLifecycleService:
        storage = self.settings.get_storage_settings()
        policy = RetentionPolicy.from_storage(storage)
        return DataLifecycleService(
            screenshots_dir=self.settings.get_screenshot_dir(),
            policy=policy,
            postgres_dsn=str(storage.get("postgres_dsn", "")).strip(),
        )

    async def startup(self) -> None:
        self.main_loop = asyncio.get_running_loop()
        self.stream_shutdown.clear()
        for channel in self.settings.get_channels():
            self.processor.ensure_channel(channel)
            if channel.get("enabled", True):
                self.processor.start(int(channel["id"]))

    def shutdown(self) -> None:
        self.stream_shutdown.set()
        for channel in self.settings.get_channels():
            self.processor.stop(int(channel["id"]))

    def storage_503(self, exc: Exception) -> HTTPException:
        return HTTPException(status_code=503, detail=f"PostgreSQL недоступен: {exc}")

    def db_status(self) -> Dict[str, Any]:
        try:
            self.events_db.fetch_recent(limit=1)
            return {"status": "ok", "backend": "postgresql"}
        except StorageUnavailableError as exc:
            return {"status": "degraded", "backend": "postgresql", "detail": str(exc)}

    def publish_event_sync(self, event: Dict[str, Any]) -> None:
        if self.main_loop and self.main_loop.is_running():
            self.main_loop.call_soon_threadsafe(asyncio.create_task, self.event_bus.publish(event))
        self.controller_automation.dispatch_event(event)

    def restart_processor_for_settings(self) -> None:
        channels = self.settings.get_channels()
        enabled_ids = [int(item["id"]) for item in channels if item.get("enabled", True)]
        for channel in channels:
            try:
                self.processor.stop(int(channel["id"]))
            except Exception:
                pass
        self.processor = self._create_processor()
        for channel in channels:
            self.processor.ensure_channel(channel)
        for channel_id in enabled_ids:
            self.processor.start(channel_id)

    def sync_channel_runtime(self, channel_id: int, enabled: bool) -> None:
        metric = self.processor.list_states().get(channel_id)
        is_running = bool(metric and metric.state == "running")
        if not enabled:
            self.processor.stop(channel_id)
            return
        if is_running:
            self.processor.restart(channel_id)
        else:
            self.processor.start(channel_id)

    def controller_exists(self, controller_id: int) -> bool:
        return any(int(item.get("id", 0)) == controller_id for item in self.settings.get_controllers())

    def validate_channel_controller_binding(self, payload: Dict[str, Any]) -> None:
        controller_id = payload.get("controller_id")
        if controller_id is None:
            payload["controller_relay"] = 0
            return
        if not self.controller_exists(int(controller_id)):
            raise HTTPException(status_code=400, detail=f"Контроллер #{controller_id} не найден")

    @staticmethod
    def validate_global_hotkeys(controllers: List[Dict[str, Any]]) -> None:
        bindings: Dict[str, List[str]] = {}
        for controller in controllers:
            controller_name = str(controller.get("name") or controller.get("id") or "unknown")
            for relay_index, relay in enumerate(controller.get("relays") or []):
                hotkey = str(relay.get("hotkey") or "").strip().upper()
                if not hotkey:
                    continue
                bindings.setdefault(hotkey, []).append(f"{controller_name}:relay{relay_index + 1}")
        duplicates = {hotkey: places for hotkey, places in bindings.items() if len(places) > 1}
        if duplicates:
            details = "; ".join(f"{hotkey} -> {', '.join(places)}" for hotkey, places in sorted(duplicates.items()))
            raise HTTPException(
                status_code=422,
                detail=f"Хоткеи должны быть уникальны глобально между всеми контроллерами: {details}",
            )

    def refresh_storage_clients(self) -> None:
        self.events_db = PostgresEventDatabase(str(self.settings.get_storage_settings().get("postgres_dsn", "")).strip())
        self.lifecycle = self._build_lifecycle()
        self.lists_db = ListDatabase(str(self.settings.get_storage_settings().get("postgres_dsn", "")).strip())
        self.controller_automation = ControllerAutomationService(
            self.controller_service,
            get_channels=self.settings.get_channels,
            get_controllers=self.settings.get_controllers,
            plate_in_list_type=self.lists_db.plate_in_list_type,
            plate_in_lists=self.lists_db.plate_in_lists,
        )
