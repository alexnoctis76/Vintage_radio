"""Vintage Radio styled QComboBox — matches library bar dropdown."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.vintage_chrome import vintage_combo_popup_stylesheet


class _ChevronOverlay(QtWidgets.QWidget):
    """Dropdown chevron painted as SVG at widget size — stays sharp when zoomed."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._stroke = t.BORDER
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_stroke(self, color: str) -> None:
        self._stroke = color
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        w, h = self.width(), self.height()
        if w < 2 or h < 2:
            return
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 12">'
            f'<polyline points="2,4 8,9 14,4" fill="none" stroke="{self._stroke}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            f"</svg>"
        ).encode("utf-8")
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        QtSvg.QSvgRenderer(QtCore.QByteArray(svg)).render(p, QtCore.QRectF(0, 0, w, h))
        p.end()


class _VintageComboItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paint combo rows with vintage selection colors (Windows ignores QSS highlight)."""

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        selected = bool(opt.state & QtWidgets.QStyle.StateFlag.State_Selected)
        hovered = bool(opt.state & QtWidgets.QStyle.StateFlag.State_MouseOver)
        rect = opt.rect.adjusted(4, 1, -4, -1)

        if selected:
            bg = QtGui.QColor(t.TRACK_SEL)
        elif hovered:
            bg = QtGui.QColor(t.LIGHT_BTN_HOVER)
        else:
            bg = QtGui.QColor(t.COMBO_LIST_BG)

        if selected or hovered:
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(rect), 4, 4)
            painter.fillPath(path, bg)

        text = index.data(QtCore.Qt.ItemDataRole.DisplayRole)
        label = "" if text is None else str(text)
        painter.setPen(QtGui.QColor(t.TEXT_PRI))
        painter.setFont(opt.font)
        painter.drawText(
            rect.adjusted(8, 0, -8, 0),
            int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
            label,
        )
        painter.restore()

    def sizeHint(
        self,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtCore.QSize:
        _ = index
        return QtCore.QSize(option.rect.width(), u.px(32))


def _apply_combo_popup_theme(view: QtWidgets.QAbstractItemView) -> None:
    """Theme the detached popup list; palette + delegate override native black highlight."""
    view.setStyleSheet(vintage_combo_popup_stylesheet())
    view.setMouseTracking(True)
    view.setAutoFillBackground(True)
    pal = view.palette()
    pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(t.COMBO_LIST_BG))
    pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(t.COMBO_LIST_BG))
    pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(t.TEXT_PRI))
    pal.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(t.TRACK_SEL))
    pal.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(t.TEXT_PRI))
    view.setPalette(pal)
    if not isinstance(view.itemDelegate(), _VintageComboItemDelegate):
        view.setItemDelegate(_VintageComboItemDelegate(view))


class VintageComboBox(QtWidgets.QComboBox):
    """Combo box with library-bar gradient, border, and chevron overlay."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        min_width: int = t.LIBBAR_COMBO_MIN_W,
        max_width: int = 9999,
        fixed_height: Optional[int] = t.LIBBAR_COMBO_H,
    ) -> None:
        super().__init__(parent)
        self._min_width = min_width
        self._max_width = max_width
        self._fixed_height = fixed_height
        self._layout_min_override: Optional[int] = None
        self._arrow_overlay = _ChevronOverlay(self)
        self.apply_theme()

    def set_layout_min_width(self, design_px: Optional[int]) -> None:
        """Optional tighter min-width for crowded toolbars (None = use _min_width)."""
        self._layout_min_override = design_px

    def _effective_min_width(self) -> int:
        base = self._layout_min_override if self._layout_min_override is not None else self._min_width
        return u.px_layout(base)

    def apply_theme(self) -> None:
        max_w = self._max_width
        max_w_rule = f"max-width: {max_w}px;" if max_w < 9000 else ""
        arrow_w = u.px(t.LIBBAR_COMBO_ARROW_W)
        combo_font = self.font()
        combo_font.setPixelSize(u.px(t.LIBBAR_COMBO_FONT_SIZE))
        self.setFont(combo_font)
        self.setStyleSheet(f"""
            VintageComboBox {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.LIBBAR_COMBO_GRAD_TOP},
                    stop:1 {t.LIBBAR_COMBO_GRAD_BOT}
                );
                border: 1px solid {t.LIBBAR_COMBO_BORDER};
                border-radius: {u.px(t.LIBBAR_COMBO_RADIUS)}px;
                padding: {t.LIBBAR_COMBO_PADDING};
                padding-right: {arrow_w + u.px(4)}px;
                font-size: {u.px(t.LIBBAR_COMBO_FONT_SIZE)}px;
                color: {t.TEXT_PRI};
                min-width: {self._effective_min_width()}px;
                {max_w_rule}
            }}
            VintageComboBox::drop-down {{
                border: none;
                width: {arrow_w}px;
                subcontrol-origin: padding;
                subcontrol-position: right center;
            }}
            VintageComboBox::down-arrow {{
                width: 0px;
                height: 0px;
                image: none;
            }}
        """)
        view = self.view()
        if view is not None:
            _apply_combo_popup_theme(view)
        if self._fixed_height is not None:
            self.setFixedHeight(u.px(self._fixed_height))
        self._arrow_overlay.set_stroke(t.BORDER)
        self._position_arrow_overlay()
        self._arrow_overlay.raise_()
        if self.isEditable():
            self._configure_line_edit()

    def setEditable(self, editable: bool) -> None:
        super().setEditable(editable)
        if editable:
            self._configure_line_edit()
            self._scroll_text_to_start()

    def _configure_line_edit(self) -> None:
        le = self.lineEdit()
        if le is None:
            return
        le.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        le_font = le.font()
        le_font.setPixelSize(u.px(t.LIBBAR_COMBO_FONT_SIZE))
        le.setFont(le_font)
        le.setStyleSheet(f"""
            background: transparent;
            color: {t.TEXT_PRI};
            border: none;
            padding: 0;
            selection-background-color: {t.TRACK_SEL};
        """)
        if not getattr(self, "_line_edit_hooks", False):
            le.textChanged.connect(self._scroll_text_to_start)
            self.currentIndexChanged.connect(self._scroll_text_to_start)
            self._line_edit_hooks = True

    def _scroll_text_to_start(self, *_args) -> None:
        QtCore.QTimer.singleShot(0, self._scroll_text_to_start_impl)

    def _scroll_text_to_start_impl(self) -> None:
        le = self.lineEdit()
        if le is None:
            return
        le.setCursorPosition(0)
        le.home(False)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_arrow_overlay()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._position_arrow_overlay)

    def showPopup(self) -> None:
        super().showPopup()
        view = self.view()
        if view is None:
            return
        _apply_combo_popup_theme(view)
        popup = view.window()
        if popup is not None and popup.isWindow() and popup is not self:
            popup.setStyleSheet(
                f"background-color: {t.COMBO_LIST_BG}; border: 1px solid {t.BORDER};"
            )
            pos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
            popup.move(pos)

    def _chevron_size(self) -> tuple[int, int]:
        return u.px(16), u.px(10)

    def _position_arrow_overlay(self) -> None:
        chevron_w, chevron_h = self._chevron_size()
        aw = u.px(t.LIBBAR_COMBO_ARROW_W)
        right_pad = u.px(6)
        ch = self.height()
        x = self.width() - aw - right_pad + max(0, (aw - chevron_w) // 2)
        y = max(0, (ch - chevron_h) // 2)
        self._arrow_overlay.setFixedSize(chevron_w, chevron_h)
        self._arrow_overlay.move(x, y)
        self._arrow_overlay.raise_()
