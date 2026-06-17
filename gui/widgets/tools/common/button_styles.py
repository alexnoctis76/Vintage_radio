"""Shared button styles for the Tools page."""

from __future__ import annotations

import gui.theme as t
from gui import ui_scale as u


def tools_outline_btn_style(*, min_h: int = t.IF_DEVICE_BTN_H) -> str:
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
            padding: 0 14px;
            font-size: {u.px(t.IF_DEVICE_BTN_FONT)}px;
            font-weight: 800;
            min-height: {u.px(min_h)}px;
            outline: none;
        }}
        QPushButton:hover   {{ background: {t.LIGHT_BTN_HOVER}; border: 2px solid {t.LM_SD_BTN_BORDER}; }}
        QPushButton:pressed {{ background: {t.LIGHT_BTN_PRESSED}; border: 2px solid {t.LM_SD_BTN_BORDER}; }}
        QPushButton:focus   {{ outline: none; border: 2px solid {t.LM_SD_BTN_BORDER}; }}
        QPushButton:disabled {{ color: #9a8878; }}
    """


def tools_primary_btn_style(*, min_h: int = t.IF_DEVICE_BTN_H) -> str:
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
            padding: 0 14px;
            font-size: {u.px(t.IF_DEVICE_BTN_FONT)}px;
            font-weight: 800;
            min-height: {u.px(min_h)}px;
        }}
        QPushButton:hover   {{ background: {t.IF_INSTALL_BTN_MID}; }}
        QPushButton:pressed {{ background: {t.IF_INSTALL_BTN_BOT}; }}
        QPushButton:disabled {{ color: rgba(255,255,255,0.55); }}
    """
