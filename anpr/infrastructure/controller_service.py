#!/usr/bin/env python3
# /anpr/infrastructure/controller_service.py
from __future__ import annotations

import threading
import time
import urllib.request
from collections import OrderedDict
from typing import Any, Dict, Optional

from anpr.infrastructure.logging_manager import get_logger
from anpr.infrastructure.network_controllers import CONTROLLER_ADAPTERS

logger = get_logger(__name__)

CONTROLLER_TYPES = OrderedDict([
    ("DTWONDER2CH", "DTWONDER2CH"),
])

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


__all__ = [
    "ControllerService",
    "CONTROLLER_TYPES",
    "RELAY_MODES",
    "build_command_url",
]
