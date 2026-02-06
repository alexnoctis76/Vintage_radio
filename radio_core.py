"""
Vintage Radio Core Logic Module

This module contains the shared state machine logic used by both:
- The MicroPython firmware (main.py) running on the device
- The PyQt GUI test mode (gui/test_mode.py) for emulation

Hardware operations are abstracted via callbacks, so the same logic
runs identically on real hardware and in emulation.

Compatible with both MicroPython and CPython.
"""

# Try MicroPython time, fall back to CPython
try:
    from time import ticks_ms, ticks_diff
except ImportError:
    import time as _time
    def ticks_ms():
        return int(_time.monotonic() * 1000)
    def ticks_diff(a, b):
        return a - b

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
LONG_PRESS_MS = 1000
TAP_WINDOW_MS = 800
BUSY_CONFIRM_MS = 1800
POST_CMD_GUARD_MS = 120
MAX_ALBUM_NUM = 99

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
    Implement this for real hardware (DFPlayer) or emulation (pygame).
    """
    
    def play_track(self, folder, track, start_ms=0):
        """Play a track. folder/track for DFPlayer, or use metadata mapping."""
        raise NotImplementedError
    
    def stop(self):
        """Stop playback."""
        raise NotImplementedError
    
    def set_volume(self, level):
        """Set volume (0-100)."""
        raise NotImplementedError
    
    def is_playing(self):
        """Return True if currently playing."""
        raise NotImplementedError
    
    def get_playback_position_ms(self):
        """Return current playback position in milliseconds."""
        raise NotImplementedError
    
    def play_am_overlay(self):
        """Play the AM radio sound overlay."""
        raise NotImplementedError
    
    def save_state(self, state_dict):
        """Persist state to storage."""
        raise NotImplementedError
    
    def load_state(self):
        """Load state from storage. Returns dict or None."""
        raise NotImplementedError
    
    def log(self, message):
        """Log a message."""
        raise NotImplementedError
    
    def get_albums(self):
        """Return list of album dicts: [{'id': int, 'name': str, 'tracks': [...]}]"""
        raise NotImplementedError
    
    def get_playlists(self):
        """Return list of playlist dicts: [{'id': int, 'name': str, 'tracks': [...]}]"""
        raise NotImplementedError
    
    def get_all_tracks(self):
        """Return list of all track dicts."""
        raise NotImplementedError


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
    
    def __init__(self, hardware):
        """
        Initialize the radio core.
        
        Args:
            hardware: An object implementing HardwareInterface
        """
        self.hw = hardware
        
        # Current state
        self.mode = MODE_ALBUM
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
        
        # Track the source type when entering shuffle mode (for "shuffle current" functionality)
        self._shuffle_source_type = None  # 'album' or 'playlist'
        
        # Button handling state
        self.tap_count = 0
        self.press_start_ms = 0
        self.last_release_ms = 0
        self.button_down = False
        
        # Resume state (for power off/on)
        self.resume_state = None
        
        # Volume
        self.volume = 100
        
        # Known tracks per album (for firmware compatibility)
        self.known_tracks = {}
    
    def init(self):
        """Initialize the radio - load state and start playback."""
        self._load_data()
        self._load_state()
        if self.power_on:
            self._start_playback_for_current()
    
    def _load_data(self):
        """Load albums, playlists, and tracks from hardware."""
        self.albums = self.hw.get_albums() or []
        self.playlists = self.hw.get_playlists() or []
        
        # Ensure we have at least one album (full library)
        if not self.albums:
            all_tracks = self.hw.get_all_tracks() or []
            self.albums = [{'id': 0, 'name': 'Library', 'tracks': all_tracks}]
        
        # Ensure we have at least one playlist (full library)
        if not self.playlists:
            all_tracks = self.hw.get_all_tracks() or []
            self.playlists = [{'id': 0, 'name': 'Library', 'tracks': all_tracks}]
        
        self.hw.log(f"Loaded {len(self.albums)} albums, {len(self.playlists)} playlists")
        for i, playlist in enumerate(self.playlists):
            self.hw.log(f"[PLAYLIST DEBUG] Playlist {i}: name='{playlist.get('name', 'Unknown')}', tracks={len(playlist.get('tracks', []))}")
    
    def _load_state(self):
        """Load persisted state."""
        state = self.hw.load_state()
        if state:
            self.mode = state.get('mode', MODE_ALBUM)
            self.current_album_index = state.get('album_index', 0)
            self.current_track = state.get('track', 1)
            self.known_tracks = state.get('known_tracks', {})
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
        # If we're in a tap window and get a new press, preserve tap_count for potential long press
        # This allows "tap + hold" to work even if tap window hasn't expired yet
        if self.tap_count > 0 and ticks_diff(ticks_ms(), self.last_release_ms) < TAP_WINDOW_MS:
            # Cancel any pending tap resolution - we might be doing a long press
            pass  # tap_count is preserved, will be used in _handle_long_press if this becomes a long press
        self.button_down = True
        self.press_start_ms = ticks_ms()
    
    def on_button_release(self):
        """Called when button is released."""
        if not self.power_on or not self.button_down:
            return
        self.button_down = False
        
        now = ticks_ms()
        press_duration = ticks_diff(now, self.press_start_ms)
        
        if press_duration >= LONG_PRESS_MS:
            self._handle_long_press()
            self.tap_count = 0
            self.last_release_ms = 0
        else:
            self.tap_count += 1
            self.last_release_ms = now
            self.hw.log(f"Tap detected, count={self.tap_count}")
    
    def tick(self):
        """
        Called regularly (e.g., every 10-50ms) to process timing-based events.
        Returns True if something happened.
        """
        if not self.power_on:
            return False
        
        now = ticks_ms()
        
        # Process tap window timeout
        if self.tap_count > 0 and ticks_diff(now, self.last_release_ms) >= TAP_WINDOW_MS:
            self._resolve_taps()
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
            # Virtual time says we should be on a different track - advance
            self.current_track = current_track_idx
            self._start_playback_for_track(current_track, start_ms=current_offset)
            self.hw.log(f"Radio advanced to track {current_track_idx} at {current_offset // 1000}s (virtual time)")
            return True
        
        return False
    
    def _resolve_taps(self):
        """Process accumulated taps after tap window expires."""
        # Only resolve if button is not currently pressed (not a long press)
        if self.button_down:
            # Button is pressed, might be a long press - don't resolve taps yet
            return
        
        if self.tap_count >= 3:
            self._triple_tap()
        elif self.tap_count == 2:
            self._double_tap()
        elif self.tap_count == 1:
            self._single_tap()
        self.tap_count = 0
        self.last_release_ms = 0
    
    def _single_tap(self):
        """Single tap - next track."""
        self.hw.log("Single tap: next track")
        self._next_track()
    
    def _double_tap(self):
        """Double tap - previous track."""
        self.hw.log("Double tap: previous track")
        self._prev_track()
    
    def _triple_tap(self):
        """Triple tap - restart current album/playlist."""
        self.hw.log("Triple tap: restart")
        self.current_track = 1
        self._save_state("triple tap restart")
        self._start_playback_for_current()
    
    def _handle_long_press(self):
        """
        Long press - mode switching based on tap count before hold:
        -_   (1 tap + hold) = Toggle Album/Playlist
        --_  (2 taps + hold) = Shuffle current album/playlist
        ---_ (3+ taps + hold) = Shuffle entire library
        _    (just hold) = Next album
        """
        # Save tap_count before it gets reset
        saved_tap_count = self.tap_count
        self.hw.log(f"Long press with tap_count={saved_tap_count}")
        
        if saved_tap_count >= 3:
            # Three taps + hold = shuffle entire library
            self._init_library_shuffle()
            self.hw.log("Mode: Shuffle (Library)")
        elif saved_tap_count == 2:
            # Two taps + hold = shuffle current album/playlist
            self._init_current_shuffle()
        elif saved_tap_count == 1:
            # One tap + hold = toggle between album/playlist
            self._cycle_mode_basic()
        else:
            # Just long press = next album
            self._next_album()
    
    def _cycle_mode_basic(self):
        """Cycle between album and playlist modes.
        
        If in shuffle or radio mode, switch back to album mode.
        """
        if self.mode == MODE_ALBUM:
            self.switch_mode(MODE_PLAYLIST)
        elif self.mode == MODE_PLAYLIST:
            self.switch_mode(MODE_ALBUM)
        else:
            # From shuffle or radio, go back to album mode
            self.switch_mode(MODE_ALBUM)
    
    def _init_current_shuffle(self):
        """Initialize shuffle mode for current album/playlist."""
        tracks = []
        source_name = 'Unknown'
        
        # Determine source based on current mode (before switching to shuffle)
        # If already in shuffle mode, use the stored source type
        if self.mode == MODE_SHUFFLE and self._shuffle_source_type:
            # We're already in shuffle, use the stored source type
            if self._shuffle_source_type == 'playlist':
                if self.playlists and self.current_album_index < len(self.playlists):
                    tracks = self.playlists[self.current_album_index].get('tracks', [])
                    source_name = self.playlists[self.current_album_index].get('name', 'Playlist')
            else:  # 'album'
                if self.albums and self.current_album_index < len(self.albums):
                    tracks = self.albums[self.current_album_index].get('tracks', [])
                    source_name = self.albums[self.current_album_index].get('name', 'Album')
        elif self.mode == MODE_PLAYLIST:
            # Currently in playlist mode - shuffle current playlist
            if self.playlists and self.current_album_index < len(self.playlists):
                tracks = self.playlists[self.current_album_index].get('tracks', [])
                source_name = self.playlists[self.current_album_index].get('name', 'Playlist')
                self._shuffle_source_type = 'playlist'
        else:
            # Currently in album mode (or other mode) - shuffle current album
            if self.albums and self.current_album_index < len(self.albums):
                tracks = self.albums[self.current_album_index].get('tracks', [])
                source_name = self.albums[self.current_album_index].get('name', 'Album')
                self._shuffle_source_type = 'album'
        
        # Fallback: if no tracks found, use library
        if not tracks:
            all_tracks = self.hw.get_all_tracks() or []
            tracks = list(all_tracks)
            source_name = 'Library'
            self._shuffle_source_type = None
            self.hw.log("Warning: No current album/playlist found, shuffling library instead")
        
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
        self.mode = MODE_SHUFFLE
        self.hw.log(f"Mode: Shuffle ({source_name}, {len(self.shuffle_tracks)} tracks)")
        self._save_state("shuffle current")
        
        # Stop current playback and enable delay for AM overlay sequencing (same as switch_mode)
        self.hw.stop()
        self.is_playing = False
        if hasattr(self.hw, 'set_delay_playback'):
            self.hw.set_delay_playback(True)
        
        # Start playback (will be delayed if delay_playback is True)
        self._start_playback_for_current()
    
    def _init_library_shuffle(self):
        """Initialize shuffle mode for entire library."""
        all_tracks = self.hw.get_all_tracks() or []
        # Create a fresh copy and shuffle
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
        self.mode = MODE_SHUFFLE
        self._shuffle_source_type = None  # Library shuffle has no specific source
        self.hw.log(f"Mode: Shuffle (Library, {len(self.shuffle_tracks)} tracks)")
        self._save_state("shuffle library")
        
        # Stop current playback and enable delay for AM overlay sequencing (same as switch_mode)
        self.hw.stop()
        self.is_playing = False
        if hasattr(self.hw, 'set_delay_playback'):
            self.hw.set_delay_playback(True)
        
        # Start playback (will be delayed if delay_playback is True)
        self._start_playback_for_current()
    
    # ===========================
    #   TRACK NAVIGATION
    # ===========================
    
    def _next_track(self):
        """Move to next track."""
        if self.mode == MODE_SHUFFLE:
            if not self.shuffle_tracks:
                return
            self.shuffle_index = (self.shuffle_index + 1) % len(self.shuffle_tracks)
            self.current_track = self.shuffle_index + 1
        elif self.mode == MODE_RADIO:
            # In radio mode, don't manually advance (virtual time handles it)
            return
        else:
            total = self._get_track_count()
            if total == 0:
                return
            if self.current_track >= total:
                self.current_track = 1
            else:
                self.current_track += 1
        
        self._save_state("next track")
        self._start_playback_for_current()
    
    def _prev_track(self):
        """Move to previous track."""
        if self.mode == MODE_SHUFFLE:
            if not self.shuffle_tracks:
                return
            self.shuffle_index = (self.shuffle_index - 1) % len(self.shuffle_tracks)
            self.current_track = self.shuffle_index + 1
        elif self.mode == MODE_RADIO:
            # In radio mode, don't manually advance (virtual time handles it)
            return
        else:
            total = self._get_track_count()
            if total == 0:
                return
            if self.current_track <= 1:
                self.current_track = total
            else:
                self.current_track -= 1
        
        self._save_state("prev track")
        self._start_playback_for_current()
    
    def _next_album(self):
        """Move to next album (long press)."""
        self.hw.log("Long press: next album")
        
        if self.mode == MODE_PLAYLIST:
            self.current_album_index = (self.current_album_index + 1) % max(len(self.playlists), 1)
        else:
            self.current_album_index = (self.current_album_index + 1) % max(len(self.albums), 1)
        
        self.current_track = 1
        self._save_state("next album")
        # AM overlay is now handled in switch_mode() when mode changes
        # Don't play it here for simple album switching
        self._start_playback_for_current()
    
    def on_track_finished(self):
        """Called when current track finishes playing."""
        if not self.power_on:
            return
        
        self.hw.log("Track finished, auto-advancing")
        
        if self.mode == MODE_RADIO:
            # Radio mode: advance based on virtual time
            self._advance_radio_track()
            return
        
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
            return
        
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
            self._start_playback_for_track(next_track, start_ms=next_offset)
            self.hw.log(f"Radio advanced to track {next_track_idx} at {next_offset // 1000}s (track finished, forced advance)")
    
    # ===========================
    #   MODE SWITCHING
    # ===========================
    
    def switch_mode(self, new_mode):
        """Switch to a new mode."""
        if new_mode == self.mode:
            self.hw.log(f"[MODE DEBUG] Already in mode {new_mode}, no switch needed")
            return
        
        old_mode = self.mode
        self.hw.log(f"[MODE DEBUG] Switching from {old_mode} to {new_mode}")
        
        # Clear shuffle source type when leaving shuffle mode
        if self.mode == MODE_SHUFFLE and new_mode != MODE_SHUFFLE:
            self._shuffle_source_type = None
        
        self.mode = new_mode
        self.hw.log(f"Switched to mode: {new_mode}")
        
        # Stop current playback before switching modes
        self.hw.stop()
        self.is_playing = False
        
        # Enable playback delay so GUI can sequence AM overlay before track
        if hasattr(self.hw, 'set_delay_playback'):
            self.hw.set_delay_playback(True)
        
        # Note: AM overlay is played by GUI layer to ensure proper sequencing
        
        if new_mode == MODE_SHUFFLE:
            self._init_shuffle()
        elif new_mode == MODE_RADIO:
            # IMPORTANT: Don't reinitialize radio if already initialized (preserve virtual time)
            # Only initialize if radio_stations is empty or radio_mode_start_ms is None
            if not self.radio_stations or self.radio_mode_start_ms is None:
                self.hw.log(f"[MODE DEBUG] Initializing radio mode (stations={len(self.radio_stations) if self.radio_stations else 0}, start_ms={self.radio_mode_start_ms})")
                self._init_radio()
            else:
                self.hw.log(f"[MODE DEBUG] Radio mode already initialized, preserving virtual time (start_ms={self.radio_mode_start_ms})")
            # Radio mode playback is started in _init_radio() or handled by tune_radio()
            self._save_state("mode switch")
            return
        else:
            self.current_track = 1
        
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
        
        # Station 0: Full library
        all_tracks = self.hw.get_all_tracks() or []
        if all_tracks:
            total_ms = sum((t.get('duration', 0) or 0) * 1000 for t in all_tracks)
            total_ms = max(total_ms, 1)
            # Generate random start offset (0 to total_ms-1)
            random_offset = randint(0, max(int(total_ms) - 1, 0))
            self.radio_stations.append(RadioStation(
                name="Full Library",
                tracks=all_tracks,
                total_duration_ms=int(total_ms),
                start_offset_ms=random_offset
            ))
            self.hw.log(f"Station 'Full Library': total={total_ms}ms, start_offset={random_offset}ms")
        
        # Albums as stations
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
            
            # Get current playback position to check if we need to restart
            current_pos_ms = self.hw.get_playback_position_ms()
            
            # Calculate the expected position based on virtual time
            # If we're on the same station and track, check if actual position matches expected
            # (within a tolerance to account for playback drift)
            position_tolerance_ms = 2000  # 2 seconds tolerance
            position_matches = (
                not station_changed and 
                track_idx == self.current_track and
                abs(current_pos_ms - offset_ms) < position_tolerance_ms
            )
            
            # Only restart playback if:
            # 1. Station changed (tuning to a different station)
            # 2. Track changed (virtual time advanced to a different track)
            # 3. Position doesn't match (playback is significantly off from virtual time)
            should_restart = station_changed or (track_idx != self.current_track) or not position_matches
            
            self.hw.log(f"[RADIO DEBUG] Found track: idx={track_idx}, offset={offset_ms}ms, should_restart={should_restart}")
            self.hw.log(f"[RADIO DEBUG] Current playback: pos={current_pos_ms}ms, track={self.current_track}, station_changed={station_changed}, position_matches={position_matches}")
            
            self.current_track = track_idx
            
            if should_restart:
                self.hw.log(f"Radio: {station.name} - Track {track_idx} at {offset_ms // 1000}s")
                
                # Play AM overlay when tuning to a new station
                if station_changed:
                    self.hw.play_am_overlay()
                
                # Start playback at the correct position in the station's timeline
                self._start_playback_for_track(track, start_ms=offset_ms)
            else:
                self.hw.log(f"[RADIO DEBUG] Not restarting playback (position matches virtual time)")
    
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
        
        # Enable playback delay so GUI can sequence AM overlay before track
        if hasattr(self.hw, 'set_delay_playback'):
            self.hw.set_delay_playback(True)
        
        # Note: AM overlay is played by GUI layer to ensure proper sequencing
        
        # Resume from saved state
        if self.resume_state:
            self.mode = self.resume_state.get('mode', MODE_ALBUM)
            self.current_album_index = self.resume_state.get('album_index', 0)
            self.current_track = self.resume_state.get('track', 1)
            start_ms = self.resume_state.get('position_ms', 0)
            self.resume_state = None
            self._start_playback_for_current(start_ms=start_ms)
        else:
            self._start_playback_for_current()
    
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
        return max(len(self._get_current_tracks()), 1)
    
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
        track = self._get_current_track()
        if track:
            self._start_playback_for_track(track, start_ms=start_ms)
    
    def _start_playback_for_track(self, track, start_ms=0):
        """Start playback for a specific track."""
        if not track:
            return
        
        # Set track hint for GUI emulator (ignored by DFPlayer firmware)
        if hasattr(self.hw, 'set_current_track_hint'):
            self.hw.set_current_track_hint(track)
        
        # Check if track has translation info (album_id/track_index) for DFPlayer mode
        # If so, use translation layer; otherwise use direct folder/track_number
        album_id = track.get('album_id')
        playlist_id = track.get('playlist_id')
        track_index = track.get('track_index')
        song_id = track.get('id')
        
        if album_id is not None and track_index is not None:
            # Use translation layer for DFPlayer
            self.hw.play_track(album_id=album_id, track_index=track_index, start_ms=start_ms)
        elif song_id is not None:
            # Try song_id translation
            self.hw.play_track(song_id=song_id, start_ms=start_ms)
        else:
            # Fallback: direct folder/track (legacy or microcontroller-only mode)
            folder = track.get('folder', 1)
            track_num = track.get('track_number', 1)
            self.hw.play_track(folder, track_num, start_ms=start_ms)
        
        self.is_playing = True
    
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

