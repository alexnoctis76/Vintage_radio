"""Tests for firmware file parsing logic (no real hardware).

Uses production save/load/metadata helpers from firmware modules.
"""

from __future__ import annotations

import json
import struct
import sys
import time
import types

import pytest

if "ustruct" not in sys.modules:
    ustruct = types.ModuleType("ustruct")
    ustruct.unpack = struct.unpack
    ustruct.unpack_from = struct.unpack_from
    sys.modules["ustruct"] = ustruct

if "machine" not in sys.modules:
    machine = types.ModuleType("machine")
    machine.Pin = object
    machine.PWM = object
    machine.Timer = object
    machine.UART = object
    machine.SPI = object
    sys.modules["machine"] = machine
if "ujson" not in sys.modules:
    import json as _json

    ujson = types.ModuleType("ujson")
    ujson.dumps = _json.dumps
    ujson.loads = _json.loads
    ujson.dump = _json.dump
    ujson.load = _json.load
    sys.modules["ujson"] = ujson
for _name in ("neopixel", "sdcard", "am_wav_loader", "pin_config_loader", "components"):
    if _name not in sys.modules:
        sys.modules[_name] = types.ModuleType(_name)
sys.modules["components"].am_wav_loader = types.ModuleType("am_wav_loader")
sys.modules["pin_config_loader"].load_pin_config = lambda: {"pins": {}}
sys.modules["pin_config_loader"].get_spi_config = lambda: {}
sys.modules["pin_config_loader"].get_dfplayer_config = lambda: {"max_volume": 28}

from firmware.pico import dfplayer_hardware as dfhw  # noqa: E402
from firmware.pi import pi_hardware as pihw  # noqa: E402

if not hasattr(dfhw.time, "ticks_ms"):
    _T0 = time.monotonic()
    dfhw.time.ticks_ms = lambda: int((time.monotonic() - _T0) * 1000)
    dfhw.time.ticks_diff = lambda a, b: a - b
    dfhw.time.ticks_add = lambda a, b: a + b
    if not hasattr(dfhw.time, "sleep_ms"):
        dfhw.time.sleep_ms = lambda ms: time.sleep(ms / 1000.0)


@pytest.fixture
def dfplayer_hw(tmp_path, monkeypatch):
    album_file = tmp_path / "album_state.txt"
    monkeypatch.setattr(dfhw, "ALBUM_FILE", str(album_file))
    hw = dfhw.DFPlayerHardware.__new__(dfhw.DFPlayerHardware)
    hw._albums = []
    hw._playlists = []
    hw._known_tracks = {}
    monkeypatch.setattr(hw, "_load_metadata", lambda: None)
    monkeypatch.setattr(hw, "_try_mount_sd", lambda: None)
    return hw


@pytest.fixture
def pi_hw(tmp_path):
    return pihw.PiHardware(media_root=str(tmp_path))


def _write_dfplayer_metadata(tmp_path, data, monkeypatch):
    (tmp_path / "radio_metadata.json").write_text(json.dumps(data), encoding="utf-8")
    hw = dfhw.DFPlayerHardware.__new__(dfhw.DFPlayerHardware)
    hw._albums = []
    hw._playlists = []
    hw._known_tracks = {}
    hw._try_mount_sd = lambda: None
    monkeypatch.chdir(tmp_path)
    dfhw.DFPlayerHardware._load_metadata(hw)
    return hw


class TestDFPlayerStateFormat:
    """Verify album_state.txt via DFPlayerHardware.save_state / load_state."""

    def test_round_trip(self, dfplayer_hw):
        original = {"album_index": 2, "track": 5, "mode": "playlist"}
        dfplayer_hw.save_state(original)
        decoded = dfplayer_hw.load_state()
        assert decoded["album_index"] == 2
        assert decoded["track"] == 5
        assert decoded["mode"] == "playlist"

    def test_default_mode(self, dfplayer_hw, tmp_path):
        (tmp_path / "album_state.txt").write_text("3,1;tracks=")
        decoded = dfplayer_hw.load_state()
        assert decoded["mode"] == "album"
        assert decoded["album_index"] == 2
        assert decoded["track"] == 1

    def test_invalid_mode_falls_back(self, dfplayer_hw, tmp_path):
        (tmp_path / "album_state.txt").write_text("1,1;tracks=;mode=bogus")
        decoded = dfplayer_hw.load_state()
        assert decoded["mode"] == "album"

    def test_shuffle_mode_round_trip(self, dfplayer_hw):
        dfplayer_hw.save_state({"album_index": 1, "track": 3, "mode": "shuffle"})
        decoded = dfplayer_hw.load_state()
        assert decoded["mode"] == "shuffle"
        assert decoded["album_index"] == 1
        assert decoded["track"] == 3


class TestMetadataParsing:
    """Test radio_metadata.json parsing via DFPlayerHardware._load_metadata."""

    def test_new_format(self, tmp_path, monkeypatch):
        data = {
            "songs": {
                "1": {"title": "Song A", "artist": "Art 1", "duration": 200, "folder": 1, "track": 1},
                "2": {"title": "Song B", "artist": "Art 2", "duration": 180, "folder": 1, "track": 2},
            },
            "albums": [
                {
                    "id": 1,
                    "name": "Album 1",
                    "tracks": [
                        {"song_id": 1, "folder": 1, "track": 1},
                        {"song_id": 2, "folder": 1, "track": 2},
                    ],
                },
            ],
            "playlists": [
                {
                    "id": 10,
                    "name": "Chill",
                    "tracks": [{"song_id": 2, "folder": 1, "track": 2}],
                },
            ],
        }
        hw = _write_dfplayer_metadata(tmp_path, data, monkeypatch)
        assert len(hw._albums) == 1
        assert hw._albums[0]["name"] == "Album 1"
        assert len(hw._albums[0]["tracks"]) == 2
        assert hw._albums[0]["tracks"][0]["title"] == "Song A"
        assert len(hw._playlists) == 1
        assert hw._playlists[0]["tracks"][0]["title"] == "Song B"

    def test_missing_song_uses_defaults(self, tmp_path, monkeypatch):
        data = {
            "songs": {},
            "albums": [
                {
                    "id": 1,
                    "name": "Empty",
                    "tracks": [{"song_id": 99, "folder": 5, "track": 3}],
                },
            ],
        }
        hw = _write_dfplayer_metadata(tmp_path, data, monkeypatch)
        track = hw._albums[0]["tracks"][0]
        assert track["title"] == "Track 1"
        assert track["folder"] == 5
        assert track["track_number"] == 3

    def test_am_sound_in_metadata(self, tmp_path, monkeypatch):
        data = {"am_sound": {"folder": 99, "track": 1}, "songs": {}, "albums": []}
        hw = _write_dfplayer_metadata(tmp_path, data, monkeypatch)
        assert hw._albums == []
        assert hw._playlists == []


class TestPiStateFormat:
    """Pi hardware album_state.txt via PiHardware.save_state / load_state."""

    def test_basic(self, pi_hw):
        pi_hw.save_state({"album_index": 2, "track": 2, "known_tracks": {1: 5, 2: 3}})
        state = pi_hw.load_state()
        assert state["album_index"] == 2
        assert state["track"] == 2
        assert state["known_tracks"] == {1: 5, 2: 3}
        assert state["mode"] == "album"

    def test_empty(self, pi_hw):
        pi_hw.save_state({"album_index": 0, "track": 1, "known_tracks": {}})
        state = pi_hw.load_state()
        assert state["album_index"] == 0
        assert state["track"] == 1
        assert state["known_tracks"] == {}


class TestPiPathResolution:
    """Test _resolve_sd_path from pi_hardware."""

    def test_absolute_with_vintage(self):
        result = pihw._resolve_sd_path("/Volumes/SD/VintageRadio/library/song.mp3")
        norm = result.replace("\\", "/")
        assert norm.endswith("/VintageRadio/library/song.mp3")

    def test_relative_path(self, monkeypatch):
        monkeypatch.setattr(pihw, "MEDIA_ROOT", "/media/vintage")
        result = pihw._resolve_sd_path("01/001.mp3")
        assert result.replace("\\", "/") == "/media/vintage/01/001.mp3"

    def test_none(self):
        assert pihw._resolve_sd_path(None) is None

    def test_empty(self):
        assert pihw._resolve_sd_path("") is None

    def test_absolute_without_vintage(self):
        result = pihw._resolve_sd_path("/some/other/path.mp3")
        norm = result.replace("\\", "/")
        assert norm.endswith("/some/other/path.mp3")
        assert "VintageRadio" not in norm
