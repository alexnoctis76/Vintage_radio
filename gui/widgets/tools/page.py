"""Tools page — Debugger and Session Logs folders."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui.widgets.tools.debugger_panel.debugger_panel import DebuggerPanel
from gui.widgets.tools.mode_tabs.mode_tabs import ToolsModeTabs
from gui.widgets.tools.session_logs_panel.session_logs_panel import SessionLogsPanel


class ToolsPage(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._build()

    @property
    def mode_tabs(self) -> ToolsModeTabs:
        return self._tabs

    @property
    def debugger_panel(self) -> DebuggerPanel:
        return self._debugger

    @property
    def session_logs_panel(self) -> SessionLogsPanel:
        return self._logs

    def set_mode(self, mode: str) -> None:
        self._tabs.set_mode(mode)
        self._show_mode(mode)

    def embed_debug_widget(self, widget: QtWidgets.QWidget) -> None:
        self._debugger.embed_debug_widget(widget)

    def _build(self) -> None:
        self.setObjectName("toolsPage")
        self.setStyleSheet(f"#toolsPage {{ background: {t.C_BG}; }}")

        l, top, r, bot = t.LM_PAGE_MARGINS
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(l, top, r, bot)
        layout.setSpacing(0)

        shell = QtWidgets.QWidget()
        shell.setObjectName("toolsShell")
        shell.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        shell_lay = QtWidgets.QVBoxLayout(shell)
        shell_lay.setContentsMargins(0, 0, 0, 0)
        shell_lay.setSpacing(0)

        self._tabs = ToolsModeTabs()
        shell_lay.addWidget(self._tabs)

        self._stack = QtWidgets.QStackedWidget()
        self._debugger = DebuggerPanel()
        self._logs = SessionLogsPanel()
        self._stack.addWidget(self._debugger)
        self._stack.addWidget(self._logs)
        shell_lay.addWidget(self._stack, 1)

        shadow = QtWidgets.QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 9)
        shadow.setColor(QtGui.QColor(75, 43, 18, 31))
        shell.setGraphicsEffect(shadow)

        layout.addWidget(shell, 1)

        self._tabs.mode_changed.connect(self._show_mode)
        self._show_mode("debugger")

    def _show_mode(self, mode: str) -> None:
        norm = str(mode).lower().replace(" ", "_")
        self._stack.setCurrentIndex(1 if norm == "session_logs" else 0)

    def apply_ui_zoom(self) -> None:
        self.reload_theme()

    def reload_theme(self) -> None:
        self.setStyleSheet(f"#toolsPage {{ background: {t.C_BG}; }}")
        self._tabs.reload_theme()
        self._debugger.reload_theme()
        self._logs.reload_theme()
