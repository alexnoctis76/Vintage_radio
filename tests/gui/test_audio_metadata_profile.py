from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gui.audio_metadata import (
    Mp3ProfileCheck,
    check_mp3_conversion_profile,
    mp3_matches_conversion_profile,
)


@pytest.fixture
def mp3_path(tmp_path: Path) -> Path:
    path = tmp_path / "track.mp3"
    path.write_bytes(b"x" * 1024)
    return path


def test_mp3_matches_dfplayer_safe_profile(mp3_path: Path):
    info = SimpleNamespace(bitrate=128_000, sample_rate=44100, channels=2, bitrate_mode=1)
    with patch("gui.audio_metadata._mutagen_mp3_info", return_value=info):
        with patch("gui.audio_metadata._is_cbr_mp3", return_value=True):
            assert mp3_matches_conversion_profile(mp3_path, "dfplayer_safe")


def test_mp3_rejects_wrong_sample_rate_for_dfplayer_safe(mp3_path: Path):
    info = SimpleNamespace(bitrate=128_000, sample_rate=48000, channels=2, bitrate_mode=1)
    with patch("gui.audio_metadata._mutagen_mp3_info", return_value=info):
        assert not mp3_matches_conversion_profile(mp3_path, "dfplayer_safe")


def test_mp3_rejects_vbr_for_dfplayer_safe(mp3_path: Path):
    info = SimpleNamespace(bitrate=128_000, sample_rate=44100, channels=2, bitrate_mode=2)
    with patch("gui.audio_metadata._mutagen_mp3_info", return_value=info):
        with patch("gui.audio_metadata._is_cbr_mp3", return_value=False):
            check = check_mp3_conversion_profile(mp3_path, "dfplayer_safe")
            assert not check.ok
            assert "VBR" in check.reason or "CBR" in check.reason


def test_mp3_matches_high_quality_profile(mp3_path: Path):
    info = SimpleNamespace(bitrate=192_000, sample_rate=44100, channels=2, bitrate_mode=2)
    with patch("gui.audio_metadata._mutagen_mp3_info", return_value=info):
        assert mp3_matches_conversion_profile(mp3_path, "high_quality")


def test_mp3_rejects_low_bitrate_for_high_quality(mp3_path: Path):
    info = SimpleNamespace(bitrate=128_000, sample_rate=44100, channels=2, bitrate_mode=1)
    with patch("gui.audio_metadata._mutagen_mp3_info", return_value=info):
        assert not mp3_matches_conversion_profile(mp3_path, "high_quality")


def test_mp3_rejects_truncated_file_with_long_header_duration(tmp_path: Path):
    mp3 = tmp_path / "trunc.mp3"
    mp3.write_bytes(b"x" * 1024)
    info = SimpleNamespace(bitrate=128_000, sample_rate=44100, channels=2, bitrate_mode=1, length=2.5)
    with patch("gui.audio_metadata._ffmpeg_decode_ok", return_value=None):
        with patch("gui.audio_metadata._ffprobe_cli_ok", return_value=True):
            with patch("gui.audio_metadata._ffprobe_stream_info") as probe:
                probe.return_value = {
                    "codec_name": "mp3",
                    "sample_rate": "44100",
                    "channels": "2",
                    "bit_rate": "128000",
                }
                with patch("gui.audio_metadata._mutagen_mp3_info", return_value=info):
                    with patch("gui.audio_metadata._is_cbr_mp3", return_value=True):
                        with patch(
                            "gui.audio_metadata._mp3_duration_seconds", return_value=2.5
                        ):
                            result = check_mp3_conversion_profile(
                                mp3,
                                "dfplayer_safe",
                                ffprobe_exe="ffprobe",
                                ffmpeg_exe="ffmpeg",
                            )
    assert not result.ok
    assert "too small" in result.reason.lower()


def test_ffprobe_path_used_when_available(tmp_path: Path):
    mp3 = tmp_path / "ok.mp3"
    mp3.write_bytes(b"x" * 1024)
    with patch("gui.audio_metadata._ffmpeg_decode_ok", return_value=None):
        with patch("gui.audio_metadata._ffprobe_cli_ok", return_value=True):
            with patch("gui.audio_metadata._ffprobe_stream_info") as probe:
                probe.return_value = {
                    "codec_name": "mp3",
                    "sample_rate": "44100",
                    "channels": "2",
                    "bit_rate": "128000",
                }
                with patch("gui.audio_metadata._mutagen_mp3_info") as mut:
                    mut.return_value = SimpleNamespace(bitrate_mode=1)
                    with patch("gui.audio_metadata._is_cbr_mp3", return_value=True):
                        result = check_mp3_conversion_profile(
                            mp3,
                            "dfplayer_safe",
                            ffprobe_exe="ffprobe",
                            ffmpeg_exe="ffmpeg",
                        )
    assert isinstance(result, Mp3ProfileCheck)
    assert result.ok
