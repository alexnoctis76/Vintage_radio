"""
Windows: force-terminate Vintage Radio so PyInstaller can delete dist\\Vintage Radio.

Run automatically from vintage_radio.spec and build_windows.bat. Safe to run by hand.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def _kill_via_psutil() -> int:
    killed = 0
    try:
        import psutil
    except ImportError:
        return 0
    name_needle = "vintage radio.exe"
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = p.info or {}
            name = (info.get("name") or "").lower()
            exe = (info.get("exe") or "").lower()
            if name != name_needle and not exe.endswith("\\vintage radio.exe"):
                continue
            proc = psutil.Process(info["pid"])
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            try:
                proc.kill()
                killed += 1
            except psutil.Error:
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return killed


def _kill_via_taskkill() -> None:
    subprocess.run(
        ["taskkill", "/IM", "Vintage Radio.exe", "/F", "/T"],
        capture_output=True,
        timeout=45,
    )


def _kill_dev_python_vintage_radio() -> None:
    """Source runs (python run_vintage_radio.py) also lock dist\\_internal DLLs if cwd is there."""
    try:
        import psutil
    except ImportError:
        return
    markers = (
        "run_vintage_radio.py",
        "run_vintage_radio",
        "-m gui.radio_manager",
        "gui\\radio_manager.py",
        "gui/radio_manager.py",
    )
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (p.info.get("name") or "").lower()
            if name not in ("python.exe", "pythonw.exe"):
                continue
            cmd = p.info.get("cmdline") or []
            flat = " ".join(cmd).lower()
            if not any(m in flat for m in markers):
                continue
            proc = psutil.Process(p.info["pid"])
            if proc.pid == os.getpid():
                continue
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            try:
                proc.kill()
            except psutil.Error:
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass


def main() -> int:
    if sys.platform != "win32":
        return 0
    # Several rounds: handles stubborn children and slow handle release
    for i in range(5):
        _kill_dev_python_vintage_radio()
        _kill_via_psutil()
        _kill_via_taskkill()
        time.sleep(0.6 if i < 4 else 1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
