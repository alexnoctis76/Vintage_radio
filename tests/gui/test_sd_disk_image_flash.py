"""Tests for SD disk image raw flash helpers."""

from pathlib import Path

from gui.sd_disk_image_flash import (
    darwin_normalize_bsd_whole_disk,
    darwin_rdisk_path,
    dd_stderr_records_out_bytes,
    disk_write_eta_seconds,
    disk_write_estimated_data_bytes,
    format_disk_size,
    parse_disk_write_progress_message,
)
from gui.sd_disk_write_helper import parse_sd_disk_write_cli_args


def test_format_disk_size() -> None:
    assert "GB" in format_disk_size(8 * 1024**3)
    assert "MB" in format_disk_size(64 * 1024**2)


def test_parse_properly_quoted_single_tokens() -> None:
    """Normal case: PowerShell quotes paths so they arrive as single argv tokens."""
    img = r"C:\Users\alexn\AppData\Local\Vintage Radio\sd_image_cache\vintage_radio_sd_last.img"
    log = r"C:\Users\alexn\AppData\Local\Temp\vintage_radio_sd_uac_abc.log"
    argv = [
        r"C:\dist\Vintage Radio\Vintage Radio.exe",
        "--vr-write-sd-disk",
        img,
        "3",
        log,
    ]
    out = parse_sd_disk_write_cli_args(argv, flag="--vr-write-sd-disk")
    assert out is not None
    p, disk, lp, prog = out
    assert p == Path(img)
    assert disk == 3
    assert lp == Path(log)
    assert prog is None


def test_parse_with_progress_json() -> None:
    img = r"C:\a\Vintage Radio\cache\img.img"
    log = r"C:\Temp\vintage_radio_sd_uac_abc.log"
    prog = r"C:\Temp\vintage_radio_sd_uac_abc.progress.json"
    argv = ["exe", "--vr-write-sd-disk", img, "2", log, prog]
    out = parse_sd_disk_write_cli_args(argv, flag="--vr-write-sd-disk")
    assert out is not None
    p, disk, lp, pr = out
    assert p == Path(img)
    assert disk == 2
    assert lp == Path(log)
    assert pr == Path(prog)


def test_parse_split_path_fallback() -> None:
    """Fallback: path with spaces split into multiple argv tokens (old PS quoting)."""
    img = r"C:\Apps\dist\Vintage Radio\sd_image_cache\vintage_radio_sd_last.img"
    argv = [
        r"C:\Apps\dist\Vintage Radio\Vintage Radio.exe",
        "--vr-write-sd-disk",
        r"C:\Apps\dist\Vintage",
        r"Radio\sd_image_cache\vintage_radio_sd_last.img",
        "3",
        r"C:\Temp\vintage_radio_sd_uac_abc.log",
    ]
    out = parse_sd_disk_write_cli_args(argv, flag="--vr-write-sd-disk")
    assert out is not None
    p, disk, log, prog = out
    assert p == Path(img)
    assert disk == 3
    assert log == Path(r"C:\Temp\vintage_radio_sd_uac_abc.log")
    assert prog is None


def test_parse_no_log() -> None:
    argv = ["exe", "--vr-write-sd-disk", r"C:\no spaces\a.img", "2"]
    out = parse_sd_disk_write_cli_args(argv, flag="--vr-write-sd-disk")
    assert out is not None
    p, disk, log, prog = out
    assert p == Path(r"C:\no spaces\a.img")
    assert disk == 2
    assert log is None
    assert prog is None


def test_parse_helper_module_argv() -> None:
    argv = ["python", r"C:\a\Vintage", r"Radio\x.img", "1"]
    out = parse_sd_disk_write_cli_args(argv, flag=None)
    assert out is not None
    p, disk, log, prog = out
    assert p == Path(r"C:\a\Vintage Radio\x.img")
    assert disk == 1
    assert log is None
    assert prog is None


def test_darwin_normalize_bsd_whole_disk() -> None:
    assert darwin_normalize_bsd_whole_disk("disk4") == "disk4"
    assert darwin_normalize_bsd_whole_disk("  /dev/disk12 ") == "disk12"
    assert darwin_normalize_bsd_whole_disk("/dev/rdisk3") == "disk3"
    assert darwin_normalize_bsd_whole_disk("disk4s1") is None
    assert darwin_normalize_bsd_whole_disk("") is None


def test_darwin_rdisk_path() -> None:
    assert darwin_rdisk_path("disk4") == "/dev/rdisk4"


def test_dd_stderr_records_out_bytes_parses_last_line() -> None:
    mib = 1024 * 1024
    stderr = (
        "21751+0 records in\n"
        "21750+0 records out\n"
        "22806528000 bytes transferred in 3647.3 secs\n"
    )
    assert dd_stderr_records_out_bytes(stderr) == 21750 * mib


def test_dd_stderr_records_out_bytes_last_match_wins() -> None:
    mib = 1024 * 1024
    assert dd_stderr_records_out_bytes("1+0 records out\n2+0 records out\n") == 2 * mib


def test_dd_stderr_records_out_bytes_none_when_missing() -> None:
    assert dd_stderr_records_out_bytes("no stats here\n") is None


def test_disk_write_estimated_data_bytes_uses_manifest() -> None:
    gib = 1024**3
    image_size = 32 * gib
    known = int(1.5 * gib)
    est = disk_write_estimated_data_bytes(
        image_size=image_size,
        written_from_file=68 * 1024 * 1024,
        bytes_data_written=68 * 1024 * 1024,
        bytes_zero_skipped=0,
        known_data_bytes=known,
    )
    assert est == known


def test_disk_write_eta_sparse_library_not_full_volume() -> None:
    gib = 1024**3
    image_size = 32 * gib
    known = int(1.5 * gib)
    scanned = 68 * 1024 * 1024
    time_data = 60.0
    eta = disk_write_eta_seconds(
        image_size=image_size,
        written_from_file=scanned,
        bytes_data_written=scanned,
        bytes_zero_skipped=0,
        time_data=time_data,
        time_zero=0.0,
        est_data_bytes=known,
    )
    assert eta is not None
    # Full-volume naive ETA at this scan rate would be ~8+ hours; sparse should be far less.
    assert eta < 3600 * 2


def test_parse_disk_write_progress_message_splits_eta() -> None:
    msg = (
        "Writing to SD card (450 MB of 1.5 GB)…"
        "\x1cInstall image: 868 MB of 29.0 GB"
        "\x1e900.5"
    )
    partition, image, eta = parse_disk_write_progress_message(msg)
    assert "Writing to SD card" in partition
    assert "Install image" in (image or "")
    assert eta == 900.5
