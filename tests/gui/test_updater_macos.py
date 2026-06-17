"""Tests for macOS updater asset selection and .app discovery."""

from __future__ import annotations

import ssl
from io import BytesIO
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import unquote

import pytest

from gui import updater
from gui.updater import ReleaseInfo


def test_installer_download_urls_merges_assets_from_tag_api():
    rel = ReleaseInfo(tag_name="v9.9.9", html_url="x", body="", assets=[])
    api_row = {
        "id": 4242,
        "name": "Vintage.Radio.dmg",
        "browser_download_url": "https://github.com/releases/download/v9.9.9/Vintage.Radio.dmg",
    }
    with (
        mock.patch("gui.updater.platform.system", return_value="Darwin"),
        mock.patch(
            "gui.updater._fetch_release_assets_for_tag",
            return_value=[api_row],
        ),
    ):
        urls = updater.installer_download_urls_for_release(rel)
    assert api_row["browser_download_url"] in urls


def test_installer_download_urls_darwin_prefers_api_asset_url():
    rel = ReleaseInfo(
        tag_name="v0.2.2-beta",
        html_url="https://github.com/x/y",
        body="",
        assets=[
            {
                "name": "Vintage.Radio.dmg",
                "browser_download_url": "https://github.com/a/b/releases/download/v0.2.2-beta/Vintage.Radio.dmg",
            },
        ],
    )
    with mock.patch("gui.updater.platform.system", return_value="Darwin"):
        urls = updater.installer_download_urls_for_release(rel)
    assert urls
    assert urls[0].startswith("https://github.com/")
    assert "Vintage.Radio.dmg" in urls[0]


def test_installer_download_urls_darwin_adds_space_named_dmg_direct():
    rel = ReleaseInfo(tag_name="v1.0.0", html_url="x", body="", assets=[])
    with mock.patch("gui.updater.platform.system", return_value="Darwin"):
        urls = updater.installer_download_urls_for_release(rel)
    assert any(
        "releases/download" in u and "Vintage Radio.dmg" in unquote(u) for u in urls
    )


def test_https_ssl_context_is_configured():
    ctx = updater._https_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)


def test_download_update_try_urls_includes_tried_urls_on_all_404(tmp_path, monkeypatch):
    def boom(req, timeout=60):
        url = getattr(req, "full_url", None) or req.get_full_url()
        raise HTTPError(url, 404, "Not Found", hdrs={}, fp=BytesIO(b""))

    monkeypatch.setattr(updater, "_urlopen_with_certs", boom)
    with pytest.raises(RuntimeError, match="Tried 2 URL"):
        updater.download_update_try_urls(
            [
                "https://example.invalid/Vintage.Radio.dmg",
                "https://example.invalid/other.dmg",
            ],
            tmp_path,
            dest_filename="cached.dmg",
        )


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
