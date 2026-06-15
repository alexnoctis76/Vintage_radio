"""
gui/widgets/common/mockup_scrollbar.py
========================================
Custom scrollbars matching scratch.html (30px rail, 38px arrow zones,
14px orange gradient thumb, CSS-style chevron arrows).

Attach around a QListWidget / QTableWidget with native bars hidden; these
widgets drive the scroll area's QScrollBar API.
"""

from __future__ import annotations

from typing import Callable, Literal, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t

Variant = Literal["station", "track", "dark", "light"]
OnViewportResize = Optional[Callable[[], None]]


class MockupScrollBar(QtWidgets.QWidget):
    """Painted scrollbar wired to *scroll_area*'s vertical or horizontal bar."""

    _ARROW = t.LM_SCROLLBAR_ARROW_H
    _THUMB_MIN = t.LM_SCROLLBAR_HANDLE_MIN_H
    _THUMB_CROSS = 14   # thumb thickness (14px wide on vertical, 14px tall on horizontal)
    _THUMB_INSET = 8    # inset from rail edge to thumb

    def __init__(
        self,
        scroll_area: QtWidgets.QAbstractScrollArea,
        *,
        variant: Variant = "station",
        orientation: QtCore.Qt.Orientation = QtCore.Qt.Orientation.Vertical,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._area = scroll_area
        self._variant = variant
        self._orientation = orientation
        self._vertical = orientation == QtCore.Qt.Orientation.Vertical
        self._bar = (
            scroll_area.verticalScrollBar()
            if self._vertical
            else scroll_area.horizontalScrollBar()
        )
        self._dragging = False
        self._drag_offset = 0

        if self._vertical:
            self.setFixedWidth(t.LM_SCROLLBAR_W)
        else:
            self.setFixedHeight(t.LM_SCROLLBAR_W)

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)

        self._bar.valueChanged.connect(self.update)
        self._bar.rangeChanged.connect(self.update)

    # ── geometry helpers ─────────────────────────────────────────────────────

    def _track_rect(self) -> QtCore.QRect:
        if self._vertical:
            return QtCore.QRect(
                0, self._ARROW,
                self.width(), max(0, self.height() - 2 * self._ARROW),
            )
        return QtCore.QRect(
            self._ARROW, 0,
            max(0, self.width() - 2 * self._ARROW), self.height(),
        )

    def _thumb_page_ratio(self, track_main: int) -> float:
        bar = self._bar
        span = bar.maximum() - bar.minimum() + bar.pageStep()
        if span <= 0:
            return 1.0
        return bar.pageStep() / span

    def _thumb_main_size(self, track_main: int) -> int:
        ratio = self._thumb_page_ratio(track_main)
        if self._vertical:
            return max(self._THUMB_MIN, min(track_main, int(track_main * ratio)))
        return max(self._THUMB_MIN, min(track_main, int(track_main * ratio)))

    def _thumb_pos(self, track_main: int, thumb_main: int) -> int:
        bar = self._bar
        scroll_range = max(1, bar.maximum() - bar.minimum())
        track_range = max(0, track_main - thumb_main)
        ratio = bar.value() / scroll_range
        return int(track_range * ratio)

    def _thumb_rect(self) -> QtCore.QRect:
        tr = self._track_rect()
        if self._vertical:
            th = self._thumb_main_size(tr.height())
            top = tr.top() + self._thumb_pos(tr.height(), th)
            return QtCore.QRect(self._THUMB_INSET, top, self._THUMB_CROSS, th)
        tw = self._thumb_main_size(tr.width())
        left = tr.left() + self._thumb_pos(tr.width(), tw)
        return QtCore.QRect(left, self._THUMB_INSET, tw, self._THUMB_CROSS)

    def _scrollable(self) -> bool:
        return self._bar.maximum() > self._bar.minimum()

    # ── painting ─────────────────────────────────────────────────────────────

    def _bg_colors(self) -> tuple[str, str, str, str]:
        v = self._variant
        if v in ("track", "light"):
            return t.SB_TRK_BG, t.SB_TRK_BORDER_L, t.SB_TRK_BORDER_R, t.SB_TRK_ARROW_COLOR
        return t.SB_STA_BG, t.SB_STA_BORDER_L, t.SB_STA_BORDER_R, t.SB_STA_ARROW_COLOR

    def _paint_thumb(self, p: QtGui.QPainter, tr: QtCore.QRect) -> None:
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(tr), 7, 7)
        if self._vertical:
            grad = QtGui.QLinearGradient(0, tr.top(), 0, tr.bottom())
        else:
            grad = QtGui.QLinearGradient(tr.left(), 0, tr.right(), 0)
        grad.setColorAt(0.0, QtGui.QColor(t.SB_THUMB_GRAD_TOP))
        grad.setColorAt(0.42, QtGui.QColor(t.SB_THUMB_GRAD_MID))
        grad.setColorAt(1.0, QtGui.QColor(t.SB_THUMB_GRAD_BOT))
        p.fillPath(path, QtGui.QBrush(grad))
        p.setPen(QtGui.QPen(QtGui.QColor(t.SB_THUMB_BORDER), 1))
        p.drawPath(path)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 107), 1))
        if self._vertical:
            p.drawLine(tr.left() + 4, tr.top() + 1, tr.right() - 4, tr.top() + 1)
        else:
            p.drawLine(tr.left() + 1, tr.top() + 4, tr.left() + 1, tr.bottom() - 4)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        bg, border_l, border_r, arrow_color = self._bg_colors()
        w, h = self.width(), self.height()

        p.fillRect(self.rect(), QtGui.QColor(bg))
        if self._vertical:
            p.setPen(QtGui.QPen(QtGui.QColor(border_l), 1))
            p.drawLine(0, 0, 0, h)
            p.setPen(QtGui.QPen(QtGui.QColor(border_r), 1))
            p.drawLine(w - 1, 0, w - 1, h)
        else:
            p.setPen(QtGui.QPen(QtGui.QColor(border_l), 1))
            p.drawLine(0, 0, w, 0)
            p.setPen(QtGui.QPen(QtGui.QColor(border_r), 1))
            p.drawLine(0, h - 1, w, h - 1)

        scrollable = self._scrollable()
        arrow_alpha = 255 if scrollable else int(255 * 0.45)

        if self._vertical:
            self._paint_chevron(
                p, QtCore.QRect(0, 0, w, self._ARROW), up=True,
                color=arrow_color, alpha=arrow_alpha,
            )
            self._paint_chevron(
                p, QtCore.QRect(0, h - self._ARROW, w, self._ARROW), up=False,
                color=arrow_color, alpha=arrow_alpha,
            )
        else:
            self._paint_chevron(
                p, QtCore.QRect(0, 0, self._ARROW, h), left=True,
                color=arrow_color, alpha=arrow_alpha,
            )
            self._paint_chevron(
                p, QtCore.QRect(w - self._ARROW, 0, self._ARROW, h), left=False,
                color=arrow_color, alpha=arrow_alpha,
            )

        if scrollable:
            self._paint_thumb(p, self._thumb_rect())
        else:
            tr = self._track_rect()
            if self._vertical:
                th = max(self._THUMB_MIN, min(tr.height(), tr.height() // 3))
                faded = QtCore.QRect(self._THUMB_INSET, tr.top(), self._THUMB_CROSS, th)
            else:
                tw = max(self._THUMB_MIN, min(tr.width(), tr.width() // 3))
                faded = QtCore.QRect(tr.left(), self._THUMB_INSET, tw, self._THUMB_CROSS)
            p.setOpacity(0.36)
            self._paint_thumb(p, faded)
            p.setOpacity(1.0)

        p.end()

    @staticmethod
    def _paint_chevron(
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        *,
        up: bool = False,
        left: bool = False,
        color: str = "#000000",
        alpha: int = 255,
    ) -> None:
        """Draw a mockup chevron (13×13, 3px stroke) centred in *rect*."""
        cx = rect.center().x()
        cy = rect.center().y()
        c = QtGui.QColor(color)
        c.setAlpha(alpha)
        pen = QtGui.QPen(
            c, 3, QtCore.Qt.PenStyle.SolidLine,
            QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        half = 6
        if up:
            painter.drawLine(cx - half, cy + 2, cx, cy - 4)
            painter.drawLine(cx, cy - 4, cx + half, cy + 2)
        elif not left:
            painter.drawLine(cx - half, cy - 2, cx, cy + 4)
            painter.drawLine(cx, cy + 4, cx + half, cy - 2)
        elif left:
            painter.drawLine(cx + 2, cy - half, cx - 4, cy)
            painter.drawLine(cx - 4, cy, cx + 2, cy + half)
        else:
            painter.drawLine(cx - 2, cy - half, cx + 4, cy)
            painter.drawLine(cx + 4, cy, cx - 2, cy + half)

    # ── interaction ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        px, py = int(pos.x()), int(pos.y())
        w, h = self.width(), self.height()

        if self._vertical:
            if py < self._ARROW:
                if self._scrollable():
                    self._bar.setValue(self._bar.value() - self._bar.pageStep())
                return
            if py >= h - self._ARROW:
                if self._scrollable():
                    self._bar.setValue(self._bar.value() + self._bar.pageStep())
                return
            thumb = self._thumb_rect()
            if thumb.contains(px, py):
                self._dragging = True
                self._drag_offset = py - thumb.top()
                return
            tr = self._track_rect()
            if py < thumb.top():
                self._bar.setValue(self._bar.value() - self._bar.pageStep())
            elif py > thumb.bottom():
                self._bar.setValue(self._bar.value() + self._bar.pageStep())
        else:
            if px < self._ARROW:
                if self._scrollable():
                    self._bar.setValue(self._bar.value() - self._bar.pageStep())
                return
            if px >= w - self._ARROW:
                if self._scrollable():
                    self._bar.setValue(self._bar.value() + self._bar.pageStep())
                return
            thumb = self._thumb_rect()
            if thumb.contains(px, py):
                self._dragging = True
                self._drag_offset = px - thumb.left()
                return
            tr = self._track_rect()
            if px < thumb.left():
                self._bar.setValue(self._bar.value() - self._bar.pageStep())
            elif px > thumb.right():
                self._bar.setValue(self._bar.value() + self._bar.pageStep())

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if not self._dragging:
            return
        tr = self._track_rect()
        if self._vertical:
            thumb_main = self._thumb_main_size(tr.height())
            track_range = max(1, tr.height() - thumb_main)
            rel = int(event.position().y()) - tr.top() - self._drag_offset
            rel = max(0, min(track_range, rel))
        else:
            thumb_main = self._thumb_main_size(tr.width())
            track_range = max(1, tr.width() - thumb_main)
            rel = int(event.position().x()) - tr.left() - self._drag_offset
            rel = max(0, min(track_range, rel))
        scroll_range = max(1, self._bar.maximum() - self._bar.minimum())
        self._bar.setValue(int(rel / track_range * scroll_range))

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = False

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.update()


class _ScrollCorner(QtWidgets.QWidget):
    """Bottom-right corner cell where horizontal and vertical rails meet."""

    def __init__(self, variant: Variant, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._variant = variant
        self.setFixedSize(t.LM_SCROLLBAR_W, t.LM_SCROLLBAR_W)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        bg = t.SB_STA_BG if self._variant == "station" else t.SB_TRK_BG
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(bg))
        p.end()


def _prepare_scroll_area(
    widget: QtWidgets.QAbstractScrollArea,
    *,
    top_pad: int,
) -> QtWidgets.QWidget:
    """Hide native bars and optionally inset the scroll area from the top."""
    widget.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    if isinstance(widget, QtWidgets.QAbstractItemView):
        widget.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        widget.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )

    if top_pad <= 0:
        return widget

    container = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(container)
    lay.setContentsMargins(0, top_pad, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widget, 1)
    return container


def _horizontal_scroll_needed(area: QtWidgets.QAbstractScrollArea) -> bool:
    bar = area.horizontalScrollBar()
    return bar.maximum() > bar.minimum()


def _apply_horizontal_bar_visibility(
    area: QtWidgets.QAbstractScrollArea,
    h_bar: MockupScrollBar,
    corner: "_ScrollCorner",
) -> None:
    needed = _horizontal_scroll_needed(area)
    h_bar.setVisible(needed)
    corner.setVisible(needed)
    if not needed:
        area.horizontalScrollBar().setValue(0)


class _ViewportResizeFilter(QtCore.QObject):
    """Re-sync track column widths and horizontal bar visibility on viewport resize."""

    def __init__(
        self,
        area: QtWidgets.QAbstractScrollArea,
        h_bar: MockupScrollBar,
        corner: "_ScrollCorner",
        on_resize: OnViewportResize,
    ) -> None:
        super().__init__(area)
        self._area = area
        self._h_bar = h_bar
        self._corner = corner
        self._on_resize = on_resize

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() == QtCore.QEvent.Type.Resize:
            if self._on_resize is not None:
                self._on_resize()
            _apply_horizontal_bar_visibility(self._area, self._h_bar, self._corner)
        return False


def wrap_with_mockup_scrollbar(
    widget: QtWidgets.QAbstractScrollArea,
    *,
    variant: Variant,
    top_pad: int = 0,
    on_viewport_resize: OnViewportResize = None,
) -> QtWidgets.QWidget:
    """Return a container with mockup vertical + horizontal scrollbars."""
    content = _prepare_scroll_area(widget, top_pad=top_pad)

    wrap = QtWidgets.QWidget()
    wrap.setObjectName(f"scrollWrap_{variant}")
    grid = QtWidgets.QGridLayout(wrap)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(0)

    v_bar = MockupScrollBar(widget, variant=variant, orientation=QtCore.Qt.Orientation.Vertical)
    h_bar = MockupScrollBar(widget, variant=variant, orientation=QtCore.Qt.Orientation.Horizontal)
    corner = _ScrollCorner(variant)

    grid.addWidget(content, 0, 0)
    grid.addWidget(v_bar, 0, 1)
    grid.addWidget(h_bar, 1, 0)
    grid.addWidget(corner, 1, 1)
    grid.setRowStretch(0, 1)
    grid.setColumnStretch(0, 1)

    def refresh_h_bar() -> None:
        _apply_horizontal_bar_visibility(widget, h_bar, corner)

    wrap._refresh_h_bar = refresh_h_bar  # type: ignore[attr-defined]
    widget._refresh_h_bar = refresh_h_bar  # type: ignore[attr-defined]

    widget.horizontalScrollBar().rangeChanged.connect(refresh_h_bar)
    QtCore.QTimer.singleShot(0, refresh_h_bar)

    if on_viewport_resize is not None:
        filt = _ViewportResizeFilter(widget, h_bar, corner, on_viewport_resize)
        widget.viewport().installEventFilter(filt)
        wrap._viewport_filter = filt  # type: ignore[attr-defined]

    return wrap


def _track_title_column_min_width(table: QtWidgets.QTableWidget) -> int:
    """Minimum width required to show full title + artist text without clipping."""
    title_font = QtGui.QFont(table.font())
    title_font.setBold(True)
    title_fm = QtGui.QFontMetrics(title_font)
    artist_font = QtGui.QFont(table.font())
    artist_font.setPointSizeF(
        max(t.TRACK_ARTIST_MIN_PT, artist_font.pointSizeF() - t.TRACK_ARTIST_SIZE_DELTA)
    )
    artist_fm = QtGui.QFontMetrics(artist_font)

    title_col_w = t.LM_TRACK_TITLE_MIN_W
    for row in range(table.rowCount()):
        title_item = table.item(row, 0)
        artist_item = table.item(row, 1)
        title = title_item.text() if title_item else ""
        artist = artist_item.text() if artist_item else ""
        text_w = max(
            title_fm.horizontalAdvance(title),
            artist_fm.horizontalAdvance(artist) if artist else 0,
        )
        row_w = t.LM_TRACK_NUM_COL_W + t.TRACK_PAD_X + text_w + t.TRACK_PAD_RIGHT
        title_col_w = max(title_col_w, row_w)
    return title_col_w


def _track_meta_column_widths(table: QtWidgets.QTableWidget) -> tuple[int, int]:
    dur_w = t.LM_TRACK_DUR_COL_W
    fmt_w = t.LM_TRACK_FMT_COL_W
    cell_fm = QtGui.QFontMetrics(table.font())
    for row in range(table.rowCount()):
        dur_item = table.item(row, 2)
        fmt_item = table.item(row, 3)
        if dur_item:
            dur_w = max(dur_w, cell_fm.horizontalAdvance(dur_item.text()) + 16)
        if fmt_item:
            fmt_w = max(fmt_w, cell_fm.horizontalAdvance(fmt_item.text()) + 16)
    return dur_w, fmt_w


def sync_track_table_column_widths(table: QtWidgets.QTableWidget) -> None:
    """Fill the row when content fits; enable horizontal scroll only on overflow."""
    viewport_w = table.viewport().width()
    if viewport_w <= 0:
        QtCore.QTimer.singleShot(0, lambda: sync_track_table_column_widths(table))
        return

    hh = table.horizontalHeader()
    title_min = _track_title_column_min_width(table)
    dur_w, fmt_w = _track_meta_column_widths(table)
    min_total = title_min + dur_w + fmt_w

    if min_total <= viewport_w:
        # Content fits — stretch the title column to fill the pane (original behaviour).
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(2, dur_w)
        table.setColumnWidth(3, fmt_w)
        table.horizontalScrollBar().setValue(0)
    else:
        # Content overflows — fixed widths so the user can scroll horizontally.
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, title_min)
        table.setColumnWidth(2, dur_w)
        table.setColumnWidth(3, fmt_w)

    refresh = getattr(table, "_refresh_h_bar", None)
    if refresh is not None:
        QtCore.QTimer.singleShot(0, refresh)
