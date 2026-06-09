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

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t


def _make_chevron_icon(color: str, width: int = 20, height: int = 12) -> QtGui.QIcon:
    """Render a downward chevron "v" as a QIcon using QSvgRenderer.

    Used for the library dropdown arrow because QSS data URLs with `#` colours
    break Qt's URL parser (# is treated as a fragment delimiter). Rendering via
    QSvgRenderer → QPixmap sidesteps the CSS parsing entirely.

    HOW TO EDIT
    -----------
      Arrow colour → pass a different `color` hex string
      Arrow size   → `width` × `height` arguments
    """
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 10">'
        f'<polyline points="1,2 8,9 15,2" fill="none" stroke="{color}" '
        f'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    ).encode("utf-8")

    pix = QtGui.QPixmap(width, height)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg))
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(p, QtCore.QRectF(pix.rect()))
    p.end()
    return QtGui.QIcon(pix)


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
        self.setFixedHeight(t.LIBBAR_HEIGHT)

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
            f"font-size: {t.LIBBAR_LABEL_FONT_SIZE}px;"
            f"font-weight: {'bold' if t.LIBBAR_LABEL_BOLD else 'normal'};"
            f"background: transparent;"
        )
        self._heading.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        row.addWidget(self._heading)

        # ── Library dropdown ──────────────────────────────────────────────────
        self._combo = QtWidgets.QComboBox()
        self._apply_combo_style()
        self._combo.setFixedHeight(t.LIBBAR_COMBO_H)
        self._combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._combo.currentIndexChanged.connect(self.library_changed)
        row.addWidget(self._combo, 1)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_qss = self._btn_qss()
        for label, sig, tip in [
            ("New",    self.new_clicked,    "Create a new library"),
            ("Rename", self.rename_clicked, "Rename the current library"),
            ("Delete", self.delete_clicked, "Delete the current library"),
        ]:
            btn = QtWidgets.QPushButton(label)
            btn.setToolTip(tip)
            btn.setFixedHeight(t.LIBBAR_BTN_H)
            btn.setStyleSheet(btn_qss)
            btn.clicked.connect(sig)
            row.addWidget(btn)

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

    def _apply_combo_style(self) -> None:
        # Qt's QSS parser treats '#' in data URLs as a fragment delimiter,
        # making SVG data URLs with hex colours unreliable.  Instead we:
        #   1. Style the drop-down to reserve space but show nothing for the arrow
        #   2. Paint the arrow pixmap onto an overlay QLabel positioned on top
        self._combo.setStyleSheet(f"""
            QComboBox {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.LIBBAR_COMBO_GRAD_TOP},
                    stop:1 {t.LIBBAR_COMBO_GRAD_BOT}
                );
                border: 1px solid {t.LIBBAR_COMBO_BORDER};
                border-radius: {t.LIBBAR_COMBO_RADIUS}px;
                padding: {t.LIBBAR_COMBO_PADDING};
                padding-right: {t.LIBBAR_COMBO_ARROW_W + 4}px;
                font-size: {t.LIBBAR_COMBO_FONT_SIZE}px;
                color: {t.TEXT_PRI};
                min-width: {t.LIBBAR_COMBO_MIN_W}px;
                max-width: {t.LIBBAR_COMBO_MAX_W}px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: {t.LIBBAR_COMBO_ARROW_W}px;
                subcontrol-origin: padding;
                subcontrol-position: right center;
            }}
            QComboBox::down-arrow {{
                width: 0px;
                height: 0px;
                image: none;
            }}
            QComboBox QAbstractItemView {{
                background: {t.COMBO_LIST_BG};
                border: 1px solid {t.BORDER};
                selection-background-color: {t.TRACK_SEL};
            }}
        """)
        # Paint the chevron as an overlay label sitting over the drop-down zone.
        # This is repositioned in resizeEvent / showEvent.
        self._install_combo_arrow_overlay()

    def _install_combo_arrow_overlay(self) -> None:
        """Create a transparent QLabel with the chevron pixmap floating over the
        combo's drop-down zone.  This avoids the QSS data-URL '#' parsing issue.
        """
        if not hasattr(self, "_arrow_overlay") or self._arrow_overlay is None:
            self._arrow_overlay = QtWidgets.QLabel(self._combo)
            self._arrow_overlay.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            self._arrow_overlay.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter
            )
        icon = _make_chevron_icon(t.BORDER, 16, 10)
        self._arrow_overlay.setPixmap(icon.pixmap(16, 10))
        self._position_arrow_overlay()

    def _position_arrow_overlay(self) -> None:
        """Keep the arrow overlay aligned with the combo's drop-down zone."""
        if not hasattr(self, "_arrow_overlay") or self._arrow_overlay is None:
            return
        aw   = t.LIBBAR_COMBO_ARROW_W
        ch   = self._combo.height()
        cx   = self._combo.width() - aw
        ow, oh = 16, 10
        right_pad = 8  # px gap between chevron centre-of-zone and the right edge
        self._arrow_overlay.setGeometry(
            cx + (aw - ow) // 2 - right_pad,
            (ch - oh) // 2,
            ow,
            oh,
        )

    def _btn_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: qlineargradient("
            f"    x1:0, y1:0, x2:0, y2:1,"
            f"    stop:0 {t.OUTLINE_BTN_GRAD_TOP},"
            f"    stop:1 {t.OUTLINE_BTN_GRAD_BOT}"
            f"  );"
            f"  border: 2px solid {t.BORDER};"
            f"  border-radius: {t.LIBBAR_BTN_RADIUS}px;"
            f"  padding: {t.LIBBAR_BTN_PADDING};"
            f"  font-size: {t.LIBBAR_BTN_FONT_SIZE}px;"
            f"  color: {t.TEXT_PRI};"
            f"}}"
            f"QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; }}"
            f"QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; }}"
        )

    # ── Geometry events ────────────────────────────────────────────────────────

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._position_arrow_overlay)

    # ── Theme reload ───────────────────────────────────────────────────────────

    def reload_theme(self) -> None:
        self.setFixedHeight(t.LIBBAR_HEIGHT)
        lay = self.layout()
        if lay is not None:
            l, top, r, bot = t.LIBBAR_H_MARGINS
            lay.setContentsMargins(l, top, r, bot)
            lay.setSpacing(t.LIBBAR_SPACING)
        self._heading.setStyleSheet(
            f"color: {t.TEXT_PRI};"
            f"font-size: {t.LIBBAR_LABEL_FONT_SIZE}px;"
            f"font-weight: {'bold' if t.LIBBAR_LABEL_BOLD else 'normal'};"
            f"background: transparent;"
        )
        btn_qss = self._btn_qss()
        for btn in self.findChildren(QtWidgets.QPushButton):
            btn.setFixedHeight(t.LIBBAR_BTN_H)
            btn.setStyleSheet(btn_qss)
        self._apply_bar_style()
        self._apply_combo_style()
        self._combo.setFixedHeight(t.LIBBAR_COMBO_H)
