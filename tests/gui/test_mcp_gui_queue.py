"""Verify MCP socket-thread callables are marshaled to the Qt GUI thread."""

from __future__ import annotations

import os
import threading
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets  # noqa: E402

from gui.radio_manager import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_mcp_queue_on_gui_runs_on_main_thread(qapp):
    mw = MainWindow()
    try:
        ran: list[int] = []

        def work() -> None:
            assert QtCore.QThread.currentThread() is mw.thread()
            ran.append(1)

        t = threading.Thread(target=lambda: mw._mcp_queue_on_gui(work))
        t.start()
        t.join(timeout=5.0)
        assert not t.is_alive()
        deadline = time.time() + 5.0
        while time.time() < deadline and not ran:
            qapp.processEvents()
            time.sleep(0.01)
        assert ran == [1]
    finally:
        mw.close()
        mw.deleteLater()
        for _ in range(20):
            qapp.processEvents()
            time.sleep(0.01)


def test_mcp_run_on_gui_sync_from_worker_thread(qapp):
    mw = MainWindow()
    try:

        def compute() -> dict:
            assert QtCore.QThread.currentThread() is mw.thread()
            return {"ok": True, "thread": "gui"}

        result_holder: dict = {}

        def worker() -> None:
            result_holder["r"] = mw._mcp_run_on_gui_sync(compute, wait_s=10.0)

        t = threading.Thread(target=worker)
        t.start()
        deadline = time.time() + 5.0
        while t.is_alive() and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert result_holder.get("r") == {"ok": True, "thread": "gui"}
    finally:
        mw.close()
        mw.deleteLater()
        for _ in range(20):
            qapp.processEvents()
            time.sleep(0.01)
