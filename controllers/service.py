from __future__ import annotations

import threading
import time
import urllib.request
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

from common.logging import get_logger
from controllers.registry import CONTROLLER_ADAPTERS

logger = get_logger(__name__)

CONTROLLER_TYPES = OrderedDict([
    ("DTWONDER2CH", "DTWONDER2CH"),
])

SUPPORTED_CONTROLLER_TYPES = tuple(CONTROLLER_TYPES.keys())

RELAY_MODES = OrderedDict([
    ("pulse", "Импульс"),
    ("pulse_timer", "Импульс с таймером"),
])


def build_command_url(
    controller: Dict[str, Any],
    relay_index: int,
    is_on: bool,
    *,
    mode_override: Optional[str] = None,
) -> Optional[str]:
    controller_type = str(controller.get("type") or "DTWONDER2CH")
    adapter = CONTROLLER_ADAPTERS.get(controller_type)
    if not adapter:
        logger.warning("Контроллер %s: неизвестный тип %s", controller.get("name") or "Контроллер", controller_type)
        return None
    return adapter.build_command_url(controller, relay_index, is_on, mode_override=mode_override)


class ControllerService:
    """Отправляет команды сетевым контроллерам."""

    def __init__(self, timeout_seconds: float = 2.0, error_cooldown_seconds: float = 10.0) -> None:
        self._timeout_seconds = float(timeout_seconds)
        self._error_cooldown_seconds = float(error_cooldown_seconds)
        self._error_state: Dict[str, Dict[str, float | int]] = {}

    def _is_in_cooldown(self, controller_name: str) -> bool:
        state = self._error_state.get(controller_name)
        if not state:
            return False
        last_error_ts = float(state.get("last_error_ts", 0.0) or 0.0)
        if not last_error_ts:
            return False
        return (time.monotonic() - last_error_ts) < self._error_cooldown_seconds

    def _register_error(self, controller_name: str) -> int:
        state = self._error_state.setdefault(controller_name, {"errors": 0, "last_error_ts": 0.0})
        state["errors"] = int(state.get("errors", 0)) + 1
        state["last_error_ts"] = time.monotonic()
        return int(state["errors"])

    def _reset_error_state(self, controller_name: str) -> None:
        if controller_name in self._error_state:
            self._error_state.pop(controller_name, None)

    def send_command(
        self,
        controller: Dict[str, Any],
        relay_index: int,
        is_on: bool,
        *,
        mode_override: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Optional[str]:
        url = build_command_url(controller, relay_index, is_on, mode_override=mode_override)
        controller_name = controller.get("name") or controller.get("address") or "Контроллер"
        if not url:
            logger.warning("Контроллер %s: не задан адрес, команда не отправлена", controller_name)
            return None
        if self._is_in_cooldown(controller_name):
            logger.warning(
                "Контроллер %s: команда пропущена (ожидание восстановления связи)",
                controller_name,
            )
            return None

        def _dispatch() -> None:
            try:
                logger.info(
                    "Контроллер %s: отправка команды (%s) %s",
                    controller_name,
                    reason or "вручную",
                    url,
                )
                with urllib.request.urlopen(url, timeout=self._timeout_seconds) as response:
                    response.read()
                logger.info("Контроллер %s: команда успешно отправлена", controller_name)
                self._reset_error_state(controller_name)
            except Exception as exc:  # noqa: BLE001
                error_count = self._register_error(controller_name)
                logger.error(
                    "Контроллер %s: ошибка отправки команды (%s). Попытка %s, таймаут %.1f с",
                    controller_name,
                    exc,
                    error_count,
                    self._timeout_seconds,
                )

        thread = threading.Thread(target=_dispatch, name=f"controller-{controller_name}", daemon=True)
        thread.start()
        return url


class ControllerAutomationService:
    """Реакция контроллера на уже сформированные ANPR события."""

    def __init__(
        self,
        controller_service: ControllerService,
        *,
        get_channels: Callable[[], List[Dict[str, Any]]],
        get_controllers: Callable[[], List[Dict[str, Any]]],
        plate_in_list_type: Callable[[str, str], bool],
        plate_in_lists: Callable[[str, List[int]], bool],
    ) -> None:
        self._controller_service = controller_service
        self._get_channels = get_channels
        self._get_controllers = get_controllers
        self._plate_in_list_type = plate_in_list_type
        self._plate_in_lists = plate_in_lists

    @staticmethod
    def _normalize_positive_int_ids(raw_ids: Any) -> List[int]:
        if not isinstance(raw_ids, list):
            return []
        normalized_ids: List[int] = []
        for item in raw_ids:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in normalized_ids:
                normalized_ids.append(value)
        return normalized_ids

    def _resolve_channel_controller_action(self, channel: Dict[str, Any], plate: str) -> tuple[bool, str]:
        mode = str(channel.get("list_filter_mode") or "all").strip().lower()
        if self._plate_in_list_type(plate, "black"):
            return False, "blacklisted"
        if mode == "all":
            return True, "matched:all"
        if mode == "whitelist":
            if self._plate_in_list_type(plate, "white"):
                return True, "matched:whitelist"
            return False, "whitelist miss"
        if mode == "custom":
            list_ids = self._normalize_positive_int_ids(channel.get("list_filter_list_ids"))
            if self._plate_in_lists(plate, list_ids):
                return True, "matched:custom"
            return False, "custom miss"
        return True, "matched:fallback"

    def handle_event(self, event: Dict[str, Any]) -> None:
        channel_id = int(event.get("channel_id") or 0)
        plate = str(event.get("plate") or "").strip()
        if channel_id <= 0 or not plate:
            return

        channel = next((item for item in self._get_channels() if int(item.get("id", 0)) == channel_id), None)
        if not channel:
            logger.debug("channel %s relay skip: channel not found", channel_id)
            return

        controller_id = channel.get("controller_id")
        if controller_id is None:
            logger.debug("channel %s relay skip: no controller", channel_id)
            return

        allowed, reason = self._resolve_channel_controller_action(channel, plate)
        if not allowed:
            logger.debug("channel %s relay skip: %s (plate=%s)", channel_id, reason, plate)
            return

        controller = next((item for item in self._get_controllers() if int(item.get("id", 0)) == int(controller_id)), None)
        if not controller:
            logger.debug("channel %s relay skip: controller not found (controller_id=%s)", channel_id, controller_id)
            return

        relay_index = int(channel.get("controller_relay", 0) or 0)
        url = self._controller_service.send_command(
            controller,
            relay_index,
            True,
            reason=f"anpr channel={channel_id} plate={plate} {reason}",
        )
        if not url:
            logger.debug(
                "channel %s relay skip: command failed / timeout (controller_id=%s relay=%s plate=%s)",
                channel_id,
                controller_id,
                relay_index,
                plate,
            )
            return
        logger.debug(
            "channel %s relay command sent: controller_id=%s relay=%s plate=%s reason=%s",
            channel_id,
            controller_id,
            relay_index,
            plate,
            reason,
        )

    def dispatch_event(self, event: Dict[str, Any]) -> None:
        try:
            self.handle_event(event)
        except Exception as exc:  # noqa: BLE001
            logger.error("controller binding processing failed: %s", exc)


__all__ = [
    "ControllerService",
    "ControllerAutomationService",
    "CONTROLLER_TYPES",
    "RELAY_MODES",
    "SUPPORTED_CONTROLLER_TYPES",
    "build_command_url",
]
