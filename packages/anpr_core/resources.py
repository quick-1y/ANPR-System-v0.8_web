from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import importlib.resources as pkg_resources

_RESOURCE_STACK = ExitStack()


def _resolve_resource(*parts: str) -> Path:
    traversable = pkg_resources.files("packages.anpr_core").joinpath("resources", *parts)
    if not traversable.exists():
        raise FileNotFoundError(f"ANPR resource not found: {'/'.join(parts)}")
    # Keep extracted files alive for the whole process lifetime in case package is zipped.
    return _RESOURCE_STACK.enter_context(pkg_resources.as_file(traversable))


def resources_root() -> Path:
    return _resolve_resource()


def default_countries_dir() -> Path:
    return _resolve_resource("countries")


def default_yolo_model_path() -> Path:
    return _resolve_resource("models", "yolo", "best.pt")


def default_ocr_model_path() -> Path:
    return _resolve_resource("models", "ocr_crnn", "crnn_ocr_model_int8_fx.pth")
