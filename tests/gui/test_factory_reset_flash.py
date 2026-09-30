"""Tests for factory reset / flash_nuke install helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from gui import radio_manager as rm


def test_fetch_flash_nuke_caches(tmp_path, monkeypatch):
    from gui.services import firmware_bundle as fb

    cache = tmp_path / "flash_nuke"
    cache.mkdir(parents=True)
    monkeypatch.setattr(fb, "_flash_nuke_cache_dir", lambda: cache)

    class FakeResp:
        def read(self):
            return b"UF2\n" + b"\x00" * 2000

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(fb.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    path = fb.fetch_flash_nuke_uf2()
    assert path.is_file()
    assert path.stat().st_size > 1000


def test_flash_micropython_for_install_retries_factory_reset(monkeypatch):
    calls: list[str] = []

    class FakeMainWindow:
        def _flash_micropython_uf2_to_bootsel_core(
            self,
            progress_callback,
            preferred_serial_port,
            should_cancel=None,
        ):
            calls.append("flash")
            return True, ""

        def _factory_reset_reflash_micropython(
            self,
            progress_callback,
            preferred_serial_port,
        ):
            calls.append("factory")
            return True, ""

    monkeypatch.setattr(
        rm,
        "_verify_stock_micropython_serial",
        lambda *a, **k: "still running third-party firmware",
    )

    ok, err = rm.MainWindow._flash_micropython_for_install(
        FakeMainWindow(), None, None,
    )
    assert ok
    assert err == ""
    assert calls == ["flash", "factory"]


def test_flash_micropython_for_install_skips_factory_when_verified(monkeypatch):
    calls: list[str] = []

    class FakeMainWindow:
        def _flash_micropython_uf2_to_bootsel_core(
            self,
            progress_callback,
            preferred_serial_port,
            should_cancel=None,
        ):
            calls.append("flash")
            return True, ""

        def _factory_reset_reflash_micropython(
            self,
            progress_callback,
            preferred_serial_port,
        ):
            calls.append("factory")
            return False, "should not run"

    monkeypatch.setattr(rm, "_verify_stock_micropython_serial", lambda *a, **k: None)

    ok, err = rm.MainWindow._flash_micropython_for_install(
        FakeMainWindow(), None, None,
    )
    assert ok
    assert calls == ["flash"]


def test_factory_erase_prefers_picotool(tmp_path, monkeypatch):
    picotool = tmp_path / "picotool.exe"
    picotool.write_bytes(b"stub")

    monkeypatch.setattr(rm, "_find_picotool_executable", lambda: picotool)
    monkeypatch.setattr(
        rm,
        "_run_picotool",
        lambda args, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    ok, err, method = rm._factory_erase_rp2040_flash(tmp_path, progress_callback=None)
    assert ok
    assert method == "picotool"
    assert err == ""


def test_factory_erase_falls_back_to_flash_nuke_when_picotool_fails(
    tmp_path, monkeypatch,
):
    picotool = tmp_path / "picotool"
    picotool.write_bytes(b"stub")
    nuke = tmp_path / "flash_nuke.uf2"
    nuke.write_bytes(b"UF2")

    monkeypatch.setattr(rm, "_find_picotool_executable", lambda: picotool)
    monkeypatch.setattr(
        rm,
        "_run_picotool",
        lambda args, **kw: SimpleNamespace(
            returncode=1, stdout="", stderr="erase failed",
        ),
    )
    monkeypatch.setattr(
        "gui.services.firmware_bundle.fetch_flash_nuke_uf2",
        lambda: nuke,
    )
    monkeypatch.setattr(
        rm,
        "_copy_uf2_to_rpi_rp2",
        lambda path, dest, **kw: (True, ""),
    )

    ok, err, method = rm._factory_erase_rp2040_flash(tmp_path)
    assert ok
    assert method == "nuke"
    assert err == ""


def test_factory_erase_fails_when_picotool_and_nuke_copy_fail(tmp_path, monkeypatch):
    picotool = tmp_path / "picotool"
    picotool.write_bytes(b"stub")
    nuke = tmp_path / "flash_nuke.uf2"
    nuke.write_bytes(b"UF2")

    monkeypatch.setattr(rm, "_find_picotool_executable", lambda: picotool)
    monkeypatch.setattr(
        rm,
        "_run_picotool",
        lambda args, **kw: SimpleNamespace(returncode=1, stdout="", stderr="fail"),
    )
    monkeypatch.setattr(
        "gui.services.firmware_bundle.fetch_flash_nuke_uf2",
        lambda: nuke,
    )
    monkeypatch.setattr(
        rm,
        "_copy_uf2_to_rpi_rp2",
        lambda path, dest, **kw: (False, "RPI-RP2 drive not found"),
    )

    ok, err, method = rm._factory_erase_rp2040_flash(tmp_path)
    assert not ok
    assert "RPI-RP2" in err
    assert method == ""
