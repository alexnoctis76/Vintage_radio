"""
Replace-all confirmation modal — second step before wiping the SD card.

Mockup: gui/scratch.html  #replaceConfirmModal
"""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from .primitives import (
    ModalFooter,
    ModalHeader,
    ModalButton,
    SafetyNote,
    SyncModalShell,
    apply_frameless_modal,
    apply_modal_rounded_mask,
    refresh_modal_rounded_mask,
)


class ReplaceConfirmDialog(QtWidgets.QDialog):
    """Confirm destructive full refresh before formatting the SD card."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        *,
        sd_display: str,
        library_name: str,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Replace all music on this SD card?")
        self.setFixedWidth(t.SYNC_MDL_CONFIRM_W)
        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        shell = SyncModalShell()
        self._shell = shell
        header = ModalHeader(
            "Replace all music on this SD card?",
            "This action refreshes the SD card from the beginning.",
        )
        header.closed.connect(self.reject)
        shell.add_widget(header)

        body = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(body)
        self._body_lay = body_lay
        body_lay.setContentsMargins(
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            16,
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            4,
        )
        body_lay.setSpacing(0)

        sd_html = _html_escape(sd_display)
        lib_html = _html_escape(library_name)
        main_text = QtWidgets.QLabel(
            f"This will remove the music currently on <b>{sd_html}</b> and copy "
            f"<b>{lib_html}</b> to the SD card from the beginning."
        )
        self._main_text = main_text
        main_text.setWordWrap(True)
        main_text.setTextFormat(QtCore.Qt.TextFormat.RichText)
        main_text.setStyleSheet(
            f"color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CONFIRM_TEXT_SIZE)}px;"
            f"background: transparent;"
        )
        body_lay.addWidget(main_text)
        body_lay.addSpacing(14)
        body_lay.addWidget(
            SafetyNote(
                "Your music library on this computer will not be changed.",
                bordered=True,
            )
        )
        shell.add_widget(body)

        footer = ModalFooter()
        self._footer = footer
        cancel_btn = ModalButton("Cancel", variant="secondary")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = ModalButton("Replace All Music", variant="danger")
        confirm_btn.clicked.connect(self.accept)
        footer.add_button(cancel_btn)
        footer.add_button(confirm_btn)
        shell.add_widget(footer)

        outer.addWidget(shell)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(24, 12, 4, 112))
        shell.setGraphicsEffect(shadow)

        apply_modal_rounded_mask(self)

    def reload_theme(self) -> None:
        """Re-apply SYNC_MDL_* tokens (dev theme live-reload)."""
        self.setFixedWidth(t.SYNC_MDL_CONFIRM_W)
        self._body_lay.setContentsMargins(
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            16,
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            4,
        )
        self._main_text.setStyleSheet(
            f"color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CONFIRM_TEXT_SIZE)}px;"
            f"background: transparent;"
        )
        self._shell.reload_theme()
        self._footer.reload_theme()
        refresh_modal_rounded_mask(self)
        self.adjustSize()
        self.update()


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
