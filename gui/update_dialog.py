"""Dialog for showing and applying available app updates."""

from __future__ import annotations

import re
import sys
import threading
import tempfile
from pathlib import Path
from typing import Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from . import updater


class _DownloadSignals(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int)
    finished = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str)


class UpdateAvailableDialog(QtWidgets.QDialog):
    """Prompt the user to download and install a newer release."""

    def __init__(
        self,
        release_info: updater.ReleaseInfo,
        current_version: str,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.release_info = release_info
        self.current_version = current_version
        self._download_urls = updater.installer_download_urls_for_release(release_info)
        self._download_url = self._download_urls[0] if self._download_urls else ""
        base = updater.official_installer_zip_basename() or "update.zip"
        safe_tag = re.sub(r"[^\w.\-+]+", "_", self.release_info.tag_name.strip()) or "release"
        self._cache_dest_name = f"{Path(base).stem}-{safe_tag}{Path(base).suffix}"
        self._signals = _DownloadSignals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_download_finished)
        self._signals.failed.connect(self._on_download_failed)

        self.setWindowTitle("Update Available")
        self.setModal(True)
        self.resize(680, 500)

        title = QtWidgets.QLabel(
            f"A new version is available: {self.release_info.tag_name}\n"
            f"Current version: {self.current_version}"
        )
        title.setWordWrap(True)

        notes = self.release_info.body or "No release notes provided."
        self.notes_view = QtWidgets.QPlainTextEdit(notes)
        self.notes_view.setReadOnly(True)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.progress.setVisible(False)

        self.download_btn = QtWidgets.QPushButton(
            "Download & Install" if self._download_url else "Open Download Page"
        )
        self.later_btn = QtWidgets.QPushButton("Later")
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.later_btn.clicked.connect(self.reject)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.download_btn)
        btn_row.addWidget(self.later_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(QtWidgets.QLabel("Release notes:"))
        layout.addWidget(self.notes_view, 1)
        layout.addWidget(self.progress)
        layout.addLayout(btn_row)

    def _on_download_clicked(self) -> None:
        if not self._download_url:
            QDesktopServices.openUrl(QUrl(self.release_info.html_url or updater.GITHUB_RELEASES_URL))
            self.accept()
            return

        self.download_btn.setEnabled(False)
        self.later_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        def _worker() -> None:
            try:
                cache_root = QtCore.QStandardPaths.writableLocation(
                    QtCore.QStandardPaths.StandardLocation.CacheLocation
                )
                base = Path(cache_root) if cache_root else Path(tempfile.gettempdir()) / "VintageRadio"
                cache_dir = base / "update"
                zip_path = updater.download_update_try_urls(
                    self._download_urls,
                    cache_dir,
                    progress_cb=self._signals.progress.emit,
                    dest_filename=self._cache_dest_name,
                )
                self._signals.finished.emit(str(zip_path))
            except Exception as e:
                self._signals.failed.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = int((done / total) * 100)
            self.progress.setRange(0, 100)
            self.progress.setValue(max(0, min(100, pct)))
        else:
            self.progress.setRange(0, 0)  # indeterminate

    def _on_download_finished(self, path: str) -> None:
        try:
            updater.apply_update(Path(path))
        except Exception as e:
            self._on_download_failed(str(e))
            return
        msg = "Update downloaded. The app will now close to complete installation."
        if sys.platform == "darwin":
            msg += (
                "\n\nThe updated app should reopen automatically in a few seconds.\n\n"
                "If it does not appear, open it manually from the same location "
                "(e.g. Applications). If something went wrong, see apply_update.log "
                "next to the update download in your VintageRadio cache folder."
            )
        elif sys.platform == "win32":
            msg += "\n\nThe updater will restart Vintage Radio when this window closes."
        QtWidgets.QMessageBox.information(self, "Updater", msg)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()
        self.accept()

    def _on_download_failed(self, error: str) -> None:
        self.download_btn.setEnabled(True)
        self.later_btn.setEnabled(True)
        self.progress.setVisible(False)
        QtWidgets.QMessageBox.critical(self, "Updater", f"Update failed:\n{error}")
