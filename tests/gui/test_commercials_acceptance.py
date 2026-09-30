"""Host tests for the commercials acceptance suites.

These drive the suite against a simulated radio so the harness logic itself is
exercised without hardware: step wiring, abort paths, and - most importantly -
that the acoustic checks actually fail when the audio disagrees with the state
the firmware reports. A suite that cannot fail is worthless on the bench.
"""

from __future__ import annotations

import pytest

from gui import mcp_commercials_acceptance as mca
from gui.audio_ident import COMMERCIALS_FOLDER

BOOT = "VRTEST IPC: uselect stdin polling enabled"


class FakeRadio:
    """A cooperative radio: correct ordering, ads on cadence, clean serial."""

    def __init__(
        self,
        *,
        stations: int = mca.EXPECTED_STATIONS,
        tracks: int = mca.TRACKS_PER_STATION,
        mode: str = "folder_99",
        library_shuffle: bool = False,
        ads_enabled: bool = True,
        report_enabled=None,
        acoustic_folder_override=None,
        acoustic_track_override=None,
    ) -> None:
        self.stations = stations
        self.tracks = tracks
        self.commercials_mode = mode
        self.library_shuffle = library_shuffle
        self.ads_enabled = ads_enabled
        self.report_enabled = report_enabled
        self.acoustic_folder_override = acoustic_folder_override
        self.acoustic_track_override = acoustic_track_override

        self.station = 0
        self.track = 1
        self.play_mode = "playlist"
        self.shuffle_source = None
        self.ad_playing = False
        self.serial = [BOOT, "DF: BUSY went LOW -> playback started"]
        self.gestures = 0
        self._polls_since_arm = 0
        self._ad_polls = 0
        self.music_since_ad = 0
        self._ad_resume = None

    # ---------------------------------------------------------------- helpers

    @property
    def folder(self) -> int:
        return COMMERCIALS_FOLDER if self.ad_playing else self.station + 1

    def _advance(self) -> None:
        if self.shuffle_source == "library":
            self.station = (self.station + 1) % self.stations
            self.track = (self.track % self.tracks) + 1
            return
        self.track += 1
        if self.track > self.tracks:
            self.track = 1
            self.station = (self.station + 1) % self.stations

    def _skip_with_ads(self) -> None:
        """Manual skip: count toward the ad interval; last track goes to the next station."""
        if self.ads_enabled and self.commercials_mode in ("folder_99", "both"):
            self.music_since_ad += 1
            if self.music_since_ad >= mca.COMMERCIAL_INTERVAL:
                self.music_since_ad = 0
                self.ad_playing = True
                if self.shuffle_source == "library":
                    st = (self.station + 1) % self.stations
                    nxt = (self.track % self.tracks) + 1
                else:
                    nxt = self.track + 1
                    st = self.station
                    if nxt > self.tracks:
                        nxt = 1
                        st = (self.station + 1) % self.stations
                self._ad_resume = (st, nxt)
                self.serial.append(f"COMMERCIALS: playing folder {COMMERCIALS_FOLDER} track 2")
                return
        self._advance()

    def _next_station(self) -> None:
        self.station = (self.station + 1) % self.stations
        self.track = 1

    def _tick_ads(self) -> None:
        """Insert an ad on cadence once the suite has left its ordering phase."""
        if not self.ads_enabled or self.commercials_mode not in ("folder_99", "both"):
            return
        if self.ad_playing:
            self._ad_polls += 1
            if self._ad_polls >= 4:
                self.ad_playing = False
                self._ad_polls = 0
                self._polls_since_arm = 0
                if self._ad_resume is not None:
                    self.station, self.track = self._ad_resume
                    self._ad_resume = None
                else:
                    self._advance()
                self.serial.append("COMMERCIALS: finished, resuming music")
                self.serial.append(
                    f"_start_playback_for_current: mode=playlist, folder={self.folder}, "
                    f"track={self.track}"
                )
            return
        if self.gestures < 4:
            return
        self._polls_since_arm += 1
        if self._polls_since_arm >= 25:
            self.ad_playing = True
            self._polls_since_arm = 0
            self._ad_resume = (self.station, self.track)
            self.serial.append(f"COMMERCIALS: playing folder {COMMERCIALS_FOLDER} track 2")

    def state(self) -> dict:
        self._tick_ads()
        return {
            "mode": self.play_mode,
            "current_track": self.track,
            "current_album_index": self.station,
            "playing_folder": self.folder,
            "busy_pin": 0,
            "is_playing": True,
            "total_playlists": self.stations,
            "shuffle_source_type": self.shuffle_source,
            "commercials_mode": self.commercials_mode,
            "commercials_enabled": (
                self.ads_enabled and self.commercials_mode in ("folder_99", "both")
                if self.report_enabled is None
                else self.report_enabled
            ),
            "commercials_interval": mca.COMMERCIAL_INTERVAL,
            "playing_commercial": self.ad_playing,
            "folder_commercial_playing": self.ad_playing,
            "linked_ad_playing": False,
        }

    # ---------------------------------------------------------------- gestures

    def gesture(self, name: str) -> None:
        self.gestures += 1
        self._polls_since_arm = 0
        if self.ad_playing:
            self.ad_playing = False
            self._ad_polls = 0
            self._ad_resume = None
            self.serial.append("COMMERCIALS: pending resume cancelled (playback changed)")

        if name == "single_tap":
            self._skip_with_ads()
        elif name == "long_press":
            self._next_station()
        elif name == "triple_tap":
            self.station, self.track = 0, 1
            self.play_mode, self.shuffle_source = "playlist", None
            self.music_since_ad = 0
        elif name == "five_tap":
            self.station, self.track = 0, 1
            self.play_mode, self.shuffle_source = "playlist", None
            self.music_since_ad = 0
        elif name == "tap_long_press":
            self.play_mode, self.shuffle_source = "playlist", None
        elif name == "double_tap_long_press":
            self.play_mode, self.shuffle_source = "shuffle", "station"
            self.track = 1
        elif name == "triple_tap_long_press":
            self.play_mode = "shuffle"
            if self.library_shuffle:
                self.shuffle_source = "library"
            else:
                self.shuffle_source = "station"
                self.station = 0
            self.track = 1
        self.serial.append("AM: PWM overlay complete, vol=28, confirmed=True")
        self.serial.append(f"_start_playback_for_current: folder={self.folder} track={self.track}")

    # ---------------------------------------------------------------- adapters

    def invoke(self, action: str, payload: dict) -> dict:
        if action == "restart_firmware":
            self.station, self.track = 0, 1
            self.play_mode, self.shuffle_source = "playlist", None
            self.music_since_ad = 0
            self.ad_playing = False
            self._ad_resume = None
            vol_lines = [ln for ln in self.serial if "set volume" in ln]
            self.serial = [BOOT]
            self.serial.extend(vol_lines or ["DF: set volume 28"])
            self.serial.append("AM: PWM overlay complete, vol=28, confirmed=True")
            return {"ok": True}
        if action in ("connect", "start_streaming", "device_connect"):
            return {"ok": True}
        if action == "physical_gesture":
            g = payload.get("gesture")
            if g == "get_state":
                return {"device": {"state": self.state()}}
            self.gesture(str(g))
            return {"device": {"state": self.state()}}
        if action == "device_stream_tail":
            return {"ok": True, "lines": list(self.serial)[-int(payload.get("limit", 400)) :]}
        return {"ok": True}

    def request(self, method: str, params: dict) -> dict:
        if method == "get_connection_state":
            return {"ok": True, "state": {"connected": True, "streaming": True}}
        if method == "device_connect":
            return {"ok": True, "auto_start_streaming": True}
        if method == "line_in_list_devices":
            return {
                "ok": True,
                "default_input_index": 0,
                "devices": [{"index": 0, "name": "Vintage Radio Line In", "channels": 2}],
            }
        if method == "line_in_analyze":
            folder = (
                self.acoustic_folder_override(self)
                if callable(self.acoustic_folder_override)
                else self.folder
            )
            track = (
                self.acoustic_track_override(self)
                if callable(self.acoustic_track_override)
                else self.track
            )
            return {
                "ok": True,
                "summary": {"rms_dbfs": -22.0, "peak_linear": 0.8},
                "reference_compare": {"envelope_pearson_r": 0.05, "loaded": True},
                "ident": {
                    "ok": True,
                    "dominant": {"folder": folder, "track": track},
                    "played_order": [{"folder": folder, "track": track}],
                    "decoded_segments": 4,
                    "total_segments": 4,
                },
            }
        return {"ok": True}


class DeafRadio(FakeRadio):
    """No usable capture device, so every acoustic check must degrade to SKIP."""

    def request(self, method: str, params: dict) -> dict:
        if method == "line_in_list_devices":
            return {"ok": True, "default_input_index": None, "devices": []}
        return {"ok": True}


@pytest.fixture(autouse=True)
def fast_clock(monkeypatch):
    """Remove real waiting. The timeouts shrink too, or the negative cases would
    busy-spin for the full on-hardware budget once sleep is a no-op."""
    monkeypatch.setattr(mca.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(mca, "_AD_WAIT_MAX_S", 1.5)
    monkeypatch.setattr(mca, "_NATURAL_END_MAX_S", 0.4)
    monkeypatch.setattr(mca, "_TRACK_START_MAX_S", 2.0)
    monkeypatch.setattr(mca, "_MODE_SWITCH_MAX_S", 2.0)
    monkeypatch.setattr(mca, "_MUSIC_READY_MAX_S", 0.5)
    monkeypatch.setattr(mca, "AD_TRACK_S", 0.05)
    monkeypatch.setattr(mca, "_MIN_PLAY_DURATION_S", 0.0)
    monkeypatch.setattr(mca, "_IDENT_CAPTURE_S", 0.0)


def run(radio: FakeRadio, suite: str = "basic_folder", require_audio: bool = True) -> dict:
    return mca.run_commercials_acceptance(
        invoke=radio.invoke,
        request=radio.request,
        target="device",
        suite=suite,
        require_audio=require_audio,
    )


def step(result: dict, name: str) -> dict:
    match = [s for s in result["steps"] if s["name"] == name]
    assert match, f"step {name!r} not found in {[s['name'] for s in result['steps']]}"
    return match[0]


class TestSuiteRegistry:
    def test_every_suite_is_runnable_by_name(self):
        assert set(mca.SUITES) == {
            "basic_folder",
            "conductor_folder",
            "conductor_inline",
            "conductor_both",
        }

    def test_basic_family_has_no_inline_suite(self):
        # Basic firmware never loads radio_catalog.json, so inline ads are impossible.
        for name, cfg in mca.SUITES.items():
            if cfg["family"] == "basic":
                assert not cfg["inline"], f"{name} claims inline ads on basic firmware"

    def test_only_conductor_claims_library_shuffle(self):
        for name, cfg in mca.SUITES.items():
            if cfg["library_shuffle"]:
                assert cfg["family"] == "conductor", name

    def test_unknown_suite_is_rejected(self):
        result = mca.run_commercials_acceptance(invoke=lambda *_a: {}, suite="nope")
        assert not result["ok"]
        assert result["error"] == "unknown_suite"
        assert "basic_folder" in result["available"]


class TestAbortPaths:
    def test_unreachable_device_aborts_immediately(self):
        result = mca.run_commercials_acceptance(
            invoke=lambda *_a: {}, target="device", suite="basic_folder"
        )
        assert not result["ok"]
        assert result["aborted"] == "device unreachable"
        assert not step(result, "device_reachable")["ok"]

    def test_wrong_library_aborts_with_actionable_message(self):
        result = run(FakeRadio(stations=7))
        assert not result["ok"]
        assert result["aborted"] == "wrong library on SD"
        note = step(result, "station_count_matches_test_library")["note"]
        assert "generate_test_library_audio" in note

    def test_abort_stops_before_playback_phases(self):
        result = run(FakeRadio(stations=1))
        assert "ordered_tracks_start_and_sustain" not in [s["name"] for s in result["steps"]]


class TestHappyPath:
    def test_basic_folder_suite_passes_against_a_correct_radio(self):
        result = run(FakeRadio())
        assert result["ok"], result["failed_steps"]
        assert step(result, "firmware_soft_reset")["ok"]
        assert step(result, "reset_to_first_station_playing")["ok"]
        assert step(result, "reset_to_first_station_playing")["track"] == 1

    def test_conductor_folder_suite_passes(self):
        result = run(FakeRadio(library_shuffle=True), suite="conductor_folder")
        assert result["ok"], result["failed_steps"]

    def test_ordered_playback_is_verified_acoustically(self):
        result = run(FakeRadio())
        s = step(result, "no_skipped_or_repeated_tracks_acoustic")
        assert s["ok"]
        assert s["heard"] == [(1, 1), (1, 2), (1, 3), (1, 4)]

    def test_tapping_through_tracks_inserts_interval_ad(self):
        result = run(FakeRadio())
        assert step(result, "gesture_skip_inserts_interval_ad")["ok"]
        assert step(result, "single_tap_past_last_track_advances_station")["ok"]

    def test_folder_99_is_kept_out_of_the_station_rotation(self):
        result = run(FakeRadio())
        s = step(result, "commercials_folder_is_not_a_station")
        assert s["ok"]
        assert COMMERCIALS_FOLDER not in s.get("heard_folders", [])

    def test_library_shuffle_is_only_checked_for_conductor(self):
        basic = run(FakeRadio())
        conductor = run(FakeRadio(library_shuffle=True), suite="conductor_folder")
        basic_names = [s["name"] for s in basic["steps"]]
        conductor_names = [s["name"] for s in conductor["steps"]]
        assert "library_shuffle_engages" not in basic_names
        assert "basic_triple_hold_returns_to_first_station_shuffled" in basic_names
        assert "library_shuffle_engages" in conductor_names


class TestFailureDetection:
    """The suite has to catch real misbehaviour, not just pass on happy paths."""

    def test_a_skipped_track_fails_the_acoustic_ordering_check(self):
        # Reports track 2 correctly but actually plays track 3: exactly the class
        # of bug that reported state alone would never reveal.
        radio = FakeRadio(acoustic_track_override=lambda r: 3 if r.track == 2 else r.track)
        result = run(radio)
        s = step(result, "no_skipped_or_repeated_tracks_acoustic")
        assert not s["ok"]
        assert (1, 3) in s["heard"]
        assert not result["ok"]

    def test_an_ad_that_never_fires_is_reported(self):
        # Policy on the Pico says ads are on; they just never insert. Phase 0
        # must not abort, or we would never reach the insert check.
        result = run(FakeRadio(ads_enabled=False, report_enabled=True))
        assert not step(result, "folder_ad_inserted_within_two_cycles")["ok"]
        assert not result["ok"]

    def test_disabled_commercials_on_pico_aborts_before_ad_phases(self):
        result = run(FakeRadio(ads_enabled=False))
        assert result["aborted"] == "commercials disabled on Pico"
        assert not step(result, "firmware_reports_commercials_enabled")["ok"]
        assert "folder_ad_inserted_within_two_cycles" not in [s["name"] for s in result["steps"]]

    def test_wrong_commercials_mode_is_flagged(self):
        result = run(FakeRadio(mode="inline"))
        s = step(result, "firmware_reports_expected_commercials_mode")
        assert not s["ok"]
        assert s["actual"] == "inline"

    def test_station_audio_from_folder_99_fails(self):
        radio = FakeRadio(acoustic_folder_override=lambda r: COMMERCIALS_FOLDER)
        result = run(radio)
        assert not step(result, "commercials_folder_is_not_a_station")["ok"]


class TestDegradedCoverage:
    def test_missing_line_in_skips_acoustic_steps_without_failing(self):
        result = run(DeafRadio())
        acoustic = step(result, "no_skipped_or_repeated_tracks_acoustic")
        assert acoustic["skipped"]
        assert result["ok"], result["failed_steps"]

    def test_skipped_steps_are_listed_as_coverage_gaps(self):
        result = run(DeafRadio())
        assert result["skipped"] > 0
        assert "Skipped steps (gaps in coverage this run)" in result["report_markdown"]
        assert "line_in_available" in result["skipped_steps"]


class TestAudioPathPrecheck:
    """A muted radio or unplugged capture adapter should be reported in seconds,
    not discovered after a full run of skipped acoustic checks."""

    class SilentRadio(FakeRadio):
        def request(self, method: str, params: dict) -> dict:
            r = super().request(method, params)
            if method == "line_in_analyze":
                r["summary"] = {"rms_dbfs": -65.0, "peak_linear": 0.001}
                r["ident"] = {"ok": False, "error": "capture_too_quiet", "dominant": None}
            return r

    def test_silent_line_in_aborts_in_phase_0(self):
        result = run(self.SilentRadio())
        assert not result["ok"]
        assert result["aborted"] == "line-in silent"
        assert not step(result, "audio_path_is_audible")["ok"]

    def test_abort_message_points_at_volume_and_cable(self):
        radio = self.SilentRadio()
        radio.serial.append("DF: set volume 0")
        result = run(radio)
        s = step(result, "audio_path_is_audible")
        assert s["device_volume"] == 0
        assert "volume" in s["note"] and "cable" in s["note"]

    def test_silent_run_stops_before_the_long_phases(self):
        result = run(self.SilentRadio())
        names = [s["name"] for s in result["steps"]]
        assert "ordered_tracks_start_and_sustain" not in names

    def test_allow_silent_runs_the_non_acoustic_checks(self):
        result = run(self.SilentRadio(), require_audio=False)
        names = [s["name"] for s in result["steps"]]
        assert "ordered_tracks_start_and_sustain" in names
        assert result["aborted"] is None

    def test_healthy_audio_path_passes_without_comment(self):
        s = step(run(FakeRadio()), "audio_path_is_audible")
        assert s["ok"]
        assert s["note"] is None


class TestLineInDeviceFallback:
    """A USB line-in adapter enumerates once per host API (MME, DirectSound,
    WASAPI) under the identical name; one API's slot can go silently stale
    after a hot unplug/replug while the others stay healthy. The suite must
    not get stuck on the first name match if it happens to be the dead one."""

    class MultiApiRadio(FakeRadio):
        """Three device slots share the name; only ``dead_indices`` are dead."""

        dead_indices = (2,)
        healthy_rms = -30.0
        dead_rms = -96.0

        def request(self, method: str, params: dict) -> dict:
            if method == "line_in_list_devices":
                return {
                    "ok": True,
                    "default_input_index": 1,
                    "devices": [
                        {"index": 2, "name": "Vintage Radio Line In", "channels": 2},
                        {"index": 15, "name": "Vintage Radio Line In", "channels": 2},
                        {"index": 33, "name": "Vintage Radio Line In", "channels": 2},
                    ],
                }
            if method == "line_in_analyze":
                if params.get("device") in self.dead_indices:
                    return {
                        "ok": True,
                        "summary": {"rms_dbfs": self.dead_rms, "peak_linear": 0.00002},
                        "ident": {"ok": False, "error": "capture_too_quiet", "dominant": None},
                    }
                r = super().request(method, params)
                r["summary"]["rms_dbfs"] = self.healthy_rms
                return r
            return super().request(method, params)

    def test_probe_skips_a_dead_host_api_slot_and_uses_a_healthy_one(self):
        result = run(self.MultiApiRadio())
        assert result["ok"], result["failed_steps"]
        s = step(result, "audio_path_is_audible")
        assert s["ok"]
        assert s["rms_dbfs"] == self.MultiApiRadio.healthy_rms

    def test_ignores_an_implausibly_loud_reading_even_when_probed_before_a_real_one(self):
        """Name-based filtering (rank_line_in_device_candidates) is one layer of
        defense against a misidentified capture path, but a driver glitch can
        corrupt a reading from a legitimately name-matched candidate too.
        _healthiest_candidate must reject a nonsensical positive dBFS itself -
        impossible for real unclipped audio - even when it is tried *before*
        a genuinely quiet-but-real candidate, rather than treating "biggest
        number so far" as automatically the best."""

        class GarbageThenRealRadio(FakeRadio):
            def request(self, method: str, params: dict) -> dict:
                if method == "line_in_list_devices":
                    return {
                        "ok": True,
                        "default_input_index": 1,
                        "devices": [
                            {"index": 99, "name": "Vintage Radio Line In", "channels": 2},
                            {"index": 15, "name": "Vintage Radio Line In", "channels": 2},
                        ],
                    }
                if method == "line_in_analyze" and params.get("device") == 99:
                    return {
                        "ok": True,
                        "summary": {"rms_dbfs": 40.26, "peak_linear": 12.0},
                        "ident": {"ok": False, "dominant": None},
                    }
                if method == "line_in_analyze" and params.get("device") == 15:
                    r = super().request(method, params)
                    r["summary"]["rms_dbfs"] = -50.0
                    return r
                return super().request(method, params)

        result = run(GarbageThenRealRadio())
        assert result["ok"], result["failed_steps"]
        s = step(result, "audio_path_is_audible")
        assert s["ok"]
        assert s["rms_dbfs"] == -50.0

    def test_falls_back_to_the_ranked_best_when_every_candidate_is_dead(self):
        """If every slot is genuinely dead, the suite must still report the
        real failure (not crash, not silently pick an arbitrary index)."""

        class AllDeadRadio(self.MultiApiRadio):
            # Include the reported default_input_index (1) too - every
            # ranked candidate must be dead, not just the named matches.
            dead_indices = (2, 15, 33, 1)

        result = run(AllDeadRadio())
        assert not result["ok"]
        s = step(result, "audio_path_is_audible")
        assert not s["ok"]
        assert s["rms_dbfs"] == AllDeadRadio.dead_rms


class TestSerialWindowIntegrity:
    """Regression: a rotated ring buffer must not let old events satisfy new checks."""

    def test_rotated_ring_marks_serial_checks_as_inconclusive(self):
        class ChattyRadio(FakeRadio):
            """Floods serial so the phase marker is evicted before it is read.

            Lines are unique, matching a real device whose log carries timestamps;
            a repeating pattern would let the overlap search realign by accident.
            """

            _noise = 0

            def invoke(self, action: str, payload: dict) -> dict:
                if action == "device_stream_tail":
                    for _ in range(2000):
                        ChattyRadio._noise += 1
                        self.serial.append(f"noise line {ChattyRadio._noise}")
                return super().invoke(action, payload)

        result = run(ChattyRadio())
        s = step(result, "ad_resumes_music_without_stale_cancel")
        assert s["ok"]
        assert "session tail" in (s.get("reason") or "")


class TestWaitForMusicReady:
    def test_overlay_complete_serial_lets_phase1_start(self):
        radio = FakeRadio()
        result = run(radio)
        assert step(result, "reset_to_first_station_playing")["ok"]
        assert any("PWM overlay complete" in ln for ln in radio.serial)

    def test_low_pearson_counts_as_music_when_overlay_line_is_missing(self):
        class NoOverlayRadio(FakeRadio):
            def gesture(self, name: str) -> None:
                super().gesture(name)
                self.serial = [ln for ln in self.serial if "PWM overlay complete" not in ln]

            def invoke(self, action: str, payload: dict) -> dict:
                r = super().invoke(action, payload)
                if action == "restart_firmware":
                    self.serial = [ln for ln in self.serial if "PWM overlay complete" not in ln]
                return r

        result = run(NoOverlayRadio())
        assert step(result, "reset_to_first_station_playing")["ok"]
        assert result["ok"], result["failed_steps"]


class TestReport:
    def test_report_names_the_suite_and_verdict(self):
        result = run(FakeRadio())
        md = result["report_markdown"]
        assert "Basic firmware - folder 99 commercials" in md
        assert "## Result: **PASS**" in md

    def test_failed_steps_are_called_out_in_the_report(self):
        result = run(FakeRadio(ads_enabled=False, report_enabled=True))
        md = result["report_markdown"]
        assert "## Result: **FAIL**" in md
        assert "folder_ad_inserted_within_two_cycles" in md
