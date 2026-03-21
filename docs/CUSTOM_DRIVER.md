# Writing a Custom Hardware Driver

This guide explains how to run the Vintage Radio firmware on **any
MicroPython-compatible board** (or even CPython on a Raspberry Pi)
by writing a custom hardware driver.

---

## Architecture Overview

```
main.py  ──>  RadioCore(hw)
                  │
                  ▼
          HardwareInterface   (abstract — firmware/radio_core.py)
                  │
        ┌─────────┼──────────┐
        ▼         ▼          ▼
  DFPlayer    PiHardware   YourDriver
  (Pico)      (RPi Linux)   (custom)
```

`RadioCore` handles **all** state-machine logic (playback order, button
gestures, mode switching, shuffle, etc.).  It never touches hardware
directly — it only calls methods on the `HardwareInterface` you provide.

Your job is to implement those methods for your specific audio module
and MCU.

---

## What You Need

| Item | Purpose |
|---|---|
| A MicroPython (or CPython) board | Runs the firmware |
| An audio output (DFPlayer, I2S DAC, VS1053, PWM, etc.) | Plays the music |
| A momentary push-button | User input (next track, mode switch, etc.) |
| (Optional) A power-sense circuit | Detects potentiometer on/off |
| (Optional) A NeoPixel / status LED | Visual feedback |
| An SD card **or** flash with your music files | Storage |

---

## Not using DFPlayer?

The same template and workflow apply.  You do **not** need a different
main.py or any extra steps.  The firmware `main.py` is driver-agnostic:
it only calls the `HardwareInterface` methods (e.g. `play_track`,
`is_playing`, `is_power_on`).  DFPlayer-specific behaviour (UART
commands, BUSY pin, file-count check) is optional and only used when
your driver provides it.  For I2S, VS1053, or other hardware you just
implement the same interface and map `folder`/`track` to whatever your
module expects (file paths, streams, etc.).

---

## Step-by-Step

### 1. Copy the template

The file `firmware/custom_driver_template.py` is a fully commented
starting point.  Copy it and rename it:

```
cp firmware/custom_driver_template.py firmware/my_hardware.py
```

Or use the GUI: open the **Pin Configuration** dialog and click
**Download Driver Template** to save a copy wherever you like.

### 2. Implement the required methods

Every method marked `raise NotImplementedError` must be filled in.
Methods that already have a default body (like `check_track_finished_uart`)
are optional — override them only if your hardware supports that feature.

#### Required methods

| Method | What it does |
|---|---|
| `play_track(folder, track, start_ms)` | Start playing a song |
| `stop()` | Stop playback |
| `set_volume(level)` | Set volume (0-100, you map to hardware range) |
| `is_playing()` | Return `True` while audio is active |
| `play_am_overlay()` | Play the AM static effect (or no-op) |
| `save_state(state_dict)` | Write state to non-volatile storage |
| `load_state()` | Read it back (return `None` on first boot) |
| `log(message)` | Output a log line |
| `get_albums()` | Return album list from `radio_metadata.json` |
| `get_playlists()` | Return playlist list |
| `get_all_tracks()` | Return flat track list |
| `is_power_on()` | `True` when power-sense is active (or always `True`) |
| `is_button_pressed()` | `True` when the button is held down |

#### Optional methods

| Method | Default | Override when... |
|---|---|---|
| `get_playback_position_ms()` | Returns `0` | Your module can report position |
| `check_track_finished_uart()` | Returns `False` | Your module signals track end (like DFPlayer 0x3D) |
| `set_delay_playback(delay)` | No-op | You need to honour the AM-overlay interlock |
| `set_current_track_hint(track)` | No-op | Useful for emulators / GUI previews |

### 3. Configure pins

Create a `pin_config.json` on your board (or let the GUI generate one).
The loader (`pin_config_loader.py`) reads it at boot:

```json
{
  "board": "esp32_generic",
  "audio_module": "i2s",
  "pins": {
    "button": 15,
    "power_sense": 34,
    "busy": 35,
    "i2s_bclk": 26,
    "i2s_lrc": 25,
    "i2s_dout": 22
  }
}
```

You can add any keys you need — `pin_config_loader.get_pin("i2s_bclk")`
will find them.

### 4. Deploy via the GUI

You do **not** need to write or modify `main.py`.  The GUI deploys
the standard `main.py` and renames your driver file so the existing
import works automatically.

1. Open the Vintage Radio GUI.
2. Create (or edit) a **Device Profile**.
3. Set the **Board** to the closest match, or any MicroPython board.
4. In **Pin Configuration**, set your pin assignments.
5. Under **Custom Hardware Driver**, browse to your `.py` file.
6. Click **Install Firmware** — the GUI will copy `main.py`,
   `radio_core.py`, `pin_config_loader.py`, your generated
   `pin_config.json`, and your custom driver (renamed so `main.py`
   can import it) to the board.

> **Advanced users:** If you need full control over the boot sequence
> (e.g. custom button logic or a different main loop), you can study
> `firmware/pico/main.py` as a reference and deploy your own manually.
> For most setups this is not necessary.

---

## Data Formats

### radio_metadata.json

Generated by the SD Card Manager.  Follows this structure:

```json
{
  "songs": [
    {"id": 1, "title": "...", "artist": "...", "duration": 210}
  ],
  "albums": [
    {
      "id": 1,
      "name": "Album Name",
      "track_refs": [
        {"song_id": 1, "folder": 1, "track": 1}
      ]
    }
  ],
  "playlists": [ ... ]
}
```

### Track dict (returned by get_albums / get_playlists / get_all_tracks)

```python
{
    "id": 1,
    "title": "Song Title",
    "artist": "Artist Name",
    "duration": 210,        # seconds
    "folder": 1,            # DFPlayer folder
    "track_number": 1,      # DFPlayer track within folder
}
```

### State dict (save_state / load_state)

```python
{
    "mode": "album",          # "album" | "playlist" | "shuffle" | "radio"
    "album_index": 0,         # current album or playlist index
    "track": 1,               # current track number
    "known_tracks": {"1": 5}, # folder_id -> max track confirmed
}
```

---

## Tips

- **`is_playing()` must be fast.**  RadioCore calls it every 10 ms in the
  main loop.  If polling your audio module is slow, cache the result and
  update it in the background or on a timer.

- **`play_track()` folder/track mapping.**  If your audio system uses file
  paths instead of numbered folders, build a lookup table from
  `radio_metadata.json` in `__init__` and translate inside `play_track()`.

- **No NeoPixel?**  That's fine — the NeoPixel calls live in `main.py`
  and `dfplayer_hardware.py`, not in RadioCore.  Your driver doesn't need
  to implement anything NeoPixel-related.

- **No power-sense circuit?**  Return `True` from `is_power_on()`. The
  radio will behave as always-on.

- **Testing.**  You can test your driver on a PC by importing it alongside
  the GUI's hardware emulator.  The GUI's `hardware_emulator.py` is
  itself a `HardwareInterface` implementation — study it as a second
  reference alongside `dfplayer_hardware.py`.
