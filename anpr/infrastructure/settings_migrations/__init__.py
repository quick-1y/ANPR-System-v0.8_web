"""Пакет миграций настроек."""

from .runner import detect_version, run_settings_migrations

__all__ = ["detect_version", "run_settings_migrations"]
