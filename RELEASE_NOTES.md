# Vintage Radio Music Manager - First Release

Desktop application for managing your music library and syncing it to a vintage-style radio device. Organize tracks, build albums and playlists, sync to SD (with optional conversion to MP3), and try everything in a built-in test mode before using the hardware.

## Highlights

- **Music library** - Import and organize audio files (MP3, FLAC, WAV, OGG, etc.) with metadata (title, artist, duration).
- **Albums & playlists** - Create and edit albums and playlists with drag-and-drop.
- **SD card sync** - Sync your library to SD with optional conversion to MP3 for DFPlayer Mini-compatible devices.
- **Test mode** - Emulate the radio on your PC: dial, volume, power, and playback (album, playlist, shuffle, radio stations).
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
