from __future__ import annotations

from typing import Any, Optional


class MainWindowPresenter:
    """Подготовка данных отображения для MainWindow."""

    DIRECTION_LABELS = {
        "APPROACHING": "К камере",
        "RECEDING": "От камеры",
    }

    @classmethod
    def format_direction(cls, direction: Optional[str]) -> str:
        if not direction:
            return "—"
        return cls.DIRECTION_LABELS.get(str(direction).upper(), "—")

    @staticmethod
    def _format_ms(value: Any) -> str:
        return f"{value:.0f} мс" if isinstance(value, (int, float)) else "—"

    @staticmethod
    def format_metrics_sections(metrics: dict[str, Any]) -> tuple[str, str]:
        fps = metrics.get("fps")
        latency_ms = metrics.get("latency_ms")
        accuracy = metrics.get("accuracy")
        errors = metrics.get("errors") if isinstance(metrics.get("errors"), dict) else {}

        fps_text = f"{fps:.1f}" if isinstance(fps, (int, float)) else "—"
        latency_text = f"{latency_ms:.0f} ms" if isinstance(latency_ms, (int, float)) else "—"
        accuracy_text = f"{accuracy:.0f}%" if isinstance(accuracy, (int, float)) else "—"
        reconnect_errors = int(errors.get("reconnect", 0) or 0)
        timeout_errors = int(errors.get("timeout", 0) or 0)
        empty_frame_errors = int(errors.get("empty_frame", 0) or 0)
        total_errors = reconnect_errors + timeout_errors + empty_frame_errors
        health = "Норма" if total_errors == 0 else f"Ошибки: {total_errors}"

        detect_ms = metrics.get("detect_ms")
        ocr_ms = metrics.get("ocr_ms")
        post_ms = metrics.get("postprocess_ms")

        detect_text = MainWindowPresenter._format_ms(detect_ms)
        ocr_ms_text = MainWindowPresenter._format_ms(ocr_ms)
        post_text = MainWindowPresenter._format_ms(post_ms)

        camera_metrics = (
            f"Состояние: {health}\n"
            f"FPS: {fps_text}\n"
            f"Задержка: {latency_text}\n"
            f"Переподкл.: {reconnect_errors}\n"
            f"Таймауты: {timeout_errors}\n"
            f"Пустые кадры: {empty_frame_errors}"
        )
        detector_metrics = (
            f"Детекция: {detect_text}\n"
            f"OCR (мс): {ocr_ms_text}\n"
            f"OCR (%): {accuracy_text}\n"
            f"Постобработка: {post_text}"
        )
        return camera_metrics, detector_metrics

    @classmethod
    def format_metrics(cls, metrics: dict[str, Any]) -> str:
        camera_metrics, detector_metrics = cls.format_metrics_sections(metrics)
        return f"{camera_metrics}\n{detector_metrics}"

    @staticmethod
    def split_status(status: str) -> tuple[str, bool]:
        normalized = (status or "").lower()
        if "движ" in normalized or "motion" in normalized:
            return "", "обнаружено" in normalized
        return status, "обнаружено" in normalized
