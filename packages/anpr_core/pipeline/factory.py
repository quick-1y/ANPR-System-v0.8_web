from __future__ import annotations

import threading
from typing import Dict, Tuple

from packages.anpr_core.config import ANPRConfig
from packages.anpr_core.detection.yolo_detector import YOLODetector
from packages.anpr_core.pipeline.anpr_pipeline import ANPRPipeline
from packages.anpr_core.postprocessing.country_config import CountryConfigLoader
from packages.anpr_core.postprocessing.validator import PlatePostProcessor
from packages.anpr_core.recognition.crnn_recognizer import CRNNRecognizer

_RECOGNIZER_LOCK = threading.RLock()
_RECOGNIZER_INITIALIZING = False
_RECOGNIZER_READY = threading.Event()
_RECOGNIZER_SINGLETON: CRNNRecognizer | None = None
_RECOGNIZER_CONFIG_KEY: tuple[str, str, str, int, int, str] | None = None


class _FallbackRecognizer:
    def recognize(self, _plate_image):
        return "", 0.0

    def recognize_batch(self, _plate_images):
        return []


_NOOP_RECOGNIZER = _FallbackRecognizer()


def _initialize_recognizer_threadsafe(config: ANPRConfig) -> CRNNRecognizer:
    return CRNNRecognizer(config)


def _get_fallback_recognizer() -> CRNNRecognizer:
    return _RECOGNIZER_SINGLETON or _NOOP_RECOGNIZER


def _get_shared_recognizer(config: ANPRConfig) -> CRNNRecognizer:
    global _RECOGNIZER_INITIALIZING, _RECOGNIZER_SINGLETON, _RECOGNIZER_CONFIG_KEY
    current_key = (config.ocr_model_path, config.device.type, config.ocr_alphabet, config.ocr_height, config.ocr_width, config.device_name)
    if _RECOGNIZER_CONFIG_KEY != current_key:
        _RECOGNIZER_SINGLETON = None
        _RECOGNIZER_CONFIG_KEY = current_key
    if _RECOGNIZER_SINGLETON is None and not _RECOGNIZER_INITIALIZING:
        with _RECOGNIZER_LOCK:
            if _RECOGNIZER_SINGLETON is None and not _RECOGNIZER_INITIALIZING:
                _RECOGNIZER_INITIALIZING = True
                _RECOGNIZER_READY.clear()

                def _init() -> None:
                    global _RECOGNIZER_INITIALIZING, _RECOGNIZER_SINGLETON
                    try:
                        _RECOGNIZER_SINGLETON = _initialize_recognizer_threadsafe(config)
                    finally:
                        _RECOGNIZER_INITIALIZING = False
                        _RECOGNIZER_READY.set()

                threading.Thread(target=_init, daemon=True).start()
    if not _RECOGNIZER_READY.wait(timeout=0.1):
        _RECOGNIZER_READY.wait()
    return _RECOGNIZER_SINGLETON or _get_fallback_recognizer()


def _build_postprocessor(config: ANPRConfig) -> PlatePostProcessor:
    loader = CountryConfigLoader(config.countries_dir)
    loader.ensure_dir()
    return PlatePostProcessor(loader, config.enabled_countries)


def build_components(
    anpr_config: ANPRConfig,
    best_shots: int,
    cooldown_seconds: int,
    min_confidence: float,
    direction_config: Dict[str, object] | None = None,
    min_plate_size: Dict[str, int] | None = None,
    max_plate_size: Dict[str, int] | None = None,
    size_filter_enabled: bool = True,
) -> Tuple[ANPRPipeline, YOLODetector]:
    detector = YOLODetector(
        anpr_config.yolo_model_path,
        anpr_config.device,
        min_plate_size=min_plate_size,
        max_plate_size=max_plate_size,
        size_filter_enabled=size_filter_enabled,
        detection_confidence_threshold=anpr_config.detector_confidence_threshold,
        bbox_padding_ratio=anpr_config.bbox_padding_ratio,
        min_padding_pixels=anpr_config.min_padding_pixels,
    )
    recognizer = _get_shared_recognizer(anpr_config)
    postprocessor = _build_postprocessor(anpr_config)
    pipeline = ANPRPipeline(
        recognizer,
        best_shots,
        cooldown_seconds,
        min_confidence=min_confidence,
        postprocessor=postprocessor,
        direction_config=direction_config,
    )
    return pipeline, detector
