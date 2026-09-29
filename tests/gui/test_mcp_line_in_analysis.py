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


def test_analyze_recording_constant_rms_matches_independent_formula():
    """RMS dBFS must match hand-computed 20*log10(amplitude), not only relative ordering."""
    import math

    np = pytest.importorskip("numpy")
    from gui.mcp_line_in_analysis import analyze_recording

    amplitude = 0.25
    sr = 8000
    x = np.full(sr, amplitude, dtype=np.float32)
    expected_rms_dbfs = round(20.0 * math.log10(amplitude), 2)

    result = analyze_recording(x, sr)
    assert result["summary"]["rms_dbfs"] == pytest.approx(expected_rms_dbfs, abs=0.02)


def test_analyze_recording_envelope_pearson_matches_independent_computation():
    np = pytest.importorskip("numpy")
    from gui.mcp_line_in_analysis import analyze_recording

    def _envelope_abs_ma(x: np.ndarray, win: int) -> np.ndarray:
        ax = np.abs(x.astype(np.float64))
        if win < 3:
            return ax
        kernel = np.ones(win, dtype=np.float64) / float(win)
        return np.convolve(ax, kernel, mode="same")

    def _pearson(a: np.ndarray, b: np.ndarray) -> float:
        n = min(len(a), len(b))
        aa = a[:n] - np.mean(a[:n])
        bb = b[:n] - np.mean(b[:n])
        da = float(np.sqrt(np.sum(aa * aa)))
        db = float(np.sqrt(np.sum(bb * bb)))
        if da < 1e-12 or db < 1e-12:
            return float("nan")
        return float(np.sum(aa * bb) / (da * db))

    sr = 8000
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    signal = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    reference = (0.27 * np.sin(2 * np.pi * 440.0 * t + 0.15)).astype(np.float32)

    env_win = max(3, sr // 200)
    ex = _envelope_abs_ma(signal, env_win)
    er = _envelope_abs_ma(reference, env_win)
    ex = ex / (float(np.max(ex)) + 1e-9)
    er = er / (float(np.max(er)) + 1e-9)
    expected_r = round(_pearson(ex, er), 4)

    result = analyze_recording(signal, sr, reference_mono=reference, reference_sr=sr)
    actual_r = result["reference_compare"]["envelope_pearson_r"]
    assert actual_r == pytest.approx(expected_r, abs=0.001)
    assert actual_r > 0.9


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


def test_capture_and_analyze_happy_path_with_fake_device(monkeypatch):
    np = pytest.importorskip("numpy")
    sd = pytest.importorskip("sounddevice")
    import gui.mcp_line_in_analysis as mia

    monkeypatch.setattr(
        sd, "query_devices", lambda idx: {"name": "fake healthy device", "max_input_channels": 2}
    )
    monkeypatch.setattr(
        sd, "rec", lambda frames, **kwargs: np.full((frames, 2), 0.1, dtype=np.float32)
    )
    monkeypatch.setattr(sd, "wait", lambda: None)

    result = mia.capture_and_analyze(duration_s=0.05, sample_rate=8000, device=0)
    assert result["ok"] is True
    assert result["capture"]["device_name"] == "fake healthy device"
    assert result["summary"]["frames"] > 0

