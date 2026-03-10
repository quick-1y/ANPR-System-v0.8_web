from __future__ import annotations

import urllib.parse
from typing import Any, Dict, Optional

from controllers.base import ControllerAdapter


def _normalize_password(password: Optional[str]) -> str:
    if password is None:
        return "0"
    value = str(password).strip()
    if not value:
        return "0"
    if value.lower().startswith("pwd="):
        return value.split("=", 1)[1] or "0"
    return value


def _normalize_address(address: str) -> str:
    address = str(address or "").strip()
    if not address:
        return ""
    if not address.startswith("http://") and not address.startswith("https://"):
        address = f"http://{address}"
    return address.rstrip("/")


def _relay_mode_payload(mode: str, timer_seconds: int) -> Dict[str, int]:
    if mode == "pulse_timer":
        return {"type": 2, "time": max(1, int(timer_seconds))}
    return {"type": 1, "time": 1}


class Dtwonder2ChAdapter(ControllerAdapter):
    type_name = "DTWONDER2CH"

    def build_command_url(
        self,
        controller: Dict[str, Any],
        relay_index: int,
        is_on: bool,
        *,
        mode_override: Optional[str] = None,
    ) -> Optional[str]:
        address = _normalize_address(str(controller.get("address", "")))
        if not address:
            return None
        relay_index = 0 if relay_index not in (0, 1) else relay_index
        relays = controller.get("relays") or []
        relay_conf = relays[relay_index] if relay_index < len(relays) else {}
        mode = mode_override or relay_conf.get("mode") or "pulse"
        timer_seconds = int(relay_conf.get("timer_seconds", 1) or 1)
        payload = _relay_mode_payload(str(mode), timer_seconds)
        params = {
            "type": payload["type"],
            "relay": relay_index,
            "on": 1 if is_on else 0,
            "time": payload["time"],
            "pwd": _normalize_password(relay_conf.get("password") or controller.get("password")),
        }
        query = urllib.parse.urlencode(params)
        return f"{address}/relay_cgi.cgi?{query}"


__all__ = ["Dtwonder2ChAdapter"]
