# Firmware vs Baseline 5.9.1 and Emulator Alignment

## 1. Pin layout (matches baseline)

| Signal    | Baseline | firmware/dfplayer_hardware.py | Notes |
|-----------|----------|-------------------------------|--------|
| PIN_AUDIO | 3        | 3                             | PWM for AM WAV |
| PIN_BUTTON| 2        | 2                             | Button (pull-up, active low) |
| PIN_NEOPIX| 16       | 16                            | NeoPixel status |
| PIN_UART_TX | 0      | 0                             | DFPlayer UART |
| PIN_UART_RX | 1      | 1                             | DFPlayer UART |
| PIN_SENSE | 14        | 14                            | Power sense Rail 2 (pull-down) |
| PIN_BUSY  | 15        | 15                            | DFPlayer BUSY (0=playing, 1=idle) |

Pin layout is identical to baseline. No changes needed.

---

## 2. DFPlayer commands (matches baseline)

Packet format: `0x7E 0xFF 0x06 cmd 0x00 p1 p2 checksum_hi checksum_lo 0xEF` (checksum = -sum(bytes 1..7) & 0xFFFF).

| Command | Baseline | firmware | Purpose |
|---------|----------|----------|---------|
| 0x3F    | df_reset | _df_reset | Reset |
| 0x06    | df_set_vol | _df_set_vol | Volume 0-30 |
| 0x0F    | df_play_folder_track | _df_play_folder_track | Play folder/track |
| 0x16    | df_stop  | _df_stop | Stop |

Additional in firmware (for radio start offset):

| Command | firmware | Purpose / caveat |
|---------|----------|------------------|
| 0x03    | _df_set_time(seconds) | Documented in some specs as "play track in root" (track index), not "set playback time". DFPlayer Mini typically does **not** support seeking within a track. So `start_ms` for radio is best-effort on hardware; if 0x03 is not seek, radio will start from track start. |

Recommendation: treat `start_ms` on hardware as optional; if 0x03 does not seek, firmware already plays the correct track from the beginning (correct station, correct track, offset only in emulator).

---

## 3. Behavior alignment

### 3.1 Boot sequence (fix applied)

- **Baseline:** load_state() -> DF_BOOT_MS -> start_sequence_synced() (reset, vol 0, play_am_and_fade_df_confirming(album, track)).
- **Firmware before fix:** reset -> core.init() -> start_with_am(). But core.init() calls _start_playback_for_current() so it started the track once, then start_with_am() stopped and started again with AM. That double-start was redundant and could cause a brief glitch.
- **Firmware after fix:** reset -> core init with skip_initial_playback -> start_with_am() only. Matches baseline: one start, inside AM overlay flow.

### 3.2 AM overlay + fade

- Baseline and firmware both: start DF track (or stop then start), play AM WAV on PWM, fade DF volume 0->target over FADE_IN_S, confirm BUSY low during window. Logic matches.

### 3.3 BUSY and track-finished

- Baseline: detect BUSY edge 0->1, then auto-advance (next track or probe).
- Firmware: same in handle_track_finished(); core.on_track_finished() runs the same RadioCore logic as the emulator. ignore_busy_until used after manual skips. Aligned.

### 3.4 Button patterns

- Baseline: short tap = next, double = prev, triple = restart album, long = next album (with silent probe and optional wrap to album 1).
- Firmware: delegates to RadioCore.on_button_release() (tap + long-press mode switching). Same patterns; long-press alone triggers album change with AM; mode changes trigger AM overlay. Aligned.

### 3.5 State save/load

- Baseline: album_state.txt format "album,track;tracks=a:c,...".
- Firmware: DFPlayerHardware.save_state() / load_state() use same format; RadioCore state (mode, album_index, track, known_tracks) is persisted via hw.save_state(). Compatible.

---

## 4. Gaps vs emulator (by design or hardware limits)

1. **Radio dial / tuning**  
   Emulator has a dial that calls tune_radio(value). The RP2040 firmware has **no ADC or dial input** yet. So on hardware, radio mode can exist (e.g. fixed station 0 or last station) but there is no way to change station without adding an ADC pin and calling core.tune_radio(dial_value) in the main loop.

2. **Volume knob**  
   Baseline sets a fixed DFPLAYER_VOL; no pot. Emulator has a volume knob routed through the hardware abstraction. Firmware does not read a volume pot; volume is set in code (e.g. DFPLAYER_VOL). Adding a volume pot would require an ADC and calling hw.set_volume() from the main loop.

3. **start_ms (radio virtual time)**  
   Emulator (VLC) can start at an offset inside a track. DFPlayer Mini does not support in-track seek in the standard command set. Firmware uses 0x03 as "set time" if available; otherwise radio on hardware starts at the beginning of the correct track. Station and track selection still match the emulator.

4. **Metadata**  
   Firmware expects radio_metadata.json (and album_state.txt) on the SD card (e.g. VintageRadio/). Emulator uses the GUI database. Same RadioCore logic; only data source differs.

---

## 5. File paths on SD (firmware)

- AM WAV: `VintageRadio/AMradioSound.wav` (or WAV_FILE in dfplayer_hardware.py).
- State: `VintageRadio/album_state.txt`.
- Metadata: `VintageRadio/radio_metadata.json`.
- DFPlayer folders: 01..99 as in baseline (folder = album_index + 1 for album mode).

---

## 6. Summary

- **Pins and DFPlayer command set:** Match baseline; no change.
- **Boot:** Fixed so playback starts only once, with AM overlay (no double start).
- **Radio/volume on device:** Behave like emulator where hardware allows; dial and volume pot require future ADC wiring and main-loop handling; radio start_ms is best-effort (correct track, offset only if 0x03 supports seek).
