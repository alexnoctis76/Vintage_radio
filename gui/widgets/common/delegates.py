"""
gui/widgets/common/delegates.py
================================
Custom QPainter delegates for the Load Music page.

  StationItemDelegate  — paints each row in the station list
  TrackItemDelegate    — paints the Title column in the track table

All layout dimensions are read from gui.theme so they hot-reload in dev mode.
Edit sizes in theme.py and hit save; the list / table repaints automatically
(Qt calls paint() fresh on each redraw, so no rebuild is needed for delegate
changes — only for layout/container changes).

HOW TO EDIT
-----------
Selected-row pill:
  Station row gradient  → t.STA_SEL_GRAD_TOP / MID / BOT, border → t.STA_SEL_BORDER
  Track row gradient    → t.TRK_SEL_GRAD_TOP / BOT, border → t.TRK_SEL_BORDER
  Corner radius         → t.STATION_SEL_RADIUS / t.TRACK_SEL_RADIUS  (px)

Normal station row background comes from the panel's own QSS gradient
(t.STA_PANE_GRAD_*); the delegate paints transparent so the panel shows through.

Row heights:  t.STATION_ROW_H  /  t.TRACK_ROW_H  (px)
"""

from __future__ import annotations
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainterPath, QPen

import gui.theme as t


# ── Item-data roles used by StationItemDelegate ────────────────────────────────
STATION_NUM_ROLE   = int(QtCore.Qt.ItemDataRole.UserRole) + 10
STATION_NAME_ROLE  = int(QtCore.Qt.ItemDataRole.UserRole) + 11
STATION_COUNT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 12

_BASIC_MAX_TRACKS = 255


class StationItemDelegate(QtWidgets.QStyledItemDelegate):
    """Custom painter for each row in the basic-mode station list.

    Draws:  ≡ drag-handle | 01 number | Station Name | 7/255 count | ✎ edit

    Selected row: orange gradient pill with 1px border and rounded corners.
    Normal row:   transparent (panel gradient shows through).

    Data is carried via STATION_*_ROLE item roles; the DisplayRole text is
    left intact so backend code (e.g. delete confirmations) still works.
    """

    def __init__(self, max_tracks: int = _BASIC_MAX_TRACKS,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._max = max_tracks

    def sizeHint(self, option, index) -> QtCore.QSize:  # type: ignore[override]
        name = (
            index.data(STATION_NAME_ROLE)
            or index.data(QtCore.Qt.ItemDataRole.DisplayRole)
            or ""
        )
        name_font = QFont(option.font)
        name_font.setBold(True)
        name_w = QtGui.QFontMetrics(name_font).horizontalAdvance(str(name))
        content_w = (
            t.STATION_PAD_LEFT
            + t.STATION_HANDLE_W
            + t.STATION_NUM_W
            + name_w
            + t.STATION_NAME_RSVD
            + _SEL_PADDING * 2
        )
        return QtCore.QSize(max(option.rect.width(), content_w), t.STATION_ROW_H)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect     = option.rect
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        r        = t.STATION_SEL_RADIUS
        frect    = QtCore.QRectF(rect).adjusted(_SEL_PADDING, 2, -_SEL_PADDING, -2)

        if selected:
            # ── Orange gradient pill ───────────────────────────────────────────
            path = QPainterPath()
            path.addRoundedRect(frect, r, r)

            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            grad.setColorAt(0.0,  QColor(t.STA_SEL_GRAD_TOP))
            grad.setColorAt(0.5,  QColor(t.STA_SEL_GRAD_MID))
            grad.setColorAt(1.0,  QColor(t.STA_SEL_GRAD_BOT))
            painter.fillPath(path, QtGui.QBrush(grad))

            # 1px border
            painter.setPen(QPen(QColor(t.STA_SEL_BORDER), 1))
            painter.drawPath(path)

            # Inset top highlight
            painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
            painter.drawLine(
                int(frect.left() + r),      int(frect.top()),
                int(frect.right() - r),     int(frect.top()),
            )
        else:
            # No fill — panel gradient shows through
            sep_color = QColor(t.STA_PANE_GRAD_BOT).lighter(t.STATION_SEP_LIGHTER)
            painter.setPen(QPen(sep_color, 1))
            painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        # Pull data from item roles
        num   = index.data(STATION_NUM_ROLE)
        name  = (index.data(STATION_NAME_ROLE)
                 or index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")
        count = index.data(STATION_COUNT_ROLE)

        if selected:
            text_color = QColor("#ffffff")
            dim_color  = QColor(255, 255, 255, 180)
        else:
            text_color = QColor(t.S_TEXT)
            dim_color  = QColor(t.BORDER_SOFT)

        x = rect.left() + t.STATION_PAD_LEFT

        # Drag-handle glyph (≡)
        painter.setPen(dim_color)
        painter.setFont(QFont(option.font))
        painter.drawText(
            QtCore.QRect(x, rect.top(), t.STATION_HANDLE_W, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            "\u2630",
        )

        # Station / folder number (bold)
        num_font = QFont(option.font)
        num_font.setBold(True)
        painter.setFont(num_font)
        painter.setPen(text_color)
        painter.drawText(
            QtCore.QRect(x + t.STATION_NUM_OFFSET, rect.top(), t.STATION_NUM_W, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            f"{int(num):02d}" if num is not None else "",
        )

        # Station name (bold, elided)
        name_font = QFont(option.font)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(text_color)
        name_rect = QtCore.QRect(
            x + t.STATION_NAME_OFFSET,
            rect.top(),
            rect.width() - t.STATION_NAME_OFFSET - t.STATION_NAME_RSVD,
            rect.height(),
        )
        painter.drawText(
            name_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            QtGui.QFontMetrics(name_font).elidedText(
                str(name), QtCore.Qt.TextElideMode.ElideRight, name_rect.width()
            ),
        )

        # Track count
        painter.setFont(QFont(option.font))
        painter.setPen(dim_color)
        painter.drawText(
            QtCore.QRect(
                rect.right() - t.STATION_COUNT_ROFF, rect.top(),
                t.STATION_COUNT_W, rect.height(),
            ),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight,
            f"{int(count)}/{self._max}" if count is not None else "",
        )

        # Edit pencil glyph (✎)
        painter.setPen(dim_color)
        painter.drawText(
            QtCore.QRect(
                rect.right() - t.STATION_PENCIL_ROFF, rect.top(),
                t.STATION_PENCIL_W, rect.height(),
            ),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            "\u270E",
        )

        painter.restore()


_SEL_PADDING = 5   # px — left/right inset on selected pills (matches mockup)


def _full_row_rect(
    view: QtWidgets.QAbstractItemView,
    cell_rect: QtCore.QRect,
    pad: int = _SEL_PADDING,
) -> QtCore.QRect:
    """Return a QRect spanning all visible columns for the row at *cell_rect*.

    Used by TrackItemDelegate (col 0) to paint a pill that covers cols 2 & 3
    without needing separate per-column delegates.  The rect is inset *pad* px
    on both sides to produce the margin visible in the mockup.
    """
    model = view.model()
    if model is None:
        return cell_rect

    col_count = model.columnCount()
    visible = [c for c in range(col_count) if not view.isColumnHidden(c)]
    if not visible:
        return cell_rect

    x0    = view.columnViewportPosition(visible[0])
    xlast = view.columnViewportPosition(visible[-1]) + view.columnWidth(visible[-1])
    return QtCore.QRect(
        x0 + pad,
        cell_rect.top(),
        xlast - x0 - 2 * pad,
        cell_rect.height(),
    )


def _draw_track_sel_pill(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    frect: QtCore.QRectF,
    r: int,
) -> None:
    """Draw the cream gradient selection pill for a track row."""
    path = QPainterPath()
    path.addRoundedRect(frect, r, r)
    grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
    grad.setColorAt(0.0, QColor(t.TRK_SEL_GRAD_TOP))
    grad.setColorAt(1.0, QColor(t.TRK_SEL_GRAD_BOT))
    painter.fillPath(path, QtGui.QBrush(grad))
    painter.setPen(QPen(QColor(t.TRK_SEL_BORDER), 1))
    painter.drawPath(path)
    painter.setPen(QPen(QColor(255, 255, 255, 184), 1))
    painter.drawLine(
        int(frect.left() + r), int(frect.top()),
        int(frect.right() - r), int(frect.top()),
    )


class RowBgDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for non-title columns (Duration, Format) of the track table.

    The selection pill is drawn by CollectionDropTable.drawRow() spanning the
    full row width.  This delegate ONLY draws the cell text with no background,
    so the pill painted by drawRow() shows through cleanly underneath.

    HOW TO EDIT
    -----------
      Text alignment → the AlignVCenter | AlignHCenter flags below.
    """

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        painter.save()
        text = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        is_sel = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        # Use primary text colour always — the cream pill already gives contrast
        painter.setPen(QtGui.QColor(t.TEXT_PRI))
        painter.setFont(option.font)
        painter.drawText(
            option.rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter,
            str(text),
        )
        painter.restore()


class TrackItemDelegate(QtWidgets.QStyledItemDelegate):
    """Custom painter for the Title column (col 0) of the tracks table.

    Draws:
      • When selected: ONE cream gradient pill spanning ALL visible columns
        (painted by temporarily overriding the clip region so it extends into
        cols 2 and 3 — those delegates suppress Qt's default highlight, leaving
        the pill visible underneath their text)
      • Left ~52px: row number ("01", "02", …) in muted brown / white
      • Right portion: bold song title + smaller artist name on two lines

    The vertical header is hidden; this delegate renders the row number instead.
    Artist text is read from hidden column 1.

    HOW TO EDIT
    -----------
      Row number area width   → t.LM_TRACK_NUM_COL_W  (px)
      Row number colour       → t.LM_TRACK_NUM_COLOR
      Selection side padding  → _SEL_PADDING at the top of this file (px)
      Title/artist layout     → TRACK_PAD_X, TRACK_TITLE_TOP_BIAS, etc. in theme.py
    """

    def sizeHint(self, option, index) -> QtCore.QSize:  # type: ignore[override]
        return QtCore.QSize(option.rect.width(), t.TRACK_ROW_H)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect     = option.rect
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)

        if selected:
            view = option.widget
            if isinstance(view, QtWidgets.QAbstractItemView):
                full_rect = _full_row_rect(view, rect)
                frect = QtCore.QRectF(full_rect).adjusted(0, 2, 0, -2)
                painter.setClipping(False)
                _draw_track_sel_pill(painter, full_rect, frect, t.TRACK_SEL_RADIUS)

        # ── Row number ────────────────────────────────────────────────────────
        row_num  = index.row() + 1
        num_rect = QtCore.QRect(rect.left(), rect.top(), t.LM_TRACK_NUM_COL_W, rect.height())
        num_font = QFont(option.font)
        num_font.setBold(False)
        painter.setFont(num_font)
        num_color = QColor(t.LM_TRACK_NUM_COLOR)
        painter.setPen(num_color)
        painter.drawText(
            num_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter,
            f"{row_num:02d}",
        )

        # ── Title + artist ────────────────────────────────────────────────────
        title  = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        artist = ""
        sib    = index.siblingAtColumn(1)
        if sib.isValid():
            artist = sib.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""

        content_x    = rect.left() + t.LM_TRACK_NUM_COL_W + t.TRACK_PAD_X
        content_w    = rect.width() - t.LM_TRACK_NUM_COL_W - t.TRACK_PAD_X - t.TRACK_PAD_RIGHT
        mid          = rect.height() // 2
        title_color  = QColor(t.TEXT_PRI)
        artist_color = QColor(t.TEXT_SEC)

        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(title_color)
        painter.drawText(
            QtCore.QRect(content_x, rect.top() + t.TRACK_TITLE_TOP_BIAS, content_w, mid),
            QtCore.Qt.AlignmentFlag.AlignBottom | QtCore.Qt.AlignmentFlag.AlignLeft,
            QtGui.QFontMetrics(title_font).elidedText(
                str(title), QtCore.Qt.TextElideMode.ElideRight, content_w,
            ),
        )

        if artist:
            af = QFont(option.font)
            af.setPointSizeF(max(t.TRACK_ARTIST_MIN_PT,
                                 af.pointSizeF() - t.TRACK_ARTIST_SIZE_DELTA))
            painter.setFont(af)
            painter.setPen(artist_color)
            painter.drawText(
                QtCore.QRect(content_x, rect.top() + mid,
                             content_w, rect.height() - mid - t.TRACK_TITLE_TOP_BIAS),
                QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft,
                QtGui.QFontMetrics(af).elidedText(
                    str(artist), QtCore.Qt.TextElideMode.ElideRight, content_w,
                ),
            )

        painter.restore()
