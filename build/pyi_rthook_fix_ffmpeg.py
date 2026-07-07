# PyInstaller runtime hook — set executable bit on bundled imageio-ffmpeg binary
#
# PyInstaller does not always preserve POSIX execute permission bits when
# extracting onedir payloads (especially inside a macOS .app bundle).
# This hook runs at startup so imageio_ffmpeg.get_ffmpeg_exe() and
# resource_paths.resolve_ffmpeg_executable() both find an executable file.
import os
import stat
import sys
from pathlib import Path

_FROZEN_ROOT = Path(getattr(sys, "_MEIPASS", ""))

if _FROZEN_ROOT.is_dir():
    _BIN_DIR = _FROZEN_ROOT / "imageio_ffmpeg" / "binaries"
    if _BIN_DIR.is_dir():
        for _p in _BIN_DIR.iterdir():
            if _p.is_file():
                try:
                    _mode = _p.stat().st_mode
                    if _mode & stat.S_IXUSR == 0:
                        _p.chmod(_mode | stat.S_IRWXU)
                except OSError:
                    pass
