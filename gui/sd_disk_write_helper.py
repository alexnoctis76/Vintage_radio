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
from typing import Optional

_ELEVATED_STDIO_KEEP: object | None = None


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
    if len(sys.argv) not in (3, 4):
        redirect_stdio_for_elevated_disk_child(None)
        print(
            "Usage: python -m gui.sd_disk_write_helper "
            "<image_path> <disk_number> [<diagnostic_log_path>]",
            file=sys.stderr,
        )
        return 2

    log_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    redirect_stdio_for_elevated_disk_child(log_path)

    try:
        img = Path(sys.argv[1])
        disk = int(sys.argv[2])
        from gui.sd_disk_image_flash import _write_image_to_physical_disk_impl

        ok, err = _write_image_to_physical_disk_impl(
            img,
            disk,
            progress_callback=None,
            should_cancel=None,
            try_offline_first=True,
        )
        if not ok:
            print(err, file=sys.stderr)
            return 1
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
