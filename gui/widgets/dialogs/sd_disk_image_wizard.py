"""Wizard dialog for experimental SD disk image build + raw flash (Windows / macOS)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets

from ...resource_paths import app_data_dir
from ...sd_disk_image_flash import (
    LAST_CACHED_SD_IMAGE_FILENAME,
    darwin_list_external_physical_disks,
    format_disk_size,
    is_windows_admin,
    windows_list_non_system_disks,
)


class SdDiskImageFlashWizardDialog(QtWidgets.QDialog):
    """Collect options for: optional prepare on PC → build .img → write to physical disk."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        *,
        sd_root: Path,
        default_disk_number: Optional[int],
        default_darwin_bsd_disk: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Experimental: SD image (clean install)")
        self.setModal(True)
        self.resize(520, 260)

        self._sd_root = sd_root
        self._disk_number: Optional[int] = None
        self._darwin_bsd_disk: Optional[str] = None

        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            "Faster than a normal sync — builds a fresh FAT32 image from your library and writes it "
            "to the target disk. The selected disk will be erased."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._admin_label = QtWidgets.QLabel()
        self._admin_label.setWordWrap(True)
        self._admin_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._admin_label)

        self._prepare_on_pc_cb = QtWidgets.QCheckBox(
            "Prepare library on this PC (recommended)"
        )
        self._prepare_on_pc_cb.setChecked(True)
        layout.addWidget(self._prepare_on_pc_cb)

        self._last_img_path = app_data_dir() / "sd_image_cache" / LAST_CACHED_SD_IMAGE_FILENAME
        self._flash_last_cb = QtWidgets.QCheckBox(
            "Flash only (reuse last built image — faster for testing)"
        )
        self._flash_last_cb.setToolTip(
            f"If a previous run succeeded in building an image, it is kept at:\n{self._last_img_path}"
        )
        self._flash_last_cb.stateChanged.connect(self._on_flash_last_changed)
        self._refresh_flash_last_available()
        layout.addWidget(self._flash_last_cb)

        disk_title = (
            "Target disk:" if sys.platform == "darwin" else "Target disk (Windows):"
        )
        layout.addWidget(QtWidgets.QLabel(disk_title))
        self._disk_combo = QtWidgets.QComboBox()
        self._disk_combo.setMinimumWidth(480)
        layout.addWidget(self._disk_combo)

        self._populate_disks(default_disk_number, default_darwin_bsd_disk)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_admin()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self._refresh_flash_last_available()

    def _refresh_flash_last_available(self) -> None:
        try:
            ok = self._last_img_path.is_file() and self._last_img_path.stat().st_size > 0
        except OSError:
            ok = False
        self._flash_last_cb.setEnabled(ok)
        if not ok:
            self._flash_last_cb.setChecked(False)
            self._prepare_on_pc_cb.setEnabled(True)

    def _on_flash_last_changed(self) -> None:
        if self._flash_last_cb.isChecked():
            self._prepare_on_pc_cb.setChecked(False)
            self._prepare_on_pc_cb.setEnabled(False)
        else:
            self._prepare_on_pc_cb.setEnabled(True)

    def _refresh_admin(self) -> None:
        if sys.platform == "darwin":
            euid = os.geteuid() if hasattr(os, "geteuid") else 0
            if euid == 0:
                self._admin_label.setText("")
                self._admin_label.hide()
            else:
                self._admin_label.setText(
                    "Writing requires your macOS password or Touch ID."
                )
                self._admin_label.show()
        elif is_windows_admin():
            self._admin_label.setText("")
            self._admin_label.hide()
        else:
            self._admin_label.setText(
                "Writing requires Windows administrator (UAC) approval."
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
                else:
                    label += " — (no mounted volumes / no label)"
                rows.append((bsd, label))
            if not rows:
                self._disk_combo.addItem("(No external physical disks found)", None)
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
            name = str(d.get("FriendlyName") or "Disk")
            bus = str(d.get("BusType") or "")
            vol = str(d.get("VolumeSummary") or "").strip()
            removable = d.get("IsRemovable")
            rem_txt = ""
            if removable is True:
                rem_txt = " — removable"
            elif removable is False:
                rem_txt = " — not marked removable"
            label = f"PhysicalDrive{num} — {format_disk_size(size)} — {name}"
            if bus:
                label += f" ({bus})"
            label += rem_txt
            if vol:
                label += f" — volumes: {vol}"
            else:
                label += " — volumes: (none mounted / no label)"
            rows.append((num, label))

        if not rows:
            self._disk_combo.addItem("(No disks found — run as Administrator?)", None)
            return

        default_idx = 0
        for i, (num, label) in enumerate(rows):
            self._disk_combo.addItem(label, num)
            if default_disk_number is not None and num == default_disk_number:
                default_idx = i
        self._disk_combo.setCurrentIndex(default_idx)

    @property
    def prepare_on_pc(self) -> bool:
        return self._prepare_on_pc_cb.isChecked()

    @property
    def flash_last_image_only(self) -> bool:
        return self._flash_last_cb.isChecked() and self._flash_last_cb.isEnabled()

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
            QtWidgets.QMessageBox.warning(
                self,
                "No disk",
                "Select a target physical disk.",
            )
            return
        if self._flash_last_cb.isChecked():
            try:
                ok_img = self._last_img_path.is_file() and self._last_img_path.stat().st_size > 0
            except OSError:
                ok_img = False
            if not ok_img:
                QtWidgets.QMessageBox.warning(
                    self,
                    "No cached image",
                    f"Cached disk image not found or empty:\n{self._last_img_path}\n\n"
                    "Run a full SD image sync once to build it.",
                )
                return
        if sys.platform == "darwin":
            self._darwin_bsd_disk = str(data)
            self._disk_number = None
        else:
            self._disk_number = int(data)
            self._darwin_bsd_disk = None
        self.accept()
