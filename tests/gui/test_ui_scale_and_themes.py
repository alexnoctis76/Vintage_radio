"""UI zoom scaling and complete colour theme palettes."""

from gui import ui_scale as u
from gui.theme_presets import apply_ui_theme, normalize_theme_id
from gui.themes import colorblind, high_contrast, vintage
import gui.theme as t


def test_ui_scale_px_scales_with_zoom() -> None:
    u.set_zoom_percent(100)
    assert u.px(20) == 20
    u.set_zoom_percent(150)
    assert u.px(20) == 30
    u.set_zoom_percent(80)
    assert u.px(10) == 8


def test_px_layout_grows_slower_above_100() -> None:
    u.set_zoom_percent(100)
    assert u.px_layout(280) == 280
    u.set_zoom_percent(200)
    assert u.px(280) == 560
    assert u.px_layout(280) == 420
    u.set_zoom_percent(100)


def test_banner_stacked_at_high_zoom() -> None:
    u.set_zoom_percent(100)
    assert u.banner_stacked() is False
    u.set_zoom_percent(130)
    assert u.banner_stacked() is True
    u.set_zoom_percent(100)


def test_connection_banner_height_grows_when_stacked() -> None:
    u.set_zoom_percent(150)
    single = u.connection_banner_height(stacked=False, control_height=28)
    stacked = u.connection_banner_height(stacked=True, control_height=28)
    assert stacked > single
    u.set_zoom_percent(100)


def test_device_banner_layout_grows_with_zoom() -> None:
    u.set_zoom_percent(100)
    h100 = u.device_banner_layout()["height"]
    u.set_zoom_percent(150)
    h150 = u.device_banner_layout()["height"]
    assert h150 > h100
    u.set_zoom_percent(100)


def test_normalize_theme_id_fallback() -> None:
    assert normalize_theme_id("high_contrast") == "high_contrast"
    assert normalize_theme_id("unknown") == "vintage"
    assert normalize_theme_id(None) == "vintage"


def test_all_palettes_have_same_keys() -> None:
    keys = set(vintage.PALETTE.keys())
    assert set(high_contrast.PALETTE.keys()) == keys
    assert set(colorblind.PALETTE.keys()) == keys
    assert len(keys) >= 270


def test_apply_ui_theme_high_contrast_changes_background() -> None:
    apply_ui_theme("vintage")
    vintage_bg = t.C_BG
    apply_ui_theme("high_contrast")
    assert t.C_BG != vintage_bg
    assert t.C_BG == "#FDF6ED"
    apply_ui_theme("vintage")
    assert t.C_BG == vintage_bg


def test_apply_ui_theme_resets_when_returning_to_vintage() -> None:
    apply_ui_theme("high_contrast")
    apply_ui_theme("vintage")
    assert t.S_BG == vintage.PALETTE["S_BG"]


def test_high_contrast_differs_from_vintage_broadly() -> None:
    v = vintage.PALETTE
    hc = high_contrast.PALETTE
    changed = sum(1 for k in v if v[k] != hc[k])
    assert changed >= 200


def test_dark_theme_differs_from_vintage_broadly() -> None:
    v = vintage.PALETTE
    dark = colorblind.PALETTE
    changed = sum(1 for k in v if v[k] != dark[k])
    assert changed >= 200


def test_high_contrast_vintage_readable_on_light_surfaces() -> None:
    """Meta pills and detail panel use dark text on cream/white — not cream-on-cream."""
    hc = high_contrast.PALETTE
    assert hc["IF_META_LABEL_FG"] == "#605246"
    assert hc["IF_META_VALUE_FG"] == "#1E1610"
    assert hc["IF_NOTES_PREVIEW_FG"] == "#1E1610"
    assert hc["IF_META_BOX_BG"] == "#FFFFFF"
    assert hc["IF_DETAIL_TOP"] == "#FDF6ED"
    assert hc["TEXT_PRI"] == "#1E1610"
    assert hc["IF_CARD_IDLE_TEXT"] == "#FDF6ED"


def test_high_contrast_vintage_palette_spec() -> None:
    hc = high_contrast.PALETTE
    assert hc["S_BG"] == "#1E1610"
    assert hc["C_BG"] == "#FDF6ED"
    assert hc["TEXT_PRI"] == "#1E1610"
    assert hc["ORANGE_BTN"] == "#C84B00"
    assert hc["IF_STATUS_PILL_ON_TOP"] == "#005A9C"
    assert hc["IF_INSTALL_BTN_FG"] == "#FDF6ED"


def test_high_contrast_dark_palette_spec() -> None:
    dark = colorblind.PALETTE
    assert dark["S_BG"] == "#121212"
    assert dark["TEXT_PRI"] == "#FFFFFF"
    assert dark["ORANGE_BTN"] == "#FF8C00"
    assert dark["IF_STATUS_PILL_ON_TOP"] == "#00E5FF"
    assert dark["IF_INSTALL_BTN_FG"] == "#121212"
    assert dark["TEXT_SEC"] == "#B3A69A"
