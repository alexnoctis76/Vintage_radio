---
name: Vintage Radio Music Manager
overview: Create a desktop GUI application (PyQt) with SQLite database to manage music library, albums, and playlists for the vintage radio. The system will automatically handle file organization on SD cards, maintain relational data for songs appearing in multiple albums, and include a test mode to emulate device behavior. Update the firmware to read from the new metadata format.
todos: []
---

# Vi

ntage Radio Music Manager - Implementation Plan

## Overview

Transform the vintage radio from a file-name-based system to a relational database-driven system with a modern GUI. Users can drag-and-drop music files, create albums/playlists, and sync to SD cards without manual file renaming.

## Architecture

### Data Model

**SQLite Database Schema:**

- `songs` table: `id`, `original_filename`, `file_path`, `title`, `artist`, `duration`, `file_hash`, `file_size`, `format`, `created_at`, `modified_at`
- `albums` table: `id`, `name`, `description`, `created_at`, `modified_at`
- `playlists` table: `id`, `name`, `description`, `created_at`, `modified_at`
- `album_songs` table: `album_id`, `song_id`, `track_order` (many-to-many)
- `playlist_songs` table: `playlist_id`, `song_id`, `track_order` (many-to-many)
- `sd_mapping` table: `song_id`, `folder_number`, `track_number` (maps songs to DFPlayer folder/track structure)
- `settings` table: `key`, `value` (for user preferences like auto-sync)

### System Components

1. **GUI Application** (`gui/radio_manager.py`)

- Main window with library view, album/playlist management
- Drag-and-drop file import
- SD card sync interface with confirmation dialogs
- Test mode emulator

2. **Database Manager** (`gui/database.py`)

- SQLite operations
- Song metadata extraction (using `mutagen` for all audio formats)
- File hash calculation for deduplication
- Database backup/restore functionality
- Metadata sync validation (compare database with file system)

3. **SD Card Manager** (`gui/sd_manager.py`)

- Auto-detect SD card drives
- Manual path selection
- File copying and renaming to DFPlayer format (folders 01-99, tracks 001-999)
- Audio format conversion (all formats → MP3 for DFPlayer compatibility)
- Metadata file generation for firmware
- SD card metadata sync checking (compare SD card files with database)
- Import albums/playlists from SD card folders (detect `*_album` and `*_playlist` folders)

4. **Firmware Updates** (`main.py`)

- Read metadata from new format
- Maintain backward compatibility with existing `album_state.txt`
- Support both folder-based and metadata-based navigation

5. **Test Mode Emulator** (`gui/test_mode.py`)

- Simulate DFPlayer BUSY signal
- Simulate button presses
- Visual feedback for radio state

## Implementation Details

### File Structure

```javascript
vintage-radio-manager/
├── gui/
│   ├── __init__.py
│   ├── radio_manager.py          # Main GUI application
│   ├── database.py               # SQLite operations
│   ├── sd_manager.py             # SD card sync logic
│   ├── test_mode.py              # Device emulator
│   ├── audio_converter.py        # Audio format conversion
│   ├── export_manager.py         # Export albums/playlists
│   ├── ui/
│   │   ├── main_window.ui        # Qt Designer file (optional)
│   │   └── components/           # Reusable UI components
│   └── resources/                # Icons, assets
├── firmware/
│   ├── main.py                   # Updated firmware
│   └── metadata_reader.py        # Helper for reading metadata
├── backups/                      # Database backup directory
│   └── .gitignore                # Exclude backups from version control
├── requirements.txt
├── README.md
└── setup.py                      # Optional installer
```

### Key Features

**GUI Application:**

- **Library View**: Grid/list of all songs with metadata
- **Album Management**: Create/edit albums, add/remove songs, reorder tracks
- **Playlist Management**: Similar to albums but separate entity
- **Drag & Drop**: Import files directly into library
- **SD Card Sync**: 
- Auto-detect removable drives
- Manual path selection
- Preview changes before sync
- Confirmation dialog before writing
- Progress indicator
- **Test Mode**: 
- Emulate button presses (tap, double, triple, long)
- Visual state display (current album/track)
- Simulate BUSY signal timing
- Playback simulation

**Database Operations:**

- Extract metadata from audio files (all formats via `mutagen`)
- Calculate file hashes to prevent duplicates
- Support songs in multiple albums/playlists
- Track order within each album/playlist
- Automatic database backups (timestamped, configurable retention)
- Metadata sync validation (check file existence, size, hash)
- Settings storage (auto-sync preference, backup frequency, etc.)

**SD Card Sync Process:**

1. User selects albums/playlists to sync
2. System calculates required folders (max 99)
3. Converts non-MP3 files to MP3 if needed (using `ffmpeg`/`pydub`)
4. Copies files to SD card with DFPlayer naming (001.mp3, 002.mp3, etc.)
5. Generates `radio_metadata.json` with mapping:
   ```json
   {
     "folders": {
       "01": {"type": "album", "id": 1, "name": "My Album", "tracks": [{"song_id": 5, "track": 1}, ...]},
       "02": {"type": "playlist", "id": 2, "name": "Favorites", "tracks": [...]}
     },
     "songs": {
       "5": {"title": "Song Name", "artist": "Artist", "original_file": "song.mp3", "hash": "abc123..."}
     }
   }
   ```

6. Preserves existing `album_state.txt` for backward compatibility

**SD Card Load/Metadata Sync:**

1. When SD card is detected/selected:

   - Scan for `radio_metadata.json`
   - Scan for `*_album` and `*_playlist` folders in root
   - Compare files on SD card with database:
     - Check file existence
     - Compare file sizes and hashes
     - Detect missing, modified, or new files

2. Sync options:

   - **Auto-sync on load**: Automatically update database when mismatches detected (user preference)
   - **Manual sync**: Show sync dialog with changes preview, user confirms

3. Import process:

   - Detect `*_album` and `*_playlist` folders
   - Read metadata files or infer from folder structure
   - Import songs and create albums/playlists in database
   - Handle duplicates (by hash comparison)

**Export Process:**

1. User selects album/playlist to export
2. Create folder: `{name}_album` or `{name}_playlist`
3. Copy all song files to folder (preserve original filenames)
4. Generate `metadata.json` in folder:
   ```json
   {
     "type": "album",  // or "playlist"
     "id": 1,
     "name": "My Album",
     "description": "...",
     "tracks": [
       {"order": 1, "filename": "song1.mp3", "title": "Song 1", "artist": "Artist"},
       ...
     ]
   }
   ```

5. User can drag folder to SD card root for import

**Firmware Updates:**

- Add metadata reader that loads `radio_metadata.json` if present
- Fall back to folder enumeration if metadata missing
- Update `load_state()` to work with both old and new formats
- Maintain all existing button functionality

### Technical Stack

- **GUI**: PyQt6 (or PySide6) for cross-platform desktop app
- **Database**: SQLite3 (Python stdlib)
- **Audio Metadata**: `mutagen` library for all audio format tag reading
- **Audio Conversion**: `pydub` with `ffmpeg` backend (or direct `ffmpeg-python`) for format conversion
- **File Operations**: `shutil`, `pathlib` for SD card operations
- **Hardware Detection**: `psutil` for drive detection on Windows
- **Hashing**: `hashlib` for file integrity checking

### User Workflow

1. **Import Music**: Drag files into GUI → format detected → metadata extracted → converted to MP3 if needed → added to library → database backup created
2. **Create Albums**: Select songs → create album → reorder tracks
3. **Sync to SD**: Select SD card → choose albums/playlists → preview → confirm → sync (with progress)
4. **Load SD Card**: Insert SD card → auto-detect → metadata sync check → auto-sync (if enabled) or manual sync dialog
5. **Export Album/Playlist**: Select album/playlist → export → folder created → drag to SD card
6. **Import from SD**: SD card with `*_album`/`*_playlist` folders → auto-detect on load → import dialog
7. **Test Mode**: Switch to test mode → simulate button presses → see state changes
8. **Update Radio**: Eject SD card → insert into radio → firmware reads metadata

### Button Functionality (Preserved)

- **Single tap**: Next track (within current album)
- **Double tap**: Previous track
- **Triple tap**: Restart album (track 1)
- **Long press**: Next album

### Additional Considerations (All Implemented)

- **File Format Support**: 
  - Accept ALL audio formats (MP3, FLAC, WAV, OGG, M4A, AAC, WMA, OPUS, etc.)
  - Auto-detect format using file extension and magic bytes
  - Convert to MP3 for DFPlayer compatibility (using `ffmpeg`/`pydub`)
  - Preserve metadata during conversion
  - Show format info in GUI

- **Metadata Fallback**: 
  - If ID3 tags missing, use filename as title
  - Extract artist from folder structure if available
  - Allow manual metadata editing in GUI

- **Error Handling**: 
  - Validate SD card format (FAT32/exFAT)
  - Check free space before sync
  - Verify file integrity (hash checking)
  - Handle conversion errors gracefully
  - Log errors for debugging

- **Progress Feedback**: 
  - Show sync progress (files copied, conversion status)
  - Display file count, estimated time remaining
  - Cancel button for long operations
  - Detailed log view

- **Database Backup**: 
  - Automatic backups on database changes (configurable frequency)
  - Manual backup option
  - Timestamped backup files in `backups/` directory
  - Configurable retention (keep last N backups)
  - Restore from backup functionality
  - Backup before major operations (sync, import, etc.)

- **Metadata Sync Validation**:
  - On SD card load, compare database with file system
  - Check file existence, size, and hash
  - Detect missing files (in DB but not on SD)
  - Detect new files (on SD but not in DB)
  - Detect modified files (hash mismatch)
  - User preference: auto-sync on load (with confirmation) or manual sync
  - Sync dialog shows changes preview before applying

- **Export/Import System**:
  - Export albums/playlists to folders (`name_album`, `name_playlist`)
  - Include metadata.json in exported folders
  - Auto-detect exported folders on SD card load
  - Import dialog with preview
  - Handle duplicates intelligently (merge or skip)

## Testing Strategy

- Unit tests for database operations
- Integration tests for SD card sync
- Manual testing of GUI workflows
- Test mode validation against firmware behavior
- Cross-platform testing (Windows first, then Mac)

## Migration Path

- Existing SD cards with numbered folders continue to work
- New metadata file is additive (doesn't break old system)

- Firmware gracefully falls back if metadata missing
- Firmware gracefully falls back if metadata missing
- Users can gradually migrate to new system
- Import existing SD card structure into database
- Export/import allows sharing albums/playlists between users

## Implementation Priority

1. **Phase 1: Core Database & Audio Support**

   - SQLite schema with all tables
   - Database manager with backup functionality
   - Audio format detection and conversion
   - Metadata extraction for all formats

2. **Phase 2: GUI Foundation**

   - Main window layout
   - Library view with drag-and-drop
   - Album/playlist management UI
   - Settings/preferences UI

3. **Phase 3: SD Card Operations**

   - SD card detection (auto + manual)
   - Sync functionality with confirmation
   - Metadata sync validation
   - Export/import system

4. **Phase 4: Advanced Features**

   - Test mode emulator
   - Firmware updates
   - Polish and error handling