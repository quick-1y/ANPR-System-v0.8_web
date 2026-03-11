"""Совместимость: переэкспорт централизованного logging-слоя."""

from common.logging import configure_logging, get_logger, log_perf_stage

__all__ = ["configure_logging", "get_logger", "log_perf_stage"]
