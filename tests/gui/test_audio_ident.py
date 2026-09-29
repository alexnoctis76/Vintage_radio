"""Tests for the acoustic track ident used by the commercials acceptance suites.

The important property is not that the codec round-trips in memory, but that the
pilot tones still decode after the audio has been through the real DFPlayer-safe
ffmpeg conversion. If LAME's psychoacoustic model discarded them, every acoustic
assertion in the device suites would silently degrade to "something was playing".
"""

from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import pytest

from gui import audio_ident

np = pytest.importorskip("numpy")

SAMPLE_RATE = 44100


def _ffmpeg_or_skip() -> str:
    from gui.resource_paths import resolve_ffmpeg_executable

    exe = resolve_ffmpeg_executable()
    if not exe:
        pytest.skip("ffmpeg unavailable")
    return exe


def _synth_with_pilots(folder: int, track: int, seconds: float = 2.0) -> "np.ndarray":
    """Band-limited music plus the ident pilots, mirroring the generator."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    music = np.zeros_like(t)
    for freq, amp in ((196.0, 1.0), (392.0, 0.5), (588.0, 0.25), (1176.0, 0.12)):
        music += amp * np.sin(2.0 * math.pi * freq * t)
    music = music / np.max(np.abs(music)) * 0.75

    f_hz, t_hz = audio_ident.ident_tones(folder, track)
    pilots = audio_ident.PILOT_AMPLITUDE * (
        np.sin(2.0 * math.pi * f_hz * t) + np.sin(2.0 * math.pi * t_hz * t)
    )
    return np.clip(music + pilots, -1.0, 1.0)


def _ident_pair(folder: int, track: int):
    f_hz, t_hz = audio_ident.ident_tones(folder, track)
    return round(f_hz, 1), round(t_hz, 1)


def _write_wav(path: Path, audio: "np.ndarray") -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


class TestIdentCodec:
    def test_tones_round_trip_for_every_slot(self):
        folders = list(range(1, audio_ident.COMMERCIALS_SLOT + 1)) + [
            audio_ident.COMMERCIALS_FOLDER
        ]
        for folder in folders:
            for track in range(1, audio_ident.SLOTS + 1):
                f_hz, t_hz = audio_ident.ident_tones(folder, track)
                assert audio_ident.decode_tones(f_hz, t_hz) == (folder, track)

    def test_commercials_folder_is_distinguishable_from_stations(self):
        ad_hz, _ = audio_ident.ident_tones(audio_ident.COMMERCIALS_FOLDER, 1)
        for folder in range(1, audio_ident.COMMERCIALS_SLOT + 1):
            station_hz, _ = audio_ident.ident_tones(folder, 1)
            assert abs(ad_hz - station_hz) > audio_ident.MATCH_TOLERANCE_HZ * 2

    def test_out_of_range_ids_are_rejected(self):
        with pytest.raises(audio_ident.IdentError):
            audio_ident.ident_tones(50, 1)
        with pytest.raises(audio_ident.IdentError):
            audio_ident.ident_tones(1, 99)

    def test_no_pilot_harmonic_lands_inside_the_band(self):
        # Amplifier distortion doubles tones; if 2*lowest fell inside the band it
        # could be misread as a different slot.
        assert 2.0 * audio_ident.BAND_LOW_HZ > audio_ident.BAND_HIGH_HZ

    def test_music_band_is_clear_of_the_pilot_band(self):
        assert audio_ident.MUSIC_MAX_HZ < audio_ident.BAND_LOW_HZ

    def test_drifted_tones_still_decode_within_tolerance(self):
        f_hz, t_hz = audio_ident.ident_tones(2, 3)
        drift = audio_ident.MATCH_TOLERANCE_HZ * 0.8
        assert audio_ident.decode_tones(f_hz + drift, t_hz - drift) == (2, 3)

    def test_tones_far_off_grid_do_not_decode(self):
        f_hz, t_hz = audio_ident.ident_tones(2, 3)
        off = audio_ident.FOLDER_STEP_HZ / 2.0
        assert audio_ident.decode_tones(f_hz + off, t_hz)[0] is None


class TestIdentDetection:
    def test_detects_ident_in_clean_audio(self):
        from gui.mcp_line_in_analysis import detect_ident_sequence

        audio = _synth_with_pilots(3, 2)
        result = detect_ident_sequence(audio, SAMPLE_RATE)
        assert result["ok"]
        assert result["dominant"] == {"folder": 3, "track": 2}

    def test_reports_a_track_change_within_one_capture(self):
        from gui.mcp_line_in_analysis import detect_ident_sequence

        audio = np.concatenate(
            [_synth_with_pilots(1, 1, 1.5), _synth_with_pilots(audio_ident.COMMERCIALS_FOLDER, 2, 1.5)]
        )
        result = detect_ident_sequence(audio, SAMPLE_RATE)
        assert result["played_order"] == [
            {"folder": 1, "track": 1},
            {"folder": audio_ident.COMMERCIALS_FOLDER, "track": 2},
        ]

    def test_silence_decodes_nothing(self):
        from gui.mcp_line_in_analysis import detect_ident_sequence

        result = detect_ident_sequence(np.zeros(SAMPLE_RATE * 2), SAMPLE_RATE)
        assert not result["ok"]
        assert result["dominant"] is None

    def test_quiet_noise_never_invents_an_ident(self):
        """Regression: an idle line-in used to decode confident idents from noise.

        A relative peak-versus-band-median test always finds a "peak" in noise, so
        a near-silent capture reported tracks that were never played. Only an
        absolute level gate rules that out.
        """
        from gui.mcp_line_in_analysis import IDENT_MIN_RMS_DBFS, detect_ident_sequence

        rng = np.random.default_rng(7)
        for trial in range(25):
            noise = rng.normal(0.0, 1.0, SAMPLE_RATE * 2).astype(np.float32)
            noise *= (10.0 ** (-65.0 / 20.0)) / (np.sqrt(np.mean(noise**2)) + 1e-12)
            result = detect_ident_sequence(noise, SAMPLE_RATE)
            assert not result["ok"], f"trial {trial} invented {result.get('dominant')}"
            assert result["error"] == "capture_too_quiet"
            assert result["capture_rms_dbfs"] < IDENT_MIN_RMS_DBFS

    def test_loud_broadband_noise_still_does_not_decode(self):
        """Loud audio without pilots must not decode either, or a wrong-library SD
        card would be reported as correctly playing idents."""
        from gui.mcp_line_in_analysis import detect_ident_sequence

        rng = np.random.default_rng(11)
        invented = 0
        for _ in range(15):
            noise = rng.normal(0.0, 0.2, SAMPLE_RATE * 2).astype(np.float32)
            if detect_ident_sequence(noise, SAMPLE_RATE)["ok"]:
                invented += 1
        assert invented == 0

    def test_reports_confidence_for_a_decoded_ident(self):
        from gui.mcp_line_in_analysis import detect_ident_sequence

        result = detect_ident_sequence(_synth_with_pilots(2, 2), SAMPLE_RATE)
        assert result["dominant_confidence"] == 1.0


class TestIdentSurvivesConversion:
    """The pilots must outlive the encoders the sync pipeline actually uses."""

    def _round_trip(self, tmp_path: Path, folder: int, track: int, encode_args: list) -> dict:
        from gui.mcp_line_in_analysis import detect_ident_sequence, load_wav_mono_float

        exe = _ffmpeg_or_skip()
        src = tmp_path / "src.wav"
        encoded = tmp_path / f"encoded{encode_args[-1]}"
        back = tmp_path / "back.wav"
        _write_wav(src, _synth_with_pilots(folder, track, seconds=3.0))

        cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src)]
        cmd += encode_args[:-1] + [str(encoded)]
        assert subprocess.run(cmd, capture_output=True).returncode == 0

        assert (
            subprocess.run(
                [exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(encoded),
                 "-ar", str(SAMPLE_RATE), "-ac", "1", str(back)],
                capture_output=True,
            ).returncode
            == 0
        )
        samples, sr = load_wav_mono_float(back)
        return detect_ident_sequence(samples, sr)

    def test_survives_dfplayer_safe_profile(self, tmp_path):
        # Exactly the encode gui/sd_manager.py applies for the default profile.
        result = self._round_trip(
            tmp_path,
            2,
            4,
            ["-vn", "-codec:a", "libmp3lame", "-ar", "44100", "-ac", "2", "-b:a", "128k", ".mp3"],
        )
        assert result["ok"], "pilots lost in dfplayer_safe conversion"
        assert result["dominant"] == {"folder": 2, "track": 4}

    def test_survives_high_quality_profile(self, tmp_path):
        result = self._round_trip(
            tmp_path,
            audio_ident.COMMERCIALS_FOLDER,
            1,
            ["-vn", "-codec:a", "libmp3lame", "-q:a", "2", ".mp3"],
        )
        assert result["ok"], "pilots lost in high_quality conversion"
        assert result["dominant"] == {"folder": audio_ident.COMMERCIALS_FOLDER, "track": 1}

    @pytest.mark.parametrize(
        "encode_args",
        [
            pytest.param(["-c:a", "flac", ".flac"], id="flac"),
            pytest.param(["-c:a", "libvorbis", "-q:a", "5", ".ogg"], id="ogg"),
            pytest.param(["-c:a", "aac", "-b:a", "192k", ".m4a"], id="m4a"),
        ],
    )
    def test_survives_source_formats(self, tmp_path, encode_args):
        """Source formats the library ships in must decode before sync even runs."""
        result = self._round_trip(tmp_path, 1, 3, encode_args)
        assert result["ok"]
        assert result["dominant"] == {"folder": 1, "track": 3}


class TestGeneratedLibrary:
    """Validate the real generated files when they are present."""

    @pytest.fixture
    def library(self):
        root = Path(__file__).resolve().parents[2] / "agent_workshop" / "test_library_audio"
        manifest = root / "manifest.json"
        if not manifest.is_file():
            pytest.skip("test library not generated (run generate_test_library_audio.py)")
        import json

        return root, json.loads(manifest.read_text(encoding="utf-8"))

    def test_every_generated_file_decodes_to_its_own_ident(self, library):
        from gui.mcp_line_in_analysis import detect_ident_sequence, load_wav_mono_float

        root, manifest = library
        exe = _ffmpeg_or_skip()
        entries = [
            (station["folder"], track)
            for layout in manifest["layouts"].values()
            for station in layout["stations"]
            for track in station["tracks"]
        ]

        import tempfile

        failures = []
        with tempfile.TemporaryDirectory() as td:
            for folder, meta in entries:
                back = Path(td) / "decode.wav"
                subprocess.run(
                    [exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                     "-i", str(root / meta["file"]), "-ar", str(SAMPLE_RATE), "-ac", "1", str(back)],
                    capture_output=True,
                )
                samples, sr = load_wav_mono_float(back)
                got = detect_ident_sequence(samples, sr).get("dominant")
                if got != {"folder": folder, "track": meta["track"]}:
                    failures.append(f"{meta['file']}: expected {folder}/{meta['track']}, got {got}")
        assert not failures, "\n".join(failures)

    def test_music_tracks_outlast_the_sustained_play_hold(self, library):
        _, manifest = library
        # The acceptance harness holds 4s after a track starts to prove sustained play.
        for layout in manifest["layouts"].values():
            for station in layout["stations"]:
                for track in station["tracks"]:
                    if not track["is_commercial"]:
                        assert track["duration_s"] >= 20.0

    def test_each_layout_covers_every_source_format(self, library):
        _, manifest = library
        for name, layout in manifest["layouts"].items():
            formats = {t["format"] for s in layout["stations"] for t in s["tracks"]}
            assert formats == {"wav", "flac", "mp3", "ogg", "m4a"}, name

    def test_inline_ads_are_identified_by_their_own_station_not_folder_99(self, library):
        """An inline ad plays from inside a station, so its ident must name that
        station. Reusing a folder-99 ident here would make the acoustic checks
        report a folder-99 insert that never happened."""
        _, manifest = library
        for name in ("inline", "both"):
            for station in manifest["layouts"][name]["stations"]:
                if station["folder"] == 99:
                    continue
                for track in station["tracks"]:
                    if track["is_commercial"]:
                        expected, _ = _ident_pair(station["folder"], track["track"])
                        assert track["folder_pilot_hz"] == expected, track["file"]

    def test_linked_ad_sits_directly_above_a_music_track(self, library):
        _, manifest = library
        for name in ("inline", "both"):
            for station in manifest["layouts"][name]["stations"]:
                tracks = station["tracks"]
                for i, track in enumerate(tracks):
                    if not track["link_to_next"]:
                        continue
                    assert i + 1 < len(tracks), "linked ad is the last track"
                    assert not tracks[i + 1]["is_commercial"]

    def test_folder_layout_keeps_all_ads_in_folder_99(self, library):
        _, manifest = library
        for station in manifest["layouts"]["folder"]["stations"]:
            for track in station["tracks"]:
                assert track["is_commercial"] == (station["folder"] == 99)
