from __future__ import annotations

from typing import Any

from anpr.ui.presenters.main_window_presenter import MainWindowPresenter


class ChannelActionsService:
    """Применяет UI-обновления канала на основе подготовленных данных presenter."""

    def __init__(self, presenter: MainWindowPresenter) -> None:
        self._presenter = presenter

    def apply_status(self, label: Any, status: str) -> None:
        clean_status, motion_active = self._presenter.split_status(status)
        label.set_status(clean_status)
        label.set_motion_active(motion_active)

    def apply_metrics(self, label: Any, metrics: dict[str, Any]) -> None:
        camera_metrics, detector_metrics = self._presenter.format_metrics_sections(metrics)
        if hasattr(label, "set_metrics_sections"):
            label.set_metrics_sections(camera_metrics, detector_metrics)
            return
        label.set_metrics(self._presenter.format_metrics(metrics))
