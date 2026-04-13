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
try:
    import sys as _sys
    _IS_MICROPYTHON = getattr(getattr(_sys, "implementation", None), "name", "") == "micropython"
except Exception:
    _IS_MICROPYTHON = False
try:
    import gc as _gc
except Exception:
    _gc = None

# ===========================
#      CONSTANTS
# ===========================

FADE_IN_S = 1.0
DF_BOOT_MS = 0
LONG_PRESS_MS = 500   # Hold >= 500ms = long press
TAP_WINDOW_MS = 350   # ms after last release to resolve taps (single-tap next/prev feels snappier; double-tap still detectable)
BUSY_CONFIRM_MS = 2200
POST_CMD_GUARD_MS = 120
# Ignore UART 0x3D "track finished" for this long after play start (duplicate / stale pulses).
DF_UART_END_GUARD_MS = 450
MAX_ALBUM_NUM = 99


def _agent_debug_ndjson(hypothesis_id, message, data):
    # #region agent log
    try:
        try:
            import ujson as _json  # type: ignore
        except ImportError:
            import json as _json
        payload = {
            "sessionId": "e8231e",
            "hypothesisId": hypothesis_id,
            "location": "radio_core",
            "message": message,
            "data": data,
            "timestamp": ticks_ms(),
        }
        print("#VRDBG " + _json.dumps(payload))
    except Exception:
        pass
    # #endregion


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

    def set_delay_playback_reason(self, reason):
        """Optional transition reason for delayed playback/AM sequencing."""
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
        
        # Basic mode station-end behavior (fixed; folder 99 is normal music, not UART flags).
        self.loop_stations = False
        # When True, after the last track of a station (or one full station shuffle pass),
        # advance to the next station instead of stopping or looping in place.
        self.advance_next_station = True
        # Basic mode: if saved state is shuffle but shuffle_tracks is empty, rebuild
        # after DFPlayer comms check (main_basic boot_sequence), not inside _load_state.
        self._defer_basic_shuffle_rebuild = False
    def _basic_playlist_track_count(self, playlist: dict) -> int:
        tracks = playlist.get("tracks", [])
        if tracks:
            return len(tracks)
        # Lazy-seeded basic stations carry placeholder track_count while hydrated=False.
        # Treat that as unknown until a real 0x4E hydrate runs.
        if self.basic_mode and not playlist.get("hydrated"):
            return 0
        try:
            return max(0, int(playlist.get("track_count", 0) or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _build_basic_track(folder: int, track_num: int) -> dict:
        return {
            "id": int(folder) * 1000 + int(track_num),
            "title": f"Track {int(track_num)}",
            "artist": "",
            "duration": 0,
            "folder": int(folder),
            "track_number": int(track_num),
        }

    def _clear_basic_library_virtual(self):
        """No-op: legacy hook when leaving shuffle (library shuffle removed)."""
        pass

    def _shuffle_entry_count(self):
        return len(self.shuffle_tracks)

    def _collect_heap(self, reason: str = "") -> None:
        """Best-effort heap collection for MicroPython before large list ops."""
        if _gc is None:
            return
        try:
            _gc.collect()
            if _IS_MICROPYTHON and hasattr(_gc, "mem_free"):
                free_b = int(_gc.mem_free())
                if free_b < 8 * 1024:
                    self.hw.log(f"BASIC: low heap after GC ({free_b}B) [{reason}]")
        except Exception:
            pass

    def _shuffle_index_for_track_number(self, track_num: int) -> int:
        """Index in ``shuffle_tracks`` whose ``track_number`` matches (default: physical track 1)."""
        want = int(track_num)
        for i, tr in enumerate(self.shuffle_tracks):
            try:
                if int(tr.get("track_number", 0) or 0) == want:
                    return int(i)
            except (TypeError, ValueError):
                continue
        return -1

    def _assign_and_shuffle_tracks(self, tracks, reason: str = "") -> bool:
        """Populate shuffle_tracks with minimal temporary allocations.

        Reuses the existing list buffer when possible to avoid repeated large heap
        allocations in long-running basic-mode station shuffle.
        """
        self._collect_heap(reason)
        try:
            if self.shuffle_tracks and len(self.shuffle_tracks) == len(tracks):
                for i, tr in enumerate(tracks):
                    self.shuffle_tracks[i] = tr
            else:
                self.shuffle_tracks = list(tracks)
            for i in range(len(self.shuffle_tracks) - 1, 0, -1):
                j = randint(0, i)
                self.shuffle_tracks[i], self.shuffle_tracks[j] = self.shuffle_tracks[j], self.shuffle_tracks[i]
            return True
        except MemoryError:
            self._collect_heap(reason + " retry")
            try:
                self.shuffle_tracks = list(tracks)
                for i in range(len(self.shuffle_tracks) - 1, 0, -1):
                    j = randint(0, i)
                    self.shuffle_tracks[i], self.shuffle_tracks[j] = self.shuffle_tracks[j], self.shuffle_tracks[i]
                return True
            except MemoryError:
                return False

    def _next_station_index(self) -> int:
        """Next station index in SD/folder order (basic mode)."""
        n = len(self.playlists)
        if n <= 0:
            return 0
        return (self.current_album_index + 1) % n

    def _hydrate_basic_station(self, station_index: int, *, allow_assume=False) -> int:
        """Ensure a basic-mode station has track_count populated.

        DFPlayer UART: vendor examples use ~500 ms serial read timeouts and spacing between
        commands; we use short drains + bounded retries (still synchronous on MicroPython —
        not parallel with AM). Track-count queries run before ``start_with_am`` / music play
        so the bus is not contended during the PWM overlay.

        Returns:
            >0: playable track count
             0: confirmed empty station
            -1: unknown (query did not return a stable answer)
        """
        if not self.playlists or station_index < 0 or station_index >= len(self.playlists):
            return -1

        pl = self.playlists[station_index]
        # Skip repeat UART storms on folders that already failed probe (long_press
        # can walk many slots; without this each skip costs ~1s+ DF queries).
        if pl.get("basic_hydrate_negative"):
            return -1
        if pl.get("hydrated"):
            return self._basic_playlist_track_count(pl)
        tracks = pl.get("tracks", [])
        if tracks:
            count = len(tracks)
            pl["track_count"] = count
            pl["hydrated"] = True
            try:
                folder = int(pl.get("id", station_index + 1))
            except (TypeError, ValueError):
                folder = station_index + 1
            if count > 0:
                self.known_tracks[folder] = count
                if hasattr(self.hw, "_known_tracks"):
                    self.hw._known_tracks[folder] = count
            return count

        try:
            folder = int(pl.get("id", station_index + 1))
        except (TypeError, ValueError):
            folder = station_index + 1

        # 0x4E often returns None if UART is busy (playback, track-finished frames,
        # host VRTEST). Drain and retry with increasing timeouts before treating as empty.
        drain = getattr(self.hw, "_df_drain_uart_for_query_ms", None)
        if callable(drain):
            drain(120)
        _sleep_ms(50)

        count = None
        query_single = getattr(self.hw, "query_files_in_folder", None)
        if callable(query_single):
            timeouts = (520, 700, 900)
            for tmo in timeouts:
                count = query_single(folder, suppress_errors=True, timeout_ms=tmo)
                if count is not None:
                    break
                _sleep_ms(80)
        if count is None:
            query_consensus = getattr(self.hw, "query_files_in_folder_consensus", None)
            if callable(query_consensus):
                count = query_consensus(folder, suppress_errors=True)

        if count is None:
            if allow_assume:
                guessed = int(self.known_tracks.get(folder, 0) or 0)
                if guessed > 0:
                    pl["track_count"] = guessed
                    pl["hydrated"] = True
                    pl.pop("basic_hydrate_fail_count", None)
                    pl.pop("basic_hydrate_negative", None)
                    self.hw.log(
                        f"BASIC: Station folder {folder:02d} track query unavailable, "
                        f"using cached count={guessed}"
                    )
                    return guessed
                # No prior data at all — do NOT assume 255.  Including a folder with
                # an invented count causes the library shuffle to pick non-existent
                # high-numbered tracks (e.g. track 249 in a folder that only has 30).
                fails = int(pl.get("basic_hydrate_fail_count", 0) or 0) + 1
                pl["basic_hydrate_fail_count"] = fails
                self.hw.log(
                    f"BASIC: Station folder {folder:02d} track count unavailable "
                    f"(try {fails}/2); likely UART/DF busy, not necessarily empty SD"
                )
                if fails >= 2:
                    pl["basic_hydrate_negative"] = True
                return -1
            fails = int(pl.get("basic_hydrate_fail_count", 0) or 0) + 1
            pl["basic_hydrate_fail_count"] = fails
            if fails >= 2:
                pl["basic_hydrate_negative"] = True
            return -1

        count = max(0, int(count))
        pl["track_count"] = count
        pl["hydrated"] = True
        pl.pop("basic_hydrate_fail_count", None)
        pl.pop("basic_hydrate_negative", None)
        if count > 0:
            self.known_tracks[folder] = count
            if hasattr(self.hw, "_known_tracks"):
                self.hw._known_tracks[folder] = count
            self.hw.log(f"BASIC: Station folder {folder:02d} hydrated -> {count} track(s)")
        else:
            self.hw.log(f"BASIC: Station folder {folder:02d} is empty")
        return count

    def _ensure_basic_station_ready_for_playback(self) -> bool:
        """Ensure current basic-mode station is playable (hydrated with tracks > 0)."""
        if not self.playlists:
            return False
        n = len(self.playlists)

        start = self.current_album_index % n
        for hop in range(n):
            idx = (start + hop) % n
            count = self._hydrate_basic_station(idx, allow_assume=(hop == 0))
            if count > 0:
                self.current_album_index = idx
                if self.current_track < 1 or self.current_track > count:
                    self.current_track = 1
                return True
        return False
    
    def init(self, skip_initial_playback=False):
        """Initialize the radio - load state and optionally start playback.
        skip_initial_playback: If True, do not start playback (caller will e.g. start_with_am).
        Used by firmware to match baseline: one start inside AM overlay, no double-start.
        """
        self._load_data()
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
        if len(self.playlists) <= 12:
            for i, playlist in enumerate(self.playlists):
                self.hw.log(
                    f"[PLAYLIST DEBUG] Playlist {i}: "
                    f"name='{playlist.get('name', 'Unknown')}', "
                    f"tracks={len(playlist.get('tracks', []))}, "
                    f"track_count={playlist.get('track_count', 0)}"
                )
        else:
            self.hw.log(
                f"[PLAYLIST DEBUG] Large station set loaded ({len(self.playlists)}); "
                "per-station debug lines suppressed"
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
            raw_known = state.get("known_tracks", {}) or {}
            known = {}
            if isinstance(raw_known, dict):
                for k, v in raw_known.items():
                    try:
                        kk = int(k)
                        vv = int(v)
                    except (TypeError, ValueError):
                        continue
                    if kk > 0 and vv >= 0:
                        known[kk] = vv
            self.known_tracks = known
            if hasattr(self.hw, "_known_tracks"):
                self.hw._known_tracks = dict(known)
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
            # Clamp track to valid range for current album/playlist.
            # In basic mode, skip the DFPlayer query entirely: hardware is not
            # confirmed ready here (comms check runs after core.init() returns).
            if not self.basic_mode:
                total_tracks = self._get_track_count()
                if total_tracks > 0 and self.current_track > total_tracks:
                    self.hw.log(f"Clamping track {self.current_track} to {total_tracks}")
                    self.current_track = total_tracks
            self.current_track = max(1, self.current_track)
            self.hw.log(f"Loaded state: mode={self.mode}, album={self.current_album_index}, track={self.current_track}")
            
            # Initialize mode-specific state based on loaded mode
            if self.mode == MODE_RADIO and not self.radio_stations:
                self._init_radio()
            elif self.mode == MODE_SHUFFLE and self._shuffle_entry_count() == 0:
                if self.basic_mode:
                    self._defer_basic_shuffle_rebuild = True
                else:
                    self._init_shuffle()
    
    def _save_state(self, reason="", persist=None):
        """Capture runtime state; persist to flash only when requested.

        By default, persistence is pot-off checkpoint only.
        """
        state = {
            'mode': self.mode,
            'album_index': self.current_album_index,
            'track': self.current_track,
        }
        if not _IS_MICROPYTHON:
            state['known_tracks'] = dict(self.known_tracks)
        self._runtime_state = dict(state)
        should_persist = (reason == "power off") if persist is None else bool(persist)
        if should_persist:
            self.hw.save_state(state)
    
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
          N taps + hold: 1+hold=exit shuffle to ordered station (basic); 2+hold=shuffle current station;
                         3+hold=same as 2+hold (reshuffle); non-basic 3+: reshuffle current source
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
        In shuffle: first entry in ``shuffle_tracks`` (same order as when shuffle
        started). Single/double tap move within that list via ``shuffle_index``.
        """
        self.hw.log("Triple tap: restart")
        if self.mode == MODE_SHUFFLE:
            if self._shuffle_entry_count() <= 0:
                self.hw.log("Triple tap: no shuffle tracks to restart")
                return
            self.shuffle_index = 0
            self.current_track = 1
            self.hw.log("Triple tap: restart at first track in shuffle order")
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
          1 tap  + hold = Non-basic: cycle mode; basic: exit shuffle to ordered station
          2 taps + hold = Shuffle current album/playlist/station (again = new random order)
          3+ taps + hold = Same as 2 taps (triple+hold matches double+hold in basic mode)
        """
        self.hw.log(f"_handle_long_press_with_taps: tap_count={tap_count}")
        
        if tap_count >= 3:
            self._init_current_shuffle()
            if not self.basic_mode:
                self.hw.log(
                    f"{tap_count}-tap+hold: shuffling current source (library shuffle removed)"
                )
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
    
    def _init_current_shuffle(self, _retried=False):
        """Initialize shuffle mode for current album/playlist/station."""
        self._clear_basic_library_virtual()
        tracks = []
        source_name = 'Unknown'
        
        if self.basic_mode:
            # Always shuffle the current station (playlist) regardless of mode.
            if self.playlists and self.current_album_index < len(self.playlists):
                self._hydrate_basic_station(self.current_album_index, allow_assume=True)
                station = self.playlists[self.current_album_index]
                tracks = station.get('tracks', [])
                if not tracks:
                    count = self._basic_playlist_track_count(station)
                    try:
                        folder = int(station.get("id", self.current_album_index + 1))
                    except (TypeError, ValueError):
                        folder = self.current_album_index + 1
                    if count > 0:
                        tracks = [self._build_basic_track(folder, i) for i in range(1, count + 1)]
                source_name = station.get('name', 'Station')
                self._shuffle_source_type = 'station'
        elif self.mode == MODE_SHUFFLE and not self._shuffle_source_type and not self.basic_mode:
            # Persisted state does not record shuffle source; prefer playlist then album.
            if self.playlists and self.current_album_index < len(self.playlists):
                tracks = self.playlists[self.current_album_index].get('tracks', [])
                source_name = self.playlists[self.current_album_index].get('name', 'Playlist')
                self._shuffle_source_type = 'playlist'
            if not tracks and self.albums and self.current_album_index < len(self.albums):
                tracks = self.albums[self.current_album_index].get('tracks', [])
                source_name = self.albums[self.current_album_index].get('name', 'Album')
                self._shuffle_source_type = 'album'
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
            if self.basic_mode and not _retried and self.playlists:
                self.hw.log(
                    "BASIC: No tracks for shuffle at current station; retrying station 1"
                )
                self.current_album_index = 0
                return self._init_current_shuffle(_retried=True)
            self.hw.log("Error: No tracks available to shuffle")
            return
        
        # Build shuffle list with minimal temporary allocations.
        if not self._assign_and_shuffle_tracks(tracks, reason="init_current_shuffle"):
            self.hw.log("Shuffle: low-memory while preparing shuffle; keeping current mode")
            return
        
        # Log the first few tracks to verify shuffle is working
        if len(self.shuffle_tracks) > 0:
            first_track = self.shuffle_tracks[0].get('title', 'Unknown') if self.shuffle_tracks[0] else 'Unknown'
            self.hw.log(f"Shuffled order starts with: {first_track}")
        
        self.shuffle_index = 0
        self.current_track = 1
        
        # Save shuffle source before switch; track list stays intact because switch_mode
        # only initializes shuffle when current list is empty.
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
        
        # Preserve the selected shuffle source kind.
        self._shuffle_source_type = saved_shuffle_source
        
        self.hw.log(f"Mode: Track shuffle ({source_name}, {len(self.shuffle_tracks)} tracks)")
        self._save_state("shuffle current")
        # switch_mode() already calls _start_playback_for_current(); do not call again
        # or the firmware runs two AM sequences and double delay_playback.
    
    # ===========================
    #   TRACK NAVIGATION
    # ===========================
    
    def _next_track(self):
        """Move to next track."""
        old_track = self.current_track
        old_album = self.current_album_index
        folder_wrap = False
        
        if self.mode == MODE_SHUFFLE:
            n = self._shuffle_entry_count()
            if n <= 0:
                self.hw.log("_next_track: No shuffle tracks available")
                return
            self.shuffle_index = (self.shuffle_index + 1) % n
            self.current_track = self.shuffle_index + 1
        elif self.mode == MODE_RADIO:
            # In radio mode, don't manually advance (virtual time handles it)
            self.hw.log("_next_track: Radio mode - manual advance disabled")
            return
        else:
            total = self._get_track_count()
            if total == 0:
                self.hw.log("_next_track: No tracks available")
                # #region agent log
                try:
                    pl = None
                    if self.playlists and 0 <= self.current_album_index < len(self.playlists):
                        pl = self.playlists[self.current_album_index]
                    _agent_debug_ndjson(
                        "TRK2",
                        "next_track_no_tracks",
                        {
                            "album_idx": int(self.current_album_index),
                            "basic": bool(self.basic_mode),
                            "hydrated": bool(pl.get("hydrated")) if pl else None,
                            "track_count_field": int(pl.get("track_count") or 0) if pl else None,
                            "n_list": len(pl.get("tracks") or []) if pl else None,
                        },
                    )
                except Exception:
                    pass
                # #endregion
                return
            if self.current_track >= total:
                self.current_track = 1
                folder_wrap = old_track >= total and total > 0
            else:
                self.current_track += 1
        
        # Get track info for logging
        new_tr = self._get_current_track()
        self.hw.log(f"_next_track: album {old_album+1} track {old_track} -> album {self.current_album_index+1} track {self.current_track}")
        self._folder_wrap_play = folder_wrap
        self._save_state("next track")
        self._start_playback_for_current()
    
    def _prev_track(self):
        """Move to previous track."""
        old_track = self.current_track
        old_album = self.current_album_index
        
        if self.mode == MODE_SHUFFLE:
            n = self._shuffle_entry_count()
            if n <= 0:
                self.hw.log("_prev_track: No shuffle tracks available")
                return
            self.shuffle_index = (self.shuffle_index - 1) % n
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
            prev_album_index = self.current_album_index
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
                if not self.playlists:
                    return
                if self.basic_mode and self._shuffle_source_type == "station":
                    self.current_album_index = self._next_station_index()
                else:
                    self.current_album_index = (self.current_album_index + 1) % len(self.playlists)

                n_playlists = len(self.playlists)
                default_name = (
                    "Station" if self._shuffle_source_type == "station" else "Playlist"
                )
                kind = (
                    "station"
                    if self._shuffle_source_type == "station"
                    else "playlist"
                )
                tracks = []
                new_source = self.playlists[self.current_album_index]
                for _attempt in range(n_playlists):
                    new_source = self.playlists[self.current_album_index]
                    if self.basic_mode and self._shuffle_source_type == "station":
                        self._hydrate_basic_station(self.current_album_index, allow_assume=True)
                    tracks = new_source.get("tracks", [])
                    if self.basic_mode and self._shuffle_source_type == "station" and not tracks:
                        count = self._basic_playlist_track_count(new_source)
                        try:
                            folder = int(new_source.get("id", self.current_album_index + 1))
                        except (TypeError, ValueError):
                            folder = self.current_album_index + 1
                        if count > 0:
                            tracks = [
                                self._build_basic_track(folder, i)
                                for i in range(1, count + 1)
                            ]
                    if tracks:
                        break
                    if not (self.basic_mode and self._shuffle_source_type == "station"):
                        break
                    self.hw.log(
                        f"Shuffle: station idx={self.current_album_index} has no usable tracks, skipping"
                    )
                    self.current_album_index = self._next_station_index()

                source_name = new_source.get("name", default_name)
                if tracks:
                    self.hw.log(
                        f"Shuffle: advancing to next {kind} '{source_name}' (idx={self.current_album_index})"
                    )

            if not tracks:
                if self.basic_mode and self._shuffle_source_type == "station":
                    self.hw.log(
                        "Shuffle: no playable station when advancing; reverting to previous station"
                    )
                    self.current_album_index = prev_album_index
                else:
                    self.hw.log("Shuffle: next source has no tracks")
                return
            
            # Reshuffle the new source's tracks. If heap is too fragmented, fall back
            # to ordered station mode instead of hard-failing the firmware loop.
            if not self._assign_and_shuffle_tracks(tracks, reason="next_album_shuffle"):
                self.hw.log(
                    "Shuffle: low-memory while advancing station; "
                    "falling back to ordered station mode"
                )
                self.mode = MODE_PLAYLIST
                self._shuffle_source_type = None
                self.shuffle_tracks = []
                self.shuffle_index = 0
                self.current_track = 1
                # Roll back only if the new source is not playable.
                if self.playlists and 0 <= self.current_album_index < len(self.playlists):
                    cur_pl = self.playlists[self.current_album_index]
                    if not cur_pl.get("tracks") and self._basic_playlist_track_count(cur_pl) <= 0:
                        self.current_album_index = prev_album_index
                self._maybe_schedule_station_change_am()
                self._start_playback_for_current()
                return
            self.shuffle_index = 0
            self.current_track = 1
            if self.basic_mode and self._shuffle_source_type == "station":
                si = self._shuffle_index_for_track_number(1)
                if si >= 0:
                    self.shuffle_index = si
                    self.current_track = si + 1
                    self.hw.log(
                        "Shuffle: new station starts at folder track 001 (then continues shuffled order)"
                    )
            self.hw.log(f"Mode: Track shuffle ({source_name}, {len(self.shuffle_tracks)} tracks)")
            self._save_state("shuffle next album")
            
            # AM overlay between stations unless we want handoff like _next_track (station shuffle).
            self._maybe_schedule_station_change_am()
            self._start_playback_for_current()
        elif self.mode == MODE_PLAYLIST:
            if self.basic_mode:
                self.current_album_index = self._next_station_index()
            else:
                self.current_album_index = (self.current_album_index + 1) % max(len(self.playlists), 1)
            self.current_track = 1
            self._save_state("next playlist")
            self._maybe_schedule_station_change_am()
            self._start_playback_for_current()
        else:
            # Album mode (or shuffle library — just advance album)
            self.current_album_index = (self.current_album_index + 1) % max(len(self.albums), 1)
            self.current_track = 1
            self._save_state("next album")
            self._schedule_delayed_playback("station_change")
            self._start_playback_for_current()
    
    def on_track_finished(self):
        """Called when current track finishes playing."""
        if not self.power_on:
            return
        # #region agent log
        try:
            _agent_debug_ndjson(
                "TRK1",
                "on_track_finished",
                {
                    "mode": self.mode,
                    "track": int(self.current_track),
                    "album_idx": int(self.current_album_index),
                    "basic": bool(self.basic_mode),
                },
            )
        except Exception:
            pass
        # #endregion
        
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
            cur = self._get_current_track()
            if cur is not None:
                folder = cur.get('folder')
                tn = cur.get('track_number', self.current_track)
                if folder is not None:
                    self.hw.log(
                        f"BASIC: Async file-not-found for folder {folder} track {tn}, correcting station"
                    )
                    self._handle_basic_track_not_found(folder, tn)
                    return

        # Basic mode: end of station shuffle (before sequential branch)
        if self.basic_mode and self.mode == MODE_SHUFFLE and self._shuffle_entry_count() > 0:
            n = self._shuffle_entry_count()
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
        self._schedule_delayed_playback("mode_change")
        if reason:
            self.hw.log(f"[MODE] AM overlay: {reason}")

    def _schedule_delayed_playback(self, reason):
        """Request exactly one AM transition before the next track start."""
        if hasattr(self.hw, "set_delay_playback_reason"):
            try:
                self.hw.set_delay_playback_reason(reason)
            except Exception:
                pass
        if hasattr(self.hw, "set_delay_playback"):
            self.hw.set_delay_playback(True)

    def _should_skip_station_change_am_overlay(self) -> bool:
        """True when advancing to another station should start audio like in-track advance."""
        if not self.basic_mode:
            return False
        if self.mode == MODE_SHUFFLE and self._shuffle_source_type == "station":
            return True
        return False

    def _maybe_schedule_station_change_am(self) -> None:
        if self._should_skip_station_change_am_overlay():
            self.hw.log(
                "BASIC: station advance — skipping AM overlay (direct play, same as track advance)"
            )
            return
        self._schedule_delayed_playback("station_change")
    
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
            self._clear_basic_library_virtual()

        self.mode = new_mode
        
        # Stop current playback before switching modes
        self.hw.stop()
        self.is_playing = False
        
        self._schedule_delayed_playback("mode_change")
        
        if new_mode == MODE_SHUFFLE:
            # Only initialize if shuffle list is empty (don't overwrite existing shuffle)
            if self._shuffle_entry_count() == 0:
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
    
    def _init_shuffle(self, start_playback=True):
        """Build shuffle tracks when entering shuffle with an empty list (mode cycle / boot)."""
        _ = start_playback  # API compat with firmware boot_sequence; playback is outer-owned
        self._init_current_shuffle()
        if self.mode == MODE_SHUFFLE and len(self.shuffle_tracks) == 0:
            self.hw.log("[MODE] Shuffle unavailable (no tracks); returning to playlist order")
            self.mode = MODE_PLAYLIST
            self._shuffle_source_type = None
    
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

        # Basic mode: SD card may have been swapped while the pot was off. Rediscover
        # stations like boot and drop stale per-folder counts so hydration re-queries
        # the DFPlayer (avoids playing phantom tracks from the previous card).
        if self.basic_mode:
            self.known_tracks = {}
            if hasattr(self.hw, "_known_tracks"):
                self.hw._known_tracks = {}
            self._load_data_basic()

        # Enable playback delay so firmware can sequence AM overlay before track
        self._schedule_delayed_playback("power_on")
        
        # Restore only mode and album from saved state (track/position ignored; we start from track 1)
        if self.resume_state:
            self.mode = self.resume_state.get('mode', MODE_ALBUM)
            self.current_album_index = self.resume_state.get('album_index', 0)
            self.resume_state = None

        if self.basic_mode and self.playlists:
            if self.current_album_index >= len(self.playlists):
                self.hw.log(
                    "Clamping album index %d after SD rediscover (have %d stations)"
                    % (self.current_album_index, len(self.playlists))
                )
                self.current_album_index = max(0, len(self.playlists) - 1)
        
        # Always start from track 1 on power-on
        self.current_track = 1
        if self.mode == MODE_SHUFFLE and self._shuffle_entry_count() > 0:
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
                playlist = self.playlists[self.current_album_index]
                tracks = playlist.get('tracks', [])
                if self.basic_mode and not tracks:
                    # Lazy-discovery path: hydrate current station on first access.
                    if not playlist.get("hydrated"):
                        self._hydrate_basic_station(self.current_album_index, allow_assume=True)
                    try:
                        folder = int(playlist.get("id", self.current_album_index + 1))
                    except (TypeError, ValueError):
                        folder = self.current_album_index + 1
                    n = self._basic_playlist_track_count(playlist)
                    if n > 0:
                        return [self._build_basic_track(folder, i) for i in range(1, n + 1)]
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
        if self.basic_mode and self.mode == MODE_PLAYLIST:
            if self.playlists and self.current_album_index < len(self.playlists):
                playlist = self.playlists[self.current_album_index]
                if not playlist.get("tracks") and not playlist.get("hydrated"):
                    self._hydrate_basic_station(self.current_album_index, allow_assume=True)
                return self._basic_playlist_track_count(playlist)
            return 0
        if self.mode == MODE_SHUFFLE:
            return self._shuffle_entry_count()
        tracks = self._get_current_tracks()
        count = len(tracks)
        # Don't log here - can cause recursion when called from get_status() during logging
        # Return 0 if no tracks so _next_track can detect the issue
        return count
    
    def _get_current_track(self):
        """Get the current track dict."""
        if self.basic_mode and self.mode == MODE_PLAYLIST:
            if self.playlists and self.current_album_index < len(self.playlists):
                playlist = self.playlists[self.current_album_index]
                tracks = playlist.get("tracks", [])
                if tracks:
                    idx = max(self.current_track - 1, 0)
                    if idx >= len(tracks):
                        return tracks[0] if tracks else None
                    return tracks[idx]
                count = self._basic_playlist_track_count(playlist)
                if count <= 0:
                    return None
                tnum = self.current_track
                if tnum < 1 or tnum > count:
                    tnum = 1
                try:
                    folder = int(playlist.get("id", self.current_album_index + 1))
                except (TypeError, ValueError):
                    folder = self.current_album_index + 1
                return self._build_basic_track(folder, tnum)
            return None
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
            if self.basic_mode:
                if not self._ensure_basic_station_ready_for_playback():
                    self.hw.log(
                        "_start_playback_for_current: No playable stations "
                        "(all empty or query unavailable)"
                    )
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
                shuffle_type = "station_tracks"
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
                shuffle_type = ""
                source_name = "Shuffle"
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
            # Combined log line — GUI parser extracts mode/source/shuffle_type/album_idx.
            self.hw.log(
                f"_start_playback_for_current: mode={mode_label}, source={source_name}, "
                f"shuffle_type={shuffle_type}, album_idx={self.current_album_index}"
            )
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
        result = self._hw_play_track(
            folder, track_num, start_ms=start_ms, folder_wrap=folder_wrap
        )
        if result:
            # play_track returns True when DFPlayer gates the command (delay_playback /
            # AM overlay active). Do not mark logical playback until the real start runs.
            deferred = bool(getattr(self.hw, "_delay_playback", False))
            get_oc = getattr(self.hw, "get_last_start_outcome", None)
            if callable(get_oc):
                try:
                    oc = get_oc() or {}
                    if oc.get("status") == "delayed":
                        deferred = True
                except Exception:
                    pass
            if deferred:
                self.is_playing = False
                self.hw.log(
                    "Playback deferred (overlay/delay gate); firmware will start after AM"
                )
                return
            self.is_playing = True
            self.hw.log(f"Playback started successfully: '{title}' by {artist}")
        else:
            self.hw.log(f"Playback failed to start: '{title}' by {artist}")
            self.is_playing = False
            # Only trim station on UART "file not found" (0x06). BUSY timeout / no response
            # is not proof the file is missing (short MP3s, clone quirks, wiring).
            if self.basic_mode and getattr(self.hw, "_last_error_code", None) == 6:
                self._handle_basic_track_not_found(folder, track_num)
                return
            deferred = bool(getattr(self.hw, "_delay_playback", False))
            get_oc = getattr(self.hw, "get_last_start_outcome", None)
            if callable(get_oc):
                try:
                    oc = get_oc() or {}
                    if oc.get("status") == "delayed":
                        deferred = True
                except Exception:
                    pass
    def _hw_play_track(self, folder, track_num, *, start_ms=0, folder_wrap=False, **kwargs):
        try:
            return self.hw.play_track(
                folder, track_num, start_ms=start_ms, folder_wrap=folder_wrap, **kwargs
            )
        except TypeError:
            return self.hw.play_track(
                folder, track_num, start_ms=start_ms, folder_wrap=folder_wrap
            )

    def _handle_basic_track_not_found(self, folder, failed_track_num):
        """Called when a play attempt returns 'file not found' in basic mode.

        Trims the station's track list to the last known-good count so future
        _get_track_count() calls return the correct value, then restarts playback.
        In shuffle mode, ``shuffle_tracks`` must be pruned of entries past the
        corrected per-folder max or recovery can loop.
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
                prev_count = self._basic_playlist_track_count(pl)
                if actual_count < prev_count:
                    pl["tracks"] = tracks[:actual_count]
                    pl["track_count"] = actual_count
                    if hasattr(self.hw, "_known_tracks"):
                        self.hw._known_tracks[folder] = actual_count
                    self.known_tracks[folder] = actual_count
                    self.hw.log(
                        f"BASIC: Station folder {folder} corrected to {actual_count} tracks"
                    )
                break

            # Shuffle mode keeps separate order state; trimming ``playlists`` does
            # not automatically remove references to missing files from that state.
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
                if self._shuffle_entry_count() <= 0:
                    self.hw.log("BASIC: No shuffle tracks left after not-found recovery")
                    return
                n = self._shuffle_entry_count()
                self.shuffle_index = min(self.shuffle_index, n - 1)
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
                    source_name = "Shuffle"
            elif self._shuffle_source_type == 'album':
                if self.albums and self.current_album_index < len(self.albums):
                    source_name = self.albums[self.current_album_index].get('name', 'Album')
                else:
                    source_name = "Shuffle"
            elif self._shuffle_source_type == 'station':
                if self.playlists and self.current_album_index < len(self.playlists):
                    source_name = self.playlists[self.current_album_index].get('name', 'Station')
                else:
                    source_name = "Shuffle"
            else:
                source_name = "Shuffle"
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
            'station_cycle_shuffle_active': False,
        }

