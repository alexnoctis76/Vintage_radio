"""
Windows-only: write a small minidump (.dmp) on native fatal exceptions (SEH).

Dumps: %TEMP%/VintageRadio/crash_dumps/

Enable / disable (Windows only):
  - Frozen (PyInstaller) exe: on by default.
  - From source: set VINTAGE_RADIO_MINIDUMP=1
  - To disable: VINTAGE_RADIO_MINIDUMP=0

Important: If the process exits "normally" (Python exception handled, sys.exit,
Qt close, etc.), Windows does NOT run the unhandled-exception filter — no .dmp.
Those cases are covered by the session log, sys.excepthook, and threading.excepthook.
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import Callable, Optional


def _minidump_enabled() -> bool:
    flag = os.environ.get("VINTAGE_RADIO_MINIDUMP", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return bool(getattr(sys, "frozen", False))


def _log_crash_line(message: str) -> None:
    try:
        from gui.session_log import write_session_line

        write_session_line(message, prefix="CRASH")
    except Exception:
        pass


def install_windows_minidump_handler(*, crash_dir: Path) -> None:
    """Register SetUnhandledExceptionFilter to write a .dmp file on native crash."""
    if sys.platform != "win32":
        return

    if not _minidump_enabled():
        _log_crash_line(
            "Minidumps off (run frozen .exe, or set VINTAGE_RADIO_MINIDUMP=1). "
            "Only native SEH faults create .dmp; normal app exit does not."
        )
        return

    try:
        import ctypes
        from ctypes import wintypes
    except Exception as e:
        _log_crash_line(f"Minidump init skipped (ctypes): {e}")
        return

    crash_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_old_dumps(crash_dir, keep=8)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Prefer System32 dbghelp (correct bitness for the OS)
    sys_root = os.environ.get("SystemRoot", r"C:\Windows")
    dbghelp_path = Path(sys_root) / "System32" / "dbghelp.dll"
    try:
        if dbghelp_path.is_file():
            dbghelp = ctypes.WinDLL(str(dbghelp_path))
        else:
            dbghelp = ctypes.WinDLL("dbghelp")
    except Exception as e:
        _log_crash_line(f"Could not load dbghelp.dll: {e}")
        return

    EXCEPTION_CONTINUE_SEARCH = 0
    GENERIC_WRITE = 0x40000000
    CREATE_ALWAYS = 2
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    MiniDumpNormal = 0x00000000

    class MINIDUMP_EXCEPTION_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("ThreadId", wintypes.DWORD),
            ("ExceptionPointers", ctypes.c_void_p),
            ("ClientPointers", wintypes.BOOL),
        ]

    MiniDumpWriteDump = dbghelp.MiniDumpWriteDump
    MiniDumpWriteDump.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(MINIDUMP_EXCEPTION_INFORMATION),
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    MiniDumpWriteDump.restype = wintypes.BOOL

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.GetLastError.restype = wintypes.DWORD

    prev_filter_holder: list[Optional[Callable]] = [None]

    @ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
    def unhandled_filter(exception_pointers: int) -> int:
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dump_path = crash_dir / f"vintage_radio_crash_{ts}.dmp"
            h_file = kernel32.CreateFileW(
                str(dump_path),
                GENERIC_WRITE,
                0,
                None,
                CREATE_ALWAYS,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if h_file == INVALID_HANDLE_VALUE or h_file is None:
                err = kernel32.GetLastError()
                try:
                    (crash_dir / "minidump_last_error.txt").write_text(
                        f"CreateFileW failed winerr={err}\npath={dump_path}\n",
                        encoding="utf-8",
                    )
                except OSError:
                    pass
                return EXCEPTION_CONTINUE_SEARCH

            ok = False
            try:
                proc = kernel32.GetCurrentProcess()
                pid = kernel32.GetCurrentProcessId()
                tid = kernel32.GetCurrentThreadId()
                mei = MINIDUMP_EXCEPTION_INFORMATION()
                mei.ThreadId = tid
                mei.ExceptionPointers = exception_pointers
                mei.ClientPointers = False
                ok = bool(
                    MiniDumpWriteDump(
                        proc,
                        pid,
                        h_file,
                        MiniDumpNormal,
                        ctypes.byref(mei),
                        None,
                        None,
                    )
                )
                if not ok:
                    err = kernel32.GetLastError()
                    try:
                        (crash_dir / "minidump_last_error.txt").write_text(
                            f"MiniDumpWriteDump returned FALSE winerr={err}\npath={dump_path}\n",
                            encoding="utf-8",
                        )
                    except OSError:
                        pass
            finally:
                kernel32.CloseHandle(h_file)

            if ok:
                _log_crash_line(f"Native crash minidump written: {dump_path}")
        except Exception as e:
            try:
                (crash_dir / "minidump_last_error.txt").write_text(
                    f"filter exception: {e!r}\n",
                    encoding="utf-8",
                )
            except OSError:
                pass

        prev = prev_filter_holder[0]
        if prev is not None:
            try:
                return int(prev(exception_pointers))
            except Exception:
                pass
        return EXCEPTION_CONTINUE_SEARCH

    try:
        SetUnhandledExceptionFilter = kernel32.SetUnhandledExceptionFilter
        SetUnhandledExceptionFilter.argtypes = [ctypes.c_void_p]
        SetUnhandledExceptionFilter.restype = ctypes.c_void_p
        prev = SetUnhandledExceptionFilter(unhandled_filter)
        if prev:
            prev_filter_holder[0] = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(prev)
        _log_crash_line(
            f"Native minidump handler registered -> {crash_dir} "
            f"(.dmp only if a low-level crash occurs; normal exit = no dump)"
        )
    except Exception as e:
        _log_crash_line(f"SetUnhandledExceptionFilter failed: {e}")


def _cleanup_old_dumps(crash_dir: Path, *, keep: int) -> None:
    try:
        dumps = sorted(
            crash_dir.glob("vintage_radio_crash_*.dmp"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in dumps[keep:]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError:
        pass
