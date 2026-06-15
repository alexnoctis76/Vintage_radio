"""Frameless alert dialogs matching Sync modal chrome (no native title bar)."""

from __future__ import annotations

from typing import List, Optional, Tuple, Union

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from gui.widgets.dialogs.sync.primitives import (
    ModalButton,
    ModalFooter,
    ModalHeader,
    SyncModalShell,
    apply_frameless_modal,
    apply_modal_rounded_mask,
)

ButtonSpec = Union[QtWidgets.QMessageBox.StandardButton, str]
StdButton = QtWidgets.QMessageBox.StandardButton


def _button_label(spec: ButtonSpec) -> str:
    if isinstance(spec, StdButton):
        return {
            StdButton.Ok: "OK",
            StdButton.Cancel: "Cancel",
            StdButton.Yes: "Yes",
            StdButton.No: "No",
            StdButton.Close: "Close",
            StdButton.Save: "Save",
            StdButton.Discard: "Discard",
            StdButton.Apply: "Apply",
            StdButton.Reset: "Reset",
            StdButton.RestoreDefaults: "Restore Defaults",
            StdButton.Help: "Help",
            StdButton.SaveAll: "Save All",
            StdButton.YesToAll: "Yes to All",
            StdButton.NoToAll: "No to All",
            StdButton.Open: "Open",
            StdButton.Abort: "Abort",
            StdButton.Retry: "Retry",
            StdButton.Ignore: "Ignore",
        }.get(spec, "OK")
    return str(spec)


def _variant_for_button(
    spec: ButtonSpec,
    role: Optional[QtWidgets.QMessageBox.ButtonRole],
) -> str:
    if role == QtWidgets.QMessageBox.ButtonRole.DestructiveRole:
        return "danger"
    if isinstance(spec, StdButton):
        if spec in (StdButton.Ok, StdButton.Yes, StdButton.YesToAll, StdButton.Save):
            return "primary"
        if spec in (StdButton.No, StdButton.Cancel, StdButton.Close, StdButton.Abort):
            return "secondary"
    if role == QtWidgets.QMessageBox.ButtonRole.AcceptRole:
        return "primary"
    return "secondary"


class VintageMessageBox(QtWidgets.QDialog):
    """Drop-in styled replacement for ``QMessageBox`` (frameless sync shell)."""

    StandardButton = QtWidgets.QMessageBox.StandardButton
    ButtonRole = QtWidgets.QMessageBox.ButtonRole
    Icon = QtWidgets.QMessageBox.Icon

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self._title = ""
        self._text = ""
        self._informative = ""
        self._icon = self.Icon.NoIcon
        self._buttons: List[Tuple[QtWidgets.QPushButton, object, Optional[QtWidgets.QMessageBox.ButtonRole]]] = []
        self._clicked: Optional[QtWidgets.QPushButton] = None
        self._default_btn: Optional[QtWidgets.QPushButton] = None
        self._width = t.SYNC_MDL_CONFIRM_W
        self._scroll_area: Optional[QtWidgets.QWidget] = None
        self._scroll_edit: Optional[QtWidgets.QPlainTextEdit] = None
        self._build_shell()

    def _build_shell(self) -> None:
        apply_frameless_modal(self)
        self.setStyleSheet("QDialog { background: transparent; }")
        self._outer = QtWidgets.QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._shell = SyncModalShell()
        self._header = ModalHeader("", "")
        self._header.closed.connect(self.reject)
        self._shell.add_widget(self._header)
        self._body = QtWidgets.QWidget()
        self._body_lay = QtWidgets.QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            12,
            t.SYNC_MDL_CONFIRM_BODY_PAD,
            4,
        )
        self._body_lay.setSpacing(8)
        self._text_lbl = QtWidgets.QLabel()
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setStyleSheet(self._main_text_style())
        self._body_lay.addWidget(self._text_lbl)
        self._info_lbl = QtWidgets.QLabel()
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._info_lbl.setStyleSheet(self._info_text_style())
        self._info_lbl.hide()
        self._body_lay.addWidget(self._info_lbl)
        self._shell.add_widget(self._body)
        self._footer = ModalFooter()
        self._shell.add_widget(self._footer)
        self._outer.addWidget(self._shell)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(24, 12, 4, 112))
        self._shell.setGraphicsEffect(shadow)
        apply_modal_rounded_mask(self)

    @staticmethod
    def _main_text_style() -> str:
        return (
            f"color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CARD_BODY_SIZE)}px;"
            f"background: transparent;"
        )

    @staticmethod
    def _info_text_style() -> str:
        return (
            f"color: {t.SYNC_MDL_CARD_BODY_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CONFIRM_TEXT_SIZE)}px;"
            f"background: transparent;"
        )

    def setWindowTitle(self, title: str) -> None:  # noqa: N802 — Qt API
        self._title = title
        self._header._title_lbl.setText(title)

    @staticmethod
    def _scrollable_text_style() -> str:
        return (
            f"color: {t.SYNC_MDL_CONFIRM_TEXT_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CONFIRM_TEXT_SIZE)}px;"
            f"background: transparent;"
            f"border: none;"
            f"font-family: Consolas, 'Courier New', monospace;"
        )

    @staticmethod
    def _needs_scrollable_text(text: str) -> bool:
        stripped = (text or "").strip()
        if not stripped:
            return False
        if "Traceback (most recent call last)" in stripped:
            return True
        return len(stripped) > 320 or stripped.count("\n") > 5

    def _show_scrollable_text(self, text: str) -> None:
        if self._scroll_edit is None:
            self._scroll_edit = QtWidgets.QPlainTextEdit()
            self._scroll_edit.setReadOnly(True)
            self._scroll_edit.setLineWrapMode(
                QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth
            )
            self._scroll_edit.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            self._scroll_area = wrap_with_mockup_scrollbar(
                self._scroll_edit,
                variant="track",
            )
            self._scroll_area.setMaximumHeight(280)
            self._body_lay.insertWidget(0, self._scroll_area)
        assert self._scroll_edit is not None
        self._scroll_edit.setPlainText(text)
        self._scroll_edit.setStyleSheet(self._scrollable_text_style())
        self._scroll_area.show()
        self._text_lbl.hide()

    def setText(self, text: str) -> None:
        self._text = text
        if self._needs_scrollable_text(text):
            self._show_scrollable_text(text)
        else:
            if self._scroll_area is not None:
                self._scroll_area.hide()
            self._text_lbl.setText(text)
            self._text_lbl.show()

    def setInformativeText(self, text: str) -> None:
        self._informative = text
        self._info_lbl.setText(text)
        self._info_lbl.setVisible(bool(text.strip()))

    def setIcon(self, icon: QtWidgets.QMessageBox.Icon) -> None:  # noqa: ARG002
        self._icon = icon

    def setStandardButtons(
        self, buttons: QtWidgets.QMessageBox.StandardButton
    ) -> None:
        self._clear_buttons()
        specs: List[StdButton] = []
        for flag in (
            StdButton.Ok,
            StdButton.Cancel,
            StdButton.Yes,
            StdButton.No,
            StdButton.Close,
            StdButton.Save,
        ):
            if buttons & flag:
                specs.append(flag)
        for spec in specs:
            self.addButton(spec)

    def addButton(
        self,
        button: ButtonSpec,
        role: Optional[QtWidgets.QMessageBox.ButtonRole] = None,
    ) -> QtWidgets.QPushButton:
        label = _button_label(button)
        variant = _variant_for_button(button, role)
        btn = ModalButton(label, variant=variant)  # type: ignore[arg-type]
        btn.clicked.connect(lambda checked=False, b=btn: self._on_button(b))
        self._footer.add_button(btn)
        self._buttons.append((btn, button, role))
        return btn

    def setDefaultButton(
        self, button: Union[QtWidgets.QPushButton, QtWidgets.QMessageBox.StandardButton]
    ) -> None:
        if isinstance(button, QtWidgets.QPushButton):
            self._default_btn = button
            button.setDefault(True)
            button.setFocus()
            return
        for btn, spec, _role in self._buttons:
            if btn is button:
                self._default_btn = btn
                btn.setDefault(True)
                btn.setFocus()
                break
            if spec == button:
                self._default_btn = btn
                btn.setDefault(True)
                btn.setFocus()
                break

    def clickedButton(self) -> Optional[QtWidgets.QAbstractButton]:
        return self._clicked

    def _clear_buttons(self) -> None:
        for btn, _spec, _role in self._buttons:
            btn.deleteLater()
        self._buttons.clear()
        while self._footer._row.count() > 1:
            item = self._footer._row.takeAt(1)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

    def _on_button(self, btn: QtWidgets.QPushButton) -> None:
        self._clicked = btn
        for b, spec, role in self._buttons:
            if b is not btn:
                continue
            if isinstance(spec, StdButton) and spec in (
                StdButton.Cancel,
                StdButton.No,
                StdButton.Close,
                StdButton.Abort,
            ):
                self.reject()
                return
            if role in (
                QtWidgets.QMessageBox.ButtonRole.RejectRole,
                QtWidgets.QMessageBox.ButtonRole.NoRole,
            ):
                self.reject()
                return
        self.accept()

    def _apply_content(self) -> None:
        self.setFixedWidth(self._width)
        self._text_lbl.setStyleSheet(self._main_text_style())
        self._info_lbl.setStyleSheet(self._info_text_style())

    @classmethod
    def _run(
        cls,
        parent: Optional[QtWidgets.QWidget],
        title: str,
        text: str,
        *,
        informative_text: str = "",
        buttons: QtWidgets.QMessageBox.StandardButton,
        default: QtWidgets.QMessageBox.StandardButton,
        icon: QtWidgets.QMessageBox.Icon = QtWidgets.QMessageBox.Icon.NoIcon,
        width: Optional[int] = None,
    ) -> QtWidgets.QMessageBox.StandardButton:
        dlg = cls(parent)
        if width is not None:
            dlg._width = width
        dlg.setWindowTitle(title)
        dlg.setText(text)
        if informative_text:
            dlg.setInformativeText(informative_text)
        dlg.setIcon(icon)
        dlg.setStandardButtons(buttons)
        dlg.setDefaultButton(default)
        dlg._apply_content()
        dlg.exec()
        clicked = dlg.clickedButton()
        if clicked is None:
            return default
        for btn, spec, _role in dlg._buttons:
            if btn is clicked and isinstance(spec, StdButton):
                return spec
        return default

    @staticmethod
    def question(
        parent: Optional[QtWidgets.QWidget],
        title: str,
        text: str,
        buttons: QtWidgets.QMessageBox.StandardButton = (
            StdButton.Yes | StdButton.No
        ),
        default: QtWidgets.QMessageBox.StandardButton = StdButton.No,
    ) -> QtWidgets.QMessageBox.StandardButton:
        return VintageMessageBox._run(
            parent,
            title,
            text,
            buttons=buttons,
            default=default,
            icon=VintageMessageBox.Icon.Question,
        )

    @staticmethod
    def information(
        parent: Optional[QtWidgets.QWidget],
        title: str,
        text: str,
        buttons: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
        default: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
    ) -> QtWidgets.QMessageBox.StandardButton:
        return VintageMessageBox._run(
            parent,
            title,
            text,
            buttons=buttons,
            default=default,
            icon=VintageMessageBox.Icon.Information,
        )

    @staticmethod
    def warning(
        parent: Optional[QtWidgets.QWidget],
        title: str,
        text: str,
        buttons: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
        default: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
    ) -> QtWidgets.QMessageBox.StandardButton:
        return VintageMessageBox._run(
            parent,
            title,
            text,
            buttons=buttons,
            default=default,
            icon=VintageMessageBox.Icon.Warning,
        )

    @staticmethod
    def critical(
        parent: Optional[QtWidgets.QWidget],
        title: str,
        text: str,
        buttons: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
        default: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
    ) -> QtWidgets.QMessageBox.StandardButton:
        return VintageMessageBox._run(
            parent,
            title,
            text,
            buttons=buttons,
            default=default,
            icon=VintageMessageBox.Icon.Critical,
        )
