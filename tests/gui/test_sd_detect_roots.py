"""Tests for SD removable-volume detection (host-specific logic is mocked)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.mark.parametrize(
    "dp_rows,wrr_extra,expect_count",
    [
        # psutil finds FAT32 E:; supplement adds F: — two roots
        (
            [SimpleNamespace(mountpoint="E:\\", opts="", fstype="fat32")],
            [(Path("F:/"), "USB")],
            2,
        ),
        # Same letter from psutil + GetDriveType path — single entry
        (
            [SimpleNamespace(mountpoint="E:\\", opts="removable", fstype="fat32")],
            [(Path("E:/"), "SD")],
            1,
        ),
    ],
)
@patch("gui.sd_manager.platform.system", return_value="Windows")
@patch("gui.sd_manager._windows_get_removable_drive_roots")
@patch("gui.sd_manager.psutil.disk_partitions")
@patch("gui.sd_manager._get_volume_label", return_value="")
def test_detect_sd_roots_windows_merges_and_dedupes(
    _mock_label, mock_dp, mock_wrr, _plat, dp_rows, wrr_extra, expect_count
):
    from gui.sd_manager import SDManager

    mock_dp.return_value = dp_rows
    mock_wrr.return_value = wrr_extra
    real_exists = Path.exists

    def _fake_exists(self: Path) -> bool:
        s = str(self).upper().replace("/", "\\")
        if len(s) >= 2 and s[1] == ":" and s[0] in "EF":
            return True
        return real_exists(self)

    with patch.object(Path, "exists", _fake_exists):
        roots = SDManager.detect_sd_roots()
    assert len(roots) == expect_count
