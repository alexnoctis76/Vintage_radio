"""Tests for UF2 install profile detection (bare MicroPython vs frozen app)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import urllib.request

from gui.uf2_install_profile import (
    _application_py_modules,
    _extract_embedded_py_modules,
    firmware_entry_supports_config,
    uf2_image_likely_micropython,
    uf2_image_supports_attached_config,
)


def _bare_mp_payload() -> bytes:
    return (
        b"UF2 block "
        b"_boot.py\x00_boot_fat.py\x00main.py\x00"
        b"asyncio/core.py\x00rp2.py\x00"
        b'Type "help()" for more information.\r\n'
    )


def _zbvr_like_payload() -> bytes:
    return (
        _bare_mp_payload()
        + b"config.py\x00dfplayer.py\x00controls.py\x00audioplayer.py\x00"
        + b"Project: ZBVR - Zion Brock Vintage Radio"
    )


def test_extract_embedded_py_modules():
    mods = _extract_embedded_py_modules(_zbvr_like_payload())
    assert "_boot.py" in mods
    assert "config.py" in mods
    assert "dfplayer.py" in mods
    assert "asyncio/core.py" in mods


def test_application_py_modules_filters_stdlib():
    mods = _extract_embedded_py_modules(_bare_mp_payload())
    assert _application_py_modules(mods) == set()
    zbvr_mods = _extract_embedded_py_modules(_zbvr_like_payload())
    app = _application_py_modules(zbvr_mods)
    assert "config.py" in app
    assert "dfplayer.py" in app
    assert "_boot.py" not in app


def test_uf2_supports_config_bare_runtime(tmp_path):
    uf2 = tmp_path / "RPI_PICO-custom.uf2"
    uf2.write_bytes(_bare_mp_payload())
    assert uf2_image_supports_attached_config(uf2)


def test_uf2_rejects_frozen_app_modules(tmp_path):
    uf2 = tmp_path / "zbvr-firmware-26_0_2.uf2"
    uf2.write_bytes(_zbvr_like_payload())
    assert not uf2_image_supports_attached_config(uf2)
    assert not uf2_image_likely_micropython(uf2)


def test_uf2_rejects_non_micropython_binary(tmp_path):
    uf2 = tmp_path / "baremetal.uf2"
    uf2.write_bytes(b"UF2\nC firmware no python modules here")
    assert not uf2_image_supports_attached_config(uf2)


def test_uf2_supports_config_missing_file(tmp_path):
    assert not uf2_image_supports_attached_config(tmp_path / "missing.uf2")


def test_firmware_entry_supports_config_folder_and_mpy():
    assert firmware_entry_supports_config({"kind": "folder"})
    assert firmware_entry_supports_config({"kind": "micropython"})


def test_firmware_entry_supports_config_local_uf2_rescans_file(tmp_path):
    uf2 = tmp_path / "app.uf2"
    uf2.write_bytes(_zbvr_like_payload())
    entry = {
        "kind": "uf2",
        "path": str(uf2),
        "supports_config": True,
        "config_path": "/tmp/config.py",
    }
    assert not firmware_entry_supports_config(entry)


def test_firmware_entry_supports_config_remote_uf2_builtin():
    assert not firmware_entry_supports_config(
        {"kind": "remote_uf2", "supports_config": False}
    )


def test_firmware_entry_supports_config_uf2_without_file_uses_saved_flag():
    assert not firmware_entry_supports_config(
        {"kind": "uf2", "path": "/missing/fw.uf2", "supports_config": False}
    )
    assert firmware_entry_supports_config(
        {"kind": "uf2", "path": "/missing/fw.uf2", "supports_config": True}
    )


@pytest.mark.network
def test_real_official_and_zbvr_samples(tmp_path):
    """Integration: official MP UF2 vs ZBVR release differ by embedded app modules."""
    zbvr_url = (
        "https://github.com/mloit/zbvr-firmware/releases/download/"
        "26.0.1/zbvr-firmware-26_0_1.uf2.zip"
    )
    zdata = urllib.request.urlopen(zbvr_url, timeout=60).read()
    z = zipfile.ZipFile(io.BytesIO(zdata))
    uf2_name = next(n for n in z.namelist() if n.lower().endswith(".uf2"))
    zbvr = tmp_path / "zbvr.uf2"
    zbvr.write_bytes(z.read(uf2_name))

    html = urllib.request.urlopen(
        "https://micropython.org/download/RPI_PICO/", timeout=60
    ).read().decode("utf-8", "replace")
    import re

    link = re.search(r'href="(/resources/firmware/RPI_PICO[^"]*\.uf2)"', html)
    assert link
    official = tmp_path / "official.uf2"
    official.write_bytes(
        urllib.request.urlopen("https://micropython.org" + link.group(1), timeout=60).read()
    )

    assert uf2_image_supports_attached_config(official)
    assert not uf2_image_supports_attached_config(zbvr)
    zbvr_app = _application_py_modules(_extract_embedded_py_modules(zbvr.read_bytes()))
    assert "config.py" in zbvr_app
    assert "dfplayer.py" in zbvr_app
