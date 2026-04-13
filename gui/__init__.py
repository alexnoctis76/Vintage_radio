"""Vintage Radio Music Manager GUI Package.

Heavy dependencies (mutagen, psutil, etc.) are loaded lazily so
``from gui.radio_manager import run_app`` only pulls them when ``radio_manager`` loads,
and ``import gui`` alone does not require the full stack.
"""

from __future__ import annotations

__version__ = "v0.2.1-beta"

__all__ = [
    "DatabaseManager",
    "SDManager",
    "compute_file_hash",
    "extract_metadata",
    "file_matches_metadata",
    "MainWindow",
    "run_app",
]


def __getattr__(name: str):
    if name in {"MainWindow", "run_app"}:
        from . import radio_manager

        return getattr(radio_manager, name)
    if name == "DatabaseManager":
        from .database import DatabaseManager

        return DatabaseManager
    if name == "SDManager":
        from .sd_manager import SDManager

        return SDManager
    if name in {"compute_file_hash", "extract_metadata", "file_matches_metadata"}:
        from . import audio_metadata

        return getattr(audio_metadata, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | {"__version__"})
