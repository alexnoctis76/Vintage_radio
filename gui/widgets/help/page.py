"""Help page — support actions and troubleshooting."""

from __future__ import annotations

import platform
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar


def _inner_card_style() -> str:
    return f"""
        QFrame#helpInnerCard {{
            border-radius: {t.IF_CARD_RADIUS}px;
            border: 1px solid {t.IF_CARD_BORDER};
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_CARD_INNER_TOP}, stop:1 {t.IF_CARD_INNER_BOT}
            );
        }}
        QFrame#helpInnerCard QLabel {{
            background: transparent;
        }}
    """


def _page_title_style() -> str:
    return (
        f"color: {t.IF_DEVICE_TITLE_FG}; "
        f"font-size: {u.px(22)}px; font-weight: 800; "
        f"background: transparent;"
    )


def _section_title_style() -> str:
    return (
        f"color:{t.IF_DEVICE_TITLE_FG}; "
        f"font-size:{u.px(t.TOOLS_SECTION_TITLE_PX)}px; font-weight:800; "
        f"background: transparent;"
    )


def _body_style() -> str:
    return (
        f"color:{t.IF_DEVICE_META_FG}; "
        f"font-size:{u.px(t.SETTINGS_HINT_FONT_PX)}px; "
        f"background: transparent;"
    )


def _bullet_style() -> str:
    return (
        f"color:{t.IF_DEVICE_META_FG}; "
        f"font-size:{u.px(t.SETTINGS_HINT_FONT_PX)}px; "
        f"background: transparent;"
        f"padding-left: 4px;"
    )


def _action_btn_style() -> str:
    btn_h = u.px(t.TOOLS_ACTION_BTN_H)
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.EJECT_BTN_GRAD_TOP},
                stop:1 {t.EJECT_BTN_GRAD_BOT}
            );
            color: {t.TEXT_PRI};
            border: 2px solid {t.BORDER};
            border-radius: {t.LM_EJECT_BTN_RADIUS}px;
            padding: 0 14px;
            font-size: {u.px(t.TOOLS_ACTION_BTN_FONT)}px;
            font-weight: 700;
            min-height: {btn_h}px;
            outline: none;
        }}
        QPushButton:hover {{
            background: {t.LIGHT_BTN_HOVER};
            border: 2px solid {t.BORDER};
        }}
        QPushButton:pressed {{
            background: {t.LIGHT_BTN_PRESSED};
            border: 2px solid {t.BORDER};
        }}
        QPushButton:focus {{
            outline: none;
            border: 2px solid {t.BORDER};
        }}
    """


class _HelpCard(QtWidgets.QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("helpInnerCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_inner_card_style())
        self._lay = QtWidgets.QVBoxLayout(self)
        self._lay.setContentsMargins(14, 12, 14, 14)
        self._lay.setSpacing(10)

    def add_title(self, title: str) -> None:
        lbl = QtWidgets.QLabel(title)
        lbl.setObjectName("helpSectionTitle")
        lbl.setStyleSheet(_section_title_style())
        self._lay.addWidget(lbl)

    def add_body(self, text: str) -> None:
        lbl = QtWidgets.QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("helpBodyLabel")
        lbl.setStyleSheet(_body_style())
        self._lay.addWidget(lbl)

    def add_bullets(self, items: list[str]) -> None:
        for item in items:
            lbl = QtWidgets.QLabel(f"\u2022  {item}")
            lbl.setWordWrap(True)
            lbl.setObjectName("helpBulletLabel")
            lbl.setStyleSheet(_bullet_style())
            self._lay.addWidget(lbl)

    def add_widget(self, widget: QtWidgets.QWidget) -> None:
        self._lay.addWidget(widget)


class HelpPage(QtWidgets.QWidget):
    """Support actions and troubleshooting."""

    view_session_log_clicked = pyqtSignal()
    open_logs_folder_clicked = pyqtSignal()
    copy_log_path_clicked = pyqtSignal()
    reenable_track_warning_clicked = pyqtSignal()
    check_updates_clicked = pyqtSignal()
    about_clicked = pyqtSignal()

    def __init__(
        self,
        *,
        app_version: str = "",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._app_version = app_version
        self._action_buttons: list[QtWidgets.QPushButton] = []
        self._intro_label: Optional[QtWidgets.QLabel] = None
        self._build()

    def _build(self) -> None:
        self.setObjectName("helpPage")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#helpPage {{ background: {t.C_BG}; }}")

        l, top, r, bot = t.LM_PAGE_MARGINS
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(l, top, r, bot)
        outer.setSpacing(t.TOOLS_SECTION_GAP)

        title = QtWidgets.QLabel("Help")
        title.setObjectName("helpPageTitle")
        title.setStyleSheet(_page_title_style())
        outer.addWidget(title)

        if self._app_version:
            intro = QtWidgets.QLabel(f"Version {self._app_version}")
            intro.setObjectName("helpIntroLabel")
            intro.setStyleSheet(_body_style())
            self._intro_label = intro
            outer.addWidget(intro)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {t.C_BG}; border: none; }}")
        scroll.viewport().setStyleSheet(f"background: {t.C_BG};")

        body = QtWidgets.QWidget()
        body.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        body.setStyleSheet(f"background: {t.C_BG};")
        body_lay = QtWidgets.QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(t.TOOLS_SECTION_GAP)

        body_lay.addWidget(self._build_support_card())
        body_lay.addWidget(self._build_troubleshooting_card())
        body_lay.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(wrap_with_mockup_scrollbar(scroll, variant="track"), 1)

    def _build_support_card(self) -> _HelpCard:
        card = _HelpCard()
        card.add_title("Support & updates")
        card.add_body("Session logs and release checks.")

        btn_row = QtWidgets.QVBoxLayout()
        btn_row.setSpacing(8)
        btn_style = _action_btn_style()

        for label, tip, signal in (
            (
                "View session log",
                "Open the Session Logs panel on Tools",
                self.view_session_log_clicked,
            ),
            (
                "Open logs folder",
                "Show the folder containing all session logs",
                self.open_logs_folder_clicked,
            ),
            (
                "Copy log path to clipboard",
                "Copy the current session log file path",
                self.copy_log_path_clicked,
            ),
            (
                "Re-enable 255+ track warning",
                "Show the station track-count warning again",
                self.reenable_track_warning_clicked,
            ),
            (
                "Check for updates",
                "Look for a newer release on GitHub",
                self.check_updates_clicked,
            ),
            (
                "About Vintage Radio",
                "Version info and release notes",
                self.about_clicked,
            ),
        ):
            btn = QtWidgets.QPushButton(label)
            btn.setToolTip(tip)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(signal.emit)
            btn_row.addWidget(btn)
            self._action_buttons.append(btn)

        host = QtWidgets.QWidget()
        host.setStyleSheet("background: transparent;")
        host.setLayout(btn_row)
        card.add_widget(host)
        return card

    @staticmethod
    def _troubleshooting_items() -> list[str]:
        items = [
            "COM port busy — close other apps using the serial port, then reconnect in Tools.",
            "SD card not found — use Select on the Storage banner or enable auto-detect in Settings.",
            "Sync failed mid-copy — check free space on the SD card and that the card is not read-only.",
            "Station over 255 tracks — trim the station; re-enable the warning from Support above if needed.",
            "Session logs capture errors and debug output — attach the latest log when reporting a bug.",
        ]
        system = platform.system()
        if system == "Windows":
            items.insert(
                1,
                "Line-in silent — replug the USB line-in adapter and confirm the correct input "
                "device in Windows Sound settings (close other apps that may be using it).",
            )
        elif system == "Darwin":
            items.insert(
                1,
                "Line-in silent — replug the USB line-in adapter and confirm the correct input "
                "device in macOS Sound settings.",
            )
        else:
            items.insert(
                1,
                "Line-in silent — replug the USB line-in adapter and confirm no other app "
                "is using the capture device.",
            )
        return items

    def _build_troubleshooting_card(self) -> _HelpCard:
        card = _HelpCard()
        card.add_title("Troubleshooting")
        card.add_bullets(self._troubleshooting_items())
        return card

    def _refresh_typography(self) -> None:
        title = self.findChild(QtWidgets.QLabel, "helpPageTitle")
        if title is not None:
            title.setStyleSheet(_page_title_style())
        if self._intro_label is not None:
            self._intro_label.setStyleSheet(_body_style())
        for lbl in self.findChildren(QtWidgets.QLabel, "helpSectionTitle"):
            lbl.setStyleSheet(_section_title_style())
        for lbl in self.findChildren(QtWidgets.QLabel, "helpBodyLabel"):
            lbl.setStyleSheet(_body_style())
        for lbl in self.findChildren(QtWidgets.QLabel, "helpBulletLabel"):
            lbl.setStyleSheet(_bullet_style())

    def apply_ui_zoom(self) -> None:
        self._refresh_typography()
        self.reload_theme()

    def reload_theme(self) -> None:
        self.setStyleSheet(f"#helpPage {{ background: {t.C_BG}; }}")
        self._refresh_typography()
        btn_style = _action_btn_style()
        for btn in self._action_buttons:
            btn.setStyleSheet(btn_style)
        for card in self.findChildren(_HelpCard):
            card.setStyleSheet(_inner_card_style())
