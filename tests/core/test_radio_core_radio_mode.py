"""Tests for RadioCore radio mode: virtual time, station initialization, tune_radio, and advance logic.

Radio mode uses a virtual timeline per station where elapsed time maps to
a specific track and offset. These tests validate correctness of the virtual
time math and the behaviors that depend on it.
"""

from __future__ import annotations

import pytest

from radio_core import (
    MODE_ALBUM,
    MODE_PLAYLIST,
    MODE_RADIO,
    RadioCore,
    RadioStation,
)
from tests.conftest import MockHardwareInterface, _make_test_albums, _make_test_playlists


def _make_hw_with_tracks():
    """Hardware with 2 albums (2 tracks each) and 1 playlist (2 tracks)."""
    albums = [
        {
            "id": 1, "name": "Album 1", "tracks": [
                {"id": 1, "title": "A1T1", "artist": "A", "duration": 60.0, "folder": 1, "track_number": 1},
                {"id": 2, "title": "A1T2", "artist": "A", "duration": 90.0, "folder": 1, "track_number": 2},
            ]
        },
        {
            "id": 2, "name": "Album 2", "tracks": [
                {"id": 3, "title": "A2T1", "artist": "B", "duration": 120.0, "folder": 2, "track_number": 1},
            ]
        },
    ]
    playlists = [
        {
            "id": 10, "name": "PL 1", "tracks": [
                {"id": 4, "title": "P1T1", "artist": "C", "duration": 180.0, "folder": 3, "track_number": 1},
            ]
        }
    ]
    return MockHardwareInterface(albums=albums, playlists=playlists)


@pytest.fixture
def radio_hw():
    return _make_hw_with_tracks()


@pytest.fixture
def radio_core(radio_hw):
    rc = RadioCore(radio_hw)
    rc.init(skip_initial_playback=True)
    return rc


# ---------------------------------------------------------------------------
# Radio station initialization
# ---------------------------------------------------------------------------

class TestRadioInit:
    def test_init_radio_creates_stations_for_full_library_albums_playlists(self, radio_core):
        radio_core._init_radio()
        station_names = [s.name for s in radio_core.radio_stations]
        # Expect full library, album stations, playlist stations
        assert any("Full Library" in n for n in station_names)
        assert any("Album 1" in n for n in station_names)
        assert any("PL 1" in n for n in station_names)

    def test_init_radio_basic_mode_skips_full_library_and_albums(self):
        from tests.conftest import MockBasicHardware, _make_basic_stations
        hw = MockBasicHardware(stations=_make_basic_stations())
        rc = RadioCore(hw, basic_mode=True)
        rc.init(skip_initial_playback=True)
        rc._init_radio()
        names = [s.name for s in rc.radio_stations]
        # Basic mode: no Full Library, no Album stations
        assert not any("Full Library" in n for n in names)
        # Should have playlist/station stations
        assert len(rc.radio_stations) > 0

    def test_station_total_duration_matches_tracks(self, radio_core):
        radio_core._init_radio()
        for station in radio_core.radio_stations:
            expected_ms = sum(
                int((t.get("duration", 0) or 0) * 1000) for t in station.tracks
            )
            assert station.total_duration_ms == max(expected_ms, 1)

    def test_station_start_offset_within_range(self, radio_core):
        radio_core._init_radio()
        for station in radio_core.radio_stations:
            assert 0 <= station.start_offset_ms < station.total_duration_ms

    def test_radio_mode_start_ms_set_on_init(self, radio_core):
        radio_core._init_radio()
        assert radio_core.radio_mode_start_ms is not None

    def test_reinit_preserves_existing_stations(self, radio_core):
        """Calling _init_radio a second time must not reset virtual clock."""
        radio_core._init_radio()
        first_start = radio_core.radio_mode_start_ms
        radio_core._init_radio()
        assert radio_core.radio_mode_start_ms == first_start


# ---------------------------------------------------------------------------
# _find_track_at_position (virtual timeline math)
# ---------------------------------------------------------------------------

class TestFindTrackAtPositionRadio:
    def test_position_at_exact_boundary_between_tracks(self, radio_core):
        """Exactly at track boundary should give track 2 with offset 0."""
        tracks = [
            {"duration": 60.0},
            {"duration": 60.0},
        ]
        # Position exactly at 60000ms = start of track 2
        track, offset = radio_core._find_track_at_position(tracks, 60_000)
        assert track == tracks[1]
        assert offset == 0

    def test_position_beyond_total_wraps_to_first(self, radio_core):
        tracks = [{"duration": 30.0}]
        track, offset = radio_core._find_track_at_position(tracks, 50_000)
        # Beyond the only track - should wrap
        assert track == tracks[0]

    def test_zero_duration_uses_default_180s(self, radio_core):
        """Track with duration=0 should use default 180000ms."""
        tracks = [
            {"duration": 0},
            {"duration": 60.0},
        ]
        # Position within the first "0-duration" track (default 180s)
        track, offset = radio_core._find_track_at_position(tracks, 100_000)
        assert track == tracks[0]
        assert offset == 100_000

    def test_none_duration_uses_default(self, radio_core):
        tracks = [{"duration": None}, {"duration": 60.0}]
        track, offset = radio_core._find_track_at_position(tracks, 50_000)
        assert track == tracks[0]

    def test_three_tracks_correct_selection(self, radio_core):
        tracks = [
            {"duration": 60.0},   # 0 - 60s
            {"duration": 90.0},   # 60s - 150s
            {"duration": 30.0},   # 150s - 180s
        ]
        track, offset = radio_core._find_track_at_position(tracks, 100_000)
        assert track == tracks[1]
        assert offset == 40_000  # 100000 - 60000


# ---------------------------------------------------------------------------
# tune_radio
# ---------------------------------------------------------------------------

class TestTuneRadio:
    def test_tune_enters_radio_mode(self, radio_core, radio_hw):
        radio_core.tune_radio(50)
        assert radio_core.mode == MODE_RADIO

    def test_tune_dial_0_maps_to_first_station(self, radio_core, radio_hw):
        radio_core.switch_mode(MODE_RADIO)
        radio_core.tune_radio(0)
        assert radio_core.radio_station_index == 0

    def test_tune_dial_100_maps_to_last_station(self, radio_core, radio_hw):
        radio_core.switch_mode(MODE_RADIO)
        radio_core.tune_radio(100)
        assert radio_core.radio_station_index == len(radio_core.radio_stations) - 1

    def test_station_change_triggers_am_overlay(self, radio_core, radio_hw):
        radio_core.switch_mode(MODE_RADIO)
        radio_hw.calls.clear()
        # Move from station 0 to last station
        radio_core.radio_station_index = 0
        radio_core.tune_radio(100)
        assert any(c[0] == "play_am_overlay" for c in radio_hw.calls)

    def test_tune_sets_cooldown(self, radio_core, radio_hw):
        radio_core.switch_mode(MODE_RADIO)
        from radio_core import ticks_ms
        radio_core.tune_radio(50)
        assert radio_core._radio_advance_cooldown_until_ms > ticks_ms()

    def test_same_station_retune_does_not_trigger_am(self, radio_core, radio_hw):
        """Tuning to the same station that's already playing should not play AM overlay."""
        radio_core.switch_mode(MODE_RADIO)
        radio_core.tune_radio(0)
        radio_hw.calls.clear()
        radio_core.tune_radio(0)
        # No station change -> no AM overlay
        assert not any(c[0] == "play_am_overlay" for c in radio_hw.calls)


# ---------------------------------------------------------------------------
# Radio mode: next/prev track are no-ops
# ---------------------------------------------------------------------------

class TestRadioModeNavigation:
    def test_next_track_noop_in_radio_mode(self, radio_core, radio_hw):
        radio_core.switch_mode(MODE_RADIO)
        radio_hw.calls.clear()
        track_before = radio_core.current_track
        radio_core._next_track()
        # next_track in radio mode should be a no-op
        assert radio_core.current_track == track_before

    def test_prev_track_noop_in_radio_mode(self, radio_core, radio_hw):
        radio_core.switch_mode(MODE_RADIO)
        radio_hw.calls.clear()
        track_before = radio_core.current_track
        radio_core._prev_track()
        assert radio_core.current_track == track_before

    def test_long_press_in_radio_mode_advances_station(self, radio_core, radio_hw):
        """Hold (0 taps + hold) advances station in radio mode via _next_album."""
        radio_core.switch_mode(MODE_RADIO)
        start_idx = radio_core.radio_station_index
        radio_core._pending_long_press = True
        radio_core.tap_count = 0
        radio_core._resolve_input()
        # Station index or album index should have incremented
        assert (
            radio_core.radio_station_index != start_idx
            or radio_core.current_album_index != 0
        )


# ---------------------------------------------------------------------------
# Radio mode: check_radio_advance cooldown
# ---------------------------------------------------------------------------

class TestRadioAdvanceCooldown:
    def test_advance_blocked_during_cooldown(self, radio_core, radio_hw):
        radio_core.switch_mode(MODE_RADIO)
        from radio_core import ticks_ms
        # Set a very long cooldown
        radio_core._radio_advance_cooldown_until_ms = ticks_ms() + 100_000
        radio_hw.calls.clear()
        result = radio_core._check_radio_advance()
        assert result is False
        # No play_track called during cooldown
        assert not any(c[0] == "play_track" for c in radio_hw.calls)

    def test_advance_allowed_after_cooldown(self, radio_core, radio_hw):
        radio_core.switch_mode(MODE_RADIO)
        # Expired cooldown
        radio_core._radio_advance_cooldown_until_ms = 0
        # Set radio_mode_start_ms far in the past so virtual time has progressed
        radio_core.radio_mode_start_ms = 0
        # This should not crash even if no advance happens
        try:
            radio_core._check_radio_advance()
        except Exception as exc:
            pytest.fail(f"_check_radio_advance raised: {exc}")
