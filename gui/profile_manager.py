"""
Device Profile Manager widgets for the Vintage Radio GUI.

ProfileSelectorBar: compact bar with profile dropdown, Save As, and Manage Profiles.
ProfileManagerDialog: full dialog for creating, editing, duplicating, and deleting profiles.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from PyQt6 import QtCore, QtWidgets

from .database import DatabaseManager
from .board_profiles import BOARD_PROFILES_BY_ID, get_board_profile
from .widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from .widgets.dialogs.sync.primitives import ModalButton, begin_sync_modal_dialog
from .widgets.dialogs.vintage_input import get_text
from .widgets.dialogs.vintage_message import VintageMessageBox


class ProfileSelectorBar(QtWidgets.QWidget):
    """
    Compact horizontal bar shown at the top of the Devices tab.

    Contains the profile dropdown, Save As button, Manage Profiles button,
    and a small info label.
    """

    profile_changed = QtCore.pyqtSignal(int)  # emits profile id

    def __init__(
        self,
        db: DatabaseManager,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._updating = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QtWidgets.QLabel("Device Profile:"))

        self._combo = QtWidgets.QComboBox()
        self._combo.setMinimumWidth(200)
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self._combo)

        self._info_label = QtWidgets.QLabel()
        self._info_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._info_label)

        save_as_btn = QtWidgets.QPushButton("Save As...")
        save_as_btn.setToolTip("Create a new profile from the current configuration")
        save_as_btn.clicked.connect(self._save_as)
        layout.addWidget(save_as_btn)

        manage_btn = QtWidgets.QPushButton("Manage Profiles...")
        manage_btn.setToolTip("Open the profile manager to create, edit, or delete profiles")
        manage_btn.clicked.connect(self._open_manager)
        layout.addWidget(manage_btn)

        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        self._updating = True
        try:
            self._combo.clear()
            profiles = self._db.list_device_profiles()
            active = self._db.get_active_profile()
            active_id = active["id"] if active else None

            for p in profiles:
                board = get_board_profile(p["board_id"])
                board_name = board.name if board else p["board_id"]
                label = f"{p['name']}  [{board_name}]"
                self._combo.addItem(label, p["id"])

            if active_id is not None:
                idx = self._combo.findData(active_id)
                if idx >= 0:
                    self._combo.setCurrentIndex(idx)

            self._update_info()
        finally:
            self._updating = False

    def current_profile_id(self) -> Optional[int]:
        data = self._combo.currentData()
        return int(data) if data is not None else None

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        pid = self.current_profile_id()
        if pid is not None:
            self._db.set_active_profile(pid)
            self._update_info()
            self.profile_changed.emit(pid)

    def _update_info(self) -> None:
        profile = self._db.get_active_profile()
        if profile and profile["notes"]:
            truncated = profile["notes"][:60]
            if len(profile["notes"]) > 60:
                truncated += "..."
            self._info_label.setText(truncated)
        else:
            self._info_label.setText("")

    def _save_as(self) -> None:
        active = self._db.get_active_profile()
        if active is None:
            return
        name, ok = get_text(
            self,
            "Save Profile As",
            "New profile name:",
            text=f"{active['name']} (copy)",
        )
        if not ok or not name.strip():
            return
        new_id = self._db.duplicate_device_profile(active["id"], name.strip())
        self._db.set_active_profile(new_id)
        self.refresh()
        self.profile_changed.emit(new_id)

    def _open_manager(self) -> None:
        dlg = ProfileManagerDialog(self._db, self)
        dlg.exec()
        self.refresh()
        active = self._db.get_active_profile()
        if active:
            self.profile_changed.emit(active["id"])


class ProfileManagerDialog(QtWidgets.QDialog):
    """
    Full profile management dialog.

    Left: list of profiles.
    Right: name, notes, board, pin summary, custom driver path.
    Bottom: New, Duplicate, Delete, Close.
    """

    def __init__(
        self,
        db: DatabaseManager,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._db = db

        main_layout, footer = begin_sync_modal_dialog(
            self,
            title="Manage Device Profiles",
            subtitle="Create, duplicate, or delete saved device profiles.",
            min_width=700,
        )

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, 1)

        # Left panel: profile list
        self._list = QtWidgets.QListWidget()
        self._list.currentRowChanged.connect(self._on_list_selection)
        splitter.addWidget(self._list)

        # Right panel: details
        details = QtWidgets.QWidget()
        details_layout = QtWidgets.QFormLayout(details)

        self._name_edit = QtWidgets.QLineEdit()
        self._name_edit.editingFinished.connect(self._save_name)
        details_layout.addRow("Name:", self._name_edit)

        self._notes_edit = QtWidgets.QPlainTextEdit()
        self._notes_edit.setMaximumHeight(80)
        self._notes_edit.textChanged.connect(self._save_notes)
        notes_scroll = wrap_with_mockup_scrollbar(self._notes_edit, variant="track")
        details_layout.addRow("Notes:", notes_scroll)

        self._board_label = QtWidgets.QLabel()
        details_layout.addRow("Board:", self._board_label)

        self._pin_summary = QtWidgets.QLabel()
        self._pin_summary.setWordWrap(True)
        self._pin_summary.setStyleSheet("font-size: 11px; color: #555;")
        details_layout.addRow("Pins:", self._pin_summary)

        self._driver_label = QtWidgets.QLabel()
        self._driver_label.setWordWrap(True)
        details_layout.addRow("Custom Driver:", self._driver_label)

        self._created_label = QtWidgets.QLabel()
        self._created_label.setStyleSheet("font-size: 10px; color: gray;")
        details_layout.addRow("Created:", self._created_label)

        splitter.addWidget(details)
        splitter.setSizes([250, 450])

        new_btn = ModalButton("New Profile", variant="secondary")
        new_btn.clicked.connect(self._new_profile)
        footer.add_left_widget(new_btn)

        dup_btn = ModalButton("Duplicate", variant="secondary")
        dup_btn.clicked.connect(self._duplicate_profile)
        footer.add_left_widget(dup_btn)

        self._delete_btn = ModalButton("Delete", variant="danger")
        self._delete_btn.clicked.connect(self._delete_profile)
        footer.add_left_widget(self._delete_btn)

        close_btn = ModalButton("Close", variant="secondary")
        close_btn.clicked.connect(self.accept)
        footer.add_button(close_btn)

        self._profiles: List[Any] = []
        self._refresh_list()
        self.resize(700, 450)

    def _refresh_list(self) -> None:
        current_row = self._list.currentRow()
        self._profiles = self._db.list_device_profiles()
        self._list.clear()
        for p in self._profiles:
            board = get_board_profile(p["board_id"])
            board_name = board.name if board else p["board_id"]
            suffix = " (default)" if p["is_default"] else ""
            self._list.addItem(f"{p['name']}  [{board_name}]{suffix}")
        if 0 <= current_row < len(self._profiles):
            self._list.setCurrentRow(current_row)
        elif self._profiles:
            self._list.setCurrentRow(0)

    def _selected_profile(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._profiles):
            return self._profiles[row]
        return None

    def _on_list_selection(self, row: int) -> None:
        p = self._selected_profile()
        if p is None:
            self._name_edit.clear()
            self._notes_edit.clear()
            self._board_label.clear()
            self._pin_summary.clear()
            self._driver_label.clear()
            self._created_label.clear()
            self._delete_btn.setEnabled(False)
            return

        self._name_edit.blockSignals(True)
        self._name_edit.setText(p["name"])
        self._name_edit.blockSignals(False)

        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText(p["notes"] or "")
        self._notes_edit.blockSignals(False)

        board = get_board_profile(p["board_id"])
        self._board_label.setText(board.name if board else p["board_id"])

        try:
            cfg = json.loads(p["pin_config_json"]) if p["pin_config_json"] else {}
            pins = cfg.get("pins", {})
            parts = [f"{k}={v}" for k, v in sorted(pins.items())]
            self._pin_summary.setText(", ".join(parts) if parts else "(no pins configured)")
        except (json.JSONDecodeError, TypeError):
            self._pin_summary.setText("(invalid config)")

        self._driver_label.setText(p["custom_hw_driver_path"] or "(built-in)")
        self._created_label.setText(p["created_at"] or "")

        can_delete = not p["is_default"] and len(self._profiles) > 1
        self._delete_btn.setEnabled(can_delete)

    def _save_name(self) -> None:
        p = self._selected_profile()
        if not p:
            return
        name = self._name_edit.text().strip()
        if not name:
            VintageMessageBox.warning(self, "Invalid Name", "Profile name cannot be empty.")
            self._name_edit.setText(p["name"])
            return
        existing = self._db.list_device_profiles()
        for other in existing:
            if other["id"] != p["id"] and other["name"].strip().lower() == name.lower():
                VintageMessageBox.warning(
                    self, "Duplicate Name",
                    f"A profile named \"{other['name']}\" already exists.",
                )
                return
        self._db.update_device_profile(p["id"], name=name)
        self._refresh_list()

    def _save_notes(self) -> None:
        p = self._selected_profile()
        if p:
            self._db.update_device_profile(p["id"], notes=self._notes_edit.toPlainText())

    def _new_profile(self) -> None:
        from .board_profiles import get_default_board_profile
        bp = get_default_board_profile()
        name, ok = get_text(
            self, "New Profile", "Profile name:", text="New Profile"
        )
        if not ok or not name.strip():
            return
        new_id = self._db.create_device_profile(
            name=name.strip(),
            board_id=bp.id,
            pin_config_json=bp.default_config_json(),
        )
        self._db.set_active_profile(new_id)
        self._refresh_list()
        self._list.setCurrentRow(len(self._profiles) - 1)

    def _duplicate_profile(self) -> None:
        p = self._selected_profile()
        if p is None:
            return
        name, ok = get_text(
            self,
            "Duplicate Profile",
            "New profile name:",
            text=f"{p['name']} (copy)",
        )
        if not ok or not name.strip():
            return
        self._db.duplicate_device_profile(p["id"], name.strip())
        self._refresh_list()

    def _delete_profile(self) -> None:
        p = self._selected_profile()
        if p is None:
            return
        reply = VintageMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile \"{p['name']}\"? This cannot be undone.",
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
        )
        if reply == VintageMessageBox.StandardButton.Yes:
            self._db.delete_device_profile(p["id"])
            self._refresh_list()
