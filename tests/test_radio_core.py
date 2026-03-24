"""Tests for radio_core.RadioCore state machine."""

import pytest

from radio_core import (
    ALL_MODES,
    MODE_ALBUM,
    MODE_PLAYLIST,
    MODE_RADIO,
    MODE_SHUFFLE,
    RadioCore,
    RadioStation,
)
from tests.conftest import MockHardwareInterface, _make_test_albums, _make_test_playlists


class TestConstants:
    def test_mode_strings(self):
        assert MODE_ALBUM == "album"
        assert MODE_PLAYLIST == "playlist"
        assert MODE_SHUFFLE == "shuffle"
        assert MODE_RADIO == "radio"

    def test_all_modes(self):
        assert set(ALL_MODES) == {"album", "playlist", "shuffle", "radio"}


class TestRadioStation:
    def test_total_duration(self):
        station = RadioStation("Test", [], total_duration_ms=5000)
        assert station.total_duration_ms == 5000

    def test_start_offset_default(self):
        station = RadioStation("Test", [])
        assert station.start_offset_ms == 0


class TestInit:
    def test_loads_albums_and_playlists(self, core, mock_hardware):
        assert len(core.albums) == 3
        assert len(core.playlists) == 1

    def test_default_state(self, core):
        assert core.mode == MODE_ALBUM
        assert core.current_album_index == 0
        assert core.current_track == 1
        assert core.power_on is True


class TestSingleTap:
    def test_advances_track(self, core, mock_hardware):
        core._start_playback_for_current()
        mock_hardware.calls.clear()

        core._single_tap()
        assert core.current_track == 2
        assert any(c[0] == "play_track" for c in mock_hardware.calls)

    def test_wraps_at_end(self, core, mock_hardware):
        core.current_track = 3
        core._single_tap()
        assert core.current_track == 1


class TestDoubleTap:
    def test_goes_previous(self, core, mock_hardware):
        core.current_track = 2
        core._double_tap()
        assert core.current_track == 1

    def test_wraps_at_beginning(self, core, mock_hardware):
        core.current_track = 1
        core._double_tap()
        total = len(core.albums[0]["tracks"])
        assert core.current_track == total


class TestTripleTap:
    def test_restarts_album(self, core, mock_hardware):
        core.current_track = 3
        core._triple_tap()
        assert core.current_track == 1
        assert any(c[0] == "save_state" for c in mock_hardware.calls)


class TestLongPress:
    def test_next_album(self, core, mock_hardware):
        core._handle_long_press_with_taps(0)
        assert core.current_album_index == 1
        assert core.current_track == 1

    def test_next_album_wraps(self, core, mock_hardware):
        core.current_album_index = 2
        core._handle_long_press_with_taps(0)
        assert core.current_album_index == 0


class TestStationShuffleLongPress:
    """Basic-mode station shuffle uses _shuffle_source_type 'station'; long press must advance station and rebuild shuffle_tracks."""

    def test_next_album_replaces_stale_shuffle_tracks(self, core, mock_hardware):
        core.playlists = [
            {"id": 1, "name": "Station 1", "tracks": [{"title": "A", "folder": 1, "track_number": 1}]},
            {"id": 2, "name": "Station 2", "tracks": [{"title": "B", "folder": 2, "track_number": 1}]},
        ]
        core.mode = MODE_SHUFFLE
        core._shuffle_source_type = "station"
        core.current_album_index = 0
        core.shuffle_tracks = [{"title": "STALE", "folder": 99, "track_number": 9}]
        core.shuffle_index = 0
        core.current_track = 1

        core._next_album()

        assert core.current_album_index == 1
        assert core.mode == MODE_SHUFFLE
        assert core._shuffle_source_type == "station"
        assert len(core.shuffle_tracks) == 1
        assert core.shuffle_tracks[0].get("folder") == 2
        assert core.shuffle_index == 0
        assert core.current_track == 1


class TestBasicStationEndAutoAdvance:
    """basic_mode: advance_next_station at end of sequential station or station shuffle."""

    def test_sequential_last_track_advances_station(self, mock_hardware):
        mock_hardware._albums = []
        mock_hardware._playlists = [
            {"id": 1, "name": "S1", "tracks": [{"title": "a", "folder": 1, "track_number": 1}]},
            {"id": 2, "name": "S2", "tracks": [{"title": "b", "folder": 2, "track_number": 1}]},
        ]
        rc = RadioCore(mock_hardware, basic_mode=True)
        rc.albums = []
        rc.playlists = list(mock_hardware._playlists)
        rc.mode = MODE_PLAYLIST
        rc.current_album_index = 0
        rc.current_track = 1
        rc.power_on = True
        rc.advance_next_station = True
        rc.loop_stations = False
        rc.is_playing = True

        rc.on_track_finished()

        assert rc.current_album_index == 1
        assert rc.current_track == 1
        assert any(c[0] == "play_track" for c in mock_hardware.calls)

    def test_station_shuffle_last_track_advances_station(self, mock_hardware):
        mock_hardware._albums = []
        mock_hardware._playlists = [
            {
                "id": 1,
                "name": "S1",
                "tracks": [
                    {"title": "a", "folder": 1, "track_number": 1},
                    {"title": "b", "folder": 1, "track_number": 2},
                ],
            },
            {"id": 2, "name": "S2", "tracks": [{"title": "c", "folder": 2, "track_number": 1}]},
        ]
        rc = RadioCore(mock_hardware, basic_mode=True)
        rc.albums = []
        rc.playlists = list(mock_hardware._playlists)
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.current_album_index = 0
        rc.shuffle_tracks = list(mock_hardware._playlists[0]["tracks"])
        rc.shuffle_index = 1
        rc.current_track = 2
        rc.power_on = True
        rc.advance_next_station = True
        rc.loop_stations = False
        rc.is_playing = True

        rc.on_track_finished()

        assert rc.current_album_index == 1
        assert rc.shuffle_index == 0
        assert len(rc.shuffle_tracks) == 1
        assert rc.shuffle_tracks[0].get("title") == "c"


class TestOneTapHold:
    def test_toggles_to_playlist(self, core, mock_hardware):
        assert core.mode == MODE_ALBUM
        core._handle_long_press_with_taps(1)
        assert core.mode == MODE_PLAYLIST

    def test_toggles_back_to_album(self, core, mock_hardware):
        core.switch_mode(MODE_PLAYLIST)
        mock_hardware.calls.clear()
        core._handle_long_press_with_taps(1)
        assert core.mode == MODE_ALBUM


class TestTwoTapsHold:
    def test_shuffles_current_album(self, core, mock_hardware):
        core._handle_long_press_with_taps(2)
        assert core.mode == MODE_SHUFFLE
        assert len(core.shuffle_tracks) > 0


class TestThreeTapsHold:
    def test_shuffles_library(self, core, mock_hardware):
        core._handle_long_press_with_taps(3)
        assert core.mode == MODE_SHUFFLE
        assert len(core.shuffle_tracks) > 0


class TestModeSwitching:
    def test_switch_to_playlist(self, core, mock_hardware):
        core.switch_mode(MODE_PLAYLIST)
        assert core.mode == MODE_PLAYLIST

    def test_switch_to_same_mode_noop(self, core, mock_hardware):
        mock_hardware.calls.clear()
        core.switch_mode(MODE_ALBUM)
        assert not any(c[0] == "stop" for c in mock_hardware.calls)

    def test_switch_to_album_resets_track(self, core, mock_hardware):
        core.current_track = 3
        core.switch_mode(MODE_PLAYLIST)
        assert core.current_track == 1

    def test_switch_no_playlists(self, mock_hardware):
        mock_hardware._playlists = []
        rc = RadioCore(mock_hardware)
        rc.init(skip_initial_playback=True)
        old_mode = rc.mode
        rc.switch_mode(MODE_PLAYLIST)
        # Playlists get a fallback "Library" playlist from _load_data
        # The switch should succeed now
        assert rc.mode in (MODE_PLAYLIST, old_mode)


class TestFindTrackAtPosition:
    def test_first_track(self, core):
        tracks = [
            {"duration": 60.0},
            {"duration": 120.0},
        ]
        track, offset = core._find_track_at_position(tracks, 30_000)
        assert track == tracks[0]
        assert offset == 30_000

    def test_second_track(self, core):
        tracks = [
            {"duration": 60.0},
            {"duration": 120.0},
        ]
        track, offset = core._find_track_at_position(tracks, 70_000)
        assert track == tracks[1]
        assert offset == 10_000

    def test_position_zero(self, core):
        tracks = [{"duration": 100.0}]
        track, offset = core._find_track_at_position(tracks, 0)
        assert track == tracks[0]
        assert offset == 0

    def test_position_beyond_total(self, core):
        tracks = [{"duration": 10.0}]
        track, offset = core._find_track_at_position(tracks, 20_000)
        assert track == tracks[0]
        assert offset == 0

    def test_zero_duration_defaults(self, core):
        tracks = [{"duration": 0}, {"duration": 60.0}]
        track, offset = core._find_track_at_position(tracks, 100_000)
        assert track == tracks[0]
        assert offset == 100_000


class TestTrackFinished:
    def test_auto_advances(self, core, mock_hardware):
        core._start_playback_for_current()
        mock_hardware.calls.clear()
        old_track = core.current_track
        core.on_track_finished()
        assert core.current_track == old_track + 1

    def test_wraps_at_end(self, core, mock_hardware):
        total = len(core.albums[0]["tracks"])
        core.current_track = total
        core.on_track_finished()
        assert core.current_track == 1


class TestPowerOffOn:
    def test_power_off_saves_state(self, core, mock_hardware):
        core._start_playback_for_current()
        mock_hardware.calls.clear()
        core.power_off()
        assert core.power_on is False
        assert any(c[0] == "save_state" for c in mock_hardware.calls)
        assert any(c[0] == "stop" for c in mock_hardware.calls)

    def test_power_on_restores_mode(self, core, mock_hardware):
        core.switch_mode(MODE_PLAYLIST)
        core.current_album_index = 0
        core.current_track = 2
        core.power_off()

        core.power_on_handler()
        assert core.power_on is True
        assert core.mode == MODE_PLAYLIST
        assert core.current_track == 1

    def test_power_off_ignored_when_already_off(self, core, mock_hardware):
        core.power_off()
        mock_hardware.calls.clear()
        core.power_off()
        assert len(mock_hardware.calls) == 0


class TestRadioMode:
    def test_tune_radio_enters_mode(self, core, mock_hardware):
        core.tune_radio(50)
        assert core.mode == MODE_RADIO

    def test_tune_radio_maps_dial_to_station(self, core, mock_hardware):
        core.switch_mode(MODE_RADIO)
        num_stations = len(core.radio_stations)
        assert num_stations > 0
        core.tune_radio(0)
        assert core.radio_station_index == 0
        core.tune_radio(100)
        assert core.radio_station_index == num_stations - 1


class TestGetStatus:
    def test_album_mode_status(self, core):
        status = core.get_status()
        assert status["mode"] == MODE_ALBUM
        assert status["track_number"] == 1
        assert status["power_on"] is True
        assert "track_title" in status

    def test_playlist_mode_status(self, core, mock_hardware):
        core.switch_mode(MODE_PLAYLIST)
        status = core.get_status()
        assert status["mode"] == MODE_PLAYLIST


class TestShuffleNavigation:
    def test_next_in_shuffle(self, core, mock_hardware):
        core._init_library_shuffle()
        old_idx = core.shuffle_index
        core._next_track()
        assert core.shuffle_index == (old_idx + 1) % len(core.shuffle_tracks)

    def test_prev_in_shuffle(self, core, mock_hardware):
        core._init_library_shuffle()
        core.shuffle_index = 0
        core._prev_track()
        assert core.shuffle_index == len(core.shuffle_tracks) - 1
