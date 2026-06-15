# gui/widgets/common — shared components reused across multiple widgets
from .delegates import StationItemDelegate, TrackItemDelegate, RowBgDelegate, configure_track_title_item
from .delegates import STATION_NUM_ROLE, STATION_NAME_ROLE, STATION_COUNT_ROLE
from .mockup_scrollbar import MockupScrollBar, wrap_with_mockup_scrollbar, sync_track_table_column_widths