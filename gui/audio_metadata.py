"""Audio metadata extraction and hashing utilities."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from mutagen import File as MutagenFile


@dataclass(frozen=True)
class Mp3ProfileCheck:
    """Result of validating an MP3 against a sync conversion profile."""

    ok: bool
    reason: str = ""


def compute_file_hash(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_metadata(file_path: Path) -> Dict[str, Any]:
    title = None
    artist = None
    duration = None
    format_name = file_path.suffix.lower().lstrip(".") or None

    audio = None
    try:
        audio = MutagenFile(file_path, easy=True)
    except Exception:
        # Corrupt file, wrong extension, truncated sync, non-audio data, etc.
        # (e.g. mutagen.mp3.HeaderNotFoundError: can't sync to MPEG frame)
        audio = None
    if audio is not None:
        tags = audio.tags or {}
        title = _first_tag_value(tags, "title")
        artist = _first_tag_value(tags, "artist")
        if audio.info is not None and hasattr(audio.info, "length"):
            try:
                duration = float(audio.info.length)
            except (TypeError, ValueError):
                duration = None
        if not format_name and hasattr(audio, "mime"):
            mime = audio.mime[0] if audio.mime else None
            if mime:
                format_name = mime.split("/")[-1]

    if not title:
        title = file_path.stem

    return {
        "original_filename": file_path.name,
        "file_path": str(file_path),
        "title": title,
        "artist": artist,
        "duration": duration,
        "file_size": file_path.stat().st_size,
        "format": format_name,
    }


def file_matches_metadata(
    file_path: Path, expected_size: Optional[int], expected_hash: Optional[str]
) -> bool:
    if not file_path.exists():
        return False
    if expected_size is not None:
        try:
            if file_path.stat().st_size != expected_size:
                return False
        except OSError:
            return False
    if expected_hash:
        actual_hash = compute_file_hash(file_path)
        if actual_hash != expected_hash:
            return False
    return True


def _first_tag_value(tags: Dict[str, Any], key: str) -> Optional[str]:
    value = tags.get(key)
    if isinstance(value, (list, tuple)) and value:
        return _normalize_str(value[0])
    if isinstance(value, str):
        return _normalize_str(value)
    return None


def _normalize_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_ffprobe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _ffprobe_cli_ok(ffprobe_exe: str) -> bool:
    """True when *ffprobe_exe* behaves like real ffprobe (not a mislinked ffmpeg)."""
    try:
        proc = subprocess.run(
            [ffprobe_exe, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    banner = ((proc.stdout or "") + (proc.stderr or "")).lower()
    return proc.returncode == 0 and "ffprobe" in banner


def _ffmpeg_decode_ok(file_path: Path, ffmpeg_exe: str) -> Optional[str]:
    """Return an error string when ffmpeg cannot decode the file, else None."""
    try:
        proc = subprocess.run(
            [ffmpeg_exe, "-v", "error", "-i", str(file_path), "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"decode check failed: {exc}"
    err = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        return err[:300] or "file could not be decoded"
    return None


def _ffprobe_stream_info(file_path: Path, ffprobe_exe: str) -> Optional[Dict[str, Any]]:
    try:
        proc = subprocess.run(
            [
                ffprobe_exe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels,bit_rate",
                "-of",
                "json",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams") or []
    if not streams:
        return None
    return streams[0]


def _mutagen_mp3_info(file_path: Path) -> Optional[Any]:
    try:
        from mutagen.mp3 import MP3

        return MP3(file_path).info
    except Exception:
        return None


def _mp3_duration_seconds(
    file_path: Path,
    *,
    info: Any = None,
    ffprobe_exe: Optional[str] = None,
) -> Optional[float]:
    """Best-effort duration in seconds for size sanity checks."""
    if info is not None:
        for attr in ("length", "duration"):
            raw = getattr(info, attr, None)
            if raw is not None:
                try:
                    sec = float(raw)
                except (TypeError, ValueError):
                    continue
                if sec > 0:
                    return sec
    if ffprobe_exe and _ffprobe_cli_ok(ffprobe_exe):
        try:
            proc = subprocess.run(
                [
                    ffprobe_exe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout or "{}")
                raw = (payload.get("format") or {}).get("duration")
                if raw is not None:
                    sec = float(raw)
                    if sec > 0:
                        return sec
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
    return None


def _mp3_size_implausible(size: int, duration_sec: Optional[float]) -> Optional[str]:
    """Return an error when *size* is impossibly small for *duration_sec*."""
    if duration_sec is None or duration_sec <= 0.05:
        return None
    # ~32 kbps floor — catches truncated files whose headers claim a long duration.
    min_bytes = max(512, int(duration_sec * 4000))
    if size < min_bytes:
        return (
            f"file size {size} B is too small for {duration_sec:.1f}s of audio "
            "(truncated or corrupt)"
        )
    return None


def _is_cbr_mp3(info: Any) -> bool:
    try:
        from mutagen.mp3 import BitrateMode
    except ImportError:
        BitrateMode = None  # type: ignore[assignment,misc]

    mode = getattr(info, "bitrate_mode", None)
    if BitrateMode is not None and mode is not None:
        if mode in (BitrateMode.VBR, BitrateMode.ABR):
            return False
        if mode == BitrateMode.CBR:
            return True
    # UNKNOWN / missing: allow when sample rate, channels, and bitrate already match.
    return True


def check_mp3_conversion_profile(
    file_path: Path,
    profile: str,
    *,
    ffprobe_exe: Optional[str] = None,
    ffmpeg_exe: Optional[str] = None,
) -> Mp3ProfileCheck:
    """Strict validation for sync skip / post-convert acceptance."""
    if file_path.suffix.lower() != ".mp3":
        return Mp3ProfileCheck(False, "not an MP3 file")
    if profile not in {"dfplayer_safe", "high_quality"}:
        profile = "dfplayer_safe"
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        return Mp3ProfileCheck(False, f"cannot read file: {exc}")
    if size < 512:
        return Mp3ProfileCheck(False, "file too small to be a valid MP3")

    if ffmpeg_exe:
        decode_err = _ffmpeg_decode_ok(file_path, ffmpeg_exe)
        if decode_err:
            return Mp3ProfileCheck(False, decode_err)

    if ffprobe_exe and _ffprobe_cli_ok(ffprobe_exe):
        stream = _ffprobe_stream_info(file_path, ffprobe_exe)
        if stream is not None:
            codec = str(stream.get("codec_name") or "").lower()
            if codec and codec not in {"mp3", "mp3float"}:
                return Mp3ProfileCheck(False, f"codec is {codec}, expected mp3")
            sample_rate = _parse_ffprobe_int(stream.get("sample_rate"))
            channels = _parse_ffprobe_int(stream.get("channels"))
            bit_rate = _parse_ffprobe_int(stream.get("bit_rate"))
            if profile == "high_quality":
                if sample_rate is None or sample_rate < 32_000:
                    return Mp3ProfileCheck(False, f"sample rate {sample_rate} Hz is too low")
                if channels is None or channels < 1:
                    return Mp3ProfileCheck(False, "missing audio channels")
                if bit_rate is None or bit_rate < 160_000:
                    return Mp3ProfileCheck(False, f"bitrate {bit_rate} bps is below 160 kbps")
                return Mp3ProfileCheck(True, "")

            if sample_rate != 44_100:
                return Mp3ProfileCheck(
                    False, f"sample rate {sample_rate} Hz (need 44.1 kHz for DFPlayer-safe)"
                )
            if channels != 2:
                return Mp3ProfileCheck(False, f"{channels or '?'} channel(s) (need stereo)")
            if bit_rate is None or not (112_000 <= bit_rate <= 144_000):
                return Mp3ProfileCheck(
                    False, f"bitrate {bit_rate} bps (need ~128 kbps CBR for DFPlayer-safe)"
                )
            info = _mutagen_mp3_info(file_path)
            if info is not None and not _is_cbr_mp3(info):
                return Mp3ProfileCheck(False, "VBR/ABR MP3 (DFPlayer-safe requires CBR)")
            duration = _mp3_duration_seconds(
                file_path, info=info, ffprobe_exe=ffprobe_exe
            )
            size_err = _mp3_size_implausible(size, duration)
            if size_err:
                return Mp3ProfileCheck(False, size_err)
            return Mp3ProfileCheck(True, "")

    info = _mutagen_mp3_info(file_path)
    if info is None:
        return Mp3ProfileCheck(False, "cannot read MP3 headers (corrupt or unsupported)")

    bitrate = int(getattr(info, "bitrate", 0) or 0)
    sample_rate = int(getattr(info, "sample_rate", 0) or 0)
    channels = int(getattr(info, "channels", 0) or 0)

    if profile == "high_quality":
        if bitrate < 160_000:
            return Mp3ProfileCheck(False, f"bitrate {bitrate} bps is below 160 kbps")
        if channels < 1:
            return Mp3ProfileCheck(False, "missing audio channels")
        if sample_rate < 32_000:
            return Mp3ProfileCheck(False, f"sample rate {sample_rate} Hz is too low")
        return Mp3ProfileCheck(True, "")

    if sample_rate != 44_100:
        return Mp3ProfileCheck(False, f"sample rate {sample_rate} Hz (need 44.1 kHz)")
    if channels != 2:
        return Mp3ProfileCheck(False, f"{channels} channel(s) (need stereo)")
    if not (112_000 <= bitrate <= 144_000):
        return Mp3ProfileCheck(False, f"bitrate {bitrate} bps (need ~128 kbps CBR)")
    if not _is_cbr_mp3(info):
        return Mp3ProfileCheck(False, "VBR/ABR MP3 (DFPlayer-safe requires CBR)")
    duration = _mp3_duration_seconds(
        file_path, info=info, ffprobe_exe=ffprobe_exe
    )
    size_err = _mp3_size_implausible(size, duration)
    if size_err:
        return Mp3ProfileCheck(False, size_err)
    return Mp3ProfileCheck(True, "")


def mp3_matches_conversion_profile(file_path: Path, profile: str) -> bool:
    """Return True when an MP3 already matches the selected sync encode profile."""
    return check_mp3_conversion_profile(file_path, profile).ok

