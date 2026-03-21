"""
Pin Configuration Editor widgets for the Vintage Radio GUI.

Provides visual editing of pin assignments, board selection,
and a raw JSON editor for advanced users.

The pin table is presented in a popup dialog to prevent accidental edits.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt6 import QtCore, QtWidgets, QtGui

from .board_profiles import (
    BOARD_PROFILES,
    BOARD_PROFILES_BY_ID,
    BoardProfile,
    PIN_FUNCTION_LABELS,
    SPI_FUNCTION_LABELS,
    get_board_profile,
    get_default_board_profile,
)

# Sections that contain GPIO pin numbers (validated for range/conflict)
_GPIO_SECTIONS = ("pins", "spi", "spi_alt")

# spi and spi_alt are mutually exclusive alternatives -- don't cross-check them
_SPI_MUTUAL_EXCLUSIVE = {"spi", "spi_alt"}


class BoardSelectorWidget(QtWidgets.QWidget):
    """Dropdown for selecting a target board, with info label."""

    board_changed = QtCore.pyqtSignal(str)  # emits board_id

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QtWidgets.QLabel("Target Board:"))
        self._combo = QtWidgets.QComboBox()
        for bp in BOARD_PROFILES:
            self._combo.addItem(f"{bp.name} ({bp.mcu})", bp.id)
        self._combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._combo)

        self._info_label = QtWidgets.QLabel()
        self._info_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._info_label)
        layout.addStretch()

    def _on_changed(self) -> None:
        board_id = self.current_board_id()
        bp = get_board_profile(board_id)
        if bp:
            self._info_label.setText(bp.notes[:80] if bp.notes else "")
        self.board_changed.emit(board_id)

    def current_board_id(self) -> str:
        return self._combo.currentData() or get_default_board_profile().id

    def set_board_id(self, board_id: str) -> None:
        idx = self._combo.findData(board_id)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)


class PinConfigDialog(QtWidgets.QDialog):
    """
    Modal dialog for editing pin assignments, custom driver, and DFPlayer settings.

    Opened via a "Configure Pins..." button. Changes are only applied when
    the user clicks Save.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        board_profile: Optional[BoardProfile],
        custom_driver_path: str = "",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pin Configuration")
        self.resize(720, 520)

        self._board_profile = board_profile
        self._config = copy.deepcopy(config)
        self._custom_driver_path = custom_driver_path or ""
        self._updating = False
        self._accepted = False

        main_layout = QtWidgets.QVBoxLayout(self)

        # Pin table
        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Function", "Value", "Description"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.verticalHeader().setVisible(False)
        main_layout.addWidget(self._table)

        # Custom hardware driver row
        driver_group = QtWidgets.QGroupBox("Custom Hardware Driver")
        driver_vlayout = QtWidgets.QVBoxLayout(driver_group)

        driver_path_row = QtWidgets.QHBoxLayout()
        self._driver_path_edit = QtWidgets.QLineEdit()
        self._driver_path_edit.setPlaceholderText("(using built-in driver)")
        self._driver_path_edit.setReadOnly(True)
        self._driver_path_edit.setText(self._custom_driver_path)
        driver_path_row.addWidget(self._driver_path_edit, 1)
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_driver)
        driver_path_row.addWidget(browse_btn)
        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_driver)
        driver_path_row.addWidget(clear_btn)
        driver_vlayout.addLayout(driver_path_row)

        template_row = QtWidgets.QHBoxLayout()
        template_btn = QtWidgets.QPushButton("Download Driver Template...")
        template_btn.setToolTip(
            "Save a documented starter file you can fill in for your own hardware"
        )
        template_btn.clicked.connect(self._download_template)
        template_row.addWidget(template_btn)

        docs_btn = QtWidgets.QPushButton("View Driver Guide...")
        docs_btn.setToolTip(
            "Open the full custom-driver documentation in a viewer"
        )
        docs_btn.clicked.connect(self._view_driver_docs)
        template_row.addWidget(docs_btn)
        template_row.addStretch()
        driver_vlayout.addLayout(template_row)

        main_layout.addWidget(driver_group)

        # Bottom buttons
        btn_layout = QtWidgets.QHBoxLayout()
        reset_btn = QtWidgets.QPushButton("Reset to Defaults")
        reset_btn.setToolTip("Reset all pins to the selected board's defaults")
        reset_btn.clicked.connect(self._reset_to_defaults)
        btn_layout.addWidget(reset_btn)

        edit_json_btn = QtWidgets.QPushButton("Edit Raw JSON")
        edit_json_btn.setToolTip("Edit the raw JSON configuration")
        edit_json_btn.clicked.connect(self._open_json_editor)
        btn_layout.addWidget(edit_json_btn)

        btn_layout.addStretch()

        save_btn = QtWidgets.QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        main_layout.addLayout(btn_layout)
        self._rebuild_table()

    def get_config(self) -> Optional[Dict[str, Any]]:
        return self._config if self._accepted else None

    def get_custom_driver_path(self) -> str:
        return self._custom_driver_path if self._accepted else ""

    def was_accepted(self) -> bool:
        return self._accepted

    # ---- Table building ----

    @staticmethod
    def _pretty_pin_key(key: str) -> str:
        """Turn a snake_case pin key into a readable label."""
        return key.replace("_", " ").title()

    def _rebuild_table(self) -> None:
        self._updating = True
        try:
            pins = self._config.get("pins", {})
            spi = self._config.get("spi", {})
            spi_alt = self._config.get("spi_alt", {})
            dfp = self._config.get("dfplayer", {})

            rows: List[tuple] = []
            for key, label in PIN_FUNCTION_LABELS.items():
                if key in pins:
                    rows.append(("pins", key, label, pins[key]))

            # Show any extra pin keys not in PIN_FUNCTION_LABELS (e.g. vs1053_*, custom driver pins)
            for key in pins:
                if key not in PIN_FUNCTION_LABELS:
                    rows.append(("pins", key, self._pretty_pin_key(key), pins[key]))

            bp = self._board_profile
            if bp and bp.supports_sd_spi and spi:
                for key, label in SPI_FUNCTION_LABELS.items():
                    if key in spi:
                        rows.append(("spi", key, f"Primary {label}", spi[key]))

            if bp and bp.supports_sd_spi and spi_alt:
                for key, label in SPI_FUNCTION_LABELS.items():
                    if key in spi_alt:
                        rows.append(("spi_alt", key, f"Alt {label}", spi_alt[key]))

            if dfp:
                if "max_volume" in dfp:
                    rows.append(("dfplayer", "max_volume", "DFPlayer Max Volume (0-30)", dfp["max_volume"]))
                if "uart_baud" in dfp:
                    rows.append(("dfplayer", "uart_baud", "UART Baud Rate", dfp["uart_baud"]))

            self._table.setRowCount(len(rows))
            self._row_keys: List[tuple] = []
            for i, (section, key, label, value) in enumerate(rows):
                self._row_keys.append((section, key))

                func_item = QtWidgets.QTableWidgetItem(label)
                func_item.setFlags(func_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, 0, func_item)

                spin = QtWidgets.QSpinBox()
                spin.setMinimum(0)
                spin.setMaximum(_spinbox_max(section, key))
                spin.setValue(int(value))
                spin.valueChanged.connect(lambda val, r=i: self._on_value_changed(r, val))
                self._table.setCellWidget(i, 1, spin)

                desc = self._describe(section, key, int(value))
                desc_item = QtWidgets.QTableWidgetItem(desc)
                desc_item.setFlags(desc_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                if "WARNING" in desc or "CONFLICT" in desc:
                    desc_item.setForeground(QtGui.QColor("#c00"))
                self._table.setItem(i, 2, desc_item)
        finally:
            self._updating = False

    # ---- Validation helpers ----

    def _describe(self, section: str, key: str, value: int) -> str:
        parts = []
        pin_warn = self._get_pin_description(section, key, value)
        if pin_warn:
            parts.append(pin_warn)
        conflict = self._check_pin_conflict(section, key, value)
        if conflict:
            parts.append(conflict)
        return "; ".join(parts)

    def _get_pin_description(self, section: str, key: str, pin: int) -> str:
        if section not in _GPIO_SECTIONS or key == "bus":
            return ""
        if not self._board_profile:
            return ""
        if pin in self._board_profile.restricted_pins:
            return f"WARNING: {self._board_profile.restricted_pins[pin]}"
        lo, hi = self._board_profile.gpio_range
        if pin < lo or pin > hi:
            return f"WARNING: outside valid range ({lo}-{hi})"
        return ""

    def _check_pin_conflict(self, section: str, key: str, pin: int) -> str:
        """Check if the same GPIO pin is used by more than one function.

        spi_alt is a fallback bus -- it only activates when primary SPI
        fails, so it never conflicts with pins or spi.  spi_alt entries
        only conflict-check within spi_alt itself.  Similarly, when
        checking a pins/spi entry we skip spi_alt entirely.
        """
        if section not in _GPIO_SECTIONS or key == "bus":
            return ""

        if section == "spi_alt":
            check_sections = ("spi_alt",)
        else:
            check_sections = ("pins", "spi")

        conflicts = []
        for check_section in check_sections:
            sub = self._config.get(check_section, {})
            for k, v in sub.items():
                if k == "bus":
                    continue
                if (check_section, k) != (section, key) and v == pin:
                    label = PIN_FUNCTION_LABELS.get(k) or SPI_FUNCTION_LABELS.get(k) or self._pretty_pin_key(k)
                    conflicts.append(label)
        if conflicts:
            return f"CONFLICT: pin {pin} also used by {', '.join(conflicts)}"
        return ""

    # ---- Handlers ----

    def _on_value_changed(self, row: int, value: int) -> None:
        if self._updating or row >= len(self._row_keys):
            return
        section, key = self._row_keys[row]
        if section not in self._config:
            self._config[section] = {}
        self._config[section][key] = value

        desc = self._describe(section, key, value)
        desc_item = self._table.item(row, 2)
        if desc_item:
            desc_item.setText(desc)
            if "WARNING" in desc or "CONFLICT" in desc:
                desc_item.setForeground(QtGui.QColor("#c00"))
            else:
                desc_item.setForeground(QtGui.QColor())

    def _reset_to_defaults(self) -> None:
        if not self._board_profile:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Pins",
            f"Reset all pins to {self._board_profile.name} defaults?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._config = copy.deepcopy(self._board_profile.default_pin_config)
            self._rebuild_table()

    def _open_json_editor(self) -> None:
        dlg = PinConfigJsonDialog(self._config, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            new_config = dlg.get_json_config()
            if new_config is not None:
                self._config = new_config
                self._rebuild_table()

    def _browse_driver(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Custom Hardware Driver",
            "",
            "Python Files (*.py);;All Files (*)",
        )
        if path:
            self._custom_driver_path = path
            self._driver_path_edit.setText(path)

    def _clear_driver(self) -> None:
        self._custom_driver_path = ""
        self._driver_path_edit.clear()

    def _download_template(self) -> None:
        """Let the user save a copy of the custom driver template file."""
        from .resource_paths import project_root

        src = project_root() / "firmware" / "custom_driver_template.py"
        if not src.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Template Not Found",
                f"Could not find the template at:\n{src}\n\n"
                "It may have been removed from this installation.",
            )
            return

        dest, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Driver Template",
            str(Path.home() / "my_hardware.py"),
            "Python Files (*.py);;All Files (*)",
        )
        if dest:
            try:
                shutil.copy2(src, dest)
                QtWidgets.QMessageBox.information(
                    self,
                    "Template Saved",
                    f"Driver template saved to:\n{dest}\n\n"
                    "Open it in your editor, fill in the methods, then select "
                    "it with Browse above.",
                )
            except OSError as e:
                QtWidgets.QMessageBox.warning(
                    self, "Save Failed", f"Could not save template:\n{e}"
                )

    def _view_driver_docs(self) -> None:
        """Show the CUSTOM_DRIVER.md guide in a scrollable dialog."""
        from .resource_paths import project_root

        doc_path = project_root() / "docs" / "CUSTOM_DRIVER.md"
        if not doc_path.exists():
            QtWidgets.QMessageBox.information(
                self,
                "Documentation",
                "The custom driver guide (docs/CUSTOM_DRIVER.md) was not "
                "found in this installation.\n\n"
                "See the project repository for the full documentation.",
            )
            return

        text = doc_path.read_text(encoding="utf-8")
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Custom Driver Guide")
        dlg.resize(700, 550)
        layout = QtWidgets.QVBoxLayout(dlg)
        viewer = QtWidgets.QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setFont(QtGui.QFont("Courier", 11))
        viewer.setPlainText(text)
        layout.addWidget(viewer)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dlg.exec()

    def _save(self) -> None:
        self._accepted = True
        self.accept()


class PinConfigJsonDialog(QtWidgets.QDialog):
    """Modal dialog for editing the raw pin_config.json."""

    def __init__(
        self,
        config: Dict[str, Any],
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit pin_config.json")
        self.resize(500, 400)
        self._result_config: Optional[Dict[str, Any]] = None

        layout = QtWidgets.QVBoxLayout(self)

        self._editor = QtWidgets.QPlainTextEdit()
        self._editor.setFont(QtGui.QFont("Courier", 11))
        self._editor.setPlainText(json.dumps(config, indent=2))
        layout.addWidget(self._editor)

        self._error_label = QtWidgets.QLabel()
        self._error_label.setStyleSheet("color: red;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _save(self) -> None:
        try:
            self._result_config = json.loads(self._editor.toPlainText())
            self._error_label.setVisible(False)
            self.accept()
        except json.JSONDecodeError as e:
            self._error_label.setText(f"Invalid JSON: {e}")
            self._error_label.setVisible(True)

    def get_json_config(self) -> Optional[Dict[str, Any]]:
        return self._result_config


def _spinbox_max(section: str, key: str) -> int:
    """Return the appropriate spinbox maximum for a given config field."""
    if section == "dfplayer":
        if key == "max_volume":
            return 30
        if key == "uart_baud":
            return 115200
    if key == "bus":
        return 3
    return 999


# Keep old name as an alias so existing imports don't break
PinConfigWidget = PinConfigDialog
