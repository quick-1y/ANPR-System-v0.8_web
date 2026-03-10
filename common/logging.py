from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Нейтральный helper для получения именованного логгера."""

    return logging.getLogger(name)
