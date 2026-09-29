"""AM static WAV loader for Pico PWM overlay.

Call load_am_wav_cache() after radio_core import, before DFPlayerHardware().

Uses v1.0.0 load (full data chunk at native rate). If heap is tight, truncates
the clip from the start — never decimates samples and never lowers sample rate.
Decimation / slow playback rate both produced bad-sounding static on Pico.
"""

import ustruct

try:
    import gc
except Exception:
    gc = None

WAV_FILE = "VintageRadio/AMradioSound.wav"

AM_TRY_PATHS = (
    "/VintageRadio/AMradioSound.wav",
    WAV_FILE,
    "/" + WAV_FILE,
    "AMradioSound.wav",
)

_CACHE = None


def _read_data_bytes(f, nbytes):
    """Read exactly nbytes from current file position into a bytearray."""
    out = bytearray(nbytes)
    pos = 0
    while pos < nbytes:
        take = min(nbytes - pos, 2048)
        chunk = f.read(take)
        if not chunk:
            break
        n = len(chunk)
        out[pos : pos + n] = chunk
        pos += n
    if pos < 1:
        raise ValueError("empty data chunk")
    if pos < nbytes:
        return memoryview(out)[:pos]
    return memoryview(out)


def load_wav_u8(path):
    """Load WAV; return (u8 sample bytes, native samplerate)."""
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF":
            raise ValueError("Not RIFF")
        f.read(4)
        if f.read(4) != b"WAVE":
            raise ValueError("Not WAVE")

        samplerate = 8000
        data = None

        while True:
            cid = f.read(4)
            if not cid:
                raise ValueError("No data chunk")
            clen = ustruct.unpack("<I", f.read(4))[0]
            if cid == b"fmt ":
                fmt = f.read(clen)
                if len(fmt) >= 8:
                    samplerate = ustruct.unpack("<I", fmt[4:8])[0]
            elif cid == b"data":
                data_start = f.tell()
                nbytes = clen
                mem_retry = True
                while True:
                    try:
                        if gc is not None:
                            gc.collect()
                        f.seek(data_start)
                        data = _read_data_bytes(f, nbytes)
                        break
                    except MemoryError:
                        if mem_retry:
                            mem_retry = False
                            if gc is not None:
                                gc.collect()
                                gc.collect()
                            continue
                        if nbytes <= 1024:
                            raise
                        nbytes = max(1024, (nbytes * 3) // 4)
                        print(
                            "AM WAV: truncate retry nbytes={} (sr stays {})".format(
                                nbytes, samplerate
                            )
                        )
                if nbytes < clen:
                    print(
                        "AM WAV: using first {} of {} bytes at {}Hz".format(
                            len(data), clen, samplerate
                        )
                    )
                break
            else:
                f.seek(clen, 1)

    return data, samplerate


def load_am_wav_cache():
    """Load once; return (wav_bytes_or_None, sample_rate, path_or_None)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    if gc is not None:
        gc.collect()
        print("AM WAV: mem_free before load = {}".format(gc.mem_free()))

    for path in AM_TRY_PATHS:
        try:
            d, sr = load_wav_u8(path)
            _CACHE = (d, sr, path)
            print("AM WAV loaded: {} ({} samples, {}Hz)".format(path, len(d), sr))
            return _CACHE
        except Exception as e:
            print("AM WAV load failed for {}: {}".format(path, e))

    _CACHE = (None, 8000, None)
    return _CACHE
