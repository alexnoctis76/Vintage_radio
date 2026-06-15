"""
gui/widgets/library_bar/library_bar.py
========================================
LibraryBar — floating card shown above the page stack on every page
except Settings and Help.

Contains:
  • "Library:" label
  • Library selector dropdown (gradient background)
  • New / Rename / Delete action buttons (gradient background)

Visual style: rounded card with gradient fill, 1px border, drop shadow.

HOW TO EDIT
-----------
  • Bar height              → t.LIBBAR_HEIGHT  (px)
  • Card corner radius      → t.LIBBAR_RADIUS  (px)
  • Background gradient     → t.LIBBAR_GRAD_TOP / BOT
  • Border colour           → t.LIBBAR_BORDER
  • Drop shadow             → t.LIBBAR_SHADOW_*
  • Inner left/right margin → t.LIBBAR_H_MARGINS  (left, top, right, bottom)
  • Element gap             → t.LIBBAR_SPACING  (px)
  • "Library:" label font   → t.LIBBAR_LABEL_FONT_SIZE  (pt)
  • Dropdown height         → t.LIBBAR_COMBO_H  (px)
  • Dropdown corner radius  → t.LIBBAR_COMBO_RADIUS  (px)
  • Button height           → t.LIBBAR_BTN_H  (px)
  • Button corner radius    → t.LIBBAR_BTN_RADIUS  (px)
"""

from __future__ import annotations
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.styled_combo import VintageComboBox


class LibraryBar(QtWidgets.QWidget):
    """Top library-selector bar — styled as a floating card with gradient fill."""

    library_changed = pyqtSignal(int)
    new_clicked     = pyqtSignal()
    rename_clicked  = pyqtSignal()
    delete_clicked  = pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._build()

    # ── Public widget references ───────────────────────────────────────────────
    @property
    def combo(self) -> QtWidgets.QComboBox:
        return self._combo

    @property
    def heading_label(self) -> QtWidgets.QLabel:
        return self._heading

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName("libraryBar")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_bar_style()
        self.setFixedHeight(u.px(t.LIBBAR_HEIGHT))

        # Drop shadow
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(t.LIBBAR_SHADOW_BLUR)
        shadow.setOffset(0, t.LIBBAR_SHADOW_OFFSET)
        col = QtGui.QColor(t.LIBBAR_SHADOW_COLOR)
        col.setAlpha(t.LIBBAR_SHADOW_ALPHA)
        shadow.setColor(col)
        self.setGraphicsEffect(shadow)

        l, top, r, bot = t.LIBBAR_H_MARGINS
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(l, top, r, bot)
        row.setSpacing(t.LIBBAR_SPACING)

        # ── "Library:" label ──────────────────────────────────────────────────
        self._heading = QtWidgets.QLabel("Library:")
        self._heading.setStyleSheet(
            f"color: {t.TEXT_PRI};"
            f"font-size: {u.px(t.LIBBAR_LABEL_FONT_SIZE)}px;"
            f"font-weight: {'bold' if t.LIBBAR_LABEL_BOLD else 'normal'};"
            f"background: transparent;"
        )
        self._heading.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        row.addWidget(self._heading)

        # ── Library dropdown ──────────────────────────────────────────────────
        self._combo = VintageComboBox(
            min_width=t.LIBBAR_COMBO_MIN_W,
            max_width=9999,
            fixed_height=t.LIBBAR_COMBO_H,
        )
        self._combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._combo.currentIndexChanged.connect(self.library_changed)
        row.addWidget(self._combo, 1)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_qss = self._btn_qss()
        self._action_buttons: list[QtWidgets.QPushButton] = []
        for label, sig, tip in [
            ("New",    self.new_clicked,    "Create a new library"),
            ("Rename", self.rename_clicked, "Rename the current library"),
            ("Delete", self.delete_clicked, "Delete the current library"),
        ]:
            btn = QtWidgets.QPushButton(label)
            btn.setToolTip(tip)
            btn.setFixedSize(u.action_button_width(btn, t.LIBBAR_BTN_W), u.px(t.LIBBAR_BTN_H))
            btn.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Fixed,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            btn.setStyleSheet(btn_qss)
            btn.clicked.connect(sig)
            row.addWidget(btn)
            self._action_buttons.append(btn)

    def _apply_bar_style(self) -> None:
        self.setStyleSheet(f"""
            #libraryBar {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.LIBBAR_GRAD_TOP},
                    stop:1 {t.LIBBAR_GRAD_BOT}
                );
                border: {t.LIBBAR_BORDER_W}px solid {t.LIBBAR_BORDER};
                border-radius: {t.LIBBAR_RADIUS}px;
            }}
        """)

    def _btn_qss(self) -> str:
        return t.outline_button_stylesheet()

    # ── Theme reload ───────────────────────────────────────────────────────────

    def apply_ui_zoom(self) -> None:
        self.reload_theme()

    def reload_theme(self) -> None:
        self.setFixedHeight(u.px(t.LIBBAR_HEIGHT))
        lay = self.layout()
        if lay is not None:
            l, top, r, bot = t.LIBBAR_H_MARGINS
            lay.setContentsMargins(l, top, r, bot)
            lay.setSpacing(t.LIBBAR_SPACING)
        self._heading.setStyleSheet(
            f"color: {t.TEXT_PRI};"
            f"font-size: {u.px(t.LIBBAR_LABEL_FONT_SIZE)}px;"
            f"font-weight: {'bold' if t.LIBBAR_LABEL_BOLD else 'normal'};"
            f"background: transparent;"
        )
        btn_qss = self._btn_qss()
        for btn in getattr(self, "_action_buttons", []):
            btn.setFixedSize(u.action_button_width(btn, t.LIBBAR_BTN_W), u.px(t.LIBBAR_BTN_H))
            btn.setStyleSheet(btn_qss)
        self._apply_bar_style()
        self._combo.apply_theme()
