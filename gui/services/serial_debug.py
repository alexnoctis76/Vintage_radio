"""Serial debug utility helpers shared by device-facing GUI modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def serial_io_errno(exc: BaseException) -> Optional[int]:
    """Best-effort errno from OSError / pyserial exceptions."""
    if isinstance(exc, OSError):
        return exc.errno
    err = getattr(exc, "errno", None)
    if isinstance(err, int):
        return err
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def append_session_ndjson_from_vrdbg_line(line: str) -> None:
    """Mirror Pico ``#VRDBG {...}`` lines into the workspace debug log."""
    s = line.strip()
    if not s.startswith("#VRDBG "):
        return
    try:
        payload = json.loads(s[7:])
    except json.JSONDecodeError:
        return
    log_path = Path(__file__).resolve().parent.parent.parent / "debug-e8231e.log"
    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def is_recoverable_usb_serial_error(exc: BaseException) -> bool:
    """True when the USB CDC handle is stale but likely recoverable."""
    eno = serial_io_errno(exc)
    if eno == 6:  # ENXIO (macOS/BSD)
        return True
    if eno == 19:  # ENODEV
        return True
    msg = str(exc).lower()
    return "device not configured" in msg or "could not configure port" in msg
