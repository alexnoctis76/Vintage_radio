# Vintage Radio Music Manager

A desktop GUI application for managing music libraries, albums, and playlists for a vintage radio device. The system provides a modern interface for organizing music files, syncing to SD cards, and testing firmware behavior.

## Features

### Core Functionality
- **Music Library Management**: Import and organize music files in any audio format (MP3, FLAC, WAV, OGG, MIDI, etc.)
- **Album & Playlist Creation**: Create custom albums and playlists with drag-and-drop support
- **Metadata Extraction**: Automatic extraction of title, artist, duration, and format information
- **SD Card Sync**: Sync your library to SD cards with automatic format conversion (to MP3 for hardware compatibility)
- **Test Mode**: Full emulation of the radio device with visual radio face and interactive controls

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
- `pygame>=2.5.2` - Audio playback (test mode)
- `psutil>=5.9.0` - System utilities (SD card detection)
- `pydub>=0.25.1` - Audio processing
- `python-vlc>=3.0.20123` - Advanced audio playback (optional, for better seeking support)

### Optional Dependencies
- **VLC Media Player**: For better audio format support and seeking capabilities
  - Windows: Download from [VideoLAN](https://www.videolan.org/vlc/)
  - The application will work without VLC, but with limited seeking support for some formats
- **FFmpeg**: For audio conversion (required if VLC is not available)
  - Download from [FFmpeg](https://ffmpeg.org/download.html)
  - Add to system PATH

## Installation

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

1. **Import Music Files**
   - Drag and drop audio files into the Library tab
   - Files are automatically scanned for metadata
   - All formats are supported (conversion happens during SD sync)

2. **Create Albums/Playlists**
   - Switch to Albums or Playlists tab
   - Create a new album/playlist
   - Drag songs from the library or import directly
   - Reorder tracks by dragging

3. **Sync to SD Card**
   - Go to Library tab
   - Click "Sync to SD" button
   - Select your SD card drive
   - Files are converted to MP3 and organized automatically

4. **Test Mode**
   - Switch to Test Mode tab
   - Interact with the virtual radio face
   - Test all modes and button combinations
   - View detailed logs of device behavior

### Button Controls (Test Mode)

- **Single Tap**: Next track
- **Tap + Hold**: Toggle Album/Playlist mode
- **2 Taps + Hold**: Shuffle current album/playlist
- **3 Taps + Hold**: Shuffle entire library
- **Radio Dial**: Tune between radio stations
- **Volume Knob**: Adjust volume
- **Power Button**: Turn device on/off

## Project Structure

```
Vintage_radio/
├── gui/                    # GUI application code
│   ├── radio_manager.py    # Main window
│   ├── test_mode.py        # Test mode emulator
│   ├── database.py         # Database operations
│   ├── sd_manager.py       # SD card sync
│   ├── hardware_emulator.py # Hardware emulation
│   └── resources/          # Images and sounds
├── firmware/               # Firmware code
│   └── dfplayer_hardware.py # DFPlayer hardware interface
├── radio_core.py           # Shared core logic (GUI + firmware)
├── main.py                 # Original firmware (reference)
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## Architecture

### Shared Core Logic
The `radio_core.py` module contains the core state machine logic used by both:
- The GUI test mode (emulation)
- The actual firmware (hardware)

This ensures that the test mode accurately represents device behavior.

### Hardware Abstraction
The system uses a `HardwareInterface` abstraction layer:
- **GUI**: `PygameHardwareEmulator` - Uses pygame for audio playback
- **Firmware**: `DFPlayerHardware` - Uses DFPlayer Mini via UART

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
The test mode provides a complete emulation of the device:
- Visual radio face with interactive controls
- Full audio playback
- All modes and button combinations
- Detailed logging

### Firmware Integration
The firmware (`firmware/dfplayer_hardware.py`) implements the same `HardwareInterface` as the GUI, ensuring compatibility.

## Known Limitations

- Audio seeking: Some formats (MIDI, etc.) have limited seeking support without VLC
- SD card format: SD cards must be formatted as FAT32 or exFAT
- File size: Large libraries may take time to sync

## Troubleshooting

### Audio Playback Issues
- Ensure pygame is properly installed: `pip install pygame`
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


