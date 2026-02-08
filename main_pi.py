# Vintage Radio Firmware - Raspberry Pi 2W/3
# Uses the same RadioCore as the Pico/DFPlayer build; hardware via pi_hardware (VLC + GPIO).

import time

from radio_core import (
    RadioCore,
    MODE_ALBUM,
    MODE_PLAYLIST,
    MODE_SHUFFLE,
    MODE_RADIO,
    LONG_PRESS_MS,
    TAP_WINDOW_MS,
    POST_CMD_GUARD_MS,
    ticks_ms,
    ticks_diff,
)
from components.pi_hardware import PiHardware

# ===========================
#      MAIN FIRMWARE CLASS
# ===========================


class VintageRadioFirmwarePi:
    """Main firmware for Pi: same logic as main.py, using PiHardware (VLC, GPIO)."""

    def __init__(self, media_root=None):
        print("Booting Vintage Radio (Pi, RadioCore-based)")
        self.hw = PiHardware(media_root=media_root)
        self.core = RadioCore(self.hw)
        self.last_button = 1
        self.press_start = 0
        self.rail2_on = False
        self.last_sense = 0
        self.prev_playing = False
        self._pending_am_overlay = False

    def wait_for_power(self):
        print("Waiting for power sense HIGH...")
        last_hint = ticks_ms()
        while not self.hw.is_power_on():
            if ticks_diff(ticks_ms(), last_hint) > 1500:
                print("...still waiting for power")
                last_hint = ticks_ms()
            time.sleep(0.02)
        print("Power detected.")
        self.rail2_on = True
        self.last_sense = 1

    def boot_sequence(self):
        self.hw.reset_dfplayer()
        self.core.init(skip_initial_playback=True)
        tr = self.core._get_current_track()
        if tr:
            folder = tr.get("folder", 1)
            track = tr.get("track_number", 1)
        else:
            folder = self.core.current_album_index + 1
            track = self.core.current_track
        confirmed = self.hw.start_with_am(folder, track)
        if confirmed:
            print("Boot playback confirmed")
        else:
            self.hw.reset_dfplayer()
            self.hw.set_volume(100)
            time.sleep(POST_CMD_GUARD_MS / 1000.0)
            self.hw.play_track(folder, track)

    def handle_button(self):
        curr = 0 if self.hw.is_button_pressed() else 1
        now = ticks_ms()
        if self.last_button == 1 and curr == 0:
            self.press_start = now
            self.core.on_button_press()
        elif self.last_button == 0 and curr == 1:
            old_mode = self.core.mode
            old_shuffle_source = getattr(self.core, "_shuffle_source_type", None)
            self.core.on_button_release()
            new_shuffle_source = getattr(self.core, "_shuffle_source_type", None)
            mode_changed = old_mode != self.core.mode
            shuffle_reshuffled = (
                self.core.mode == MODE_SHUFFLE
                and old_shuffle_source != new_shuffle_source
            )
            press_dur = ticks_diff(now, self.press_start)
            if press_dur >= LONG_PRESS_MS and self.core.tap_count == 0:
                self._handle_album_change_with_am()
            elif mode_changed or shuffle_reshuffled:
                tr = self.core._get_current_track()
                if tr:
                    folder = tr.get("folder", 1)
                    track = tr.get("track_number", 1)
                else:
                    folder = self.core.current_album_index + 1
                    track = self.core.current_track
                self.hw.start_with_am(folder, track)
            time.sleep(0.04)
        self.last_button = curr

    def _handle_album_change_with_am(self):
        folder = self.core.current_album_index + 1
        track = self.core.current_track
        if self.hw.has_track(folder, track):
            self.hw.start_with_am(folder, track)
        else:
            print("Album not found, wrapping to album 1.")
            self.core.current_album_index = 0
            self.core.current_track = 1
            self.core._save_state("wrap to album 1")
            self.hw.start_with_am(1, 1)

    def handle_track_finished(self):
        if not self.rail2_on:
            return
        if time.monotonic() < self.hw.ignore_busy_until:
            self.prev_playing = self.hw.is_playing()
            return
        playing = self.hw.is_playing()
        if self.prev_playing and not playing:
            print("Track finished")
            self.core.on_track_finished()
        self.prev_playing = playing

    def handle_power_change(self):
        sense = 1 if self.hw.is_power_on() else 0
        if sense != self.last_sense:
            if sense == 0:
                print("Power OFF")
                self.rail2_on = False
                self.core.power_off()
            else:
                print("Power ON")
                self.rail2_on = True
                self.hw.reset_dfplayer()
                self.core.power_on_handler()
                folder = self.core.current_album_index + 1
                track = self.core.current_track
                self.hw.start_with_am(folder, track)
            self.last_sense = sense

    def run(self):
        print("Button active. Patterns: tap=next, double=prev, triple=restart, hold=next album, etc.")
        while True:
            self.handle_button()
            self.core.tick()
            self.handle_track_finished()
            self.handle_power_change()
            time.sleep(0.01)


def main():
    import os
    media_root = os.environ.get("VINTAGE_RADIO_MEDIA_ROOT")
    firmware = VintageRadioFirmwarePi(media_root=media_root)
    firmware.wait_for_power()
    firmware.boot_sequence()
    firmware.run()


if __name__ == "__main__":
    main()
