"""
gui/widgets/load_music/track_panel/track_panel.py
===================================================
TrackPanel — the right pane on the Load Music page.

Contains:
  • A header bar (cocoa gradient, "Tracks" label + "+ Add" button)
  • A drag-reorderable track table  (CollectionDropTable)

Visual style: warm ivory gradient background with a faint radial glow at
the top-center, matching the HTML mockup.

HOW TO EDIT
-----------
  • Pane background gradient → t.TRK_PANE_GRAD_TOP / MID / BOT
  • Header gradient          → t.PANEL_HDR_GRAD_TOP / BOT  (same as station header)
  • Header height            → t.LM_PANEL_HEADER_H  (px)
  • Header inner margins     → t.LM_PANEL_HDR_MARGINS  (left, top, right, bottom)
  • Header element gap       → t.LM_PANEL_HDR_SPACING  (px)
  • Header label font        → t.LM_PANEL_HDR_FONT_SIZE / LM_PANEL_HDR_FONT_WEIGHT
  • "+ Add" button gradient  → t.MINI_BTN_GRAD_TOP / BOT
  • "+ Add" button height    → t.LM_PANEL_NEW_BTN_H  (px)
  • "+ Add" button radius    → t.LM_PANEL_NEW_BTN_RADIUS  (px)
  • Row divider colour       → t.LM_TRACK_DIVIDER_COLOR
  • Row height               → t.LM_TRACK_DEFAULT_SECTION  (also t.TRACK_ROW_H in delegates)
  • Row-number column        → t.LM_TRACK_VHEADER_W
  • Scrollbar                → t.LM_SCROLLBAR_*
  • Row paint (title/artist) → gui/widgets/common/delegates.py (TrackItemDelegate)
"""

from __future__ import annotations
from typing import Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.delegates import TrackItemDelegate, RowBgDelegate
from gui.widgets.common.mockup_scrollbar import (
    sync_track_table_column_widths,
    wrap_with_mockup_scrollbar,
)


class TrackPanel(QtWidgets.QWidget):
    """Header bar + track table.  All appearance values come from gui.theme."""

    add_tracks_clicked     = pyqtSignal()
    files_dropped          = pyqtSignal(list)
    order_changed          = pyqtSignal()
    context_menu_requested = pyqtSignal(QtCore.QPoint)
    edit_track_requested = pyqtSignal(int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._build()

    # ── Public attributes ──────────────────────────────────────────────────────
    @property
    def tracks_table(self) -> QtWidgets.QTableWidget:
        return self._table

    @property
    def station_detail(self) -> QtWidgets.QLabel:
        return self._detail_label

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName("trackPanel")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_panel_style()

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._header = self._make_header()
        v.addWidget(self._header)

        self._detail_label = QtWidgets.QLabel("Select a station to view tracks.")
        self._detail_label.setWordWrap(True)
        self._detail_label.setVisible(False)
        v.addWidget(self._detail_label)

        v.addWidget(self._make_table(), 1)

        for label in ("Add Tracks", "Remove Selected"):
            b = QtWidgets.QPushButton(label)
            b.setVisible(False)
            v.addWidget(b)

    def _apply_panel_style(self) -> None:
        self.setStyleSheet(f"""
            #trackPanel {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0   {t.TRK_PANE_GRAD_TOP},
                    stop:0.4 {t.TRK_PANE_GRAD_MID},
                    stop:1   {t.TRK_PANE_GRAD_BOT}
                );
            }}
        """)

    def _make_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QWidget()
        header.setObjectName("trackHeader")
        header.setFixedHeight(t.LM_PANEL_HEADER_H)
        header.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setStyleSheet(f"""
            #trackHeader {{
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

        lbl = QtWidgets.QLabel("Tracks")
        self._header_title = lbl
        lbl.setStyleSheet(self._header_title_style())
        row.addWidget(lbl)
        row.addStretch()

        add_btn = QtWidgets.QPushButton("+ Add")
        self._add_btn = add_btn
        add_btn.setFixedHeight(u.px(t.LM_PANEL_NEW_BTN_H))
        add_btn.setStyleSheet(self._add_btn_style())
        add_btn.setToolTip(
            "Browse for audio files to add to this station (also imports them to the library)"
        )
        add_btn.clicked.connect(self.add_tracks_clicked)
        row.addWidget(add_btn)
        return header

    def _on_edit_track_requested(self, row: int) -> None:
        table = self._table
        idx = table.model().index(row, 0)
        if not idx.isValid():
            return
        table.selectRow(row)
        rect = table.visualRect(idx)
        pos = QtCore.QPoint(
            rect.right() - t.TRACK_PENCIL_ROFF - 4,
            rect.center().y(),
        )
        self.context_menu_requested.emit(pos)

    def _make_table(self) -> QtWidgets.QWidget:
        from gui.radio_manager import CollectionDropTable  # type: ignore[attr-defined]

        self._table = CollectionDropTable()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Title", "Artist", "Duration", "Format"])

        self._table.horizontalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, t.LM_TRACK_DUR_COL_W)
        self._table.setColumnWidth(3, t.LM_TRACK_FMT_COL_W)
        self._table.setColumnHidden(1, True)
        self._table.setItemDelegateForColumn(0, TrackItemDelegate(self._table))
        # Apply background-only delegate to duration/format columns so selection
        # shows the same cream gradient pill instead of the default Qt highlight.
        _bg = RowBgDelegate(self._table)
        self._table.setItemDelegateForColumn(2, _bg)
        self._table.setItemDelegateForColumn(3, _bg)

        vh = self._table.verticalHeader()
        vh.setVisible(False)   # row numbers drawn inside TrackItemDelegate
        vh.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(u.px(t.LM_TRACK_DEFAULT_SECTION))

        self._table.setShowGrid(False)
        self._apply_table_style()
        self._table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )

        self._table.files_dropped.connect(self.files_dropped)
        self._table.order_changed.connect(self.order_changed)
        self._table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self.context_menu_requested)
        self._table.edit_track_requested.connect(self._on_edit_track_requested)

        return wrap_with_mockup_scrollbar(
            self._table,
            variant="track",
            top_pad=t.LM_LIST_TOP_PAD,
            on_viewport_resize=lambda: sync_track_table_column_widths(self._table),
        )

    def _apply_table_style(self) -> None:
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: transparent;
                border: none;
                outline: none;
                selection-background-color: transparent;
                selection-color: transparent;
            }}
            QTableWidget::item {{
                background: transparent;
                color: transparent;
                padding-right: {t.LM_TRACK_ITEM_PAD_RIGHT}px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background: transparent;
                color: transparent;
                border: none;
            }}
            QHeaderView::section:vertical {{
                background: transparent;
                color: {t.TEXT_SEC};
                border: none;
                font-weight: bold;
                font-size: {u.px(t.LM_TRACK_NUM_FONT_SIZE)}px;
            }}
        """)

    def _header_title_style(self) -> str:
        return (
            f"color: {t.LM_PANEL_HDR_TEXT_COLOR};"
            f"font-weight: {t.LM_PANEL_HDR_FONT_WEIGHT};"
            f"font-size: {u.px(t.LM_PANEL_HDR_FONT_SIZE)}px;"
            f"background: transparent;"
        )

    def _add_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.MINI_BTN_GRAD_TOP},
                    stop:1 {t.MINI_BTN_GRAD_BOT}
                );
                color: #f5dab5;
                border: 1px solid {t.MINI_BTN_BORDER};
                border-radius: {u.px(t.LM_PANEL_NEW_BTN_RADIUS)}px;
                padding: {t.LM_PANEL_NEW_BTN_PADDING};
                font-weight: bold;
                font-size: {u.px(t.LM_PANEL_HDR_FONT_SIZE)}px;
            }}
            QPushButton:hover   {{ background: {t.MINI_BTN_GRAD_TOP}; }}
            QPushButton:pressed {{ background: {t.MINI_BTN_GRAD_BOT}; }}
        """

    def _refresh_header_theme(self) -> None:
        self._header.setFixedHeight(u.px(t.LM_PANEL_HEADER_H))
        self._header.setStyleSheet(f"""
            #trackHeader {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.PANEL_HDR_GRAD_TOP},
                    stop:1 {t.PANEL_HDR_GRAD_BOT}
                );
                border-top: 1px solid rgba(255,255,255,0.16);
                border-bottom: 1px solid rgba(0,0,0,0.35);
            }}
        """)
        self._header_title.setStyleSheet(self._header_title_style())
        self._add_btn.setFixedHeight(u.px(t.LM_PANEL_NEW_BTN_H))
        self._add_btn.setStyleSheet(self._add_btn_style())

    def reload_theme(self) -> None:
        self._apply_panel_style()
        self._refresh_header_theme()
        self._apply_table_style()
        vh = self._table.verticalHeader()
        vh.setDefaultSectionSize(u.px(t.LM_TRACK_DEFAULT_SECTION))
        self._table.update()
