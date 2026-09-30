"""Section divider row in the official firmware list (current vs legacy)."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets

import gui.theme as t
from gui import ui_scale as u


class FirmwareSectionHeader(QtWidgets.QWidget):
    def __init__(self, title: str, *, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 10, 4, 4)
        lay.setSpacing(6)

        self._rule = QtWidgets.QFrame()
        self._rule.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self._rule.setFixedHeight(1)
        lay.addWidget(self._rule)

        self._label = QtWidgets.QLabel(title)
        self._label.setWordWrap(True)
        lay.addWidget(self._label)

        self.reload_theme()

    def reload_theme(self) -> None:
        self._rule.setStyleSheet(f"background: {t.IF_TAB_DIVIDER}; border: none;")
        self._label.setStyleSheet(
            f"color: {t.IF_CARD_IDLE_SUBTEXT}; font-size: {u.px(11)}px; font-weight: 700;"
        )
