"""Dark left panel with filter strip and card-style firmware list."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from gui.widgets.install_firmware.firmware_list_panel.firmware_card import FirmwareCard


def _svg_resource(filename: str) -> Path:
    from gui.resource_paths import gui_dir

    return gui_dir() / "resources" / filename


_FILTER_ICON_COLOR = "#2c1f14"


def _filter_btn_style() -> str:
    return """
        QPushButton {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #fff7ec, stop:1 #ead8bf);
            color: #2c1f14;
            border: 1px solid #d9b47f;
            border-radius: 8px;
        }
        QPushButton:hover { background: #fff7ec; }
    """


def _add_btn_style() -> str:
    border = "1px solid #d9b47f"
    radius = "8px"
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.MINI_BTN_GRAD_TOP},
                stop:1 {t.MINI_BTN_GRAD_BOT}
            );
            color: #fff4df;
            border: {border};
            border-radius: {radius};
            padding: 0 14px;
            font-size: {u.px(13)}px;
            font-weight: 800;
            outline: none;
        }}
        QPushButton:hover {{
            background: {t.MINI_BTN_GRAD_TOP};
            border: {border};
            border-radius: {radius};
        }}
        QPushButton:pressed {{
            background: {t.MINI_BTN_GRAD_BOT};
            border: {border};
            border-radius: {radius};
        }}
        QPushButton:focus {{
            outline: none;
            border: {border};
            border-radius: {radius};
        }}
    """


class FirmwareListPanel(QtWidgets.QWidget):
    selection_changed = pyqtSignal(object)
    add_custom_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: List[Dict[str, Any]] = []
        self._cards: List[FirmwareCard] = []
        self._selected_id = ""
        self._mode = "official"
        self._build()

    @property
    def list_widget(self) -> QtWidgets.QWidget:
        """Backward compat alias — returns the scroll area."""
        return self._scroll

    def set_mode(self, mode: str) -> None:
        self._mode = "custom" if mode == "custom" else "official"

    def selected_entry(self) -> Optional[Dict[str, Any]]:
        if not self._selected_id:
            return None
        for entry in self._entries:
            if str(entry.get("id", "")) == self._selected_id:
                return entry
        return None

    def set_entries(
        self,
        entries: List[Dict[str, Any]],
        *,
        selected_id: str = "",
        show_filter: bool = False,
    ) -> None:
        self._entries = list(entries)
        show_filter_btn = (
            self._mode == "official" and show_filter and len(entries) > 1
        )
        show_strip = show_filter_btn or self._mode == "custom"
        self._filter_strip.setVisible(show_strip)
        self._filter_strip.setFixedHeight(t.IF_FILTER_STRIP_H if show_strip else 0)
        self._filter_btn.setVisible(show_filter_btn)
        self._add_btn.setVisible(self._mode == "custom")

        top_pad = 18 if show_strip else 14
        self._cards_lay.setContentsMargins(14, top_pad, 14, 18)

        while self._cards_lay.count():
            item = self._cards_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()

        pick_id = selected_id
        if pick_id and not any(str(e.get("id", "")) == pick_id for e in entries):
            pick_id = ""
        if not pick_id and entries:
            pick_id = str(entries[0].get("id", ""))

        self._selected_id = pick_id
        for entry in entries:
            card = FirmwareCard(entry, selected=str(entry.get("id", "")) == pick_id)
            card.clicked.connect(lambda e=entry: self._on_card_clicked(e))
            self._cards_lay.addWidget(card)
            self._cards.append(card)

        self._cards_lay.addStretch(1)

        if pick_id:
            picked = next((e for e in entries if str(e.get("id", "")) == pick_id), None)
            self.selection_changed.emit(picked)
        elif not entries:
            self.selection_changed.emit(None)

    def _on_card_clicked(self, entry: Dict[str, Any]) -> None:
        self._selected_id = str(entry.get("id", ""))
        for card in self._cards:
            card.set_selected(str(card.entry.get("id", "")) == self._selected_id)
        self.selection_changed.emit(entry)

    def _build(self) -> None:
        self.setObjectName("firmwareListPane")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_pane_style()

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._filter_strip = QtWidgets.QWidget()
        self._filter_strip.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._filter_strip.setStyleSheet("background: transparent;")
        strip_lay = QtWidgets.QHBoxLayout(self._filter_strip)
        strip_lay.setContentsMargins(18, 9, 18, 9)

        self._filter_btn = QtWidgets.QPushButton()
        self._filter_btn.setFixedSize(50, 42)
        self._filter_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._filter_btn.setToolTip("Filter firmware (coming soon)")
        self._filter_btn.setStyleSheet(_filter_btn_style())
        self._filter_btn.setVisible(False)
        strip_lay.addWidget(self._filter_btn)
        strip_lay.addStretch(1)

        self._add_btn = QtWidgets.QPushButton("+ Add custom")
        self._add_btn.setFixedHeight(42)
        self._add_btn.setVisible(False)
        self._add_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._add_btn.setStyleSheet(_add_btn_style())
        self._add_btn.clicked.connect(self.add_custom_clicked.emit)
        strip_lay.addWidget(self._add_btn)

        self._filter_strip.setFixedHeight(0)
        self._filter_strip.setVisible(False)
        lay.addWidget(self._filter_strip)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._cards_host = QtWidgets.QWidget()
        self._cards_host.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._cards_host.setStyleSheet("background: transparent;")
        self._cards_lay = QtWidgets.QVBoxLayout(self._cards_host)
        self._cards_lay.setContentsMargins(14, 14, 6, 18)
        self._cards_lay.setSpacing(16)
        self._scroll.setWidget(self._cards_host)

        self._scroll_wrap = wrap_with_mockup_scrollbar(
            self._scroll,
            variant="station",
        )
        lay.addWidget(self._scroll_wrap, 1)

        self._paint_filter_icon()

    def _paint_filter_icon(self) -> None:
        size = 24
        pix = QtGui.QPixmap(size, size)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        renderer = QtSvg.QSvgRenderer(str(_svg_resource("Filter.svg")))
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        renderer.render(p, QtCore.QRectF(pix.rect()))
        p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(pix.rect(), QtGui.QColor(_FILTER_ICON_COLOR))
        p.end()
        self._filter_btn.setIcon(QtGui.QIcon(pix))
        self._filter_btn.setIconSize(QtCore.QSize(size, size))

    def _apply_pane_style(self) -> None:
        r = t.IF_TAB_CORNER_RADIUS
        self.setStyleSheet(f"""
            #firmwareListPane {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.IF_LIST_PANEL_TOP},
                    stop:1 {t.IF_LIST_PANEL_BOT}
                );
                border: none;
                border-radius: 0 0 0 {r}px;
            }}
        """)

    def reload_theme(self) -> None:
        self._apply_pane_style()
        self._filter_btn.setStyleSheet(_filter_btn_style())
        self._add_btn.setStyleSheet(_add_btn_style())
        self._paint_filter_icon()
        for card in self._cards:
            card.set_selected(str(card.entry.get("id", "")) == self._selected_id)
