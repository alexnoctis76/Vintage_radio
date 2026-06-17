# Vintage Radio Music Manager (this readme is outdated, updating soon)

This app makes it easier to load and manage music for the [Vintage AM Radio](https://www.zionbrock.com/radio) by Zion Brock—a 3D-printed, offline radio that plays from an SD card and uses a DFPlayer Mini for playback. Instead of manually formatting the card and organizing files by folder and name, you can use this desktop app to manage your library, build albums and playlists, sync to SD with automatic conversion to MP3, and test behavior before using the hardware.

The GUI provides a modern interface for organizing music files, syncing to SD cards, and testing firmware behavior. You can **drag and drop files or folders** into the Library, Albums, or Playlists views to import music quickly.

![Main Interface Overview](docs/images/library.png)

In the future I will be adding metadata support to automatically create albums from file metadata, and finalize support for the raspberry pi 2 W and raspberry pi 3 (currently implemented, but not fully tested with hardware)

## Features

### Core Functionality
- **Music Library Management**: Import and organize music files in any audio format (MP3, FLAC, WAV, OGG, MIDI, etc.)
- **Album & Playlist Creation**: Create custom albums and playlists with drag-and-drop support
- **Metadata Extraction**: Automatic extraction of title, artist, duration, and format information
- **SD Card Sync**: Sync your library to SD cards with automatic format conversion (to MP3 for hardware compatibility)
- **Emulator**: Full emulation of the radio device with visual radio face and interactive controls

### Playback Modes
- **Album Mode**: Play tracks in album order
- **Playlist Mode**: Play tracks in playlist order
- **Shuffle Mode**: Shuffle current album/playlist or entire library
- **Radio Mode**: Virtual radio stations with continuous playback and tuning dial

### Advanced Features
- **Format Conversion**: Automatic conversion to MP3 during SD sync for DFPlayer Mini compatibility
- **Virtual Time Tracking**: Radio mode tracks continuous playback across stations
- **AM Radio Overlay**: Authentic AM radio sound effects when tuning or switching modes
- **State Persistence**: Resume playback from where you left off after power cycles
- **Database Backups**: Automatic database backups with configurable retention

## Requirements

### Python
- Python 3.8 or higher

### Dependencies
Install from `requirements.txt`:
```bash
pip install -r requirements.txt
```

**Core Dependencies:**
- `PyQt6>=6.6.0` - GUI framework
- `mutagen>=1.47.0` - Audio metadata extraction
- `pygame-ce>=2.5.2` - Audio playback (emulator; same API as pygame, `import pygame`)
- `psutil>=5.9.0` - System utilities (SD card detection)
- `pydub>=0.25.1` - Audio processing
- `python-vlc>=3.0.20123` - Advanced audio playback (optional, for better seeking support)

### Required for file conversion (sync to SD)
To convert non-MP3 files (FLAC, WAV, OGG, etc.) to MP3 when syncing to SD card or exporting, **one of the following is required**:

- **VLC Media Player** (recommended) – [Download from VideoLAN](https://www.videolan.org/vlc/). Install on your system; the app will use it for conversion and for better seeking in the Emulator.
- **FFmpeg** – used by pydub for conversion fallback when VLC is unavailable. Packaged app builds bundle an FFmpeg binary; source/dev runs can also use a system FFmpeg from PATH.

Without either VLC or FFmpeg, only MP3 files can be synced (other formats will be skipped).

### Optional
- **VLC** also improves playback and seeking in the Emulator. **FFmpeg** is only used when VLC is not available for conversion.

## Installation
(This is if you are compiling the app yourself. If you download one of the ZIPs from the release, the only additional thing you need is VLC media player)
1. Clone the repository:
```bash
git clone <repository-url>
cd Vintage_radio
```

2. Create a virtual environment (recommended):
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# or
source .venv/bin/activate  # Linux/Mac
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install VLC media player
   if you havent already, please install VLC media player, this is required for the app to work.
## Usage

### Running the Application

```bash
python -m gui.radio_manager
```

Or directly:
```bash
python gui/radio_manager.py
```

### Basic Workflow

1. **Import Music Files (Library)**
   - **Drag and drop** audio files or entire folders into the Library tab, or use Import Files / Import Folder. The library shows all tracks in a searchable table with title, artist, duration, and format; you can edit or remove entries from here and use **Sync to SD** when ready.
   - ![Library: search, import, and sync to SD](docs/images/library.png)
   - The library supports searching by title, artist, format, or file path, making it easy to find specific tracks in large collections.

2. **Create Albums**
   - In the Albums tab, create a new album, then **drag and drop** files or folders onto the drop area (or add selected songs from the library). Select an album to see its track list, reorder by dragging, and use the buttons to rename, edit the description, or remove tracks.
   - ![Albums: drag and drop to add tracks](docs/images/albums.png)
   - ![Album detail: track list and ordering](docs/images/albums-detail.png)

3. **Create Playlists**
   - In the Playlists tab, create a playlist and add tracks from the library (or drag and drop). The right panel shows the playlist’s track list; use Add Selected Songs / Remove Selected to adjust the order and contents.
   - ![Playlists: build and edit playlists](docs/images/playlists.png)

4. **Sync to SD and Devices**
   - The Devices tab is where you set the **SD / media root** (or drag a folder onto it), run **Sync Library to SD**, validate the card, and export album or playlist contents. You can also export for RP2040 (Pico), install to Pico, or deploy to Raspberry Pi.
   - ![Devices: SD root, sync, validate, export, Pico, and Pi](docs/images/devices.png)
   - When syncing, a progress dialog shows real-time status with accurate progress tracking for each file being copied or converted.
   - ![Sync Progress: Real-time sync status with file-by-file progress](docs/images/sync-progress.png)

5. **Emulator**
   - The Emulator tab emulates the radio: power on/off, volume knob, and mode buttons (Album, Playlist, Shuffle, Radio). Use the virtual dial and tap/hold controls to change tracks and stations; the event log at the bottom shows playback and state. Sync your library to SD first so the Emulator can use the same files as the hardware.
   - ![Emulator: Album mode with radio face and playback controls](docs/images/emulator-album.png)
   - ![Emulator: Shuffle with radio face and event log](docs/images/emulator-shuffle.png)
   - ![Emulator: Radio mode and station info](docs/images/emulator-radio.png)

6. **Device Debug Console**
   - The Device Debug tab provides advanced debugging capabilities for the physical hardware. Connect to your device via serial port (COM port on Windows), send Python commands directly to the firmware, view debug logs showing DFPlayer commands and device responses, and interact with the device in real-time. The console displays detailed communication logs including volume changes, track playback commands, and volume adjustments. This is useful for troubleshooting hardware issues and testing firmware behavior.
   - ![Device Debug: Connected device with console output showing DFPlayer commands and Now Playing status](docs/images/device-debug.png)

### Button Controls (Works on Physical Device and Emulator - try clicking the button on the emulator radio and using the dial!)

- **Single Tap**: Next track
- **Tap + Hold**: Toggle Album/Playlist mode
- **2 Taps + Hold**: Shuffle current album/playlist
- **3 Taps + Hold**: Shuffle entire library
- **Radio Dial**: Tune between radio stations
- **Volume Knob**: Adjust volume
- **Power Button**: Turn device on/off

## Building standalone executables (Windows / Mac)

Packaging behavior differs across Windows and macOS. To avoid drift, use the canonical packaging guide:

- [`docs/BUILD_AND_PACKAGE.md`](docs/BUILD_AND_PACKAGE.md)

Quick commands:

- **Windows:** `build_windows.bat` (or `pyinstaller build/vintage_radio.spec`)
- **macOS:** `bash build_macos.sh`
- Output: `dist/Vintage Radio/`

## Project Structure

The canonical repository taxonomy and source-vs-generated policy lives in:

- [`docs/REPO_STRUCTURE.md`](docs/REPO_STRUCTURE.md)

## Architecture

### Shared Core Logic
`firmware/radio_core.py` contains the core state machine logic used by both:
- The GUI emulator (`gui/hardware_emulator.py`)
- The actual firmware (`firmware/pico/main.py`, `firmware/pi/main_pi.py`)

This ensures that the emulator accurately represents device behavior.

### Hardware Abstraction
The system uses a `HardwareInterface` abstraction layer:
- **GUI**: `PygameHardwareEmulator` - Uses pygame for audio playback
- **Pico Firmware**: `DFPlayerHardware` (`firmware/pico/dfplayer_hardware.py`) - Uses DFPlayer Mini via UART
- **Pi Firmware**: `PiHardware` (`firmware/pi/pi_hardware.py`) - Uses VLC and GPIO

### Database Schema
- `songs`: Music file metadata
- `albums`: Album definitions
- `playlists`: Playlist definitions
- `album_songs`: Album-track relationships
- `playlist_songs`: Playlist-track relationships
- `sd_mapping`: SD card file mapping
- `settings`: User preferences

## Development

### Testing
The emulator provides a complete emulation of the device:
- Visual radio face with interactive controls
- Full audio playback
- All modes and button combinations
- Detailed logging

### Firmware Integration
The firmware uses `firmware/pico/dfplayer_hardware.py` (and `firmware/pi/pi_hardware.py` for Pi), implementing the same `HardwareInterface` as the GUI, ensuring compatibility.

## Known Limitations

- Audio seeking: Some formats (MIDI, etc.) have limited seeking support without VLC
- SD card format: SD cards must be formatted as FAT32 or exFAT
- File size: Large libraries may take time to sync

## Troubleshooting

### Audio Playback Issues
- Ensure pygame is available: `pip install -r requirements.txt` (uses **pygame-ce**, still `import pygame`)
- For better format support, install VLC Media Player
- Check that audio files are not corrupted

### SD Card Sync Issues
- Verify SD card is formatted as FAT32 or exFAT
- Check available space on SD card
- Ensure SD card is not write-protected

### Format Conversion Issues
- Install VLC Media Player for best compatibility
- Or install FFmpeg and add to system PATH
- Check that source files are not corrupted

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]

## Acknowledgments

- Built with PyQt6 for the GUI
- Uses pygame for audio playback
- DFPlayer Mini for hardware audio playback


