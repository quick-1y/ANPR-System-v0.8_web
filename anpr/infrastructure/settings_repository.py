import copy
import os
import tempfile
import threading
from typing import Any, Dict

import yaml

from common.logging import get_logger
from anpr.infrastructure.settings_migrations import run_settings_migrations
from anpr.infrastructure.settings_schema import SETTINGS_VERSION


logger = get_logger(__name__)


class SettingsRepository:
    _file_lock = threading.RLock()

    def __init__(self, manager: Any, path: str | None = None) -> None:
        self._manager = manager
        self.path = path or os.getenv("SETTINGS_PATH", "config/settings.yaml")
        self.settings = self._load()

    def load(self) -> Dict[str, Any]:
        self.settings = self._load()
        return self.settings

    def save(self, data: Dict[str, Any]) -> None:
        self._save(data)
        self.settings = data

    def _load(self) -> Dict[str, Any]:
        with self._file_lock:
            if not os.path.exists(self.path):
                defaults = self._manager._default()
                self._write_to_disk(defaults)
                return defaults
            with open(self.path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ValueError(f"Некорректный формат {self.path}: ожидается YAML-объект")
        return self._upgrade(data)

    def _upgrade(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Обновляет существующие настройки, добавляя недостающие поля."""

        data, changed = run_settings_migrations(data, SETTINGS_VERSION)
        tracking_defaults = data.get("tracking", {})
        reconnect_defaults = self._manager._reconnect_defaults()
        storage_defaults = self._manager._storage_defaults()
        plate_defaults = self._manager._plate_defaults()
        time_defaults = self._manager._time_defaults()
        logging_defaults = self._manager._logging_defaults()
        model_defaults = self._manager._model_defaults()
        ocr_defaults = self._manager._ocr_defaults()
        detector_defaults = self._manager._detector_defaults()
        inference_defaults = self._manager._inference_defaults()
        debug_defaults = self._manager._debug_defaults()

        if not data.get("theme"):
            data["theme"] = "dark"
            changed = True

        direction_defaults = self._manager._direction_defaults()
        direction_settings = tracking_defaults.get("direction")
        if direction_settings is None:
            tracking_defaults["direction"] = direction_defaults
            data["tracking"] = tracking_defaults
            changed = True
        else:
            for key, value in direction_defaults.items():
                if key not in direction_settings:
                    direction_settings[key] = value
                    changed = True

        for channel in data.get("channels", []):
            if self._manager._fill_channel_defaults(channel, tracking_defaults):
                changed = True

        if self._manager._fill_reconnect_defaults(data, reconnect_defaults):
            changed = True

        if self._manager._fill_model_defaults(data, model_defaults):
            changed = True

        if self._manager._fill_ocr_defaults(data, ocr_defaults):
            changed = True

        if self._manager._fill_detector_defaults(data, detector_defaults):
            changed = True

        if self._manager._fill_inference_defaults(data, inference_defaults):
            changed = True

        if self._manager._fill_storage_defaults(data, storage_defaults):
            changed = True

        if self._manager._fill_plate_defaults(data, plate_defaults):
            changed = True

        if self._manager._fill_time_defaults(data, time_defaults):
            changed = True

        if self._manager._fill_logging_defaults(data, logging_defaults):
            changed = True

        if self._manager._fill_debug_defaults(data, debug_defaults):
            changed = True

        if self._manager._fill_controller_defaults(data):
            changed = True

        if changed:
            self._save(data)
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        logger.debug(f"Сохранение настроек из потока: {threading.current_thread().name}")
        with self._file_lock:
            snapshot = copy.deepcopy(data)
        self._write_to_disk(snapshot)

    def _write_to_disk(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._file_lock:
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self.path) or ".", prefix=".settings_", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.path)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

    def refresh(self) -> None:
        with self._file_lock:
            self.settings = self._load()
