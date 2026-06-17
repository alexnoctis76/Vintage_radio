"""
Reusable building blocks for sync modal dialogs (mockup: gui/scratch.html).

HOW TO EDIT
-----------
  All colours, sizes, and radii → gui/theme.py  (SYNC_MDL_* constants)
"""

from __future__ import annotations

from typing import Literal, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u

ButtonVariant = Literal["primary", "secondary", "danger", "update", "full_refresh"]


def apply_frameless_modal(dialog: QtWidgets.QDialog) -> None:
    """Hide the native OS title bar; the modal chrome provides its own close button."""
    dialog.setWindowFlags(
        QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint
    )
    dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)


def apply_modal_rounded_mask(dialog: QtWidgets.QDialog) -> None:
    """Clip frameless sync modals to SYNC_MDL_RADIUS rounded corners."""
    from gui.window_chrome import apply_modal_rounded_mask as _apply

    _apply(dialog)


def refresh_modal_rounded_mask(dialog: QtWidgets.QDialog) -> None:
    """Re-apply the rounded window mask after theme size/radius changes."""
    filt = getattr(dialog, "_modal_round_filter", None)
    if filt is not None:
        filt._apply()


def begin_sync_modal_dialog(
    dialog: QtWidgets.QDialog,
    *,
    title: str,
    subtitle: str = "",
    width: Optional[int] = None,
    min_width: Optional[int] = None,
) -> Tuple[QtWidgets.QVBoxLayout, ModalFooter]:
    """Apply frameless sync chrome; return ``(body_layout, footer)``."""
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    if width is not None:
        dialog.setFixedWidth(width)
    elif min_width is not None:
        dialog.setMinimumWidth(min_width)
    apply_frameless_modal(dialog)
    dialog.setStyleSheet("QDialog { background: transparent; }")

    outer = QtWidgets.QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)

    shell = SyncModalShell()
    header = ModalHeader(title, subtitle)
    header.closed.connect(dialog.reject)
    shell.add_widget(header)

    body = QtWidgets.QWidget()
    body_lay = QtWidgets.QVBoxLayout(body)
    body_lay.setContentsMargins(
        t.SYNC_MDL_BODY_PAD, 12, t.SYNC_MDL_BODY_PAD, 16,
    )
    body_lay.setSpacing(10)
    shell.add_widget(body)

    footer = ModalFooter()
    shell.add_widget(footer)

    outer.addWidget(shell)

    shadow = QtWidgets.QGraphicsDropShadowEffect(dialog)
    shadow.setBlurRadius(48)
    shadow.setOffset(0, 12)
    shadow.setColor(QtGui.QColor(24, 12, 4, 112))
    shell.setGraphicsEffect(shadow)

    apply_modal_rounded_mask(dialog)
    return body_lay, footer


def _reload_sync_modal_subtree(root: QtWidgets.QWidget) -> None:
    """Reload themed children inside a plain container (e.g. dialog body)."""
    for w in root.findChildren(QtWidgets.QWidget):
        if hasattr(w, "reload_theme"):
            w.reload_theme()


def _modal_shell_stylesheet() -> str:
    return f"""
        #syncModalShell {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.SYNC_MDL_BG_TOP},
                stop:1 {t.SYNC_MDL_BG_BOT}
            );
            border: 1px solid {t.SYNC_MDL_BORDER};
            border-radius: {t.SYNC_MDL_RADIUS}px;
        }}
    """


class ModalCloseButton(QtWidgets.QToolButton):
    """Circular × close control in the modal header."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setText("\u00d7")
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.reload_theme()

    def reload_theme(self) -> None:
        self.setFixedSize(u.px(t.SYNC_MDL_CLOSE_SIZE), u.px(t.SYNC_MDL_CLOSE_SIZE))
        self.setStyleSheet(f"""
            QToolButton {{
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: {u.px(t.SYNC_MDL_CLOSE_RADIUS)}px;
                background: rgba(255, 255, 255, 0.08);
                color: {t.SYNC_MDL_HDR_TITLE_CLR};
                font-size: {u.px(20)}px;
                font-weight: bold;
                padding: 0;
            }}
            QToolButton:hover {{
                background: rgba(255, 255, 255, 0.16);
            }}
        """)


class ModalButton(QtWidgets.QPushButton):
    """Primary / secondary / danger action button used in sync modals."""

    def __init__(
        self,
        label: str,
        *,
        variant: ButtonVariant = "primary",
        full_width: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(label, parent)
        self._variant = variant
        self._full_width = full_width
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.reload_theme()

    def _label_width(self) -> int:
        font = QtGui.QFont(self.font())
        font.setPixelSize(u.px(t.SYNC_MDL_BTN_SIZE))
        font.setWeight(QtGui.QFont.Weight.Bold)
        fm = QtGui.QFontMetrics(font)
        # Match QSS padding (12px × 2) + 2px border × 2, plus a small safety margin.
        return fm.horizontalAdvance(self.text() or "") + 32

    def reload_theme(self) -> None:
        self.setFixedHeight(u.px(t.SYNC_MDL_BTN_H))
        if self._full_width:
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
        else:
            self.setFixedWidth(max(u.px(t.SYNC_MDL_FOOTER_BTN_W), self._label_width()))
        self._apply_variant(self._variant)

    def _apply_variant(self, variant: ButtonVariant) -> None:
        if variant == "primary":
            border, top, mid, bot, color = (
                t.SYNC_MDL_BTN_PRIMARY_BORDER,
                t.SYNC_MDL_BTN_PRIMARY_TOP,
                t.SYNC_MDL_BTN_PRIMARY_MID,
                t.SYNC_MDL_BTN_PRIMARY_BOT,
                t.IF_INSTALL_BTN_FG,
            )
        elif variant == "danger":
            border, top, mid, bot, color = (
                t.SYNC_MDL_BTN_DANGER_BORDER,
                t.SYNC_MDL_BTN_DANGER_TOP,
                t.SYNC_MDL_BTN_DANGER_MID,
                t.SYNC_MDL_BTN_DANGER_BOT,
                t.SYNC_MDL_BTN_DANGER_TEXT,
            )
        elif variant == "full_refresh":
            border, top, mid, bot, color = (
                t.SYNC_MDL_BADGE_ALT_BOT,
                t.SYNC_MDL_BADGE_ALT_TOP,
                t.SYNC_MDL_BADGE_ALT_TOP,
                t.SYNC_MDL_BADGE_ALT_BOT,
                t.SYNC_MDL_BADGE_TEXT,
            )
        elif variant == "update":
            border, top, mid, bot, color = (
                t.SYNC_MDL_BADGE_BOT,
                t.SYNC_MDL_BADGE_TOP,
                t.SYNC_MDL_BADGE_TOP,
                t.SYNC_MDL_BADGE_BOT,
                t.SYNC_MDL_BADGE_TEXT,
            )
        else:
            border, top, mid, bot, color = (
                t.SYNC_MDL_BTN_SEC_BORDER,
                t.SYNC_MDL_BTN_SEC_TOP,
                t.SYNC_MDL_BTN_SEC_TOP,
                t.SYNC_MDL_BTN_SEC_BOT,
                t.SYNC_MDL_BTN_SEC_TEXT,
            )
        self.setStyleSheet(f"""
            QPushButton {{
                border: 2px solid {border};
                border-radius: {t.SYNC_MDL_BTN_RADIUS}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {top},
                    stop:0.58 {mid},
                    stop:1 {bot}
                );
                color: {color};
                font-size: {u.px(t.SYNC_MDL_BTN_SIZE)}px;
                font-weight: 700;
                padding: 0 12px;
                outline: none;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {top},
                    stop:1 {bot}
                );
                border: 2px solid {border};
            }}
            QPushButton:pressed {{
                padding-top: 2px;
                border: 2px solid {border};
            }}
            QPushButton:focus {{
                outline: none;
                border: 2px solid {border};
            }}
        """)


class ModalHeader(QtWidgets.QWidget):
    """Dark cocoa header bar with title, subtitle, and close button."""

    closed = QtCore.pyqtSignal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("syncModalHeader")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QtWidgets.QHBoxLayout(self)
        row.setSpacing(12)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(4)
        text_col.setContentsMargins(0, 10, 0, 10)

        self._title_lbl = QtWidgets.QLabel(title)
        self._title_lbl.setWordWrap(True)
        text_col.addWidget(self._title_lbl)

        self._sub_lbl: Optional[QtWidgets.QLabel] = None
        if subtitle:
            self._sub_lbl = QtWidgets.QLabel(subtitle)
            self._sub_lbl.setWordWrap(True)
            text_col.addWidget(self._sub_lbl)

        row.addLayout(text_col, 1)

        self._close_btn = ModalCloseButton(self)
        self._close_btn.clicked.connect(self.closed.emit)
        close_wrap = QtWidgets.QWidget()
        close_wrap.setStyleSheet("background: transparent;")
        self._close_wrap = close_wrap
        close_lay = QtWidgets.QVBoxLayout(close_wrap)
        close_lay.setSpacing(0)
        close_lay.addWidget(self._close_btn)
        close_lay.addStretch(1)
        row.addWidget(close_wrap, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        self._row = row
        self._close_lay = close_lay
        self.reload_theme()

    def reload_theme(self) -> None:
        self.setFixedHeight(u.px(t.SYNC_MDL_HDR_H))
        self._row.setContentsMargins(u.px(t.SYNC_MDL_HDR_PAD_L), 0, u.px(t.SYNC_MDL_HDR_PAD_R), 0)
        self._close_lay.setContentsMargins(0, u.px(t.SYNC_MDL_CLOSE_TOP_PAD), 0, 0)
        self._title_lbl.setStyleSheet(
            f"color: {t.SYNC_MDL_HDR_TITLE_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_HDR_TITLE_SIZE)}px;"
            f"font-weight: bold;"
            f"background: transparent;"
        )
        if self._sub_lbl is not None:
            self._sub_lbl.setStyleSheet(
                f"color: {t.SYNC_MDL_HDR_SUB_CLR};"
                f"font-size: {u.px(t.SYNC_MDL_HDR_SUB_SIZE)}px;"
                f"background: transparent;"
            )
        self._close_btn.reload_theme()
        self.setStyleSheet(f"""
            #syncModalHeader {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.SYNC_MDL_HDR_TOP},
                    stop:1 {t.SYNC_MDL_HDR_BOT}
                );
                border-top-left-radius: {t.SYNC_MDL_RADIUS}px;
                border-top-right-radius: {t.SYNC_MDL_RADIUS}px;
            }}
        """)


class ModalFooter(QtWidgets.QWidget):
    """Right-aligned footer row for Cancel / confirm actions."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._row = QtWidgets.QHBoxLayout(self)
        self._row.setContentsMargins(
            t.SYNC_MDL_FOOTER_PAD_H, 0, t.SYNC_MDL_FOOTER_PAD_H, t.SYNC_MDL_FOOTER_PAD_B,
        )
        self._row.setSpacing(t.SYNC_MDL_FOOTER_GAP)
        self._row.addStretch(1)

    def reload_theme(self) -> None:
        self._row.setContentsMargins(
            t.SYNC_MDL_FOOTER_PAD_H, 0, t.SYNC_MDL_FOOTER_PAD_H, t.SYNC_MDL_FOOTER_PAD_B,
        )
        self._row.setSpacing(t.SYNC_MDL_FOOTER_GAP)
        for i in range(self._row.count()):
            item = self._row.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None and hasattr(w, "reload_theme"):
                w.reload_theme()

    def add_left_widget(self, widget: QtWidgets.QWidget) -> None:
        self._row.insertWidget(0, widget)

    def add_button(self, button: QtWidgets.QPushButton) -> None:
        self._row.addWidget(button)


class SyncBadge(QtWidgets.QLabel):
    """Pill badge ('Update', 'Full refresh') on sync option cards."""

    def __init__(self, text: str, *, alt: bool = False, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(text, parent)
        self._alt = alt
        self.reload_theme()

    def reload_theme(self) -> None:
        top = t.SYNC_MDL_BADGE_ALT_TOP if self._alt else t.SYNC_MDL_BADGE_TOP
        bot = t.SYNC_MDL_BADGE_ALT_BOT if self._alt else t.SYNC_MDL_BADGE_BOT

        font = QtGui.QFont(self.font())
        font.setPixelSize(u.px(t.SYNC_MDL_BADGE_SIZE))
        font.setWeight(QtGui.QFont.Weight.ExtraBold)
        self.setFont(font)

        fm = QtGui.QFontMetrics(font)
        pad_h = u.px(t.SYNC_MDL_BADGE_PAD_H)
        pad_v = u.px(t.SYNC_MDL_BADGE_PAD_V)
        pill_h = max(fm.height() + pad_v * 2 + 4, u.px(t.SYNC_MDL_BADGE_MIN_H))
        pill_w = fm.horizontalAdvance(self.text()) + pad_h * 2
        pill_radius = pill_h // 2

        self.setFixedSize(pill_w, pill_h)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.setStyleSheet(f"""
            QLabel {{
                color: {t.SYNC_MDL_BADGE_TEXT};
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {top},
                    stop:1 {bot}
                );
                border: none;
                border-radius: {pill_radius}px;
                padding: 0 {pad_h}px;
                font-size: {u.px(t.SYNC_MDL_BADGE_SIZE)}px;
                font-weight: 800;
            }}
        """)


class SyncOptionCard(QtWidgets.QFrame):
    """One sync choice card (Sync Changes or Replace All Music)."""

    action_clicked = QtCore.pyqtSignal()

    def __init__(
        self,
        title: str,
        badge: str,
        description: str,
        helper: str,
        button_label: str,
        *,
        full_refresh: bool = False,
        button_variant: ButtonVariant = "primary",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._full_refresh = full_refresh
        self._button_variant = button_variant
        self.setObjectName("syncCardFull" if full_refresh else "syncCard")
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(0)

        topline = QtWidgets.QHBoxLayout()
        topline.setSpacing(10)
        self._title_lbl = QtWidgets.QLabel(title)
        topline.addWidget(self._title_lbl)
        self._badge = SyncBadge(badge, alt=full_refresh)
        topline.addWidget(self._badge)
        topline.addStretch(1)
        lay.addLayout(topline)
        lay.addSpacing(12)

        self._desc_lbl = QtWidgets.QLabel(description)
        self._desc_lbl.setWordWrap(True)
        lay.addWidget(self._desc_lbl)

        self._helper_lbl = QtWidgets.QLabel(helper)
        self._helper_lbl.setWordWrap(True)
        lay.addStretch(1)
        lay.addWidget(self._helper_lbl)
        lay.addSpacing(12)

        self._action = ModalButton(button_label, variant=button_variant, full_width=True)
        self._action.clicked.connect(self.action_clicked.emit)
        lay.addWidget(self._action)

        self.reload_theme()

    def reload_theme(self) -> None:
        full_refresh = self._full_refresh
        self.setMinimumHeight(u.px(t.SYNC_MDL_CARD_MIN_H))
        border = t.SYNC_MDL_CARD_ALT_BORDER if full_refresh else t.SYNC_MDL_CARD_BORDER
        bg_top = t.SYNC_MDL_CARD_ALT_BG_TOP if full_refresh else t.SYNC_MDL_CARD_BG_TOP
        bg_bot = t.SYNC_MDL_CARD_ALT_BG_BOT if full_refresh else t.SYNC_MDL_CARD_BG_BOT
        self.setStyleSheet(f"""
            QFrame#{self.objectName()} {{
                border: 1px solid {border};
                border-radius: {t.SYNC_MDL_CARD_RADIUS}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {bg_top},
                    stop:1 {bg_bot}
                );
            }}
        """)
        self._title_lbl.setStyleSheet(
            f"color: {t.TEXT_PRI};"
            f"font-size: {u.px(t.SYNC_MDL_CARD_TITLE_SIZE)}px;"
            f"font-weight: bold;"
            f"background: transparent;"
        )
        self._desc_lbl.setStyleSheet(
            f"color: {t.SYNC_MDL_CARD_BODY_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CARD_BODY_SIZE)}px;"
            f"line-height: 1.4;"
            f"background: transparent;"
        )
        self._helper_lbl.setStyleSheet(
            f"color: {t.SYNC_MDL_CARD_HELPER_CLR};"
            f"font-size: {u.px(t.SYNC_MDL_CARD_HELPER_SIZE)}px;"
            f"background: transparent;"
        )
        self._badge.reload_theme()
        self._action.reload_theme()


class SafetyNote(QtWidgets.QFrame):
    """Warning callout with orange ! icon (icon + text only, no bordered box)."""

    def __init__(
        self,
        text: str,
        *,
        bordered: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._bordered = bordered
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QtWidgets.QHBoxLayout(self)
        row.setSpacing(12)

        self._icon = QtWidgets.QLabel("!")
        self._icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._icon, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        self._msg = QtWidgets.QLabel(text)
        self._msg.setWordWrap(True)
        row.addWidget(self._msg, 1)

        self._row = row
        self.reload_theme()

    def reload_theme(self) -> None:
        if self._bordered:
            frame_style = f"""
                QFrame {{
                    border: 1px solid {t.SYNC_MDL_SAFETY_BORDER};
                    border-radius: 10px;
                    background: {t.SYNC_MDL_SAFETY_BG};
                }}
            """
            self._row.setContentsMargins(14, 12, 14, 12)
        else:
            frame_style = "QFrame { border: none; background: transparent; }"
            self._row.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet(frame_style)

        self._icon.setFixedSize(u.px(t.SYNC_MDL_SAFETY_ICON), u.px(t.SYNC_MDL_SAFETY_ICON))
        icon_r = u.px(t.SYNC_MDL_SAFETY_ICON) // 2
        self._icon.setStyleSheet(f"""
            QLabel {{
                background: {t.STA_ACTIVE};
                color: white;
                border: none;
                border-radius: {icon_r}px;
                font-weight: 800;
                font-size: {u.px(13)}px;
            }}
        """)
        self._msg.setStyleSheet(
            f"color: {t.SYNC_MDL_SAFETY_TEXT};"
            f"font-size: {u.px(t.SYNC_MDL_SAFETY_SIZE)}px;"
            f"background: transparent;"
            f"border: none;"
            f"padding: 0;"
        )


class SyncModalShell(QtWidgets.QFrame):
    """Rounded modal container shared by sync dialogs."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("syncModalShell")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_modal_shell_stylesheet())
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def add_widget(self, widget: QtWidgets.QWidget) -> None:
        self._layout.addWidget(widget)

    def reload_theme(self) -> None:
        self.setStyleSheet(_modal_shell_stylesheet())
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None:
                continue
            if hasattr(w, "reload_theme"):
                w.reload_theme()
            else:
                _reload_sync_modal_subtree(w)
