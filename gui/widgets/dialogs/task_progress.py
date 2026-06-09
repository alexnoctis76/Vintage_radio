"""Reusable threaded progress dialog for long-running GUI tasks."""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable, List, Optional

from PyQt6 import QtCore, QtWidgets

# Keep Python references to threads/workers that are still running after their
# dialog has been closed.  Without this, Python's GC destroys the QThread wrapper
# while the underlying C++ thread is alive, causing Qt to call abort().
_orphaned_threads: List[object] = []


class _BackgroundWorker(QtCore.QObject):
    """Runs a callable in a QThread and emits progress/completion signals."""

    # Use object (not int) for current/total so PyQt does not coerce Python's arbitrary-
    # precision ints to C++ int32.  Values above ~2.1 GiB would silently overflow a
    # 32-bit Qt int, causing the progress bar to wrap and cycle multiple times for large
    # disk images even though the signal is emitted with correct byte counts.
    progress = QtCore.pyqtSignal(object, object, str)  # current (bytes), total (bytes), message
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
        show_byte_detail: bool = True,
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
        self._detail_label.setVisible(show_byte_detail)
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
        # Set to True once the worker signals it has entered a non-cancellable
        # cleanup phase (current == total > 0).  Cancel is disabled at that point.
        self._in_cleanup = False

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

        # ETA / phase tracking (reset when *total* changes between phases).
        self._progress_last_total: Optional[int] = None
        self._progress_monotonic_start: Optional[float] = None

    @staticmethod
    def _format_bytes_short(n: int) -> str:
        n = max(0, n)
        if n >= 1 << 30:
            return f"{n / (1 << 30):.2f} GiB"
        if n >= 1 << 20:
            return f"{n / (1 << 20):.1f} MiB"
        if n >= 1 << 10:
            return f"{n / (1 << 10):.0f} KiB"
        return f"{n} B"

    @staticmethod
    def _is_file_count_phase(message: str) -> bool:
        """True when current/total represent file indices rather than byte counts.

        The experimental SD image-build phase reports progress as
        ``"Writing disk image (X/Y files)..."`` (and the lead-in message
        ``"FAT32 image created - packing files into disk image..."``). Detecting
        these prevents the detail label from formatting file indices as bytes.
        """
        if not message:
            return False
        m = message.strip().lower()
        return (
            m.startswith("writing disk image")
            or m.startswith("image: writing disk image")
            or "packing files into disk image" in m
        )

    @QtCore.pyqtSlot(object, object, str)
    def _on_progress(self, current: object, total: object, message: str):
        # Ensure plain Python ints (signal carries object to avoid Qt int32 truncation).
        current = int(current)  # type: ignore[arg-type]
        total = int(total)  # type: ignore[arg-type]

        # QProgressBar uses int ranges; values above ~2 GiB overflow signed 32-bit on Qt
        # and the bar sticks at 0 or wrong values. Scale huge jobs to 0..10000 + %.
        _QT_SAFE_MAX = 2_100_000_000

        if total > 0:
            if self._progress_last_total != total:
                self._progress_last_total = total
                self._progress_monotonic_start = time.monotonic()

            cur = min(max(0, current), total)
            if total > _QT_SAFE_MAX:
                scaled_max = 10_000
                scaled_val = min(scaled_max, max(0, cur * scaled_max // max(1, total)))
                self._progress_bar.setRange(0, scaled_max)
                self._progress_bar.setValue(scaled_val)
                # QProgressBar::setFormat does literal substitution of %p/%v/%m only;
                # it does NOT treat "%%" as an escape, so "%p%%" renders as "1%%".
                # Use a single percent sign for the trailing literal.
                self._progress_bar.setFormat("%p%")
            else:
                self._progress_bar.setRange(0, total)
                self._progress_bar.setValue(cur)
                self._progress_bar.setFormat("%v / %m")

            # During the image-build phase ``current``/``total`` are file indices,
            # not byte counts. Show them as files so the detail label doesn't read
            # "11 KiB / 24 KiB" for what is really "11321 / 24992 files".
            if self._is_file_count_phase(message):
                detail_parts = [f"{cur} / {total} files"]
            else:
                detail_parts = [
                    f"{self._format_bytes_short(cur)} / {self._format_bytes_short(total)}"
                ]
            if cur > 0 and cur < total and self._progress_monotonic_start is not None:
                elapsed = time.monotonic() - self._progress_monotonic_start
                if elapsed > 0.4:
                    rate = cur / elapsed
                    if rate > 256:  # ignore noise
                        rem = (total - cur) / rate
                        if 1.0 <= rem < 86400 * 3:
                            if rem >= 3600:
                                detail_parts.append(
                                    f"~{int(rem // 3600)} h {int((rem % 3600) // 60)} min remaining"
                                )
                            elif rem >= 120:
                                detail_parts.append(f"~{int(rem // 60)} min remaining")
                            elif rem >= 60:
                                detail_parts.append(f"~{int(rem // 60)} min {int(rem % 60)} s remaining")
                            else:
                                detail_parts.append(f"~{max(1, int(rem))} s remaining")
            self._detail_label.setText("  •  ".join(detail_parts))

            # Disable Cancel once the write is done and we are just cleaning up
            # (remounting disk, etc.).  Cancelling at this point cannot undo the
            # write and only causes a crash from forcibly killing the thread.
            if cur >= total and not self._in_cleanup:
                self._in_cleanup = True
                if hasattr(self, "_cancel_btn"):
                    self._cancel_btn.setEnabled(False)
                    self._cancel_btn.setText("Please wait…")
        else:
            # Message-only update: show busy state instead of leaving a stale max (e.g. 2/2).
            self._progress_bar.setRange(0, 0)
            self._detail_label.setText("")
            self._progress_last_total = None
            self._progress_monotonic_start = None
        self._status_label.setText(message)

    @QtCore.pyqtSlot(object)
    def _on_finished(self, result):
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(1)
        self._status_label.setText("Complete!")
        # Flush bar/label so the dialog does not look stuck before nested UI runs.
        QtWidgets.QApplication.processEvents()
        self._cleanup_thread()
        cb = self.on_success
        self.on_success = None
        self.accept()
        # Defer success UI to the next event-loop tick so this dialog is fully closed
        # first (avoids nested-modal + QThread teardown races that could abort the app).
        if cb is not None:

            def _emit_success() -> None:
                cb(result)

            QtCore.QTimer.singleShot(0, _emit_success)

    @QtCore.pyqtSlot(str)
    def _on_error(self, error_msg: str):
        self._cleanup_thread()
        # Session log: QMessageBox.critical / .warning are patched in run_app to log GUI-ERROR.
        if self.on_error:
            self.on_error(error_msg)
        else:
            QtWidgets.QMessageBox.critical(self, self.windowTitle(), f"Error:\n\n{error_msg}")
        self.reject()

    def _cleanup_thread(self) -> None:
        """Gracefully stop the worker thread (called on the normal finish/error path)."""
        try:
            self._thread.quit()
            self._thread.wait(10000)
        except Exception:
            pass

    def _detach_thread(self) -> None:
        """Detach the running thread so it outlives the dialog without crashing Qt.

        ``QThread::~QThread()`` calls ``abort()`` if the thread is still running when
        the C++ object is destroyed.  When the user cancels mid-operation (e.g. while
        ``dd`` or ``diskutil`` blocks), we cannot safely stop the thread immediately.
        Instead we:

        1. Keep Python-level references alive in ``_orphaned_threads`` so the GC does
           not destroy the ``QThread`` wrapper while the C++ thread runs.
        2. Disconnect all worker signals so they don't fire on a closed dialog.
        3. Register a ``finished`` callback that removes the references once the thread
           exits naturally (the cancel event causes it to exit at the next poll tick).
        """
        try:
            self._worker.progress.disconnect(self._on_progress)
        except Exception:
            pass
        try:
            self._worker.finished.disconnect(self._on_finished)
        except Exception:
            pass
        try:
            self._worker.error.disconnect(self._on_error)
        except Exception:
            pass

        thread = self._thread
        worker = self._worker

        def _release() -> None:
            try:
                _orphaned_threads.remove(thread)
            except ValueError:
                pass
            try:
                _orphaned_threads.remove(worker)
            except ValueError:
                pass

        _orphaned_threads.append(thread)
        _orphaned_threads.append(worker)
        thread.finished.connect(_release)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(100, self._thread.start)

    def closeEvent(self, event):
        if self._thread.isRunning():
            self._cancel_event.set()
            self._detach_thread()
        super().closeEvent(event)

    def reject(self):
        # If we are already in cleanup (write done, remounting) the Cancel button
        # should be disabled and this method should not be reachable — guard anyway.
        if self._in_cleanup:
            return

        self._cancel_event.set()

        if self._thread.isRunning():
            if hasattr(self, "_cancel_btn"):
                # Use a plain QMessageBox instance (not the static .warning() method) so
                # the session-log patch does not record this confirmation as [GUI-ERROR].
                _mb = QtWidgets.QMessageBox(self)
                _mb.setWindowTitle("Cancel?")
                _mb.setText(
                    "Cancelling now will stop the write mid-way and may leave the "
                    "SD card in an incomplete state, requiring a reformat.\n\n"
                    "Cancel the write anyway?"
                )
                _mb.setIcon(QtWidgets.QMessageBox.Icon.Warning)
                _yes = _mb.addButton("Cancel write", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
                _mb.addButton("Keep writing", QtWidgets.QMessageBox.ButtonRole.RejectRole)
                _mb.exec()
                if _mb.clickedButton() is not _yes:
                    self._cancel_event.clear()
                    return
            self._detach_thread()

        super().reject()
