"""Tests for RadioCore in basic_mode=True.

Basic mode skips metadata files; stations are discovered from the DFPlayer
folder structure. Album mode is not available. Feature flags are encoded in
folder-99 file counts. These tests validate behavior that is DIFFERENT from
the full (advanced) mode.
"""

from __future__ import annotations

import pytest

from radio_core import MODE_ALBUM, MODE_PLAYLIST, MODE_SHUFFLE, RadioCore
from tests.conftest import MockBasicHardware, _make_basic_stations


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestBasicModeInit:
    def test_starts_in_playlist_mode(self, basic_core):
        assert basic_core.mode == MODE_PLAYLIST

    def test_discovers_stations_as_playlists(self, basic_core):
        assert len(basic_core.playlists) == 2
        assert basic_core.playlists[0]["name"] == "Station 1"

    def test_albums_stay_empty(self, basic_core):
        assert basic_core.albums == []

    def test_empty_discovery_creates_placeholder(self):
        hw = MockBasicHardware(stations=[])
        hw.discover_stations = lambda: []
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        assert len(rc.playlists) >= 1  # placeholder "Empty" playlist created

    def test_known_tracks_populated_from_stations(self, basic_core):
        """discover_stations should populate hw._known_tracks."""
        assert len(basic_core.hw._known_tracks) > 0


# ---------------------------------------------------------------------------
# Feature flags (folder 99 file count)
# ---------------------------------------------------------------------------

class TestFeatureFlags:
    def _make_rc(self, count):
        hw = MockBasicHardware(folder_99_count=count)
        rc = RadioCore(hw, basic_mode=True)
        rc.albums = []
        rc.playlists = hw.discover_stations()
        rc._check_feature_flags()
        return rc

    def test_count_0_means_stop_at_end(self):
        rc = self._make_rc(0)
        assert rc.loop_stations is False
        assert rc.advance_next_station is False

    def test_count_1_means_stop_at_end(self):
        rc = self._make_rc(1)
        assert rc.loop_stations is False
        assert rc.advance_next_station is False

    def test_count_2_means_loop(self):
        rc = self._make_rc(2)
        assert rc.loop_stations is True
        assert rc.advance_next_station is False

    def test_count_3_means_advance(self):
        rc = self._make_rc(3)
        assert rc.loop_stations is False
        assert rc.advance_next_station is True

    def test_count_5_means_advance(self):
        rc = self._make_rc(5)
        assert rc.advance_next_station is True

    def test_count_none_keeps_defaults(self):
        hw = MockBasicHardware()
        hw.query_files_in_folder_consensus = lambda *a, **kw: None
        hw.query_files_in_folder = lambda *a, **kw: None
        rc = RadioCore(hw, basic_mode=True)
        rc.albums = []
        rc.playlists = hw.discover_stations()
        default_advance = rc.advance_next_station
        rc._check_feature_flags()
        # Should remain unchanged (defaults preserved when query fails)
        assert rc.advance_next_station == default_advance


# ---------------------------------------------------------------------------
# Mode switching in basic mode
# ---------------------------------------------------------------------------

class TestBasicModeSwitching:
    def test_one_tap_hold_from_playlist_is_noop(self, basic_core):
        assert basic_core.mode == MODE_PLAYLIST
        basic_core._pending_long_press = True
        basic_core.tap_count = 1
        basic_core._resolve_input()
        # In basic mode, 1-tap+hold only exits shuffle back to playlist.
        assert basic_core.mode == MODE_PLAYLIST

    def test_one_tap_hold_from_shuffle_exits_to_playlist(self, basic_core):
        basic_core._init_current_shuffle()
        assert basic_core.mode == MODE_SHUFFLE
        basic_core._pending_long_press = True
        basic_core.tap_count = 1
        basic_core._resolve_input()
        assert basic_core.mode == MODE_PLAYLIST

    def test_album_mode_never_reachable_via_switch(self, basic_core):
        """switch_mode(MODE_ALBUM) must be rejected in basic mode."""
        basic_core.switch_mode(MODE_ALBUM)
        assert basic_core.mode != MODE_ALBUM

    def test_switch_to_same_mode_is_noop(self, basic_core, mock_basic_hardware):
        mock_basic_hardware.calls.clear()
        basic_core.switch_mode(MODE_PLAYLIST)
        assert not any(c[0] == "stop" for c in mock_basic_hardware.calls)


# ---------------------------------------------------------------------------
# Auto-advance at end of station
# ---------------------------------------------------------------------------

class TestBasicAutoAdvance:
    def _core_with_flags(self, loop, advance):
        stations = [
            {"id": 1, "name": "S1", "tracks": [
                {"id": 1, "title": "a", "folder": 1, "track_number": 1, "duration": 60.0}
            ]},
            {"id": 2, "name": "S2", "tracks": [
                {"id": 2, "title": "b", "folder": 2, "track_number": 1, "duration": 60.0}
            ]},
        ]
        hw = MockBasicHardware(stations=stations)
        rc = RadioCore(hw, basic_mode=True)
        rc.albums = []
        rc.playlists = list(stations)
        rc.mode = MODE_PLAYLIST
        rc.current_album_index = 0
        rc.current_track = 1
        rc.power_on = True
        rc.is_playing = True
        rc.loop_stations = loop
        rc.advance_next_station = advance
        return rc, hw

    def test_advance_true_moves_to_next_station(self):
        rc, hw = self._core_with_flags(loop=False, advance=True)
        rc.on_track_finished()
        assert rc.current_album_index == 1
        assert rc.current_track == 1
        assert any(c[0] == "play_track" for c in hw.calls)

    def test_advance_false_stops_at_end(self):
        rc, hw = self._core_with_flags(loop=False, advance=False)
        rc.on_track_finished()
        # Should stop, not advance
        assert not any(c[0] == "play_track" for c in hw.calls)

    def test_loop_true_wraps_to_first_station(self):
        stations = [
            {"id": 1, "name": "S1", "tracks": [
                {"id": 1, "title": "a", "folder": 1, "track_number": 1, "duration": 60.0}
            ]},
        ]
        hw = MockBasicHardware(stations=stations)
        rc = RadioCore(hw, basic_mode=True)
        rc.albums = []
        rc.playlists = list(stations)
        rc.mode = MODE_PLAYLIST
        rc.current_album_index = 0
        rc.current_track = 1
        rc.power_on = True
        rc.is_playing = True
        rc.loop_stations = True
        rc.advance_next_station = False
        rc.on_track_finished()
        # With loop and single station: should replay station 0
        assert rc.current_album_index == 0

    def test_last_station_with_advance_wraps_to_first(self):
        stations = [
            {"id": 1, "name": "S1", "tracks": [
                {"id": 1, "title": "a", "folder": 1, "track_number": 1, "duration": 60.0}
            ]},
            {"id": 2, "name": "S2", "tracks": [
                {"id": 2, "title": "b", "folder": 2, "track_number": 1, "duration": 60.0}
            ]},
        ]
        hw = MockBasicHardware(stations=stations)
        rc = RadioCore(hw, basic_mode=True)
        rc.albums = []
        rc.playlists = list(stations)
        rc.mode = MODE_PLAYLIST
        rc.current_album_index = 1  # last station
        rc.current_track = 1
        rc.power_on = True
        rc.is_playing = True
        rc.loop_stations = False
        rc.advance_next_station = True
        rc.on_track_finished()
        assert rc.current_album_index == 0  # wraps


# ---------------------------------------------------------------------------
# Error recovery: file-not-found (0x06)
# ---------------------------------------------------------------------------

class TestBasicFileNotFoundRecovery:
    def _core_with_station(self, num_tracks=3):
        tracks = [
            {"id": i, "title": f"T{i}", "folder": 1, "track_number": i, "duration": 60.0}
            for i in range(1, num_tracks + 1)
        ]
        stations = [{"id": 1, "name": "S1", "tracks": tracks}]
        hw = MockBasicHardware(stations=stations)
        rc = RadioCore(hw, basic_mode=True)
        rc.albums = []
        rc.playlists = list(stations)
        rc.mode = MODE_PLAYLIST
        rc.current_album_index = 0
        rc.current_track = 1
        rc.power_on = True
        rc.is_playing = True
        rc.advance_next_station = False
        rc.loop_stations = False
        return rc, hw

    def test_trims_station_to_tracks_before_failure(self):
        rc, hw = self._core_with_station(num_tracks=5)
        rc._handle_basic_track_not_found(folder=1, failed_track_num=4)
        # Station should be trimmed to 3 tracks (tracks 1-3)
        assert len(rc.playlists[0]["tracks"]) == 3

    def test_trim_to_zero_tracks_does_not_crash(self):
        rc, hw = self._core_with_station(num_tracks=2)
        try:
            rc._handle_basic_track_not_found(folder=1, failed_track_num=1)
        except Exception as exc:
            pytest.fail(f"_handle_basic_track_not_found raised: {exc}")

    def test_shuffle_tracks_pruned_after_trim(self):
        rc, hw = self._core_with_station(num_tracks=4)
        # Simulate being in shuffle with some tracks from this station
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.shuffle_tracks = list(rc.playlists[0]["tracks"])
        rc.shuffle_index = 0
        rc._handle_basic_track_not_found(folder=1, failed_track_num=3)
        # Shuffle tracks should not contain the trimmed-off tracks
        for t in rc.shuffle_tracks:
            assert t.get("track_number", 0) < 3

    def test_recursion_guard_prevents_infinite_loop(self):
        """Recursion depth guard should stop at depth 8 without infinite recursion."""
        rc, hw = self._core_with_station(num_tracks=1)
        # Call repeatedly - should terminate gracefully
        for _ in range(10):
            try:
                rc._handle_basic_track_not_found(folder=1, failed_track_num=1)
            except RecursionError:
                pytest.fail("Recursion guard failed - RecursionError raised")
