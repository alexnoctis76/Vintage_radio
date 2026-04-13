from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from gui.widgets.task_progress_dialog import TaskProgressDialog  # noqa: E402


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
