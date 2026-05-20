"""Decorative background widgets for the vintage radio UI shell."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


class DecorativeImagePanel(QtWidgets.QWidget):
    """Draws a PNG asset as a scaled decorative background.

    The widget is transparent to mouse events so real PyQt controls placed on
    top (via a sibling overlay or stacked layout) remain fully interactive.

    Usage::

        panel = DecorativeImagePanel("/path/to/shell.png", keep_aspect=True)
        panel.setParent(container)
        panel.lower()  # keep behind real widgets

    """

    def __init__(
        self,
        image_path: str,
        keep_aspect: bool = True,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pixmap = QtGui.QPixmap(image_path)
        self._keep_aspect = keep_aspect
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if self._pixmap.isNull():
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self.rect()
        if self._keep_aspect:
            scaled = self._pixmap.scaled(
                rect.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.drawPixmap(rect, self._pixmap)


class RadioShellWidget(QtWidgets.QWidget):
    """Full-page widget that paints a radio shell PNG as a decorative background.

    All child widgets laid out inside this widget render on top of the painted
    shell. Children that should appear "see-through" (group boxes, containers)
    must have ``background: transparent`` in their QSS or palette.

    The shell image is scaled to cover the full widget area while keeping
    its aspect ratio (``KeepAspectRatioByExpanding``), centred so the outer
    gold/brass border is equally cropped on all sides when the window is not
    at the image's native ratio.

    Pass a fallback colour (e.g. ``"#f2ede4"``) that is used when the image
    file is not found — this prevents a stark white flash on first load.
    """

    def __init__(
        self,
        image_path: str,
        fallback_color: str = "#f2ede4",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pixmap = QtGui.QPixmap(image_path)
        self._fallback = QtGui.QColor(fallback_color)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self.rect()
        if self._pixmap.isNull():
            painter.fillRect(rect, self._fallback)
            return
        scaled = self._pixmap.scaled(
            rect.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        x = (rect.width() - scaled.width()) // 2
        y = (rect.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
