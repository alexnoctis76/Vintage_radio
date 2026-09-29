"""Conductor shuffle keeps a linked commercial attached to the track below it."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.conftest import MockBasicHardware

ROOT = Path(__file__).resolve().parents[2]
CONDUCTOR_CORE = ROOT / "firmware" / "conductor" / "radio_core.py"


def _load_conductor_radio_core():
    spec = importlib.util.spec_from_file_location(
        "conductor_radio_core_under_test", CONDUCTOR_CORE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CatalogHardware(MockBasicHardware):
    def __init__(self, catalog):
        super().__init__(stations=[])
        self._catalog = catalog

    def get_radio_catalog(self):
        return self._catalog

    def get_commercials_config(self):
        return {"enabled": False, "interval": 5, "mode": "inline", "folder": 99}


def _inline_catalog():
    return {
        "version": 1,
        "commercials": {"enabled": False, "mode": "inline", "interval": 5, "folder": 99},
        "stations": [
            {
                "folder": 1,
                "tracks": [
                    {"t": 1, "ad": 1, "link": 1},
                    {"t": 2, "ad": 0},
                    {"t": 3, "ad": 1},
                    {"t": 4, "ad": 0},
                ],
            }
        ],
    }


def test_shuffle_units_pair_linked_commercial_with_next_music():
    core = _load_conductor_radio_core()
    rc = core.RadioCore(_CatalogHardware(_inline_catalog()), basic_mode=True)
    tracks = [
        {"folder": 1, "track_number": 1, "ad": 1, "link": 1},
        {"folder": 1, "track_number": 2, "ad": 0},
        {"folder": 1, "track_number": 3, "ad": 1},
        {"folder": 1, "track_number": 4, "ad": 0},
    ]
    units = rc._shuffle_units_from_tracks(tracks)
    assert len(units) == 2
    assert units[0]["track_number"] == 2
    assert units[0]["pre_ad"]["track_number"] == 1
    assert units[1]["track_number"] == 4
    assert units[1].get("pre_ad") is None


def test_station_shuffle_plays_linked_commercial_before_music():
    core = _load_conductor_radio_core()
    hw = _CatalogHardware(_inline_catalog())
    rc = core.RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.current_album_index = 0
    rc._init_current_shuffle()
    assert rc.mode == core.MODE_SHUFFLE
    assert all(int(tr.get("ad") or 0) == 0 for tr in rc.shuffle_tracks)
    linked = [tr for tr in rc.shuffle_tracks if tr.get("pre_ad")]
    assert linked
    rc.shuffle_index = rc.shuffle_tracks.index(linked[0])
    rc.current_track = rc.shuffle_index + 1
    rc._clear_linked_ad_state()
    hw.calls.clear()
    rc._start_playback_for_current()
    play_calls = [c for c in hw.calls if c[0] == "play_track"]
    assert play_calls
    assert play_calls[0][1] == 1
    assert play_calls[0][2] == linked[0]["pre_ad"]["track_number"]
    assert rc._linked_ad_playing is True

    rc.on_track_finished()
    play_calls = [c for c in hw.calls if c[0] == "play_track"]
    assert play_calls[-1][2] == linked[0]["track_number"]
    assert rc._linked_ad_playing is False


def test_moving_off_a_staged_linked_ad_clears_it():
    core = _load_conductor_radio_core()
    hw = _CatalogHardware(_inline_catalog())
    rc = core.RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc.current_album_index = 0
    rc._init_current_shuffle()
    linked = [tr for tr in rc.shuffle_tracks if tr.get("pre_ad")]
    plain = [tr for tr in rc.shuffle_tracks if not tr.get("pre_ad")]
    assert linked and plain

    rc.shuffle_index = rc.shuffle_tracks.index(linked[0])
    rc.current_track = rc.shuffle_index + 1
    rc._clear_linked_ad_state()
    rc._start_playback_for_current()
    assert rc._linked_ad_playing is True

    rc.shuffle_index = rc.shuffle_tracks.index(plain[0])
    rc.current_track = rc.shuffle_index + 1
    hw.calls.clear()
    rc._start_playback_for_current()
    assert rc._linked_ad_playing is False
    play_calls = [c for c in hw.calls if c[0] == "play_track"]
    assert play_calls[-1][2] == plain[0]["track_number"]


def test_get_status_reports_linked_commercial():
    core = _load_conductor_radio_core()
    hw = _CatalogHardware(_inline_catalog())
    rc = core.RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    status = rc.get_status()
    assert status["commercials_mode"] == "inline"
    # Catalog starts on the linked commercial in ordered play.
    assert status["playing_commercial"] is True
    assert status["linked_ad_playing"] is False

    rc.current_album_index = 0
    rc._init_current_shuffle()
    linked = [tr for tr in rc.shuffle_tracks if tr.get("pre_ad")]
    rc.shuffle_index = rc.shuffle_tracks.index(linked[0])
    rc.current_track = rc.shuffle_index + 1
    rc._clear_linked_ad_state()
    rc._start_playback_for_current()
    status = rc.get_status()
    assert status["linked_ad_playing"] is True
    assert status["playing_commercial"] is True


def test_ipc_get_state_includes_commercial_fields():
    import importlib.util

    ipc_path = ROOT / "firmware" / "conductor" / "components" / "vintage_radio_ipc.py"
    spec = importlib.util.spec_from_file_location("conductor_ipc_under_test", ipc_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _Hw:
        pin_busy = None
        _playing_folder = 1
        _playing_track = 2

        def is_playing(self):
            return True

    class _Core:
        mode = "shuffle"
        current_track = 1
        current_album_index = 0
        power_on = True
        tap_count = 0
        button_down = False
        playlists = [{}]
        _shuffle_source_type = "station"

        def _commercials_status_fields(self):
            return {
                "playing_commercial": True,
                "commercials_mode": "inline",
                "linked_ad_playing": True,
                "folder_commercial_playing": False,
            }

    class _Fw:
        hw = _Hw()
        core = _Core()

    state = module._cmd_get_state(_Fw())
    assert state["playing_commercial"] is True
    assert state["linked_ad_playing"] is True
    assert state["commercials_mode"] == "inline"
    assert state["folder_commercial_playing"] is False


def test_both_mode_keeps_inline_ads_and_enables_folder_inserts():
    core = _load_conductor_radio_core()
    catalog = {
        "version": 1,
        "commercials": {"enabled": True, "mode": "both", "interval": 2, "folder": 99},
        "stations": [
            {
                "folder": 1,
                "tracks": [
                    {"t": 1, "ad": 0},
                    {"t": 2, "ad": 1},
                    {"t": 3, "ad": 0},
                ],
            },
            {"folder": 99, "tracks": [{"t": 1, "ad": 0}]},
        ],
    }
    hw = _CatalogHardware(catalog)
    hw.query_files_in_folder = lambda folder_num, **_kw: 2 if folder_num == 99 else 3
    hw.query_files_in_folder_consensus = hw.query_files_in_folder
    rc = core.RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    assert rc._commercials_enabled is True
    assert rc._commercials_mode == "both"
    folders = []
    ads = []
    for pl in rc.playlists:
        for tr in pl.get("tracks") or []:
            folders.append(tr.get("folder"))
            ads.append(int(tr.get("ad") or 0))
    assert 99 not in folders
    assert 1 in ads


def test_library_shuffle_includes_linked_pairs():
    core = _load_conductor_radio_core()
    hw = _CatalogHardware(_inline_catalog())
    rc = core.RadioCore(hw, basic_mode=True)
    rc.init(skip_initial_playback=True)
    rc._init_library_shuffle()
    assert rc._shuffle_source_type == "library"
    assert any(tr.get("pre_ad") for tr in rc.shuffle_tracks)
    assert not any(int(tr.get("ad") or 0) for tr in rc.shuffle_tracks)
