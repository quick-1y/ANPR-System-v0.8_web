"""Миграция настроек с версии 1 на 2."""

from __future__ import annotations

from typing import Any, Dict

from anpr.infrastructure.settings_schema import direction_defaults, normalize_region_config


TARGET_VERSION = 2


def migrate(data: Dict[str, Any]) -> Dict[str, Any]:
    migrated = dict(data)
    tracking = dict(migrated.get("tracking") or {})

    current_direction = dict(tracking.get("direction") or {})
    for key, value in direction_defaults().items():
        current_direction.setdefault(key, value)
    tracking["direction"] = current_direction
    migrated["tracking"] = tracking

    channels = list(migrated.get("channels") or [])
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        channel["region"] = normalize_region_config(channel.get("region"))

    migrated["channels"] = channels
    migrated["settings_version"] = TARGET_VERSION
    return migrated
