# Vintage Radio Music Manager

Desktop application for managing your music library and syncing it to a vintage-style radio device. Organize tracks, build albums and playlists, sync to SD (with optional conversion to MP3), and try everything in a built-in emulator before using the hardware.

---

# Release summary — **v0.2.1-beta**

> **Note.** [VLC media player](https://www.videolan.org/vlc/) is required for full functionality (conversion to MP3 and best emulator seeking). FFmpeg can be used as a fallback for conversion when VLC is not installed.

## Basic mode (unchanged direction)

**Basic mode** remains the main architecture: `firmware/pico/main_basic.py` and `RadioCore(..., basic_mode=True)` with **stations derived from the DFPlayer / SD folder layout**, not a full desktop-only metadata graph. This release tightens **playback and visit-mode behavior** on the Pico (fewer spurious track advances, clearer DFPlayer folder handling) and improves **host-side** SD workflows below.

### How basic mode differs from advanced mode

| | **Basic mode** | **Advanced mode** |
|---|----------------|-------------------|
| **Discovery** | Stations from **UART** to the DFPlayer (**0x4F** folder count, **0x4E** files per folder) in `discover_stations()`, via `_load_data_basic()` in `radio_core.py`. The card’s **folder layout** is the source of truth. | Libraries from **metadata**: `get_albums()` / `get_playlists()` and paths shaped by **JSON / app sync**. |
| **SD workflow** | Prepare folders `01`…, optional **folder 99** for flags. Swap SD cards without a new firmware build for every library edit; discovery on **cold boot**. | Richer pipeline; card content is expected to match **prepared metadata**. |
| **UX / features** | **No album mode** in the same sense—station playback, shuffle modes, radio, folder **99** flags. **Folders = stations.** | Full **album + playlist** flows and mode cycling. |

### Trade-offs (still relevant)

- **Boot / UART / RAM:** Discovery builds per-track state from DFPlayer-reported counts; very large libraries increase time and RAM use.
- **Filesystem quirks:** Stray files (e.g. `._*` from macOS) can skew counts—use the app’s sync path that strips junk when preparing cards.
- **SD swap without reboot:** Until a fingerprint/refresh step exists, prefer **cold boot** after swapping cards so discovery matches the new card.

---

## What’s new in v0.2.1-beta

### Experimental: clean SD disk image (Windows)

- **Build a FAT32 `.img` from your library** (with optional “prepare on this PC” staging) and **flash it to a physical SD card** from the app.
- **UAC elevation** only for the raw write step (you do not need to run the whole app as Administrator).
- **Removable media:** Windows cannot “offline” SD/USB the same way as internal disks; the app **locks and dismounts volumes** (`FSCTL_LOCK_VOLUME` / `FSCTL_DISMOUNT_VOLUME`) before writing to `\\.\PhysicalDriveN`, and uses **Win32 `WriteFile`** for reliable raw writes.
- **Wizard** lists **USB and MMC** disks only (internal NVMe/SATA fixed disks are filtered out), shows **size and volume labels**, and supports **“flash only”** to reuse the last built image for faster retesting.
- **Progress and errors** are clearer (staging vs image build vs flash); **session log** captures GUI errors including message boxes.

### MCP debug and physical acceptance (host)

- **TCP debug server** (optional) for automation: ping, device connect, serial tail, **line-in analysis**, and a **full device acceptance** suite driven against the real Pico (basic mode).
- **`gui/services/serial_debug`** and scripts under **`scripts/`** (e.g. MCP bridge, physical check helpers) support CI-style checks from the desktop.

### Firmware and `radio_core`

- Continued improvements to **`dfplayer_hardware.py`**, **`main_basic.py`**, **`main.py`**, and **`radio_core.py`** for basic-mode station discovery, playback, and visit/shuffle edge cases; IPC components under **`firmware/pico/components/`** (e.g. `vintage_radio_ipc`, AM WAV loader path).

### Desktop quality of life

- **Updater** UI hook for checking GitHub releases (see **Help** / version flows in-app).
- **`docs/REPO_STRUCTURE.md`** and README tweaks for navigating the repo.

### Tests

- Extended coverage for **`radio_core`**, **`sd_manager`**, SD image helpers, MCP, and widgets used in the new flows.

---

**Full Changelog (GitHub):** https://github.com/alexnoctis76/Vintage_radio/compare/v0.2.0-beta...v0.2.1-beta

---

## Previous release highlights (v0.2.0-beta and earlier)

## Latest Changes (historical)

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
- **macOS** - Unzip `Vintage-Radio-macOS.zip` and run the app inside the folder.

## Before You Start

- **File conversion (non-MP3 to MP3):** For converting FLAC, WAV, OGG, etc. when syncing to SD, you need **one of**: [VLC](https://www.videolan.org/vlc/) (recommended) or [FFmpeg](https://ffmpeg.org/download.html) on your system. Without either, only MP3 files can be synced.
- **From source:** Python 3.8+, dependencies in `requirements.txt`. See the README for install and run instructions.

## Documentation

- Main [README](README.md) - Setup, usage, and building from source.
- [Pi setup](docs/README_Pi.md) - Running on Raspberry Pi.
- [RP2040](docs/README_RP2040.md) - RP2040 firmware notes.
