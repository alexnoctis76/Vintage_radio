"""UpdateAvailableDialog must construct with VintageProgressBar API."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from gui import updater  # noqa: E402
from gui.update_dialog import UpdateAvailableDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_update_available_dialog_constructs(qapp):
    release = updater.ReleaseInfo(
        tag_name="v1.0.1",
        html_url="https://github.com/example/releases/tag/v1.0.1",
        body="Test release notes",
        assets=[
            {
                "name": "Vintage-Radio-Windows.zip",
                "browser_download_url": "https://example.com/Vintage-Radio-Windows.zip",
            }
        ],
        platform_version="v1.0.1",
    )
    dlg = UpdateAvailableDialog(release, "v1.0.0")
    try:
        assert dlg.progress.maximum() == 100
        assert dlg.progress.value() == 0
    finally:
        dlg.deleteLater()
