"""
Vintage Radio — UI Theme
========================
Every colour, size, margin, spacing, radius, gradient, and shadow used in the
UI lives here.  Edit any value and save; the app will live-reload the current
page when running with the  --dev  flag.

HOW VALUES ARE ORGANISED
------------------------
  Colours / palette  → top section
  Gradient stops     → GRAD_* section (suffix _TOP / _MID / _BOT)
  Shadows            → SHADOW_* parameters for QGraphicsDropShadowEffect
  Sidebar            → SIDEBAR_* constants
  Library bar        → LIBBAR_* constants
  Load Music         → LM_* constants (page, storage, splitter, panels, sync)
  Split-panel frame  → SPLIT_* constants
  Delegate rows      → STATION_* / TRACK_* constants

HOW TO ADD A NEW CONSTANT
--------------------------
  1.  Add the name here (e.g. MY_VALUE = 42)
  2.  Reference it in the widget file as  import gui.theme as t … t.MY_VALUE
  3.  Save — the file-watcher will trigger a page rebuild automatically in dev mode.
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  COLOUR PALETTE  (flat base colours — gradients are in the GRADIENT section)
# ═══════════════════════════════════════════════════════════════════════════════

S_BG           = "#130902"   # Sidebar background (gradient base)  — Near-black Brown
S_ACTIVE       = "#D46F1A"   # Sidebar active / selected btn        — Accent Orange
S_TEXT         = "#FFF4E3"   # Sidebar label & icon tint            — Warm White
S_HOVER_TINT   = "rgba(255,255,255,0.055)"  # Sidebar button hover overlay

C_BG           = "#FBF6EE"   # Page / content area background       — Warm Ivory
TOP_BAR_BG     = "#F1DFC8"   # Library bar background (gradient base)

PANEL_DARK     = "#6B5A43"   # Station pane background (gradient base) — Mocha Taupe
PANEL_HDR      = "#3B2917"   # Panel header gradient base              — Dark Cocoa

STA_ACTIVE     = "#D46F1A"   # Selected station row tint             — Accent Orange
TRACK_BG       = "#FFF3E2"   # Track table background (gradient base)
TRACK_SEL      = "#FFE6C6"   # Selected track row (gradient base)    — Apricot

ORANGE_BTN     = "#D46F1A"   # Primary action button (Sync)          — Accent Orange
BAR_ORANGE     = "#D46F1A"   # Storage capacity bar fill (gradient base)
BAR_TRACK_BG   = "#F9EFE0"   # Storage capacity bar empty area (gradient base)

BORDER         = "#9B6A36"   # All dividers, outlines, borders       — Border Bronze
BORDER_SOFT    = "#C9A066"   # Softer variant for subtle separators
TEXT_PRI       = "#2C1F14"   # Primary text                          — Near-black Brown
TEXT_SEC       = "#7A6C5A"   # Secondary / dimmed text               — Mid Taupe

# Hover tints for light (parchment) buttons
LIGHT_BTN_HOVER   = "#e8d8bc"
LIGHT_BTN_PRESSED = "#d8c8a8"

# Hover tint for orange action buttons
ORANGE_BTN_HOVER = "#b85e15"

# Warning banner text colour and font
WARN_TEXT  = "#b07800"    # amber-orange warning text
WARN_BOLD  = True         # bold warning text?

# Panel header text colour (used on dark headers in stations/tracks panels)
PANEL_HDR_TEXT    = "#FFF4E5"
LM_PANEL_HDR_TEXT_COLOR = "#FFF4E5"   # alias used directly in widgets

# Dropdown / combo widget fill
COMBO_BG      = "#FFF9F1"   # combo box background
COMBO_LIST_BG = "#FFF9F1"   # expanded dropdown list background

# App root / right-pane background (usually the same as C_BG)
APP_ROOT_BG   = "#FBF6EE"
RIGHT_PANE_BG = "#FBF6EE"

# Misc accent used on mini-button borders
MINI_BTN_BORDER = "#7A4C24"

# ═══════════════════════════════════════════════════════════════════════════════
#  GRADIENT STOPS
# ═══════════════════════════════════════════════════════════════════════════════
#  Suffix _TOP = stop:0, _MID = intermediate stop, _BOT = stop:1
#  Use in QSS:  qlineargradient(x1:0,y1:0,x2:0,y2:1,
#                               stop:0 {t.FOO_GRAD_TOP}, stop:1 {t.FOO_GRAD_BOT})

# Sidebar vertical gradient
SIDEBAR_GRAD_TOP = "#130902"
SIDEBAR_GRAD_MID = "#21150c"
SIDEBAR_GRAD_BOT = "#110904"

# Active nav-item orange gradient (top → bottom)
NAV_ACTIVE_GRAD_TOP = "#c86917"
NAV_ACTIVE_GRAD_BOT = "#8c3f08"

# Library bar background gradient
LIBBAR_GRAD_TOP = "#f1dfc8"
LIBBAR_GRAD_BOT = "#f1dfc6"

# Library bar combo gradient
LIBBAR_COMBO_GRAD_TOP = "#fff9f1"
LIBBAR_COMBO_GRAD_BOT = "#f2e5d2"

# Library bar / storage outline-button gradient
OUTLINE_BTN_GRAD_TOP = "#fff8ef"
OUTLINE_BTN_GRAD_BOT = "#ead6bd"

# Panel header gradient (shared by station and track panels)
PANEL_HDR_GRAD_TOP = "#4a341f"   # slightly lighter cocoa
PANEL_HDR_GRAD_BOT = "#3b2917"   # dark cocoa

# Station pane background gradient
STA_PANE_GRAD_TOP = "#6b5a43"
STA_PANE_GRAD_BOT = "#5a4b37"

# Track pane background gradient
TRK_PANE_GRAD_TOP = "#fff3e2"
TRK_PANE_GRAD_MID = "#fbf2e6"
TRK_PANE_GRAD_BOT = "#f4e4cd"

# "+ New" / "+ Add" mini-button gradient (dark brown)
MINI_BTN_GRAD_TOP = "#6e4826"
MINI_BTN_GRAD_BOT = "#3f2715"

# Capacity bar track gradient
CAP_TRACK_GRAD_TOP = "#f9efe0"
CAP_TRACK_GRAD_BOT = "#f0dfca"

# Capacity bar fill gradient
CAP_FILL_GRAD_TOP = "#e8994d"
CAP_FILL_GRAD_MID = "#cc6c1f"
CAP_FILL_GRAD_BOT = "#a74d12"

# Sync button gradient (primary orange action)
SYNC_BTN_GRAD_TOP = "#e27d25"
SYNC_BTN_GRAD_MID = "#ce6817"
SYNC_BTN_GRAD_BOT = "#a94f10"
SYNC_BTN_BORDER   = "#813c09"

# Eject button gradient (secondary light action)
EJECT_BTN_GRAD_TOP = "#fff7ec"
EJECT_BTN_GRAD_BOT = "#ead8bf"

# Selected station row gradient (orange pill)
STA_SEL_GRAD_TOP = "#ffc475"
STA_SEL_GRAD_MID = "#cf761f"
STA_SEL_GRAD_BOT = "#ad5514"
STA_SEL_BORDER   = "#eea54c"

# Selected track row gradient (cream pill)
TRK_SEL_GRAD_TOP = "#fff0d7"
TRK_SEL_GRAD_BOT = "#ffdfaa"
TRK_SEL_BORDER   = "#eca34a"

# ═══════════════════════════════════════════════════════════════════════════════
#  SHADOWS  (passed to QGraphicsDropShadowEffect or drawn via QPainter)
# ═══════════════════════════════════════════════════════════════════════════════

LIBBAR_SHADOW_BLUR   = 18    # px — blur radius for library bar card shadow
LIBBAR_SHADOW_OFFSET = 6     # px — y offset
LIBBAR_SHADOW_COLOR  = "#4e2708"   # shadow color (alpha set on the effect object)
LIBBAR_SHADOW_ALPHA  = 64    # 0-255 (≈ 0.25 opacity)

PANEL_SHADOW_BLUR    = 18    # px — blur radius for split-panel frame shadow
PANEL_SHADOW_OFFSET  = 9     # px — y offset
PANEL_SHADOW_COLOR   = "#4b2b12"
PANEL_SHADOW_ALPHA   = 64    # ≈ 0.25 opacity

BTN_SHADOW_BLUR      = 8     # px — blur for Sync / Eject button shadows
BTN_SHADOW_OFFSET    = 4     # px — y offset
BTN_SHADOW_COLOR     = "#56290a"
BTN_SHADOW_ALPHA     = 72    # ≈ 0.28 opacity

# QPainter active nav glow parameters
NAV_ACTIVE_RING_COLOR  = "#e07918"          # 2px outline ring color
NAV_ACTIVE_GLOW_ALPHA  = 92                 # 0-255 (≈ 0.36 opacity) for radial glow

# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

SIDEBAR_WIDTH            = 140   # px — total width of the left nav rail
SIDEBAR_MARGINS          = (8, 14, 8, 14)   # (left, top, right, bottom) px
SIDEBAR_SPACING          = 4    # px — gap between nav buttons
SIDEBAR_BTN_RADIUS       = 8    # px — corner radius on each nav button
SIDEBAR_BTN_PADDING      = "10px 6px 8px 6px"
SIDEBAR_BTN_FONT_SIZE    = 11   # pt — label text size
SIDEBAR_BTN_FONT_WEIGHT  = 600  # CSS font-weight
SIDEBAR_BTN_MIN_H        = 110  # px — minimum button height
SIDEBAR_ICON_SIZE        = 42   # px — square canvas for each glyph icon
SIDEBAR_ICON_FILL        = 0.78 # fraction of canvas used by the glyph (0.0–1.0)

# ═══════════════════════════════════════════════════════════════════════════════
#  LIBRARY BAR  (shown above pages except Settings and Help)
# ═══════════════════════════════════════════════════════════════════════════════

LIBBAR_HEIGHT        = 64    # px — bar total height (mockup: 78px)
LIBBAR_RADIUS        = 9     # px — card corner radius
LIBBAR_H_MARGINS     = (20, 0, 20, 0)  # (left, top, right, bottom) inner margins
LIBBAR_SPACING       = 12   # px — gap between elements
LIBBAR_BORDER_W      = 1     # px — border width
LIBBAR_BORDER        = "#d6bd99"  # border colour

LIBBAR_BTN_RADIUS    = 8    # px — New / Rename / Delete button corner radius
LIBBAR_BTN_PADDING   = "0px 18px"   # (vertical horizontal) button inner padding
LIBBAR_BTN_FONT_SIZE = 13   # pt
LIBBAR_BTN_H         = 44   # px — button fixed height

LIBBAR_COMBO_MIN_W      = 200  # px
LIBBAR_COMBO_MAX_W      = 600  # px
LIBBAR_COMBO_PADDING    = "0px 12px"
LIBBAR_COMBO_RADIUS     = 8    # px
LIBBAR_COMBO_FONT_SIZE  = 13   # pt
LIBBAR_COMBO_ARROW_W    = 22   # px
LIBBAR_COMBO_ARROW_SIZE = 5    # px
LIBBAR_COMBO_ARROW_H    = 6    # px
LIBBAR_COMBO_H          = 44   # px — combo fixed height
LIBBAR_COMBO_BORDER     = "#c6a77e"

LIBBAR_LABEL_FONT_SIZE = 13  # pt
LIBBAR_LABEL_BOLD      = True

# ═══════════════════════════════════════════════════════════════════════════════
#  SPLIT PANEL FRAME  (the bordered container around station + track panels)
# ═══════════════════════════════════════════════════════════════════════════════

SPLIT_PANEL_BORDER_W  = 2       # px — frame border width
SPLIT_PANEL_BORDER    = "#5a3b1f"  # frame border colour
SPLIT_PANEL_RADIUS    = 8       # px — frame corner radius
SPLIT_PANEL_SEP       = "#4c321d"  # 2px vertical separator between panes

# ═══════════════════════════════════════════════════════════════════════════════
#  LOAD MUSIC PAGE  (layout of the page as a whole)
# ═══════════════════════════════════════════════════════════════════════════════

LM_PAGE_MARGINS  = (16, 12, 16, 12)  # (left, top, right, bottom) outer page padding
LM_PAGE_SPACING  = 10   # px — vertical gap between the four page sections

# ─── Warning banner ───────────────────────────────────────────────────────────
LM_WARN_ROW_SPACING = 8   # px
LM_WARN_BTN_W       = 80  # px

# ─── Storage section ──────────────────────────────────────────────────────────
LM_STORAGE_SECTION_SPACING = 4    # px
LM_STORAGE_ROW_SPACING     = 12   # px

LM_CAPACITY_BAR_H      = 26    # px — height (mockup: 30px)
LM_CAPACITY_BAR_MIN_W  = 280   # px
LM_CAPACITY_BAR_MAX_W  = 420   # px
LM_CAPACITY_BAR_RADIUS = 13    # px — pill radius (matches mockup)
LM_CAPACITY_BAR_BORDER = "#a8703d"  # 2px border on the bar

LM_HEADING_FONT_SIZE = 15   # pt — "Storage" section heading

LM_SD_BTN_RADIUS  = 8      # px
LM_SD_BTN_PADDING = "0px 16px"
LM_SD_BTN_FONT    = 13     # pt
LM_SD_BTN_H       = 44     # px — fixed height for Detect/Select buttons
LM_SD_BTN_BORDER  = "#9b6a36"   # 2px border colour

# ─── Splitter / panel layout ──────────────────────────────────────────────────
LM_SPLITTER_HANDLE_W      = 0   # px — 0 = no visible drag handle (separator is drawn)
LM_SPLITTER_STATION_RATIO = 1   # relative share for the station panel
LM_SPLITTER_TRACK_RATIO   = 2   # relative share for the track panel

# ─── Shared panel chrome (station + track panels) ─────────────────────────────
LM_PANEL_RADIUS      = 0    # px — panels clip inside the frame; no individual radius
LM_PANEL_HEADER_H    = 56   # px — header strip height (matches mockup exactly)
LM_PANEL_HDR_MARGINS = (20, 0, 16, 0)  # (left, top, right, bottom)
LM_PANEL_HDR_SPACING = 8    # px

LM_PANEL_NEW_BTN_RADIUS  = 7    # px — "+ New" / "+ Add" button radius
LM_PANEL_NEW_BTN_PADDING = "0px 14px"
LM_PANEL_NEW_BTN_H       = 40   # px — fixed height for + New / + Add buttons
LM_PANEL_HDR_FONT_SIZE   = 15   # pt
LM_PANEL_HDR_FONT_BOLD   = True

# ─── Scrollbar (station pane — dark brown to match HTML .station-custom-scrollbar) ──────
LM_SCROLLBAR_W            = 30   # px — total width (HTML: 30px)
LM_SCROLLBAR_HANDLE_MIN_H = 64   # px — minimum thumb height (HTML: 64px)
LM_SCROLLBAR_ARROW_H      = 38   # px — up/down button height (HTML: 38px)

# Station-pane scrollbar colours
SB_STA_BG           = "#625642"
SB_STA_BORDER_L     = "rgba(28,18,10,0.58)"   # left edge border
SB_STA_BORDER_R     = "rgba(255,240,210,0.14)"
SB_STA_ARROW_COLOR  = "#f3dcc0"   # chevron colour on dark bg

# Track-pane scrollbar colours
SB_TRK_BG           = "#f7efe3"
SB_TRK_BORDER_L     = "#d3b995"
SB_TRK_BORDER_R     = "rgba(83,52,24,0.22)"
SB_TRK_ARROW_COLOR  = "#543a23"   # chevron colour on light bg

# Shared thumb gradient (same for both panes)
SB_THUMB_GRAD_TOP   = "#eba04d"
SB_THUMB_GRAD_MID   = "#db852e"
SB_THUMB_GRAD_BOT   = "#c46617"
SB_THUMB_BORDER     = "#9f4c12"
SB_THUMB_W_MARGIN   = 8   # px margin each side → effective thumb width = SCROLLBAR_W - 2×8 = 14px

# Gap between pane header bar and first list/table row (HTML: ~6–8px breathing room)
LM_LIST_TOP_PAD     = 8    # px

# ─── Station panel ────────────────────────────────────────────────────────────
LM_STATION_WARN_BTN_W = 80   # px

# ─── Track panel ──────────────────────────────────────────────────────────────
LM_TRACK_VHEADER_W       = 0    # px — 0 = vertical header hidden; row# drawn in delegate
LM_TRACK_NUM_COL_W       = 52   # px — width reserved in col-0 for row-number area (HTML: 52px)
LM_TRACK_DEFAULT_SECTION = 66   # px — default row height (must match TRACK_ROW_H)
LM_TRACK_NUM_FONT_SIZE   = 11   # pt
LM_TRACK_NUM_COLOR       = "#4d3d2c"   # row-number colour (HTML: .track-row .num)

LM_TRACK_ITEM_PAD_RIGHT = 8     # px
LM_TRACK_DIVIDER_COLOR  = "#dfc9a8"   # warm tan divider (replaces alpha border)
LM_TRACK_DUR_COL_W      = 92    # px — duration column (HTML grid: 92px)
LM_TRACK_FMT_COL_W      = 78    # px — format column (HTML grid: 78px)
LM_TRACK_TITLE_MIN_W    = 180   # px — min title column before horizontal scroll kicks in

# ─── Sync bar ─────────────────────────────────────────────────────────────────
LM_SYNC_TOP_MARGIN  = 6    # px
LM_SYNC_SPACING     = 14   # px

LM_SYNC_BTN_RADIUS  = 7    # px
LM_SYNC_BTN_PADDING = "0px 24px"
LM_SYNC_BTN_FONT    = 13   # pt
LM_SYNC_BTN_H       = 56   # px — fixed height (mockup: 62px)
LM_SYNC_BTN_W       = 220  # px — fixed width (mockup: 246px)

LM_EJECT_BTN_RADIUS  = 7   # px
LM_EJECT_BTN_PADDING = "0px 20px"
LM_EJECT_BTN_FONT    = 13  # pt
LM_EJECT_BTN_W       = 220  # px — fixed width (mockup: 248px)

# Icon colours for Sync / Eject button drawn icons
SYNC_ICON_COLOR  = "#ffffff"
EJECT_ICON_COLOR = "#352516"

# ═══════════════════════════════════════════════════════════════════════════════
#  STATION ROW DELEGATE  (StationItemDelegate)
# ═══════════════════════════════════════════════════════════════════════════════

STATION_ROW_H        = 72   # px — row height (mockup: 84px, scaled)
STATION_SEL_RADIUS   = 7    # px — corner radius on selected-row pill
STATION_PAD_LEFT     = 14   # px — gap from widget edge to first element
STATION_HANDLE_W     = 18   # px — ≡ drag-handle column width
STATION_NUM_OFFSET   = 22   # px — x-offset from PAD_LEFT to "01" number
STATION_NUM_W        = 34   # px — two-digit number column width
STATION_NAME_OFFSET  = 60   # px — x-offset from PAD_LEFT to station name
STATION_NAME_RSVD    = 90   # px — reserved on right for count + pencil
STATION_COUNT_W      = 52   # px — "N/255" count label width
STATION_COUNT_ROFF   = 86   # px — distance from right edge to count start
STATION_PENCIL_ROFF  = 26   # px — distance from right edge to ✎ pencil
STATION_PENCIL_W     = 18   # px — pencil glyph column width
STATION_ACCENT_W     = 4    # px — coloured left accent bar on selected rows
STATION_SEP_LIGHTER  = 130  # %  — lighter() factor for the row separator line

# ═══════════════════════════════════════════════════════════════════════════════
#  TRACK ROW DELEGATE  (TrackItemDelegate)
# ═══════════════════════════════════════════════════════════════════════════════

TRACK_ROW_H             = 66    # px — row height (mockup: 78px, scaled)
TRACK_SEL_RADIUS        = 7     # px — corner radius on selected-row pill
TRACK_PAD_X             = 14    # px — left padding AFTER the row-number area
TRACK_PAD_RIGHT         = 18    # px
TRACK_TITLE_TOP_BIAS    = 4     # px
TRACK_ARTIST_SIZE_DELTA = 1.0   # pt
TRACK_ARTIST_MIN_PT     = 7.0   # pt

# ═══════════════════════════════════════════════════════════════════════════════
#  LIBRARY BAR CONTAINER MARGINS  (spacing from sidebar / right edge / top)
# ═══════════════════════════════════════════════════════════════════════════════
#  HTML: .library-bar { left:26px; right:17px; top:13px; }
LIBBAR_WRAP_L = 26   # px — gap from sidebar right edge
LIBBAR_WRAP_T = 13   # px — gap from top of main area
LIBBAR_WRAP_R = 17   # px — gap from right window edge
LIBBAR_WRAP_B = 8    # px — gap below bar before page content

# ═══════════════════════════════════════════════════════════════════════════════
#  FOOTER BAR  (bottom bar with zoom controls + version)
# ═══════════════════════════════════════════════════════════════════════════════
#  HTML: .bottom-bar { height:58px; background:#f5eadc; border-top:1px solid #d8c6ad; }
FOOTER_H         = 48    # px — status bar height
FOOTER_BG        = "#f5eadc"
FOOTER_BORDER    = "#d8c6ad"
FOOTER_TEXT      = "#35271a"
FOOTER_FONT_SIZE = 13    # pt

ZOOM_BTN_W           = 36   # px — zoom button width
ZOOM_BTN_H           = 30   # px — zoom button height
ZOOM_BTN_RADIUS      = 9    # px
ZOOM_BTN_BORDER      = "#d3b995"
ZOOM_BTN_GRAD_TOP    = "#fff8ef"
ZOOM_BTN_GRAD_BOT    = "#eadcc9"
ZOOM_SPACING         = 8    # px

# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR — small-nav sizes (Settings / Help)
# ═══════════════════════════════════════════════════════════════════════════════
SIDEBAR_BTN_MIN_H_SMALL = 90   # px — Settings and Help buttons (HTML .small-nav: 110px)
