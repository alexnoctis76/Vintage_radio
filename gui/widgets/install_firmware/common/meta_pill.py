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
    radius = t.if_pill_radius(t.IF_META_PILL_H)
    return f"""
        QFrame#ifMetaPill {{
            border-radius: {radius}px;
            border: 1px solid {t.IF_META_PILL_BORDER};
            background: {t.IF_META_BOX_BG};
            min-width: {width}px;
            max-width: {width}px;
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
        self.setFixedSize(self._pill_width, t.IF_META_PILL_H)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._apply_style()

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 3, 8, 3)
        lay.setSpacing(0)

        self._label = QtWidgets.QLabel(label.upper())
        self._label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(self._label_style())

        value_row = QtWidgets.QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(4)
        value_row.addStretch(1)

        self._icon = QtWidgets.QLabel()
        self._icon.setFixedSize(t.IF_META_ICON, t.IF_META_ICON)
        self._icon.setVisible(icon is not None)
        if icon is not None:
            self._icon.setPixmap(_icon_pixmap(icon, t.IF_META_ICON))
        value_row.addWidget(self._icon)

        self._value = QtWidgets.QLabel("")
        self._value.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._value.setStyleSheet(self._value_style())
        value_row.addWidget(self._value)
        value_row.addStretch(1)

        lay.addWidget(self._label)
        lay.addLayout(value_row)

    def _label_style(self) -> str:
        return (
            f"color:{t.IF_META_LABEL_FG}; font-size:{u.px(t.IF_META_LABEL_PX)}px; font-weight:900;"
        )

    def _value_style(self) -> str:
        return (
            f"color:{t.IF_META_VALUE_FG}; font-size:{u.px(t.IF_META_VALUE_PX)}px; font-weight:800;"
        )

    def _apply_style(self) -> None:
        self.setStyleSheet(meta_pill_stylesheet(width=self._pill_width))

    def set_value(self, text: str) -> None:
        self._value.setText(text)

    def reload_theme(self) -> None:
        self.setFixedSize(self._pill_width, u.px(t.IF_META_PILL_H))
        self._apply_style()
        self._label.setStyleSheet(self._label_style())
        self._value.setStyleSheet(self._value_style())
        if self._icon_kind is not None:
            icon_sz = u.px(t.IF_META_ICON)
            self._icon.setFixedSize(icon_sz, icon_sz)
            self._icon.setPixmap(_icon_pixmap(self._icon_kind, icon_sz))


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
