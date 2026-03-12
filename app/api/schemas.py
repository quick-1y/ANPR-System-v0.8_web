from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from controllers import SUPPORTED_CONTROLLER_TYPES


class ChannelPayload(BaseModel):
    name: str
    source: str
    enabled: bool = True
    roi_enabled: bool = True
    region: Dict[str, Any] | None = None


class ROIRegionPayload(BaseModel):
    unit: str = Field(default="percent", pattern="^(px|percent)$")
    points: List[Dict[str, float]] = Field(default_factory=list)


class PlateSizePayload(BaseModel):
    width: int = Field(ge=1, le=4000)
    height: int = Field(ge=1, le=4000)


class ChannelConfigPayload(BaseModel):
    name: str
    source: str
    enabled: Optional[bool] = None
    controller_id: Optional[int] = None
    controller_relay: int = Field(default=0, ge=0, le=1)
    list_filter_mode: str = Field(default="all", pattern="^(all|whitelist|custom)$")
    list_filter_list_ids: List[int] = Field(default_factory=list)
    detection_mode: str = Field(default="motion", pattern="^(always|motion)$")
    motion_threshold: float = Field(default=0.01, ge=0.0, le=1.0)
    motion_frame_stride: int = Field(default=1, ge=1, le=30)
    motion_activation_frames: int = Field(default=3, ge=1, le=120)
    motion_release_frames: int = Field(default=6, ge=1, le=120)
    detector_frame_stride: int = Field(default=2, ge=1, le=30)
    size_filter_enabled: bool = True
    min_plate_size: PlateSizePayload = Field(default_factory=lambda: PlateSizePayload(width=80, height=20))
    max_plate_size: PlateSizePayload = Field(default_factory=lambda: PlateSizePayload(width=600, height=240))
    best_shots: int = Field(default=3, ge=1, le=20)
    cooldown_seconds: int = Field(default=5, ge=0, le=300)
    ocr_min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    roi_enabled: bool = True
    region: ROIRegionPayload = Field(default_factory=ROIRegionPayload)

    @field_validator("controller_id")
    @classmethod
    def normalize_controller_id(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if int(value) <= 0:
            return None
        return int(value)


class ChannelOCRPayload(BaseModel):
    best_shots: int = Field(ge=1, le=20)
    cooldown_seconds: int = Field(ge=0, le=300)
    ocr_min_confidence: float = Field(ge=0.0, le=1.0)


class ChannelFilterPayload(BaseModel):
    list_filter_mode: str = Field(pattern="^(all|whitelist|custom)$")
    list_filter_list_ids: List[int] = []
    size_filter_enabled: bool = True
    min_plate_size: Dict[str, int] = {"width": 80, "height": 20}
    max_plate_size: Dict[str, int] = {"width": 600, "height": 240}


def _normalize_hotkey(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return ""
    parts = [part.strip() for part in normalized.split("+") if part.strip()]
    if not parts:
        return ""
    modifiers_order = ["CTRL", "ALT", "SHIFT"]
    seen_modifiers: set[str] = set()
    normalized_parts: list[str] = []
    key_part = ""
    for part in parts:
        if part in modifiers_order:
            seen_modifiers.add(part)
            continue
        if key_part:
            raise ValueError("Хоткей должен содержать только одну основную клавишу")
        key_part = part
    if not key_part:
        raise ValueError("Хоткей должен содержать основную клавишу")
    for modifier in modifiers_order:
        if modifier in seen_modifiers:
            normalized_parts.append(modifier)
    normalized_parts.append(key_part)
    return "+".join(normalized_parts)


class RelayPayload(BaseModel):
    mode: str = Field(default="pulse", pattern="^(pulse|pulse_timer)$")
    timer_seconds: int = Field(default=1, ge=1, le=3600)
    hotkey: str = ""

    @field_validator("hotkey")
    @classmethod
    def normalize_hotkey(cls, value: str) -> str:
        return _normalize_hotkey(value)

    @model_validator(mode="after")
    def normalize_timer(self) -> "RelayPayload":
        if self.mode == "pulse":
            self.timer_seconds = 1
        return self


class ControllerPayload(BaseModel):
    name: str
    type: str = Field(default="DTWONDER2CH", min_length=1, max_length=64)
    address: str
    password: str = "0"
    relays: List[RelayPayload]

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        controller_type = str(value or "").strip()
        if not controller_type:
            return "DTWONDER2CH"
        if controller_type not in SUPPORTED_CONTROLLER_TYPES:
            supported = ", ".join(SUPPORTED_CONTROLLER_TYPES)
            raise ValueError(f"Неподдерживаемый тип контроллера: {controller_type}. Поддерживаются: {supported}")
        return controller_type

    @model_validator(mode="after")
    def validate_relays(self) -> "ControllerPayload":
        if len(self.relays) != 2:
            raise ValueError("Контроллер должен содержать ровно 2 реле")
        hotkeys = [relay.hotkey for relay in self.relays if relay.hotkey]
        if len(hotkeys) != len(set(hotkeys)):
            raise ValueError("Хоткеи реле должны быть уникальными")
        return self


class ControllerTestPayload(BaseModel):
    relay_index: int = Field(ge=0, le=1)
    is_on: bool = True


class ListPayload(BaseModel):
    name: str
    type: str = "white"


class EntryPayload(BaseModel):
    plate: str
    comment: str = ""


class RetentionPolicyPayload(BaseModel):
    auto_cleanup_enabled: bool = True
    cleanup_interval_minutes: int = 30
    events_retention_days: int = 30
    media_retention_days: int = 14
    max_screenshots_mb: int = 4096
    export_dir: str = "data/exports"


class ExportBundlePayload(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    channel: Optional[str] = None
    include_media: bool = True


class ReconnectSignalLossPayload(BaseModel):
    enabled: bool = True
    frame_timeout_seconds: int = Field(default=5, ge=1, le=300)
    retry_interval_seconds: int = Field(default=5, ge=1, le=300)


class ReconnectPeriodicPayload(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=1, le=1440)


class ReconnectPayload(BaseModel):
    signal_loss: ReconnectSignalLossPayload
    periodic: ReconnectPeriodicPayload


class StoragePayload(BaseModel):
    postgres_dsn: Optional[str] = None
    screenshots_dir: str
    logs_dir: str
    auto_cleanup_enabled: bool
    cleanup_interval_minutes: int = Field(ge=1, le=1440)
    events_retention_days: int = Field(ge=1, le=3650)
    media_retention_days: int = Field(ge=1, le=3650)
    max_screenshots_mb: int = Field(ge=128, le=1024 * 1024)
    export_dir: str


class LoggingPayload(BaseModel):
    level: str = Field(pattern="^(ALL|DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    retention_days: int = Field(ge=1, le=3650)


class TimePayload(BaseModel):
    timezone: str
    offset_minutes: int = Field(ge=-720, le=720)


class PlatesPayload(BaseModel):
    config_dir: str
    enabled_countries: List[str] = Field(default_factory=list)


class DebugPayload(BaseModel):
    show_channel_metrics: bool = True
    log_panel_enabled: bool = False


class GlobalSettingsPayload(BaseModel):
    grid: str
    theme: str
    reconnect: ReconnectPayload
    storage: StoragePayload
    logging: LoggingPayload
    time: TimePayload
    plates: PlatesPayload
    debug: DebugPayload
