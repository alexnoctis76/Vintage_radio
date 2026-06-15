"""Live viewer for the Vintage Radio session log file."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

import gui.theme as t
from gui import ui_scale as u
from gui.session_log import get_log_dir, get_session_log_path
from gui.widgets.common.mockup_scrollbar import wrap_with_mockup_scrollbar
from gui.widgets.dialogs.vintage_message import VintageMessageBox


def _inner_card_style() -> str:
    return f"""
        QFrame#toolsLogInnerCard {{
            border-radius: {t.IF_CARD_RADIUS}px;
            border: 1px solid {t.IF_CARD_BORDER};
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.IF_CARD_INNER_TOP}, stop:1 {t.IF_CARD_INNER_BOT}
            );
        }}
    """


def _path_field_style() -> str:
    return f"""
        QLineEdit#toolsLogPathField {{
            background: {t.TOOLS_INPUT_BG};
            color: {t.TOOLS_INPUT_FG};
            border: 1px solid {t.TOOLS_INPUT_BORDER};
            border-radius: {t.TOOLS_PATH_FIELD_RADIUS}px;
            padding: 0 12px;
            font-size: {u.px(t.IF_DEVICE_META_SIZE)}px;
            min-height: {u.px(t.TOOLS_ACTION_BTN_H)}px;
            max-height: {u.px(t.TOOLS_ACTION_BTN_H)}px;
        }}
    """


def _outline_action_btn_style() -> str:
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.OUTLINE_BTN_GRAD_TOP},
                stop:1 {t.OUTLINE_BTN_GRAD_BOT}
            );
            color: {t.TEXT_PRI};
            border: 2px solid {t.LM_SD_BTN_BORDER};
            border-radius: {t.LM_SD_BTN_RADIUS}px;
            padding: 0 14px;
            font-size: {u.px(t.TOOLS_ACTION_BTN_FONT)}px;
            font-weight: 800;
            min-height: {u.px(t.TOOLS_ACTION_BTN_H)}px;
            max-height: {u.px(t.TOOLS_ACTION_BTN_H)}px;
        }}
        QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; }}
        QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; }}
    """


def _editor_action_btn_style() -> str:
    return f"""
        QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.TOOLS_EDITOR_BTN_TOP}, stop:1 {t.TOOLS_EDITOR_BTN_BOT}
            );
            color: {t.IF_SW_BADGE_FG};
            border: 2px solid {t.TOOLS_EDITOR_BTN_BORDER};
            border-radius: {t.LM_SD_BTN_RADIUS}px;
            padding: 0 14px;
            font-size: {u.px(t.TOOLS_ACTION_BTN_FONT)}px;
            font-weight: 800;
            min-height: {u.px(t.TOOLS_ACTION_BTN_H)}px;
            max-height: {u.px(t.TOOLS_ACTION_BTN_H)}px;
        }}
        QPushButton:hover   {{ background: {t.TOOLS_EDITOR_BTN_TOP}; }}
        QPushButton:pressed {{ background: {t.TOOLS_EDITOR_BTN_BOT}; }}
    """


def _section_title_style() -> str:
    return (
        f"color:{t.IF_DEVICE_TITLE_FG}; "
        f"font-size:{u.px(t.TOOLS_SECTION_TITLE_PX)}px; font-weight:800;"
    )


def _paint_section_icon(*, variant: str) -> QtGui.QPixmap:
    size = t.TOOLS_SECTION_ICON
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    grad = QtGui.QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0, QtGui.QColor(t.IF_DEVICE_ICON_TOP))
    grad.setColorAt(1, QtGui.QColor(t.IF_DEVICE_ICON_BOT))
    p.setBrush(grad)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    r = t.IF_DEVICE_ICON_RADIUS * size // t.IF_DEVICE_ICON
    p.drawRoundedRect(QtCore.QRectF(0, 0, size, size), r, r)

    pen = QtGui.QPen(QtGui.QColor("#fff6ea"))
    pen.setWidthF(max(1.4, size * 0.06))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    s = size / 28.0

    if variant == "document":
        p.drawRoundedRect(QtCore.QRectF(8 * s, 5 * s, 12 * s, 17 * s), 2 * s, 2 * s)
        p.drawLine(QtCore.QPointF(11 * s, 10 * s), QtCore.QPointF(17 * s, 10 * s))
        p.drawLine(QtCore.QPointF(11 * s, 14 * s), QtCore.QPointF(17 * s, 14 * s))
        p.drawLine(QtCore.QPointF(11 * s, 18 * s), QtCore.QPointF(15 * s, 18 * s))
    else:
        for y in (8, 13, 18):
            p.drawLine(QtCore.QPointF(8 * s, y * s), QtCore.QPointF(20 * s, y * s))
        p.drawLine(QtCore.QPointF(8 * s, 8 * s), QtCore.QPointF(8 * s, 18 * s))
        p.drawLine(QtCore.QPointF(13 * s, 8 * s), QtCore.QPointF(13 * s, 18 * s))

    p.end()
    return pix


def _make_section_header(title: str, *, icon_variant: str) -> QtWidgets.QWidget:
    row = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)

    icon = QtWidgets.QLabel()
    icon.setFixedSize(t.TOOLS_SECTION_ICON, t.TOOLS_SECTION_ICON)
    icon.setPixmap(_paint_section_icon(variant=icon_variant))
    lay.addWidget(icon)

    label = QtWidgets.QLabel(title)
    label.setStyleSheet(_section_title_style())
    lay.addWidget(label)
    lay.addStretch(1)
    return row


class SessionLogsPanel(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._tail_pos = 0
        self._build()
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(1200)
        self._poll.timeout.connect(self._refresh_tail)
        self._poll.start()
        self._refresh_full()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self._refresh_tail()

    def _build(self) -> None:
        self.setObjectName("toolsSessionLogsPanel")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_panel_style()

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(
            t.TOOLS_PANEL_PAD, t.TOOLS_PANEL_PAD, t.TOOLS_PANEL_PAD, t.TOOLS_PANEL_PAD
        )
        root.setSpacing(t.TOOLS_SECTION_GAP)

        root.addWidget(self._build_session_log_card())
        root.addWidget(self._build_log_viewer_card(), 1)

    def _build_session_log_card(self) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("toolsLogInnerCard")
        card.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_inner_card_style())

        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        lay.addWidget(_make_section_header("Session Log", icon_variant="document"))

        path_row = QtWidgets.QHBoxLayout()
        path_row.setSpacing(8)

        self._path_field = QtWidgets.QLineEdit()
        self._path_field.setObjectName("toolsLogPathField")
        self._path_field.setReadOnly(True)
        self._path_field.setPlaceholderText("No session log for this run yet.")
        self._path_field.setStyleSheet(_path_field_style())
        path_row.addWidget(self._path_field, 1)

        self._refresh_btn = QtWidgets.QPushButton("Refresh")
        self._open_btn = QtWidgets.QPushButton("Open in Editor")
        self._copy_btn = QtWidgets.QPushButton("Copy Path")
        self._folder_btn = QtWidgets.QPushButton("Open Log Folder")

        for btn in (self._refresh_btn, self._copy_btn, self._folder_btn):
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(_outline_action_btn_style())
        self._open_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._open_btn.setStyleSheet(_editor_action_btn_style())

        self._refresh_btn.clicked.connect(self._refresh_full)
        self._open_btn.clicked.connect(self._open_in_editor)
        self._copy_btn.clicked.connect(self._copy_path)
        self._folder_btn.clicked.connect(self._open_log_folder)

        for btn in (self._refresh_btn, self._open_btn, self._copy_btn, self._folder_btn):
            path_row.addWidget(btn, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(path_row)
        return card

    def _build_log_viewer_card(self) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("toolsLogInnerCard")
        card.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_inner_card_style())
        card.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        lay.addWidget(_make_section_header("Log Viewer", icon_variant="list"))

        self._viewer = QtWidgets.QPlainTextEdit()
        self._viewer.setObjectName("toolsLogViewer")
        self._viewer.setReadOnly(True)
        self._viewer.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self._viewer.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._viewer.setFont(QtGui.QFont("Consolas", u.px(t.TOOLS_LOG_FONT)))
        self._apply_viewer_style()
        self._viewer_scroll_wrap = wrap_with_mockup_scrollbar(
            self._viewer,
            variant="station",
        )
        lay.addWidget(self._viewer_scroll_wrap, 1)
        return card

    def _apply_viewer_style(self) -> None:
        self._viewer.setStyleSheet(f"""
            QPlainTextEdit#toolsLogViewer {{
                background: {t.TOOLS_CONSOLE_BG};
                color: {t.TOOLS_CONSOLE_FG};
                border: 1px solid {t.TOOLS_CONSOLE_BORDER};
                border-radius: {t.TOOLS_PATH_FIELD_RADIUS}px;
                padding: 10px;
            }}
        """)
        pal = self._viewer.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(t.TOOLS_CONSOLE_FG))
        pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(t.TOOLS_CONSOLE_BG))
        self._viewer.setPalette(pal)

    def _log_path(self) -> Optional[Path]:
        p = get_session_log_path()
        return p if p and p.is_file() else None

    def _apply_panel_style(self) -> None:
        self.setStyleSheet(f"""
            #toolsSessionLogsPanel {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t.TOOLS_PANEL_TOP}, stop:1 {t.TOOLS_PANEL_BOT}
                );
                border: 1px solid {t.TOOLS_PANEL_BORDER};
                border-top: none;
                border-bottom-left-radius: {t.TOOLS_PANEL_RADIUS}px;
                border-bottom-right-radius: {t.TOOLS_PANEL_RADIUS}px;
            }}
        """)

    def _refresh_full(self) -> None:
        path = self._log_path()
        if path is None:
            self._path_field.clear()
            self._path_field.setPlaceholderText("No session log for this run yet.")
            self._viewer.setPlainText("")
            self._tail_pos = 0
            return
        self._path_field.setText(str(path))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._viewer.setPlainText(f"Could not read log: {exc}")
            self._tail_pos = 0
            return
        self._viewer.setPlainText(text)
        self._tail_pos = path.stat().st_size
        sb = self._viewer.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _refresh_tail(self) -> None:
        path = self._log_path()
        if path is None:
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size < self._tail_pos:
            self._refresh_full()
            return
        if size == self._tail_pos:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self._tail_pos)
                chunk = handle.read()
        except OSError:
            return
        if chunk:
            at_bottom = self._viewer.verticalScrollBar().value() >= (
                self._viewer.verticalScrollBar().maximum() - 24
            )
            cursor = self._viewer.textCursor()
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
            cursor.insertText(chunk)
            self._tail_pos = size
            if at_bottom:
                sb = self._viewer.verticalScrollBar()
                sb.setValue(sb.maximum())

    def _open_in_editor(self) -> None:
        path = self._log_path()
        if path is None:
            VintageMessageBox.information(
                self, "Session Log", "No session log found for this session."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _copy_path(self) -> None:
        path = self._log_path()
        if path is None:
            return
        QtWidgets.QApplication.clipboard().setText(str(path))

    def _open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_log_dir())))

    def reload_theme(self) -> None:
        self._apply_panel_style()
        for card in self.findChildren(QtWidgets.QFrame, "toolsLogInnerCard"):
            card.setStyleSheet(_inner_card_style())
        self._path_field.setStyleSheet(_path_field_style())
        self._apply_viewer_style()
        self._viewer.setFont(QtGui.QFont("Consolas", u.px(t.TOOLS_LOG_FONT)))
        self._refresh_btn.setStyleSheet(_outline_action_btn_style())
        self._copy_btn.setStyleSheet(_outline_action_btn_style())
        self._folder_btn.setStyleSheet(_outline_action_btn_style())
        self._open_btn.setStyleSheet(_editor_action_btn_style())
