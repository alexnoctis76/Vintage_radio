"""Frameless text editor / viewer dialog (Notes, metadata, etc.)."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from gui.widgets.dialogs.sync.primitives import (
    ModalButton,
    ModalFooter,
    ModalHeader,
    SyncModalShell,
    apply_frameless_modal,
    apply_modal_rounded_mask,
)

ButtonSpec = Tuple[str, str]  # (label, variant)


class VintageTextDialog(QtWidgets.QDialog):
    """Sync-styled dialog with a scrollable text area and footer actions."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        *,
        title: str,
        subtitle: str = "",
        text: str = "",
        read_only: bool = True,
        width: int = t.SYNC_MDL_CONFIRM_W,
        min_height: int = 280,
        buttons: Optional[List[ButtonSpec]] = None,
        monospace: bool = False,
        scrollbar_variant: str = "track",
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self._result_text = text
        self._read_only = read_only

        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")
        self.setFixedWidth(width)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        shell = SyncModalShell()
        header = ModalHeader(title, subtitle)
        header.closed.connect(self.reject)
        shell.add_widget(header)

        body = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(body)
        body_lay.setContentsMargins(
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            12,
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            4,
        )
        body_lay.setSpacing(0)

        self._editor = QtWidgets.QPlainTextEdit()
        self._editor.setPlainText(text)
        self._editor.setReadOnly(read_only)
        self._editor.setMinimumHeight(min_height)
        if monospace:
            mono = (
                QtGui.QFont("Consolas")
                if __import__("sys").platform == "win32"
                else QtGui.QFontDatabase.systemFont(
                    QtGui.QFontDatabase.SystemFont.FixedFont
                )
            )
            self._editor.setFont(mono)
        self._editor.setStyleSheet(f"""
            QPlainTextEdit {{
                color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};
                background: {t.SYNC_MDL_SAFETY_BG};
                border: 1px solid {t.SYNC_MDL_SAFETY_BORDER};
                border-radius: 8px;
                padding: 10px;
                font-size: {u.px(t.SYNC_MDL_CONFIRM_TEXT_SIZE)}px;
            }}
        """)
        scroll_wrap = wrap_with_mockup_scrollbar(
            self._editor,
            variant=scrollbar_variant,  # type: ignore[arg-type]
        )
        body_lay.addWidget(scroll_wrap)
        shell.add_widget(body)

        footer = ModalFooter()
        self._footer = footer
        self._action_buttons: List[ModalButton] = []
        for label, variant in buttons or [("Close", "secondary")]:
            btn = ModalButton(label, variant=variant)  # type: ignore[arg-type]
            btn.clicked.connect(lambda checked=False, lbl=label: self._on_action(lbl))
            footer.add_button(btn)
            self._action_buttons.append(btn)
        shell.add_widget(footer)

        outer.addWidget(shell)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(24, 12, 4, 112))
        shell.setGraphicsEffect(shadow)

        apply_modal_rounded_mask(self)
        self.adjustSize()

    def text(self) -> str:
        return self._editor.toPlainText()

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        self._editor.setReadOnly(read_only)

    def _on_action(self, label: str) -> None:
        self._result_text = self._editor.toPlainText()
        if label.lower() in ("cancel", "close"):
            self.reject()
        else:
            self.accept()

    @staticmethod
    def show_read_only(
        parent: Optional[QtWidgets.QWidget],
        *,
        title: str,
        text: str,
        subtitle: str = "",
    ) -> None:
        dlg = VintageTextDialog(
            parent,
            title=title,
            subtitle=subtitle,
            text=text,
            read_only=True,
            buttons=[("Close", "secondary")],
        )
        dlg.exec()
