"""Write a raw disk image to a physical drive (experimental clean SD install).

Windows: ``\\\\.\\PhysicalDriveN`` with optional volume lock / dismount.
macOS: whole-disk ``diskN`` via ``/dev/rdiskN``; unmount with ``diskutil``; admin via ``osascript``.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import platform
import plistlib
import re
import secrets
import select
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Chunk size for raw writes (bytes). Must be a multiple of 512 for some APIs.
_WRITE_CHUNK_BYTES = 1024 * 1024

# Marker embedded in error strings when macOS Full Disk Access is required.
# Radio manager detects this to show an actionable FDA dialog instead of a plain error.
DARWIN_FDA_REQUIRED_MARKER = "__VR_DARWIN_FDA_REQUIRED__"

_DD_RECORDS_OUT_RE = re.compile(r"(\d+)\+0 records out")


def _darwin_nonblocking_pipe_drain(pipe: Any, acc: bytearray, *, chunk: int = 65536) -> None:
    """Append any immediately-readable bytes from *pipe* into *acc* (non-blocking).

    If the child writes enough to stderr while the parent only ``read()``s at exit,
    the pipe buffer can fill and **block the child** (classic ``subprocess`` deadlock).
    ``dd`` is usually quiet, but ``sudo``/system messages can still fill the buffer on
    long runs; draining during ``poll()`` avoids that class of failure.
    """
    if pipe is None:
        return
    try:
        fd = pipe.fileno()
    except (ValueError, OSError):
        return
    while True:
        try:
            readable, _, _ = select.select([fd], [], [], 0)
        except (ValueError, OSError, InterruptedError):
            return
        if not readable:
            return
        try:
            data = os.read(fd, chunk)
        except BlockingIOError:
            continue
        except OSError:
            return
        if not data:
            return
        acc.extend(data)


def dd_stderr_records_out_bytes(stderr_text: str, *, block_size: int = 1024 * 1024) -> Optional[int]:
    """Return bytes implied by the last ``N+0 records out`` line from ``dd`` stderr."""
    matches = list(_DD_RECORDS_OUT_RE.finditer(stderr_text))
    if not matches:
        return None
    return int(matches[-1].group(1)) * block_size


def _sd_log(message: str) -> None:
    """Write a timestamped [SD-WRITE] line to the session log (best-effort)."""
    try:
        from gui.session_log import write_session_line  # avoid circular at module level
        write_session_line(message, prefix="SD-WRITE")
    except Exception:
        pass

# Pre-allocated zero block for zero-skip comparison (avoids per-chunk allocation).
_ZERO_CHUNK = bytes(_WRITE_CHUNK_BYTES)


def _win32_write_physical_disk(fd: int, data: bytes) -> None:
    r"""Write to ``\\.\PhysicalDriveN`` via Win32 ``WriteFile``.

    ``os.write`` on the CRT file descriptor can raise ``OSError: [Errno 9] Bad file
    descriptor`` even when the handle is valid — the same symptom as blocking direct
    writes (see MSDN "Blocking Direct Write Operations to Volumes and Disks").
    """
    import msvcrt
    from ctypes import wintypes

    h = msvcrt.get_osfhandle(fd)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wf = kernel32.WriteFile
    wf.argtypes = (
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    wf.restype = wintypes.BOOL

    total = len(data)
    i = 0
    while i < total:
        piece = data[i : i + _WRITE_CHUNK_BYTES]
        buf = ctypes.create_string_buffer(piece)
        written = wintypes.DWORD(0)
        if not wf(h, buf, len(piece), ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if written.value != len(piece):
            raise OSError(f"WriteFile short write ({written.value} of {len(piece)} bytes)")
        i += len(piece)


def _write_raw_to_disk_fd(fd: int, data: bytes) -> None:
    if platform.system() == "Windows":
        _win32_write_physical_disk(fd, data)
    else:
        os.write(fd, data)


def _seek_disk_fd_cur(fd: int, offset: int) -> None:
    """Advance the disk file-descriptor position by *offset* bytes without writing.

    Used by the zero-skip optimisation: full-disk FAT32 images are mostly sparse
    (empty clusters are zeros); seeking past them instead of writing means we only
    touch the sectors that actually contain music data and FAT structures.

    On Windows we use ``SetFilePointerEx`` on the Win32 HANDLE so that the position
    is shared with the subsequent ``WriteFile`` call in ``_win32_write_physical_disk``.
    On other platforms a plain ``os.lseek`` is sufficient.
    """
    if platform.system() == "Windows":
        import msvcrt
        from ctypes import c_int64, c_longlong

        h = msvcrt.get_osfhandle(fd)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        new_pos = c_int64(0)
        FILE_CURRENT = 1
        if not k32.SetFilePointerEx(h, c_longlong(offset), ctypes.byref(new_pos), FILE_CURRENT):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.lseek(fd, offset, os.SEEK_CUR)


def _emit_disk_write_progress(
    written: int,
    total: int,
    message: str,
    *,
    progress_callback: Optional[Callable[[int, int, str], None]],
    progress_file_path: Optional[Path],
) -> None:
    """Mirror progress to GUI callback and/or a JSON sidecar (elevated child → parent)."""
    if progress_callback:
        progress_callback(written, total, message)
    if progress_file_path is not None:
        try:
            p = Path(progress_file_path)
            payload = json.dumps(
                {"written": written, "total": total, "message": message},
                ensure_ascii=False,
            )
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(payload + "\n", encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass


def _read_uac_progress_file(path: Path) -> Optional[Tuple[int, int, str]]:
    """Read JSON written by elevated disk-write process (atomic replace)."""
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return None
        data = json.loads(text)
        w = int(data.get("written", 0))
        t = int(data.get("total", 0))
        msg = str(data.get("message", ""))
        return w, t, msg
    except (OSError, ValueError, TypeError):
        return None

# Cached FAT32 image under ``app_data_dir()/sd_image_cache/`` for reuse / faster flash testing.
LAST_CACHED_SD_IMAGE_FILENAME = "vintage_radio_sd_last.img"


def is_windows_admin() -> bool:
    if platform.system() != "Windows":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _physical_drive_path(disk_number: int) -> str:
    return rf"\\.\PhysicalDrive{int(disk_number)}"


def windows_drive_letter_from_path(path: Path) -> Optional[str]:
    """Return 'E' for ``E:\\Music`` or ``E:\\``."""
    try:
        s = str(path.resolve())
    except OSError:
        s = str(path)
    if len(s) >= 2 and s[1] == ":":
        return s[0].upper()
    return None


def windows_disk_number_for_drive_letter(letter: str) -> Optional[int]:
    """Resolve physical disk number for a mounted drive letter (Windows)."""
    if platform.system() != "Windows":
        return None
    letter = letter.strip().upper()[:1]
    if not letter or not letter.isalpha():
        return None
    ps = (
        f"$p = Get-Partition -DriveLetter '{letter}' -ErrorAction SilentlyContinue; "
        f"if ($p) {{ $p.DiskNumber }} else {{ '' }}"
    )
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        if r.returncode != 0:
            return None
        out = (r.stdout or "").strip()
        if not out.isdigit():
            return None
        return int(out)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def windows_get_disk_size_bytes(disk_number: int) -> Optional[int]:
    if platform.system() != "Windows":
        return None
    ps = f"(Get-Disk -Number {int(disk_number)} -ErrorAction SilentlyContinue).Size"
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        if r.returncode != 0:
            return None
        out = (r.stdout or "").strip()
        if not out.isdigit():
            return None
        return int(out)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def windows_list_non_system_disks() -> List[Dict[str, Any]]:
    """Return removable physical disks only (USB / MMC SD readers, USB sticks).

    Excludes internal NVMe/SATA/ATA/SCSI system storage so the wizard cannot
    target a fixed drive by mistake.
    """
    if platform.system() != "Windows":
        return []
    ps = r"""
# Whitelist bus types that are typically removable external/slot media only.
# This hides internal NVMe/SATA/ATA fixed disks — it is NOT a cryptographic guarantee.
# USB external HDDs still appear as BusType USB; the user must match size/labels to the SD card.
$allowed = @('USB', 'MMC')
$disks = Get-Disk | Where-Object {
  -not $_.IsSystem -and ($allowed -contains $_.BusType.ToString())
}
$out = @()
foreach ($d in $disks) {
  $partInfos = @()
  Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue | ForEach-Object {
    $vol = Get-Volume -Partition $_ -ErrorAction SilentlyContinue
    if ($null -eq $vol) { return }
    $dl = $vol.DriveLetter
    $lbl = $vol.FileSystemLabel
    if ($dl) {
      $s = ($dl.ToString() + ':')
      if ($lbl) { $s += ' (' + $lbl + ')' } else { $s += ' (no label)' }
      $partInfos += $s
    } elseif ($lbl) {
      $partInfos += '(' + $lbl + ')'
    }
  }
  $volSummary = if ($partInfos.Count -gt 0) { [string]::Join(', ', $partInfos) } else { '' }
  $out += [PSCustomObject]@{
    Number = $d.Number
    Size = $d.Size
    FriendlyName = $d.FriendlyName
    BusType = $d.BusType.ToString()
    IsRemovable = $d.IsRemovable
    VolumeSummary = $volSummary
  }
}
$out | ConvertTo-Json -Compress -Depth 4
"""
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        if r.returncode != 0:
            return []
        raw = (r.stdout or "").strip()
        if not raw:
            return []
        data = json.loads(raw)
        rows: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            rows = [data]
        elif isinstance(data, list):
            rows = [x for x in data if isinstance(x, dict)]
        # Deduplicate by disk Number (Get-Disk can surface duplicates in some setups).
        seen: set = set()
        unique: List[Dict[str, Any]] = []
        def _num(row: Dict[str, Any]) -> int:
            try:
                return int(row.get("Number", 0))
            except (TypeError, ValueError):
                return 0

        for row in sorted(rows, key=_num):
            try:
                n = int(row["Number"])
            except (KeyError, TypeError, ValueError):
                continue
            if n in seen:
                continue
            seen.add(n)
            unique.append(row)
        return unique
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        pass
    return []


def darwin_normalize_bsd_whole_disk(name: str) -> Optional[str]:
    """Return ``diskN`` for a whole-disk BSD name, or *None* if invalid / partition-only."""
    s = (name or "").strip()
    if not s:
        return None
    if s.startswith("/dev/"):
        s = s[5:]
    if s.startswith("rdisk"):
        s = "disk" + s[5:]
    if not re.fullmatch(r"disk\d+", s):
        return None
    return s


def _darwin_volume_root_from_path(p: Path) -> Optional[Path]:
    """``/Volumes/MyCard/sub`` → ``/Volumes/MyCard``."""
    try:
        p = p.resolve()
    except OSError:
        p = Path(p)
    parts = p.parts
    if len(parts) >= 3 and parts[1] == "Volumes":
        return Path("/Volumes") / parts[2]
    return None


def darwin_default_bsd_disk_from_volume_path(sd_root: Path) -> Optional[str]:
    """Resolve whole-disk BSD name (e.g. ``disk4``) for a path under ``/Volumes/...``."""
    if platform.system() != "Darwin":
        return None
    vol = _darwin_volume_root_from_path(sd_root)
    if vol is None or not vol.is_dir():
        return None
    try:
        r = subprocess.run(
            ["diskutil", "info", "-plist", str(vol)],
            capture_output=True,
            timeout=60,
        )
        if r.returncode != 0 or not r.stdout:
            return None
        info = plistlib.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException, TypeError):
        return None
    parent = info.get("ParentWholeDisk")
    if isinstance(parent, str) and darwin_normalize_bsd_whole_disk(parent):
        return darwin_normalize_bsd_whole_disk(parent)
    dev = info.get("DeviceIdentifier")
    if isinstance(dev, str) and info.get("WholeDisk") is True:
        return darwin_normalize_bsd_whole_disk(dev)
    return None


def darwin_rdisk_path(bsd_whole_disk: str) -> str:
    """Raw whole-disk device (faster for imaging), e.g. ``disk4`` → ``/dev/rdisk4``."""
    d = darwin_normalize_bsd_whole_disk(bsd_whole_disk)
    if not d:
        raise ValueError(f"Not a whole-disk BSD name: {bsd_whole_disk!r}")
    return f"/dev/r{d}"


def darwin_get_disk_size_bytes(bsd_whole_disk: str) -> Optional[int]:
    """Byte size of a whole disk from ``diskutil info``."""
    if platform.system() != "Darwin":
        return None
    d = darwin_normalize_bsd_whole_disk(bsd_whole_disk)
    if not d:
        return None
    try:
        r = subprocess.run(
            ["diskutil", "info", "-plist", d],
            capture_output=True,
            timeout=60,
        )
        if r.returncode != 0 or not r.stdout:
            return None
        info = plistlib.loads(r.stdout)
        sz = info.get("TotalSize")
        if isinstance(sz, int) and sz > 0:
            return sz
    except (OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException, TypeError, ValueError):
        pass
    return None


def darwin_list_external_physical_disks() -> List[Dict[str, Any]]:
    """USB / external physical disks from ``diskutil list external physical`` (plist)."""
    if platform.system() != "Darwin":
        return []
    try:
        r = subprocess.run(
            ["diskutil", "list", "-plist", "external", "physical"],
            capture_output=True,
            timeout=90,
        )
        if r.returncode != 0 or not r.stdout:
            return []
        data = plistlib.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException, TypeError):
        return []

    whole = [x for x in (data.get("WholeDisks") or []) if isinstance(x, str)]
    if not whole:
        return []

    def _partition_summaries(entry: Dict[str, Any]) -> str:
        parts = entry.get("Partitions") or []
        bits: List[str] = []
        if isinstance(parts, list):
            for p in parts:
                if not isinstance(p, dict):
                    continue
                vn = str(p.get("VolumeName") or "").strip()
                mp = str(p.get("MountPoint") or "").strip()
                ct = str(p.get("Content") or "").strip()
                if vn or mp:
                    bits.append(f"{vn or ct or 'volume'}{f' @ {mp}' if mp else ''}")
                elif ct and ct not in ("Apple_partition_map", "Apple_partition_scheme"):
                    bits.append(ct)
        return ", ".join(bits) if bits else ""

    rows: List[Dict[str, Any]] = []
    for entry in data.get("AllDisksAndPartitions") or []:
        if not isinstance(entry, dict):
            continue
        did = entry.get("DeviceIdentifier")
        if not isinstance(did, str) or did not in whole:
            continue
        try:
            size = int(entry.get("Size") or 0)
        except (TypeError, ValueError):
            size = 0
        vol_name = str(entry.get("VolumeName") or "").strip()
        mount = str(entry.get("MountPoint") or "").strip()
        part_sum = _partition_summaries(entry)
        vol_summary = part_sum or (f"{vol_name} @ {mount}" if (vol_name or mount) else "")
        rows.append(
            {
                "BSDName": did,
                "Size": size,
                "VolumeSummary": vol_summary,
                "MountPoint": mount,
                "VolumeName": vol_name,
            }
        )

    rows.sort(key=lambda x: str(x.get("BSDName", "")))
    return rows


def _diskpart_run_script(lines: List[str]) -> Tuple[int, str]:
    if platform.system() != "Windows":
        return 1, "Not Windows"
    fd, path = tempfile.mkstemp(prefix="vr_diskpart_", suffix=".txt")
    try:
        script = "\r\n".join(lines) + "\r\n"
        os.write(fd, script.encode("ascii", errors="replace"))
        os.close(fd)
        try:
            r = subprocess.run(
                ["diskpart", "/s", path],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0,
            )
        except OSError as e:
            # WinError 740: elevation required — diskpart cannot run non-elevated.
            win = getattr(e, "winerror", None)
            return (win if win is not None else -1), str(e)
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        return r.returncode, out
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def windows_offline_disk(disk_number: int) -> Tuple[bool, str]:
    code, out = _diskpart_run_script(
        [f"select disk {int(disk_number)}", "offline disk"]
    )
    return code == 0, out[-2000:]


def windows_online_disk(disk_number: int) -> Tuple[bool, str]:
    code, out = _diskpart_run_script(
        [f"select disk {int(disk_number)}", "online disk"]
    )
    return code == 0, out[-2000:]


def _windows_set_disk_offline_ps(disk_number: int) -> Tuple[bool, str]:
    """Take a disk offline via PowerShell ``Set-Disk`` (more reliable for USB/SD).

    Forcibly dismounts all volumes on the disk so a raw write to ``PhysicalDriveN``
    cannot be blocked by the filesystem layer (WinError 5 / access denied).
    """
    if platform.system() != "Windows":
        return False, "Not Windows"
    ps = (
        f"$d = Get-Disk -Number {int(disk_number)} -ErrorAction Stop; "
        "if ($d.IsOffline -eq $false) { "
        f"  Set-Disk -Number {int(disk_number)} -IsOffline $true -ErrorAction Stop "
        "}"
    )
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return r.returncode == 0, out
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def _windows_set_disk_online_ps(disk_number: int) -> Tuple[bool, str]:
    """Bring a disk back online (and writable) via PowerShell."""
    if platform.system() != "Windows":
        return False, "Not Windows"
    ps = (
        f"$d = Get-Disk -Number {int(disk_number)} -ErrorAction Stop; "
        "if ($d.IsOffline) { "
        f"  Set-Disk -Number {int(disk_number)} -IsOffline $false -ErrorAction Stop "
        "} "
        f"Set-Disk -Number {int(disk_number)} -IsReadOnly $false -ErrorAction SilentlyContinue"
    )
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return r.returncode == 0, out
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def _windows_get_disk_volume_letters(disk_number: int) -> List[str]:
    """Return drive letters (e.g. ['E', 'F']) for mounted volumes on *disk_number*."""
    if platform.system() != "Windows":
        return []
    ps = (
        f"Get-Partition -DiskNumber {int(disk_number)} -ErrorAction SilentlyContinue"
        " | Where-Object {$_.DriveLetter}"
        " | Select-Object -ExpandProperty DriveLetter"
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        letters = []
        for line in (r.stdout or "").splitlines():
            ch = line.strip()
            if ch and len(ch) == 1 and ch.isalpha():
                letters.append(ch.upper())
        return letters
    except (OSError, subprocess.TimeoutExpired):
        return []


# Win32 IOCTL codes for volume lock/dismount.
_FSCTL_LOCK_VOLUME = 0x00090018
_FSCTL_DISMOUNT_VOLUME = 0x00090020


def _windows_lock_and_dismount_volumes(disk_number: int) -> Tuple[List[object], str]:
    r"""Lock and dismount all mounted volumes on *disk_number* via Win32 FSCTL.

    Opens each volume (e.g. ``\\.\E:``) with ``GENERIC_READ|GENERIC_WRITE``, sends
    ``FSCTL_LOCK_VOLUME`` then ``FSCTL_DISMOUNT_VOLUME``.  Keeping the handles open
    holds the lock so Windows cannot re-mount the volume while we write to the
    physical disk.

    Returns ``(handles, warnings_text)``.  Caller must call
    ``_windows_close_volume_handles`` after the write finishes.

    This is the correct approach for *removable* media; ``Set-Disk -IsOffline`` and
    ``diskpart offline disk`` both fail with "not supported on removable media".
    """
    if platform.system() != "Windows":
        return [], ""

    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.CloseHandle.restype = wintypes.BOOL

    letters = _windows_get_disk_volume_letters(disk_number)
    if not letters:
        return [], "No mounted volumes with drive letters found for this disk."

    handles: List[object] = []
    warnings: List[str] = []
    invalid = ctypes.c_void_p(-1).value  # INVALID_HANDLE_VALUE

    for letter in letters:
        vol_path = f"\\\\.\\{letter}:"
        h = kernel32.CreateFileW(
            vol_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if h is None or h == invalid or h == -1:
            err = ctypes.get_last_error()
            warnings.append(f"Could not open volume {vol_path} (WinError {err})")
            continue

        br = wintypes.DWORD(0)
        if not kernel32.DeviceIoControl(
            h, _FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(br), None
        ):
            warnings.append(
                f"FSCTL_LOCK_VOLUME on {vol_path} failed (WinError {ctypes.get_last_error()})"
            )

        br2 = wintypes.DWORD(0)
        if not kernel32.DeviceIoControl(
            h, _FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(br2), None
        ):
            warnings.append(
                f"FSCTL_DISMOUNT_VOLUME on {vol_path} failed (WinError {ctypes.get_last_error()})"
            )
            kernel32.CloseHandle(h)
        else:
            handles.append(h)

    return handles, "; ".join(warnings)


def _windows_close_volume_handles(handles: List[object]) -> None:
    """Release volume handles acquired by ``_windows_lock_and_dismount_volumes``."""
    if not handles or platform.system() != "Windows":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for h in handles:
        try:
            kernel32.CloseHandle(h)
        except Exception:
            pass


def _windows_bring_disk_online(disk_number: int) -> None:
    """Attempt to bring a non-removable disk back online; safe no-op for removable media."""
    ps = (
        f"$d = Get-Disk -Number {int(disk_number)} -ErrorAction SilentlyContinue; "
        "if ($d -and $d.IsOffline) { "
        f"  Set-Disk -Number {int(disk_number)} -IsOffline $false -ErrorAction SilentlyContinue; "
        f"  Set-Disk -Number {int(disk_number)} -IsReadOnly $false -ErrorAction SilentlyContinue "
        "}"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _ps_escape_single_quoted(s: str) -> str:
    """Escape for use inside PowerShell single-quoted strings ('' for ')."""
    return s.replace("'", "''")


def _write_image_via_uac_subprocess(
    image_path: Path,
    disk_number: int,
    *,
    image_size: int,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, str]:
    """Relaunch the write step with Administrator rights (UAC prompt).

    Elevated ``Start-Process`` does *not* inherit the PowerShell session's working
    directory; without ``-WorkingDirectory``, ``python -m gui....`` often runs from
    ``System32`` and fails to import the project (exit code 1, no visible output).

    The elevated helper writes JSON progress to a temp ``*.progress.json`` file;
    we ``Popen`` the launcher PowerShell and poll that file so the GUI shows bytes
    written (same as the in-process admin path).
    """
    project_root = Path(__file__).resolve().parent.parent
    launcher = Path(sys.executable).resolve()
    img = Path(image_path).resolve()
    disk = int(disk_number)
    frozen = bool(getattr(sys, "frozen", False))

    # Working directory for the elevated child (required for `python -m gui...`).
    if frozen:
        work_dir = str(Path(sys.executable).resolve().parent)
    else:
        work_dir = str(project_root)

    ex = _ps_escape_single_quoted(str(launcher))
    im = _ps_escape_single_quoted(str(img))
    wd = _ps_escape_single_quoted(work_dir)

    # Log path for the elevated child (cannot use Start-Process -Redirect* with -Verb RunAs:
    # PowerShell reports AmbiguousParameterSet for that combination).
    token = secrets.token_hex(8)
    diag_log = Path(tempfile.gettempdir()) / f"vintage_radio_sd_uac_{token}.log"
    progress_path = Path(tempfile.gettempdir()) / f"vintage_radio_sd_uac_{token}.progress.json"
    try:
        diag_log.write_text("", encoding="utf-8")
    except OSError:
        pass
    try:
        progress_path.unlink(missing_ok=True)
    except OSError:
        pass
    lg = _ps_escape_single_quoted(str(diag_log))
    pg = _ps_escape_single_quoted(str(progress_path))

    if frozen:
        # Single pre-quoted string so CreateProcess gets properly quoted tokens.
        arg_line = (
            "$argStr = '--vr-write-sd-disk \"' + $img + '\" ' + $disk + ' \"' + $logPath + '\" \"' + $progressPath + '\"'\n"
            "$p = Start-Process -FilePath $exe -ArgumentList $argStr "
            f"-WorkingDirectory '{wd}' "
            "-WindowStyle Hidden -Verb RunAs -Wait -PassThru"
        )
    else:
        arg_line = (
            "$argStr = '-m gui.sd_disk_write_helper \"' + $img + '\" ' + $disk + ' \"' + $logPath + '\" \"' + $progressPath + '\"'\n"
            "$p = Start-Process -FilePath $exe -ArgumentList $argStr "
            f"-WorkingDirectory '{wd}' "
            "-WindowStyle Hidden -Verb RunAs -Wait -PassThru"
        )

    script_lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$logPath = '{lg}'",
        f"$progressPath = '{pg}'",
        f"$exe = '{ex}'",
        f"$img = '{im}'",
        f"$disk = {disk}",
        arg_line,
        "exit $p.ExitCode",
    ]
    script = "\r\n".join(script_lines) + "\r\n"

    fd, ps1_path = tempfile.mkstemp(prefix="vr_sd_uac_", suffix=".ps1")
    no_window = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    )
    try:
        os.close(fd)
        Path(ps1_path).write_text(script, encoding="utf-8-sig")
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=no_window,
        )
        last_emit: Optional[Tuple[int, int, str]] = None
        ps_out = ""
        try:
            while proc.poll() is None:
                if should_cancel and should_cancel():
                    proc.terminate()
                    try:
                        proc.wait(timeout=15)
                    except (OSError, subprocess.TimeoutExpired):
                        try:
                            proc.kill()
                        except OSError:
                            pass
                    return False, "Cancelled"

                if progress_callback:
                    snap = _read_uac_progress_file(progress_path)
                    if snap is not None:
                        w, t, msg = snap
                        cur = (w, t, msg)
                        if cur != last_emit:
                            last_emit = cur
                            if t > 0:
                                progress_callback(w, t, msg)
                            else:
                                progress_callback(0, 0, msg)
                time.sleep(0.12)
        finally:
            stderr = ""
            try:
                _stdout, stderr = proc.communicate(timeout=120)
            except (subprocess.TimeoutExpired, OSError):
                pass
            ps_out = (stderr or "").strip()

        r_code = proc.returncode

        child_blob = ""
        try:
            if diag_log.is_file():
                child_blob = diag_log.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pass

        if r_code == 0:
            if progress_callback and image_size > 0:
                progress_callback(image_size, image_size, "SD card write complete.")
            try:
                diag_log.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                progress_path.unlink(missing_ok=True)
            except OSError:
                pass
            return True, ""

        detail_parts = [f"PowerShell exit: {r_code}"]
        if ps_out:
            detail_parts.append(f"Launcher: {ps_out}")
        if child_blob:
            detail_parts.append(f"Elevated process log:\n{child_blob[:12000]}")
        else:
            detail_parts.append(
                "(No diagnostic log from the elevated Python process — "
                "if you approved UAC, try again.)"
            )
        detail = "\n\n".join(detail_parts)

        hint = ""
        if r_code is not None and r_code != 0 and not child_blob and not ps_out:
            hint = (
                "\n\nIf you cancelled the Windows security prompt, run SD image sync again and approve it."
            )
        return (
            False,
            "Could not write to the SD card after the Administrator prompt.\n\n" + detail + hint,
        )
    except OSError as e:
        return False, f"Could not start the elevated write step: {e}"
    finally:
        try:
            os.unlink(ps1_path)
        except OSError:
            pass
        try:
            diag_log.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            progress_path.unlink(missing_ok=True)
        except OSError:
            pass


def write_image_to_physical_disk(
    image_path: Path,
    disk_number: int,
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    try_offline_first: bool = True,
) -> Tuple[bool, str]:
    """Write *entire* *image_path* to ``PhysicalDrive`` *disk_number* (Windows).

    If the GUI is not running as Administrator, Windows shows a UAC prompt and a
    small elevated helper performs the raw write (you do not need to restart the
    whole app as Administrator).

    Destroys all data on the target disk.
    """
    if platform.system() != "Windows":
        return (
            False,
            "Writing a disk image from Vintage Radio is only implemented on Windows. "
            "Save the .img file and flash it with Balena Etcher, Raspberry Pi Imager, or dd.",
        )

    image_path = Path(image_path).resolve()
    if not image_path.is_file():
        return False, f"Image file not found: {image_path}"

    image_size = image_path.stat().st_size
    if image_size <= 0:
        return False, "Image file is empty."

    disk_size = windows_get_disk_size_bytes(disk_number)
    if disk_size is not None and image_size > disk_size:
        return (
            False,
            f"Image ({image_size} bytes) is larger than the selected disk ({disk_size} bytes). "
            "Choose a larger SD card or reduce library size.",
        )

    if not is_windows_admin():
        if progress_callback:
            progress_callback(
                0,
                0,
                "Requesting Windows permission to write to the SD card (UAC)…",
            )
        return _write_image_via_uac_subprocess(
            image_path,
            disk_number,
            image_size=image_size,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    return _write_image_to_physical_disk_impl(
        image_path,
        disk_number,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
        try_offline_first=try_offline_first,
    )


def _sparse_copy_image_to_fd(
    fd: int,
    image_path: Path,
    image_size: int,
    *,
    cap_bytes: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    progress_file_path: Optional[Path] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    device_label: str = "",
    volume_lock_warnings: str = "",
) -> Tuple[bool, str]:
    """Stream *image_path* to an open raw disk *fd* (zero-chunk seek optimisation).

    *cap_bytes*: if set, stop reading from the image at this byte offset.  Used when
    an image is marginally larger than the target disk (manufacturing tolerance between
    same-nominal-size SD cards): the trailing empty FAT32 space is simply not written.
    """
    write_limit = cap_bytes if cap_bytes is not None else image_size
    written_from_file = 0
    try:
        img = open(image_path, "rb")
    except OSError as e:
        return False, f"Could not read image file {image_path}: {e}"
    try:
        with img:
            while True:
                if should_cancel and should_cancel():
                    return False, "Cancelled"
                if written_from_file >= write_limit:
                    break
                remaining = write_limit - written_from_file
                read_size = min(_WRITE_CHUNK_BYTES, remaining)
                chunk = img.read(read_size)
                if not chunk:
                    break

                if len(chunk) == _WRITE_CHUNK_BYTES and chunk == _ZERO_CHUNK:
                    _seek_disk_fd_cur(fd, _WRITE_CHUNK_BYTES)
                    written_from_file += len(chunk)
                    _emit_disk_write_progress(
                        written_from_file,
                        image_size,
                        f"Writing to SD card ({written_from_file // (1024 * 1024)} MiB / "
                        f"{image_size // (1024 * 1024)} MiB, skipping empty sectors)…",
                        progress_callback=progress_callback,
                        progress_file_path=progress_file_path,
                    )
                    continue

                to_write = chunk
                rem = len(to_write) % 512
                if rem:
                    to_write = to_write + (b"\x00" * (512 - rem))
                _write_raw_to_disk_fd(fd, to_write)
                written_from_file += len(chunk)
                _emit_disk_write_progress(
                    written_from_file,
                    image_size,
                    f"Writing to SD card ({written_from_file // (1024 * 1024)} MiB / "
                    f"{image_size // (1024 * 1024)} MiB)…",
                    progress_callback=progress_callback,
                    progress_file_path=progress_file_path,
                )
    except OSError as e:
        parts = [f"Disk write to {device_label} failed: {e}"]
        if platform.system() == "Windows":
            winerr = getattr(e, "winerror", None)
            if winerr == 5 or (e.errno in (errno.EACCES, errno.EPERM)):
                parts.append(
                    " Windows blocked the write — the SD card still has a mounted volume. "
                    "Safely eject the SD card in the Windows system tray so it has no "
                    "drive letter (e.g. no 'E:' shown in Explorer), then retry."
                )
            elif e.errno == errno.EBADF or "bad file descriptor" in str(e).lower():
                parts.append(
                    " Windows often reports this when direct writes are blocked (volume still in use)."
                )
        elif platform.system() == "Darwin":
            if e.errno in (errno.EACCES, errno.EPERM):
                parts.append(
                    " macOS blocked the write. Close any Finder windows on the SD card, "
                    "eject it from the menu bar if needed, then retry and approve the admin prompt."
                )
            elif e.errno == errno.EINVAL:
                parts.append(
                    " The raw device may still be busy — quit Disk Utility and other disk tools, then retry."
                )
        if volume_lock_warnings:
            parts.append(f" Volume lock warnings: {volume_lock_warnings}")
        return False, "".join(parts)
    return True, ""


def _write_image_to_physical_disk_impl(
    image_path: Path,
    disk_number: int,
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    try_offline_first: bool = True,
    progress_file_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Perform raw write; caller must already hold Administrator rights."""
    image_path = Path(image_path).resolve()
    if not image_path.is_file():
        return False, f"Image file not found: {image_path}"

    image_size = image_path.stat().st_size
    if image_size <= 0:
        return False, "Image file is empty."

    disk_size = windows_get_disk_size_bytes(disk_number)
    if disk_size is not None and image_size > disk_size:
        return (
            False,
            f"Image ({image_size} bytes) is larger than the selected disk ({disk_size} bytes). "
            "Choose a larger SD card or reduce library size.",
        )

    device = _physical_drive_path(disk_number)

    # Lock and dismount all mounted volumes on the disk so Windows allows raw writes.
    # NOTE: Set-Disk -IsOffline and diskpart "offline disk" both fail for removable
    # media ("not supported on removable media"). The correct approach is FSCTL per volume.
    vol_handles: List[object] = []
    vol_warn = ""
    if try_offline_first:
        vol_handles, vol_warn = _windows_lock_and_dismount_volumes(disk_number)

    _emit_disk_write_progress(
        0,
        image_size,
        "Preparing to write to SD card (locking volumes)…",
        progress_callback=progress_callback,
        progress_file_path=progress_file_path,
    )

    try:
        fd = os.open(device, os.O_RDWR | os.O_BINARY)
    except OSError as e:
        hint = ""
        winerr = getattr(e, "winerror", None)
        msg_l = str(e).lower()
        access_denied = (
            winerr == 5
            or winerr == 32  # ERROR_SHARING_VIOLATION — volume often still mounted
            or e.errno in (errno.EACCES, errno.EPERM)
            or "permission denied" in msg_l
            or "access is denied" in msg_l
            or "access denied" in msg_l
        )
        if access_denied:
            admin = " (this session is not running as Administrator.)" if not is_windows_admin() else ""
            hint = (
                " Raw disk access was refused."
                f"{admin}"
                " Eject or safely remove the SD card’s volume in Windows (system tray), close Explorer"
                " windows on that drive, then retry. If it still fails, exit Vintage Radio and start it"
                " with Run as administrator (right-click the app or shortcut)."
            )
        _windows_close_volume_handles(vol_handles)
        _windows_bring_disk_online(disk_number)
        return False, f"Could not open {device}: {e}.{hint}"

    ok, err = False, ""
    try:
        ok, err = _sparse_copy_image_to_fd(
            fd,
            image_path,
            image_size,
            progress_callback=progress_callback,
            progress_file_path=progress_file_path,
            should_cancel=should_cancel,
            device_label=device,
            volume_lock_warnings=vol_warn,
        )
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    _windows_close_volume_handles(vol_handles)
    _windows_bring_disk_online(disk_number)

    if not ok:
        return False, err or "Write failed."

    if disk_size is not None and image_size < disk_size:
        # Expected: image is sized to data + FAT, card may be larger.
        pass

    return True, ""


def _darwin_unmount_disk(bsd_whole_disk: str) -> Tuple[bool, str]:
    r = subprocess.run(
        ["diskutil", "unmountDisk", bsd_whole_disk],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    return r.returncode == 0, out[-4000:]


def _darwin_try_remount_disk(bsd_whole_disk: str) -> None:
    try:
        subprocess.run(
            ["diskutil", "mountDisk", bsd_whole_disk],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _darwin_remount_async(bsd_whole_disk: str) -> None:
    """Start a daemon thread to remount *bsd_whole_disk* without blocking the caller.

    Used on success paths so the progress dialog closes immediately after the write
    finishes instead of waiting up to 30 s for ``diskutil mountDisk`` to complete.
    The card's volumes will appear in Finder once the background thread finishes.
    """
    import threading as _threading

    t = _threading.Thread(
        target=_darwin_try_remount_disk,
        args=(bsd_whole_disk,),
        daemon=True,
        name=f"vr-remount-{bsd_whole_disk}",
    )
    t.start()


def _write_image_to_darwin_disk_impl(
    image_path: Path,
    bsd_whole_disk: str,
    *,
    cap_bytes: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    progress_file_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Raw-write *image_path* to whole disk *bsd_whole_disk* (caller must be root)."""
    image_path = Path(image_path).resolve()
    if not image_path.is_file():
        return False, f"Image file not found: {image_path}"

    image_size = image_path.stat().st_size
    if image_size <= 0:
        return False, "Image file is empty."

    d = darwin_normalize_bsd_whole_disk(bsd_whole_disk)
    if not d:
        return False, f"Invalid whole-disk identifier: {bsd_whole_disk!r} (expected e.g. disk4)."

    disk_size = darwin_get_disk_size_bytes(d)
    if disk_size is not None and image_size > disk_size:
        return (
            False,
            f"Image ({image_size} bytes) is larger than the selected disk ({disk_size} bytes). "
            "Choose a larger SD card or reduce library size.",
        )

    try:
        rdev = darwin_rdisk_path(d)
    except ValueError as e:
        return False, str(e)

    _darwin_unmount_disk(d)

    _emit_disk_write_progress(
        0,
        image_size,
        "Preparing to write to SD card (unmounted volumes)…",
        progress_callback=progress_callback,
        progress_file_path=progress_file_path,
    )

    try:
        fd = os.open(rdev, os.O_WRONLY)
    except OSError as e:
        _darwin_try_remount_disk(d)
        hint = ""
        if e.errno in (errno.EACCES, errno.EPERM):
            hint = (
                " Root privileges are required to write to the raw SD device. "
                "Approve the macOS password prompt, or run this step from an admin account."
            )
        return False, f"Could not open {rdev}: {e}.{hint}"

    ok, err = False, ""
    try:
        ok, err = _sparse_copy_image_to_fd(
            fd,
            image_path,
            image_size,
            cap_bytes=cap_bytes,
            progress_callback=progress_callback,
            progress_file_path=progress_file_path,
            should_cancel=should_cancel,
            device_label=rdev,
            volume_lock_warnings="",
        )
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    if ok:
        _emit_disk_write_progress(
            image_size,
            image_size,
            "SD card write complete.",
            progress_callback=progress_callback,
            progress_file_path=progress_file_path,
        )
        # Remount asynchronously so the dialog closes immediately; Finder will
        # show the card's volumes once the background remount finishes.
        _darwin_remount_async(d)
    else:
        _emit_disk_write_progress(
            0,
            image_size,
            "Write failed — remounting disk…",
            progress_callback=progress_callback,
            progress_file_path=progress_file_path,
        )
        _darwin_try_remount_disk(d)

    if not ok:
        return False, err or "Write failed."
    return True, ""


def _write_image_via_darwin_sudo_dd(
    image_path: Path,
    bsd_whole_disk: str,
    *,
    image_size: int,
    cap_bytes: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, str]:
    """Elevated raw write using ``sudo -S /bin/dd`` as a direct child process.

    Previous approach — ``do shell script … with administrator privileges`` — spawns
    the shell via ``security_authtrampoline`` (a system daemon), which severs the macOS
    TCC responsible-process chain.  macOS 15 therefore cannot associate the privileged
    ``dd`` with Vintage Radio.app, so Full Disk Access on the app has no effect.

    This approach obtains the admin password from a plain ``osascript display dialog``
    (no privilege escalation at all), then pipes the password to ``sudo -S /bin/dd``
    launched as a **direct child** of our Python process.  The kernel audit chain
    becomes ``dd → sudo → Python → Vintage Radio.app``, and TCC correctly attributes
    the raw-device open to the app.  As long as Full Disk Access is granted to
    Vintage Radio.app in System Settings → Privacy & Security, the write succeeds.
    """
    d = darwin_normalize_bsd_whole_disk(bsd_whole_disk)
    if not d:
        return False, f"Invalid disk identifier: {bsd_whole_disk!r}"

    raw_dev = f"/dev/r{d}"

    # --- Step 1: obtain admin password via a plain dialog (no privilege change) -------
    if progress_callback:
        progress_callback(0, image_size, "Requesting admin password to write to the SD card…")

    try:
        r_pwd = subprocess.run(
            [
                "osascript",
                "-e",
                (
                    'display dialog "Vintage Radio needs your administrator password '
                    'to write to the SD card." '
                    'default answer "" with hidden answer '
                    'buttons {"Cancel", "OK"} default button "OK" '
                    'with title "Write SD Card"'
                ),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for the password dialog."
    except OSError as exc:
        return False, f"Could not show password dialog: {exc}"

    if r_pwd.returncode != 0:
        err_text = (r_pwd.stderr or "").strip()
        if "User canceled" in err_text or "(-128)" in err_text:
            return False, "Cancelled: password prompt was dismissed."
        return False, f"Password dialog failed (exit {r_pwd.returncode})."

    # AppleScript result format: "button returned:OK, text returned:<password>"
    # Split on the fixed separator; password may contain commas/colons.
    raw_out = (r_pwd.stdout or "").strip()
    parts = raw_out.split(", text returned:", 1)
    password = parts[1] if len(parts) > 1 else ""

    # --- Step 2: unmount volumes and write via sudo -S dd ----------------------------
    _darwin_unmount_disk(d)

    if progress_callback:
        progress_callback(
            0,
            image_size,
            "Writing full SD card image (entire card capacity — not just your tracks; "
            "this step can take many minutes)…",
        )

    # Run dd entirely on the Qt worker thread (no nested ``threading.Thread``).  A
    # background ``Thread`` + ``communicate`` alongside ``done_event.wait`` caused
    # races with dialog teardown / ``QThread::quit`` (stuck UI, ``Fatal Python error:
    # Aborted`` from Qt when the progress dialog closed while ``dd`` was still running).
    try:
        _dd_cmd = [
            "sudo", "-S", "-k", "--", "/bin/dd",
            f"if={image_path.resolve()}",
            f"of={raw_dev}",
            "bs=1m",
        ]
        if cap_bytes is not None and cap_bytes < image_size:
            # Limit dd to the physical disk capacity (1 MiB block alignment).
            _dd_cmd.append(f"count={cap_bytes // (1024 * 1024)}")
        proc = subprocess.Popen(
            _dd_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _sd_log("dd cmd: " + " ".join(shlex.quote(c) for c in _dd_cmd))
    except OSError as exc:
        _darwin_try_remount_disk(d)
        return False, f"Could not start dd: {exc}"

    try:
        if proc.stdin:
            proc.stdin.write(f"{password}\n".encode())
            proc.stdin.flush()
            proc.stdin.close()
    except BrokenPipeError:
        pass
    except OSError:
        pass

    # Cap estimated progress at 90 % of image_size.  dd does not report per-block
    # progress; we estimate from elapsed time at ~20 MB/s (conservative — real
    # USB 2.0 SD card writers typically do 10–30 MB/s).  Capping at 90 % ensures
    # the bar never LOOKS done while dd is still writing; it jumps to 100 % only
    # when dd actually exits with rc=0.
    _BYTES_PER_SEC_ESTIMATE = 20 * 1024 * 1024
    _MAX_ESTIMATE = int(image_size * 0.90)
    _start = time.time()
    _deadline = _start + 7200.0
    cancelled = False

    _sd_log(f"dd started: image={image_path.name} size={image_size} dev={raw_dev} cap_bytes={cap_bytes}")

    stderr_acc = bytearray()
    while proc.poll() is None:
        _darwin_nonblocking_pipe_drain(proc.stderr, stderr_acc)
        if time.time() > _deadline:
            proc.kill()
            try:
                proc.wait(timeout=120)
            except OSError:
                pass
            _sd_log("dd timed out (2 hours)")
            _darwin_try_remount_disk(d)
            return False, "Write timed out (2 hours)."
        if should_cancel and should_cancel():
            cancelled = True
            proc.kill()
            try:
                proc.wait(timeout=120)
            except OSError:
                pass
            _sd_log("dd cancelled by user")
            break
        if progress_callback and image_size > 0:
            elapsed = time.time() - _start
            est = min(int(elapsed * _BYTES_PER_SEC_ESTIMATE), _MAX_ESTIMATE)
            progress_callback(
                est,
                image_size,
                "Writing to SD card (progress is estimated — bar will jump to 100 % "
                "when dd confirms completion): "
                f"~{est // (1024 * 1024)} / {image_size // (1024 * 1024)} MiB …",
            )
        time.sleep(0.5)

    stdout_b = b""
    stderr_b = b""
    try:
        if proc.stdout:
            stdout_b = proc.stdout.read() or b""
        if proc.stderr:
            _darwin_nonblocking_pipe_drain(proc.stderr, stderr_acc)
            try:
                tail = proc.stderr.read() or b""
            except OSError:
                tail = b""
            stderr_b = bytes(stderr_acc) + tail
    except OSError:
        stderr_b = bytes(stderr_acc)

    if cancelled:
        if progress_callback:
            progress_callback(0, image_size, "Write cancelled — remounting disk…")
        _darwin_try_remount_disk(d)
        return False, "Cancelled: SD write was stopped."

    rc = proc.returncode if proc.returncode is not None else -1
    out = stdout_b.decode(errors="replace").strip()
    raw_err = stderr_b.decode(errors="replace")
    err_lines = [
        ln
        for ln in raw_err.splitlines()
        if not ln.startswith("Password:") and "pkg_resources" not in ln
    ]
    err_txt = "\n".join(err_lines).strip()

    if rc == 0:
        _sd_log(f"dd complete: rc=0 elapsed={time.time() - _start:.0f}s")
        if progress_callback:
            progress_callback(image_size, image_size, "SD card write complete.")
        _darwin_remount_async(d)
        return True, ""

    _log_err = err_txt if len(err_txt) <= 12000 else (err_txt[:12000] + "\n… (stderr truncated)")
    _sd_log(f"dd failed: rc={rc} stderr={_log_err!r}")
    if progress_callback:
        progress_callback(0, image_size, "Write failed — remounting disk…")
    _darwin_try_remount_disk(d)

    if "incorrect password" in err_txt.lower() or "try again" in err_txt.lower():
        return False, "Incorrect password — please try again."
    if "Operation not permitted" in err_txt or "Operation not permitted" in out:
        return (
            False,
            f"{DARWIN_FDA_REQUIRED_MARKER}\n"
            "Vintage Radio needs Full Disk Access to write to the SD card.\n\n"
            "Even though the password was accepted, macOS blocked raw disk "
            "access because Vintage Radio does not have Full Disk Access.\n\n"
            "How to fix:\n"
            "  1. Open System Settings \u2192 Privacy & Security \u2192 Full Disk Access\n"
            "  2. Click + and add Vintage Radio (from /Applications)\n"
            "  3. Toggle it on, then quit and relaunch Vintage Radio\n"
            "  4. Try the SD card write again",
        )

    detail = err_txt or out
    body = f"Disk write failed (dd exit {rc}).\n{detail[:2000]}" if detail else f"Disk write failed (dd exit {rc})."

    target = cap_bytes if cap_bytes is not None else image_size
    wrote = dd_stderr_records_out_bytes(err_txt)
    if wrote is not None and target > 0 and wrote < int(target * 0.95):
        body += (
            "\n\nThe copy stopped before reaching the full size. Common causes: loose USB "
            "connection or hub power limits, a flaky SD reader, thermal disconnect, or a "
            "counterfeit card that reports more capacity than it can actually store. Try "
            "another port or cable, avoid long passive hubs, and retry."
        )

    return (False, body)


def write_image_to_physical_disk_darwin(
    image_path: Path,
    bsd_whole_disk: str,
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, str]:
    """Write *image_path* to whole disk ``diskN`` on macOS (raw ``/dev/rdiskN``).

    Strategy (in order):

    1. **Direct Python write** — if Full Disk Access is granted to Vintage Radio in
       System Settings → Privacy & Security, the app can open ``/dev/rdiskN`` directly
       without root.  This is the preferred path: it uses the same sparse-aware,
       per-block progress tracking as the Windows path and is typically 2–4× faster
       than piping through ``dd`` because zero chunks in the image are *seeked over*
       rather than written.

    2. **``sudo -S /bin/dd`` fallback** — used only when the direct open fails with
       EPERM (Full Disk Access not yet granted).  Shows a password dialog and runs
       ``dd`` as a direct child process so macOS TCC can trace the open back to the
       app.  Progress is time-estimated only.
    """
    if platform.system() != "Darwin":
        return False, "Internal error: Darwin disk write called on a non-macOS system."

    image_path = Path(image_path).resolve()
    if not image_path.is_file():
        return False, f"Image file not found: {image_path}"

    image_size = image_path.stat().st_size
    if image_size <= 0:
        return False, "Image file is empty."

    d = darwin_normalize_bsd_whole_disk(bsd_whole_disk)
    if not d:
        return False, f"Invalid whole-disk identifier: {bsd_whole_disk!r}"

    disk_size = darwin_get_disk_size_bytes(d)
    cap_bytes: Optional[int] = None
    if disk_size is not None and image_size > disk_size:
        overage = image_size - disk_size
        tolerance = max(256 * 1024 * 1024, int(disk_size * 0.02))  # 256 MiB or 2%
        if overage > tolerance:
            return (
                False,
                f"Image ({image_size} bytes) is larger than the selected disk "
                f"({disk_size} bytes) by {overage // (1024 * 1024)} MiB — too much to "
                "trim safely. Choose a larger SD card or rebuild the image.",
            )
        # Small overage (manufacturing tolerance between same-nominal-size cards):
        # cap the write at disk_size bytes.  The trailing FAT32 free space is not
        # written; the filesystem remains fully functional for DFPlayer use.
        cap_bytes = disk_size

    # --- Preferred path: direct Python write (requires Full Disk Access on the app) --
    # Probe the raw device before unmounting — if FDA is not granted we get EPERM here
    # and can fall back to sudo-dd without having already disturbed the filesystem.
    rdev = darwin_rdisk_path(d)
    try:
        probe_fd = os.open(rdev, os.O_WRONLY)
        os.close(probe_fd)
        # FDA available — use the full direct-write impl (sparse-aware, real progress).
        return _write_image_to_darwin_disk_impl(
            image_path,
            d,
            cap_bytes=cap_bytes,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            progress_file_path=None,
        )
    except OSError as _probe_err:
        if _probe_err.errno not in (errno.EACCES, errno.EPERM):
            # Unexpected error (e.g. device busy) — surface it directly.
            _darwin_try_remount_disk(d)
            return False, f"Could not open {rdev}: {_probe_err}"
        # EPERM / EACCES → FDA not granted; fall through to sudo-dd.

    # --- Fallback: sudo -S dd (estimated progress, no sparse optimisation) -----------
    return _write_image_via_darwin_sudo_dd(
        image_path,
        d,
        image_size=image_size,
        cap_bytes=cap_bytes,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    )


def format_disk_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / (1024**3):.1f} GB"
    if n >= 1024**2:
        return f"{n / (1024**2):.0f} MB"
    return f"{n} bytes"
