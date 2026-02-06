# Format Support: RP2040-Zero + DFPlayer Mini

## Hardware Configuration
- **RP2040-Zero**: Microcontroller (handles button logic, state management, AM overlay)
- **DFPlayer Mini**: Audio playback module (handles actual audio playback)

## DFPlayer Mini Format Support
- **Primary Support**: MP3 (guaranteed, reliable)
- **Secondary Support**: WAV (may work, format-dependent)
- **Not Supported**: MIDI, FLAC, OGG, M4A, AAC, etc.

## Solution: Convert All Formats to MP3

Since DFPlayer Mini primarily supports MP3, we need to:
1. **SD Card Sync**: Convert all audio files to MP3 before copying to SD card
2. **GUI Test Mode**: Can play original formats for testing, but virtual time tracking ensures logic correctness
3. **Metadata Extraction**: Use `mutagen` to read metadata from ALL formats (already implemented)

## Implementation Strategy

### SD Card Sync (`gui/sd_manager.py`)
- Detect file format
- If not MP3, convert to MP3 using `pydub` + `ffmpeg`
- Copy converted MP3 to SD card
- Preserve original file in database (for GUI playback)

### GUI Test Mode (`gui/hardware_emulator.py`)
- Play original formats directly (for convenience)
- Virtual time tracking ensures radio mode logic is correct
- Seeking may not work for all formats in pygame, but virtual time is always accurate

### Firmware (`firmware/dfplayer_hardware.py`)
- Expects MP3 files on SD card
- Uses `setTime()` command for seeking (works reliably on MP3)



