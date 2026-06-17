"""RP2040 USB serial port identification (exclude Bluetooth COM ports)."""

from __future__ import annotations

from types import SimpleNamespace

from gui.device_debug import DeviceDebugWidget


def test_rp2040_port_accepts_pico_vid():
    port = SimpleNamespace(
        device="COM6",
        vid=0x2E8A,
        pid=0x0005,
        hwid="USB VID:PID=2E8A:0005 SER=5303284740AB671C",
        description="USB Serial Device (COM6)",
        manufacturer="Microsoft",
        product=None,
        interface=None,
    )
    assert DeviceDebugWidget._is_rp2040_port(port)


def test_rp2040_port_rejects_bluetooth_com():
    port = SimpleNamespace(
        device="COM4",
        vid=None,
        pid=None,
        hwid=(
            "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_VID&0001009E_PID&4066"
            "\\C&1491C9C2&0&BC87FA9DED0A_C00000000"
        ),
        description="Standard Serial over Bluetooth link (COM4)",
        manufacturer="Microsoft",
        product=None,
        interface=None,
    )
    assert not DeviceDebugWidget._is_rp2040_port(port)


def test_install_banner_bootsel_only(monkeypatch):
    from gui.radio_manager import MainWindow, _list_rp2040_serial_ports

    mgr = MainWindow.__new__(MainWindow)
    monkeypatch.setattr(
        "gui.radio_manager.SDManager.is_rp2040_bootsel_present",
        lambda: True,
    )
    monkeypatch.setattr(
        "gui.radio_manager._list_rp2040_serial_ports",
        lambda: [],
    )
    monkeypatch.setattr(
        "gui.radio_manager._read_preferred_serial_port_from_ui",
        lambda _mgr: None,
    )

    detected, title, status, meta, on = mgr._basic_install_device_banner()
    assert detected
    assert "BOOTSEL" in title
    assert status == "Ready to flash"
    assert "RPI-RP2" in meta
    assert on


def test_install_banner_bootsel_conflict(monkeypatch):
    from gui.radio_manager import MainWindow

    mgr = MainWindow.__new__(MainWindow)
    monkeypatch.setattr(
        "gui.radio_manager.SDManager.is_rp2040_bootsel_present",
        lambda: True,
    )
    monkeypatch.setattr(
        "gui.radio_manager._list_rp2040_serial_ports",
        lambda: ["COM6"],
    )
    monkeypatch.setattr(
        "gui.radio_manager._read_preferred_serial_port_from_ui",
        lambda _mgr: None,
    )

    detected, title, status, meta, on = mgr._basic_install_device_banner()
    assert detected
    assert "conflict" in title.lower()
    assert not on
    assert "COM6" in meta
