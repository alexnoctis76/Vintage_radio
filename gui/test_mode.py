"""Test mode emulator for Vintage Radio behavior.

This module provides a GUI test environment that runs the SAME core logic
as the firmware (main.py). The shared logic is in radio_core.py.

Architecture:
- RadioCore (radio_core.py): Shared state machine logic
- PygameHardwareEmulator (hardware_emulator.py): GUI hardware implementation
- TestModeWidget (this file): UI components and event handling
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import random
import threading
import time
from typing import Dict, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from .database import DatabaseManager
from .hardware_emulator import PygameHardwareEmulator
from .sd_manager import SDManager

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_core import (
    RadioCore, HardwareInterface,
    DF_BOOT_MS, LONG_PRESS_MS, TAP_WINDOW_MS,
    MODE_ALBUM, MODE_PLAYLIST, MODE_SHUFFLE, MODE_RADIO,
    ticks_ms, ticks_diff,
)

# Keep these for backward compatibility in UI
FADE_IN_S = 2.4
BUSY_CONFIRM_MS = 1800
WAV_FILE = "AMradioSound.wav"


# Legacy dataclasses kept for UI compatibility
@dataclass
class AlbumState:
    album_id: int
    name: str
    tracks: List[Dict]


@dataclass
class PlaylistState:
    playlist_id: int
    name: str
    tracks: List[Dict]


@dataclass
class RadioStation:
    """A radio station representing a collection of tracks (library/album/playlist)."""
    name: str
    tracks: List[Dict]
    total_duration_ms: int
    start_offset_ms: int


class RadioFaceView(QtWidgets.QGraphicsView):
    dial_changed = QtCore.pyqtSignal(int)
    button_pressed = QtCore.pyqtSignal()
    button_released = QtCore.pyqtSignal()

    def __init__(self, png_path: Path, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self.scene)
        
        # Enable mouse tracking for cursor changes
        self.setMouseTracking(True)
        # Ensure clicks aren't consumed for focus - we want every click to register
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        # Load main radio PNG
        self.radio_pixmap = QtGui.QPixmap(str(png_path))
        self.radio_item = QtWidgets.QGraphicsPixmapItem(self.radio_pixmap)
        self.radio_item.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
        self.scene.addItem(self.radio_item)

        # Scene size from PNG dimensions
        self.scene.setSceneRect(0, 0, self.radio_pixmap.width(), self.radio_pixmap.height())
        self.setMinimumHeight(280)

        # PNG pixel coordinates (from Figma export)
        # Dial center marked with #EA2A46 at 1872.5, 2043
        self.base_dial_center = QtCore.QPointF(1872.5, 2043.0)
        self.base_dial_radius = 168.0  # Approximate, adjust if needed
        
        # Scale factor for other elements: PNG vs original SVG viewBox (600x607)
        self.base_svg_size = QtCore.QSizeF(600.0, 607.0)
        self.render_scale = self.radio_pixmap.width() / self.base_svg_size.width()
        
        # Button position - the small ellipse on the radio body  
        # PNG dimensions: 2399 x 2426
        # User-specified: center at (1200, 840)
        self.base_button_center = QtCore.QPointF(1200.0, 840.0)
        self.base_button_rx = 80.0  # Hit area width
        self.base_button_ry = 50.0  # Hit area height
        
        # Power indicator position (scaled from SVG coordinates)
        self.base_power_center = QtCore.QPointF(394.692 * self.render_scale, 528.948 * self.render_scale)
        self.base_power_radius = 7.5 * self.render_scale

        self.dial_center = self.base_dial_center
        self.dial_radius = self.base_dial_radius
        self.button_center = self.base_button_center
        self.button_rx = self.base_button_rx
        self.button_ry = self.base_button_ry
        self.power_center = self.base_power_center
        self.power_radius = self.base_power_radius

        # Load dial overlay PNG
        dial_path = Path(__file__).resolve().parent / "resources" / "volDial.png"
        self.dial_pixmap_base = QtGui.QPixmap(str(dial_path))
        self.dial_item = QtWidgets.QGraphicsPixmapItem(self.dial_pixmap_base)
        self.dial_item.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
        self.dial_item.setZValue(10)
        self.scene.addItem(self.dial_item)

        # Load power indicator PNG
        power_path = Path(__file__).resolve().parent / "resources" / "powerInd.png"
        self.power_pixmap_on = QtGui.QPixmap(str(power_path))
        self.power_pixmap_off = self._create_off_power_pixmap(self.power_pixmap_on)
        self.power_indicator = QtWidgets.QGraphicsPixmapItem(self.power_pixmap_on)
        self.power_indicator.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
        self.power_indicator.setZValue(11)
        self.scene.addItem(self.power_indicator)

        self._dial_drag = False
        self._button_down = False
        self._current_dial_value = 100
        self._update_layout()
        self.set_dial_value(100)

    def _create_off_power_pixmap(self, on_pixmap: QtGui.QPixmap) -> QtGui.QPixmap:
        """Create a darkened version of the power indicator for off state."""
        off = QtGui.QPixmap(on_pixmap.size())
        off.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(off)
        painter.drawPixmap(0, 0, on_pixmap)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceAtop)
        painter.fillRect(off.rect(), QtGui.QColor(58, 58, 58, 200))
        painter.end()
        return off

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fitInView(self.scene.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def set_power(self, on: bool) -> None:
        pixmap = self.power_pixmap_on if on else self.power_pixmap_off
        self.power_indicator.setPixmap(pixmap)

    def set_dial_value(self, value: int) -> None:
        self._current_dial_value = value
        angle_deg = -135 + (value / 100.0) * 270.0
        # Rotate the dial pixmap around its center
        transform = QtGui.QTransform()
        center = QtCore.QPointF(self.dial_pixmap_base.width() / 2, self.dial_pixmap_base.height() / 2)
        transform.translate(center.x(), center.y())
        transform.rotate(angle_deg)
        transform.translate(-center.x(), -center.y())
        rotated = self.dial_pixmap_base.transformed(transform, QtCore.Qt.TransformationMode.SmoothTransformation)
        self.dial_item.setPixmap(rotated)
        # Recenter after rotation (rotated pixmap may be larger)
        self.dial_item.setPos(
            self.dial_center.x() - rotated.width() / 2,
            self.dial_center.y() - rotated.height() / 2,
        )

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        pos = self.mapToScene(event.position().toPoint())
        if self._inside_button(pos):
            self._button_down = True
            self.button_pressed.emit()
            event.accept()
            return
        if self._inside_dial(pos):
            self._dial_drag = True
            self._update_dial_from_pos(pos)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        # Treat double-clicks as regular clicks so rapid tapping works
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        pos = self.mapToScene(event.position().toPoint())
        
        if self._dial_drag:
            self._update_dial_from_pos(pos)
            event.accept()
            return
        
        # Update cursor based on what's under the mouse
        if self._inside_button(pos) or self._inside_dial(pos):
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._button_down:
            self._button_down = False
            self.button_released.emit()
            event.accept()
            return
        if self._dial_drag:
            self._dial_drag = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _inside_dial(self, pos: QtCore.QPointF) -> bool:
        dx = pos.x() - self.dial_center.x()
        dy = pos.y() - self.dial_center.y()
        return (dx * dx + dy * dy) <= (self.dial_radius * self.dial_radius)

    def _inside_button(self, pos: QtCore.QPointF) -> bool:
        dx = pos.x() - self.button_center.x()
        dy = pos.y() - self.button_center.y()
        return (dx * dx) / (self.button_rx * self.button_rx) + (dy * dy) / (self.button_ry * self.button_ry) <= 1

    def _update_dial_from_pos(self, pos: QtCore.QPointF) -> None:
        dx = pos.x() - self.dial_center.x()
        dy = pos.y() - self.dial_center.y()
        angle = math.degrees(math.atan2(dy, dx))
        angle = max(-135, min(135, angle))
        value = int(((angle + 135) / 270.0) * 100)
        self.set_dial_value(value)
        self.dial_changed.emit(value)

    def _update_layout(self) -> None:
        # Coordinates are already scaled by render_scale, just use them directly
        self.dial_center = self.base_dial_center
        self.dial_radius = self.base_dial_radius
        self.button_center = self.base_button_center
        self.button_rx = self.base_button_rx
        self.button_ry = self.base_button_ry
        self.power_center = self.base_power_center
        self.power_radius = self.base_power_radius

        # Position dial (will be repositioned on rotation in set_dial_value)
        self.set_dial_value(self._current_dial_value)

        # Position power indicator centered
        pw = self.power_pixmap_on.width()
        ph = self.power_pixmap_on.height()
        self.power_indicator.setPos(
            self.power_center.x() - pw / 2,
            self.power_center.y() - ph / 2,
        )


class TestModeWidget(QtWidgets.QWidget):
    """
    GUI Test Mode that uses the SAME RadioCore logic as the firmware.
    
    This widget delegates all state machine operations to RadioCore,
    ensuring identical behavior between the GUI test mode and the actual device.
    """
    
    def __init__(self, db: DatabaseManager, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        
        # Initialize state variables FIRST (needed by log callback)
        self.albums: List[AlbumState] = []
        self.playlists: List[PlaylistState] = []
        self.shuffle_tracks: List[Dict] = []
        self.shuffle_index = 0
        self.mode = "album"
        self.current_album_index = 0
        self.current_track = 1
        self.is_playing = False
        
        # Initialize hardware emulator (pygame-based)
        am_wav = Path(__file__).resolve().parent / "resources" / "AMradioSound.wav"
        self.hw_emulator = PygameHardwareEmulator(
            db=db,
            log_callback=self._log,
            am_wav_path=am_wav if am_wav.exists() else None,
        )
        
        # Initialize RadioCore - THE SAME LOGIC AS FIRMWARE
        self.core = RadioCore(self.hw_emulator)
        self.resume_position_ms: Optional[int] = None
        self.resume_mode: Optional[str] = None
        self.resume_album_index: Optional[int] = None
        self.resume_track: Optional[int] = None
        self.audio_ready = False
        self.am_sound = None
        self.am_channel = None
        self.target_volume = 1.0
        self._playback_timer = QtCore.QTimer(self)
        self._playback_timer.setInterval(200)
        self._playback_timer.timeout.connect(self._poll_playback)
        self._fade_timer = QtCore.QTimer(self)
        self._fade_timer.setInterval(100)
        self._fade_timer.timeout.connect(self._tick_fade)
        self._fade_steps = 0
        self._fade_step = 0
        self._am_fade_steps = 0
        self._am_fade_step = 0
        # Use threading.Timer instead of QTimer for tap resolution (more reliable with QGraphicsView)
        self._tap_thread_timer: Optional[threading.Timer] = None
        self.tap_count = 0
        self._last_tap_time: Optional[float] = None  # time.monotonic() of last tap
        self.rail2_on = True
        self._press_timer = QtCore.QElapsedTimer()
        self._long_press_fired = False
        self._tuning_timer = QtCore.QTimer(self)
        self._tuning_timer.setSingleShot(True)
        self._tuning_timer.timeout.connect(self._lock_radio_station)
        self.is_tuning = False
        self._pending_track_playback = None  # (track, start_ms) tuple for delayed playback after AM overlay
        # Radio stations: [Library, Album1, Album2, ..., Playlist1, Playlist2, ...]
        self.radio_stations: List[RadioStation] = []
        self.radio_station_index = 0
        self.radio_mode_start_time: Optional[float] = None  # time.monotonic() when radio mode started
        self.log_path: Optional[Path] = None
        
        # Timer to call RadioCore.tick() regularly
        self._core_tick_timer = QtCore.QTimer(self)
        self._core_tick_timer.setInterval(20)  # 20ms = 50Hz
        self._core_tick_timer.timeout.connect(self._core_tick)
        self._core_tick_timer.start()

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        
        # SD card sync warning label (red text if out of sync)
        self.sd_sync_warning = QtWidgets.QLabel()
        self.sd_sync_warning.setWordWrap(True)
        self.sd_sync_warning.setStyleSheet("color: red; font-weight: bold;")
        self.sd_sync_warning.setVisible(False)
        
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        
        # Initialize SD manager for sync checking
        self.sd_manager = SDManager(db)

        self.refresh_btn = QtWidgets.QPushButton("Refresh Library")
        self.refresh_btn.clicked.connect(self.refresh_from_db)

        self.power_toggle = QtWidgets.QCheckBox("Power On (Rail 2)")
        self.power_toggle.setChecked(True)
        self.power_toggle.toggled.connect(self.toggle_power)
        self.knob_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.knob_slider.setRange(0, 100)
        self.knob_slider.setValue(100)
        self.knob_slider.valueChanged.connect(self.update_knob_volume)
        self.knob_label = QtWidgets.QLabel("Knob: 100%")
        self.mode_label = QtWidgets.QLabel("Mode: Album")
        self.radio_button = QtWidgets.QPushButton("Radio Button")
        self.radio_button.setCheckable(True)
        self.radio_button.pressed.connect(lambda: self.on_button_pressed("GUI"))
        self.radio_button.released.connect(lambda: self.on_button_released("GUI"))
        self.mode_album_btn = QtWidgets.QPushButton("Album Mode")
        self.mode_playlist_btn = QtWidgets.QPushButton("Playlist Mode")
        self.mode_shuffle_btn = QtWidgets.QPushButton("Shuffle Mode")
        self.mode_radio_btn = QtWidgets.QPushButton("Radio Mode")
        self.mode_album_btn.clicked.connect(lambda: self._switch_mode("album"))
        self.mode_playlist_btn.clicked.connect(lambda: self._switch_mode("playlist"))
        self.mode_shuffle_btn.clicked.connect(lambda: self._switch_mode("shuffle"))
        self.mode_radio_btn.clicked.connect(lambda: self._switch_mode("radio"))
        self.mode_hint_label = QtWidgets.QLabel(
            "Tap: Next | Double-tap: Prev | Triple-tap: Restart | "
            "Hold: Next album | Tap+Hold: Switch mode | 2 taps+Hold: Shuffle current | 3 taps+Hold: Shuffle all"
        )
        self.mode_hint_label.setWordWrap(True)
        self.radio_dial = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.radio_dial.setRange(0, 100)
        self.radio_dial.setValue(50)
        self.radio_dial.valueChanged.connect(self._tune_radio)
        self.radio_dial_label = QtWidgets.QLabel("Radio Dial")
        png_path = Path(__file__).resolve().parent / "resources" / "vintage_radio.png"
        self.radio_face = RadioFaceView(png_path)
        self.radio_face.dial_changed.connect(self.knob_slider.setValue)
        # Use QueuedConnection to avoid timing issues with QGraphicsView event processing
        self.radio_face.button_pressed.connect(
            lambda: self.on_button_pressed("PNG"), 
            QtCore.Qt.ConnectionType.QueuedConnection
        )
        self.radio_face.button_released.connect(
            lambda: self.on_button_released("PNG"),
            QtCore.Qt.ConnectionType.QueuedConnection
        )

        self.play_btn = QtWidgets.QPushButton("Play Current")
        self.play_btn.clicked.connect(self.play_current)
        self.finish_btn = QtWidgets.QPushButton("Finish Track")
        self.finish_btn.clicked.connect(self.finish_track)

        tap_layout = QtWidgets.QHBoxLayout()
        single_btn = QtWidgets.QPushButton("Tap (Next)")
        double_btn = QtWidgets.QPushButton("Double-Tap (Prev)")
        triple_btn = QtWidgets.QPushButton("Triple-Tap (Restart)")
        long_btn = QtWidgets.QPushButton("Hold (Next Source)")
        single_btn.clicked.connect(self.single_tap)
        double_btn.clicked.connect(self.double_tap)
        triple_btn.clicked.connect(self.triple_tap)
        long_btn.clicked.connect(self.long_press)
        tap_layout.addWidget(single_btn)
        tap_layout.addWidget(double_btn)
        tap_layout.addWidget(triple_btn)
        tap_layout.addWidget(long_btn)
        
        # Set pointing hand cursor for all clickable buttons
        pointer_cursor = QtCore.Qt.CursorShape.PointingHandCursor
        for btn in [
            self.refresh_btn, self.radio_button, self.mode_album_btn,
            self.mode_playlist_btn, self.mode_shuffle_btn, self.mode_radio_btn,
            self.play_btn, self.finish_btn, single_btn, double_btn, triple_btn, long_btn
        ]:
            btn.setCursor(pointer_cursor)

        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(self.refresh_btn)
        top_layout.addWidget(self.power_toggle)
        top_layout.addWidget(self.knob_label)
        top_layout.addWidget(self.knob_slider)
        top_layout.addWidget(self.mode_label)
        top_layout.addStretch()
        
        # SD sync warning layout
        sync_warning_layout = QtWidgets.QHBoxLayout()
        sync_warning_layout.addWidget(self.sd_sync_warning)
        sync_warning_layout.addStretch()
        top_layout.addWidget(self.play_btn)
        top_layout.addWidget(self.finish_btn)

        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.addWidget(self.mode_album_btn)
        mode_layout.addWidget(self.mode_playlist_btn)
        mode_layout.addWidget(self.mode_shuffle_btn)
        mode_layout.addWidget(self.mode_radio_btn)
        mode_layout.addWidget(self.radio_button)

        radio_layout = QtWidgets.QHBoxLayout()
        radio_layout.addWidget(self.radio_dial_label)
        radio_layout.addWidget(self.radio_dial)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addLayout(sync_warning_layout)  # SD sync warning (red text if out of sync)
        layout.addLayout(mode_layout)
        layout.addWidget(self.mode_hint_label)
        layout.addWidget(self.radio_face)
        layout.addLayout(radio_layout)
        layout.addWidget(self.status_label)
        layout.addLayout(tap_layout)
        layout.addWidget(QtWidgets.QLabel("Event Log:"))
        layout.addWidget(self.log, 1)

        # Use hw_emulator's audio instead of duplicate init
        self.audio_ready = self.hw_emulator._audio_ready
        self.am_sound = self.hw_emulator._am_sound
        
        self.refresh_from_db()
        # Check SD card sync status on initialization
        # Use QTimer to ensure widget is visible before checking
        QtCore.QTimer.singleShot(100, self._check_sd_sync)
        self._init_log_file()
        # Auto-start playback on boot (like firmware does)
        if self.rail2_on:
            QtCore.QTimer.singleShot(DF_BOOT_MS, self._power_on_handler)

    def _core_tick(self) -> None:
        """Called regularly to process RadioCore timing events."""
        if not self.rail2_on:
            return
        
        # Let RadioCore process timing-based events (tap window timeout)
        if self.core.tick():
            self._sync_from_core()
            self._update_status("Action from core tick.")
        
        # Check if track finished
        if self.hw_emulator.check_track_finished():
            self.core.on_track_finished()
            self._sync_from_core()
            self._update_status("Track finished, auto-advanced.")
    
    def _sync_from_core(self) -> None:
        """Sync widget state from RadioCore."""
        self.mode = self.core.mode
        self.current_album_index = self.core.current_album_index
        self.current_track = self.core.current_track
        self.shuffle_index = self.core.shuffle_index
        self.is_playing = self.core.is_playing
        self.radio_station_index = self.core.radio_station_index
        
        # Sync shuffle tracks from core (if available)
        if self.core.shuffle_tracks:
            self.shuffle_tracks = self.core.shuffle_tracks
        
        # Sync radio stations from core (if available)
        if self.core.radio_stations:
            self.radio_stations = self.core.radio_stations
        
        # Update mode label
        if hasattr(self, 'mode_label'):
            self.mode_label.setText(f"Mode: {self.mode.title()}")
    
    def showEvent(self, event):
        """Called when widget is shown - check SD sync status."""
        super().showEvent(event)
        # Check sync status when tab becomes visible
        self._check_sd_sync()
    
    def _check_sd_sync(self) -> None:
        """Check if library is in sync with SD card and show warning if not."""
        results = self.sd_manager.validate_sd()
        
        # Filter out size mismatches that are due to format conversion
        # (These are expected when files are converted to MP3)
        actual_size_mismatches = [
            item for item in results.get("size_mismatch", [])
            if item.get("reason") == "size_mismatch"
        ]
        
        # Count total issues (excluding format conversion size differences)
        total_issues = (
            len(results.get("missing_sd_path", [])) +
            len(results.get("missing_file", [])) +
            len(actual_size_mismatches) +
            len(results.get("hash_mismatch", []))
        )
        
        if total_issues > 0:
            # Show red warning
            missing_sd = len(results.get("missing_sd_path", []))
            missing_files = len(results.get("missing_file", []))
            hash_mismatch = len(results.get("hash_mismatch", []))
            
            warning_parts = []
            if missing_sd > 0:
                warning_parts.append(f"{missing_sd} missing SD paths")
            if missing_files > 0:
                warning_parts.append(f"{missing_files} missing files")
            if len(actual_size_mismatches) > 0:
                warning_parts.append(f"{len(actual_size_mismatches)} size mismatches")
            if hash_mismatch > 0:
                warning_parts.append(f"{hash_mismatch} hash mismatches")
            
            warning_text = f"⚠️ Library out of sync with SD card: {', '.join(warning_parts)}. Sync to SD card to test with actual hardware files."
            self.sd_sync_warning.setText(warning_text)
            self.sd_sync_warning.setVisible(True)
        else:
            # All in sync
            self.sd_sync_warning.setVisible(False)
    
    def refresh_from_db(self) -> None:
        self.albums = []
        self.playlists = []
        for album in self.db.list_albums():
            tracks = self.db.list_album_songs(album["id"])
            self.albums.append(
                AlbumState(
                    album_id=album["id"],
                    name=album["name"],
                    tracks=[dict(track) for track in tracks],
                )
            )
        for playlist in self.db.list_playlists():
            tracks = self.db.list_playlist_songs(playlist["id"])
            self.playlists.append(
                PlaylistState(
                    playlist_id=playlist["id"],
                    name=playlist["name"],
                    tracks=[dict(track) for track in tracks],
                )
            )
        if not self.albums:
            self.albums.append(
                AlbumState(
                    album_id=0,
                    name="Library",
                    tracks=[dict(track) for track in self.db.list_songs()],
                )
            )
        if not self.playlists:
            self.playlists.append(
                PlaylistState(
                    playlist_id=0,
                    name="Library",
                    tracks=[dict(track) for track in self.db.list_songs()],
                )
            )
        # Initialize local shuffle tracks as fallback
        if not self.shuffle_tracks:
            self.shuffle_tracks = [dict(track) for track in self.db.list_songs()]
            random.shuffle(self.shuffle_tracks)
            self.shuffle_index = 0
        
        # Initialize RadioCore with data from database
        self.core._load_data()
        
        # Clear radio stations so they get reinitialized with updated SD card paths
        # This ensures radio mode uses the latest files after SD sync
        if self.core.radio_stations:
            self.core.radio_stations = []
            self.core.radio_mode_start_ms = None
            self.hw_emulator.log("Radio stations cleared - will reinitialize with updated SD card paths")
        
        self._sync_from_core()
        
        # DON'T overwrite state after sync - keep synced values from RadioCore
        # Only initialize radio_mode_start_time if not set
        if self.radio_mode_start_time is None:
            self.radio_mode_start_time = None
        
        self._update_status("Loaded albums for test mode.")
        # Check SD card sync status
        self._check_sd_sync()

    def current_album(self) -> AlbumState:
        return self.albums[self.current_album_index]

    def current_playlist(self) -> PlaylistState:
        index = min(self.current_album_index, len(self.playlists) - 1)
        return self.playlists[index]

    def play_current(self) -> None:
        if not self.audio_ready:
            self._log("Audio backend not available.")
            return
        if not self.rail2_on:
            self._log("Power is off.")
            return
        song = self._current_song()
        if song is None:
            self._log("No track to play.")
            return
        path = self._resolve_song_path(song)
        if path is None:
            self._log("Track file not found.")
            return
        self._start_playback(path)
        self._update_status("Play current track.")

    def finish_track(self) -> None:
        if not self.is_playing:
            self._log("Finish ignored (not playing).")
            return
        self._stop_playback()
        self._on_track_finished(auto=True)

    def single_tap(self, *, auto: bool = False) -> None:
        """Helper button: immediately advance to next track - uses RadioCore."""
        if not self.rail2_on:
            return
        self.core._single_tap()
        self._sync_from_core()
        self._update_status("Next track.")

    def double_tap(self) -> None:
        """Helper button: immediately go to previous track - uses RadioCore."""
        if not self.rail2_on:
            return
        self.core._double_tap()
        self._sync_from_core()
        self._update_status("Previous track.")

    def triple_tap(self) -> None:
        """Helper button: immediately restart current album/playlist - uses RadioCore."""
        if not self.rail2_on:
            return
        self.core._triple_tap()
        self._sync_from_core()
        self._update_status("Restarted album/playlist.")
    
    def _go_previous(self) -> None:
        """Go to previous track, handling all modes correctly."""
        if self.mode == "shuffle":
            if not self.shuffle_tracks:
                self._log("Shuffle list empty.")
                return
            if self.shuffle_index > 0:
                self.shuffle_index -= 1
            else:
                self.shuffle_index = len(self.shuffle_tracks) - 1
            self.current_track = self.shuffle_index + 1
            self._update_status("Previous track (shuffle).")
            self._start_playback_for_current()
            return
        
        if self.mode == "radio":
            # In radio mode, prev changes to previous station track
            station = self._get_current_radio_station()
            if station and station.tracks:
                if self.current_track > 1:
                    self.current_track -= 1
                else:
                    self.current_track = len(station.tracks)
                self._update_status("Previous track (radio).")
                self._start_playback_for_song(station.tracks[self.current_track - 1])
            return
        
        total = self._current_track_count()
        if self.current_track > 1:
            self.current_track -= 1
        else:
            self.current_track = total
        self._update_status("Previous track.")
        self._start_playback_for_current()
    
    def _restart_current(self) -> None:
        """Restart from track 1, handling all modes correctly."""
        if self.mode == "shuffle":
            # Re-shuffle and start from beginning
            random.shuffle(self.shuffle_tracks)
            self.shuffle_index = 0
            self.current_track = 1
            self._update_status("Restarted shuffle.")
            self._start_playback_for_current()
            return
        
        if self.mode == "radio":
            # In radio mode, restart plays from track 1 of current station
            self.current_track = 1
            station = self._get_current_radio_station()
            if station and station.tracks:
                self._update_status("Restarted radio station.")
                self._start_playback_for_song(station.tracks[0])
            return
        
        self.current_track = 1
        self._update_status("Restarted.")
        self._start_playback_for_current()
    
    def _get_current_radio_station(self) -> Optional[RadioStation]:
        """Get the current radio station if in radio mode."""
        if self.radio_stations and self.radio_station_index < len(self.radio_stations):
            return self.radio_stations[self.radio_station_index]
        return None

    def long_press(self) -> None:
        """Helper button: simulate long press - uses RadioCore."""
        if not self.rail2_on:
            return
        # Use RadioCore's long press handling
        self.core._handle_long_press()
        self._sync_from_core()
        self._update_status("Long press action.")
    
    def _go_next_source(self) -> None:
        """Advance to the next album, playlist, or radio station."""
        if self.mode == "playlist":
            if self.playlists:
                self.current_album_index = (self.current_album_index + 1) % len(self.playlists)
            self.current_track = 1
            self._update_status("Next playlist.")
            self._start_playback_for_current()
        elif self.mode == "shuffle":
            # In shuffle mode, long press re-shuffles
            random.shuffle(self.shuffle_tracks)
            self.shuffle_index = 0
            self.current_track = 1
            self._update_status("Re-shuffled library.")
            self._start_playback_for_current()
        elif self.mode == "radio":
            # In radio mode, go to next station (with AM overlay)
            if self.radio_stations:
                self.radio_station_index = (self.radio_station_index + 1) % len(self.radio_stations)
                self.current_track = 1
                station = self.radio_stations[self.radio_station_index]
                self._update_status(f"Next station: {station.name}")
                if station.tracks:
                    self._start_playback_for_song(station.tracks[0], with_am_overlay=True)
        else:
            # Album mode
            if self.albums:
                self.current_album_index = (self.current_album_index + 1) % len(self.albums)
            self.current_track = 1
            self._update_status("Next album.")
            self._start_playback_for_current()
    
    def _switch_to_current_shuffle(self) -> None:
        """Shuffle the current album, playlist, station, or re-shuffle if already shuffling."""
        if self.mode == "shuffle":
            # Already shuffling - re-shuffle the current list
            random.shuffle(self.shuffle_tracks)
            self.shuffle_index = 0
            self.current_track = 1
            self._log(f"Re-shuffled ({len(self.shuffle_tracks)} tracks)")
            self._update_status("Re-shuffled current.")
            if self.rail2_on:
                self._start_playback_for_current()
            return
        
        if self.mode == "radio":
            # Shuffle the current station's tracks
            station = self._get_current_radio_station()
            if station and station.tracks:
                self.shuffle_tracks = [dict(track) for track in station.tracks]
                source_name = station.name
            else:
                self._log("No radio station to shuffle.")
                return
        elif self.mode == "playlist":
            playlist = self.current_playlist()
            self.shuffle_tracks = [dict(track) for track in playlist.tracks]
            source_name = playlist.name
        else:
            album = self.current_album()
            self.shuffle_tracks = [dict(track) for track in album.tracks]
            source_name = album.name
        
        random.shuffle(self.shuffle_tracks)
        self.shuffle_index = 0
        self.current_track = 1
        self.mode = "shuffle"
        self._log(f"Shuffle mode: {source_name} ({len(self.shuffle_tracks)} tracks)")
        self.mode_label.setText(f"Mode: Shuffle ({source_name})")
        self._update_status(f"Shuffle: {source_name}")
        if self.rail2_on:
            self._start_playback_for_current()
    
    def _switch_to_library_shuffle(self) -> None:
        """Shuffle the entire library."""
        self.shuffle_tracks = [dict(track) for track in self.db.list_songs()]
        random.shuffle(self.shuffle_tracks)
        self.shuffle_index = 0
        self.current_track = 1
        self.mode = "shuffle"
        self._log(f"Shuffle mode: Full Library ({len(self.shuffle_tracks)} tracks)")
        self.mode_label.setText("Mode: Shuffle (Library)")
        self._update_status("Shuffle: Full Library")
        if self.rail2_on:
            self._start_playback_for_current()

    def _update_status(self, action: str) -> None:
        source_name = self._source_name()
        
        # Get current track info for accurate display
        song = self._current_song()
        track_title = song.get("title", "Unknown") if song else "Unknown"
        track_artist = song.get("artist", "Unknown") if song else "Unknown"
        track_album = song.get("album", "Unknown") if song else "Unknown"
        
        # Build status text based on mode
        if self.mode == "shuffle":
            # In shuffle mode, show the actual track's album and full track info
            track_count = len(self.shuffle_tracks) if self.shuffle_tracks else 0
            status = (
                f"Mode: {self.mode.title()} | Source: {source_name}\n"
                f"Track: {self.current_track}/{track_count} - {track_title}\n"
                f"Artist: {track_artist} | Album: {track_album}\n"
                f"Playing: {self.is_playing}"
            )
        elif self.mode == "radio":
            # In radio mode, show station info
            station = self._get_current_radio_station()
            station_name = station.name if station else "Unknown"
            track_count = len(station.tracks) if station and station.tracks else 0
            status = (
                f"Mode: {self.mode.title()} | Source: {source_name}\n"
                f"Station: {station_name} | Track: {self.current_track}/{track_count}\n"
                f"Now Playing: {track_title} ({track_artist})\n"
                f"Playing: {self.is_playing}"
            )
        else:
            # Album or Playlist mode - show source info
            if self.mode == "album":
                source = self.current_album()
            else:  # playlist
                source = self.current_playlist()
            status = (
                f"Mode: {self.mode.title()} | Source: {source_name}\n"
                f"Track: {self.current_track}/{self._track_count(source)} - {track_title}\n"
                f"Artist: {track_artist} | Album: {track_album}\n"
                f"Playing: {self.is_playing}"
            )
        
        self.status_label.setText(status)
        self._log(action)

    def _log(self, message: str) -> None:
        # Build log line, handling case where albums/playlists aren't loaded yet
        try:
            song = self._current_song()
            title = song.get("title") if song else None
            artist = song.get("artist") if song else None
            source_name = self._source_name()
            track_info = f"{self.mode.title()} | {source_name} | Track {self.current_track}"
            if title or artist:
                track_info = f"{track_info} - {title or 'Unknown'} ({artist or 'Unknown'})"
            line = f"{message} | {track_info}"
        except (AttributeError, IndexError):
            # During initialization, just log the message
            line = message
        
        # Append to GUI log widget if it exists
        if hasattr(self, 'log') and self.log is not None:
            self.log.append(line)
        else:
            print(f"[TestMode] {line}")
        
        # Also write to file if configured
        if hasattr(self, 'log_path') and self.log_path is not None:
            try:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"[{timestamp}] {line}\n")
            except OSError:
                pass

    def _track_count(self, album: AlbumState) -> int:
        return max(len(album.tracks), 1)

    def _current_song(self) -> Optional[Dict]:
        if self.mode == "radio":
            if not self.radio_stations or self.radio_station_index >= len(self.radio_stations):
                return None
            station = self.radio_stations[self.radio_station_index]
            if not station.tracks:
                return None
            track_index = max(self.current_track - 1, 0)
            if track_index >= len(station.tracks):
                return station.tracks[0] if station.tracks else None
            return station.tracks[track_index]
        if self.mode == "shuffle":
            if not self.shuffle_tracks:
                return None
            index = max(min(self.shuffle_index, len(self.shuffle_tracks) - 1), 0)
            return self.shuffle_tracks[index]
        if self.mode == "playlist":
            playlist = self.current_playlist()
            if not playlist.tracks:
                return None
            index = max(self.current_track - 1, 0)
            if index >= len(playlist.tracks):
                return None
            return playlist.tracks[index]
        album = self.current_album()
        if not album.tracks:
            return None
        index = max(self.current_track - 1, 0)
        if index >= len(album.tracks):
            return None
        return album.tracks[index]

    def _resolve_song_path(self, song: Dict) -> Optional[str]:
        sd_path = song.get("sd_path")
        if sd_path and Path(sd_path).exists():
            return sd_path
        file_path = song.get("file_path")
        if file_path and Path(file_path).exists():
            return file_path
        return None

    def _init_audio(self) -> None:
        try:
            import pygame
        except Exception:
            self.audio_ready = False
            self._log("pygame not available. Install pygame for audio playback.")
            return
        try:
            pygame.mixer.init()
            pygame.mixer.set_num_channels(2)
            self.audio_ready = True
            am_path = Path(__file__).resolve().parent / "resources" / WAV_FILE
            if am_path.exists():
                self.am_sound = pygame.mixer.Sound(str(am_path))
            else:
                self._log(f"Missing AM WAV: {WAV_FILE}")
        except Exception as exc:
            self.audio_ready = False
            self._log(f"Audio init failed: {exc}")

    def _poll_playback(self) -> None:
        """Poll playback state - just updates internal state.
        
        Auto-advance is handled by _core_tick() via RadioCore.
        """
        if not self.audio_ready:
            return
        try:
            import pygame
        except Exception:
            return
        # Just sync is_playing state - auto-advance is handled by _core_tick
        if self.is_playing and not pygame.mixer.music.get_busy():
            self.is_playing = False

    def _stop_playback(self) -> None:
        if not self.audio_ready:
            return
        try:
            import pygame
        except Exception:
            return
        pygame.mixer.music.stop()
        if self.am_channel is not None:
            self.am_channel.stop()
        self._fade_timer.stop()
        self.is_playing = False

    def _on_track_finished(self, *, auto: bool) -> None:
        self.is_playing = False
        self._update_status("Auto-advance." if auto else "Track finished.")
        self._advance_next()

    def toggle_power(self, on: bool) -> None:
        """Toggle power using RadioCore."""
        self.rail2_on = on
        self.radio_face.set_power(on)
        if not on:
            self.core.power_off()
            self._sync_from_core()
            self._update_status("Power off.")
        else:
            # Simulate DFPlayer boot delay
            QtCore.QTimer.singleShot(DF_BOOT_MS, self._power_on_handler)
    
    def _power_on_handler(self) -> None:
        """Handle power on after boot delay - uses RadioCore."""
        # Enable playback delay so we can sequence AM overlay before track
        self.hw_emulator.set_delay_playback(True)
        
        # Play AM overlay first
        self.hw_emulator.play_am_overlay()
        
        if not hasattr(self, '_core_initialized'):
            self._core_initialized = True
            self.core.init()  # First boot: load state + start playback (will be delayed)
        else:
            self.core.power_on_handler()  # Resume from power off (will be delayed)
        
        self._sync_from_core()
        
        # Schedule track playback after AM overlay finishes
        if self.am_sound:
            am_duration_ms = int(self.am_sound.get_length() * 1000)
            QtCore.QTimer.singleShot(am_duration_ms, self._start_track_after_am)
        else:
            # No AM sound, play immediately
            self._start_track_after_am()
        
        self._update_status("Power on, playback started.")

    def update_knob_volume(self, value: int) -> None:
        self.knob_label.setText(f"Knob: {value}%")
        self.radio_face.set_dial_value(value)
        if not self.audio_ready:
            return
        try:
            import pygame
        except Exception:
            return
        self.target_volume = max(0.0, min(1.0, value / 100.0))
        if self.mode == "radio" and self.is_tuning:
            pygame.mixer.music.set_volume(min(0.2, self.target_volume))
        else:
            pygame.mixer.music.set_volume(self.target_volume)

    def _register_tap(self) -> None:
        if not self.rail2_on:
            return
        old_count = self.tap_count
        self.tap_count += 1
        self._last_tap_time = time.monotonic()
        self._log(f"TAP REGISTERED: {old_count} -> {self.tap_count}, window open for {TAP_WINDOW_MS}ms")
        
        # Cancel any existing timer
        if self._tap_thread_timer is not None:
            self._tap_thread_timer.cancel()
        
        # Use threading.Timer and invoke callback on main thread via QTimer.singleShot
        def on_timeout():
            # Use QTimer.singleShot(0, ...) to safely call _resolve_taps on the main Qt thread
            QtCore.QTimer.singleShot(0, self._resolve_taps)
        
        self._tap_thread_timer = threading.Timer(TAP_WINDOW_MS / 1000.0, on_timeout)
        self._tap_thread_timer.start()

    def _resolve_taps(self) -> None:
        """Called when tap window expires - execute the tap action."""
        self._log(f"Timer expired, resolving {self.tap_count} tap(s)")
        if self.tap_count >= 3:
            self._restart_current()
        elif self.tap_count == 2:
            self._go_previous()
        elif self.tap_count == 1:
            self._advance_next()
        self.tap_count = 0

    def _advance_next(self) -> None:
        """Advance to the next track, handling all modes correctly."""
        if self.mode == "shuffle":
            if not self.shuffle_tracks:
                self._log("Shuffle list empty.")
                return
            self.shuffle_index += 1
            if self.shuffle_index >= len(self.shuffle_tracks):
                random.shuffle(self.shuffle_tracks)
                self.shuffle_index = 0
            self.current_track = self.shuffle_index + 1
            self._update_status("Next track (shuffle).")
            self._start_playback_for_current()
            return
        
        if self.mode == "radio":
            station = self._get_current_radio_station()
            if station and station.tracks:
                total = len(station.tracks)
                if self.current_track < total:
                    self.current_track += 1
                else:
                    self.current_track = 1
                self._update_status("Next track (radio).")
                self._start_playback_for_song(station.tracks[self.current_track - 1])
            return
        
        # Album or Playlist mode
        total = self._current_track_count()
        if self.current_track < total:
            self.current_track += 1
            self._update_status("Next track.")
        else:
            self.current_track = 1
            self._update_status("Wrap to track 1.")
        self._start_playback_for_current()

    def _start_playback_for_current(self, *, start_ms: Optional[int] = None, with_am_overlay: bool = False) -> None:
        song = self._current_song()
        if song is None:
            return
        path = self._resolve_song_path(song)
        if path is None:
            self._log("Track file not found.")
            return
        self._start_playback(path, start_ms=start_ms, with_am_overlay=with_am_overlay)

    def _start_playback(self, path: str, *, start_ms: Optional[int] = None, with_am_overlay: bool = False) -> None:
        if not self.audio_ready:
            return
        try:
            import pygame
        except Exception:
            return
        self.target_volume = max(0.0, min(1.0, self.knob_slider.value() / 100.0))
        self._stop_playback()
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(0.0)
            if start_ms and start_ms > 0:
                pygame.mixer.music.play()
                try:
                    pygame.mixer.music.set_pos(start_ms / 1000.0)
                except Exception:
                    pass
            else:
                pygame.mixer.music.play()
        except Exception as exc:
            self._log(f"Playback error: {exc}")
            return
        # Only play AM radio overlay when tuning or first entering radio mode
        if with_am_overlay and self.am_sound is not None:
            self.am_channel = pygame.mixer.find_channel()
            if self.am_channel is not None:
                self.am_channel.set_volume(1.0)
                self.am_channel.play(self.am_sound)
                self._am_fade_steps = max(int(self.am_sound.get_length() * 10), 1)
                self._am_fade_step = 0
        self.is_playing = True
        self._fade_steps = max(int(FADE_IN_S * 10), 1)
        self._fade_step = 0
        if not self._fade_timer.isActive():
            self._fade_timer.start()
        if not self._playback_timer.isActive():
            self._playback_timer.start()

    def _tick_fade(self) -> None:
        if not self.audio_ready:
            self._fade_timer.stop()
            return
        try:
            import pygame
        except Exception:
            self._fade_timer.stop()
            return
        if self._fade_step < self._fade_steps:
            self._fade_step += 1
            volume = (self._fade_step / self._fade_steps) * self.target_volume
            if self.mode == "radio" and self.is_tuning:
                volume = min(0.2, volume)
            pygame.mixer.music.set_volume(volume)
        if self.am_channel is not None and self._am_fade_steps > 0:
            self._am_fade_step += 1
            remaining = max(self._am_fade_steps - self._am_fade_step, 0)
            volume = max(remaining / self._am_fade_steps, 0.0)
            self.am_channel.set_volume(volume)
            if remaining == 0:
                self.am_channel.stop()
        if self._fade_step >= self._fade_steps and (
            self.am_channel is None or self._am_fade_step >= self._am_fade_steps
        ):
            self._fade_timer.stop()

    def _current_playback_position(self) -> Optional[int]:
        if not self.audio_ready or not self.is_playing:
            return None
        try:
            import pygame
        except Exception:
            return None
        pos = pygame.mixer.music.get_pos()
        if pos < 0:
            return None
        return pos

    def _tune_radio(self, value: int) -> None:
        """Tune radio dial using RadioCore."""
        if not self.rail2_on:
            return
        
        # Prevent repeated calls with the same value (debounce)
        if hasattr(self, '_last_tune_value') and self._last_tune_value == value:
            return
        self._last_tune_value = value
        
        # Stop current playback when tuning starts
        self.hw_emulator.stop()
        self.is_playing = False
        
        # Check if station changed (before calling tune_radio)
        old_station_idx = getattr(self, '_last_tuned_station', None)
        
        # Enable playback delay so RadioCore's play_track calls are intercepted
        self.hw_emulator.set_delay_playback(True)
        
        # Use RadioCore's tune_radio (handles mode switch and station selection)
        # This will call play_track, but it will be delayed and stored in _pending_playback
        self.core.tune_radio(value)
        self._sync_from_core()
        
        # Check if station changed
        station_changed = (
            old_station_idx is None or 
            old_station_idx != self.core.radio_station_index
        )
        self._last_tuned_station = self.core.radio_station_index
        
        self.is_tuning = True
        self._tuning_timer.start(600)  # Reset timer - if knob stops, this fires
        self.mode_label.setText(f"Mode: {self.mode.title()}")
        
        # Play AM overlay first if station changed, then execute pending playback
        if station_changed:
            self._play_am_overlay_then_track()
        else:
            # Same station, just update position - play immediately (no AM overlay)
            self.hw_emulator.set_delay_playback(False)
            self.hw_emulator.execute_pending_playback()

    def _init_log_file(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        log_dir = project_root / "agent_workshop"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = log_dir / "test_mode.log"
            if not self.log_path.exists():
                self.log_path.write_text("", encoding="utf-8")
        except OSError:
            self.log_path = None

    def _init_radio_stations(self) -> None:
        """Initialize radio stations when entering radio mode.
        
        Station 0: Full Library
        Stations 1-N: Albums
        Stations N+1-M: Playlists
        
        Each station gets a random start offset.
        """
        self.radio_stations = []
        all_tracks = [dict(track) for track in self.db.list_songs()]
        
        # Station 0: Full Library
        lib_duration = sum((t.get("duration") or 0) * 1000 for t in all_tracks)
        self.radio_stations.append(RadioStation(
            name="Full Library",
            tracks=all_tracks,
            total_duration_ms=int(lib_duration) if lib_duration > 0 else 1,
            start_offset_ms=random.randint(0, max(int(lib_duration) - 1, 0)) if lib_duration > 0 else 0,
        ))
        
        # Albums as stations
        for album in self.albums:
            if album.album_id == 0 and album.name == "Library":
                continue  # Skip the fallback library album
            duration = sum((t.get("duration") or 0) * 1000 for t in album.tracks)
            self.radio_stations.append(RadioStation(
                name=album.name,
                tracks=album.tracks,
                total_duration_ms=int(duration) if duration > 0 else 1,
                start_offset_ms=random.randint(0, max(int(duration) - 1, 0)) if duration > 0 else 0,
            ))
        
        # Playlists as stations
        for playlist in self.playlists:
            if playlist.playlist_id == 0 and playlist.name == "Library":
                continue  # Skip the fallback library playlist
            duration = sum((t.get("duration") or 0) * 1000 for t in playlist.tracks)
            self.radio_stations.append(RadioStation(
                name=f"Playlist: {playlist.name}",
                tracks=playlist.tracks,
                total_duration_ms=int(duration) if duration > 0 else 1,
                start_offset_ms=random.randint(0, max(int(duration) - 1, 0)) if duration > 0 else 0,
            ))
        
        self.radio_mode_start_time = time.monotonic()
        self._log(f"Radio mode initialized with {len(self.radio_stations)} stations.")

    def _select_radio_station(self, dial_value: int) -> None:
        """Select a radio station based on dial position."""
        if not self.radio_stations:
            self._init_radio_stations()
        if not self.radio_stations:
            self._log("No radio stations available.")
            return
        
        # Map dial (0-100) to station index
        max_index = len(self.radio_stations) - 1
        station_index = int((dial_value / 100.0) * max_index)
        station_index = max(0, min(station_index, max_index))
        self.radio_station_index = station_index
        
        station = self.radio_stations[station_index]
        if not station.tracks:
            self._log(f"Station '{station.name}' has no tracks.")
            return
        
        # Calculate virtual position in the station
        elapsed_ms = int((time.monotonic() - (self.radio_mode_start_time or time.monotonic())) * 1000)
        virtual_position_ms = (station.start_offset_ms + elapsed_ms) % station.total_duration_ms
        
        # Find which track and position within that track
        track, track_offset_ms = self._find_track_at_position(station.tracks, virtual_position_ms)
        if track is None:
            track = station.tracks[0]
            track_offset_ms = 0
        
        self.current_track = station.tracks.index(track) + 1 if track in station.tracks else 1
        self._log(f"Radio tuned to '{station.name}' - Track {self.current_track} at {track_offset_ms // 1000}s")
        # Play AM overlay when tuning to a station
        self._start_playback_for_song(track, offset_ms=track_offset_ms, with_am_overlay=True)


    def _lock_radio_station(self) -> None:
        """Called when knob stops moving - stop AM overlay and play track immediately."""
        if self.mode != "radio":
            return
        self.is_tuning = False
        
        # Stop AM overlay immediately
        self._stop_am_overlay()
        
        # Disable playback delay and execute pending playback immediately
        self.hw_emulator.set_delay_playback(False)
        self.hw_emulator.execute_pending_playback()
        
        self._apply_radio_distortion(tuning=False)
        self._update_status("Locked radio station.")
    
    def _stop_am_overlay(self) -> None:
        """Stop AM overlay sound."""
        try:
            import pygame
            if self.am_channel:
                self.am_channel.stop()
                self.am_channel = None
            # Also stop VLC AM overlay if using it
            if hasattr(self.hw_emulator, '_vlc_am_player') and self.hw_emulator._vlc_am_player:
                self.hw_emulator._vlc_am_player.stop()
        except Exception:
            pass
    
    def _play_am_overlay_then_track(self) -> None:
        """Play AM overlay first, then start track playback when it finishes."""
        if not self.audio_ready:
            # No audio, execute pending playback immediately
            self.hw_emulator.set_delay_playback(False)
            self.hw_emulator.execute_pending_playback()
            return
        
        try:
            import pygame
            if self.am_sound is None:
                # No AM sound available, play track immediately
                self.hw_emulator.set_delay_playback(False)
                self.hw_emulator.execute_pending_playback()
                return
            
            # Stop any existing AM overlay
            self._stop_am_overlay()
            
            # Play AM overlay
            self.am_channel = pygame.mixer.find_channel()
            if self.am_channel:
                self.am_channel.set_volume(1.0)
                self.am_channel.play(self.am_sound)
                self._log("AM overlay playing")
                
                # Calculate AM sound duration and schedule track playback
                am_duration_ms = int(self.am_sound.get_length() * 1000)
                
                # Start track playback after AM overlay finishes
                # Only if still tuning (otherwise _lock_radio_station will handle it)
                QtCore.QTimer.singleShot(am_duration_ms, self._start_track_after_am)
        except Exception as e:
            self._log(f"AM overlay error: {e}")
            # Fallback: play track immediately if AM overlay fails
            self.hw_emulator.set_delay_playback(False)
            self.hw_emulator.execute_pending_playback()
    
    def _start_track_after_am(self) -> None:
        """Start track playback after AM overlay finishes."""
        # Execute pending playback (works for radio tuning, mode switching, and power on)
        self.hw_emulator.set_delay_playback(False)
        self.hw_emulator.execute_pending_playback()

    def _apply_radio_distortion(self, *, tuning: bool) -> None:
        """Apply radio distortion effect (lower volume when tuning)."""
        if not self.audio_ready:
            return
        try:
            import pygame
        except Exception:
            return
        base_volume = self.knob_slider.value() / 100.0
        if tuning:
            # Lower music volume when tuning (AM overlay is playing)
            pygame.mixer.music.set_volume(min(0.2, base_volume))
        else:
            # Normal volume when locked
            pygame.mixer.music.set_volume(base_volume)

    def _find_track_at_position(self, tracks: List[Dict], position_ms: int) -> tuple:
        """Find which track contains the given position and the offset within it."""
        cumulative_ms = 0
        for track in tracks:
            duration_ms = int((track.get("duration") or 0) * 1000)
            if duration_ms <= 0:
                duration_ms = 180000  # Default 3 minutes if unknown
            if cumulative_ms + duration_ms > position_ms:
                return track, position_ms - cumulative_ms
            cumulative_ms += duration_ms
        # Position exceeds total - wrap to first track
        return tracks[0] if tracks else None, 0
    
    def _start_playback_for_song(self, song: Dict, *, offset_ms: Optional[int] = None, with_am_overlay: bool = False) -> None:
        path = self._resolve_song_path(song)
        if path is None:
            self._log("Track file not found.")
            return
        self._start_playback(path, start_ms=offset_ms, with_am_overlay=with_am_overlay)

    def _current_track_count(self) -> int:
        if self.mode == "radio":
            if self.radio_stations and self.radio_station_index < len(self.radio_stations):
                return max(len(self.radio_stations[self.radio_station_index].tracks), 1)
            return 1
        if self.mode == "shuffle":
            return max(len(self.shuffle_tracks), 1)
        if self.mode == "playlist":
            return max(len(self.current_playlist().tracks), 1)
        return self._track_count(self.current_album())

    def _source_name(self) -> str:
        # Use RadioCore's status for accurate source name (especially for shuffle mode)
        status = self.core.get_status()
        return status.get('source', 'Unknown')

    def _switch_mode(self, mode: str) -> None:
        """Switch mode using RadioCore."""
        # Enable playback delay so we can sequence AM overlay before track
        self.hw_emulator.set_delay_playback(True)
        
        # Play AM overlay first
        self.hw_emulator.play_am_overlay()
        
        # Special handling for shuffle button
        if mode == "shuffle":
            if self.mode == "shuffle":
                # Already in shuffle - reshuffle the current source
                if self.core._shuffle_source_type:
                    # Reshuffle current album/playlist
                    self.core._init_current_shuffle()
                else:
                    # Reshuffle library
                    self.core._init_library_shuffle()
            elif self.mode in ("album", "playlist"):
                # Shuffle the current album/playlist
                self.core._init_current_shuffle()
            else:
                # Other mode - switch to library shuffle
                self.core.switch_mode(mode)
        else:
            self.core.switch_mode(mode)
        
        self._sync_from_core()
        self.mode_label.setText(f"Mode: {self.mode.title()}")
        
        # Schedule track playback after AM overlay finishes
        if self.am_sound:
            am_duration_ms = int(self.am_sound.get_length() * 1000)
            QtCore.QTimer.singleShot(am_duration_ms, self._start_track_after_am)
        else:
            # No AM sound, play immediately
            self._start_track_after_am()
        
        self._update_status("Mode switched.")

    def on_button_pressed(self, source: str = "?") -> None:
        """Handle button press - delegates to RadioCore."""
        if not self.rail2_on:
            return
        
        # Delegate to RadioCore (same logic as firmware)
        self.core.on_button_press()
        
        # Track locally for GUI feedback
        self._press_timer.start()
        self._log(f"[{source}] Button PRESSED, tap_count={self.core.tap_count}")

    def on_button_released(self, source: str = "?") -> None:
        """Handle button release - delegates to RadioCore."""
        if not self.rail2_on:
            return
        
        elapsed = self._press_timer.elapsed() if self._press_timer.isValid() else 0
        self._log(f"[{source}] Button RELEASED, elapsed={elapsed}ms")
        
        # Delegate to RadioCore (same logic as firmware)
        self.core.on_button_release()
        
        # Sync state from core and update display
        self._sync_from_core()
        self._update_status("Button action processed.")

