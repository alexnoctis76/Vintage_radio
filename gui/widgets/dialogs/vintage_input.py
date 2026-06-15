"""Frameless text / choice prompts matching Sync modal chrome."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple, Union

from PyQt6 import QtCore, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.styled_combo import VintageComboBox
from gui.widgets.dialogs.sync.primitives import (
    ModalButton,
    ModalFooter,
    begin_sync_modal_dialog,
)


def _field_style() -> str:
    return f"""
        QLineEdit, QPlainTextEdit {{
            color: {t.POPUP_DLG_INPUT_FG};
            background: {t.POPUP_DLG_INPUT_BG};
            border: 1px solid {t.POPUP_DLG_INPUT_BORDER};
            border-radius: {t.TOOLS_PATH_FIELD_RADIUS}px;
            padding: 8px 10px;
            font-size: {u.px(t.SYNC_MDL_CONFIRM_TEXT_SIZE)}px;
        }}
    """


class _VintageFormDialog(QtWidgets.QDialog):
    """Sync-styled form with optional field widget and OK / Cancel."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        *,
        title: str,
        subtitle: str = "",
        field: Optional[QtWidgets.QWidget] = None,
        ok_label: str = "OK",
        cancel_label: str = "Cancel",
        width: int = t.SYNC_MDL_CONFIRM_W,
    ) -> None:
        super().__init__(parent)
        self._result_value: str = ""

        body_lay, footer = begin_sync_modal_dialog(
            self,
            title=title,
            subtitle=subtitle,
            width=width,
        )
        if field is not None:
            body_lay.addWidget(field)
        body_lay.addStretch(0)

        cancel_btn = ModalButton(cancel_label, variant="secondary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = ModalButton(ok_label, variant="primary")
        ok_btn.clicked.connect(self.accept)
        footer.add_button(cancel_btn)
        footer.add_button(ok_btn)

        self._field = field
        self._ok_btn = ok_btn

    def result_value(self) -> str:
        return self._result_value


def get_text(
    parent: Optional[QtWidgets.QWidget],
    title: str,
    label: str,
    *,
    text: str = "",
    echo: QtWidgets.QLineEdit.EchoMode = QtWidgets.QLineEdit.EchoMode.Normal,
) -> Tuple[str, bool]:
    edit = QtWidgets.QLineEdit(text)
    edit.setEchoMode(echo)
    edit.setStyleSheet(_field_style())

    dlg = _VintageFormDialog(parent, title=title, subtitle=label, field=edit)
    edit.returnPressed.connect(dlg.accept)
    if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return "", False
    return edit.text().strip(), True


def get_item(
    parent: Optional[QtWidgets.QWidget],
    title: str,
    label: str,
    items: Sequence[str],
    current: int = 0,
    editable: bool = False,
) -> Tuple[str, bool]:
    combo = VintageComboBox(
        min_width=280,
        max_width=9999,
        fixed_height=t.TOOLS_ACTION_BTN_H,
    )
    for item in items:
        combo.addItem(str(item))
    if items:
        combo.setCurrentIndex(max(0, min(current, len(items) - 1)))
    combo.setEditable(editable)

    dlg = _VintageFormDialog(parent, title=title, subtitle=label, field=combo)
    if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return "", False
    return combo.currentText().strip(), True


def get_multiline_text(
    parent: Optional[QtWidgets.QWidget],
    title: str,
    label: str,
    *,
    text: str = "",
    min_height: int = 160,
) -> Tuple[str, bool]:
    edit = QtWidgets.QPlainTextEdit()
    edit.setPlainText(text)
    edit.setMinimumHeight(min_height)
    edit.setStyleSheet(_field_style())

    dlg = _VintageFormDialog(
        parent,
        title=title,
        subtitle=label,
        field=edit,
        width=t.SYNC_MDL_CONFIRM_W + 40,
    )
    if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return "", False
    return edit.toPlainText(), True
