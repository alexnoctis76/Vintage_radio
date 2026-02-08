"""Path helpers for resources and project root. Works from source and when frozen (PyInstaller)."""

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
    """Writable directory for db, backups (exe dir when frozen, else project root)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_path(*parts: str) -> Path:
    """Path to a file under gui/resources."""
    return gui_dir() / "resources" / "/".join(parts)
