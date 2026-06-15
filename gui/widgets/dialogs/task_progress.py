"""Reusable threaded progress dialog for long-running GUI tasks."""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.sd_disk_image_flash import parse_disk_write_progress_message
from gui.widgets.common.vintage_progress import VintageProgressBar
from gui.widgets.dialogs.vintage_message import VintageMessageBox
from gui.widgets.dialogs.sync.primitives import (
    ModalButton,
    ModalFooter,
    ModalHeader,
    SyncModalShell,
    apply_frameless_modal,
    apply_modal_rounded_mask,
    refresh_modal_rounded_mask,
)

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

    @QtCore.pyqtSlot(object, object, str)
    def _relay_progress(self, current: object, total: object, message: str) -> None:
        self.progress.emit(current, total, message)

    def _safe_progress(self, current: int, total: int, message: str) -> None:
        # sync_library_basic reports from ThreadPoolExecutor workers; marshal to this
        # QObject's thread before emitting so GUI slots always run on the main thread.
        QtCore.QMetaObject.invokeMethod(
            self,
            "_relay_progress",
            QtCore.Qt.ConnectionType.QueuedConnection,
            QtCore.Q_ARG(object, current),
            QtCore.Q_ARG(object, total),
            QtCore.Q_ARG(str, message),
        )

    @QtCore.pyqtSlot()
    def run(self):
        try:
            kw = dict(self._kwargs)
            kw["progress_callback"] = self._safe_progress
            result = self._fn(*self._args, **kw)
            self.finished.emit(result)
        except Exception as exc:
            msg = str(exc)
            if "cancelled by user" in msg.lower() or msg.strip().lower() == "cancelled":
                self.error.emit(msg)
            else:
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
        show_byte_detail: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(t.SYNC_MDL_PROGRESS_W)
        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        shell = SyncModalShell()
        self._shell = shell

        header = ModalHeader(title)
        header.closed.connect(self.reject)
        shell.add_widget(header)

        body = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(body)
        self._body_lay = body_lay
        body_lay.setContentsMargins(
            t.SYNC_MDL_BODY_PAD,
            18,
            t.SYNC_MDL_BODY_PAD,
            t.SYNC_MDL_FOOTER_PAD_B if cancelable else 20,
        )
        body_lay.setSpacing(10)

        self._image_scan_label = QtWidgets.QLabel("")
        self._image_scan_label.setWordWrap(True)
        self._image_scan_label.hide()
        body_lay.addWidget(self._image_scan_label)

        self._status_label = QtWidgets.QLabel("Starting...")
        self._status_label.setWordWrap(True)
        body_lay.addWidget(self._status_label)

        self._progress_bar = VintageProgressBar()
        self._progress_bar.setRange(0, 0)
        body_lay.addWidget(self._progress_bar)

        self._eta_label = QtWidgets.QLabel("")
        self._eta_label.setWordWrap(True)
        body_lay.addWidget(self._eta_label)

        shell.add_widget(body)

        self._footer: Optional[ModalFooter] = None
        self._cancel_btn: Optional[ModalButton] = None
        if cancelable:
            footer = ModalFooter()
            self._footer = footer
            self._cancel_btn = ModalButton("Cancel", variant="secondary")
            self._cancel_btn.clicked.connect(self.reject)
            footer.add_button(self._cancel_btn)
            shell.add_widget(footer)

        outer.addWidget(shell)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(24, 12, 4, 112))
        shell.setGraphicsEffect(shadow)

        apply_modal_rounded_mask(self)
        self._apply_body_styles()

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

        # ETA / phase tracking (reset when phase changes, not mid-phase total tweaks).
        self._progress_last_phase: Optional[str] = None
        self._progress_last_total: Optional[int] = None
        self._progress_monotonic_start: Optional[float] = None

        # Legacy kwarg — byte detail removed from UI; kept for call-site compatibility.
        _ = show_byte_detail
        self._cancelable = cancelable

    def _status_label_min_height(self) -> int:
        fm = QtGui.QFontMetrics(self._status_label.font())
        return max(fm.height() + 8, 24)

    def _apply_body_styles(self) -> None:
        self._status_label.setStyleSheet(
            f"color: {t.SYNC_MDL_PROGRESS_STATUS_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_PROGRESS_STATUS_SIZE)}px;"
            f"background: transparent;"
            f"padding-top: 2px;"
            f"padding-bottom: 2px;"
        )
        self._status_label.setMinimumHeight(self._status_label_min_height())
        self._image_scan_label.setStyleSheet(
            f"color: {t.SYNC_MDL_PROGRESS_ETA_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_PROGRESS_ETA_SIZE)}px;"
            f"background: transparent;"
            f"padding-bottom: 2px;"
        )
        self._eta_label.setStyleSheet(
            f"color: {t.SYNC_MDL_PROGRESS_ETA_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_PROGRESS_ETA_SIZE)}px;"
            f"background: transparent;"
        )

    def reload_theme(self) -> None:
        """Re-apply SYNC_MDL_* tokens (dev theme live-reload)."""
        self.setFixedWidth(t.SYNC_MDL_PROGRESS_W)
        self._body_lay.setContentsMargins(
            t.SYNC_MDL_BODY_PAD,
            18,
            t.SYNC_MDL_BODY_PAD,
            t.SYNC_MDL_FOOTER_PAD_B if self._cancelable else 20,
        )
        self._apply_body_styles()
        self._progress_bar.reload_theme()
        self._shell.reload_theme()
        if self._footer is not None:
            self._footer.reload_theme()
        refresh_modal_rounded_mask(self)
        self.adjustSize()
        self.update()

    @staticmethod
    def _format_bytes_short(n: int) -> str:
        """Human-readable size for progress (GB / MB — what users see on SD card labels)."""
        n = max(0, n)
        if n >= 1024**3:
            return f"{n / (1024**3):.1f} GB"
        if n >= 1024**2:
            return f"{n / (1024**2):.0f} MB"
        if n >= 1024:
            return f"{n / 1024:.0f} KB"
        return f"{n} B"

    @staticmethod
    def _format_eta_seconds(rem: float) -> str:
        """Format ETA with largest units plus sub-units down to seconds."""
        rem_i = max(1, int(rem))
        days, rem_i = divmod(rem_i, 86400)
        hours, rem_i = divmod(rem_i, 3600)
        minutes, seconds = divmod(rem_i, 60)

        parts: List[str] = []
        if days:
            parts.append(f"{days} d")
        if hours or days:
            parts.append(f"{hours} h")
        if minutes or hours or days:
            parts.append(f"{minutes} min")
        parts.append(f"{seconds} s")
        return "~" + " ".join(parts) + " remaining"

    @staticmethod
    def _progress_phase_key(message: str) -> str:
        """Stable phase id; totals may adjust within a phase (e.g. sparse disk write)."""
        if not message:
            return ""
        m = message.strip()
        if m.startswith("Writing to SD card"):
            return "disk_write"
        if m.startswith("Install image:"):
            return "disk_write"
        if m.startswith("Creating install image"):
            return "image_create"
        if m.startswith("Writing disk image") or m.startswith("Image: writing disk image"):
            return "image_write"
        if "packing files into disk image" in m.lower():
            return "image_pack"
        ml = m.lower()
        if ml.startswith("preparing "):
            return "sync_prep"
        if ml.startswith("converting audio"):
            return "sync_convert"
        if ml.startswith("copying"):
            return "sync_copy"
        if ml.startswith("removing stale"):
            return "sync_cleanup"
        return m[:96]

    @staticmethod
    def _is_file_count_phase(message: str) -> bool:
        """True when current/total represent file indices rather than byte counts."""
        if not message:
            return False
        m = message.strip().lower()
        return (
            m.startswith("writing disk image")
            or m.startswith("image: writing disk image")
            or "packing files into disk image" in m
            or m.startswith("preparing ")
            or m.startswith("converting audio")
            or m.startswith("copying")
            or m.startswith("removing stale")
            or " files/s" in m
        )

    @QtCore.pyqtSlot(object, object, str)
    def _on_progress(self, current: object, total: object, message: str):
        # Ensure plain Python ints (signal carries object to avoid Qt int32 truncation).
        current = int(current)  # type: ignore[arg-type]
        total = int(total)  # type: ignore[arg-type]
        phase = self._progress_phase_key(message)
        partition_message, image_scan_message, embedded_eta = (
            parse_disk_write_progress_message(message)
        )
        if phase == "disk_write":
            message = partition_message

        # QProgressBar uses int ranges; values above ~2 GiB overflow signed 32-bit on Qt
        # and the bar sticks at 0 or wrong values. Scale huge jobs to 0..10000 + %.
        _QT_SAFE_MAX = 2_100_000_000

        if total > 0:
            phase_changed = phase != self._progress_last_phase
            if phase_changed:
                self._progress_last_phase = phase
                self._progress_last_total = None
                self._progress_monotonic_start = None

            # Within disk_write the partition total may shrink as we learn sparsity;
            # do not reset the ETA clock when it adjusts mid-stream.
            if self._progress_last_total != total and phase != "disk_write":
                self._progress_last_total = total
                self._progress_monotonic_start = time.monotonic()
            elif self._progress_last_total is None:
                self._progress_last_total = total
                self._progress_monotonic_start = time.monotonic()

            cur = min(max(0, current), total)
            if total > _QT_SAFE_MAX:
                scaled_max = 10_000
                scaled_val = min(scaled_max, max(0, cur * scaled_max // max(1, total)))
                self._progress_bar.setRange(0, scaled_max)
                self._progress_bar.setValue(scaled_val)
                pct = scaled_val * 100 // scaled_max
                self._progress_bar.setText(f"{pct}%")
            else:
                self._progress_bar.setRange(0, total)
                self._progress_bar.setValue(cur)
                if self._is_file_count_phase(message):
                    self._progress_bar.setText(f"{cur} / {total} files")
                else:
                    pct = cur * 100 // max(1, total)
                    self._progress_bar.setText(f"{pct}%")

            eta_text = ""
            if embedded_eta is not None and phase == "disk_write":
                if embedded_eta < 86400 * 3:
                    eta_text = self._format_eta_seconds(embedded_eta)
            elif cur > 0 and cur < total and self._progress_monotonic_start is not None:
                elapsed = time.monotonic() - self._progress_monotonic_start
                if elapsed > 0.4:
                    rate = cur / elapsed
                    if rate > 256:  # ignore noise
                        rem = (total - cur) / rate
                        if 1.0 <= rem < 86400 * 3:
                            eta_text = self._format_eta_seconds(rem)
            self._eta_label.setText(eta_text)

            # Disable Cancel once the write is done and we are just cleaning up
            # (remounting disk, etc.).  Cancelling at this point cannot undo the
            # write and only causes a crash from forcibly killing the thread.
            if cur >= total and not self._in_cleanup:
                self._in_cleanup = True
                if self._cancel_btn is not None:
                    self._cancel_btn.setEnabled(False)
                    self._cancel_btn.setText("Please wait…")
        else:
            # Message-only update: show busy state instead of leaving a stale max (e.g. 2/2).
            self._progress_bar.setRange(0, 0)
            self._progress_bar.setText("")
            self._eta_label.setText("")
            self._image_scan_label.hide()
            self._progress_last_phase = None
            self._progress_last_total = None
            self._progress_monotonic_start = None
        self._status_label.setText(message)
        self._status_label.setMinimumHeight(self._status_label_min_height())
        if phase == "disk_write" and image_scan_message:
            self._image_scan_label.setText(image_scan_message)
            self._image_scan_label.show()
        elif phase != "disk_write":
            self._image_scan_label.hide()

    @QtCore.pyqtSlot(object)
    def _on_finished(self, result):
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(1)
        self._progress_bar.setText("100%")
        self._status_label.setText("Complete!")
        self._image_scan_label.hide()
        self._eta_label.setText("")
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
        if self.on_error:
            self.on_error(error_msg)
        else:
            VintageMessageBox.critical(self, self.windowTitle(), f"Error:\n\n{error_msg}")
        self.reject()

    def _cleanup_thread(self) -> None:
        """Gracefully stop the worker thread (called on the normal finish/error path)."""
        try:
            self._thread.quit()
            self._thread.wait(10000)
        except Exception:
            pass

    def _detach_thread(self) -> None:
        """Detach the running thread so it outlives the dialog without crashing Qt."""
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
        if self._thread.isRunning() and not self._in_cleanup:
            event.ignore()
            self.reject()
            return
        super().closeEvent(event)

    def reject(self):
        # If we are already in cleanup (write done, remounting) the Cancel button
        # should be disabled and this method should not be reachable — guard anyway.
        if self._in_cleanup:
            return

        if self._thread.isRunning():
            if self._cancel_btn is not None:
                _mb = VintageMessageBox(self)
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
                    return
            self._cancel_event.set()
            self._detach_thread()
        super().reject()


class IndeterminateProgressDialog(QtWidgets.QDialog):
    """Frameless progress shell for blocking main-thread work (``processEvents`` loops)."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        title: str,
        message: str = "Working...",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(t.SYNC_MDL_PROGRESS_W)
        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        shell = SyncModalShell()
        header = ModalHeader(title)
        shell.add_widget(header)

        body = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(body)
        body_lay.setContentsMargins(
            t.SYNC_MDL_BODY_PAD, 16, t.SYNC_MDL_BODY_PAD, 20,
        )
        body_lay.setSpacing(10)

        self._status_label = QtWidgets.QLabel(message)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"color: {t.SYNC_MDL_PROGRESS_STATUS_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_PROGRESS_STATUS_SIZE)}px;"
            f"background: transparent;"
        )
        body_lay.addWidget(self._status_label)

        self._progress_bar = VintageProgressBar()
        self._progress_bar.setRange(0, 0)
        body_lay.addWidget(self._progress_bar)

        shell.add_widget(body)
        outer.addWidget(shell)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(24, 12, 4, 112))
        shell.setGraphicsEffect(shadow)

        apply_modal_rounded_mask(self)

    def set_message(self, message: str) -> None:
        self._status_label.setText(message)
        QtWidgets.QApplication.processEvents()

    def set_progress(self, current: int, total: int, message: str = "") -> None:
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
        else:
            self._progress_bar.setRange(0, 0)
        if message:
            self._status_label.setText(message)
        QtWidgets.QApplication.processEvents()

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        QtWidgets.QApplication.processEvents()
