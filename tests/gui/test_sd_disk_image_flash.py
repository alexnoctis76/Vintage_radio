"""Tests for SD disk image raw flash helpers."""

from gui.sd_disk_image_flash import format_disk_size


def test_format_disk_size() -> None:
    assert "GB" in format_disk_size(8 * 1024**3)
    assert "MB" in format_disk_size(64 * 1024**2)
