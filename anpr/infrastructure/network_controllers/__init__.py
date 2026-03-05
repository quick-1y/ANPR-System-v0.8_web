#!/usr/bin/env python3
# /anpr/infrastructure/network_controllers/__init__.py
from __future__ import annotations

from typing import Dict

from .base import ControllerAdapter
from .dtwonder2ch import Dtwonder2ChAdapter

CONTROLLER_ADAPTERS: Dict[str, ControllerAdapter] = {
    Dtwonder2ChAdapter.type_name: Dtwonder2ChAdapter(),
}

__all__ = ["ControllerAdapter", "Dtwonder2ChAdapter", "CONTROLLER_ADAPTERS"]
