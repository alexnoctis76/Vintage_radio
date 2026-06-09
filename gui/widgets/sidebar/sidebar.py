"""
gui/widgets/sidebar/sidebar.py
================================
Sidebar — the left navigation rail.

Each nav button is a checkable _NavButton (QToolButton subclass) that overrides
paintEvent to draw a rich orange gradient + outer ring + radial glow when active,
matching the HTML mockup's skeuomorphic style.

Icons are rendered from inline SVG strings (matching scratch.html exactly) using
QSvgRenderer, replacing the previous Unicode glyph approach.

HOW TO EDIT
-----------
  • Sidebar width             → t.SIDEBAR_WIDTH  (px)
  • Background gradient       → t.SIDEBAR_GRAD_TOP / MID / BOT
  • Button corner radius      → t.SIDEBAR_BTN_RADIUS  (px)
  • Button minimum height     → t.SIDEBAR_BTN_MIN_H  (px)
  • Smaller min-height        → t.SIDEBAR_BTN_MIN_H_SMALL  (Settings/Help)
  • Button label font size    → t.SIDEBAR_BTN_FONT_SIZE  (pt)
  • Icon canvas size          → t.SIDEBAR_ICON_SIZE  (px)
  • Hover overlay             → t.S_HOVER_TINT  (rgba string)
  • Active gradient colours   → t.NAV_ACTIVE_GRAD_TOP / BOT
  • Active ring colour        → t.NAV_ACTIVE_RING_COLOR
  • Active glow opacity       → t.NAV_ACTIVE_GLOW_ALPHA  (0-255)
  • Outer margins             → t.SIDEBAR_MARGINS  (left, top, right, bottom)
  • Gap between buttons       → t.SIDEBAR_SPACING  (px)
  • SVG icon strings          → _SVG_* constants below

TO ADD A NEW PAGE
-----------------
  1.  Add a _SVG_* constant with the SVG string.
  2.  Append an entry to _NAV_ITEMS below.
  3.  Add the widget to the QStackedWidget in radio_manager._build_basic_shell().
"""

from __future__ import annotations
from pathlib import Path
from typing import List, NamedTuple, Optional, Union
from functools import partial

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t


# ── SVG sources — either an inline string or a Path to a resource file ────────
# File-based SVGs are loaded at render time so they work correctly when frozen
# with PyInstaller (resource_paths.gui_dir() handles the path resolution).

def _svg_resource(filename: str) -> Path:
    """Return the absolute path to an SVG in gui/resources/."""
    from gui.resource_paths import gui_dir
    return gui_dir() / "resources" / filename


# These two use the exact SVG files the user supplied.
# The other three remain as inline strings (sourced from scratch.html).
_SVG_LOAD_MUSIC: Union[str, Path] = _svg_resource("Load Music.svg")
_SVG_FIRMWARE:   Union[str, Path] = _svg_resource("Install Firmware.svg")

_SVG_TOOLS = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<path d="M14 50 L38 26" stroke="white" stroke-width="5" stroke-linecap="round"/>'
    '<circle cx="44" cy="20" r="9" stroke="white" stroke-width="4.5" fill="none"/>'
    '<path d="M20 44 L10 54" stroke="white" stroke-width="6" stroke-linecap="round"/>'
    '</svg>'
)

_SVG_SETTINGS = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<circle cx="32" cy="32" r="9" stroke="white" stroke-width="4.5" fill="none"/>'
    '<path d="M32 8v6M32 50v6M8 32h6M50 32h6'
    'M16.7 16.7l4.2 4.2M43.1 43.1l4.2 4.2'
    'M16.7 47.3l4.2-4.2M43.1 20.9l4.2-4.2" '
    'stroke="white" stroke-width="4" stroke-linecap="round"/>'
    '</svg>'
)

_SVG_HELP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<circle cx="32" cy="32" r="24" stroke="white" stroke-width="4.5" fill="none"/>'
    '<path d="M24 24c0-4.4 3.6-8 8-8s8 3.6 8 8c0 5-8 8-8 12" '
    'stroke="white" stroke-width="4.5" fill="none" stroke-linecap="round"/>'
    '<circle cx="32" cy="48" r="3" fill="white"/>'
    '</svg>'
)


class _NavItem(NamedTuple):
    label: str
    svg: Union[str, Path]  # inline SVG string or Path to an SVG resource file
    small: bool = False    # True → SIDEBAR_BTN_MIN_H_SMALL height


_NAV_ITEMS: List[_NavItem] = [
    _NavItem("Load Music",        _SVG_LOAD_MUSIC),
    _NavItem("Install\nFirmware", _SVG_FIRMWARE),
    _NavItem("Tools",             _SVG_TOOLS),
    _NavItem("Settings",          _SVG_SETTINGS, small=True),
    _NavItem("Help",              _SVG_HELP,     small=True),
]

# Divider is inserted AFTER these indices (0-based)
_DIVIDER_AFTER: frozenset = frozenset({1, 3})   # after Tools (idx2→Tools, divider after 1 = Firmware), after Settings


# ── Custom button with QPainter active-state rendering ────────────────────────

class _NavButton(QtWidgets.QToolButton):
    """QToolButton that paints a gradient fill + ring + radial glow when checked."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = self.rect()
        radius = t.SIDEBAR_BTN_RADIUS

        if self.isChecked():
            self._paint_active(p, r, radius)
        elif self.underMouse():
            self._paint_hover(p, r, radius)

        # Let the base class draw icon + text on top (transparent background)
        p.end()
        super().paintEvent(event)

    def _paint_active(self, p: QtGui.QPainter, r: QtCore.QRect, radius: int) -> None:
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(r).adjusted(2, 2, -2, -2), radius, radius)

        # 1. Radial glow behind the button
        cx = r.center().x()
        cy = r.center().y()
        glow = QtGui.QRadialGradient(cx, cy, max(r.width(), r.height()) * 0.7)
        glow_col = QtGui.QColor(t.NAV_ACTIVE_RING_COLOR)
        glow_col.setAlpha(t.NAV_ACTIVE_GLOW_ALPHA)
        glow.setColorAt(0.0, glow_col)
        glow.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
        p.fillRect(r, glow)

        # 2. Orange gradient fill
        grad = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        grad.setColorAt(0.0, QtGui.QColor(t.NAV_ACTIVE_GRAD_TOP))
        grad.setColorAt(1.0, QtGui.QColor(t.NAV_ACTIVE_GRAD_BOT))
        p.fillPath(path, QtGui.QBrush(grad))

        # 3. 2px ring
        p.setPen(QtGui.QPen(QtGui.QColor(t.NAV_ACTIVE_RING_COLOR), 2))
        p.drawPath(path)

        # 4. Inset top highlight
        highlight = QtGui.QColor(255, 255, 255, 56)
        p.setPen(QtGui.QPen(highlight, 1))
        inner = QtCore.QRectF(r).adjusted(3, 3, -3, r.height() // 2)
        p.drawLine(int(inner.left()), int(inner.top()),
                   int(inner.right()), int(inner.top()))

    def _paint_hover(self, p: QtGui.QPainter, r: QtCore.QRect, radius: int) -> None:
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(r), radius, radius)
        hover_col = QtGui.QColor(255, 255, 255, 14)  # very subtle
        p.fillPath(path, hover_col)


# ── Main Sidebar widget ───────────────────────────────────────────────────────

class Sidebar(QtWidgets.QWidget):
    """Left navigation rail.  Emits page_changed(index) when a button is pressed."""

    page_changed = pyqtSignal(int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._buttons: List[_NavButton] = []
        self._group: Optional[QtWidgets.QButtonGroup] = None
        self._build()

    # ── Public references ──────────────────────────────────────────────────────
    @property
    def buttons(self) -> List[QtWidgets.QToolButton]:
        return list(self._buttons)

    @property
    def button_group(self) -> Optional[QtWidgets.QButtonGroup]:
        return self._group

    def set_active(self, index: int) -> None:
        """Programmatically select a nav button without firing page_changed."""
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName("sidebar")
        self.setFixedWidth(t.SIDEBAR_WIDTH)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._apply_style()

        l, top, r, bot = t.SIDEBAR_MARGINS
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(l, top, r, bot)
        v.setSpacing(t.SIDEBAR_SPACING)

        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)

        # Settings and Help buttons live at the bottom; everything before them
        # fills upward with a stretch spacer inserted after Tools (index 2).
        _STRETCH_AFTER = 2

        for idx, item in enumerate(_NAV_ITEMS):
            btn = self._make_button(idx, item)
            self._group.addButton(btn, idx)
            v.addWidget(btn)
            self._buttons.append(btn)

            if idx == _STRETCH_AFTER:
                v.addStretch(1)

            # Thin horizontal divider lines matching the HTML .nav-divider rule
            if idx in _DIVIDER_AFTER:
                v.addWidget(self._make_divider())

    def _make_button(self, idx: int, item: _NavItem) -> _NavButton:
        btn = _NavButton()
        btn.setText(item.label)
        sz = t.SIDEBAR_ICON_SIZE

        icon = QtGui.QIcon()
        icon.addPixmap(
            _render_svg(item.svg, sz, t.S_TEXT),
            QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.Off,
        )
        icon.addPixmap(
            _render_svg(item.svg, sz, "#ffffff"),
            QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.On,
        )
        btn.setIcon(icon)
        btn.setIconSize(QtCore.QSize(sz, sz))
        btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setMinimumHeight(
            t.SIDEBAR_BTN_MIN_H_SMALL if item.small else t.SIDEBAR_BTN_MIN_H
        )
        btn.clicked.connect(partial(self.page_changed.emit, idx))
        self._style_button(btn)
        return btn

    def _make_divider(self) -> QtWidgets.QFrame:
        """Thin horizontal rule between nav groups (matches HTML .nav-divider)."""
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet(
            "background: rgba(255,255,255,0.13); max-height:1px; "
            "margin-top: 10px; margin-bottom: 14px;"
        )
        sep.setFixedHeight(1)
        return sep

    def _style_button(self, btn: _NavButton) -> None:
        btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                color: {t.S_TEXT};
                border: none;
                border-radius: {t.SIDEBAR_BTN_RADIUS}px;
                padding: {t.SIDEBAR_BTN_PADDING};
                font-size: {t.SIDEBAR_BTN_FONT_SIZE}px;
                font-weight: {t.SIDEBAR_BTN_FONT_WEIGHT};
            }}
            QToolButton:checked {{
                color: #ffffff;
            }}
        """)

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            QWidget#sidebar {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0   {t.SIDEBAR_GRAD_TOP},
                    stop:0.45 {t.SIDEBAR_GRAD_MID},
                    stop:1   {t.SIDEBAR_GRAD_BOT}
                );
            }}
        """)

    # ── Theme reload ───────────────────────────────────────────────────────────

    def reload_theme(self) -> None:
        self.setFixedWidth(t.SIDEBAR_WIDTH)
        self._apply_style()
        for idx, btn in enumerate(self._buttons):
            self._style_button(btn)
            item = _NAV_ITEMS[idx]
            btn.setMinimumHeight(
                t.SIDEBAR_BTN_MIN_H_SMALL if item.small else t.SIDEBAR_BTN_MIN_H
            )
        self.update()


# ── SVG icon renderer ─────────────────────────────────────────────────────────

def _render_svg(svg_source: Union[str, Path], size: int, color: str) -> QtGui.QPixmap:
    """Render an SVG into a *size*×*size* QPixmap tinted with *color*.

    *svg_source* can be either:
      - An inline SVG string  (used for the three simple inline icons)
      - A ``pathlib.Path``    (used for Load Music and Install Firmware, which
                               are loaded from gui/resources/ so the exact files
                               supplied by the user are used verbatim)

    All rendered pixels are alpha-masked with *color* via CompositionMode_SourceIn,
    so the original fill/stroke colour of the SVG does not matter — only the
    alpha channel is preserved.

    HOW TO EDIT
    -----------
      Icon colour → passed from _make_button: t.S_TEXT for inactive, white for active.
      Icon size   → t.SIDEBAR_ICON_SIZE
    """
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)

    if isinstance(svg_source, Path):
        renderer = QtSvg.QSvgRenderer(str(svg_source))
    else:
        renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg_source.encode("utf-8")))
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(p, QtCore.QRectF(pix.rect()))

    # Tint: flood-fill with the target colour while respecting the alpha mask
    p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(pix.rect(), QtGui.QColor(color))
    p.end()
    return pix
