"""Shared fixtures for Vintage Radio tests."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from gui.database import DatabaseManager
from radio_core import HardwareInterface, RadioCore, MODE_PLAYLIST


def pytest_runtest_setup(item):
    """Print once per test so the IDE has output to show (avoids 'no output' message)."""
    print(f"[{item.nodeid}]", flush=True)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Add a report section for every test so the IDE has per-test output to display."""
    outcome = yield
    report = outcome.get_result() if hasattr(outcome, "get_result") else outcome
    if getattr(report, "when", None) == "call":
        if not hasattr(report, "sections"):
            report.sections = []
        report.sections.append(("Output", f"Ran: {item.nodeid}"))
    return report


@pytest.fixture
def tmp_db(tmp_path):
    """DatabaseManager backed by a temporary SQLite file."""
    db = DatabaseManager(
        db_path=tmp_path / "test.db",
        backups_dir=tmp_path / "backups",
    )
    yield db
    db.close()


@pytest.fixture
def sample_songs():
    """Metadata dicts for three test songs (no real audio files)."""
    return [
        {
            "original_filename": "track_a.mp3",
            "file_path": "/fake/track_a.mp3",
            "title": "Song A",
            "artist": "Artist 1",
            "duration": 200.0,
            "file_hash": "aaa111",
            "file_size": 5000,
            "format": "mp3",
        },
        {
            "original_filename": "track_b.mp3",
            "file_path": "/fake/track_b.mp3",
            "title": "Song B",
            "artist": "Artist 2",
            "duration": 180.0,
            "file_hash": "bbb222",
            "file_size": 4500,
            "format": "mp3",
        },
        {
            "original_filename": "track_c.flac",
            "file_path": "/fake/track_c.flac",
            "title": "Song C",
            "artist": "Artist 1",
            "duration": 240.0,
            "file_hash": "ccc333",
            "file_size": 12000,
            "format": "flac",
        },
    ]


@pytest.fixture
def populated_db(tmp_db, sample_songs):
    """DB pre-populated with songs, an album, and a playlist."""
    ids = []
    for s in sample_songs:
        sid = tmp_db.add_song(**s)
        ids.append(sid)

    album_id = tmp_db.create_album("Test Album")
    for order, sid in enumerate(ids, start=1):
        tmp_db.add_song_to_album(album_id, sid, order)

    playlist_id = tmp_db.create_playlist("Test Playlist")
    for order, sid in enumerate(ids[:2], start=1):
        tmp_db.add_song_to_playlist(playlist_id, sid, order)

    return tmp_db, ids, album_id, playlist_id


def _make_minimal_mp3(path: Path) -> Path:
    """Write a tiny but valid MP3 file (MPEG frame header + silence)."""
    # MPEG1 Layer3 128kbps 44100Hz stereo frame header
    frame_header = b"\xff\xfb\x90\x00"
    # Pad to a full frame (417 bytes for 128kbps); 10 frames needed for mutagen
    frame = frame_header + b"\x00" * 413
    path.write_bytes(frame * 10)
    return path


@pytest.fixture
def sample_audio_file(tmp_path):
    """Create a minimal MP3 file and return its path."""
    return _make_minimal_mp3(tmp_path / "test_song.mp3")


@pytest.fixture
def sample_audio_files(tmp_path):
    """Create three minimal MP3 files and return their paths."""
    paths = []
    for name in ("track_a.mp3", "track_b.mp3", "track_c.mp3"):
        paths.append(_make_minimal_mp3(tmp_path / name))
    return paths


class MockHardwareInterface(HardwareInterface):
    """Records calls for testing RadioCore without real hardware."""

    def __init__(self, albums=None, playlists=None, all_tracks=None):
        self.calls: List[tuple] = []
        self.logs: List[str] = []
        self._albums = albums or []
        self._playlists = playlists or []
        self._all_tracks = all_tracks
        self._state: Optional[Dict] = None
        self._playing = False
        self._volume = 100
        self._position_ms = 0
        self._delay_playback = False

    def play_track(self, folder, track, start_ms=0, folder_wrap=False):
        self.calls.append(("play_track", folder, track, start_ms, folder_wrap))
        self._playing = True
        return True

    def stop(self):
        self.calls.append(("stop",))
        self._playing = False

    def set_volume(self, level):
        self.calls.append(("set_volume", level))
        self._volume = level

    def is_playing(self):
        return self._playing

    def get_playback_position_ms(self):
        return self._position_ms

    def play_am_overlay(self):
        self.calls.append(("play_am_overlay",))

    def save_state(self, state_dict):
        self.calls.append(("save_state", dict(state_dict)))
        self._state = dict(state_dict)

    def load_state(self):
        return self._state

    def log(self, message):
        self.logs.append(message)

    def get_albums(self):
        return self._albums

    def get_playlists(self):
        return self._playlists

    def get_all_tracks(self):
        if self._all_tracks is not None:
            return self._all_tracks
        tracks = []
        for a in self._albums:
            tracks.extend(a.get("tracks", []))
        return tracks

    def discover_stations(self):
        return []

    def set_delay_playback(self, delay):
        self._delay_playback = delay

    def set_current_track_hint(self, track_dict):
        pass


def _make_test_albums():
    """Three albums with 3 tracks each, durations in seconds."""
    albums = []
    track_id = 1
    for album_num in range(1, 4):
        tracks = []
        for t in range(1, 4):
            tracks.append({
                "id": track_id,
                "title": f"Album{album_num} Track{t}",
                "artist": f"Artist {album_num}",
                "duration": 180.0 + t * 10,
                "folder": album_num,
                "track_number": t,
            })
            track_id += 1
        albums.append({"id": album_num, "name": f"Album {album_num}", "tracks": tracks})
    return albums


def _make_test_playlists():
    """One playlist with 4 tracks."""
    return [
        {
            "id": 100,
            "name": "My Playlist",
            "tracks": [
                {"id": 50, "title": "PL Track 1", "artist": "PL Artist", "duration": 200.0, "folder": 1, "track_number": 1},
                {"id": 51, "title": "PL Track 2", "artist": "PL Artist", "duration": 210.0, "folder": 1, "track_number": 2},
                {"id": 52, "title": "PL Track 3", "artist": "PL Artist", "duration": 190.0, "folder": 2, "track_number": 1},
                {"id": 53, "title": "PL Track 4", "artist": "PL Artist", "duration": 220.0, "folder": 2, "track_number": 2},
            ],
        }
    ]


@pytest.fixture
def mock_hardware():
    """MockHardwareInterface loaded with test albums and playlists."""
    return MockHardwareInterface(
        albums=_make_test_albums(),
        playlists=_make_test_playlists(),
    )


@pytest.fixture
def core(mock_hardware):
    """RadioCore initialized with mock hardware (skip playback so tests control state)."""
    rc = RadioCore(mock_hardware)
    rc.init(skip_initial_playback=True)
    return rc


# ---------------------------------------------------------------------------
# Basic-mode fixtures
# ---------------------------------------------------------------------------

def _make_basic_stations():
    """Two stations with 3 tracks each for basic-mode tests."""
    stations = []
    for folder in range(1, 3):
        tracks = []
        for track_num in range(1, 4):
            tracks.append({
                "id": (folder - 1) * 3 + track_num,
                "title": f"Station{folder} Track{track_num}",
                "artist": f"Artist {folder}",
                "duration": 120.0 + track_num * 10,
                "folder": folder,
                "track_number": track_num,
            })
        stations.append({"id": folder, "name": f"Station {folder}", "tracks": tracks})
    return stations


class MockBasicHardware(MockHardwareInterface):
    """MockHardwareInterface for basic mode: has discover_stations, query_files_in_folder."""

    def __init__(self, stations=None, folder_99_count=3):
        super().__init__(albums=[], playlists=[])
        self._stations = stations if stations is not None else _make_basic_stations()
        self._folder_99_count = folder_99_count
        self._known_tracks = {}

    def discover_stations(self):
        # Populate _known_tracks from stations as firmware would
        for station in self._stations:
            folder = station["tracks"][0]["folder"] if station["tracks"] else 1
            self._known_tracks[folder] = len(station["tracks"])
        return list(self._stations)

    def query_files_in_folder(self, folder_num, suppress_errors=False, timeout_ms=500):
        if folder_num == 99:
            return self._folder_99_count
        for station in self._stations:
            if station["tracks"] and station["tracks"][0]["folder"] == folder_num:
                return len(station["tracks"])
        return 0

    def query_files_in_folder_consensus(self, folder_num, suppress_errors=False):
        return self.query_files_in_folder(folder_num, suppress_errors)


@pytest.fixture
def mock_basic_hardware():
    """MockBasicHardware with 2 stations, folder 99 count=3 (advance mode)."""
    return MockBasicHardware()


@pytest.fixture
def basic_core(mock_basic_hardware):
    """RadioCore in basic_mode, initialized with skip_initial_playback."""
    rc = RadioCore(mock_basic_hardware, basic_mode=True)
    rc.init(skip_initial_playback=True)
    return rc


# ---------------------------------------------------------------------------
# DFPlayer protocol helpers (pure-Python, no hardware)
# ---------------------------------------------------------------------------

def build_dfplayer_packet(cmd, p1=0, p2=0, feedback=False):
    """Build a 10-byte DFPlayer command packet (matches firmware _df_send logic)."""
    fb = 0x01 if feedback else 0x00
    body = bytes([0xFF, 0x06, cmd, fb, p1 & 0xFF, p2 & 0xFF])
    csum = (-sum(body)) & 0xFFFF
    return bytes([0x7E]) + body + bytes([(csum >> 8) & 0xFF, csum & 0xFF, 0xEF])


def build_dfplayer_response(cmd, p1=0, p2=0):
    """Build a 10-byte DFPlayer response packet (module → Pico)."""
    return build_dfplayer_packet(cmd, p1, p2, feedback=False)


@pytest.fixture
def make_dfplayer_packet():
    """Fixture exposing build_dfplayer_packet helper."""
    return build_dfplayer_packet


@pytest.fixture
def make_dfplayer_response():
    """Fixture exposing build_dfplayer_response helper."""
    return build_dfplayer_response


# ---------------------------------------------------------------------------
# Minimal WAV builder
# ---------------------------------------------------------------------------

def make_minimal_wav_u8(num_samples=64, sample_rate=8000):
    """Return bytes of a valid 8-bit PCM WAV file."""
    data = bytes([128] * num_samples)  # silence at mid-level
    data_chunk = b"data" + struct.pack("<I", len(data)) + data
    fmt_chunk = (
        b"fmt "
        + struct.pack("<I", 16)       # chunk size
        + struct.pack("<H", 1)        # PCM
        + struct.pack("<H", 1)        # mono
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", sample_rate)  # byte rate
        + struct.pack("<H", 1)        # block align
        + struct.pack("<H", 8)        # bits per sample
    )
    riff_body = b"WAVE" + fmt_chunk + data_chunk
    return b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body


@pytest.fixture
def minimal_wav_path(tmp_path):
    """Write a minimal 8-bit mono WAV to a temp file and return its Path."""
    p = tmp_path / "test.wav"
    p.write_bytes(make_minimal_wav_u8())
    return p
