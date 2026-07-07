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
#  Primitives live in gui.theme_primitives; tokens here alias them for widgets.
# ═══════════════════════════════════════════════════════════════════════════════

from gui import theme_primitives as _p

S_BG           = _p.SIDEBAR_BG
S_ACTIVE       = _p.ACCENT
S_TEXT         = _p.TEXT_ON_DARK
S_HOVER_TINT   = "rgba(255,255,255,0.055)"

C_BG           = _p.SURFACE_PAGE
TOP_BAR_BG     = _p.SURFACE_BAR

PANEL_DARK     = _p.PANEL_STATION
PANEL_HDR      = _p.COCOA

STA_ACTIVE     = _p.ACCENT
TRACK_BG       = _p.SURFACE_WARM
TRACK_SEL      = _p.TRACK_SEL

ORANGE_BTN     = _p.ACCENT
BAR_ORANGE     = _p.ACCENT
BAR_TRACK_BG   = _p.BAR_TRACK

BORDER         = _p.BORDER_BRONZE
BORDER_SOFT    = _p.BORDER_SOFT
TEXT_PRI       = _p.TEXT_PRI
TEXT_SEC       = _p.TEXT_SEC

LIGHT_BTN_HOVER   = _p.LIGHT_BTN_HOVER
LIGHT_BTN_PRESSED = _p.LIGHT_BTN_PRESSED
ORANGE_BTN_HOVER  = _p.ACCENT_HOVER

WARN_TEXT  = _p.WARN
WARN_BOLD  = True

PANEL_HDR_TEXT    = _p.TEXT_ON_DARK
LM_PANEL_HDR_TEXT_COLOR = _p.TEXT_ON_DARK

COMBO_BG      = _p.SURFACE_PARCHMENT
COMBO_LIST_BG = _p.SURFACE_PARCHMENT

APP_ROOT_BG   = _p.SURFACE_PAGE
RIGHT_PANE_BG = _p.SURFACE_PAGE

MINI_BTN_BORDER = _p.BORDER_MINI

# ═══════════════════════════════════════════════════════════════════════════════
#  GRADIENT STOPS
# ═══════════════════════════════════════════════════════════════════════════════
#  Suffix _TOP = stop:0, _MID = intermediate stop, _BOT = stop:1
#  Use in QSS:  qlineargradient(x1:0,y1:0,x2:0,y2:1,
#                               stop:0 {t.FOO_GRAD_TOP}, stop:1 {t.FOO_GRAD_BOT})

# Sidebar vertical gradient
SIDEBAR_GRAD_TOP = _p.SIDEBAR_BG
SIDEBAR_GRAD_MID = _p.SIDEBAR_BG_MID
SIDEBAR_GRAD_BOT = _p.SIDEBAR_BG_DEEP

NAV_ACTIVE_GRAD_TOP = _p.NAV_ACTIVE_TOP
NAV_ACTIVE_GRAD_BOT = _p.NAV_ACTIVE_BOT

LIBBAR_GRAD_TOP = _p.SURFACE_BAR
LIBBAR_GRAD_BOT = "#F1DFC6"

LIBBAR_COMBO_GRAD_TOP = _p.SURFACE_PARCHMENT
LIBBAR_COMBO_GRAD_BOT = "#F2E5D2"

OUTLINE_BTN_GRAD_TOP = _p.OUTLINE_BTN_TOP
OUTLINE_BTN_GRAD_BOT = _p.OUTLINE_BTN_BOT

PANEL_HDR_GRAD_TOP = _p.COCOA_LIGHT
PANEL_HDR_GRAD_BOT = _p.COCOA

STA_PANE_GRAD_TOP = _p.MOCHA
STA_PANE_GRAD_BOT = _p.MOCHA_DEEP

TRK_PANE_GRAD_TOP = _p.SURFACE_WARM
TRK_PANE_GRAD_MID = _p.SURFACE_WARM_MID
TRK_PANE_GRAD_BOT = _p.SURFACE_WARM_BOT

MINI_BTN_GRAD_TOP = "#6E4826"
MINI_BTN_GRAD_BOT = "#3F2715"

CAP_TRACK_GRAD_TOP = _p.BAR_TRACK
CAP_TRACK_GRAD_BOT = _p.BAR_TRACK_BOT

CAP_FILL_GRAD_TOP = _p.ACCENT_BRIGHT
CAP_FILL_GRAD_MID = _p.ACCENT_MID
CAP_FILL_GRAD_BOT = _p.ACCENT_DEEP

SYNC_BTN_GRAD_TOP = _p.ACCENT_GRAD_TOP
SYNC_BTN_GRAD_MID = _p.ACCENT_GRAD_MID
SYNC_BTN_GRAD_BOT = _p.ACCENT_GRAD_BOT
SYNC_BTN_BORDER   = _p.ACCENT_BORDER

EJECT_BTN_GRAD_TOP = _p.EJECT_BTN_TOP
EJECT_BTN_GRAD_BOT = _p.EJECT_BTN_BOT

STA_SEL_GRAD_TOP = _p.STA_SEL_TOP
STA_SEL_GRAD_MID = _p.STA_SEL_MID
STA_SEL_GRAD_BOT = _p.STA_SEL_BOT
STA_SEL_BORDER   = _p.STA_SEL_BORDER

TRK_SEL_GRAD_TOP = _p.TRACK_SEL_TOP
TRK_SEL_GRAD_BOT = _p.TRACK_SEL_BOT
TRK_SEL_BORDER   = _p.TRACK_SEL_BORDER

# ═══════════════════════════════════════════════════════════════════════════════
#  SHADOWS  (passed to QGraphicsDropShadowEffect or drawn via QPainter)
# ═══════════════════════════════════════════════════════════════════════════════

LIBBAR_SHADOW_BLUR   = 18    # px — blur radius for library bar card shadow
LIBBAR_SHADOW_OFFSET = 6     # px — y offset
LIBBAR_SHADOW_COLOR  = _p.SHADOW_WARM
LIBBAR_SHADOW_ALPHA  = 64    # 0-255 (≈ 0.25 opacity)

PANEL_SHADOW_BLUR    = 18    # px — blur radius for split-panel frame shadow
PANEL_SHADOW_OFFSET  = 9     # px — y offset
PANEL_SHADOW_COLOR   = _p.SHADOW_PANEL
PANEL_SHADOW_ALPHA   = 64    # ≈ 0.25 opacity

BTN_SHADOW_BLUR      = 8     # px — blur for Sync / Eject button shadows
BTN_SHADOW_OFFSET    = 4     # px — y offset
BTN_SHADOW_COLOR     = _p.SHADOW_BTN
BTN_SHADOW_ALPHA     = 72    # ≈ 0.28 opacity

# QPainter active nav glow parameters
NAV_ACTIVE_RING_COLOR  = _p.NAV_RING
NAV_ACTIVE_GLOW_ALPHA  = 92                 # 0-255 (≈ 0.36 opacity) for radial glow

# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

SIDEBAR_WIDTH            = 140   # px — total width of the left nav rail
SIDEBAR_MARGINS          = (8, 14, 8, 14)   # (left, top, right, bottom) px
SIDEBAR_SPACING          = 4    # px — gap between nav buttons
SIDEBAR_BTN_RADIUS       = 8    # px — corner radius on each nav button
SIDEBAR_BTN_PADDING      = "10px 6px 8px 6px"
SIDEBAR_BTN_FONT_SIZE    = 14   # pt — label text size
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
LIBBAR_BORDER        = _p.BORDER_TAN

LIBBAR_BTN_RADIUS    = 8    # px — New / Rename / Delete button corner radius
LIBBAR_BTN_PADDING   = "0px 18px"   # (vertical horizontal) button inner padding
LIBBAR_BTN_FONT_SIZE = 13   # pt
LIBBAR_BTN_H         = 44   # px — button fixed height
LIBBAR_BTN_W         = 96   # px — fixed width (keeps combo ratio when window grows)
OUTLINE_BTN_BORDER_W     = 2    # px — outline button QSS border (New, Details, …)
OUTLINE_BTN_EDGE_MARGIN  = 2    # px — QSS horizontal margin so border is not clipped
OUTLINE_BTN_PAD_H        = 18   # px — horizontal padding (from LIBBAR_BTN_PADDING)

LIBBAR_COMBO_MIN_W      = 200  # px
LIBBAR_COMBO_PADDING    = "0px 12px"
LIBBAR_COMBO_RADIUS     = 8    # px
LIBBAR_COMBO_FONT_SIZE  = 13   # pt
LIBBAR_COMBO_ARROW_W    = 22   # px
LIBBAR_COMBO_ARROW_SIZE = 5    # px
LIBBAR_COMBO_ARROW_H    = 6    # px
LIBBAR_COMBO_H          = 44   # px — combo fixed height
LIBBAR_COMBO_BORDER     = _p.BORDER_COMBO

LIBBAR_LABEL_FONT_SIZE = 13  # pt
LIBBAR_LABEL_BOLD      = True

# ═══════════════════════════════════════════════════════════════════════════════
#  SPLIT PANEL FRAME  (the bordered container around station + track panels)
# ═══════════════════════════════════════════════════════════════════════════════

SPLIT_PANEL_BORDER_W  = 2       # px — frame border width
SPLIT_PANEL_BORDER    = _p.BORDER_FRAME
SPLIT_PANEL_RADIUS    = 8       # px — frame corner radius
SPLIT_PANEL_SEP       = _p.BORDER_FRAME_SOFT

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
LM_CAPACITY_BAR_BORDER = _p.PROGRESS_BORDER

LM_HEADING_FONT_SIZE = 15   # pt — "Storage" section heading

LM_SD_BTN_RADIUS  = 8      # px
LM_SD_BTN_PADDING = "0px 16px"
LM_SD_BTN_FONT    = 13     # pt
LM_SD_BTN_H       = 44     # px — fixed height for Detect/Select buttons
LM_SD_BTN_BORDER  = _p.BORDER_BRONZE

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
LM_PANEL_HDR_FONT_WEIGHT = 900  # match IF_TAB_FONT weight (Install Firmware folder tabs)

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
SB_THUMB_GRAD_TOP     = "#eba04d"
SB_THUMB_GRAD_MID     = "#db852e"
SB_THUMB_GRAD_BOT     = "#c46617"
# Station-specific thumb top (dark rail variant).  Defaults to SB_THUMB_GRAD_TOP;
# override in palettes where the station and track rails have different luminances.
SB_STA_THUMB_GRAD_TOP = SB_THUMB_GRAD_TOP
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
LM_TRACK_TITLE_FONT_SIZE = 13   # px — bold title in track delegate
LM_TRACK_ARTIST_FONT_SIZE = 11  # px — artist sub-line (must stay ≤ title)
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
SYNC_ICON_COLOR  = _p.WHITE
EJECT_ICON_COLOR = _p.TEXT_PRI

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
STATION_COUNT_COLOR      = "#e8d5bc"  # track count on unselected rows
STATION_PENCIL_COLOR     = "#f3dcc0"  # edit pencil on unselected rows
STATION_COUNT_COLOR_SEL  = "#fff8ef"  # track count on selected orange row
STATION_PENCIL_COLOR_SEL = "#ffffff"  # edit pencil on selected row

# ═══════════════════════════════════════════════════════════════════════════════
#  TRACK ROW DELEGATE  (TrackItemDelegate)
# ═══════════════════════════════════════════════════════════════════════════════

TRACK_ROW_H             = 66    # px — row height (mockup: 78px, scaled)
TRACK_SEL_RADIUS        = 7     # px — corner radius on selected-row pill
TRACK_PAD_X             = 14    # px — left padding AFTER the row-number area
TRACK_PAD_RIGHT         = 18    # px
TRACK_TITLE_TOP_BIAS    = 4     # px
TRACK_ARTIST_GAP        = 6     # px — vertical gap between title and artist
TRACK_ARTIST_SIZE_DELTA = 1.0   # pt
TRACK_ARTIST_MIN_PT     = 7.0   # pt

# ═══════════════════════════════════════════════════════════════════════════════
#  LIBRARY BAR CONTAINER MARGINS  (spacing from sidebar / right edge / top)
# ═══════════════════════════════════════════════════════════════════════════════
#  HTML: .library-bar { left:26px; right:17px; top:13px; }
LIBBAR_WRAP_L = 16   # px — align with LM_PAGE_MARGINS left (page content below)
LIBBAR_WRAP_T = 13   # px — gap from top of main area
LIBBAR_WRAP_R = 16   # px — align with LM_PAGE_MARGINS right
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

# Native OS caption (Windows 11 title bar) — match modal / panel cocoa header
WIN_CAPTION_BG   = "#4a341f"
WIN_CAPTION_FG   = "#fff5e6"

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

# ═══════════════════════════════════════════════════════════════════════════════
#  INSTALL FIRMWARE PAGE  (InstallFirmwarePage — values from gui/scratch.html)
# ═══════════════════════════════════════════════════════════════════════════════

IF_DEVICE_BANNER_H       = 62   # px — compact (50% of HTML 124px row)
IF_DEVICE_ICON           = 36   # px — .device-icon scaled
IF_DEVICE_ICON_RADIUS    = 9    # px — icon corner radius
IF_DEVICE_ICON_INNER     = 24   # px — svg inside icon
IF_DEVICE_TITLE_SIZE     = 13   # pt
IF_DEVICE_TITLE_FG       = _p.TEXT_PRI
IF_DEVICE_META_SIZE      = 10   # pt
IF_DEVICE_META_FG        = _p.TEXT_SEC
IF_DEVICE_BTN_W          = 110  # px
IF_DEVICE_BTN_H          = 28   # px
IF_DEVICE_BTN_FONT       = 11   # pt
IF_DEVICE_BANNER_PAD_H   = 12   # px — horizontal inner padding
IF_DEVICE_BANNER_PAD_V   = 8    # px — vertical inner padding
IF_DEVICE_ROW_GAP        = 10   # px
IF_DEVICE_BANNER_BORDER  = _p.BORDER_TAN
IF_DEVICE_BANNER_TOP     = _p.SURFACE_IVORY
IF_DEVICE_BANNER_BOT     = "#F0DDC4"
IF_DEVICE_ICON_TOP       = _p.ACCENT_GRAD_TOP
IF_DEVICE_ICON_BOT       = "#9C4610"

IF_TAB_H                 = 48   # px
IF_TAB_FONT              = 17   # pt — HTML 24px scaled
IF_TAB_BORDER            = _p.BORDER_FRAME
IF_TAB_DIVIDER           = "#7A5128"
IF_TAB_BG                = "#F5EAD9"
IF_TAB_INACTIVE_TOP      = _p.SURFACE_WHITE
IF_TAB_INACTIVE_BOT      = "#FFF8ED"
IF_TAB_INACTIVE_FG       = _p.TEXT_PRI
IF_TAB_INACTIVE_BORDER   = "#7A5128"
IF_TAB_ACTIVE_TOP        = PANEL_HDR_GRAD_TOP   # match Load Music "Stations" header
IF_TAB_ACTIVE_BOT        = PANEL_HDR_GRAD_BOT
IF_TAB_ACTIVE_FG         = LM_PANEL_HDR_TEXT_COLOR
IF_TAB_ACTIVE_OVERLAP    = 2    # px — active tab covers panel seam
IF_TAB_CORNER_RADIUS     = 7    # px — rounded tab tops (left column)
IF_TAB_INACTIVE_TOP_CLIP = 2    # px — inactive tab top trimmed to active tab seam

# Keep Load Music panel titles ("Stations", "Tracks") in sync with folder tab type.
LM_PANEL_HDR_FONT_SIZE = IF_TAB_FONT

IF_STATUS_PILL_ON_TOP    = _p.STATUS_OK_TOP
IF_STATUS_PILL_ON_BOT    = _p.STATUS_OK_BOT
IF_STATUS_PILL_OFF_TOP   = _p.STATUS_OFF_TOP
IF_STATUS_PILL_OFF_BOT   = _p.STATUS_OFF_BOT
IF_STATUS_PILL_FG        = "#FFF8ED"
IF_STATUS_PILL_FONT      = 9    # pt
IF_STATUS_PILL_PAD_V     = 2    # px
IF_STATUS_PILL_PAD_H     = 8    # px
IF_STATUS_PILL_H         = 18   # px
IF_PILL_FONT             = 9    # pt — legacy alias

IF_LIST_PANEL_TOP        = _p.IF_LIST_TOP
IF_LIST_PANEL_BOT        = _p.IF_LIST_BOT
IF_FILTER_STRIP_H        = 60   # px
IF_FILTER_STRIP_BG       = "rgba(44, 34, 22, 0.17)"
IF_FILTER_STRIP_BG_SOLID = _p.IF_FILTER_SOLID

IF_CARD_SEL_TOP          = _p.IF_CARD_SEL_TOP
IF_CARD_SEL_BOT          = _p.IF_CARD_SEL_BOT
IF_CARD_SEL_BORDER       = _p.IF_CARD_SEL_BORDER
IF_CARD_IDLE_BG          = _p.IF_CARD_IDLE
IF_CARD_IDLE_TEXT        = _p.IF_CARD_IDLE_TEXT
IF_CARD_IDLE_SUBTEXT     = _p.IF_CARD_IDLE_SUB

IF_FIRMWARE_CARD_H       = 138  # px — .firmware-card min-height
IF_CARD_TITLE_PX         = 18   # px — HTML 24 scaled
IF_CARD_SUB_PX           = 13   # px
IF_CARD_TAG_PX           = 10   # px
IF_CARD_TAG_GAP          = 6    # px
IF_CARD_TAG_W            = 58   # px — uniform tag pill width
IF_CARD_TAG_H            = 22   # px
IF_CARD_TAG_PAD_V        = 2    # px
IF_CARD_TAG_BG_SEL       = "#59ffffff"
IF_CARD_TAG_FG_SEL       = _p.WHITE
IF_CARD_TAG_BG_IDLE      = "#6B5844"
IF_CARD_TAG_FG_IDLE      = _p.IF_CARD_IDLE_TEXT

IF_PILL_RADIUS           = 9999 # px — fallback; prefer if_pill_radius(h)

def if_pill_radius(height_px: int) -> int:
    """Semicircular pill ends for a given widget height."""
    return max(4, height_px // 2)

IF_SW_BADGE_FG           = "#FFF6EA"
IF_SW_BADGE_H            = 22   # px
IF_SW_BADGE_MIN_W        = 64   # px
IF_SW_BADGE_PAD_V        = 3    # px
IF_SW_BADGE_PAD_H        = 10   # px
IF_META_LABEL_FG         = _p.TEXT_SEC
IF_META_VALUE_FG         = _p.TEXT_PRI
IF_META_PILL_W           = 130  # px — uniform meta pill width
IF_META_DEVICE_PILL_W    = 178  # px — fits "DFPlayer + RP2040" + icon
IF_META_AUTHOR_PILL_W    = 180  # px — wider for GitHub link
IF_META_PILL_H           = 36   # px
IF_META_PILL_BORDER      = _p.BORDER_TAN
IF_META_ICON             = 12   # px — icon beside meta value
IF_REPO_AUTHOR_FG        = "#7B3C0D"
IF_PROGRESS_W            = 180  # px — footer install progress track
IF_PROGRESS_H            = 14   # px
IF_PROGRESS_BORDER       = _p.PROGRESS_BORDER
IF_PROGRESS_TRACK_TOP    = _p.BAR_TRACK
IF_PROGRESS_TRACK_BOT    = _p.BAR_TRACK_BOT
IF_PROGRESS_FILL_TOP     = _p.ACCENT_BRIGHT
IF_PROGRESS_FILL_MID     = _p.ACCENT_MID
IF_PROGRESS_FILL_BOT     = _p.ACCENT_DEEP
IF_STATUS_CHECK_FG       = "#3d8a4a"
IF_NOTES_PILL_FG         = "#fff4e6"
IF_NOTES_PILL_FONT       = 10   # pt
IF_NOTES_PILL_W          = 76   # px
IF_NOTES_PILL_H          = 20   # px
IF_NOTES_PILL_PAD_V      = 2    # px
IF_NOTES_PILL_PAD_H      = 8    # px

IF_DETAIL_TOP            = _p.SURFACE_WARM
IF_DETAIL_MID            = _p.SURFACE_WARM_MID
IF_DETAIL_BOT            = _p.SURFACE_WARM_BOT
IF_CARD_BORDER           = "#D0A875"
IF_CARD_INNER_TOP        = _p.SURFACE_IVORY
IF_CARD_INNER_BOT        = "#EAD7BD"
IF_CARD_RADIUS           = 12   # px
IF_DETAIL_CARD_GAP       = 10   # px — tighter for default 1200×780 window

IF_SW_TITLE_PX           = 18   # pt — compact detail header
IF_SW_DESC_PX            = 13   # pt
IF_SW_BADGE_TOP          = "#DF852F"
IF_SW_BADGE_BOT          = _p.ACCENT_GRAD_BOT
IF_SW_BADGE_SOFT_TOP     = "#8B6240"
IF_SW_BADGE_SOFT_BOT     = "#4A321E"
IF_META_LABEL_PX         = 8    # pt — compact meta pills
IF_META_VALUE_PX         = 10   # pt
IF_META_BOX_H            = 30   # px — legacy alias
IF_SW_BADGE_FONT         = 11   # pt
IF_NOTES_TITLE_PX        = 15   # pt
IF_NOTES_PREVIEW_H       = 68   # px — legacy alias / minimum hint
IF_NOTES_PREVIEW_MIN_H   = 48   # px — notes box minimum when card stretches
IF_NOTES_FONT_SIZE       = 12   # pt
IF_NOTES_PILL_BG         = "#6e553b"   # read-only pill (HTML .notes-pill)
IF_NOTES_PILL_EDIT_TOP   = "#8b5a2b"   # editable — brown per conversation
IF_NOTES_PILL_EDIT_BOT   = "#6b4423"
IF_META_BOX_BG           = _p.SURFACE_META
IF_NOTES_PREVIEW_BG      = _p.SURFACE_META
IF_NOTES_PREVIEW_FG      = TEXT_PRI
IF_NOTES_PREVIEW_BORDER  = "#d5b287"
IF_NOTES_SB_W            = 13   # px — inline rail inside notes preview (HTML)
IF_NOTES_SB_THUMB_W      = 7    # px — thumb cross-section after 3px track padding
IF_NOTES_SB_TRACK        = "#f4ead7"
IF_NOTES_SB_TRACK_BORDER = "rgba(97, 66, 34, 0.28)"
IF_NOTES_SB_THUMB_PAD    = 3    # px — gap between thumb and rail edge
IF_SMALL_BTN_H           = 32   # px
IF_SMALL_BTN_FONT        = 13   # pt

IF_INSTALL_BTN_W         = 196  # px — scaled down for default window
IF_INSTALL_BTN_H         = 40   # px
IF_INSTALL_BTN_FONT      = 14   # pt
IF_INSTALL_BTN_FG        = _p.SURFACE_IVORY
IF_INSTALL_BTN_DISABLED_FG = _p.SURFACE_IVORY
IF_INSTALL_BTN_TOP       = _p.ACCENT_GRAD_TOP
IF_INSTALL_BTN_MID       = _p.ACCENT_GRAD_MID
IF_INSTALL_BTN_BOT       = _p.ACCENT_GRAD_BOT
IF_INSTALL_BTN_BORDER    = _p.ACCENT_BORDER
IF_STATUS_FONT_SIZE      = 13   # pt
IF_STATUS_MSG_FG         = _p.TEXT_SEC
IF_LIST_WIDTH_HINT       = 398  # px — HTML grid col

IF_PAGE_ROW_GAP          = 12   # px
IF_FOOTER_H              = 48   # px — compact action row
IF_DETAIL_MIDDLE_MIN     = 120  # px — notes row grows to fill card height

# ═══════════════════════════════════════════════════════════════════════════════
#  SYNC MODAL DIALOGS  (SyncChoiceDialog / ReplaceConfirmDialog)
# ═══════════════════════════════════════════════════════════════════════════════

SYNC_MDL_CHOICE_W       = 720   # px — sync choice dialog width (HTML: 890px)
SYNC_MDL_CONFIRM_W      = 520   # px — replace confirm dialog width (HTML: 650px)
SYNC_MDL_PROGRESS_W     = 520   # px — task progress dialog width
SYNC_MDL_PROGRESS_H     = 20    # px — progress bar height inside sync modals
SYNC_MDL_PROGRESS_TEXT_SIZE = 11  # pt — overlay text on progress bar
SYNC_MDL_PROGRESS_TEXT_CLR  = _p.TEXT_PRI
SYNC_MDL_PROGRESS_ETA_SIZE  = 12  # pt
SYNC_MDL_PROGRESS_ETA_CLR   = _p.TEXT_SEC
SYNC_MDL_PROGRESS_STATUS_SIZE = 13  # pt
SYNC_MDL_PROGRESS_STATUS_CLR  = _p.TEXT_PRI
SYNC_MDL_RADIUS         = 14   # px — outer window corner radius
SYNC_MDL_BORDER         = "#B98A55"

SYNC_MDL_BG_TOP         = "#FFF8ED"
SYNC_MDL_BG_BOT         = "#F1DFC6"

SYNC_MDL_HDR_H          = 68   # px
SYNC_MDL_HDR_TOP        = _p.MODAL_HDR_TOP
SYNC_MDL_HDR_BOT        = _p.MODAL_HDR_BOT
SYNC_MDL_HDR_TITLE_SIZE = 18   # pt
SYNC_MDL_HDR_SUB_SIZE   = 12   # pt
SYNC_MDL_HDR_TITLE_CLR  = _p.MODAL_HDR_TITLE
SYNC_MDL_HDR_SUB_CLR    = _p.MODAL_HDR_SUB
SYNC_MDL_HDR_PAD_L      = 10   # px
SYNC_MDL_HDR_PAD_R      = 5   # px

SYNC_MDL_CLOSE_SIZE     = 32   # px
SYNC_MDL_CLOSE_RADIUS   = 8    # px
SYNC_MDL_CLOSE_TOP_PAD  = 5    # px — push × down from top of header bar

SYNC_MDL_BODY_PAD       = 22   # px
SYNC_MDL_CARD_GAP       = 16   # px
SYNC_MDL_CARD_MIN_H     = 280  # px
SYNC_MDL_CARD_RADIUS    = 12   # px
SYNC_MDL_CARD_BORDER    = _p.BORDER_CARD
SYNC_MDL_CARD_BG_TOP    = _p.SURFACE_IVORY
SYNC_MDL_CARD_BG_BOT    = "#EAD7BD"
SYNC_MDL_CARD_ALT_BORDER = "#B87A46"
SYNC_MDL_CARD_ALT_BG_TOP = "#FFF4E5"
SYNC_MDL_CARD_ALT_BG_BOT = "#ECD1B5"

SYNC_MDL_CARD_TITLE_SIZE = 18  # pt
SYNC_MDL_CARD_BODY_SIZE  = 16  # pt
SYNC_MDL_CARD_HELPER_SIZE = 13 # pt
SYNC_MDL_CARD_BODY_CLR   = _p.TEXT_PRI
SYNC_MDL_CARD_HELPER_CLR = _p.TEXT_SEC

SYNC_MDL_BADGE_PAD_H    = 10   # px
SYNC_MDL_BADGE_PAD_V    = 4    # px
SYNC_MDL_BADGE_MIN_H    = 24   # px — minimum pill height (semicircular ends)
SYNC_MDL_BADGE_SIZE     = 10   # pt
SYNC_MDL_BADGE_TOP      = IF_SW_BADGE_TOP
SYNC_MDL_BADGE_BOT      = IF_SW_BADGE_BOT
SYNC_MDL_BADGE_ALT_TOP  = IF_SW_BADGE_SOFT_TOP
SYNC_MDL_BADGE_ALT_BOT  = IF_SW_BADGE_SOFT_BOT
SYNC_MDL_BADGE_TEXT     = IF_SW_BADGE_FG

SYNC_MDL_BTN_H          = 44   # px
SYNC_MDL_BTN_RADIUS     = 8    # px
SYNC_MDL_BTN_SIZE       = 13   # pt
SYNC_MDL_BTN_PRIMARY_BORDER = _p.ACCENT_BORDER
SYNC_MDL_BTN_PRIMARY_TOP    = _p.ACCENT_GRAD_TOP
SYNC_MDL_BTN_PRIMARY_MID    = _p.ACCENT_GRAD_MID
SYNC_MDL_BTN_PRIMARY_BOT    = _p.ACCENT_GRAD_BOT
SYNC_MDL_BTN_SEC_BORDER     = _p.BORDER_BRONZE
SYNC_MDL_BTN_SEC_TOP        = _p.EJECT_BTN_TOP
SYNC_MDL_BTN_SEC_BOT        = _p.EJECT_BTN_BOT
SYNC_MDL_BTN_SEC_TEXT       = _p.TEXT_PRI
SYNC_MDL_BTN_DANGER_BORDER  = "#752617"
SYNC_MDL_BTN_DANGER_TOP     = "#cf5a38"
SYNC_MDL_BTN_DANGER_MID     = "#a83a22"
SYNC_MDL_BTN_DANGER_BOT     = "#802715"
SYNC_MDL_BTN_DANGER_TEXT    = "#fff7ed"

SYNC_MDL_FOOTER_PAD_H   = 24   # px
SYNC_MDL_FOOTER_PAD_B   = 22   # px
SYNC_MDL_FOOTER_BTN_W   = 130  # px — minimum footer button width (grows to fit label)
SYNC_MDL_FOOTER_GAP     = 12   # px

SYNC_MDL_CONFIRM_BODY_PAD = 22 # px
SYNC_MDL_CONFIRM_TEXT_SIZE = 12 # pt
SYNC_MDL_CONFIRM_TEXT_CLR  = _p.TEXT_PRI

SYNC_MDL_SAFETY_BORDER  = "#d1a979"
SYNC_MDL_SAFETY_BG      = "rgba(255, 246, 232, 0.72)"
SYNC_MDL_SAFETY_TEXT    = "#5c4128"
SYNC_MDL_SAFETY_SIZE    = 13   # pt
SYNC_MDL_SAFETY_ICON    = 24   # px

# ═══════════════════════════════════════════════════════════════════════════════
#  TOOLS PAGE  (debugger + session logs)
# ═══════════════════════════════════════════════════════════════════════════════
TOOLS_TAB_H              = IF_TAB_H
TOOLS_TAB_FONT           = IF_TAB_FONT
TOOLS_PANEL_BORDER       = IF_DEVICE_BANNER_BORDER
TOOLS_PANEL_TOP          = IF_DEVICE_BANNER_TOP
TOOLS_PANEL_BOT          = IF_DEVICE_BANNER_BOT
TOOLS_PANEL_RADIUS       = 10   # px
TOOLS_PANEL_PAD          = 12   # px
TOOLS_CONSOLE_BG         = PANEL_HDR_GRAD_BOT   # darkest branded brown (#3b2917)
TOOLS_CONSOLE_FG         = LM_PANEL_HDR_TEXT_COLOR
TOOLS_CONSOLE_BORDER     = "#7A5128"
TOOLS_INPUT_BG           = _p.SURFACE_CREAM
TOOLS_INPUT_BORDER       = _p.BORDER_CARD
TOOLS_INPUT_FG           = _p.TEXT_PRI
TOOLS_MUTED_FG           = IF_DEVICE_META_FG
TOOLS_LOG_FONT           = 11   # pt
TOOLS_SECTION_ICON       = 28   # px — header icon tile
TOOLS_SECTION_TITLE_PX   = 16   # pt
TOOLS_SECTION_GAP        = 12   # px — gap between Session Log / Log Viewer cards
TOOLS_PATH_FIELD_H       = 36   # px
TOOLS_PATH_FIELD_RADIUS  = 8    # px
TOOLS_ACTION_BTN_H       = 32   # px
TOOLS_ACTION_BTN_FONT    = 12   # pt
TOOLS_EDITOR_BTN_TOP     = "#b8865a"
TOOLS_EDITOR_BTN_BOT     = "#7a5230"
TOOLS_EDITOR_BTN_BORDER  = "#5a3b1f"
TOOLS_DEBUG_BTN_H        = IF_DEVICE_BTN_H   # px
TOOLS_DEBUG_BTN_W        = IF_DEVICE_BTN_W   # px — compact conn / action buttons
TOOLS_CONN_COMBO_MIN_W   = 120   # px — COM dropdown min; expands to fill remaining row space
TOOLS_DEBUG_ROW_GAP      = 8    # px
TOOLS_NOW_PLAYING_MAX_H  = 72   # px

# Settings page body typography & controls
SETTINGS_BODY_FONT_PX  = 15   # px — primary option labels / field text
SETTINGS_HINT_FONT_PX  = 13   # px — descriptive hint text under options
SETTINGS_DIVIDER_COLOR = IF_CARD_BORDER
SETTINGS_FIELD_GAP     = 8    # px — label → control spacing in option rows
SETTINGS_HINT_GAP      = 36   # px — gap between left controls and hint column
SETTINGS_HINT_MIN_W    = 140  # px — narrowest hint column when window is small
SETTINGS_ACTION_INDENT = 22   # px — secondary actions nested under a checkbox
# Vintage checkbox (settings, modals, forms)
VINTAGE_CB_SIZE            = 24   # px — indicator width / height
VINTAGE_CB_FRAME_PAD       = 3    # px — inset so 2px border is not clipped
VINTAGE_CB_PEN_W           = 2    # px — indicator border width (must match paintEvent)
VINTAGE_CB_RADIUS          = 6    # px — indicator corner radius
VINTAGE_CB_SPACING         = 10   # px — gap between indicator and label
VINTAGE_CB_FONT_PX         = 16   # px — label font size
VINTAGE_CB_TEXT_FG         = IF_DEVICE_TITLE_FG
VINTAGE_CB_BG              = TOOLS_INPUT_BG
VINTAGE_CB_BORDER          = TOOLS_INPUT_BORDER
VINTAGE_CB_HOVER_BG        = LIGHT_BTN_HOVER
VINTAGE_CB_CHECK_TOP       = IF_INSTALL_BTN_TOP
VINTAGE_CB_CHECK_BOT       = IF_INSTALL_BTN_BOT
VINTAGE_CB_CHECK_BORDER    = IF_INSTALL_BTN_BORDER
VINTAGE_CB_CHECKMARK_FG    = IF_INSTALL_BTN_FG
VINTAGE_CB_DISABLED_FG     = IF_DEVICE_META_FG
VINTAGE_CB_DISABLED_BG     = "#f0e6d8"
VINTAGE_CB_DISABLED_BORDER = BORDER_SOFT
VINTAGE_CB_DISABLED_CHECK_BG = "#c9a882"
SETTINGS_SPIN_BTN_W    = 26   # px — stepper column width on VintageSpinBox
SETTINGS_SPIN_MIN_W    = 88   # px — minimum total field width
SETTINGS_SPIN_PAD_LEFT = 10   # px — QSS padding-left on the value area
SETTINGS_SPIN_PAD_RIGHT = 6   # px — gap between value text and stepper column
SETTINGS_SPIN_TEXT_SLACK = 30 # px — extra width so digits/suffix never clip
SETTINGS_SPIN_LAYOUT_MARGIN = 24  # px — inset when capping to parent/view width
SETTINGS_SPIN_VIEW_MIN_PX = 160   # px — ignore parent narrower than this (pre-layout)
SETTINGS_SPIN_BTN_TOP  = EJECT_BTN_GRAD_TOP
SETTINGS_SPIN_BTN_BOT  = EJECT_BTN_GRAD_BOT

# Track row drag handle + edit pencil (mirrors station row chrome)
TRACK_HANDLE_W         = 18   # px — ≡ column at row left
TRACK_LEFT_PAD         = 10   # px — inset before handle
TRACK_NUM_W            = 34   # px — two-digit index after handle
TRACK_RIGHT_RSVD       = 36   # px — reserved for edit pencil
TRACK_PENCIL_ROFF      = 22   # px — from row right edge to pencil
TRACK_PENCIL_W         = 18   # px
TRACK_HANDLE_COLOR     = BORDER_SOFT
TRACK_HANDLE_COLOR_SEL = "#7a5128"
TRACK_PENCIL_COLOR     = "#7a5128"
TRACK_PENCIL_COLOR_SEL = "#4a321e"

# ═══════════════════════════════════════════════════════════════════════════════
#  POPUP MENUS & SYSTEM DIALOGS  (context menus, QMessageBox, QInputDialog)
# ═══════════════════════════════════════════════════════════════════════════════
POPUP_MENU_BG            = _p.SURFACE_CREAM
POPUP_MENU_BORDER        = _p.BORDER_CARD
POPUP_MENU_FG            = TEXT_PRI
POPUP_MENU_SEL_BG        = TRACK_SEL
POPUP_MENU_SEL_FG        = TEXT_PRI
POPUP_MENU_SEP           = _p.BORDER_TAN
POPUP_MENU_RADIUS        = 8    # px
POPUP_MENU_PAD           = 6    # px
POPUP_MENU_ITEM_PAD_V    = 8    # px
POPUP_MENU_ITEM_PAD_H    = 14   # px

POPUP_DLG_BG_TOP         = "#fff8ef"
POPUP_DLG_BG_BOT         = "#f0ddc4"
POPUP_DLG_BORDER         = "#c7a06d"
POPUP_DLG_INPUT_BG       = TOOLS_INPUT_BG
POPUP_DLG_INPUT_BORDER   = TOOLS_INPUT_BORDER
POPUP_DLG_INPUT_FG       = TOOLS_INPUT_FG
POPUP_DLG_BTN_TOP        = OUTLINE_BTN_GRAD_TOP
POPUP_DLG_BTN_BOT        = OUTLINE_BTN_GRAD_BOT
POPUP_DLG_BTN_BORDER     = LM_SD_BTN_BORDER
POPUP_DLG_BTN_RADIUS     = LM_SD_BTN_RADIUS
POPUP_DLG_PRIMARY_TOP    = IF_INSTALL_BTN_TOP
POPUP_DLG_PRIMARY_MID    = IF_INSTALL_BTN_MID
POPUP_DLG_PRIMARY_BOT    = IF_INSTALL_BTN_BOT
POPUP_DLG_PRIMARY_BORDER = IF_INSTALL_BTN_BORDER
POPUP_DLG_PRIMARY_FG     = IF_INSTALL_BTN_FG

# Tooltips (cream panel — Fusion default is dark on Windows)
TOOLTIP_BG               = POPUP_MENU_BG
TOOLTIP_FG               = TEXT_PRI
TOOLTIP_BORDER           = POPUP_MENU_BORDER
TOOLTIP_RADIUS           = 6    # px
TOOLTIP_PAD_V            = 6    # px
TOOLTIP_PAD_H            = 10   # px
TOOLTIP_FONT_PX          = IF_DEVICE_META_SIZE + 1


def outline_button_stylesheet(*, font_px: int | None = None, font_weight: int = 700) -> str:
    """Shared QSS for cream outline buttons (library bar, Details, …)."""
    from gui import ui_scale as u

    fs = u.px(font_px if font_px is not None else LIBBAR_BTN_FONT_SIZE)
    m = u.px(OUTLINE_BTN_EDGE_MARGIN)
    bw = OUTLINE_BTN_BORDER_W
    radius = u.px(LIBBAR_BTN_RADIUS)
    return (
        f"QPushButton {{"
        f"  background: qlineargradient("
        f"    x1:0, y1:0, x2:0, y2:1,"
        f"    stop:0 {OUTLINE_BTN_GRAD_TOP},"
        f"    stop:1 {OUTLINE_BTN_GRAD_BOT}"
        f"  );"
        f"  border: {bw}px solid {BORDER};"
        f"  border-radius: {radius}px;"
        f"  padding: {LIBBAR_BTN_PADDING};"
        f"  margin-left: {m}px;"
        f"  margin-right: {m}px;"
        f"  font-size: {fs}px;"
        f"  font-weight: {font_weight};"
        f"  color: {TEXT_PRI};"
        f"  outline: none;"
        f"}}"
        f"QPushButton:hover   {{ background: {LIGHT_BTN_HOVER}; border: {bw}px solid {BORDER}; }}"
        f"QPushButton:pressed {{ background: {LIGHT_BTN_PRESSED}; border: {bw}px solid {BORDER}; }}"
        f"QPushButton:focus   {{ outline: none; border: {bw}px solid {BORDER}; }}"
    )


def outline_button_width_for_text(text: str, text_width_px: int, *, min_w: int = 0) -> int:
    """Minimum widget width so label + padding + border + edge margin are not clipped."""
    slack = (
        2 * OUTLINE_BTN_PAD_H
        + 2 * OUTLINE_BTN_BORDER_W
        + 2 * OUTLINE_BTN_EDGE_MARGIN
        + 2
    )
    return max(min_w, text_width_px + slack)
