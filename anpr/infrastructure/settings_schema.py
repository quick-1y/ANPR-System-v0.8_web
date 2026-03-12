"""Схема настроек приложения и дефолтные значения."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

SETTINGS_VERSION = 2
LOG_LEVELS = ("ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def normalize_log_level(value: Any) -> str:
    normalized = str(value or "INFO").upper()
    return normalized if normalized in LOG_LEVELS else "INFO"


DEFAULT_ROI_POINTS = [
    {"x": 500, "y": 300},
    {"x": 1200, "y": 300},
    {"x": 1200, "y": 900},
    {"x": 500, "y": 900},
]


def normalize_region_config(region: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Приводит ROI к единому формату с точками."""

    if not region:
        return {"unit": "px", "points": [point.copy() for point in DEFAULT_ROI_POINTS]}

    normalized_unit = str(region.get("unit", "px")).lower()
    if normalized_unit not in ("px", "percent"):
        normalized_unit = "px"

    raw_points = region.get("points") or []
    points: list[dict[str, float]] = []
    for point in raw_points:
        if not isinstance(point, dict):
            continue
        points.append({"x": float(point.get("x", 0)), "y": float(point.get("y", 0))})

    if points:
        return {"unit": normalized_unit, "points": points}

    x = float(region.get("x", 0))
    y = float(region.get("y", 0))
    width = float(region.get("width", 100))
    height = float(region.get("height", 100))
    rect_points = [
        {"x": x, "y": y},
        {"x": x + width, "y": y},
        {"x": x + width, "y": y + height},
        {"x": x, "y": y + height},
    ]
    return {"unit": "percent", "points": rect_points}


def relay_defaults() -> Dict[str, Any]:
    return {"mode": "pulse", "timer_seconds": 1, "hotkey": ""}


def reconnect_defaults() -> Dict[str, Any]:
    return {
        "signal_loss": {"enabled": True, "frame_timeout_seconds": 5, "retry_interval_seconds": 5},
        "periodic": {"enabled": False, "interval_minutes": 60},
    }


def storage_defaults() -> Dict[str, Any]:
    return {
        "screenshots_dir": "data/screenshots",
        "logs_dir": "logs",
        "auto_cleanup_enabled": True,
        "cleanup_interval_minutes": 30,
        "events_retention_days": 30,
        "media_retention_days": 14,
        "max_screenshots_mb": 4096,
        "export_dir": "data/exports",
    }


def plate_defaults() -> Dict[str, Any]:
    return {"config_dir": "anpr/countries", "enabled_countries": ["RU", "UA", "BY", "KZ"]}


def model_defaults() -> Dict[str, Any]:
    return {"yolo_model_path": "anpr/models/yolo/best.pt", "ocr_model_path": "anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth", "device": "cpu"}


def inference_defaults() -> Dict[str, Any]:
    cpu_count = os.cpu_count() or 1
    return {"workers": max(1, cpu_count - 1), "shared_memory": True}


def plate_size_defaults() -> Dict[str, Dict[str, int]]:
    return {"min_plate_size": {"width": 80, "height": 20}, "max_plate_size": {"width": 600, "height": 240}}


def direction_defaults() -> Dict[str, float | int]:
    return {
        "history_size": 12,
        "min_track_length": 3,
        "smoothing_window": 5,
        "confidence_threshold": 0.55,
        "jitter_pixels": 1.0,
        "min_area_change_ratio": 0.02,
    }


def ocr_defaults() -> Dict[str, Any]:
    return {"img_height": 32, "img_width": 128, "alphabet": "0123456789ABCEHKMOPTXY", "confidence_threshold": 0.6}


def detector_defaults() -> Dict[str, Any]:
    return {"confidence_threshold": 0.5, "bbox_padding_ratio": 0.08, "min_padding_pixels": 2}


def time_defaults() -> Dict[str, Any]:
    now = datetime.now().astimezone()
    offset = now.utcoffset() or timedelta()
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    total = abs(minutes)
    hours = total // 60
    mins = total % 60
    default_zone = f"UTC{sign}{hours:02d}:{mins:02d}"
    return {"timezone": default_zone, "offset_minutes": 0}


def logging_defaults() -> Dict[str, Any]:
    return {"level": "INFO", "retention_days": 30, "allowed_levels": list(LOG_LEVELS)}


def debug_defaults() -> Dict[str, Any]:
    return {
        "show_channel_metrics": True,
        "log_panel_enabled": False,
    }


def channel_defaults(tracking: Dict[str, Any]) -> Dict[str, Any]:
    size_defaults = plate_size_defaults()
    return {
        "best_shots": int(tracking.get("best_shots", 3)),
        "cooldown_seconds": int(tracking.get("cooldown_seconds", 5)),
        "ocr_min_confidence": float(tracking.get("ocr_min_confidence", 0.6)),
        "direction": dict(tracking.get("direction", direction_defaults())),
        "roi_enabled": True,
        "region": {"unit": "px", "points": [point.copy() for point in DEFAULT_ROI_POINTS]},
        "detection_mode": "motion",
        "detector_frame_stride": 2,
        "motion_threshold": 0.01,
        "motion_frame_stride": 1,
        "motion_activation_frames": 3,
        "motion_release_frames": 6,
        "size_filter_enabled": True,
        "min_plate_size": size_defaults["min_plate_size"].copy(),
        "max_plate_size": size_defaults["max_plate_size"].copy(),
        "controller_id": None,
        "controller_relay": 0,
        "list_filter_mode": "all",
        "list_filter_list_ids": [],
    }


def build_default_settings() -> Dict[str, Any]:
    return {
        "settings_version": SETTINGS_VERSION,
        "models": model_defaults(),
        "ocr": ocr_defaults(),
        "detector": detector_defaults(),
        "inference": inference_defaults(),
        "debug": debug_defaults(),
        "grid": "2x2",
        "theme": "dark",
        "channels": [],
        "controllers": [],
        "reconnect": reconnect_defaults(),
        "storage": storage_defaults(),
        "tracking": {
            "best_shots": 3,
            "cooldown_seconds": 5,
            "ocr_min_confidence": 0.6,
            "direction": direction_defaults(),
        },
        "plates": plate_defaults(),
        "logging": logging_defaults(),
        "time": time_defaults(),
    }
