"""Read-only notes for official firmware; editable for custom entries."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar


class FirmwareNotesPanel(QtWidgets.QWidget):
    """Right pane: gesture / user notes for the selected software."""

    notes_edited = pyqtSignal(str)
    remove_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._is_custom = False
        self._build()

    @property
    def notes_edit(self) -> QtWidgets.QPlainTextEdit:
        return self._notes

    @property
    def remove_btn(self) -> QtWidgets.QPushButton:
        return self._remove_btn

    def set_entry(self, *, notes: str, custom: bool, editable: bool) -> None:
        self._is_custom = custom
        self._notes.blockSignals(True)
        self._notes.setPlainText(notes)
        self._notes.setReadOnly(not editable)
        self._notes.blockSignals(False)
        self._hint.setVisible(not custom)
        self._remove_btn.setVisible(custom)
        if custom:
            self._hint.setText("Your notes are saved automatically when you edit them.")
        else:
            self._hint.setText("Official firmware notes (read-only).")

    def _build(self) -> None:
        self.setObjectName("firmwareNotesPane")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_pane_style()

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_header())
        body = QtWidgets.QWidget()
        body.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        body.setStyleSheet("background: transparent;")
        body_lay = QtWidgets.QVBoxLayout(body)
        body_lay.setContentsMargins(16, 12, 16, 16)
        body_lay.setSpacing(8)

        self._hint = QtWidgets.QLabel("Official firmware notes (read-only).")
        self._hint.setStyleSheet(f"color:{t.TEXT_SEC}; font-size:{u.px(12)}px;")
        body_lay.addWidget(self._hint)

        self._notes = QtWidgets.QPlainTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setStyleSheet(f"""
            QPlainTextEdit {{
                background: rgba(255, 252, 246, 0.72);
                color: {t.TEXT_PRI};
                border: 1px solid {t.BORDER};
                border-radius: 8px;
                padding: 10px;
                font-size: {u.px(t.IF_NOTES_FONT_SIZE)}px;
                line-height: 1.45;
            }}
        """)
        self._notes.textChanged.connect(self._on_text_changed)
        notes_scroll = wrap_with_mockup_scrollbar(self._notes, variant="track")
        body_lay.addWidget(notes_scroll, 1)

        lay.addWidget(body, 1)

    def _build_header(self) -> QtWidgets.QWidget:
        hdr = QtWidgets.QWidget()
        hdr.setFixedHeight(t.LM_PANEL_HEADER_H)
        hdr.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        hdr.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.PANEL_HDR_GRAD_TOP},
                    stop:1 {t.PANEL_HDR_GRAD_BOT}
                );
            }}
        """)
        row = QtWidgets.QHBoxLayout(hdr)
        l, top, r, bot = t.LM_PANEL_HDR_MARGINS
        row.setContentsMargins(l, top, r, bot)

        title = QtWidgets.QLabel("Notes")
        title.setStyleSheet(
            f"color:{t.LM_PANEL_HDR_TEXT_COLOR};"
            f"font-size:{u.px(t.LM_PANEL_HDR_FONT_SIZE)}px; font-weight:800;"
        )
        row.addWidget(title)
        row.addStretch(1)

        self._remove_btn = QtWidgets.QPushButton("Remove")
        self._remove_btn.setFixedHeight(t.LM_PANEL_NEW_BTN_H)
        self._remove_btn.setVisible(False)
        self._remove_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._remove_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #fff0ea,
                    stop:1 #f0d4c8
                );
                color: #5c2a18;
                border: 1px solid #b86a52;
                border-radius: {t.LM_PANEL_NEW_BTN_RADIUS}px;
                padding: 0 12px;
                font-size: {u.px(12)}px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background: #ffe8de; }}
        """)
        self._remove_btn.clicked.connect(self.remove_clicked.emit)
        row.addWidget(self._remove_btn)
        return hdr

    def _on_text_changed(self) -> None:
        if self._is_custom and not self._notes.isReadOnly():
            self.notes_edited.emit(self._notes.toPlainText())

    def _apply_pane_style(self) -> None:
        self.setStyleSheet(f"""
            #firmwareNotesPane {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.TRK_PANE_GRAD_TOP},
                    stop:1 {t.TRK_PANE_GRAD_BOT}
                );
            }}
        """)

    def reload_theme(self) -> None:
        self._apply_pane_style()
        self._hint.setStyleSheet(f"color:{t.TEXT_SEC}; font-size:{u.px(12)}px;")
        self._notes.setStyleSheet(f"""
            QPlainTextEdit {{
                background: rgba(255, 252, 246, 0.72);
                color: {t.TEXT_PRI};
                border: 1px solid {t.BORDER};
                border-radius: 8px;
                padding: 10px;
                font-size: {u.px(t.IF_NOTES_FONT_SIZE)}px;
            }}
        """)
