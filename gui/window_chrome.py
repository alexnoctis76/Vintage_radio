"""
Native window chrome helpers (caption colours, modal rounding).

Windows 11: custom brown caption via DWM.  Other platforms: no-op for caption.
"""

from __future__ import annotations

import sys
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t

# Windows 11+ DWM attributes (build 22000+)
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def _hex_to_colorref(hex_color: str) -> int:
    """Convert #RRGGBB to Win32 COLORREF (0x00BBGGRR)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return 0
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_native_caption_colors(
    window: QtWidgets.QWidget,
    *,
    background: Optional[str] = None,
    foreground: Optional[str] = None,
) -> bool:
    """Tint the OS title bar on Windows 11; dark caption fallback on Windows 10."""
    if sys.platform != "win32":
        return False

    try:
        hwnd = int(window.winId())
    except (TypeError, ValueError, AttributeError):
        return False
    if hwnd <= 0:
        return False

    bg = background or t.WIN_CAPTION_BG
    fg = foreground or t.WIN_CAPTION_FG

    try:
        import ctypes

        dwm = ctypes.windll.dwmapi
        user32 = ctypes.windll.user32
        caption = ctypes.c_int(_hex_to_colorref(bg))
        text = ctypes.c_int(_hex_to_colorref(fg))
        ok_cap = dwm.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_CAPTION_COLOR,
            ctypes.byref(caption),
            ctypes.sizeof(caption),
        )
        ok_txt = dwm.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_TEXT_COLOR,
            ctypes.byref(text),
            ctypes.sizeof(text),
        )
        if ok_cap != 0 or ok_txt != 0:
            dark = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(dark),
                ctypes.sizeof(dark),
            )
        applied = ok_cap == 0 and ok_txt == 0
        if applied:
            # Force the non-client frame to repaint with the new DWM colours immediately.
            _SWP_FRAMECHANGED = 0x0020
            _SWP_NOMOVE = 0x0002
            _SWP_NOSIZE = 0x0001
            _SWP_NOZORDER = 0x0004
            _SWP_NOACTIVATE = 0x0010
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED | _SWP_NOACTIVATE,
            )
        return applied
    except Exception:
        return False


def ensure_native_caption_colors(
    window: QtWidgets.QWidget,
    *,
    background: Optional[str] = None,
    foreground: Optional[str] = None,
) -> None:
    """Apply caption tint synchronously, then schedule retries for late HWND readiness."""
    apply_native_caption_colors(window, background=background, foreground=foreground)
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    apply_native_caption_colors(window, background=background, foreground=foreground)
    schedule_native_caption_colors(window, background=background, foreground=foreground)


def schedule_native_caption_colors(
    window: QtWidgets.QWidget,
    *,
    background: Optional[str] = None,
    foreground: Optional[str] = None,
) -> None:
    """Apply caption colours repeatedly until the native HWND accepts DWM tint."""
    delays = (0, 1, 16, 50, 150, 400, 800, 1200)

    def _try(delay_ms: int) -> None:
        def _run() -> None:
            apply_native_caption_colors(
                window,
                background=background,
                foreground=foreground,
            )

        QtCore.QTimer.singleShot(delay_ms, _run)

    for ms in delays:
        _try(ms)


class _CaptionColorFilter(QtCore.QObject):
    """Re-apply DWM caption tint when the window is shown or activated."""

    def __init__(self, window: QtWidgets.QWidget) -> None:
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self._window and event.type() in (
            QtCore.QEvent.Type.Show,
            QtCore.QEvent.Type.WindowActivate,
            QtCore.QEvent.Type.Polish,
        ):
            apply_native_caption_colors(self._window)
            if event.type() == QtCore.QEvent.Type.Show:
                schedule_native_caption_colors(self._window)
        return False


def install_caption_color_filter(window: QtWidgets.QWidget) -> None:
    """Ensure the brown title bar is applied on first paint, not only after focus changes."""
    filt = getattr(window, "_caption_color_filter", None)
    if filt is None:
        filt = _CaptionColorFilter(window)
        window.installEventFilter(filt)
        window._caption_color_filter = filt  # type: ignore[attr-defined]


class _ModalRoundMaskFilter(QtCore.QObject):
    """Clip a frameless dialog to SYNC_MDL_RADIUS rounded corners."""

    def __init__(self, dialog: QtWidgets.QDialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Show,
            QtCore.QEvent.Type.LayoutRequest,
        ):
            QtCore.QTimer.singleShot(0, self._apply)
        return False

    def _apply(self) -> None:
        r = t.SYNC_MDL_RADIUS
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self._dialog.rect()), r, r)
        poly = path.toFillPolygon()
        self._dialog.setMask(QtGui.QRegion(poly.toPolygon()))


def apply_modal_rounded_mask(dialog: QtWidgets.QDialog) -> None:
    """Install rounded-corner clipping on a frameless sync modal."""
    filt = _ModalRoundMaskFilter(dialog)
    dialog.installEventFilter(filt)
    dialog._modal_round_filter = filt  # type: ignore[attr-defined]
    QtCore.QTimer.singleShot(0, filt._apply)
