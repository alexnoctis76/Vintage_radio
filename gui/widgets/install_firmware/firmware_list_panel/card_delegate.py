"""Paint firmware list rows as rich cards matching gui/scratch.html."""

from __future__ import annotations

from typing import Any, Dict, List

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u


class FirmwareCardDelegate(QtWidgets.QStyledItemDelegate):
    """Legacy delegate — prefer FirmwareCard widgets in firmware_list_panel."""

    MARGIN_X = 14
    MARGIN_Y = 8
    CARD_RADIUS = 11
    TAG_GAP = 7
    TAG_PAD_H = 9

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        entry = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(self.MARGIN_X, self.MARGIN_Y, -self.MARGIN_X, -self.MARGIN_Y)
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        disabled = bool(entry.get("disabled"))

        self._paint_card_bg(painter, rect, selected=selected, disabled=disabled)
        self._paint_card_content(painter, rect, entry, selected=selected, disabled=disabled)
        painter.restore()

    def _paint_card_bg(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        *,
        selected: bool,
        disabled: bool,
    ) -> None:
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(rect), self.CARD_RADIUS, self.CARD_RADIUS)

        if selected:
            grad = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, QtGui.QColor(t.IF_CARD_SEL_TOP))
            grad.setColorAt(0.55, QtGui.QColor("#cf761f"))
            grad.setColorAt(1, QtGui.QColor(t.IF_CARD_SEL_BOT))
            painter.fillPath(path, grad)
            pen = QtGui.QPen(QtGui.QColor(t.IF_CARD_SEL_BORDER))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawPath(path)
        else:
            fill = QtGui.QColor(t.IF_CARD_IDLE_BG)
            fill.setAlpha(185 if not disabled else 120)
            painter.fillPath(path, fill)
            border = QtGui.QColor(255, 229, 190, 60)
            painter.setPen(QtGui.QPen(border, 1))
            painter.drawPath(path)

    def _paint_card_content(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        entry: Dict[str, Any],
        *,
        selected: bool,
        disabled: bool,
    ) -> None:
        title = str(entry.get("listName") or entry.get("name") or "Firmware")
        subtitle = str(
            entry.get("listSubtitle")
            or entry.get("description")
            or entry.get("name")
            or ""
        ).strip()
        if disabled:
            subtitle = str(entry.get("listSubtitle") or "Coming soon")

        text_color = QtGui.QColor("#ffffff" if selected else t.IF_CARD_IDLE_TEXT)
        sub_color = QtGui.QColor("#ffffff" if selected else t.IF_CARD_IDLE_SUBTEXT)
        if disabled and not selected:
            text_color = QtGui.QColor(t.IF_CARD_IDLE_SUBTEXT)
            sub_color = QtGui.QColor("#8a7968")

        x = rect.left() + 18
        y = rect.top() + 16
        w = max(rect.width() - 36, 40)

        title_font = QtGui.QFont()
        title_font.setPixelSize(u.px(t.IF_CARD_TITLE_PX))
        title_font.setWeight(QtGui.QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.setPen(text_color)
        painter.drawText(
            QtCore.QRect(x, y, w, 30),
            int(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.TextFlag.TextWordWrap),
            title,
        )

        sub_font = QtGui.QFont()
        sub_font.setPixelSize(u.px(t.IF_CARD_SUB_PX))
        painter.setFont(sub_font)
        painter.setPen(sub_color)
        painter.drawText(
            QtCore.QRect(x, y + 32, w, 40),
            int(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.TextFlag.TextWordWrap),
            subtitle,
        )

        tags = self._tags_for(entry)
        tag_y = rect.bottom() - 34
        tag_x = x
        tag_font = QtGui.QFont()
        tag_font.setPixelSize(u.px(t.IF_CARD_TAG_PX))
        tag_font.setWeight(QtGui.QFont.Weight.Bold)
        painter.setFont(tag_font)
        fm = QtGui.QFontMetrics(tag_font)

        for tag in tags:
            tw = fm.horizontalAdvance(tag) + self.TAG_PAD_H * 2
            tag_rect = QtCore.QRectF(tag_x, tag_y, tw, 22)
            tag_path = QtGui.QPainterPath()
            tag_path.addRoundedRect(tag_rect, 11, 11)
            tag_fill = QtGui.QColor(255, 255, 255, 42 if selected else 28)
            painter.fillPath(tag_path, tag_fill)
            painter.setPen(QtGui.QColor("#fff6f0" if selected else t.IF_CARD_IDLE_TEXT))
            painter.drawText(tag_rect, int(QtCore.Qt.AlignmentFlag.AlignCenter), tag)
            tag_x += int(tw) + self.TAG_GAP

    def _tags_for(self, entry: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        version = str(entry.get("version") or "").strip()
        device = str(entry.get("device") or "").strip()
        mc = str(entry.get("microcontroller") or "").strip()
        mp3 = str(entry.get("mp3Controller") or "").strip()
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

    def sizeHint(
        self,
        option: QtWidgets.QStyleOptionViewItem,
        _index: QtCore.QModelIndex,
    ) -> QtCore.QSize:
        width = option.rect.width() if option.rect.width() > 0 else 360
        return QtCore.QSize(width, t.IF_FIRMWARE_CARD_H + self.MARGIN_Y * 2)
