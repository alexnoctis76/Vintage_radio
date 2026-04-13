"""Reusable threaded progress dialog for long-running GUI tasks."""

from __future__ import annotations

import threading
import traceback
from typing import Any, Callable, Optional

from PyQt6 import QtCore, QtWidgets

class _BackgroundWorker(QtCore.QObject):
    """Runs a callable in a QThread and emits progress/completion signals."""

    progress = QtCore.pyqtSignal(int, int, str)  # current, total, message
    finished = QtCore.pyqtSignal(object)  # result object
    error = QtCore.pyqtSignal(str)  # formatted error text

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    @QtCore.pyqtSlot()
    def run(self):
        try:
            # Never pass a callback that touches TaskProgressDialog (main thread) from here.
            # Emit only from this QObject (worker's thread) so slots on the dialog get
            # QueuedConnection delivery — fixes stuck 0/N and "Not Responding" on Windows.
            kw = dict(self._kwargs)

            def _safe_progress(current: int, total: int, message: str) -> None:
                self.progress.emit(current, total, message)

            kw["progress_callback"] = _safe_progress
            result = self._fn(*self._args, **kw)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(f"{exc}\n\n{traceback.format_exc()}")


class TaskProgressDialog(QtWidgets.QDialog):
    """Run a function in a worker thread with a non-blocking progress UI."""

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        title: str,
        func: Callable,
        args: tuple = (),
        kwargs: dict | None = None,
        cancelable: bool = False,
        cancel_callback_kwarg: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(580)
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QtWidgets.QVBoxLayout(self)
        self._status_label = QtWidgets.QLabel("Starting...")
        self._status_label.setWordWrap(True)
        self._status_label.setMinimumWidth(520)
        self._status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            self._status_label.sizePolicy().verticalPolicy(),
        )
        layout.addWidget(self._status_label)

        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setRange(0, 0)
        # Default "%p" shows 0% until ~1% of huge totals (e.g. 200/25000); show counts instead.
        self._progress_bar.setFormat("%v / %m")
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

        self.on_success: Optional[Callable[[Any], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self._cancel_event = threading.Event()

        self._thread = QtCore.QThread()
        kw = dict(kwargs or {})
        if cancel_callback_kwarg:
            kw[cancel_callback_kwarg] = self._cancel_event.is_set
        self._worker = _BackgroundWorker(func, *args, **kw)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        qc = QtCore.Qt.ConnectionType.QueuedConnection
        self._worker.progress.connect(self._on_progress, qc)
        self._worker.finished.connect(self._on_finished, qc)
        self._worker.error.connect(self._on_error, qc)

    @QtCore.pyqtSlot(int, int, str)
    def _on_progress(self, current: int, total: int, message: str):
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(min(max(0, current), total))
        else:
            # Message-only update: show busy state instead of leaving a stale max (e.g. 2/2).
            self._progress_bar.setRange(0, 0)
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
        # Session log: QMessageBox.critical / .warning are patched in run_app to log GUI-ERROR.
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
        QtCore.QTimer.singleShot(100, self._thread.start)

    def closeEvent(self, event):
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)

    def reject(self):
        self._cancel_event.set()
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        super().reject()
