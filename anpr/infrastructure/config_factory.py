"""Фабрики конфигурации на границе app-layer и anpr-core."""

from __future__ import annotations

from typing import Any, Dict

from packages.anpr_core.config import ANPRConfig, AppConfig


def build_anpr_config(raw_settings: Dict[str, Any]) -> ANPRConfig:
    models = dict(raw_settings.get("models") or {})
    plates = dict(raw_settings.get("plates") or {})
    ocr = dict(raw_settings.get("ocr") or {})
    detector = dict(raw_settings.get("detector") or {})
    return ANPRConfig.from_settings(models, plates, ocr, detector)


def build_app_config(raw_settings: Dict[str, Any]) -> AppConfig:
    storage = dict(raw_settings.get("storage") or {})
    logging = dict(raw_settings.get("logging") or {})
    logging["logs_dir"] = storage.get("logs_dir", "logs")
    return AppConfig(
        grid=str(raw_settings.get("grid", "2x2")),
        theme=str(raw_settings.get("theme", "dark")),
        storage=storage,
        reconnect=dict(raw_settings.get("reconnect") or {}),
        logging=logging,
        time=dict(raw_settings.get("time") or {}),
        debug=dict(raw_settings.get("debug") or {}),
    )
