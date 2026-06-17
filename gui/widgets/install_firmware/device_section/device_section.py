"""Device banner matching gui/scratch.html .device-panel (compact height)."""



from __future__ import annotations



from typing import Optional



from PyQt6 import QtCore, QtGui, QtWidgets

from PyQt6.QtCore import pyqtSignal



import gui.theme as t
from gui import ui_scale as u

from gui.widgets.install_firmware.common.pill_label import PillLabel





def _device_btn_style(*, primary: bool = False) -> str:

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

            padding: 0 10px;

            font-size: {u.px(t.IF_DEVICE_BTN_FONT)}px;

            font-weight: 800;

        }}

        QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; }}

        QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; }}

    """





def _paint_device_chip_glyph(size: int) -> QtGui.QPixmap:
    """Chip + download glyph (transparent background)."""
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    pen = QtGui.QPen(QtGui.QColor("#fff4e6"))
    pen.setWidthF(max(1.8, size * 0.045))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    s = size / 64.0
    p.drawRoundedRect(QtCore.QRectF(18 * s, 14 * s, 28 * s, 36 * s), 4 * s, 4 * s)
    for px in (24, 32, 40):
        p.drawLine(QtCore.QPointF(px * s, 7 * s), QtCore.QPointF(px * s, 14 * s))
        p.drawLine(QtCore.QPointF(px * s, 50 * s), QtCore.QPointF(px * s, 57 * s))
    for py in (24, 32, 40):
        p.drawLine(QtCore.QPointF(10 * s, py * s), QtCore.QPointF(18 * s, py * s))
        p.drawLine(QtCore.QPointF(46 * s, py * s), QtCore.QPointF(54 * s, py * s))
    cx = 32 * s
    p.drawLine(QtCore.QPointF(cx, 20 * s), QtCore.QPointF(cx, 39 * s))
    p.drawLine(QtCore.QPointF(24 * s, 31 * s), QtCore.QPointF(cx, 39 * s))
    p.drawLine(QtCore.QPointF(40 * s, 31 * s), QtCore.QPointF(cx, 39 * s))
    p.end()
    return pix


def _paint_device_chip_icon(size: int) -> QtGui.QPixmap:
    """Chip + download glyph from scratch.html device-icon SVG (legacy flat pixmap)."""
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

    glyph = _paint_device_chip_glyph(int(size * 0.88))
    p.drawPixmap(int(size * 0.06), int(size * 0.06), glyph)
    p.end()
    return pix





class DeviceSection(QtWidgets.QFrame):

    refresh_clicked = pyqtSignal()

    choose_device_clicked = pyqtSignal()



    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:

        super().__init__(parent)

        self._build()



    @property

    def title_label(self) -> QtWidgets.QLabel:

        return self._title



    @property

    def status_pill(self) -> PillLabel:

        return self._status_pill



    @property

    def meta_label(self) -> QtWidgets.QLabel:

        return self._meta



    @property

    def choose_device_btn(self) -> QtWidgets.QPushButton:

        return self._choose_btn



    @property

    def refresh_btn(self) -> QtWidgets.QPushButton:

        return self._refresh_btn



    def set_detected(
        self,
        detected: bool,
        *,
        status_text: str | None = None,
        status_on: bool = True,
    ) -> None:

        if detected:

            self._status_pill.setText(status_text or "Connected")

            self._status_pill.apply_variant("status_on" if status_on else "status_off")

        else:

            self._status_pill.setText(status_text or "Not connected")

            self._status_pill.apply_variant("status_off")



    def set_meta_text(self, text: str) -> None:

        self._meta.setText(text)



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
        self._icon_wrap.setPixmap(_paint_device_chip_icon(icon_sz))
        self._icon_wrap.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_DEVICE_ICON_TOP}, stop:1 {t.IF_DEVICE_ICON_BOT}
            );
            border-radius: {u.px(t.IF_DEVICE_ICON_RADIUS)}px;
        """)

        btn_h = m["btn_h"]
        self._refresh_btn.setFixedSize(
            u.action_button_width(self._refresh_btn, t.IF_DEVICE_BTN_W), btn_h
        )
        self._choose_btn.setFixedSize(
            u.action_button_width(self._choose_btn, t.IF_DEVICE_BTN_W), btn_h
        )
        self._refresh_btn.setStyleSheet(_device_btn_style(primary=True))
        self._choose_btn.setStyleSheet(_device_btn_style())

    def _build(self) -> None:

        self.setObjectName("ifDeviceBanner")

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
        self._icon_wrap.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        icon_sz = u.px(t.IF_DEVICE_ICON)
        self._icon_wrap.setFixedSize(icon_sz, icon_sz)
        self._icon_wrap.setPixmap(_paint_device_chip_icon(icon_sz))
        self._icon_wrap.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_DEVICE_ICON_TOP}, stop:1 {t.IF_DEVICE_ICON_BOT}
            );
            border-radius: {u.px(t.IF_DEVICE_ICON_RADIUS)}px;
        """)

        lay.addWidget(self._icon_wrap, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)



        text_col = QtWidgets.QVBoxLayout()

        text_col.setSpacing(m["text_gap"])

        self._title = QtWidgets.QLabel("Waiting for device...")

        self._title.setWordWrap(False)

        self._title.setSizePolicy(

            QtWidgets.QSizePolicy.Policy.Expanding,

            QtWidgets.QSizePolicy.Policy.Preferred,

        )

        self._title.setStyleSheet(

            f"color:{t.IF_DEVICE_TITLE_FG}; font-size:{u.px(t.IF_DEVICE_TITLE_SIZE)}px; font-weight:800;"

        )

        text_col.addWidget(self._title)



        meta_row = QtWidgets.QHBoxLayout()

        meta_row.setSpacing(m["meta_gap"])

        self._status_pill = PillLabel("Not connected", variant="status_off")

        meta_row.addWidget(self._status_pill)

        self._meta = QtWidgets.QLabel("Plug in USB to detect your Pico.")

        self._meta.setStyleSheet(

            f"color:{t.IF_DEVICE_META_FG}; font-size:{u.px(t.IF_DEVICE_META_SIZE)}px;"

        )

        self._meta.setMinimumWidth(0)

        self._meta.setSizePolicy(

            QtWidgets.QSizePolicy.Policy.Ignored,

            QtWidgets.QSizePolicy.Policy.Preferred,

        )

        meta_row.addWidget(self._meta, 1)

        text_col.addLayout(meta_row)

        lay.addLayout(text_col, 1)



        self._refresh_btn = QtWidgets.QPushButton("Autodetect")

        self._refresh_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

        self._refresh_btn.setToolTip("Rescan USB ports and update device status.")

        self._refresh_btn.clicked.connect(self.refresh_clicked.emit)



        self._choose_btn = QtWidgets.QPushButton("Choose Device")

        self._choose_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

        self._choose_btn.setToolTip(

            "Pick a specific RP2040 serial port when more than one is connected."

        )

        self._choose_btn.clicked.connect(self.choose_device_clicked.emit)



        btn_box = QtWidgets.QHBoxLayout()

        btn_box.setSpacing(m["btn_gap"])

        btn_box.addWidget(self._refresh_btn)

        btn_box.addWidget(self._choose_btn)

        lay.addLayout(btn_box)



        self._sync_layout()

        self.set_detected(False)



    def _apply_banner_style(self) -> None:

        self.setStyleSheet(f"""

            #ifDeviceBanner {{

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
        self._meta.setStyleSheet(
            f"color:{t.IF_DEVICE_META_FG}; font-size:{u.px(t.IF_DEVICE_META_SIZE)}px;"
        )
        self._status_pill.reload_theme()
        self._sync_layout()
        detected = self._status_pill.text() == "Connected"
        self.set_detected(detected)


