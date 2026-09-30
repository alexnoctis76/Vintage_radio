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
    assert vintage_radio_firmware_entry_id("1.1.0") == "vintage_radio_1_1_0"


def test_current_vs_legacy_generation():
    from gui.services.firmware_bundle import (
        is_current_firmware_generation,
        is_legacy_firmware_generation,
    )

    assert is_current_firmware_generation("1.1.0")
    assert is_current_firmware_generation("1.2.0")
    assert not is_current_firmware_generation("1.0.1")
    assert is_legacy_firmware_generation("1.0.0")


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


def test_list_micropython_uf2_hrefs_filters_board():
    from gui.services.firmware_bundle import list_micropython_uf2_hrefs

    html = """
    <a href="/resources/firmware/RPI_PICO-20240602-v1.23.0.uf2">ok</a>
    <a href="/resources/firmware/OTHER-20240602-v1.0.0.uf2">skip</a>
    """
    links = list_micropython_uf2_hrefs(html)
    assert links == ["/resources/firmware/RPI_PICO-20240602-v1.23.0.uf2"]


def test_vintage_radio_spec_bundles_firmware_release_uf2():
    spec = Path(__file__).resolve().parents[2] / "build" / "vintage_radio.spec"
    text = spec.read_text(encoding="utf-8")
    assert "firmware/release" in text
    assert "vintage-radio-firmware-*-full.uf2" in text


def test_firmware_downloads_use_certifi_ssl_context(monkeypatch):
    """macOS/frozen Python has no system CA store; downloads must pass a certifi context."""
    import ssl
    from unittest import mock

    from gui.services import firmware_bundle

    seen = {}

    def fake_urlopen(req, timeout=None, context=None):
        seen["context"] = context
        raise RuntimeError("stop")

    monkeypatch.setattr(firmware_bundle.urllib.request, "urlopen", fake_urlopen)
    try:
        firmware_bundle._urlopen(mock.Mock(), 5)
    except RuntimeError:
        pass
    assert isinstance(seen["context"], ssl.SSLContext)


def test_mpremote_helper_spec_excludes_mpy_cross():
    """Bundled mpy_cross without its binary raises SystemExit and kills the helper."""
    spec = Path(__file__).resolve().parents[2] / "build" / "mpremote_helper.spec"
    text = spec.read_text(encoding="utf-8")
    assert "'mpy_cross'" in text.split("excludes=", 1)[1].split("]", 1)[0]
