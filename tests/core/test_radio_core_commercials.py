"""Basic firmware: folder 99 commercials insertion and resume."""

from __future__ import annotations

from tests.conftest import MockBasicHardware, _make_basic_stations
from radio_core import MODE_PLAYLIST, MODE_SHUFFLE, RadioCore


def _stations_with_ads():
    stations = _make_basic_stations()
    stations.append(
        {
            "id": 99,
            "name": "Folder 99",
            "tracks": [
                {
                    "id": 9901,
                    "title": "Ad 1",
                    "artist": "",
                    "duration": 15.0,
                    "folder": 99,
                    "track_number": 1,
                },
                {
                    "id": 9902,
                    "title": "Ad 2",
                    "artist": "",
                    "duration": 15.0,
                    "folder": 99,
                    "track_number": 2,
                },
            ],
        }
    )
    return stations


class _AdsHardware(MockBasicHardware):
    def get_commercials_config(self):
        return {"enabled": True, "interval": 2, "mode": "folder_99", "folder": 99}


def test_basic_seeding_excludes_folder_99_when_ads_enabled():
    hw = _AdsHardware(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    folders = []
    for pl in rc.playlists:
        tracks = pl.get("tracks") or []
        if tracks:
            folders.append(tracks[0].get("folder"))
        else:
            folders.append(pl.get("id"))
    assert 99 not in folders
    assert len(rc.playlists) == 2


def test_inserts_ad_after_interval_music_tracks_then_resumes():
    hw = _AdsHardware(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 1
    rc.is_playing = True
    rc._hydrate_basic_station(0, allow_assume=True)

    rc.on_track_finished()
    rc.on_track_finished()

    play_calls = [c for c in hw.calls if c[0] == "play_track"]
    assert any(c[1] == 99 for c in play_calls)
    assert rc._commercial_resume is not None or getattr(rc, "_playing_commercial", False)

    rc.on_track_finished()
    assert getattr(rc, "_playing_commercial", False) is False
    cur = rc._get_current_track()
    assert cur is not None
    assert cur.get("folder") != 99


def _core_playing_ad():
    hw = _AdsHardware(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 1
    rc.is_playing = True
    rc._hydrate_basic_station(0, allow_assume=True)
    rc.on_track_finished()
    rc.on_track_finished()
    assert rc._playing_commercial is True
    assert rc._commercial_resume is not None
    return hw, rc


def test_station_change_during_ad_does_not_replay_previous_station():
    hw, rc = _core_playing_ad()

    rc._next_album()
    assert rc._playing_commercial is False
    assert rc._commercial_resume is None
    assert rc.current_album_index == 1

    hw.logs.clear()
    rc.on_track_finished()
    assert "COMMERCIALS: finished, resuming music" not in hw.logs
    assert rc.current_album_index == 1


def test_next_track_during_ad_does_not_restart_the_new_track():
    hw, rc = _core_playing_ad()

    rc._next_track()
    started = rc.current_track
    assert rc._playing_commercial is False
    assert rc._commercial_resume is None

    hw.calls.clear()
    hw.logs.clear()
    rc.on_track_finished()
    assert "COMMERCIALS: finished, resuming music" not in hw.logs
    replays = [
        c
        for c in hw.calls
        if c[0] == "play_track" and c[1] == 1 and c[2] == started
    ]
    assert not replays


def test_get_status_reports_folder_commercial():
    hw = _AdsHardware(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    status = rc.get_status()
    assert status["playing_commercial"] is False
    assert status["folder_commercial_playing"] is False
    assert status["commercials_mode"] == "folder_99"

    rc._playing_commercial = True
    status = rc.get_status()
    assert status["playing_commercial"] is True
    assert status["folder_commercial_playing"] is True
    assert status["linked_ad_playing"] is False


def test_single_tap_counts_toward_ad_interval():
    hw = _AdsHardware(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 1
    rc.is_playing = True
    rc._hydrate_basic_station(0, allow_assume=True)

    rc._single_tap()
    assert getattr(rc, "_playing_commercial", False) is False
    assert rc.current_track == 2

    rc._single_tap()
    assert rc._playing_commercial is True
    play_calls = [c for c in hw.calls if c[0] == "play_track"]
    assert any(c[1] == 99 for c in play_calls)
    assert rc._commercial_resume == (0, 3)


def test_commercial_resume_past_end_wraps_when_not_advancing():
    hw = _AdsHardware(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 3
    rc.is_playing = True
    rc._playing_commercial = True
    rc.advance_next_station = False
    rc._commercial_resume = (0, 4)
    rc._resume_after_commercial()
    assert rc._playing_commercial is False
    assert rc.current_track == 1
    assert any(c[0] == "play_track" for c in hw.calls)


def test_single_tap_on_last_track_advances_station():
    hw = _AdsHardware(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 3
    rc.is_playing = True
    rc._hydrate_basic_station(0, allow_assume=True)
    rc._hydrate_basic_station(1, allow_assume=True)

    rc._single_tap()
    assert getattr(rc, "_playing_commercial", False) is False
    assert rc.current_album_index == 1
    assert rc.current_track == 1


def test_single_tap_on_last_track_inserts_ad_then_resumes_next_station():
    class _EveryTrackAds(_AdsHardware):
        def get_commercials_config(self):
            return {"enabled": True, "interval": 1, "mode": "folder_99", "folder": 99}

    hw = _EveryTrackAds(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 3
    rc.is_playing = True
    rc._hydrate_basic_station(0, allow_assume=True)
    rc._hydrate_basic_station(1, allow_assume=True)

    rc._single_tap()
    assert rc._playing_commercial is True
    assert rc._commercial_resume == (0, 4)

    rc.on_track_finished()
    assert getattr(rc, "_playing_commercial", False) is False
    assert rc.current_album_index == 1
    assert rc.current_track == 1


def test_empty_folder_99_skips_insertion():
    stations = _make_basic_stations()
    hw = _AdsHardware(stations=stations)
    hw.query_files_in_folder = lambda folder_num, **_kw: 0 if folder_num == 99 else 3
    hw.query_files_in_folder_consensus = hw.query_files_in_folder
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.current_album_index = 0
    rc.current_track = 1
    rc._hydrate_basic_station(0, allow_assume=True)
    rc.on_track_finished()
    rc.on_track_finished()
    play_calls = [c for c in hw.calls if c[0] == "play_track"]
    assert not any(c[1] == 99 for c in play_calls)


def test_shuffle_skip_ad_advances_shuffle_index_not_same_file():
    """Skip-ad used current_track+1 as a folder number; shuffle playback uses shuffle_index."""

    class _Interval2(_AdsHardware):
        def get_commercials_config(self):
            return {"enabled": True, "interval": 2, "mode": "folder_99", "folder": 99}

    hw = _Interval2(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 1
    rc.is_playing = True
    rc._hydrate_basic_station(0, allow_assume=True)
    rc._init_current_shuffle()
    assert rc.mode == MODE_SHUFFLE
    ordered = list(rc.playlists[0]["tracks"])
    rc.shuffle_tracks = ordered
    rc.shuffle_index = 0
    rc.current_track = 1

    rc._single_tap()
    assert rc._playing_commercial is False
    assert rc.shuffle_index == 1
    playing_before_ad = rc._get_current_track()
    assert playing_before_ad is not None
    assert playing_before_ad.get("track_number") == 2

    rc._single_tap()
    assert rc._playing_commercial is True
    assert rc._commercial_resume == (0, 3)

    rc.on_track_finished()
    assert rc._playing_commercial is False
    assert rc.shuffle_index == 2
    resumed = rc._get_current_track()
    assert resumed is not None
    assert resumed.get("folder") == 1
    assert resumed.get("track_number") == 3
    assert resumed.get("track_number") != playing_before_ad.get("track_number")


def test_shuffle_natural_end_ad_on_last_entry_advances_station():
    class _EveryTrackAds(_AdsHardware):
        def get_commercials_config(self):
            return {"enabled": True, "interval": 1, "mode": "folder_99", "folder": 99}

    hw = _EveryTrackAds(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 3
    rc.is_playing = True
    rc._hydrate_basic_station(0, allow_assume=True)
    rc._hydrate_basic_station(1, allow_assume=True)
    rc._init_current_shuffle()
    rc.shuffle_tracks = list(rc.playlists[0]["tracks"])
    rc.shuffle_index = 2
    rc.current_track = 3

    rc.on_track_finished()
    assert rc._playing_commercial is True
    assert rc._commercial_resume == (0, 4)

    rc.on_track_finished()
    assert rc._playing_commercial is False
    assert rc.current_album_index == 1


def test_shuffle_skip_ad_on_last_entry_advances_station():
    class _EveryTrackAds(_AdsHardware):
        def get_commercials_config(self):
            return {"enabled": True, "interval": 1, "mode": "folder_99", "folder": 99}

    hw = _EveryTrackAds(stations=_stations_with_ads())
    rc = RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.mode = MODE_PLAYLIST
    rc.current_album_index = 0
    rc.current_track = 3
    rc.is_playing = True
    rc._hydrate_basic_station(0, allow_assume=True)
    rc._hydrate_basic_station(1, allow_assume=True)
    rc._init_current_shuffle()
    rc.shuffle_tracks = list(rc.playlists[0]["tracks"])
    rc.shuffle_index = 2
    rc.current_track = 3

    rc._single_tap()
    assert rc._playing_commercial is True
    assert rc._commercial_resume == (0, 4)

    rc.on_track_finished()
    assert rc._playing_commercial is False
    assert rc.current_album_index == 1
    assert rc.mode == MODE_SHUFFLE
