"""Tests for bundled firmware asset resolution."""

from __future__ import annotations


def test_bundled_full_uf2_prefers_firmware_release(tmp_path, monkeypatch):
    from gui.services import firmware_bundle as fb

    release = tmp_path / "firmware" / "release"
    release.mkdir(parents=True)
    uf2 = release / "vintage-radio-firmware-1.0.0-full.uf2"
    uf2.write_bytes(b"UF2")

    monkeypatch.setattr(fb, "project_root", lambda: tmp_path)
    assert fb.bundled_vintage_radio_full_uf2() == uf2


def test_bundled_full_uf2_missing_returns_none(tmp_path, monkeypatch):
    from gui.services import firmware_bundle as fb

    monkeypatch.setattr(fb, "project_root", lambda: tmp_path)
    assert fb.bundled_vintage_radio_full_uf2() is None
