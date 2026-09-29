"""Help page — support actions and troubleshooting."""

from __future__ import annotations

import math
import platform
from dataclasses import dataclass
from typing import List, Optional

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


@dataclass(frozen=True)
class LedLegendEntry:
    """One RP2040 NeoPixel state — swatch RGB is tuned for the Help card, not raw GPIO values."""

    label: str
    description: str
    red: int
    green: int
    blue: int
    mode: str = "solid"  # solid | breathe | flash
    cycle_ms: int = 5000
    min_brightness_pct: int = 0
    flash_duty_pct: int = 0
    swatch_red: Optional[int] = None
    swatch_green: Optional[int] = None
    swatch_blue: Optional[int] = None

    def swatch_rgb(self) -> tuple[int, int, int]:
        return (
            self.red if self.swatch_red is None else self.swatch_red,
            self.green if self.swatch_green is None else self.swatch_green,
            self.blue if self.swatch_blue is None else self.swatch_blue,
        )

    @property
    def text(self) -> str:
        return f"{self.label} — {self.description}"


class _LedLegendDot(QtWidgets.QWidget):
    """Animated LED swatch (breathing / flash / solid)."""

    _TICK_MS = 40

    def __init__(
        self,
        entry: LedLegendEntry,
        *,
        diameter: int,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self._diameter = max(12, diameter)
        self._phase_ms = 0
        self.setFixedSize(self._diameter, self._diameter)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def advance(self, delta_ms: int = _TICK_MS) -> None:
        if self.entry.mode == "solid":
            return
        self._phase_ms = (self._phase_ms + delta_ms) % max(self.entry.cycle_ms, delta_ms)
        self.update()

    def _brightness_scale(self) -> float:
        entry = self.entry
        if entry.mode == "solid":
            return 1.0
        phase = self._phase_ms % max(entry.cycle_ms, 1)
        if entry.mode == "flash":
            duty = max(1, min(100, entry.flash_duty_pct))
            on_ms = int(entry.cycle_ms * duty / 100)
            return 1.0 if phase < on_ms else 0.15
        wave = (
            1.0
            + math.sin((2.0 * math.pi * phase / entry.cycle_ms) - (math.pi / 2.0))
        ) * 50.0
        wave = max(0.0, min(100.0, wave))
        floor = max(0, min(100, entry.min_brightness_pct))
        if floor > 0:
            wave = floor + (wave * (100.0 - floor) / 100.0)
        return wave / 100.0

    def _display_color(self) -> QtGui.QColor:
        entry = self.entry
        sr, sg, sb = entry.swatch_rgb()
        scale = self._brightness_scale()
        r = min(255, max(0, int(sr * scale)))
        g = min(255, max(0, int(sg * scale)))
        b = min(255, max(0, int(sb * scale)))
        return QtGui.QColor(r, g, b)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        color = self._display_color()
        d = self._diameter
        cx = d / 2.0
        cy = d / 2.0
        radius = d / 2.0 - 1.5

        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        glow = QtGui.QRadialGradient(cx, cy, radius * 1.35)
        glow.setColorAt(0.0, QtGui.QColor(color.red(), color.green(), color.blue(), 200))
        glow.setColorAt(0.55, QtGui.QColor(color.red(), color.green(), color.blue(), 80))
        glow.setColorAt(1.0, QtGui.QColor(color.red(), color.green(), color.blue(), 0))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QtCore.QPointF(cx, cy), radius * 1.2, radius * 1.2)

        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 55), 1.0))
        p.setBrush(color)
        p.drawEllipse(QtCore.QPointF(cx, cy), radius, radius)
        p.end()


class _LedLegendRow(QtWidgets.QWidget):
    def __init__(self, entry: LedLegendEntry, *, dot_size: int) -> None:
        super().__init__()
        self.setStyleSheet("background: transparent;")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        dot = _LedLegendDot(entry, diameter=dot_size)
        row.addWidget(dot, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        text = QtWidgets.QLabel(entry.text)
        text.setWordWrap(True)
        text.setObjectName("helpBulletLabel")
        text.setStyleSheet(_bullet_style())
        row.addWidget(text, 1)
        self._dot = dot


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
        self._led_legend_dots: list[_LedLegendDot] = []
        self._legend_anim_timer = QtCore.QTimer(self)
        self._legend_anim_timer.setInterval(_LedLegendDot._TICK_MS)
        self._legend_anim_timer.timeout.connect(self._tick_led_legend)
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
        body_lay.addWidget(self._build_led_status_card())
        body_lay.addWidget(self._build_commercials_card())
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
    def led_status_legend_entries() -> List[LedLegendEntry]:
        """Onboard NeoPixel (GPIO 16) — keep in sync with firmware/pico/dfplayer_hardware.py."""
        return [
            LedLegendEntry(
                "Playing",
                "violet pulse while music is active",
                0x7A,
                0x14,
                0xFF,
                mode="breathe",
                cycle_ms=5000,
                swatch_red=172,
                swatch_green=125,
                swatch_blue=249,
            ),
            LedLegendEntry(
                "Idle",
                "dim blue when the pot is on but nothing is playing (uncommon)",
                0,
                8,
                36,
                mode="solid",
                swatch_red=72,
                swatch_green=132,
                swatch_blue=255,
            ),
            LedLegendEntry(
                "Standby",
                "dim white pulse when the volume pot is off (not an error)",
                0x14,
                0x14,
                0x14,
                mode="breathe",
                cycle_ms=4000,
                min_brightness_pct=22,
                swatch_red=210,
                swatch_green=210,
                swatch_blue=215,
            ),
            LedLegendEntry(
                "AM tuning",
                "brief green flash before a track fades in",
                0,
                0xAA,
                0,
                mode="flash",
                cycle_ms=3200,
                flash_duty_pct=14,
            ),
            LedLegendEntry(
                "Warning",
                "deep orange pulse on a recoverable playback fault",
                0x52,
                0x16,
                0x00,
                mode="breathe",
                cycle_ms=1200,
                min_brightness_pct=18,
                swatch_red=255,
                swatch_green=98,
                swatch_blue=0,
            ),
            LedLegendEntry(
                "Fatal error",
                "solid red after a firmware crash (check Tools \u2192 Debugger serial)",
                0x36,
                0,
                0,
                mode="solid",
                swatch_red=255,
                swatch_green=48,
                swatch_blue=48,
            ),
        ]

    @classmethod
    def led_status_legend_items(cls) -> list[str]:
        return [entry.text for entry in cls.led_status_legend_entries()]

    def _build_led_status_card(self) -> _HelpCard:
        card = _HelpCard()
        card.add_title("RP2040 status LED")
        card.add_body(
            "The onboard NeoPixel on the Raspberry Pi Pico shows radio state at a glance."
        )
        dot_size = u.px(22)
        self._led_legend_dots.clear()
        for entry in self.led_status_legend_entries():
            row = _LedLegendRow(entry, dot_size=dot_size)
            self._led_legend_dots.append(row._dot)
            card.add_widget(row)
        return card

    def _build_commercials_card(self) -> _HelpCard:
        card = _HelpCard()
        card.add_title("Commercials & sweepers")
        card.add_body(
            "Two firmware families (Default and Conductor), one library badge. Duplicate "
            "a library before switching so a live show card stays intact."
        )
        card.add_bullets(
            [
                "Commercials station — ads live in the Commercials station and play every few songs (Default firmware).",
                "Tagged tracks — mark individual songs as commercials in the normal rotation (Conductor firmware).",
                "Both together — station rotation plus tagged tracks; Conductor firmware only.",
                "Link a commercial to the track below it so that pair stays together in shuffle.",
                "After you change commercials settings or the library, use Install Firmware.",
                "Duplicate a library if you want to try a different setup.",
            ]
        )
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

    def _tick_led_legend(self) -> None:
        for dot in self._led_legend_dots:
            dot.advance()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if self._led_legend_dots:
            self._legend_anim_timer.start()

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self._legend_anim_timer.stop()
        super().hideEvent(event)

    def reload_theme(self) -> None:
        self.setStyleSheet(f"#helpPage {{ background: {t.C_BG}; }}")
        self._refresh_typography()
        btn_style = _action_btn_style()
        for btn in self._action_buttons:
            btn.setStyleSheet(btn_style)
        for card in self.findChildren(_HelpCard):
            card.setStyleSheet(_inner_card_style())
