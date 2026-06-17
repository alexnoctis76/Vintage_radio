"""Device connection banner — single-row Tools debugger layout."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets
from PyQt6.QtCore import pyqtSignal

import gui.theme as t
from gui import ui_scale as u
from gui.resource_paths import resource_path
from gui.widgets.common.styled_combo import VintageComboBox
from gui.widgets.install_firmware.common.pill_label import PillLabel

_USB_SVG = resource_path("USB.svg")
_USB_GLYPH_COLOR = "#fff4e6"


def _paint_usb_connection_icon(size: int) -> QtGui.QPixmap:
    """Orange badge with the USB.svg resource (cream-tinted)."""
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
    p.end()

    inset = size * 0.16
    glyph_size = int(size - 2 * inset)
    glyph = QtGui.QPixmap(glyph_size, glyph_size)
    glyph.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QtSvg.QSvgRenderer(str(_USB_SVG))
    gp = QtGui.QPainter(glyph)
    gp.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(gp, QtCore.QRectF(glyph.rect()))
    gp.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    gp.fillRect(glyph.rect(), QtGui.QColor(_USB_GLYPH_COLOR))
    gp.end()

    out = QtGui.QPixmap(size, size)
    out.fill(QtCore.Qt.GlobalColor.transparent)
    op = QtGui.QPainter(out)
    op.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    op.drawPixmap(0, 0, pix)
    op.drawPixmap(int(inset), int(inset), glyph)
    op.end()
    return out


def _banner_btn_style(*, primary: bool = False) -> str:
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
                padding: 0 {u.px(8)}px;
                font-size: {u.px(t.IF_DEVICE_BTN_FONT)}px;
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
            padding: 0 {u.px(8)}px;
            font-size: {u.px(t.IF_DEVICE_BTN_FONT)}px;
            font-weight: 800;
        }}
        QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; }}
        QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; }}
    """


class ConnectionSection(QtWidgets.QFrame):
    scan_clicked = pyqtSignal()
    connect_clicked = pyqtSignal()
    reset_clicked = pyqtSignal()

    def __init__(self, *, compact: bool = True, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._compact = compact
        self._meta_text = ""
        self._build()

    @property
    def port_combo(self) -> VintageComboBox:
        return self._port_combo

    @property
    def scan_btn(self) -> QtWidgets.QPushButton:
        return self._scan_btn

    @property
    def connect_btn(self) -> QtWidgets.QPushButton:
        return self._connect_btn

    @property
    def reset_btn(self) -> QtWidgets.QPushButton:
        return self._reset_btn

    @property
    def status_label(self) -> QtWidgets.QLabel:
        """Legacy alias — meta line is hidden; pill shows connection state."""
        return self._meta

    @property
    def status_pill(self) -> PillLabel:
        return self._status_pill

    def set_connected(self, connected: bool) -> None:
        if connected:
            self._status_pill.setText("Connected")
            self._status_pill.apply_variant("status_on")
        else:
            self._status_pill.setText("Not connected")
            self._status_pill.apply_variant("status_off")

    def set_meta_text(self, text: str) -> None:
        """Port / error detail — tooltip only (no inline hint label)."""
        self._meta_text = text or ""
        self._meta.setText(self._meta_text)
        tip = self._meta_text.strip()
        self._status_pill.setToolTip(tip)
        self._port_combo.setToolTip(tip)

    def _sync_layout(self) -> None:
        m = u.device_banner_layout(control_height=t.TOOLS_DEBUG_BTN_H)
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(m["pad_h"], m["pad_v"], m["pad_h"], m["pad_v"])
            lay.setSpacing(m["gap"])
        self.setFixedHeight(m["height"])

        icon_sz = m["icon_h"]
        self._icon_wrap.setFixedSize(icon_sz, icon_sz)
        self._icon_wrap.setPixmap(_paint_usb_connection_icon(icon_sz))
        self._icon_wrap.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_DEVICE_ICON_TOP}, stop:1 {t.IF_DEVICE_ICON_BOT}
            );
            border-radius: {u.px(t.IF_DEVICE_ICON_RADIUS)}px;
        """)

        self._port_combo.setMaximumWidth(QtWidgets.QWIDGETSIZE_MAX)
        self._port_combo.set_layout_min_width(t.TOOLS_CONN_COMBO_MIN_W)
        self._port_combo.apply_theme()

        btn_h = m["btn_h"]
        min_btn = t.TOOLS_DEBUG_BTN_W if self._compact else t.IF_DEVICE_BTN_W
        for btn, primary in (
            (self._scan_btn, False),
            (self._connect_btn, True),
            (self._reset_btn, False),
        ):
            btn.setFixedHeight(btn_h)
            btn.setFixedWidth(u.action_button_width(btn, min_btn, h_pad=16))
            btn.setStyleSheet(_banner_btn_style(primary=primary))

    def _build(self) -> None:
        self.setObjectName("toolsConnectionBanner")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_banner_style()

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 4)
        shadow.setColor(QtGui.QColor(75, 43, 18, 33))
        self.setGraphicsEffect(shadow)

        m = u.device_banner_layout(control_height=t.TOOLS_DEBUG_BTN_H)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(m["pad_h"], m["pad_v"], m["pad_h"], m["pad_v"])
        row.setSpacing(m["gap"])
        self.setFixedHeight(m["height"])

        self._icon_wrap = QtWidgets.QLabel()
        self._icon_wrap.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        icon_sz = m["icon_h"]
        self._icon_wrap.setFixedSize(icon_sz, icon_sz)
        self._icon_wrap.setPixmap(_paint_usb_connection_icon(icon_sz))
        self._icon_wrap.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_DEVICE_ICON_TOP}, stop:1 {t.IF_DEVICE_ICON_BOT}
            );
            border-radius: {u.px(t.IF_DEVICE_ICON_RADIUS)}px;
        """)
        row.addWidget(self._icon_wrap)

        self._title = QtWidgets.QLabel("Device Connection")
        self._title.setStyleSheet(
            f"color:{t.IF_DEVICE_TITLE_FG}; font-size:{u.px(t.IF_DEVICE_TITLE_SIZE)}px; font-weight:800;"
        )
        self._title.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        row.addWidget(self._title)

        self._status_pill = PillLabel("Not connected", variant="status_off")
        row.addWidget(self._status_pill)

        combo_h = t.TOOLS_DEBUG_BTN_H if self._compact else t.LIBBAR_COMBO_H
        self._port_combo = VintageComboBox(
            min_width=t.TOOLS_CONN_COMBO_MIN_W,
            fixed_height=combo_h,
        )
        self._port_combo.setEditable(True)
        self._port_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        row.addWidget(self._port_combo, 1)

        self._scan_btn = QtWidgets.QPushButton("Scan" if self._compact else "Scan Ports")
        self._scan_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._scan_btn.clicked.connect(self.scan_clicked.emit)
        row.addWidget(self._scan_btn)

        self._connect_btn = QtWidgets.QPushButton("Connect")
        self._connect_btn.setObjectName("deviceDebugPrimaryBtn")
        self._connect_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._connect_btn.clicked.connect(self.connect_clicked.emit)
        row.addWidget(self._connect_btn)

        reset_label = "Reset" if self._compact else "Reset Connection"
        self._reset_btn = QtWidgets.QPushButton(reset_label)
        self._reset_btn.setToolTip(
            "Forcefully reset connection (useful if device is stuck or frozen)"
        )
        self._reset_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._reset_btn.clicked.connect(self.reset_clicked.emit)
        row.addWidget(self._reset_btn)

        # Hidden — kept for device_debug.connection_status compatibility.
        self._meta = QtWidgets.QLabel("")
        self._meta.setVisible(False)

        self._sync_layout()

    def _apply_banner_style(self) -> None:
        self.setStyleSheet(f"""
            #toolsConnectionBanner {{
                border: 1px solid {t.IF_DEVICE_BANNER_BORDER};
                border-radius: {u.px(t.IF_DEVICE_ICON_RADIUS)}px;
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
        self._status_pill.reload_theme()
        self._sync_layout()
