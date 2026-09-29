"""Right pane matching gui/scratch.html .firmware-details-panel — no outer scrollbar."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.updater import GITHUB_REPO_SLUG
from gui.widgets.install_firmware.common.meta_pill import AuthorMetaPill, EditableMetaPill
from gui.widgets.install_firmware.common.notes_preview_box import NotesPreviewBox
from gui.widgets.install_firmware.common.pill_label import PillLabel

_DEFAULT_FIRMWARE_AUTHOR = GITHUB_REPO_SLUG.split("/", 1)[0]


def _svg_resource(filename: str) -> Path:
    from gui.resource_paths import gui_dir
    return gui_dir() / "resources" / filename


def _inner_card_style() -> str:
    return f"""
        QFrame#innerCard {{
            border-radius: {t.IF_CARD_RADIUS}px;
            border: 1px solid {t.IF_CARD_BORDER};
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_CARD_INNER_TOP}, stop:1 {t.IF_CARD_INNER_BOT}
            );
        }}
    """


def _small_btn_style() -> str:
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.OUTLINE_BTN_GRAD_TOP}, stop:1 {t.OUTLINE_BTN_GRAD_BOT}
            );
            color: {t.TEXT_PRI};
            border: 1px solid {t.BORDER};
            border-radius: 8px;
            min-height: {t.IF_SMALL_BTN_H}px;
            padding: 0 18px;
            font-size: {u.px(t.IF_SMALL_BTN_FONT)}px;
            font-weight: {u.qss_weight(900)};
        }}
        QPushButton:hover {{ background: {t.LIGHT_BTN_HOVER}; }}
    """


def _config_action_btn_style() -> str:
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.OUTLINE_BTN_GRAD_TOP}, stop:1 {t.OUTLINE_BTN_GRAD_BOT}
            );
            color: {t.TEXT_PRI};
            border: 1px solid {t.BORDER};
            border-radius: 6px;
            padding: 0 8px;
            font-size: {u.px(11)}px;
            font-weight: {u.qss_weight(800)};
        }}
        QPushButton:hover {{ background: {t.LIGHT_BTN_HOVER}; }}
    """


def _remove_source_btn_style() -> str:
    return f"""
        QPushButton {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #fff0ea, stop:1 #f0d4c8);
            color: #5c2a18;
            border: 1px solid #b86a52;
            border-radius: 8px;
            padding: 0 14px;
            font-size: {u.px(t.IF_SMALL_BTN_FONT)}px;
            font-weight: {u.qss_weight(800)};
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #fff5f0, stop:1 #f5ddd2);
        }}
    """


def _config_field_height() -> int:
    return u.px(t.IF_SMALL_BTN_H)


def _config_field_style() -> str:
    return f"""
        QLineEdit#firmwareConfigField {{
            background: {t.TOOLS_INPUT_BG};
            color: {t.TOOLS_INPUT_FG};
            border: 1px solid {t.TOOLS_INPUT_BORDER};
            border-radius: {t.TOOLS_PATH_FIELD_RADIUS}px;
            padding: 0 10px;
            font-size: {u.px(t.IF_SW_DESC_PX)}px;
        }}
        QLineEdit#firmwareConfigField:read-only {{
            color: {t.TEXT_SEC};
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_CARD_INNER_TOP}, stop:1 {t.IF_CARD_INNER_BOT}
            );
        }}
    """


def _config_caption_style() -> str:
    return (
        f"color:{t.TEXT_SEC}; font-size:{u.px(t.IF_SW_DESC_PX)}px; "
        f"font-weight:{u.qss_weight(700)};"
    )


def _install_btn_style() -> str:
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_INSTALL_BTN_TOP}, stop:0.58 {t.IF_INSTALL_BTN_MID},
                stop:1 {t.IF_INSTALL_BTN_BOT}
            );
            color: {t.IF_INSTALL_BTN_FG};
            border: 2px solid {t.IF_INSTALL_BTN_BORDER};
            border-radius: 7px;
            font-size: {u.px(t.IF_INSTALL_BTN_FONT)}px;
            font-weight: {u.qss_weight(900)};
        }}
        QPushButton:hover {{
            background: {t.IF_INSTALL_BTN_MID};
            color: {t.IF_INSTALL_BTN_FG};
        }}
        QPushButton:disabled {{
            color: {t.IF_INSTALL_BTN_DISABLED_FG};
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #c9864a, stop:1 #9a5a28
            );
        }}
    """


def _apply_install_btn_theme(btn: QtWidgets.QPushButton) -> None:
    btn.setStyleSheet(_install_btn_style())
    pal = btn.palette()
    fg = QtGui.QColor(t.IF_INSTALL_BTN_FG)
    pal.setColor(QtGui.QPalette.ColorGroup.All, QtGui.QPalette.ColorRole.ButtonText, fg)
    pal.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.ButtonText,
        QtGui.QColor(t.IF_INSTALL_BTN_DISABLED_FG),
    )
    btn.setPalette(pal)


def _make_install_icon(size: int = 26) -> QtGui.QIcon:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QtSvg.QSvgRenderer(str(_svg_resource("Install Firmware.svg")))
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(p, QtCore.QRectF(pix.rect()))
    p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(pix.rect(), QtGui.QColor("#ffffff"))
    p.end()
    return QtGui.QIcon(pix)


def _format_notes_preview(text: str) -> str:
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    out: list[str] = []
    for ln in lines:
        out.append(ln if ln.startswith("•") or ln.startswith("-") else f"• {ln}")
    return "\n".join(out)


class _NotesCard(QtWidgets.QFrame):
    view_clicked = pyqtSignal()
    edit_clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        *,
        editable_pill: bool,
        action_label: str,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._editable_pill = editable_pill
        self.setObjectName("innerCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_inner_card_style())
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        title_row = QtWidgets.QHBoxLayout()
        hdr = QtWidgets.QLabel(title)
        hdr.setObjectName("notesCardTitle")
        self._title_label = hdr
        hdr.setStyleSheet(
            f"color:{t.TEXT_PRI}; font-size:{u.px(t.IF_NOTES_TITLE_PX)}px; "
            f"font-weight:{u.qss_weight(800)};"
        )
        title_row.addWidget(hdr)
        title_row.addStretch(1)
        lay.addLayout(title_row)

        self._preview = NotesPreviewBox()
        self._preview.setMinimumHeight(t.IF_NOTES_PREVIEW_MIN_H)
        lay.addWidget(self._preview, 1)

        self._action_btn = QtWidgets.QPushButton(action_label)
        self._action_btn.setFixedHeight(t.IF_SMALL_BTN_H)
        self._action_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._action_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._action_btn.setStyleSheet(_small_btn_style())
        self._action_btn.clicked.connect(
            self.edit_clicked.emit if editable_pill else self.view_clicked.emit
        )
        lay.addWidget(self._action_btn)

    def set_preview(self, text: str, *, placeholder: str = "") -> None:
        body = _format_notes_preview(text)
        self._preview.set_plain_text(body if body else (placeholder or "No notes yet."))

    def reload_theme(self) -> None:
        self.setStyleSheet(_inner_card_style())
        self._title_label.setStyleSheet(
            f"color:{t.TEXT_PRI}; font-size:{u.px(t.IF_NOTES_TITLE_PX)}px; "
            f"font-weight:{u.qss_weight(800)};"
        )
        self._preview.apply_theme()
        self._action_btn.setStyleSheet(_small_btn_style())


class FirmwareDetailPanel(QtWidgets.QWidget):
    view_firmware_notes_clicked = pyqtSignal()
    edit_user_notes_clicked = pyqtSignal()
    remove_clicked = pyqtSignal()
    add_custom_clicked = pyqtSignal()
    install_clicked = pyqtSignal()
    config_remote_changed = pyqtSignal(str)
    attach_config_file_clicked = pyqtSignal()
    attach_config_folder_clicked = pyqtSignal()
    clear_config_clicked = pyqtSignal()
    custom_meta_changed = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._mode = "official"
        self._has_selection = False
        self._meta_edit_blocked = False
        self._build()

    @property
    def install_btn(self) -> QtWidgets.QPushButton:
        return self._install_btn

    @property
    def status_label(self) -> QtWidgets.QLabel:
        return self._status

    def set_status(self, text: str) -> None:
        self._status.setText(text)
        ready = "ready to install" in text.lower()
        self._status_icon.setVisible(ready)

    def set_install_progress(self, percent: int, *, visible: bool = False) -> None:
        pct = max(0, min(100, int(percent)))
        self._progress.setVisible(visible)
        track_w = max(0, t.IF_PROGRESS_W - 4)
        self._progress_fill.setFixedWidth(int(track_w * pct / 100))

    def set_mode(self, mode: str) -> None:
        self._mode = "custom" if mode == "custom" else "official"

    def set_entry(
        self,
        entry: Optional[Dict[str, Any]],
        *,
        user_notes: str = "",
        custom_empty: bool = False,
    ) -> None:
        self._has_selection = entry is not None and not custom_empty
        self._footer.setVisible(not custom_empty and entry is not None)

        if custom_empty or (self._mode == "custom" and entry is None):
            self._show_empty_custom()
            return

        self._empty_stack.setVisible(False)
        self._body.setVisible(True)
        self._footer.setVisible(True)

        if not entry:
            self._body.setVisible(False)
            self._footer.setVisible(False)
            return

        custom = bool(entry.get("custom"))
        self._sw_title.setText(str(entry.get("name") or "Firmware"))
        badge = str(entry.get("badge") or ("Custom" if custom else "Official"))
        self._sw_badge.setText(badge)
        badge_variant = (
            "badge_soft" if (custom or badge != "Official") else "badge_official"
        )
        self._sw_badge.apply_variant(badge_variant)  # type: ignore[arg-type]
        self._sw_desc.setText(str(entry.get("description") or ""))
        self._sync_sw_desc_height()
        self._meta_edit_blocked = True
        version = str(entry.get("version") or ("Custom" if custom else "v1.1"))
        device = str(entry.get("device") or ("RP2040" if custom else "DFPlayer + RP2040"))
        author = str(entry.get("author") or ("You" if custom else _DEFAULT_FIRMWARE_AUTHOR))
        self._meta_version.set_value(version)
        self._meta_device.set_value(device)
        self._meta_version.set_editable(custom)
        self._meta_device.set_editable(custom)
        if custom:
            self._meta_author_link.setVisible(False)
            self._meta_author_edit.setVisible(True)
            self._meta_author_edit.set_value(author)
            self._meta_author_edit.set_editable(True)
        else:
            self._meta_author_edit.setVisible(False)
            self._meta_author_link.setVisible(True)
            self._meta_author_link.set_author(author, str(entry.get("repoUrl") or ""))
        self._meta_edit_blocked = False

        self._fw_notes_card.setVisible(not custom)
        if not custom:
            self._fw_notes_card.set_preview(
                str(entry.get("notes") or ""),
                placeholder="No firmware notes available.",
            )

        notes_text = user_notes if not custom else str(entry.get("notes") or "")
        self._user_notes_card.set_preview(
            notes_text,
            placeholder="Write your notes about this firmware…",
        )
        self._user_notes_card.setVisible(True)
        self._remove_btn.setVisible(custom)
        self._sync_detail_middle_layout(entry)
        self._apply_config_attach_ui(entry)

    def set_install_enabled(self, enabled: bool) -> None:
        self._install_btn.setEnabled(enabled)

    def _entry_supports_config(self, entry: Dict[str, Any]) -> bool:
        from gui.uf2_install_profile import firmware_entry_supports_config

        return firmware_entry_supports_config(entry)

    def _sync_detail_middle_layout(self, entry: Dict[str, Any]) -> None:
        """Official: Firmware Notes | Your Notes. Custom: Your Notes | Attached config."""
        custom = bool(entry.get("custom"))
        show_config = custom and self._entry_supports_config(entry)
        self._middle.setVisible(True)
        self._middle.setMinimumHeight(t.IF_DETAIL_MIDDLE_MIN)
        self._middle.setMaximumHeight(16777215)
        self._fw_notes_card.setVisible(not custom)
        self._user_notes_card.setVisible(True)
        self._config_card.setVisible(show_config)

    def _apply_config_attach_ui(self, entry: Dict[str, Any]) -> None:
        if not self._entry_supports_config(entry):
            return
        cfg_path = str(entry.get("config_path") or "").strip()
        has_config = bool(cfg_path)
        self._config_clear_btn.setVisible(has_config)
        self._config_attach_file_btn.setText(
            "Change…" if has_config and Path(cfg_path).is_file() else "File…"
        )
        self._config_attach_file_btn.setToolTip(
            "Change attached config file" if has_config and Path(cfg_path).is_file()
            else "Attach a config file"
        )
        self._config_attach_folder_btn.setToolTip("Attach a config folder")
        self._config_clear_btn.setToolTip("Clear attached config")
        if not cfg_path:
            self._config_hint.setVisible(True)
            self._config_hint.setText(
                "Optional config copied to the Pico after flash or install."
            )
            self._config_local_block.setVisible(False)
            self._config_remote_block.setVisible(False)
            return
        local = Path(cfg_path)
        self._config_hint.setVisible(True)
        if local.is_dir():
            self._config_hint.setText(
                "Folder bundle — files copy using relative paths "
                "(or pico_inject_manifest.json when present)."
            )
            self._config_local_block.setVisible(True)
            self._config_local_caption.setText("Local folder")
            self._config_local_path.setText(str(local))
            self._config_remote_block.setVisible(False)
            return
        remote = str(entry.get("config_remote") or local.name).strip() or local.name
        self._config_hint.setVisible(False)
        self._config_local_block.setVisible(True)
        self._config_local_caption.setText("Local file")
        self._config_local_path.setText(str(local))
        self._config_remote_block.setVisible(True)
        self._config_remote_edit.blockSignals(True)
        self._config_remote_edit.setText(remote)
        self._config_remote_edit.blockSignals(False)

    def _show_empty_custom(self) -> None:
        self._body.setVisible(False)
        self._footer.setVisible(False)
        self._empty_stack.setVisible(True)

    def _build(self) -> None:
        self.setObjectName("firmwareDetailPane")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._apply_pane_style()

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(t.IF_DETAIL_CARD_GAP)

        self._body = QtWidgets.QWidget()
        self._body.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        body_lay = QtWidgets.QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(t.IF_DETAIL_CARD_GAP)
        body_lay.addWidget(self._build_software_card())

        self._middle = QtWidgets.QWidget()
        self._middle.setMinimumHeight(t.IF_DETAIL_MIDDLE_MIN)
        self._middle.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        middle_lay = QtWidgets.QHBoxLayout(self._middle)
        middle_lay.setContentsMargins(0, 0, 0, 0)
        middle_lay.setSpacing(t.IF_DETAIL_CARD_GAP)

        self._fw_notes_card = _NotesCard(
            "Firmware Notes", editable_pill=False, action_label="View Details"
        )
        self._fw_notes_card.view_clicked.connect(self.view_firmware_notes_clicked.emit)
        middle_lay.addWidget(self._fw_notes_card, 1)

        self._user_notes_card = _NotesCard(
            "Your Notes", editable_pill=True, action_label="Edit Notes"
        )
        self._user_notes_card.edit_clicked.connect(self.edit_user_notes_clicked.emit)
        middle_lay.addWidget(self._user_notes_card, 1)

        self._config_card = self._build_config_card()
        middle_lay.addWidget(self._config_card, 1)
        body_lay.addWidget(self._middle, 1)

        root.addWidget(self._body, 1)

        self._empty_stack = self._build_empty_custom()
        root.addWidget(self._empty_stack, 1)

        self._footer = self._build_footer()
        root.addWidget(self._footer, 0)

    def _build_software_card(self) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("innerCard")
        card.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_inner_card_style())
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(4)

        title_row = QtWidgets.QHBoxLayout()
        self._sw_title = QtWidgets.QLabel("Vintage Radio Default")
        self._apply_sw_title_style()
        title_row.addWidget(self._sw_title, 1)
        self._sw_badge = PillLabel("Official", variant="badge_official")
        title_row.addWidget(self._sw_badge, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        lay.addLayout(title_row)

        self._sw_desc = QtWidgets.QLabel("")
        self._sw_desc.setWordWrap(True)
        self._sw_desc.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self._apply_sw_desc_style()
        lay.addWidget(self._sw_desc)

        meta_row = QtWidgets.QHBoxLayout()
        meta_row.setSpacing(8)
        meta_row.addStretch(1)
        self._meta_version = EditableMetaPill("Version", icon="tag")
        self._meta_device = EditableMetaPill(
            "Device",
            icon="chip",
            width=t.IF_META_DEVICE_PILL_W,
        )
        self._meta_author_link = AuthorMetaPill()
        self._meta_author_edit = EditableMetaPill(
            "Author",
            icon="github",
            width=t.IF_META_AUTHOR_PILL_W,
        )
        self._meta_version.value_changed.connect(
            lambda v: self._emit_custom_meta("version", v)
        )
        self._meta_device.value_changed.connect(
            lambda v: self._emit_custom_meta("device", v)
        )
        self._meta_author_edit.value_changed.connect(
            lambda v: self._emit_custom_meta("author", v)
        )
        meta_row.addWidget(self._meta_version)
        meta_row.addWidget(self._meta_device)
        meta_row.addWidget(self._meta_author_link)
        meta_row.addWidget(self._meta_author_edit)
        self._meta_author_edit.setVisible(False)
        lay.addLayout(meta_row)
        return card

    def _emit_custom_meta(self, field: str, value: str) -> None:
        if self._meta_edit_blocked:
            return
        self.custom_meta_changed.emit(field, str(value or "").strip())

    def _build_config_card(self) -> QtWidgets.QFrame:
        """Right column for custom firmware — mirrors _NotesCard layout."""
        card = QtWidgets.QFrame()
        card.setObjectName("innerCard")
        card.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_inner_card_style())
        card.setVisible(False)
        card.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        title_row = QtWidgets.QHBoxLayout()
        self._config_title = QtWidgets.QLabel("Attached config")
        self._config_title.setStyleSheet(
            f"color:{t.TEXT_PRI}; font-size:{u.px(t.IF_NOTES_TITLE_PX)}px; "
            f"font-weight:{u.qss_weight(800)};"
        )
        title_row.addWidget(self._config_title)
        title_row.addStretch(1)
        lay.addLayout(title_row)

        self._config_body = QtWidgets.QWidget()
        self._config_body.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        body_lay = QtWidgets.QVBoxLayout(self._config_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(8)

        self._config_hint = QtWidgets.QLabel("")
        self._config_hint.setWordWrap(True)
        self._config_hint.setStyleSheet(
            f"color:{t.TEXT_SEC}; font-size:{u.px(t.IF_SW_DESC_PX)}px;"
        )
        body_lay.addWidget(self._config_hint)

        field_h = _config_field_height()
        self._config_local_block = QtWidgets.QWidget()
        local_lay = QtWidgets.QVBoxLayout(self._config_local_block)
        local_lay.setContentsMargins(0, 0, 0, 0)
        local_lay.setSpacing(4)
        self._config_local_caption = QtWidgets.QLabel("Local file")
        self._config_local_caption.setStyleSheet(_config_caption_style())
        local_lay.addWidget(self._config_local_caption)
        self._config_local_path = QtWidgets.QLineEdit()
        self._config_local_path.setObjectName("firmwareConfigField")
        self._config_local_path.setReadOnly(True)
        self._config_local_path.setFixedHeight(field_h)
        self._config_local_path.setStyleSheet(_config_field_style())
        local_lay.addWidget(self._config_local_path)
        self._config_local_block.setVisible(False)
        body_lay.addWidget(self._config_local_block)

        self._config_remote_block = QtWidgets.QWidget()
        remote_lay = QtWidgets.QVBoxLayout(self._config_remote_block)
        remote_lay.setContentsMargins(0, 0, 0, 0)
        remote_lay.setSpacing(4)
        self._config_remote_caption = QtWidgets.QLabel("Pico destination")
        self._config_remote_caption.setStyleSheet(_config_caption_style())
        remote_lay.addWidget(self._config_remote_caption)
        self._config_remote_edit = QtWidgets.QLineEdit()
        self._config_remote_edit.setObjectName("firmwareConfigField")
        self._config_remote_edit.setPlaceholderText("config.py")
        self._config_remote_edit.setFixedHeight(field_h)
        self._config_remote_edit.setStyleSheet(_config_field_style())
        self._config_remote_edit.editingFinished.connect(self._emit_config_remote_changed)
        remote_lay.addWidget(self._config_remote_edit)
        self._config_remote_block.setVisible(False)
        body_lay.addWidget(self._config_remote_block)
        body_lay.addStretch(1)
        lay.addWidget(self._config_body, 1)

        config_btn_h = u.px(26)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(6)
        self._config_attach_file_btn = QtWidgets.QPushButton("File…")
        self._config_attach_file_btn.setCursor(
            QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        )
        self._config_attach_file_btn.setStyleSheet(_config_action_btn_style())
        self._config_attach_file_btn.setFixedHeight(config_btn_h)
        self._config_attach_file_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._config_attach_file_btn.setToolTip("Attach a config file")
        self._config_attach_file_btn.clicked.connect(
            self.attach_config_file_clicked.emit
        )
        btn_row.addWidget(self._config_attach_file_btn, 1)

        self._config_attach_folder_btn = QtWidgets.QPushButton("Folder…")
        self._config_attach_folder_btn.setCursor(
            QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        )
        self._config_attach_folder_btn.setStyleSheet(_config_action_btn_style())
        self._config_attach_folder_btn.setFixedHeight(config_btn_h)
        self._config_attach_folder_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._config_attach_folder_btn.setToolTip("Attach a config folder")
        self._config_attach_folder_btn.clicked.connect(
            self.attach_config_folder_clicked.emit
        )
        btn_row.addWidget(self._config_attach_folder_btn, 1)

        self._config_clear_btn = QtWidgets.QPushButton("Clear")
        self._config_clear_btn.setVisible(False)
        self._config_clear_btn.setCursor(
            QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        )
        self._config_clear_btn.setStyleSheet(_config_action_btn_style())
        self._config_clear_btn.setFixedHeight(config_btn_h)
        self._config_clear_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._config_clear_btn.setToolTip("Clear attached config")
        self._config_clear_btn.clicked.connect(self.clear_config_clicked.emit)
        btn_row.addWidget(self._config_clear_btn, 1)
        lay.addLayout(btn_row)
        return card

    def _emit_config_remote_changed(self) -> None:
        text = self._config_remote_edit.text().strip().replace("\\", "/").lstrip("/")
        if text:
            self.config_remote_changed.emit(text)

    def _build_footer(self) -> QtWidgets.QWidget:
        foot = QtWidgets.QWidget()
        foot.setMinimumHeight(t.IF_FOOTER_H)
        row = QtWidgets.QHBoxLayout(foot)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        status_host = QtWidgets.QWidget()
        status_host.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        status_wrap = QtWidgets.QHBoxLayout(status_host)
        status_wrap.setContentsMargins(0, 0, 0, 0)
        status_wrap.setSpacing(6)
        status_wrap.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self._status_icon = QtWidgets.QLabel()
        self._status_icon.setFixedSize(18, 18)
        self._status_icon.setPixmap(self._status_check_pix())
        self._status_icon.setVisible(True)
        status_wrap.addWidget(
            self._status_icon,
            0,
            QtCore.Qt.AlignmentFlag.AlignTop,
        )

        self._status = QtWidgets.QLabel("Ready to install.")
        self._status.setWordWrap(True)
        self._status.setMinimumWidth(0)
        self._status.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self._status.setStyleSheet(
            f"color:{t.IF_STATUS_MSG_FG}; font-size:{u.px(t.IF_STATUS_FONT_SIZE)}px; font-weight:600;"
        )
        status_wrap.addWidget(self._status, 1)
        row.addWidget(status_host, 1)

        self._progress = QtWidgets.QFrame()
        self._progress.setFixedSize(t.IF_PROGRESS_W, t.IF_PROGRESS_H)
        self._progress.setObjectName("ifInstallProgress")
        self._progress.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._progress.setStyleSheet(f"""
            QFrame#ifInstallProgress {{
                border: 1px solid {t.IF_PROGRESS_BORDER};
                border-radius: {t.IF_PROGRESS_H // 2}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.IF_PROGRESS_TRACK_TOP}, stop:1 {t.IF_PROGRESS_TRACK_BOT}
                );
            }}
        """)
        prog_lay = QtWidgets.QHBoxLayout(self._progress)
        prog_lay.setContentsMargins(2, 2, 2, 2)
        prog_lay.setSpacing(0)
        self._progress_fill = QtWidgets.QFrame()
        self._progress_fill.setFixedHeight(t.IF_PROGRESS_H - 4)
        self._progress_fill.setFixedWidth(0)
        self._progress_fill.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_PROGRESS_FILL_TOP},
                stop:0.58 {t.IF_PROGRESS_FILL_MID},
                stop:1 {t.IF_PROGRESS_FILL_BOT}
            );
            border-radius: {(t.IF_PROGRESS_H - 4) // 2}px;
        """)
        prog_lay.addWidget(self._progress_fill)
        prog_lay.addStretch(1)
        self._progress.setVisible(False)
        row.addWidget(self._progress, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        self._remove_btn = QtWidgets.QPushButton("Remove source")
        self._remove_btn.setVisible(False)
        self._remove_btn.setFixedHeight(t.IF_INSTALL_BTN_H)
        self._remove_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._remove_btn.setStyleSheet(_remove_source_btn_style())
        self._remove_btn.clicked.connect(self.remove_clicked.emit)
        row.addWidget(self._remove_btn, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        self._install_btn = QtWidgets.QPushButton("  Install Firmware")
        self._install_btn.setIcon(_make_install_icon(20))
        self._install_btn.setIconSize(QtCore.QSize(20, 20))
        self._install_btn.setFixedSize(t.IF_INSTALL_BTN_W, t.IF_INSTALL_BTN_H)
        self._install_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        _apply_install_btn_theme(self._install_btn)
        self._install_btn.setToolTip(
            "Copies the firmware bundled with this app.\n"
            "USB serial when connected; if the Pico is in BOOTSEL (RPI-RP2), "
            "MicroPython is flashed first, then the same firmware is copied."
        )
        self._install_btn.clicked.connect(self.install_clicked.emit)
        row.addWidget(self._install_btn)
        return foot

    @staticmethod
    def _status_check_pix() -> QtGui.QPixmap:
        size = 18
        pix = QtGui.QPixmap(size, size)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(t.IF_STATUS_CHECK_FG))
        pen.setWidthF(2.2)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawEllipse(QtCore.QRectF(2, 2, 14, 14))
        p.drawLine(QtCore.QPointF(5.5, 9.0), QtCore.QPointF(8.0, 11.5))
        p.drawLine(QtCore.QPointF(8.0, 11.5), QtCore.QPointF(13.0, 6.0))
        p.end()
        return pix

    def _build_empty_custom(self) -> QtWidgets.QWidget:
        wrap = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(wrap)
        lay.setContentsMargins(0, 40, 0, 40)
        lay.addStretch(1)

        card = QtWidgets.QFrame()
        card.setObjectName("innerCard")
        card.setStyleSheet(
            _inner_card_style().replace(
                f"border: 1px solid {t.IF_CARD_BORDER};",
                f"border: 2px dashed {t.IF_CARD_BORDER};",
            )
        )
        inner = QtWidgets.QVBoxLayout(card)
        inner.setContentsMargins(28, 24, 28, 24)
        inner.setSpacing(14)

        title = QtWidgets.QLabel("No custom firmware yet")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color:{t.TEXT_PRI}; font-size:{u.px(t.IF_NOTES_TITLE_PX)}px; "
            f"font-weight:{u.qss_weight(800)};"
        )
        inner.addWidget(title)

        copy = QtWidgets.QLabel(
            "Choose a firmware folder path or a UF2 file. UF2 files install directly; "
            "folders copy firmware files after MicroPython setup if needed.\n\n"
            "After you add a source, attach an optional config file or folder in the "
            "firmware card (copied to the Pico when you install)."
        )
        copy.setWordWrap(True)
        copy.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        copy.setStyleSheet(f"color:{t.TEXT_SEC}; font-size:{u.px(t.IF_SW_DESC_PX)}px;")
        inner.addWidget(copy)

        btn = QtWidgets.QPushButton("Choose Firmware")
        btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(_small_btn_style())
        btn.clicked.connect(self.add_custom_clicked.emit)
        inner.addWidget(btn)

        lay.addWidget(card)
        lay.addStretch(2)
        wrap.setVisible(False)
        return wrap

    def _apply_pane_style(self) -> None:
        r = t.IF_TAB_CORNER_RADIUS
        self.setStyleSheet(f"""
            #firmwareDetailPane {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.IF_DETAIL_TOP},
                    stop:0.72 {t.IF_DETAIL_MID},
                    stop:1 {t.IF_DETAIL_BOT}
                );
                border: none;
                border-radius: 0 {r}px {r}px 0;
            }}
        """)

    def resizeEvent(self, a0: QtGui.QResizeEvent) -> None:
        super().resizeEvent(a0)
        self._sync_sw_desc_height()

    def _apply_sw_title_style(self) -> None:
        self._sw_title.setStyleSheet(
            f"color:{t.TEXT_PRI}; font-size:{u.px(t.IF_SW_TITLE_PX)}px; "
            f"font-weight:{u.qss_weight(800)};"
        )

    def _apply_sw_desc_style(self) -> None:
        self._sw_desc.setStyleSheet(
            f"color:{t.TEXT_SEC}; font-size:{u.px(t.IF_SW_DESC_PX)}px;"
        )

    def _sync_sw_desc_height(self) -> None:
        """Size description to wrapped content — macOS line metrics exceed the old 32px cap."""
        if not hasattr(self, "_sw_desc"):
            return
        width = self._sw_desc.width()
        if width <= 1:
            QtCore.QTimer.singleShot(0, self._sync_sw_desc_height)
            return
        height = self._sw_desc.heightForWidth(width)
        if height <= 0:
            fm = QtGui.QFontMetrics(self._sw_desc.font())
            height = fm.lineSpacing() * 3
        self._sw_desc.setMinimumHeight(height)
        self._sw_desc.setMaximumHeight(height)

    def reload_theme(self) -> None:
        self._apply_pane_style()
        self._apply_sw_title_style()
        self._apply_sw_desc_style()
        self._sync_sw_desc_height()
        self._sw_badge.apply_variant(
            "badge_soft"
            if self._sw_badge.text() != "Official"
            else "badge_official"
        )  # type: ignore[arg-type]
        self._meta_version.reload_theme()
        self._meta_device.reload_theme()
        self._meta_author_link.reload_theme()
        self._meta_author_edit.reload_theme()
        self._status.setStyleSheet(
            f"color:{t.IF_STATUS_MSG_FG}; font-size:{u.px(t.IF_STATUS_FONT_SIZE)}px; font-weight:600;"
        )
        self._status_icon.setPixmap(self._status_check_pix())
        self._progress.setStyleSheet(f"""
            QFrame#ifInstallProgress {{
                border: 1px solid {t.IF_PROGRESS_BORDER};
                border-radius: {t.IF_PROGRESS_H // 2}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.IF_PROGRESS_TRACK_TOP}, stop:1 {t.IF_PROGRESS_TRACK_BOT}
                );
            }}
        """)
        self._progress_fill.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_PROGRESS_FILL_TOP},
                stop:0.58 {t.IF_PROGRESS_FILL_MID},
                stop:1 {t.IF_PROGRESS_FILL_BOT}
            );
            border-radius: {(t.IF_PROGRESS_H - 4) // 2}px;
        """)
        _apply_install_btn_theme(self._install_btn)
        field_h = _config_field_height()
        config_btn_h = u.px(26)
        field_style = _config_field_style()
        action_style = _config_action_btn_style()
        self._config_local_path.setFixedHeight(field_h)
        self._config_remote_edit.setFixedHeight(field_h)
        self._config_local_path.setStyleSheet(field_style)
        self._config_remote_edit.setStyleSheet(field_style)
        for btn in (
            self._config_attach_file_btn,
            self._config_attach_folder_btn,
            self._config_clear_btn,
        ):
            btn.setStyleSheet(action_style)
            btn.setFixedHeight(config_btn_h)
        self._remove_btn.setStyleSheet(_remove_source_btn_style())
        self._remove_btn.setFixedHeight(t.IF_INSTALL_BTN_H)
        self._config_local_caption.setStyleSheet(_config_caption_style())
        self._config_remote_caption.setStyleSheet(_config_caption_style())
        self._config_title.setStyleSheet(
            f"color:{t.TEXT_PRI}; font-size:{u.px(t.IF_NOTES_TITLE_PX)}px; "
            f"font-weight:{u.qss_weight(800)};"
        )
        self._config_card.setStyleSheet(_inner_card_style())
        self._fw_notes_card.reload_theme()
        self._user_notes_card.reload_theme()
