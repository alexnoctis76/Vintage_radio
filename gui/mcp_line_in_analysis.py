"""Line-in capture and numeric audio analysis for MCP / automated regression.

Turns DFPlayer/amp line-in audio into JSON-friendly metrics an agent can reason about:
RMS, peaks, zero-crossing rate, coarse spectral centroid, envelope correlation vs a
reference WAV (e.g. gui/resources/AMradioSound.wav used on the Pico).

Requires optional packages: ``numpy``, ``sounddevice`` (``pip install numpy sounddevice``).
"""

from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

JsonDict = Dict[str, Any]


def _need_audio_stack() -> Tuple[Any, Any]:
    try:
        import numpy as np
    except ImportError as e:
        raise ImportError(
            "mcp_line_in_analysis requires numpy. Install with: pip install numpy"
        ) from e
    try:
        import sounddevice as sd
    except ImportError as e:
        raise ImportError(
            "mcp_line_in_analysis requires sounddevice. "
            "Install with: pip install sounddevice"
        ) from e
    return np, sd


def list_input_devices() -> JsonDict:
    """Return host input devices (index + name + default sample rate)."""
    try:
        _, sd = _need_audio_stack()
    except ImportError as e:
        return {"ok": False, "error": "missing_dependency", "detail": str(e)}
    try:
        devices = sd.query_devices()
        default_in = sd.default.device[0] if sd.default.device else None
        out = []
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                out.append(
                    {
                        "index": i,
                        "name": d.get("name", ""),
                        "channels": int(d.get("max_input_channels", 0)),
                        "default_sr": float(d.get("default_samplerate", 0) or 0),
                    }
                )
        return {
            "ok": True,
            "default_input_index": default_in,
            "devices": out,
        }
    except Exception as e:
        return {"ok": False, "error": "query_devices_failed", "detail": str(e)}


def load_wav_mono_float(path: Path) -> Tuple[Any, int]:
    """Load WAV as mono float32 roughly in [-1, 1]. Returns (numpy 1d array, sample_rate)."""
    np, _ = _need_audio_stack()
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    with wave.open(str(p), "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw == 1:
        u = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        x = (u - 128.0) / 128.0
        if ch == 2:
            x = x.reshape(-1, 2).mean(axis=1)
    elif sw == 2:
        s = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if ch == 2:
            s = s.reshape(-1, 2).mean(axis=1)
        x = s
    else:
        raise ValueError("unsupported WAV sample width: {}".format(sw))
    return x, int(sr)


def resample_linear(x: Any, src_sr: int, dst_sr: int) -> Any:
    np, _ = _need_audio_stack()
    if src_sr == dst_sr or len(x) < 2:
        return x.astype(np.float32)
    ratio = float(dst_sr) / float(src_sr)
    n_out = max(2, int(round(len(x) * ratio)))
    t_old = np.linspace(0.0, 1.0, num=len(x), endpoint=False)
    t_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(t_new, t_old, x.astype(np.float32)).astype(np.float32)


def _rms_dbfs(x: Any) -> float:
    np, _ = _need_audio_stack()
    if len(x) == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(x), dtype=np.float64)))
    if rms <= 1e-12:
        return -120.0
    return 20.0 * math.log10(rms + 1e-12)


def _zero_crossing_rate(x: Any, sr: int) -> float:
    np, _ = _need_audio_stack()
    if len(x) < 2:
        return 0.0
    s = np.sign(x[1:]) - np.sign(x[:-1])
    zc = float(np.sum(np.abs(s) > 1))
    return zc / max(len(x) - 1, 1) * float(sr)


def _spectral_centroid_hz(x: Any, sr: int) -> float:
    """Very light-weight centroid via first-difference energy (no FFT dependency)."""
    np, _ = _need_audio_stack()
    if len(x) < 8:
        return 0.0
    d = np.diff(x.astype(np.float64))
    spec = np.fft.rfft(d)
    mag = np.abs(spec)
    freqs = np.fft.rfftfreq(len(d), d=1.0 / float(sr))
    s = float(np.sum(mag))
    if s < 1e-18:
        return 0.0
    return float(np.sum(freqs * mag) / s)


def _envelope(x: Any, win: int) -> Any:
    np, _ = _need_audio_stack()
    ax = np.abs(x.astype(np.float64))
    if win < 3:
        return ax
    k = np.ones(win, dtype=np.float64) / float(win)
    return np.convolve(ax, k, mode="same")


def _corr(a: Any, b: Any) -> float:
    np, _ = _need_audio_stack()
    n = min(len(a), len(b))
    if n < 8:
        return float("nan")
    aa = a[:n] - np.mean(a[:n])
    bb = b[:n] - np.mean(b[:n])
    da = float(np.sqrt(np.sum(aa * aa)))
    db = float(np.sqrt(np.sum(bb * bb)))
    if da < 1e-12 or db < 1e-12:
        return float("nan")
    return float(np.sum(aa * bb) / (da * db))


def _downsample_maxhold(x: Any, bins: int) -> List[int]:
    np, _ = _need_audio_stack()
    if len(x) == 0 or bins < 1:
        return []
    n = len(x)
    out: List[int] = []
    for i in range(bins):
        lo = i * n // bins
        hi = (i + 1) * n // bins
        if hi <= lo:
            hi = lo + 1
        chunk = np.abs(x[lo:hi])
        peak = float(np.max(chunk)) if chunk.size else 0.0
        out.append(int(min(1000, round(peak * 1000))))
    return out


def analyze_recording(
    samples: Any,
    sample_rate: int,
    *,
    windows: Optional[List[JsonDict]] = None,
    reference_mono: Optional[Any] = None,
    reference_sr: int = 0,
    envelope_bins: int = 64,
) -> JsonDict:
    """Pure analysis on float32 mono samples (numpy array)."""
    np, _ = _need_audio_stack()
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    sr = int(sample_rate)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    summary = {
        "frames": int(len(x)),
        "duration_s": round(len(x) / float(sr), 4) if sr else 0.0,
        "peak_linear": round(peak, 6),
        "rms_dbfs": round(_rms_dbfs(x), 2),
        "zero_crossing_per_s": round(_zero_crossing_rate(x, sr), 1),
        "spectral_centroid_hz": round(_spectral_centroid_hz(x, sr), 1),
    }
    win_specs = windows or []
    segments = []
    for w in win_specs:
        if not isinstance(w, dict):
            continue
        name = str(w.get("name", "window"))
        try:
            t0 = float(w.get("start_s", 0.0))
            t1 = float(w.get("end_s", 0.0))
        except (TypeError, ValueError):
            continue
        i0 = max(0, int(t0 * sr))
        i1 = min(len(x), int(t1 * sr))
        if i1 <= i0:
            segments.append(
                {
                    "name": name,
                    "ok": False,
                    "error": "empty_window",
                    "start_s": t0,
                    "end_s": t1,
                }
            )
            continue
        seg = x[i0:i1]
        segments.append(
            {
                "name": name,
                "ok": True,
                "start_s": t0,
                "end_s": t1,
                "rms_dbfs": round(_rms_dbfs(seg), 2),
                "peak_linear": round(float(np.max(np.abs(seg))), 6),
                "zero_crossing_per_s": round(_zero_crossing_rate(seg, sr), 1),
                "spectral_centroid_hz": round(_spectral_centroid_hz(seg, sr), 1),
            }
        )

    ref_block: JsonDict = {"loaded": False}
    if reference_mono is not None and reference_sr > 0 and len(x) > 64:
        ref = resample_linear(reference_mono, reference_sr, sr)
        n = min(len(x), len(ref))
        if n > 256:
            env_win = max(3, sr // 200)
            ex = _envelope(x[:n], env_win)
            er = _envelope(ref[:n], env_win)
            ex = ex / (float(np.max(ex)) + 1e-9)
            er = er / (float(np.max(er)) + 1e-9)
            c = _corr(ex, er)
            mse = float(np.mean(np.square(ex - er)))
            ref_block = {
                "loaded": True,
                "reference_frames_used": n,
                "envelope_pearson_r": round(c, 4) if not math.isnan(c) else None,
                "envelope_mse": round(mse, 6),
                "interpretation": (
                    "higher_r_lower_mse means captured line-in envelope tracks reference WAV"
                ),
            }

    preview = _downsample_maxhold(x, envelope_bins)
    return {
        "summary": summary,
        "windows": segments,
        "reference_compare": ref_block,
        "envelope_preview_0_1000": preview,
    }


def capture_and_analyze(
    *,
    duration_s: float = 5.0,
    sample_rate: int = 48000,
    device: Optional[int] = None,
    reference_wav: Optional[str] = None,
    windows: Optional[List[JsonDict]] = None,
) -> JsonDict:
    """Record from line-in (or chosen input), then analyze. Blocking call."""
    np, sd = _need_audio_stack()
    duration_s = max(0.05, min(float(duration_s), 120.0))
    sample_rate = int(sample_rate)
    if sample_rate < 8000 or sample_rate > 192000:
        return {"ok": False, "error": "bad_sample_rate"}

    ref_arr = None
    ref_sr = 0
    ref_path = None
    if reference_wav:
        try:
            ref_path = str(Path(reference_wav).expanduser().resolve())
            ref_arr, ref_sr = load_wav_mono_float(Path(ref_path))
        except Exception as e:
            return {
                "ok": False,
                "error": "reference_load_failed",
                "detail": str(e),
                "path": reference_wav,
            }

    frames = int(round(duration_s * sample_rate))
    try:
        dev_name = ""
        in_ch = 1
        if device is not None:
            info = sd.query_devices(int(device))
            dev_name = str(info.get("name", ""))
            in_ch = int(info.get("max_input_channels", 1) or 1)
        else:
            di = sd.default.device[0]
            if di is not None:
                info = sd.query_devices(int(di))
                dev_name = str(info.get("name", ""))
                in_ch = int(info.get("max_input_channels", 1) or 1)
        # Stereo line-in: recording with channels=1 often maps only the left channel.
        # A mono TS plug or TRS wired to the right channel then reads as silence.
        use_ch = 2 if in_ch >= 2 else 1
        rec = sd.rec(
            frames,
            samplerate=sample_rate,
            channels=use_ch,
            dtype="float32",
            device=device,
        )
        sd.wait()
    except Exception as e:
        return {"ok": False, "error": "record_failed", "detail": str(e)}

    arr = np.asarray(rec, dtype=np.float32)
    if arr.ndim == 2 and arr.shape[1] >= 2:
        L = arr[:, 0].astype(np.float64)
        R = arr[:, 1].astype(np.float64)
        rl = float(np.sqrt(np.mean(L * L)))
        rr = float(np.sqrt(np.mean(R * R)))
        # Pick the louder channel (typical when one side is unused or floating).
        x = (L if rl >= rr else R).astype(np.float32)
    else:
        x = arr.reshape(-1).astype(np.float32)
    analysis = analyze_recording(
        x,
        sample_rate,
        windows=windows,
        reference_mono=ref_arr,
        reference_sr=ref_sr,
    )
    return {
        "ok": True,
        "capture": {
            "sample_rate": sample_rate,
            "duration_s": round(duration_s, 4),
            "device_index": device,
            "device_name": dev_name,
            "reference_path": ref_path,
        },
        **analysis,
    }

