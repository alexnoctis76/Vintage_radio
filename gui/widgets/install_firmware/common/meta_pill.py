"""VERSION / DEVICE / AUTHOR meta pills for the software detail card."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Literal, Optional

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets

import gui.theme as t
from gui import ui_scale as u

MetaIconKind = Literal["tag", "chip", "github"]


def _svg_resource(filename: str) -> Path:
    from gui.resource_paths import gui_dir

    return gui_dir() / "resources" / filename


def meta_pill_stylesheet(*, width: int) -> str:
    w = u.px(width)
    return f"""
        QFrame#ifMetaPill {{
            background: transparent;
            border: none;
            min-width: {w}px;
            max-width: {w}px;
        }}
        QFrame#ifMetaPill QLabel {{
            background: transparent;
        }}
    """


def _paint_tag_icon(size: int, color: str) -> QtGui.QPixmap:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(max(1.4, size * 0.11))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    s = size / 16.0
    p.drawRoundedRect(QtCore.QRectF(2 * s, 3 * s, 12 * s, 10 * s), 2 * s, 2 * s)
    p.drawLine(QtCore.QPointF(5 * s, 3 * s), QtCore.QPointF(5 * s, 1.5 * s))
    p.drawLine(QtCore.QPointF(11 * s, 3 * s), QtCore.QPointF(11 * s, 1.5 * s))
    p.end()
    return pix


def _paint_chip_icon(size: int, color: str) -> QtGui.QPixmap:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(max(1.4, size * 0.11))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    s = size / 16.0
    p.drawRoundedRect(QtCore.QRectF(3 * s, 3 * s, 10 * s, 10 * s), 2 * s, 2 * s)
    for px in (6, 10):
        p.drawLine(QtCore.QPointF(px * s, 1 * s), QtCore.QPointF(px * s, 3 * s))
        p.drawLine(QtCore.QPointF(px * s, 13 * s), QtCore.QPointF(px * s, 15 * s))
    for py in (6, 10):
        p.drawLine(QtCore.QPointF(1 * s, py * s), QtCore.QPointF(3 * s, py * s))
        p.drawLine(QtCore.QPointF(13 * s, py * s), QtCore.QPointF(15 * s, py * s))
    p.end()
    return pix


def _paint_github_icon(size: int, color: str) -> QtGui.QPixmap:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QtSvg.QSvgRenderer(str(_svg_resource("Github.svg")))
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(p, QtCore.QRectF(pix.rect()))
    p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(pix.rect(), QtGui.QColor(color))
    p.end()
    return pix


def _icon_pixmap(kind: MetaIconKind, size: int) -> QtGui.QPixmap:
    color = t.IF_META_VALUE_FG
    if kind == "tag":
        return _paint_tag_icon(size, color)
    if kind == "chip":
        return _paint_chip_icon(size, color)
    return _paint_github_icon(size, color)


class MetaPill(QtWidgets.QFrame):
    """Uniform-width rounded pill showing a label + value pair."""

    def __init__(
        self,
        label: str,
        *,
        icon: Optional[MetaIconKind] = None,
        width: Optional[int] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._pill_width = width or t.IF_META_PILL_W
        self._icon_kind = icon
        self.setObjectName("ifMetaPill")
        self.setFixedSize(u.px(self._pill_width), u.px(t.IF_META_PILL_H))
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._apply_style()

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(u.px(8), u.px(3), u.px(8), u.px(3))
        lay.setSpacing(0)

        self._label = QtWidgets.QLabel(label.upper())
        self._label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(self._label_style())

        value_row = QtWidgets.QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(u.px(4))
        value_row.addStretch(1)

        self._icon = QtWidgets.QLabel()
        icon_sz = u.px(t.IF_META_ICON)
        self._icon.setFixedSize(icon_sz, icon_sz)
        self._icon.setVisible(icon is not None)
        if icon is not None:
            self._icon.setPixmap(_icon_pixmap(icon, icon_sz))
        value_row.addWidget(self._icon)

        self._value = QtWidgets.QLabel("")
        self._value.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._value.setStyleSheet(self._value_style())
        self._full_value = ""
        value_row.addWidget(self._value)
        value_row.addStretch(1)

        lay.addWidget(self._label)
        lay.addLayout(value_row)

    def _label_style(self) -> str:
        return (
            f"color:{t.IF_META_LABEL_FG}; font-size:{u.px(t.IF_META_LABEL_PX)}px; "
            f"font-weight:{u.qss_weight(900)};"
        )

    def _value_style(self) -> str:
        return (
            f"color:{t.IF_META_VALUE_FG}; font-size:{u.px(t.IF_META_VALUE_PX)}px; "
            f"font-weight:{u.qss_weight(800)};"
        )

    def _value_text_width(self) -> int:
        margins = u.px(16)
        icon = (u.px(t.IF_META_ICON) + u.px(4)) if self._icon.isVisible() else 0
        return max(u.px(20), self.width() - margins - icon)

    def _apply_value_text(self, text: str) -> None:
        self._full_value = str(text or "")
        available = self._value_text_width()
        fm = QtGui.QFontMetrics(self._value.font())
        shown = fm.elidedText(
            self._full_value,
            QtCore.Qt.TextElideMode.ElideRight,
            available,
        )
        self._value.setText(shown)
        self._value.setToolTip(
            self._full_value if shown != self._full_value else ""
        )

    def _apply_style(self) -> None:
        self.setStyleSheet(meta_pill_stylesheet(width=self._pill_width))

    def paintEvent(self, a0: QtGui.QPaintEvent) -> None:
        """Paint rounded pill chrome — QSS border-radius is ignored by Windows native style."""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = max(u.px(4), self.height() // 2)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, QtGui.QColor(t.IF_META_BOX_BG))
        pen = QtGui.QPen(QtGui.QColor(t.IF_META_PILL_BORDER))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        super().paintEvent(a0)

    def resizeEvent(self, a0: QtGui.QResizeEvent) -> None:
        super().resizeEvent(a0)
        if self._full_value:
            self._apply_value_text(self._full_value)

    def set_value(self, text: str) -> None:
        self._apply_value_text(text)

    def reload_theme(self) -> None:
        self.setFixedSize(u.px(self._pill_width), u.px(t.IF_META_PILL_H))
        self._apply_style()
        self._label.setStyleSheet(self._label_style())
        self._value.setStyleSheet(self._value_style())
        if self._icon_kind is not None:
            icon_sz = u.px(t.IF_META_ICON)
            self._icon.setFixedSize(icon_sz, icon_sz)
            self._icon.setPixmap(_icon_pixmap(self._icon_kind, icon_sz))
        if self._full_value:
            self._apply_value_text(self._full_value)


class AuthorMetaPill(MetaPill):
    """Author pill with GitHub icon and clickable repo link."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(
            "Author",
            icon="github",
            width=t.IF_META_AUTHOR_PILL_W,
            parent=parent,
        )
        self._repo_url = ""
        self._author_name = ""
        self._value.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._value.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._value.setOpenExternalLinks(True)
        self._value.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

    def set_author(self, name: str, repo_url: str = "") -> None:
        self._author_name = str(name or "").strip()
        self._repo_url = str(repo_url or "").strip()
        if self._repo_url and self._author_name:
            safe_name = escape(self._author_name)
            self._value.setText(
                f'<a href="{escape(self._repo_url, quote=True)}" style="color:{t.IF_REPO_AUTHOR_FG}; '
                f'text-decoration: underline;">{safe_name}</a>'
            )
            self._value.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
            )
            self._value.setOpenExternalLinks(True)
            self._value.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        else:
            self._value.setText(self._author_name or "—")
            self._value.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
            self._value.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ArrowCursor))

    def reload_theme(self) -> None:
        super().reload_theme()
        self.set_author(self._author_name, self._repo_url)
