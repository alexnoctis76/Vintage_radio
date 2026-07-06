"""Tests for VintageMessageBox's "More Info" detail toggle."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from gui.widgets.dialogs.vintage_message import VintageMessageBox  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_no_detail_button_when_no_detailed_text(qapp):
    dlg = VintageMessageBox(None)
    dlg.setText("Short summary")
    try:
        assert dlg._detail_btn is None
    finally:
        dlg.deleteLater()


def test_detail_button_added_and_toggles_visibility(qapp):
    dlg = VintageMessageBox(None)
    dlg.setText("Short summary")
    dlg.setDetailedText("Traceback (most recent call last):\n  raw stuff")
    try:
        assert dlg._detail_btn is not None
        assert dlg._detail_btn.text() == "More Info"
        assert dlg._body_stack.currentWidget() is dlg._summary_page

        dlg._toggle_detail()
        assert dlg._detail_visible is True
        assert dlg._detail_btn.text() == "Hide Details"
        assert dlg._scroll_edit is not None
        assert dlg._scroll_edit.toPlainText() == "Traceback (most recent call last):\n  raw stuff"
        assert dlg._body_stack.currentWidget() is dlg._scroll_area

        dlg._toggle_detail()
        assert dlg._detail_visible is False
        assert dlg._detail_btn.text() == "More Info"
        assert dlg._body_stack.currentWidget() is dlg._summary_page
    finally:
        dlg.deleteLater()


def test_toggling_detail_does_not_resize_dialog(qapp):
    """Regression: resizing this frameless/translucent dialog at runtime left
    stale pixels behind (reported as buttons "glitching"). The body must be a
    fixed-size stack so More Info/Hide Details never changes dlg.size()."""
    dlg = VintageMessageBox(None)
    dlg.setText("Short summary")
    dlg.setDetailedText("line 1\n" * 40)
    dlg.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
    dlg.show()
    qapp.processEvents()
    try:
        before = dlg.size()
        dlg._toggle_detail()
        qapp.processEvents()
        assert dlg.size() == before
        dlg._toggle_detail()
        qapp.processEvents()
        assert dlg.size() == before
    finally:
        dlg.close()
        dlg.deleteLater()


def test_setting_empty_detailed_text_removes_button(qapp):
    dlg = VintageMessageBox(None)
    dlg.setDetailedText("some detail")
    assert dlg._detail_btn is not None
    dlg.setDetailedText("")
    try:
        assert dlg._detail_btn is None
    finally:
        dlg.deleteLater()


def test_body_stack_stays_transparent(qapp):
    """Regression: QStackedWidget is a QFrame -- once WA_StyledBackground
    cascades down from the dialog/shell stylesheets, an unstyled QFrame paints
    an opaque palette background instead of staying transparent, hiding the
    shell's warm gradient behind a flat cream box."""
    dlg = VintageMessageBox(None)
    try:
        assert "background: transparent" in dlg._body_stack.styleSheet()
        assert "background: transparent" in dlg._summary_page.styleSheet()
    finally:
        dlg.deleteLater()


def test_standard_buttons_survive_detail_button_present(qapp):
    """Regression: adding the left-aligned More Info button must not break the
    footer's stretch/removal bookkeeping for the normal OK/Cancel buttons."""
    dlg = VintageMessageBox(None)
    dlg.setDetailedText("some detail")
    dlg.setStandardButtons(
        QtWidgets.QMessageBox.StandardButton.Ok
        | QtWidgets.QMessageBox.StandardButton.Cancel
    )
    try:
        assert len(dlg._buttons) == 2
        # Re-applying standard buttons should cleanly replace them, not
        # accumulate or drop the stretch/detail button.
        dlg.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        assert len(dlg._buttons) == 1
        assert dlg._detail_btn is not None
    finally:
        dlg.deleteLater()
