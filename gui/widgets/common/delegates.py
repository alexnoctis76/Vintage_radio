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
from gui import ui_scale as u


# ── Item-data roles used by StationItemDelegate ────────────────────────────────
STATION_NUM_ROLE   = int(QtCore.Qt.ItemDataRole.UserRole) + 10
STATION_NAME_ROLE  = int(QtCore.Qt.ItemDataRole.UserRole) + 11
STATION_COUNT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 12
STATION_KIND_ROLE  = int(QtCore.Qt.ItemDataRole.UserRole) + 13

_BASIC_MAX_TRACKS = 255
_SEL_PADDING = 5   # px — left/right inset on selected pills (matches mockup)


def _sel_padding() -> int:
    return u.px(_SEL_PADDING)


def _station_name_font(base: QFont) -> QFont:
    font = QFont(base)
    font.setBold(True)
    font.setPixelSize(u.px(t.LM_STATION_NAME_FONT_SIZE))
    return font


def _station_count_font(base: QFont) -> QFont:
    font = QFont(base)
    font.setPixelSize(u.px(t.LM_STATION_COUNT_FONT_SIZE))
    return font


def _station_pencil_font(base: QFont) -> QFont:
    font = QFont(base)
    font.setBold(True)
    font.setPixelSize(u.px(t.LM_STATION_PENCIL_FONT_SIZE))
    return font


def _station_row_layout(font: QFont, max_tracks: int) -> dict[str, int]:
    """Right-rail geometry derived from font metrics (zoom-safe)."""
    count_fm = QtGui.QFontMetrics(_station_count_font(font))
    pencil_fm = QtGui.QFontMetrics(_station_pencil_font(font))
    name_fm = QtGui.QFontMetrics(_station_name_font(font))

    count_sample = f"{max_tracks}/{max_tracks}"
    count_w = count_fm.horizontalAdvance(count_sample) + u.px(8)
    pencil_w = max(
        u.px(t.STATION_PENCIL_W),
        pencil_fm.horizontalAdvance("\u270E") + u.px(6),
    )

    right_pad = u.px(8)
    count_pencil_gap = u.px(10)

    pencil_roff = right_pad + pencil_w
    count_roff = pencil_roff + count_pencil_gap + count_w
    name_rsrv = count_roff + u.px(6)

    row_h = max(
        u.px(t.STATION_ROW_H),
        count_fm.height() + u.px(24),
        name_fm.height() + u.px(24),
    )

    return {
        "count_w": count_w,
        "count_roff": count_roff,
        "pencil_roff": pencil_roff,
        "pencil_w": pencil_w,
        "name_rsrv": name_rsrv,
        "row_h": row_h,
        "right_pad": right_pad,
    }


def station_pencil_hit_rect(
    row_rect: QtCore.QRect,
    font: Optional[QFont] = None,
    max_tracks: int = _BASIC_MAX_TRACKS,
) -> QtCore.QRect:
    """Clickable hit target for the station-row edit pencil."""
    layout = _station_row_layout(font or QFont(), max_tracks)
    pad = 8
    pencil_x = row_rect.right() - layout["pencil_roff"]
    return QtCore.QRect(
        pencil_x - pad,
        row_rect.top(),
        layout["pencil_w"] + pad * 2,
        row_rect.height(),
    )


def _track_tag_font(base: Optional[QFont] = None) -> QFont:
    font = QFont(base or QFont())
    font.setPixelSize(max(u.px(10), u.px(t.LM_TRACK_ARTIST_FONT_SIZE)))
    font.setBold(True)
    return font


def _track_action_layout(
    *,
    show_ad_toggle: bool = False,
    show_badge: bool = False,
    show_link_toggle: bool = False,
    font: Optional[QFont] = None,
) -> dict[str, int]:
    """Right-cluster geometry for pencil, commercial toggle, link, and badge."""
    pad = u.px(12)
    gap = u.px(10)
    btn_w = u.px(t.TRACK_PENCIL_W)
    ad_w = u.px(getattr(t, "TRACK_AD_TOGGLE_W", 39))
    pencil_roff = pad + btn_w
    ad_roff = pencil_roff + gap + ad_w if show_ad_toggle else pencil_roff
    link_roff = ad_roff + gap + btn_w if show_link_toggle else ad_roff
    badge_w = 0
    if show_badge:
        badge_w = QtGui.QFontMetrics(_track_tag_font(font)).horizontalAdvance(
            "Commercial"
        ) + u.px(14)
        badge_roff = link_roff + gap + badge_w
    else:
        badge_roff = link_roff
    return {
        "btn_w": btn_w,
        "ad_w": ad_w,
        "pad": pad,
        "gap": gap,
        "pencil_roff": pencil_roff,
        "ad_roff": ad_roff,
        "link_roff": link_roff,
        "badge_roff": badge_roff,
        "badge_w": badge_w,
        "reserved": badge_roff + u.px(t.TRACK_PAD_RIGHT),
    }


def track_pencil_hit_rect(
    row_rect: QtCore.QRect,
    *,
    show_ad_toggle: bool = False,
    show_link_toggle: bool = False,
) -> QtCore.QRect:
    """Clickable hit target for the track-row edit pencil."""
    layout = _track_action_layout(
        show_ad_toggle=show_ad_toggle, show_link_toggle=show_link_toggle
    )
    return QtCore.QRect(
        row_rect.right() - layout["pencil_roff"],
        row_rect.top(),
        layout["btn_w"],
        row_rect.height(),
    )


def track_commercial_hit_rect(
    row_rect: QtCore.QRect,
    *,
    show_link_toggle: bool = False,
) -> QtCore.QRect:
    """Clickable hit target for the track-row commercial toggle."""
    layout = _track_action_layout(show_ad_toggle=True, show_link_toggle=show_link_toggle)
    return QtCore.QRect(
        row_rect.right() - layout["ad_roff"],
        row_rect.top(),
        layout["ad_w"],
        row_rect.height(),
    )


def track_link_hit_rect(
    row_rect: QtCore.QRect,
    *,
    show_ad_toggle: bool = True,
) -> QtCore.QRect:
    """Clickable hit target for linking a commercial to the track below."""
    layout = _track_action_layout(show_ad_toggle=show_ad_toggle, show_link_toggle=True)
    return QtCore.QRect(
        row_rect.right() - layout["link_roff"],
        row_rect.top(),
        layout["btn_w"],
        row_rect.height(),
    )


def track_commercial_badge_rect(
    row_rect: QtCore.QRect,
    font: Optional[QFont] = None,
    *,
    show_ad_toggle: bool = True,
    show_link_toggle: bool = False,
) -> QtCore.QRect:
    """Vertically centered Commercial badge, left of the right-side actions."""
    layout = _track_action_layout(
        show_ad_toggle=show_ad_toggle,
        show_badge=True,
        show_link_toggle=show_link_toggle,
        font=font,
    )
    th = QtGui.QFontMetrics(_track_tag_font(font)).height() + u.px(4)
    return QtCore.QRect(
        row_rect.right() - layout["badge_roff"],
        row_rect.top() + max(0, (row_rect.height() - th) // 2),
        layout["badge_w"],
        th,
    )


_AD_ASPECT = 669.0 / 301.0
_CHAIN_ASPECT = 152.0 / 1024.0
_ICON_PIX_CACHE: dict = {}


def _resource_path(filename: str):
    from gui.resource_paths import gui_dir

    return gui_dir() / "resources" / filename


def _ad_svg_path():
    return _resource_path("Ad.svg")


def _fit_rect(bounds: QtCore.QRect, aspect: float, *, pad: int = 0) -> QtCore.QRectF:
    """Largest rectangle of `aspect` (width/height) centered in bounds."""
    avail_w = max(1.0, float(bounds.width() - pad * 2))
    avail_h = max(1.0, float(bounds.height() - pad * 2))
    if avail_w / avail_h > aspect:
        h = avail_h
        w = h * aspect
    else:
        w = avail_w
        h = w / aspect
    return QtCore.QRectF(
        bounds.center().x() - w / 2.0,
        bounds.center().y() - h / 2.0,
        w,
        h,
    )


def _tinted_alpha_pixmap(path, dest_w: int, dest_h: int, color: QColor) -> QtGui.QPixmap:
    """Scale a black-on-transparent icon and tint opaque pixels."""
    key = ("alpha", str(path), dest_w, dest_h, color.name(QColor.NameFormat.HexArgb))
    cached = _ICON_PIX_CACHE.get(key)
    if cached is not None:
        return cached
    src = QtGui.QPixmap(str(path))
    scaled = src.scaled(
        max(1, dest_w),
        max(1, dest_h),
        QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
    tinted = QtGui.QPixmap(scaled.size())
    tinted.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(tinted)
    p.drawPixmap(0, 0, scaled)
    p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), color)
    p.end()
    _ICON_PIX_CACHE[key] = tinted
    return tinted


def _recolored_bw_pixmap(path, dest_w: int, dest_h: int, dark: QColor, light: QColor) -> QtGui.QPixmap:
    """Recolor a black-and-white icon, keeping its original shape."""
    key = (
        "bw",
        str(path),
        dest_w,
        dest_h,
        dark.name(QColor.NameFormat.HexArgb),
        light.name(QColor.NameFormat.HexArgb),
    )
    cached = _ICON_PIX_CACHE.get(key)
    if cached is not None:
        return cached
    src = QtGui.QPixmap(str(path))
    scaled = src.scaled(
        max(1, dest_w),
        max(1, dest_h),
        QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
    image = scaled.toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    d_r, d_g, d_b, d_a = dark.red(), dark.green(), dark.blue(), dark.alpha()
    l_r, l_g, l_b, l_a = light.red(), light.green(), light.blue(), light.alpha()
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < 16:
                continue
            if pixel.red() + pixel.green() + pixel.blue() < 384:
                image.setPixelColor(x, y, QColor(d_r, d_g, d_b, d_a))
            else:
                image.setPixelColor(x, y, QColor(l_r, l_g, l_b, l_a))
    out = QtGui.QPixmap.fromImage(image)
    _ICON_PIX_CACHE[key] = out
    return out


def _draw_ad_badge(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    color: QColor,
    *,
    active: bool,
    knock_out: Optional[QColor] = None,
) -> None:
    """Original AD + waves plate, same 669:301 shape, themed high-contrast colors."""
    del color, knock_out
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    dest = _fit_rect(rect, _AD_ASPECT, pad=u.px(1))
    if dest.width() < 8 or dest.height() < 6:
        painter.restore()
        return
    dark = QColor(getattr(t, "TRK_AD_TAG_BORDER", t.TRK_AD_SEL_BORDER))
    light = QColor(getattr(t, "TRK_AD_TAG_BG", "#FFF6D6"))
    if not active:
        dark = QColor(t.TEXT_SEC)
        light = QColor(getattr(t, "TRK_PANE_GRAD_TOP", light))
    pix = _recolored_bw_pixmap(
        _resource_path("Ad.png"),
        max(1, int(dest.width() * 2)),
        max(1, int(dest.height() * 2)),
        dark,
        light,
    )
    painter.drawPixmap(dest.toRect(), pix)
    painter.restore()


def _draw_chain_icon(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    color: QColor,
    *,
    active: bool,
) -> None:
    """Link-commercial control: rotated chain-link icon."""
    del active
    painter.save()
    painter.setRenderHint(
        QtGui.QPainter.RenderHint.Antialiasing
        | QtGui.QPainter.RenderHint.SmoothPixmapTransform
    )
    dest = _fit_rect(rect, 1.0, pad=u.px(4))
    if dest.width() < 8:
        painter.restore()
        return
    pix = _tinted_alpha_pixmap(
        _resource_path("Link.png"),
        max(1, int(dest.width() * 2)),
        max(1, int(dest.height() * 2)),
        color,
    )
    painter.drawPixmap(dest.toRect(), pix)
    painter.restore()


def draw_track_link_chain(
    painter: QtGui.QPainter,
    top_rect: QtCore.QRect,
    bottom_rect: QtCore.QRect,
) -> None:
    """Vertical chain between a commercial row and the music track below it."""
    color = QColor(getattr(t, "TRK_LINK_ACTIVE", t.TRK_AD_SEL_BORDER))
    handle_w = u.px(t.TRACK_HANDLE_W)
    x0 = top_rect.left() + u.px(t.TRACK_LEFT_PAD)
    x = x0 + handle_w / 2.0
    y1 = top_rect.center().y() + u.px(4)
    y2 = bottom_rect.center().y() - u.px(4)
    if y2 <= y1:
        return
    height = y2 - y1
    width = min(float(handle_w), max(u.px(10), height * _CHAIN_ASPECT))
    dest = QtCore.QRectF(x - width / 2.0, y1, width, height)
    painter.save()
    painter.setRenderHint(
        QtGui.QPainter.RenderHint.Antialiasing
        | QtGui.QPainter.RenderHint.SmoothPixmapTransform
    )
    pix = _tinted_alpha_pixmap(
        _resource_path("Chain.png"),
        max(1, int(dest.width() * 2)),
        max(1, int(dest.height() * 2)),
        color,
    )
    painter.drawPixmap(dest.toRect(), pix)
    painter.restore()


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
        name_font = _station_name_font(option.font)
        name_w = QtGui.QFontMetrics(name_font).horizontalAdvance(str(name))
        layout = _station_row_layout(option.font, self._max)
        content_w = (
            u.px(t.STATION_PAD_LEFT)
            + u.px(t.STATION_HANDLE_W)
            + u.px(t.STATION_NUM_W)
            + name_w
            + layout["name_rsrv"]
            + _sel_padding() * 2
        )
        return QtCore.QSize(max(option.rect.width(), content_w), layout["row_h"])

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect     = option.rect
        painter.setClipRect(rect)
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        is_comm = str(index.data(STATION_KIND_ROLE) or "") == "commercials"
        r        = u.px(t.STATION_SEL_RADIUS)
        pad      = _sel_padding()
        frect    = QtCore.QRectF(rect).adjusted(pad, 2, -pad, -2)

        if selected or is_comm:
            # ── Orange (music) or teal (commercials) gradient pill ─────────────
            path = QPainterPath()
            path.addRoundedRect(frect, r, r)

            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if is_comm and selected:
                grad.setColorAt(0.0, QColor(t.STA_COMM_SEL_GRAD_TOP))
                grad.setColorAt(0.5, QColor(t.STA_COMM_SEL_GRAD_MID))
                grad.setColorAt(1.0, QColor(t.STA_COMM_SEL_GRAD_BOT))
                border = t.STA_COMM_SEL_BORDER
            elif is_comm:
                grad.setColorAt(0.0, QColor(t.STA_COMM_GRAD_TOP))
                grad.setColorAt(0.5, QColor(t.STA_COMM_GRAD_MID))
                grad.setColorAt(1.0, QColor(t.STA_COMM_GRAD_BOT))
                border = t.STA_COMM_SEL_BORDER
            else:
                grad.setColorAt(0.0,  QColor(t.STA_SEL_GRAD_TOP))
                grad.setColorAt(0.5,  QColor(t.STA_SEL_GRAD_MID))
                grad.setColorAt(1.0,  QColor(t.STA_SEL_GRAD_BOT))
                border = t.STA_SEL_BORDER
            painter.fillPath(path, QtGui.QBrush(grad))

            # 1px border
            painter.setPen(QPen(QColor(border), 1))
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

        layout = _station_row_layout(option.font, self._max)

        if is_comm:
            text_color = QColor(t.STA_COMM_TEXT)
            count_color = QColor(t.STA_COMM_COUNT)
            pencil_color = QColor(t.STA_COMM_PENCIL)
            handle_color = QColor(t.STA_COMM_TEXT)
        elif selected:
            text_color = QColor("#ffffff")
            count_color = QColor(t.STATION_COUNT_COLOR_SEL)
            pencil_color = QColor(t.STATION_PENCIL_COLOR_SEL)
            handle_color = QColor(255, 255, 255, 180)
        else:
            text_color = QColor(t.S_TEXT)
            count_color = QColor(t.STATION_COUNT_COLOR)
            pencil_color = QColor(t.STATION_PENCIL_COLOR)
            handle_color = QColor(t.BORDER_SOFT)

        x = rect.left() + u.px(t.STATION_PAD_LEFT)
        handle_w = u.px(t.STATION_HANDLE_W)
        num_off = u.px(t.STATION_NUM_OFFSET)
        num_w = u.px(t.STATION_NUM_W)
        name_off = u.px(t.STATION_NAME_OFFSET)

        # Drag-handle glyph (≡)
        painter.setPen(handle_color)
        painter.setFont(_station_count_font(option.font))
        painter.drawText(
            QtCore.QRect(x, rect.top(), handle_w, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            "\u2630",
        )

        # Station / folder number (bold)
        painter.setFont(_station_name_font(option.font))
        painter.setPen(text_color)
        painter.drawText(
            QtCore.QRect(x + num_off, rect.top(), num_w, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            f"{int(num):02d}" if num is not None else "",
        )

        # Station name (bold, elided)
        name_font = _station_name_font(option.font)
        painter.setFont(name_font)
        painter.setPen(text_color)
        name_rect = QtCore.QRect(
            x + name_off,
            rect.top(),
            max(0, rect.width() - name_off - layout["name_rsrv"]),
            rect.height(),
        )
        painter.drawText(
            name_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            QtGui.QFontMetrics(name_font).elidedText(
                str(name), QtCore.Qt.TextElideMode.ElideRight, name_rect.width()
            ),
        )

        # Track count — width from font metrics so "255/255" never clips at high zoom
        painter.setFont(_station_count_font(option.font))
        painter.setPen(count_color)
        count_str = f"{int(count)}/{self._max}" if count is not None else ""
        painter.drawText(
            QtCore.QRect(
                rect.right() - layout["count_roff"],
                rect.top(),
                layout["count_w"],
                rect.height(),
            ),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight,
            count_str,
        )

        # Edit pencil glyph (✎)
        painter.setFont(_station_pencil_font(option.font))
        painter.setPen(pencil_color)
        painter.drawText(
            QtCore.QRect(
                rect.right() - layout["pencil_roff"],
                rect.top(),
                layout["pencil_w"],
                rect.height(),
            ),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            "\u270E",
        )

        painter.restore()


def _full_row_rect(
    view: QtWidgets.QAbstractItemView,
    cell_rect: QtCore.QRect,
    pad: int = _SEL_PADDING,
) -> QtCore.QRect:
    """Return a QRect spanning the visible viewport width for the row.

    Used by TrackItemDelegate (col 0) to paint a pill that covers duration and
    format without leaving a zoom-rounding seam at the right edge.
    """
    vp = view.viewport().rect() if view.viewport() is not None else cell_rect
    width = max(0, vp.width() - 2 * pad)
    return QtCore.QRect(
        vp.left() + pad,
        cell_rect.top(),
        width,
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


TRACK_TITLE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2
TRACK_ARTIST_ROLE = QtCore.Qt.ItemDataRole.UserRole + 3
TRACK_COMMERCIAL_ROLE = QtCore.Qt.ItemDataRole.UserRole + 4
TRACK_COMMERCIAL_TOGGLE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 5
TRACK_LINK_ROLE = QtCore.Qt.ItemDataRole.UserRole + 6
TRACK_LINK_TOGGLE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 7
TRACK_SYNC_ERROR_ROLE = QtCore.Qt.ItemDataRole.UserRole + 8


def track_title_text(item: Optional[QtWidgets.QTableWidgetItem]) -> str:
    """Return the visible track title stored on a title-column item."""
    if item is None:
        return ""
    stored = item.data(TRACK_TITLE_ROLE)
    if stored is not None and str(stored).strip():
        return str(stored)
    return item.text()


def configure_track_title_item(
    item: QtWidgets.QTableWidgetItem,
    title: str,
    *,
    artist: str = "",
    is_commercial: bool = False,
    show_commercial_toggle: bool = False,
    link_to_next: bool = False,
    show_link_toggle: bool = False,
    sync_error: str = "",
) -> None:
    """Store title/artist for the delegate and clear native item text."""
    item.setData(TRACK_TITLE_ROLE, (title or "").strip())
    item.setData(TRACK_ARTIST_ROLE, (artist or "").strip())
    item.setData(TRACK_COMMERCIAL_ROLE, bool(is_commercial))
    item.setData(TRACK_COMMERCIAL_TOGGLE_ROLE, bool(show_commercial_toggle))
    item.setData(TRACK_LINK_ROLE, bool(link_to_next))
    item.setData(TRACK_LINK_TOGGLE_ROLE, bool(show_link_toggle))
    item.setData(TRACK_SYNC_ERROR_ROLE, (sync_error or "").strip())
    item.setText("")
    item.setForeground(QtGui.QBrush(QtCore.Qt.GlobalColor.transparent))


def track_sync_error_text(item: Optional[QtWidgets.QTableWidgetItem]) -> str:
    if item is None:
        return ""
    stored = item.data(TRACK_SYNC_ERROR_ROLE)
    if stored is not None and str(stored).strip():
        return str(stored).strip()
    return ""


def track_is_commercial(item: Optional[QtWidgets.QTableWidgetItem]) -> bool:
    if item is None:
        return False
    return bool(item.data(TRACK_COMMERCIAL_ROLE))


def track_is_linked(item: Optional[QtWidgets.QTableWidgetItem]) -> bool:
    if item is None:
        return False
    return bool(item.data(TRACK_LINK_ROLE))


def track_artist_text(item: Optional[QtWidgets.QTableWidgetItem]) -> str:
    """Return artist text cached on the title-column item."""
    if item is None:
        return ""
    stored = item.data(TRACK_ARTIST_ROLE)
    if stored is not None and str(stored).strip():
        return str(stored)
    return ""


class RowBgDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for non-title columns (Duration, Format) of the track table.

    The selection pill is drawn by CollectionDropTable.drawRow() spanning the
    full row width.  This delegate ONLY draws the cell text with no background,
    so the pill painted by drawRow() shows through cleanly underneath.

    HOW TO EDIT
    -----------
      Text alignment → the AlignVCenter | AlignHCenter flags below.
    """

    def initStyleOption(
        self,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        super().initStyleOption(option, index)
        option.text = ""

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        painter.save()
        text = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        is_sel = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        title_item = None
        view = option.widget
        if isinstance(view, QtWidgets.QTableWidget):
            title_item = view.item(index.row(), 0)
        is_ad = track_is_commercial(title_item)
        is_linked = track_is_linked(title_item)
        painter.setPen(QtGui.QColor(t.TRK_AD_TEXT if is_ad else t.TEXT_PRI))
        painter.setFont(option.font)
        painter.drawText(
            option.rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter,
            str(text),
        )
        if not is_sel and not is_linked:
            painter.setPen(QtGui.QColor(t.LM_TRACK_DIVIDER_COLOR))
            painter.drawLine(
                option.rect.left(),
                option.rect.bottom(),
                option.rect.right(),
                option.rect.bottom(),
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
        return QtCore.QSize(option.rect.width(), u.px(t.TRACK_ROW_H))

    def initStyleOption(
        self,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        """Suppress default item text — we paint title/artist ourselves; Qt would
        center the title over the artist line on unselected rows."""
        super().initStyleOption(option, index)
        option.text = ""
        option.icon = QtGui.QIcon()
        option.features &= ~QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasDisplay
        option.features &= ~QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasDecoration

    def _artist_for_row(
        self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> str:
        view = option.widget
        if isinstance(view, QtWidgets.QTableWidget):
            title_item = view.item(index.row(), 0)
            cached = track_artist_text(title_item)
            if cached:
                return cached
            artist_item = view.item(index.row(), 1)
            if artist_item is not None:
                return artist_item.text()
        sib = index.siblingAtColumn(1)
        if sib.isValid():
            artist = sib.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
            if artist:
                return str(artist)
        return ""

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect     = option.rect
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        view = option.widget
        if isinstance(view, QtWidgets.QAbstractItemView) and view.viewport() is not None:
            painter.setClipRect(view.viewport().rect())

        is_ad = bool(index.data(TRACK_COMMERCIAL_ROLE))
        show_toggle = bool(index.data(TRACK_COMMERCIAL_TOGGLE_ROLE))
        is_linked = bool(index.data(TRACK_LINK_ROLE))
        show_link = bool(index.data(TRACK_LINK_TOGGLE_ROLE))
        actions = _track_action_layout(
            show_ad_toggle=show_toggle,
            show_badge=is_ad,
            show_link_toggle=show_link,
            font=option.font,
        )
        if is_ad:
            if isinstance(view, QtWidgets.QAbstractItemView):
                pad = _sel_padding() if selected else 0
                full_rect = _full_row_rect(view, rect, pad=pad)
                inset = 2 if selected else 1
                frect = QtCore.QRectF(full_rect).adjusted(0, inset, 0, -inset)
                ad_path = QPainterPath()
                ad_path.addRoundedRect(frect, u.px(t.TRACK_SEL_RADIUS), u.px(t.TRACK_SEL_RADIUS))
                ad_grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
                if selected:
                    ad_grad.setColorAt(0.0, QColor(t.TRK_AD_SEL_GRAD_TOP))
                    ad_grad.setColorAt(1.0, QColor(t.TRK_AD_SEL_GRAD_BOT))
                else:
                    ad_grad.setColorAt(0.0, QColor(t.TRK_AD_GRAD_TOP))
                    ad_grad.setColorAt(1.0, QColor(t.TRK_AD_GRAD_BOT))
                painter.fillPath(ad_path, QtGui.QBrush(ad_grad))
                if selected:
                    painter.setPen(QPen(QColor(t.TRK_AD_SEL_BORDER), 1))
                    painter.drawPath(ad_path)
                    painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
                    painter.drawLine(
                        int(frect.left() + u.px(t.TRACK_SEL_RADIUS)),
                        int(frect.top()),
                        int(frect.right() - u.px(t.TRACK_SEL_RADIUS)),
                        int(frect.top()),
                    )
            handle_color = QColor(t.TRK_AD_TEXT)
            pencil_color = QColor(t.TRK_AD_TEXT)
            text_pri = QColor(t.TRK_AD_TEXT)
            text_sec = QColor(t.TRK_AD_TEXT)
        elif selected:
            if isinstance(view, QtWidgets.QAbstractItemView):
                full_rect = _full_row_rect(view, rect)
                frect = QtCore.QRectF(full_rect).adjusted(0, 2, 0, -2)
                _draw_track_sel_pill(painter, full_rect, frect, u.px(t.TRACK_SEL_RADIUS))
            handle_color = QColor(t.TRACK_HANDLE_COLOR_SEL)
            pencil_color = QColor(t.TRACK_PENCIL_COLOR_SEL)
            text_pri = QColor(t.TEXT_PRI)
            text_sec = QColor(t.TEXT_SEC)
        else:
            handle_color = QColor(t.TRACK_HANDLE_COLOR)
            pencil_color = QColor(t.TRACK_PENCIL_COLOR)
            text_pri = QColor(t.TEXT_PRI)
            text_sec = QColor(t.TEXT_SEC)

        handle_w = u.px(t.TRACK_HANDLE_W)
        num_w = u.px(t.TRACK_NUM_W)
        x0 = rect.left() + u.px(t.TRACK_LEFT_PAD)
        num_font = QFont(option.font)
        num_font.setPixelSize(u.px(t.LM_TRACK_NUM_FONT_SIZE))

        # ── Drag handle (≡) ───────────────────────────────────────────────────
        painter.setPen(handle_color)
        painter.setFont(num_font)
        painter.drawText(
            QtCore.QRect(x0, rect.top(), handle_w, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter,
            "\u2630",
        )

        # ── Row number ────────────────────────────────────────────────────────
        row_num = index.row() + 1
        num_rect = QtCore.QRect(x0 + handle_w, rect.top(), num_w, rect.height())
        painter.setPen(QColor(t.TRK_AD_TEXT if is_ad else t.LM_TRACK_NUM_COLOR))
        painter.drawText(
            num_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignCenter,
            f"{row_num:02d}",
        )

        # ── Title + artist ────────────────────────────────────────────────────
        title = track_title_text(
            option.widget.item(index.row(), 0)
            if isinstance(option.widget, QtWidgets.QTableWidget)
            else None
        )
        if not title:
            title = index.data(TRACK_TITLE_ROLE) or index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        artist = self._artist_for_row(option, index)

        content_x = x0 + handle_w + num_w + u.px(t.TRACK_PAD_X)
        content_w = max(1, rect.width() - (content_x - rect.left()) - actions["reserved"])
        gap = u.px(t.TRACK_ARTIST_GAP)
        top_bias = u.px(t.TRACK_TITLE_TOP_BIAS)
        layout_h = min(rect.height(), u.px(t.TRACK_ROW_H))
        mid = layout_h // 2
        title_h = max(1, mid - gap // 2)
        artist_y = rect.top() + mid + (gap + 1) // 2
        artist_h = max(1, layout_h - mid - (gap + 1) // 2 - top_bias)

        title_font = QFont(option.font)
        title_font.setPixelSize(u.px(t.LM_TRACK_TITLE_FONT_SIZE))
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(text_pri)
        painter.drawText(
            QtCore.QRect(content_x, rect.top() + top_bias, content_w, title_h),
            QtCore.Qt.AlignmentFlag.AlignBottom | QtCore.Qt.AlignmentFlag.AlignLeft,
            QtGui.QFontMetrics(title_font).elidedText(
                str(title), QtCore.Qt.TextElideMode.ElideRight, content_w,
            ),
        )

        sync_error = ""
        title_item = (
            option.widget.item(index.row(), 0)
            if isinstance(option.widget, QtWidgets.QTableWidget)
            else None
        )
        if title_item is not None:
            sync_error = track_sync_error_text(title_item)
        elif index.data(TRACK_SYNC_ERROR_ROLE):
            sync_error = str(index.data(TRACK_SYNC_ERROR_ROLE) or "").strip()

        subtitle = sync_error or artist
        if subtitle:
            af = QFont(option.font)
            af.setPixelSize(u.px(t.LM_TRACK_ARTIST_FONT_SIZE))
            af.setBold(False)
            painter.setFont(af)
            if sync_error:
                painter.setPen(QColor(t.TRK_AD_TEXT if is_ad else "#B42318"))
                display = f"Sync failed: {sync_error}"
            else:
                painter.setPen(text_sec)
                display = str(artist)
            painter.drawText(
                QtCore.QRect(content_x, artist_y, content_w, artist_h),
                QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft,
                QtGui.QFontMetrics(af).elidedText(
                    display, QtCore.Qt.TextElideMode.ElideRight, content_w,
                ),
            )

        if is_ad:
            tag_font = _track_tag_font(option.font)
            tag_rect = track_commercial_badge_rect(
                rect,
                option.font,
                show_ad_toggle=show_toggle,
                show_link_toggle=show_link,
            )
            radius = tag_rect.height() / 2.0
            painter.setPen(QPen(QColor(t.TRK_AD_TAG_BORDER), max(1, u.px(1))))
            painter.setBrush(QColor(t.TRK_AD_TAG_BG))
            painter.drawRoundedRect(QtCore.QRectF(tag_rect), radius, radius)
            painter.setPen(QColor(t.TRK_AD_TAG_FG))
            painter.setFont(tag_font)
            painter.drawText(tag_rect, QtCore.Qt.AlignmentFlag.AlignCenter, "Commercial")

        if show_toggle:
            ad_rect = QtCore.QRect(
                rect.right() - actions["ad_roff"],
                rect.top(),
                actions["ad_w"],
                rect.height(),
            )
            if is_ad:
                knock_out = QColor(
                    t.TRK_AD_SEL_GRAD_TOP if selected else t.TRK_AD_GRAD_TOP
                )
            else:
                knock_out = QColor(
                    t.TRK_SEL_GRAD_TOP if selected else t.TRK_PANE_GRAD_TOP
                )
            _draw_ad_badge(
                painter,
                ad_rect,
                pencil_color,
                active=is_ad,
                knock_out=knock_out,
            )

        if show_link:
            link_rect = QtCore.QRect(
                rect.right() - actions["link_roff"],
                rect.top(),
                actions["btn_w"],
                rect.height(),
            )
            _draw_chain_icon(
                painter,
                link_rect,
                QColor(t.TRK_LINK_ACTIVE if is_linked else pencil_color),
                active=is_linked,
            )

        pencil_font = QFont(option.font)
        pencil_font.setBold(True)
        pencil_font.setPixelSize(u.px(t.TRACK_PENCIL_FONT_PX))
        painter.setFont(pencil_font)
        painter.setPen(pencil_color)
        painter.drawText(
            QtCore.QRect(
                rect.right() - actions["pencil_roff"],
                rect.top(),
                actions["btn_w"],
                rect.height(),
            ),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignCenter,
            "\u270E",
        )

        if not selected and not is_linked:
            painter.setPen(QColor(t.LM_TRACK_DIVIDER_COLOR))
            painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()
