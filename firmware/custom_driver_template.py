"""
Custom Hardware Driver Template for Vintage Radio
==================================================

This file is a ready-to-fill-in template for adding support
for a new audio module or microcontroller.  It works for
*any* hardware: DFPlayer Mini, I2S DACs, VS1053, PWM audio, etc.

QUICK START
-----------
1. Save a copy of this file (e.g. my_i2s_hardware.py).
2. Fill in each method below.  Remove the ``raise NotImplementedError``
   lines and replace them with your hardware code.
3. In the Vintage Radio GUI, open Pin Configuration and set your
   pin assignments for your board.
4. Under "Custom Hardware Driver", browse to your completed .py file.
5. Click "Install Firmware" -- the GUI handles everything else.
   It deploys the standard main.py, radio_core.py, your pin_config.json,
   and your driver file to the microcontroller automatically.

You do NOT need to write or modify main.py yourself.  The same
main.py is used for all drivers (DFPlayer and non-DFPlayer).  It
only calls the methods defined on HardwareInterface; DFPlayer-specific
behaviour is optional and only used when your driver provides it.

FOLDER/TRACK: The core always talks in "folder" and "track" numbers
(1-99, 1-999).  Your driver maps those to whatever your hardware
needs: DFPlayer commands, file paths like /01/001.mp3, I2S streams, etc.

Refer to docs/CUSTOM_DRIVER.md (also viewable from the GUI via
"View Driver Guide") for a full explanation of each method's
contract, expected return values, and edge cases.
"""

try:
    import ujson as json
except ImportError:
    import json

import os
import time

from radio_core import HardwareInterface


class CustomHardware(HardwareInterface):
    """Replace 'CustomHardware' with a name that describes your setup."""

    def __init__(self):
        """Initialise all hardware peripherals here.

        Typical work:
        - Configure GPIO pins (button, power sense, status LED).
        - Open serial / I2C / SPI buses for your audio module.
        - Set initial volume.
        - Load metadata from radio_metadata.json on your storage device.
        """
        # -- Example: read pin assignments from pin_config.json --
        # from pin_config_loader import load_pin_config, get_pin
        # cfg = load_pin_config()
        # self.button_pin = Pin(get_pin("button", 2), Pin.IN, Pin.PULL_UP)

        self._volume = 100
        self._playing = False

        self._albums = []
        self._playlists = []
        self._all_tracks = []

        self._delay_playback = False

        # Load your metadata once so get_albums()/get_playlists() work.
        self._load_metadata()

    # ------------------------------------------------------------------
    #  Playback
    # ------------------------------------------------------------------

    def play_track(self, folder, track, start_ms=0):
        """Start playing the given track.

        The core always passes folder (1-99) and track (1-999).  Map these
        to your hardware: e.g. DFPlayer UART command, file path /01/001.mp3
        for an I2S SD card, or whatever your module expects.  Use the
        metadata you loaded in __init__ if you need path or ID mapping.

        Args:
            folder:   Folder number (1-99).
            track:    Track number within folder (1-999).
            start_ms: Optional seek position in ms.

        Returns:
            True if playback started successfully.
        """
        if self._delay_playback:
            return True
        raise NotImplementedError("play_track")

    def stop(self):
        """Stop playback immediately."""
        raise NotImplementedError("stop")

    def set_volume(self, level):
        """Set the volume.

        ``level`` is 0-100.  Map it to whatever range your hardware
        supports (e.g. DFPlayer uses 0-30).
        """
        self._volume = level
        raise NotImplementedError("set_volume")

    def is_playing(self):
        """Return True if audio is currently playing.

        RadioCore polls this as a fallback when check_track_finished_uart()
        is not available.  Make sure it is responsive (< 10 ms).
        """
        raise NotImplementedError("is_playing")

    def get_playback_position_ms(self):
        """Return the current playback position in milliseconds.

        Return 0 if the hardware cannot report position.
        """
        return 0

    def check_track_finished_uart(self):
        """Return True once when a 'track finished' event is received.

        DFPlayer sends a UART 0x3D message when a track ends.
        If your module has a similar signal, consume and return True.

        If not, return False here and RadioCore will use BUSY-pin
        polling via is_playing() instead.
        """
        return False

    def play_am_overlay(self):
        """Play the AM radio 'tuning static' sound effect.

        This fires when the user changes modes or on power-on to
        give the vintage radio feel.  Implementations may:
        - Play a WAV via PWM on a dedicated GPIO.
        - Tell the audio module to play a specific file.
        - Do nothing (return immediately) if unsupported.
        """
        pass

    # ------------------------------------------------------------------
    #  State persistence
    # ------------------------------------------------------------------

    def save_state(self, state_dict):
        """Write the state dict to non-volatile storage.

        Typical implementation: write JSON to a file on the SD card
        or flash filesystem.

        state_dict always contains:
            mode (str) ............ "album" / "playlist" / "shuffle" / "radio"
            album_index (int) ..... current album/playlist index
            track (int) ........... current track number
            known_tracks (dict) ... {folder_id: max_track_seen}
        """
        try:
            with open("radio_state.json", "w") as f:
                json.dump(state_dict, f)
        except Exception as e:
            self.log(f"save_state failed: {e}")

    def load_state(self):
        """Load and return the previously saved state dict.

        Return None if no state file exists (first boot).
        """
        try:
            with open("radio_state.json", "r") as f:
                return json.load(f)
        except Exception:
            return None

    # ------------------------------------------------------------------
    #  Logging
    # ------------------------------------------------------------------

    def log(self, message):
        """Output a log message.  print() works for serial consoles."""
        print(message)

    # ------------------------------------------------------------------
    #  Metadata (albums, playlists, tracks)
    # ------------------------------------------------------------------

    def _load_metadata(self):
        """Load radio_metadata.json from storage.

        The file is generated by the GUI's SD Card Manager.
        Populate self._albums, self._playlists, self._all_tracks.
        """
        try:
            with open("radio_metadata.json", "r") as f:
                data = json.load(f)
        except Exception:
            self.log("No radio_metadata.json found")
            return

        songs = {str(s["id"]): s for s in data.get("songs", [])}

        for album in data.get("albums", []):
            tracks = []
            for ref in album.get("track_refs", []):
                song = songs.get(str(ref["song_id"]), {})
                tracks.append({
                    "id": ref["song_id"],
                    "title": song.get("title", "Unknown"),
                    "artist": song.get("artist", "Unknown"),
                    "duration": song.get("duration", 180),
                    "folder": ref.get("folder", 1),
                    "track_number": ref.get("track", 1),
                })
            self._albums.append({
                "id": album.get("id", 0),
                "name": album.get("name", "Untitled"),
                "tracks": tracks,
            })

        for pl in data.get("playlists", []):
            tracks = []
            for ref in pl.get("track_refs", []):
                song = songs.get(str(ref["song_id"]), {})
                tracks.append({
                    "id": ref["song_id"],
                    "title": song.get("title", "Unknown"),
                    "artist": song.get("artist", "Unknown"),
                    "duration": song.get("duration", 180),
                    "folder": ref.get("folder", 1),
                    "track_number": ref.get("track", 1),
                })
            self._playlists.append({
                "id": pl.get("id", 0),
                "name": pl.get("name", "Untitled"),
                "tracks": tracks,
            })

        all_ids_seen = set()
        for collection in self._albums + self._playlists:
            for t in collection["tracks"]:
                if t["id"] not in all_ids_seen:
                    all_ids_seen.add(t["id"])
                    self._all_tracks.append(t)

    def get_albums(self):
        return self._albums

    def get_playlists(self):
        return self._playlists

    def get_all_tracks(self):
        return self._all_tracks

    # ------------------------------------------------------------------
    #  GPIO / hardware inputs
    # ------------------------------------------------------------------

    def is_power_on(self):
        """Return True when the power-sense pin reads HIGH.

        The main loop polls this to detect the potentiometer
        being turned on/off.

        If your board doesn't have a power sense circuit, just
        return True so the firmware never enters the 'off' state.
        """
        return True  # <-- replace with your GPIO read

    def is_button_pressed(self):
        """Return True when the user button is held down.

        Most buttons are active-low with an internal pull-up,
        so: return self.button_pin.value() == 0
        """
        raise NotImplementedError("is_button_pressed")

    # ------------------------------------------------------------------
    #  Optional overrides
    # ------------------------------------------------------------------

    def set_delay_playback(self, delay):
        self._delay_playback = bool(delay)

    def set_current_track_hint(self, track):
        pass
