# Vintage Radio Software - Microcontroller-Only Mode
# This software runs on Raspberry Pi Pico without DFPlayer Mini
# Uses RadioCore for state machine logic and a microcontroller-only hardware implementation
#
# Hardware: Raspberry Pi Pico (audio via PWM or I2S)
# Compatible with MicroPython
#
# NOTE: This is a placeholder for future microcontroller-only hardware implementation.
# Currently, the system uses DFPlayer for audio playback. This file would be used
# if you want to implement direct audio playback on the Pico (e.g., via I2S DAC).

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

# Import hardware implementation (placeholder - would need to be created)
# from firmware.microcontroller_hardware import MicrocontrollerHardware

# ===========================
#      CONFIGURATION
# ===========================

# ===========================
#      MAIN SOFTWARE CLASS
# ===========================

class VintageRadioMicrocontroller:
    """
    Main software class for microcontroller-only mode.
    
    This mode would use direct audio playback on the Pico (e.g., I2S DAC)
    instead of DFPlayer Mini. This is a placeholder implementation.
    
    NOTE: This requires implementing MicrocontrollerHardware class that:
    - Plays audio files directly from SD card (MP3/WAV decoding on Pico)
    - Implements HardwareInterface interface
    - Handles button, power sense, NeoPixel, etc.
    """
    
    def __init__(self):
        print("Booting Vintage Radio (Microcontroller-Only Mode)")
        print("NOTE: This mode requires MicrocontrollerHardware implementation")
        
        # TODO: Initialize microcontroller-only hardware interface
        # self.hw = MicrocontrollerHardware()
        
        # For now, this is a placeholder
        raise NotImplementedError(
            "Microcontroller-only mode requires MicrocontrollerHardware implementation. "
            "This would need to decode and play audio files directly on the Pico."
        )
    
    def run(self):
        """Main loop (placeholder)."""
        pass


# ===========================
#      ENTRY POINT
# ===========================

def main():
    """Main entry point for microcontroller-only mode software."""
    software = VintageRadioMicrocontroller()
    software.run()


# Run if executed directly
if __name__ == "__main__":
    main()

