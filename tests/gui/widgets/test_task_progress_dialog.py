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
    assert TaskProgressDialog._format_bytes_short(2048) == "2 KiB"
    assert "GiB" in TaskProgressDialog._format_bytes_short(31 * (1 << 30))


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
        assert "GiB" in dlg._detail_label.text()
    finally:
        dlg.close()
        dlg.deleteLater()
        parent.deleteLater()
