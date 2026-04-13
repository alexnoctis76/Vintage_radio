"""Write a raw disk image to a physical drive (experimental clean SD install).

Windows: ``\\\\.\\PhysicalDriveN`` with optional ``diskpart`` offline/online.
Other platforms: not implemented here — save the .img and use Etcher / dd.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import platform
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Chunk size for raw writes (bytes). Must be a multiple of 512 for some APIs.
_WRITE_CHUNK_BYTES = 1024 * 1024


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


def _write_image_via_uac_subprocess(image_path: Path, disk_number: int) -> Tuple[bool, str]:
    """Relaunch the write step with Administrator rights (UAC prompt).

    Elevated ``Start-Process`` does *not* inherit the PowerShell session's working
    directory; without ``-WorkingDirectory``, ``python -m gui....`` often runs from
    ``System32`` and fails to import the project (exit code 1, no visible output).
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
    try:
        diag_log.write_text("", encoding="utf-8")
    except OSError:
        pass
    lg = _ps_escape_single_quoted(str(diag_log))

    if frozen:
        arg_line = (
            "$p = Start-Process -FilePath $exe -ArgumentList @("
            "'--vr-write-sd-disk',$img,$disk,$logPath) "
            f"-WorkingDirectory '{wd}' "
            "-WindowStyle Hidden -Verb RunAs -Wait -PassThru"
        )
    else:
        arg_line = (
            "$p = Start-Process -FilePath $exe -ArgumentList @("
            "'-m','gui.sd_disk_write_helper',$img,$disk,$logPath) "
            f"-WorkingDirectory '{wd}' "
            "-WindowStyle Hidden -Verb RunAs -Wait -PassThru"
        )

    script_lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$logPath = '{lg}'",
        f"$exe = '{ex}'",
        f"$img = '{im}'",
        f"$disk = {disk}",
        arg_line,
        "exit $p.ExitCode",
    ]
    script = "\r\n".join(script_lines) + "\r\n"

    fd, ps1_path = tempfile.mkstemp(prefix="vr_sd_uac_", suffix=".ps1")
    try:
        os.close(fd)
        Path(ps1_path).write_text(script, encoding="utf-8-sig")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1_path],
            capture_output=True,
            text=True,
            timeout=3600 * 6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        ps_out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()

        child_blob = ""
        try:
            if diag_log.is_file():
                child_blob = diag_log.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pass

        if r.returncode == 0:
            try:
                diag_log.unlink(missing_ok=True)
            except OSError:
                pass
            return True, ""

        detail_parts = [f"PowerShell exit: {r.returncode}"]
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
        if r.returncode is not None and r.returncode != 0 and not child_blob and not ps_out:
            hint = (
                "\n\nIf you cancelled the Windows security prompt, run SD image sync again and approve it."
            )
        return (
            False,
            "Could not write to the SD card after the Administrator prompt.\n\n" + detail + hint,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for the elevated disk write to finish."
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
        return _write_image_via_uac_subprocess(image_path, disk_number)

    return _write_image_to_physical_disk_impl(
        image_path,
        disk_number,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
        try_offline_first=try_offline_first,
    )


def _write_image_to_physical_disk_impl(
    image_path: Path,
    disk_number: int,
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    try_offline_first: bool = True,
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

    def _write_fd(fd: int) -> Tuple[bool, str]:
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
                    chunk = img.read(_WRITE_CHUNK_BYTES)
                    if not chunk:
                        break
                    to_write = chunk
                    rem = len(to_write) % 512
                    if rem:
                        to_write = to_write + (b"\x00" * (512 - rem))
                    _write_raw_to_disk_fd(fd, to_write)
                    written_from_file += len(chunk)
                    if progress_callback:
                        progress_callback(
                            written_from_file,
                            image_size,
                            f"Writing to SD card ({written_from_file // (1024 * 1024)} MiB / "
                            f"{image_size // (1024 * 1024)} MiB)...",
                        )
        except OSError as e:
            parts = [f"Disk write to {device} failed: {e}"]
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
            if vol_warn:
                parts.append(f" Volume lock warnings: {vol_warn}")
            return False, "".join(parts)
        return True, ""

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
        ok, err = _write_fd(fd)
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


def format_disk_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / (1024**3):.1f} GB"
    if n >= 1024**2:
        return f"{n / (1024**2):.0f} MB"
    return f"{n} bytes"
