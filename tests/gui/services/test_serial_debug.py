from __future__ import annotations

from gui.services.serial_debug import is_recoverable_usb_serial_error, serial_io_errno


def test_serial_io_errno_prefers_errno_from_oserror():
    err = OSError(6, "Device not configured")
    assert serial_io_errno(err) == 6


def test_is_recoverable_usb_serial_error_by_errno():
    assert is_recoverable_usb_serial_error(OSError(6, "Device not configured")) is True
    assert is_recoverable_usb_serial_error(OSError(19, "No such device")) is True


def test_is_recoverable_usb_serial_error_by_message():
    class FakeExc(Exception):
        pass

    assert is_recoverable_usb_serial_error(FakeExc("could not configure port")) is True
    assert is_recoverable_usb_serial_error(FakeExc("unrelated failure")) is False
