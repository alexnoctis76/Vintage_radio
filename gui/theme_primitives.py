"""Semantic colour primitives for the Vintage theme.

``gui.theme`` assigns widget tokens from these constants so repeated hex values
and shared gradient ladders have a single definition. Alternate themes derive
from ``gui.themes.*`` palettes; this module is the vintage baseline only.
"""

from __future__ import annotations

# ── Text ─────────────────────────────────────────────────────────────────────
TEXT_PRI = "#2C1F14"       # primary body text on light surfaces
TEXT_SEC = "#7A6C5A"       # secondary / muted text on light surfaces
TEXT_ON_DARK = "#FFF4E5"   # text on cocoa headers, sidebar, dark panels

# ── App chrome ─────────────────────────────────────────────────────────────────
SIDEBAR_BG = "#130902"
SIDEBAR_BG_MID = "#21150C"
SIDEBAR_BG_DEEP = "#110904"

SURFACE_PAGE = "#FBF6EE"   # main content background
SURFACE_BAR = "#F1DFC8"    # library bar base
SURFACE_WHITE = "#FFFFFF"
SURFACE_CREAM = "#FFF8EF"  # outline buttons, popup fields, tools inputs
SURFACE_IVORY = "#FFF7EB"  # cards, banners, modal headers on light
SURFACE_PARCHMENT = "#FFF9F1"  # combo boxes
SURFACE_WARM = "#FFF3E2"   # track pane / detail panel top
SURFACE_WARM_MID = "#FBF2E6"
SURFACE_WARM_BOT = "#F4E4CD"
SURFACE_META = "#FFFAF1"   # meta pills, notes preview

COCOA = "#3B2917"
COCOA_LIGHT = "#4A341F"
MOCHA = "#6B5A43"
MOCHA_DEEP = "#5A4B37"
PANEL_STATION = MOCHA

# ── Accent orange (shared primary-action gradient ladder) ────────────────────
ACCENT = "#D46F1A"
ACCENT_HOVER = "#B85E15"
ACCENT_GRAD_TOP = "#E27D25"
ACCENT_GRAD_MID = "#CE6817"
ACCENT_GRAD_BOT = "#A94F10"
ACCENT_BORDER = "#813C09"
ACCENT_BRIGHT = "#E8994D"  # capacity / progress fill top
ACCENT_MID = "#CC6C1F"
ACCENT_DEEP = "#A74D12"

# ── Borders & dividers ───────────────────────────────────────────────────────
BORDER_BRONZE = "#9B6A36"
BORDER_SOFT = "#C9A066"
BORDER_TAN = "#D6BD99"
BORDER_CARD = "#C7A06D"
BORDER_FRAME = "#5A3B1F"
BORDER_FRAME_SOFT = "#4C321D"
BORDER_COMBO = "#C6A77E"
BORDER_MINI = "#7A4C24"

# ── Selection & rows ─────────────────────────────────────────────────────────
TRACK_SEL = "#FFE6C6"
TRACK_SEL_TOP = "#FFF0D7"
TRACK_SEL_BOT = "#FFDFAA"
TRACK_SEL_BORDER = "#ECA34A"

STA_SEL_TOP = "#FFC475"
STA_SEL_MID = "#CF761F"
STA_SEL_BOT = "#AD5514"
STA_SEL_BORDER = "#EEA54C"

NAV_ACTIVE_TOP = "#C86917"
NAV_ACTIVE_BOT = "#8C3F08"
NAV_RING = "#E07918"

# ── Light button surfaces ──────────────────────────────────────────────────────
LIGHT_BTN_HOVER = "#E8D8BC"
LIGHT_BTN_PRESSED = "#D8C8A8"
OUTLINE_BTN_TOP = SURFACE_CREAM
OUTLINE_BTN_BOT = "#EAD6BD"
EJECT_BTN_TOP = "#FFF7EC"
EJECT_BTN_BOT = "#EAD8BF"

# ── Capacity / progress track (empty bar) ──────────────────────────────────────
BAR_TRACK = "#F9EFE0"
BAR_TRACK_BOT = "#F0DFCA"
PROGRESS_BORDER = "#A8703D"

# ── Install-firmware list panel (dark column) ──────────────────────────────────
IF_LIST_TOP = "#5C4D38"
IF_LIST_BOT = "#4D402F"
IF_CARD_IDLE = "#4D3C2A"
IF_CARD_IDLE_TEXT = "#FFF4DF"
IF_CARD_IDLE_SUB = "#F5E8D4"
IF_CARD_SEL_TOP = "#FFC978"
IF_CARD_SEL_BOT = "#B65A12"
IF_CARD_SEL_BORDER = "#EEA54C"
IF_FILTER_SOLID = "#3D3228"

# ── Modal / sync cocoa header ──────────────────────────────────────────────────
MODAL_HDR_TOP = COCOA_LIGHT
MODAL_HDR_BOT = "#2D1D10"
MODAL_HDR_TITLE = "#FFF5E6"
MODAL_HDR_SUB = "#EAD9C1"

# ── Shadow tints ───────────────────────────────────────────────────────────────
SHADOW_WARM = "#4E2708"
SHADOW_PANEL = "#4B2B12"
SHADOW_BTN = "#56290A"

# ── Status / misc ──────────────────────────────────────────────────────────────
WARN = "#B07800"
STATUS_OK_TOP = "#48A964"
STATUS_OK_BOT = "#267B43"
STATUS_OFF_TOP = "#A8A8A8"
STATUS_OFF_BOT = "#7A7A7A"
WHITE = "#FFFFFF"
