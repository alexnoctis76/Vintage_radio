"""Shared vintage styling for context menus and system-style dialogs."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u

_POPUP_MARKER = "/* vintage-popup-styles */"
_RENDER_MARKER = "/* vintage-render-fixes */"


def vintage_rendering_fix_stylesheet() -> str:
    """Suppress native focus chrome and stacked-page seam lines on Windows."""
    return f"""
        QPushButton, QToolButton {{
            outline: none;
            margin: 0px;
        }}
        QPushButton:focus, QToolButton:focus {{
            outline: none;
        }}
        QStackedWidget {{
            background-color: {t.C_BG};
            border: none;
        }}
        #appRoot, #rightPane {{
            background-color: {t.C_BG};
        }}
        QToolTip {{
            background-color: {t.TOOLTIP_BG};
            color: {t.TOOLTIP_FG};
            border: 1px solid {t.TOOLTIP_BORDER};
            border-radius: {u.px(t.TOOLTIP_RADIUS)}px;
            padding: {u.px(t.TOOLTIP_PAD_V)}px {u.px(t.TOOLTIP_PAD_H)}px;
            font-size: {u.px(t.TOOLTIP_FONT_PX)}px;
        }}
    """


def configure_vintage_app_rendering(app: QtWidgets.QApplication) -> None:
    """Use Fusion (QSS-friendly) and round HiDPI sizes to whole pixels."""
    try:
        from PyQt6.QtWidgets import QStyleFactory

        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            app.setStyle(fusion)
        else:
            app.setStyle("Fusion")
    except Exception:
        try:
            app.setStyle("Fusion")
        except Exception:
            pass
    configure_vintage_tooltip_palette(app)


def tooltip_stylesheet() -> str:
    """QSS for QTipLabel instances (tooltips on dark panels ignore app-level QToolTip rules)."""
    return f"""
        QLabel {{
            background-color: {t.TOOLTIP_BG};
            color: {t.TOOLTIP_FG};
            border: 1px solid {t.TOOLTIP_BORDER};
            border-radius: {u.px(t.TOOLTIP_RADIUS)}px;
            padding: {u.px(t.TOOLTIP_PAD_V)}px {u.px(t.TOOLTIP_PAD_H)}px;
            font-size: {u.px(t.TOOLTIP_FONT_PX)}px;
        }}
    """


def configure_vintage_tooltip_palette(app: QtWidgets.QApplication) -> None:
    """Force readable tooltip colours (Windows may ignore QSS without palette)."""
    pal = app.palette()
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor(t.TOOLTIP_BG))
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor(t.TOOLTIP_FG))
    app.setPalette(pal)


def apply_widget_tooltip_palette(widget: QtWidgets.QWidget) -> None:
    """Ensure tooltips from this widget use vintage colours (dark headers invert otherwise)."""
    pal = widget.palette()
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor(t.TOOLTIP_BG))
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor(t.TOOLTIP_FG))
    widget.setPalette(pal)


class _VintageTooltipFilter(QtCore.QObject):
    """Style QTipLabel on show — fixes black tooltips from widgets on dark panel headers."""

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Show:
            if watched.metaObject().className() == "QTipLabel":
                w = watched  # type: ignore[assignment]
                w.setStyleSheet(tooltip_stylesheet())
                w.setAutoFillBackground(True)
                apply_widget_tooltip_palette(w)
        return super().eventFilter(watched, event)


def install_vintage_tooltip_filter(app: Optional[QtWidgets.QApplication] = None) -> None:
    if app is None:
        app = QtWidgets.QApplication.instance()
    if app is None:
        return
    filt = getattr(app, "_vintage_tooltip_filter", None)
    if filt is None:
        filt = _VintageTooltipFilter(app)
        app.installEventFilter(filt)
        app._vintage_tooltip_filter = filt  # type: ignore[attr-defined]


def vintage_combo_popup_stylesheet() -> str:
    """QSS for QComboBox dropdown lists (popup is a separate top-level window)."""
    return f"""
        QListView, QComboBox QAbstractItemView, QAbstractItemView {{
            background-color: {t.COMBO_LIST_BG};
            color: {t.TEXT_PRI};
            border: 1px solid {t.BORDER};
            border-radius: {t.LIBBAR_COMBO_RADIUS}px;
            padding: 4px 0;
            selection-background-color: {t.TRACK_SEL};
            selection-color: {t.TEXT_PRI};
            outline: none;
        }}
        QListView::item, QAbstractItemView::item {{
            padding: 6px 12px;
            min-height: 28px;
            color: {t.TEXT_PRI};
        }}
        QListView::item:selected, QAbstractItemView::item:selected {{
            background-color: {t.TRACK_SEL};
            color: {t.TEXT_PRI};
        }}
        QListView::item:hover, QAbstractItemView::item:hover {{
            background-color: {t.LIGHT_BTN_HOVER};
            color: {t.TEXT_PRI};
        }}
    """


def vintage_popup_stylesheet() -> str:
    """Application-wide QSS for QMenu, QMessageBox, QInputDialog, and plain QDialog."""
    return f"""
        QMenu {{
            background-color: {t.POPUP_MENU_BG};
            border: 1px solid {t.POPUP_MENU_BORDER};
            border-radius: {t.POPUP_MENU_RADIUS}px;
            padding: {t.POPUP_MENU_PAD}px;
            color: {t.POPUP_MENU_FG};
            font-size: {u.px(t.IF_DEVICE_META_SIZE + 1)}px;
        }}
        QMenu::item {{
            padding: {t.POPUP_MENU_ITEM_PAD_V}px {t.POPUP_MENU_ITEM_PAD_H}px;
            border-radius: 4px;
            background: transparent;
        }}
        QMenu::item:selected {{
            background-color: {t.POPUP_MENU_SEL_BG};
            color: {t.POPUP_MENU_SEL_FG};
        }}
        QMenu::separator {{
            height: 1px;
            background: {t.POPUP_MENU_SEP};
            margin: 4px 8px;
        }}

        QMessageBox, QInputDialog, QDialog {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.POPUP_DLG_BG_TOP},
                stop:1 {t.POPUP_DLG_BG_BOT}
            );
            color: {t.POPUP_MENU_FG};
        }}
        QMessageBox QLabel, QInputDialog QLabel, QDialog QLabel {{
            color: {t.POPUP_MENU_FG};
            background: transparent;
            font-size: {u.px(t.IF_DEVICE_META_SIZE + 1)}px;
        }}
        QMessageBox QLineEdit, QInputDialog QLineEdit,
        QMessageBox QTextEdit, QDialog QTextEdit,
        QMessageBox QPlainTextEdit, QDialog QPlainTextEdit,
        QInputDialog QComboBox, QDialog QComboBox,
        QInputDialog QSpinBox, QDialog QSpinBox {{
            background: {t.POPUP_DLG_INPUT_BG};
            color: {t.POPUP_DLG_INPUT_FG};
            border: 1px solid {t.POPUP_DLG_INPUT_BORDER};
            border-radius: {t.TOOLS_PATH_FIELD_RADIUS}px;
            padding: 4px 8px;
            selection-background-color: {t.POPUP_MENU_SEL_BG};
        }}
        QMessageBox QPushButton, QInputDialog QPushButton, QDialog QPushButton {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.POPUP_DLG_BTN_TOP},
                stop:1 {t.POPUP_DLG_BTN_BOT}
            );
            color: {t.POPUP_MENU_FG};
            border: 2px solid {t.POPUP_DLG_BTN_BORDER};
            border-radius: {t.POPUP_DLG_BTN_RADIUS}px;
            padding: 6px 16px;
            font-size: {u.px(t.IF_DEVICE_BTN_FONT)}px;
            font-weight: 700;
            min-height: {t.TOOLS_ACTION_BTN_H}px;
            outline: none;
        }}
        QMessageBox QPushButton:hover, QInputDialog QPushButton:hover, QDialog QPushButton:hover {{
            background: {t.LIGHT_BTN_HOVER};
            border: 2px solid {t.POPUP_DLG_BTN_BORDER};
        }}
        QMessageBox QPushButton:pressed, QInputDialog QPushButton:pressed, QDialog QPushButton:pressed {{
            background: {t.LIGHT_BTN_PRESSED};
            border: 2px solid {t.POPUP_DLG_BTN_BORDER};
        }}
        QMessageBox QPushButton:focus, QInputDialog QPushButton:focus, QDialog QPushButton:focus {{
            outline: none;
            border: 2px solid {t.POPUP_DLG_BTN_BORDER};
        }}
        QMessageBox QPushButton:default, QInputDialog QPushButton:default {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.POPUP_DLG_PRIMARY_TOP}, stop:0.58 {t.POPUP_DLG_PRIMARY_MID},
                stop:1 {t.POPUP_DLG_PRIMARY_BOT}
            );
            color: {t.POPUP_DLG_PRIMARY_FG};
            border: 2px solid {t.POPUP_DLG_PRIMARY_BORDER};
        }}
        QDialogButtonBox QPushButton {{
            min-width: 88px;
        }}
        QProgressBar {{
            border: 1px solid {t.POPUP_DLG_INPUT_BORDER};
            border-radius: {t.TOOLS_PATH_FIELD_RADIUS}px;
            background: {t.POPUP_DLG_INPUT_BG};
            text-align: center;
            color: {t.POPUP_MENU_FG};
        }}
        QProgressBar::chunk {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {t.POPUP_DLG_PRIMARY_TOP},
                stop:1 {t.POPUP_DLG_PRIMARY_BOT}
            );
            border-radius: 6px;
        }}

        {vintage_combo_popup_stylesheet()}
    """


def install_vintage_popup_styles(app: Optional[QtWidgets.QApplication] = None) -> None:
    """Apply vintage popup/dialog styling and rendering seam fixes application-wide."""
    if app is None:
        app = QtWidgets.QApplication.instance()
    if app is None:
        return
    configure_vintage_tooltip_palette(app)
    install_vintage_tooltip_filter(app)
    base = app.styleSheet() or ""
    for marker in (_POPUP_MARKER, _RENDER_MARKER):
        if marker in base:
            base = base.partition(marker)[0].rstrip()
    app.setStyleSheet(
        base
        + "\n"
        + _POPUP_MARKER
        + "\n"
        + vintage_popup_stylesheet()
        + "\n"
        + _RENDER_MARKER
        + "\n"
        + vintage_rendering_fix_stylesheet()
    )


def style_vintage_menu(menu: QtWidgets.QMenu) -> QtWidgets.QMenu:
    """Ensure a single QMenu instance uses vintage styling (fallback if global QSS missed)."""
    menu.setStyleSheet(vintage_popup_stylesheet())
    return menu


def create_vintage_menu(
    parent: Optional[QtWidgets.QWidget] = None,
) -> QtWidgets.QMenu:
    """Create a context menu with vintage styling."""
    menu = QtWidgets.QMenu(parent)
    style_vintage_menu(menu)
    return menu
