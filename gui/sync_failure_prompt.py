"""Thread-safe sync failure prompts (background worker -> Qt main thread)."""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Literal, Optional, Union

from PyQt6 import QtCore, QtWidgets

from gui.widgets.dialogs.vintage_message import VintageMessageBox

SyncFailureAction = Literal["stop", "skip", "skip_all"]

_StdButton = VintageMessageBox.StandardButton
_SKIP_ALL_LABEL = "Skip all remaining"
_ButtonSpec = Union[_StdButton, str]
_PROMPT_WAIT_TIMEOUT_S = 300.0

_log = logging.getLogger(__name__)


def sync_failure_dialog_buttons() -> tuple[_ButtonSpec, ...]:
    """Button specs for the sync failure prompt (PyQt6 has no IgnoreAll enum)."""
    return (_StdButton.Abort, _StdButton.Ignore, _SKIP_ALL_LABEL)


def map_sync_failure_choice(spec: object) -> SyncFailureAction:
    """Map the clicked VintageMessageBox button spec to a sync failure action."""
    if spec == _StdButton.Abort:
        return "stop"
    if spec == _SKIP_ALL_LABEL:
        return "skip_all"
    return "skip"


def run_sync_failure_choice(
    parent: Optional[QtWidgets.QWidget],
    body: str,
) -> SyncFailureAction:
    """Show the sync failure dialog and return the user's choice."""
    dlg = VintageMessageBox(parent)
    dlg.setWindowTitle("Track problem during sync")
    dlg.setText(body)
    dlg.setIcon(VintageMessageBox.Icon.Warning)
    abort_btn = dlg.addButton(_StdButton.Abort)
    for spec in sync_failure_dialog_buttons()[1:]:
        dlg.addButton(spec)
    dlg.setDefaultButton(abort_btn)
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
        if not self._waiter.wait(timeout=_PROMPT_WAIT_TIMEOUT_S):
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
        path = str(info.get("path") or "?")
        station = str(info.get("station") or "").strip()
        err = str(info.get("error") or "Unknown problem").strip()
        if len(err) > 400:
            err = err[:400] + "..."

        if kind == "hash_mismatch":
            headline = "A library file no longer matches its saved fingerprint."
            detail = (
                "The file may have been edited, replaced, or corrupted since it was added "
                "to the library."
            )
        elif kind == "copy_failure":
            headline = "A track could not be copied to the SD card."
            detail = err
        else:
            headline = "A library file could not be converted to DFPlayer-safe MP3."
            detail = err

        station_line = f"\nStation: {station}" if station else ""
        body = (
            f"{headline}\n\n"
            f"File: {name}{station_line}\n"
            f"Path: {path}\n\n"
            f"{detail}\n\n"
            "Stop sync to fix the file in your library, or skip it and continue with "
            "the remaining tracks."
        )

        try:
            self._result = run_sync_failure_choice(self._parent, body)
        except Exception:
            _log.exception("Sync failure prompt failed; defaulting to skip")
            self._result = "skip"
        finally:
            if self._waiter is not None:
                self._waiter.set()
