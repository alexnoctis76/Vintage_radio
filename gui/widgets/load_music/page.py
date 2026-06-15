"""
gui/widgets/load_music/page.py
================================
LoadMusicPage — the full "Load Music" tab assembled from its five sub-widgets.

This class owns the layout of the page but delegates all appearance logic to
the individual sub-widget classes.  MainWindow wires signals and aliases the
inner widget references onto its own ``self._basic_*`` attributes after
instantiating this class.

Sub-widgets (each in its own subfolder):
  storage_section/  — "Storage" heading, SD path label, capacity bar, buttons
  station_panel/    — left pane: header + drag-reorderable station list
  track_panel/      — right pane: header + drag-reorderable track table
  sync_bar/         — bottom row: Sync / Eject buttons

HOW TO EDIT
-----------
  • Page outer margins (l, t, r, b) → t.LM_PAGE_MARGINS  in gui/theme.py
  • Gap between sections             → t.LM_PAGE_SPACING  in gui/theme.py
  • Page background colour           → t.C_BG             in gui/theme.py
  • Splitter handle width            → t.LM_SPLITTER_HANDLE_W
  • Initial panel size ratio (1:2)   → t.LM_SPLITTER_STATION_RATIO / TRACK_RATIO

  Warning banner colours / sizes     → t.WARN_TEXT, t.WARN_BOLD,
                                       t.LM_WARN_ROW_SPACING, t.LM_WARN_BTN_W
"""

from __future__ import annotations
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.load_music.storage_section.storage_section import StorageSection
from gui.widgets.load_music.station_panel.station_panel     import StationPanel
from gui.widgets.load_music.track_panel.track_panel         import TrackPanel
from gui.widgets.load_music.sync_bar.sync_bar               import SyncBar


class LoadMusicPage(QtWidgets.QWidget):
    """Complete Load Music page widget.

    Instantiate with the runtime parameters that come from MainWindow's state,
    then connect signals and alias the inner widget refs in radio_manager.py.

    Parameters
    ----------
    sd_root:
        Currently selected SD card root path (shown in the storage section).
    max_tracks:
        Maximum tracks per station enforced by the firmware (default 255).
    """

    def __init__(
        self,
        *,
        sd_root: str = "",
        max_tracks: int = 255,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._sd_root             = sd_root
        self._max_tracks          = max_tracks
        self._build()

    # ── Sub-widget instance references ────────────────────────────────────────
    # radio_manager.py connects signals via these properties and aliases the
    # inner widget refs (e.g. page.storage_section.sd_root_label) onto
    # self._basic_* attributes so all existing backend code keeps working.

    @property
    def storage_section(self) -> StorageSection:
        return self._storage

    @property
    def station_panel(self) -> StationPanel:
        return self._stations

    @property
    def track_panel(self) -> TrackPanel:
        return self._tracks

    @property
    def sync_bar(self) -> SyncBar:
        return self._sync

    # ── Warning-banner widget references ──────────────────────────────────────
    # These are aliased by MainWindow onto self._basic_sd_sync_warning and
    # self._basic_sd_sync_details_btn.  The "Details…" button's clicked signal
    # is connected by radio_manager.py to self._show_basic_sd_sync_details.

    @property
    def warning_label(self) -> QtWidgets.QLabel:
        return self._warn_label

    @property
    def warning_details_btn(self) -> QtWidgets.QPushButton:
        return self._warn_details_btn

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName("loadMusicPage")
        self.setStyleSheet(f"#loadMusicPage {{ background: {t.C_BG}; }}")

        # ── EDIT: overall page chrome ──────────────────────────────────────────
        # Outer margins   → t.LM_PAGE_MARGINS  (left, top, right, bottom) px
        # Section gap     → t.LM_PAGE_SPACING  px
        # ─────────────────────────────────────────────────────────────────────
        l, top, r, bot = t.LM_PAGE_MARGINS
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(l, top, r, bot)
        layout.setSpacing(t.LM_PAGE_SPACING)

        layout.addLayout(self._build_warning_row())
        layout.addWidget(self._build_storage_section())
        layout.addWidget(self._build_splitter(), 1)  # QFrame wrapping the splitter
        layout.addWidget(self._build_sync_bar())

    # ── 1. Warning banner ─────────────────────────────────────────────────────

    def _build_warning_row(self) -> QtWidgets.QHBoxLayout:
        """SD-mismatch warning banner (hidden unless triggered by the backend).

        ── EDIT in gui/theme.py ──────────────────────────────────────────────
        • Warning text colour     → WARN_TEXT
        • Warning text bold?      → WARN_BOLD
        • Row element gap         → LM_WARN_ROW_SPACING  (px)
        • "Details…" button width → LM_WARN_BTN_W  (px)
        ─────────────────────────────────────────────────────────────────────
        """
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(t.LM_WARN_ROW_SPACING)

        self._warn_label = QtWidgets.QLabel()
        self._warn_label.setWordWrap(True)
        self._warn_label.setStyleSheet(
            f"color: {t.WARN_TEXT};"
            f"font-weight: {'bold' if t.WARN_BOLD else 'normal'};"
        )
        self._warn_label.setVisible(False)
        row.addWidget(self._warn_label, 1)

        self._warn_details_btn = QtWidgets.QPushButton("Details...")
        self._warn_details_btn.setVisible(False)
        row.addWidget(self._warn_details_btn)
        self._apply_warn_details_btn_theme()

        return row

    @staticmethod
    def _warn_details_btn_style() -> str:
        return t.outline_button_stylesheet(font_weight=700)

    def _apply_warn_details_btn_theme(self) -> None:
        btn = self._warn_details_btn
        btn.setStyleSheet(self._warn_details_btn_style())
        btn.setFixedHeight(u.px(t.LIBBAR_BTN_H))
        btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        font = QtGui.QFont(btn.font())
        font.setPixelSize(u.px(t.LIBBAR_BTN_FONT_SIZE))
        font.setBold(True)
        text_w = QtGui.QFontMetrics(font).horizontalAdvance(btn.text())
        btn.setFixedWidth(
            t.outline_button_width_for_text(btn.text(), text_w, min_w=t.LM_WARN_BTN_W)
        )

    def apply_ui_zoom(self) -> None:
        self.reload_theme()


    def reload_theme(self) -> None:
        """Re-apply theme tokens (dev theme live-reload)."""
        self.setStyleSheet(f"#loadMusicPage {{ background: {t.C_BG}; }}")
        self._warn_label.setStyleSheet(
            f"color: {t.WARN_TEXT};"
            f"font-weight: {'bold' if t.WARN_BOLD else 'normal'};"
        )
        self._apply_warn_details_btn_theme()
        self._storage.reload_theme()
        self._stations.reload_theme()
        self._tracks.reload_theme()
        self._sync.reload_theme()

    # ── 2. Storage section ────────────────────────────────────────────────────

    def _build_storage_section(self) -> StorageSection:
        """SD storage banner — capacity bar + Detect / Select (device-banner style)."""
        self._storage = StorageSection(sd_root=self._sd_root)
        return self._storage

    # ── 3. Main splitter (stations left | tracks right) ───────────────────────

    def _build_splitter(self) -> QtWidgets.QFrame:
        """Horizontal splitter wrapped in a bordered + shadowed QFrame.

        ── EDIT in gui/theme.py ──────────────────────────────────────────────
        • Frame border colour / width  → SPLIT_PANEL_BORDER, SPLIT_PANEL_BORDER_W
        • Frame corner radius          → SPLIT_PANEL_RADIUS
        • Frame drop shadow            → PANEL_SHADOW_*
        • Drag-handle width            → LM_SPLITTER_HANDLE_W  (px; 0 = none)
        • Station share                → LM_SPLITTER_STATION_RATIO
        • Track share                  → LM_SPLITTER_TRACK_RATIO
          Default 1:2 means stations ≈ 33 %, tracks ≈ 67 % of the width.
        ─────────────────────────────────────────────────────────────────────
        """
        # Outer frame — provides the visible border + drop shadow
        frame = QtWidgets.QFrame()
        frame.setObjectName("splitPanelFrame")
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        frame.setStyleSheet(f"""
            #splitPanelFrame {{
                border: {t.SPLIT_PANEL_BORDER_W}px solid {t.SPLIT_PANEL_BORDER};
                border-radius: {t.SPLIT_PANEL_RADIUS}px;
                background: transparent;
            }}
        """)
        shadow = QtWidgets.QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(t.PANEL_SHADOW_BLUR)
        shadow.setOffset(0, t.PANEL_SHADOW_OFFSET)
        col = QtGui.QColor(t.PANEL_SHADOW_COLOR)
        col.setAlpha(t.PANEL_SHADOW_ALPHA)
        shadow.setColor(col)
        frame.setGraphicsEffect(shadow)

        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # Splitter inside the frame
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setHandleWidth(t.LM_SPLITTER_HANDLE_W)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {t.SPLIT_PANEL_SEP};
                width: 2px;
            }}
        """)

        self._stations = StationPanel(max_tracks=self._max_tracks)
        self._tracks   = TrackPanel()

        splitter.addWidget(self._stations)
        splitter.addWidget(self._tracks)
        splitter.setStretchFactor(0, t.LM_SPLITTER_STATION_RATIO)
        splitter.setStretchFactor(1, t.LM_SPLITTER_TRACK_RATIO)

        frame_layout.addWidget(splitter)
        return frame

    # ── 4. Sync bar ───────────────────────────────────────────────────────────

    def _build_sync_bar(self) -> SyncBar:
        """Bottom action row — Sync to SD Card / Safely Remove SD."""
        self._sync = SyncBar()
        return self._sync
