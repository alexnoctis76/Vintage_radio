"""Interface zoom — scale pixel sizes derived from theme tokens."""

from __future__ import annotations

ZOOM_PERCENT = 100


def set_zoom_percent(value: int) -> None:
    """Set global UI zoom (80–200). Used by Settings and the status-bar controls."""
    global ZOOM_PERCENT
    ZOOM_PERCENT = max(80, min(200, int(value)))


def px(base: float) -> int:
    """Scale a design-time pixel value for the current zoom level."""
    return max(1, int(round(float(base) * ZOOM_PERCENT / 100)))


def px_layout(base: float, *, above_100_factor: float = 0.5) -> int:
    """Scale layout-critical widths; grows slower above 100% zoom to reduce crowding."""
    z = ZOOM_PERCENT
    if z <= 100:
        return px(base)
    factor = 100.0 + (z - 100.0) * above_100_factor
    return max(1, int(round(float(base) * factor / 100)))


def banner_compact() -> bool:
    """True when horizontal toolbars should drop non-essential chrome (icon, long labels)."""
    return ZOOM_PERCENT >= 175


def banner_stacked() -> bool:
    """True when device/storage banners should use a second row for controls."""
    return ZOOM_PERCENT >= 130


def connection_banner_height(*, stacked: bool, control_height: float | None = None) -> int:
    """Row height for the Tools device-connection banner."""
    import gui.theme as t

    m = device_banner_layout(control_height=control_height)
    if not stacked:
        return m["height"]
    title_h = px(t.IF_DEVICE_TITLE_SIZE) + px(8)
    controls_h = max(
        m["btn_h"],
        px(t.IF_STATUS_PILL_H) + 2 * px(t.IF_STATUS_PILL_PAD_V) + px(4),
    )
    return m["pad_v"] * 2 + title_h + m["gap"] + controls_h


def pt(base: float) -> int:
    """Scale a design-time point size (same ratio as :func:`px`)."""
    return max(1, int(round(float(base) * ZOOM_PERCENT / 100)))


def fs(base: float) -> str:
    """CSS ``font-size`` value scaled for the current zoom level."""
    return f"{px(base)}px"


def device_banner_layout(*, control_height: float | None = None) -> dict[str, int]:
    """Scaled padding, spacing, and row height for device / storage / connection banners."""
    import gui.theme as t

    ch = float(control_height if control_height is not None else t.IF_DEVICE_BTN_H)
    pad_h = px(t.IF_DEVICE_BANNER_PAD_H)
    pad_v = px(t.IF_DEVICE_BANNER_PAD_V)
    gap = px(t.IF_DEVICE_ROW_GAP)
    btn_h = px(ch)
    icon_h = px(t.IF_DEVICE_ICON)
    title_h = px(t.IF_DEVICE_TITLE_SIZE + 4)
    meta_h = max(px(t.IF_STATUS_PILL_H + 2), px(t.IF_DEVICE_META_SIZE + 2))
    text_h = title_h + px(2) + meta_h
    height = max(px(t.IF_DEVICE_BANNER_H), max(btn_h, icon_h, text_h) + 2 * pad_v)
    return {
        "pad_h": pad_h,
        "pad_v": pad_v,
        "gap": gap,
        "height": height,
        "btn_h": btn_h,
        "icon_h": icon_h,
        "meta_gap": px(8),
        "btn_gap": px(8),
        "text_gap": px(2),
    }


def action_button_width(btn, min_design_w: float, *, h_pad: float = 24) -> int:
    """Button width from label at current zoom; avoids oversized fixed widths when zoomed."""
    from PyQt6 import QtGui

    fm = QtGui.QFontMetrics(btn.font())
    return max(px_layout(min_design_w), fm.horizontalAdvance(btn.text()) + px(h_pad))
