"""Vintage-styled progress bar with rounded track, orange fill, and shimmer."""

from __future__ import annotations

import time

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t


class VintageProgressBar(QtWidgets.QWidget):
    """Rounded orange progress bar with animated shimmer on the fill."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = 0
        self._maximum = 0
        self._value = 0
        self._text = ""
        self._indeterminate_offset = 0.0
        self._anim_start = time.monotonic()

        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance_animation)
        self._timer.start(33)

        self.reload_theme()

    def reload_theme(self) -> None:
        self.setFixedHeight(t.SYNC_MDL_PROGRESS_H)

    def setRange(self, minimum: int, maximum: int) -> None:
        self._minimum = minimum
        self._maximum = maximum
        self.update()

    def setValue(self, value: int) -> None:
        self._value = value
        self.update()

    def setText(self, text: str) -> None:
        self._text = text
        self.update()

    def text(self) -> str:
        return self._text

    def maximum(self) -> int:
        return self._maximum

    def value(self) -> int:
        return self._value

    def _advance_animation(self) -> None:
        if not self.isVisible():
            return
        if self._maximum == 0 and self._minimum == 0:
            self._indeterminate_offset = (
                (time.monotonic() - self._anim_start) * 0.35
            ) % 1.0
        self.update()

    def _shimmer_phase(self) -> float:
        """Wall-clock shimmer so the highlight keeps moving even if repaints stall."""
        return (time.monotonic() - self._anim_start) * 0.55 % 1.0

    def _track_rect(self) -> QtCore.QRectF:
        inset = 1.0
        return QtCore.QRectF(
            inset,
            inset,
            max(0.0, self.width() - inset * 2),
            max(0.0, self.height() - inset * 2),
        )

    def _fill_ratio(self) -> float:
        if self._maximum == 0 and self._minimum == 0:
            return 0.0
        span = max(1, self._maximum - self._minimum)
        return min(1.0, max(0.0, (self._value - self._minimum) / span))

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        track = self._track_rect()
        if track.width() <= 0 or track.height() <= 0:
            return

        radius = track.height() / 2.0

        track_grad = QtGui.QLinearGradient(track.topLeft(), track.bottomLeft())
        track_grad.setColorAt(0.0, QtGui.QColor(t.IF_PROGRESS_TRACK_TOP))
        track_grad.setColorAt(1.0, QtGui.QColor(t.IF_PROGRESS_TRACK_BOT))
        painter.setPen(QtGui.QPen(QtGui.QColor(t.IF_PROGRESS_BORDER), 1.0))
        painter.setBrush(QtGui.QBrush(track_grad))
        painter.drawRoundedRect(track, radius, radius)

        if self._maximum == 0 and self._minimum == 0:
            self._paint_indeterminate(painter, track, radius)
        else:
            self._paint_determinate(painter, track, radius)

        if self._text:
            painter.setPen(QtGui.QColor(t.SYNC_MDL_PROGRESS_TEXT_CLR))
            font = painter.font()
            font.setPixelSize(t.SYNC_MDL_PROGRESS_TEXT_SIZE)
            font.setWeight(QtGui.QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(
                track.toRect(),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                self._text,
            )

    def _paint_determinate(
        self, painter: QtGui.QPainter, track: QtCore.QRectF, radius: float
    ) -> None:
        ratio = self._fill_ratio()
        fill_w = track.width() * ratio
        if fill_w <= 0.5:
            # No fill yet — still show shimmer across the empty track while work runs.
            self._paint_shimmer(painter, track)
            return

        fill_rect = QtCore.QRectF(track.left(), track.top(), fill_w, track.height())
        fill_path = QtGui.QPainterPath()
        fill_path.addRoundedRect(fill_rect, radius, radius)

        clip_path = QtGui.QPainterPath()
        clip_path.addRoundedRect(track, radius, radius)
        painter.save()
        painter.setClipPath(clip_path)

        fill_grad = QtGui.QLinearGradient(fill_rect.topLeft(), fill_rect.bottomLeft())
        fill_grad.setColorAt(0.0, QtGui.QColor(t.IF_PROGRESS_FILL_TOP))
        fill_grad.setColorAt(0.58, QtGui.QColor(t.IF_PROGRESS_FILL_MID))
        fill_grad.setColorAt(1.0, QtGui.QColor(t.IF_PROGRESS_FILL_BOT))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(fill_grad))
        painter.drawPath(fill_path)

        self._paint_shimmer(painter, fill_rect)
        painter.restore()

    def _paint_indeterminate(
        self, painter: QtGui.QPainter, track: QtCore.QRectF, radius: float
    ) -> None:
        segment_w = max(track.width() * 0.28, radius * 2)
        travel = max(1.0, track.width() - segment_w)
        x = track.left() + travel * self._indeterminate_offset
        fill_rect = QtCore.QRectF(x, track.top(), segment_w, track.height())

        clip_path = QtGui.QPainterPath()
        clip_path.addRoundedRect(track, radius, radius)
        painter.save()
        painter.setClipPath(clip_path)

        fill_grad = QtGui.QLinearGradient(fill_rect.topLeft(), fill_rect.bottomLeft())
        fill_grad.setColorAt(0.0, QtGui.QColor(t.IF_PROGRESS_FILL_TOP))
        fill_grad.setColorAt(0.58, QtGui.QColor(t.IF_PROGRESS_FILL_MID))
        fill_grad.setColorAt(1.0, QtGui.QColor(t.IF_PROGRESS_FILL_BOT))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(fill_grad))
        painter.drawRoundedRect(fill_rect, radius, radius)

        self._paint_shimmer(painter, fill_rect)
        painter.restore()

    def _paint_shimmer(
        self, painter: QtGui.QPainter, fill_rect: QtCore.QRectF
    ) -> None:
        if fill_rect.width() <= 1.0:
            return

        band_w = max(18.0, fill_rect.width() * 0.35)
        center_x = fill_rect.left() + fill_rect.width() * self._shimmer_phase()
        shimmer_rect = QtCore.QRectF(
            center_x - band_w / 2.0,
            fill_rect.top(),
            band_w,
            fill_rect.height(),
        )

        shimmer_grad = QtGui.QLinearGradient(
            shimmer_rect.topLeft(), shimmer_rect.topRight()
        )
        shimmer_grad.setColorAt(0.0, QtGui.QColor(255, 255, 255, 0))
        shimmer_grad.setColorAt(0.45, QtGui.QColor(255, 255, 255, 55))
        shimmer_grad.setColorAt(0.55, QtGui.QColor(255, 255, 255, 95))
        shimmer_grad.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))

        painter.setCompositionMode(
            QtGui.QPainter.CompositionMode.CompositionMode_SourceOver
        )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(shimmer_grad))
        painter.drawRect(shimmer_rect)
