"""Themed QCheckBox — custom-painted indicator; label stays native/transparent."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u


def vintage_checkbox_label_stylesheet(*, font_px: Optional[int] = None) -> str:
    """Label-only QSS; the indicator is painted manually in ``VintageCheckBox``."""
    font = font_px if font_px is not None else u.px(t.VINTAGE_CB_FONT_PX)
    return f"""
        VintageCheckBox {{
            color: {t.VINTAGE_CB_TEXT_FG};
            font-size: {font}px;
            background: transparent;
            border: none;
            padding: 0;
            margin: 0;
        }}
        VintageCheckBox:disabled {{
            color: {t.VINTAGE_CB_DISABLED_FG};
        }}
        VintageCheckBox::indicator {{
            width: 0;
            height: 0;
            border: none;
            margin: 0;
            padding: 0;
            image: none;
        }}
    """


class VintageCheckBox(QtWidgets.QCheckBox):
    """Check box with a custom-painted vintage indicator (works on Windows)."""

    def __init__(
        self,
        text: str = "",
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        font_px: Optional[int] = None,
    ) -> None:
        super().__init__(text, parent)
        self._font_px = font_px
        self._hover = False
        self.setAutoFillBackground(False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.setMouseTracking(True)
        self.apply_theme()

    def apply_theme(self) -> None:
        self.setStyleSheet(vintage_checkbox_label_stylesheet(font_px=self._font_px))
        self.setMinimumHeight(self.sizeHint().height())
        self.updateGeometry()
        self.update()

    def setText(self, text: str) -> None:  # noqa: A003 — Qt API name
        super().setText(text)
        self.setMinimumHeight(self.sizeHint().height())
        self.updateGeometry()
        self.update()

    def _frame_inset(self) -> float:
        """Inset from widget edge so the 2px indicator border is fully inside the clip rect."""
        return u.px(t.VINTAGE_CB_FRAME_PAD) + t.VINTAGE_CB_PEN_W / 2

    def _indicator_rect(self) -> QtCore.QRectF:
        inset = self._frame_inset()
        sz = u.px(t.VINTAGE_CB_SIZE)
        avail_h = max(sz, self.height() - inset * 2)
        y = inset + (avail_h - sz) / 2
        return QtCore.QRectF(inset, y, sz, sz)

    def _text_rect(self) -> QtCore.QRect:
        inset = int(self._frame_inset())
        gap = u.px(t.VINTAGE_CB_SPACING)
        left = inset + u.px(t.VINTAGE_CB_SIZE) + gap
        return QtCore.QRect(left, 0, max(0, self.width() - left), self.height())

    def _content_height(self) -> int:
        fm = self.fontMetrics()
        text_h = fm.height() if self.text() else 0
        inset = self._frame_inset()
        return max(
            int(text_h + inset * 2),
            int(u.px(t.VINTAGE_CB_SIZE) + inset * 2 + 2),
        )

    def sizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        inset = self._frame_inset()
        w = int(
            inset
            + u.px(t.VINTAGE_CB_SIZE)
            + u.px(t.VINTAGE_CB_SPACING)
            + text_w
            + u.px(t.VINTAGE_CB_FRAME_PAD)
        )
        return QtCore.QSize(w, self._content_height())

    def minimumSizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        return self.sizeHint()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: ARG002
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        rect = self._indicator_rect()
        radius = u.px(t.VINTAGE_CB_RADIUS)
        enabled = self.isEnabled()
        checked = self.isChecked()

        if not enabled:
            fill = QtGui.QColor(t.VINTAGE_CB_DISABLED_BG if not checked else t.VINTAGE_CB_DISABLED_CHECK_BG)
            border = QtGui.QColor(t.VINTAGE_CB_DISABLED_BORDER)
        elif checked:
            grad = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
            top = t.ORANGE_BTN_HOVER if self._hover else t.VINTAGE_CB_CHECK_TOP
            grad.setColorAt(0, QtGui.QColor(top))
            grad.setColorAt(1, QtGui.QColor(t.VINTAGE_CB_CHECK_BOT))
            fill = grad
            border = QtGui.QColor(t.VINTAGE_CB_CHECK_BORDER)
        else:
            fill = QtGui.QColor(t.VINTAGE_CB_HOVER_BG if self._hover else t.VINTAGE_CB_BG)
            border = QtGui.QColor(t.BORDER if self._hover else t.VINTAGE_CB_BORDER)

        painter.setPen(QtGui.QPen(border, t.VINTAGE_CB_PEN_W))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)

        if checked and enabled:
            painter.setPen(
                QtGui.QPen(QtGui.QColor(t.VINTAGE_CB_CHECKMARK_FG), 2.2, QtCore.Qt.PenStyle.SolidLine)
            )
            cx, cy = rect.center().x(), rect.center().y()
            path = QtGui.QPainterPath()
            path.moveTo(cx - 5, cy)
            path.lineTo(cx - 1, cy + 4)
            path.lineTo(cx + 6, cy - 4)
            painter.drawPath(path)

        text_color = QtGui.QColor(
            t.VINTAGE_CB_TEXT_FG if enabled else t.VINTAGE_CB_DISABLED_FG
        )
        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(
            self._text_rect(),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            self.text(),
        )

    def hitButton(self, pos: QtCore.QPoint) -> bool:  # type: ignore[override]
        return self.rect().contains(pos)


def apply_vintage_checkbox_theme(
    checkbox: QtWidgets.QCheckBox,
    *,
    font_px: Optional[int] = None,
) -> None:
    """Best-effort theme for a plain ``QCheckBox`` — prefer ``VintageCheckBox``."""
    checkbox.setProperty("vintageCheckbox", True)
    checkbox.setStyleSheet(vintage_checkbox_label_stylesheet(font_px=font_px))
    checkbox.setAutoFillBackground(False)
    checkbox.style().unpolish(checkbox)
    checkbox.style().polish(checkbox)
