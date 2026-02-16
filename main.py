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
        last_hint = ticks_ms()
        
        while not self.hw.is_power_on():
            if ticks_diff(ticks_ms(), last_hint) > 1500:
                print("...still waiting for GP14 HIGH")
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
    
    def boot_sequence(self):
        """Perform boot sequence: reset DFPlayer, load state, start playback with AM overlay.
        Matches baseline 5.9.1: one start inside AM overlay (no double-start).
        """
        # Reset DFPlayer and wait for boot
        self.hw.reset_dfplayer()
        
        # Load state only; do not start playback yet (we start with AM overlay below)
        self.core.init(skip_initial_playback=True)
        
        # Report AM sound status
        if self.hw.wav_data is not None:
            print(f"AM sound: PWM overlay ENABLED ({len(self.hw.wav_data)} samples on Pico flash)")
        else:
            print(f"AM sound: PWM overlay disabled, using DFPlayer SD fallback (folder={self.hw._am_folder}, track={self.hw._am_track})")
            print(f"AM sound: For overlay, copy AMradioSound.wav to Pico via 'Install to Pico'")
        
        # Start with AM overlay (single start, same as baseline start_sequence_synced)
        tr = self.core._get_current_track()
        if tr:
            folder = tr.get("folder", 1)
            track = tr.get("track_number", 1)
            title = tr.get("title", "Unknown")
            artist = tr.get("artist", "Unknown")
            print(f"Boot: Using track from metadata - '{title}' by {artist} (folder={folder:02d}, track={track:03d}, album_idx={self.core.current_album_index}, logical_track={self.core.current_track})")
        else:
            folder = self.core.current_album_index + 1
            track = self.core.current_track
            print(f"Boot: No track dict, using fallback - folder={folder:02d}, track={track:03d}, album_idx={self.core.current_album_index}")
            print(f"Boot: WARNING - This means metadata wasn't loaded correctly!")
        confirmed = self.hw.start_with_am(folder, track)
        
        if confirmed:
            print("Boot playback confirmed")
        else:
            print("Boot playback not confirmed - attempting second chance")
            self.hw.reset_dfplayer()
            self.hw.set_volume(100)
            time.sleep_ms(POST_CMD_GUARD_MS)
            self.hw.play_track(folder, track)
    
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
    
    def _play_am_for_change(self):
        """Play AM overlay for mode/album change. Called when delay_playback is set."""
        tr = self.core._get_current_track()
        if tr:
            folder = tr.get('folder', 1)
            track = tr.get('track_number', 1)
            title = tr.get('title', 'Unknown')
            print(f"AM overlay triggered: '{title}' (folder={folder}, track={track})")
        else:
            folder = self.core.current_album_index + 1
            track = self.core.current_track
            print(f"AM overlay triggered: folder={folder}, track={track} (no metadata)")
        self.hw.start_with_am(folder, track)
    
    def handle_track_finished(self):
        """Detect track finished via BUSY pin with debouncing.
        
        Instead of triggering on a single 0->1 edge (which can be caused by
        brief glitches from volume changes or command sequencing), we require
        BUSY to stay HIGH continuously for BUSY_DEBOUNCE_MS before triggering
        the track-finished event.
        """
        BUSY_DEBOUNCE_MS = 500  # BUSY must stay HIGH for this long to confirm track end
        
        if not self.rail2_on:
            return
        
        b = self.hw.pin_busy.value()
        now = ticks_ms()
        
        if b == 0:
            # BUSY is LOW (playing) — reset debounce timer
            self._busy_high_since = 0
        elif b == 1 and self.prev_busy == 0:
            # BUSY just went HIGH — start debounce timer
            self._busy_high_since = now
        
        # Check if BUSY has been confirmed HIGH for long enough
        if b == 1 and self._busy_high_since > 0:
            if ticks_diff(now, self._busy_high_since) >= BUSY_DEBOUNCE_MS:
                # Check if we should ignore this (e.g., just started a new track)
                if ticks_diff(now, self.hw.ignore_busy_until) >= 0:
                    print("BUSY confirmed HIGH: track finished")
                    self._busy_high_since = 0  # Reset so we don't re-trigger
                    
                    # Get current track info before advancing
                    old_tr = self.core._get_current_track()
                    old_title = old_tr.get('title', 'Unknown') if old_tr else 'Unknown'
                    old_album = self.core.current_album_index
                    old_track = self.core.current_track
                    
                    # Advance to next track (this will save state and start playback)
                    self.core.on_track_finished()
                    
                    # Get new track info after advancing
                    new_tr = self.core._get_current_track()
                    new_title = new_tr.get('title', 'Unknown') if new_tr else 'Unknown'
                    new_album = self.core.current_album_index
                    new_track = self.core.current_track
                    print(f"Track finished: '{old_title}' -> '{new_title}' (album {old_album+1} track {old_track} -> album {new_album+1} track {new_track})")
        
        self.prev_busy = b
    
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
                self.core.power_on_handler()
                
                # Play AM overlay on power-on (use metadata for correct DFPlayer folder/track)
                tr = self.core._get_current_track()
                if tr:
                    folder = tr.get('folder', 1)
                    track = tr.get('track_number', 1)
                    title = tr.get('title', 'Unknown')
                    print(f"Power-on AM overlay: '{title}' (folder={folder}, track={track})")
                else:
                    folder = self.core.current_album_index + 1
                    track = self.core.current_track
                    print(f"Power-on AM overlay: folder={folder}, track={track} (no metadata)")
                self.hw.start_with_am(folder, track)
            
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
            # Handle button events (edge detection only)
            self.handle_button()
            
            # Process deferred input (tap window timeout)
            # Actions like mode switch, album change, etc. happen inside tick()
            self.core.tick()
            
            # After tick(), check if a mode/album change set delay_playback
            # This means switch_mode() or _next_album() wants AM overlay before playback
            if self.hw._delay_playback:
                self._play_am_for_change()
            
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
    firmware = VintageRadioFirmware()
    firmware.wait_for_power()
    firmware.boot_sequence()
    firmware.run()


# Run if executed directly
if __name__ == "__main__":
    main()
