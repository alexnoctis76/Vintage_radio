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
from .sd_manager import SDManager, SYNC_TARGET_VOLUME_LABEL
from .experimental_sd_image import (
    pyfatfs_dependency_message,
    run_experimental_sd_disk_image_export,
    suggest_image_size_bytes,
)
from .sd_disk_image_flash import (
    LAST_CACHED_SD_IMAGE_FILENAME,
    darwin_default_bsd_disk_from_volume_path,
    darwin_get_disk_size_bytes,
    format_disk_size,
    is_windows_admin,
    windows_disk_number_for_drive_letter,
    windows_drive_letter_from_path,
    windows_get_disk_size_bytes,
    write_image_to_physical_disk,
    write_image_to_physical_disk_darwin,
    DARWIN_FDA_REQUIRED_MARKER,
)
from .widgets.sd_disk_image_wizard_dialog import SdDiskImageFlashWizardDialog
from .session_log import write_session_line, get_session_log_path
from .test_mode import TestModeWidget
from .debug_mcp_server import DebugMcpServerManager
from .widgets.task_progress_dialog import TaskProgressDialog, _BackgroundWorker
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
        self.setWindowTitle("Preferences")
        self.setModal(True)

        self.auto_backup_checkbox = QtWidgets.QCheckBox("Enable automatic backups")
        self.auto_backup_checkbox.setChecked(auto_backup)

        self.retention_spin = QtWidgets.QSpinBox()
        self.retention_spin.setRange(1, 100)
        self.retention_spin.setValue(backup_retention)

        retention_layout = QtWidgets.QHBoxLayout()
        retention_layout.addWidget(QtWidgets.QLabel("Backup retention (count):"))
        retention_layout.addWidget(self.retention_spin)

        self.sd_root_edit = QtWidgets.QLineEdit(sd_root)
        self.sd_root_edit.setPlaceholderText("Select SD card root folder")
        self.sd_browse_btn = QtWidgets.QPushButton("Browse")
        self.sd_browse_btn.clicked.connect(self.select_sd_root)
        sd_root_layout = QtWidgets.QHBoxLayout()
        sd_root_layout.addWidget(self.sd_root_edit)
        sd_root_layout.addWidget(self.sd_browse_btn)

        self.sd_auto_detect_checkbox = QtWidgets.QCheckBox(
            "Auto-detect SD card root (Windows)"
        )
        self.sd_auto_detect_checkbox.setChecked(sd_auto_detect)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.auto_backup_checkbox)
        layout.addLayout(retention_layout)
        layout.addWidget(QtWidgets.QLabel("SD card root folder:"))
        layout.addLayout(sd_root_layout)
        layout.addWidget(self.sd_auto_detect_checkbox)
        layout.addWidget(button_box)

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
        self.setWindowTitle("Edit Metadata")
        self.setModal(True)

        self.title_edit = QtWidgets.QLineEdit()
        self.title_edit.setPlaceholderText("Leave blank to keep existing")
        self.artist_edit = QtWidgets.QLineEdit()
        self.artist_edit.setPlaceholderText("Leave blank to keep existing")
        self.clear_empty_checkbox = QtWidgets.QCheckBox(
            "Clear fields when empty"
        )

        form = QtWidgets.QFormLayout()
        form.addRow("Title:", self.title_edit)
        form.addRow("Artist:", self.artist_edit)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.clear_empty_checkbox)
        layout.addWidget(button_box)

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
        text += "\n\nClick Setup Pico again to install the app once the Pico is connected."
    QtWidgets.QMessageBox.warning(parent, "Install to Pico", text)


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
) -> None:
    """Run install on main thread with progress dialog. Status bar updates via processEvents()."""
    dlg = QtWidgets.QDialog(parent)
    title = "Install to Pico (Basic Mode)" if basic_mode else "Install to Pico"
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(400)
    layout = QtWidgets.QVBoxLayout(dlg)
    status = QtWidgets.QLabel("Starting...")
    status.setWordWrap(True)
    layout.addWidget(status)
    progress = QtWidgets.QProgressBar()
    progress.setRange(0, 0)
    layout.addWidget(progress)
    dlg.show()
    QtWidgets.QApplication.processEvents()

    def report(step: int, total: int, msg: str):
        progress.setRange(0, max(1, total))
        progress.setValue(step)
        status.setText(msg)
        QtWidgets.QApplication.processEvents()

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


# REPL snippet for mpremote ``exec``: must print ``micropython`` so we do not treat a bare
# USB CDC session (or CircuitPython, etc.) as Vintage Radio–compatible MicroPython.
_MPREMOTE_MICROPYTHON_PROBE = (
    "import sys;n=getattr(sys.implementation,'name',None);print(n if n else '')"
)


def _mpremote_result_indicates_micropython(result: Any) -> bool:
    """True if mpremote exited OK and device output identifies MicroPython on the REPL."""
    if getattr(result, "returncode", 1) != 0:
        return False
    combined = ((getattr(result, "stdout", None) or "") + (getattr(result, "stderr", None) or "")).lower()
    return "micropython" in combined


def _wait_mpremote_serial_ready(
    mpremote_cmd: List[str],
    cwd: Optional[str],
    *,
    progress_callback: Optional[Callable[..., Any]],
    total_steps: int,
    creationflags: int = 0,
    env: Optional[dict] = None,
    deadline_s: float = 78.0,
    poll_s: float = 2.0,
) -> bool:
    """Poll until MicroPython answers on USB serial (Pico back after UF2 / reboot)."""
    import time

    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline_s:
        elapsed = int(time.monotonic() - t0)
        if progress_callback:
            progress_callback(
                0,
                max(1, total_steps),
                "Waiting for MicroPython on USB serial "
                f"(elapsed {elapsed}s, timeout {int(deadline_s)}s). "
                "After a fresh install the port can take several seconds.",
            )
        r = _run_mpremote(
            mpremote_cmd,
            ["connect", "auto", "exec", _MPREMOTE_MICROPYTHON_PROBE],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=14,
            creationflags=creationflags,
            env=env,
        )
        if _mpremote_result_indicates_micropython(r):
            return True
        time.sleep(poll_s)
    return False


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


# After copying a .uf2, Windows/macOS often need a few seconds before the new CDC port appears.
_POST_MICROPYTHON_INSTALL_DELAY_MS = 3500


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
                for c, text in enumerate(cols):
                    item = QtWidgets.QTableWidgetItem(text)
                    if c == 0:
                        item.setData(QtCore.Qt.ItemDataRole.UserRole, sid)
                        if extra is not None:
                            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, extra)
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                    self.setItem(new_row, c, item)
        finally:
            self.blockSignals(False)
            self.setSortingEnabled(True)

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

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

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
        self.setWindowTitle("Install MicroPython on Pico")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._downloaded_path: Optional[Path] = None
        self._preselect_rpi_rp2 = preselect_rpi_rp2
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
        layout = QtWidgets.QVBoxLayout(self)
        instructions = (
            "1. Hold the BOOTSEL button on the Pico.\n"
            "2. Plug the Pico into USB. It will appear as a drive (e.g. RPI-RP2).\n"
            "3. Select a firmware version below (auto-fetched), or browse for a .uf2 file.\n"
            "4. Click Install to Pico. The Pico will reboot with MicroPython (one-time setup)."
        )
        layout.addWidget(QtWidgets.QLabel(instructions))

        # ── Board selector ──
        form = QtWidgets.QFormLayout()
        self.board_combo = QtWidgets.QComboBox()
        self.board_combo.addItem("Pico", "Pico")
        self.board_combo.addItem("Pico W", "Pico W")
        self.board_combo.currentIndexChanged.connect(self._on_board_changed)
        form.addRow("Board:", self.board_combo)

        # ── Firmware version selector ──
        self.firmware_combo = QtWidgets.QComboBox()
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
        self.drive_combo = QtWidgets.QComboBox()
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
                QtWidgets.QMessageBox.warning(
                    self, "Install MicroPython on Pico",
                    "The file path entered is not a valid .uf2 file.",
                )
                return
            self._install_uf2(uf2_path)
            return

        # Use selected firmware from combo — need to download first
        fw_data = self.firmware_combo.currentData()
        if not fw_data or not isinstance(fw_data, dict):
            QtWidgets.QMessageBox.warning(
                self, "Install MicroPython on Pico",
                "No firmware selected. Either select a version from the dropdown or browse for a local .uf2 file.",
            )
            return

        # Verify drive first before downloading
        drive_data = self.drive_combo.currentData()
        if drive_data is None or not Path(drive_data).is_dir():
            QtWidgets.QMessageBox.warning(
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
            QtWidgets.QMessageBox.warning(
                self, "Install MicroPython on Pico",
                "No Pico drive selected. Hold BOOTSEL, plug in the Pico, then click Refresh.",
            )
            return
        dest_dir = Path(drive_data)
        if not dest_dir.is_dir():
            QtWidgets.QMessageBox.warning(
                self, "Install MicroPython on Pico",
                f"Drive not found: {dest_dir}. Unplug and replug the Pico (with BOOTSEL held), then Refresh.",
            )
            return
        dest_file = dest_dir / uf2_path.name
        try:
            shutil.copy2(uf2_path, dest_file)
        except OSError as e:
            QtWidgets.QMessageBox.warning(
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

    def __init__(self) -> None:
        super().__init__()
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

        self.library_table = LibraryTable()
        self.library_table.files_dropped.connect(self.import_files)
        self.library_table.itemChanged.connect(self.on_library_item_changed)
        self._loading_library = False
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

        self._build_menu()
        self._build_library_toolbar()
        self._build_tabs()
        self._set_button_cursors()
        self._refresh_all()
        self._build_status_bar_zoom()
        self._apply_ui_zoom()
        self._maybe_auto_start_mcp()
        QtCore.QTimer.singleShot(1200, self._check_for_updates_on_startup)

    def _apply_default_window_geometry(self) -> None:
        """Size and center window to a fraction of available screen (min/max bounds)."""
        app = QtWidgets.QApplication.instance()
        if not app:
            self.resize(1000, 700)
            return
        screen = app.primaryScreen()
        if not screen:
            self.resize(1000, 700)
            return
        rect = screen.availableGeometry()
        w = min(max(int(rect.width() * 0.85), 800), 1600)
        h = min(max(int(rect.height() * 0.85), 550), 1000)
        x = rect.x() + (rect.width() - w) // 2
        y = rect.y() + (rect.height() - h) // 2
        self.setGeometry(x, y, w, h)

    def _build_status_bar_zoom(self) -> None:
        """Add zoom +/- buttons at bottom left of the status bar."""
        container = QtWidgets.QWidget()
        zoom_layout = QtWidgets.QHBoxLayout(container)
        zoom_layout.setContentsMargins(4, 0, 4, 0)
        zoom_layout.setSpacing(2)
        zoom_label = QtWidgets.QLabel("Zoom")
        zoom_label.setStyleSheet("font-weight: bold;")
        zoom_layout.addWidget(zoom_label)
        zoom_out_btn = QtWidgets.QPushButton("\u2212")
        zoom_out_btn.setToolTip("Zoom out (min 80%)")
        zoom_out_btn.setFixedSize(26, 22)
        zoom_out_btn.clicked.connect(self._on_zoom_out)
        zoom_in_btn = QtWidgets.QPushButton("+")
        zoom_in_btn.setToolTip("Zoom in (max 200%)")
        zoom_in_btn.setFixedSize(26, 22)
        zoom_in_btn.clicked.connect(self._on_zoom_in)
        zoom_layout.addWidget(zoom_out_btn)
        zoom_layout.addWidget(zoom_in_btn)
        self.statusBar().addWidget(container)

    def _apply_ui_zoom(self) -> None:
        """Apply UI zoom level via application font scale. Uses a fixed base point size so direction stays correct."""
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

        # Propagate the new font to all child widgets so zoom takes effect everywhere.
        # Skip the debug console (QPlainTextEdit) which uses its own Ctrl+scroll zoom.
        from gui.device_debug import DeviceDebugWidget
        for widget in self.findChildren(QtWidgets.QWidget):
            if isinstance(widget, QtWidgets.QPlainTextEdit):
                if isinstance(widget.parent(), DeviceDebugWidget) or (
                    hasattr(widget, "objectName") and widget.objectName() == "console_output"
                ):
                    continue
            wf = widget.font()
            scaled = QFont(wf)
            scaled.setPointSize(new_pt)
            if wf.bold():
                scaled.setBold(True)
            widget.setFont(scaled)

        fm = QtGui.QFontMetrics(app.font())
        if hasattr(self, "_library_heading_label") and self._library_heading_label is not None:
            label_font = QFont(app.font())
            label_font.setBold(True)
            self._library_heading_label.setFont(label_font)
        if hasattr(self, "_lib_combo") and self._lib_combo is not None:
            self._lib_combo.setMinimumWidth(max(180, fm.averageCharWidth() * 22))
        min_w = min(1200, max(700, int(650 * self._ui_zoom_level // 100)))
        min_h = min(900, max(500, int(450 * self._ui_zoom_level // 100)))
        self.setMinimumSize(min_w, min_h)
        cw = self.centralWidget()
        if cw is not None:
            cw.setMinimumWidth(max(650, fm.averageCharWidth() * 72))
            if isinstance(cw, QtWidgets.QTabWidget):
                cw.tabBar().setExpanding(False)
        if hasattr(self, "library_table") and self.library_table is not None:
            self.library_table.horizontalHeader().setMinimumSectionSize(
                max(40, fm.averageCharWidth() * 8)
            )
        if hasattr(self, "_library_controls_widget") and self._library_controls_widget is not None:
            self._library_controls_widget.setMinimumWidth(max(400, fm.averageCharWidth() * 55))

    def _on_zoom_in(self) -> None:
        self._ui_zoom_level = min(200, self._ui_zoom_level + 10)
        self.db.set_setting("ui_zoom_level", str(self._ui_zoom_level))
        self._apply_ui_zoom()

    def _on_zoom_out(self) -> None:
        self._ui_zoom_level = max(80, self._ui_zoom_level - 10)
        self.db.set_setting("ui_zoom_level", str(self._ui_zoom_level))
        self._apply_ui_zoom()

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
        name, ok = QtWidgets.QInputDialog.getText(
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
        reply = QtWidgets.QMessageBox.question(
            self,
            "Remove custom source",
            f"Remove “{profiles[idx].get('name', '')}” from this library?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
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
            reply = QtWidgets.QMessageBox.question(
                self,
                "Developer mode",
                "The MCP debug server is under the Developer menu.\n\n"
                "Turn on Developer mode (saved in preferences) and start the MCP server?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.Yes,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
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
                QtWidgets.QMessageBox.warning(
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
        QtWidgets.QMessageBox.information(
            self,
            "MCP Debug Status",
            json.dumps(st, indent=2),
        )

    def _run_mcp_smoke_script(self) -> None:
        res = self._mcp_manager.run_script("basic_smoke")
        self._mcp_log("MCP smoke script result: {}".format(res))
        QtWidgets.QMessageBox.information(self, "MCP Smoke Script", json.dumps(res, indent=2))

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
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(window_title)
        dlg.resize(720, 520)
        lay = QtWidgets.QVBoxLayout(dlg)
        txt = QtWidgets.QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(str(suite.get("report_markdown", "")))
        lay.addWidget(txt)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)
        ok = bool(suite.get("ok"))
        self._mcp_log(
            "MCP acceptance finished: ok={} (see report dialog)".format(ok)
        )
        dlg.exec()

    def _run_mcp_acceptance_suite_dialog(self) -> None:
        """Quick/standard/full scripted suite — must not run on the GUI thread (deadlock)."""
        from .mcp_device_acceptance import run_acceptance_suite

        profile, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Acceptance suite",
            "Profile:",
            ["minimal", "standard", "full"],
            1,
            False,
        )
        if not ok:
            return
        target, ok2 = QtWidgets.QInputDialog.getItem(
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

        confirm = QtWidgets.QMessageBox.question(
            self,
            "Full device acceptance",
            "Runs the full on-device regression suite — typically 15–35+ minutes "
            "(5 tracks in playlist, shuffle-station, shuffle-library, 3 station changes, "
            "three ~6 s line-in captures, serial checks).\n\n"
            "Progress and Pico serial tails are appended to the MCP / session log "
            "(same place as [MCP] lines). Line-in steps pause logging for several seconds "
            "while the PC records audio — that is normal.\n\n"
            "Keep this window open. Continue?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        target, ok = QtWidgets.QInputDialog.getItem(
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
            QtWidgets.QMessageBox.warning(
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
            QtWidgets.QMessageBox.information(self, "Deploy MCP / VRTEST support", msg)
            return

        choice = QtWidgets.QDialog(self)
        choice.setWindowTitle("Deploy MCP / VRTEST support to Pico")
        choice.setMinimumWidth(520)
        v = QtWidgets.QVBoxLayout(choice)
        intro = QtWidgets.QLabel(
                "The MCP debug server runs on this computer. For serial automation (VRTEST), "
                "the Pico needs components/vintage_radio_ipc.py on its flash. "
                "Flashing a UF2 image alone often does not add new components/*.py files."
        )
        intro.setWordWrap(True)
        v.addWidget(intro)
        combo = QtWidgets.QComboBox()
        combo.addItem(
            "IPC only — components/vintage_radio_ipc.py (fixes ImportError)",
            False,
        )
        combo.addItem(
            "Full — IPC + main.py + main_basic.py from this app (poll_ipc in loop)",
            True,
        )
        v.addWidget(combo)
        foot = QtWidgets.QLabel(
            "Pico must be connected via USB (mpremote connect auto). "
            "The device will soft-reset after copy."
        )
        foot.setWordWrap(True)
        v.addWidget(foot)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(choice.accept)
        buttons.rejected.connect(choice.reject)
        v.addWidget(buttons)
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
            QtWidgets.QMessageBox.information(
                self,
                "Deploy MCP / VRTEST support",
                str(msg),
            )

        def on_err(msg: str) -> None:
            QtWidgets.QMessageBox.warning(
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
        self._capture_serial_debug_session_for_rebuild()
        old_central = self.centralWidget()
        self._device_debug_widget = None
        self._sd_card_tab_enter_refresh_done = False
        self._build_tabs()
        if old_central is not None:
            old_central.deleteLater()
        if self.devices_view_mode == "legacy":
            self._refresh_all()
        elif self.devices_view_mode in ("basic", "advanced"):
            QtCore.QTimer.singleShot(200, self._apply_serial_debug_restore)

    # ── Library switcher toolbar ──────────────────────────────

    def _build_library_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("Library")
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(16, 16))
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)

        self._library_heading_label = QtWidgets.QLabel("  Library: ")
        self._library_heading_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        tb.addWidget(self._library_heading_label)

        app = QtWidgets.QApplication.instance()
        if app:
            lib_font = QFont(app.font())
            lib_font.setBold(True)
            self._library_heading_label.setFont(lib_font)
        self._lib_combo = QtWidgets.QComboBox()
        if app:
            fm = QtGui.QFontMetrics(app.font())
            self._lib_combo.setMinimumWidth(max(180, fm.averageCharWidth() * 22))
        self._lib_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        tb.addWidget(self._lib_combo)
        self._populate_lib_combo()
        self._lib_combo.currentIndexChanged.connect(self._on_lib_combo_changed)

        new_btn = QtWidgets.QPushButton("New")
        new_btn.setToolTip("Create a new library")
        new_btn.clicked.connect(self._new_library)
        tb.addWidget(new_btn)

        rename_btn = QtWidgets.QPushButton("Rename")
        rename_btn.setToolTip("Rename the current library")
        rename_btn.clicked.connect(self._rename_library)
        tb.addWidget(rename_btn)

        delete_btn = QtWidgets.QPushButton("Delete")
        delete_btn.setToolTip("Delete the current library")
        delete_btn.clicked.connect(self._delete_library)
        tb.addWidget(delete_btn)

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
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Library", "Library name:"
        )
        if not ok or not name.strip():
            return
        try:
            slug = self._lib_registry.create_library(name.strip())
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, "New Library", str(e))
            return
        self._populate_lib_combo()
        self._switch_library(slug)

    def _rename_library(self) -> None:
        slug = self._lib_registry.active_library()
        old_name = self._lib_registry.active_library_name()
        name, ok = QtWidgets.QInputDialog.getText(
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
            QtWidgets.QMessageBox.information(
                self, "Delete Library", "Cannot delete the only library."
            )
            return
        reply = QtWidgets.QMessageBox.warning(
            self,
            "Delete Library",
            f"Permanently delete library \"{name}\" and all its data?\n\nThis cannot be undone.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        with self._wait_cursor_scope():
            self.db.close()
            self._lib_registry.delete_library(slug)
            new_slug = self._lib_registry.active_library()
            self.db = DatabaseManager(db_path=self._lib_registry.db_path_for(new_slug))
            self._propagate_db()
            self._populate_lib_combo()
            self._apply_saved_settings()
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
            self._lib_registry.set_active(slug)
            self.db = DatabaseManager(db_path=self._lib_registry.db_path_for(slug))
            self._propagate_db()
            self._populate_lib_combo()
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._apply_saved_settings()
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

    def _build_tabs(self) -> None:
        tabs = QtWidgets.QTabWidget()
        self._tabs_widget = tabs

        if self.devices_view_mode in ("basic", "advanced"):
            # Devices tab (advanced) is not built; sd_root_label may point at a
            # QLabel destroyed when switching from advanced — clear stale refs.
            if not _qt_widget_alive(getattr(self, "sd_root_label", None)):
                self.sd_root_label = None
            tabs.addTab(self._build_basic_mcu_tab(), "Microprocessor")
            tabs.addTab(self._build_basic_sd_card_tab(), "SD Card")
            self._device_debug_tab_index = -1
        else:
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

    def _append_basic_mcu_cheatsheet(self, fw_layout: QtWidgets.QVBoxLayout) -> None:
        # Collapsible reference: low-saturation grays (section / gesture / action differ by value).
        btn_cheatsheet_toggle = QtWidgets.QPushButton()
        btn_cheatsheet_toggle.setFlat(True)
        btn_cheatsheet_toggle.setCursor(
            QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        )
        btn_cheatsheet_toggle.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        btn_cheatsheet_toggle.setStyleSheet(
            "QPushButton { text-align: left; font-weight: bold; font-size: 14px; "
            "margin-top: 10px; padding: 6px 4px; border: none; background: transparent; }"
            "QPushButton:hover { background: rgba(128, 128, 128, 0.12); border-radius: 4px; }"
        )
        _cheatsheet_expanded = True
        
        def _toggle_basic_button_cheatsheet() -> None:
            nonlocal _cheatsheet_expanded
            _cheatsheet_expanded = not _cheatsheet_expanded
            btn_cheatsheet_table.setVisible(_cheatsheet_expanded)
            arrow = "\u25bc " if _cheatsheet_expanded else "\u25b6 "
            btn_cheatsheet_toggle.setText(arrow + "Button presses")
        
        btn_cheatsheet_toggle.clicked.connect(_toggle_basic_button_cheatsheet)
        btn_cheatsheet_toggle.setText("\u25bc Button presses")
        btn_cheatsheet_toggle.setToolTip("Show or hide the on-device button reference.")
        show_button_cheatsheet = not self._uses_custom_software()
        if show_button_cheatsheet:
            fw_layout.addWidget(btn_cheatsheet_toggle)
        
        # Table cheatsheet: shades of black (tiny lightness steps only).
        _cs_header_bg = QColor(38, 38, 40)
        _cs_header_fg = QColor(240, 240, 242)
        _cs_label_bg = QColor(22, 22, 24)
        _cs_label_fg = QColor(190, 190, 194)
        _cs_action_bg = QColor(30, 30, 32)
        _cs_action_fg = QColor(208, 208, 212)
        
        btn_cheatsheet_table = QtWidgets.QTableWidget()
        btn_cheatsheet_table.setObjectName("basicButtonCheatsheetTable")
        btn_cheatsheet_table.setColumnCount(2)
        btn_cheatsheet_table.verticalHeader().setVisible(False)
        btn_cheatsheet_table.horizontalHeader().setVisible(False)
        btn_cheatsheet_table.setShowGrid(True)
        btn_cheatsheet_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection
        )
        btn_cheatsheet_table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        btn_cheatsheet_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        # Vertical Minimum makes Qt give a short viewport → pointless scrollbar. We
        # size exactly to rows + turn scroll bars off so the cheatsheet never scrolls.
        btn_cheatsheet_table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        btn_cheatsheet_table.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        btn_cheatsheet_table.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        btn_cheatsheet_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        btn_cheatsheet_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        btn_cheatsheet_table.setStyleSheet(
            "QTableWidget#basicButtonCheatsheetTable { "
            "gridline-color: #2a2a2c; border: 1px solid #2a2a2c; "
            "background-color: #141416; border-radius: 4px; }"
            "QTableWidget#basicButtonCheatsheetTable::item { padding: 8px; }"
        )
        
        def _cs_header_row(title: str) -> None:
            r = btn_cheatsheet_table.rowCount()
            btn_cheatsheet_table.insertRow(r)
            it = QtWidgets.QTableWidgetItem(title)
            it.setBackground(QBrush(_cs_header_bg))
            it.setForeground(QBrush(_cs_header_fg))
            _hf = QFont(it.font())
            _hf.setBold(True)
            it.setFont(_hf)
            it.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            btn_cheatsheet_table.setItem(r, 0, it)
            btn_cheatsheet_table.setSpan(r, 0, 1, 2)
        
        def _cs_data_row(gesture: str, desc_plain: str) -> None:
            r = btn_cheatsheet_table.rowCount()
            btn_cheatsheet_table.insertRow(r)
            left = QtWidgets.QTableWidgetItem(gesture)
            left.setBackground(QBrush(_cs_label_bg))
            left.setForeground(QBrush(_cs_label_fg))
            lf = QFont(left.font())
            lf.setWeight(QFont.Weight.DemiBold)
            left.setFont(lf)
            left.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            btn_cheatsheet_table.setItem(r, 0, left)
            right = QtWidgets.QTableWidgetItem(desc_plain)
            right.setBackground(QBrush(_cs_action_bg))
            right.setForeground(QBrush(_cs_action_fg))
            right.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            right.setTextAlignment(
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            btn_cheatsheet_table.setItem(r, 1, right)
        
        def _cs_data_row_html(gesture: str, desc_html: str) -> None:
            r = btn_cheatsheet_table.rowCount()
            btn_cheatsheet_table.insertRow(r)
            left = QtWidgets.QTableWidgetItem(gesture)
            left.setBackground(QBrush(_cs_label_bg))
            left.setForeground(QBrush(_cs_label_fg))
            lf = QFont(left.font())
            lf.setWeight(QFont.Weight.DemiBold)
            left.setFont(lf)
            left.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            btn_cheatsheet_table.setItem(r, 0, left)
            # Cell widget + flat QLabel: a bare QLabel in a table cell often picks up a
            # sunken/frame border on macOS; wrapper + WA_StyledBackground + NoFrame fixes it.
            cell_wrap = QtWidgets.QWidget()
            cell_wrap.setObjectName("basicButtonCheatsheetCell")
            cell_wrap.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
            cell_wrap.setAutoFillBackground(True)
            _cw_pal = cell_wrap.palette()
            _cw_pal.setColor(QtGui.QPalette.ColorRole.Window, _cs_action_bg)
            cell_wrap.setPalette(_cw_pal)
            cell_lay = QtWidgets.QVBoxLayout(cell_wrap)
            cell_lay.setContentsMargins(0, 0, 0, 0)
            cell_lay.setSpacing(0)
            desc_lbl = QtWidgets.QLabel()
            desc_lbl.setObjectName("basicButtonCheatsheetRich")
            desc_lbl.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            desc_lbl.setLineWidth(0)
            desc_lbl.setMidLineWidth(0)
            desc_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
            desc_lbl.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            desc_lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
            desc_lbl.setText(desc_html)
            desc_lbl.setWordWrap(True)
            desc_lbl.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
            )
            desc_lbl.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.MinimumExpanding,
            )
            _ag = _cs_action_bg.name()
            _afg = _cs_action_fg.name()
            desc_lbl.setStyleSheet(
                f"QLabel#basicButtonCheatsheetRich {{ "
                f"background-color: {_ag}; color: {_afg}; "
                "border: none; outline: none; margin: 0px; padding: 8px; }}"
            )
            cell_lay.addWidget(desc_lbl, 1)
            btn_cheatsheet_table.setCellWidget(r, 1, cell_wrap)
        
        _cs_header_row("Taps")
        _cs_data_row("Single", "Next track")
        _cs_data_row("Double", "Previous track")
        _cs_data_row(
            "Triple",
            "Restart from the beginning: track 1 in station order, or first track "
            "in the current station track-shuffle pass",
        )
        _cs_data_row(
            "Four",
            "Previous station (or previous album/playlist when track-shuffling); "
            "pairs with Hold = next station",
        )
        _cs_data_row(
            "Five",
            "Jump to the first station and track 1; exits track shuffle if active",
        )
        
        _cs_header_row("Hold (long press, no taps)")
        _cs_data_row_html(
            "Hold",
            "Next station in folder order (also advances station while in track-shuffle mode).",
        )
        
        _cs_header_row("Tap + hold")
        _cs_data_row(
            "1 tap + hold",
            "Exit track shuffle to normal ordered-station mode (no-op if already ordered)",
        )
        _cs_data_row("2 taps + hold", "Shuffle tracks in the current station")
        _cs_data_row(
            "3 taps + hold",
            "First station with a fresh track shuffle (stays in shuffle; does not switch to ordered mode)",
        )
        
        btn_cheatsheet_table.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        
        def _refit_basic_button_cheatsheet_height() -> None:
            t = btn_cheatsheet_table
            t.resizeRowsToContents()
            h = 0
            hh = t.horizontalHeader()
            if hh.isVisible():
                h += hh.height()
            for r in range(t.rowCount()):
                rh = t.rowHeight(r)
                if rh <= 0:
                    rh = t.sizeHintForRow(r)
                h += max(rh, 1)
            h += 2 * t.frameWidth() + 4
            t.setFixedHeight(max(h, 120))
        
        _refit_basic_button_cheatsheet_height()
        QtCore.QTimer.singleShot(0, _refit_basic_button_cheatsheet_height)
        
        btn_cheatsheet_table.setToolTip(
            "Same gestures as firmware (radio_core). A tap is a short press; "
            "for Tap + hold, do your tap(s), then keep holding until the radio reacts."
        )
        if show_button_cheatsheet:
            fw_layout.addWidget(btn_cheatsheet_table)

    def _build_basic_mcu_tab(self) -> QtWidgets.QWidget:
        """Basic mode: Microprocessor tab with single setup button (left) and debug console (right)."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)

        # ── Left panel: single setup button ──
        left = QtWidgets.QWidget()
        left.setMinimumWidth(260)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)

        fw_group = QtWidgets.QGroupBox("Device Setup")
        fw_layout = QtWidgets.QVBoxLayout(fw_group)

        info_label = QtWidgets.QLabel(
            "Connect your RP2040 Pico via USB, then click the button below.\n"
            "MicroPython is installed automatically if needed, then Vintage Radio "
            "Pico firmware and supporting files are copied to the device."
        )
        info_label.setWordWrap(True)
        info_label.setForegroundRole(QtGui.QPalette.ColorRole.Text)
        info_label.setStyleSheet("padding: 4px;")
        fw_layout.addWidget(info_label)

        presence_row = QtWidgets.QHBoxLayout()
        presence_row.addWidget(QtWidgets.QLabel("USB"))
        self._basic_device_detected_led = QtWidgets.QLabel()
        self._basic_device_detected_led.setFixedSize(16, 16)
        self._set_basic_device_presence_indicator(False)
        presence_row.addWidget(self._basic_device_detected_led)
        self._basic_device_detected_label = QtWidgets.QLabel("No serial device detected")
        self._basic_device_detected_label.setForegroundRole(QtGui.QPalette.ColorRole.Text)
        presence_row.addWidget(self._basic_device_detected_label)
        presence_row.addStretch()
        fw_layout.addLayout(presence_row)

        fw_layout.addSpacing(8)

        setup_btn = QtWidgets.QPushButton("Setup Device")
        if self._is_advanced_mode():
            setup_btn.setToolTip(
                "Advanced setup. For 'Our software' this flashes advanced app firmware. "
                "For custom software, it installs MicroPython (if needed) and copies your selected files."
            )
            setup_btn.clicked.connect(self._on_setup_advanced_device_clicked)
        else:
            setup_btn.setToolTip(
                "One-click setup: installs MicroPython if needed, then copies Vintage Radio "
                "basic-mode firmware, pin configuration, and the AM overlay sound file to the Pico."
            )
            setup_btn.clicked.connect(self._on_setup_basic_device_clicked)
        setup_btn.setStyleSheet("font-weight: bold; padding: 10px; font-size: 14px;")
        fw_layout.addWidget(setup_btn)

        if self._is_advanced_mode():
            source_label = QtWidgets.QLabel("Software source")
            source_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            fw_layout.addWidget(source_label)
            self._advanced_software_source_combo = QtWidgets.QComboBox()
            self._advanced_software_source_combo.addItem("Our software (recommended)", "our")
            self._advanced_software_source_combo.addItem("Custom software (local files/folder)", "custom")
            src_setting = self._software_source_for_sync()
            self._advanced_software_source_combo.setCurrentIndex(1 if src_setting == "custom" else 0)
            self._advanced_software_source_combo.currentIndexChanged.connect(self._on_advanced_software_source_changed)
            fw_layout.addWidget(self._advanced_software_source_combo)

            profile_row = QtWidgets.QWidget()
            profile_layout = QtWidgets.QHBoxLayout(profile_row)
            profile_layout.setContentsMargins(0, 0, 0, 0)
            profile_layout.addWidget(QtWidgets.QLabel("Saved custom sources"))
            self._advanced_custom_profile_combo = QtWidgets.QComboBox()
            self._advanced_custom_profile_combo.blockSignals(True)
            profiles = self._advanced_custom_profiles_ensure()
            active_i = self._advanced_active_profile_index()
            if profiles and active_i >= len(profiles):
                active_i = max(0, len(profiles) - 1)
                self._advanced_set_active_profile_index(active_i)
            for p in profiles:
                self._advanced_custom_profile_combo.addItem(p.get("name") or "Unnamed")
            if self._advanced_custom_profile_combo.count() > 0:
                self._advanced_custom_profile_combo.setCurrentIndex(
                    min(active_i, self._advanced_custom_profile_combo.count() - 1)
                )
            self._advanced_custom_profile_combo.blockSignals(False)
            profile_layout.addWidget(self._advanced_custom_profile_combo, 1)
            add_src_btn = QtWidgets.QPushButton("Add Software Source")
            add_src_btn.setToolTip("Pick a folder, then name it. It appears in the list for install and notes.")
            add_src_btn.clicked.connect(self._on_advanced_add_software_source)
            rem_src_btn = QtWidgets.QPushButton("Remove")
            rem_src_btn.setToolTip("Remove the selected saved source from this library.")
            rem_src_btn.clicked.connect(self._on_advanced_remove_custom_source)
            profile_layout.addWidget(add_src_btn)
            profile_layout.addWidget(rem_src_btn)
            fw_layout.addWidget(profile_row)
            profile_row.setVisible(self._uses_custom_software())

            notes_above_eq = QtWidgets.QLabel("Notes / description (above DFPlayer EQ)")
            notes_above_eq.setStyleSheet("font-weight: bold; margin-top: 10px;")
            fw_layout.addWidget(notes_above_eq)
            self._advanced_mcu_notes_edit = QtWidgets.QTextEdit()
            self._advanced_mcu_notes_edit.setMinimumHeight(72)
            self._advanced_mcu_notes_edit.setMaximumHeight(160)
            fw_layout.addWidget(self._advanced_mcu_notes_edit)

            eq_label = QtWidgets.QLabel("DFPlayer EQ (our software only)")
            eq_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            fw_layout.addWidget(eq_label)
            self._advanced_dfplayer_eq_combo = QtWidgets.QComboBox()
            for lbl, data in (
                ("Normal", "normal"),
                ("Pop", "pop"),
                ("Rock", "rock"),
                ("Jazz", "jazz"),
                ("Classic", "classic"),
                ("Bass", "bass"),
            ):
                self._advanced_dfplayer_eq_combo.addItem(lbl, data)
            eq_current = self._selected_dfplayer_eq()
            for idx in range(self._advanced_dfplayer_eq_combo.count()):
                if self._advanced_dfplayer_eq_combo.itemData(idx) == eq_current:
                    self._advanced_dfplayer_eq_combo.setCurrentIndex(idx)
                    break
            self._advanced_dfplayer_eq_combo.currentIndexChanged.connect(self._on_advanced_dfplayer_eq_changed)
            fw_layout.addWidget(self._advanced_dfplayer_eq_combo)

            btn_doc_label = QtWidgets.QLabel("Button presses (editable table, saved per library or source)")
            btn_doc_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            btn_doc_label.setToolTip(
                "Each row has a row-action control on the left (green highlight on hover). "
                "Click it for insert/delete and section options, or right-click gesture/action cells."
            )
            fw_layout.addWidget(btn_doc_label)
            self._advanced_mcu_buttons_scroll = QtWidgets.QScrollArea()
            self._advanced_mcu_buttons_scroll.setObjectName("advancedMcuButtonsScroll")
            self._advanced_mcu_buttons_scroll.setWidgetResizable(False)
            self._advanced_mcu_buttons_scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._advanced_mcu_buttons_scroll.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            self._advanced_mcu_buttons_scroll.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            self._advanced_mcu_buttons_scroll.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            self._advanced_mcu_buttons_scroll.setStyleSheet(
                "QScrollArea#advancedMcuButtonsScroll { border: 1px solid #2a2a2c; border-radius: 4px; "
                "background-color: #0e0e10; }"
                "QScrollBar:vertical { min-width: 16px; background: #1a1a1c; margin: 2px; border-radius: 4px; }"
                "QScrollBar::handle:vertical { min-height: 36px; background: #4a4a52; border-radius: 7px; }"
                "QScrollBar::handle:vertical:hover { background: #4CAF50; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
            )
            self._advanced_mcu_buttons_table = QtWidgets.QTableWidget(0, 3)
            self._advanced_mcu_buttons_table.setObjectName("advancedMcuButtonsTable")
            self._advanced_mcu_buttons_table.setHorizontalHeaderLabels(
                ["", "Gesture / control", "Action"]
            )
            self._advanced_mcu_buttons_table.verticalHeader().setVisible(False)
            _mcu_hh = self._advanced_mcu_buttons_table.horizontalHeader()
            _mcu_hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
            _mcu_hh.resizeSection(0, _ADV_MCU_JUNCTION_W)
            _mcu_hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
            _mcu_hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
            _mcu_hh.resizeSection(1, 200)
            self._advanced_mcu_buttons_table.setSelectionMode(
                QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
            )
            self._advanced_mcu_buttons_table.setEditTriggers(
                QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
                | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            )
            self._advanced_mcu_buttons_table.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._advanced_mcu_buttons_table.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._advanced_mcu_buttons_table.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            self._advanced_mcu_buttons_table.setStyleSheet(
                "QTableWidget#advancedMcuButtonsTable { "
                "gridline-color: #2a2a2c; border: none; "
                "background-color: #141416; }"
                "QTableWidget#advancedMcuButtonsTable::item { padding: 6px; color: #e8e8ea; }"
                "QHeaderView::section { background-color: #262628; color: #f0f0f2; padding: 6px; "
                "border: 1px solid #2a2a2c; font-weight: bold; }"
            )
            self._advanced_mcu_buttons_table.setContextMenuPolicy(
                QtCore.Qt.ContextMenuPolicy.CustomContextMenu
            )
            self._advanced_mcu_buttons_table.customContextMenuRequested.connect(
                self._on_advanced_mcu_buttons_table_context_menu
            )
            self._advanced_mcu_buttons_table.setMouseTracking(True)
            self._advanced_mcu_buttons_table.viewport().setMouseTracking(True)
            self._advanced_mcu_buttons_scroll.setWidget(self._advanced_mcu_buttons_table)
            self._advanced_mcu_layout_filter = _AdvancedMcuTableLayoutFilter(self)
            self._advanced_mcu_buttons_scroll.viewport().installEventFilter(self._advanced_mcu_layout_filter)
            self._advanced_mcu_buttons_scroll.installEventFilter(self._advanced_mcu_layout_filter)
            self._advanced_mcu_buttons_table.cellEntered.connect(self._advanced_mcu_on_cell_entered)
            fw_layout.addWidget(self._advanced_mcu_buttons_scroll)
            self._advanced_mcu_install_outside_selection_filters(fw_group)

            self._advanced_custom_profile_combo.currentIndexChanged.connect(
                self._on_advanced_custom_profile_changed
            )
            self._load_advanced_mcu_profile_into_ui()
            self._advanced_mcu_notes_edit.textChanged.connect(self._schedule_flush_advanced_mcu_fields)
            self._advanced_mcu_buttons_table.itemChanged.connect(
                self._on_advanced_mcu_button_table_item_changed
            )
            QtCore.QTimer.singleShot(0, self._advanced_refit_mcu_button_table_height)
            if self._uses_custom_software() and self._advanced_custom_profile_combo.count() > 0:
                self._advanced_profile_combo_last_idx = self._advanced_custom_profile_combo.currentIndex()
            else:
                self._advanced_profile_combo_last_idx = -1

        if not self._is_advanced_mode():
            self._append_basic_mcu_cheatsheet(fw_layout)

        fw_layout.addStretch()
        left_layout.addWidget(fw_group)

        # ── Right panel: streamlined debug console ──
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        debug_group = QtWidgets.QGroupBox("Device Console")
        debug_layout = QtWidgets.QVBoxLayout(debug_group)
        self._basic_debug_container = debug_group
        self._basic_debug_layout = debug_layout
        self._basic_debug_widget = DeviceDebugWidget(
            basic_mode=True,
            db=self.db,
            db_getter=lambda: self.db,
        )
        self._basic_debug_widget.device_presence_changed.connect(
            self._set_basic_device_presence_indicator
        )
        debug_layout.addWidget(self._basic_debug_widget)
        right_layout.addWidget(debug_group)

        has_usb = SDManager.is_rp2040_bootsel_present()
        try:
            import serial.tools.list_ports as list_ports

            has_usb = has_usb or any(
                DeviceDebugWidget._is_rp2040_port(port_info)
                for port_info in list_ports.comports()
            )
        except Exception:
            pass
        self._set_basic_device_presence_indicator(bool(has_usb))

        layout.addWidget(left, 1)
        layout.addWidget(right, 2)
        return widget

    def _set_basic_device_presence_indicator(self, detected: bool) -> None:
        """Green LED when a Pico shows up as serial, console connected, or BOOTSEL (RPI-RP2 drive)."""
        led = getattr(self, "_basic_device_detected_led", None)
        lbl = getattr(self, "_basic_device_detected_label", None)
        if not _qt_widget_alive(led):
            return
        if detected:
            led.setStyleSheet(
                "min-width: 14px; max-width: 14px; min-height: 14px; max-height: 14px; "
                "border-radius: 7px; background-color: #2ecc40; border: 1px solid #1a9930;"
            )
            led.setToolTip(
                "USB: MicroPython serial port, connected Device Console, or unflashed Pico in "
                "BOOTSEL mode (RPI-RP2 removable drive)."
            )
            if _qt_widget_alive(lbl):
                lbl.setText("Device detected")
                lbl.setForegroundRole(QtGui.QPalette.ColorRole.Text)
                lbl.setStyleSheet("font-weight: bold;")
        else:
            led.setStyleSheet(
                "min-width: 14px; max-width: 14px; min-height: 14px; max-height: 14px; "
                "border-radius: 7px; background-color: #bdc3c7; border: 1px solid #95a5a6;"
            )
            led.setToolTip(
                "No Pico detected. Plug in USB, or hold BOOTSEL while plugging in (RPI-RP2 drive)."
            )
            if _qt_widget_alive(lbl):
                lbl.setText("No serial device detected")
                lbl.setForegroundRole(QtGui.QPalette.ColorRole.Text)
                lbl.setStyleSheet("")

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
        if not cur:
            return False
        return _volume_name_key(cur) != _volume_name_key(trusted)

    def _basic_confirm_first_sd_sync_target(self, sd_path_str: str) -> bool:
        """One-time check before the first successful basic sync (no trusted volume yet)."""
        if not self._is_basic_like_mode():
            return True
        if (self.db.get_setting("basic_trusted_sd_volume") or "").strip():
            return True
        vol = self._basic_sd_path_volume_tag(sd_path_str)
        vol_line = vol if vol else "(unknown)"
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm SD card",
            "This library has not completed a basic-mode sync to an SD card yet.\n\n"
            f"You are about to write station folders to:\n  {sd_path_str}\n"
            f"Volume name (best guess): {vol_line}\n\n"
            "Make sure this is the correct SD card or USB drive. Writing to the "
            "wrong device can erase important data.\n\n"
            "Proceed with sync to this location?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        return reply == QtWidgets.QMessageBox.StandardButton.Yes

    def _basic_confirm_different_card(self, new_root: str, *, for_sync: bool) -> bool:
        """If the volume differs from the last basic sync target, confirm. Returns False to abort."""
        if not self._is_basic_like_mode():
            return True
        if not self._basic_should_warn_different_card(new_root):
            return True
        trusted = (self.db.get_setting("basic_trusted_sd_volume") or "").strip()
        cur = self._basic_sd_path_volume_tag(new_root)
        verb = "sync stations to" if for_sync else "use"
        reply = QtWidgets.QMessageBox.question(
            self,
            "Different SD card",
            f'Your last successful basic-mode sync used the volume named "{trusted}".\n\n'
            f'The selected path looks like "{cur}".\n\n'
            "If this is the wrong card, you could overwrite the wrong device.\n\n"
            f'Do you want to {verb} this volume anyway?',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        return reply == QtWidgets.QMessageBox.StandardButton.Yes

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
        if (self.db.get_setting("sd_volume_label") or "").strip():
            k = _volume_name_key(SYNC_TARGET_VOLUME_LABEL)
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
        ``basic_trusted_sd_volume`` / ``sd_volume_label`` / ``VINTAGERADIO``.
        """
        names: set = set()
        for raw in (
            self.db.get_setting("sd_volume_label"),
            self.db.get_setting("basic_trusted_sd_volume"),
        ):
            k = _volume_name_key(raw)
            if k:
                names.add(k)
        if (self.db.get_setting("sd_volume_label") or "").strip():
            k = _volume_name_key(SYNC_TARGET_VOLUME_LABEL)
            if k:
                names.add(k)
        return names

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
            QtWidgets.QMessageBox.information(
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
                QtWidgets.QMessageBox.information(
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
            QtWidgets.QMessageBox.information(
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
            QtWidgets.QMessageBox.information(
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
            QtWidgets.QMessageBox.information(
                self,
                "SD Detect",
                "Multiple removable drives are connected, and no saved SD identity is set yet.\n\n"
                "Use Select to pick your SD card. After a successful sync, Detect will "
                "find that card automatically by name.",
            )
            return

        QtWidgets.QMessageBox.information(
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
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("SD Card Differences")
        dlg.resize(560, 380)
        layout = QtWidgets.QVBoxLayout(dlg)
        text = QtWidgets.QTextEdit()
        text.setReadOnly(True)
        if len(msgs) > 30:
            text.setPlainText(
                "Your SD card differs from your library in many places "
                "(first 30 shown below).\nSyncing will bring the card up to date.\n\n"
                + "\n".join(f"  - {m}" for m in msgs[:30])
                + f"\n  ... and {len(msgs) - 30} more."
            )
        else:
            text.setPlainText("\n".join(f"  - {m}" for m in msgs))
        layout.addWidget(text)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dlg.exec()

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

            time.sleep(0.35)
            write_session_line(
                "Released app-held serial port(s) so mpremote can access the device",
                prefix=log_prefix,
            )
            print("[Vintage Radio] Released app-held serial port(s) for mpremote")
        return released

    def _on_setup_basic_device_clicked(self) -> None:
        """Qt slot: log first (durable) then run setup — isolates signal vs handler crashes."""
        write_session_line("Setup Device: Qt clicked (before _setup_basic_device)", prefix="SETUP")
        self._setup_basic_device()

    def _on_setup_advanced_device_clicked(self) -> None:
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
                QtWidgets.QMessageBox.information(self, "Setup Device", msg)
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
                    QtWidgets.QMessageBox.warning(self, "Setup Device", "firmware/pico/main_basic.py not found.")
                    return

            install_now = install_callback or (lambda: self.install_to_pico(basic_mode=True))

            # Prefer explicit RP2040 ports first to avoid grabbing unrelated serial devices (e.g. Bluetooth COM).
            rp_ports: List[Any] = []
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
                for port_info in rp_ports:
                    port_dev = getattr(port_info, "device", None) or str(port_info)
                    write_session_line(f"Trying mpremote explicit connect: {port_dev}", prefix="SETUP")
                    print(f"[Setup Basic Device] Trying mpremote explicit connect: {port_dev}")
                    r = _run_mpremote(
                        mpremote_cmd,
                        ["connect", port_dev, "exec", _MPREMOTE_MICROPYTHON_PROBE],
                        cwd=str(root),
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    out = ((r.stdout or "") + (r.stderr or "")).strip()
                    if out:
                        write_session_line(
                            f"explicit connect output ({port_dev}): {out[:800]}",
                            prefix="SETUP",
                        )
                        print(f"[Setup Basic Device] explicit connect output ({port_dev}): {out[:600]}")
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
            except Exception:
                write_session_line(
                    f"RP2040 explicit scan/connect exception:\n{traceback.format_exc()}",
                    prefix="SETUP",
                )
                print("[Setup Basic Device] RP2040 explicit scan/connect exception:")
                print(traceback.format_exc())

            # Fallback: can we reach a running MicroPython via auto-detected port?
            write_session_line("Trying mpremote auto connect fallback", prefix="SETUP")
            print("[Setup Basic Device] Trying mpremote auto connect fallback")
            try:
                r = _run_mpremote(
                    mpremote_cmd,
                    ["connect", "auto", "exec", _MPREMOTE_MICROPYTHON_PROBE],
                    cwd=str(root), capture_output=True, text=True, timeout=10,
                )
                out = ((r.stdout or "") + (r.stderr or "")).strip()
                if out:
                    write_session_line(f"auto connect output: {out[:800]}", prefix="SETUP")
                    print(f"[Setup Basic Device] auto connect output: {out[:600]}")
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
                write_session_line("Opening InstallMicroPythonDialog", prefix="SETUP")
                print("[Setup Basic Device] Opening InstallMicroPythonDialog")
                dlg = InstallMicroPythonDialog(self, preselect_rpi_rp2=True)
                dlg.exec()
                self.statusBar().showMessage(f"MicroPython installed. Installing {install_label}...", 8000)
                QtCore.QTimer.singleShot(_POST_MICROPYTHON_INSTALL_DELAY_MS, install_now)
                return

            if rp_ports:
                write_session_line(
                    "RP2040 USB serial seen but MicroPython not verified — prompt for UF2 install",
                    prefix="SETUP",
                )
                print("[Setup Basic Device] RP2040 port(s) present without verified MicroPython")
                msg = QtWidgets.QMessageBox(self)
                msg.setIcon(QtWidgets.QMessageBox.Icon.Information)
                msg.setWindowTitle("Setup Device — MicroPython required")
                msg.setText(
                    "A Raspberry Pi Pico USB serial port was found, but MicroPython did not respond.\n\n"
                    "On a new or erased board you must install MicroPython before Vintage Radio can "
                    "copy firmware.\n\n"
                    "1. Hold BOOTSEL and plug the Pico into USB (it should show up as RPI-RP2 "
                    "like a thumb drive).\n"
                    "2. Click Install MicroPython… and copy the .uf2 file to that drive.\n"
                    "3. When the Pico reboots, run Setup Device again.\n\n"
                    "If MicroPython is already installed, close other apps using the serial port and retry."
                )
                install_btn = msg.addButton(
                    "Install MicroPython…", QtWidgets.QMessageBox.ButtonRole.ActionRole
                )
                msg.addButton("Close", QtWidgets.QMessageBox.ButtonRole.RejectRole)
                msg.exec()
                if msg.clickedButton() == install_btn:
                    dlg = InstallMicroPythonDialog(self, preselect_rpi_rp2=True)
                    dlg.exec()
                    self.statusBar().showMessage(
                        f"When MicroPython is running, click Setup Device again to install {install_label}.",
                        12000,
                    )
                    QtCore.QTimer.singleShot(_POST_MICROPYTHON_INSTALL_DELAY_MS, install_now)
                return

            write_session_line("No compatible Pico detected (user message)", prefix="SETUP")
            print("[Setup Basic Device] No compatible Pico detected")
            QtWidgets.QMessageBox.information(
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
            QtWidgets.QMessageBox.critical(
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

    def _selected_conversion_profile(self) -> str:
        if not self._is_advanced_mode():
            return "dfplayer_safe"
        profile = (self.db.get_setting("advanced_conversion_profile", "dfplayer_safe") or "").strip().lower()
        if profile not in {"dfplayer_safe", "high_quality"}:
            return "dfplayer_safe"
        return profile

    def _on_advanced_conversion_profile_changed(self, *_args) -> None:
        combo = getattr(self, "_advanced_conversion_profile_combo", None)
        if combo is None:
            return
        self.db.set_setting(
            "advanced_conversion_profile",
            str(combo.currentData() or "dfplayer_safe"),
        )

    def _read_pico_install_mode(self) -> Optional[str]:
        """Read ``install_mode`` from ``VintageRadio/advanced_runtime.json`` on the Pico.

        When the Device console holds the serial port, use ``VRTEST get_install_mode`` so we
        never spawn a second ``mpremote`` session (that interrupts ``main.py``). When nothing
        is connected, fall back to ``mpremote exec``.
        """
        def _norm(val: object) -> Optional[str]:
            if val is None:
                return None
            m = str(val).strip().lower()
            if m in {"basic", "advanced", "legacy"}:
                return m
            return None

        self._ensure_device_debug_widget_loaded()
        tried_vrtest = False
        for _name in ("_basic_debug_widget", "_device_debug_widget"):
            w = getattr(self, _name, None)
            if w is None:
                continue
            if not getattr(w, "_connected", False):
                continue
            ser = getattr(w, "_serial_connection", None)
            if ser is None or not getattr(ser, "is_open", False):
                continue
            if not hasattr(w, "run_vrtest_command"):
                continue
            tried_vrtest = True
            vr = w.run_vrtest_command("get_install_mode", timeout=5.0)
            if vr.get("ok") and isinstance(vr.get("device"), dict):
                mode = _norm(vr["device"].get("install_mode"))
                if mode is not None:
                    return mode
        if tried_vrtest:
            try:
                write_session_line(
                    "[Pico] install_mode: VRTEST get_install_mode failed or unsupported firmware; "
                    "skipping mpremote while serial is open."
                )
            except Exception:
                pass
            return None

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

    def _build_basic_sd_card_tab(self) -> QtWidgets.QWidget:
        """Basic mode: SD Card tab with station manager, track list, capacity, and sync."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        warn_row = QtWidgets.QHBoxLayout()
        self._basic_sd_sync_warning = QtWidgets.QLabel()
        self._basic_sd_sync_warning.setWordWrap(True)
        self._basic_sd_sync_warning.setStyleSheet("color: #b07800; font-weight: bold;")
        self._basic_sd_sync_warning.setVisible(False)
        warn_row.addWidget(self._basic_sd_sync_warning, 1)
        self._basic_sd_sync_details_btn = QtWidgets.QPushButton("Details...")
        self._basic_sd_sync_details_btn.setVisible(False)
        self._basic_sd_sync_details_btn.setFixedWidth(80)
        self._basic_sd_sync_details_btn.clicked.connect(self._show_basic_sd_sync_details)
        warn_row.addWidget(self._basic_sd_sync_details_btn)
        layout.addLayout(warn_row)

        self._basic_sd_sync_issues: List[str] = []

        # ── Storage selector row ──
        storage_group = QtWidgets.QGroupBox("Storage")
        storage_layout = QtWidgets.QHBoxLayout(storage_group)
        storage_layout.addWidget(QtWidgets.QLabel("SD card root:"))
        self._basic_sd_root_label = QtWidgets.QLabel(self.sd_root or "(not set)")
        self._basic_sd_root_label.setStyleSheet("color: #555;")
        storage_layout.addWidget(self._basic_sd_root_label, 1)
        detect_btn = QtWidgets.QPushButton("Detect")
        detect_btn.setToolTip(
            "Find your SD card again using the saved volume name (e.g. after reconnecting USB). "
            "Does not ask to confirm a different card."
        )
        detect_btn.clicked.connect(self._select_sd_root_basic)
        select_btn = QtWidgets.QPushButton("Select")
        select_btn.setToolTip(
            "Pick from detected removable drives (dropdown). "
            "If nothing is listed, use Browse. Wrong-card safety is only on Sync."
        )
        select_btn.clicked.connect(self._select_sd_root_manual_basic)
        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_sd_root_basic)
        storage_layout.addWidget(detect_btn)
        storage_layout.addWidget(select_btn)
        storage_layout.addWidget(browse_btn)
        layout.addWidget(storage_group)

        # ── SD capacity bar ──
        cap_layout = QtWidgets.QHBoxLayout()
        cap_layout.addWidget(QtWidgets.QLabel("SD Capacity:"))
        self._basic_sd_capacity_bar = QtWidgets.QProgressBar()
        self._basic_sd_capacity_bar.setFormat("%p% used")
        self._basic_sd_capacity_bar.setValue(0)
        cap_layout.addWidget(self._basic_sd_capacity_bar, 1)
        self._basic_sd_capacity_label = QtWidgets.QLabel("")
        cap_layout.addWidget(self._basic_sd_capacity_label)
        layout.addLayout(cap_layout)

        # ── Station manager (left) + track list (right) ──
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # Left: station list
        station_panel = QtWidgets.QWidget()
        station_layout = QtWidgets.QVBoxLayout(station_panel)
        station_layout.setContentsMargins(0, 0, 0, 0)

        station_heading = QtWidgets.QHBoxLayout()
        stations_label = QtWidgets.QLabel("Stations")
        stations_label.setStyleSheet("font-weight: bold;")
        stations_label.setToolTip(
            "Drag stations to reorder. Each station maps to a numbered folder on the SD card. "
            "You can also drop folders here to import each folder as a station."
        )
        station_heading.addWidget(stations_label)
        self._basic_stations_size_label = QtWidgets.QLabel("")
        self._basic_stations_size_label.setStyleSheet("color: #888; font-size: 11px;")
        self._basic_stations_size_label.setToolTip("Estimated total size of all station tracks on the SD card")
        station_heading.addWidget(self._basic_stations_size_label)
        station_heading.addStretch()
        station_layout.addLayout(station_heading)

        self._basic_station_list = StationImportListWidget()
        self._basic_station_list.order_changed.connect(self._on_basic_station_reordered)
        self._basic_station_list.currentItemChanged.connect(self._on_basic_station_selected)
        self._basic_station_list.folders_dropped.connect(self._import_folders_as_basic_stations)
        self._basic_station_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._basic_station_list.customContextMenuRequested.connect(self._show_station_context_menu)
        station_layout.addWidget(self._basic_station_list)

        station_btns = QtWidgets.QHBoxLayout()
        add_station_btn = QtWidgets.QPushButton("New Station")
        add_station_btn.clicked.connect(self._create_basic_station)
        rename_station_btn = QtWidgets.QPushButton("Rename")
        rename_station_btn.clicked.connect(self._rename_basic_station)
        del_station_btn = QtWidgets.QPushButton("Delete")
        del_station_btn.clicked.connect(self._delete_basic_station)
        station_btns.addWidget(add_station_btn)
        station_btns.addWidget(rename_station_btn)
        station_btns.addWidget(del_station_btn)
        station_layout.addLayout(station_btns)
        splitter.addWidget(station_panel)

        # Right: tracks in selected station (reorderable + file drop)
        track_panel = QtWidgets.QWidget()
        track_layout = QtWidgets.QVBoxLayout(track_panel)
        track_layout.setContentsMargins(0, 0, 0, 0)
        self._basic_station_detail = QtWidgets.QLabel("Select a station to view tracks.")
        self._basic_station_detail.setWordWrap(True)
        track_layout.addWidget(self._basic_station_detail)

        self._basic_station_tracks_table = CollectionDropTable()
        self._basic_station_tracks_table.setColumnCount(4)
        self._basic_station_tracks_table.setHorizontalHeaderLabels(["Title", "Artist", "Duration", "Format"])
        self._basic_station_tracks_table.horizontalHeader().setStretchLastSection(True)
        self._basic_station_tracks_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._basic_station_tracks_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._basic_station_tracks_table.files_dropped.connect(self._import_files_to_basic_station)
        self._basic_station_tracks_table.order_changed.connect(self._persist_basic_station_track_order)
        self._basic_station_tracks_table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._basic_station_tracks_table.customContextMenuRequested.connect(self._show_station_track_context_menu)
        track_layout.addWidget(self._basic_station_tracks_table, 1)

        track_btns = QtWidgets.QHBoxLayout()
        add_tracks_btn = QtWidgets.QPushButton("Add Tracks")
        add_tracks_btn.setToolTip("Browse for audio files to add to this station (also imports them to the library)")
        add_tracks_btn.clicked.connect(self._add_tracks_to_basic_station)
        remove_tracks_btn = QtWidgets.QPushButton("Remove Selected")
        remove_tracks_btn.clicked.connect(self._remove_songs_from_basic_station)
        track_btns.addWidget(add_tracks_btn)
        track_btns.addWidget(remove_tracks_btn)
        track_btns.addStretch()
        track_layout.addLayout(track_btns)
        splitter.addWidget(track_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        # ── Sync buttons ──
        sync_group = QtWidgets.QGroupBox("Sync")
        sync_layout = QtWidgets.QHBoxLayout(sync_group)
        sync_btn = QtWidgets.QPushButton("Sync Stations to SD")
        sync_btn.setToolTip("Copy all stations to the SD card in DFPlayer folder format.")
        sync_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        sync_btn.clicked.connect(self._sync_basic_to_sd)
        eject_btn = QtWidgets.QPushButton("Safely Remove SD")
        eject_btn.clicked.connect(self.safely_remove_sd)
        self._basic_auto_eject_cb = QtWidgets.QCheckBox("Automatically safely remove SD card after syncing")
        self._basic_auto_eject_cb.setChecked(self.db.get_setting("auto_eject_after_sync", "0") == "1")
        self._basic_auto_eject_cb.stateChanged.connect(self._on_auto_eject_after_sync_changed)

        if self._is_advanced_mode():
            conv_box = QtWidgets.QGroupBox("Conversion Profile")
            conv_layout = QtWidgets.QHBoxLayout(conv_box)
            self._advanced_conversion_profile_combo = QtWidgets.QComboBox()
            self._advanced_conversion_profile_combo.addItem("DFPlayer-safe (default)", "dfplayer_safe")
            self._advanced_conversion_profile_combo.addItem("Higher quality (advanced)", "high_quality")
            current_profile = self._selected_conversion_profile()
            self._advanced_conversion_profile_combo.setCurrentIndex(
                1 if current_profile == "high_quality" else 0
            )
            self._advanced_conversion_profile_combo.currentIndexChanged.connect(
                self._on_advanced_conversion_profile_changed
            )
            conv_layout.addWidget(self._advanced_conversion_profile_combo)
            sync_layout.addWidget(conv_box)

        sync_layout.addWidget(sync_btn)
        exp_img_btn = QtWidgets.QPushButton("Experimental: SD image sync (clean install)…")
        exp_img_btn.setToolTip(
            "Build a FAT32 disk image from your stations, then write it to a physical SD card "
            "(Windows, Administrator; experimental)."
        )
        exp_img_btn.clicked.connect(self._on_experimental_sd_disk_image)
        sync_layout.addWidget(exp_img_btn)
        sync_layout.addWidget(eject_btn)
        sync_layout.addWidget(self._basic_auto_eject_cb)
        sync_layout.addStretch()
        layout.addWidget(sync_group)

        self._refresh_basic_station_list()
        self._update_basic_stations_size()
        return widget

    # ── Basic-mode SD capacity ──

    def _refresh_basic_sd_capacity(self) -> None:
        """Update the SD capacity bar and label from the current sd_root."""
        bar = getattr(self, "_basic_sd_capacity_bar", None)
        cap_label = getattr(self, "_basic_sd_capacity_label", None)
        if not _qt_widget_alive(bar) or not _qt_widget_alive(cap_label):
            return
        sd_root = self._resolve_sd_root(interactive=False)
        if not sd_root:
            bar.setValue(0)
            cap_label.setText("No SD card selected")
            return
        try:
            usage = shutil.disk_usage(str(sd_root))
            pct = int(usage.used * 100 / usage.total) if usage.total else 0
            bar.setValue(pct)
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
        restore_row = -1
        for idx, station in enumerate(stations):
            track_count = len(self.db.list_basic_station_tracks(station["id"]))
            item = QtWidgets.QListWidgetItem(
                f'{station["name"]}  (Folder {station["folder_number"]:02d}, {track_count} tracks)'
            )
            item.setData(QtCore.Qt.ItemDataRole.UserRole, station["id"])
            self._basic_station_list.addItem(item)
            if preserve_selection and prev_station_id is not None and station["id"] == prev_station_id:
                restore_row = idx
        self._basic_station_list.blockSignals(False)
        if preserve_selection and restore_row >= 0:
            self._basic_station_list.setCurrentRow(restore_row)
        else:
            self._basic_station_list.setCurrentRow(-1)
        self._sync_basic_station_tracks_from_selection()

    def _sync_basic_station_tracks_from_selection(self) -> None:
        """Apply the station list's current row to the detail label and tracks table."""
        if not hasattr(self, "_basic_station_list"):
            return
        cur = self._basic_station_list.currentItem()
        self._on_basic_station_selected(cur, None)

    def _on_basic_station_selected(self, current, _previous) -> None:
        if current is None:
            self._basic_station_detail.setText("Select a station to view tracks.")
            self._basic_station_tracks_table.setRowCount(0)
            return
        station_id = current.data(QtCore.Qt.ItemDataRole.UserRole)
        if station_id is None:
            self._basic_station_detail.setText("Select a station to view tracks.")
            self._basic_station_tracks_table.setRowCount(0)
            return
        station = self.db.get_basic_station(station_id)
        if station is None:
            self._basic_station_detail.setText("Select a station to view tracks.")
            self._basic_station_tracks_table.setRowCount(0)
            return
        track_count = len(self.db.list_basic_station_tracks(station_id))
        max_tracks = self._current_max_tracks_per_station()
        self._basic_station_detail.setText(
            f'Station: {station["name"]}  |  Folder: {station["folder_number"]:02d}'
            f"  |  Tracks: {track_count}/{max_tracks}"
        )
        self._refresh_basic_station_tracks(station_id)

    def _refresh_basic_station_tracks(self, station_id: int) -> None:
        """Reload the tracks table for a given station (including duplicates)."""
        songs = self.db.list_basic_station_songs(station_id)
        table = self._basic_station_tracks_table
        table.setRowCount(len(songs))
        for row_idx, song in enumerate(songs):
            title_item = QtWidgets.QTableWidgetItem(song["title"] or song["original_filename"])
            # Store song id for reorder; store bst_id (track row id) in UserRole+1 for removal
            title_item.setData(QtCore.Qt.ItemDataRole.UserRole, song["id"])
            title_item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, song["bst_id"])
            self._decorate_track_title_item_source_health(title_item, song)
            table.setItem(row_idx, 0, title_item)
            table.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(song["artist"] or ""))
            dur = song["duration"]
            dur_str = f"{int(dur // 60)}:{int(dur % 60):02d}" if dur else ""
            table.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(dur_str))
            table.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(song["format"] or ""))
        table.resizeColumnsToContents()

    def _create_basic_station(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New Station", "Station name:")
        if not ok or not name.strip():
            return
        try:
            folder = self.db.next_basic_station_folder(max_folder=99)
        except ValueError:
            max_station_folders = 99
            QtWidgets.QMessageBox.warning(
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
        name, ok = QtWidgets.QInputDialog.getText(
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
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Station",
            f"Delete station '{item.text().split('  (')[0]}'?\nThis will remove the station and its track list.",
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
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
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Information)
        box.setWindowTitle("Track Count Warning")
        box.setText(
            "This station exceeds 255 tracks. Custom software may support this, "
            "but behavior depends on your target firmware."
        )
        cb = QtWidgets.QCheckBox("Don't show again")
        box.setCheckBox(cb)
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        box.exec()
        if cb.isChecked():
            self.db.set_setting("basic_suppress_track_count_over_255_warning", "1")

    def _add_tracks_to_basic_station(self) -> None:
        """Browse for audio files from file explorer, import to library, and add to selected station."""
        station_id = self._get_selected_basic_station_id()
        if station_id is None:
            QtWidgets.QMessageBox.information(self, "No Station", "Select a station first.")
            return

        current_count = len(self.db.list_basic_station_tracks(station_id))
        max_tracks = self._current_max_tracks_per_station()
        if self._is_track_limit_enforced() and current_count >= max_tracks:
            QtWidgets.QMessageBox.warning(
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
            QtWidgets.QMessageBox.warning(
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

    def _import_files_to_basic_station(self, paths: list) -> None:
        """Handle file drop onto the station tracks table: import and add to current station."""
        station_id = self._get_selected_basic_station_id()
        if station_id is None:
            QtWidgets.QMessageBox.information(self, "No Station", "Select a station first, then drop files.")
            return

        current_count = len(self.db.list_basic_station_tracks(station_id))
        max_tracks = self._current_max_tracks_per_station()
        remaining = max_tracks - current_count
        if self._is_track_limit_enforced() and remaining <= 0:
            QtWidgets.QMessageBox.warning(
                self, "Track Limit",
                f"This station already has {current_count} tracks (max {max_tracks} per folder in this mode).",
            )
            return

        song_ids = self.import_files(paths, silent=True)
        if song_ids:
            if self._is_track_limit_enforced() and len(song_ids) > remaining:
                QtWidgets.QMessageBox.warning(
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

    def _import_folders_as_basic_stations(self, folders: list[Path]) -> None:
        """Create one station per dropped folder and import its files as tracks."""
        if not folders:
            return

        current_stations = len(self.db.list_basic_stations())
        max_station_folders = 99 if self._uses_custom_software() else 98
        free_station_slots = max(0, max_station_folders - current_stations)
        if free_station_slots <= 0:
            QtWidgets.QMessageBox.warning(
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
            QtWidgets.QMessageBox.warning(
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
            QtWidgets.QMessageBox.information(
                self,
                "Stations Imported",
                f"Created {created} station(s) with {imported_tracks} track(s).{detail_text}",
            )

        def on_error(msg):
            self.refresh_library()
            self._refresh_basic_station_list()
            self._update_basic_stations_size()
            QtWidgets.QMessageBox.warning(
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

    def _begin_host_sd_volume_sync_guard(self) -> List[Tuple[Any, bool]]:
        """Pause CDC streaming and USB presence polling while the host writes to SD.

        Keeps the serial port open (no DTR toggle). Required on macOS where concurrent
        ``in_waiting`` polls + mass-storage writes can glitch USB and interrupt firmware.
        """
        self._ensure_device_debug_widget_loaded()
        pairs: List[Tuple[Any, bool]] = []
        for name in ("_basic_debug_widget", "_device_debug_widget"):
            w = getattr(self, name, None)
            if w is not None:
                pairs.append((w, w.begin_host_sd_volume_sync()))
        return pairs

    @staticmethod
    def _end_host_sd_volume_sync_guard(pairs: List[Tuple[Any, bool]]) -> None:
        for w, was in pairs:
            w.end_host_sd_volume_sync(was)

    def _sync_basic_to_sd(self) -> None:
        """Sync basic-mode stations to SD card."""
        sd_root = self._resolve_sd_root()
        if not sd_root:
            QtWidgets.QMessageBox.warning(self, "No SD Card", "Select an SD card first.")
            return

        stations = self.db.list_basic_stations()
        if not stations:
            QtWidgets.QMessageBox.information(self, "No Stations", "Create at least one station with tracks first.")
            return

        if not self._basic_confirm_first_sd_sync_target(str(sd_root)):
            return

        if not self._basic_confirm_different_card(str(sd_root), for_sync=True):
            return

        broken = self.sd_manager.get_basic_broken_source_paths()
        # Re-stat every source path before any sync dialog so fixes outside the app
        # (e.g. file restored in Explorer) clear warning icons even when ``broken`` is now empty.
        self._refresh_library_source_health_ui()
        if broken:
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
            if not self._show_scrollable_broken_paths_dialog(
                window_title="Broken file paths detected",
                headline=headline,
                explanation=explanation,
                entries=broken,
                line_fmt=lambda e: f"{e['title']}  ({e['station']})\n{e['path']}",
                proceed_text="Sync anyway (skip missing tracks)",
                cancel_text="Cancel",
            ):
                self._refresh_library_source_health_ui()
                return

        software_source = self._software_source_for_sync()
        if self._is_advanced_mode() and software_source == "our":
            pico_mode = self._read_pico_install_mode()
            if pico_mode == "basic":
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Reflash Required",
                    "Advanced mode is using our software, but the connected Pico appears to run basic firmware.\n\n"
                    "Reflash now before syncing?",
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.Yes,
                )
                if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                    self._on_setup_advanced_device_clicked()
                    return

        force_clean = False
        sync_choice = QtWidgets.QMessageBox(self)
        sync_choice.setWindowTitle("Sync Stations to SD")
        sync_choice.setText("How do you want to sync stations to the SD card?")
        sync_choice.setInformativeText(
            "Each station is written to its own DFPlayer folder (01, 02, …).\n\n"
            "Normal sync — copies only new or changed files.\n\n"
            "Clean install — quick-formats or wipes the SD card, then writes every track fresh.\n\n"
            "Converted MP3s are saved on this computer (user cache) so later syncs can skip "
            "re-encoding and finish faster. You can delete that cache when choosing clean install "
            "if you want a full re-encode from source files."
        )
        sync_choice.setIcon(QtWidgets.QMessageBox.Icon.Question)
        btn_normal = sync_choice.addButton(
            "Normal sync",
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        btn_clean = sync_choice.addButton(
            "Clean install",
            QtWidgets.QMessageBox.ButtonRole.ActionRole,
        )
        sync_choice.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        sync_choice.setDefaultButton(btn_normal)
        sync_choice.exec()
        clicked = sync_choice.clickedButton()
        if clicked is None:
            return
        if clicked == sync_choice.button(QtWidgets.QMessageBox.StandardButton.Cancel):
            return
        if clicked == btn_clean:
            force_clean = True
            clean_opts = QtWidgets.QMessageBox(self)
            clean_opts.setWindowTitle("Clean install — local cache")
            clean_opts.setIcon(QtWidgets.QMessageBox.Icon.Information)
            clean_opts.setText(
                "For this library, Vintage Radio keeps converted MP3s in your user cache folder "
                "so future syncs can skip re-encoding and run faster."
            )
            clean_opts.setInformativeText(
                "The SD card will still be wiped and every slot rewritten.\n\n"
                "Optionally delete the local cache first so this sync re-encodes everything from "
                "your source files (much slower). Leave unchecked to reuse cached conversions "
                "when possible."
            )
            cb_delete_cache = QtWidgets.QCheckBox(
                "Delete local converted MP3 cache before syncing (full re-encode)"
            )
            clean_opts.setCheckBox(cb_delete_cache)
            btn_continue = clean_opts.addButton(
                "Continue",
                QtWidgets.QMessageBox.ButtonRole.AcceptRole,
            )
            clean_opts.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
            clean_opts.setDefaultButton(btn_continue)
            clean_opts.exec()
            if clean_opts.clickedButton() != btn_continue:
                return
            if cb_delete_cache.isChecked():
                ok_del, err_del = self.sd_manager.clear_basic_sync_mp3_cache_for_library()
                if not ok_del:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Could not delete conversion cache",
                        f"The cache folder could not be removed:\n\n{err_del}\n\n"
                        "Sync will continue; existing cache files may still be reused.",
                    )

        sd_vol_guard = self._begin_host_sd_volume_sync_guard()
        try:
            dlg = TaskProgressDialog(
                parent=self,
                title="Sync Stations to SD" + (" (clean)" if force_clean else ""),
                func=self.sd_manager.sync_library_basic,
                args=(sd_root,),
                kwargs={
                    "force_clean": force_clean,
                    "conversion_profile": self._selected_conversion_profile(),
                    "dfplayer_eq": self._selected_dfplayer_eq() if software_source == "our" else "normal",
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
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Some files failed to convert",
                        "These library files could not be converted to MP3 and were not copied "
                        "to the SD card. Fix or remove the bad files and sync again.\n\n"
                        + "\n\n".join(detail_lines)
                        + tail,
                    )
                else:
                    QtWidgets.QMessageBox.information(
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
                        rename_label = preserved if preserved else None
                        if self.sd_manager.set_sync_target_volume_label(
                            Path(self.sd_root), label=rename_label
                        ):
                            effective = preserved if preserved else SYNC_TARGET_VOLUME_LABEL
                            self.db.set_setting("sd_volume_label", effective)
                            if preserved:
                                self.sd_label = preserved
                                self.db.set_setting("sd_label", preserved)
                            # macOS diskutil rename changes the mount path
                            if sys.platform == "darwin" and not Path(self.sd_root).is_dir():
                                new_path = Path("/Volumes") / effective
                                if new_path.is_dir():
                                    self.sd_root = str(new_path)
                                    self.db.set_setting("sd_root", self.sd_root)
                        tag = self._basic_sd_path_volume_tag(self.sd_root)
                        if tag:
                            self.db.set_setting("basic_trusted_sd_volume", tag)
                    except Exception:
                        pass
                self._update_sd_root_label()
                self._refresh_basic_sd_capacity()
                self._check_basic_sd_sync()
                if self.db.get_setting("auto_eject_after_sync", "0") == "1" and self.sd_root:
                    QtCore.QTimer.singleShot(1500, lambda: self.safely_remove_sd(auto=True, attempt=1))

            def on_error(msg):
                if "Sync cancelled by user" in str(msg):
                    self.statusBar().showMessage("Basic sync cancelled.", 4000)
                    return
                QtWidgets.QMessageBox.critical(
                    self,
                    "Sync Error",
                    f"Error during basic sync:\n\n{msg}",
                )

            dlg.on_success = on_success
            dlg.on_error = on_error
            dlg.exec()
        finally:
            self._end_host_sd_volume_sync_guard(sd_vol_guard)

    def _on_experimental_sd_disk_image(self) -> None:
        """Experimental: clean sync via FAT32 image — build image, then write to physical SD."""
        if not self._is_basic_like_mode():
            return
        sd_root = self._resolve_sd_root()
        if not sd_root or not Path(sd_root).is_dir():
            QtWidgets.QMessageBox.warning(
                self,
                "No SD folder",
                "Select an SD card mount point or folder to use as the sync target.",
            )
            return
        stations = self.db.list_basic_stations()
        if not stations:
            QtWidgets.QMessageBox.information(
                self,
                "No stations",
                "Create at least one station with tracks before building an SD image.",
            )
            return

        missing_pyfatfs = pyfatfs_dependency_message()
        if missing_pyfatfs:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing dependency",
                missing_pyfatfs,
            )
            return

        sd_p = Path(sd_root)

        if platform.system() not in ("Windows", "Darwin"):
            intro = QtWidgets.QMessageBox(self)
            intro.setWindowTitle("Experimental: SD disk image (export only)")
            intro.setIcon(QtWidgets.QMessageBox.Icon.Information)
            intro.setText(
                "Raw disk flashing from this app is only implemented on Windows and macOS.\n\n"
                "You can still save a FAT32 .img built with pyfatfs and flash it with Etcher, "
                "Pi Imager, or dd on this platform."
            )
            intro.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel
            )
            if intro.exec() != QtWidgets.QMessageBox.StandardButton.Ok:
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
                QtWidgets.QMessageBox.information(
                    self,
                    "Disk image",
                    f"Image saved to:\n{out_p}\n\nFlash it with your preferred tool, then eject safely.",
                )

            dlg.on_success = on_ok_export
            dlg.on_error = lambda msg: QtWidgets.QMessageBox.critical(
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

        prepare_on_pc = wiz.prepare_on_pc
        flash_last = wiz.flash_last_image_only
        last_img = app_data_dir() / "sd_image_cache" / LAST_CACHED_SD_IMAGE_FILENAME

        if flash_last:
            try:
                if not last_img.is_file() or last_img.stat().st_size <= 0:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "No cached image",
                        f"No reusable disk image at:\n{last_img}\n\n"
                        "Run a full SD image sync once to build it.",
                    )
                    return
            except OSError:
                QtWidgets.QMessageBox.warning(
                    self,
                    "No cached image",
                    f"Could not read cached image:\n{last_img}",
                )
                return
            ds = _selected_disk_size_bytes()
            _cached_sz = last_img.stat().st_size
            if ds is not None and _cached_sz > ds:
                _overage = _cached_sz - ds
                _tolerance = max(256 * 1024 * 1024, int(ds * 0.02))
                if _overage > _tolerance:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "SD card too small",
                        f"The cached image is about {format_disk_size(_cached_sz)}, but the "
                        f"selected disk is {format_disk_size(ds)}. The difference "
                        f"({format_disk_size(_overage)}) is too large to trim safely. "
                        "Use a larger card, or uncheck 'Flash cached image only' to rebuild.",
                    )
                    return
                # Small overage (≤ 256 MiB / 2%) — same-nominal-size card with slightly
                # different actual capacity.  The write will be capped at the disk boundary;
                # the last few MB of empty FAT32 space will not be written (safe for DFPlayer).
            if ds is not None and _cached_sz < ds:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Rebuild required — card size changed",
                    f"The cached image ({format_disk_size(_cached_sz)}) is smaller than "
                    f"the selected card ({format_disk_size(ds)}).\n\n"
                    "The SD card would not show its full capacity after flashing, "
                    "preventing normal syncs from using the remaining space.\n\n"
                    "Uncheck 'Flash cached image only' to rebuild the image for this card size.",
                )
                return
        else:
            ds = _selected_disk_size_bytes()
            if not prepare_on_pc:
                est = suggest_image_size_bytes(sd_p)
                if ds is not None and est > ds:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "SD card too small",
                        f"This library needs about {format_disk_size(est)} for the image, but the selected "
                        f"disk is {format_disk_size(ds)}. Use a larger card or reduce stations/tracks.",
                    )
                    return

        if use_darwin and bsd_disk:
            target_label = f"whole disk {bsd_disk} (raw /dev/r{bsd_disk})"
        else:
            target_label = f"PhysicalDrive{disk_number}"
        confirm_lines = [
            f"Write a fresh FAT32 image to {target_label}?",
            "",
            f"{'Disk size: ' + format_disk_size(ds) if ds else 'Size: unknown'}",
            "",
            "ALL DATA on that physical disk will be permanently erased.",
        ]
        if use_darwin:
            euid = os.geteuid() if hasattr(os, "geteuid") else 0
            if euid != 0:
                confirm_lines.extend(
                    [
                        "",
                        "After the image is built, macOS will ask for your password or Touch ID to allow "
                        "writing to the raw SD device.",
                    ]
                )
        elif not is_windows_admin():
            confirm_lines.extend(
                [
                    "",
                    "After the image is built, Windows will show a security prompt (UAC) to allow "
                    "writing to the card. Approve it to continue. You do not need to restart this "
                    "app as Administrator.",
                ]
            )
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm disk erase",
            "\n".join(confirm_lines),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        software_source = self._software_source_for_sync()
        dfplayer_eq = self._selected_dfplayer_eq() if software_source == "our" else "normal"
        conv_profile = self._selected_conversion_profile()

        def _worker_sd_image(
            *,
            progress_callback: Optional[Callable] = None,
            should_cancel: Optional[Callable[[], bool]] = None,
        ) -> dict:
            cache_dir = app_data_dir() / "sd_image_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            staging_root = cache_dir / "staging"
            used_staging = False
            img_path = cache_dir / LAST_CACHED_SD_IMAGE_FILENAME

            def _export_cb(_c: int, _t: int, m: str) -> None:
                if progress_callback:
                    if _t > 0:
                        progress_callback(_c, _t, f"Image: {m}")
                    else:
                        progress_callback(0, 0, f"Image: {m}")

            try:
                if flash_last:
                    if progress_callback:
                        progress_callback(
                            0,
                            0,
                            "Using cached disk image (skipping prepare and build)…",
                        )
                    if not img_path.is_file() or img_path.stat().st_size <= 0:
                        raise RuntimeError(f"Missing cached image: {img_path}")
                    if use_darwin:
                        assert bsd_disk is not None
                        ok2, err2 = write_image_to_physical_disk_darwin(
                            img_path,
                            bsd_disk,
                            progress_callback=progress_callback,
                            should_cancel=should_cancel,
                        )
                    else:
                        assert disk_number is not None
                        ok2, err2 = write_image_to_physical_disk(
                            img_path,
                            disk_number,
                            progress_callback=progress_callback,
                            should_cancel=should_cancel,
                        )
                    if not ok2:
                        raise RuntimeError(err2 or "Disk write failed.")
                    return {"ok": True}

                if prepare_on_pc:
                    used_staging = True
                    if progress_callback:
                        progress_callback(
                            0,
                            0,
                            "Preparing DFPlayer layout on your PC (not writing files to the SD card)...",
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
                    )
                    est2 = suggest_image_size_bytes(staging_root)
                    _disk_bytes = _selected_disk_size_bytes()
                    if _disk_bytes is not None and est2 > _disk_bytes:
                        raise RuntimeError(
                            f"SD card too small: need about {format_disk_size(est2)} for this image, "
                            f"but the selected disk is {format_disk_size(_disk_bytes)}."
                        )
                    source_root = staging_root
                else:
                    _disk_bytes = _selected_disk_size_bytes()
                    source_root = sd_p

                disk_size_label = (
                    format_disk_size(_disk_bytes) if _disk_bytes else "unknown size"
                )
                if progress_callback:
                    progress_callback(
                        0,
                        0,
                        f"Building FAT32 disk image ({disk_size_label} — full card capacity)...",
                    )
                ok, err = run_experimental_sd_disk_image_export(
                    source_root,
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
                    raise RuntimeError(err or "Disk image build failed.")

                if use_darwin:
                    assert bsd_disk is not None
                    ok2, err2 = write_image_to_physical_disk_darwin(
                        img_path,
                        bsd_disk,
                        progress_callback=progress_callback,
                        should_cancel=should_cancel,
                    )
                else:
                    assert disk_number is not None
                    ok2, err2 = write_image_to_physical_disk(
                        img_path,
                        disk_number,
                        progress_callback=progress_callback,
                        should_cancel=should_cancel,
                    )
                if not ok2:
                    raise RuntimeError(err2 or "Disk write failed.")
                return {"ok": True}
            finally:
                if used_staging:
                    shutil.rmtree(staging_root, ignore_errors=True)

        dlg = TaskProgressDialog(
            parent=self,
            title="SD image sync (experimental)",
            func=_worker_sd_image,
            args=(),
            kwargs={},
            cancelable=True,
            cancel_callback_kwarg="should_cancel",
        )

        def on_ok_sd(_result: object) -> None:
            self.statusBar().showMessage("SD card image written. Safely remove the card if needed.", 8000)
            QtWidgets.QMessageBox.information(
                self,
                "Done",
                "The FAT32 image was written to the selected disk.\n\n"
                "Safely remove the SD card, insert it in the radio, and power on.",
            )

        def on_error_sd(msg: str) -> None:
            if use_darwin and DARWIN_FDA_REQUIRED_MARKER in msg:
                display_msg = msg.replace(DARWIN_FDA_REQUIRED_MARKER + "\n", "")
                dlg_fda = QtWidgets.QMessageBox(self)
                dlg_fda.setWindowTitle("Full Disk Access Required")
                dlg_fda.setText(display_msg)
                dlg_fda.setIcon(QtWidgets.QMessageBox.Icon.Warning)
                open_btn = dlg_fda.addButton(
                    "Open System Settings", QtWidgets.QMessageBox.ButtonRole.ActionRole
                )
                dlg_fda.addButton(QtWidgets.QMessageBox.StandardButton.Ok)
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
            else:
                QtWidgets.QMessageBox.critical(self, "SD image sync failed", msg)

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

        # Basic mode: SD Card tab (index 1) — full refresh + wait cursor only on first visit
        # per session (reset on library switch / tab rebuild). Later visits skip to avoid
        # re-scanning the whole library on every tab click.
        if self._is_basic_like_mode() and index == 1:
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
        install_mp_btn = QtWidgets.QPushButton("Install MicroPython on Pico...")
        install_mp_btn.setToolTip("One-time setup: put the Pico in BOOTSEL mode, then copy the MicroPython .uf2 to it. After this you can use Install to Pico.")
        install_mp_btn.clicked.connect(self._show_install_micropython_dialog)
        rp2040_layout.addWidget(export_rp2040_btn)
        rp2040_layout.addWidget(install_pico_btn)
        rp2040_layout.addWidget(install_mp_btn)
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

    @staticmethod
    def _song_source_path_missing(song: Any) -> bool:
        """True when the library has no usable path or the file is not on disk."""
        try:
            fp = (song["file_path"] or "").strip()
        except (TypeError, KeyError, IndexError):
            return True
        if not fp:
            return True
        try:
            return not Path(fp).is_file()
        except OSError:
            return True

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
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(window_title)
        dlg.resize(560, 420)
        layout = QtWidgets.QVBoxLayout(dlg)
        head_lbl = QtWidgets.QLabel(headline)
        head_lbl.setWordWrap(True)
        layout.addWidget(head_lbl)
        intro_lbl = QtWidgets.QLabel(explanation)
        intro_lbl.setWordWrap(True)
        layout.addWidget(intro_lbl)
        body = QtWidgets.QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText("\n\n".join(line_fmt(e) for e in entries))
        body.setMinimumHeight(200)
        body.setMaximumHeight(320)
        mono = QtGui.QFont("Consolas") if sys.platform == "win32" else QtGui.QFontDatabase.systemFont(
            QtGui.QFontDatabase.SystemFont.FixedFont
        )
        body.setFont(mono)
        layout.addWidget(body, 1)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        accepted = {"ok": False}
        if proceed_text:
            btn_proceed = QtWidgets.QPushButton(proceed_text)
            btn_proceed.setDefault(True)
            btn_cancel = QtWidgets.QPushButton(cancel_text)

            def _do_proceed() -> None:
                accepted["ok"] = True
                dlg.accept()

            def _do_cancel() -> None:
                accepted["ok"] = False
                dlg.reject()

            btn_proceed.clicked.connect(_do_proceed)
            btn_cancel.clicked.connect(_do_cancel)
            btn_row.addWidget(btn_proceed)
            btn_row.addWidget(btn_cancel)
        else:
            btn_ok = QtWidgets.QPushButton("OK")
            btn_ok.setDefault(True)

            def _do_ok() -> None:
                accepted["ok"] = True
                dlg.accept()

            btn_ok.clicked.connect(_do_ok)
            btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)
        dlg.exec()
        return bool(accepted["ok"])

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
            QtWidgets.QMessageBox.warning(
                self, "Could not read file", str(e) or "Unknown error reading audio file."
            )
            return
        new_path = metadata["file_path"]
        conflict = self.db.get_song_by_path(new_path)
        if conflict is not None and int(conflict["id"]) != song_id:
            t = conflict["title"] or conflict["original_filename"] or new_path
            QtWidgets.QMessageBox.warning(
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
            self.statusBar().showMessage(
                f"Import complete. Added: {added}, Skipped: {skipped}", 5000
            )

        def on_error(msg):
            self.refresh_library()
            QtWidgets.QMessageBox.warning(self, "Import Error", f"Error during import:\n\n{msg}")

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
            QtWidgets.QMessageBox.warning(
                self, "Import Error", f"Error during import:\n\n{errors[0]}"
            )
            return []
        if not results:
            return []
        _added, _skipped, added_ids = results[0]
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
                f"Import complete. Added: {added}, skipped: {skipped}", 5000
            )
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
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Remove Songs",
            f"Remove {len(song_ids)} song(s) from the library? Files stay on disk.",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
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
        name, ok = QtWidgets.QInputDialog.getText(self, "New Album", "Album name:")
        if not ok or not name.strip():
            return
        self.db.create_album(name.strip())
        self.refresh_albums()

    def delete_album(self) -> None:
        item = self.album_list.currentItem()
        if item is None:
            return
        album_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        confirm = QtWidgets.QMessageBox.question(
            self, "Delete Album", f"Delete album '{item.text()}'?"
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.db.delete_album(album_id)
        self.refresh_albums()
        self.album_songs_table.setRowCount(0)

    def rename_album(self) -> None:
        item = self.album_list.currentItem()
        if item is None:
            return
        album_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        name, ok = QtWidgets.QInputDialog.getText(
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
        text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self, "Album Description", "Description:", existing_text
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
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Remove Tracks",
            f"Remove {len(song_ids)} track(s) from this album?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
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
        name, ok = QtWidgets.QInputDialog.getText(self, "New Playlist", "Playlist name:")
        if not ok or not name.strip():
            return
        self.db.create_playlist(name.strip())
        self.refresh_playlists()

    def delete_playlist(self) -> None:
        item = self.playlist_list.currentItem()
        if item is None:
            return
        playlist_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        confirm = QtWidgets.QMessageBox.question(
            self, "Delete Playlist", f"Delete playlist '{item.text()}'?"
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.db.delete_playlist(playlist_id)
        self.refresh_playlists()
        self.playlist_songs_table.setRowCount(0)

    def rename_playlist(self) -> None:
        item = self.playlist_list.currentItem()
        if item is None:
            return
        playlist_id = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        name, ok = QtWidgets.QInputDialog.getText(
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
        text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self, "Playlist Description", "Description:", existing_text
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
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Remove Tracks",
            f"Remove {len(song_ids)} track(s) from this playlist?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
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
        dialog = SettingsDialog(
            auto_backup=self.db.auto_backup,
            backup_retention=self.db.backup_retention,
            sd_root=self.sd_root,
            sd_auto_detect=self.sd_auto_detect,
            parent=self,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        auto_backup, retention, sd_root, sd_auto_detect = dialog.get_values()
        self.db.set_setting("auto_backup", "1" if auto_backup else "0")
        self.db.set_setting("backup_retention", str(retention))
        self.db.set_setting("sd_root", sd_root)
        self.db.set_setting("sd_auto_detect", "1" if sd_auto_detect else "0")
        self.db.auto_backup = auto_backup
        self.db.backup_retention = retention
        self.sd_root = sd_root
        self.sd_auto_detect = sd_auto_detect
        if self.sd_root:
            self.sd_label = self._get_volume_label(Path(self.sd_root))
            self.db.set_setting("sd_label", self.sd_label)
        self._update_sd_root_label()

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

    def _manual_select_sd_root_dialog(
        self,
        candidates: List[Tuple[Path, str]],
        identity: set,
    ) -> Optional[Tuple[str, str]]:
        """Basic-mode **Select**: combo dropdown of detected roots (one or many). Cancel returns ``None``."""
        choices: List[str] = []
        mapping: Dict[str, str] = {}
        for path, label in candidates:
            display = f"{path} ({label})" if label else str(path)
            choices.append(display)
            mapping[display] = str(path)

        default_idx = 0
        if self.sd_root:
            try:
                saved = Path(self.sd_root).expanduser().resolve()
                for i, (path, _label) in enumerate(candidates):
                    try:
                        if path.resolve() == saved:
                            default_idx = i
                            break
                    except OSError:
                        continue
            except OSError:
                pass
        if default_idx == 0 and identity:
            for i, (path, label) in enumerate(candidates):
                if self._basic_candidate_matches_identity(path, label, identity):
                    default_idx = i
                    break

        dlg_flags = (
            QtCore.Qt.WindowType.Dialog
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.WindowCloseButtonHint
        )
        selection, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Select SD Root",
            "Choose SD card root:",
            choices,
            default_idx,
            False,
            dlg_flags,
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

    def select_sd_root(self, *, manual: bool = False) -> None:
        """Pick SD root from detected removable volumes (dropdown if several).

        When *manual* is False (e.g. advanced Devices "Detect"), we may apply the saved
        path or a single identity match without opening a dialog.

        When *manual* is True (basic-mode **Select**), show the combo dropdown of detected
        drives (same control whether there is one or many; stays on top so it is not hidden).
        """
        candidates = self.sd_manager.detect_sd_roots()
        if not candidates:
            mb = QtWidgets.QMessageBox(self)
            mb.setIcon(QtWidgets.QMessageBox.Icon.Information)
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
            choices: List[str] = []
            mapping: Dict[str, str] = {}
            for path, label in candidates:
                display = f"{path} ({label})" if label else str(path)
                choices.append(display)
                mapping[display] = str(path)

            default_idx = 0
            if self.sd_root:
                try:
                    saved = Path(self.sd_root).expanduser().resolve()
                    for i, (path, label) in enumerate(candidates):
                        try:
                            if path.resolve() == saved:
                                default_idx = i
                                break
                        except OSError:
                            continue
                except OSError:
                    pass
            if default_idx == 0 and identity:
                for i, (path, label) in enumerate(candidates):
                    if self._basic_candidate_matches_identity(path, label, identity):
                        default_idx = i
                        break

            dlg_flags = (
                QtCore.Qt.WindowType.Dialog
                | QtCore.Qt.WindowType.WindowStaysOnTopHint
                | QtCore.Qt.WindowType.WindowCloseButtonHint
            )
            selection, ok = QtWidgets.QInputDialog.getItem(
                self,
                "Select SD Root",
                "Choose SD card root:",
                choices,
                default_idx,
                False,
                dlg_flags,
            )
            if not ok or not selection:
                return
            new_root = mapping.get(selection, selection)
            new_label = ""
            for path, label in candidates:
                if str(path) == new_root:
                    new_label = label or ""
                    break
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
            reply = QtWidgets.QMessageBox.question(
                self,
                "Recover from SD card",
                f"{len(recoverable_from_sd)} song(s) have missing source files on this PC, "
                f"but copies already exist on the SD card:\n\n{names}{more}\n\n"
                "Link library to the SD card copies so they can be synced in the future?\n"
                "(This updates the library paths to point to the SD card.)",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.Yes,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
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
                QtWidgets.QMessageBox.critical(
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
                reply = QtWidgets.QMessageBox.warning(
                    self,
                    "Missing Source Files",
                    f"{n_missing} of {total} song(s) have missing source files and will NOT be copied:\n\n"
                    f"{names}{more}\n\n"
                    "Continue syncing the remaining songs?\n\n"
                    "(Fix missing songs: Library → Remove broken entries, then re-import from this PC.)",
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.Cancel,
                    QtWidgets.QMessageBox.StandardButton.Yes,
                )
                if reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                    return

        # ── Ask for normal vs clean sync ──
        force_clean = False
        reply = QtWidgets.QMessageBox.question(
            self,
            "SD Card Sync",
            "Sync library to SD card?\n\n"
            "Files that already exist and match will be skipped.\n\n"
            "Click 'Yes' for normal sync (skips existing files).\n"
            "Click 'No' for clean install (re-syncs all files).",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Cancel:
            return
        if reply == QtWidgets.QMessageBox.StandardButton.No:
            force_clean = True

        effective_audio_target = "dfplayer_rp2040" if self._is_basic_like_mode() else self.audio_target
        sd_vol_guard = self._begin_host_sd_volume_sync_guard()
        try:
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
                    QtWidgets.QMessageBox.warning(
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
                    # Mark this SD as our sync target (set volume label so we recognize it when multiple cards are present)
                    if self.sd_root:
                        try:
                            if self.sd_manager.set_sync_target_volume_label(Path(self.sd_root)):
                                self.db.set_setting("sd_volume_label", SYNC_TARGET_VOLUME_LABEL)
                                if sys.platform == "darwin" and not Path(self.sd_root).is_dir():
                                    new_path = Path("/Volumes") / SYNC_TARGET_VOLUME_LABEL
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
                QtWidgets.QMessageBox.critical(self, "Sync Error", f"An error occurred during SD sync:\n\n{msg}")

            dlg.on_success = on_success
            dlg.on_error = on_error
            dlg.exec()
        finally:
            self._end_host_sd_volume_sync_guard(sd_vol_guard)

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
                QtWidgets.QMessageBox.warning(
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
                QtWidgets.QMessageBox.information(self, "SD Card Ejected", msg)

        def _report_failure(title: str, msg: str) -> None:
            if auto and attempt < 3:
                delay_ms = 1200 * attempt
                QtCore.QTimer.singleShot(delay_ms, lambda: self.safely_remove_sd(auto=True, attempt=attempt + 1))
                return
            if auto:
                self.statusBar().showMessage(f"Auto-eject failed: {msg}", 8000)
            else:
                QtWidgets.QMessageBox.warning(self, title, msg)

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
            QtWidgets.QMessageBox.information(self, "Install Firmware", msg)
            return
        root = self._project_root()
        if not (root / "firmware" / "pico" / "main.py").exists() or not (root / "firmware" / "radio_core.py").exists():
            QtWidgets.QMessageBox.warning(self, "Install Firmware", "Project files not found.")
            return
        if not (root / "firmware" / "pico" / "dfplayer_hardware.py").exists():
            QtWidgets.QMessageBox.warning(self, "Install Firmware", "firmware/pico/dfplayer_hardware.py not found.")
            return

        # Quick test: can we connect to Pico (MicroPython already installed)?
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

        # No connection: check for Pico in BOOTSEL (RPI-RP2 drive) -- Pico-only
        print(f"[Setup Device] All connection attempts failed. Output:\n{conn_err}")
        if is_pico and self._is_rpi_rp2_present():
            dlg = InstallMicroPythonDialog(self, preselect_rpi_rp2=True)
            dlg.exec()
            self.statusBar().showMessage("MicroPython installed. Installing app...", 8000)
            QtCore.QTimer.singleShot(_POST_MICROPYTHON_INSTALL_DELAY_MS, self._install_to_pico_after_firmware)
        else:
            board_name = bp.name if bp else "device"
            msg = (
                f"No {board_name} detected. Connect the device via USB.\n\n"
                "Ensure MicroPython is installed on the device."
            )
            if is_pico:
                msg += "\nIf it's new, hold BOOTSEL while plugging in to install MicroPython first."
            if conn_err and len(conn_err) < 500:
                msg += f"\n\nConnection attempt output:\n{conn_err.strip()}"
            elif conn_err:
                msg += f"\n\nConnection attempt output:\n{conn_err[:500].strip()}..."
            QtWidgets.QMessageBox.information(self, "Install Firmware", msg)

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
                mpremote_cmd, args, cwd=_mpremote_cwd, capture_output=True, text=True,
                timeout=timeout_sec, creationflags=creation_flags, env=env,
            )

        def run_mpremote_with_retry(args: List[str], timeout_sec: int = 30):
            """Run mpremote; retry on 'no device found' while USB serial is still enumerating after flash/reboot."""
            import time

            r = run_mpremote(args, timeout_sec=timeout_sec)
            for attempt in range(5):
                if r.returncode == 0:
                    return r
                err = (r.stderr or "") + (r.stdout or "")
                if "no device found" not in err.lower():
                    return r
                time.sleep(min(8.0, 2.0 + attempt * 2.0))
                r = run_mpremote(args, timeout_sec=timeout_sec)
            return r

        if after_firmware:
            if not _wait_mpremote_serial_ready(
                mpremote_cmd,
                _mpremote_cwd,
                progress_callback=progress_callback,
                total_steps=total,
                creationflags=creation_flags,
                env=env,
            ):
                raise RuntimeError(
                    "Timed out waiting for the Pico on USB serial after installing MicroPython.\n\n"
                    "When the new COM port appears, run Setup Device again."
                )

        # ── Create directories (batched: one mpremote call) ──
        _report("Creating directories on Pico...")
        try:
            run_mpremote_with_retry(
                ["exec", "import os; os.mkdir('components'); os.mkdir('VintageRadio')"],
                timeout_sec=15,
            )
        except Exception:
            pass  # directories may already exist

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
                raise RuntimeError(
                    "Failed to copy firmware files.\n\n"
                    "Ensure the Pico is connected via USB and running MicroPython.\n\n"
                    f"{r.stderr or r.stdout or ''}"
                )

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
            QtWidgets.QMessageBox.information(self, "Install to Pico", msg)
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
            QtWidgets.QMessageBox.warning(self, "Install to Pico", f"{main_source} not found.")
            return
        if not (root / "firmware" / "radio_core.py").exists():
            QtWidgets.QMessageBox.warning(self, "Install to Pico", "Project files not found.")
            return
        if not (root / "firmware" / "pico" / "dfplayer_hardware.py").exists():
            QtWidgets.QMessageBox.warning(self, "Install to Pico", "firmware/pico/dfplayer_hardware.py not found.")
            return

        profile_params = self._get_active_profile_install_params()
        profile_params["basic_mode"] = basic_mode
        profile_params["install_mode"] = install_mode
        profile_params["dfplayer_eq"] = dfplayer_eq
        profile_params["after_firmware"] = after_firmware
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

        if not _wait_mpremote_serial_ready(
            mpremote_cmd,
            _mpremote_cwd,
            progress_callback=progress_callback,
            total_steps=total,
            creationflags=creationflags,
            env=env,
        ):
            raise RuntimeError(
                "Timed out waiting for the Pico on USB serial (mpremote could not open a session).\n\n"
                "After installing MicroPython the board disconnects and comes back as a COM port; "
                "that can take 10–30 seconds on some PCs.\n\n"
                "Unplug/replug the Pico if nothing happens, close other apps using the COM port, "
                "then try Setup Device again."
            )

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
            QtWidgets.QMessageBox.warning(
                self,
                "Custom Software",
                "Choose a valid local custom software folder or file first.",
            )
            return
        mpremote_cmd = self._resolve_mpremote_cmd()
        if not mpremote_cmd:
            QtWidgets.QMessageBox.information(
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
        ip, ok = QtWidgets.QInputDialog.getText(
            self,
            "Deploy to Pi",
            "Enter Raspberry Pi IP address:",
            QtWidgets.QLineEdit.EchoMode.Normal,
            "",
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
        progress = QtWidgets.QProgressDialog("Deploying to Pi...", None, 0, 0, self)
        progress.setWindowTitle("Deploy to Pi")
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QtWidgets.QApplication.processEvents()
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
                QtWidgets.QMessageBox.warning(
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
            QtWidgets.QMessageBox.warning(self, "Deploy to Pi", "Timed out. Check Pi IP and SSH.")
        except FileNotFoundError:
            progress.close()
            QtWidgets.QMessageBox.warning(
                self,
                "Deploy to Pi",
                "scp/ssh not found. On Windows enable OpenSSH client (Settings > Apps > Optional features).",
            )
        except Exception as e:
            progress.close()
            QtWidgets.QMessageBox.warning(self, "Deploy to Pi", f"Error: {e}")

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
        progress = QtWidgets.QProgressDialog(
            "Exporting SD contents...", "Cancel", 0, 0, self
        )
        progress.setWindowTitle("Export SD Contents")
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QtWidgets.QApplication.processEvents()
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
            QtWidgets.QMessageBox.critical(
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
            if sv:
                label_matches.add(SYNC_TARGET_VOLUME_LABEL.strip().upper())
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
                choices = []
                mapping = {}
                for path, label in candidates:
                    display = f"{path} ({label})" if label else str(path)
                    choices.append(display)
                    mapping[display] = str(path)
                _sd_pick_flags = (
                    QtCore.Qt.WindowType.Dialog
                    | QtCore.Qt.WindowType.WindowStaysOnTopHint
                    | QtCore.Qt.WindowType.WindowCloseButtonHint
                )
                selection, ok = QtWidgets.QInputDialog.getItem(
                    self,
                    "Select SD Root",
                    "Choose SD card root:",
                    choices,
                    0,
                    False,
                    _sd_pick_flags,
                )
                if ok and selection:
                    self.sd_root = mapping.get(selection, selection)
                    self.db.set_setting("sd_root", self.sd_root)
                    self.sd_label = ""
                    for path, label in candidates:
                        if str(path) == self.sd_root:
                            self.sd_label = label
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
        """Open the current session log in the system's default text editor."""
        from .session_log import get_session_log_path
        log_path = get_session_log_path()
        if log_path and log_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))
        else:
            QtWidgets.QMessageBox.information(
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
            QtWidgets.QMessageBox.information(
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
                QtWidgets.QMessageBox.information(
                    self,
                    "Check for Updates",
                    "An update check is already in progress.",
                )
            return

        self._update_check_in_flight = True

        def _worker() -> None:
            try:
                info = updater.check_latest_release(
                    user_agent=f"VintageRadio/{__version__}",
                    current_version=__version__,
                )
                self.update_check_finished.emit(info, manual, "")
            except Exception as e:
                self.update_check_finished.emit(None, manual, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_check_finished(self, info: object, manual: bool, error: str) -> None:
        self._update_check_in_flight = False

        if error:
            if manual:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Check for Updates",
                    f"Could not check for updates:\n{error}",
                )
            return

        release = info if isinstance(info, updater.ReleaseInfo) else None
        if release is None:
            if manual:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Check for Updates",
                    "Could not fetch release information from GitHub.\n\n"
                    "If your connection is fine, the API may be rate-limited or "
                    "temporarily unavailable. You can open the releases page manually:\n"
                    f"{updater.GITHUB_RELEASES_URL}",
                )
            return

        if updater.is_newer(release.advertised_version(), __version__):
            self._show_update_dialog(release)
            return

        if manual:
            QtWidgets.QMessageBox.information(
                self,
                "Check for Updates",
                f"You're up to date.\nCurrent version: {__version__}",
            )

    def _show_update_dialog(self, release: updater.ReleaseInfo) -> None:
        dlg = UpdateAvailableDialog(release, __version__, self)
        dlg.exec()

    def _show_about(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "About Vintage Radio",
            "Vintage Radio Music Manager\n"
            f"Version: {__version__}\n\n"
            f"Releases: {updater.GITHUB_RELEASES_URL}",
        )

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

    app = QtWidgets.QApplication(sys.argv)
    try:
        app.setStyle(_VintageRadioTooltipStyle(app.style()))
    except Exception:
        pass

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
            QtWidgets.QMessageBox.information(
                None,
                "Conversion tools not found",
                "No audio conversion tools were detected on your system.\n\n"
                "To enable conversion (recommended), install VLC or ffmpeg + pydub.\n\n"
                f"Hints:\n{hint}",
            )
    except Exception:
        # If diagnostic fails, ignore silently — normal app functionality is unaffected.
        pass

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_app()


