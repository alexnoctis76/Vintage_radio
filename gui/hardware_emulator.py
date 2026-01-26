"""
Hardware Emulator for GUI Test Mode

This module implements the HardwareInterface from radio_core.py
using pygame for audio playback and the database for storage.

This allows the GUI test mode to run the exact same logic as the firmware.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional
import json
import time
import tempfile
import subprocess

try:
    import pygame
except ImportError:
    pygame = None

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    VLC_AVAILABLE = False

from .database import DatabaseManager

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_core import HardwareInterface


class PygameHardwareEmulator(HardwareInterface):
    """
    Hardware emulator using pygame for audio and SQLite for storage.
    """
    
    def __init__(
        self,
        db: DatabaseManager,
        log_callback: Optional[Callable[[str], None]] = None,
        am_wav_path: Optional[Path] = None,
    ):
        self.db = db
        self._log_callback = log_callback
        self.am_wav_path = am_wav_path
        
        self._audio_ready = False
        self._am_sound = None
        self._am_channel = None
        self._volume = 100
        self._is_playing = False
        self._playback_start_time = 0
        self._playback_start_offset_ms = 0  # Track the offset we started playback at
        self._current_sound = None  # For WAV files loaded as Sound objects
        self._current_channel = None  # Channel for current Sound object
        self._current_temp_file = None  # Temporary file for seeking (pydub)
        
        # VLC player instance (if available - provides native seeking for all formats)
        self._vlc_instance = None
        self._vlc_player = None
        self._vlc_am_player = None  # For AM overlay
        
        # Flag to delay playback (used for AM overlay sequencing)
        self._delay_playback = False
        self._pending_playback = None  # (folder, track, start_ms) tuple
        
        # Check if ffmpeg is available (needed for seeking all formats with pygame fallback)
        self._ffmpeg_available = self._check_ffmpeg()
        
        # Track metadata cache
        self._track_cache: Dict[int, Dict] = {}
        
        self._init_audio()
    
    def _check_ffmpeg(self) -> bool:
        """Check if ffmpeg is available (needed for seeking all audio formats)."""
        if not PYDUB_AVAILABLE:
            return False
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _init_audio(self):
        """Initialize audio - try VLC first (better seeking), fall back to pygame."""
        # Try VLC first (native seeking for all formats, no temp files needed)
        if VLC_AVAILABLE:
            try:
                self._vlc_instance = vlc.Instance('--intf', 'dummy', '--quiet')
                self._vlc_player = self._vlc_instance.media_player_new()
                self._vlc_am_player = self._vlc_instance.media_player_new()
                self._audio_ready = True
                self.log("Audio initialized (VLC - native seeking for all formats)")
                
                # Load AM sound if path provided
                if self.am_wav_path and self.am_wav_path.exists():
                    try:
                        am_media = self._vlc_instance.media_new(str(self.am_wav_path))
                        self._vlc_am_player.set_media(am_media)
                        self.log(f"AM sound loaded: {self.am_wav_path}")
                    except Exception as e:
                        self.log(f"Failed to load AM sound: {e}")
                return
            except Exception as e:
                self.log(f"VLC init failed: {e}, falling back to pygame")
        
        # Fall back to pygame (requires temp files for seeking non-OGG formats)
        if pygame is None:
            self.log("pygame not available - audio disabled")
            return
        
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
            self._audio_ready = True
            self.log("Audio initialized (pygame - temp files needed for seeking non-OGG formats)")
            
            # Load AM sound if path provided
            if self.am_wav_path and self.am_wav_path.exists():
                try:
                    self._am_sound = pygame.mixer.Sound(str(self.am_wav_path))
                    self.log(f"AM sound loaded: {self.am_wav_path}")
                except Exception as e:
                    self.log(f"Failed to load AM sound: {e}")
        except Exception as e:
            self.log(f"Audio init failed: {e}")
            self._audio_ready = False
    
    def set_current_track_hint(self, track_dict: Optional[Dict]):
        """Set a hint for the current track - used by RadioCore before play_track."""
        self._current_track_hint = track_dict
    
    def set_delay_playback(self, delay: bool):
        """Enable/disable playback delay (for AM overlay sequencing)."""
        self._delay_playback = delay
        if not delay and self._pending_playback:
            # Playback delay disabled, execute pending playback
            folder, track, start_ms = self._pending_playback
            self._pending_playback = None
            self.play_track(folder, track, start_ms)
    
    def execute_pending_playback(self):
        """Execute any pending playback (after AM overlay finishes)."""
        if self._pending_playback:
            folder, track, start_ms = self._pending_playback
            self._pending_playback = None
            self._delay_playback = False
            # Call play_track directly (bypassing delay check since we disabled it)
            self.play_track(folder, track, start_ms)
    
    def play_track(self, folder: int, track: int, start_ms: int = 0):
        """Play a track by folder/track number or by resolving from database."""
        if not self._audio_ready:
            self.log("Audio not ready")
            return
        
        # If playback is delayed (for AM overlay sequencing), store the request
        if self._delay_playback:
            self._pending_playback = (folder, track, start_ms)
            self.log(f"Playback delayed (AM overlay sequencing): folder={folder}, track={track}, start_ms={start_ms}")
            return
        
        # Normal playback (delay disabled or not in use)
        
        # First try the track hint if set
        song = getattr(self, '_current_track_hint', None)
        if song is None:
            # Fall back to finding by folder/track number
            song = self._find_track(folder, track)
        
        # Clear the hint after use
        self._current_track_hint = None
        
        if not song:
            self.log(f"Track not found: folder={folder}, track={track}")
            return
        
        path = self._resolve_path(song)
        if not path:
            self.log(f"File not found for track: {song.get('title', 'Unknown')}")
            return
        
        try:
            file_ext = Path(path).suffix.lower()
            
            # Use VLC if available (native seeking for ALL formats, no temp files)
            if self._vlc_player:
                try:
                    media = self._vlc_instance.media_new(str(path))
                    self._vlc_player.set_media(media)
                    self._vlc_player.set_volume(self._volume)
                    
                    # VLC supports native seeking for ALL formats!
                    if start_ms and start_ms > 0:
                        # VLC uses milliseconds for set_time
                        self._vlc_player.set_time(start_ms)
                    
                    self._vlc_player.play()
                    self._playback_start_time = time.time() * 1000
                    self._playback_start_offset_ms = start_ms if start_ms else 0
                    self._is_playing = True
                    
                    self.log(f"Playing: {song.get('title', 'Unknown')} (start={start_ms}ms, VLC - native seeking for ALL formats)")
                    return
                except Exception as e:
                    self.log(f"VLC playback failed: {e}, falling back to pygame")
            
            # Fall back to pygame (requires temp files for seeking non-OGG formats)
            # 
            # WHY TEMP FILES WITH PYGAME?
            # ============================
            # pygame.mixer.music.set_pos() only works for OGG/Vorbis files.
            # For other formats (MP3, WAV, MIDI, FLAC, etc.), pygame has NO direct seeking API.
            # 
            # pygame.mixer.Sound loads entire files into memory but also doesn't support
            # seeking to arbitrary positions - it always plays from the beginning.
            #
            # The temp file approach is the standard workaround:
            # 1. Decode audio file (pydub + ffmpeg handles all formats)
            # 2. Extract segment starting from start_ms
            # 3. Export segment to temporary WAV file
            # 4. Play the temp file (pygame can play WAV from start)
            # 5. Clean up temp file on stop
            #
            # This is necessary because pygame doesn't have a "seek to position X" API
            # for most audio formats. The temp file is the only way to start playback
            # from an arbitrary position in formats that don't support seeking.
            if start_ms and start_ms > 0 and PYDUB_AVAILABLE and self._ffmpeg_available:
                try:
                    # Load audio file (pydub uses ffmpeg for decoding - works for all formats)
                    audio = AudioSegment.from_file(str(path))
                    
                    # Extract segment starting from start_ms
                    remaining_audio = audio[start_ms:]
                    
                    # Export to temporary WAV file (pygame can play WAV reliably)
                    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                        tmp_path = Path(tmp_file.name)
                        remaining_audio.export(str(tmp_path), format="wav")
                    
                    # Play the temporary file
                    pygame.mixer.music.load(str(tmp_path))
                    pygame.mixer.music.set_volume(self._volume / 100.0)
                    pygame.mixer.music.play()
                    
                    # Store temp file path for cleanup
                    self._current_temp_file = tmp_path
                    self._playback_start_offset_ms = start_ms
                    self._playback_start_time = time.time() * 1000
                    
                    self.log(f"Playing: {song.get('title', 'Unknown')} (start={start_ms}ms, using pydub+ffmpeg - works for ALL formats)")
                    self._is_playing = True
                    self._current_sound = None
                    self._current_channel = None
                    return
                except Exception as e:
                    # Fallback to normal playback if pydub/ffmpeg fails
                    self.log(f"Pydub seeking failed ({e}), falling back to normal playback")
            
            # Default: use mixer.music (streaming)
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self._volume / 100.0)
            pygame.mixer.music.play()
            
            # Try pygame's set_pos if seeking (only works for OGG)
            if start_ms and start_ms > 0:
                time.sleep(0.1)  # Small delay to ensure playback has started
                try:
                    pygame.mixer.music.set_pos(start_ms / 1000.0)
                    self.log(f"Playing: {song.get('title', 'Unknown')} (start={start_ms}ms, seeking via set_pos - OGG format)")
                except Exception:
                    # set_pos failed (format doesn't support seeking in pygame)
                    # Virtual time tracking will still be correct
                    self.log(f"Playing: {song.get('title', 'Unknown')} (intended start={start_ms}ms, seeking not supported for {file_ext} format)")
            else:
                self.log(f"Playing: {song.get('title', 'Unknown')} (start=0ms)")
            
            # Track when playback started and the offset for virtual time calculations
            self._playback_start_time = time.time() * 1000
            self._playback_start_offset_ms = start_ms if start_ms else 0
            self._is_playing = True
            self._current_sound = None
            self._current_channel = None
            self._current_temp_file = None
        except Exception as e:
            self.log(f"Playback error: {e}")
    
    def _find_track(self, folder: int, track: int) -> Optional[Dict]:
        """Find track by folder/track number."""
        # Check cache first
        cache_key = (folder, track)
        if cache_key in self._track_cache:
            return self._track_cache[cache_key]
        
        # Search in albums (folder = album index + 1, track = track number)
        albums = self.get_albums()
        if folder <= len(albums) and folder > 0:
            album = albums[folder - 1]
            tracks = album.get('tracks', [])
            if track <= len(tracks) and track > 0:
                song = tracks[track - 1]
                self._track_cache[cache_key] = song
                return song
        
        # Fallback: search all tracks
        all_tracks = self.get_all_tracks()
        for t in all_tracks:
            if t.get('folder') == folder and t.get('track_number') == track:
                self._track_cache[cache_key] = t
                return t
        
        # Last resort: just get track by index
        if track <= len(all_tracks) and track > 0:
            return all_tracks[track - 1]
        
        return None
    
    def _resolve_path(self, song: Dict) -> Optional[str]:
        """
        Resolve the file path for a song.
        
        Priority (matches firmware behavior):
        1. SD card path (if exists) - this is what firmware uses
        2. Original library path (fallback if SD card not mounted)
        
        This ensures GUI test mode uses the same files as the firmware.
        """
        # Try SD path first (like firmware does)
        sd_path = song.get('sd_path')
        if sd_path:
            sd_path_obj = Path(sd_path)
            if sd_path_obj.exists():
                self.log(f"Using SD card file: {sd_path}")
                return str(sd_path_obj)
            else:
                self.log(f"SD card file not found: {sd_path}, falling back to original")
        
        # Fallback to original library path
        local_path = song.get('file_path')
        if local_path:
            local_path_obj = Path(local_path)
            if local_path_obj.exists():
                self.log(f"Using original library file: {local_path}")
                return str(local_path_obj)
        
        self.log(f"No valid path found for song: {song.get('title', 'Unknown')}")
        return None
    
    def stop(self):
        """Stop playback."""
        if not self._audio_ready:
            return
        try:
            # Stop Sound object if playing
            if self._current_channel:
                self._current_channel.stop()
                self._current_channel = None
                self._current_sound = None
            
            # Stop mixer.music if playing
            pygame.mixer.music.stop()
            
            # Clean up temporary file if one was created for seeking
            if self._current_temp_file and self._current_temp_file.exists():
                try:
                    self._current_temp_file.unlink()
                except Exception:
                    pass
                self._current_temp_file = None
            
            if self._am_channel:
                self._am_channel.stop()
            self._is_playing = False
            self.log("Playback stopped")
        except Exception as e:
            self.log(f"Stop error: {e}")
    
    def set_volume(self, level: int):
        """Set volume (0-100)."""
        self._volume = max(0, min(100, level))
        if self._audio_ready:
            try:
                if self._vlc_player:
                    self._vlc_player.audio_set_volume(self._volume)
                elif pygame:
                    pygame.mixer.music.set_volume(self._volume / 100.0)
            except Exception:
                pass
    
    def is_playing(self) -> bool:
        """Return True if currently playing."""
        if not self._audio_ready:
            return False
        try:
            if self._vlc_player and VLC_AVAILABLE:
                state = self._vlc_player.get_state()
                return state in (vlc.State.Playing, vlc.State.Buffering)
            elif pygame:
                # Check Sound object if using one
                if self._current_channel:
                    return self._current_channel.get_busy()
                
                # Check mixer.music
                return self._is_playing and pygame.mixer.music.get_busy()
        except Exception:
            return False
    
    def get_playback_position_ms(self) -> int:
        """Return current playback position in milliseconds."""
        if not self._audio_ready or not self._is_playing:
            return 0
        try:
            if self._vlc_player:
                # VLC provides native position in milliseconds
                pos_ms = self._vlc_player.get_time()
                if pos_ms < 0:
                    # Not playing or position unknown, use virtual time
                    elapsed_ms = int((time.time() * 1000) - self._playback_start_time)
                    return self._playback_start_offset_ms + elapsed_ms
                return pos_ms
            elif pygame:
                # If using Sound object (WAV files), calculate position differently
                if self._current_sound and self._current_channel and self._current_channel.get_busy():
                    # For Sound objects, we track elapsed time from start
                    elapsed_ms = int((time.time() * 1000) - self._playback_start_time)
                    actual_pos = self._playback_start_offset_ms + elapsed_ms
                    return actual_pos
                
                # Default: use mixer.music position
                pygame_pos = pygame.mixer.music.get_pos()
                if pygame_pos < 0:
                    pygame_pos = 0
                
                # Add the start offset to get the actual position in the original file
                actual_pos = self._playback_start_offset_ms + pygame_pos
                return actual_pos
        except Exception:
            # Fallback to virtual time tracking
            elapsed_ms = int((time.time() * 1000) - self._playback_start_time)
            return self._playback_start_offset_ms + elapsed_ms
    
    def play_am_overlay(self):
        """Play the AM radio sound overlay."""
        if not self._audio_ready:
            return
        try:
            if self._vlc_am_player:
                # VLC AM overlay
                self._vlc_am_player.play()
                self.log("AM overlay playing (VLC)")
            elif self._am_sound:
                # pygame AM overlay
                self._am_channel = pygame.mixer.find_channel()
                if self._am_channel:
                    self._am_channel.set_volume(1.0)
                    self._am_channel.play(self._am_sound)
                    self.log("AM overlay playing (pygame)")
        except Exception as e:
            self.log(f"AM overlay error: {e}")
    
    def save_state(self, state_dict: Dict):
        """Persist state to database settings."""
        try:
            self.db.set_setting('radio_state', json.dumps(state_dict))
        except Exception as e:
            self.log(f"Save state error: {e}")
    
    def load_state(self) -> Optional[Dict]:
        """Load state from database settings."""
        try:
            state_json = self.db.get_setting('radio_state')
            if state_json:
                return json.loads(state_json)
        except Exception as e:
            self.log(f"Load state error: {e}")
        return None
    
    def log(self, message: str):
        """Log a message."""
        if self._log_callback:
            self._log_callback(message)
        else:
            print(f"[HW] {message}")
    
    def get_albums(self) -> List[Dict]:
        """Return list of albums with tracks."""
        albums = []
        for album in self.db.list_albums():
            tracks = self.db.list_album_songs(album['id'])
            albums.append({
                'id': album['id'],
                'name': album['name'],
                'tracks': [self._enrich_track(t, idx + 1, album['id']) for idx, t in enumerate(tracks)],
            })
        return albums
    
    def get_playlists(self) -> List[Dict]:
        """Return list of playlists with tracks."""
        playlists = []
        for playlist in self.db.list_playlists():
            tracks = self.db.list_playlist_songs(playlist['id'])
            playlists.append({
                'id': playlist['id'],
                'name': playlist['name'],
                'tracks': [self._enrich_track(t, idx + 1) for idx, t in enumerate(tracks)],
            })
        return playlists
    
    def get_all_tracks(self) -> List[Dict]:
        """Return list of all tracks."""
        tracks = self.db.list_songs()
        return [self._enrich_track(t, idx + 1) for idx, t in enumerate(tracks)]
    
    def _enrich_track(self, track: Dict, track_number: int, folder: int = 1) -> Dict:
        """Add folder/track_number to track dict for DFPlayer compatibility."""
        result = dict(track)
        result['track_number'] = track_number
        result['folder'] = folder
        return result
    
    def check_track_finished(self) -> bool:
        """Check if current track has finished playing."""
        if not self._audio_ready:
            return False
        was_playing = self._is_playing
        is_now_playing = self.is_playing()
        if was_playing and not is_now_playing:
            self._is_playing = False
            return True
        return False

