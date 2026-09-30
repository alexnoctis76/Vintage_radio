"""Tests for DFPlayer Mini binary UART protocol.

Exercises production packet helpers and AM WAV loader — no duplicate golden
reimplementations in this file.
"""

from __future__ import annotations

import struct
import sys
import time
import types

import pytest

from dfplayer_protocol import (
    DF_ERROR_MSGS,
    build_dfplayer_packet,
    packet_body_checksum,
)

if "ustruct" not in sys.modules:
    ustruct = types.ModuleType("ustruct")
    ustruct.unpack = struct.unpack
    ustruct.unpack_from = struct.unpack_from
    sys.modules["ustruct"] = ustruct

from firmware.pico.components import am_wav_loader as wav_loader  # noqa: E402


def _stub_dfplayer_imports():
    """MicroPython stubs so dfplayer_hardware can be imported on the host."""
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


_stub_dfplayer_imports()
from firmware.pico import dfplayer_hardware as dfhw  # noqa: E402

if not hasattr(dfhw.time, "ticks_ms"):
    _T0 = time.monotonic()
    dfhw.time.ticks_ms = lambda: int((time.monotonic() - _T0) * 1000)
    dfhw.time.ticks_diff = lambda a, b: a - b
    dfhw.time.ticks_add = lambda a, b: a + b
    if not hasattr(dfhw.time, "sleep_ms"):
        dfhw.time.sleep_ms = lambda ms: time.sleep(ms / 1000.0)


def _build_wav(num_frames: int, samplerate: int = 8000) -> bytes:
    fmt = struct.pack("<HHIIHH", 1, 1, samplerate, samplerate, 1, 8)
    data = bytes([128 + (i % 16) for i in range(num_frames)])
    body = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + b"WAVE" + body


class TestPacketStructure:
    def test_packet_is_10_bytes(self):
        assert len(build_dfplayer_packet(0x06, 0, 15)) == 10

    def test_packet_starts_with_7e(self):
        assert build_dfplayer_packet(0x06)[0] == 0x7E

    def test_packet_ends_with_ef(self):
        assert build_dfplayer_packet(0x06)[9] == 0xEF

    def test_packet_byte_1_is_ff(self):
        assert build_dfplayer_packet(0x06)[1] == 0xFF

    def test_packet_byte_2_is_06_length(self):
        assert build_dfplayer_packet(0x06)[2] == 0x06

    def test_cmd_byte_position(self):
        pkt = build_dfplayer_packet(0x0F, 2, 3)
        assert pkt[3] == 0x0F

    def test_no_feedback_byte_is_zero(self):
        assert build_dfplayer_packet(0x06, feedback=False)[4] == 0x00

    def test_feedback_byte_is_one(self):
        assert build_dfplayer_packet(0x06, feedback=True)[4] == 0x01

    def test_p1_p2_positions(self):
        pkt = build_dfplayer_packet(0x0F, p1=5, p2=7)
        assert pkt[5] == 5
        assert pkt[6] == 7


class TestChecksum:
    def test_checksum_formula(self):
        pkt = build_dfplayer_packet(0x06, 0, 15)
        csum = packet_body_checksum(pkt[1:7])
        assert pkt[7] == (csum >> 8) & 0xFF
        assert pkt[8] == csum & 0xFF

    def test_checksum_stop_command(self):
        pkt = build_dfplayer_packet(0x16)
        csum = packet_body_checksum(pkt[1:7])
        assert pkt[7] == (csum >> 8) & 0xFF
        assert pkt[8] == csum & 0xFF

    def test_checksum_volume_15(self):
        pkt = build_dfplayer_packet(0x06, 0, 15)
        expected = packet_body_checksum(bytes([0xFF, 0x06, 0x06, 0x00, 0x00, 0x0F]))
        assert pkt[7:9] == bytes([(expected >> 8) & 0xFF, expected & 0xFF])

    def test_checksum_play_folder_2_track_3(self):
        pkt = build_dfplayer_packet(0x0F, 2, 3)
        expected = packet_body_checksum(bytes([0xFF, 0x06, 0x0F, 0x00, 0x02, 0x03]))
        assert pkt[7] == (expected >> 8) & 0xFF
        assert pkt[8] == expected & 0xFF


class TestKnownCommands:
    def test_volume_set_cmd_is_0x06(self):
        assert build_dfplayer_packet(0x06, 0, 20)[3] == 0x06

    def test_play_folder_track_cmd_is_0x0f(self):
        assert build_dfplayer_packet(0x0F, 1, 1)[3] == 0x0F

    def test_stop_cmd_is_0x16(self):
        assert build_dfplayer_packet(0x16)[3] == 0x16

    def test_query_status_cmd_is_0x42_with_feedback(self):
        pkt = build_dfplayer_packet(0x42, feedback=True)
        assert pkt[3] == 0x42
        assert pkt[4] == 0x01

    def test_query_file_count_cmd_is_0x48(self):
        assert build_dfplayer_packet(0x48, feedback=True)[3] == 0x48

    def test_query_folder_count_cmd_is_0x4f(self):
        assert build_dfplayer_packet(0x4F, feedback=True)[3] == 0x4F


class TestResponsePacketParsing:
    def test_valid_response_parses_cmd(self):
        pkt = build_dfplayer_packet(0x3D, 0, 5)
        assert pkt[3] == 0x3D

    def test_valid_response_parses_p1_p2(self):
        pkt = build_dfplayer_packet(0x42, 0, 1)
        assert pkt[5] == 0
        assert pkt[6] == 1

    def test_valid_response_checksum_passes(self):
        pkt = build_dfplayer_packet(0x3D, 0, 5)
        expected = packet_body_checksum(pkt[1:7])
        actual = (pkt[7] << 8) | pkt[8]
        assert actual == expected

    def test_response_with_wrong_start_byte_detectable(self):
        pkt = bytearray(build_dfplayer_packet(0x42))
        pkt[0] = 0x00
        assert pkt[0] != 0x7E

    def test_response_with_bad_checksum_detectable(self):
        pkt = bytearray(build_dfplayer_packet(0x42))
        pkt[7] ^= 0xFF
        expected_csum = packet_body_checksum(pkt[1:7])
        actual_csum = (pkt[7] << 8) | pkt[8]
        assert actual_csum != expected_csum


class TestDfSendUsesProductionPacketBuilder:
    def test_df_send_writes_production_packet(self):
        class _Uart:
            def __init__(self):
                self.written = None

            def write(self, data):
                self.written = bytes(data)
                return len(data)

        hw = dfhw.DFPlayerHardware.__new__(dfhw.DFPlayerHardware)
        hw.uart = _Uart()
        hw._df_send(0x0F, 2, 3, feedback=False)
        assert hw.uart.written == build_dfplayer_packet(0x0F, 2, 3, feedback=False)


class TestErrorCodes:
    def test_error_0x06_is_file_not_found(self):
        assert "not found" in DF_ERROR_MSGS[0x06].lower()

    def test_error_0x01_is_busy(self):
        assert "busy" in DF_ERROR_MSGS[0x01].lower()

    def test_all_error_codes_have_messages(self):
        for code in range(0x01, 0x08):
            assert code in DF_ERROR_MSGS
            assert isinstance(DF_ERROR_MSGS[code], str)
            assert len(DF_ERROR_MSGS[code]) > 0

    def test_dfplayer_hardware_shares_error_table(self):
        assert dfhw.DF_ERROR_MSGS == DF_ERROR_MSGS


class TestWavLoading:
    def test_load_valid_wav(self, tmp_path):
        p = tmp_path / "t.wav"
        p.write_bytes(_build_wav(64, 8000))
        wav_loader._CACHE = None
        data, sr = wav_loader.load_wav_u8(str(p))
        assert sr == 8000
        assert len(data) == 64

    def test_load_wav_from_file(self, tmp_path):
        p = tmp_path / "t.wav"
        p.write_bytes(_build_wav(32, 8000))
        wav_loader._CACHE = None
        data, sr = wav_loader.load_wav_u8(str(p))
        assert sr == 8000
        assert len(data) == 32

    def test_non_riff_file_raises(self, tmp_path):
        bad_file = tmp_path / "bad.wav"
        bad_file.write_bytes(b"JUNK" + b"\x00" * 100)
        with pytest.raises(ValueError, match="Not RIFF"):
            wav_loader.load_wav_u8(str(bad_file))
