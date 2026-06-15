"""SD card management utilities."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import platform
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import psutil

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

from .audio_metadata import (
    compute_file_hash,
    extract_metadata,
    file_matches_metadata,
    mp3_matches_conversion_profile,
)
from .database import DatabaseManager
from .resource_paths import resource_path, resolve_ffmpeg_executable


# Volume label we set on the SD card after first sync so we can recognize it among multiple cards
SYNC_TARGET_VOLUME_LABEL = "VINTAGERADIO"

# Manifest file written at the SD root during sync so we can reliably detect
# content mismatches even when two different libraries share folder structure.
_SYNC_MANIFEST_NAME = ".sync_manifest.json"


def _basic_sync_progress_step_interval(total: int, *, large_step: int) -> int:
    """Emit progress every N completions so small syncs update every file (avoids stuck 0/N UI)."""
    if total <= 0:
        return 1
    if total <= 500:
        return 1
    return large_step

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


def _sd_copy_file_fast(src: Path, dest: Path) -> None:
    """Copy file bytes quickly for SD sync (large buffers; Windows uses ``CopyFileW``).

    Many small MP3s are still limited by FAT metadata updates per file; this matches
    typical Explorer/FastCopy-style buffering better than default ``shutil`` chunks.
    Override buffer size with env ``VINTAGE_RADIO_SD_COPY_BUFFER_BYTES`` (default 4 MiB).
    """
    src = Path(src)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = (os.environ.get("VINTAGE_RADIO_SD_COPY_BUFFER_BYTES", "") or "").strip()
        buf = int(raw) if raw else 4 * 1024 * 1024
    except ValueError:
        buf = 4 * 1024 * 1024
    buf = max(64 * 1024, min(buf, 128 * 1024 * 1024))

    if os.name == "nt":
        try:
            import ctypes

            ok = ctypes.windll.kernel32.CopyFileW(
                str(src.resolve()),
                str(dest.resolve()),
                False,
            )
            if ok:
                return
        except Exception:
            pass

    with open(src, "rb") as fsrc, open(dest, "wb") as fdst:
        shutil.copyfileobj(fsrc, fdst, length=buf)


class SDManager:
    # Temp suffix for copy/convert-then-rename (atomic slot on FAT/USB)
    _SD_PART_SUFFIX = ".vrpart"

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self._ffmpeg_exe: Optional[str] = None
        self._ffmpeg_checked = False
        self._ffmpeg_available = False
        self._vlc_checked = False
        self._vlc_available = False
        self._active_proc_lock = threading.Lock()
        self._active_ffmpeg_processes: set[subprocess.Popen[Any]] = set()

    @staticmethod
    def _safe_rmtree(path: Path) -> None:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def _clean_install_purge(
        self,
        sd_root: Path,
        progress_callback: Optional[callable] = None,
        volume_label: str = SYNC_TARGET_VOLUME_LABEL,
    ) -> Path:
        """Wipe app-managed content for a clean install.

        Strategy (fastest first):
        1. PowerShell ``Format-Volume`` quick-format (instant, Windows <= 32 GB)
        2. macOS ``diskutil eraseDisk`` (instant, any size)
        3. Parallel folder deletion fallback (works everywhere, slower)
        """
        root = Path(sd_root)
        fmt_label = _sanitize_fat_volume_label(volume_label) or SYNC_TARGET_VOLUME_LABEL

        # ── Attempt quick format ──
        system = platform.system()
        if system == "Windows":
            try:
                return self._quick_format_windows(
                    root,
                    progress_callback=progress_callback,
                    volume_label=fmt_label,
                )
            except Exception as e:
                print(f"Quick format unavailable ({e}), falling back to parallel purge")
        elif system == "Darwin":
            try:
                formatted = self._format_sd_card(root, label=fmt_label)
                if progress_callback:
                    progress_callback(1, 1, "Format complete")
                return formatted
            except Exception as e:
                print(f"diskutil format failed ({e}), falling back to parallel purge")

        # ── Fallback: parallel folder deletion ──
        if progress_callback:
            progress_callback(0, 1, "Removing SD content (parallel)...")

        items_to_delete: List[Path] = []
        try:
            for item in root.iterdir():
                name = item.name
                if len(name) == 2 and name.isdigit():
                    items_to_delete.append(item)
        except OSError:
            pass

        items_to_delete.append(root / "VintageRadio")
        for name in (
            _SYNC_MANIFEST_NAME,
            "radio_metadata.json",
            "advanced_runtime.json",
            ".metadata_never_index",
            ".DS_Store",
            "Thumbs.db",
            "desktop.ini",
        ):
            items_to_delete.append(root / name)

        items_to_delete = [p for p in items_to_delete if p.exists()]
        total = max(1, len(items_to_delete))
        done = 0

        num_workers = min(8, total)
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = {pool.submit(self._safe_rmtree, p): p for p in items_to_delete}
            for future in as_completed(futures):
                done += 1
                if progress_callback and (done % 5 == 0 or done == total):
                    progress_callback(done, total + 1, f"Removed {done}/{total} items...")

        _remove_sd_root_service_dirs(root)

        if progress_callback:
            progress_callback(total + 1, total + 1, "Clean install purge complete")
        return root

    def _quick_format_windows(
        self,
        sd_root: Path,
        progress_callback: Optional[callable] = None,
        volume_label: str = SYNC_TARGET_VOLUME_LABEL,
    ) -> Path:
        """Quick-format an SD card via PowerShell ``Format-Volume``.

        Raises ``RuntimeError`` if the format fails or the drive is > 32 GB
        (Windows native FAT32 limitation).
        """
        drive_str = str(sd_root.resolve())
        if len(drive_str) < 2 or drive_str[1] != ":":
            raise RuntimeError(f"Cannot determine drive letter from {sd_root}")
        drive_letter = drive_str[0]

        if progress_callback:
            progress_callback(0, 1, "Quick-formatting SD card (FAT32)...")

        safe_label = (volume_label or SYNC_TARGET_VOLUME_LABEL).replace("'", "''")
        ps_cmd = (
            f"Format-Volume -DriveLetter {drive_letter} "
            f"-FileSystem FAT32 "
            f"-NewFileSystemLabel '{safe_label}' "
            f"-Force -Confirm:$false"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Format-Volume failed (rc={result.returncode}): "
                f"{(result.stderr or result.stdout).strip()}"
            )

        for _ in range(30):
            if sd_root.is_dir():
                try:
                    list(sd_root.iterdir())
                    if progress_callback:
                        progress_callback(1, 1, "Format complete")
                    return sd_root
                except OSError:
                    pass
            time.sleep(0.5)
        raise RuntimeError("SD card not accessible after format")

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
            try:
                _sd_copy_file_fast(src, part)
            except OSError:
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
    def set_sync_target_volume_label(sd_root: Path, label: Optional[str] = None) -> bool:
        """
        Try to set the volume label of the given path so we can detect "our" SD card
        when multiple are present.

        If *label* is None, uses :data:`SYNC_TARGET_VOLUME_LABEL` (default app label).
        Returns True if we believe the label was set (or already matched).
        """
        target = _sanitize_fat_volume_label(label) if label else SYNC_TARGET_VOLUME_LABEL
        if not target:
            target = SYNC_TARGET_VOLUME_LABEL
        try:
            system = platform.system()
            if system == "Windows":
                root = str(sd_root.resolve())
                if len(root) >= 2 and root[1] == ":":
                    drive = root[:2]
                    try:
                        import ctypes
                        from ctypes import wintypes
                        if ctypes.windll.kernel32.SetVolumeLabelW(drive + "\\", target):
                            return True
                    except Exception:
                        pass
                    try:
                        r = subprocess.run(
                            ["label", drive, target],
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
                            if current == target:
                                return True
                            r = subprocess.run(
                                ["diskutil", "rename", current, target],
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
        label = _sanitize_fat_volume_label(label) or SYNC_TARGET_VOLUME_LABEL
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

            # `format` is a cmd.exe built-in, not on PATH as an executable — use format.com
            # so subprocess can spawn it (avoids FileNotFoundError on Windows).
            system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
            format_com = Path(system_root) / "System32" / "format.com"
            if not format_com.is_file():
                raise RuntimeError(
                    f"Windows format utility not found at {format_com}. Cannot reformat the SD card."
                )
            try:
                result = subprocess.run(
                    [str(format_com), drive, "/FS:FAT32", "/Q", f"/V:{label}", "/Y"],
                    capture_output=True, text=True, timeout=300,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    "SD format timed out on Windows. The card may be busy or very slow. "
                    "Try normal sync, or eject/reinsert and retry clean install."
                ) from e
            if result.returncode != 0:
                err = (result.stderr or "") + (result.stdout or "")
                raise RuntimeError(f"format command failed: {err.strip() or result.returncode}")

            # Windows remounts the freshly formatted volume asynchronously.
            # Poll until the path is accessible (mirrors macOS diskutil wait loop).
            for _ in range(16):
                try:
                    if sd_root.is_dir():
                        return sd_root
                except OSError:
                    pass
                time.sleep(0.5)
            try:
                if sd_root.is_dir():
                    return sd_root
            except OSError:
                pass
            raise RuntimeError(
                f"Formatted volume at {sd_root} is not accessible after format. "
                "Try ejecting and reinserting the SD card."
            )

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

        Windows: Uses psutil (``all=True``) plus ``GetDriveTypeW`` removable drives
        so internal/USB SD readers are listed even when partition opts omit
        *removable*.  macOS: /Volumes.  Linux: /mnt, /media.
        """
        roots: List[Tuple[Path, str]] = []
        system = platform.system()

        if system == "Windows":
            system_drive = os.environ.get("SystemDrive", "C:")
            seen: set = set()

            def _add(path: Path, label: str) -> None:
                try:
                    key = str(path.resolve()).rstrip("\\").upper()
                except OSError:
                    key = str(path).rstrip("\\").upper()
                if key in seen:
                    return
                try:
                    if not path.exists():
                        return
                except OSError:
                    return
                seen.add(key)
                roots.append((path, label))

            for part in psutil.disk_partitions(all=True):
                mount = part.mountpoint
                if not mount:
                    continue
                if mount.upper().startswith(system_drive.upper()):
                    continue
                opts = part.opts.lower()
                fstype = part.fstype.lower()
                if "removable" in opts or fstype in {"fat", "fat32", "exfat"}:
                    path = Path(mount)
                    try:
                        accessible = path.exists()
                    except OSError:
                        accessible = False
                    if accessible:
                        _add(path, _get_volume_label(path))

            for path, label in _windows_get_removable_drive_roots():
                _add(path, label or _get_volume_label(path))

        elif system == "Darwin":
            # macOS: Scan /Volumes for mounted external drives.
            # Use psutil to restrict to FAT/exFAT/msdos filesystems (SD cards, USB
            # sticks) and volumes flagged as removable, so large external HDDs and
            # internal volumes are not offered as SD card targets.
            try:
                partition_map: dict = {}
                for part in psutil.disk_partitions(all=True):
                    if part.mountpoint:
                        partition_map[part.mountpoint] = part
            except Exception:
                partition_map = {}

            system_volume_keywords = {
                "Macintosh HD", "System", "Recovery", "Install", "Installer",
                ".localized", ".disabled", "MobileBackups", "Update", "TimeMachine",
                "Shared Support", "Caches", "VM", "Temp"
            }

            volumes_path = Path("/Volumes")
            if volumes_path.exists():
                try:
                    for item in volumes_path.iterdir():
                        name = item.name
                        if name.startswith("."):
                            continue
                        if any(keyword.lower() in name.lower() for keyword in system_volume_keywords):
                            continue
                        if not item.is_dir() or not os.access(item, os.R_OK):
                            continue

                        # Check filesystem type via psutil if available; prefer
                        # FAT/exFAT volumes. If psutil has no record (some virtual
                        # mounts) fall back to allowing it.
                        part = partition_map.get(str(item))
                        if part is not None:
                            fstype = part.fstype.lower()
                            opts = part.opts.lower()
                            is_fat = fstype in {"msdos", "fat", "fat32", "exfat", "vfat"}
                            is_removable = "removable" in opts or "external" in opts
                            # Exclude clearly non-removable, non-FAT volumes
                            # (internal HFS+/APFS, large HDDs, etc.)
                            if not is_fat and not is_removable:
                                continue

                        roots.append((item, name))
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
            # macOS: UF2 volume is always FAT, but psutil filters can omit rare mounts; check /Volumes.
            if platform.system() == "Darwin":
                vols = Path("/Volumes")
                if vols.is_dir():
                    for item in vols.iterdir():
                        try:
                            if item.is_dir() and item.name.upper().startswith("RPI-RP2"):
                                return True
                        except OSError:
                            continue
        except Exception:
            pass
        return False

    @staticmethod
    def volume_label(path: Path) -> str:
        return _get_volume_label(path)

    @staticmethod
    def library_root(sd_root: Path) -> Path:
        """Pi / raspberry_pi layout only — flat library under VintageRadio/."""
        return sd_root / "VintageRadio" / "library"

    @staticmethod
    def vintage_root(sd_root: Path) -> Path:
        """Pi / legacy host layout. DFPlayer SD must not use this folder (numbered dirs only)."""
        return sd_root / "VintageRadio"

    @staticmethod
    def dfplayer_radio_metadata_path(sd_root: Path) -> Path:
        """``radio_metadata.json`` at SD root for DFPlayer (no VintageRadio/ directory)."""
        return sd_root / "radio_metadata.json"

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

    def _remove_legacy_vintage_radio_folder_on_dfplayer_sd(self, sd_root: Path) -> None:
        """Remove ``VintageRadio/`` on the DFPlayer SD card if present.

        The DFPlayer must only see numbered station folders (and reserved ``99/``);
        metadata and runtime JSON live at the SD root.
        """
        vr = sd_root / "VintageRadio"
        if not vr.is_dir():
            return
        try:
            shutil.rmtree(vr)
            print("SD: removed VintageRadio/ (DFPlayer: numbered folders + root JSON only)")
        except OSError as e:
            print(f"Warning: could not remove VintageRadio/ from SD: {e}")

    def _check_ffmpeg(self) -> bool:
        """Check if ffmpeg is available (needed for audio conversion)."""
        if self._ffmpeg_checked:
            return self._ffmpeg_available
        exe = resolve_ffmpeg_executable()
        if not exe:
            self._ffmpeg_checked = True
            self._ffmpeg_available = False
            return False
        try:
            result = subprocess.run(
                [exe, '-version'],
                capture_output=True,
                timeout=2
            )
            ok = result.returncode == 0
            if ok:
                self._ffmpeg_exe = exe
                if PYDUB_AVAILABLE:
                    try:
                        # Tell pydub explicitly which ffmpeg binary to use.
                        from pydub import AudioSegment as _AudioSegment

                        _AudioSegment.converter = exe
                    except Exception:
                        pass
            self._ffmpeg_checked = True
            self._ffmpeg_available = ok
            return ok
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._ffmpeg_checked = True
            self._ffmpeg_available = False
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
        if self._vlc_checked:
            return self._vlc_available

        # 1) Executable / app-bundle detection (fast; no python-vlc import)
        try:
            # macOS app bundle path
            if platform.system() == "Darwin":
                mac_path = Path("/Applications/VLC.app/Contents/MacOS/VLC")
                if mac_path.exists():
                    self._vlc_checked = True
                    self._vlc_available = True
                    return True
            # Windows common install locations or CLI in PATH
            if platform.system() == "Windows":
                vlc_paths = [
                    "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe",
                    "C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe",
                ]
                for vlc_path in vlc_paths:
                    if Path(vlc_path).exists():
                        self._vlc_checked = True
                        self._vlc_available = True
                        return True
            # Try invoking vlc --version on PATH
            result = subprocess.run(["vlc", "--version"], capture_output=True, timeout=2)
            if result.returncode == 0:
                self._vlc_checked = True
                self._vlc_available = True
                return True
        except Exception:
            pass
        # 2) python-vlc (last resort; can be slow to import on some Macs)
        try:
            import vlc as _vlc  # noqa: F401

            self._vlc_checked = True
            self._vlc_available = True
            return True
        except Exception:
            self._vlc_checked = True
            self._vlc_available = False
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
            # Bound wait time so one bad conversion does not stall sync for minutes.
            if not self._wait_for_stable_file_size(part_path, min_bytes=512, timeout_s=45.0):
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
                timeout=90,
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

    def _resolve_basic_convert_mode(self) -> str:
        """Resolve conversion mode for basic sync: auto|direct_ffmpeg|pydub."""
        env_raw = (os.environ.get("VINTAGE_RADIO_CONVERT_MODE", "") or "").strip().lower()
        db_raw = (self.db.get_setting("basic_convert_mode", "") or "").strip().lower()
        mode = env_raw or db_raw or "auto"
        if mode in {"auto", "direct_ffmpeg", "pydub"}:
            return mode
        return "auto"

    def _register_active_ffmpeg_process(self, proc: subprocess.Popen[Any]) -> None:
        with self._active_proc_lock:
            self._active_ffmpeg_processes.add(proc)

    def _unregister_active_ffmpeg_process(self, proc: subprocess.Popen[Any]) -> None:
        with self._active_proc_lock:
            self._active_ffmpeg_processes.discard(proc)

    def _terminate_active_ffmpeg_processes(self) -> None:
        """Best-effort kill for all tracked ffmpeg child processes."""
        with self._active_proc_lock:
            procs = list(self._active_ffmpeg_processes)
        for proc in procs:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception:
                pass
            finally:
                self._unregister_active_ffmpeg_process(proc)

    def _convert_to_mp3_ffmpeg_direct(
        self,
        source_path: Path,
        target_path: Path,
        *,
        should_cancel: Optional[Callable[[], bool]] = None,
        conversion_profile: str = "dfplayer_safe",
    ) -> bool:
        """Convert via direct ffmpeg subprocess (no pydub wrapper)."""
        ffmpeg_exe = self._ffmpeg_exe or resolve_ffmpeg_executable()
        if not ffmpeg_exe:
            return False
        target_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = target_path.parent / f"{target_path.name}{self._SD_PART_SUFFIX}"
        try:
            part_path.unlink(missing_ok=True)
        except OSError:
            pass

        cmd = [
            ffmpeg_exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            # Keep each process single-threaded so N parallel jobs ~= N cores (no oversubscription).
            "-threads",
            "1",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-codec:a",
            "libmp3lame",
        ]
        if conversion_profile == "high_quality":
            cmd.extend(["-q:a", "2"])
        else:
            cmd.extend(["-ar", "44100", "-ac", "2", "-b:a", "128k"])
        cmd.extend([
            "-f",
            "mp3",
            str(part_path),
        ])

        proc: Optional[subprocess.Popen[Any]] = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._register_active_ffmpeg_process(proc)
            while True:
                if should_cancel and should_cancel():
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    return False
                rc = proc.poll()
                if rc is not None:
                    break
                time.sleep(0.15)

            if proc.returncode != 0:
                try:
                    err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="ignore")
                    if err.strip():
                        print(f"ffmpeg conversion failed for {source_path.name}: {err[:300]}")
                except Exception:
                    print(f"ffmpeg conversion failed for {source_path.name}")
                try:
                    part_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False

            if not self._wait_for_stable_file_size(part_path, min_bytes=512, timeout_s=45.0):
                print(f"ffmpeg output did not stabilize for {source_path.name}")
                try:
                    part_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False
            self._atomic_replace_written_file(part_path, target_path)
            return True
        except Exception as e:
            print(f"ffmpeg conversion error for {source_path.name}: {e}")
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        finally:
            if proc is not None:
                self._unregister_active_ffmpeg_process(proc)

    def _convert_to_mp3(
        self,
        source_path: Path,
        target_path: Path,
        *,
        should_cancel: Optional[Callable[[], bool]] = None,
        mode: Optional[str] = None,
        conversion_profile: str = "dfplayer_safe",
    ) -> bool:
        """
        Convert audio file to MP3 format for DFPlayer Mini compatibility.
        Supports: FLAC, WAV, OGG, M4A, AAC, and other formats.
        Prefers pydub/ffmpeg for most formats (faster for bulk WAV), keeps
        VLC-first for FLAC edge cases.
        Returns True if successful, False otherwise.
        """
        source_ext = source_path.suffix.lower()
        ffmpeg_available = self._check_ffmpeg()
        force_ffmpeg_only = (os.environ.get("VINTAGE_RADIO_FORCE_FFMPEG", "").strip() == "1")
        convert_mode = (mode or self._resolve_basic_convert_mode()).strip().lower()
        if convert_mode not in {"auto", "direct_ffmpeg", "pydub"}:
            convert_mode = "auto"
        vlc_available = (not force_ffmpeg_only) and self._check_vlc()
        prefer_vlc_first = source_ext == ".flac"

        if should_cancel and should_cancel():
            return False

        def _try_direct_ffmpeg() -> bool:
            if not ffmpeg_available:
                return False
            return self._convert_to_mp3_ffmpeg_direct(
                source_path,
                target_path,
                should_cancel=should_cancel,
                conversion_profile=conversion_profile,
            )

        def _try_pydub() -> bool:
            if not PYDUB_AVAILABLE or not ffmpeg_available:
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
                _p_base = (
                    ["-q:a", "2"]
                    if conversion_profile == "high_quality"
                    else ["-ar", "44100", "-ac", "2", "-b:a", "128k"]
                )
                audio.export(
                    str(part_path),
                    format="mp3",
                    bitrate="192k" if conversion_profile == "high_quality" else "128k",
                    parameters=["-threads", "1"] + _p_base,
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
                        audio.export(
                            str(part_path),
                            format="mp3",
                            bitrate="192k" if conversion_profile == "high_quality" else "128k",
                        )
                        self._atomic_replace_written_file(part_path, target_path)
                        return True
                    except Exception as e2:
                        print(f"Alternative FLAC conversion also failed for {source_path.name}: {e2}")
                        try:
                            part_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                return False

        if convert_mode == "direct_ffmpeg":
            if _try_direct_ffmpeg():
                return True
            if not force_ffmpeg_only and vlc_available:
                return self._convert_to_mp3_vlc(source_path, target_path)
            return _try_pydub()

        if convert_mode == "pydub":
            if _try_pydub():
                return True
            if _try_direct_ffmpeg():
                return True
            if not force_ffmpeg_only and vlc_available:
                return self._convert_to_mp3_vlc(source_path, target_path)
            return False

        if prefer_vlc_first:
            if vlc_available and self._convert_to_mp3_vlc(source_path, target_path):
                return True
            if _try_direct_ffmpeg():
                return True
            return _try_pydub()

        if _try_direct_ffmpeg():
            return True
        if _try_pydub():
            return True
        if vlc_available:
            if self._convert_to_mp3_vlc(source_path, target_path):
                return True
            print(f"VLC conversion failed for {source_path.name}")
        return False

    def _basic_convert_workers_auto(self, total_jobs: int) -> Tuple[int, str]:
        """Pick parallel conversion count from logical CPU count + installed RAM (no model sniffing).

        Uses only ``os.cpu_count()`` and ``psutil.virtual_memory().total`` — safe on all platforms.
        Tiers keep weaker machines conservative; high RAM + many threads allows ~2× logical CPUs
        (capped) when FFmpeg runs with ``-threads 1`` per process.
        """
        n = max(1, os.cpu_count() or 2)
        try:
            ram_gb = float(psutil.virtual_memory().total) / (1024.0**3)
        except Exception:
            ram_gb = 16.0

        if ram_gb >= 32.0 and n >= 8:
            w = min(32, n * 2, total_jobs)
            tier = "workstation (<=2x logical CPUs, RAM>=32 GiB)"
        elif ram_gb >= 16.0 and n >= 4:
            w = min(16, n, total_jobs)
            tier = "balanced (<=1x logical CPU, RAM>=16 GiB)"
        elif ram_gb >= 8.0:
            w = min(12, n, total_jobs)
            tier = "modest (RAM>=8 GiB)"
        else:
            w = min(6, max(1, (n + 1) // 2), total_jobs)
            tier = "conservative (low RAM)"

        return max(1, w), tier

    def _resolve_basic_convert_workers(self, total_jobs: int) -> Tuple[int, str]:
        """Resolve conversion worker count with env/db override and auto hardware tiers.

        Returns ``(worker_count, note)`` for session logging (Phase 1b).
        """
        # Priority: env var > DB setting > auto hardware tier.
        env_raw = (os.environ.get("VINTAGE_RADIO_CONVERT_WORKERS", "") or "").strip()
        db_raw = (self.db.get_setting("basic_convert_workers", "") or "").strip()
        raw = env_raw or db_raw
        if raw:
            try:
                val = int(raw)
                return max(1, min(64, val)), "manual (env or basic_convert_workers)"
            except ValueError:
                pass
        w, tier = self._basic_convert_workers_auto(total_jobs)
        n = os.cpu_count() or "?"
        return w, f"auto: {tier}; logical_cpus={n}"

    def _library_cache_fingerprint(self) -> str:
        """Stable short id for this library (database file) for on-disk cache names."""
        try:
            raw = str(self.db.db_path.resolve()).encode("utf-8", errors="replace")
        except Exception:
            raw = str(self.db.db_path).encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()[:16]

    def _basic_sync_mp3_cache_dir(
        self,
        conversion_profile: str,
        convert_mode: str,
    ) -> Path:
        """Persistent host cache for converted MP3s (per library + encode settings).

        Stored under the OS user cache dir (e.g. ``%LOCALAPPDATA%\\Vintage Radio\\Cache``
        on Windows) so full SD syncs can skip re-encoding when source hash/size matches.
        """
        try:
            import platformdirs

            base = Path(platformdirs.user_cache_dir("Vintage Radio", appauthor=False))
        except Exception:
            base = Path.home() / ".cache" / "Vintage Radio"
        safe = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            f"{conversion_profile}_{convert_mode}",
        ).strip("_") or "default"
        root = base / "basic_sync_mp3" / self._library_cache_fingerprint() / safe
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return root

    def clear_basic_sync_mp3_cache_for_library(self) -> Tuple[bool, str]:
        """Delete all locally cached converted MP3s for this library (all profiles/modes).

        Used when the user wants a "super clean" install: SD wipe plus full re-encode
        with no reuse of host-side cache files.
        """
        try:
            import platformdirs

            base = Path(platformdirs.user_cache_dir("Vintage Radio", appauthor=False))
        except Exception:
            base = Path.home() / ".cache" / "Vintage Radio"
        root = base / "basic_sync_mp3" / self._library_cache_fingerprint()
        if not root.is_dir():
            return True, ""
        try:
            shutil.rmtree(root)
            return True, ""
        except OSError as e:
            return False, str(e)

    def prefetch_basic_conversion_cache(
        self,
        *,
        song_ids: Optional[List[int]] = None,
        conversion_profile: str = "dfplayer_safe",
        dfplayer_eq: str = "normal",
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Convert tracks into the host MP3 cache while idle (returns newly converted count).

        Skips tracks already cached, source MP3s matching the profile, and missing files.
        """
        _ = dfplayer_eq  # reserved for future EQ-aware cache keys
        convert_mode = self._resolve_basic_convert_mode()
        force_ffmpeg_only = os.environ.get("VINTAGE_RADIO_FORCE_FFMPEG", "").strip() == "1"
        vlc_available = (not force_ffmpeg_only) and self._check_vlc()
        ffmpeg_available = self._check_ffmpeg()
        if convert_mode == "pydub":
            can_convert = vlc_available or (ffmpeg_available and PYDUB_AVAILABLE)
        else:
            can_convert = vlc_available or ffmpeg_available
        if not can_convert:
            return 0

        cache_root = self._basic_sync_mp3_cache_dir(conversion_profile, convert_mode)
        songs: List[Any] = []
        if song_ids is not None:
            rows = self.db.get_songs_by_ids(song_ids)
            songs.extend(rows)
        else:
            seen: set[int] = set()
            for station in self.db.list_basic_stations():
                for song in self.db.list_basic_station_songs(station["id"]):
                    sid = int(song["id"])
                    if sid not in seen:
                        seen.add(sid)
                        songs.append(song)

        converted = 0
        for song in songs:
            if should_stop and should_stop():
                break
            fp_raw = (song["file_path"] or "").strip()
            if not fp_raw:
                continue
            file_path = Path(fp_raw)
            if not file_path.is_file():
                continue
            source_ext = file_path.suffix.lower()
            if source_ext == ".mp3" and mp3_matches_conversion_profile(
                file_path, conversion_profile
            ):
                continue
            cache_key = self._cache_key_for_song(song, file_path)
            if cache_key is None:
                continue
            cache_mp3 = cache_root / f"{cache_key[0]}_{cache_key[1]}.mp3"
            if cache_mp3.is_file():
                try:
                    if file_path.stat().st_mtime <= cache_mp3.stat().st_mtime:
                        continue
                except OSError:
                    continue
            if self._convert_to_mp3(
                file_path,
                cache_mp3,
                mode=convert_mode,
                conversion_profile=conversion_profile,
            ):
                converted += 1
        return converted

    def _resolve_basic_sd_copy_workers(self, total_jobs: int) -> int:
        """Parallel copy workers for Phase 2 (USB/SD is often slower than conversion)."""
        env_raw = (os.environ.get("VINTAGE_RADIO_SD_COPY_WORKERS", "") or "").strip()
        db_raw = (self.db.get_setting("basic_sd_copy_workers", "") or "").strip()
        raw = env_raw or db_raw
        if raw:
            try:
                return max(1, min(32, int(raw)))
            except ValueError:
                pass
        # Default: more threads than before; cap to reduce FAT/USB contention on weak readers.
        return max(2, min(12, total_jobs, max(4, (os.cpu_count() or 4))))

    def get_basic_broken_source_paths(self) -> List[Dict[str, str]]:
        """Return tracks whose source file no longer exists at the stored path.

        Each entry: ``{"title": ..., "path": ..., "station": ...}``.
        Used to warn the user before syncing so they can fix or remove tracks.
        """
        broken: List[Dict[str, str]] = []
        try:
            stations = self.db.list_basic_stations()
        except Exception:
            return broken
        for station in stations:
            station_name = (station["name"] or "").strip() or f"Station {station['folder_number']}"
            try:
                tracks = self.db.list_basic_station_songs(station["id"])
            except Exception:
                continue
            for song in tracks:
                fp_raw = (song["file_path"] or "").strip()
                if not fp_raw:
                    continue
                try:
                    if not Path(fp_raw).exists():
                        title = (
                            (song["title"] or "").strip()
                            or (song["original_filename"] or "").strip()
                            or Path(fp_raw).name
                        )
                        broken.append({"title": title, "path": fp_raw, "station": station_name})
                except (OSError, ValueError):
                    pass
        return broken

    def _cache_key_for_song(self, song: Any, file_path: Path) -> Optional[Tuple[str, int]]:
        """Return a stable cache key for one source track."""
        try:
            file_hash = str(song["file_hash"] or "").strip()
            if not file_hash:
                file_hash = compute_file_hash(file_path)
            size_raw = song["file_size"]
            if size_raw is None:
                size_raw = file_path.stat().st_size
            return file_hash, int(size_raw)
        except Exception:
            return None

    def _try_copy_from_cache(
        self,
        cache: Dict[Tuple[str, int], Path],
        cache_key: Optional[Tuple[str, int]],
        target_path: Path,
    ) -> bool:
        if cache_key is None:
            return False
        cached_path = cache.get(cache_key)
        if cached_path is None or not cached_path.exists():
            return False
        try:
            self._atomic_copy2(cached_path, target_path)
            return True
        except Exception:
            return False

    def _remember_cache_entry(
        self,
        cache: Dict[Tuple[str, int], Path],
        cache_key: Optional[Tuple[str, int]],
        target_path: Path,
    ) -> None:
        if cache_key is None:
            return
        cache[cache_key] = target_path

    def sync_library_basic(
        self,
        sd_root: Path,
        force_clean: bool = False,
        progress_callback: Optional[callable] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        conversion_profile: str = "dfplayer_safe",
        dfplayer_eq: str = "normal",
        copy_destination_label: str = "SD card",
        sync_log_prefix: str = "Basic SD",
        use_conversion_cache: bool = True,
    ) -> Dict[str, object]:
        """Sync basic-mode stations to SD card.

        Each station maps to a DFPlayer folder (01-99). Tracks are duplicated
        across folders if they appear in multiple stations. The DFPlayer firmware
        discovers layout by querying the module directly; the app also writes a
        hidden ``.sync_manifest.json`` at the SD root (for host-side mismatch checks),
        which the DFPlayer ignores.
        """
        preserved_volume_label = ""
        if force_clean:
            root_in = Path(sd_root)
            hint = (
                (self.db.get_setting("sd_volume_label") or "").strip()
                or (self.db.get_setting("sd_label") or "").strip()
            )
            raw = _resolve_mount_volume_name(root_in, hint)
            preserved_volume_label = (
                _sanitize_fat_volume_label(raw)
                or _sanitize_fat_volume_label(hint)
                or SYNC_TARGET_VOLUME_LABEL
            )
            sd_root = self._clean_install_purge(
                root_in,
                progress_callback=progress_callback,
                volume_label=preserved_volume_label,
            )

        if conversion_profile not in {"dfplayer_safe", "high_quality"}:
            conversion_profile = "dfplayer_safe"
        if dfplayer_eq not in {"normal", "pop", "rock", "jazz", "classic", "bass"}:
            dfplayer_eq = "normal"
        stations = self.db.list_basic_stations()
        if not stations:
            if progress_callback:
                progress_callback(1, 1, "No stations to sync")
            self._copy_am_wav_to_dfplayer_sd(sd_root)
            self._write_advanced_runtime_sd_config(
                sd_root,
                dfplayer_eq=dfplayer_eq,
                conversion_profile=conversion_profile,
            )
            n = self.remove_hidden_junk_from_sd(sd_root)
            if n:
                print(
                    f"Basic SD sync: removed {n} hidden/junk item(s) "
                    "(macOS ._*, .DS_Store, __MACOSX, etc.)"
                )
            out: Dict[str, object] = {
                "copied": 0,
                "skipped": 0,
                "sd_root": str(sd_root),
                "conversion_failures": [],
            }
            if preserved_volume_label:
                out["preserved_volume_label"] = preserved_volume_label
            return out

        vlc_available = self._check_vlc()
        ffmpeg_available = self._check_ffmpeg()
        force_ffmpeg_only = (os.environ.get("VINTAGE_RADIO_FORCE_FFMPEG", "").strip() == "1")
        convert_mode = self._resolve_basic_convert_mode()
        if force_ffmpeg_only:
            vlc_available = False
        # direct_ffmpeg works without pydub; pydub mode requires pydub+ffmpeg.
        if convert_mode == "pydub":
            can_convert = vlc_available or (ffmpeg_available and PYDUB_AVAILABLE)
        else:
            can_convert = vlc_available or ffmpeg_available

        ephemeral_cache_root: Optional[Path] = None
        try:
            if use_conversion_cache:
                conversion_cache_root = self._basic_sync_mp3_cache_dir(
                    conversion_profile, convert_mode
                )
                print(f"Basic sync MP3 cache directory: {conversion_cache_root}")
            else:
                ephemeral_cache_root = Path(
                    tempfile.mkdtemp(prefix="vr_sync_ephemeral_")
                )
                conversion_cache_root = ephemeral_cache_root
                print(
                    "Basic sync MP3 cache: disabled — using ephemeral temp conversions only"
                )
            print(
                "Basic sync conversion backend: "
                f"ffmpeg={'yes' if ffmpeg_available else 'no'}"
                f"{f' ({self._ffmpeg_exe})' if self._ffmpeg_exe else ''}, "
                f"vlc={'yes' if vlc_available else 'no'}, "
                f"force_ffmpeg_only={'yes' if force_ffmpeg_only else 'no'}, "
                f"mode={convert_mode}, profile={conversion_profile}"
            )

            return self._sync_library_basic_impl(
                sd_root=sd_root,
                force_clean=force_clean,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
                conversion_profile=conversion_profile,
                dfplayer_eq=dfplayer_eq,
                copy_destination_label=copy_destination_label,
                sync_log_prefix=sync_log_prefix,
                use_conversion_cache=use_conversion_cache,
                conversion_cache_root=conversion_cache_root,
                can_convert=can_convert,
                convert_mode=convert_mode,
                preserved_volume_label=preserved_volume_label,
                stations=stations,
            )
        finally:
            if ephemeral_cache_root is not None:
                shutil.rmtree(ephemeral_cache_root, ignore_errors=True)

    def _sync_library_basic_impl(
        self,
        *,
        sd_root: Path,
        force_clean: bool,
        progress_callback: Optional[callable],
        should_cancel: Optional[Callable[[], bool]],
        conversion_profile: str,
        dfplayer_eq: str,
        copy_destination_label: str,
        sync_log_prefix: str,
        use_conversion_cache: bool,
        conversion_cache_root: Path,
        can_convert: bool,
        convert_mode: str,
        preserved_volume_label: str,
        stations: List[Any],
    ) -> Dict[str, object]:
        """Inner basic sync implementation (see ``sync_library_basic``)."""
        station_tracks: List[Tuple[int, List]] = []
        total_tracks = 0
        for station in stations:
            tracks = self.db.list_basic_station_songs(station["id"])
            station_tracks.append((station["folder_number"], tracks))
            total_tracks += len(tracks)

        copied = 0
        skipped = 0
        converted = 0
        cache_copied = 0
        direct_mp3_copied = 0
        processed_tracks = 0
        conversion_failures: List[Dict[str, str]] = []
        missing_source_paths: List[Dict[str, str]] = []
        sync_start = time.monotonic()
        last_progress_emit = 0.0

        manifest_stations: Dict[str, dict] = {}
        old_manifest_stations, manifest_trusted, stored_profile, stored_eq, manifest_synced_at = (
            self._load_basic_sync_baseline(sd_root, force_clean=force_clean)
        )
        settings_match = (
            (stored_profile is None or stored_profile == conversion_profile)
            and (stored_eq is None or stored_eq == dfplayer_eq)
        )
        conversion_cache: Dict[Tuple[str, int], Path] = {}
        deferred_cache_copy_jobs: List[Tuple[Path, Path]] = []

        def _raise_if_cancelled() -> None:
            if should_cancel and should_cancel():
                self._terminate_active_ffmpeg_processes()
                raise RuntimeError("Sync cancelled by user.")
        station_names_by_folder = {
            int(st["folder_number"]): (st["name"] or "").strip()
            for st in stations
        }

        def _emit_prep_progress(message: str) -> None:
            nonlocal last_progress_emit
            if not progress_callback:
                return
            now = time.monotonic()
            prep_step = 1 if total_tracks <= 500 else 10
            prep_interval = 0.0 if total_tracks <= 500 else 0.12
            if (processed_tracks % prep_step) != 0 and (now - last_progress_emit) < prep_interval:
                return
            progress_callback(
                processed_tracks,
                total_tracks,
                f"{message} ({processed_tracks}/{total_tracks})",
            )
            last_progress_emit = now

        # ── Phase 1: Prepare copy jobs + run conversions (sequential) ──
        # Phase 1a scans + schedules conversions; Phase 1b executes conversions.
        copy_jobs: List[Tuple[Path, Path, str]] = []  # (local_src, sd_target, job_type)
        convert_jobs: List[Tuple[Path, Path, Path, Optional[Tuple[str, int]]]] = []
        failed_cache_paths: set[Path] = set()

        used_folders: set = set()
        for folder_num, tracks in station_tracks:
            _raise_if_cancelled()
            station_start = time.monotonic()
            station_to_copy = 0
            station_skipped = 0
            station_queued_convert = 0
            used_folders.add(folder_num)
            folder_key = f"{folder_num:02d}"
            folder_path = sd_root / folder_key
            folder_path.mkdir(parents=True, exist_ok=True)
            valid_track_nums: set = set()
            manifest_tracks: Dict[str, dict] = {}

            station_name = station_names_by_folder.get(folder_num, "")

            for track_order, song in enumerate(tracks, start=1):
                _raise_if_cancelled()
                valid_track_nums.add(track_order)
                file_path = Path(song["file_path"])
                title = song["title"] or song["original_filename"]
                _emit_prep_progress(f"Preparing {folder_key}: {title}")

                if not file_path.exists():
                    title_for_log = song["title"] or song["original_filename"] or file_path.name
                    print(f"Source file missing, skipping: {file_path}")
                    missing_source_paths.append({
                        "title": title_for_log,
                        "path": str(file_path),
                        "station": station_name,
                    })
                    skipped += 1
                    station_skipped += 1
                    processed_tracks += 1
                    continue

                target_path = folder_path / f"{track_order:03d}.mp3"
                source_ext = file_path.suffix.lower()
                cache_key = self._cache_key_for_song(song, file_path)
                descriptor = self._library_track_descriptor(song, file_path)
                manifest_tracks[f"{track_order:03d}"] = {
                    "source_name": descriptor["source_name"],
                    "source_size": descriptor["source_size"],
                    "source_hash": descriptor.get("source_hash"),
                }

                old_folder = old_manifest_stations.get(folder_key, {})
                old_entry = (old_folder.get("tracks") or {}).get(f"{track_order:03d}")
                if self._basic_track_can_skip(
                    force_clean=force_clean,
                    manifest_trusted=manifest_trusted,
                    settings_match=settings_match,
                    old_entry=old_entry,
                    descriptor=descriptor,
                    target_path=target_path,
                    source_path=file_path,
                    source_ext=source_ext,
                    conversion_profile=conversion_profile,
                    source_duration=song["duration"],
                    manifest_synced_at=manifest_synced_at,
                ):
                    skipped += 1
                    processed_tracks += 1
                    continue

                try:
                    cached_src = conversion_cache.get(cache_key) if cache_key else None
                    if cached_src is not None:
                        if cached_src.exists():
                            copy_jobs.append((cached_src, target_path, "cache"))
                            station_to_copy += 1
                        else:
                            # Same song in another station: wait until Phase 1b finishes
                            # writing the shared cache file (avoid Phase 2 racing on missing path).
                            deferred_cache_copy_jobs.append((cached_src, target_path))
                            station_to_copy += 1
                    elif source_ext == ".mp3" and mp3_matches_conversion_profile(
                        file_path, conversion_profile
                    ):
                        copy_jobs.append((file_path, target_path, "direct_mp3"))
                        self._remember_cache_entry(conversion_cache, cache_key, file_path)
                        station_to_copy += 1
                    elif can_convert:
                        cache_mp3: Optional[Path] = None
                        if cache_key is not None:
                            cache_mp3 = conversion_cache_root / f"{cache_key[0]}_{cache_key[1]}.mp3"
                        if (
                            use_conversion_cache
                            and cache_mp3 is not None
                            and cache_mp3.exists()
                        ):
                            copy_jobs.append((cache_mp3, target_path, "cache"))
                            station_to_copy += 1
                            self._remember_cache_entry(conversion_cache, cache_key, cache_mp3)
                        else:
                            if cache_mp3 is None:
                                tmp_dir = conversion_cache_root / "_tmp"
                                tmp_dir.mkdir(parents=True, exist_ok=True)
                                cache_mp3 = tmp_dir / f"nohash_{folder_key}_{track_order:03d}.mp3"
                            # Reserve cache key immediately so duplicates queue behind one conversion.
                            self._remember_cache_entry(conversion_cache, cache_key, cache_mp3)
                            convert_jobs.append((file_path, cache_mp3, target_path, cache_key))
                            station_to_copy += 1
                            station_queued_convert += 1
                    elif source_ext == ".mp3":
                        print(
                            f"Warning: cannot re-encode {file_path.name} for profile "
                            f"{conversion_profile}; copying as-is"
                        )
                        copy_jobs.append((file_path, target_path, "direct_mp3"))
                        self._remember_cache_entry(conversion_cache, cache_key, file_path)
                        station_to_copy += 1
                    else:
                        print(f"Cannot convert {file_path.name} (no converter)")
                        skipped += 1
                        station_skipped += 1
                except OSError as e:
                    print(f"Error preparing {file_path.name}: {e}")
                    skipped += 1
                    station_skipped += 1
                processed_tracks += 1

            manifest_stations[folder_key] = {
                "name": station_name,
                "tracks": manifest_tracks,
            }

            # Remove stale tracks (safe before copy phase — stale slots != valid slots).
            try:
                for item in folder_path.iterdir():
                    if item.suffix.lower() == ".mp3" and item.stem.isdigit():
                        if int(item.stem) not in valid_track_nums:
                            print(f"Removing stale track: {item}")
                            try:
                                item.unlink(missing_ok=True)
                            except OSError as e:
                                print(f"Warning: could not remove stale track {item}: {e}")
            except OSError as e:
                print(f"Warning: could not scan folder for stale tracks {folder_path}: {e}")

            station_elapsed = time.monotonic() - station_start
            print(
                f"Prepare station {folder_key} '{station_name or folder_key}': "
                f"{station_to_copy} to copy, {station_skipped} skipped, "
                f"{station_queued_convert} queued for conversion in {station_elapsed:.1f}s"
            )

        prep_elapsed = time.monotonic() - sync_start
        print(
            f"Phase 1a (scan) done: {len(copy_jobs)} provisional copy jobs, "
            f"{len(convert_jobs)} queued conversions, {skipped} skipped in {prep_elapsed:.1f}s"
        )

        # ── Phase 1b: Execute local conversions (parallel) ──
        if convert_jobs:
            _raise_if_cancelled()
            convert_start = time.monotonic()
            max_convert_workers, _convert_workers_note = self._resolve_basic_convert_workers(
                len(convert_jobs)
            )
            done_convert = 0
            print(
                f"Phase 1b conversion: {max_convert_workers} workers — {_convert_workers_note}; "
                f"VINTAGE_RADIO_CONVERT_WORKERS env={os.environ.get('VINTAGE_RADIO_CONVERT_WORKERS', '')!r}"
            )
            if progress_callback:
                progress_callback(
                    0,
                    len(convert_jobs),
                    f"Converting audio ({len(convert_jobs)} files, {max_convert_workers} workers)...",
                )

            with ThreadPoolExecutor(max_workers=max_convert_workers) as pool:
                futures = {
                    pool.submit(
                        self._convert_to_mp3,
                        src,
                        cache_mp3,
                        should_cancel=should_cancel,
                        mode=convert_mode,
                        conversion_profile=conversion_profile,
                    ): (src, cache_mp3, target, cache_key)
                    for (src, cache_mp3, target, cache_key) in convert_jobs
                }
                for future in as_completed(futures):
                    _raise_if_cancelled()
                    src, cache_mp3, target, cache_key = futures[future]
                    done_convert += 1
                    ok = False
                    convert_exc: Optional[Exception] = None
                    try:
                        ok = bool(future.result())
                    except Exception as e:
                        ok = False
                        convert_exc = e
                    if ok:
                        converted += 1
                        # Actual SD copy job enters queue only after local conversion succeeds.
                        copy_jobs.append((cache_mp3, target, "converted"))
                        self._remember_cache_entry(conversion_cache, cache_key, cache_mp3)
                    else:
                        failed_cache_paths.add(cache_mp3)
                        skipped += 1
                        err_text = (
                            str(convert_exc).strip()
                            if convert_exc is not None
                            else "conversion failed (see log for details)"
                        )
                        conversion_failures.append(
                            {
                                "path": str(src),
                                "name": src.name,
                                "error": err_text[:800],
                            }
                        )
                        print(f"Failed to convert {src.name}: {err_text}")

                    _conv_step = _basic_sync_progress_step_interval(len(convert_jobs), large_step=50)
                    if progress_callback and (
                        done_convert % _conv_step == 0
                        or done_convert == len(convert_jobs)
                        or len(convert_jobs) <= 50
                    ):
                        elapsed = time.monotonic() - convert_start
                        rate = done_convert / max(0.001, elapsed)
                        remaining = len(convert_jobs) - done_convert
                        eta = int(remaining / rate) if rate > 0 else 0
                        progress_callback(
                            done_convert,
                            len(convert_jobs),
                            f"Converting audio ({done_convert}/{len(convert_jobs)}, {rate:.1f}/s, ETA ~{eta}s)",
                        )

            # Remove copy jobs that depend on failed conversions.
            if failed_cache_paths:
                copy_jobs = [
                    (src, dst, kind)
                    for (src, dst, kind) in copy_jobs
                    if src not in failed_cache_paths
                ]

            convert_elapsed = time.monotonic() - convert_start
            print(
                f"Phase 1b (convert) done: {converted}/{len(convert_jobs)} converted "
                f"in {convert_elapsed:.1f}s ({converted / max(0.001, convert_elapsed):.1f}/s, "
                f"{max_convert_workers} workers)"
            )

        # Duplicate tracks across stations: copy shared cache file to extra targets now.
        for _src, _dst in deferred_cache_copy_jobs:
            copy_jobs.append((_src, _dst, "cache"))

        # ── Phase 2: Copy files to SD card (parallel) ──
        total_copies = len(copy_jobs)
        copies_done = 0
        copy_phase_start = time.monotonic()
        _copy_lock = threading.Lock()

        if total_copies > 0:
            _raise_if_cancelled()
            if progress_callback:
                progress_callback(
                    0,
                    total_copies,
                    f"Copying to {copy_destination_label} (0/{total_copies})...",
                )

            num_workers = self._resolve_basic_sd_copy_workers(total_copies)
            print(
                f"Phase 2 copy workers: {num_workers} "
                f"(override env VINTAGE_RADIO_SD_COPY_WORKERS="
                f"{os.environ.get('VINTAGE_RADIO_SD_COPY_WORKERS', '')!r})"
            )

            with ThreadPoolExecutor(max_workers=num_workers) as pool:
                futures = {}
                for job_src, job_dst, job_type in copy_jobs:
                    futures[pool.submit(self._atomic_copy2, job_src, job_dst)] = (
                        job_src,
                        job_dst,
                        job_type,
                    )

                for future in as_completed(futures):
                    _raise_if_cancelled()
                    job_src, job_dst, job_type = futures[future]
                    try:
                        future.result()
                        with _copy_lock:
                            copied += 1
                            copies_done += 1
                            if job_type == "cache":
                                cache_copied += 1
                            elif job_type == "direct_mp3":
                                direct_mp3_copied += 1
                    except Exception as e:
                        with _copy_lock:
                            copies_done += 1
                            skipped += 1
                        print(f"Copy error: {job_src.name} -> {job_dst}: {e}")

                    if progress_callback:
                        elapsed = time.monotonic() - copy_phase_start
                        rate = copies_done / max(0.001, elapsed)
                        remaining = total_copies - copies_done
                        eta = int(remaining / rate) if rate > 0 and remaining > 0 else 0
                        progress_callback(
                            copies_done,
                            total_copies,
                            f"Copying to {copy_destination_label} ({copies_done}/{total_copies}, "
                            f"{job_src.name}, {rate:.1f} files/s"
                            + (f", ETA ~{eta}s" if eta > 0 else "")
                            + ")",
                        )

            copy_elapsed = time.monotonic() - copy_phase_start
            print(
                f"Phase 2 (copy) done: {copies_done} files in {copy_elapsed:.1f}s "
                f"({copies_done / max(0.001, copy_elapsed):.1f} files/s, "
                f"{num_workers} threads)"
            )

        # ── Phase 3: Cleanup stale station folders on SD ──
        self._remove_stale_numeric_sd_folders(
            sd_root,
            used_folders,
            progress_callback=progress_callback,
        )
        if progress_callback:
            progress_callback(0, 0, "Copying AM radio sound...")
        self._copy_am_wav_to_dfplayer_sd(sd_root)
        self._write_advanced_runtime_sd_config(
            sd_root,
            dfplayer_eq=dfplayer_eq,
            conversion_profile=conversion_profile,
        )

        if progress_callback:
            progress_callback(1, 1, f"{sync_log_prefix} sync complete.")
        self._remove_legacy_vintage_radio_folder_on_dfplayer_sd(sd_root)
        n = self.remove_hidden_junk_from_sd(sd_root)
        if n:
            print(
                f"Basic SD sync: removed {n} hidden/junk item(s) "
                "(macOS ._*, .DS_Store, __MACOSX, etc.)"
            )

        self._write_sync_manifest(
            sd_root,
            manifest_stations,
            conversion_profile=conversion_profile,
            dfplayer_eq=dfplayer_eq,
        )

        total_elapsed = time.monotonic() - sync_start
        rate = (total_copies / total_elapsed) if total_elapsed > 0 else 0.0
        print(
            f"{sync_log_prefix} sync complete: {copied} copied, {skipped} skipped across "
            f"{len(stations)} stations in {total_elapsed:.1f}s ({rate:.1f} tracks/s). "
            f"direct_mp3={direct_mp3_copied}, converted={converted}, "
            f"cache_copied={cache_copied}"
        )
        out_end: Dict[str, object] = {
            "copied": copied,
            "skipped": skipped,
            "sd_root": str(sd_root),
            "conversion_failures": conversion_failures,
            "missing_source_paths": missing_source_paths,
        }
        if preserved_volume_label:
            out_end["preserved_volume_label"] = preserved_volume_label
        return out_end

    @staticmethod
    def _remove_stale_numeric_sd_folders(
        sd_root: Path,
        used_folders: set,
        *,
        progress_callback=None,
        progress_total: int | None = None,
    ) -> int:
        """Delete numbered station folders on SD that are no longer in the library."""
        stale = sorted(
            (
                item
                for item in sd_root.iterdir()
                if item.is_dir() and item.name.isdigit() and int(item.name) not in used_folders
            ),
            key=lambda p: p.name,
        )
        n = len(stale)
        if not stale:
            if progress_callback:
                progress_callback(0, 0, "No stale folders to remove.")
            return 0
        removed = 0
        for i, item in enumerate(stale):
            if progress_callback:
                progress_callback(
                    i,
                    n,
                    f"Removing stale folder {item.name} ({i + 1}/{n})...",
                )
            print(f"Removing stale folder: {item}")
            shutil.rmtree(item, ignore_errors=True)
            removed += 1
        if progress_callback:
            progress_callback(n, n, f"Removed {removed} stale folder(s).")
        return removed

    # -- Sync manifest helpers ------------------------------------------------

    @staticmethod
    def _read_sd_runtime_config(sd_root: Path) -> Tuple[Optional[str], Optional[str]]:
        """Read ``advanced_runtime.json`` from *sd_root* if present."""
        cfg_path = sd_root / "advanced_runtime.json"
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return None, None
        if not isinstance(data, dict):
            return None, None
        profile = str(data.get("conversion_profile") or "").strip() or None
        eq = str(data.get("dfplayer_eq") or "").strip() or None
        return profile, eq

    def _load_basic_sync_baseline(
        self,
        sd_root: Path,
        *,
        force_clean: bool,
    ) -> Tuple[Dict[str, dict], bool, Optional[str], Optional[str], Optional[float]]:
        """Return ``(old_stations, manifest_trusted, stored_profile, stored_eq, synced_at_epoch)``."""
        if force_clean:
            return {}, False, None, None, None
        old_manifest = self._read_sync_manifest(sd_root)
        stations_raw = (old_manifest or {}).get("stations") if old_manifest else None
        runtime_profile, runtime_eq = self._read_sd_runtime_config(sd_root)
        synced_at_epoch = self._parse_manifest_synced_at(old_manifest)
        if not isinstance(stations_raw, dict) or not stations_raw:
            return {}, False, runtime_profile, runtime_eq, synced_at_epoch
        manifest_trusted = isinstance(old_manifest, dict) and old_manifest.get("version") == 1
        stored_profile = str(old_manifest.get("conversion_profile") or "").strip() or None
        stored_eq = str(old_manifest.get("dfplayer_eq") or "").strip() or None
        if stored_profile is None:
            stored_profile = runtime_profile
        if stored_eq is None:
            stored_eq = runtime_eq
        return stations_raw, manifest_trusted, stored_profile, stored_eq, synced_at_epoch

    @staticmethod
    def _parse_manifest_synced_at(manifest: Optional[dict]) -> Optional[float]:
        if not isinstance(manifest, dict):
            return None
        raw = manifest.get("synced_at")
        if not raw:
            return None
        try:
            import datetime

            dt = datetime.datetime.fromisoformat(str(raw))
            if dt.tzinfo is None:
                return dt.timestamp()
            return dt.timestamp()
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _library_track_descriptor(song: Any, file_path: Path) -> Dict[str, Any]:
        """Fingerprint a library track for manifest compare / skip decisions."""
        try:
            src_sz = int(song["file_size"]) if song["file_size"] else int(file_path.stat().st_size)
        except (OSError, TypeError, ValueError):
            try:
                src_sz = int(file_path.stat().st_size)
            except OSError:
                src_sz = 0
        src_hash = str(song["file_hash"] or "").strip() or None
        return {
            "source_name": file_path.name,
            "source_size": src_sz,
            "source_hash": src_hash,
        }

    @staticmethod
    def _manifest_entry_matches_library(
        m_entry: dict,
        descriptor: Dict[str, Any],
        *,
        source_hash: str = "",
    ) -> bool:
        """True when a saved manifest slot describes the same library source."""
        if str(m_entry.get("source_name") or "") != descriptor["source_name"]:
            return False
        expected_size = m_entry.get("source_size")
        if expected_size is not None:
            try:
                if int(expected_size) != int(descriptor["source_size"]):
                    return False
            except (TypeError, ValueError):
                return False
        expected_hash = str(m_entry.get("source_hash") or "").strip()
        actual_hash = (source_hash or str(descriptor.get("source_hash") or "")).strip()
        if expected_hash and actual_hash:
            return expected_hash == actual_hash
        if expected_hash and not actual_hash:
            return False
        # Legacy manifest entry without hash: name + size match is enough; manifest
        # will be upgraded on the next successful copy pass.
        return True

    def _resolve_source_hash(self, source_path: Path, descriptor: Dict[str, Any]) -> str:
        return self._resolve_source_hash_static(source_path, descriptor)

    @staticmethod
    def _resolve_source_hash_static(source_path: Path, descriptor: Dict[str, Any]) -> str:
        h = str(descriptor.get("source_hash") or "").strip()
        if h:
            return h
        try:
            return compute_file_hash(source_path)
        except OSError:
            return ""

    def _basic_track_can_skip(
        self,
        *,
        force_clean: bool,
        manifest_trusted: bool,
        settings_match: bool,
        old_entry: Optional[dict],
        descriptor: Dict[str, Any],
        target_path: Path,
        source_path: Path,
        source_ext: str,
        conversion_profile: str,
        source_duration: Optional[float] = None,
        manifest_synced_at: Optional[float] = None,
    ) -> bool:
        """Return True when the SD slot already matches the library and can be left in place.

        Sync Changes compares the library to ``.sync_manifest.json`` on the SD card
        (fast, no per-file hashing). Full file verification runs only when the
        manifest is missing or the slot entry does not match the library.
        """
        _ = source_duration  # reserved for fallback paths if extended later
        if force_clean or not settings_match:
            return False
        try:
            target_size = target_path.stat().st_size
        except OSError:
            return False
        if target_size <= 0:
            return False

        # ── Fast path: manifest slot matches library (metadata-only) ──
        if manifest_trusted and old_entry:
            source_hash = str(descriptor.get("source_hash") or "").strip()
            if not source_hash:
                source_hash = self._resolve_source_hash(source_path, descriptor)
            if self._manifest_entry_matches_library(
                old_entry, descriptor, source_hash=source_hash
            ):
                if manifest_synced_at is not None:
                    try:
                        if source_path.stat().st_mtime > manifest_synced_at + 2.0:
                            return False
                    except OSError:
                        pass
                return True

        # ── Fallback: no manifest proof — verify SD file content ──
        if source_ext == ".mp3":
            try:
                if int(source_path.stat().st_size) != int(target_size):
                    return False
            except OSError:
                return False
            if not mp3_matches_conversion_profile(source_path, conversion_profile):
                return False
            if not mp3_matches_conversion_profile(target_path, conversion_profile):
                return False
            try:
                return compute_file_hash(source_path) == compute_file_hash(target_path)
            except OSError:
                return False

        return False

    @staticmethod
    def _local_manifest_path(sd_root: Path) -> Optional[Path]:
        """Return a machine-local cache path for the manifest keyed to *sd_root*.

        Used as a fallback when the SD card root is not writable (e.g. Windows
        permission restrictions immediately after a format).  Returns *None* on
        any error so callers can skip it gracefully.
        """
        try:
            import re
            import platformdirs
            cache_dir = Path(platformdirs.user_cache_dir("Vintage Radio"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            key = re.sub(r"[^A-Za-z0-9_-]", "_", str(sd_root.resolve()))[:80]
            return cache_dir / f"sd_manifest_{key}.json"
        except Exception:
            return None

    @staticmethod
    def _write_sync_manifest(
        sd_root: Path,
        stations: Dict[str, dict],
        *,
        conversion_profile: str = "dfplayer_safe",
        dfplayer_eq: str = "normal",
    ) -> None:
        """Persist a lightweight manifest after a basic-mode sync.

        Tries the SD card root first (works on macOS/Linux and most Windows
        configs). Falls back to a machine-local app cache so Windows permission
        restrictions on the drive root do not silently discard the manifest.
        """
        import datetime
        manifest = {
            "version": 1,
            "synced_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "conversion_profile": str(conversion_profile or "dfplayer_safe"),
            "dfplayer_eq": str(dfplayer_eq or "normal"),
            "stations": stations,
        }
        sd_path = sd_root / _SYNC_MANIFEST_NAME
        local_path = SDManager._local_manifest_path(sd_root)
        wrote_any = False
        for path in filter(None, [sd_path, local_path]):
            try:
                with path.open("w", encoding="utf-8") as fh:
                    json.dump(manifest, fh, separators=(",", ":"))
                wrote_any = True
            except OSError:
                pass
        if not wrote_any:
            print("Warning: could not write sync manifest to any location")

    @staticmethod
    def _read_sync_manifest(sd_root: Path) -> Optional[dict]:
        """Read the manifest written by a previous sync, or *None* if absent/corrupt.

        Checks the SD card root first (backward-compatible with cards synced
        on macOS), then falls back to the machine-local app cache.
        """
        sd_path = sd_root / _SYNC_MANIFEST_NAME
        local_path = SDManager._local_manifest_path(sd_root)
        for path in filter(None, [sd_path, local_path]):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and data.get("version") == 1:
                    return data
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return None

    _VALIDATE_MAX_ISSUES = 31

    def validate_basic_sd(self, sd_root: Path, reserved_folder: Optional[int] = 99) -> List[str]:
        """Compare basic-mode stations to DFPlayer folders on *sd_root*.

        Returns human-readable issue strings (empty if layout matches). Mirrors
        :meth:`sync_library_basic` naming: ``NN/001.mp3`` ...

        When a ``.sync_manifest.json`` is present (written by
        :meth:`sync_library_basic`), a **fast manifest-only** comparison is used
        that avoids per-file stat calls on the SD card.  This keeps startup
        responsive even for libraries with thousands of tracks.

        Falls back to per-file heuristics only when the manifest is absent.
        """
        msgs: List[str] = []
        if not sd_root.is_dir():
            return ["SD root is missing or not a directory."]
        try:
            stations = self.db.list_basic_stations()
        except Exception:
            return ["Could not read stations from the database."]

        manifest = self._read_sync_manifest(sd_root)
        manifest_stations = (manifest or {}).get("stations", {})

        # ── Fast path: manifest-only comparison (no SD file I/O) ──
        if manifest_stations:
            return self._validate_basic_sd_manifest_fast(
                stations, manifest_stations, reserved_folder,
            )

        # ── Slow path: per-file heuristics (no manifest on card) ──
        cap = self._VALIDATE_MAX_ISSUES
        for st in stations:
            if len(msgs) >= cap:
                break
            fid = int(st["id"])
            fn = int(st["folder_number"])
            name = (st["name"] or "").strip() or f"Station {fn}"
            if reserved_folder is not None and fn == reserved_folder:
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
                    if len(msgs) >= cap:
                        break
            for idx in sorted(mp3_set):
                if len(msgs) >= cap:
                    break
                if idx > n:
                    msgs.append(
                        f'Station "{name}": extra file {idx:03d}.mp3 on SD '
                        f"(app has only {n} tracks in folder {folder_key})."
                    )
            if len(msgs) >= cap:
                break
            for order, song in enumerate(tracks, start=1):
                if len(msgs) >= cap:
                    break
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
                    continue
                t = song["title"] or song["original_filename"] or f"track {order}"

                try:
                    if fp.suffix.lower() == ".mp3":
                        if fp.stat().st_size != slot.stat().st_size:
                            msgs.append(
                                f'Station "{name}": {order:03d}.mp3 on SD does not match '
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
                                                f'Station "{name}": {order:03d}.mp3 on SD '
                                                f'looks out of sync with "{t}" (duration differs — '
                                                f"track order may have changed — sync to SD)."
                                            )
                except OSError:
                    pass
        return msgs

    def _validate_basic_sd_manifest_fast(
        self,
        stations: list,
        manifest_stations: Dict[str, dict],
        reserved_folder: Optional[int],
    ) -> List[str]:
        """Manifest-based validation -- no SD card I/O required.

        Compares the DB station/track list against what the manifest says was
        last synced.  Catches renamed/added/removed stations and tracks,
        reordering, and source-file changes.
        """
        msgs: List[str] = []
        cap = self._VALIDATE_MAX_ISSUES
        db_folder_keys: set = set()

        for st in stations:
            if len(msgs) >= cap:
                break
            fn = int(st["folder_number"])
            if reserved_folder is not None and fn == reserved_folder:
                continue
            folder_key = f"{fn:02d}"
            db_folder_keys.add(folder_key)
            name = (st["name"] or "").strip() or f"Station {fn}"
            m_folder = manifest_stations.get(folder_key)
            if not m_folder:
                msgs.append(
                    f'Station "{name}" (folder {folder_key}) was not in the last sync.'
                )
                continue

            m_tracks = m_folder.get("tracks") or {}
            tracks = self.db.list_basic_station_songs(int(st["id"]))
            n = len(tracks)
            if n == 0:
                continue

            m_count = len(m_tracks)
            if n != m_count:
                msgs.append(
                    f'Station "{name}" (folder {folder_key}): app has {n} tracks '
                    f"but last sync had {m_count}."
                )

            for order, song in enumerate(tracks, start=1):
                if len(msgs) >= cap:
                    break
                track_key = f"{order:03d}"
                m_entry = m_tracks.get(track_key)
                if not m_entry:
                    t = song["title"] or song["original_filename"] or f"track {order}"
                    msgs.append(
                        f'Station "{name}": track "{t}" (slot {track_key}) '
                        f"was not in the last sync."
                    )
                    continue
                fp_raw = song["file_path"]
                if not fp_raw:
                    continue
                fp = Path(fp_raw)
                expected_name = str(m_entry.get("source_name") or "")
                descriptor = {
                    "source_name": fp.name,
                    "source_size": None,
                    "source_hash": str(song["file_hash"] or "").strip() or None,
                }
                try:
                    if song["file_size"] is not None:
                        descriptor["source_size"] = int(song["file_size"])
                    elif fp.exists():
                        descriptor["source_size"] = int(fp.stat().st_size)
                except Exception:
                    descriptor["source_size"] = None

                if fp.name != expected_name:
                    t = song["title"] or song["original_filename"] or f"track {order}"
                    msgs.append(
                        f'Station "{name}": slot {track_key} was synced from '
                        f'"{expected_name}" but app now has "{t}".'
                    )
                    continue

                source_hash = ""
                if fp.exists():
                    try:
                        source_hash = SDManager._resolve_source_hash_static(fp, descriptor)
                    except Exception:
                        source_hash = str(descriptor.get("source_hash") or "")
                if not SDManager._manifest_entry_matches_library(
                    m_entry, descriptor, source_hash=source_hash
                ):
                    t = song["title"] or song["original_filename"] or f"track {order}"
                    msgs.append(
                        f'Station "{name}": slot {track_key} changed for "{t}" '
                        "(source differs from last sync)."
                    )
                    continue

        for mk in manifest_stations:
            if len(msgs) >= cap:
                break
            if mk not in db_folder_keys:
                m_name = (manifest_stations[mk].get("name") or mk).strip()
                msgs.append(
                    f'Folder {mk} ("{m_name}") is on the SD card but no longer in the app.'
                )

        return msgs

    def basic_library_manifest_diff(
        self,
        manifest_stations: Dict[str, dict],
        *,
        reserved_folder: Optional[int] = 99,
    ) -> List[str]:
        """Compare the current library to a saved sync manifest (empty list = unchanged)."""
        try:
            stations = self.db.list_basic_stations()
        except Exception:
            return ["Could not read stations from the database."]
        return self._validate_basic_sd_manifest_fast(
            stations, manifest_stations, reserved_folder,
        )

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
          ``radio_metadata.json`` and ``advanced_runtime.json`` at SD root (no ``VintageRadio/``
          on the card). All tracks converted to MP3.
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
        is stored in the ``sd_mapping`` database table and embedded in
        ``radio_metadata.json`` at the **SD root** so the firmware can look up the
        real location of any track regardless of which album/playlist it belongs to.

        Args:
            force_clean: If True, re-sync all files even if they already exist.
            progress_callback: Optional callback(current, total, message).
        """
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
            self._write_metadata(sd_root)
            self._remove_legacy_vintage_radio_folder_on_dfplayer_sd(sd_root)
            return 0, 0

        # ── Assign each song a (folder, track_number) slot in library order ──
        # Every resync (normal or clean) assigns slots in the same order as albums/playlists
        # so that metadata and SD card layout always match.
        # Many DFPlayer clones struggle with large directories (>15-20 files per
        # folder), causing playback failures for higher-numbered tracks.  Spreading
        # songs across folders avoids this.  15 tracks/folder × 99 folders = 1,485
        # max tracks — more than the 255 per single folder the datasheet allows.
        MAX_TRACKS_PER_FOLDER = 100

        song_slot: Dict[int, Tuple[int, int]] = {}  # song_id -> (folder, track)
        next_folder = 1
        next_track = 1

        for sid in used_song_ids:
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
        used_folders = {f for f, _ in song_slot.values()}
        work_done += 1
        cleanup_step = work_done

        def _cleanup_progress(_current: int, _total: int, msg: str) -> None:
            if progress_callback:
                progress_callback(cleanup_step, total_work, msg)

        self._remove_stale_numeric_sd_folders(
            sd_root,
            used_folders,
            progress_callback=_cleanup_progress if progress_callback else None,
            progress_total=1,
        )

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
        self._write_metadata(sd_root)
        self._remove_legacy_vintage_radio_folder_on_dfplayer_sd(sd_root)

        if progress_callback:
            progress_callback(total_work, total_work, "Sync complete!")

        print(f"SD sync complete: {copied} copied, {skipped} skipped, {len(used_song_ids)} unique songs")
        if copied == 0 and skipped > 0:
            print("No files were copied (all sources missing?). Re-import in Library or fix file paths, then sync again.")
        return copied, skipped

    def _write_advanced_runtime_sd_config(
        self,
        sd_root: Path,
        *,
        dfplayer_eq: str,
        conversion_profile: str,
    ) -> None:
        cfg_path = sd_root / "advanced_runtime.json"
        payload = {
            "dfplayer_eq": dfplayer_eq,
            "conversion_profile": conversion_profile,
        }
        try:
            cfg_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as e:
            print(f"Warning: could not write advanced runtime config: {e}")

    def _copy_am_wav_to_dfplayer_sd(self, sd_root: Path) -> bool:
        """AM static uses Pico PWM only; do not copy AM WAV onto the DFPlayer SD card."""
        print(
            "SD sync: skipping AM WAV copy to DFPlayer SD "
            "(install AMradioSound.wav on Pico flash for PWM AM)"
        )
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

        Reads ``radio_metadata.json`` from the SD root (or legacy ``VintageRadio/``)
        to reconstruct albums and playlists.  Audio files are resolved from their
        DFPlayer folder/track paths (e.g. ``01/044.mp3``).  Songs that already
        exist in the library (matched by hash+size) are reused; new files are
        copied to ``dest_dir`` (if provided) and added to the library with the
        copied file path.  If ``dest_dir`` is None, files are added with the SD
        path as their source (legacy behavior).
        """
        imported_albums = 0
        imported_playlists = 0
        imported_songs = 0
        metadata_path = self.dfplayer_radio_metadata_path(sd_root)
        if not metadata_path.exists():
            legacy = self.vintage_root(sd_root) / "radio_metadata.json"
            if legacy.exists():
                metadata_path = legacy
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

    def _write_metadata(self, metadata_dir: Path) -> None:
        """Write ``metadata_dir/radio_metadata.json`` with deduplicated SD layout.

        Each track entry in an album/playlist includes the **actual** DFPlayer
        folder and track number (from ``sd_mapping``) so the firmware can call
        ``playFolder(folder, track)`` directly.  Albums and playlists are purely
        logical groupings -- they no longer correspond to physical folders.

        The file is kept compact so MicroPython on the Pico can parse it
        within its limited RAM (~256 KB).  Only fields the firmware actually
        needs are included (title, artist, duration, folder, track).

        For DFPlayer SD use ``metadata_dir = sd_root``; for Pi layout use
        ``metadata_dir = vintage_root``.
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

        metadata_path = metadata_dir / "radio_metadata.json"
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


def _windows_get_removable_drive_roots() -> List[Tuple[Path, str]]:
    """Drive letters Windows reports as DRIVE_REMOVABLE (2).

    Supplements ``psutil`` when the SD reader does not expose the *removable*
    partition flag but is still classified as removable by the OS.
    """
    if platform.system() != "Windows":
        return []
    try:
        import ctypes
        import string

        DRIVE_REMOVABLE = 2
        kernel32 = ctypes.windll.kernel32
        sys_letter = (os.environ.get("SystemDrive", "C:")[:1]).upper()
        out: List[Tuple[Path, str]] = []
        for letter in string.ascii_uppercase:
            if letter == sys_letter:
                continue
            root = f"{letter}:\\"
            try:
                if kernel32.GetDriveTypeW(root) != DRIVE_REMOVABLE:
                    continue
            except Exception:
                continue
            p = Path(root)
            try:
                if not p.exists():
                    continue
            except OSError:
                continue
            out.append((p, _get_volume_label(p)))
        return out
    except Exception:
        return []


def _sanitize_fat_volume_label(raw: str) -> str:
    """Return a FAT32-friendly volume label (max 11 chars, A-Z / 0-9 / space)."""
    s = (raw or "").strip().upper()
    s = re.sub(r"[^A-Z0-9 ]+", "", s)
    s = s[:11].strip()
    return s


def _resolve_mount_volume_name(sd_root: Path, db_hint: str = "") -> str:
    """Best-effort current volume display name for *sd_root* before a format."""
    if os.name == "nt":
        v = (_get_volume_label(sd_root) or "").strip()
        if v:
            return v
        # Bare drive roots (``E:\\``) have ``.name == "E:"`` — not a useful label; prefer *db_hint*.
        try:
            nm = (sd_root.name or "").strip()
            if len(nm) == 2 and nm[1] == ":" and nm[0].isalpha():
                hint = (db_hint or "").strip()
                if hint:
                    return hint
        except (OSError, ValueError):
            pass
    try:
        name = (sd_root.name or "").strip()
        if name and name not in (".", "/"):
            return name
    except (OSError, ValueError):
        pass
    return (db_hint or "").strip()


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

