"""Main GUI application for Vintage Radio Music Manager."""
# pyright: reportOptionalMemberAccess=none, reportOptionalCall=none, reportAttributeAccessIssue=none, reportIncompatibleMethodOverride=none

from __future__ import annotations

import json
import os
import platform
import shutil
import time
import subprocess
import sys
import threading
import traceback
import unicodedata
from collections import deque
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, cast

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QFont, QIcon

from .audio_metadata import compute_file_hash, extract_metadata
from .board_profiles import get_board_profile, get_default_board_profile, BOARD_PROFILES_BY_ID
from .database import DatabaseManager
from .device_debug import DeviceDebugWidget
from .library_manager import LibraryRegistry
from .pin_config_editor import BoardSelectorWidget, PinConfigDialog
from .profile_manager import ProfileSelectorBar
from .resource_paths import app_data_dir, project_root, resource_path
from .release_config import ZBVR_FIRMWARE_ENTRY_ID, is_official_firmware_visible
from .sd_manager import SDManager, _get_volume_serial
from .conversion_prefetch import ConversionPrefetchController
from .experimental_sd_image import (
    pyfatfs_dependency_message,
    run_experimental_sd_disk_image_export,
    suggest_image_size_bytes,
    estimate_folder_bytes,
)
from .sd_disk_image_flash import (
    LAST_CACHED_SD_IMAGE_FILENAME,
    darwin_default_bsd_disk_from_volume_path,
    darwin_get_disk_size_bytes,
    format_disk_size,
    is_windows_admin,
    load_cached_sd_image_manifest,
    save_cached_sd_image_manifest,
    windows_disk_number_for_drive_letter,
    windows_drive_letter_from_path,
    windows_get_disk_size_bytes,
    write_image_to_physical_disk,
    write_image_to_physical_disk_darwin,
    DARWIN_FDA_REQUIRED_MARKER,
)
from .widgets.dialogs.sd_disk_image_wizard import SdDiskImageFlashWizardDialog
from .session_log import write_session_line, get_session_log_path
import gui.theme as _theme
from gui import ui_scale as _ui_scale
from gui.theme_presets import apply_ui_theme, normalize_theme_id
from .widgets.common.delegates import (
    StationItemDelegate as _StationItemDelegateNew,
    TrackItemDelegate as _TrackItemDelegateNew,
    configure_track_title_item,
    track_title_text,
    STATION_NUM_ROLE as _STATION_NUM_ROLE_NEW,
    STATION_NAME_ROLE as _STATION_NAME_ROLE_NEW,
    STATION_COUNT_ROLE as _STATION_COUNT_ROLE_NEW,
)
from .widgets.common.mockup_scrollbar import sync_track_table_column_widths
from .widgets.common.vintage_chrome import (
    configure_vintage_app_rendering,
    install_vintage_popup_styles,
)
from .widgets.help.page               import HelpPage as _HelpPage
from .widgets.load_music.page           import LoadMusicPage  as _LoadMusicPage
from .widgets.install_firmware.page     import InstallFirmwarePage as _InstallFirmwarePage
from .widgets.tools.page                import ToolsPage as _ToolsPage
from .widgets.settings.page             import SettingsPage as _SettingsPage
from .widgets.library_bar.library_bar   import LibraryBar     as _LibraryBar
from .widgets.sidebar.sidebar           import Sidebar        as _Sidebar, _NAV_ITEMS as _SIDEBAR_NAV_ITEMS
from .test_mode import TestModeWidget
from .debug_mcp_server import DebugMcpServerManager
from .widgets.dialogs.vintage_message import VintageMessageBox
from .widgets.dialogs.vintage_input import get_item, get_multiline_text, get_text
from .widgets.dialogs.sync.primitives import ModalButton, begin_sync_modal_dialog
from .widgets.common.styled_combo import VintageComboBox
from .widgets.common.styled_checkbox import VintageCheckBox
from .widgets.common.styled_spin import VintageSpinBox
from .widgets.dialogs.vintage_text_dialog import VintageTextDialog
from .widgets.dialogs.task_progress import IndeterminateProgressDialog, TaskProgressDialog, _BackgroundWorker
from .widgets.dialogs.sync import (
    ReplaceConfirmDialog,
    ScrollableListConfirmDialog,
    SyncChoiceDialog,
)
from .widgets.dialogs.sync.primitives import ModalButton, begin_sync_modal_dialog
from . import __version__, sd_manager as sd_manager_module, updater
from .update_dialog import UpdateAvailableDialog

BASIC_MAX_TRACKS_PER_STATION = 255
BASIC_MAX_TRACKS_EXPERIMENTAL = 999

# Advanced Microprocessor button table: merged heading rows serialize as
#   ["__SECTION__", "Heading text"]
ADVANCED_MCU_BTN_SECTION_TAG = "__SECTION__"
_ADVANCED_MCU_BTN_LEGACY_SECTION_FIRST_COL = frozenset(
    {"TAPS", "HOLD (long press, no taps)", "TAP + HOLD"}
)

# Advanced MCU button table: column 0 = gutter handles; 1–2 = gesture / action.
_ADV_MCU_COL_HANDLE = 0
_ADV_MCU_COL_GESTURE = 1
_ADV_MCU_COL_ACTION = 2
_ADV_MCU_JUNCTION_W = 44

# ═══════════════════════════════════════════════════════════════════════════════
# VINTAGE RADIO UI — COLOUR PALETTE
#
# All colours used in the UI are defined here.  Change a constant and every
# widget that references it will update automatically (no hunting through QSS).
#
# Naming:
#   _S_*      → Sidebar elements
#   _C_*      → Content / page area
#   _PANEL_*  → Station/Track panel blocks
#   _TRACK_*  → Track table specific
#   _ORANGE_* / _BAR_* → Accent orange uses
#   _BORDER   → All thin dividers and outlines
#   _TEXT_*   → Text colours
#   _TOP_BAR_BG → Library bar background
# ═══════════════════════════════════════════════════════════════════════════════

_S_BG        = "#3A281C"   # Sidebar background       — Dark Walnut
_S_ACTIVE    = "#D46F1A"   # Sidebar active button    — Primary Accent Orange
_S_TEXT      = "#F3E9D6"   # Sidebar label / icon     — Parchment Cream
_C_BG        = "#FBF6EE"   # Page / content area      — Warm Ivory
_TOP_BAR_BG  = "#F3E9D6"   # Library bar background   — Parchment
_PANEL_DARK  = "#6B5A46"   # Station list rows        — Mocha Taupe
_PANEL_HDR   = "#4A341F"   # Panel header strips      — Cocoa
_STA_ACTIVE  = "#D46F1A"   # Selected station row     — Accent Orange
_TRACK_BG    = "#FBF6EE"   # Track table rows         — Warm Ivory
_TRACK_SEL   = "#FFE6C6"   # Selected track row       — Apricot Highlight
_ORANGE_BTN  = "#D46F1A"   # "Sync to SD" button      — Accent Orange
_BAR_ORANGE  = "#D46F1A"   # Storage bar fill         — Accent Orange
_BORDER      = "#C9A066"   # All dividers / outlines  — Border Bronze
_TEXT_PRI    = "#2C1F14"   # Primary text             — Near-black Brown
_TEXT_SEC    = "#7A6C5A"   # Secondary / dim text     — Mid Taupe


class _AdvancedMcuTableLayoutFilter(QtCore.QObject):
    """Keep the MCU button table width matched to the scroll viewport (resize can skip viewport-only hooks)."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(main)
        self._main = main

    def eventFilter(self, obj: QtCore.QObject, ev: QtCore.QEvent) -> bool:
        scroll = getattr(self._main, "_advanced_mcu_buttons_scroll", None)
        t = getattr(self._main, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(scroll) or not _qt_widget_alive(t):
            return False
        vp = t.viewport()
        if obj not in (vp, scroll):
            return False
        if ev.type() == QtCore.QEvent.Type.Resize:
            self._main._advanced_mcu_table_sync_width_to_scroll()
            return False
        if obj is vp and ev.type() == QtCore.QEvent.Type.Leave:
            self._main._advanced_mcu_set_visible_gutter_row(None)
        return False


class _AdvancedMcuClearTableSelectionFilter(QtCore.QObject):
    """Clear button-table selection when the user presses outside the table/scroll area."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(main)
        self._main = main

    def eventFilter(self, obj: QtCore.QObject, ev: QtCore.QEvent) -> bool:
        if ev.type() != QtCore.QEvent.Type.MouseButtonPress:
            return False
        if not isinstance(ev, QtGui.QMouseEvent):
            return False
        self._main._advanced_mcu_clear_table_selection_if_press_outside(ev.globalPosition().toPoint())
        return False


class _AdvancedMcuRowGutterHandle(QtWidgets.QFrame):
    """Left edge: vertical connector line + circular action control (green hover)."""

    def __init__(
        self,
        on_activate: Callable[[], None],
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setMinimumWidth(_ADV_MCU_JUNCTION_W)
        self.setMaximumWidth(_ADV_MCU_JUNCTION_W)
        self._on_activate = on_activate
        self._junction_visible = False
        self._line_hot = False
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(0)
        lay.addStretch(1)
        self._btn = QtWidgets.QToolButton(self)
        self._btn.setFixedSize(22, 22)
        self._btn.setAutoRaise(True)
        self._btn.setToolTip("Row actions: insert, delete, section heading…")
        self._btn.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_TitleBarMenuButton)
        )
        self._btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._btn.setStyleSheet(
            "QToolButton { border-radius: 11px; border: 1px solid #4a4a52; background-color: #222226; }"
            "QToolButton:hover { border: 2px solid #4CAF50; background-color: #1a2e1a; }"
            "QToolButton:pressed { background-color: #153018; border-color: #6fdc6f; }"
        )
        self._btn.clicked.connect(on_activate)
        self.setMouseTracking(True)
        lay.addWidget(self._btn, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        self.set_junction_visible(False)

    def is_junction_visible(self) -> bool:
        return self._junction_visible

    def set_junction_visible(self, visible: bool) -> None:
        self._junction_visible = bool(visible)
        self._btn.setVisible(self._junction_visible)
        if not self._junction_visible:
            self._line_hot = False
        self.update()

    def mouseMoveEvent(self, ev: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if self._junction_visible:
            self._line_hot = True
            self.update()
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev: QtCore.QEvent) -> None:  # type: ignore[override]
        self._line_hot = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, ev: QtGui.QPaintEvent) -> None:
        super().paintEvent(ev)
        if not self._junction_visible:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        cx = self.width() // 2
        if self._line_hot:
            pen = QtGui.QPen(QtGui.QColor("#4CAF50"))
            pen.setWidth(2)
        else:
            pen = QtGui.QPen(QtGui.QColor("#2d3236"))
            pen.setWidth(1)
        p.setPen(pen)
        p.drawLine(cx, 0, cx, self.height())


def _volume_name_key(name: Optional[str]) -> str:
    """Normalize volume / folder names for comparison (macOS NFD vs NFC, stray spaces)."""
    if not name:
        return ""
    return unicodedata.normalize("NFC", str(name).strip()).upper()


def _qt_widget_alive(widget: Optional[QtCore.QObject]) -> bool:
    """True if *widget* still has a live C++ Qt object (not destroyed).

    After ``_rebuild_tabs()``, widgets from the old central tab tree are deleted;
    Python may still hold references — any call on them raises RuntimeError.
    """
    if widget is None:
        return False
    try:
        widget.metaObject()
    except RuntimeError:
        return False
    return True


class LibraryTable(QtWidgets.QTableWidget):
    files_dropped = QtCore.pyqtSignal(list)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(
            ["Title", "Artist", "Duration", "Format", "Path"]
        )
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.setSortingEnabled(True)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        files: List[Path] = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file():
                files.append(path)
        if files:
            self.files_dropped.emit(files)
        event.acceptProposedAction()


class SettingsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        *,
        auto_backup: bool,
        backup_retention: int,
        sd_root: str,
        sd_auto_detect: bool,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)

        body_lay, footer = begin_sync_modal_dialog(
            self,
            title="Preferences",
            subtitle="Library backup and SD card defaults.",
            min_width=480,
        )

        self.auto_backup_checkbox = VintageCheckBox("Enable automatic backups")
        self.auto_backup_checkbox.setChecked(auto_backup)
        body_lay.addWidget(self.auto_backup_checkbox)

        retention_layout = QtWidgets.QHBoxLayout()
        retention_layout.addWidget(QtWidgets.QLabel("Backup retention (count):"))
        self.retention_spin = VintageSpinBox()
        self.retention_spin.setRange(1, 100)
        self.retention_spin.setValue(backup_retention)
        retention_layout.addWidget(self.retention_spin)
        retention_layout.addStretch(1)
        body_lay.addLayout(retention_layout)

        body_lay.addWidget(QtWidgets.QLabel("SD card root folder:"))
        self.sd_root_edit = QtWidgets.QLineEdit(sd_root)
        self.sd_root_edit.setPlaceholderText("Select SD card root folder")
        self.sd_browse_btn = ModalButton("Browse", variant="secondary")
        self.sd_browse_btn.clicked.connect(self.select_sd_root)
        sd_root_layout = QtWidgets.QHBoxLayout()
        sd_root_layout.addWidget(self.sd_root_edit, 1)
        sd_root_layout.addWidget(self.sd_browse_btn)
        body_lay.addLayout(sd_root_layout)

        self.sd_auto_detect_checkbox = VintageCheckBox(
            "Auto-detect SD card root (Windows)"
        )
        self.sd_auto_detect_checkbox.setChecked(sd_auto_detect)
        body_lay.addWidget(self.sd_auto_detect_checkbox)

        cancel_btn = ModalButton("Cancel", variant="secondary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = ModalButton("OK", variant="primary")
        ok_btn.clicked.connect(self.accept)
        footer.add_button(cancel_btn)
        footer.add_button(ok_btn)

    def select_sd_root(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select SD Card Root",
            str(Path.home()),
        )
        if folder:
            self.sd_root_edit.setText(folder)

    def get_values(self) -> tuple[bool, int, str, bool]:
        return (
            self.auto_backup_checkbox.isChecked(),
            int(self.retention_spin.value()),
            self.sd_root_edit.text().strip(),
            self.sd_auto_detect_checkbox.isChecked(),
        )


class MetadataDialog(QtWidgets.QDialog):
    def __init__(
        self,
        *,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)

        body_lay, footer = begin_sync_modal_dialog(
            self,
            title="Edit Metadata",
            subtitle="Leave fields blank to keep existing values.",
            min_width=420,
        )

        self.title_edit = QtWidgets.QLineEdit()
        self.title_edit.setPlaceholderText("Leave blank to keep existing")
        self.artist_edit = QtWidgets.QLineEdit()
        self.artist_edit.setPlaceholderText("Leave blank to keep existing")
        self.clear_empty_checkbox = VintageCheckBox("Clear fields when empty")

        form = QtWidgets.QFormLayout()
        form.addRow("Title:", self.title_edit)
        form.addRow("Artist:", self.artist_edit)
        body_lay.addLayout(form)
        body_lay.addWidget(self.clear_empty_checkbox)

        cancel_btn = ModalButton("Cancel", variant="secondary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = ModalButton("OK", variant="primary")
        ok_btn.clicked.connect(self.accept)
        footer.add_button(cancel_btn)
        footer.add_button(ok_btn)

    def get_values(self) -> dict:
        title = self.title_edit.text().strip()
        artist = self.artist_edit.text().strip()
        clear_empty = self.clear_empty_checkbox.isChecked()
        fields: dict = {}
        if title:
            fields["title"] = title
        elif clear_empty:
            fields["title"] = ""
        if artist:
            fields["artist"] = artist
        elif clear_empty:
            fields["artist"] = ""
        return fields


def _show_install_error(parent: QtWidgets.QWidget, msg: str, after_firmware: bool) -> None:
    text = f"Error:\n\n{msg}"
    if after_firmware:
        text += "\n\nClick Install Firmware again once the Pico shows up on USB serial."
    VintageMessageBox.warning(parent, "Install to Pico", text)


def _run_install_main_thread(
    parent: QtWidgets.QWidget,
    mpremote_cmd: List[str],
    root: Path,
    sd_root: Optional[str],
    sd_manager: "SDManager",
    after_firmware: bool,
    on_success: Callable[[str], None],
    on_error: Callable[[str], None],
    pin_config_json: str = "",
    custom_hw_driver_path: str = "",
    basic_mode: bool = False,
    install_mode: str = "basic",
    dfplayer_eq: str = "normal",
    preferred_serial_port: Optional[str] = None,
) -> None:
    """Run install on main thread with progress dialog. Status bar updates via processEvents()."""
    title = "Install to Pico (Basic Mode)" if basic_mode else "Install to Pico"
    dlg = IndeterminateProgressDialog(parent, title, "Starting...")
    dlg.show_and_raise()

    def report(step: int, total: int, msg: str):
        dlg.set_progress(step, total, msg)

    try:
        write_session_line(
            f"_run_install_main_thread: basic_mode={basic_mode} after_firmware={after_firmware}",
            prefix="INSTALL",
        )
        worker_class = type(parent)
        result = worker_class._install_to_pico_worker(
            mpremote_cmd, root, sd_root, sd_manager, progress_callback=report,
            pin_config_json=pin_config_json,
            custom_hw_driver_path=custom_hw_driver_path,
            basic_mode=basic_mode,
            install_mode=install_mode,
            dfplayer_eq=dfplayer_eq,
            after_firmware=after_firmware,
            preferred_serial_port=preferred_serial_port,
        )
        dlg.close()
        on_success(result)
    except Exception as e:
        dlg.close()
        write_session_line(
            f"_run_install_main_thread FAILED: {e}\n{traceback.format_exc()}",
            prefix="INSTALL",
        )
        on_error(f"{e}\n\n{traceback.format_exc()}")


def _resolve_system_mpremote_for_worker() -> Optional[List[str]]:
    """Return [python3, -m, mpremote] for use in worker threads (avoids in-process sys.stdout hijacking)."""
    for py in (shutil.which("python3"), shutil.which("python"),
               "/usr/local/bin/python3", "/opt/homebrew/bin/python3", "/usr/bin/python3"):
        if not py or (py.startswith("/") and not Path(py).exists()):
            continue
        try:
            from gui.resource_paths import subprocess_env
            _cwd = os.path.expanduser("~") if getattr(sys, "frozen", False) else None
            r = subprocess.run(
                [py, "-m", "mpremote", "--version"],
                capture_output=True,
                timeout=5,
                cwd=_cwd,
                env=subprocess_env() if getattr(sys, "frozen", False) else None,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if r.returncode == 0:
                return [py, "-m", "mpremote"]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
    return None


def _run_mpremote(
    mpremote_cmd: List[str],
    args: List[str],
    cwd: Optional[str] = None,
    capture_output: bool = True,
    text: bool = True,
    timeout: int = 30,
    creationflags: int = 0,
    env: Optional[dict] = None,
):
    """Run mpremote via subprocess or in-process (when bundled). Returns result with .returncode, .stdout, .stderr."""
    if mpremote_cmd and mpremote_cmd[0] == "__INPROCESS__":
        write_session_line(
            f"mpremote in-process: args={args!r} cwd={cwd!r}",
            prefix="MPREMOTE",
        )
        from io import StringIO

        class _EncodedStringIO(StringIO):
            """StringIO with encoding='utf-8' so mpremote's b.decode(sys.stdout.encoding) works."""

            encoding = "utf-8"

        mpremote_main = mpremote_cmd[1]
        argv = ["mpremote"] + args  # args already include full command (e.g. connect auto exec ...)
        old_argv = sys.argv
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        old_cwd = os.getcwd() if cwd else None
        out = _EncodedStringIO()
        err = _EncodedStringIO()
        try:
            if cwd:
                os.chdir(cwd)
            sys.argv = argv
            sys.stdout = out
            sys.stderr = err
            rc = cast(Callable[[], int], mpremote_cmd[1])()
            write_session_line(
                f"mpremote in-process finished rc={rc} stdout_len={len(out.getvalue())} stderr_len={len(err.getvalue())}",
                prefix="MPREMOTE",
            )
            return type("Result", (), {"returncode": rc, "stdout": out.getvalue(), "stderr": err.getvalue()})()
        except SystemExit as se:
            rc = se.code if isinstance(se.code, int) else (1 if se.code else 0)
            write_session_line(
                f"mpremote in-process raised SystemExit (code={se.code!r}), "
                f"captured as rc={rc} stdout={out.getvalue()[:400]!r} stderr={err.getvalue()[:400]!r}",
                prefix="MPREMOTE",
            )
            return type("Result", (), {"returncode": rc, "stdout": out.getvalue(), "stderr": err.getvalue()})()
        except Exception as e:
            write_session_line(
                f"mpremote in-process exception: {e}\n{traceback.format_exc()}",
                prefix="MPREMOTE",
            )
            raise
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            if old_cwd is not None:
                try:
                    os.chdir(old_cwd)
                except OSError:
                    pass
    # When using system Python (py -m mpremote), avoid cwd inside app bundle so it doesn't load app's mpremote
    run_cwd = cwd
    if run_cwd and getattr(sys, "frozen", False):
        is_mpremote_subproc = (
            len(mpremote_cmd) >= 3
            and mpremote_cmd[1] == "-m"
            and mpremote_cmd[2] == "mpremote"
        ) or (len(mpremote_cmd) >= 2 and mpremote_cmd[1] == "--vr-mpremote")
        if is_mpremote_subproc:
            run_cwd = os.path.expanduser("~")
    if args and args[0] == "connect":
        write_session_line(
            f"mpremote subprocess: cmd={mpremote_cmd!r} args={args!r} cwd={run_cwd!r}",
            prefix="MPREMOTE",
        )
    cf = creationflags
    if cf == 0 and sys.platform == "win32":
        cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        mpremote_cmd + args,
        cwd=run_cwd,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        creationflags=cf,
        env=env,
    )


def _mpremote_failure_is_transient_no_device(result: Any) -> bool:
    if getattr(result, "returncode", 1) == 0:
        return False
    err = ((getattr(result, "stderr", None) or "") + (getattr(result, "stdout", None) or "")).lower()
    return "no device found" in err or "could not open" in err


def _mpremote_failure_is_transient_serial(result: Any) -> bool:
    """True when a retry may help (USB glitch, port contention, REPL not ready yet)."""
    if getattr(result, "returncode", 1) == 0:
        return False
    err = ((getattr(result, "stderr", None) or "") + (getattr(result, "stdout", None) or "")).lower()
    return (
        "no device found" in err
        or "could not open" in err
        or "clearcommerror" in err
        or "permissionerror" in err
        or "does not recognize the command" in err
        or "winerror 22" in err
        or "could not enter raw repl" in err
        or "device reports readiness to read but returned no data" in err
    )


def _list_rp2040_serial_ports() -> List[str]:
    """All connected RP2040/Pico CDC ports, sorted (COM number varies by machine)."""
    try:
        import serial.tools.list_ports as list_ports

        from gui.device_debug import DeviceDebugWidget

        ports: List[str] = []
        for port_info in list_ports.comports():
            if DeviceDebugWidget._is_rp2040_port(port_info):
                dev = getattr(port_info, "device", None) or str(port_info)
                ports.append(dev)
        return sorted(set(ports))
    except Exception:
        return []


def _find_rp2040_serial_port(*, preferred: Optional[str] = None) -> Optional[str]:
    """Best-effort RP2040 CDC port, identified by USB vendor id — not a fixed COM number."""
    ports = _list_rp2040_serial_ports()
    if not ports:
        return None
    if len(ports) == 1:
        return ports[0]
    if preferred:
        pref = preferred.strip()
        for dev in ports:
            if dev == pref or dev.upper() == pref.upper():
                return dev
    return ports[0]


def _read_preferred_serial_port_from_ui(radio_manager: Any) -> Optional[str]:
    """Device-tab COM selection when it points at an RP2040 port."""
    for attr in ("_device_debug_widget", "_basic_debug_widget"):
        widget = getattr(radio_manager, attr, None)
        if widget is None:
            continue
        try:
            port = widget.port_combo.currentData()
            if port:
                return str(port)
        except Exception:
            pass
    return None


def _mpremote_args_with_connect(args: List[str], port: Optional[str]) -> List[str]:
    if not port or (args and args[0] == "connect"):
        return args
    return ["connect", port] + args


def _format_install_mpremote_error(err: str) -> str:
    """Turn mpremote stderr/stdout into actionable install guidance."""
    combined = (err or "").strip()
    lower = combined.lower()
    if _serial_output_indicates_blocking_firmware(combined):
        return (
            "The Pico is running firmware that blocks file transfer "
            "(mpremote cannot use raw REPL).\n\n"
            "Flash stock MicroPython first:\n"
            "  Install Firmware will guide you through BOOTSEL, or use "
            "Tools → MicroPython → Install MicroPython on Pico…\n"
            "Then run Install Firmware again.\n\n"
            f"Technical detail:\n{combined[:1400]}"
        )
    if "clearcommerror" in lower or "does not recognize the command" in lower:
        return (
            "Windows lost access to the COM port during install.\n\n"
            "Try:\n"
            "  1. Disconnect Tools → Debugger if it is connected\n"
            "  2. Close Thonny, serial monitors, or other apps using COM ports\n"
            "  3. Unplug the Pico USB cable, wait 3 seconds, replug\n"
            "  4. Run Install Firmware again (leave Debugger disconnected)\n\n"
            f"Technical detail:\n{combined[:1400]}"
        )
    if "could not enter raw repl" in lower:
        return (
            "mpremote could not enter MicroPython raw REPL (required to copy files).\n\n"
            "Common causes:\n"
            "  • Community / custom UF2 firmware instead of stock MicroPython\n"
            "  • Another program still using the COM port\n"
            "  • Pico in BOOTSEL mode (RPI-RP2 drive) instead of serial mode\n\n"
            "Fix: Tools → MicroPython to flash official MicroPython, then retry Install Firmware.\n\n"
            f"Technical detail:\n{combined[:1400]}"
        )
    return (
        "Failed to copy firmware files.\n\n"
        "Ensure the Pico is connected via USB and running stock MicroPython.\n\n"
        f"{combined}"
    )


# REPL snippet for mpremote ``exec``: must print ``micropython`` so we do not treat a bare
# USB CDC session (or CircuitPython, etc.) as Vintage Radio–compatible MicroPython.
_MPREMOTE_MICROPYTHON_PROBE = (
    "import sys;n=getattr(sys.implementation,'name',None);print(n if n else '')"
)
_MPREMOTE_PROBE_TIMEOUT_S = 22


def _serial_output_indicates_vintage_radio_firmware(text: str) -> bool:
    """True when UART output is from our main_basic / Vintage Radio stack (not ZBVR/Retro Radio)."""
    lower = (text or "").lower()
    vintage_markers = (
        "booting vintage radio",
        "vintage radio main() [basic mode]",
        "basic mode active",
        "basic: discovering stations",
        "basic: seeded",
        "--- dfplayer comms check (basic mode) ---",
        "#vrdbg",
    )
    if any(marker in lower for marker in vintage_markers):
        return True
    # Runtime dfplayer_hardware.py lines (basic mode) — distinct from Retro Radio banners.
    if "df: playing" in lower and "retro radio" not in lower:
        return True
    return False


def _serial_output_indicates_blocking_firmware(text: str) -> Optional[str]:
    """Return a short firmware label when serial output is not stock MicroPython REPL."""
    if _serial_output_indicates_vintage_radio_firmware(text):
        return None
    lower = (text or "").lower()
    if "could not enter raw repl" in lower:
        return "custom firmware (raw REPL blocked)"
    if (
        "retro radio baseline" in lower
        or "booting retro radio" in lower
        or "zbvr" in lower
        or "initiailzing modules" in lower
        or "initializing modules" in lower
    ):
        return "third-party firmware"
    if lower.count("loading module:") >= 2:
        return "third-party firmware"
    idle_markers = (
        "now playing:",
        "dfplayer online",
        "waiting for dfplayer",
        "loading audio data:",
        "discovering playlist",
        "pwm audio:",
        "equalizer setting:",
        "filesystem has ",
        " files in ",
        " folders",
    )
    if sum(1 for marker in idle_markers if marker in lower) >= 2:
        return "third-party firmware"
    return None


def _sniff_rp2040_serial_text(
    port: str,
    *,
    duration_s: float = 3.0,
    interrupt_uart: bool = False,
) -> str:
    """Read recent UART text without mpremote (fast firmware identification)."""
    try:
        import serial
    except ImportError:
        return ""
    try:
        ser = serial.Serial(port, 115200, timeout=0.15)
    except Exception:
        return ""
    try:
        import time

        time.sleep(0.15)
        # Do not reset_input_buffer — keep recent boot banner already in the UART buffer.
        if interrupt_uart:
            try:
                ser.write(b"\x03\x03")
                time.sleep(0.35)
            except Exception:
                pass
        deadline = time.time() + duration_s
        parts: List[str] = []
        while time.time() < deadline:
            try:
                chunk = ser.read(4096)
            except Exception:
                break
            if chunk:
                parts.append(chunk.decode("utf-8", errors="replace"))
        return "".join(parts)
    finally:
        try:
            if ser.is_open:
                ser.close()
        except Exception:
            pass


def _run_mpremote_probe(
    mpremote_cmd: List[str],
    port: str,
    cwd: str,
    *,
    timeout_sec: int = _MPREMOTE_PROBE_TIMEOUT_S,
) -> Any:
    """Run MicroPython probe on *port* ('auto' allowed); never raise TimeoutExpired to callers."""
    if port == "auto":
        args = ["connect", "auto", "exec", _MPREMOTE_MICROPYTHON_PROBE]
    else:
        args = ["connect", port, "exec", _MPREMOTE_MICROPYTHON_PROBE]
    try:
        return _run_mpremote(
            mpremote_cmd,
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        partial = ""
        if exc.stdout:
            partial = exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", errors="replace")
        if exc.stderr:
            err = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace")
            partial += err
        return type(
            "Result",
            (),
            {"returncode": 124, "stdout": partial, "stderr": "mpremote probe timed out"},
        )()


def _setup_device_failure_message(
    *,
    probe_outputs: List[str],
    timed_out: bool,
) -> str:
    combined = "\n".join(probe_outputs)
    blocking = _serial_output_indicates_blocking_firmware(combined)
    if blocking:
        return (
            f"The Pico on USB serial is running {blocking}, not stock MicroPython.\n\n"
            "That firmware is built on MicroPython but blocks the file-transfer mode "
            "Vintage Radio uses to install (mpremote raw REPL). Having “MicroPython” "
            "on the board is not enough — it must be the official MicroPython UF2.\n\n"
            "To install Vintage Radio:\n"
            "1. Hold BOOTSEL and plug in USB (RPI-RP2 drive appears).\n"
            "2. Tools → MicroPython → flash the official MicroPython .uf2 "
            "(this replaces the current firmware).\n"
            "3. After reboot, run Install Firmware again.\n\n"
            "Close Tools → Debugger and other serial apps before step 3."
        )
    if timed_out:
        return (
            "The Pico answered on USB serial but did not reach MicroPython raw REPL in time.\n\n"
            "Common causes:\n"
            "  • Community or custom UF2 firmware that blocks mpremote\n"
            "  • Another program holding the COM port\n"
            "  • Long boot / playback keeping the port busy\n\n"
            "Try: disconnect Debugger, flash stock MicroPython (Tools → MicroPython), "
            "then Install Firmware again."
        )
    return (
        "A Raspberry Pi Pico USB serial port was found, but stock MicroPython did not respond.\n\n"
        "On a new or erased board you must install MicroPython before Vintage Radio can "
        "copy firmware.\n\n"
        "1. Hold BOOTSEL and plug the Pico into USB (RPI-RP2 drive).\n"
        "2. Tools → MicroPython → copy the official .uf2 file.\n"
        "3. When the Pico reboots, run Install Firmware again.\n\n"
        "If MicroPython is already installed, close other apps using the serial port and retry."
    )


def _pico_install_assessment(
    mpremote_cmd: Optional[List[Any]],
    root: Path,
    *,
    preferred_port: Optional[str] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Classify Pico USB state for Vintage Radio mpremote install."""
    def _progress(msg: str) -> None:
        if progress_callback:
            progress_callback(0, 0, msg)

    if not mpremote_cmd:
        return {"status": "no_mpremote"}

    port = _find_rp2040_serial_port(preferred=preferred_port)
    if not port:
        _progress("No Pico serial port found — checking for BOOTSEL (RPI-RP2)…")
        try:
            from gui.sd_manager import SDManager

            for path, label in SDManager.detect_sd_roots():
                if label and label.strip().upper() == "RPI-RP2":
                    return {"status": "bootsel", "port": None, "bootsel_path": str(path)}
        except Exception:
            pass
        return {"status": "no_pico", "port": None}

    _progress(f"Reading firmware output on {port}…")
    sniff = _sniff_rp2040_serial_text(port)
    blocking = _serial_output_indicates_blocking_firmware(sniff)
    if not blocking and len(sniff.strip()) < 80:
        sniff = sniff + _sniff_rp2040_serial_text(
            port, duration_s=2.5, interrupt_uart=True,
        )
        blocking = _serial_output_indicates_blocking_firmware(sniff)
    if blocking:
        _progress(f"Detected {blocking} on {port} — MicroPython flash required.")
        return {
            "status": "needs_reflash",
            "port": port,
            "blocking_label": blocking,
            "sniff": sniff,
        }

    if _serial_output_indicates_vintage_radio_firmware(sniff):
        _progress(
            f"Vintage Radio firmware detected on {port} — preparing file update…"
        )
    elif _sniff_suggests_stock_micropython_repl(sniff):
        _progress(
            f"Testing MicroPython file transfer on {port} "
            f"(up to {_MPREMOTE_PROBE_TIMEOUT_S}s)…"
        )
    elif _sniff_suggests_app_firmware(sniff):
        label = _serial_output_indicates_blocking_firmware(sniff) or "third-party firmware"
        _progress(f"Detected {label} on {port} — MicroPython flash required.")
        return {
            "status": "needs_reflash",
            "port": port,
            "blocking_label": label,
            "sniff": sniff,
        }
    else:
        _progress(
            f"Testing MicroPython file transfer on {port} "
            f"(up to {_MPREMOTE_PROBE_TIMEOUT_S}s)…"
        )

    probe = _run_mpremote_probe(mpremote_cmd, port, str(root))
    probe_out = ((probe.stdout or "") + (probe.stderr or "")).strip()
    if _mpremote_result_indicates_micropython(probe):
        repl = _run_mpremote(
            mpremote_cmd,
            _mpremote_args_with_connect(
                ["exec", "import os; print('VR_INSTALL_PROBE', len(os.listdir()))"],
                port,
            ),
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=_MPREMOTE_PROBE_TIMEOUT_S,
        )
        repl_out = (repl.stdout or "") + (repl.stderr or "")
        if repl.returncode == 0 and "VR_INSTALL_PROBE" in repl_out:
            return {"status": "ready", "port": port}

    if _serial_output_indicates_blocking_firmware(probe_out):
        return {
            "status": "needs_reflash",
            "port": port,
            "blocking_label": _serial_output_indicates_blocking_firmware(probe_out),
            "sniff": probe_out,
        }
    return {
        "status": "needs_reflash",
        "port": port,
        "blocking_label": None,
        "sniff": probe_out or sniff,
    }


def _sniff_suggests_stock_micropython_repl(text: str) -> bool:
    """True when UART text looks like an idle official MicroPython REPL."""
    lower = (text or "").lower()
    if "micropython v1" in lower:
        return True
    if "\n>>> " in lower or lower.rstrip().endswith(">>>"):
        return True
    return False


def _sniff_suggests_app_firmware(text: str) -> bool:
    """True when UART shows a running app, not an idle MicroPython REPL."""
    if not text or len(text.strip()) < 20:
        return False
    if _serial_output_indicates_vintage_radio_firmware(text):
        return False
    if _sniff_suggests_stock_micropython_repl(text):
        return False
    if _serial_output_indicates_blocking_firmware(text):
        return True
    lower = text.lower()
    return ">>>" not in lower and "micropython v1" not in lower


def _mpremote_result_indicates_micropython(result: Any) -> bool:
    """True if mpremote exited OK and device output identifies MicroPython on the REPL."""
    if getattr(result, "returncode", 1) != 0:
        return False
    combined = ((getattr(result, "stdout", None) or "") + (getattr(result, "stderr", None) or "")).lower()
    return "micropython" in combined


def _post_flash_serial_timeout_message(port: Optional[str] = None) -> str:
    """Actionable error when MicroPython does not answer after a UF2 flash."""
    base = (
        "Timed out waiting for the Pico on USB serial after installing MicroPython.\n\n"
        "The board often disconnects and reappears as a new COM port; on some PCs that "
        "takes 15–30 seconds."
    )
    if port:
        sniff = _sniff_rp2040_serial_text(port, duration_s=2.0)
        blocking = _serial_output_indicates_blocking_firmware(sniff)
        if blocking:
            return (
                f"{base}\n\n"
                f"Serial output on {port} still looks like {blocking}, not stock MicroPython. "
                "The MicroPython .uf2 may not have flashed correctly.\n\n"
                "Put the Pico in BOOTSEL mode (RPI-RP2 drive) and run Install Firmware again."
            )
        if sniff.strip():
            write_session_line(
                f"Post-flash timeout serial ({port}): {sniff[:400]!r}",
                prefix="INSTALL",
            )
    return (
        f"{base}\n\n"
        "Try unplugging the Pico USB cable, wait 3 seconds, replug, then run Install Firmware again. "
        "Close Tools → Debugger and other apps that might use the COM port."
    )


def _is_authentic_rp2040_bootsel_volume(path: Path) -> Tuple[bool, str]:
    """True when *path* looks like the ROM UF2 bootloader (not an emulated MSC share)."""
    info = path / "INFO_UF2.TXT"
    if info.is_file():
        try:
            text = info.read_text(encoding="utf-8", errors="replace").lower()
        except OSError as exc:
            return False, f"Could not read INFO_UF2.TXT on {path}: {exc}"
        if "raspberry pi" in text or "rp2" in text or "uf2 bootloader" in text:
            return True, ""
        return False, (
            f"{path} has INFO_UF2.TXT but it does not look like a Pico BOOTSEL volume."
        )
    index = path / "INDEX.HTM"
    if index.is_file():
        return True, ""
    return False, (
        f"{path} is missing INFO_UF2.TXT — it may not be a Pico in BOOTSEL mode.\n"
        "Hold BOOTSEL while plugging in USB (or hold BOOTSEL and tap RESET)."
    )


def _bootsel_serial_blocking_message(port: str) -> str:
    return (
        f"The Pico still appears on USB serial ({port}) while RPI-RP2 is visible.\n\n"
        "In true BOOTSEL mode the COM port must disappear — only the RPI-RP2 drive "
        "should show. Some third-party firmware emulates an RPI-RP2 drive while still "
        "running on serial; copying a .uf2 there does not replace flash.\n\n"
        "Unplug USB, hold BOOTSEL, plug USB back in while still holding BOOTSEL, "
        "then release BOOTSEL once RPI-RP2 appears."
    )


def _wait_for_serial_port_gone(
    *,
    preferred_port: Optional[str] = None,
    timeout_s: float = 8.0,
    poll_s: float = 0.35,
) -> bool:
    """Wait until no RP2040 CDC port is listed (required before UF2 copy)."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _find_rp2040_serial_port(preferred=preferred_port) is None:
            return True
        time.sleep(poll_s)
    return _find_rp2040_serial_port(preferred=preferred_port) is None


def _wait_for_bootsel_polling(
    progress_callback: Optional[Callable[..., Any]],
    *,
    intro: str,
    timeout_s: float = 180.0,
    is_present: Callable[[], bool],
    preferred_serial_port: Optional[str] = None,
) -> bool:
    """Poll until RPI-RP2 appears and USB serial is gone (safe from a worker thread)."""
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        remaining = max(0, int(deadline - time.time()))
        bootsel = is_present()
        port = _find_rp2040_serial_port(preferred=preferred_serial_port)
        if progress_callback:
            if bootsel and port:
                progress_callback(
                    0,
                    0,
                    f"{intro}\n\n"
                    f"RPI-RP2 is visible but USB serial ({port}) is still active.\n\n"
                    "The COM port must disappear before flash can proceed.\n\n"
                    f"Unplug USB, hold BOOTSEL, plug back in while holding BOOTSEL… "
                    f"({remaining}s remaining)",
                )
            elif bootsel:
                progress_callback(
                    0,
                    0,
                    f"{intro}\n\n"
                    f"RPI-RP2 detected and USB serial is off — ready to flash. "
                    f"({remaining}s remaining)",
                )
            else:
                progress_callback(
                    0,
                    0,
                    f"{intro}\n\nWaiting for RPI-RP2 drive… ({remaining}s remaining)\n\n"
                    "Unplug USB, hold BOOTSEL, plug back in while holding BOOTSEL, "
                    "or hold BOOTSEL and tap RESET.",
                )
        if bootsel and port is None:
            if _wait_for_serial_port_gone(
                preferred_port=preferred_serial_port,
                timeout_s=2.0,
            ):
                return True
        time.sleep(0.4)
    return False


def _wait_for_bootsel_volume_gone(
    *,
    timeout_s: float = 45.0,
    progress_callback: Optional[Callable[..., Any]] = None,
) -> bool:
    """After a UF2 copy the RPI-RP2 volume should disappear as the Pico reboots."""
    import time

    from gui.sd_manager import SDManager

    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if not SDManager.is_rp2040_bootsel_present():
            return True
        if progress_callback:
            progress_callback(0, 0, "Waiting for Pico to reboot after UF2 flash…")
        time.sleep(0.5)
    return False


def _copy_uf2_to_rpi_rp2(
    uf2_path: Path,
    dest_dir: Path,
    *,
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Tuple[bool, str]:
    """Copy a .uf2 to RPI-RP2 (same mechanism as drag-and-drop in Explorer)."""
    authentic, auth_detail = _is_authentic_rp2040_bootsel_volume(dest_dir)
    if not authentic:
        return False, auth_detail

    dest_file = dest_dir / uf2_path.name
    src_size = uf2_path.stat().st_size
    write_session_line(
        f"Copying UF2 {uf2_path.name} ({src_size} bytes) → {dest_file} (RPI-RP2 at {dest_dir})",
        prefix="INSTALL",
    )
    if progress_callback:
        progress_callback(0, 0, f"Copying {uf2_path.name} to RPI-RP2 ({dest_dir})…")
    try:
        with uf2_path.open("rb") as src_f:
            with dest_file.open("wb") as dest_f:
                shutil.copyfileobj(src_f, dest_f, length=1024 * 1024)
                dest_f.flush()
                os.fsync(dest_f.fileno())
    except OSError as exc:
        return False, f"Could not copy .uf2 to {dest_dir}: {exc}"
    try:
        copied_size = dest_file.stat().st_size
    except OSError as exc:
        return False, f"Could not verify .uf2 on {dest_dir}: {exc}"
    if copied_size != src_size:
        return False, (
            f"UF2 copy size mismatch on {dest_dir}: expected {src_size} bytes, "
            f"got {copied_size}."
        )
    try:
        with dest_file.open("rb") as verify_f:
            header = verify_f.read(32)
        if len(header) >= 8 and header[0:4] not in (b"UF2\n", b"\x00UF2"):
            write_session_line(
                f"UF2 header warning on {dest_file}: {header[:8]!r}",
                prefix="INSTALL",
            )
    except OSError:
        pass
    if not _wait_for_bootsel_volume_gone(progress_callback=progress_callback):
        return False, (
            "The RPI-RP2 drive is still present after copying the .uf2 — the Pico may "
            "not have accepted the flash.\n\n"
            "Ensure the COM port disappeared before copying. Unplug USB, hold BOOTSEL, "
            "plug back in while holding BOOTSEL, then try drag-and-drop in File Explorer."
        )
    write_session_line("RPI-RP2 drive disappeared after UF2 copy (Pico rebooted)", prefix="INSTALL")
    return True, ""


def _find_picotool_executable() -> Optional[Path]:
    """Locate picotool (bundled workshop copy or PATH)."""
    for candidate in (
        project_root() / "agent_workshop" / "tools" / "picotool" / "picotool.exe",
        project_root() / "agent_workshop" / "tools" / "picotool.exe",
        Path(shutil.which("picotool") or ""),
    ):
        if candidate.is_file():
            return candidate
    return None


def _run_picotool(args: List[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    exe = _find_picotool_executable()
    if exe is None:
        raise RuntimeError("picotool not found")
    cmd = [str(exe)] + list(args)
    write_session_line(f"picotool: {' '.join(cmd)}", prefix="INSTALL")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def _flash_uf2_file(
    uf2_path: Path,
    dest_dir: Path,
    *,
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Tuple[bool, str]:
    """Flash a UF2 via picotool load when available, else RPI-RP2 drag-and-drop copy."""
    if _find_picotool_executable() is not None:
        if progress_callback:
            progress_callback(0, 0, f"Flashing {uf2_path.name} via picotool…")
        try:
            result = _run_picotool(["load", "-f", str(uf2_path)])
        except (subprocess.TimeoutExpired, OSError) as exc:
            write_session_line(f"picotool load failed: {exc}", prefix="INSTALL")
        else:
            if result.returncode == 0:
                write_session_line(f"picotool load OK: {uf2_path.name}", prefix="INSTALL")
                return True, ""
            write_session_line(
                f"picotool load rc={result.returncode}: "
                f"{(result.stderr or result.stdout or '').strip()[:400]}",
                prefix="INSTALL",
            )
    return _copy_uf2_to_rpi_rp2(uf2_path, dest_dir, progress_callback=progress_callback)


def _factory_erase_rp2040_flash(
    dest_dir: Path,
    *,
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Tuple[bool, str, str]:
    """Erase all RP2040 flash. Returns (ok, error, method) where method is picotool|nuke|."""
    if _find_picotool_executable() is not None:
        if progress_callback:
            progress_callback(0, 0, "Factory reset: erasing all flash (picotool)…")
        try:
            result = _run_picotool(["erase", "-a", "-f"])
        except (subprocess.TimeoutExpired, OSError) as exc:
            write_session_line(f"picotool erase failed: {exc}", prefix="INSTALL")
        else:
            if result.returncode == 0:
                write_session_line("picotool erase -a succeeded", prefix="INSTALL")
                return True, "", "picotool"
            write_session_line(
                f"picotool erase rc={result.returncode}: "
                f"{(result.stderr or result.stdout or '').strip()[:400]}",
                prefix="INSTALL",
            )

    from gui.services.firmware_bundle import fetch_flash_nuke_uf2

    if progress_callback:
        progress_callback(0, 0, "Factory reset: downloading flash_nuke.uf2…")
    try:
        nuke_path = fetch_flash_nuke_uf2()
    except Exception as exc:
        return False, f"Could not download flash_nuke.uf2: {exc}", ""
    if progress_callback:
        progress_callback(0, 0, "Factory reset: erasing all flash (flash_nuke.uf2)…")
    write_session_line(f"Factory erase via flash_nuke: {nuke_path.name}", prefix="INSTALL")
    ok, err = _copy_uf2_to_rpi_rp2(nuke_path, dest_dir, progress_callback=progress_callback)
    return ok, err, "nuke" if ok else ""


def _verify_stock_micropython_serial(
    preferred_port: Optional[str] = None,
    *,
    timeout_s: float = 50.0,
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Optional[str]:
    """Wait for stock MicroPython on USB serial. Returns None on success, else error text."""
    import time

    if progress_callback:
        progress_callback(0, 0, "Verifying MicroPython booted on USB serial…")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        port = _find_rp2040_serial_port(preferred=preferred_port)
        if port:
            sniff = _sniff_rp2040_serial_text(port, duration_s=2.0)
            if _sniff_suggests_stock_micropython_repl(sniff):
                write_session_line(f"Verified stock MicroPython on {port}", prefix="INSTALL")
                return None
            blocking = _serial_output_indicates_blocking_firmware(sniff)
            if blocking:
                write_session_line(
                    f"Verify: {port} still shows {blocking}: {sniff[:200]!r}",
                    prefix="INSTALL",
                )
                return f"still running {blocking}"
            if _sniff_suggests_app_firmware(sniff):
                write_session_line(
                    f"Verify: {port} still shows app firmware: {sniff[:200]!r}",
                    prefix="INSTALL",
                )
                return "still running third-party firmware"
        if progress_callback:
            progress_callback(
                0,
                0,
                "Waiting for MicroPython on USB serial after flash…",
            )
        time.sleep(2.0)
    return "timed out waiting for stock MicroPython on USB serial"


_FACTORY_RESET_BOOTSEL_INTRO = (
    "The first MicroPython flash did not replace the previous firmware.\n\n"
    "Factory reset will erase all flash. Unplug all power from the device, "
    "hold BOOTSEL, plug USB while still holding BOOTSEL, then release once "
    "only RPI-RP2 appears and the COM port is gone."
)


def _wait_mpremote_serial_ready(
    mpremote_cmd: List[str],
    cwd: Optional[str],
    *,
    progress_callback: Optional[Callable[..., Any]],
    total_steps: int,
    creationflags: int = 0,
    env: Optional[dict] = None,
    deadline_s: Optional[float] = None,
    poll_s: float = 2.0,
    after_uf2_flash: bool = False,
    preferred_port: Optional[str] = None,
) -> Optional[str]:
    """Poll until MicroPython answers on USB serial.

    Returns None on success, or an error message string on failure.
    """
    import time

    if deadline_s is None:
        deadline_s = 120.0 if after_uf2_flash else 78.0
    if after_uf2_flash:
        poll_s = max(poll_s, 2.5)
        if progress_callback:
            progress_callback(
                0,
                max(1, total_steps),
                "Waiting for Pico to reboot after MicroPython flash…",
            )
        time.sleep(8.0)

    t0 = time.monotonic()
    last_port: Optional[str] = None
    last_blocking_label: Optional[str] = None

    while time.monotonic() - t0 < deadline_s:
        elapsed = int(time.monotonic() - t0)
        port = _find_rp2040_serial_port(preferred=preferred_port)
        if progress_callback:
            port_hint = port or "waiting for COM port…"
            progress_callback(
                0,
                max(1, total_steps),
                f"Waiting for MicroPython on {port_hint} "
                f"(elapsed {elapsed}s, timeout {int(deadline_s)}s). "
                "The Pico may disconnect briefly after flashing.",
            )

        if port != last_port and port:
            write_session_line(f"RP2040 serial port: {port}", prefix="INSTALL")
            last_port = port

        if port and after_uf2_flash and elapsed >= 6:
            sniff = _sniff_rp2040_serial_text(port, duration_s=1.2)
            blocking = _serial_output_indicates_blocking_firmware(sniff)
            if blocking:
                last_blocking_label = blocking
                write_session_line(
                    f"Post-flash serial still shows {blocking} on {port}",
                    prefix="INSTALL",
                )

        if port:
            probe_timeout = 20 if after_uf2_flash else 14
            r = _run_mpremote(
                mpremote_cmd,
                _mpremote_args_with_connect(
                    ["exec", _MPREMOTE_MICROPYTHON_PROBE],
                    port,
                ),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=probe_timeout,
                creationflags=creationflags,
                env=env,
            )
            probe_out = ((r.stdout or "") + (r.stderr or "")).strip()
            if _mpremote_result_indicates_micropython(r):
                write_session_line(f"MicroPython ready on {port}", prefix="INSTALL")
                return None
            blocking = _serial_output_indicates_blocking_firmware(probe_out)
            if blocking:
                last_blocking_label = blocking
                write_session_line(
                    f"mpremote probe on {port} rc={r.returncode}: still {blocking}",
                    prefix="INSTALL",
                )
                if after_uf2_flash:
                    return (
                        f"After installing MicroPython, the Pico on {port} is still running "
                        f"{blocking}.\n\n"
                        "The .uf2 flash did not replace the previous firmware. This usually "
                        "means the Pico was not in true BOOTSEL mode (ROM bootloader).\n\n"
                        "Unplug USB completely. Hold BOOTSEL, plug USB back in while still "
                        "holding BOOTSEL, then release once only the RPI-RP2 drive appears "
                        "and the COM port is gone. Run Install Firmware again, or drag the "
                        "MicroPython .uf2 into RPI-RP2 manually in File Explorer."
                    )
            elif probe_out and (elapsed % 12 < poll_s + 0.5):
                write_session_line(
                    f"mpremote probe on {port} rc={r.returncode}: {probe_out[:240]}",
                    prefix="INSTALL",
                )
            elif after_uf2_flash and last_blocking_label and elapsed >= 20:
                return (
                    f"After installing MicroPython, the Pico on {port} is still running "
                    f"{last_blocking_label}.\n\n"
                    "The .uf2 flash did not replace the previous firmware. Use BOOTSEL (RPI-RP2) "
                    "and copy the MicroPython .uf2 manually, then run Install Firmware again."
                )

        time.sleep(poll_s)

    if last_blocking_label:
        port_hint = last_port or "USB serial"
        return (
            f"Timed out: {port_hint} still shows {last_blocking_label} after MicroPython flash.\n\n"
            "The UF2 did not replace the previous firmware. Use BOOTSEL (RPI-RP2 drive) and "
            "copy the MicroPython .uf2 manually, then run Install Firmware again."
        )
    return _post_flash_serial_timeout_message(last_port)


def _run_mpremote_connect_auto_with_retry(
    mpremote_cmd: List[str],
    subargs: List[str],
    *,
    cwd: Optional[str] = None,
    timeout: int = 30,
    creationflags: int = 0,
    env: Optional[dict] = None,
    max_attempts: int = 6,
) -> Any:
    """Run ``mpremote connect auto <subargs>`` with backoff while the OS is still enumerating USB serial."""
    import time

    args = ["connect", "auto"] + list(subargs)
    last: Any = None
    for attempt in range(max_attempts):
        if attempt:
            time.sleep(min(8.0, 1.5 * (attempt + 1)))
        last = _run_mpremote(
            mpremote_cmd,
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
            env=env,
        )
        if last.returncode == 0:
            return last
        if not _mpremote_failure_is_transient_no_device(last):
            return last
    return last


# After copying a .uf2, Windows/macOS often need several seconds before the new CDC port appears.
_POST_MICROPYTHON_INSTALL_DELAY_MS = 8000


_TABLE_REORDER_MIME = "application/x-vintage-radio-table-reorder"


class ReorderTable(QtWidgets.QTableWidget):
    """QTableWidget with drag-to-reorder. Uses fully custom drag/drop so Qt
    never performs InternalMove (which nukes rows on macOS).

    Reorder is tracked by *row index* (not song id) so duplicate song ids
    are handled correctly.
    """
    order_changed = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(QtCore.Qt.DropAction.CopyAction)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSortingEnabled(False)
        self._pending_order: Optional[List[int]] = None
        self._drop_indicator_row: int = -1

    # -- snapshot helpers --------------------------------------------------

    def _snapshot_all(self) -> List[tuple]:
        """Return [(row, song_id, [col_texts], extra_data), ...] for every row.
        extra_data preserves any UserRole+1 data stored on the first column item."""
        result: List[tuple] = []
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is None:
                continue
            song_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if song_id is None:
                continue
            extra = item.data(QtCore.Qt.ItemDataRole.UserRole + 1)
            cols = []
            for c in range(self.columnCount()):
                it = self.item(row, c)
                if c == 0:
                    cols.append(track_title_text(it))
                else:
                    cols.append(it.text() if it is not None else "")
            result.append((row, int(song_id), cols, extra))
        return result

    def _rebuild_from_snapshot(self, ordered_snap: List[tuple]) -> None:
        """Replace table contents from an ordered list of snapshot tuples."""
        self.setSortingEnabled(False)
        self.blockSignals(True)
        try:
            self.setRowCount(len(ordered_snap))
            for new_row, (_, sid, cols, extra) in enumerate(ordered_snap):
                artist = cols[1] if len(cols) > 1 else ""
                for c, text in enumerate(cols):
                    if c == 0:
                        item = QtWidgets.QTableWidgetItem()
                        configure_track_title_item(item, text, artist=artist)
                    else:
                        item = QtWidgets.QTableWidgetItem(text)
                    if c == 0:
                        item.setData(QtCore.Qt.ItemDataRole.UserRole, sid)
                        if extra is not None:
                            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, extra)
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                    self.setItem(new_row, c, item)
        finally:
            self.blockSignals(False)
            # Preserve track order — sorting would reorder rows and break SD sync.

    # -- drop indicator painting -------------------------------------------

    def _row_at_pos(self, pos: QtCore.QPoint) -> int:
        """Return the row index for the drop indicator, clamped to [0, rowCount]."""
        idx = self.indexAt(self.viewport().mapFrom(self, pos))
        if idx.isValid():
            rect = self.visualRect(idx)
            if pos.y() > rect.center().y():
                return idx.row() + 1
            return idx.row()
        return self.rowCount()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._drop_indicator_row < 0:
            return
        painter = QtGui.QPainter(self.viewport())
        pen = QtGui.QPen(QtGui.QColor("#4CAF50"), 2)
        painter.setPen(pen)
        row = self._drop_indicator_row
        if row < self.rowCount():
            rect = self.visualRect(self.model().index(row, 0))
            y = rect.top()
        else:
            if self.rowCount() > 0:
                rect = self.visualRect(self.model().index(self.rowCount() - 1, 0))
                y = rect.bottom()
            else:
                y = 0
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()

    # -- accept our custom mime during drag-over ----------------------------

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(_TABLE_REORDER_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(_TABLE_REORDER_MIME):
            event.acceptProposedAction()
            new_row = self._row_at_pos(event.position().toPoint())
            if new_row != self._drop_indicator_row:
                self._drop_indicator_row = new_row
                self.viewport().update()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._drop_indicator_row = -1
        self.viewport().update()
        super().dragLeaveEvent(event)

    # -- drag (encode row indices, not song ids) ---------------------------

    def startDrag(self, supportedActions: QtCore.Qt.DropActions) -> None:
        rows = sorted(set(idx.row() for idx in self.selectedIndexes()))
        if not rows:
            return
        mime = QtCore.QMimeData()
        mime.setData(_TABLE_REORDER_MIME,
                     ",".join(str(r) for r in rows).encode("utf-8"))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.exec(QtCore.Qt.DropAction.CopyAction)

    # -- drop (use row indices) --------------------------------------------

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        self._drop_indicator_row = -1
        self.viewport().update()

        if event.source() is not self or not event.mimeData().hasFormat(_TABLE_REORDER_MIME):
            super().dropEvent(event)
            return

        data = event.mimeData().data(_TABLE_REORDER_MIME)
        raw = bytes(cast(Any, data)).decode("utf-8")
        try:
            moving_rows = sorted(int(x.strip()) for x in raw.split(",") if x.strip())
        except ValueError:
            event.ignore()
            return
        if not moving_rows:
            event.ignore()
            return

        snap = self._snapshot_all()
        total = len(snap)
        moving_set = set(moving_rows)

        target_row = self._row_at_pos(event.position().toPoint())

        moving_items = [snap[r] for r in moving_rows if r < total]
        staying_items = [snap[r] for r in range(total) if r not in moving_set]

        # Adjust insertion index: count how many staying rows are above the drop
        above = sum(1 for r in range(total) if r < target_row and r not in moving_set)
        insert_at = max(0, min(above, len(staying_items)))

        ordered = staying_items[:insert_at] + moving_items + staying_items[insert_at:]
        self._pending_order = [entry[1] for entry in ordered]
        self._rebuild_from_snapshot(ordered)

        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()
        QtCore.QTimer.singleShot(0, self.order_changed.emit)


class CollectionDropTable(ReorderTable):
    files_dropped = QtCore.pyqtSignal(list)
    edit_track_requested = QtCore.pyqtSignal(int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def _pencil_hit(self, pos: QtCore.QPoint) -> Optional[int]:
        from gui.widgets.common.delegates import track_pencil_hit_rect

        idx = self.indexAt(pos)
        if not idx.isValid():
            return None
        rect = self.visualRect(idx)
        if track_pencil_hit_rect(rect).contains(pos):
            return idx.row()
        return None

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._pencil_hit(pos) is not None:
            self.viewport().setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self.viewport().unsetCursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            row = self._pencil_hit(pos)
            if row is not None:
                self.selectRow(row)
                self.edit_track_requested.emit(row)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths: List[Path] = []
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.is_dir():
                    paths.extend([p for p in path.rglob("*") if p.is_file()])
                elif path.is_file():
                    paths.append(path)
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


_REORDER_MIME = "application/x-vintage-radio-list-reorder"


class ReorderListWidget(QtWidgets.QListWidget):
    """A QListWidget that supports drag-and-drop reordering. Uses custom drag/drop
    so Qt never modifies the model (avoids InternalMove nuking items on macOS).
    """

    order_changed = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(QtCore.Qt.DropAction.CopyAction)
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self._drop_indicator_row: int = -1

    def _row_at_pos(self, pos: QtCore.QPoint) -> int:
        idx = self.indexAt(self.viewport().mapFrom(self, pos))
        if idx.isValid():
            rect = self.visualRect(idx)
            if pos.y() > rect.center().y():
                return idx.row() + 1
            return idx.row()
        return self.count()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._drop_indicator_row < 0:
            return
        painter = QtGui.QPainter(self.viewport())
        pen = QtGui.QPen(QtGui.QColor("#4CAF50"), 2)
        painter.setPen(pen)
        row = self._drop_indicator_row
        if row < self.count():
            rect = self.visualRect(self.model().index(row, 0))
            y = rect.top()
        else:
            if self.count() > 0:
                rect = self.visualRect(self.model().index(self.count() - 1, 0))
                y = rect.bottom()
            else:
                y = 0
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(_REORDER_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(_REORDER_MIME):
            event.acceptProposedAction()
            new_row = self._row_at_pos(event.position().toPoint())
            if new_row != self._drop_indicator_row:
                self._drop_indicator_row = new_row
                self.viewport().update()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._drop_indicator_row = -1
        self.viewport().update()
        super().dragLeaveEvent(event)

    def startDrag(self, supportedActions: QtCore.Qt.DropActions) -> None:
        """Start drag with our mime data (UIDs only). We do not call super() so Qt
        never performs InternalMove or removes any rows.
        """
        rows = sorted(set(idx.row() for idx in self.selectedIndexes()))
        uids: List[int] = []
        for row in rows:
            it = self.item(row)
            if it is None:
                continue
            uid = it.data(QtCore.Qt.ItemDataRole.UserRole)
            if uid is not None:
                uids.append(int(uid))
        if not uids:
            return
        mime = QtCore.QMimeData()
        mime.setData(_REORDER_MIME, ",".join(str(u) for u in uids).encode("utf-8"))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.exec(QtCore.Qt.DropAction.CopyAction)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        self._drop_indicator_row = -1
        self.viewport().update()

        if event.source() is not self:
            super().dropEvent(event)
            return
        if not event.mimeData().hasFormat(_REORDER_MIME):
            event.ignore()
            return

        data = event.mimeData().data(_REORDER_MIME)
        raw = bytes(cast(Any, data)).decode("utf-8")
        try:
            moving = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            event.ignore()
            return
        if not moving:
            event.ignore()
            return

        all_ids: List[tuple] = []
        for row in range(self.count()):
            item = self.item(row)
            if item is None:
                continue
            uid = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if uid is None:
                continue
            all_ids.append((row, int(uid), item.text(), item))
        current_uids = [uid for (_, uid, _, _) in all_ids]
        staying = [u for u in current_uids if u not in moving]
        if len(staying) + len(moving) != len(current_uids):
            event.ignore()
            return

        target_row = self._row_at_pos(event.position().toPoint())
        insert_at = max(0, min(target_row, len(staying)))
        new_order = staying[:insert_at] + moving + staying[insert_at:]

        id_to_item: Dict[int, tuple] = {}
        for (_r, uid, text, item) in all_ids:
            id_to_item[uid] = (text, item)
        new_items: List[QtWidgets.QListWidgetItem] = []
        for uid in new_order:
            text, orig = id_to_item.get(uid, ("", None))
            new_item = QtWidgets.QListWidgetItem(text)
            new_item.setData(QtCore.Qt.ItemDataRole.UserRole, uid)
            if orig is not None:
                try:
                    new_item.setIcon(orig.icon())
                except Exception:
                    pass
            new_items.append(new_item)

        self.blockSignals(True)
        try:
            self.clear()
            for ni in new_items:
                self.addItem(ni)
            if moving:
                first = moving[0]
                for idx in range(self.count()):
                    if self.item(idx) and self.item(idx).data(QtCore.Qt.ItemDataRole.UserRole) == first:
                        self.setCurrentRow(idx)
                        break
        finally:
            self.blockSignals(False)

        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()
        QtCore.QTimer.singleShot(0, self.order_changed.emit)


class StationImportListWidget(ReorderListWidget):
    """Station list widget that accepts dropped folders for station import."""

    folders_dropped = QtCore.pyqtSignal(list)
    edit_station_requested = QtCore.pyqtSignal(object)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if event.mimeData().hasUrls():
            folders: List[Path] = []
            seen: set[str] = set()
            for url in event.mimeData().urls():
                if not url.isLocalFile():
                    continue
                folder = Path(url.toLocalFile())
                if not folder.is_dir():
                    continue
                key = str(folder)
                if key in seen:
                    continue
                seen.add(key)
                folders.append(folder)
            if folders:
                self.folders_dropped.emit(folders)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.pos())
        if item is not None and self._pencil_hit(event.pos(), item):
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self.unsetCursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None and self._pencil_hit(event.pos(), item):
                self.setCurrentItem(item)
                self.edit_station_requested.emit(item)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def _pencil_hit(self, pos: QtCore.QPoint, item: QtWidgets.QListWidgetItem) -> bool:
        from gui.widgets.common.delegates import station_pencil_hit_rect

        delegate = self.itemDelegate()
        max_tracks = getattr(delegate, "_max", 255)
        rect = self.visualItemRect(item)
        return station_pencil_hit_rect(rect, self.font(), max_tracks).contains(pos)


# Data roles used by _StationItemDelegate to render station rows. Kept well above
# UserRole+1 (used by the tracks table) to avoid any collision.
_STATION_NUM_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 10
_STATION_NAME_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 11
_STATION_COUNT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 12


class _StationItemDelegate(QtWidgets.QStyledItemDelegate):
    """Custom painter for each row in the basic-mode station list.

    Draws: ≡ drag-handle | 01 number | Station Name | 7/255 count | ✎ edit icon
    Data comes from _STATION_*_ROLE; DisplayRole text is untouched for backend logic.

    ── HOW TO EDIT ─────────────────────────────────────────────────────────────
    • Row height          → change ROW_H (px).
    • Left padding        → change PAD_LEFT (px from widget edge).
    • Column widths       → adjust the offsets in the five paint sections below.
    • Colors              → edit the palette constants at the top of this file.
    • Fonts               → set font size on each *_font object inside paint().
    • Accent bar width    → change ACCENT_W (the coloured strip on selected rows).
    • Separator line      → change SEP_LIGHTER (% brightness relative to row bg).
    ────────────────────────────────────────────────────────────────────────────
    """

    _MAX = BASIC_MAX_TRACKS_PER_STATION

    # ── Station row layout constants (px) ────────────────────────────────────
    ROW_H       = 56    # height of each station row
    PAD_LEFT    = 14    # gap between widget left edge and first element
    HANDLE_W    = 18    # width of the ≡ drag-handle column
    NUM_OFFSET  = 22    # x-offset from PAD_LEFT to start of "01" number
    NUM_W       = 34    # width of the two-digit station number column
    NAME_OFFSET = 60    # x-offset from PAD_LEFT to start of the station name
    NAME_RSVD   = 90    # px reserved on the right for count + pencil
    COUNT_W     = 52    # width of the "N/255" count label
    COUNT_ROFF  = 86    # distance from row right edge to start of count
    PENCIL_ROFF = 26    # distance from row right edge to the ✎ pencil glyph
    PENCIL_W    = 18    # width of the pencil glyph column
    ACCENT_W    = 4     # width of the left accent bar on the selected row (px)
    SEP_LIGHTER = 130   # lighter() factor for the row separator line (100 = same)
    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)

    def sizeHint(self, option, index) -> QtCore.QSize:  # type: ignore[override]
        return QtCore.QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        painter.save()
        rect = option.rect
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)

        # ── 1. Row background ────────────────────────────────────────────────
        # selected → theme STA_SEL_GRAD_MID (guarantees themed contrast in HC/CB)
        # normal   → theme STA_PANE_GRAD_TOP
        painter.fillRect(rect, QColor(_theme.STA_SEL_GRAD_MID if selected else _theme.STA_PANE_GRAD_TOP))

        # ── 2. Left accent bar (selected rows only) ──────────────────────────
        # Coloured strip at the very left edge; width = ACCENT_W px.
        if selected:
            painter.fillRect(
                QtCore.QRect(rect.left(), rect.top(), self.ACCENT_W, rect.height()),
                QColor(_C_BG),
            )

        # ── Data from item roles ─────────────────────────────────────────────
        num   = index.data(_STATION_NUM_ROLE)
        name  = index.data(_STATION_NAME_ROLE) or index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(_STATION_COUNT_ROLE)

        # Colors: bright text on selected (orange), cream on normal (taupe)
        text_color = QColor("#ffffff" if selected else _S_TEXT)
        dim_color  = QColor(_C_BG    if selected else _BORDER)

        x = rect.left() + self.PAD_LEFT

        # ── 3. Drag-handle glyph (≡) ─────────────────────────────────────────
        painter.setPen(dim_color)
        painter.setFont(QFont(option.font))   # regular weight
        painter.drawText(
            QtCore.QRect(x, rect.top(), self.HANDLE_W, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            "\u2630",
        )

        # ── 4. Station / folder number (bold, e.g. "01") ─────────────────────
        num_font = QFont(option.font)
        num_font.setBold(True)                # make the number stand out
        painter.setFont(num_font)
        painter.setPen(text_color)
        painter.drawText(
            QtCore.QRect(x + self.NUM_OFFSET, rect.top(), self.NUM_W, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            f"{int(num):02d}" if num is not None else "",
        )

        # ── 5. Station name (bold, elided if too long) ───────────────────────
        name_font = QFont(option.font)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(text_color)
        name_rect = QtCore.QRect(
            x + self.NAME_OFFSET,
            rect.top(),
            rect.width() - self.NAME_OFFSET - self.NAME_RSVD,
            rect.height(),
        )
        painter.drawText(
            name_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            QtGui.QFontMetrics(name_font).elidedText(
                str(name), QtCore.Qt.TextElideMode.ElideRight, name_rect.width()
            ),
        )

        # ── 6. Track count ("N/255") ─────────────────────────────────────────
        painter.setFont(QFont(option.font))   # regular weight
        painter.setPen(dim_color)
        painter.drawText(
            QtCore.QRect(rect.right() - self.COUNT_ROFF, rect.top(), self.COUNT_W, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight,
            f"{int(count)}/{self._MAX}" if count is not None else "",
        )

        # ── 7. Edit pencil glyph (✎) ─────────────────────────────────────────
        painter.setPen(dim_color)
        painter.drawText(
            QtCore.QRect(rect.right() - self.PENCIL_ROFF, rect.top(), self.PENCIL_W, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            "\u270E",
        )

        # ── 8. Subtle row separator (skip for selected) ──────────────────────
        if not selected:
            sep_color = QColor(_PANEL_DARK).lighter(self.SEP_LIGHTER)
            painter.setPen(QtGui.QPen(sep_color, 1))
            painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()


class _TrackItemDelegate(QtWidgets.QStyledItemDelegate):
    """Custom painter for the Title column of the tracks table.

    Each row shows:  [bold song title]
                     [smaller artist in secondary colour]

    The artist comes from the hidden column 1 (Artist). Paint-only: the actual
    cell data and column order are never touched, so drag-reorder still works.

    ── HOW TO EDIT ─────────────────────────────────────────────────────────────
    • Row height          → change ROW_H (px).
    • Left padding        → change PAD_X (px from cell left).
    • Title / artist split→ the midpoint is ROW_H // 2; adjust top/bottom offsets.
    • Artist font size    → change ARTIST_SIZE_DELTA (points smaller than title).
    • Colors              → edit palette constants at the top of this file.
    ────────────────────────────────────────────────────────────────────────────
    """

    # ── Track row layout constants ────────────────────────────────────────────
    ROW_H            = 48     # height of each track row (px)
    PAD_X            = 14     # left padding inside the cell (px)
    PAD_RIGHT        = 18     # px to subtract from right edge for elide width
    TITLE_TOP_BIAS   = 4      # extra px from top of upper half for title baseline
    ARTIST_SIZE_DELTA = 1.0   # points to subtract from title font for artist
    ARTIST_MIN_PT    = 7.0    # minimum artist font size (pt)
    # ─────────────────────────────────────────────────────────────────────────

    def sizeHint(self, option, index) -> QtCore.QSize:  # type: ignore[override]
        return QtCore.QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        painter.save()
        rect     = option.rect
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)

        # ── 1. Row background ────────────────────────────────────────────────
        # selected → _TRACK_SEL (Apricot Highlight)
        # normal   → _TRACK_BG  (Warm Ivory)
        painter.fillRect(rect, QColor(_TRACK_SEL if selected else _TRACK_BG))

        # ── 2. Pull data ─────────────────────────────────────────────────────
        title  = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        artist = ""
        sib    = index.siblingAtColumn(1)   # hidden Artist column
        if sib.isValid():
            artist = sib.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""

        mid = rect.height() // 2           # vertical midpoint — title above, artist below

        # ── 3. Song title (bold, primary colour) ─────────────────────────────
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(_TEXT_PRI))
        painter.drawText(
            QtCore.QRect(
                rect.left() + self.PAD_X,
                rect.top() + self.TITLE_TOP_BIAS,
                rect.width() - self.PAD_RIGHT,
                mid,
            ),
            QtCore.Qt.AlignmentFlag.AlignBottom | QtCore.Qt.AlignmentFlag.AlignLeft,
            QtGui.QFontMetrics(title_font).elidedText(
                str(title), QtCore.Qt.TextElideMode.ElideRight,
                rect.width() - self.PAD_RIGHT,
            ),
        )

        # ── 4. Artist name (smaller, secondary colour; omitted if empty) ─────
        if artist:
            artist_font = QFont(option.font)
            artist_font.setPointSizeF(
                max(self.ARTIST_MIN_PT, artist_font.pointSizeF() - self.ARTIST_SIZE_DELTA)
            )
            painter.setFont(artist_font)
            painter.setPen(QColor(_TEXT_SEC))
            painter.drawText(
                QtCore.QRect(
                    rect.left() + self.PAD_X,
                    rect.top() + mid,
                    rect.width() - self.PAD_RIGHT,
                    rect.height() - mid - self.TITLE_TOP_BIAS,
                ),
                QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft,
                QtGui.QFontMetrics(artist_font).elidedText(
                    str(artist), QtCore.Qt.TextElideMode.ElideRight,
                    rect.width() - self.PAD_RIGHT,
                ),
            )

        painter.restore()


class InstallMicroPythonDialog(QtWidgets.QDialog):
    """One-time setup: copy MicroPython .uf2 to Pico in BOOTSEL mode.

    Automatically fetches the latest two stable UF2 firmware releases from
    the MicroPython GitHub repository for both Pico and Pico W boards.
    Falls back to manual file browse if the fetch fails (e.g. no internet).
    """

    MICROPYTHON_PICO_URL = "https://micropython.org/download/RPI_PICO/"
    MICROPYTHON_PICO_W_URL = "https://micropython.org/download/RPI_PICO_W/"

    # Board key -> (download page URL, firmware slug used in filenames)
    _BOARDS = {
        "Pico": ("https://micropython.org/download/RPI_PICO/", "RPI_PICO"),
        "Pico W": ("https://micropython.org/download/RPI_PICO_W/", "RPI_PICO_W"),
    }

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, preselect_rpi_rp2: bool = False) -> None:
        super().__init__(parent)
        self._downloaded_path: Optional[Path] = None
        self._preselect_rpi_rp2 = preselect_rpi_rp2
        self._body_lay, _footer = begin_sync_modal_dialog(
            self,
            title="Install MicroPython on Pico",
            subtitle="One-time setup — copy a MicroPython .uf2 to the Pico in BOOTSEL mode.",
            min_width=520,
        )
        self._build_ui()
        self._refresh_drives()
        if preselect_rpi_rp2:
            for i in range(self.drive_combo.count()):
                text = self.drive_combo.itemText(i)
                if "RPI-RP2" in text.upper():
                    self.drive_combo.setCurrentIndex(i)
                    break
        # Fetch firmware list in background
        self._fetch_thread: Optional[threading.Thread] = None
        self._start_firmware_fetch()

    def _build_ui(self) -> None:
        layout = self._body_lay
        instructions = (
            "1. Hold the BOOTSEL button on the Pico.\n"
            "2. Plug the Pico into USB. It will appear as a drive (e.g. RPI-RP2).\n"
            "3. Select a firmware version below (auto-fetched), or browse for a .uf2 file.\n"
            "4. Click Install to Pico. The Pico will reboot with MicroPython (one-time setup)."
        )
        layout.addWidget(QtWidgets.QLabel(instructions))

        # ── Board selector ──
        form = QtWidgets.QFormLayout()
        self.board_combo = VintageComboBox(
            min_width=160,
            max_width=320,
            fixed_height=_theme.TOOLS_ACTION_BTN_H,
        )
        self.board_combo.addItem("Pico", "Pico")
        self.board_combo.addItem("Pico W", "Pico W")
        self.board_combo.currentIndexChanged.connect(self._on_board_changed)
        form.addRow("Board:", self.board_combo)

        # ── Firmware version selector ──
        self.firmware_combo = VintageComboBox(
            min_width=220,
            max_width=9999,
            fixed_height=_theme.TOOLS_ACTION_BTN_H,
        )
        self.firmware_combo.setToolTip("Select a firmware version to download and install")
        self.firmware_combo.addItem("Fetching latest firmware...", None)
        self.firmware_combo.setEnabled(False)
        firmware_row = QtWidgets.QHBoxLayout()
        firmware_row.addWidget(self.firmware_combo, 1)
        self._refresh_firmware_btn = QtWidgets.QPushButton("Refresh")
        self._refresh_firmware_btn.setToolTip("Re-fetch firmware list from GitHub")
        self._refresh_firmware_btn.clicked.connect(self._start_firmware_fetch)
        firmware_row.addWidget(self._refresh_firmware_btn)
        form.addRow("Firmware:", firmware_row)

        # ── Or browse manually ──
        self.uf2_edit = QtWidgets.QLineEdit()
        self.uf2_edit.setPlaceholderText("Or browse for a local .uf2 file...")
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_uf2)
        uf2_row = QtWidgets.QHBoxLayout()
        uf2_row.addWidget(self.uf2_edit)
        uf2_row.addWidget(browse_btn)
        form.addRow("Local file:", uf2_row)

        # ── Pico drive ──
        self.drive_combo = VintageComboBox(
            min_width=220,
            max_width=9999,
            fixed_height=_theme.TOOLS_ACTION_BTN_H,
        )
        self.drive_combo.setToolTip("Select the Pico drive (shown when BOOTSEL is held and Pico is connected)")
        refresh_drives_btn = QtWidgets.QPushButton("Refresh")
        refresh_drives_btn.clicked.connect(self._refresh_drives)
        drive_row = QtWidgets.QHBoxLayout()
        drive_row.addWidget(self.drive_combo)
        drive_row.addWidget(refresh_drives_btn)
        form.addRow("Pico drive:", drive_row)
        layout.addLayout(form)

        # ── Links ──
        link_layout = QtWidgets.QHBoxLayout()
        link_btn = QtWidgets.QPushButton("MicroPython downloads (Pico)")
        link_btn.setToolTip("Open MicroPython download page for standard Pico")
        link_btn.setFlat(True)
        link_btn.setStyleSheet("color: #0066cc; text-decoration: underline; text-align: left;")
        link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QtCore.QUrl(self.MICROPYTHON_PICO_URL)))
        link_w_btn = QtWidgets.QPushButton("Downloads (Pico W)")
        link_w_btn.setToolTip("Open MicroPython download page for Pico W")
        link_w_btn.setFlat(True)
        link_w_btn.setStyleSheet("color: #0066cc; text-decoration: underline; text-align: left;")
        link_w_btn.clicked.connect(lambda: QDesktopServices.openUrl(QtCore.QUrl(self.MICROPYTHON_PICO_W_URL)))
        link_layout.addWidget(link_btn)
        link_layout.addWidget(link_w_btn)
        link_layout.addStretch()
        layout.addLayout(link_layout)

        # ── Install button ──
        copy_btn = QtWidgets.QPushButton("Install to Pico")
        copy_btn.clicked.connect(self._copy_to_pico)
        layout.addWidget(copy_btn)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Store fetched firmware data: {board_key: [(display_name, download_url, file_name), ...]}
        self._firmware_data: Dict[str, list] = {}

    # ── Firmware fetching ──

    def _start_firmware_fetch(self) -> None:
        """Kick off background fetch of firmware releases from GitHub."""
        self.firmware_combo.clear()
        self.firmware_combo.addItem("Fetching latest firmware...", None)
        self.firmware_combo.setEnabled(False)
        self._refresh_firmware_btn.setEnabled(False)
        self.status_label.setText("")
        self._fetch_thread = threading.Thread(target=self._fetch_firmware_releases, daemon=True)
        self._fetch_thread.start()

    def _fetch_firmware_releases(self) -> None:
        """Background: scrape micropython.org download pages for UF2 links.

        This function is resilient to macOS Python SSL issues: it first attempts a
        normal HTTPS request, then retries using certifi's CA bundle if available,
        and finally falls back to an unverified SSL context as last resort.
        """
        import urllib.request
        import urllib.error
        import json as _json
        import re as _re
        import ssl

        # Helper to fetch a URL with multiple SSL strategies (certifi first for macOS SSL issues)
        def fetch_url(req: urllib.request.Request, timeout: int = 15) -> str:
            # 1) Try certifi CA bundle first (fixes macOS "unable to get local issuer certificate")
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    return resp.read().decode("utf-8")
            except Exception as e_certifi:
                # 2) Try default SSL behavior
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        return resp.read().decode("utf-8")
                except Exception as e_default:
                    # 3) As last resort, disable SSL verification (less secure)
                    try:
                        ctx = ssl.create_default_context()
                        ctx.check_hostname = False
                        ctx.verify_mode = ssl.CERT_NONE
                        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                            return resp.read().decode("utf-8")
                    except Exception as e_all:
                        raise e_all from e_certifi

        result: Dict[str, list] = {}
        errors: Dict[str, str] = {}

        for board_key, (page_url, slug) in self._BOARDS.items():
            entries: list = []
            try:
                req = urllib.request.Request(page_url, headers={"User-Agent": "VintageRadio/1.0"})
                html = fetch_url(req, timeout=15)

                # Find .uf2 links — they appear in order newest-first on the page
                uf2_links = _re.findall(r'href="(/resources/firmware/[^"]*\.uf2)"', html)
                for link in uf2_links:
                    filename = link.rsplit("/", 1)[-1]
                    # Extract version from filename like RPI_PICO-20251209-v1.27.0.uf2
                    m = _re.search(r"-(\d{8})-(v[\d.]+)\.uf2$", filename)
                    if m:
                        date_str, version = m.group(1), m.group(2)
                        display = f"{version}  ({date_str[:4]}-{date_str[4:6]}-{date_str[6:]})"
                    else:
                        display = filename
                    download_url = "https://micropython.org" + link
                    entries.append((display, download_url, filename))
                    if len(entries) >= 2:
                        break
            except Exception as e:
                errors[board_key] = f"{type(e).__name__}: {e}"
            result[board_key] = entries

        if not any(result.values()):
            # Build a helpful error message including per-board details if available
            if errors:
                details = "; ".join(f"{k}: {v}" for k, v in errors.items())
                msg = f"Could not find firmware on micropython.org. Errors: {details}"
            else:
                msg = "Could not find firmware on micropython.org"

            QtCore.QMetaObject.invokeMethod(
                self, "_on_fetch_error", QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, msg),
            )
            return

        QtCore.QMetaObject.invokeMethod(
            self, "_on_fetch_success", QtCore.Qt.ConnectionType.QueuedConnection,
            QtCore.Q_ARG(str, _json.dumps(result)),
        )

    @QtCore.pyqtSlot(str)
    def _on_fetch_success(self, data_json: str) -> None:
        import json as _json
        self._firmware_data = _json.loads(data_json)
        self._refresh_firmware_btn.setEnabled(True)
        self._populate_firmware_combo()

    @QtCore.pyqtSlot(str)
    def _on_fetch_error(self, error_msg: str) -> None:
        self._refresh_firmware_btn.setEnabled(True)
        self.firmware_combo.clear()
        self.firmware_combo.addItem("(Could not fetch - use Browse instead)", None)
        self.firmware_combo.setEnabled(False)
        self.status_label.setText(f"Could not fetch firmware list: {error_msg}")
        self.status_label.setStyleSheet("color: #cc6600;")

    def _populate_firmware_combo(self) -> None:
        """Fill the firmware combo with entries for the currently selected board."""
        board_key = self.board_combo.currentData()
        entries = self._firmware_data.get(board_key, [])
        self.firmware_combo.clear()
        if entries:
            for display, url, filename in entries:
                self.firmware_combo.addItem(display, {"url": url, "filename": filename})
            self.firmware_combo.setEnabled(True)
            self.status_label.setText("")
            self.status_label.setStyleSheet("")
        else:
            self.firmware_combo.addItem("(No firmware found - use Browse instead)", None)
            self.firmware_combo.setEnabled(False)

    def _on_board_changed(self, _index: int) -> None:
        if self._firmware_data:
            self._populate_firmware_combo()

    # ── Manual browse ──

    def _browse_uf2(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select MicroPython firmware (.uf2)",
            "",
            "UF2 firmware (*.uf2);;All files (*)",
        )
        if path:
            self.uf2_edit.setText(path)

    # ── Drives ──

    def _refresh_drives(self) -> None:
        self.drive_combo.clear()
        for path, label in SDManager.detect_sd_roots():
            display = f"{label} ({path})" if label else str(path)
            self.drive_combo.addItem(display, path)
        if self.drive_combo.count() == 0:
            self.drive_combo.addItem("(No removable drives found)", None)

    # ── Install ──

    def _copy_to_pico(self) -> None:
        # Determine UF2 source: manual browse takes priority, then combo selection
        manual_path = self.uf2_edit.text().strip()
        if manual_path:
            uf2_path = Path(manual_path)
            if not uf2_path.is_file() or uf2_path.suffix.lower() != ".uf2":
                VintageMessageBox.warning(
                    self, "Install MicroPython on Pico",
                    "The file path entered is not a valid .uf2 file.",
                )
                return
            self._install_uf2(uf2_path)
            return

        # Use selected firmware from combo — need to download first
        fw_data = self.firmware_combo.currentData()
        if not fw_data or not isinstance(fw_data, dict):
            VintageMessageBox.warning(
                self, "Install MicroPython on Pico",
                "No firmware selected. Either select a version from the dropdown or browse for a local .uf2 file.",
            )
            return

        # Verify drive first before downloading
        drive_data = self.drive_combo.currentData()
        if drive_data is None or not Path(drive_data).is_dir():
            VintageMessageBox.warning(
                self, "Install MicroPython on Pico",
                "No Pico drive selected. Hold BOOTSEL, plug in the Pico, then click Refresh.",
            )
            return

        # Download to temp and then install
        url = fw_data["url"]
        filename = fw_data["filename"]
        self.status_label.setStyleSheet("color: #333;")
        self.status_label.setText(f"Downloading {filename}...")
        self.setEnabled(False)
        QtWidgets.QApplication.processEvents()

        download_thread = threading.Thread(
            target=self._download_and_install, args=(url, filename), daemon=True
        )
        download_thread.start()

    def _download_and_install(self, url: str, filename: str) -> None:
        import urllib.request
        import tempfile
        import ssl

        def _download_with_ssl(url: str, dest_path: Path) -> None:
            """Download URL to file using certifi CA bundle (fixes macOS SSL verify failed)."""
            req = urllib.request.Request(url, headers={"User-Agent": "VintageRadio/1.0"})
            # Prefer certifi so HTTPS works on macOS when system certs are not in Python's trust store
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                dest_path.write_bytes(resp.read())

        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="vintage_radio_uf2_"))
            dest = tmp_dir / filename
            _download_with_ssl(url, dest)
            self._downloaded_path = dest
            QtCore.QMetaObject.invokeMethod(
                self, "_on_download_success", QtCore.Qt.ConnectionType.QueuedConnection,
            )
        except Exception as e:
            QtCore.QMetaObject.invokeMethod(
                self, "_on_download_error", QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, str(e)),
            )

    @QtCore.pyqtSlot()
    def _on_download_success(self) -> None:
        self.setEnabled(True)
        if self._downloaded_path and self._downloaded_path.is_file():
            self.status_label.setText(f"Downloaded: {self._downloaded_path.name}")
            self.status_label.setStyleSheet("color: green;")
            self._install_uf2(self._downloaded_path)
        else:
            self.status_label.setText("Download failed (file not found).")
            self.status_label.setStyleSheet("color: red;")

    @QtCore.pyqtSlot(str)
    def _on_download_error(self, error_msg: str) -> None:
        self.setEnabled(True)
        self.status_label.setText(f"Download failed: {error_msg}")
        self.status_label.setStyleSheet("color: red;")

    def _install_uf2(self, uf2_path: Path) -> None:
        """Copy a .uf2 file to the selected Pico drive."""
        drive_data = self.drive_combo.currentData()
        if drive_data is None:
            VintageMessageBox.warning(
                self, "Install MicroPython on Pico",
                "No Pico drive selected. Hold BOOTSEL, plug in the Pico, then click Refresh.",
            )
            return
        dest_dir = Path(drive_data)
        if not dest_dir.is_dir():
            VintageMessageBox.warning(
                self, "Install MicroPython on Pico",
                f"Drive not found: {dest_dir}. Unplug and replug the Pico (with BOOTSEL held), then Refresh.",
            )
            return
        dest_file = dest_dir / uf2_path.name
        try:
            shutil.copy2(uf2_path, dest_file)
        except OSError as e:
            VintageMessageBox.warning(
                self, "Install MicroPython on Pico",
                f"Could not copy to Pico: {e}",
            )
            return

        # Clean up downloaded temp file
        if self._downloaded_path and self._downloaded_path.exists():
            try:
                tmp_dir = self._downloaded_path.parent
                self._downloaded_path.unlink()
                tmp_dir.rmdir()
            except OSError:
                pass
            self._downloaded_path = None

        self.status_label.setText("Firmware copied! Pico will reboot with MicroPython.")
        self.status_label.setStyleSheet("color: green;")
        # Close dialog so caller can run app install automatically (no extra message box)
        self.accept()


class MainWindow(QtWidgets.QMainWindow):
    update_check_finished = QtCore.pyqtSignal(object, bool, str)

    def __init__(self, dev_mode: bool = False) -> None:
        super().__init__()
        self._ui_dev_mode = dev_mode   # True when launched with --dev
        self._theme_watcher: Optional[QtCore.QFileSystemWatcher] = None
        self._apply_default_window_geometry()

        icon_path = resource_path("vintage_radio.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._lib_registry = LibraryRegistry()
        slug = self._lib_registry.active_library()
        db_path = self._lib_registry.db_path_for(slug)
        self.db = DatabaseManager(db_path=db_path)
        self._update_window_title()
        self._developer_mode = (
            os.environ.get("VINTAGE_RADIO_ENABLE_MCP_DEBUG", "").strip().lower()
            in ("1", "true", "yes")
            or str(self.db.get_setting("developer_mode", "0")).strip().lower()
            in ("1", "true", "yes")
        )
        try:
            self._mcp_port = int(os.environ.get("VINTAGE_RADIO_MCP_PORT", "8765"))
        except ValueError:
            self._mcp_port = 8765
        self._mcp_manager = DebugMcpServerManager(
            get_connection_state=self._mcp_get_connection_state,
            invoke_action=self._mcp_invoke_action,
            get_log_path=self._mcp_get_log_path,
            log=self._mcp_log,
        )
        self._mcp_gui_queue: deque = deque()
        self._mcp_gui_queue_lock = threading.Lock()
        self._update_check_in_flight = False
        self.update_check_finished.connect(self._on_update_check_finished)

        self._undo_stack: List[dict] = []
        self._redo_stack: List[dict] = []
        self.sd_manager = SDManager(self.db)
        self._conversion_prefetch = ConversionPrefetchController(self)

        self.library_table = LibraryTable()
        self.library_table.files_dropped.connect(self.import_files)
        self.library_table.itemChanged.connect(self.on_library_item_changed)
        self._loading_library = False
        self._basic_tracks_load_token = 0
        self._basic_tracks_target_station_id: Optional[int] = None
        self._basic_tracks_loader_thread: Optional[QtCore.QThread] = None
        self._song_path_missing_cache: dict[str, bool] = {}
        self.library_table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.library_table.customContextMenuRequested.connect(
            self.show_library_menu
        )

        self.library_search = QtWidgets.QLineEdit()
        self.library_search.setPlaceholderText("Search by title, artist, format, or path")
        self.library_search.textChanged.connect(self.refresh_library)

        self.album_list = ReorderListWidget()
        self.album_list.order_changed.connect(self._persist_album_list_order)
        self.album_songs_table = self._create_song_table(reorderable=True)
        self.album_songs_table.order_changed.connect(self.persist_album_order)
        if isinstance(self.album_songs_table, CollectionDropTable):
            self.album_songs_table.files_dropped.connect(self.import_files_to_album)
        self.playlist_list = ReorderListWidget()
        self.playlist_list.order_changed.connect(self._persist_playlist_list_order)
        self.playlist_songs_table = self._create_song_table(reorderable=True)
        self.playlist_songs_table.order_changed.connect(self.persist_playlist_order)
        if isinstance(self.playlist_songs_table, CollectionDropTable):
            self.playlist_songs_table.files_dropped.connect(
                self.import_files_to_playlist
            )
        self.album_songs_table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.album_songs_table.customContextMenuRequested.connect(
            self.show_album_table_menu
        )
        self.playlist_songs_table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.playlist_songs_table.customContextMenuRequested.connect(
            self.show_playlist_table_menu
        )

        self.sd_root_label = QtWidgets.QLabel()
        self.sd_status = QtWidgets.QTextEdit()
        self.sd_status.setReadOnly(True)
        self.sd_album_combo = QtWidgets.QComboBox()
        self.sd_playlist_combo = QtWidgets.QComboBox()
        self.test_mode_widget = None
        self._device_debug_widget = None  # Lazy-load to avoid crash during init (macOS/pyserial)

        self._apply_saved_settings()
        self._normalize_sidebar_view_mode()

        self._build_menu()
        self._build_library_toolbar()
        self._build_tabs()
        self._set_button_cursors()
        self._refresh_all()
        self._build_status_bar_zoom()
        self._apply_ui_zoom()
        self._maybe_auto_start_mcp()
        QtCore.QTimer.singleShot(1200, self._check_for_updates_on_startup)
        from gui.window_chrome import install_caption_color_filter

        install_caption_color_filter(self)
        QtCore.QTimer.singleShot(0, self._sync_startup_chrome)
        QtCore.QTimer.singleShot(250, self._sync_startup_chrome)
        install_vintage_popup_styles()

    def _normalize_sidebar_view_mode(self) -> None:
        """Sidebar UI runs in basic mode unless the user switches view mode this session.

        Older library DBs often still have ``view_mode=advanced`` from when the View
        menu was visible. That silently turned on advanced-only sync behavior (e.g.
        firmware reflash prompts) with no UI affordance to switch back.
        """
        if self.devices_view_mode == "advanced":
            self.devices_view_mode = "basic"
            self.db.set_setting("view_mode", "basic")

    def _apply_default_window_geometry(self) -> None:
        """Size and centre the window at 1200×780 (clamped to available screen)."""
        app = QtWidgets.QApplication.instance()
        fallback_w, fallback_h = 1200, 780
        if not app:
            self.resize(fallback_w, fallback_h)
            return
        screen = app.primaryScreen()
        if not screen:
            self.resize(fallback_w, fallback_h)
            return
        rect = screen.availableGeometry()
        w = min(fallback_w, rect.width())
        h = min(fallback_h, rect.height())
        x = rect.x() + (rect.width() - w) // 2
        y = rect.y() + (rect.height() - h) // 2
        self.setGeometry(x, y, w, h)

    def _build_status_bar_zoom(self) -> None:
        """Build the footer bar: zoom controls on left, version label on right.

        Styled to match the HTML mockup:
          background: #f5eadc; border-top: 1px solid #d8c6ad; height: 48px.
        Zoom buttons: gradient pill with border and drop shadow.

        HOW TO EDIT
        -----------
          Footer colours / height  → theme.FOOTER_*
          Zoom button sizes        → theme.ZOOM_BTN_W / H / RADIUS etc.
        """
        sb = self.statusBar()
        sb.setFixedHeight(_theme.FOOTER_H)
        sb.setStyleSheet(f"""
            QStatusBar {{
                background: {_theme.FOOTER_BG};
                border-top: 1px solid {_theme.FOOTER_BORDER};
                color: {_theme.FOOTER_TEXT};
                font-size: {_theme.FOOTER_FONT_SIZE}px;
            }}
            QStatusBar::item {{
                border: none;
            }}
        """)

        _zoom_btn_qss = f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {_theme.ZOOM_BTN_GRAD_TOP},
                    stop:1 {_theme.ZOOM_BTN_GRAD_BOT});
                border: 1px solid {_theme.ZOOM_BTN_BORDER};
                border-radius: {_theme.ZOOM_BTN_RADIUS}px;
                color: {_theme.FOOTER_TEXT};
                font-weight: bold;
                font-size: {_theme.FOOTER_FONT_SIZE}px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {_theme.ZOOM_BTN_GRAD_BOT},
                    stop:1 {_theme.ZOOM_BTN_GRAD_TOP});
            }}
            QPushButton:pressed {{
                background: {_theme.ZOOM_BTN_GRAD_BOT};
            }}
        """

        def _zoom_shadow():
            eff = QtWidgets.QGraphicsDropShadowEffect()
            eff.setBlurRadius(8)
            eff.setOffset(0, 2)
            eff.setColor(QtGui.QColor(0, 0, 0, 45))
            return eff

        container = QtWidgets.QWidget()
        zoom_layout = QtWidgets.QHBoxLayout(container)
        zoom_layout.setContentsMargins(10, 0, 6, 0)
        zoom_layout.setSpacing(_theme.ZOOM_SPACING)

        zoom_label = QtWidgets.QLabel("Zoom")
        zoom_label.setStyleSheet(
            f"color: {_theme.FOOTER_TEXT}; font-size: {_theme.FOOTER_FONT_SIZE}px;"
        )
        zoom_layout.addWidget(zoom_label)

        zoom_out_btn = QtWidgets.QPushButton("\u2212")
        zoom_out_btn.setToolTip("Zoom out (min 80%)")
        zoom_out_btn.setFixedSize(_theme.ZOOM_BTN_W, _theme.ZOOM_BTN_H)
        zoom_out_btn.setStyleSheet(_zoom_btn_qss)
        zoom_out_btn.setGraphicsEffect(_zoom_shadow())
        zoom_out_btn.clicked.connect(self._on_zoom_out)

        zoom_in_btn = QtWidgets.QPushButton("+")
        zoom_in_btn.setToolTip("Zoom in (max 200%)")
        zoom_in_btn.setFixedSize(_theme.ZOOM_BTN_W, _theme.ZOOM_BTN_H)
        zoom_in_btn.setStyleSheet(_zoom_btn_qss)
        zoom_in_btn.setGraphicsEffect(_zoom_shadow())
        zoom_in_btn.clicked.connect(self._on_zoom_in)

        zoom_layout.addWidget(zoom_out_btn)
        zoom_layout.addWidget(zoom_in_btn)
        sb.addWidget(container)

        # Version label — pinned to the right via addPermanentWidget
        ver_label = QtWidgets.QLabel(__version__)
        self._footer_version_label = ver_label
        ver_label.setStyleSheet(self._footer_version_stylesheet())
        sb.addPermanentWidget(ver_label)

    @staticmethod
    def _footer_version_stylesheet() -> str:
        return (
            f"color: {_theme.FOOTER_TEXT}; "
            f"font-size: {_ui_scale.px(_theme.FOOTER_FONT_SIZE - 1)}px; "
            "margin-right: 14px;"
        )

    def _apply_ui_zoom(self) -> None:
        """Apply UI zoom level. Styled widgets refresh via reload_theme / u.px(); avoid
        forcing point sizes on every child — that breaks sidebar nav and page layout."""
        _ui_scale.set_zoom_percent(self._ui_zoom_level)
        app = QtWidgets.QApplication.instance()
        if not app:
            return
        if not getattr(self, "_ui_zoom_base_pt", None):
            base_pt = app.font().pointSize()
            self._ui_zoom_base_pt = base_pt if base_pt and base_pt > 0 else 10
        base_pt = self._ui_zoom_base_pt
        new_pt = max(1, int(base_pt * self._ui_zoom_level / 100))
        base_font = app.font()
        new_font = QFont(base_font)
        new_font.setPointSize(new_pt)
        app.setFont(new_font)

        fm = QtGui.QFontMetrics(app.font())
        if hasattr(self, "_library_heading_label") and self._library_heading_label is not None:
            label_font = QFont(app.font())
            label_font.setBold(True)
            self._library_heading_label.setFont(label_font)
        if hasattr(self, "_lib_combo") and self._lib_combo is not None:
            self._lib_combo.setMinimumWidth(max(180, fm.averageCharWidth() * 22))
        min_w = min(1600, max(700, int(650 * self._ui_zoom_level // 100)))
        min_h = min(900, max(500, int(450 * self._ui_zoom_level // 100)))
        self.setMinimumSize(min_w, min_h)
        cw = self.centralWidget()
        if cw is not None:
            cw.setMinimumWidth(0)
            if isinstance(cw, QtWidgets.QTabWidget):
                cw.tabBar().setExpanding(False)
        if hasattr(self, "library_table") and self.library_table is not None:
            self.library_table.horizontalHeader().setMinimumSectionSize(
                max(40, fm.averageCharWidth() * 8)
            )
        if hasattr(self, "_library_controls_widget") and self._library_controls_widget is not None:
            self._library_controls_widget.setMinimumWidth(max(400, fm.averageCharWidth() * 55))
        self._relayout_basic_station_rows()
        self._apply_ui_zoom_to_themed_pages()
        footer_ver = getattr(self, "_footer_version_label", None)
        if _qt_widget_alive(footer_ver):
            footer_ver.setStyleSheet(self._footer_version_stylesheet())

    def _apply_ui_zoom_to_themed_pages(self) -> None:
        """Refresh pages that bake font sizes into stylesheets (Settings, Help, etc.)."""
        for attr in (
            "_settings_page",
            "_help_page",
            "_load_music_page",
            "_install_firmware_page",
            "_tools_page",
            "_library_bar",
            "_sidebar",
        ):
            page = getattr(self, attr, None)
            if not _qt_widget_alive(page):
                continue
            if hasattr(page, "apply_ui_zoom"):
                page.apply_ui_zoom()
            elif hasattr(page, "reload_theme"):
                page.reload_theme()
        install_vintage_popup_styles()

    def _relayout_basic_station_rows(self) -> None:
        """Refresh station row heights after font/zoom changes."""
        lst = getattr(self, "_basic_station_list", None)
        if not _qt_widget_alive(lst):
            return
        delegate = lst.itemDelegate()
        model = lst.model()
        if model is None:
            return
        option = QtWidgets.QStyleOptionViewItem()
        lst.initViewItemOption(option)
        vw = max(lst.viewport().width(), 100)
        for i in range(lst.count()):
            item = lst.item(i)
            if item is None:
                continue
            option.rect = QtCore.QRect(0, 0, vw, 0)
            idx = model.index(i, 0)
            item.setSizeHint(delegate.sizeHint(option, idx))
        lst.doItemsLayout()
        lst.viewport().update()

    def _sync_settings_ui_zoom_display(self) -> None:
        page = getattr(self, "_settings_page", None)
        if not _qt_widget_alive(page):
            return
        spin = page.ui_zoom_spin
        if spin.value() != self._ui_zoom_level:
            spin.blockSignals(True)
            spin.setValue(self._ui_zoom_level)
            spin.blockSignals(False)

    def _on_zoom_in(self) -> None:
        self._ui_zoom_level = min(200, self._ui_zoom_level + 10)
        self.db.set_setting("ui_zoom_level", str(self._ui_zoom_level))
        self._apply_ui_zoom()
        self._sync_settings_ui_zoom_display()

    def _on_zoom_out(self) -> None:
        self._ui_zoom_level = max(80, self._ui_zoom_level - 10)
        self.db.set_setting("ui_zoom_level", str(self._ui_zoom_level))
        self._apply_ui_zoom()
        self._sync_settings_ui_zoom_display()

    def _set_button_cursors(self) -> None:
        """Set pointing hand cursor for all buttons in the application."""
        pointer = QtCore.Qt.CursorShape.PointingHandCursor
        # Recursively find all buttons and set cursor
        for btn in self.findChildren(QtWidgets.QPushButton):
            btn.setCursor(pointer)
        for chk in self.findChildren(QtWidgets.QCheckBox):
            chk.setCursor(pointer)
        for combo in self.findChildren(QtWidgets.QComboBox):
            combo.setCursor(pointer)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("File")

        import_action = QtGui.QAction("Import Files", self)
        import_action.triggered.connect(self.open_import_dialog)
        menu.addAction(import_action)

        backup_action = QtGui.QAction("Backup Now", self)
        backup_action.triggered.connect(self.run_backup)
        menu.addAction(backup_action)

        settings_action = QtGui.QAction("Preferences", self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        exit_action = QtGui.QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

        edit_menu = self.menuBar().addMenu("Edit")
        undo_action = QtGui.QAction("Undo", self)
        undo_action.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self.undo_last_action)
        edit_menu.addAction(undo_action)
        redo_action = QtGui.QAction("Redo", self)
        redo_action.setShortcut(QtGui.QKeySequence.StandardKey.Redo)
        redo_action.triggered.connect(self.redo_last_action)
        edit_menu.addAction(redo_action)

        view_menu = self.menuBar().addMenu("View")
        self._view_basic_action = QtGui.QAction("Basic", self)
        self._view_basic_action.setCheckable(True)
        self._view_basic_action.triggered.connect(lambda: self._set_devices_view_mode("basic"))
        view_menu.addAction(self._view_basic_action)
        self._view_advanced_action = QtGui.QAction("Advanced", self)
        self._view_advanced_action.setCheckable(True)
        self._view_advanced_action.triggered.connect(lambda: self._set_devices_view_mode("advanced"))
        view_menu.addAction(self._view_advanced_action)
        self._view_legacy_action = QtGui.QAction("Legacy", self)
        self._view_legacy_action.setCheckable(True)
        self._view_legacy_action.triggered.connect(lambda: self._set_devices_view_mode("legacy"))
        legacy_menu = view_menu.addMenu("Legacy")
        legacy_menu.addAction(self._view_legacy_action)
        self._update_view_menu_checked()

        tools_menu = self.menuBar().addMenu("Tools")
        sync_action = QtGui.QAction("Sync to SD", self)
        sync_action.triggered.connect(self.sync_to_sd)
        tools_menu.addAction(sync_action)

        self._tools_developer_mode_action = QtGui.QAction("Developer mode", self)
        self._tools_developer_mode_action.setCheckable(True)
        self._tools_developer_mode_action.setChecked(self._developer_mode)
        self._tools_developer_mode_action.setToolTip(
            "Show the Developer menu (MCP debug server, scripts). "
            "Preference is saved; turn off to hide developer tools."
        )
        self._tools_developer_mode_action.triggered.connect(self._set_developer_mode_from_tools_menu)
        tools_menu.addAction(self._tools_developer_mode_action)
        tools_menu.aboutToShow.connect(self._sync_tools_developer_mode_action_checked)

        # Secret hardware diagnostics menu item: only visible when Shift is held
        # while the Tools menu is being opened. The action is always reachable via
        # Ctrl+Shift+H regardless of whether the menu item is visible.
        self._hw_diag_action = QtGui.QAction("Hardware Diagnostics...", self)
        self._hw_diag_action.setShortcut(
            QtGui.QKeySequence("Ctrl+Shift+H")
        )
        self._hw_diag_action.triggered.connect(self._open_hw_diagnostics)
        self._hw_diag_action.setVisible(False)
        tools_menu.addSeparator()
        tools_menu.addAction(self._hw_diag_action)

        # Show the hidden action when Shift is held as the menu is about to open
        tools_menu.aboutToShow.connect(self._reveal_hw_diag_on_shift)
        tools_menu.aboutToHide.connect(
            lambda: self._hw_diag_action.setVisible(False)
        )
        self.addAction(self._hw_diag_action)  # shortcut active even without menu

        # Shortcut is always registered so users get feedback even when dev mode is off.
        self._mcp_toggle_action = QtGui.QAction("MCP debug server OFF — click to start", self)
        self._mcp_toggle_action.setCheckable(True)
        self._mcp_toggle_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+M"))
        self._mcp_toggle_action.triggered.connect(self._handle_mcp_toggle_action)
        self.addAction(self._mcp_toggle_action)

        if self._developer_mode:
            self._install_developer_menu()

        help_menu = self.menuBar().addMenu("Help")

        view_log_action = QtGui.QAction("View Session Log", self)
        view_log_action.triggered.connect(self._view_session_log)
        help_menu.addAction(view_log_action)

        open_log_folder_action = QtGui.QAction("Open Logs Folder", self)
        open_log_folder_action.triggered.connect(self._open_logs_folder)
        help_menu.addAction(open_log_folder_action)

        copy_log_path_action = QtGui.QAction("Copy Log Path to Clipboard", self)
        copy_log_path_action.triggered.connect(self._copy_log_path)
        help_menu.addAction(copy_log_path_action)

        help_menu.addSeparator()
        reenable_track_warn_action = QtGui.QAction(
            "Re-enable station track count warning (255+ tracks)", self
        )
        reenable_track_warn_action.setToolTip(
            "Shows the informational dialog again when a station would exceed 255 tracks "
            "after you chose Don't show again on that warning."
        )
        reenable_track_warn_action.triggered.connect(self._reenable_basic_track_count_warning)
        help_menu.addAction(reenable_track_warn_action)

        help_menu.addSeparator()
        check_updates_action = QtGui.QAction("Check for Updates", self)
        check_updates_action.triggered.connect(self._check_for_updates_menu)
        help_menu.addAction(check_updates_action)

        about_action = QtGui.QAction("About Vintage Radio", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _update_view_menu_checked(self) -> None:
        """Sync View menu check state with current devices_view_mode."""
        if hasattr(self, "_view_basic_action") and hasattr(self, "_view_advanced_action"):
            self._view_basic_action.setChecked(self.devices_view_mode == "basic")
            self._view_advanced_action.setChecked(self.devices_view_mode == "advanced")
        if hasattr(self, "_view_legacy_action"):
            self._view_legacy_action.setChecked(self.devices_view_mode == "legacy")

    def _is_basic_like_mode(self) -> bool:
        return self.devices_view_mode in ("basic", "advanced")

    def _is_advanced_mode(self) -> bool:
        return self.devices_view_mode == "advanced"

    def _uses_custom_software(self) -> bool:
        return self._is_advanced_mode() and self.db.get_setting("advanced_software_source", "our") == "custom"

    @staticmethod
    def _default_advanced_mcu_button_rows() -> List[List[str]]:
        s = ADVANCED_MCU_BTN_SECTION_TAG
        return [
            [s, "TAPS"],
            ["Single", "Next track"],
            ["Double", "Previous track"],
            [
                "Triple",
                "Restart from the beginning: track 1 in station order, or first track "
                "in the current station track-shuffle pass",
            ],
            [
                "Four",
                "Previous station (or previous album/playlist in shuffle); pairs with Hold = next station",
            ],
            [
                "Five",
                "Jump to the first station (basic) or first album/playlist (advanced); exits track shuffle",
            ],
            [s, "HOLD (long press, no taps)"],
            [
                "Hold",
                "Next station in folder order (also advances station while in track-shuffle mode).",
            ],
            [s, "TAP + HOLD"],
            [
                "1 tap + hold",
                "Exit track shuffle to normal ordered-station mode (no-op if already ordered)",
            ],
            ["2 taps + hold", "Shuffle tracks in the current station (repeat = reshuffle)"],
            [
                "3 taps + hold",
                "First station (or first album/playlist) with a fresh track shuffle — stays in shuffle",
            ],
        ]

    def _advanced_parse_button_rows_json(self, raw: str) -> List[List[str]]:
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        out: List[List[str]] = []
        for row in data:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                out.append([str(row[0]), str(row[1])])
            elif isinstance(row, (list, tuple)) and len(row) == 1:
                out.append([str(row[0]), ""])
        migrated: List[List[str]] = []
        for pair in out:
            if len(pair) < 2:
                continue
            a0 = str(pair[0]).strip()
            a1 = str(pair[1]).strip() if len(pair) > 1 else ""
            if a0 == ADVANCED_MCU_BTN_SECTION_TAG:
                migrated.append([ADVANCED_MCU_BTN_SECTION_TAG, a1 or "Heading"])
                continue
            if not a1 and a0 in _ADVANCED_MCU_BTN_LEGACY_SECTION_FIRST_COL:
                migrated.append([ADVANCED_MCU_BTN_SECTION_TAG, a0])
                continue
            migrated.append([str(pair[0]), str(pair[1]) if len(pair) > 1 else ""])
        return migrated

    @staticmethod
    def _advanced_button_rows_to_json(rows: List[List[str]]) -> str:
        clean: List[List[str]] = []
        for r in rows:
            if len(r) >= 2:
                clean.append([str(r[0]), str(r[1])])
            elif len(r) == 1:
                clean.append([str(r[0]), ""])
        return json.dumps(clean, ensure_ascii=False)

    def _advanced_mcu_clear_row_handles(self, t: QtWidgets.QTableWidget) -> None:
        for r in range(t.rowCount()):
            if t.cellWidget(r, _ADV_MCU_COL_HANDLE) is not None:
                t.removeCellWidget(r, _ADV_MCU_COL_HANDLE)

    def _advanced_refresh_mcu_row_handles(self) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return
        self._advanced_mcu_clear_row_handles(t)
        for r in range(t.rowCount()):
            gutter = _AdvancedMcuRowGutterHandle(
                partial(self._advanced_mcu_row_junction_menu, t, r),
                parent=t,
            )
            t.setCellWidget(r, _ADV_MCU_COL_HANDLE, gutter)
        self._advanced_mcu_set_visible_gutter_row(None)

    def _advanced_fill_mcu_button_table(
        self,
        rows: List[List[str]],
        *,
        prefer_blank: bool = False,
    ) -> None:
        """Fill the gestures table. If *prefer_blank* and *rows* is empty, show blank starter rows only."""
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return
        t.blockSignals(True)
        self._advanced_mcu_clear_row_handles(t)
        t.clearContents()
        if hasattr(t, "clearSpans"):
            t.clearSpans()
        base = list(rows)
        if not base:
            if prefer_blank:
                base = []
            else:
                base = list(self._default_advanced_mcu_button_rows())
        if not base and prefer_blank:
            n = 5
        else:
            n = len(base) + 2
        t.setRowCount(n)
        _sec_bg = QColor(38, 38, 40)
        _sec_fg = QColor(240, 240, 242)
        for i, pair in enumerate(base):
            a = str(pair[0]) if len(pair) > 0 else ""
            b = str(pair[1]) if len(pair) > 1 else ""
            if a.strip() == ADVANCED_MCU_BTN_SECTION_TAG:
                title = b.strip() or "Heading"
                it = QtWidgets.QTableWidgetItem(title)
                it.setFlags(
                    it.flags()
                    | QtCore.Qt.ItemFlag.ItemIsEditable
                    | QtCore.Qt.ItemFlag.ItemIsEnabled
                    | QtCore.Qt.ItemFlag.ItemIsSelectable
                )
                _sf = QFont(it.font())
                _sf.setBold(True)
                it.setFont(_sf)
                it.setBackground(QBrush(_sec_bg))
                it.setForeground(QBrush(_sec_fg))
                it.setTextAlignment(
                    QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
                t.setSpan(i, _ADV_MCU_COL_GESTURE, 1, 2)
                t.setItem(i, _ADV_MCU_COL_GESTURE, it)
            else:
                t.setSpan(i, _ADV_MCU_COL_GESTURE, 1, 1)
                t.setSpan(i, _ADV_MCU_COL_ACTION, 1, 1)
                left = QtWidgets.QTableWidgetItem(a)
                left.setFlags(
                    left.flags()
                    | QtCore.Qt.ItemFlag.ItemIsEditable
                    | QtCore.Qt.ItemFlag.ItemIsEnabled
                    | QtCore.Qt.ItemFlag.ItemIsSelectable
                )
                right = QtWidgets.QTableWidgetItem(b)
                right.setFlags(
                    right.flags()
                    | QtCore.Qt.ItemFlag.ItemIsEditable
                    | QtCore.Qt.ItemFlag.ItemIsEnabled
                    | QtCore.Qt.ItemFlag.ItemIsSelectable
                )
                t.setItem(i, _ADV_MCU_COL_GESTURE, left)
                t.setItem(i, _ADV_MCU_COL_ACTION, right)
        for i in range(len(base), n):
            t.setSpan(i, _ADV_MCU_COL_GESTURE, 1, 1)
            t.setSpan(i, _ADV_MCU_COL_ACTION, 1, 1)
            t.setItem(i, _ADV_MCU_COL_GESTURE, QtWidgets.QTableWidgetItem(""))
            t.setItem(i, _ADV_MCU_COL_ACTION, QtWidgets.QTableWidgetItem(""))
        t.blockSignals(False)
        self._advanced_refresh_mcu_row_handles()
        self._advanced_refit_mcu_button_table_height()

    def _advanced_ensure_button_table_growing_rows(self) -> None:
        """Keep at least two trailing blank rows after the last non-empty row (expand row count as needed)."""
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return
        last_nonempty = -1
        for r in range(t.rowCount()):
            if t.columnSpan(r, _ADV_MCU_COL_GESTURE) == 2:
                itg = t.item(r, _ADV_MCU_COL_GESTURE)
                if itg and itg.text().strip():
                    last_nonempty = r
                continue
            it0 = t.item(r, _ADV_MCU_COL_GESTURE)
            it1 = t.item(r, _ADV_MCU_COL_ACTION)
            a = (it0.text() if it0 else "").strip()
            b = (it1.text() if it1 else "").strip()
            if a or b:
                last_nonempty = r
        need = last_nonempty + 1 + 2
        if last_nonempty < 0:
            need = max(need, 5)
        if need > t.rowCount():
            old = t.rowCount()
            t.setRowCount(need)
            for r in range(old, need):
                t.setSpan(r, _ADV_MCU_COL_GESTURE, 1, 1)
                t.setSpan(r, _ADV_MCU_COL_ACTION, 1, 1)
                if t.item(r, _ADV_MCU_COL_GESTURE) is None:
                    t.setItem(r, _ADV_MCU_COL_GESTURE, QtWidgets.QTableWidgetItem(""))
                if t.item(r, _ADV_MCU_COL_ACTION) is None:
                    t.setItem(r, _ADV_MCU_COL_ACTION, QtWidgets.QTableWidgetItem(""))
            self._advanced_refresh_mcu_row_handles()

    def _advanced_mcu_table_sync_width_to_scroll(self) -> None:
        """Match table width to the scroll viewport (avoids empty band + scrollbar gap after resize)."""
        scroll = getattr(self, "_advanced_mcu_buttons_scroll", None)
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(scroll) or not _qt_widget_alive(t):
            return
        vpw = int(scroll.viewport().width())
        if vpw < 1:
            return
        w = max(200, vpw)
        t.setFixedWidth(w)
        t.resizeRowsToContents()

    def _advanced_mcu_on_cell_entered(self, row: int, column: int) -> None:
        """cellEntered fires on hover (mouse tracking) — drives row gutter visibility."""
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t) or row < 0:
            return
        if column in (_ADV_MCU_COL_GESTURE, _ADV_MCU_COL_ACTION, _ADV_MCU_COL_HANDLE):
            self._advanced_mcu_set_visible_gutter_row(row)
        else:
            self._advanced_mcu_set_visible_gutter_row(None)

    def _advanced_mcu_widget_is_descendant_of_table(self, w: Optional[QtWidgets.QWidget]) -> bool:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t) or w is None:
            return False
        x: Optional[QtWidgets.QWidget] = w
        while x is not None:
            if x is t:
                return True
            x = x.parentWidget()
        return False

    def _advanced_mcu_set_visible_gutter_row(self, row: Optional[int]) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return
        self._advanced_mcu_gutter_active_row = row
        for r in range(t.rowCount()):
            grip = t.cellWidget(r, _ADV_MCU_COL_HANDLE)
            if isinstance(grip, _AdvancedMcuRowGutterHandle):
                grip.set_junction_visible(row is not None and r == row)

    def _advanced_mcu_clear_table_selection(self) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return
        t.clearSelection()
        sm = t.selectionModel()
        if sm is not None:
            sm.clearCurrentIndex()
        self._advanced_mcu_set_visible_gutter_row(None)

    def _advanced_mcu_clear_table_selection_if_press_outside(self, global_pos: QtCore.QPoint) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t) or not t.isVisible():
            return
        w = QtWidgets.QApplication.widgetAt(global_pos)
        if w is not None and self._advanced_mcu_widget_is_descendant_of_table(w):
            return
        self._advanced_mcu_clear_table_selection()

    def _advanced_mcu_install_outside_selection_filters(self, fw_group: QtWidgets.QWidget) -> None:
        filt = _AdvancedMcuClearTableSelectionFilter(self)
        self._advanced_mcu_outside_sel_filter = filt
        fw_group.installEventFilter(filt)
        scroll = getattr(self, "_advanced_mcu_buttons_scroll", None)
        for w in fw_group.findChildren(QtWidgets.QWidget):
            if _qt_widget_alive(scroll) and scroll.isAncestorOf(w):
                continue
            w.installEventFilter(filt)
        if _qt_widget_alive(scroll):
            scroll.verticalScrollBar().installEventFilter(filt)

    def _advanced_refit_mcu_button_table_height(self) -> None:
        """Put the table inside a capped-height scroll area; table keeps full content height."""
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        scroll = getattr(self, "_advanced_mcu_buttons_scroll", None)
        if not _qt_widget_alive(t):
            return
        self._advanced_ensure_button_table_growing_rows()
        self._advanced_mcu_table_sync_width_to_scroll()
        if hasattr(t, "setWordWrap"):
            t.setWordWrap(True)
        t.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        t.resizeRowsToContents()
        header = t.horizontalHeader()
        h = header.height() + 2 * t.frameWidth() + 6
        fm = t.fontMetrics()
        min_row_h = max(22, fm.height() + 10)
        for r in range(t.rowCount()):
            rh = t.rowHeight(r)
            if rh <= 0:
                rh = t.sizeHintForRow(r)
            h += max(rh, min_row_h)
        min_table_h = 120
        cap = 560
        win = t.window()
        if isinstance(win, QtWidgets.QWidget) and win.isVisible():
            try:
                cap = max(280, min(620, int(win.height() * 0.52)))
            except Exception:
                pass
        content_h = max(min_table_h, h)
        if _qt_widget_alive(scroll):
            scroll_h = min(content_h, cap)
            scroll.setMinimumHeight(min_table_h)
            scroll.setMaximumHeight(cap)
            scroll.setFixedHeight(scroll_h)
            t.setFixedHeight(content_h)
            scroll.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn
                if content_h > scroll_h + 2
                else QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            QtCore.QTimer.singleShot(0, self._advanced_mcu_table_sync_width_to_scroll)
        else:
            if content_h <= cap:
                t.setFixedHeight(content_h)
                t.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            else:
                t.setFixedHeight(cap)
                t.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

    def _advanced_read_mcu_button_table(self) -> List[List[str]]:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return []
        out: List[List[str]] = []
        for r in range(t.rowCount()):
            if t.columnSpan(r, _ADV_MCU_COL_GESTURE) == 2:
                itg = t.item(r, _ADV_MCU_COL_GESTURE)
                title = (itg.text() if itg else "").strip()
                if title:
                    out.append([ADVANCED_MCU_BTN_SECTION_TAG, title])
                continue
            it0 = t.item(r, _ADV_MCU_COL_GESTURE)
            it1 = t.item(r, _ADV_MCU_COL_ACTION)
            a = (it0.text() if it0 else "").strip()
            b = (it1.text() if it1 else "").strip()
            if a or b:
                out.append([a, b])
        return out

    def _advanced_get_active_custom_install_path(self) -> str:
        """Filesystem path used for custom install (mpremote); mirrors DB legacy key."""
        profiles = self._advanced_custom_profiles_ensure()
        combo = getattr(self, "_advanced_custom_profile_combo", None)
        idx = (
            combo.currentIndex()
            if combo is not None and _qt_widget_alive(combo) and combo.count() > 0
            else self._advanced_active_profile_index()
        )
        if 0 <= idx < len(profiles):
            return (profiles[idx].get("path") or "").strip()
        return (self.db.get_setting("advanced_custom_software_path", "") or "").strip()

    def _advanced_sync_custom_path_setting_to_active_source(self) -> None:
        self.db.set_setting("advanced_custom_software_path", self._advanced_get_active_custom_install_path())

    def _advanced_custom_profiles_ensure(self) -> List[Dict[str, str]]:
        """Load persisted custom-software profiles; migrate legacy single path into one profile."""
        raw = (self.db.get_setting("advanced_custom_profiles_json", "") or "").strip()
        profiles: List[Dict[str, str]] = []
        try:
            data = json.loads(raw) if raw else []
        except Exception:
            data = []
        if isinstance(data, list):
            for i, e in enumerate(data):
                if not isinstance(e, dict):
                    continue
                profiles.append(
                    {
                        "name": str(e.get("name") or f"Profile {i + 1}").strip() or f"Profile {i + 1}",
                        "path": str(e.get("path") or "").strip(),
                        "description": str(e.get("description") or ""),
                        "buttons": str(e.get("buttons") or ""),
                    }
                )
        legacy = (self.db.get_setting("advanced_custom_software_path", "") or "").strip()
        if not profiles and legacy:
            profiles = [
                {
                    "name": "Default",
                    "path": legacy,
                    "description": "",
                    "buttons": "",
                }
            ]
            self.db.set_setting("advanced_custom_profiles_json", json.dumps(profiles))
        return profiles

    def _advanced_custom_profiles_save(self, profiles: List[Dict[str, str]]) -> None:
        self.db.set_setting("advanced_custom_profiles_json", json.dumps(profiles))

    def _advanced_active_profile_index(self) -> int:
        try:
            return max(0, int((self.db.get_setting("advanced_active_custom_profile_index", "0") or "0").strip() or "0"))
        except ValueError:
            return 0

    def _advanced_set_active_profile_index(self, idx: int) -> None:
        self.db.set_setting("advanced_active_custom_profile_index", str(max(0, idx)))

    def _advanced_save_custom_profile_at_index(self, idx: int) -> None:
        """Write the current Microprocessor fields into profiles[idx] and persist."""
        notes_w = getattr(self, "_advanced_mcu_notes_edit", None)
        btn_t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(notes_w) or not _qt_widget_alive(btn_t):
            return
        profiles = self._advanced_custom_profiles_ensure()
        if idx < 0 or idx >= len(profiles):
            return
        profiles[idx]["description"] = notes_w.toPlainText()
        profiles[idx]["buttons"] = self._advanced_button_rows_to_json(self._advanced_read_mcu_button_table())
        self._advanced_custom_profiles_save(profiles)
        self._advanced_sync_custom_path_setting_to_active_source()

    def _flush_advanced_mcu_notes_and_buttons(self) -> None:
        """Persist notes + button reference from the Microprocessor tab (debounced)."""
        notes_w = getattr(self, "_advanced_mcu_notes_edit", None)
        btn_t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(notes_w) or not _qt_widget_alive(btn_t):
            return
        if self._uses_custom_software():
            combo = getattr(self, "_advanced_custom_profile_combo", None)
            if combo is None or not _qt_widget_alive(combo):
                return
            idx = combo.currentIndex()
            self._advanced_save_custom_profile_at_index(idx)
        else:
            self.db.set_setting("advanced_mcu_notes", notes_w.toPlainText())
            self.db.set_setting(
                "advanced_mcu_button_table_json",
                self._advanced_button_rows_to_json(self._advanced_read_mcu_button_table()),
            )
        self._advanced_refit_mcu_button_table_height()

    def _schedule_flush_advanced_mcu_fields(self) -> None:
        t = getattr(self, "_advanced_mcu_flush_timer", None)
        if t is None or not _qt_widget_alive(t):
            t = QtCore.QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._flush_advanced_mcu_notes_and_buttons)
            self._advanced_mcu_flush_timer = t
        else:
            t.stop()
        t.start(450)

    def _on_advanced_mcu_button_table_item_changed(self, *_args) -> None:
        self._schedule_flush_advanced_mcu_fields()
        QtCore.QTimer.singleShot(0, self._advanced_refit_mcu_button_table_height)

    def _on_advanced_mcu_buttons_table_context_menu(self, pos: QtCore.QPoint) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return
        r = t.rowAt(pos.y())
        c = t.columnAt(pos.x())
        if c == _ADV_MCU_COL_HANDLE:
            return
        self._advanced_mcu_open_row_actions_menu(t, r if r >= 0 else 0, t.mapToGlobal(pos))

    def _advanced_mcu_open_row_actions_menu(
        self,
        t: QtWidgets.QTableWidget,
        r: int,
        global_pos: QtCore.QPoint,
    ) -> None:
        """Context menu and gutter button share the same row action set."""
        if t.rowCount() <= 0:
            return
        r = max(0, min(r, t.rowCount() - 1))
        is_section = t.columnSpan(r, _ADV_MCU_COL_GESTURE) == 2
        menu = QtWidgets.QMenu(self)
        act_above = menu.addAction("Insert row above")
        act_below = menu.addAction("Insert row below")
        menu.addSeparator()
        act_sec = menu.addAction("Insert section heading above this row")
        act_mrg = menu.addAction("Merge this row into section heading (two columns → one)")
        act_spl = menu.addAction("Split section into two columns")
        menu.addSeparator()
        act_del = menu.addAction("Delete this row")
        act_mrg.setEnabled(not is_section)
        act_spl.setEnabled(is_section)
        act_del.setEnabled(t.rowCount() > 1)
        chosen = menu.exec(global_pos)
        if chosen == act_above:
            self._advanced_mcu_table_insert_data_row_at(r)
        elif chosen == act_below:
            self._advanced_mcu_table_insert_data_row_at(r + 1)
        elif chosen == act_sec:
            self._advanced_mcu_table_insert_section(r)
        elif chosen == act_mrg:
            self._advanced_mcu_table_merge_row(r)
        elif chosen == act_spl:
            self._advanced_mcu_table_split_row(r)
        elif chosen == act_del:
            self._advanced_mcu_table_delete_row(r)

    def _advanced_mcu_row_junction_menu(self, t: QtWidgets.QTableWidget, r: int) -> None:
        if not _qt_widget_alive(t):
            return
        w = t.cellWidget(r, _ADV_MCU_COL_HANDLE)
        if w is not None:
            gp = w.mapToGlobal(QtCore.QPoint(w.width(), w.height() // 2))
        else:
            idx = t.model().index(r, _ADV_MCU_COL_HANDLE)
            gp = t.mapToGlobal(t.visualRect(idx).center())
        self._advanced_mcu_open_row_actions_menu(t, r, gp)

    def _advanced_mcu_table_insert_section(self, r: int) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return
        row = max(0, min(r, t.rowCount()))
        t.blockSignals(True)
        t.insertRow(row)
        it = QtWidgets.QTableWidgetItem("New heading")
        it.setFlags(
            it.flags()
            | QtCore.Qt.ItemFlag.ItemIsEditable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
        )
        _sec_bg = QColor(38, 38, 40)
        _sec_fg = QColor(240, 240, 242)
        _sf = QFont(it.font())
        _sf.setBold(True)
        it.setFont(_sf)
        it.setBackground(QBrush(_sec_bg))
        it.setForeground(QBrush(_sec_fg))
        t.setSpan(row, _ADV_MCU_COL_GESTURE, 1, 2)
        t.setItem(row, _ADV_MCU_COL_GESTURE, it)
        t.blockSignals(False)
        self._advanced_refresh_mcu_row_handles()
        self._advanced_refit_mcu_button_table_height()
        self._schedule_flush_advanced_mcu_fields()

    def _advanced_mcu_table_insert_data_row_at(self, r: int) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t):
            return
        r = max(0, min(r, t.rowCount()))
        t.blockSignals(True)
        t.insertRow(r)
        t.setSpan(r, _ADV_MCU_COL_GESTURE, 1, 1)
        t.setSpan(r, _ADV_MCU_COL_ACTION, 1, 1)
        left = QtWidgets.QTableWidgetItem("")
        right = QtWidgets.QTableWidgetItem("")
        for it in (left, right):
            it.setFlags(
                it.flags()
                | QtCore.Qt.ItemFlag.ItemIsEditable
                | QtCore.Qt.ItemFlag.ItemIsEnabled
                | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
        t.setItem(r, _ADV_MCU_COL_GESTURE, left)
        t.setItem(r, _ADV_MCU_COL_ACTION, right)
        t.blockSignals(False)
        self._advanced_refresh_mcu_row_handles()
        self._advanced_refit_mcu_button_table_height()
        self._schedule_flush_advanced_mcu_fields()

    def _advanced_mcu_table_delete_row(self, r: int) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t) or r < 0 or r >= t.rowCount():
            return
        if t.rowCount() <= 1:
            return
        if t.cellWidget(r, _ADV_MCU_COL_HANDLE) is not None:
            t.removeCellWidget(r, _ADV_MCU_COL_HANDLE)
        t.removeRow(r)
        self._advanced_refresh_mcu_row_handles()
        self._advanced_refit_mcu_button_table_height()
        self._schedule_flush_advanced_mcu_fields()

    def _advanced_mcu_table_merge_row(self, r: int) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t) or r < 0 or r >= t.rowCount():
            return
        if t.columnSpan(r, _ADV_MCU_COL_GESTURE) == 2:
            return
        it0 = t.item(r, _ADV_MCU_COL_GESTURE)
        it1 = t.item(r, _ADV_MCU_COL_ACTION)
        a = it0.text().strip() if it0 else ""
        b = it1.text().strip() if it1 else ""
        title = a if not b else f"{a} — {b}"
        title = title.strip(" —\u00a0\t")
        if not title:
            return
        t.blockSignals(True)
        if it1 is not None:
            t.takeItem(r, _ADV_MCU_COL_ACTION)
        if it0 is None:
            it0 = QtWidgets.QTableWidgetItem(title)
            t.setItem(r, _ADV_MCU_COL_GESTURE, it0)
        else:
            it0.setText(title)
        _sec_bg = QColor(38, 38, 40)
        _sec_fg = QColor(240, 240, 242)
        it0.setBackground(QBrush(_sec_bg))
        it0.setForeground(QBrush(_sec_fg))
        _sf = QFont(it0.font())
        _sf.setBold(True)
        it0.setFont(_sf)
        t.setSpan(r, _ADV_MCU_COL_GESTURE, 1, 2)
        t.blockSignals(False)
        self._advanced_refit_mcu_button_table_height()
        self._schedule_flush_advanced_mcu_fields()

    def _advanced_mcu_table_split_row(self, r: int) -> None:
        t = getattr(self, "_advanced_mcu_buttons_table", None)
        if not _qt_widget_alive(t) or r < 0 or r >= t.rowCount():
            return
        if t.columnSpan(r, _ADV_MCU_COL_GESTURE) != 2:
            return
        it = t.item(r, _ADV_MCU_COL_GESTURE)
        title = (it.text() if it else "").strip()
        t.blockSignals(True)
        t.setSpan(r, _ADV_MCU_COL_GESTURE, 1, 1)
        t.setSpan(r, _ADV_MCU_COL_ACTION, 1, 1)
        left = QtWidgets.QTableWidgetItem(title)
        left.setFlags(
            left.flags()
            | QtCore.Qt.ItemFlag.ItemIsEditable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
        )
        right = QtWidgets.QTableWidgetItem("")
        right.setFlags(
            right.flags()
            | QtCore.Qt.ItemFlag.ItemIsEditable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
        )
        lf = QFont(left.font())
        lf.setBold(False)
        left.setFont(lf)
        t.setItem(r, _ADV_MCU_COL_GESTURE, left)
        t.setItem(r, _ADV_MCU_COL_ACTION, right)
        t.blockSignals(False)
        self._advanced_refit_mcu_button_table_height()
        self._schedule_flush_advanced_mcu_fields()

    def _load_advanced_mcu_profile_into_ui(self) -> None:
        """Load notes/button table for the current software source + custom source index."""
        notes_w = getattr(self, "_advanced_mcu_notes_edit", None)
        btn_t = getattr(self, "_advanced_mcu_buttons_table", None)
        combo = getattr(self, "_advanced_custom_profile_combo", None)
        if not _qt_widget_alive(notes_w) or not _qt_widget_alive(btn_t):
            return
        default_rows = self._default_advanced_mcu_button_rows()
        if self._uses_custom_software():
            profiles = self._advanced_custom_profiles_ensure()
            idx = combo.currentIndex() if combo is not None and _qt_widget_alive(combo) else 0
            if idx < 0 or idx >= len(profiles):
                idx = 0
            self._advanced_set_active_profile_index(idx)
            if not profiles:
                notes_w.clear()
                self._advanced_fill_mcu_button_table([], prefer_blank=True)
                self._advanced_sync_custom_path_setting_to_active_source()
                return
            p = profiles[idx]
            notes_w.setPlainText(p.get("description") or "")
            rows = self._advanced_parse_button_rows_json(p.get("buttons") or "")
            self._advanced_fill_mcu_button_table(rows, prefer_blank=True)
            self._advanced_sync_custom_path_setting_to_active_source()
        else:
            notes_w.setPlainText(self.db.get_setting("advanced_mcu_notes", "") or "")
            rows = self._advanced_parse_button_rows_json(
                self.db.get_setting("advanced_mcu_button_table_json", "") or ""
            )
            if not rows:
                rows = list(default_rows)
            self._advanced_fill_mcu_button_table(rows, prefer_blank=False)

    def _on_advanced_custom_profile_changed(self, idx: int) -> None:
        prev = getattr(self, "_advanced_profile_combo_last_idx", None)
        if self._uses_custom_software() and prev is not None and prev >= 0:
            self._advanced_save_custom_profile_at_index(prev)
        self._advanced_profile_combo_last_idx = idx
        self._advanced_set_active_profile_index(idx)
        self._load_advanced_mcu_profile_into_ui()

    def _on_advanced_add_software_source(self) -> None:
        start = str(Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose custom software folder",
            start,
        )
        if not folder or not str(folder).strip():
            return
        folder = str(folder).strip()
        name, ok = get_text(
            self,
            "Name this source",
            "Name (shown in Saved custom sources):",
        )
        if not ok or not name.strip():
            return
        profiles = self._advanced_custom_profiles_ensure()
        profiles.append(
            {
                "name": name.strip(),
                "path": folder,
                "description": "",
                "buttons": "",
            }
        )
        self._advanced_custom_profiles_save(profiles)
        self._advanced_set_active_profile_index(len(profiles) - 1)
        self.db.set_setting("advanced_custom_software_path", folder)
        self._rebuild_tabs()

    def _on_advanced_remove_custom_source(self) -> None:
        combo = getattr(self, "_advanced_custom_profile_combo", None)
        if combo is None or not _qt_widget_alive(combo) or combo.count() == 0:
            return
        idx = combo.currentIndex()
        profiles = self._advanced_custom_profiles_ensure()
        if idx < 0 or idx >= len(profiles):
            return
        reply = VintageMessageBox.question(
            self,
            "Remove custom source",
            f"Remove “{profiles[idx].get('name', '')}” from this library?",
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
            VintageMessageBox.StandardButton.No,
        )
        if reply != VintageMessageBox.StandardButton.Yes:
            return
        del profiles[idx]
        self._advanced_custom_profiles_save(profiles)
        new_idx = min(idx, max(0, len(profiles) - 1))
        self._advanced_set_active_profile_index(new_idx)
        if profiles:
            self.db.set_setting(
                "advanced_custom_software_path",
                (profiles[new_idx].get("path") or "").strip(),
            )
        else:
            self.db.set_setting("advanced_custom_software_path", "")
        self._rebuild_tabs()

    def _set_devices_view_mode(self, mode: str) -> None:
        """Set Devices tab view mode, persist, and rebuild tabs."""
        if mode not in ("basic", "advanced", "legacy"):
            return
        old_mode = getattr(self, "devices_view_mode", None)
        self.devices_view_mode = mode
        self.db.set_setting("view_mode", mode)
        self._update_view_menu_checked()

        if old_mode != mode:
            self._rebuild_tabs()

        if hasattr(self, "_devices_stack") and self._devices_stack is not None:
            self._devices_stack.setCurrentIndex(0 if mode in ("basic", "advanced") else 1)
        if mode in ("basic", "advanced") and hasattr(self, "_check_basic_sd_pico_warning"):
            self._check_basic_sd_pico_warning()

    def _sync_tools_developer_mode_action_checked(self) -> None:
        act = getattr(self, "_tools_developer_mode_action", None)
        if act is None:
            return
        act.blockSignals(True)
        act.setChecked(self._developer_mode)
        act.blockSignals(False)

    def _set_developer_mode_from_tools_menu(self, checked: bool) -> None:
        self._set_developer_mode(bool(checked))

    def _set_developer_mode(self, enabled: bool) -> None:
        """Turn developer UI on/off and persist. Stops MCP when turning off."""
        enabled = bool(enabled)
        if enabled == self._developer_mode:
            if enabled and getattr(self, "_dev_menu", None) is None:
                self._install_developer_menu()
            elif not enabled and getattr(self, "_dev_menu", None) is not None:
                self._toggle_mcp_server_from_ui(False)
                self._uninstall_developer_menu()
            return
        self._developer_mode = enabled
        self.db.set_setting("developer_mode", "1" if enabled else "0")
        act = getattr(self, "_tools_developer_mode_action", None)
        if act:
            act.blockSignals(True)
            act.setChecked(enabled)
            act.blockSignals(False)
        if not enabled:
            self._toggle_mcp_server_from_ui(False)
            self._uninstall_developer_menu()
            self.statusBar().showMessage("Developer mode off (MCP stopped).", 4000)
        else:
            self._install_developer_menu()
            self.statusBar().showMessage("Developer mode on.", 4000)

    def _uninstall_developer_menu(self) -> None:
        dev = getattr(self, "_dev_menu", None)
        if dev is None:
            return
        self.menuBar().removeAction(dev.menuAction())
        dev.deleteLater()
        self._dev_menu = None

    def _refresh_mcp_toggle_action_ui(self) -> None:
        if not hasattr(self, "_mcp_toggle_action"):
            return
        running = self._mcp_manager.is_running()
        self._mcp_toggle_action.blockSignals(True)
        self._mcp_toggle_action.setChecked(running)
        if running:
            self._mcp_toggle_action.setText(
                "MCP debug server ON ({}:{})".format("127.0.0.1", self._mcp_port)
            )
        else:
            self._mcp_toggle_action.setText("MCP debug server OFF — click to start")
        self._mcp_toggle_action.blockSignals(False)

    def _mcp_log(self, message: str) -> None:
        print(message)
        write_session_line(message, prefix="MCP")
        w = self._active_debug_widget()
        if w is not None and _qt_widget_alive(w):
            try:
                w._log("[MCP] {}".format(message), "command")
            except Exception:
                pass

    def _mcp_log_acceptance_worker(self, message: str) -> None:
        """Call from acceptance test worker threads; forwards to the GUI log safely."""
        self._mcp_queue_on_gui(lambda m=message: self._mcp_log(m))

    def _mcp_queue_on_gui(self, fn: Callable[[], None]) -> None:
        """Run *fn* on the Qt GUI thread (MCP client runs on a socket thread)."""
        with self._mcp_gui_queue_lock:
            self._mcp_gui_queue.append(fn)
        QtCore.QMetaObject.invokeMethod(
            self,
            "_mcp_drain_gui_queue",
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

    @QtCore.pyqtSlot()
    def _mcp_drain_gui_queue(self) -> None:
        with self._mcp_gui_queue_lock:
            batch = list(self._mcp_gui_queue)
            self._mcp_gui_queue.clear()
        for fn in batch:
            try:
                fn()
            except Exception as e:
                self._mcp_log("MCP GUI queue error: {}".format(e))

    def _mcp_run_on_gui_sync(
        self, fn: Callable[[], Dict[str, Any]], *, wait_s: float = 45.0
    ) -> Dict[str, Any]:
        """Run *fn* on the GUI thread and block the caller until the result is ready."""
        result_box: Dict[str, Any] = {}
        done = threading.Event()

        def _wrap() -> None:
            try:
                result_box["r"] = fn()
            except Exception as e:
                result_box["r"] = {
                    "ok": False,
                    "error": "mcp_gui_exception",
                    "detail": str(e),
                }
            finally:
                done.set()

        self._mcp_queue_on_gui(_wrap)
        if not done.wait(timeout=wait_s):
            return {"ok": False, "error": "mcp_gui_timeout"}
        return result_box.get("r", {"ok": False, "error": "mcp_gui_no_result"})

    def _ensure_device_debug_widget_loaded(self) -> None:
        """GUI thread: instantiate Device Debug widget if the tab exists but is still a placeholder."""
        if self._device_debug_tab_index < 0:
            return
        if self._device_debug_widget is not None:
            return
        layout = getattr(self, "_device_debug_tab_layout", None)
        ph = getattr(self, "_device_debug_placeholder", None)
        if layout is None or ph is None:
            return
        layout.removeWidget(ph)
        ph.deleteLater()
        self._device_debug_placeholder = None
        self._device_debug_widget = DeviceDebugWidget(
            db=self.db,
            db_getter=lambda: self.db,
        )
        layout.addWidget(self._device_debug_widget)

    def _mcp_get_log_path(self) -> Optional[str]:
        p = get_session_log_path()
        return str(p) if p else None

    def _active_debug_widget(self):
        """Prefer the **Device** tab debug widget when it exists.

        MCP / VRTEST / serial streaming for the Pico must use the same widget the user
        connects on the Device tab. The Library tab's *basic* debug widget was checked
        first previously, so ``device_stream_tail`` and ``get_stream_ring_tail`` often
        read an empty ring (only the stream-start tip) while firmware logs went to the
        Device widget — breaking acceptance serial dumps and Now Playing parsing.
        """
        self._ensure_device_debug_widget_loaded()
        for name in ("_device_debug_widget", "_basic_debug_widget"):
            w = getattr(self, name, None)
            if _qt_widget_alive(w):
                return w
        return None

    def _mcp_get_connection_state(self) -> Dict[str, Any]:
        w = self._active_debug_widget()
        if w is None:
            return {"connected": False, "reason": "debug_widget_unavailable"}
        port = ""
        try:
            port = w.port_combo.currentText().strip()
        except Exception:
            pass
        connected = bool(getattr(w, "_connected", False))
        streaming = bool(getattr(w, "_streaming_thread", None)) and not bool(
            getattr(w, "_stop_streaming", False)
        )
        return {"connected": connected, "port": port, "streaming": streaming}

    def _mcp_select_serial_port(self, w: DeviceDebugWidget, port_str: str) -> bool:
        """Select the device combo entry for a port name (e.g. ``COM6``)."""
        if not port_str or not _qt_widget_alive(w):
            return False
        w._scan_ports()  # type: ignore[attr-defined]
        want = port_str.strip().upper().replace(" ", "")
        best_i = -1
        for i in range(w.port_combo.count()):
            data = w.port_combo.itemData(i)
            if not data:
                continue
            dev = str(data).strip().upper()
            if dev == want:
                best_i = i
                break
            if want in dev or dev.endswith(want):
                best_i = i
        if best_i < 0:
            return False
        w.port_combo.setCurrentIndex(best_i)
        return True

    def _mcp_pick_rp2040_port(self, w: DeviceDebugWidget) -> Optional[str]:
        """Scan ports and select the first RP2040/Pico in the combo; return device path or None.

        Call **only** from the Qt GUI thread (e.g. inside a queued slot).
        """
        if not _qt_widget_alive(w):
            return None
        try:
            import serial.tools.list_ports
        except ImportError:
            return None
        w._scan_ports()  # type: ignore[attr-defined]
        for p in serial.tools.list_ports.comports():
            if w._is_rp2040_port(p):
                dev = p.device
                for i in range(w.port_combo.count()):
                    if w.port_combo.itemData(i) == dev:
                        w.port_combo.setCurrentIndex(i)
                        return str(dev)
        return None

    @staticmethod
    def _mcp_resolve_pico_port(port_hint: Optional[str]) -> Optional[str]:
        """Resolve Pico serial path without touching Qt (safe from MCP / socket thread)."""
        if port_hint is not None and str(port_hint).strip():
            return str(port_hint).strip()
        try:
            import serial.tools.list_ports
        except ImportError:
            return None
        for p in serial.tools.list_ports.comports():
            if DeviceDebugWidget._is_rp2040_port(p):
                return str(p.device)
        return None

    def _mcp_ensure_streaming(self, w: DeviceDebugWidget) -> None:
        """Start serial streaming if connected and not already streaming."""
        try:
            if not _qt_widget_alive(w):
                return
            if not getattr(w, "_connected", False):
                return
            if getattr(w, "_stop_streaming", False):
                return
            t = getattr(w, "_streaming_thread", None)
            if t is not None and t.is_alive():
                return
            w._start_streaming()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _mcp_connect_device_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP: pick RP2040 (or ``payload.port``), then connect on the **GUI** thread only."""
        w = self._active_debug_widget()
        if w is None:
            return {"ok": False, "error": "debug_widget_unavailable"}
        raw_port = payload.get("port")
        hint_opt: Optional[str] = None
        if raw_port is not None and str(raw_port).strip():
            hint_opt = str(raw_port).strip()
        auto_stream = payload.get("auto_start_streaming")
        if auto_stream is None:
            auto_stream = True
        auto_stream = bool(auto_stream)

        chosen = self._mcp_resolve_pico_port(hint_opt)
        if not chosen:
            return {
                "ok": False,
                "error": "no_device_found",
                "hint": "Connect Pico via USB or pass payload.port (e.g. COM6).",
            }

        QtCore.QMetaObject.invokeMethod(
            self,
            "_mcp_execute_connect_device",
            QtCore.Qt.ConnectionType.QueuedConnection,
            QtCore.Q_ARG(str, chosen),
            QtCore.Q_ARG(bool, auto_stream),
        )
        return {
            "ok": True,
            "port": chosen,
            "queued": True,
            "note": "Connect is asynchronous; poll get_connection_state within a few seconds.",
            "auto_start_streaming": auto_stream,
        }

    @QtCore.pyqtSlot(str, bool)
    def _mcp_execute_connect_device(self, chosen: str, auto_stream: bool) -> None:
        """GUI thread: select *chosen* in the device combo and open serial (MCP)."""
        self._ensure_device_debug_widget_loaded()
        w = self._active_debug_widget()
        if w is None or not _qt_widget_alive(w):
            self._mcp_log("MCP connect_device: debug widget unavailable on GUI thread")
            return
        w._log("MCP: connect_device ({})".format(chosen), "command")
        w._scan_ports()  # type: ignore[attr-defined]
        idx = -1
        for i in range(w.port_combo.count()):
            data = w.port_combo.itemData(i)
            if data is not None and str(data) == chosen:
                idx = i
                break
        if idx < 0:
            cu = chosen.upper()
            for i in range(w.port_combo.count()):
                data = w.port_combo.itemData(i)
                if data is not None and str(data).upper() == cu:
                    idx = i
                    break
        if idx < 0:
            self._mcp_log(
                "MCP connect_device: {} not found in port list after scan".format(chosen)
            )
            return
        w.port_combo.setCurrentIndex(idx)
        ser = getattr(w, "_serial_connection", None)
        if getattr(w, "_connected", False) and ser is not None and ser.is_open:
            try:
                if str(ser.port) == chosen:
                    if auto_stream:
                        self._mcp_ensure_streaming(w)
                    return
            except Exception:
                pass
        try:
            w._connect()  # type: ignore[attr-defined]
        finally:
            if auto_stream:
                QtCore.QTimer.singleShot(2500, lambda: self._mcp_ensure_streaming(w))

    def _mcp_invoke_action(self, action: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        payload = payload or {}

        if action == "physical_gesture":
            target = str(payload.get("target", "device")).strip().lower()
            gesture = str(payload.get("gesture", "")).strip()
            if not gesture:
                return {"ok": False, "error": "missing_gesture"}
            if target == "emulator":
                return self._mcp_emulator_gesture(gesture)

            def _gesture_fn() -> Dict[str, Any]:
                self._ensure_device_debug_widget_loaded()
                ww = self._active_debug_widget()
                if ww is None:
                    return {"ok": False, "error": "debug_widget_unavailable"}
                ww._log("MCP: physical_gesture {}".format(gesture), "command")
                try:
                    tmo = float(payload.get("timeout", 25.0))
                except (TypeError, ValueError):
                    tmo = 25.0
                # Large basic-mode libraries (e.g. 98 folders) can exceed 120s while hydrating
                # before VRTEST long_press returns; cap high enough for stress / acceptance.
                return ww.run_vrtest_command(gesture, timeout=max(5.0, min(tmo, 900.0)))  # type: ignore[no-any-return]

            try:
                sync_wait = float(payload.get("timeout", 25.0)) + 35.0
            except (TypeError, ValueError):
                sync_wait = 60.0
            return self._mcp_run_on_gui_sync(_gesture_fn, wait_s=max(60.0, sync_wait))
        if action == "device_stream_tail":
            lim = int(payload.get("limit", 200))

            def _tail_fn() -> Dict[str, Any]:
                self._ensure_device_debug_widget_loaded()
                ww = self._active_debug_widget()
                if ww is None:
                    return {"ok": False, "error": "debug_widget_unavailable"}
                return {"ok": True, "lines": ww.get_stream_ring_tail(lim)}  # type: ignore[attr-defined]

            return self._mcp_run_on_gui_sync(_tail_fn)

        def _queue_device_action(label: str, op: Callable[[DeviceDebugWidget], None]) -> Dict[str, Any]:
            def _do() -> None:
                self._ensure_device_debug_widget_loaded()
                ww = self._active_debug_widget()
                if ww is None:
                    self._mcp_log("MCP {}: debug widget unavailable".format(label))
                    return
                ww._log("MCP: {}".format(label), "command")
                op(ww)

            self._mcp_queue_on_gui(_do)
            return {"ok": True, "queued": True}

        if action == "connect_device":
            return self._mcp_connect_device_action(payload)
        if action == "scan_ports":
            return _queue_device_action("scan_ports", lambda ww: ww._scan_ports())  # type: ignore[attr-defined]
        if action == "connect":

            def _op_connect(ww: DeviceDebugWidget) -> None:
                p = payload.get("port")
                if p and str(p).strip():
                    self._mcp_select_serial_port(ww, str(p))
                ww._connect()  # type: ignore[attr-defined]

            return _queue_device_action("connect", _op_connect)
        if action == "disconnect":
            return _queue_device_action("disconnect", lambda ww: ww._disconnect())  # type: ignore[attr-defined]
        if action == "restart_firmware":
            return _queue_device_action(
                "restart_firmware", lambda ww: ww._restart_firmware()  # type: ignore[attr-defined]
            )
        if action == "soft_reset":
            return _queue_device_action("soft_reset", lambda ww: ww._soft_reset())  # type: ignore[attr-defined]
        if action == "start_streaming":
            return _queue_device_action(
                "start_streaming", lambda ww: ww._start_streaming()  # type: ignore[attr-defined]
            )
        if action == "stop_streaming":
            return _queue_device_action(
                "stop_streaming", lambda ww: ww._stop_streaming_forcefully()  # type: ignore[attr-defined]
            )
        if action == "list_files":
            return _queue_device_action("list_files", lambda ww: ww._list_files())  # type: ignore[attr-defined]
        if action == "send_command":
            cmd = str(payload.get("command", "")).strip()
            if not cmd:
                return {"ok": False, "error": "missing_command"}
            timeout = float(payload.get("timeout", 8.0))

            def _send_fn() -> Dict[str, Any]:
                self._ensure_device_debug_widget_loaded()
                ww = self._active_debug_widget()
                if ww is None:
                    return {"ok": False, "error": "debug_widget_unavailable"}
                port_data = ww.port_combo.currentData()
                port = (
                    str(port_data).strip()
                    if port_data is not None and str(port_data).strip()
                    else ww.port_combo.currentText().strip()
                )
                if not port:
                    return {"ok": False, "error": "no_selected_port"}
                ww._log("MCP: send_command {!r}".format(cmd[:120]), "command")
                try:
                    rc, out, err = ww._send_serial_command(  # type: ignore[attr-defined]
                        port, cmd, timeout=timeout
                    )
                    return {"ok": True, "returncode": rc, "stdout": out, "stderr": err}
                except Exception as e:
                    return {"ok": False, "error": "send_failed", "detail": str(e)}

            return self._mcp_run_on_gui_sync(_send_fn, wait_s=max(45.0, timeout + 15.0))
        if action == "install_basic_to_pico":
            # Same file set as Device "Setup Pico" / Install to Pico (basic): main_basic as main.py,
            # radio_core, dfplayer + IPC, pin_config, AM WAV, reboot.
            def _install_fn() -> Dict[str, Any]:
                mpremote_cmd = self._resolve_mpremote_cmd()
                if not mpremote_cmd:
                    return {
                        "ok": False,
                        "error": "mpremote_unavailable",
                        "detail": getattr(self, "_mpremote_bundle_error", None) or "",
                    }
                self._release_serial_if_connected_for_mpremote(log_prefix="MCP_INSTALL")
                root = self._project_root()
                profile = self._get_active_profile_install_params()
                try:
                    msg = MainWindow._install_to_pico_worker(
                        mpremote_cmd,
                        root,
                        self.sd_root,
                        self.sd_manager,
                        progress_callback=None,
                        pin_config_json=profile.get("pin_config_json") or "",
                        custom_hw_driver_path=profile.get("custom_hw_driver_path") or "",
                        basic_mode=True,
                        install_mode=str(profile.get("install_mode") or "basic"),
                        dfplayer_eq=str(profile.get("dfplayer_eq") or "normal"),
                    )
                    self.statusBar().showMessage(str(msg), 8000)
                    return {"ok": True, "message": msg}
                except Exception as e:
                    return {
                        "ok": False,
                        "error": "install_failed",
                        "detail": str(e),
                        "traceback": traceback.format_exc(),
                    }

            return self._mcp_run_on_gui_sync(_install_fn, wait_s=600.0)
        return {"ok": False, "error": "unknown_action", "action": action}

    def _mcp_emulator_gesture(self, gesture: str) -> Dict[str, Any]:
        """Run TestModeWidget gestures on the GUI thread (same RadioCore as firmware)."""
        result: Dict[str, Any] = {}
        done = threading.Event()

        def work() -> None:
            try:
                tw = self.test_mode_widget
                if tw is None:
                    tw = self._ensure_test_mode_widget()
                c = tw.core
                if gesture == "ping":
                    result.update({"ok": True, "device": {"ok": True, "cmd": "ping"}})
                elif gesture == "get_state":
                    playing = bool(getattr(tw, "is_playing", False))
                    st = {
                        "mode": getattr(tw, "mode", c.mode),
                        "current_track": int(getattr(tw, "current_track", c.current_track)),
                        "current_album_index": int(c.current_album_index),
                        "is_playing": playing,
                        "busy_pin": None,
                        "power_on": bool(c.power_on),
                        "tap_count_pending": int(c.tap_count),
                        "button_down": bool(c.button_down),
                    }
                    result.update(
                        {"ok": True, "device": {"ok": True, "cmd": "get_state", "state": st}}
                    )
                elif gesture == "single_tap":
                    tw.single_tap(auto=True)  # type: ignore[attr-defined]
                    result.update({"ok": True, "device": {"ok": True, "cmd": "single_tap"}})
                elif gesture == "double_tap":
                    tw.double_tap()  # type: ignore[attr-defined]
                    result.update({"ok": True, "device": {"ok": True, "cmd": "double_tap"}})
                elif gesture == "triple_tap":
                    tw.triple_tap()  # type: ignore[attr-defined]
                    result.update({"ok": True, "device": {"ok": True, "cmd": "triple_tap"}})
                elif gesture == "four_tap":
                    tw.four_tap()  # type: ignore[attr-defined]
                    result.update({"ok": True, "device": {"ok": True, "cmd": "four_tap"}})
                elif gesture == "five_tap":
                    tw.five_tap()  # type: ignore[attr-defined]
                    result.update({"ok": True, "device": {"ok": True, "cmd": "five_tap"}})
                elif gesture == "long_press":
                    tw.long_press()  # type: ignore[attr-defined]
                    result.update({"ok": True, "device": {"ok": True, "cmd": "long_press"}})
                else:
                    result.update({"ok": False, "error": "unknown_emulator_gesture", "gesture": gesture})
            except Exception as e:
                result.update({"ok": False, "error": str(e)})
            finally:
                done.set()

        QtCore.QTimer.singleShot(0, work)
        if not done.wait(timeout=60.0):
            return {"ok": False, "error": "timeout_waiting_for_gui_thread"}
        return result

    def _install_developer_menu(self) -> None:
        """Create Developer menu when developer mode is on; safe to call if already present."""
        if getattr(self, "_dev_menu", None) is not None:
            return
        self._dev_menu = self.menuBar().addMenu("Developer")
        self._dev_menu.aboutToShow.connect(self._refresh_mcp_toggle_action_ui)
        self._dev_menu.addAction(self._mcp_toggle_action)

        if not hasattr(self, "_mcp_status_action"):
            self._mcp_status_action = QtGui.QAction("Show MCP Status", self)
            self._mcp_status_action.triggered.connect(self._show_mcp_status)
        self._dev_menu.addAction(self._mcp_status_action)

        if not hasattr(self, "_mcp_smoke_action"):
            self._mcp_smoke_action = QtGui.QAction("Run MCP Smoke Script", self)
            self._mcp_smoke_action.triggered.connect(self._run_mcp_smoke_script)
        self._dev_menu.addAction(self._mcp_smoke_action)

        if not hasattr(self, "_mcp_acceptance_action"):
            self._mcp_acceptance_action = QtGui.QAction("Run acceptance suite…", self)
            self._mcp_acceptance_action.triggered.connect(self._run_mcp_acceptance_suite_dialog)
        self._dev_menu.addAction(self._mcp_acceptance_action)

        if not hasattr(self, "_mcp_full_acceptance_action"):
            self._mcp_full_acceptance_action = QtGui.QAction(
                "Run full device acceptance (physical)…", self
            )
            self._mcp_full_acceptance_action.triggered.connect(
                self._run_mcp_full_acceptance_dialog
            )
        self._dev_menu.addAction(self._mcp_full_acceptance_action)

        if not hasattr(self, "_mcp_deploy_ipc_action"):
            self._mcp_deploy_ipc_action = QtGui.QAction(
                "Deploy MCP / VRTEST support to Pico…", self
            )
            self._mcp_deploy_ipc_action.triggered.connect(self._deploy_mcp_support_to_pico)
        self._dev_menu.addAction(self._mcp_deploy_ipc_action)

        self._refresh_mcp_toggle_action_ui()

    def _handle_mcp_toggle_action(self, checked: bool) -> None:
        if not self._developer_mode:
            # Reset check state immediately; this is only a prompt in non-dev mode.
            self._mcp_toggle_action.setChecked(False)
            reply = VintageMessageBox.question(
                self,
                "Developer mode",
                "The MCP debug server is under the Developer menu.\n\n"
                "Turn on Developer mode (saved in preferences) and start the MCP server?",
                VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
                VintageMessageBox.StandardButton.Yes,
            )
            if reply == VintageMessageBox.StandardButton.Yes:
                self._set_developer_mode(True)
                self._toggle_mcp_server_from_ui(True)
            else:
                self.statusBar().showMessage(
                    "MCP not started. Use Tools → Developer mode, or --enable-mcp-debug.",
                    7000,
                )
            return
        self._toggle_mcp_server_from_ui(checked)

    def _toggle_mcp_server_from_ui(self, checked: bool) -> None:
        if checked:
            res = self._mcp_manager.start(port=self._mcp_port)
            if not res.get("ok"):
                self._refresh_mcp_toggle_action_ui()
                VintageMessageBox.warning(
                    self,
                    "MCP Debug Server",
                    "Could not start MCP debug server:\n{}".format(res),
                )
                return
            self._refresh_mcp_toggle_action_ui()
            self.statusBar().showMessage(
                "MCP debug server running on 127.0.0.1:{}".format(self._mcp_port), 5000
            )
        else:
            self._mcp_manager.stop()
            self._refresh_mcp_toggle_action_ui()
            self.statusBar().showMessage("MCP debug server stopped", 3000)

    def _show_mcp_status(self) -> None:
        st = self._mcp_manager.status()
        VintageMessageBox.information(
            self,
            "MCP Debug Status",
            json.dumps(st, indent=2),
        )

    def _run_mcp_smoke_script(self) -> None:
        res = self._mcp_manager.run_script("basic_smoke")
        self._mcp_log("MCP smoke script result: {}".format(res))
        VintageMessageBox.information(self, "MCP Smoke Script", json.dumps(res, indent=2))

    def _mcp_show_acceptance_report_dialog(
        self, suite: Dict[str, Any], *, window_title: str
    ) -> None:
        """Show markdown report on the GUI thread (call via QTimer.singleShot from workers)."""
        if not _qt_widget_alive(self):
            return
        try:
            self.statusBar().clearMessage()
        except Exception:
            pass
        dlg = VintageTextDialog(
            self,
            title=window_title,
            text=str(suite.get("report_markdown", "")),
            read_only=True,
            min_height=360,
            width=_theme.SYNC_MDL_CONFIRM_W + 120,
            buttons=[("Close", "secondary")],
            monospace=True,
        )
        ok = bool(suite.get("ok"))
        self._mcp_log(
            "MCP acceptance finished: ok={} (see report dialog)".format(ok)
        )
        dlg.exec()

    def _run_mcp_acceptance_suite_dialog(self) -> None:
        """Quick/standard/full scripted suite — must not run on the GUI thread (deadlock)."""
        from .mcp_device_acceptance import run_acceptance_suite

        profile, ok = get_item(
            self,
            "Acceptance suite",
            "Profile:",
            ["minimal", "standard", "full"],
            1,
            False,
        )
        if not ok:
            return
        target, ok2 = get_item(
            self,
            "Acceptance suite",
            "Target:",
            ["device", "emulator"],
            0,
            False,
        )
        if not ok2:
            return

        self.statusBar().showMessage(
            "Acceptance suite running in background — watch Device tab / MCP log…",
            0,
        )
        self._mcp_log(
            "Starting acceptance suite (profile={}, target={}) on worker thread…".format(
                profile, target
            )
        )

        def _work() -> None:
            try:
                suite = run_acceptance_suite(
                    invoke=self._mcp_invoke_action,
                    target=target,
                    suite_profile=profile,
                )
            except Exception as e:
                suite = {
                    "ok": False,
                    "report_markdown": "Acceptance suite crashed:\n\n{}".format(e),
                }
            QtCore.QTimer.singleShot(
                0,
                lambda s=suite: self._mcp_show_acceptance_report_dialog(
                    s, window_title="Acceptance suite report"
                ),
            )

        threading.Thread(
            target=_work, daemon=True, name="McpAcceptanceSuite"
        ).start()

    def _run_mcp_full_acceptance_dialog(self) -> None:
        """Comprehensive physical-device suite; logs stream to MCP / Device tab."""
        from .mcp_device_acceptance import run_device_acceptance_full

        confirm = VintageMessageBox.question(
            self,
            "Full device acceptance",
            "Runs the full on-device regression suite — typically 15–35+ minutes "
            "(5 tracks in playlist, shuffle-station, shuffle-library, 3 station changes, "
            "three ~6 s line-in captures, serial checks).\n\n"
            "Progress and Pico serial tails are appended to the MCP / session log "
            "(same place as [MCP] lines). Line-in steps pause logging for several seconds "
            "while the PC records audio — that is normal.\n\n"
            "Keep this window open. Continue?",
            VintageMessageBox.StandardButton.Yes
            | VintageMessageBox.StandardButton.No,
            VintageMessageBox.StandardButton.Yes,
        )
        if confirm != VintageMessageBox.StandardButton.Yes:
            return

        target, ok = get_item(
            self,
            "Full device acceptance",
            "Target:",
            ["device", "emulator"],
            0,
            False,
        )
        if not ok:
            return

        mgr = self._mcp_manager

        def _request(method_name: str, method_params: Dict[str, Any]) -> Dict[str, Any]:
            return mgr._dispatch({"method": method_name, "params": method_params})

        self.statusBar().showMessage(
            "Full device acceptance running — see MCP log for live progress…",
            0,
        )
        self._mcp_log("Starting full device acceptance (target={})…".format(target))

        def _work() -> None:
            try:
                suite = run_device_acceptance_full(
                    invoke=self._mcp_invoke_action,
                    request=_request,
                    target=target,
                    log_fn=self._mcp_log_acceptance_worker,
                )
            except Exception as e:
                suite = {
                    "ok": False,
                    "report_markdown": "Full acceptance crashed:\n\n{}".format(e),
                }
            QtCore.QTimer.singleShot(
                0,
                lambda s=suite: self._mcp_show_acceptance_report_dialog(
                    s, window_title="Full device acceptance report"
                ),
            )

        threading.Thread(
            target=_work, daemon=True, name="McpFullAcceptance"
        ).start()

    def _deploy_mcp_support_to_pico(self) -> None:
        """Push vintage_radio_ipc (+ optional main files) so VRTEST works; MCP TCP server stays on the PC."""
        pico_root = self._project_root() / "firmware" / "pico"
        ipc = pico_root / "components" / "vintage_radio_ipc.py"
        if not ipc.is_file():
            VintageMessageBox.warning(
                self,
                "Deploy MCP / VRTEST support",
                "Could not find firmware file:\n{}".format(ipc),
            )
            return
        mpremote_cmd = self._resolve_mpremote_cmd()
        if not mpremote_cmd:
            bundle_err = getattr(self, "_mpremote_bundle_error", None)
            msg = "mpremote is not available. Install with:\n\npip install mpremote"
            if bundle_err:
                msg += "\n\n({})".format(bundle_err)
            VintageMessageBox.information(self, "Deploy MCP / VRTEST support", msg)
            return

        choice = QtWidgets.QDialog(self)
        choice_lay, choice_footer = begin_sync_modal_dialog(
            choice,
            title="Deploy MCP / VRTEST support to Pico",
            subtitle="Choose what to copy to the connected Pico.",
            min_width=520,
        )
        intro = QtWidgets.QLabel(
            "The MCP debug server runs on this computer. For serial automation (VRTEST), "
            "the Pico needs components/vintage_radio_ipc.py on its flash. "
            "Flashing a UF2 image alone often does not add new components/*.py files."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("background: transparent;")
        choice_lay.addWidget(intro)
        combo = VintageComboBox(
            min_width=280,
            max_width=9999,
            fixed_height=_theme.TOOLS_ACTION_BTN_H,
        )
        combo.addItem(
            "IPC only — components/vintage_radio_ipc.py (fixes ImportError)",
            False,
        )
        combo.addItem(
            "Full — IPC + main.py + main_basic.py from this app (poll_ipc in loop)",
            True,
        )
        choice_lay.addWidget(combo)
        foot = QtWidgets.QLabel(
            "Pico must be connected via USB (mpremote connect auto). "
            "The device will soft-reset after copy."
        )
        foot.setWordWrap(True)
        foot.setStyleSheet("background: transparent;")
        choice_lay.addWidget(foot)
        cancel_btn = ModalButton("Cancel", variant="secondary")
        cancel_btn.clicked.connect(choice.reject)
        deploy_btn = ModalButton("Deploy", variant="primary")
        deploy_btn.clicked.connect(choice.accept)
        choice_footer.add_button(cancel_btn)
        choice_footer.add_button(deploy_btn)
        if choice.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        include_main = bool(combo.currentData())

        dlg = TaskProgressDialog(
            parent=self,
            title="Deploy MCP / VRTEST support",
            func=MainWindow._deploy_mcp_support_worker,
            args=(mpremote_cmd, pico_root, include_main),
        )

        def on_ok(msg: str) -> None:
            self.statusBar().showMessage(str(msg), 8000)
            VintageMessageBox.information(
                self,
                "Deploy MCP / VRTEST support",
                str(msg),
            )

        def on_err(msg: str) -> None:
            VintageMessageBox.warning(
                self,
                "Deploy MCP / VRTEST support",
                msg,
            )

        dlg.on_success = on_ok
        dlg.on_error = on_err
        dlg.exec()

    def _maybe_auto_start_mcp(self) -> None:
        if not self._developer_mode:
            return
        auto = os.environ.get("VINTAGE_RADIO_MCP_AUTOSTART", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if not auto:
            return
        QtCore.QTimer.singleShot(1500, lambda: self._toggle_mcp_server_from_ui(True))

    def _capture_serial_debug_session_for_rebuild(self) -> None:
        """If Device Console is open, remember COM port and release it before the UI is torn down.

        Basic and Advanced views both use ``_basic_debug_widget`` on the Microprocessor tab;
        ``_rebuild_tabs`` recreates that widget, so we disconnect here and reconnect after rebuild.
        """
        self._serial_debug_restore_snapshot = None
        for name in ("_basic_debug_widget", "_device_debug_widget"):
            w = getattr(self, name, None)
            if not _qt_widget_alive(w) or not getattr(w, "_connected", False):
                continue
            port = None
            try:
                port = w.port_combo.currentData()
            except Exception:
                port = None
            if not port:
                try:
                    ser = getattr(w, "_serial_connection", None)
                    if ser is not None and getattr(ser, "is_open", False):
                        port = str(ser.port)
                except Exception:
                    port = None
            if not port:
                try:
                    w._disconnect()
                except Exception:
                    pass
                continue
            thr = getattr(w, "_streaming_thread", None)
            streaming = bool(
                thr and thr.is_alive() and not getattr(w, "_stop_streaming", True)
            )
            self._serial_debug_restore_snapshot = {"port": str(port), "streaming": streaming}
            try:
                w._disconnect()
            except Exception as e:
                write_session_line(
                    "pre-rebuild serial disconnect: {}".format(e),
                    prefix="DEVICE",
                )
            return

    def _apply_serial_debug_restore(self) -> None:
        """GUI thread: reconnect Device Console after ``_rebuild_tabs`` (basic/advanced)."""
        snap = getattr(self, "_serial_debug_restore_snapshot", None)
        if not snap or not snap.get("port"):
            return
        if self.devices_view_mode not in ("basic", "advanced"):
            self._serial_debug_restore_snapshot = None
            return
        port = str(snap["port"])
        want_streaming = bool(snap.get("streaming", True))
        self._serial_debug_restore_snapshot = None

        w = getattr(self, "_basic_debug_widget", None)
        if not _qt_widget_alive(w):
            return
        if getattr(w, "_connected", False):
            return
        if not self._mcp_select_serial_port(w, port):
            self.statusBar().showMessage(
                "View changed: port {} not found — pick it in Device Console and Connect.".format(
                    port
                ),
                8000,
            )
            return
        try:
            w._connect()
        except Exception as e:
            self.statusBar().showMessage(
                "View changed: auto-reconnect failed ({}). Use Connect.".format(e),
                8000,
            )
            return

        if not want_streaming:

            def _maybe_stop_stream() -> None:
                ww = getattr(self, "_basic_debug_widget", None)
                if not _qt_widget_alive(ww):
                    return
                if not getattr(ww, "_connected", False):
                    return
                thr = getattr(ww, "_streaming_thread", None)
                if thr and thr.is_alive():
                    try:
                        ww._toggle_streaming()
                    except Exception:
                        pass

            QtCore.QTimer.singleShot(1400, _maybe_stop_stream)

    def _rebuild_tabs(self) -> None:
        """Tear down the current tab widget and rebuild for the active view mode."""
        # Guard install/setup slots so wiring signals during tab rebuild can't fire an
        # install action. Switching from Basic to Advanced previously triggered an
        # accidental "Install to Pico (Basic Mode)" progress dialog because rebuilding
        # the firmware-version widget could synthesise a clicked() while we connected
        # the install button. The guard is checked at the top of every install slot.
        self._rebuilding_tabs = True
        try:
            self._capture_serial_debug_session_for_rebuild()
            old_central = self.centralWidget()
            # Drop the previous Advanced Tools window (and the debug widget it owned)
            # so the rebuilt tab can construct a fresh one tied to the new widgets.
            old_advanced_tools = getattr(self, "_advanced_tools_dialog", None)
            if old_advanced_tools is not None:
                try:
                    old_advanced_tools.close()
                except Exception:
                    pass
                self._advanced_tools_dialog = None
            self._device_debug_widget = None
            self._sd_card_tab_enter_refresh_done = False
            self._build_tabs()
            if old_central is not None:
                old_central.deleteLater()
            if self.devices_view_mode == "legacy":
                self._refresh_all()
            elif self.devices_view_mode in ("basic", "advanced"):
                QtCore.QTimer.singleShot(200, self._apply_serial_debug_restore)
        finally:
            # Defer flag clear by one event-loop tick so any queued click() emitted
            # during widget setup is processed (and gated) before normal use resumes.
            QtCore.QTimer.singleShot(0, lambda: setattr(self, "_rebuilding_tabs", False))

    # ── Library switcher toolbar ──────────────────────────────

    def _build_library_toolbar(self) -> None:
        """Kept for backwards-compat with the __init__ call sequence.

        The library selector is now an inline bar built by
        ``_build_library_bar_widget()`` and placed inside the page shell, so this
        method intentionally does nothing (no QToolBar is added).
        """
        return

    def _build_library_bar_widget(self) -> QtWidgets.QWidget:
        """Library selector bar — delegates to gui/widgets/library_bar/library_bar.py.

        ── EDIT in gui/theme.py ──────────────────────────────────────────────
        LIBBAR_HEIGHT, LIBBAR_H_MARGINS, LIBBAR_SPACING, LIBBAR_BORDER_W,
        LIBBAR_BTN_RADIUS, LIBBAR_BTN_PADDING, LIBBAR_BTN_FONT_SIZE,
        LIBBAR_COMBO_MIN_W, LIBBAR_COMBO_MAX_W, LIBBAR_COMBO_PADDING,
        LIBBAR_COMBO_RADIUS, LIBBAR_COMBO_FONT_SIZE, LIBBAR_COMBO_ARROW_W,
        LIBBAR_COMBO_ARROW_SIZE, LIBBAR_COMBO_ARROW_H,
        LIBBAR_LABEL_FONT_SIZE, LIBBAR_LABEL_BOLD,
        TOP_BAR_BG, BORDER, TEXT_PRI, TRACK_SEL, COMBO_BG, COMBO_LIST_BG,
        LIGHT_BTN_HOVER, LIGHT_BTN_PRESSED
        ─────────────────────────────────────────────────────────────────────
        """
        bar = _LibraryBar()
        # Alias MainWindow attributes so all existing backend code still works.
        self._lib_combo             = bar.combo
        self._library_heading_label = bar.heading_label
        # Populate the combo with current libraries.
        self._populate_lib_combo()
        # Connect widget signals to existing MainWindow handlers.
        bar.library_changed.connect(self._on_lib_combo_changed)
        bar.new_clicked.connect(self._new_library)
        bar.rename_clicked.connect(self._rename_library)
        bar.delete_clicked.connect(self._delete_library)
        return bar

    def _populate_lib_combo(self) -> None:
        combo = self._lib_combo
        combo.blockSignals(True)
        combo.clear()
        active_slug = self._lib_registry.active_library()
        for lib in self._lib_registry.list_libraries():
            combo.addItem(lib["name"], lib["slug"])
            if lib["slug"] == active_slug:
                combo.setCurrentIndex(combo.count() - 1)
        combo.blockSignals(False)

    def _on_lib_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        slug = self._lib_combo.itemData(index)
        if slug and slug != self._lib_registry.active_library():
            self._switch_library(slug)

    def _new_library(self) -> None:
        name, ok = get_text(
            self, "New Library", "Library name:"
        )
        if not ok or not name.strip():
            return
        try:
            slug = self._lib_registry.create_library(name.strip())
        except ValueError as e:
            VintageMessageBox.warning(self, "New Library", str(e))
            return
        self._populate_lib_combo()
        self._switch_library(slug)

    def _rename_library(self) -> None:
        slug = self._lib_registry.active_library()
        old_name = self._lib_registry.active_library_name()
        name, ok = get_text(
            self, "Rename Library", "New name:", text=old_name
        )
        if not ok or not name.strip() or name.strip() == old_name:
            return
        self._lib_registry.rename_library(slug, name.strip())
        self._populate_lib_combo()
        self._update_window_title()

    def _delete_library(self) -> None:
        slug = self._lib_registry.active_library()
        name = self._lib_registry.active_library_name()
        libs = self._lib_registry.list_libraries()
        if len(libs) <= 1:
            VintageMessageBox.information(
                self, "Delete Library", "Cannot delete the only library."
            )
            return
        reply = VintageMessageBox.warning(
            self,
            "Delete Library",
            f"Permanently delete library \"{name}\" and all its data?\n\nThis cannot be undone.",
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.Cancel,
            VintageMessageBox.StandardButton.Cancel,
        )
        if reply != VintageMessageBox.StandardButton.Yes:
            return
        with self._wait_cursor_scope():
            self.db.close()
            self._lib_registry.delete_library(slug)
            new_slug = self._lib_registry.active_library()
            self.db = DatabaseManager(db_path=self._lib_registry.db_path_for(new_slug))
            self._propagate_db()
            self._populate_lib_combo()
            self._apply_saved_settings()
            self._normalize_sidebar_view_mode()
            self._refresh_all()
            self._update_window_title()
            if hasattr(self, "test_mode_widget") and self.test_mode_widget:
                self.test_mode_widget.refresh_from_db()
            self._sd_card_tab_enter_refresh_done = False

    @contextmanager
    def _wait_cursor_scope(self) -> Iterator[None]:
        """Show the busy cursor while a potentially slow UI-blocking operation runs."""
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
            app.processEvents()
        try:
            yield
        finally:
            if app is not None:
                app.restoreOverrideCursor()

    def _switch_library(self, slug: str) -> None:
        """Close the current DB, open the one for *slug*, and refresh everything."""
        if slug == self._lib_registry.active_library():
            return
        with self._wait_cursor_scope():
            self.db.close()
            self._cancel_basic_tracks_load()
            self._song_path_missing_cache.clear()
            self._lib_registry.set_active(slug)
            self.db = DatabaseManager(db_path=self._lib_registry.db_path_for(slug))
            self._propagate_db()
            self._populate_lib_combo()
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._apply_saved_settings()
            self._normalize_sidebar_view_mode()
            self._refresh_all()
            self._update_window_title()
            if hasattr(self, "test_mode_widget") and self.test_mode_widget:
                self.test_mode_widget.refresh_from_db()
            self._sd_card_tab_enter_refresh_done = False

    def _propagate_db(self) -> None:
        """Push the current self.db to all sub-components that hold a reference."""
        self.sd_manager.db = self.db
        if hasattr(self, "test_mode_widget") and self.test_mode_widget:
            self.test_mode_widget.db = self.db
            if hasattr(self.test_mode_widget, "hw_emulator"):
                self.test_mode_widget.hw_emulator.db = self.db
            if hasattr(self.test_mode_widget, "sd_manager"):
                self.test_mode_widget.sd_manager.db = self.db
        w = getattr(self, "_basic_debug_widget", None)
        if w is not None:
            w.set_library_db(self.db)
        w = getattr(self, "_device_debug_widget", None)
        if w is not None:
            w.set_library_db(self.db)

    def _update_window_title(self) -> None:
        name = self._lib_registry.active_library_name()
        self.setWindowTitle(f"Vintage Radio Music Manager - {name}")

    def _sync_startup_chrome(self) -> None:
        """Refresh title bar, SD path label, and Windows caption tint after first layout."""
        self._update_window_title()
        self._update_sd_root_label()
        if _qt_widget_alive(getattr(self, "_basic_sd_capacity_bar", None)):
            self._refresh_basic_sd_capacity()
        from gui.window_chrome import ensure_native_caption_colors

        ensure_native_caption_colors(self)

    def _build_tabs(self) -> None:
        if self.devices_view_mode in ("basic", "advanced"):
            self._build_basic_shell()
            self._start_theme_watcher()   # dev-mode live reload (no-op in production)
            return

        tabs = QtWidgets.QTabWidget()
        self._tabs_widget = tabs
        tabs.addTab(self._build_library_tab(), "Library")
        tabs.addTab(self._build_albums_tab(), "Albums")
        tabs.addTab(self._build_playlists_tab(), "Playlists")
        tabs.addTab(self._build_sd_tab(), "Devices")
        tabs.addTab(self._ensure_test_mode_widget(), "Emulator")
        device_tab_container = self._build_device_debug_tab()
        self._device_debug_tab_index = tabs.count()
        tabs.addTab(device_tab_container, "Device Debug")

        tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(tabs)

    # Page indices in the basic/advanced sidebar shell.
    _PAGE_LOAD_MUSIC = 0
    _PAGE_INSTALL_FW = 1
    _PAGE_TOOLS = 2
    _PAGE_SETTINGS = 3
    _PAGE_HELP = 4

    # ═══════════════════════════════════════════════════════════════════════════
    # DEV-MODE THEME LIVE RELOAD
    #
    # Active only when the app is launched with  --dev  (never in production).
    # How it works:
    #   1. QFileSystemWatcher watches gui/theme.py for changes.
    #   2. On save, importlib reloads the module so gui.theme.* values update.
    #   3. Sidebar, library bar, and the current page are rebuilt from scratch.
    #
    # To use:
    #   python run_vintage_radio.py --dev
    #   Open gui/theme.py in your editor, change a value, save.
    #   Shell chrome + current page update within ~0.5 s.
    # ═══════════════════════════════════════════════════════════════════════════

    def _start_theme_watcher(self) -> None:
        """Start watching gui/theme.py for changes (dev mode only)."""
        if not self._ui_dev_mode:
            return
        theme_path = Path(__file__).parent / "theme.py"
        if not theme_path.exists():
            return
        self._theme_watcher = QtCore.QFileSystemWatcher([str(theme_path)], self)
        self._theme_watcher.fileChanged.connect(self._on_theme_file_changed)
        print(f"[DEV] Theme live-reload active — watching {theme_path}")

    def _on_theme_file_changed(self, path: str) -> None:
        """Called when theme.py is saved. Reload theme and rebuild shell + page."""
        import importlib
        try:
            importlib.reload(_theme)
        except Exception as exc:
            print(f"[DEV] theme.py reload error: {exc}")
            return

        # Re-watch the file (editors often replace-write rather than modify in place)
        if self._theme_watcher:
            self._theme_watcher.addPath(path)

        print("[DEV] theme.py reloaded — rebuilding sidebar, library bar, and page …")
        self._reload_dev_theme_ui()
        print("[DEV] Theme reload complete.")

    def _reload_app_theme_ui(self) -> None:
        """Rebuild chrome and pages after the user selects a different colour theme."""
        self._reload_dev_theme_ui()
        self._apply_ui_zoom_to_themed_pages()
        self._refresh_status_bar_theme()
        footer_ver = getattr(self, "_footer_version_label", None)
        if _qt_widget_alive(footer_ver):
            footer_ver.setStyleSheet(self._footer_version_stylesheet())
        from gui.window_chrome import schedule_native_caption_colors

        schedule_native_caption_colors(self)

    def _refresh_status_bar_theme(self) -> None:
        """Re-apply footer / zoom control colours after a palette change."""
        sb = self.statusBar()
        if sb is None:
            return
        sb.setFixedHeight(_theme.FOOTER_H)
        sb.setStyleSheet(f"""
            QStatusBar {{
                background: {_theme.FOOTER_BG};
                border-top: 1px solid {_theme.FOOTER_BORDER};
                color: {_theme.FOOTER_TEXT};
                font-size: {_ui_scale.px(_theme.FOOTER_FONT_SIZE)}px;
            }}
            QStatusBar::item {{
                border: none;
            }}
        """)
        zoom_qss = f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {_theme.ZOOM_BTN_GRAD_TOP},
                    stop:1 {_theme.ZOOM_BTN_GRAD_BOT});
                border: 1px solid {_theme.ZOOM_BTN_BORDER};
                border-radius: {_theme.ZOOM_BTN_RADIUS}px;
                color: {_theme.FOOTER_TEXT};
                font-weight: bold;
                font-size: {_ui_scale.px(_theme.FOOTER_FONT_SIZE)}px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {_theme.ZOOM_BTN_GRAD_BOT},
                    stop:1 {_theme.ZOOM_BTN_GRAD_TOP});
            }}
            QPushButton:pressed {{
                background: {_theme.ZOOM_BTN_GRAD_BOT};
            }}
        """
        label_qss = (
            f"color: {_theme.FOOTER_TEXT}; "
            f"font-size: {_ui_scale.px(_theme.FOOTER_FONT_SIZE)}px;"
        )
        for w in sb.findChildren(QtWidgets.QPushButton):
            w.setStyleSheet(zoom_qss)
            w.setFixedSize(_theme.ZOOM_BTN_W, _theme.ZOOM_BTN_H)
        for w in sb.findChildren(QtWidgets.QLabel):
            if w is not getattr(self, "_footer_version_label", None):
                w.setStyleSheet(label_qss)

    def _reload_dev_theme_open_modals(self) -> None:
        """Refresh any open sync modals and the native caption bar."""
        from gui.window_chrome import apply_native_caption_colors, schedule_native_caption_colors

        app = QtWidgets.QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                if w is self or not w.isVisible():
                    continue
                if hasattr(w, "reload_theme"):
                    w.reload_theme()
        schedule_native_caption_colors(self)

    def _reload_dev_theme_ui(self) -> None:
        """Rebuild sidebar, library bar, all pages, and popup styles."""
        central = self.centralWidget()
        if _qt_widget_alive(central):
            central.setStyleSheet(f"#appRoot {{ background: {_theme.C_BG}; }}")

        right = getattr(self, "_right_pane", None)
        if _qt_widget_alive(right):
            right.setStyleSheet(f"#rightPane {{ background: {_theme.C_BG}; }}")

        stack = getattr(self, "_page_stack", None)
        if _qt_widget_alive(stack):
            stack.setStyleSheet(f"QStackedWidget {{ background: {_theme.C_BG}; }}")

        lib_wrap = central.findChild(QtWidgets.QWidget, "libBarWrap") if _qt_widget_alive(central) else None
        if _qt_widget_alive(lib_wrap):
            lib_wrap.setStyleSheet("#libBarWrap { background: transparent; }")
            lay = lib_wrap.layout()
            if lay is not None:
                lay.setContentsMargins(
                    _theme.LIBBAR_WRAP_L, _theme.LIBBAR_WRAP_T,
                    _theme.LIBBAR_WRAP_R, _theme.LIBBAR_WRAP_B,
                )

        self._dev_rebuild_sidebar()
        self._dev_rebuild_library_bar()
        self._dev_rebuild_all_pages()
        install_vintage_popup_styles()
        self._reload_dev_theme_open_modals()

    def _dev_rebuild_sidebar(self) -> None:
        """Swap in a fresh Sidebar widget (picks up SIDEBAR_* / S_* from theme)."""
        old = getattr(self, "_sidebar", None)
        if not _qt_widget_alive(old):
            return
        parent = old.parentWidget()
        layout = parent.layout() if parent else None
        if layout is None:
            return

        stack = getattr(self, "_page_stack", None)
        nav_idx = stack.currentIndex() if _qt_widget_alive(stack) else self._PAGE_LOAD_MUSIC

        new = self._build_sidebar()
        new.set_active(nav_idx)

        idx = layout.indexOf(old)
        layout.removeWidget(old)
        layout.insertWidget(idx, new)
        old.deleteLater()
        self._sidebar = new

    def _dev_rebuild_library_bar(self) -> None:
        """Swap in a fresh LibraryBar (picks up LIBBAR_* from theme)."""
        old = getattr(self, "_library_bar", None)
        if not _qt_widget_alive(old):
            return
        parent = old.parentWidget()
        layout = parent.layout() if parent else None
        if layout is None:
            return

        visible = old.isVisible()
        active_slug = self._lib_registry.active_library()

        new = self._build_library_bar_widget()
        new.setVisible(visible)

        # Restore the library selection without triggering a switch.
        combo = self._lib_combo
        if _qt_widget_alive(combo):
            for i in range(combo.count()):
                if combo.itemData(i) == active_slug:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(i)
                    combo.blockSignals(False)
                    break

        idx = layout.indexOf(old)
        layout.removeWidget(old)
        layout.insertWidget(idx, new)
        old.deleteLater()
        self._library_bar = new

    def _dev_rebuild_current_page(self) -> None:
        """Rebuild the visible page in the stack."""
        stack = getattr(self, "_page_stack", None)
        if not _qt_widget_alive(stack):
            return

        page_idx = stack.currentIndex()
        rebuilders = {
            self._PAGE_LOAD_MUSIC: self._build_basic_sd_card_tab,
            self._PAGE_INSTALL_FW: self._build_basic_mcu_tab,
            self._PAGE_TOOLS: self._build_tools_page,
            self._PAGE_SETTINGS: self._build_settings_page,
        }
        builder = rebuilders.get(page_idx)
        if builder is None:
            w = stack.widget(page_idx)
            if w and hasattr(w, "reload_theme"):
                w.reload_theme()
            return

        old = stack.widget(page_idx)
        new = builder()
        stack.insertWidget(page_idx, new)
        stack.setCurrentIndex(page_idx)
        if old:
            stack.removeWidget(old)
            old.deleteLater()

        # Refresh data on the rebuilt Load Music page.
        if page_idx == self._PAGE_LOAD_MUSIC:
            self._refresh_basic_station_list()
            self._update_basic_stations_size()
            self._refresh_basic_sd_capacity()

    def _dev_rebuild_all_pages(self) -> None:
        """Rebuild every page in the stack so all cached styles pick up the new palette."""
        stack = getattr(self, "_page_stack", None)
        if not _qt_widget_alive(stack):
            return

        current = stack.currentIndex()
        rebuilders = {
            self._PAGE_LOAD_MUSIC: self._build_basic_sd_card_tab,
            self._PAGE_INSTALL_FW: self._build_basic_mcu_tab,
            self._PAGE_TOOLS: self._build_tools_page,
            self._PAGE_SETTINGS: self._build_settings_page,
            self._PAGE_HELP: self._build_help_page,
        }
        for page_idx, builder in rebuilders.items():
            old = stack.widget(page_idx)
            new = builder()
            stack.insertWidget(page_idx, new)
            if old is not None:
                stack.removeWidget(old)
                old.deleteLater()
        stack.setCurrentIndex(current)
        if current == self._PAGE_LOAD_MUSIC:
            self._refresh_basic_station_list()
            self._update_basic_stations_size()
            self._refresh_basic_sd_capacity()

    def _build_basic_shell(self) -> None:
        """Basic/advanced layout: left sidebar nav + library bar + page stack."""
        # Hide the traditional menu bar — navigation lives in the sidebar.
        self.menuBar().setVisible(False)

        # Devices tab (advanced) is not built; sd_root_label may point at a QLabel
        # destroyed when switching from advanced — clear stale refs.
        if not _qt_widget_alive(getattr(self, "sd_root_label", None)):
            self.sd_root_label = None

        central = QtWidgets.QWidget()
        central.setObjectName("appRoot")
        central.setStyleSheet(f"#appRoot {{ background: {_theme.C_BG}; }}")
        outer = QtWidgets.QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._sidebar = self._build_sidebar()
        outer.addWidget(self._sidebar)

        right = QtWidgets.QWidget()
        right.setObjectName("rightPane")
        self._right_pane = right
        right.setStyleSheet(f"#rightPane {{ background: {_theme.C_BG}; }}")
        right_v = QtWidgets.QVBoxLayout(right)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(0)

        self._library_bar = self._build_library_bar_widget()
        # Wrap in a container so the bar has the same margins as the HTML mockup:
        # left:26px; top:13px; right:17px — matching .library-bar positioning.
        _lib_wrap = QtWidgets.QWidget()
        _lib_wrap.setObjectName("libBarWrap")
        _lib_wrap.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        _lib_wrap.setStyleSheet("#libBarWrap { background: transparent; }")
        _lw = QtWidgets.QVBoxLayout(_lib_wrap)
        _lw.setContentsMargins(
            _theme.LIBBAR_WRAP_L, _theme.LIBBAR_WRAP_T,
            _theme.LIBBAR_WRAP_R, _theme.LIBBAR_WRAP_B,
        )
        _lw.setSpacing(0)
        _lw.addWidget(self._library_bar)
        right_v.addWidget(_lib_wrap)

        stack = QtWidgets.QStackedWidget()
        self._page_stack = stack
        self._apply_page_stack_background(stack)
        stack.setStyleSheet(f"QStackedWidget {{ background: {_theme.C_BG}; }}")
        self._tabs_widget = stack  # keep downstream references working
        stack.addWidget(self._build_basic_sd_card_tab())   # 0 Load Music
        stack.addWidget(self._build_basic_mcu_tab())        # 1 Install Firmware
        stack.addWidget(self._build_tools_page())           # 2 Tools
        stack.addWidget(self._build_settings_page())        # 3 Settings
        stack.addWidget(self._build_help_page())            # 4 Help
        self._device_debug_tab_index = -1
        stack.currentChanged.connect(self._on_tab_changed)
        right_v.addWidget(stack, 1)

        outer.addWidget(right, 1)
        self.setCentralWidget(central)

        stack.setCurrentIndex(self._PAGE_LOAD_MUSIC)
        if getattr(self, "_nav_buttons", None):
            self._nav_buttons[self._PAGE_LOAD_MUSIC].setChecked(True)

    # ═══════════════════════════════════════════════════════════════════════════
    # SIDEBAR — navigation rail
    #
    # Icons are Unicode glyphs rendered into QPixmaps.
    # To swap an icon: change the glyph character in _SIDEBAR_GLYPHS.
    # To add a page: add an entry to _SIDEBAR_GLYPHS, _build_sidebar's
    # nav_specs, and a new stack.addWidget() call in _build_basic_shell.
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Icon glyphs (Unicode characters rendered as warm-cream bitmaps) ───────
    # Replace any character here to change what icon is shown for that nav item.
    _SIDEBAR_GLYPHS = [
        "\u266b",   # 0 Load Music      ♫  (music beam notes)
        "\u2193",   # 1 Install Firmware ↓  (downward arrow)
        "\u2692",   # 2 Tools            ⚒  (hammer and pick)
        "\u2699",   # 3 Settings         ⚙  (gear)
        "?",        # 4 Help             ?
    ]

    @staticmethod
    def _make_sidebar_icon(glyph: str, size: int = 36,
                           color: str = _S_TEXT) -> "QtGui.QIcon":
        """Render a Unicode glyph as a coloured QIcon for use in the sidebar.

        ── EDIT ──────────────────────────────────────────────────────────────
        • Icon canvas size (square px)  → size parameter default
        • Glyph fill fraction           → the 0.78 multiplier in setPixelSize
        • Normal icon colour            → color parameter default (_S_TEXT)
        • Active icon colour            → "#ffffff" passed in _make_sidebar_icon_active
        ──────────────────────────────────────────────────────────────────────
        """
        pix = QtGui.QPixmap(size, size)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        font = QtGui.QFont()
        font.setPixelSize(max(16, int(size * 0.78)))  # glyph size relative to canvas
        painter.setFont(font)
        painter.setPen(QtGui.QColor(color))
        painter.drawText(pix.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()
        return QtGui.QIcon(pix)

    @staticmethod
    def _make_sidebar_icon_active(glyph: str, size: int = 36) -> "QtGui.QIcon":
        """White variant of the glyph icon used when the button is checked."""
        return MainWindow._make_sidebar_icon(glyph, size, color="#ffffff")

    def _build_sidebar(self) -> QtWidgets.QWidget:
        """Left navigation rail — delegates to gui/widgets/sidebar.py.

        ── EDIT in gui/theme.py ──────────────────────────────────────────────
        SIDEBAR_WIDTH, SIDEBAR_MARGINS, SIDEBAR_SPACING,
        SIDEBAR_BTN_RADIUS, SIDEBAR_BTN_PADDING, SIDEBAR_BTN_FONT_SIZE,
        SIDEBAR_BTN_FONT_WEIGHT, SIDEBAR_BTN_MIN_H,
        SIDEBAR_ICON_SIZE, SIDEBAR_ICON_FILL,
        S_BG, S_TEXT, S_ACTIVE, S_HOVER_TINT

        ── EDIT glyph icons in gui/widgets/sidebar/sidebar.py ───────────────
        GLYPHS list and LABELS list at the top of that file.
        ─────────────────────────────────────────────────────────────────────
        """
        bar = _Sidebar()
        # Alias MainWindow attributes so all existing backend code still works.
        self._nav_buttons      = bar.buttons
        self._nav_button_group = bar.button_group
        # Connect the single page_changed signal to the existing handler.
        bar.page_changed.connect(self._on_sidebar_nav)
        return bar

    def _apply_page_stack_background(self, stack: QtWidgets.QStackedWidget) -> None:
        """Opaque page-stack fill avoids 1px hairlines when switching views."""
        pal = stack.palette()
        bg = QtGui.QColor(_theme.C_BG)
        pal.setColor(QtGui.QPalette.ColorRole.Window, bg)
        pal.setColor(QtGui.QPalette.ColorRole.Base, bg)
        stack.setPalette(pal)
        stack.setAutoFillBackground(True)

    def _on_sidebar_nav(self, index: int) -> None:
        """Switch the page stack and toggle library-bar visibility."""
        stack = getattr(self, "_page_stack", None)
        if stack is None:
            return
        stack.setCurrentIndex(index)
        current = stack.currentWidget()
        if current is not None:
            current.update()
        stack.update()
        right = getattr(self, "_right_pane", None)
        if _qt_widget_alive(right):
            right.update()
        bar = getattr(self, "_library_bar", None)
        if _qt_widget_alive(bar):
            bar.setVisible(index not in (self._PAGE_SETTINGS, self._PAGE_HELP))

    def _build_tools_page(self) -> QtWidgets.QWidget:
        page = _ToolsPage()
        page.embed_debug_widget(self._ensure_device_debug_widget())
        page.set_on_micropython_install(self._show_install_micropython_dialog)
        self._tools_page = page
        return page

    def _ensure_device_debug_widget(self) -> DeviceDebugWidget:
        """Single DeviceDebugWidget instance — embedded on the Tools tab."""
        w = getattr(self, "_basic_debug_widget", None)
        if _qt_widget_alive(w):
            return w
        holder = getattr(self, "_basic_debug_widget_holder", None)
        if not _qt_widget_alive(holder):
            holder = QtWidgets.QWidget(self)
            holder.setVisible(False)
            holder.setFixedSize(0, 0)
            self._basic_debug_widget_holder = holder
        w = DeviceDebugWidget(
            parent=holder,
            basic_mode=True,
            db=self.db,
            db_getter=lambda: self.db,
        )
        self._basic_debug_widget = w
        w.device_presence_changed.connect(self._set_basic_device_presence_indicator)
        return w

    def _build_settings_page(self) -> QtWidgets.QWidget:
        page = _SettingsPage(
            auto_eject_checked=self.db.get_setting("auto_eject_after_sync", "0") == "1",
            conversion_profile=self._selected_conversion_profile(),
            retain_conversion_cache=self._retain_conversion_cache(),
            experimental_fast_sync=self._experimental_fast_sync_enabled(),
            sd_image_reuse_when_unchanged=self._sd_image_reuse_when_unchanged_enabled(),
            auto_backup=self.db.auto_backup,
            backup_retention=self.db.backup_retention,
            sd_auto_detect=self.sd_auto_detect,
            ui_zoom_level=self._ui_zoom_level,
            ui_theme=getattr(self, "_ui_theme", "vintage"),
        )
        self._settings_page = page
        self._settings_auto_eject_cb = page.auto_eject_checkbox
        self._settings_conversion_profile_combo = page.conversion_profile_combo
        page.conversion_profile_combo.currentIndexChanged.connect(
            self._on_conversion_profile_changed
        )
        page.retain_conversion_cache_changed.connect(
            self._on_retain_conversion_cache_changed
        )
        page.clear_conversion_cache_clicked.connect(
            self._on_clear_conversion_cache_clicked
        )
        page.experimental_fast_sync_changed.connect(
            self._on_experimental_fast_sync_changed
        )
        page.sd_image_reuse_when_unchanged_changed.connect(
            self._on_sd_image_reuse_when_unchanged_changed
        )
        page.auto_eject_changed.connect(self._on_auto_eject_after_sync_changed)
        page.auto_backup_changed.connect(self._on_settings_auto_backup_changed)
        page.backup_retention_changed.connect(self._on_settings_backup_retention_changed)
        page.sd_auto_detect_changed.connect(self._on_settings_sd_auto_detect_changed)
        page.ui_zoom_changed.connect(self._on_settings_ui_zoom_changed)
        page.ui_theme_changed.connect(self._on_settings_ui_theme_changed)
        return page

    def _build_help_page(self) -> QtWidgets.QWidget:
        page = _HelpPage(app_version=__version__)
        self._help_page = page
        page.view_session_log_clicked.connect(self._view_session_log)
        page.open_logs_folder_clicked.connect(self._open_logs_folder)
        page.copy_log_path_clicked.connect(self._copy_log_path)
        page.reenable_track_warning_clicked.connect(self._reenable_basic_track_count_warning)
        page.check_updates_clicked.connect(self._check_for_updates_menu)
        page.about_clicked.connect(self._show_about)
        return page

    def _ensure_test_mode_widget(self) -> TestModeWidget:
        """Create emulator widget lazily so basic view does not start hidden playback."""
        if self.test_mode_widget is None:
            self.test_mode_widget = TestModeWidget(self.db)
        return self.test_mode_widget

    def _build_device_debug_tab(self) -> QtWidgets.QWidget:
        """Build Device Debug tab with optional SD/library out-of-sync warning."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        self.device_sync_warning = QtWidgets.QLabel()
        self.device_sync_warning.setWordWrap(True)
        self.device_sync_warning.setStyleSheet("color: #b07800; font-weight: bold;")
        self.device_sync_warning.setVisible(False)
        layout.addWidget(self.device_sync_warning)
        self._device_debug_placeholder = QtWidgets.QLabel("Loading Device Debug...")
        layout.addWidget(self._device_debug_placeholder)
        self._device_debug_tab_container = container
        self._device_debug_tab_layout = layout
        return container

    def _build_basic_mcu_tab(self) -> QtWidgets.QWidget:
        """Install Firmware tab — device status, software list, notes, install actions."""
        page = _InstallFirmwarePage()

        # Device debugger lives on the Tools tab; ensure it exists for presence polling.
        self._ensure_device_debug_widget()

        # Aliases for presence + device picker updates.
        dev = page.device_section
        self._basic_device_title_label = dev.title_label
        self._basic_device_meta_label = dev.meta_label
        self._basic_device_status_pill = dev.status_pill
        self._basic_choose_device_btn = dev.choose_device_btn
        self._basic_install_firmware_btn = page.detail_panel.install_btn
        self._install_firmware_page = page

        dev.refresh_clicked.connect(self._on_refresh_device_clicked)
        dev.choose_device_clicked.connect(self._on_choose_device_clicked)
        page.mode_tabs.mode_changed.connect(self._on_firmware_mode_changed)
        page.firmware_list.add_custom_clicked.connect(self._on_add_custom_firmware_menu)
        page.firmware_list.selection_changed.connect(self._on_firmware_selection_changed)
        page.detail_panel.view_firmware_notes_clicked.connect(
            self._on_view_firmware_notes_clicked
        )
        page.detail_panel.edit_user_notes_clicked.connect(self._on_edit_user_notes_clicked)
        page.detail_panel.remove_clicked.connect(self._on_firmware_remove_selected)
        page.detail_panel.add_custom_clicked.connect(self._on_add_custom_firmware_menu)
        page.detail_panel.install_clicked.connect(self._on_install_selected_firmware)

        saved_mode = (self.db.get_setting("install_firmware_tab_mode", "") or "official").strip()
        page.set_firmware_mode(saved_mode if saved_mode in ("official", "custom") else "official")
        self._refresh_firmware_list_ui()
        self._set_basic_device_presence_indicator(self._basic_device_usb_present())
        self._refresh_basic_choose_device_visibility()
        return page

    def _basic_device_usb_present(self) -> bool:
        has_usb = SDManager.is_rp2040_bootsel_present()
        try:
            import serial.tools.list_ports as list_ports

            has_usb = has_usb or any(
                DeviceDebugWidget._is_rp2040_port(port_info)
                for port_info in list_ports.comports()
            )
        except Exception:
            pass
        return bool(has_usb)

    def _basic_install_device_banner(self) -> Tuple[bool, str, str, str, bool]:
        """Return (detected, title, status_pill, meta_line, status_pill_on)."""
        bootsel = SDManager.is_rp2040_bootsel_present()
        rp_ports = _list_rp2040_serial_ports()
        preferred = _read_preferred_serial_port_from_ui(self)
        if preferred and preferred not in rp_ports:
            preferred = None
        serial_port = preferred or (rp_ports[0] if rp_ports else "")

        if bootsel and rp_ports:
            port_hint = serial_port or rp_ports[0]
            return (
                True,
                "Pico — BOOTSEL conflict",
                "Not ready",
                (
                    f"RPI-RP2 and {port_hint} are both visible. "
                    "Unplug USB, hold BOOTSEL, plug in while holding BOOTSEL until "
                    "only RPI-RP2 appears and the COM port disappears."
                ),
                False,
            )
        if bootsel:
            return (
                True,
                "Pico in BOOTSEL mode",
                "Ready to flash",
                "RPI-RP2 · BOOTSEL · USB serial off",
                True,
            )
        if serial_port:
            return (
                True,
                "Raspberry Pi Pico detected",
                "Connected",
                f"{serial_port} · RP2040 · USB serial · DFPlayer",
                True,
            )
        return (
            False,
            "Waiting for device...",
            "Not connected",
            "Plug in USB to detect your Pico.",
            False,
        )

    def _set_basic_device_presence_indicator(self, detected: bool) -> None:
        """Update device banner, install button, and Choose Device visibility."""
        banner = self._basic_install_device_banner()
        detected, title_text, status_text, meta_text, status_on = banner

        page = getattr(self, "_install_firmware_page", None)
        if _qt_widget_alive(page):
            page.device_section.set_detected(
                detected, status_text=status_text, status_on=status_on,
            )
            page.device_section.set_meta_text(meta_text)
            if hasattr(page.device_section, "_title"):
                page.device_section._title.setText(title_text)

        title = getattr(self, "_basic_device_title_label", None)
        if _qt_widget_alive(title):
            title.setText(title_text)

        install_btn = getattr(self, "_basic_install_firmware_btn", None)
        if _qt_widget_alive(install_btn):
            page = getattr(self, "_install_firmware_page", None)
            entry = page.firmware_list.selected_entry() if _qt_widget_alive(page) else None
            status, enabled = self._firmware_install_status(entry, detected=detected)
            install_btn.setEnabled(enabled)
            if _qt_widget_alive(page):
                page.detail_panel.set_status(status)

        self._refresh_basic_choose_device_visibility()

    def _on_refresh_device_clicked(self) -> None:
        w = getattr(self, "_basic_debug_widget", None)
        if _qt_widget_alive(w) and hasattr(w, "_scan_ports"):
            try:
                w._scan_ports()
            except Exception:
                pass
        self._set_basic_device_presence_indicator(self._basic_device_usb_present())
        self.statusBar().showMessage("Device list refreshed.", 3000)

    def _basic_detected_device_meta_line(self, detected: bool) -> str:
        if not detected:
            return "Plug in USB to detect your Pico."
        parts: List[str] = []
        port_label = ""
        w = getattr(self, "_basic_debug_widget", None)
        if _qt_widget_alive(w) and hasattr(w, "port_combo"):
            port = w.port_combo.currentData()
            if port:
                port_label = str(port)
        if not port_label:
            try:
                import serial.tools.list_ports as list_ports

                for port_info in list_ports.comports():
                    if DeviceDebugWidget._is_rp2040_port(port_info):
                        port_label = str(getattr(port_info, "device", "") or "")
                        break
            except Exception:
                pass
        if port_label:
            parts.append(port_label)
        if SDManager.is_rp2040_bootsel_present() and not port_label:
            parts.append("BOOTSEL")
        else:
            parts.append("RP2040")
            if port_label:
                parts.append("USB serial")
        parts.append("DFPlayer")
        return " · ".join(parts)

    def _basic_detected_device_name(self) -> str:
        """Best-effort human-readable label for the first detected RP2040 USB device."""
        try:
            import serial.tools.list_ports as list_ports

            for port_info in list_ports.comports():
                if not DeviceDebugWidget._is_rp2040_port(port_info):
                    continue
                desc = (getattr(port_info, "description", "") or "").strip()
                product = (getattr(port_info, "product", "") or "").strip()
                device = getattr(port_info, "device", "") or ""
                friendly = product or desc or "RP2040 device"
                if device and device not in friendly:
                    return f"{friendly} ({device})"
                return friendly
        except Exception:
            pass
        if SDManager.is_rp2040_bootsel_present():
            return "RP2040 (BOOTSEL mode)"
        return "RP2040 device"

    def _refresh_basic_choose_device_visibility(self) -> None:
        """Show Choose Device on the Install Firmware banner (mock always shows both)."""
        btn = getattr(self, "_basic_choose_device_btn", None)
        if not _qt_widget_alive(btn):
            return
        btn.setVisible(True)

    # ── Advanced Tools window (debug console) ──────────────────────────────

    def _open_advanced_tools_dialog(self) -> None:
        """Open the Tools tab with the Debugger folder selected."""
        self._open_tools_tab("debugger")

    def _open_tools_tab(self, mode: str = "debugger", *, open_micropython_dialog: bool = False) -> None:
        sidebar = getattr(self, "_sidebar", None)
        if _qt_widget_alive(sidebar):
            sidebar.set_active(self._PAGE_TOOLS)
        self._on_sidebar_nav(self._PAGE_TOOLS)
        page = getattr(self, "_tools_page", None)
        if _qt_widget_alive(page):
            page.set_mode(mode)
            if mode == "session_logs":
                page.session_logs_panel._refresh_full()
        w = getattr(self, "_basic_debug_widget", None)
        if _qt_widget_alive(w) and hasattr(w, "reload_vintage_theme"):
            w.reload_vintage_theme()
        if open_micropython_dialog:
            self._show_install_micropython_dialog()

    # ── Choose Device picker ──────────────────────────────

    def _on_choose_device_clicked(self) -> None:
        """Show a picker of detected RP2040 ports and select it on the debug widget."""
        try:
            import serial.tools.list_ports as list_ports

            ports = [
                p for p in list_ports.comports() if DeviceDebugWidget._is_rp2040_port(p)
            ]
        except Exception:
            ports = []
        if not ports:
            VintageMessageBox.information(
                self,
                "Choose Device",
                "No RP2040 devices detected. Plug in your Pico and try again.",
            )
            return
        labels: List[str] = []
        devices: List[str] = []
        for p in ports:
            desc = (getattr(p, "description", "") or "").strip()
            product = (getattr(p, "product", "") or "").strip()
            dev = getattr(p, "device", "") or "?"
            friendly = product or desc or "RP2040"
            labels.append(f"{friendly}  ({dev})")
            devices.append(str(dev))
        if len(labels) == 1:
            chosen, ok = labels[0], True
        else:
            chosen, ok = get_item(
                self,
                "Choose Device",
                "Select the RP2040 device to use:",
                labels,
                0,
                False,
            )
        if not ok or not chosen:
            return
        try:
            idx = labels.index(chosen)
        except ValueError:
            return
        port_dev = devices[idx]
        w = getattr(self, "_basic_debug_widget", None)
        if _qt_widget_alive(w) and hasattr(w, "port_combo"):
            self._mcp_select_serial_port(w, port_dev)
        self.statusBar().showMessage(f"Selected device: {port_dev}", 5000)

    # ── Advanced firmware list ──────────────────────────────

    def _firmware_entry_installable(self, entry: Optional[Dict[str, Any]]) -> bool:
        if not entry or entry.get("disabled"):
            return False
        if entry.get("installable") is False:
            return False
        return bool(entry.get("available", True))

    def _firmware_install_status(self, entry: Optional[Dict[str, Any]], *, detected: bool) -> tuple[str, bool]:
        if not entry:
            return "Select firmware to install.", False
        if not self._firmware_entry_installable(entry):
            return "Install is not available for this firmware yet.", False
        if not detected:
            return "Connect a device to install.", False
        return "Ready to install.", True

    def _builtin_firmware_entries(self) -> List[Dict[str, Any]]:
        """Hardcoded built-in firmware entries shown at the top of the Advanced list.

        Each entry has keys: ``id`` (stable), ``name``, ``description``, ``notes``,
        ``recommended`` (bool), ``available`` (bool — hide placeholders).
        """
        return [
            {
                "id": "v1.1_stable",
                "name": "Vintage Radio Basic Firmware",
                "listName": "Default RP2040",
                "listSubtitle": "One-step UF2 when bundled, else auto mpremote",
                "description": (
                    "Official firmware made with this app in mind - an improved version of Zion's original firmware with station browsing, playback control, "
                    "AM tuning overlay, shuffle modes, and the full gesture set for DFPlayer + RP2040 hardware."
                ),
                "badge": "Official",
                "version": "v1.0",
                "microcontroller": "RP2040",
                "mp3Controller": "DFPlayer",
                "device": "DFPlayer + RP2040",
                "author": updater.GITHUB_REPO_SLUG.split("/", 1)[0],
                "repoUrl": "https://github.com/alexnoctis76/Vintage_radio",
                "notes": (
                    "Vintage Radio basic-mode firmware (main_basic.py + radio_core).\n\n"
                    "Install: flashes a bundled full-flash .uf2 in BOOTSEL mode when available; "
                    "otherwise installs MicroPython automatically (if needed) and copies firmware via USB.\n\n"
                    "Stock MicroPython only (no Vintage Radio app) is under Tools → MicroPython.\n\n"
                    "Includes DFPlayer playback, AM tuning overlay, and the full gesture set.\n\n"
                    "Button presses:\n"
                    "  Single tap       — Next track\n"
                    "  Double tap       — Previous track\n"
                    "  Triple tap       — Restart station at track 1\n"
                    "  Long press       — Next station\n"
                    "  Tap + hold       — Exit shuffle, return to ordered playback\n"
                    "  Double tap + hold — Shuffle current station\n"
                    "  Triple tap + hold — First station + shuffle tracks\n"
                    "  Four taps        — Previous station\n"
                    "  Five taps        — First station (exits track shuffle)"
                ),
                "recommended": True,
                "available": True,
                "kind": "vintage_radio",
                "custom": False,
            },
            {
                "id": ZBVR_FIRMWARE_ENTRY_ID,
                "name": "Zbvr-Firmware RP2040",
                "listName": "Zbvr-Firmware RP2040",
                "listSubtitle": "Refactored DFPlayer firmware",
                "description": (
                    "Community refactor of Zion's baseline firmware for RP2040 + DFPlayer "
                    "Mini — modular layout, shuffle modes, fade in/out, and improved "
                    "DFPlayer communication."
                ),
                "badge": "Community",
                "version": "v26.0.1",
                "microcontroller": "RP2040",
                "mp3Controller": "DFPlayer",
                "device": "DFPlayer + RP2040",
                "author": "mloit",
                "repoUrl": "https://github.com/mloit/zbvr-firmware",
                "notes": (
                    "Zbvr-Firmware 26.0.1 (Theraformed) — RP2040 + DFPlayer Mini.\n\n"
                    "Highlights from the release:\n"
                    "  Bi-directional DFPlayer communication with timeout handling\n"
                    "  Playlist built at boot from valid folders only\n"
                    "  Track/album shuffle, full-disk shuffle, and auto-reshuffle\n"
                    "  Fade in/out for MP3 and WAV playback\n"
                    "  Live SD card insert/remove handling\n"
                    "  LED colour feedback and quickstart boot mode\n\n"
                    "Releases: https://github.com/mloit/zbvr-firmware/releases"
                ),
                "recommended": False,
                "available": True,
                "installable": True,
                "kind": "remote_uf2",
                "cacheKey": "zbvr_26_0_1",
                "githubRepo": "mloit/zbvr-firmware",
                "githubTag": "26.0.1",
                "downloadUrl": (
                    "https://github.com/mloit/zbvr-firmware/releases/download/"
                    "26.0.1/zbvr-firmware-26_0_1.uf2.zip"
                ),
                "custom": False,
            },
        ]

    def _official_firmware_entries_for_ui(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for entry in self._builtin_firmware_entries():
            row = dict(entry)
            entry_id = str(row.get("id", ""))
            if not is_official_firmware_visible(entry_id):
                continue
            if row.get("disabled") or row.get("available", True):
                entries.append(row)
        return entries

    def _custom_firmware_entries_for_ui(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for entry in self._custom_firmware_entries_load():
            row = dict(entry)
            kind = str(row.get("kind") or "micropython").lower()
            if kind == "uf2":
                row["badge"] = "UF2"
                row["listSubtitle"] = "BOOTSEL install"
                row["description"] = row.get("description") or "Installs directly in BOOTSEL mode"
            elif kind == "folder":
                row["badge"] = "Folder"
                row["listSubtitle"] = "Source folder"
                row["description"] = row.get("description") or "MicroPython source folder"
            else:
                row["badge"] = "Custom"
                row["listSubtitle"] = "MicroPython file"
                row["description"] = row.get("description") or "MicroPython source file"
            row["listName"] = row.get("name") or "Custom"
            row["version"] = "Custom"
            row["device"] = "RP2040"
            row["author"] = "You"
            row["custom"] = True
            entries.append(row)
        return entries

    def _firmware_entries_for_ui(self) -> List[Dict[str, Any]]:
        """Built-in + custom entries with display badges for the Install Firmware tab."""
        return self._official_firmware_entries_for_ui() + self._custom_firmware_entries_for_ui()

    def _current_firmware_tab_mode(self) -> str:
        page = getattr(self, "_install_firmware_page", None)
        if _qt_widget_alive(page):
            return page.mode_tabs.mode
        raw = (self.db.get_setting("install_firmware_tab_mode", "") or "official").strip()
        return raw if raw in ("official", "custom") else "official"

    def _on_firmware_mode_changed(self, mode: str) -> None:
        norm = "custom" if str(mode).lower() == "custom" else "official"
        self.db.set_setting("install_firmware_tab_mode", norm)
        page = getattr(self, "_install_firmware_page", None)
        if _qt_widget_alive(page):
            page.set_firmware_mode(norm)
        self._refresh_firmware_list_ui()

    def _firmware_user_notes_load(self) -> Dict[str, str]:
        raw = (self.db.get_setting("install_firmware_user_notes_json", "") or "").strip()
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def _firmware_user_notes_save(self, notes: Dict[str, str]) -> None:
        self.db.set_setting("install_firmware_user_notes_json", json.dumps(notes))

    def _firmware_user_note_for(self, entry_id: str) -> str:
        return self._firmware_user_notes_load().get(str(entry_id), "")

    def _set_firmware_user_note_for(self, entry_id: str, text: str) -> None:
        notes = self._firmware_user_notes_load()
        key = str(entry_id)
        if text.strip():
            notes[key] = text
        elif key in notes:
            del notes[key]
        self._firmware_user_notes_save(notes)

    def _refresh_firmware_list_ui(self) -> None:
        page = getattr(self, "_install_firmware_page", None)
        if not _qt_widget_alive(page):
            return
        mode = self._current_firmware_tab_mode()
        if mode == "custom":
            entries = self._custom_firmware_entries_for_ui()
        else:
            entries = self._official_firmware_entries_for_ui()
        selected_id = self._selected_firmware_entry_id()
        if selected_id and not any(str(e.get("id", "")) == selected_id for e in entries):
            selected_id = str(entries[0].get("id", "")) if entries else ""
            if selected_id:
                self._set_selected_firmware_entry_id(selected_id)
        page.firmware_list.set_entries(
            entries,
            selected_id=selected_id,
            show_filter=len(entries) > 1,
        )
        entry = page.firmware_list.selected_entry()
        self._apply_firmware_detail_panel(entry, custom_empty=(mode == "custom" and not entries))

    def _apply_firmware_detail_panel(
        self,
        entry: Optional[Dict[str, Any]],
        *,
        custom_empty: bool = False,
    ) -> None:
        page = getattr(self, "_install_firmware_page", None)
        if not _qt_widget_alive(page):
            return
        user_notes = ""
        if entry and not entry.get("custom"):
            user_notes = self._firmware_user_note_for(str(entry.get("id", "")))
        page.detail_panel.set_entry(
            entry,
            user_notes=user_notes,
            custom_empty=custom_empty,
        )
        detected = self._basic_device_usb_present()
        status, enabled = self._firmware_install_status(entry, detected=detected)
        if custom_empty or not entry:
            page.detail_panel.set_status("Add a custom firmware source to continue.")
            page.detail_panel.install_btn.setEnabled(False)
        else:
            page.detail_panel.set_status(status)
            page.detail_panel.install_btn.setEnabled(enabled)

    def _on_firmware_selection_changed(self, entry: object) -> None:
        if entry is None:
            mode = self._current_firmware_tab_mode()
            custom_entries = self._custom_firmware_entries_for_ui()
            self._apply_firmware_detail_panel(
                None,
                custom_empty=(mode == "custom" and not custom_entries),
            )
            return
        if not isinstance(entry, dict):
            return
        self._set_selected_firmware_entry_id(str(entry.get("id", "")))
        self._apply_firmware_detail_panel(entry)

    def _on_view_firmware_notes_clicked(self) -> None:
        page = getattr(self, "_install_firmware_page", None)
        entry = page.firmware_list.selected_entry() if _qt_widget_alive(page) else None
        if entry and not entry.get("custom"):
            self._show_firmware_notes_dialog(entry, custom=False, editable=False)

    def _on_edit_user_notes_clicked(self) -> None:
        page = getattr(self, "_install_firmware_page", None)
        if not _qt_widget_alive(page):
            return
        entry = page.firmware_list.selected_entry()
        if not entry:
            return
        if entry.get("custom"):
            self._show_firmware_notes_dialog(entry, custom=True, editable=True)
        else:
            self._show_official_user_notes_dialog(entry)

    def _show_official_user_notes_dialog(self, entry: Dict[str, Any]) -> None:
        entry_id = str(entry.get("id", ""))
        dlg = VintageTextDialog(
            self,
            title=f"Your Notes — {entry.get('name', 'Firmware')}",
            text=self._firmware_user_note_for(entry_id),
            read_only=False,
            buttons=[("Cancel", "secondary"), ("Save", "primary")],
        )
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._set_firmware_user_note_for(entry_id, dlg.text())
            self._apply_firmware_detail_panel(entry)

    def _on_firmware_remove_selected(self) -> None:
        page = getattr(self, "_install_firmware_page", None)
        if not _qt_widget_alive(page):
            return
        entry = page.firmware_list.selected_entry()
        if entry and entry.get("custom"):
            self._remove_custom_firmware_entry(entry)

    def _on_add_custom_firmware_menu(self) -> None:
        page = getattr(self, "_install_firmware_page", None)
        anchor = page.firmware_list if _qt_widget_alive(page) else self
        menu = QtWidgets.QMenu(self)
        act_uf2 = menu.addAction("Add .uf2 file…")
        act_file = menu.addAction("Add MicroPython file…")
        act_folder = menu.addAction("Add source folder…")
        chosen = menu.exec(QtGui.QCursor.pos())
        if chosen == act_uf2:
            self._on_browse_custom_firmware_local(uf2_only=True)
        elif chosen == act_file:
            self._on_browse_custom_firmware_local(mpy_only=True)
        elif chosen == act_folder:
            self._on_browse_custom_firmware_folder()

    def _on_install_selected_firmware(self) -> None:
        """Install the software selected on the Install Firmware tab."""
        self._on_install_firmware_advanced_clicked()

    def _selected_firmware_entry_id(self) -> str:
        return (self.db.get_setting("install_firmware_selected_entry", "") or "").strip()

    def _set_selected_firmware_entry_id(self, entry_id: str) -> None:
        self.db.set_setting("install_firmware_selected_entry", str(entry_id or ""))

    # ── Custom firmware persistence ──────────────────────────────

    def _custom_firmware_entries_load(self) -> List[Dict[str, Any]]:
        """Load custom firmware entries persisted under ``custom_firmware_entries_json``.

        Each entry: ``{id, name, path, kind: 'uf2'|'micropython', notes}``.
        """
        raw = (self.db.get_setting("custom_firmware_entries_json", "") or "").strip()
        out: List[Dict[str, Any]] = []
        try:
            data = json.loads(raw) if raw else []
        except Exception:
            data = []
        if isinstance(data, list):
            for e in data:
                if not isinstance(e, dict):
                    continue
                kind = str(e.get("kind") or "micropython").strip().lower()
                if kind not in ("uf2", "micropython", "folder"):
                    path_val = str(e.get("path") or "")
                    if path_val and Path(path_val).is_dir():
                        kind = "folder"
                    else:
                        kind = "micropython"
                desc = "Local file"
                if kind == "uf2":
                    desc = "Installs directly in BOOTSEL mode"
                elif kind == "folder":
                    desc = "MicroPython source folder"
                else:
                    desc = "Local MicroPython source"
                out.append(
                    {
                        "id": str(e.get("id") or e.get("path") or e.get("name") or "custom"),
                        "name": str(e.get("name") or "Custom firmware"),
                        "path": str(e.get("path") or ""),
                        "kind": kind,
                        "notes": str(e.get("notes") or e.get("description") or ""),
                        "description": desc,
                        "custom": True,
                    }
                )
        return out

    def _custom_firmware_entries_save(self, entries: List[Dict[str, Any]]) -> None:
        serializable = [
            {
                "id": str(e.get("id", "")),
                "name": str(e.get("name", "")),
                "path": str(e.get("path", "")),
                "kind": str(e.get("kind", "micropython")),
                "notes": str(e.get("notes", "")),
            }
            for e in entries
        ]
        self.db.set_setting("custom_firmware_entries_json", json.dumps(serializable))

    def _on_browse_custom_firmware_local(
        self,
        *,
        uf2_only: bool = False,
        mpy_only: bool = False,
    ) -> None:
        if uf2_only:
            caption = "Select UF2 firmware"
            flt = "UF2 firmware (*.uf2);;All files (*)"
        elif mpy_only:
            caption = "Select MicroPython source file"
            flt = "MicroPython (*.py *.mpy);;All files (*)"
        else:
            caption = "Select firmware file"
            flt = "Firmware files (*.uf2 *.py *.mpy);;UF2 (*.uf2);;MicroPython (*.py *.mpy);;All files (*)"
        path_str, _flt = QtWidgets.QFileDialog.getOpenFileName(
            self,
            caption,
            "",
            flt,
        )
        if not path_str:
            return
        path = Path(path_str)
        if not path.is_file():
            VintageMessageBox.warning(
                self, "Browse firmware", f"Not a file: {path}"
            )
            return
        ext = path.suffix.lower()
        allowed = (".uf2",) if uf2_only else ((".py", ".mpy") if mpy_only else (".uf2", ".py", ".mpy"))
        if ext not in allowed:
            VintageMessageBox.warning(
                self,
                "Browse firmware",
                "That file type is not supported here.",
            )
            return
        kind = "uf2" if ext == ".uf2" else "micropython"
        entries = self._custom_firmware_entries_load()
        new_id = f"custom:{path.resolve()}"
        entries = [e for e in entries if e.get("id") != new_id]
        entries.append(
            {
                "id": new_id,
                "name": path.name,
                "path": str(path),
                "kind": kind,
                "notes": "",
            }
        )
        self._custom_firmware_entries_save(entries)
        self._set_selected_firmware_entry_id(new_id)
        page = getattr(self, "_install_firmware_page", None)
        if _qt_widget_alive(page):
            page.set_firmware_mode("custom")
            self.db.set_setting("install_firmware_tab_mode", "custom")
        self._refresh_firmware_list_ui()

    def _on_browse_custom_firmware_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose custom software folder",
            str(Path.home()),
        )
        if not folder or not str(folder).strip():
            return
        path = Path(folder.strip())
        if not path.is_dir():
            VintageMessageBox.warning(self, "Browse firmware", f"Not a folder: {path}")
            return
        entries = self._custom_firmware_entries_load()
        new_id = f"custom:{path.resolve()}"
        entries = [e for e in entries if e.get("id") != new_id]
        entries.append(
            {
                "id": new_id,
                "name": path.name,
                "path": str(path),
                "kind": "folder",
                "notes": "",
            }
        )
        self._custom_firmware_entries_save(entries)
        self._set_selected_firmware_entry_id(new_id)
        page = getattr(self, "_install_firmware_page", None)
        if _qt_widget_alive(page):
            page.set_firmware_mode("custom")
            self.db.set_setting("install_firmware_tab_mode", "custom")
        self._refresh_firmware_list_ui()

    def _rebuild_advanced_firmware_list(self) -> None:
        self._refresh_firmware_list_ui()

    def _show_firmware_ellipsis_menu(
        self,
        entry: Dict[str, Any],
        custom: bool,
        source_widget: QtWidgets.QWidget,
    ) -> None:
        menu = QtWidgets.QMenu(self)
        act_view = menu.addAction("View notes")
        act_edit = None
        act_remove = None
        if custom:
            act_edit = menu.addAction("Edit notes")
            menu.addSeparator()
            act_remove = menu.addAction("Remove")
        chosen = menu.exec(source_widget.mapToGlobal(QtCore.QPoint(0, source_widget.height())))
        if chosen is None:
            return
        if chosen == act_view:
            self._show_firmware_notes_dialog(entry, custom=custom, editable=False)
        elif act_edit is not None and chosen == act_edit:
            self._show_firmware_notes_dialog(entry, custom=custom, editable=True)
        elif act_remove is not None and chosen == act_remove:
            self._remove_custom_firmware_entry(entry)

    def _show_firmware_notes_dialog(
        self,
        entry: Dict[str, Any],
        *,
        custom: bool,
        editable: bool,
    ) -> None:
        title = f"Notes — {entry.get('name', 'Firmware')}"
        notes = str(entry.get("notes") or "")
        if custom and editable:
            dlg = VintageTextDialog(
                self,
                title=title,
                text=notes,
                read_only=False,
                buttons=[("Save", "primary")],
            )
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                entries = self._custom_firmware_entries_load()
                for e in entries:
                    if e.get("id") == entry.get("id"):
                        e["notes"] = dlg.text()
                        break
                self._custom_firmware_entries_save(entries)
                page = getattr(self, "_install_firmware_page", None)
                if _qt_widget_alive(page):
                    sel = page.firmware_list.selected_entry()
                    if sel and sel.get("id") == entry.get("id"):
                        self._apply_firmware_detail_panel(sel)
            return

        VintageTextDialog.show_read_only(
            self,
            title=title,
            text=notes,
        )

    def _remove_custom_firmware_entry(self, entry: Dict[str, Any]) -> None:
        reply = VintageMessageBox.question(
            self,
            "Remove custom firmware",
            f"Remove '{entry.get('name', 'this entry')}' from your custom firmware list?",
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
            VintageMessageBox.StandardButton.No,
        )
        if reply != VintageMessageBox.StandardButton.Yes:
            return
        entries = self._custom_firmware_entries_load()
        entries = [e for e in entries if e.get("id") != entry.get("id")]
        self._custom_firmware_entries_save(entries)
        if self._selected_firmware_entry_id() == str(entry.get("id", "")):
            self._set_selected_firmware_entry_id("")
        self._rebuild_advanced_firmware_list()

    def _on_install_firmware_advanced_clicked(self) -> None:
        """Install the software selected on the Install Firmware tab."""
        if getattr(self, "_rebuilding_tabs", False):
            return
        page = getattr(self, "_install_firmware_page", None)
        entry = page.firmware_list.selected_entry() if _qt_widget_alive(page) else None
        if not entry:
            VintageMessageBox.information(
                self,
                "Install firmware",
                "Select a software entry first.",
            )
            return
        entry_id = str(entry.get("id", ""))
        if entry_id == "v1.1_stable" or str(entry.get("kind") or "").lower() == "vintage_radio":
            self._install_vintage_radio_official_firmware()
            return
        kind = str(entry.get("kind") or "micropython").lower()
        if kind == "remote_uf2":
            self._install_remote_uf2_firmware(entry)
            return
        if not self._firmware_entry_installable(entry):
            VintageMessageBox.information(
                self,
                "Install firmware",
                "Install is not available for this firmware yet.\n\n"
                "Select Vintage Radio Basic, or add a custom firmware source.",
            )
            return
        path_str = str(entry.get("path") or "")
        if not path_str:
            VintageMessageBox.warning(
                self, "Install firmware", "This entry has no path on disk."
            )
            return
        path = Path(path_str)
        if kind == "uf2":
            if not path.is_file():
                VintageMessageBox.warning(
                    self, "Install firmware", f"File not found: {path}"
                )
                return
            self._install_custom_uf2_to_pico(path)
            return
        if not path.exists():
            VintageMessageBox.warning(
                self,
                "Install firmware",
                f"Path not found: {path}\n\nRemove this entry or choose a new path.",
            )
            return
        label = str(entry.get("name") or path.name)
        self.db.set_setting("advanced_custom_software_path", str(path))
        self._setup_basic_device(
            install_callback=lambda: self.install_custom_software_to_pico(),
            install_label=label,
            require_builtin_firmware=False,
        )

    def _install_remote_uf2_firmware(self, entry: Dict[str, Any]) -> None:
        """Download a community .uf2 release (if needed) and flash via BOOTSEL."""
        from gui.services.remote_firmware import ensure_entry_uf2

        label = str(entry.get("name") or "Firmware")
        progress = IndeterminateProgressDialog(
            self, "Install firmware", f"Downloading {label}…",
        )
        progress.show_and_raise()

        result: Dict[str, Any] = {"path": None, "error": None}

        def _worker() -> None:
            try:
                result["path"] = ensure_entry_uf2(entry)
            except Exception as exc:
                result["error"] = str(exc)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        while thread.is_alive():
            QtWidgets.QApplication.processEvents()
            time.sleep(0.05)
        progress.close()

        if result["error"]:
            VintageMessageBox.warning(
                self,
                "Install firmware",
                f"Could not download {label}:\n\n{result['error']}",
            )
            return
        uf2_path = result["path"]
        if uf2_path is None:
            VintageMessageBox.warning(
                self,
                "Install firmware",
                f"Download finished but no .uf2 file was produced for {label}.",
            )
            return
        write_session_line(f"Remote UF2 ready: {uf2_path}", prefix="SETUP")
        self._flash_uf2_to_bootsel(uf2_path)

    def _resolve_bootsel_drive(self) -> Optional[Path]:
        try:
            for path, label in SDManager.detect_sd_roots():
                if label and label.strip().upper() == "RPI-RP2":
                    return Path(path)
        except Exception:
            pass
        if platform.system() == "Darwin":
            vols = Path("/Volumes")
            if vols.is_dir():
                for item in vols.iterdir():
                    try:
                        if item.is_dir() and item.name.upper().startswith("RPI-RP2"):
                            return item
                    except OSError:
                        continue
        return None

    def _flash_uf2_to_bootsel(self, uf2_path: Path, *, success_title: str = "Install firmware") -> bool:
        """Copy a .uf2 to the Pico BOOTSEL drive. Returns True on success."""
        if not uf2_path.is_file():
            VintageMessageBox.warning(
                self,
                success_title,
                f"Firmware file not found:\n{uf2_path}",
            )
            return False
        if not self._is_rpi_rp2_present():
            reply = VintageMessageBox.question(
                self,
                "BOOTSEL required",
                "No RPI-RP2 drive detected.\n\n"
                "Hold the BOOTSEL button while plugging in the Pico so it appears as "
                "a USB drive, then click OK to try again.",
                VintageMessageBox.StandardButton.Ok | VintageMessageBox.StandardButton.Cancel,
                VintageMessageBox.StandardButton.Ok,
            )
            if reply != VintageMessageBox.StandardButton.Ok:
                return False
            if not self._is_rpi_rp2_present():
                VintageMessageBox.warning(
                    self,
                    "BOOTSEL required",
                    "Still no RPI-RP2 drive detected. Aborting install.",
                )
                return False
        dest_dir = self._resolve_bootsel_drive()
        if dest_dir is None:
            VintageMessageBox.warning(
                self,
                success_title,
                "Could not locate the RPI-RP2 drive. Replug the Pico (BOOTSEL held) and retry.",
            )
            return False
        dest_file = dest_dir / uf2_path.name
        try:
            shutil.copy2(uf2_path, dest_file)
        except OSError as e:
            VintageMessageBox.warning(
                self,
                success_title,
                f"Could not copy .uf2 to {dest_dir}:\n{e}",
            )
            return False
        VintageMessageBox.information(
            self,
            success_title,
            f"Copied {uf2_path.name} to {dest_dir}.\n\nThe Pico should reboot automatically.",
        )
        return True

    def _install_custom_uf2_to_pico(self, uf2_path: Path) -> None:
        """Copy a .uf2 directly to a Pico in BOOTSEL mode (no MicroPython prompt)."""
        self._flash_uf2_to_bootsel(uf2_path)

    def _wait_for_bootsel_with_progress(
        self,
        *,
        title: str,
        intro: str,
        timeout_s: float = 180.0,
    ) -> bool:
        """Poll until RPI-RP2 appears or *timeout_s* elapses (main thread + modal)."""
        dlg = IndeterminateProgressDialog(self, title, intro)
        dlg.show_and_raise()

        def _report(_cur: int, _total: int, message: str) -> None:
            dlg.set_message(message)

        found = _wait_for_bootsel_polling(
            _report,
            intro=intro,
            timeout_s=timeout_s,
            is_present=self._is_rpi_rp2_present,
            preferred_serial_port=_read_preferred_serial_port_from_ui(self),
        )
        dlg.close()
        return found

    def _copy_uf2_to_bootsel_quiet(
        self,
        uf2_path: Path,
        *,
        preferred_serial_port: Optional[str] = None,
    ) -> bool:
        """Copy a .uf2 to BOOTSEL without extra dialogs (automated install path)."""
        ok, _detail = self._bootsel_preflight_for_uf2_flash(preferred_serial_port)
        if not ok:
            write_session_line(f"BOOTSEL preflight failed: {_detail}", prefix="INSTALL")
            return False
        dest_dir = self._resolve_bootsel_drive()
        if dest_dir is None:
            return False
        copied, err = _copy_uf2_to_rpi_rp2(uf2_path, dest_dir)
        if not copied:
            write_session_line(f"BOOTSEL copy failed: {err}", prefix="INSTALL")
        else:
            write_session_line(f"Flashed UF2: {uf2_path}", prefix="INSTALL")
        return copied

    def _flash_micropython_then_install_vintage_radio(
        self,
        *,
        blocking_label: Optional[str] = None,
    ) -> None:
        """Replace non-stock firmware via BOOTSEL MicroPython flash, then mpremote install."""
        if blocking_label:
            intro = (
                f"Detected {blocking_label} on the Pico.\n\n"
                "Vintage Radio will flash official MicroPython (replacing that firmware), "
                "then copy the Vintage Radio app automatically.\n\n"
                "No hardware reset is required — put the Pico in BOOTSEL mode when prompted."
            )
        else:
            intro = (
                "The Pico needs official MicroPython before Vintage Radio can be copied.\n\n"
                "Put the Pico in BOOTSEL mode when prompted; the app will flash MicroPython "
                "and install Vintage Radio automatically."
            )

        if not self._is_rpi_rp2_present():
            if not self._wait_for_bootsel_with_progress(
                title="Install Vintage Radio",
                intro=intro,
            ):
                VintageMessageBox.information(
                    self,
                    "Install Vintage Radio",
                    "Timed out waiting for BOOTSEL (RPI-RP2 drive).\n\n"
                    "Hold BOOTSEL while plugging in USB, then click Install Firmware again.",
                )
                return

        if not self._auto_flash_micropython_to_bootsel():
            VintageMessageBox.warning(
                self,
                "Install Vintage Radio",
                "Could not copy MicroPython to the Pico.\n\n"
                "Ensure RPI-RP2 is visible and try again.",
            )
            return

        self.statusBar().showMessage(
            "MicroPython flashed. Installing Vintage Radio when the Pico reboots…", 12000
        )
        QtCore.QTimer.singleShot(
            _POST_MICROPYTHON_INSTALL_DELAY_MS,
            lambda: self.install_to_pico(basic_mode=True, after_firmware=True),
        )

    def _bootsel_preflight_for_uf2_flash(
        self,
        preferred_serial_port: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Ensure RPI-RP2 is present, authentic, and USB serial is off."""
        if not self._is_rpi_rp2_present():
            return False, "No RPI-RP2 drive detected. Hold BOOTSEL while plugging in USB."
        dest_dir = self._resolve_bootsel_drive()
        if dest_dir is None:
            return False, "Could not locate the RPI-RP2 drive path."
        authentic, auth_detail = _is_authentic_rp2040_bootsel_volume(dest_dir)
        if not authentic:
            return False, auth_detail
        port = _find_rp2040_serial_port(preferred=preferred_serial_port)
        if port:
            return False, _bootsel_serial_blocking_message(port)
        if not _wait_for_serial_port_gone(
            preferred_port=preferred_serial_port,
            timeout_s=3.0,
        ):
            port = _find_rp2040_serial_port(preferred=preferred_serial_port)
            if port:
                return False, _bootsel_serial_blocking_message(port)
        write_session_line(
            f"BOOTSEL preflight OK: RPI-RP2 at {dest_dir} (USB serial off)",
            prefix="INSTALL",
        )
        return True, str(dest_dir)

    def _flash_micropython_uf2_to_bootsel_core(
        self,
        progress_callback: Optional[Callable[..., Any]] = None,
        preferred_serial_port: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Download/cache stock MicroPython and flash to BOOTSEL (no Qt dialogs)."""
        from gui.services.firmware_bundle import fetch_micropython_uf2

        ok, detail = self._bootsel_preflight_for_uf2_flash(preferred_serial_port)
        if not ok:
            return False, detail

        dest_dir = Path(detail)

        if progress_callback:
            progress_callback(0, 0, "Downloading MicroPython for Pico…")
        try:
            uf2_path = fetch_micropython_uf2()
        except Exception as exc:
            write_session_line(f"MicroPython download failed: {exc}", prefix="SETUP")
            return False, f"MicroPython download failed: {exc}"
        if uf2_path is None:
            return False, "MicroPython download returned no file."

        return _flash_uf2_file(
            Path(uf2_path),
            dest_dir,
            progress_callback=progress_callback,
        )

    def _factory_reset_reflash_micropython(
        self,
        progress_callback: Optional[Callable[..., Any]] = None,
        preferred_serial_port: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Erase all flash then flash stock MicroPython (after first flash did not stick)."""
        write_session_line("Starting factory reset (full flash erase)", prefix="INSTALL")

        def _progress(msg: str) -> None:
            if progress_callback:
                progress_callback(0, 0, msg)

        if not self._is_rpi_rp2_present():
            _progress(_FACTORY_RESET_BOOTSEL_INTRO)
            if not _wait_for_bootsel_polling(
                progress_callback,
                intro=_FACTORY_RESET_BOOTSEL_INTRO,
                timeout_s=180.0,
                is_present=self._is_rpi_rp2_present,
                preferred_serial_port=preferred_serial_port,
            ):
                return False, (
                    "Timed out waiting for BOOTSEL to run factory reset.\n\n"
                    "Unplug all power, hold BOOTSEL, plug USB while holding BOOTSEL."
                )

        ok, detail = self._bootsel_preflight_for_uf2_flash(preferred_serial_port)
        if not ok:
            return False, detail
        dest_dir = Path(detail)

        ok, err, erase_method = _factory_erase_rp2040_flash(
            dest_dir, progress_callback=progress_callback,
        )
        if not ok:
            return False, err or "Factory erase failed."

        if erase_method == "nuke":
            import time

            _progress("Waiting for Pico to re-enter BOOTSEL after flash erase…")
            time.sleep(2.0)
            if not self._is_rpi_rp2_present():
                if not _wait_for_bootsel_polling(
                    progress_callback,
                    intro="Put the Pico back in BOOTSEL mode to flash MicroPython.",
                    timeout_s=90.0,
                    is_present=self._is_rpi_rp2_present,
                    preferred_serial_port=preferred_serial_port,
                ):
                    return False, (
                        "After flash_nuke the Pico did not reappear as RPI-RP2.\n\n"
                        "Hold BOOTSEL and plug in USB, then run Install Firmware again."
                    )
            ok, detail = self._bootsel_preflight_for_uf2_flash(preferred_serial_port)
            if not ok:
                return False, detail
            dest_dir = Path(detail)

        from gui.services.firmware_bundle import fetch_micropython_uf2

        _progress("Factory reset complete — flashing MicroPython…")
        try:
            uf2_path = fetch_micropython_uf2()
        except Exception as exc:
            return False, f"MicroPython download failed: {exc}"

        ok, err = _flash_uf2_file(
            Path(uf2_path),
            dest_dir,
            progress_callback=progress_callback,
        )
        if not ok:
            return False, err

        verify_err = _verify_stock_micropython_serial(
            preferred_serial_port,
            progress_callback=progress_callback,
        )
        if verify_err:
            return False, (
                f"Factory reset completed but MicroPython still did not boot ({verify_err}).\n\n"
                "The Pico may not be entering true ROM BOOTSEL, or the board may need "
                "a full power cycle (not just USB). Try USB directly into the PC, not "
                "through a hub."
            )
        return True, ""

    def _flash_micropython_for_install(
        self,
        progress_callback: Optional[Callable[..., Any]] = None,
        preferred_serial_port: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Flash MicroPython, verify boot, factory-reset and retry once if needed."""
        flashed, flash_err = self._flash_micropython_uf2_to_bootsel_core(
            progress_callback,
            preferred_serial_port=preferred_serial_port,
        )
        if not flashed:
            return False, flash_err or "Could not flash MicroPython."

        verify_err = _verify_stock_micropython_serial(
            preferred_serial_port,
            progress_callback=progress_callback,
        )
        if verify_err is None:
            return True, ""

        write_session_line(
            f"First MicroPython flash did not stick ({verify_err}); running factory reset",
            prefix="INSTALL",
        )
        if progress_callback:
            progress_callback(
                0,
                0,
                "MicroPython did not replace the old firmware.\n\n"
                "Running factory reset (full flash erase)…",
            )
        return self._factory_reset_reflash_micropython(
            progress_callback,
            preferred_serial_port=preferred_serial_port,
        )

    def _smart_install_vintage_radio_worker(
        self,
        progress_callback: Optional[Callable[..., Any]] = None,
        preferred_serial_port: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Background worker: detect Pico state and flash MicroPython when needed."""
        write_session_line("Smart install Vintage Radio basic", prefix="INSTALL")

        def _progress(msg: str) -> None:
            if progress_callback:
                progress_callback(0, 0, msg)

        _progress("Preparing firmware install…")

        from gui.services.firmware_bundle import bundled_vintage_radio_full_uf2

        full_uf2 = bundled_vintage_radio_full_uf2()
        if full_uf2 is not None:
            write_session_line(f"Bundled full-flash UF2: {full_uf2}", prefix="INSTALL")
            if not self._is_rpi_rp2_present():
                intro = (
                    "A one-file Vintage Radio firmware image is available.\n\n"
                    "Put the Pico in BOOTSEL mode (RPI-RP2 drive) to flash it."
                )
                if not _wait_for_bootsel_polling(
                    progress_callback,
                    intro=intro,
                    is_present=self._is_rpi_rp2_present,
                    preferred_serial_port=preferred_serial_port,
                ):
                    return {
                        "action": "message",
                        "level": "info",
                        "title": "Install Vintage Radio",
                        "message": (
                            "Timed out waiting for BOOTSEL. Hold BOOTSEL and try "
                            "Install Firmware again."
                        ),
                    }
            _progress(f"Flashing {full_uf2.name}…")
            if self._copy_uf2_to_bootsel_quiet(
                full_uf2, preferred_serial_port=preferred_serial_port,
            ):
                return {
                    "action": "message",
                    "level": "info",
                    "title": "Install Vintage Radio",
                    "message": (
                        f"Flashed {full_uf2.name}.\n\n"
                        "The Pico should reboot with Vintage Radio ready."
                    ),
                    "status_message": "Vintage Radio firmware flashed.",
                }
            return {
                "action": "message",
                "level": "warning",
                "title": "Install Vintage Radio",
                "message": "Could not copy the firmware .uf2 to RPI-RP2.",
            }

        mpremote_cmd = self._resolve_mpremote_cmd()
        if not mpremote_cmd:
            return {
                "action": "message",
                "level": "info",
                "title": "Install Vintage Radio",
                "message": (
                    "mpremote is not available. Install it with: pip install mpremote"
                ),
            }

        _progress("Checking Pico connection…")
        assessment = _pico_install_assessment(
            mpremote_cmd,
            self._project_root(),
            preferred_port=preferred_serial_port,
            progress_callback=progress_callback,
        )
        status = assessment.get("status")
        write_session_line(f"Pico install assessment: {assessment}", prefix="INSTALL")

        if status == "ready":
            write_session_line("Pico ready for mpremote install", prefix="INSTALL")
            return {"action": "install_to_pico", "after_firmware": False}

        if status == "bootsel":
            _progress("Flashing MicroPython…")
            flashed, flash_err = self._flash_micropython_for_install(
                progress_callback,
                preferred_serial_port=preferred_serial_port,
            )
            if flashed:
                return {"action": "install_to_pico", "after_firmware": True}
            return {
                "action": "message",
                "level": "warning",
                "title": "Install Vintage Radio",
                "message": flash_err or (
                    "Could not copy MicroPython to the Pico.\n\n"
                    "Ensure RPI-RP2 is visible and try again."
                ),
            }

        blocking_label = assessment.get("blocking_label")
        if status == "needs_reflash":
            if blocking_label:
                intro = (
                    f"Detected {blocking_label}.\n\n"
                    "Hold BOOTSEL and tap RESET until the RPI-RP2 drive appears "
                    "in File Explorer and the COM port disappears.\n\n"
                    "Vintage Radio will flash official MicroPython, then install the app."
                )
            else:
                intro = (
                    "The Pico needs official MicroPython before Vintage Radio can be copied.\n\n"
                    "Hold BOOTSEL and tap RESET until the RPI-RP2 drive appears."
                )
        else:
            intro = (
                "No Pico detected on USB serial.\n\n"
                "Connect the Pico and put it in BOOTSEL mode (RPI-RP2 drive) "
                "to flash MicroPython, then Vintage Radio will install automatically."
            )

        if status in ("needs_reflash", "no_pico"):
            if not self._is_rpi_rp2_present():
                write_session_line(
                    "Waiting for BOOTSEL (RPI-RP2 drive) — hold BOOTSEL and tap RESET",
                    prefix="INSTALL",
                )
                _progress(intro)
                if not _wait_for_bootsel_polling(
                    progress_callback,
                    intro=intro,
                    is_present=self._is_rpi_rp2_present,
                    preferred_serial_port=preferred_serial_port,
                ):
                    if status == "no_pico":
                        return {
                            "action": "message",
                            "level": "info",
                            "title": "Install Vintage Radio",
                            "message": (
                                "No Pico detected. Connect via USB and try Install Firmware again."
                            ),
                        }
                    return {
                        "action": "message",
                        "level": "info",
                        "title": "Install Vintage Radio",
                        "message": (
                            "Timed out waiting for BOOTSEL (RPI-RP2 drive).\n\n"
                            "Hold BOOTSEL while plugging in USB, then click Install Firmware again."
                        ),
                    }
            _progress("Flashing MicroPython…")
            flashed, flash_err = self._flash_micropython_for_install(
                progress_callback,
                preferred_serial_port=preferred_serial_port,
            )
            if flashed:
                return {"action": "install_to_pico", "after_firmware": True}
            return {
                "action": "message",
                "level": "warning",
                "title": "Install Vintage Radio",
                "message": flash_err or (
                    "Could not copy MicroPython to the Pico.\n\n"
                    "Ensure RPI-RP2 is visible and try again."
                ),
            }

        return {
            "action": "message",
            "level": "warning",
            "title": "Install Vintage Radio",
            "message": (
                "Could not determine Pico state. Connect the Pico via USB and try again."
            ),
        }

    def _apply_smart_install_result(self, result: Dict[str, Any]) -> None:
        """Main-thread follow-up after the smart-install worker finishes."""
        action = result.get("action")
        if action == "install_to_pico":
            after = bool(result.get("after_firmware"))
            if after:
                self.statusBar().showMessage(
                    "MicroPython flashed. Installing Vintage Radio when the Pico reboots…",
                    12000,
                )
                QtCore.QTimer.singleShot(
                    _POST_MICROPYTHON_INSTALL_DELAY_MS,
                    lambda: self.install_to_pico(basic_mode=True, after_firmware=True),
                )
            else:
                self.install_to_pico(basic_mode=True)
            return

        status_msg = result.get("status_message")
        if status_msg:
            self.statusBar().showMessage(str(status_msg), 10000)

        message = str(result.get("message") or "")
        if not message:
            return
        title = str(result.get("title") or "Install Firmware")
        level = str(result.get("level") or "info").lower()
        if level == "warning":
            VintageMessageBox.warning(self, title, message)
        else:
            VintageMessageBox.information(self, title, message)

    def _prepare_install_serial_for_worker(self, dlg: TaskProgressDialog) -> None:
        """Main-thread setup before the install worker thread starts."""
        port = _read_preferred_serial_port_from_ui(self) or _find_rp2040_serial_port()
        dlg.set_status_message("Releasing USB serial port for install…")
        QtWidgets.QApplication.processEvents()
        if self._release_serial_if_connected_for_mpremote(log_prefix="INSTALL"):
            self.statusBar().showMessage(
                "Serial console disconnected so Install Firmware can use the USB port. "
                "Click Connect on the Device tab when finished.",
                12000,
            )
        if port:
            dlg.set_status_message(
                f"Checking firmware on {port} (device already connected via USB)…"
            )
        else:
            dlg.set_status_message("Looking for Pico on USB…")
        QtWidgets.QApplication.processEvents()

    def _run_smart_install_with_progress(self) -> None:
        """Run smart install on a worker thread with a modal progress dialog."""
        if getattr(self, "_smart_install_active", False):
            return

        root = self._project_root()
        if not (root / "firmware" / "pico" / "main.py").exists() or not (
            root / "firmware" / "radio_core.py"
        ).exists():
            VintageMessageBox.warning(self, "Install Firmware", "Project files not found.")
            return
        if not (root / "firmware" / "pico" / "dfplayer_hardware.py").exists():
            VintageMessageBox.warning(
                self,
                "Install Firmware",
                "firmware/pico/dfplayer_hardware.py not found.",
            )
            return

        preferred = _read_preferred_serial_port_from_ui(self)

        dlg = TaskProgressDialog(
            parent=self,
            title="Install Firmware",
            func=self._smart_install_vintage_radio_worker,
            kwargs={"preferred_serial_port": preferred},
            initial_message="Preparing firmware install…",
            on_before_start=lambda: self._prepare_install_serial_for_worker(dlg),
        )

        def _on_success(result: Any) -> None:
            self._smart_install_active = False
            if isinstance(result, dict):
                self._apply_smart_install_result(result)

        def _on_error(msg: str) -> None:
            self._smart_install_active = False
            VintageMessageBox.warning(self, "Install Firmware", f"Error:\n\n{msg}")

        dlg.on_success = _on_success
        dlg.on_error = _on_error
        self._smart_install_active = True
        dlg.exec()
        self._smart_install_active = False

    def _smart_install_vintage_radio_basic(self) -> None:
        """Detect Pico state and install using the correct path (one button)."""
        self._run_smart_install_with_progress()

    def _install_vintage_radio_official_firmware(self) -> None:
        """Install official Vintage Radio basic firmware (smart detect + one-button flow)."""
        self._run_smart_install_with_progress()

    def _auto_flash_micropython_to_bootsel(self) -> bool:
        """Download/cache stock MicroPython and copy to BOOTSEL without opening a dialog."""
        progress = IndeterminateProgressDialog(
            self, "Setup Device", "Downloading MicroPython for Pico…",
        )
        progress.show_and_raise()

        def _report(_cur: int, _total: int, message: str) -> None:
            progress.set_message(message)

        ok, _err = self._flash_micropython_for_install(_report)
        progress.close()
        return ok

    def _prompt_install_micropython_via_tools(self, *, install_label: str) -> None:
        msg = VintageMessageBox(self)
        msg.setIcon(VintageMessageBox.Icon.Information)
        msg.setWindowTitle("MicroPython required")
        msg.setText(
            "MicroPython must be installed on the Pico before Vintage Radio firmware can be copied.\n\n"
            "Use Tools → MicroPython to flash the official MicroPython .uf2 in BOOTSEL mode, "
            "then run Install Firmware again.\n\n"
            f"After MicroPython is running, the app will install {install_label} automatically."
        )
        open_btn = msg.addButton(
            "Open Tools → MicroPython", VintageMessageBox.ButtonRole.ActionRole
        )
        msg.addButton("Close", VintageMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == open_btn:
            self._open_tools_tab("micropython", open_micropython_dialog=True)

    def _current_max_tracks_per_station(self) -> int:
        if not self._is_advanced_mode():
            return BASIC_MAX_TRACKS_PER_STATION
        if self._uses_custom_software():
            return BASIC_MAX_TRACKS_EXPERIMENTAL
        allow_exp = self.db.get_setting("advanced_allow_our_software_gt255", "0") == "1"
        return BASIC_MAX_TRACKS_EXPERIMENTAL if allow_exp else BASIC_MAX_TRACKS_PER_STATION

    def _is_track_limit_enforced(self) -> bool:
        return not (self._is_advanced_mode() and self._uses_custom_software())

    def _software_source_for_sync(self) -> str:
        if not self._is_advanced_mode():
            return "our"
        val = (self.db.get_setting("advanced_software_source", "our") or "our").strip().lower()
        return "custom" if val == "custom" else "our"

    def _selected_dfplayer_eq(self) -> str:
        val = (self.db.get_setting("advanced_dfplayer_eq", "normal") or "normal").strip().lower()
        if val not in {"normal", "pop", "rock", "jazz", "classic", "bass"}:
            return "normal"
        return val

    def _basic_sd_path_volume_tag(self, path_str: str) -> str:
        """Volume / mount name for wrong-card messaging (best-effort)."""
        try:
            p = Path(path_str).expanduser()
            if p.is_dir():
                p = p.resolve()
        except OSError:
            p = Path(path_str)
        lab = self._get_volume_label(p)
        if lab and str(lab).strip():
            return str(lab).strip()
        try:
            if p.is_dir():
                parent = p.parent
                if parent.name == "Volumes" or str(parent).endswith("Volumes"):
                    return p.name
        except Exception:
            pass
        return p.name or str(path_str)

    def _basic_should_warn_different_card(self, new_root: str) -> bool:
        trusted = (self.db.get_setting("basic_trusted_sd_volume") or "").strip()
        if not trusted:
            return False
        cur = self._basic_sd_path_volume_tag(new_root).strip()
        if cur and _volume_name_key(cur) != _volume_name_key(trusted):
            return True
        trusted_serial = (self.db.get_setting("basic_trusted_sd_serial") or "").strip().upper()
        if trusted_serial:
            try:
                cur_serial = _get_volume_serial(Path(new_root).expanduser()).strip().upper()
            except OSError:
                cur_serial = ""
            if cur_serial and cur_serial != trusted_serial:
                return True
        return False

    def _basic_confirm_first_sd_sync_target(self, sd_path_str: str) -> bool:
        """One-time check before the first successful basic sync (no trusted volume yet)."""
        if not self._is_basic_like_mode():
            return True
        if (self.db.get_setting("basic_trusted_sd_volume") or "").strip():
            return True
        vol = self._basic_sd_path_volume_tag(sd_path_str)
        vol_line = vol if vol else "(unknown)"
        reply = VintageMessageBox.question(
            self,
            "Confirm SD card",
            "This library has not completed a basic-mode sync to an SD card yet.\n\n"
            f"You are about to write station folders to:\n  {sd_path_str}\n"
            f"Volume name (best guess): {vol_line}\n\n"
            "Make sure this is the correct SD card or USB drive. Writing to the "
            "wrong device can erase important data.\n\n"
            "Proceed with sync to this location?",
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
            VintageMessageBox.StandardButton.No,
        )
        return reply == VintageMessageBox.StandardButton.Yes

    def _collect_basic_broken_source_paths(self) -> List[Dict[str, str]]:
        """Tracks whose source file is missing on disk (uses the path-missing cache when warm)."""
        broken: List[Dict[str, str]] = []
        try:
            stations = self.db.list_basic_stations()
        except Exception:
            return broken
        for station in stations:
            station_name = (station["name"] or "").strip() or f"Station {station['folder_number']}"
            try:
                tracks = self.db.list_basic_station_songs(station["id"])
            except Exception:
                continue
            for song in tracks:
                fp_raw = (song["file_path"] or "").strip()
                if not fp_raw:
                    continue
                if not self._song_source_path_missing(song):
                    continue
                title = (
                    (song["title"] or "").strip()
                    or (song["original_filename"] or "").strip()
                    or Path(fp_raw).name
                )
                broken.append({"title": title, "path": fp_raw, "station": station_name})
        return broken

    def _basic_confirm_broken_sources_before_sync(self) -> bool:
        """Warn about missing source files after the user picks a sync mode."""
        broken = self._collect_basic_broken_source_paths()
        if not broken:
            return True
        n = len(broken)
        path_phrase = "its stored path" if n == 1 else "their stored paths"
        headline = (
            f"{n} track{'s' if n != 1 else ''} in your library can't be found at {path_phrase}."
        )
        explanation = (
            "These tracks will be skipped during sync. To include them, fix the paths "
            "(right-click a track in the station list and choose Replace source file…), "
            "or remove the tracks, then sync again.\n\n"
            "Full list:"
        )
        proceed = self._show_scrollable_broken_paths_dialog(
            window_title="Broken file paths detected",
            headline=headline,
            explanation=explanation,
            entries=broken,
            line_fmt=lambda e: f"{e['title']}  ({e['station']})\n{e['path']}",
            proceed_text="Sync anyway (skip missing tracks)",
            cancel_text="Cancel",
        )
        QtCore.QTimer.singleShot(0, self._refresh_library_source_health_ui)
        return proceed

    def _basic_volume_mismatch_pair(self, new_root: str) -> Optional[tuple[str, str]]:
        """Return (trusted_volume, current_volume) when the SD target differs from last sync."""
        if not self._basic_should_warn_different_card(new_root):
            return None
        trusted = (self.db.get_setting("basic_trusted_sd_volume") or "").strip()
        cur = self._basic_sd_path_volume_tag(new_root).strip()
        if not trusted:
            return None
        if not cur or _volume_name_key(cur) == _volume_name_key(trusted):
            cur = f"{cur or trusted} (different physical card)"
        return trusted, cur

    def _basic_confirm_different_card(self, new_root: str, *, for_sync: bool) -> bool:
        """If the volume differs from the last basic sync target, confirm. Returns False to abort."""
        if not self._is_basic_like_mode():
            return True
        if not self._basic_should_warn_different_card(new_root):
            return True
        trusted = (self.db.get_setting("basic_trusted_sd_volume") or "").strip()
        cur = self._basic_sd_path_volume_tag(new_root)
        verb = "sync stations to" if for_sync else "use"
        reply = VintageMessageBox.question(
            self,
            "Different SD card",
            f'Your last successful basic-mode sync used the volume named "{trusted}".\n\n'
            f'The selected path looks like "{cur}".\n\n'
            "If this is the wrong card, you could overwrite the wrong device.\n\n"
            f'Do you want to {verb} this volume anyway?',
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
            VintageMessageBox.StandardButton.No,
        )
        return reply == VintageMessageBox.StandardButton.Yes

    def _basic_sd_label_match_set(self) -> set:
        """Normalized uppercase volume keys we use to recognize the user's SD card across reconnects."""
        names: set = set()
        for raw in (
            self.sd_label,
            self.db.get_setting("sd_volume_label"),
            self.db.get_setting("basic_trusted_sd_volume"),
        ):
            k = _volume_name_key(raw)
            if k:
                names.add(k)
        return names

    def _basic_sd_identity_match_set(self) -> set:
        """Like _basic_sd_label_match_set plus the last folder name of sd_root (macOS volume name)."""
        names = set(self._basic_sd_label_match_set())
        if self.sd_root:
            try:
                tail = Path(self.sd_root).expanduser().name
                k = _volume_name_key(tail)
                if k:
                    names.add(k)
            except (OSError, ValueError):
                pass
        return names

    def _basic_sync_target_identity_match_set(self) -> set:
        """Volume keys for the card last used for SD sync (settings DB only).

        Omits :attr:`sd_label` and ``sd_root`` so after **Select** switches to another
        volume, **Detect** can still resolve the original sync-target card from
        ``basic_trusted_sd_volume`` / ``sd_volume_label``.
        """
        names: set = set()
        for raw in (
            self.db.get_setting("sd_volume_label"),
            self.db.get_setting("basic_trusted_sd_volume"),
        ):
            k = _volume_name_key(raw)
            if k:
                names.add(k)
        return names

    def _refresh_basic_sd_after_sync(self) -> None:
        """Re-detect SD mount and refresh status after sync (format, rename, or label change)."""
        if not self._is_basic_like_mode():
            self._update_sd_root_label()
            self._check_basic_sd_sync()
            return
        self._try_rebind_basic_sd_mount()
        candidates = self.sd_manager.detect_sd_roots()
        sync_id = self._basic_sync_target_identity_match_set()
        if sync_id and candidates:
            sync_matched = [
                (path, label)
                for path, label in candidates
                if self._basic_candidate_matches_identity(path, label, sync_id)
            ]
            if len(sync_matched) == 1:
                path, lab = sync_matched[0]
                new_label = (lab or "").strip() or (self._get_volume_label(path) or "")
                self.sd_root = str(path)
                self.sd_label = new_label
                self.db.set_setting("sd_root", self.sd_root)
                self.db.set_setting("sd_label", self.sd_label)
        elif self.sd_root:
            try:
                path = Path(self.sd_root)
                if path.is_dir():
                    lab = self._get_volume_label(path) or self.sd_label
                    if lab:
                        self.sd_label = lab
                        self.db.set_setting("sd_label", self.sd_label)
            except OSError:
                pass
        self._update_sd_root_label()
        self._refresh_basic_sd_capacity()
        self._check_basic_sd_sync()

    @staticmethod
    def _basic_candidate_matches_identity(path: Path, label: str, identity: set) -> bool:
        if not identity:
            return False
        lab_k = _volume_name_key(label)
        if lab_k and lab_k in identity:
            return True
        try:
            name_k = _volume_name_key(path.name)
            if name_k and name_k in identity:
                return True
        except Exception:
            pass
        return False

    def detect_basic_sd_root(self) -> None:
        """Basic mode: set sd_root to the removable volume that matches saved identity (no dialogs)."""
        if not self._is_basic_like_mode():
            self.select_sd_root()
            return

        self._try_rebind_basic_sd_mount()

        candidates = self.sd_manager.detect_sd_roots()
        if not candidates:
            VintageMessageBox.information(
                self, "SD Detect", "No removable drives detected."
            )
            return

        sync_id = self._basic_sync_target_identity_match_set()
        sync_matched: List[Tuple[Path, str]] = []
        if sync_id:
            sync_matched = [
                (path, label)
                for path, label in candidates
                if self._basic_candidate_matches_identity(path, label, sync_id)
            ]
            if len(sync_matched) == 1:
                path, lab = sync_matched[0]
                new_label = (lab or "").strip() or (self._get_volume_label(path) or "")
                self.sd_root = str(path)
                self.sd_label = new_label
                self.db.set_setting("sd_root", self.sd_root)
                self.db.set_setting("sd_label", self.sd_label)
                self._update_sd_root_label()
                self._check_basic_sd_sync()
                self.statusBar().showMessage(
                    f"SD card (last sync target): {self.sd_root}", 5000
                )
                return
            if len(sync_matched) > 1:
                VintageMessageBox.information(
                    self,
                    "SD Detect",
                    "Several removable drives match your last sync target.\n\n"
                    "Use Select to pick the correct one.",
                )
                return

        # Saved path shortcut: only if no sync record, or current root is already the sync-target card.
        use_saved_path = True
        if self.sd_root and sync_id:
            try:
                saved = Path(self.sd_root).expanduser().resolve()
                if saved.is_dir():
                    slabel = self._get_volume_label(saved) or saved.name or ""
                    if not self._basic_candidate_matches_identity(saved, slabel, sync_id):
                        use_saved_path = False
            except OSError:
                use_saved_path = False

        if use_saved_path and self.sd_root:
            try:
                saved = Path(self.sd_root).expanduser().resolve()
                if saved.is_dir():
                    for path, label in candidates:
                        try:
                            if path.resolve() == saved:
                                lab = (label or "").strip() or (
                                    self._get_volume_label(path) or path.name
                                )
                                self.sd_root = str(path)
                                self.sd_label = lab
                                self.db.set_setting("sd_root", self.sd_root)
                                self.db.set_setting("sd_label", self.sd_label)
                                self._update_sd_root_label()
                                self._check_basic_sd_sync()
                                self.statusBar().showMessage(
                                    f"SD card: {self.sd_root}", 4000
                                )
                                return
                        except OSError:
                            continue
            except OSError:
                pass

        if sync_id and not sync_matched:
            VintageMessageBox.information(
                self,
                "SD Detect",
                "Could not find the SD card used for your last sync "
                "(trusted volume / sync label not among detected drives).\n\n"
                "Connect that card and try Detect again, or use Select.",
            )
            return

        identity = self._basic_sd_identity_match_set()
        matched = [
            (path, label)
            for path, label in candidates
            if self._basic_candidate_matches_identity(path, label, identity)
        ]

        if len(matched) == 1:
            path, lab = matched[0]
            new_label = (lab or "").strip() or (self._get_volume_label(path) or "")
            self.sd_root = str(path)
            self.sd_label = new_label
            self.db.set_setting("sd_root", self.sd_root)
            self.db.set_setting("sd_label", self.sd_label)
            self._update_sd_root_label()
            self._check_basic_sd_sync()
            self.statusBar().showMessage(f"Detected SD card: {self.sd_root}", 5000)
            return

        if len(matched) > 1:
            VintageMessageBox.information(
                self,
                "SD Detect",
                "Several removable drives match your saved volume name.\n\n"
                "Use Select to pick the correct one.",
            )
            return

        if len(candidates) == 1:
            path, lab = candidates[0]
            self.sd_root = str(path)
            self.sd_label = (lab or "") or (self._get_volume_label(path) or "")
            self.db.set_setting("sd_root", self.sd_root)
            self.db.set_setting("sd_label", self.sd_label)
            self._update_sd_root_label()
            self._check_basic_sd_sync()
            self.statusBar().showMessage(
                "Using the only removable drive found. Use Select if this is not your SD card.",
                6000,
            )
            return

        if not identity:
            VintageMessageBox.information(
                self,
                "SD Detect",
                "Multiple removable drives are connected, and no saved SD identity is set yet.\n\n"
                "Use Select to pick your SD card. After a successful sync, Detect will "
                "find that card automatically by name.",
            )
            return

        VintageMessageBox.information(
            self,
            "SD Detect",
            "Could not match any detected removable drive to your saved SD card "
            "(by volume name).\n\n"
            "On macOS many volumes appear under /Volumes; if you renamed the card, "
            "use Select or Browse once, then sync so the app can remember the new name.\n\n"
            "Use Select to choose from the list, or Browse to pick a folder.",
        )

    def _try_rebind_basic_sd_mount(self) -> None:
        """If saved sd_root is missing, reattach to the same card by volume name (basic mode)."""
        if not self._is_basic_like_mode():
            return
        if not self.sd_root:
            return
        try:
            if Path(self.sd_root).is_dir():
                return
        except OSError:
            pass
        candidates = self.sd_manager.detect_sd_roots()
        if not candidates:
            return
        identity = self._basic_sd_identity_match_set()
        matched = [
            (path, label)
            for path, label in candidates
            if self._basic_candidate_matches_identity(path, label, identity)
        ]
        if len(matched) == 1:
            path, label = matched[0]
            self.sd_root = str(path)
            self.sd_label = label or self._get_volume_label(path) or ""
            self.db.set_setting("sd_root", self.sd_root)
            self.db.set_setting("sd_label", self.sd_label)
            self._update_sd_root_label()

    def _check_basic_sd_sync(self) -> None:
        """Show a warning when basic stations and the mounted SD layout disagree."""
        warn = getattr(self, "_basic_sd_sync_warning", None)
        if not _qt_widget_alive(warn):
            return
        warn.setVisible(False)
        details_btn = getattr(self, "_basic_sd_sync_details_btn", None)
        if _qt_widget_alive(details_btn):
            details_btn.setVisible(False)
        if not self._is_basic_like_mode():
            return
        self._try_rebind_basic_sd_mount()
        if not self.sd_root:
            return
        try:
            root = Path(self.sd_root)
            if not root.is_dir():
                return
        except OSError:
            return

        trusted = (self.db.get_setting("basic_trusted_sd_volume") or "").strip()
        is_different_card = trusted and self._basic_should_warn_different_card(self.sd_root)

        if is_different_card:
            warn.setText("This looks like a different SD card from your last sync.")
            warn.setVisible(True)
            return

        msgs = self.sd_manager.validate_basic_sd(
            root,
            reserved_folder=(99 if not self._uses_custom_software() else None),
        )
        if not msgs:
            return

        self._basic_sd_sync_issues = msgs
        n = len(msgs)
        if n > 30:
            warn.setText(
                "Your SD card looks different from your library (many changes detected). "
                "A sync will bring it up to date."
            )
        else:
            warn.setText(
                f"Your SD card looks different from your library "
                f"({n} difference{'s' if n != 1 else ''} found)."
            )
        warn.setVisible(True)
        if _qt_widget_alive(details_btn):
            details_btn.setVisible(True)

    def _show_basic_sd_sync_details(self) -> None:
        """Open a scrollable dialog listing SD sync mismatch details."""
        msgs = getattr(self, "_basic_sd_sync_issues", [])
        if not msgs:
            return
        body = "\n".join(f"  - {m}" for m in msgs)
        if len(msgs) > 30:
            body = (
                "Your SD card differs from your library in many places "
                "(first 30 shown below).\nSyncing will bring the card up to date.\n\n"
                + "\n".join(f"  - {m}" for m in msgs[:30])
                + f"\n  ... and {len(msgs) - 30} more."
            )
        VintageTextDialog(
            self,
            title="SD Card Differences",
            text=body,
            read_only=True,
            min_height=280,
            buttons=[("Close", "secondary")],
        ).exec()

    def _release_serial_if_connected_for_mpremote(self, *, log_prefix: str = "SERIAL") -> bool:
        """Close the app's serial session so ``mpremote`` can open the COM port (Windows: exclusive)."""
        released = False
        for name in ("_basic_debug_widget", "_device_debug_widget"):
            w = getattr(self, name, None)
            if w is None or not _qt_widget_alive(w):
                continue
            try:
                if getattr(w, "_connected", False):
                    w._disconnect()
                    released = True
            except Exception:
                pass
        if released:
            import time

            time.sleep(1.25 if sys.platform == "win32" else 0.35)
            write_session_line(
                "Released app-held serial port(s) so mpremote can access the device",
                prefix=log_prefix,
            )
            print("[Vintage Radio] Released app-held serial port(s) for mpremote")
        return released

    def _on_setup_basic_device_clicked(self) -> None:
        """Qt slot: log first (durable) then run setup — isolates signal vs handler crashes."""
        if getattr(self, "_rebuilding_tabs", False):
            # Guard against accidental clicked() emitted while wiring buttons during a
            # tab rebuild (e.g. switching view mode); see _rebuild_tabs.
            return
        write_session_line("Setup Device: Qt clicked (before _setup_basic_device)", prefix="SETUP")
        self._setup_basic_device()

    def _on_setup_advanced_device_clicked(self) -> None:
        if getattr(self, "_rebuilding_tabs", False):
            return
        self._flush_advanced_mcu_notes_and_buttons()
        source = self._software_source_for_sync()
        if source == "custom":
            self._advanced_sync_custom_path_setting_to_active_source()
            self._setup_basic_device(
                install_callback=self.install_custom_software_to_pico,
                install_label="custom software",
                require_builtin_firmware=False,
            )
            return
        self._setup_basic_device(
            install_callback=lambda: self.install_to_pico(
                basic_mode=True,
                install_mode="advanced",
                dfplayer_eq=self._selected_dfplayer_eq(),
            ),
            install_label="advanced firmware",
            require_builtin_firmware=True,
        )

    def _setup_basic_device(
        self,
        *,
        install_callback: Optional[Callable[[], None]] = None,
        install_label: str = "basic firmware",
        require_builtin_firmware: bool = True,
        auto_flash_micropython: bool = False,
    ) -> None:
        """One-click: install MicroPython if needed, then install application firmware."""
        try:
            write_session_line("Starting one-click setup flow", prefix="SETUP")
            print("[Setup Basic Device] Starting one-click setup flow")
            mpremote_cmd = self._resolve_mpremote_cmd()
            if not mpremote_cmd:
                bundle_err = getattr(self, "_mpremote_bundle_error", None)
                write_session_line(f"mpremote unavailable bundle_err={bundle_err!r}", prefix="SETUP")
                print(f"[Setup Basic Device] mpremote unavailable. bundle_err={bundle_err!r}")
                msg = "mpremote is not available. Install it with: pip install mpremote"
                if bundle_err:
                    msg += "\n\n(Bundled mpremote failed:\n" + str(bundle_err) + ")"
                VintageMessageBox.information(self, "Setup Device", msg)
                return

            if self._release_serial_if_connected_for_mpremote(log_prefix="SETUP"):
                self.statusBar().showMessage(
                    "Serial console disconnected so Setup Device can use the USB port. "
                    "Click Connect on the Device tab when finished.",
                    12000,
                )

            write_session_line(f"Resolved mpremote command: {mpremote_cmd!r}", prefix="SETUP")
            print(f"[Setup Basic Device] Resolved mpremote command: {mpremote_cmd!r}")
            root = self._project_root()
            if require_builtin_firmware:
                main_basic_path = root / "firmware" / "pico" / "main_basic.py"
                if not main_basic_path.exists():
                    write_session_line(f"Missing firmware file: {main_basic_path}", prefix="SETUP")
                    print(f"[Setup Basic Device] Missing firmware file: {main_basic_path}")
                    VintageMessageBox.warning(self, "Setup Device", "firmware/pico/main_basic.py not found.")
                    return

            install_now = install_callback or (lambda: self.install_to_pico(basic_mode=True))

            # Prefer explicit RP2040 ports first to avoid grabbing unrelated serial devices (e.g. Bluetooth COM).
            rp_ports: List[Any] = []
            probe_outputs: List[str] = []
            probe_timed_out = False
            try:
                import serial.tools.list_ports as list_ports

                ports = list(list_ports.comports())
                write_session_line(f"Serial ports discovered: {len(ports)}", prefix="SETUP")
                print(f"[Setup Basic Device] Serial ports discovered: {len(ports)}")
                rp_ports.clear()
                for port_info in ports:
                    port_dev = getattr(port_info, "device", None) or str(port_info)
                    hwid = getattr(port_info, "hwid", "") or ""
                    is_rp = DeviceDebugWidget._is_rp2040_port(port_info)
                    write_session_line(
                        f"Port candidate device={port_dev!r} rp2040={is_rp}",
                        prefix="SETUP",
                    )
                    print(
                        f"[Setup Basic Device] Port candidate: device={port_dev!r} hwid={hwid!r} rp2040={is_rp}"
                    )
                    if is_rp:
                        rp_ports.append(port_info)

                write_session_line(f"RP2040 candidate ports: {len(rp_ports)}", prefix="SETUP")
                print(f"[Setup Basic Device] RP2040 candidate ports: {len(rp_ports)}")
                probe_outputs: List[str] = []
                probe_timed_out = False
                for port_info in rp_ports:
                    port_dev = getattr(port_info, "device", None) or str(port_info)
                    sniff = _sniff_rp2040_serial_text(port_dev)
                    if sniff.strip():
                        probe_outputs.append(sniff)
                        write_session_line(
                            f"serial sniff ({port_dev}): {sniff[:400]!r}",
                            prefix="SETUP",
                        )
                        blocking = _serial_output_indicates_blocking_firmware(sniff)
                        if blocking:
                            write_session_line(
                                f"Detected non-installable firmware on {port_dev}: {blocking}",
                                prefix="SETUP",
                            )
                            print(f"[Setup Basic Device] Detected {blocking} on {port_dev}")
                            break

                    write_session_line(f"Trying mpremote explicit connect: {port_dev}", prefix="SETUP")
                    print(f"[Setup Basic Device] Trying mpremote explicit connect: {port_dev}")
                    r = _run_mpremote_probe(mpremote_cmd, port_dev, str(root))
                    out = ((r.stdout or "") + (r.stderr or "")).strip()
                    if out:
                        probe_outputs.append(out)
                        write_session_line(
                            f"explicit connect output ({port_dev}): {out[:800]}",
                            prefix="SETUP",
                        )
                        print(f"[Setup Basic Device] explicit connect output ({port_dev}): {out[:600]}")
                    if getattr(r, "returncode", 1) == 124:
                        probe_timed_out = True
                    write_session_line(
                        f"explicit connect rc ({port_dev}) = {r.returncode} micropython="
                        f"{_mpremote_result_indicates_micropython(r)}",
                        prefix="SETUP",
                    )
                    print(
                        f"[Setup Basic Device] explicit connect rc ({port_dev}) = {r.returncode} "
                        f"micropython_ok={_mpremote_result_indicates_micropython(r)}"
                    )
                    if _mpremote_result_indicates_micropython(r):
                        write_session_line(
                            f"explicit connect OK on {port_dev}, calling install_to_pico(basic_mode=True)",
                            prefix="SETUP",
                        )
                        print(f"[Setup Basic Device] explicit connect succeeded on {port_dev}, installing firmware")
                        install_now()
                        return
                    if _serial_output_indicates_blocking_firmware(out):
                        break
            except Exception:
                write_session_line(
                    f"RP2040 explicit scan/connect exception:\n{traceback.format_exc()}",
                    prefix="SETUP",
                )
                print("[Setup Basic Device] RP2040 explicit scan/connect exception:")
                print(traceback.format_exc())
                probe_timed_out = True

            # Fallback: can we reach a running MicroPython via auto-detected port?
            write_session_line("Trying mpremote auto connect fallback", prefix="SETUP")
            print("[Setup Basic Device] Trying mpremote auto connect fallback")
            try:
                r = _run_mpremote_probe(mpremote_cmd, "auto", str(root))
                out = ((r.stdout or "") + (r.stderr or "")).strip()
                if out:
                    probe_outputs.append(out)
                    write_session_line(f"auto connect output: {out[:800]}", prefix="SETUP")
                    print(f"[Setup Basic Device] auto connect output: {out[:600]}")
                if getattr(r, "returncode", 1) == 124:
                    probe_timed_out = True
                write_session_line(
                    f"auto connect rc = {r.returncode} micropython={_mpremote_result_indicates_micropython(r)}",
                    prefix="SETUP",
                )
                print(
                    f"[Setup Basic Device] auto connect rc = {r.returncode} "
                    f"micropython_ok={_mpremote_result_indicates_micropython(r)}"
                )
                if _mpremote_result_indicates_micropython(r):
                    write_session_line("auto connect OK, calling install_to_pico(basic_mode=True)", prefix="SETUP")
                    print("[Setup Basic Device] auto connect succeeded, installing firmware")
                    install_now()
                    return
            except Exception:
                write_session_line(
                    f"auto connect exception:\n{traceback.format_exc()}",
                    prefix="SETUP",
                )
                print("[Setup Basic Device] auto connect exception:")
                print(traceback.format_exc())

            # No MicroPython found -- check for Pico in BOOTSEL mode
            bootsel_present = self._is_rpi_rp2_present()
            write_session_line(f"BOOTSEL (RPI-RP2) present: {bootsel_present}", prefix="SETUP")
            print(f"[Setup Basic Device] BOOTSEL (RPI-RP2) present: {bootsel_present}")
            if bootsel_present:
                if auto_flash_micropython and self._auto_flash_micropython_to_bootsel():
                    self.statusBar().showMessage(
                        f"MicroPython installed. Installing {install_label}...", 8000
                    )
                    QtCore.QTimer.singleShot(_POST_MICROPYTHON_INSTALL_DELAY_MS, install_now)
                    return
                write_session_line("BOOTSEL present — prompt Tools → MicroPython", prefix="SETUP")
                print("[Setup Basic Device] BOOTSEL present — directing user to Tools → MicroPython")
                self._prompt_install_micropython_via_tools(install_label=install_label)
                return

            if rp_ports:
                write_session_line(
                    "RP2040 USB serial seen but MicroPython not verified — prompt for UF2 install",
                    prefix="SETUP",
                )
                print("[Setup Basic Device] RP2040 port(s) present without verified MicroPython")
                msg = VintageMessageBox(self)
                msg.setIcon(VintageMessageBox.Icon.Information)
                msg.setWindowTitle("Setup Device — stock MicroPython required")
                msg.setText(
                    _setup_device_failure_message(
                        probe_outputs=probe_outputs,
                        timed_out=probe_timed_out,
                    )
                )
                open_btn = msg.addButton(
                    "Open Tools → MicroPython", VintageMessageBox.ButtonRole.ActionRole
                )
                msg.addButton("Close", VintageMessageBox.ButtonRole.RejectRole)
                msg.exec()
                if msg.clickedButton() == open_btn:
                    self._open_tools_tab("micropython", open_micropython_dialog=True)
                return

            write_session_line("No compatible Pico detected (user message)", prefix="SETUP")
            print("[Setup Basic Device] No compatible Pico detected")
            VintageMessageBox.information(
                self, "Setup Device",
                "No Pico detected (mpremote could not open a MicroPython session).\n\n"
                "1. Connect the Pico via USB.\n"
                "2. If another program had the port open, this app disconnects its console "
                "automatically—try 'Setup Device' again.\n"
                "3. If it's new, hold BOOTSEL while plugging in.\n"
                "4. Then click 'Setup Device' again.",
            )
        except Exception:
            write_session_line(
                f"FATAL exception in setup flow:\n{traceback.format_exc()}",
                prefix="SETUP",
            )
            print("[Setup Basic Device] FATAL exception in setup flow:")
            print(traceback.format_exc())
            VintageMessageBox.critical(
                self,
                "Setup Device Error",
                "An unexpected error occurred during Setup Device.\n\n"
                "Please open Help > View Session Log and send the latest log.",
            )

    def _on_advanced_software_source_changed(self, *_args) -> None:
        combo = getattr(self, "_advanced_software_source_combo", None)
        if combo is None:
            return
        data = combo.currentData()
        source = "custom" if str(data) == "custom" else "our"
        self.db.set_setting("advanced_software_source", source)
        self._rebuild_tabs()

    def _on_advanced_dfplayer_eq_changed(self, *_args) -> None:
        combo = getattr(self, "_advanced_dfplayer_eq_combo", None)
        if combo is None:
            return
        self.db.set_setting("advanced_dfplayer_eq", str(combo.currentData() or "normal"))

    def _retain_conversion_cache(self) -> bool:
        return self.db.get_setting("retain_conversion_cache", "1") == "1"

    def _schedule_conversion_prefetch(self, song_ids: Optional[List[int]] = None) -> None:
        """Queue idle background MP3 conversion for faster future syncs."""
        if not self._retain_conversion_cache():
            return
        self._conversion_prefetch.schedule(song_ids=song_ids)

    def _on_retain_conversion_cache_changed(self, *_args) -> None:
        page = getattr(self, "_settings_page", None)
        if not _qt_widget_alive(page):
            return
        checked = page.retain_conversion_cache_checkbox.isChecked()
        self.db.set_setting("retain_conversion_cache", "1" if checked else "0")

    def _on_clear_conversion_cache_clicked(self) -> None:
        mb = VintageMessageBox(self)
        mb.setWindowTitle("Clear conversion cache?")
        mb.setIcon(VintageMessageBox.Icon.Question)
        mb.setText(
            "Delete all locally cached converted MP3s for this library?"
        )
        mb.setInformativeText(
            "This only affects files stored on your PC to speed up sync. "
            "Your music library and SD card are not changed.\n\n"
            "The next sync will re-encode tracks from source files (slower)."
        )
        btn_clear = mb.addButton(
            "Clear cache",
            VintageMessageBox.ButtonRole.DestructiveRole,
        )
        mb.addButton(VintageMessageBox.StandardButton.Cancel)
        mb.setDefaultButton(btn_clear)
        mb.exec()
        if mb.clickedButton() is not btn_clear:
            return
        ok, err = self.sd_manager.clear_basic_sync_mp3_cache_for_library()
        if ok:
            self.statusBar().showMessage("Conversion cache cleared.", 5000)
        else:
            VintageMessageBox.warning(
                self,
                "Could not clear conversion cache",
                f"The cache folder could not be removed:\n\n{err}",
            )

    def _experimental_fast_sync_enabled(self) -> bool:
        if self.db.get_setting("experimental_fast_sync", "0") == "1":
            return True
        page = getattr(self, "_settings_page", None)
        if _qt_widget_alive(page):
            return page.experimental_fast_sync_checkbox.isChecked()
        return False

    def _sd_image_reuse_when_unchanged_enabled(self) -> bool:
        return self.db.get_setting("sd_image_reuse_when_unchanged", "1") == "1"

    def _on_experimental_fast_sync_changed(self, *_args) -> None:
        page = getattr(self, "_settings_page", None)
        if not _qt_widget_alive(page):
            return
        checked = page.experimental_fast_sync_checkbox.isChecked()
        self.db.set_setting("experimental_fast_sync", "1" if checked else "0")

    def _on_sd_image_reuse_when_unchanged_changed(self, *_args) -> None:
        page = getattr(self, "_settings_page", None)
        if not _qt_widget_alive(page):
            return
        checked = page.sd_image_reuse_when_unchanged_checkbox.isChecked()
        self.db.set_setting("sd_image_reuse_when_unchanged", "1" if checked else "0")

    def _can_reuse_cached_sd_image(
        self,
        *,
        conv_profile: str,
        dfplayer_eq: str,
        disk_size_bytes: Optional[int],
    ) -> bool:
        if not self._sd_image_reuse_when_unchanged_enabled():
            return False
        cache_dir = app_data_dir() / "sd_image_cache"
        img_path = cache_dir / LAST_CACHED_SD_IMAGE_FILENAME
        try:
            if not img_path.is_file() or img_path.stat().st_size <= 0:
                return False
            cached_sz = int(img_path.stat().st_size)
        except OSError:
            return False
        manifest = load_cached_sd_image_manifest(cache_dir)
        if not manifest:
            return False
        if str(manifest.get("conversion_profile") or "") != conv_profile:
            return False
        if str(manifest.get("dfplayer_eq") or "") != dfplayer_eq:
            return False
        if self.sd_manager.basic_library_manifest_diff(manifest.get("stations") or {}):
            return False
        ds = disk_size_bytes
        if ds is None:
            return True
        if cached_sz > ds:
            overage = cached_sz - ds
            tolerance = max(256 * 1024 * 1024, int(ds * 0.02))
            return overage <= tolerance
        if cached_sz < ds:
            return False
        return True

    def _selected_conversion_profile(self) -> str:
        profile = (
            self.db.get_setting("conversion_profile")
            or self.db.get_setting("advanced_conversion_profile", "dfplayer_safe")
            or ""
        ).strip().lower()
        if profile not in {"dfplayer_safe", "high_quality"}:
            return "dfplayer_safe"
        return profile

    def _on_conversion_profile_changed(self, *_args) -> None:
        combo = getattr(self, "_settings_conversion_profile_combo", None)
        if combo is None:
            combo = getattr(self, "_advanced_conversion_profile_combo", None)
        if combo is None:
            return
        value = str(combo.currentData() or "dfplayer_safe")
        self.db.set_setting("conversion_profile", value)
        self.db.set_setting("advanced_conversion_profile", value)

    def _on_advanced_conversion_profile_changed(self, *_args) -> None:
        """Legacy alias for advanced-tab combo wiring."""
        self._on_conversion_profile_changed()

    def _on_settings_auto_backup_changed(self, *_args) -> None:
        page = getattr(self, "_settings_page", None)
        if not _qt_widget_alive(page):
            return
        checked = page.auto_backup_checkbox.isChecked()
        self.db.set_setting("auto_backup", "1" if checked else "0")
        self.db.auto_backup = checked

    def _on_settings_backup_retention_changed(self, value: int) -> None:
        retention = max(1, int(value))
        self.db.set_setting("backup_retention", str(retention))
        self.db.backup_retention = retention

    def _on_settings_sd_auto_detect_changed(self, *_args) -> None:
        page = getattr(self, "_settings_page", None)
        if not _qt_widget_alive(page):
            return
        checked = page.sd_auto_detect_checkbox.isChecked()
        self.db.set_setting("sd_auto_detect", "1" if checked else "0")
        self.sd_auto_detect = checked

    def _on_settings_ui_zoom_changed(self, value: int) -> None:
        self._ui_zoom_level = max(80, min(200, int(value)))
        self.db.set_setting("ui_zoom_level", str(self._ui_zoom_level))
        self._apply_ui_zoom()

    def _on_settings_ui_theme_changed(self, *_args) -> None:
        page = getattr(self, "_settings_page", None)
        if not _qt_widget_alive(page):
            return
        theme_id = normalize_theme_id(str(page.ui_theme_combo.currentData() or "vintage"))
        if theme_id == getattr(self, "_ui_theme", "vintage"):
            return
        self._ui_theme = theme_id
        self.db.set_setting("ui_theme", theme_id)
        apply_ui_theme(theme_id)
        self._reload_app_theme_ui()

    def _read_pico_install_mode(self) -> Optional[str]:
        mpremote_cmd = self._resolve_mpremote_cmd()
        if not mpremote_cmd:
            return None
        try:
            r = _run_mpremote(
                mpremote_cmd,
                [
                    "connect",
                    "auto",
                    "exec",
                    "import json\n"
                    "try:\n"
                    "  d=json.load(open('VintageRadio/advanced_runtime.json','r'))\n"
                    "  print(d.get('install_mode','basic'))\n"
                    "except Exception:\n"
                    "  print('basic')",
                ],
                cwd=str(self._project_root()),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return None
        if r.returncode != 0:
            return None
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip().splitlines()
        if not out:
            return None
        mode = out[-1].strip().lower()
        if mode in {"basic", "advanced", "legacy"}:
            return mode
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # LOAD MUSIC PAGE — widget factories
    #
    # The page is assembled in _build_basic_sd_card_tab() from five focused
    # sub-widgets.  Edit each sub-method independently; values are annotated
    # so you can find every size, colour, and spacing in one place.
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_basic_sd_card_tab(self) -> QtWidgets.QWidget:
        """Load Music page — assembled by LoadMusicPage in gui/widgets/load_music/.

        All appearance values are in gui/theme.py (LM_PAGE_MARGINS, LM_PAGE_SPACING,
        WARN_*, LM_SPLITTER_*, etc.).  Edit each sub-widget file independently:
          gui/widgets/load_music/storage_section/storage_section.py
          gui/widgets/load_music/station_panel/station_panel.py
          gui/widgets/load_music/track_panel/track_panel.py
          gui/widgets/load_music/sync_bar/sync_bar.py
        """
        self._basic_sd_sync_issues: List[str] = []

        page = _LoadMusicPage(
            sd_root=self.sd_root or "",
            max_tracks=BASIC_MAX_TRACKS_PER_STATION,
        )

        # ── Warning banner aliases and signal ─────────────────────────────────
        self._basic_sd_sync_warning    = page.warning_label
        self._basic_sd_sync_details_btn = page.warning_details_btn
        self._basic_sd_sync_details_btn.clicked.connect(self._show_basic_sd_sync_details)

        # ── StorageSection aliases and signals ────────────────────────────────
        self._basic_storage_section   = page.storage_section
        self._basic_sd_root_label     = page.storage_section.sd_root_label
        self._basic_sd_capacity_bar   = page.storage_section.capacity_bar
        self._basic_sd_percent_label  = page.storage_section.percent_label
        self._basic_sd_capacity_label = page.storage_section.capacity_label
        page.storage_section.detect_clicked.connect(self._select_sd_root_basic)
        page.storage_section.select_clicked.connect(self._select_sd_root_manual_basic)
        page.storage_section.browse_clicked.connect(self._browse_sd_root_basic)

        # ── StationPanel aliases and signals ──────────────────────────────────
        self._basic_station_list        = page.station_panel.station_list
        self._basic_stations_size_label = page.station_panel.size_label
        page.station_panel.station_selected.connect(self._on_basic_station_selected)
        page.station_panel.order_changed.connect(self._on_basic_station_reordered)
        page.station_panel.folders_dropped.connect(self._import_folders_as_basic_stations)
        page.station_panel.context_menu_requested.connect(self._show_station_context_menu)
        page.station_panel.new_station_clicked.connect(self._create_basic_station)

        # ── TrackPanel aliases and signals ────────────────────────────────────
        self._basic_station_tracks_table = page.track_panel.tracks_table
        self._basic_station_detail       = page.track_panel.station_detail
        page.track_panel.add_tracks_clicked.connect(self._add_tracks_to_basic_station)
        page.track_panel.files_dropped.connect(self._import_files_to_basic_station)
        page.track_panel.order_changed.connect(self._persist_basic_station_track_order)
        page.track_panel.context_menu_requested.connect(self._show_station_track_context_menu)

        # ── SyncBar aliases and signals ───────────────────────────────────────
        page.sync_bar.sync_clicked.connect(self._sync_basic_to_sd)
        page.sync_bar.eject_clicked.connect(self.safely_remove_sd)

        self._refresh_basic_station_list()
        self._update_basic_stations_size()
        self._update_sd_root_label()
        self._refresh_basic_sd_capacity()
        QtCore.QTimer.singleShot(0, self._sync_startup_chrome)
        return page

    # ── Basic-mode SD capacity ──

    def _refresh_basic_sd_capacity(self) -> None:
        """Update the SD capacity bar and label from the current sd_root."""
        bar = getattr(self, "_basic_sd_capacity_bar", None)
        cap_label = getattr(self, "_basic_sd_capacity_label", None)
        pct_label = getattr(self, "_basic_sd_percent_label", None)
        if not _qt_widget_alive(bar) or not _qt_widget_alive(cap_label):
            return

        def _set_pct(text: str) -> None:
            if _qt_widget_alive(pct_label):
                pct_label.setText(text)

        sd_root = self._resolve_sd_root(interactive=False)
        storage = getattr(self, "_basic_storage_section", None)
        if _qt_widget_alive(storage):
            storage.set_has_sd_card(bool(sd_root))
        if not sd_root:
            bar.setValue(0)
            _set_pct("")
            cap_label.setText("No SD card selected")
            return
        try:
            usage = shutil.disk_usage(str(sd_root))
            pct = int(usage.used * 100 / usage.total) if usage.total else 0
            bar.setValue(pct)
            _set_pct(f"{pct}% used")
            used_mb = usage.used / (1024 * 1024)
            total_mb = usage.total / (1024 * 1024)
            free_mb = usage.free / (1024 * 1024)
            if total_mb >= 1024:
                cap_label.setText(
                    f"{used_mb / 1024:.1f} / {total_mb / 1024:.1f} GB  ({free_mb / 1024:.1f} GB free)"
                )
            else:
                cap_label.setText(
                    f"{used_mb:.0f} / {total_mb:.0f} MB  ({free_mb:.0f} MB free)"
                )
        except OSError:
            bar.setValue(0)
            _set_pct("")
            cap_label.setText("Cannot read SD card")

    # ── Basic-mode station list management ──

    def _refresh_basic_station_list(self, *, preserve_selection: bool = True) -> None:
        """Reload station list from DB into the QListWidget.

        When *preserve_selection* is True, re-select the same station *id* if it
        still exists (same library). After a library switch, pass False so we clear
        the row — numeric ids are not stable across databases.

        Always syncs the tracks table to the current row; Qt sometimes skips
        ``currentItemChanged`` after ``clear()`` + repopulate, which left a
        highlighted row with an empty track list.
        """
        if not hasattr(self, "_basic_station_list"):
            return
        prev_station_id = None
        if preserve_selection:
            prev_item = self._basic_station_list.currentItem()
            if prev_item is not None:
                prev_station_id = prev_item.data(QtCore.Qt.ItemDataRole.UserRole)
        self._basic_station_list.blockSignals(True)
        self._basic_station_list.clear()
        stations = self.db.list_basic_stations()
        track_counts = self.db.basic_station_track_counts()
        restore_row = -1
        for idx, station in enumerate(stations):
            track_count = track_counts.get(int(station["id"]), 0)
            item = QtWidgets.QListWidgetItem(
                f'{station["name"]}  (Folder {station["folder_number"]:02d}, {track_count} tracks)'
            )
            item.setData(QtCore.Qt.ItemDataRole.UserRole, station["id"])
            # Extra roles drive _StationItemDelegate's custom rendering.
            item.setData(_STATION_NUM_ROLE, int(station["folder_number"]))
            item.setData(_STATION_NAME_ROLE, station["name"])
            item.setData(_STATION_COUNT_ROLE, int(track_count))
            self._basic_station_list.addItem(item)
            if preserve_selection and prev_station_id is not None and station["id"] == prev_station_id:
                restore_row = idx
        if preserve_selection and restore_row >= 0:
            self._basic_station_list.setCurrentRow(restore_row)
        else:
            self._basic_station_list.setCurrentRow(-1)
        self._basic_station_list.blockSignals(False)
        self._sync_basic_station_tracks_from_selection()

    def _sync_basic_station_tracks_from_selection(self) -> None:
        """Apply the station list's current row to the detail label and tracks table."""
        if not hasattr(self, "_basic_station_list"):
            return
        cur = self._basic_station_list.currentItem()
        self._on_basic_station_selected(cur, None)

    def _on_basic_station_selected(self, current, _previous) -> None:
        """Switch stations immediately; load tracks without blocking the UI thread."""
        if current is None:
            self._cancel_basic_tracks_load()
            self._apply_empty_basic_station_tracks()
            return

        station_id = current.data(QtCore.Qt.ItemDataRole.UserRole)
        if station_id is None:
            self._cancel_basic_tracks_load()
            self._apply_empty_basic_station_tracks()
            return

        station_id = int(station_id)
        self._update_basic_station_detail_from_item(current)
        self._cancel_basic_tracks_load()
        self._basic_tracks_load_token += 1
        token = self._basic_tracks_load_token
        self._basic_tracks_target_station_id = station_id

        # Clear stale tracks right away so the previous station doesn't linger.
        self._basic_station_tracks_table.setRowCount(0)

        QtCore.QTimer.singleShot(
            0,
            lambda sid=station_id, t=token: self._load_basic_station_tracks_sync(sid, t),
        )

    def _update_basic_station_detail_from_item(self, item: QtWidgets.QListWidgetItem) -> None:
        name = item.data(_STATION_NAME_ROLE) or ""
        folder = int(item.data(_STATION_NUM_ROLE) or 0)
        track_count = int(item.data(_STATION_COUNT_ROLE) or 0)
        max_tracks = self._current_max_tracks_per_station()
        self._basic_station_detail.setText(
            f"Station: {name}  |  Folder: {folder:02d}  |  Tracks: {track_count}/{max_tracks}"
        )

    def _apply_empty_basic_station_tracks(self) -> None:
        self._basic_station_detail.setText("Select a station to view tracks.")
        self._basic_station_tracks_table.setRowCount(0)

    def _cancel_basic_tracks_load(self) -> None:
        thread = self._basic_tracks_loader_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(200)
        self._basic_tracks_loader_thread = None

    def _load_basic_station_tracks_sync(self, station_id: int, token: int) -> None:
        if token != self._basic_tracks_load_token:
            return
        if station_id != self._basic_tracks_target_station_id:
            return
        songs = [dict(row) for row in self.db.list_basic_station_songs(station_id)]
        if token != self._basic_tracks_load_token:
            return
        if station_id != self._basic_tracks_target_station_id:
            return
        self._populate_basic_station_tracks_table(songs)
        sync_track_table_column_widths(self._basic_station_tracks_table)
        self._schedule_track_source_health_checks(songs)
        self._sync_station_track_count_on_item(station_id, len(songs))

    def _sync_station_track_count_on_item(self, station_id: int, track_count: int) -> None:
        """Keep the station row's cached count in sync after a track reload."""
        for i in range(self._basic_station_list.count()):
            item = self._basic_station_list.item(i)
            if item is None:
                continue
            sid = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if sid is not None and int(sid) == station_id:
                item.setData(_STATION_COUNT_ROLE, int(track_count))
                break

    def _populate_basic_station_tracks_table(self, songs: list) -> None:
        """Fill the tracks table in one batched pass (no per-row filesystem checks)."""
        table = self._basic_station_tracks_table
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        table.setSortingEnabled(False)
        try:
            table.setRowCount(len(songs))
            for row_idx, song in enumerate(songs):
                title = song.get("title") or song.get("original_filename") or ""
                artist = song.get("artist") or ""
                title_item = QtWidgets.QTableWidgetItem()
                configure_track_title_item(title_item, title, artist=artist)
                title_item.setData(QtCore.Qt.ItemDataRole.UserRole, song.get("id"))
                title_item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, song.get("bst_id"))
                table.setItem(row_idx, 0, title_item)
                table.setItem(
                    row_idx, 1,
                    QtWidgets.QTableWidgetItem(song.get("artist") or ""),
                )
                dur = song.get("duration")
                dur_str = f"{int(dur // 60)}:{int(dur % 60):02d}" if dur else ""
                table.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(dur_str))
                table.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(song.get("format") or ""))
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)

    def _schedule_track_source_health_checks(self, songs: list, start: int = 0) -> None:
        """Apply missing-file warning icons in small batches so the UI stays responsive."""
        table = self._basic_station_tracks_table
        if table.rowCount() != len(songs):
            return
        batch = 40
        end = min(start + batch, len(songs))
        for row_idx in range(start, end):
            item = table.item(row_idx, 0)
            if item is not None:
                self._decorate_track_title_item_source_health(item, songs[row_idx])
        if end < len(songs):
            QtCore.QTimer.singleShot(
                0,
                lambda s=songs, n=end: self._schedule_track_source_health_checks(s, n),
            )

    def _apply_basic_station_selection(self, current) -> None:
        """Legacy entry point — redirects to the non-blocking selection handler."""
        self._on_basic_station_selected(current, None)

    def _refresh_basic_station_tracks(self, station_id: int) -> None:
        """Reload the tracks table for a given station (including duplicates)."""
        songs = [dict(row) for row in self.db.list_basic_station_songs(station_id)]
        self._populate_basic_station_tracks_table(songs)
        sync_track_table_column_widths(self._basic_station_tracks_table)
        self._schedule_track_source_health_checks(songs)

    def _create_basic_station(self) -> None:
        name, ok = get_text(self, "New Station", "Station name:")
        if not ok or not name.strip():
            return
        try:
            folder = self.db.next_basic_station_folder(max_folder=99)
        except ValueError:
            max_station_folders = 99
            VintageMessageBox.warning(
                self,
                "Limit Reached",
                f"All {max_station_folders} station folders are in use.",
            )
            return
        self.db.create_basic_station(name.strip(), folder)
        self._refresh_basic_station_list()
        self._update_basic_stations_size()

    def _rename_basic_station(self) -> None:
        item = self._basic_station_list.currentItem()
        if item is None:
            return
        station_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        station = self.db.get_basic_station(station_id)
        if station is None:
            return
        name, ok = get_text(
            self, "Rename Station", "New name:", text=station["name"]
        )
        if ok and name.strip():
            self.db.update_basic_station(station_id, name=name.strip())
            self._refresh_basic_station_list()

    def _delete_basic_station(self) -> None:
        item = self._basic_station_list.currentItem()
        if item is None:
            return
        station_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        reply = VintageMessageBox.question(
            self, "Delete Station",
            f"Delete station '{item.text().split('  (')[0]}'?\nThis will remove the station and its track list.",
        )
        if reply == VintageMessageBox.StandardButton.Yes:
            self.db.delete_basic_station(station_id)
            self._refresh_basic_station_list()
            self._basic_station_tracks_table.setRowCount(0)
            self._basic_station_detail.setText("Select a station to view tracks.")
            self._update_basic_stations_size()

    def _on_basic_station_reordered(self) -> None:
        ids = []
        for i in range(self._basic_station_list.count()):
            item = self._basic_station_list.item(i)
            if item:
                sid = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if sid is not None:
                    ids.append(sid)
        if ids:
            self.db.update_basic_station_order(ids)
            self._refresh_basic_station_list()
            self._update_basic_stations_size()

    def _get_selected_basic_station_id(self) -> Optional[int]:
        """Return the selected station id, or None."""
        item = self._basic_station_list.currentItem()
        if item is None:
            return None
        return item.data(QtCore.Qt.ItemDataRole.UserRole)

    def _warn_basic_station_exceeds_255_tracks(self) -> None:
        """Warn when a station would exceed 255 tracks (custom firmware); optional 'don't show again'."""
        if self.db.get_setting("basic_suppress_track_count_over_255_warning", "0") == "1":
            return
        box = VintageMessageBox(self)
        box.setIcon(VintageMessageBox.Icon.Information)
        box.setWindowTitle("Track Count Warning")
        box.setText(
            "This station exceeds 255 tracks. Custom software may support this, "
            "but behavior depends on your target firmware."
        )
        cb = QtWidgets.QCheckBox("Don't show again")
        box.setCheckBox(cb)
        box.setStandardButtons(VintageMessageBox.StandardButton.Ok)
        box.exec()
        if cb.isChecked():
            self.db.set_setting("basic_suppress_track_count_over_255_warning", "1")

    def _add_tracks_to_basic_station(self) -> None:
        """Browse for audio files from file explorer, import to library, and add to selected station."""
        station_id = self._get_selected_basic_station_id()
        if station_id is None:
            VintageMessageBox.information(self, "No Station", "Select a station first.")
            return

        current_count = len(self.db.list_basic_station_tracks(station_id))
        max_tracks = self._current_max_tracks_per_station()
        if self._is_track_limit_enforced() and current_count >= max_tracks:
            VintageMessageBox.warning(
                self, "Track Limit",
                f"This station already has {current_count} tracks (max {max_tracks} per folder in this mode).",
            )
            return

        last_dir = self.db.get_setting("basic_last_import_dir", str(Path.home()))
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add Tracks to Station", last_dir, "Audio Files (*.*)",
        )
        if not files:
            return

        self.db.set_setting("basic_last_import_dir", str(Path(files[0]).parent))

        remaining = max_tracks - current_count
        if self._is_track_limit_enforced() and len(files) > remaining:
            VintageMessageBox.warning(
                self, "Track Limit",
                f"Only {remaining} more track(s) can be added (max {max_tracks} per station). "
                f"Adding the first {remaining}.",
            )
            files = files[:remaining]
        elif (not self._is_track_limit_enforced()) and (current_count + len(files) > BASIC_MAX_TRACKS_PER_STATION):
            self._warn_basic_station_exceeds_255_tracks()

        song_ids = self.import_files([Path(f) for f in files], silent=True)
        if song_ids:
            next_order = self.db.next_basic_station_track_order(station_id)
            for sid in song_ids:
                self.db.add_song_to_basic_station(station_id, sid, next_order)
                next_order += 1
            self._refresh_basic_station_tracks(station_id)
            self._refresh_basic_station_list()
            self._update_basic_stations_size()
            self._schedule_conversion_prefetch(song_ids)

    def _import_files_to_basic_station(self, paths: list) -> None:
        """Handle file drop onto the station tracks table: import and add to current station."""
        station_id = self._get_selected_basic_station_id()
        if station_id is None:
            VintageMessageBox.information(self, "No Station", "Select a station first, then drop files.")
            return

        current_count = len(self.db.list_basic_station_tracks(station_id))
        max_tracks = self._current_max_tracks_per_station()
        remaining = max_tracks - current_count
        if self._is_track_limit_enforced() and remaining <= 0:
            VintageMessageBox.warning(
                self, "Track Limit",
                f"This station already has {current_count} tracks (max {max_tracks} per folder in this mode).",
            )
            return

        song_ids = self.import_files(paths, silent=True)
        if song_ids:
            if self._is_track_limit_enforced() and len(song_ids) > remaining:
                VintageMessageBox.warning(
                    self, "Track Limit",
                    f"Only {remaining} more track(s) can be added. Adding the first {remaining}.",
                )
                song_ids = song_ids[:remaining]
            elif (not self._is_track_limit_enforced()) and (current_count + len(song_ids) > BASIC_MAX_TRACKS_PER_STATION):
                self._warn_basic_station_exceeds_255_tracks()
            next_order = self.db.next_basic_station_track_order(station_id)
            for sid in song_ids:
                self.db.add_song_to_basic_station(station_id, sid, next_order)
                next_order += 1
            self._refresh_basic_station_tracks(station_id)
            self._refresh_basic_station_list()
            self._update_basic_stations_size()
            self._schedule_conversion_prefetch(song_ids)

    def _import_folders_as_basic_stations(self, folders: list[Path]) -> None:
        """Create one station per dropped folder and import its files as tracks."""
        if not folders:
            return

        current_stations = len(self.db.list_basic_stations())
        max_station_folders = 99 if self._uses_custom_software() else 98
        free_station_slots = max(0, max_station_folders - current_stations)
        if free_station_slots <= 0:
            VintageMessageBox.warning(
                self,
                "Station Limit",
                f"All {max_station_folders} station folders are already in use.",
            )
            return

        unique_folders: List[Path] = []
        seen: set[str] = set()
        for folder in folders:
            if not folder.exists() or not folder.is_dir():
                continue
            key = str(folder)
            if key in seen:
                continue
            seen.add(key)
            unique_folders.append(folder)
        if not unique_folders:
            return

        if len(unique_folders) > free_station_slots:
            VintageMessageBox.warning(
                self,
                "Station Limit",
                f"Only {free_station_slots} station slot(s) are available. "
                f"Importing the first {free_station_slots} folder(s).",
            )
            unique_folders = unique_folders[:free_station_slots]

        dlg = TaskProgressDialog(
            parent=self,
            title="Importing Folders as Stations",
            func=self._import_folders_as_basic_stations_worker,
            args=(
                unique_folders,
                self.db,
                self._current_max_tracks_per_station(),
                self._is_track_limit_enforced(),
                max_station_folders,
            ),
            kwargs={},
        )

        def on_success(result):
            created = int(result.get("created", 0))
            imported_tracks = int(result.get("imported_tracks", 0))
            skipped_folders = int(result.get("skipped_folders", 0))
            truncated_stations = int(result.get("truncated_stations", 0))
            first_created_id = result.get("first_created_id")

            self.refresh_library()
            self._refresh_basic_station_list()
            if first_created_id is not None:
                for row in range(self._basic_station_list.count()):
                    item = self._basic_station_list.item(row)
                    if item and item.data(QtCore.Qt.ItemDataRole.UserRole) == first_created_id:
                        self._basic_station_list.setCurrentRow(row)
                        break
            self._update_basic_stations_size()

            details: List[str] = []
            if skipped_folders:
                details.append(f"{skipped_folders} folder(s) had no importable files")
            if truncated_stations:
                details.append(
                    f"{truncated_stations} station(s) capped at {self._current_max_tracks_per_station()} tracks"
                )
            detail_text = ""
            if details:
                detail_text = "\n" + "\n".join(f"- {line}" for line in details)
            VintageMessageBox.information(
                self,
                "Stations Imported",
                f"Created {created} station(s) with {imported_tracks} track(s).{detail_text}",
            )

        def on_error(msg):
            self.refresh_library()
            self._refresh_basic_station_list()
            self._update_basic_stations_size()
            VintageMessageBox.warning(
                self, "Station Import Error", f"Error during station import:\n\n{msg}"
            )

        dlg.on_success = on_success
        dlg.on_error = on_error
        dlg.exec()

    @staticmethod
    def _import_folders_as_basic_stations_worker(
        folders: List[Path],
        db: DatabaseManager,
        max_tracks_per_station: int,
        enforce_track_limit: bool,
        max_station_folders: int,
        progress_callback: Optional[Callable[..., Any]] = None,
    ) -> Dict[str, Optional[int]]:
        """Background worker for folder -> station import."""
        created = 0
        imported_tracks = 0
        skipped_folders = 0
        truncated_stations = 0
        first_created_id: Optional[int] = None

        total = len(folders)
        for idx, folder in enumerate(folders, start=1):
            if progress_callback:
                progress_callback(
                    idx - 1,
                    total,
                    f"Importing station folder {idx}/{total}: {folder.name}",
                )

            files = sorted([p for p in folder.rglob("*") if p.is_file()])
            if not files:
                skipped_folders += 1
                continue

            try:
                folder_number = db.next_basic_station_folder(max_folder=max_station_folders)
            except ValueError:
                break

            station_name = folder.name.strip() or f"Station {folder_number:02d}"
            station_id = db.create_basic_station(station_name, folder_number)
            song_ids: List[int] = []

            for file_path in files:
                try:
                    metadata = extract_metadata(file_path)
                    file_hash = compute_file_hash(file_path)
                    existing = db.get_song_by_hash_size(file_hash, metadata["file_size"])
                    if existing is None:
                        existing = db.get_song_by_path(metadata["file_path"])
                    if existing is not None:
                        old_fp = existing["file_path"]
                        new_fp = metadata["file_path"]
                        if new_fp != old_fp and Path(new_fp).exists() and not Path(old_fp).exists():
                            db.update_song(int(existing["id"]), {"file_path": new_fp})
                        song_ids.append(int(existing["id"]))
                        continue

                    song_id = db.add_song(
                        original_filename=metadata["original_filename"],
                        file_path=metadata["file_path"],
                        title=metadata["title"],
                        artist=metadata["artist"],
                        duration=metadata["duration"],
                        file_hash=file_hash,
                        file_size=metadata["file_size"],
                        format=metadata["format"],
                    )
                    song_ids.append(song_id)
                except Exception:
                    continue

            if not song_ids:
                db.delete_basic_station(station_id)
                skipped_folders += 1
                continue

            if enforce_track_limit:
                limited_song_ids = song_ids[:max_tracks_per_station]
                if len(song_ids) > max_tracks_per_station:
                    truncated_stations += 1
            else:
                limited_song_ids = song_ids[:max_tracks_per_station]

            next_order = db.next_basic_station_track_order(station_id)
            for sid in limited_song_ids:
                db.add_song_to_basic_station(station_id, sid, next_order)
                next_order += 1

            created += 1
            imported_tracks += len(limited_song_ids)
            if first_created_id is None:
                first_created_id = station_id

            if progress_callback:
                progress_callback(
                    idx,
                    total,
                    f"Imported {folder.name}: {len(limited_song_ids)} track(s) into station {folder_number:02d}",
                )

        if progress_callback:
            progress_callback(total, total, "Station import complete")

        return {
            "created": created,
            "imported_tracks": imported_tracks,
            "skipped_folders": skipped_folders,
            "truncated_stations": truncated_stations,
            "first_created_id": first_created_id,
        }

    def _persist_basic_station_track_order(self) -> None:
        """Persist track order after drag-reorder in the station tracks table.
        Rebuilds the track list from the current table order, preserving duplicates."""
        item = self._basic_station_list.currentItem()
        if item is None:
            return
        station_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        table = self._basic_station_tracks_table
        song_ids = []
        for row in range(table.rowCount()):
            title_item = table.item(row, 0)
            if title_item:
                sid = title_item.data(QtCore.Qt.ItemDataRole.UserRole)
                if sid is not None:
                    song_ids.append(sid)
        if song_ids:
            self.db.replace_basic_station_tracks(station_id, song_ids)
            self._refresh_basic_station_tracks(station_id)
            self._update_basic_stations_size()

    def _remove_songs_from_basic_station(self) -> None:
        station_item = self._basic_station_list.currentItem()
        if station_item is None:
            return
        station_id = station_item.data(QtCore.Qt.ItemDataRole.UserRole)
        selected = self._basic_station_tracks_table.selectedItems()
        bst_ids = set()
        for sel in selected:
            row = sel.row()
            title_item = self._basic_station_tracks_table.item(row, 0)
            if title_item:
                bst_id = title_item.data(QtCore.Qt.ItemDataRole.UserRole + 1)
                if bst_id is not None:
                    bst_ids.add(bst_id)
        for bst_id in bst_ids:
            self.db.remove_basic_station_track(bst_id)
        self._refresh_basic_station_tracks(station_id)
        self._refresh_basic_station_list()
        self._update_basic_stations_size()

    # ── Basic-mode SD root wrappers (auto-refresh capacity) ──

    def _select_sd_root_basic(self) -> None:
        """Re-detect the same SD card by saved labels (no wrong-card dialog)."""
        self.detect_basic_sd_root()
        self._refresh_basic_sd_capacity()

    def _select_sd_root_manual_basic(self) -> None:
        """Pick a removable drive from the list (dropdown if several). Wrong-card warning is only on Sync."""
        self.select_sd_root(manual=True)
        self._refresh_basic_sd_capacity()

    def _browse_sd_root_basic(self) -> None:
        """Browse SD root and auto-refresh capacity."""
        self.browse_sd_root()
        self._refresh_basic_sd_capacity()

    # ── Basic-mode context menus ──

    def _show_station_context_menu(self, pos) -> None:
        item = self._basic_station_list.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        if item:
            station_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            rename_act = menu.addAction("Rename Station")
            rename_act.triggered.connect(self._rename_basic_station)
            del_act = menu.addAction("Delete Station")
            del_act.triggered.connect(self._delete_basic_station)
            menu.addSeparator()
            add_act = menu.addAction("Add Tracks...")
            add_act.triggered.connect(self._add_tracks_to_basic_station)
        new_act = menu.addAction("New Station")
        new_act.triggered.connect(self._create_basic_station)
        menu.exec(self._basic_station_list.viewport().mapToGlobal(pos))

    def _show_station_track_context_menu(self, pos) -> None:
        table = self._basic_station_tracks_table
        item = table.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        add_act = menu.addAction("Add Tracks...")
        add_act.triggered.connect(self._add_tracks_to_basic_station)
        if item:
            menu.addSeparator()
            row = item.row()
            title_item = table.item(row, 0)
            sid = (
                int(title_item.data(QtCore.Qt.ItemDataRole.UserRole))
                if title_item
                and title_item.data(QtCore.Qt.ItemDataRole.UserRole) is not None
                else None
            )
            if sid is not None:
                replace_act = menu.addAction("Replace source file…")
                replace_act.triggered.connect(
                    lambda checked=False, _sid=sid: self._replace_song_source_path(_sid)
                )
            remove_act = menu.addAction("Remove Selected")
            remove_act.triggered.connect(self._remove_songs_from_basic_station)
        menu.exec(table.viewport().mapToGlobal(pos))

    # ── Basic-mode estimated size ──

    def _update_basic_stations_size(self) -> None:
        """Calculate and display estimated total size of all station tracks."""
        if not hasattr(self, "_basic_stations_size_label"):
            return
        stations = self.db.list_basic_stations()
        total_bytes = 0
        for station in stations:
            songs = self.db.list_basic_station_songs(station["id"])
            for song in songs:
                size = song["file_size"]
                if size:
                    total_bytes += size
        if total_bytes == 0:
            self._basic_stations_size_label.setText("")
        elif total_bytes < 1024 * 1024:
            self._basic_stations_size_label.setText(f"~{total_bytes / 1024:.0f} KB")
        elif total_bytes < 1024 * 1024 * 1024:
            self._basic_stations_size_label.setText(f"~{total_bytes / (1024 * 1024):.1f} MB")
        else:
            self._basic_stations_size_label.setText(f"~{total_bytes / (1024 * 1024 * 1024):.2f} GB")
        if self._is_basic_like_mode():
            QtCore.QTimer.singleShot(0, self._check_basic_sd_sync)

    # ── Basic-mode SD sync ──

    def _sync_basic_to_sd(self) -> None:
        """Sync basic-mode stations to SD card."""
        sd_root = self._resolve_sd_root()
        if not sd_root:
            VintageMessageBox.warning(self, "No SD Card", "Select an SD card first.")
            return

        stations = self.db.list_basic_stations()
        if not stations:
            VintageMessageBox.information(self, "No Stations", "Create at least one station with tracks first.")
            return

        if not self._basic_confirm_first_sd_sync_target(str(sd_root)):
            return

        if not self._basic_confirm_different_card(str(sd_root), for_sync=True):
            return

        sd_display = self._basic_sd_display_text()
        library_name = self._lib_registry.active_library_name() or "this library"

        choice_dlg = SyncChoiceDialog(
            self,
            sd_display=sd_display,
            library_name=library_name,
            show_fast_sync=self._experimental_fast_sync_enabled(),
            volume_mismatch=self._basic_volume_mismatch_pair(str(sd_root)),
        )
        if choice_dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        choice = choice_dlg.choice
        if not choice:
            return

        if choice == "fast":
            if not self._basic_confirm_broken_sources_before_sync():
                return
            self._on_experimental_sd_disk_image()
            return

        force_clean = False
        if choice == "replace":
            confirm_dlg = ReplaceConfirmDialog(
                self,
                sd_display=sd_display,
                library_name=library_name,
            )
            if confirm_dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            force_clean = True

        if not self._basic_confirm_broken_sources_before_sync():
            return

        software_source = self._software_source_for_sync()
        dlg = TaskProgressDialog(
            parent=self,
            title="Sync Stations to SD" + (" (clean)" if force_clean else ""),
            func=self.sd_manager.sync_library_basic,
            args=(sd_root,),
            kwargs={
                "force_clean": force_clean,
                "conversion_profile": self._selected_conversion_profile(),
                "dfplayer_eq": self._selected_dfplayer_eq() if software_source == "our" else "normal",
                "use_conversion_cache": self._retain_conversion_cache(),
            },
            cancelable=True,
            cancel_callback_kwarg="should_cancel",
        )

        def on_success(result):
            conversion_failures: List[Dict[str, Any]] = []
            missing_paths: List[Dict[str, str]] = []
            if isinstance(result, dict):
                copied = int(result.get("copied", 0))
                skipped = int(result.get("skipped", 0))
                raw_cf = result.get("conversion_failures")
                if isinstance(raw_cf, list):
                    conversion_failures = [x for x in raw_cf if isinstance(x, dict)]
                raw_mp = result.get("missing_source_paths")
                if isinstance(raw_mp, list):
                    missing_paths = [x for x in raw_mp if isinstance(x, dict)]
                result_sd_root = result.get("sd_root")
                if result_sd_root:
                    self.sd_root = str(result_sd_root)
                    self.db.set_setting("sd_root", self.sd_root)
            else:
                copied, skipped = result
            self.statusBar().showMessage(
                f"Basic sync complete. Copied: {copied}, Skipped: {skipped}", 5000
            )
            if missing_paths:
                n_mp = len(missing_paths)
                self._show_scrollable_broken_paths_dialog(
                    window_title="Some tracks were skipped",
                    headline=(
                        f"{n_mp} track{'s' if n_mp != 1 else ''} could not be found and "
                        "were not copied to the SD card."
                    ),
                    explanation=(
                        "Update the file path (Library or station track list: right-click → "
                        "Replace source file…) or remove the tracks, then sync again.\n\n"
                        "Full list:"
                    ),
                    entries=missing_paths,
                    line_fmt=lambda e: (
                        f"{e.get('title', '?')}  ({e.get('station', '?')})\n{e.get('path', '?')}"
                    ),
                    proceed_text=None,
                )
            if conversion_failures:
                show_n = min(15, len(conversion_failures))
                detail_lines = []
                for item in conversion_failures[:show_n]:
                    name = str(item.get("name") or Path(str(item.get("path", ""))).name)
                    err = str(item.get("error") or "unknown error").strip()
                    if len(err) > 200:
                        err = err[:200] + "…"
                    detail_lines.append(f"{name}\n  {err}")
                tail = ""
                if len(conversion_failures) > show_n:
                    tail = f"\n\n… and {len(conversion_failures) - show_n} more (full paths in log)."
                VintageMessageBox.warning(
                    self,
                    "Some files failed to convert",
                    "These library files could not be converted to MP3 and were not copied "
                    "to the SD card. Fix or remove the bad files and sync again.\n\n"
                    + "\n\n".join(detail_lines)
                    + tail,
                )
            else:
                VintageMessageBox.information(
                    self,
                    "Sync complete",
                    f"Library synced to the SD card.\n\nCopied: {copied}\nSkipped: {skipped}",
                )
            self._refresh_library_source_health_ui()
            for _w in (
                getattr(self, "_basic_debug_widget", None),
                getattr(self, "_device_debug_widget", None),
            ):
                if _w is not None and hasattr(_w, "refresh_library_db_and_now_playing"):
                    _w.refresh_library_db_and_now_playing()
            if self.sd_root:
                try:
                    preserved = ""
                    if isinstance(result, dict):
                        preserved = str(
                            result.get("preserved_volume_label") or ""
                        ).strip()
                    if not preserved and self.sd_root:
                        preserved = self.sd_manager.capture_volume_label_before_sync(
                            Path(self.sd_root)
                        )
                    if preserved and self.sd_manager.set_sync_target_volume_label(
                        Path(self.sd_root), label=preserved
                    ):
                        self.db.set_setting("sd_volume_label", preserved)
                        self.sd_label = preserved
                        self.db.set_setting("sd_label", preserved)
                        if sys.platform == "darwin" and not Path(self.sd_root).is_dir():
                            new_path = Path("/Volumes") / preserved
                            if new_path.is_dir():
                                self.sd_root = str(new_path)
                                self.db.set_setting("sd_root", self.sd_root)
                    tag = self._basic_sd_path_volume_tag(self.sd_root)
                    if tag:
                        self.db.set_setting("basic_trusted_sd_volume", tag)
                    try:
                        serial = _get_volume_serial(Path(self.sd_root)).strip()
                        if serial:
                            self.db.set_setting("basic_trusted_sd_serial", serial)
                    except OSError:
                        pass
                except Exception:
                    pass
            self._refresh_basic_sd_after_sync()
            if self.db.get_setting("auto_eject_after_sync", "0") == "1" and self.sd_root:
                QtCore.QTimer.singleShot(1500, lambda: self.safely_remove_sd(auto=True, attempt=1))

        def on_error(msg):
            if "Sync cancelled by user" in str(msg):
                self.statusBar().showMessage("Basic sync cancelled.", 4000)
                return
            VintageMessageBox.critical(
                self,
                "Sync Error",
                f"Error during basic sync:\n\n{msg}",
            )

        dlg.on_success = on_success
        dlg.on_error = on_error
        dlg.exec()

    def _on_experimental_sd_disk_image(self) -> None:
        """Experimental: clean sync via FAT32 image — build image, then write to physical SD."""
        if not self._is_basic_like_mode():
            return
        sd_root = self._resolve_sd_root()
        if not sd_root or not Path(sd_root).is_dir():
            VintageMessageBox.warning(
                self,
                "No SD folder",
                "Select an SD card mount point or folder to use as the sync target.",
            )
            return
        stations = self.db.list_basic_stations()
        if not stations:
            VintageMessageBox.information(
                self,
                "No stations",
                "Create at least one station with tracks before installing to an SD card.",
            )
            return

        if not self._basic_confirm_first_sd_sync_target(str(sd_root)):
            return
        if not self._basic_confirm_different_card(str(sd_root), for_sync=True):
            return

        missing_pyfatfs = pyfatfs_dependency_message()
        if missing_pyfatfs:
            VintageMessageBox.warning(
                self,
                "Missing dependency",
                missing_pyfatfs,
            )
            return

        sd_p = Path(sd_root)

        if platform.system() not in ("Windows", "Darwin"):
            intro = VintageMessageBox(self)
            intro.setWindowTitle("Experimental: SD disk image (export only)")
            intro.setIcon(VintageMessageBox.Icon.Information)
            intro.setText(
                "Raw disk flashing from this app is only implemented on Windows and macOS.\n\n"
                "You can still save a FAT32 .img built with pyfatfs and flash it with Etcher, "
                "Pi Imager, or dd on this platform."
            )
            intro.setStandardButtons(
                VintageMessageBox.StandardButton.Ok | VintageMessageBox.StandardButton.Cancel
            )
            if intro.exec() != VintageMessageBox.StandardButton.Ok:
                return
            out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Save disk image",
                "",
                "Disk image (*.img);;All files (*.*)",
            )
            if not out_path:
                return
            if not out_path.lower().endswith(".img"):
                out_path = out_path + ".img"
            out_p = Path(out_path)

            def _worker_export(
                *,
                progress_callback: Optional[Callable] = None,
                should_cancel: Optional[Callable[[], bool]] = None,
            ) -> dict:
                ok, err = run_experimental_sd_disk_image_export(
                    sd_p,
                    out_p,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )
                if not ok:
                    raise RuntimeError(err or "Disk image export failed.")
                return {"path": str(out_p)}

            dlg = TaskProgressDialog(
                parent=self,
                title="Building SD disk image (experimental)",
                func=_worker_export,
                args=(),
                kwargs={},
                cancelable=True,
                cancel_callback_kwarg="should_cancel",
            )

            def on_ok_export(_result: object) -> None:
                self.statusBar().showMessage(f"Disk image saved: {out_p}", 8000)
                VintageMessageBox.information(
                    self,
                    "Disk image",
                    f"Image saved to:\n{out_p}\n\nFlash it with your preferred tool, then eject safely.",
                )

            dlg.on_success = on_ok_export
            dlg.on_error = lambda msg: VintageMessageBox.critical(
                self,
                "Disk image failed",
                msg,
            )
            dlg.exec()
            return

        use_darwin = platform.system() == "Darwin"
        if use_darwin:
            default_bsd = darwin_default_bsd_disk_from_volume_path(sd_p)
            wiz = SdDiskImageFlashWizardDialog(
                self,
                sd_root=sd_p,
                default_disk_number=None,
                default_darwin_bsd_disk=default_bsd,
            )
        else:
            letter = windows_drive_letter_from_path(sd_p)
            default_disk = windows_disk_number_for_drive_letter(letter) if letter else None
            wiz = SdDiskImageFlashWizardDialog(
                self,
                sd_root=sd_p,
                default_disk_number=default_disk,
                default_darwin_bsd_disk=None,
            )
        if wiz.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        disk_number: Optional[int] = None
        bsd_disk: Optional[str] = None
        if use_darwin:
            bsd_disk = wiz.selected_darwin_bsd_disk
            if not bsd_disk:
                return
        else:
            disk_number = wiz.selected_disk_number
            if disk_number is None:
                return

        def _selected_disk_size_bytes() -> Optional[int]:
            if use_darwin:
                return darwin_get_disk_size_bytes(bsd_disk) if bsd_disk else None
            return windows_get_disk_size_bytes(disk_number) if disk_number is not None else None

        software_source = self._software_source_for_sync()
        dfplayer_eq = self._selected_dfplayer_eq() if software_source == "our" else "normal"
        conv_profile = self._selected_conversion_profile()
        ds = _selected_disk_size_bytes()
        reuse_cached = self._can_reuse_cached_sd_image(
            conv_profile=conv_profile,
            dfplayer_eq=dfplayer_eq,
            disk_size_bytes=ds,
        )
        cache_dir = app_data_dir() / "sd_image_cache"
        last_img = cache_dir / LAST_CACHED_SD_IMAGE_FILENAME

        if use_darwin and bsd_disk:
            target_label = bsd_disk
        else:
            target_label = f"Drive {disk_number}"
        confirm_lines = [
            f"Install your music library on {target_label}?",
            "",
            f"Card size: {format_disk_size(ds) if ds else 'unknown'}",
            "",
            "Everything already on that card will be erased.",
        ]
        if reuse_cached:
            confirm_lines.extend(
                [
                    "",
                    "Your library has not changed — the saved install image will be reused.",
                ]
            )
        if use_darwin:
            euid = os.geteuid() if hasattr(os, "geteuid") else 0
            if euid != 0:
                confirm_lines.extend(
                    [
                        "",
                        "You may be asked for your password to write to the card.",
                    ]
                )
        elif not is_windows_admin():
            confirm_lines.extend(
                [
                    "",
                    "You may see a security prompt asking permission to write to the card.",
                ]
            )
        reply = VintageMessageBox.question(
            self,
            "Confirm install",
            "\n".join(confirm_lines),
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
            VintageMessageBox.StandardButton.No,
        )
        if reply != VintageMessageBox.StandardButton.Yes:
            return

        def _worker_sd_image(
            *,
            progress_callback: Optional[Callable] = None,
            should_cancel: Optional[Callable[[], bool]] = None,
        ) -> dict:
            cache_dir.mkdir(parents=True, exist_ok=True)
            staging_root = cache_dir / "staging"
            img_path = last_img

            def _export_cb(_c: int, _t: int, m: str) -> None:
                if progress_callback and _t > 0:
                    progress_callback(_c, _t, m)

            def _manifest_data_bytes() -> Optional[int]:
                manifest = load_cached_sd_image_manifest(cache_dir)
                if not manifest:
                    return None
                try:
                    raw = manifest.get("data_bytes")
                    if raw is None:
                        return None
                    val = int(raw)
                    return val if val > 0 else None
                except (TypeError, ValueError):
                    return None

            try:
                if reuse_cached:
                    if progress_callback:
                        progress_callback(
                            0,
                            0,
                            "Library unchanged — using saved install image…",
                        )
                    if not img_path.is_file() or img_path.stat().st_size <= 0:
                        raise RuntimeError(f"Missing saved install image: {img_path}")
                    known_data = _manifest_data_bytes()
                    if use_darwin:
                        assert bsd_disk is not None
                        ok2, err2 = write_image_to_physical_disk_darwin(
                            img_path,
                            bsd_disk,
                            progress_callback=progress_callback,
                            should_cancel=should_cancel,
                            known_data_bytes=known_data,
                        )
                    else:
                        assert disk_number is not None
                        ok2, err2 = write_image_to_physical_disk(
                            img_path,
                            disk_number,
                            progress_callback=progress_callback,
                            should_cancel=should_cancel,
                            known_data_bytes=known_data,
                        )
                    if not ok2:
                        raise RuntimeError(err2 or "Could not write to the SD card.")
                    return {"ok": True, "reused": True}

                if progress_callback:
                    progress_callback(
                        0,
                        0,
                        "Preparing your music on this computer…",
                    )
                shutil.rmtree(staging_root, ignore_errors=True)
                staging_root.mkdir(parents=True, exist_ok=True)

                def _sync_cb(c: int, t: int, m: str) -> None:
                    if progress_callback:
                        progress_callback(c, t if t else 0, f"Prepare: {m}")

                self.sd_manager.sync_library_basic(
                    staging_root,
                    force_clean=False,
                    progress_callback=_sync_cb,
                    should_cancel=should_cancel,
                    conversion_profile=conv_profile,
                    dfplayer_eq=dfplayer_eq,
                    copy_destination_label="PC staging folder (for disk image)",
                    sync_log_prefix="Prepare (PC staging)",
                    use_conversion_cache=self._retain_conversion_cache(),
                )
                est2 = suggest_image_size_bytes(staging_root)
                _disk_bytes = _selected_disk_size_bytes()
                if _disk_bytes is not None and est2 > _disk_bytes:
                    raise RuntimeError(
                        f"SD card is too small: need about {format_disk_size(est2)}, "
                        f"but the selected card is {format_disk_size(_disk_bytes)}."
                    )

                ok, err = run_experimental_sd_disk_image_export(
                    staging_root,
                    img_path,
                    size_bytes=_disk_bytes,
                    progress_callback=_export_cb,
                    should_cancel=should_cancel,
                )
                if not ok:
                    try:
                        img_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise RuntimeError(err or "Could not create the install image.")

                staging_manifest = SDManager._read_sync_manifest(staging_root)
                known_data = estimate_folder_bytes(staging_root)
                if staging_manifest and staging_manifest.get("stations"):
                    try:
                        save_cached_sd_image_manifest(
                            cache_dir,
                            stations=staging_manifest["stations"],
                            conversion_profile=conv_profile,
                            dfplayer_eq=dfplayer_eq,
                            image_size_bytes=int(img_path.stat().st_size),
                            data_bytes=known_data,
                        )
                    except OSError:
                        pass

                if progress_callback:
                    progress_callback(0, 0, "Writing to SD card…")
                if use_darwin:
                    assert bsd_disk is not None
                    ok2, err2 = write_image_to_physical_disk_darwin(
                        img_path,
                        bsd_disk,
                        progress_callback=progress_callback,
                        should_cancel=should_cancel,
                        known_data_bytes=known_data,
                    )
                else:
                    assert disk_number is not None
                    ok2, err2 = write_image_to_physical_disk(
                        img_path,
                        disk_number,
                        progress_callback=progress_callback,
                        should_cancel=should_cancel,
                        known_data_bytes=known_data,
                    )
                if not ok2:
                    raise RuntimeError(err2 or "Could not write to the SD card.")
                return {"ok": True, "reused": False}
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)

        dlg = TaskProgressDialog(
            parent=self,
            title="Installing to SD card",
            func=_worker_sd_image,
            args=(),
            kwargs={},
            cancelable=True,
            cancel_callback_kwarg="should_cancel",
        )

        def on_ok_sd(_result: object) -> None:
            self.statusBar().showMessage("SD card install finished.", 8000)
            VintageMessageBox.information(
                self,
                "Done",
                "Your music is on the SD card.\n\n"
                "Safely remove the card, put it in the radio, and turn the radio on.",
            )

        def on_error_sd(msg: str) -> None:
            if use_darwin and DARWIN_FDA_REQUIRED_MARKER in msg:
                display_msg = msg.replace(DARWIN_FDA_REQUIRED_MARKER + "\n", "")
                dlg_fda = VintageMessageBox(self)
                dlg_fda.setWindowTitle("Permission needed")
                dlg_fda.setText(display_msg)
                dlg_fda.setIcon(VintageMessageBox.Icon.Warning)
                open_btn = dlg_fda.addButton(
                    "Open System Settings", VintageMessageBox.ButtonRole.ActionRole
                )
                dlg_fda.addButton(VintageMessageBox.StandardButton.Ok)
                dlg_fda.exec()
                if dlg_fda.clickedButton() is open_btn:
                    import subprocess as _sp
                    _sp.Popen(
                        [
                            "open",
                            "x-apple.systempreferences:com.apple.preference.security"
                            "?Privacy_AllFiles",
                        ]
                    )
                return
            if "cancelled by user" in str(msg).lower():
                self.statusBar().showMessage("SD card install cancelled.", 4000)
                return
            VintageMessageBox.critical(self, "SD card install failed", msg)

        dlg.on_success = on_ok_sd
        dlg.on_error = on_error_sd
        dlg.exec()

    def _refresh_basic_sd_tab_on_select(self) -> None:
        """SD Card tab selected: rebind mount, capacity, sync banner, source-health icons."""
        self._try_rebind_basic_sd_mount()
        self._update_sd_root_label()
        self._refresh_basic_sd_capacity()
        self._check_basic_sd_sync()
        self._refresh_library_source_health_ui()

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab switches: lazy-load debug widgets, check sync status."""
        # Advanced mode: Device Debug tab lazy-load
        if self._device_debug_tab_index >= 0 and index == self._device_debug_tab_index:
            self._ensure_device_debug_widget_loaded()
            self._check_device_tab_sync()

        # Basic mode: Load Music (SD Card) tab is now index 0 (shown first).
        # Full refresh + wait cursor only on first visit per session (reset on library
        # switch / tab rebuild). Later visits skip to avoid re-scanning the whole library.
        if self._is_basic_like_mode() and index == 0:
            if not getattr(self, "_sd_card_tab_enter_refresh_done", False):
                self._sd_card_tab_enter_refresh_done = True
                with self._wait_cursor_scope():
                    self._refresh_basic_sd_tab_on_select()

        # Legacy mode: Devices tab warning
        if self.devices_view_mode == "legacy" and index == 3 and hasattr(self, "_check_basic_sd_pico_warning"):
            self._check_basic_sd_pico_warning()

    def _check_device_tab_sync(self) -> None:
        """If library and SD card are out of sync, show a warning on the Device Debug tab.
        Only show when our sync-target SD card is present (so we don't warn when the card is unplugged).
        """
        if not self.sd_manager.is_sync_target_sd_present(
            self.sd_root, self.db.get_setting("sd_volume_label")
        ):
            self.device_sync_warning.setVisible(False)
            return
        results = self.sd_manager.validate_sd()
        actual_size_mismatches = [
            item for item in results.get("size_mismatch", [])
            if item.get("reason") == "size_mismatch"
        ]
        source_missing = results.get("source_file_missing", [])
        total_issues = (
            len(source_missing) +
            len(results.get("missing_sd_path", [])) +
            len(results.get("missing_file", [])) +
            len(actual_size_mismatches) +
            len(results.get("hash_mismatch", []))
        )
        if total_issues > 0:
            parts = []
            if source_missing:
                parts.append(
                    f"{len(source_missing)} track(s) have broken file paths — "
                    "update or remove them in the Library before syncing"
                )
            n = len(results.get("missing_sd_path", []))
            if n:
                parts.append(f"{n} tracks not yet on the SD card")
            n = len(results.get("missing_file", []))
            if n:
                parts.append(f"{n} files missing from SD card")
            if actual_size_mismatches:
                parts.append(f"{len(actual_size_mismatches)} files differ in size")
            n = len(results.get("hash_mismatch", []))
            if n:
                parts.append(f"{n} files changed since last sync")
            self.device_sync_warning.setText(
                "Your SD card differs from your library: " + ". ".join(parts)
            )
            self.device_sync_warning.setVisible(True)
        else:
            self.device_sync_warning.setVisible(False)

    def _build_library_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        controls_widget = QtWidgets.QWidget()
        controls = QtWidgets.QHBoxLayout(controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        import_btn = QtWidgets.QPushButton("Import Files")
        import_btn.clicked.connect(self.open_import_dialog)
        import_folder_btn = QtWidgets.QPushButton("Import Folder")
        import_folder_btn.clicked.connect(self.import_folder_dialog)
        sync_btn = QtWidgets.QPushButton("Sync to SD")
        sync_btn.clicked.connect(self.sync_to_sd)
        edit_btn = QtWidgets.QPushButton("Edit Selected")
        edit_btn.clicked.connect(self.edit_selected_metadata)
        delete_btn = QtWidgets.QPushButton("Remove Selected")
        delete_btn.clicked.connect(self.delete_selected_songs)
        controls.addWidget(import_btn)
        controls.addWidget(import_folder_btn)
        controls.addWidget(sync_btn)
        controls.addStretch()
        controls.addWidget(edit_btn)
        controls.addWidget(delete_btn)

        self._library_controls_widget = controls_widget
        layout.addWidget(self.library_search)
        layout.addWidget(controls_widget)
        layout.addWidget(self.library_table)
        return widget

    def _build_albums_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)

        left_panel = QtWidgets.QVBoxLayout()
        left_panel.addWidget(QtWidgets.QLabel("Albums (drag to reorder)"))
        left_panel.addWidget(self.album_list)

        # Move up / down buttons for album list
        album_move_btns = QtWidgets.QHBoxLayout()
        album_up_btn = QtWidgets.QPushButton("Move Up")
        album_down_btn = QtWidgets.QPushButton("Move Down")
        album_up_btn.setToolTip("Move the selected album up in the list")
        album_down_btn.setToolTip("Move the selected album down in the list")
        album_up_btn.clicked.connect(lambda: self._move_list_item(self.album_list, -1))
        album_down_btn.clicked.connect(lambda: self._move_list_item(self.album_list, 1))
        album_move_btns.addWidget(album_up_btn)
        album_move_btns.addWidget(album_down_btn)
        left_panel.addLayout(album_move_btns)

        album_buttons = QtWidgets.QHBoxLayout()
        create_btn = QtWidgets.QPushButton("New Album")
        delete_btn = QtWidgets.QPushButton("Delete Album")
        add_btn = QtWidgets.QPushButton("Add Selected Songs")
        remove_btn = QtWidgets.QPushButton("Remove Selected")
        details_btns = QtWidgets.QHBoxLayout()
        rename_btn = QtWidgets.QPushButton("Rename")
        desc_btn = QtWidgets.QPushButton("Edit Description")
        rename_btn.clicked.connect(self.rename_album)
        desc_btn.clicked.connect(self.edit_album_description)
        details_btns.addWidget(rename_btn)
        details_btns.addWidget(desc_btn)
        create_btn.clicked.connect(self.create_album)
        delete_btn.clicked.connect(self.delete_album)
        add_btn.clicked.connect(self.add_selected_to_album)
        remove_btn.clicked.connect(self.remove_selected_from_album)
        album_buttons.addWidget(create_btn)
        album_buttons.addWidget(delete_btn)
        left_panel.addLayout(album_buttons)
        left_panel.addLayout(details_btns)
        left_panel.addWidget(add_btn)
        left_panel.addWidget(remove_btn)

        right_panel = QtWidgets.QVBoxLayout()
        self.album_details = QtWidgets.QLabel("Select an album to view details.")
        self.album_details.setWordWrap(True)
        right_panel.addWidget(self.album_details)
        right_panel.addWidget(self.album_songs_table, 1)

        layout.addLayout(left_panel, 1)
        layout.addLayout(right_panel, 2)

        self.album_list.currentItemChanged.connect(self.refresh_album_songs)
        return widget

    def _build_playlists_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)

        left_panel = QtWidgets.QVBoxLayout()
        left_panel.addWidget(QtWidgets.QLabel("Playlists (drag to reorder)"))
        left_panel.addWidget(self.playlist_list)

        # Move up / down buttons for playlist list
        playlist_move_btns = QtWidgets.QHBoxLayout()
        playlist_up_btn = QtWidgets.QPushButton("Move Up")
        playlist_down_btn = QtWidgets.QPushButton("Move Down")
        playlist_up_btn.setToolTip("Move the selected playlist up in the list")
        playlist_down_btn.setToolTip("Move the selected playlist down in the list")
        playlist_up_btn.clicked.connect(lambda: self._move_list_item(self.playlist_list, -1))
        playlist_down_btn.clicked.connect(lambda: self._move_list_item(self.playlist_list, 1))
        playlist_move_btns.addWidget(playlist_up_btn)
        playlist_move_btns.addWidget(playlist_down_btn)
        left_panel.addLayout(playlist_move_btns)

        playlist_buttons = QtWidgets.QHBoxLayout()
        create_btn = QtWidgets.QPushButton("New Playlist")
        delete_btn = QtWidgets.QPushButton("Delete Playlist")
        add_btn = QtWidgets.QPushButton("Add Selected Songs")
        remove_btn = QtWidgets.QPushButton("Remove Selected")
        details_btns = QtWidgets.QHBoxLayout()
        rename_btn = QtWidgets.QPushButton("Rename")
        desc_btn = QtWidgets.QPushButton("Edit Description")
        rename_btn.clicked.connect(self.rename_playlist)
        desc_btn.clicked.connect(self.edit_playlist_description)
        details_btns.addWidget(rename_btn)
        details_btns.addWidget(desc_btn)
        create_btn.clicked.connect(self.create_playlist)
        delete_btn.clicked.connect(self.delete_playlist)
        add_btn.clicked.connect(self.add_selected_to_playlist)
        remove_btn.clicked.connect(self.remove_selected_from_playlist)
        playlist_buttons.addWidget(create_btn)
        playlist_buttons.addWidget(delete_btn)
        left_panel.addLayout(playlist_buttons)
        left_panel.addLayout(details_btns)
        left_panel.addWidget(add_btn)
        left_panel.addWidget(remove_btn)

        right_panel = QtWidgets.QVBoxLayout()
        self.playlist_details = QtWidgets.QLabel("Select a playlist to view details.")
        self.playlist_details.setWordWrap(True)
        right_panel.addWidget(self.playlist_details)
        right_panel.addWidget(self.playlist_songs_table, 1)

        layout.addLayout(left_panel, 1)
        layout.addLayout(right_panel, 2)

        self.playlist_list.currentItemChanged.connect(self.refresh_playlist_songs)
        return widget

    def _build_sd_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        # ---- Device Profile selector bar ----
        self._profile_bar = ProfileSelectorBar(self.db, self)
        self._profile_bar.profile_changed.connect(self._on_profile_changed)
        layout.addWidget(self._profile_bar)

        # ---- Storage (shared: root + Detect + Browse) ----
        storage_group = QtWidgets.QGroupBox("Storage & target")
        storage_layout = QtWidgets.QVBoxLayout(storage_group)
        root_layout = QtWidgets.QHBoxLayout()
        root_layout.addWidget(QtWidgets.QLabel("SD / media root:"))
        if not _qt_widget_alive(getattr(self, "sd_root_label", None)):
            self.sd_root_label = QtWidgets.QLabel()
        root_layout.addWidget(self.sd_root_label)
        detect_btn = QtWidgets.QPushButton("Detect")
        detect_btn.setToolTip("Auto-detect removable drives (e.g. SD card or USB) as the storage root.")
        detect_btn.clicked.connect(self.select_sd_root)
        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.setToolTip("Choose a folder on your computer to use as the storage root (e.g. SD card mount or a folder for testing).")
        browse_btn.clicked.connect(self.browse_sd_root)
        root_layout.addWidget(detect_btn)
        root_layout.addWidget(browse_btn)
        storage_layout.addLayout(root_layout)
        layout.addWidget(storage_group)

        # ---- Stacked content: Basic (0) | Advanced (1) ----
        self._devices_stack = QtWidgets.QStackedWidget()
        self._devices_stack.addWidget(self._build_sd_tab_basic_content())
        self._devices_stack.addWidget(self._build_sd_tab_advanced_content())
        self._devices_stack.setCurrentIndex(0 if self._is_basic_like_mode() else 1)
        if self._is_basic_like_mode():
            self._check_basic_sd_pico_warning()
        layout.addWidget(self._devices_stack)

        layout.addWidget(QtWidgets.QLabel("Validation / import status:"))
        layout.addWidget(self.sd_status, 1)

        self._load_active_profile()
        return widget

    def _build_sd_tab_basic_content(self) -> QtWidgets.QWidget:
        """Basic Devices view: board selector, notes, pin config, Sync, Eject, Setup."""
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)

        # Board selector (shared widget reference stored for profile loading)
        self._basic_board_selector = BoardSelectorWidget()
        self._basic_board_selector.board_changed.connect(self._on_board_changed)
        layout.addWidget(self._basic_board_selector)

        # Profile notes
        notes_row = QtWidgets.QHBoxLayout()
        notes_row.addWidget(QtWidgets.QLabel("Profile Notes:"))
        self._basic_notes_edit = QtWidgets.QPlainTextEdit()
        self._basic_notes_edit.setMaximumHeight(50)
        self._basic_notes_edit.setPlaceholderText("Describe your wiring, audio module, use case...")
        self._basic_notes_edit.textChanged.connect(self._on_basic_notes_changed)
        notes_row.addWidget(self._basic_notes_edit, 1)
        layout.addLayout(notes_row)

        # Configure Pins button
        pin_row = QtWidgets.QHBoxLayout()
        self._basic_pin_summary = QtWidgets.QLabel()
        self._basic_pin_summary.setStyleSheet("color: gray; font-size: 11px;")
        pin_row.addWidget(self._basic_pin_summary, 1)
        config_pins_btn = QtWidgets.QPushButton("Configure Pins...")
        config_pins_btn.setToolTip("Open pin configuration editor")
        config_pins_btn.clicked.connect(self._open_pin_config_dialog)
        pin_row.addWidget(config_pins_btn)
        layout.addLayout(pin_row)

        self._basic_sd_pico_warning = QtWidgets.QLabel()
        self._basic_sd_pico_warning.setWordWrap(True)
        self._basic_sd_pico_warning.setStyleSheet("color: #c00; font-weight: bold;")
        self._basic_sd_pico_warning.setVisible(False)
        layout.addWidget(self._basic_sd_pico_warning)

        sd_ops_group = QtWidgets.QGroupBox("SD card / media operations")
        sd_ops_layout = QtWidgets.QVBoxLayout(sd_ops_group)
        row = QtWidgets.QHBoxLayout()
        sync_btn = QtWidgets.QPushButton("Sync Library to SD")
        sync_btn.setToolTip("Copy your full library to the storage root for DFPlayer + RP2040.")
        sync_btn.clicked.connect(self.sync_to_sd)
        eject_btn = QtWidgets.QPushButton("Safely Remove SD Card")
        eject_btn.setToolTip("Safely eject the SD card so it can be removed without data loss.")
        eject_btn.clicked.connect(self.safely_remove_sd)
        self._auto_eject_after_sync_cb = QtWidgets.QCheckBox("Automatically safely remove SD card after syncing")
        self._auto_eject_after_sync_cb.setChecked(self.db.get_setting("auto_eject_after_sync", "0") == "1")
        self._auto_eject_after_sync_cb.stateChanged.connect(self._on_auto_eject_after_sync_changed)
        row.addWidget(sync_btn)
        row.addWidget(eject_btn)
        row.addWidget(self._auto_eject_after_sync_cb)
        row.addStretch()
        sd_ops_layout.addLayout(row)
        layout.addWidget(sd_ops_group)

        self._basic_device_group = QtWidgets.QGroupBox("Device")
        device_layout = QtWidgets.QHBoxLayout(self._basic_device_group)
        self._basic_setup_btn = QtWidgets.QPushButton("Install Firmware")
        self._basic_setup_btn.setToolTip("Install firmware and copy the app to your device. Connect the device via USB.")
        self._basic_setup_btn.clicked.connect(
            lambda: QtCore.QTimer.singleShot(0, self._setup_pico_smart)
        )
        device_layout.addWidget(self._basic_setup_btn)
        device_layout.addStretch()
        layout.addWidget(self._basic_device_group)

        layout.addStretch()
        return page

    def _build_sd_tab_advanced_content(self) -> QtWidgets.QWidget:
        """Advanced Devices view: board selector, pin config, full SD ops, firmware install."""
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)

        # Board selector
        self._adv_board_selector = BoardSelectorWidget()
        self._adv_board_selector.board_changed.connect(self._on_board_changed)
        layout.addWidget(self._adv_board_selector)

        # Profile notes
        notes_layout = QtWidgets.QHBoxLayout()
        notes_layout.addWidget(QtWidgets.QLabel("Profile Notes:"))
        self._adv_notes_edit = QtWidgets.QPlainTextEdit()
        self._adv_notes_edit.setMaximumHeight(55)
        self._adv_notes_edit.setPlaceholderText("Describe your wiring, audio module, use case...")
        self._adv_notes_edit.textChanged.connect(self._on_notes_changed)
        notes_layout.addWidget(self._adv_notes_edit, 1)
        layout.addLayout(notes_layout)

        # Pin configuration button + summary
        pin_row = QtWidgets.QHBoxLayout()
        self._adv_pin_summary = QtWidgets.QLabel()
        self._adv_pin_summary.setStyleSheet("color: gray; font-size: 11px;")
        pin_row.addWidget(self._adv_pin_summary, 1)
        adv_config_pins_btn = QtWidgets.QPushButton("Configure Pins...")
        adv_config_pins_btn.setToolTip("Open pin configuration editor")
        adv_config_pins_btn.clicked.connect(self._open_pin_config_dialog)
        pin_row.addWidget(adv_config_pins_btn)
        layout.addLayout(pin_row)

        # Legacy audio target combo (hidden, kept for backward compat with sync logic)
        self.audio_target_combo = QtWidgets.QComboBox()
        self.audio_target_combo.addItem("DFPlayer + RP2040", "dfplayer_rp2040")
        self.audio_target_combo.addItem("Raspberry Pi 2W/3", "raspberry_pi")
        self.audio_target_combo.setVisible(False)
        idx = self.audio_target_combo.findData(self.audio_target)
        if idx >= 0:
            self.audio_target_combo.setCurrentIndex(idx)
        self.audio_target_combo.currentIndexChanged.connect(self._on_audio_target_changed)
        layout.addWidget(self.audio_target_combo)

        self.pi_convert_checkbox = QtWidgets.QCheckBox("Convert non-MP3 to MP3 when syncing for Pi")
        self.pi_convert_checkbox.setToolTip("When Raspberry Pi is the audio target: if checked, non-MP3 files are converted to MP3 during sync; if unchecked, files are copied as-is (e.g. FLAC, WAV).")
        self.pi_convert_checkbox.setChecked(self.pi_convert_audio)
        self.pi_convert_checkbox.stateChanged.connect(self._on_pi_convert_changed)
        self._update_pi_convert_visibility()
        layout.addWidget(self.pi_convert_checkbox)

        sd_ops_group = QtWidgets.QGroupBox("SD card / media operations")
        sd_ops_layout = QtWidgets.QVBoxLayout(sd_ops_group)
        actions_row = QtWidgets.QHBoxLayout()
        sync_btn = QtWidgets.QPushButton("Sync Library to SD")
        sync_btn.setToolTip("Copy (and convert if needed) your full library to the storage root. Layout depends on Audio target: DFPlayer uses 01/, 02/, 001.mp3; Pi uses VintageRadio/library/. Files that already exist and match will be skipped.")
        sync_btn.clicked.connect(self.sync_to_sd)
        validate_btn = QtWidgets.QPushButton("Validate SD")
        validate_btn.setToolTip("Check that every track in the library has a file on storage and report missing or mismatched files.")
        validate_btn.clicked.connect(self.validate_sd)
        eject_btn = QtWidgets.QPushButton("Safely Remove SD Card")
        eject_btn.setToolTip("Safely eject the SD card so it can be removed without data loss.")
        eject_btn.clicked.connect(self.safely_remove_sd)
        self._auto_eject_after_sync_cb_advanced = QtWidgets.QCheckBox("Automatically safely remove SD card after syncing")
        self._auto_eject_after_sync_cb_advanced.setChecked(self.db.get_setting("auto_eject_after_sync", "0") == "1")
        self._auto_eject_after_sync_cb_advanced.stateChanged.connect(self._on_auto_eject_after_sync_changed)
        import_btn = QtWidgets.QPushButton("Import from SD")
        import_btn.setToolTip("Import albums and playlists that were previously exported to this storage (e.g. from another machine) into your library.")
        import_btn.clicked.connect(self.import_from_sd)
        export_sd_contents_btn = QtWidgets.QPushButton("Export SD contents to folder...")
        export_sd_contents_btn.setToolTip("Run the same sync as \"Sync Library to SD\" but into a folder you choose (e.g. to copy to a USB stick or SD card manually later).")
        export_sd_contents_btn.clicked.connect(self.export_sd_contents_to_folder)
        actions_row.addWidget(sync_btn)
        actions_row.addWidget(validate_btn)
        actions_row.addWidget(eject_btn)
        actions_row.addWidget(self._auto_eject_after_sync_cb_advanced)
        actions_row.addWidget(import_btn)
        actions_row.addWidget(export_sd_contents_btn)
        sd_ops_layout.addLayout(actions_row)
        export_collections_row = QtWidgets.QHBoxLayout()
        export_album_btn = QtWidgets.QPushButton("Export Album")
        export_album_btn.setToolTip("Copy only the selected album to the storage root. Format depends on Audio target (DFPlayer: 01/001.mp3 style; Pi: folder with tracks).")
        export_album_btn.clicked.connect(self.export_album_to_sd)
        export_playlist_btn = QtWidgets.QPushButton("Export Playlist")
        export_playlist_btn.setToolTip("Copy only the selected playlist to the storage root. Format depends on Audio target.")
        export_playlist_btn.clicked.connect(self.export_playlist_to_sd)
        export_collections_row.addWidget(QtWidgets.QLabel("Album:"))
        export_collections_row.addWidget(self.sd_album_combo)
        export_collections_row.addWidget(export_album_btn)
        export_collections_row.addSpacing(20)
        export_collections_row.addWidget(QtWidgets.QLabel("Playlist:"))
        export_collections_row.addWidget(self.sd_playlist_combo)
        export_collections_row.addWidget(export_playlist_btn)
        sd_ops_layout.addLayout(export_collections_row)
        layout.addWidget(sd_ops_group)

        rp2040_group = QtWidgets.QGroupBox("RP2040 (Pico)")
        rp2040_layout = QtWidgets.QHBoxLayout(rp2040_group)
        export_rp2040_btn = QtWidgets.QPushButton("Export for RP2040")
        export_rp2040_btn.setToolTip("Save main.py, radio_core.py, and components/ to a folder on your PC. Copy that folder to the Pico (e.g. with Thonny) after installing MicroPython.")
        export_rp2040_btn.clicked.connect(self.export_rp2040_firmware)
        install_pico_btn = QtWidgets.QPushButton("Install to Pico")
        install_pico_btn.setToolTip("Copy the application files directly to a connected Pico via USB. Requires mpremote (pip install mpremote) and MicroPython already installed on the Pico.")
        install_pico_btn.clicked.connect(self.install_to_pico)
        mp_tools_hint = QtWidgets.QLabel(
            "MicroPython only: Tools → MicroPython tab"
        )
        mp_tools_hint.setStyleSheet("color: #666; font-style: italic;")
        rp2040_layout.addWidget(export_rp2040_btn)
        rp2040_layout.addWidget(install_pico_btn)
        rp2040_layout.addWidget(mp_tools_hint)
        rp2040_layout.addStretch()
        layout.addWidget(rp2040_group)

        pi_group = QtWidgets.QGroupBox("Raspberry Pi")
        pi_layout = QtWidgets.QHBoxLayout(pi_group)
        export_pi_btn = QtWidgets.QPushButton("Export for Raspberry Pi")
        export_pi_btn.setToolTip("Save main_pi.py, radio_core.py, components/pi_hardware.py, and requirements_pi.txt to a folder. Copy that folder to the Pi (e.g. via USB or SCP) and run pip3 install -r requirements_pi.txt.")
        export_pi_btn.clicked.connect(self.export_pi_firmware)
        deploy_pi_btn = QtWidgets.QPushButton("Deploy to Pi")
        deploy_pi_btn.setToolTip("Copy the application files to a Raspberry Pi over the network via SCP, then run pip3 install on the Pi. Enter the Pi's IP address when prompted. Requires SSH access.")
        deploy_pi_btn.clicked.connect(self.deploy_to_pi)
        pi_layout.addWidget(export_pi_btn)
        pi_layout.addWidget(deploy_pi_btn)
        pi_layout.addStretch()
        layout.addWidget(pi_group)

        return page

    def _on_audio_target_changed(self) -> None:
        self.audio_target = self.audio_target_combo.currentData() or "dfplayer_rp2040"
        self.db.set_setting("audio_target", self.audio_target)
        self._update_pi_convert_visibility()

    def _on_pi_convert_changed(self) -> None:
        self.pi_convert_audio = self.pi_convert_checkbox.isChecked()
        self.db.set_setting("pi_convert_audio", "1" if self.pi_convert_audio else "0")

    def _update_pi_convert_visibility(self) -> None:
        if hasattr(self, "pi_convert_checkbox"):
            self.pi_convert_checkbox.setVisible(self.audio_target == "raspberry_pi")

    # ---- Device profile / pin config handlers ----

    def _load_active_profile(self) -> None:
        """Load the active device profile into all UI widgets."""
        import json as _json
        profile = self.db.get_active_profile()
        if profile is None:
            return

        board_id = profile["board_id"]
        bp = get_board_profile(board_id)
        board_name = bp.name if bp else board_id
        notes = profile["notes"] or ""

        try:
            pin_cfg = _json.loads(profile["pin_config_json"]) if profile["pin_config_json"] else {}
        except (_json.JSONDecodeError, TypeError):
            pin_cfg = bp.default_pin_config if bp else {}

        # Dynamic button label
        if hasattr(self, "_basic_setup_btn"):
            if bp and bp.platform == "cpython":
                self._basic_setup_btn.setText("Deploy to Pi")
            elif bp and "pico" in bp.id:
                self._basic_setup_btn.setText("Setup Pico")
            else:
                self._basic_setup_btn.setText("Install Firmware")

        if hasattr(self, "_basic_device_group"):
            self._basic_device_group.setTitle(board_name)

        # Board selectors (both views)
        for selector in ("_basic_board_selector", "_adv_board_selector"):
            w = getattr(self, selector, None)
            if w is not None:
                w.set_board_id(board_id)

        # Notes fields (both views)
        for notes_edit in ("_basic_notes_edit", "_adv_notes_edit"):
            w = getattr(self, notes_edit, None)
            if w is not None:
                w.blockSignals(True)
                w.setPlainText(notes)
                w.blockSignals(False)

        # Pin summary labels (both views)
        summary = self._build_pin_summary(pin_cfg)
        for label_attr in ("_basic_pin_summary", "_adv_pin_summary"):
            lbl = getattr(self, label_attr, None)
            if lbl is not None:
                lbl.setText(summary)

        # Audio target (derived from board platform)
        if bp and bp.platform == "cpython":
            target = "raspberry_pi"
        else:
            target = "dfplayer_rp2040"
        if hasattr(self, "audio_target_combo"):
            idx = self.audio_target_combo.findData(target)
            if idx >= 0:
                self.audio_target_combo.setCurrentIndex(idx)
        self.audio_target = target
        self.db.set_setting("audio_target", target)
        self._update_pi_convert_visibility()

    @staticmethod
    def _build_pin_summary(pin_cfg: dict) -> str:
        pins = pin_cfg.get("pins", {})
        if not pins:
            return "(no pins configured)"
        parts = [f"{k}={v}" for k, v in sorted(pins.items())]
        text = ", ".join(parts)
        if len(text) > 80:
            text = text[:77] + "..."
        driver = pin_cfg.get("_custom_driver", "")
        prefix = f"Pins: {text}"
        return prefix

    def _on_profile_changed(self, profile_id: int) -> None:
        self._load_active_profile()

    def _on_board_changed(self, board_id: str) -> None:
        import json as _json
        profile = self.db.get_active_profile()
        if profile is None:
            return
        bp = get_board_profile(board_id)
        if bp is None:
            return

        import copy
        new_cfg = copy.deepcopy(bp.default_pin_config)
        self.db.update_device_profile(
            profile["id"],
            board_id=board_id,
            pin_config_json=_json.dumps(new_cfg),
        )
        self._load_active_profile()

    def _on_notes_changed(self) -> None:
        """Handler for advanced view notes changes."""
        profile = self.db.get_active_profile()
        if profile is None:
            return
        self.db.update_device_profile(
            profile["id"],
            notes=self._adv_notes_edit.toPlainText(),
        )

    def _on_basic_notes_changed(self) -> None:
        """Handler for basic view notes changes."""
        profile = self.db.get_active_profile()
        if profile is None:
            return
        self.db.update_device_profile(
            profile["id"],
            notes=self._basic_notes_edit.toPlainText(),
        )
        if hasattr(self, "_adv_notes_edit"):
            self._adv_notes_edit.blockSignals(True)
            self._adv_notes_edit.setPlainText(self._basic_notes_edit.toPlainText())
            self._adv_notes_edit.blockSignals(False)

    def _open_pin_config_dialog(self) -> None:
        """Open the pin configuration popup dialog."""
        import json as _json
        profile = self.db.get_active_profile()
        if profile is None:
            return

        bp = get_board_profile(profile["board_id"])
        try:
            pin_cfg = _json.loads(profile["pin_config_json"]) if profile["pin_config_json"] else {}
        except (_json.JSONDecodeError, TypeError):
            pin_cfg = bp.default_pin_config if bp else {}

        dlg = PinConfigDialog(
            config=pin_cfg,
            board_profile=bp,
            custom_driver_path=profile["custom_hw_driver_path"] or "",
            parent=self,
        )
        dlg.exec()
        if dlg.was_accepted():
            new_cfg = dlg.get_config()
            new_driver = dlg.get_custom_driver_path()
            if new_cfg is not None:
                self.db.update_device_profile(
                    profile["id"],
                    pin_config_json=_json.dumps(new_cfg),
                    custom_hw_driver_path=new_driver,
                )
                self._load_active_profile()

    def _on_auto_eject_after_sync_changed(self) -> None:
        sender = self.sender()
        if isinstance(sender, QtWidgets.QCheckBox) and _qt_widget_alive(sender):
            checked = sender.isChecked()
        elif _qt_widget_alive(getattr(self, "_auto_eject_after_sync_cb", None)):
            checked = self._auto_eject_after_sync_cb.isChecked()
        elif _qt_widget_alive(getattr(self, "_basic_auto_eject_cb", None)):
            checked = self._basic_auto_eject_cb.isChecked()
        elif _qt_widget_alive(getattr(self, "_settings_auto_eject_cb", None)):
            checked = self._settings_auto_eject_cb.isChecked()
        else:
            checked = False
        self.db.set_setting("auto_eject_after_sync", "1" if checked else "0")
        # Keep the other view's checkboxes in sync (Basic vs Advanced); skip destroyed widgets.
        cb = getattr(self, "_auto_eject_after_sync_cb", None)
        if _qt_widget_alive(cb) and sender is not cb:
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        cb_adv = getattr(self, "_auto_eject_after_sync_cb_advanced", None)
        if _qt_widget_alive(cb_adv) and sender is not cb_adv:
            cb_adv.blockSignals(True)
            cb_adv.setChecked(checked)
            cb_adv.blockSignals(False)
        cb_basic = getattr(self, "_basic_auto_eject_cb", None)
        if _qt_widget_alive(cb_basic) and sender is not cb_basic:
            cb_basic.blockSignals(True)
            cb_basic.setChecked(checked)
            cb_basic.blockSignals(False)
        cb_settings = getattr(self, "_settings_auto_eject_cb", None)
        if _qt_widget_alive(cb_settings) and sender is not cb_settings:
            cb_settings.blockSignals(True)
            cb_settings.setChecked(checked)
            cb_settings.blockSignals(False)

    def _create_song_table(self, reorderable: bool = False) -> QtWidgets.QTableWidget:
        table: QtWidgets.QTableWidget
        if reorderable:
            table = CollectionDropTable()
        else:
            table = QtWidgets.QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Title", "Artist", "Duration", "Format"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        return table

    def _apply_saved_settings(self) -> None:
        auto_backup = self.db.get_setting("auto_backup", "0") == "1"
        retention_raw = self.db.get_setting("backup_retention", "10") or "10"
        self.sd_root = self.db.get_setting("sd_root", "") or ""
        self.sd_auto_detect = self.db.get_setting("sd_auto_detect", "1") == "1"
        self.sd_label = self.db.get_setting("sd_label", "") or ""
        self.audio_target = self.db.get_setting("audio_target", "dfplayer_rp2040") or "dfplayer_rp2040"
        if self.audio_target not in ("dfplayer_rp2040", "raspberry_pi"):
            self.audio_target = "dfplayer_rp2040"
        self.pi_convert_audio = self.db.get_setting("pi_convert_audio", "1") == "1"
        self.devices_view_mode = self.db.get_setting("view_mode", "basic") or "basic"
        if self.devices_view_mode == "advanced_legacy":
            self.devices_view_mode = "legacy"
        if self.devices_view_mode not in ("basic", "advanced", "legacy"):
            self.devices_view_mode = "basic"
        try:
            self._ui_zoom_level = max(80, min(200, int(self.db.get_setting("ui_zoom_level", "100") or "100")))
        except (ValueError, TypeError):
            self._ui_zoom_level = 100
        _ui_scale.set_zoom_percent(self._ui_zoom_level)
        self._ui_theme = normalize_theme_id(self.db.get_setting("ui_theme", "vintage"))
        apply_ui_theme(self._ui_theme)
        try:
            retention = max(1, int(retention_raw))
        except ValueError:
            retention = 10
        self.db.auto_backup = auto_backup
        self.db.backup_retention = retention
        self._try_rebind_basic_sd_mount()
        self._update_sd_root_label()

    def _refresh_all(self) -> None:
        self.refresh_library()
        self.refresh_albums()
        self.refresh_playlists()
        self._refresh_basic_stations_if_visible()

    def _refresh_basic_stations_if_visible(self) -> None:
        """Reload basic-mode station list when the active library DB changes.

        ``_refresh_all`` is invoked on library switch, but basic SD Card UI was
        never refreshed — the list kept showing the previous library's stations
        (often empty after switching to a new/empty DB, or stale rows).
        """
        if not self._is_basic_like_mode():
            return
        if not hasattr(self, "_basic_station_list"):
            return
        if not _qt_widget_alive(self._basic_station_list):
            return
        self._refresh_basic_station_list(preserve_selection=False)
        self._update_basic_stations_size()

    def _refresh_library_source_health_ui(self) -> None:
        """Re-read the DB and refresh broken-path icons/tooltips on every track table.

        Intentionally does **not** call ``_update_basic_stations_size`` (that schedules
        ``_check_basic_sd_sync`` again); pair with that call separately when needed.
        """
        if _qt_widget_alive(getattr(self, "library_table", None)):
            self.refresh_library()
        self.refresh_album_songs()
        self.refresh_playlist_songs()
        station_id = self._get_selected_basic_station_id()
        if station_id is not None:
            self._refresh_basic_station_tracks(station_id)

    def _song_source_path_missing(self, song: Any) -> bool:
        """True when the library has no usable path or the file is not on disk."""
        try:
            fp = (song["file_path"] or "").strip()
        except (TypeError, KeyError, IndexError):
            return True
        if not fp:
            return True
        cache = getattr(self, "_song_path_missing_cache", None)
        if cache is not None and fp in cache:
            return cache[fp]
        try:
            missing = not Path(fp).is_file()
        except OSError:
            missing = True
        if cache is not None:
            cache[fp] = missing
        return missing

    def _broken_source_file_tooltip(self, song: Any) -> str:
        try:
            p = (song["file_path"] or "").strip() or "(no path stored)"
        except (TypeError, KeyError, IndexError):
            p = "(no path stored)"
        return (
            f"Source file not found:\n{p}\n\n"
            "Right-click this track and choose Replace source file…, "
            "or remove it from the list."
        )

    def _decorate_track_title_item_source_health(
        self, title_item: QtWidgets.QTableWidgetItem, song: Any
    ) -> None:
        """Show a warning icon + tooltip when the stored source path is broken."""
        if self._song_source_path_missing(song):
            title_item.setIcon(
                self.style().standardIcon(
                    QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning
                )
            )
            title_item.setToolTip(self._broken_source_file_tooltip(song))
        else:
            title_item.setIcon(QIcon())
            title_item.setToolTip("")

    def _show_scrollable_broken_paths_dialog(
        self,
        *,
        window_title: str,
        headline: str,
        explanation: str,
        entries: List[Dict[str, str]],
        line_fmt: Callable[[Dict[str, str]], str],
        proceed_text: Optional[str] = None,
        cancel_text: str = "Cancel",
    ) -> bool:
        """List every broken entry in a scrollable view. Return True if user proceeds (or OK-only)."""
        dlg = ScrollableListConfirmDialog(
            self,
            window_title=window_title,
            headline=headline,
            explanation=explanation,
            entries=entries,
            line_fmt=line_fmt,
            proceed_text=proceed_text,
            cancel_text=cancel_text,
        )
        return dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted

    def _replace_song_source_path(self, song_id: int) -> None:
        """Point an existing library track at a new audio file on disk."""
        row = self.db.get_song_by_id(song_id)
        if row is None:
            return
        prev_path = (row["file_path"] or "").strip()
        start_dir = str(Path(prev_path).parent) if prev_path else str(Path.home())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Replace source file",
            start_dir,
            "Audio Files (*.*)",
        )
        if not path:
            return
        file_path = Path(path)
        if not file_path.is_file():
            return
        try:
            metadata = extract_metadata(file_path)
            file_hash = compute_file_hash(file_path)
        except Exception as e:
            VintageMessageBox.warning(
                self, "Could not read file", str(e) or "Unknown error reading audio file."
            )
            return
        new_path = metadata["file_path"]
        conflict = self.db.get_song_by_path(new_path)
        if conflict is not None and int(conflict["id"]) != song_id:
            t = conflict["title"] or conflict["original_filename"] or new_path
            VintageMessageBox.warning(
                self,
                "Already in library",
                "This file is already linked to another track:\n\n"
                f"{t}\n\n"
                "Remove or update that track first, or pick a different file.",
            )
            return
        self.db.update_song(
            song_id,
            {
                "file_path": new_path,
                "original_filename": metadata["original_filename"],
                "title": metadata["title"],
                "artist": metadata["artist"],
                "duration": metadata["duration"],
                "file_hash": file_hash,
                "file_size": metadata["file_size"],
                "format": metadata["format"],
                "sd_path": "",
            },
        )
        self._refresh_library_source_health_ui()
        self._update_basic_stations_size()
        QtCore.QTimer.singleShot(0, self._check_basic_sd_sync)
        self.statusBar().showMessage("Source file updated.", 5000)

    def refresh_library(self) -> None:
        rows = self.db.list_songs()
        filter_text = self.library_search.text().strip().lower()
        if filter_text:
            rows = [
                song
                for song in rows
                if filter_text
                in " ".join(
                    [
                        str(song["title"] or ""),
                        str(song["artist"] or ""),
                        str(song["format"] or ""),
                        str(song["file_path"] or ""),
                    ]
                ).lower()
            ]
        self._loading_library = True
        self.library_table.setSortingEnabled(False)
        self.library_table.setRowCount(len(rows))
        for row_idx, song in enumerate(rows):
            title_item = QtWidgets.QTableWidgetItem(song["title"] or "")
            title_item.setFlags(
                title_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable
            )
            self._decorate_track_title_item_source_health(title_item, song)
            self.library_table.setItem(row_idx, 0, title_item)
            self._set_table_item(
                self.library_table,
                row_idx,
                1,
                song["artist"],
                editable=True,
            )
            duration = self._format_duration(song["duration"])
            self._set_table_item(self.library_table, row_idx, 2, duration)
            self._set_table_item(self.library_table, row_idx, 3, song["format"])
            self._set_table_item(self.library_table, row_idx, 4, song["file_path"])
            title_item.setData(QtCore.Qt.ItemDataRole.UserRole, song["id"])
        self.library_table.setSortingEnabled(True)
        self._loading_library = False

    def refresh_albums(self) -> None:
        self.album_list.clear()
        for album in self.db.list_albums():
            item = QtWidgets.QListWidgetItem(album["name"])
            item.setData(QtCore.Qt.ItemDataRole.UserRole, album["id"])
            self.album_list.addItem(item)
        if self.album_list.count() > 0 and self.album_list.currentRow() == -1:
            self.album_list.setCurrentRow(0)
        self._refresh_sd_combos()

    def refresh_playlists(self) -> None:
        self.playlist_list.clear()
        for playlist in self.db.list_playlists():
            item = QtWidgets.QListWidgetItem(playlist["name"])
            item.setData(QtCore.Qt.ItemDataRole.UserRole, playlist["id"])
            self.playlist_list.addItem(item)
        if self.playlist_list.count() > 0 and self.playlist_list.currentRow() == -1:
            self.playlist_list.setCurrentRow(0)
        self._refresh_sd_combos()

    def refresh_album_songs(self) -> None:
        if not _qt_widget_alive(getattr(self, "album_songs_table", None)):
            return
        self._update_album_details()
        cur = (
            self.album_list.currentItem()
            if _qt_widget_alive(getattr(self, "album_list", None))
            else None
        )
        self._populate_association_table(cur, self.album_songs_table, is_album=True)

    def refresh_playlist_songs(self) -> None:
        if not _qt_widget_alive(getattr(self, "playlist_songs_table", None)):
            return
        self._update_playlist_details()
        cur = (
            self.playlist_list.currentItem()
            if _qt_widget_alive(getattr(self, "playlist_list", None))
            else None
        )
        self._populate_association_table(cur, self.playlist_songs_table, is_album=False)

    def _populate_association_table(
        self,
        list_item: Optional[QtWidgets.QListWidgetItem],
        table: QtWidgets.QTableWidget,
        *,
        is_album: bool,
    ) -> None:
        if list_item is None:
            table.setRowCount(0)
            return
        entity_id = int(list_item.data(QtCore.Qt.ItemDataRole.UserRole))
        songs = (
            self.db.list_album_songs(entity_id)
            if is_album
            else self.db.list_playlist_songs(entity_id)
        )
        table.setRowCount(len(songs))
        for row_idx, song in enumerate(songs):
            title_item = QtWidgets.QTableWidgetItem(song["title"] or "")
            self._decorate_track_title_item_source_health(title_item, song)
            table.setItem(row_idx, 0, title_item)
            self._set_table_item(table, row_idx, 1, song["artist"])
            duration = self._format_duration(song["duration"])
            self._set_table_item(table, row_idx, 2, duration)
            self._set_table_item(table, row_idx, 3, song["format"])
            title_item.setData(QtCore.Qt.ItemDataRole.UserRole, song["id"])

    def open_import_dialog(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Import Audio Files",
            str(Path.home()),
            "Audio Files (*.*)",
        )
        self.import_files([Path(path) for path in files])

    def import_folder_dialog(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Import Folder",
            str(Path.home()),
        )
        if not folder:
            return
        files = [path for path in Path(folder).rglob("*") if path.is_file()]
        self.import_files(files)

    def import_files(
        self, files: Iterable[Path], *, silent: bool = False
    ) -> List[int]:
        file_list = [p for p in files if p.exists() and p.is_file()]
        if not file_list:
            return []

        # For small imports (≤3 files), do it inline to keep it snappy
        if len(file_list) <= 3:
            return self._import_files_sync(file_list, show_status=not silent)

        if silent:
            return self._import_files_silent_threaded(file_list)

        # For larger imports, run in background thread with progress dialog
        self._pending_import_ids: List[int] = []

        dlg = TaskProgressDialog(
            parent=self,
            title="Importing Files",
            func=self._import_files_worker,
            args=(file_list, self.db),
            kwargs={},
        )

        def on_success(result):
            added, skipped, added_ids = result
            self._pending_import_ids = added_ids
            self.refresh_library()
            self._schedule_conversion_prefetch(added_ids)
            self.statusBar().showMessage(
                f"Import complete. Added: {added}, Skipped: {skipped}", 5000
            )

        def on_error(msg):
            self.refresh_library()
            VintageMessageBox.warning(self, "Import Error", f"Error during import:\n\n{msg}")

        dlg.on_success = on_success
        dlg.on_error = on_error
        dlg.exec()
        return getattr(self, "_pending_import_ids", [])

    def _import_files_silent_threaded(self, file_list: List[Path]) -> List[int]:
        """Import many files on a worker thread without a modal progress dialog."""
        results: List[Tuple[int, int, List[int]]] = []
        errors: List[str] = []
        loop = QtCore.QEventLoop(self)
        thread = QtCore.QThread(self)
        worker = _BackgroundWorker(
            self._import_files_worker,
            file_list,
            self.db,
            progress_callback=None,
        )
        worker.moveToThread(thread)

        def on_finished(result: object) -> None:
            results.append(result)  # type: ignore[arg-type]
            thread.quit()
            loop.quit()

        def on_error(msg: str) -> None:
            errors.append(msg)
            thread.quit()
            loop.quit()

        thread.started.connect(worker.run)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        thread.start()
        loop.exec()
        thread.wait(300_000)
        worker.deleteLater()
        thread.deleteLater()

        self.refresh_library()
        if errors:
            VintageMessageBox.warning(
                self, "Import Error", f"Error during import:\n\n{errors[0]}"
            )
            return []
        if not results:
            return []
        _added, _skipped, added_ids = results[0]
        self._schedule_conversion_prefetch(added_ids)
        return added_ids

    @staticmethod
    def _import_files_worker(
        file_list: List[Path],
        db: DatabaseManager,
        progress_callback: Optional[Callable[..., Any]] = None,
    ) -> Tuple[int, int, List[int]]:
        """Background worker: import files into the database."""
        added = 0
        skipped = 0
        added_ids: List[int] = []
        total = len(file_list)

        for i, path in enumerate(file_list):
            if progress_callback:
                progress_callback(i, total, f"Importing: {path.name}")
            try:
                metadata = extract_metadata(path)
                file_hash = compute_file_hash(path)
                existing = db.get_song_by_hash_size(file_hash, metadata["file_size"])
                if existing is None:
                    existing = db.get_song_by_path(metadata["file_path"])
                if existing is not None:
                    # Fix stale path if the file now lives somewhere else (e.g. different PC)
                    old_fp = existing["file_path"]
                    new_fp = metadata["file_path"]
                    if new_fp != old_fp and Path(new_fp).exists() and not Path(old_fp).exists():
                        db.update_song(int(existing["id"]), {"file_path": new_fp})
                    skipped += 1
                    added_ids.append(int(existing["id"]))
                    continue
                song_id = db.add_song(
                    original_filename=metadata["original_filename"],
                    file_path=metadata["file_path"],
                    title=metadata["title"],
                    artist=metadata["artist"],
                    duration=metadata["duration"],
                    file_hash=file_hash,
                    file_size=metadata["file_size"],
                    format=metadata["format"],
                )
                added += 1
                added_ids.append(song_id)
            except Exception:
                skipped += 1

        if progress_callback:
            progress_callback(total, total, "Import complete!")
        return added, skipped, added_ids

    def _import_files_sync(
        self, files: Iterable[Path], *, show_status: bool = True
    ) -> List[int]:
        """Synchronous import for small batches (≤3 files)."""
        added = 0
        skipped = 0
        added_ids: List[int] = []
        for path in files:
            if not path.exists() or not path.is_file():
                continue
            try:
                metadata = extract_metadata(path)
                file_hash = compute_file_hash(path)
                existing = self.db.get_song_by_hash_size(file_hash, metadata["file_size"])
                if existing is None:
                    existing = self.db.get_song_by_path(metadata["file_path"])
                if existing is not None:
                    old_fp = existing["file_path"]
                    new_fp = metadata["file_path"]
                    if new_fp != old_fp and Path(new_fp).exists() and not Path(old_fp).exists():
                        self.db.update_song(int(existing["id"]), {"file_path": new_fp})
                    skipped += 1
                    added_ids.append(int(existing["id"]))
                    continue
                song_id = self.db.add_song(
                    original_filename=metadata["original_filename"],
                    file_path=metadata["file_path"],
                    title=metadata["title"],
                    artist=metadata["artist"],
                    duration=metadata["duration"],
                    file_hash=file_hash,
                    file_size=metadata["file_size"],
                    format=metadata["format"],
                )
                added += 1
                added_ids.append(song_id)
            except Exception:
                skipped += 1
        self.refresh_library()
        if show_status:
            self.statusBar().showMessage(
                f"Import complete. Added: {added}, Skipped: {skipped}", 5000
            )
        if added_ids:
            self._schedule_conversion_prefetch(added_ids)
        return added_ids

    def edit_selected_metadata(self) -> None:
        song_ids = self._selected_library_song_ids()
        if not song_ids:
            return
        previous_rows = self.db.get_songs_by_ids(song_ids)
        previous = {
            row["id"]: {"title": row["title"], "artist": row["artist"]}
            for row in previous_rows
        }
        dialog = MetadataDialog(parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        fields = dialog.get_values()
        if not fields:
            return
        updated: Dict[int, Dict[str, str]] = {}
        for row in previous_rows:
            merged = {"title": row["title"], "artist": row["artist"]}
            merged.update(fields)
            updated[row["id"]] = merged
        for song_id in song_ids:
            self.db.update_song(song_id, fields)
        self._push_undo(
            {
                "type": "edit_metadata",
                "previous": previous,
                "updated": updated,
            }
        )
        self.refresh_library()

    def delete_selected_songs(self) -> None:
        song_ids = self._selected_library_song_ids()
        if not song_ids:
            return
        confirm = VintageMessageBox.question(
            self,
            "Remove Songs",
            f"Remove {len(song_ids)} song(s) from the library? Files stay on disk.",
        )
        if confirm != VintageMessageBox.StandardButton.Yes:
            return
        song_rows = self.db.get_songs_by_ids(song_ids)
        album_links = []
        playlist_links = []
        for row in song_rows:
            album_links.extend(
                self.db.conn.execute(
                    "SELECT album_id, song_id, track_order FROM album_songs WHERE song_id = ?;",
                    (row["id"],),
                ).fetchall()
            )
            playlist_links.extend(
                self.db.conn.execute(
                    "SELECT playlist_id, song_id, track_order FROM playlist_songs WHERE song_id = ?;",
                    (row["id"],),
                ).fetchall()
            )
        for song_id in song_ids:
            self.db.delete_song(song_id)
        self._push_undo(
            {
                "type": "remove_songs",
                "songs": song_rows,
                "album_links": album_links,
                "playlist_links": playlist_links,
                "song_ids": song_ids,
            }
        )
        self.refresh_library()

    def create_album(self) -> None:
        name, ok = get_text(self, "New Album", "Album name:")
        if not ok or not name.strip():
            return
        self.db.create_album(name.strip())
        self.refresh_albums()

    def delete_album(self) -> None:
        item = self.album_list.currentItem()
        if item is None:
            return
        album_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        confirm = VintageMessageBox.question(
            self, "Delete Album", f"Delete album '{item.text()}'?"
        )
        if confirm != VintageMessageBox.StandardButton.Yes:
            return
        self.db.delete_album(album_id)
        self.refresh_albums()
        self.album_songs_table.setRowCount(0)

    def rename_album(self) -> None:
        item = self.album_list.currentItem()
        if item is None:
            return
        album_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        name, ok = get_text(
            self, "Rename Album", "Album name:", text=item.text()
        )
        if not ok or not name.strip():
            return
        self.db.update_album(album_id, {"name": name.strip()})
        self.refresh_albums()

    def edit_album_description(self) -> None:
        item = self.album_list.currentItem()
        if item is None:
            return
        album_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        existing = self.db.conn.execute(
            "SELECT description FROM albums WHERE id = ?;", (album_id,)
        ).fetchone()
        existing_text = existing["description"] if existing and existing["description"] else ""
        text, ok = get_multiline_text(
            self, "Album Description", "Description:", text=existing_text
        )
        if not ok:
            return
        self.db.update_album(album_id, {"description": text.strip()})
        self._update_album_details()

    def add_selected_to_album(self) -> None:
        album_item = self.album_list.currentItem()
        if album_item is None:
            return
        album_id = int(album_item.data(QtCore.Qt.ItemDataRole.UserRole))
        song_ids = self._selected_library_song_ids()
        if not song_ids:
            return
        track_order = self.db.next_album_track_order(album_id)
        for song_id in song_ids:
            self.db.add_song_to_album(album_id, song_id, track_order)
            track_order += 1
        self.refresh_album_songs()

    def import_files_to_album(self, files: Iterable[Path]) -> None:
        album_item = self.album_list.currentItem()
        if album_item is None:
            return
        album_id = int(album_item.data(QtCore.Qt.ItemDataRole.UserRole))
        song_ids = self.import_files(files)
        track_order = self.db.next_album_track_order(album_id)
        for song_id in song_ids:
            self.db.add_song_to_album(album_id, song_id, track_order)
            track_order += 1
        self.refresh_album_songs()

    def remove_selected_from_album(self) -> None:
        album_item = self.album_list.currentItem()
        if album_item is None:
            return
        album_id = int(album_item.data(QtCore.Qt.ItemDataRole.UserRole))
        song_ids = self._selected_table_song_ids(self.album_songs_table)
        if not song_ids:
            return
        confirm = VintageMessageBox.question(
            self,
            "Remove Tracks",
            f"Remove {len(song_ids)} track(s) from this album?",
        )
        if confirm != VintageMessageBox.StandardButton.Yes:
            return
        removed = [
            row
            for row in self.db.list_album_tracks(album_id)
            if row["song_id"] in song_ids
        ]
        remaining = [
            song_id
            for song_id in self._table_song_ids(self.album_songs_table)
            if song_id not in song_ids
        ]
        self.db.replace_album_tracks(album_id, remaining)
        if removed:
            self._push_undo(
                {
                    "type": "remove_album_tracks",
                    "album_id": album_id,
                    "tracks": removed,
                    "remaining": remaining,
                }
            )
        self.refresh_album_songs()

    def create_playlist(self) -> None:
        name, ok = get_text(self, "New Playlist", "Playlist name:")
        if not ok or not name.strip():
            return
        self.db.create_playlist(name.strip())
        self.refresh_playlists()

    def delete_playlist(self) -> None:
        item = self.playlist_list.currentItem()
        if item is None:
            return
        playlist_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        confirm = VintageMessageBox.question(
            self, "Delete Playlist", f"Delete playlist '{item.text()}'?"
        )
        if confirm != VintageMessageBox.StandardButton.Yes:
            return
        self.db.delete_playlist(playlist_id)
        self.refresh_playlists()
        self.playlist_songs_table.setRowCount(0)

    def rename_playlist(self) -> None:
        item = self.playlist_list.currentItem()
        if item is None:
            return
        playlist_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        name, ok = get_text(
            self, "Rename Playlist", "Playlist name:", text=item.text()
        )
        if not ok or not name.strip():
            return
        self.db.update_playlist(playlist_id, {"name": name.strip()})
        self.refresh_playlists()

    def edit_playlist_description(self) -> None:
        item = self.playlist_list.currentItem()
        if item is None:
            return
        playlist_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        existing = self.db.conn.execute(
            "SELECT description FROM playlists WHERE id = ?;", (playlist_id,)
        ).fetchone()
        existing_text = (
            existing["description"] if existing and existing["description"] else ""
        )
        text, ok = get_multiline_text(
            self, "Playlist Description", "Description:", text=existing_text
        )
        if not ok:
            return
        self.db.update_playlist(playlist_id, {"description": text.strip()})
        self._update_playlist_details()

    def add_selected_to_playlist(self) -> None:
        playlist_item = self.playlist_list.currentItem()
        if playlist_item is None:
            return
        playlist_id = int(playlist_item.data(QtCore.Qt.ItemDataRole.UserRole))
        song_ids = self._selected_library_song_ids()
        if not song_ids:
            return
        track_order = self.db.next_playlist_track_order(playlist_id)
        for song_id in song_ids:
            self.db.add_song_to_playlist(playlist_id, song_id, track_order)
            track_order += 1
        self.refresh_playlist_songs()

    def import_files_to_playlist(self, files: Iterable[Path]) -> None:
        playlist_item = self.playlist_list.currentItem()
        if playlist_item is None:
            return
        playlist_id = int(playlist_item.data(QtCore.Qt.ItemDataRole.UserRole))
        song_ids = self.import_files(files)
        track_order = self.db.next_playlist_track_order(playlist_id)
        for song_id in song_ids:
            self.db.add_song_to_playlist(playlist_id, song_id, track_order)
            track_order += 1
        self.refresh_playlist_songs()

    def remove_selected_from_playlist(self) -> None:
        playlist_item = self.playlist_list.currentItem()
        if playlist_item is None:
            return
        playlist_id = int(playlist_item.data(QtCore.Qt.ItemDataRole.UserRole))
        song_ids = self._selected_table_song_ids(self.playlist_songs_table)
        if not song_ids:
            return
        confirm = VintageMessageBox.question(
            self,
            "Remove Tracks",
            f"Remove {len(song_ids)} track(s) from this playlist?",
        )
        if confirm != VintageMessageBox.StandardButton.Yes:
            return
        removed = [
            row
            for row in self.db.list_playlist_tracks(playlist_id)
            if row["song_id"] in song_ids
        ]
        remaining = [
            song_id
            for song_id in self._table_song_ids(self.playlist_songs_table)
            if song_id not in song_ids
        ]
        self.db.replace_playlist_tracks(playlist_id, remaining)
        if removed:
            self._push_undo(
                {
                    "type": "remove_playlist_tracks",
                    "playlist_id": playlist_id,
                    "tracks": removed,
                    "remaining": remaining,
                }
            )
        self.refresh_playlist_songs()

    def open_settings(self) -> None:
        sidebar = getattr(self, "_sidebar", None)
        if _qt_widget_alive(sidebar):
            sidebar.set_active(self._PAGE_SETTINGS)
        self._on_sidebar_nav(self._PAGE_SETTINGS)

    def _update_sd_root_label(self) -> None:
        """Update advanced Devices tab label and/or basic SD Card tab label."""
        if not self.sd_root:
            adv_text = "Not set"
            basic_text = "(not set)"
        else:
            vol = self.sd_label or self._get_volume_label(Path(self.sd_root))
            if vol:
                adv_text = f"{self.sd_root} ({vol})"
                basic_text = adv_text
            else:
                adv_text = self.sd_root
                basic_text = self.sd_root
        if _qt_widget_alive(getattr(self, "sd_root_label", None)):
            self.sd_root_label.setText(adv_text)
        if _qt_widget_alive(getattr(self, "_basic_sd_root_label", None)):
            self._basic_sd_root_label.setText(basic_text)

    def _basic_sd_display_text(self) -> str:
        """Human-readable SD target for sync modal subtitles."""
        if not self.sd_root:
            return "(no SD card selected)"
        vol = self.sd_label or self._get_volume_label(Path(self.sd_root))
        if vol:
            return f"{self.sd_root} ({vol})"
        return str(self.sd_root)

    def _get_volume_label(self, path: Path) -> str:
        if hasattr(self.sd_manager, "volume_label"):
            return self.sd_manager.volume_label(path)
        return sd_manager_module._get_volume_label(path)

    def _refresh_sd_combos(self) -> None:
        self.sd_album_combo.blockSignals(True)
        self.sd_playlist_combo.blockSignals(True)
        self.sd_album_combo.clear()
        self.sd_playlist_combo.clear()
        for album in self.db.list_albums():
            self.sd_album_combo.addItem(album["name"], album["id"])
        for playlist in self.db.list_playlists():
            self.sd_playlist_combo.addItem(playlist["name"], playlist["id"])
        self.sd_album_combo.blockSignals(False)
        self.sd_playlist_combo.blockSignals(False)

    def _sd_root_default_index(
        self,
        candidates: List[Tuple[Path, str]],
        identity: set,
    ) -> int:
        default_idx = 0
        if self.sd_root:
            try:
                saved = Path(self.sd_root).expanduser().resolve()
                for i, (path, _label) in enumerate(candidates):
                    try:
                        if path.resolve() == saved:
                            return i
                    except OSError:
                        continue
            except OSError:
                pass
        if identity:
            for i, (path, label) in enumerate(candidates):
                if self._basic_candidate_matches_identity(path, label, identity):
                    return i
        return default_idx

    def _pick_sd_root_from_candidates(
        self,
        candidates: List[Tuple[Path, str]],
        *,
        default_idx: int = 0,
    ) -> Optional[Tuple[str, str]]:
        """Sync-styled combo to pick a detected SD root."""
        choices: List[str] = []
        mapping: Dict[str, str] = {}
        for path, label in candidates:
            display = f"{path} ({label})" if label else str(path)
            choices.append(display)
            mapping[display] = str(path)

        selection, ok = get_item(
            self,
            "Select SD Root",
            "Choose SD card root:",
            choices,
            default_idx,
        )
        if not ok or not selection:
            return None
        new_root = mapping.get(selection, selection)
        new_label = ""
        for path, label in candidates:
            if str(path) == new_root:
                new_label = label or ""
                break
        return new_root, new_label

    def _manual_select_sd_root_dialog(
        self,
        candidates: List[Tuple[Path, str]],
        identity: set,
    ) -> Optional[Tuple[str, str]]:
        """Basic-mode **Select**: combo dropdown of detected roots (one or many)."""
        default_idx = self._sd_root_default_index(candidates, identity)
        return self._pick_sd_root_from_candidates(candidates, default_idx=default_idx)

    def select_sd_root(self, *, manual: bool = False) -> None:
        """Pick SD root from detected removable volumes (dropdown if several).

        When *manual* is False (e.g. advanced Devices "Detect"), we may apply the saved
        path or a single identity match without opening a dialog.

        When *manual* is True (basic-mode **Select**), show the combo dropdown of detected
        drives (same control whether there is one or many; stays on top so it is not hidden).
        """
        candidates = self.sd_manager.detect_sd_roots()
        if not candidates:
            mb = VintageMessageBox(self)
            mb.setIcon(VintageMessageBox.Icon.Information)
            mb.setWindowTitle("SD card")
            mb.setText("No removable drives were detected automatically.")
            mb.setInformativeText(
                "Use <b>Browse</b> next to Select to choose your SD card folder manually, "
                "or reconnect the card and click Detect."
            )
            mb.exec()
            return

        if not manual:
            # Saved path still present (resolved match — handles same card, normalized path).
            if self.sd_root:
                try:
                    saved = Path(self.sd_root).expanduser().resolve()
                    if saved.is_dir():
                        for path, label in candidates:
                            try:
                                if path.resolve() == saved:
                                    lab = (label or "").strip() or (
                                        self._get_volume_label(path) or path.name
                                    )
                                    self.sd_root = str(path)
                                    self.sd_label = lab
                                    self.db.set_setting("sd_root", self.sd_root)
                                    self.db.set_setting("sd_label", self.sd_label)
                                    self._update_sd_root_label()
                                    self._check_basic_sd_sync()
                                    self.statusBar().showMessage(
                                        f"SD card: {self.sd_root}", 4000
                                    )
                                    return
                            except OSError:
                                continue
                except OSError:
                    pass

            identity = self._basic_sd_identity_match_set()
            matched = [
                (path, label)
                for path, label in candidates
                if self._basic_candidate_matches_identity(path, label, identity)
            ]

            if len(matched) == 1:
                path, lab = matched[0]
                new_label = (lab or "").strip() or (self._get_volume_label(path) or "")
                self.sd_root = str(path)
                self.sd_label = new_label
                self.db.set_setting("sd_root", self.sd_root)
                self.db.set_setting("sd_label", self.sd_label)
                self._update_sd_root_label()
                self._check_basic_sd_sync()
                self.statusBar().showMessage(
                    f"Detected SD card: {self.sd_root}", 5000
                )
                return
        else:
            identity = self._basic_sd_identity_match_set()

        if manual:
            picked = self._manual_select_sd_root_dialog(candidates, identity)
            if picked is None:
                return
            new_root, new_label = picked
        elif len(candidates) == 1:
            new_root = str(candidates[0][0])
            new_label = candidates[0][1] or ""
        else:
            default_idx = self._sd_root_default_index(candidates, identity)
            picked = self._pick_sd_root_from_candidates(candidates, default_idx=default_idx)
            if picked is None:
                return
            new_root, new_label = picked
        self.sd_root = new_root
        self.sd_label = new_label or ""
        self.db.set_setting("sd_root", self.sd_root)
        self.db.set_setting("sd_label", self.sd_label)
        self._update_sd_root_label()
        self._check_basic_sd_sync()

    def browse_sd_root(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select SD Card Root",
            str(Path.home()),
        )
        if not folder:
            return
        self.sd_root = folder
        self.sd_label = self._get_volume_label(Path(self.sd_root))
        self.db.set_setting("sd_root", folder)
        self.db.set_setting("sd_label", self.sd_label)
        self._update_sd_root_label()
        self._check_basic_sd_sync()

    def run_backup(self) -> None:
        backup_path = self.db.backup_now()
        if backup_path:
            self.statusBar().showMessage(
                f"Backup created: {backup_path.name}", 5000
            )

    def sync_to_sd(self) -> None:
        sd_root = self._resolve_sd_root()
        if not sd_root:
            return

        # ── Pre-sync: check for missing source files ──
        missing_source_songs = []
        recoverable_from_sd = []
        all_songs = self.db.list_songs()
        for song in all_songs:
            fp = song["file_path"]
            if fp and not Path(fp).exists():
                mapping = self.db.get_sd_mapping(song["id"])
                if mapping:
                    slot_path = sd_root / f"{mapping['folder_number']:02d}" / f"{mapping['track_number']:03d}.mp3"
                    if slot_path.exists():
                        recoverable_from_sd.append((song["id"], song["title"] or "Unknown", str(slot_path)))
                        continue
                missing_source_songs.append(song["title"] or song["original_filename"] or "Unknown")

        # If there are files on SD we can adopt, offer to do that first
        if recoverable_from_sd:
            names = "\n".join(f"  - {title}" for _, title, _ in recoverable_from_sd[:10])
            more = f"\n  ... and {len(recoverable_from_sd) - 10} more" if len(recoverable_from_sd) > 10 else ""
            reply = VintageMessageBox.question(
                self,
                "Recover from SD card",
                f"{len(recoverable_from_sd)} song(s) have missing source files on this PC, "
                f"but copies already exist on the SD card:\n\n{names}{more}\n\n"
                "Link library to the SD card copies so they can be synced in the future?\n"
                "(This updates the library paths to point to the SD card.)",
                VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
                VintageMessageBox.StandardButton.Yes,
            )
            if reply == VintageMessageBox.StandardButton.Yes:
                for song_id, title, slot_path in recoverable_from_sd:
                    self.db.update_song(song_id, {"file_path": slot_path})
                    self.db.update_song_sd_path(song_id, slot_path)
                self.statusBar().showMessage(
                    f"Linked {len(recoverable_from_sd)} song(s) to SD card copies.", 5000
                )
                missing_source_songs = []  # Re-check after recovery
                for song in all_songs:
                    fp = song["file_path"]
                    if fp and not Path(fp).exists():
                        mapping = self.db.get_sd_mapping(song["id"])
                        if mapping:
                            slot_path = sd_root / f"{mapping['folder_number']:02d}" / f"{mapping['track_number']:03d}.mp3"
                            if slot_path.exists():
                                continue
                        missing_source_songs.append(song["title"] or "Unknown")

        # If there are still songs with no source anywhere, warn clearly
        if missing_source_songs:
            total = len(all_songs)
            n_missing = len(missing_source_songs)
            names = "\n".join(f"  - {t}" for t in missing_source_songs[:10])
            more = f"\n  ... and {n_missing - 10} more" if n_missing > 10 else ""
            if n_missing == total:
                VintageMessageBox.critical(
                    self,
                    "Cannot Sync — All Source Files Missing",
                    f"None of the {total} song(s) in your library can be found on this computer.\n\n"
                    f"Paths point to another machine:\n{names}{more}\n\n"
                    "To fix this:\n"
                    "1. Go to Library tab\n"
                    "2. Remove the broken entries (select all → Remove Selected)\n"
                    "3. Import your music files from this PC (Import Files / Import Folder)\n"
                    "4. Re-add songs to your albums/playlists\n"
                    "5. Then Sync to SD again",
                )
                return
            else:
                reply = VintageMessageBox.warning(
                    self,
                    "Missing Source Files",
                    f"{n_missing} of {total} song(s) have missing source files and will NOT be copied:\n\n"
                    f"{names}{more}\n\n"
                    "Continue syncing the remaining songs?\n\n"
                    "(Fix missing songs: Library → Remove broken entries, then re-import from this PC.)",
                    VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.Cancel,
                    VintageMessageBox.StandardButton.Yes,
                )
                if reply == VintageMessageBox.StandardButton.Cancel:
                    return

        # ── Ask for normal vs clean sync ──
        force_clean = False
        reply = VintageMessageBox.question(
            self,
            "SD Card Sync",
            "Sync library to SD card?\n\n"
            "Files that already exist and match will be skipped.\n\n"
            "Click 'Yes' for normal sync (skips existing files).\n"
            "Click 'No' for clean install (re-syncs all files).",
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No | VintageMessageBox.StandardButton.Cancel,
            VintageMessageBox.StandardButton.Yes,
        )
        if reply == VintageMessageBox.StandardButton.Cancel:
            return
        if reply == VintageMessageBox.StandardButton.No:
            force_clean = True

        preserved_volume_label = self.sd_manager.capture_volume_label_before_sync(sd_root)
        
        effective_audio_target = "dfplayer_rp2040" if self._is_basic_like_mode() else self.audio_target
        dlg = TaskProgressDialog(
            parent=self,
            title="SD Card Sync" + (" (clean install)" if force_clean else ""),
            func=self.sd_manager.sync_library,
            args=(sd_root,),
            kwargs={
                "audio_target": effective_audio_target,
                "pi_convert_audio": self.pi_convert_audio,
                "force_clean": force_clean,
            },
        )

        def on_success(result):
            copied, skipped = result
            if skipped > 0 and copied == 0:
                VintageMessageBox.warning(
                    self,
                    "Sync Complete — No Files Copied",
                    f"No music files were copied to the SD card.\n"
                    f"{skipped} file(s) were skipped (source missing or already up to date).\n\n"
                    "If songs are missing, re-import them in the Library tab.",
                )
            else:
                self.statusBar().showMessage(
                    f"SD sync complete. Copied: {copied}, Skipped: {skipped}", 5000
                )
                # Remember sync target by its existing volume name (no forced rename).
                if self.sd_root:
                    try:
                        label = preserved_volume_label or self.sd_manager.capture_volume_label_before_sync(
                            Path(self.sd_root)
                        )
                        if label:
                            if self.sd_manager.set_sync_target_volume_label(
                                Path(self.sd_root), label=label
                            ):
                                self.db.set_setting("sd_volume_label", label)
                                self.sd_label = label
                                self.db.set_setting("sd_label", label)
                            if sys.platform == "darwin" and not Path(self.sd_root).is_dir():
                                new_path = Path("/Volumes") / label
                                if new_path.is_dir():
                                    self.sd_root = str(new_path)
                                    self.db.set_setting("sd_root", self.sd_root)
                    except Exception:
                        pass
                    self._update_sd_root_label()
            # Auto-eject when option is on (for both "files copied" and "nothing copied" outcomes)
            if self.db.get_setting("auto_eject_after_sync", "0") == "1" and self.sd_root:
                QtCore.QTimer.singleShot(1500, lambda: self.safely_remove_sd(auto=True, attempt=1))
            if hasattr(self, 'test_mode_widget') and self.test_mode_widget:
                self.test_mode_widget.refresh_from_db()

        def on_error(msg):
            VintageMessageBox.critical(self, "Sync Error", f"An error occurred during SD sync:\n\n{msg}")

        dlg.on_success = on_success
        dlg.on_error = on_error
        dlg.exec()

    def _clear_sd_storage_selection_after_eject(self) -> None:
        """Drop saved SD path so the UI matches an unplugged card (Detect / Select will re-bind)."""
        self.sd_root = ""
        self.sd_label = ""
        self.db.set_setting("sd_root", "")
        self.db.set_setting("sd_label", "")
        self._update_sd_root_label()
        if self._is_basic_like_mode():
            self._refresh_basic_sd_capacity()
            self._check_basic_sd_sync()

    def safely_remove_sd(self, *, auto: bool = False, attempt: int = 1) -> None:
        """Safely eject/remove the SD card."""
        sd_root = self._resolve_sd_root()
        if not sd_root:
            if not auto:
                VintageMessageBox.warning(
                    self,
                    "No SD Card",
                    "No SD card root selected. Please select an SD card first."
                )
            return

        def _report_success(msg: str) -> None:
            self._clear_sd_storage_selection_after_eject()
            if auto:
                self.statusBar().showMessage(msg, 6000)
            else:
                VintageMessageBox.information(self, "SD Card Ejected", msg)

        def _report_failure(title: str, msg: str) -> None:
            if auto and attempt < 3:
                delay_ms = 1200 * attempt
                QtCore.QTimer.singleShot(delay_ms, lambda: self.safely_remove_sd(auto=True, attempt=attempt + 1))
                return
            if auto:
                self.statusBar().showMessage(f"Auto-eject failed: {msg}", 8000)
            else:
                VintageMessageBox.warning(self, title, msg)

        # Last pass: OSes recreate .Spotlight-V100 / .fseventsd while the volume
        # stays mounted; strip them again right before flush + eject. On macOS,
        # dot_clean -m first matches JaVaWa-style cleanup (AppleDouble on FAT).
        try:
            self.sd_manager.remove_hidden_junk_from_sd(
                sd_root, dot_clean_merge=(sys.platform == "darwin")
            )
        except Exception:
            pass
        if sys.platform == "darwin":
            try:
                subprocess.run(
                    ["mdutil", "-i", "off", str(sd_root)],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
            except Exception:
                pass
            try:
                self.sd_manager.remove_hidden_junk_from_sd(sd_root)
            except Exception:
                pass

        # Flush filesystem buffers before attempting eject (macOS/Linux)
        if sys.platform != "win32":
            try:
                os.sync()
            except (AttributeError, OSError):
                pass

        try:
            import platform
            system = platform.system()
            if system == "Windows":
                drive_letter = sd_root.drive
                if not drive_letter:
                    sd_root_str = str(sd_root)
                    if len(sd_root_str) >= 2 and sd_root_str[1] == ":":
                        drive_letter = sd_root_str[:2]
                if not drive_letter:
                    _report_failure(
                        "Cannot Eject",
                        "Could not determine drive letter. Please eject manually using Windows Explorer."
                    )
                    return
                drive = drive_letter.rstrip(":")
                try:
                    ps_script = (
                        "$sh=New-Object -ComObject Shell.Application;"
                        "$ns=$sh.Namespace(17);"
                        f"$it=$ns.ParseName('{drive}:');"
                        "if($null -eq $it){exit 2};"
                        "$it.InvokeVerb('Eject');"
                        "Start-Sleep -Milliseconds 700;"
                        "exit 0;"
                    )
                    result = subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                        capture_output=True,
                        text=True,
                        timeout=12,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    drive_root = Path(f"{drive}:\\")
                    if result.returncode == 0 and not drive_root.exists():
                        _report_success(f"SD card ({drive}:) has been safely ejected.\n\nYou can now safely remove it.")
                        return
                except Exception:
                    pass

                # Fallback: low-level eject API for systems where shell verb is unavailable.
                try:
                    import ctypes
                    from ctypes import wintypes

                    kernel32 = ctypes.windll.kernel32
                    volume_path = f"\\\\.\\{drive}:"
                    handle = kernel32.CreateFileW(
                        volume_path,
                        0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
                        0x1 | 0x2,  # FILE_SHARE_READ | FILE_SHARE_WRITE
                        None,
                        0x3,  # OPEN_EXISTING
                        0,
                        None,
                    )
                    invalid_handle = ctypes.c_void_p(-1).value
                    if handle == invalid_handle:
                        _report_failure(
                            "Cannot Eject",
                            f"Could not open drive {drive}:. The drive may be in use.\n\n"
                            "Please close any programs using the SD card and try again, or eject manually using Windows Explorer."
                        )
                        return
                    try:
                        bytes_returned = wintypes.DWORD()
                        result = kernel32.DeviceIoControl(
                            handle,
                            0x2D4808,  # IOCTL_STORAGE_EJECT_MEDIA
                            None,
                            0,
                            None,
                            0,
                            ctypes.byref(bytes_returned),
                            None,
                        )
                    finally:
                        kernel32.CloseHandle(handle)
                    if result:
                        _report_success(f"SD card ({drive}:) has been safely ejected.\n\nYou can now safely remove it.")
                    else:
                        _report_failure(
                            "Eject Failed",
                            f"Could not eject drive {drive}:.\n\nPlease try ejecting manually using Windows Explorer."
                        )
                except Exception as e:
                    _report_failure(
                        "Eject Error",
                        f"An error occurred while trying to eject the SD card:\n{str(e)}\n\n"
                        "Please eject manually using Windows Explorer."
                    )
            elif system == "Darwin":
                # macOS: eject, then force-unmount if the volume is busy (Finder still refreshing).
                mount = str(sd_root)
                try:
                    last_err = ""
                    ok = False
                    for cmd in (
                        ["hdiutil", "unmount", mount],
                        ["diskutil", "eject", mount],
                        ["diskutil", "unmount", "force", mount],
                    ):
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=20,
                        )
                        out = (result.stderr or result.stdout or "").strip()
                        if out:
                            last_err = out
                        if result.returncode == 0:
                            ok = True
                            break
                    if ok:
                        _report_success(
                            "SD card has been unmounted or ejected.\n\n"
                            "The app cleared the saved SD path; use Detect when you plug the card in again.\n\n"
                            "If Finder still shows the volume, eject it there too."
                        )
                    else:
                        _report_failure(
                            "Eject Failed",
                            f"Could not eject SD card: {last_err or 'unknown error'}\n\n"
                            "Close any Finder windows on the card, then try again or eject from Finder."
                        )
                except FileNotFoundError:
                    _report_failure(
                        "Eject Unavailable",
                        "diskutil not found on this system. Please eject the SD card manually using Finder or Disk Utility."
                    )
            else:
                # For Linux and other Unix-like systems, try umount first, then fallback to eject
                try:
                    result = subprocess.run(
                        ["umount", str(sd_root)],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        _report_success("SD card has been safely unmounted.\n\nYou can now safely remove it.")
                        return
                except Exception:
                    pass
                try:
                    result = subprocess.run(
                        ["eject", str(sd_root)],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        _report_success("SD card has been safely ejected.\n\nYou can now safely remove it.")
                    else:
                        _report_failure(
                            "Eject Failed",
                            f"Could not eject SD card: {result.stderr or result.stdout}\n\nPlease try ejecting manually."
                        )
                except FileNotFoundError:
                    _report_failure(
                        "Eject Unavailable",
                        "Eject command not found. Please eject the SD card manually using your OS file manager."
                    )
        except Exception as e:
            _report_failure(
                "Eject Error",
                f"An error occurred while trying to eject the SD card:\n{str(e)}\n\n"
                "Please eject manually using your operating system's file manager."
            )
    
    def validate_sd(self) -> None:
        results = self.sd_manager.validate_sd()
        lines = []
        for key, items in results.items():
            lines.append(f"{key}: {len(items)}")
        self.sd_status.setPlainText("\n".join(lines))

    def export_album_to_sd(self) -> None:
        sd_root = self._resolve_sd_root()
        if not sd_root:
            return
        album_id = self.sd_album_combo.currentData()
        if album_id is None:
            return
        target = self.sd_manager.export_album(
            int(album_id),
            sd_root,
            audio_target=self.audio_target,
            pi_convert_audio=self.pi_convert_audio,
        )
        if target:
            self.statusBar().showMessage(
                f"Exported album to {target.name}", 5000
            )

    def export_playlist_to_sd(self) -> None:
        sd_root = self._resolve_sd_root()
        if not sd_root:
            return
        playlist_id = self.sd_playlist_combo.currentData()
        if playlist_id is None:
            return
        target = self.sd_manager.export_playlist(
            int(playlist_id),
            sd_root,
            audio_target=self.audio_target,
            pi_convert_audio=self.pi_convert_audio,
        )
        if target:
            self.statusBar().showMessage(
                f"Exported playlist to {target.name}", 5000
            )

    def import_from_sd(self) -> None:
        sd_root = self._resolve_sd_root()
        if not sd_root:
            return

        # Prompt user for destination directory to copy files to
        dest_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Destination Directory for Imported Files",
            str(Path.home()),
        )
        if not dest_dir:
            return  # User cancelled

        def _on_import_success(results: Dict) -> None:
            self.refresh_albums()
            self.refresh_playlists()
            self.refresh_library()
            songs_count = results.get('songs', 0)
            status_lines = [
                f"Imported albums: {results['albums']}",
                f"Imported playlists: {results['playlists']}",
            ]
            if songs_count:
                status_lines.append(f"New songs added to library: {songs_count}")
            self.sd_status.setPlainText("\n".join(status_lines))

        dlg = TaskProgressDialog(
            parent=self,
            title="Import from SD Card",
            func=self.sd_manager.import_from_sd,
            args=(sd_root, Path(dest_dir)),
        )
        dlg.on_success = _on_import_success
        dlg.exec()

    def _project_root(self) -> Path:
        """Project root (parent of gui package, or bundle root when frozen)."""
        return project_root()

    def export_rp2040_firmware(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose folder to export RP2040 components",
            str(Path.home()),
        )
        if not folder:
            return
        root = self._project_root()
        dest = Path(folder)
        dest.mkdir(parents=True, exist_ok=True)
        pico_main = root / "firmware" / "pico" / "main.py"
        if pico_main.exists():
            shutil.copy2(pico_main, dest / "main.py")
        rc_src = root / "firmware" / "radio_core.py"
        if rc_src.exists():
            shutil.copy2(rc_src, dest / "radio_core.py")

        profile_params = self._get_active_profile_install_params()
        custom_driver = profile_params.get("custom_hw_driver_path", "")
        if custom_driver and Path(custom_driver).is_file():
            (dest / "components").mkdir(parents=True, exist_ok=True)
            shutil.copy2(custom_driver, dest / "components" / "dfplayer_hardware.py")
        else:
            fw_src = root / "firmware" / "pico" / "dfplayer_hardware.py"
            if fw_src.exists():
                (dest / "components").mkdir(parents=True, exist_ok=True)
                shutil.copy2(fw_src, dest / "components" / "dfplayer_hardware.py")

        loader_src = root / "firmware" / "pin_config_loader.py"
        if loader_src.exists():
            shutil.copy2(loader_src, dest / "pin_config_loader.py")

        sdcard_src = root / "firmware" / "pico" / "sdcard.py"
        if sdcard_src.exists():
            shutil.copy2(sdcard_src, dest / "sdcard.py")

        pin_json = profile_params.get("pin_config_json", "")
        if pin_json:
            (dest / "pin_config.json").write_text(pin_json, encoding="utf-8")

        vintage_dest = dest / "VintageRadio"
        vintage_dest.mkdir(parents=True, exist_ok=True)
        readme_txt = dest / "README_RP2040.txt"
        readme_txt.write_text(
            "RP2040 + DFPlayer. Copy main.py, radio_core.py, pin_config_loader.py,\n"
            "sdcard.py, pin_config.json, and components/ to the Pico.\n"
            "AM sound uses AMradioSound.wav on Pico flash (PWM overlay), not the SD card.\n"
            "SD layout: folders 01/, 02/, ... at SD root with 001.mp3, 002.mp3 inside;\n"
            "folder 99 is a normal station folder like the rest; radio_metadata.json at SD root (no VintageRadio/ on card).\n"
            "See README_RP2040.md in this folder for full setup.\n",
            encoding="utf-8",
        )
        docs_readme = root / "docs" / "README_RP2040.md"
        if docs_readme.exists():
            shutil.copy2(docs_readme, dest / "README_RP2040.md")
        self.statusBar().showMessage(f"Exported RP2040 components to {folder}", 5000)

    def _show_install_micropython_dialog(self) -> None:
        dlg = InstallMicroPythonDialog(self)
        dlg.exec()

    def _setup_pico_smart(self) -> None:
        """One button: if MicroPython is installed, install app; else if RPI-RP2 present, flash firmware then prompt to run again.

        Board-aware: for non-Pico MicroPython boards (ESP32 etc.), skips BOOTSEL/UF2 logic
        but still uses mpremote for firmware install over USB serial.
        For Raspberry Pi (cpython), redirects to deploy_to_pi.
        """
        profile = self.db.get_active_profile()
        board_id = profile["board_id"] if profile else "raspberry_pi_pico"
        bp = get_board_profile(board_id)

        if bp and bp.platform == "cpython":
            self.deploy_to_pi()
            return

        is_pico = bp is not None and "pico" in bp.id

        mpremote_cmd = self._resolve_mpremote_cmd()
        if not mpremote_cmd:
            bundle_err = getattr(self, "_mpremote_bundle_error", None)
            if bundle_err:
                print(f"[Setup Device] mpremote import failed:\n{bundle_err}")
            msg = "mpremote is not available. Install it with: pip install mpremote\n\nThen connect the device via USB and try again."
            if bundle_err:
                msg += "\n\n(Bundled mpremote failed to load:\n" + str(bundle_err) + ")"
            VintageMessageBox.information(self, "Install Firmware", msg)
            return
        root = self._project_root()
        if not (root / "firmware" / "pico" / "main.py").exists() or not (root / "firmware" / "radio_core.py").exists():
            VintageMessageBox.warning(self, "Install Firmware", "Project files not found.")
            return
        if not (root / "firmware" / "pico" / "dfplayer_hardware.py").exists():
            VintageMessageBox.warning(self, "Install Firmware", "firmware/pico/dfplayer_hardware.py not found.")
            return

        if is_pico:
            self._smart_install_vintage_radio_basic()
            return

        # Non-Pico MicroPython boards: probe serial and install when reachable.
        conn_err = ""
        try:
            r = _run_mpremote(
                mpremote_cmd,
                ["connect", "auto", "exec", _MPREMOTE_MICROPYTHON_PROBE],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if _mpremote_result_indicates_micropython(r):
                self.install_to_pico()
                return
            conn_err = (r.stderr or "") + (r.stdout or "")

            # Fallback 1: "connect auto" can fail on macOS bundled app; try each port explicitly
            try:
                import serial.tools.list_ports as list_ports
                for port_info in list_ports.comports():
                    port_dev = getattr(port_info, "device", None) or str(port_info)
                    hwid = getattr(port_info, "hwid", "") or ""
                    if "2E8A" in hwid or "2E8A" in str(port_info):  # Raspberry Pi Pico VID
                        r2 = _run_mpremote(
                            mpremote_cmd,
                            ["connect", port_dev, "exec", _MPREMOTE_MICROPYTHON_PROBE],
                            cwd=str(root),
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        if _mpremote_result_indicates_micropython(r2):
                            self.install_to_pico()
                            return
                        conn_err += f"\n[Port {port_dev}]: {(r2.stderr or '') + (r2.stdout or '')}"
            except Exception as fallback_e:
                conn_err += f"\n[Fallback scan]: {fallback_e}"

            # Fallback 2: in-process mpremote can fail on macOS; try system Python via subprocess
            if getattr(sys, "frozen", False):
                from gui.resource_paths import subprocess_env
                sp_env = subprocess_env()
                # Use home as cwd so system Python doesn't load app's mpremote from bundle
                _safe_cwd = os.path.expanduser("~")
                seen = set()
                py_candidates = []
                for p in (shutil.which("python3"), shutil.which("python"),
                          "/usr/local/bin/python3", "/opt/homebrew/bin/python3", "/usr/bin/python3"):
                    if not p or p in seen:
                        continue
                    if not p.startswith("/") or Path(p).exists():
                        seen.add(p)
                        py_candidates.append(p)
                for py_exe in py_candidates:
                    if not py_exe:
                        continue
                    try:
                        r3 = subprocess.run(
                            [py_exe, "-m", "mpremote", "connect", "auto", "exec", _MPREMOTE_MICROPYTHON_PROBE],
                            cwd=_safe_cwd,
                            capture_output=True,
                            text=True,
                            timeout=10,
                            env=sp_env,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                        )
                        if _mpremote_result_indicates_micropython(r3):
                            self._mpremote_system_cmd = [py_exe, "-m", "mpremote"]
                            self.install_to_pico()
                            return
                        conn_err += f"\n[System {py_exe}]: {(r3.stderr or '') + (r3.stdout or '')}"
                        # Try each Pico port with system Python too
                        try:
                            import serial.tools.list_ports as list_ports
                            for port_info in list_ports.comports():
                                port_dev = getattr(port_info, "device", None) or str(port_info)
                                hwid = getattr(port_info, "hwid", "") or ""
                                if "2E8A" in hwid or "2E8A" in str(port_info):
                                    r4 = subprocess.run(
                                        [py_exe, "-m", "mpremote", "connect", port_dev, "exec", _MPREMOTE_MICROPYTHON_PROBE],
                                        cwd=_safe_cwd,
                                        capture_output=True,
                                        text=True,
                                        timeout=10,
                                        env=sp_env,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                    )
                                    if _mpremote_result_indicates_micropython(r4):
                                        self._mpremote_system_cmd = [py_exe, "-m", "mpremote"]
                                        self.install_to_pico()
                                        return
                                    conn_err += f"\n[System {py_exe} {port_dev}]: {(r4.stderr or '') + (r4.stdout or '')}"
                        except Exception:
                            pass
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                        continue
        except (subprocess.TimeoutExpired, Exception) as e:
            conn_err = str(e)

        print(f"[Setup Device] All connection attempts failed. Output:\n{conn_err}")
        board_name = bp.name if bp else "device"
        msg = (
            f"No {board_name} detected. Connect the device via USB.\n\n"
            "Ensure MicroPython is installed on the device."
        )
        if conn_err and len(conn_err) < 500:
            msg += f"\n\nConnection attempt output:\n{conn_err.strip()}"
        elif conn_err:
            msg += f"\n\nConnection attempt output:\n{conn_err[:500].strip()}..."
        VintageMessageBox.information(self, "Install Firmware", msg)

    def _is_rpi_rp2_present(self) -> bool:
        """True if a drive with label RPI-RP2 (Pico in BOOTSEL) is present."""
        return SDManager.is_rp2040_bootsel_present()

    def _check_basic_sd_pico_warning(self) -> None:
        """Show warning in basic view only when both our SD card and RPI-RP2 (unflashed Pico) are present."""
        if not hasattr(self, "_basic_sd_pico_warning"):
            return
        sd_present = self.sd_manager.is_sync_target_sd_present(
            self.sd_root, self.db.get_setting("sd_volume_label")
        )
        rp2_present = self._is_rpi_rp2_present()
        if sd_present and rp2_present:
            self._basic_sd_pico_warning.setText(
                "Your SD card and Pico (in setup mode) are both connected. "
                "Install MicroPython on the Pico first (Setup Pico), then install the app."
            )
            self._basic_sd_pico_warning.setVisible(True)
        else:
            self._basic_sd_pico_warning.setVisible(False)

    def _resolve_mpremote_cmd(self) -> Optional[List[Any]]:
        """Find the mpremote command (bundled in-process, standalone, or system-installed).

        When frozen (packaged app): try bundled mpremote first so the app works without system mpremote.
        When not frozen: try current interpreter, then PATH, then system Python.
        """
        if hasattr(self, "_mpremote_bundle_error"):
            delattr(self, "_mpremote_bundle_error")
        # Use system Python cmd if setup already proved it works (fallback path)
        if getattr(self, "_mpremote_system_cmd", None):
            return list(self._mpremote_system_cmd)
        # Packaged macOS: in-process mpremote crashes (pyserial/IOKit + Qt main-thread conflict).
        # Use bundled mpremote_helper (subprocess, no Qt) or system Python fallback.
        if getattr(sys, "frozen", False) and sys.platform == "darwin":
            macos_dir = Path(sys.executable).parent
            helper = macos_dir / "mpremote_helper" / "mpremote_helper"
            if not helper.exists():
                helper = macos_dir / "mpremote_helper"
            if helper.exists():
                return [str(helper)]
            fallback = _resolve_system_mpremote_for_worker()
            if fallback:
                return list(fallback)
            setattr(
                self, "_mpremote_bundle_error",
                "On packaged macOS, Setup Pico requires system Python with mpremote.\n"
                "Run in Terminal: python3 -m pip install mpremote"
            )
            return None
        # Packaged Windows/Linux: subprocess via same bundled exe (see run_vintage_radio --vr-mpremote).
        # In-process mpremote + pyserial inside the Qt process is unreliable on Windows PyInstaller.
        if getattr(sys, "frozen", False) and sys.platform != "darwin":
            try:
                from mpremote.main import main as _mpremote_main  # noqa: F401
            except ImportError as e:
                import traceback
                setattr(self, "_mpremote_bundle_error", f"{e}\n{traceback.format_exc()}")
            else:
                return [str(Path(sys.executable).resolve()), "--vr-mpremote"]

        # Standalone mpremote on PATH (e.g. pipx install mpremote)
        cmd = shutil.which("mpremote")
        if cmd:
            return [cmd]

        # Current interpreter (from source): pip install mpremote
        if not getattr(sys, "frozen", False):
            try:
                import mpremote  # noqa: F401
                python_cmd = shutil.which("python") or sys.executable
                return [python_cmd, "-m", "mpremote"]
            except ImportError:
                pass

        # System Python (user may have: pip install mpremote globally)
        system_python = shutil.which("python3") or shutil.which("pythonw") or shutil.which("python")
        if system_python:
            try:
                result = subprocess.run(
                    [system_python, "-m", "mpremote", "--version"],
                    capture_output=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if result.returncode == 0:
                    return [system_python, "-m", "mpremote"]
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass

        return None

    @staticmethod
    def _install_to_pico_worker(
        mpremote_cmd: List[str],
        root: Path,
        sd_root: Optional[str],
        sd_manager: SDManager,
        progress_callback: Optional[Callable[..., Any]] = None,
        pin_config_json: str = "",
        custom_hw_driver_path: str = "",
        basic_mode: bool = False,
        install_mode: str = "basic",
        dfplayer_eq: str = "normal",
        after_firmware: bool = False,
        preferred_serial_port: Optional[str] = None,
    ) -> str:
        """Background worker: copy firmware files to Pico via mpremote CLI.

        Uses mpremote command-line interface (bundled in-process when frozen, or subprocess).
        All subprocess calls use CREATE_NO_WINDOW on Windows to prevent new windows.

        In-process mpremote must NOT run in a worker thread (macOS NSWindow main-thread requirement).
        Caller must pass subprocess form when using TaskProgressDialog.
        Returns a status message string. Raises on fatal error.
        """
        import tempfile as _tempfile

        # In-process mpremote hijacks sys.stdout and must run on main thread (macOS NSWindow requirement).
        import threading
        if mpremote_cmd and mpremote_cmd[0] == "__INPROCESS__":
            if threading.current_thread() is not threading.main_thread():
                fallback = _resolve_system_mpremote_for_worker()
                if fallback:
                    mpremote_cmd = list(fallback)
                else:
                    raise RuntimeError(
                        "Install runs in a background thread; in-process mpremote is not safe here.\n"
                        "Install mpremote for system Python: python3 -m pip install mpremote"
                    )

        main_source = "firmware/pico/main_basic.py" if basic_mode else "firmware/pico/main.py"
        files_to_copy = [
            (main_source, "main.py"),
            ("firmware/radio_core.py", "radio_core.py"),
            ("firmware/pico/dfplayer_hardware.py", "components/dfplayer_hardware.py"),
            (
                "firmware/pico/components/vintage_radio_ipc.py",
                "components/vintage_radio_ipc.py",
            ),
            (
                "firmware/pico/components/am_wav_loader.py",
                "components/am_wav_loader.py",
            ),
            ("firmware/pin_config_loader.py", "pin_config_loader.py"),
            ("firmware/pico/sdcard.py", "sdcard.py"),
        ]

        # If a custom driver is specified in the active profile, use it instead
        if custom_hw_driver_path and Path(custom_hw_driver_path).is_file():
            files_to_copy = [
                (src, dst) for src, dst in files_to_copy
                if dst != "components/dfplayer_hardware.py"
            ]
            files_to_copy.append((custom_hw_driver_path, "components/dfplayer_hardware.py"))

        write_session_line(
            "Pico install copy list: {}".format(
                ", ".join(remote for _src, remote in files_to_copy)
            ),
            prefix="INSTALL",
        )

        # Total steps: mkdir + firmware batch + pin_config + app config + AM WAV + metadata + reboot
        total = 7
        step = 0

        if progress_callback:
            progress_callback(
                0,
                total,
                "Preparing to copy Vintage Radio firmware to the Pico…",
            )

        def _report(msg: str):
            nonlocal step
            if progress_callback:
                progress_callback(step, total, msg)
            step += 1

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        env = None
        if getattr(sys, "frozen", False) and mpremote_cmd and mpremote_cmd[0] != "__INPROCESS__":
            python_exe = mpremote_cmd[0]
            if "_internal" in python_exe:
                exe_dir = Path(sys.executable).parent
                internal_dir = exe_dir / "_internal"
                if internal_dir.exists():
                    env = os.environ.copy()
                    env["PATH"] = str(internal_dir) + os.pathsep + env.get("PATH", "")
            else:
                from gui.resource_paths import subprocess_env
                env = subprocess_env()

        # System Python subprocess must not use app bundle as cwd (would load app's broken mpremote)
        _mpremote_cwd = str(root)
        if getattr(sys, "frozen", False) and mpremote_cmd and mpremote_cmd[0] != "__INPROCESS__":
            exe = mpremote_cmd[0].lower()
            if "python" in exe or (exe.startswith("/usr") and "mpremote" not in exe):
                _mpremote_cwd = os.path.expanduser("~")

        def run_mpremote(args: List[str], timeout_sec: int = 30):
            return _run_mpremote(
                mpremote_cmd, _mpremote_args_with_connect(args, rp_port), cwd=_mpremote_cwd, capture_output=True, text=True,
                timeout=timeout_sec, creationflags=creation_flags, env=env,
            )

        def run_mpremote_with_retry(args: List[str], timeout_sec: int = 30):
            """Run mpremote; retry transient USB / REPL / port errors."""
            import time

            r = run_mpremote(args, timeout_sec=timeout_sec)
            for attempt in range(6):
                if r.returncode == 0:
                    return r
                err = (r.stderr or "") + (r.stdout or "")
                if not (
                    _mpremote_failure_is_transient_no_device(r)
                    or _mpremote_failure_is_transient_serial(r)
                ):
                    return r
                time.sleep(min(10.0, 1.5 + attempt * 1.5))
                r = run_mpremote(args, timeout_sec=timeout_sec)
            return r

        rp_port = _find_rp2040_serial_port(preferred=preferred_serial_port)

        if after_firmware:
            wait_err = _wait_mpremote_serial_ready(
                mpremote_cmd,
                _mpremote_cwd,
                progress_callback=progress_callback,
                total_steps=total,
                creationflags=creation_flags,
                env=env,
                after_uf2_flash=True,
                preferred_port=preferred_serial_port,
            )
            if wait_err is not None:
                raise RuntimeError(wait_err)
            rp_port = _find_rp2040_serial_port(preferred=preferred_serial_port)

        if rp_port:
            write_session_line(f"Pico install using explicit port {rp_port}", prefix="INSTALL")

        # ── Create directories (batched: one mpremote call) ──
        _report("Creating directories on Pico...")
        try:
            run_mpremote_with_retry(
                ["exec", "import os\nfor d in ('components','VintageRadio'):\n try: os.mkdir(d)\n except OSError: pass"],
                timeout_sec=15,
            )
        except Exception:
            pass  # directories may already exist

        # Preflight: raw REPL + filesystem access (fails fast on blocking firmware / port contention).
        _report("Checking MicroPython file transfer…")
        probe = run_mpremote_with_retry(
            ["exec", "import os; print('VR_INSTALL_PROBE', os.listdir())"],
            timeout_sec=20,
        )
        probe_out = (probe.stdout or "") + (probe.stderr or "")
        if probe.returncode != 0 or "VR_INSTALL_PROBE" not in probe_out:
            raise RuntimeError(_format_install_mpremote_error(probe_out or "mpremote probe failed"))

        # ── Copy firmware files (one mpremote cp per file; batched cp requires dest to be a dir) ──
        _report("Copying main, radio_core, components (dfplayer + vintage_radio_ipc), …")
        for local, remote in files_to_copy:
            src = root / local
            if not src.exists():
                raise RuntimeError(
                    "Firmware file is missing from the application bundle — cannot push to the Pico.\n\n"
                    f"Missing source: {local}\n"
                    f"Resolved path: {src}\n\n"
                    "If you are running a packaged build, reinstall from a build that includes "
                    "firmware/pico/components (e.g. am_wav_loader.py). "
                    "From source, ensure the repo firmware tree is intact."
                )
            r = run_mpremote_with_retry(["cp", str(src), f":{remote}"])
            if r.returncode != 0:
                detail = (r.stderr or "") + (r.stdout or "")
                raise RuntimeError(_format_install_mpremote_error(detail))

        # ── Write pin_config.json from active profile ──
        _report("Writing pin configuration...")
        if pin_config_json:
            tmpdir_cfg = _tempfile.mkdtemp()
            try:
                cfg_file = Path(tmpdir_cfg) / "pin_config.json"
                cfg_file.write_text(pin_config_json, encoding="utf-8")
                r = run_mpremote_with_retry(["cp", str(cfg_file), ":pin_config.json"])
                if r.returncode != 0:
                    print(f"Warning: pin_config.json copy failed: {r.stderr or r.stdout}")
            except Exception as e:
                print(f"Warning: Could not copy pin_config.json: {e}")
            finally:
                try:
                    shutil.rmtree(tmpdir_cfg)
                except Exception:
                    pass

        # ── Write advanced runtime settings used by new advanced mode ──
        _report("Writing runtime settings...")
        install_mode = (install_mode or "basic").strip().lower()
        if install_mode not in {"basic", "advanced", "legacy"}:
            install_mode = "basic"
        dfplayer_eq = (dfplayer_eq or "normal").strip().lower()
        if dfplayer_eq not in {"normal", "pop", "rock", "jazz", "classic", "bass"}:
            dfplayer_eq = "normal"
        tmpdir_cfg2 = _tempfile.mkdtemp()
        try:
            mode_file = Path(tmpdir_cfg2) / "advanced_runtime.json"
            mode_file.write_text(
                json.dumps({"install_mode": install_mode, "dfplayer_eq": dfplayer_eq}),
                encoding="utf-8",
            )
            r = run_mpremote_with_retry(["cp", str(mode_file), ":VintageRadio/advanced_runtime.json"])
            if r.returncode != 0:
                print(f"Warning: advanced_runtime.json copy failed: {r.stderr or r.stdout}")
        except Exception as e:
            print(f"Warning: Could not copy advanced_runtime.json: {e}")
        finally:
            try:
                shutil.rmtree(tmpdir_cfg2)
            except Exception:
                pass

        # ── Copy AMradioSound.wav ──
        _report("Copying AM radio sound...")
        from gui.resource_paths import resource_path
        am_wav_src = resource_path("AMradioSound.wav")
        if not am_wav_src.exists():
            am_wav_src = root / "AMradioSound.wav"
        if am_wav_src.exists():
            try:
                r = run_mpremote_with_retry(["cp", str(am_wav_src), ":VintageRadio/AMradioSound.wav"])
                if r.returncode == 0:
                    print("AMradioSound.wav copied to Pico flash (PWM overlay enabled)")
                    try:
                        src_size = am_wav_src.stat().st_size
                    except OSError:
                        src_size = -1
                    verify = run_mpremote_with_retry(
                        [
                            "exec",
                            "import os\n"
                            "p='VintageRadio/AMradioSound.wav'\n"
                            "try:\n"
                            " s=os.stat(p)[6]\n"
                            " print('AM_WAV_OK', s)\n"
                            "except Exception as e:\n"
                            " print('AM_WAV_MISSING', e)\n",
                        ],
                        timeout_sec=10,
                    )
                    out = (verify.stdout or "") + (verify.stderr or "")
                    if "AM_WAV_OK" in out:
                        try:
                            parts = out.strip().split()
                            pico_size = int(parts[-1])
                        except Exception:
                            pico_size = -1
                        if src_size > 0 and pico_size == src_size:
                            print(f"AM WAV verify: OK on Pico ({pico_size} bytes)")
                        elif pico_size > 0:
                            print(
                                f"Warning: AM WAV verify size mismatch (src={src_size}, pico={pico_size})"
                            )
                        else:
                            print("Warning: AM WAV verify returned unreadable size output")
                    else:
                        print(
                            "Warning: AM WAV verify failed; Pico file not readable after copy. "
                            f"Output: {out.strip()}"
                        )
                else:
                    print(f"Warning: Failed to copy AMradioSound.wav: {r.stderr or r.stdout}")
            except Exception as e:
                print(f"Warning: Could not copy AMradioSound.wav: {e}")
        else:
            print("AMradioSound.wav not found - PWM overlay won't be available")

        # ── Copy radio_metadata.json (legacy install path only) ──
        # Basic/new-advanced firmware discovers stations directly from DFPlayer folders.
        # Keep metadata copy for legacy compatibility only.
        if install_mode == "legacy":
            _report("Copying metadata...")
            tmpdir = _tempfile.mkdtemp()
            try:
                tmp_vintage = Path(tmpdir) / "VintageRadio"
                tmp_vintage.mkdir(parents=True, exist_ok=True)
                sd_manager._write_metadata(tmp_vintage)
                metadata_src = tmp_vintage / "radio_metadata.json"
                if metadata_src.exists():
                    r = run_mpremote(["cp", str(metadata_src), ":VintageRadio/radio_metadata.json"])
                    if r.returncode != 0:
                        print(f"Warning: metadata copy failed: {r.stderr or r.stdout}")
            except Exception as e:
                print(f"Warning: Could not generate or copy metadata: {e}")
            finally:
                try:
                    shutil.rmtree(tmpdir)
                except Exception:
                    pass
        else:
            _report("Skipping metadata copy (basic/advanced discovery mode)...")

        # Remove stale album_state.txt and reboot. machine.reset() drops USB serial — mpremote may
        # exit non-zero (ClearCommError / PermissionError) or subprocess may time out; both OK.
        _report("Rebooting Pico...")
        try:
            r = run_mpremote(
                [
                    "exec",
                    "import os\n"
                    "try: os.remove('VintageRadio/album_state.txt')\n"
                    "except: pass\n"
                    "import machine\n"
                    "machine.reset()",
                ],
                timeout_sec=8,
            )
            err = ((r.stderr or "") + (r.stdout or "")).strip()
            if r.returncode != 0:
                transient = (
                    "ClearCommError" in err
                    or "PermissionError" in err
                    or "does not recognize the command" in err.lower()
                    or "WinError 22" in err
                    or "bad file descriptor" in err.lower()
                )
                if transient:
                    print(
                        "Reboot initiated (serial closed as expected after machine.reset())."
                    )
                elif err:
                    print(f"Note: reboot step exited {r.returncode}: {err[:600]}")
        except subprocess.TimeoutExpired:
            print("Reboot initiated (connection closed as expected)")
        except Exception as e:
            print(f"Note: Could not trigger reboot: {e}")

        if progress_callback:
            progress_callback(total, total, "Done!")
        return "Installed to Pico successfully. Pico has been rebooted."

    def _install_to_pico_after_firmware(self) -> None:
        """Called after firmware install; run app install and only prompt to retry if it failed."""
        self.install_to_pico(after_firmware=True)

    def _get_active_profile_install_params(self) -> dict:
        """Read pin config and custom driver from the active profile for install/export."""
        profile = self.db.get_active_profile()
        if profile is None:
            return {
                "pin_config_json": "",
                "custom_hw_driver_path": "",
                "install_mode": "basic",
                "dfplayer_eq": "normal",
            }
        return {
            "pin_config_json": profile["pin_config_json"] or "",
            "custom_hw_driver_path": profile["custom_hw_driver_path"] or "",
            "install_mode": "basic",
            "dfplayer_eq": "normal",
        }

    def install_to_pico(
        self,
        after_firmware: bool = False,
        basic_mode: bool = False,
        *,
        install_mode: str = "basic",
        dfplayer_eq: str = "normal",
    ) -> None:
        """Copy application files to Pico via mpremote (bundled with executable, or requires: pip install mpremote).

        Args:
            after_firmware: If True, this was triggered right after flashing MicroPython.
            basic_mode: If True, flash main_basic.py as main.py instead of the standard main.py.
        """
        write_session_line(
            f"install_to_pico entered after_firmware={after_firmware} basic_mode={basic_mode} install_mode={install_mode} eq={dfplayer_eq}",
            prefix="INSTALL",
        )
        mpremote_cmd = self._resolve_mpremote_cmd()
        if not mpremote_cmd:
            msg = ("mpremote is not available. In a packaged executable, mpremote should be bundled.\n\n"
                   "If running from source, install it with:\n\n  pip install mpremote\n\n"
                   "Then connect the Pico via USB (with MicroPython already installed) and try again.\n"
                   "See README_RP2040.md for how to install MicroPython on the Pico (one-time).")
            if getattr(self, "_mpremote_bundle_error", None):
                msg += "\n\n(Bundled mpremote failed to load:\n" + str(self._mpremote_bundle_error) + ")"
            VintageMessageBox.information(self, "Install to Pico", msg)
            return

        if self._release_serial_if_connected_for_mpremote(log_prefix="INSTALL"):
            self.statusBar().showMessage(
                "Serial console disconnected so Install to Pico can use the USB port. "
                "Click Connect on the Device tab when finished.",
                12000,
            )

        if self._is_advanced_mode() and self._uses_custom_software():
            self._flush_advanced_mcu_notes_and_buttons()
            self._advanced_sync_custom_path_setting_to_active_source()
            self.install_custom_software_to_pico()
            return

        root = self._project_root()
        main_source = "firmware/pico/main_basic.py" if basic_mode else "firmware/pico/main.py"
        if not (root / main_source).exists():
            VintageMessageBox.warning(self, "Install to Pico", f"{main_source} not found.")
            return
        if not (root / "firmware" / "radio_core.py").exists():
            VintageMessageBox.warning(self, "Install to Pico", "Project files not found.")
            return
        if not (root / "firmware" / "pico" / "dfplayer_hardware.py").exists():
            VintageMessageBox.warning(self, "Install to Pico", "firmware/pico/dfplayer_hardware.py not found.")
            return

        profile_params = self._get_active_profile_install_params()
        profile_params["basic_mode"] = basic_mode
        profile_params["install_mode"] = install_mode
        profile_params["dfplayer_eq"] = dfplayer_eq
        profile_params["after_firmware"] = after_firmware
        profile_params["preferred_serial_port"] = _read_preferred_serial_port_from_ui(self)
        use_inprocess = mpremote_cmd and mpremote_cmd[0] == "__INPROCESS__"

        title = "Install to Pico (Basic Mode)" if basic_mode else "Install to Pico"

        if use_inprocess:
            _run_install_main_thread(
                self, mpremote_cmd, root, self.sd_root, self.sd_manager,
                after_firmware, on_success=lambda m: self.statusBar().showMessage(str(m), 5000),
                on_error=lambda m: _show_install_error(self, m, after_firmware),
                **profile_params,
            )
        else:
            dlg = TaskProgressDialog(
                parent=self,
                title=title,
                func=self._install_to_pico_worker,
                args=(mpremote_cmd, root, self.sd_root, self.sd_manager),
                kwargs=profile_params,
                show_byte_detail=False,
                initial_message=(
                    "Waiting for MicroPython on USB serial after flash…"
                    if after_firmware
                    else "Preparing to copy Vintage Radio firmware to the Pico…"
                ),
            )

            def on_success(msg):
                self.statusBar().showMessage(str(msg), 5000)

            def on_error(msg):
                _show_install_error(self, msg, after_firmware)

            dlg.on_success = on_success
            dlg.on_error = on_error
            dlg.exec()

    @staticmethod
    def _install_custom_software_worker(
        mpremote_cmd: List[str],
        source_path: Path,
        progress_callback: Optional[Callable[..., Any]] = None,
    ) -> str:
        import threading
        if mpremote_cmd and mpremote_cmd[0] == "__INPROCESS__":
            if threading.current_thread() is not threading.main_thread():
                fallback = _resolve_system_mpremote_for_worker()
                if fallback:
                    mpremote_cmd = list(fallback)
                else:
                    raise RuntimeError(
                        "Custom install runs in a background thread; install mpremote for system Python:\n"
                        "python3 -m pip install mpremote"
                    )

        if source_path.is_file():
            files_to_copy = [(source_path, "main.py")]
        else:
            files_to_copy = []
            for fp in sorted([p for p in source_path.rglob("*") if p.is_file()]):
                rel = fp.relative_to(source_path).as_posix()
                if rel.startswith(".git/") or rel.startswith("__pycache__/"):
                    continue
                files_to_copy.append((fp, rel))
        if not files_to_copy:
            raise RuntimeError("No files found in selected custom software source.")

        total = len(files_to_copy) + 2
        step = 0

        def _report(msg: str) -> None:
            nonlocal step
            if progress_callback:
                progress_callback(step, total, msg)
            step += 1

        root = source_path.parent if source_path.is_file() else source_path
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        env = None
        if getattr(sys, "frozen", False) and mpremote_cmd and mpremote_cmd[0] != "__INPROCESS__":
            python_exe = mpremote_cmd[0]
            if "_internal" in str(python_exe):
                exe_dir = Path(sys.executable).parent
                internal_dir = exe_dir / "_internal"
                if internal_dir.exists():
                    env = os.environ.copy()
                    env["PATH"] = str(internal_dir) + os.pathsep + env.get("PATH", "")
            else:
                from gui.resource_paths import subprocess_env

                env = subprocess_env()

        _mpremote_cwd = str(root)
        if getattr(sys, "frozen", False) and mpremote_cmd and mpremote_cmd[0] != "__INPROCESS__":
            exe = str(mpremote_cmd[0]).lower()
            if "python" in exe or (exe.startswith("/usr") and "mpremote" not in exe):
                _mpremote_cwd = os.path.expanduser("~")

        wait_err = _wait_mpremote_serial_ready(
            mpremote_cmd,
            _mpremote_cwd,
            progress_callback=progress_callback,
            total_steps=total,
            creationflags=creationflags,
            env=env,
            after_uf2_flash=True,
        )
        if wait_err is not None:
            raise RuntimeError(wait_err)

        _report("Preparing Pico directories...")
        _run_mpremote_connect_auto_with_retry(
            mpremote_cmd,
            ["exec", "import os\ntry: os.mkdir('VintageRadio')\nexcept: pass"],
            cwd=_mpremote_cwd,
            timeout=15,
            creationflags=creationflags,
            env=env,
        )
        made_dirs: set[str] = set()
        for idx, (local_fp, remote_rel) in enumerate(files_to_copy, start=1):
            remote_rel = remote_rel.replace("\\", "/")
            parent = str(Path(remote_rel).parent).replace("\\", "/")
            if parent and parent not in (".", "/") and parent not in made_dirs:
                _run_mpremote_connect_auto_with_retry(
                    mpremote_cmd,
                    ["exec", f"import os\ntry: os.mkdir('{parent}')\nexcept: pass"],
                    cwd=_mpremote_cwd,
                    timeout=15,
                    creationflags=creationflags,
                    env=env,
                )
                made_dirs.add(parent)
            _report(f"Copying file {idx}/{len(files_to_copy)}: {local_fp.name}")
            r = _run_mpremote_connect_auto_with_retry(
                mpremote_cmd,
                ["cp", str(local_fp), f":{remote_rel}"],
                cwd=_mpremote_cwd,
                timeout=30,
                creationflags=creationflags,
                env=env,
            )
            if r.returncode != 0:
                raise RuntimeError(
                    "Failed to copy custom software file:\n"
                    f"{local_fp}\n\n{r.stderr or r.stdout or ''}"
                )
        _report("Rebooting Pico...")
        try:
            r = _run_mpremote_connect_auto_with_retry(
                mpremote_cmd,
                ["exec", "import machine\nmachine.reset()"],
                cwd=_mpremote_cwd,
                timeout=8,
                creationflags=creationflags,
                env=env,
            )
            err = ((r.stderr or "") + (r.stdout or "")).strip()
            if r.returncode != 0 and err:
                transient = (
                    "ClearCommError" in err
                    or "PermissionError" in err
                    or "does not recognize the command" in err.lower()
                    or "WinError 22" in err
                )
                if transient:
                    print(
                        "Reboot initiated (serial closed as expected after machine.reset())."
                    )
        except Exception:
            pass
        if progress_callback:
            progress_callback(total, total, "Done!")
        return "Custom software installed successfully."

    @staticmethod
    def _deploy_mcp_support_worker(
        mpremote_cmd: List[Any],
        pico_root: Path,
        include_main: bool,
        progress_callback: Optional[Callable[..., Any]] = None,
    ) -> str:
        """Copy VRTEST IPC (and optionally main loops) from firmware/pico to the Pico flash."""
        import threading

        if mpremote_cmd and mpremote_cmd[0] == "__INPROCESS__":
            if threading.current_thread() is not threading.main_thread():
                fallback = _resolve_system_mpremote_for_worker()
                if fallback:
                    mpremote_cmd = list(fallback)
                else:
                    raise RuntimeError(
                        "Deploy runs in a background thread; install mpremote for system Python:\n"
                        "python -m pip install mpremote"
                    )

        files_to_copy: List[Tuple[Path, str]] = [
            (
                pico_root / "components" / "vintage_radio_ipc.py",
                "components/vintage_radio_ipc.py",
            ),
        ]
        if include_main:
            files_to_copy.extend(
                [
                    (pico_root / "main.py", "main.py"),
                    (pico_root / "main_basic.py", "main_basic.py"),
                ]
            )
        for local_fp, _ in files_to_copy:
            if not local_fp.is_file():
                raise FileNotFoundError("Missing project file: {}".format(local_fp))

        total = len(files_to_copy) + 2
        step = 0

        def _report(msg: str) -> None:
            nonlocal step
            if progress_callback:
                progress_callback(step, total, msg)
            step += 1

        root = pico_root
        _report("Ensuring components/ on Pico...")
        _run_mpremote(
            mpremote_cmd,
            [
                "connect",
                "auto",
                "exec",
                "import os\ntry: os.mkdir('components')\nexcept: pass",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )

        made_dirs: set[str] = {"components"}
        for idx, (local_fp, remote_rel) in enumerate(files_to_copy, start=1):
            remote_rel = remote_rel.replace("\\", "/")
            parent = str(Path(remote_rel).parent).replace("\\", "/")
            if parent and parent not in (".", "/") and parent not in made_dirs:
                _run_mpremote(
                    mpremote_cmd,
                    [
                        "connect",
                        "auto",
                        "exec",
                        "import os\ntry: os.mkdir('{}')\nexcept: pass".format(parent),
                    ],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                made_dirs.add(parent)
            _report("Copying {} ({}/{})...".format(local_fp.name, idx, len(files_to_copy)))
            r = _run_mpremote(
                mpremote_cmd,
                ["connect", "auto", "cp", str(local_fp), ":{}".format(remote_rel)],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=45,
            )
            if r.returncode != 0:
                raise RuntimeError(
                    "Failed to copy:\n{}\n\n{}".format(
                        local_fp, (r.stderr or r.stdout or "").strip()
                    )
                )

        _report("Resetting Pico...")
        try:
            _run_mpremote(
                mpremote_cmd,
                ["connect", "auto", "exec", "import machine\nmachine.reset()"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            pass
        if progress_callback:
            progress_callback(total, total, "Done!")
        return "MCP / VRTEST support deployed. Reconnect serial if needed; watch for VRTEST IPC line on boot."

    def install_custom_software_to_pico(self) -> None:
        source_raw = (self.db.get_setting("advanced_custom_software_path", "") or "").strip()
        source_path = Path(source_raw) if source_raw else None
        if not source_path or not source_path.exists():
            VintageMessageBox.warning(
                self,
                "Custom Software",
                "Choose a valid local custom software folder or file first.",
            )
            return
        mpremote_cmd = self._resolve_mpremote_cmd()
        if not mpremote_cmd:
            VintageMessageBox.information(
                self,
                "Custom Software",
                "mpremote is not available. Install it with:\n\npip install mpremote",
            )
            return
        dlg = TaskProgressDialog(
            parent=self,
            title="Install Custom Software",
            func=self._install_custom_software_worker,
            args=(mpremote_cmd, source_path),
            kwargs={},
        )

        def on_success(msg):
            self.statusBar().showMessage(str(msg), 5000)

        def on_error(msg):
            _show_install_error(self, msg, False)

        dlg.on_success = on_success
        dlg.on_error = on_error
        dlg.exec()

    def deploy_to_pi(self) -> None:
        """Copy application files to Raspberry Pi via SCP (requires SSH access)."""
        ip, ok = get_text(
            self,
            "Deploy to Pi",
            "Enter Raspberry Pi IP address:",
        )
        if not ok or not ip.strip():
            return
        ip = ip.strip()
        user = "pi"
        root = self._project_root()
        deploy_dir = app_data_dir() / "agent_workshop" / "deploy_pi" / "vintage_radio"
        deploy_dir.mkdir(parents=True, exist_ok=True)
        (deploy_dir / "components").mkdir(parents=True, exist_ok=True)
        pi_main = root / "firmware" / "pi" / "main_pi.py"
        if pi_main.exists():
            shutil.copy2(pi_main, deploy_dir / "main_pi.py")
        rc_src = root / "firmware" / "radio_core.py"
        if rc_src.exists():
            shutil.copy2(rc_src, deploy_dir / "radio_core.py")
        pi_hw = root / "firmware" / "pi" / "pi_hardware.py"
        if pi_hw.exists():
            shutil.copy2(pi_hw, deploy_dir / "components" / "pi_hardware.py")
        (deploy_dir / "requirements_pi.txt").write_text("python-vlc\nRPi.GPIO\n", encoding="utf-8")
        docs_pi = root / "docs" / "README_Pi.md"
        if docs_pi.exists():
            shutil.copy2(docs_pi, deploy_dir / "README_Pi.md")
        parent = deploy_dir.parent
        progress = IndeterminateProgressDialog(self, "Deploy to Pi", "Deploying to Pi...")
        progress.show_and_raise()
        try:
            r = subprocess.run(
                ["scp", "-r", "-o", "StrictHostKeyChecking=no", "vintage_radio", f"{user}@{ip}:/home/{user}/"],
                cwd=str(parent),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode != 0:
                progress.close()
                VintageMessageBox.warning(
                    self,
                    "Deploy to Pi",
                    f"SCP failed. Ensure the Pi is on the network and SSH is enabled.\n\n{r.stderr or r.stdout or ''}",
                )
                return
            r2 = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{ip}", f"cd /home/{user}/vintage_radio && pip3 install -r requirements_pi.txt"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            progress.close()
            if r2.returncode != 0:
                self.statusBar().showMessage(
                    "Files copied; pip install failed. Run on Pi: cd vintage_radio && pip3 install -r requirements_pi.txt",
                    8000,
                )
            else:
                self.statusBar().showMessage("Deployed to Pi successfully.", 5000)
        except subprocess.TimeoutExpired:
            progress.close()
            VintageMessageBox.warning(self, "Deploy to Pi", "Timed out. Check Pi IP and SSH.")
        except FileNotFoundError:
            progress.close()
            VintageMessageBox.warning(
                self,
                "Deploy to Pi",
                "scp/ssh not found. On Windows enable OpenSSH client (Settings > Apps > Optional features).",
            )
        except Exception as e:
            progress.close()
            VintageMessageBox.warning(self, "Deploy to Pi", f"Error: {e}")

    def export_pi_firmware(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose folder to export Raspberry Pi components",
            str(Path.home()),
        )
        if not folder:
            return
        root = self._project_root()
        dest = Path(folder)
        dest.mkdir(parents=True, exist_ok=True)
        pi_main = root / "firmware" / "pi" / "main_pi.py"
        if pi_main.exists():
            shutil.copy2(pi_main, dest / "main_pi.py")
        rc_src = root / "firmware" / "radio_core.py"
        if rc_src.exists():
            shutil.copy2(rc_src, dest / "radio_core.py")
        pi_hw = root / "firmware" / "pi" / "pi_hardware.py"
        if pi_hw.exists():
            (dest / "components").mkdir(parents=True, exist_ok=True)
            shutil.copy2(pi_hw, dest / "components" / "pi_hardware.py")

        loader_src = root / "firmware" / "pin_config_loader.py"
        if loader_src.exists():
            shutil.copy2(loader_src, dest / "pin_config_loader.py")

        profile_params = self._get_active_profile_install_params()
        pin_json = profile_params.get("pin_config_json", "")
        if pin_json:
            (dest / "pin_config.json").write_text(pin_json, encoding="utf-8")

        req = dest / "requirements_pi.txt"
        req.write_text(
            "python-vlc\nRPi.GPIO\n",
            encoding="utf-8",
        )
        readme_txt = dest / "README_Pi.txt"
        readme_txt.write_text(
            "Raspberry Pi 2W/3. Run: python3 main_pi.py\n"
            "Set media path (VintageRadio folder or library) in pi_hardware.py or config.\n"
            "SD/Export for Pi uses VintageRadio/library/ with original-style filenames.\n"
            "See README_Pi.md in this folder for full setup.\n",
            encoding="utf-8",
        )
        docs_readme_pi = root / "docs" / "README_Pi.md"
        if docs_readme_pi.exists():
            shutil.copy2(docs_readme_pi, dest / "README_Pi.md")
        self.statusBar().showMessage(f"Exported Raspberry Pi components to {folder}", 5000)

    def export_sd_contents_to_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose folder to export SD contents",
            str(Path.home()),
        )
        if not folder:
            return
        sd_root = Path(folder)
        progress = IndeterminateProgressDialog(
            self, "Export SD Contents", "Exporting SD contents...",
        )
        progress.show_and_raise()
        try:
            copied, skipped = self.sd_manager.sync_library(
                sd_root,
                audio_target=self.audio_target,
                pi_convert_audio=self.pi_convert_audio,
            )
            progress.close()
            self.statusBar().showMessage(
                f"Exported SD contents to {folder}. Copied: {copied}, skipped: {skipped}",
                5000,
            )
        except Exception as e:
            progress.close()
            VintageMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred:\n{str(e)}",
            )

    def _resolve_sd_root(self, *, interactive: bool = True) -> Optional[Path]:
        """Resolve SD card path. When *interactive* is False, never open a volume-picker
        dialog or browse folder — used for passive UI refresh (e.g. SD tab, after eject).
        """
        if self.sd_root:
            path = Path(self.sd_root)
            try:
                if path.exists():
                    return path
            except OSError:
                pass  # volume temporarily unrecognized (e.g. WinError 1005 post-format)
            if self._is_basic_like_mode():
                self._try_rebind_basic_sd_mount()
                if self.sd_root:
                    path2 = Path(self.sd_root)
                    try:
                        if path2.exists():
                            return path2
                    except OSError:
                        pass
        if self.sd_auto_detect:
            candidates = self.sd_manager.detect_sd_roots()
            label_matches: set = set()
            if self.sd_label and str(self.sd_label).strip():
                label_matches.add(str(self.sd_label).strip().upper())
            sv = (self.db.get_setting("sd_volume_label") or "").strip().upper()
            if sv:
                label_matches.add(sv)
            bt = (self.db.get_setting("basic_trusted_sd_volume") or "").strip().upper()
            if bt:
                label_matches.add(bt)
            if label_matches:
                matched = [
                    path
                    for path, label in candidates
                    if label and label.strip().upper() in label_matches
                ]
                if len(matched) == 1:
                    self.sd_root = str(matched[0])
                    self.sd_label = self._get_volume_label(matched[0])
                    self.db.set_setting("sd_root", self.sd_root)
                    self.db.set_setting("sd_label", self.sd_label)
                    self._update_sd_root_label()
                    return matched[0]
            if len(candidates) == 1:
                self.sd_root = str(candidates[0][0])
                self.db.set_setting("sd_root", self.sd_root)
                self.sd_label = candidates[0][1]
                self.db.set_setting("sd_label", self.sd_label)
                self._update_sd_root_label()
                return candidates[0][0]
            if len(candidates) > 1:
                if not interactive:
                    return None
                picked = self._pick_sd_root_from_candidates(candidates, default_idx=0)
                if picked is None:
                    return None
                self.sd_root = picked[0]
                self.sd_label = picked[1]
                self.db.set_setting("sd_root", self.sd_root)
                self.db.set_setting("sd_label", self.sd_label)
                self._update_sd_root_label()
                return Path(self.sd_root)
        if not self.sd_auto_detect:
            if not interactive:
                return None
            self.browse_sd_root()
            if self.sd_root:
                return Path(self.sd_root)
        return None

    def _selected_library_song_ids(self) -> List[int]:
        ids: List[int] = []
        for index in self.library_table.selectionModel().selectedRows():
            item = self.library_table.item(index.row(), 0)
            if item is None:
                continue
            song_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if song_id is not None:
                ids.append(int(song_id))
        return ids

    def _selected_table_song_ids(self, table: QtWidgets.QTableWidget) -> List[int]:
        ids: List[int] = []
        for index in table.selectionModel().selectedRows():
            item = table.item(index.row(), 0)
            if item is None:
                continue
            song_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if song_id is not None:
                ids.append(int(song_id))
        return ids

    def _table_song_ids(self, table: QtWidgets.QTableWidget) -> List[int]:
        ids: List[int] = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            song_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if song_id is not None:
                ids.append(int(song_id))
        return ids

    def persist_album_order(self) -> None:
        album_item = self.album_list.currentItem()
        if album_item is None:
            return
        album_id = int(album_item.data(QtCore.Qt.ItemDataRole.UserRole))
        order = getattr(self.album_songs_table, '_pending_order', None)
        if order is not None:
            self.album_songs_table._pending_order = None
            self.db.replace_album_tracks(album_id, order)
        else:
            self.db.replace_album_tracks(album_id, self._table_song_ids(self.album_songs_table))
        self.refresh_album_songs()

    def persist_playlist_order(self) -> None:
        playlist_item = self.playlist_list.currentItem()
        if playlist_item is None:
            return
        playlist_id = int(playlist_item.data(QtCore.Qt.ItemDataRole.UserRole))
        order = getattr(self.playlist_songs_table, '_pending_order', None)
        if order is not None:
            self.playlist_songs_table._pending_order = None
            self.db.replace_playlist_tracks(playlist_id, order)
        else:
            self.db.replace_playlist_tracks(
                playlist_id, self._table_song_ids(self.playlist_songs_table)
            )
        self.refresh_playlist_songs()

    # ── Album / Playlist list reordering ──────────────────────────────

    def _list_widget_ids(self, list_widget: QtWidgets.QListWidget) -> List[int]:
        """Return the ordered list of IDs stored in a QListWidget."""
        ids: List[int] = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item is not None:
                ids.append(int(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        return ids

    def _move_list_item(self, list_widget: QtWidgets.QListWidget, direction: int) -> None:
        """Move the currently selected item up (-1) or down (+1)."""
        row = list_widget.currentRow()
        if row < 0:
            return
        new_row = row + direction
        if new_row < 0 or new_row >= list_widget.count():
            return
        # Block signals while we rearrange so currentItemChanged doesn't fire
        list_widget.blockSignals(True)
        item = list_widget.takeItem(row)
        list_widget.insertItem(new_row, item)
        list_widget.setCurrentRow(new_row)
        list_widget.blockSignals(False)
        # Persist & notify
        if list_widget is self.album_list:
            self._persist_album_list_order()
        elif list_widget is self.playlist_list:
            self._persist_playlist_list_order()

    def _persist_album_list_order(self) -> None:
        """Save the current album list order to the database."""
        self.db.update_album_order(self._list_widget_ids(self.album_list))

    def _persist_playlist_list_order(self) -> None:
        """Save the current playlist list order to the database."""
        self.db.update_playlist_order(self._list_widget_ids(self.playlist_list))

    def _update_album_details(self) -> None:
        if not _qt_widget_alive(getattr(self, "album_details", None)):
            return
        if not _qt_widget_alive(getattr(self, "album_list", None)):
            return
        item = self.album_list.currentItem()
        if item is None:
            self.album_details.setText("Select an album to view details.")
            return
        album_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        row = self.db.conn.execute(
            "SELECT name, description FROM albums WHERE id = ?;", (album_id,)
        ).fetchone()
        description = row["description"] if row and row["description"] else ""
        self.album_details.setText(
            f"Name: {item.text()}\nDescription: {description}"
        )

    def _update_playlist_details(self) -> None:
        if not _qt_widget_alive(getattr(self, "playlist_details", None)):
            return
        if not _qt_widget_alive(getattr(self, "playlist_list", None)):
            return
        item = self.playlist_list.currentItem()
        if item is None:
            self.playlist_details.setText("Select a playlist to view details.")
            return
        playlist_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        row = self.db.conn.execute(
            "SELECT name, description FROM playlists WHERE id = ?;", (playlist_id,)
        ).fetchone()
        description = row["description"] if row and row["description"] else ""
        self.playlist_details.setText(
            f"Name: {item.text()}\nDescription: {description}"
        )

    def on_library_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._loading_library or item is None:
            return
        if item.column() not in (0, 1):
            return
        song_item = self.library_table.item(item.row(), 0)
        if song_item is None:
            return
        song_id = song_item.data(QtCore.Qt.ItemDataRole.UserRole)
        if song_id is None:
            return
        field = "title" if item.column() == 0 else "artist"
        previous = self.db.get_song_by_id(int(song_id))
        if previous is None:
            return
        new_value = item.text().strip()
        self.db.update_song(int(song_id), {field: new_value})
        self._push_undo(
            {
                "type": "edit_metadata",
                "previous": {
                    previous["id"]: {
                        "title": previous["title"],
                        "artist": previous["artist"],
                    }
                },
                "updated": {
                    previous["id"]: {
                        "title": new_value if field == "title" else previous["title"],
                        "artist": new_value if field == "artist" else previous["artist"],
                    }
                },
            }
        )

    def show_library_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        edit_action = menu.addAction("Edit Selected")
        remove_action = menu.addAction("Remove Selected")
        open_action = menu.addAction("Open in Explorer")
        sel_ids = self._selected_library_song_ids()
        replace_action = None
        if len(sel_ids) == 1:
            replace_action = menu.addAction("Replace source file…")
        menu.addSeparator()
        add_album_menu = menu.addMenu("Add to Album")
        add_playlist_menu = menu.addMenu("Add to Playlist")
        albums = self.db.list_albums()
        playlists = self.db.list_playlists()
        if not albums:
            disabled = add_album_menu.addAction("No albums available")
            disabled.setEnabled(False)
        else:
            for album in albums:
                action = add_album_menu.addAction(album["name"])
                action.triggered.connect(
                    lambda _, album_id=album["id"]: self.add_selected_to_album_id(
                        album_id
                    )
                )
        if not playlists:
            disabled = add_playlist_menu.addAction("No playlists available")
            disabled.setEnabled(False)
        else:
            for playlist in playlists:
                action = add_playlist_menu.addAction(playlist["name"])
                action.triggered.connect(
                    lambda _, playlist_id=playlist["id"]: self.add_selected_to_playlist_id(
                        playlist_id
                    )
                )

        action = menu.exec(self.library_table.viewport().mapToGlobal(pos))
        if action == edit_action:
            self.edit_selected_metadata()
        elif action == remove_action:
            self.delete_selected_songs()
        elif action == open_action:
            self.open_selected_in_explorer()
        elif replace_action is not None and action == replace_action and len(sel_ids) == 1:
            self._replace_song_source_path(sel_ids[0])

    def open_selected_in_explorer(self) -> None:
        song_ids = self._selected_library_song_ids()
        if not song_ids:
            return
        rows = self.db.get_songs_by_ids(song_ids)
        if not rows:
            return
        path = rows[0]["file_path"]
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def show_album_table_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        sel_ids = self._selected_table_song_ids(self.album_songs_table)
        replace_action = None
        if len(sel_ids) == 1:
            replace_action = menu.addAction("Replace source file…")
        remove_action = menu.addAction("Remove Selected")
        action = menu.exec(self.album_songs_table.viewport().mapToGlobal(pos))
        if action == remove_action:
            self.remove_selected_from_album()
        elif replace_action is not None and action == replace_action and len(sel_ids) == 1:
            self._replace_song_source_path(sel_ids[0])

    def show_playlist_table_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        sel_ids = self._selected_table_song_ids(self.playlist_songs_table)
        replace_action = None
        if len(sel_ids) == 1:
            replace_action = menu.addAction("Replace source file…")
        remove_action = menu.addAction("Remove Selected")
        action = menu.exec(self.playlist_songs_table.viewport().mapToGlobal(pos))
        if action == remove_action:
            self.remove_selected_from_playlist()
        elif replace_action is not None and action == replace_action and len(sel_ids) == 1:
            self._replace_song_source_path(sel_ids[0])

    def add_selected_to_album_id(self, album_id: int) -> None:
        song_ids = self._selected_library_song_ids()
        if not song_ids:
            return
        track_order = self.db.next_album_track_order(album_id)
        for song_id in song_ids:
            self.db.add_song_to_album(album_id, song_id, track_order)
            track_order += 1
        self.refresh_album_songs()

    def add_selected_to_playlist_id(self, playlist_id: int) -> None:
        song_ids = self._selected_library_song_ids()
        if not song_ids:
            return
        track_order = self.db.next_playlist_track_order(playlist_id)
        for song_id in song_ids:
            self.db.add_song_to_playlist(playlist_id, song_id, track_order)
            track_order += 1
        self.refresh_playlist_songs()

    def _push_undo(self, action: Dict) -> None:
        self._undo_stack.append(action)
        self._redo_stack.clear()

    def undo_last_action(self) -> None:
        if not self._undo_stack:
            self.statusBar().showMessage("Nothing to undo.", 3000)
            return
        action = self._undo_stack.pop()
        self._apply_undo(action)
        self._redo_stack.append(action)

    def redo_last_action(self) -> None:
        if not self._redo_stack:
            self.statusBar().showMessage("Nothing to redo.", 3000)
            return
        action = self._redo_stack.pop()
        self._apply_redo(action)
        self._undo_stack.append(action)

    def _apply_undo(self, action: Dict) -> None:
        action_type = action.get("type")
        if action_type == "remove_songs":
            for song in action.get("songs", []):
                self.db.insert_song_with_id(song)
            for link in action.get("album_links", []):
                self.db.insert_album_track(
                    link["album_id"], link["song_id"], link["track_order"]
                )
            for link in action.get("playlist_links", []):
                self.db.insert_playlist_track(
                    link["playlist_id"], link["song_id"], link["track_order"]
                )
            self.refresh_library()
            self.refresh_albums()
            self.refresh_playlists()
        elif action_type == "remove_album_tracks":
            album_id = action["album_id"]
            for track in action.get("tracks", []):
                self.db.insert_album_track(
                    album_id, track["song_id"], track["track_order"]
                )
            self.refresh_album_songs()
        elif action_type == "remove_playlist_tracks":
            playlist_id = action["playlist_id"]
            for track in action.get("tracks", []):
                self.db.insert_playlist_track(
                    playlist_id, track["song_id"], track["track_order"]
                )
            self.refresh_playlist_songs()
        elif action_type == "edit_metadata":
            previous = action.get("previous", {})
            for song_id, fields in previous.items():
                self.db.update_song(int(song_id), fields)
            self.refresh_library()

    def _apply_redo(self, action: Dict) -> None:
        action_type = action.get("type")
        if action_type == "remove_songs":
            for song_id in action.get("song_ids", []):
                self.db.delete_song(int(song_id))
            self.refresh_library()
        elif action_type == "remove_album_tracks":
            album_id = action["album_id"]
            remaining = action.get("remaining", [])
            self.db.replace_album_tracks(album_id, remaining)
            self.refresh_album_songs()
        elif action_type == "remove_playlist_tracks":
            playlist_id = action["playlist_id"]
            remaining = action.get("remaining", [])
            self.db.replace_playlist_tracks(playlist_id, remaining)
            self.refresh_playlist_songs()
        elif action_type == "edit_metadata":
            updated = action.get("updated", {})
            for song_id, fields in updated.items():
                self.db.update_song(int(song_id), fields)
            self.refresh_library()

    # ── Session log helpers ────────────────────────────────────

    def _reveal_hw_diag_on_shift(self) -> None:
        """Show the hidden Hardware Diagnostics menu item when Shift is held."""
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        self._hw_diag_action.setVisible(
            bool(modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier)
        )

    def _open_hw_diagnostics(self) -> None:
        """Open the Hardware Diagnostics dialog (secret menu / Ctrl+Shift+H)."""
        from .hardware_test_dialog import HardwareTestDialog
        # Pre-fill with the port from the Devices tab if available
        default_port: str | None = None
        try:
            default_port = self._device_debug_widget.current_port()  # type: ignore[attr-defined]
        except Exception:
            pass
        dlg = HardwareTestDialog(parent=self, default_port=default_port)
        dlg.exec()

    def _view_session_log(self) -> None:
        """Show the session log on the Tools tab (basic) or open in the system editor."""
        if self.devices_view_mode in ("basic", "advanced"):
            self._open_tools_tab("session_logs")
            page = getattr(self, "_tools_page", None)
            if _qt_widget_alive(page):
                page.session_logs_panel._refresh_full()
                return
        from .session_log import get_session_log_path
        log_path = get_session_log_path()
        if log_path and log_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))
        else:
            VintageMessageBox.information(
                None, "Session Log", "No session log found for this session."
            )

    def _open_logs_folder(self) -> None:
        """Open the logs folder in the system file manager."""
        from .session_log import get_log_dir
        log_dir = get_log_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _copy_log_path(self) -> None:
        """Copy the current session log path to the clipboard."""
        from .session_log import get_session_log_path
        log_path = get_session_log_path()
        if log_path:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(str(log_path))
            self.statusBar().showMessage(f"Log path copied: {log_path}", 5000)
        else:
            self.statusBar().showMessage("No session log active", 3000)

    def _reenable_basic_track_count_warning(self) -> None:
        """Clear suppression so the >255 tracks per station warning can appear again."""
        key = "basic_suppress_track_count_over_255_warning"
        was_suppressed = self.db.get_setting(key, "0") == "1"
        self.db.set_setting(key, "0")
        if was_suppressed:
            VintageMessageBox.information(
                self,
                "Track count warning",
                "The warning for stations over 255 tracks will be shown again "
                "the next time it applies.",
            )
        else:
            self.statusBar().showMessage(
                "Track count warning for 255+ tracks was already enabled.", 5000
            )

    def _check_for_updates_menu(self) -> None:
        self._check_for_updates(manual=True)

    def _check_for_updates_on_startup(self) -> None:
        if not getattr(sys, "frozen", False):
            return
        self._check_for_updates(manual=False)

    def _check_for_updates(self, *, manual: bool) -> None:
        if self._update_check_in_flight:
            if manual:
                VintageMessageBox.information(
                    self,
                    "Check for Updates",
                    "An update check is already in progress.",
                )
            return

        self._update_check_in_flight = True

        def _worker() -> None:
            try:
                result = updater.run_update_check(
                    user_agent=f"VintageRadio/{__version__}",
                    current_version=__version__,
                )
                self.update_check_finished.emit(result, manual, "")
            except Exception as e:
                self.update_check_finished.emit(None, manual, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_check_finished(self, info: object, manual: bool, error: str) -> None:
        self._update_check_in_flight = False

        if error:
            if manual:
                VintageMessageBox.warning(
                    self,
                    "Check for Updates",
                    f"Could not check for updates:\n{error}",
                )
            return

        if isinstance(info, updater.UpdateCheckResult):
            result = info
        elif isinstance(info, updater.ReleaseInfo):
            result = updater.UpdateCheckResult(
                status="update_available",
                release=info,
            )
        else:
            result = updater.UpdateCheckResult(status="unavailable")

        if result.status == "unavailable":
            if manual:
                detail = (result.error or "").strip()
                body = "Could not fetch release information from GitHub."
                if detail:
                    body = f"{body}\n\n{detail}"
                body = (
                    f"{body}\n\nIf your connection is fine, the API may be rate-limited or "
                    f"temporarily unavailable. You can open the releases page manually:\n"
                    f"{updater.GITHUB_RELEASES_URL}"
                )
                VintageMessageBox.warning(self, "Check for Updates", body)
            return

        if result.status == "update_available" and result.release is not None:
            if updater.is_newer(result.release.advertised_version(), __version__):
                self._show_update_dialog(result.release)
                return

        if manual:
            msg = f"You're up to date.\nCurrent version: {__version__}"
            latest = (result.latest_published or "").strip()
            if latest and updater.is_newer(__version__, latest):
                msg += f"\nLatest on GitHub: {latest}"
            VintageMessageBox.information(self, "Check for Updates", msg)

    def _show_update_dialog(self, release: updater.ReleaseInfo) -> None:
        dlg = UpdateAvailableDialog(release, __version__, self)
        dlg.exec()

    def _show_about(self) -> None:
        VintageMessageBox.information(
            self,
            "About Vintage Radio",
            "Vintage Radio Music Manager\n"
            f"Version: {__version__}\n\n"
            f"Releases: {updater.GITHUB_RELEASES_URL}",
        )

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        from gui.window_chrome import ensure_native_caption_colors

        ensure_native_caption_colors(self)
        super().showEvent(event)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.WindowStateChange:
            from gui.window_chrome import apply_native_caption_colors

            apply_native_caption_colors(self)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            if getattr(self, "_mcp_manager", None) is not None and self._mcp_manager.is_running():
                self._mcp_manager.stop()
        except Exception:
            pass
        super().closeEvent(event)

    @staticmethod
    def _format_duration(value: Optional[float]) -> str:
        if value is None:
            return ""
        try:
            seconds = int(round(float(value)))
        except (TypeError, ValueError):
            return ""
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def _set_table_item(
        table: QtWidgets.QTableWidget,
        row: int,
        column: int,
        value: Optional[str],
        *,
        editable: bool = False,
    ) -> None:
        item = QtWidgets.QTableWidgetItem(value or "")
        if editable:
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, column, item)


class _VintageRadioTooltipStyle(QtWidgets.QProxyStyle):
    """Lengthen default tooltip hide delay so longer help text stays readable on hover."""

    def styleHint(  # type: ignore[override]
        self,
        hint: QtWidgets.QStyle.StyleHint,
        option: Optional[QtWidgets.QStyleOption] = None,
        widget: Optional[QtWidgets.QWidget] = None,
        returnData: Any = None,
    ) -> int:
        if hint == QtWidgets.QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return 25000
        if hint == QtWidgets.QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return 400
        return int(super().styleHint(hint, option, widget, returnData))


def run_app() -> None:
    # Initialize session logging BEFORE anything else
    from .session_log import init_session_logging, install_messagebox_session_logging
    log_path = init_session_logging(app_version=__version__)
    install_messagebox_session_logging()
    print(f"Vintage Radio GUI starting...")

    QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor
    )
    app = QtWidgets.QApplication(sys.argv)
    configure_vintage_app_rendering(app)
    try:
        app.setStyle(_VintageRadioTooltipStyle(app.style()))
    except Exception:
        pass
    install_vintage_popup_styles(app)

    # Set application icon (radio icon; taskbar/dock)
    icon_path = resource_path("vintage_radio.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Startup diagnostic: check whether VLC or ffmpeg+pydub are available for audio conversion.
    try:
        from .sd_manager import SDManager, PYDUB_AVAILABLE
        sd_check = SDManager(None)  # type: ignore[arg-type]
        vlc_ok = sd_check._check_vlc()
        ffmpeg_ok = sd_check._check_ffmpeg()
        if not vlc_ok and not ffmpeg_ok:
            # Build platform-specific install hints
            import platform
            system = platform.system()
            if system == "Darwin":
                hint = (
                    "Install VLC (VideoLAN) application: https://www.videolan.org/vlc/\n"
                    "Or via Homebrew: brew install --cask vlc\n"
                    "Install ffmpeg (for pydub): brew install ffmpeg\n"
                    "Then in your virtualenv: pip install python-vlc pydub certifi"
                )
            elif system == "Windows":
                hint = (
                    "Install VLC: https://www.videolan.org/vlc/ (ensure 'Add to PATH' if available)\n"
                    "Install ffmpeg: https://ffmpeg.org/download.html (add to PATH)\n"
                    "Then in your environment: pip install python-vlc pydub certifi"
                )
            else:
                hint = (
                    "Install VLC (package manager or https://www.videolan.org/vlc/)\n"
                    "Install ffmpeg (e.g. apt install ffmpeg)\n"
                    "Then: pip install python-vlc pydub certifi"
                )
            VintageMessageBox.information(
                None,
                "Conversion tools not found",
                "No audio conversion tools were detected on your system.\n\n"
                "To enable conversion (recommended), install VLC or ffmpeg + pydub.\n\n"
                f"Hints:\n{hint}",
            )
    except Exception:
        # If diagnostic fails, ignore silently — normal app functionality is unaffected.
        pass

    _dev_mode = "--dev" in sys.argv
    window = MainWindow(dev_mode=_dev_mode)
    window.show()
    from gui.window_chrome import ensure_native_caption_colors

    ensure_native_caption_colors(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    run_app()


