"""Regression tests for sync failure prompt button wiring."""

from __future__ import annotations

import os
import threading

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from gui.sync_failure_prompt import (  # noqa: E402
    _APPLY_ALL_CHECKBOX,
    _SKIP_ALL_LABEL,
    map_sync_failure_choice,
    run_hash_mismatch_sync_choice,
    run_sync_failure_choice,
    sync_failure_dialog_buttons,
    SyncFailurePrompter,
)
from gui.sd_manager import _SyncFailurePolicy, _decide_sync_failure  # noqa: E402
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


def test_skip_all_policy_only_auto_skips_hash_mismatch():
    policy = _SyncFailurePolicy()
    policy.skip_all = True
    assert (
        _decide_sync_failure(None, policy, {"kind": "hash_mismatch"})
        == "skip"
    )
    calls: list = []

    def _cb(info: dict) -> str:
        calls.append(info)
        return "stop"

    assert (
        _decide_sync_failure(_cb, policy, {"kind": "conversion_failure"})
        == "stop"
    )
    assert calls == [{"kind": "conversion_failure"}]


def test_force_stop_prompt_sets_stop_and_unblocks_waiter(qapp):
    prompter = SyncFailurePrompter(None)
    prompter._waiter = threading.Event()
    prompter._force_stop_prompt()
    assert prompter._result == "stop"
    assert prompter._waiter.is_set()


def test_prompter_ask_returns_stop_when_cancelled(qapp):
    prompter = SyncFailurePrompter(None)
    prompter.set_should_cancel(lambda: True)

    results: list = []

    def worker() -> None:
        results.append(
            prompter.ask(
                {
                    "kind": "hash_mismatch",
                    "name": "Track",
                    "path": "/x.mp3",
                    "error": "hash",
                }
            )
        )

    thread = threading.Thread(target=worker)
    thread.start()
    while thread.is_alive():
        qapp.processEvents()
        thread.join(timeout=0.05)
    assert results == ["stop"]


def test_run_sync_failure_choice_auto_clicks_skip(qapp, monkeypatch):
    monkeypatch.setattr(
        VintageMessageBox,
        "exec",
        lambda self: self._on_button(self._buttons[1][0]),
    )
    assert run_sync_failure_choice(None, "body") == "skip"


def test_hash_mismatch_dialog_update_without_apply_all(qapp, monkeypatch):
    from gui.sync_failure_prompt import _HashMismatchSyncDialog

    def _fake_exec(self):
        self._on_update()
        return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(_HashMismatchSyncDialog, "exec", _fake_exec)
    assert run_hash_mismatch_sync_choice(None, "body") == "accept_file"


def test_hash_mismatch_dialog_skip_with_apply_all(qapp, monkeypatch):
    from gui.sync_failure_prompt import _HashMismatchSyncDialog

    def _fake_exec(self):
        self._apply_all_cb.setChecked(True)
        self._on_skip()
        return int(QtWidgets.QDialog.DialogCode.Accepted)

    monkeypatch.setattr(_HashMismatchSyncDialog, "exec", _fake_exec)
    assert run_hash_mismatch_sync_choice(None, "body") == "skip_all"


def test_apply_all_checkbox_label():
    assert "remaining mismatches" in _APPLY_ALL_CHECKBOX.lower()
