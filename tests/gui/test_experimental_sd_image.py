"""Tests for experimental SD disk image export (pyfatfs)."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import pytest

from gui.experimental_sd_image import (
    _fat_volume_label,
    copy_sd_folder_into_fat_image,
    create_fat32_image_file,
    suggest_image_size_bytes,
)


def test_fat_volume_label() -> None:
    assert _fat_volume_label("VINTAGERADIO") == "VINTAGERADI"
    assert _fat_volume_label("AB") == "AB"
    assert _fat_volume_label("") == "NO NAME"


def test_suggest_image_size_bytes_minimum() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        assert suggest_image_size_bytes(root) >= 64 * 1024 * 1024


@pytest.mark.skipif(
    importlib.util.find_spec("pyfatfs") is None,
    reason="pyfatfs not installed",
)
def test_create_and_copy_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "sd"
        root.mkdir()
        (root / "sub").mkdir()
        (root / "sub" / "hello.txt").write_bytes(b"hi")

        img = Path(td) / "out.img"
        ok, err = create_fat32_image_file(img, 64 * 1024 * 1024)
        assert ok, err
        ok2, err2 = copy_sd_folder_into_fat_image(root, img)
        assert ok2, err2

        from pyfatfs.PyFatFS import PyFatFS

        fs = PyFatFS(str(img), read_only=True)
        try:
            assert fs.exists("/sub/hello.txt")
            with fs.openbin("/sub/hello.txt", "r") as f:
                assert f.read() == b"hi"
        finally:
            fs.close()
