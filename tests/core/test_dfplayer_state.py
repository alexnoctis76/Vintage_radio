"""Tests for DFPlayer hardware state persistence and metadata loading.

Unlike test_firmware_parsing.py which tests the state TEXT FORMAT in isolation,
these tests verify that RadioCore's save_state/load_state round-trip works
correctly through the MockHardware, that metadata is loaded and parsed correctly,
and that station discovery populates the right data structures.
"""

from __future__ import annotations

import json
import pytest

from radio_core import RadioCore, MODE_ALBUM, MODE_PLAYLIST, MODE_SHUFFLE
from tests.conftest import MockHardwareInterface, _make_test_albums, _make_test_playlists


# ---------------------------------------------------------------------------
# State persistence through RadioCore (save/load via HardwareInterface)
# ---------------------------------------------------------------------------

class TestRadioCoreStatePersistence:
    def test_save_state_round_trip(self):
        """save_state then load_state through MockHardware preserves all fields."""
        hw = MockHardwareInterface(
            albums=_make_test_albums(),
            playlists=_make_test_playlists(),
        )
        rc = RadioCore(hw)
        rc.init(skip_initial_playback=True)
        # Keep index in-range for playlist mode (fixture has 1 playlist).
        rc.current_album_index = 0
        rc.current_track = 2
        rc.mode = MODE_PLAYLIST
        rc.known_tracks = {1: 3, 2: 5}
        rc._save_state("test", persist=True)

        # New RadioCore loading from same hardware state
        rc2 = RadioCore(hw)
        rc2.albums = _make_test_albums()
        rc2.playlists = _make_test_playlists()
        rc2._load_state()

        assert rc2.current_album_index == 0
        assert rc2.current_track == 2
        assert rc2.mode == MODE_PLAYLIST
        assert rc2.known_tracks == {1: 3, 2: 5}

    def test_save_state_not_persisted_on_next_track(self):
        hw = MockHardwareInterface(
            albums=_make_test_albums(),
            playlists=_make_test_playlists(),
        )
        rc = RadioCore(hw)
        rc.init(skip_initial_playback=True)
        hw.calls.clear()
        rc._next_track()
        assert not any(c[0] == "save_state" for c in hw.calls)

    def test_save_state_not_persisted_on_mode_switch(self):
        hw = MockHardwareInterface(
            albums=_make_test_albums(),
            playlists=_make_test_playlists(),
        )
        rc = RadioCore(hw)
        rc.init(skip_initial_playback=True)
        hw.calls.clear()
        rc.switch_mode(MODE_PLAYLIST)
        assert not any(c[0] == "save_state" for c in hw.calls)

    def test_load_state_with_none_does_not_crash(self):
        hw = MockHardwareInterface(albums=_make_test_albums(), playlists=_make_test_playlists())
        hw._state = None
        rc = RadioCore(hw)
        rc.albums = _make_test_albums()
        rc.playlists = _make_test_playlists()
        try:
            rc._load_state()
        except Exception as exc:
            pytest.fail(f"_load_state with None state raised: {exc}")

    def test_load_state_clamps_album_and_track(self):
        hw = MockHardwareInterface(albums=_make_test_albums(), playlists=_make_test_playlists())
        hw._state = {
            "mode": MODE_ALBUM,
            "album_index": 100,  # way out of range
            "track": 500,        # way out of range
            "known_tracks": {},
        }
        rc = RadioCore(hw)
        rc.albums = _make_test_albums()
        rc.playlists = _make_test_playlists()
        rc._load_state()
        assert rc.current_album_index < len(rc.albums)
        assert rc.current_track <= len(rc.albums[rc.current_album_index]["tracks"])

    def test_load_state_forces_playlist_in_basic_mode_if_album_saved(self):
        """If basic mode loads a saved 'album' mode, it must be corrected to playlist."""
        hw = MockHardwareInterface(albums=[], playlists=_make_test_playlists())
        hw._state = {
            "mode": MODE_ALBUM,  # invalid for basic mode
            "album_index": 0,
            "track": 1,
            "known_tracks": {},
        }
        rc = RadioCore(hw, basic_mode=True)
        rc.albums = []
        rc.playlists = _make_test_playlists()
        rc._load_state()
        assert rc.mode != MODE_ALBUM

    def test_known_tracks_persisted_and_restored(self):
        hw = MockHardwareInterface(albums=_make_test_albums(), playlists=_make_test_playlists())
        rc = RadioCore(hw)
        rc.init(skip_initial_playback=True)
        rc.known_tracks = {3: 7, 5: 2}
        rc._save_state("known_tracks_test", persist=True)

        rc2 = RadioCore(hw)
        rc2.albums = _make_test_albums()
        rc2.playlists = _make_test_playlists()
        rc2._load_state()
        assert rc2.known_tracks == {3: 7, 5: 2}


# ---------------------------------------------------------------------------
# Metadata loading helpers (via MockHardwareInterface)
# ---------------------------------------------------------------------------

class TestMetadataViaHardware:
    def test_get_albums_returns_correct_structure(self):
        albums = _make_test_albums()
        hw = MockHardwareInterface(albums=albums)
        assert len(hw.get_albums()) == 3
        for album in hw.get_albums():
            assert "id" in album
            assert "name" in album
            assert "tracks" in album
            for track in album["tracks"]:
                assert "folder" in track
                assert "track_number" in track
                assert "duration" in track

    def test_get_playlists_returns_correct_structure(self):
        playlists = _make_test_playlists()
        hw = MockHardwareInterface(playlists=playlists)
        for pl in hw.get_playlists():
            assert "id" in pl
            assert "name" in pl
            assert "tracks" in pl

    def test_get_all_tracks_deduplicates_across_albums(self):
        """get_all_tracks should return a flat list across all albums."""
        albums = _make_test_albums()
        hw = MockHardwareInterface(albums=albums)
        all_tracks = hw.get_all_tracks()
        total_expected = sum(len(a["tracks"]) for a in albums)
        assert len(all_tracks) == total_expected

    def test_get_all_tracks_with_explicit_all_tracks_list(self):
        explicit = [
            {"id": 1, "title": "T1", "duration": 60.0, "folder": 1, "track_number": 1},
            {"id": 2, "title": "T2", "duration": 90.0, "folder": 1, "track_number": 2},
        ]
        hw = MockHardwareInterface(albums=[], all_tracks=explicit)
        assert hw.get_all_tracks() == explicit


# ---------------------------------------------------------------------------
# Station discovery (basic mode MockBasicHardware)
# ---------------------------------------------------------------------------

class TestStationDiscovery:
    def test_discovers_correct_number_of_stations(self):
        from tests.conftest import MockBasicHardware, _make_basic_stations
        hw = MockBasicHardware(stations=_make_basic_stations())
        stations = hw.discover_stations()
        assert len(stations) == 2

    def test_each_station_has_correct_track_count(self):
        from tests.conftest import MockBasicHardware, _make_basic_stations
        hw = MockBasicHardware(stations=_make_basic_stations())
        stations = hw.discover_stations()
        for station in stations:
            assert len(station["tracks"]) == 3

    def test_known_tracks_populated_on_discovery(self):
        from tests.conftest import MockBasicHardware, _make_basic_stations
        hw = MockBasicHardware(stations=_make_basic_stations())
        hw.discover_stations()
        assert len(hw._known_tracks) > 0
        for folder, count in hw._known_tracks.items():
            assert isinstance(folder, int)
            assert count > 0

    def test_empty_discovery_returns_empty_list(self):
        from tests.conftest import MockBasicHardware
        hw = MockBasicHardware(stations=[])
        hw.discover_stations = lambda: []
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        # Empty discovery should produce a placeholder, not crash
        assert len(rc.playlists) >= 1

    def test_station_folder_numbers_match_tracks(self):
        from tests.conftest import MockBasicHardware, _make_basic_stations
        hw = MockBasicHardware(stations=_make_basic_stations())
        stations = hw.discover_stations()
        for station in stations:
            if station["tracks"]:
                folder = station["tracks"][0]["folder"]
                for track in station["tracks"]:
                    assert track["folder"] == folder
