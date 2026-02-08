"""Main GUI application for Vintage Radio Music Manager."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QIcon

from .audio_metadata import compute_file_hash, extract_metadata
from .database import DatabaseManager
from .sd_manager import SDManager
from .test_mode import TestModeWidget
from . import sd_manager as sd_manager_module


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


class ReorderTable(QtWidgets.QTableWidget):
    order_changed = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSortingEnabled(False)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        super().dropEvent(event)
        self.order_changed.emit()


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


class InstallMicroPythonDialog(QtWidgets.QDialog):
    """One-time setup: copy MicroPython .uf2 to Pico in BOOTSEL mode."""

    MICROPYTHON_PICO_URL = "https://micropython.org/download/RPI_PICO/"
    MICROPYTHON_PICO_W_URL = "https://micropython.org/download/RPI_PICO_W/"

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Install MicroPython on Pico")
        self.setModal(True)
        self._build_ui()
        self._refresh_drives()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        instructions = (
            "1. Hold the BOOTSEL button on the Pico.\n"
            "2. Plug the Pico into USB. It will appear as a drive (e.g. RPI-RP2).\n"
            "3. Download the MicroPython .uf2 for your board (link below), then select it and the Pico drive here.\n"
            "4. Click Copy to Pico. The Pico will reboot with MicroPython (one-time setup)."
        )
        layout.addWidget(QtWidgets.QLabel(instructions))
        link_layout = QtWidgets.QHBoxLayout()
        link_btn = QtWidgets.QPushButton("Open MicroPython download (Pico)")
        link_btn.setToolTip("Standard Pico (no wireless)")
        link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QtCore.QUrl(self.MICROPYTHON_PICO_URL)))
        link_w_btn = QtWidgets.QPushButton("Open download (Pico W)")
        link_w_btn.setToolTip("Pico W (Wi-Fi)")
        link_w_btn.clicked.connect(lambda: QDesktopServices.openUrl(QtCore.QUrl(self.MICROPYTHON_PICO_W_URL)))
        link_layout.addWidget(link_btn)
        link_layout.addWidget(link_w_btn)
        link_layout.addStretch()
        layout.addLayout(link_layout)
        form = QtWidgets.QFormLayout()
        self.uf2_edit = QtWidgets.QLineEdit()
        self.uf2_edit.setPlaceholderText("Path to .uf2 file")
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_uf2)
        uf2_row = QtWidgets.QHBoxLayout()
        uf2_row.addWidget(self.uf2_edit)
        uf2_row.addWidget(browse_btn)
        form.addRow("UF2 file:", uf2_row)
        self.drive_combo = QtWidgets.QComboBox()
        self.drive_combo.setToolTip("Select the Pico drive (shown when BOOTSEL is held and Pico is connected)")
        refresh_drives_btn = QtWidgets.QPushButton("Refresh")
        refresh_drives_btn.clicked.connect(self._refresh_drives)
        drive_row = QtWidgets.QHBoxLayout()
        drive_row.addWidget(self.drive_combo)
        drive_row.addWidget(refresh_drives_btn)
        form.addRow("Pico drive:", drive_row)
        layout.addLayout(form)
        copy_btn = QtWidgets.QPushButton("Copy to Pico")
        copy_btn.clicked.connect(self._copy_to_pico)
        layout.addWidget(copy_btn)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: green;")
        layout.addWidget(self.status_label)

    def _browse_uf2(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select MicroPython firmware (.uf2)",
            "",
            "UF2 firmware (*.uf2);;All files (*)",
        )
        if path:
            self.uf2_edit.setText(path)

    def _refresh_drives(self) -> None:
        self.drive_combo.clear()
        for path, label in SDManager.detect_sd_roots():
            display = f"{label} ({path})" if label else str(path)
            self.drive_combo.addItem(display, path)
        if self.drive_combo.count() == 0:
            self.drive_combo.addItem("(No removable drives found)", None)

    def _copy_to_pico(self) -> None:
        uf2_path = Path(self.uf2_edit.text().strip())
        if not uf2_path.is_file() or uf2_path.suffix.lower() != ".uf2":
            QtWidgets.QMessageBox.warning(
                self,
                "Install MicroPython on Pico",
                "Please select a valid .uf2 file (e.g. from the MicroPython download page).",
            )
            return
        drive_data = self.drive_combo.currentData()
        if drive_data is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Install MicroPython on Pico",
                "No Pico drive selected. Hold BOOTSEL, plug in the Pico, then click Refresh.",
            )
            return
        dest_dir = Path(drive_data)
        if not dest_dir.is_dir():
            QtWidgets.QMessageBox.warning(
                self,
                "Install MicroPython on Pico",
                f"Drive not found: {dest_dir}. Unplug and replug the Pico (with BOOTSEL held), then Refresh.",
            )
            return
        dest_file = dest_dir / uf2_path.name
        try:
            shutil.copy2(uf2_path, dest_file)
        except OSError as e:
            QtWidgets.QMessageBox.warning(
                self,
                "Install MicroPython on Pico",
                f"Could not copy to Pico: {e}",
            )
            return
        self.status_label.setText("Firmware copied. Pico will reboot with MicroPython.")
        QtWidgets.QMessageBox.information(
            self,
            "Install MicroPython on Pico",
            "MicroPython firmware copied. The Pico will reboot shortly. You can then use \"Install to Pico\" to deploy the app.",
        )


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vintage Radio Music Manager")
        self.resize(1000, 700)
        
        # Set window icon
        icon_path = Path(__file__).resolve().parent / "resources" / "vintage_radio.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.db = DatabaseManager()
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

        self.album_list = QtWidgets.QListWidget()
        self.album_songs_table = self._create_song_table(reorderable=True)
        self.album_songs_table.order_changed.connect(self.persist_album_order)
        if isinstance(self.album_songs_table, CollectionDropTable):
            self.album_songs_table.files_dropped.connect(self.import_files_to_album)
        self.playlist_list = QtWidgets.QListWidget()
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

        self._apply_saved_settings()

        self._build_menu()
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

    def _build_tabs(self) -> None:
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_library_tab(), "Library")
        tabs.addTab(self._build_albums_tab(), "Albums")
        tabs.addTab(self._build_playlists_tab(), "Playlists")
        tabs.addTab(self._build_sd_tab(), "Devices")
        tabs.addTab(self.test_mode_widget, "Test Mode")
        self.setCentralWidget(tabs)

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
        left_panel.addWidget(QtWidgets.QLabel("Albums"))
        left_panel.addWidget(self.album_list)

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
        left_panel.addWidget(QtWidgets.QLabel("Playlists"))
        left_panel.addWidget(self.playlist_list)

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
        sync_btn.setToolTip("Copy (and convert if needed) your full library to the storage root. Layout depends on Audio target: DFPlayer uses 01/, 02/, 001.mp3; Pi uses VintageRadio/library/.")
        sync_btn.clicked.connect(self.sync_to_sd)
        validate_btn = QtWidgets.QPushButton("Validate SD")
        validate_btn.setToolTip("Check that every track in the library has a file on storage and report missing or mismatched files.")
        validate_btn.clicked.connect(self.validate_sd)
        import_btn = QtWidgets.QPushButton("Import from SD")
        import_btn.setToolTip("Import albums and playlists that were previously exported to this storage (e.g. from another machine) into your library.")
        import_btn.clicked.connect(self.import_from_sd)
        export_sd_contents_btn = QtWidgets.QPushButton("Export SD contents to folder...")
        export_sd_contents_btn.setToolTip("Run the same sync as \"Sync Library to SD\" but into a folder you choose (e.g. to copy to a USB stick or SD card manually later).")
        export_sd_contents_btn.clicked.connect(self.export_sd_contents_to_folder)
        actions_row.addWidget(sync_btn)
        actions_row.addWidget(validate_btn)
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
        added = 0
        skipped = 0
        added_ids: List[int] = []
        for path in files:
            if not path.exists() or not path.is_file():
                continue
            try:
                metadata = extract_metadata(path)
                file_hash = compute_file_hash(path)
                if (
                    self.db.get_song_by_hash_size(file_hash, metadata["file_size"])
                    is not None
                    or self.db.get_song_by_path(metadata["file_path"]) is not None
                ):
                    skipped += 1
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
        
        # Show progress dialog
        progress = QtWidgets.QProgressDialog("Syncing library to SD card...", "Cancel", 0, 0, self)
        progress.setWindowTitle("SD Card Sync")
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)  # Show immediately
        progress.setValue(0)
        progress.setMaximum(0)  # Indeterminate progress
        progress.show()
        QtWidgets.QApplication.processEvents()  # Update UI
        
        try:
            copied, skipped = self.sd_manager.sync_library(
                sd_root,
                audio_target=self.audio_target,
                pi_convert_audio=self.pi_convert_audio,
            )
            progress.close()
            self.statusBar().showMessage(
                f"SD sync complete. Copied: {copied}, skipped: {skipped}", 5000
            )
            # Refresh test mode to pick up new SD card paths (including radio stations)
            if hasattr(self, 'test_mode_widget') and self.test_mode_widget:
                self.test_mode_widget.refresh_from_db()
        except Exception as e:
            progress.close()
            QtWidgets.QMessageBox.critical(
                self,
                "Sync Error",
                f"An error occurred during SD sync:\n{str(e)}"
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
        results = self.sd_manager.import_from_sd(sd_root)
        self.refresh_albums()
        self.refresh_playlists()
        self.refresh_library()
        self.sd_status.setPlainText(
            f"Imported albums: {results['albums']}\nImported playlists: {results['playlists']}"
        )

    def _project_root(self) -> Path:
        """Project root (parent of gui package)."""
        return Path(__file__).resolve().parents[1]

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
        am_wav = Path(__file__).resolve().parent / "resources" / "AMradioSound.wav"
        vintage_dest = dest / "VintageRadio"
        vintage_dest.mkdir(parents=True, exist_ok=True)
        if am_wav.exists():
            shutil.copy2(am_wav, vintage_dest / "AMradioSound.wav")
        readme_txt = dest / "README_RP2040.txt"
        readme_txt.write_text(
            "RP2040 + DFPlayer. Copy main.py, radio_core.py, and components/\n"
            "to the Pico. Put AMradioSound.wav in VintageRadio/ on the SD card.\n"
            "SD layout: folders 01/, 02/, ... at SD root with 001.mp3, 002.mp3 inside;\n"
            "VintageRadio/ for AMradioSound.wav, album_state.txt, radio_metadata.json.\n"
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

    def install_to_pico(self) -> None:
        """Copy application files to Pico via mpremote (requires: pip install mpremote, MicroPython on Pico)."""
        mpremote = shutil.which("mpremote")
        if not mpremote:
            QtWidgets.QMessageBox.information(
                self,
                "Install to Pico",
                "mpremote is not installed. Install it with:\n\n  pip install mpremote\n\n"
                "Then connect the Pico via USB (with MicroPython already installed) and try again.\n"
                "See README_RP2040.md for how to install MicroPython on the Pico (one-time).",
            )
            return
        root = self._project_root()
        if not (root / "main.py").exists() or not (root / "radio_core.py").exists():
            QtWidgets.QMessageBox.warning(self, "Install to Pico", "Project files not found.")
            return
        comp_src = root / "components" / "dfplayer_hardware.py"
        if not comp_src.exists():
            QtWidgets.QMessageBox.warning(self, "Install to Pico", "components/dfplayer_hardware.py not found.")
            return
        progress = QtWidgets.QProgressDialog("Installing to Pico...", None, 0, 0, self)
        progress.setWindowTitle("Install to Pico")
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QtWidgets.QApplication.processEvents()
        try:
            try:
                subprocess.run(
                    [mpremote, "exec", "import os; os.mkdir('components')"],
                    cwd=str(root), capture_output=True, text=True, timeout=15
                )
            except Exception:
                pass
            for local, remote in [
                ("main.py", "main.py"),
                ("radio_core.py", "radio_core.py"),
                ("components/dfplayer_hardware.py", "components/dfplayer_hardware.py"),
            ]:
                src = root / local
                if not src.exists():
                    continue
                cmd = [mpremote, "cp", str(src), f":{remote}"]
                r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=30)
                if r.returncode != 0:
                    progress.close()
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Install to Pico",
                        f"Failed to copy {local}.\n\nEnsure the Pico is connected via USB and running MicroPython.\n\n{r.stderr or r.stdout or ''}",
                    )
                    return
            progress.close()
            self.statusBar().showMessage("Installed to Pico successfully.", 5000)
        except subprocess.TimeoutExpired:
            progress.close()
            QtWidgets.QMessageBox.warning(self, "Install to Pico", "Timed out. Check Pico connection and try again.")
        except Exception as e:
            progress.close()
            QtWidgets.QMessageBox.warning(self, "Install to Pico", f"Error: {e}")

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
        deploy_dir = root / "agent_workshop" / "deploy_pi" / "vintage_radio"
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
        self.db.replace_album_tracks(album_id, self._table_song_ids(self.album_songs_table))

    def persist_playlist_order(self) -> None:
        playlist_item = self.playlist_list.currentItem()
        if playlist_item is None:
            return
        playlist_id = int(playlist_item.data(QtCore.Qt.ItemDataRole.UserRole))
        self.db.replace_playlist_tracks(
            playlist_id, self._table_song_ids(self.playlist_songs_table)
        )

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
    app = QtWidgets.QApplication(sys.argv)
    
    # Set application icon (for taskbar/Windows thumbnail)
    icon_path = Path(__file__).resolve().parent / "resources" / "vintage_radio.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_app()


