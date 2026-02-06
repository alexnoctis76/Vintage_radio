"""Firmware Management Widget - Thonny replacement for Pico management."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets


class FirmwareManagerWidget(QtWidgets.QWidget):
    """Widget for managing Raspberry Pi Pico firmware - replaces Thonny functionality."""
    
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._check_mpremote()
        self._scan_ports()
    
    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Title
        title = QtWidgets.QLabel("Firmware Manager")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        
        # Connection section
        conn_group = QtWidgets.QGroupBox("Connection")
        conn_layout = QtWidgets.QVBoxLayout(conn_group)
        
        port_layout = QtWidgets.QHBoxLayout()
        port_layout.addWidget(QtWidgets.QLabel("COM Port:"))
        self.port_combo = QtWidgets.QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(150)
        port_layout.addWidget(self.port_combo)
        
        self.scan_btn = QtWidgets.QPushButton("Scan Ports")
        self.scan_btn.clicked.connect(self._scan_ports)
        port_layout.addWidget(self.scan_btn)
        
        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.connect_btn.clicked.connect(self._test_connection)
        port_layout.addWidget(self.connect_btn)
        
        port_layout.addStretch()
        conn_layout.addLayout(port_layout)
        
        self.connection_status = QtWidgets.QLabel("Not connected")
        self.connection_status.setStyleSheet("color: gray;")
        conn_layout.addWidget(self.connection_status)
        
        layout.addWidget(conn_group)
        
        # Flash firmware section
        flash_group = QtWidgets.QGroupBox("Flash Firmware")
        flash_layout = QtWidgets.QVBoxLayout(flash_group)
        
        info_label = QtWidgets.QLabel(
            "Flash the Vintage Radio firmware files to the connected Pico."
        )
        info_label.setWordWrap(True)
        flash_layout.addWidget(info_label)
        
        flash_btn = QtWidgets.QPushButton("Flash Firmware")
        flash_btn.clicked.connect(self._flash_firmware)
        flash_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        flash_layout.addWidget(flash_btn)
        
        self.flash_status = QtWidgets.QLabel("")
        flash_layout.addWidget(self.flash_status)
        
        layout.addWidget(flash_group)
        
        # File management section
        files_group = QtWidgets.QGroupBox("Pico Filesystem")
        files_layout = QtWidgets.QVBoxLayout(files_group)
        
        files_btn_layout = QtWidgets.QHBoxLayout()
        self.list_files_btn = QtWidgets.QPushButton("List Files")
        self.list_files_btn.clicked.connect(self._list_files)
        files_btn_layout.addWidget(self.list_files_btn)
        
        self.upload_file_btn = QtWidgets.QPushButton("Upload File")
        self.upload_file_btn.clicked.connect(self._upload_file)
        files_btn_layout.addWidget(self.upload_file_btn)
        
        self.delete_file_btn = QtWidgets.QPushButton("Delete File")
        self.delete_file_btn.clicked.connect(self._delete_file)
        files_btn_layout.addWidget(self.delete_file_btn)
        
        files_btn_layout.addStretch()
        files_layout.addLayout(files_btn_layout)
        
        self.files_list = QtWidgets.QListWidget()
        self.files_list.setMaximumHeight(150)
        files_layout.addWidget(self.files_list)
        
        layout.addWidget(files_group)
        
        # REPL/Console section
        repl_group = QtWidgets.QGroupBox("REPL Console")
        repl_layout = QtWidgets.QVBoxLayout(repl_group)
        
        repl_btn_layout = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Run main.py")
        self.run_btn.clicked.connect(self._run_firmware)
        repl_btn_layout.addWidget(self.run_btn)
        
        self.repl_btn = QtWidgets.QPushButton("Open REPL")
        self.repl_btn.clicked.connect(self._open_repl)
        repl_btn_layout.addWidget(self.repl_btn)
        
        self.reset_btn = QtWidgets.QPushButton("Soft Reset")
        self.reset_btn.clicked.connect(self._soft_reset)
        repl_btn_layout.addWidget(self.reset_btn)
        
        repl_btn_layout.addStretch()
        repl_layout.addLayout(repl_btn_layout)
        
        self.console_output = QtWidgets.QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setMaximumHeight(200)
        self.console_output.setFont(QtGui.QFont("Courier", 9))
        repl_layout.addWidget(self.console_output)
        
        layout.addWidget(repl_group)
        
        layout.addStretch()
    
    def _check_mpremote(self) -> None:
        """Check if mpremote is installed."""
        try:
            result = subprocess.run(
                ["mpremote", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                self._log("mpremote is installed")
            else:
                self._log("WARNING: mpremote not found. Install with: pip install mpremote", "error")
        except FileNotFoundError:
            self._log("ERROR: mpremote not found. Install with: pip install mpremote", "error")
        except Exception as e:
            self._log(f"Error checking mpremote: {e}", "error")
    
    def _scan_ports(self) -> None:
        """Scan for available COM ports."""
        self.port_combo.clear()
        
        try:
            # Windows: scan COM1-COM20
            if sys.platform == "win32":
                try:
                    import serial.tools.list_ports
                    ports = serial.tools.list_ports.comports()
                    for port in ports:
                        self.port_combo.addItem(port.device, port.description)
                except ImportError:
                    # Fallback: try common COM ports
                    for i in range(1, 21):
                        self.port_combo.addItem(f"COM{i}")
            else:
                # Linux/Mac: common paths
                import glob
                for port in glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"):
                    self.port_combo.addItem(port)
        except Exception as e:
            self._log(f"Error scanning ports: {e}", "error")
        
        if self.port_combo.count() == 0:
            self.port_combo.addItem("No ports found")
            self._log("No COM ports found. Make sure Pico is connected.")
        else:
            self._log(f"Found {self.port_combo.count()} port(s)")
    
    def _get_port(self) -> Optional[str]:
        """Get selected COM port."""
        port = self.port_combo.currentText()
        if not port or port == "No ports found":
            return None
        return port
    
    def _run_mpremote(self, args: List[str], capture_output: bool = True) -> subprocess.CompletedProcess:
        """Run mpremote command."""
        port = self._get_port()
        if not port:
            raise ValueError("No port selected")
        
        cmd = ["mpremote", "connect", port] + args
        return subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            timeout=30
        )
    
    def _test_connection(self) -> None:
        """Test connection to Pico."""
        port = self._get_port()
        if not port:
            QtWidgets.QMessageBox.warning(self, "No Port", "Please select a COM port first.")
            return
        
        self.connect_btn.setEnabled(False)
        self.connection_status.setText("Testing connection...")
        self.connection_status.setStyleSheet("color: orange;")
        
        def test():
            try:
                result = self._run_mpremote(["exec", "import sys; print(sys.version)"])
                if result.returncode == 0:
                    self.connection_status.setText(f"Connected to {port}")
                    self.connection_status.setStyleSheet("color: green;")
                    self._log(f"Connection successful! {result.stdout.strip()}")
                else:
                    self.connection_status.setText("Connection failed")
                    self.connection_status.setStyleSheet("color: red;")
                    self._log(f"Connection failed: {result.stderr}", "error")
            except Exception as e:
                self.connection_status.setText("Connection failed")
                self.connection_status.setStyleSheet("color: red;")
                self._log(f"Connection error: {e}", "error")
            finally:
                self.connect_btn.setEnabled(True)
        
        threading.Thread(target=test, daemon=True).start()
    
    def _flash_firmware(self) -> None:
        """Flash firmware files to Pico."""
        port = self._get_port()
        if not port:
            QtWidgets.QMessageBox.warning(self, "No Port", "Please select a COM port first.")
            return
        
        # Check if files exist
        project_root = Path(__file__).resolve().parent.parent
        files_to_flash = [
            ("radio_core.py", project_root / "radio_core.py"),
            ("main.py", project_root / "main.py"),
            ("firmware/dfplayer_hardware.py", project_root / "firmware" / "dfplayer_hardware.py"),
        ]
        
        missing = [name for name, path in files_to_flash if not path.exists()]
        if missing:
            QtWidgets.QMessageBox.warning(
                self,
                "Files Missing",
                f"The following files are missing:\n" + "\n".join(missing)
            )
            return
        
        self.flash_status.setText("Flashing firmware...")
        self.flash_status.setStyleSheet("color: orange;")
        
        def flash():
            try:
                # Create firmware directory
                result = self._run_mpremote(["mkdir", "firmware"])
                if result.returncode != 0:
                    self._log(f"Warning: Could not create firmware directory: {result.stderr}")
                
                # Flash each file
                for name, path in files_to_flash:
                    self._log(f"Flashing {name}...")
                    if "/" in name:
                        # File in subdirectory
                        result = self._run_mpremote(["cp", str(path), f":{name}"])
                    else:
                        result = self._run_mpremote(["cp", str(path), f":{name}"])
                    
                    if result.returncode == 0:
                        self._log(f"✓ {name} flashed successfully")
                    else:
                        self._log(f"✗ Failed to flash {name}: {result.stderr}", "error")
                        self.flash_status.setText(f"Failed to flash {name}")
                        self.flash_status.setStyleSheet("color: red;")
                        return
                
                self.flash_status.setText("Firmware flashed successfully!")
                self.flash_status.setStyleSheet("color: green;")
                self._log("✓ All files flashed successfully!")
                
            except Exception as e:
                self.flash_status.setText(f"Error: {e}")
                self.flash_status.setStyleSheet("color: red;")
                self._log(f"Flash error: {e}", "error")
        
        threading.Thread(target=flash, daemon=True).start()
    
    def _list_files(self) -> None:
        """List files on Pico."""
        def list_files():
            try:
                result = self._run_mpremote(["ls"])
                if result.returncode == 0:
                    self.files_list.clear()
                    files = result.stdout.strip().split("\n")
                    for file in files:
                        if file.strip():
                            self.files_list.addItem(file.strip())
                    self._log(f"Listed {len(files)} file(s)")
                else:
                    self._log(f"Failed to list files: {result.stderr}", "error")
            except Exception as e:
                self._log(f"List files error: {e}", "error")
        
        threading.Thread(target=list_files, daemon=True).start()
    
    def _upload_file(self) -> None:
        """Upload a file to Pico."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select file to upload",
            "",
            "Python Files (*.py);;All Files (*)"
        )
        if not file_path:
            return
        
        def upload():
            try:
                filename = Path(file_path).name
                result = self._run_mpremote(["cp", file_path, f":{filename}"])
                if result.returncode == 0:
                    self._log(f"✓ Uploaded {filename}")
                    self._list_files()
                else:
                    self._log(f"✗ Upload failed: {result.stderr}", "error")
            except Exception as e:
                self._log(f"Upload error: {e}", "error")
        
        threading.Thread(target=upload, daemon=True).start()
    
    def _delete_file(self) -> None:
        """Delete selected file from Pico."""
        item = self.files_list.currentItem()
        if not item:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select a file to delete.")
            return
        
        filename = item.text()
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete {filename} from Pico?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        
        def delete():
            try:
                result = self._run_mpremote(["rm", filename])
                if result.returncode == 0:
                    self._log(f"✓ Deleted {filename}")
                    self._list_files()
                else:
                    self._log(f"✗ Delete failed: {result.stderr}", "error")
            except Exception as e:
                self._log(f"Delete error: {e}", "error")
        
        threading.Thread(target=delete, daemon=True).start()
    
    def _run_firmware(self) -> None:
        """Run main.py on Pico."""
        def run():
            try:
                self._log("Running main.py...")
                result = self._run_mpremote(["run", "main.py"], capture_output=False)
                # Note: This will block, so we run it in a thread
            except Exception as e:
                self._log(f"Run error: {e}", "error")
        
        threading.Thread(target=run, daemon=True).start()
    
    def _open_repl(self) -> None:
        """Open REPL in external terminal."""
        port = self._get_port()
        if not port:
            QtWidgets.QMessageBox.warning(self, "No Port", "Please select a COM port first.")
            return
        
        import os
        if sys.platform == "win32":
            os.system(f'start cmd /k mpremote connect {port} repl')
        elif sys.platform == "darwin":
            os.system(f'osascript -e \'tell app "Terminal" to do script "mpremote connect {port} repl"\'')
        else:
            os.system(f'xterm -e "mpremote connect {port} repl" &')
    
    def _soft_reset(self) -> None:
        """Soft reset Pico (Ctrl+D)."""
        def reset():
            try:
                result = self._run_mpremote(["exec", "\x04"])  # Ctrl+D
                self._log("Soft reset sent")
            except Exception as e:
                self._log(f"Reset error: {e}", "error")
        
        threading.Thread(target=reset, daemon=True).start()
    
    def _log(self, message: str, level: str = "info") -> None:
        """Log message to console."""
        color_map = {
            "info": "black",
            "error": "red",
            "success": "green",
            "warning": "orange"
        }
        color = color_map.get(level, "black")
        self.console_output.append(f'<span style="color: {color};">{message}</span>')
        # Auto-scroll to bottom
        self.console_output.verticalScrollBar().setValue(
            self.console_output.verticalScrollBar().maximum()
        )

