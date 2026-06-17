"""Wizard dialog for quick SD card install (build library image + raw flash)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.styled_combo import VintageComboBox
from gui.widgets.dialogs.sync.primitives import (
    ModalButton,
    ModalFooter,
    ModalHeader,
    SyncModalShell,
    apply_frameless_modal,
    apply_modal_rounded_mask,
)
from gui.widgets.dialogs.vintage_message import VintageMessageBox

from ...sd_disk_image_flash import (
    darwin_list_external_physical_disks,
    format_disk_size,
    is_windows_admin,
    windows_list_non_system_disks,
)


def _field_label_style() -> str:
    return (
        f"color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};"
        f"font-size: {u.px(t.SYNC_MDL_CONFIRM_TEXT_SIZE)}px;"
        f"background: transparent;"
    )


class SdDiskImageFlashWizardDialog(QtWidgets.QDialog):
    """Pick the SD card to receive a full-library install."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        *,
        sd_root: Path,
        default_disk_number: Optional[int],
        default_darwin_bsd_disk: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Replace All Music")
        self.setModal(True)
        self.setFixedWidth(t.SYNC_MDL_CONFIRM_W)

        self._sd_root = sd_root
        self._disk_number: Optional[int] = None
        self._darwin_bsd_disk: Optional[str] = None

        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        shell = SyncModalShell()
        header = ModalHeader(
            "Quick Replace All Music",
            "Copy your whole library to the card in one step.",
        )
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
        body_lay.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Your music is prepared on this computer, then written to the SD card "
            "you choose below. Everything already on that card will be erased."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(_field_label_style())
        body_lay.addWidget(intro)

        self._admin_label = QtWidgets.QLabel()
        self._admin_label.setWordWrap(True)
        self._admin_label.setStyleSheet(
            f"color: {t.SYNC_MDL_CARD_HELPER_CLR}; font-size: {u.px(t.SYNC_MDL_CARD_HELPER_SIZE)}px;"
            f"background: transparent;"
        )
        body_lay.addWidget(self._admin_label)

        disk_title = QtWidgets.QLabel("Which card should we use?")
        disk_title.setStyleSheet(_field_label_style())
        body_lay.addWidget(disk_title)

        self._disk_combo = VintageComboBox(
            min_width=320,
            max_width=640,
            fixed_height=t.TOOLS_ACTION_BTN_H,
        )
        body_lay.addWidget(self._disk_combo)

        shell.add_widget(body)

        footer = ModalFooter()
        cancel_btn = ModalButton("Cancel", variant="secondary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = ModalButton("Continue", variant="primary")
        ok_btn.clicked.connect(self._on_accept)
        footer.add_button(cancel_btn)
        footer.add_button(ok_btn)
        shell.add_widget(footer)

        outer.addWidget(shell)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(24, 12, 4, 112))
        shell.setGraphicsEffect(shadow)

        apply_modal_rounded_mask(self)

        self._populate_disks(default_disk_number, default_darwin_bsd_disk)
        self._refresh_admin()

    def _refresh_admin(self) -> None:
        if sys.platform == "darwin":
            euid = os.geteuid() if hasattr(os, "geteuid") else 0
            if euid == 0:
                self._admin_label.setText("")
                self._admin_label.hide()
            else:
                self._admin_label.setText(
                    "You may be asked for your password to write to the card."
                )
                self._admin_label.show()
        elif is_windows_admin():
            self._admin_label.setText("")
            self._admin_label.hide()
        else:
            self._admin_label.setText(
                "You may see a security prompt asking permission to write to the card."
            )
            self._admin_label.show()

    def _populate_disks(
        self,
        default_disk_number: Optional[int],
        default_darwin_bsd_disk: Optional[str],
    ) -> None:
        self._disk_combo.clear()
        rows: List[Tuple[object, str]] = []

        if sys.platform == "darwin":
            for d in darwin_list_external_physical_disks():
                bsd = str(d.get("BSDName") or "")
                if not bsd:
                    continue
                try:
                    size = int(d.get("Size") or 0)
                except (TypeError, ValueError):
                    size = 0
                vol = str(d.get("VolumeSummary") or "").strip()
                label = f"{bsd} — {format_disk_size(size)}"
                if vol:
                    label += f" — {vol}"
                rows.append((bsd, label))
            if not rows:
                self._disk_combo.addItem("(No removable cards found)", None)
                return
            default_idx = 0
            for i, (bsd, label) in enumerate(rows):
                self._disk_combo.addItem(label, bsd)
                if default_darwin_bsd_disk and bsd == default_darwin_bsd_disk:
                    default_idx = i
            self._disk_combo.setCurrentIndex(default_idx)
            return

        for d in windows_list_non_system_disks():
            try:
                num = int(d["Number"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                size = int(d["Size"])
            except (KeyError, TypeError, ValueError):
                size = 0
            name = str(d.get("FriendlyName") or "SD card")
            vol = str(d.get("VolumeSummary") or "").strip()
            label = f"Drive {num} — {format_disk_size(size)} — {name}"
            if vol:
                label += f" — {vol}"
            rows.append((num, label))

        if not rows:
            self._disk_combo.addItem("(No cards found)", None)
            return

        default_idx = 0
        for i, (num, label) in enumerate(rows):
            self._disk_combo.addItem(label, num)
            if default_disk_number is not None and num == default_disk_number:
                default_idx = i
        self._disk_combo.setCurrentIndex(default_idx)

    @property
    def selected_disk_number(self) -> Optional[int]:
        """Windows physical drive index; always *None* on macOS."""
        return self._disk_number

    @property
    def selected_darwin_bsd_disk(self) -> Optional[str]:
        """Whole-disk BSD name (e.g. ``disk4``) on macOS; *None* on Windows."""
        return self._darwin_bsd_disk

    def _on_accept(self) -> None:
        data = self._disk_combo.currentData()
        if data is None:
            VintageMessageBox.warning(
                self,
                "No card selected",
                "Choose the SD card you want to install your music on.",
            )
            return
        if sys.platform == "darwin":
            self._darwin_bsd_disk = str(data)
            self._disk_number = None
        else:
            self._disk_number = int(data)
            self._darwin_bsd_disk = None
        self.accept()
