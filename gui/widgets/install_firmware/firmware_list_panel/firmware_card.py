"""Clickable firmware card widget matching scratch.html .firmware-card."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.install_firmware.common.pill_label import PillLabel


class FirmwareCard(QtWidgets.QFrame):
    """Single selectable firmware card in the left panel list."""

    clicked = pyqtSignal()

    def __init__(
        self,
        entry: Dict[str, Any],
        *,
        selected: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FirmwareCard")
        self._entry = entry
        self._selected = selected
        self._tag_pills: List[PillLabel] = []
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(t.IF_FIRMWARE_CARD_H)
        self._build()
        self.set_selected(selected)

    @property
    def entry(self) -> Dict[str, Any]:
        return self._entry

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _build(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(6)

        title = str(self._entry.get("listName") or self._entry.get("name") or "Firmware")
        self._title = QtWidgets.QLabel(title)
        self._title.setWordWrap(True)
        lay.addWidget(self._title)

        subtitle = str(
            self._entry.get("listSubtitle") or self._entry.get("description") or ""
        ).strip()
        if self._entry.get("disabled"):
            subtitle = str(self._entry.get("listSubtitle") or "Coming soon")
        self._subtitle = QtWidgets.QLabel(subtitle)
        self._subtitle.setWordWrap(True)
        lay.addWidget(self._subtitle)

        tag_row = QtWidgets.QHBoxLayout()
        tag_row.setSpacing(t.IF_CARD_TAG_GAP)
        tag_row.addStretch(1)
        for tag in self._tags_for(self._entry):
            pill = PillLabel(
                tag,
                variant="card_tag_idle",
                fixed_width=t.IF_CARD_TAG_W,
                fixed_height=t.IF_CARD_TAG_H,
            )
            self._tag_pills.append(pill)
            tag_row.addWidget(pill)
        lay.addLayout(tag_row)

    def _tags_for(self, entry: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        version = str(entry.get("version") or "").strip()
        mc = str(entry.get("microcontroller") or "").strip()
        mp3 = str(entry.get("mp3Controller") or "").strip()
        device = str(entry.get("device") or "")
        kind = str(entry.get("kind") or "").lower()
        if version:
            tags.append(version)
        if mc:
            tags.append(mc)
        elif "RP2040" in device:
            tags.append("RP2040")
        if mp3:
            tags.append(mp3)
        elif "DFPlayer" in device:
            tags.append("DFPlayer")
        elif "VS1053" in device:
            tags.append("VS1053")
        if kind == "uf2":
            tags.append("UF2")
        return tags[:3]

    def reload_theme(self) -> None:
        self._apply_style()

    def _apply_style(self) -> None:
        variant = "card_tag_selected" if self._selected else "card_tag_idle"
        for pill in self._tag_pills:
            pill.apply_variant(variant)

        if self._selected:
            self.setStyleSheet(f"""
                QFrame#FirmwareCard {{
                    border-radius: 11px;
                    border: 1px solid {t.IF_CARD_SEL_BORDER};
                    background: qlineargradient(
                        x1:0, y1:0, x2:0, y2:1,
                        stop:0 {t.IF_CARD_SEL_TOP},
                        stop:0.55 #cf761f,
                        stop:1 {t.IF_CARD_SEL_BOT}
                    );
                }}
            """)
            self._title.setStyleSheet(
                f"font-size:{u.px(t.IF_CARD_TITLE_PX)}px; font-weight:{u.qss_weight(800)}; color:#ffffff; background:transparent;"
            )
            self._subtitle.setStyleSheet(
                f"font-size:{u.px(t.IF_CARD_SUB_PX)}px; color:#fff6e5; background:transparent;"
            )
        else:
            disabled = bool(self._entry.get("disabled"))
            self.setStyleSheet(f"""
                QFrame#FirmwareCard {{
                    border-radius: 11px;
                    border: 1px solid #c4a882;
                    background-color: {t.IF_CARD_IDLE_BG};
                }}
            """)
            self._title.setStyleSheet(
                f"font-size:{u.px(t.IF_CARD_TITLE_PX)}px; font-weight:{u.qss_weight(800)}; color:{t.IF_CARD_IDLE_TEXT}; background:transparent;"
            )
            sub = "#8a7968" if disabled else t.IF_CARD_IDLE_SUBTEXT
            self._subtitle.setStyleSheet(
                f"font-size:{u.px(t.IF_CARD_SUB_PX)}px; color:{sub}; background:transparent;"
            )

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
