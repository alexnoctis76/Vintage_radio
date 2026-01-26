"""SD card management utilities."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import platform
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import psutil

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

from .audio_metadata import compute_file_hash, extract_metadata, file_matches_metadata
from .database import DatabaseManager


class SDManager:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    @staticmethod
    def detect_sd_roots() -> List[Tuple[Path, str]]:
        roots: List[Tuple[Path, str]] = []
        system_drive = os.environ.get("SystemDrive", "C:")
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            if not mount:
                continue
            if mount.upper().startswith(system_drive.upper()):
                continue
            opts = part.opts.lower()
            if "removable" in opts or part.fstype.lower() in {"fat", "fat32", "exfat"}:
                path = Path(mount)
                label = _get_volume_label(path)
                roots.append((path, label))
        return roots

    @staticmethod
    def volume_label(path: Path) -> str:
        return _get_volume_label(path)

    @staticmethod
    def library_root(sd_root: Path) -> Path:
        return sd_root / "VintageRadio" / "library"

    @staticmethod
    def vintage_root(sd_root: Path) -> Path:
        return sd_root / "VintageRadio"

    @staticmethod
    def _unique_path(root: Path, filename: str) -> Path:
        base = Path(filename).stem
        suffix = Path(filename).suffix
        candidate = root / filename
        counter = 1
        while candidate.exists():
            candidate = root / f"{base}_{counter}{suffix}"
            counter += 1
        return candidate

    def _check_ffmpeg(self) -> bool:
        """Check if ffmpeg is available (needed for audio conversion)."""
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
    
    def _check_vlc(self) -> bool:
        """
        Check if VLC is available (can be used for audio conversion).
        """
        try:
            # Try to find VLC executable
            # Common locations: vlc (Linux/Mac), "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe" (Windows)
            if platform.system() == "Windows":
                # Try common Windows paths
                vlc_paths = [
                    "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe",
                    "C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe",
                ]
                for vlc_path in vlc_paths:
                    if Path(vlc_path).exists():
                        return True
                # Try vlc in PATH
                result = subprocess.run(
                    ['vlc', '--version'],
                    capture_output=True,
                    timeout=2
                )
                return result.returncode == 0
            else:
                # Linux/Mac - vlc should be in PATH
                result = subprocess.run(
                    ['vlc', '--version'],
                    capture_output=True,
                    timeout=2
                )
                return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _get_vlc_path(self) -> str:
        """Get the path to VLC executable."""
        if platform.system() == "Windows":
            vlc_paths = [
                "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe",
                "C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe",
            ]
            for vlc_path in vlc_paths:
                if Path(vlc_path).exists():
                    return vlc_path
        # Try vlc in PATH
        return "vlc"
    
    def _convert_to_mp3_vlc(self, source_path: Path, target_path: Path) -> bool:
        """
        Convert audio file to MP3 using VLC command-line interface.
        Returns True if successful, False otherwise.
        """
        if not self._check_vlc():
            return False
        
        try:
            vlc_path = self._get_vlc_path()
            # VLC command-line conversion syntax:
            # vlc --intf dummy --sout "#transcode{acodec=mp3,ab=192}:std{access=file,mux=dummy,dst=output.mp3}" input.flac vlc://quit
            # Note: VLC requires the destination path to be absolute
            abs_target = str(target_path.resolve())
            abs_source = str(source_path.resolve())
            
            cmd = [
                vlc_path,
                '--intf', 'dummy',
                '--quiet',
                '--sout', f'#transcode{{acodec=mp3,ab=192}}:std{{access=file,mux=dummy,dst={abs_target}}}',
                abs_source,
                'vlc://quit'
            ]
            
            print(f"Attempting VLC conversion: {source_path.name} -> {target_path.name}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=300,  # 5 minute timeout for conversion
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if result.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0:
                print(f"VLC conversion successful: {source_path.name}")
                return True
            else:
                print(f"VLC conversion failed for {source_path.name}: return code {result.returncode}")
                if result.stderr:
                    error_msg = result.stderr.decode('utf-8', errors='ignore')
                    if error_msg.strip():
                        print(f"VLC error: {error_msg[:200]}")  # First 200 chars
                if result.stdout:
                    stdout_msg = result.stdout.decode('utf-8', errors='ignore')
                    if stdout_msg.strip():
                        print(f"VLC output: {stdout_msg[:200]}")
                return False
        except Exception as e:
            print(f"VLC conversion error for {source_path.name}: {e}")
            return False
    
    def _convert_to_mp3(self, source_path: Path, target_path: Path) -> bool:
        """
        Convert audio file to MP3 format for DFPlayer Mini compatibility.
        Supports: FLAC, WAV, OGG, M4A, AAC, and other formats.
        Tries VLC first (better FLAC support), falls back to pydub/ffmpeg.
        Returns True if successful, False otherwise.
        """
        source_ext = source_path.suffix.lower()
        
        # Try VLC first (especially good for FLAC)
        if self._check_vlc():
            if self._convert_to_mp3_vlc(source_path, target_path):
                return True
            print(f"VLC conversion failed for {source_path.name}, trying pydub/ffmpeg...")
        
        # Fall back to pydub/ffmpeg
        if not PYDUB_AVAILABLE:
            return False
        
        if not self._check_ffmpeg():
            return False
        
        try:
            # Load audio file (pydub uses ffmpeg for decoding)
            # Explicitly specify format for FLAC files to ensure proper handling
            if source_ext == ".flac":
                # Explicitly specify FLAC format for better compatibility
                audio = AudioSegment.from_file(str(source_path), format="flac")
            else:
                # Let pydub auto-detect format for other files
                audio = AudioSegment.from_file(str(source_path))
            
            # Export as MP3 with consistent quality settings
            # Use parameters that work well for all source formats
            audio.export(
                str(target_path),
                format="mp3",
                bitrate="192k",
                parameters=["-q:a", "2"]  # High quality VBR encoding
            )
            return True
        except Exception as e:
            print(f"pydub/ffmpeg conversion error for {source_path.name}: {e}")
            # Try alternative method for FLAC if first attempt failed
            if source_ext == ".flac":
                try:
                    # Try without explicit format specification
                    audio = AudioSegment.from_file(str(source_path))
                    audio.export(str(target_path), format="mp3", bitrate="192k")
                    return True
                except Exception as e2:
                    print(f"Alternative FLAC conversion also failed for {source_path.name}: {e2}")
            return False

    def sync_library(self, sd_root: Path) -> Tuple[int, int]:
        """
        Sync library to SD card, converting all files to MP3 for DFPlayer Mini compatibility.
        
        WHY CONVERT TO MP3?
        ===================
        The original firmware (main.py) uses:
        - DFPlayer Mini: For music track playback (primarily MP3)
        - RP2040 PWM: For AM overlay sound (WAV file - AMradioSound.wav)
        
        DFPlayer Mini hardware format support:
        - MP3: Fully supported, reliable, seeking works with setTime()
        - WAV: May work but format-dependent and unreliable for seeking
        - MIDI/FLAC/OGG/etc.: Not supported by DFPlayer Mini
        
        NOTE: While RP2040 CAN play WAV files directly via PWM (as shown with AMradioSound.wav),
        the music tracks are played through DFPlayer Mini, which primarily supports MP3.
        
        Since your GUI accepts ALL formats (MP3, WAV, FLAC, MIDI, OGG, etc.) for metadata extraction,
        but DFPlayer Mini can only reliably play MP3, we convert everything to MP3 during SD sync.
        
        This ensures:
        1. Hardware compatibility - all files will play on DFPlayer Mini
        2. Seeking works - setTime() command works reliably on MP3
        3. User convenience - users can import any format, conversion is automatic
        
        The original firmware likely only had MP3 files because users manually converted them
        before putting them on the SD card. We automate this step.
        """
        vintage_root = self.vintage_root(sd_root)
        vintage_root.mkdir(parents=True, exist_ok=True)
        library_root = self.library_root(sd_root)
        library_root.mkdir(parents=True, exist_ok=True)
        self._ensure_am_wav(vintage_root)

        songs = self.db.list_songs()
        copied = 0
        skipped = 0
        vlc_available = self._check_vlc()
        ffmpeg_available = self._check_ffmpeg()
        
        # Debug output
        if vlc_available:
            print(f"VLC available for conversion: {self._get_vlc_path()}")
        if ffmpeg_available and PYDUB_AVAILABLE:
            print("ffmpeg/pydub available for conversion")
        if not vlc_available and not (ffmpeg_available and PYDUB_AVAILABLE):
            print("Warning: No conversion tools available (VLC or ffmpeg/pydub)")
        
        for song in songs:
            file_path = Path(song["file_path"])
            if not file_path.exists():
                skipped += 1
                continue
            
            # Determine target filename (always MP3 for DFPlayer compatibility)
            source_ext = file_path.suffix.lower()
            target_filename = file_path.stem + ".mp3"
            
            existing_sd = song["sd_path"]
            if existing_sd:
                existing_path = Path(existing_sd)
                if existing_path.exists():
                    try:
                        # Check if file exists and is MP3 (converted)
                        if existing_path.suffix.lower() == ".mp3":
                            # Check if source hasn't changed (simple size check)
                            if existing_path.stat().st_size > 0:
                                skipped += 1
                                continue
                    except OSError:
                        pass
            
            target_path = self._unique_path(library_root, target_filename)
            
            try:
                # Convert to MP3 if needed (for DFPlayer Mini compatibility)
                if source_ext == ".mp3":
                    # Already MP3, just copy
                    shutil.copy2(file_path, target_path)
                else:
                    # Convert to MP3 - try conversion (VLC or pydub/ffmpeg)
                    if self._convert_to_mp3(file_path, target_path):
                        print(f"Converted {file_path.name} to MP3")
                    else:
                        # Conversion failed - check what's available for better error message
                        if not vlc_available and not (ffmpeg_available and PYDUB_AVAILABLE):
                            print(f"Cannot convert {file_path.name} (VLC and ffmpeg/pydub not available), skipping")
                        else:
                            print(f"Failed to convert {file_path.name}, skipping")
                        skipped += 1
                        continue
                
                self.db.update_song_sd_path(song["id"], str(target_path))
                copied += 1
            except OSError as e:
                print(f"Error syncing {file_path.name}: {e}")
                skipped += 1
        
        self._write_metadata(vintage_root)
        return copied, skipped

    def validate_sd(self) -> Dict[str, List[Dict[str, str]]]:
        results: Dict[str, List[Dict[str, str]]] = {
            "missing_sd_path": [],
            "missing_file": [],
            "size_mismatch": [],
            "hash_mismatch": [],
        }
        songs = self.db.list_songs()
        for song in songs:
            sd_path = song["sd_path"]
            if not sd_path:
                results["missing_sd_path"].append(
                    {"id": str(song["id"]), "title": song["title"] or ""}
                )
                continue
            path = Path(sd_path)
            if not path.exists():
                results["missing_file"].append(
                    {"id": str(song["id"]), "title": song["title"] or ""}
                )
                continue
            
            # Check if file format changed (conversion occurred)
            # Format in DB might be stored with or without dot (e.g., "flac" or ".flac")
            # sqlite3.Row uses [] access, not .get()
            original_format = (song["format"] or "").lower().lstrip(".") if song["format"] else ""
            sd_format = path.suffix.lower().lstrip(".")
            format_changed = (
                original_format and 
                sd_format and 
                original_format != sd_format and
                sd_format == "mp3"  # SD files are always MP3 after conversion
            )
            
            expected_size = song["file_size"]
            if expected_size is not None:
                try:
                    actual_size = path.stat().st_size
                    if actual_size != expected_size:
                        # Size mismatch is expected if format was converted
                        if not format_changed:
                            # Only report as mismatch if format didn't change
                            results["size_mismatch"].append(
                                {
                                    "id": str(song["id"]), 
                                    "title": song["title"] or "",
                                    "reason": "size_mismatch"
                                }
                            )
                        # If format changed, size difference is expected (conversion)
                        continue
                except OSError:
                    results["size_mismatch"].append(
                        {
                            "id": str(song["id"]), 
                            "title": song["title"] or "",
                            "reason": "file_error"
                        }
                    )
                    continue
            
            # Hash check - skip if format was converted (hash will be different)
            if song["file_hash"] and not format_changed:
                if not file_matches_metadata(path, expected_size, song["file_hash"]):
                    results["hash_mismatch"].append(
                        {"id": str(song["id"]), "title": song["title"] or ""}
                    )
        return results

    def export_album(self, album_id: int, sd_root: Path) -> Optional[Path]:
        album = self.db.get_album_by_id(album_id)
        if album is None:
            return None
        vintage_root = self.vintage_root(sd_root)
        vintage_root.mkdir(parents=True, exist_ok=True)
        folder = vintage_root / f"{album['name']}_album"
        folder.mkdir(parents=True, exist_ok=True)
        tracks = self.db.list_album_songs(album_id)
        metadata = {
            "type": "album",
            "id": album_id,
            "name": album["name"],
            "description": album["description"] or "",
            "tracks": [],
        }
        for index, song in enumerate(tracks, start=1):
            source = Path(song["file_path"])
            if not source.exists():
                continue
            target = folder / source.name
            shutil.copy2(source, target)
            metadata["tracks"].append(
                {
                    "order": index,
                    "filename": source.name,
                    "title": song["title"],
                    "artist": song["artist"],
                }
            )
        with (folder / "metadata.json").open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
        return folder

    def export_playlist(self, playlist_id: int, sd_root: Path) -> Optional[Path]:
        playlist = self.db.get_playlist_by_id(playlist_id)
        if playlist is None:
            return None
        vintage_root = self.vintage_root(sd_root)
        vintage_root.mkdir(parents=True, exist_ok=True)
        folder = vintage_root / f"{playlist['name']}_playlist"
        folder.mkdir(parents=True, exist_ok=True)
        tracks = self.db.list_playlist_songs(playlist_id)
        metadata = {
            "type": "playlist",
            "id": playlist_id,
            "name": playlist["name"],
            "description": playlist["description"] or "",
            "tracks": [],
        }
        for index, song in enumerate(tracks, start=1):
            source = Path(song["file_path"])
            if not source.exists():
                continue
            target = folder / source.name
            shutil.copy2(source, target)
            metadata["tracks"].append(
                {
                    "order": index,
                    "filename": source.name,
                    "title": song["title"],
                    "artist": song["artist"],
                }
            )
        with (folder / "metadata.json").open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
        return folder

    def import_from_sd(self, sd_root: Path) -> Dict[str, int]:
        imported_albums = 0
        imported_playlists = 0
        vintage_root = self.vintage_root(sd_root)
        if not vintage_root.exists():
            return {"albums": 0, "playlists": 0}
        for folder in vintage_root.iterdir():
            if not folder.is_dir():
                continue
            name = folder.name
            if name.endswith("_album"):
                if self._import_collection(folder, is_album=True):
                    imported_albums += 1
            elif name.endswith("_playlist"):
                if self._import_collection(folder, is_album=False):
                    imported_playlists += 1
        return {"albums": imported_albums, "playlists": imported_playlists}

    def _write_metadata(self, vintage_root: Path) -> None:
        metadata = {
            "folders": {},
            "songs": {},
        }
        folder_index = 1
        for album in self.db.list_albums():
            tracks = self.db.list_album_songs(album["id"])
            folder_key = f"{folder_index:02d}"
            metadata["folders"][folder_key] = {
                "type": "album",
                "id": album["id"],
                "name": album["name"],
                "tracks": [
                    {"song_id": song["id"], "track": idx + 1}
                    for idx, song in enumerate(tracks)
                ],
            }
            folder_index += 1
        for playlist in self.db.list_playlists():
            tracks = self.db.list_playlist_songs(playlist["id"])
            folder_key = f"{folder_index:02d}"
            metadata["folders"][folder_key] = {
                "type": "playlist",
                "id": playlist["id"],
                "name": playlist["name"],
                "tracks": [
                    {"song_id": song["id"], "track": idx + 1}
                    for idx, song in enumerate(tracks)
                ],
            }
            folder_index += 1

        for song in self.db.list_songs():
            metadata["songs"][str(song["id"])] = {
                "title": song["title"],
                "artist": song["artist"],
                "original_file": song["original_filename"],
                "hash": song["file_hash"],
                "sd_path": song["sd_path"],
            }

        metadata_path = vintage_root / "radio_metadata.json"
        try:
            with metadata_path.open("w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2)
        except OSError:
            pass

    def _ensure_am_wav(self, vintage_root: Path) -> None:
        source = Path(__file__).resolve().parent / "resources" / "AMradioSound.wav"
        target = vintage_root / "AMradioSound.wav"
        if target.exists() or not source.exists():
            return
        try:
            shutil.copy2(source, target)
        except OSError:
            pass

    def _import_collection(self, folder: Path, *, is_album: bool) -> bool:
        metadata_path = folder / "metadata.json"
        tracks: List[Dict[str, str]] = []
        name = folder.name.rsplit("_", 1)[0]
        description = ""
        if metadata_path.exists():
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                name = data.get("name", name)
                description = data.get("description", "")
                tracks = data.get("tracks", [])
            except (OSError, json.JSONDecodeError):
                tracks = []
        if not tracks:
            tracks = [
                {"filename": path.name, "order": index}
                for index, path in enumerate(sorted(folder.iterdir()), start=1)
                if path.is_file() and path.name.lower() != "metadata.json"
            ]
        if is_album:
            collection_id = self.db.create_album(name, description)
        else:
            collection_id = self.db.create_playlist(name, description)
        for entry in sorted(tracks, key=lambda item: item.get("order", 0)):
            filename = entry.get("filename")
            if not filename:
                continue
            file_path = folder / filename
            if not file_path.exists():
                continue
            metadata = extract_metadata(file_path)
            file_hash = compute_file_hash(file_path)
            existing = self.db.get_song_by_hash_size(
                file_hash, metadata["file_size"]
            )
            if existing is None:
                song_id = self.db.add_song(
                    original_filename=metadata["original_filename"],
                    file_path=str(file_path),
                    title=metadata["title"],
                    artist=metadata["artist"],
                    duration=metadata["duration"],
                    file_hash=file_hash,
                    file_size=metadata["file_size"],
                    format=metadata["format"],
                    sd_path=str(file_path),
                )
            else:
                song_id = int(existing["id"])
            order = int(entry.get("order", 0)) or 1
            if is_album:
                self.db.add_song_to_album(collection_id, song_id, order)
            else:
                self.db.add_song_to_playlist(collection_id, song_id, order)
        return True


def _get_volume_label(path: Path) -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return ""
    volume_name = ctypes.create_unicode_buffer(261)
    file_system_name = ctypes.create_unicode_buffer(261)
    serial_number = wintypes.DWORD()
    max_component_length = wintypes.DWORD()
    file_system_flags = wintypes.DWORD()
    root_path = str(path)
    if not root_path.endswith("\\"):
        root_path += "\\"
    result = ctypes.windll.kernel32.GetVolumeInformationW(
        root_path,
        volume_name,
        len(volume_name),
        ctypes.byref(serial_number),
        ctypes.byref(max_component_length),
        ctypes.byref(file_system_flags),
        file_system_name,
        len(file_system_name),
    )
    if result:
        return volume_name.value or ""
    return ""

