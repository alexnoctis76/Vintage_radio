"""SD card management utilities."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import platform
import time
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

# Manifest file written at the SD root during sync so we can reliably detect
# content mismatches even when two different libraries share folder structure.
_SYNC_MANIFEST_NAME = ".sync_manifest.json"

# macOS / Windows create these at the volume root when the card is mounted or
# browsed in Finder/Explorer. We never strip our sync manifest (a file, not
# in this set). Removing these keeps the card cleaner and avoids extra root
# clutter; 0x4E is still mostly about junk inside ``01/``, ``02/``, etc.
_SD_ROOT_SERVICE_DIRS = frozenset({
    ".Spotlight-V100",
    ".fseventsd",
    ".Trashes",
    ".TemporaryItems",
    "System Volume Information",
})


def _remove_sd_root_service_dirs(root: Path) -> int:
    """Delete known OS index / trash folders at *root* only. Returns removal count."""
    removed = 0
    for dirname in _SD_ROOT_SERVICE_DIRS:
        p = root / dirname
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
            elif p.is_file():
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    return removed


def _copy2_with_fallback(src: Path, dest: Path) -> None:
    """Copy *src* to *dest* preserving timestamps when possible.

    On macOS, FAT32/exFAT volumes reject extended-attribute writes with EINVAL.
    Fall back to a data-only copy in that case so syncs succeed on every platform.
    """
    try:
        shutil.copy2(src, dest)
    except OSError as e:
        if e.errno == errno.EINVAL:
            shutil.copyfile(src, dest)
        else:
            raise


class SDManager:
    # Temp suffix for copy/convert-then-rename (atomic slot on FAT/USB)
    _SD_PART_SUFFIX = ".vrpart"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    @staticmethod
    def _wait_for_stable_file_size(
        path: Path,
        *,
        min_bytes: int = 2048,
        timeout_s: float = 300.0,
        poll_s: float = 0.12,
        stable_polls: int = 4,
    ) -> bool:
        """True when *path* exists, is at least *min_bytes*, and size stops growing.

        VLC/pydub can create a non-empty file long before encoding finishes; polling
        ``exists() and size > 0`` alone yields truncated MP3s.
        """
        deadline = time.monotonic() + timeout_s
        last_sz = -1
        same = 0
        while time.monotonic() < deadline:
            try:
                if path.exists():
                    sz = path.stat().st_size
                    if sz >= min_bytes:
                        if sz == last_sz:
                            same += 1
                            if same >= stable_polls:
                                return True
                        else:
                            same = 0
                            last_sz = sz
                    else:
                        same = 0
                        last_sz = -1
            except OSError:
                pass
            time.sleep(poll_s)
        try:
            return path.exists() and path.stat().st_size >= min_bytes
        except OSError:
            return False

    def _atomic_copy2(self, src: Path, dest: Path) -> None:
        """Copy to removable media: write ``*.vrpart`` then ``os.replace`` into final name."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.parent / f"{dest.name}{self._SD_PART_SUFFIX}"
        try:
            _copy2_with_fallback(src, part)
            os.replace(part, dest)
        except Exception:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _atomic_replace_written_file(self, part: Path, final: Path) -> None:
        """Rename a fully written temp file to the DFPlayer slot name."""
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, final)

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
    def _format_sd_card(sd_root: Path, label: str = SYNC_TARGET_VOLUME_LABEL) -> Path:
        """Reformat the SD card as FAT32 and return the (possibly new) mount path.

        Raises ``RuntimeError`` on failure or unsupported platform configuration.
        """
        system = platform.system()

        if system == "Darwin":
            # Resolve disk identifier from mount path
            try:
                info = subprocess.run(
                    ["diskutil", "info", "-plist", str(sd_root)],
                    capture_output=True, timeout=10,
                )
                if info.returncode != 0:
                    raise RuntimeError(f"diskutil info failed: {info.stderr.decode(errors='replace')}")
                import plistlib
                plist = plistlib.loads(info.stdout)
                disk_id = plist.get("ParentWholeDisk") or plist.get("DeviceIdentifier")
                if not disk_id:
                    raise RuntimeError("Could not determine disk identifier for SD card.")
            except subprocess.TimeoutExpired:
                raise RuntimeError("diskutil info timed out")

            result = subprocess.run(
                ["diskutil", "eraseDisk", "FAT32", label, "MBRFormat", disk_id],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(f"diskutil eraseDisk failed: {result.stderr}")
            new_path = Path("/Volumes") / label
            # Give macOS a moment to mount the freshly formatted volume
            for _ in range(10):
                if new_path.is_dir():
                    return new_path
                time.sleep(0.5)
            if new_path.is_dir():
                return new_path
            raise RuntimeError(
                f"Formatted volume not found at {new_path} after diskutil eraseDisk."
            )

        if system == "Windows":
            root = str(sd_root.resolve())
            if len(root) < 2 or root[1] != ":":
                raise RuntimeError(f"Cannot determine drive letter from {sd_root}")
            drive = root[:2]

            # Windows `format` refuses FAT32 on >32 GB volumes. Detect and skip.
            try:
                import ctypes
                free = ctypes.c_ulonglong(0)
                total = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    drive + "\\", None, ctypes.pointer(total), ctypes.pointer(free),
                )
                if total.value > 32 * 1024 * 1024 * 1024:
                    print(
                        f"SD card is larger than 32 GB ({total.value / (1024**3):.1f} GB). "
                        "Windows cannot format >32 GB as FAT32. Skipping reformat."
                    )
                    return sd_root
            except Exception:
                pass

            result = subprocess.run(
                ["format", drive, "/FS:FAT32", "/Q", f"/V:{label}", "/Y"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(f"format command failed: {result.stderr}")
            return sd_root

        if system == "Linux":
            # Resolve the block device from the mount path
            try:
                import re as _re
                mounts = Path("/proc/mounts").read_text()
                device = None
                for line in mounts.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == str(sd_root):
                        device = parts[0]
                        break
                if not device:
                    raise RuntimeError(f"Could not find block device for {sd_root}")
                subprocess.run(["umount", str(sd_root)], capture_output=True, timeout=10, check=True)
                subprocess.run(
                    ["mkfs.fat", "-F", "32", "-n", label, device],
                    capture_output=True, text=True, timeout=120, check=True,
                )
                mount_point = sd_root
                subprocess.run(["mount", device, str(mount_point)], capture_output=True, timeout=10, check=True)
                return mount_point
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Linux format failed: {e.stderr}")

        raise RuntimeError(f"Unsupported platform: {system}")

    @staticmethod
    def remove_hidden_junk_from_sd(sd_root: Path, *, dot_clean_merge: bool = False) -> int:
        """Delete macOS/Windows metadata files that confuse the DFPlayer (0x4E counts them).

        Removes:
        - At the volume root only: ``.Spotlight-V100``, ``.fseventsd``, ``.Trashes``,
          ``.TemporaryItems``, ``System Volume Information`` (macOS/Windows may
          recreate these while the volume stays mounted; we remove them again at the
          end of this pass and once more before eject in the GUI)
        - AppleDouble files ``._*`` (e.g. ``._001.mp3`` next to ``001.mp3``)
        - ``.DS_Store``, ``.apdisk``, ``.localized``
        - ``Thumbs.db``, ``desktop.ini``
        - Entire ``__MACOSX`` directory trees (common after Finder/zip)

        Does not remove ``.sync_manifest.json`` (app sync fingerprint).

        On macOS, creates an empty ``.metadata_never_index`` at the volume root if
        missing (tells Spotlight to skip indexing on many external volumes).

        *dot_clean_merge*: when True and on macOS, run ``dot_clean -m`` on the volume
        first (merges AppleDouble on FAT/exFAT), matching the flow described at
        https://www.javawa.nl/cleanejectreplacement.html . Prefer True only for
        pre-eject cleanup; it can be slow on large cards.

        Returns the number of files deleted plus one count per directory tree removed.
        """
        removed = 0
        try:
            root = sd_root.resolve()
        except OSError:
            return 0
        if not root.is_dir():
            return 0

        if dot_clean_merge and platform.system() == "Darwin":
            try:
                subprocess.run(
                    ["dot_clean", "-m", str(root)],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

        removed += _remove_sd_root_service_dirs(root)

        macosx_dirs: List[Path] = []
        try:
            for p in root.rglob("__MACOSX"):
                if p.is_dir():
                    macosx_dirs.append(p)
        except OSError:
            pass
        for d in sorted(macosx_dirs, key=lambda p: len(p.parts), reverse=True):
            try:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
            except OSError:
                pass

        junk_exact = frozenset({".DS_Store", ".apdisk", "Thumbs.db", "desktop.ini", ".localized"})
        part_suffix = SDManager._SD_PART_SUFFIX
        try:
            for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
                base = Path(dirpath)
                for name in filenames:
                    if name.endswith(part_suffix):
                        fp = base / name
                        try:
                            fp.unlink()
                            removed += 1
                        except OSError:
                            pass
                        continue
                    if name in junk_exact or name.startswith("._"):
                        fp = base / name
                        try:
                            fp.unlink()
                            removed += 1
                        except OSError:
                            pass
        except OSError:
            pass

        # Spotlight/FSEvents often recreate root service folders during a long walk
        # or right after many file writes; remove them again before returning.
        removed += _remove_sd_root_service_dirs(root)

        if platform.system() == "Darwin":
            try:
                (root / ".metadata_never_index").touch(exist_ok=True)
            except OSError:
                pass

        return removed

    @staticmethod
    def is_sync_target_sd_present(
        sd_root: Optional[str],
        stored_label: Optional[str],
        extra_labels: Optional[Iterable[str]] = None,
    ) -> bool:
        """
        Return True only when the SD card we sync to is actually connected and
        visible as a removable drive. Uses detect_sd_roots() so we don't show
        "out of sync" when the card is unplugged (path may still exist on some systems).

        *extra_labels*: optional additional volume names to treat as the same card
        (e.g. basic-mode trusted volume name).
        """
        detected = SDManager.detect_sd_roots()
        if not detected:
            return False
        label_set: set = set()
        if stored_label and str(stored_label).strip():
            label_set.add(str(stored_label).strip().upper())
        if extra_labels:
            for x in extra_labels:
                if x and str(x).strip():
                    label_set.add(str(x).strip().upper())
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
            if label_set and label and label.strip().upper() in label_set:
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
                    try:
                        accessible = path.exists()
                    except OSError:
                        accessible = False
                    if accessible:
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
    def is_rp2040_bootsel_present() -> bool:
        """True if an RP2040 is in USB bootloader mode (UF2 drive), usually named RPI-RP2.

        Unflashed / BOOTSEL Pico has no serial port; it only appears as this removable volume.
        """
        try:
            for _path, label in SDManager.detect_sd_roots():
                if label and label.strip().upper() == "RPI-RP2":
                    return True
        except Exception:
            pass
        return False

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

        On macOS, check the app bundle *before* ``import vlc`` — importing
        python-vlc can block for a long time while libVLC loads and would delay
        GUI startup when this runs from ``run_app`` before the window is shown.
        """
        # 1) Executable / app-bundle detection (fast; no python-vlc import)
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
            if result.returncode == 0:
                return True
        except Exception:
            pass
        # 2) python-vlc (last resort; can be slow to import on some Macs)
        try:
            import vlc as _vlc  # noqa: F401

            return True
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

        Writes to ``*.vrpart``, waits until the output size stabilizes (VLC is
        async — ``exists()`` and ``size > 0`` is not enough), then renames into
        the final slot so the SD card never sees a truncated ``NNN.mp3``.
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = target_path.parent / f"{target_path.name}{self._SD_PART_SUFFIX}"
        try:
            part_path.unlink(missing_ok=True)
        except OSError:
            pass
        abs_part = str(part_path.resolve())
        abs_source = str(source_path.resolve())

        def _finalize_part() -> bool:
            if not self._wait_for_stable_file_size(part_path, min_bytes=512, timeout_s=300.0):
                print(f"VLC output did not stabilize for {source_path.name}")
                try:
                    part_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False
            try:
                self._atomic_replace_written_file(part_path, target_path)
            except OSError as e:
                print(f"Could not finalize converted file {target_path.name}: {e}")
                try:
                    part_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False
            return True

        try:
            import vlc
            instance = vlc.Instance(['--intf', 'dummy', '--quiet'])
            sout = f"#transcode{{acodec=mp3,ab=192}}:std{{access=file,mux=dummy,dst={abs_part}}}"
            media = instance.media_new(abs_source, f":sout={sout}")
            player = instance.media_player_new()
            player.set_media(media)
            player.play()
            ok = _finalize_part()
            try:
                player.stop()
            except Exception:
                pass
            if ok:
                return True
        except Exception as e:
            print(f"libVLC conversion unavailable or failed: {e}")

        try:
            vlc_path = self._get_vlc_path()
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
            cmd = [
                vlc_path,
                '--intf', 'dummy',
                '--quiet',
                '--sout',
                f'#transcode{{acodec=mp3,ab=192}}:std{{access=file,mux=dummy,dst={abs_part}}}',
                abs_source,
                'vlc://quit',
            ]
            print(
                f"Attempting VLC (exec) conversion: {source_path.name} -> {target_path.name} using {vlc_path}"
            )
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            if result.returncode != 0:
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
                try:
                    part_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False
            if _finalize_part():
                print(f"VLC conversion successful: {source_path.name}")
                return True
            return False
        except Exception as e:
            print(f"VLC exec conversion error for {source_path.name}: {e}")
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
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
        
        target_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = target_path.parent / f"{target_path.name}{self._SD_PART_SUFFIX}"
        try:
            part_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            if source_ext == ".flac":
                audio = AudioSegment.from_file(str(source_path), format="flac")
            else:
                audio = AudioSegment.from_file(str(source_path))
            audio.export(
                str(part_path),
                format="mp3",
                bitrate="192k",
                parameters=["-q:a", "2"],
            )
            self._atomic_replace_written_file(part_path, target_path)
            return True
        except Exception as e:
            print(f"pydub/ffmpeg conversion error for {source_path.name}: {e}")
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
            if source_ext == ".flac":
                try:
                    audio = AudioSegment.from_file(str(source_path))
                    audio.export(str(part_path), format="mp3", bitrate="192k")
                    self._atomic_replace_written_file(part_path, target_path)
                    return True
                except Exception as e2:
                    print(f"Alternative FLAC conversion also failed for {source_path.name}: {e2}")
                    try:
                        part_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            return False

    def _resolved_basic_station_end_mode(self) -> str:
        raw = self.db.get_setting("basic_station_end_mode", "") or ""
        end_mode = raw.strip()
        if end_mode in ("loop", "advance", "none"):
            return end_mode
        legacy = (self.db.get_setting("basic_loop_stations", "") or "").strip()
        if legacy == "1":
            return "loop"
        if legacy == "0":
            return "none"
        return "advance"

    def sync_library_basic(
        self,
        sd_root: Path,
        force_clean: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[int, int]:
        """Sync basic-mode stations to SD card.

        Each station maps to a DFPlayer folder (01-98). Tracks are duplicated
        across folders if they appear in multiple stations. Folder 99 is
        reserved for the AM WAV overlay. The DFPlayer firmware discovers layout
        by querying the module directly; the app also writes a hidden
        ``.sync_manifest.json`` at the SD root (for host-side mismatch checks),
        which the DFPlayer ignores.
        """
        RESERVED_FOLDER = 99
        stations = self.db.list_basic_stations()
        if not stations:
            if progress_callback:
                progress_callback(1, 1, "No stations to sync")
            self._copy_am_wav_to_dfplayer_sd(sd_root)
            _end = self._resolved_basic_station_end_mode()
            print(f"Basic SD sync: station end mode = {_end!r} (folder 99 / DFPlayer 0x4E count)")
            self._write_basic_feature_flags(sd_root, end_mode=_end)
            n = self.remove_hidden_junk_from_sd(sd_root)
            if n:
                print(
                    f"Basic SD sync: removed {n} hidden/junk item(s) "
                    "(macOS ._*, .DS_Store, __MACOSX, etc.)"
                )
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

        manifest_stations: Dict[str, dict] = {}
        old_manifest = self._read_sync_manifest(sd_root) if not force_clean else None
        old_manifest_stations = (old_manifest or {}).get("stations", {})
        used_folders: set = set()
        for folder_num, tracks in station_tracks:
            used_folders.add(folder_num)
            folder_key = f"{folder_num:02d}"
            folder_path = sd_root / folder_key
            folder_path.mkdir(parents=True, exist_ok=True)
            valid_track_nums: set = set()
            manifest_tracks: Dict[str, dict] = {}

            station_name = ""
            for st in stations:
                if int(st["folder_number"]) == folder_num:
                    station_name = (st["name"] or "").strip()
                    break

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

                manifest_tracks[f"{track_order:03d}"] = {
                    "source_name": file_path.name,
                    "source_size": file_path.stat().st_size,
                }

                if not force_clean and target_path.exists():
                    try:
                        target_size = target_path.stat().st_size
                        if source_ext == ".mp3":
                            if target_size == file_path.stat().st_size:
                                skipped += 1
                                work_done += 1
                                continue
                        else:
                            # Non-MP3: check old manifest first, then fall
                            # back to source-mtime comparison.
                            old_folder = old_manifest_stations.get(folder_key, {})
                            old_entry = (old_folder.get("tracks") or {}).get(f"{track_order:03d}")
                            if old_entry and target_size > 0:
                                if (old_entry.get("source_name") == file_path.name
                                        and old_entry.get("source_size") == file_path.stat().st_size):
                                    skipped += 1
                                    work_done += 1
                                    continue
                            elif target_size > 0:
                                try:
                                    if file_path.stat().st_mtime <= target_path.stat().st_mtime:
                                        skipped += 1
                                        work_done += 1
                                        continue
                                except OSError:
                                    pass
                    except OSError:
                        pass

                try:
                    if source_ext == ".mp3":
                        self._atomic_copy2(file_path, target_path)
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

            manifest_stations[folder_key] = {
                "name": station_name,
                "tracks": manifest_tracks,
            }

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

        _end = self._resolved_basic_station_end_mode()
        print(f"Basic SD sync: station end mode = {_end!r} (folder 99 / DFPlayer 0x4E count)")
        self._write_basic_feature_flags(sd_root, end_mode=_end)

        if progress_callback:
            progress_callback(total_work, total_work, "Basic sync complete!")
        n = self.remove_hidden_junk_from_sd(sd_root)
        if n:
            print(
                f"Basic SD sync: removed {n} hidden/junk item(s) "
                "(macOS ._*, .DS_Store, __MACOSX, etc.)"
            )

        self._write_sync_manifest(sd_root, manifest_stations)

        print(f"Basic SD sync complete: {copied} copied, {skipped} skipped across {len(stations)} stations")
        return copied, skipped

    # -- Sync manifest helpers ------------------------------------------------

    @staticmethod
    def _write_sync_manifest(sd_root: Path, stations: Dict[str, dict]) -> None:
        """Persist a lightweight manifest at the SD root after a basic-mode sync."""
        import datetime
        manifest = {
            "version": 1,
            "synced_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "stations": stations,
        }
        path = sd_root / _SYNC_MANIFEST_NAME
        try:
            with path.open("w", encoding="utf-8") as fh:
                json.dump(manifest, fh, separators=(",", ":"))
        except OSError as e:
            print(f"Warning: could not write sync manifest: {e}")

    @staticmethod
    def _read_sync_manifest(sd_root: Path) -> Optional[dict]:
        """Read the manifest written by a previous sync, or *None* if absent/corrupt."""
        path = sd_root / _SYNC_MANIFEST_NAME
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("version") == 1:
                return data
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return None

    def validate_basic_sd(self, sd_root: Path) -> List[str]:
        """Compare basic-mode stations to DFPlayer folders on *sd_root*.

        Returns human-readable issue strings (empty if layout matches). Mirrors
        :meth:`sync_library_basic` naming: ``NN/001.mp3`` ...

        If a ``.sync_manifest.json`` (written by :meth:`sync_library_basic`) is
        present on the SD root, it is used as the primary mismatch check: the
        manifest records the original filename and size of each track that was
        synced, allowing reliable detection even when a completely different
        library happens to share the same folder structure or file sizes.  When
        the manifest is absent (old card, manually copied files), the method
        falls back to the legacy size/duration heuristics.
        """
        msgs: List[str] = []
        if not sd_root.is_dir():
            return ["SD root is missing or not a directory."]
        RESERVED_FOLDER = 99
        try:
            stations = self.db.list_basic_stations()
        except Exception:
            return ["Could not read stations from the database."]

        manifest = self._read_sync_manifest(sd_root)
        manifest_stations = (manifest or {}).get("stations", {})

        for st in stations:
            fid = int(st["id"])
            fn = int(st["folder_number"])
            name = (st["name"] or "").strip() or f"Station {fn}"
            if fn == RESERVED_FOLDER:
                continue
            folder_key = f"{fn:02d}"
            folder = sd_root / folder_key
            tracks = self.db.list_basic_station_songs(fid)
            n = len(tracks)
            if n == 0:
                continue
            if not folder.is_dir():
                msgs.append(f'Missing folder {folder_key} for station "{name}" ({n} tracks in the app).')
                continue

            manifest_folder = manifest_stations.get(folder_key, {})
            manifest_tracks = manifest_folder.get("tracks", {}) if manifest_folder else {}

            mp3_indices: List[int] = []
            try:
                for p in folder.iterdir():
                    if not p.is_file():
                        continue
                    if p.suffix.lower() != ".mp3":
                        continue
                    if p.stem.isdigit():
                        mp3_indices.append(int(p.stem))
            except OSError as e:
                msgs.append(f'Station "{name}" (folder {folder_key}): cannot read folder ({e}).')
                continue
            mp3_set = set(mp3_indices)
            for order in range(1, n + 1):
                if order not in mp3_set:
                    msgs.append(
                        f'Station "{name}": missing {order:03d}.mp3 on SD (folder {folder_key}).'
                    )
            for idx in sorted(mp3_set):
                if idx > n:
                    msgs.append(
                        f'Station "{name}": extra file {idx:03d}.mp3 on SD '
                        f"(app has only {n} tracks in folder {folder_key})."
                    )
            for order, song in enumerate(tracks, start=1):
                fp_raw = song["file_path"]
                if not fp_raw:
                    t = song["title"] or song["original_filename"] or f"track {order}"
                    msgs.append(f'Station "{name}": no file path for "{t}".')
                    continue
                fp = Path(fp_raw)
                if not fp.exists():
                    t = song["title"] or song["original_filename"] or f"track {order}"
                    msgs.append(
                        f'Station "{name}": source file missing for "{t}" '
                        f"(expected {order:03d}.mp3 on SD after sync)."
                    )
                    continue

                slot = folder / f"{order:03d}.mp3"
                if not slot.is_file():
                    continue  # missing-slot issues already reported above
                t = song["title"] or song["original_filename"] or f"track {order}"
                track_key = f"{order:03d}"

                try:
                    # Primary check: manifest-based comparison (reliable across
                    # different libraries that happen to share structure/sizes).
                    m_entry = manifest_tracks.get(track_key)
                    if m_entry:
                        if (fp.name != m_entry.get("source_name")
                                or fp.stat().st_size != m_entry.get("source_size")):
                            msgs.append(
                                f'Station "{name}": {track_key}.mp3 on SD was synced from a '
                                f'different source than "{t}" (sync to SD to update).'
                            )
                        continue  # manifest is authoritative; skip heuristic

                    # Fallback: legacy heuristic (no manifest on this card).
                    if fp.suffix.lower() == ".mp3":
                        if fp.stat().st_size != slot.stat().st_size:
                            msgs.append(
                                f'Station "{name}": {track_key}.mp3 on SD does not match '
                                f'"{t}" in this position (track order or file changed — sync to SD).'
                            )
                    else:
                        lib_dur = song["duration"]
                        if lib_dur is not None:
                            try:
                                lib_sec = float(lib_dur)
                            except (TypeError, ValueError):
                                lib_sec = None
                            if lib_sec is not None and lib_sec > 0:
                                meta = extract_metadata(slot)
                                sd_dur = meta.get("duration")
                                if sd_dur is not None:
                                    try:
                                        sd_sec = float(sd_dur)
                                    except (TypeError, ValueError):
                                        sd_sec = None
                                    if sd_sec is not None:
                                        tol = max(3.0, 0.05 * lib_sec)
                                        if abs(sd_sec - lib_sec) > tol:
                                            msgs.append(
                                                f'Station "{name}": {track_key}.mp3 on SD '
                                                f'looks out of sync with "{t}" (duration differs — '
                                                f"track order may have changed — sync to SD)."
                                            )
                except OSError:
                    pass
        return msgs

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

        After a successful sync pass, macOS/Windows hidden junk (``._*``, ``.DS_Store``,
        etc.) is removed from ``sd_root`` so DFPlayer folder counts stay accurate.
        """
        target = audio_target or "dfplayer_rp2040"
        pi_convert = pi_convert_audio if pi_convert_audio is not None else True
        if target == "dfplayer_rp2040":
            result = self._sync_library_dfplayer(
                sd_root, force_clean=force_clean, progress_callback=progress_callback
            )
        else:
            result = self._sync_library_pi(
                sd_root,
                convert_to_mp3=pi_convert,
                force_clean=force_clean,
                progress_callback=progress_callback,
            )
        n = self.remove_hidden_junk_from_sd(sd_root)
        if n:
            print(
                f"SD sync: removed {n} hidden/junk item(s) "
                "(macOS ._*, .DS_Store, __MACOSX, etc.)"
            )
        return result

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
                    self._atomic_copy2(file_path, target_path)
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
            # Incremental sync may skip unchanged files (see Phase 1). Clean sync
            # (force_clean) never skips — every slot is rewritten. Parallel workers
            # are safe with _atomic_copy2 (temp + os.replace per file).
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

    _BASIC_FLAG_MP3_STUB = b"\xff\xfb\x90\x00" + b"\x00" * 413

    def _write_basic_feature_flags(
        self, sd_root: Path, end_mode: str = "advance"
    ) -> None:
        """Write feature flags under DFPlayer folder 99 (firmware reads count via 0x4E only).

        The Pico does not read a separate text file or flash slot for this — only the
        DFPlayer ``query_files_in_folder(99)`` result is used.

        Layout:
          ``001.wav`` — AM sound (always, when synced)
          ``002.mp3`` — present for loop *or* as part of advance bundle
          ``003.mp3``, ``004.mp3`` — advance-only extra stubs

        Count (0x4E): many modules skip ``.wav`` in the count, so advance uses **three**
        MP3 stubs so total is >=3 even when only 002--004 are counted. Otherwise
        002+003 would read as 2 and firmware would treat it as **loop**.

        1 = end playback, 2 = loop, 3+ = proceed to next station.
        """
        if end_mode not in ("loop", "advance", "none"):
            end_mode = "advance"
        folder = sd_root / "99"
        folder.mkdir(parents=True, exist_ok=True)
        stub = self._BASIC_FLAG_MP3_STUB
        p002 = folder / "002.mp3"
        p003 = folder / "003.mp3"
        p004 = folder / "004.mp3"

        if end_mode == "loop":
            if not p002.exists():
                p002.write_bytes(stub)
                print(f"Feature flag written: {p002} (loop)")
            for p, label in ((p003, "003"), (p004, "004")):
                if p.exists():
                    p.unlink()
                    print(f"Feature flag removed: {p} ({label} cleared for loop)")
        elif end_mode == "advance":
            for p, name in ((p002, "002"), (p003, "003"), (p004, "004")):
                if not p.exists():
                    p.write_bytes(stub)
                    print(f"Feature flag written: {p} (advance bundle)")
        else:
            for p, label in ((p002, "002"), (p003, "003"), (p004, "004")):
                if p.exists():
                    p.unlink()
                    print(f"Feature flag removed: {p} (stop at end)")

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
                    part_wav = target_path.parent / f"{target_path.name}{self._SD_PART_SUFFIX}"
                    try:
                        part_wav.unlink(missing_ok=True)
                    except OSError:
                        pass
                    audio.export(str(part_wav), format="wav", parameters=["-acodec", "pcm_s16le"])
                    self._atomic_replace_written_file(part_wav, target_path)
                    print(f"AM WAV converted and copied to SD: {target_path}")
                    return True
                except Exception as e:
                    print(f"Conversion failed: {e}, copying original")
            
            self._atomic_copy2(source, target_path)
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
                    self._atomic_copy2(file_path, target_path)
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
                        self._atomic_copy2(file_path, target_path)
                    else:
                        if not self._convert_to_mp3(file_path, target_path):
                            skipped += 1
                            continue
                else:
                    self._atomic_copy2(file_path, target_path)
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
                self._atomic_copy2(source, target_path)
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
                    self._atomic_copy2(source, target)
                else:
                    self._convert_to_mp3(source, target)
            else:
                target = folder / source.name
                self._atomic_copy2(source, target)
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
                        _copy2_with_fallback(sd_file, dest_file)
                        file_path = str(dest_file)
                    except OSError as e:
                        print(f"Failed to copy {sd_file.name} to {dest_dir}: {e}")
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
                    _copy2_with_fallback(source, target)
                    print(f"AM WAV copied to: {target} (original format)")
            else:
                # Copy as-is (format is already compatible or conversion not available)
                _copy2_with_fallback(source, target)
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
                _copy2_with_fallback(source, target)
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

