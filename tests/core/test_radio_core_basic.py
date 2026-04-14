"""Tests for RadioCore in basic_mode=True.

Basic mode skips metadata files; stations are discovered from the DFPlayer
folder structure. Album mode is not available. These tests validate behavior
that is DIFFERENT from the full (advanced) mode.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import radio_core
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

    def test_lazy_hydrates_current_station_before_play(self):
        hw = MockBasicHardware(stations=_make_basic_stations())
        seeded = [
            {"id": st["id"], "name": st["name"], "tracks": [], "track_count": 0, "hydrated": False}
            for st in hw._stations
        ]
        hw.discover_stations = lambda: list(seeded)
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.current_album_index = 0
        rc.current_track = 1

        rc._start_playback_for_current()

        assert rc.playlists[0].get("hydrated") is True
        assert rc.playlists[0].get("track_count") == 3
        assert any(c[0] == "play_track" for c in hw.calls)

    def test_next_station_skips_confirmed_empty_folder(self):
        hw = MockBasicHardware(stations=_make_basic_stations())
        seeded = [
            {"id": 1, "name": "Station 1", "tracks": [], "track_count": 0, "hydrated": False},
            {"id": 2, "name": "Station 2", "tracks": [], "track_count": 0, "hydrated": False},
            {"id": 3, "name": "Station 3", "tracks": [], "track_count": 0, "hydrated": False},
        ]
        count_map = {1: 3, 2: 0, 3: 2}
        hw.discover_stations = lambda: list(seeded)
        hw.query_files_in_folder = lambda folder_num, **_kw: count_map.get(folder_num, 0)
        hw.query_files_in_folder_consensus = lambda folder_num, **_kw: count_map.get(folder_num, 0)

        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.current_album_index = 0
        rc.current_track = 1
        rc._next_album()

        # Station 2 is empty, so playback should land on station 3.
        assert rc.current_album_index == 2
        assert rc.playlists[2].get("track_count") == 2

    def test_track1_play_failure_does_not_advance_or_mark_negative(self):
        """Failed track-1 play does not auto-advance stations or set basic_hydrate_negative
        (BUSY timeout != file not found)."""
        hw = MockBasicHardware(stations=_make_basic_stations())
        seeded = [
            {"id": 1, "name": "S1", "tracks": [], "track_count": 255, "hydrated": True},
            {"id": 2, "name": "S2", "tracks": [], "track_count": 3, "hydrated": True},
        ]
        hw.discover_stations = lambda: list(seeded)
        play_attempts = []

        def play_track(folder, track, start_ms=0, folder_wrap=False):
            play_attempts.append((folder, track))
            hw.calls.append(("play_track", folder, track, start_ms, folder_wrap))
            if folder == 1 and track == 1 and len([a for a in play_attempts if a == (1, 1)]) == 1:
                return False
            hw._playing = True
            return True

        hw.play_track = play_track
        hw._last_error_code = None

        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.current_album_index = 0
        rc.current_track = 1
        rc.known_tracks[1] = 255

        rc._start_playback_for_current()

        assert rc.playlists[0].get("basic_hydrate_negative") is not True
        assert rc.current_album_index == 0
        assert play_attempts.count((1, 1)) == 1
        assert (2, 1) not in play_attempts

    def test_track_count_lookup_hydrates_current_station(self):
        hw = MockBasicHardware(stations=_make_basic_stations())
        seeded = [
            {"id": st["id"], "name": st["name"], "tracks": [], "track_count": 0, "hydrated": False}
            for st in hw._stations
        ]
        hw.discover_stations = lambda: list(seeded)
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.current_album_index = 0
        rc.current_track = 1

        assert rc._get_track_count() == 3
        assert rc.playlists[0].get("hydrated") is True

    def test_unhydrated_placeholder_counts_are_not_treated_as_confirmed(self):
        hw = MockBasicHardware(stations=[])
        rc = RadioCore(hw, basic_mode=True)
        pl = {"id": 9, "name": "S9", "tracks": [], "track_count": 255, "hydrated": False}
        assert rc._basic_playlist_track_count(pl) == 0

    def test_load_state_shuffle_defers_station_shuffle_rebuild(self):
        hw = MockBasicHardware(stations=[])
        rc = RadioCore(hw, basic_mode=True)
        rc.playlists = [
            {"id": 1, "name": "S1", "tracks": [], "track_count": 0, "hydrated": False},
            {"id": 2, "name": "S2", "tracks": [], "track_count": 0, "hydrated": False},
        ]
        hw._state = {
            "mode": "shuffle",
            "album_index": 0,
            "track": 1,
            "known_tracks": {1: 2, 2: 2},
        }
        rc._load_state()
        assert rc._defer_basic_shuffle_rebuild is True
        assert rc._shuffle_entry_count() == 0


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

    def test_three_tap_hold_jumps_to_first_station_shuffle(self, basic_core):
        basic_core._init_current_shuffle()
        assert basic_core.mode == MODE_SHUFFLE
        basic_core.current_album_index = 1
        basic_core._pending_long_press = True
        basic_core.tap_count = 3
        basic_core._resolve_input()
        assert basic_core.mode == MODE_SHUFFLE
        assert basic_core.current_album_index == 0
        assert basic_core._shuffle_source_type == "station"
        assert basic_core.current_track == 1

    def test_album_mode_never_reachable_via_switch(self, basic_core):
        """switch_mode(MODE_ALBUM) must be rejected in basic mode."""
        basic_core.switch_mode(MODE_ALBUM)
        assert basic_core.mode != MODE_ALBUM

    def test_switch_to_same_mode_is_noop(self, basic_core, mock_basic_hardware):
        mock_basic_hardware.calls.clear()
        basic_core.switch_mode(MODE_PLAYLIST)
        assert not any(c[0] == "stop" for c in mock_basic_hardware.calls)

    def test_four_tap_hold_unmapped_is_noop(self, basic_core):
        basic_core.current_album_index = 1
        basic_core.mode = MODE_PLAYLIST
        basic_core._handle_long_press_with_taps(4)
        assert basic_core.mode == MODE_PLAYLIST
        assert basic_core.current_album_index == 1

    def test_five_tap_hold_unmapped_is_noop(self, basic_core):
        basic_core.current_album_index = 1
        basic_core.mode = MODE_PLAYLIST
        basic_core._handle_long_press_with_taps(5)
        assert basic_core.mode == MODE_PLAYLIST
        assert basic_core.current_album_index == 1


class TestBasicFourFiveTap:
    def test_five_tap_goes_first_station(self, basic_core):
        basic_core.current_album_index = 1
        basic_core.current_track = 2
        basic_core.tap_count = 5
        basic_core._pending_long_press = False
        basic_core._resolve_input()
        assert basic_core.current_album_index == 0
        assert basic_core.current_track == 1
        assert basic_core.mode == MODE_PLAYLIST

    def test_five_tap_exits_shuffle_to_first_station(self, basic_core):
        basic_core._init_current_shuffle()
        assert basic_core.mode == MODE_SHUFFLE
        basic_core.current_album_index = 1
        basic_core.tap_count = 5
        basic_core._pending_long_press = False
        basic_core._resolve_input()
        assert basic_core.mode == MODE_PLAYLIST
        assert basic_core.current_album_index == 0

    def test_four_tap_prev_station_via_resolve(self, basic_core):
        basic_core.current_album_index = 1
        basic_core.tap_count = 4
        basic_core._pending_long_press = False
        basic_core._resolve_input()
        assert basic_core.current_album_index == 0


class DelayReasonHardware(MockBasicHardware):
    """Mock basic hardware that records delayed-playback transition reasons."""

    def __init__(self, stations=None):
        super().__init__(stations=stations)
        self.delay_reasons = []

    def set_delay_playback_reason(self, reason):
        self.delay_reasons.append(reason)


class TestBasicAmTriggerScope:
    def _make_core(self):
        stations = _make_basic_stations()
        hw = DelayReasonHardware(stations=stations)
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.mode = MODE_PLAYLIST
        rc.current_album_index = 0
        rc.current_track = 1
        return rc, hw

    def test_mode_switch_playlist_to_shuffle_basic_schedules_am_overlay(self):
        rc, hw = self._make_core()
        rc.switch_mode(MODE_SHUFFLE)
        assert "mode_change" in hw.delay_reasons

    def test_mode_switch_shuffle_to_playlist_still_sets_mode_change_reason(self):
        rc, hw = self._make_core()
        rc.switch_mode(MODE_SHUFFLE)
        hw.delay_reasons.clear()
        rc.switch_mode(MODE_PLAYLIST)
        assert "mode_change" in hw.delay_reasons

    def test_next_station_sets_station_change_reason(self):
        rc, hw = self._make_core()
        rc._next_album()
        assert "station_change" in hw.delay_reasons

    def test_power_on_sets_power_on_reason(self):
        rc, hw = self._make_core()
        rc.power_on = False
        rc.power_on_handler()
        assert "power_on" in hw.delay_reasons

    def test_next_track_does_not_schedule_am_transition(self):
        rc, hw = self._make_core()
        rc._next_track()
        assert hw.delay_reasons == []

    def test_station_shuffle_next_station_schedules_am_overlay(self):
        stations = _make_basic_stations()
        hw = DelayReasonHardware(stations=stations)
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.current_album_index = 0
        rc.current_track = 1
        rc.shuffle_tracks = list(rc.playlists[0]["tracks"])
        rc.shuffle_index = 0
        rc._next_album()
        assert "station_change" in hw.delay_reasons


class TestBasicStationCycleShuffle:
    def _make_core(self):
        stations = [
            {
                "id": 1,
                "name": "Station 1",
                "tracks": [{"id": 1001, "title": "S1T1", "folder": 1, "track_number": 1, "duration": 60.0}],
            },
            {
                "id": 2,
                "name": "Station 2",
                "tracks": [{"id": 2001, "title": "S2T1", "folder": 2, "track_number": 1, "duration": 60.0}],
            },
            {
                "id": 3,
                "name": "Station 3",
                "tracks": [{"id": 3001, "title": "S3T1", "folder": 3, "track_number": 1, "duration": 60.0}],
            },
        ]
        hw = MockBasicHardware(stations=stations)
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.mode = MODE_PLAYLIST
        rc.current_album_index = 0
        rc.current_track = 1
        return rc

    def test_next_station_sequential_in_playlist_mode(self):
        rc = self._make_core()
        rc._next_album()
        assert rc.current_album_index == 1
        rc._next_album()
        assert rc.current_album_index == 2
        rc._next_album()
        assert rc.current_album_index == 0

    def test_station_shuffle_mode_advances_station_sequentially(self):
        rc = self._make_core()
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.current_album_index = 0
        rc.shuffle_tracks = list(rc.playlists[0]["tracks"])
        rc.shuffle_index = len(rc.shuffle_tracks) - 1
        rc.current_track = len(rc.shuffle_tracks)

        rc._next_album()
        assert rc.current_album_index == 1
        assert rc.mode == MODE_SHUFFLE
        assert rc._shuffle_source_type == "station"

    def test_station_shuffle_single_tap_on_last_wraps_same_station(self):
        """Explicit next (single_tap) at last shuffle step wraps; does not auto-advance station."""
        tracks = [
            {"id": i, "title": f"T{i}", "folder": 1, "track_number": i, "duration": 1.0}
            for i in range(1, 4)
        ]
        s1 = {"id": 1, "name": "S1", "tracks": tracks}
        s2 = {
            "id": 2,
            "name": "S2",
            "tracks": [{"id": 99, "title": "x", "folder": 2, "track_number": 1, "duration": 1.0}],
        }
        hw = MockBasicHardware(stations=[s1, s2])
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.playlists = [s1, s2]
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.current_album_index = 0
        rc.shuffle_tracks = list(tracks)
        rc.shuffle_index = 2
        rc.current_track = 3
        rc._single_tap()
        assert rc.current_album_index == 0
        assert rc.shuffle_index == 0
        assert rc.current_track == 1

    def test_station_shuffle_natural_end_stops_when_no_advance_no_loop(self):
        tracks = [
            {"id": i, "title": f"T{i}", "folder": 1, "track_number": i, "duration": 1.0}
            for i in range(1, 3)
        ]
        s1 = {"id": 1, "name": "S1", "tracks": tracks}
        hw = MockBasicHardware(stations=[s1])
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.playlists = [s1]
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.current_album_index = 0
        rc.shuffle_tracks = list(tracks)
        rc.shuffle_index = 1
        rc.current_track = 2
        rc.power_on = True
        rc.is_playing = True
        rc.advance_next_station = False
        rc.loop_stations = False
        rc.on_track_finished()
        assert any(c[0] == "stop" for c in hw.calls)

    def test_station_shuffle_long_press_starts_new_station_at_shuffle_head(self):
        """After long-press next station, play begins at shuffle_tracks[0] (random order), not 001."""
        tracks = [
            {"id": i, "title": f"T{i}", "folder": 1, "track_number": i, "duration": 1.0}
            for i in range(1, 8)
        ]
        tracks2 = [
            {"id": 100 + i, "title": f"S2T{i}", "folder": 2, "track_number": i, "duration": 1.0}
            for i in range(1, 8)
        ]
        s1 = {"id": 1, "name": "Station 1", "tracks": tracks}
        s2 = {"id": 2, "name": "Station 2", "tracks": tracks2}
        hw = MockBasicHardware(stations=[s1, s2])
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.playlists = [s1, s2]
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.current_album_index = 0
        rc.shuffle_tracks = list(tracks)
        rc.shuffle_index = 3
        rc.current_track = 4

        rc._next_album()

        assert rc.current_album_index == 1
        assert rc.shuffle_index == 0
        assert rc.current_track == 1
        cur = rc.shuffle_tracks[rc.shuffle_index]
        assert cur["folder"] == 2
        assert cur == rc.shuffle_tracks[0]
        assert {t["track_number"] for t in rc.shuffle_tracks} == set(range(1, 8))

    def test_shuffle_long_press_skips_empty_station_without_stale_shuffle_tracks(self):
        t1 = [
            {"id": i, "title": f"T{i}", "folder": 1, "track_number": i, "duration": 1.0}
            for i in range(1, 4)
        ]
        s1 = {"id": 1, "name": "S1", "tracks": t1}
        s2 = {"id": 2, "name": "S2", "tracks": [], "track_count": 0, "hydrated": True}
        t3 = [
            {"id": 300 + i, "title": f"T{i}", "folder": 3, "track_number": i, "duration": 1.0}
            for i in range(1, 4)
        ]
        s3 = {"id": 3, "name": "S3", "tracks": t3}
        hw = MockBasicHardware(stations=[s1, s2, s3])
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc.playlists = [s1, s2, s3]
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.current_album_index = 0
        rc.shuffle_tracks = list(t1)

        rc._next_album()

        assert rc.current_album_index == 2
        assert rc.shuffle_index == 0
        assert rc.shuffle_tracks[rc.shuffle_index]["folder"] == 3
        assert rc.shuffle_tracks[rc.shuffle_index] == rc.shuffle_tracks[0]
        assert {t["track_number"] for t in rc.shuffle_tracks} == {1, 2, 3}


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


class TestBasicShuffleWorstCase:
    """Stress basic station-shuffle transitions with 255-track stations."""

    @staticmethod
    def _station(folder: int):
        tracks = []
        for t in range(1, 256):
            tracks.append(
                {
                    "id": folder * 1000 + t,
                    "title": f"S{folder}T{t}",
                    "artist": "",
                    "duration": 60.0,
                    "folder": folder,
                    "track_number": t,
                }
            )
        return {"id": folder, "name": f"Station {folder}", "tracks": tracks}

    def test_repeated_station_shuffle_advances_do_not_crash(self):
        stations = [self._station(1), self._station(2), self._station(3)]
        hw = MockBasicHardware(stations=stations)
        rc = RadioCore(hw, basic_mode=True)
        rc.albums = []
        rc.playlists = list(stations)
        rc.mode = MODE_SHUFFLE
        rc._shuffle_source_type = "station"
        rc.current_album_index = 0
        rc.shuffle_tracks = list(stations[0]["tracks"])
        rc.shuffle_index = 254
        rc.current_track = 255
        rc.power_on = True
        rc.is_playing = True
        rc.advance_next_station = True
        rc.loop_stations = False

        # Simulate repeated station-boundary auto-advances.
        for _ in range(30):
            rc.on_track_finished()
            assert rc.mode in (MODE_SHUFFLE, MODE_PLAYLIST)
            assert 0 <= rc.current_album_index < len(rc.playlists)
            if rc.mode == MODE_SHUFFLE:
                assert len(rc.shuffle_tracks) == 255
                # Jump to boundary again for next loop iteration.
                rc.shuffle_index = 254
                rc.current_track = 255



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
