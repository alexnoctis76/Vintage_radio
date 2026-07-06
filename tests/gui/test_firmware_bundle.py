"""Tests for bundled firmware asset resolution."""

from __future__ import annotations

from pathlib import Path


def test_bundled_full_uf2_prefers_firmware_release(tmp_path, monkeypatch):
    from gui.services import firmware_bundle as fb

    release = tmp_path / "firmware" / "release"
    release.mkdir(parents=True)
    uf2 = release / "vintage-radio-firmware-1.0.0-full.uf2"
    uf2.write_bytes(b"UF2")

    monkeypatch.setattr(fb, "project_root", lambda: tmp_path)
    assert fb.bundled_vintage_radio_full_uf2() == uf2


def test_bundled_full_uf2_prefers_newest_semver(tmp_path, monkeypatch):
    from gui.services import firmware_bundle as fb

    release = tmp_path / "firmware" / "release"
    release.mkdir(parents=True)
    old = release / "vintage-radio-firmware-1.0.0-full.uf2"
    new = release / "vintage-radio-firmware-1.0.1-full.uf2"
    old.write_bytes(b"OLD")
    new.write_bytes(b"NEW")

    monkeypatch.setattr(fb, "project_root", lambda: tmp_path)
    assert fb.bundled_vintage_radio_full_uf2() == new
    assert fb.list_bundled_vintage_radio_full_uf2() == [new, old]


def test_vintage_radio_firmware_entry_id():
    from gui.services.firmware_bundle import vintage_radio_firmware_entry_id

    assert vintage_radio_firmware_entry_id("1.0.1") == "vintage_radio_1_0_1"


def test_full_uf2_version_string():
    from gui.services.firmware_bundle import full_uf2_version_string

    assert full_uf2_version_string(
        Path("vintage-radio-firmware-1.0.1-full.uf2")
    ) == "1.0.1"
    assert full_uf2_version_string(Path("other.uf2")) is None


def test_is_older_bundled_vintage_radio_full_uf2(tmp_path, monkeypatch):
    from gui.services import firmware_bundle as fb

    release = tmp_path / "firmware" / "release"
    release.mkdir(parents=True)
    old = release / "vintage-radio-firmware-1.0.0-full.uf2"
    new = release / "vintage-radio-firmware-1.0.1-full.uf2"
    old.write_bytes(b"OLD")
    new.write_bytes(b"NEW")

    monkeypatch.setattr(fb, "project_root", lambda: tmp_path)
    assert fb.is_older_bundled_vintage_radio_full_uf2(old) is True
    assert fb.is_older_bundled_vintage_radio_full_uf2(new) is False


def test_bundled_full_uf2_missing_returns_none(tmp_path, monkeypatch):
    from gui.services import firmware_bundle as fb

    monkeypatch.setattr(fb, "project_root", lambda: tmp_path)
    assert fb.bundled_vintage_radio_full_uf2() is None


def test_firmware_release_has_full_uf2_for_packaging():
    """Release UF2 images must exist on disk before PyInstaller (see vintage_radio.spec)."""
    root = Path(__file__).resolve().parents[2]
    matches = sorted((root / "firmware" / "release").glob("vintage-radio-firmware-*-full.uf2"))
    assert matches, "Add vintage-radio-firmware-*-full.uf2 under firmware/release before release build"


def test_vintage_radio_spec_bundles_firmware_release_uf2():
    spec = Path(__file__).resolve().parents[2] / "build" / "vintage_radio.spec"
    text = spec.read_text(encoding="utf-8")
    assert "firmware/release" in text
    assert "vintage-radio-firmware-*-full.uf2" in text
