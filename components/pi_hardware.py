"""
Raspberry Pi Hardware Interface.

Implements HardwareInterface from radio_core.py for Raspberry Pi 2W/3.
Uses VLC for playback (with seek), GPIO for button/power/BUSY, and the same
album_state.txt / radio_metadata.json format as the DFPlayer build.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from radio_core import HardwareInterface, FADE_IN_S

# Configurable paths (set before instantiating or via env)
MEDIA_ROOT = os.environ.get("VINTAGE_RADIO_MEDIA_ROOT", "/media/vintage")
VINTAGE_DIR = Path(MEDIA_ROOT) / "VintageRadio"
ALBUM_FILE = str(VINTAGE_DIR / "album_state.txt")
METADATA_FILE = str(VINTAGE_DIR / "radio_metadata.json")
WAV_FILE = str(VINTAGE_DIR / "AMradioSound.wav")

# GPIO pin numbers (BCM); match Pico layout where possible
PIN_BUTTON = 2
PIN_SENSE = 14   # power sense
PIN_BUSY = 15    # optional: can derive from VLC playing

try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    VLC_AVAILABLE = False

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False


def _resolve_sd_path(sd_path: Optional[str]) -> Optional[str]:
    """Convert metadata sd_path to local path using MEDIA_ROOT."""
    if not sd_path:
        return None
    p = Path(sd_path)
    if p.is_absolute() and "VintageRadio" in sd_path:
        parts = sd_path.split("VintageRadio", 1)
        if len(parts) == 2:
            rest = parts[1].lstrip("/\\")
            return str(Path(MEDIA_ROOT) / "VintageRadio" / rest)
    if not p.is_absolute():
        return str(Path(MEDIA_ROOT) / sd_path)
    return sd_path


class PiHardware(HardwareInterface):
    """
    Hardware implementation for Raspberry Pi: VLC playback, GPIO for
    button/power, same state/metadata files as DFPlayer build.
    """

    def __init__(self, media_root: Optional[str] = None) -> None:
        global MEDIA_ROOT, VINTAGE_DIR, ALBUM_FILE, METADATA_FILE, WAV_FILE
        if media_root is not None:
            MEDIA_ROOT = media_root
            VINTAGE_DIR = Path(MEDIA_ROOT) / "VintageRadio"
            ALBUM_FILE = str(VINTAGE_DIR / "album_state.txt")
            METADATA_FILE = str(VINTAGE_DIR / "radio_metadata.json")
            WAV_FILE = str(VINTAGE_DIR / "AMradioSound.wav")
        self._player: Optional[Any] = None
        self._instance: Optional[Any] = None
        self._volume = 100
        self._albums: List[Dict] = []
        self._playlists: List[Dict] = []
        self._known_tracks: Dict[int, int] = {}
        self._songs_sd_path: Dict[str, str] = {}
        self._folder_track_to_song: Dict[tuple, int] = {}
        self._am_overlay_active = False
        self._delay_playback = False
        self.ignore_busy_until = 0.0  # time.monotonic() until we ignore track-finished
        if VLC_AVAILABLE:
            self._instance = vlc.Instance("--no-xlib")
            self._player = self._instance.media_player_new()
        if GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(PIN_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(PIN_SENSE, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            if PIN_BUSY is not None:
                GPIO.setup(PIN_BUSY, GPIO.IN)
        self._load_metadata()

    def _load_metadata(self) -> None:
        try:
            with open(METADATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.log(f"No valid radio_metadata.json: {e}")
            return
        folders = data.get("folders", {})
        self._albums = []
        self._playlists = []
        self._folder_track_to_song = {}
        self._songs_sd_path = {}
        for song_id, song in data.get("songs", {}).items():
            sd_path = song.get("sd_path")
            if sd_path:
                self._songs_sd_path[song_id] = _resolve_sd_path(sd_path) or sd_path
        for folder_key, folder in folders.items():
            try:
                folder_id = int(folder_key)
            except (ValueError, TypeError):
                continue
            folder_type = folder.get("type", "album")
            name = folder.get("name", f"Folder {folder_id}")
            tracks_data = folder.get("tracks", [])
            tracks = []
            for idx, t in enumerate(tracks_data):
                song_id = t.get("song_id", idx + 1)
                track_num = t.get("track", idx + 1)
                self._folder_track_to_song[(folder_id, track_num)] = song_id
                track = {
                    "id": song_id,
                    "title": t.get("title", f"Track {idx + 1}"),
                    "artist": t.get("artist", "Unknown"),
                    "duration": t.get("duration", 180),
                    "folder": folder_id,
                    "track_number": track_num,
                }
                tracks.append(track)
            if tracks:
                self._known_tracks[folder_id] = len(tracks)
            entry = {"id": folder_id, "name": name, "tracks": tracks}
            if folder_type == "playlist":
                self._playlists.append(entry)
            else:
                self._albums.append(entry)
        self.log(f"Loaded metadata: {len(self._albums)} albums, {len(self._playlists)} playlists")

    def _path_for(self, folder: int, track: int) -> Optional[str]:
        song_id = self._folder_track_to_song.get((folder, track))
        if song_id is None:
            return None
        return self._songs_sd_path.get(str(song_id))

    def has_track(self, folder: int, track: int) -> bool:
        path = self._path_for(folder, track)
        return path is not None and os.path.isfile(path)

    def set_delay_playback(self, delay: bool) -> None:
        """When True, play_track() no-ops so firmware can run start_with_am() first."""
        self._delay_playback = bool(delay)

    def play_track(self, folder: int, track: int, start_ms: int = 0) -> bool:
        if self._am_overlay_active:
            return True
        if self._delay_playback:
            return True
        path = self._path_for(folder, track)
        if not path or not os.path.isfile(path):
            self.log(f"No file for folder={folder} track={track}")
            return False
        if not VLC_AVAILABLE or not self._player:
            self.log("VLC not available")
            return False
        self._player.stop()
        media = self._instance.media_new(path)
        self._player.set_media(media)
        if start_ms > 0:
            self._player.play()
            time.sleep(0.2)
            self._player.set_time(start_ms)
        else:
            self._player.play()
        self.ignore_busy_until = time.monotonic() + 2.0
        return True

    def stop(self) -> None:
        if self._player:
            self._player.stop()

    def set_volume(self, level: int) -> None:
        self._volume = max(0, min(100, level))
        if self._player:
            self._player.audio_set_volume(self._volume)

    def is_playing(self) -> bool:
        if self._player and VLC_AVAILABLE:
            state = self._player.get_state()
            return state in (vlc.State.Playing, vlc.State.Buffering)
        if GPIO_AVAILABLE and PIN_BUSY is not None:
            return GPIO.input(PIN_BUSY) == 0
        return False

    def get_playback_position_ms(self) -> int:
        if self._player and VLC_AVAILABLE:
            return self._player.get_time() or 0
        return 0

    def play_am_overlay(self) -> bool:
        if not os.path.isfile(WAV_FILE):
            self.log("No AM WAV file")
            return False
        if not VLC_AVAILABLE or not self._player:
            return False
        self._am_overlay_active = True
        self._player.stop()
        media = self._instance.media_new(WAV_FILE)
        self._player.set_media(media)
        self._player.play()
        dur_ms = 3000
        start = time.monotonic()
        while time.monotonic() - start < (dur_ms / 1000.0) + 1:
            if not self.is_playing():
                break
            time.sleep(0.05)
        self._am_overlay_active = False
        return True

    def save_state(self, state_dict: Dict) -> None:
        try:
            Path(ALBUM_FILE).parent.mkdir(parents=True, exist_ok=True)
            album_idx = state_dict.get("album_index", 0) + 1
            track = state_dict.get("track", 1)
            known = state_dict.get("known_tracks", {})
            track_str = ",".join(f"{a}:{c}" for a, c in sorted(known.items()))
            payload = f"{album_idx},{track};tracks={track_str}"
            with open(ALBUM_FILE, "w", encoding="utf-8") as f:
                f.write(payload)
        except Exception as e:
            self.log(f"State save error: {e}")

    def load_state(self) -> Optional[Dict]:
        self._load_metadata()
        state = {}
        try:
            with open(ALBUM_FILE, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except Exception:
            return {
                "mode": "album",
                "album_index": 0,
                "track": 1,
                "known_tracks": dict(self._known_tracks),
            }
        parts = raw.split(";")
        try:
            a_str, t_str = parts[0].split(",")
            album_idx = int(a_str) - 1
            track = int(t_str)
        except (ValueError, IndexError):
            return {
                "mode": "album",
                "album_index": 0,
                "track": 1,
                "known_tracks": dict(self._known_tracks),
            }
        known_tracks = {}
        if len(parts) > 1 and parts[1].startswith("tracks="):
            for pair in parts[1][7:].split(","):
                if not pair:
                    continue
                try:
                    a, c = pair.split(":")
                    known_tracks[int(a)] = int(c)
                except ValueError:
                    pass
        return {
            "mode": "album",
            "album_index": album_idx,
            "track": track,
            "known_tracks": known_tracks,
        }

    def log(self, message: str) -> None:
        print(message)

    def get_albums(self) -> List[Dict]:
        return self._albums

    def get_playlists(self) -> List[Dict]:
        return self._playlists

    def get_all_tracks(self) -> List[Dict]:
        out = []
        for album in self._albums:
            out.extend(album.get("tracks", []))
        return out

    def is_power_on(self) -> bool:
        if GPIO_AVAILABLE:
            return GPIO.input(PIN_SENSE) == 1
        return True

    def is_button_pressed(self) -> bool:
        if GPIO_AVAILABLE:
            return GPIO.input(PIN_BUTTON) == 0
        return False

    def reset_dfplayer(self) -> None:
        self.stop()

    def start_with_am(self, folder: int, track: int) -> bool:
        self.play_am_overlay()
        result = self.play_track(folder, track, 0)
        self._delay_playback = False
        return result
