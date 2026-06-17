# Vintage Radio Firmware - BASIC MODE
# Uses DFPlayer folder structure as the source of truth for stations.
# No metadata files required -- stations are discovered via UART queries.
#
# Hardware: Raspberry Pi Pico + DFPlayer Mini
# Compatible with MicroPython

from machine import Pin
import time
import builtins

_print_orig = builtins.print


def _firmware_log_clock():
    """Monotonic-ish wall segment for serial: ``HH:MM:SS.mmm`` (dot before ms, not a third host stamp)."""
    try:
        lt = time.localtime()
        ms = time.ticks_ms() % 1000
        return f"{lt[3]:02d}:{lt[4]:02d}:{lt[5]:02d}.{ms:03d}"
    except Exception:
        return "00:00:00.000"


def print(*args, **kwargs):  # noqa: A001 — replace global print for serial timestamps
    prefix = f"[{_firmware_log_clock()}]"
    if args:
        args = (prefix,) + args
    else:
        args = (prefix,)
    return _print_orig(*args, **kwargs)


builtins.print = print

from radio_core import (
    RadioCore,
    HardwareInterface,
    MODE_ALBUM, MODE_PLAYLIST, MODE_SHUFFLE, MODE_RADIO,
    FADE_IN_S, DF_BOOT_MS, BUSY_CONFIRM_MS, POST_CMD_GUARD_MS,
    ticks_ms, ticks_diff,
)

import gc

gc.collect()
try:
    from components import am_wav_loader
except ImportError:
    import am_wav_loader

am_wav_loader.load_am_wav_cache()
gc.collect()

from components.dfplayer_hardware import DFPlayerHardware
from components.vintage_radio_ipc import poll_ipc


class VintageRadioFirmware:
    """Basic-mode firmware. Stations are discovered from DFPlayer SD card
    folder structure (0x4F/0x4E queries). No album mode, no metadata files."""

    def __init__(self):
        print("Booting Vintage Radio (BASIC MODE)")
        self.hw = DFPlayerHardware()
        self.core = RadioCore(self.hw, basic_mode=True)

        self.last_button = 1
        self.press_start = 0
        self.rail2_on = False
        self.last_sense = 0
        self.prev_busy = 1
        self._busy_high_since = 0
        self._was_playing = False
        self._last_stuck_query_ms = 0
        # Guard against false "stopped" reads that can cause mid-track artifacts/skips.
        self._stuck_status_zero_count = 0
        # Start recovery escalation counters:
        # - explicit errors (UART 0x40) escalate faster than ambiguous starts.
        self._start_unconfirmed_streak = 0
        self._start_explicit_error_streak = 0
        self._reset_after_unconfirmed = 3
        self._reset_after_explicit = 2
        self._last_uart_decision_track = None
        self._last_uart_decision_reason = ""
        self._last_uart_decision_tick = 0
        # Power sense debounce (noisy/floating pin or USB reconnect glitches)
        self._pwr_db_raw = None
        self._pwr_db_count = 0

    def wait_for_power(self):
        skip_power_check = self._check_skip_power_sense()
        if skip_power_check:
            print("Power sense check DISABLED (configured via debug mode)")
            self.rail2_on = True
            # Match real GPIO so handle_power_change() does not see a bogus HIGH->LOW edge
            # (would immediately call power_off() while the pot is still physically off).
            self.last_sense = 1 if self.hw.is_power_on() else 0
            return

        print("Waiting for power sense HIGH...")
        print("(Turn pot on, or create skip_power_sense.txt with 'true' to skip)")
        last_hint = ticks_ms()
        while not self.hw.is_power_on():
            if ticks_diff(ticks_ms(), last_hint) > 500:
                print("...waiting for power sense HIGH")
                last_hint = ticks_ms()
            time.sleep_ms(20)

        print("Power sense HIGH detected.")
        self.rail2_on = True
        self.last_sense = 1

    def _check_skip_power_sense(self):
        try:
            with open("skip_power_sense.txt", "r") as f:
                content = f.read().strip().lower()
                return content == "true" or content == "1"
        except OSError:
            return False

    def _check_hw_comms(self):
        """Verify DFPlayer communication after boot."""
        print("--- DFPlayer comms check (basic mode) ---")
        if hasattr(self.hw, "_df_read_pending") and hasattr(self.hw, "query_file_count"):
            self.hw._df_read_pending()
            busy = self.hw.pin_busy.value()
            print(f"  BUSY pin = {busy} (expect 1=idle)")
            fc = self.hw.query_file_count()
            if fc is not None:
                print(f"  TF file count = {fc}")
            else:
                print("  TF file count = TIMEOUT (GP1 not wired to DFPlayer TX?)")

            num_stations = len(self.core.playlists)
            if num_stations > 0:
                first = self.core.playlists[0]
                folder = int(first.get("id", first.get("folder", 1)))
                # Never send an audible probe play here: it is heard before the boot AM
                # sequence and fights UART timing. TF count + optional 0x4E is enough.
                qf = getattr(self.hw, "query_files_in_folder", None)
                if callable(qf):
                    fc = qf(folder, suppress_errors=True, timeout_ms=700)
                    print(f"  Folder {folder:02d} file count probe (no play): {fc}")
                else:
                    print(f"  Skipping folder probe (no query_files_in_folder); first station={folder}")
        print("--- End DFPlayer check ---")

    def boot_sequence(self):
        try:
            reset = getattr(self.hw, "reset_dfplayer", None)
            if reset is not None:
                reset()
            self.core.init(skip_initial_playback=True)
            self._check_hw_comms()
            # Shuffle rebuild is deferred past init (see _load_state) so it runs after
            # DFPlayer comms check and does not fight the diagnostic probe play.
            if getattr(self.core, "_defer_basic_shuffle_rebuild", False):
                self.core._defer_basic_shuffle_rebuild = False
                # Build shuffle list only; _start_with_am_and_recovery owns first play.
                self.core._init_shuffle(start_playback=False)
                self.core.current_track = 1
                if self.core.mode == MODE_SHUFFLE and self.core.shuffle_tracks:
                    self.core.shuffle_index = 0
                elif self.core.mode == MODE_RADIO and self.core.radio_stations:
                    self.core.radio_station_index = 0
            else:
                # Do not clobber album_state / load_state track for playlist or album mode.
                if self.core.mode == MODE_SHUFFLE and self.core.shuffle_tracks:
                    self.core.shuffle_index = 0
                    self.core.current_track = 1
                elif self.core.mode == MODE_RADIO and self.core.radio_stations:
                    self.core.radio_station_index = 0
                    self.core.current_track = 1
            wav_data = getattr(self.hw, "wav_data", None)
            if wav_data is not None:
                am_path = getattr(self.hw, "_am_wav_path", None)
                if am_path:
                    print(f"AM sound: VS1053 codec overlay ({am_path})")
                elif isinstance(wav_data, (bytes, bytearray)):
                    print(f"AM sound: PWM overlay ENABLED ({len(wav_data)} samples)")
                else:
                    print("AM sound: overlay ENABLED")
            else:
                print("AM sound: MCU overlay disabled (install AMradioSound.wav on Pico flash)")
        except Exception as e:
            print(f"Boot init error: {e}")
            self.core.current_album_index = 0
            self.core.current_track = 1
        self._start_with_am_and_recovery("Boot")

    def handle_button(self):
        if getattr(self, "_ipc_synthetic_active", False):
            return
        curr = 0 if self.hw.is_button_pressed() else 1
        now = ticks_ms()
        if self.last_button == 1 and curr == 0:
            self.press_start = now
            print(f"Button PRESSED at {now}")
            self.core.on_button_press()
        elif self.last_button == 0 and curr == 1:
            press_dur = ticks_diff(now, self.press_start)
            print(f"Button RELEASED at {now}, duration: {press_dur}ms")
            self.core.on_button_release()
            time.sleep_ms(40)
        self.last_button = curr

    def _start_with_am_and_recovery(self, context="Boot"):
        try:
            if self.hw.np is not None:
                self.hw.np[0] = (0, 10, 0)
                self.hw.np.write()
            onboard = getattr(self.hw, "_onboard_np", None)
            if onboard is not None:
                onboard[0] = (0, 10, 0)
                onboard.write()
        except Exception:
            pass
        tr = self.core._get_current_track()
        if tr:
            folder = tr.get('folder', 1)
            track = tr.get('track_number', 1)
            title = tr.get('title', 'Unknown')
            print(f"{context}: '{title}' (folder={folder}, track={track})")
        else:
            folder = self.core.current_album_index + 1
            track = self.core.current_track
            print(f"{context}: folder={folder}, track={track} (no metadata)")

        start_with_am = getattr(self.hw, "start_with_am", None)
        if start_with_am is not None:
            confirmed = start_with_am(folder, track)
        else:
            self.hw.play_am_overlay()
            self.hw.play_track(folder, track)
            time.sleep_ms(800)
            confirmed = self.hw.is_playing()

        self.prev_busy = 1
        self._busy_high_since = 0
        started = bool(confirmed or self.hw.is_playing())
        outcome = {}
        get_start_outcome = getattr(self.hw, "get_last_start_outcome", None)
        if callable(get_start_outcome):
            try:
                outcome = get_start_outcome() or {}
            except Exception:
                outcome = {}

        status = outcome.get("status", "unknown")
        reason = outcome.get("reason", "unknown")
        outcome_tick = int(outcome.get("tick_ms", 0) or 0)
        outcome_folder = outcome.get("folder")
        outcome_track = outcome.get("track")
        fresh = (
            outcome_tick > 0
            and ticks_diff(ticks_ms(), outcome_tick) <= 9000
            and outcome_folder == folder
            and outcome_track == track
        )
        if not fresh:
            status = "unknown"
            reason = "no_fresh_start_outcome"
        # A fresh "pending" outcome means the play command was issued but BUSY
        # is slow to confirm (typical after AM sequence / first folder access).
        # Treat as started — the main-loop BUSY/UART fallback will detect the
        # track. Firing a second-chance stop+replay here would interrupt a track
        # that is very likely already playing.
        if not started and fresh and status == "pending":
            started = True
            print(
                f"{context} pending start assumed (fresh outcome: reason={reason}) "
                "- leaving main-loop to confirm"
            )
        if started:
            self.core.is_playing = True
            self._was_playing = True
            self._start_unconfirmed_streak = 0
            self._start_explicit_error_streak = 0
        else:
            explicit = (status == "explicit_error")
            if explicit:
                self._start_explicit_error_streak += 1
                self._start_unconfirmed_streak = 0
            else:
                self._start_unconfirmed_streak += 1
                self._start_explicit_error_streak = 0

            print(
                f"{context} playback not confirmed "
                f"(start_confirm={status}, reason={reason}) - second chance"
            )
            play_track = getattr(self.hw, "play_track", None)
            if callable(play_track):
                time.sleep_ms(120)
                if play_track(folder, track, start_ms=0, folder_wrap=False):
                    print(f"{context} second-chance confirmed (play_track)")
                    self._was_playing = True
                    self._start_unconfirmed_streak = 0
                    self._start_explicit_error_streak = 0
                    return
                if self.hw.is_playing():
                    print(f"{context} second-chance confirmed (is_playing)")
                    self._was_playing = True
                    self._start_unconfirmed_streak = 0
                    self._start_explicit_error_streak = 0
                    return

            refreshed = {}
            if callable(get_start_outcome):
                try:
                    refreshed = get_start_outcome() or {}
                except Exception:
                    refreshed = {}
            refreshed_status = refreshed.get("status", status)
            refreshed_reason = refreshed.get("reason", reason)
            explicit = (refreshed_status == "explicit_error")
            if explicit:
                self._start_explicit_error_streak = max(
                    self._start_explicit_error_streak, 1
                )
                self._start_unconfirmed_streak = 0

            should_reset = False
            if explicit and self._start_explicit_error_streak >= self._reset_after_explicit:
                should_reset = True
            if (not explicit) and self._start_unconfirmed_streak >= self._reset_after_unconfirmed:
                should_reset = True

            if not should_reset:
                print(
                    f"{context} reset deferred "
                    f"(start_confirm={refreshed_status}, reason={refreshed_reason}, "
                    f"unconfirmed_streak={self._start_unconfirmed_streak}, "
                    f"explicit_streak={self._start_explicit_error_streak})"
                )
                return

            if hasattr(self.hw, "_df_reset"):
                print(
                    f"{context} escalating to DF reset "
                    f"(start_confirm={refreshed_status}, reason={refreshed_reason})"
                )
                self.hw._df_reset()
                time.sleep_ms(DF_BOOT_MS)
                self.hw._df_set_vol(getattr(self.hw, "_df_volume", 28))
                self.hw._df_stop()
                time.sleep_ms(POST_CMD_GUARD_MS)
                self.hw._df_play_folder_track(folder, track)
                if getattr(self.hw, "_wait_for_busy_low", lambda _: False)(1500):
                    print(f"{context} second-chance confirmed (BUSY LOW)")
                    getattr(self.hw, "_note_track_learned", lambda _f, _t: None)(folder, track)
                    self._start_unconfirmed_streak = 0
                    self._start_explicit_error_streak = 0
                else:
                    print(f"{context} second-chance still not confirmed")
            else:
                self.hw.play_track(folder, track)
                time.sleep_ms(800)
                if self.hw.is_playing():
                    print(f"{context} second-chance confirmed (is_playing)")
                    self._start_unconfirmed_streak = 0
                    self._start_explicit_error_streak = 0
                else:
                    print(f"{context} second-chance still not confirmed")

    def _play_am_for_change(self):
        reason = "mode_change"
        get_reason = getattr(self.hw, "get_delay_playback_reason", None)
        if callable(get_reason):
            try:
                reason = get_reason() or "mode_change"
            except Exception:
                reason = "mode_change"
        if reason == "station_change":
            ctx = "Station change"
        elif reason == "power_on":
            ctx = "Power-on"
        else:
            ctx = "Mode change"
        self._start_with_am_and_recovery(ctx)

    def _fire_track_finished(self):
        self._was_playing = False
        old_tr = self.core._get_current_track()
        old_title = old_tr.get('title', 'Unknown') if old_tr else 'Unknown'
        old_album = self.core.current_album_index
        old_track = self.core.current_track
        self.core.on_track_finished()
        # If the new track's play command was sent (even if unconfirmed / still seeking),
        # end-detection will be armed.  Keep _was_playing=True so the BUSY LOW→HIGH edge
        # is still usable as a fallback when the slow-seeking track eventually plays.
        if getattr(self.hw, "_uart_track_end_armed", False):
            self._was_playing = True
        new_tr = self.core._get_current_track()
        new_title = new_tr.get('title', 'Unknown') if new_tr else 'Unknown'
        new_album = self.core.current_album_index
        new_track = self.core.current_track
        print(f"Auto-advanced: '{old_title}' -> '{new_title}' (station {old_album+1} track {old_track} -> station {new_album+1} track {new_track})")

    def handle_track_finished(self):
        """Detect end of track: BUSY pin first (DFPlayer hardware truth), then UART 0x3D.

        UART 0x3D is unreliable (global track index, queued duplicates). We only treat it
        as track-end when the BUSY pin already reads idle (HIGH), i.e. playback has stopped.
        There is no millisecond stale-age window; that discarded real short-track ends.
        """
        if not self.rail2_on:
            return

        pin_busy = getattr(self.hw, "pin_busy", None)
        if pin_busy is None:
            if self._was_playing and not self.hw.is_playing():
                self._was_playing = False
                print("Track finished (stream end)")
                self._fire_track_finished()
            elif self.hw.is_playing():
                self._was_playing = True
            return

        # --- Primary: BUSY LOW while playing -> HIGH when idle (classic DFPlayer). ---
        BUSY_DEBOUNCE_MS = 400
        STUCK_BUSY_QUERY_MIN_MS = 6000
        STUCK_QUERY_INTERVAL_MS = 2500
        STUCK_QUERY_REQUIRED_ZEROES = 2
        b = pin_busy.value()
        now = ticks_ms()
        # Treat DFPlayer BUSY (hw.is_playing) as authoritative: core.is_playing can lag
        # after AM overlay / deferred starts and would suppress real track-end edges.
        track_expected = bool(
            self.core.is_playing or self._was_playing or self.hw.is_playing()
        )
        ignore_until = getattr(self.hw, "ignore_busy_until", 0)
        start_tick = getattr(self.hw, "_playback_start_tick", 0)

        if (
            b == 0
            and track_expected
            and not getattr(self.hw, "_uart_track_end_armed", False)
            and getattr(self.hw, "query_status", None)
            and ticks_diff(now, ignore_until) >= 0
            and start_tick
            and ticks_diff(now, start_tick) > STUCK_BUSY_QUERY_MIN_MS
        ):
            if ticks_diff(now, self._last_stuck_query_ms) >= STUCK_QUERY_INTERVAL_MS:
                self._last_stuck_query_ms = now
                qs = self.hw.query_status()
                if qs == 0:
                    self._stuck_status_zero_count += 1
                    print(
                        "DF: query_status=stopped while BUSY LOW "
                        f"({self._stuck_status_zero_count}/{STUCK_QUERY_REQUIRED_ZEROES})"
                    )
                    if self._stuck_status_zero_count >= STUCK_QUERY_REQUIRED_ZEROES:
                        print("Track finished (query_status fallback confirmed)")
                        self._stuck_status_zero_count = 0
                        self._busy_high_since = 0
                        self.prev_busy = 1
                        self._fire_track_finished()
                        self.prev_busy = pin_busy.value()
                        return
                else:
                    self._stuck_status_zero_count = 0

        if b == 0:
            if self.core.is_playing or self.hw.is_playing():
                self._was_playing = True
            self._busy_high_since = 0
        elif b == 1 and self.prev_busy == 0:
            if track_expected:
                self._busy_high_since = now
            else:
                self._busy_high_since = 0
            self._stuck_status_zero_count = 0
        if b == 1 and self._busy_high_since > 0:
            if ticks_diff(now, self._busy_high_since) >= BUSY_DEBOUNCE_MS and track_expected:
                if ticks_diff(now, ignore_until) >= 0:
                    print("Track finished (BUSY)")
                    self._busy_high_since = 0
                    self._fire_track_finished()
                    self.prev_busy = pin_busy.value()
                    return
        self.prev_busy = b

        # --- Secondary: UART 0x3D only when BUSY says idle (avoids bogus advances). ---
        if getattr(self.hw, "check_track_finished_uart", None) and self.hw.check_track_finished_uart():
            armed = getattr(self.hw, "_uart_track_end_armed", False)
            finished_num = getattr(self.hw, "_track_finished_track_num", None)
            if not armed:
                getattr(self.hw, "consume_track_finished_uart", lambda: None)()
                self._log_uart_decision("discard:unarmed", finished_num)
                return
            if pin_busy.value() == 0:
                getattr(self.hw, "consume_track_finished_uart", lambda: None)()
                self._log_uart_decision("discard:busy_low", finished_num)
                return

            consumed_num = getattr(self.hw, "consume_track_finished_uart", lambda: None)()
            consumed_num = consumed_num if consumed_num is not None else finished_num
            self.hw._uart_track_end_armed = False
            self._log_uart_decision("accept", consumed_num)
            self.prev_busy = pin_busy.value()
            self._fire_track_finished()

    def _log_uart_decision(self, reason: str, track_num, extra: str = ""):
        now = ticks_ms()
        if (
            track_num == self._last_uart_decision_track
            and reason == self._last_uart_decision_reason
            and ticks_diff(now, self._last_uart_decision_tick) < 300
        ):
            return
        self._last_uart_decision_track = track_num
        self._last_uart_decision_reason = reason
        self._last_uart_decision_tick = now
        if extra:
            print("DF: UART track-finished {} track={} {}".format(reason, track_num, extra))
        else:
            print("DF: UART track-finished {} track={}".format(reason, track_num))

    def handle_power_change(self):
        raw = 1 if self.hw.is_power_on() else 0
        if raw != self._pwr_db_raw:
            self._pwr_db_raw = raw
            self._pwr_db_count = 1
            return
        self._pwr_db_count += 1
        if self._pwr_db_count < 8:
            return
        sense = raw
        if sense != self.last_sense:
            if sense == 0:
                print("Power sense LOW - Rail 2 power OFF (pot turned OFF)")
                self.rail2_on = False
                self.core.power_off()
            else:
                print("Power sense HIGH - Rail 2 power ON (pot turned ON)")
                self.rail2_on = True
                reset = getattr(self.hw, "reset_dfplayer", None)
                if reset is not None:
                    reset()
                self.core.power_on_handler()
                self._start_with_am_and_recovery("Power-on")
            self.last_sense = sense

    def run(self):
        print("BASIC MODE active. Button patterns:")
        print("  tap = next track")
        print("  double-tap = previous track")
        print("  triple-tap = restart station")
        print("  four-tap = previous station")
        print("  five-tap = first station (ordered mode)")
        print("  hold = next station")
        print("  tap + hold = exit track shuffle to ordered station mode")
        print("  double-tap + hold = track shuffle in current station (repeat = reshuffle)")
        print("  triple-tap + hold = first station + track shuffle (reshuffle)")

        while True:
            try:
                ts = getattr(self.hw, "tick_stream", None)
                if ts:
                    n = 4 if getattr(self.hw, "_stream_file", None) is not None else 1
                    for _ in range(n):
                        ts()
                if getattr(self.hw, '_df_read_pending', None):
                    self.hw._df_read_pending()

                poll_ipc(self)
                self.handle_button()

                old_track_idx = self.core.current_track
                self.core.tick()

                if self.hw._delay_playback:
                    self._play_am_for_change()
                    self._busy_high_since = 0

                self.handle_track_finished()
                # tick() or auto-advance may have changed track; reset BUSY debounce
                if self.core.current_track != old_track_idx:
                    self._busy_high_since = 0
                self.handle_power_change()

                if getattr(self.hw, 'poll_volume_adc', None):
                    self.hw.poll_volume_adc()

                update_led = getattr(self.hw, "update_playback_led", None)
                if update_led is not None:
                    update_led(is_playing=getattr(self.core, "is_playing", False))
            except OSError as e:
                print("Main loop recoverable error:", e)

            time.sleep_ms(1)


firmware = None

def main():
    global firmware
    print("===== Vintage Radio main() [BASIC MODE] =====")
    try:
        firmware = VintageRadioFirmware()
        firmware.wait_for_power()
        print("Boot sequence starting...")
        firmware.boot_sequence()
        firmware.run()
    except Exception as e:
        err_msg = "FATAL: " + str(e)
        print(err_msg)
        try:
            import sys
            sys.print_exception(e)
        except Exception:
            pass
        try:
            import neopixel
            from pin_config_loader import get_pin
            neo_pin = get_pin("neopixel", 16)
            np = neopixel.NeoPixel(Pin(neo_pin), 1)
            np[0] = (10, 0, 0)
            np.write()
        except Exception:
            pass
        while True:
            time.sleep_ms(2000)
            print(err_msg)


if __name__ == "__main__":
    main()
