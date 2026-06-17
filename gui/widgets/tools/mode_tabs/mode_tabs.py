"""Debugger / Session Logs folder tabs for the Tools page."""

from __future__ import annotations

from typing import Literal, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u

ToolsMode = Literal["debugger", "session_logs"]


class ToolsModeTabs(QtWidgets.QWidget):
    mode_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._mode: ToolsMode = "debugger"
        self._build()

    @property
    def mode(self) -> ToolsMode:
        return self._mode

    def set_mode(self, mode: str) -> None:
        norm: ToolsMode = "session_logs" if str(mode).lower().replace(" ", "_") == "session_logs" else "debugger"
        if norm == self._mode:
            return
        self._mode = norm
        self._debugger_btn.setChecked(norm == "debugger")
        self._logs_btn.setChecked(norm == "session_logs")
        self._apply_tab_styles()

    def _build(self) -> None:
        self.setObjectName("toolsModeTabs")
        self.setFixedHeight(t.TOOLS_TAB_H)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._debugger_btn = QtWidgets.QPushButton("Debugger")
        self._logs_btn = QtWidgets.QPushButton("Session Logs")
        for btn in (self._debugger_btn, self._logs_btn):
            btn.setCheckable(True)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            lay.addWidget(btn, 1)

        self._debugger_btn.setChecked(True)
        self._debugger_btn.clicked.connect(lambda: self._on_tab("debugger"))
        self._logs_btn.clicked.connect(lambda: self._on_tab("session_logs"))
        self._apply_container_style()
        self._apply_tab_styles()

    def _on_tab(self, mode: ToolsMode) -> None:
        if self._mode == mode:
            return
        self._mode = mode
        self._debugger_btn.setChecked(mode == "debugger")
        self._logs_btn.setChecked(mode == "session_logs")
        self._apply_tab_styles()
        self.mode_changed.emit(mode)

    def _tab_style(self, *, active: bool, first: bool, top_clip: int) -> str:
        r = t.IF_TAB_CORNER_RADIUS
        overlap = t.IF_TAB_ACTIVE_OVERLAP

        if active:
            corners = f"border-top-left-radius: {r}px;" if first else f"border-top-right-radius: {r}px;"
            bg = (
                f"qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                f"stop:0 {t.IF_TAB_ACTIVE_TOP}, stop:1 {t.IF_TAB_ACTIVE_BOT})"
            )
            fg = t.IF_TAB_ACTIVE_FG
            border = (
                f"border: none; border-bottom: {overlap}px solid {t.IF_TAB_ACTIVE_BOT}; "
                f"margin-top: 0px; margin-bottom: -{overlap}px; {corners}"
            )
        else:
            corners = ""
            bg = (
                f"qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                f"stop:0 {t.IF_TAB_INACTIVE_TOP}, stop:1 {t.IF_TAB_INACTIVE_BOT})"
            )
            fg = t.IF_TAB_INACTIVE_FG
            side = f"border-right: 1px solid {t.IF_TAB_DIVIDER};" if first else ""
            border = (
                f"border: 1px solid {t.IF_TAB_INACTIVE_BORDER}; border-top: none; "
                f"border-bottom: none; margin-top: {top_clip}px; {side} {corners}"
            )
        return f"""
            QPushButton {{
                background: {bg};
                color: {fg};
                font-size: {u.px(t.TOOLS_TAB_FONT)}px;
                font-weight: 900;
                {border}
            }}
        """

    def _apply_container_style(self) -> None:
        self.setStyleSheet(f"""
            #toolsModeTabs {{
                border: none;
                background: {t.IF_TAB_BG};
            }}
        """)

    def _apply_tab_styles(self) -> None:
        clip = t.IF_TAB_INACTIVE_TOP_CLIP
        for btn, first in ((self._debugger_btn, True), (self._logs_btn, False)):
            active = btn.isChecked()
            top_clip = 0 if active else clip
            btn.setFixedHeight(u.px(t.TOOLS_TAB_H) - u.px(top_clip))
            btn.setStyleSheet(
                self._tab_style(active=active, first=first, top_clip=top_clip)
            )
        if self._debugger_btn.isChecked():
            self._debugger_btn.raise_()
        else:
            self._logs_btn.raise_()

    def reload_theme(self) -> None:
        self.setFixedHeight(u.px(t.TOOLS_TAB_H))
        self._apply_container_style()
        self._apply_tab_styles()
