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
from .resource_paths import resource_path


# Volume label we set on the SD card after first sync so we can recognize it among multiple cards
SYNC_TARGET_VOLUME_LABEL = "VINTAGERADIO"


class SDManager:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    @staticmethod
    def set_sync_target_volume_label(sd_root: Path) -> bool:
        """
        Try to set the volume label of the given path to SYNC_TARGET_VOLUME_LABEL
        so we can detect "our" SD card when multiple are present.
        Returns True if we believe the label was set (or already matched).
        """
        try:
            system = platform.system()
            if system == "Windows":
                root = str(sd_root.resolve())
                if len(root) >= 2 and root[1] == ":":
                    drive = root[:2]
                    try:
                        import ctypes
                        from ctypes import wintypes
                        if ctypes.windll.kernel32.SetVolumeLabelW(drive + "\\", SYNC_TARGET_VOLUME_LABEL):
                            return True
                    except Exception:
                        pass
                    try:
                        r = subprocess.run(
                            ["label", drive, SYNC_TARGET_VOLUME_LABEL],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        return r.returncode == 0
                    except Exception:
                        pass
                return False
            if system == "Darwin":
                volumes = Path("/Volumes")
                if not volumes.exists():
                    return False
                for item in volumes.iterdir():
                    if not item.is_dir():
                        continue
                    try:
                        if sd_root.resolve() == item.resolve():
                            current = item.name
                            if current == SYNC_TARGET_VOLUME_LABEL:
                                return True
                            r = subprocess.run(
                                ["diskutil", "rename", current, SYNC_TARGET_VOLUME_LABEL],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            return r.returncode == 0
                    except (OSError, PermissionError):
                        continue
                return False
        except Exception:
            pass
        return False

    @staticmethod
    def is_sync_target_sd_present(sd_root: Optional[str], stored_label: Optional[str]) -> bool:
        """
        Return True only when the SD card we sync to is actually connected and
        visible as a removable drive. Uses detect_sd_roots() so we don't show
        "out of sync" when the card is unplugged (path may still exist on some systems).
        """
        detected = SDManager.detect_sd_roots()
        if not detected:
            return False
        try:
            sd_path = Path(sd_root).resolve() if sd_root else None
        except Exception:
            sd_path = None
        for path, label in detected:
            if sd_path is not None:
                try:
                    pr = path.resolve()
                    if sd_path == pr or pr in sd_path.parents or sd_path in path.parents:
                        return True
                except Exception:
                    pass
            if stored_label and label and label.strip().upper() == stored_label.strip().upper():
                return True
        return False

    @staticmethod
    def detect_sd_roots() -> List[Tuple[Path, str]]:
        """
        Detect external storage devices (SD cards, USB drives) across platforms.

        Windows: Uses removable flag and filesystem type (FAT, FAT32, ExFAT)
        macOS: Scans /Volumes excluding system volumes
        Linux: Scans /mnt and /media for external mounts
        """
        roots: List[Tuple[Path, str]] = []
        system = platform.system()

        if system == "Windows":
            # Windows: Use psutil to detect removable drives
            system_drive = os.environ.get("SystemDrive", "C:")
            for part in psutil.disk_partitions(all=False):
                mount = part.mountpoint
                if not mount:
                    continue
                # Skip system drive
                if mount.upper().startswith(system_drive.upper()):
                    continue
                # Check for removable flag or typical external filesystem types
                opts = part.opts.lower()
                fstype = part.fstype.lower()
                if "removable" in opts or fstype in {"fat", "fat32", "exfat"}:
                    path = Path(mount)
                    if path.exists():
                        label = _get_volume_label(path)
                        roots.append((path, label))

        elif system == "Darwin":
            # macOS: Scan /Volumes for mounted external drives
            # Exclude system volumes, recovery, installer, and temporary volumes
            system_volume_keywords = {
                "Macintosh HD", "System", "Recovery", "Install", "Installer",
                ".localized", ".disabled", "MobileBackups", "Update", "TimeMachine",
                "Shared Support", "Caches", "VM", "Temp"
            }

            volumes_path = Path("/Volumes")
            if volumes_path.exists():
                try:
                    for item in volumes_path.iterdir():
                        # Skip system volume names and hidden volumes
                        name = item.name

                        # Skip if name matches system patterns
                        if name.startswith("."):
                            continue
                        if any(keyword.lower() in name.lower() for keyword in system_volume_keywords):
                            continue

                        # Verify it's actually a mount point and accessible
                        if item.is_dir() and os.access(item, os.R_OK):
                            label = item.name
                            roots.append((item, label))
                except (OSError, PermissionError):
                    pass

        elif system == "Linux":
            # Linux: Check common mount points for external drives
            mount_points = [Path("/mnt"), Path("/media")]
            for mount_base in mount_points:
                if not mount_base.exists():
                    continue
                try:
                    for item in mount_base.iterdir():
                        # Skip system mounts and hidden directories
                        if item.name.startswith("."):
                            continue
                        # Check if it's a readable directory
                        if item.is_dir() and os.access(item, os.R_OK):
                            # Try to filter out system mounts by checking psutil
                            is_system_mount = False
                            for part in psutil.disk_partitions(all=True):
                                if part.mountpoint == str(item):
                                    # Skip root filesystem and common system mounts
                                    if part.fstype in {"ext4", "btrfs", "tmpfs", "devtmpfs", "squashfs"}:
                                        is_system_mount = True
                                    break
                            if not is_system_mount:
                                label = item.name
                                roots.append((item, label))
                except (OSError, PermissionError):
                    pass

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

        Returns True if either the python-vlc (libvlc) binding is importable
        or a VLC executable is detectable on the system (PATH or common app
        locations). This makes VLC conversion more reliable on macOS where
        the CLI may not be installed by default.
        """
        # 1) python-vlc (libvlc) available?
        try:
            import vlc as _vlc
            return True
        except Exception:
            pass

        # 2) Executable-based VLC detection
        try:
            # macOS app bundle path
            if platform.system() == "Darwin":
                mac_path = Path("/Applications/VLC.app/Contents/MacOS/VLC")
                if mac_path.exists():
                    return True
            # Windows common install locations or CLI in PATH
            if platform.system() == "Windows":
                vlc_paths = [
                    "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe",
                    "C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe",
                ]
                for vlc_path in vlc_paths:
                    if Path(vlc_path).exists():
                        return True
            # Try invoking vlc --version on PATH
            result = subprocess.run(["vlc", "--version"], capture_output=True, timeout=2)
            return result.returncode == 0
        except Exception:
            return False
    
    def _get_vlc_path(self) -> str:
        """Get the best path to a VLC executable for subprocess calls.

        On macOS prefer the application bundle binary. On Windows prefer
        the Program Files paths. Otherwise fall back to 'vlc' (PATH).
        """
        if platform.system() == "Darwin":
            mac_path = Path("/Applications/VLC.app/Contents/MacOS/VLC")
            if mac_path.exists():
                return str(mac_path)
        if platform.system() == "Windows":
            vlc_paths = [
                "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe",
                "C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe",
            ]
            for vlc_path in vlc_paths:
                if Path(vlc_path).exists():
                    return vlc_path
        # Fallback to PATH name
        return "vlc"
    
    def _convert_to_mp3_vlc(self, source_path: Path, target_path: Path) -> bool:
        """
        Convert audio file to MP3 using VLC. Try libVLC (python-vlc) first
        because it's typically more reliable on macOS and avoids spawning a
        subprocess; fall back to calling the VLC CLI executable.
        """
        # Try python-vlc (libVLC) first
        try:
            import vlc
            # Build libvlc instance with dummy interface
            instance = vlc.Instance(['--intf', 'dummy', '--quiet'])
            # Build media with sout chain to transcode audio to MP3
            abs_target = str(target_path.resolve())
            abs_source = str(source_path.resolve())
            sout = f"#transcode{{acodec=mp3,ab=192}}:std{{access=file,mux=dummy,dst={abs_target}}}"
            media = instance.media_new(abs_source, f":sout={sout}")
            player = instance.media_player_new()
            player.set_media(media)
            # play() is asynchronous — use events to wait for end
            playing = player.play()
            # Some libvlc builds return -1/0 — we still need to wait for completion
            # Wait until the file is converted or timeout
            import time
            start = time.time()
            timeout = 300
            # Poll for existence of target file as conversion completes
            while True:
                if target_path.exists() and target_path.stat().st_size > 0:
                    try:
                        player.stop()
                    except Exception:
                        pass
                    return True
                if time.time() - start > timeout:
                    try:
                        player.stop()
                    except Exception:
                        pass
                    print(f"libVLC conversion timed out for {source_path.name}")
                    break
                time.sleep(0.2)
        except Exception as e:
            # Import or runtime error — fall back to CLI
            print(f"libVLC conversion unavailable or failed: {e}")

        # Fallback to CLI VLC
        try:
            vlc_path = self._get_vlc_path()
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
            print(f"Attempting VLC (exec) conversion: {source_path.name} -> {target_path.name} using {vlc_path}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=300,  # 5 minute timeout
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0:
                print(f"VLC conversion successful: {source_path.name}")
                return True
            else:
                print(f"VLC conversion failed for {source_path.name}: return code {result.returncode}")
                if result.stderr:
                    try:
                        error_msg = result.stderr.decode('utf-8', errors='ignore')
                        if error_msg.strip():
                            print(f"VLC stderr: {error_msg[:400]}")
                    except Exception:
                        pass
                if result.stdout:
                    try:
                        stdout_msg = result.stdout.decode('utf-8', errors='ignore')
                        if stdout_msg.strip():
                            print(f"VLC stdout: {stdout_msg[:400]}")
                    except Exception:
                        pass
                return False
        except Exception as e:
            print(f"VLC exec conversion error for {source_path.name}: {e}")
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

    def sync_library_basic(
        self,
        sd_root: Path,
        force_clean: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[int, int]:
        """Sync basic-mode stations to SD card.

        Each station maps to a DFPlayer folder (01-98). Tracks are duplicated
        across folders if they appear in multiple stations. Folder 99 is
        reserved for the AM WAV overlay. No metadata file is written -- the
        firmware discovers stations by querying the DFPlayer directly.
        """
        RESERVED_FOLDER = 99
        stations = self.db.list_basic_stations()
        if not stations:
            if progress_callback:
                progress_callback(1, 1, "No stations to sync")
            self._copy_am_wav_to_dfplayer_sd(sd_root)
            return 0, 0

        vlc_available = self._check_vlc()
        ffmpeg_available = self._check_ffmpeg()
        can_convert = vlc_available or (ffmpeg_available and PYDUB_AVAILABLE)

        # Count total tracks for progress
        station_tracks: List[Tuple[int, List]] = []
        total_tracks = 0
        for station in stations:
            tracks = self.db.list_basic_station_songs(station["id"])
            station_tracks.append((station["folder_number"], tracks))
            total_tracks += len(tracks)

        total_work = total_tracks + 2  # tracks + cleanup + AM WAV
        work_done = 0
        copied = 0
        skipped = 0

        used_folders: set = set()
        for folder_num, tracks in station_tracks:
            used_folders.add(folder_num)
            folder_path = sd_root / f"{folder_num:02d}"
            folder_path.mkdir(parents=True, exist_ok=True)
            valid_track_nums: set = set()

            for track_order, song in enumerate(tracks, start=1):
                valid_track_nums.add(track_order)
                file_path = Path(song["file_path"])
                title = song["title"] or song["original_filename"]
                if progress_callback:
                    progress_callback(work_done, total_work, f"Syncing: {title}")

                if not file_path.exists():
                    print(f"Source file missing, skipping: {file_path}")
                    skipped += 1
                    work_done += 1
                    continue

                target_path = folder_path / f"{track_order:03d}.mp3"
                source_ext = file_path.suffix.lower()

                if not force_clean and target_path.exists():
                    try:
                        target_size = target_path.stat().st_size
                        if source_ext == ".mp3":
                            if target_size == file_path.stat().st_size:
                                skipped += 1
                                work_done += 1
                                continue
                        elif target_size > 1024:
                            skipped += 1
                            work_done += 1
                            continue
                    except OSError:
                        pass

                try:
                    if source_ext == ".mp3":
                        shutil.copy2(file_path, target_path)
                        copied += 1
                    elif can_convert:
                        if self._convert_to_mp3(file_path, target_path):
                            copied += 1
                        else:
                            print(f"Failed to convert {file_path.name}")
                            skipped += 1
                    else:
                        print(f"Cannot convert {file_path.name} (no converter)")
                        skipped += 1
                except OSError as e:
                    print(f"Error syncing {file_path.name}: {e}")
                    skipped += 1
                work_done += 1

            # Remove stale tracks within this folder
            for item in folder_path.iterdir():
                if item.suffix.lower() == ".mp3" and item.stem.isdigit():
                    if int(item.stem) not in valid_track_nums:
                        print(f"Removing stale track: {item}")
                        item.unlink(missing_ok=True)

        # Clean up folders not assigned to any station
        work_done += 1
        if progress_callback:
            progress_callback(work_done, total_work, "Cleaning up...")
        for item in sd_root.iterdir():
            if item.is_dir() and item.name.isdigit():
                folder_num = int(item.name)
                if folder_num != RESERVED_FOLDER and folder_num not in used_folders:
                    print(f"Removing stale folder: {item}")
                    shutil.rmtree(item, ignore_errors=True)

        work_done += 1
        if progress_callback:
            progress_callback(work_done, total_work, "Copying AM radio sound...")
        self._copy_am_wav_to_dfplayer_sd(sd_root)

        # Write feature flags to folder 99
        loop_enabled = self.db.get_setting("basic_loop_stations", "1") == "1"
        self._write_basic_feature_flags(sd_root, loop_stations=loop_enabled)

        if progress_callback:
            progress_callback(total_work, total_work, "Basic sync complete!")
        print(f"Basic SD sync complete: {copied} copied, {skipped} skipped across {len(stations)} stations")
        return copied, skipped

    def sync_library(
        self,
        sd_root: Path,
        audio_target: Optional[str] = None,
        pi_convert_audio: Optional[bool] = None,
        force_clean: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[int, int]:
        """
        Sync library to SD card. Layout and naming depend on audio_target:
        - dfplayer_rp2040: folders 01/, 02/, ... at SD root with 001.mp3, 002.mp3 inside;
          VintageRadio/ only for AM WAV, state, metadata. All tracks converted to MP3.
        - raspberry_pi: flat VintageRadio/library/ with original-style filenames;
          if pi_convert_audio convert non-MP3 to MP3, else copy as-is.
        
        Args:
            force_clean: If True, re-sync all files even if they already exist and match.
            progress_callback: Optional callback(current, total, message) for progress updates.
        """
        target = audio_target or "dfplayer_rp2040"
        pi_convert = pi_convert_audio if pi_convert_audio is not None else True
        if target == "dfplayer_rp2040":
            return self._sync_library_dfplayer(sd_root, force_clean=force_clean, progress_callback=progress_callback)
        return self._sync_library_pi(sd_root, convert_to_mp3=pi_convert, force_clean=force_clean, progress_callback=progress_callback)

    def _sync_library_dfplayer(self, sd_root: Path, force_clean: bool = False,
                               progress_callback: Optional[callable] = None) -> Tuple[int, int]:
        """DFPlayer layout – **deduplicated**.

        Each unique song is written to the SD card exactly once, spread across
        numbered folders ``01/``, ``02/``, ... (max 255 tracks per folder, the
        DFPlayer track-number limit).  The mapping ``song_id -> (folder, track)``
        is stored in the ``sd_mapping`` database table and embedded in the
        ``radio_metadata.json`` so the firmware can look up the real location of
        any track regardless of which album/playlist it belongs to.

        Folder 99 is reserved for the AM radio WAV file.

        Args:
            force_clean: If True, re-sync all files even if they already exist.
            progress_callback: Optional callback(current, total, message).
        """
        vintage_root = self.vintage_root(sd_root)
        vintage_root.mkdir(parents=True, exist_ok=True)
        vlc_available = self._check_vlc()
        ffmpeg_available = self._check_ffmpeg()
        if vlc_available:
            print(f"VLC available for conversion: {self._get_vlc_path()}")
        if ffmpeg_available and PYDUB_AVAILABLE:
            print("ffmpeg/pydub available for conversion")
        if not vlc_available and not (ffmpeg_available and PYDUB_AVAILABLE):
            print("Warning: No conversion tools available (VLC or ffmpeg/pydub)")

        # ── Collect every unique song referenced by any album or playlist ──
        all_songs = self.db.list_songs()
        # Build a lookup so we can get full row by ID
        song_by_id: Dict[int, any] = {s["id"]: s for s in all_songs}

        # Gather the set of song IDs actually used in albums/playlists
        used_song_ids: List[int] = []
        seen_ids: set = set()
        albums = self.db.list_albums()
        playlists = self.db.list_playlists()
        for album in albums:
            for track in self.db.list_album_songs(album["id"]):
                if track["id"] not in seen_ids:
                    used_song_ids.append(track["id"])
                    seen_ids.add(track["id"])
        for playlist in playlists:
            for track in self.db.list_playlist_songs(playlist["id"]):
                if track["id"] not in seen_ids:
                    used_song_ids.append(track["id"])
                    seen_ids.add(track["id"])

        if not used_song_ids:
            print("No songs to sync (no albums or playlists)")
            if progress_callback:
                progress_callback(1, 1, "Nothing to sync")
            self._copy_am_wav_to_dfplayer_sd(sd_root)
            self._write_metadata(vintage_root)
            return 0, 0

        # ── Assign each song a (folder, track_number) slot in library order ──
        # Every resync (normal or clean) assigns slots in the same order as albums/playlists
        # so that metadata and SD card layout always match.
        # Many DFPlayer clones struggle with large directories (>15-20 files per
        # folder), causing playback failures for higher-numbered tracks.  Spreading
        # songs across folders avoids this.  15 tracks/folder × 98 folders = 1,470
        # max tracks — more than the 255 per single folder the datasheet allows.
        MAX_TRACKS_PER_FOLDER = 100
        RESERVED_FOLDER = 99  # AM WAV

        song_slot: Dict[int, Tuple[int, int]] = {}  # song_id -> (folder, track)
        next_folder = 1
        next_track = 1

        for sid in used_song_ids:
            if next_folder == RESERVED_FOLDER:
                next_folder += 1
                next_track = 1
            song_slot[sid] = (next_folder, next_track)
            next_track += 1
            if next_track > MAX_TRACKS_PER_FOLDER:
                next_folder += 1
                next_track = 1

        # ── Phase 1: Scan songs and identify what needs to be copied ──
        from concurrent.futures import ThreadPoolExecutor, as_completed
        can_convert = vlc_available or (ffmpeg_available and PYDUB_AVAILABLE)
        copied = 0
        skipped = 0
        pending_tasks = []
        scan_total = len(used_song_ids)

        for i, sid in enumerate(used_song_ids):
            song = song_by_id.get(sid)
            if not song:
                skipped += 1
                continue
            file_path = Path(song["file_path"])
            if not file_path.exists():
                print(f"Source file missing, skipping: {file_path}")
                # On clean sync, clear this slot on SD so old files don't persist
                if force_clean and sid in song_slot:
                    folder_num, track_num = song_slot[sid]
                    folder_path = sd_root / f"{folder_num:02d}"
                    target_path = folder_path / f"{track_num:03d}.mp3"
                    if target_path.exists():
                        try:
                            target_path.unlink(missing_ok=True)
                            print(f"Removed stale slot (no source): {target_path}")
                        except OSError:
                            pass
                    try:
                        self.db.update_song_sd_path(sid, "")
                    except Exception:
                        pass
                skipped += 1
                continue

            folder_num, track_num = song_slot[sid]
            folder_path = sd_root / f"{folder_num:02d}"
            folder_path.mkdir(parents=True, exist_ok=True)
            target_path = folder_path / f"{track_num:03d}.mp3"

            title = song["title"] or song["original_filename"]
            if progress_callback:
                progress_callback(i, scan_total, f"Checking: {title}")

            # Skip check (fast size comparison)
            if not force_clean and target_path.exists():
                try:
                    target_size = target_path.stat().st_size
                    source_ext = file_path.suffix.lower()
                    already_matches = False
                    if source_ext == ".mp3":
                        source_size = file_path.stat().st_size
                        already_matches = (target_size == source_size)
                    else:
                        already_matches = (target_size > 1024)

                    if already_matches:
                        # Update mapping in DB
                        self.db.set_sd_mapping(sid, folder_num, track_num)
                        existing_sd = self._row_get(song, "sd_path")
                        target_str = str(target_path)
                        if existing_sd != target_str:
                            self.db.update_song_sd_path(sid, target_str)
                        skipped += 1
                        continue
                except (OSError, Exception):
                    pass

            source_ext = file_path.suffix.lower()
            action = "copy" if source_ext == ".mp3" else "convert"
            pending_tasks.append((sid, file_path, target_path, folder_num, track_num, action, title))

        # ── Phase 2: Copy/convert files + cleanup + AM WAV + metadata ──
        # Now we know how many files actually need syncing, so progress is accurate.
        total_work = len(pending_tasks) + 3  # files + cleanup + AM WAV + metadata
        work_done = 0

        def _process_one(task):
            sid, file_path, target_path, folder_num, track_num, action, title = task
            try:
                if action == "copy":
                    shutil.copy2(file_path, target_path)
                    return ("ok", sid, str(target_path), folder_num, track_num, title)
                else:
                    if self._convert_to_mp3(file_path, target_path):
                        return ("ok", sid, str(target_path), folder_num, track_num, title)
                    else:
                        if not can_convert:
                            print(f"Cannot convert {file_path.name} (no converter), skipping")
                        else:
                            print(f"Failed to convert {file_path.name}, skipping")
                        return ("skip", sid, None, folder_num, track_num, title)
            except OSError as e:
                print(f"Error syncing {file_path.name}: {e}")
                return ("skip", sid, None, folder_num, track_num, title)

        if pending_tasks:
            if progress_callback:
                progress_callback(0, total_work, f"Syncing {len(pending_tasks)} files to SD card...")
            mappings_batch: List[tuple] = []
            sd_paths_batch: List[tuple] = []
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(_process_one, t): t for t in pending_tasks}
                for future in as_completed(futures):
                    status, sid, sd_path, folder_num, track_num, title = future.result()
                    if status == "ok":
                        mappings_batch.append((sid, folder_num, track_num))
                        sd_paths_batch.append((sid, sd_path if sd_path is not None else ""))
                        copied += 1
                    else:
                        skipped += 1
                    work_done += 1
                    if progress_callback:
                        progress_callback(work_done, total_work, f"Synced: {title}")
            if mappings_batch:
                self.db.set_sd_mappings_batch(mappings_batch)
            if sd_paths_batch:
                self.db.update_song_sd_paths_batch(sd_paths_batch)
        else:
            if progress_callback:
                progress_callback(0, total_work, "All files already up to date")

        # ── Clean up stale folders (folders with no assigned songs) ──
        work_done += 1
        if progress_callback:
            progress_callback(work_done, total_work, "Cleaning up stale files...")
        used_folders = {f for f, _ in song_slot.values()}
        for item in sd_root.iterdir():
            if item.is_dir() and item.name.isdigit():
                folder_num = int(item.name)
                if folder_num != RESERVED_FOLDER and folder_num not in used_folders:
                    print(f"Removing stale folder: {item}")
                    shutil.rmtree(item, ignore_errors=True)

        # Also remove stale files within used folders (track numbers no longer needed)
        folder_tracks: Dict[int, set] = {}
        for f, t in song_slot.values():
            folder_tracks.setdefault(f, set()).add(t)
        for folder_num, valid_tracks in folder_tracks.items():
            folder_path = sd_root / f"{folder_num:02d}"
            if not folder_path.exists():
                continue
            for f in folder_path.iterdir():
                if f.suffix.lower() == ".mp3" and f.stem.isdigit():
                    track_num = int(f.stem)
                    if track_num not in valid_tracks:
                        print(f"Removing stale track: {f}")
                        f.unlink(missing_ok=True)

        # ── AM WAV and metadata ──
        work_done += 1
        if progress_callback:
            progress_callback(work_done, total_work, "Copying AM radio sound...")
        self._copy_am_wav_to_dfplayer_sd(sd_root)

        work_done += 1
        if progress_callback:
            progress_callback(work_done, total_work, "Writing metadata...")
        self._write_metadata(vintage_root)

        if progress_callback:
            progress_callback(total_work, total_work, "Sync complete!")

        print(f"SD sync complete: {copied} copied, {skipped} skipped, {len(used_song_ids)} unique songs")
        if copied == 0 and skipped > 0:
            print("No files were copied (all sources missing?). Re-import in Library or fix file paths, then sync again.")
        return copied, skipped

    def _write_basic_feature_flags(self, sd_root: Path, loop_stations: bool = True) -> None:
        """Write/remove feature flag files in folder 99.

        Folder 99 layout:
          001.wav - AM radio sound (always present)
          002.mp3 - Loop stations flag (present = loop enabled)

        The firmware queries folder 99 file count (0x4E) to detect flags.
        """
        flag_path = sd_root / "99" / "002.mp3"
        if loop_stations:
            if not flag_path.exists():
                flag_path.parent.mkdir(parents=True, exist_ok=True)
                # Write a minimal valid MP3 frame (silent, ~0.1s)
                # MPEG1 Layer3, 128kbps, 44100Hz, stereo, padding
                flag_path.write_bytes(
                    b'\xff\xfb\x90\x00' + b'\x00' * 413
                )
                print(f"Feature flag written: {flag_path} (loop_stations=True)")
        else:
            if flag_path.exists():
                flag_path.unlink()
                print(f"Feature flag removed: {flag_path} (loop_stations=False)")

    def _copy_am_wav_to_dfplayer_sd(self, sd_root: Path) -> bool:
        """Copy AMradioSound.wav to folder 99/001.wav on the DFPlayer SD card.
        
        The DFPlayer can play WAV files natively (16-bit PCM). By placing the AM
        static sound on the SD card, the DFPlayer itself plays the sound through
        its speaker output instead of the Pico trying to play it via PWM on GPIO.
        
        Returns True if the file was successfully copied.
        """
        source = resource_path("AMradioSound.wav")
        folder_path = sd_root / "99"
        folder_path.mkdir(parents=True, exist_ok=True)
        target_path = folder_path / "001.wav"
        
        if not source.exists():
            print(f"Warning: AM WAV source not found: {source}")
            return False
        
        # Check if already exists and matches
        if target_path.exists():
            try:
                source_size = source.stat().st_size
                target_size = target_path.stat().st_size
                if source_size == target_size:
                    print(f"AM WAV already on SD card: {target_path} (size matches)")
                    return True
            except OSError:
                pass
        
        try:
            # Validate and optionally convert for DFPlayer compatibility
            import wave
            needs_conversion = False
            try:
                with wave.open(str(source), 'rb') as wav_in:
                    channels = wav_in.getnchannels()
                    sample_width = wav_in.getsampwidth()
                    framerate = wav_in.getframerate()
                    comptype = wav_in.getcomptype()
                    print(f"AM WAV format: {sample_width*8}-bit, {channels} ch, {framerate} Hz, {comptype}")
                    # DFPlayer prefers: 16-bit, mono, PCM
                    if sample_width != 2 or channels != 1 or comptype != 'NONE':
                        needs_conversion = True
                        print("Converting to 16-bit PCM mono for DFPlayer compatibility...")
            except Exception as e:
                print(f"Could not read WAV format: {e}, copying as-is")
            
            if needs_conversion and PYDUB_AVAILABLE:
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_wav(str(source))
                    if audio.channels != 1:
                        audio = audio.set_channels(1)
                    audio = audio.set_sample_width(2)  # 16-bit
                    audio.export(str(target_path), format="wav",
                                 parameters=["-acodec", "pcm_s16le"])
                    print(f"AM WAV converted and copied to SD: {target_path}")
                    return True
                except Exception as e:
                    print(f"Conversion failed: {e}, copying original")
            
            shutil.copy2(source, target_path)
            print(f"AM WAV copied to SD: {target_path}")
            return True
            
        except OSError as e:
            print(f"Error copying AM WAV to SD: {e}")
            return False

    @staticmethod
    def _row_get(row, key, default=None):
        """Safe .get()-like access for sqlite3.Row or dict objects."""
        try:
            val = row[key]
            return val if val is not None else default
        except (KeyError, IndexError):
            return default

    def _write_folder_tracks_dfplayer(
        self,
        sd_root: Path,
        folder_index: int,
        tracks: List[Dict],
        vlc_available: bool,
        ffmpeg_available: bool,
        force_clean: bool = False,
        max_workers: int = 4,
    ) -> Tuple[int, int]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        folder_path = sd_root / f"{folder_index:02d}"
        folder_path.mkdir(parents=True, exist_ok=True)
        copied = 0
        skipped = 0

        # ── Phase 1: classify each track as skip / copy / convert ──
        pending_tasks = []  # (track_num, song_id, file_path, target_path, action)

        for track_num, song in enumerate(tracks, start=1):
            file_path = Path(song["file_path"])
            if not file_path.exists():
                skipped += 1
                continue
            target_path = folder_path / f"{track_num:03d}.mp3"

            # Check if file already exists and matches (skip if not force_clean)
            # Uses fast size comparison only — no hashing (reading entire files
            # from an SD card for SHA-256 is extremely slow).
            if not force_clean and target_path.exists():
                try:
                    target_size = target_path.stat().st_size
                    source_ext = file_path.suffix.lower()
                    already_matches = False
                    if source_ext == ".mp3":
                        # MP3 source -> target is a direct copy, sizes must match
                        source_size = file_path.stat().st_size
                        already_matches = (target_size == source_size)
                    else:
                        # Non-MP3 source -> target is a conversion; verify it exists
                        # with a reasonable size (> 1KB means it was converted)
                        already_matches = (target_size > 1024)

                    if already_matches:
                        # Only update DB if the path actually changed
                        existing_sd = self._row_get(song, "sd_path")
                        target_str = str(target_path)
                        if existing_sd != target_str:
                            self.db.update_song_sd_path(song["id"], target_str)
                        skipped += 1
                        continue
                except (OSError, Exception):
                    pass

            source_ext = file_path.suffix.lower()
            action = "copy" if source_ext == ".mp3" else "convert"
            pending_tasks.append((track_num, song["id"], file_path, target_path, action))

        if not pending_tasks:
            return copied, skipped

        # ── Phase 2: process copy/convert tasks in parallel ──
        can_convert = vlc_available or (ffmpeg_available and PYDUB_AVAILABLE)

        def _process_one(task):
            """Worker: runs in thread pool. Returns (status, song_id, sd_path)."""
            _track_num, song_id, file_path, target_path, action = task
            try:
                if action == "copy":
                    shutil.copy2(file_path, target_path)
                    return ("ok", song_id, str(target_path))
                else:  # convert
                    if self._convert_to_mp3(file_path, target_path):
                        return ("ok", song_id, str(target_path))
                    else:
                        if not can_convert:
                            print(f"Cannot convert {file_path.name} (no converter available), skipping")
                        else:
                            print(f"Failed to convert {file_path.name}, skipping")
                        return ("skip", song_id, None)
            except OSError as e:
                print(f"Error syncing {file_path.name}: {e}")
                return ("skip", song_id, None)

        print(f"  Processing {len(pending_tasks)} track(s) with up to {max_workers} workers...")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_process_one, t): t for t in pending_tasks}
            for future in as_completed(futures):
                try:
                    status, song_id, sd_path = future.result()
                    if status == "ok":
                        self.db.update_song_sd_path(song_id, sd_path)
                        copied += 1
                    else:
                        skipped += 1
                except Exception as e:
                    print(f"  Unexpected error in worker: {e}")
                    skipped += 1

        return copied, skipped

    def _sync_library_pi(self, sd_root: Path, convert_to_mp3: bool, force_clean: bool = False,
                          progress_callback: Optional[callable] = None) -> Tuple[int, int]:
        """Pi layout: VintageRadio/library/ with original-style filenames; convert or copy per convert_to_mp3."""
        vintage_root = self.vintage_root(sd_root)
        vintage_root.mkdir(parents=True, exist_ok=True)
        library_root = self.library_root(sd_root)
        library_root.mkdir(parents=True, exist_ok=True)
        # For Pi, copy AM WAV to SD card (Pi can access SD card directly)
        self._ensure_am_wav(vintage_root)
        vlc_available = self._check_vlc()
        ffmpeg_available = self._check_ffmpeg()
        if convert_to_mp3 and not vlc_available and not (ffmpeg_available and PYDUB_AVAILABLE):
            print("Warning: No conversion tools available (VLC or ffmpeg/pydub)")
        copied = 0
        skipped = 0
        all_songs = self.db.list_songs()
        total_steps = len(all_songs) + 1  # +1 for metadata
        for i, song in enumerate(all_songs):
            title = song["title"] or song["original_filename"] or "Unknown"
            if progress_callback:
                progress_callback(i, total_steps, f"Syncing: {title}")
            file_path = Path(song["file_path"])
            if not file_path.exists():
                skipped += 1
                continue
            source_ext = file_path.suffix.lower()
            if convert_to_mp3:
                target_filename = file_path.stem + ".mp3"
            else:
                target_filename = file_path.name
            # Check if file already exists and matches (skip if not force_clean)
            existing_sd = song["sd_path"]
            if not force_clean and existing_sd:
                existing_path = Path(existing_sd)
                if existing_path.exists():
                    try:
                        existing_size = existing_path.stat().st_size
                        if existing_size > 0:
                            # Fast check: if source is MP3 (direct copy), compare sizes
                            # For converted files, just check target exists with content
                            if source_ext == ".mp3":
                                source_size = file_path.stat().st_size
                                if existing_size == source_size:
                                    skipped += 1
                                    continue
                            else:
                                # Converted file — exists with content, assume valid
                                skipped += 1
                                continue
                    except (OSError, Exception):
                        # Error checking existing file - proceed with copy
                        pass
            target_path = self._unique_path(library_root, target_filename)
            try:
                if convert_to_mp3:
                    if source_ext == ".mp3":
                        shutil.copy2(file_path, target_path)
                    else:
                        if not self._convert_to_mp3(file_path, target_path):
                            skipped += 1
                            continue
                else:
                    shutil.copy2(file_path, target_path)
                self.db.update_song_sd_path(song["id"], str(target_path))
                copied += 1
            except OSError as e:
                print(f"Error syncing {file_path.name}: {e}")
                skipped += 1
        if progress_callback:
            progress_callback(total_steps - 1, total_steps, "Writing metadata...")
        self._write_metadata(vintage_root)
        if progress_callback:
            progress_callback(total_steps, total_steps, "Sync complete!")
        return copied, skipped

    def validate_sd(self) -> Dict[str, List[Dict[str, str]]]:
        results: Dict[str, List[Dict[str, str]]] = {
            "source_file_missing": [],
            "missing_sd_path": [],
            "missing_file": [],
            "size_mismatch": [],
            "hash_mismatch": [],
        }
        songs = self.db.list_songs()
        for song in songs:
            # Check source file first (library paths from another PC often break)
            file_path = song["file_path"]
            if file_path and not Path(file_path).exists():
                results["source_file_missing"].append(
                    {"id": str(song["id"]), "title": song["title"] or "", "path": file_path}
                )
                continue
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

    def export_album(
        self,
        album_id: int,
        sd_root: Path,
        audio_target: Optional[str] = None,
        pi_convert_audio: Optional[bool] = None,
    ) -> Optional[Path]:
        album = self.db.get_album_by_id(album_id)
        if album is None:
            return None
        album = dict(album)
        target = audio_target or "dfplayer_rp2040"
        pi_convert = pi_convert_audio if pi_convert_audio is not None else True
        tracks = self.db.list_album_songs(album_id)
        if target == "dfplayer_rp2040":
            folder = sd_root / "01"
            folder.mkdir(parents=True, exist_ok=True)
            return self._export_collection_dfplayer(
                folder, tracks, "album", album_id, album["name"], album.get("description") or ""
            )
        vintage_root = self.vintage_root(sd_root)
        vintage_root.mkdir(parents=True, exist_ok=True)
        folder = vintage_root / f"{album['name']}_album"
        folder.mkdir(parents=True, exist_ok=True)
        return self._export_collection_pi(
            folder, tracks, "album", album_id, album["name"], album.get("description") or "",
            convert_to_mp3=pi_convert,
        )

    def export_playlist(
        self,
        playlist_id: int,
        sd_root: Path,
        audio_target: Optional[str] = None,
        pi_convert_audio: Optional[bool] = None,
    ) -> Optional[Path]:
        playlist = self.db.get_playlist_by_id(playlist_id)
        if playlist is None:
            return None
        playlist = dict(playlist)
        target = audio_target or "dfplayer_rp2040"
        pi_convert = pi_convert_audio if pi_convert_audio is not None else True
        tracks = self.db.list_playlist_songs(playlist_id)
        if target == "dfplayer_rp2040":
            folder = sd_root / "02"
            folder.mkdir(parents=True, exist_ok=True)
            return self._export_collection_dfplayer(
                folder, tracks, "playlist", playlist_id, playlist["name"],
                playlist.get("description") or "",
            )
        vintage_root = self.vintage_root(sd_root)
        vintage_root.mkdir(parents=True, exist_ok=True)
        folder = vintage_root / f"{playlist['name']}_playlist"
        folder.mkdir(parents=True, exist_ok=True)
        return self._export_collection_pi(
            folder, tracks, "playlist", playlist_id, playlist["name"],
            playlist.get("description") or "",
            convert_to_mp3=pi_convert,
        )

    def _export_collection_dfplayer(
        self,
        folder: Path,
        tracks: List[Dict],
        col_type: str,
        col_id: int,
        name: str,
        description: str,
    ) -> Path:
        metadata = {"type": col_type, "id": col_id, "name": name, "description": description, "tracks": []}
        for index, song in enumerate(tracks, start=1):
            source = Path(song["file_path"])
            if not source.exists():
                continue
            target_path = folder / f"{index:03d}.mp3"
            if source.suffix.lower() == ".mp3":
                shutil.copy2(source, target_path)
            else:
                self._convert_to_mp3(source, target_path)
            metadata["tracks"].append(
                {"order": index, "filename": target_path.name, "title": song["title"], "artist": song["artist"]}
            )
        with (folder / "metadata.json").open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
        return folder

    def _export_collection_pi(
        self,
        folder: Path,
        tracks: List[Dict],
        col_type: str,
        col_id: int,
        name: str,
        description: str,
        *,
        convert_to_mp3: bool,
    ) -> Path:
        metadata = {"type": col_type, "id": col_id, "name": name, "description": description, "tracks": []}
        for index, song in enumerate(tracks, start=1):
            source = Path(song["file_path"])
            if not source.exists():
                continue
            if convert_to_mp3:
                target = folder / (source.stem + ".mp3")
                if source.suffix.lower() == ".mp3":
                    shutil.copy2(source, target)
                else:
                    self._convert_to_mp3(source, target)
            else:
                target = folder / source.name
                shutil.copy2(source, target)
            metadata["tracks"].append(
                {"order": index, "filename": target.name, "title": song["title"], "artist": song["artist"]}
            )
        with (folder / "metadata.json").open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
        return folder

    def import_from_sd(
        self,
        sd_root: Path,
        dest_dir: Optional[Path] = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, int]:
        """Import albums and playlists from an SD card.

        Reads ``radio_metadata.json`` from the ``VintageRadio/`` directory to
        reconstruct albums and playlists.  Audio files are resolved from their
        DFPlayer folder/track paths (e.g. ``01/044.mp3``).  Songs that already
        exist in the library (matched by hash+size) are reused; new files are
        copied to ``dest_dir`` (if provided) and added to the library with the
        copied file path.  If ``dest_dir`` is None, files are added with the SD
        path as their source (legacy behavior).
        """
        imported_albums = 0
        imported_playlists = 0
        imported_songs = 0
        vintage_root = self.vintage_root(sd_root)

        metadata_path = vintage_root / "radio_metadata.json"
        if not metadata_path.exists():
            # Fall back to legacy folder-based import (doesn't support dest_dir)
            return self._import_from_sd_legacy(sd_root)

        if progress_callback:
            progress_callback(0, 0, "Reading metadata from SD card...")

        try:
            with metadata_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Failed to read radio_metadata.json: {e}")
            return {"albums": 0, "playlists": 0, "songs": 0}

        songs_meta = data.get("songs", {})
        albums_data = data.get("albums", [])
        playlists_data = data.get("playlists", [])

        # Total steps: songs + albums + playlists + 1 (finalizing)
        total_steps = len(songs_meta) + len(albums_data) + len(playlists_data) + 1
        current_step = 0

        # Build a map: song_id (from metadata) -> local song_id (in our DB)
        meta_to_local: Dict[str, int] = {}

        for meta_song_id, song_info in songs_meta.items():
            folder = song_info.get("folder")
            track = song_info.get("track")
            song_title = song_info.get("title", f"Song {meta_song_id}")

            if progress_callback:
                progress_callback(current_step, total_steps, f"Scanning: {song_title}")

            if folder is None or track is None:
                current_step += 1
                continue

            # Resolve file on SD card
            sd_file = sd_root / f"{folder:02d}" / f"{track:03d}.mp3"
            if not sd_file.exists():
                print(f"SD file not found for song {meta_song_id}: {sd_file}")
                current_step += 1
                continue

            # Check if already in library (by hash+size)
            file_hash = compute_file_hash(sd_file)
            file_size = sd_file.stat().st_size
            existing = self.db.get_song_by_hash_size(file_hash, file_size)

            if existing:
                meta_to_local[meta_song_id] = int(existing["id"])
                current_step += 1
            else:
                # Copy file to destination directory if provided
                if dest_dir:
                    if progress_callback:
                        progress_callback(current_step, total_steps, f"Copying: {song_title}")
                    # Create destination directory if it doesn't exist
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    # Copy file to destination, preserving filename
                    dest_file = dest_dir / sd_file.name
                    # If file already exists at destination, use a unique name
                    if dest_file.exists():
                        counter = 1
                        stem = dest_file.stem
                        suffix = dest_file.suffix
                        while dest_file.exists():
                            dest_file = dest_dir / f"{stem}_{counter}{suffix}"
                            counter += 1
                    try:
                        shutil.copy2(sd_file, dest_file)
                        file_path = str(dest_file)
                    except OSError as e:
                        print(f"Failed to copy {sd_file.name} to {dest_dir}: {e}")
                        # Fall back to using SD path if copy fails
                        file_path = str(sd_file)
                else:
                    # No destination directory - use SD path (legacy behavior)
                    file_path = str(sd_file)

                # Import as new song
                metadata = extract_metadata(sd_file)  # Extract from source file
                # Prefer title/artist from radio_metadata.json over file tags
                title = song_info.get("title") or metadata["title"]
                artist = song_info.get("artist") or metadata["artist"]
                duration = song_info.get("duration") or metadata["duration"]

                song_id = self.db.add_song(
                    original_filename=sd_file.name,
                    file_path=file_path,  # Use copied file path if dest_dir provided
                    title=title,
                    artist=artist,
                    duration=duration,
                    file_hash=file_hash,
                    file_size=file_size,
                    format=metadata["format"],
                    sd_path=str(sd_file),  # Keep SD path for reference
                )
                meta_to_local[meta_song_id] = song_id
                # Store the DFPlayer mapping
                self.db.set_sd_mapping(song_id, folder, track)
                imported_songs += 1
            
            current_step += 1

        # Import albums
        for album_data in albums_data:
            album_name = album_data.get("name", "Unknown Album")
            if progress_callback:
                progress_callback(current_step, total_steps, f"Importing album: {album_name}")
            current_step += 1

            album_id = self.db.create_album(album_name)
            has_tracks = False
            for idx, track_entry in enumerate(album_data.get("tracks", []), start=1):
                meta_sid = str(track_entry.get("song_id", ""))
                local_sid = meta_to_local.get(meta_sid)
                if local_sid is not None:
                    self.db.add_song_to_album(album_id, local_sid, idx)
                    has_tracks = True
            if has_tracks:
                imported_albums += 1
                print(f"Imported album: '{album_name}' ({len(album_data.get('tracks', []))} tracks)")

        # Import playlists
        for playlist_data in playlists_data:
            playlist_name = playlist_data.get("name", "Unknown Playlist")
            if progress_callback:
                progress_callback(current_step, total_steps, f"Importing playlist: {playlist_name}")
            current_step += 1

            playlist_id = self.db.create_playlist(playlist_name)
            has_tracks = False
            for idx, track_entry in enumerate(playlist_data.get("tracks", []), start=1):
                meta_sid = str(track_entry.get("song_id", ""))
                local_sid = meta_to_local.get(meta_sid)
                if local_sid is not None:
                    self.db.add_song_to_playlist(playlist_id, local_sid, idx)
                    has_tracks = True
            if has_tracks:
                imported_playlists += 1
                print(f"Imported playlist: '{playlist_name}' ({len(playlist_data.get('tracks', []))} tracks)")

        if progress_callback:
            progress_callback(total_steps, total_steps, "Import complete!")

        print(f"Import from SD complete: {imported_albums} albums, "
              f"{imported_playlists} playlists, {imported_songs} new songs")
        return {"albums": imported_albums, "playlists": imported_playlists, "songs": imported_songs}

    def _import_from_sd_legacy(self, sd_root: Path) -> Dict[str, int]:
        """Legacy import: looks for *_album and *_playlist folders in VintageRadio/."""
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
        """Write ``radio_metadata.json`` with deduplicated SD layout.

        Each track entry in an album/playlist includes the **actual** DFPlayer
        folder and track number (from ``sd_mapping``) so the firmware can call
        ``playFolder(folder, track)`` directly.  Albums and playlists are purely
        logical groupings -- they no longer correspond to physical folders.

        The file is kept compact so MicroPython on the Pico can parse it
        within its limited RAM (~256 KB).  Only fields the firmware actually
        needs are included (title, artist, duration, folder, track).
        """
        metadata: Dict = {
            "albums": [],
            "playlists": [],
            "songs": {},
            "am_sound": {
                "folder": 99,
                "track": 1,
            },
        }

        # Build a quick lookup: song_id -> (folder, track)
        sd_map: Dict[int, Tuple[int, int]] = {}
        for song in self.db.list_songs():
            mapping = self.db.get_sd_mapping(song["id"])
            if mapping:
                sd_map[song["id"]] = (mapping["folder_number"], mapping["track_number"])

        # ── Albums ──
        for album in self.db.list_albums():
            tracks = self.db.list_album_songs(album["id"])
            track_list = []
            for idx, song in enumerate(tracks):
                folder, track_num = sd_map.get(song["id"], (1, idx + 1))
                track_list.append({
                    "song_id": song["id"],
                    "folder": folder,
                    "track": track_num,
                })
            metadata["albums"].append({
                "id": album["id"],
                "name": album["name"],
                "tracks": track_list,
            })

        # ── Playlists ──
        for playlist in self.db.list_playlists():
            tracks = self.db.list_playlist_songs(playlist["id"])
            track_list = []
            for idx, song in enumerate(tracks):
                folder, track_num = sd_map.get(song["id"], (1, idx + 1))
                track_list.append({
                    "song_id": song["id"],
                    "folder": folder,
                    "track": track_num,
                })
            metadata["playlists"].append({
                "id": playlist["id"],
                "name": playlist["name"],
                "tracks": track_list,
            })

        # ── Song details (compact: only fields the firmware needs) ──
        # Includes sd_path for Pi hardware file resolution.
        # Excludes hash and original_file (not used by firmware).
        for song in self.db.list_songs():
            entry: Dict = {
                "title": song["title"],
                "artist": song["artist"],
                "duration": song["duration"],
                "sd_path": song["sd_path"] or "",
            }
            mapping = sd_map.get(song["id"])
            if mapping:
                entry["folder"] = mapping[0]
                entry["track"] = mapping[1]
            metadata["songs"][str(song["id"])] = entry

        metadata_path = vintage_root / "radio_metadata.json"
        try:
            # Write compact JSON (no indent) to minimize file size for MicroPython
            with metadata_path.open("w", encoding="utf-8") as handle:
                json.dump(metadata, handle, separators=(",", ":"))
            file_size = metadata_path.stat().st_size
            print(f"Metadata written: {len(metadata['albums'])} albums, "
                  f"{len(metadata['playlists'])} playlists, "
                  f"{len(metadata['songs'])} songs ({file_size:,} bytes)")
        except OSError as e:
            print(f"Error writing metadata: {e}")

    def _ensure_am_wav(self, vintage_root: Path) -> None:
        """Ensure AM WAV file is copied to SD card in DFPlayer-compatible format.
        
        DFPlayer Mini supports WAV files in PCM format. The file is validated and
        converted to 16-bit PCM mono if needed for maximum compatibility.
        """
        source = resource_path("AMradioSound.wav")
        target = vintage_root / "AMradioSound.wav"
        
        if not source.exists():
            print(f"Warning: AM WAV source not found: {source}")
            return
        
        # Ensure VintageRadio directory exists
        vintage_root.mkdir(parents=True, exist_ok=True)
        
        try:
            # Check if we need to convert the WAV file for DFPlayer compatibility
            # DFPlayer works best with 16-bit PCM WAV files
            import wave
            needs_conversion = False
            
            try:
                with wave.open(str(source), 'rb') as wav_in:
                    channels = wav_in.getnchannels()
                    sample_width = wav_in.getsampwidth()
                    framerate = wav_in.getframerate()
                    comptype = wav_in.getcomptype()
                    
                    # Check if format needs conversion
                    # DFPlayer prefers: 16-bit (2 bytes), mono, uncompressed PCM
                    if sample_width != 2 or channels != 1 or comptype != 'NONE':
                        needs_conversion = True
                        print(f"AM WAV format: {sample_width*8}-bit, {channels} channel(s), {framerate} Hz, {comptype}")
                        print("Converting to 16-bit PCM mono for DFPlayer compatibility...")
            except Exception as e:
                print(f"Could not read WAV file format: {e}, copying as-is")
                needs_conversion = False
            
            if needs_conversion and PYDUB_AVAILABLE:
                # Convert to 16-bit PCM mono using pydub
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_wav(str(source))
                    # Ensure mono and 16-bit
                    if audio.channels != 1:
                        audio = audio.set_channels(1)
                    # Export as 16-bit PCM WAV
                    audio.export(str(target), format="wav", parameters=["-acodec", "pcm_s16le"])
                    print(f"AM WAV converted and copied to: {target}")
                except Exception as e:
                    print(f"Conversion failed: {e}, copying original file")
                    shutil.copy2(source, target)
                    print(f"AM WAV copied to: {target} (original format)")
            else:
                # Copy as-is (format is already compatible or conversion not available)
                shutil.copy2(source, target)
                if not needs_conversion:
                    print(f"AM WAV copied to: {target} (format already compatible)")
                else:
                    print(f"AM WAV copied to: {target} (conversion not available, may need manual conversion)")
        except OSError as e:
            print(f"Error copying AM WAV to {target}: {e}")
        except Exception as e:
            print(f"Unexpected error processing AM WAV: {e}")
            # Fallback: try to copy as-is
            try:
                shutil.copy2(source, target)
                print(f"AM WAV copied to: {target} (fallback)")
            except Exception as e2:
                print(f"Failed to copy AM WAV: {e2}")

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

