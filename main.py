# Vintage Radio Firmware - Using Shared RadioCore
# This firmware uses the same logic as the GUI test mode via radio_core.py
#
# Hardware: Raspberry Pi Pico + DFPlayer Mini
# Compatible with MicroPython

from machine import Pin, Timer
import time

# Import shared core logic
from radio_core import (
    RadioCore, 
    HardwareInterface,
    MODE_ALBUM, MODE_PLAYLIST, MODE_SHUFFLE, MODE_RADIO,
    FADE_IN_S, DF_BOOT_MS, LONG_PRESS_MS, TAP_WINDOW_MS, BUSY_CONFIRM_MS, POST_CMD_GUARD_MS,
    ticks_ms, ticks_diff,
)

# Import hardware implementation
from firmware.dfplayer_hardware import DFPlayerHardware

# ===========================
#      CONFIGURATION
# ===========================

MAX_ALBUM_NUM = 99
ALBUM_PROBE_MS = 650

# ===========================
#      MAIN FIRMWARE CLASS
# ===========================

class VintageRadioFirmware:
    """
    Main firmware class that runs the Vintage Radio.
    
    Uses RadioCore for state machine logic and DFPlayerHardware for hardware access.
    This ensures the firmware runs the exact same logic as the GUI test mode.
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
        
        # Track mode changes for AM overlay sequencing
        self._pending_am_overlay = False
    
    def wait_for_power(self):
        """Wait for power sense (GP14) to go HIGH."""
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
    
    def boot_sequence(self):
        """Perform boot sequence: reset DFPlayer, load state, start playback with AM overlay.
        Matches baseline 5.9.1: one start inside AM overlay (no double-start).
        """
        # Reset DFPlayer and wait for boot
        self.hw.reset_dfplayer()
        
        # Load state only; do not start playback yet (we start with AM overlay below)
        self.core.init(skip_initial_playback=True)
        
        # Start with AM overlay (single start, same as baseline start_sequence_synced)
        album_idx = self.core.current_album_index
        track = self.core.current_track
        folder = album_idx + 1  # DFPlayer folders 1-based
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
        """Handle button press and release events."""
        curr = 0 if self.hw.is_button_pressed() else 1
        now = ticks_ms()
        
        # Button press edge (1 -> 0)
        if self.last_button == 1 and curr == 0:
            self.press_start = now
            self.core.on_button_press()
        
        # Button release edge (0 -> 1)
        elif self.last_button == 0 and curr == 1:
            # Store old mode and shuffle state to detect changes
            old_mode = self.core.mode
            old_shuffle_source = getattr(self.core, '_shuffle_source_type', None)
            
            # Delegate to RadioCore (same logic as GUI)
            self.core.on_button_release()
            
            # Check if we need to play AM overlay:
            # 1. Mode changed (normal mode switch)
            # 2. Mode is shuffle AND shuffle_source_type changed (reshuffling)
            new_shuffle_source = getattr(self.core, '_shuffle_source_type', None)
            mode_changed = old_mode != self.core.mode
            shuffle_reshuffled = (
                self.core.mode == MODE_SHUFFLE and 
                old_shuffle_source != new_shuffle_source
            )
            
            # Check if this was a long press with mode switching
            press_dur = ticks_diff(now, self.press_start)
            
            # For album changes (long press alone), we need to play AM overlay
            if press_dur >= LONG_PRESS_MS and self.core.tap_count == 0:
                # Long press alone = next album, which needs AM overlay
                self._handle_album_change_with_am()
            elif mode_changed or shuffle_reshuffled:
                # Mode changed or shuffle reinitialized - play AM overlay
                if mode_changed:
                    print(f"Mode changed from {old_mode} to {self.core.mode}, playing AM overlay")
                else:
                    print(f"Shuffle reinitialized (source: {old_shuffle_source} -> {new_shuffle_source}), playing AM overlay")
                
                # Mark that we need to play AM overlay
                # RadioCore will call play_track(), but we'll intercept it with start_with_am()
                self._pending_am_overlay = True
                
                # Get the track that RadioCore wants to play
                # RadioCore's switch_mode() or shuffle init already set current_album_index and current_track
                folder = self.core.current_album_index + 1
                track = self.core.current_track
                
                # Play AM overlay with current track (this will start the track after AM finishes)
                self.hw.start_with_am(folder, track)
                self._pending_am_overlay = False
            
            time.sleep_ms(40)  # Debounce
        
        self.last_button = curr
    
    def _handle_album_change_with_am(self):
        """Handle album change with AM overlay (long press alone)."""
        folder = self.core.current_album_index + 1
        track = self.core.current_track
        
        # Probe silently first
        if self._probe_album_silent(folder, track):
            # Album exists, play with AM
            self.hw.start_with_am(folder, track)
        else:
            # Album doesn't exist, wrap to album 1
            print(f"Album {folder} did not confirm. Wrapping to album 1.")
            self.core.current_album_index = 0
            self.core.current_track = 1
            self.core._save_state("wrap to album 1")
            self.hw.start_with_am(1, 1)
    
    def _probe_album_silent(self, folder, track):
        """Silent probe to check if an album exists."""
        print(f"Probe album (silent): folder {folder} track {track}")
        self.hw._df_set_vol(0)
        self.hw._df_stop()
        time.sleep_ms(POST_CMD_GUARD_MS)
        self.hw._df_play_folder_track(folder, track)
        
        start = ticks_ms()
        while ticks_diff(ticks_ms(), start) < ALBUM_PROBE_MS:
            if self.hw.pin_busy.value() == 0:
                return True
            time.sleep_ms(25)
        return False
    
    def handle_track_finished(self):
        """Detect track finished via BUSY edge and trigger auto-advance."""
        if not self.rail2_on:
            return
        
        b = self.hw.pin_busy.value()
        
        # Check for BUSY edge (0 -> 1 = track finished)
        if self.prev_busy == 0 and b == 1:
            # Check if we should ignore this edge
            if ticks_diff(ticks_ms(), self.hw.ignore_busy_until) >= 0:
                print("BUSY edge: track finished")
                self.core.on_track_finished()
        
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
                
                # Play AM overlay on power-on
                folder = self.core.current_album_index + 1
                track = self.core.current_track
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
            # Handle button events
            self.handle_button()
            
            # Process tap window timeout
            self.core.tick()
            
            # Detect track finished
            self.handle_track_finished()
            
            # Watch power sense line
            self.handle_power_change()
            
            time.sleep_ms(10)


# ===========================
#      ENTRY POINT
# ===========================

def main():
    """Main entry point for the firmware."""
    firmware = VintageRadioFirmware()
    firmware.wait_for_power()
    firmware.boot_sequence()
    firmware.run()


# Run if executed directly
if __name__ == "__main__":
    main()
