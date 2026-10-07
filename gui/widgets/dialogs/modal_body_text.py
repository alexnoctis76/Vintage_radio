"""Wrapping copy inside frameless modals.

Windows keeps a normal word-wrapped label. macOS QLabel clips the first line
and the last wrapped line in these dialogs, so Darwin uses a borderless text
edit whose height comes from a standalone document (the edit's own document
size stays a few pixels tall until it is painted).
"""

from __future__ import annotations

import re
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u

_FONT_PX_RE = re.compile(r"font-size:\s*(\d+)px")


def wrapped_document_height(text: str, font: QtGui.QFont, width: int, *, rich: bool) -> int:
    """Pixel height of ``text`` wrapped to ``width``, including document margin."""
    doc = QtGui.QTextDocument()
    doc.setDefaultFont(font)
    doc.setDocumentMargin(8)
    opt = QtGui.QTextOption()
    opt.setWrapMode(QtGui.QTextOption.WrapMode.WordWrap)
    doc.setDefaultTextOption(opt)
    if rich:
        doc.setHtml(text or "")
    else:
        doc.setPlainText(text or "")
    doc.setTextWidth(max(40, width))
    return int(doc.size().height())


class ModalBodyText(QtWidgets.QWidget):
    """Drop-in wrapping body for sync-styled modals."""

    def __init__(
        self,
        text: str = "",
        *,
        rich: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._rich = rich
        self._style = ""
        self._plain = text or ""
        self._fitted_dialog = False
        self._syncing_height = False
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        if sys.platform == "darwin":
            # QTextEdit for both plain and rich so setTextFormat(RichText) after
            # construction can call setHtml. QPlainTextEdit has no setHtml.
            self._label: QtWidgets.QLabel | None = None
            edit = QtWidgets.QTextEdit()
            edit.setAcceptRichText(rich)
            edit.setReadOnly(True)
            edit.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            edit.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            edit.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            edit.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            edit.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
            edit.setAutoFillBackground(False)
            edit.viewport().setAutoFillBackground(False)
            pal = edit.palette()
            transparent = QtGui.QColor(0, 0, 0, 0)
            pal.setColor(QtGui.QPalette.ColorRole.Base, transparent)
            edit.setPalette(pal)
            edit.viewport().setPalette(pal)
            self._edit: QtWidgets.QTextEdit | None = edit
            lay.addWidget(edit)
        else:
            self._edit = None
            label = QtWidgets.QLabel(text)
            label.setWordWrap(True)
            if rich:
                label.setTextFormat(QtCore.Qt.TextFormat.RichText)
            self._label = label
            lay.addWidget(label)
        if text:
            self.setText(text)

    def uses_label(self) -> bool:
        return self._label is not None

    def hasHeightForWidth(self) -> bool:  # noqa: N802 — Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 — Qt API
        if self._label is not None:
            return self._label.heightForWidth(width)
        return self._measured_height(width)

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 — Qt API
        if self._label is not None:
            return self._label.sizeHint()
        width = self._measure_width()
        return QtCore.QSize(width, self._measured_height(width))

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802 — Qt API
        return self.sizeHint()

    def setMinimumHeight(self, height: int) -> None:  # noqa: N802 — Qt API
        if self._edit is not None:
            height = max(int(height), self._measured_height(self._measure_width()))
        super().setMinimumHeight(height)

    def setWordWrap(self, wrap: bool) -> None:
        if self._label is not None:
            self._label.setWordWrap(wrap)

    def setTextFormat(self, fmt: QtCore.Qt.TextFormat) -> None:
        rich = fmt == QtCore.Qt.TextFormat.RichText
        if self._label is not None:
            self._rich = rich
            self._label.setTextFormat(fmt)
            return
        if rich == self._rich:
            return
        self._rich = rich
        assert self._edit is not None
        self._edit.setAcceptRichText(rich)
        if self._plain:
            self.setText(self._plain)

    def setAlignment(self, alignment: QtCore.Qt.AlignmentFlag) -> None:
        if self._label is not None:
            self._label.setAlignment(alignment)

    def setStyleSheet(self, style: str) -> None:  # noqa: N802 — Qt API
        self._style = style or ""
        if self._label is not None:
            self._label.setStyleSheet(self._style)
            return
        assert self._edit is not None
        font = QtGui.QFont(self._edit.font())
        font.setPixelSize(self._font_px())
        self._edit.setFont(font)
        self._edit.setStyleSheet(
            "QPlainTextEdit, QTextEdit {"
            f"{self._style}"
            "border: none;"
            "padding: 0;"
            "}"
        )
        self._sync_height()

    def setText(self, text: str) -> None:
        self._plain = text or ""
        if self._label is not None:
            self._label.setText(self._plain)
            return
        assert self._edit is not None
        if self._rich:
            self._edit.setHtml(self._plain)
        else:
            self._edit.setPlainText(self._plain)
        self._sync_height()

    def clear(self) -> None:
        self.setText("")

    def text(self) -> str:
        # Same string that was passed to setText on both platforms. The Mac
        # editor's toPlainText() would strip HTML that QLabel.text() keeps.
        return self._plain

    def fontMetrics(self) -> QtGui.QFontMetrics:  # noqa: N802 — Qt API
        if self._label is not None:
            return self._label.fontMetrics()
        assert self._edit is not None
        return self._edit.fontMetrics()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802 — Qt API
        super().showEvent(event)
        if self._edit is None:
            return
        self._sync_height()
        # Fit a fixed-width modal once. Later shows (More Info) must not
        # resize it or they leave stale pixels behind. Resizable dialogs
        # are left at the size the caller set.
        if not self._fitted_dialog and self._is_fixed_width_frameless_modal():
            self._fitted_dialog = True
            self._grow_dialog()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        if self._edit is None or self._syncing_height:
            return
        if event.oldSize().width() == event.size().width():
            return
        self._syncing_height = True
        try:
            self._sync_height()
        finally:
            self._syncing_height = False

    def _font_px(self) -> int:
        match = _FONT_PX_RE.search(self._style)
        if match:
            return int(match.group(1))
        return u.px(t.SYNC_MDL_CARD_BODY_SIZE)

    def _is_fixed_width_frameless_modal(self) -> bool:
        window = self.window()
        if not isinstance(window, QtWidgets.QDialog):
            return False
        if not (window.windowFlags() & QtCore.Qt.WindowType.FramelessWindowHint):
            return False
        min_w = window.minimumWidth()
        return min_w > 0 and min_w == window.maximumWidth()

    def _measure_width(self) -> int:
        if self.width() > 40:
            return self.width()
        widget: QtWidgets.QWidget | None = self.parentWidget()
        while widget is not None:
            if isinstance(widget, QtWidgets.QDialog):
                dialog_w = widget.width()
                if dialog_w <= 40:
                    dialog_w = max(widget.minimumWidth(), widget.sizeHint().width())
                if dialog_w > 40:
                    return max(80, dialog_w - 2 * t.SYNC_MDL_CONFIRM_BODY_PAD - 2)
            widget = widget.parentWidget()
        return max(80, t.SYNC_MDL_CONFIRM_W - 2 * t.SYNC_MDL_CONFIRM_BODY_PAD - 2)

    def _measured_height(self, width: int) -> int:
        assert self._edit is not None
        font = QtGui.QFont(self._edit.font())
        font.setPixelSize(self._font_px())
        doc_h = wrapped_document_height(self._plain, font, width, rich=self._rich)
        return max(doc_h + QtGui.QFontMetrics(font).lineSpacing(), u.px(24))

    def _sync_height(self) -> None:
        if self._edit is None:
            return
        width = self._measure_width()
        height = self._measured_height(width)
        self._edit.setFixedHeight(height)
        self.setMinimumHeight(height)

    def _grow_dialog(self) -> None:
        window = self.window()
        if not isinstance(window, QtWidgets.QDialog):
            return
        window.adjustSize()
        from gui.widgets.dialogs.sync.primitives import refresh_modal_rounded_mask

        refresh_modal_rounded_mask(window)
