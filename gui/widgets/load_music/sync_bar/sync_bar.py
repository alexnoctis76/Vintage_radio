"""
gui/widgets/load_music/sync_bar/sync_bar.py
=============================================
SyncBar — bottom action row on the Load Music page.

Contains:
  • "Sync to SD Card"  (primary orange gradient button)
  • "Safely Remove SD" (secondary light gradient button)

Sync preferences (conversion profile, auto-eject) live on the Settings page.
"""

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


_SVG_SD_CARD = _svg_resource("SD card.svg")


def _make_sd_card_icon(size: int = 32, color: str = "#ffffff") -> QtGui.QIcon:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)

    renderer = QtSvg.QSvgRenderer(str(_SVG_SD_CARD))
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(p, QtCore.QRectF(pix.rect()))

    p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(pix.rect(), QtGui.QColor(color))
    p.end()
    return QtGui.QIcon(pix)


def _make_eject_icon(size: int = 32, color: str = "#352516") -> QtGui.QIcon:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    c = QtGui.QColor(color)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QBrush(c))

    cx = size // 2
    top_y = 5
    bot_y = top_y + 13
    half_b = 9
    tri = QtGui.QPolygonF([
        QtCore.QPointF(cx, top_y),
        QtCore.QPointF(cx + half_b, bot_y),
        QtCore.QPointF(cx - half_b, bot_y),
    ])
    p.drawPolygon(tri)
    p.drawRect(cx - 9, bot_y + 3, 18, 4)

    p.end()
    return QtGui.QIcon(pix)


def _sync_btn_style() -> str:
    return f"""
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
            text-align: center;
        }}
        QPushButton:hover   {{ background: {t.SYNC_BTN_GRAD_MID}; }}
        QPushButton:pressed {{ background: {t.SYNC_BTN_GRAD_BOT}; }}
    """


def _eject_btn_style() -> str:
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.EJECT_BTN_GRAD_TOP},
                stop:1 {t.EJECT_BTN_GRAD_BOT}
            );
            color: {t.TEXT_PRI};
            border: 2px solid {t.BORDER};
            border-radius: {u.px(t.LM_EJECT_BTN_RADIUS)}px;
            padding: {t.LM_EJECT_BTN_PADDING};
            font-size: {u.px(t.LM_EJECT_BTN_FONT)}px;
            text-align: center;
        }}
        QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; }}
        QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; }}
    """


class SyncBar(QtWidgets.QWidget):
    """Bottom sync action row on the Load Music page."""

    sync_clicked = pyqtSignal()
    eject_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._sync_btn: QtWidgets.QPushButton
        self._eject_btn: QtWidgets.QPushButton
        self._build()

    def _build(self) -> None:
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, t.LM_SYNC_TOP_MARGIN, 0, 0)
        row.setSpacing(t.LM_SYNC_SPACING)

        row.addStretch()

        icon_sz = u.px(22)
        self._sync_btn = QtWidgets.QPushButton("  Sync to SD Card")
        self._sync_btn.setIcon(_make_sd_card_icon(icon_sz, t.SYNC_ICON_COLOR))
        self._sync_btn.setIconSize(QtCore.QSize(icon_sz, icon_sz))
        self._sync_btn.setFixedSize(u.px(t.LM_SYNC_BTN_W), u.px(t.LM_SYNC_BTN_H))
        self._sync_btn.setToolTip("Copy all stations to the SD card in DFPlayer folder format.")
        self._sync_btn.setStyleSheet(_sync_btn_style())
        self._sync_btn.clicked.connect(self.sync_clicked)
        self._add_shadow(self._sync_btn)
        row.addWidget(self._sync_btn)

        self._eject_btn = QtWidgets.QPushButton("  Safely Remove SD")
        self._eject_btn.setIcon(_make_eject_icon(icon_sz, t.EJECT_ICON_COLOR))
        self._eject_btn.setIconSize(QtCore.QSize(icon_sz, icon_sz))
        self._eject_btn.setFixedSize(u.px(t.LM_EJECT_BTN_W), u.px(t.LM_SYNC_BTN_H))
        self._eject_btn.setStyleSheet(_eject_btn_style())
        self._eject_btn.clicked.connect(self.eject_clicked)
        self._add_shadow(self._eject_btn)
        row.addWidget(self._eject_btn)

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
        self._sync_btn.setIcon(_make_sd_card_icon(icon_sz, t.SYNC_ICON_COLOR))
        self._sync_btn.setIconSize(QtCore.QSize(icon_sz, icon_sz))
        self._sync_btn.setFixedSize(u.px(t.LM_SYNC_BTN_W), u.px(t.LM_SYNC_BTN_H))
        self._sync_btn.setStyleSheet(_sync_btn_style())
        self._eject_btn.setIcon(_make_eject_icon(icon_sz, t.EJECT_ICON_COLOR))
        self._eject_btn.setIconSize(QtCore.QSize(icon_sz, icon_sz))
        self._eject_btn.setFixedSize(u.px(t.LM_EJECT_BTN_W), u.px(t.LM_SYNC_BTN_H))
        self._eject_btn.setStyleSheet(_eject_btn_style())
