"""Help tab — RP2040 NeoPixel status legend."""

from gui.widgets.help.page import HelpPage


def test_led_status_legend_covers_main_states():
    items = HelpPage.led_status_legend_items()
    joined = " ".join(items).lower()
    assert "violet" in joined
    assert "standby" in joined
    assert "white" in joined or "blue" in joined
    assert "fatal" in joined


def test_led_status_legend_entries_include_animation_modes():
    entries = HelpPage.led_status_legend_entries()
    assert len(entries) == 6
    modes = {e.mode for e in entries}
    assert "breathe" in modes
    assert "flash" in modes
    assert "solid" in modes
    playing = entries[0]
    assert playing.swatch_rgb() == (172, 125, 249)
    idle = entries[1]
    ir, ig, ib = idle.swatch_rgb()
    assert ib > ir and ib > ig
    standby = entries[2]
    sr, sg, sb = standby.swatch_rgb()
    assert abs(sr - sg) <= 8 and abs(sg - sb) <= 8
    warning = entries[4]
    wr, wg, wb = warning.swatch_rgb()
    assert wg < 120 and wb == 0
