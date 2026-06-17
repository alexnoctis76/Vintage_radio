"""Continuous stepped border for the Install Firmware panels grid."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u


def _step_fillet() -> float:
    return float(u.px(max(3, t.IF_TAB_CORNER_RADIUS - 2)))


class FirmwarePanelsBorderOverlay(QtWidgets.QWidget):
    """Transparent overlay — paints one closed outline over tabs, list, and detail."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def sync_geometry(self) -> None:
        host = self.parentWidget()
        if host is not None:
            self.setGeometry(host.rect())

    def _split_x(self) -> float:
        host = self.parentWidget()
        if isinstance(host, FirmwarePanelsHost):
            return host.measure_split_x()
        return float(u.px_layout(t.IF_LIST_WIDTH_HINT))

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        w = self.width()
        h = self.height()
        if w < 4 or h < 4:
            return

        split_x = self._split_x()
        tab_h = float(u.px(t.IF_TAB_H))
        r = float(u.px(t.IF_TAB_CORNER_RADIUS))
        fillet = _step_fillet()

        path = self._outline_path(w, h, split_x=split_x, tab_h=tab_h, radius=r, fillet=fillet)

        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(t.IF_TAB_BORDER))
        pen.setWidthF(max(1.5, u.px(2)))
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()

    @staticmethod
    def _outline_path(
        w: float,
        h: float,
        *,
        split_x: float,
        tab_h: float,
        radius: float,
        fillet: float,
    ) -> QtGui.QPainterPath:
        r = radius
        path = QtGui.QPainterPath()

        # Clockwise outer loop from top-left.
        path.moveTo(0.0, r)
        path.arcTo(QtCore.QRectF(0.0, 0.0, 2.0 * r, 2.0 * r), 180.0, -90.0)
        path.lineTo(split_x - r, 0.0)
        path.arcTo(
            QtCore.QRectF(split_x - 2.0 * r, 0.0, 2.0 * r, 2.0 * r),
            90.0,
            -90.0,
        )
        path.lineTo(split_x, tab_h - fillet)
        path.quadTo(split_x, tab_h, split_x + fillet, tab_h)
        path.lineTo(w - r, tab_h)
        path.arcTo(
            QtCore.QRectF(w - 2.0 * r, tab_h, 2.0 * r, 2.0 * r),
            90.0,
            -90.0,
        )
        path.lineTo(w, h - r)
        path.arcTo(
            QtCore.QRectF(w - 2.0 * r, h - 2.0 * r, 2.0 * r, 2.0 * r),
            0.0,
            -90.0,
        )
        path.lineTo(r, h)
        path.arcTo(
            QtCore.QRectF(0.0, h - 2.0 * r, 2.0 * r, 2.0 * r),
            270.0,
            -90.0,
        )
        path.lineTo(0.0, r)

        # List / detail divider — closes the left column box.
        path.moveTo(split_x, tab_h)
        path.lineTo(split_x, h)

        return path


class FirmwarePanelsHost(QtWidgets.QWidget):
    """Grid host for firmware panels with a border overlay on top."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ifPanelsHost")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#ifPanelsHost { background: transparent; }")
        self._border = FirmwarePanelsBorderOverlay(self)
        self._split_anchor: Optional[QtWidgets.QWidget] = None

    def set_split_anchor(self, widget: QtWidgets.QWidget) -> None:
        """Left-column right edge — border divider follows this widget, not a fixed hint."""
        self._split_anchor = widget

    def measure_split_x(self) -> float:
        if self._split_anchor is not None and self._split_anchor.isVisible():
            pt = self._split_anchor.mapTo(self, QtCore.QPoint(self._split_anchor.width(), 0))
            return float(max(u.px(80), pt.x()))
        return float(u.px_layout(t.IF_LIST_WIDTH_HINT))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._border.sync_geometry()
        self._border.raise_()
        self._border.update()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._border.sync_geometry()
        self._border.raise_()
        self._border.update()

    def reload_border(self) -> None:
        self._border.sync_geometry()
        self._border.update()
