"""
gui/widgets/load_music/storage_section/storage_section.py
===========================================================
StorageSection — "Storage" heading + SD drive label + capacity bar + buttons.

Sits directly below the Library Bar on the Load Music page.

HOW TO EDIT
-----------
  • "Storage" heading font      → t.LM_HEADING_FONT_SIZE  (pt)
  • Heading colour              → t.TEXT_PRI
  • Vertical gap (heading→bar)  → t.LM_STORAGE_SECTION_SPACING  (px)
  • Bar row element gap         → t.LM_STORAGE_ROW_SPACING  (px)
  • Capacity bar height         → t.LM_CAPACITY_BAR_H  (px)
  • Capacity bar min width      → t.LM_CAPACITY_BAR_MIN_W  (px)
  • Capacity bar max width      → t.LM_CAPACITY_BAR_MAX_W  (px)
  • Capacity bar corner radius  → t.LM_CAPACITY_BAR_RADIUS  (px)
  • Bar border colour           → t.LM_CAPACITY_BAR_BORDER
  • Bar track gradient          → t.CAP_TRACK_GRAD_TOP / BOT
  • Bar fill gradient           → t.CAP_FILL_GRAD_TOP / MID / BOT
  • Detect / Select button h    → t.LM_SD_BTN_H  (px)
  • Detect / Select btn radius  → t.LM_SD_BTN_RADIUS  (px)
  • Detect / Select btn font    → t.LM_SD_BTN_FONT  (pt)
  • Detect / Select btn border  → t.LM_SD_BTN_BORDER
"""

from __future__ import annotations
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t


class _CapacityBar(QtWidgets.QWidget):
    """Custom capacity bar with properly rounded fill ends at any fill level.

    QProgressBar::chunk in Qt does not reliably clip partial-fill rounded
    corners.  This widget draws both the track and the fill with QPainter so
    the right end of the fill is always rounded, not square.

    HOW TO EDIT
    -----------
      • Bar height        → t.LM_CAPACITY_BAR_H
      • Corner radius     → t.LM_CAPACITY_BAR_RADIUS
      • Border colour     → t.LM_CAPACITY_BAR_BORDER
      • Track gradient    → t.CAP_TRACK_GRAD_TOP / BOT
      • Fill gradient     → t.CAP_FILL_GRAD_TOP / MID / BOT
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._value = 0       # 0-100
        self._minimum = 0
        self._maximum = 100
        self.setFixedHeight(t.LM_CAPACITY_BAR_H)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    # ── QProgressBar-compatible API ───────────────────────────────────────────
    def setValue(self, value: int) -> None:
        self._value = max(self._minimum, min(self._maximum, value))
        self.update()

    def value(self) -> int:
        return self._value

    def setMinimum(self, v: int) -> None:
        self._minimum = v

    def setMaximum(self, v: int) -> None:
        self._maximum = v

    def setRange(self, minimum: int, maximum: int) -> None:
        self._minimum = minimum
        self._maximum = maximum

    def setFormat(self, _: str) -> None:
        pass  # text not shown

    def setTextVisible(self, _: bool) -> None:
        pass

    # ── Paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = self.rect()
        border_w = 2
        radius   = t.LM_CAPACITY_BAR_RADIUS
        inner_r  = max(1, radius - border_w)

        # 1. Track (background) — drawn as a filled rounded rect
        track_grad = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        track_grad.setColorAt(0.0, QtGui.QColor(t.CAP_TRACK_GRAD_TOP))
        track_grad.setColorAt(1.0, QtGui.QColor(t.CAP_TRACK_GRAD_BOT))
        p.setPen(QtGui.QPen(QtGui.QColor(t.LM_CAPACITY_BAR_BORDER), border_w))
        p.setBrush(QtGui.QBrush(track_grad))
        p.drawRoundedRect(
            QtCore.QRectF(r).adjusted(border_w / 2, border_w / 2,
                                       -border_w / 2, -border_w / 2),
            radius, radius,
        )

        # 2. Fill — clipped to inner area so it never overflows the border
        span = self._maximum - self._minimum
        fraction = (self._value - self._minimum) / span if span > 0 else 0.0
        inner = QtCore.QRectF(r).adjusted(border_w, border_w, -border_w, -border_w)
        fill_w = inner.width() * fraction
        if fill_w > 1:
            p.save()
            # Clip to the inner rect so the fill can't exceed the bar bounds
            p.setClipRect(inner)
            fill_grad = QtGui.QLinearGradient(0, inner.top(), 0, inner.bottom())
            fill_grad.setColorAt(0.0,  QtGui.QColor(t.CAP_FILL_GRAD_TOP))
            fill_grad.setColorAt(0.5,  QtGui.QColor(t.CAP_FILL_GRAD_MID))
            fill_grad.setColorAt(1.0,  QtGui.QColor(t.CAP_FILL_GRAD_BOT))
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QBrush(fill_grad))
            fill_rect = QtCore.QRectF(inner.x(), inner.y(), fill_w, inner.height())
            p.drawRoundedRect(fill_rect, inner_r, inner_r)
            p.restore()

        p.end()


class StorageSection(QtWidgets.QWidget):
    """'Storage' heading + SD drive label + capacity bar + Detect / Select."""

    detect_clicked = pyqtSignal()
    select_clicked = pyqtSignal()
    browse_clicked = pyqtSignal()

    def __init__(self, sd_root: str = "",
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._sd_root = sd_root
        self._build()

    # ── Public widget references ───────────────────────────────────────────────
    @property
    def sd_root_label(self) -> QtWidgets.QLabel:
        return self._root_label

    @property
    def capacity_bar(self) -> _CapacityBar:
        return self._bar

    @property
    def percent_label(self) -> QtWidgets.QLabel:
        return self._pct_label

    @property
    def capacity_label(self) -> QtWidgets.QLabel:
        return self._cap_label

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.LM_STORAGE_SECTION_SPACING)

        # ── "Storage" heading ─────────────────────────────────────────────────
        heading = QtWidgets.QLabel("Storage")
        heading.setStyleSheet(
            f"font-weight: bold;"
            f"font-size: {t.LM_HEADING_FONT_SIZE}px;"
            f"color: {t.TEXT_PRI};"
        )
        v.addWidget(heading)

        # ── Capacity row ──────────────────────────────────────────────────────
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(t.LM_STORAGE_ROW_SPACING)

        drive_lbl = QtWidgets.QLabel("SD Drive:")
        drive_lbl.setStyleSheet(f"color: {t.TEXT_SEC};")
        row.addWidget(drive_lbl)

        self._root_label = QtWidgets.QLabel(self._sd_root or "(not set)")
        self._root_label.setStyleSheet(f"color: {t.TEXT_PRI}; font-weight: bold;")
        row.addWidget(self._root_label)

        self._bar = _CapacityBar()
        self._bar.setMinimumWidth(t.LM_CAPACITY_BAR_MIN_W)
        self._bar.setMaximumWidth(t.LM_CAPACITY_BAR_MAX_W)
        self._bar.setValue(0)
        row.addWidget(self._bar)

        self._pct_label = QtWidgets.QLabel("")
        self._pct_label.setStyleSheet(f"color: {t.TEXT_SEC};")
        row.addWidget(self._pct_label)

        self._cap_label = QtWidgets.QLabel("")
        self._cap_label.setStyleSheet(f"color: {t.TEXT_SEC};")
        row.addWidget(self._cap_label)

        row.addStretch(1)

        _btn_qss = self._btn_qss()

        detect_btn = QtWidgets.QPushButton("Detect")
        detect_btn.setFixedHeight(t.LM_SD_BTN_H)
        detect_btn.setToolTip(
            "Find your SD card again using the saved volume name (e.g. after reconnecting USB).\n"
            "Does not ask to confirm a different card."
        )
        detect_btn.setStyleSheet(_btn_qss)
        detect_btn.clicked.connect(self.detect_clicked)
        self._add_btn_shadow(detect_btn)
        row.addWidget(detect_btn)

        select_btn = QtWidgets.QPushButton("Select")
        select_btn.setFixedHeight(t.LM_SD_BTN_H)
        select_btn.setToolTip(
            "Pick from detected removable drives (dropdown).\n"
            "If nothing is listed, use Browse.  Wrong-card safety is only on Sync."
        )
        select_btn.setStyleSheet(_btn_qss)
        select_btn.clicked.connect(self.select_clicked)
        self._add_btn_shadow(select_btn)
        row.addWidget(select_btn)

        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.setFixedHeight(t.LM_SD_BTN_H)
        browse_btn.setStyleSheet(_btn_qss)
        browse_btn.clicked.connect(self.browse_clicked)
        browse_btn.setVisible(False)
        row.addWidget(browse_btn)

        v.addLayout(row)

    def _add_btn_shadow(self, btn: QtWidgets.QPushButton) -> None:
        shadow = QtWidgets.QGraphicsDropShadowEffect(btn)
        shadow.setBlurRadius(t.BTN_SHADOW_BLUR)
        shadow.setOffset(0, t.BTN_SHADOW_OFFSET)
        col = QtGui.QColor(t.BTN_SHADOW_COLOR)
        col.setAlpha(t.BTN_SHADOW_ALPHA)
        shadow.setColor(col)
        btn.setGraphicsEffect(shadow)

    def _btn_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: qlineargradient("
            f"    x1:0, y1:0, x2:0, y2:1,"
            f"    stop:0 {t.OUTLINE_BTN_GRAD_TOP},"
            f"    stop:1 {t.OUTLINE_BTN_GRAD_BOT}"
            f"  );"
            f"  border: 2px solid {t.LM_SD_BTN_BORDER};"
            f"  border-radius: {t.LM_SD_BTN_RADIUS}px;"
            f"  padding: {t.LM_SD_BTN_PADDING};"
            f"  font-size: {t.LM_SD_BTN_FONT}px;"
            f"  color: {t.TEXT_PRI};"
            f"}}"
            f"QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; }}"
            f"QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; }}"
        )

    def reload_theme(self) -> None:
        self._bar.setFixedHeight(t.LM_CAPACITY_BAR_H)
        self._bar.update()
