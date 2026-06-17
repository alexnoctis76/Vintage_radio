from __future__ import annotations

import wave
from pathlib import Path

import pytest


def _write_test_wav_8bit_mono(path: Path, sr: int = 8000, n: int = 800) -> None:
    """Short silence-ish WAV for reference load tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(sr)
        data = bytes([128 + (i % 11) for i in range(n)])
        w.writeframes(data)


def test_analyze_recording_sine_correlates_with_self():
    np = pytest.importorskip("numpy")
    from gui.mcp_line_in_analysis import analyze_recording

    sr = 8000
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    x = (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    r = analyze_recording(x, sr, reference_mono=x.copy(), reference_sr=sr)
    assert "summary" in r
    assert r["summary"]["frames"] == sr
    rc = r["reference_compare"]
    assert rc.get("loaded") is True
    assert rc.get("envelope_pearson_r") is not None
    assert rc["envelope_pearson_r"] > 0.99


def test_analyze_windows(tmp_path: Path):
    np = pytest.importorskip("numpy")
    from gui.mcp_line_in_analysis import analyze_recording

    sr = 1000
    x = np.zeros(sr, dtype=np.float32)
    x[100:300] = 0.5
    x[600:900] = -0.3
    r = analyze_recording(
        x,
        sr,
        windows=[
            {"name": "quiet", "start_s": 0.0, "end_s": 0.05},
            {"name": "loud", "start_s": 0.1, "end_s": 0.3},
        ],
    )
    assert len(r["windows"]) == 2
    assert r["windows"][0]["name"] == "quiet"
    assert r["windows"][0]["rms_dbfs"] < r["windows"][1]["rms_dbfs"]


def test_load_wav_mono_float_8bit(tmp_path: Path):
    pytest.importorskip("numpy")
    from gui.mcp_line_in_analysis import load_wav_mono_float

    p = tmp_path / "t.wav"
    _write_test_wav_8bit_mono(p, sr=8000, n=400)
    x, sr = load_wav_mono_float(p)
    assert sr == 8000
    assert len(x) == 400

