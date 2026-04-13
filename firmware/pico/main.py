# Vintage Radio Firmware - Using Shared RadioCore
# This firmware uses the same logic as the GUI emulator via radio_core.py
#
# Hardware: Raspberry Pi Pico + DFPlayer Mini
# Compatible with MicroPython

from machine import Pin
import time
import builtins

_print_orig = builtins.print


def _firmware_log_clock():
    try:
        lt = time.localtime()
        ms = time.ticks_ms() % 1000
        return f"{lt[3]:02d}:{lt[4]:02d}:{lt[5]:02d}:{ms:03d}"
    except Exception:
        return "00:00:00:000"


def print(*args, **kwargs):  # noqa: A001 — replace global print for serial timestamps
    prefix = f"[{_firmware_log_clock()}]"
    if args:
        args = (prefix,) + args
    else:
        args = (prefix,)
    return _print_orig(*args, **kwargs)


builtins.print = print

# Import shared core logic
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

# Import hardware implementation
from components.dfplayer_hardware import DFPlayerHardware
from components.vintage_radio_ipc import poll_ipc

# ===========================
#      MAIN FIRMWARE CLASS
# ===========================

class VintageRadioFirmware:
    """
    Main firmware class that runs the Vintage Radio.
    
    Uses RadioCore for state machine logic and DFPlayerHardware for hardware access.
    This ensures the firmware runs the exact same logic as the GUI emulator.
    """
    
    def __init__(self):
        print("Booting Vintage Radio (RadioCore-based)")
        
        # Initialize hardware interface
        self.hw = DFPlayerHardware()
        
        # Initialize core state machine
        self.core = RadioCore(self.hw)
        
        # Button state tracking (for edge detection)
        self.last_button = 1  # Not pressed (pull-up)
        self.press_start = 0
        
        # Power state
        self.rail2_on = False
        self.last_sense = 0
        
        # BUSY pin state for track-finished detection
        self.prev_busy = 1
        self._busy_high_since = 0  # Timestamp when BUSY first went HIGH (for debounce)
        self._was_playing = False  # For drivers without BUSY (e.g. VS1053) track-finished
        self._last_stuck_query_ms = 0
        self._stuck_status_zero_count = 0
        self._last_uart_decision_track = None
        self._last_uart_decision_reason = ""
        self._last_uart_decision_tick = 0
        self._ipc_synthetic_active = False
        self._pwr_db_raw = None
        self._pwr_db_count = 0

    def wait_for_power(self):
        """Wait for power sense pin to go HIGH, or skip if configured."""
        # Check if power sense check is disabled
        skip_power_check = self._check_skip_power_sense()
        
        if skip_power_check:
            print("Power sense check DISABLED (configured via debug mode)")
            self.rail2_on = True
            self.last_sense = 1 if self.hw.is_power_on() else 0
            return
        
        print("Waiting for power sense HIGH...")
        print("(Turn pot on, or create skip_power_sense.txt with 'true' to skip)")
        last_hint = ticks_ms()
        while not self.hw.is_power_on():
            if ticks_diff(ticks_ms(), last_hint) > 5000:
                print(
                    "...still waiting for power sense HIGH "
                    "(turn the volume pot ON, or skip_power_sense.txt)"
                )
                last_hint = ticks_ms()
            time.sleep_ms(20)
        
        print("Power sense HIGH detected.")
        self.rail2_on = True
        self.last_sense = 1
    
    def _check_skip_power_sense(self):
        """Check if power sense check should be skipped (from config file)."""
        try:
            with open("skip_power_sense.txt", "r") as f:
                content = f.read().strip().lower()
                result = content == "true" or content == "1"
                return result
        except OSError:
            # File doesn't exist - default to requiring power sense (safe)
            return False
    
    def _check_hw_comms(self):
        """Diagnostic: verify audio hardware is responsive after boot.

        For DFPlayer drivers runs full UART/SD check; for other drivers
        just does a test play and checks is_playing().
        """
        known_tracks = getattr(self.hw, "_known_tracks", {})
        total_expected = sum(known_tracks.values())
        num_folders = len(known_tracks)
        print(f"  Metadata: {total_expected} songs across {num_folders} folders")

        if hasattr(self.hw, "_df_read_pending") and hasattr(self.hw, "query_file_count"):
            print("--- DFPlayer comms check ---")
            self.hw._df_read_pending()
            busy = self.hw.pin_busy.value()
            print(f"  BUSY pin = {busy} (expect 1=idle)")
            fc = self.hw.query_file_count()
            if fc is not None:
                print(f"  TF file count = {fc}")
            else:
                print("  TF file count = TIMEOUT (GP1 not wired to DFPlayer TX?)")
            if fc is not None and total_expected > 0:
                if fc < total_expected:
                    print(f"  *** SD CARD INCOMPLETE: {fc} files < {total_expected} expected ***")
                else:
                    print(f"  SD card OK: {fc} files >= {total_expected} expected")
            print("  Test play: folder=1, track=1")
            self.hw._df_play_folder_track(1, 1)
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
        else:
            # VS1053 etc: skip test play to avoid start/stop before real track (can confuse decoder)
            if getattr(self.hw, "tick_stream", None) is None:
                print("--- Audio hardware check (test play) ---")
                self.hw.play_track(1, 1)
                time.sleep_ms(800)
                playing = self.hw.is_playing()
                print(f"  Test play folder=1 track=1: is_playing={playing}")
                if not playing:
                    print("  Warning: playback may not have started. Check wiring and storage.")
                self.hw.stop()
                print("--- End check ---")
            else:
                print("--- Audio hardware: VS1053 (streaming), no test play ---")
    
    def boot_sequence(self):
        """Perform boot sequence: optional hardware reset, load state, start playback with AM overlay.
        Works with any HardwareInterface; DFPlayer-specific steps are optional.
        """
        try:
            reset = getattr(self.hw, "reset_dfplayer", None)
            if reset is not None:
                reset()
            self.core.init(skip_initial_playback=True)
            self._check_hw_comms()
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
        """Handle button press and release events (edge detection only).
        
        With deferred timing, all actions happen in tick() via _resolve_input(),
        not here. This method only detects edges and delegates to RadioCore.
        """
        if getattr(self, "_ipc_synthetic_active", False):
            return
        curr = 0 if self.hw.is_button_pressed() else 1
        now = ticks_ms()
        
        # Button press edge (1 -> 0)
        if self.last_button == 1 and curr == 0:
            self.press_start = now
            print(f"Button PRESSED at {now}")
            self.core.on_button_press()
        
        # Button release edge (0 -> 1)
        elif self.last_button == 0 and curr == 1:
            press_dur = ticks_diff(now, self.press_start)
            print(f"Button RELEASED at {now}, duration: {press_dur}ms")
            self.core.on_button_release()
            time.sleep_ms(40)  # Debounce
        
        self.last_button = curr
    
    def _start_with_am_and_recovery(self, context="Boot"):
        """Start playback via AM overlay with optional second-chance recovery.

        Uses start_with_am() when the driver provides it (e.g. DFPlayer);
        otherwise calls play_am_overlay() then play_track() and confirms via is_playing().
        """
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
        fresh = (
            outcome_tick > 0
            and ticks_diff(ticks_ms(), outcome_tick) <= 9000
            and outcome.get("folder") == folder
            and outcome.get("track") == track
        )
        if not fresh:
            status = "unknown"
            reason = "no_fresh_start_outcome"

        if started:
            self.core.is_playing = True
            self._was_playing = True
        if not started:
            print(
                f"{context} playback not confirmed "
                f"(start_confirm={status}, reason={reason}) - second chance"
            )
            play_track = getattr(self.hw, "play_track", None)
            if callable(play_track):
                time.sleep_ms(120)
                if play_track(folder, track, start_ms=0, folder_wrap=False):
                    print(f"{context} second-chance confirmed (play_track)")
                    self.core.is_playing = True
                    self._was_playing = True
                    return
            if hasattr(self.hw, "_df_reset"):
                self.hw._df_reset()
                time.sleep_ms(DF_BOOT_MS)
                self.hw._df_set_vol(getattr(self.hw, "_df_volume", 28))
                self.hw._df_stop()
                time.sleep_ms(POST_CMD_GUARD_MS)
                self.hw._df_play_folder_track(folder, track)
                if getattr(self.hw, "_wait_for_busy_low", lambda _: False)(1500):
                    print(f"{context} second-chance confirmed (BUSY LOW)")
                    self.core.is_playing = True
                    getattr(self.hw, "_note_track_learned", lambda _f, _t: None)(folder, track)
                else:
                    print(f"{context} second-chance still not confirmed")
            else:
                self.hw.play_track(folder, track)
                time.sleep_ms(800)
                if self.hw.is_playing():
                    print(f"{context} second-chance confirmed (is_playing)")
                    self.core.is_playing = True
                else:
                    print(f"{context} second-chance still not confirmed")
    
    def _play_am_for_change(self):
        """Play AM overlay for mode/album change. Called when delay_playback is set."""
        self._start_with_am_and_recovery("Mode change")
    
    def _fire_track_finished(self):
        """Advance to next track and log (shared by UART and BUSY paths)."""
        old_tr = self.core._get_current_track()
        old_title = old_tr.get('title', 'Unknown') if old_tr else 'Unknown'
        old_album = self.core.current_album_index
        old_track = self.core.current_track
        self.core.on_track_finished()
        new_tr = self.core._get_current_track()
        new_title = new_tr.get('title', 'Unknown') if new_tr else 'Unknown'
        new_album = self.core.current_album_index
        new_track = self.core.current_track
        print(f"Track finished: '{old_title}' -> '{new_title}' (album {old_album+1} track {old_track} -> album {new_album+1} track {new_track})")
    
    def handle_track_finished(self):
        """BUSY pin first; UART 0x3D only when BUSY is idle (playback stopped)."""
        if not self.rail2_on:
            return

        pin_busy = getattr(self.hw, "pin_busy", None)
        if pin_busy is None:
            # No BUSY pin (e.g. VS1053): use is_playing() transition
            if self._was_playing and not self.hw.is_playing():
                self._was_playing = False
                print("Track finished (stream end)")
                self._fire_track_finished()
            elif self.hw.is_playing():
                self._was_playing = True
            return
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
            if ticks_diff(now, getattr(self, "_last_stuck_query_ms", 0)) >= STUCK_QUERY_INTERVAL_MS:
                self._last_stuck_query_ms = now
                qs = self.hw.query_status()
                if qs == 0:
                    self._stuck_status_zero_count = getattr(self, "_stuck_status_zero_count", 0) + 1
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
                    self.prev_busy = pin_busy.value()
                    return
        self.prev_busy = b

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
    
    def _quick_sd_check(self, target_folder=None, target_track=None):
        """Optional SD/file count check after power-on (DFPlayer and similar)."""
        query_file_count = getattr(self.hw, "query_file_count", None)
        known_tracks = getattr(self.hw, "_known_tracks", {})
        total_expected = sum(known_tracks.values())
        num_folders = len(known_tracks)
        if query_file_count is None:
            if total_expected > 0:
                print(f"SD check: metadata expects {total_expected} songs across {num_folders} folders")
            return
        fc = query_file_count()
        if fc is not None:
            print(f"SD check: device sees {fc} files, metadata expects {total_expected} songs")
            if total_expected > 0 and fc < total_expected:
                print(f"  WARNING: fewer files ({fc}) than metadata expects ({total_expected})")
        else:
            print(f"SD check: file count query timed out")
            if total_expected > 0:
                print(f"  Metadata expects {total_expected} songs across {num_folders} folders")

    def handle_power_change(self):
        """Handle power on/off via power sense pin."""
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
                self._quick_sd_check()
                self.core.power_on_handler()
                self._start_with_am_and_recovery("Power-on")

            self.last_sense = sense
    
    def run(self):
        """Main loop."""
        print("Button active. Patterns:")
        print("  tap = next track")
        print("  double-tap = previous track")
        print("  triple-tap = restart album")
        print("  hold = next album")
        print("  tap + hold = toggle album/playlist")
        print("  double-tap + hold = shuffle current")
        print("  triple-tap + hold = shuffle library")
        
        while True:
            try:
                # VS1053: multiple feeds per loop iteration to avoid buffer underrun (slow-mo sound)
                ts = getattr(self.hw, "tick_stream", None)
                if ts:
                    n = 4 if getattr(self.hw, "_stream_file", None) is not None else 1
                    for _ in range(n):
                        ts()
                # Drain DFPlayer UART responses (track-finished 0x3D, errors 0x40, ACKs, etc.)
                if getattr(self.hw, '_df_read_pending', None):
                    self.hw._df_read_pending()

                poll_ipc(self)
                # Handle button events (edge detection only)
                self.handle_button()
                
                # Process deferred input (tap window timeout)
                old_track_idx = self.core.current_track
                self.core.tick()
                
                # After tick(), check if a mode/album change set delay_playback
                if self.hw._delay_playback:
                    self._play_am_for_change()
                    self._busy_high_since = 0
                
                # Detect track finished
                self.handle_track_finished()
                if self.core.current_track != old_track_idx:
                    self._busy_high_since = 0
                
                # Watch power sense line
                self.handle_power_change()
                
                # Poll volume potentiometer ADC (self-throttled to ~50ms intervals)
                if getattr(self.hw, 'poll_volume_adc', None):
                    self.hw.poll_volume_adc()
            except OSError as e:
                print("Main loop recoverable error:", e)
            
            # Short sleep; tick_stream feeds data as fast as DREQ allows
            time.sleep_ms(1)


# ===========================
#      ENTRY POINT
# ===========================

# Global firmware instance (for debug access)
firmware = None

def main():
    """Main entry point for the firmware."""
    global firmware
    print("===== Vintage Radio main() =====")
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
        # Red LED to signal crash (visible without serial)
        try:
            import neopixel
            from pin_config_loader import get_pin
            neo_pin = get_pin("neopixel", 16)
            np = neopixel.NeoPixel(Pin(neo_pin), 1)
            np[0] = (10, 0, 0)
            np.write()
        except Exception:
            pass
        # Keep repeating the error so Device Debug can pick it up after connecting
        while True:
            time.sleep_ms(2000)
            print(err_msg)


# Run if executed directly
if __name__ == "__main__":
    main()
