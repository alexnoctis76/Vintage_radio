"""Thread-safe sync failure prompts (background worker -> Qt main thread)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Literal, Optional, Union

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.styled_checkbox import VintageCheckBox
from gui.widgets.dialogs.modal_body_text import ModalBodyText
from gui.widgets.dialogs.sync.primitives import (
    ModalButton,
    ModalFooter,
    ModalHeader,
    SyncModalShell,
    apply_frameless_modal,
    apply_modal_rounded_mask,
)
from gui.widgets.dialogs.vintage_message import VintageMessageBox

SyncFailureAction = Literal["stop", "skip", "skip_all", "accept_file", "accept_all"]

_StdButton = VintageMessageBox.StandardButton
_SKIP_ALL_LABEL = "Skip rest"
_UPDATE_TRACK_LABEL = "Update Track"
_SKIP_TRACK_LABEL = "Skip Track"
_APPLY_ALL_CHECKBOX = "Apply to all remaining mismatches in this sync"
_ButtonSpec = Union[_StdButton, str]
_PROMPT_WAIT_TIMEOUT_S = 300.0

_log = logging.getLogger(__name__)


def sync_failure_dialog_buttons() -> tuple[_ButtonSpec, ...]:
    """Button specs for non-hash sync failure prompts (VintageMessageBox)."""
    return (_StdButton.Abort, _StdButton.Ignore, _SKIP_ALL_LABEL)


def map_sync_failure_choice(spec: object) -> SyncFailureAction:
    """Map VintageMessageBox footer button specs to sync failure actions."""
    if spec == _StdButton.Abort:
        return "stop"
    if spec == _SKIP_ALL_LABEL:
        return "skip_all"
    if spec == _StdButton.Ignore:
        return "skip"
    return "skip"


class _HashMismatchSyncDialog(QtWidgets.QDialog):
    """Hash mismatch prompt: three centered actions + optional apply-to-all."""

    def __init__(self, parent: Optional[QtWidgets.QWidget], body: str) -> None:
        super().__init__(parent)
        self._result: SyncFailureAction = "stop"
        self.setModal(True)
        self.setWindowTitle("File changed on disk")
        self.setFixedWidth(t.SYNC_MDL_SYNC_FAILURE_W)
        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        shell = SyncModalShell()
        header = ModalHeader("File changed on disk", "")
        header.closed.connect(self.reject)
        shell.add_widget(header)

        body_w = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(body_w)
        body_lay.setContentsMargins(
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            12,
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            8,
        )
        body_lay.setSpacing(12)

        text_lbl = ModalBodyText(body)
        text_lbl.setStyleSheet(
            f"color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CARD_BODY_SIZE)}px;"
            f"background: transparent;"
        )
        self._body_text_lbl = text_lbl
        body_lay.addWidget(text_lbl)

        self._apply_all_cb = VintageCheckBox(_APPLY_ALL_CHECKBOX)
        body_lay.addWidget(self._apply_all_cb)
        shell.add_widget(body_w)

        footer = ModalFooter()
        abort_btn = ModalButton("Abort", variant="secondary")
        update_btn = ModalButton(_UPDATE_TRACK_LABEL, variant="primary")
        skip_btn = ModalButton(_SKIP_TRACK_LABEL, variant="secondary")
        abort_btn.clicked.connect(self._on_abort)
        update_btn.clicked.connect(self._on_update)
        skip_btn.clicked.connect(self._on_skip)
        footer.add_button(abort_btn)
        footer.add_button(update_btn)
        footer.add_button(skip_btn)
        footer.center_action_buttons()
        shell.add_widget(footer)

        outer.addWidget(shell)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(24, 12, 4, 112))
        shell.setGraphicsEffect(shadow)
        apply_modal_rounded_mask(self)

        update_btn.setDefault(True)
        update_btn.setFocus()

    def _apply_all(self) -> bool:
        return self._apply_all_cb.isChecked()

    def _on_abort(self) -> None:
        self._result = "stop"
        self.reject()

    def _on_update(self) -> None:
        self._result = "accept_all" if self._apply_all() else "accept_file"
        self.accept()

    def _on_skip(self) -> None:
        self._result = "skip_all" if self._apply_all() else "skip"
        self.accept()

    def chosen_action(self) -> SyncFailureAction:
        return self._result


def run_hash_mismatch_sync_choice(
    parent: Optional[QtWidgets.QWidget],
    body: str,
    *,
    register_dialog: Optional[Callable[[QtWidgets.QDialog], None]] = None,
) -> SyncFailureAction:
    dlg = _HashMismatchSyncDialog(parent, body)
    if register_dialog is not None:
        register_dialog(dlg)
    code = dlg.exec()
    if code != QtWidgets.QDialog.DialogCode.Accepted:
        return "stop"
    return dlg.chosen_action()


def run_sync_failure_choice(
    parent: Optional[QtWidgets.QWidget],
    body: str,
    *,
    register_dialog: Optional[Callable[[VintageMessageBox], None]] = None,
) -> SyncFailureAction:
    """Show the sync failure dialog and return the user's choice."""
    dlg = VintageMessageBox(parent)
    if register_dialog is not None:
        register_dialog(dlg)
    dlg.setWindowTitle("Track problem during sync")
    dlg.setText(body)
    dlg.setIcon(VintageMessageBox.Icon.Warning)
    specs = sync_failure_dialog_buttons()
    for spec in specs:
        dlg.addButton(spec)
    if dlg._buttons:
        dlg.setDefaultButton(dlg._buttons[0][0])
    dlg._apply_content()
    dlg.exec()
    clicked = dlg.clickedButton()
    if clicked is None:
        return "stop"
    for btn, spec, _role in dlg._buttons:
        if btn is clicked:
            return map_sync_failure_choice(spec)
    return "stop"


class SyncFailurePrompter(QtCore.QObject):
    """Ask the user how to handle a bad library file while sync runs on a worker thread."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._waiter: Optional[threading.Event] = None
        self._pending: Optional[Dict[str, Any]] = None
        self._result: SyncFailureAction = "skip"
        self._should_cancel: Optional[Callable[[], bool]] = None
        self._open_dlg: Optional[QtWidgets.QDialog] = None

    def set_should_cancel(self, fn: Optional[Callable[[], bool]]) -> None:
        self._should_cancel = fn

    @QtCore.pyqtSlot()
    def _force_stop_prompt(self) -> None:
        self._result = "stop"
        dlg = self._open_dlg
        if dlg is not None:
            try:
                dlg.reject()
            except RuntimeError:
                pass
        if self._waiter is not None and not self._waiter.is_set():
            self._waiter.set()

    def ask(self, info: Dict[str, Any]) -> SyncFailureAction:
        """Block the calling thread until the user chooses an action on the GUI thread."""
        self._pending = dict(info)
        self._waiter = threading.Event()
        QtCore.QMetaObject.invokeMethod(
            self,
            "_show_dialog",
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        assert self._waiter is not None
        deadline = time.monotonic() + _PROMPT_WAIT_TIMEOUT_S
        while not self._waiter.wait(timeout=0.25):
            if self._should_cancel and self._should_cancel():
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_force_stop_prompt",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                )
                self._waiter.wait(timeout=2.0)
                return "stop"
            if time.monotonic() >= deadline:
                break
        if not self._waiter.is_set():
            _log.warning(
                "Sync failure prompt timed out after %.0fs; defaulting to skip",
                _PROMPT_WAIT_TIMEOUT_S,
            )
            self._result = "skip"
        return self._result

    @QtCore.pyqtSlot()
    def _show_dialog(self) -> None:
        info = self._pending or {}
        kind = str(info.get("kind") or "problem")
        name = str(info.get("name") or "?")
        station = str(info.get("station") or "").strip()
        err = str(info.get("error") or "Unknown problem").strip()
        if len(err) > 400:
            err = err[:400] + "..."

        if kind == "hash_mismatch":
            headline = (
                "This track's file on your computer no longer matches what the library "
                "has saved."
            )
            detail = (
                "That often happens after retagging, re-exporting, or editing the file "
                "outside Vintage Radio."
            )
        elif kind == "copy_failure":
            headline = "A track could not be copied to the SD card."
            detail = err
        else:
            headline = "A library file could not be converted to DFPlayer-safe MP3."
            detail = err

        station_line = f"\nStation: {station}" if station else ""
        if kind == "hash_mismatch":
            hint = (
                "Choose Update Track to save the file as it is now and copy it to the SD "
                "card, or Skip Track to leave the library unchanged for this slot."
            )
        else:
            hint = (
                "Stop sync to fix the file in your library, or skip it and continue "
                "with the remaining tracks."
            )
        body = (
            f"{headline}\n\n"
            f"Track: {name}{station_line}\n"
            f"{detail}\n\n"
            f"{hint}"
        )

        try:
            self._open_dlg = None
            if kind == "hash_mismatch":
                self._result = run_hash_mismatch_sync_choice(
                    self._parent,
                    body,
                    register_dialog=lambda d: setattr(self, "_open_dlg", d),
                )
            else:
                self._result = run_sync_failure_choice(
                    self._parent,
                    body,
                    register_dialog=lambda d: setattr(self, "_open_dlg", d),
                )
        except Exception:
            _log.exception("Sync failure prompt failed; defaulting to skip")
            self._result = "skip"
        finally:
            self._open_dlg = None
            if self._waiter is not None:
                self._waiter.set()
