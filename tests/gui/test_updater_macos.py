"""Tests for macOS updater asset selection and .app discovery."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from gui import updater


def test_get_platform_asset_darwin_prefers_preferred_dmg_name():
    assets = [
        {"name": "Vintage-Radio-macOS.zip"},
        {"name": "Vintage.Radio.dmg", "browser_download_url": "https://x/d.dmg"},
    ]
    with mock.patch("gui.updater.platform.system", return_value="Darwin"):
        picked = updater.get_platform_asset(assets)
    assert picked is not None
    assert picked["name"] == "Vintage.Radio.dmg"


def test_vintage_dot_radio_dmg_matches():
    assert updater._get_macos_release_asset(
        [{"name": "Vintage.Radio.dmg", "browser_download_url": "https://x/a.dmg"}]
    )["name"] == "Vintage.Radio.dmg"


def test_get_macos_release_prefers_dmg_over_zip():
    assets = [
        {"name": "Vintage-Radio-macOS.zip", "browser_download_url": "https://x/z.zip"},
        {"name": "Vintage.Radio.dmg", "browser_download_url": "https://x/v.dmg"},
    ]
    picked = updater._get_macos_release_asset(assets)
    assert picked is not None
    assert picked["name"] == "Vintage.Radio.dmg"


def test_get_macos_release_ignores_unrelated_dmg():
    assets = [
        {"name": "Other-Project.dmg"},
        {"name": "Vintage-Radio-macOS.zip", "browser_download_url": "https://x/z.zip"},
    ]
    picked = updater._get_macos_release_asset(assets)
    assert picked is not None
    assert picked["name"] == "Vintage-Radio-macOS.zip"


def test_pick_macos_app_skips_macosx_junk(tmp_path: Path):
    junk = tmp_path / "__MACOSX" / "_Vintage Radio.app"
    junk.mkdir(parents=True)
    (junk / "not_real").write_text("x", encoding="utf-8")

    real = tmp_path / "Vintage Radio.app"
    (real / "Contents" / "MacOS").mkdir(parents=True)
    (real / "Contents" / "MacOS" / "Vintage Radio").write_text("", encoding="utf-8")

    found = updater._pick_macos_app_bundle_from_root(tmp_path)
    assert found == real
