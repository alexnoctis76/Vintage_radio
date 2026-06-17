from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gui.audio_metadata import mp3_matches_conversion_profile


def test_mp3_matches_dfplayer_safe_profile():
    info = SimpleNamespace(bitrate=128_000, sample_rate=44100, channels=2)
    with patch("mutagen.mp3.MP3", return_value=SimpleNamespace(info=info)):
        assert mp3_matches_conversion_profile(Path("track.mp3"), "dfplayer_safe")


def test_mp3_rejects_wrong_sample_rate_for_dfplayer_safe():
    info = SimpleNamespace(bitrate=128_000, sample_rate=48000, channels=2)
    with patch("mutagen.mp3.MP3", return_value=SimpleNamespace(info=info)):
        assert not mp3_matches_conversion_profile(Path("track.mp3"), "dfplayer_safe")


def test_mp3_matches_high_quality_profile():
    info = SimpleNamespace(bitrate=192_000, sample_rate=44100, channels=2)
    with patch("mutagen.mp3.MP3", return_value=SimpleNamespace(info=info)):
        assert mp3_matches_conversion_profile(Path("track.mp3"), "high_quality")


def test_mp3_rejects_low_bitrate_for_high_quality():
    info = SimpleNamespace(bitrate=128_000, sample_rate=44100, channels=2)
    with patch("mutagen.mp3.MP3", return_value=SimpleNamespace(info=info)):
        assert not mp3_matches_conversion_profile(Path("track.mp3"), "high_quality")
