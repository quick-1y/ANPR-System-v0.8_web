from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import torch

from packages.anpr_core.resources import default_countries_dir, default_ocr_model_path, default_yolo_model_path


@dataclass
class ANPRConfig:
    yolo_model_path: str
    ocr_model_path: str
    device_name: str = "cpu"
    ocr_height: int = 32
    ocr_width: int = 128
    ocr_alphabet: str = "0123456789ABCEHKMOPTXY"
    detector_confidence_threshold: float = 0.5
    bbox_padding_ratio: float = 0.08
    min_padding_pixels: int = 2
    countries_dir: str = field(default_factory=lambda: str(default_countries_dir()))
    enabled_countries: List[str] = field(default_factory=lambda: ["RU", "UA", "BY", "KZ"])

    @property
    def device(self) -> torch.device:
        normalized = self.device_name.strip().lower()
        if normalized == "gpu":
            normalized = "cuda"
        if normalized.startswith("cuda") and not torch.cuda.is_available():
            return torch.device("cpu")
        try:
            return torch.device(normalized)
        except (TypeError, ValueError):
            return torch.device("cpu")

    @classmethod
    def from_settings(
        cls,
        model_settings: Dict[str, Any],
        plate_settings: Dict[str, Any],
        ocr_settings: Dict[str, Any],
        detector_settings: Dict[str, Any],
    ) -> "ANPRConfig":
        yolo_path = str(model_settings.get("yolo_model_path") or "").strip()
        ocr_path = str(model_settings.get("ocr_model_path") or "").strip()
        countries_dir = str(plate_settings.get("config_dir") or "").strip()
        return cls(
            yolo_model_path=yolo_path or str(default_yolo_model_path()),
            ocr_model_path=ocr_path or str(default_ocr_model_path()),
            device_name=str(model_settings.get("device") or "cpu"),
            ocr_height=int(ocr_settings.get("img_height", 32)),
            ocr_width=int(ocr_settings.get("img_width", 128)),
            ocr_alphabet=str(ocr_settings.get("alphabet", "0123456789ABCEHKMOPTXY")),
            detector_confidence_threshold=float(detector_settings.get("confidence_threshold", 0.5)),
            bbox_padding_ratio=float(detector_settings.get("bbox_padding_ratio", 0.08)),
            min_padding_pixels=int(detector_settings.get("min_padding_pixels", 2)),
            countries_dir=countries_dir or str(default_countries_dir()),
            enabled_countries=[str(x).upper() for x in plate_settings.get("enabled_countries", ["RU", "UA", "BY", "KZ"])],
        )


@dataclass
class AppConfig:
    grid: str
    theme: str
    storage: Dict[str, Any]
    reconnect: Dict[str, Any]
    logging: Dict[str, Any]
    time: Dict[str, Any]
    debug: Dict[str, Any]
