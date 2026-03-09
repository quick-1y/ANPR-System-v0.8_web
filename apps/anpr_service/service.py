from __future__ import annotations

from typing import Any, Callable, Dict

from anpr.infrastructure.settings_manager import SettingsManager
from anpr.infrastructure.storage import PostgresEventDatabase
from packages.anpr_core.channel_runtime import ChannelProcessor
from packages.anpr_core.config import ANPRConfig
from packages.anpr_core.ports import EventSinkPort


class PostgresEventSinkAdapter(EventSinkPort):
    def __init__(self, postgres_dsn: str) -> None:
        self._db = PostgresEventDatabase(postgres_dsn)

    def insert_event(self, **kwargs: Any) -> int:
        return self._db.insert_event(**kwargs)


class ANPRService:
    def __init__(self, settings: SettingsManager, event_callback: Callable[[Dict[str, Any]], None]) -> None:
        self._settings = settings
        self._event_callback = event_callback
        self.processor = self._build_processor()

    def _build_sink(self) -> EventSinkPort:
        storage = self._settings.get_storage_settings()
        return PostgresEventSinkAdapter(str(storage.get("postgres_dsn", "")).strip())

    def _build_anpr_config(self) -> ANPRConfig:
        return self._settings.get_anpr_config()

    def _build_processor(self) -> ChannelProcessor:
        return ChannelProcessor(
            event_callback=self._event_callback,
            anpr_config=self._build_anpr_config(),
            sink=self._build_sink(),
        )

    def sync_channels(self) -> None:
        for channel in self._settings.get_channels():
            self.processor.ensure_channel(channel)

    def start_enabled_channels(self) -> None:
        for channel in self._settings.get_channels():
            if channel.get("enabled", True):
                self.processor.start(int(channel["id"]))

    def rebuild_processor(self) -> ChannelProcessor:
        self.processor = self._build_processor()
        return self.processor
