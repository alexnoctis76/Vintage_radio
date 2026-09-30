"""Regression tests for sync failure prompt button wiring."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from gui.sync_failure_prompt import (  # noqa: E402
    _SKIP_ALL_LABEL,
    map_sync_failure_choice,
    run_sync_failure_choice,
    sync_failure_dialog_buttons,
)
from gui.widgets.dialogs.vintage_message import (  # noqa: E402
    VintageMessageBox,
    _button_label,
)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_pyqt6_has_no_ignore_all_standard_button():
    """PyQt6 StandardButton has Ignore but not IgnoreAll (Qt5 name)."""
    std = QtWidgets.QMessageBox.StandardButton
    assert hasattr(std, "Ignore")
    assert not hasattr(std, "IgnoreAll")


def test_sync_failure_button_specs_are_constructible():
    specs = sync_failure_dialog_buttons()
    assert len(specs) == 3
    labels = [_button_label(spec) for spec in specs]
    assert labels == ["Abort", "Ignore", _SKIP_ALL_LABEL]


def test_sync_failure_dialog_adds_three_footer_buttons(qapp):
    dlg = VintageMessageBox(None)
    for spec in sync_failure_dialog_buttons():
        dlg.addButton(spec)
    try:
        assert len(dlg._buttons) == 3
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (VintageMessageBox.StandardButton.Abort, "stop"),
        (VintageMessageBox.StandardButton.Ignore, "skip"),
        (_SKIP_ALL_LABEL, "skip_all"),
        ("unexpected", "skip"),
    ],
)
def test_map_sync_failure_choice(spec, expected):
    assert map_sync_failure_choice(spec) == expected


def test_run_sync_failure_choice_auto_clicks_skip(qapp, monkeypatch):
    monkeypatch.setattr(
        VintageMessageBox,
        "exec",
        lambda self: self._on_button(self._buttons[1][0]),
    )
    assert run_sync_failure_choice(None, "body") == "skip"
