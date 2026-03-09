"""Миграция настроек с версии 2 на 3 (нормализация путей ANPR-ресурсов)."""

from __future__ import annotations

from typing import Any, Dict

TARGET_VERSION = 3

LEGACY_COUNTRIES_PATHS = {
    "anpr/countries",
    "packages/anpr_core/resources/countries",
}

LEGACY_YOLO_PATHS = {
    "anpr/models/yolo/best.pt",
    "packages/anpr_core/resources/models/yolo/best.pt",
}

LEGACY_OCR_PATHS = {
    "anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth",
    "packages/anpr_core/resources/models/ocr_crnn/crnn_ocr_model_int8_fx.pth",
}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().replace('\\', '/')


def migrate(data: Dict[str, Any]) -> Dict[str, Any]:
    migrated = dict(data)

    plates = dict(migrated.get("plates") or {})
    config_dir = _normalize_text(plates.get("config_dir"))
    if config_dir in LEGACY_COUNTRIES_PATHS:
        plates["config_dir"] = ""
    migrated["plates"] = plates

    models = dict(migrated.get("models") or {})
    yolo_model_path = _normalize_text(models.get("yolo_model_path"))
    ocr_model_path = _normalize_text(models.get("ocr_model_path"))
    if yolo_model_path in LEGACY_YOLO_PATHS:
        models["yolo_model_path"] = ""
    if ocr_model_path in LEGACY_OCR_PATHS:
        models["ocr_model_path"] = ""
    migrated["models"] = models

    migrated["settings_version"] = TARGET_VERSION
    return migrated
