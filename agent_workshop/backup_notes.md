# Backup Notes - Working Test Mode Logic

## What Was Working Before RadioCore Integration

### 1. Audio Initialization
- test_mode.py had its own `_init_audio()` that initialized pygame
- Used `self.audio_ready`, `self.am_sound`, `self.am_channel`
- Volume fade-in using `_fade_timer` and `_tick_fade()`

### 2. Playback
- `_start_playback(path, start_ms, with_am_overlay)` - Core playback method
- `_start_playback_for_current()` - Gets current song and plays it
- `_start_playback_for_song(song, offset_ms, with_am_overlay)` - Play specific song
- Playback monitoring via `_poll_playback()` timer checking `pygame.mixer.music.get_busy()`

### 3. Track Advancement
- `_advance_next()` - Handled all modes (shuffle, radio, album, playlist)
- `_on_track_finished()` - Called when track ends, triggers `_advance_next()`
- For shuffle: increments `shuffle_index`, reshuffles at end
- For radio: increments `current_track` within station
- For album/playlist: increments `current_track`, wraps at end

### 4. Shuffle Mode
- `shuffle_tracks` - List of track dicts from database
- `shuffle_index` - Current position in shuffled list
- On reaching end: `random.shuffle(shuffle_tracks)` and reset index to 0

### 5. Radio Mode
- `radio_stations` - List of RadioStation dataclass objects
- Each station has: name, tracks, total_duration_ms, start_offset_ms
- `radio_mode_start_time` - time.monotonic() when radio mode started
- Virtual time: calculates position based on elapsed time since mode start
- `_select_radio_station(dial_value)` - Maps 0-100 dial to station index
- `_find_track_at_position(tracks, position_ms)` - Finds track at virtual time

### 6. Key Data Structures
```python
@dataclass
class AlbumState:
    album_id: int
    name: str
    tracks: List[Dict]

@dataclass
class PlaylistState:
    playlist_id: int
    name: str
    tracks: List[Dict]

@dataclass
class RadioStation:
    name: str
    tracks: List[Dict]
    total_duration_ms: int
    start_offset_ms: int
```

### 7. Key State Variables
- `mode`: "album" | "playlist" | "shuffle" | "radio"
- `current_album_index`: Index into albums or playlists list
- `current_track`: 1-based track number
- `shuffle_tracks`: List of track dicts
- `shuffle_index`: 0-based index into shuffle_tracks
- `radio_stations`: List of RadioStation objects
- `radio_station_index`: Index into radio_stations
- `is_playing`: Boolean
- `audio_ready`: Boolean

## RadioCore Differences

RadioCore uses different data structures:
- `self.albums` - List of dicts with 'id', 'name', 'tracks' keys
- `self.playlists` - List of dicts with 'id', 'name', 'tracks' keys
- `self.radio_stations` - List of RadioStation objects from radio_core.py (different class!)
- Track dicts expect `folder` and `track_number` keys for DFPlayer

## Integration Issues Found

1. **Two pygame inits** - Both test_mode and hw_emulator init pygame
2. **RadioCore.init() never called** - So playback never starts
3. **power_on_handler returns early** - Because power_on is already True on boot
4. **Track format mismatch** - hw_emulator expects folder/track_number
5. **refresh_from_db overwrites state** - Resets indexes after sync
6. **Two auto-advance systems** - _poll_playback AND _core_tick both try to advance

