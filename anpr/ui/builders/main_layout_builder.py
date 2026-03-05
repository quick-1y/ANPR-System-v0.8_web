from __future__ import annotations

from PyQt5 import QtWidgets


def build_main_root(header: QtWidgets.QWidget, tabs: QtWidgets.QTabWidget) -> QtWidgets.QWidget:
    root = QtWidgets.QWidget()
    root_layout = QtWidgets.QVBoxLayout(root)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)
    root_layout.addWidget(header)
    root_layout.addWidget(tabs, 1)
    return root
