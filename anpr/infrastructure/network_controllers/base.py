#!/usr/bin/env python3
# /anpr/infrastructure/network_controllers/base.py
from __future__ import annotations

from typing import Any, Dict, Optional


class ControllerAdapter:
    """Базовый класс для адаптеров сетевых контроллеров."""

    type_name = "BASE"

    def build_command_url(
        self,
        controller: Dict[str, Any],
        relay_index: int,
        is_on: bool,
        *,
        mode_override: Optional[str] = None,
    ) -> Optional[str]:
        raise NotImplementedError
