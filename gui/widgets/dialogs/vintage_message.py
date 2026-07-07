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
        self._detail_text = ""
        self._detail_visible = False
        self._detail_btn: Optional[QtWidgets.QPushButton] = None
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
        self._body_lay.setSpacing(0)
        # A QStackedWidget reserves space for the largest page up front, so
        # toggling "More Info" swaps content in place without ever resizing this
        # frameless/translucent dialog -- resizing it at runtime left stale pixels
        # from the old layout behind (the reported "glitch").
        self._body_stack = QtWidgets.QStackedWidget()
        # QStackedWidget is a QFrame -- once WA_StyledBackground is cascaded down
        # from the dialog/shell stylesheets, an unstyled QFrame paints an opaque
        # palette background instead of staying transparent. Without this it hides
        # the shell's warm gradient behind a flat cream box.
        self._body_stack.setStyleSheet(
            "QStackedWidget { background: transparent; border: none; }"
        )
        self._summary_page = QtWidgets.QWidget()
        self._summary_page.setStyleSheet("background: transparent;")
        summary_lay = QtWidgets.QVBoxLayout(self._summary_page)
        summary_lay.setContentsMargins(0, 0, 0, 0)
        summary_lay.setSpacing(8)
        self._text_lbl = QtWidgets.QLabel()
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setStyleSheet(self._main_text_style())
        summary_lay.addWidget(self._text_lbl)
        self._info_lbl = QtWidgets.QLabel()
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._info_lbl.setStyleSheet(self._info_text_style())
        self._info_lbl.hide()
        summary_lay.addWidget(self._info_lbl)
        self._body_stack.addWidget(self._summary_page)
        self._body_lay.addWidget(self._body_stack)
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

    def _ensure_scroll_widget(self) -> None:
        """Create (and register with the body stack) the scrollable text page.

        Called eagerly from setDetailedText() -- not lazily on first toggle --
        so the stack already knows about both pages, and their combined sizeHint,
        before the dialog is ever shown. Adding a page after the dialog is shown
        would grow the window on the first "More Info" click.
        """
        if self._scroll_edit is not None:
            return
        self._scroll_edit = QtWidgets.QPlainTextEdit()
        self._scroll_edit.setReadOnly(True)
        self._scroll_edit.setLineWrapMode(
            QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self._scroll_edit.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll_edit.setStyleSheet(self._scrollable_text_style())
        self._scroll_area = wrap_with_mockup_scrollbar(
            self._scroll_edit,
            variant="track",
        )
        self._scroll_area.setMaximumHeight(280)
        self._body_stack.addWidget(self._scroll_area)

    def _show_scrollable_text(self, text: str) -> None:
        self._ensure_scroll_widget()
        assert self._scroll_edit is not None
        self._scroll_edit.setPlainText(text)
        self._body_stack.setCurrentWidget(self._scroll_area)

    def setText(self, text: str) -> None:
        self._text = text
        if self._needs_scrollable_text(text):
            self._show_scrollable_text(text)
        else:
            self._text_lbl.setText(text)
            self._body_stack.setCurrentWidget(self._summary_page)

    def setInformativeText(self, text: str) -> None:
        self._informative = text
        self._info_lbl.setText(text)
        self._info_lbl.setVisible(bool(text.strip()))

    def setDetailedText(self, text: str) -> None:
        """Attach technical detail (traceback, raw command output, etc.) that stays
        hidden behind a "More Info" toggle until the user asks for it."""
        self._detail_text = (text or "").strip()
        if self._detail_text:
            self._ensure_scroll_widget()
            if self._detail_btn is None:
                self._detail_btn = ModalButton("More Info", variant="secondary")
                self._detail_btn.clicked.connect(self._toggle_detail)
                self._footer.add_left_widget(self._detail_btn)
        elif self._detail_btn is not None:
            self._detail_btn.deleteLater()
            self._detail_btn = None
            self._detail_visible = False

    def _toggle_detail(self) -> None:
        self._detail_visible = not self._detail_visible
        if self._detail_visible:
            self._show_scrollable_text(self._detail_text)
            if self._detail_btn is not None:
                self._detail_btn.setText("Hide Details")
        else:
            self._body_stack.setCurrentWidget(self._summary_page)
            if self._detail_btn is not None:
                self._detail_btn.setText("More Info")

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
        # Remove only the tracked accept/reject buttons -- do not touch the
        # stretch or a "More Info" button that may sit to the left of it.
        for btn, _spec, _role in self._buttons:
            self._footer._row.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

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
        detailed_text: str = "",
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
        if detailed_text:
            dlg.setDetailedText(detailed_text)
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
        detailed_text: str = "",
    ) -> QtWidgets.QMessageBox.StandardButton:
        return VintageMessageBox._run(
            parent,
            title,
            text,
            buttons=buttons,
            default=default,
            icon=VintageMessageBox.Icon.Information,
            detailed_text=detailed_text,
        )

    @staticmethod
    def warning(
        parent: Optional[QtWidgets.QWidget],
        title: str,
        text: str,
        buttons: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
        default: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
        detailed_text: str = "",
    ) -> QtWidgets.QMessageBox.StandardButton:
        return VintageMessageBox._run(
            parent,
            title,
            text,
            buttons=buttons,
            default=default,
            icon=VintageMessageBox.Icon.Warning,
            detailed_text=detailed_text,
        )

    @staticmethod
    def critical(
        parent: Optional[QtWidgets.QWidget],
        title: str,
        text: str,
        buttons: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
        default: QtWidgets.QMessageBox.StandardButton = StdButton.Ok,
        detailed_text: str = "",
    ) -> QtWidgets.QMessageBox.StandardButton:
        return VintageMessageBox._run(
            parent,
            title,
            text,
            buttons=buttons,
            default=default,
            icon=VintageMessageBox.Icon.Critical,
            detailed_text=detailed_text,
        )
