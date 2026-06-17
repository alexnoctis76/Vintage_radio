"""Tools tab panel — install stock MicroPython on a Pico (BOOTSEL)."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u


class MicroPythonPanel(QtWidgets.QWidget):
    install_clicked = QtCore.pyqtSignal()

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        on_install: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_install = on_install
        self._build()
        if on_install is not None:
            self.install_clicked.connect(on_install)

    def _build(self) -> None:
        self.setObjectName("toolsMicroPythonPanel")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(u.px(t.TOOLS_PANEL_PAD), u.px(t.TOOLS_PANEL_PAD), u.px(t.TOOLS_PANEL_PAD), u.px(t.TOOLS_PANEL_PAD))
        outer.setSpacing(u.px(t.TOOLS_SECTION_GAP))

        card = QtWidgets.QFrame()
        card.setObjectName("toolsMicroPythonCard")
        card.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(u.px(16), u.px(16), u.px(16), u.px(16))
        lay.setSpacing(u.px(10))

        title = QtWidgets.QLabel("MicroPython for Pico")
        title.setStyleSheet(
            f"color:{t.TEXT_PRI}; font-size:{u.px(t.TOOLS_SECTION_TITLE_PX)}px; font-weight:900;"
        )
        lay.addWidget(title)

        body = QtWidgets.QLabel(
            "Install the official MicroPython runtime only — use this when you want a bare "
            "MicroPython board, need to recover from a bad flash, or before copying custom "
            "Python firmware with Thonny or mpremote.\n\n"
            "Vintage Radio firmware on the Install Firmware tab normally handles MicroPython "
            "for you automatically when needed."
        )
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color:{t.TOOLS_MUTED_FG}; font-size:{u.px(t.TOOLS_ACTION_BTN_FONT)}px; font-weight:600;"
        )
        lay.addWidget(body)

        steps = QtWidgets.QLabel(
            "1. Hold BOOTSEL on the Pico and plug in USB (RPI-RP2 drive appears).\n"
            "2. Click Install MicroPython below and pick a version.\n"
            "3. After reboot, install Vintage Radio from the Install Firmware tab."
        )
        steps.setWordWrap(True)
        steps.setStyleSheet(
            f"color:{t.TEXT_SEC}; font-size:{u.px(t.TOOLS_ACTION_BTN_FONT)}px;"
        )
        lay.addWidget(steps)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        self._install_btn = QtWidgets.QPushButton("Install MicroPython on Pico…")
        self._install_btn.setFixedHeight(u.px(t.TOOLS_ACTION_BTN_H))
        self._install_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._install_btn.setToolTip(
            "Copy an official MicroPython .uf2 to the Pico in BOOTSEL mode."
        )
        self._install_btn.clicked.connect(self.install_clicked.emit)
        self._install_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {t.TOOLS_EDITOR_BTN_TOP}, stop:1 {t.TOOLS_EDITOR_BTN_BOT});
                color: #ffffff;
                border: 2px solid {t.TOOLS_EDITOR_BTN_BORDER};
                border-radius: {u.px(t.TOOLS_PATH_FIELD_RADIUS)}px;
                padding: 4px 14px;
                font-weight: bold;
                font-size: {u.px(t.TOOLS_ACTION_BTN_FONT)}px;
            }}
            QPushButton:hover {{ background: {t.TOOLS_EDITOR_BTN_TOP}; }}
        """)
        btn_row.addWidget(self._install_btn)
        lay.addLayout(btn_row)

        outer.addWidget(card)
        outer.addStretch(1)
        self._apply_panel_style()

    def _apply_panel_style(self) -> None:
        self.setStyleSheet(f"""
            #toolsMicroPythonPanel {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.TOOLS_PANEL_TOP}, stop:1 {t.TOOLS_PANEL_BOT}
                );
                border: 1px solid {t.TOOLS_PANEL_BORDER};
                border-top: none;
                border-bottom-left-radius: {t.TOOLS_PANEL_RADIUS}px;
                border-bottom-right-radius: {t.TOOLS_PANEL_RADIUS}px;
            }}
            #toolsMicroPythonCard {{
                background: {t.TOOLS_INPUT_BG};
                border: 1px solid {t.TOOLS_INPUT_BORDER};
                border-radius: {u.px(t.TOOLS_PATH_FIELD_RADIUS)}px;
            }}
        """)

    def reload_theme(self) -> None:
        self._apply_panel_style()
