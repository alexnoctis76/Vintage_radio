# Vintage Radio Firmware - Using Shared RadioCore
# This firmware uses the same logic as the GUI emulator via radio_core.py
#
# Hardware: Raspberry Pi Pico + DFPlayer Mini
# Compatible with MicroPython

from machine import Pin
import time

# Import shared core logic
from radio_core import (
    RadioCore, 
    HardwareInterface,
    MODE_ALBUM, MODE_PLAYLIST, MODE_SHUFFLE, MODE_RADIO,
    FADE_IN_S, DF_BOOT_MS, BUSY_CONFIRM_MS, POST_CMD_GUARD_MS,
    ticks_ms, ticks_diff,
)

# Import hardware implementation
from components.dfplayer_hardware import DFPlayerHardware

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
    
    def wait_for_power(self):
        """Wait for power sense (GP14) to go HIGH, or skip if configured."""
        # Check if power sense check is disabled
        skip_power_check = self._check_skip_power_sense()
        
        if skip_power_check:
            print("Power sense check DISABLED (configured via debug mode)")
            self.rail2_on = True
            self.last_sense = 1
            return
        
        print("Waiting for GP14 HIGH (power sense)...")
        print("(Turn pot on, or create skip_power_sense.txt with 'true' to skip)")
        last_hint = ticks_ms()
        while not self.hw.is_power_on():
            if ticks_diff(ticks_ms(), last_hint) > 500:
                print("...waiting for GP14 HIGH")
                last_hint = ticks_ms()
            time.sleep_ms(20)
        
        print("GP14 HIGH detected.")
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
    
    def _check_dfplayer_comms(self):
        """Diagnostic: verify DFPlayer is alive after boot."""
        print("--- DFPlayer comms check ---")
        self.hw._df_read_pending()
        
        busy = self.hw.pin_busy.value()
        print(f"  BUSY pin = {busy} (expect 1=idle)")
        
        fc = self.hw.query_file_count()
        if fc is not None:
            print(f"  TF file count = {fc}")
        else:
            print("  TF file count = TIMEOUT (GP1 not wired to DFPlayer TX?)")

        total_expected = sum(self.hw._known_tracks.values())
        num_folders = len(self.hw._known_tracks)
        print(f"  Metadata: {total_expected} songs across {num_folders} folders")
        if fc is not None and total_expected > 0:
            if fc < total_expected:
                print(f"  *** SD CARD INCOMPLETE: {fc} files < {total_expected} expected ***")
                print(f"  *** Re-sync SD card from the GUI SD Card Manager ***")
            else:
                print(f"  SD card OK: {fc} files >= {total_expected} expected")

        # Test play: folder=1, track=1 (should always exist)
        print("  Test play: folder=1, track=1")
        self.hw._df_play_folder_track(1, 1)
        time.sleep_ms(500)
        busy_after = self.hw.pin_busy.value()
        self.hw._df_read_pending()
        err = self.hw._last_error_code
        print(f"  Result: BUSY={busy_after}, error={err}")
        if busy_after == 0:
            print("  DFPlayer OK: track plays")
        else:
            print("  DFPlayer NOT playing. Check wiring and SD card.")
        self.hw._df_stop()
        time.sleep_ms(100)

        self.hw._last_error_code = None
        print("--- End DFPlayer check ---")
    
    def boot_sequence(self):
        """Perform boot sequence: reset DFPlayer, load state, start playback with AM overlay.
        Matches baseline 5.9.1: one start inside AM overlay (no double-start).
        On exception, logs and still attempts to start playback with folder=1, track=1.
        """
        try:
            # Reset DFPlayer and wait for boot
            self.hw.reset_dfplayer()
            # Load state (also loads metadata with track->folder mappings)
            self.core.init(skip_initial_playback=True)
            # Diagnostic: verify DFPlayer communication (needs metadata loaded first)
            self._check_dfplayer_comms()
            # Always start from first song of current playlist/album on power-on
            self.core.current_track = 1
            if self.core.mode == "shuffle" and self.core.shuffle_tracks:
                self.core.shuffle_index = 0
            elif self.core.mode == "radio" and self.core.radio_stations:
                self.core.radio_station_index = 0
            # Report AM sound status
            if self.hw.wav_data is not None:
                print(f"AM sound: PWM overlay ENABLED ({len(self.hw.wav_data)} samples on Pico flash)")
            else:
                print(f"AM sound: PWM overlay disabled, using DFPlayer SD fallback (folder={self.hw._am_folder}, track={self.hw._am_track})")
                print(f"AM sound: For overlay, copy AMradioSound.wav to Pico via 'Install to Pico'")
        except Exception as e:
            print(f"Boot init error: {e}")
            # Ensure we have a valid track to play so _start_with_am_and_recovery doesn't use stale indices
            self.core.current_album_index = 0
            self.core.current_track = 1
        # Start with AM overlay (single start, same as baseline start_sequence_synced)
        self._start_with_am_and_recovery("Boot")
    
    def handle_button(self):
        """Handle button press and release events (edge detection only).
        
        With deferred timing, all actions happen in tick() via _resolve_input(),
        not here. This method only detects edges and delegates to RadioCore.
        """
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
        """Start playback via AM overlay with second-chance recovery on failure."""
        # Show green as soon as we're about to start playback (before any blocking DFPlayer calls)
        try:
            self.hw.np[0] = (0, 10, 0)
            self.hw.np.write()
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
        confirmed = self.hw.start_with_am(folder, track)
        self.prev_busy = 1
        self._busy_high_since = 0
        if not confirmed:
            print(f"{context} playback not confirmed - second chance")
            self.hw._df_reset()
            time.sleep_ms(DF_BOOT_MS)
            self.hw._df_set_vol(self.hw._df_volume)
            self.hw._df_stop()
            time.sleep_ms(POST_CMD_GUARD_MS)
            self.hw._df_play_folder_track(folder, track)
            if self.hw._wait_for_busy_low(1500):
                print(f"{context} second-chance confirmed (BUSY LOW)")
                self.hw._note_track_learned(folder, track)
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
        """Detect track finished: prefer UART 0x3D (instant), fall back to BUSY pin debounce."""
        if not self.rail2_on:
            return
        
        # Prefer UART track-finished (0x3D) when available — instant and unambiguous
        if getattr(self.hw, 'check_track_finished_uart', None) and self.hw.check_track_finished_uart():
            self.hw.consume_track_finished_uart()
            print("Track finished (UART 0x3D)")
            self._fire_track_finished()
            self.prev_busy = self.hw.pin_busy.value()
            return
        
        # Fallback: BUSY pin with relaxed debounce (safety net only)
        BUSY_DEBOUNCE_MS = 5000  # Long debounce; UART is primary
        b = self.hw.pin_busy.value()
        now = ticks_ms()
        
        if b == 0:
            self._busy_high_since = 0
        elif b == 1 and self.prev_busy == 0:
            self._busy_high_since = now
        
        if b == 1 and self._busy_high_since > 0:
            if ticks_diff(now, self._busy_high_since) >= BUSY_DEBOUNCE_MS:
                if ticks_diff(now, self.hw.ignore_busy_until) >= 0:
                    print("Track finished (BUSY fallback)")
                    self._busy_high_since = 0
                    self._fire_track_finished()
        
        self.prev_busy = b
    
    def _quick_sd_check(self, target_folder=None, target_track=None):
        """Quick SD card file count check after DFPlayer reset.
        
        Queries DFPlayer for total file count and compares with the total
        number of expected songs from metadata.
        """
        fc = self.hw.query_file_count()
        total_expected = sum(self.hw._known_tracks.values())
        num_folders = len(self.hw._known_tracks)
        if fc is not None:
            print(f"SD check: DFPlayer sees {fc} files, metadata expects {total_expected} songs across {num_folders} folders")
            if total_expected > 0 and fc < total_expected:
                print(f"  WARNING: SD card has fewer files ({fc}) than metadata expects ({total_expected})")
                print(f"  -> Re-sync SD card from GUI (SD Card Manager).")
        else:
            print(f"SD check: file count query timed out (GP1 not wired to DFPlayer TX?)")
            if total_expected > 0:
                print(f"  Metadata expects {total_expected} songs across {num_folders} folders")

    def handle_power_change(self):
        """Handle power on/off via GP14."""
        sense = 1 if self.hw.is_power_on() else 0
        
        if sense != self.last_sense:
            if sense == 0:
                print("GP14 LOW - Rail 2 power OFF (pot turned OFF)")
                self.rail2_on = False
                self.core.power_off()
            else:
                print("GP14 HIGH - Rail 2 power ON (pot turned ON)")
                self.rail2_on = True
                self.hw.reset_dfplayer()
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
            # Drain DFPlayer UART responses (track-finished 0x3D, errors 0x40, ACKs, etc.)
            if getattr(self.hw, '_df_read_pending', None):
                self.hw._df_read_pending()
            
            # Handle button events (edge detection only)
            self.handle_button()
            
            # Process deferred input (tap window timeout)
            # Actions like mode switch, album change, etc. happen inside tick()
            old_track_idx = self.core.current_track
            self.core.tick()
            
            # If tick() changed the track (button-driven skip), reset debounce
            if self.core.current_track != old_track_idx:
                self._busy_high_since = 0
            
            # After tick(), check if a mode/album change set delay_playback
            # This means switch_mode() or _next_album() wants AM overlay before playback
            if self.hw._delay_playback:
                self._play_am_for_change()
                self._busy_high_since = 0
            
            # Detect track finished
            self.handle_track_finished()
            
            # Watch power sense line
            self.handle_power_change()
            
            time.sleep_ms(10)


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
            np = neopixel.NeoPixel(Pin(16), 1)
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
