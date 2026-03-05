"""Запуск цепочки миграций settings.json."""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Tuple

from anpr.infrastructure.settings_migrations.v1_to_v2 import migrate as migrate_v1_to_v2
from anpr.infrastructure.settings_schema import SETTINGS_VERSION

MigrationFn = Callable[[Dict[str, Any]], Dict[str, Any]]

MIGRATIONS: dict[int, MigrationFn] = {
    1: migrate_v1_to_v2,
}


def detect_version(data: Dict[str, Any]) -> int:
    value = data.get("settings_version")
    if isinstance(value, int) and value > 0:
        return value
    return 1


def run_settings_migrations(data: Dict[str, Any], target_version: int = SETTINGS_VERSION) -> Tuple[Dict[str, Any], bool]:
    current = detect_version(data)
    migrated = copy.deepcopy(data)
    changed = False

    while current < target_version:
        migration = MIGRATIONS.get(current)
        if migration is None:
            break
        migrated = migration(migrated)
        current = detect_version(migrated)
        changed = True

    if migrated.get("settings_version") != target_version:
        migrated["settings_version"] = target_version
        changed = True

    return migrated, changed
