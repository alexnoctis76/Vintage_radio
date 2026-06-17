"""Bottom action row — status, Install firmware, Advanced tools."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u


def _svg_resource(filename: str) -> Path:
    from gui.resource_paths import gui_dir
    return gui_dir() / "resources" / filename


def _make_firmware_icon(size: int = 24, color: str = "#ffffff") -> QtGui.QIcon:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QtSvg.QSvgRenderer(str(_svg_resource("Install Firmware.svg")))
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(p, QtCore.QRectF(pix.rect()))
    p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(pix.rect(), QtGui.QColor(color))
    p.end()
    return QtGui.QIcon(pix)


class InstallActionBar(QtWidgets.QWidget):
    install_clicked = pyqtSignal()
    advanced_tools_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._adv_btn: QtWidgets.QPushButton
        self._build()

    @property
    def install_btn(self) -> QtWidgets.QPushButton:
        return self._install_btn

    @property
    def status_label(self) -> QtWidgets.QLabel:
        return self._status

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def _build(self) -> None:
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, t.LM_SYNC_TOP_MARGIN, 0, 0)
        row.setSpacing(t.LM_SYNC_SPACING)

        self._status = QtWidgets.QLabel("Ready to install.")
        self._status.setStyleSheet(
            f"color:{t.TEXT_SEC}; font-size:{u.px(t.IF_STATUS_FONT_SIZE)}px; font-weight:600;"
        )
        row.addWidget(self._status, 1)

        icon_sz = u.px(22)
        self._install_btn = QtWidgets.QPushButton("  Install Firmware")
        self._install_btn.setIcon(_make_firmware_icon(icon_sz, t.SYNC_ICON_COLOR))
        self._install_btn.setIconSize(QtCore.QSize(icon_sz, icon_sz))
        self._install_btn.setFixedSize(u.px(t.IF_INSTALL_BTN_W), u.px(t.LM_SYNC_BTN_H))
        self._install_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._install_btn.setToolTip(
            "Install the selected software. Official Vintage Radio uses a bundled full-flash "
            ".uf2 when available; otherwise copies firmware over USB (MicroPython is installed "
            "automatically when possible). Community .uf2 files install in BOOTSEL mode."
        )
        self._install_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0   {t.SYNC_BTN_GRAD_TOP},
                    stop:0.5 {t.SYNC_BTN_GRAD_MID},
                    stop:1   {t.SYNC_BTN_GRAD_BOT}
                );
                color: #ffffff;
                border: 2px solid {t.SYNC_BTN_BORDER};
                border-radius: {u.px(t.LM_SYNC_BTN_RADIUS)}px;
                padding: {t.LM_SYNC_BTN_PADDING};
                font-weight: bold;
                font-size: {u.px(t.LM_SYNC_BTN_FONT)}px;
            }}
            QPushButton:hover   {{ background: {t.SYNC_BTN_GRAD_MID}; }}
            QPushButton:pressed {{ background: {t.SYNC_BTN_GRAD_BOT}; }}
            QPushButton:disabled {{ color: rgba(255,255,255,0.55); }}
        """)
        self._install_btn.clicked.connect(self.install_clicked.emit)
        self._add_shadow(self._install_btn)
        row.addWidget(self._install_btn)

        self._adv_btn = QtWidgets.QPushButton("Advanced tools…")
        self._adv_btn.setFlat(True)
        self._adv_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._adv_btn.setToolTip(
            "Open the device console: connect, view serial output, send commands, "
            "and inspect playback."
        )
        self._adv_btn.setStyleSheet(f"""
            QPushButton {{
                color: {t.TEXT_PRI};
                font-size: {u.px(t.IF_STATUS_FONT_SIZE)}px;
                font-weight: 700;
                border: none;
                padding: 4px 8px;
                text-decoration: underline;
            }}
            QPushButton:hover {{ color: {t.NAV_ACTIVE_GRAD_TOP}; }}
        """)
        self._adv_btn.clicked.connect(self.advanced_tools_clicked.emit)
        row.addWidget(self._adv_btn)

    def _add_shadow(self, btn: QtWidgets.QPushButton) -> None:
        shadow = QtWidgets.QGraphicsDropShadowEffect(btn)
        shadow.setBlurRadius(t.BTN_SHADOW_BLUR)
        shadow.setOffset(0, t.BTN_SHADOW_OFFSET)
        col = QtGui.QColor(t.BTN_SHADOW_COLOR)
        col.setAlpha(t.BTN_SHADOW_ALPHA)
        shadow.setColor(col)
        btn.setGraphicsEffect(shadow)

    def reload_theme(self) -> None:
        icon_sz = u.px(22)
        self._install_btn.setIcon(_make_firmware_icon(icon_sz, t.SYNC_ICON_COLOR))
        self._install_btn.setIconSize(QtCore.QSize(icon_sz, icon_sz))
        self._install_btn.setFixedSize(u.px(t.IF_INSTALL_BTN_W), u.px(t.LM_SYNC_BTN_H))
        self._install_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0   {t.SYNC_BTN_GRAD_TOP},
                    stop:0.5 {t.SYNC_BTN_GRAD_MID},
                    stop:1   {t.SYNC_BTN_GRAD_BOT}
                );
                color: #ffffff;
                border: 2px solid {t.SYNC_BTN_BORDER};
                border-radius: {u.px(t.LM_SYNC_BTN_RADIUS)}px;
                padding: {t.LM_SYNC_BTN_PADDING};
                font-weight: bold;
                font-size: {u.px(t.LM_SYNC_BTN_FONT)}px;
            }}
            QPushButton:hover   {{ background: {t.SYNC_BTN_GRAD_MID}; }}
            QPushButton:pressed {{ background: {t.SYNC_BTN_GRAD_BOT}; }}
            QPushButton:disabled {{ color: rgba(255,255,255,0.55); }}
        """)
        self._status.setStyleSheet(
            f"color:{t.TEXT_SEC}; font-size:{u.px(t.IF_STATUS_FONT_SIZE)}px; font-weight:600;"
        )
        self._adv_btn.setStyleSheet(f"""
            QPushButton {{
                color: {t.TEXT_PRI};
                font-size: {u.px(t.IF_STATUS_FONT_SIZE)}px;
                font-weight: 700;
                border: none;
                padding: 4px 8px;
                text-decoration: underline;
            }}
            QPushButton:hover {{ color: {t.NAV_ACTIVE_GRAD_TOP}; }}
        """)
