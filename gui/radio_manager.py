"""Main GUI application for Vintage Radio Music Manager."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QIcon

from .audio_metadata import compute_file_hash, extract_metadata
from .database import DatabaseManager
from .device_debug import DeviceDebugWidget
from .library_manager import LibraryRegistry
from .resource_paths import app_data_dir, project_root, resource_path
from .sd_manager import SDManager, SYNC_TARGET_VOLUME_LABEL
from .test_mode import TestModeWidget
from . import sd_manager as sd_manager_module


# ───────────────────────────────────────────────────────────
#  Background worker for long-running tasks
# ───────────────────────────────────────────────────────────

class _BackgroundWorker(QtCore.QObject):
    """Runs a callable in a QThread and emits signals for progress / completion."""
    progress = QtCore.pyqtSignal(int, int, str)   # current, total, message
    finished = QtCore.pyqtSignal(object)           # result (any Python object)
    error = QtCore.pyqtSignal(str)                 # error message

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    @QtCore.pyqtSlot()
    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(f"{exc}\n\n{traceback.format_exc()}")


class TaskProgressDialog(QtWidgets.QDialog):
    """
    A non-blocking progress dialog that runs *func* in a background thread.

    Usage::

        dlg = TaskProgressDialog(
            parent=self,
            title="SD Card Sync",
            func=self.sd_manager.sync_library,
            args=(sd_root,),
            kwargs={"force_clean": True, "progress_callback": dlg.report_progress},
        )
        dlg.on_success = lambda result: print("done", result)
        dlg.exec()
    """

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        title: str,
        func: Callable,
        args: tuple = (),
        kwargs: dict | None = None,
        cancelable: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)

        # --- UI ---
        layout = QtWidgets.QVBoxLayout(self)
        self._status_label = QtWidgets.QLabel("Starting...")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate initially
        layout.addWidget(self._progress_bar)

        self._detail_label = QtWidgets.QLabel("")
        self._detail_label.setStyleSheet("color: gray; font-size: 11px;")
        self._detail_label.setWordWrap(True)
        layout.addWidget(self._detail_label)

        if cancelable:
            btn_layout = QtWidgets.QHBoxLayout()
            btn_layout.addStretch()
            self._cancel_btn = QtWidgets.QPushButton("Cancel")
            self._cancel_btn.clicked.connect(self.reject)
            btn_layout.addWidget(self._cancel_btn)
            layout.addLayout(btn_layout)

        # --- Callbacks set by caller ---
        self.on_success: Optional[Callable[[Any], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

        # --- Thread setup ---
        self._thread = QtCore.QThread()
        kw = dict(kwargs or {})
        kw["progress_callback"] = self._progress_callback
        self._worker = _BackgroundWorker(func, *args, **kw)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

    def _progress_callback(self, current: int, total: int, message: str):
        """Thread-safe: emit signal that will be received on the main thread."""
        self._worker.progress.emit(current, total, message)

    @QtCore.pyqtSlot(int, int, str)
    def _on_progress(self, current: int, total: int, message: str):
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
        self._status_label.setText(message)

    @QtCore.pyqtSlot(object)
    def _on_finished(self, result):
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(1)
        self._status_label.setText("Complete!")
        self._cleanup_thread()
        if self.on_success:
            self.on_success(result)
        self.accept()

    @QtCore.pyqtSlot(str)
    def _on_error(self, error_msg: str):
        self._cleanup_thread()
        if self.on_error:
            self.on_error(error_msg)
        else:
            QtWidgets.QMessageBox.critical(self, self.windowTitle(), f"Error:\n\n{error_msg}")
        self.reject()

    def _cleanup_thread(self):
        try:
            self._thread.quit()
            self._thread.wait(5000)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        # Start the thread after the dialog is shown
        QtCore.QTimer.singleShot(100, self._thread.start)

    def closeEvent(self, event):
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)

    def reject(self):
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        super().reject()


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
        from io import StringIO
        mpremote_main = mpremote_cmd[1]
        argv = ["mpremote", "connect", "auto"] + args
        old_argv = sys.argv
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        out = StringIO()
        err = StringIO()
        try:
            sys.argv = argv
            sys.stdout = out
            sys.stderr = err
            rc = mpremote_main()
            return type("Result", (), {"returncode": rc, "stdout": out.getvalue(), "stderr": err.getvalue()})()
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    return subprocess.run(
        mpremote_cmd + args,
        cwd=cwd,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        creationflags=creationflags,
        env=env,
    )


_TABLE_REORDER_MIME = "application/x-vintage-radio-table-reorder"


class ReorderTable(QtWidgets.QTableWidget):
    """QTableWidget with drag-to-reorder. Uses fully custom drag/drop so Qt
    never performs InternalMove (which nukes rows on macOS).
    """
    order_changed = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
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

    # -- snapshot helpers --------------------------------------------------

    def _snapshot_all(self) -> List[tuple]:
        """Return [(row, song_id, [col_texts]), ...] for every row."""
        result: List[tuple] = []
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is None:
                continue
            song_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if song_id is None:
                continue
            cols = []
            for c in range(self.columnCount()):
                it = self.item(row, c)
                cols.append(it.text() if it is not None else "")
            result.append((row, int(song_id), cols))
        return result

    def _rebuild_table(self, new_order: List[int],
                       id_to_cols: Dict[int, List[str]]) -> None:
        """Replace table contents with rows in *new_order*."""
        self.setSortingEnabled(False)
        self.blockSignals(True)
        try:
            self.setRowCount(len(new_order))
            for new_row, sid in enumerate(new_order):
                cols = id_to_cols.get(sid, [""] * self.columnCount())
                for c, text in enumerate(cols):
                    item = QtWidgets.QTableWidgetItem(text)
                    if c == 0:
                        item.setData(QtCore.Qt.ItemDataRole.UserRole, sid)
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                    self.setItem(new_row, c, item)
        finally:
            self.blockSignals(False)
            self.setSortingEnabled(True)

    # -- accept our custom mime during drag-over ----------------------------

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(_TABLE_REORDER_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(_TABLE_REORDER_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    # -- drag (our own QDrag, no super) ------------------------------------

    def startDrag(self, supportedActions: QtCore.Qt.DropActions) -> None:
        rows = sorted(set(idx.row() for idx in self.selectedIndexes()))
        sids: List[int] = []
        for r in rows:
            item = self.item(r, 0)
            if item is None:
                continue
            sid = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if sid is not None:
                sids.append(int(sid))
        if not sids:
            return
        mime = QtCore.QMimeData()
        mime.setData(_TABLE_REORDER_MIME,
                     ",".join(str(s) for s in sids).encode("utf-8"))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.exec(QtCore.Qt.DropAction.CopyAction)

    # -- drop --------------------------------------------------------------

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if event.source() is not self or not event.mimeData().hasFormat(_TABLE_REORDER_MIME):
            super().dropEvent(event)
            return

        raw = bytes(event.mimeData().data(_TABLE_REORDER_MIME)).decode("utf-8")
        try:
            moving = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            event.ignore()
            return
        if not moving:
            event.ignore()
            return

        snap = self._snapshot_all()
        current_sids = [sid for (_, sid, _) in snap]
        id_to_cols: Dict[int, List[str]] = {sid: cols for (_, sid, cols) in snap}
        moving_set = set(moving)
        staying = [s for s in current_sids if s not in moving_set]

        drop_pos = event.position().toPoint()
        viewport_pos = self.viewport().mapFrom(self, drop_pos)
        target_row = self.indexAt(viewport_pos).row()
        if target_row < 0:
            target_row = len(staying)
        insert_at = max(0, min(target_row, len(staying)))

        new_order = staying[:insert_at] + moving + staying[insert_at:]
        self._pending_order = new_order
        self._rebuild_table(new_order, id_to_cols)

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
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(QtCore.Qt.DropAction.CopyAction)
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(_REORDER_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(_REORDER_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

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
        if event.source() is not self:
            super().dropEvent(event)
            return
        if not event.mimeData().hasFormat(_REORDER_MIME):
            event.ignore()
            return

        raw = bytes(event.mimeData().data(_REORDER_MIME)).decode("utf-8")
        try:
            moving = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            event.ignore()
            return
        if not moving:
            event.ignore()
            return

        # Current list order (row -> uid, and uid -> item for text/icon)
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

        drop_pos = event.position().toPoint()
        viewport_pos = self.viewport().mapFrom(self, drop_pos)
        target_row = self.indexAt(viewport_pos).row()
        if target_row < 0:
            target_row = len(staying)
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

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Install MicroPython on Pico")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._downloaded_path: Optional[Path] = None
        self._build_ui()
        self._refresh_drives()
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
        QtWidgets.QMessageBox.information(
            self, "Install MicroPython on Pico",
            "MicroPython firmware copied. The Pico will reboot shortly.\n\n"
            "You can then use \"Install to Pico\" to deploy the app.",
        )


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1000, 700)

        icon_path = resource_path("vintage_radio.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._lib_registry = LibraryRegistry()
        slug = self._lib_registry.active_library()
        db_path = self._lib_registry.db_path_for(slug)
        self.db = DatabaseManager(db_path=db_path)
        self._update_window_title()

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
        self.test_mode_widget = TestModeWidget(self.db)
        self.device_debug_widget = DeviceDebugWidget()

        self._apply_saved_settings()

        self._build_menu()
        self._build_library_toolbar()
        self._build_tabs()
        self._set_button_cursors()
        self._refresh_all()
    
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

        tools_menu = self.menuBar().addMenu("Tools")
        sync_action = QtGui.QAction("Sync to SD", self)
        sync_action.triggered.connect(self.sync_to_sd)
        tools_menu.addAction(sync_action)

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

    # ── Library switcher toolbar ──────────────────────────────

    def _build_library_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("Library")
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(16, 16))
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)

        label = QtWidgets.QLabel("  Library: ")
        label.setStyleSheet("font-weight: bold;")
        tb.addWidget(label)

        self._lib_combo = QtWidgets.QComboBox()
        self._lib_combo.setMinimumWidth(180)
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

    def _switch_library(self, slug: str) -> None:
        """Close the current DB, open the one for *slug*, and refresh everything."""
        if slug == self._lib_registry.active_library():
            return
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

    def _propagate_db(self) -> None:
        """Push the current self.db to all sub-components that hold a reference."""
        self.sd_manager.db = self.db
        if hasattr(self, "test_mode_widget") and self.test_mode_widget:
            self.test_mode_widget.db = self.db
            if hasattr(self.test_mode_widget, "hw_emulator"):
                self.test_mode_widget.hw_emulator.db = self.db
            if hasattr(self.test_mode_widget, "sd_manager"):
                self.test_mode_widget.sd_manager.db = self.db

    def _update_window_title(self) -> None:
        name = self._lib_registry.active_library_name()
        self.setWindowTitle(f"Vintage Radio Music Manager - {name}")

    def _build_tabs(self) -> None:
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_library_tab(), "Library")
        tabs.addTab(self._build_albums_tab(), "Albums")
        tabs.addTab(self._build_playlists_tab(), "Playlists")
        tabs.addTab(self._build_sd_tab(), "Devices")
        tabs.addTab(self.test_mode_widget, "Emulator")
        device_tab_container = self._build_device_debug_tab()
        self._device_debug_tab_index = tabs.count()
        tabs.addTab(device_tab_container, "Device Debug")
        tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(tabs)

    def _build_device_debug_tab(self) -> QtWidgets.QWidget:
        """Build Device Debug tab with optional SD/library out-of-sync warning."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        self.device_sync_warning = QtWidgets.QLabel()
        self.device_sync_warning.setWordWrap(True)
        self.device_sync_warning.setStyleSheet("color: #c00; font-weight: bold;")
        self.device_sync_warning.setVisible(False)
        layout.addWidget(self.device_sync_warning)
        layout.addWidget(self.device_debug_widget)
        return container

    def _on_tab_changed(self, index: int) -> None:
        """When switching to Device Debug tab, check SD/library sync and show warning if needed."""
        if index == self._device_debug_tab_index:
            self._check_device_tab_sync()

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
                    f"{len(source_missing)} song(s) have missing source files (paths from another PC?) — re-import in Library or fix paths, then Sync to SD"
                )
            n = len(results.get("missing_sd_path", []))
            if n:
                parts.append(f"{n} missing SD paths")
            n = len(results.get("missing_file", []))
            if n:
                parts.append(f"{n} missing files on SD")
            if actual_size_mismatches:
                parts.append(f"{len(actual_size_mismatches)} size mismatches")
            n = len(results.get("hash_mismatch", []))
            if n:
                parts.append(f"{n} hash mismatches")
            self.device_sync_warning.setText(
                "⚠️ Library and SD card may be out of sync: " + ". ".join(parts)
            )
            self.device_sync_warning.setVisible(True)
        else:
            self.device_sync_warning.setVisible(False)

    def _build_library_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        controls = QtWidgets.QHBoxLayout()
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

        layout.addWidget(self.library_search)
        layout.addLayout(controls)
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

        # ---- Storage & target ----
        storage_group = QtWidgets.QGroupBox("Storage & target")
        storage_layout = QtWidgets.QVBoxLayout(storage_group)
        root_layout = QtWidgets.QHBoxLayout()
        root_layout.addWidget(QtWidgets.QLabel("SD / media root:"))
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
        target_layout = QtWidgets.QHBoxLayout()
        target_layout.addWidget(QtWidgets.QLabel("Audio target:"))
        self.audio_target_combo = QtWidgets.QComboBox()
        self.audio_target_combo.addItem("DFPlayer + RP2040", "dfplayer_rp2040")
        self.audio_target_combo.addItem("Raspberry Pi 2W/3", "raspberry_pi")
        self.audio_target_combo.setToolTip("Choose which device the library will be synced for. DFPlayer uses numbered folders (01/, 002.mp3); Pi uses a flat library folder.")
        idx = self.audio_target_combo.findData(self.audio_target)
        if idx >= 0:
            self.audio_target_combo.setCurrentIndex(idx)
        self.audio_target_combo.currentIndexChanged.connect(self._on_audio_target_changed)
        target_layout.addWidget(self.audio_target_combo)
        target_layout.addWidget(QtWidgets.QLabel("Used for sync layout and export options."))
        target_layout.addStretch()
        storage_layout.addLayout(target_layout)
        self.pi_convert_checkbox = QtWidgets.QCheckBox("Convert non-MP3 to MP3 when syncing for Pi")
        self.pi_convert_checkbox.setToolTip("When Raspberry Pi is the audio target: if checked, non-MP3 files are converted to MP3 during sync; if unchecked, files are copied as-is (e.g. FLAC, WAV).")
        self.pi_convert_checkbox.setChecked(self.pi_convert_audio)
        self.pi_convert_checkbox.stateChanged.connect(self._on_pi_convert_changed)
        self._update_pi_convert_visibility()
        storage_layout.addWidget(self.pi_convert_checkbox)
        layout.addWidget(storage_group)

        # ---- SD card operations ----
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
        import_btn = QtWidgets.QPushButton("Import from SD")
        import_btn.setToolTip("Import albums and playlists that were previously exported to this storage (e.g. from another machine) into your library.")
        import_btn.clicked.connect(self.import_from_sd)
        export_sd_contents_btn = QtWidgets.QPushButton("Export SD contents to folder...")
        export_sd_contents_btn.setToolTip("Run the same sync as \"Sync Library to SD\" but into a folder you choose (e.g. to copy to a USB stick or SD card manually later).")
        export_sd_contents_btn.clicked.connect(self.export_sd_contents_to_folder)
        actions_row.addWidget(sync_btn)
        actions_row.addWidget(validate_btn)
        actions_row.addWidget(eject_btn)
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

        # ---- RP2040 (Pico) ----
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

        # ---- Raspberry Pi ----
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

        layout.addWidget(QtWidgets.QLabel("Validation / import status:"))
        layout.addWidget(self.sd_status, 1)
        return widget

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
        try:
            retention = max(1, int(retention_raw))
        except ValueError:
            retention = 10
        self.db.auto_backup = auto_backup
        self.db.backup_retention = retention
        self._update_sd_root_label()

    def _refresh_all(self) -> None:
        self.refresh_library()
        self.refresh_albums()
        self.refresh_playlists()

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
            self._set_table_item(
                self.library_table,
                row_idx,
                0,
                song["title"],
                editable=True,
            )
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
            self.library_table.item(row_idx, 0).setData(
                QtCore.Qt.ItemDataRole.UserRole, song["id"]
            )
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
        self._update_album_details()
        self._populate_association_table(
            self.album_list.currentItem(), self.album_songs_table, is_album=True
        )

    def refresh_playlist_songs(self) -> None:
        self._update_playlist_details()
        self._populate_association_table(
            self.playlist_list.currentItem(), self.playlist_songs_table, is_album=False
        )

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
            self._set_table_item(table, row_idx, 0, song["title"])
            self._set_table_item(table, row_idx, 1, song["artist"])
            duration = self._format_duration(song["duration"])
            self._set_table_item(table, row_idx, 2, duration)
            self._set_table_item(table, row_idx, 3, song["format"])
            table.item(row_idx, 0).setData(
                QtCore.Qt.ItemDataRole.UserRole, song["id"]
            )

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

    def import_files(self, files: Iterable[Path]) -> List[int]:
        file_list = [p for p in files if p.exists() and p.is_file()]
        if not file_list:
            return []
        
        # For small imports (≤3 files), do it inline to keep it snappy
        if len(file_list) <= 3:
            return self._import_files_sync(file_list)
        
        # For larger imports, run in background thread with progress
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
        return getattr(self, '_pending_import_ids', [])

    @staticmethod
    def _import_files_worker(
        file_list: List[Path],
        db: DatabaseManager,
        progress_callback: Optional[callable] = None,
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

    def _import_files_sync(self, files: Iterable[Path]) -> List[int]:
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
        if not self.sd_root:
            self.sd_root_label.setText("Not set")
            return
        label = self.sd_label or self._get_volume_label(Path(self.sd_root))
        if label:
            self.sd_root_label.setText(f"{self.sd_root} ({label})")
        else:
            self.sd_root_label.setText(self.sd_root)

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

    def select_sd_root(self) -> None:
        candidates = self.sd_manager.detect_sd_roots()
        if not candidates:
            QtWidgets.QMessageBox.information(
                self, "SD Detect", "No removable drives detected."
            )
            return
        if len(candidates) == 1:
            self.sd_root = str(candidates[0][0])
            self.sd_label = candidates[0][1]
        else:
            choices = []
            mapping = {}
            for path, label in candidates:
                display = f"{path} ({label})" if label else str(path)
                choices.append(display)
                mapping[display] = str(path)
            selection, ok = QtWidgets.QInputDialog.getItem(
                self,
                "Select SD Root",
                "Choose SD card root:",
                choices,
                0,
                False,
            )
            if not ok or not selection:
                return
            self.sd_root = mapping.get(selection, selection)
            self.sd_label = ""
            for path, label in candidates:
                if str(path) == self.sd_root:
                    self.sd_label = label
        self.db.set_setting("sd_root", self.sd_root)
        self.db.set_setting("sd_label", self.sd_label)
        self._update_sd_root_label()

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
        
        dlg = TaskProgressDialog(
            parent=self,
            title="SD Card Sync" + (" (clean install)" if force_clean else ""),
            func=self.sd_manager.sync_library,
            args=(sd_root,),
            kwargs={
                "audio_target": self.audio_target,
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
                    except Exception:
                        pass
            if hasattr(self, 'test_mode_widget') and self.test_mode_widget:
                self.test_mode_widget.refresh_from_db()

        def on_error(msg):
            QtWidgets.QMessageBox.critical(self, "Sync Error", f"An error occurred during SD sync:\n\n{msg}")

        dlg.on_success = on_success
        dlg.on_error = on_error
        dlg.exec()

    def safely_remove_sd(self) -> None:
        """Safely eject/remove the SD card."""
        sd_root = self._resolve_sd_root()
        if not sd_root:
            QtWidgets.QMessageBox.warning(
                self,
                "No SD Card",
                "No SD card root selected. Please select an SD card first."
            )
            return
        
        try:
            import platform
            system = platform.system()
            if system == "Windows":
                # Existing Windows API handling preserved
                import ctypes
                from ctypes import wintypes
                drive_letter = sd_root.drive
                if not drive_letter:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Cannot Eject",
                        "Could not determine drive letter. Please eject manually using Windows Explorer."
                    )
                    return
                drive = drive_letter.rstrip(":")
                kernel32 = ctypes.windll.kernel32
                volume_path = f"\\\\.\\{drive}:"
                handle = kernel32.CreateFileW(
                    volume_path,
                    0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
                    0x1 | 0x2,  # FILE_SHARE_READ | FILE_SHARE_WRITE
                    None,
                    0x3,  # OPEN_EXISTING
                    0,  # No flags
                    None
                )
                if handle == -1:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Cannot Eject",
                        f"Could not lock drive {drive}:. The drive may be in use.\n\nPlease close any programs using the SD card and try again, or eject manually using Windows Explorer."
                    )
                    return
                try:
                    result = kernel32.DeviceIoControl(
                        handle,
                        0x2D4808,  # IOCTL_STORAGE_EJECT_MEDIA
                        None,
                        0,
                        None,
                        0,
                        ctypes.byref(wintypes.DWORD()),
                        None
                    )
                    if result:
                        QtWidgets.QMessageBox.information(
                            self,
                            "SD Card Ejected",
                            f"SD card ({drive}:) has been safely ejected.\n\nYou can now safely remove it."
                        )
                    else:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Eject Failed",
                            f"Could not eject drive {drive}:.\n\nPlease try ejecting manually using Windows Explorer."
                        )
                finally:
                    kernel32.CloseHandle(handle)
            elif system == "Darwin":
                # macOS: use diskutil to eject the volume
                try:
                    result = subprocess.run(
                        ["diskutil", "eject", str(sd_root)],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        QtWidgets.QMessageBox.information(
                            self,
                            "SD Card Ejected",
                            "SD card has been safely ejected.\n\nYou can now safely remove it."
                        )
                    else:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Eject Failed",
                            f"Could not eject SD card: {result.stderr or result.stdout}\n\nPlease try ejecting manually using Finder or Disk Utility."
                        )
                except FileNotFoundError:
                    QtWidgets.QMessageBox.warning(
                        self,
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
                        QtWidgets.QMessageBox.information(
                            self,
                            "SD Card Ejected",
                            "SD card has been safely unmounted.\n\nYou can now safely remove it."
                        )
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
                        QtWidgets.QMessageBox.information(
                            self,
                            "SD Card Ejected",
                            "SD card has been safely ejected.\n\nYou can now safely remove it."
                        )
                    else:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Eject Failed",
                            f"Could not eject SD card: {result.stderr or result.stdout}\n\nPlease try ejecting manually."
                        )
                except FileNotFoundError:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Eject Unavailable",
                        "Eject command not found. Please eject the SD card manually using your OS file manager."
                    )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                "Eject Error",
                f"An error occurred while trying to eject the SD card:\n{str(e)}\n\nPlease eject manually using your operating system's file manager."
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
        for name in ("main.py", "radio_core.py"):
            src = root / name
            if src.exists():
                shutil.copy2(src, dest / name)
        fw_src = root / "components" / "dfplayer_hardware.py"
        if fw_src.exists():
            (dest / "components").mkdir(parents=True, exist_ok=True)
            shutil.copy2(fw_src, dest / "components" / "dfplayer_hardware.py")
        vintage_dest = dest / "VintageRadio"
        vintage_dest.mkdir(parents=True, exist_ok=True)
        readme_txt = dest / "README_RP2040.txt"
        readme_txt.write_text(
            "RP2040 + DFPlayer. Copy main.py, radio_core.py, and components/\n"
            "to the Pico. AM sound is on SD card in folder 99/001.wav.\n"
            "SD layout: folders 01/, 02/, ... at SD root with 001.mp3, 002.mp3 inside;\n"
            "folder 99/001.wav for AM static sound; VintageRadio/ for metadata.\n"
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

    def _resolve_mpremote_cmd(self) -> Optional[List[str]]:
        """Find the mpremote command (bundled in-process, standalone, or system-installed).

        Priority order (frozen app):
        1. Standalone mpremote executable (if available)
        2. System Python with mpremote
        3. Bundled mpremote (in-process; no subprocess needed)
        """
        # First, try standalone mpremote executable (works everywhere)
        cmd = shutil.which("mpremote")
        if cmd:
            return [cmd]

        # Try system Python (user may have: pip install mpremote)
        system_python = shutil.which("pythonw") or shutil.which("python")
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

        # Frozen: use bundled mpremote in-process (no separate Python needed)
        if getattr(sys, "frozen", False):
            try:
                from mpremote.main import main as mpremote_main
                return ["__INPROCESS__", mpremote_main]
            except ImportError:
                pass

        # Not frozen: try current interpreter with -m mpremote
        if not getattr(sys, "frozen", False):
            try:
                import mpremote  # noqa: F401
                python_cmd = shutil.which("python") or sys.executable
                return [python_cmd, "-m", "mpremote"]
            except ImportError:
                pass

        return None

    @staticmethod
    def _install_to_pico_worker(
        mpremote_cmd: List[str],
        root: Path,
        sd_root: Optional[str],
        sd_manager: SDManager,
        progress_callback: Optional[callable] = None,
    ) -> str:
        """Background worker: copy firmware files to Pico via mpremote CLI.

        Uses mpremote command-line interface (bundled in-process when frozen, or subprocess).
        All subprocess calls use CREATE_NO_WINDOW on Windows to prevent new windows.

        Returns a status message string. Raises on fatal error.
        """
        import tempfile as _tempfile

        files_to_copy = [
            ("main.py", "main.py"),
            ("radio_core.py", "radio_core.py"),
            ("components/dfplayer_hardware.py", "components/dfplayer_hardware.py"),
        ]
        # Total steps: mkdir×2 + files + AM WAV + metadata + reboot
        total = 2 + len(files_to_copy) + 1 + 1 + 1
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

        def run_mpremote(args: List[str], timeout_sec: int = 30):
            return _run_mpremote(
                mpremote_cmd, args, cwd=str(root), capture_output=True, text=True,
                timeout=timeout_sec, creationflags=creation_flags, env=env,
            )

        def run_mpremote_with_retry(args: List[str], timeout_sec: int = 30):
            """Run mpremote; if it fails with 'no device found', wait 3s and retry once (Pico may still be re-enumerating after flash/reboot)."""
            r = run_mpremote(args, timeout_sec=timeout_sec)
            if r.returncode != 0:
                err = (r.stderr or "") + (r.stdout or "")
                if "no device found" in err.lower():
                    import time
                    time.sleep(3)
                    r = run_mpremote(args, timeout_sec=timeout_sec)
            return r

        # ── Create directories ──
        _report("Creating directories on Pico...")
        for dirname in ("components", "VintageRadio"):
            try:
                run_mpremote_with_retry(["exec", f"import os; os.mkdir('{dirname}')"], timeout_sec=15)
            except Exception:
                pass  # directory may already exist
        step = 2

        # ── Copy firmware files ──
        for local, remote in files_to_copy:
            _report(f"Copying {local}...")
            src = root / local
            if not src.exists():
                continue
            r = run_mpremote_with_retry(["cp", str(src), f":{remote}"])
            if r.returncode != 0:
                raise RuntimeError(
                    f"Failed to copy {local}.\n\n"
                    f"Ensure the Pico is connected via USB and running MicroPython.\n\n"
                    f"{r.stderr or r.stdout or ''}"
                )

        # ── Copy AMradioSound.wav ──
        _report("Copying AM radio sound...")
        from gui.resource_paths import resource_path
        am_wav_src = resource_path("AMradioSound.wav")
        if not am_wav_src.exists():
            am_wav_src = root / "AMradioSound.wav"
        if am_wav_src.exists():
            try:
                r = run_mpremote(["cp", str(am_wav_src), ":VintageRadio/AMradioSound.wav"])
                if r.returncode == 0:
                    print("AMradioSound.wav copied to Pico flash (PWM overlay enabled)")
                else:
                    print(f"Warning: Failed to copy AMradioSound.wav: {r.stderr or r.stdout}")
            except Exception as e:
                print(f"Warning: Could not copy AMradioSound.wav: {e}")
        else:
            print("AMradioSound.wav not found - PWM overlay won't be available")

        # ── Copy radio_metadata.json ──
        _report("Copying metadata...")
        metadata_src = None
        if sd_root:
            candidate = Path(sd_root) / "VintageRadio" / "radio_metadata.json"
            if candidate.exists():
                metadata_src = candidate

        tmpdir_cleanup = None
        if not metadata_src:
            tmpdir = _tempfile.mkdtemp()
            tmpdir_cleanup = tmpdir
            try:
                tmp_vintage = Path(tmpdir) / "VintageRadio"
                tmp_vintage.mkdir(parents=True, exist_ok=True)
                sd_manager._write_metadata(tmp_vintage)
                metadata_src = tmp_vintage / "radio_metadata.json"
            except Exception as e:
                print(f"Warning: Could not generate metadata: {e}")
                metadata_src = None

        if metadata_src and metadata_src.exists():
            try:
                run_mpremote(["cp", str(metadata_src), ":VintageRadio/radio_metadata.json"])
            except Exception as e:
                print(f"Warning: metadata copy failed: {e}")

        if tmpdir_cleanup:
            try:
                shutil.rmtree(tmpdir_cleanup)
            except Exception:
                pass

        # Full reboot (as if pressing reset button) so new firmware runs from cold
        _report("Rebooting Pico...")
        try:
            run_mpremote(["exec", "import machine; machine.reset()"], timeout_sec=5)
        except Exception as e:
            print(f"Note: Could not trigger reboot: {e}")

        if progress_callback:
            progress_callback(total, total, "Done!")
        return "Installed to Pico successfully. Pico has been rebooted."

    def install_to_pico(self) -> None:
        """Copy application files to Pico via mpremote (bundled with executable, or requires: pip install mpremote)."""
        mpremote_cmd = self._resolve_mpremote_cmd()
        if not mpremote_cmd:
            QtWidgets.QMessageBox.information(
                self,
                "Install to Pico",
                "mpremote is not available. In a packaged executable, mpremote should be bundled.\n\n"
                "If running from source, install it with:\n\n  pip install mpremote\n\n"
                "Then connect the Pico via USB (with MicroPython already installed) and try again.\n"
                "See README_RP2040.md for how to install MicroPython on the Pico (one-time).",
            )
            return

        root = self._project_root()
        if not (root / "main.py").exists() or not (root / "radio_core.py").exists():
            QtWidgets.QMessageBox.warning(self, "Install to Pico", "Project files not found.")
            return
        if not (root / "components" / "dfplayer_hardware.py").exists():
            QtWidgets.QMessageBox.warning(self, "Install to Pico", "components/dfplayer_hardware.py not found.")
            return

        dlg = TaskProgressDialog(
            parent=self,
            title="Install to Pico",
            func=self._install_to_pico_worker,
            args=(mpremote_cmd, root, self.sd_root, self.sd_manager),
            kwargs={},
        )

        def on_success(msg):
            self.statusBar().showMessage(str(msg), 5000)

        def on_error(msg):
            QtWidgets.QMessageBox.warning(self, "Install to Pico", f"Error:\n\n{msg}")

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
        for name in ("main_pi.py", "radio_core.py"):
            src = root / name
            if src.exists():
                shutil.copy2(src, deploy_dir / name)
        pi_hw = root / "components" / "pi_hardware.py"
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
        for name in ("main_pi.py", "radio_core.py"):
            src = root / name
            if src.exists():
                shutil.copy2(src, dest / name)
        pi_hw = root / "components" / "pi_hardware.py"
        if pi_hw.exists():
            (dest / "components").mkdir(parents=True, exist_ok=True)
            shutil.copy2(pi_hw, dest / "components" / "pi_hardware.py")
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

    def _resolve_sd_root(self) -> Optional[Path]:
        if self.sd_root:
            path = Path(self.sd_root)
            if path.exists():
                return path
        if self.sd_auto_detect:
            candidates = self.sd_manager.detect_sd_roots()
            if self.sd_label:
                matched = [path for path, label in candidates if label == self.sd_label]
                if len(matched) == 1:
                    self.sd_root = str(matched[0])
                    self.db.set_setting("sd_root", self.sd_root)
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
                choices = []
                mapping = {}
                for path, label in candidates:
                    display = f"{path} ({label})" if label else str(path)
                    choices.append(display)
                    mapping[display] = str(path)
                selection, ok = QtWidgets.QInputDialog.getItem(
                    self,
                    "Select SD Root",
                    "Choose SD card root:",
                    choices,
                    0,
                    False,
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
        remove_action = menu.addAction("Remove Selected")
        action = menu.exec(self.album_songs_table.viewport().mapToGlobal(pos))
        if action == remove_action:
            self.remove_selected_from_album()

    def show_playlist_table_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        remove_action = menu.addAction("Remove Selected")
        action = menu.exec(self.playlist_songs_table.viewport().mapToGlobal(pos))
        if action == remove_action:
            self.remove_selected_from_playlist()

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


def run_app() -> None:
    # Initialize session logging BEFORE anything else
    from .session_log import init_session_logging
    log_path = init_session_logging(app_version="1.0.0")
    print(f"Vintage Radio GUI starting...")

    app = QtWidgets.QApplication(sys.argv)

    # Set application icon (radio icon; taskbar/dock)
    icon_path = resource_path("vintage_radio.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Startup diagnostic: check whether VLC or ffmpeg+pydub are available for audio conversion.
    try:
        from .sd_manager import SDManager, PYDUB_AVAILABLE
        sd_check = SDManager(None)
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


