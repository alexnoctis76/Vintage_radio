"""Host tests for DFPlayer play-start confirmation polling logic."""

from __future__ import annotations

import sys
import time
import types
import struct

import pytest

# Stub MicroPython modules before importing dfplayer_hardware.
if "machine" not in sys.modules:
    machine = types.ModuleType("machine")
    machine.Pin = object
    machine.PWM = object
    machine.Timer = object
    machine.UART = object
    machine.SPI = object
    sys.modules["machine"] = machine
if "ustruct" not in sys.modules:
    ustruct = types.ModuleType("ustruct")
    ustruct.unpack = struct.unpack
    ustruct.unpack_from = struct.unpack_from
    sys.modules["ustruct"] = ustruct
if "ujson" not in sys.modules:
    import json as _json

    ujson = types.ModuleType("ujson")
    ujson.dumps = _json.dumps
    ujson.loads = _json.loads
    ujson.dump = _json.dump
    ujson.load = _json.load
    sys.modules["ujson"] = ujson
for _name in ("neopixel", "sdcard", "am_wav_loader", "pin_config_loader", "components"):
    if _name not in sys.modules:
        sys.modules[_name] = types.ModuleType(_name)
sys.modules["components"].am_wav_loader = types.ModuleType("am_wav_loader")
sys.modules["pin_config_loader"].load_pin_config = lambda: {"pins": {}}
sys.modules["pin_config_loader"].get_spi_config = lambda: {}
sys.modules["pin_config_loader"].get_dfplayer_config = lambda: {"max_volume": 28}

from firmware.pico import dfplayer_hardware as dfhw  # noqa: E402

if not hasattr(dfhw.time, "ticks_ms"):
    _T0 = time.monotonic()

    def _ticks_ms():
        return int((time.monotonic() - _T0) * 1000)

    def _ticks_diff(a, b):
        return a - b

    dfhw.time.ticks_ms = _ticks_ms
    dfhw.time.ticks_diff = _ticks_diff
    dfhw.time.ticks_add = lambda a, b: a + b
    if not hasattr(dfhw.time, "sleep_ms"):
        dfhw.time.sleep_ms = lambda ms: time.sleep(ms / 1000.0)


class _PinStub:
    def __init__(self, value=1):
        self._value = value

    def value(self):
        return self._value


class _PlayConfirmHarness:
    """Minimal harness for _poll_play_start_confirm without hardware init."""

    PLAY_CONFIRM_QUERY_INTERVAL_MS = dfhw.PLAY_CONFIRM_QUERY_INTERVAL_MS

    def __init__(self):
        self.pin_busy = _PinStub(1)
        self._track_finished_via_uart = False
        self._last_error_code = None
        self._query_calls = 0
        self._query_results = []

    def _df_read_pending(self):
        pass

    def query_status(self):
        self._query_calls += 1
        if self._query_results:
            return self._query_results.pop(0)
        return None

    _poll_play_start_confirm = dfhw.DFPlayerHardware._poll_play_start_confirm


class TestPlayStartConfirmPoll:
    def test_busy_low_confirms_immediately(self):
        hw = _PlayConfirmHarness()
        hw.pin_busy = _PinStub(0)
        play_sent = dfhw.time.ticks_ms()
        ok, reason, err = hw._poll_play_start_confirm(500, play_sent)
        assert ok is True
        assert reason == "busy_low"
        assert err is None
        assert hw._query_calls == 0

    def test_query_status_during_poll_confirms(self, monkeypatch):
        hw = _PlayConfirmHarness()
        hw._query_results = [None, 1]
        play_sent = dfhw.time.ticks_ms()

        def fast_sleep(_ms):
            pass

        monkeypatch.setattr(dfhw.time, "sleep_ms", fast_sleep)
        ok, reason, err = hw._poll_play_start_confirm(
            hw.PLAY_CONFIRM_QUERY_INTERVAL_MS + 500, play_sent
        )
        assert ok is True
        assert reason == "query_status_playing"
        assert err is None
        assert hw._query_calls >= 1

    def test_uart_finished_during_confirm_confirms_without_consume(self):
        hw = _PlayConfirmHarness()
        hw._track_finished_via_uart = True
        play_sent = dfhw.time.ticks_ms()
        ok, reason, err = hw._poll_play_start_confirm(500, play_sent)
        assert ok is True
        assert reason == "uart_finished_during_confirm"
        assert hw._track_finished_via_uart is True

    def test_final_query_status_fallback(self):
        hw = _PlayConfirmHarness()
        play_sent = dfhw.time.ticks_ms()
        hw._query_results = [None]

        def query_status():
            hw._query_calls += 1
            return 1

        hw.query_status = query_status
        ok, reason, err = hw._poll_play_start_confirm(50, play_sent)
        assert ok is True
        assert reason == "query_status_playing_final"
        assert hw._query_calls == 1

    def test_uart_error_returns_error_code(self):
        hw = _PlayConfirmHarness()
        hw._last_error_code = 6
        play_sent = dfhw.time.ticks_ms()
        ok, reason, err = hw._poll_play_start_confirm(500, play_sent)
        assert ok is False
        assert reason is None
        assert err == 6


class TestPlayStartConfirmScaling:
    def test_deep_folder_gets_longer_confirm(self):
        shallow = dfhw.DFPlayerHardware._play_start_confirm_ms(None, 1, 1)
        deep = dfhw.DFPlayerHardware._play_start_confirm_ms(None, 34, 170)
        assert deep > shallow
        assert deep <= dfhw.BUSY_CONFIRM_MS_MAX
        assert deep >= dfhw.BUSY_CONFIRM_MS


class TestPlayPreSettleScaling:
    """Fit from hardware measurements: folder 1 ~150-200ms, folder 10
    ~1.1-1.2s, folder 90 ~6.7s to a genuinely confirmed start. The pre-settle
    wait (before the FIRST play attempt) is what actually needs to scale —
    see _play_pre_settle_extra_ms docstring for why the confirm window alone
    isn't the fix."""

    def test_shallow_folder_gets_minimal_extra_settle(self):
        extra = dfhw.DFPlayerHardware._play_pre_settle_extra_ms(None, 1)
        assert extra == 0

    def test_deep_folder_gets_much_larger_extra_settle(self):
        extra = dfhw.DFPlayerHardware._play_pre_settle_extra_ms(None, 90)
        assert extra > dfhw.DFPlayerHardware._play_pre_settle_extra_ms(None, 10)
        # Matches the ~6.7s hardware measurement at folder 90 reasonably closely.
        assert 5500 <= extra <= 7500

    def test_extra_settle_is_capped(self):
        extra = dfhw.DFPlayerHardware._play_pre_settle_extra_ms(None, 999)
        assert extra == 7500

    def test_monotonic_in_folder_depth(self):
        values = [
            dfhw.DFPlayerHardware._play_pre_settle_extra_ms(None, f)
            for f in (1, 10, 30, 70, 99)
        ]
        assert values == sorted(values)


class TestDeepFolderAttempt0ExtendedConfirm:
    """Attempt 0 on folder >= 70 gets one long, uninterrupted confirm window
    instead of the normal (shorter) scaled window, to test whether the
    stop/resend/reset interruption between retries -- not raw wait time --
    is what causes complete failures on hardware (folder 90 tracks 11/12)."""

    def test_shallow_folder_gets_no_extension(self):
        assert dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms(None, 10, 1) is None
        assert dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms(None, 69, 1) is None

    def test_deep_folder_gets_extended_window_far_beyond_normal(self):
        normal = dfhw.DFPlayerHardware._play_start_confirm_ms(None, 90, 11)
        extended = dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms(None, 90, 11)
        assert extended is not None
        assert extended > normal
        assert extended >= 20000

    def test_extended_window_is_capped(self):
        extended = dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms(None, 99, 255)
        # 22000 + (255-1)*12 = 25048, under the 28000 cap -- confirms the cap
        # doesn't bind within the real track-number range (max 255) while
        # still bounding a hypothetical larger track value.
        assert extended == 22000 + 254 * 12
        assert dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms(None, 99, 100000) == 28000

    def test_boundary_folder_70_gets_extension(self):
        assert dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms(None, 70, 1) is not None


class TestMaxPlayAttemptsTiering:
    def test_shallow_warm_folder_gets_2_attempts(self):
        assert dfhw.DFPlayerHardware._max_play_attempts(None, 10, False) == 2

    def test_shallow_cold_jump_gets_3_attempts(self):
        assert dfhw.DFPlayerHardware._max_play_attempts(None, 10, True) == 3

    def test_mid_depth_folder_gets_3_attempts_even_when_warm(self):
        assert dfhw.DFPlayerHardware._max_play_attempts(None, 30, False) == 3
        assert dfhw.DFPlayerHardware._max_play_attempts(None, 69, False) == 3

    def test_very_deep_folder_gets_4_attempts_even_when_warm(self):
        """Reproduces the need behind tracks 9/10 in folder 90 failing both of
        2 attempts despite being ordinary warm same-folder track advances."""
        assert dfhw.DFPlayerHardware._max_play_attempts(None, 70, False) == 4
        assert dfhw.DFPlayerHardware._max_play_attempts(None, 90, False) == 4

    def test_very_deep_cold_jump_still_capped_at_4(self):
        assert dfhw.DFPlayerHardware._max_play_attempts(None, 90, True) == 4


class _PlayTrackHarness:
    """Harness for play_track()'s attempt-count/retry logic, without real hardware.

    Reproduces the on-hardware finding: a cold jump into a folder that isn't
    already loaded can fail 2 confirm attempts (BUSY stuck HIGH) yet a 3rd
    attempt confirms fine. Verifies play_track() grants that 3rd attempt only
    when the target folder differs from the one already loaded.
    """

    play_track = dfhw.DFPlayerHardware.play_track
    _play_start_confirm_ms = dfhw.DFPlayerHardware._play_start_confirm_ms
    _deep_folder_attempt0_confirm_ms = dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms

    _play_pre_settle_extra_ms = dfhw.DFPlayerHardware._play_pre_settle_extra_ms
    _max_play_attempts = dfhw.DFPlayerHardware._max_play_attempts

    def __init__(self, confirm_sequence):
        self._am_overlay_active = False
        self._delay_playback = False
        self._uart_track_end_armed = False
        self._playing_folder = None
        self._last_error_code = None
        self._df_volume = 28
        self._confirm_sequence = list(confirm_sequence)
        self.play_attempts = []
        self.stop_calls = 0
        self.reset_calls = 0
        self.confirm_ms_used = []

    def _set_last_start_outcome(self, *a, **k):
        pass

    def _df_folder_wrap_preplay(self, folder):
        pass

    def _df_reset(self):
        self.reset_calls += 1

    def _log_play_retry_probe(self, folder, track, play_sent_tick):
        # busy=1 (module idle, not yet confirmed), qs=None: matches the real
        # failure logs and does not trigger the "skip stop, already playing" path.
        return (1, None)

    def _df_stop(self):
        self.stop_calls += 1

    def _wait_for_busy_high(self, timeout_ms):
        return True

    def _df_set_vol(self, v):
        pass

    def _clear_uart_track_finished_stale(self, ms):
        pass

    def _df_play_folder_track(self, folder, track):
        self.play_attempts.append((folder, track))
        self._playing_folder = folder
        self._playing_track = track

    def _poll_play_start_confirm(self, confirm_ms, play_sent_tick):
        self.confirm_ms_used.append(confirm_ms)
        idx = len(self.play_attempts) - 1
        confirmed = idx < len(self._confirm_sequence) and self._confirm_sequence[idx]
        return (confirmed, "busy_low" if confirmed else None, None)

    def _log_play_confirm_failed(self, *a, **k):
        pass

    def _complete_play_track_start(self, folder, track, attempt, confirm_reason, start_ms):
        return True


class TestColdFolderJumpRetry:
    @pytest.fixture(autouse=True)
    def _fast_sleep(self, monkeypatch):
        monkeypatch.setattr(dfhw.time, "sleep_ms", lambda ms: None)

    def test_same_folder_gets_only_2_attempts(self):
        hw = _PlayTrackHarness(confirm_sequence=[False, False])
        hw._playing_folder = 5
        result = hw.play_track(5, 2)
        assert result is False
        assert len(hw.play_attempts) == 2

    def test_first_ever_play_not_treated_as_cold_jump(self):
        """prev folder unknown (never played) should behave like the warm case,
        not grant an extra attempt — matches original pre-fix behavior at boot."""
        hw = _PlayTrackHarness(confirm_sequence=[False, False])
        assert hw._playing_folder is None
        result = hw.play_track(5, 1)
        assert result is False
        assert len(hw.play_attempts) == 2

    def test_cold_folder_jump_gets_3rd_attempt_and_succeeds(self):
        """Reproduces the hardware finding: a cold jump into a shallow folder
        timed out twice (busy stuck HIGH) then a fresh attempt confirmed
        immediately. Uses a shallow target folder to isolate the cold-jump
        bonus attempt from the separate depth-tiering bonus (see
        TestVeryDeepFolderRetry for that case)."""
        hw = _PlayTrackHarness(confirm_sequence=[False, False, True])
        hw._playing_folder = 10
        result = hw.play_track(20, 1)
        assert result is True
        assert len(hw.play_attempts) == 3
        assert hw.play_attempts[-1] == (20, 1)
        # Any escalated (3+ attempt) sequence gets a hard reset before its
        # final try, not just very-deep folders.
        assert hw.reset_calls == 1

    def test_cold_folder_jump_still_fails_after_3_attempts(self):
        hw = _PlayTrackHarness(confirm_sequence=[False, False, False])
        hw._playing_folder = 10
        result = hw.play_track(20, 1)
        assert result is False
        assert len(hw.play_attempts) == 3


class TestDeepFolderAttempt0UsesExtendedWindow:
    """play_track() itself must actually apply the extended attempt-0 window
    for deep folders, and fall back to the normal (shorter) window for any
    subsequent retries so worst-case total time stays bounded."""

    @pytest.fixture(autouse=True)
    def _fast_sleep(self, monkeypatch):
        monkeypatch.setattr(dfhw.time, "sleep_ms", lambda ms: None)

    def test_attempt0_uses_extended_window_on_deep_folder(self):
        hw = _PlayTrackHarness(confirm_sequence=[True])
        hw._playing_folder = 90
        result = hw.play_track(90, 11)
        assert result is True
        assert len(hw.confirm_ms_used) == 1
        normal = dfhw.DFPlayerHardware._play_start_confirm_ms(None, 90, 11)
        assert hw.confirm_ms_used[0] > normal
        assert hw.confirm_ms_used[0] == dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms(
            None, 90, 11
        )

    def test_retries_fall_back_to_normal_shorter_window(self):
        hw = _PlayTrackHarness(confirm_sequence=[False, False, False, True])
        hw._playing_folder = 90
        result = hw.play_track(90, 11)
        assert result is True
        assert len(hw.confirm_ms_used) == 4
        normal = dfhw.DFPlayerHardware._play_start_confirm_ms(None, 90, 11)
        extended = dfhw.DFPlayerHardware._deep_folder_attempt0_confirm_ms(None, 90, 11)
        assert hw.confirm_ms_used[0] == extended
        assert hw.confirm_ms_used[1:] == [normal, normal, normal]

    def test_shallow_folder_never_gets_extended_window(self):
        hw = _PlayTrackHarness(confirm_sequence=[False, True])
        hw._playing_folder = 10
        result = hw.play_track(10, 2)
        assert result is True
        normal = dfhw.DFPlayerHardware._play_start_confirm_ms(None, 10, 2)
        assert hw.confirm_ms_used == [normal, normal]


class TestPreSettleSkippedWhenExtendedWindowActive:
    """The large scaled pre-settle sleep (_play_pre_settle_extra_ms) was
    originally meant to fix deep-folder attempt-0 failures by delaying
    *before* sending the play command. Hardware evidence showed that theory
    was wrong -- the module just needs a longer uninterrupted wait *after*
    the command -- so folders using the extended attempt-0 confirm window
    should skip the scaled pre-settle sleep entirely (only the small fixed
    200ms base settle remains), while folders below the extension threshold
    keep the original scaled pre-settle behavior."""

    def test_deep_folder_skips_scaled_pre_settle(self, monkeypatch):
        monkeypatch.setattr(dfhw.time, "sleep_ms", lambda ms: None)
        hw = _PlayTrackHarness(confirm_sequence=[True])
        hw._playing_folder = 90
        recorded = []
        real_extra = hw._play_pre_settle_extra_ms(90)
        assert real_extra > 1000  # sanity: folder 90 would normally get a large value

        def spy_sleep(ms):
            recorded.append(ms)

        monkeypatch.setattr(dfhw.time, "sleep_ms", spy_sleep)
        hw.play_track(90, 11)
        # The pre-settle sleep is always exactly 200ms + extra; with the
        # extended window active, extra must be 0 (i.e. exactly 200ms, not
        # 200ms + the large scaled value).
        assert 200 in recorded
        assert (200 + real_extra) not in recorded

    def test_mid_depth_folder_still_uses_scaled_pre_settle(self, monkeypatch):
        hw = _PlayTrackHarness(confirm_sequence=[True])
        hw._playing_folder = 50
        assert hw._deep_folder_attempt0_confirm_ms(50, 2) is None
        real_extra = hw._play_pre_settle_extra_ms(50)
        recorded = []

        def spy_sleep(ms):
            recorded.append(ms)

        monkeypatch.setattr(dfhw.time, "sleep_ms", spy_sleep)
        hw.play_track(50, 2)
        assert (200 + real_extra) in recorded


class TestVeryDeepFolderRetry:
    """Folder >= 70 gets a 4th attempt even for ordinary warm (same-folder)
    track advances, plus a hard DFPlayer reset before that final attempt —
    reproduces tracks 9/10 in folder 90 failing both of only 2 attempts
    during hardware testing despite being routine same-folder advances."""

    @pytest.fixture(autouse=True)
    def _fast_sleep(self, monkeypatch):
        monkeypatch.setattr(dfhw.time, "sleep_ms", lambda ms: None)

    def test_warm_deep_folder_gets_4th_attempt_and_succeeds(self):
        hw = _PlayTrackHarness(confirm_sequence=[False, False, False, True])
        hw._playing_folder = 90  # already playing this folder — not a cold jump
        result = hw.play_track(90, 10)
        assert result is True
        assert len(hw.play_attempts) == 4
        assert hw.reset_calls == 1  # hard recovery fired before the 4th (final) attempt

    def test_warm_deep_folder_still_fails_after_4_attempts(self):
        hw = _PlayTrackHarness(confirm_sequence=[False, False, False, False])
        hw._playing_folder = 90
        result = hw.play_track(90, 10)
        assert result is False
        assert len(hw.play_attempts) == 4
        assert hw.reset_calls == 1

    def test_reset_not_used_for_ordinary_2_attempt_case(self):
        hw = _PlayTrackHarness(confirm_sequence=[False, False])
        hw._playing_folder = 5
        result = hw.play_track(5, 2)
        assert result is False
        assert hw.reset_calls == 0

    def test_mid_depth_folder_uses_3_attempts_no_reset_needed_if_3rd_succeeds(self):
        hw = _PlayTrackHarness(confirm_sequence=[False, False, True])
        hw._playing_folder = 50
        result = hw.play_track(50, 2)
        assert result is True
        assert len(hw.play_attempts) == 3
        # Hard-reset escalation still fires before the last of 3+ attempts,
        # regardless of whether that attempt goes on to succeed.
        assert hw.reset_calls == 1
