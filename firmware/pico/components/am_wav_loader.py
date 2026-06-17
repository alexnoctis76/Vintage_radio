"""AM static WAV loader — import and call load_am_wav_cache() *before* radio_core on Pico.

radio_core + DFPlayerHardware consume a lot of RAM; loading the WAV first avoids
MemoryError → decimated ~6k-sample buffers (muddy PWM static).
"""

import os
import time
import ustruct

try:
    import gc
except Exception:
    gc = None

try:
    import ujson as json
except ImportError:
    import json

WAV_FILE = "VintageRadio/AMradioSound.wav"
MAX_AM_WAV_SAMPLES = 48000

AM_TRY_PATHS = (
    "/VintageRadio/AMradioSound.wav",
    WAV_FILE,
    "/" + WAV_FILE,
    "AMradioSound.wav",
)

_CACHE = None


def _extract_u8_from_frame(frame, bits_per_sample):
    if bits_per_sample == 8:
        return frame[0]
    if bits_per_sample == 16:
        s = ustruct.unpack_from("<h", frame, 0)[0]
        u8 = (s + 32768) >> 8
        if u8 < 0:
            u8 = 0
        elif u8 > 255:
            u8 = 255
        return u8
    raise ValueError("unsupported bits_per_sample {}".format(bits_per_sample))


def _read_wav_data_compact(f, data_bytes, channels, bits_per_sample, target_samples=MAX_AM_WAV_SAMPLES):
    frame_bytes = channels * (bits_per_sample // 8)
    if frame_bytes <= 0:
        raise ValueError("invalid frame size")
    total_frames = data_bytes // frame_bytes
    if total_frames <= 0:
        return b""
    step = 1
    if total_frames > target_samples:
        step = (total_frames + target_samples - 1) // target_samples

    n_out = (total_frames + step - 1) // step
    out = bytearray(n_out)
    out_idx = 0
    remaining = data_bytes
    frame_index = 0
    block_size = frame_bytes * 512
    frame_stride = bits_per_sample // 8
    while remaining > 0:
        take = block_size if remaining > block_size else remaining
        block = f.read(take)
        if not block:
            break
        n = len(block)
        pos = 0
        while pos + frame_bytes <= n:
            if frame_index % step == 0 and out_idx < n_out:
                out[out_idx] = _extract_u8_from_frame(
                    block[pos : pos + frame_stride], bits_per_sample
                )
                out_idx += 1
            frame_index += 1
            pos += frame_bytes
        remaining -= n
    if out_idx != n_out:
        return memoryview(out)[:out_idx]
    return memoryview(out)


def load_wav_u8(path):
    """Load WAV and return (unsigned 8-bit mono bytes, samplerate)."""
    wav_target_cap = MAX_AM_WAV_SAMPLES
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF":
            raise ValueError("not RIFF")
        f.read(4)
        if f.read(4) != b"WAVE":
            raise ValueError("not WAVE")

        samplerate = 8000
        audio_fmt = 1
        channels = 1
        bits_per_sample = 8
        data = None

        while True:
            cid = f.read(4)
            if not cid:
                break
            sz_raw = f.read(4)
            if len(sz_raw) < 4:
                raise ValueError("truncated chunk header")
            clen = ustruct.unpack("<I", sz_raw)[0]
            if cid == b"fmt ":
                chunk = f.read(clen)
                if len(chunk) != clen:
                    raise ValueError("truncated chunk data")
                if clen < 16:
                    raise ValueError("invalid fmt chunk")
                audio_fmt, channels, samplerate = ustruct.unpack_from("<HHI", chunk, 0)
                bits_per_sample = ustruct.unpack_from("<H", chunk, 14)[0]
            elif cid == b"data":
                denom = max(1, channels * (bits_per_sample // 8))
                total = clen // denom
                target_samples = MAX_AM_WAV_SAMPLES
                data_start_pos = f.tell()
                mem_retry_same = True
                while True:
                    try:
                        if gc is not None:
                            gc.collect()
                        f.seek(data_start_pos)
                        data = _read_wav_data_compact(
                            f, clen, channels, bits_per_sample, target_samples=target_samples
                        )
                        wav_target_cap = target_samples
                        break
                    except MemoryError:
                        if mem_retry_same:
                            mem_retry_same = False
                            if gc is not None:
                                gc.collect()
                                gc.collect()
                            continue
                        target_samples = max(1024, (target_samples * 3) // 4)
                        if target_samples < 1024:
                            raise
                        print(
                            "AM WAV debug: compact load retry with target_samples={}".format(
                                target_samples
                            )
                        )
                if len(data) < 1:
                    raise ValueError("empty data chunk")
                if total > target_samples:
                    step = (total + target_samples - 1) // target_samples
                    samplerate = max(1000, samplerate // step)
            else:
                f.seek(clen, 1)
            if clen & 1:
                f.read(1)

        if data is None:
            raise ValueError("no data chunk")
        if audio_fmt != 1:
            raise ValueError("unsupported WAV encoding {}".format(audio_fmt))
        if channels not in (1, 2):
            raise ValueError("unsupported channel count {}".format(channels))

        if bits_per_sample in (8, 16):
            try:
                print(
                    "#VRDBG "
                    + json.dumps(
                        {
                            "sessionId": "e8231e",
                            "hypothesisId": "AM1",
                            "location": "am_wav_loader.load_wav_u8",
                            "message": "wav_loaded",
                            "data": {
                                "samples": len(data),
                                "sr": int(samplerate),
                                "target_cap": int(wav_target_cap),
                            },
                            "timestamp": time.ticks_ms(),
                        }
                    )
                )
            except Exception:
                pass
            return data, samplerate

        raise ValueError("unsupported bits_per_sample {}".format(bits_per_sample))


def load_am_wav_cache():
    """Load once; return (wav_bytes_or_None, sample_rate, path_or_None)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    try:
        if gc is not None:
            gc.collect()
        root_entries = os.listdir("/")
        print("AM WAV debug: '/' entries =", root_entries)
        if "VintageRadio" in root_entries:
            try:
                vr_entries = os.listdir("/VintageRadio")
                print("AM WAV debug: '/VintageRadio' entries =", vr_entries)
            except Exception as e:
                print("AM WAV debug: cannot list /VintageRadio:", e)
    except Exception as e:
        print("AM WAV debug: cannot list root:", e)

    for path in AM_TRY_PATHS:
        try:
            print("AM WAV debug: trying path:", path)
            d, sr = load_wav_u8(path)
            _CACHE = (d, sr, path)
            print("AM WAV loaded from Pico flash: {} -> PWM overlay enabled".format(path))
            return _CACHE
        except Exception as e:
            print("AM WAV debug: load failed for {}: {}".format(path, e))

    _CACHE = (None, 8000, None)
    return _CACHE
