"""Tests for pure-logic helper functions in the GUI layer.

Covers:
- TestModeWidget._find_track_at_position: mapping a virtual time position to (track, offset)
- TestModeWidget._resolve_song_path: resolving sd_path vs file_path with existence checks
- TestModeWidget._current_song: multi-mode song retrieval
- TestModeWidget._current_track_count: track count per mode
- RadioStation dataclass from test_mode
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from unittest import mock

import pytest

from gui.test_mode import TestModeWidget, AlbumState, PlaylistState, RadioStation


# ---------------------------------------------------------------------------
# _find_track_at_position
# ---------------------------------------------------------------------------

class TestFindTrackAtPosition:
    """Tests for the virtual-position-to-track mapping used in radio mode."""

    def _call(self, tracks, position_ms):
        return TestModeWidget._find_track_at_position(None, tracks, position_ms)

    def test_first_track_start(self):
        tracks = [
            {"title": "A", "duration": 60.0},
            {"title": "B", "duration": 120.0},
        ]
        track, offset = self._call(tracks, 0)
        assert track["title"] == "A"
        assert offset == 0

    def test_first_track_middle(self):
        tracks = [
            {"title": "A", "duration": 60.0},
            {"title": "B", "duration": 120.0},
        ]
        track, offset = self._call(tracks, 30_000)
        assert track["title"] == "A"
        assert offset == 30_000

    def test_second_track(self):
        tracks = [
            {"title": "A", "duration": 60.0},
            {"title": "B", "duration": 120.0},
        ]
        track, offset = self._call(tracks, 70_000)
        assert track["title"] == "B"
        assert offset == 10_000

    def test_exact_boundary_lands_on_next(self):
        tracks = [
            {"title": "A", "duration": 60.0},
            {"title": "B", "duration": 120.0},
        ]
        track, offset = self._call(tracks, 60_000)
        assert track["title"] == "B"
        assert offset == 0

    def test_wraps_to_first_when_past_total(self):
        tracks = [
            {"title": "A", "duration": 60.0},
            {"title": "B", "duration": 60.0},
        ]
        track, offset = self._call(tracks, 200_000)
        assert track["title"] == "A"
        assert offset == 0

    def test_defaults_to_180s_when_duration_missing(self):
        tracks = [
            {"title": "A", "duration": None},
            {"title": "B", "duration": 60.0},
        ]
        track, offset = self._call(tracks, 100_000)
        assert track["title"] == "A"
        assert offset == 100_000

    def test_defaults_to_180s_when_duration_zero(self):
        tracks = [
            {"title": "A", "duration": 0},
            {"title": "B", "duration": 60.0},
        ]
        track, offset = self._call(tracks, 100_000)
        assert track["title"] == "A"
        assert offset == 100_000

    def test_empty_tracks_returns_none(self):
        track, offset = self._call([], 5000)
        assert track is None
        assert offset == 0

    def test_single_track(self):
        tracks = [{"title": "Solo", "duration": 300.0}]
        track, offset = self._call(tracks, 150_000)
        assert track["title"] == "Solo"
        assert offset == 150_000

    def test_three_tracks_third_one(self):
        tracks = [
            {"title": "A", "duration": 60.0},
            {"title": "B", "duration": 60.0},
            {"title": "C", "duration": 60.0},
        ]
        track, offset = self._call(tracks, 130_000)
        assert track["title"] == "C"
        assert offset == 10_000


# ---------------------------------------------------------------------------
# _resolve_song_path
# ---------------------------------------------------------------------------

class TestResolveSongPath:
    """Tests for resolving playback file path (sd_path preferred over file_path)."""

    def _call(self, song):
        return TestModeWidget._resolve_song_path(None, song)

    def test_prefers_sd_path_when_exists(self, tmp_path):
        sd = tmp_path / "sd.mp3"
        sd.write_bytes(b"\x00")
        fp = tmp_path / "lib.mp3"
        fp.write_bytes(b"\x00")

        result = self._call({"sd_path": str(sd), "file_path": str(fp)})
        assert result == str(sd)

    def test_falls_back_to_file_path(self, tmp_path):
        fp = tmp_path / "lib.mp3"
        fp.write_bytes(b"\x00")

        result = self._call({"sd_path": "/nonexistent/sd.mp3", "file_path": str(fp)})
        assert result == str(fp)

    def test_returns_none_when_neither_exists(self):
        result = self._call({"sd_path": "/nonexistent/sd.mp3", "file_path": "/nonexistent/lib.mp3"})
        assert result is None

    def test_returns_none_when_no_paths(self):
        result = self._call({})
        assert result is None

    def test_sd_path_none_falls_back_to_file_path(self, tmp_path):
        fp = tmp_path / "lib.mp3"
        fp.write_bytes(b"\x00")

        result = self._call({"sd_path": None, "file_path": str(fp)})
        assert result == str(fp)

    def test_returns_file_path_when_sd_path_empty_string(self, tmp_path):
        fp = tmp_path / "lib.mp3"
        fp.write_bytes(b"\x00")

        result = self._call({"sd_path": "", "file_path": str(fp)})
        assert result == str(fp)


# ---------------------------------------------------------------------------
# _current_song (using a mock widget with relevant state attributes)
# ---------------------------------------------------------------------------

def _make_mock_widget(
    mode="album",
    albums=None,
    playlists=None,
    shuffle_tracks=None,
    shuffle_index=0,
    current_album_index=0,
    current_track=1,
    radio_stations=None,
    radio_station_index=0,
):
    """Build a mock object with all the state attributes _current_song and friends need."""
    widget = mock.Mock(spec=[])
    widget.mode = mode
    widget.albums = albums or [AlbumState(album_id=1, name="Album 1", tracks=[
        {"id": 1, "title": "Track 1"},
        {"id": 2, "title": "Track 2"},
    ])]
    widget.playlists = playlists or [PlaylistState(playlist_id=1, name="Playlist 1", tracks=[
        {"id": 3, "title": "PL Track 1"},
    ])]
    widget.shuffle_tracks = shuffle_tracks or []
    widget.shuffle_index = shuffle_index
    widget.current_album_index = current_album_index
    widget.current_track = current_track
    widget.radio_stations = radio_stations or []
    widget.radio_station_index = radio_station_index

    widget.current_album = lambda: widget.albums[widget.current_album_index]
    widget.current_playlist = lambda: widget.playlists[min(widget.current_album_index, len(widget.playlists) - 1)]
    widget._track_count = lambda album: max(len(album.tracks), 1)

    return widget


class TestCurrentSong:
    """Tests for _current_song which retrieves the active track based on mode."""

    def test_album_mode_first_track(self):
        w = _make_mock_widget(mode="album", current_track=1)
        song = TestModeWidget._current_song(w)
        assert song["title"] == "Track 1"

    def test_album_mode_second_track(self):
        w = _make_mock_widget(mode="album", current_track=2)
        song = TestModeWidget._current_song(w)
        assert song["title"] == "Track 2"

    def test_album_mode_out_of_range(self):
        w = _make_mock_widget(mode="album", current_track=99)
        song = TestModeWidget._current_song(w)
        assert song is None

    def test_album_mode_empty_album(self):
        w = _make_mock_widget(
            mode="album",
            albums=[AlbumState(album_id=1, name="Empty", tracks=[])],
        )
        song = TestModeWidget._current_song(w)
        assert song is None

    def test_playlist_mode(self):
        w = _make_mock_widget(mode="playlist", current_track=1)
        song = TestModeWidget._current_song(w)
        assert song["title"] == "PL Track 1"

    def test_playlist_mode_out_of_range(self):
        w = _make_mock_widget(mode="playlist", current_track=10)
        song = TestModeWidget._current_song(w)
        assert song is None

    def test_shuffle_mode(self):
        tracks = [{"id": 10, "title": "Shuffle 1"}, {"id": 11, "title": "Shuffle 2"}]
        w = _make_mock_widget(mode="shuffle", shuffle_tracks=tracks, shuffle_index=1)
        song = TestModeWidget._current_song(w)
        assert song["title"] == "Shuffle 2"

    def test_shuffle_mode_empty(self):
        w = _make_mock_widget(mode="shuffle", shuffle_tracks=[], shuffle_index=0)
        song = TestModeWidget._current_song(w)
        assert song is None

    def test_shuffle_mode_index_clamped(self):
        tracks = [{"id": 10, "title": "Only"}]
        w = _make_mock_widget(mode="shuffle", shuffle_tracks=tracks, shuffle_index=99)
        song = TestModeWidget._current_song(w)
        assert song["title"] == "Only"

    def test_radio_mode(self):
        station = RadioStation(
            name="Station 1",
            tracks=[{"id": 20, "title": "Radio 1"}, {"id": 21, "title": "Radio 2"}],
            total_duration_ms=360_000,
            start_offset_ms=0,
        )
        w = _make_mock_widget(
            mode="radio", radio_stations=[station], radio_station_index=0, current_track=2,
        )
        song = TestModeWidget._current_song(w)
        assert song["title"] == "Radio 2"

    def test_radio_mode_no_stations(self):
        w = _make_mock_widget(mode="radio", radio_stations=[], radio_station_index=0)
        song = TestModeWidget._current_song(w)
        assert song is None

    def test_radio_mode_empty_station(self):
        station = RadioStation(name="Empty", tracks=[], total_duration_ms=0, start_offset_ms=0)
        w = _make_mock_widget(mode="radio", radio_stations=[station])
        song = TestModeWidget._current_song(w)
        assert song is None

    def test_radio_mode_track_out_of_range_wraps(self):
        station = RadioStation(
            name="S", tracks=[{"id": 1, "title": "T1"}],
            total_duration_ms=180_000, start_offset_ms=0,
        )
        w = _make_mock_widget(mode="radio", radio_stations=[station], current_track=99)
        song = TestModeWidget._current_song(w)
        assert song["title"] == "T1"


# ---------------------------------------------------------------------------
# _current_track_count
# ---------------------------------------------------------------------------

class TestCurrentTrackCount:
    """Tests for _current_track_count which returns the number of tracks for the active mode."""

    def test_album_mode(self):
        w = _make_mock_widget(mode="album")
        count = TestModeWidget._current_track_count(w)
        assert count == 2

    def test_playlist_mode(self):
        w = _make_mock_widget(mode="playlist")
        count = TestModeWidget._current_track_count(w)
        assert count == 1

    def test_shuffle_mode(self):
        tracks = [{"id": i} for i in range(5)]
        w = _make_mock_widget(mode="shuffle", shuffle_tracks=tracks)
        count = TestModeWidget._current_track_count(w)
        assert count == 5

    def test_shuffle_mode_empty(self):
        w = _make_mock_widget(mode="shuffle", shuffle_tracks=[])
        count = TestModeWidget._current_track_count(w)
        assert count == 1

    def test_album_mode_empty(self):
        w = _make_mock_widget(
            mode="album",
            albums=[AlbumState(album_id=1, name="Empty", tracks=[])],
        )
        count = TestModeWidget._current_track_count(w)
        assert count == 1


# ---------------------------------------------------------------------------
# RadioStation dataclass
# ---------------------------------------------------------------------------

class TestRadioStationDataclass:
    """Ensure the test_mode.RadioStation dataclass works as expected."""

    def test_create_station(self):
        s = RadioStation(
            name="My Station",
            tracks=[{"title": "T1"}],
            total_duration_ms=180_000,
            start_offset_ms=5000,
        )
        assert s.name == "My Station"
        assert len(s.tracks) == 1
        assert s.total_duration_ms == 180_000
        assert s.start_offset_ms == 5000

    def test_empty_station(self):
        s = RadioStation(name="Empty", tracks=[], total_duration_ms=0, start_offset_ms=0)
        assert s.tracks == []
        assert s.total_duration_ms == 0


# ---------------------------------------------------------------------------
# AlbumState / PlaylistState dataclasses
# ---------------------------------------------------------------------------

class TestAlbumPlaylistState:
    def test_album_state(self):
        a = AlbumState(album_id=5, name="Jazz", tracks=[{"title": "T"}])
        assert a.album_id == 5
        assert a.name == "Jazz"
        assert len(a.tracks) == 1

    def test_playlist_state(self):
        p = PlaylistState(playlist_id=10, name="Chill", tracks=[])
        assert p.playlist_id == 10
        assert p.name == "Chill"
        assert p.tracks == []
