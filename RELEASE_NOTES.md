# Vintage Radio Music Manager

Desktop application for managing your music library and syncing it to a vintage-style radio device. Organize tracks, build albums and playlists, sync to SD (with optional conversion to MP3), and try everything in a built-in emulator before using the hardware.

---

## Latest Changes

### Emulator (formerly Test Mode)

- **Renamed** "Test Mode" to "Emulator" throughout the app for clarity.
- **Fixed radio button playback** - Mode switches triggered by the radio face button (tap+hold gestures) now correctly play audio. Previously, the 500ms tap-resolution timer caused the mode switch to fire asynchronously, and the pending playback was never executed.
- **Fixed "Playback failed to start" false alarm** - The emulator's `play_track()` now returns proper status values so RadioCore no longer logs misleading failure messages when playback is queued for AM overlay sequencing.

### Drag-and-Drop Improvements

- **Users can now drag songs in playlists and albums to reorder** - Dragging songs to reorder within an album or playlist now possible. The radio will play them in the order they appear.
- **Existing library songs can be added to collections** - Dragging folders from the file explorer into an album or playlist now adds songs that already exist in the library, instead of silently skipping them.

### SD Sync & Metadata

- **Accurate sync progress bar** - The sync progress dialog now reports real-time status across three distinct phases (scan, copy/convert, finalize) instead of jumping or stalling.
- **Reduced metadata size (~67%)** - Removed the legacy `folders` key, `hash`, and `original_file` fields from `radio_metadata.json`. Added the `duration` field. This brings metadata from ~70 KB down to ~23 KB, preventing memory issues on the Pico.

### Device Debug Console

- **Removed "Query Device" button** - It was intrusive (interrupted firmware via Ctrl+C) and redundant with stream parsing.
- **"Save Session Log"** - Replaced "View Debug Log" (which tried to read from the device) with a button that saves the local PC-side console output to a file.
- **Fixed serial commands** - Refactored multi-line commands (List Files, Check Firmware Status, Get Status) to single-line MicroPython-compatible commands to prevent serial garbling.
- **MicroPython compatibility** - Replaced CPython-only APIs (`os.getfree`, `os.path.isfile`, `.title()`) with MicroPython equivalents (`gc.mem_free()`, `os.stat()`, string literals).
- **Improved text readability** - Changed info label color from unreadable light blue to dark gray.

### Firmware (Pico / Pi)

- **Deduplicated metadata parsing** - Both `dfplayer_hardware.py` and `pi_hardware.py` now parse the new streamlined metadata format and handle errors per-collection instead of failing entirely.
- **Fixed `.title()` crash on MicroPython** - Replaced `ctype.title()` with a compatible string literal.

### Database

- **Robust schema migration** - Added `_ensure_sort_order_columns()` which runs after all migrations to guarantee the `sort_order` column exists, regardless of stored schema version. This prevents the `no such column: sort_order` startup crash.

---

## First Release Highlights

- **Music library** - Import and organize audio files (MP3, FLAC, WAV, OGG, etc.) with metadata (title, artist, duration).
- **Albums & playlists** - Create and edit albums and playlists with drag-and-drop.
- **SD card sync** - Sync your library to SD with optional conversion to MP3 for DFPlayer Mini-compatible devices.
- **Emulator** - Emulate the radio on your PC: dial, volume, power, and playback (album, playlist, shuffle, radio stations).
- **Radio mode** - Virtual stations with continuous playback and an AM-style tuning experience.
- **Standalone builds** - No Python install needed: run the included Windows or macOS app from the release assets.

## Downloads

- **Windows** - Unzip `Vintage-Radio-Windows.zip`, open the `Vintage Radio` folder, and run `Vintage Radio.exe`.
- **macOS** - Unzip `Vintage-Radio-macOS.zip`, open the `Vintage Radio` folder:
  1. **First time only:** Right-click `open_vintage_radio.command` → "Open" → "Open" in the security dialog. This removes the macOS quarantine and launches the app.
  2. **After that:** Just double-click `Vintage Radio.app` directly.
  - Works on both Intel and Apple Silicon Macs (Apple Silicon runs via Rosetta 2).
  - **Alternative:** Right-click `Vintage Radio.app` → "Open" → "Open" in the dialog, or run `xattr -dr com.apple.quarantine .` in the folder via Terminal.

## Before You Start

- **File conversion (non-MP3 to MP3):** For converting FLAC, WAV, OGG, etc. when syncing to SD, you need **one of**: [VLC](https://www.videolan.org/vlc/) (recommended) or [FFmpeg](https://ffmpeg.org/download.html) on your system. Without either, only MP3 files can be synced.
- **From source:** Python 3.8+, dependencies in `requirements.txt`. See the README for install and run instructions.

## Documentation

- Main [README](README.md) - Setup, usage, and building from source.
- [Pi setup](docs/README_Pi.md) - Running on Raspberry Pi.
- [RP2040](docs/README_RP2040.md) - RP2040 firmware notes.
