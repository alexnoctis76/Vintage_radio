"""Path helpers for resources and project root. Works from source and when frozen (PyInstaller)."""

import os
from pathlib import Path
import sys


def _frozen_base() -> Path | None:
    """Return base path when running as PyInstaller bundle, else None."""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    return None


def gui_dir() -> Path:
    """Base path for the gui package (use for gui/resources, etc.)."""
    base = _frozen_base()
    if base is not None:
        return base / "gui"
    return Path(__file__).resolve().parent


def project_root() -> Path:
    """Project root (parent of gui when not frozen; bundle root when frozen)."""
    base = _frozen_base()
    if base is not None:
        return base
    return Path(__file__).resolve().parents[1]


def app_data_dir() -> Path:
    """Writable directory for db, backups.

    When running from source: project root.
    When frozen (packaged): on macOS uses ~/Library/Application Support/Vintage Radio/
    so the app bundle is not written to (avoids read-only or replacement issues).
    On Windows/Linux frozen apps use the directory containing the executable.
    """
    if not getattr(sys, "frozen", False):
        return project_root()
    try:
        import platform
        if platform.system() == "Darwin":
            import platformdirs
            path = Path(platformdirs.user_data_dir(appname="Vintage Radio", roaming=False))
            path.mkdir(parents=True, exist_ok=True)
            return path
    except Exception:
        pass
    return Path(sys.executable).resolve().parent


def subprocess_env() -> dict:
    """Environment for subprocess calls. When frozen on macOS, PATH is extended
    so tools like ffmpeg (e.g. from Homebrew) are found when the app is launched
    from Finder (which often has a minimal PATH).
    """
    if not getattr(sys, "frozen", False):
        return os.environ
    try:
        import platform
        if platform.system() == "Darwin":
            extra = os.pathsep.join(["/usr/local/bin", "/opt/homebrew/bin"])
            path = os.environ.get("PATH", "")
            if extra not in path:
                return {**os.environ, "PATH": extra + os.pathsep + path}
    except Exception:
        pass
    return os.environ


def resource_path(*parts: str) -> Path:
    """Path to a file under gui/resources."""
    return gui_dir() / "resources" / "/".join(parts)
