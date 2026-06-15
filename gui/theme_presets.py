"""Apply complete UI colour palettes from ``gui.themes``."""

from __future__ import annotations

from gui.themes import THEME_CHOICES, apply_palette_to_theme_module, get_palette, normalize_theme_id
from gui.themes.vintage import PALETTE as VINTAGE_PALETTE

__all__ = [
    "THEME_CHOICES",
    "apply_ui_theme",
    "normalize_theme_id",
]


def apply_ui_theme(theme_id: str) -> None:
    """Replace every colour token on ``gui.theme`` with the selected palette."""
    import gui.theme as theme_mod

    theme_id = normalize_theme_id(theme_id)
    # Always reset to the vintage baseline so tokens from a prior theme cannot linger.
    apply_palette_to_theme_module(theme_mod, VINTAGE_PALETTE)
    if theme_id != "vintage":
        apply_palette_to_theme_module(theme_mod, get_palette(theme_id))
