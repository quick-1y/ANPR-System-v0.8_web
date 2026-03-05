from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypedDict


class DetectionDict(TypedDict, total=False):
    bbox: List[int]
    track_id: int
    text: str
    confidence: float
    direction: str
    unreadable: bool


class EventDict(TypedDict, total=False):
    id: int
    timestamp: str
    channel: str
    plate: str
    confidence: float
    direction: str
    bbox: List[int]
    frame_path: str
    plate_path: str
    frame_image: Any
    plate_image: Any


@dataclass(frozen=True)
class InferenceInput:
    source: str
    channel_name: str
    roi_rect: tuple[int, int, int, int]
