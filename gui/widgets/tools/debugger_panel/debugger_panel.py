"""Themed host for DeviceDebugWidget on the Tools page."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets

import gui.theme as t


class DebuggerPanel(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._debug_widget: Optional[QtWidgets.QWidget] = None
        self._build()

    def embed_debug_widget(self, widget: QtWidgets.QWidget) -> None:
        if self._debug_widget is widget:
            return
        if self._debug_widget is not None:
            self._layout.removeWidget(self._debug_widget)
        self._debug_widget = widget
        widget.setParent(self)
        self._layout.addWidget(widget, 1)
        if hasattr(widget, "reload_vintage_theme"):
            widget.reload_vintage_theme()

    def _build(self) -> None:
        self.setObjectName("toolsDebuggerPanel")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_panel_style()
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(0)

    def _apply_panel_style(self) -> None:
        self.setStyleSheet(f"""
            #toolsDebuggerPanel {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.TOOLS_PANEL_TOP}, stop:1 {t.TOOLS_PANEL_BOT}
                );
                border: 1px solid {t.TOOLS_PANEL_BORDER};
                border-top: none;
                border-bottom-left-radius: {t.TOOLS_PANEL_RADIUS}px;
                border-bottom-right-radius: {t.TOOLS_PANEL_RADIUS}px;
            }}
        """)

    def reload_theme(self) -> None:
        self._apply_panel_style()
        w = self._debug_widget
        if w is not None and hasattr(w, "reload_vintage_theme"):
            w.reload_vintage_theme()
