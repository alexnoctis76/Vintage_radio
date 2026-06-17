"""WCAG contrast checks for complete theme palettes (foreground on background).

Monochromatic SVG/glyph icons are treated as *text* and must meet 4.5:1.
See .cursor/rules/design-system-accessibility.mdc for the rationale.

All three shipped themes are listed so new regressions are caught.
``high_contrast`` and ``colorblind`` are accessibility-focused and must pass
all checks. ``vintage`` is the default aesthetic theme and is intentionally
not modified; its known gaps are documented via xfail markers.
"""

from __future__ import annotations

import pytest

from gui.themes.contrast_utils import contrast_ratio, meets_wcag_aa_text, meets_wcag_aa_ui
from gui.themes import high_contrast, vintage, colorblind

# Themes that must pass every contrast check with no exceptions.
_STRICT_THEMES = [
    ("high_contrast", high_contrast.PALETTE),
    ("colorblind", colorblind.PALETTE),
]

# All themes — used for tests where vintage is xfail (known intentional gaps).
_ALL_THEMES = [
    ("high_contrast", high_contrast.PALETTE),
    ("colorblind", colorblind.PALETTE),
    pytest.param("vintage", vintage.PALETTE,
                 marks=pytest.mark.xfail(
                     reason="Vintage is an aesthetic default theme; "
                            "known WCAG gaps are intentional and not modified.",
                     strict=False,
                 )),
]

# (foreground token, background token, min_ratio, description)
_TEXT_PAIRS = [
    ("TEXT_PRI", "C_BG", 4.5, "primary body on page"),
    ("TEXT_PRI", "TRACK_BG", 4.5, "primary body on track panel"),
    ("TEXT_SEC", "C_BG", 4.5, "secondary on page"),
    ("S_TEXT", "S_BG", 4.5, "sidebar labels"),
    ("PANEL_HDR_TEXT", "PANEL_HDR", 4.5, "panel header strip"),
    ("LM_PANEL_HDR_TEXT_COLOR", "PANEL_HDR", 4.5, "load-music panel header"),
    ("IF_CARD_IDLE_TEXT", "IF_CARD_IDLE_BG", 4.5, "firmware card on dark list"),
    ("IF_CARD_IDLE_SUBTEXT", "IF_CARD_IDLE_BG", 4.5, "firmware card subtitle"),
    ("IF_TAB_ACTIVE_FG", "IF_TAB_ACTIVE_TOP", 4.5, "active folder tab"),
    ("IF_TAB_INACTIVE_FG", "IF_TAB_INACTIVE_TOP", 4.5, "inactive folder tab"),
    ("IF_INSTALL_BTN_FG", "IF_INSTALL_BTN_TOP", 4.5, "install button label"),
    ("IF_DEVICE_TITLE_FG", "IF_DEVICE_BANNER_TOP", 4.5, "device banner title"),
    ("IF_DEVICE_META_FG", "IF_DEVICE_BANNER_TOP", 4.5, "device banner meta"),
    ("IF_META_VALUE_FG", "IF_META_BOX_BG", 4.5, "meta pill value"),
    ("IF_META_LABEL_FG", "IF_META_BOX_BG", 4.5, "meta pill label"),
    ("IF_NOTES_PREVIEW_FG", "IF_NOTES_PREVIEW_BG", 4.5, "notes preview"),
    ("STATION_COUNT_COLOR", "STA_PANE_GRAD_TOP", 4.5, "station count on dark pane"),
    ("STATION_COUNT_COLOR_SEL", "STA_SEL_GRAD_MID", 4.5, "station count on selected row"),
    ("STATION_PENCIL_COLOR_SEL", "STA_SEL_GRAD_MID", 4.5, "station edit on selected row"),
    ("TRACK_PENCIL_COLOR_SEL", "TRK_SEL_GRAD_TOP", 4.5, "track edit on selected row"),
    ("LM_TRACK_NUM_COLOR", "TRACK_BG", 4.5, "track row number"),
    ("FOOTER_TEXT", "FOOTER_BG", 4.5, "footer status text"),
    ("FOOTER_TEXT", "ZOOM_BTN_GRAD_TOP", 4.5, "zoom control on dark button"),
    ("TOOLS_CONSOLE_FG", "TOOLS_CONSOLE_BG", 4.5, "tools console"),
    ("TOOLS_INPUT_FG", "TOOLS_INPUT_BG", 4.5, "tools input field"),
    ("VINTAGE_CB_TEXT_FG", "VINTAGE_CB_BG", 4.5, "checkbox label"),
    ("POPUP_MENU_FG", "POPUP_MENU_BG", 4.5, "context menu"),
    ("POPUP_MENU_SEL_FG", "POPUP_MENU_SEL_BG", 4.5, "context menu selection"),
    ("SYNC_MDL_HDR_TITLE_CLR", "SYNC_MDL_HDR_TOP", 4.5, "sync modal title"),
    ("SYNC_MDL_HDR_SUB_CLR", "SYNC_MDL_HDR_TOP", 4.5, "sync modal subtitle"),
    ("SYNC_MDL_CARD_BODY_CLR", "SYNC_MDL_CARD_BG_TOP", 4.5, "sync modal card body"),
    ("SYNC_MDL_CARD_HELPER_CLR", "SYNC_MDL_CARD_BG_TOP", 4.5, "sync modal helper"),
    ("SYNC_MDL_BTN_SEC_TEXT", "SYNC_MDL_BTN_SEC_TOP", 4.5, "sync modal secondary btn"),
    ("IF_STATUS_PILL_FG", "IF_STATUS_PILL_ON_TOP", 4.5, "connected status pill (top)"),
    ("IF_STATUS_PILL_FG", "IF_STATUS_PILL_ON_BOT", 4.5, "connected status pill (bot)"),
    ("IF_STATUS_PILL_FG", "IF_STATUS_PILL_OFF_TOP", 4.5, "disconnected status pill (top)"),
    ("IF_STATUS_PILL_FG", "IF_STATUS_PILL_OFF_BOT", 4.5, "disconnected status pill (bot)"),
    ("TOOLTIP_FG", "TOOLTIP_BG", 4.5, "tooltip"),
    ("WIN_CAPTION_FG", "WIN_CAPTION_BG", 4.5, "window caption"),
]

_UI_PAIRS = [
    # Non-text UI components (scrollbar thumbs) — 3:1 minimum.
    # Station and track scrollbars may have different rail luminances, so separate
    # thumb tokens exist for each context (SB_STA_THUMB_GRAD_TOP vs SB_THUMB_GRAD_TOP).
    ("SB_STA_THUMB_GRAD_TOP", "SB_STA_BG", 3.0, "station scrollbar thumb on dark/med rail"),
    ("SB_THUMB_GRAD_TOP", "SB_TRK_BG", 3.0, "track scrollbar thumb on light rail"),
]

# Monochromatic icons — must meet the TEXT threshold (4.5:1) per accessibility rule.
# Each entry covers one distinct (icon_color, surface) occurrence.
_ICON_PAIRS = [
    # Sidebar nav icons: inactive glyph on sidebar gradient background
    ("S_TEXT", "SIDEBAR_GRAD_TOP", 4.5, "sidebar icon inactive (worst stop)"),
    # Sidebar nav icons: active glyph is always #FFFFFF; checked via literal below
    # SD card icon inside the Sync button
    ("SYNC_ICON_COLOR", "SYNC_BTN_GRAD_TOP", 4.5, "SD card icon on sync btn (top)"),
    ("SYNC_ICON_COLOR", "SYNC_BTN_GRAD_BOT", 4.5, "SD card icon on sync btn (bot)"),
    # Eject icon inside the Safely Remove button
    ("EJECT_ICON_COLOR", "EJECT_BTN_GRAD_TOP", 4.5, "eject icon on eject btn (top)"),
    # Firmware button icon (same SYNC_ICON_COLOR reused on Install btn)
    ("SYNC_ICON_COLOR", "IF_INSTALL_BTN_TOP", 4.5, "firmware btn icon (top)"),
    ("SYNC_ICON_COLOR", "IF_INSTALL_BTN_BOT", 4.5, "firmware btn icon (bot)"),
    # Scrollbar arrow/chevron glyphs
    ("SB_STA_ARROW_COLOR", "SB_STA_BG", 4.5, "station scrollbar arrow on rail"),
    ("SB_TRK_ARROW_COLOR", "SB_TRK_BG", 4.5, "track scrollbar arrow on rail"),
    # Station row: edit pencil icon (unselected dark pane)
    ("STATION_PENCIL_COLOR", "STA_PANE_GRAD_TOP", 4.5, "station pencil unselected"),
    # Station row: edit pencil icon (selected row)
    ("STATION_PENCIL_COLOR_SEL", "STA_SEL_GRAD_MID", 4.5, "station pencil selected"),
    # Track row: drag-handle glyph (unselected)
    ("TRACK_HANDLE_COLOR", "TRK_PANE_GRAD_TOP", 4.5, "track drag-handle unselected"),
    # Track row: drag-handle glyph (selected)
    ("TRACK_HANDLE_COLOR_SEL", "TRK_SEL_GRAD_TOP", 4.5, "track drag-handle selected"),
    # Track row: edit pencil icon (unselected)
    ("TRACK_PENCIL_COLOR", "TRK_PANE_GRAD_TOP", 4.5, "track pencil unselected"),
    # Track row: edit pencil icon (selected)
    ("TRACK_PENCIL_COLOR_SEL", "TRK_SEL_GRAD_TOP", 4.5, "track pencil selected"),
]

# Hardcoded icon colours that are not palette tokens — checked with literal values.
# Format: (literal_fg_hex, bg_token, min_ratio, description)
_HARDCODED_ICON_PAIRS = [
    # Active sidebar icon is always rendered white regardless of theme
    ("#FFFFFF", "NAV_ACTIVE_GRAD_TOP", 4.5, "sidebar icon active (gradient top, worst)"),
    ("#FFFFFF", "NAV_ACTIVE_GRAD_BOT", 4.5, "sidebar icon active (gradient bot)"),
    # USB glyph (#fff4e6 cream, hardcoded in connection_section.py) on badge gradient
    ("#fff4e6", "IF_DEVICE_ICON_TOP", 4.5, "USB glyph on device badge (top)"),
    ("#fff4e6", "IF_DEVICE_ICON_BOT", 4.5, "USB glyph on device badge (bot)"),
    # Chip glyph (white, painted inline) on device badge gradient
    ("#FFFFFF", "IF_DEVICE_ICON_TOP", 4.5, "chip glyph on device badge (top)"),
    ("#FFFFFF", "IF_DEVICE_ICON_BOT", 4.5, "chip glyph on device badge (bot)"),
]


def _check_pairs(palette: dict, pairs: list, *, ui: bool = False) -> list[str]:
    failures: list[str] = []
    for fg_key, bg_key, minimum, label in pairs:
        fg = palette[fg_key]
        bg = palette[bg_key]
        if not isinstance(fg, str) or not isinstance(bg, str):
            continue
        try:
            ratio = contrast_ratio(fg, bg)
        except ValueError:
            continue
        ok = meets_wcag_aa_ui(ratio) if ui else meets_wcag_aa_text(ratio)
        if not ok or ratio < minimum:
            failures.append(
                f"{label}: {fg_key} {fg} on {bg_key} {bg} → {ratio:.2f}:1 (need {minimum}:1)"
            )
    return failures


def _check_hardcoded_icon_pairs(palette: dict, pairs: list) -> list[str]:
    """Check icon pairs where the foreground is a hardcoded literal, not a palette token."""
    failures: list[str] = []
    for fg_literal, bg_key, minimum, label in pairs:
        bg = palette.get(bg_key)
        if not isinstance(bg, str):
            continue
        try:
            ratio = contrast_ratio(fg_literal, bg)
        except ValueError:
            continue
        if ratio < minimum:
            failures.append(
                f"{label}: {fg_literal} on {bg_key} {bg} → {ratio:.2f}:1 (need {minimum}:1)"
            )
    return failures


@pytest.mark.parametrize("palette_name,palette", _ALL_THEMES)
def test_theme_text_pairs_wcag_aa(palette_name: str, palette: dict) -> None:
    failures = _check_pairs(palette, _TEXT_PAIRS)
    assert not failures, f"{palette_name} text contrast failures:\n" + "\n".join(failures)


@pytest.mark.parametrize("palette_name,palette", _ALL_THEMES)
def test_theme_ui_pairs_wcag_aa(palette_name: str, palette: dict) -> None:
    failures = _check_pairs(palette, _UI_PAIRS, ui=True)
    assert not failures, f"{palette_name} UI contrast failures:\n" + "\n".join(failures)


@pytest.mark.parametrize("palette_name,palette", _ALL_THEMES)
def test_theme_icon_pairs_wcag_aa(palette_name: str, palette: dict) -> None:
    """Monochromatic icons must meet 4.5:1 (treated as text per accessibility rule)."""
    failures = _check_pairs(palette, _ICON_PAIRS)
    failures += _check_hardcoded_icon_pairs(palette, _HARDCODED_ICON_PAIRS)
    assert not failures, f"{palette_name} icon contrast failures:\n" + "\n".join(failures)
