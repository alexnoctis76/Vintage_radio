"""Settings page — user preferences organized in themed cards."""

from __future__ import annotations

import platform
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.theme_presets import THEME_CHOICES
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from gui.widgets.common.styled_combo import VintageComboBox
from gui.widgets.common.styled_checkbox import VintageCheckBox
from gui.widgets.common.styled_spin import VintageSpinBox


def _inner_card_style() -> str:
    return f"""
        QFrame#settingsInnerCard {{
            border-radius: {t.IF_CARD_RADIUS}px;
            border: 1px solid {t.IF_CARD_BORDER};
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_CARD_INNER_TOP}, stop:1 {t.IF_CARD_INNER_BOT}
            );
        }}
        QFrame#settingsInnerCard QLabel {{
            background: transparent;
        }}
        QFrame#settingsInnerCard VintageCheckBox {{
            background: transparent;
            border: none;
        }}
        QFrame#settingsInnerCard QWidget#settingsRowHost {{
            background: transparent;
        }}
        QFrame#settingsInnerCard QLabel#settingsHintLabel {{
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


def _hint_style() -> str:
    return (
        f"color:{t.IF_DEVICE_META_FG}; "
        f"font-size:{u.px(t.SETTINGS_HINT_FONT_PX)}px; "
        f"background: transparent;"
    )


def _transparent_checkbox(text: str) -> VintageCheckBox:
    return VintageCheckBox(text)


def _field_label_style() -> str:
    return (
        f"color: {t.IF_DEVICE_TITLE_FG}; "
        f"font-size: {u.px(t.SETTINGS_BODY_FONT_PX)}px; "
        f"background: transparent;"
    )


def _option_divider() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    line.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
    line.setStyleSheet(
        f"color: {t.SETTINGS_DIVIDER_COLOR}; background: {t.SETTINGS_DIVIDER_COLOR}; "
        f"max-height: 1px; border: none;"
    )
    line.setFixedHeight(1)
    return line


def _secondary_btn_style() -> str:
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
            min-height: {u.px(t.TOOLS_ACTION_BTN_H)}px;
            max-height: {u.px(t.TOOLS_ACTION_BTN_H)}px;
        }}
        QPushButton:hover {{
            background: {t.LIGHT_BTN_HOVER};
        }}
        QPushButton:pressed {{
            background: {t.LIGHT_BTN_PRESSED};
        }}
        QPushButton:disabled {{
            color: {t.IF_DEVICE_META_FG};
        }}
    """


def _make_section_header(title: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(title)
    label.setObjectName("settingsSectionTitle")
    label.setStyleSheet(_section_title_style())
    label.setAutoFillBackground(False)
    return label


def _transparent_label(text: str, *, style: str, word_wrap: bool = False) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    lbl.setWordWrap(word_wrap)
    lbl.setStyleSheet(style)
    lbl.setAutoFillBackground(False)
    if word_wrap:
        lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        lbl.setMinimumWidth(0)
    return lbl


def _hint_label(text: str) -> QtWidgets.QLabel:
    """Right-aligned hint that expands to fill space after the control."""
    lbl = _transparent_label(text, style=_hint_style(), word_wrap=True)
    lbl.setObjectName("settingsHintLabel")
    lbl.setAlignment(
        QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignTop
    )
    lbl.setMinimumWidth(t.SETTINGS_HINT_MIN_W)
    lbl.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Expanding,
        QtWidgets.QSizePolicy.Policy.Preferred,
    )
    return lbl


class _SettingsInnerCard(QtWidgets.QFrame):
    """Settings section card — controls left, responsive right-aligned hints."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("settingsInnerCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_inner_card_style())

        self._rows = QtWidgets.QVBoxLayout()
        self._rows.setContentsMargins(14, 12, 14, 12)
        self._rows.setSpacing(10)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._rows)

    def add_header(self, title: str) -> None:
        self._rows.addWidget(_make_section_header(title))

    def add_divider(self) -> None:
        self._rows.addWidget(_option_divider())

    def add_full_width(self, widget: QtWidgets.QWidget) -> None:
        self._rows.addWidget(widget)

    def add_row(
        self,
        left: QtWidgets.QLayout | QtWidgets.QWidget,
        hint_text: str,
        *,
        indent: int = 0,
    ) -> None:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(indent, 0, 0, 0)
        row.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        if isinstance(left, QtWidgets.QLayout):
            left_w = _transparent_layout_host(left)
        else:
            left_w = left
            left_w.setAutoFillBackground(False)
            left_w.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Minimum,
                QtWidgets.QSizePolicy.Policy.Fixed
                if isinstance(left, VintageCheckBox)
                else QtWidgets.QSizePolicy.Policy.Preferred,
            )
            if isinstance(left, VintageCheckBox):
                left_w.setMinimumHeight(left.sizeHint().height())

        row.addWidget(left_w, 0)
        row.addSpacing(t.SETTINGS_HINT_GAP)
        row.addWidget(_hint_label(hint_text), 1)

        self._rows.addLayout(row)


def _transparent_layout_host(layout: QtWidgets.QLayout) -> QtWidgets.QWidget:
    """Wrap a layout without introducing a visible panel behind its widgets."""
    host = QtWidgets.QWidget()
    host.setObjectName("settingsRowHost")
    host.setLayout(layout)
    host.setAutoFillBackground(False)
    host.setStyleSheet("background: transparent;")
    host.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Minimum,
        QtWidgets.QSizePolicy.Policy.Preferred,
    )
    return host


def _field_row(
    label_text: str,
    control: QtWidgets.QWidget,
    *,
    indent: int = 0,
) -> QtWidgets.QHBoxLayout:
    """Label and control grouped on the left with a tight gap."""
    inner = QtWidgets.QHBoxLayout()
    inner.setSpacing(t.SETTINGS_FIELD_GAP)
    inner.setContentsMargins(indent, 0, 0, 0)
    inner.setAlignment(
        QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
    )
    label = _transparent_label(label_text, style=_field_label_style())
    label.setObjectName("settingsFieldLabel")
    label.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Maximum,
        QtWidgets.QSizePolicy.Policy.Preferred,
    )
    control.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Maximum,
        QtWidgets.QSizePolicy.Policy.Fixed,
    )
    inner.addWidget(label)
    inner.addWidget(control)
    return inner


def _action_row(
    control: QtWidgets.QWidget,
    *,
    indent: int = 0,
) -> QtWidgets.QHBoxLayout:
    """Left-aligned action button row (no trailing stretch)."""
    row = QtWidgets.QHBoxLayout()
    row.setContentsMargins(indent, 0, 0, 0)
    row.setAlignment(
        QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
    )
    control.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Maximum,
        QtWidgets.QSizePolicy.Policy.Fixed,
    )
    row.addWidget(control)
    return row


class SettingsPage(QtWidgets.QWidget):
    auto_eject_changed = pyqtSignal(int)
    conversion_profile_changed = pyqtSignal(int)
    retain_conversion_cache_changed = pyqtSignal(int)
    clear_conversion_cache_clicked = pyqtSignal()
    experimental_fast_sync_changed = pyqtSignal(int)
    sd_image_reuse_when_unchanged_changed = pyqtSignal(int)
    auto_backup_changed = pyqtSignal(int)
    backup_retention_changed = pyqtSignal(int)
    sd_auto_detect_changed = pyqtSignal(int)
    ui_zoom_changed = pyqtSignal(int)
    ui_theme_changed = pyqtSignal(int)

    def __init__(
        self,
        *,
        auto_eject_checked: bool = False,
        conversion_profile: str = "dfplayer_safe",
        retain_conversion_cache: bool = True,
        experimental_fast_sync: bool = False,
        sd_image_reuse_when_unchanged: bool = True,
        auto_backup: bool = False,
        backup_retention: int = 10,
        sd_auto_detect: bool = True,
        ui_zoom_level: int = 100,
        ui_theme: str = "vintage",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._auto_eject_checked = auto_eject_checked
        self._conversion_profile = conversion_profile
        self._retain_conversion_cache = retain_conversion_cache
        self._experimental_fast_sync = experimental_fast_sync
        self._sd_image_reuse_when_unchanged = sd_image_reuse_when_unchanged
        self._auto_backup = auto_backup
        self._backup_retention = backup_retention
        self._sd_auto_detect = sd_auto_detect
        self._ui_zoom_level = ui_zoom_level
        self._ui_theme = ui_theme
        self._build()

    @property
    def auto_eject_checkbox(self) -> QtWidgets.QCheckBox:
        return self._auto_eject_cb

    @property
    def conversion_profile_combo(self) -> VintageComboBox:
        return self._conv_combo

    @property
    def retain_conversion_cache_checkbox(self) -> QtWidgets.QCheckBox:
        return self._retain_cache_cb

    @property
    def clear_conversion_cache_button(self) -> QtWidgets.QPushButton:
        return self._clear_cache_btn

    @property
    def experimental_fast_sync_checkbox(self) -> QtWidgets.QCheckBox:
        return self._experimental_cb

    @property
    def sd_image_reuse_when_unchanged_checkbox(self) -> QtWidgets.QCheckBox:
        return self._sd_image_reuse_cb

    @property
    def auto_backup_checkbox(self) -> QtWidgets.QCheckBox:
        return self._auto_backup_cb

    @property
    def backup_retention_spin(self) -> QtWidgets.QSpinBox:
        return self._retention_spin

    @property
    def sd_auto_detect_checkbox(self) -> QtWidgets.QCheckBox:
        return self._sd_auto_detect_cb

    @property
    def ui_zoom_spin(self) -> QtWidgets.QSpinBox:
        return self._zoom_spin

    @property
    def ui_theme_combo(self) -> VintageComboBox:
        return self._theme_combo

    def _build(self) -> None:
        self.setObjectName("settingsPage")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#settingsPage {{ background: {t.C_BG}; }}")

        l, top, r, bot = t.LM_PAGE_MARGINS
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(l, top, r, bot)
        outer.setSpacing(t.TOOLS_SECTION_GAP)

        title = QtWidgets.QLabel("Settings")
        title.setObjectName("settingsPageTitle")
        title.setStyleSheet(_page_title_style())
        outer.addWidget(title)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {t.C_BG}; border: none; }}"
        )
        scroll.viewport().setStyleSheet(f"background: {t.C_BG};")

        body = QtWidgets.QWidget()
        body.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        body.setStyleSheet(f"background: {t.C_BG};")
        body_lay = QtWidgets.QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(t.TOOLS_SECTION_GAP)

        body_lay.addWidget(self._build_sync_card())
        body_lay.addWidget(self._build_library_card())
        body_lay.addWidget(self._build_sd_card())
        body_lay.addWidget(self._build_appearance_card())
        body_lay.addStretch(1)

        scroll.setWidget(body)
        scroll_wrap = wrap_with_mockup_scrollbar(scroll, variant="track")
        outer.addWidget(scroll_wrap, 1)

    def _build_sync_card(self) -> _SettingsInnerCard:
        card = _SettingsInnerCard()
        card.add_header("Sync & SD Card")

        self._auto_eject_cb = _transparent_checkbox(
            "Automatically safely remove SD card after syncing"
        )
        self._auto_eject_cb.setChecked(self._auto_eject_checked)
        self._auto_eject_cb.stateChanged.connect(self.auto_eject_changed)
        card.add_full_width(self._auto_eject_cb)

        card.add_divider()

        self._conv_combo = VintageComboBox(
            min_width=220,
            max_width=420,
            fixed_height=u.px(t.TOOLS_ACTION_BTN_H),
        )
        self._conv_combo.addItem("DFPlayer-safe (default)", "dfplayer_safe")
        self._conv_combo.addItem("Higher quality (advanced)", "high_quality")
        self._conv_combo.setCurrentIndex(
            1 if self._conversion_profile == "high_quality" else 0
        )
        self._conv_combo.currentIndexChanged.connect(self.conversion_profile_changed)
        card.add_row(
            _field_row("Conversion profile:", self._conv_combo),
            "Controls how audio is converted when copying tracks to the SD card. "
            "MP3 files that do not match the selected profile are re-encoded on sync.",
        )

        card.add_divider()

        self._retain_cache_cb = _transparent_checkbox(
            "Retain local converted MP3 cache between syncs"
        )
        self._retain_cache_cb.setChecked(self._retain_conversion_cache)
        self._retain_cache_cb.setToolTip(
            "When enabled, converted MP3s are saved on this PC so future syncs "
            "can skip re-encoding and run faster."
        )
        self._retain_cache_cb.stateChanged.connect(self.retain_conversion_cache_changed)
        card.add_row(
            self._retain_cache_cb,
            "When enabled, converted MP3s are saved on this PC so future syncs "
            "can skip re-encoding and run faster.",
        )

        self._clear_cache_btn = QtWidgets.QPushButton("Clear conversion cache…")
        self._clear_cache_btn.setStyleSheet(_secondary_btn_style())
        self._clear_cache_btn.setCursor(
            QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        )
        self._clear_cache_btn.clicked.connect(self.clear_conversion_cache_clicked.emit)
        card.add_row(
            _action_row(self._clear_cache_btn, indent=t.SETTINGS_ACTION_INDENT),
            "Clearing the cache removes stored conversions for this library. "
            "The next sync will re-encode tracks from your source files.",
        )

        card.add_divider()

        self._experimental_cb = _transparent_checkbox(
            "Enable Fast Full Sync (experimental)"
        )
        self._experimental_cb.setChecked(self._experimental_fast_sync)
        self._experimental_cb.setToolTip(
            "When enabled, the Sync to SD Card dialog offers Quick Replace All Music — "
            "copies your whole library to the card in one step."
        )
        self._experimental_cb.stateChanged.connect(self.experimental_fast_sync_changed)
        card.add_row(
            self._experimental_cb,
            "Experimental options appear on the sync dialog when this is checked.",
        )

        self._sd_image_reuse_cb = _transparent_checkbox(
            "Reuse saved disk image when the library has not changed"
        )
        self._sd_image_reuse_cb.setChecked(self._sd_image_reuse_when_unchanged)
        self._sd_image_reuse_cb.setToolTip(
            "When your music library is unchanged since the last install, "
            "Quick SD card install skips rebuilding and writes the saved image."
        )
        self._sd_image_reuse_cb.stateChanged.connect(
            self.sd_image_reuse_when_unchanged_changed
        )
        card.add_row(
            self._sd_image_reuse_cb,
            "Turn off to always rebuild from scratch, even when nothing changed.",
        )

        return card

    def _build_library_card(self) -> _SettingsInnerCard:
        card = _SettingsInnerCard()
        card.add_header("Library & Backups")

        self._auto_backup_cb = _transparent_checkbox("Enable automatic library backups")
        self._auto_backup_cb.setChecked(self._auto_backup)
        self._auto_backup_cb.stateChanged.connect(self.auto_backup_changed)
        card.add_full_width(self._auto_backup_cb)

        card.add_divider()

        self._retention_spin = VintageSpinBox()
        self._retention_spin.setRange(1, 100)
        self._retention_spin.setValue(max(1, self._backup_retention))
        self._retention_spin.valueChanged.connect(self.backup_retention_changed)
        card.add_row(
            _field_row("Backup retention (count):", self._retention_spin),
            "Older automatic backups are removed when the count exceeds this limit.",
        )

        return card

    def _build_sd_card(self) -> _SettingsInnerCard:
        card = _SettingsInnerCard()
        card.add_header("SD Card Detection")

        self._sd_auto_detect_cb = _transparent_checkbox("Auto-detect SD card root")
        self._sd_auto_detect_cb.setChecked(self._sd_auto_detect)
        self._sd_auto_detect_cb.stateChanged.connect(self.sd_auto_detect_changed)
        sd_hint = (
            "When enabled, the app tries to find a removable drive at startup. "
            "You can always pick the folder manually on the Load Music page."
        )
        if platform.system() == "Windows":
            sd_hint += " Removable-drive detection works best on Windows."
        card.add_row(
            self._sd_auto_detect_cb,
            sd_hint,
        )

        return card

    def _build_appearance_card(self) -> _SettingsInnerCard:
        card = _SettingsInnerCard()
        card.add_header("Appearance")

        self._zoom_spin = VintageSpinBox()
        self._zoom_spin.setRange(80, 200)
        self._zoom_spin.setSingleStep(10)
        self._zoom_spin.setSuffix(" %")
        self._zoom_spin.setValue(max(80, min(200, self._ui_zoom_level)))
        self._zoom_spin.valueChanged.connect(self.ui_zoom_changed)
        card.add_row(
            _field_row("Interface zoom:", self._zoom_spin),
            "Adjusts text and control sizes across the app. "
            "You can also use the zoom controls in the status bar.",
        )

        card.add_divider()

        self._theme_combo = VintageComboBox(
            min_width=220,
            max_width=420,
            fixed_height=u.px(t.TOOLS_ACTION_BTN_H),
        )
        for theme_id, label in THEME_CHOICES:
            self._theme_combo.addItem(label, theme_id)
        idx = max(0, self._theme_combo.findData(self._ui_theme))
        self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.currentIndexChanged.connect(self.ui_theme_changed)
        card.add_row(
            _field_row("Colour theme:", self._theme_combo),
            "Vintage is the default warm palette. High contrast and colourblind "
            "friendly options adjust accents and text for readability.",
        )

        return card

    def _refresh_typography(self) -> None:
        title = self.findChild(QtWidgets.QLabel, "settingsPageTitle")
        if title is not None:
            title.setStyleSheet(_page_title_style())
        for lbl in self.findChildren(QtWidgets.QLabel, "settingsSectionTitle"):
            lbl.setStyleSheet(_section_title_style())
        for lbl in self.findChildren(QtWidgets.QLabel, "settingsFieldLabel"):
            lbl.setStyleSheet(_field_label_style())
        for lbl in self.findChildren(QtWidgets.QLabel, "settingsHintLabel"):
            lbl.setStyleSheet(_hint_style())

    def apply_ui_zoom(self) -> None:
        """Re-apply scaled typography and control metrics after zoom changed."""
        self._refresh_typography()
        self.reload_theme()

    def reload_theme(self) -> None:
        self.setStyleSheet(f"#settingsPage {{ background: {t.C_BG}; }}")
        self._refresh_typography()
        for card in self.findChildren(_SettingsInnerCard):
            card.setStyleSheet(_inner_card_style())
        self._auto_eject_cb.apply_theme()
        self._retain_cache_cb.apply_theme()
        self._clear_cache_btn.setStyleSheet(_secondary_btn_style())
        self._experimental_cb.apply_theme()
        self._sd_image_reuse_cb.apply_theme()
        self._auto_backup_cb.apply_theme()
        self._sd_auto_detect_cb.apply_theme()
        self._retention_spin.apply_theme()
        self._zoom_spin.apply_theme()
        self._conv_combo.apply_theme()
        if hasattr(self, "_theme_combo"):
            self._theme_combo.setFixedHeight(u.px(t.TOOLS_ACTION_BTN_H))
            self._theme_combo.apply_theme()
