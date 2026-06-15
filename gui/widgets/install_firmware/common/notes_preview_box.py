"""Firmware notes preview — bordered text area with thin inline scrollbar."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u


class _InlineNotesScrollBar(QtWidgets.QWidget):
    """Thin no-arrow scrollbar drawn inside the notes preview border."""

    _THUMB_MIN = 24

    def __init__(
        self,
        scroll_area: QtWidgets.QAbstractScrollArea,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._area = scroll_area
        self._bar = scroll_area.verticalScrollBar()
        self._dragging = False
        self._drag_offset = 0
        self.setFixedWidth(t.IF_NOTES_SB_W)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self._bar.valueChanged.connect(self.update)
        self._bar.rangeChanged.connect(self.update)

    def _track_rect(self) -> QtCore.QRect:
        return self.rect().adjusted(0, 6, 0, -6)

    def _thumb_main_size(self, track_h: int) -> int:
        bar = self._bar
        span = bar.maximum() - bar.minimum() + bar.pageStep()
        if span <= 0:
            return track_h
        ratio = bar.pageStep() / span
        return max(self._THUMB_MIN, min(track_h, int(track_h * ratio)))

    def _thumb_pos(self, track_h: int, thumb_h: int) -> int:
        scroll_range = max(1, self._bar.maximum() - self._bar.minimum())
        track_range = max(0, track_h - thumb_h)
        return int(track_range * (self._bar.value() / scroll_range))

    def _thumb_rect(self) -> QtCore.QRect:
        tr = self._track_rect()
        th = self._thumb_main_size(tr.height())
        top = tr.top() + self._thumb_pos(tr.height(), th)
        left = (self.width() - t.IF_NOTES_SB_THUMB_W) // 2
        return QtCore.QRect(left, top, t.IF_NOTES_SB_THUMB_W, th)

    def _scrollable(self) -> bool:
        return self._bar.maximum() > self._bar.minimum()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(t.IF_NOTES_SB_TRACK))
        p.setPen(QtGui.QPen(QtGui.QColor(t.IF_NOTES_SB_TRACK_BORDER), 1))
        p.drawLine(0, 0, 0, self.height())

        if self._scrollable():
            tr = self._thumb_rect()
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(tr), tr.width() / 2.0, tr.width() / 2.0)
            grad = QtGui.QLinearGradient(0, tr.top(), 0, tr.bottom())
            grad.setColorAt(0.0, QtGui.QColor("#f0ad5a"))
            grad.setColorAt(1.0, QtGui.QColor("#bf5c16"))
            p.fillPath(path, QtGui.QBrush(grad))
        p.end()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != QtCore.Qt.MouseButton.LeftButton or not self._scrollable():
            return
        py = int(event.position().y())
        thumb = self._thumb_rect()
        if thumb.contains(int(event.position().x()), py):
            self._dragging = True
            self._drag_offset = py - thumb.top()
            return
        tr = self._track_rect()
        if py < thumb.top():
            self._bar.setValue(self._bar.value() - self._bar.pageStep())
        elif py > thumb.bottom():
            self._bar.setValue(self._bar.value() + self._bar.pageStep())

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if not self._dragging:
            return
        tr = self._track_rect()
        thumb_h = self._thumb_main_size(tr.height())
        track_range = max(1, tr.height() - thumb_h)
        rel = int(event.position().y()) - tr.top() - self._drag_offset
        rel = max(0, min(track_range, rel))
        scroll_range = max(1, self._bar.maximum() - self._bar.minimum())
        self._bar.setValue(int(rel / track_range * scroll_range))

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = False


class NotesPreviewBox(QtWidgets.QFrame):
    """Read-only notes body with border and inline mockup scrollbar."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("notesPreviewBox")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._edit = QtWidgets.QPlainTextEdit()
        self._edit.setObjectName("notesPreviewEdit")
        self._edit.setReadOnly(True)
        self._edit.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        self._scroll = _InlineNotesScrollBar(self._edit)
        lay.addWidget(self._edit, 1)
        lay.addWidget(self._scroll, 0)

        self.apply_theme()

    @property
    def editor(self) -> QtWidgets.QPlainTextEdit:
        return self._edit

    def set_plain_text(self, text: str) -> None:
        self._edit.setPlainText(text)

    def apply_theme(self) -> None:
        self.setStyleSheet(f"""
            #notesPreviewBox {{
                background: {t.IF_NOTES_PREVIEW_BG};
                border: 1px solid {t.IF_NOTES_PREVIEW_BORDER};
                border-radius: 10px;
            }}
        """)
        self._edit.setStyleSheet(f"""
            QPlainTextEdit#notesPreviewEdit {{
                background: transparent;
                color: {t.IF_NOTES_PREVIEW_FG};
                border: none;
                padding: 10px 4px 10px 12px;
                font-size: {u.px(t.IF_NOTES_FONT_SIZE)}px;
            }}
        """)
        self._scroll.update()
