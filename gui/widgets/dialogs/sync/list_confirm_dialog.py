"""Scrollable list confirmation modal — sync chrome for broken-path warnings."""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from .primitives import (
    ModalButton,
    ModalFooter,
    ModalHeader,
    SyncModalShell,
    apply_frameless_modal,
    apply_modal_rounded_mask,
    refresh_modal_rounded_mask,
)


class ScrollableListConfirmDialog(QtWidgets.QDialog):
    """List entries in a scrollable view with OK-only or proceed/cancel actions."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        *,
        window_title: str,
        headline: str,
        explanation: str,
        entries: List[Dict[str, str]],
        line_fmt: Callable[[Dict[str, str]], str],
        proceed_text: Optional[str] = None,
        cancel_text: str = "Cancel",
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(window_title)
        self.setFixedWidth(t.SYNC_MDL_CONFIRM_W)
        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        shell = SyncModalShell()
        self._shell = shell

        header = ModalHeader(window_title, headline)
        header.closed.connect(self.reject)
        shell.add_widget(header)

        body = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(body)
        self._body_lay = body_lay
        body_lay.setContentsMargins(
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            12,
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            4,
        )
        body_lay.setSpacing(10)

        intro_lbl = QtWidgets.QLabel(explanation)
        intro_lbl.setWordWrap(True)
        intro_lbl.setStyleSheet(
            f"color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CONFIRM_TEXT_SIZE)}px;"
            f"background: transparent;"
        )
        body_lay.addWidget(intro_lbl)

        list_body = QtWidgets.QPlainTextEdit()
        list_body.setReadOnly(True)
        list_body.setPlainText("\n\n".join(line_fmt(e) for e in entries))
        list_body.setMinimumHeight(160)
        list_body.setMaximumHeight(280)
        mono = (
            QtGui.QFont("Consolas")
            if sys.platform == "win32"
            else QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        )
        list_body.setFont(mono)
        list_body.setStyleSheet(
            f"color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};"
            f"background: {t.SYNC_MDL_SAFETY_BG};"
            f"border: 1px solid {t.SYNC_MDL_SAFETY_BORDER};"
            f"border-radius: 8px;"
            f"padding: 8px;"
        )
        list_scroll = wrap_with_mockup_scrollbar(list_body, variant="track")
        body_lay.addWidget(list_scroll)
        shell.add_widget(body)

        footer = ModalFooter()
        self._footer = footer
        if proceed_text:
            cancel_btn = ModalButton(cancel_text, variant="secondary")
            cancel_btn.clicked.connect(self.reject)
            proceed_btn = ModalButton(proceed_text, variant="danger")
            proceed_btn.clicked.connect(self.accept)
            footer.add_button(cancel_btn)
            footer.add_button(proceed_btn)
        else:
            ok_btn = ModalButton("OK", variant="primary")
            ok_btn.clicked.connect(self.accept)
            footer.add_button(ok_btn)
        shell.add_widget(footer)

        outer.addWidget(shell)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(24, 12, 4, 112))
        shell.setGraphicsEffect(shadow)

        apply_modal_rounded_mask(self)

    def reload_theme(self) -> None:
        self.setFixedWidth(t.SYNC_MDL_CONFIRM_W)
        self._body_lay.setContentsMargins(
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            12,
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            4,
        )
        self._shell.reload_theme()
        self._footer.reload_theme()
        refresh_modal_rounded_mask(self)
        self.adjustSize()
        self.update()
