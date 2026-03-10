from __future__ import annotations

from typing import Dict

from controllers.adapters import Dtwonder2ChAdapter
from controllers.base import ControllerAdapter

CONTROLLER_ADAPTERS: Dict[str, ControllerAdapter] = {
    Dtwonder2ChAdapter.type_name: Dtwonder2ChAdapter(),
}

__all__ = ["CONTROLLER_ADAPTERS"]
