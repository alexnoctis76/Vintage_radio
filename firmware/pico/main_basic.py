# Vintage Radio Firmware - BASIC MODE
# Uses DFPlayer folder structure as the source of truth for stations.
# No metadata files required -- stations are discovered via UART queries.
#
# Hardware: Raspberry Pi Pico + DFPlayer Mini
# Compatible with MicroPython

from machine import Pin
import time

from radio_core import (
    RadioCore,
    HardwareInterface,
    MODE_ALBUM, MODE_PLAYLIST, MODE_SHUFFLE, MODE_RADIO,
    FADE_IN_S, DF_BOOT_MS, BUSY_CONFIRM_MS, POST_CMD_GUARD_MS,
    dfplayer_confirms_playback_stopped,
    ticks_ms, ticks_diff,
)

from components.dfplayer_hardware import DFPlayerHardware


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

    def wait_for_power(self):
        skip_power_check = self._check_skip_power_sense()
        if skip_power_check:
            print("Power sense check DISABLED (configured via debug mode)")
            self.rail2_on = True
            self.last_sense = 1
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
                folder = first.get("folder", first.get("id", 1))
                print(f"  Test play: folder={folder}, track=1")
                self.hw._df_play_folder_track(folder, 1)
                time.sleep_ms(500)
                busy_after = self.hw.pin_busy.value()
                self.hw._df_read_pending()
                err = getattr(self.hw, "_last_error_code", None)
                print(f"  Result: BUSY={busy_after}, error={err}")
                self.hw._df_stop()
                time.sleep_ms(100)
                if hasattr(self.hw, "_last_error_code"):
                    self.hw._last_error_code = None
        print("--- End DFPlayer check ---")

    def boot_sequence(self):
        try:
            reset = getattr(self.hw, "reset_dfplayer", None)
            if reset is not None:
                reset()
            self.core.init(skip_initial_playback=True)
            self._check_hw_comms()
            self.core.current_track = 1
            if self.core.mode == "shuffle" and self.core.shuffle_tracks:
                self.core.shuffle_index = 0
            elif self.core.mode == "radio" and self.core.radio_stations:
                self.core.radio_station_index = 0
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
                am_f = getattr(self.hw, "_am_folder", 99)
                am_t = getattr(self.hw, "_am_track", 1)
                print(f"AM sound: overlay disabled or N/A (fallback folder={am_f}, track={am_t})")
        except Exception as e:
            print(f"Boot init error: {e}")
            self.core.current_album_index = 0
            self.core.current_track = 1
        self._start_with_am_and_recovery("Boot")

    def handle_button(self):
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
        if confirmed or self.hw.is_playing():
            self._was_playing = True
        if not confirmed:
            print(f"{context} playback not confirmed - second chance")
            if hasattr(self.hw, "_df_reset"):
                self.hw._df_reset()
                time.sleep_ms(DF_BOOT_MS)
                self.hw._df_set_vol(getattr(self.hw, "_df_volume", 28))
                self.hw._df_stop()
                time.sleep_ms(POST_CMD_GUARD_MS)
                self.hw._df_play_folder_track(folder, track)
                if getattr(self.hw, "_wait_for_busy_low", lambda _: False)(1500):
                    print(f"{context} second-chance confirmed (BUSY LOW)")
                    getattr(self.hw, "_note_track_learned", lambda _f, _t: None)(folder, track)
                else:
                    print(f"{context} second-chance still not confirmed")
            else:
                self.hw.play_track(folder, track)
                time.sleep_ms(800)
                if self.hw.is_playing():
                    print(f"{context} second-chance confirmed (is_playing)")
                else:
                    print(f"{context} second-chance still not confirmed")

    def _play_am_for_change(self):
        self._start_with_am_and_recovery("Mode change")

    def _fire_track_finished(self):
        old_tr = self.core._get_current_track()
        old_title = old_tr.get('title', 'Unknown') if old_tr else 'Unknown'
        old_album = self.core.current_album_index
        old_track = self.core.current_track
        self.core.on_track_finished()
        new_tr = self.core._get_current_track()
        new_title = new_tr.get('title', 'Unknown') if new_tr else 'Unknown'
        new_album = self.core.current_album_index
        new_track = self.core.current_track
        print(f"Track finished: '{old_title}' -> '{new_title}' (station {old_album+1} track {old_track} -> station {new_album+1} track {new_track})")

    def handle_track_finished(self):
        if not self.rail2_on:
            return

        if getattr(self.hw, "check_track_finished_uart", None) and self.hw.check_track_finished_uart():
            armed = getattr(self.hw, "_uart_track_end_armed", False)
            if armed and not dfplayer_confirms_playback_stopped(self.hw):
                getattr(self.hw, "consume_track_finished_uart", lambda: None)()
                print("DF: UART track-finished discarded (module still playing)")
                return

            getattr(self.hw, "consume_track_finished_uart", lambda: None)()
            if armed:
                self.hw._uart_track_end_armed = False
                print("Track finished (UART)")
                pin_busy = getattr(self.hw, "pin_busy", None)
                if pin_busy is not None:
                    self.prev_busy = pin_busy.value()
                self._fire_track_finished()
            # Spurious 0x3D before playback is armed: discard without touching prev_busy
            # so the BUSY LOW->HIGH edge is still detectable.
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
        # Short debounce only: old 5000ms forced ~5s between every track.
        BUSY_DEBOUNCE_MS = 400
        # Keep status query as a rare last-resort path (not part of normal playback loop):
        # frequent 0x42 polling can cause audible pulsing/chop on some DFPlayer clones.
        STUCK_BUSY_QUERY_MIN_MS = 6000
        STUCK_QUERY_INTERVAL_MS = 2500
        STUCK_QUERY_REQUIRED_ZEROES = 2
        b = pin_busy.value()
        now = ticks_ms()
        ignore_until = getattr(self.hw, "ignore_busy_until", 0)
        start_tick = getattr(self.hw, "_playback_start_tick", 0)

        # BUSY stuck LOW but module reports stopped (some bad MP3s / clones).
        # Guard: skip when UART track-end detection is armed — 0x3D will handle end-of-track
        # cleanly. Sending 0x42 mid-track causes audible pulsing on many DFPlayer clones.
        if (
            b == 0
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
                        return
                else:
                    # Any non-zero/None response cancels this fallback window.
                    self._stuck_status_zero_count = 0

        if b == 0:
            self._busy_high_since = 0
        elif b == 1 and self.prev_busy == 0:
            self._busy_high_since = now
            self._stuck_status_zero_count = 0
        if b == 1 and self._busy_high_since > 0:
            if ticks_diff(now, self._busy_high_since) >= BUSY_DEBOUNCE_MS:
                if ticks_diff(now, ignore_until) >= 0:
                    print("Track finished (BUSY fallback)")
                    self._busy_high_since = 0
                    self._fire_track_finished()
        self.prev_busy = b

    def handle_power_change(self):
        sense = 1 if self.hw.is_power_on() else 0
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
        print("  hold = next station (in station shuffle: next station, still shuffled)")
        print("  tap + hold = exit shuffle to normal station order")
        print("  double-tap + hold = shuffle current station (repeat = reshuffle same station)")
        print("  triple-tap + hold = shuffle library")

        while True:
            try:
                ts = getattr(self.hw, "tick_stream", None)
                if ts:
                    n = 4 if getattr(self.hw, "_stream_file", None) is not None else 1
                    for _ in range(n):
                        ts()
                if getattr(self.hw, '_df_read_pending', None):
                    self.hw._df_read_pending()

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
