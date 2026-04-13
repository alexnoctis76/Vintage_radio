"""Elevated one-shot raw disk write (invoked via UAC prompt).

Usage (from project root, same interpreter as the GUI):

  python -m gui.sd_disk_write_helper <image_path> <disk_number> [<diagnostic_log_path>]

``disk_number`` is the Windows disk index (same as PhysicalDriveN).
If ``diagnostic_log_path`` is given, stdout/stderr are dup2'd to that file so
imports and tracebacks survive broken OS-level fds from elevated subprocesses.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

_ELEVATED_STDIO_KEEP: object | None = None


def parse_sd_disk_write_cli_args(
    argv: List[str],
    *,
    flag: Optional[str] = "--vr-write-sd-disk",
) -> Optional[Tuple[Path, int, Optional[Path], Optional[Path]]]:
    r"""Parse elevated raw-disk write CLI arguments robustly.

    **Frozen exe:** ``--vr-write-sd-disk <image> <disk> [<log>] [<progress.json>]``

    **Dev:** ``python -m gui.sd_disk_write_helper <image> <disk> [<log>] [<progress.json>]`` (no flag).

    ``<image>`` may span **multiple** ``argv`` entries when the path contains spaces
    (e.g. ``...\Vintage Radio\...``) because ``Start-Process / CreateProcess``
    tokenisation splits on spaces when arguments are not properly quoted.  We parse
    from the **right**: optional ``*.progress.json``, optional ``*.log``, then a
    numeric disk index, then join the remainder as the image path.
    """
    if flag is not None:
        if len(argv) < 4 or argv[1] != flag:
            return None
        tail = argv[2:]
    else:
        if len(argv) < 3:
            return None
        tail = argv[1:]
    if len(tail) < 2:
        return None
    progress_path: Optional[Path] = None
    log_path: Optional[Path] = None
    if len(tail) >= 2 and tail[-1].lower().endswith(".progress.json"):
        progress_path = Path(tail[-1])
        tail = tail[:-1]
    if len(tail) >= 3 and tail[-1].lower().endswith(".log"):
        log_path = Path(tail[-1])
        tail = tail[:-1]
    if len(tail) < 2:
        return None
    disk_str = tail[-1]
    if not disk_str.isdigit():
        return None
    disk = int(disk_str)
    img = Path(" ".join(tail[:-1]))
    return img, disk, log_path, progress_path


def redirect_stdio_for_elevated_disk_child(log_path: Optional[Path]) -> None:
    """Repoint OS fds 1 and 2 before importing ``gui`` (fixes errno 9 / EBADF).

    ``Start-Process -Verb RunAs`` can leave the child with invalid default
    stdout/stderr handles; Python and native code then fail on first write.
    """
    global _ELEVATED_STDIO_KEEP
    try:
        if log_path is not None:
            f = open(log_path, "w", encoding="utf-8", errors="replace", newline="\n")
        else:
            f = open(os.devnull, "w", encoding="utf-8", errors="replace", newline="\n")
        fd = f.fileno()
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        _ELEVATED_STDIO_KEEP = f
        sys.stdout = f
        sys.stderr = f
    except OSError as exc:
        if log_path is not None:
            try:
                with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                    lf.write(f"\n[stdio redirect failed: {exc}]\n")
            except OSError:
                pass


def main() -> int:
    parsed = parse_sd_disk_write_cli_args(sys.argv, flag=None)
    if parsed is None:
        redirect_stdio_for_elevated_disk_child(None)
        print(
            "Usage: python -m gui.sd_disk_write_helper "
            "<image_path> <disk_number> [<diagnostic_log_path> [<progress.json>]]",
            file=sys.stderr,
        )
        return 2

    img, disk, log_path, progress_path = parsed
    redirect_stdio_for_elevated_disk_child(log_path)

    try:
        from gui.sd_disk_image_flash import _write_image_to_physical_disk_impl

        ok, err = _write_image_to_physical_disk_impl(
            img,
            disk,
            progress_callback=None,
            should_cancel=None,
            try_offline_first=True,
            progress_file_path=progress_path,
        )
        if not ok:
            print(err or "Disk write failed.", file=sys.stderr)
            sys.stderr.flush()
            return 1
        return 0
    except Exception:
        traceback.print_exc()
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
