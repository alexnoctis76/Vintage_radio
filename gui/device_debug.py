"""Device Debug Widget - REPL and debugging interface for physical Pico device."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from typing import Any, Callable, Optional, Tuple

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


def live_vrtest_arg_for_command(command: str) -> Optional[str]:
    """Map Send Command text to a VRTEST arg when it can run without Ctrl+C (REPL).

    Returns None when the command must use the REPL path (interrupts main.py).
    """
    text = (command or "").strip()
    if not text:
        return None
    # Single-line only; multiline REPL snippets stay on the interrupt path.
    if "\n" in text:
        return None
    normalized = text.rstrip(";").strip()
    lowered = normalized.lower()
    live_map = {
        "gc.mem_free()": "mem_free",
        "import gc; gc.mem_free()": "mem_free",
        "mem_free": "mem_free",
        "gc.collect()": "gc_collect",
        "import gc; gc.collect()": "gc_collect",
        "gc_collect": "gc_collect",
        "collect": "gc_collect",
    }
    if lowered in live_map:
        return live_map[lowered]
    return None


def format_live_vrtest_result(device: dict) -> str:
    """Human-readable stdout for a VRTEST_RESULT object from the device."""
    if not device.get("ok"):
        err = device.get("error", "unknown")
        detail = device.get("detail", "")
        return f"VRTEST error: {err}" + (f" ({detail})" if detail else "")
    cmd = device.get("cmd", "")
    if cmd == "mem_free":
        return "mem_free: {} bytes".format(device.get("mem_free", "?"))
    if cmd == "gc_collect":
        before = device.get("mem_free_before", "?")
        after = device.get("mem_free_after", "?")
        recovered = device.get("recovered", "?")
        return (
            "gc.collect() complete — mem_free before: {} bytes, after: {} bytes "
            "(recovered {} bytes)".format(before, after, recovered)
        )
    if cmd == "get_state" and isinstance(device.get("state"), dict):
        return json.dumps(device["state"], indent=2, sort_keys=True)
    return json.dumps(device, indent=2, sort_keys=True)


from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from .sd_manager import SDManager
from .services.serial_debug import (
    append_session_ndjson_from_vrdbg_line,
    is_recoverable_usb_serial_error,
)
from .widgets.common.styled_combo import VintageComboBox
from .widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from .widgets.dialogs.vintage_message import VintageMessageBox
from .widgets.tools.connection_section import ConnectionSection


class DeviceDebugWidget(QtWidgets.QWidget):
    """Widget for debugging the physical Pico device via mpremote."""

    #: Emitted when USB "device here" state changes: serial port, console connected, or RPI-RP2 (BOOTSEL).
    device_presence_changed = QtCore.pyqtSignal(bool)
    
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        basic_mode: bool = False,
        db=None,
        db_getter: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("deviceDebugRoot")
        self._basic_mode = basic_mode
        self._db = db
        #: If set, always read the active library DB from the manager (survives library switch / reconnect).
        self._db_getter = db_getter
        self._mpremote_cmd = None
        self._connected = False
        self._output_thread = None
        self._stop_output = False
        self._streaming_thread = None
        self._stop_streaming = False
        self._active_operations = set()  # Track active operations to prevent conflicts
        self._debug_logging = True  # Enable detailed debug logging
        self._port_lock = threading.Lock()  # Serialize port access
        self._serial_connection = None  # THE persistent serial connection (shared by all operations)
        self._use_mpremote = False  # Set to False to disable mpremote entirely (serial-only mode)
        self._streaming_pause_event = threading.Event()  # Set = streaming paused
        self._streaming_resume_event = threading.Event()  # Set = streaming can resume
        self._current_device_mode = ""  # Track current mode from stream output
        self._current_device_source = ""  # Track current source (album/playlist name)
        self._current_shuffle_type = ""  # Track shuffle type: 'library', 'album', 'playlist', 'source'
        self._current_track_title = ""
        self._current_track_artist = ""
        self._current_album_idx = 0  # Track album/playlist index for fallback display
        self._am_wav_loaded = None  # None = unknown, True/False = detected from stream
        self._last_presence_emitted: Optional[bool] = None
        self._poll_signature: Optional[Tuple[str, ...]] = None
        self._poll_usb_signature: Optional[Tuple[Tuple[str, ...], bool]] = None
        self._stream_ring_lock = threading.Lock()
        self._stream_ring: deque[str] = deque(maxlen=2500)
        self._setup_ui()
        self._scan_ports()  # Port scanning uses serial.tools.list_ports (no mpremote needed)
        self._presence_poll_timer = QtCore.QTimer(self)
        self._presence_poll_timer.setInterval(1500)
        self._presence_poll_timer.timeout.connect(self._poll_serial_presence)
        self._presence_poll_timer.start()
        self._debug_log("DeviceDebugWidget initialized", "info")

    def _effective_db(self):
        """Database used for station/track lookup (getter wins when provided)."""
        if self._db_getter is not None:
            try:
                d = self._db_getter()
                if d is not None:
                    return d
            except Exception:
                pass
        return self._db

    def set_library_db(self, db) -> None:
        """Use the active library database for basic-mode track name lookup (library switch)."""
        self._db = db
        self._scan_console_for_now_playing()

    def refresh_library_db_and_now_playing(self) -> None:
        """Re-sync cached DB handle from getter and re-parse the console (connect, SD sync)."""
        if self._db_getter is not None:
            try:
                d = self._db_getter()
                if d is not None:
                    self._db = d
            except Exception:
                pass
        self._scan_console_for_now_playing()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.TOOLS_DEBUG_ROW_GAP if self._basic_mode else 8)
        
        if not self._basic_mode:
            title = QtWidgets.QLabel("Device Debug Console")
            title.setStyleSheet("font-size: 18px; font-weight: bold;")
            layout.addWidget(title)
        
        # Connection banner (matches Install Firmware / Load Music storage bars)
        self._conn_section = ConnectionSection(compact=self._basic_mode)
        self._conn_section.scan_clicked.connect(self._scan_ports)
        self._conn_section.connect_clicked.connect(self._toggle_connection)
        self._conn_section.reset_clicked.connect(self._reset_connection)
        self.port_combo = self._conn_section.port_combo
        self.scan_btn = self._conn_section.scan_btn
        self.connect_btn = self._conn_section.connect_btn
        self.reset_connection_btn = self._conn_section.reset_btn
        self.connection_status = self._conn_section.status_label
        self.reset_connection_btn.setEnabled(False)
        layout.addWidget(self._conn_section)
        
        # Quick actions
        actions_group = QtWidgets.QGroupBox("Quick Actions")
        actions_layout = QtWidgets.QHBoxLayout(actions_group)
        actions_layout.setSpacing(t.TOOLS_DEBUG_ROW_GAP)
        
        self.restart_firmware_btn = QtWidgets.QPushButton("Restart Firmware")
        self.restart_firmware_btn.setToolTip("Restart main.py on the device (use this if device stops working after connecting)")
        self.restart_firmware_btn.clicked.connect(self._restart_firmware)
        self.restart_firmware_btn.setEnabled(False)
        
        self.soft_reset_btn = QtWidgets.QPushButton("Soft Reset")
        self.soft_reset_btn.setToolTip("Perform a full device soft reset (machine.soft_reset())")
        self.soft_reset_btn.clicked.connect(self._soft_reset)
        self.soft_reset_btn.setEnabled(False)
        
        self.get_status_btn = QtWidgets.QPushButton("Get Status")
        self.get_status_btn.setToolTip("Get device status, memory info, and recent debug log")
        self.get_status_btn.clicked.connect(self._get_status)
        self.get_status_btn.setEnabled(False)
        
        self.view_debug_log_btn = QtWidgets.QPushButton("Save Session Log")
        self.view_debug_log_btn.setToolTip("Save the current console output to a file on your PC")
        self.view_debug_log_btn.clicked.connect(self._view_debug_log)
        self.view_debug_log_btn.setEnabled(True)  # Always enabled - saves local console content
        
        self.check_firmware_btn = QtWidgets.QPushButton("Check Firmware Status")
        self.check_firmware_btn.setToolTip("Check if firmware is running and see recent activity")
        self.check_firmware_btn.clicked.connect(self._check_firmware_status)
        self.check_firmware_btn.setEnabled(False)
        
        self.list_files_btn = QtWidgets.QPushButton("List Files")
        self.list_files_btn.setToolTip("List files on the device")
        self.list_files_btn.clicked.connect(self._list_files)
        self.list_files_btn.setEnabled(False)
        
        self.clear_console_btn = QtWidgets.QPushButton("Clear Console")
        self.clear_console_btn.clicked.connect(self._clear_console)
        
        self.stream_output_btn = QtWidgets.QPushButton("Start Streaming")
        self.stream_output_btn.setToolTip(
            "Stream real-time output from the Pico (non-intrusive, like Thonny). "
            "Streaming starts automatically when you connect; use this to stop or start again."
        )
        self.stream_output_btn.clicked.connect(self._toggle_streaming)
        self.stream_output_btn.setEnabled(False)
        
        # Debug logging toggle
        self.debug_logging_checkbox = QtWidgets.QCheckBox("Debug Logging")
        self.debug_logging_checkbox.setChecked(True)
        self.debug_logging_checkbox.setToolTip("Enable detailed debug logs in console and Python console")
        self.debug_logging_checkbox.stateChanged.connect(self._toggle_debug_logging)
        
        # Start/Stop button (Thonny-style, shown in basic mode)
        self.run_stop_btn = QtWidgets.QPushButton("Start")
        self.run_stop_btn.setObjectName("vrRunStopBtn")
        self.run_stop_btn.setToolTip(
            "Stop interrupts MicroPython (Ctrl+C), runs a short REPL snippet to call "
            "DFPlayer stop on the running firmware, then leaves you at REPL. "
            "After Connect we assume main.py is already running and show Stop; "
            "use Start if you stopped the firmware or are at the REPL."
        )
        self.run_stop_btn.clicked.connect(self._toggle_run_stop)
        self._firmware_running = False
        self._set_run_stop_button_state(running=False, enabled=False)

        self.test_basic_fw_btn = QtWidgets.QPushButton("Flash Basic Mode Firmware")
        self.test_basic_fw_btn.setToolTip(
            "Flash basic-mode firmware (discovers stations from DFPlayer folders via UART queries). "
            "Use this to test DFPlayer 0x4F/0x4E query support on your hardware."
        )
        self.test_basic_fw_btn.clicked.connect(self._flash_basic_firmware)

        power_layout = QtWidgets.QHBoxLayout()
        self.power_sense_checkbox = QtWidgets.QCheckBox("Skip Power Sense Check (No Potentiometer)")
        self.power_sense_checkbox.setToolTip(
            "When checked, the device will start without waiting for GP14 (power sense) to go HIGH. "
            "Use this when testing without a potentiometer. Default: OFF (requires power sense)."
        )
        self.power_sense_checkbox.stateChanged.connect(self._toggle_power_sense)
        power_layout.addWidget(self.power_sense_checkbox)
        power_layout.addStretch()

        power_layout.addWidget(self.power_sense_checkbox)
        power_layout.addStretch()

        for btn in (
            self.restart_firmware_btn,
            self.soft_reset_btn,
            self.run_stop_btn,
            self.clear_console_btn,
            self.view_debug_log_btn,
        ):
            actions_layout.addWidget(btn)
        if not self._basic_mode:
            for btn in (
                self.get_status_btn,
                self.list_files_btn,
                self.check_firmware_btn,
            ):
                actions_layout.addWidget(btn)
            actions_layout.addWidget(self.stream_output_btn)
            actions_layout.addWidget(self.debug_logging_checkbox)
            actions_layout.addWidget(self.test_basic_fw_btn)
            actions_layout.addLayout(power_layout)
            actions_layout.addStretch()
            layout.addWidget(actions_group)

        if self._basic_mode:
            self.view_debug_log_btn.setText("Save Log")
        else:
            self.view_debug_log_btn.setText("Save Session Log")

        if self._basic_mode:
            self.list_files_btn.setVisible(False)
            self.check_firmware_btn.setVisible(False)
            self.test_basic_fw_btn.setVisible(False)
            self.power_sense_checkbox.setVisible(False)
            self.debug_logging_checkbox.setVisible(False)
            self.get_status_btn.setVisible(False)
            self.stream_output_btn.setVisible(False)
            self._debug_logging = True
            self.run_stop_btn.setVisible(True)
        else:
            self.run_stop_btn.setVisible(False)
        
        # Now Playing display
        now_playing_group = QtWidgets.QGroupBox("Now Playing")
        now_playing_layout = QtWidgets.QVBoxLayout(now_playing_group)
        now_playing_layout.setContentsMargins(8, 8, 8, 8)
        
        self.now_playing_label = QtWidgets.QLabel("Not connected")
        self.now_playing_label.setStyleSheet(
            "font-size: 12px; padding: 8px; background-color: #2d2d2d; "
            "border: 1px solid #555; border-radius: 4px; color: #d4d4d4;"
        )
        self.now_playing_label.setWordWrap(True)
        self.now_playing_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        self.now_playing_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        now_playing_layout.addWidget(self.now_playing_label, 1)
        
        # Console output
        console_group = QtWidgets.QGroupBox("Console Output")
        console_layout = QtWidgets.QVBoxLayout(console_group)
        console_layout.setContentsMargins(8, 8, 8, 8)
        
        self.console_output = QtWidgets.QTextEdit()
        self.console_output.setObjectName("deviceDebugConsole")
        self.console_output.setReadOnly(True)
        self.console_output.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.console_output.setFont(QtGui.QFont("Consolas", t.TOOLS_LOG_FONT))
        self._console_scroll_wrap = wrap_with_mockup_scrollbar(
            self.console_output,
            variant="station",
        )
        console_layout.addWidget(self._console_scroll_wrap, 1)
        
        # Command input
        cmd_group = QtWidgets.QGroupBox("Send Command")
        cmd_group.setToolTip(
            "gc.mem_free() and gc.collect() run live via VRTEST (playback continues). "
            "Other commands use the REPL (Ctrl+C stops main.py until Restart Firmware)."
        )
        cmd_layout = QtWidgets.QVBoxLayout(cmd_group)
        cmd_layout.setSpacing(6)
        
        cmd_input_layout = QtWidgets.QHBoxLayout()
        cmd_input_layout.setSpacing(t.TOOLS_DEBUG_ROW_GAP)
        self.cmd_input = QtWidgets.QLineEdit()
        self.cmd_input.setPlaceholderText(
            "Python command — gc.mem_free() / gc.collect() keep playback running; "
            "type help for more"
        )
        self.cmd_input.returnPressed.connect(self._send_command)
        cmd_input_layout.addWidget(self.cmd_input, 1)
        
        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.setObjectName("deviceDebugPrimaryBtn")
        self.send_btn.clicked.connect(self._send_command)
        self.send_btn.setEnabled(False)
        cmd_input_layout.addWidget(self.send_btn)
        
        cmd_layout.addLayout(cmd_input_layout)
        
        # Example commands
        examples_label = QtWidgets.QLabel("Example commands:")
        examples_label.setObjectName("deviceDebugMuted")
        cmd_layout.addWidget(examples_label)
        
        examples_text = QtWidgets.QLabel(
            "help | print('Hello') | import machine; machine.Pin(2).value() | "
            "from components.dfplayer_hardware import DFPlayerHardware; hw = DFPlayerHardware() | "
            "check_amplifier (diagnostic command)"
        )
        examples_text.setObjectName("deviceDebugMutedSmall")
        examples_text.setWordWrap(True)
        cmd_layout.addWidget(examples_text)
        if self._basic_mode:
            examples_label.setVisible(False)
            examples_text.setVisible(False)

        console_container = QtWidgets.QWidget()
        console_container_layout = QtWidgets.QVBoxLayout(console_container)
        console_container_layout.setContentsMargins(0, 0, 0, 0)
        console_container_layout.setSpacing(t.TOOLS_DEBUG_ROW_GAP)
        console_container_layout.addWidget(console_group, 1)
        console_container_layout.addWidget(cmd_group)

        if self._basic_mode:
            playback_row = QtWidgets.QWidget()
            playback_row.setObjectName("deviceDebugPlaybackRow")
            row_layout = QtWidgets.QHBoxLayout(playback_row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(t.TOOLS_DEBUG_ROW_GAP)

            now_playing_group.setMinimumHeight(t.TOOLS_NOW_PLAYING_MAX_H)
            now_playing_group.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )
            actions_group.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Minimum,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )

            row_layout.addWidget(now_playing_group, 1)
            row_layout.addWidget(
                actions_group,
                0,
                QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignRight,
            )

            layout.addWidget(playback_row)
            layout.addWidget(console_container, 1)
        else:
            splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
            splitter.setChildrenCollapsible(False)
            splitter.addWidget(now_playing_group)
            splitter.addWidget(console_container)
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([120, 400])
            splitter.setHandleWidth(6)
            splitter.setStyleSheet(
                "QSplitter::handle { background-color: #444; border: 1px solid #555; }"
            )
            layout.addWidget(splitter, 1)

        if self._basic_mode:
            self.reload_vintage_theme()
    
    def reload_vintage_theme(self) -> None:
        """Apply Vintage Radio cream/brown styling (basic mode / Tools tab)."""
        if not self._basic_mode:
            return

        self.setStyleSheet(f"""
            #deviceDebugRoot {{
                background: transparent;
            }}
            #deviceDebugRoot QGroupBox {{
                font-weight: 800;
                font-size: 13px;
                color: {t.IF_DEVICE_TITLE_FG};
                border: 1px solid {t.IF_CARD_BORDER};
                border-radius: {t.IF_CARD_RADIUS}px;
                margin-top: 12px;
                padding: 8px 10px 10px 10px;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.IF_CARD_INNER_TOP}, stop:1 {t.IF_CARD_INNER_BOT}
                );
            }}
            #deviceDebugRoot QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
            #deviceDebugRoot QLabel {{
                color: {t.IF_DEVICE_TITLE_FG};
                background: transparent;
            }}
            #deviceDebugRoot QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.OUTLINE_BTN_GRAD_TOP},
                    stop:1 {t.OUTLINE_BTN_GRAD_BOT}
                );
                color: {t.TEXT_PRI};
                border: 2px solid {t.LM_SD_BTN_BORDER};
                border-radius: {t.LM_SD_BTN_RADIUS}px;
                padding: 0 10px;
                font-size: {t.IF_DEVICE_BTN_FONT}px;
                font-weight: 800;
                min-height: {t.TOOLS_DEBUG_BTN_H}px;
                max-height: {t.TOOLS_DEBUG_BTN_H}px;
            }}
            #deviceDebugRoot QPushButton:hover {{
                background: {t.LIGHT_BTN_HOVER};
            }}
            #deviceDebugRoot QPushButton:pressed {{
                background: {t.LIGHT_BTN_PRESSED};
            }}
            #deviceDebugRoot QPushButton:disabled {{
                color: #9a8878;
            }}
            #deviceDebugRoot QPushButton#deviceDebugPrimaryBtn {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.IF_INSTALL_BTN_TOP}, stop:0.58 {t.IF_INSTALL_BTN_MID},
                    stop:1 {t.IF_INSTALL_BTN_BOT}
                );
                color: {t.IF_INSTALL_BTN_FG};
                border: 2px solid {t.IF_INSTALL_BTN_BORDER};
            }}
            #deviceDebugRoot QPushButton#deviceDebugPrimaryBtn:hover {{
                background: {t.IF_INSTALL_BTN_MID};
            }}
            #deviceDebugRoot QLineEdit {{
                background: {t.TOOLS_INPUT_BG};
                color: {t.TOOLS_INPUT_FG};
                border: 1px solid {t.TOOLS_INPUT_BORDER};
                border-radius: {t.TOOLS_PATH_FIELD_RADIUS}px;
                padding: 0 10px;
                min-height: {t.TOOLS_DEBUG_BTN_H}px;
                max-height: {t.TOOLS_DEBUG_BTN_H}px;
                font-size: {t.LIBBAR_COMBO_FONT_SIZE}px;
            }}
            #deviceDebugRoot QCheckBox {{
                color: {t.IF_DEVICE_TITLE_FG};
                font-size: {t.IF_DEVICE_META_SIZE}px;
            }}
            #deviceDebugRoot QLabel#deviceDebugMuted {{
                color: {t.TOOLS_MUTED_FG};
                font-size: 10px;
                padding: 4px;
                font-style: italic;
            }}
            #deviceDebugRoot QLabel#deviceDebugMutedSmall {{
                color: {t.TOOLS_MUTED_FG};
                font-size: 9px;
            }}
        """)

        if hasattr(self, "_conn_section"):
            self._conn_section.reload_theme()

        self.run_stop_btn.setStyleSheet(
            self._run_stop_button_stylesheet(running=self._firmware_running)
        )

        console_style = (
            f"QTextEdit#deviceDebugConsole {{ "
            f"background: {t.TOOLS_CONSOLE_BG}; color: {t.TOOLS_CONSOLE_FG}; "
            f"border: none; padding: 6px; }}"
        )
        self.now_playing_label.setStyleSheet(
            f"font-size: 12px; padding: 6px 8px; background: {t.TOOLS_CONSOLE_BG}; "
            f"border: 1px solid {t.TOOLS_CONSOLE_BORDER}; border-radius: {t.TOOLS_PATH_FIELD_RADIUS}px; "
            f"color: {t.TOOLS_CONSOLE_FG};"
        )
        self.console_output.setFont(QtGui.QFont("Consolas", t.TOOLS_LOG_FONT))
        self.console_output.setStyleSheet(console_style)
        pal = self.console_output.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(t.TOOLS_CONSOLE_FG))
        pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(t.TOOLS_CONSOLE_BG))
        self.console_output.setPalette(pal)
        self.connection_status.setStyleSheet(
            f"color: {t.IF_DEVICE_META_FG}; font-size: {t.IF_DEVICE_META_SIZE}px;"
        )
    
    def _pause_streaming(self):
        """Pause the streaming thread so we can use the serial port for a command."""
        if not self._streaming_thread or not self._streaming_thread.is_alive():
            return  # Not streaming, nothing to pause
        self._streaming_resume_event.clear()
        self._streaming_pause_event.set()  # Signal streaming to pause
        # Wait up to 2s for streaming to actually pause (it will set resume_event when paused)
        self._streaming_resume_event.wait(timeout=2.0)
    
    def _resume_streaming(self):
        """Resume the streaming thread after a command completes."""
        self._streaming_pause_event.clear()  # Clear pause signal so streaming continues
        self._streaming_resume_event.clear()

    def _try_reopen_serial_connection(self, port_name: str) -> Any:
        """
        Close and reopen USB serial on the same port path.

        macOS often returns errno 6 (ENXIO / 'Device not configured') when the CDC
        file handle goes stale even though the Pico is still plugged in. Reopening
        usually restores streaming without disconnecting in the UI.
        """
        if not SERIAL_AVAILABLE or not port_name or not self._connected:
            return None
        new_ser = None
        with self._port_lock:
            old = self._serial_connection
            try:
                if old is not None:
                    try:
                        if old.is_open:
                            old.close()
                    except Exception:
                        pass
                new_ser = serial.Serial(
                    port=port_name,
                    baudrate=115200,
                    timeout=0.5,
                    write_timeout=2.0,
                )
                self._serial_connection = new_ser
            except Exception as ex:
                self._serial_connection = None
                self._debug_log(
                    f"Serial reopen after USB I/O error failed: {ex}", "warning"
                )
                return None
        self._debug_log(
            "Serial port reopened after recoverable USB error (stream continues).",
            "info",
        )
        return new_ser

    def _send_serial_command(self, port: str, command: str, timeout: float = 5.0) -> tuple[int, str, str]:
        """
        Send a command via the persistent serial connection.
        Thread-safe: uses port_lock to prevent concurrent commands.
        Pauses streaming if active, sends Ctrl+C to enter REPL, executes command, resumes streaming.
        
        Returns: (returncode, stdout, stderr)
        """
        if not SERIAL_AVAILABLE:
            return (1, "", "pyserial not available")
        
        ser = self._serial_connection
        if not ser or not ser.is_open:
            return (1, "", "Not connected. Use Connect button first.")
        
        # Lock to prevent concurrent commands
        with self._port_lock:
            return self._send_serial_command_locked(ser, command, timeout)
    
    def _send_serial_command_locked(self, ser, command: str, timeout: float) -> tuple[int, str, str]:
        """Internal: execute command with port_lock already held."""
        # Pause streaming so we have exclusive access to the serial port
        was_streaming = self._streaming_thread and self._streaming_thread.is_alive()
        if was_streaming:
            self._pause_streaming()
        
        import time
        try:
            # Clear any existing data
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Send Ctrl+C to interrupt firmware and get to REPL
            for _ in range(2):
                ser.write(b'\x03')
                time.sleep(0.15)
            
            # Wait for REPL prompt
            time.sleep(0.5)
            ser.reset_input_buffer()  # Discard interrupt output
            
            # Send command
            if '\n' in command:
                lines = command.strip().split('\n')
                for i, line in enumerate(lines):
                    if line.strip():
                        ser.write((line + '\r\n').encode('utf-8'))
                        time.sleep(0.15)
                        if i < len(lines) - 1:
                            time.sleep(0.2)
                            if ser.in_waiting > 0:
                                ser.read(ser.in_waiting)  # consume continuation prompt
            else:
                ser.write((command + '\r\n').encode('utf-8'))
            
            # Read response
            output = b""
            start_time = time.time()
            prompt_found = False
            last_data_time = start_time
            
            while time.time() - start_time < timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    output += data
                    last_data_time = time.time()
                    tail = output[-60:] if len(output) >= 60 else output
                    if b'>>> ' in tail:
                        time.sleep(0.2)
                        if ser.in_waiting > 0:
                            output += ser.read(ser.in_waiting)
                        prompt_found = True
                        break
                else:
                    if len(output) > 0 and time.time() - last_data_time > 0.5:
                        break
                time.sleep(0.05)
            
            # Parse output
            output_str = output.decode('utf-8', errors='replace')
            lines = output_str.split('\n')
            result_lines = []
            command_lines = command.strip().split('\n') if command.strip() else []
            
            for line in lines:
                ls = line.strip()
                if ls.startswith('>>>') or ls.startswith('...') or not ls:
                    continue
                # Skip command echo lines
                is_echo = False
                for cmd_line in command_lines:
                    cl = cmd_line.strip()
                    if cl and cl in ls:
                        is_echo = True
                        break
                if not is_echo:
                    result_lines.append(ls)
            
            result = '\n'.join(result_lines).strip()
            
            if not result and not prompt_found:
                debug_output = output_str[:200] if output_str else "(no output)"
                return (1, "", f"No response from device. Raw: {debug_output}")
            
            return (0, result, "")
            
        except serial.SerialException as e:
            return (1, "", f"Serial error: {e}")
        except Exception as e:
            return (1, "", f"Error: {e}")
        finally:
            if was_streaming:
                self._resume_streaming()

    def get_stream_ring_tail(self, limit: int = 200) -> list:
        lim = max(1, min(int(limit), 5000))
        with self._stream_ring_lock:
            lines = list(self._stream_ring)
        return lines[-lim:]

    def run_vrtest_command(self, command: str, timeout: float = 15.0) -> dict:
        """Send a VRTEST line without Ctrl+C; requires firmware with vintage_radio_ipc in the main loop."""
        if not SERIAL_AVAILABLE:
            return {"ok": False, "error": "pyserial_unavailable"}
        ser = self._serial_connection
        if not ser or not ser.is_open or not self._connected:
            return {"ok": False, "error": "not_connected"}
        cmd = command.strip()
        if not cmd:
            return {"ok": False, "error": "empty_command"}
        # MicroPython USB-CDC stdin often expects CRLF; LF-only can leave lines unseen.
        payload_line = "VRTEST " + cmd + "\r\n"
        with self._port_lock:
            was_streaming = self._streaming_thread and self._streaming_thread.is_alive()
            if was_streaming:
                self._pause_streaming()
            try:
                try:
                    if ser.in_waiting:
                        ser.read(ser.in_waiting)
                except Exception:
                    pass
                ser.write(payload_line.encode("utf-8"))
                buf = b""
                start = time.time()
                mark = b"VRTEST_RESULT "
                while time.time() - start < timeout:
                    if ser.in_waiting:
                        buf += ser.read(ser.in_waiting)
                    pos = buf.find(mark)
                    if pos >= 0:
                        # Firmware may print DF:/radio lines before VRTEST_RESULT; feed them
                        # through the normal stream path so the ring + Now Playing stay in sync.
                        preface = buf[:pos]
                        if preface.strip():
                            for raw_line in preface.split(b"\n"):
                                if raw_line.strip():
                                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                                    QtCore.QMetaObject.invokeMethod(
                                        self,
                                        "_display_stream_output",
                                        QtCore.Qt.ConnectionType.QueuedConnection,
                                        QtCore.Q_ARG(str, line),
                                    )
                        rest = buf[pos + len(mark) :]
                        nl = rest.find(b"\n")
                        if nl >= 0:
                            raw_json = rest[:nl].decode("utf-8", errors="replace")
                            try:
                                obj = json.loads(raw_json)
                            except json.JSONDecodeError as e:
                                return {
                                    "ok": False,
                                    "error": "bad_json",
                                    "detail": str(e),
                                    "raw": raw_json[:400],
                                }
                            return {"ok": True, "device": obj}
                    time.sleep(0.02)
                return {
                    "ok": False,
                    "error": "timeout",
                    "raw_tail": buf.decode("utf-8", errors="replace")[-800:],
                    "hint": (
                        "No VRTEST_RESULT from Pico. Use Developer → Deploy MCP / VRTEST support to Pico… "
                        "or copy components/vintage_radio_ipc.py; main.py/main_basic.py must call poll_ipc() "
                        "in the run loop. Boot log should show 'VRTEST IPC: uselect stdin polling enabled'."
                    ),
                }
            except serial.SerialException as e:
                return {"ok": False, "error": "serial", "detail": str(e)}
            except Exception as e:
                return {"ok": False, "error": "exception", "detail": str(e)}
            finally:
                if was_streaming:
                    self._resume_streaming()

    def _list_port_devices(self) -> Tuple[str, ...]:
        """Sorted tuple of serial device paths (stable signature for plug/unplug detection)."""
        if not SERIAL_AVAILABLE:
            return tuple()
        try:
            return tuple(sorted(p.device for p in serial.tools.list_ports.comports()))
        except Exception:
            return tuple()

    @staticmethod
    def _is_rp2040_port(port_info: Any) -> bool:
        """Best-effort: Raspberry Pi Pico / RP2040 USB CDC.

        Requires Raspberry Pi USB vendor id 0x2E8A when the OS reports VID/PID.
        Bluetooth and other virtual COM ports are excluded explicitly.
        """
        hwid = (getattr(port_info, "hwid", "") or "").upper()
        if "BTHENUM" in hwid or "BLUETOOTH" in hwid:
            return False
        desc = (getattr(port_info, "description", "") or "").upper()
        if "BLUETOOTH" in desc:
            return False
        try:
            vid = getattr(port_info, "vid", None)
            if vid is not None:
                return int(vid) == 0x2E8A
        except (TypeError, ValueError):
            pass
        if "2E8A" in hwid:
            return True
        return False

    def _list_rp2040_devices(self) -> Tuple[str, ...]:
        """Sorted tuple of RP2040 serial ports only."""
        if not SERIAL_AVAILABLE:
            return tuple()
        try:
            return tuple(
                sorted(
                    p.device
                    for p in serial.tools.list_ports.comports()
                    if self._is_rp2040_port(p)
                )
            )
        except Exception:
            return tuple()

    def _computed_presence_for_led(self) -> bool:
        """Whether the Device Setup LED should show 'device available'."""
        bootsel = SDManager.is_rp2040_bootsel_present()
        if self._basic_mode:
            has_ports = len(self._list_rp2040_devices()) > 0
        else:
            has_ports = len(self._list_port_devices()) > 0
        if self._connected:
            try:
                open_port = (
                    self._serial_connection.port
                    if self._serial_connection is not None
                    else None
                )
            except Exception:
                open_port = None
            # Presence while connected: the port must still exist in the OS list.
            # In basic mode do not require the open port to appear in the RP2040-only
            # list (VID is sometimes missing from hwid on Windows, which would falsely
            # turn the LED off despite an active session).
            all_devs = self._list_port_devices()
            if open_port is not None and str(open_port) not in all_devs:
                return False
            return True
        return has_ports or bootsel

    def _update_device_presence_led(self, *, force_emit: bool = False) -> None:
        effective = self._computed_presence_for_led()
        if force_emit or self._last_presence_emitted != effective:
            self._last_presence_emitted = effective
            self.device_presence_changed.emit(effective)

    def _poll_serial_presence(self) -> None:
        """Periodic poll so plug/unplug, BOOTSEL drive, and LED update without clicking Scan Ports."""
        cur_ports = self._list_port_devices()
        cur_bootsel = SDManager.is_rp2040_bootsel_present()
        cur = (cur_ports, cur_bootsel)
        prev = self._poll_usb_signature
        if cur != prev:
            self._poll_usb_signature = cur
            self._poll_signature = cur_ports
            if prev is not None and SERIAL_AVAILABLE:
                self._scan_ports(from_auto_poll=True)
            else:
                self._update_device_presence_led(force_emit=True)
        else:
            self._update_device_presence_led()

    def _scan_ports(self, *, from_auto_poll: bool = False) -> None:
        """Scan for available COM ports using serial.tools.list_ports (no mpremote needed)."""
        if not from_auto_poll:
            self._debug_log("Starting port scan...", "info")
        preserve = self.port_combo.currentData()
        self.port_combo.clear()

        if not SERIAL_AVAILABLE:
            self._log("Cannot scan ports: pyserial not available. Install with: pip install pyserial", "error")
            self._poll_signature = tuple()
            self._poll_usb_signature = (tuple(), SDManager.is_rp2040_bootsel_present())
            self._update_device_presence_led(force_emit=True)
            return

        try:
            ports = serial.tools.list_ports.comports()
            if not from_auto_poll:
                self._debug_log(f"Found {len(ports)} serial port(s)", "info")

            rp2040_index: Optional[int] = None
            for port_info in ports:
                port_name = port_info.device
                description = f"{port_info.description or 'Unknown'} {port_info.hwid or ''}".strip()
                self.port_combo.addItem(f"{port_name} - {description}", port_name)
                if self._basic_mode and rp2040_index is None and self._is_rp2040_port(port_info):
                    rp2040_index = self.port_combo.count() - 1
                if not from_auto_poll:
                    self._debug_log(f"Added port: {port_name} - {description}", "info")

            restored_preserve = False
            if preserve:
                for i in range(self.port_combo.count()):
                    if self.port_combo.itemData(i) == preserve:
                        self.port_combo.setCurrentIndex(i)
                        restored_preserve = True
                        break

            if self._basic_mode and rp2040_index is not None:
                # In basic mode we always prefer an attached RP2040 over unrelated serial devices.
                if not restored_preserve or self.port_combo.currentIndex() != rp2040_index:
                    self.port_combo.setCurrentIndex(rp2040_index)

            if self.port_combo.count() == 0:
                self.port_combo.addItem("(No COM ports found)", None)
                if not from_auto_poll:
                    self._log("No COM ports found. Connect your Pico via USB.", "warning")
            elif not from_auto_poll:
                self._log(f"Found {self.port_combo.count()} device(s)", "info")
        except Exception as e:
            error_msg = f"Error scanning ports: {e}\n{traceback.format_exc()}"
            self._debug_log(error_msg, "error")
            self._log(f"Error scanning ports: {e}", "error")
            if self.port_combo.count() == 0:
                self.port_combo.addItem("(No COM ports found)", None)
        self._poll_signature = self._list_port_devices()
        self._poll_usb_signature = (self._poll_signature, SDManager.is_rp2040_bootsel_present())
        self._update_device_presence_led(force_emit=True)

    def _toggle_connection(self) -> None:
        """Connect or disconnect from the device."""
        if self._connected:
            self._disconnect()
        else:
            self._connect()
    
    def _connect(self) -> None:
        """Connect to the device."""
        # Check if already connected
        if self._connected:
            self._log("Already connected. Disconnect first to reconnect.", "warning")
            return
        
        if "connect" in self._active_operations:
            self._debug_log("Connect operation already in progress, ignoring", "warning")
            return
        
        port = self.port_combo.currentData()
        if not port:
            self._log("Please select a COM port first", "error")
            return
        
        # Verify port still exists (e.g. after device reset it may have a new path on macOS)
        if SERIAL_AVAILABLE:
            try:
                available = [p.device for p in serial.tools.list_ports.comports()]
                if available and str(port) not in available:
                    self._scan_ports()
                    self._log(
                        f"Port {port} no longer exists (device may have reset). "
                        "Scanned for ports — please select the device again and click Connect.",
                        "warning"
                    )
                    return
            except Exception as e:
                self._debug_log(f"Could not verify port: {e}", "warning")
        
        if not SERIAL_AVAILABLE:
            self._log("pyserial not available. Install with: pip install pyserial", "error")
            return
        
        # Ensure buttons are in correct state before starting
        try:
            self.connect_btn.setEnabled(True)  # Re-enable in case it was stuck
        except:
            pass
        
        self._active_operations.add("connect")
        self._debug_log(f"Starting connection to {port}...", "info")
        self._log(f"Connecting to {port}...", "info")
        
        try:
            self.connect_btn.setEnabled(False)
        except Exception as e:
            self._debug_log(f"Error disabling connect button: {e}", "error")
            self._active_operations.discard("connect")
            return
        
        def connect_thread():
            try:
                import time
                time.sleep(0.3)
                
                if "connect" not in self._active_operations:
                    self._debug_log("Connection cancelled", "info")
                    return
                
                # Open serial port and KEEP IT OPEN for the entire session
                # This is how Thonny works - one persistent connection
                try:
                    ser = serial.Serial(
                        port=port,
                        baudrate=115200,
                        timeout=0.5,
                        write_timeout=2.0
                    )
                    # Store as persistent connection - used by ALL operations
                    self._serial_connection = ser
                    self._debug_log(f"Serial port {port} opened and stored as persistent connection", "info")
                    port_val = str(port) if port else ""
                    returncode_val = 0
                    stdout_val = "Connected! (Persistent serial connection opened)"
                    stderr_val = ""
                except serial.SerialException as e:
                    self._debug_log(f"Failed to open serial port: {e}", "error")
                    self._serial_connection = None
                    port_val = str(port) if port else ""
                    returncode_val = 1
                    stdout_val = ""
                    stderr_val = f"Failed to open serial port: {e}"
                
                # Update UI on main thread - capture values and schedule callback
                
                # Use QMetaObject.invokeMethod to ensure this runs on main thread
                # This is the proper way to call UI updates from background threads
                try:
                    QtCore.QMetaObject.invokeMethod(
                        self,
                        "_execute_ui_update",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(str, port_val),
                        QtCore.Q_ARG(int, returncode_val),
                        QtCore.Q_ARG(str, stdout_val),
                        QtCore.Q_ARG(str, stderr_val)
                    )
                except Exception as invoke_error:
                    error_msg = f"Error invoking UI update: {invoke_error}\n{traceback.format_exc()}"
                    self._debug_log(error_msg, "error")
                    # Fallback: try to log error (but don't access UI directly from thread)
                    try:
                        print(f"[DeviceDebug] Connection completed but UI update failed: {invoke_error}")
                    except:
                        pass
                finally:
                    # Always clear the operation, even if invokeMethod failed
                    self._active_operations.discard("connect")
                    self._debug_log("connect operation cleared from _active_operations", "info")
                
            except subprocess.TimeoutExpired:
                self._debug_log("Connection timed out after 10 seconds - device may be unresponsive", "error")
                # Clear operation immediately
                self._active_operations.discard("connect")
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_connection_timeout",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
            except KeyboardInterrupt:
                # User cancelled (shouldn't happen in background thread, but handle it)
                self._debug_log("Connection cancelled by user", "warning")
                self._active_operations.discard("connect")
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_connection_error",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, "Connection cancelled")
                )
            except Exception as e:
                error_msg = f"Connection error: {e}\n{traceback.format_exc()}"
                self._debug_log(error_msg, "error")
                # Clear operation immediately
                self._active_operations.discard("connect")
                error_msg_val = str(e)
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_connection_error",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, error_msg_val)
                )
        
        threading.Thread(target=connect_thread, daemon=True).start()
    
    def _reset_connection(self) -> None:
        """Forcefully reset the connection - close everything and release port."""
        self._log("Resetting connection...", "info")
        
        # Stop streaming
        self._stop_streaming_forcefully()
        
        # Close persistent serial connection
        if self._serial_connection:
            try:
                if self._serial_connection.is_open:
                    self._serial_connection.close()
            except:
                pass
            self._serial_connection = None
        
        self._connected = False
        self._active_operations.clear()

        import time
        time.sleep(1.0)

        self._restore_disconnected_state()
        self._log("Connection reset complete. You can now reconnect.", "info")
        self._poll_signature = self._list_port_devices()
        self._update_device_presence_led(force_emit=True)
    
    def _disconnect(self) -> None:
        """Disconnect from the device - close the persistent serial connection."""
        self._debug_log("Disconnecting...", "info")
        
        # Stop streaming if active (but don't close port yet - we do that below)
        self._stop_streaming = True
        self._stop_output = True
        self._streaming_pause_event.set()  # Unblock streaming if it's paused
        
        if self._streaming_thread and self._streaming_thread.is_alive():
            self._streaming_thread.join(timeout=3.0)
        
        # Close the persistent serial connection
        if self._serial_connection:
            try:
                if self._serial_connection.is_open:
                    self._serial_connection.close()
                    self._debug_log("Persistent serial connection closed", "info")
            except Exception as e:
                self._debug_log(f"Error closing serial connection: {e}", "warning")
            finally:
                self._serial_connection = None
        
        self._connected = False
        self._active_operations.clear()
        self._restore_disconnected_state()
        self._log("Disconnected", "info")
        self._poll_signature = self._list_port_devices()
        self._poll_usb_signature = (
            self._poll_signature,
            SDManager.is_rp2040_bootsel_present(),
        )
        self._update_device_presence_led(force_emit=True)

    @QtCore.pyqtSlot(str, int, str, str)
    def _execute_ui_update(self, port: str, returncode: int, stdout: str, stderr: str):
        """Execute UI update on main thread - called via QMetaObject.invokeMethod."""
        try:
            self._debug_log(f"_execute_ui_update called on main thread: port={port}, returncode={returncode}", "info")
            
            # Validate that widget still exists and is valid
            if not self or not hasattr(self, 'connect_btn'):
                self._debug_log("Widget is invalid or destroyed, skipping UI update", "warning")
                return
            if returncode == 0:
                self._debug_log("Connection successful, updating UI to connected state", "info")
                self._connected = True
                self.connect_btn.setText("Disconnect")
                self.connect_btn.setEnabled(True)
                self._conn_section.set_connected(True)
                self._conn_section.set_meta_text(f"Connected to {port}")
                
                # Enable all action buttons
                self.restart_firmware_btn.setEnabled(True)
                self.soft_reset_btn.setEnabled(True)
                self.get_status_btn.setEnabled(True)
                self.list_files_btn.setEnabled(True)
                self.view_debug_log_btn.setEnabled(True)
                self.check_firmware_btn.setEnabled(True)
                self.send_btn.setEnabled(True)
                self.stream_output_btn.setEnabled(True)
                self.reset_connection_btn.setEnabled(True)
                self.run_stop_btn.setEnabled(True)
                
                # Set "now playing" to waiting state (parsed from stream, not from Ctrl+C)
                self.now_playing_label.setText(
                    f"<span style='color: {self._now_playing_color('artist')};'>"
                    "Listening for playback info from stream...</span>"
                )
                
                # Auto-start streaming so user sees logs immediately
                self._stop_streaming = False
                self._stop_output = False
                if not self._basic_mode:
                    self.stream_output_btn.setText("Stop Streaming")
                self._log("Auto-starting output stream...", "info")
                self._start_streaming()
                # Re-bind DB from manager (if getter) and re-scan console after reconnect / SD work.
                self.refresh_library_db_and_now_playing()
                # Basic mode: assume main.py is already running when opening serial (matches Run/Stop UX)
                if self._basic_mode:
                    self._set_run_stop_button_state(running=True, enabled=True)
                
                # Disable port selection
                self.port_combo.setEnabled(False)
                self.scan_btn.setEnabled(False)
                
                # Verify buttons are actually enabled
                soft_reset_enabled = self.soft_reset_btn.isEnabled()
                get_status_enabled = self.get_status_btn.isEnabled()
                list_files_enabled = self.list_files_btn.isEnabled()
                send_enabled = self.send_btn.isEnabled()
                self._debug_log(f"Button states verified - Soft Reset: {soft_reset_enabled}, Get Status: {get_status_enabled}, List Files: {list_files_enabled}, Send: {send_enabled}", "info")
                
                self._log(f"✓ Connected to {port}", "success")
                if stdout and stdout.strip():
                    self._log(stdout.strip(), "output")
                
                # NOTE: Do NOT check power sense here - it sends Ctrl+C and interrupts firmware.
                # User can check/toggle power sense manually from the checkbox.
                
                # Final verification - ensure buttons are still enabled
                final_soft_reset = self.soft_reset_btn.isEnabled()
                final_get_status = self.get_status_btn.isEnabled()
                final_list_files = self.list_files_btn.isEnabled()
                final_send = self.send_btn.isEnabled()
                self._debug_log(f"Final button states - Soft Reset: {final_soft_reset}, Get Status: {final_get_status}, List Files: {final_list_files}, Send: {final_send}", "info")
                self._debug_log(f"Connection state: _connected={self._connected}", "info")
                self._debug_log("UI updated to connected state successfully - all buttons should be enabled", "info")
                
                # Force a repaint to ensure UI updates
                self.update()
                self.repaint()  # Force immediate repaint
                self._update_device_presence_led(force_emit=True)
            else:
                self._debug_log(f"Connection failed with return code {returncode}", "error")
                self._log(f"Connection failed: {stderr or stdout}", "error")
                # If port is missing (e.g. after device reset, macOS re-enumerates with new path)
                err_text = (stderr or stdout or "").lower()
                if "no such file or directory" in err_text or "could not open port" in err_text:
                    self._scan_ports()
                    self._log(
                        "Port no longer available (device may have reset or been unplugged). "
                        "Scanned for ports — please select the device again and click Connect.",
                        "warning"
                    )
                self._restore_disconnected_state()
        except Exception as e:
            error_msg = f"Error in _execute_ui_update: {e}\n{traceback.format_exc()}"
            self._debug_log(error_msg, "error")
            self._log(f"Error updating UI: {e}", "error")
            # Try to preserve button states even on error
            try:
                # If we got partway through, try to keep buttons enabled
                if self._connected:
                    self._debug_log("Attempting to preserve connected state despite error", "warning")
                    self.soft_reset_btn.setEnabled(True)
                    self.get_status_btn.setEnabled(True)
                    self.list_files_btn.setEnabled(True)
                    self.view_debug_log_btn.setEnabled(True)
                    self.check_firmware_btn.setEnabled(True)
                    self.send_btn.setEnabled(True)
                    self.stream_output_btn.setEnabled(True)
                else:
                    self._restore_disconnected_state()
            except:
                pass
        finally:
            self._active_operations.discard("connect")
            self._debug_log("_execute_ui_update completed", "info")
    
    def _restore_disconnected_state(self) -> None:
        """Restore UI to disconnected state - ensures all buttons are in correct state."""
        try:
            self._debug_log("Restoring disconnected state", "info")
            # Stop streaming if active
            self._stop_streaming_forcefully()
            self.stream_output_btn.setText("Start Streaming")
            self.stream_output_btn.setEnabled(False)
            
            self.connect_btn.setText("Connect")
            self.connect_btn.setEnabled(True)
            self._conn_section.set_connected(False)
            self._conn_section.set_meta_text("Not connected")
            self.restart_firmware_btn.setEnabled(False)
            self.soft_reset_btn.setEnabled(False)
            self.get_status_btn.setEnabled(False)
            self.list_files_btn.setEnabled(False)
            self.view_debug_log_btn.setEnabled(False)
            self.check_firmware_btn.setEnabled(False)
            self.send_btn.setEnabled(False)
            self.stream_output_btn.setEnabled(False)
            self.stream_output_btn.setText("Start Streaming")
            self.reset_connection_btn.setEnabled(False)
            self._set_run_stop_button_state(running=False, enabled=False)
            
            self.now_playing_label.setText("Not connected")
            self._current_device_mode = ""
            self._current_device_source = ""
            self._current_shuffle_type = ""
            self._current_track_title = ""
            self._current_track_artist = ""
            self._current_basic_folder = None
            self._current_basic_track = None
            
            self.port_combo.setEnabled(True)
            self.scan_btn.setEnabled(True)
            self._debug_log("Disconnected state restored", "info")
        except Exception as e:
            self._debug_log(f"Error restoring disconnected state: {e}\n{traceback.format_exc()}", "error")
    
    def _send_command(self) -> None:
        """Send a command to the device."""
        if not self._connected:
            self._log("Not connected. Please connect first.", "error")
            return
        
        command = self.cmd_input.text().strip()
        if not command:
            return
        
        if command == "help":
            self._show_help()
            self.cmd_input.clear()
            return
        
        if command.lower().strip() in ("check_amplifier", "_check_amplifier"):
            # Handle both with and without underscore for user convenience
            # This is a GUI command, not sent to the device
            self._check_amplifier()
            self.cmd_input.clear()
            return
        
        # Handle test_play_track command (intercept and send as proper Python)
        if command.strip().startswith("test_play_track"):
            # Parse: test_play_track(1, 1) or test_play_track 1 1
            try:
                import re
                match = re.match(r'test_play_track\s*\(?\s*(\d+)\s*,\s*(\d+)\s*\)?', command)
                if match:
                    folder = int(match.group(1))
                    track = int(match.group(2))
                    # Send as proper Python command
                    py_cmd = f"from components.dfplayer_hardware import DFPlayerHardware; hw = DFPlayerHardware(); hw.test_play_track({folder}, {track})"
                    command = py_cmd
                else:
                    self._log("Usage: test_play_track(1, 1) or test_play_track 1 1", "error")
                    self.cmd_input.clear()
                    return
            except Exception as e:
                self._log(f"Error parsing test_play_track: {e}", "error")
                self.cmd_input.clear()
                return
        
        op_id = f"cmd_{id(command)}"
        if op_id in self._active_operations:
            self._debug_log("Command already executing, ignoring", "warning")
            return
        
        live_vrtest = live_vrtest_arg_for_command(command)
        
        self._active_operations.add(op_id)
        route = "VRTEST (live)" if live_vrtest else "REPL (Ctrl+C)"
        self._log(f">>> {command}  [{route}]", "command")
        self.cmd_input.clear()
        
        port = self.port_combo.currentData()
        self._debug_log(f"Sending command to {port}: {command[:100]} via {route}", "info")
        
        def run_command():
            try:
                if not SERIAL_AVAILABLE:
                    self._active_operations.discard(op_id)
                    QtCore.QMetaObject.invokeMethod(
                        self,
                        "_display_command_result",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(int, 1),
                        QtCore.Q_ARG(str, ""),
                        QtCore.Q_ARG(str, "pyserial not available."),
                        QtCore.Q_ARG(int, 0)
                    )
                    return
                
                if live_vrtest:
                    result = self.run_vrtest_command(live_vrtest, timeout=10)
                    self._active_operations.discard(op_id)
                    if not result.get("ok"):
                        err = result.get("error", "vrtest_failed")
                        detail = result.get("detail") or result.get("hint") or ""
                        stderr = "{}: {}".format(err, detail).strip(": ")
                        QtCore.QMetaObject.invokeMethod(
                            self,
                            "_display_command_result",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(int, 1),
                            QtCore.Q_ARG(str, ""),
                            QtCore.Q_ARG(str, stderr),
                            QtCore.Q_ARG(int, 0),
                        )
                        return
                    device = result.get("device") or {}
                    stdout = format_live_vrtest_result(device)
                    rc = 0 if device.get("ok") else 1
                    QtCore.QMetaObject.invokeMethod(
                        self,
                        "_display_command_result",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(int, rc),
                        QtCore.Q_ARG(str, stdout),
                        QtCore.Q_ARG(str, ""),
                        QtCore.Q_ARG(int, 0),
                    )
                    return
                
                # Use _send_serial_command which handles pause/resume of streaming
                returncode, stdout, stderr = self._send_serial_command(port, command, timeout=10)
                
                self._active_operations.discard(op_id)
                
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_command_result",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(int, returncode),
                    QtCore.Q_ARG(str, stdout.strip() if stdout else ""),
                    QtCore.Q_ARG(str, stderr.strip() if stderr else ""),
                    QtCore.Q_ARG(int, 0)
                )
                
            except Exception as e:
                error_msg = f"Error executing command: {e}\n{traceback.format_exc()}"
                self._debug_log(error_msg, "error")
                self._active_operations.discard(op_id)
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_command_error",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, str(e))
                )
        
        threading.Thread(target=run_command, daemon=True).start()
    
    def _soft_reset(self) -> None:
        """Perform a soft reset using mpremote's reset command."""
        if not self._connected:
            return
        
        if "soft_reset" in self._active_operations:
            self._debug_log("Soft reset already in progress, ignoring", "warning")
            return
        
        self._active_operations.add("soft_reset")
        port = self.port_combo.currentData()
        self._debug_log(f"Starting soft reset on {port}...", "info")
        self._log("Performing soft reset...", "info")
        
        def reset():
            try:
                self._debug_log("Sending soft reset via serial...", "info")
                returncode, stdout, stderr = self._send_serial_command(
                    port, "import machine; machine.soft_reset()", timeout=3
                )
                
                self._active_operations.discard("soft_reset")
                
                stdout_val = stdout.strip() if stdout else ""
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_soft_reset_result",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, stdout_val)
                )
            except subprocess.TimeoutExpired as e:
                # Timeout is actually expected/normal for soft_reset - device resets immediately
                self._debug_log(f"Soft reset command timed out (this is normal - device resets immediately): {e}", "info")
                # Clear operation on timeout (which is expected for soft_reset)
                self._active_operations.discard("soft_reset")
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_soft_reset_timeout_success",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
            except Exception as e:
                error_msg = f"Reset error: {e}\n{traceback.format_exc()}"
                self._debug_log(error_msg, "error")
                # Clear operation on error
                self._active_operations.discard("soft_reset")
                error_msg_val = str(e)
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_soft_reset_error",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, error_msg_val)
                )
        
        threading.Thread(target=reset, daemon=True).start()
    
    def _restart_firmware(self) -> None:
        """Restart main.py on the device - use this if device stops working after connecting."""
        if not self._connected:
            self._log("Not connected. Please connect first.", "error")
            return
        
        if "restart_firmware" in self._active_operations:
            self._debug_log("Restart firmware already in progress, ignoring", "warning")
            return
        
        self._active_operations.add("restart_firmware")
        port = self.port_combo.currentData()
        self._log("Restarting firmware (main.py)...", "info")
        self._debug_log(f"Restarting firmware on {port}...", "info")
        
        def restart():
            try:
                # Use soft_reset which cleanly restarts the Pico and re-runs main.py.
                # The device will disconnect/timeout — that is expected success.
                cmd = "import machine; machine.soft_reset()"
                
                returncode, stdout, stderr = self._send_serial_command(port, cmd, timeout=5)
                self._active_operations.discard("restart_firmware")
                
                # Any response (or lack thereof) after soft_reset means it worked.
                # The device reboots and runs main.py automatically.
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_restart_firmware_result",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, "Device restarting — firmware will re-run main.py automatically")
                )
            except Exception as e:
                self._active_operations.discard("restart_firmware")
                # Timeout or disconnect is expected — the device rebooted successfully
                error_str = str(e).lower()
                if "timeout" in error_str or "no response" in error_str or "disconnect" in error_str:
                    QtCore.QMetaObject.invokeMethod(
                        self,
                        "_display_restart_firmware_result",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(str, "Device restarting — firmware will re-run main.py automatically")
                    )
                else:
                    self._debug_log(f"Error restarting firmware: {e}\n{traceback.format_exc()}", "error")
                    QtCore.QMetaObject.invokeMethod(
                        self,
                        "_display_restart_firmware_error",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(str, str(e)[:200])
                    )
        
        threading.Thread(target=restart, daemon=True).start()
    
    def _get_status(self) -> None:
        """Get device status."""
        if not self._connected:
            return
        
        if "get_status" in self._active_operations:
            self._debug_log("Get status already in progress, ignoring", "warning")
            return
        
        self._active_operations.add("get_status")
        port = self.port_combo.currentData()
        self._debug_log(f"Getting status from {port}...", "info")
        self._log("Getting device status...", "info")
        
        commands = [
            "import sys; print(f'MicroPython: {sys.version}')",
            "import machine; print(f'Frequency: {machine.freq()} Hz')",
            "import gc; gc.collect(); print(f'Free RAM: {gc.mem_free()} bytes ({gc.mem_free()//1024} KB)')",
            "import os; s=os.statvfs('/'); print(f'Flash: {s[0]*s[3]//1024}KB free / {s[0]*s[2]//1024}KB total')",
        ]
        
        def get_status():
            try:
                for i, cmd in enumerate(commands):
                    try:
                        self._debug_log(f"Executing status command {i+1}/{len(commands)}", "info")
                        returncode, stdout, stderr = self._send_serial_command(port, cmd, timeout=5)
                        self._debug_log(f"Status command {i+1} return code: {returncode}", "info")
                        if returncode == 0 and stdout.strip():
                            stdout_val = stdout.strip()
                            # Use QMetaObject.invokeMethod to ensure UI update happens on main thread
                            QtCore.QMetaObject.invokeMethod(
                                self,
                                "_display_status_output",
                                QtCore.Qt.ConnectionType.QueuedConnection,
                                QtCore.Q_ARG(str, stdout_val)
                            )
                    except subprocess.TimeoutExpired:
                        self._debug_log(f"Status command {i+1} timed out", "warning")
                    except Exception as e:
                        error_msg = f"Error in status command {i+1}: {e}\n{traceback.format_exc()}"
                        self._debug_log(error_msg, "error")
                        error_msg_val = str(e)
                        # Use QMetaObject.invokeMethod for thread-safe UI update
                        QtCore.QMetaObject.invokeMethod(
                            self,
                            "_display_status_error",
                            QtCore.Qt.ConnectionType.QueuedConnection,
                            QtCore.Q_ARG(str, error_msg_val)
                        )
            finally:
                self._active_operations.discard("get_status")
        
        threading.Thread(target=get_status, daemon=True).start()
    
    # Now-playing info is parsed non-intrusively from the stream output.
    # No query-device method needed (it used to interrupt firmware via Ctrl+C).
    
    def _list_files(self) -> None:
        """List files on the device."""
        if not self._connected:
            return
        
        if "list_files" in self._active_operations:
            self._debug_log(f"List files already in progress, ignoring. Active operations: {self._active_operations}", "warning")
            # Force clear if it's been stuck for too long (safety mechanism)
            # This shouldn't normally happen, but helps recover from stuck operations
            return
        
        self._active_operations.add("list_files")
        port = self.port_combo.currentData()
        self._debug_log(f"Listing files on {port}...", "info")
        self._log("Listing files...", "info")
        
        def list_files():
            try:
                cmd = "import os; [print(n, '[DIR]' if os.stat(n)[0]&0x4000 else str(os.stat(n)[6])+'B') for n in sorted(os.listdir('.'))]"
                self._debug_log(f"Executing: list files via serial", "info")
                returncode, stdout, stderr = self._send_serial_command(port, cmd, timeout=15)
                
                self._active_operations.discard("list_files")
                
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_list_files_result",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(int, returncode),
                    QtCore.Q_ARG(str, stdout.strip() if stdout else ""),
                    QtCore.Q_ARG(str, stderr.strip() if stderr else "")
                )
            except subprocess.TimeoutExpired as e:
                self._debug_log(f"List files timed out after 15 seconds: {e}", "error")
                # Clear operation immediately
                self._active_operations.discard("list_files")
                self._debug_log("list_files operation cleared after timeout", "info")
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_list_files_timeout",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
            except Exception as e:
                error_msg = f"Error listing files: {e}\n{traceback.format_exc()}"
                self._debug_log(error_msg, "error")
                # Clear operation immediately
                self._active_operations.discard("list_files")
                self._debug_log("list_files operation cleared after error", "info")
                error_msg_val = str(e)
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_list_files_error",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, error_msg_val)
                )
        
        threading.Thread(target=list_files, daemon=True).start()
    
    def _clear_console(self) -> None:
        """Clear the console output."""
        self.console_output.clear()
    
    def _view_debug_log(self) -> None:
        """Export the current session's console output to a file on the PC."""
        from datetime import datetime
        
        console_text = self.console_output.toPlainText()
        if not console_text.strip():
            self._log("Console is empty - nothing to save.", "info")
            return
        
        default_name = f"debug_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Debug Session Log", default_name, "Log Files (*.log);;Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(console_text)
            self._log(f"Session log saved to: {file_path}", "success")
        except Exception as e:
            self._log(f"Failed to save log: {e}", "error")
    
    # Debug log display slots removed — session logs are now saved to PC via Save Session Log.
    
    def _check_firmware_status(self) -> None:
        """Check if firmware is running and show recent activity using single-line commands."""
        if not self._connected:
            self._log("Not connected. Please connect first.", "error")
            return
        
        if "check_firmware" in self._active_operations:
            self._debug_log("Firmware check already in progress, ignoring", "warning")
            return
        
        self._active_operations.add("check_firmware")
        port = self.port_combo.currentData()
        if not port:
            text = self.port_combo.currentText().strip()
            if text and text.startswith("COM"):
                port = text.split()[0] if ' ' in text else text
            else:
                self._log("No port selected", "error")
                self._active_operations.discard("check_firmware")
                return
        
        # Each command is a single line to avoid multi-line serial issues
        commands = [
            ("Files", "import os; f=os.listdir(); print('main.py:','main.py' in f,', radio_core.py:','radio_core.py' in f)"),
            ("VintageRadio", "import os; print(os.listdir('VintageRadio'))"),
            ("Flash", "import os; s=os.statvfs('/'); print(str(s[0]*s[3]//1024)+'KB free /',str(s[0]*s[2]//1024)+'KB total')"),
            ("RAM", "import gc; gc.collect(); print(str(gc.mem_free()//1024)+'KB free')"),
        ]
        
        def check_firmware():
            try:
                self._log_safe("=== Firmware Status ===", "info")
                for label, cmd in commands:
                    try:
                        returncode, stdout, stderr = self._send_serial_command(port, cmd, timeout=5)
                        if returncode == 0 and stdout.strip():
                            self._log_safe(f"{label}: {stdout.strip()}", "output")
                        else:
                            self._log_safe(f"{label}: (no response)", "warning")
                    except Exception as e:
                        self._log_safe(f"{label}: error - {e}", "error")
                self._log_safe("=== End Status ===", "info")
            finally:
                self._active_operations.discard("check_firmware")
        
        threading.Thread(target=check_firmware, daemon=True).start()
    
    def _log_safe(self, msg: str, level: str = "info") -> None:
        """Thread-safe log helper — posts _log call to the main thread."""
        # Encode level into the string so the slot can unpack it
        QtCore.QMetaObject.invokeMethod(
            self,
            "_display_safe_log_msg",
            QtCore.Qt.ConnectionType.QueuedConnection,
            QtCore.Q_ARG(str, f"{level}|||{msg}")
        )
    
    def _stop_streaming_forcefully(self) -> None:
        """Stop the streaming thread. Does NOT close the persistent serial connection."""
        self._stop_streaming = True
        self._stop_output = True
        self._streaming_pause_event.set()  # Unblock if paused
        
        # Wait for thread to finish
        if self._streaming_thread and self._streaming_thread.is_alive():
            self._streaming_thread.join(timeout=3.0)
            if self._streaming_thread.is_alive():
                self._debug_log("Warning: Streaming thread did not stop within timeout", "warning")
        
        self._stop_output = False  # Reset for next start

    def _run_stop_button_stylesheet(self, *, running: bool) -> str:
        """Start/Stop styling — rounded like other debugger buttons."""
        radius = t.LM_SD_BTN_RADIUS
        btn_h = t.TOOLS_DEBUG_BTN_H
        font = t.IF_DEVICE_BTN_FONT
        base = (
            f"min-height:{btn_h}px; max-height:{btn_h}px; "
            f"border-radius:{radius}px; font-weight:800; "
            f"padding:0 10px; font-size:{font}px;"
        )
        if running:
            return (
                f"QPushButton#vrRunStopBtn {{ background-color:#c62828; color:#fff7eb; "
                f"border:2px solid #8b1a1a; {base} }}"
                f"QPushButton#vrRunStopBtn:hover {{ background-color:#b71c1c; }}"
                f"QPushButton#vrRunStopBtn:disabled {{ background-color:#c62828; color:#fff7eb; }}"
            )
        return (
            f"QPushButton#vrRunStopBtn {{ background-color:#4CAF50; color:#fff7eb; "
            f"border:2px solid #2e7d32; {base} }}"
            f"QPushButton#vrRunStopBtn:hover {{ background-color:#43a047; }}"
            f"QPushButton#vrRunStopBtn:disabled {{ background-color:#4CAF50; color:#fff7eb; }}"
        )

    def _set_run_stop_button_state(self, *, running: bool, enabled: Optional[bool] = None) -> None:
        """Keep Run/Stop button text, style and enablement in sync."""
        self._firmware_running = bool(running)
        # In basic mode while connected, always leave the control enabled so Qt does not
        # paint it with the global disabled (grey) palette; streaming/flash paths were
        # leaving enabled=False and wiping the green/red styling.
        if self._connected and self._basic_mode:
            self.run_stop_btn.setEnabled(True)
        elif enabled is not None:
            self.run_stop_btn.setEnabled(bool(enabled))
        else:
            self.run_stop_btn.setEnabled(False)
        if self._firmware_running:
            self.run_stop_btn.setText("Stop")
        else:
            self.run_stop_btn.setText("Start")
        self.run_stop_btn.setStyleSheet(self._run_stop_button_stylesheet(running=self._firmware_running))
    
    def _toggle_run_stop(self) -> None:
        """Start or stop the firmware (basic mode Thonny-style button).
        Also auto-starts streaming when firmware starts, and stops it when firmware stops."""
        if not self._connected:
            self._log("Not connected. Please connect first.", "error")
            return
        if self._firmware_running:
            self._log("Stopping firmware (interrupt + DFPlayer stop)...", "info")
            self._stop_streaming_forcefully()
            port_data = self.port_combo.currentData()
            port = (
                str(port_data).strip()
                if port_data is not None and str(port_data).strip()
                else self.port_combo.currentText().strip()
            )
            # _send_serial_command already sends Ctrl+C and opens REPL; then run df_stop on __main__.firmware
            stop_cmd = (
                "try:\n"
                " import sys\n"
                " m=sys.modules.get('__main__',None)\n"
                " f=getattr(m,'firmware',None) if m else None\n"
                " if f is not None and getattr(f,'hw',None) is not None:\n"
                "  f.hw._df_stop()\n"
                "except Exception as e:\n"
                " print('device_stop_err',e)\n"
            )
            if port:
                try:
                    rc, out, err = self._send_serial_command(port, stop_cmd, timeout=6.0)
                    if rc != 0 and err:
                        self._log("Stop: {}".format(err), "warning")
                    elif out:
                        self._debug_log("Stop REPL output: {}".format(out[:300]), "info")
                except Exception as ex:
                    self._log("Stop command failed: {}".format(ex), "warning")
            else:
                self._log("Stop: no serial port selected", "error")
            self._set_run_stop_button_state(running=False, enabled=True)
        else:
            self._log("Starting firmware...", "info")
            self._restart_firmware()
            self._set_run_stop_button_state(running=True, enabled=True)
            # Auto-start streaming so output appears in the console
            is_streaming = self._streaming_thread and self._streaming_thread.is_alive()
            if not is_streaming:
                QtCore.QTimer.singleShot(1500, self._auto_start_streaming_after_run)

    def _auto_start_streaming_after_run(self) -> None:
        """Start streaming after a short delay to let firmware boot."""
        is_streaming = self._streaming_thread and self._streaming_thread.is_alive()
        if self._firmware_running and self._connected and not is_streaming:
            self._toggle_streaming()

    def _toggle_streaming(self) -> None:
        """Toggle real-time output streaming from the Pico."""
        if not self._connected:
            self._log("Not connected. Please connect first.", "error")
            return
        
        if not SERIAL_AVAILABLE:
            self._log("pyserial not available - cannot stream output. Install with: pip install pyserial", "error")
            return
        
        if self._streaming_thread and self._streaming_thread.is_alive():
            # Stop streaming
            self._stop_streaming_forcefully()
            self.stream_output_btn.setText("Start Streaming")
            self._log("Stopped streaming output", "info")
        else:
            # Start streaming
            self._stop_streaming = False
            self._stop_output = False  # Ensure output is enabled
            self.stream_output_btn.setText("Stop Streaming")
            self._log("Starting output stream (capturing print statements from firmware)...", "info")
            self._start_streaming()
    
    def _schedule_now_playing_resync(self) -> None:
        """Re-parse the console after streaming starts — catches mid-track connect when boot lines are already in the buffer."""
        for ms in (80, 250, 900, 2200, 5000):
            QtCore.QTimer.singleShot(ms, self.refresh_library_db_and_now_playing)
    
    def _start_streaming(self) -> None:
        """Start streaming output from the Pico using the persistent serial connection."""
        if not self._connected:
            return
        
        if not SERIAL_AVAILABLE:
            self._log("pyserial not available", "error")
            return
        
        ser = self._serial_connection
        if not ser or not ser.is_open:
            self._log("No serial connection. Connect first.", "error")
            return
        
        # Reset stop flags
        self._stop_streaming = False
        self._stop_output = False
        self._streaming_pause_event.clear()
        self._streaming_resume_event.clear()
        
        def stream_thread():
            """Background thread: reads output from Pico via the shared serial connection."""
            import time
            # Local binding required: any later `ser = ...` in this function makes `ser` local
            # for the whole body; without this, `str(ser.port)` above the first assignment raises
            # UnboundLocalError ("cannot access local variable 'ser'...").
            ser = self._serial_connection
            try:
                self._debug_log("Streaming started on persistent connection", "info")
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_stream_output",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, "[Tip: If no output appears, click 'Soft Reset' to restart the device and see boot messages.]")
                )
                self._serial_error_count = 0
                buffer = ""
                try:
                    port_name = str(ser.port)
                except Exception:
                    port_name = str(self.port_combo.currentData() or "")

                def _recover_stream_serial(exc: BaseException) -> bool:
                    """If USB CDC handle is stale, reopen port. Returns True to retry loop."""
                    nonlocal ser
                    if not port_name or not is_recoverable_usb_serial_error(exc):
                        return False
                    new_ser = self._try_reopen_serial_connection(port_name)
                    if new_ser is not None:
                        ser = new_ser
                        self._serial_error_count = 0
                        return True
                    return False

                while not self._stop_output and not self._stop_streaming:
                    if not self._connected:
                        break
                    
                    # Check if we've been asked to pause (a command wants the port)
                    if self._streaming_pause_event.is_set():
                        self._debug_log("Streaming paused for command", "info")
                        self._streaming_resume_event.set()  # Signal that we've paused
                        # Wait until pause is cleared (command finished)
                        while self._streaming_pause_event.is_set():
                            if self._stop_streaming or self._stop_output:
                                return
                            time.sleep(0.05)
                        self._debug_log("Streaming resumed", "info")
                        ser = self._serial_connection
                        # Do **not** discard ser.in_waiting here: that bytes contained
                        # firmware print() output emitted while VRTEST held the port. Dropping
                        # it removed lines from the stream ring and broke Now Playing parsing.
                        continue
                    
                    try:
                        if not ser or not ser.is_open:
                            self._debug_log("Serial port closed, stopping stream", "warning")
                            break
                        
                        try:
                            waiting = ser.in_waiting
                        except (serial.SerialException, OSError) as e:
                            if _recover_stream_serial(e):
                                time.sleep(0.05)
                                continue
                            self._serial_error_count += 1
                            if self._serial_error_count > 25:
                                self._debug_log(f"Too many serial errors ({self._serial_error_count}), stopping stream: {e}", "error")
                                break
                            time.sleep(1.0)
                            continue
                        
                        if waiting > 0:
                            self._serial_error_count = 0
                            try:
                                data = ser.read(waiting).decode('utf-8', errors='replace')
                                buffer += data
                                while '\n' in buffer:
                                    line, buffer = buffer.split('\n', 1)
                                    if line.strip():
                                        QtCore.QMetaObject.invokeMethod(
                                            self,
                                            "_display_stream_output",
                                            QtCore.Qt.ConnectionType.QueuedConnection,
                                            QtCore.Q_ARG(str, line)
                                        )
                                if len(buffer) > 200:
                                    QtCore.QMetaObject.invokeMethod(
                                        self,
                                        "_display_stream_output",
                                        QtCore.Qt.ConnectionType.QueuedConnection,
                                        QtCore.Q_ARG(str, buffer)
                                    )
                                    buffer = ""
                            except (serial.SerialException, OSError) as e:
                                if _recover_stream_serial(e):
                                    time.sleep(0.05)
                                    continue
                                self._serial_error_count += 1
                                if self._serial_error_count > 25:
                                    self._debug_log(f"Too many serial read errors, stopping stream: {e}", "error")
                                    break
                                time.sleep(0.5)
                                continue
                        else:
                            # No data - sleep briefly but check stop/pause flags frequently
                            for _ in range(5):
                                if self._stop_streaming or self._stop_output or self._streaming_pause_event.is_set():
                                    break
                                time.sleep(0.1)
                    
                    except Exception as e:
                        if _recover_stream_serial(e):
                            time.sleep(0.05)
                            continue
                        self._serial_error_count += 1
                        if self._serial_error_count > 40:
                            self._debug_log(f"Too many stream errors ({self._serial_error_count}), stopping: {e}", "error")
                            break
                        time.sleep(0.5)
                        continue
                
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_stream_stopped",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
            except Exception as e:
                self._debug_log(f"Stream thread error: {e}", "error")
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_stream_stopped",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
            # NOTE: Do NOT close serial connection here - it's shared/persistent
        
        self._streaming_thread = threading.Thread(target=stream_thread, daemon=True)
        self._streaming_thread.start()
        self._schedule_now_playing_resync()
    
    @QtCore.pyqtSlot(str)
    def _display_stream_output(self, content: str):
        """Display streamed output on main thread and parse for now-playing info."""
        try:
            if content and content.strip():
                line = content.rstrip()
                append_session_ndjson_from_vrdbg_line(line)
                with self._stream_ring_lock:
                    self._stream_ring.append(line)
                # Pico line already includes ``[HH:MM:SS.mmm]`` from firmware print(); avoid
                # duplicating host time inside the message (was: host + [host] + device).
                self._log(line, self._classify_stream_level(line))
                
                # Parse stream for "now playing" updates (non-intrusive)
                self._parse_stream_for_now_playing(line)
        except Exception as e:
            self._debug_log(f"Error displaying stream output: {e}", "error")

    @staticmethod
    def _classify_stream_level(line: str) -> str:
        """Map streamed firmware text to log severity for UI/session readability."""
        s = (line or "").strip().lower()
        if not s:
            return "output"
        error_markers = (
            "traceback",
            "memoryerror",
            "syntaxerror",
            "fatal:",
            "boot init error",
            "error:",
            "playback failed",
            "timed out",
            "timeout",
            "exception",
            "not confirmed",
            "failed to start",
        )
        warn_markers = (
            "warn",
            "busy stayed high",
            "fallback",
            "cooling down",
            "recovery attempt",
            "retry",
            "not playing",
            "no uart error",
        )
        if any(m in s for m in error_markers):
            return "error"
        if any(m in s for m in warn_markers):
            return "warning"
        return "info"
    
    def _parse_stream_for_now_playing(self, line: str):
        """Parse streaming output to extract now-playing info without interrupting firmware.
        
        Always displays the current mode alongside track information.
        Detects: mode, source (album/playlist name), shuffle type, track title/artist.
        Handles combined log format: _start_playback_for_current: mode=X, source=Y, shuffle_type=Z, album_idx=N, ...
        Also handles older firmware that may have separate lines.
        """
        import re
        try:
            # Detect combined mode/source/shuffle_type from _start_playback_for_current log:
            #   "_start_playback_for_current: mode=album, source=Toxicity, shuffle_type=, album_idx=1, ..."
            if "_start_playback_for_current: mode=" in line:
                mode_match = re.search(r"mode=(\w+)", line)
                if mode_match:
                    detected_mode = mode_match.group(1)
                    # Firmware logs "station" in basic mode, but guard against old firmware
                    # sending "playlist" — treat both as "station" when in basic mode.
                    if self._basic_mode and detected_mode == "playlist":
                        detected_mode = "station"
                    self._current_device_mode = detected_mode
                
                # Extract source name (everything between "source=" and the next ", shuffle_type=" or ", album_idx=")
                source_match = re.search(r"source=([^,]*?)(?:,\s*shuffle_type=|,\s*album_idx=|$)", line)
                if source_match:
                    source_val = source_match.group(1).strip()
                    if source_val:
                        self._current_device_source = source_val
                
                # Extract shuffle_type
                shuffle_match = re.search(r"shuffle_type=(\w*)", line)
                if shuffle_match and shuffle_match.group(1):
                    self._current_shuffle_type = shuffle_match.group(1)
                elif self._current_device_mode != "shuffle":
                    self._current_shuffle_type = ""

                # Extract album_idx as fallback for source name
                idx_match = re.search(r"album_idx=(\d+)", line)
                if idx_match:
                    self._current_album_idx = int(idx_match.group(1))
                    # Use album_idx as fallback ONLY if source is empty
                    if not self._current_device_source:
                        mode = self._current_device_mode or ""
                        if mode == "station":
                            self._current_device_source = f"Station #{self._current_album_idx + 1}"
                        elif mode == "playlist":
                            self._current_device_source = f"Playlist #{self._current_album_idx + 1}"
                        elif mode == "album":
                            self._current_device_source = f"Album #{self._current_album_idx + 1}"
                
                # In basic mode, the combined line also carries folder/track — resolve
                # the actual song name immediately so Now Playing updates in one step.
                if self._basic_mode and self._effective_db():
                    folder_match = re.search(r"folder=(\d+),?\s*track=(\d+)", line)
                    if folder_match:
                        self._current_basic_folder = int(folder_match.group(1))
                        self._current_basic_track = int(folder_match.group(2))
                        resolved = self._resolve_basic_track_name(
                            self._current_basic_folder, self._current_basic_track
                        )
                        if resolved:
                            self._current_track_title, self._current_track_artist = resolved

                self._update_now_playing_display()
            
            # Detect mode changes: "[MODE] album -> playlist" or "[MODE] album -> playlist, album_idx=0"
            if "[MODE]" in line:
                match = re.search(r"(\w+)\s*->\s*(\w+)", line)
                if match:
                    new_mode = match.group(2)
                    if self._basic_mode and new_mode == "playlist":
                        new_mode = "station"
                    self._current_device_mode = new_mode
                    # Clear source on mode change (will be re-detected from next playback log)
                    self._current_device_source = ""
                    if match.group(2) != "shuffle":
                        self._current_shuffle_type = ""
                    # Extract album_idx if present
                    idx_match = re.search(r"album_idx=(\d+)", line)
                    if idx_match:
                        self._current_album_idx = int(idx_match.group(1))
                        mode = new_mode
                        if mode == "station":
                            self._current_device_source = f"Station #{self._current_album_idx + 1}"
                        elif mode == "playlist":
                            self._current_device_source = f"Playlist #{self._current_album_idx + 1}"
                        elif mode == "album":
                            self._current_device_source = f"Album #{self._current_album_idx + 1}"
                    self._update_now_playing_display()
                    return
            
            # Detect shuffle initialization:
            #   "Mode: Track shuffle (...)" (basic station) or legacy "Mode: Shuffle (...)"
            if "Mode: Track shuffle" in line or "Mode: Shuffle" in line:
                match = re.search(
                    r"Mode: (?:[Tt]rack )?[Ss]huffle \((.+?),\s*(\d+)\s*tracks?\)", line
                )
                if match:
                    source = match.group(1).strip()
                    self._current_device_mode = "shuffle"
                    self._current_device_source = source
                    if source == "Library":
                        self._current_shuffle_type = "library"
                    elif source.startswith("Station"):
                        self._current_shuffle_type = "station_tracks"
                    else:
                        # Source is an album or playlist name
                        self._current_shuffle_type = "source"
                    self._update_now_playing_display()
                    return
            
            # Detect "Long press: next album/playlist" or "Shuffle: advancing to next album/playlist" patterns
            if "next album" in line.lower() or "next playlist" in line.lower():
                # Album/playlist changed, source will be re-detected from next playback log
                self._current_device_source = ""
            
            # Detect AM sound events (PWM overlay or DFPlayer sequential)
            if "AM: PWM overlay mode" in line:
                self._am_wav_loaded = True  # PWM overlay active
            elif "AM: DFPlayer sequential mode" in line:
                self._am_wav_loaded = True  # DFPlayer fallback active
            elif "AM: Playing static sound" in line:
                self._am_wav_loaded = True
            elif "AM: Static sound not confirmed" in line:
                self._am_wav_loaded = False
            
            # Detect playback start: "Starting playback: 'title' by artist (folder=X, track=Y, start_ms=Z)"
            #   or "Playback started successfully: 'title' by artist"
            #   Artist may be empty (basic mode generates empty artist strings).
            if "Starting playback:" in line or "_start_playback_for_current: Playing" in line or "Playback started successfully:" in line:
                match = re.search(r"'([^']+)'\s+by\s*(.*?)(?:\s*\(folder=|\s*$)", line)
                if match:
                    title = match.group(1)
                    artist = match.group(2).strip()
                    # In basic mode, resolve generic "Track N" to real song name
                    if self._basic_mode and self._effective_db() and re.match(r"^Track \d+$", title):
                        folder_match = re.search(r"folder=(\d+),?\s*track=(\d+)", line)
                        if folder_match:
                            self._current_basic_folder = int(folder_match.group(1))
                            self._current_basic_track = int(folder_match.group(2))
                            resolved = self._resolve_basic_track_name(
                                self._current_basic_folder, self._current_basic_track
                            )
                            if resolved:
                                title, artist = resolved
                        elif not re.match(r"^Track \d+$", getattr(self, '_current_track_title', '')):
                            # No folder info on this line but we already have a real resolved
                            # title from the combined _start_playback_for_current: mode= line.
                            # Don't overwrite it with the generic "Track N" placeholder.
                            self._update_now_playing_display()
                            return
                    self._current_track_title = title
                    self._current_track_artist = artist
                    self._update_now_playing_display()
                    return
            
            # Detect track auto-advance: "Auto-advanced: 'old' -> 'new'" (legacy: "Track finished:")
            if "Auto-advanced:" in line or "Track finished:" in line:
                match = re.search(r"'([^']+)'\s*->\s*'([^']+)'", line)
                if match:
                    new_title = match.group(2)
                    new_artist = "(auto-advanced)"
                    if self._basic_mode and self._effective_db() and re.match(r"^Track \d+$", new_title):
                        folder_match = re.search(r"station (\d+) track (\d+) -> station (\d+) track (\d+)", line)
                        if folder_match:
                            resolved = self._resolve_basic_track_name(
                                int(folder_match.group(3)), int(folder_match.group(4))
                            )
                            if resolved:
                                new_title, new_artist = resolved
                    self._current_track_title = new_title
                    self._current_track_artist = new_artist
                    self._update_now_playing_display()
        except Exception:
            pass  # Non-critical - don't let parsing errors affect streaming
    
    def _scan_console_for_now_playing(self) -> None:
        """Scan existing console output for the most recent playback line
        to detect what's currently playing (useful when streaming starts mid-playback)."""
        try:
            text = self.console_output.toPlainText()
            if not text:
                return
            lines = text.split('\n')
            import re as _re
            # Prefer full metadata lines (same order as stream parsing)
            for line in reversed(lines):
                if "_start_playback_for_current: mode=" in line:
                    self._parse_stream_for_now_playing(line)
                    return
            for line in reversed(lines):
                if "Starting playback:" in line or "Playback started successfully:" in line:
                    self._parse_stream_for_now_playing(line)
                    return
            # Fallback: DFPlayer firmware prints e.g.
            #   DF: Playing 'Track 1' ... (folder=01, track=001) -> ... (folder=1, track=1)
            # Use the last (folder=N, track=M) pair on the line (command uses unpadded ints).
            if self._basic_mode:
                for line in reversed(lines):
                    if "DF: Playing" in line:
                        pairs = _re.findall(r"folder=(\d+),\s*track=(\d+)", line)
                        if pairs:
                            folder_num = int(pairs[-1][0])
                            track_num = int(pairs[-1][1])
                            self._current_basic_folder = folder_num
                            self._current_basic_track = track_num
                            if self._effective_db():
                                resolved = self._resolve_basic_track_name(folder_num, track_num)
                                if resolved:
                                    self._current_track_title, self._current_track_artist = resolved
                                else:
                                    self._current_track_title = f"Track {track_num}"
                                    self._current_track_artist = ""
                            else:
                                self._current_track_title = f"Track {track_num}"
                                self._current_track_artist = ""
                            # Mode/source may be missing until next _start_playback line — infer station from DB
                            if not getattr(self, "_current_device_mode", ""):
                                self._current_device_mode = "station"
                            self._update_now_playing_display()
                        return
                for line in reversed(lines):
                    m = _re.search(r"Expected SD path:\s*(\d+)/(\d+)\.", line)
                    if m:
                        folder_num = int(m.group(1))
                        track_num = int(m.group(2))
                        self._current_basic_folder = folder_num
                        self._current_basic_track = track_num
                        if self._effective_db():
                            resolved = self._resolve_basic_track_name(folder_num, track_num)
                            if resolved:
                                self._current_track_title, self._current_track_artist = resolved
                            else:
                                self._current_track_title = f"Track {track_num}"
                                self._current_track_artist = ""
                        else:
                            self._current_track_title = f"Track {track_num}"
                            self._current_track_artist = ""
                        if not getattr(self, "_current_device_mode", ""):
                            self._current_device_mode = "station"
                        self._update_now_playing_display()
                        return
        except Exception:
            pass

    def _resolve_basic_track_name(self, folder_num: int, track_num: int):
        """Look up the actual song name from the station database given a DFPlayer folder/track.
        Returns (title, artist) or None if not found.
        Also updates _current_device_source to the station name so the display
        shows which station the track belongs to (useful for library shuffle)."""
        try:
            db = self._effective_db()
            if db is None:
                return None
            fn = int(folder_num)
            tn = int(track_num)
            stations = db.list_basic_stations()
            for station in stations:
                if int(station["folder_number"]) == fn:
                    station_name = station["name"] or f"Station {fn}"
                    songs = db.list_basic_station_songs(station["id"])
                    if 0 < tn <= len(songs):
                        song = songs[tn - 1]
                        try:
                            title = song["title"] or song["original_filename"] or f"Track {tn}"
                        except (KeyError, TypeError):
                            title = f"Track {tn}"
                        try:
                            artist = song["artist"] or ""
                        except (KeyError, TypeError):
                            artist = ""
                        self._current_device_source = station_name
                        return (title, artist)
                    break
        except Exception:
            pass
        return None

    def _update_now_playing_display(self):
        """Update the now playing label with current mode, source, track, and artist."""
        try:
            mode = self._current_device_mode or "Unknown"
            title = getattr(self, '_current_track_title', '')
            artist = getattr(self, '_current_track_artist', '')
            source = getattr(self, '_current_device_source', '')
            shuffle_type = getattr(self, '_current_shuffle_type', '')
            folder = getattr(self, '_current_basic_folder', None)
            track_num = getattr(self, '_current_basic_track', None)
            
            parts = []
            
            # Build mode display with shuffle distinction
            if mode.lower() == "shuffle":
                if shuffle_type == "library":
                    mode_display = "Library shuffle"
                elif shuffle_type == "album" and source:
                    mode_display = f"Album track shuffle ({source})"
                elif shuffle_type == "playlist" and source:
                    mode_display = f"Playlist track shuffle ({source})"
                elif shuffle_type in ("station_tracks", "station") and source:
                    mode_display = f"Track shuffle ({source})"
                elif shuffle_type == "source" and source:
                    mode_display = f"Track shuffle ({source})"
                elif source:
                    mode_display = f"Track shuffle ({source})"
                else:
                    mode_display = "Track shuffle"
            elif mode.lower() in ("station", "playlist") and self._basic_mode:
                mode_display = "Station (ordered tracks)"
            else:
                mode_display = mode.title()
            
            parts.append(
                f"<span style='color: {self._now_playing_color('mode')};'>Mode: {mode_display}</span>"
            )
            
            # Show source (album/playlist name) for non-shuffle modes
            if mode.lower() != "shuffle" and source:
                parts.append(
                    f"<span style='color: {self._now_playing_color('source')};'>{source}</span>"
                )
            
            if title:
                parts.append(
                    f"<b style='color: {self._now_playing_color('title')};'>&#9835; {title}</b>"
                )
            if artist:
                parts.append(
                    f"<span style='color: {self._now_playing_color('artist')};'>{artist}</span>"
                )
            
            # Show folder/track location for basic mode
            if self._basic_mode and folder is not None and track_num is not None:
                parts.append(
                    f"<span style='color: {self._now_playing_color('loc')}; font-size: smaller;'>"
                    f"Folder {folder:02d} / Track {track_num:03d}</span>"
                )
            
            self.now_playing_label.setText("<br>".join(parts))
        except Exception:
            pass
    
    @QtCore.pyqtSlot()
    def _display_stream_stopped(self):
        """Update UI when streaming stops."""
        try:
            self.stream_output_btn.setText("Start Streaming")
        except Exception as e:
            self._debug_log(f"Error updating stream button: {e}", "error")
    
    def _check_amplifier(self) -> None:
        """Run amplifier diagnostic checks."""
        if not self._connected:
            self._log("Not connected. Please connect first.", "error")
            return
        
        if "check_amplifier" in self._active_operations:
            self._debug_log("Amplifier check already in progress, ignoring", "warning")
            return
        
        self._active_operations.add("check_amplifier")
        # Get port name from combo box data (not text, which includes description)
        port = self.port_combo.currentData()
        if not port:
            # Fallback: try to extract port from text if data is None
            text = self.port_combo.currentText().strip()
            if text and text.startswith("COM"):
                port = text.split()[0] if ' ' in text else text
            else:
                self._log("No port selected", "error")
                return
        
        self._log("=== Amplifier Diagnostic ===", "info")
        self._log("Checking DFPlayer and amplifier connections...", "info")
        
        # Command to check DFPlayer status, volume, BUSY pin, and suggest amplifier checks
        cmd = (
            "from components.dfplayer_hardware import DFPlayerHardware\n"
            "from machine import Pin\n"
            "import time\n"
            "print('=== DFPlayer Status ===')\n"
            "hw = DFPlayerHardware()\n"
            "print(f'DFPlayer Volume: {hw._df_volume}/30 (max)')\n"
            "print(f'BUSY Pin (GP15): {hw.pin_busy.value()} (0=playing, 1=idle)')\n"
            "print(f'UART TX (GP0): {Pin(0, Pin.OUT).value()}')\n"
            "print(f'UART RX (GP1): {Pin(1, Pin.IN).value()}')\n"
            "print('')\n"
        )
        # First command just gets basic status - we don't use the result
        self._send_serial_command(port, cmd, timeout=10)
        cmd_full = cmd + (
            "print('=== Amplifier Troubleshooting ===')\n"
            "print('1. Check amplifier power: Is it getting 5V/12V?')\n"
            "print('2. Check DFPlayer output: SPK_1/SPK_2 or DAC connected to amp input?')\n"
            "print('3. Check amplifier enable/shutdown pin (if present)')\n"
            "print('4. Check gain/volume pot on amplifier (if present)')\n"
            "print('5. Check ground connections: All GNDs connected?')\n"
            "print('6. Try: hw._df_set_vol(30); hw._df_play_folder_track(1, 1)')\n"
            "print('   Then check BUSY pin - should go to 0 (playing)')\n"
            "print('')\n"
            "print('=== Test Playback ===')\n"
            "print('Sending test command: play folder 1, track 1...')\n"
            "hw._df_set_vol(30)\n"
            "time.sleep_ms(100)\n"
            "hw._df_play_folder_track(1, 1)\n"
            "time.sleep_ms(500)\n"
            "busy_after = hw.pin_busy.value()\n"
            "print(f'BUSY pin after playback command: {busy_after} (0=playing, 1=idle)')\n"
            "if busy_after == 0:\n"
            "  print('✓ DFPlayer is playing! Check amplifier connections.')\n"
            "else:\n"
            "  print('✗ DFPlayer not playing. Check SD card and file structure.')\n"
        )
        
        def run_diagnostic():
            max_retries = 3
            retry_delay = 1.0
            
            try:
                for attempt in range(max_retries):
                    try:
                        returncode, stdout, stderr = self._send_serial_command(port, cmd_full, timeout=15)
                        
                        if returncode == 0:
                            output = stdout.strip() if stdout else ""
                            if output:
                                for line in output.split('\n'):
                                    if line.strip():
                                        self._log(line, "output")
                            else:
                                self._log("(No output)", "info")
                            self._active_operations.discard("check_amplifier")
                            break  # Success, exit retry loop
                        else:
                            error_msg = stderr or stdout or "Unknown error"
                            # Check if it's a port conflict error
                            if "failed to access" in error_msg.lower():
                                if attempt < max_retries - 1:
                                    self._log(f"Port conflict, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})", "info")
                                    import time
                                    time.sleep(retry_delay)
                                    retry_delay *= 2  # Exponential backoff
                                    continue
                                else:
                                    self._log(f"Error: {error_msg}", "error")
                                    self._active_operations.discard("check_amplifier")
                                    break
                            else:
                                self._log(f"Error: {error_msg}", "error")
                                self._active_operations.discard("check_amplifier")
                                break
                    except subprocess.TimeoutExpired:
                        if attempt < max_retries - 1:
                            self._log(f"Timeout, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})", "info")
                            import time
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        else:
                            self._active_operations.discard("check_amplifier")
                            self._log("Diagnostic timed out after multiple retries", "error")
                            break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            self._log(f"Error, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries}): {e}", "warning")
                            import time
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        else:
                            self._active_operations.discard("check_amplifier")
                            self._log(f"Error running diagnostic: {e}", "error")
                            break
            finally:
                pass  # _send_serial_command handles streaming pause/resume
        
        threading.Thread(target=run_diagnostic, daemon=True).start()
    
    def _show_help(self) -> None:
        """Show help with example commands."""
        help_text = """
Example Commands (sent to device):
  gc.mem_free()  — live (playback continues)
  gc.collect()   — live (runs gc.collect() on device)
  import gc; gc.mem_free()
  print('Hello from Pico!')  — REPL (Ctrl+C stops firmware; use Restart Firmware after)
  import machine; machine.Pin(2).value()
  from components.dfplayer_hardware import DFPlayerHardware; hw = DFPlayerHardware()
  import os; os.listdir()

GUI Commands (not sent to device):
  check_amplifier - Run amplifier diagnostic
  help - Show this help message
        """
        self._log(help_text.strip(), "info")
    
    def _check_power_sense_setting(self) -> None:
        """Check current power sense setting on device."""
        if not self._connected:
            return
        
        port = self.port_combo.currentData()
        self._debug_log("Checking power sense setting...", "info")
        
        def check():
            try:
                cmd = (
                    "try:\n"
                    "    with open('skip_power_sense.txt', 'r') as f:\n"
                    "        val = f.read().strip().lower()\n"
                    "        print('true' if val in ('true', '1') else 'false')\n"
                    "except:\n"
                    "    print('false')"
                )
                returncode, stdout, stderr = self._send_serial_command(port, cmd, timeout=5)
                self._debug_log(f"Power sense check return code: {returncode}", "info")
                if returncode == 0:
                    setting = stdout.strip().lower() == "true"
                    self._debug_log(f"Power sense setting: {setting}", "info")
                    # Update checkbox on main thread using QMetaObject.invokeMethod
                    QtCore.QMetaObject.invokeMethod(
                        self,
                        "_update_power_sense_checkbox",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(int, 1 if setting else 0)
                    )
            except Exception as e:
                self._debug_log(f"Error checking power sense: {e}\n{traceback.format_exc()}", "error")
        
        threading.Thread(target=check, daemon=True).start()
    
    def _toggle_power_sense(self, state: int) -> None:
        """Toggle power sense check on/off."""
        if not self._connected:
            self.power_sense_checkbox.setChecked(False)
            self._log("Not connected. Please connect first.", "error")
            return
        
        if "toggle_power" in self._active_operations:
            self._debug_log("Power sense toggle already in progress, ignoring", "warning")
            return
        
        self._active_operations.add("toggle_power")
        # state: 0 = unchecked, 2 = checked
        enabled = self.power_sense_checkbox.isChecked()
        port = self.port_combo.currentData()
        
        self._debug_log(f"Toggling power sense: enabled={enabled}", "info")
        self._log(f"{'Disabling' if enabled else 'Enabling'} power sense check...", "info")
        
        def toggle():
            try:
                # Write the setting to a file on the device
                value = "true" if enabled else "false"
                cmd = (
                    f"with open('skip_power_sense.txt', 'w') as f:\n"
                    f"    f.write('{value}')"
                )
                self._debug_log(f"Executing power sense toggle command...", "info")
                returncode, stdout, stderr = self._send_serial_command(port, cmd, timeout=5)
                self._debug_log(f"Power sense toggle return code: {returncode}", "info")
                
                self._active_operations.discard("toggle_power")
                
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_power_sense_toggle_result",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(int, returncode),
                    QtCore.Q_ARG(str, stderr.strip() if stderr else ""),
                    QtCore.Q_ARG(int, 1 if enabled else 0)
                )
            except subprocess.TimeoutExpired:
                self._debug_log("Power sense toggle timed out", "error")
                # Clear operation immediately
                self._active_operations.discard("toggle_power")
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_power_sense_timeout",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
            except Exception as e:
                error_msg = f"Error toggling power sense: {e}\n{traceback.format_exc()}"
                self._debug_log(error_msg, "error")
                # Clear operation immediately
                self._active_operations.discard("toggle_power")
                error_msg_val = str(e)
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_display_power_sense_error",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, error_msg_val)
                )
        
        threading.Thread(target=toggle, daemon=True).start()
    
    def _flash_basic_firmware(self) -> None:
        """Flash basic-mode firmware to test DFPlayer query commands.

        Uses the parent MainWindow's install_to_pico flow but swaps
        main.py for main_basic.py.
        """
        reply = VintageMessageBox.question(
            self,
            "Flash Basic Mode Firmware",
            "This will install basic-mode firmware on the connected Pico.\n\n"
            "Basic mode discovers stations from DFPlayer SD card folders "
            "using UART query commands (0x4F, 0x4E).\n"
            "No metadata files are needed -- folder structure is the source of truth.\n\n"
            "Make sure your SD card has numbered folders (01/, 02/, etc.) with MP3 files.\n\n"
            "Proceed?",
            VintageMessageBox.StandardButton.Yes | VintageMessageBox.StandardButton.No,
            VintageMessageBox.StandardButton.No,
        )
        if reply != VintageMessageBox.StandardButton.Yes:
            return

        main_window = self.window()
        if not hasattr(main_window, "install_to_pico"):
            self._log("Cannot find install_to_pico on MainWindow.", "error")
            return

        main_window.install_to_pico(after_firmware=False, basic_mode=True)

    def _log(self, message: str, level: str = "info") -> None:
        """Add a message to the console output. Thread-safe - can be called from any thread."""
        # Check if we're on the main thread
        if QtCore.QThread.currentThread() == self.thread():
            # We're on the main thread, update UI directly
            self._log_impl(message, level)
        else:
            # We're on a background thread, queue the update
            try:
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_log_impl",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, message),
                    QtCore.Q_ARG(str, level)
                )
            except Exception as e:
                # Fallback to print if invokeMethod fails
                print(f"[DeviceDebug] Failed to queue log message: {e}")
                print(f"[DeviceDebug] {message}")
    
    def _console_log_color(self, level: str) -> str:
        """Return HTML color for a console log line."""
        colors = {
            "error": "#f48771",
            "warning": "#dcdcaa",
            "success": "#4ec9b0",
            "command": "#569cd6",
            "output": "#d4d4d4",
        }
        if level in colors:
            return colors[level]
        # Default [INFO] — tan in vintage mode, light blue otherwise
        return t.TOOLS_CONSOLE_FG if self._basic_mode else "#9cdcfe"

    def _now_playing_color(self, role: str) -> str:
        """Return HTML color for now-playing label parts."""
        colors = {
            "mode": "#dcdcaa",
            "source": "#c586c0",
            "title": "#4ec9b0",
            "loc": "#808080",
        }
        if role == "artist":
            return t.TOOLS_CONSOLE_FG if self._basic_mode else "#9cdcfe"
        return colors.get(role, "#d4d4d4")

    @QtCore.pyqtSlot(str, str)
    def _log_impl(self, message: str, level: str = "info") -> None:
        """Internal implementation of log - must be called on main thread."""
        from .session_log import format_session_timestamp

        timestamp = format_session_timestamp()
        
        if level == "error":
            prefix = "[ERROR]"
        elif level == "warning":
            prefix = "[WARN]"
        elif level == "success":
            prefix = "[OK]"
        elif level == "command":
            prefix = "[CMD]"
        elif level == "output":
            prefix = ""
        else:
            prefix = "[INFO]"
        
        color = self._console_log_color(level)
        formatted = f'<span style="color: {color};">{timestamp} {prefix} {message}</span>'
        # Always echo to stdout so the session log captures it
        print(f"{timestamp} {prefix} {message}")
        try:
            if hasattr(self, 'console_output') and self.console_output:
                self.console_output.append(formatted)
                # Auto-scroll to bottom
                scrollbar = self.console_output.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        except Exception as e:
            print(f"[DeviceDebug] UI update error: {e}")
    
    def _debug_log(self, message: str, level: str = "info") -> None:
        """Internal debug logging - logs to GUI console with [DEBUG] prefix.
        Session log captures the output automatically via _log_impl's print()."""
        if self._debug_logging:
            try:
                self._log(f"[DEBUG] {message}", level)
            except Exception:
                # If UI logging fails, at least print to console
                print(f"[DeviceDebug-DEBUG] {level.upper()}: {message}")
    
    def _toggle_debug_logging(self, state: int) -> None:
        """Toggle debug logging on/off."""
        self._debug_logging = self.debug_logging_checkbox.isChecked()
        status = "enabled" if self._debug_logging else "disabled"
        print(f"[DeviceDebug] Debug logging {status}")
        if self._debug_logging:
            self._log(f"Debug logging {status}", "info")
    
    @QtCore.pyqtSlot(int, str, str)
    def _display_list_files_result(self, returncode: int, stdout: str, stderr: str):
        """Display list files result on main thread."""
        try:
            if returncode == 0:
                if stdout:
                    self._log(stdout, "output")
                else:
                    self._log("(No files listed or empty output)", "info")
            else:
                self._log(f"Error: {stderr or stdout or 'Unknown error'}", "error")
        except Exception as e:
            self._debug_log(f"Error displaying list files result: {e}\n{traceback.format_exc()}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_status_output(self, output: str):
        """Display status command output on main thread."""
        try:
            if output:
                self._log(output, "output")
        except Exception as e:
            self._debug_log(f"Error displaying status output: {e}\n{traceback.format_exc()}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_safe_log_msg(self, encoded_msg: str):
        """Display a log message on main thread (used by _log_safe). Format: 'level|||message'."""
        try:
            parts = encoded_msg.split("|||", 1)
            if len(parts) == 2:
                level, msg = parts
            else:
                level, msg = "info", encoded_msg
            self._log(msg, level)
        except Exception as e:
            self._debug_log(f"Error displaying log message: {e}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_now_playing(self, json_str: str):
        """Display now playing information on main thread."""
        try:
            import json
            # Handle empty or invalid JSON gracefully
            if not json_str or not json_str.strip():
                self.now_playing_label.setText("No status available (device may not be responding)")
                self.now_playing_label.setStyleSheet(
                    "font-size: 12px; padding: 8px; background-color: #2d2d2d; "
                    "border: 1px solid #ffaa00; border-radius: 4px; color: #ffaa88;"
                )
                return
            
            try:
                status = json.loads(json_str)
            except json.JSONDecodeError as e:
                self._debug_log(f"Error parsing JSON from now playing: {e}, received: {json_str[:200]}", "error")
                self.now_playing_label.setText(f"Error parsing status: {json_str[:100]}")
                self.now_playing_label.setStyleSheet(
                    "font-size: 12px; padding: 8px; background-color: #2d2d2d; "
                    "border: 1px solid #ff4444; border-radius: 4px; color: #ff8888;"
                )
                return
            
            if "error" in status:
                error_msg = status.get("error", "Unknown error")
                # Provide more helpful error messages
                if "Firmware not accessible" in error_msg or "Firmware instance not found" in error_msg:
                    help_text = (
                        "Firmware not accessible. This usually means:\n"
                        "• Device is not running main.py (may need to restart)\n"
                        "• Firmware is in main loop and instance isn't accessible\n"
                        "• Try: Soft Reset to restart the firmware"
                    )
                    self.now_playing_label.setText(f"Error: {error_msg}\n\n{help_text}")
                else:
                    self.now_playing_label.setText(f"Error: {error_msg}")
                self.now_playing_label.setStyleSheet(
                    "font-size: 12px; padding: 8px; background-color: #2d2d2d; "
                    "border: 1px solid #ff4444; border-radius: 4px; color: #ff8888;"
                )
                return
            
            # Extract status information
            mode = status.get("mode", "Unknown")
            source = status.get("source", "Unknown")
            track_title = status.get("track_title", "Unknown")
            track_artist = status.get("track_artist", "Unknown")
            track_number = status.get("track_number", 0)
            track_count = status.get("track_count", 0)
            is_playing = status.get("is_playing", False)
            power_on = status.get("power_on", False)
            
            # Build display text
            playing_status = "▶ Playing" if is_playing else "⏸ Paused"
            power_status = "ON" if power_on else "OFF"
            
            if mode == "shuffle":
                display_text = (
                    f"<b>Mode:</b> {mode.title()}<br>"
                    f"<b>Status:</b> {playing_status} | Power: {power_status}<br>"
                    f"<b>Track:</b> {track_number}/{track_count}<br>"
                    f"<b>Title:</b> {track_title}<br>"
                    f"<b>Artist:</b> {track_artist}"
                )
            elif mode == "radio":
                display_text = (
                    f"<b>Mode:</b> {mode.title()}<br>"
                    f"<b>Station:</b> {source}<br>"
                    f"<b>Status:</b> {playing_status} | Power: {power_status}<br>"
                    f"<b>Track:</b> {track_number}/{track_count}<br>"
                    f"<b>Now Playing:</b> {track_title}<br>"
                    f"<b>Artist:</b> {track_artist}"
                )
            else:  # album or playlist
                display_text = (
                    f"<b>Mode:</b> {mode.title()}<br>"
                    f"<b>Source:</b> {source}<br>"
                    f"<b>Status:</b> {playing_status} | Power: {power_status}<br>"
                    f"<b>Track:</b> {track_number}/{track_count}<br>"
                    f"<b>Title:</b> {track_title}<br>"
                    f"<b>Artist:</b> {track_artist}"
                )
            
            self.now_playing_label.setText(display_text)
            self.now_playing_label.setStyleSheet(
                "font-size: 12px; padding: 8px; background-color: #2d2d2d; "
                "border: 1px solid #555; border-radius: 4px; color: #d4d4d4;"
            )
        except Exception as e:
            self._debug_log(f"Error displaying now playing: {e}\n{traceback.format_exc()}", "error")
            self.now_playing_label.setText(f"Error displaying status: {str(e)[:50]}")
            self.now_playing_label.setStyleSheet(
                "font-size: 12px; padding: 8px; background-color: #2d2d2d; "
                "border: 1px solid #ff4444; border-radius: 4px; color: #ff8888;"
            )
    
    @QtCore.pyqtSlot(str)
    def _display_soft_reset_result(self, stdout: str):
        """Display soft reset result on main thread."""
        try:
            self._log("Soft reset sent - device should restart automatically", "success")
            if stdout:
                self._log(stdout, "output")
        except Exception as e:
            self._debug_log(f"Error displaying soft reset result: {e}\n{traceback.format_exc()}", "error")
    
    @QtCore.pyqtSlot(int, str, str, int)
    def _display_command_result(self, returncode: int, stdout: str, stderr: str, was_streaming_int: int):
        """Display command result on main thread."""
        try:
            if returncode == 0:
                if stdout:
                    self._log(stdout, "output")
            else:
                error = stderr or stdout or "Unknown error"
                if error:
                    self._log(f"Error: {error}", "error")
        except Exception as e:
            self._debug_log(f"Error displaying command result: {e}\n{traceback.format_exc()}", "error")
    
    @QtCore.pyqtSlot()
    def _display_command_timeout(self):
        """Display command timeout message on main thread."""
        try:
            self._log("Command timed out - device may be busy or command is taking too long", "error")
        except Exception as e:
            self._debug_log(f"Error displaying timeout: {e}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_command_error(self, error: str):
        """Display command error message on main thread."""
        try:
            self._log(f"Error executing command: {error}", "error")
        except Exception as e:
            self._debug_log(f"Error displaying error: {e}", "error")
    
    @QtCore.pyqtSlot(int)
    def _update_power_sense_checkbox(self, checked_int: int):
        """Update power sense checkbox on main thread."""
        try:
            checked = bool(checked_int)  # Convert int back to bool
            self.power_sense_checkbox.setChecked(checked)
        except Exception as e:
            self._debug_log(f"Error updating checkbox: {e}", "error")
    
    @QtCore.pyqtSlot(int, str, int)
    def _display_power_sense_toggle_result(self, returncode: int, stderr: str, enabled_int: int):
        """Display power sense toggle result on main thread."""
        enabled = bool(enabled_int)  # Convert int back to bool
        try:
            if returncode == 0:
                status = "DISABLED" if enabled else "ENABLED"
                self._log(f"✓ Power sense check {status}. Device will {'skip' if enabled else 'require'} power sense on next boot.", "success")
            else:
                self._log(f"Failed to set power sense: {stderr or 'Unknown error'}", "error")
        except Exception as e:
            self._debug_log(f"Error displaying power sense result: {e}\n{traceback.format_exc()}", "error")
    
    @QtCore.pyqtSlot()
    def _display_power_sense_timeout(self):
        """Display power sense toggle timeout on main thread."""
        try:
            self._log("Power sense toggle timed out", "error")
        except Exception as e:
            self._debug_log(f"Error displaying timeout: {e}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_power_sense_error(self, error: str):
        """Display power sense toggle error on main thread."""
        try:
            self._log(f"Error: {error}", "error")
        except Exception as e:
            self._debug_log(f"Error displaying error: {e}", "error")
    
    @QtCore.pyqtSlot()
    def _display_soft_reset_timeout(self):
        """Display soft reset timeout on main thread."""
        try:
            self._log("Reset timed out - device may be unresponsive. Try disconnecting and reconnecting.", "error")
        except Exception as e:
            self._debug_log(f"Error displaying timeout: {e}", "error")
    
    @QtCore.pyqtSlot()
    def _display_soft_reset_timeout_success(self):
        """Display soft reset timeout success message (timeout is normal for soft_reset)."""
        try:
            self._log("Soft reset sent - device is restarting (timeout is normal)", "success")
        except Exception as e:
            self._debug_log(f"Error displaying timeout success: {e}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_soft_reset_error(self, error: str):
        """Display soft reset error on main thread."""
        try:
            self._log(f"Reset error: {error}", "error")
        except Exception as e:
            self._debug_log(f"Error displaying error: {e}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_restart_firmware_result(self, output: str):
        """Display restart firmware result on main thread."""
        try:
            self._log("Firmware restart initiated - device should be running main.py now", "success")
            if output:
                self._log(output, "output")
            if self._basic_mode and self._connected:
                self._set_run_stop_button_state(running=True, enabled=True)
        except Exception as e:
            self._debug_log(f"Error displaying restart firmware result: {e}\n{traceback.format_exc()}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_restart_firmware_error(self, error: str):
        """Display restart firmware error on main thread."""
        try:
            self._log(f"Error restarting firmware: {error}", "error")
            self._log("Try using Soft Reset instead, or physically reset the device", "info")
        except Exception as e:
            self._debug_log(f"Error displaying restart firmware error: {e}", "error")
    
    @QtCore.pyqtSlot()
    def _display_restart_firmware_timeout(self):
        """Display restart firmware timeout on main thread."""
        try:
            self._log("Firmware restart timed out - this is normal if firmware started running", "info")
        except Exception as e:
            self._debug_log(f"Error displaying restart firmware timeout: {e}", "error")
    
    @QtCore.pyqtSlot()
    def _display_list_files_timeout(self):
        """Display list files timeout on main thread."""
        try:
            self._log("List files timed out - device may be busy or have many files", "error")
        except Exception as e:
            self._debug_log(f"Error displaying timeout: {e}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_list_files_error(self, error: str):
        """Display list files error on main thread."""
        try:
            self._log(f"Error: {error}", "error")
        except Exception as e:
            self._debug_log(f"Error displaying error: {e}", "error")
    
    @QtCore.pyqtSlot(str)
    def _display_status_error(self, error: str):
        """Display status command error on main thread."""
        try:
            self._log(f"Error: {error}", "error")
        except Exception as e:
            self._debug_log(f"Error displaying error: {e}", "error")
    
    @QtCore.pyqtSlot()
    def _display_connection_timeout(self):
        """Display connection timeout on main thread."""
        try:
            # Validate widget exists
            if not self or not hasattr(self, 'connect_btn'):
                return
            
            self._connected = False
            self.connect_btn.setText("Connect")
            self.connect_btn.setEnabled(True)
            self._conn_section.set_connected(False)
            self._conn_section.set_meta_text("Connection timed out")
            self._log("✗ Connection timed out", "error")
            self._restore_disconnected_state()
        except Exception as e:
            error_msg = f"Error in _display_connection_timeout: {e}\n{traceback.format_exc()}"
            self._debug_log(error_msg, "error")
            # Try to restore state even on error
            try:
                if hasattr(self, '_restore_disconnected_state'):
                    self._restore_disconnected_state()
            except:
                pass
    
    @QtCore.pyqtSlot(str)
    def _display_connection_error(self, error: str):
        """Display connection error on main thread."""
        try:
            # Validate widget exists
            if not self or not hasattr(self, 'connect_btn'):
                return
            
            self._connected = False
            self.connect_btn.setText("Connect")
            self.connect_btn.setEnabled(True)
            error_display = str(error)[:50] if error else "Unknown error"
            self._conn_section.set_connected(False)
            self._conn_section.set_meta_text(f"Error: {error_display}")
            self._log(f"✗ Connection error: {error}", "error")
            self._restore_disconnected_state()
        except Exception as e:
            error_msg = f"Error in _display_connection_error: {e}\n{traceback.format_exc()}"
            self._debug_log(error_msg, "error")
            # Try to restore state even on error
            try:
                if hasattr(self, '_restore_disconnected_state'):
                    self._restore_disconnected_state()
            except:
                pass

