"""Complete UI colour palettes — one module per theme."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from gui.themes import colorblind, high_contrast, vintage

THEME_MODULES = {
    "vintage": vintage,
    "high_contrast": high_contrast,
    "colorblind": colorblind,
}

THEME_CHOICES: List[Tuple[str, str]] = [
    (mod.THEME_ID, mod.THEME_LABEL) for mod in (vintage, high_contrast, colorblind)
]


def normalize_theme_id(raw: str | None) -> str:
    key = (raw or "vintage").strip().lower()
    return key if key in THEME_MODULES else "vintage"


def get_palette(theme_id: str) -> Dict[str, Any]:
    mod = THEME_MODULES[normalize_theme_id(theme_id)]
    return dict(mod.PALETTE)


def apply_palette_to_theme_module(theme_mod: Any, palette: Dict[str, Any]) -> None:
    for key, value in palette.items():
        setattr(theme_mod, key, value)
