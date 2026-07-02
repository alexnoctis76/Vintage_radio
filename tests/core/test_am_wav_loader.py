"""Host tests for AM WAV loader."""

from __future__ import annotations

import struct
import sys
import types

if "ustruct" not in sys.modules:
    ustruct = types.ModuleType("ustruct")
    ustruct.unpack = struct.unpack
    ustruct.unpack_from = struct.unpack_from
    sys.modules["ustruct"] = ustruct

from firmware.pico.components import am_wav_loader as loader  # noqa: E402


def _build_wav(num_frames: int, samplerate: int = 8000) -> bytes:
    fmt = struct.pack("<HHIIHH", 1, 1, samplerate, samplerate, 1, 8)
    data = bytes([128 + (i % 16) for i in range(num_frames)])
    body = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + b"WAVE" + body


class TestAmWavLoader:
    def test_full_load_keeps_samplerate(self, tmp_path):
        p = tmp_path / "t.wav"
        p.write_bytes(_build_wav(8000, 8000))
        loader._CACHE = None
        data, sr = loader.load_wav_u8(str(p))
        assert sr == 8000
        assert len(data) == 8000

    def test_truncate_keeps_samplerate_not_decimation(self, monkeypatch, tmp_path):
        p = tmp_path / "t.wav"
        p.write_bytes(_build_wav(37565, 8000))
        calls = {"n": 0}
        orig = loader._read_data_bytes

        def flaky(f, nbytes):
            calls["n"] += 1
            if calls["n"] == 1:
                raise MemoryError
            return orig(f, 12000)

        monkeypatch.setattr(loader, "_read_data_bytes", flaky)
        loader._CACHE = None
        data, sr = loader.load_wav_u8(str(p))
        assert sr == 8000
        assert len(data) == 12000
