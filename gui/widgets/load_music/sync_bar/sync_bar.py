"""
gui/widgets/load_music/sync_bar/sync_bar.py
=============================================
SyncBar — bottom action row on the Load Music page.

Contains:
  • (Advanced-only) Conversion Profile selector
  • Auto-eject checkbox
  • "Sync to SD Card"  (primary orange gradient button)
  • "Safely Remove SD" (secondary light gradient button)

HOW TO EDIT
-----------
  • Top gap above the bar     → t.LM_SYNC_TOP_MARGIN  (px)
  • Gap between elements      → t.LM_SYNC_SPACING  (px)
  • Sync button height        → t.LM_SYNC_BTN_H  (px)
  • Sync button radius        → t.LM_SYNC_BTN_RADIUS  (px)
  • Sync button padding       → t.LM_SYNC_BTN_PADDING
  • Sync button font          → t.LM_SYNC_BTN_FONT  (pt)
  • Sync button gradient      → t.SYNC_BTN_GRAD_TOP / MID / BOT
  • Sync button border        → t.SYNC_BTN_BORDER
  • Eject button height       → same as Sync (t.LM_SYNC_BTN_H)
  • Eject button radius       → t.LM_EJECT_BTN_RADIUS  (px)
  • Eject button padding      → t.LM_EJECT_BTN_PADDING
  • Eject button gradient     → t.EJECT_BTN_GRAD_TOP / BOT
  • Eject button border       → t.BORDER
  • Drop shadow on buttons    → t.BTN_SHADOW_*
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t


def _svg_resource(filename: str) -> Path:
    """Return the absolute path to an SVG in gui/resources/."""
    from gui.resource_paths import gui_dir
    return gui_dir() / "resources" / filename


_SVG_SD_CARD = _svg_resource("SD card.svg")


def _make_sd_card_icon(size: int = 32, color: str = "#ffffff") -> QtGui.QIcon:
    """Render the user-supplied SD card SVG from gui/resources/SD card.svg."""
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
    """Draw an eject (triangle + bar) icon as a QIcon pixmap using QPainter paths.

    Shape: upward triangle with a horizontal bar below it.
    The icon colour is controlled by t.EJECT_ICON_COLOR.

    HOW TO EDIT
    -----------
      Icon colour  → t.EJECT_ICON_COLOR
      Icon size    → `size` argument (default 32px canvas)
    """
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    c = QtGui.QColor(color)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QBrush(c))

    # Upward-pointing triangle: base 18px wide, 13px tall, centred horizontally
    cx = size // 2
    top_y  = 5
    bot_y  = top_y + 13
    half_b = 9
    tri = QtGui.QPolygonF([
        QtCore.QPointF(cx, top_y),
        QtCore.QPointF(cx + half_b, bot_y),
        QtCore.QPointF(cx - half_b, bot_y),
    ])
    p.drawPolygon(tri)

    # Horizontal bar below triangle (4px tall)
    p.drawRect(cx - 9, bot_y + 3, 18, 4)

    p.end()
    return QtGui.QIcon(pix)


class SyncBar(QtWidgets.QWidget):
    """Bottom sync action row on the Load Music page."""

    sync_clicked       = pyqtSignal()
    eject_clicked      = pyqtSignal()
    auto_eject_changed = pyqtSignal(int)

    def __init__(self, is_advanced: bool = False,
                 auto_eject_checked: bool = False,
                 conversion_profile: str = "dfplayer_safe",
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._is_advanced        = is_advanced
        self._auto_eject_checked = auto_eject_checked
        self._conversion_profile = conversion_profile
        self._build()

    # ── Public widget references ───────────────────────────────────────────────
    @property
    def auto_eject_checkbox(self) -> QtWidgets.QCheckBox:
        return self._auto_eject_cb

    @property
    def conversion_profile_combo(self) -> Optional[QtWidgets.QComboBox]:
        return getattr(self, "_conv_combo", None)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, t.LM_SYNC_TOP_MARGIN, 0, 0)
        row.setSpacing(t.LM_SYNC_SPACING)

        if self._is_advanced:
            conv_box = QtWidgets.QGroupBox("Conversion Profile")
            conv_lay = QtWidgets.QHBoxLayout(conv_box)
            self._conv_combo = QtWidgets.QComboBox()
            self._conv_combo.addItem("DFPlayer-safe (default)", "dfplayer_safe")
            self._conv_combo.addItem("Higher quality (advanced)", "high_quality")
            self._conv_combo.setCurrentIndex(
                1 if self._conversion_profile == "high_quality" else 0
            )
            conv_lay.addWidget(self._conv_combo)
            row.addWidget(conv_box)

        self._auto_eject_cb = QtWidgets.QCheckBox(
            "Automatically safely remove SD card after syncing"
        )
        self._auto_eject_cb.setChecked(self._auto_eject_checked)
        self._auto_eject_cb.stateChanged.connect(self.auto_eject_changed)
        row.addWidget(self._auto_eject_cb)

        row.addStretch()

        sync_btn = QtWidgets.QPushButton("  Sync to SD Card")
        sync_btn.setIcon(_make_sd_card_icon(24, t.SYNC_ICON_COLOR))
        sync_btn.setIconSize(QtCore.QSize(22, 22))
        sync_btn.setFixedSize(t.LM_SYNC_BTN_W, t.LM_SYNC_BTN_H)
        sync_btn.setToolTip("Copy all stations to the SD card in DFPlayer folder format.")
        sync_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0   {t.SYNC_BTN_GRAD_TOP},
                    stop:0.5 {t.SYNC_BTN_GRAD_MID},
                    stop:1   {t.SYNC_BTN_GRAD_BOT}
                );
                color: #ffffff;
                border: 2px solid {t.SYNC_BTN_BORDER};
                border-radius: {t.LM_SYNC_BTN_RADIUS}px;
                padding: {t.LM_SYNC_BTN_PADDING};
                font-weight: bold;
                font-size: {t.LM_SYNC_BTN_FONT}px;
                text-align: center;
            }}
            QPushButton:hover   {{ background: {t.SYNC_BTN_GRAD_MID}; }}
            QPushButton:pressed {{ background: {t.SYNC_BTN_GRAD_BOT}; }}
        """)
        sync_btn.clicked.connect(self.sync_clicked)
        self._add_shadow(sync_btn)
        row.addWidget(sync_btn)

        eject_btn = QtWidgets.QPushButton("  Safely Remove SD")
        eject_btn.setIcon(_make_eject_icon(24, t.EJECT_ICON_COLOR))
        eject_btn.setIconSize(QtCore.QSize(22, 22))
        eject_btn.setFixedSize(t.LM_EJECT_BTN_W, t.LM_SYNC_BTN_H)
        eject_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.EJECT_BTN_GRAD_TOP},
                    stop:1 {t.EJECT_BTN_GRAD_BOT}
                );
                color: {t.TEXT_PRI};
                border: 2px solid {t.BORDER};
                border-radius: {t.LM_EJECT_BTN_RADIUS}px;
                padding: {t.LM_EJECT_BTN_PADDING};
                font-size: {t.LM_EJECT_BTN_FONT}px;
                text-align: center;
            }}
            QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; }}
            QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; }}
        """)
        eject_btn.clicked.connect(self.eject_clicked)
        self._add_shadow(eject_btn)
        row.addWidget(eject_btn)

    def _add_shadow(self, btn: QtWidgets.QPushButton) -> None:
        shadow = QtWidgets.QGraphicsDropShadowEffect(btn)
        shadow.setBlurRadius(t.BTN_SHADOW_BLUR)
        shadow.setOffset(0, t.BTN_SHADOW_OFFSET)
        col = QtGui.QColor(t.BTN_SHADOW_COLOR)
        col.setAlpha(t.BTN_SHADOW_ALPHA)
        shadow.setColor(col)
        btn.setGraphicsEffect(shadow)
