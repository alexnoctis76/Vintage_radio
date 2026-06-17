"""WCAG 2.x contrast helpers for theme palette review.

See WCAG 2.1 Success Criterion 1.4.3 (text) and 1.4.11 (non-text UI).
https://www.w3.org/TR/WCAG21/
"""

from __future__ import annotations

import re
from typing import Tuple


def _parse_hex(color: str) -> Tuple[int, int, int]:
    s = (color or "").strip()
    if not s.startswith("#"):
        raise ValueError(f"Expected #hex color, got {color!r}")
    s = s[1:]
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(f"Expected #RRGGBB, got {color!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _parse_rgba(color: str) -> Tuple[int, int, int]:
    m = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
        (color or "").strip(),
        re.I,
    )
    if not m:
        raise ValueError(f"Unsupported color format: {color!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def parse_rgb(color: str) -> Tuple[int, int, int]:
    c = (color or "").strip()
    if c.startswith("#"):
        return _parse_hex(c)
    if c.lower().startswith("rgb"):
        return _parse_rgba(c)
    raise ValueError(f"Unsupported color format: {color!r}")


def relative_luminance(rgb: Tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """Return WCAG contrast ratio between two solid colours."""
    l1 = relative_luminance(parse_rgb(foreground))
    l2 = relative_luminance(parse_rgb(background))
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


def meets_wcag_aa_text(ratio: float, *, large: bool = False) -> bool:
    return ratio >= (3.0 if large else 4.5)


def meets_wcag_aa_ui(ratio: float) -> bool:
    """Non-text UI components (icons, focus rings, chart segments)."""
    return ratio >= 3.0
