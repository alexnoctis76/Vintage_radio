"""
gui/widgets/load_music/station_panel/station_panel.py
========================================================
StationPanel — the left pane on the Load Music page.

Contains:
  • A header bar (gradient fill, "Stations" label + "+ New" button)
  • A drag-reorderable station list  (StationImportListWidget)

Visual style: dark gradient background with cocoa header, matching the
HTML mockup.  A 1px right-edge separator divides it from the track panel.

HOW TO EDIT
-----------
  • Pane background gradient → t.STA_PANE_GRAD_TOP / BOT
  • Header gradient          → t.PANEL_HDR_GRAD_TOP / BOT
  • Header height            → t.LM_PANEL_HEADER_H  (px)
  • Header inner margins     → t.LM_PANEL_HDR_MARGINS  (left, top, right, bottom)
  • Header element gap       → t.LM_PANEL_HDR_SPACING  (px)
  • Header label font        → t.LM_PANEL_HDR_FONT_SIZE  (pt, bold)
  • "+ New" button gradient  → t.MINI_BTN_GRAD_TOP / BOT
  • "+ New" button height    → t.LM_PANEL_NEW_BTN_H  (px)
  • "+ New" button radius    → t.LM_PANEL_NEW_BTN_RADIUS  (px)
  • "+ New" button border    → t.MINI_BTN_BORDER
  • Right-edge separator     → t.SPLIT_PANEL_SEP  (colour)
  • Scrollbar width          → t.LM_SCROLLBAR_W  (px)
  • Row paint / height       → gui/widgets/common/delegates.py + STATION_* in theme.py
"""

from __future__ import annotations
from typing import List, Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui.widgets.common.delegates import StationItemDelegate
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar


class StationPanel(QtWidgets.QWidget):
    """Header bar + station list.  All appearance values come from gui.theme."""

    station_selected       = pyqtSignal(object, object)
    order_changed          = pyqtSignal()
    folders_dropped        = pyqtSignal(list)
    context_menu_requested = pyqtSignal(QtCore.QPoint)
    new_station_clicked    = pyqtSignal()

    def __init__(self, max_tracks: int = 255,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._max_tracks = max_tracks
        self._build()

    # ── Public attributes ──────────────────────────────────────────────────────
    @property
    def station_list(self) -> QtWidgets.QListWidget:
        return self._list

    @property
    def size_label(self) -> QtWidgets.QLabel:
        return self._size_label

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName("stationPanel")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_panel_style()

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        v.addWidget(self._make_header())
        v.addWidget(self._make_list(), 1)

        # Hidden legacy buttons — kept for backward-compat signal connections
        for label in ("New Station", "Rename", "Delete"):
            b = QtWidgets.QPushButton(label)
            b.setVisible(False)
            v.addWidget(b)

    def _apply_panel_style(self) -> None:
        self.setStyleSheet(f"""
            #stationPanel {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.STA_PANE_GRAD_TOP},
                    stop:1 {t.STA_PANE_GRAD_BOT}
                );
                border-right: 1px solid {t.SPLIT_PANEL_SEP};
            }}
        """)

    def _make_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QWidget()
        header.setObjectName("stationHeader")
        header.setFixedHeight(t.LM_PANEL_HEADER_H)
        header.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setStyleSheet(f"""
            #stationHeader {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.PANEL_HDR_GRAD_TOP},
                    stop:1 {t.PANEL_HDR_GRAD_BOT}
                );
                border-top: 1px solid rgba(255,255,255,0.16);
                border-bottom: 1px solid rgba(0,0,0,0.35);
            }}
        """)
        l, top, r, bot = t.LM_PANEL_HDR_MARGINS
        row = QtWidgets.QHBoxLayout(header)
        row.setContentsMargins(l, top, r, bot)
        row.setSpacing(t.LM_PANEL_HDR_SPACING)

        lbl = QtWidgets.QLabel("Stations")
        lbl.setStyleSheet(
            f"color: {t.LM_PANEL_HDR_TEXT_COLOR};"
            f"font-weight: {'bold' if t.LM_PANEL_HDR_FONT_BOLD else 'normal'};"
            f"font-size: {t.LM_PANEL_HDR_FONT_SIZE}px;"
            f"background: transparent;"
        )
        lbl.setToolTip(
            "Drag stations to reorder — each maps to a numbered folder on the SD card.\n"
            "Drop folders here to import them as stations."
        )
        row.addWidget(lbl)
        row.addStretch()

        self._size_label = QtWidgets.QLabel("")
        self._size_label.setVisible(False)
        row.addWidget(self._size_label)

        new_btn = QtWidgets.QPushButton("+ New")
        new_btn.setFixedHeight(t.LM_PANEL_NEW_BTN_H)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.MINI_BTN_GRAD_TOP},
                    stop:1 {t.MINI_BTN_GRAD_BOT}
                );
                color: #f5dab5;
                border: 1px solid {t.MINI_BTN_BORDER};
                border-radius: {t.LM_PANEL_NEW_BTN_RADIUS}px;
                padding: {t.LM_PANEL_NEW_BTN_PADDING};
                font-weight: bold;
                font-size: {t.LM_PANEL_HDR_FONT_SIZE}px;
            }}
            QPushButton:hover   {{ background: {t.MINI_BTN_GRAD_TOP}; }}
            QPushButton:pressed {{ background: {t.MINI_BTN_GRAD_BOT}; }}
        """)
        new_btn.clicked.connect(self.new_station_clicked)
        row.addWidget(new_btn)
        return header

    def _make_list(self) -> QtWidgets.QWidget:
        from gui.radio_manager import StationImportListWidget  # type: ignore[attr-defined]

        self._list = StationImportListWidget()
        self._list.setItemDelegate(StationItemDelegate(self._max_tracks, self._list))
        self._list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
                selection-background-color: transparent;
                selection-color: #ffffff;
            }}
            QListWidget::item {{
                background: transparent;
                border: none;
            }}
            QListWidget::item:selected {{
                background: transparent;
                color: #ffffff;
            }}
        """)

        # Top gap between header bar and first row (see also LM_LIST_TOP_PAD on track wrap)
        self._list.setViewportMargins(0, t.LM_LIST_TOP_PAD, 0, 0)

        self._list.currentItemChanged.connect(self._on_station_item_changed)
        self._list.order_changed.connect(self.order_changed)
        self._list.folders_dropped.connect(self.folders_dropped)
        self._list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self.context_menu_requested)

        return wrap_with_mockup_scrollbar(self._list, variant="station")

    def _on_station_item_changed(
        self,
        current: Optional[QtWidgets.QListWidgetItem],
        previous: Optional[QtWidgets.QListWidgetItem],
    ) -> None:
        self.station_selected.emit(current, previous)

    def reload_theme(self) -> None:
        self._apply_panel_style()
        self._list.update()
