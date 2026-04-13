"""Tests for GitHub release updater asset selection and download URLs."""

from __future__ import annotations

import sys
from unittest import mock

import pytest

from gui import updater


def test_get_platform_asset_prefers_canonical_windows_zip():
    assets = [
        {"name": "Old-Windows-portable.zip", "browser_download_url": "https://x/old.zip"},
        {"name": "Vintage-Radio-Windows.zip", "browser_download_url": "https://x/good.zip"},
        {"name": "Vintage-Radio-macOS.zip", "browser_download_url": "https://x/mac.zip"},
    ]
    with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
        picked = updater.get_platform_asset(assets)
    assert picked is not None
    assert picked["name"] == "Vintage-Radio-Windows.zip"
    assert picked["browser_download_url"] == "https://x/good.zip"


def test_get_platform_asset_prefers_vintage_radio_prefix_over_random_windows():
    assets = [
        {"name": "something-windows-extra.zip", "browser_download_url": "https://x/bad.zip"},
        {"name": "Vintage-Radio-Windows-nightly.zip", "browser_download_url": "https://x/ok.zip"},
    ]
    with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
        picked = updater.get_platform_asset(assets)
    assert picked["name"] == "Vintage-Radio-Windows-nightly.zip"


def test_direct_download_url_for_release_windows():
    with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
        url = updater.direct_download_url_for_release("v0.2.1-beta")
    assert (
        url
        == "https://github.com/alexnoctis76/Vintage_radio/releases/download/v0.2.1-beta/Vintage-Radio-Windows.zip"
    )


def test_newest_release_from_list_uses_semver_not_list_order():
    items = [
        {
            "tag_name": "v0.0.1",
            "draft": False,
            "html_url": "https://github.com/a/b/releases/tag/v0.0.1",
            "body": "",
            "assets": [],
        },
        {
            "tag_name": "v0.2.1-beta",
            "draft": False,
            "html_url": "https://github.com/a/b/releases/tag/v0.2.1-beta",
            "body": "",
            "assets": [],
        },
    ]
    best = updater._newest_release_from_list(items)
    assert best is not None
    assert best.tag_name == "v0.2.1-beta"


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("v0.2.2", "v0.2.1-beta", True),
        ("v0.0.1", "v0.2.1-beta", False),
        ("v0.2.1-beta", "v0.2.1-beta", False),
    ],
)
def test_is_newer(latest: str, current: str, expected: bool):
    assert updater.is_newer(latest, current) is expected
