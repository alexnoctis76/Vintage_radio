"""
Vintage Radio Core Logic Module

This module contains the shared state machine logic used by both:
- The MicroPython firmware (main.py) running on the device
- The PyQt GUI emulator (gui/test_mode.py) for emulation

Hardware operations are abstracted via callbacks, so the same logic
runs identically on real hardware and in emulation.

Compatible with both MicroPython and CPython.
"""

# Try MicroPython time, fall back to CPython
try:
    from time import ticks_ms, ticks_diff, sleep_ms as _sleep_ms
except ImportError:
    import time as _time
    def ticks_ms():
        return int(_time.monotonic() * 1000)
    def ticks_diff(a, b):
        return a - b
    def _sleep_ms(ms):
        _time.sleep(ms / 1000.0)

# Try MicroPython random
try:
    from urandom import randint
except ImportError:
    from random import randint

# ===========================
#      CONSTANTS
# ===========================

FADE_IN_S = 2.4
DF_BOOT_MS = 2000
LONG_PRESS_MS = 500   # Hold >= 500ms = long press
TAP_WINDOW_MS = 350   # ms after last release to resolve taps (single-tap next/prev feels snappier; double-tap still detectable)
BUSY_CONFIRM_MS = 2200
POST_CMD_GUARD_MS = 120
# After 0x3D, poll this long for BUSY idle (HIGH) or query_status stopped (0) before
# advancing.  Startup noise often sends 0x3D while the module is still playing; waiting
# for hardware to agree avoids skipping ahead without discarding real ends (0x3D usually
# arrives slightly before BUSY rises).
DF_UART_STOP_CONFIRM_MS = 320
MAX_ALBUM_NUM = 99


def dfplayer_confirms_playback_stopped(hw, timeout_ms=None):
    """True if DFPlayer looks idle: BUSY HIGH and/or query_status == 0.

    Drains UART while polling so late 0x40/0x3D bytes do not confuse the next command.
    If neither BUSY nor query_status exists, returns True (nothing to verify).
    """
    if timeout_ms is None:
        timeout_ms = DF_UART_STOP_CONFIRM_MS
    poll = getattr(hw, "_df_read_pending", None)
    pin_busy = getattr(hw, "pin_busy", None)
    qstatus = getattr(hw, "query_status", None)
    if pin_busy is None and qstatus is None:
        return True
    t0 = ticks_ms()
    while ticks_diff(ticks_ms(), t0) <= timeout_ms:
        if poll:
            poll()
        if pin_busy is not None and pin_busy.value() == 1:
            return True
        if qstatus is not None:
            st = qstatus()
            if st == 0:
                return True
        _sleep_ms(12)
    return False

# ===========================
#      MODE ENUM
# ===========================

MODE_ALBUM = "album"
MODE_PLAYLIST = "playlist"
MODE_SHUFFLE = "shuffle"
MODE_RADIO = "radio"

ALL_MODES = [MODE_ALBUM, MODE_PLAYLIST, MODE_SHUFFLE, MODE_RADIO]

# ===========================
#      RADIO STATION
# ===========================

class RadioStation:
    """A radio station representing a collection of tracks."""
    def __init__(self, name, tracks, total_duration_ms=0, start_offset_ms=0):
        self.name = name
        self.tracks = tracks  # List of track dicts with at least 'duration' key
        self.total_duration_ms = total_duration_ms
        self.start_offset_ms = start_offset_ms


# ===========================
#      HARDWARE INTERFACE
# ===========================

class HardwareInterface:
    """
    Abstract interface for hardware operations.

    Implement this for real hardware (DFPlayer, I2S, etc.) or
    emulation (pygame).  The firmware entry point (main.py) and
    RadioCore both call these methods.

    See docs/CUSTOM_DRIVER.md for a full guide on building a
    custom driver and firmware/custom_driver_template.py for a
    ready-to-fill-in starting point.
    """

    # ---- Playback ----

    def play_track(self, folder, track, start_ms=0, folder_wrap=False):
        """Play a track.

        Args:
            folder: DFPlayer folder number (1-99).
            track:  Track number within that folder (1-999).
            start_ms: Seek to this position after starting (0 = beginning).
            folder_wrap: True when advancing from the last track of this folder
                back to track 1 (loop). DFPlayer drivers may use extra settle
                or a bridge selection so 0x0F is not ignored.

        Returns:
            True if playback started, False on failure.
        """
        raise NotImplementedError

    def stop(self):
        """Stop playback immediately."""
        raise NotImplementedError

    def set_volume(self, level):
        """Set volume.

        Args:
            level: 0-100 (the driver maps this to its hardware range).
        """
        raise NotImplementedError

    def is_playing(self):
        """Return True if audio is currently playing."""
        raise NotImplementedError

    def get_playback_position_ms(self):
        """Return current playback position in milliseconds.

        Return 0 if the hardware cannot report position.
        """
        raise NotImplementedError

    def check_track_finished_uart(self):
        """Return True if a track-finished event was received.

        For DFPlayer this is the 0x3D UART message.  If your hardware
        does not send such events, leave the default (returns False)
        and RadioCore will fall back to polling is_playing().
        """
        return False

    def play_am_overlay(self):
        """Play the AM radio 'tuning' static effect.

        Can be a no-op if the hardware does not support an AM overlay.
        """
        raise NotImplementedError

    # ---- State persistence ----

    def save_state(self, state_dict):
        """Persist state to non-volatile storage.

        state_dict contains at least:
            mode (str), album_index (int), track (int), known_tracks (dict).
        """
        raise NotImplementedError

    def load_state(self):
        """Load previously saved state.

        Returns:
            A dict with the same keys as save_state(), or None if
            no state was saved.
        """
        raise NotImplementedError

    # ---- Logging ----

    def log(self, message):
        """Output a log/debug message (e.g. print to serial)."""
        raise NotImplementedError

    # ---- Metadata ----

    def get_albums(self):
        """Return albums from radio_metadata.json.

        Each album is a dict:
            {'id': int, 'name': str, 'tracks': [<track_dict>, ...]}

        Each track_dict contains at least:
            id, title, artist, duration (seconds), folder, track_number.
        """
        raise NotImplementedError

    def get_playlists(self):
        """Return playlists from radio_metadata.json.

        Same format as get_albums().
        """
        raise NotImplementedError

    def get_all_tracks(self):
        """Return a flat list of every unique track dict."""
        raise NotImplementedError

    # ---- Hardware / GPIO ----

    def is_power_on(self):
        """Return True when the power-sense input is active.

        The firmware main loop polls this to detect power on/off.
        If your hardware has no power sense, return True.
        """
        raise NotImplementedError

    def is_button_pressed(self):
        """Return True when the user button is currently held down.

        Active-low buttons should invert the pin value here.
        """
        raise NotImplementedError

    # ---- Optional (override if needed) ----

    def set_delay_playback(self, delay):
        """When True, play_track() should no-op.

        The firmware sets this before running the AM overlay
        sequence so the core's auto-play doesn't race with it.
        Override if your driver needs to honour this flag.
        """
        pass

    def set_current_track_hint(self, track):
        """Hint for emulators / GUIs -- the track dict about to play.

        Firmware drivers can ignore this.
        """
        pass

    def discover_stations(self):
        """Discover stations from hardware (e.g. DFPlayer folder queries).

        Used by basic_mode to build station/playlist data directly from
        the SD card folder structure without metadata files.

        Returns:
            List of station dicts (same format as get_albums/get_playlists),
            or empty list if not supported.
        """
        return []

# ===========================
#      CORE STATE MACHINE
# ===========================

class RadioCore:
    """
    Core state machine for the vintage radio.
    
    This class contains all the logic for:
    - Mode switching (album, playlist, shuffle, radio)
    - Button handling (tap, double-tap, triple-tap, long press)
    - Track navigation
    - Auto-advance on track end
    - Power on/off handling
    - Radio mode with virtual station timing
    """
    
    def __init__(self, hardware, basic_mode=False):
        """
        Initialize the radio core.
        
        Args:
            hardware: An object implementing HardwareInterface
            basic_mode: When True, stations are discovered from DFPlayer
                        folder structure (no metadata). No album mode --
                        only station (playlist), shuffle, and radio.
        """
        self.hw = hardware
        self.basic_mode = basic_mode
        
        # Current state
        self.mode = MODE_PLAYLIST if basic_mode else MODE_ALBUM
        self.power_on = True
        self.is_playing = False
        
        # Album/Playlist mode state
        self.current_album_index = 0
        self.current_track = 1
        self.albums = []
        self.playlists = []
        
        # Shuffle mode state
        self.shuffle_tracks = []
        self.shuffle_index = 0
        
        # Radio mode state
        self.radio_stations = []
        self.radio_station_index = 0
        self.radio_mode_start_ms = None
        # Cooldown so tick does not override a recent tune or force-advance (avoids ping-pong/wrong start)
        self._radio_advance_cooldown_until_ms = 0
        
        # Track the source type when entering shuffle mode (for "shuffle current" functionality)
        self._shuffle_source_type = None  # 'album' or 'playlist'
        
        # Button handling state
        self.tap_count = 0
        self.press_start_ms = 0
        self.last_release_ms = 0
        self.button_down = False
        self._pending_long_press = False
        
        # Resume state (for power off/on)
        self.resume_state = None
        
        # Volume
        self.volume = 100
        
        # Known tracks per album (for firmware compatibility)
        self.known_tracks = {}
        # Set by _next_track when looping same station: last track -> track 1 (DFPlayer quirk)
        self._folder_wrap_play = False
        
        # Basic mode feature flags (read from DFPlayer folder 99 file count via 0x4E; see _check_feature_flags)
        # Defaults match desktop app until _check_feature_flags() runs (default: advance).
        self.loop_stations = False
        # When True, after the last track of a station (or one full station shuffle pass),
        # advance to the next station instead of stopping or looping in place.
        self.advance_next_station = True
    
    def init(self, skip_initial_playback=False):
        """Initialize the radio - load state and optionally start playback.
        skip_initial_playback: If True, do not start playback (caller will e.g. start_with_am).
        Used by firmware to match baseline: one start inside AM overlay, no double-start.
        """
        self._load_data()
        if self.basic_mode:
            self._check_feature_flags()
        self._load_state()
        if self.power_on and not skip_initial_playback:
            self._start_playback_for_current()
    
    def _load_data(self):
        """Load albums, playlists, and tracks from hardware."""
        if self.basic_mode:
            self._load_data_basic()
            return
        self.albums = self.hw.get_albums() or []
        self.playlists = self.hw.get_playlists() or []
        
        # Ensure we have at least one album (full library)
        if not self.albums:
            all_tracks = self.hw.get_all_tracks() or []
            self.albums = [{'id': 0, 'name': 'Library', 'tracks': all_tracks}]

    def _load_data_basic(self):
        """Load station data by querying DFPlayer folder structure.
        
        In basic mode, stations are discovered via UART queries (0x4F, 0x4E)
        and mapped to playlists. Albums stay empty (no album mode).
        Per-folder sizes come from the DFPlayer Mini 0x4E command (consensus read).
        macOS ``._*`` files inflate 0x4E; the desktop app's Sync to SD removes them
        after each sync. Runtime 0x06 handling can still correct bad counts.
        The hardware's internal _playlists/_albums are also set so that
        _load_metadata() (called from load_state) won't overwrite them
        with advanced-mode radio_metadata.json.
        """
        self.albums = []
        stations = self.hw.discover_stations()
        if stations:
            self.playlists = stations
        else:
            self.playlists = [{"id": 0, "name": "Empty", "tracks": []}]
        self.hw.log(f"BASIC: Loaded {len(self.playlists)} stations")
        
        if not self.playlists:
            all_tracks = self.hw.get_all_tracks() or []
            self.playlists = [{'id': 0, 'name': 'Library', 'tracks': all_tracks}]
        
        # Populate hw-level caches so _load_metadata() sees them and skips
        # the radio_metadata.json load (which would overwrite station data).
        if hasattr(self.hw, '_playlists'):
            self.hw._playlists = list(self.playlists)
        if hasattr(self.hw, '_albums'):
            self.hw._albums = list(self.albums)
        
        self.hw.log(f"Loaded {len(self.albums)} albums, {len(self.playlists)} playlists")
        for i, playlist in enumerate(self.playlists):
            self.hw.log(f"[PLAYLIST DEBUG] Playlist {i}: name='{playlist.get('name', 'Unknown')}', tracks={len(playlist.get('tracks', []))}")

    def _check_feature_flags(self):
        """Read feature flags from DFPlayer folder 99 only (0x4E file count).

        Folder 99 holds ``001.wav`` (AM). Extra tiny MP3 stubs encode end behavior.
        Many DFPlayer modules **do not count WAV** in 0x4E, so ``002+003`` alone can
        read as **count==2** (loop) even when the desktop meant **advance**. The SD
        sync therefore writes **three** stubs (002--004) for advance so count is >=3
        even when 001.wav is ignored.

          <=1 file  -> stop at end of station / one shuffle pass
          2 files   -> loop (repeat station or shuffle order)
          3+ files  -> advance to next station when a station ends

        No separate MCU flash or sidecar text file — the module reports counts over UART.
        """
        if not hasattr(self.hw, "query_files_in_folder"):
            return
        if hasattr(self.hw, "query_files_in_folder_consensus"):
            count = self.hw.query_files_in_folder_consensus(
                99, suppress_errors=True
            )
        else:
            count = self.hw.query_files_in_folder(99, suppress_errors=True)
        if count is None:
            self.hw.log("BASIC: Could not query folder 99 for feature flags, using defaults")
            return
        if count <= 1:
            self.loop_stations = False
            self.advance_next_station = False
        elif count == 2:
            self.loop_stations = True
            self.advance_next_station = False
        else:
            self.loop_stations = False
            self.advance_next_station = True
        self.hw.log(
            "BASIC: Feature flags folder 99: count=%s loop_stations=%s advance_next_station=%s"
            % (count, self.loop_stations, self.advance_next_station)
        )

    def _load_state(self):
        """Load persisted state."""
        state = self.hw.load_state()
        if state:
            loaded_mode = state.get('mode', MODE_PLAYLIST if self.basic_mode else MODE_ALBUM)
            if self.basic_mode and loaded_mode == MODE_ALBUM:
                loaded_mode = MODE_PLAYLIST
            self.mode = loaded_mode
            self.current_album_index = state.get('album_index', 0)
            self.current_track = state.get('track', 1)
            if self.basic_mode:
                # In basic mode, use hardware's _known_tracks (set by discover_stations)
                # rather than potentially stale values from persisted state.
                self.known_tracks = dict(getattr(self.hw, '_known_tracks', {}))
            else:
                self.known_tracks = state.get('known_tracks', {})
            # Clamp album/playlist index to valid range (metadata may have changed since state was saved)
            if self.mode == MODE_PLAYLIST and self.playlists:
                if self.current_album_index >= len(self.playlists):
                    self.hw.log(f"Clamping playlist index {self.current_album_index} to {len(self.playlists) - 1}")
                    self.current_album_index = max(0, len(self.playlists) - 1)
            elif self.mode == MODE_ALBUM and self.albums:
                if self.current_album_index >= len(self.albums):
                    self.hw.log(f"Clamping album index {self.current_album_index} to {len(self.albums) - 1}")
                    self.current_album_index = max(0, len(self.albums) - 1)
            self.current_album_index = max(0, self.current_album_index)
            # Clamp track to valid range for current album/playlist
            tracks = self._get_current_tracks()
            if tracks and self.current_track > len(tracks):
                self.hw.log(f"Clamping track {self.current_track} to {len(tracks)}")
                self.current_track = len(tracks)
            self.current_track = max(1, self.current_track)
            self.hw.log(f"Loaded state: mode={self.mode}, album={self.current_album_index}, track={self.current_track}")
            
            # Initialize mode-specific state based on loaded mode
            if self.mode == MODE_RADIO and not self.radio_stations:
                self._init_radio()
            elif self.mode == MODE_SHUFFLE and not self.shuffle_tracks:
                self._init_shuffle()
    
    def _save_state(self, reason=""):
        """Persist current state."""
        state = {
            'mode': self.mode,
            'album_index': self.current_album_index,
            'track': self.current_track,
            'known_tracks': self.known_tracks,
        }
        self.hw.save_state(state)
        self.hw.log(f"Saved state [{reason}]: {state}")
    
    # ===========================
    #   BUTTON HANDLING
    # ===========================
    
    def on_button_press(self):
        """Called when button is pressed down."""
        if not self.power_on:
            return
        # New press always resets the idle timer - we're receiving input
        self.button_down = True
        self.press_start_ms = ticks_ms()
        self.hw.log(f"on_button_press: down (existing tap_count={self.tap_count})")
    
    def on_button_release(self):
        """Called when button is released."""
        if not self.power_on or not self.button_down:
            return
        self.button_down = False
        
        now = ticks_ms()
        press_duration = ticks_diff(now, self.press_start_ms)
        
        if press_duration >= LONG_PRESS_MS:
            # This was a hold (long press). Record it and start the 500ms idle timer.
            self.hw.log(f"on_button_release: HOLD detected ({press_duration}ms), tap_count={self.tap_count}")
            self._pending_long_press = True
            self.last_release_ms = now
        else:
            # This was a tap. Increment count and start/restart the 500ms idle timer.
            self.tap_count += 1
            self.last_release_ms = now
            self.hw.log(f"on_button_release: TAP #{self.tap_count} ({press_duration}ms)")
    
    def tick(self):
        """
        Called regularly (e.g., every 10-50ms) to process timing-based events.
        Returns True if something happened.
        """
        if not self.power_on:
            return False
        
        now = ticks_ms()
        
        # Wait for 500ms of no input (idle timeout) after the last release
        # Only resolve if button is NOT currently held down
        if self.last_release_ms > 0 and not self.button_down and \
           ticks_diff(now, self.last_release_ms) >= TAP_WINDOW_MS:
            self._resolve_input()
            return True
        
        # Radio mode: check if track should advance based on virtual time
        # Only check every ~1 second to avoid excessive checking
        if self.mode == MODE_RADIO and self.is_playing:
            # Use a simple time-based throttle (check every ~1 second)
            now = ticks_ms()
            if not hasattr(self, '_last_radio_check_ms'):
                self._last_radio_check_ms = now
            if ticks_diff(now, self._last_radio_check_ms) >= 1000:  # Check every 1 second
                self._last_radio_check_ms = now
                if self._check_radio_advance():
                    return True
        
        return False
    
    def _check_radio_advance(self):
        """Check if radio mode should advance to next track based on virtual time.
        Returns True if track was advanced.
        """
        if not self.radio_stations or self.radio_station_index >= len(self.radio_stations):
            return False
        
        # Do not override a recent tune or force-advance (avoids ping-pong and wrong start position)
        if ticks_ms() < self._radio_advance_cooldown_until_ms:
            return False
        
        station = self.radio_stations[self.radio_station_index]
        if not station.tracks:
            return False
        
        # Calculate current virtual position
        if self.radio_mode_start_ms is None:
            self.radio_mode_start_ms = ticks_ms()
            return False
        
        elapsed_ms = ticks_diff(ticks_ms(), self.radio_mode_start_ms)
        virtual_pos_ms = (station.start_offset_ms + elapsed_ms) % station.total_duration_ms
        
        # Find which track should be playing at this virtual time
        current_track, current_offset = self._find_track_at_position(station.tracks, virtual_pos_ms)
        if not current_track:
            return False
        
        # Check if we're playing the correct track
        current_track_idx = station.tracks.index(current_track) + 1 if current_track in station.tracks else 1
        
        # Only advance if we've moved to a completely different track
        # Don't restart if we're on the same track (even if offset changed slightly)
        if current_track_idx != self.current_track:
            n = len(station.tracks)
            next_after_virtual = (current_track_idx % n) + 1
            # Do not override when we're one track *ahead* of virtual time: that happens
            # when the previous track finished and we force-advanced to the next track.
            # Overriding would ping-pong us back to the previous track (handles wrap: e.g. virtual=20, we're on 1).
            if self.current_track == next_after_virtual:
                return False
            # Virtual time says we should be on a different track and we're behind - advance
            self.current_track = current_track_idx
            self._start_playback_for_track(current_track, start_ms=current_offset)
            self.hw.log(f"Radio advanced to track {current_track_idx} at {current_offset // 1000}s (virtual time)")
            return True
        
        return False
    
    def _resolve_input(self):
        """
        Called after 500ms of idle (no button activity).
        Resolves ALL accumulated input: taps and/or a hold.
        
        Gestures:
          Taps only:  1=next, 2=prev, 3+=restart
          Hold only:  next album/playlist/station (in station-shuffle: next station + new shuffle)
          N taps + hold: 1+hold=toggle mode, 2+hold=shuffle current, 3+hold=shuffle library
        """
        had_hold = getattr(self, '_pending_long_press', False)
        tap_count = self.tap_count
        
        self.hw.log(f"_resolve_input: taps={tap_count}, hold={had_hold}")
        
        # Reset state
        self.tap_count = 0
        self.last_release_ms = 0
        self._pending_long_press = False
        
        if had_hold:
            # Had a hold - use _handle_long_press with accumulated tap count
            self._handle_long_press_with_taps(tap_count)
        elif tap_count >= 3:
            self._triple_tap()
        elif tap_count == 2:
            self._double_tap()
        elif tap_count == 1:
            self._single_tap()
        else:
            self.hw.log(f"_resolve_input: no actionable input")
    
    def _single_tap(self):
        """Single tap - next track (next in shuffle order when in shuffle mode)."""
        self.hw.log("Single tap: next track")
        self._next_track()
    
    def _double_tap(self):
        """Double tap - previous track (previous in shuffle order when in shuffle mode)."""
        self.hw.log("Double tap: previous track")
        self._prev_track()
    
    def _triple_tap(self):
        """Triple tap - restart from the beginning of the current source.

        In ordered station/playlist/album mode: track 1 of that list.
        In shuffle (station, album, playlist, or library): first entry in the
        current ``shuffle_tracks`` order (same random order as when shuffle
        started; does not re-shuffle). Single/double tap already move within
        that list via ``shuffle_index``.
        """
        self.hw.log("Triple tap: restart")
        if self.mode == MODE_SHUFFLE:
            if not self.shuffle_tracks:
                self.hw.log("Triple tap: no shuffle tracks to restart")
                return
            self.shuffle_index = 0
            self.current_track = 1
            st = self._shuffle_source_type
            if st in ("album", "playlist", "station"):
                self.hw.log(
                    "Triple tap: restart at first track in current source shuffle order"
                )
            else:
                self.hw.log(
                    "Triple tap: restart at first track in library shuffle order"
                )
        else:
            # Ordered playlist/station/album, or radio: first track index
            self.current_track = 1
        self._save_state("triple tap restart")
        self._start_playback_for_current()
    
    def _handle_long_press_with_taps(self, tap_count):
        """
        Hold gesture resolved after 500ms idle.
        
        Behaviour depends on how many taps preceded the hold:
          0 taps + hold = Next album/playlist/station (in station-shuffle: next station, reshuffled)
          1 tap  + hold = Toggle Album/Playlist mode (basic: exit shuffle to station order)
          2 taps + hold = Shuffle current album/playlist/station (again = new random order)
          3+ taps + hold = Shuffle entire library
        """
        self.hw.log(f"_handle_long_press_with_taps: tap_count={tap_count}")
        
        if tap_count >= 3:
            self._init_library_shuffle()
            self.hw.log("Mode: Shuffle (Library)")
        elif tap_count == 2:
            self._init_current_shuffle()
        elif tap_count == 1:
            if not self.basic_mode:
                self._cycle_mode_basic()
            elif self.mode == MODE_SHUFFLE:
                # Exit shuffle and return to normal station mode
                self.switch_mode(MODE_PLAYLIST)
            # else: already in station mode, 1-tap + hold does nothing
            # (0-tap + hold already advances the station)
        else:
            self._next_album()
    
    def _cycle_mode_basic(self):
        """Cycle between modes. In basic_mode, album mode is not available --
        cycle between station (playlist) and shuffle only.
        """
        if self.basic_mode:
            if self.mode == MODE_PLAYLIST:
                self.switch_mode(MODE_SHUFFLE)
            else:
                self.switch_mode(MODE_PLAYLIST)
        else:
            if self.mode == MODE_ALBUM:
                self.switch_mode(MODE_PLAYLIST)
            elif self.mode == MODE_PLAYLIST:
                self.switch_mode(MODE_ALBUM)
            else:
                self.switch_mode(MODE_ALBUM)
    
    def _init_current_shuffle(self):
        """Initialize shuffle mode for current album/playlist/station."""
        tracks = []
        source_name = 'Unknown'
        
        if self.basic_mode:
            # In basic mode, always shuffle the current station (playlist) regardless of
            # the current mode.  This prevents the fallback-to-library behaviour when
            # calling shuffle-station from inside library-shuffle mode (where
            # self.mode == MODE_SHUFFLE and _shuffle_source_type is None).
            if self.playlists and self.current_album_index < len(self.playlists):
                tracks = self.playlists[self.current_album_index].get('tracks', [])
                source_name = self.playlists[self.current_album_index].get('name', 'Station')
                self._shuffle_source_type = 'station'
        elif self.mode == MODE_SHUFFLE and self._shuffle_source_type:
            if self._shuffle_source_type in ('playlist', 'station'):
                if self.playlists and self.current_album_index < len(self.playlists):
                    tracks = self.playlists[self.current_album_index].get('tracks', [])
                    source_name = self.playlists[self.current_album_index].get('name', 'Station' if self.basic_mode else 'Playlist')
            else:  # 'album'
                if self.albums and self.current_album_index < len(self.albums):
                    tracks = self.albums[self.current_album_index].get('tracks', [])
                    source_name = self.albums[self.current_album_index].get('name', 'Album')
        elif self.mode == MODE_PLAYLIST:
            if self.playlists and self.current_album_index < len(self.playlists):
                tracks = self.playlists[self.current_album_index].get('tracks', [])
                source_name = self.playlists[self.current_album_index].get('name', 'Station' if self.basic_mode else 'Playlist')
                self._shuffle_source_type = 'station' if self.basic_mode else 'playlist'
        else:
            if self.albums and self.current_album_index < len(self.albums):
                tracks = self.albums[self.current_album_index].get('tracks', [])
                source_name = self.albums[self.current_album_index].get('name', 'Album')
                self._shuffle_source_type = 'album'
        
        if not tracks:
            if self.basic_mode:
                for pl in self.playlists:
                    tracks.extend(pl.get('tracks', []))
            else:
                tracks = list(self.hw.get_all_tracks() or [])
            source_name = 'Library'
            self._shuffle_source_type = None
            self.hw.log("Warning: No current source found, shuffling library instead")
        
        if not tracks:
            self.hw.log("Error: No tracks available to shuffle")
            return
        
        # Create a fresh copy of tracks and shuffle them
        self.shuffle_tracks = list(tracks)
        
        # Fisher-Yates shuffle - always create a new random order
        # Shuffle from the end to the beginning
        for i in range(len(self.shuffle_tracks) - 1, 0, -1):
            j = randint(0, i)
            self.shuffle_tracks[i], self.shuffle_tracks[j] = self.shuffle_tracks[j], self.shuffle_tracks[i]
        
        # Log the first few tracks to verify shuffle is working
        if len(self.shuffle_tracks) > 0:
            first_track = self.shuffle_tracks[0].get('title', 'Unknown') if self.shuffle_tracks[0] else 'Unknown'
            self.hw.log(f"Shuffled order starts with: {first_track}")
        
        self.shuffle_index = 0
        self.current_track = 1
        
        # Save shuffle configuration before calling switch_mode (which will overwrite it)
        saved_shuffle_tracks = list(self.shuffle_tracks) if self.shuffle_tracks else list(tracks)
        if self._shuffle_source_type:
            saved_shuffle_source = self._shuffle_source_type
        elif self.basic_mode:
            saved_shuffle_source = 'station'
        elif self.mode == MODE_PLAYLIST:
            saved_shuffle_source = 'playlist'
        else:
            saved_shuffle_source = 'album'
        
        # Use switch_mode to properly initialize shuffle mode
        self.switch_mode(MODE_SHUFFLE)
        
        # Restore our specific shuffle configuration (switch_mode calls _init_shuffle which overwrites)
        self.shuffle_tracks = saved_shuffle_tracks
        self._shuffle_source_type = saved_shuffle_source
        
        self.hw.log(f"Mode: Shuffle ({source_name}, {len(self.shuffle_tracks)} tracks)")
        self._save_state("shuffle current")
        
        # Start playback (will be delayed if delay_playback is True)
        self._start_playback_for_current()
    
    def _init_library_shuffle(self):
        """Initialize shuffle mode for entire library.
        In basic mode, gathers all tracks from discovered stations (playlists)
        rather than calling hw.get_all_tracks() which may hit metadata.
        """
        if self.basic_mode:
            all_tracks = []
            for pl in self.playlists:
                all_tracks.extend(pl.get('tracks', []))
        else:
            all_tracks = self.hw.get_all_tracks() or []
        self.shuffle_tracks = list(all_tracks)
        
        # Fisher-Yates shuffle - always create a new random order
        for i in range(len(self.shuffle_tracks) - 1, 0, -1):
            j = randint(0, i)
            self.shuffle_tracks[i], self.shuffle_tracks[j] = self.shuffle_tracks[j], self.shuffle_tracks[i]
        
        # Log the first few tracks to verify shuffle is working
        if len(self.shuffle_tracks) > 0:
            first_track = self.shuffle_tracks[0].get('title', 'Unknown') if self.shuffle_tracks[0] else 'Unknown'
            self.hw.log(f"Shuffled library order starts with: {first_track}")
        
        self.shuffle_index = 0
        self.current_track = 1
        
        # Save shuffle configuration before calling switch_mode (which will overwrite it)
        saved_shuffle_tracks = list(self.shuffle_tracks)
        
        if self.mode == MODE_SHUFFLE:
            self._arm_am_overlay_before_next_play("library shuffle (from station/album shuffle)")
        else:
            self.switch_mode(MODE_SHUFFLE)
        
        # Restore our library shuffle configuration (switch_mode calls _init_shuffle which overwrites)
        self.shuffle_tracks = saved_shuffle_tracks
        self._shuffle_source_type = None  # Library shuffle has no specific source
        
        self.hw.log(f"Mode: Shuffle (Library, {len(self.shuffle_tracks)} tracks)")
        self._save_state("shuffle library")
        
        # Start playback (switch_mode already stopped playback and set delay_playback)
        self._start_playback_for_current()
    
    # ===========================
    #   TRACK NAVIGATION
    # ===========================
    
    def _next_track(self):
        """Move to next track."""
        old_track = self.current_track
        old_album = self.current_album_index
        folder_wrap = False
        
        if self.mode == MODE_SHUFFLE:
            if not self.shuffle_tracks:
                self.hw.log("_next_track: No shuffle tracks available")
                return
            self.shuffle_index = (self.shuffle_index + 1) % len(self.shuffle_tracks)
            self.current_track = self.shuffle_index + 1
        elif self.mode == MODE_RADIO:
            # In radio mode, don't manually advance (virtual time handles it)
            self.hw.log("_next_track: Radio mode - manual advance disabled")
            return
        else:
            total = self._get_track_count()
            if total == 0:
                self.hw.log("_next_track: No tracks available")
                return
            if self.current_track >= total:
                self.current_track = 1
                folder_wrap = old_track >= total and total > 0
            else:
                self.current_track += 1
        
        # Get track info for logging
        new_tr = self._get_current_track()
        new_title = new_tr.get('title', 'Unknown') if new_tr else 'Unknown'
        new_artist = new_tr.get('artist', 'Unknown') if new_tr else 'Unknown'
        self.hw.log(f"_next_track: album {old_album+1} track {old_track} -> album {self.current_album_index+1} track {self.current_track}")
        self.hw.log(f"_next_track: Will play '{new_title}' by {new_artist}")
        self._folder_wrap_play = folder_wrap
        self._save_state("next track")
        self._start_playback_for_current()
    
    def _prev_track(self):
        """Move to previous track."""
        old_track = self.current_track
        old_album = self.current_album_index
        
        if self.mode == MODE_SHUFFLE:
            if not self.shuffle_tracks:
                self.hw.log("_prev_track: No shuffle tracks available")
                return
            self.shuffle_index = (self.shuffle_index - 1) % len(self.shuffle_tracks)
            self.current_track = self.shuffle_index + 1
        elif self.mode == MODE_RADIO:
            # In radio mode, don't manually advance (virtual time handles it)
            self.hw.log("_prev_track: Radio mode - manual advance disabled")
            return
        else:
            total = self._get_track_count()
            if total == 0:
                self.hw.log("_prev_track: No tracks available")
                return
            if self.current_track <= 1:
                self.current_track = total
            else:
                self.current_track -= 1
        
        self.hw.log(f"_prev_track: album {old_album+1} track {old_track} -> album {self.current_album_index+1} track {self.current_track}")
        self._save_state("prev track")
        self._start_playback_for_current()
    
    def _next_album(self, from_auto_advance=False):
        """Move to next album/playlist (long press).
        
        In shuffle mode: advance to next album/playlist/station in the source list
        and reshuffle that source's tracks.
        In album/playlist mode: advance to next album/playlist.

        from_auto_advance: if True, skip the generic "long press" log line.
        """
        if not from_auto_advance:
            self.hw.log("Long press: next album/playlist")
        
        if self.mode == MODE_SHUFFLE and self._shuffle_source_type in ('album', 'playlist', 'station'):
            # In shuffle mode: advance to next source and rebuild shuffle_tracks (fixes
            # basic-mode 'station' shuffle, which was falling through to the album branch
            # and leaving stale shuffle_tracks from the previous folder).
            if self._shuffle_source_type == 'album':
                if self.albums:
                    self.current_album_index = (self.current_album_index + 1) % len(self.albums)
                    new_source = self.albums[self.current_album_index]
                    tracks = new_source.get('tracks', [])
                    source_name = new_source.get('name', 'Unknown')
                    self.hw.log(f"Shuffle: advancing to next album '{source_name}' (idx={self.current_album_index})")
                else:
                    return
            else:
                # playlist (GUI) or station (basic mode) — both use self.playlists
                if self.playlists:
                    self.current_album_index = (self.current_album_index + 1) % len(self.playlists)
                    new_source = self.playlists[self.current_album_index]
                    tracks = new_source.get('tracks', [])
                    default_name = (
                        'Station' if self._shuffle_source_type == 'station' else 'Playlist'
                    )
                    source_name = new_source.get('name', default_name)
                    kind = (
                        'station'
                        if self._shuffle_source_type == 'station'
                        else 'playlist'
                    )
                    self.hw.log(
                        f"Shuffle: advancing to next {kind} '{source_name}' (idx={self.current_album_index})"
                    )
                else:
                    return
            
            if not tracks:
                self.hw.log("Shuffle: next source has no tracks")
                return
            
            # Reshuffle the new source's tracks
            self.shuffle_tracks = list(tracks)
            for i in range(len(self.shuffle_tracks) - 1, 0, -1):
                j = randint(0, i)
                self.shuffle_tracks[i], self.shuffle_tracks[j] = self.shuffle_tracks[j], self.shuffle_tracks[i]
            self.shuffle_index = 0
            self.current_track = 1
            self.hw.log(f"Mode: Shuffle ({source_name}, {len(self.shuffle_tracks)} tracks)")
            self._save_state("shuffle next album")
            
            # Set delay_playback so firmware can play AM overlay
            if hasattr(self.hw, 'set_delay_playback'):
                self.hw.set_delay_playback(True)
            self._start_playback_for_current()
        elif self.mode == MODE_PLAYLIST:
            self.current_album_index = (self.current_album_index + 1) % max(len(self.playlists), 1)
            self.current_track = 1
            self._save_state("next playlist")
            if hasattr(self.hw, 'set_delay_playback'):
                self.hw.set_delay_playback(True)
            self._start_playback_for_current()
        else:
            # Album mode (or shuffle library — just advance album)
            self.current_album_index = (self.current_album_index + 1) % max(len(self.albums), 1)
            self.current_track = 1
            self._save_state("next album")
            if hasattr(self.hw, 'set_delay_playback'):
                self.hw.set_delay_playback(True)
            self._start_playback_for_current()
    
    def on_track_finished(self):
        """Called when current track finishes playing."""
        if not self.power_on:
            return
        
        if self.mode == MODE_RADIO:
            self.hw.log("Track finished, auto-advancing (radio)")
            self._advance_radio_track()
            return
        
        # In basic mode, check for an asynchronous "file not found" error (0x06).
        # Cheap DFPlayer clones lower BUSY immediately (so play_track returns True),
        # then send error 0x06 after the fact when they can't find the file.
        # By the time on_track_finished fires (BUSY / UART / query_status), the error
        # is sitting in hw._last_error_code.  Trim the station now so the device
        # doesn't keep trying phantom tracks.
        if self.basic_mode and getattr(self.hw, '_last_error_code', None) == 6:
            tracks = self._get_current_tracks()
            if tracks and 0 < self.current_track <= len(tracks):
                folder = tracks[self.current_track - 1].get('folder')
                if folder is not None:
                    self.hw.log(f"BASIC: Async file-not-found for folder {folder} track {self.current_track}, correcting station")
                    self._handle_basic_track_not_found(folder, self.current_track)
                    return

        # Basic mode: end of station shuffle / library shuffle (before sequential branch)
        if self.basic_mode and self.mode == MODE_SHUFFLE and self.shuffle_tracks:
            n = len(self.shuffle_tracks)
            if n > 0 and self.shuffle_index >= n - 1:
                if self._shuffle_source_type in ('album', 'playlist', 'station'):
                    if self.advance_next_station:
                        self.hw.log(
                            "Track finished: finished shuffled station, advancing to next station"
                        )
                        self._next_album(from_auto_advance=True)
                        return
                    if not self.loop_stations:
                        self.hw.log(
                            "Track finished: end of shuffled station (no loop), stopping"
                        )
                        self.hw.stop()
                        self.is_playing = False
                        return
                elif self._shuffle_source_type is None:
                    # Library shuffle (all tracks): one full pass then stop if not looping
                    if not self.loop_stations:
                        self.hw.log(
                            "Track finished: end of library shuffle pass, stopping"
                        )
                        self.hw.stop()
                        self.is_playing = False
                        return

        # Basic mode: end of station in sequential (playlist) mode
        if self.basic_mode and self.mode == MODE_PLAYLIST:
            total = self._get_track_count()
            if total > 0 and self.current_track >= total:
                if self.advance_next_station:
                    self.hw.log(
                        "Track finished: end of station, advancing to next station"
                    )
                    self._next_album(from_auto_advance=True)
                    return
                if not self.loop_stations:
                    self.hw.log("Track finished: end of station (loop disabled), stopping")
                    self.hw.stop()
                    self.is_playing = False
                    return

        self.hw.log("Track finished, auto-advancing")
        self._next_track()
    
    def _advance_radio_track(self):
        """Advance to next track in radio mode based on virtual time.
        Called when a track finishes - uses virtual time to determine next track.
        """
        if not self.radio_stations or self.radio_station_index >= len(self.radio_stations):
            return
        
        station = self.radio_stations[self.radio_station_index]
        if not station.tracks:
            return
        
        # Calculate current virtual position
        if self.radio_mode_start_ms is None:
            self.radio_mode_start_ms = ticks_ms()
        elapsed_ms = ticks_diff(ticks_ms(), self.radio_mode_start_ms)
        virtual_pos_ms = (station.start_offset_ms + elapsed_ms) % station.total_duration_ms

        # Find which track should be playing at this virtual time
        current_track, current_offset = self._find_track_at_position(station.tracks, virtual_pos_ms)
        if not current_track:
            return
        
        current_track_idx = station.tracks.index(current_track) + 1 if current_track in station.tracks else 1
        
        # When a track finishes, we need to advance to the next track in the station
        # Check if virtual time has already moved to the next track
        if current_track_idx != self.current_track:
            # Virtual time says we should be on a different track - use that
            self.current_track = current_track_idx
            self._start_playback_for_track(current_track, start_ms=current_offset)
            self.hw.log(f"Radio advanced to track {current_track_idx} at {current_offset // 1000}s (virtual time)")
        else:
            # Still on the same track according to virtual time, but track finished
            # Force advance to next track in the station sequence
            next_track_idx = (self.current_track % len(station.tracks)) + 1
            
            next_track = station.tracks[next_track_idx - 1]
            # Calculate offset for next track based on virtual time
            # Find cumulative time up to this track
            cumulative = 0
            for i in range(next_track_idx - 1):
                duration_ms = int((station.tracks[i].get('duration', 0) or 0) * 1000)
                if duration_ms <= 0:
                    duration_ms = 180000
                cumulative += duration_ms
            
            # Calculate offset within next track
            next_offset = virtual_pos_ms - cumulative
            if next_offset < 0:
                # Virtual time hasn't reached this track yet, start from beginning
                next_offset = 0
            else:
                next_track_duration = int((next_track.get('duration', 0) or 0) * 1000)
                if next_track_duration <= 0:
                    next_track_duration = 180000
                if next_offset >= next_track_duration:
                    # Virtual time is past this track, wrap to beginning
                    next_offset = 0
            
            self.current_track = next_track_idx
            self._radio_advance_cooldown_until_ms = ticks_ms() + 1500
            self._start_playback_for_track(next_track, start_ms=next_offset)
            self.hw.log(f"Radio advanced to track {next_track_idx} at {next_offset // 1000}s (track finished, forced advance)")
    
    # ===========================
    #   MODE SWITCHING
    # ===========================
    
    def _arm_am_overlay_before_next_play(self, reason=""):
        """Stop and set delay_playback so firmware plays AM.wav before the next track.
        
        When already in MODE_SHUFFLE, switch_mode(MODE_SHUFFLE) returns immediately and
        would skip stop + delay — call this when changing shuffle *variant* (e.g. station
        shuffle -> library shuffle) so AM still plays.
        """
        self.hw.stop()
        self.is_playing = False
        if hasattr(self.hw, 'set_delay_playback'):
            self.hw.set_delay_playback(True)
        if reason:
            self.hw.log(f"[MODE] AM overlay: {reason}")
    
    def switch_mode(self, new_mode):
        """Switch to a new mode."""
        if new_mode == self.mode:
            return
        
        old_mode = self.mode
        self.hw.log(f"[MODE] {old_mode} -> {new_mode}")
        
        # Validate mode switch
        if self.basic_mode and new_mode == MODE_ALBUM:
            self.hw.log("[MODE] Album mode not available in basic mode")
            return
        if new_mode == MODE_PLAYLIST and not self.playlists:
            self.hw.log("[MODE] No playlists, cannot switch")
            return
        if new_mode == MODE_ALBUM and not self.albums:
            self.hw.log("[MODE] No albums, cannot switch")
            return
        
        # Clear shuffle source type when leaving shuffle mode
        if self.mode == MODE_SHUFFLE and new_mode != MODE_SHUFFLE:
            self._shuffle_source_type = None
        
        self.mode = new_mode
        
        # Stop current playback before switching modes
        self.hw.stop()
        self.is_playing = False
        
        # Enable playback delay so GUI can sequence AM overlay before track
        if hasattr(self.hw, 'set_delay_playback'):
            self.hw.set_delay_playback(True)
        
        # Note: AM overlay is played by GUI layer to ensure proper sequencing
        
        if new_mode == MODE_SHUFFLE:
            # Only initialize if shuffle_tracks is empty (don't overwrite existing shuffle)
            if not self.shuffle_tracks:
                self._init_shuffle()
        elif new_mode == MODE_RADIO:
            if not self.radio_stations or self.radio_mode_start_ms is None:
                self._init_radio()
            # Radio mode playback is started in _init_radio() or handled by tune_radio()
            self._save_state("mode switch")
            return
        else:
            # For album/playlist mode, reset to track 1
            self.current_track = 1
            
            # Reset album_index to 0 when switching between album and playlist modes
            if (old_mode == MODE_ALBUM and new_mode == MODE_PLAYLIST) or \
               (old_mode == MODE_PLAYLIST and new_mode == MODE_ALBUM):
                self.current_album_index = 0
            
            # Ensure album_index is valid for the new mode
            if new_mode == MODE_PLAYLIST:
                if self.playlists and self.current_album_index >= len(self.playlists):
                    self.current_album_index = 0
            elif new_mode == MODE_ALBUM:
                if self.albums and self.current_album_index >= len(self.albums):
                    self.current_album_index = 0
            
            self.hw.log(f"[MODE] {old_mode} -> {new_mode}, album_idx={self.current_album_index}")
        
        self._save_state("mode switch")
        self._start_playback_for_current()
    
    def _init_shuffle(self):
        """Initialize shuffle mode (defaults to library shuffle when called from switch_mode)."""
        self._init_library_shuffle()
    
    def _init_radio(self):
        """Initialize radio mode with stations.
        
        Only initializes if not already initialized, to preserve virtual time clock
        and station random offsets across mode switches.
        """
        # If radio mode is already initialized, don't reinitialize (preserve virtual time)
        if self.radio_stations and self.radio_mode_start_ms is not None:
            self.hw.log("Radio mode already initialized, preserving virtual time")
            return
        
        # Initialize radio mode for the first time
        self.radio_stations = []
        self.radio_mode_start_ms = ticks_ms()
        
        # In basic mode, skip the full-library mega-station and albums
        if not self.basic_mode:
            # Station 0: Full library
            all_tracks = self.hw.get_all_tracks() or []
            if all_tracks:
                total_ms = sum((t.get('duration', 0) or 0) * 1000 for t in all_tracks)
                total_ms = max(total_ms, 1)
                random_offset = randint(0, max(int(total_ms) - 1, 0))
                self.radio_stations.append(RadioStation(
                    name="Full Library",
                    tracks=all_tracks,
                    total_duration_ms=int(total_ms),
                    start_offset_ms=random_offset
                ))
                self.hw.log(f"Station 'Full Library': total={total_ms}ms, start_offset={random_offset}ms")
        
        # Albums as stations (skipped in basic mode -- albums is empty)
        for album in self.albums:
            if album.get('id') == 0 and album.get('name') == 'Library':
                continue
            tracks = album.get('tracks', [])
            if not tracks:
                continue
            total_ms = sum((t.get('duration', 0) or 0) * 1000 for t in tracks)
            total_ms = max(total_ms, 1)
            # Generate random start offset (0 to total_ms-1)
            random_offset = randint(0, max(int(total_ms) - 1, 0))
            self.radio_stations.append(RadioStation(
                name=album.get('name', 'Unknown Album'),
                tracks=tracks,
                total_duration_ms=int(total_ms),
                start_offset_ms=random_offset
            ))
            self.hw.log(f"Station '{album.get('name', 'Unknown')}': total={total_ms}ms, start_offset={random_offset}ms")
        
        # Playlists as stations
        for playlist in self.playlists:
            if playlist.get('id') == 0 and playlist.get('name') == 'Library':
                continue
            tracks = playlist.get('tracks', [])
            if not tracks:
                continue
            total_ms = sum((t.get('duration', 0) or 0) * 1000 for t in tracks)
            total_ms = max(total_ms, 1)
            # Generate random start offset (0 to total_ms-1)
            random_offset = randint(0, max(int(total_ms) - 1, 0))
            self.radio_stations.append(RadioStation(
                name=f"Playlist: {playlist.get('name', 'Unknown')}",
                tracks=tracks,
                total_duration_ms=int(total_ms),
                start_offset_ms=random_offset
            ))
            self.hw.log(f"Station 'Playlist: {playlist.get('name', 'Unknown')}': total={total_ms}ms, start_offset={random_offset}ms")
        
        self.radio_station_index = 0
        self.hw.log(f"Radio initialized with {len(self.radio_stations)} stations at time {self.radio_mode_start_ms}")
        
        # Note: AM overlay is already played in switch_mode() when switching to radio mode
        # Don't play it again here to avoid double-playing
        
        # Start playback at the first station's virtual position
        if self.radio_stations:
            # Calculate initial virtual position for first station
            # At initialization, elapsed time is 0, so virtual position = start_offset
            station = self.radio_stations[0]
            if station.tracks:
                virtual_pos_ms = station.start_offset_ms % station.total_duration_ms
                track, offset_ms = self._find_track_at_position(station.tracks, virtual_pos_ms)
                if track:
                    track_idx = station.tracks.index(track) + 1 if track in station.tracks else 1
                    self.current_track = track_idx
                    self._start_playback_for_track(track, start_ms=offset_ms)
                    self.hw.log(f"Radio started: {station.name} - Track {track_idx} at {offset_ms // 1000}s (offset={offset_ms}ms from start_offset={station.start_offset_ms}ms)")
    
    def tune_radio(self, dial_value):
        """
        Tune the radio dial (0-100).
        Called when the radio dial is moved.
        
        Each station has its own virtual timeline that continues independently.
        When you tune to a station, you hear what's playing at that station's
        current virtual time position. When you tune away and come back, you
        pick up where that station's timeline is now.
        """
        if self.mode != MODE_RADIO:
            self.switch_mode(MODE_RADIO)
        
        if not self.radio_stations:
            return
        
        # Map dial (0-100) to station index
        max_idx = len(self.radio_stations) - 1
        station_idx = int((dial_value / 100.0) * max_idx)
        station_idx = max(0, min(station_idx, max_idx))
        
        # Check if station changed
        station_changed = (station_idx != self.radio_station_index)
        self.radio_station_index = station_idx
        
        station = self.radio_stations[station_idx]
        if not station.tracks:
            return
        
        # Calculate virtual position based on elapsed time since radio mode started
        # Each station has its own timeline: (start_offset + elapsed) % total_duration
        # This ensures that when you tune back to a station, it continues where it would be
        # IMPORTANT: radio_mode_start_ms should already be set by _init_radio()
        # Only set it here if radio mode wasn't properly initialized
        if self.radio_mode_start_ms is None:
            self.hw.log("Warning: radio_mode_start_ms was None, initializing radio mode now")
            self._init_radio()
            if self.radio_mode_start_ms is None:
                return  # Still None after init, something is wrong
        
        elapsed_ms = ticks_diff(ticks_ms(), self.radio_mode_start_ms)
        virtual_pos_ms = (station.start_offset_ms + elapsed_ms) % station.total_duration_ms
        
        # Log for debugging
        self.hw.log(f"[RADIO DEBUG] tune_radio: dial={dial_value}, station_idx={station_idx}, station_changed={station_changed}")
        self.hw.log(f"[RADIO DEBUG] Virtual time: radio_mode_start_ms={self.radio_mode_start_ms}, elapsed={elapsed_ms}ms")
        self.hw.log(f"[RADIO DEBUG] Station '{station.name}': start_offset={station.start_offset_ms}ms, total_duration={station.total_duration_ms}ms")
        self.hw.log(f"[RADIO DEBUG] Calculated virtual_pos={virtual_pos_ms}ms (formula: ({station.start_offset_ms} + {elapsed_ms}) % {station.total_duration_ms})")
        
        # Find track at this position in the station's virtual timeline
        track, offset_ms = self._find_track_at_position(station.tracks, virtual_pos_ms)
        if track:
            track_idx = station.tracks.index(track) + 1 if track in station.tracks else 1
            
            # Only restart when station or track (by virtual time) actually changed.
            # Do NOT use get_playback_position_ms() to decide restart: during tuning we often
            # just stopped playback (or AM overlay is playing), so position is 0 and we would
            # restart on every dial tick and overwrite pending playback repeatedly.
            should_restart = station_changed or (track_idx != self.current_track)
            
            current_pos_ms = self.hw.get_playback_position_ms()
            self.hw.log(f"[RADIO DEBUG] Found track: idx={track_idx}, offset={offset_ms}ms, should_restart={should_restart}")
            self.hw.log(f"[RADIO DEBUG] Current playback: pos={current_pos_ms}ms, track={self.current_track}, station_changed={station_changed}")
            
            self.current_track = track_idx
            
            if should_restart:
                self.hw.log(f"Radio: {station.name} - Track {track_idx} at {offset_ms // 1000}s")
                
                # Cooldown so the next tick does not override this tune (correct track/offset)
                self._radio_advance_cooldown_until_ms = ticks_ms() + 2500
                
                # Play AM overlay when tuning to a new station
                if station_changed:
                    self.hw.play_am_overlay()
                
                # Start playback at the correct position in the station's timeline
                self._start_playback_for_track(track, start_ms=offset_ms)
            else:
                self.hw.log(f"[RADIO DEBUG] Not restarting playback (same station and track)")
    
    def _find_track_at_position(self, tracks, position_ms):
        """Find which track contains the given position."""
        cumulative = 0
        # Reduced logging to avoid recursion - only log key info when not in status retrieval
        for i, track in enumerate(tracks):
            duration_ms = int((track.get('duration', 0) or 0) * 1000)
            if duration_ms <= 0:
                duration_ms = 180000  # Default 3 minutes
            track_end = cumulative + duration_ms
            if track_end > position_ms:
                offset = position_ms - cumulative
                return track, offset
            cumulative += duration_ms
        # Position exceeds total - wrap to first track
        return tracks[0] if tracks else None, 0
    
    # ===========================
    #   POWER CONTROL
    # ===========================
    
    def power_off(self):
        """Handle power off."""
        if not self.power_on:
            return
        
        self.hw.log("Power off")
        self.power_on = False
        
        # Save resume state
        self.resume_state = {
            'mode': self.mode,
            'album_index': self.current_album_index,
            'track': self.current_track,
            'position_ms': self.hw.get_playback_position_ms(),
        }
        
        self._save_state("power off")
        self.hw.stop()
    
    def power_on_handler(self):
        """Handle power on."""
        if self.power_on:
            return
        
        self.hw.log("Power on")
        self.power_on = True
        
        # Stop any current playback (in case power was toggled quickly)
        self.hw.stop()
        self.is_playing = False
        
        # Enable playback delay so firmware can sequence AM overlay before track
        if hasattr(self.hw, 'set_delay_playback'):
            self.hw.set_delay_playback(True)
        
        # Restore only mode and album from saved state (track/position ignored; we start from track 1)
        if self.resume_state:
            self.mode = self.resume_state.get('mode', MODE_ALBUM)
            self.current_album_index = self.resume_state.get('album_index', 0)
            self.resume_state = None
        
        # Always start from track 1 on power-on
        self.current_track = 1
        if self.mode == MODE_SHUFFLE and self.shuffle_tracks:
            self.shuffle_index = 0
        elif self.mode == MODE_RADIO and self.radio_stations:
            self.radio_station_index = 0
    
    # ===========================
    #   PLAYBACK HELPERS
    # ===========================
    
    def _get_current_tracks(self):
        """Get the track list for current mode."""
        if self.mode == MODE_SHUFFLE:
            return self.shuffle_tracks
        elif self.mode == MODE_RADIO:
            if self.radio_stations and self.radio_station_index < len(self.radio_stations):
                return self.radio_stations[self.radio_station_index].tracks
            return []
        elif self.mode == MODE_PLAYLIST:
            if self.playlists and self.current_album_index < len(self.playlists):
                tracks = self.playlists[self.current_album_index].get('tracks', [])
                # Don't log here - causes recursion when called from get_status() during logging
                return tracks
            # Don't log here - causes recursion when called from get_status() during logging
            return []
        else:  # MODE_ALBUM
            if self.albums and self.current_album_index < len(self.albums):
                return self.albums[self.current_album_index].get('tracks', [])
            return []
    
    def _get_track_count(self):
        """Get total track count for current mode."""
        tracks = self._get_current_tracks()
        count = len(tracks)
        # Don't log here - can cause recursion when called from get_status() during logging
        # Return 0 if no tracks so _next_track can detect the issue
        return count
    
    def _get_current_track(self):
        """Get the current track dict."""
        tracks = self._get_current_tracks()
        if not tracks:
            return None
        
        # In shuffle mode, use shuffle_index directly
        if self.mode == MODE_SHUFFLE:
            idx = max(self.shuffle_index, 0)
        else:
            idx = max(self.current_track - 1, 0)
        
        if idx >= len(tracks):
            return tracks[0] if tracks else None
        return tracks[idx]
    
    def _start_playback_for_current(self, start_ms=0):
        """Start playback for current track."""
        # Validate current state before getting track
        if self.mode == MODE_PLAYLIST:
            if not self.playlists:
                self.hw.log("_start_playback_for_current: No playlists available")
                return
            if self.current_album_index >= len(self.playlists):
                self.hw.log(f"_start_playback_for_current: Invalid playlist index {self.current_album_index} (have {len(self.playlists)} playlists), resetting to 0")
                self.current_album_index = 0
        elif self.mode == MODE_ALBUM:
            if not self.albums:
                self.hw.log("_start_playback_for_current: No albums available")
                return
            if self.current_album_index >= len(self.albums):
                self.hw.log(f"_start_playback_for_current: Invalid album index {self.current_album_index} (have {len(self.albums)} albums), resetting to 0")
                self.current_album_index = 0
        
        # Determine source name for logging (album/playlist/shuffle source)
        source_name = ""
        shuffle_type = ""
        if self.mode == MODE_SHUFFLE:
            if self._shuffle_source_type == 'playlist':
                shuffle_type = "playlist"
                if self.playlists and self.current_album_index < len(self.playlists):
                    source_name = self.playlists[self.current_album_index].get('name', 'Playlist')
                else:
                    source_name = "Unknown Playlist"
            elif self._shuffle_source_type == 'station':
                shuffle_type = "station"
                if self.playlists and self.current_album_index < len(self.playlists):
                    source_name = self.playlists[self.current_album_index].get('name', 'Station')
                else:
                    source_name = "Unknown Station"
            elif self._shuffle_source_type == 'album':
                shuffle_type = "album"
                if self.albums and self.current_album_index < len(self.albums):
                    source_name = self.albums[self.current_album_index].get('name', 'Album')
                else:
                    source_name = "Unknown Album"
            else:
                shuffle_type = "library"
                source_name = "Library"
        elif self.mode == MODE_PLAYLIST:
            if self.playlists and self.current_album_index < len(self.playlists):
                source_name = self.playlists[self.current_album_index].get('name', 'Unknown Playlist')
        elif self.mode == MODE_ALBUM:
            if self.albums and self.current_album_index < len(self.albums):
                source_name = self.albums[self.current_album_index].get('name', 'Unknown Album')
        
        track = self._get_current_track()
        if track:
            folder = track.get('folder')
            track_num = track.get('track_number')
            title = track.get('title', 'Unknown')
            artist = track.get('artist', 'Unknown')
            # In basic mode, report "station" instead of "playlist" so the GUI
            # displays "Station" not "Playlist".
            mode_label = "station" if (self.basic_mode and self.mode == MODE_PLAYLIST) else self.mode
            # Single combined log line so GUI parser can extract everything at once
            self.hw.log(f"_start_playback_for_current: mode={mode_label}, source={source_name}, shuffle_type={shuffle_type}, album_idx={self.current_album_index}, track_idx={self.current_track}, folder={folder}, track={track_num}")
            self.hw.log(f"_start_playback_for_current: Playing '{title}' by {artist}")
            self._start_playback_for_track(track, start_ms=start_ms)
        else:
            self.hw.log(f"_start_playback_for_current: No track available (mode={self.mode}, album_idx={self.current_album_index}, track={self.current_track})")
    
    def _start_playback_for_track(self, track, start_ms=0):
        """Start playback for a specific track."""
        if not track:
            self.hw.log("_start_playback_for_track: No track provided")
            return
        
        # For DFPlayer, we need folder/track numbers
        folder = track.get('folder', 1)
        track_num = track.get('track_number', 1)
        title = track.get('title', 'Unknown')
        artist = track.get('artist', 'Unknown')
        
        self.hw.log(f"Starting playback: '{title}' by {artist} (folder={folder}, track={track_num}, start_ms={start_ms})")
        
        # Set track hint for GUI emulator (ignored by DFPlayer firmware)
        if hasattr(self.hw, 'set_current_track_hint'):
            self.hw.set_current_track_hint(track)
        
        folder_wrap = getattr(self, "_folder_wrap_play", False)
        self._folder_wrap_play = False
        # DFPlayer wrap bridge is for same-station loop only; advance mode should not
        # run it (avoids extra glitches and wrong UX when station should change).
        if self.basic_mode and not self.loop_stations:
            folder_wrap = False
        result = self.hw.play_track(
            folder, track_num, start_ms=start_ms, folder_wrap=folder_wrap
        )
        if result:
            self.is_playing = True
            self.hw.log(f"Playback started successfully: '{title}' by {artist}")
        else:
            self.hw.log(f"Playback failed to start: '{title}' by {artist}")
            self.is_playing = False
            # Only trim station on UART "file not found" (0x06). BUSY timeout / no response
            # is not proof the file is missing (short MP3s, clone quirks, wiring).
            if self.basic_mode and getattr(self.hw, "_last_error_code", None) == 6:
                self._handle_basic_track_not_found(folder, track_num)

    def _handle_basic_track_not_found(self, folder, failed_track_num):
        """Called when a play attempt returns 'file not found' in basic mode.

        Trims the station's track list to the last known-good count so future
        _get_track_count() calls return the correct value, then restarts playback.
        Library shuffle uses ``shuffle_tracks`` / ``shuffle_index`` (not
        ``current_track`` alone); stale entries must be pruned or recovery loops
        forever and can hit maximum recursion depth.
        """
        self._basic_not_found_recovery_depth = (
            getattr(self, "_basic_not_found_recovery_depth", 0) + 1
        )
        if self._basic_not_found_recovery_depth > 8:
            self._basic_not_found_recovery_depth -= 1
            self.hw.log("BASIC: file-not-found recovery stopped (too many retries)")
            return
        try:
            if failed_track_num <= 1:
                self.hw.log(
                    f"BASIC: Station folder {folder} has no playable tracks - cannot recover"
                )
                return
            try:
                folder_id = int(folder)
            except (TypeError, ValueError):
                folder_id = folder

            actual_count = failed_track_num - 1
            matched = False
            for pl in self.playlists:
                pid = pl.get("id")
                try:
                    pid_int = int(pid)
                except (TypeError, ValueError):
                    pid_int = None
                if pid_int is not None:
                    if pid_int != folder_id:
                        continue
                elif pid != folder and pid != folder_id:
                    continue
                matched = True
                tracks = pl.get("tracks", [])
                if actual_count < len(tracks):
                    pl["tracks"] = tracks[:actual_count]
                    if hasattr(self.hw, "_known_tracks"):
                        self.hw._known_tracks[folder] = actual_count
                    self.known_tracks[folder] = actual_count
                    self.hw.log(
                        f"BASIC: Station folder {folder} corrected to {actual_count} tracks"
                    )
                break

            # Shuffle mode keeps a separate list of track dicts; trimming ``playlists``
            # does not remove references to missing files from ``shuffle_tracks``.
            if self.mode == MODE_SHUFFLE and self.shuffle_tracks:

                def _shuffle_entry_valid(t: dict) -> bool:
                    f = t.get("folder")
                    try:
                        fi = int(f) if f is not None else None
                    except (TypeError, ValueError):
                        fi = None
                    if fi != folder_id:
                        return True
                    tn = t.get("track_number", 0)
                    try:
                        tn = int(tn)
                    except (TypeError, ValueError):
                        return True
                    return tn <= actual_count

                before = len(self.shuffle_tracks)
                self.shuffle_tracks = [t for t in self.shuffle_tracks if _shuffle_entry_valid(t)]
                dropped = before - len(self.shuffle_tracks)
                if dropped:
                    self.hw.log(
                        f"BASIC: Removed {dropped} shuffle entr(y/ies) not on SD "
                        f"(folder {folder_id}, max track {actual_count})"
                    )

            if self.mode == MODE_SHUFFLE:
                if not self.shuffle_tracks:
                    self.hw.log("BASIC: No shuffle tracks left after not-found recovery")
                    return
                self.shuffle_index = min(self.shuffle_index, len(self.shuffle_tracks) - 1)
                self.shuffle_index = max(0, self.shuffle_index)
                self.current_track = self.shuffle_index + 1
            else:
                self.current_track = 1

            if not matched:
                self.hw.log(
                    f"BASIC: No playlist matched folder {folder_id} for trim; "
                    "retrying playback after shuffle prune"
                )

            self._start_playback_for_current()
        finally:
            self._basic_not_found_recovery_depth = max(
                0, getattr(self, "_basic_not_found_recovery_depth", 1) - 1
            )

    def start_playback_for_current(self, start_ms=0):
        """Request playback for the current track (public API for firmware/GUI to call after power-on or when sequencing AM overlay)."""
        self._start_playback_for_current(start_ms=start_ms)
    
    def set_volume(self, level):
        """Set volume (0-100)."""
        self.volume = max(0, min(100, level))
        self.hw.set_volume(self.volume)
    
    # ===========================
    #   STATUS HELPERS
    # ===========================
    
    def get_status(self):
        """Get current status dict for display."""
        source_name = "Unknown"
        if self.mode == MODE_SHUFFLE:
            # Determine shuffle source based on stored type
            if self._shuffle_source_type == 'playlist':
                if self.playlists and self.current_album_index < len(self.playlists):
                    source_name = self.playlists[self.current_album_index].get('name', 'Playlist')
                else:
                    source_name = "Library Shuffle"
            elif self._shuffle_source_type == 'album':
                if self.albums and self.current_album_index < len(self.albums):
                    source_name = self.albums[self.current_album_index].get('name', 'Album')
                else:
                    source_name = "Library Shuffle"
            else:
                # No specific source type means library shuffle
                source_name = "Library Shuffle"
        elif self.mode == MODE_RADIO:
            if self.radio_stations and self.radio_station_index < len(self.radio_stations):
                source_name = f"Radio: {self.radio_stations[self.radio_station_index].name}"
            else:
                source_name = "AM Radio"
        elif self.mode == MODE_PLAYLIST:
            if self.playlists and self.current_album_index < len(self.playlists):
                source_name = self.playlists[self.current_album_index].get('name', 'Unknown')
        else:
            if self.albums and self.current_album_index < len(self.albums):
                source_name = self.albums[self.current_album_index].get('name', 'Unknown')
        
        track = self._get_current_track()
        track_title = track.get('title', 'Unknown') if track else 'Unknown'
        track_artist = track.get('artist', 'Unknown') if track else 'Unknown'
        
        return {
            'mode': self.mode,
            'source': source_name,
            'track_number': self.current_track,
            'track_count': self._get_track_count(),
            'track_title': track_title,
            'track_artist': track_artist,
            'is_playing': self.is_playing,
            'power_on': self.power_on,
            'volume': self.volume,
        }

