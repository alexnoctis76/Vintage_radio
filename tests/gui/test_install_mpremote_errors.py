"""Tests for mpremote install error formatting."""

from __future__ import annotations

from gui import radio_manager as rm
from gui.radio_manager import (
    _find_rp2040_serial_port,
    _format_install_mpremote_error,
    _mpremote_args_with_connect,
    _post_flash_serial_timeout_message,
    _serial_output_indicates_blocking_firmware,
    _setup_device_failure_message,
    _wait_mpremote_serial_ready,
)


def test_blocking_firmware_message():
    err = "Booting Retro Radio Baseline 26.0.1\ncould not enter raw repl"
    msg = _format_install_mpremote_error(err)
    assert "blocks file transfer" in msg
    assert "MicroPython" in msg
    assert "Zbvr" not in msg


def test_clearcommerror_message():
    err = "ClearCommError failed (PermissionError(13, 'The device does not recognize the command.'"
    msg = _format_install_mpremote_error(err)
    assert "COM port" in msg
    assert "Debugger" in msg


def test_raw_repl_generic_message():
    msg = _format_install_mpremote_error("TransportError: could not enter raw repl")
    assert "raw REPL" in msg


def test_detect_blocking_serial():
    label = _serial_output_indicates_blocking_firmware("Booting Retro Radio Baseline 26.0.1")
    assert label == "third-party firmware"


def test_detect_blocking_serial_loading_modules():
    sniff = "Loading Module: LED\nLoading Module: DFPlayer\nLoading Module: Controls"
    assert _serial_output_indicates_blocking_firmware(sniff) == "third-party firmware"


def test_detect_blocking_serial_idle_now_playing():
    sniff = (
        "Now Playing: Album 01 Track 001\n"
        "DFPlayer online, ready to proceed\n"
        "Filesystem has 114 files in 6 folders"
    )
    assert _serial_output_indicates_blocking_firmware(sniff) == "third-party firmware"


def test_vintage_radio_firmware_not_blocking():
    from gui.radio_manager import (
        _serial_output_indicates_vintage_radio_firmware,
        _sniff_suggests_app_firmware,
    )

    boot = "Booting Vintage Radio (BASIC MODE)\n--- DFPlayer comms check (basic mode) ---"
    assert _serial_output_indicates_vintage_radio_firmware(boot)
    assert _serial_output_indicates_blocking_firmware(boot) is None

    idle = "BASIC MODE active. Button patterns:\nDF: Playing folder=01 track=001"
    assert _serial_output_indicates_vintage_radio_firmware(idle)
    assert _serial_output_indicates_blocking_firmware(idle) is None
    assert not _sniff_suggests_app_firmware(idle)


def test_pico_assessment_vintage_radio_runs_mpremote(monkeypatch):
    sniff = (
        "Booting Vintage Radio (BASIC MODE)\n"
        "BASIC MODE active. Button patterns:\n"
    )
    monkeypatch.setattr(rm, "_find_rp2040_serial_port", lambda preferred=None: "COM6")
    monkeypatch.setattr(rm, "_sniff_rp2040_serial_text", lambda *a, **k: sniff)

    probe_calls: list[str] = []

    def fake_probe(_cmd, port, cwd, **kw):
        probe_calls.append(port)
        return type("R", (), {"returncode": 0, "stdout": "micropython", "stderr": ""})()

    def fake_run(_cmd, args, **_kw):
        return type(
            "R",
            (),
            {"returncode": 0, "stdout": "VR_INSTALL_PROBE 8", "stderr": ""},
        )()

    monkeypatch.setattr(rm, "_run_mpremote_probe", fake_probe)
    monkeypatch.setattr(rm, "_run_mpremote", fake_run)
    result = rm._pico_install_assessment(["mpremote"], rm.Path("."))
    assert result["status"] == "ready"
    assert probe_calls == ["COM6"]


def test_micropython_cache_uses_app_data_dir(tmp_path, monkeypatch):
    from gui.services import firmware_bundle as fb

    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setattr(fb, "app_data_dir", lambda: data)
    cache = fb._micropython_cache_dir()
    assert cache == data / "firmware_cache" / "micropython"
    assert cache.is_dir()


def test_sniff_suggests_app_firmware():
    from gui.radio_manager import _sniff_suggests_app_firmware, _sniff_suggests_stock_micropython_repl

    idle = "Now Playing: Album 01 Track 001\nDFPlayer online"
    assert _sniff_suggests_app_firmware(idle)
    assert not _sniff_suggests_stock_micropython_repl(idle)
    assert not _sniff_suggests_app_firmware("MicroPython v1.23.0 on 2024-01-01; Raspberry Pi Pico\n>>> ")


def test_pico_assessment_skips_mpremote_for_idle_app(monkeypatch):
    sniff = (
        "Now Playing: Album 01 Track 001\n"
        "DFPlayer online, ready to proceed\n"
        "Filesystem has 114 files in 6 folders"
    )
    monkeypatch.setattr(rm, "_find_rp2040_serial_port", lambda preferred=None: "COM6")
    monkeypatch.setattr(rm, "_sniff_rp2040_serial_text", lambda *a, **k: sniff)

    def fail_mpremote(*_a, **_k):
        raise AssertionError("mpremote should not run for idle app firmware")

    monkeypatch.setattr(rm, "_run_mpremote_probe", fail_mpremote)
    result = rm._pico_install_assessment(["mpremote"], rm.Path("."))
    assert result["status"] == "needs_reflash"
    assert result["blocking_label"] == "third-party firmware"


def test_bootsel_preflight_rejects_active_serial(tmp_path, monkeypatch):
    info = tmp_path / "INFO_UF2.TXT"
    info.write_text("UF2 Bootloader v3.0\nModel: Raspberry Pi RP2\n", encoding="utf-8")

    from gui.radio_manager import MainWindow

    mgr = MainWindow.__new__(MainWindow)
    monkeypatch.setattr(mgr, "_is_rpi_rp2_present", lambda: True)
    monkeypatch.setattr(mgr, "_resolve_bootsel_drive", lambda: tmp_path)
    monkeypatch.setattr(rm, "_find_rp2040_serial_port", lambda preferred=None: "COM6")
    monkeypatch.setattr(rm, "_wait_for_serial_port_gone", lambda **kw: False)

    ok, detail = mgr._bootsel_preflight_for_uf2_flash("COM6")
    assert not ok
    assert "COM6" in detail


def test_authentic_bootsel_volume(tmp_path):
    from gui.radio_manager import _is_authentic_rp2040_bootsel_volume

    info = tmp_path / "INFO_UF2.TXT"
    info.write_text("UF2 Bootloader v3.0\nModel: Raspberry Pi RP2\n", encoding="utf-8")
    ok, _ = _is_authentic_rp2040_bootsel_volume(tmp_path)
    assert ok

    empty = tmp_path / "empty"
    empty.mkdir()
    ok, detail = _is_authentic_rp2040_bootsel_volume(empty)
    assert not ok
    assert "INFO_UF2" in detail


def test_setup_message_explains_third_party_vs_micropython():
    msg = _setup_device_failure_message(
        probe_outputs=["Booting Retro Radio Baseline 26.0.1"],
        timed_out=False,
    )
    assert "third-party firmware" in msg
    assert "Zbvr" not in msg
    assert "not enough" in msg.lower() or "official MicroPython" in msg


def test_wait_mpremote_uses_explicit_port(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(_cmd, args, **_kw):
        calls.append(list(args))
        return type("R", (), {"returncode": 0, "stdout": "micropython", "stderr": ""})()

    monkeypatch.setattr(rm, "_run_mpremote", fake_run)
    monkeypatch.setattr(rm, "_find_rp2040_serial_port", lambda preferred=None: "COM6")

    import time as time_mod

    monkeypatch.setattr(time_mod, "sleep", lambda _s: None)

    assert _wait_mpremote_serial_ready(
        ["mpremote"],
        ".",
        progress_callback=None,
        total_steps=1,
        deadline_s=1.0,
        poll_s=0.01,
    ) is None
    assert calls
    assert calls[0][:2] == ["connect", "COM6"]


def test_mpremote_args_with_connect_inserts_port():
    assert _mpremote_args_with_connect(["exec", "print(1)"], "COM6") == [
        "connect",
        "COM6",
        "exec",
        "print(1)",
    ]


def test_post_flash_timeout_message_detects_blocking(monkeypatch):
    monkeypatch.setattr(
        rm,
        "_sniff_rp2040_serial_text",
        lambda _port, **kw: "Booting Retro Radio Baseline 26.0.1",
    )
    msg = _post_flash_serial_timeout_message("COM6")
    assert "still looks like third-party firmware" in msg
    assert "BOOTSEL" in msg


def test_find_rp2040_port_prefers_device_selection(monkeypatch):
    monkeypatch.setattr(
        rm,
        "_list_rp2040_serial_ports",
        lambda: ["COM3", "COM12"],
    )
    assert _find_rp2040_serial_port(preferred="COM12") == "COM12"
    assert _find_rp2040_serial_port(preferred="COM99") == "COM3"
    assert _find_rp2040_serial_port() == "COM3"


def test_wait_mpremote_fails_fast_when_blocking_after_uf2(monkeypatch):
    probe_text = "Booting Retro Radio Baseline 26.0.1\ncould not enter raw repl"

    def fake_run(_cmd, args, **_kw):
        return type("R", (), {"returncode": 1, "stdout": probe_text, "stderr": ""})()

    monkeypatch.setattr(rm, "_run_mpremote", fake_run)
    monkeypatch.setattr(rm, "_find_rp2040_serial_port", lambda preferred=None: "COM6")
    monkeypatch.setattr(rm, "_sniff_rp2040_serial_text", lambda _port, **kw: "")

    import time as time_mod

    monkeypatch.setattr(time_mod, "sleep", lambda _s: None)

    err = _wait_mpremote_serial_ready(
        ["mpremote"],
        ".",
        progress_callback=None,
        total_steps=1,
        deadline_s=30.0,
        poll_s=0.01,
        after_uf2_flash=True,
    )
    assert err is not None
    assert "still running" in err
    assert ".uf2 flash" in err.lower()
