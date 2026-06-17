"""Right pane matching gui/scratch.html .firmware-details-panel — no outer scrollbar."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.updater import GITHUB_REPO_SLUG
from gui.widgets.install_firmware.common.meta_pill import AuthorMetaPill, MetaPill
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

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._mode = "official"
        self._has_selection = False
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
        self._meta_version.set_value(
            str(entry.get("version") or ("Custom" if custom else "v1.1")),
        )
        self._meta_device.set_value(
            str(entry.get("device") or "DFPlayer + RP2040"),
        )
        self._meta_author.set_author(
            str(entry.get("author") or ("You" if custom else _DEFAULT_FIRMWARE_AUTHOR)),
            str(entry.get("repoUrl") or ""),
        )

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
        body_lay.addWidget(self._middle, 1)

        remove_row = QtWidgets.QHBoxLayout()
        remove_row.addStretch(1)
        self._remove_btn = QtWidgets.QPushButton("Remove source")
        self._remove_btn.setVisible(False)
        self._remove_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._remove_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #fff0ea, stop:1 #f0d4c8);
                color: #5c2a18; border: 1px solid #b86a52; border-radius: 8px;
                padding: 8px 14px; font-weight: 800;
            }
        """)
        self._remove_btn.clicked.connect(self.remove_clicked.emit)
        remove_row.addWidget(self._remove_btn)
        body_lay.addLayout(remove_row)

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
        self._sw_title = QtWidgets.QLabel("Vintage Radio Basic")
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
        self._meta_version = MetaPill("Version", icon="tag")
        self._meta_device = MetaPill(
            "Device",
            icon="chip",
            width=t.IF_META_DEVICE_PILL_W,
        )
        self._meta_author = AuthorMetaPill()
        meta_row.addWidget(self._meta_version)
        meta_row.addWidget(self._meta_device)
        meta_row.addWidget(self._meta_author)
        lay.addLayout(meta_row)
        return card

    def _build_footer(self) -> QtWidgets.QWidget:
        foot = QtWidgets.QWidget()
        foot.setFixedHeight(t.IF_FOOTER_H)
        row = QtWidgets.QHBoxLayout(foot)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        status_wrap = QtWidgets.QHBoxLayout()
        status_wrap.setSpacing(6)
        self._status_icon = QtWidgets.QLabel()
        self._status_icon.setFixedSize(18, 18)
        self._status_icon.setPixmap(self._status_check_pix())
        self._status_icon.setVisible(True)
        status_wrap.addWidget(self._status_icon)

        self._status = QtWidgets.QLabel("Ready to install.")
        self._status.setStyleSheet(
            f"color:{t.IF_STATUS_MSG_FG}; font-size:{u.px(t.IF_STATUS_FONT_SIZE)}px; font-weight:600;"
        )
        status_wrap.addWidget(self._status)
        row.addLayout(status_wrap, 1)

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

        self._install_btn = QtWidgets.QPushButton("  Install Firmware")
        self._install_btn.setIcon(_make_install_icon(20))
        self._install_btn.setIconSize(QtCore.QSize(20, 20))
        self._install_btn.setFixedSize(t.IF_INSTALL_BTN_W, t.IF_INSTALL_BTN_H)
        self._install_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        _apply_install_btn_theme(self._install_btn)
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
            "folders copy firmware files after MicroPython setup if needed."
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
        self._meta_author.reload_theme()
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
        self._fw_notes_card.reload_theme()
        self._user_notes_card.reload_theme()
