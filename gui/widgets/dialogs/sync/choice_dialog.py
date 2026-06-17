"""
Sync choice modal — pick Sync Changes or Replace All Music.

Mockup: gui/scratch.html  #syncChoiceModal
"""

from __future__ import annotations

from typing import Literal, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui.widgets.common.styled_checkbox import VintageCheckBox
from .primitives import (
    ModalFooter,
    ModalHeader,
    ModalButton,
    SafetyNote,
    SyncModalShell,
    SyncOptionCard,
    apply_frameless_modal,
    apply_modal_rounded_mask,
    refresh_modal_rounded_mask,
)

SyncChoice = Literal["changes", "replace", "fast"]


class SyncChoiceDialog(QtWidgets.QDialog):
    """Two-card modal shown when the user clicks Sync to SD Card."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        *,
        sd_display: str,
        library_name: str,
        show_fast_sync: bool = False,
        volume_mismatch: Optional[tuple[str, str]] = None,
    ) -> None:
        super().__init__(parent)
        self._choice: Optional[SyncChoice] = None
        self.setModal(True)
        self.setWindowTitle("Sync music to SD card")
        self.setFixedWidth(t.SYNC_MDL_CHOICE_W)
        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        shell = SyncModalShell()
        self._shell = shell
        subtitle = f"Choose how you want to update {sd_display} from {library_name}."
        header = ModalHeader("Sync music to SD card", subtitle)
        header.closed.connect(self.reject)
        shell.add_widget(header)

        body = QtWidgets.QWidget()
        body.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        body_lay = QtWidgets.QVBoxLayout(body)
        self._body_lay = body_lay
        body_lay.setContentsMargins(
            t.SYNC_MDL_BODY_PAD, t.SYNC_MDL_BODY_PAD, t.SYNC_MDL_BODY_PAD, 16,
        )
        body_lay.setSpacing(t.SYNC_MDL_CARD_GAP)

        if volume_mismatch is not None:
            trusted_vol, current_vol = volume_mismatch
            body_lay.addWidget(
                SafetyNote(
                    f'Your last successful sync used the volume named "{trusted_vol}". '
                    f'The selected path looks like "{current_vol}". '
                    "If this is the wrong card, you could overwrite the wrong device."
                )
            )

        cards_row = QtWidgets.QWidget()
        cards_lay = QtWidgets.QHBoxLayout(cards_row)
        self._cards_lay = cards_lay
        cards_lay.setContentsMargins(0, 0, 0, 0)
        cards_lay.setSpacing(t.SYNC_MDL_CARD_GAP)

        changes_card = SyncOptionCard(
            title="Sync Changes",
            badge="Update",
            description=(
                "Update only the stations and tracks that changed since your last sync. "
                "Existing music stays in place, so this usually finishes faster."
            ),
            helper="Best for regular updates.",
            button_label="Sync Changes",
            button_variant="update",
        )
        changes_card.action_clicked.connect(self._choose_changes)
        cards_lay.addWidget(changes_card, 1)

        replace_card = SyncOptionCard(
            title="Replace All Music",
            badge="Full refresh",
            description=(
                "Formats the SD card, then reloads the entire selected library from scratch. "
                "Use this when loading a new library, making many changes, or starting fresh."
            ),
            helper="Best for new libraries, big changes, or a clean start.",
            button_label="Replace All Music",
            full_refresh=True,
            button_variant="full_refresh",
        )
        replace_card.action_clicked.connect(self._choose_replace)
        cards_lay.addWidget(replace_card, 1)
        body_lay.addWidget(cards_row, 1)
        shell.add_widget(body)

        footer = ModalFooter()
        self._footer = footer
        self._fast_sync_cb: Optional[VintageCheckBox] = None
        if show_fast_sync:
            self._fast_sync_cb = VintageCheckBox("Quick Replace All Music (experimental)")
            self._fast_sync_cb.setToolTip(
                "Prepare an image of your library and write it to the SD card as one file. "
                "Faster than a normal Full Refresh."
            )
            footer.add_left_widget(self._fast_sync_cb)

        cancel_btn = ModalButton("Cancel", variant="secondary")
        cancel_btn.clicked.connect(self.reject)
        footer.add_button(cancel_btn)
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
        self.setFixedWidth(t.SYNC_MDL_CHOICE_W)
        self._body_lay.setContentsMargins(
            t.SYNC_MDL_BODY_PAD, t.SYNC_MDL_BODY_PAD, t.SYNC_MDL_BODY_PAD, 16,
        )
        self._body_lay.setSpacing(t.SYNC_MDL_CARD_GAP)
        self._cards_lay.setSpacing(t.SYNC_MDL_CARD_GAP)
        if self._fast_sync_cb is not None:
            self._fast_sync_cb.apply_theme()
        self._shell.reload_theme()
        self._footer.reload_theme()
        refresh_modal_rounded_mask(self)
        self.adjustSize()
        self.update()

    @property
    def choice(self) -> Optional[SyncChoice]:
        return self._choice

    def _choose_changes(self) -> None:
        self._choice = "changes"
        self.accept()

    def _choose_replace(self) -> None:
        if self._fast_sync_cb is not None and self._fast_sync_cb.isChecked():
            self._choice = "fast"
            self.accept()
            return
        self._choice = "replace"
        self.accept()
