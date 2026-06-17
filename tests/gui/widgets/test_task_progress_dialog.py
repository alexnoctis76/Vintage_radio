from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from gui.widgets.dialogs.task_progress import TaskProgressDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_task_progress_dialog_runs_background_callable(qapp):
    parent = QtWidgets.QWidget()
    seen = {}

    def work(progress_callback):
        progress_callback(1, 1, "done")
        return {"ok": True}

    dlg = TaskProgressDialog(parent=parent, title="Test Progress", func=work)
    dlg.on_success = lambda result: seen.setdefault("result", result)
    dlg.show()

    deadline = time.time() + 3.0
    while time.time() < deadline and "result" not in seen:
        qapp.processEvents()
        time.sleep(0.01)

    try:
        assert seen.get("result") == {"ok": True}
    finally:
        dlg.close()
        dlg.deleteLater()
        parent.deleteLater()


def test_format_bytes_short(qapp):
    assert TaskProgressDialog._format_bytes_short(0) == "0 B"
    assert TaskProgressDialog._format_bytes_short(2048) == "2 KB"
    assert "GB" in TaskProgressDialog._format_bytes_short(31 * (1 << 30))


def test_format_eta_seconds(qapp):
    assert TaskProgressDialog._format_eta_seconds(45) == "~45 s remaining"
    assert TaskProgressDialog._format_eta_seconds(90) == "~1 min 30 s remaining"
    assert TaskProgressDialog._format_eta_seconds(3661) == "~1 h 1 min 1 s remaining"
    assert TaskProgressDialog._format_eta_seconds(90061) == "~1 d 1 h 1 min 1 s remaining"


def test_progress_bar_file_count_sync_copy(qapp):
    """Sync copy phase reports file indices, not bytes."""
    parent = QtWidgets.QWidget()
    dlg = TaskProgressDialog(parent=parent, title="t", func=lambda **kw: None)
    try:
        dlg._on_progress(1, 2, "Copying to SD card (1/2, track.mp3, 3.5 files/s, ETA ~1s)")
        assert dlg._progress_bar.maximum() == 2
        assert dlg._progress_bar.value() == 1
        assert dlg._progress_bar.text() == "1 / 2 files"
    finally:
        dlg.close()
        dlg.deleteLater()
        parent.deleteLater()


def test_progress_phase_key_stable_for_sync_prep(qapp):
    parent = QtWidgets.QWidget()
    dlg = TaskProgressDialog(parent=parent, title="t", func=lambda **kw: None)
    try:
        k1 = TaskProgressDialog._progress_phase_key("Preparing 01: Song A (1/100)")
        k2 = TaskProgressDialog._progress_phase_key("Preparing 02: Song B (2/100)")
        assert k1 == k2 == "sync_prep"
    finally:
        dlg.close()
        dlg.deleteLater()
        parent.deleteLater()


def test_progress_bar_scales_past_qt_int32(qapp):
    """Totals > ~2 GiB overflow QProgressBar's int range; dialog scales to 0..10000."""
    parent = QtWidgets.QWidget()
    dlg = TaskProgressDialog(parent=parent, title="t", func=lambda **kw: None)
    try:
        total = 35 * (1 << 30)
        cur = total // 2
        dlg._on_progress(cur, total, "writing")
        assert dlg._progress_bar.maximum() == 10_000
        assert dlg._progress_bar.value() == 5_000
        assert dlg._progress_bar.text() == "50%"
        assert dlg._eta_label.text() == ""
    finally:
        dlg.close()
        dlg.deleteLater()
        parent.deleteLater()
