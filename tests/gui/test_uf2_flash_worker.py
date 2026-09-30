"""Custom UF2 flash must use the progress worker, not main-thread copy."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gui.radio_manager import (
    MainWindow,
    _UF2_COPY_CHUNK_BYTES,
    _UF2_REBOOT_WAIT_OPTIONAL_S,
    _UF2_REBOOT_WAIT_REQUIRED_S,
    _copy_uf2_to_rpi_rp2,
    _flash_uf2_file,
    _mpremote_result_indicates_exec_ready,
    _mpremote_result_indicates_usable,
    _post_flash_config_inject_timeout_message,
    _uf2_flash_initial_progress_message,
    _wait_for_mpremote_usable_after_uf2,
)


def test_install_custom_uf2_routes_to_progress_helper(tmp_path):
    uf2 = tmp_path / "custom.uf2"
    uf2.write_bytes(b"uf2")
    mgr = MagicMock()
    entry = {"config_path": ""}

    MainWindow._install_custom_uf2_to_pico(mgr, uf2, entry=entry)

    mgr._run_uf2_flash_with_progress.assert_called_once_with(
        uf2, entry=entry, title="Install firmware"
    )


def test_run_uf2_flash_with_progress_uses_task_progress_dialog(tmp_path):
    uf2 = tmp_path / "custom.uf2"
    uf2.write_bytes(b"uf2")
    mgr = MagicMock()
    mgr._prepare_config_injections_for_uf2 = MagicMock(return_value=[("a.py", "config.py")])

    exec_calls: list = []

    class FakeDlg:
        def __init__(self, **kwargs):
            exec_calls.append(kwargs)

        def exec(self):
            return 0

    with patch("gui.radio_manager.TaskProgressDialog", FakeDlg), patch(
        "gui.radio_manager._read_preferred_serial_port_from_ui", return_value=None
    ), patch(
        "gui.uf2_install_profile.firmware_entry_supports_config", return_value=True
    ):
        MainWindow._run_uf2_flash_with_progress(
            mgr,
            uf2,
            entry={"kind": "uf2", "config_path": "a.py", "supports_config": True},
            title="Install firmware",
        )

    assert len(exec_calls) == 1
    assert exec_calls[0]["func"] == mgr._flash_uf2_with_config_worker
    assert exec_calls[0]["kwargs"]["uf2_path_str"] == str(uf2)
    assert exec_calls[0]["kwargs"]["config_injections"] == [("a.py", "config.py")]
    assert exec_calls[0]["kwargs"]["supports_config"] is True
    assert exec_calls[0]["on_before_start"] is not None


def test_flash_uf2_worker_does_not_use_shutil_copy2_on_main_thread(tmp_path):
    """Worker path uses _flash_uf2_file; legacy _flash_uf2_to_bootsel used shutil.copy2."""
    uf2 = tmp_path / "fw.uf2"
    uf2.write_bytes(b"uf2")
    # Static check: custom install no longer references _flash_uf2_to_bootsel
    rm_source = Path(__file__).resolve().parents[2] / "gui" / "radio_manager.py"
    text = rm_source.read_text(encoding="utf-8")
    custom_block = text.split("def _install_custom_uf2_to_pico", 1)[1].split(
        "def _wait_for_bootsel_with_progress", 1
    )[0]
    assert "_flash_uf2_to_bootsel" not in custom_block
    assert "_run_uf2_flash_with_progress" in custom_block


def test_mpremote_usable_probe_accepts_vr_ok():
    ok = SimpleNamespace(returncode=0, stdout="vr_ok\n", stderr="")
    bad = SimpleNamespace(returncode=0, stdout="micropython\n", stderr="")
    assert _mpremote_result_indicates_usable(ok)
    assert not _mpremote_result_indicates_usable(bad)


def test_mpremote_exec_ready_probe_accepts_micropython():
    ok = SimpleNamespace(returncode=0, stdout="mpremote_ok\n", stderr="")
    mp = SimpleNamespace(returncode=0, stdout="micropython\n", stderr="")
    bad = SimpleNamespace(returncode=0, stdout="booting retro radio\n", stderr="")
    assert _mpremote_result_indicates_exec_ready(ok)
    assert _mpremote_result_indicates_exec_ready(mp)
    assert not _mpremote_result_indicates_exec_ready(bad)


def test_post_flash_config_inject_timeout_message_mentions_micropython():
    msg = _post_flash_config_inject_timeout_message()
    assert "MicroPython" in msg
    assert "Third-party" in msg


@patch("gui.radio_manager.time.monotonic", side_effect=[0.0, 3.0, 3.0, 3.0])
@patch("gui.radio_manager._sniff_rp2040_serial_text", return_value="booting zbvr\n")
@patch("gui.radio_manager._run_mpremote")
@patch("gui.radio_manager._find_rp2040_serial_port", return_value="COM7")
@patch("gui.radio_manager.time.sleep")
def test_wait_for_mpremote_usable_after_uf2_fails_fast_on_third_party(
    _sleep, _port, run_mp, _sniff, _mono,
):
    err = _wait_for_mpremote_usable_after_uf2(
        ["mpremote"],
        ".",
        preferred_port="COM7",
        deadline_s=30.0,
        poll_s=0.01,
        initial_sleep_s=0.0,
    )
    assert err is not None
    assert "MicroPython" in err
    run_mp.assert_not_called()


@patch("gui.radio_manager._run_mpremote")
@patch("gui.radio_manager._find_rp2040_serial_port", return_value=None)
@patch("gui.radio_manager.time.sleep")
def test_wait_for_mpremote_usable_after_uf2_fails_when_no_com_port(_sleep, _port, run_mp):
    err = _wait_for_mpremote_usable_after_uf2(
        ["mpremote"],
        ".",
        deadline_s=30.0,
        poll_s=0.01,
        initial_sleep_s=0.0,
        no_port_fail_s=0.0,
    )
    assert err is not None
    assert "MicroPython" in err
    run_mp.assert_not_called()


@patch("gui.radio_manager.time.monotonic", side_effect=[0.0, 0.0, 0.0, 0.0, 0.0])
@patch("gui.radio_manager._sniff_rp2040_serial_text", return_value="")
@patch("gui.radio_manager._run_mpremote")
@patch("gui.radio_manager._find_rp2040_serial_port", return_value="COM7")
@patch("gui.radio_manager.time.sleep")
def test_wait_for_mpremote_usable_after_uf2_uses_exec_probe(_sleep, _port, run_mp, _sniff, _mono):
    run_mp.return_value = SimpleNamespace(returncode=0, stdout="mpremote_ok\n", stderr="")
    err = _wait_for_mpremote_usable_after_uf2(
        ["mpremote"],
        ".",
        preferred_port="COM7",
        deadline_s=1.0,
        poll_s=0.01,
        initial_sleep_s=0.0,
    )
    assert err is None
    args = run_mp.call_args[0][1]
    assert "mpremote_ok" in args[-1]


@patch("gui.radio_manager._wait_for_bootsel_volume_gone", return_value=True)
@patch("gui.radio_manager.os.fsync")
def test_copy_uf2_to_rpi_rp2_reports_chunked_progress(_fsync, _gone, tmp_path):
    bootsel = tmp_path / "RPI-RP2"
    bootsel.mkdir()
    (bootsel / "INDEX.HTM").write_text("<html></html>", encoding="utf-8")

    uf2 = tmp_path / "test.uf2"
    size = _UF2_COPY_CHUNK_BYTES * 2 + 100
    uf2.write_bytes(b"UF2\n\x00" + b"x" * (size - 5))

    progress: list[tuple[int, int, str]] = []

    def _cb(cur: int, tot: int, msg: str) -> None:
        progress.append((cur, tot, msg))

    ok, err = _copy_uf2_to_rpi_rp2(uf2, bootsel, progress_callback=_cb)
    assert ok
    assert err == ""
    assert (bootsel / "test.uf2").stat().st_size == size

    byte_updates = [(c, t) for c, t, _m in progress if t > 0]
    assert len(byte_updates) >= 3
    assert byte_updates[-1] == (size, size)
    assert any("Writing" in m for _c, _t, m in progress)
    assert any("Finalizing" in m for _c, _t, m in progress)


def test_uf2_flash_initial_progress_message_includes_windows_note():
    msg = _uf2_flash_initial_progress_message(preparing="Preparing…")
    if __import__("sys").platform == "win32":
        assert "Not Responding" in msg
    else:
        assert msg == "Preparing…"


@patch("gui.radio_manager._wait_for_bootsel_volume_gone", return_value=True)
@patch("gui.radio_manager._run_picotool")
@patch("gui.radio_manager._find_picotool_executable", return_value=Path("picotool.exe"))
@patch("gui.radio_manager.time.sleep")
def test_flash_uf2_file_picotool_waits_for_reboot(_sleep, _find_picotool, _run_picotool, _gone, tmp_path):
    uf2 = tmp_path / "fw.uf2"
    uf2.write_bytes(b"uf2")
    _run_picotool.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
    ok, err = _flash_uf2_file(uf2, tmp_path, reboot_required=True)
    assert ok
    assert err == ""
    _gone.assert_called_once_with(
        timeout_s=_UF2_REBOOT_WAIT_REQUIRED_S,
        progress_callback=None,
        should_cancel=None,
    )
    _sleep.assert_called()


@patch("gui.radio_manager._wait_for_bootsel_volume_gone", return_value=False)
@patch("gui.radio_manager.os.fsync")
def test_copy_uf2_optional_reboot_succeeds_when_drive_stays(_fsync, _gone, tmp_path):
    bootsel = tmp_path / "RPI-RP2"
    bootsel.mkdir()
    (bootsel / "INDEX.HTM").write_text("<html></html>", encoding="utf-8")
    uf2 = tmp_path / "standalone.uf2"
    uf2.write_bytes(b"UF2\n\x00" + b"x" * 100)
    ok, err = _copy_uf2_to_rpi_rp2(
        uf2,
        bootsel,
        reboot_timeout_s=_UF2_REBOOT_WAIT_OPTIONAL_S,
        reboot_required=False,
    )
    assert ok
    assert err == ""
    _gone.assert_called_once()


@patch("gui.radio_manager._wait_for_bootsel_volume_gone", return_value=False)
@patch("gui.radio_manager.os.fsync")
def test_copy_uf2_required_reboot_fails_when_drive_stays(_fsync, _gone, tmp_path):
    bootsel = tmp_path / "RPI-RP2"
    bootsel.mkdir()
    (bootsel / "INDEX.HTM").write_text("<html></html>", encoding="utf-8")
    uf2 = tmp_path / "fw.uf2"
    uf2.write_bytes(b"UF2\n\x00" + b"x" * 100)
    ok, err = _copy_uf2_to_rpi_rp2(uf2, bootsel, reboot_required=True)
    assert not ok
    assert "RPI-RP2 drive is still present" in err


@patch("gui.radio_manager._wait_for_bootsel_volume_gone", return_value=False)
@patch("gui.radio_manager._run_picotool")
@patch("gui.radio_manager._find_picotool_executable", return_value=Path("picotool.exe"))
@patch("gui.radio_manager.time.sleep")
def test_flash_uf2_file_picotool_skips_sleep_when_reboot_optional(
    _sleep, _find_picotool, _run_picotool, _gone, tmp_path,
):
    uf2 = tmp_path / "fw.uf2"
    uf2.write_bytes(b"uf2")
    _run_picotool.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
    ok, err = _flash_uf2_file(
        uf2,
        tmp_path,
        reboot_timeout_s=_UF2_REBOOT_WAIT_OPTIONAL_S,
        reboot_required=False,
    )
    assert ok
    assert err == ""
    _sleep.assert_not_called()


def test_flash_uf2_worker_uses_supports_config_not_standalone_flag():
    rm_source = Path(__file__).resolve().parents[2] / "gui" / "radio_manager.py"
    text = rm_source.read_text(encoding="utf-8")
    block = text.split("def _flash_uf2_with_config_worker", 1)[1].split(
        "def _run_uf2_flash_with_progress", 1
    )[0]
    assert "standalone_uf2" not in block
    assert "supports_config" in block
    assert "needs_micropython = bool(injections) or config_only" in block


def test_flash_uf2_worker_uses_usable_wait_not_micropython_wait():
    rm_source = Path(__file__).resolve().parents[2] / "gui" / "radio_manager.py"
    text = rm_source.read_text(encoding="utf-8")
    block = text.split("def _flash_uf2_with_config_worker", 1)[1].split(
        "def _run_uf2_flash_with_progress", 1
    )[0]
    assert "_ensure_micropython_for_uf2_install" in block
    assert "_wait_for_mpremote_usable_after_uf2" in block
    assert "_wait_mpremote_serial_ready" not in block
    assert "_mpremote_copy_to_pico_verified" in block
    assert "_reboot_pico_after_config_inject" in block
    reboot_block = text.split("def _reboot_pico_after_config_inject", 1)[1].split(
        "def _mpremote_read_pico_radio_catalog", 1
    )[0]
    assert "machine.soft_reset()" in reboot_block
    assert "machine;machine.reset()" not in reboot_block


def test_flash_uf2_worker_tries_bootloader_when_no_bootsel():
    rm_source = Path(__file__).resolve().parents[2] / "gui" / "radio_manager.py"
    text = rm_source.read_text(encoding="utf-8")
    block = text.split("def _flash_uf2_with_config_worker", 1)[1].split(
        "def _run_uf2_flash_with_progress", 1
    )[0]
    assert "_try_reboot_pico_to_bootsel" in block
    assert "config_only" in block
    assert "_prompt_custom_uf2_install_mode" not in block
    assert "if wait_err is None" not in block


def test_run_uf2_flash_prompts_before_worker(tmp_path):
    uf2 = tmp_path / "custom.uf2"
    uf2.write_bytes(b"uf2")
    mgr = MagicMock()
    mgr._prepare_config_injections_for_uf2 = MagicMock(return_value=[("a.py", "config.py")])
    mgr._prompt_custom_uf2_install_mode = MagicMock(return_value="flash")

    class FakeDlg:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return 0

    with patch("gui.radio_manager.TaskProgressDialog", FakeDlg), patch(
        "gui.radio_manager._read_preferred_serial_port_from_ui", return_value=None
    ), patch(
        "gui.uf2_install_profile.firmware_entry_supports_config", return_value=True
    ):
        MainWindow._run_uf2_flash_with_progress(
            mgr,
            uf2,
            entry={"kind": "uf2", "config_path": "a.py", "supports_config": True},
            title="Install firmware",
        )

    mgr._prompt_custom_uf2_install_mode.assert_called_once()
    assert mgr._prompt_custom_uf2_install_mode.call_args.kwargs.get("title") == "Install firmware"


@patch("gui.radio_manager._run_mpremote")
@patch("gui.radio_manager._find_rp2040_serial_port", return_value="COM7")
def test_mpremote_copy_verified_rejects_mismatch(_port, run_mp, tmp_path):
    from gui.radio_manager import _mpremote_copy_to_pico_verified

    local = tmp_path / "config.py"
    local.write_text("EQUALIZER = 5\n", encoding="utf-8")
    calls = {"n": 0}

    def cp_side_effect(_cmd, args, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        Path(args[-1]).write_text("EQUALIZER = 0\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    run_mp.side_effect = cp_side_effect
    ok, err = _mpremote_copy_to_pico_verified(
        ["mpremote"], local, ":config.py", preferred_port="COM7",
    )
    assert not ok
    assert "verify" in err.lower()
