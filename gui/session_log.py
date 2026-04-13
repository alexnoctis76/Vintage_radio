"""
Session logging for the Vintage Radio GUI application.

Creates a timestamped log file in the system temp directory that captures:
- All print() output (stdout/stderr)
- Python logging messages
- Unhandled exceptions with tracebacks
- GUI debug events

Log files are stored in:
  %TEMP%/VintageRadio/       (Windows)
  $TMPDIR/VintageRadio/      (macOS: often /var/folders/.../T/VintageRadio/)
  /tmp/VintageRadio/        (Linux)

Old log files are automatically cleaned up (keeps last 10 sessions).
"""

from __future__ import annotations

import atexit
import datetime
import logging
import os
import sys
import tempfile
import threading
import traceback
from io import StringIO
from pathlib import Path
from typing import Optional


def format_session_timestamp(now: Optional[datetime.datetime] = None) -> str:
    """Wall time with milliseconds: ``HH:MM:SS:mmm`` (colon before ms, no duplicate brackets)."""
    t = now or datetime.datetime.now()
    return t.strftime("%H:%M:%S") + f":{t.microsecond // 1000:03d}"


# ── Module-level state ──────────────────────────────────────────
_session_log_path: Optional[Path] = None
_original_stdout = sys.stdout
_original_stderr = sys.stderr
_file_handler: Optional[logging.FileHandler] = None


def get_log_dir() -> Path:
    """Return the directory where session logs are stored."""
    log_dir = Path(tempfile.gettempdir()) / "VintageRadio"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_session_log_path() -> Optional[Path]:
    """Return the path of the current session's log file (None if not initialized)."""
    return _session_log_path


def log_gui_error(title: str, message: str) -> None:
    """Log a GUI-visible failure (task dialog, message box) to the session log file."""
    if not _session_log_path:
        return
    ts = format_session_timestamp()
    block = f"{title}\n{message}"
    try:
        with open(_session_log_path, "a", encoding="utf-8", newline="\n") as f:
            for line in block.splitlines() or [block]:
                f.write(f"{ts} [GUI-ERROR] {line}\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass


def install_messagebox_session_logging() -> None:
    """Route QMessageBox.critical / .warning through the session log (GUI-ERROR).

    Call once after init_session_logging() so user-visible warnings and errors
    are always captured even when no TaskProgressDialog is involved.
    """
    from PyQt6.QtWidgets import QMessageBox

    _orig_critical = QMessageBox.critical
    _orig_warning = QMessageBox.warning

    @staticmethod
    def critical(parent, title, text, *args, **kwargs):  # type: ignore[no-untyped-def]
        log_gui_error(str(title), str(text))
        return _orig_critical(parent, title, text, *args, **kwargs)

    @staticmethod
    def warning(parent, title, text, *args, **kwargs):  # type: ignore[no-untyped-def]
        log_gui_error(str(title), str(text))
        return _orig_warning(parent, title, text, *args, **kwargs)

    QMessageBox.critical = critical  # type: ignore[assignment]
    QMessageBox.warning = warning  # type: ignore[assignment]


def write_session_line(message: str, *, prefix: str = "SETUP") -> None:
    """Append one line directly to the session log file and flush + fsync.

    Use this for crash-prone paths (e.g. Setup Device / mpremote). Unlike ``print()``,
    this does not depend on ``sys.stdout`` (PyInstaller windowed builds, torn TeeWriter).
    Survives until the OS buffers are lost (hard kill / native crash may still omit lines).
    """
    if not _session_log_path:
        return
    try:
        ts = format_session_timestamp()
        line = f"{ts} [{prefix}] {message}\n"
        with open(_session_log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
    except Exception:
        pass


def init_session_logging(app_version: str = "dev") -> Path:
    """
    Initialize session logging. Call once at application start.

    - Creates a timestamped log file
    - Redirects stdout/stderr to both console AND log file
    - Sets up Python ``logging`` to write to the file
    - Installs a global exception hook
    - Cleans up old session logs (keeps last 10)

    Returns the path to the new log file.
    """
    global _session_log_path, _file_handler

    log_dir = get_log_dir()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _session_log_path = log_dir / f"vintage_radio_{timestamp}.log"

    # ── Open log file ────────────────────────────────────────
    log_file = open(_session_log_path, "w", encoding="utf-8", buffering=1)  # line-buffered

    # Write header
    log_file.write(f"{'='*72}\n")
    log_file.write(f"  Vintage Radio — Session Log\n")
    log_file.write(f"  Version : {app_version}\n")
    log_file.write(f"  Started : {datetime.datetime.now().isoformat()}\n")
    log_file.write(f"  Platform: {sys.platform} / Python {sys.version}\n")
    log_file.write(f"  Log file: {_session_log_path}\n")
    log_file.write(f"{'='*72}\n\n")
    log_file.flush()

    # ── Tee stdout / stderr ──────────────────────────────────
    sys.stdout = _TeeWriter(_original_stdout, log_file, prefix="")
    sys.stderr = _TeeWriter(_original_stderr, log_file, prefix="[STDERR] ")

    # ── Python logging → file ────────────────────────────────
    _file_handler = logging.FileHandler(str(_session_log_path), encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(_file_handler)
    root_logger.setLevel(logging.DEBUG)

    # ── Optional: verbose console logging ────────────────────
    # Set VINTAGE_RADIO_VERBOSE=1 (or true/yes) to see DEBUG logs in the terminal as well as in the file.
    if os.environ.get("VINTAGE_RADIO_VERBOSE", "").strip().lower() in ("1", "true", "yes"):
        console_handler = logging.StreamHandler(_original_stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root_logger.addHandler(console_handler)
        print("Verbose debug logging enabled (VINTAGE_RADIO_VERBOSE)")

    # ── Global exception hook ────────────────────────────────
    _original_excepthook = sys.excepthook

    def _exception_hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            log_file.write(f"\n{'!'*72}\n")
            log_file.write(f"UNHANDLED EXCEPTION at {datetime.datetime.now().isoformat()}\n")
            log_file.write(msg)
            log_file.write(f"{'!'*72}\n\n")
            log_file.flush()
        except Exception:
            pass
        # Still call the original hook (prints to stderr / crash dialog)
        _original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _exception_hook

    # ── Thread exceptions (Python 3.8+) — otherwise silent in GUI threads ──
    if hasattr(threading, "excepthook"):
        _orig_thread_excepthook = threading.excepthook

        def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
            try:
                msg = "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                )
                log_file.write(f"\n{'!'*72}\n")
                log_file.write(
                    f"THREAD EXCEPTION (thread={args.thread!r}) at "
                    f"{datetime.datetime.now().isoformat()}\n"
                )
                log_file.write(msg)
                log_file.write(f"{'!'*72}\n\n")
                log_file.flush()
            except Exception:
                pass
            _orig_thread_excepthook(args)

        threading.excepthook = _thread_excepthook

    # ── Cleanup on exit ──────────────────────────────────────
    def _on_exit():
        try:
            end_msg = f"\n{'='*72}\n  Session ended: {datetime.datetime.now().isoformat()}\n{'='*72}\n"
            log_file.write(end_msg)
            log_file.flush()
            log_file.close()
        except Exception:
            pass

    atexit.register(_on_exit)

    # ── Purge old logs (keep last 10) ────────────────────────
    _cleanup_old_logs(log_dir, keep=10)

    print(f"Session log: {_session_log_path}")

    # Dump Python stack on fault (helps when a C extension or embedded code aborts).
    try:
        import faulthandler

        faulthandler.enable(file=log_file, all_threads=True)
    except Exception:
        pass

    # Windows: optional minidump on native fatal exceptions (see gui/windows_crash_dump.py).
    try:
        if sys.platform == "win32":
            from .windows_crash_dump import install_windows_minidump_handler

            install_windows_minidump_handler(crash_dir=log_dir / "crash_dumps")
    except Exception:
        pass

    return _session_log_path


def _cleanup_old_logs(log_dir: Path, keep: int = 10) -> None:
    """Delete oldest log files, keeping the most recent *keep* files."""
    try:
        logs = sorted(
            log_dir.glob("vintage_radio_*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in logs[keep:]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:
        pass


class _TeeWriter:
    """
    File-like wrapper that writes to both a console stream and a log file.
    Thread-safe enough for typical Qt usage (GIL-protected writes).
    """

    def __init__(self, console, logfile, prefix: str = ""):
        self._console = console
        self._logfile = logfile
        self._prefix = prefix

    def write(self, text: str) -> int:
        if not text:
            return 0
        # Write to console (original stdout/stderr)
        try:
            self._console.write(text)
        except Exception:
            pass
        # Write to log file with optional prefix (for stderr lines)
        try:
            if self._prefix and text.strip():
                # Prefix each non-empty line
                for line in text.splitlines(True):
                    if line.strip():
                        self._logfile.write(f"{self._prefix}{line}")
                    else:
                        self._logfile.write(line)
            else:
                self._logfile.write(text)
            self._logfile.flush()
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            self._console.flush()
        except Exception:
            pass
        try:
            self._logfile.flush()
        except Exception:
            pass

    def fileno(self):
        return self._console.fileno()

    # Forward any other attribute access to the console stream
    def __getattr__(self, name):
        return getattr(self._console, name)

