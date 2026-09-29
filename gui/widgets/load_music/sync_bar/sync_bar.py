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
from gui.widgets.common.styled_checkbox import VintageCheckBox
from gui.widgets.common.styled_spin import VintageSpinBox


def _svg_resource(filename: str) -> Path:
    from gui.resource_paths import gui_dir
    return gui_dir() / "resources" / filename


_SVG_SD_CARD = _svg_resource("SD card.svg")

from gui.commercials import (
    COMMERCIALS_STATION_LABEL,
    COMMERCIALS_STATION_TOOLTIP,
    COMMERCIALS_TAGGED_LABEL,
    COMMERCIALS_TAGGED_TOOLTIP,
)


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
    commercials_toggled = pyqtSignal(bool)
    commercials_interval_changed = pyqtSignal(int)
    inline_commercials_toggled = pyqtSignal(bool)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._sync_btn: QtWidgets.QPushButton
        self._eject_btn: QtWidgets.QPushButton
        self._build()

    def _build(self) -> None:
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, t.LM_SYNC_TOP_MARGIN, 0, 0)
        row.setSpacing(t.LM_SYNC_SPACING)

        row.addWidget(self._make_commercials_group(), 0)
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

    def _make_commercials_group(self) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        box.setObjectName("commercialsSyncGroup")
        box.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        col = QtWidgets.QVBoxLayout(box)
        col.setContentsMargins(0, 0, 12, 0)
        col.setSpacing(4)

        title = QtWidgets.QLabel("Commercials / sweepers")
        title.setStyleSheet(
            f"color: {t.TEXT_PRI}; font-weight: 800; "
            f"font-size: {u.px(t.LM_EJECT_BTN_FONT)}px; background: transparent;"
        )
        self._commercials_title = title
        col.addWidget(title)

        hint = QtWidgets.QLabel("Choose how ads play on this library")
        hint.setStyleSheet(
            f"color: {t.TEXT_SEC}; font-size: {u.px(max(11, t.LM_EJECT_BTN_FONT - 1))}px; "
            f"background: transparent;"
        )
        self._commercials_hint = hint
        col.addWidget(hint)

        type_row = QtWidgets.QHBoxLayout()
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(u.px(14))
        self._commercials_type_row = type_row

        self.commercials_check = VintageCheckBox(COMMERCIALS_STATION_LABEL)
        self.commercials_check.setToolTip(COMMERCIALS_STATION_TOOLTIP)
        self.commercials_check.toggled.connect(self.commercials_toggled)
        type_row.addWidget(self.commercials_check)

        self.commercials_interval = VintageSpinBox()
        self.commercials_interval.setRange(1, 99)
        self.commercials_interval.setValue(5)
        self.commercials_interval.setToolTip(
            "Number of songs between commercials from the Commercials station."
        )
        self.commercials_interval.valueChanged.connect(self.commercials_interval_changed)
        self.commercials_interval.setVisible(False)
        type_row.addWidget(self.commercials_interval)

        self.inline_check = VintageCheckBox(COMMERCIALS_TAGGED_LABEL)
        self.inline_check.setToolTip(COMMERCIALS_TAGGED_TOOLTIP)
        self.inline_check.toggled.connect(self.inline_commercials_toggled)
        type_row.addWidget(self.inline_check)
        type_row.addStretch()
        col.addLayout(type_row)
        self._commercials_bar = box
        return box

    def set_commercials_visible(self, visible: bool) -> None:
        bar = getattr(self, "_commercials_bar", None)
        if bar is not None:
            bar.setVisible(bool(visible))

    def set_commercials_state(
        self,
        *,
        enabled: bool,
        interval: int,
        inline: bool = False,
        folder: Optional[bool] = None,
    ) -> None:
        self.commercials_check.blockSignals(True)
        self.commercials_interval.blockSignals(True)
        self.inline_check.blockSignals(True)
        try:
            folder_on = bool(enabled) if folder is None else bool(folder)
            if folder is None:
                folder_on = bool(enabled) and not inline
            self.commercials_check.setChecked(folder_on)
            self.inline_check.setChecked(bool(inline))
            self.commercials_interval.setValue(max(1, min(99, int(interval or 5))))
            show_interval = folder_on
            self.commercials_interval.setVisible(show_interval)
            self.commercials_interval.setEnabled(show_interval)
        finally:
            self.commercials_check.blockSignals(False)
            self.commercials_interval.blockSignals(False)
            self.inline_check.blockSignals(False)

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
        title = getattr(self, "_commercials_title", None)
        hint = getattr(self, "_commercials_hint", None)
        if title is not None:
            title.setStyleSheet(
                f"color: {t.TEXT_PRI}; font-weight: 800; "
                f"font-size: {u.px(t.LM_EJECT_BTN_FONT)}px; background: transparent;"
            )
        if hint is not None:
            hint.setStyleSheet(
                f"color: {t.TEXT_SEC}; font-size: {u.px(max(11, t.LM_EJECT_BTN_FONT - 1))}px; "
                f"background: transparent;"
            )
        type_row = getattr(self, "_commercials_type_row", None)
        if type_row is not None:
            type_row.setSpacing(u.px(14))
        self.commercials_check.apply_theme()
        self.inline_check.apply_theme()
        self.commercials_interval.apply_theme()
