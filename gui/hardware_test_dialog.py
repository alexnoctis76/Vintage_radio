"""Hardware Diagnostics Dialog.

Accessible via:
  - Keyboard shortcut: Ctrl+Shift+H
  - Hidden menu item in Tools menu (only visible when Shift is held while opening the menu)

Flashes hw_test.py to a connected Pico and streams the test output to a
color-coded console showing [PASS] / [FAIL] lines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from gui.widgets.common.styled_combo import VintageComboBox
import gui.theme as t
from gui.widgets.dialogs.sync.primitives import ModalButton, begin_sync_modal_dialog
from gui.widgets.dialogs.vintage_message import VintageMessageBox


def _resource_path(relative: str) -> Path:
    """Return absolute path to a bundled resource (works frozen and from source)."""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).parent.parent / relative


class _FlashAndRunWorker(QtCore.QObject):
    """Runs the flash-and-test sequence in a background thread."""

    output_line = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(int, int)  # (passed, failed)
    error = QtCore.pyqtSignal(str)

    def __init__(self, port: str, hw_test_path: Path):
        super().__init__()
        self._port = port
        self._hw_test_path = hw_test_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self._do_run()
        except Exception as exc:
            self.error.emit(str(exc))

    def _do_run(self):
        import subprocess
        import sys

        port = self._port
        hw_test = self._hw_test_path

        if not hw_test.exists():
            self.error.emit(f"hw_test.py not found at: {hw_test}")
            return

        self.output_line.emit(f"[INFO] Flashing {hw_test.name} to device on {port}...")

        # Step 1: Copy hw_test.py to the device
        cp_cmd = [sys.executable, "-m", "mpremote", "connect", port,
                  "cp", str(hw_test), ":hw_test.py"]
        result = subprocess.run(cp_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            err = (result.stderr or result.stdout).strip()
            self.output_line.emit(f"[ERROR] Flash failed: {err}")
            self.error.emit(f"mpremote copy failed: {err}")
            return

        self.output_line.emit("[INFO] File copied. Restarting and running tests...")

        if self._cancelled:
            return

        # Step 2: Execute the tests
        run_cmd = [sys.executable, "-m", "mpremote", "connect", port,
                   "exec", "import hw_test; hw_test.run_all()"]
        proc = subprocess.Popen(run_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)

        passed = 0
        failed = 0

        for line in proc.stdout:
            if self._cancelled:
                proc.terminate()
                break
            stripped = line.rstrip()
            if stripped:
                self.output_line.emit(stripped)
                if "[PASS]" in stripped:
                    passed += 1
                elif "[FAIL]" in stripped:
                    failed += 1

        proc.wait()
        self.finished.emit(passed, failed)


class HardwareTestDialog(QtWidgets.QDialog):
    """Secret hardware diagnostics dialog.

    Flash hw_test.py to a connected Pico and view live test output.
    """

    def __init__(self, parent=None, default_port: Optional[str] = None):
        super().__init__(parent)
        self._worker: Optional[_FlashAndRunWorker] = None
        self._thread: Optional[QtCore.QThread] = None

        self._body_lay, footer = begin_sync_modal_dialog(
            self,
            title="Hardware Diagnostics",
            subtitle="Flash hw_test.py to a connected Pico and view live output.",
            min_width=640,
        )
        self._footer = footer
        self._build_ui(default_port)
        self._scan_ports()
        self.resize(720, 520)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self, default_port: Optional[str]) -> None:
        layout = self._body_lay

        # Top row: port selector + scan + run
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Device:"))
        self._port_combo = VintageComboBox(
            min_width=180,
            max_width=9999,
            fixed_height=t.TOOLS_ACTION_BTN_H,
        )
        top.addWidget(self._port_combo, 1)

        self._scan_btn = ModalButton("Scan", variant="secondary")
        self._scan_btn.clicked.connect(self._scan_ports)
        top.addWidget(self._scan_btn)

        self._run_btn = ModalButton("Run Tests", variant="primary")
        self._run_btn.clicked.connect(self._start_tests)
        top.addWidget(self._run_btn)

        layout.addLayout(top)

        # Console output
        layout.addWidget(QtWidgets.QLabel("Console Output:"))
        self._console = QtWidgets.QPlainTextEdit()
        self._console.setReadOnly(True)
        self._console.setFont(QtGui.QFont("Courier New", 10))
        self._console.setStyleSheet(
            "background: #1a1a1a; color: #e0e0e0; border: 1px solid #444; border-radius: 8px; padding: 8px;"
        )
        console_scroll = wrap_with_mockup_scrollbar(self._console, variant="station")
        layout.addWidget(console_scroll, 1)

        # Summary label
        self._summary_label = QtWidgets.QLabel("")
        self._summary_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._summary_label.setStyleSheet("background: transparent;")
        layout.addWidget(self._summary_label)

        save_btn = ModalButton("Save Log", variant="secondary")
        save_btn.clicked.connect(self._save_log)
        self._footer.add_left_widget(save_btn)

        copy_btn = ModalButton("Copy to Clipboard", variant="secondary")
        copy_btn.clicked.connect(self._copy_log)
        self._footer.add_left_widget(copy_btn)

        close_btn = ModalButton("Close", variant="secondary")
        close_btn.clicked.connect(self.close)
        self._footer.add_button(close_btn)

    # ------------------------------------------------------------------
    # Port scanning
    # ------------------------------------------------------------------

    def _scan_ports(self) -> None:
        self._port_combo.clear()
        try:
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
        except ImportError:
            self._port_combo.addItem("(pyserial not installed)")
            return

        pico_ports = []
        other_ports = []
        for p in ports:
            desc = (p.description or "").lower()
            vid = getattr(p, "vid", None)
            # Raspberry Pi Pico vendor IDs: 0x2E8A
            if vid == 0x2E8A or "pico" in desc or "rp2" in desc.lower():
                pico_ports.append(p)
            else:
                other_ports.append(p)

        for p in pico_ports + other_ports:
            label = f"{p.device} — {p.description}" if p.description else p.device
            self._port_combo.addItem(label, userData=p.device)

        if not pico_ports and not other_ports:
            self._port_combo.addItem("(no ports found)")

    def _selected_port(self) -> Optional[str]:
        idx = self._port_combo.currentIndex()
        if idx < 0:
            return None
        data = self._port_combo.itemData(idx)
        return data if isinstance(data, str) else None

    # ------------------------------------------------------------------
    # Test execution
    # ------------------------------------------------------------------

    def _start_tests(self) -> None:
        port = self._selected_port()
        if not port:
            VintageMessageBox.warning(self, "No Port", "Select a port first.")
            return

        hw_test_path = _resource_path("firmware/pico/hw_test.py")

        self._console.clear()
        self._summary_label.setText("")
        self._run_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)

        self._thread = QtCore.QThread(self)
        self._worker = _FlashAndRunWorker(port, hw_test_path)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.output_line.connect(self._append_line)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def _append_line(self, line: str) -> None:
        """Append a line to the console with color coding."""
        cursor = self._console.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)

        fmt = QtGui.QTextCharFormat()
        if "[PASS]" in line:
            fmt.setForeground(QtGui.QColor("#50fa7b"))  # green
        elif "[FAIL]" in line:
            fmt.setForeground(QtGui.QColor("#ff5555"))  # red
        elif "[ERROR]" in line:
            fmt.setForeground(QtGui.QColor("#ffb86c"))  # orange
        elif "[INFO]" in line:
            fmt.setForeground(QtGui.QColor("#8be9fd"))  # cyan
        else:
            fmt.setForeground(QtGui.QColor("#e0e0e0"))  # default

        cursor.insertText(line + "\n", fmt)
        self._console.setTextCursor(cursor)
        self._console.ensureCursorVisible()

    def _on_finished(self, passed: int, failed: int) -> None:
        total = passed + failed
        summary = f"Results: {passed}/{total} passed, {failed} failed"
        self._append_line("")
        self._append_line(summary)
        self._summary_label.setText(summary)
        if failed == 0 and total > 0:
            self._summary_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        elif failed > 0:
            self._summary_label.setStyleSheet("color: #e74c3c; font-weight: bold;")

        self._run_btn.setEnabled(True)
        self._scan_btn.setEnabled(True)
        self._cleanup_thread()

    def _on_error(self, msg: str) -> None:
        self._append_line(f"[ERROR] {msg}")
        self._run_btn.setEnabled(True)
        self._scan_btn.setEnabled(True)
        self._cleanup_thread()

    def _cleanup_thread(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    # ------------------------------------------------------------------
    # Log actions
    # ------------------------------------------------------------------

    def _save_log(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Diagnostics Log", "hw_diagnostics.txt",
            "Text files (*.txt);;All files (*)"
        )
        if path:
            Path(path).write_text(self._console.toPlainText(), encoding="utf-8")

    def _copy_log(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self._console.toPlainText())

    # ------------------------------------------------------------------
    # Cleanup on close
    # ------------------------------------------------------------------

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._worker:
            self._worker.cancel()
        self._cleanup_thread()
        super().closeEvent(event)
