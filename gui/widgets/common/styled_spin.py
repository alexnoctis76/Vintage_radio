"""Themed QSpinBox matching Settings / Tools inputs."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets

import gui.theme as t
from gui import ui_scale as u


def _make_triangle_pixmap(*, up: bool, color: str, width: int = 10, height: int = 6) -> QtGui.QPixmap:
    if up:
        points = "5,1 1,6 9,6"
    else:
        points = "1,1 9,1 5,6"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 7">'
        f'<polygon points="{points}" fill="{color}"/>'
        f'</svg>'
    ).encode("utf-8")
    pix = QtGui.QPixmap(width, height)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg))
    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QtCore.QRectF(pix.rect()))
    painter.end()
    return pix


def vintage_spin_stylesheet() -> str:
    r = t.TOOLS_PATH_FIELD_RADIUS
    btn_w = u.px(t.SETTINGS_SPIN_BTN_W)
    pad_l = u.px(t.SETTINGS_SPIN_PAD_LEFT)
    pad_r = u.px(t.SETTINGS_SPIN_PAD_RIGHT)
    btn_h = u.px(t.TOOLS_ACTION_BTN_H)
    return f"""
        VintageSpinBox {{
            background: {t.TOOLS_INPUT_BG};
            color: {t.TOOLS_INPUT_FG};
            border: 1px solid {t.TOOLS_INPUT_BORDER};
            border-radius: {r}px;
            padding: 0 {pad_l}px;
            padding-right: {btn_w + pad_r}px;
            min-height: {btn_h}px;
            max-height: {btn_h}px;
            font-size: {u.px(t.SETTINGS_BODY_FONT_PX)}px;
        }}
        VintageSpinBox:focus {{
            border: 1px solid {t.BORDER};
        }}
        VintageSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: {btn_w}px;
            border: none;
            border-left: 1px solid {t.TOOLS_INPUT_BORDER};
            border-top-right-radius: {r}px;
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.SETTINGS_SPIN_BTN_TOP},
                stop:1 {t.SETTINGS_SPIN_BTN_BOT}
            );
        }}
        VintageSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: {btn_w}px;
            border: none;
            border-left: 1px solid {t.TOOLS_INPUT_BORDER};
            border-bottom-right-radius: {r}px;
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.SETTINGS_SPIN_BTN_TOP},
                stop:1 {t.SETTINGS_SPIN_BTN_BOT}
            );
        }}
        VintageSpinBox::up-button:hover, VintageSpinBox::down-button:hover {{
            background: {t.LIGHT_BTN_HOVER};
        }}
        VintageSpinBox::up-button:pressed, VintageSpinBox::down-button:pressed {{
            background: {t.LIGHT_BTN_PRESSED};
        }}
        VintageSpinBox::up-arrow, VintageSpinBox::down-arrow {{
            width: 0px;
            height: 0px;
            image: none;
        }}
    """


class VintageSpinBox(QtWidgets.QSpinBox):
    """Spin box with rounded field, SVG stepper arrows, and content-fit width."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        fit_to_content: bool = True,
        max_width: Optional[int] = None,
    ) -> None:
        super().__init__(parent)
        self._fit_to_content = fit_to_content
        self._max_width = max_width
        self._arrow_w = 10
        self._arrow_h = 6

        self._up_arrow = QtWidgets.QLabel(self)
        self._up_arrow.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._up_arrow.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter
        )

        self._down_arrow = QtWidgets.QLabel(self)
        self._down_arrow.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._down_arrow.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter
        )

        self.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.apply_theme()

        self.valueChanged.connect(self._on_content_changed)

    def apply_theme(self) -> None:
        self.setStyleSheet(vintage_spin_stylesheet())
        color = t.TEXT_PRI
        self._up_arrow.setPixmap(
            _make_triangle_pixmap(up=True, color=color, width=self._arrow_w, height=self._arrow_h)
        )
        self._down_arrow.setPixmap(
            _make_triangle_pixmap(up=False, color=color, width=self._arrow_w, height=self._arrow_h)
        )
        self._position_arrows()
        self._update_content_width()

    def setRange(self, minimum: int, maximum: int) -> None:
        super().setRange(minimum, maximum)
        self._update_content_width()

    def setSuffix(self, suffix: str) -> None:
        super().setSuffix(suffix)
        self._update_content_width()

    def setPrefix(self, prefix: str) -> None:
        super().setPrefix(prefix)
        self._update_content_width()

    def setMaximumWidth(self, max_width: int) -> None:  # noqa: A003 — Qt API name
        self._max_width = max_width
        self._update_content_width()

    def _on_content_changed(self, *_args) -> None:
        self._update_content_width()

    def _value_font_metrics(self) -> QtGui.QFontMetrics:
        font = QtGui.QFont(self.font())
        font.setPixelSize(u.px(t.SETTINGS_BODY_FONT_PX))
        return QtGui.QFontMetrics(font)

    def _formatted_samples(self) -> list[str]:
        samples = {self.minimum(), self.maximum(), self.value()}
        prefix = self.prefix()
        suffix = self.suffix()
        return [f"{prefix}{value}{suffix}" for value in samples]

    def _content_width(self) -> int:
        fm = self._value_font_metrics()
        chrome = (
            u.px(t.SETTINGS_SPIN_PAD_LEFT)
            + u.px(t.SETTINGS_SPIN_PAD_RIGHT)
            + u.px(t.SETTINGS_SPIN_BTN_W)
            + u.px(t.SETTINGS_SPIN_TEXT_SLACK)
        )
        text_w = max(fm.horizontalAdvance(text) for text in self._formatted_samples())
        return max(u.px(t.SETTINGS_SPIN_MIN_W), text_w + chrome)

    def _view_max_width(self) -> Optional[int]:
        """Widest sensible ancestor — cap only when layout has finished sizing."""
        if self._max_width is not None:
            return self._max_width

        best: Optional[int] = None
        widget: Optional[QtWidgets.QWidget] = self.parentWidget()
        while widget is not None:
            w = widget.width()
            if w >= t.SETTINGS_SPIN_VIEW_MIN_PX:
                candidate = w - t.SETTINGS_SPIN_LAYOUT_MARGIN
                if best is None or candidate > best:
                    best = candidate
            widget = widget.parentWidget()
        return best

    def _update_content_width(self) -> None:
        if not self._fit_to_content:
            return

        content_w = self._content_width()
        view_cap = self._view_max_width()
        if view_cap is None or view_cap >= content_w:
            width = content_w
        else:
            # View genuinely narrower than content (rare); still prefer readability.
            width = max(view_cap, t.SETTINGS_SPIN_MIN_W)

        self.setFixedWidth(width)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_arrows()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._position_arrows)
        QtCore.QTimer.singleShot(0, self._update_content_width)

    def _position_arrows(self) -> None:
        btn_w = t.SETTINGS_SPIN_BTN_W
        half_h = self.height() // 2
        cx = self.width() - btn_w
        aw, ah = self._arrow_w, self._arrow_h
        self._up_arrow.setGeometry(
            cx + (btn_w - aw) // 2,
            (half_h - ah) // 2,
            aw,
            ah,
        )
        self._down_arrow.setGeometry(
            cx + (btn_w - aw) // 2,
            half_h + (half_h - ah) // 2,
            aw,
            ah,
        )
