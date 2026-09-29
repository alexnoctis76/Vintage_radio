"""Tests for GitHub release updater asset selection and download URLs."""

from __future__ import annotations

import json
import sys
from unittest import mock

import pytest

from gui import updater
from gui.release_config import reload_release_config


@pytest.fixture(autouse=True)
def _clear_release_config_cache():
    reload_release_config()
    yield
    reload_release_config()


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="get_platform_asset Windows branch")
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


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="get_platform_asset Windows branch")
def test_get_platform_asset_prefers_vintage_radio_prefix_over_random_windows():
    assets = [
        {"name": "something-windows-extra.zip", "browser_download_url": "https://x/bad.zip"},
        {"name": "Vintage-Radio-Windows-nightly.zip", "browser_download_url": "https://x/ok.zip"},
    ]
    with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
        picked = updater.get_platform_asset(assets)
    assert picked["name"] == "Vintage-Radio-Windows-nightly.zip"


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer basename")
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


def test_effective_platform_version_falls_back_to_tag_without_manifest():
    info = updater.ReleaseInfo(
        tag_name="v0.2.4-beta",
        html_url="https://example/u",
        body="",
        assets=[
            {
                "name": "Vintage-Radio-Windows.zip",
                "browser_download_url": "https://example/z.zip",
            }
        ],
    )
    assert updater._effective_platform_version(info) == "v0.2.4-beta"


def test_effective_platform_version_reads_manifest_on_windows():
    info = updater.ReleaseInfo(
        tag_name="v0.2.4-beta",
        html_url="https://example/u",
        body="",
        assets=[
            {
                "name": "release-versions.json",
                "browser_download_url": "https://example/manifest.json",
            },
            {
                "name": "Vintage-Radio-Windows.zip",
                "browser_download_url": "https://example/z.zip",
            },
        ],
    )
    with mock.patch.object(
        updater,
        "_fetch_release_versions_manifest_dict",
        return_value={"windows": "v0.2.3-beta"},
    ):
        with mock.patch.object(updater, "_platform_matcher", return_value="windows"):
            assert updater._effective_platform_version(info) == "v0.2.3-beta"


def test_best_release_newer_than_for_platform_respects_manifest_not_tag():
    items = [
        {
            "tag_name": "v0.2.4-beta",
            "draft": False,
            "html_url": "https://example/u",
            "body": "",
            "assets": [
                {
                    "name": "release-versions.json",
                    "browser_download_url": "https://example/manifest.json",
                },
                {
                    "name": "Vintage-Radio-Windows.zip",
                    "browser_download_url": "https://example/z.zip",
                },
            ],
        }
    ]
    with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
        with mock.patch.object(
            updater,
            "_fetch_release_versions_manifest_dict",
            return_value={"windows": "v0.2.3-beta"},
        ):
            rel = updater._best_release_newer_than_for_platform(items, "v0.2.2-beta")
    assert rel is not None
    assert rel.tag_name == "v0.2.4-beta"
    assert rel.platform_version == "v0.2.3-beta"

    with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
        with mock.patch.object(
            updater,
            "_fetch_release_versions_manifest_dict",
            return_value={"windows": "v0.2.3-beta"},
        ):
            rel2 = updater._best_release_newer_than_for_platform(items, "v0.2.3-beta")
    assert rel2 is None


def test_run_update_check_up_to_date_when_current_ahead_of_github():
    items = [
        {
            "tag_name": "v0.2.5-beta",
            "draft": False,
            "html_url": "https://github.com/a/b/releases/tag/v0.2.5-beta",
            "body": "",
            "assets": [
                {
                    "name": "Vintage-Radio-Windows.zip",
                    "browser_download_url": "https://example/z.zip",
                }
            ],
        }
    ]
    with mock.patch.object(updater, "_fetch_release_list", return_value=items):
        with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
            result = updater.run_update_check(current_version="v1.0.0")
    assert result.status == "up_to_date"
    assert result.latest_published == "v0.2.5-beta"
    assert result.release is not None


def test_preferred_macos_asset_basename_arm64():
    with mock.patch("gui.updater.platform.machine", return_value="arm64"):
        assert updater.preferred_macos_asset_basename() == "Vintage-Radio-macOS-arm64.zip"


def test_preferred_macos_asset_basename_x86_64():
    with mock.patch("gui.updater.platform.machine", return_value="x86_64"):
        assert updater.preferred_macos_asset_basename() == "Vintage-Radio-macOS-x86_64.zip"


def test_get_platform_asset_mac_prefers_arch_specific_zip():
    assets = [
        {"name": "Vintage-Radio-macOS-x86_64.zip", "browser_download_url": "https://x/intel.zip"},
        {"name": "Vintage-Radio-macOS-arm64.zip", "browser_download_url": "https://x/arm.zip"},
    ]
    with mock.patch("gui.updater.platform.system", return_value="Darwin"):
        with mock.patch("gui.updater.platform.machine", return_value="arm64"):
            picked = updater.get_platform_asset(assets)
    assert picked is not None
    assert picked["name"] == "Vintage-Radio-macOS-arm64.zip"


def test_get_platform_asset_linux():
    assets = [
        {"name": "Vintage-Radio-Linux.zip", "browser_download_url": "https://x/linux.zip"},
    ]
    with mock.patch("gui.updater.platform.system", return_value="Linux"):
        picked = updater.get_platform_asset(assets)
    assert picked is not None
    assert picked["name"] == "Vintage-Radio-Linux.zip"


def test_run_update_check_skipped_when_update_disabled():
    items = [
        {
            "tag_name": "v9.9.9",
            "draft": False,
            "html_url": "https://github.com/a/b/releases/tag/v9.9.9",
            "body": "",
            "assets": [
                {
                    "name": "Vintage-Radio-Windows.zip",
                    "browser_download_url": "https://example/z.zip",
                }
            ],
        }
    ]
    with mock.patch.object(updater, "_fetch_release_list", return_value=items):
        with mock.patch("gui.release_config.update_check_enabled", return_value=False):
            result = updater.run_update_check(current_version="v0.1.0")
    assert result.status == "up_to_date"
    assert result.release is None


def test_stable_channel_ignores_prerelease(tmp_path, monkeypatch):
    cfg = tmp_path / "release_config.json"
    cfg.write_text(
        json.dumps({"update": {"enabled": True, "channel": "stable", "prerelease_only": False}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("gui.release_config.project_root", lambda: tmp_path)
    from gui.release_config import reload_release_config

    reload_release_config()

    items = [
        {
            "tag_name": "v9.9.9-upgrade-test",
            "draft": False,
            "prerelease": True,
            "html_url": "https://github.com/a/b/releases/tag/v9.9.9-upgrade-test",
            "body": "",
            "assets": [
                {
                    "name": "Vintage-Radio-Windows.zip",
                    "browser_download_url": "https://example/pre.zip",
                }
            ],
        },
        {
            "tag_name": "v1.0.2",
            "draft": False,
            "prerelease": False,
            "html_url": "https://github.com/a/b/releases/tag/v1.0.2",
            "body": "",
            "assets": [
                {
                    "name": "Vintage-Radio-Windows.zip",
                    "browser_download_url": "https://example/stable.zip",
                }
            ],
        },
    ]
    with mock.patch.object(updater, "_fetch_release_list", return_value=updater._filter_release_items(items)):
        with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
            result = updater.run_update_check(current_version="v1.0.0")
    assert result.status == "update_available"
    assert result.release is not None
    assert result.release.tag_name == "v1.0.2"


def test_test_channel_only_sees_matching_prerelease(tmp_path, monkeypatch):
    cfg = tmp_path / "release_config.json"
    cfg.write_text(
        json.dumps(
            {
                "update": {
                    "enabled": True,
                    "channel": "test",
                    "prerelease_only": True,
                    "tag_suffix": "-upgrade-test",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("gui.release_config.project_root", lambda: tmp_path)
    from gui.release_config import reload_release_config

    reload_release_config()

    items = [
        {
            "tag_name": "v1.2.0-beta",
            "draft": False,
            "prerelease": True,
            "html_url": "https://github.com/a/b/releases/tag/v1.2.0-beta",
            "body": "",
            "assets": [
                {
                    "name": "Vintage-Radio-Windows.zip",
                    "browser_download_url": "https://example/beta.zip",
                }
            ],
        },
        {
            "tag_name": "v1.1.0-upgrade-test",
            "draft": False,
            "prerelease": True,
            "html_url": "https://github.com/a/b/releases/tag/v1.1.0-upgrade-test",
            "body": "",
            "assets": [
                {
                    "name": "Vintage-Radio-Windows.zip",
                    "browser_download_url": "https://example/test.zip",
                }
            ],
        },
    ]
    with mock.patch.object(updater, "_fetch_release_list", return_value=updater._filter_release_items(items)):
        with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
            result = updater.run_update_check(current_version="v1.0.0")
    assert result.status == "update_available"
    assert result.release is not None
    assert result.release.tag_name == "v1.1.0-upgrade-test"


def test_macos_cpu_arch_arm64_when_rosetta_on_apple_silicon(monkeypatch):
    monkeypatch.setattr("gui.updater.platform.machine", lambda: "x86_64")
    monkeypatch.setattr("gui.updater._macos_hardware_has_arm64", lambda: True)
    assert updater._macos_cpu_arch() == "arm64"


def test_run_update_check_update_available():
    items = [
        {
            "tag_name": "v1.1.0",
            "draft": False,
            "prerelease": False,
            "html_url": "https://github.com/a/b/releases/tag/v1.1.0",
            "body": "",
            "assets": [
                {
                    "name": "Vintage-Radio-Windows.zip",
                    "browser_download_url": "https://example/z.zip",
                }
            ],
        }
    ]
    with mock.patch.object(updater, "_fetch_release_list", return_value=items):
        with mock.patch.object(sys.modules["platform"], "system", return_value="Windows"):
            result = updater.run_update_check(current_version="v1.0.0")
    assert result.status == "update_available"
    assert result.release is not None
    assert result.release.tag_name == "v1.1.0"
