from __future__ import annotations

from typing import Iterable

from PyQt6 import QtWidgets


def build_main_tabs(tabs_widget: QtWidgets.QTabWidget, tabs: Iterable[tuple[QtWidgets.QWidget, str]]) -> QtWidgets.QTabWidget:
    for widget, title in tabs:
        tabs_widget.addTab(widget, title)
    return tabs_widget
