"""
BACKUP OF WORKING TEST MODE METHODS
====================================
This file contains the key working methods from test_mode.py BEFORE full RadioCore integration.
Use as reference when fixing RadioCore integration issues.

Key working methods:
- _advance_next: Handles track advancement for all modes
- _start_playback_for_current: Starts playback using pygame
- _start_playback: Core pygame playback with fade-in
- _init_radio_stations: Creates radio stations from albums/playlists
- _select_radio_station: Tunes to a station based on dial position
- _find_track_at_position: Finds track at virtual time position
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import random
import time

# Constants
FADE_IN_S = 2.4
WAV_FILE = "AMradioSound.wav"


@dataclass
class RadioStation:
    """A radio station with a name, tracks, and virtual time positioning."""
    name: str
    tracks: List[Dict]
    total_duration_ms: int
    start_offset_ms: int


# =============================================================================
# WORKING ADVANCE NEXT METHOD
# =============================================================================

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


# =============================================================================
# WORKING PLAYBACK METHODS
# =============================================================================

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


def _start_playback_for_song(self, song: Dict, *, offset_ms: Optional[int] = None, with_am_overlay: bool = False) -> None:
    path = self._resolve_song_path(song)
    if path is None:
        self._log("Track file not found.")
        return
    self._start_playback(path, start_ms=offset_ms, with_am_overlay=with_am_overlay)


# =============================================================================
# WORKING RADIO METHODS
# =============================================================================

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


# =============================================================================
# WORKING SHUFFLE INITIALIZATION (from refresh_from_db)
# =============================================================================

def _init_shuffle_from_db(self, db):
    """Initialize shuffle tracks from database."""
    self.shuffle_tracks = [dict(track) for track in db.list_songs()]
    random.shuffle(self.shuffle_tracks)
    self.shuffle_index = 0


# =============================================================================
# WORKING _current_song METHOD
# =============================================================================

def _current_song(self) -> Optional[Dict]:
    if self.mode == "radio":
        station = self._get_current_radio_station()
        if station and station.tracks:
            idx = min(self.current_track - 1, len(station.tracks) - 1)
            return station.tracks[idx]
        return None
    if self.mode == "shuffle":
        if not self.shuffle_tracks:
            return None
        idx = min(self.shuffle_index, len(self.shuffle_tracks) - 1)
        return self.shuffle_tracks[idx]
    if self.mode == "playlist":
        pl = self.current_playlist()
        if not pl.tracks:
            return None
        idx = min(self.current_track - 1, len(pl.tracks) - 1)
        return pl.tracks[idx]
    # Album mode
    album = self.current_album()
    if not album.tracks:
        return None
    idx = min(self.current_track - 1, len(album.tracks) - 1)
    return album.tracks[idx]


def _get_current_radio_station(self):
    """Get the current radio station."""
    if self.radio_stations and self.radio_station_index < len(self.radio_stations):
        return self.radio_stations[self.radio_station_index]
    return None

