"""Tests for SD disk image raw flash helpers."""

from pathlib import Path

from gui.sd_disk_image_flash import format_disk_size
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
