"""
gui/widgets/load_music/storage_section/storage_section.py
===========================================================
Storage banner — SD path, capacity bar, and Detect / Select actions.

Layout mirrors the Install Firmware device banner (cream card, icon, status
pill, primary + outline buttons).
"""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.install_firmware.common.pill_label import PillLabel


def _banner_btn_style(*, primary: bool = False) -> str:
    fs = u.px(t.IF_DEVICE_BTN_FONT)
    if primary:
        return f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.IF_INSTALL_BTN_TOP}, stop:0.58 {t.IF_INSTALL_BTN_MID},
                    stop:1 {t.IF_INSTALL_BTN_BOT}
                );
                color: {t.IF_INSTALL_BTN_FG};
                border: 2px solid {t.IF_INSTALL_BTN_BORDER};
                border-radius: {u.px(t.LM_SD_BTN_RADIUS)}px;
                padding: 0 10px;
                font-size: {fs}px;
                font-weight: 800;
            }}
            QPushButton:hover   {{ background: {t.IF_INSTALL_BTN_MID}; }}
            QPushButton:pressed {{ background: {t.IF_INSTALL_BTN_BOT}; }}
        """
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.OUTLINE_BTN_GRAD_TOP},
                stop:1 {t.OUTLINE_BTN_GRAD_BOT}
            );
            color: {t.TEXT_PRI};
            border: 2px solid {t.LM_SD_BTN_BORDER};
            border-radius: {u.px(t.LM_SD_BTN_RADIUS)}px;
            padding: 0 10px;
            font-size: {fs}px;
            font-weight: 800;
        }}
        QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; }}
        QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; }}
    """


def _paint_sd_card_icon(size: int) -> QtGui.QPixmap:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    r = size * 0.25
    bg = QtGui.QLinearGradient(0, 0, 0, size)
    bg.setColorAt(0, QtGui.QColor(t.IF_DEVICE_ICON_TOP))
    bg.setColorAt(1, QtGui.QColor(t.IF_DEVICE_ICON_BOT))
    p.setBrush(bg)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.drawRoundedRect(QtCore.QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88), r, r)

    pen = QtGui.QPen(QtGui.QColor("#fff4e6"))
    pen.setWidthF(max(1.8, size * 0.045))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    s = size / 64.0
    p.drawRoundedRect(QtCore.QRectF(16 * s, 18 * s, 32 * s, 28 * s), 3 * s, 3 * s)
    p.drawRect(QtCore.QRectF(22 * s, 14 * s, 8 * s, 6 * s))
    p.drawLine(QtCore.QPointF(22 * s, 30 * s), QtCore.QPointF(42 * s, 30 * s))
    p.drawLine(QtCore.QPointF(22 * s, 36 * s), QtCore.QPointF(36 * s, 36 * s))
    p.end()
    return pix


class _CapacityBar(QtWidgets.QWidget):
    """Custom capacity bar with rounded fill ends."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._value = 0
        self._minimum = 0
        self._maximum = 100
        self.setFixedHeight(u.px(t.LM_CAPACITY_BAR_H))
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    def setValue(self, value: int) -> None:
        self._value = max(self._minimum, min(self._maximum, value))
        self.update()

    def value(self) -> int:
        return self._value

    def setMinimum(self, v: int) -> None:
        self._minimum = v

    def setMaximum(self, v: int) -> None:
        self._maximum = v

    def setRange(self, minimum: int, maximum: int) -> None:
        self._minimum = minimum
        self._maximum = maximum

    def setFormat(self, _: str) -> None:
        pass

    def setTextVisible(self, _: bool) -> None:
        pass

    def paintEvent(self, _: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        border_w = max(1, u.px(2))
        radius = u.px(t.LM_CAPACITY_BAR_RADIUS)
        inner_r = max(1, radius - border_w)

        track_grad = QtGui.QLinearGradient(0, rect.top(), 0, rect.bottom())
        track_grad.setColorAt(0.0, QtGui.QColor(t.CAP_TRACK_GRAD_TOP))
        track_grad.setColorAt(1.0, QtGui.QColor(t.CAP_TRACK_GRAD_BOT))
        p.setPen(QtGui.QPen(QtGui.QColor(t.LM_CAPACITY_BAR_BORDER), border_w))
        p.setBrush(QtGui.QBrush(track_grad))
        p.drawRoundedRect(
            QtCore.QRectF(rect).adjusted(border_w / 2, border_w / 2, -border_w / 2, -border_w / 2),
            radius,
            radius,
        )

        span = self._maximum - self._minimum
        fraction = (self._value - self._minimum) / span if span > 0 else 0.0
        inner = QtCore.QRectF(rect).adjusted(border_w, border_w, -border_w, -border_w)
        fill_w = inner.width() * fraction
        if fill_w > 0.5:
            p.save()
            clip_path = QtGui.QPainterPath()
            clip_path.addRoundedRect(inner, inner_r, inner_r)
            p.setClipPath(clip_path)
            fill_grad = QtGui.QLinearGradient(0, inner.top(), 0, inner.bottom())
            fill_grad.setColorAt(0.0, QtGui.QColor(t.CAP_FILL_GRAD_TOP))
            fill_grad.setColorAt(0.5, QtGui.QColor(t.CAP_FILL_GRAD_MID))
            fill_grad.setColorAt(1.0, QtGui.QColor(t.CAP_FILL_GRAD_BOT))
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QBrush(fill_grad))
            fill_h = inner.height()
            fill_radius = min(inner_r, fill_h / 2.0, max(0.0, fill_w / 2.0))
            fill_rect = QtCore.QRectF(inner.x(), inner.y(), fill_w, fill_h)
            p.drawRoundedRect(fill_rect, fill_radius, fill_radius)
            p.restore()
        p.end()


class StorageSection(QtWidgets.QFrame):
    """SD storage banner with capacity bar and Detect / Select buttons."""

    detect_clicked = pyqtSignal()
    select_clicked = pyqtSignal()
    browse_clicked = pyqtSignal()

    def __init__(self, sd_root: str = "", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._sd_root = sd_root
        self._build()

    @property
    def sd_root_label(self) -> QtWidgets.QLabel:
        return self._root_label

    @property
    def capacity_bar(self) -> _CapacityBar:
        return self._bar

    @property
    def percent_label(self) -> QtWidgets.QLabel:
        return self._pct_label

    @property
    def capacity_label(self) -> QtWidgets.QLabel:
        return self._cap_label

    @property
    def title_label(self) -> QtWidgets.QLabel:
        return self._title

    @property
    def status_pill(self) -> PillLabel:
        return self._status_pill

    @property
    def detect_btn(self) -> QtWidgets.QPushButton:
        return self._detect_btn

    @property
    def select_btn(self) -> QtWidgets.QPushButton:
        return self._select_btn

    def set_has_sd_card(self, selected: bool) -> None:
        if selected:
            self._status_pill.setText("Ready")
            self._status_pill.apply_variant("status_on")
        else:
            self._status_pill.setText("Not selected")
            self._status_pill.apply_variant("status_off")

    def _sync_layout(self) -> None:
        m = u.device_banner_layout()
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(m["pad_h"], m["pad_v"], m["pad_h"], m["pad_v"])
            lay.setSpacing(m["gap"])
        self.setFixedHeight(m["height"])

        icon_sz = m["icon_h"]
        compact = u.banner_compact()
        self._icon_wrap.setVisible(not compact)
        self._icon_wrap.setFixedSize(icon_sz, icon_sz)
        self._icon_wrap.setPixmap(_paint_sd_card_icon(icon_sz))
        self._icon_wrap.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_DEVICE_ICON_TOP}, stop:1 {t.IF_DEVICE_ICON_BOT}
            );
            border-radius: {u.px(t.IF_DEVICE_ICON_RADIUS)}px;
        """)

        if u.ZOOM_PERCENT > 120:
            self._bar.setMinimumWidth(u.px_layout(80))
            self._bar.setMaximumWidth(16777215)
        else:
            self._bar.setMinimumWidth(u.px(t.LM_CAPACITY_BAR_MIN_W))
            self._bar.setMaximumWidth(u.px(t.LM_CAPACITY_BAR_MAX_W))
        self._bar.setFixedHeight(u.px(t.LM_CAPACITY_BAR_H))
        self._bar.update()

        for lbl in (self._pct_label, self._cap_label):
            lbl.setMinimumWidth(0)
            lbl.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Maximum,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )
        self._root_label.setMinimumWidth(0)
        self._root_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )

        btn_h = m["btn_h"]
        for btn, primary in (
            (self._detect_btn, True),
            (self._select_btn, False),
            (self._browse_btn, False),
        ):
            btn.setFixedSize(u.action_button_width(btn, t.IF_DEVICE_BTN_W), btn_h)
            btn.setStyleSheet(_banner_btn_style(primary=primary))

    def _build(self) -> None:
        self.setObjectName("lmStorageBanner")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_banner_style()

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 4)
        col = QtGui.QColor(75, 43, 18, 33)
        shadow.setColor(col)
        self.setGraphicsEffect(shadow)

        lay = QtWidgets.QHBoxLayout(self)
        m = u.device_banner_layout()
        lay.setContentsMargins(m["pad_h"], m["pad_v"], m["pad_h"], m["pad_v"])
        lay.setSpacing(m["gap"])
        self.setFixedHeight(m["height"])

        self._icon_wrap = QtWidgets.QLabel()
        icon_sz = m["icon_h"]
        self._icon_wrap.setFixedSize(icon_sz, icon_sz)
        self._icon_wrap.setPixmap(_paint_sd_card_icon(icon_sz))
        self._icon_wrap.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_DEVICE_ICON_TOP}, stop:1 {t.IF_DEVICE_ICON_BOT}
            );
            border-radius: {u.px(t.IF_DEVICE_ICON_RADIUS)}px;
        """)
        lay.addWidget(self._icon_wrap)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(m["text_gap"])
        self._title = QtWidgets.QLabel("Storage")
        self._title.setStyleSheet(
            f"color:{t.IF_DEVICE_TITLE_FG}; font-size:{u.px(t.IF_DEVICE_TITLE_SIZE)}px; font-weight:800;"
        )
        text_col.addWidget(self._title)

        meta_row = QtWidgets.QHBoxLayout()
        meta_row.setSpacing(m["meta_gap"])
        self._status_pill = PillLabel("Not selected", variant="status_off")
        meta_row.addWidget(self._status_pill)
        self._root_label = QtWidgets.QLabel(self._sd_root or "Choose an SD card to sync music.")
        self._root_label.setStyleSheet(
            f"color:{t.IF_DEVICE_META_FG}; font-size:{u.px(t.IF_DEVICE_META_SIZE)}px;"
        )
        meta_row.addWidget(self._root_label, 1)
        text_col.addLayout(meta_row)
        lay.addLayout(text_col, 1)

        cap_col = QtWidgets.QHBoxLayout()
        cap_col.setSpacing(m["meta_gap"])
        self._bar = _CapacityBar()
        self._bar.setMinimumWidth(u.px(t.LM_CAPACITY_BAR_MIN_W))
        self._bar.setMaximumWidth(u.px(t.LM_CAPACITY_BAR_MAX_W))
        self._bar.setValue(0)
        cap_col.addWidget(self._bar)

        self._pct_label = QtWidgets.QLabel("")
        self._pct_label.setStyleSheet(f"color:{t.IF_DEVICE_META_FG}; font-size:{u.px(t.IF_DEVICE_META_SIZE)}px;")
        cap_col.addWidget(self._pct_label)

        self._cap_label = QtWidgets.QLabel("")
        self._cap_label.setStyleSheet(f"color:{t.IF_DEVICE_META_FG}; font-size:{u.px(t.IF_DEVICE_META_SIZE)}px;")
        cap_col.addWidget(self._cap_label)
        lay.addLayout(cap_col)

        self._detect_btn = QtWidgets.QPushButton("Detect")
        self._detect_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._detect_btn.setToolTip(
            "Find your SD card again using the saved volume name (e.g. after reconnecting USB).\n"
            "Does not ask to confirm a different card."
        )
        self._detect_btn.clicked.connect(self.detect_clicked.emit)

        self._select_btn = QtWidgets.QPushButton("Select")
        self._select_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._select_btn.setToolTip(
            "Pick from detected removable drives (dropdown).\n"
            "If nothing is listed, use Browse. Wrong-card safety is only on Sync."
        )
        self._select_btn.clicked.connect(self.select_clicked.emit)

        self._browse_btn = QtWidgets.QPushButton("Browse")
        self._browse_btn.clicked.connect(self.browse_clicked.emit)
        self._browse_btn.setVisible(False)

        btn_box = QtWidgets.QHBoxLayout()
        btn_box.setSpacing(m["btn_gap"])
        btn_box.addWidget(self._detect_btn)
        btn_box.addWidget(self._select_btn)
        lay.addLayout(btn_box)

        self._sync_layout()
        self.set_has_sd_card(bool(self._sd_root))

    def _apply_banner_style(self) -> None:
        self.setStyleSheet(f"""
            #lmStorageBanner {{
                border: 1px solid {t.IF_DEVICE_BANNER_BORDER};
                border-radius: {u.px(12)}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.IF_DEVICE_BANNER_TOP}, stop:1 {t.IF_DEVICE_BANNER_BOT}
                );
            }}
        """)

    def reload_theme(self) -> None:
        self._apply_banner_style()
        self._title.setStyleSheet(
            f"color:{t.IF_DEVICE_TITLE_FG}; font-size:{u.px(t.IF_DEVICE_TITLE_SIZE)}px; font-weight:800;"
        )
        self._root_label.setStyleSheet(
            f"color:{t.IF_DEVICE_META_FG}; font-size:{u.px(t.IF_DEVICE_META_SIZE)}px;"
        )
        self._pct_label.setStyleSheet(
            f"color:{t.IF_DEVICE_META_FG}; font-size:{u.px(t.IF_DEVICE_META_SIZE)}px;"
        )
        self._cap_label.setStyleSheet(
            f"color:{t.IF_DEVICE_META_FG}; font-size:{u.px(t.IF_DEVICE_META_SIZE)}px;"
        )
        self._status_pill.reload_theme()
        self._sync_layout()
        selected = self._status_pill.text() == "Ready"
        self.set_has_sd_card(selected)
