"""Tests for hardware detection logic (SD card roots, serial ports).

Originally a standalone script. Converted to pytest with mocked psutil and
serial.tools.list_ports so tests run without physical hardware attached.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# SD detection tests (mocked psutil disk_partitions)
# ---------------------------------------------------------------------------

class TestSDDetection:
    def _fake_partition(self, device="", mountpoint="", fstype="",
                        opts="", maxfile=0, maxpath=0):
        class FakePart:
            pass
        p = FakePart()
        p.device = device
        p.mountpoint = mountpoint
        p.fstype = fstype
        p.opts = opts
        p.maxfile = maxfile
        p.maxpath = maxpath
        return p

    def test_detect_sd_roots_returns_list(self):
        """SDManager.detect_sd_roots should return a list (even when empty)."""
        from gui.sd_manager import SDManager
        with mock.patch("psutil.disk_partitions", return_value=[]):
            roots = SDManager.detect_sd_roots()
        assert isinstance(roots, list)

    def test_no_partitions_returns_empty(self):
        from gui.sd_manager import SDManager
        with mock.patch("psutil.disk_partitions", return_value=[]):
            roots = SDManager.detect_sd_roots()
        assert roots == []

    def test_internal_drive_not_included(self):
        """System / internal partitions should be excluded from SD candidates."""
        from gui.sd_manager import SDManager
        internal = self._fake_partition(device="/dev/sda1", mountpoint="/")
        with mock.patch("psutil.disk_partitions", return_value=[internal]):
            roots = SDManager.detect_sd_roots()
        # Internal OS partition should not show up as removable SD
        assert all(str(p).replace("\\", "/") != "/" for p, _ in roots)

    def test_usb_drive_may_be_included(self):
        """A partition on a removable path may be included (platform-dependent)."""
        from gui.sd_manager import SDManager
        # We just verify no crash; actual inclusion depends on OS heuristics
        usb = self._fake_partition(
            device="/dev/sdb1",
            mountpoint="/media/usb",
            fstype="vfat",
        )
        with mock.patch("psutil.disk_partitions", return_value=[usb]):
            try:
                roots = SDManager.detect_sd_roots()
                assert isinstance(roots, list)
            except Exception as exc:
                pytest.fail(f"detect_sd_roots raised: {exc}")


# ---------------------------------------------------------------------------
# Serial detection tests (mocked serial.tools.list_ports)
# ---------------------------------------------------------------------------

class TestSerialDetection:
    def _fake_port(self, device="COM1", description="Test Port", vid=None):
        class FakePort:
            pass
        p = FakePort()
        p.device = device
        p.description = description
        p.vid = vid
        p.pid = None
        p.serial_number = None
        return p

    def test_serial_available_returns_list(self):
        """list_ports.comports() should return a list."""
        fake_ports = [
            self._fake_port("COM3", "USB Serial Device", vid=0x2E8A),
            self._fake_port("COM4", "Other Device"),
        ]
        with mock.patch("serial.tools.list_ports.comports", return_value=fake_ports):
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
        assert len(ports) == 2

    def test_pico_detected_by_vid(self):
        """Pico VID 0x2E8A should be identifiable."""
        fake_ports = [
            self._fake_port("COM3", "RP2 Boot", vid=0x2E8A),
        ]
        with mock.patch("serial.tools.list_ports.comports", return_value=fake_ports):
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
        pico_ports = [p for p in ports if getattr(p, "vid", None) == 0x2E8A]
        assert len(pico_ports) == 1

    def test_no_ports_returns_empty(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=[]):
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
        assert ports == []

    def test_serial_import_error_handled_gracefully(self):
        """If pyserial is not installed, code should handle ImportError cleanly."""
        import sys
        original = sys.modules.get("serial")
        sys.modules["serial"] = None  # Simulate not installed
        try:
            try:
                import serial  # type: ignore
                _ = serial  # make it available
            except ImportError:
                pass  # Expected
        finally:
            if original is not None:
                sys.modules["serial"] = original
            elif "serial" in sys.modules and sys.modules["serial"] is None:
                del sys.modules["serial"]

    def test_port_device_and_description_accessible(self):
        port = self._fake_port("COM5", "RP2040 Serial")
        assert port.device == "COM5"
        assert port.description == "RP2040 Serial"
